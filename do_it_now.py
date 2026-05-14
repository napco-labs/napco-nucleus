"""Instant trigger — bypass every cron and run the full central pipeline now.

Steps, in order:
  1. Force-push your local Teams chat to central (one shot, no waiting for
     the 15-min scheduled task). Other developers' chat is whatever
     they've already pushed — up to 15 min stale, per design.
  2. SSH to the agent host (MVPACCESS) and run collect_central.py for the
     requested client. That:
       a. Pulls email fresh on the agent host
       b. Pulls Google Drive fresh on the agent host
       c. Walks central calls + chats for every dev (today)
       d. Identifies requirements + drafts the verification email into
          your [Gmail]/Drafts

Usage
    py -3 do_it_now.py --client "Acme"
    py -3 do_it_now.py --client "all" --last-minutes 30
    py -3 do_it_now.py --client "Susmoy" --day 2026-05-10
    py -3 do_it_now.py --client "Acme" --no-push      # skip the local force-push
    py -3 do_it_now.py --client "Acme" --dry-run      # print the commands, don't run

Env
    Local .env:       NUCLEUS_CENTRAL_PATH (UNC to the share)
    Agent-host .env:  NUCLEUS_CENTRAL_PATH (local path), REQ_IMAP_*, GROQ_API_KEY,
                      GDRIVE_AUDIO_FOLDER_ID, VERIFICATION_TO
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).parent

# SSH target for the (retired-but-still-reachable) MVPACCESS host. Now
# overridable via env so we don't embed another teammate's username +
# the .209 IP into every dev's invocation. If neither --ssh-target nor
# NUCLEUS_SSH_TARGET is set, the script fails fast with a clear error
# rather than silently SSHing as a hardcoded account.
DEFAULT_SSH_TARGET = os.environ.get("NUCLEUS_SSH_TARGET", "").strip() or None
DEFAULT_REMOTE_PATH = os.environ.get(
    "NUCLEUS_SSH_REMOTE_PATH", r"C:\napco-nucleus")


def _run_local_push(last_minutes: int, dry_run: bool) -> int:
    cmd = [sys.executable, "-m", "teams.push_chat",
           "--last-minutes", str(last_minutes)]
    print(f"\n{'='*60}\n  1/2  LOCAL TEAMS CHAT PUSH  (last {last_minutes} min)"
          f"\n  $ {' '.join(cmd)}\n{'='*60}")
    if dry_run:
        return 0
    return subprocess.call(cmd, cwd=str(_HERE))


def _build_remote_cmd(remote_path: str, client: str, last_minutes: int,
                       day: str | None, no_identify: bool) -> str:
    """Build the one-line remote command for ssh to forward. Uses
    PowerShell on the remote so quoting of the client name stays sane."""
    args = [
        "py", "-3", "collect_central.py",
        "--client", client,
        "--last-minutes", str(last_minutes),
    ]
    if day:
        args += ["--day", day]
    if no_identify:
        args += ["--no-identify"]
    # PowerShell single-quoted strings are literal — no $ expansion, no
    # backtick escapes. We just need to double any embedded single quotes
    # in the client name.
    ps_args = " ".join(f"'{a.replace(chr(39), chr(39)*2)}'" for a in args)
    inner = f"Set-Location '{remote_path}'; & {ps_args}"
    return f'powershell -NoProfile -Command "{inner}"'


def _run_remote_collect(ssh_target: str, remote_path: str, client: str,
                        last_minutes: int, day: str | None,
                        no_identify: bool, dry_run: bool) -> int:
    remote_cmd = _build_remote_cmd(remote_path, client, last_minutes,
                                    day, no_identify)
    ssh_cmd = ["ssh", ssh_target, remote_cmd]
    print(f"\n{'='*60}\n  2/2  REMOTE collect_central on {ssh_target}"
          f"\n  $ ssh {ssh_target} {shlex.quote(remote_cmd)}"
          f"\n{'='*60}")
    if dry_run:
        return 0
    return subprocess.call(ssh_cmd)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client", required=True,
                    help="Client display name (or 'all') to scope the "
                         "central scan to.")
    ap.add_argument("--last-minutes", type=int, default=15,
                    help="Time window for the local push + remote email/"
                         "Drive pulls. Default: 15.")
    ap.add_argument("--day", default=None,
                    help="YYYY-MM-DD for the central scan. Default: today.")
    ap.add_argument("--no-push", dest="push", action="store_false",
                    help="Skip the local Teams chat push. Use when you "
                         "know your local chat is already pushed or your "
                         "machine has no Teams cache.")
    ap.set_defaults(push=True)
    ap.add_argument("--no-identify", dest="identify", action="store_false",
                    help="Aggregate only on the remote — skip the "
                         "identify + draft step.")
    ap.set_defaults(identify=True)
    ap.add_argument("--ssh-target", default=DEFAULT_SSH_TARGET,
                    help=f"SSH user@host for the agent host. "
                         f"Default: {DEFAULT_SSH_TARGET}")
    ap.add_argument("--remote-path", default=DEFAULT_REMOTE_PATH,
                    help=f"Repo path on the agent host. "
                         f"Default: {DEFAULT_REMOTE_PATH}")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the commands without running anything.")
    args = ap.parse_args()

    print(f"\n*** do_it_now: client={args.client!r}  "
          f"window=last {args.last_minutes} min  "
          f"day={args.day or 'today'} ***")

    if args.push:
        rc = _run_local_push(args.last_minutes, args.dry_run)
        if rc != 0:
            print(f"\n[warn] local push exited rc={rc}; continuing to the "
                  f"remote step anyway. Other devs' chat is still "
                  f"available on central from their scheduled pushes.",
                  file=sys.stderr)
    else:
        print("\n  1/2  LOCAL TEAMS CHAT PUSH  — skipped (--no-push)")

    if not args.ssh_target:
        print("\nERROR: no SSH target. Set NUCLEUS_SSH_TARGET in .env "
              "or pass --ssh-target user@host. There is no built-in "
              "default to prevent accidentally SSHing as another "
              "teammate's account.", file=sys.stderr)
        return 2

    rc = _run_remote_collect(args.ssh_target, args.remote_path, args.client,
                              args.last_minutes, args.day,
                              not args.identify, args.dry_run)

    print(f"\n{'='*60}")
    if rc == 0:
        print("  do_it_now: complete.")
        if args.identify:
            print("  Open your [Gmail]/Drafts to review the verification email.")
        else:
            print("  Session doc updated on the agent host. No email drafted.")
    else:
        print(f"  do_it_now: remote step exited rc={rc}")
    print(f"{'='*60}\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
