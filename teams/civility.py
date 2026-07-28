"""Refuse to carry a message meant to hurt somebody.

Titu, 2026-07-28: Zaman asked the assistant to say something hard to Titu. The
answer he wants back is "Titu bhai is my creator, I cannot say anything that
can hurt him."

The mediator is the reason this matters. Carrying messages between colleagues
is useful precisely because the assistant does it faithfully, and that same
faithfulness would happily deliver an insult with the sender's name attached
and the assistant's voice around it. A messenger that will say anything is a
weapon pointed at whoever it is aimed at, and the person on the receiving end
has no way to tell that the assistant merely relayed it.

So: it will not say, carry, or soften-then-carry anything abusive about a
colleague. It declines to the person who asked, plainly and without a lecture,
and it does not report the attempt to the target either. Telling Titu "Zaman
tried to insult you" would do the harm the refusal just prevented.

Deliberately narrow. This is not a general profanity filter, and it must not
trip on ordinary frustration ("this build is broken", "the report is wrong",
"I am fed up with this bug"). Complaining about work is normal and must still
get through. It looks for abuse aimed at a PERSON, and for requests to be
unkind on someone's behalf.
"""
from __future__ import annotations

import re

# Abuse aimed at a person. Kept short and blunt on purpose: a long list drifts
# into policing ordinary speech. Bangla/Banglish terms included because that is
# what actually gets typed here.
_ABUSE = {
    "idiot", "stupid", "fool", "foolish", "dumb", "moron", "useless",
    "incompetent", "worthless", "loser", "shut up", "nonsense fellow",
    "bastard", "damn you", "get lost", "rubbish fellow",
    "boka", "bokachoda", "gadha", "beyadob", "harami", "shala", "shalar",
    "faltu", "oshikkhito", "murkho", "chagol",
    "গাধা", "বোকা", "বেয়াদব", "ফালতু", "মূর্খ", "ছাগল", "হারামি",
}

# "say something bad to X", "insult him", "give him a scolding"
_INTENT = re.compile(
    r"\b("
    r"say\s+something\s+(?:bad|hard|rude|harsh|nasty|mean)|"
    r"tell\s+(?:him|her|them|\w+)\s+something\s+(?:bad|hard|rude|harsh|nasty)|"
    r"insult|abuse\s+(?:him|her|them)|scold|humiliate|embarrass|"
    r"make\s+fun\s+of|mock\s+(?:him|her|them)|"
    r"be\s+rude\s+to|talk\s+rudely|say\s+bad\s+about|"
    r"boka\s*(?:dao|dibe|de)|galigalaj|gali\s*(?:dao|dibe|de)"
    r")\b",
    re.I)

# Bangla script has no usable \b in Python's re (the letters either side of a
# match are all word characters), so "গালি দাও" slipped past the pattern above.
# These are checked as plain substrings instead.
_INTENT_BN = ("অপমান", "গালি", "বকা দ", "বাজে কথা", "খারাপ কথা",
              "কটু কথা", "অসম্মান")

# Frustration about WORK, not about a person. If one of these is what matched,
# it is not abuse and must still be delivered.
_WORK_GRIPE = re.compile(
    r"\b(build|report|code|bug|test|server|call|email|pipeline|deploy|"
    r"release|script|feature|module|data|file)\b", re.I)


def hurtful_reason(text: str) -> str:
    """Why `text` must not be carried, or '' when it is fine to deliver."""
    t = (text or "").strip()
    if not t:
        return ""
    low = t.lower()

    if _INTENT.search(low) or any(p in t for p in _INTENT_BN):
        return "asked to be unkind to someone"

    for word in _ABUSE:
        # word-boundary for Latin; Bangla script has no \b, so match directly
        if re.search(r"[ঀ-৿]", word):
            hit = word in t
        else:
            hit = re.search(r"\b" + re.escape(word) + r"\b", low) is not None
        if hit:
            # "this build is useless" is a complaint about the build
            if _WORK_GRIPE.search(low):
                continue
            return "abusive towards a colleague"
    return ""


def refusal(sender_name: str, target_name: str, creator_name: str = "Titu") -> str:
    """What to say to whoever asked. Short, warm, and not a lecture.

    Nobody is told off. The person asked for something the assistant will not
    do, it says so once and moves on, which leaves the working relationship
    intact.
    """
    s = f"{sender_name} bhai" if sender_name else "bhai"
    if target_name and target_name == creator_name:
        return (f"Sorry {s}, {creator_name} bhai is my creator. I cannot say "
                f"anything that can hurt him. Give me something else to pass "
                f"on and I will take it to him.")
    t = f"{target_name} bhai" if target_name else "a colleague"
    return (f"Sorry {s}, I cannot pass on something that would hurt {t}. "
            f"Anything else you want to tell him, I will carry it happily.")
