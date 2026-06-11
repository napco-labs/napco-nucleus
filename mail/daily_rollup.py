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


# Matches the verification-doc requirement line. Primary format (Titu's spec):
#   "Requirement#1: Title - summary"
# Also tolerates the older "1. [P1/S2 ~4h] Title - summary" so prior docs still
# parse. Groups: 1=number (Requirement# form), 2=number (old "N." form),
# 3=title. Any "[...]" tag after an old-style number is stripped.
# The title/summary separator is " - " (whitespace REQUIRED on both sides) so
# internal hyphens stay intact — otherwise "Re-publish…" truncates to "Re" and
# "End-to-end…" to "End" (2026-06-11).
_REQ_LINE = __import__("re").compile(
    r"^\s*(?:Requirement#\s*(\d+):|(\d+)\.)\s*(?:\[[^\]]*\]\s*)?(.+?)"
    r"(?:\s+[-–—]\s+.+)?$")


def _parse_verification_summary(path: Path) -> list[dict]:
    """Pull a one-line headline per requirement out of the verification .docx
    so the email body can summarise them at-a-glance. Returns a list of
    {"n": "1", "title": "..."} dicts. Returns [] if the file is missing or
    has no recognisable requirement lines (best-effort, never raises)."""
    try:
        from docx import Document  # lazy: optional dep on the host side
        d = Document(str(path))
    except Exception:
        return []
    out: list[dict] = []
    for p in d.paragraphs:
        m = _REQ_LINE.match(p.text or "")
        if m:
            out.append({"n": (m.group(1) or m.group(2)),
                        "title": m.group(3).strip()})
    return out


# ── Same-day dedupe of emailed requirements ──────────────────────────────
# Event-triggered runs (one per transcription) must NOT re-email the team a
# requirement that already went out earlier today, and must NOT send at all
# when there's nothing net-new — otherwise every completed transcription
# blasts assad + CC, often with 0 requirements (2026-06-09). We track the
# requirement titles already emailed per BD day in a tiny state file; the
# 23:00 clock run ignores this gate and always sends the daily summary.
_EMAILED_DIR = REQUIREMENTS_DIR / ".emailed"


def _req_key(r: dict) -> str:
    return (r.get("title") or "").strip().lower()


def _emailed_keys(day: str) -> set[str]:
    try:
        f = _EMAILED_DIR / f"{day}.txt"
        return {l.strip() for l in f.read_text(encoding="utf-8").splitlines()
                if l.strip()}
    except Exception:
        return set()


def _record_emailed(day: str, keys: list[str]) -> None:
    try:
        _EMAILED_DIR.mkdir(parents=True, exist_ok=True)
        merged = _emailed_keys(day) | {k for k in keys if k}
        (_EMAILED_DIR / f"{day}.txt").write_text(
            "\n".join(sorted(merged)), encoding="utf-8")
    except Exception as e:
        print(f"[rollup] warn: could not record emailed requirements: {e}",
              file=sys.stderr)


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
    lines.append("Dear Team,")
    lines.append("")
    if reqs:
        lines.append(
            "Below are the requirement TITLES identified from the last "
            "24 hours (MS Teams calls, chats, email, and Google Drive). "
            "These are titles only — for the full description, sources, "
            "and confidence notes, please see the attached document.")
        lines.append("")
        for r in reqs:
            lines.append(f"  Requirement#{r['n']}: {r['title']}")
    else:
        lines.append(
            "No requirements were found from the MS Teams calls, chats, "
            "email, or Google Drive last night. This is just a notification "
            "to let you know the scenario. No action needed.")
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
    ap.add_argument("--require-new", action="store_true",
                    help="Only send if there is >=1 requirement not already "
                         "emailed today (skip empty/duplicate sends). Used for "
                         "event-triggered runs; the 23:00 clock run omits it so "
                         "the daily summary always goes out.")
    args = ap.parse_args()

    day = args.day or dt.date.today().strftime("%Y-%m-%d")

    to_addrs = _split_addresses(os.environ.get("NUCLEUS_ROLLUP_TO", ""))
    cc_addrs = _split_addresses(os.environ.get("NUCLEUS_ROLLUP_CC", ""))
    if not to_addrs:
        print("NUCLEUS_ROLLUP_TO is not set — refusing to send anonymously.",
              file=sys.stderr)
        return 2

    # Parse the curated requirements FIRST — the email shape + attachment
    # depend on it.
    verif = _verification_doc(day)
    reqs = _parse_verification_summary(verif) if verif.exists() else []

    # Attach the Requirements Verification doc ONLY when there are
    # requirements. A no-requirements run is a plain notification — do NOT
    # attach a blank/empty doc (per Titu, 2026-06-09). The raw session.docx
    # stays off by default (it contains pre-triage noise); set
    # NUCLEUS_ROLLUP_INCLUDE_SESSION=1 to include it for debugging.
    attachments: list[Path] = []
    if reqs and verif.exists():
        attachments.append(verif)
        if os.environ.get("NUCLEUS_ROLLUP_INCLUDE_SESSION", "").strip() in (
                "1", "true", "yes") and SESSION_DOC.exists():
            attachments.append(SESSION_DOC)

    already = _emailed_keys(day)
    new_reqs = [r for r in reqs if _req_key(r) not in already]

    print(f"[rollup] day={day}  to={to_addrs}  cc={cc_addrs}  "
          f"attachments={[p.name for p in attachments]}  "
          f"reqs_inlined={len(reqs)}  net_new={len(new_reqs)}  "
          f"require_new={args.require_new}")

    # Event-triggered runs: skip the team email unless something is net-new.
    # Kills the empty / duplicate midday blasts; the clock run never sets this.
    if args.require_new and not new_reqs:
        print(f"[rollup] --require-new: {len(reqs)} requirement(s) on file, "
              f"0 net-new since last send — skipping email.")
        return 0

    msg = _build_message(day, to_addrs, cc_addrs, attachments, reqs)
    if args.dry_run:
        print("[rollup] --dry-run: not sending.")
        return 0

    import time as _time
    all_recipients = to_addrs + cc_addrs
    for _attempt in range(2):
        try:
            _send(msg, all_recipients=all_recipients)
            print(f"[rollup] sent to {len(to_addrs)} TO + {len(cc_addrs)} CC "
                  f"recipients.")
            _record_emailed(day, [_req_key(r) for r in reqs])
            return 0
        except Exception as e:
            if _attempt == 0:
                print(f"[rollup] SMTP failed (attempt 1): {e} — retrying in 60s",
                      file=sys.stderr)
                _time.sleep(60)
            else:
                print(f"[rollup] SMTP failed (attempt 2): {e} — giving up.",
                      file=sys.stderr)
                return 1


if __name__ == "__main__":
    sys.exit(main())
