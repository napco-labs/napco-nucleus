"""Auto-transcribe new calls landing on the central share.

Runs on the agent host (MVPACCESS) as a Scheduled Task every couple of
minutes. Walks <NUCLEUS_CENTRAL_PATH>/<dev>/<date>/calls/ for the
configured day window, finds every completed call session that doesn't
yet have a transcript, and transcribes it in place. Loads the
faster-whisper model once per run.

Completion signal:
    <session>.json exists.
    record_call.py copies mic.wav -> speaker.wav -> <session>.json in
    that order, so the metadata JSON only lands after both WAVs are
    fully on central. That's the "this call is done uploading" marker.

Idempotent — sessions that already have <session>_transcript.md next to
the WAVs are skipped. Cross-process safe via tools._lock.file_lock; a
second invocation while one is running aborts immediately so the
2-minute cron can't pile up overlapping Whisper runs.

Why on the agent host:
    faster-whisper large-v3 is CPU-heavy. Doing it on each dev's PC
    pegs the laptop right after a call. Centralising onto MVPACCESS
    keeps dev machines responsive and gives consistent perf across the
    team.

Usage:
    py -3 -m tools.transcribe_calls
    py -3 -m tools.transcribe_calls --days 3
    py -3 -m tools.transcribe_calls --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
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
from tools._lock import file_lock  # noqa: E402

logger = logging.getLogger(__name__)


def _central_root() -> Path | None:
    raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    return Path(raw) if raw else None


def _day_dirs(root: Path, days: int) -> list[Path]:
    """Today + the previous (days-1) days for every dev folder under root."""
    today = dt.date.today()
    out: list[Path] = []
    try:
        dev_dirs = [d for d in root.iterdir() if d.is_dir()]
    except OSError as e:
        logger.error("cannot list central root %s: %s", root, e)
        return out
    for dev in dev_dirs:
        for i in range(days):
            day = (today - dt.timedelta(days=i)).strftime("%Y-%m-%d")
            calls = dev / day / "calls"
            if calls.exists():
                out.append(calls)
    return out


def _pending_sessions(calls_dir: Path) -> list[str]:
    """Session prefixes (e.g. '20260513-203305') with metadata present
    but no transcript yet."""
    pending: list[str] = []
    for meta in sorted(calls_dir.glob("*.json")):
        session = meta.stem
        if (calls_dir / f"{session}_transcript.md").exists():
            continue
        if not (calls_dir / f"{session}_mic.wav").exists():
            continue
        if not (calls_dir / f"{session}_speaker.wav").exists():
            continue
        pending.append(session)
    return pending


def _scan(root: Path, days: int) -> list[tuple[Path, str]]:
    work: list[tuple[Path, str]] = []
    for calls_dir in _day_dirs(root, days):
        for session in _pending_sessions(calls_dir):
            work.append((calls_dir, session))
    return work


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=2,
                    help="How many days back to scan (default: 2 — "
                         "today + yesterday, catches calls that ended "
                         "across midnight).")
    ap.add_argument("--dry-run", action="store_true",
                    help="List pending sessions without transcribing.")
    args = ap.parse_args()

    root = _central_root()
    if root is None:
        print("NUCLEUS_CENTRAL_PATH not set; aborting.", file=sys.stderr)
        return 2
    if not root.exists():
        print(f"Central path not reachable: {root}", file=sys.stderr)
        return 2

    print(f"Transcribe calls — central={root}  days={args.days}")
    work = _scan(root, args.days)
    if not work:
        print("  nothing to transcribe.")
        memory.log_activity(
            task_name="transcribe-calls:scan",
            result="ok:0",
            technical_details={"pending": 0, "days": args.days})
        return 0

    print(f"  pending: {len(work)} session(s)")
    for calls_dir, session in work:
        print(f"    {calls_dir.parent.parent.name}/{calls_dir.parent.name}/{session}")

    if args.dry_run:
        memory.log_activity(
            task_name="transcribe-calls:scan",
            result=f"dry_run:{len(work)}",
            technical_details={"pending": len(work), "days": args.days})
        return 0

    # Non-blocking lock — if a previous run is still going, skip this tick.
    with file_lock("transcribe_calls", block=False) as got:
        if not got:
            print("  another transcribe-calls run is in progress; "
                  "skipping this tick.")
            memory.log_activity(
                task_name="transcribe-calls:scan",
                result="skipped:locked",
                technical_details={"pending": len(work)})
            return 0

        # Lazy import — heavy module load only when there's real work.
        from teams.transcribe_call import load_model, transcribe_session

        print("  loading faster-whisper (one-time per run)...")
        model = load_model()

        ok, failed = 0, 0
        for calls_dir, session in work:
            try:
                transcribe_session(
                    session=session,
                    calls_dir=calls_dir,
                    output_dir=calls_dir,
                    model=model,
                )
                ok += 1
            except Exception as e:
                logger.exception("transcribe failed: %s/%s",
                                 calls_dir, session)
                print(f"  FAILED {session}: {e}", file=sys.stderr)
                failed += 1

        print(f"  done: {ok} transcribed, {failed} failed.")
        memory.log_activity(
            task_name="transcribe-calls:run",
            result=f"ok:{ok}/failed:{failed}",
            technical_details={"transcribed": ok, "failed": failed,
                               "days": args.days})
        return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
