"""Make NN keep its word.

The problem this solves: `auto_reply` is purely reactive. It answers a message
and stops. So when the persona says "let me check and get back to you" -- which
is the natural thing a colleague says -- nothing ever happens. On 2026-07-27
Assad asked why a call he added NN to produced nothing; NN replied "let me check
the latest status" and then went silent, because no code path existed to do it.
A promise NN cannot keep is worse than no promise, so the fix is to keep it.

How it works: the persona ends a reply with a marker on its own line when it has
committed to checking something, e.g.

    [[FOLLOWUP: status]]

`extract` strips that marker (the human never sees it) and `enqueue` records the
commitment. The auto_reply loop later drains the queue, actually runs the check,
and sends the result as a NEW message via teams.notify -- NN speaking first,
which it otherwise never does.

Deliberately conservative:
  * one action per contact at a time (no pile-ups if someone asks twice)
  * a settle delay, so the follow-up reads as a real check rather than a reflex
  * attempts are capped, so a broken action can never spam a colleague
  * 1:1 only, inherited from teams.notify -- never a group or meeting chat
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

_REPO = Path(__file__).parent.parent
QUEUE_FILE = _REPO / "data" / "followups.json"

# The persona emits this. Kept deliberately ugly so it can never appear by
# accident in ordinary conversation.
_MARKER_RE = re.compile(r"\[\[\s*FOLLOWUP\s*:\s*([a-z_]+)\s*\]\]", re.I)

# Known actions. Anything else is dropped rather than guessed at.
ACTIONS = ("status",)

SETTLE_SECONDS = 25.0     # wait before acting, so it looks like a real check
MAX_ATTEMPTS = 3


def extract(text: str):
    """Split a generated reply into (clean_text, action|None).

    The marker is removed from the outgoing message. If the persona emitted an
    action we do not recognise, the marker is still stripped and the action
    dropped -- a stray token must never reach a colleague.
    """
    if not text:
        return text, None
    m = _MARKER_RE.search(text)
    if not m:
        return text, None
    action = m.group(1).lower()
    clean = _MARKER_RE.sub("", text).strip()
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    if action not in ACTIONS:
        return clean, None
    return clean, action


def _load() -> list:
    try:
        with open(QUEUE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items: list) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUEUE_FILE.with_suffix(".tmp")
    # utf-8 WITHOUT bom -- json.load rejects a BOM
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(str(tmp), str(QUEUE_FILE))


def enqueue(contact: str, action: str) -> bool:
    """Record a commitment. Returns False if this contact already has one."""
    contact = (contact or "").strip()
    if not contact or action not in ACTIONS:
        return False
    items = _load()
    for it in items:
        if (it.get("contact", "").lower() == contact.lower()
                and it.get("action") == action):
            return False          # already promised, do not double up
    items.append({
        "contact": contact,
        "action": action,
        "created_at": time.time(),
        "attempts": 0,
    })
    _save(items)
    return True


def due(now: float | None = None):
    """The one item ready to run, or None. One at a time, oldest first."""
    now = time.time() if now is None else now
    items = _load()
    ready = [i for i in items
             if (now - i.get("created_at", 0)) >= SETTLE_SECONDS
             and i.get("attempts", 0) < MAX_ATTEMPTS]
    if not ready:
        return None
    ready.sort(key=lambda i: i.get("created_at", 0))
    return ready[0]


def bump(item: dict) -> None:
    """Record a failed attempt; drops the item once MAX_ATTEMPTS is hit."""
    items = _load()
    out = []
    for it in items:
        same = (it.get("contact") == item.get("contact")
                and it.get("action") == item.get("action"))
        if same:
            it["attempts"] = it.get("attempts", 0) + 1
            if it["attempts"] >= MAX_ATTEMPTS:
                continue          # give up rather than nag
        out.append(it)
    _save(out)


def done(item: dict) -> None:
    items = [it for it in _load()
             if not (it.get("contact") == item.get("contact")
                     and it.get("action") == item.get("action"))]
    _save(items)


def pending_count() -> int:
    return len(_load())


# ---------------------------------------------------------------------------
# Pending confirmations
#
# After reporting status NN offers to run the pipeline and send the email. The
# colleague answers "yes" -- which matches no command trigger on its own, so
# without this NN would have asked a question it could not act on. We remember
# what was offered, to whom, and for how long.
#
# Deliberately narrow: only ONE offer per contact, it expires, and the caller
# must still check the dev allowlist before acting. A stranger saying "yes"
# must never be able to mail a client.
# ---------------------------------------------------------------------------

CONFIRM_FILE = _REPO / "data" / "pending_confirms.json"
CONFIRM_TTL = 1800.0        # 30 minutes, then the offer goes stale

# Deliberately STRICT. This confirms sending a requirements email to the team
# AND to an external client contact, which cannot be taken back. Bare "ok",
# "okay", "sure" and "go" are NOT here on purpose: people type those to
# acknowledge, not to authorise. An ambiguous word must never mail a client.
_YES = (
    "yes", "yes please", "yes send", "yeah", "yep",
    "please do", "please send", "do it", "send it", "send the email",
    "go ahead", "ok send", "okay send",
    "korun", "koro", "kore din", "pathan", "pathao", "pathiye din",
    "হ্যাঁ", "হ্যা", "করুন", "করো", "পাঠান", "পাঠাও", "পাঠিয়ে দিন",
)

# Said in reply to an offer, these are too vague to act on. We ask once more
# rather than guessing, because guessing wrong sends mail to a client.
_AMBIGUOUS = (
    "ok", "okay", "k", "sure", "go", "fine", "alright", "right", "hmm",
    "achha", "acha", "thik", "thik ache", "আচ্ছা", "ঠিক আছে",
)
_NO = (
    "no", "nope", "not now", "later", "dont", "don't", "no need", "cancel",
    "na", "না", "লাগবে না", "পরে", "এখন না",
)


def _norm(text: str) -> str:
    return re.sub(r"[^\wঀ-৿\s']", " ", (text or "").lower()).strip()


def is_yes(text: str) -> bool:
    t = _norm(text)
    if not t or len(t.split()) > 5:      # a sentence is not a bare confirmation
        return False
    return any(t == y or t.startswith(y + " ") or t.endswith(" " + y)
               for y in _YES)


def is_ambiguous(text: str) -> bool:
    """True for a reply that MIGHT mean yes but is not clear enough to act on."""
    t = _norm(text)
    if not t or len(t.split()) > 3:
        return False
    return any(t == a for a in _AMBIGUOUS)


def is_no(text: str) -> bool:
    t = _norm(text)
    if not t or len(t.split()) > 5:
        return False
    return any(t == n or t.startswith(n + " ") or t.endswith(" " + n)
               for n in _NO)


def _load_confirms() -> dict:
    try:
        with open(CONFIRM_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_confirms(d: dict) -> None:
    CONFIRM_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIRM_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    os.replace(str(tmp), str(CONFIRM_FILE))


def offer(contact: str, action: str) -> None:
    """Record that we asked `contact` whether to do `action`."""
    contact = (contact or "").strip().lower()
    if not contact:
        return
    d = _load_confirms()
    d[contact] = {"action": action, "asked_at": time.time()}
    _save_confirms(d)


def pending_offer(contact: str):
    """The live offer for this contact, or None if absent/expired."""
    contact = (contact or "").strip().lower()
    d = _load_confirms()
    it = d.get(contact)
    if not it:
        return None
    if (time.time() - it.get("asked_at", 0)) > CONFIRM_TTL:
        d.pop(contact, None)
        _save_confirms(d)
        return None
    return it.get("action")


def clear_offer(contact: str) -> None:
    contact = (contact or "").strip().lower()
    d = _load_confirms()
    if d.pop(contact, None) is not None:
        _save_confirms(d)
