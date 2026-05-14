"""Daily summary email — closes the "is normal operation happening?"
loop that healthcheck doesn't cover.

Healthcheck answers "is anything broken?". Daily summary answers
"is anything happening?" — an unexpectedly quiet day on a busy
project is worth knowing about too.

What it reports:

  Pipeline activity (last 24h)
    - runs (activity_logs rows with task_name starting requirement-
      collection:)
    - requirements drafted (write_verification rows; titles + mean
      confidence)
    - reviews logged (requirement_reviews rows; keep/edit/reject
      breakdown)
    - client replies processed (rows updated in the last 24h via
      poll_replies, identified by confirmation_at)

  Memory state (snapshot)
    - requirements_seen: pending / confirmed / needs_change / rejected
      / unclear counts
    - reviews: total + mean_confidence over the last 7 days

  Operational
    - healthcheck failures in the last 24h (if any healthcheck logs
      exist via activity_logs)

Usage:
    py -3 -m tools.daily_summary                # print to stdout
    py -3 -m tools.daily_summary --send         # email to summary_to
    py -3 -m tools.daily_summary --since 48h    # widen the window
    py -3 -m tools.daily_summary --json         # machine-readable

Schedule it via Task Scheduler: daily at 23:00 with --send.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import socket
import sqlite3
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


def _parse_since(s: str) -> dt.timedelta:
    """Parse '24h', '48h', '7d', '3600s'. Default to '24h' if blank."""
    s = (s or "24h").strip().lower()
    m = re.fullmatch(r"(\d+)\s*([smhd])?", s)
    if not m:
        raise ValueError(f"bad --since {s!r}; try '24h' or '7d'")
    n, unit = int(m.group(1)), (m.group(2) or "h")
    return dt.timedelta(seconds={"s": 1, "m": 60,
                                  "h": 3600, "d": 86400}[unit] * n)


def _gather(since: dt.timedelta) -> dict:
    cutoff_dt = dt.datetime.now() - since
    cutoff_iso = cutoff_dt.isoformat(timespec="seconds")
    # activity_logs uses CURRENT_TIMESTAMP (UTC-ish), compare via SQLite
    cutoff_sqlite = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
    out: dict = {
        "since": cutoff_dt.isoformat(timespec="seconds"),
        "now": dt.datetime.now().isoformat(timespec="seconds"),
        "host": socket.gethostname(),
    }
    try:
        with sqlite3.connect(memory.db_path()) as c:
            c.row_factory = sqlite3.Row

            # Pipeline activity rows in the window
            runs = c.execute(
                "SELECT task_name, result, timestamp FROM activity_logs "
                "WHERE timestamp >= ? "
                "AND task_name LIKE 'requirement-collection:%' "
                "ORDER BY timestamp DESC",
                (cutoff_sqlite,),
            ).fetchall()
            out["pipeline_runs"] = [dict(r) for r in runs]

            # Reviews in the window
            reviews = c.execute(
                "SELECT decision, predicted_confidence, requirement_title, "
                "       reviewed_at FROM requirement_reviews "
                "WHERE reviewed_at >= ? ORDER BY reviewed_at DESC",
                (cutoff_iso,),
            ).fetchall()
            out["reviews"] = [dict(r) for r in reviews]

            # Client confirmations applied in the window (poll_replies)
            confs = c.execute(
                "SELECT title, client_name, confirmation_status, "
                "       confirmation_at, confirmation_notes "
                "FROM requirements_seen "
                "WHERE confirmation_at IS NOT NULL "
                "AND confirmation_at >= ? "
                "ORDER BY confirmation_at DESC",
                (cutoff_iso,),
            ).fetchall()
            out["confirmations_today"] = [dict(r) for r in confs]
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        out["pipeline_runs"] = []
        out["reviews"] = []
        out["confirmations_today"] = []

    # Snapshots
    out["confirmation_counts"] = memory.confirmation_counts()
    out["memory_stats"] = memory.stats()
    out["calibration_buckets"] = memory.calibration_buckets()
    return out


def _render_text(data: dict) -> str:
    lines: list[str] = []
    host = data.get("host", "?")
    lines.append(f"NAPCO Nucleus daily summary — {data['now']} (host: {host})")
    lines.append(f"Window: since {data['since']}")
    lines.append("")

    # Pipeline activity
    runs = data.get("pipeline_runs") or []
    lines.append(f"Pipeline runs in window: {len(runs)}")
    by_task: dict[str, int] = {}
    drafts: list[dict] = []
    for r in runs:
        t = r["task_name"]
        by_task[t] = by_task.get(t, 0) + 1
        if t == "requirement-collection:write_verification":
            drafts.append(r)
    for t in sorted(by_task):
        lines.append(f"  {t:50s} {by_task[t]}")
    if drafts:
        lines.append("")
        lines.append("Verification drafts written:")
        for d in drafts[:10]:
            lines.append(f"  {d['timestamp']}  {d['result']}")
        if len(drafts) > 10:
            lines.append(f"  ... and {len(drafts) - 10} more")
    lines.append("")

    # Reviews
    reviews = data.get("reviews") or []
    if reviews:
        breakdown: dict[str, int] = {"keep": 0, "edit": 0,
                                     "reject": 0, "skip": 0}
        confidences: list[float] = []
        for r in reviews:
            d = r["decision"]
            breakdown[d] = breakdown.get(d, 0) + 1
            c = r["predicted_confidence"]
            if isinstance(c, (int, float)):
                confidences.append(float(c))
        mean = (sum(confidences) / len(confidences)) if confidences else None
        lines.append(f"Reviews logged: {len(reviews)}")
        for k in ("keep", "edit", "reject", "skip"):
            if breakdown.get(k, 0):
                lines.append(f"  {k:6s} {breakdown[k]}")
        if mean is not None:
            lines.append(f"  mean predicted confidence: {mean:.2f}")
        lines.append("")
    else:
        lines.append("Reviews logged: 0")
        lines.append("")

    # Confirmations applied in window
    confs_today = data.get("confirmations_today") or []
    if confs_today:
        lines.append(f"Client confirmations applied in window: {len(confs_today)}")
        for c in confs_today[:10]:
            line = (f"  [{c['confirmation_status']:13s}] "
                    f"{c['client_name'] or '?'}: {c['title']}")
            lines.append(line[:120])
        lines.append("")

    # Memory snapshot
    conf = data.get("confirmation_counts") or {}
    if conf:
        total = sum(conf.values())
        lines.append("Confirmation state (all requirements):")
        for k in ("pending", "confirmed", "needs_change",
                  "rejected", "unclear"):
            n = conf.get(k, 0)
            if n:
                pct = (n / total) if total else 0
                lines.append(f"  {k:14s} {n:5d}  ({pct:.0%})")
        lines.append("")

    # Calibration verdicts
    buckets = data.get("calibration_buckets") or []
    decided_buckets = [b for b in buckets if b.get("decided", 0)]
    if decided_buckets:
        lines.append("Calibration (cumulative):")
        for b in buckets:
            if not b.get("decided"):
                continue
            lo, hi = b["lo"], min(b["hi"], 1.0)
            rate = b.get("accept_rate")
            rate_s = f"{rate:.0%}" if rate is not None else "—"
            lines.append(f"  {lo:.2f}-{hi:.2f}  decided={b['decided']:3d}  "
                         f"accept-rate={rate_s}")
        lines.append("")

    # Memory rows total
    ms = data.get("memory_stats") or {}
    if ms:
        lines.append("Memory rows:")
        for k in ("activity", "requirements", "test_runs",
                  "email_checkpoints", "drive_processed", "reviews"):
            if k in ms:
                lines.append(f"  {k:18s} {ms[k]}")

    return "\n".join(lines)


def _send_email(text: str) -> bool:
    import smtplib
    import ssl
    from email.message import EmailMessage

    host = (os.environ.get("SMTP_HOST") or "").strip()
    user = (os.environ.get("SMTP_USER") or "").strip()
    pw = os.environ.get("SMTP_PASSWORD") or ""
    sender = (os.environ.get("SMTP_FROM") or user).strip()
    name = (os.environ.get("SMTP_FROM_NAME") or "NAPCO Nucleus").strip()
    # Recipient: NUCLEUS_DAILY_SUMMARY_TO > SUMMARY_EMAILS first addr > SMTP_USER
    to_addr = (os.environ.get("NUCLEUS_DAILY_SUMMARY_TO") or "").strip()
    if not to_addr:
        first = (os.environ.get("SUMMARY_EMAILS") or "").split(",")[0].strip()
        to_addr = first or user or sender
    if not host or not user or not pw or not to_addr:
        print("[summary] SMTP not configured "
              "(need SMTP_HOST/USER/PASSWORD + NUCLEUS_DAILY_SUMMARY_TO "
              "or SUMMARY_EMAILS).", file=sys.stderr)
        return False
    msg = EmailMessage()
    msg["From"] = f"{name} <{sender}>"
    msg["To"] = to_addr
    today = dt.date.today().strftime("%Y-%m-%d")
    msg["Subject"] = f"NN daily summary — {today} ({socket.gethostname()})"
    msg.set_content(text)
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
        ctx = ssl.create_default_context()
        # Port 465 = implicit SSL; everything else uses STARTTLS.
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(user, pw)
                s.send_message(msg)
    except Exception as e:
        print(f"[summary] send failed: {type(e).__name__}: {e}",
              file=sys.stderr)
        return False
    print(f"[summary] sent to {to_addr}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="24h",
                    help="Window size. Try '24h', '48h', '7d'. Default 24h.")
    ap.add_argument("--send", action="store_true",
                    help="Email the summary via existing SMTP creds.")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="Machine-readable output.")
    args = ap.parse_args()

    try:
        since = _parse_since(args.since)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    data = _gather(since)

    if args.as_json:
        print(json.dumps(data, indent=2, default=str, ensure_ascii=False))
        return 0

    text = _render_text(data)
    print(text)

    if args.send:
        print()
        ok = _send_email(text)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
