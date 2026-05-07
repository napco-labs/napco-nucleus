"""SQLite state for the requirement-watcher pipeline.

One database at data/watcher.db.

Original Teams-source tables:
  - messages: every processed Teams message (idempotency + audit)
  - state:    arbitrary key/value (last_poll_ms, watermarks, etc.)

v1 multi-source extensions (added 2026-05-05):
  - email_items:        raw fetched email entries, dedup by Message-ID
  - drive_items:        raw Drive file revisions, dedup by file_id + revision_id
  - requirements:       classifier output, one row per identified requirement
  - sent_emails:        verification emails we sent (our Message-ID for threading)
  - reply_corrections:  client replies threaded to a sent email, parsed corrections
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Iterable

DB_PATH = Path(__file__).parent.parent / "data" / "teams" / "watcher.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    sender_mri TEXT,
    sender_name TEXT,
    is_self INTEGER NOT NULL,
    arrival_ms INTEGER,
    message_type TEXT,
    body TEXT,
    raw_json TEXT,
    processed_at INTEGER NOT NULL,
    handlers_run TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_arrival ON messages(arrival_ms);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS email_items (
    id TEXT PRIMARY KEY,            -- the email's Message-ID header
    sender TEXT NOT NULL,
    recipients_json TEXT,
    subject TEXT,
    sent_at_ms INTEGER,
    body_text TEXT,
    body_html TEXT,
    raw_headers_json TEXT,
    fetched_at INTEGER NOT NULL,
    processed_at INTEGER             -- NULL until classifier has run on this
);

CREATE INDEX IF NOT EXISTS idx_email_sent ON email_items(sent_at_ms);
CREATE INDEX IF NOT EXISTS idx_email_processed ON email_items(processed_at);

CREATE TABLE IF NOT EXISTS drive_items (
    id TEXT PRIMARY KEY,            -- "<file_id>::<revision_id>"
    file_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    name TEXT,
    mime_type TEXT,
    owner TEXT,
    modified_at_ms INTEGER,
    snippet TEXT,                    -- excerpted plain text (first N chars)
    fetched_at INTEGER NOT NULL,
    processed_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_drive_modified ON drive_items(modified_at_ms);
CREATE INDEX IF NOT EXISTS idx_drive_processed ON drive_items(processed_at);

CREATE TABLE IF NOT EXISTS requirements (
    id TEXT PRIMARY KEY,             -- uuid4
    source TEXT NOT NULL,            -- 'teams' | 'email' | 'drive'
    source_item_id TEXT NOT NULL,    -- messages.id | email_items.id | drive_items.id
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    acceptance_criteria_json TEXT,
    estimate_hours INTEGER,
    raw_excerpt TEXT,
    classified_at INTEGER NOT NULL,
    sent_at INTEGER,                 -- NULL until a verification email goes out
    sent_email_id TEXT,              -- FK -> sent_emails.id
    superseded_by TEXT               -- FK -> requirements.id (if client correction replaced this)
);

CREATE INDEX IF NOT EXISTS idx_req_unsent ON requirements(sent_at) WHERE sent_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_req_source ON requirements(source, source_item_id);

CREATE TABLE IF NOT EXISTS sent_emails (
    id TEXT PRIMARY KEY,             -- our outbound Message-ID
    recipients_json TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_md TEXT,
    requirement_ids_json TEXT,       -- list of requirements.id included
    sent_at INTEGER NOT NULL,
    in_reply_to TEXT                 -- non-NULL for [Updated] re-sends; chains to prior sent_emails.id
);

CREATE INDEX IF NOT EXISTS idx_sent_at ON sent_emails(sent_at);

CREATE TABLE IF NOT EXISTS reply_corrections (
    id TEXT PRIMARY KEY,             -- the reply email's Message-ID
    in_reply_to TEXT NOT NULL,       -- FK -> sent_emails.id
    sender TEXT NOT NULL,
    received_at_ms INTEGER NOT NULL,
    body_text TEXT,
    parsed_corrections_json TEXT,    -- list[{requirement_id, change_type, new_value}]
    applied_at INTEGER,              -- NULL until the corrections have been applied
    fetched_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_corr_inreplyto ON reply_corrections(in_reply_to);
CREATE INDEX IF NOT EXISTS idx_corr_applied ON reply_corrections(applied_at);

CREATE TABLE IF NOT EXISTS chat_registry (
    chat_number INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT UNIQUE NOT NULL,
    title TEXT,
    format TEXT,                       -- 'v2' or 'skype'
    first_seen_ms INTEGER NOT NULL,
    last_activity_ms INTEGER,
    participants_json TEXT,
    msg_count INTEGER,
    is_allowlisted INTEGER DEFAULT 0,
    is_excluded INTEGER DEFAULT 0,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_registry_activity ON chat_registry(last_activity_ms);
CREATE INDEX IF NOT EXISTS idx_registry_allowlisted ON chat_registry(is_allowlisted);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ---- Teams messages (existing API, unchanged) ---------------------------

def is_processed(message_id: str) -> bool:
    with _connect() as c:
        row = c.execute("SELECT 1 FROM messages WHERE id = ?", (message_id,)).fetchone()
    return row is not None


def known_ids(message_ids: Iterable[str]) -> set[str]:
    ids = list(message_ids)
    if not ids:
        return set()
    with _connect() as c:
        placeholders = ",".join("?" * len(ids))
        rows = c.execute(
            f"SELECT id FROM messages WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    return {r["id"] for r in rows}


def save_message(msg: dict, handlers_run: list[str]) -> None:
    raw = msg.get("raw")
    raw_json = json.dumps(raw, default=str, ensure_ascii=False) if raw else None
    with _connect() as c:
        c.execute(
            """
            INSERT OR REPLACE INTO messages
            (id, conversation_id, sender_mri, sender_name, is_self,
             arrival_ms, message_type, body, raw_json, processed_at, handlers_run)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg["id"],
                msg["conversation_id"],
                msg.get("sender_mri"),
                msg.get("sender_name"),
                int(bool(msg.get("is_self"))),
                msg.get("arrival_ms"),
                msg.get("message_type"),
                msg.get("body"),
                raw_json,
                int(time.time() * 1000),
                ",".join(handlers_run),
            ),
        )


