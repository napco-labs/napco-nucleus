"""Cross-process file lock — prevents the cron and `do_it_now` from
running collect_central simultaneously and stepping on each other's
session-doc writes.

Atomic-mkdir lock: lock acquisition is creating a directory (atomic
on every OS). Releasing is removing it. A stale lock from a crashed
process is auto-cleared either when the recorded holder PID is dead
(same host only, instant detection) or after `stale_after_s` mtime
fallback (default 30 min). The lock writes a small `holder.txt`
inside for diagnostics ("who's holding this and since when?").

PID-liveness check matters: a SIGKILL (e.g. OOM-killer) skips the
finally-block that would normally rmdir the lock, so the directory
lingers. Without the liveness check, the next scheduled run could
race the 30-min mtime threshold and abort -- which is exactly what
happened on 2026-05-21 when a runaway python ate 5.2 GB inside the
daily-draft container, got OOM-killed at 22:04, and stalled the
22:30 cron with a 28-minute-old corpse lock.

Usage:
    from tools._lock import file_lock

    with file_lock("collect_central"):
        # exclusive section
        run_pipeline(...)

Or non-blocking:

    with file_lock("collect_central", block=False) as got:
        if not got:
            print("another collect_central is running; aborting.")
            return
        ...
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import socket
import sys
import time
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCK_ROOT = Path(__file__).parent.parent / "data" / "_locks"

_HOLDER_RE = re.compile(r"pid=(?P<pid>\d+)\s+host=(?P<host>\S+)")


def _lock_dir(name: str) -> Path:
    return _LOCK_ROOT / f"{name}.lock"


def _holder_info() -> str:
    return (f"pid={os.getpid()} host={socket.gethostname()} "
            f"started={dt.datetime.now().isoformat(timespec='seconds')}")


def _parse_holder(lock_dir: Path) -> tuple[int, str] | None:
    """Return (pid, host) recorded in holder.txt, or None if not parseable."""
    try:
        raw = (lock_dir / "holder.txt").read_text(encoding="utf-8")
    except OSError:
        return None
    m = _HOLDER_RE.search(raw)
    if not m:
        return None
    try:
        return int(m.group("pid")), m.group("host")
    except (TypeError, ValueError):
        return None


def _holder_dead(lock_dir: Path) -> bool:
    """True iff holder was recorded on THIS host AND its PID is no
    longer alive. Returns False on cross-host locks (can't peek into
    another machine's process table) or when holder.txt is missing."""
    parsed = _parse_holder(lock_dir)
    if parsed is None:
        return False
    pid, host = parsed
    if host != socket.gethostname():
        # Different machine -- we can't observe its process table.
        # Defer to the mtime fallback.
        return False
    try:
        # Signal 0 is the standard "is this pid alive" probe.
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        # Process exists but we lack signal rights -- treat as alive.
        return False
    except OSError:
        return False
    return False


def _stale(lock_dir: Path, stale_after_s: int) -> bool:
    if _holder_dead(lock_dir):
        return True
    try:
        age = time.time() - lock_dir.stat().st_mtime
    except OSError:
        return False
    return age > stale_after_s


@contextmanager
def file_lock(name: str, *, block: bool = True, poll_s: float = 0.5,
              wait_max_s: int = 120, stale_after_s: int = 1800):
    """Acquire an inter-process file lock by atomic mkdir.

    block=True   — wait up to wait_max_s for the lock; raise
                   RuntimeError if not acquired in time
    block=False  — try once; yield True if got the lock, False if not.

    stale_after_s — if an existing lock is older than this, assume the
                    holder crashed and break it. Default 30 minutes —
                    safe upper bound on a normal collect_central run.
    """
    _LOCK_ROOT.mkdir(parents=True, exist_ok=True)
    lock_dir = _lock_dir(name)
    holder_file = lock_dir / "holder.txt"
    start = time.time()
    got = False
    while True:
        try:
            lock_dir.mkdir(parents=False, exist_ok=False)
            got = True
            try:
                holder_file.write_text(_holder_info(), encoding="utf-8")
            except OSError:
                pass
            break
        except FileExistsError:
            # Someone else holds it. Stale?
            if _stale(lock_dir, stale_after_s):
                reason = ("holder PID dead" if _holder_dead(lock_dir)
                          else f"age > {stale_after_s}s")
                logger.warning(
                    "file_lock(%s): breaking stale lock (%s)",
                    name, reason)
                # Best-effort cleanup
                try:
                    holder_file.unlink(missing_ok=True)
                except Exception:
                    pass
                try:
                    lock_dir.rmdir()
                except OSError:
                    pass
                continue  # try again
            if not block:
                break
            if time.time() - start > wait_max_s:
                raise RuntimeError(
                    f"file_lock({name}): not acquired within "
                    f"{wait_max_s}s; another run is holding it.")
            time.sleep(poll_s)

    try:
        yield got
    finally:
        if got:
            try:
                holder_file.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                lock_dir.rmdir()
            except OSError as e:
                logger.warning("file_lock(%s): release failed: %s",
                               name, e)


def lock_status(name: str) -> dict | None:
    """Inspect whether the lock is currently held + by whom. None if
    the lock isn't held. Used by healthcheck for visibility."""
    lock_dir = _lock_dir(name)
    if not lock_dir.exists():
        return None
    holder_file = lock_dir / "holder.txt"
    info = ""
    try:
        info = holder_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    try:
        age = time.time() - lock_dir.stat().st_mtime
    except OSError:
        age = -1
    return {"name": name, "path": str(lock_dir),
            "holder": info, "age_s": round(age, 1)}
