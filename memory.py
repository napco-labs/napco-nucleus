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
    -- OpenProject Work Package id + URL (renamed from gitlab_issue_*
    -- on 2026-04-28 when the backlog backend swapped to OpenProject).
    wp_id             INTEGER,
    wp_url            TEXT,
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    touch_count       INTEGER NOT NULL DEFAULT 1,
    -- Client-aware memory (added 2026-05-11): which client raised this?
    -- Inferred by the agent from the source (email sender domain, chat
    -- conversation, call client_name metadata). NULL for legacy rows.
    client_name       TEXT,
    -- Reply tracking (added 2026-05-11). Closed-loop verification:
    -- once a client replies to our verification email, the agent
    -- updates these fields per requirement. Lets you tell apart
    -- drafted-but-not-confirmed from confirmed.
    confirmation_status TEXT NOT NULL DEFAULT 'pending',  -- pending|confirmed|needs_change|rejected|unclear
    confirmation_at TEXT,
    confirmation_notes TEXT NOT NULL DEFAULT '',
    confirmation_email_uid TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_requirements_norm_source
    ON requirements_seen(title_norm, source);
-- idx_requirements_client_last is created inside _migrate_requirements_seen
-- so it runs AFTER the ALTER TABLE that adds the client_name column on
-- legacy DBs. On fresh installs the column is present in the CREATE
-- TABLE above, so the migration is a no-op except for the index.

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

-- Reviewer decisions per predicted requirement. Feeds the confidence
-- calibration curve: are the LLM's 0.90 predictions actually 90%
-- correct? Decisions: 'keep' (accepted as-is), 'edit' (kept after
-- editing), 'reject' (false positive — Titu would not have sent
-- this to the client). 'skip' is recorded too so analytics can
-- distinguish "no decision yet" from "deliberately deferred".
CREATE TABLE IF NOT EXISTS requirement_reviews (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    reviewed_at           TEXT NOT NULL,
    requirement_title     TEXT NOT NULL,
    predicted_confidence  REAL,
    source_refs_json      TEXT NOT NULL DEFAULT '[]',
    decision              TEXT NOT NULL,
    edited_title          TEXT,
    reviewer_notes        TEXT NOT NULL DEFAULT '',
    sidecar_path          TEXT NOT NULL DEFAULT '',
    docx_path             TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_reviews_reviewed_at
    ON requirement_reviews(reviewed_at DESC);
CREATE INDEX IF NOT EXISTS idx_reviews_decision_conf
    ON requirement_reviews(decision, predicted_confidence);

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
            _migrate_requirements_seen(conn)
            conn.commit()
        _INITIALIZED.add(p)
    return p


def _migrate_requirements_seen(conn: sqlite3.Connection) -> None:
    """Idempotent column-additions for tables that pre-date a feature.
    Only runs when the column is missing — safe to call on every init.

    Schema changes applied here:
      - 2026-05-11: requirements_seen.client_name (client-aware memory)
    """
    try:
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(requirements_seen)").fetchall()}
    except sqlite3.OperationalError:
        return  # table doesn't exist yet; CREATE TABLE in _SCHEMA handles it
    if "client_name" not in cols:
        conn.execute(
            "ALTER TABLE requirements_seen ADD COLUMN client_name TEXT")
    if "confirmation_status" not in cols:
        # pending | confirmed | needs_change | rejected | unclear
        conn.execute(
            "ALTER TABLE requirements_seen ADD COLUMN "
            "confirmation_status TEXT NOT NULL DEFAULT 'pending'")
    if "confirmation_at" not in cols:
        conn.execute(
            "ALTER TABLE requirements_seen ADD COLUMN confirmation_at TEXT")
    if "confirmation_notes" not in cols:
        conn.execute(
            "ALTER TABLE requirements_seen ADD COLUMN "
            "confirmation_notes TEXT NOT NULL DEFAULT ''")
    if "confirmation_email_uid" not in cols:
        conn.execute(
            "ALTER TABLE requirements_seen ADD COLUMN "
            "confirmation_email_uid TEXT")
    # Idempotent — runs on fresh installs (where the column is present
    # via the CREATE TABLE in _SCHEMA) and on migrated installs alike.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_requirements_client_last "
        "ON requirements_seen(client_name, last_seen DESC)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_requirements_confirmation "
        "ON requirements_seen(confirmation_status, client_name)")


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
    wp_id: int | None = None,
    wp_url: str | None = None,
    client_name: str | None = None,
) -> bool:
    """Upsert into requirements_seen. Dedup key is (title_norm, source).
    Merges summary + Work Package link on repeat; increments touch_count.

    `wp_id` / `wp_url` point at the OpenProject Work Package this
    requirement was published as (renamed from `gitlab_issue_iid` /
    `gitlab_issue_url` on 2026-04-28 when the backlog backend swapped
    from GitLab to OpenProject).

    `client_name` (added 2026-05-11): the client this requirement
    belongs to — inferred from the source channel (email sender domain,
    chat conversation, call metadata). Enables get_client_history()
    for context-aware identification on subsequent sessions."""
    if not title:
        return False
    norm = _norm_title(title)
    if not norm:
        return False
    ts = _now()
    client = (client_name or "").strip() or None
    try:
        with _conn() as c:
            existing = c.execute(
                "SELECT id, summary, wp_id, wp_url, client_name "
                "FROM requirements_seen WHERE title_norm = ? AND source = ?",
                (norm, source),
            ).fetchone()
            if existing:
                c.execute(
                    "UPDATE requirements_seen SET "
                    "  last_seen = ?, "
                    "  touch_count = touch_count + 1, "
                    "  summary = CASE WHEN ? = '' THEN summary ELSE ? END, "
                    "  wp_id = COALESCE(?, wp_id), "
                    "  wp_url = COALESCE(?, wp_url), "
                    "  client_name = COALESCE(?, client_name) "
                    "WHERE id = ?",
                    (ts, summary, summary, wp_id, wp_url, client,
                     existing["id"]),
                )
            else:
                c.execute(
                    "INSERT INTO requirements_seen "
                    "(title, title_norm, source, source_ref, summary, "
                    " wp_id, wp_url, client_name, "
                    " first_seen, last_seen, touch_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (title.strip(), norm, source, source_ref, summary,
                     wp_id, wp_url, client, ts, ts),
                )
        return True
    except Exception as e:
        logger.warning("memory.remember_requirement failed: %s", e)
        return False


