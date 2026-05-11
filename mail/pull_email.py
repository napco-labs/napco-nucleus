"""
On-demand email pull — fetch IMAP messages by sender / subject / time
window and append them to NAPCO Nucleus's pull-session doc.

Four filters, all optional, all AND'd:

    --from-sender "addr"     match From: header (substring or full)
    --subject "text"         match Subject: header (substring)
    --last-minutes N         relative window: now - N min  ..  now
    --from HH:MM --to HH:MM  manual absolute window (with optional --date)

Usage:
    python -m mail.pull_email --last-minutes 15
    python -m mail.pull_email --from-sender "titucse@gmail.com" --last-minutes 30
    python -m mail.pull_email --subject "budget" --from "3 PM" --to "5 PM"
    python -m mail.pull_email --from-sender "khasan@ael-bd.com" --subject "Q3 plan"
    python -m mail.pull_email --date 2026-05-06 --from 09:00 --to 18:00

With no filters at all, default is today 00:00 -> 23:59 (full day —
narrow with at least one filter to avoid pulling the whole inbox).

Differs from the auto-poll inbox model (requirements_inbox.py): this is
explicitly user-commanded, narrowly filtered, and writes ONE consolidated
section into the session doc instead of one .txt per email in inbox/email/.

Env vars (same as requirements_inbox.py):
    REQ_IMAP_HOST       default imap.gmail.com
    REQ_IMAP_PORT       default 993
    REQ_IMAP_USER       required
    REQ_IMAP_PASSWORD   required
    REQ_IMAP_MAILBOX    default INBOX

Reuses the body + attachment extraction helpers from requirements_inbox
(PDF / Word / TXT attachments are extracted to text, no email
allowlist applied — when you ask for it, you get it).
"""
from __future__ import annotations

import argparse
import datetime as dt
import email
import email.utils
import hashlib
import imaplib
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).parent.parent  # mail/<file> -> NN root
load_dotenv(_HERE / ".env", override=True)

# Reuse requirements_inbox's parsing helpers + the session-doc helper.
from mail import requirements_inbox as ri  # noqa: E402
from tools import _session_doc as session_doc  # noqa: E402
from tools._session_doc import _slugify  # noqa: E402
from tools._retry import retry as _retry_deco  # noqa: E402


def _parse_time(s: str) -> dt.time:
    s = s.strip().upper().replace(".", "")
    for fmt in ("%H:%M", "%I:%M %p", "%I %p", "%I:%M%p", "%I%p"):
        try:
            return dt.datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized time {s!r}. Try '15:00' or '3:00 PM'.")


def _imap_date(d: dt.date) -> str:
    """Format a date in IMAP SEARCH form (e.g. 06-May-2026)."""
    return d.strftime("%d-%b-%Y")


def _build_search_criteria(*, sender: str | None, subject: str | None,
                           start_dt: dt.datetime,
                           end_dt: dt.datetime) -> list[str]:
    """Build IMAP SEARCH criteria. SINCE/BEFORE bracket the date range
    (server-side narrowing), client filters to the exact window."""
    crit: list[str] = []
    crit += ["SINCE", _imap_date(start_dt.date()),
             "BEFORE", _imap_date(end_dt.date() + dt.timedelta(days=1))]
    if sender:
        crit += ["FROM", f'"{sender}"']
    if subject:
        crit += ["SUBJECT", f'"{subject}"']
    return crit


