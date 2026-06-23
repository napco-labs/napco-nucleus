"""Re-push local call recordings that never made it to the central share.

The live push in ``record_call._postprocess_and_upload`` is best-effort and
fires exactly once when a call ends. If the central share is momentarily
unreachable (network blip, laptop on the wrong VLAN, SMB auth not yet
mounted) the copy fails, the daemon logs ``central upload FAILED``, and the
WAVs + metadata are left **local only** — there is no retry. Over time a
dev's machine accumulates calls that ``collect_central`` on the agent host
can never see.

This script closes that gap. It scans the dev's local calls directory,
works out where each call *should* live on central (keyed off the call's
own timestamp, NOT today's date), and copies up anything that is missing or
size-mismatched. Safe to run repeatedly — it skips files already present on
central with a matching size, so a daily scheduled run just heals whatever
slipped through.

Layout it mirrors (same as the live push):

    <NUCLEUS_CENTRAL_PATH>/<dev>/<YYYY-MM-DD>/calls/<stamp>_mic.wav
                                                    <stamp>_speaker.wav
                                                    <stamp>.json

The <YYYY-MM-DD> day is taken from each call's metadata ``started_at`` when
present, else parsed from the ``<YYYYMMDD-HHMMSS>`` stamp. This matches
where the call would have landed had the original push succeeded, so
``collect_central --day`` finds it.

Usage
    python -m teams.backfill_central                  # push everything missing
    python -m teams.backfill_central --dry-run        # show plan, copy nothing
    python -m teams.backfill_central --day 2026-06-09 # only that day's calls
    python -m teams.backfill_central --force          # re-copy even if present

Env
    NUCLEUS_CENTRAL_PATH    required (UNC or local path to the central root)
    NUCLEUS_DEV_NAME        optional; defaults to USERNAME / hostname
    NUCLEUS_SAMBA_USER      optional; mounts the share before copying
    NUCLEUS_SAMBA_PASSWORD  optional; pairs with NUCLEUS_SAMBA_USER
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import socket
import sys
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).parent
_REPO = _HERE.parent
load_dotenv(_REPO / ".env", override=True)

sys.path.insert(0, str(_REPO))

from teams._central import ensure_smb_auth  # noqa: E402

LOCAL_CALLS_DIR = _REPO / "data" / "teams" / "calls"


def _dev_name() -> str:
    """Same resolution order as record_call._dev_name (kept in sync)."""
    raw = (os.environ.get("NUCLEUS_DEV_NAME") or "").strip()
    if raw:
        return raw
    return (os.environ.get("USERNAME") or os.environ.get("USER")
            or socket.gethostname() or "unknown").strip()


def _day_for_call(stamp: str, metadata: dict) -> str | None:
    """Return YYYY-MM-DD for a call, preferring metadata over the stamp.

    The live push files a call under the day it ENDED (date.today() at
    upload). We don't have that here, so we use the call's start instead:
    metadata.started_at if it parses, else the date embedded in the stamp.
    For all non-midnight-straddling calls these are identical, and
    collect_central scans yesterday too, so straddles are still caught.
    """
    started = (metadata or {}).get("started_at")
    if isinstance(started, str) and started:
        try:
            return dt.datetime.fromisoformat(started).strftime("%Y-%m-%d")
        except ValueError:
            pass
    # Fall back to the <YYYYMMDD-HHMMSS> stamp.
    try:
        return dt.datetime.strptime(stamp[:8], "%Y%m%d").strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        return None


def _needs_copy(src: Path, dst: Path, force: bool) -> bool:
    if force:
        return True
    if not dst.exists():
        return True
    try:
        return src.stat().st_size != dst.stat().st_size
    except OSError:
        return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", default=None,
                    help="Only back-fill calls for this YYYY-MM-DD.")
    ap.add_argument("--dry-run", action="store_true",
                    help="List what would be pushed but copy nothing.")
    ap.add_argument("--force", action="store_true",
                    help="Re-copy even when central already has the file.")
    args = ap.parse_args()

    central_raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    if not central_raw:
        print("NUCLEUS_CENTRAL_PATH is not set. Add it to .env and re-run.",
              file=sys.stderr)
        return 2
    central = Path(central_raw)
    dev = _dev_name()

    if not LOCAL_CALLS_DIR.exists():
        print(f"No local calls dir at {LOCAL_CALLS_DIR} — nothing to do.")
        return 0

    metas = sorted(LOCAL_CALLS_DIR.glob("*.json"))
    if not metas:
        print(f"No call metadata in {LOCAL_CALLS_DIR} — nothing to do.")
        return 0

    print(f"*** backfill_central: dev={dev!r}  central={central} ***")
    if not args.dry_run:
        ensure_smb_auth(central_raw)
    if not central.exists():
        print(f"central path not reachable: {central}\n"
              f"  Check NUCLEUS_CENTRAL_PATH and that the share is mounted "
              f"(net use {central}).", file=sys.stderr)
        return 3

    pushed = skipped = failed = 0
    calls_seen = 0

    for meta_path in metas:
        stamp = meta_path.stem
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            print(f"  WARN: can't read {meta_path.name}: {e} — using stamp date",
                  file=sys.stderr)
            metadata = {}

        day = _day_for_call(stamp, metadata)
        if day is None:
            print(f"  WARN: can't derive a day for {stamp} — skipping",
                  file=sys.stderr)
            continue
        if args.day and day != args.day:
            continue

        calls_seen += 1
        dst_dir = central / dev / day / "calls"

        # Tracks are Opus once compressed at capture; raw WAV if ffmpeg was
        # unavailable. List both — the .exists() filter keeps whichever landed.
        srcs = [meta_path,
                LOCAL_CALLS_DIR / f"{stamp}_mic.opus",
                LOCAL_CALLS_DIR / f"{stamp}_speaker.opus",
                LOCAL_CALLS_DIR / f"{stamp}_mic.wav",
                LOCAL_CALLS_DIR / f"{stamp}_speaker.wav"]
        present = [s for s in srcs if s.exists()]
        to_copy = [s for s in present if _needs_copy(s, dst_dir / s.name, args.force)]

        if not to_copy:
            skipped += 1
            print(f"  ok    {dev}/{day}/{stamp}  (already on central)")
            continue

        names = ", ".join(s.name.replace(stamp, "<stamp>") for s in to_copy)
        if args.dry_run:
            print(f"  PUSH  {dev}/{day}/{stamp}  -> {dst_dir}  [{names}]")
            pushed += 1
            continue

        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            for src in to_copy:
                dst = dst_dir / src.name
                shutil.copy2(str(src), str(dst))
                size_mb = src.stat().st_size / 1024 / 1024
                print(f"  ->    {dst}  ({size_mb:.1f} MB)")
            print(f"  PUSH  {dev}/{day}/{stamp}  OK [{names}]")
            pushed += 1
        except Exception as e:
            print(f"  FAIL  {dev}/{day}/{stamp}: {e}", file=sys.stderr)
            failed += 1

    verb = "would push" if args.dry_run else "pushed"
    print(f"\nScanned {calls_seen} call(s): {verb} {pushed}, "
          f"skipped {skipped} (already present), failed {failed}.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
