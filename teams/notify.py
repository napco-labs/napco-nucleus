"""Send a one-off Teams chat message to someone via UI automation.

Usage:  py -3 -m teams.notify <search> <message ...>
  <search>  = Teams login/email (or name) to open the chat with
  <message> = the text to send (rest of the args)

Reuses the auto_reply UIA helpers. Only works while the screen is UNLOCKED.
Exit 0 on success, 1 on failure.
"""
import sys
import time

import uiautomation as auto
from teams import auto_reply as ar


def send(search, message):
    win = ar._teams_window()
    if win is None:
        print("Teams window not found (locked screen?)")
        return False
    ar.activate_window(win)
    time.sleep(0.6)
    auto.SendKeys("{Ctrl}n", waitTime=0.1)          # new chat
    time.sleep(1.3)
    auto.SendKeys(ar._sk_escape(search), waitTime=0.05)
    time.sleep(1.6)
    auto.SendKeys("{Enter}", waitTime=0.1)           # pick suggestion
    time.sleep(0.9)
    auto.SendKeys("{Enter}", waitTime=0.1)           # focus message box
    time.sleep(1.0)
    return ar.send_reply(win, message, human=False)  # paste (emoji/Bangla ok)


def main():
    if len(sys.argv) < 3:
        print("usage: py -3 -m teams.notify <search> <message>")
        return 1
    search = sys.argv[1]
    message = " ".join(sys.argv[2:])
    ok = send(search, message)
    print("sent" if ok else "send failed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
