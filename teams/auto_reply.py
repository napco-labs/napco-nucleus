"""Auto-reply for the Meeting Assistant's Teams chats (canned + Claude).

Runs in the interactive desktop session (scheduled task at logon), same UIA
technique as teams/auto_answer.py. For each NEW incoming message in the focused
Teams conversation:
  1. If it matches a canned rule in auto_reply_rules.json -> use that reply
     (instant, deterministic; e.g. "who are you" -> "I am Napco Nucleus").
  2. Otherwise, if use_claude is on, ask the local Claude (`claude --print`)
     with the Napco Nucleus persona in nucleus_persona.md and use its answer.
Then type the reply into the compose box and press Enter.

SAFETY
  * Persona prompt keeps replies short, on-identity, no business commitments,
    no internal-info leaks.
  * Self-echo guard: never replies to a message equal to one we just sent
    (prevents Claude answering its own replies in a loop).
  * De-bounced on the last answered message.
  * UIA selectors are HINTS -- tune against the live Teams build via
    logs\auto_reply.log (cannot be verified over headless WinRM).

Run:  py -3 -m teams.auto_reply
"""
import re
import os
import json
import time
import random
import ctypes
import asyncio
import datetime
import threading
import subprocess
from collections import deque
from pathlib import Path

import uiautomation as auto

_HERE = Path(__file__).parent
_REPO = _HERE.parent
RULES_FILE = _HERE / "auto_reply_rules.json"
PERSONA_FILE = _HERE / "nucleus_persona.md"
LOG = r"E:\napco-nucleus\logs\auto_reply.log"

COMPOSE_HINTS = ("type a message", "type a new message", "type a reply",
                 "message", "compose")
MESSAGE_CTRL_TYPES = (auto.ControlType.ListItemControl,
                      auto.ControlType.TextControl,
                      auto.ControlType.GroupControl)

DEFAULT_POLL_S = 3.0
DEFAULT_CLAUDE_TIMEOUT = 45
MAX_REPLY_CHARS = 800

# varied, human-sounding "you already asked this" lines (a repeat within 30 min)
ALREADY_ANSWERED = [
    "I just answered that above, {first} bhai :)",
    "Already replied to this one, {first} bhai, please scroll up a little",
    "That one is answered above, {first} bhai",
    "I covered this just now, {first} bhai, take a look above",
    "এটা তো একটু আগেই বললাম ভাই :)",
    "উপরে একটু দেখুন ভাই, উত্তরটা উপরেই আছে",
]

_DIAG = False                           # set from settings.diagnose (get_incoming logging)

# compose-box placeholder strings that must NOT be treated as incoming messages
PLACEHOLDER_TEXTS = {
    "type a message", "type a new message", "type a reply", "message",
    "compose", "type a message...", "type a new message...",
}

# Teams labels a message bubble one of two ways depending on build/view:
#   "Message from <sender>. <content>"   OR   "<content> by <sender>"
_MSG_FROM_RE = re.compile(r"^message from (.+?)\s*[.,:;-]\s+(.+?)\s*$", re.I)
_MSG_BY_RE = re.compile(r"^(.+?)\s+by\s+(.+?)\s*$", re.I)


def _parse_msg(t):
    """Return (content, sender) if t is a message bubble label, else None."""
    m = _MSG_FROM_RE.match(t)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    m = _MSG_BY_RE.match(t)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None
# Teams window/doc title: "Chat | <partner name> | Microsoft Teams"
_CHAT_TITLE_RE = re.compile(r"chat \| (.+?) \| microsoft teams", re.I)
# UI chrome that must NEVER be treated as an incoming message
_NOISE_RE = re.compile(
    r"^\s*(\d+\s+results?|\d+\s+new(\s+messages?)?|results?|no results|"
    r"search.*|seen\b.*|delivered|sent|edited|.*\bis typing\b.*|"
    r"\d{1,2}:\d{2}\s*(am|pm)?.*|today at .*|yesterday.*|napco nucleus)\s*$",
    re.I)
# devs who have engaged/added the assistant -> reminder stops nudging them
REACHED_FILE = _REPO / "data" / "reached_devs.json"


def log(msg: str) -> None:
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except Exception:
        pass


def load_rules():
    try:
        data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], {}, []
    except Exception as e:
        log(f"rules file unreadable: {e}")
        return [], {}, []
    rules = []
    for r in data.get("rules", []):
        contains = [str(c).strip().lower() for c in r.get("contains", []) if str(c).strip()]
        rr = r.get("reply", "")
        if isinstance(rr, list):
            reply = [str(x).strip() for x in rr if str(x).strip()]
        else:
            reply = str(rr).strip()
        if contains and reply:
            rules.append({"contains": contains, "reply": reply,
                          "always": bool(r.get("always", False))})
    cmds = []
    for c in data.get("commands", []):
        contains = [str(x).strip().lower() for x in c.get("contains", []) if str(x).strip()]
        if contains and (c.get("task") or c.get("trigger") or c.get("report_cmd")):
            cmds.append({"contains": contains,
                         "task": str(c.get("task", "")),
                         "trigger": str(c.get("trigger", "")),
                         "report_cmd": str(c.get("report_cmd", "")),
                         "dedup": bool(c.get("dedup", False)),
                         "ack": str(c.get("ack", "")).strip()})
    return rules, data.get("settings", {}), cmds


