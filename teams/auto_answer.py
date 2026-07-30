"""Auto-accept incoming Teams calls for the Meeting Assistant.

Runs in the interactive desktop session (scheduled task at logon). Polls the
UI-Automation tree for an incoming-call Accept/Answer button and invokes it, so
nobody has to click "Accept" on the machine. Logs every action so we can tune
the button match against the real Teams UI.

Deliberately biased to AUDIO accept (never the video button) and de-bounced so
one incoming call is accepted once, not repeatedly.

ALREADY IN A CALL (Titu, 2026-07-28): "if anybody wants you to add again, do
not receive his call rather send a message politely that Sorry! you are in a
call and let you finish it first." So while a recording is in progress the
watcher accepts nothing and instead messages the caller once.

It does NOT click Decline to stop the ringing. Decline and Hang up sit next to
each other in the same tree, and a mis-click while a call is live would end the
call we are recording. A second call ringing out is recoverable; losing the
meeting we are capturing is not.
"""
import os
import random
import subprocess
import sys
import time
import datetime
from pathlib import Path

import uiautomation as auto

_REPO = Path(__file__).parent.parent

# This watcher is launched by a scheduled task, which does NOT load .env, so
# without this the tunables below could only be set machine-wide. record_call
# does the same thing for the same reason.
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env", override=True)
except Exception:
    pass

# The scheduled task launches this BY PATH ("pythonw.exe ...\teams\
# auto_answer.py"), which puts teams\ on sys.path but not the repo root, so
# "from teams import ..." raises ModuleNotFoundError and the watcher dies at
# startup. Put the repo root on the path before importing anything of ours,
# so the task keeps working without being re-registered.
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from teams import dev_names  # noqa: E402
LOG = str(_REPO / "logs" / "auto_answer.log")

# Written by record_call while a call is being captured; its presence is the
# single source of truth for "we are already in a call".
RECORDING_MARKER = _REPO / "data" / "teams" / ".recording_active"

# match order matters: prefer explicit audio-accept, then generic accept/answer.
ACCEPT_HINTS = (
    "accept with audio", "answer with audio", "accept call",
    "answer call", "accept", "answer",
)
# never click these
DENY_HINTS = ("decline", "reject", "video", "ignore", "hang up")


def _env_float(name: str, default: float) -> float:
    try:
        return float((os.environ.get(name) or "").strip() or default)
    except ValueError:
        return default


# Let it ring like a person would before picking up. Answering on the first
# poll tick was instant and inhuman -- Titu, 2026-07-30: "accept the ring as
# your normal speed so that nobody can understand it is a bot." Randomised
# rather than fixed, because a constant 5.0s is its own tell.
_ANSWER_DELAY_MIN_S = _env_float("NUCLEUS_ANSWER_DELAY_MIN_S", 4.0)
_ANSWER_DELAY_MAX_S = _env_float("NUCLEUS_ANSWER_DELAY_MAX_S", 9.0)

# Mute our own mic a few seconds into the call. Nobody speaks at this machine,
# so an open mic only feeds room noise (and any speaker bleed) back into the
# meeting. Not done at the instant of answering: Teams settles the in-call
# toolbar for a moment, and a click into a half-built toolbar hits nothing.
_MUTE_AFTER_S = _env_float("NUCLEUS_MUTE_AFTER_ANSWER_S", 10.0)

MUTE_SCRIPT = _REPO / "scripts" / "mute-nn-audio.ps1"

# A leftover call window keeps the chat surface out of reach, so auto_reply
# cannot answer anyone until it is gone. Titu, 2026-07-30: a call ended, the
# window stayed, and NN went silent to every question for the rest of the
# night. Only windows naming themselves a call/meeting are candidates -- the
# main Teams window must never be touched, or chat dies for good.
CALL_WINDOW_HINTS = (
    "call with", "meeting with", "call ended", "meeting ended",
    "calling", "in a call",
)
HANGUP_HINTS = ("hang up", "leave call", "leave meeting", "end call")

BUSY_MESSAGE = ("Sorry {name}bhai, I am in a call right now. Let me finish it "
                "first and I will come back to you.")

# Do not tell the same person twice inside one call.
_BUSY_GAP_S = 300.0


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except Exception:
        pass


def in_call() -> bool:
    try:
        return RECORDING_MARKER.exists()
    except Exception:
        return False


def _is_accept(ctrl):
    try:
        if ctrl.ControlType != auto.ControlType.ButtonControl:
            return False
        nm = (ctrl.Name or "").strip().lower()
        if not nm:
            return False
        if any(d in nm for d in DENY_HINTS):
            return False
        return any(h in nm for h in ACCEPT_HINTS)
    except Exception:
        return False


