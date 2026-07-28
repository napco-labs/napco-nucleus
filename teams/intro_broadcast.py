"""One-time: introduce Napco Nucleus to every dev in dev_list.json.

Sends a short 4-paragraph intro (personalized by name) to each dev's chat.
Run ONCE, in the interactive desktop session (screen unlocked):
    py -3 -m teams.intro_broadcast
"""
import sys
import json
import time
from pathlib import Path

import uiautomation as auto
from teams import auto_reply as ar

_HERE = Path(__file__).parent
_REPO = _HERE.parent
LIST_FILE = _HERE / "dev_list.json"
SENT_FILE = _REPO / "data" / "intro_sent.json"      # names already introduced -> skip
LOG = r"E:\napco-nucleus\logs\intro_broadcast.log"

INTRO = (
    "Hi {name} bhai, I am Napco Nucleus, your new AI teammate built by Kamrul "
    "Hasan. I join your client calls and chats and turn what is discussed into "
    "clear, tracked requirements for the team. Please add me to your client "
    "meetings just like any teammate, that is all you need to do. No more "
    "note-taking or missing a requirement. Thanks a lot bhai :)"
)


def _send_plain(win, text):
    """Type the message as a PLAIN Teams message (Shift+Enter for line breaks)
    so a multi-line paste never gets auto-converted into a Loop component."""
    box = ar.find_compose(win)
    if box is None:
        return False
    try:
        box.SetFocus()
        time.sleep(0.2)
        box.SendKeys("{Ctrl}a{Delete}", waitTime=0.02)
        for i, line in enumerate(text.split("\n")):
            if i > 0:
                box.SendKeys("+{Enter}", waitTime=0.05)   # Shift+Enter = soft break
            box.SendKeys(ar._sk_escape(line), waitTime=0.012)
        time.sleep(0.3)
        return ar._submit(win, box)
    except Exception as e:
        log(f"plain send failed: {e}")
        return False


def log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {m}\n")
    except Exception:
        pass


def _open(win, dev):
    match = str(dev.get("chat") or dev.get("name") or "").strip()
    item = ar.find_chat_item(win, match) if match else None
    if item is not None and ar.open_chat(item):
        time.sleep(1.3)
        return True
    search = str(dev.get("search") or dev.get("name") or "")
    ar.activate_window(win)
    time.sleep(0.5)
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
    try:
        data = json.loads(LIST_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"dev_list unreadable: {e}")
        return 1
    devs = [d if isinstance(d, dict) else {"search": str(d), "name": str(d)}
            for d in data.get("devs", []) if d]

    def _load_sent():
        try:
            return {str(x).strip().lower()
                    for x in json.loads(SENT_FILE.read_text(encoding="utf-8"))}
        except Exception:
            return set()

    def _save_sent(s):
        try:
            SENT_FILE.parent.mkdir(parents=True, exist_ok=True)
            SENT_FILE.write_text(json.dumps(sorted(s), indent=2), encoding="utf-8")
        except Exception:
            pass

    already = _load_sent()
    win = ar._teams_window()
    if win is None:
        log("Teams window not found (locked screen?)")
        print("Teams not found")
        return 1
    sent = 0
    for d in devs:
        name = d.get("name") or d.get("search") or "there"
        if name.strip().lower() in already:
            log(f"skip {name} (already introduced)")
            continue
        msg = INTRO.replace("{name}", name)
        log(f"intro -> {name}")
        try:
            _open(win, d)
            if _send_plain(win, msg):                  # TYPE it (no paste -> no Loop)
                sent += 1
                already.add(name.strip().lower())
                _save_sent(already)                    # record immediately
                log(f"sent to {name}")
            else:
                log(f"send returned False for {name}")
        except Exception as e:
            log(f"error for {name}: {e}")
        time.sleep(4)
    log(f"done: intro sent to {sent}/{len(devs)}")
    print(f"sent {sent}/{len(devs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
