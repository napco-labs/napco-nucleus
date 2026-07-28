"""Canonical developer names.

A Teams display name is not what we call somebody. "Md. Ahsan Habib Rocky" is
Rocky, "Kamrul Hasan" is Titu, "Sheikh Amin" is Amin, "Assad Zaman" is Zaman.

The assistant used to take the display name and split on whitespace, keeping
the first token (auto_reply.py, announce_rollup.py). That produced "Md",
"Kamrul" and "Sheikh" in real chats (reported by Titu, 2026-07-28) and reads
as if the assistant does not know the team it works with.

So every name the assistant says out loud goes through resolve(), and the
answer comes from dev_list.json, never from the Teams window title. The seven
names Titu uses are Titu, Ferdows, Zaman, Atik, Rocky, Isruk and Amin.

The roster is re-read when dev_list.json changes, matching how
auto_reply_rules.json hot-reloads, so fixing a name never needs a restart.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

DEV_LIST_FILE = Path(__file__).parent / "dev_list.json"

# Titles and family prefixes that are never how a person is addressed here.
# "Md"/"Mohammad" in particular open a large share of Bangladeshi legal names,
# so a first-token fallback without this is wrong more often than it is right.
_HONORIFICS = {
    "md", "mohammad", "mohammed", "mohd", "muhammad", "mohamad",
    "sheikh", "shaikh", "syed", "sayed", "abu", "al",
    "mr", "mrs", "ms", "miss", "dr", "engr", "eng", "prof",
}

_lock = threading.Lock()
_cache: list[dict] = []
_cache_mtime = -1.0


def _norm(s) -> str:
    """Lowercase, strip punctuation, collapse whitespace. 'Md. Ahsan' -> 'md ahsan'."""
    s = str(s or "").lower()
    s = re.sub(r"[^a-z0-9ঀ-৿\s]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s) -> list[str]:
    return [t for t in _norm(s).split() if t]


def _load() -> list[dict]:
    """Roster from dev_list.json, re-read whenever the file changes."""
    global _cache, _cache_mtime
    try:
        mtime = DEV_LIST_FILE.stat().st_mtime
    except Exception:
        return _cache
    with _lock:
        if mtime == _cache_mtime and _cache:
            return _cache
        try:
            data = json.loads(DEV_LIST_FILE.read_text(encoding="utf-8"))
        except Exception:
            return _cache
        devs = []
        for d in data.get("devs", []):
            if not isinstance(d, dict):
                continue
            name = (d.get("name") or "").strip()
            if not name:
                continue
            search = (d.get("search") or "").strip()
            entry = {
                "name": name,
                "search": search,
                "chat": (d.get("chat") or "").strip(),
                "aliases": [a for a in (d.get("aliases") or []) if a],
                # local-part of the login, e.g. rockycs33@hotmail.com -> rockycs33
                "local": search.split("@", 1)[0].strip().lower() if search else "",
            }
            devs.append(entry)
        _cache, _cache_mtime = devs, mtime
        return _cache


def roster() -> list[dict]:
    """All known devs as {name, search, chat, aliases}."""
    return list(_load())


def find(raw) -> dict | None:
    """The dev entry `raw` refers to, or None. `raw` may be a Teams display
    name, a chat-list label, a login/email, or a bare first name."""
    n = _norm(raw)
    if not n:
        return None
    toks = set(n.split())
    devs = _load()

    # 1. the canonical name itself ("rocky", "titu")
    for d in devs:
        if _norm(d["name"]) == n:
            return d
    # 2. an explicit alias ("md ahsan habib rocky")
    for d in devs:
        if any(_norm(a) == n for a in d["aliases"]):
            return d
    # 3. login / email, whole or local-part
    for d in devs:
        if d["local"] and (d["local"] == n or d["local"] in toks):
            return d
        if d["search"] and _norm(d["search"]) == n:
            return d
    # 4. the chat-list label, either direction ("kamrul" vs "kamrul hasan").
    #    The "query inside label" direction needs a real query: a 1-2 letter
    #    fragment sits inside almost every label, so "a" would match Zaman.
    for d in devs:
        c = _norm(d["chat"])
        if not c:
            continue
        if c in n or (len(n) >= 3 and n in c):
            return d
    # 5. canonical name appearing anywhere in the display name.
    #    This is what rescues "Md. Ahsan Habib Rocky" -> Rocky without
    #    needing every display name written down in advance.
    for d in devs:
        if _norm(d["name"]) in toks:
            return d
    # 6. any alias token overlapping, e.g. "Mostafa Jannatul Ferdows"
    for d in devs:
        for a in d["aliases"]:
            at = set(_tokens(a))
            if at and at & toks and len(at & toks) >= min(2, len(at)):
                return d
    return None


def _skeleton(s) -> str:
    """Consonants only. 'zaman' -> 'zmn', which is how people abbreviate."""
    return re.sub(r"[aeiou]", "", _norm(s).replace(" ", ""))


def _is_subseq(q: str, s: str) -> bool:
    """True when every letter of q appears in s, in order. 'zma' fits 'zaman'."""
    it = iter(s)
    return all(ch in it for ch in q)


def _lev(a: str, b: str) -> int:
    """Edit distance, small strings only."""
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def find_loose(raw):
    """Best roster match for a shortened or misspelled name.

    Titu, 2026-07-28: "You will understand the name if I ask you an incomplete
    name. For example: knock Zmn/Zama (Zaman) you will knock Zaman bhai."

    Returns (entry, candidates). `entry` is None when nothing is close enough
    OR when two devs are equally close -- guessing between Amin and Atik on
    "A" and knocking the wrong person is worse than asking which one.
    """
    exact = find(raw)
    if exact is not None:
        return exact, [exact]
    n = _norm(raw).replace(" ", "")
    if len(n) < 2:
        return None, []
    nskel = _skeleton(n)

    scored = []
    for d in _load():
        # Fuzzy scoring runs against SHORT keys only. A full display name like
        # "mostafajannatulferdows" contains almost any three letters as a
        # subsequence, which made "Sal" (Salman, not on the roster) match
        # Ferdows. Long aliases still work through find()'s exact rules above.
        keys = [_norm(d["name"]).replace(" ", "")]
        if d["chat"]:
            keys.append(_norm(d["chat"]).replace(" ", ""))
        keys += [k for k in (_norm(a).replace(" ", "") for a in d["aliases"])
                 if len(k) <= 14]
        best = 0
        for k in [k for k in keys if k]:
            if k.startswith(n) or n.startswith(k):
                best = max(best, 95)
            if nskel and nskel == _skeleton(k):
                best = max(best, 90)
            if len(n) >= 3 and n in k:
                best = max(best, 85)
            # One typo is a typo. Two edits on a short name is a different
            # person: "Salman" is two edits from "Zaman", and Salman is a real
            # colleague who is not on this roster. Only allow a second edit
            # once the name is long enough for it to still be unambiguous.
            dist = _lev(n, k)
            if len(k) > 3 and dist <= (2 if len(n) >= 8 else 1):
                best = max(best, 82 - dist * 10)
            # a subsequence only means anything against a comparably short
            # key, otherwise every scattered letter counts as a hit
            if len(n) >= 3 and len(k) <= len(n) + 4 and _is_subseq(n, k):
                best = max(best, 70)
        if best:
            scored.append((best, d))

    if not scored:
        return None, []
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    top = scored[0][0]
    winners = [d for s, d in scored if s == top]
    if len(winners) == 1:
        return winners[0], [d for _, d in scored]
    return None, winners


def resolve(raw, default: str = "") -> str:
    """How to address whoever `raw` names.

    Returns the canonical short name for known devs (Titu, Ferdows, Zaman,
    Atik, Rocky, Isruk, Amin). For anybody else, falls back to their first
    real name token with honorifics dropped, so an outsider still gets
    something human rather than "Md".
    """
    d = find(raw)
    if d:
        return d["name"]
    for t in _tokens(raw):
        if t not in _HONORIFICS and len(t) > 1:
            return t[:1].upper() + t[1:]
    return default


def is_known(raw) -> bool:
    """True when `raw` is one of the seven devs on the roster."""
    return find(raw) is not None
