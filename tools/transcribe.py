"""
NAPCO Nucleus — Bangla→English call transcription via faster-whisper.

One MCP tool:

    transcribe_call_audio   Transcribe a recorded Teams call (mic + speaker
                            WAV pair) to chat-style English markdown.

Reads WAVs from data/requirements/inbox/audio/ and writes a transcript
to data/requirements/inbox/meetings/. The audio capture itself is done
manually (e.g. via Teams-Requirement-Watcher's record_call.py) — NN
only handles the transcription leg.

`language="bn"` is hard-set on every transcribe call so neither the
mic nor speaker file gets mis-detected as Hindi (the symptom we saw
2026-05-05 with auto-detection: "Login page" → "Loaning place").
`task="translate"` produces English output regardless of source.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
from pathlib import Path

from claude_agent_sdk import tool

import memory

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent.parent
_AUDIO_INBOX = _HERE / "data" / "requirements" / "inbox" / "audio"
_MEETINGS_INBOX = _HERE / "data" / "requirements" / "inbox" / "meetings"

_MODEL_NAME = os.environ.get("WHISPER_MODEL", "large-v3")
_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")


def _text(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


def _find_latest_session(audio_dir: Path) -> str | None:
    sessions = sorted({p.name.split("_")[0] for p in audio_dir.glob("*_mic.wav")})
    if not sessions:
        sessions = sorted({p.name.split("_")[0] for p in audio_dir.glob("*_speaker.wav")})
    return sessions[-1] if sessions else None


def _resolve_files(session_or_path: str | None) -> tuple[str, list[Path]]:
    """Return (session_label, [wav files]) for the given arg.

    - None: use newest session in _AUDIO_INBOX
    - "20260505-203305": match _AUDIO_INBOX/20260505-203305_*.wav
    - absolute path to a .wav: single-file transcription
    """
    if session_or_path:
        p = Path(session_or_path)
        if p.is_file() and p.suffix.lower() == ".wav":
            return p.stem.split("_")[0], [p]
        files = sorted(_AUDIO_INBOX.glob(f"{session_or_path}_*.wav"))
        if files:
            return session_or_path, files
        raise FileNotFoundError(
            f"No WAVs match session '{session_or_path}' in {_AUDIO_INBOX}"
        )

    session = _find_latest_session(_AUDIO_INBOX)
    if not session:
        raise FileNotFoundError(
            f"No *_mic.wav or *_speaker.wav files found in {_AUDIO_INBOX}. "
            f"Drop a Teams call recording there first."
        )
    files = sorted(_AUDIO_INBOX.glob(f"{session}_*.wav"))
    return session, files


def _transcribe_one(model, wav: Path, label: str) -> list[dict]:
    """Transcribe one WAV with language=bn forced. Returns list of segments."""
    segments, info = model.transcribe(
        str(wav),
        task="translate",
        language="bn",
        beam_size=1,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    logger.info(f"  [{label}] detected={info.language!r} ({info.language_probability:.2f})")
    out: list[dict] = []
    for s in segments:
        text = s.text.strip()
        if text:
            out.append({"start": s.start, "end": s.end, "text": text, "speaker": label})
    return out


# ─── transcribe_call_audio ──────────────────────────────────────────

@tool(
    "transcribe_call_audio",
    "Transcribe a recorded Teams call to chat-style English markdown. "
    "Pairs mic + speaker WAVs from data/requirements/inbox/audio/ and "
    "produces ONE merged transcript at data/requirements/inbox/meetings/"
    "transcript-<session>.md. Forces language='bn' (Bangla source) and "
    "task='translate' (English output). Args: `session` — explicit "
    "session prefix like '20260505-203305' OR absolute .wav path; if "
    "omitted, the newest *_mic.wav in inbox/audio is used. Returns "
    "{path, session, segment_count, file_count}. Long calls take ~1.5x "
    "real-time on CPU (60-min call → ~90-min transcribe).",
    {"session": str},
)
async def transcribe_call_audio_tool(args):
    session_arg = (args.get("session") or "").strip() or None

    try:
        session, files = _resolve_files(session_arg)
    except FileNotFoundError as e:
        return _text({"error": str(e)})

    try:
        from faster_whisper import WhisperModel  # lazy
    except ImportError as e:
        return _text({
            "error": "faster-whisper not installed. pip install faster-whisper",
            "detail": str(e),
        })

    try:
        started = datetime.datetime.strptime(session, "%Y%m%d-%H%M%S")
    except ValueError:
        started = datetime.datetime.now()

    logger.info(
        f"Loading Whisper {_MODEL_NAME} ({_DEVICE}/{_COMPUTE_TYPE}) "
        f"for session {session} ({len(files)} files)"
    )
    model = WhisperModel(_MODEL_NAME, device=_DEVICE, compute_type=_COMPUTE_TYPE)

    all_segs: list[dict] = []
    for wav in files:
        label = "You" if wav.stem.endswith("_mic") else "Other"
        try:
            all_segs.extend(_transcribe_one(model, wav, label))
        except Exception as e:
            logger.exception(f"transcribe {wav.name} failed")
            memory.log_activity(
                task_name="requirement-collection:transcribe",
                result=f"error:{type(e).__name__}",
                technical_details={"file": str(wav), "error": str(e)},
            )
            return _text({"error": f"{type(e).__name__}: {e}", "file": str(wav)})

    all_segs.sort(key=lambda s: s["start"])

    _MEETINGS_INBOX.mkdir(parents=True, exist_ok=True)
    out = _MEETINGS_INBOX / f"transcript-{session}.md"

    with out.open("w", encoding="utf-8") as f:
        f.write(f"# Call transcript — {session}\n\n")
        f.write(f"_Started_: {started:%Y-%m-%d %H:%M}  \n")
        f.write(f"_Source_: {', '.join(w.name for w in files)}  \n")
        f.write(f"_Translated to English by faster-whisper {_MODEL_NAME} (language=bn, task=translate)_\n\n")
        f.write("---\n\n")
        for s in all_segs:
            ts = started + datetime.timedelta(seconds=s["start"])
            f.write(f"**{s['speaker']} [{ts:%d-%m-%Y %I:%M %p}]:**  \n")
            f.write(f"> {s['text']}\n\n")

    memory.log_activity(
        task_name="requirement-collection:transcribe",
        result=f"session={session} segments={len(all_segs)}",
        technical_details={
            "session": session,
            "files": [str(w) for w in files],
            "segment_count": len(all_segs),
            "path": str(out),
        },
    )

    return _text({
        "path": str(out.relative_to(_HERE).as_posix()),
        "absolute_path": str(out),
        "session": session,
        "segment_count": len(all_segs),
        "file_count": len(files),
        "files_processed": [w.name for w in files],
    })


TOOLS = [transcribe_call_audio_tool]
TOOL_NAMES = ["transcribe_call_audio"]
