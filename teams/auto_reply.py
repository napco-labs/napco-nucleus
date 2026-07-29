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

from teams import chat_intake, civility, dev_names

# ---------------------------------------------------------------------------
# Force EVERY child process this daemon spawns to be windowless.
#
# Setting creationflags on our own subprocess.run calls was not enough: the
# warm claude_agent_sdk pool spawns the Claude CLI through its own async path,
# so two console windows appeared on the desktop (pool size 2 = 2 windows).
#
# That is not cosmetic. This process drives Teams through UI automation, and a
# window appearing mid-type STEALS FOCUS from the compose box -- the cause of
# the recurring "submit: compose still has text after all send methods".
#
# Patching Popen itself catches every spawner, including asyncio's, which on
# Windows goes through subprocess.Popen underneath.
# ---------------------------------------------------------------------------
if os.name == "nt":
    _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    _OrigPopen = subprocess.Popen

    class _NoWindowPopen(_OrigPopen):
        def __init__(self, *a, **kw):
            try:
                kw["creationflags"] = (kw.get("creationflags") or 0) | _CREATE_NO_WINDOW
            except Exception:
                pass
            super().__init__(*a, **kw)

    subprocess.Popen = _NoWindowPopen

# followups has no back-reference, so a top-level import is safe. teams.notify
# does `from teams import auto_reply`, so THAT one must stay lazy (below) or we
# get a circular import at startup.
try:
    from teams import followups
except ImportError:                     # running as a loose script
    import followups

_HERE = Path(__file__).parent
_REPO = _HERE.parent
RULES_FILE = _HERE / "auto_reply_rules.json"
PERSONA_FILE = _HERE / "nucleus_persona.md"
# Written by record_call while a Teams call is being captured. Same marker
# teams/live_heartbeat.py watches. Being in a call counts as being present.
RECORDING_MARKER = _REPO / "data" / "teams" / ".recording_active"
LOG = r"E:\napco-nucleus\logs\auto_reply.log"

COMPOSE_HINTS = ("type a message", "type a new message", "type a reply",
                 "message", "compose")
MESSAGE_CTRL_TYPES = (auto.ControlType.ListItemControl,
                      auto.ControlType.TextControl,
                      auto.ControlType.GroupControl)

DEFAULT_POLL_S = 3.0
DEFAULT_CLAUDE_TIMEOUT = 45
MAX_REPLY_CHARS = 800          # overridden by settings.max_reply_chars


ASCII_ONLY = True              # overridden by settings.ascii_only
SINGLE_SENTENCE = True         # overridden by settings.single_sentence

# ---------------------------------------------------------------------------
# Short per-contact conversation memory.
#
# Every Claude reply used to be generated from the incoming message ALONE, with
# the prompt explicitly ordering the model to ignore anything earlier. That was
# a guard against the warm SDK pool bleeding one person's chat into another's,
# but it also meant Nucleus could not see what IT had just said. On 2026-07-29
# it told Titu "my call recording only covers MS Teams, not Google Meet" and
# then, thirty seconds later, answered "join the meeting" with "On it, once the
# call starts I'll pick up the audio automatically" -- a promise it had just
# said it could not keep.
#
# The fix keeps the isolation and drops the amnesia: history is stored PER
# CONTACT (same key as last_reply_at) and only that contact's turns are ever
# put in a prompt, so cross-person leakage is still impossible.
# ---------------------------------------------------------------------------
TURN_MEMORY = {}               # contact key -> deque[(role, text)]
TURNS_KEPT = 6                 # last 3 exchanges; keeps the prompt small


def remember_turn(contact, role, text):
    """Record one turn of this contact's chat. role is 'them' or 'me'."""
    if not contact or not text:
        return
    d = TURN_MEMORY.get(contact)
    if d is None:
        d = TURN_MEMORY[contact] = deque(maxlen=TURNS_KEPT)
    d.append((role, " ".join(str(text).split())[:300]))
    # Bound the number of contacts we hold, not just the turns per contact.
    if len(TURN_MEMORY) > 60:
        for k in list(TURN_MEMORY)[:20]:
            TURN_MEMORY.pop(k, None)


def recent_turns(contact):
    """This contact's last few turns, oldest first. Never another contact's."""
    return list(TURN_MEMORY.get(contact) or ())


def _tidy_reply(text, limit=None, single=None):
    """Make a reply safe to type into Teams, and human to read.

    Order matters and was got wrong once: strip non-ASCII FIRST, then fix
    punctuation, otherwise removing Bangla leaves a stray comma at the front.

    Why each step exists:
      * one line     - in the char-by-char path a newline is sent as Enter,
                       which submits the message half-typed
      * ASCII only   - Bangla and emoji cannot be typed by SendKeys, so they
                       force a clipboard PASTE, and paste is what Teams turns
                       into a Loop component that then cannot be sent
      * no dashes    - Titu's standing rule; a dash is the clearest tell that
                       software wrote the sentence
      * short        - less time holding the compose box, less to go wrong
    """
    if not text:
        return text

    t = " ".join(str(text).split())

    if ASCII_ONLY:
        t = "".join(c if ord(c) < 128 else " " for c in t)
        t = " ".join(t.split())
    else:
        # ascii_only is OFF on .72 because replies have to be able to come back
        # in Bangla script. That lets emoji through too, and emoji do NOT
        # survive the SendKeys path: on 2026-07-29 a reply to Titu arrived
        # ending in a bare U+FFFD. Bangla, Hindi, Urdu and Arabic all live in
        # the BMP, emoji almost all live above it, so dropping astral
        # characters keeps every language and loses only the thing that was
        # arriving broken anyway. U+FFFD itself is stripped whatever the
        # source, and so are the invisible joiners Teams leaves in the box.
        t = "".join(
            "" if (ord(c) > 0xFFFF                      # emoji / pictographs
                   or c == "�"                     # already-mangled char
                   or c in "️︎‍⁠​"  # VS/ZWJ/joiners
                   or 0x2190 <= ord(c) <= 0x27BF        # arrows, dingbats
                   or 0x2B00 <= ord(c) <= 0x2BFF)
            else c
            for c in t)
        t = " ".join(t.split())

    for dash in ("—", "–", " -- ", "--", " - "):
        t = t.replace(dash, ", ")

    t = t.replace(" ,", ",")
    while ",," in t:
        t = t.replace(",,", ",")
    t = " ".join(t.split())

    t = t.lstrip(" ,;:.-").rstrip(" ,;:-")      # keep a closing . ! ?
    if not t:
        return ""
    t = t[0].upper() + t[1:]

    want_single = SINGLE_SENTENCE if single is None else single
    if want_single:
        # Titu: one sentence, nothing more. Cut at the FIRST sentence end so a
        # rambling model answer still arrives as one clean line.
        m = re.search(r"[.!?](\s|$)", t)
        if m:
            t = t[:m.start() + 1].strip()

    cap = int(limit or MAX_REPLY_CHARS)
    if len(t) <= cap:
        return t
    cut = t[:cap]
    for end_mark in (". ", "! ", "? "):
        i = cut.rfind(end_mark)
        if i > cap * 0.5:
            return cut[:i + 1].strip()
    i = cut.rfind(" ")
    return (cut[:i] if i > 0 else cut).strip()


