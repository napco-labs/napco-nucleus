"""
NAPCO Nucleus — SQLite-backed persistent memory.

Complements file-based artifacts (test report JSONs, requirement inbox
.txt files) with fast local memory that answers queries the filesystem
can't do efficiently:

    activity_logs      Append-only log of every meaningful agent action.
    requirements_seen  Every requirement ever ingested, normalized so
                       "Add SSO login" and "add sso login path" collapse.
                       Lets the agent skip duplicate research and ask
                       "have I seen this requirement before?" with FTS5.
    test_run_history   One row per test-suite run (pass/fail/duration/
                       PDF path/regressions). Drives trend + regression
                       analysis without re-scanning report JSONs.
    email_checkpoints  IMAP UIDVALIDITY + last_uid per mailbox (replaces
                       the old data/requirements/state.json email block).
    drive_processed    Idempotency index for Google Drive ingestion
                       (replaces data/requirements/drive-processed.json).

DB file: nucleus_memory.db (project root, committed to the repo so
memory travels with git clone). Path override via
NAPCO_NUCLEUS_DB_PATH env var.

All writes are best-effort — if the DB is locked or missing, callers
log and continue. Memory loss is acceptable; primary-flow loss is not.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

logger = logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DB_PATH = os.path.join(_HERE, "nucleus_memory.db")


def db_path() -> str:
    return os.environ.get("NAPCO_NUCLEUS_DB_PATH", _DEFAULT_DB_PATH)


_SCHEMA = """
-- Append-only action log.
CREATE TABLE IF NOT EXISTS activity_logs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name         TEXT,
    result            TEXT,
    technical_details TEXT,
    timestamp         DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_activity_task ON activity_logs(task_name);
CREATE INDEX IF NOT EXISTS idx_activity_ts   ON activity_logs(timestamp DESC);

