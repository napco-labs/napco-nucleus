"""Daily end-to-end health check of the requirement pipeline, with auto-repair.

Requirement 10 (Titu, 2026-07-27), widened on his instruction: "If it needs to
restart daemon, might be fix the STT, might be missing mirroring that needs to
be fixed, might be voice is not recording. So everything will be checked and
will be fixed automatically."

Runs on the assistant box, which is the only host that can see all three layers:
the local capture daemons, the SMB mirror, and central over SSH.

WHAT IT CHECKS AND REPAIRS
  Local capture
    * the daemons that must be Running (Voice Daemon, Speaker Guard, Live
      Heartbeat, Auto Answer)          -> restarted if stopped
    * Teams running at all             -> started if not
    * screen locked                    -> REPORTED, cannot be fixed remotely
      (UIA dies on a locked screen, so this silently breaks everything)
  Mirroring
    * central share reachable          -> reported
    * finished local recordings that never reached central  -> re-mirrored
  Transcription / STT
    * stale *.part siblings on central -> removed. transcribe_calls SKIPS any
      session with a lingering .part, so one interrupted upload parks a call
      forever. This is a known trap, not a hypothetical.
    * a call on central with no transcript after TRANSCRIBE_GRACE_MIN
                                       -> reported (never re-run blindly)
  Central services
    * nucleus containers stopped/exited -> started
    * a container stuck restarting      -> REPORTED, never bounced (a restart
      loop means something is broken; bouncing hides the cause)
    * transcribe up but not ticking     -> reported

WHAT IT WILL NEVER DO
  * fire the requirement pipeline or send any email
  * touch the GitHub runner registration
  * recreate, rebuild, pull or delete containers
  * delete any recording, transcript or requirement artifact
  * message anyone except Titu

Silent when healthy, so the one message that matters is never lost in noise.

Run:  py -3 -m tools.pipeline_selfcheck
      py -3 -m tools.pipeline_selfcheck --dry-run    # show, change nothing
      py -3 -m tools.pipeline_selfcheck --always     # report even if healthy
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).parent.parent
LOG = _REPO / "logs" / "pipeline_selfcheck.log"
STATE = _REPO / "data" / "selfcheck_state.json"
LOCAL_CALLS = _REPO / "data" / "teams" / "calls"

CENTRAL_HOST = "ubuntu@172.16.205.123"
COMPOSE_DIR = "/home/ubuntu/napco-nucleus/deploy/linux-central"
NOTIFY_TO = "titucse@hotmail.com"          # Titu only

EXPECTED_CONTAINERS = ["nucleus-transcribe", "nucleus-daily-draft",
                       "nucleus-samba", "nucleus-stage-email",
                       "nucleus-stage-drive"]

MUST_RUN_TASKS = ["NAPCO Nucleus - Voice Daemon",
                  "NAPCO Nucleus - Speaker Guard",
                  "NAPCO Nucleus - Live Heartbeat",
                  "NAPCO Nucleus - Auto Answer"]

TRANSCRIBE_GRACE_MIN = 45      # a call older than this with no transcript = odd
STALE_PART_MIN = 30            # a .part untouched this long is abandoned

SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
       "-o", "StrictHostKeyChecking=accept-new", CENTRAL_HOST]


def log(msg: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (datetime.datetime.now()
                                 .strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _ssh(cmd: str, timeout: int = 90):
    try:
        p = subprocess.run(SSH + [cmd], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, "ssh failed: %s" % e


def _ps(cmd: str, timeout: int = 60):
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, (p.stdout or "").strip()
    except Exception as e:
        return 1, "powershell failed: %s" % e


class Result:
    def __init__(self):
        self.findings, self.fixed, self.needs_you = [], [], []

    def issue(self, msg):
        self.findings.append(msg)

    def repaired(self, msg):
        self.fixed.append(msg)

    def manual(self, msg):
        self.needs_you.append(msg)


# ---------------------------------------------------------------- local ----
def check_local(r: Result, dry: bool) -> None:
    # screen locked -> UIA is dead, and nothing below will work
    rc, out = _ps("if (Get-Process LogonUI -EA SilentlyContinue) "
                  "{ 'LOCKED' } else { 'unlocked' }")
    if out == "LOCKED":
        r.issue("the screen is LOCKED - chat and call automation cannot run")
        r.manual("unlock the assistant box")

    # daemons that must be running
    for task in MUST_RUN_TASKS:
        rc, state = _ps("(Get-ScheduledTask -TaskName '%s' -EA SilentlyContinue)"
                        ".State" % task)
        if not state:
            r.issue("%s is not registered" % task)
            r.manual(task + " (missing)")
            continue
        if state.strip().lower() == "running":
            continue
        r.issue("%s is %s" % (task, state.strip()))
        if dry:
            r.repaired("%s (dry-run)" % task)
            continue
        _ps("Enable-ScheduledTask -TaskName '%s' -EA SilentlyContinue | Out-Null; "
            "Start-ScheduledTask -TaskName '%s'" % (task, task))
        rc, after = _ps("Start-Sleep -Seconds 8; (Get-ScheduledTask -TaskName "
                        "'%s').State" % task, timeout=40)
        if after.strip().lower() == "running":
            r.repaired(task)
            log("restarted %s" % task)
        else:
            r.manual("%s (restart failed)" % task)

    # Teams itself
    rc, out = _ps("if (Get-Process ms-teams -EA SilentlyContinue) "
                  "{ 'up' } else { 'down' }")
    if out == "down":
        r.issue("Teams is not running")
        if not dry:
            _ps("Start-ScheduledTask -TaskName 'NAPCO Nucleus - Start Teams' "
                "-EA SilentlyContinue")
            rc, after = _ps("Start-Sleep -Seconds 15; if (Get-Process ms-teams "
                            "-EA SilentlyContinue) { 'up' } else { 'down' }",
                            timeout=45)
            if after == "up":
                r.repaired("Teams restarted")
            else:
                r.manual("Teams (could not start)")
        else:
            r.repaired("Teams (dry-run)")


# -------------------------------------------------------------- mirror ----
def _central_root() -> Path | None:
    try:
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=True)
    except Exception:
        pass
    raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    return Path(raw) if raw else None


def check_mirror(r: Result, dry: bool) -> None:
    root = _central_root()
    if root is None:
        r.issue("NUCLEUS_CENTRAL_PATH is not set")
        r.manual("central path config")
        return
    if not root.exists():
        r.issue("central share %s is unreachable - nothing can mirror" % root)
        r.manual("central share")
        return

    dev = (os.environ.get("NUCLEUS_DEV_NAME") or "").strip() or "unknown"
    if not LOCAL_CALLS.exists():
        return

    # finished local recordings (skip anything still being written)
    local = [p for p in LOCAL_CALLS.glob("*")
             if p.is_file() and p.suffix.lower() in (".opus", ".wav", ".json")
             and not p.name.endswith(".part")]
    missing = []
    for p in local:
        stamp = p.name.split("_")[0].split(".")[0]
        day = None
        if len(stamp) >= 8 and stamp[:8].isdigit():
            day = "%s-%s-%s" % (stamp[:4], stamp[4:6], stamp[6:8])
        if not day:
            continue
        dst = root / dev / day / "calls" / p.name
        if not dst.exists():
            missing.append((p, dst))

    if not missing:
        return
    r.issue("%d recording file(s) never reached central" % len(missing))
    if dry:
        r.repaired("%d file(s) (dry-run, not copied)" % len(missing))
        return
    ok = 0
    for src, dst in missing:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(str(src), str(dst))
            ok += 1
        except Exception as e:
            log("re-mirror failed %s: %s" % (src.name, str(e)[:120]))
    if ok:
        r.repaired("re-mirrored %d recording file(s)" % ok)
        log("re-mirrored %d file(s)" % ok)
    if ok < len(missing):
        r.manual("%d file(s) could not be mirrored" % (len(missing) - ok))


# ------------------------------------------------------------ central ----
def check_central(r: Result, dry: bool) -> None:
    rc, out = _ssh('docker ps -a --filter name=nucleus '
                   '--format "{{.Names}}|{{.State}}|{{.Status}}"')
    if rc != 0:
        r.issue("cannot reach central (.123) over SSH")
        r.manual("SSH to central")
        return

    states = {}
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 3:
            states[parts[0]] = {"state": parts[1], "status": parts[2]}

    for name in EXPECTED_CONTAINERS:
        info = states.get(name)
        if info is None:
            r.issue("%s is missing entirely" % name)
            r.manual(name + " (missing)")
            continue
        state = (info["state"] or "").lower()
        if state == "running":
            continue
        if state == "restarting":
            r.issue("%s is stuck restarting (%s)" % (name, info["status"]))
            r.manual(name + " (restart loop - needs diagnosis, not a bounce)")
            continue
        r.issue("%s is %s" % (name, state))
        if dry:
            r.repaired("%s (dry-run)" % name)
            continue
        svc = name.replace("nucleus-", "")
        _ssh("cd %s && docker compose start %s" % (COMPOSE_DIR, svc))
        rc2, out2 = _ssh('docker ps --filter name=%s --format "{{.State}}"' % name)
        if out2.strip().lower() == "running":
            r.repaired(name)
            log("started %s" % name)
        else:
            r.manual(name + " (start failed)")

    # transcribe alive but not ticking
    rc, out = _ssh("docker logs --since 15m nucleus-transcribe 2>&1 | "
                   "grep -c 'transcribe-loop. tick' || true")
    if rc == 0 and out.strip().isdigit() and int(out.strip()) == 0:
        r.issue("transcribe is up but has not ticked in 15 minutes")
        r.manual("nucleus-transcribe (not ticking)")


# ----------------------------------------------------------- STT flow ----
def check_stt(r: Result, dry: bool) -> None:
    # 1. stale .part files park a session forever - transcribe_calls skips any
    #    session that still has one. This has bitten us before.
    # A .part is only safe to remove when a COMPLETE sibling exists AND that
    # sibling is not materially smaller. Found the hard way on 2026-07-27:
    # 20260714-204302_mic.wav.part was 1097MB while its "complete" .wav was
    # 30MB -- the partial held the real call and the wav was the truncated one.
    # Deleting on existence alone would have destroyed ~1GB of audio.
    rc, out = _ssh(
        "for p in $(find /srv/nucleus-central -name '*.part' -mmin +%d 2>/dev/null); do "
        "  real=${p%%.part}; ps=$(stat -c%%s \"$p\"); "
        "  if [ -f \"$real\" ]; then rs=$(stat -c%%s \"$real\"); "
        "    if [ \"$rs\" -ge \"$ps\" ]; then echo \"SAFE|$p\"; "
        "    else echo \"BIGGER|$p|$ps|$rs\"; fi; "
        "  else echo \"ORPHAN|$p|$ps\"; fi; done" % STALE_PART_MIN)

    safe, bigger, orphan = [], [], []
    for line in out.splitlines():
        f = line.strip().split("|")
        if f[0] == "SAFE":
            safe.append(f[1])
        elif f[0] == "BIGGER":
            bigger.append((f[1], int(f[2]), int(f[3])))
        elif f[0] == "ORPHAN":
            orphan.append((f[1], int(f[2])))

    if safe:
        r.issue("%d stale .part file(s) blocking transcription" % len(safe))
        if dry:
            r.repaired("%d .part file(s) (dry-run)" % len(safe))
        else:
            for p in safe:
                _ssh("rm -f '%s'" % p)
            r.repaired("removed %d superseded .part file(s)" % len(safe))
            log("removed %d superseded .part file(s)" % len(safe))

    for p, ps, rs in bigger:
        r.issue("%s is %dMB but its finished file is only %dMB - the partial "
                "may hold the real recording"
                % (Path(p).name, ps // 1048576, rs // 1048576))
        r.manual("%s (NOT deleted - larger than the finished file)" % Path(p).name)

    for p, ps in orphan:
        if "/.deleted/" in p:
            continue          # already discarded, ignore quietly
        r.issue("%s has no finished file at all (%dMB)"
                % (Path(p).name, ps // 1048576))
        r.manual("%s (orphan partial - NOT deleted)" % Path(p).name)

    # 2. a call old enough to have been transcribed, but with no transcript
    rc, out = _ssh(
        "for w in $(find /srv/nucleus-central -name '*_speaker.wav' -mmin +%d "
        "-mmin -2880 2>/dev/null); do t=${w%%_speaker.wav}_transcript.md; "
        "[ -f \"$t\" ] || echo \"$w\"; done" % TRANSCRIBE_GRACE_MIN)
    missing = [l.strip() for l in out.splitlines() if l.strip()]
    if missing:
        r.issue("%d recording(s) older than %dmin still have no transcript"
                % (len(missing), TRANSCRIBE_GRACE_MIN))
        # deliberately NOT auto-retried: a repeated STT failure usually means
        # quota, auth, or a corrupt file, and blind retries burn quota.
        r.manual("STT: %s" % ", ".join(Path(m).name for m in missing[:3]))


def build_report(r: Result) -> str:
    if not r.findings:
        return ("Titu bhai, daily pipeline check done. Capture, mirroring, "
                "transcription and central are all healthy. Nothing needed "
                "fixing.")
    out = ["Titu bhai, daily pipeline check found %d issue(s)." % len(r.findings)]
    for f in r.findings:
        out.append("- " + f)
    if r.fixed:
        out.append("Fixed automatically: " + ", ".join(r.fixed) + ".")
    if r.needs_you:
        out.append("Needs your attention: " + ", ".join(r.needs_you) + ".")
    return "\n".join(out)


def main() -> int:
    dry = "--dry-run" in sys.argv
    always = "--always" in sys.argv

    r = Result()
    for fn in (check_local, check_mirror, check_central, check_stt):
        try:
            fn(r, dry)
        except Exception as e:
            r.issue("%s failed: %s" % (fn.__name__, str(e)[:120]))
            log("%s raised: %s" % (fn.__name__, str(e)[:200]))

    report = build_report(r)
    print(report)
    log("check: %d issue(s), %d fixed, %d manual"
        % (len(r.findings), len(r.fixed), len(r.needs_you)))

    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(
            {"at": datetime.datetime.now().isoformat(timespec="seconds"),
             "findings": r.findings, "fixed": r.fixed,
             "needs_you": r.needs_you}, indent=2), encoding="utf-8")
    except Exception:
        pass

    if not r.findings and not always:
        return 0
    if dry:
        print("[dry-run] would notify %s" % NOTIFY_TO)
        return 0
    try:
        from teams import notify
        notify.send(NOTIFY_TO, report)
        log("notified Titu")
    except Exception as e:
        log("notify failed: %s" % str(e)[:150])
    return 0


if __name__ == "__main__":
    sys.exit(main())
