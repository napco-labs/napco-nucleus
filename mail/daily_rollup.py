"""Daily roll-up emailer — one consolidated email per day.

Picks up the artifacts that ``collect_central.py`` already produced for the
day and mails them as attachments to a fixed recipient list. Lives at the
*end* of the daily-draft loop on .123 so it fires once per BD day, right
after ``collect_central.py --client all --last-minutes 1440`` completes.

What gets attached
------------------
1. ``data/requirements/sessions/current.docx`` — always. This is the unified
   session doc the pipeline wrote during the run (chats + call transcripts +
   email + drive content across every dev).
2. ``data/requirements/Requirements Verification <YYYY-MM-DD>.docx`` — when
   today's file exists (Claude's identified-requirements artifact). Skipped
   silently if the Claude step didn't produce one (e.g. auth blip).

Env vars
--------
    NUCLEUS_ROLLUP_TO       comma-separated TO list. Required.
    NUCLEUS_ROLLUP_CC       comma-separated CC list. Optional.
    SMTP_HOST/PORT/USER/PASSWORD/FROM/FROM_NAME  -- same set the existing
                            tools/daily_summary.py uses. Port 465 = SSL,
                            anything else = STARTTLS.

CLI
---
    python -m mail.daily_rollup              # today (local BD time)
    python -m mail.daily_rollup --day 2026-05-21
    python -m mail.daily_rollup --dry-run    # print plan + recipients, no send
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent.parent
load_dotenv(_HERE / ".env", override=True)

REQUIREMENTS_DIR = _HERE / "data" / "requirements"
SESSION_DOC = REQUIREMENTS_DIR / "sessions" / "current.docx"


def _verification_doc(day: str) -> Path:
    return REQUIREMENTS_DIR / f"Requirements Verification {day}.docx"


def _split_addresses(raw: str) -> list[str]:
    return [a.strip() for a in (raw or "").split(",") if a.strip()]


_REQ_LINE = __import__("re").compile(
    r"^\s*(\d+)\.\s*\[(P\d+/S\d+)\]\s*(.+?)(?:\s*[-–—]\s*.+)?$")


def _parse_verification_summary(path: Path) -> list[dict]:
    """Pull a one-line headline per requirement out of the verification
    .docx so the email body can summarise them at-a-glance. Returns a
    list of {"n": "1", "ps": "P2/S3", "title": "..."} dicts. Returns
    [] if the file is missing or contains no recognisable requirement
    lines (parser is best-effort, never raises)."""
    try:
        from docx import Document  # lazy: optional dep on the host side
        d = Document(str(path))
    except Exception:
        return []
    out: list[dict] = []
    for p in d.paragraphs:
        m = _REQ_LINE.match(p.text or "")
        if m:
            out.append({"n": m.group(1), "ps": m.group(2),
                        "title": m.group(3).strip()})
    return out


def _build_message(day: str, to_addrs: list[str], cc_addrs: list[str],
                   attachments: list[Path],
                   reqs: list[dict]) -> EmailMessage:
    sender = (os.environ.get("SMTP_FROM")
              or os.environ.get("SMTP_USER") or "").strip()
    name = (os.environ.get("SMTP_FROM_NAME") or "NAPCO Nucleus").strip()

    msg = EmailMessage()
    msg["From"] = f"{name} <{sender}>" if sender else name
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    msg["Subject"] = f"NAPCO Nucleus — daily client requirements ({day})"

    lines: list[str] = []
    lines.append(
        f"Daily summary of client requirements identified from the team's "
        f"emails, Teams chats and calls in the last 24 hours.")
    lines.append("")
    if reqs:
        lines.append(f"Requirements identified today ({len(reqs)}):")
        for r in reqs:
            lines.append(f"  {r['n']}. [{r['ps']}] {r['title']}")
    else:
        lines.append("No new client requirements were identified from "
                     "today's calls and communications. This may mean "
                     "discussions were internal, or calls had no "
                     "actionable items for the client.")
    lines.append("")
    lines.append(
        "The attached document contains the full text, sources and "
        "confidence notes. Please reply to this email with any corrections.")
    lines.append("")
    lines.append("— NAPCO Nucleus")
    msg.set_content("\n".join(lines))

    for path in attachments:
        with open(path, "rb") as f:
            data = f.read()
        msg.add_attachment(
            data,
            maintype="application",
            subtype=("vnd.openxmlformats-officedocument.wordprocessingml."
                     "document"),
            filename=path.name,
        )
    return msg


def _send(msg: EmailMessage, all_recipients: list[str]) -> None:
    host = (os.environ.get("SMTP_HOST") or "").strip()
    user = (os.environ.get("SMTP_USER") or "").strip()
    pw = os.environ.get("SMTP_PASSWORD") or ""
    if not host or not user or not pw:
        raise SystemExit(
            "SMTP_HOST/SMTP_USER/SMTP_PASSWORD missing — cannot send.")
    port = int(os.environ.get("SMTP_PORT", "587"))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(user, pw)
            s.send_message(msg, to_addrs=all_recipients)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(user, pw)
            s.send_message(msg, to_addrs=all_recipients)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", default=None,
                    help="YYYY-MM-DD. Default: today (local BD time).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the plan + recipients without sending.")
    args = ap.parse_args()

    day = args.day or dt.date.today().strftime("%Y-%m-%d")

    to_addrs = _split_addresses(os.environ.get("NUCLEUS_ROLLUP_TO", ""))
    cc_addrs = _split_addresses(os.environ.get("NUCLEUS_ROLLUP_CC", ""))
    if not to_addrs:
        print("NUCLEUS_ROLLUP_TO is not set — refusing to send anonymously.",
              file=sys.stderr)
        return 2

    # Boss-facing email: ONLY attach the curated Requirements Verification
    # doc. The raw session.docx (pipeline input) contains noise — marketing
    # emails, broken-mic call clips, low-confidence ASR — that the Claude
    # identify step already triaged out. Including it as an attachment
    # invites the reader to open the wrong file. If you ever need to ship
    # the session doc too (debugging), set NUCLEUS_ROLLUP_INCLUDE_SESSION=1.
    attachments: list[Path] = []
    verif = _verification_doc(day)
    if verif.exists():
        attachments.append(verif)
    else:
        print(f"[rollup] note: no '{verif.name}' — Claude identify step did "
              "not run or produced no output.")
    if os.environ.get("NUCLEUS_ROLLUP_INCLUDE_SESSION", "").strip() in (
            "1", "true", "yes"):
        if SESSION_DOC.exists():
            attachments.append(SESSION_DOC)

    reqs = _parse_verification_summary(verif) if verif.exists() else []

    print(f"[rollup] day={day}  to={to_addrs}  cc={cc_addrs}  "
          f"attachments={[p.name for p in attachments]}  "
          f"reqs_inlined={len(reqs)}")

    msg = _build_message(day, to_addrs, cc_addrs, attachments, reqs)
    if args.dry_run:
        print("[rollup] --dry-run: not sending.")
        return 0

    _send(msg, all_recipients=to_addrs + cc_addrs)
    print(f"[rollup] sent to {len(to_addrs)} TO + {len(cc_addrs)} CC "
          f"recipients.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