def message_count() -> int:
    with _connect() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM messages").fetchone()
    return row["n"] if row else 0


# ---- state k/v (existing API, unchanged) --------------------------------

def get_state(key: str) -> str | None:
    with _connect() as c:
        row = c.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_state(key: str, value: str) -> None:
    with _connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
            (key, value),
        )


# ---- email_items --------------------------------------------------------

def email_known_ids(message_ids: Iterable[str]) -> set[str]:
    ids = list(message_ids)
    if not ids:
        return set()
    with _connect() as c:
        placeholders = ",".join("?" * len(ids))
        rows = c.execute(
            f"SELECT id FROM email_items WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    return {r["id"] for r in rows}


def save_email_item(item: dict) -> None:
    with _connect() as c:
        c.execute(
            """
            INSERT OR IGNORE INTO email_items
            (id, sender, recipients_json, subject, sent_at_ms,
             body_text, body_html, raw_headers_json, fetched_at, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                item["id"],
                item["sender"],
                json.dumps(item.get("recipients") or [], ensure_ascii=False),
                item.get("subject"),
                item.get("sent_at_ms"),
                item.get("body_text"),
                item.get("body_html"),
                json.dumps(item.get("raw_headers") or {}, ensure_ascii=False),
                int(time.time() * 1000),
            ),
        )


def unprocessed_email_items() -> list[sqlite3.Row]:
    with _connect() as c:
        return c.execute(
            "SELECT * FROM email_items WHERE processed_at IS NULL ORDER BY sent_at_ms ASC"
        ).fetchall()


def mark_email_processed(item_id: str) -> None:
    with _connect() as c:
        c.execute(
            "UPDATE email_items SET processed_at = ? WHERE id = ?",
            (int(time.time() * 1000), item_id),
        )


# ---- drive_items --------------------------------------------------------

def drive_known_ids(item_ids: Iterable[str]) -> set[str]:
    ids = list(item_ids)
    if not ids:
        return set()
    with _connect() as c:
        placeholders = ",".join("?" * len(ids))
        rows = c.execute(
            f"SELECT id FROM drive_items WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    return {r["id"] for r in rows}


def save_drive_item(item: dict) -> None:
    with _connect() as c:
        c.execute(
            """
            INSERT OR IGNORE INTO drive_items
            (id, file_id, revision_id, name, mime_type, owner,
             modified_at_ms, snippet, fetched_at, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                item["id"],
                item["file_id"],
                item["revision_id"],
                item.get("name"),
                item.get("mime_type"),
                item.get("owner"),
                item.get("modified_at_ms"),
                item.get("snippet"),
                int(time.time() * 1000),
            ),
        )


def unprocessed_drive_items() -> list[sqlite3.Row]:
    with _connect() as c:
        return c.execute(
            "SELECT * FROM drive_items WHERE processed_at IS NULL ORDER BY modified_at_ms ASC"
        ).fetchall()


def mark_drive_processed(item_id: str) -> None:
    with _connect() as c:
        c.execute(
            "UPDATE drive_items SET processed_at = ? WHERE id = ?",
            (int(time.time() * 1000), item_id),
        )


# ---- requirements -------------------------------------------------------

def save_requirement(
    *,
    source: str,
    source_item_id: str,
    title: str,
    description: str,
    acceptance_criteria: list[str] | None,
    estimate_hours: int | None,
    raw_excerpt: str | None,
) -> str:
    rid = uuid.uuid4().hex
    with _connect() as c:
        c.execute(
            """
            INSERT INTO requirements
            (id, source, source_item_id, title, description,
             acceptance_criteria_json, estimate_hours, raw_excerpt, classified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                source,
                source_item_id,
                title,
                description,
                json.dumps(acceptance_criteria or [], ensure_ascii=False),
                estimate_hours,
                raw_excerpt,
                int(time.time() * 1000),
            ),
        )
    return rid


def unsent_requirements() -> list[sqlite3.Row]:
    with _connect() as c:
        return c.execute(
            """
            SELECT * FROM requirements
            WHERE sent_at IS NULL AND superseded_by IS NULL
            ORDER BY classified_at ASC
            """
        ).fetchall()


def mark_requirements_sent(req_ids: list[str], sent_email_id: str) -> None:
    if not req_ids:
        return
    now = int(time.time() * 1000)
    with _connect() as c:
        c.executemany(
            "UPDATE requirements SET sent_at = ?, sent_email_id = ? WHERE id = ?",
            [(now, sent_email_id, rid) for rid in req_ids],
        )


# ---- sent_emails --------------------------------------------------------

def save_sent_email(
    *,
    message_id: str,
    recipients: list[str],
    subject: str,
    body_md: str,
    requirement_ids: list[str],
    in_reply_to: str | None = None,
) -> None:
    with _connect() as c:
        c.execute(
            """
            INSERT INTO sent_emails
            (id, recipients_json, subject, body_md, requirement_ids_json, sent_at, in_reply_to)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                json.dumps(recipients, ensure_ascii=False),
                subject,
                body_md,
                json.dumps(requirement_ids, ensure_ascii=False),
                int(time.time() * 1000),
                in_reply_to,
            ),
        )