def match_reply(text, rules):
    low = (text or "").strip().lower()
    if not low:
        return None
    for r in rules:
        for c in r["contains"]:
            # word-boundary so short triggers ("hi") don't match inside words
            if re.search(r"\b" + re.escape(c) + r"\b", low):
                rep = r["reply"]
                return random.choice(rep) if isinstance(rep, list) else rep
    return None


def _canned_texts(rules):
    """All possible canned reply strings (flattening reply pools) - echo guard."""
    out = set()
    for r in rules:
        rep = r["reply"]
        for x in (rep if isinstance(rep, list) else [rep]):
            out.add(str(x).strip().lower())
    return out


def is_always(text, rules):
    """True if text matches an 'always'-reply rule (greetings/thanks/courtesy) -
    these bypass the 30-min repeat suppression and always get a friendly reply."""
    low = (text or "").strip().lower()
    if not low:
        return False
    for r in rules:
        if r.get("always"):
            for c in r["contains"]:
                if re.search(r"\b" + re.escape(c) + r"\b", low):
                    return True
    return False


DEV_LIST_FILE = _HERE / "dev_list.json"


def load_allowlist():
    """Names/emails allowed to trigger COMMANDS (run pipeline, health check).
    Built from dev_list.json so only the known devs can drive backend actions."""
    try:
        data = json.loads(DEV_LIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return set()
    out = set()
    for d in data.get("devs", []):
        if isinstance(d, dict):
            for k in ("name", "search", "chat"):
                v = str(d.get(k, "")).strip().lower()
                if v:
                    out.add(v)
        elif str(d).strip():
            out.add(str(d).strip().lower())
    return out


def is_allowed(who, allow):
    w = (who or "").strip().lower()
    if not w or not allow:
        return False
    return any(a and (a in w or w in a) for a in allow)


def match_command(text, commands):
    """Return the command dict whose trigger phrase is in text, else None."""
    low = (text or "").strip().lower()
    if not low:
        return None
    for c in commands:
        for phrase in c.get("contains", []):
            p = str(phrase).strip().lower()
            if p and re.search(r"\b" + re.escape(p) + r"\b", low):
                return c
    return None


def dispatch_task(cmd, requester=""):
    """Trigger the pipeline on central (.123). Runs the command's `trigger`
    string in the background (typically an ssh into .123 that kicks the
    pipeline; .123 does the extract + email). Also writes an audit line."""
    trigger = str(cmd.get("trigger", "")).strip()
    task = str(cmd.get("task", "")).strip()
    try:
        q = _REPO / "data" / "command_requests.jsonl"
        q.parent.mkdir(parents=True, exist_ok=True)
        with open(q, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "task": task, "requester": requester}) + "\n")
    except Exception:
        pass
    if not trigger:
        log(f"command '{task}' from '{requester}': no trigger configured yet")
        return
    try:
        logf = _REPO / "logs" / "agent" / "pipeline-trigger.log"
        logf.parent.mkdir(parents=True, exist_ok=True)
        out = open(logf, "a", encoding="utf-8")
        out.write(f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} "
                  f"requester={requester} ===\n{trigger}\n")
        out.flush()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(trigger, stdout=out, stderr=out, cwd=str(_REPO),
                         shell=True, creationflags=flags)
        log(f"triggered pipeline on .123 for '{requester or '?'}'")
    except Exception as e:
        log(f"pipeline trigger failed: {e}")


