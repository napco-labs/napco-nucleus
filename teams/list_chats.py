"""List your Teams chats from the local IndexedDB cache.

Cross-references three stores:
  - Teams:conversation-manager → conversations  (chat list + last activity)
  - Teams:replychain-manager   → replychains    (sender MRIs per chat)
  - Teams:profiles             → profiles       (MRI → display name)

Output:
  - top 15 most-recent group chats to the terminal
  - full list (every group chat, every participant) to data/chats.txt

Use the output to identify the target conversation ID for the watcher.

Run: python list_chats.py
"""
from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

LEVELDB_PATH = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Packages" / "MSTeams_8wekyb3d8bbwe" / "LocalCache"
    / "Microsoft" / "MSTeams" / "EBWebView" / "WV2Profile_tfl"
    / "IndexedDB" / "https_teams.live.com_0.indexeddb.leveldb"
)

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "teams" / "chats.txt"


def fmt_ts(ms: float | int | None) -> str:
    if not ms or ms < 1_000_000_000_000:
        return "(no timestamp)"
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def find_db_by_prefix(db, prefix: str):
    for info in db.database_ids:
        if info.name and info.name.startswith(prefix):
            return info
    return None


def main() -> int:
    if not LEVELDB_PATH.exists():
        print(f"Not found: {LEVELDB_PATH}", file=sys.stderr)
        return 1

    from ccl_chromium_reader import ccl_chromium_indexeddb

    print("Opening IndexedDB...")
    db = ccl_chromium_indexeddb.WrappedIndexDB(str(LEVELDB_PATH))

    # --- 1. profiles: MRI -> displayName --------------------------------
    profiles: dict[str, str] = {}
    pinfo = find_db_by_prefix(db, "Teams:profiles:")
    if pinfo:
        print(f"Reading profiles from {pinfo.name[:80]}...")
        for rec in db[pinfo.dbid_no]["profiles"].iterate_records():
            v = rec.value
            if isinstance(v, dict):
                mri = v.get("mri") or v.get("id")
                name = v.get("displayName") or v.get("givenName") or ""
                if mri and name:
                    profiles[mri] = name

    # --- 2. replychains: conversationId -> {sender MRIs} ----------------
    # messageMap keys are dedupe keys of the form "<senderMri>_<sequence>".
    # MRIs themselves can contain underscores (e.g. 8:live:zaman_ael), so we
    # split on the LAST underscore. Only "8:" MRIs are real users; "19:"
    # entries are thread/system events and we drop them.
    def extract_user_mri(key: str, msg: dict) -> str | None:
        # Prefer the explicit 'from' field on the message if present.
        sender = msg.get("from") or msg.get("creator")
        if isinstance(sender, str) and sender.startswith("8:"):
            return sender
        # Fall back to the dedupe-key prefix.
        parts = key.rsplit("_", 1)
        candidate = parts[0]
        if candidate.startswith("8:"):
            return candidate
        return None

    conv_senders: dict[str, set[str]] = {}
    rcinfo = find_db_by_prefix(db, "Teams:replychain-manager:")
    if rcinfo:
        print(f"Reading replychains from {rcinfo.name[:80]}...")
        for rec in db[rcinfo.dbid_no]["replychains"].iterate_records():
            v = rec.value
            if isinstance(v, dict):
                cid = v.get("conversationId")
                msgmap = v.get("messageMap") or {}
                if cid:
                    bucket = conv_senders.setdefault(cid, set())
                    for key, msg in msgmap.items():
                        if isinstance(msg, dict):
                            mri = extract_user_mri(key, msg)
                            if mri:
                                bucket.add(mri)

    # --- 3. conversations: the chat list --------------------------------
    convs: list[dict] = []
    cinfo = find_db_by_prefix(db, "Teams:conversation-manager:")
    if cinfo:
        print(f"Reading conversations from {cinfo.name[:80]}...")
        for rec in db[cinfo.dbid_no]["conversations"].iterate_records():
            v = rec.value
            if isinstance(v, dict):
                convs.append(v)

    # Dedupe: same conversation can appear multiple times — keep the most recent
    convs.sort(key=lambda c: c.get("lastMessageTimeUtc") or 0, reverse=True)
    seen: set[str] = set()
    unique: list[dict] = []
    for c in convs:
        cid = c.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            unique.append(c)

    group_chats = [
        c for c in unique
        if "thread.v2" in (c.get("id") or "")
        and c.get("lastMessageTimeUtc")
    ]

    # --- 4. write full file ---------------------------------------------
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        f.write(f"Total unique conversations:        {len(unique)}\n")
        f.write(f"Group chats (thread.v2) with msgs: {len(group_chats)}\n\n")
        f.write("=" * 78 + "\n\n")
        for c in group_chats:
            cid = c.get("id") or "?"
            last = fmt_ts(c.get("lastMessageTimeUtc"))
            senders = conv_senders.get(cid, set())
            names = sorted({profiles.get(s) or s for s in senders}, key=str.casefold)
            f.write(f"Last activity: {last}\n")
            f.write(f"Conversation ID: {cid}\n")
            f.write(f"Participants ({len(names)}):\n")
            for n in names:
                f.write(f"    - {n}\n")
            f.write("\n")

    # --- 5. console summary ---------------------------------------------
    print(f"\nWrote {len(group_chats)} group chats to: {OUTPUT_PATH}\n")
    print("=== Top 15 most-recent group chats ===\n")
    for i, c in enumerate(group_chats[:15], 1):
        cid = c.get("id") or "?"
        last = fmt_ts(c.get("lastMessageTimeUtc"))
        senders = conv_senders.get(cid, set())
        names = sorted({profiles.get(s) or s for s in senders}, key=str.casefold)
        names_preview = ", ".join(names[:4])
        if len(names) > 4:
            names_preview += f", +{len(names) - 4} more"
        print(f"{i:>2}. {last}  ({len(names)} ppl)  {names_preview}")
        print(f"     {cid}")
        print()

    print(f"Open {OUTPUT_PATH} for the full list.")
    print("Tell me the conversation ID of the chat you want to monitor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
