"""
IMAP draft helper — push an .eml draft into the user's IMAP Drafts folder
so it appears in their mail client (Outlook / Gmail web / etc.).

Reads IMAP creds from the same env vars as the inbox poller:
    REQ_IMAP_HOST       default imap.gmail.com
    REQ_IMAP_PORT       default 993
    REQ_IMAP_USER       required
    REQ_IMAP_PASSWORD   required

Drafts folder resolution order:
    1. IMAP_DRAFTS_FOLDER env override
    2. Auto-detect via the IMAP \\Drafts SPECIAL-USE flag (RFC 6154)
    3. Fallback to "[Gmail]/Drafts" if host looks like Gmail, else "Drafts"
"""
from __future__ import annotations

import imaplib
import logging
import os
import re
import time
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def append_draft(msg: EmailMessage, *,
                 dedup_by_subject: bool = True) -> dict:
    """Append `msg` to the user's IMAP Drafts folder.

    If `dedup_by_subject` is True (default), any existing draft with
    the same Subject in the Drafts folder is marked \\Deleted and
    EXPUNGEd before the new draft is appended. This prevents
    duplicate verification drafts piling up when `do_it_now` is run
    multiple times for the same client/day.

    Returns: {appended: bool, folder: str|None, error: str|None,
             replaced: int — count of stale drafts removed}
    Never raises — IMAP errors are caught and surfaced in the dict.
    """
    host = (os.getenv("REQ_IMAP_HOST") or "imap.gmail.com").strip()
    port = int(os.getenv("REQ_IMAP_PORT", "993"))
    user = (os.getenv("REQ_IMAP_USER") or "").strip()
    password = os.getenv("REQ_IMAP_PASSWORD") or ""

    if not user or not password:
        return {"appended": False, "folder": None,
                "error": "REQ_IMAP_USER / REQ_IMAP_PASSWORD not set — "
                         "draft not pushed to mail client"}

    folder_override = (os.getenv("IMAP_DRAFTS_FOLDER") or "").strip()

    try:
        m = imaplib.IMAP4_SSL(host, port)
    except Exception as e:
        return {"appended": False, "folder": None,
                "error": f"IMAP connect failed: {type(e).__name__}: {e}"}

    try:
        try:
            m.login(user, password)
        except Exception as e:
            return {"appended": False, "folder": None,
                    "error": f"IMAP login failed: {type(e).__name__}: {e}"}

        if folder_override:
            drafts = folder_override
        else:
            drafts = _find_drafts_folder(m, host)
            if not drafts:
                return {"appended": False, "folder": None,
                        "error": "Could not locate Drafts folder via "
                                 "\\Drafts flag; set IMAP_DRAFTS_FOLDER env",
                        "replaced": 0}

        # Idempotent path: drop any prior draft with the same Subject
        # before appending the new one. Non-fatal if it fails — we
        # still proceed to APPEND so a fresh draft lands.
        replaced = 0
        if dedup_by_subject:
            subj = (msg.get("Subject") or "").strip()
            if subj:
                replaced = _purge_existing_drafts(m, drafts, subj)

        raw = bytes(msg)
        try:
            typ, data = m.append(
                drafts,
                r"(\Draft \Seen)",
                imaplib.Time2Internaldate(time.time()),
                raw,
            )
        except Exception as e:
            return {"appended": False, "folder": drafts,
                    "error": f"APPEND raised: {type(e).__name__}: {e}",
                    "replaced": replaced}

        if typ != "OK":
            tail = (data[0].decode("utf-8", "replace") if data and data[0]
                    else "")[:300]
            return {"appended": False, "folder": drafts,
                    "error": f"APPEND {typ}: {tail}", "replaced": replaced}

        return {"appended": True, "folder": drafts, "error": None,
                "replaced": replaced}
    finally:
        try:
            m.logout()
        except Exception:
            pass


def _purge_existing_drafts(m: imaplib.IMAP4_SSL, drafts_folder: str,
                            subject: str) -> int:
    """Mark + expunge any existing drafts in `drafts_folder` whose
    Subject matches exactly. Returns the count purged. Best-effort —
    swallows errors and returns 0 if anything goes wrong (the caller
    still APPENDs a new draft regardless)."""
    try:
        typ, _ = m.select(drafts_folder, readonly=False)
        if typ != "OK":
            return 0
        # SUBJECT in IMAP SEARCH does substring match, so we'll
        # double-check by fetching subjects of hits and exact-comparing.
        safe_subj = subject.replace('"', '\\"')
        typ, data = m.uid("SEARCH", None, "SUBJECT", f'"{safe_subj}"')
        if typ != "OK":
            return 0
        uids = (data[0] or b"").split()
        if not uids:
            return 0
        # Exact-match filter
        to_delete: list[bytes] = []
        for uid in uids:
            typ, msg_data = m.uid("FETCH", uid,
                                   "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
            if typ != "OK" or not msg_data:
                continue
            for chunk in msg_data:
                if not isinstance(chunk, tuple) or len(chunk) < 2:
                    continue
                body = chunk[1]
                if not isinstance(body, bytes):
                    continue
                text = body.decode("utf-8", "replace").strip()
                # text looks like "Subject: <subject>\r\n\r\n"
                if text.lower().startswith("subject:"):
                    actual = text.split(":", 1)[1].strip()
                    if actual == subject:
                        to_delete.append(uid)
                        break
        if not to_delete:
            return 0
        uid_set = b",".join(to_delete).decode()
        m.uid("STORE", uid_set, "+FLAGS", r"(\Deleted)")
        try:
            m.expunge()
        except Exception:
            pass
        return len(to_delete)
    except Exception as e:
        logger.info("dedup purge failed (non-fatal): %s", e)
        return 0


def _find_drafts_folder(m: imaplib.IMAP4_SSL, host: str) -> str | None:
    """Return the Drafts folder name via the \\Drafts SPECIAL-USE flag,
    with host-specific fallbacks."""
    try:
        typ, data = m.list()
    except Exception:
        typ, data = "NO", []

    if typ == "OK" and data:
        for raw in data:
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            if r"\Drafts" not in line:
                continue
            # IMAP LIST line format:
            #   (\HasNoChildren \Drafts) "/" "[Gmail]/Drafts"
            # Last quoted token (or trailing bare token) is the folder name.
            m_quoted = re.search(r'"([^"]+)"\s*$', line)
            if m_quoted:
                return m_quoted.group(1)
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                return parts[1].strip()

    # Fallbacks
    if "gmail" in host.lower():
        return "[Gmail]/Drafts"
    return "Drafts"
