"""Aggregate every dev's central uploads for one (client, day) and identify.

Runs on the agent host (MVPACCESS) where Claude is authenticated. Walks
the central tree at NUCLEUS_CENTRAL_PATH, picks up every dev's call
recordings + chat docs for the chosen day, filters calls by client
(via the metadata.client_name written by record_call), builds ONE
unified session doc, then runs `agent.py --task verify_session` to
identify requirements + draft a client email.

This is the answer to the fragmented-conversation problem: Client A
talks to Dev 1 for 2 min about half a feature, then to Dev 3 for 4 min
about the other half. Each dev's local NN sees only their fragment;
collect_central sees both and stitches them.

Layout it expects (created by the per-dev push):

    <NUCLEUS_CENTRAL_PATH>/
      <dev>/
        <YYYY-MM-DD>/
          calls/<stamp>_mic.wav  <stamp>_speaker.wav  <stamp>.json
          chat/chat_<YYYY-MM-DD>_<HHMM>-<HHMM>.docx
          chat/attachments/<filename>     (files shared in Teams chat
                                           that the dev has downloaded
                                           locally; pushed by push_chat)
          chat/attachments/manifest.json  (URL -> {name, size, stored_as})

In addition to the per-dev push, collect_central also pulls EMAIL and
GOOGLE DRIVE locally on the agent host (so the unified session doc has
every requirement source, not just chat + calls from dev machines).
Both pulls run against the time window controlled by --last-minutes.

Usage
    python collect_central.py --client "Susmoy"
    python collect_central.py --client "all" --day 2026-05-08
    python collect_central.py --client "Acme" --no-identify     # aggregate only
    python collect_central.py --client "Acme" --dry-run         # plan only
    python collect_central.py --client "Acme" --last-minutes 30 # widen window
    python collect_central.py --client "Acme" --no-email        # skip email pull
    python collect_central.py --client "Acme" --no-drive        # skip Drive pull

Env
    NUCLEUS_CENTRAL_PATH   required (UNC or local path to the central root)
    VERIFICATION_TO        recipient for the verification email; must be set
                           if --no-identify is NOT passed.
    REQ_IMAP_*             needed for the email pull (skip via --no-email)
    GOOGLE_CREDENTIALS_PATH / GDRIVE_AUDIO_FOLDER_ID  needed for the
                           Drive pull (skip via --no-drive)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env", override=True)

sys.path.insert(0, str(_HERE))

from tools import _session_doc as session_doc  # noqa: E402


def _client_match(metadata: dict, target: str) -> bool:
    if target.lower() == "all":
        return True
    needle = target.strip().lower()
    if not needle:
        return True
    primary = (metadata.get("client_name") or "").lower()
    if needle in primary:
        return True
    info = metadata.get("client_info") or {}
    for c in info.get("clients") or []:
        nm = (c.get("name") or "").lower()
        ident = (c.get("identity") or "").lower()
        if needle in nm or needle in ident:
            return True
    return False


_ATTACHMENT_EXT_KIND = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "doc",
    ".txt": "txt",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".xls": "xls",
}


def _scan_central(central: Path, day: str, client: str) -> dict:
    """Walk central/<dev>/<day>/ and bucket by source. Returns dict with
    'calls', 'chats', and 'attachments' lists."""
    calls: list[dict] = []
    chats: list[dict] = []
    attachments: list[dict] = []

    if not central.exists():
        raise RuntimeError(f"central path does not exist: {central}")

    for dev_dir in sorted(central.iterdir()):
        if not dev_dir.is_dir():
            continue
        day_dir = dev_dir / day
        if not day_dir.exists():
            continue

        calls_dir = day_dir / "calls"
        if calls_dir.exists():
            for meta_path in sorted(calls_dir.glob("*.json")):
                try:
                    metadata = json.loads(
                        meta_path.read_text(encoding="utf-8-sig"))
                except Exception as e:
                    print(f"  WARN: skipping {meta_path}: {e}",
                          file=sys.stderr)
                    continue
                if not _client_match(metadata, client):
                    continue
                stamp = metadata.get("session") or meta_path.stem
                mic = calls_dir / f"{stamp}_mic.wav"
                spk = calls_dir / f"{stamp}_speaker.wav"
                calls.append({
                    "dev": dev_dir.name,
                    "stamp": stamp,
                    "metadata": metadata,
                    "mic_path": mic if mic.exists() else None,
                    "speaker_path": spk if spk.exists() else None,
                })

        chat_dir = day_dir / "chat"
        if chat_dir.exists():
            for doc_path in sorted(chat_dir.glob("*.docx")):
                chats.append({"dev": dev_dir.name, "path": doc_path})

            att_dir = chat_dir / "attachments"
            if att_dir.exists():
                for f in sorted(att_dir.iterdir()):
                    if not f.is_file() or f.name == "manifest.json":
                        continue
                    kind = _ATTACHMENT_EXT_KIND.get(f.suffix.lower())
                    if not kind:
                        continue  # skip images, audio, video, archives, etc.
                    attachments.append({
                        "dev": dev_dir.name,
                        "path": f,
                        "kind": kind,
                    })

    return {"calls": calls, "chats": chats, "attachments": attachments}


def _extract_attachment_text(path: Path, kind: str) -> str:
    """Dispatch to the same extractors drive/mail use."""
    from drive import drive_ingester as di  # lazy
    if kind == "pdf":
        return di._extract_pdf_text(path)
    if kind == "docx":
        return di._extract_docx_text(path)
    if kind == "doc":
        return di._extract_doc_text(path)
    if kind == "txt":
        return di._extract_txt_text(path)
    if kind == "xlsx":
        return di._extract_xlsx_text(path)
    if kind == "xls":
        return di._extract_xls_text(path)
    return ""


def _transcribe_call(mic: Path | None, speaker: Path | None,
                     stamp: str) -> list[str]:
    """Return body lines for the MEETING section. Uses faster-whisper
    large-v3, Bangla -> English translate (matches pull_meeting.py).
    Falls back to a placeholder line if Whisper isn't available."""
    if not mic and not speaker:
        return ["(both tracks missing)"]
    try:
        from faster_whisper import WhisperModel  # lazy
    except ImportError:
        return [f"(faster-whisper not installed; raw WAVs at {mic} / {speaker})"]

    model = WhisperModel("large-v3", device="cpu", compute_type="int8")

    try:
        started = dt.datetime.strptime(stamp, "%Y%m%d-%H%M%S")
    except ValueError:
        started = None

    all_segs: list[dict] = []
    for wav, label in [(mic, "You"), (speaker, "Other")]:
        if not wav:
            continue
        segments, info = model.transcribe(
            str(wav), task="translate", language="bn",
            beam_size=1, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        for s in segments:
            text = s.text.strip()
            if text:
                all_segs.append({
                    "start": s.start, "end": s.end,
                    "text": text, "speaker": label,
                })
    all_segs.sort(key=lambda s: s["start"])

    lines: list[str] = []
    if not all_segs:
        return ["(no speech detected on either track)"]
    for s in all_segs:
        if started:
            ts = (started + dt.timedelta(seconds=s["start"])).strftime("%H:%M:%S")
            lines.append(f"[{ts}] {s['speaker']}: {s['text']}")
        else:
            lines.append(f"[+{int(s['start']):04d}s] {s['speaker']}: {s['text']}")
    return lines


def _read_chat_docx_lines(path: Path) -> list[str]:
    """Pull paragraph lines from a chat .docx in order; skip the title.
    Returns the body text intact (Heading 1 entries become section
    markers: '--- chat: <title> ---')."""
    from docx import Document  # lazy
    doc = Document(str(path))
    lines: list[str] = []
    for p in doc.paragraphs:
        style = p.style.name if p.style else ""
        text = p.text.strip()
        if not text:
            continue
        if style.startswith("Heading 1"):
            lines.append(f"--- chat: {text} ---")
        elif style.startswith("Heading"):
            continue  # skip the document title
        else:
            lines.append(text)
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client", required=True,
                    help="Client display name to scope to. Substring match "
                         "against metadata.client_name + each participant's "
                         "name. Use 'all' to skip filtering.")
    ap.add_argument("--day", default=None,
                    help="YYYY-MM-DD. Default: today (local time).")
    ap.add_argument("--no-reset", dest="reset", action="store_false",
                    help="Append to the existing session doc instead of "
                         "starting a fresh one. Default: reset.")
    ap.set_defaults(reset=True)
    ap.add_argument("--no-identify", dest="identify", action="store_false",
                    help="Aggregate into the session doc but skip the "
                         "identify + draft step. Useful for inspecting "
                         "what got pulled before paying for an LLM run.")
    ap.set_defaults(identify=True)
    ap.add_argument("--last-minutes", type=int, default=15,
                    help="Time window (minutes) for the email + Drive "
                         "pulls. Default: 15.")
    ap.add_argument("--no-email", dest="pull_email", action="store_false",
                    help="Skip pulling email from IMAP.")
    ap.set_defaults(pull_email=True)
    ap.add_argument("--no-drive", dest="pull_drive", action="store_false",
                    help="Skip pulling files from Google Drive.")
    ap.set_defaults(pull_drive=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="List what would be pulled but don't read WAVs, "
                         "transcribe, or write the session doc.")
    args = ap.parse_args()

    central_raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    if not central_raw:
        print("NUCLEUS_CENTRAL_PATH is not set. "
              "Add it to .env and re-run.", file=sys.stderr)
        return 2
    central = Path(central_raw)

    day = args.day or dt.date.today().strftime("%Y-%m-%d")

    print(f"\n*** collect_central: client={args.client!r}  day={day} ***")
    print(f"central: {central}")
    bundle = _scan_central(central, day, args.client)
    n_calls = len(bundle["calls"])
    n_chats = len(bundle["chats"])
    n_atts = len(bundle["attachments"])
    print(f"matched: {n_calls} call(s), {n_chats} chat doc(s), "
          f"{n_atts} chat attachment(s)")

    if n_calls == 0 and n_chats == 0 and n_atts == 0:
        print("Nothing matched. Either no captures yet today, or the client "
              "filter doesn't match anything. Try --client all to inspect.")
        return 0

    print()
    for c in bundle["calls"]:
        md = c["metadata"]
        print(f"  CALL  {c['dev']}/{c['stamp']}  client='{md.get('client_name')}'  "
              f"dur={md.get('duration_seconds', '?')}s")
    for c in bundle["chats"]:
        print(f"  CHAT  {c['dev']}/{c['path'].name}")
    for a in bundle["attachments"]:
        print(f"  ATT   {a['dev']}/{a['path'].name}  ({a['kind']})")

    if args.dry_run:
        print("\n[dry-run] no writes. Done.")
        return 0

    if args.reset:
        result = session_doc.reset(
            label=f"central-{args.client.replace(' ', '-')}-{day}")
        print(f"\nSession reset: {result['session_path']} "
              f"(label '{result['new_label']}')")

    # ── Email + Drive: pull fresh on the agent host so the unified ──
    # session doc has every source, not only what's on central. These
    # are global sources (one mailbox, one Drive folder) so they run
    # once here regardless of --client.
    if args.pull_email:
        print(f"\n=== EMAIL — last {args.last_minutes} min ===")
        rc = subprocess.call(
            [sys.executable, "-m", "mail.pull_email",
             "--last-minutes", str(args.last_minutes)],
            cwd=str(_HERE),
        )
        if rc != 0:
            print(f"  ! email pull exit code {rc} — continuing",
                  file=sys.stderr)

    if args.pull_drive:
        print(f"\n=== GOOGLE DRIVE — last {args.last_minutes} min ===")
        rc = subprocess.call(
            [sys.executable, "-m", "drive.pull_drive",
             "--last-minutes", str(args.last_minutes)],
            cwd=str(_HERE),
        )
        if rc != 0:
            print(f"  ! drive pull exit code {rc} — continuing",
                  file=sys.stderr)

    # ── Append calls (each one is one MEETING section) ────────────
    for c in bundle["calls"]:
        md = c["metadata"]
        stamp = c["stamp"]
        print(f"\n--- transcribing {c['dev']}/{stamp} ({md.get('client_name')}) ---")
        body_lines = [
            f"Source: {c['dev']}",
            f"Started: {md.get('started_at')}",
            f"Duration: {md.get('duration_seconds')}s",
            f"Call ID: {(md.get('client_info') or {}).get('call_id', '')}",
            f"Call type: {(md.get('client_info') or {}).get('call_type', '')}",
            f"Participants: " + ", ".join(
                p.get("name", "?")
                for p in (md.get("client_info") or {}).get("participants", [])
            ),
            "",
        ]
        body_lines += _transcribe_call(
            c["mic_path"], c["speaker_path"], stamp)

        session_doc.append_section(
            source="MEETING",
            headline=f"{c['dev']} <-> {md.get('client_name')}  ({stamp})",
            metadata={
                "Source dev": c["dev"],
                "Started": str(md.get("started_at", "")),
                "Duration": f"{md.get('duration_seconds', '?')}s",
                "Client": str(md.get("client_name", "")),
            },
            body_paragraphs=body_lines,
        )

    # ── Append chat docs (each one becomes one TEAMS CHAT section) ─
    for c in bundle["chats"]:
        try:
            lines = _read_chat_docx_lines(c["path"])
        except Exception as e:
            print(f"  WARN: couldn't read {c['path']}: {e}", file=sys.stderr)
            continue
        m = re.search(r"chat_(\d{4}-\d{2}-\d{2})_(\d{4})-(\d{4})", c["path"].stem)
        win = (f"{m.group(1)} {m.group(2)[:2]}:{m.group(2)[2:]}"
               f"-{m.group(3)[:2]}:{m.group(3)[2:]}") if m else c["path"].stem
        session_doc.append_section(
            source="TEAMS CHAT",
            headline=f"{c['dev']}  ({win})",
            metadata={
                "Source dev": c["dev"],
                "Window": win,
                "File": c["path"].name,
            },
            body_paragraphs=lines or ["(empty .docx)"],
        )

    # ── Append Teams chat attachments (one TEAMS ATTACHMENT section each) ─
    for a in bundle["attachments"]:
        path = a["path"]
        kind = a["kind"]
        print(f"\n--- extracting attachment {a['dev']}/{path.name} ({kind}) ---")
        try:
            text = _extract_attachment_text(path, kind)
        except Exception as e:
            print(f"  WARN: extraction failed for {path}: {e}", file=sys.stderr)
            text = f"(extraction failed: {e})"
        body_lines = [ln for ln in (text or "").splitlines() if ln.strip()] \
                     or ["(no text extracted)"]
        try:
            size_kb = path.stat().st_size / 1024
        except OSError:
            size_kb = 0
        session_doc.append_section(
            source="TEAMS ATTACHMENT",
            headline=f"{a['dev']}  ({path.name})",
            metadata={
                "Source dev": a["dev"],
                "File": path.name,
                "Type": kind,
                "Size KB": f"{size_kb:.1f}",
            },
            body_paragraphs=body_lines,
        )

    print(f"\nSession doc updated. Path: "
          f"{session_doc.SESSION_PATH.relative_to(_HERE).as_posix()}")

    if not args.identify:
        print("\n--no-identify: stopping before LLM step.")
        return 0

    if not os.environ.get("VERIFICATION_TO"):
        print("\nVERIFICATION_TO not set in .env. Identify step needs a "
              "client recipient.", file=sys.stderr)
        return 2

    print("\n=== running verify_session (identify + draft) ===")
    rc = subprocess.call(
        [sys.executable, "agent.py", "--task", "verify_session"],
        cwd=str(_HERE),
    )
    print(f"\nverify_session exit code: {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
