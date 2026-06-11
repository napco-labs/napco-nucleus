#!/usr/bin/env python3
"""Re-stamp central-share file/folder mtimes from the embedded call stamp.

WHY: calls are pushed to central by the live daemon and (for stranded
calls) by `backfill_central`. Both write files at *push time*, so every
file and day-folder ends up with a "Date modified" of whenever the push
ran — e.g. a whole month of day-folders all showing the backfill date.
Browsing the share in Explorer then sorts/looks wrong: the date column
tells you nothing about when the call actually happened (2026-06-11).

FIX: every call file is named `YYYYMMDD-HHMMSS_*` — that stamp is the
real call time. This walks the central root and sets:
  * each call file's mtime   -> its own filename stamp
  * each folder's mtime      -> the latest stamp found anywhere beneath it
so the "Date modified" column reflects real call chronology and sorts
correctly. Idempotent and safe to run repeatedly (skips files already
within 1s of target); folders with no stamped files are left untouched.

Usage (on .123):
  python3 tools/normalize_central_mtimes.py --root /srv/nucleus-central
  python3 tools/normalize_central_mtimes.py --root /srv/nucleus-central --quiet
  python3 tools/normalize_central_mtimes.py --root /srv/nucleus-central --dry-run
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime

# Matches the call stamp anywhere in a name: 20260609-205603
_STAMP = re.compile(r"(\d{8})-(\d{6})")


def _stamp_epoch(name: str) -> float | None:
    """Return the local-time epoch for the YYYYMMDD-HHMMSS stamp in `name`,
    or None if there isn't one / it isn't a real datetime. The host TZ is
    Asia/Dhaka and the stamps are BD-local, so mktime (local) is correct."""
    m = _STAMP.search(name)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return time.mktime(dt.timetuple())


def _set_mtime(path: str, epoch: float, dry: bool) -> bool:
    """Set atime+mtime of `path` to `epoch`. Returns True if it changed
    (more than 1s off). Never raises — logs and moves on."""
    try:
        if abs(os.path.getmtime(path) - epoch) <= 1.0:
            return False
        if not dry:
            os.utime(path, (epoch, epoch))
        return True
    except OSError as e:
        print(f"[normalize] warn: {path}: {e}", file=sys.stderr)
        return False


def normalize(root: str, dry: bool, quiet: bool) -> int:
    changed = 0
    # Bottom-up so a folder's mtime is set AFTER its children, and so a
    # parent can inherit the max stamp of everything beneath it.
    dir_max: dict[str, float] = {}
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        latest = 0.0
        for fn in filenames:
            ep = _stamp_epoch(fn)
            if ep is None:
                continue
            latest = max(latest, ep)
            if _set_mtime(os.path.join(dirpath, fn), ep, dry):
                changed += 1
        # fold in any already-computed child-dir maxima
        for d in dirnames:
            cm = dir_max.get(os.path.join(dirpath, d), 0.0)
            latest = max(latest, cm)
        dir_max[dirpath] = latest
        if latest > 0.0 and _set_mtime(dirpath, latest, dry):
            changed += 1
            if not quiet:
                when = datetime.fromtimestamp(latest).strftime(
                    "%Y-%m-%d %H:%M:%S")
                print(f"[normalize] {dirpath} -> {when}")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default="/srv/nucleus-central",
                    help="central share root (default: /srv/nucleus-central)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change, touch nothing")
    ap.add_argument("--quiet", action="store_true",
                    help="only print the final count (for cron)")
    a = ap.parse_args()
    if not os.path.isdir(a.root):
        print(f"[normalize] root not found: {a.root}", file=sys.stderr)
        return 1
    n = normalize(a.root, a.dry_run, a.quiet)
    verb = "would update" if a.dry_run else "updated"
    print(f"[normalize] {verb} {n} mtime(s) under {a.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