class WarmSDK:
    """One Claude Agent SDK client kept warm in a background asyncio thread so
    replies skip the cold-start. Reconnects on error and every RECONNECT_EVERY
    asks so conversation history stays short (bounds cross-message context).
    Used in a small POOL (see _warm_ask) so one recycling client never stalls
    replies, and no single client accumulates many different people's messages."""
    RECONNECT_EVERY = 4

    def __init__(self, system, model):
        self.system = system
        self.model = model or "claude-haiku-4-5-20251001"
        self.loop = None
        self.client = None
        self._asks = 0
        self._recycle = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._main())
        except Exception as e:
            log(f"warm sdk thread died: {str(e)[:120]}")

    async def _main(self):
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        opts = ClaudeAgentOptions(system_prompt=self.system, model=self.model)
        while True:
            try:
                async with ClaudeSDKClient(options=opts) as client:
                    self.client = client
                    self._recycle = False
                    self._asks = 0
                    log("warm sdk connected")
                    while not self._recycle:
                        await asyncio.sleep(1)
            except Exception as e:
                log(f"warm sdk reconnect: {str(e)[:100]}")
            self.client = None
            await asyncio.sleep(2)

    def ask(self, message, timeout=25):
        if self.client is None or self.loop is None:
            return None

        async def _q():
            from claude_agent_sdk import AssistantMessage, TextBlock
            await self.client.query(message)
            parts = []
            async for m in self.client.receive_response():
                if isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, TextBlock):
                            parts.append(b.text)
            return "".join(parts).strip()
        try:
            fut = asyncio.run_coroutine_threadsafe(_q(), self.loop)
            out = (fut.result(timeout=timeout) or "").strip()
        except Exception as e:
            log(f"warm sdk ask failed: {str(e)[:100]}")
            return None
        self._asks += 1
        if self._asks >= self.RECONNECT_EVERY:
            self._recycle = True          # recycle to keep context small
        return out[:MAX_REPLY_CHARS] if out else None


_WARM_POOL = []
POOL_SIZE = 2


def _ensure_pool(system, model):
    global _WARM_POOL
    if not _WARM_POOL:
        _WARM_POOL = [WarmSDK(system, model) for _ in range(POOL_SIZE)]
        time.sleep(0.2)


def _warm_ask(system, user, model, timeout_s):
    """Ask via the first READY client in the pool (skips any that are
    reconnecting). Returns None if none ready -> caller falls back to the CLI."""
    try:
        _ensure_pool(system, model)
        for w in _WARM_POOL:
            if w.client is not None:
                out = w.ask(user, timeout=timeout_s)
                if out is not None:
                    return out
        return None
    except Exception as e:
        log(f"warm ask error: {str(e)[:100]}")
        return None


def _central_fingerprint():
    """Fingerprint (size+mtime+name of latest transcripts) of the napco-nucleus
    folder on central, via SSH. Same content -> same fingerprint -> skip re-run."""
    cmd = ("ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "
           "ubuntu@172.16.205.123 \"ls --time-style=+%s -l "
           "/srv/nucleus-central/napco-nucleus/*/calls/*_transcript.md 2>/dev/null "
           "| awk '{print $5, $6, $7}' | sort\"")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=20)
        return (p.stdout or "").strip()
    except Exception as e:
        log(f"fingerprint failed: {str(e)[:80]}")
        return ""


def _pipeline_last_fp():
    try:
        f = _REPO / "data" / "pipeline_lastrun.json"
        return json.loads(f.read_text(encoding="utf-8")).get("fingerprint", "")
    except Exception:
        return ""


def _set_pipeline_fp(fp):
    try:
        f = _REPO / "data" / "pipeline_lastrun.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"fingerprint": fp,
                     "ts": datetime.datetime.now().isoformat(timespec="seconds")}),
                     encoding="utf-8")
    except Exception as e:
        log(f"set fp failed: {str(e)[:80]}")


def run_report(report_cmd, model, timeout_s=25):
    """Run a READ-ONLY status command (e.g. ssh into .123 to gather pipeline
    health), then summarize its output with Claude into a short chat report."""
    try:
        proc = subprocess.run(report_cmd, capture_output=True, text=True,
                              cwd=str(_REPO), shell=True, timeout=timeout_s)
        raw = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    except Exception as e:
        return f"I could not reach the pipeline to check right now ({e})."
    if not raw:
        return "I checked, but the pipeline returned no status data."
    ask = ("Summarize this requirement management pipeline status into a short, "
           "friendly report: 1-3 sentences, plain language, no em dashes. Say if "
           "it looks healthy or if something is down. Reply with the report text "
           "only.\n\nRAW STATUS:\n" + raw[:4000])
    out = _warm_ask("", ask, model, 30)
    return out if out else raw[:400]


def claude_answer(message, timeout_s, model="", sender=""):
    """Answer AS Napco Nucleus. FAST path = warm SDK; fallback = CLI."""
    try:
        persona = PERSONA_FILE.read_text(encoding="utf-8")
    except Exception:
        persona = ("You are Napco Nucleus, an AI meeting assistant. Reply "
                   "briefly and politely. Output only the reply text.")
    who = f"You are replying to {sender}. " if sender else ""
    user = (f"{who}Reply ONLY to this one Teams message below. Ignore any earlier "
            f"messages in this session - they may be from a DIFFERENT person, so "
            f"never reference them or say 'as I told you'.\n\n"
            f"Message: {message}\n\n"
            f"Reply with the reply text ONLY, 1-3 short sentences.")
    out = _warm_ask(persona, user, model, timeout_s)   # warm SDK, no cold-start
    if out:
        return out
    # fallback: Claude CLI (slower, but works if the API path fails)
    prompt = f"{persona}\n\n{user}\n"
    cmd = ["claude", "--print"] + (["--model", model] if model else [])
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              cwd=str(_REPO), timeout=timeout_s, shell=True)
    except Exception as e:
        log(f"claude cli failed: {e}")
        return None
    out = (proc.stdout or "").strip()
    return out[:MAX_REPLY_CHARS] if out else None