_VALID_CONFIRMATION = {"pending", "confirmed", "needs_change",
                       "rejected", "unclear"}


def update_confirmation(
    *,
    title: str | None = None,
    requirement_id: int | None = None,
    status: str,
    notes: str = "",
    email_uid: str | None = None,
    confirmed_at: str | None = None,
) -> bool:
    """Mark a requirement's confirmation_status. Match by id (preferred)
    or by case-insensitive title. status must be one of:
    pending | confirmed | needs_change | rejected | unclear."""
    if status not in _VALID_CONFIRMATION:
        raise ValueError(
            f"status must be one of {sorted(_VALID_CONFIRMATION)}; "
            f"got {status!r}")
    ts = confirmed_at or _now()
    try:
        with _conn() as c:
            if requirement_id is not None:
                cur = c.execute(
                    "UPDATE requirements_seen SET "
                    "  confirmation_status = ?, "
                    "  confirmation_at = ?, "
                    "  confirmation_notes = ?, "
                    "  confirmation_email_uid = COALESCE(?, confirmation_email_uid) "
                    "WHERE id = ?",
                    (status, ts, notes or "", email_uid, int(requirement_id)),
                )
            elif title:
                norm = _norm_title(title)
                cur = c.execute(
                    "UPDATE requirements_seen SET "
                    "  confirmation_status = ?, "
                    "  confirmation_at = ?, "
                    "  confirmation_notes = ?, "
                    "  confirmation_email_uid = COALESCE(?, confirmation_email_uid) "
                    "WHERE title_norm = ?",
                    (status, ts, notes or "", email_uid, norm),
                )
            else:
                return False
            return cur.rowcount > 0
    except Exception as e:
        logger.warning("memory.update_confirmation failed: %s", e)
        return False


def confirmation_counts() -> dict[str, int]:
    """Counts per confirmation_status across requirements_seen.
    Used by the calibration report to show the closed-loop signal."""
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT confirmation_status, COUNT(*) AS n "
                "FROM requirements_seen GROUP BY confirmation_status"
            ).fetchall()
            return {r["confirmation_status"]: r["n"] for r in rows}
    except Exception as e:
        logger.warning("memory.confirmation_counts failed: %s", e)
        return {}


def pending_requirements(client_name: str | None = None,
                         limit: int = 100) -> list[dict]:
    """Requirements drafted but not yet confirmed by the client.
    Optionally filter by client_name. Used by the reply poller as the
    candidate pool to match against incoming replies."""
    limit = max(1, min(limit, 500))
    try:
        with _conn() as c:
            sql = ("SELECT id, title, summary, source, source_ref, "
                   "       client_name, first_seen, last_seen "
                   "FROM requirements_seen "
                   "WHERE confirmation_status = 'pending'")
            args: list = []
            if client_name:
                sql += " AND LOWER(client_name) = LOWER(?)"
                args.append(client_name.strip())
            sql += " ORDER BY last_seen DESC LIMIT ?"
            args.append(limit)
            rows = c.execute(sql, args).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("memory.pending_requirements failed: %s", e)
        return []


