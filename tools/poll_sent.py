r"""Poll the IMAP Sent folder for verification emails that have left
Drafts → Sent. Stamps sent_at on the matching requirements_seen rows.

Closes the middle of the requirement lifecycle:

  drafted  ────►  sent_at  ────►  confirmation_at
  (this step is what poll_sent.py fills in)

Without sent_at we can't distinguish "Titu hasn't sent it yet" from
"Titu sent it and the client is just slow to reply" — and the
auto-send roadmap can't gate on it.

Matching strategy:
  - Look for Sent-folder messages with subject matching
    r"requirements?\s+verification" (same regex as poll_replies)
  - Date from the Sent message's `Date` header is the sent_at value
  - All requirements_seen rows whose first_seen falls on that date
    get the stamp (one verification email -> one batch of requirements)

Idempotent: rows that already have sent_at stamped are skipped.

Usage:
    py -3 -m tools.poll_sent                       # last 14 days
    py -3 -m tools.poll_sent --days 30
    py -3 -m tools.poll_sent --dry-run
    py -3 -m tools.poll_sent --json

Folder resolution: IMAP_SENT_FOLDER env override > IMAP \\Sent
SPECIAL-USE flag > "[Gmail]/Sent Mail" / "Sent Items" / "Sent" fallback
by host heuristic.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email
import email.utils
import imaplib
import json
import os
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_HERE / ".env", override=False)

import memory  # noqa: E402
from tools._retry import retry as _retry_deco  # noqa: E402


_SUBJECT_RE = re.compile(r"requirements?\s+verification", re.IGNORECASE)


def _decode_header(raw) -> str:
    if not raw:
        return ""
    from email.header import decode_header, make_header
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _imap_date(d: dt.date) -> str:
    return d.strftime("%d-%b-%Y")


def _find_sent_folder(m: imaplib.IMAP4_SSL, host: str) -> str | None:
    override = (os.environ.get("IMAP_SENT_FOLDER") or "").strip()
    if override:
        return override
    try:
        typ, data = m.list()
    except Exception:
        typ, data = "NO", []
    if typ == "OK" and data:
        for raw in data:
            line = (raw.decode("utf-8", "replace")
                    if isinstance(raw, bytes) else raw)
            if r"\Sent" not in line:
                continue
            m_quoted = re.search(r'"([^"]+)"\s*$', line)
            if m_quoted:
                return m_quoted.group(1)
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                return parts[1].strip()
    if "gmail" in host.lower():
        return "[Gmail]/Sent Mail"
    return "Sent"


@_retry_deco(attempts=3, base_delay=1.0)
def fetch_sent_verifications(days: int) -> list[dict]:
    """Return list of {uid, subject, sent_at} for verification emails
    in the Sent folder over the last N days."""
    end_dt = dt.datetime.now()
    start_dt = end_dt - dt.timedelta(days=days)

    host = (os.getenv("REQ_IMAP_HOST") or "imap.gmail.com").strip()
    port = int(os.getenv("REQ_IMAP_PORT", "993"))
    user = (os.getenv("REQ_IMAP_USER") or "").strip()
    pw = os.getenv("REQ_IMAP_PASSWORD") or ""
    if not user or not pw:
        raise RuntimeError("REQ_IMAP_USER / REQ_IMAP_PASSWORD must be set")

    out: list[dict] = []
    m = imaplib.IMAP4_SSL(host, port)
    try:
        m.login(user, pw)
        sent_folder = _find_sent_folder(m, host)
        if not sent_folder:
            raise RuntimeError("could not locate Sent folder")
        typ, _ = m.select(sent_folder, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"SELECT {sent_folder} failed: {typ}")

        typ, data = m.uid("SEARCH", None, "SINCE",
                           _imap_date(start_dt.date()))
        if typ != "OK":
            return out
        uids = (data[0] or b"").split()
        for uid_b in uids:
            uid = uid_b.decode()
            typ, msg_data = m.uid(
                "FETCH", uid,
                "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])")
            if typ != "OK" or not msg_data:
                continue
            for chunk in msg_data:
                if not isinstance(chunk, tuple) or len(chunk) < 2:
                    continue
                body = chunk[1]
                if not isinstance(body, bytes):
                    continue
                hdrs = email.message_from_bytes(body)
                subj = _decode_header(hdrs.get("Subject")) or ""
                if not _SUBJECT_RE.search(subj):
                    continue
                date_str = hdrs.get("Date") or ""
                try:
                    parsed = email.utils.parsedate_to_datetime(date_str)
                    if parsed:
                        sent_at = parsed.astimezone().replace(
                            tzinfo=None).isoformat(timespec="seconds")
                    else:
                        sent_at = ""
                except Exception:
                    sent_at = ""
                if not sent_at:
                    continue
                out.append({"uid": uid, "subject": subj,
                            "sent_at": sent_at,
                            "folder": sent_folder})
                break
    finally:
        try:
            m.logout()
        except Exception:
            pass
    return out


def _color(s, c): return f"\033[{c}m{s}\033[0m"
def _g(s): return _color(s, "32")
def _y(s): return _color(s, "33")
def _r(s): return _color(s, "31")
def _d(s): return _color(s, "2")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=14,
                    help="Look back N days. Default: 14.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Find verifications in Sent but do NOT stamp.")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="Machine-readable output.")
    args = ap.parse_args()

    if not args.as_json:
        print(f"\nScanning Sent folder for verification emails "
              f"(last {args.days} day(s))…")
    try:
        sent = fetch_sent_verifications(args.days)
    except Exception as e:
        print(_r(f"IMAP error: {type(e).__name__}: {e}"),
              file=sys.stderr)
        return 2

    if not args.as_json:
        print(f"Matched {len(sent)} sent verification email(s).")

    results: list[dict] = []
    for entry in sent:
        if args.dry_run:
            results.append({**entry, "stamped": 0, "dry_run": True})
            if not args.as_json:
                print(_d(f"  [dry-run] {entry['sent_at']}  "
                         f"{entry['subject'][:60]}"))
            continue
        n = memory.mark_sent_by_subject(
            subject=entry["subject"],
            sent_at=entry["sent_at"],
            sent_email_uid=entry["uid"],
        )
        results.append({**entry, "stamped": n})
        if not args.as_json:
            marker = _g(f"✓ stamped {n} req(s)") if n else _d(
                "(no matching unsent reqs)")
            print(f"  {entry['sent_at']}  {entry['subject'][:60]}  {marker}")

    counts = memory.sent_counts()
    if args.as_json:
        print(json.dumps(
            {"days": args.days, "dry_run": args.dry_run,
             "sent_emails": results, "counts": counts},
            indent=2, default=str))
        return 0
    if counts:
        print()
        print("Lifecycle counts across requirements_seen:")
        print(f"  drafted        {counts.get('drafted', 0)}")
        print(f"  sent           {counts.get('sent', 0)}")
        print(f"  awaiting reply {counts.get('awaiting_reply', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
