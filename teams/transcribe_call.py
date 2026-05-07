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
"""
from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

from faster_whisper import WhisperModel

MODEL_NAME = "large-v3"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"


def find_latest_session(calls_dir: Path) -> str | None:
    sessions = sorted({p.name.split("_")[0] for p in calls_dir.glob("*_mic.wav")})
    return sessions[-1] if sessions else None


def transcribe(model: WhisperModel, wav: Path, label: str) -> list[dict]:
    segments, info = model.transcribe(
        str(wav),
        task="translate",
        language="bn",
        beam_size=1,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    print(f"  [{label}] detected={info.language!r} ({info.language_probability:.2f})")
    out = []
    for s in segments:
        text = s.text.strip()
        if text:
            out.append({"start": s.start, "end": s.end, "text": text, "speaker": label})
            print(f"    {s.start:7.2f}->{s.end:7.2f}  {label:5}  {text[:80]}")
    return out


def main() -> int:
    calls_dir = Path(__file__).parent.parent / "data" / "teams" / "calls"
    arg = sys.argv[1] if len(sys.argv) > 1 else None

    if arg and Path(arg).is_file():
        files = [Path(arg)]
        session = Path(arg).stem.split("_")[0]
    else:
        session = arg or find_latest_session(calls_dir)
        if not session:
            print("No recordings found in data/calls/", file=sys.stderr)
            return 1
        files = sorted(calls_dir.glob(f"{session}_*.wav"))
        if not files:
            print(f"No files for session {session}", file=sys.stderr)
            return 1

    try:
        started = datetime.datetime.strptime(session, "%Y%m%d-%H%M%S")
    except ValueError:
        started = datetime.datetime.now()

    print(f"Session: {session}  ({len(files)} files)")
    print(f"Loading {MODEL_NAME} ({DEVICE}/{COMPUTE_TYPE}) — first run downloads ~3 GB...")
    model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)

    all_segs: list[dict] = []
    for wav in files:
        label = "You" if wav.stem.endswith("_mic") else "Other"
        print(f"\n{wav.name} -> {label}")
        all_segs.extend(transcribe(model, wav, label))

    all_segs.sort(key=lambda s: s["start"])

    out_dir = Path(os.environ.get("MEETING_OUT_DIR") or str(calls_dir))
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
