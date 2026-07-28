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
from teams import dev_names

_HERE = Path(__file__).parent
_REPO = _HERE.parent
LIST_FILE = _HERE / "dev_list.json"
STATE_FILE = _REPO / "data" / "reminder_state.json"
REACHED_FILE = _REPO / "data" / "reached_devs.json"
LOG = r"E:\napco-nucleus\logs\remind_devs.log"

BST = timezone(timedelta(hours=6))
# Titu 2026-07-27: remind EVERY colleague between 17:00 and 17:30 BD, with at
# least 5 minutes between two people, Monday to Friday. The scheduled task
# fires every 5 min inside that window and each run reminds exactly ONE person,
# which is what produces the spacing -- no sleeping inside the process.
WINDOW_START_MIN = 17 * 60          # 17:00 BD
WINDOW_END_MIN = 17 * 60 + 30       # 17:30 BD
MIN_GAP_SECONDS = 300               # >= 5 minutes between two colleagues
MAX_PER_DAY = 99                    # the window is the real limit now
MODEL = "claude-sonnet-5"

# Only one kind of nudge now. Titu 2026-07-27: professional and respectful,
# short, and the point is simply that they do not forget to add the assistant.
# The joke / quiz / "fun" types were removed -- they read as banter, and a
# colleague who jokes at people unprompted is not the tone we want.
ENGAGE_TYPES = ["meeting"]

MEETING_TEMPLATES = [
    "{name} bhai, if you have a client call today, please add Napco Nucleus so the requirements are captured.",
    "{name} bhai, please add me to any client call today and I will take care of the notes.",
    "Hello {name} bhai, a gentle reminder to add Napco Nucleus to any client call today.",
    "{name} ভাই, আজ কোনো ক্লায়েন্ট কল থাকলে অনুগ্রহ করে আমাকে অ্যাড করে নিবেন।",
    "{name} bhai, please keep me in today's client call if there is one, so nothing is missed.",
]
# Kept as names so any stale reference still resolves, but they now hold the
# same respectful wording rather than jokes.
JOKE_FALLBACK = MEETING_TEMPLATES
QUIZ_FALLBACK = MEETING_TEMPLATES
FUN_FALLBACK = MEETING_TEMPLATES


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
    """Is this run allowed to remind someone right now?"""
    if force:
        return True, "forced"
    if now.weekday() > 4:                       # Mon=0 .. Fri=4
        return False, "not a weekday (Mon-Fri only)"
    mins = now.hour * 60 + now.minute
    if not (WINDOW_START_MIN <= mins < WINDOW_END_MIN):
        return False, "outside 17:00-17:30 BD (now %s)" % now.strftime("%H:%M")
    st = _load_state()
    if st.get("date") == now.strftime("%Y-%m-%d"):
        since = time.time() - float(st.get("last_at", 0) or 0)
        if since < MIN_GAP_SECONDS:
            return False, "only %.0fs since the last colleague (need %ds)" % (
                since, MIN_GAP_SECONDS)
    return True, "ok"


def _sent_today(now):
    st = _load_state()
    if st.get("date") != now.strftime("%Y-%m-%d"):
        return set()
    return {str(x).lower() for x in st.get("sent", [])}


def _bump_state(now, who=""):
    st = _load_state()
    today = now.strftime("%Y-%m-%d")
    if st.get("date") != today:
        st = {"date": today, "sent": [], "count": 0}
    st["count"] = st.get("count", 0) + 1
    st["last_at"] = time.time()
    if who:
        st.setdefault("sent", []).append(who)
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
                           cwd=str(_REPO), timeout=45, shell=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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
    """Open the dev's chat and PROVE we are in it before anyone types.

    The old version clicked the first chat-list entry that matched and
    returned True regardless, and the Ctrl+N fallback returned True without
    ever looking at where it landed. Two ways to message the wrong colleague,
    and no way to tell that it happened.

    Chat-list entries include the last-message preview, so a search for
    "Rocky" also matched Zaman's chat when Zaman had just written the word
    (seen live 2026-07-28). find_chat_items matches the contact name only and
    returns every candidate, so we can try each and check.
    """
    want = str(dev.get("name") or "").strip()
    ar.activate_window(win)
    time.sleep(0.5)

    match = str(dev.get("chat") or want).strip()
    if match:
        for item in ar.find_chat_items(win, match):
            if not ar.open_chat(item):
                continue
            time.sleep(1.5)
            here = (ar.chat_partner(win) or "").strip()
            if here and dev_names.resolve(here) == want:
                return True
            log("chat click landed on '%s', not %s - trying next" % (here, want))

    # fallback: Ctrl+N search by login, still verified before we accept it
    search = str(dev.get("search") or want)
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
    time.sleep(1.4)
    here = (ar.chat_partner(win) or "").strip()
    if here and dev_names.resolve(here) == want:
        return True
    log("search fallback landed on '%s', not %s - refusing to send" % (here, want))
    return False


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
                # KEEP "chat". Dropping it here is why every send failed on
                # 2026-07-27: open_chat_with looks for dev["chat"], found
                # nothing, and fell back to matching on the short name.
                devs.append({"search": s, "name": n or s,
                             "chat": str(d.get("chat", "")).strip()})
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

    # ONE colleague per run. The 5-minute spacing comes from the schedule,
    # not from sleeping in-process -- a long sleep would hold the Teams window
    # hostage and block auto_reply from answering anyone meanwhile.
    already = _sent_today(now)
    pending = [d for d in devs if d["name"].lower() not in already]
    if not pending:
        log("every colleague already reminded today (%d)" % len(already))
        print("all reminded today")
        return 0

    d = pending[0]
    name, search = d["name"], d["search"]
    kind, msg = compose(name)
    log("reminding '%s' (%s) [%s]; %d left after this"
        % (name, search, kind, len(pending) - 1))

    sent = 0
    try:
        if not open_chat_with(win, d):
            # Could not prove we are in the right chat. Sending anyway would
            # put a reminder meant for one colleague into somebody else's
            # conversation; the old code ignored this return value entirely.
            log("could not reach %s's chat - not sending, will retry next run" % name)
            print("could not reach %s" % name)
            return 0
        if ar.send_reply(win, msg, human=False):
            sent = 1
            _bump_state(now, who=name)
            log("sent to '%s': %s" % (name, msg[:60]))
        else:
            log("send FAILED to '%s' - will retry next run" % name)
    except Exception as e:
        log("error for '%s': %s" % (name, str(e)[:120]))

    if len(pending) - sent > 0:
        mins_left = WINDOW_END_MIN - (now.hour * 60 + now.minute)
        if (len(pending) - sent) * (MIN_GAP_SECONDS / 60.0) > mins_left:
            log("WARNING: %d colleague(s) still to remind but only %d min left "
                "in the window - widen WINDOW_END_MIN or shorten MIN_GAP_SECONDS"
                % (len(pending) - sent, mins_left))

    print("reminded %d this run, %d pending" % (sent, len(pending) - sent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
