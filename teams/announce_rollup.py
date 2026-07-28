"""Tell the team, in Teams, that the requirements email has gone out.

Requirement 9 (Titu, 2026-07-27): "After sending email, it will notify all the
team members that requirement email has been sent. Please have a look."

Why a marker file rather than doing it inline: the requirement pipeline and the
mail send run in a container on the Linux central host, which has no Teams and
no desktop. Only the Windows assistant box can drive Teams. So mail/daily_rollup
drops a JSON breadcrumb into <central>/.rollup_sent/ after a successful send,
and this script -- running on the assistant box -- picks it up and announces it.

Safeguards, because this messages every developer at once:
  * each marker is announced EXACTLY once (the marker is stamped `announced`)
  * markers older than STALE_HOURS are retired silently, never announced, so a
    box that was offline for a day does not wake up and spam everyone
  * 1:1 direct messages only, never a group or meeting chat
  * a per-person send failure is logged and skipped, never retried in a loop
  * announcing is independent of the reminder cap in remind_devs -- this is a
    factual notification about work delivered, not a nudge

Run:  py -3 -m teams.announce_rollup            (scheduled, every few minutes)
      py -3 -m teams.announce_rollup --dry-run  (show what it would send)
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

_HERE = Path(__file__).parent
_REPO = _HERE.parent
LOG = _REPO / "logs" / "announce_rollup.log"
DEV_LIST_FILE = _HERE / "dev_list.json"

STALE_HOURS = 12.0

# Gap between the seven announcements, jittered.
#
# This was 4 seconds. Seven near-identical messages from one account inside a
# minute is the exact shape consumer anti-abuse systems are built to catch, and
# this account is a personal one whose termination would be unrecoverable
# (docs/MICROSOFT-POLICY-AUDIT.md, item B). Titu has already lost a LinkedIn
# account to automated-activity enforcement, so this is a real cost, not a
# theoretical one.
#
# 40-100s spreads the same seven messages over roughly 5-10 minutes, which
# reads like somebody working down their chat list. Nobody is waiting on these:
# the email has already been sent, this is only the nudge to go and read it.
SEND_GAP_MIN_S = 40.0
SEND_GAP_MAX_S = 100.0


def log(msg: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        import datetime
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (datetime.datetime.now()
                                 .strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _central() -> Path:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env", override=True)
    raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    if not raw:
        raise RuntimeError("NUCLEUS_CENTRAL_PATH not set")
    return Path(raw) / ".rollup_sent"


def _devs() -> list[dict]:
    """Everyone to announce to, as {name, search}. Uses the same dev list the
    reminder uses, so there is one roster to maintain."""
    try:
        data = json.loads(DEV_LIST_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log("dev_list unreadable: %s" % e)
        return []
    out = []
    for d in data.get("devs", []):
        if isinstance(d, dict):
            search = (d.get("search") or d.get("chat") or d.get("name") or "").strip()
            name = (d.get("name") or search).strip()
            if search:
                out.append({"name": name, "search": search})
    return out


def _message(marker: dict, first: str) -> str:
    """Short, respectful, factual. No emoji -- this is a work notification."""
    n = marker.get("requirements", 0)
    day = marker.get("day", "")
    what = "requirement" if n == 1 else "requirements"
    return (
        "%s bhai, the %s email for %s has been sent with %d %s. "
        "Please have a look when you get a moment."
        % (first, "requirements", day, n, what)
    )


def _pending(dirp: Path) -> list[Path]:
    if not dirp.exists():
        return []
    return sorted(p for p in dirp.glob("*.json") if p.is_file())


def main() -> int:
    dry = "--dry-run" in sys.argv
    try:
        dirp = _central()
    except Exception as e:
        log("central unavailable: %s" % e)
        return 1

    pending = _pending(dirp)
    if not pending:
        return 0

    devs = _devs()
    if not devs:
        log("no devs in dev_list - nothing to announce to")
        return 1

    from teams import dev_names, notify

    for mpath in pending:
        try:
            marker = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception as e:
            log("unreadable marker %s: %s" % (mpath.name, e))
            continue

        if marker.get("announced"):
            continue

        age_h = (time.time() - mpath.stat().st_mtime) / 3600.0
        if age_h > STALE_HOURS:
            marker["announced"] = True
            marker["skipped"] = "stale (%.1fh)" % age_h
            mpath.write_text(json.dumps(marker, indent=2), encoding="utf-8")
            log("retired stale marker %s (%.1fh old), announced nobody"
                % (mpath.name, age_h))
            continue

        # CLAIM the marker before sending anything, not after.
        #
        # The task repeats every 5 minutes and a paced run now takes 5-10, so
        # the next run can start while this one is still working down the
        # list. Stamping only at the end would let two runs announce the same
        # email and message all seven people twice, which is both embarrassing
        # and precisely the burst pattern the pacing exists to avoid.
        #
        # Claiming first means a crash mid-run leaves some people un-nudged.
        # That is the better failure: the email itself has already been sent,
        # so the worst case is somebody reads it a bit later.
        if not dry:
            marker["announced"] = True
            marker["announced_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            marker["claimed"] = True
            mpath.write_text(json.dumps(marker, indent=2), encoding="utf-8")

        sent, failed = [], []
        for d in devs:
            first = dev_names.resolve(d["name"], default="bhai") or "bhai"
            text = _message(marker, first)
            if dry:
                print("  -> %-22s %s" % (d["search"], text))
                sent.append(d["search"])
                continue
            try:
                ok = notify.send(d["search"], text)
            except Exception as e:
                ok = False
                log("send to %s raised: %s" % (d["search"], str(e)[:120]))
            (sent if ok else failed).append(d["search"])
            # jittered, because a constant gap is itself a machine signature
            time.sleep(random.uniform(SEND_GAP_MIN_S, SEND_GAP_MAX_S))

        if not dry:
            # already claimed above; record the outcome
            marker["announced_to"] = sent
            marker["failed"] = failed
            marker.pop("claimed", None)
            mpath.write_text(json.dumps(marker, indent=2), encoding="utf-8")

        log("announced %s: %d sent, %d failed%s"
            % (mpath.name, len(sent), len(failed), " (dry-run)" if dry else ""))

    return 0


if __name__ == "__main__":
    sys.exit(main())
