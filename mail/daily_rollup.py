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
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

from mail import nucleus_flair

_HERE = Path(__file__).resolve().parent.parent
load_dotenv(_HERE / ".env", override=True)

REQUIREMENTS_DIR = _HERE / "data" / "requirements"
SESSION_DOC = REQUIREMENTS_DIR / "sessions" / "current.docx"


def _verification_doc(day: str) -> Path:
    return REQUIREMENTS_DIR / f"Requirements Verification {day}.docx"


def _verification_docs(day: str) -> list[Path]:
    """All verification docs for the day: the legacy single
    'Requirements Verification <day>.docx' AND the per-project
    'Requirements Verification - <label> <day>.docx' files introduced by
    the 2026-06-25 doc split (one doc per OpenProject project). Sorted so
    ordering is stable across runs."""
    return sorted(REQUIREMENTS_DIR.glob(f"Requirements Verification*{day}.docx"))


_COVERAGE_DIR = REQUIREMENTS_DIR / ".coverage"


def _coverage_note(day: str, reqs: list) -> tuple[str | None, bool]:
    """Return (note, escalate) for an empty (no-requirements) email so a
    silent drop is VISIBLE — without crying wolf on a genuinely quiet day.

    `note` is an informational line about what was processed; `escalate`
    is True only on a HARD failure (non-zero identify exit) and bumps the
    subject to [ACTION NEEDED]. Returns (None, False) when there's nothing
    to add (requirements were found, or no sources came in at all).
    collect_central writes the signal this reads
    (data/requirements/.coverage/<day>.json)."""
    if reqs:
        return None, False  # requirements listed already — no note needed
    try:
        cov = json.loads(
            (_COVERAGE_DIR / f"{day}.json").read_text(encoding="utf-8"))
    except Exception:
        return None, False  # no signal (older/missing) — benign legacy path
    src = cov.get("sources") or {}
    calls = int(src.get("calls", 0) or 0)
    chats = int(src.get("chats", 0) or 0)
    atts = int(src.get("attachments", 0) or 0)
    if calls + chats + atts == 0:
        return None, False  # genuinely nothing came in — quiet day, benign
    rc = cov.get("verify_rc")
    if rc not in (0, None):
        # Hard failure: identify errored (auth/crash/timeout). Shout.
        note = (
            f"PIPELINE CHECK NEEDED — {calls} call(s), {chats} chat(s), "
            f"{atts} attachment(s) were collected for {day}, but the "
            f"requirement identify step FAILED (exit={rc}) and produced no "
            f"requirements. This is a failure, not a quiet day — please "
            f"check the run.")
        return note, True
    # Identify ran clean; sources were present but yielded 0 client
    # requirements. Informational only (e.g. internal/duplicate calls) so
    # the coverage is visible at a glance — not an alarm.
    return (
        f"For your awareness: {calls} call(s), {chats} chat(s), and "
        f"{atts} attachment(s) were processed for {day}, and 0 new client "
        f"requirements were identified from them. If you expected "
        f"requirements here, just reply and I'll re-check that source.",
        False)


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


