"""
Drive → Whisper → inbox pipeline.

Lists audio files in the configured Google Drive folder, downloads any
that haven't been transcribed yet, sends each to Groq's Whisper API,
and writes the transcript to data/requirements/inbox/meetings/ with the
standard 4-line header preface so the existing LLM splitter picks it
up on the same workflow run.

Env vars:
    GOOGLE_SERVICE_ACCOUNT_JSON   JSON key for a service account that
                                  has at least Viewer on the folder.
    GDRIVE_AUDIO_FOLDER_ID        The Drive folder ID (from its URL).
    GROQ_API_KEY                  Groq API key, `api` scope.
    GROQ_WHISPER_MODEL            Optional. Defaults to
                                  whisper-large-v3-turbo (fastest tier).

State:
    data/requirements/drive-processed.json
        { "processed": [{"file_id": "...", "name": "...",
                         "transcribed_at": "...",
                         "transcript_path": "..."}] }
    Used as the idempotency key — a Drive file ID never gets
    transcribed twice.

Run standalone:
    py -3 audio_transcriber.py
    py -3 audio_transcriber.py --dry-run
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import mimetypes
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env")

logger = logging.getLogger(__name__)

MEETINGS_DIR = _HERE / "data" / "requirements" / "inbox" / "meetings"
STATE_PATH = _HERE / "data" / "requirements" / "drive-processed.json"

# Groq's Whisper endpoint is OpenAI-compatible. Turbo is 2-3x faster
# than large-v3 with only a small quality delta; good default for
# meeting audio. Override via GROQ_WHISPER_MODEL if needed.
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "whisper-large-v3-turbo"
GROQ_MAX_BYTES = 25 * 1024 * 1024  # 25 MB per Groq docs

AUDIO_MIME_PREFIXES = ("audio/", "video/")
AUDIO_EXT_FALLBACK = {".mp3", ".mp4", ".m4a", ".mpeg", ".mpga",
                      ".wav", ".webm", ".mkv", ".ogg", ".flac"}


# ───────────────────────── state helpers ──────────────────────────

def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"processed": []}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "processed" not in data:
            return {"processed": []}
        return data
    except Exception:
        return {"processed": []}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


def _already_processed(state: dict, file_id: str) -> bool:
    return any(e.get("file_id") == file_id for e in state.get("processed", []))


# ─────────────────────────── Drive ────────────────────────────────

def _drive_service():
    """Build a Drive v3 client from the JSON service-account key."""
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON not set")
    info = json.loads(raw)
    from google.oauth2 import service_account  # lazy import
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly",
                      "https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list_audio_files(drive, folder_id: str) -> list[dict]:
    """Return non-trashed children of the folder that look like audio/video."""
    q = f"'{folder_id}' in parents and trashed = false"
    files: list[dict] = []
    page_token = None
    while True:
        resp = drive.files().list(
            q=q,
            fields=("nextPageToken,"
                    " files(id, name, mimeType, size, createdTime)"),
            pageSize=100,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        for f in resp.get("files", []):
            mt = (f.get("mimeType") or "").lower()
            name = f.get("name") or ""
            ext = Path(name).suffix.lower()
            if mt.startswith(AUDIO_MIME_PREFIXES) or ext in AUDIO_EXT_FALLBACK:
                files.append(f)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def _download_file(drive, file_id: str, out_path: Path) -> None:
    """Stream-download a Drive file to disk."""
    from googleapiclient.http import MediaIoBaseDownload  # lazy
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024)
        done = False
        while not done:
            _status, done = downloader.next_chunk()


# ─────────────────────────── Groq ─────────────────────────────────

def _transcribe_via_groq(audio_path: Path) -> str:
    """POST the audio file to Groq's Whisper endpoint. Returns text."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")
    model = os.getenv("GROQ_WHISPER_MODEL") or DEFAULT_MODEL

    size = audio_path.stat().st_size
    if size > GROQ_MAX_BYTES:
        raise RuntimeError(
            f"{audio_path.name} is {size / 1e6:.1f} MB — exceeds Groq's "
            f"{GROQ_MAX_BYTES / 1e6:.0f} MB limit. Shorten the recording "
            f"or split the file before uploading to Drive."
        )

    mime = mimetypes.guess_type(str(audio_path))[0] or "application/octet-stream"
    with open(audio_path, "rb") as f:
        files = {"file": (audio_path.name, f, mime)}
        data = {
            "model": model,
            # Leaving language empty lets Whisper auto-detect.
            # Whisper's Bangla recognition is strong, and the downstream
            # LLM splitter already forces English output.
            "response_format": "text",
        }
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files=files, data=data,
            timeout=600,  # 10 min — a long meeting can take a while
        )
    if not r.ok:
        raise RuntimeError(f"Groq transcription failed {r.status_code}: "
                           f"{r.text[:400]}")
    # response_format=text returns raw text body, not JSON.
    return r.text.strip()


