"""Proactive daily engagement to devs from Napco Nucleus.

Once a day (max), reaches out to each developer in teams/dev_list.json with a
VARIED message, like a human colleague:
  * often a meeting nudge ("do you have a client meeting today? add me")
  * sometimes a joke, a quiz/riddle, or a fun one-liner
Rules (non-annoying):
  * Bangladesh time (UTC+6) only, between 17:00 and 22:00 (5-10 PM BST).
  * At most ONCE per day. Skips Saturday and Sunday.
  * Skips any dev who has already added/engaged the assistant.
Run often (scheduled task every 30 min); the gate decides if it actually sends.
Only works while the MASTAN2 screen is UNLOCKED (UI automation limitation).

Run:  py -3 -m teams.remind_devs        (add --force to bypass the time gate)
"""
import sys
import json
import time
import random
import datetime
import subprocess
from datetime import timezone, timedelta
from pathlib import Path

import uiautomation as auto
from teams import auto_reply as ar

_HERE = Path(__file__).parent
_REPO = _HERE.parent
LIST_FILE = _HERE / "dev_list.json"
STATE_FILE = _REPO / "data" / "reminder_state.json"
REACHED_FILE = _REPO / "data" / "reached_devs.json"
LOG = r"E:\napco-nucleus\logs\remind_devs.log"

BST = timezone(timedelta(hours=6))
WINDOW_START, WINDOW_END = 17, 22
MAX_PER_DAY = 1
MODEL = "claude-haiku-4-5-20251001"

# message TYPES for the day; "meeting" weighted higher (that is the real goal)
ENGAGE_TYPES = ["meeting", "meeting", "meeting", "joke", "quiz", "fun"]

MEETING_TEMPLATES = [
    "{name} bhai, do you have any client meeting today? Please add Napco Nucleus so I can capture everything for you :)",
    "{name} bhai, kono client call ache aj? Amake add korte vulben na jeno, ami sob capture kore nibo :)",
    "Hi {name} bhai, if you have a client call today, add me in so nothing gets missed.",
    "{name} ভাই, আজ কোনো ক্লায়েন্ট মিটিং থাকলে আমাকে অ্যাড করে নেবেন :)",
    "{name} bhai, meeting thakle amake dhukiye diyen, note-taking ta ami samle nibo :)",
]
JOKE_FALLBACK = [
    "{name} bhai, why did the developer go broke? He used up all his cache :)",
    "{name} bhai, ekta bug ar ekta feature er difference ki? Documentation :)",
    "{name} bhai, koto jon programmer lage ekta bulb lagate? Zero, that's a hardware problem :)",
]
QUIZ_FALLBACK = [
    "{name} bhai, quick riddle: I speak without a mouth and hear without ears. What am I?",
    "{name} bhai, puzzle: what has keys but opens no locks, space but no room? :)",
    "{name} bhai, ekta puzzle: 8 ta 8 diye kivabe 1000 banabe? (Hint: 888+88+8+8+8) :)",
]
FUN_FALLBACK = [
    "{name} bhai, ei to, chup kore boshe apnader requirement gulo capture korchi :)",
    "{name} bhai, zero salary, no lunch break, never forgets. Just add me to your meetings :)",
    "{name} bhai, adda dite mon chaiche but kaj age! Add me to a call na :)",
]


def log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {m}\n")
    except Exception:
        pass


def _load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(s):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"state save failed: {e}")


def _gate(now, force):
    if force:
        return True, "forced"
    if now.weekday() >= 5:
        return False, "weekend (skip Sat/Sun)"
    if not (WINDOW_START <= now.hour < WINDOW_END):
        return False, f"outside 17:00-22:00 BST (now {now:%H:%M})"
    st = _load_state()
    if st.get("date") == now.strftime("%Y-%m-%d") and st.get("count", 0) >= MAX_PER_DAY:
        return False, "already reached out today"
    return True, "ok"


def _bump_state(now):
    st = _load_state()
    today = now.strftime("%Y-%m-%d")
    if st.get("date") != today:
        st["date"] = today
        st["count"] = 0
    st["count"] = st.get("count", 0) + 1
    _save_state(st)