def find_accept_button():
    """Search every top-level window for an Accept/Answer button."""
    root = auto.GetRootControl()
    try:
        windows = root.GetChildren()
    except Exception:
        return None
    for win in windows:
        try:
            btn = win.Control(searchDepth=0xFFFFFFFF, Compare=lambda c, d: _is_accept(c))
            if btn.Exists(0, 0):
                return btn
        except Exception:
            continue
    return None


def _is_mute(ctrl):
    """A button that MUTES us right now.

    Teams names this control by the action it performs, so "Unmute" means we
    are already muted and clicking it would put the mic back on -- the exact
    opposite of the intent. Requiring "mute" while rejecting "unmute" makes
    the check idempotent: once muted, nothing here matches again.
    """
    try:
        if ctrl.ControlType != auto.ControlType.ButtonControl:
            return False
        nm = (ctrl.Name or "").strip().lower()
        if not nm or "unmute" in nm:
            return False
        return "mute" in nm
    except Exception:
        return False


def _is_hangup(ctrl):
    try:
        if ctrl.ControlType != auto.ControlType.ButtonControl:
            return False
        nm = (ctrl.Name or "").strip().lower()
        return bool(nm) and any(h in nm for h in HANGUP_HINTS)
    except Exception:
        return False


def mute_self() -> str:
    """Mute our microphone. Returns what actually worked, for the log.

    Prefers the in-call Teams button so the other participants SEE us muted
    rather than merely hearing nothing. Falls back to muting the capture
    device, which mute-nn-audio.ps1 already does safely -- it is careful to
    leave the SPEAKER unmuted, since loopback capture of the speaker is how we
    record the call at all.
    """
    root = auto.GetRootControl()
    try:
        windows = root.GetChildren()
    except Exception:
        windows = []
    for win in windows:
        try:
            btn = win.Control(searchDepth=0xFFFFFFFF,
                              Compare=lambda c, d: _is_mute(c))
            if btn.Exists(0, 0):
                name = btn.Name
                try:
                    btn.GetInvokePattern().Invoke()
                except Exception:
                    btn.Click(simulateMove=False)
                return f"teams button '{name}'"
        except Exception:
            continue
    if MUTE_SCRIPT.exists():
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(MUTE_SCRIPT), "-Quiet"],
                timeout=30, capture_output=True)
            return "capture-device mute (no Teams mute button found)"
        except Exception as e:
            return f"FAILED: {str(e)[:80]}"
    return "FAILED: no mute button and no mute script"


def close_stale_call_window() -> bool:
    """Close a Teams call window that outlived its call.

    Guarded twice over, because closing the wrong window costs us chat: the
    recording marker must be gone (the call really is over) AND the window
    must still carry no hang-up control (Teams itself no longer considers it
    live). Anything that does not name itself a call or meeting is ignored
    outright, so the main Teams window is never a candidate.
    """
    if in_call():
        return False
    root = auto.GetRootControl()
    try:
        windows = root.GetChildren()
    except Exception:
        return False
    for win in windows:
        try:
            nm = (win.Name or "").strip()
            low = nm.lower()
            if not nm or not any(h in low for h in CALL_WINDOW_HINTS):
                continue
            hang = win.Control(searchDepth=0xFFFFFFFF,
                               Compare=lambda c, d: _is_hangup(c))
            if hang.Exists(0, 0):
                log(f"leftover window '{nm}' still shows a hang-up control — "
                    f"treating the call as live, leaving it alone")
                continue
            try:
                win.GetWindowPattern().Close()
            except Exception:
                try:
                    win.SetActive()
                    win.SendKeys("{Esc}")
                except Exception as e:
                    log(f"could not close leftover window '{nm}': "
                        f"{str(e)[:80]}")
                    continue
            log(f"closed leftover call window '{nm}' so chat replies can "
                f"reach the UI again")
            return True
        except Exception:
            continue
    return False


def _top_window(ctrl):
    """Walk up to the top-level window holding `ctrl`."""
    seen = 0
    cur = ctrl
    try:
        while cur is not None and seen < 40:
            parent = cur.GetParentControl()
            if parent is None or parent.ControlType == auto.ControlType.PaneControl \
                    and not parent.Name:
                return cur
            if parent.ControlType == auto.ControlType.WindowControl and parent.Name:
                cur = parent
            elif parent.Name and cur.Name == "":
                cur = parent
            else:
                cur = parent
            seen += 1
    except Exception:
        pass
    return cur


