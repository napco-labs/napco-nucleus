"""Daily health check of the requirement pipeline, with conservative auto-repair.

Requirement 10 (Titu, 2026-07-27): "It will check the requirement management
pipeline daily and if there are any issues will fix it automatically."

Runs on the assistant box (which has both SSH to central and Teams), checks the
pipeline on .123, repairs what is safely repairable, and reports to Titu in a
1:1 chat.

WHAT IT WILL FIX BY ITSELF
  * a nucleus container that is stopped or exited  -> docker compose start
  * a container stuck restarting                   -> reported, NOT restarted
    (a restart loop means something is broken; bouncing it hides the cause)

WHAT IT WILL NEVER DO
  * touch the GitHub runner registration (needs a fresh token and a human)
  * fire the requirement pipeline or send any email
  * recreate, rebuild, pull, or delete anything
  * message anyone except Titu

Silence is the normal outcome. It only messages when something was actually
wrong, so a daily "all good" never trains anyone to ignore it. Use --always to
force a report, and --dry-run to see what it would do.

Run:  py -3 -m tools.pipeline_selfcheck
"""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).parent.parent
LOG = _REPO / "logs" / "pipeline_selfcheck.log"
STATE = _REPO / "data" / "selfcheck_state.json"

CENTRAL_HOST = "ubuntu@172.16.205.123"
COMPOSE_DIR = "/home/ubuntu/napco-nucleus/deploy/linux-central"
NOTIFY_TO = "titucse@hotmail.com"      # Titu only

EXPECTED = ["nucleus-transcribe", "nucleus-daily-draft", "nucleus-samba",
            "nucleus-stage-email", "nucleus-stage-drive"]

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
    """Run a command on central. Returns (rc, stdout+stderr)."""
    try:
        p = subprocess.run(SSH + [cmd], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, "ssh failed: %s" % e


def container_states() -> dict:
    """name -> status string, for every nucleus container (running or not)."""
    rc, out = _ssh('docker ps -a --filter name=nucleus '
                   '--format "{{.Names}}|{{.State}}|{{.Status}}"')
    if rc != 0:
        return {}
    states = {}
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 3:
            states[parts[0]] = {"state": parts[1], "status": parts[2]}
    return states


def check_and_repair(dry: bool) -> dict:
    findings, repaired, unrepairable = [], [], []

    states = container_states()
    if not states:
        findings.append("cannot reach central (.123) over SSH")
        return {"reachable": False, "findings": findings,
                "repaired": repaired, "unrepairable": unrepairable}

    for name in EXPECTED:
        info = states.get(name)
        if info is None:
            findings.append("%s is missing entirely" % name)
            unrepairable.append(name)
            continue
        state = (info["state"] or "").lower()
        if state == "running":
            continue
        if state == "restarting":
            # a restart loop is a real fault; bouncing it would mask the cause
            findings.append("%s is stuck restarting (%s)" % (name, info["status"]))
            unrepairable.append(name)
            continue
        findings.append("%s is %s (%s)" % (name, state, info["status"]))
        if dry:
            repaired.append("%s (dry-run, not started)" % name)
            continue
        svc = name.replace("nucleus-", "")
        rc, out = _ssh("cd %s && docker compose start %s" % (COMPOSE_DIR, svc))
        after = container_states().get(name, {}).get("state", "?")
        if rc == 0 and after.lower() == "running":
            repaired.append(name)
            log("repaired %s" % name)
        else:
            unrepairable.append(name)
            log("could not repair %s: rc=%s %s" % (name, rc, out[:160]))

    # transcription must actually be ticking, not merely up
    rc, out = _ssh("docker logs --tail 40 nucleus-transcribe 2>&1 | "
                   "grep -c 'transcribe-loop. tick' || true")
    if rc == 0 and out.strip().isdigit() and int(out.strip()) == 0:
        findings.append("transcribe is up but not ticking")
        unrepairable.append("nucleus-transcribe (no ticks)")

    return {"reachable": True, "findings": findings,
            "repaired": repaired, "unrepairable": unrepairable}


def build_report(res: dict) -> str:
    if not res["findings"]:
        return ("Titu bhai, daily pipeline check done. Everything is healthy, "
                "nothing needed fixing.")
    parts = ["Titu bhai, daily pipeline check found %d issue(s)."
             % len(res["findings"])]
    for f in res["findings"]:
        parts.append("- " + f)
    if res["repaired"]:
        parts.append("Fixed automatically: " + ", ".join(res["repaired"]) + ".")
    if res["unrepairable"]:
        parts.append("Needs you: " + ", ".join(res["unrepairable"]) + ".")
    return "\n".join(parts)


def main() -> int:
    dry = "--dry-run" in sys.argv
    always = "--always" in sys.argv

    res = check_and_repair(dry)
    report = build_report(res)
    log("check: %d finding(s), %d repaired, %d unrepairable"
        % (len(res["findings"]), len(res["repaired"]), len(res["unrepairable"])))

    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(
            {"at": datetime.datetime.now().isoformat(timespec="seconds"),
             **res}, indent=2), encoding="utf-8")
    except Exception:
        pass

    print(report)

    # Only speak up when something was wrong. A daily "all good" trains people
    # to ignore the channel, and then they miss the one that matters.
    if not res["findings"] and not always:
        return 0
    if dry:
        print("[dry-run] would notify %s" % NOTIFY_TO)
        return 0
    try:
        from teams import notify
        ok = notify.send(NOTIFY_TO, report)
        log("notified Titu: %s" % ok)
    except Exception as e:
        log("notify failed: %s" % str(e)[:150])
    return 0


if __name__ == "__main__":
    sys.exit(main())
