"""Daily 'flair' block for the requirement roll-up email.

A small, professional, audience-safe footer that changes every day so the
team (and the boss, who is on every send) gets something fresh:

  1. A live COVERAGE INSIGHT built from the week's real pipeline numbers
     (requirements captured, team calls processed).
  2. A rotating QUALITY/CRAFT QUOTE, selected deterministically by date.

Hard rule: this is cosmetic. Every entry point is wrapped so that ANY
failure returns an empty string — the daily email must never break or be
delayed because of the flair. The caller (mail.daily_rollup) computes the
week's numbers (it already has the verification-doc parser + central path)
and passes them in; this module only formats + picks the quote.
"""
from __future__ import annotations

import datetime as dt

_RULE = "-" * 32

# Professional, boss-safe quotes on quality, craft, teamwork, and
# continuous improvement. Rotated one-per-day by date. Keep additions
# tasteful — this goes to the whole team and management.
QUOTES: list[tuple[str, str]] = [
    ("Quality is not an act, it is a habit.", "Aristotle"),
    ("Quality means doing it right when no one is looking.", "Henry Ford"),
    ("Quality is never an accident; it is always the result of "
     "intelligent effort.", "John Ruskin"),
    ("The bitterness of poor quality remains long after the sweetness of "
     "low price is forgotten.", "Benjamin Franklin"),
    ("Testing leads to failure, and failure leads to understanding.",
     "Burt Rutan"),
    ("If you don't have time to do it right, when will you have time to do "
     "it over?", "John Wooden"),
    ("Continuous improvement is better than delayed perfection.",
     "Mark Twain"),
    ("It is not enough to do your best; you must know what to do, and then "
     "do your best.", "W. Edwards Deming"),
    ("Simplicity is the soul of efficiency.", "Austin Freeman"),
    ("Make it work, make it right, make it fast.", "Kent Beck"),
    ("The best way to predict the future is to invent it.", "Alan Kay"),
    ("Good code is its own best documentation.", "Steve McConnell"),
    ("Coming together is a beginning, staying together is progress, and "
     "working together is success.", "Henry Ford"),
    ("Alone we can do so little; together we can do so much.",
     "Helen Keller"),
    ("A satisfied customer is the best business strategy of all.",
     "Michael LeBoeuf"),
    ("Perfection is not attainable, but if we chase perfection we can "
     "catch excellence.", "Vince Lombardi"),
    ("The strength of the team is each individual member; the strength of "
     "each member is the team.", "Phil Jackson"),
    ("Plans are nothing; planning is everything.",
     "Dwight D. Eisenhower"),
    ("What gets measured gets managed.", "Peter Drucker"),
    ("Measure twice, cut once.", "Proverb"),
    ("The function of good software is to make the complex appear simple.",
     "Grady Booch"),
    ("First, solve the problem. Then, write the code.", "John Johnson"),
    ("Programs must be written for people to read, and only incidentally "
     "for machines to execute.", "Harold Abelson"),
    ("The details are not the details; they make the design.",
     "Charles Eames"),
    ("Knowing is not enough; we must apply. Willing is not enough; we must "
     "do.", "Johann Wolfgang von Goethe"),
    ("Care about your craft.", "The Pragmatic Programmer"),
    ("Excellence is doing ordinary things extraordinarily well.",
     "John W. Gardner"),
    ("Done is better than perfect — but done right is better still.",
     "NAPCO Nucleus"),
]

# Reassurance / relief lines in Nucleus's own voice, spoken TO the devs.
# The real problem this system solves: clients forget what they asked,
# requirements change untracked, devs forget / mishear / are under
# pressure. These say, plainly: you don't have to hold it all in your head
# — it's captured, sourced, and tracked. Boss-safe (they show the system
# de-risking the team) and morale-positive. Rendered without attribution
# since the whole email is already from NAPCO Nucleus.
REASSURANCE: list[str] = [
    "Every requirement from today's calls is captured here — you don't "
    "have to hold it all in your head.",
    "Clients forget. Conversations blur. That's exactly why Nucleus writes "
    "everything down, so nothing is lost.",
    "If it was said on a call, it's recorded and traceable. Build with a "
    "clear mind — the tracking is handled.",
    "No requirement slips through the cracks on my watch. Focus on the "
    "work; I'll keep the list.",
    "Unsure what the client actually asked? It's transcribed here. Check, "
    "don't second-guess yourself.",
    "What the client asked last week is still here today. Nothing "
    "forgotten, nothing quietly dropped.",
    "You don't have to remember everything — remembering is my job, so "
    "building can be yours.",
    "Every change of mind from the client is logged. If the goalposts "
    "moved, you'll see it here.",
    "One task at a time. The full list is safe with Nucleus, so today only "
    "needs today's focus.",
    "Pressure is real; missed requirements don't have to be. Nucleus keeps "
    "the receipts.",
    "Take a breath. The requirements are written, sourced, and waiting — "
    "they aren't going anywhere.",
    "If a requirement isn't in writing, it isn't your fault for forgetting "
    "it — that's the gap Nucleus closes.",
    "Steady beats frantic. The backlog is tracked; you just pick the next "
    "one and build it well.",
    "Every call, every chat, every change — kept in one place so the team "
    "carries less in their heads.",
    "Nothing here depends on anyone's memory. It depends on what was "
    "actually said — and that's all captured.",
]

# One merged rotation: attributed quotes + un-attributed Nucleus reassurance
# lines. (text, author) — author None marks a reassurance line.
ITEMS: list[tuple[str, str | None]] = (
    [(q, a) for q, a in QUOTES] + [(r, None) for r in REASSURANCE])


def _s(n: int) -> str:
    return "" if n == 1 else "s"


def _item_for(day: str) -> tuple[str, str | None]:
    """Pick one rotation item (quote or reassurance line) per calendar day,
    deterministically — so every day differs but is stable within the day."""
    try:
        idx = dt.date.fromisoformat(day).toordinal()
    except Exception:
        idx = 0
    return ITEMS[idx % len(ITEMS)]


def _insight(reqs_week: int, calls_week: int) -> str:
    """One line from the week's real numbers. Empty when there's nothing
    worth stating (so we don't print '0 requirements')."""
    if reqs_week <= 0 and calls_week <= 0:
        return ""
    if reqs_week > 0 and calls_week > 0:
        return (f"Nucleus coverage this week: {reqs_week} "
                f"requirement{_s(reqs_week)} captured across {calls_week} "
                f"team call{_s(calls_week)}.")
    if reqs_week > 0:
        return (f"Nucleus coverage this week: {reqs_week} "
                f"requirement{_s(reqs_week)} captured.")
    return (f"Nucleus coverage this week: {calls_week} team "
            f"call{_s(calls_week)} processed.")


def daily_flair(day: str, reqs_week: int = 0, calls_week: int = 0) -> str:
    """Return the flair block (rule + optional insight + a daily quote), or
    '' on any error. Never raises — the email must not depend on this."""
    try:
        lines = [_RULE]
        insight = _insight(int(reqs_week or 0), int(calls_week or 0))
        if insight:
            lines.append(insight)
            lines.append("")
        text, who = _item_for(day)
        if who:
            # Attributed quote.
            lines.append(f"“{text}”")
            lines.append(f"   — {who}")
        else:
            # Nucleus reassurance line — plain, no attribution (the email is
            # already from NAPCO Nucleus).
            lines.append(text)
        return "\n".join(lines)
    except Exception:
        return ""
