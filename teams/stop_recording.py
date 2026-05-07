"""Signal a running `teams.record_call` to stop cleanly.

Creates a sentinel file the recorder polls every ~0.5s. Once it sees
the file, it sets the thread-stop event, the WAV writers close cleanly,
and the recorder exits.

Use:  python -m teams.stop_recording
"""
from __future__ import annotations

from pathlib import Path

from teams.record_call import STOP_FILE


def main() -> int:
    STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    STOP_FILE.touch(exist_ok=True)
    print(f"Wrote stop sentinel: {STOP_FILE}")
    print("The recorder will close WAVs and exit within ~1 second.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
