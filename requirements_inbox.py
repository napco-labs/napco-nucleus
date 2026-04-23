"""
Requirement Management — email inbox poller.

Polls an IMAP mailbox (typically the user's work Gmail / Exchange),
keeps only messages whose From address is in REQ_SENDER_ALLOWLIST,
and writes each matching message as a .txt file under
data/requirements/inbox/email/ with a short header preface so the
downstream LLM splitter has source context.

Idempotency is anchored on per-mailbox UIDVALIDITY + a since-UID
checkpoint stored in data/requirements/state.json, so re-running
the poll never re-ingests the same email.

Run standalone:
    python requirements_inbox.py              # poll and write
    python requirements_inbox.py --dry-run    # show matches, no writes
    python requirements_inbox.py --since N    # override since-UID

Or call poll_requirement_inbox() from tools.py.

Env vars:
    REQ_IMAP_HOST            default imap.gmail.com
    REQ_IMAP_PORT            default 993
    REQ_IMAP_USER            required (mailbox login)
    REQ_IMAP_PASSWORD        required (app password or account secret)
    REQ_SENDER_ALLOWLIST     required, comma-separated addresses

The mailbox polled is INBOX. If you want to restrict to a label or
folder, move requirement emails into a Gmail label and point this
script at that label via the REQ_IMAP_MAILBOX env var.
"""
from __future__ import annotations

import argparse
import email
import email.utils
import imaplib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from email.header import decode_header
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env")

logger = logging.getLogger(__name__)

INBOX_DIR = _HERE / "data" / "requirements" / "inbox" / "email"
STATE_FILE = _HERE / "data" / "requirements" / "state.json"


def _decode(raw: str | bytes | None) -> str:
    """Decode a MIME-encoded header value safely."""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    parts = decode_header(raw)
    out: list[str] = []
    for part, enc in parts:
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", "replace"))
        else:
            out.append(part)
    return "".join(out).strip()


def _extract_from_address(from_header: str) -> str:
    """Return the bare email address from a From header (strip display name)."""
    _, addr = email.utils.parseaddr(from_header or "")
    return (addr or "").strip().lower()