def get_client_history(
    client_name: str,
    limit: int = 20,
    since: str | None = None,
) -> list[dict]:
    """Recent requirements seen for one client. Used as CONTEXT during
    identification — not for dedup (that's search_requirements). The
    agent reads this list to spot recurring asks ('client always wants
    audit logging — flag if missing') and follow-ups vs new asks.

    Match is exact + case-insensitive on client_name. Pass `since` as
    an ISO timestamp to limit to recent activity."""
    if not (client_name or "").strip():
        return []
    limit = max(1, min(limit, 200))
    try:
        with _conn() as c:
            sql = (
                "SELECT id, title, summary, source, source_ref, "
                "       client_name, wp_id, wp_url, "
                "       first_seen, last_seen, touch_count "
                "FROM requirements_seen "
                "WHERE LOWER(client_name) = LOWER(?)"
            )
            args: list[Any] = [client_name.strip()]
            if since:
                sql += " AND last_seen >= ?"
                args.append(since)
            sql += " ORDER BY last_seen DESC, id DESC LIMIT ?"
            args.append(limit)
            rows = c.execute(sql, args).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("memory.get_client_history failed: %s", e)
        return []


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
                "       r.wp_id, r.wp_url, "
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


# ─── Writes / reads: requirement_reviews (calibration loop) ─────────

_VALID_DECISIONS = {"keep", "edit", "reject", "skip"}


def record_review(
    *,
    requirement_title: str,
    decision: str,
    predicted_confidence: float | None = None,
    source_refs: list[str] | None = None,
    edited_title: str | None = None,
    reviewer_notes: str = "",
    sidecar_path: str = "",
    docx_path: str = "",
) -> int | None:
    """Persist one reviewer decision against a predicted requirement.
    Returns the row id or None on failure."""
    if decision not in _VALID_DECISIONS:
        raise ValueError(
            f"decision must be one of {sorted(_VALID_DECISIONS)}; got {decision!r}")
    try:
        import json as _json  # local alias to avoid import shadow issues
        srcs_json = _json.dumps(source_refs or [], ensure_ascii=False)
        with _conn() as c:
            cur = c.execute(
                "INSERT INTO requirement_reviews "
                "(reviewed_at, requirement_title, predicted_confidence, "
                "source_refs_json, decision, edited_title, reviewer_notes, "
                "sidecar_path, docx_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _now(), requirement_title.strip(),
                    float(predicted_confidence)
                        if predicted_confidence is not None else None,
                    srcs_json, decision,
                    (edited_title or None),
                    reviewer_notes or "",
                    sidecar_path or "",
                    docx_path or "",
                ),
            )
            return int(cur.lastrowid)
    except Exception as e:
        logger.warning("memory.record_review failed: %s", e)
        return None


def recent_reviews(limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 500))
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM requirement_reviews "
                "ORDER BY reviewed_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("memory.recent_reviews failed: %s", e)
        return []


def calibration_buckets(
    buckets: list[tuple[float, float]] | None = None,
) -> list[dict]:
    """Bucket reviewer decisions by predicted confidence and report
    accept rate (keep + edit) vs. reject rate per bucket. Default
    buckets: [0.90-1.00], [0.75-0.90), [0.50-0.75), [<0.50]."""
    if buckets is None:
        buckets = [(0.90, 1.0001), (0.75, 0.90), (0.50, 0.75), (0.0, 0.50)]
    out: list[dict] = []
    try:
        with _conn() as c:
            for lo, hi in buckets:
                row = c.execute(
                    "SELECT decision, COUNT(*) AS n FROM requirement_reviews "
                    "WHERE predicted_confidence IS NOT NULL "
                    "AND predicted_confidence >= ? AND predicted_confidence < ? "
                    "GROUP BY decision",
                    (lo, hi),
                ).fetchall()
                counts = {r["decision"]: r["n"] for r in row}
                kept = counts.get("keep", 0)
                edited = counts.get("edit", 0)
                rejected = counts.get("reject", 0)
                skipped = counts.get("skip", 0)
                total_decided = kept + edited + rejected  # exclude skips
                accept_rate = (
                    (kept + edited) / total_decided
                    if total_decided > 0 else None
                )
                out.append({
                    "lo": lo, "hi": hi,
                    "keep": kept, "edit": edited,
                    "reject": rejected, "skip": skipped,
                    "decided": total_decided,
                    "accept_rate": accept_rate,
                })
    except Exception as e:
        logger.warning("memory.calibration_buckets failed: %s", e)
    return out


# ───────────────────────────────────────────────────────────────────


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
                "reviews":            c.execute("SELECT COUNT(*) FROM requirement_reviews").fetchone()[0],
            }
    except Exception as e:
        logger.warning("memory.stats failed: %s", e)
        return {"error": str(e)}
