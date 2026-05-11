"""Read messages from the Teams local IndexedDB cache.

Pure read — no SQLite, no side effects. Two public functions:

  list_monitored_conversations(exclude_ids) -> list of group-chat conversations
  read_chat_messages(conversation_id)       -> messages for one conversation
"""
from __future__ import annotations

import html
import os
import re
from pathlib import Path
from typing import Iterator

LEVELDB_PATH = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Packages" / "MSTeams_8wekyb3d8bbwe" / "LocalCache"
    / "Microsoft" / "MSTeams" / "EBWebView" / "WV2Profile_tfl"
    / "IndexedDB" / "https_teams.live.com_0.indexeddb.leveldb"
)


def _coerce_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode("utf-8", errors="replace")
        except Exception:
            return ""
    return ""


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = s.replace("\xa0", " ")
    return s.strip()


def _is_real_chat(msg: dict) -> bool:
    mt = msg.get("messageType") or ""
    return mt in ("Text", "RichText/Html") or mt.startswith("RichText")


# URIObject types Teams uses for shared content
_URI_TYPE_LABEL = {
    "File.1": "File",
    "Picture.1": "Image",
    "Video.1": "Video",
    "Audio.1": "Audio",
}


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _extract_uriobject(content: str) -> dict | None:
    """Pull attachment metadata from a URIObject XML blob. Returns
    {name, kind, size_bytes, url} or None if no URIObject present."""
    if "<URIObject" not in content:
        return None
    type_m = re.search(r'\btype="([^"]+)"', content)
    uri_m = re.search(r'\buri="([^"]+)"', content)
    name_m = re.search(r'<OriginalName\s+v="([^"]*)"', content)
    size_m = re.search(r'<FileSize\s+v="(\d+)"', content)
    obj_type = (type_m.group(1) if type_m else "") or ""
    kind = _URI_TYPE_LABEL.get(obj_type, obj_type or "Attachment")
    size_bytes = int(size_m.group(1)) if size_m else 0
    return {
        "name": (name_m.group(1) if name_m else "") or "(no name)",
        "kind": kind,
        "size_bytes": size_bytes,
        "url": (uri_m.group(1) if uri_m else "") or "",
    }


def _format_attachment_body(att: dict) -> str:
    """Render one URIObject's metadata as a single readable body line."""
    size = f", {_fmt_size(att['size_bytes'])}" if att.get("size_bytes") else ""
    url = f"\nURL: {att['url']}" if att.get("url") else ""
    return f"[Attachment: {att['name']} ({att['kind']}{size})]{url}"


def _extract_contact_body(content: str) -> str:
    """Render <contacts><c .../></contacts> as a body line."""
    names: list[str] = []
    for m in re.finditer(r'<c\s[^>]*f="([^"]+)"', content):
        names.append(m.group(1))
    if not names:
        return "[Shared contact]"
    return "[Shared contact: " + ", ".join(names) + "]"


def _find_db(db, prefix: str):
    for info in db.database_ids:
        if info.name and info.name.startswith(prefix):
            return info
    return None


def _load_profiles(db) -> dict[str, str]:
    info = _find_db(db, "Teams:profiles:")
    if not info:
        return {}
    profiles: dict[str, str] = {}
    for rec in db[info.dbid_no]["profiles"].iterate_records():
        v = rec.value
        if isinstance(v, dict):
            mri = v.get("mri") or v.get("id")
            name = v.get("displayName") or v.get("givenName") or ""
            if mri and name:
                profiles[mri] = name
    return profiles


def list_monitored_conversations(
    exclude_ids: set[str] | None = None,
) -> list[dict]:
    """Enumerate all GROUP chats (thread.v2) with at least one message.

    Returns a list of dicts: {id, title, last_ms, participant_count}.
    Excludes any conversation whose id is in `exclude_ids`.
    Sorted by last activity, most recent first.
    """
    if not LEVELDB_PATH.exists():
        return []

    from ccl_chromium_reader import ccl_chromium_indexeddb
    db = ccl_chromium_indexeddb.WrappedIndexDB(str(LEVELDB_PATH))

    cinfo = _find_db(db, "Teams:conversation-manager:")
    if not cinfo:
        return []

    raw: list[dict] = []
    for rec in db[cinfo.dbid_no]["conversations"].iterate_records():
        v = rec.value
        if isinstance(v, dict):
            raw.append(v)

    # Dedupe: same conversation can appear multiple times — keep most recent
    raw.sort(key=lambda c: c.get("lastMessageTimeUtc") or 0, reverse=True)
    seen: set[str] = set()
    excluded = exclude_ids or set()

    out: list[dict] = []
    for c in raw:
        cid = c.get("id") or ""
        if not cid or cid in seen:
            continue
        seen.add(cid)
        if cid in excluded:
            continue
        if "thread.v2" not in cid:
            continue
        if not c.get("lastMessageTimeUtc"):
            continue
        out.append(
            {
                "id": cid,
                "title": c.get("title") or c.get("threadTopic") or "",
                "last_ms": int(c.get("lastMessageTimeUtc") or 0),
            }
        )
    return out


