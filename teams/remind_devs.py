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
WINDOW_START_MIN = 16 * 60          # 16:00 BD
WINDOW_END_MIN = 17 * 60            # 17:00 BD (Titu moved it 2026-07-28)
# A full hour holds twelve 5-minute slots for seven colleagues, so the spacing
# can stay gentle. It was briefly cut to 4 minutes to squeeze everyone into a
# 30-minute window; widening to 17:00-18:00 removed that pressure, and wider
# spacing is also less like a machine working through a list.
MIN_GAP_SECONDS = 300
MAX_PER_DAY = 99                    # the window is the real limit now
MODEL = "claude-sonnet-5"

# Only one kind of nudge now. Titu 2026-07-27: professional and respectful,
# short, and the point is simply that they do not forget to add the assistant.
# The joke / quiz / "fun" types were removed -- they read as banter, and a
# colleague who jokes at people unprompted is not the tone we want.
ENGAGE_TYPES = ["meeting"]

# Colleagues never to interrupt while they are on a call, by name.
# Salman works from the USA and relays client requirements back; a nudge in the
# middle of his call is the last thing he needs (Titu, 2026-07-28).
NEVER_INTERRUPT = {"salman"}

# Marker record_call drops while the assistant is itself capturing a call.
RECORDING_MARKER = _REPO / "data" / "teams" / ".recording_active"

# Sent when Teams shows a colleague is on a call RIGHT NOW. Short, because
# they are mid-conversation and will read it at a glance or not at all.
IN_CALL_TEMPLATES = [
    "{name} bhai, I can see you are on a call. If it is a client call, please add me and I will take the notes.",
    "{name} bhai, sorry to interrupt. If this is a client call, please add Napco Nucleus so nothing is missed.",
    "{name} bhai, if you are with a client now, please add me to the call and I will capture the requirements.",
    "{name} ভাই, আপনি কলে আছেন দেখছি। ক্লায়েন্ট কল হলে অনুগ্রহ করে আমাকে অ্যাড করে নিবেন।",
]

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


def _bump_state(now, who="", message=""):
    st = _load_state()
    today = now.strftime("%Y-%m-%d")
    if st.get("date") != today:
        st = {"date": today, "sent": [], "messages": [], "count": 0}
    st["count"] = st.get("count", 0) + 1
    st["last_at"] = time.time()
    if who:
        st.setdefault("sent", []).append(who)
    # Keep the actual wording, so tomorrow's first message and today's later
    # ones can be checked against what has already gone out. Without this each
    # colleague is written for in isolation and they drift back towards the
    # same sentence.
    if message:
        st.setdefault("messages", []).append(message)
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
                           encoding="utf-8", errors="replace",
                           cwd=str(_REPO), timeout=45, shell=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (p.stdout or "").strip()
        return out or None
    except Exception as e:
        log(f"claude gen failed ({kind}): {str(e)[:80]}")
        return None


