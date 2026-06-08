"""Transcribe a recorded call (mic + speaker WAVs) and translate to English.

Pairs the *_mic.wav and *_speaker.wav files written by record_call.py and
produces a single chat-style markdown with English text, regardless of
spoken language. Speaker labels: mic=You, speaker=Other.

Usage:
  python transcribe_call.py                    # latest session in data/calls/
  python transcribe_call.py 20260505-203305    # specific session prefix
  python transcribe_call.py path/to/file.wav   # one file (no merge)

Output: <MEETING_OUT_DIR>/<session>_transcript.md
        defaults to data/calls/<session>_transcript.md (TRW's own folder)

Set MEETING_OUT_DIR to redirect output. NAPCO Nucleus uses this to pull
transcripts into its own requirement-collection inbox without
duplicating TRW's transcribe logic:

    set MEETING_OUT_DIR=E:\\Projects\\NAPCO-Nucleus\\data\\requirements\\inbox\\meetings
    python transcribe_call.py

Library use (e.g. from tools/transcribe_calls.py running on the agent
host) calls transcribe_session() directly so the Whisper model can be
loaded once and reused across many sessions.
"""
from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

# NOTE: faster-whisper is NOT a project dependency anymore (removed 2026-06-08;
# call transcription is Google STT on central). This module is a standalone
# offline tool — it imports faster_whisper lazily in load_model() so the rest
# of the package (and the voice daemon) work without the package installed.

MODEL_NAME = "large-v3"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"

# Domain-specific primer — helps Whisper recognise NAPCO/AEL names and
# mixed Bangla-English technical vocabulary before it sees any audio.
INITIAL_PROMPT = (
    "NAPCO Security, MVP Access, AEL, Dashboard, OpenProject, HTS, DVR, Arcules. "
    "Titu, Assad, Rocky, Ferdows, Atik, Isruk, Amin, "
    "Michael Carrieri, Salman Firoz, Richard Goldsobel, Robert Zhu, Siva. "
    "requirements, sprint, deadline, approval, verification, deployment, staging."
)


def find_latest_session(calls_dir: Path) -> str | None:
    sessions = sorted({p.name.split("_")[0] for p in calls_dir.glob("*_mic.wav")})
    return sessions[-1] if sessions else None


def load_model() -> "WhisperModel":
    try:
        from faster_whisper import WhisperModel  # lazy; this offline tool only
    except ImportError as e:
        raise SystemExit(
            "faster-whisper is not installed. This standalone offline tool "
            "needs it; the live pipeline uses Google STT on central instead. "
            "Install with: pip install faster-whisper"
        ) from e
    return WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)


def transcribe(model: WhisperModel, wav: Path, label: str) -> list[dict]:
    segments, info = model.transcribe(
        str(wav),
        task="translate",       # always output English regardless of input language
        language=None,          # auto-detect per window — handles Bangla+English mix
        beam_size=5,            # was 1; higher = more accurate, ~2x slower
        initial_prompt=INITIAL_PROMPT,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=True,
    )
    print(f"  [{label}] detected={info.language!r} ({info.language_probability:.2f})")
    out = []
    for s in segments:
        text = s.text.strip()
        if text:
            out.append({"start": s.start, "end": s.end, "text": text, "speaker": label})
            print(f"    {s.start:7.2f}->{s.end:7.2f}  {label:5}  {text[:80]}")
    return out


def transcribe_session(
    session: str,
    calls_dir: Path,
    output_dir: Path | None = None,
    model: WhisperModel | None = None,
) -> Path:
    """Transcribe one call session and write the markdown transcript.

    session     — timestamp prefix, e.g. "20260505-203305"
    calls_dir   — directory containing <session>_mic.wav + <session>_speaker.wav
    output_dir  — where to write <session>_transcript.md (defaults to calls_dir)
    model       — pre-loaded WhisperModel; if None, loads one (slow first call)

    Returns the path to the transcript that was written.
    """
    files = sorted(calls_dir.glob(f"{session}_*.wav"))
    if not files:
        raise FileNotFoundError(
            f"No WAVs for session {session} in {calls_dir}")

    try:
        started = datetime.datetime.strptime(session, "%Y%m%d-%H%M%S")
    except ValueError:
        started = datetime.datetime.now()

    if model is None:
        print(f"Loading {MODEL_NAME} ({DEVICE}/{COMPUTE_TYPE}) — "
              "first run downloads ~3 GB...")
        model = load_model()

    all_segs: list[dict] = []
    for wav in files:
        label = "You" if wav.stem.endswith("_mic") else "Other"
        print(f"\n{wav.name} -> {label}")
        all_segs.extend(transcribe(model, wav, label))

    all_segs.sort(key=lambda s: s["start"])

    out_dir = output_dir or calls_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{session}_transcript.md"
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# Call transcript — {session}\n\n")
        f.write(f"_Started_: {started:%Y-%m-%d %H:%M}  \n")
        f.write(f"_Source_: {', '.join(w.name for w in files)}  \n")
        f.write(f"_Translated to English by faster-whisper {MODEL_NAME}_\n\n")
        f.write("---\n\n")
        for s in all_segs:
            ts = started + datetime.timedelta(seconds=s["start"])
            f.write(f"**{s['speaker']} [{ts:%d-%m-%Y %I:%M %p}]:**  \n")
            f.write(f"> {s['text']}\n\n")

    print(f"\nWrote {len(all_segs)} segments to: {out.resolve()}")
    return out


def main() -> int:
    calls_dir = Path(__file__).parent.parent / "data" / "teams" / "calls"
    arg = sys.argv[1] if len(sys.argv) > 1 else None

    if arg and Path(arg).is_file():
        wav = Path(arg)
        session = wav.stem.split("_")[0]
        calls_dir = wav.parent
    else:
        session = arg or find_latest_session(calls_dir)
        if not session:
            print("No recordings found in data/calls/", file=sys.stderr)
            return 1

    print(f"Session: {session}")
    out_dir = Path(os.environ["MEETING_OUT_DIR"]) if os.environ.get("MEETING_OUT_DIR") else None
    try:
        transcribe_session(session, calls_dir, output_dir=out_dir)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