def _claude_gen(kind, name):
    """Fresh joke/quiz/fun line via Claude, in colleague tone. None on failure."""
    common = (f"Keep it SIMPLE, clear and easy to understand at a glance. Use "
              f"short, everyday words. No confusing or overly clever wordplay. "
              f"Address the person as '{name} bhai'. Mostly plain English; a "
              f"little simple Bangla is fine. Output only the message, 1-2 lines.")
    prompts = {
        "joke": f"Write ONE short, simple, clearly funny joke for your dev teammate {name}. {common}",
        "quiz": f"Write ONE short and EASY fun riddle for your dev teammate {name} to solve. Make it simple and clear, not tricky. {common}",
        "fun": f"Write ONE short, fun, friendly one-liner to your dev teammate {name}, gently hinting to add Napco Nucleus to their meetings. {common}",
    }
    try:
        p = subprocess.run(["claude", "--print", "--model", MODEL],
                           input=prompts[kind], capture_output=True, text=True,
                           cwd=str(_REPO), timeout=45, shell=True)
        out = (p.stdout or "").strip()
        return out or None
    except Exception as e:
        log(f"claude gen failed ({kind}): {str(e)[:80]}")
        return None


def compose(name):
    kind = random.choice(ENGAGE_TYPES)
    if kind == "meeting":
        return "meeting", random.choice(MEETING_TEMPLATES).replace("{name}", name)
    gen = _claude_gen(kind, name)
    if gen:
        return kind, gen
    fb = {"joke": JOKE_FALLBACK, "quiz": QUIZ_FALLBACK, "fun": FUN_FALLBACK}[kind]
    return kind, random.choice(fb).replace("{name}", name)


def open_chat_with(win, dev):
    """Open the dev's chat. Prefer clicking their EXISTING chat in the list
    (reliable); fall back to Ctrl+N search only if not found."""
    ar.activate_window(win)
    time.sleep(0.5)
    match = str(dev.get("chat") or dev.get("name") or "").strip()
    item = ar.find_chat_item(win, match) if match else None
    if item is not None and ar.open_chat(item):
        time.sleep(1.3)
        return True
    # fallback: Ctrl+N search by the search term (email)
    search = str(dev.get("search") or dev.get("name") or "")
    auto.SendKeys("{Ctrl}n", waitTime=0.1)
    time.sleep(1.5)
    auto.SendKeys("{Ctrl}a", waitTime=0.05)
    auto.SendKeys("{Delete}", waitTime=0.05)
    time.sleep(0.4)
    auto.SendKeys(ar._sk_escape(search), waitTime=0.06)
    time.sleep(2.2)
    auto.SendKeys("{Enter}", waitTime=0.1)
    time.sleep(1.1)
    auto.SendKeys("{Enter}", waitTime=0.1)
    time.sleep(1.1)
    return True


def main():
    force = "--force" in sys.argv[1:]
    now = datetime.datetime.now(BST)
    ok, reason = _gate(now, force)
    if not ok:
        log(f"skip: {reason}")
        print(f"skip: {reason}")
        return 0
    try:
        data = json.loads(LIST_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"dev_list unreadable: {e}")
        return 1
    devs = []
    for d in data.get("devs", []):
        if isinstance(d, dict):
            s = str(d.get("search", "")).strip()
            n = str(d.get("name", "")).strip()
            if s:
                devs.append({"search": s, "name": n or s})
        elif str(d).strip():
            s = str(d).strip()
            devs.append({"search": s, "name": s})
    if not devs:
        log("dev_list empty - add devs to teams/dev_list.json")
        print("dev_list empty")
        return 0

    reached = []
    try:
        if REACHED_FILE.exists():
            reached += json.loads(REACHED_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    reached += data.get("added", [])
    reached_low = [str(r).strip().lower() for r in reached if str(r).strip()]

    def _is_reached(d):
        nm, se = d["name"].lower(), d["search"].lower()
        return any((r in nm or nm in r or r == se) for r in reached_low)
    devs = [d for d in devs if not _is_reached(d)]
    if not devs:
        log("all listed devs already added the assistant - nothing to send")
        print("all devs reached")
        return 0

    win = ar._teams_window()
    if win is None:
        log("Teams window not found (locked screen?)")
        print("Teams not found")
        return 1

    sent = 0
    for d in devs:
        name, search = d["name"], d["search"]
        kind, msg = compose(name)
        log(f"engaging '{name}' ({search}) ({kind})")
        try:
            open_chat_with(win, d)                        # open the dev's chat
            if ar.send_reply(win, msg, human=False):     # paste (emoji/Bangla)
                sent += 1
                log(f"sent [{kind}] to '{name}': {msg[:50]}")
            else:
                log(f"send FAILED to '{name}'")
        except Exception as e:
            log(f"error for '{name}': {e}")
        time.sleep(random.uniform(3.0, 6.0))
    if sent:
        _bump_state(now)
        log(f"done: engaged {sent}/{len(devs)} devs today")
    print(f"engaged {sent}/{len(devs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