def caller_name(btn):
    """Who is calling, as a roster name, or '' if we cannot tell.

    Reads the text in the incoming-call window and keeps the first fragment
    that resolves to somebody on the dev roster. We only ever message known
    devs, so an unrecognised caller simply gets no message.
    """
    win = _top_window(btn)
    if win is None:
        return ""
    texts = []
    try:
        if win.Name:
            texts.append(win.Name)
    except Exception:
        pass

    def walk(c, d):
        if d > 12 or len(texts) > 60:
            return
        try:
            if c.ControlType in (auto.ControlType.TextControl,
                                 auto.ControlType.WindowControl):
                nm = (c.Name or "").strip()
                if nm:
                    texts.append(nm)
            for ch in c.GetChildren():
                walk(ch, d + 1)
        except Exception:
            return

    try:
        walk(win, 0)
    except Exception:
        pass

    for t in texts:
        # strip the usual call-toast wording before matching
        cleaned = t
        for noise in ("is calling you", "incoming call from", "incoming call",
                      "is calling", "calling you", "Microsoft Teams", "Teams"):
            cleaned = cleaned.replace(noise, " ")
        if dev_names.is_known(cleaned):
            return dev_names.resolve(cleaned)
    return ""


def tell_caller_busy(who: str) -> bool:
    """Message the caller that we are already in a call."""
    entry = dev_names.find(who)
    if entry is None:
        return False
    name = (entry["name"] + " ") if entry.get("name") else ""
    body = BUSY_MESSAGE.format(name=name)
    try:
        from teams import notify
        return bool(notify.send(entry["search"], body))
    except Exception as e:
        log(f"busy message to '{who}' failed: {str(e)[:120]}")
        return False


def main():
    log(f"auto_answer watcher started (ring delay "
        f"{_ANSWER_DELAY_MIN_S:.0f}-{_ANSWER_DELAY_MAX_S:.0f}s, "
        f"mute after {_MUTE_AFTER_S:.0f}s)")
    last_accept = 0.0
    told_busy = {}                    # roster name -> time we last told them
    mute_at = 0.0                     # when to mute after answering; 0 = idle
    while True:
        try:
            now = time.time()

            # Mute a few seconds into a call we answered.
            if mute_at and now >= mute_at:
                mute_at = 0.0
                log(f"muting our mic ~{_MUTE_AFTER_S:.0f}s into the call: "
                    f"{mute_self()}")

            # Sweep away a call window that outlived its call. Cheap, and the
            # only thing standing between a finished call and NN answering
            # chat again.
            close_stale_call_window()

            if now - last_accept > 8:  # de-bounce: don't re-accept same call
                btn = find_accept_button()
                if btn is not None:
                    if in_call():
                        # Already recording: accept nothing, say so once.
                        who = caller_name(btn)
                        if not who:
                            log("second call ringing while in a call; caller "
                                "not recognised, left it ringing")
                            time.sleep(4)
                            continue
                        if (now - told_busy.get(who, 0.0)) > _BUSY_GAP_S:
                            ok = tell_caller_busy(who)
                            told_busy[who] = time.time()
                            log(f"BUSY: declined to answer {who} while in a "
                                f"call; polite message sent={ok}")
                        time.sleep(4)
                        continue
                    # Let it ring first. Poll while we wait so a caller who
                    # gives up is noticed instead of being "answered" into a
                    # window that has already gone.
                    delay = random.uniform(_ANSWER_DELAY_MIN_S,
                                           _ANSWER_DELAY_MAX_S)
                    log(f"incoming call ringing — letting it ring "
                        f"{delay:.1f}s before answering")
                    rang = 0.0
                    hung_up = False
                    while rang < delay:
                        time.sleep(0.5)
                        rang += 0.5
                        if find_accept_button() is None:
                            hung_up = True
                            break
                    if hung_up:
                        log(f"caller hung up after ~{rang:.1f}s — nothing to "
                            f"answer")
                        continue
                    # Re-find it: the reference we matched before the wait can
                    # be stale by now, and invoking a stale control silently
                    # does nothing.
                    btn = find_accept_button()
                    if btn is None:
                        log("accept button vanished at the moment of answering")
                        continue
                    name = btn.Name
                    try:
                        btn.GetInvokePattern().Invoke()
                    except Exception:
                        try:
                            btn.Click(simulateMove=False)
                        except Exception as ce:
                            log(f"click failed on '{name}': {ce}")
                            time.sleep(1.5)
                            continue
                    last_accept = time.time()
                    told_busy.clear()          # new call, fresh slate
                    mute_at = last_accept + _MUTE_AFTER_S
                    log(f"ACCEPTED incoming call via button '{name}' after "
                        f"~{rang:.1f}s of ringing")
                    time.sleep(8)
                    continue
            time.sleep(1.5)
        except Exception as e:
            log(f"loop error: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()