def _body_text(msg: email.message.Message) -> str:
    """Pull the plain-text body out, preferring text/plain then falling
    back to stripped text/html."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, "replace")
            except Exception:
                continue
            if ctype == "text/plain":
                plain_parts.append(text)
            elif ctype == "text/html":
                html_parts.append(text)
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                text = payload.decode(charset, "replace")
                if msg.get_content_type() == "text/plain":
                    plain_parts.append(text)
                else:
                    html_parts.append(text)
        except Exception:
            pass

    if plain_parts:
        return "\n\n".join(plain_parts).strip()
    if html_parts:
        return re.sub(r"<[^>]+>", " ",
                      re.sub(r"<script.*?</script>|<style.*?</style>", " ",
                             "\n".join(html_parts), flags=re.S | re.I)
                      ).strip()
    return ""


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


def _safe_subject_slug(subject: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", subject or "").strip("-").lower()
    return (s or "no-subject")[:max_len]


def poll_requirement_inbox(dry_run: bool = False, since_uid: str | None = None) -> dict:
    """Poll the mailbox and write matching emails to the inbox dir.
    Returns a summary dict — never raises for empty results or for
    dropped messages; does raise for auth / config errors."""
    host = (os.getenv("REQ_IMAP_HOST") or "imap.gmail.com").strip()
    port = int(os.getenv("REQ_IMAP_PORT", "993"))
    user = (os.getenv("REQ_IMAP_USER") or "").strip()
    password = os.getenv("REQ_IMAP_PASSWORD") or ""
    mailbox = (os.getenv("REQ_IMAP_MAILBOX") or "INBOX").strip()
    allowlist_raw = os.getenv("REQ_SENDER_ALLOWLIST") or ""
    allowlist = {a.strip().lower() for a in allowlist_raw.split(",") if a.strip()}

    if not user or not password:
        return {"error": "REQ_IMAP_USER and REQ_IMAP_PASSWORD must be set",
                "ingested": 0}
    if not allowlist:
        return {"error": "REQ_SENDER_ALLOWLIST must contain at least one address",
                "ingested": 0}

    state = _load_state()
    email_state = state.setdefault("email", {})
    if since_uid is None:
        since_uid = str(email_state.get(f"{user}:{mailbox}:last_uid") or "0")

    INBOX_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"Connecting to {host}:{port} as {user} (mailbox={mailbox})")
    m = imaplib.IMAP4_SSL(host, port)
    try:
        m.login(user, password)
        m.select(mailbox, readonly=True)

        # UIDVALIDITY pin — if the server's UIDVALIDITY changed we can't
        # trust our stored since_uid, so reset to 0 (full reingest on
        # next run, filtered by allowlist).
        typ, uidval_data = m.status(mailbox, "(UIDVALIDITY)")
        uidvalidity = None
        if typ == "OK" and uidval_data:
            m_ = re.search(r"UIDVALIDITY (\d+)", uidval_data[0].decode())
            if m_:
                uidvalidity = m_.group(1)
        stored_uidvalidity = email_state.get(f"{user}:{mailbox}:uidvalidity")
        if uidvalidity and stored_uidvalidity and uidvalidity != stored_uidvalidity:
            logger.warning(f"UIDVALIDITY changed ({stored_uidvalidity} -> "
                           f"{uidvalidity}); resetting since_uid to 0")
            since_uid = "0"
        if uidvalidity:
            email_state[f"{user}:{mailbox}:uidvalidity"] = uidvalidity

        # Search for UIDs strictly greater than since_uid.
        search_since = str(int(since_uid) + 1) if since_uid.isdigit() else "1"
        typ, data = m.uid("SEARCH", None, f"UID {search_since}:*")
        if typ != "OK":
            return {"error": f"IMAP SEARCH failed: {typ}", "ingested": 0}

        uids = (data[0] or b"").split()
        ingested = 0
        skipped_offlist = 0
        max_uid_seen = int(since_uid or "0")
        written_files: list[str] = []

        for uid_bytes in uids:
            uid = uid_bytes.decode()
            try:
                max_uid_seen = max(max_uid_seen, int(uid))
            except ValueError:
                pass
            typ, msg_data = m.uid("FETCH", uid, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if isinstance(raw, bytes):
                msg = email.message_from_bytes(raw)
            else:
                continue

            from_hdr = _decode(msg.get("From"))
            from_addr = _extract_from_address(from_hdr)
            if from_addr not in allowlist:
                skipped_offlist += 1
                continue

            subject = _decode(msg.get("Subject"))
            date_hdr = msg.get("Date") or ""
            try:
                received = email.utils.parsedate_to_datetime(date_hdr)
            except Exception:
                received = datetime.now(timezone.utc)
            body = _body_text(msg)

            preface = (
                f"# source: email\n"
                f"# from: {from_addr}\n"
                f"# received: {received.isoformat()}\n"
                f"# subject: {subject}\n\n"
            )

            ts = received.strftime("%Y-%m-%dT%H-%M")
            slug = _safe_subject_slug(subject)
            fname = f"{ts}-uid{uid}-{slug}.txt"
            path = INBOX_DIR / fname

            if dry_run:
                logger.info(f"[dry-run] would write {path.name} "
                            f"(from={from_addr}, subject={subject[:60]})")
            else:
                path.write_text(preface + body, encoding="utf-8")
                written_files.append(str(path.relative_to(_HERE).as_posix()))
                logger.info(f"Wrote {path.name}")
            ingested += 1

        if not dry_run:
            email_state[f"{user}:{mailbox}:last_uid"] = str(max_uid_seen)
            state["email"] = email_state
            _save_state(state)

        return {
            "ingested": ingested,
            "skipped_offlist": skipped_offlist,
            "files": written_files,
            "since_uid": since_uid,
            "new_last_uid": str(max_uid_seen),
            "dry_run": dry_run,
        }
    finally:
        try:
            m.logout()
        except Exception:
            pass


def _cli() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--since", default=None,
                   help="Override since-UID checkpoint (e.g. 0 to force full re-poll)")
    args = p.parse_args()
    result = poll_requirement_inbox(dry_run=args.dry_run, since_uid=args.since)
    print(json.dumps(result, indent=2, default=str))
    if result.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    _cli()
