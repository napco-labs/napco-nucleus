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
    # Image OCR — extracted to text via Tesseract if available, else
    # a placeholder pointing the reviewer at the file.
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".bmp": "image",
    ".tiff": "image",
    ".tif": "image",
}


def _call_track(calls_dir: Path, stamp: str, kind: str) -> Path | None:
    """Find a call track by either extension — Opus (compressed) preferred,
    then legacy WAV. Without this, compressed calls resolve to no audio path
    and _transcribe_call returns '(both tracks missing)' → zero requirements."""
    for ext in (".opus", ".wav"):
        p = calls_dir / f"{stamp}_{kind}{ext}"
        if p.exists():
            return p
    return None


def _scan_central(central: Path, days, client: str, calls_within: int = 0) -> dict:
    """Walk central/<dev>/<day>/ for each day and bucket by source.

    `days` may be a single date string or a list of strings. The
    auto-fire path passes [today, yesterday] so calls that straddled
    midnight (started before midnight, finished after) and live in
    yesterday's folder still get picked up. Memory dedup
    (`requirements_seen`) prevents double-drafting on subsequent runs.

    Returns dict with 'calls', 'chats', and 'attachments' lists.
    """
    if isinstance(days, str):
        days = [days]

    calls: list[dict] = []
    chats: list[dict] = []
    attachments: list[dict] = []

    if not central.exists():
        raise RuntimeError(f"central path does not exist: {central}")

    for dev_dir in sorted(central.iterdir()):
        if not dev_dir.is_dir():
            continue
        for day in days:
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
                    # Per-call (event) runs scope to FRESHLY-transcribed calls so
                    # we don't re-run Google STT over the whole day on every
                    # trigger. Keyed on the transcript mtime (just written by the
                    # transcribe loop), so the call's length doesn't matter.
                    if calls_within > 0:
                        ref = calls_dir / f"{stamp}_transcript.md"
                        ts = ref if ref.exists() else meta_path
                        age_min = (dt.datetime.now().timestamp()
                                   - ts.stat().st_mtime) / 60.0
                        if age_min > calls_within:
                            continue
                    calls.append({
                        "dev": dev_dir.name,
                        "stamp": stamp,
                        "metadata": metadata,
                        "mic_path": _call_track(calls_dir, stamp, "mic"),
                        "speaker_path": _call_track(calls_dir, stamp, "speaker"),
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
    if kind == "image":
        return _extract_image_text(path)
    return ""


def _extract_image_text(path: Path) -> str:
    """OCR an image attachment (screenshots dropped in Teams chat).

    Uses Tesseract via pytesseract if available. Tesseract is a system
    binary, not a pip package — install:

      Windows:  winget install --id UB-Mannheim.TesseractOCR
                (or download from
                https://github.com/UB-Mannheim/tesseract/wiki)
      Plus the Bangla language pack for Bangla-text screenshots.

    If pytesseract or the binary is missing, returns a placeholder
    pointing the reviewer at the file — the pipeline continues, the
    LLM identifier just sees less detail for image inputs.
    """
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError:
        return (
            f"(image attachment {path.name} not OCR'd — install "
            f"pytesseract + Pillow + Tesseract OCR to enable. "
            f"Reviewer should open {path} manually if it matters.)"
        )
    try:
        img = Image.open(str(path))
    except Exception as e:
        return f"(could not open image {path.name}: {e})"

    # Try Bangla + English first (most common case for NAPCO). Fall
    # back to English-only if the Bangla traineddata isn't installed.
    for lang in ("ben+eng", "eng"):
        try:
            text = pytesseract.image_to_string(img, lang=lang)
        except pytesseract.TesseractError as e:
            if "Failed loading language" in str(e) and lang != "eng":
                continue
            return (f"(Tesseract failed on {path.name}: {e}. "
                    f"Reviewer should open the image manually.)")
        except Exception as e:
            return f"(OCR error on {path.name}: {e})"
        text = (text or "").strip()
        if not text:
            return f"(no readable text found in {path.name})"
        return f"[OCR via Tesseract, lang={lang}]\n{text}"
    return f"(OCR returned empty text for {path.name})"




def _segs_to_body_lines(all_segs: list[dict],
                        started: dt.datetime | None,
                        source_label: str = "Bangla") -> list[str]:
    """Render transcript segments as MEETING-section body lines.

    Renders Google STT segment dicts as MEETING-section body lines.
    source_label drives the header line so a reviewer knows what the
    session doc actually contains.
    """
    if not all_segs:
        return ["(no speech detected on either track)"]
    lines: list[str] = []
    if source_label == "Bangla":
        lines.append("Source language: Bangla (transcribed verbatim — Claude "
                     "translates to English at identify time).")
    else:
        lines.append(f"Source language: {source_label} (translated at "
                     f"capture time).")
    lines.append("Markers: (uncertain) = low ASR confidence, double-check "
                 "before relying on these lines.")
    lines.append("")
    uncertain_count = 0
    for s in all_segs:
        is_uncertain = bool(s.get("uncertain", False))
        if is_uncertain:
            uncertain_count += 1
        marker = "  (uncertain)" if is_uncertain else ""
        if started:
            ts = (started + dt.timedelta(seconds=s["start"])).strftime("%H:%M:%S")
            lines.append(f"[{ts}] {s['speaker']}{marker}: {s['text']}")
        else:
            lines.append(f"[+{int(s['start']):04d}s] {s['speaker']}{marker}: {s['text']}")
    if uncertain_count:
        lines.append("")
        lines.append(f"({uncertain_count} of {len(all_segs)} segments "
                     f"flagged uncertain — review before trusting those lines.)")
    return lines


def _transcribe_call(mic: Path | None, speaker: Path | None,
                     stamp: str) -> list[str]:
    """Return body lines for the MEETING section using Google STT."""
    if not mic and not speaker:
        return ["(both tracks missing)"]

    try:
        started = dt.datetime.strptime(stamp, "%Y%m%d-%H%M%S")
    except ValueError:
        started = None

    try:
        from tools.google_stt import google_transcribe  # lazy
        mic_segs = google_transcribe(mic, "You") if mic else []
        spk_segs = google_transcribe(speaker, "Other") if speaker else []
        all_segs = sorted(mic_segs + spk_segs, key=lambda s: s["start"])
        if all_segs:
            print(f"  transcribed via Google STT ({len(all_segs)} segments)")
            return _segs_to_body_lines(all_segs, started, source_label="Bangla")
        return ["(no speech detected in call audio)"]
    except Exception as e:
        print(f"  Google STT failed: {e}", file=sys.stderr)
        return ["(call audio could not be transcribed — "
                "requirements from this call may be missing)"]


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


_COVERAGE_DIR = _HERE / "data" / "requirements" / ".coverage"


def _write_coverage(day: str, calls: int, chats: int, atts: int,
                    verify_rc: int) -> None:
    """Record what this run collected + whether identify succeeded.

    daily_rollup reads this so it can tell a genuinely-quiet day (no
    sources) apart from a FAILED run (sources collected but the identify
    step errored or wrote no verification doc) — and shout in the email
    instead of sending a silent 'no requirements' notice (2026-06-17:
    Assad's Bangla calls were collected but the identify step bailed)."""
    _COVERAGE_DIR.mkdir(parents=True, exist_ok=True)
    doc = (_HERE / "data" / "requirements"
           / f"Requirements Verification {day}.docx")
    payload = {
        "day": day,
        "sources": {"calls": calls, "chats": chats, "attachments": atts},
        "verify_rc": verify_rc,
        "doc_exists": doc.exists(),
    }
    (_COVERAGE_DIR / f"{day}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
    ap.add_argument("--calls-within-minutes", type=int, default=0,
                    help="Only include calls transcribed within the last N "
                         "minutes (by transcript mtime). 0 = all calls for the "
                         "day. Used by the per-call event run so it (re)processes "
                         "ONLY the freshly-finished call, not the whole day.")
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

    if args.day:
        # User specified an exact day -- honor it literally.
        days_to_scan = [args.day]
        day_label = args.day
    else:
        # Auto-fire path: also scan yesterday's folder to catch calls
        # that started before midnight and ended after. Memory's
        # requirements_seen handles dedup if a real requirement spans
        # both scans on consecutive nightly runs.
        today = dt.date.today()
        yesterday = today - dt.timedelta(days=1)
        days_to_scan = [today.strftime("%Y-%m-%d"),
                        yesterday.strftime("%Y-%m-%d")]
        day_label = f"{days_to_scan[0]} (+ yesterday for midnight straddles)"

    print(f"\n*** collect_central: client={args.client!r}  day={day_label} ***")
    print(f"central: {central}")
    bundle = _scan_central(central, days_to_scan, args.client,
                           calls_within=args.calls_within_minutes)
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
        # Use the primary day (today, or whatever --day specified) for the
        # session label even when also scanning yesterday for straddles.
        primary_day = days_to_scan[0]
        result = session_doc.reset(
            label=f"central-{args.client.replace(' ', '-')}-{primary_day}")
        print(f"\nSession reset: {result['session_path']} "
              f"(label '{result['new_label']}')")

    # ── Email + Drive: pull fresh on the agent host so the unified ──
    # session doc has every source, not only what's on central. These
    # are global sources (one mailbox, one Drive folder) so they run
    # once here regardless of --client.
    if args.pull_email:
        print(f"\n=== EMAIL — last {args.last_minutes} min ===")
        try:
            rc = subprocess.call(
                [sys.executable, "-m", "mail.pull_email",
                 "--last-minutes", str(args.last_minutes)],
                cwd=str(_HERE),
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            print("  ! email pull exceeded 600s — abandoning, continuing",
                  file=sys.stderr)
            rc = 124
        if rc != 0:
            print(f"  ! email pull exit code {rc} — continuing",
                  file=sys.stderr)

    if args.pull_drive:
        print(f"\n=== GOOGLE DRIVE — last {args.last_minutes} min ===")
        try:
            rc = subprocess.call(
                [sys.executable, "-m", "drive.pull_drive",
                 "--last-minutes", str(args.last_minutes)],
                cwd=str(_HERE),
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            print("  ! drive pull exceeded 600s — abandoning, continuing",
                  file=sys.stderr)
            rc = 124
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
    try:
        rc = subprocess.call(
            [sys.executable, "agent.py", "--task", "verify_session"],
            cwd=str(_HERE),
            # 30 min cap on the Claude pass. A healthy run is 1-3 min;
            # a network hang or model stall must not pin the daily
            # cron forever (we got bitten by exactly this when the
            # Max OAuth token expired and the SDK retried for hours).
            timeout=1800,
        )
    except subprocess.TimeoutExpired:
        print("\nverify_session exceeded 30 min wall clock — aborting.",
              file=sys.stderr)
        return 124
    print(f"\nverify_session exit code: {rc}")
    # Propagate Claude failures (auth, network, model error). Previously
    # we returned rc unconditionally, but agent.py:236 returns 0 even on
    # API 401 -- the failure was invisible to the supervising loop until
    # 2026-05-21 morning, when we saw a week of empty Gmail Drafts.
    # Until that exit-code bug in agent.py is fixed too, we still trust
    # rc here; the daily-draft loop's new "skip rollup on non-zero rc"
    # guard catches the empty-output case from the other side.
    try:
        _write_coverage(days_to_scan[0], n_calls, n_chats, n_atts, rc)
    except Exception as e:
        print(f"  warn: could not write coverage signal: {e}",
              file=sys.stderr)
    return rc


def _main_with_lock() -> int:
    """Wrap main() in a cross-process file lock so the chat-push cron
    and an on-demand do_it_now invocation can't run collect_central
    simultaneously and corrupt session.docx / verification artifacts."""
    from tools._lock import file_lock  # lazy
    try:
        with file_lock("collect_central", block=False) as got:
            if not got:
                print("\n[lock] another collect_central run is in flight — "
                      "aborting to avoid duplicate writes.",
                      file=sys.stderr)
                return 75  # EX_TEMPFAIL
            return main()
    except RuntimeError as e:
        print(f"\n[lock] {e}", file=sys.stderr)
        return 75


if __name__ == "__main__":
    sys.exit(_main_with_lock())