# varied, human-sounding "you already asked this" lines (a repeat within 30 min)
# Only used for a genuine double-send within repeat_window_s (90s), e.g. an
# accidental double Enter. Anything later is answered properly again: people
# re-ask because they did not SEE the answer, and "I already replied" is a
# brush-off.
ALREADY_ANSWERED = [
    "Just above, {first} bhai :)",
    "Sent that one a second ago, {first} bhai.",
    "That is the one right above, {first} bhai.",
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


def _is_bangla(text):
    """True if the text contains Bangla script (U+0980 to U+09FF)."""
    return any("\u0980" <= c <= "\u09ff" for c in (text or ""))


def _banglish(text):
    """Bangla written in English letters, e.g. 'ki obostha', 'kemon acho'.
    Cheap token check: these are the words the team actually types."""
    low = (text or "").lower()
    hits = ("ki obostha", "kemon ach", "kemon acho", "ki khobor", "bhalo ach",
            "kotha bol", "banglay", "bangla ", "koro ", "korun", "amar ",
            "ami ", "apni ", "tumi ", "kichu ", "lagbe", "hoyeche", "hobe",
            "korchi", "dekhchi", "bolun", "bolo ")
    return any(h in low for h in hits)


def match_reply(text, rules):
    low = (text or "").strip().lower()
    if not low:
        return None
    # Banglish ('ki obostha') is ASCII, so a script check alone misses it
    # and answers a Bangla question in English. That was Titu's complaint.
    want_bangla = _is_bangla(text) or _banglish(text)
    for r in rules:
        for c in r["contains"]:
            # word-boundary so short triggers ("hi") don't match inside words
            if re.search(r"\b" + re.escape(c) + r"\b", low):
                rep = r["reply"]
                if not isinstance(rep, list):
                    return rep
                # Answer in the language they used. The pools carry both, and
                # picking at random meant a Bangla question got an English
                # answer, which reads as not listening.
                same = [x for x in rep if _is_bangla(x) == want_bangla]
                return random.choice(same or rep)
    return None


ANSWERED_FILE = _REPO / "data" / "answered.json"


def _load_answered():
    """Questions already answered, and whether we have primed before.

    Kept on disk because the loop only ever reacts to an UNREAD badge. Every
    restart used to start with an empty memory, and anything that clears a
    badge without us processing it -- opening the chat by hand, a one-off
    send, Teams syncing a read receipt from the phone -- made that message
    invisible forever. Persisting this is what makes the catch-up sweep safe
    to run: it can look at every dev chat without re-answering old messages.
    """
    try:
        d = json.loads(ANSWERED_FILE.read_text(encoding="utf-8"))
        seen = {str(k): float(v) for k, v in (d.get("answered") or {}).items()}
        return seen, bool(d.get("primed"))
    except Exception:
        return {}, False


def _save_answered(answered, primed=True):
    try:
        ANSWERED_FILE.parent.mkdir(parents=True, exist_ok=True)
        cut = time.time() - 7 * 24 * 3600
        keep = {k: v for k, v in answered.items() if v > cut}
        tmp = ANSWERED_FILE.with_name(ANSWERED_FILE.name + ".tmp")
        tmp.write_text(json.dumps({"primed": primed, "answered": keep}),
                       encoding="utf-8")
        os.replace(str(tmp), str(ANSWERED_FILE))
    except Exception as e:
        log(f"could not save answered state: {str(e)[:100]}")


def _addr(text, first):
    """Put the person's name into a canned reply.

    Titu, 2026-07-28: address people as "<Name> bhai", not a bare "bhai". The
    canned pools carry a {first} placeholder; when we do not know who we are
    talking to it collapses cleanly back to the un-named wording rather than
    leaving a gap or a stray double space.
    """
    if text is None:
        return None
    if not first:
        out = text.replace("{first} ", "").replace("{first}", "")
    else:
        out = text.replace("{first}", first)
    return re.sub(r"\s{2,}", " ", out).strip()


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
    if not w:
        return False
    # The roster resolver knows display names and aliases ("Md. Ahsan Habib
    # Rocky" is Rocky), so ask it first. The substring pass below stays as a
    # fallback for anyone matched by a raw dev_list value.
    if dev_names.is_known(who):
        return True
    if not allow:
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
        _hide_child_consoles()
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
# Settable from auto_reply_rules.json -> settings.sdk_pool_size.
# SET TO 0 ON THE ASSISTANT BOX. The warm claude_agent_sdk pool spawns the
# Claude CLI through its own async path, which we cannot make windowless -- it
# put one visible console on the desktop per pool slot (size 2 = 2 windows).
# Those windows steal focus from the Teams compose box mid-type, which is what
# caused "submit: compose still has text after all send methods".
# With 0, _warm_ask short-circuits and claude_answer uses the CLI path, which
# DOES honour CREATE_NO_WINDOW. Slower first token, but it can actually send.
POOL_SIZE = 2


def _ensure_pool(system, model):
    global _WARM_POOL
    if POOL_SIZE <= 0:
        return                      # pool disabled: CLI path only, no windows
    if not _WARM_POOL:
        _WARM_POOL = [WarmSDK(system, model) for _ in range(POOL_SIZE)]
        time.sleep(0.2)


def _hide_child_consoles():
    # The warm SDK pool spawns one claude.exe per client. claude_agent_sdk calls
    # anyio.open_process without creationflags, so on Windows every client pops a
    # blank console window - visible clutter on a box that must stay unlocked, and
    # a focus thief that can swallow keystrokes mid-reply into Teams. anyio DOES
    # accept creationflags, the SDK just never passes it, so wrap open_process and
    # default CREATE_NO_WINDOW in. Idempotent: re-wrapping is a no-op.
    if os.name != "nt":
        return
    try:
        import anyio
    except Exception:
        return
    if getattr(anyio.open_process, "_nn_no_window", False):
        return
    _orig = anyio.open_process
    CREATE_NO_WINDOW = 0x08000000

    async def _wrapped(*args, **kwargs):
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
        return await _orig(*args, **kwargs)

    _wrapped._nn_no_window = True
    anyio.open_process = _wrapped


def _warm_ask(system, user, model, timeout_s):
    """Ask via the first READY client in the pool (skips any that are
    reconnecting). Returns None if none ready -> caller falls back to the CLI."""
    if POOL_SIZE <= 0:
        return None                 # straight to the windowless CLI path
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
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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


def _claude_ask(system, user, model, timeout_s):
    """Warm pool if available, otherwise the CLI. run_report used to call
    _warm_ask directly, so turning the pool off (sdk_pool_size=0, to stop the
    console windows) made it fall back to dumping raw shell output at people."""
    out = _warm_ask(system, user, model, timeout_s)
    if out:
        return out
    prompt = (system + chr(10) + chr(10) + user) if system else user
    cmd = ["claude", "--print"] + (["--model", model] if model else [])
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                              cwd=str(_REPO), timeout=timeout_s, shell=True)
    except Exception as e:
        log(f"claude cli (ask) failed: {e}")
        return None
    return (proc.stdout or "").strip() or None