def get_sent_email(message_id: str) -> sqlite3.Row | None:
    with _connect() as c:
        return c.execute(
            "SELECT * FROM sent_emails WHERE id = ?", (message_id,)
        ).fetchone()


# ---- reply_corrections --------------------------------------------------

def save_reply_correction(
    *,
    reply_message_id: str,
    in_reply_to: str,
    sender: str,
    received_at_ms: int,
    body_text: str | None,
) -> None:
    with _connect() as c:
        c.execute(
            """
            INSERT OR IGNORE INTO reply_corrections
            (id, in_reply_to, sender, received_at_ms, body_text, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                reply_message_id,
                in_reply_to,
                sender,
                received_at_ms,
                body_text,
                int(time.time() * 1000),
            ),
        )


def unapplied_reply_corrections() -> list[sqlite3.Row]:
    with _connect() as c:
        return c.execute(
            "SELECT * FROM reply_corrections WHERE applied_at IS NULL ORDER BY received_at_ms ASC"
        ).fetchall()


def mark_correction_applied(reply_id: str, parsed_json: str) -> None:
    with _connect() as c:
        c.execute(
            """
            UPDATE reply_corrections
            SET applied_at = ?, parsed_corrections_json = ?
            WHERE id = ?
            """,
            (int(time.time() * 1000), parsed_json, reply_id),
        )


# ---- chat_registry ------------------------------------------------------

def upsert_chat(
    *,
    conversation_id: str,
    title: str | None,
    fmt: str,
    last_activity_ms: int | None,
    participants: list[str],
    msg_count: int,
) -> int:
    """Insert a new chat (assigns next chat_number) or update an existing one.

    Returns the chat_number (stable across calls).
    """
    now = int(time.time() * 1000)
    with _connect() as c:
        row = c.execute(
            "SELECT chat_number FROM chat_registry WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row:
            c.execute(
                """
                UPDATE chat_registry
                SET title = ?,
                    format = ?,
                    last_activity_ms = ?,
                    participants_json = ?,
                    msg_count = ?
                WHERE conversation_id = ?
                """,
                (
                    title,
                    fmt,
                    last_activity_ms,
                    json.dumps(participants, ensure_ascii=False),
                    msg_count,
                    conversation_id,
                ),
            )
            return int(row["chat_number"])
        c.execute(
            """
            INSERT INTO chat_registry
            (conversation_id, title, format, first_seen_ms, last_activity_ms,
             participants_json, msg_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                title,
                fmt,
                now,
                last_activity_ms,
                json.dumps(participants, ensure_ascii=False),
                msg_count,
            ),
        )
        new_number = c.execute("SELECT last_insert_rowid() AS n").fetchone()["n"]
    return int(new_number)


