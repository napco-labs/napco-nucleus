"""Push the dev's recent Teams chat messages to the central store.

Runs on a 15-min Windows Task Scheduler timer per teammate. Each run:

  1. Reads every Teams chat in the local IndexedDB that has messages in
     the last N minutes (default 15).
  2. Consolidates them into ONE .docx (one section per chat with msgs).
  3. Writes the .docx locally to data/teams/chat-pushes/ for audit.
  4. If NUCLEUS_CENTRAL_PATH is set, copies the .docx to:
        <central>/<dev>/<YYYY-MM-DD>/chat/chat_<HHMM>-<HHMM>.docx
     so the agent host can pick up everyone's chat fragments in one place.

Differs from teams.pull_chat:
  - pull_chat appends to the per-dev session doc (the dev's local
    on-demand workflow). This script is for scheduled cross-dev sync.
  - Always writes a STANDALONE .docx per run; never touches session_doc.
  - All-chats only — no chat picking; no manual filters.

Usage
    python -m teams.push_chat                      # last 15 min
    python -m teams.push_chat --last-minutes 30
    python -m teams.push_chat --dry-run            # don't write anything

Exit codes
    0 — done (even if no messages found)
    2 — fatal config error (missing IndexedDB etc.)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import socket
import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt
from dotenv import load_dotenv

_HERE = Path(__file__).parent.parent
load_dotenv(_HERE / ".env", override=True)

sys.path.insert(0, str(_HERE))

from teams import reader, store  # noqa: E402


LOCAL_OUT_DIR = _HERE / "data" / "teams" / "chat-pushes"


def _dev_name() -> str:
    raw = (os.environ.get("NUCLEUS_DEV_NAME") or "").strip()
    if raw:
        return raw
    return (os.environ.get("USERNAME") or os.environ.get("USER")
            or socket.gethostname() or "unknown").strip()


def _central_chat_dir() -> Path | None:
    raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    if not raw:
        return None
    day = dt.date.today().strftime("%Y-%m-%d")
    return Path(raw) / _dev_name() / day / "chat"


def _build_docx(out_path: Path,
                start_dt: dt.datetime, end_dt: dt.datetime,
                chat_blocks: list[dict]) -> None:
    """One Word doc, one heading per chat, message lines inside."""
    doc = Document()

    title = doc.add_heading("Teams chat push", level=0)
    sub = doc.add_paragraph()
    sub.add_run(
        f"Dev: {_dev_name()}    "
        f"Window: {start_dt:%Y-%m-%d %H:%M} -> {end_dt:%H:%M}    "
        f"Chats: {len(chat_blocks)}    "
        f"Host: {socket.gethostname()}"
    ).italic = True

    for blk in chat_blocks:
        title_str = (
            f"{blk['title']} (chat #{blk['chat_number']})"
            if blk.get("chat_number")
            else blk["title"]
        )
        doc.add_heading(title_str, level=1)
        info = doc.add_paragraph()
        info_run = info.add_run(
            f"Conversation: {blk['cid']}   "
            f"Msgs: {len(blk['msgs'])}   "
            f"Senders: {', '.join(blk['senders'])}"
        )
        info_run.font.size = Pt(9)
        info_run.italic = True

        for m in blk["msgs"]:
            ts = dt.datetime.fromtimestamp((m.get("arrival_ms") or 0) / 1000)
            sender = m.get("sender_name") or "(unknown)"
            body = (m.get("body") or "").strip()
            if not body:
                continue
            p = doc.add_paragraph()
            p.add_run(f"[{ts:%H:%M}] {sender}: ").bold = True
            p.add_run(body)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--last-minutes", type=int, default=15,
                    help="Window size. Default: 15.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Read + summarize but write nothing.")
    args = ap.parse_args()

    if args.last_minutes <= 0:
        print("--last-minutes must be > 0", file=sys.stderr)
        return 1

    end_dt = dt.datetime.now()
    start_dt = end_dt - dt.timedelta(minutes=args.last_minutes)
    from_ms = int(start_dt.timestamp() * 1000)
    to_ms = int(end_dt.timestamp() * 1000)

    print(f"[push_chat] dev={_dev_name()} host={socket.gethostname()}")
    print(f"[push_chat] window: {start_dt:%Y-%m-%d %H:%M} -> {end_dt:%H:%M}")

    rows = store.list_chat_registry(order="activity")
    if not rows:
        print("[push_chat] chat registry empty. "
              "Run `python -m teams.list_chats` first.", file=sys.stderr)
        return 2
    # store.list_chat_registry returns sqlite3.Row; flatten to plain dicts
    # so .get() works downstream (Row only supports __getitem__).
    chat_lookup: dict[str, dict] = {
        r["conversation_id"]: {
            "title": r["title"],
            "chat_number": r["chat_number"],
        }
        for r in rows
    }

    cids = set(chat_lookup.keys())
    grouped = reader.read_messages_by_conversations(cids, since_ms=from_ms)

    chat_blocks: list[dict] = []
    total_msgs = 0
    for cid, msgs in grouped.items():
        windowed = [m for m in msgs
                    if from_ms <= (m.get("arrival_ms") or 0) <= to_ms
                    and (m.get("body") or "").strip()]
        if not windowed:
            continue
        senders = sorted({m.get("sender_name") or "(unknown)" for m in windowed})
        info = chat_lookup.get(cid, {})
        chat_no = info.get("chat_number")
        title = info.get("title") or (
            f"(chat #{chat_no})" if chat_no else "(untitled)")
        chat_blocks.append({
            "cid": cid,
            "title": title,
            "chat_number": chat_no,
            "msgs": windowed,
            "senders": senders,
        })
        total_msgs += len(windowed)

    if not chat_blocks:
        print(f"[push_chat] no messages in window across "
              f"{len(cids)} chats. Nothing to push.")
        return 0

    print(f"[push_chat] {len(chat_blocks)} chat(s) with {total_msgs} msg(s) total")

    name = (
        f"chat_{start_dt:%Y-%m-%d}_"
        f"{start_dt:%H%M}-{end_dt:%H%M}.docx"
    )

    if args.dry_run:
        print(f"[push_chat] dry-run: would write {name}")
        for blk in chat_blocks:
            print(f"   + {blk['title']}  ({len(blk['msgs'])} msg)")
        return 0

    local_path = LOCAL_OUT_DIR / name
    _build_docx(local_path, start_dt, end_dt, chat_blocks)
    size_kb = local_path.stat().st_size / 1024
    print(f"[push_chat] local: {local_path}  ({size_kb:.1f} KB)")

    central_dir = _central_chat_dir()
    if central_dir is None:
        print("[push_chat] central upload: skipped "
              "(NUCLEUS_CENTRAL_PATH not set)")
        return 0
    try:
        central_dir.mkdir(parents=True, exist_ok=True)
        dst = central_dir / name
        shutil.copy2(str(local_path), str(dst))
        print(f"[push_chat] -> {dst}")
        print("[push_chat] central upload: OK")
    except Exception as e:
        print(f"[push_chat] central upload FAILED: {e}", file=sys.stderr)
        print(f"[push_chat] local copy preserved at {local_path}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