def dump_ui(win):
    """Diagnostic: log compose-box candidates + last message rows so the UIA
    selectors can be tuned from the log (the desktop can't be seen remotely)."""
    try:
        edits = []

        def walk(c, d):
            if d > 40:
                return
            try:
                if c.ControlType in (auto.ControlType.EditControl,
                                     auto.ControlType.DocumentControl):
                    try:
                        ctn = c.ControlTypeName
                    except Exception:
                        ctn = str(c.ControlType)
                    edits.append(f"[{ctn}] name='{(c.Name or '')[:45]}' "
                                 f"aid='{(c.AutomationId or '')[:30]}'")
                for ch in c.GetChildren():
                    walk(ch, d + 1)
            except Exception:
                return
        for ch in win.GetChildren():
            walk(ch, 0)
        log("DIAG edit/doc controls: " + (" ## ".join(edits[:15]) if edits else "NONE FOUND"))
        texts = []
        for ch in win.GetChildren():
            _collect_text(ch, texts, 0)
        log("DIAG last6 text rows: " + " || ".join(t[:45] for t in texts[-6:]))
        log(f"DIAG partner='{chat_partner(win)}'")
        mf = [t[:70] for t in texts if t.lower().startswith('message from')]
        log("DIAG msg-from rows: " + (" || ".join(mf[-4:]) if mf else "NONE"))
        # dump chat-list items (left rail) to learn the 'unread' marker
        items = []

        def _w2(c, d):
            if d > 25 or len(items) > 40:
                return
            try:
                if c.ControlType in (auto.ControlType.ListItemControl,
                                     auto.ControlType.TreeItemControl):
                    nm = (c.Name or "").strip()
                    if nm:
                        items.append(nm[:70])
                for ch in c.GetChildren():
                    _w2(ch, d + 1)
            except Exception:
                return
        for ch in win.GetChildren():
            _w2(ch, 0)
        log("DIAG chat-list items: " + " ## ".join(items[:25]))
    except Exception as e:
        log(f"DIAG error: {e}")


def chat_partner(win):
    """Return the name in 'Chat | <name> | Microsoft Teams', or ''."""
    try:
        m = _CHAT_TITLE_RE.search(win.Name or "")
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    found = []

    def walk(c, d):
        if d > 6 or found:
            return
        try:
            mm = _CHAT_TITLE_RE.search(c.Name or "")
            if mm:
                found.append(mm.group(1).strip())
                return
            for ch in c.GetChildren():
                walk(ch, d + 1)
        except Exception:
            return
    try:
        for ch in win.GetChildren():
            walk(ch, 0)
    except Exception:
        pass
    return found[0] if found else ""


def mark_reached(name):
    """Record a dev who has engaged the assistant so the reminder stops nudging
    them ('once they add you, stop sending messages')."""
    if not name:
        return
    try:
        data = (json.loads(REACHED_FILE.read_text(encoding="utf-8"))
                if REACHED_FILE.exists() else [])
    except Exception:
        data = []
    if name.lower() not in [str(d).lower() for d in data]:
        data.append(name)
        try:
            REACHED_FILE.parent.mkdir(parents=True, exist_ok=True)
            REACHED_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            log(f"marked reached (stop reminding): {name}")
        except Exception as e:
            log(f"reached write failed: {e}")


def _teams_window():
    root = auto.GetRootControl()
    try:
        for win in root.GetChildren():
            nm = (win.Name or "").lower()
            cls = (win.ClassName or "")
            if "teams" in nm or "Teams" in cls:
                return win
    except Exception as e:
        log(f"window scan error: {e}")
    return None


def find_unread(win):
    """Return [(item, contact_name)] for chat-list entries marked unread.
    Teams labels them 'Unread message Chat <name> Available/Away ... Last message'."""
    out = []

    def walk(c, d):
        if d > 25:
            return
        try:
            if c.ControlType in (auto.ControlType.ListItemControl,
                                 auto.ControlType.TreeItemControl):
                nm = c.Name or ""
                if "unread message" in nm.lower():
                    m = re.search(r"chat\s+(.+?)\s+(?:available|away|busy|offline|"
                                  r"do not disturb|be right back|last message)",
                                  nm, re.I)
                    out.append((c, m.group(1).strip() if m else ""))
            for ch in c.GetChildren():
                walk(ch, d + 1)
        except Exception:
            return
    try:
        for ch in win.GetChildren():
            walk(ch, 0)
    except Exception:
        pass
    return out


