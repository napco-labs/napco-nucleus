"""Shared helper: the allowlist of Teams calls the AUTO recorder is allowed
to record (specific group chats and/or specific members). Inverse of
teams._exclude.

Customer requirement (2026-07-06): the daemon must record ONLY calls that
involve a listed group chat or a listed member, and SKIP every other call.

Two env vars, both comma-separated, both optional:

  NUCLEUS_INCLUDE_CHATS    conversation_ids (group / 1:1 chats) to record.
                           Get ids from `python -m teams.list_chats` or
                           `python -m teams.whois` (run during a call).

  NUCLEUS_INCLUDE_MEMBERS  people to record. Each entry matches a call
                           participant when it EITHER equals that person's
                           Teams MRI (e.g. "8:live:zaman_ael" — exact,
                           case-insensitive) OR is a case-insensitive
                           substring of their display name (e.g. "atik").
                           Prefer MRIs — display names can collide. Get both
                           from `python -m teams.whois`.

Allowlist mode is ON only when at least one of the two vars is non-empty.
When BOTH are empty the allowlist is OFF and the recorder behaves exactly as
before (records every Teams call), so this stays backward-compatible.

A call/chat is kept when it matches an allowlisted chat OR an allowlisted
member (union, not intersection). Consumed by:
  - teams.voice_daemon's AUTO watcher (CALLS) — see _allowlisted_active_call
    there for the hard-gate / fail-closed semantics (no non-allowlisted audio
    is ever written to disk). Matches via match_member (MRI + name).
  - teams.push_chat (CHAT text) — see chat_included below; matches via
    match_member_name (display names only, from chat_registry).
"""
from __future__ import annotations

import os


def included_conversation_ids() -> set[str]:
    raw = (os.environ.get("NUCLEUS_INCLUDE_CHATS") or "").strip()
    if not raw:
        return set()
    return {p.strip() for p in raw.split(",") if p.strip()}


def included_member_tokens() -> list[str]:
    raw = (os.environ.get("NUCLEUS_INCLUDE_MEMBERS") or "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def allowlist_active() -> bool:
    """True when at least one allowlist var is set. When False the recorder
    records every call (feature off)."""
    return bool(included_conversation_ids() or included_member_tokens())


def match_member(participants, tokens) -> str | None:
    """Return the display name (or MRI) of the first participant that matches
    any token, else None.

    A token matches a participant when it EQUALS the participant identity
    (MRI), case-insensitively, OR is a case-insensitive substring of the
    participant display name. MRI compare is exact so a short token can't
    accidentally match an MRI; name compare is substring so "atik" matches
    "Atikur Zaman".

    `participants` is the resolver's list of {"identity": mri, "name": disp}.
    Used by the CALL path (teams.calls resolver), which has MRIs.
    """
    if not tokens:
        return None
    toks = [t.lower() for t in tokens if t]
    for p in participants or []:
        ident = (p.get("identity") or "").lower()
        name = p.get("name") or ""
        name_l = name.lower()
        for t in toks:
            if t == ident or (name_l and t in name_l):
                return name or p.get("identity") or ""
    return None


def match_member_name(names, tokens) -> str | None:
    """Name-only variant of match_member for the CHAT path.

    The chat_registry stores participants as plain display-name strings
    (participants_json), not {identity, name} dicts — there are no MRIs to
    match against. So a token matches when it EQUALS or is a case-insensitive
    substring of a participant name ("salman" matches "Salman Ahmed Firoz").
    Prefer display-name tokens (not MRIs) in NUCLEUS_INCLUDE_MEMBERS so the
    same value works for both calls and chats.
    """
    if not tokens:
        return None
    toks = [t.lower() for t in tokens if t]
    for name in names or []:
        nl = (name or "").lower()
        if not nl:
            continue
        for t in toks:
            if t == nl or t in nl:
                return name
    return None


def call_matches_allowlist(conversation_id, participants) -> bool:
    """Allowlist decision for a RESOLVED call (used by record_call's finalizer).

    True when the call's conversation_id is on NUCLEUS_INCLUDE_CHATS OR one of
    its participants matches NUCLEUS_INCLUDE_MEMBERS. `participants` is the
    resolver's list of {"identity": mri, "name": disp} dicts, so this matches
    via match_member (MRI + display name), unlike the chat path.

    Only meaningful when allowlist_active() — the finalizer gates on that so a
    call is filtered ONLY when the allowlist is on. Called at end-of-call
    (record-then-filter): the daemon records every call, then the finalizer
    keeps only the ones this returns True for. Deciding here, not at call
    start, is deliberate — participants only exist once callEnded has fired
    (see teams.calls.resolve_client_for_recording), so a start-time decision
    always resolved to (unknown) and dropped every call (2026-07-06).
    """
    if conversation_id and conversation_id in included_conversation_ids():
        return True
    return match_member(participants, included_member_tokens()) is not None


def chat_included(conversation_id, participant_names) -> bool:
    """Allowlist decision for a whole CHAT (used by teams.push_chat).

    True when the chat should be kept under the allowlist: its
    conversation_id is on NUCLEUS_INCLUDE_CHATS, OR one of its participant
    names matches NUCLEUS_INCLUDE_MEMBERS. Only meaningful when
    allowlist_active() — callers should gate on that so the feature stays
    off (keep every chat) when neither var is set.
    """
    if conversation_id and conversation_id in included_conversation_ids():
        return True
    return match_member_name(participant_names, included_member_tokens()) is not None