-- Every requirement the agent has seen. Legal-style normalization
-- strips stopwords/punctuation so near-duplicate titles collapse.
CREATE TABLE IF NOT EXISTS requirements_seen (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT NOT NULL,
    title_norm        TEXT NOT NULL,
    source            TEXT NOT NULL,
    source_ref        TEXT NOT NULL DEFAULT '',
    summary           TEXT NOT NULL DEFAULT '',
    gitlab_issue_iid  INTEGER,
    gitlab_issue_url  TEXT,
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    touch_count       INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_requirements_norm_source
    ON requirements_seen(title_norm, source);

-- One row per suite-run.
CREATE TABLE IF NOT EXISTS test_run_history (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                    TEXT NOT NULL,
    task_name             TEXT NOT NULL,
    suite                 TEXT NOT NULL DEFAULT '',
    total                 INTEGER NOT NULL DEFAULT 0,
    passed                INTEGER NOT NULL DEFAULT 0,
    failed                INTEGER NOT NULL DEFAULT 0,
    skipped               INTEGER NOT NULL DEFAULT 0,
    duration_s            REAL,
    report_pdf_path       TEXT,
    regressions_detected  INTEGER NOT NULL DEFAULT 0,
    notes                 TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_test_run_task_ts ON test_run_history(task_name, ts DESC);

-- IMAP checkpoint per mailbox (replaces state.json email block).
CREATE TABLE IF NOT EXISTS email_checkpoints (
    mailbox_key  TEXT PRIMARY KEY,
    uidvalidity  TEXT,
    last_uid     TEXT,
    updated_at   TEXT NOT NULL
);

-- Google Drive idempotency (replaces drive-processed.json).
CREATE TABLE IF NOT EXISTS drive_processed (
    file_id       TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL,
    ingested_at   TEXT NOT NULL,
    output_path   TEXT NOT NULL DEFAULT ''
);

-- FTS5 over requirements_seen for fuzzy recall by title / summary.
CREATE VIRTUAL TABLE IF NOT EXISTS requirements_fts USING fts5(
    title, summary, source_ref,
    content='requirements_seen', content_rowid='id',
    tokenize='porter unicode61'
);

-- Sync triggers for the FTS table.
CREATE TRIGGER IF NOT EXISTS requirements_fts_ai
    AFTER INSERT ON requirements_seen BEGIN
    INSERT INTO requirements_fts(rowid, title, summary, source_ref)
    VALUES (new.id, new.title, new.summary, new.source_ref);
END;
CREATE TRIGGER IF NOT EXISTS requirements_fts_ad
    AFTER DELETE ON requirements_seen BEGIN
    INSERT INTO requirements_fts(requirements_fts, rowid, title, summary, source_ref)
    VALUES ('delete', old.id, old.title, old.summary, old.source_ref);
END;
CREATE TRIGGER IF NOT EXISTS requirements_fts_au
    AFTER UPDATE ON requirements_seen BEGIN
    INSERT INTO requirements_fts(requirements_fts, rowid, title, summary, source_ref)
    VALUES ('delete', old.id, old.title, old.summary, old.source_ref);
    INSERT INTO requirements_fts(rowid, title, summary, source_ref)
    VALUES (new.id, new.title, new.summary, new.source_ref);
END;
"""


_INIT_LOCK = threading.Lock()
_INITIALIZED: set[str] = set()


def init_db(path: str | None = None) -> str:
    """Create schema if missing. Idempotent. Returns the DB path used."""
    p = path or db_path()
    with _INIT_LOCK:
        if p in _INITIALIZED:
            return p
        with sqlite3.connect(p) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()
        _INITIALIZED.add(p)
    return p


@contextmanager
def _conn():
    path = init_db()
    c = sqlite3.connect(path, timeout=5.0)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_title(title: str) -> str:
    """Lowercase + strip punctuation + collapse whitespace. Used as
    the unique key on requirements_seen so spelling variants collapse."""
    n = (title or "").strip().lower()
    n = re.sub(r"[.,()\[\]{}:;\"']", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _fts_escape(query: str) -> str:
    q = (query or "").strip()
    return '""' if not q else '"' + q.replace('"', '""') + '"'


# ─── Writes: activity_logs ──────────────────────────────────────────
def log_activity(
    task_name: str,
    result: str = "",
    technical_details: Any = "",
) -> bool:
    """Append to activity_logs. technical_details accepts a dict/list
    (JSON-encoded) or a string. Best-effort."""
    if isinstance(technical_details, (dict, list)):
        details = json.dumps(technical_details, default=str)
    else:
        details = str(technical_details or "")
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO activity_logs (task_name, result, technical_details) "
                "VALUES (?, ?, ?)",
                (task_name, result, details),
            )
        return True
    except Exception as e:
        logger.warning("memory.log_activity failed: %s", e)
        return False


# ─── Writes: requirements_seen ──────────────────────────────────────
def remember_requirement(
    title: str,
    source: str,
    source_ref: str = "",
    summary: str = "",
    gitlab_issue_iid: int | None = None,
    gitlab_issue_url: str | None = None,
) -> bool:
    """Upsert into requirements_seen. Dedup key is (title_norm, source).
    Merges summary + GitLab link on repeat; increments touch_count."""
    if not title:
        return False
    norm = _norm_title(title)
    if not norm:
        return False
    ts = _now()
    try:
        with _conn() as c:
            existing = c.execute(
                "SELECT id, summary, gitlab_issue_iid, gitlab_issue_url "
                "FROM requirements_seen WHERE title_norm = ? AND source = ?",
                (norm, source),
            ).fetchone()
            if existing:
                c.execute(
                    "UPDATE requirements_seen SET "
                    "  last_seen = ?, "
                    "  touch_count = touch_count + 1, "
                    "  summary = CASE WHEN ? = '' THEN summary ELSE ? END, "
                    "  gitlab_issue_iid = COALESCE(?, gitlab_issue_iid), "
                    "  gitlab_issue_url = COALESCE(?, gitlab_issue_url) "
                    "WHERE id = ?",
                    (ts, summary, summary, gitlab_issue_iid,
                     gitlab_issue_url, existing["id"]),
                )
            else:
                c.execute(
                    "INSERT INTO requirements_seen "
                    "(title, title_norm, source, source_ref, summary, "
                    " gitlab_issue_iid, gitlab_issue_url, "
                    " first_seen, last_seen, touch_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (title.strip(), norm, source, source_ref, summary,
                     gitlab_issue_iid, gitlab_issue_url, ts, ts),
                )
        return True
    except Exception as e:
        logger.warning("memory.remember_requirement failed: %s", e)
        return False


# ─── Writes: test_run_history ───────────────────────────────────────
def log_test_run(
    task_name: str,
    total: int = 0,
    passed: int = 0,
    failed: int = 0,
    skipped: int = 0,
    duration_s: float | None = None,
    suite: str = "",
    report_pdf_path: str = "",
    regressions_detected: int = 0,
    notes: str = "",
) -> bool:
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO test_run_history "
                "(ts, task_name, suite, total, passed, failed, skipped, "
                " duration_s, report_pdf_path, regressions_detected, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_now(), task_name, suite, total, passed, failed, skipped,
                 duration_s, report_pdf_path, regressions_detected, notes),
            )
        return True
    except Exception as e:
        logger.warning("memory.log_test_run failed: %s", e)
        return False


# ─── Writes: email_checkpoints + drive_processed ────────────────────
def set_email_checkpoint(mailbox_key: str, uidvalidity: str | None,
                          last_uid: str | None) -> bool:
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO email_checkpoints (mailbox_key, uidvalidity, last_uid, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(mailbox_key) DO UPDATE SET "
                "  uidvalidity = excluded.uidvalidity, "
                "  last_uid = excluded.last_uid, "
                "  updated_at = excluded.updated_at",
                (mailbox_key, uidvalidity, last_uid, _now()),
            )
        return True
    except Exception as e:
        logger.warning("memory.set_email_checkpoint failed: %s", e)
        return False


def get_email_checkpoint(mailbox_key: str) -> dict | None:
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT * FROM email_checkpoints WHERE mailbox_key = ?",
                (mailbox_key,),
            ).fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.warning("memory.get_email_checkpoint failed: %s", e)
        return None


def mark_drive_processed(file_id: str, name: str, kind: str,
                         output_path: str = "") -> bool:
    try:
        with _conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO drive_processed "
                "(file_id, name, kind, ingested_at, output_path) "
                "VALUES (?, ?, ?, ?, ?)",
                (file_id, name, kind, _now(), output_path),
            )
        return True
    except Exception as e:
        logger.warning("memory.mark_drive_processed failed: %s", e)
        return False


def is_drive_processed(file_id: str) -> bool:
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT 1 FROM drive_processed WHERE file_id = ?", (file_id,),
            ).fetchone()
            return row is not None
    except Exception as e:
        logger.warning("memory.is_drive_processed failed: %s", e)
        return False


# ─── Reads ──────────────────────────────────────────────────────────
def recall_activity(
    task_name: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[dict]:
    limit = max(1, min(limit, 500))
    try:
        with _conn() as c:
            sql = "SELECT * FROM activity_logs WHERE 1=1"
            args: list[Any] = []
            if task_name:
                sql += " AND task_name = ?"
                args.append(task_name)
            if since:
                sql += " AND timestamp >= ?"
                args.append(since)
            sql += " ORDER BY timestamp DESC, id DESC LIMIT ?"
            args.append(limit)
            rows = c.execute(sql, args).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("memory.recall_activity failed: %s", e)
        return []


def search_requirements(query: str, limit: int = 20) -> list[dict]:
    limit = max(1, min(limit, 100))
    if not query or not query.strip():
        return []
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT r.id, r.title, r.source, r.source_ref, r.summary, "
                "       r.gitlab_issue_iid, r.gitlab_issue_url, "
                "       r.first_seen, r.last_seen, r.touch_count, "
                "       snippet(requirements_fts, 0, '[', ']', '...', 15) AS hit "
                "FROM requirements_fts "
                "JOIN requirements_seen r ON r.id = requirements_fts.rowid "
                "WHERE requirements_fts MATCH ? "
                "ORDER BY bm25(requirements_fts) LIMIT ?",
                (_fts_escape(query), limit),
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logger.warning("memory.search_requirements failed: %s", e)
        return []


def recall_test_runs(
    task_name: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict]:
    limit = max(1, min(limit, 200))
    try:
        with _conn() as c:
            sql = "SELECT * FROM test_run_history WHERE 1=1"
            args: list[Any] = []
            if task_name:
                sql += " AND task_name = ?"
                args.append(task_name)
            if since:
                sql += " AND ts >= ?"
                args.append(since)
            sql += " ORDER BY ts DESC, id DESC LIMIT ?"
            args.append(limit)
            rows = c.execute(sql, args).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("memory.recall_test_runs failed: %s", e)
        return []


def stats() -> dict:
    try:
        with _conn() as c:
            return {
                "db_path":            db_path(),
                "activity":           c.execute("SELECT COUNT(*) FROM activity_logs").fetchone()[0],
                "requirements":       c.execute("SELECT COUNT(*) FROM requirements_seen").fetchone()[0],
                "test_runs":          c.execute("SELECT COUNT(*) FROM test_run_history").fetchone()[0],
                "email_checkpoints":  c.execute("SELECT COUNT(*) FROM email_checkpoints").fetchone()[0],
                "drive_processed":    c.execute("SELECT COUNT(*) FROM drive_processed").fetchone()[0],
            }
    except Exception as e:
        logger.warning("memory.stats failed: %s", e)
        return {"error": str(e)}