def find_chat_item(win, match):
    """Find a left-rail chat-list item whose name contains `match` (a display
    name substring). Returns the control to click, or None. Reliable for
    opening an EXISTING contact's chat (no Ctrl+N search needed)."""
    m = (match or "").strip().lower()
    if not m:
        return None
    found = []

    def walk(c, d):
        if d > 25 or found:
            return
        try:
            if c.ControlType in (auto.ControlType.ListItemControl,
                                 auto.ControlType.TreeItemControl):
                nm = (c.Name or "").lower()
                if ("chat " in nm or "unread message" in nm) and m in nm:
                    found.append(c)
                    return
            for ch in c.GetChildren():
                walk(ch, d + 1)
        except Exception:
            return
    try:
        for ch in win.GetChildren():
            walk(ch, 0)
    except Exception:
        pass
    return found[0] if found else None


def open_chat(item):
    """Click/select a chat-list item to open that conversation."""
    for how in ("invoke", "select", "click"):
        try:
            if how == "invoke":
                item.GetInvokePattern().Invoke()
            elif how == "select":
                item.GetSelectionItemPattern().Select()
            else:
                item.Click(simulateMove=False)
            return True
        except Exception:
            continue
    return False


def get_incoming(win, own_names, self_sent):
    """Return (content, sender) of the newest message, ONLY if it is from the
    chat partner (the person named in 'Chat | <partner> | Microsoft Teams').

    This is the robust discriminator: a message 'Message from <partner>.' is
    incoming; anything else (our own replies -> a different sender, system text,
    UI chrome with no 'Message from' label) is skipped. No loose fallback, so it
    never answers itself or chrome.
    """
    partner = chat_partner(win)
    plow = partner.strip().lower() if partner else ""
    rows = []                  # (name, bottom_y) - position tells us newest
    try:
        for ctrl in win.GetChildren():
            _collect_rows(ctrl, rows, 0)
    except Exception as e:
        log(f"read error: {e}")
        return "", ""
    best = None
    best_y = -1                # newest partner message (largest bottom_y)
    our_y = -1                 # newest of OUR own messages/replies
    own_rows = []              # diag: what got counted as "ours"
    for nm, by in rows:
        low = nm.strip().lower()
        if not low or low in PLACEHOLDER_TEXTS or _NOISE_RE.match(low):
            continue
        # skip left-rail chat-list entries (they embed "Last message You: ...")
        if ("last message" in low or "unread message" in low
                or low.startswith("chat ")):
            continue
        if any(s and (low == s or low.startswith(s[:20]) or s.startswith(low[:20]))
               for s in self_sent):
            our_y = max(our_y, by)         # our reply position
            if _DIAG:
                own_rows.append((nm[:26], by, "self"))
            continue
        got = _parse_msg(nm.strip())
        if not got:
            continue
        content, sender = got
        slow = sender.lower()
        if slow in own_names:
            our_y = max(our_y, by)         # our own bubble
            if _DIAG:
                own_rows.append((nm[:26], by, "own"))
            continue
        if plow and (slow == plow or slow in plow or plow in slow):
            if by > best_y:
                best_y, best = by, (content, sender)
    if _DIAG:
        near = sorted([r for r in own_rows if r[1] >= best_y - 30], key=lambda x: -x[1])[:4]
        log(f"DIAG gi best={best} best_y={best_y} our_y={our_y} "
            f"own_near_best={near}")
    if best is None:
        return "", ""
    if our_y >= best_y:                    # our reply is below it -> already answered
        return "", ""
    content, sender = best
    lc = content.lower()
    if content and lc not in PLACEHOLDER_TEXTS and not _NOISE_RE.match(lc):
        return content, sender
    return "", ""


def _collect_rows(ctrl, out, depth):
    """Collect (name, bottom_y screen position) for message-like controls."""
    if depth > 40:
        return
    try:
        if ctrl.ControlType in MESSAGE_CTRL_TYPES:
            nm = (ctrl.Name or "").strip()
            if nm and len(nm) > 1:
                try:
                    by = ctrl.BoundingRectangle.bottom
                except Exception:
                    by = 0
                out.append((nm, by))
        for ch in ctrl.GetChildren():
            _collect_rows(ch, out, depth + 1)
    except Exception:
        return


def _collect_text(ctrl, out, depth):
    if depth > 40:
        return
    try:
        if ctrl.ControlType in MESSAGE_CTRL_TYPES:
            nm = (ctrl.Name or "").strip()
            if nm and len(nm) > 1:
                out.append(nm)
        for child in ctrl.GetChildren():
            _collect_text(child, out, depth + 1)
    except Exception:
        return


def _is_compose(ctrl):
    try:
        if ctrl.ControlType != auto.ControlType.EditControl:
            return False
        nm = (ctrl.Name or "").lower()
        aid = (ctrl.AutomationId or "").lower()
        if aid.startswith("new-message"):   # Teams compose box, strongest signal
            return True
        return any(h in nm or h in aid for h in COMPOSE_HINTS)
    except Exception:
        return False