def run_report(report_cmd, model, timeout_s=25):
    """Run a READ-ONLY status command (e.g. ssh into .123 to gather pipeline
    health), then summarize its output with Claude into a short chat report."""
    try:
        proc = subprocess.run(report_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                              cwd=str(_REPO), shell=True, timeout=timeout_s)
        raw = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    except Exception as e:
        return f"I could not reach the pipeline to check right now ({e})."
    if not raw:
        return "I checked, but the pipeline returned no status data."
    ask = (
        "Below is raw technical output from our requirement pipeline. Turn it "
        "into what a NON-TECHNICAL colleague would want to hear.\n\n"
        "Rules:\n"
        "- TWO short sentences maximum, plain English.\n"
        "- Never mention container names, docker, uptimes, file paths or "
        "servers. Say 'the pipeline', 'recordings', 'the last email'.\n"
        "- Lead with whether it is working or not.\n"
        "- If something is broken, say what that means for them in practice.\n"
        "- No dashes, no emoji, no markdown, no lists.\n"
        "- Reply with the sentences only.\n\n"
        "Right tone: 'Everything is running normally and your call from this "
        "evening has been processed. The last requirements email went out on "
        "17 July.'\n\n"
        "RAW STATUS:\n" + raw[:4000])
    out = _claude_ask("", ask, model, 30)
    if out:
        return out
    # Never dump raw shell output at a person. If we cannot summarise it, say so.
    return ("I checked and the pipeline answered, but I could not put the "
            "result into words just now.")


def claude_answer(message, timeout_s, model="", sender="", history=None):
    """Answer AS Napco Nucleus. FAST path = warm SDK; fallback = CLI.

    `history` is THIS contact's own recent turns (see remember_turn). It is
    scoped by the caller, so the old "ignore everything earlier" instruction is
    no longer needed to keep one person's chat out of another's: there is
    nothing in the prompt but this one conversation.
    """
    try:
        persona = PERSONA_FILE.read_text(encoding="utf-8")
    except Exception:
        persona = ("You are Napco Nucleus, an AI meeting assistant. Reply "
                   "briefly and politely. Output only the reply text.")
    who = f"You are replying to {sender}. " if sender else ""
    convo = ""
    if history:
        lines = [("You: " if r == "me" else f"{sender or 'They'}: ") + t
                 for r, t in history]
        convo = ("Here is what the two of you have already said in THIS chat, "
                 "oldest first. It is only this one conversation, nobody "
                 "else's:\n" + "\n".join(lines) + "\n\n"
                 "Stay consistent with it. Never contradict something you "
                 "already told this person, and never agree to do something "
                 "you just said you cannot do.\n\n")
    user = (f"{who}{convo}Reply to this new Teams message.\n\n"
            f"Message: {message}\n\n"
            f"Reply with the reply text ONLY, 1-3 short sentences.")
    out = _warm_ask(persona, user, model, timeout_s)   # warm SDK, no cold-start
    if out:
        return out
    # fallback: Claude CLI (slower, but works if the API path fails)
    prompt = f"{persona}\n\n{user}\n"
    cmd = ["claude", "--print"] + (["--model", model] if model else [])
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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


def _item_contact(name):
    """The contact name out of a chat-list entry.

    A Teams chat-list item reads:
        "Chat <contact> <presence> Last message <preview> <time>"
    so the preview text is part of the item name. Matching against the whole
    string meant a message that merely MENTIONED somebody hijacked the click:
    "Chat Assad Zaman Available Last message Then say to Rocky bahi 2:42 PM"
    matched a search for Rocky and opened Zaman's chat instead (seen live
    2026-07-28). Only the contact part may be matched on.
    """
    nm = (name or "").strip()
    m = re.search(r"(?:unread message\s*)?chat\s+(.+?)\s+(?:available|away|busy|"
                  r"offline|do not disturb|be right back|presenting|"
                  r"last message)", nm, re.I)
    if m:
        return m.group(1).strip()
    # no presence/preview marker: take what follows "chat "
    m = re.search(r"(?:unread message\s*)?chat\s+(.+)$", nm, re.I)
    return m.group(1).strip() if m else nm


# Teams writes the person's presence into the chat-list entry, between their
# name and the message preview:
#   "Chat Assad Zaman Available Last message ..."
#   "Chat Md. Ahsan Habib Rocky In a call Last message ..."
# So we can tell who is busy without any API, any tenant, or any extra call.
_PRESENCE_WORDS = ("in a call", "in a meeting", "presenting", "do not disturb",
                   "be right back", "out of office", "available", "busy",
                   "away", "offline")

# The ones that mean "this person is not free right now" -- everything Teams
# shows with a RED icon.
#
# Plain "busy" belongs here. Teams reports a person on a call as "In a call"
# sometimes and simply "Busy" other times, and the red dot looks identical
# either way (Titu spotted the red icons, 2026-07-28). Leaving "busy" out meant
# somebody visibly on a call could still be treated as free and sent the
# ordinary nudge.
#
# The messages that go to a busy colleague are phrased conditionally ("if it is
# a client call, please add me"), so they read correctly whether the person is
# genuinely mid-call or has just set themselves Busy to concentrate.
_BUSY_PRESENCE = ("in a call", "in a meeting", "presenting", "do not disturb",
                  "busy")


def item_presence(name):
    """Presence out of a chat-list entry, lowercased, or '' if not shown."""
    low = (name or "").lower()
    m = re.search(r"(?:unread message\s*)?chat\s+.+?\s+("
                  + "|".join(re.escape(w) for w in _PRESENCE_WORDS)
                  + r")(?:\s+last message|\s*$)", low)
    return m.group(1) if m else ""


def is_busy_presence(name):
    """True when the chat-list entry says this person is on a call, in a
    meeting, presenting, or on do-not-disturb."""
    return item_presence(name) in _BUSY_PRESENCE


def _item_preview(name):
    """The 'Last message ...' part of a chat-list entry, or ''."""
    m = re.search(r"last message\s+(.*)$", (name or ""), re.I)
    if not m:
        return ""
    # trim the trailing timestamp Teams appends ("... 2:42 PM")
    return re.sub(r"\s+\d{1,2}:\d{2}\s*(?:am|pm)?\s*$", "", m.group(1),
                  flags=re.I).strip()


def _we_spoke_last(name):
    """True when the chat-list preview shows OUR message as the latest.

    Teams prefixes the preview with "You:" when the last message is ours.
    Reading this off the list is what lets the sweep decide whether a chat
    needs opening at all, instead of clicking through every conversation
    every couple of minutes -- which looks, from the desktop, like the
    assistant frantically flicking between people and typing nothing
    (Titu, 2026-07-28).
    """
    p = _item_preview(name)
    return p.lower().startswith("you:")


def find_chat_items(win, match):
    """Every left-rail chat item whose CONTACT NAME matches `match`.

    Returns a list, best first, because a single "first match" is exactly what
    let the wrong chat get opened. Callers should click and then VERIFY with
    chat_partner before typing anything.
    """
    m = (match or "").strip().lower()
    if not m:
        return []
    exact, partial = [], []

    def walk(c, d):
        if d > 25:
            return
        try:
            if c.ControlType in (auto.ControlType.ListItemControl,
                                 auto.ControlType.TreeItemControl):
                nm = (c.Name or "")
                low = nm.lower()
                if "chat " in low or "unread message" in low:
                    contact = _item_contact(nm).lower()
                    if contact == m:
                        exact.append(c)
                    elif m in contact:
                        partial.append(c)
            for ch in c.GetChildren():
                walk(ch, d + 1)
        except Exception:
            return
    try:
        for ch in win.GetChildren():
            walk(ch, 0)
    except Exception:
        pass
    return exact + partial


def find_chat_item(win, match):
    """First chat-list item whose CONTACT NAME matches. Kept for callers that
    only want one; prefer find_chat_items plus a chat_partner check."""
    items = find_chat_items(win, match)
    return items[0] if items else None


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


