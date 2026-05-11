"""Stage new Google Drive files into the central share.

Runs on MVPACCESS via Task Scheduler every 15 min, mirroring the
chat-push and stage_email cadence. Background capture; not triggered
by the operator.

What it does:
  1. List files in GDRIVE_AUDIO_FOLDER_ID (Drive service account).
  2. For each file NOT already in the drive_processed table:
       - download the bytes
       - copy to <central>/drive/<YYYY-MM-DD>/<file-name>
         (date = the file's createdTime; falls back to today)
       - record (file_id, name, output_path) in drive_processed
  3. Skip already-staged files — drive_processed is the dedup table.

The requirement-management workflow still does its own live pull, so
this is purely an additive audit trail. Central now permanently holds
a record of every Drive file processed, matching how chat / calls /
email are staged.

Usage:
  py -3 -m tools.stage_drive                    # incremental
  py -3 -m tools.stage_drive --dry-run          # plan only
  py -3 -m tools.stage_drive --reset-state      # treat all files as new
                                                # (for one-time backfill)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import tempfile
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


def _central_drive_dir(created_dt: dt.datetime | None) -> Path | None:
    raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    if not raw:
        return None
    day = (created_dt or dt.datetime.now()).strftime("%Y-%m-%d")
    return Path(raw) / "drive" / day


def _safe_filename(name: str) -> str:
    import re
    forbidden = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
    base = Path(name).name or "file"
    return forbidden.sub("_", base).strip(" .") or "file"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan only, no downloads or state writes.")
    ap.add_argument("--reset-state", action="store_true",
                    help="Treat every file as new (clears the local "
                         "drive_processed table before scanning). "
                         "One-shot backfill mode — use carefully.")
    args = ap.parse_args()

    folder = (os.environ.get("GDRIVE_AUDIO_FOLDER_ID") or "").strip()
    if not folder:
        print("GDRIVE_AUDIO_FOLDER_ID not set; aborting.", file=sys.stderr)
        return 2

    try:
        from drive import drive_ingester as di  # lazy
    except Exception as e:
        print(f"failed to import drive_ingester: {e}", file=sys.stderr)
        return 2

    if args.reset_state and not args.dry_run:
        try:
            import sqlite3
            with sqlite3.connect(memory.db_path()) as c:
                c.execute("DELETE FROM drive_processed")
                c.commit()
            print("  reset drive_processed table.")
        except Exception as e:
            print(f"  ! reset failed: {e}", file=sys.stderr)

    print(f"Stage Drive — folder {folder}")

    try:
        drive = di._drive_service()
    except Exception as e:
        print(f"Drive auth error: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 2

    try:
        files = di._list_ingestable_files(drive, folder)
    except Exception as e:
        print(f"Drive list error: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 2

    print(f"  found {len(files)} ingestable file(s) in folder")

    staged = 0
    skipped = 0
    errors = 0
    for f in files:
        fid = f.get("id") or ""
        name = f.get("name") or "(unnamed)"
        if not fid:
            continue

        # SQLite drive_processed is the dedup record shared between the
        # cron + the workflow's pull_drive subprocess.
        if memory.is_drive_processed(fid):
            skipped += 1
            continue

        # Parse createdTime to pick the date dir
        ct = f.get("createdTime") or ""
        created_dt = None
        try:
            iso = ct.replace("Z", "+00:00")
            created_dt = dt.datetime.fromisoformat(iso).astimezone()
            created_dt = created_dt.replace(tzinfo=None)
        except Exception:
            created_dt = None

        central_dir = _central_drive_dir(created_dt)
        if central_dir is None:
            print("  ! NUCLEUS_CENTRAL_PATH not set; can't stage to central")
            return 2

        safe = _safe_filename(name)
        target = central_dir / safe

        if target.exists():
            # Same name + size? mark processed
            try:
                if target.stat().st_size > 0:
                    _record_drive(fid, name, str(target))
                    skipped += 1
                    continue
            except OSError:
                pass

        if args.dry_run:
            print(f"  [dry-run] {name} -> {target}")
            staged += 1
            continue

        try:
            # Download to a temp file first, then copy to central.
            with tempfile.NamedTemporaryFile(
                    delete=False, suffix=Path(name).suffix or "") as tmp:
                tmp_path = Path(tmp.name)
            try:
                di._download_file(drive, fid, tmp_path)
                central_dir.mkdir(parents=True, exist_ok=True)
                # If collision with a different-size file, append the
                # file_id as a uniquifier.
                if target.exists() and target.stat().st_size != tmp_path.stat().st_size:
                    stem = target.stem
                    suff = target.suffix
                    target = central_dir / f"{stem}__{fid[:8]}{suff}"
                import shutil as _sh
                _sh.copy2(str(tmp_path), str(target))
            finally:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            kind = di._classify(f) or "staged"
            memory.mark_drive_processed(fid, name, kind, str(target))
            staged += 1
            print(f"  + {name} -> {target}")
        except Exception as e:
            errors += 1
            print(f"  ! {name}: {type(e).__name__}: {e}", file=sys.stderr)

    print(f"\nResult: staged={staged} skipped={skipped} errors={errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