def find_compose(win):
    """Manual tree walk (win.Control(Compare=) does not descend into the Teams
    web content reliably). Returns the compose EditControl or None."""
    found = []

    def walk(c, d):
        if d > 45 or found:
            return
        try:
            if _is_compose(c):
                found.append(c)
                return
            for ch in c.GetChildren():
                walk(ch, d + 1)
        except Exception:
            return
    try:
        for ch in win.GetChildren():
            walk(ch, 0)
            if found:
                break
    except Exception as e:
        log(f"compose walk error: {e}")
    return found[0] if found else None


_SK_SPECIAL = {'{': '{{}', '}': '{}}', '+': '{+}', '^': '{^}', '%': '{%}',
               '~': '{~}', '(': '{(}', ')': '{)}', '[': '{[}', ']': '{]}'}


def _sk_escape(text):
    return ''.join(_SK_SPECIAL.get(ch, ch) for ch in text)


def activate_window(win):
    """Foreground + restore the Teams window so we can read/reply regardless of
    its prior state (minimized/background) and the dev sees 'Seen'."""
    try:
        h = win.NativeWindowHandle
        if h:
            ctypes.windll.user32.ShowWindow(h, 9)          # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(h)
    except Exception:
        pass
    try:
        win.SetActive()
    except Exception:
        try:
            win.SetFocus()
        except Exception:
            pass


def nudge_input():
    """Tiny mouse move to reset OS idle so Teams presence never goes Away."""
    try:
        ctypes.windll.user32.mouse_event(0x0001, 1, 0, 0, 0)
        ctypes.windll.user32.mouse_event(0x0001, -1, 0, 0, 0)
    except Exception:
        pass


def _find_send_button(win):
    """Find the Teams 'Send' button, so we submit reliably even if the account
    is set to Ctrl+Enter-to-send or focus drifts after typing."""
    found = []

    def walk(c, d):
        if d > 45 or found:
            return
        try:
            if c.ControlType == auto.ControlType.ButtonControl:
                nm = (c.Name or "").strip().lower()
                aid = (c.AutomationId or "").lower()
                if (nm == "send" or nm == "send message" or nm.startswith("send ")
                        or aid == "send" or aid.startswith("sendmessage")):
                    found.append(c)
                    return
            for ch in c.GetChildren():
                walk(ch, d + 1)
        except Exception:
            return
    try:
        for ch in win.GetChildren():
            walk(ch, 0)
    except Exception:
        pass
    return found[0] if found else None


def _compose_value(win):
    """Best-effort read of the compose box text. '' = empty, None = unreadable."""
    try:
        b = find_compose(win)
        if b is None:
            return None
        try:
            v = b.GetValuePattern().Value
            if v is not None:
                return v.strip()
        except Exception:
            pass
        nm = (b.Name or "").strip()
        return "" if nm.lower() in PLACEHOLDER_TEXTS else nm
    except Exception:
        return None


def _submit(win, box):
    """Submit and VERIFY the compose box emptied. Tries Send button, then
    Ctrl+Enter, then Enter - so it works regardless of the send-key setting and
    never leaves a 'written but not sent' message."""
    def _click_send():
        b = _find_send_button(win)
        if b is None:
            return
        try:
            b.GetInvokePattern().Invoke()
        except Exception:
            try:
                b.Click(simulateMove=False)
            except Exception:
                pass

    def _keys(seq):
        try:
            bx = find_compose(win)
            if bx:
                bx.SetFocus()
                time.sleep(0.1)
                bx.SendKeys(seq, waitTime=0.05)
        except Exception:
            pass

    for i, way in enumerate((_click_send,
                             lambda: _keys("{Ctrl}{Enter}"),
                             lambda: _keys("{Enter}"))):
        way()
        time.sleep(0.4)
        v = _compose_value(win)
        if v is None:
            return True                 # cannot verify -> assume it went (Send btn)
        if not v or len(v) < 2:
            return True                 # box emptied -> definitely sent
    log("submit: compose still has text after all send methods")
    return False