def _followup_body(action, commands, claude_model):
    """Run a promised check and return the message to send back.

    Reuses the existing status command rather than inventing a second way to
    ask the same question, so the follow-up reports exactly what "check the
    pipeline" would have reported.
    """
    if action != "status":
        return ""
    cmd = None
    for c in commands:
        if c.get("report_cmd"):
            cmd = c
            break
    if not cmd:
        return ""
    try:
        out = run_report(cmd["report_cmd"], claude_model)
    except Exception as e:
        log(f"followup report failed: {str(e)[:120]}")
        return ""
    out = (out or "").strip()
    if not out:
        return ""
    if len(out) < 400:
        out = "Checked it just now - " + out
    # Offer to act, rather than leaving them to work out the next step. The
    # caller records the offer so a bare "yes" is actually actionable.
    return out.rstrip() + "\n\nShall I run the pipeline and send the email now?"


def _parse_window(spec):
    """'09:00-21:00' -> (start_minute, end_minute), or None if unset/invalid."""
    try:
        a, b = str(spec).split("-", 1)
        ah, am = (int(x) for x in a.strip().split(":"))
        bh, bm = (int(x) for x in b.strip().split(":"))
        return ah * 60 + am, bh * 60 + bm
    except Exception:
        return None


def _within_window(spec) -> bool:
    """True when local time is inside `spec`. An empty or unparseable spec
    means 'always', so a bad edit to the rules file can never silently mute
    the assistant. Windows that wrap past midnight ('22:00-06:00') work."""
    w = _parse_window(spec)
    if w is None:
        return True
    start, end = w
    now = datetime.datetime.now()
    cur = now.hour * 60 + now.minute
    if start <= end:
        return start <= cur < end
    return cur >= start or cur < end


# ---------------------------------------------------------------------------
# Knock relay (Titu, 2026-07-28): "please knock Zaman bhai" makes the assistant
# open Zaman's chat and say "Hello Zaman bhai, Titu bhai asked me to knock you.
# How can I help you?", then come back and confirm to whoever asked.
#
# Only devs on the roster can ask, and only devs on the roster can be knocked.
# Relaying a stranger's message to the team is how an assistant gets used as a
# spam relay, and a knock we cannot attribute to a real person is not a knock
# worth passing on.
# ---------------------------------------------------------------------------
_KNOCK_RE = re.compile(
    r"(?:^|\b)(?:please\s+|plz\s+|pls\s+|can\s+you\s+|could\s+you\s+|"
    r"would\s+you\s+|kindly\s+)*"
    r"(?:knock|poke|nudge|ping)\s+(?:to\s+|up\s+)?"
    r"(?P<who>[A-Za-z][A-Za-z.\s]{0,30}?)"
    r"(?:\s+bhai)?(?:\s+for\s+me)?(?:\s+(?:please|plz|pls))?\s*[.!?]*$",
    re.I)

# Words that follow "knock" but are not a person.
_KNOCK_NOT_A_NAME = {"me", "you", "him", "her", "them", "us", "someone",
                     "somebody", "anyone", "everyone", "all", "the team",
                     "team", "it", "that", "this", "off", "out"}


# ---------------------------------------------------------------------------
# Relay (Titu, 2026-07-28): after a knock, "Zaman bhai asked to tell me
# something, he did not do anything. I was expecting a mediator." So the
# assistant carries messages both ways: "tell Titu bhai that the build is
# ready", and after a knock a bare "tell him ..." goes back to whoever knocked.
# ---------------------------------------------------------------------------
_RELAY_TO_NAMED = re.compile(
    r"(?:^|\b)(?:please\s+|plz\s+|pls\s+|kindly\s+|can\s+you\s+|could\s+you\s+|"
    r"would\s+you\s+)*"
    r"(?:tell|inform|let|ask|say\s+to)\s+"
    # The name is one or two words, and neither may be a connector: without
    # the lookaheads "tell Zaman the report is done" captured "Zaman the" and
    # ate the first word of the message.
    r"(?P<who>(?!bhai\b)[A-Za-z][A-Za-z.]{0,20}"
    r"(?:\s+(?!bhai\b|that\b|the\b|to\b|know\b|about\b)[A-Za-z][A-Za-z.]{0,20})?)"
    r"(?:\s+bhai)?\s+"
    r"(?:that\s+|to\s+know\s+that\s+|know\s+that\s+|know\s+|to\s+|:\s*)?"
    r"(?P<what>\S.*)$",
    re.I | re.S)

_RELAY_TO_PRONOUN = re.compile(
    r"(?:^|\b)(?:please\s+|plz\s+|pls\s+|kindly\s+|can\s+you\s+|could\s+you\s+|"
    r"would\s+you\s+)*"
    r"(?:tell|inform|let|say\s+to)\s+"
    r"(?P<who>him|her|them|he|she|back|him\s+back|her\s+back)"
    r"(?:\s+bhai)?\s+"
    r"(?:that\s+|know\s+that\s+|know\s+|to\s+|:\s*)?"
    r"(?P<what>\S.*)$",
    re.I | re.S)

_PRONOUNS = {"him", "her", "them", "he", "she", "back",
             "him back", "her back"}

# How long a "tell him ..." still knows who "him" is after we carried a
# message. Long enough for a real reply, short enough that tomorrow's stray
# "tell him ok" does not go to yesterday's requester.
RELAY_LINK_TTL_S = 4 * 3600.0


def parse_relay(msg):
    """('<who or pronoun>', '<message>') for a relay request, else ('', '').

    The pronoun form is checked first: "tell him the build is ready" must not
    be read as a message for somebody called "him".
    """
    t = (msg or "").strip()
    if not t:
        return "", ""
    for rx in (_RELAY_TO_PRONOUN, _RELAY_TO_NAMED):
        m = rx.search(t)
        if not m:
            continue
        who = (m.group("who") or "").strip(" .:\t")
        what = (m.group("what") or "").strip(" .:\t")
        if not who or not what or len(what) < 2:
            continue
        # "tell me", "tell us" is not a relay, it is a question to us
        if who.lower() in {"me", "us", "myself"}:
            return "", ""
        return who, what
    return "", ""


def parse_knock(msg):
    """The raw name in a knock request, or '' when this is not one."""
    m = _KNOCK_RE.search((msg or "").strip())
    if not m:
        return ""
    who = (m.group("who") or "").strip(" .!?\t")
    if not who or who.lower() in _KNOCK_NOT_A_NAME:
        return ""
    return who


