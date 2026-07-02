"""Prune old call/chat/email data from the central share to bound disk use.

Central (.123) has limited storage. This walks the per-dev date-partitioned
folders (<central>/<Dev>/<YYYY-MM-DD>/...) and the shared email/<YYYY-MM-DD>/
folder, and deletes any date folder older than --keep-days (default 3,
today inclusive).

Does NOT touch:
  - /srv/nucleus-central/tools/, _staging/ (infra binaries/cache, not call data)
  - /srv/nucleus-data (processed output: memory.db, verification docs) —
    entirely separate volume, this script never looks there
  - a call session whose WAVs/opus exist but has no transcript yet AND no
    poison-pill failure marker (*.transcribe_failures at the max-retry
    count) — logged and skipped rather than deleted, so an orphaned/slow
    session is never destroyed before transcribe_calls.py gets to it.

Usage:
    py -3 -m tools.central_retention                    # dry-run, keep 3 days
    py -3 -m tools.central_retention --keep-days 5
    py -3 -m tools.central_retention --yes               # actually delete
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_HERE / ".env", override=False)

MAX_TRANSCRIBE_FAILURES = 5  # mirrors tools/transcribe_calls.py

_NON_DEV_DIRS = {"tools", "_staging", "_locks", "drive", "email"}


def _central_root() -> Path | None:
    raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    return Path(raw) if raw else None


def _parse_date(name: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(name, "%Y-%m-%d").date()
    except ValueError:
        return None


def _calls_dir_is_safe_to_delete(calls_dir: Path) -> tuple[bool, str]:
    """A calls/ folder is unsafe to delete if it holds a session that has
    audio but no transcript and hasn't exhausted its retry budget yet —
    that's still live work for transcribe_calls.py."""
    if not calls_dir.is_dir():
        return True, ""
    for mic in calls_dir.glob("*_mic.*"):
        session = mic.stem.rsplit("_mic", 1)[0]
        transcript = calls_dir / f"{session}_transcript.md"
        if transcript.exists():
            continue
        fail_marker = calls_dir / f"{session}.transcribe_failures"
        count = 0
        if fail_marker.exists():
            try:
                count = int(fail_marker.read_text().strip())
            except Exception:
                count = 0
        if count < MAX_TRANSCRIBE_FAILURES:
            return False, f"session {session} has no transcript yet (failures={count})"
    return True, ""


def _candidate_date_dirs(root: Path) -> list[tuple[Path, dt.date, str]]:
    """Return (date_dir_path, date, owner_label) for every date-partitioned
    folder under root: <root>/<Dev>/<YYYY-MM-DD>/ and <root>/email/<YYYY-MM-DD>/."""
    out: list[tuple[Path, dt.date, str]] = []
    try:
        top = [d for d in root.iterdir() if d.is_dir()]
    except OSError as e:
        print(f"[retention] cannot list {root}: {e}", file=sys.stderr)
        return out

    for entry in top:
        if entry.name == "email":
            for day_dir in entry.iterdir() if entry.is_dir() else []:
                d = _parse_date(day_dir.name)
                if d is not None and day_dir.is_dir():
                    out.append((day_dir, d, "email"))
            continue
        if entry.name in _NON_DEV_DIRS:
            continue
        # Per-dev folder: <root>/<Dev>/<YYYY-MM-DD>/
        for day_dir in entry.iterdir() if entry.is_dir() else []:
            d = _parse_date(day_dir.name)
            if d is not None and day_dir.is_dir():
                out.append((day_dir, d, entry.name))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep-days", type=int, default=3,
                    help="Keep this many most-recent calendar days "
                         "(today inclusive). Default: 3.")
    ap.add_argument("--yes", action="store_true",
                    help="Actually delete. Without this flag, dry-run only.")
    args = ap.parse_args()

    root = _central_root()
    if root is None or not root.exists():
        print(f"NUCLEUS_CENTRAL_PATH not set or not reachable: {root}",
              file=sys.stderr)
        return 2

    today = dt.date.today()
    cutoff = today - dt.timedelta(days=args.keep_days - 1)
    print(f"[retention] central={root}  keep-days={args.keep_days}  "
          f"cutoff={cutoff} (deleting anything strictly before this date)")

    candidates = _candidate_date_dirs(root)
    to_delete: list[tuple[Path, dt.date, str]] = []
    skipped_recent = 0
    for path, d, owner in candidates:
        if d >= cutoff:
            skipped_recent += 1
            continue
        to_delete.append((path, d, owner))

    if not to_delete:
        print(f"[retention] nothing older than {cutoff}. "
              f"({skipped_recent} recent date-folder(s) kept)")
        return 0

    total_bytes = 0
    blocked: list[tuple[Path, str]] = []
    final: list[tuple[Path, dt.date, str, int]] = []
    for path, d, owner in sorted(to_delete, key=lambda t: (t[2], t[1])):
        calls_dir = path / "calls"
        safe, reason = _calls_dir_is_safe_to_delete(calls_dir)
        if not safe:
            blocked.append((path, reason))
            continue
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        total_bytes += size
        final.append((path, d, owner, size))

    for path, d, owner, size in final:
        print(f"  {'[DELETE]' if args.yes else '[would delete]'} "
              f"{owner}/{d}  ({size / (1024*1024):.1f} MB)  {path}")
    for path, reason in blocked:
        print(f"  [SKIP-unsafe] {path} — {reason}")

    print(f"\n[retention] {len(final)} date-folder(s), "
          f"{total_bytes / (1024*1024*1024):.2f} GB total older than {cutoff}"
          f"{f', {len(blocked)} blocked (unsafe)' if blocked else ''}")

    if not args.yes:
        print("[retention] dry-run only — pass --yes to actually delete.")
        return 0

    deleted, failed = 0, 0
    for path, d, owner, size in final:
        try:
            shutil.rmtree(path)
            deleted += 1
        except OSError as e:
            print(f"  [FAILED] {path}: {e}", file=sys.stderr)
            failed += 1

    print(f"[retention] done: deleted={deleted}  failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