# ─────────────────────────── Main ─────────────────────────────────

def _preface(file: dict, lang_hint: str = "") -> str:
    return (
        f"# source: meetings\n"
        f"# from: drive:{file.get('id')}\n"
        f"# received: {file.get('createdTime') or datetime.now(timezone.utc).isoformat()}\n"
        f"# subject: {file.get('name')}\n\n"
    )


def _safe_filename(original: str) -> str:
    stem = Path(original).stem
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in stem).strip("-")
    date = datetime.now().strftime("%Y-%m-%d")
    return f"{date}-{safe or 'audio'}.txt"


def transcribe_new_audio(dry_run: bool = False) -> dict:
    folder_id = os.getenv("GDRIVE_AUDIO_FOLDER_ID")
    if not folder_id:
        return {"error": "GDRIVE_AUDIO_FOLDER_ID not set",
                "transcribed": 0, "files": []}

    drive = _drive_service()
    listed = _list_audio_files(drive, folder_id)
    logger.info(f"Drive folder {folder_id}: found {len(listed)} audio file(s)")

    state = _load_state()
    pending = [f for f in listed if not _already_processed(state, f["id"])]
    if not pending:
        return {"transcribed": 0, "files": [], "skipped_already_done": len(listed)}

    MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = _HERE / "data" / "requirements" / "_audio_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for f in pending:
        fid = f["id"]
        name = f["name"]
        tmp_path = tmp_dir / f"{fid}-{Path(name).name}"
        logger.info(f"downloading {name} (id={fid}, {int(f.get('size') or 0)/1e6:.1f} MB)")
        try:
            _download_file(drive, fid, tmp_path)
        except Exception as e:
            logger.exception(f"download failed for {name}")
            results.append({"file": name, "id": fid, "error": f"download: {e}"})
            continue

        if dry_run:
            logger.info(f"[dry-run] would transcribe {name}")
            results.append({"file": name, "id": fid, "dry_run": True})
            try:
                tmp_path.unlink()
            except Exception:
                pass
            continue

        try:
            logger.info(f"transcribing {name} via Groq Whisper...")
            transcript_text = _transcribe_via_groq(tmp_path)
        except Exception as e:
            logger.exception(f"transcription failed for {name}")
            results.append({"file": name, "id": fid, "error": f"groq: {e}"})
            try:
                tmp_path.unlink()
            except Exception:
                pass
            continue

        out_name = _safe_filename(name)
        out_path = MEETINGS_DIR / out_name
        # If same name would collide (rare), suffix with the fid slug.
        if out_path.exists():
            out_path = MEETINGS_DIR / f"{out_path.stem}-{fid[:6]}.txt"
        out_path.write_text(_preface(f) + transcript_text, encoding="utf-8")
        logger.info(f"wrote transcript -> {out_path.name}")

        state["processed"].append({
            "file_id": fid,
            "name": name,
            "transcribed_at": datetime.now(timezone.utc).isoformat(),
            "transcript_path": str(out_path.relative_to(_HERE).as_posix()),
        })
        _save_state(state)

        try:
            tmp_path.unlink()
        except Exception:
            pass

        results.append({
            "file": name,
            "id": fid,
            "transcript": str(out_path.relative_to(_HERE).as_posix()),
            "chars": len(transcript_text),
        })

    return {
        "transcribed": sum(1 for r in results if "transcript" in r),
        "errors": sum(1 for r in results if "error" in r),
        "files": results,
    }


def _cli() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="List + download pending files but do not call Groq.")
    args = p.parse_args()
    out = transcribe_new_audio(dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    if out.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    _cli()