# Compose-toolbar buttons that must NEVER be mistaken for Send. Clicking the
# Loop one is what created the Loop Paragraphs that blocked sending all evening.
_NOT_SEND = ("loop", "format", "emoji", "giphy", "sticker", "attach", "file",
             "praise", "schedule", "record", "video", "audio", "meet",
             "priority", "important", "poll", "approval", "more")


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
                # PROVEN 2026-07-27: the AutomationId alone is NOT specific
                # enough. Teams compose-toolbar buttons share that id prefix,
                # so 'Loop components (Ctrl+Alt+L)' matched and got CLICKED --
                # which is what kept inserting a Loop Paragraph into the box
                # and made every message unsendable. Match on the NAME, and
                # refuse anything that is obviously a different tool.
                if any(bad in nm for bad in _NOT_SEND):
                    for ch in c.GetChildren():
                        walk(ch, d + 1)
                    return
                if (nm == "send" or nm == "send message"
                        or nm.startswith("send (")      # 'Send (Ctrl+Enter)'
                        or nm.startswith("send message")):
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
                v = v.strip()
                # PROVEN 2026-07-27: after a SUCCESSFUL send the box reads back
                # as its placeholder, 'Type a message'. That is 14 chars, so the
                # old len(v) < 2 check called a successful send a failure, then
                # wiped the box and logged an error. The placeholder IS empty.
                return "" if v.lower() in PLACEHOLDER_TEXTS else v
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

    # Instrumentation: when a send fails we need to know WHICH thing failed.
    # A greyed/absent Send button means Teams is refusing the content; a present
    # and enabled button that changes nothing means our click never landed.
    try:
        _b = _find_send_button(win)
        if _b is None:
            log("submit: NO Send button found in the window")
        else:
            try:
                log("submit: Send button found, enabled=%s offscreen=%s name=%r"
                    % (_b.IsEnabled, _b.IsOffscreen, (_b.Name or "")[:40]))
            except Exception as _e:
                log("submit: Send button found but unreadable: %s" % _e)
    except Exception as _e:
        log("submit: send-button probe failed: %s" % _e)

    names = ("SendButton", "Ctrl+Enter", "Enter")
    for i, way in enumerate((_click_send,
                             lambda: _keys("{Ctrl}{Enter}"),
                             lambda: _keys("{Enter}"))):
        before = _compose_value(win)
        way()
        time.sleep(0.4)
        v = _compose_value(win)
        log("submit: %-10s before=%r after=%r"
            % (names[i], (before or "")[:35], (v or "")[:35]))
        if v is None:
            return True                 # cannot verify -> assume it went (Send btn)
        if not v or len(v) < 2:
            log("submit: sent via %s" % names[i])
            return True                 # box emptied -> definitely sent
    # Clear the box. A stuck draft is worse than a lost reply: it sits below
    # the partner's last message, so get_incoming reads it as "already
    # answered" and that chat goes permanently silent.
    try:
        bx = find_compose(win)
        if bx:
            bx.SetFocus()
            time.sleep(0.1)
            bx.SendKeys("{Ctrl}a{Delete}", waitTime=0.05)
            log("submit failed: cleared the stuck draft so the chat is not blocked")
    except Exception as e:
        log(f"submit failed AND could not clear the draft: {e}")
    log("submit: compose still has text after all send methods")
    return False


