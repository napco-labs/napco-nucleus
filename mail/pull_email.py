"""
On-demand email pull — fetch IMAP messages by sender / subject / time
window and append them to NAPCO Nucleus's pull-session doc.

Differs from the auto-poll inbox model (requirements_inbox.py): this is
explicitly user-commanded, narrowly filtered, and writes ONE consolidated
section into the session doc instead of one .txt per email in inbox/email/.

Usage:
    python pull_email.py --from-sender "titucse@gmail.com" --from "3 PM" --to "5 PM"
    python pull_email.py --subject "budget" --date 2026-05-06 --from 09:00 --to 18:00
    python pull_email.py --from-sender "khasan@ael-bd.com" --subject "Q3 plan"

Filters are AND'd. At least one of --from-sender / --subject is required.
Time window defaults to today, 00:00 -> 23:59.

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
                           target_date: dt.date) -> list[str]:
    """Build IMAP SEARCH criteria. We use date-window narrowing for
    efficiency (SINCE / BEFORE bracket the day), then time-of-day filter
    on the client side because IMAP SEARCH has no time-of-day predicate."""
    crit: list[str] = []
    crit += ["SINCE", _imap_date(target_date),
             "BEFORE", _imap_date(target_date + dt.timedelta(days=1))]
    if sender:
        crit += ["FROM", f'"{sender}"']
    if subject:
        crit += ["SUBJECT", f'"{subject}"']
    return crit


def fetch_filtered_emails(*, sender: str | None, subject: str | None,
                          target_date: dt.date, from_t: dt.time,
                          to_t: dt.time) -> list[dict]:
    """Connect to IMAP, run SEARCH for the day + filters, then narrow to
    the time window client-side. Returns a list of parsed message dicts
    with body + attachments already extracted."""
    host = (os.getenv("REQ_IMAP_HOST") or "imap.gmail.com").strip()
    port = int(os.getenv("REQ_IMAP_PORT", "993"))
    user = (os.getenv("REQ_IMAP_USER") or "").strip()
    password = os.getenv("REQ_IMAP_PASSWORD") or ""
    mailbox = (os.getenv("REQ_IMAP_MAILBOX") or "INBOX").strip()

    if not user or not password:
        raise RuntimeError("REQ_IMAP_USER / REQ_IMAP_PASSWORD must be set")

    from_ts = dt.datetime.combine(target_date, from_t)
    to_ts = dt.datetime.combine(target_date, to_t)

    out: list[dict] = []
    m = imaplib.IMAP4_SSL(host, port)
    try:
        m.login(user, password)
        m.select(mailbox, readonly=True)
        crit = _build_search_criteria(sender=sender, subject=subject,
                                      target_date=target_date)
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

            # Client-side time-of-day filter
            if received_local:
                # Compare in the user's local tz against the requested window
                naive_local = received_local.replace(tzinfo=None)
                if not (from_ts <= naive_local <= to_ts):
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


def _build_section_paragraphs(emails: list[dict]) -> list[str]:
    lines: list[str] = []
    for i, e in enumerate(emails, 1):
        lines.append("")
        lines.append(f"--- Email {i} of {len(emails)} ---")
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


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from-sender", default=None,
                   help="Match From: header (substring or full address)")
    p.add_argument("--subject", default=None,
                   help="Match Subject: header (substring)")
    p.add_argument("--from", dest="from_t", default="00:00",
                   help="Start of time window (HH:MM or '3 PM')")
    p.add_argument("--to", dest="to_t", default="23:59",
                   help="End of time window (HH:MM or '5 PM')")
    p.add_argument("--date", default=None,
                   help="Target date YYYY-MM-DD (default today)")
    args = p.parse_args()

    if not args.from_sender and not args.subject:
        print("Need at least one of --from-sender or --subject", file=sys.stderr)
        return 1

    target_date = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
                   if args.date else dt.date.today())
    try:
        from_t = _parse_time(args.from_t)
        to_t = _parse_time(args.to_t)
    except ValueError as e:
        print(f"Time parse error: {e}", file=sys.stderr)
        return 1

    print(f"Pulling emails from mailbox...")
    print(f"  From sender: {args.from_sender or '(any)'}")
    print(f"  Subject:     {args.subject or '(any)'}")
    print(f"  Date:        {target_date}")
    print(f"  Window:      {from_t.strftime('%H:%M')} -> {to_t.strftime('%H:%M')}")

    try:
        emails = fetch_filtered_emails(
            sender=args.from_sender, subject=args.subject,
            target_date=target_date, from_t=from_t, to_t=to_t)
    except Exception as e:
        print(f"\nIMAP error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    print(f"\nMatched {len(emails)} email(s).")
    if not emails:
        return 0

    headline_parts = []
    if args.from_sender:
        headline_parts.append(f"from {args.from_sender}")
    if args.subject:
        headline_parts.append(f"subject '{args.subject}'")
    headline = "  ".join(headline_parts) or "(no filter)"

    body = _build_section_paragraphs(emails)
    result = session_doc.append_section(
        source="EMAIL",
        headline=headline,
        metadata={
            "Date": str(target_date),
            "Window": f"{from_t.strftime('%H:%M')} -> {to_t.strftime('%H:%M')}",
            "Matched": str(len(emails)),
            "Attachments parsed": str(sum(len(e["attachments"]) for e in emails)),
        },
        body_paragraphs=body,
    )
    print(f"\nAppended to session doc: {result['absolute_path']}")
    print(f"Section: {result['section']}")
    print(f"Lines added: {result['appended_paragraphs']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
