"""Shared helper: list of Teams conversation_ids the dev does NOT want
pushed to central (chat or call).

Source: the `NUCLEUS_EXCLUDE_CHATS` env var, comma-separated. Trailing
whitespace and empty entries are ignored. conversation_ids are matched
exactly — get the value from `python -m teams.list_chats`.

Used by:
  - teams.push_chat: skip excluded conversations when bundling chat.
  - teams.voice_daemon: bail out of _start_recording when the active
    call resolves to an excluded conversation_id.
"""
from __future__ import annotations

import os


def excluded_conversation_ids() -> set[str]:
    raw = (os.environ.get("NUCLEUS_EXCLUDE_CHATS") or "").strip()
    if not raw:
        return set()
    return {p.strip() for p in raw.split(",") if p.strip()}