def send_reply(win, text, human=True, think=(0.2, 0.5), type_speed=0.02):
    activate_window(win)                 # 'Seen' + let keystrokes land
    time.sleep(0.3)
    box = find_compose(win)
    if box is None:
        log("compose box NOT found")
        return False
    try:
        box.SetFocus()
        time.sleep(0.15)
        box.SendKeys("{Ctrl}a{Delete}", waitTime=0.02)     # clear any draft
        # char-by-char typing only for plain English (SendKeys cannot produce
        # Bangla or emoji) -> those are pasted from clipboard instead
        non_ascii = any(ord(c) > 127 for c in text)
        if human and not non_ascii:
            time.sleep(random.uniform(*think))             # brief think pause
            box.SendKeys(_sk_escape(text), waitTime=type_speed)   # shows 'typing...'
        else:
            if human:
                time.sleep(random.uniform(*think))
            auto.SetClipboardText(text)
            time.sleep(0.1)
            box.SendKeys("{Ctrl}v", waitTime=0.05)
        time.sleep(0.35)
        return _submit(win, box)           # click Send button (reliable)
    except Exception as e:
        log(f"send failed: {e}; trying clipboard fallback")
        try:
            box.SetFocus()
            auto.SetClipboardText(text)
            box.SendKeys("{Ctrl}a{Delete}{Ctrl}v", waitTime=0.05)
            time.sleep(0.3)
            return _submit(win, box)
        except Exception as e2:
            log(f"fallback send failed: {e2}")
            return False