def list_chat_registry(order: str = "activity") -> list[sqlite3.Row]:
    """Return all registry rows. order='activity' = newest activity first;
    order='number' = chat_number ascending."""
    sort = (
        "last_activity_ms DESC, chat_number ASC"
        if order == "activity"
        else "chat_number ASC"
    )
    with _connect() as c:
        return c.execute(f"SELECT * FROM chat_registry ORDER BY {sort}").fetchall()


def get_chat_by_number(n: int) -> sqlite3.Row | None:
    with _connect() as c:
        return c.execute(
            "SELECT * FROM chat_registry WHERE chat_number = ?",
            (n,),
        ).fetchone()


def get_chat_by_id(conversation_id: str) -> sqlite3.Row | None:
    with _connect() as c:
        return c.execute(
            "SELECT * FROM chat_registry WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()


def set_chat_flag(conversation_id: str, *, allowlisted: bool | None = None, excluded: bool | None = None) -> None:
    """Toggle allowlist/exclude flags for a chat."""
    sets: list[str] = []
    args: list = []
    if allowlisted is not None:
        sets.append("is_allowlisted = ?")
        args.append(1 if allowlisted else 0)
    if excluded is not None:
        sets.append("is_excluded = ?")
        args.append(1 if excluded else 0)
    if not sets:
        return
    args.append(conversation_id)
    with _connect() as c:
        c.execute(
            f"UPDATE chat_registry SET {', '.join(sets)} WHERE conversation_id = ?",
            args,
        )


def allowlisted_chat_ids() -> set[str]:
    with _connect() as c:
        rows = c.execute(
            "SELECT conversation_id FROM chat_registry WHERE is_allowlisted = 1"
        ).fetchall()
    return {r["conversation_id"] for r in rows}
