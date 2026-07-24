"""Gentle scheduled reminder to devs: add Napco Nucleus to your meetings.

Sends a short, friendly nudge to each developer in teams/dev_list.json via
Teams. Designed to be NON-annoying and rule-bound:
  * Bangladesh time (UTC+6) only.
  * Only between 17:00 and 22:00 (5 PM - 10 PM BST).
  * At most TWICE per day, and the two sends are spaced >= 2 hours apart.
  * Skips Saturday and Sunday.
Run it often (e.g. a scheduled task every 30 min); the gating below decides
whether this run actually sends. State persists in data/reminder_state.json so
the twice-a-day / spacing rules survive restarts.

Only works while the MASTAN2 screen is UNLOCKED (UI automation limitation).

Run:  py -3 -m teams.remind_devs        (add --force to bypass the time gate)
"""
import sys
import json
import time
import random
import datetime
from datetime import timezone, timedelta
from pathlib import Path

import uiautomation as auto
from teams import auto_reply as ar

_HERE = Path(__file__).parent
_REPO = _HERE.parent
LIST_FILE = _HERE / "dev_list.json"
STATE_FILE = _REPO / "data" / "reminder_state.json"
REACHED_FILE = _REPO / "data" / "reached_devs.json"   # devs who already added him
LOG = r"E:\napco-nucleus\logs\remind_devs.log"

BST = timezone(timedelta(hours=6))       # Bangladesh Standard Time
WINDOW_START, WINDOW_END = 17, 22        # 5 PM .. 10 PM
MAX_PER_DAY = 2
MIN_GAP_MIN = 120                        # >= 2 hours between the two sends

SOFT_DEFAULT = [
    "Hi :) gentle reminder to add Napco Nucleus to your client meetings so I "
    "can capture the requirements for you. Thanks so much!",
    "Hello :) just a soft nudge, add Napco Nucleus to your calls and chats and "
    "I will take care of capturing everything. Appreciate it!",
    "Hi there :) whenever you have a client meeting, add Napco Nucleus so "
    "nothing gets missed. Thank you!",
]
# gentle, workplace-friendly humor - used SOMETIMES so it stays fresh
JOKE_DEFAULT = [
    "Psst :) it's Napco Nucleus. Add me to your client calls and I'll do the "
    "boring note-taking while you look brilliant. Deal?",
    "Hi :) your friendly AI here. Add me to your meetings and I promise to "
    "remember every requirement. My memory never needs coffee :)",
    "Knock knock :) it's Napco Nucleus. Add me to your calls and no requirement "
    "will ever sneak past. I do not blink!",
    "Hi :) I work for zero salary and never take lunch breaks. Just add me to "
    "your client meetings and your requirements are safe with me :)",
    "Reminder from Napco Nucleus :) add me to the call. I am great at listening "
    "and terrible at forgetting. Thanks a ton!",
]
JOKE_CHANCE = 0.25                       # low per-run chance...
MAX_JOKES_PER_WEEK = 2                    # ...capped so humor is once/twice a WEEK


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
    """Return (ok, reason). now is a BST-aware datetime."""
    if force:
        return True, "forced"
    if now.weekday() >= 5:                        # 5=Sat, 6=Sun
        return False, "weekend (skip Sat/Sun)"
    if not (WINDOW_START <= now.hour < WINDOW_END):
        return False, f"outside 17:00-22:00 BST (now {now:%H:%M})"
    st = _load_state()
    today = now.strftime("%Y-%m-%d")
    if st.get("date") != today:
        return True, "first send today"
    if st.get("count", 0) >= MAX_PER_DAY:
        return False, "already sent twice today"
    last = st.get("last_ts", 0)
    if last and (now.timestamp() - last) < MIN_GAP_MIN * 60:
        mins = int((MIN_GAP_MIN * 60 - (now.timestamp() - last)) / 60)
        return False, f"too soon (wait ~{mins} min for spacing)"
    return True, "second send allowed"


def _bump_state(now, joke_run=False):
    st = _load_state()
    today = now.strftime("%Y-%m-%d")
    if st.get("date") != today:
        st["date"] = today
        st["count"] = 0
        st["last_ts"] = 0
    st["count"] = st.get("count", 0) + 1
    st["last_ts"] = now.timestamp()
    week = now.strftime("%G-W%V")            # ISO year-week
    if st.get("joke_week") != week:
        st["joke_week"] = week
        st["joke_week_count"] = 0
    if joke_run:
        st["joke_week_count"] = st.get("joke_week_count", 0) + 1
    _save_state(st)


def open_chat_with(win, name):
    """Open a 1:1 chat with `name` via Teams new-chat (Ctrl+N)."""
    ar.activate_window(win)
    time.sleep(0.6)
    auto.SendKeys("{Ctrl}n", waitTime=0.1)
    time.sleep(1.3)
    auto.SendKeys(ar._sk_escape(name), waitTime=0.05)
    time.sleep(1.6)
    auto.SendKeys("{Enter}", waitTime=0.1)       # pick first suggestion
    time.sleep(0.9)
    auto.SendKeys("{Enter}", waitTime=0.1)       # focus the message box
    time.sleep(1.0)


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
    devs = [str(d).strip() for d in data.get("devs", []) if str(d).strip()]
    soft = data.get("messages") or SOFT_DEFAULT
    jokes = data.get("jokes") or JOKE_DEFAULT
    if not devs:
        log("dev_list empty - no names to remind (add Teams display names)")
        print("dev_list empty")
        return 0

    # skip devs who have already added / engaged the assistant
    reached = []
    try:
        if REACHED_FILE.exists():
            reached += json.loads(REACHED_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    reached += data.get("added", [])                 # manual opt-out list too
    reached_low = {str(r).strip().lower() for r in reached}
    pending = [d for d in devs if d.lower() not in reached_low]
    skipped = [d for d in devs if d.lower() in reached_low]
    if skipped:
        log(f"skipping (already added): {', '.join(skipped)}")
    if not pending:
        log("all listed devs have already added the assistant - nothing to send")
        print("all devs reached")
        return 0
    devs = pending

    win = ar._teams_window()
    if win is None:
        log("Teams window not found (locked screen?)")
        print("Teams not found")
        return 1

    # humor only VERY sometimes: <= 2 per ISO week, low per-run chance
    week = now.strftime("%G-W%V")
    st0 = _load_state()
    jokes_wk = st0.get("joke_week_count", 0) if st0.get("joke_week") == week else 0
    joke_run = (bool(jokes) and jokes_wk < MAX_JOKES_PER_WEEK
                and random.random() < JOKE_CHANCE)
    pool = jokes if joke_run else soft
    log(f"tone: {'JOKE' if joke_run else 'soft'} (jokes this week={jokes_wk})")

    sent = 0
    for name in devs:
        msg = random.choice(pool)
        log(f"reminding '{name}' ({reason})")
        try:
            open_chat_with(win, name)
            if ar.send_reply(win, msg, human=False):   # paste (supports emoji)
                sent += 1
                log(f"sent to '{name}'")
            else:
                log(f"send FAILED to '{name}'")
        except Exception as e:
            log(f"error for '{name}': {e}")
        time.sleep(random.uniform(3.0, 6.0))
    if sent:
        _bump_state(now, joke_run)
        st = _load_state()
        log(f"done: {sent}/{len(devs)} reminded; today count={st.get('count')}; "
            f"tone={'JOKE' if joke_run else 'soft'}; jokes_this_week={st.get('joke_week_count')}")
    print(f"reminded {sent}/{len(devs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
