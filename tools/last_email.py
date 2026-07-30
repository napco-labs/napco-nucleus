"""Report when the requirements email actually last went out.

NN used to answer "when did you last send the email?" by grepping the
daily-draft container's docker logs. That is not a record, it is a buffer:
`docker logs --tail 400` only reaches back a few hundred lines, and every
container recreate throws the history away entirely. So the answer drifted
and then froze -- on 2026-07-30 NN was still telling Titu the last email
went out on 22 July, when he had received one on the 29th.

mail/daily_rollup.py writes `data/requirements/.emailed/<day>.txt` listing
the requirement keys it emailed, and only after SMTP has accepted the
message. That file is the send receipt: it survives restarts, it cannot be
written by a run that failed, and its mtime is the send time. Read that.

Usage:
    python -m tools.last_email          # one human-readable line
    python -m tools.last_email --json   # machine-readable
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
EMAILED_DIR = _REPO / "data" / "requirements" / ".emailed"


def last_email() -> dict | None:
    """Newest send receipt, or None if the pipeline has never sent one.

    Ordered by the DAY IN THE FILENAME, not mtime. A late re-run for an
    earlier day rewrites that day's file and would otherwise make an old day
    look like the most recent send.
    """
    try:
        files = [f for f in EMAILED_DIR.glob("*.txt") if f.is_file()]
    except OSError:
        return None
    if not files:
        return None

    def day_key(f: Path) -> str:
        return f.stem

    newest = max(files, key=day_key)
    try:
        keys = [ln for ln in newest.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
    except OSError:
        keys = []
    try:
        sent_at = dt.datetime.fromtimestamp(newest.stat().st_mtime)
    except OSError:
        sent_at = None
    return {
        "day": newest.stem,
        "sent_at": sent_at.isoformat(timespec="seconds") if sent_at else None,
        "requirements": len(keys),
        "receipt": str(newest),
    }


def describe() -> str:
    info = last_email()
    if info is None:
        return ("No requirements email has ever been sent from this host "
                "(no send receipt under data/requirements/.emailed).")
    when = info["sent_at"] or "unknown time"
    try:
        sent = dt.datetime.fromisoformat(when)
        days = (dt.datetime.now() - sent).days
        ago = ("today" if days == 0 else
               "yesterday" if days == 1 else f"{days} days ago")
        when = f"{sent:%d %b %Y %H:%M} ({ago})"
    except ValueError:
        pass
    return (f"Last requirements email: sent {when}, covering {info['day']}, "
            f"with {info['requirements']} requirement(s).")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true",
                    help="emit the raw record instead of a sentence")
    args = ap.parse_args()
    if args.json:
        print(json.dumps(last_email(), indent=2))
    else:
        print(describe())
    return 0


if __name__ == "__main__":
    sys.exit(main())