def main():
    log("auto_reply (canned + claude + commands) watcher started")
    rules, settings, commands = load_rules()
    poll = float(settings.get("poll_seconds", DEFAULT_POLL_S))
    use_claude = bool(settings.get("use_claude", True))
    claude_timeout = int(settings.get("claude_timeout_s", DEFAULT_CLAUDE_TIMEOUT))
    diagnose = bool(settings.get("diagnose", False))
    globals()["_DIAG"] = diagnose
    human_typing = bool(settings.get("human_typing", True))
    keep_alive = bool(settings.get("keep_alive", True))
    keep_alive_s = int(settings.get("keep_alive_seconds", 50))
    claude_model = str(settings.get("claude_model", "")).strip()
    think = (float(settings.get("think_min", 0.2)),
             float(settings.get("think_max", 0.5)))
    type_speed = float(settings.get("type_speed", 0.02))
    cooldown = float(settings.get("reply_cooldown_s", 8))
    reply_gap = float(settings.get("reply_gap_s", 5))
    repeat_window = float(settings.get("repeat_window_s", 1800))
    own_names = {str(n).strip().lower() for n in settings.get("own_names", ["Napco Nucleus"])}
    log(f"{len(rules)} canned rule(s); use_claude={use_claude}; poll={poll}s; "
        f"model={claude_model or 'default'}; human_typing={human_typing}; "
        f"keep_alive={keep_alive}; cooldown={cooldown}s")
    canned_texts = _canned_texts(rules)
    cmd_allow = load_allowlist()   # who may trigger commands (from dev_list)
    self_sent = deque(maxlen=15)   # our own recent replies (echo guard)
    answered_at = {}                     # "contact|question" -> time answered (30-min window)
    last_reply_at = {}                   # contact -> time of last reply (per-contact gap)
    last_nudge = 0.0
    rules_mtime = _mtime(RULES_FILE)

    # pre-warm the SDK client at startup so the FIRST reply is already fast
    if use_claude:
        try:
            _persona = PERSONA_FILE.read_text(encoding="utf-8")
        except Exception:
            _persona = "You are Napco Nucleus."
        try:
            _ensure_pool(_persona, claude_model)
            log(f"pre-warming SDK pool (size {POOL_SIZE})")
        except Exception as e:
            log(f"pre-warm failed: {str(e)[:100]}")

    def handle_open_chat(win):
        """Read the currently-open chat and reply once (if a new partner msg)."""
        nonlocal answered_at
        msg, sender = get_incoming(win, own_names, self_sent)
        low = msg.strip().lower()
        if not low or low in canned_texts or low in self_sent or low in PLACEHOLDER_TEXTS:
            return
        who = sender or chat_partner(win)
        first = who.split()[0] if who else ""
        clow = who.strip().lower()
        norm = re.sub(r"\s+\S.*?today at .+$", "", low, flags=re.I).strip() or low
        key = f"{clow}|{norm}"                       # repeat key is PER CONTACT
        # per-contact gap: replying to one dev never blocks replying to another
        if (time.time() - last_reply_at.get(clow, 0)) < reply_gap:
            return
        already = (key in answered_at
                   and (time.time() - answered_at[key]) < repeat_window)
        if already and is_always(msg, rules):
            already = False
        activate_window(win)                         # mark 'Seen'
        if already:
            rep = random.choice(ALREADY_ANSWERED).replace("{first}", first).replace("  ", " ").strip()
            send_reply(win, rep, human=human_typing, think=think, type_speed=type_speed)
            self_sent.append(rep.strip().lower())
            last_reply_at[clow] = time.time()
            log(f"REPEAT notice to '{first}'")
            return
        cmd = match_command(msg, commands)
        if cmd and not is_allowed(who, cmd_allow):
            log(f"command from non-allowed '{who}' ignored -> normal reply")
            cmd = None                       # not a dev -> no backend actions
        if cmd and cmd.get("report_cmd"):
            rep = run_report(cmd["report_cmd"], claude_model)
            send_reply(win, rep, human=human_typing, think=think, type_speed=type_speed)
            self_sent.append(rep.strip().lower())
            log(f"REPORTED to '{first}'")
        elif cmd and cmd.get("dedup"):
            fp = _central_fingerprint()
            if fp and fp == _pipeline_last_fp():
                rep = (f"Okay {first} bhai, but I already ran on the latest calls, "
                       f"so skipping to avoid a duplicate.").replace("  ", " ").strip()
                send_reply(win, rep, human=human_typing, think=think, type_speed=type_speed)
                self_sent.append(rep.strip().lower())
                log(f"DEDUP skip for '{first}'")
            else:
                ack = (cmd.get("ack") or "Okay {sender} bhai").replace(
                    "{sender}", first).replace("  ", " ").strip()
                send_reply(win, ack, human=human_typing, think=think, type_speed=type_speed)
                dispatch_task(cmd, who)
                if fp:
                    _set_pipeline_fp(fp)
                self_sent.append(ack.strip().lower())
                log(f"RUN pipeline (new) by '{first}'")
        elif cmd:
            ack = (cmd.get("ack") or "Okay {sender} bhai").replace(
                "{sender}", first).replace("  ", " ").strip()
            send_reply(win, ack, human=human_typing, think=think, type_speed=type_speed)
            dispatch_task(cmd, who)
            self_sent.append(ack.strip().lower())
            log(f"COMMAND '{cmd.get('task')}' by '{first}'")
        else:
            reply = match_reply(msg, rules)
            src = "canned"
            if reply is None and use_claude:
                reply = claude_answer(msg, claude_timeout, claude_model, sender=first)
                src = "claude"
            if reply and send_reply(win, reply, human=human_typing,
                                    think=think, type_speed=type_speed):
                self_sent.append(reply.strip().lower())
                log(f"REPLIED[{src}] to '{msg[:40]}' -> '{reply[:60]}'")
        answered_at[key] = time.time()
        if len(answered_at) > 400:
            cut = time.time() - repeat_window
            answered_at = {k: v for k, v in answered_at.items() if v > cut}
        last_reply_at[clow] = time.time()
        # NOTE: do NOT mark_reached here. Chatting is not the same as adding NN
        # to a meeting. The reminder must keep nudging until the dev actually
        # adds the assistant (tracked manually via dev_list "added", or by real
        # call-capture attribution later). Auto-marking on chat wrongly silenced
        # reminders after a single "hi".

    while True:
        try:
            mt = _mtime(RULES_FILE)
            if mt != rules_mtime:
                rules, settings, commands = load_rules()
                poll = float(settings.get("poll_seconds", DEFAULT_POLL_S))
                use_claude = bool(settings.get("use_claude", True))
                claude_timeout = int(settings.get("claude_timeout_s", DEFAULT_CLAUDE_TIMEOUT))
                diagnose = bool(settings.get("diagnose", False))
                globals()["_DIAG"] = diagnose
                human_typing = bool(settings.get("human_typing", True))
                keep_alive = bool(settings.get("keep_alive", True))
                keep_alive_s = int(settings.get("keep_alive_seconds", 50))
                claude_model = str(settings.get("claude_model", "")).strip()
                think = (float(settings.get("think_min", 0.2)),
                         float(settings.get("think_max", 0.5)))
                type_speed = float(settings.get("type_speed", 0.02))
                cooldown = float(settings.get("reply_cooldown_s", 8))
                reply_gap = float(settings.get("reply_gap_s", 5))
                repeat_window = float(settings.get("repeat_window_s", 1800))
                own_names = {str(n).strip().lower() for n in settings.get("own_names", ["Napco Nucleus"])}
                canned_texts = _canned_texts(rules)
                cmd_allow = load_allowlist()
                rules_mtime = mt
                log(f"rules reloaded: {len(rules)} rule(s); use_claude={use_claude}")

            # keep-alive: reset OS idle so Teams presence never shows 'Away'
            if keep_alive and (time.time() - last_nudge) > keep_alive_s:
                nudge_input()
                last_nudge = time.time()

            win = _teams_window()
            if win is not None:
                if diagnose:
                    dump_ui(win)
                # 1) any UNREAD chats? open each and reply (handles parallel devs)
                unread = find_unread(win)
                if diagnose:
                    log(f"DIAG unread found={[c for _, c in unread]}")
                if unread:
                    for item, contact in unread:
                        if open_chat(item):
                            time.sleep(1.3)          # let the chat switch + render
                            handle_open_chat(win)
                else:
                    # 2) nothing unread -> handle whatever chat is currently open
                    handle_open_chat(win)
            time.sleep(poll)
        except Exception as e:
            log(f"loop error: {e}")
            time.sleep(max(poll, 3.0))


def _mtime(p):
    try:
        return p.stat().st_mtime
    except Exception:
        return 0.0


if __name__ == "__main__":
    main()
