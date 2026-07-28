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
import sys
import time
import datetime
from pathlib import Path

import uiautomation as auto

_REPO = Path(__file__).parent.parent

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
    log("auto_answer watcher started")
    last_accept = 0.0
    told_busy = {}                    # roster name -> time we last told them
    while True:
        try:
            now = time.time()
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
                    log(f"ACCEPTED incoming call via button '{name}'")
                    time.sleep(8)
                    continue
            time.sleep(1.5)
        except Exception as e:
            log(f"loop error: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()
