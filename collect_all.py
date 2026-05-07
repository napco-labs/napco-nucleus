"""
End-to-end one-shot: pull from all 4 channels, then identify and draft.

Runs the full requirement-management flow in sequence:
  1. Teams chat from every chat in the registry           --all-chats
  2. Email from your IMAP inbox                           any sender / subject
  3. Google Drive files from the configured folder
  4. Latest call recording (if one was captured recently)  Whisper transcribe
  5. Identify requirements + draft client email           agent verify_session

Each run RESETS the pull-session doc by default (the previous one is
archived) so the batch is clean. Pass --no-reset to keep accumulating
into the existing session.

The verify step (5) checks each candidate requirement against
requirements_seen and skips ones that were already drafted in prior
runs — so running collect_all every 30/60 min won't re-draft the same
requirement repeatedly. New requirements are saved into the table at
the end so the next run dedups them.

The final draft is pushed to your Outlook / Gmail Drafts folder for
manual review and send.

Usage:
    python collect_all.py                       # default: last 15 min, reset
    python collect_all.py --last-minutes 30
    python collect_all.py --last-minutes 60
    python collect_all.py --last-minutes 60 --no-reset   # accumulate
    python collect_all.py --skip-meeting        # don't transcribe call audio

Env:
    VERIFICATION_TO   default client recipient (or set in .env)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env", override=True)


def _run(label: str, cmd: list[str]) -> int:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  $ {' '.join(cmd)}")
    print(f"{'='*60}")
    rc = subprocess.call(cmd, cwd=str(_HERE))
    if rc != 0:
        print(f"  ! exit code {rc} — continuing", file=sys.stderr)
    return rc


def _latest_recording_age_seconds() -> float | None:
    calls_dir = _HERE / "data" / "teams" / "calls"
    if not calls_dir.is_dir():
        return None
    mics = list(calls_dir.glob("*_mic.wav"))
    if not mics:
        return None
    latest = max(mics, key=lambda p: p.stat().st_mtime)
    return time.time() - latest.stat().st_mtime


def _maybe_reset(label: str | None) -> None:
    """Archive the current session and start a fresh one."""
    sys.path.insert(0, str(_HERE))
    from tools import _session_doc as sd  # noqa: E402
    result = sd.reset(label=label or f"collect_all-{int(time.time())}")
    print(f"\nSession reset. New session: {result['session_path']} "
          f"(label '{result['new_label']}')")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--last-minutes", type=int, default=15,
                   help="Time window for channel pulls. Default: 15")
    p.add_argument("--no-reset", dest="reset", action="store_false",
                   help="Append to the current pull session instead of "
                        "starting a fresh one. Default behavior is to "
                        "reset (archive previous, start clean) so each "
                        "collect_all run is its own batch.")
    p.set_defaults(reset=True)
    p.add_argument("--skip-meeting", action="store_true",
                   help="Don't transcribe/append the latest call recording.")
    p.add_argument("--meeting-max-age-min", type=int, default=None,
                   help="Only transcribe a recording if it's at most N "
                        "minutes old. Default: same as --last-minutes.")
    args = p.parse_args()

    n = args.last_minutes
    max_age_min = args.meeting_max_age_min if args.meeting_max_age_min is not None else n

    print(f"\n*** collect_all: window = last {n} min ***")

    if args.reset:
        _maybe_reset(label=f"collect_all-{n}min")

    # 1. Teams chat — all chats in registry
    _run("1/5  TEAMS CHAT (all chats)",
         [sys.executable, "-m", "teams.pull_chat",
          "--all-chats", "--last-minutes", str(n)])

    # 2. Email
    _run("2/5  EMAIL",
         [sys.executable, "-m", "mail.pull_email",
          "--last-minutes", str(n)])

    # 3. Drive
    _run("3/5  GOOGLE DRIVE",
         [sys.executable, "-m", "drive.pull_drive",
          "--last-minutes", str(n)])

    # 4. Meeting (only if a recent recording exists)
    if args.skip_meeting:
        print(f"\n4/5  MEETING — skipped (--skip-meeting)")
    else:
        age = _latest_recording_age_seconds()
        if age is None:
            print(f"\n4/5  MEETING — skipped (no recordings in data/teams/calls/)")
        elif age > max_age_min * 60:
            print(f"\n4/5  MEETING — skipped (latest recording is "
                  f"{age/60:.0f} min old, max age {max_age_min} min)")
        else:
            _run(f"4/5  MEETING (latest recording, {age/60:.0f} min old)",
                 [sys.executable, "pull_meeting.py"])

    # 5. Identify + draft
    if not os.getenv("VERIFICATION_TO"):
        print("\n5/5  VERIFY — VERIFICATION_TO not set in .env",
              file=sys.stderr)
        print("Set VERIFICATION_TO=<client@email> in .env, or pass it "
              "inline:", file=sys.stderr)
        print("    set VERIFICATION_TO=client@example.com  &  "
              "python collect_all.py", file=sys.stderr)
        return 2

    rc = _run("5/5  IDENTIFY + DRAFT EMAIL",
              [sys.executable, "agent.py", "--task", "verify_session"])

    print(f"\n{'='*60}")
    if rc == 0:
        print("  collect_all complete.")
        print("  Open your Outlook / Gmail Drafts folder to review the email.")
    else:
        print(f"  collect_all finished with errors (last rc={rc})")
    print(f"{'='*60}\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