def _normalize_message(msg: dict, key: str, conversation_id: str, profiles: dict[str, str]) -> dict | None:
    if not _is_real_chat(msg):
        return None

    mid = str(msg.get("id") or key)

    creator = msg.get("creator")
    if not (isinstance(creator, str) and creator.startswith("8:")):
        fallback = key.rsplit("_", 1)[0]
        creator = fallback if fallback.startswith("8:") else ""

    sender_name = (
        msg.get("imDisplayName")
        or profiles.get(creator)
        or creator
        or "(unknown)"
    )

    content = _coerce_text(msg.get("content"))
    mt = msg.get("messageType") or ""

    # Attachment messages: file / image / video / audio shared in chat.
    # Replace the (largely useless) HTML chrome with a structured
    # one-liner so downstream consumers and the LLM identifier see the
    # filename, kind, size, and URL.
    attachment = None
    if mt in ("RichText/Media_GenericFile", "RichText/UriObject") \
            or mt.startswith("RichText/Media_"):
        attachment = _extract_uriobject(content)

    if attachment:
        body = _format_attachment_body(attachment)
    elif mt == "RichText/Contacts":
        body = _extract_contact_body(content)
    elif mt in ("RichText/Media_CallTranscript", "RichText/Media_Album"):
        # CallTranscript carries opaque JSON pointer metadata; Album is empty.
        # Neither contributes to requirement extraction — emit nothing.
        body = ""
    else:
        body = _strip_html(content) if "<" in content else content.strip()

    return {
        "id": mid,
        "conversation_id": conversation_id,
        "sender_mri": creator,
        "sender_name": sender_name,
        "is_self": bool(msg.get("isSentByCurrentUser")),
        "arrival_ms": int(
            msg.get("originalArrivalTime")
            or msg.get("clientArrivalTime")
            or 0
        ),
        "message_type": mt,
        "body": body,
        "attachment": attachment,
        "raw": msg,
    }


def read_messages_by_conversations(
    conversation_ids: set[str] | None = None,
    since_ms: int | None = None,
) -> dict[str, list[dict]]:
    """Single-pass read of the replychain DB.

    Returns dict { conversation_id: [messages sorted by arrival_ms] }.
    If `conversation_ids` is None, returns messages for all conversations.
    If `since_ms` is given, drops messages older than that timestamp.
    """
    if not LEVELDB_PATH.exists():
        return {}

    from ccl_chromium_reader import ccl_chromium_indexeddb
    db = ccl_chromium_indexeddb.WrappedIndexDB(str(LEVELDB_PATH))
    profiles = _load_profiles(db)

    rcinfo = _find_db(db, "Teams:replychain-manager:")
    if not rcinfo:
        return {}

    out: dict[str, list[dict]] = {}
    seen_ids: set[str] = set()

    for rec in db[rcinfo.dbid_no]["replychains"].iterate_records():
        v = rec.value
        if not isinstance(v, dict):
            continue
        cid = v.get("conversationId")
        if not cid:
            continue
        if conversation_ids is not None and cid not in conversation_ids:
            continue

        msgmap = v.get("messageMap") or {}
        for key, msg in msgmap.items():
            if not isinstance(msg, dict):
                continue
            normalized = _normalize_message(msg, key, cid, profiles)
            if not normalized:
                continue
            if since_ms is not None and (normalized["arrival_ms"] or 0) < since_ms:
                continue
            if normalized["id"] in seen_ids:
                continue
            seen_ids.add(normalized["id"])
            out.setdefault(cid, []).append(normalized)

    for cid in out:
        out[cid].sort(key=lambda m: m["arrival_ms"] or 0)
    return out


def read_chat_messages(conversation_id: str) -> Iterator[dict]:
    """Yield real chat messages for one conversation. Backwards-compat wrapper."""
    grouped = read_messages_by_conversations({conversation_id})
    yield from grouped.get(conversation_id, [])
