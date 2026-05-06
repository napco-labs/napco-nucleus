"""
NAPCO Nucleus — Teams chat ingestion (local IndexedDB → markdown).

One MCP tool:

    ingest_teams_chat   Read messages from a specific Teams group chat
                        (consumer MSA cache) and write them as markdown
                        to data/requirements/inbox/chat/.

This is a NN-side port of the Teams-Requirement-Watcher reader. Runs
ONLY on a machine where Teams desktop is signed in and the cache is
populated — i.e. Mohammad's local box, not the runner. The agent task
that calls this tool must run locally.

Default conversation id: TEAMS_REQUIREMENTS_CONVERSATION_ID env var,
falling back to the ContiHosting group (chat #123 in TRW's registry):
  19:d52919448d3a4dc1a71af28521280ef0@thread.skype
"""
from __future__ import annotations

import datetime
import html
import json
import logging
import os
import re
from pathlib import Path

from claude_agent_sdk import tool

import memory

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent.parent
_CHAT_INBOX = _HERE / "data" / "requirements" / "inbox" / "chat"

# Consumer MSA Teams desktop IndexedDB path (Windows).
_LEVELDB_PATH = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Packages" / "MSTeams_8wekyb3d8bbwe" / "LocalCache"
    / "Microsoft" / "MSTeams" / "EBWebView" / "WV2Profile_tfl"
    / "IndexedDB" / "https_teams.live.com_0.indexeddb.leveldb"
)

_DEFAULT_CONVERSATION_ID = "19:d52919448d3a4dc1a71af28521280ef0@thread.skype"


def _text(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


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
        "message_type": msg.get("messageType", ""),
        "body": body,
    }


def _read_conversation(conversation_id: str) -> list[dict]:
    """Single-pass read of the replychain DB for ONE conversation. Returns
    sorted-ascending list of normalized messages. Caller handles errors."""
    if not _LEVELDB_PATH.exists():
        raise FileNotFoundError(
            f"Teams cache not found at {_LEVELDB_PATH}. "
            f"Is Teams desktop installed and signed in on this machine?"
        )
    from ccl_chromium_reader import ccl_chromium_indexeddb  # lazy
    db = ccl_chromium_indexeddb.WrappedIndexDB(str(_LEVELDB_PATH))
    profiles = _load_profiles(db)

    rcinfo = _find_db(db, "Teams:replychain-manager:")
    if not rcinfo:
        return []

    out: list[dict] = []
    seen_ids: set[str] = set()
    for rec in db[rcinfo.dbid_no]["replychains"].iterate_records():
        v = rec.value
        if not isinstance(v, dict):
            continue
        if v.get("conversationId") != conversation_id:
            continue
        msgmap = v.get("messageMap") or {}
        for key, msg in msgmap.items():
            if not isinstance(msg, dict):
                continue
            normalized = _normalize_message(msg, key, conversation_id, profiles)
            if not normalized:
                continue
            if normalized["id"] in seen_ids:
                continue
            seen_ids.add(normalized["id"])
            out.append(normalized)

    out.sort(key=lambda m: m["arrival_ms"] or 0)
    return out


def _safe_slug(s: str, max_len: int = 60) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]", "_", s or "")
    return s[:max_len].strip("_") or "chat"


# ─── ingest_teams_chat ──────────────────────────────────────────────