@_retry_deco(attempts=3, base_delay=1.0)
def fetch_emails_in_window(*, sender: str | None, subject: str | None,
                           start_dt: dt.datetime,
                           end_dt: dt.datetime) -> list[dict]:
    """Connect to IMAP, narrow by date, filter to the absolute datetime
    window client-side. Returns parsed message dicts with body +
    attachments already extracted.

    Retried up to 3 times on transient network / IMAP errors."""
    host = (os.getenv("REQ_IMAP_HOST") or "imap.gmail.com").strip()
    port = int(os.getenv("REQ_IMAP_PORT", "993"))
    user = (os.getenv("REQ_IMAP_USER") or "").strip()
    password = os.getenv("REQ_IMAP_PASSWORD") or ""
    mailbox = (os.getenv("REQ_IMAP_MAILBOX") or "INBOX").strip()

    if not user or not password:
        raise RuntimeError("REQ_IMAP_USER / REQ_IMAP_PASSWORD must be set")

    out: list[dict] = []
    m = imaplib.IMAP4_SSL(host, port)
    try:
        m.login(user, password)
        m.select(mailbox, readonly=True)
        crit = _build_search_criteria(sender=sender, subject=subject,
                                      start_dt=start_dt, end_dt=end_dt)
        typ, data = m.uid("SEARCH", None, *crit)
        if typ != "OK":
            raise RuntimeError(f"IMAP SEARCH failed: {typ}")
        uids = (data[0] or b"").split()
        for uid_b in uids:
            uid = uid_b.decode()
            typ, msg_data = m.uid("FETCH", uid, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if not isinstance(raw, bytes):
                continue
            msg = email.message_from_bytes(raw)

            from_hdr = ri._decode(msg.get("From"))
            from_addr = ri._extract_from_address(from_hdr)
            subj = ri._decode(msg.get("Subject")) or "(no subject)"
            date_hdr = msg.get("Date") or ""
            try:
                received = email.utils.parsedate_to_datetime(date_hdr)
            except Exception:
                received = None
            received_local = (received.astimezone() if received else None)

            # Client-side absolute-datetime filter
            if received_local:
                naive_local = received_local.replace(tzinfo=None)
                if not (start_dt <= naive_local <= end_dt):
                    continue

            body = ri._body_text(msg)
            attachments = ri._extract_attachments(msg)
            out.append({
                "uid": uid,
                "from": from_addr,
                "subject": subj,
                "received": received_local.strftime("%Y-%m-%d %H:%M") if received_local else "(no date)",
                "body": body,
                "attachments": attachments,
            })
    finally:
        try:
            m.logout()
        except Exception:
            pass

    return out


def _build_email_paragraphs(e: dict) -> list[str]:
    """Body paragraphs for a single email's session-doc section."""
    lines: list[str] = []
    lines.append(f"From: {e['from']}")
    lines.append(f"Subject: {e['subject']}")
    lines.append(f"Received: {e['received']}")
    lines.append("")
    lines.append("Body:")
    body = (e['body'] or "(empty)").strip()
    for ln in body.splitlines() or [body]:
        lines.append(ln)
    atts = e["attachments"]
    if atts:
        lines.append("")
        lines.append(f"Attachments ({len(atts)}):")
        for fname, text in atts:
            lines.append(f"  --- attachment: {fname} ---")
            for ln in (text or "(empty)").splitlines():
                lines.append(f"  {ln}")
    return lines


def _email_source_id(e: dict) -> str:
    """Granular per-email Source ID.

    Format: email/<sender-slug>/<YYYY-MM-DDTHHMM>/<8-char-sha1>

    The hash component disambiguates two emails from the same sender at
    the same minute and stays stable across runs (deterministic over
    sender + subject + received).
    """
    sender = (e.get("from") or "unknown").strip() or "unknown"
    received = (e.get("received") or "").strip()
    # received looks like "YYYY-MM-DD HH:MM" — collapse to a clean token
    if received and received != "(no date)":
        received_token = received.replace(" ", "T").replace(":", "")
    else:
        received_token = "no-date"
    sender_slug = _slugify(sender, max_len=40).lower()
    digest = hashlib.sha1(
        f"{sender}|{e.get('subject') or ''}|{received}".encode("utf-8")
    ).hexdigest()[:8]
    return f"email/{sender_slug}/{received_token}/{digest}"


def _email_headline(e: dict, max_subject: int = 80) -> str:
    """Human-readable section heading for one email."""
    sender = (e.get("from") or "(unknown sender)").strip() or "(unknown sender)"
    subject = (e.get("subject") or "(no subject)").strip() or "(no subject)"
    if len(subject) > max_subject:
        subject = subject[: max_subject - 1] + "…"
    return f"from {sender} — {subject}"


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from-sender", default=None,
                   help="Match From: header (substring or full address)")
    p.add_argument("--subject", default=None,
                   help="Match Subject: header (substring)")
    p.add_argument("--last-minutes", type=int, default=None,
                   help="Pull emails from the last N minutes "
                        "(supersedes --from / --to / --date)")
    p.add_argument("--from", dest="from_t", default="00:00",
                   help="Start of time window (HH:MM or '3 PM')")
    p.add_argument("--to", dest="to_t", default="23:59",
                   help="End of time window (HH:MM or '5 PM')")
    p.add_argument("--date", default=None,
                   help="Target date YYYY-MM-DD (default today)")
    args = p.parse_args()

    # All four filters are optional and can be combined freely. With no
    # filter at all, the default window is today 00:00 -> 23:59 (full
    # day, all senders, all subjects). Sender, subject, last-minutes,
    # and explicit --from/--to/--date are all AND'd.

    # Resolve the absolute (start_dt, end_dt) window from either the
    # relative --last-minutes flag or the --from/--to/--date triple.
    if args.last_minutes is not None:
        if args.last_minutes <= 0:
            print("--last-minutes must be > 0", file=sys.stderr)
            return 1
        end_dt = dt.datetime.now()
        start_dt = end_dt - dt.timedelta(minutes=args.last_minutes)
    else:
        target_date = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
                       if args.date else dt.date.today())
        try:
            from_t = _parse_time(args.from_t)
            to_t = _parse_time(args.to_t)
        except ValueError as e:
            print(f"Time parse error: {e}", file=sys.stderr)
            return 1
        start_dt = dt.datetime.combine(target_date, from_t)
        end_dt = dt.datetime.combine(target_date, to_t)

    print(f"Pulling emails from mailbox...")
    print(f"  From sender: {args.from_sender or '(any)'}")
    print(f"  Subject:     {args.subject or '(any)'}")
    print(f"  Window:      {start_dt.strftime('%Y-%m-%d %H:%M:%S')}"
          f" -> {end_dt.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        emails = fetch_emails_in_window(
            sender=args.from_sender, subject=args.subject,
            start_dt=start_dt, end_dt=end_dt)
    except Exception as e:
        print(f"\nIMAP error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    print(f"\nMatched {len(emails)} email(s).")
    if not emails:
        return 0

    # One session-doc section per email so each gets its own Source ID
    # the LLM can cite precisely (instead of "all emails in this 48h
    # window" lumped under one ID).
    total_lines = 0
    session_path: str | None = None
    for e in emails:
        result = session_doc.append_section(
            source="EMAIL",
            headline=_email_headline(e),
            metadata={
                "From": e["from"],
                "Subject": (e["subject"] or "(no subject)")[:120],
                "Received": e["received"],
                "Attachments": str(len(e["attachments"])),
            },
            body_paragraphs=_build_email_paragraphs(e),
            source_id=_email_source_id(e),
        )
        total_lines += result["appended_paragraphs"]
        session_path = result["absolute_path"]
        print(f"  + {result['source_id']}  ({result['appended_paragraphs']} lines)")

    print(f"\nAppended {len(emails)} email section(s) to session doc.")
    if session_path:
        print(f"Session doc: {session_path}")
    print(f"Total lines added: {total_lines}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