def _claude_meeting(name, already_sent):
    """A fresh, individually written reminder for `name`. None on failure.

    Titu, 2026-07-28: "you will not send the same message to everybody. Use
    human tone, politeness." Seven colleagues drawing from five fixed
    templates guarantees repeats, and a person who sends the identical
    sentence to the whole team reads as a mailshot, which is exactly what this
    is trying not to be.

    Previously sent messages are passed in so today's are visibly different
    from each other, not just different by luck.
    """
    avoid = ""
    if already_sent:
        lines = "\n".join("- " + m for m in already_sent[-6:])
        avoid = ("\n\nYou have already sent these to OTHER colleagues today. "
                 "Yours must be clearly different in wording and structure, "
                 "not a reshuffle of the same sentence:\n" + lines)
    prompt = (
        f"You are Napco Nucleus, a courteous colleague on a Bangladeshi dev "
        f"team. Write ONE short message to your teammate {name}, politely "
        f"asking them to add you to any client call today so you can capture "
        f"the requirements and take care of the meeting notes.\n\n"
        f"Rules:\n"
        f"- address them as '{name} bhai'\n"
        f"- warm, respectful, and genuinely polite: use please\n"
        f"- ONE or two short sentences, no more\n"
        f"- plain everyday words, no corporate phrasing, no assistant phrasing\n"
        f"- NO dashes as punctuation, use a comma or a full stop\n"
        f"- no markdown, no bullet points, no headings, no emoji\n"
        f"- English, or simple Bangla; if Bangla, use the respectful আপনি "
        f"form and never তুমি\n"
        f"- do not introduce yourself, they know who you are\n"
        f"- output ONLY the message text, nothing else"
        f"{avoid}")
    try:
        # encoding MUST be utf-8. Without it Python uses the console codepage
        # (cp1252 on this box) and the call dies with "'charmap' codec can't
        # encode characters" the moment the prompt contains Bangla, which it
        # always does because the rules mention আপনি and তুমি. The failure is
        # caught below and silently falls back to a template, so the symptom
        # was "the messages are all identical" rather than an error anyone saw
        # (2026-07-28).
        p = subprocess.run(["claude", "--print", "--model", MODEL],
                           input=prompt, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           cwd=str(_REPO), timeout=45, shell=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (p.stdout or "").strip()
        # a stray dash would break Titu's standing rule, so repair rather than
        # discard an otherwise good message
        out = out.replace(" -- ", ", ").replace(" — ", ", ").replace(" – ", ", ")
        return out or None
    except Exception as e:
        log(f"claude gen failed (meeting): {str(e)[:80]}")
        return None


def compose_in_call(name):
    """Message for a colleague Teams shows as being on a call right now.

    Deliberately a template rather than a Claude generation: they are mid
    conversation, and waiting up to 45 seconds for a model to write something
    clever means the call may be over before the message lands.
    """
    return random.choice(IN_CALL_TEMPLATES).replace("{name}", name)


def compose(name, already_sent=None):
    already_sent = already_sent or []
    gen = _claude_meeting(name, already_sent)
    if gen and len(gen) <= 320:
        return "meeting", gen
    if gen:
        log("claude message too long (%d chars), using a template" % len(gen))
    # Fall back to a template we have NOT already used today, so even the
    # fallback path does not send the same line twice.
    used = {m.strip().lower() for m in already_sent}
    pool = [t for t in MEETING_TEMPLATES
            if t.replace("{name}", name).strip().lower() not in used]
    return "meeting", random.choice(pool or MEETING_TEMPLATES).replace("{name}", name)


def dev_is_busy(win, dev):
    """True when Teams shows this colleague on a call / in a meeting /
    presenting / do-not-disturb.

    Read straight off the chat-list entry, which carries presence between the
    name and the message preview, so it needs no API, no tenant and no extra
    round trip. A reminder that lands in the middle of a client call is worse
    than no reminder, and it is the exact call we are asking to be added to.
    """
    match = str(dev.get("chat") or dev.get("name") or "").strip()
    if not match:
        return False
    try:
        for item in ar.find_chat_items(win, match):
            nm = item.Name or ""
            if ar.dev_names.resolve(ar._item_contact(nm)) != dev.get("name"):
                continue
            return ar.is_busy_presence(nm)
    except Exception as e:
        log("presence check failed for %s: %s" % (dev.get("name"), str(e)[:60]))
    return False


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

    # Somebody being ON a call is the BEST moment to ask, not a reason to wait
    # (Titu, 2026-07-28). That call is exactly the one we want to be added to,
    # so they get a different, immediate message instead of the generic nudge.
    #
    # Two conditions on that. We only ask if WE are free: the assistant holds a
    # single Teams account and can only be in one call at a time, so inviting
    # ourselves into a second one while recording the first would be a promise
    # we cannot keep. And never Salman, by name, whatever list he appears on.
    d, in_call = None, False
    we_are_busy = RECORDING_MARKER.exists()
    for cand in pending:
        busy = dev_is_busy(win, cand)
        if not busy:
            d = cand
            break
        if cand["name"].strip().lower() in NEVER_INTERRUPT:
            log("%s is busy, and is on the never-interrupt list - skipping" % cand["name"])
            continue
        if we_are_busy:
            log("%s is on a call but so are we - not asking to join a second one"
                % cand["name"])
            continue
        d, in_call = cand, True
        log("%s is on a call right now - asking them to add me to it" % cand["name"])
        break
    if d is None:
        log("nobody available to remind this run")
        print("nobody available")
        return 0

    name, search = d["name"], d["search"]
    if in_call:
        kind, msg = "in-call", compose_in_call(name)
    else:
        kind, msg = compose(name, _load_state().get("messages", []))
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
        # TYPE it, slowly, like every other sender in the system.
        #
        # human=False takes the clipboard-paste branch, and pasting is what
        # Teams turns into a Loop component that then cannot be submitted: the
        # text appears in the box and is wiped when the send fails. Titu
        # watched exactly that happen in Rocky's chat on 2026-07-28, and the
        # log still said "sent". Typing is the path that has worked all day
        # for replies, knocks and relays.
        #
        # single=False because this module never loads auto_reply_rules.json,
        # so SINGLE_SENTENCE is still the module default True and would cut the
        # reminder down to its first sentence.
        if ar.send_reply(win, msg, human=True, think=(0.4, 1.0),
                         type_speed=0.02, single=False):
            sent = 1
            _bump_state(now, who=name, message=msg)
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