@tool(
    "ingest_teams_chat",
    "Read all messages from a Teams group chat (consumer MSA cache) and "
    "write them as markdown to data/requirements/inbox/chat/. Defaults to "
    "the ContiHosting group chat (env TEAMS_REQUIREMENTS_CONVERSATION_ID, "
    "fallback 19:d52919448d3a4dc1a71af28521280ef0@thread.skype). Pass "
    "`conversation_id` to override. Output: chat_<sanitized-id>_<YYYY-MM-DD>.md "
    "with one message per block in '[YYYY-MM-DD HH:MM] Sender: body' shape. "
    "Returns {path, message_count, participants, date_range, conversation_id}. "
    "REQUIRES the local Teams desktop cache — fails on the runner.",
    {"conversation_id": str, "since_ms": int},
)
async def ingest_teams_chat_tool(args):
    cid = (args.get("conversation_id") or "").strip()
    if not cid:
        cid = (os.environ.get("TEAMS_REQUIREMENTS_CONVERSATION_ID") or "").strip()
    if not cid:
        cid = _DEFAULT_CONVERSATION_ID
    since_ms = args.get("since_ms")
    if not isinstance(since_ms, int):
        since_ms = None

    try:
        msgs = _read_conversation(cid)
    except ImportError as e:
        return _text({
            "error": "ccl_chromium_reader not installed. "
                     "pip install git+https://github.com/cclgroupltd/ccl_chromium_reader.git",
            "detail": str(e),
        })
    except FileNotFoundError as e:
        return _text({"error": str(e)})
    except Exception as e:
        logger.exception("ingest_teams_chat failed")
        memory.log_activity(
            task_name="requirement-collection:ingest_teams_chat",
            result=f"error:{type(e).__name__}",
            technical_details={"error": str(e), "conversation_id": cid},
        )
        return _text({"error": f"{type(e).__name__}: {e}", "conversation_id": cid})

    if since_ms is not None:
        msgs = [m for m in msgs if (m.get("arrival_ms") or 0) >= since_ms]

    if not msgs:
        memory.log_activity(
            task_name="requirement-collection:ingest_teams_chat",
            result="empty",
            technical_details={"conversation_id": cid},
        )
        return _text({
            "conversation_id": cid,
            "message_count": 0,
            "note": "No messages in conversation (or none after since_ms filter).",
        })

    senders: list[str] = []
    for m in msgs:
        n = m.get("sender_name") or ""
        if n and n not in senders:
            senders.append(n)
    first = datetime.datetime.fromtimestamp((msgs[0].get("arrival_ms") or 0) / 1000)
    last = datetime.datetime.fromtimestamp((msgs[-1].get("arrival_ms") or 0) / 1000)

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    safe = _safe_slug(cid)
    _CHAT_INBOX.mkdir(parents=True, exist_ok=True)
    out = _CHAT_INBOX / f"chat_{safe}_{today}.md"

    with out.open("w", encoding="utf-8") as f:
        f.write("# Teams chat dump\n\n")
        f.write(f"_Conversation ID_: `{cid}`  \n")
        f.write(f"_Total messages_: {len(msgs)}  \n")
        f.write(f"_Date range_: {first:%Y-%m-%d %H:%M} -> {last:%Y-%m-%d %H:%M}  \n")
        f.write(f"_Participants_ ({len(senders)}): {', '.join(senders)}\n\n")
        f.write("---\n\n")
        for m in msgs:
            ts = datetime.datetime.fromtimestamp((m.get("arrival_ms") or 0) / 1000)
            sender = m.get("sender_name") or "(unknown)"
            body = (m.get("body") or "").strip()
            if not body:
                continue
            f.write(f"**[{ts:%Y-%m-%d %H:%M}] {sender}:**  \n")
            for line in body.splitlines() or [body]:
                f.write(f"> {line}\n")
            f.write("\n")

    memory.log_activity(
        task_name="requirement-collection:ingest_teams_chat",
        result=f"messages={len(msgs)} path={out.name}",
        technical_details={
            "conversation_id": cid,
            "message_count": len(msgs),
            "participants": senders,
            "date_range": f"{first:%Y-%m-%d} -> {last:%Y-%m-%d}",
            "path": str(out),
        },
    )

    return _text({
        "path": str(out.relative_to(_HERE).as_posix()),
        "absolute_path": str(out),
        "message_count": len(msgs),
        "participants": senders,
        "date_range": f"{first:%Y-%m-%d %H:%M} -> {last:%Y-%m-%d %H:%M}",
        "conversation_id": cid,
    })


TOOLS = [ingest_teams_chat_tool]
TOOL_NAMES = ["ingest_teams_chat"]
