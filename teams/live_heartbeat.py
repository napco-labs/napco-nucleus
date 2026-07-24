"""Live in-call mirror heartbeat -> Central.

While a Teams call is being recorded (the MARKER_FILE '.recording_active'
exists), push a small STATUS json to Central every few seconds at
    <NUCLEUS_CENTRAL_PATH>/<dev>/<YYYY-MM-DD>/live/<stamp>.json
so you can watch the capture happening in REAL TIME on central (elapsed
seconds + mic/speaker bytes climbing), and catch a stuck capture DURING the
call instead of only after it ends.

This does NOT stream the audio bytes -- it is a lightweight beacon that rides
the same open SMB share the finalizer already uses. When the call ends
(marker gone) the beacon is cleared; the real opus tracks land in ../calls/.

Run:  py -3 -m teams.live_heartbeat   (cwd = repo root)
Standalone (no package imports) so it survives independently of record_call.
"""
import os
import json
import time
import socket
import datetime
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).parent
_REPO = _HERE.parent
load_dotenv(_REPO / ".env", override=True)

MARKER_FILE = _REPO / "data" / "teams" / ".recording_active"
POLL_S = 6.0


def _dev_name() -> str:
    raw = (os.environ.get("NUCLEUS_DEV_NAME") or "").strip()
    if raw:
        return raw
    return (os.environ.get("USERNAME") or os.environ.get("USER")
            or socket.gethostname() or "unknown").strip()


def _central_root() -> str:
    return (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()


def _live_dir(day: str):
    root = _central_root()
    if not root:
        return None
    return Path(root) / _dev_name() / day / "live"


def _size(p) -> int:
    try:
        return Path(p).stat().st_size
    except Exception:
        return 0


def main() -> None:
    print(f"[live] heartbeat watcher started (poll={POLL_S}s, "
          f"dev={_dev_name()}, central={_central_root() or 'UNSET'})")
    active_stamp = None
    active_day = None
    while True:
        try:
            if MARKER_FILE.exists():
                m = json.loads(MARKER_FILE.read_text(encoding="utf-8"))
                stamp = m.get("stamp", "")
                out_dir = m.get("out_dir", "")
                spk = m.get("spk_path") or str(
                    Path(out_dir) / f"{stamp}_speaker.wav")
                mic = m.get("mic_path") or str(
                    Path(out_dir) / f"{stamp}_mic.wav")
                try:
                    started = datetime.datetime.fromisoformat(m["started_at"])
                except Exception:
                    started = datetime.datetime.now()
                day = started.strftime("%Y-%m-%d")

                live_dir = _live_dir(day)
                if live_dir is not None and stamp:
                    live_dir.mkdir(parents=True, exist_ok=True)
                    mic_b, spk_b = _size(mic), _size(spk)
                    elapsed = (datetime.datetime.now()
                               - started).total_seconds()
                    payload = {
                        "state": "RECORDING",
                        "stamp": stamp,
                        "host": socket.gethostname(),
                        "dev": _dev_name(),
                        "started_at": started.isoformat(timespec="seconds"),
                        "elapsed_s": round(elapsed, 1),
                        "mic_bytes": mic_b,
                        "speaker_bytes": spk_b,
                        "total_mb": round((mic_b + spk_b) / 1048576, 2),
                        "updated_at": datetime.datetime.now().isoformat(
                            timespec="seconds"),
                    }
                    # atomic publish so a reader never sees a half file
                    tmp = live_dir / f".{stamp}.json.tmp"
                    dst = live_dir / f"{stamp}.json"
                    tmp.write_text(json.dumps(payload, indent=2),
                                   encoding="utf-8")
                    os.replace(str(tmp), str(dst))
                    print(f"[live] {stamp} elapsed={elapsed:.0f}s "
                          f"mic={mic_b/1048576:.1f}MB "
                          f"spk={spk_b/1048576:.1f}MB -> central/live")
                    active_stamp, active_day = stamp, day
            else:
                # call ended (marker renamed to .finalizing_*): clear beacon.
                if active_stamp and active_day:
                    ld = _live_dir(active_day)
                    if ld is not None:
                        try:
                            (ld / f"{active_stamp}.json").unlink()
                            print(f"[live] {active_stamp} ended; "
                                  f"cleared live beacon")
                        except FileNotFoundError:
                            pass
                        except Exception as e:
                            print(f"[live] beacon clear failed: {e}")
                    active_stamp = active_day = None
            time.sleep(POLL_S)
        except Exception as e:
            print(f"[live] loop error: {e}")
            time.sleep(POLL_S)


if __name__ == "__main__":
    main()
