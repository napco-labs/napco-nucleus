"""Resolve client info for a recorded call by walking Teams IndexedDB.

Each Teams call writes one `Event/Call` message into the local IndexedDB
replychain database. The message carries:
  - `originalArrivalTime` (epoch ms) — when the call event landed
  - `creator` — MRI of who placed the call (e.g. "8:live:susmoy.saha")
  - `conversationId` — the chat the call belongs to
  - `content` — XML <partlist> with every participant's identity + display name
  - `isSentByCurrentUser` — True when the current user placed the call

Given a recording start timestamp, this module finds the closest
Event/Call within a configurable window and returns the participant(s)
that aren't the current user — i.e. the client(s) on the call.

Used by:
  - teams/record_call.py (post-stop, to enrich the metadata sidecar)
  - any future tool that needs to ask "who was on this call?"
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from teams.reader import LEVELDB_PATH, _find_db


# ─── self-MRI detection ─────────────────────────────────────────────

def _self_mri_from_db_names(db) -> Optional[str]:
    """Some Teams databases embed the current user's MRI in their name,
    e.g. `Teams:tenant-manager:react-web-client:<aad>:8:titucse:en-us`.
    Returns the first `8:<username>` segment we find. None if not present."""
    pat = re.compile(r":(8:[A-Za-z0-9._-]+):")
    for info in db.database_ids:
        if not info.name:
            continue
        m = pat.search(info.name)
        if m:
            return m.group(1)
    return None


def _self_mri_from_messages(db, rcinfo, scan_limit: int = 200) -> Optional[str]:
    """Authoritative fallback: walk the replychain looking for a message
    flagged isSentByCurrentUser=True and read its `creator` field. That
    creator MRI is the current user. Stop after finding one or scanning
    `scan_limit` messages."""
    seen = 0
    for rec in db[rcinfo.dbid_no]["replychains"].iterate_records():
        v = rec.value
        if not isinstance(v, dict):
            continue
        for msg in (v.get("messageMap") or {}).values():
            if not isinstance(msg, dict):
                continue
            seen += 1
            if msg.get("isSentByCurrentUser") and msg.get("creator", "").startswith("8:"):
                return msg.get("creator")
            if seen >= scan_limit:
                return None
    return None


# ─── partlist parsing ───────────────────────────────────────────────

def _parse_partlist(content: str) -> tuple[str, str, list[dict]]:
    """Parse an Event/Call message's content XML.

    Handles two Teams schema shapes:

    Old (multi-year-old logs):
      <partlist type="missed" callId="UUID">
        <part identity="live:foo"><name>Foo</name></part>
      </partlist>

    New (current Teams):
      <ended/>
      <partlist count="N">
        <part identity="8:foo">
          <name>8:foo</name>           <-- raw identity
          <displayName>Foo Bar</displayName>  <-- actual display name
          <duration>123</duration>
        </part>
      </partlist>
      <callEventType>callEnded</callEventType>
      <callId>UUID</callId>

    Returns (call_type, call_id, participants) where participants prefer
    displayName, fall back to <name> only if it isn't an MRI, and finally
    to the identity itself.
    """
    if not content:
        return ("", "", [])
    # Wrap in a fake root so ET can parse the multi-top-level shape.
    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError:
        return _parse_partlist_regex(content)

    partlist = root.find("partlist")
    if partlist is None:
        return _parse_partlist_regex(content)

    # callId: prefer top-level <callId>, fall back to partlist attribute (old shape).
    call_id_elem = root.find("callId")
    call_id = (call_id_elem.text or "").strip() if call_id_elem is not None and call_id_elem.text else ""
    if not call_id:
        call_id = (partlist.attrib.get("callId") or "").strip()

    # call_type: <callEventType> wins; partlist@type as fallback; sibling tags
    # like <ended/>, <missed/>, <answered/> as last-resort signal.
    call_type = ""
    cet = root.find("callEventType")
    if cet is not None and cet.text:
        call_type = cet.text.strip()
    if not call_type:
        call_type = (partlist.attrib.get("type") or "").strip()
    if not call_type:
        for tag in ("ended", "missed", "answered", "started", "declined"):
            if root.find(tag) is not None:
                call_type = tag
                break

    parts: list[dict] = []
    for p in partlist.findall("part"):
        identity = (p.attrib.get("identity") or "").strip()
        display = ""
        dn = p.find("displayName")
        if dn is not None and dn.text and dn.text.strip():
            display = dn.text.strip()
        if not display:
            n = p.find("name")
            if n is not None and n.text:
                t = n.text.strip()
                # In the new shape <name> mirrors identity (e.g. "8:foo");
                # only treat as a real display name if it doesn't look like an MRI.
                if t and not t.startswith("8:"):
                    display = t
        if not display:
            display = identity
        parts.append({"identity": identity, "name": display})

    return (call_type, call_id, parts)


_RE_PART_NEW = re.compile(
    r'<part\s+identity="([^"]+)"[^>]*>'
    r'(?:.*?<displayName>([^<]*)</displayName>)?'
    r'(?:.*?<name>([^<]*)</name>)?',
    re.I | re.S,
)
_RE_CALLID_TOP = re.compile(r'<callId>([^<]+)</callId>', re.I)
_RE_CALLEVENTTYPE = re.compile(r'<callEventType>([^<]+)</callEventType>', re.I)
_RE_PARTLIST_ATTRS = re.compile(r'<partlist\b([^>]*)>', re.I)


def _parse_partlist_regex(content: str) -> tuple[str, str, list[dict]]:
    """Fallback when XML parsing fails. Tolerant of malformed content."""
    call_id = ""
    call_type = ""
    m = _RE_CALLID_TOP.search(content)
    if m:
        call_id = m.group(1).strip()
    m = _RE_CALLEVENTTYPE.search(content)
    if m:
        call_type = m.group(1).strip()
    if not call_id or not call_type:
        # Old-shape attributes on the partlist tag itself.
        m = _RE_PARTLIST_ATTRS.search(content)
        if m:
            attrs = m.group(1)
            mm = re.search(r'callId="([^"]+)"', attrs)
            if mm and not call_id:
                call_id = mm.group(1)
            mm = re.search(r'type="([^"]+)"', attrs)
            if mm and not call_type:
                call_type = mm.group(1)
    parts: list[dict] = []
    for ident, display, name in _RE_PART_NEW.findall(content):
        ident = ident.strip()
        display = (display or "").strip()
        name = (name or "").strip()
        chosen = display or (name if name and not name.startswith("8:") else "") or ident
        parts.append({"identity": ident, "name": chosen})
    return (call_type, call_id, parts)


# ─── self-filter ────────────────────────────────────────────────────

def _is_self(participant_identity: str, self_mri: Optional[str]) -> bool:
    """True if a partlist <part identity=...> entry is the current user.

    Teams stores partlist identities WITHOUT the `8:` MRI prefix
    (e.g. `live:susmoy.saha`, `titucse`), but the self_mri WITH the
    prefix (e.g. `8:titucse`). Match by suffix.
    """
    if not self_mri or not participant_identity:
        return False
    bare = self_mri.split(":", 1)[1] if ":" in self_mri else self_mri
    pi = participant_identity.lower()
    return pi == bare.lower() or pi.endswith(":" + bare.lower())


# ─── public API ─────────────────────────────────────────────────────

def resolve_client_for_recording(
    start_time_unix_ms: int,
    window_seconds: int = 120,
) -> dict:
    """Find the Teams call closest to start_time and return participant info.

    Args:
      start_time_unix_ms: epoch ms of when recording started (or any point
        during the call). The resolver searches Event/Call entries with
        `originalArrivalTime` within ±window_seconds of this.
      window_seconds: half-width of the search window. Default 120 (a
        Teams call is rarely longer than ~2 hours; 120s is plenty for
        matching recording-start to call-event-arrival).

    Returns a dict with:
      matched (bool), reason (str)
      call_id, conversation_id, call_type, started_at_ms (when matched)
      self_mri (the current user's MRI, e.g. "8:titucse")
      participants: full list (may include self)
      clients: participants minus self
      client_name: best-guess primary client display name
      delta_seconds: how far the matched call was from start_time
    """
    if not LEVELDB_PATH.exists():
        return {"matched": False,
                "reason": f"Teams IndexedDB not found at {LEVELDB_PATH}"}
    try:
        from ccl_chromium_reader import ccl_chromium_indexeddb
    except ImportError as e:
        return {"matched": False, "reason": f"ccl_chromium_reader missing: {e}"}

    try:
        db = ccl_chromium_indexeddb.WrappedIndexDB(str(LEVELDB_PATH))
    except Exception as e:
        return {"matched": False, "reason": f"failed to open IndexedDB: {e}"}

    rcinfo = _find_db(db, "Teams:replychain-manager:")
    if not rcinfo:
        return {"matched": False, "reason": "replychain DB not present"}

    # Resolve current user's MRI: try authoritative first, then fall back.
    self_mri = _self_mri_from_messages(db, rcinfo) or _self_mri_from_db_names(db)

    best: Optional[dict] = None
    best_delta_ms: Optional[int] = None
    window_ms = window_seconds * 1000

    for rec in db[rcinfo.dbid_no]["replychains"].iterate_records():
        v = rec.value
        if not isinstance(v, dict):
            continue
        cid = v.get("conversationId") or ""
        for msg in (v.get("messageMap") or {}).values():
            if not isinstance(msg, dict):
                continue
            if msg.get("messageType") != "Event/Call":
                continue
            arrival = int(msg.get("originalArrivalTime") or 0)
            if not arrival:
                continue
            delta = abs(arrival - start_time_unix_ms)
            if delta > window_ms:
                continue
            if best_delta_ms is not None and delta >= best_delta_ms:
                continue
            content = msg.get("content") or ""
            call_type, call_id, parts = _parse_partlist(content)
            best = {
                "arrival_ms": arrival,
                "conversation_id": cid,
                "call_type": call_type,
                "call_id": call_id,
                "creator": msg.get("creator", ""),
                "is_self_caller": bool(msg.get("isSentByCurrentUser", False)),
                "participants": parts,
            }
            best_delta_ms = delta

    if best is None:
        return {
            "matched": False,
            "reason": (f"no Event/Call within +/-{window_seconds}s of "
                       f"{start_time_unix_ms}"),
            "self_mri": self_mri,
        }

    clients = [p for p in best["participants"]
               if not _is_self(p["identity"], self_mri)]
    primary = clients[0]["name"] if clients else "(unknown)"

    return {
        "matched": True,
        "reason": "matched",
        "call_id": best["call_id"],
        "conversation_id": best["conversation_id"],
        "call_type": best["call_type"],
        "started_at_ms": best["arrival_ms"],
        "self_mri": self_mri,
        "is_self_caller": best["is_self_caller"],
        "participants": best["participants"],
        "clients": clients,
        "client_name": primary,
        "delta_seconds": (best_delta_ms or 0) / 1000.0,
    }