def _week_days(day: str) -> list[str]:
    try:
        d = dt.date.fromisoformat(day)
    except Exception:
        d = dt.date.today()
    return [(d - dt.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def _reqs_this_week(day: str) -> int:
    """Total requirements across the last 7 days' verification docs — reuses
    the same parser the email uses, so the number matches what went out."""
    total = 0
    for d in _week_days(day):
        for doc in _verification_docs(d):
            try:
                total += len(_parse_verification_summary(doc))
            except Exception:
                pass
    return total


def _calls_this_week(day: str) -> int:
    """Count team calls captured to the central tree in the last 7 days (one
    *.json per call session). Best-effort — returns 0 on any problem so the
    flair never breaks the email."""
    central = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    if not central:
        return 0
    days = set(_week_days(day))
    n = 0
    try:
        root = Path(central)
        for dev in root.iterdir():
            if not dev.is_dir():
                continue
            for d in days:
                cdir = dev / d / "calls"
                if cdir.exists():
                    n += len(list(cdir.glob("*.json")))
    except Exception:
        return 0
    return n


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
                   reqs: list[dict],
                   note: str | None = None,
                   escalate: bool = False) -> EmailMessage:
    sender = (os.environ.get("SMTP_FROM")
              or os.environ.get("SMTP_USER") or "").strip()
    name = (os.environ.get("SMTP_FROM_NAME") or "NAPCO Nucleus").strip()

    msg = EmailMessage()
    msg["From"] = f"{name} <{sender}>" if sender else name
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    subject = f"NAPCO Nucleus — daily client requirements ({day})"
    if escalate:
        subject = f"[ACTION NEEDED] {subject}"
    msg["Subject"] = subject

    lines: list[str] = []
    lines.append("Dear Team,")
    lines.append("")
    if reqs:
        lines.append(
            "Please find attached the Requirements Verification document "
            "prepared from your recent communications (MS Teams calls, chats, "
            "email, and Google Drive). It sets out the requirements we "
            "identified, together with any open questions where we need your "
            "input to finalise them.")
        lines.append("")
        lines.append(
            "Kindly review the attached document and reply with your "
            "confirmation or any corrections, and we will proceed accordingly.")
    elif note:
        lines.append(note)
    else:
        lines.append(
            "No requirements were found from the MS Teams calls, chats, "
            "email, or Google Drive last night. This is just a notification "
            "to let you know the scenario. No action needed.")
    lines.append("")

    # Daily flair: a live coverage insight + a rotating quality quote or a
    # Nucleus reassurance line for the devs. Fully best-effort — empty on any
    # error so it can never break or delay the send.
    try:
        flair = nucleus_flair.daily_flair(
            day, _reqs_this_week(day), _calls_this_week(day))
    except Exception:
        flair = ""
    if flair:
        lines.append(flair)
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

    if args.day:
        day = args.day
    else:
        # The nightly loop starts collect_central at 23:30; its Claude
        # identify pass can push THIS emailer past midnight, so
        # dt.date.today() would name the NEXT day's (nonexistent)
        # verification doc and send an empty "no requirements" summary
        # (2026-06-17 incident: collect used 06-17, rollup used 06-18).
        # In the small-hours window, if today has no doc yet but
        # yesterday's exists, this run is the tail of last night — use
        # yesterday so the email reflects the day that was actually
        # collected.
        now = dt.datetime.now()
        today = now.date().strftime("%Y-%m-%d")
        yday = (now.date() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
        if now.hour < 6 and not _verification_docs(today) \
                and _verification_docs(yday):
            day = yday
        else:
            day = today

    to_addrs = _split_addresses(os.environ.get("NUCLEUS_ROLLUP_TO", ""))
    cc_addrs = _split_addresses(os.environ.get("NUCLEUS_ROLLUP_CC", ""))
    if not to_addrs:
        print("NUCLEUS_ROLLUP_TO is not set — refusing to send anonymously.",
              file=sys.stderr)
        return 2

    # Parse the curated requirements FIRST — the email shape + attachment
    # depend on it. Gather across ALL per-day docs (legacy single doc +
    # the per-project split docs), then renumber so the consolidated email
    # shows one continuous Requirement# sequence instead of each doc
    # restarting at 1.
    verif_docs = _verification_docs(day)
    reqs = []
    for _doc in verif_docs:
        reqs.extend(_parse_verification_summary(_doc))
    for _i, _r in enumerate(reqs, 1):
        _r["n"] = str(_i)

    # Requirements-only CC: addresses that receive the email ONLY when it
    # actually carries requirements (e.g. an external client rep) — never on
    # an empty / notification send. Was a central-only uncommitted patch;
    # folded into the repo here so it stops drifting from origin.
    if reqs:
        for a in _split_addresses(
                os.environ.get("NUCLEUS_ROLLUP_CC_REQS_ONLY", "")):
            if a not in cc_addrs and a not in to_addrs:
                cc_addrs.append(a)

    # Attach the Requirements Verification doc ONLY when there are
    # requirements. A no-requirements run is a plain notification — do NOT
    # attach a blank/empty doc (per Titu, 2026-06-09). The raw session.docx
    # stays off by default (it contains pre-triage noise); set
    # NUCLEUS_ROLLUP_INCLUDE_SESSION=1 to include it for debugging.
    attachments: list[Path] = []
    if reqs and verif_docs:
        attachments.extend(verif_docs)  # one per project (CA4K + MVP Access)
        if os.environ.get("NUCLEUS_ROLLUP_INCLUDE_SESSION", "").strip() in (
                "1", "true", "yes") and SESSION_DOC.exists():
            attachments.append(SESSION_DOC)

    already = _emailed_keys(day)
    new_reqs = [r for r in reqs if _req_key(r) not in already]

    # On an empty email, surface what was actually processed so a silent
    # drop is visible — and escalate the subject only on a hard failure.
    note, escalate = _coverage_note(day, reqs)

    print(f"[rollup] day={day}  to={to_addrs}  cc={cc_addrs}  "
          f"attachments={[p.name for p in attachments]}  "
          f"reqs_inlined={len(reqs)}  net_new={len(new_reqs)}  "
          f"require_new={args.require_new}  note={bool(note)}  "
          f"escalate={escalate}")

    # Never send a blank email to anyone.
    # Skip if there are zero requirements AND no hard-failure escalation.
    # escalate=True means the identify step crashed — that's an [ACTION NEEDED]
    # alert worth sending even with no requirements list.
    if not reqs and not escalate:
        print(f"[rollup] 0 requirements and no pipeline failure — skipping send.")
        return 0

    # Event-triggered runs: also skip if everything already went out today.
    if args.require_new and not new_reqs:
        print(f"[rollup] --require-new: {len(reqs)} requirement(s) on file, "
              f"0 net-new since last send — skipping email.")
        return 0

    msg = _build_message(day, to_addrs, cc_addrs, attachments, reqs,
                         note, escalate)
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