def send_reply(win, text, human=True, think=(0.2, 0.5), type_speed=0.02,
               single=None):
    # single=False lets a follow-up keep its second sentence, which carries the
    # "shall I send the email?" offer. With the global one-sentence rule that
    # offer was being cut off before it ever reached anyone.
    text = _tidy_reply(text, single=single)
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
        # With ASCII_ONLY the text is guaranteed typeable, so NEVER paste.
        # Pasting is what Teams converts into a Loop Paragraph, and a Loop
        # Paragraph cannot be sent at all -- the text just sits in the box and
        # every submit method fails.
        if ASCII_ONLY:
            non_ascii = False
        if human and not non_ascii:
            time.sleep(random.uniform(*think))             # brief think pause
            box.SendKeys(_sk_escape(text), interval=type_speed, waitTime=0.3)
            # interval is PER CHARACTER. waitTime is only the pause after,
            # which is what type_speed used to be wired to by mistake.
        else:
            if human:
                time.sleep(random.uniform(*think))
            auto.SetClipboardText(text)
            time.sleep(0.1)
            box.SendKeys("{Ctrl}{Shift}v", waitTime=0.05)   # PLAIN paste: never a Loop component
        time.sleep(0.35)
        return _submit(win, box)           # click Send button (reliable)
    except Exception as e:
        log(f"send failed: {e}; trying clipboard fallback")
        try:
            box.SetFocus()
            auto.SetClipboardText(text)
            box.SendKeys("{Ctrl}a{Delete}{Ctrl}{Shift}v", waitTime=0.05)   # PLAIN paste
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
    keep_alive_hours = str(settings.get("keep_alive_hours", "")).strip()
    # The hours NN is awake. Outside them it answers nobody (Titu, 2026-07-28:
    # "I asked you to go away from 11 PM to 11 AM. You did not and you
    # responded at 1:00 AM"). keep_alive_hours only ever governed the presence
    # nudge, so it never stopped a single reply -- this is the actual gate.
    active_hours = str(settings.get("active_hours", "")).strip()
    keep_alive_jitter = max(0.0, min(0.9, float(
        settings.get("keep_alive_jitter", 0.4))))
    presence_active_s = max(0.0, float(
        settings.get("presence_active_minutes", 10))) * 60.0
    wake_pause = max(0.0, float(settings.get("wake_pause_s", 1.0)))
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
        f"keep_alive={keep_alive}; cooldown={cooldown}s; "
        f"presence_active={presence_active_s/60:.0f}min; "
        f"wake_pause={wake_pause}s; "
        f"active_hours={active_hours or 'always'}")
    canned_texts = _canned_texts(rules)
    cmd_allow = load_allowlist()   # who may trigger commands (from dev_list)
    self_sent = deque(maxlen=15)   # our own recent replies (echo guard)
    # "contact|question" -> time answered. Loaded from disk so a restart does
    # not forget what it has already dealt with, which is what makes the
    # catch-up sweep safe to run.
    answered_at, answered_primed = _load_answered()
    last_reply_at = {}                   # contact -> time of last reply (per-contact gap)
    last_nudge = 0.0
    next_nudge_gap = float(keep_alive_s)
    # 0.0 = "no activity yet", so NN starts Away and only becomes Available
    # when someone actually messages or a call starts.
    last_activity = 0.0
    away_logged_at = 0.0                 # rate-limit the "staying silent" log
    repeat_noticed = set()               # questions we have already pointed at
    # how often to take a second look at the CURRENTLY OPEN window. Other
    # people's chats are reached only via an unread badge; nothing here walks
    # the chat list.
    sweep_gap_s = max(60.0, float(settings.get("sweep_seconds", 600)))
    # who we last carried a message TO, and on whose behalf:
    #   knocked/told person -> (their display name, requester name, when)
    # so their "tell him ..." goes back to the right person without naming.
    relay_link = {}
    rules_mtime = _mtime(RULES_FILE)

    # pre-warm the SDK client at startup so the FIRST reply is already fast
    globals()["POOL_SIZE"] = int(settings.get("sdk_pool_size", POOL_SIZE))
    globals()["MAX_REPLY_CHARS"] = int(
        settings.get("max_reply_chars", MAX_REPLY_CHARS))
    globals()["ASCII_ONLY"] = bool(settings.get("ascii_only", ASCII_ONLY))
    globals()["SINGLE_SENTENCE"] = bool(
        settings.get("single_sentence", SINGLE_SENTENCE))
    if use_claude and POOL_SIZE > 0:
        try:
            _persona = PERSONA_FILE.read_text(encoding="utf-8")
        except Exception:
            _persona = "You are Napco Nucleus."
        try:
            _ensure_pool(_persona, claude_model)
            log(f"pre-warming SDK pool (size {POOL_SIZE})")
        except Exception as e:
            log(f"pre-warm failed: {str(e)[:100]}")

    def _say_to(win, entry, body):
        """Open `entry`'s chat and say `body`. True when it was delivered.

        Prefers clicking their existing chat; falls back to Ctrl+N only if
        that fails, because the Ctrl+N flow can "succeed" onto the wrong
        contact (seen 2026-07-27).
        """
        want = entry["name"]
        opened = False
        # Try every candidate, not just the first, and VERIFY where we landed
        # before typing. A single unverified click sent a knock meant for
        # Rocky into Zaman's chat (2026-07-28).
        try:
            for item in find_chat_items(win, entry.get("chat") or want):
                if not open_chat(item):
                    continue
                time.sleep(1.6)
                here = (chat_partner(win) or "").strip()
                if here and dev_names.resolve(here) == want:
                    opened = True
                    break
                log(f"say_to: click landed on '{here}', not {want} - trying next")
        except Exception as e:
            log(f"say_to '{want}' chat-list click failed: {str(e)[:100]}")

        if not opened:
            # search box fallback, still verified before we type
            try:
                activate_window(win)
                time.sleep(0.5)
                auto.SendKeys("{Ctrl}n", waitTime=0.1)
                time.sleep(1.5)
                auto.SendKeys(_sk_escape(entry["search"]), waitTime=0.05)
                time.sleep(2.0)
                auto.SendKeys("{Enter}", waitTime=0.1)
                time.sleep(1.0)
                auto.SendKeys("{Enter}", waitTime=0.1)
                time.sleep(1.4)
                here = (chat_partner(win) or "").strip()
                opened = bool(here) and dev_names.resolve(here) == want
                log(f"say_to search fallback for {want} landed on "
                    f"'{here}': {'ok' if opened else 'wrong'}")
            except Exception as e:
                log(f"say_to search fallback failed: {str(e)[:100]}")

        if not opened:
            log(f"say_to ABORTED: could not reach {want}'s chat safely")
            return False

        ok = send_reply(win, body, human=human_typing, think=think,
                        type_speed=type_speed, single=False)
        if ok:
            self_sent.append(body.strip().lower())
        return ok

    def _back_to(win, display, expect_first):
        """Return to `display`'s chat. True ONLY when we can see we are there,
        so a confirmation never lands on the person we just went to."""
        try:
            for item in find_chat_items(win, display):
                if not open_chat(item):
                    continue
                time.sleep(1.4)
                here = (chat_partner(win) or "").strip()
                if here and dev_names.resolve(here) == expect_first:
                    return True
        except Exception as e:
            log(f"return to '{display}' failed: {str(e)[:100]}")
        return False

    def handle_open_chat(win, record_only=False):
        """Read the currently-open chat and reply once (if a new partner msg).

        record_only marks whatever is sitting there as already handled without
        answering it. That is how the first sweep after an upgrade avoids
        replying to the tail of seven conversations at once.
        """
        nonlocal answered_at, last_activity, away_logged_at
        msg, sender = get_incoming(win, own_names, self_sent)
        low = msg.strip().lower()
        if not low or low in canned_texts or low in self_sent or low in PLACEHOLDER_TEXTS:
            return
        # Away hours: stay completely silent, exactly like a colleague who is
        # asleep. No canned reply, no Claude answer, no command execution -- an
        # "I am away" auto-response at 1 AM is still answering at 1 AM. Nothing
        # is lost: the message sits in the chat and the chat push still ships
        # it to central, so any requirement in it is picked up regardless.
        if not _within_window(active_hours):
            if (time.time() - away_logged_at) > 1800:
                away_logged_at = time.time()
                log(f"AWAY ({active_hours}) - staying silent, message from "
                    f"'{dev_names.resolve(sender or chat_partner(win))}' left unanswered")
            return
        who = sender or chat_partner(win)
        # Never address anyone by the first token of their Teams display name:
        # "Md. Ahsan Habib Rocky" is Rocky, not "Md", and "Kamrul Hasan" is
        # Titu, not "Kamrul" (both reported live by Titu, 2026-07-28). The
        # roster in dev_list.json is the only source for what we call people.
        first = dev_names.resolve(who) if who else ""
        clow = who.strip().lower()
        norm = re.sub(r"\s+\S.*?today at .+$", "", low, flags=re.I).strip() or low
        key = f"{clow}|{norm}"                       # repeat key is PER CONTACT
        if record_only:
            answered_at[key] = time.time()
            return
        # per-contact gap: replying to one dev never blocks replying to another
        if (time.time() - last_reply_at.get(clow, 0)) < reply_gap:
            return
        already = (key in answered_at
                   and (time.time() - answered_at[key]) < repeat_window)
        if already and is_always(msg, rules):
            already = False
        # Presence: a real message just arrived. "Come back to the keyboard"
        # BEFORE answering — reset OS idle so Teams flips to Available, then
        # hold Available for presence_active_s after this message. Between
        # conversations nothing nudges, so Teams drifts to Away by itself.
        last_activity = time.time()
        nudge_input()
        if wake_pause > 0:
            time.sleep(wake_pause)
        activate_window(win)                         # mark 'Seen'
        if already:
            # One answer per question (Titu, 2026-07-28). The first repeat gets
            # a short pointer to the answer just above, because people re-ask
            # when they did not SEE it. A second repeat of the same question
            # gets nothing: saying "it is above" twice is itself answering
            # multiple times.
            if key in repeat_noticed:
                log(f"REPEAT again from '{first}' - already pointed at it, staying quiet")
                last_reply_at[clow] = time.time()
                return
            rep = _addr(random.choice(ALREADY_ANSWERED), first)
            send_reply(win, rep, human=human_typing, think=think, type_speed=type_speed)
            self_sent.append(rep.strip().lower())
            remember_turn(clow, "me", rep)
            repeat_noticed.add(key)
            last_reply_at[clow] = time.time()
            log(f"REPEAT notice to '{first}'")
            return
        # Did we just offer this person something and they answered? "yes" on
        # its own matches no trigger, so without this NN would have asked a
        # question it could not act on.
        offered = followups.pending_offer(who)
        if offered:
            if followups.is_yes(msg):
                followups.clear_offer(who)
                if is_allowed(who, cmd_allow):
                    run_cmd = next((c for c in commands
                                    if c.get("task") == "run-pipeline-email"), None)
                    if run_cmd:
                        ack = f"Right away {first} bhai, running it and sending the email now."
                        send_reply(win, ack, human=human_typing, think=think,
                                   type_speed=type_speed)
                        self_sent.append(ack.strip().lower())
                        dispatch_task(run_cmd, who)
                        log(f"CONFIRMED '{offered}' by '{who}' -> pipeline+email dispatched")
                        last_reply_at[clow] = time.time()
                        return
                else:
                    # not a dev: never let an outsider trigger a client email
                    rep = (f"Sorry {first} bhai, I can only run that for the dev "
                           f"team. Let Titu bhai know and he will trigger it.")
                    send_reply(win, rep, human=human_typing, think=think,
                               type_speed=type_speed)
                    self_sent.append(rep.strip().lower())
                    log(f"CONFIRM refused (not allowlisted): '{who}'")
                    last_reply_at[clow] = time.time()
                    return
            elif followups.is_ambiguous(msg):
                # "ok" / "achha" might mean yes, might just be an
                # acknowledgement. Sending a client email on a guess is not a
                # risk worth taking, so ask once, plainly. The offer stays open.
                rep = (f"Just to be sure {first} bhai, shall I send the "
                       f"requirements email now? Reply yes and I will.")
                send_reply(win, rep, human=human_typing, think=think,
                           type_speed=type_speed)
                self_sent.append(rep.strip().lower())
                log(f"CONFIRM ambiguous ('{msg[:20]}') from '{who}' - asked again")
                last_reply_at[clow] = time.time()
                return
            elif followups.is_no(msg):
                followups.clear_offer(who)
                rep = f"No problem {first} bhai, leaving it for now."
                send_reply(win, rep, human=human_typing, think=think,
                           type_speed=type_speed)
                self_sent.append(rep.strip().lower())
                log(f"CONFIRM declined by '{who}'")
                last_reply_at[clow] = time.time()
                return

        # A bare acknowledgement with nothing outstanding is the end of the
        # conversation, not a new question. A colleague reads "ok" and says
        # nothing back; answering it starts a politeness loop that never ends.
        # Only applies when there is NO pending offer -- if we asked something,
        # the ambiguous branch above has already handled it.
        if followups.is_ambiguous(msg):
            log(f"ACK '{msg[:20]}' from '{first}' - letting the chat rest")
            last_reply_at[clow] = time.time()
            return

        # A developer handing over a pile of chats. File it to central under
        # THEIR name so the requirements it yields are attributable to them,
        # then say so plainly -- a silent swallow leaves them wondering whether
        # it landed (Titu, 2026-07-28).
        if dev_names.is_known(who) and chat_intake.looks_like_chat_dump(msg):
            ok, detail = chat_intake.file_handover(first, msg)
            if ok:
                rep = (f"Got them {first} bhai, I have filed your chats to the "
                       f"central store. They will be counted when I identify "
                       f"requirements.")
                log(f"CHAT HANDOVER from '{first}' -> {detail}")
            else:
                rep = (f"{first} bhai, I have kept your chats but could not "
                       f"reach the central store just now. I will not lose "
                       f"them, and I am flagging it.")
                log(f"CHAT HANDOVER from '{first}' FAILED: {detail}")
            send_reply(win, rep, human=human_typing, think=think,
                       type_speed=type_speed)
            self_sent.append(rep.strip().lower())
            last_reply_at[clow] = time.time()
            return

        # "Tell Titu bhai that the build is ready" -> carry it to Titu and
        # confirm here. After a knock, a bare "tell him ..." goes back to
        # whoever asked for the knock.
        relay_who, relay_what = parse_relay(msg)
        if relay_what and is_allowed(who, cmd_allow):
            link = relay_link.get(first)
            if relay_who.lower() in _PRONOUNS:
                # a pronoun only resolves if we recently brought this person a
                # message; otherwise we ask rather than guess
                rnear = []
                rtarget = (dev_names.find(link[1])
                           if link and (time.time() - link[2]) < RELAY_LINK_TTL_S
                           else None)
            else:
                rtarget, rnear = dev_names.find_loose(relay_who)

            if rtarget is None:
                if relay_who.lower() in _PRONOUNS:
                    rep = (f"{first} bhai, who should I pass that to? Give me "
                           f"the name and I will take it to them.")
                elif len(rnear) > 1:
                    opts = " or ".join(d["name"] for d in rnear)
                    rep = (f"{first} bhai, did you mean {opts}?")
                else:
                    names = ", ".join(d["name"] for d in dev_names.roster())
                    rep = (f"Sorry {first} bhai, I do not have {relay_who} on "
                           f"my list. I can pass it to {names}.")
                send_reply(win, rep, human=human_typing, think=think,
                           type_speed=type_speed)
                self_sent.append(rep.strip().lower())
                log(f"RELAY unresolved target '{relay_who}' from '{first}'")
                last_reply_at[clow] = time.time()
                return
            if rtarget["name"] == first:
                rep = f"That is you {first} bhai, you can tell me directly."
                send_reply(win, rep, human=human_typing, think=think,
                           type_speed=type_speed)
                self_sent.append(rep.strip().lower())
                last_reply_at[clow] = time.time()
                return

            # Never carry an insult. The mediator is useful because it relays
            # faithfully, and that same faithfulness would deliver abuse with
            # the sender's name on it in our voice. Decline to the asker, and
            # do NOT warn the target: telling somebody "he tried to insult
            # you" does the harm the refusal just prevented.
            # check the payload AND the whole request: "tell Titu something
            # hard" hides the intent in the wording around the message, not
            # in the message itself
            bad = (civility.hurtful_reason(relay_what)
                   or civility.hurtful_reason(msg))
            if bad:
                rep = civility.refusal(first, rtarget["name"])
                send_reply(win, rep, human=human_typing, think=think,
                           type_speed=type_speed)
                self_sent.append(rep.strip().lower())
                log(f"RELAY REFUSED ({bad}): '{first}' -> "
                    f"'{rtarget['name']}'")
                last_reply_at[clow] = time.time()
                return

            body = (f"{rtarget['name']} bhai, {first} bhai asked me to tell "
                    f"you: {relay_what}")
            log(f"RELAY '{first}' -> '{rtarget['name']}': {relay_what[:60]}")
            last_activity = time.time()
            nudge_input()
            ok = _say_to(win, rtarget, body)
            if ok:
                # let the receiver answer back through us as well
                relay_link[rtarget["name"]] = (who, first, time.time())
            back_ok = _back_to(win, who, first)
            if back_ok:
                rep = (f"Passed it on to {rtarget['name']} bhai."
                       if ok else
                       f"Sorry {first} bhai, I could not reach "
                       f"{rtarget['name']} bhai just now.")
                send_reply(win, rep, human=human_typing, think=think,
                           type_speed=type_speed)
                self_sent.append(rep.strip().lower())
            else:
                log(f"RELAY delivered but could not get back to '{first}'")
            last_reply_at[clow] = time.time()
            return

        # "Please knock Zaman bhai" -> go and knock him, then report back here.
        knock_raw = parse_knock(msg)
        if knock_raw:
            # Partial and misspelled names are fine: "knock Zmn" is Zaman.
            target, near = dev_names.find_loose(knock_raw)
            if not is_allowed(who, cmd_allow):
                rep = (f"Sorry {first} bhai, I can only pass a knock along for "
                       f"someone on the dev team.")
                send_reply(win, rep, human=human_typing, think=think,
                           type_speed=type_speed)
                self_sent.append(rep.strip().lower())
                log(f"KNOCK refused (not allowlisted): '{who}'")
                last_reply_at[clow] = time.time()
                return
            if target is None:
                if len(near) > 1:
                    # two devs equally close: ask rather than knock the wrong
                    # one, since a knock is visible to that person
                    opts = " or ".join(d["name"] for d in near)
                    rep = (f"{first} bhai, did you mean {opts}? Tell me which "
                           f"one and I will knock them.")
                else:
                    names = ", ".join(d["name"] for d in dev_names.roster())
                    rep = (f"Sorry {first} bhai, I do not have {knock_raw} on my "
                           f"list. I can knock {names}.")
                send_reply(win, rep, human=human_typing, think=think,
                           type_speed=type_speed)
                self_sent.append(rep.strip().lower())
                log(f"KNOCK unknown target '{knock_raw}' asked by '{first}'")
                last_reply_at[clow] = time.time()
                return
            if target["name"] == first:
                rep = f"That is you {first} bhai, I am right here."
                send_reply(win, rep, human=human_typing, think=think,
                           type_speed=type_speed)
                self_sent.append(rep.strip().lower())
                last_reply_at[clow] = time.time()
                return

            body = (f"Hello {target['name']} bhai, {first} bhai asked me to "
                    f"knock you. How can I help you? If you want to send "
                    f"anything back to {first} bhai, tell me and I will pass "
                    f"it on.")
            log(f"KNOCK '{target['name']}' requested by '{first}'")
            last_activity = time.time()
            nudge_input()
            ok = _say_to(win, target, body)
            if ok:
                log(f"KNOCK delivered to '{target['name']}'")
                # Remember who this knock came from, so "tell him the build is
                # ready" from the knocked person finds its way back without
                # them having to name anybody (Titu, 2026-07-28: "I was
                # expecting a mediator").
                relay_link[target["name"]] = (who, first, time.time())

            # Come back to whoever asked and confirm. Only speak once we can
            # SEE we are back -- posting "done" into the chat we just knocked
            # would tell the wrong person.
            back_ok = _back_to(win, who, first)
            if back_ok:
                rep = (f"Done {first} bhai, I have knocked {target['name']} bhai."
                       if ok else
                       f"Sorry {first} bhai, I could not reach "
                       f"{target['name']} bhai just now.")
                send_reply(win, rep, human=human_typing, think=think,
                           type_speed=type_speed)
                self_sent.append(rep.strip().lower())
            else:
                log(f"KNOCK done but could not get back to '{first}' to confirm")
            last_reply_at[clow] = time.time()
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
            remember_turn(clow, "them", msg)
            reply = _addr(match_reply(msg, rules), first)
            src = "canned"
            if reply is None and use_claude:
                reply = claude_answer(msg, claude_timeout, claude_model,
                                      sender=first,
                                      history=recent_turns(clow)[:-1])
                src = "claude"
            # If the persona committed to checking something, strip the marker
            # (the colleague must never see it) and record the promise so the
            # loop actually honours it. Saying "let me check" and then going
            # silent is the failure this exists to prevent.
            promised = None
            if reply:
                reply, promised = followups.extract(reply)
            if reply and send_reply(win, reply, human=human_typing,
                                    think=think, type_speed=type_speed):
                self_sent.append(reply.strip().lower())
                remember_turn(clow, "me", reply)
                log(f"REPLIED[{src}] to '{msg[:40]}' -> '{reply[:60]}'")
                if promised and followups.enqueue(who, promised):
                    log(f"FOLLOWUP queued: {promised} for '{who}'")
        answered_at[key] = time.time()
        if len(answered_at) > 400:
            cut = time.time() - repeat_window
            answered_at = {k: v for k, v in answered_at.items() if v > cut}
            # keep the "already pointed at it" set from growing forever, and
            # let a question asked again much later be answered properly
            repeat_noticed.intersection_update(answered_at)
        last_reply_at[clow] = time.time()
        # NOTE: do NOT mark_reached here. Chatting is not the same as adding NN
        # to a meeting. The reminder must keep nudging until the dev actually
        # adds the assistant (tracked manually via dev_list "added", or by real
        # call-capture attribution later). Auto-marking on chat wrongly silenced
        # reminders after a single "hi".

    # No roster-wide sweep (Titu, 2026-07-28: "Stop sweep. You will sweep only
    # on your current open window... For other, you will understand if there
    # any unread, then switch there and read"). Nothing walks other people's
    # chats any more. Reaching another conversation now requires an unread
    # badge, which is the loop's step 1, or somebody messaging the open chat.
    last_sweep = time.time()
    last_saved = time.time()
    if not answered_primed:
        _save_answered(answered_at, primed=True)

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
                keep_alive_hours = str(
                    settings.get("keep_alive_hours", "")).strip()
                active_hours = str(settings.get("active_hours", "")).strip()
                keep_alive_jitter = max(0.0, min(0.9, float(
                    settings.get("keep_alive_jitter", 0.4))))
                presence_active_s = max(0.0, float(
                    settings.get("presence_active_minutes", 10))) * 60.0
                wake_pause = max(0.0, float(
                    settings.get("wake_pause_s", 1.0)))
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

            # Honour any promise made earlier. This is the ONLY place NN speaks
            # without being spoken to first, and it exists because a colleague
            # who says "let me check" and then goes quiet is worse than one who
            # says nothing. Runs the real check, then opens the chat and reports.
            try:
                item = followups.due()
                if item is not None and win is not None:
                    who_f = item["contact"]
                    log(f"FOLLOWUP running '{item['action']}' for '{who_f}'")
                    body = _followup_body(item["action"], commands, claude_model)
                    if body:
                        last_activity = time.time()   # we are about to speak
                        nudge_input()
                        # PREFER the chat that is already open. notify.send
                        # presses Ctrl+N and takes the first search suggestion,
                        # which "succeeds" even when it lands on the wrong
                        # contact or an empty draft chat -- observed 2026-07-27,
                        # the status message was delivered and Titu never saw
                        # it. If we are already looking at this person, just
                        # reply here.
                        ok = False
                        try:
                            here = (chat_partner(win) or "").strip().lower()
                            want = (who_f or "").strip().lower()
                            if here and want and (here == want
                                                  or here.startswith(want[:12])
                                                  or want.startswith(here[:12])):
                                ok = send_reply(win, body, human=human_typing,
                                                think=think, type_speed=type_speed,
                                                single=False)   # keep the offer
                                log(f"FOLLOWUP delivered in the open chat with '{here}'")
                        except Exception as e:
                            log(f"followup in-place send failed: {str(e)[:100]}")
                        if not ok:
                            from teams import notify   # lazy: circular import
                            ok = notify.send(who_f, body)
                            log(f"FOLLOWUP fell back to opening a new chat: {ok}")
                        if ok:
                            followups.done(item)
                            # we just asked "shall I send the email?" - remember
                            # it, so their "yes" is actually actionable
                            followups.offer(who_f, "run-pipeline-email")
                            log(f"FOLLOWUP delivered to '{who_f}' (offer recorded)")
                        else:
                            followups.bump(item)
                            log(f"FOLLOWUP send failed for '{who_f}'")
                    else:
                        followups.bump(item)
                        log(f"FOLLOWUP produced no body for '{who_f}'")
            except Exception as e:
                log(f"followup loop error: {str(e)[:120]}")

            # In a call = present. record_call drops .recording_active for the
            # duration, so a meeting holds Available exactly as a live chat
            # does, and it keeps holding for presence_active_s afterwards.
            try:
                if RECORDING_MARKER.exists():
                    last_activity = time.time()
            except Exception:
                pass

            # Presence follows real conversation, not the clock. We only hold
            # Available for presence_active_s after the last message; outside
            # that we stop nudging entirely and Teams goes Away on its own.
            # Jittered, because a synthetic input event landing on an exact
            # 50s grid is itself a bot tell. keep_alive_hours stays empty
            # (= always) since .72 is only powered on 11:00-22:00 anyway.
            if (keep_alive and _within_window(keep_alive_hours)
                    and (time.time() - last_activity) < presence_active_s
                    and (time.time() - last_nudge) > next_nudge_gap):
                nudge_input()
                last_nudge = time.time()
                next_nudge_gap = keep_alive_s * (
                    1.0 + random.uniform(-keep_alive_jitter, keep_alive_jitter))

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
                    # 2) nothing unread -> handle whatever chat is currently
                    #    open. This runs every poll on purpose: a chat that is
                    #    open and focused never RAISES an unread badge, Teams
                    #    marks those messages read on arrival, so this is the
                    #    only thing that answers the person we are talking to.
                    handle_open_chat(win)
                    # 3) and a slow re-look at that same window, in case
                    #    something landed while we were busy elsewhere
                    if (time.time() - last_sweep) > sweep_gap_s:
                        last_sweep = time.time()
                        handle_open_chat(win)
            if (time.time() - last_saved) > 20:
                _save_answered(answered_at, primed=True)
                last_saved = time.time()
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
