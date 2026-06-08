"""
On-demand meeting pull — transcribe the latest call recording (from
teams/record_call.py) locally with faster-whisper and append the
speaker-labeled transcript to the pull-session doc.

Mic track  -> "You"
Speaker track (system loopback / other party) -> "Other"

Usage:
    python pull_meeting.py                           # latest session
    python pull_meeting.py --session 20260507-184500 # specific session
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env", override=True)

from tools import _session_doc as session_doc  # noqa: E402

# Default TRW recording dir is now NN-internal: data/teams/calls/
DEFAULT_CALLS_DIR = _HERE / "data" / "teams" / "calls"


def _find_latest_session(calls_dir: Path) -> str | None:
    sessions = sorted({p.name.split("_")[0]
                       for p in calls_dir.glob("*_mic.wav")})
    return sessions[-1] if sessions else None


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--session", default=None,
                   help="Recording session stamp (YYYYMMDD-HHMMSS). Default: latest.")
    p.add_argument("--calls-dir", default=str(DEFAULT_CALLS_DIR),
                   help=f"Recording directory. Default: {DEFAULT_CALLS_DIR}")
    args = p.parse_args()

    calls_dir = Path(args.calls_dir)
    if not calls_dir.is_dir():
        print(f"Recording dir not found: {calls_dir}\n"
              f"Run `python -m teams.record_call` first.", file=__import__('sys').stderr)
        return 1

    session = args.session or _find_latest_session(calls_dir)
    if not session:
        print(f"No *_mic.wav recordings in {calls_dir}.\n"
              f"Run `python -m teams.record_call` first.",
              file=__import__('sys').stderr)
        return 1

    files = sorted(calls_dir.glob(f"{session}_*.wav"))
    if not files:
        print(f"No files for session {session} in {calls_dir}",
              file=__import__('sys').stderr)
        return 1

    print(f"Session:    {session}  ({len(files)} track(s))")
    print(f"Loading faster-whisper large-v3 (~3 GB on first run). "
          f"Expect a few minutes on CPU.")

    # In-process transcribe — same logic as teams/transcribe_call.py.
    # faster-whisper is no longer a project dependency (removed 2026-06-08;
    # live transcription is Google STT on central). This standalone tool
    # imports it lazily and degrades with a clear message if absent.
    try:
        from faster_whisper import WhisperModel  # lazy; this offline tool only
    except ImportError:
        print("faster-whisper is not installed. This standalone offline tool "
              "needs it; the live pipeline uses Google STT on central. "
              "Install with: pip install faster-whisper", file=__import__('sys').stderr)
        return 1
    model = WhisperModel("large-v3", device="cpu", compute_type="int8")

    all_segs: list[dict] = []
    for wav in files:
        label = "You" if wav.stem.endswith("_mic") else "Other"
        print(f"\n{wav.name} -> {label}")
        segments, info = model.transcribe(
            str(wav), task="translate", language="bn",
            beam_size=1, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        print(f"  detected={info.language!r} ({info.language_probability:.2f})")
        for s in segments:
            text = s.text.strip()
            if text:
                all_segs.append({"start": s.start, "end": s.end,
                                 "text": text, "speaker": label})
                # Encode-safe progress print (Windows cp1252 console can't render
                # all Unicode the model returns; the actual text variable is kept
                # as-is for the docx).
                safe = text[:80].encode("ascii", "replace").decode("ascii")
                print(f"    {s.start:7.2f}->{s.end:7.2f}  {label:5}  {safe}")

    all_segs.sort(key=lambda s: s["start"])

    try:
        started = dt.datetime.strptime(session, "%Y%m%d-%H%M%S")
    except ValueError:
        started = dt.datetime.now()

    body_lines = [
        f"Session: {session}",
        f"Started: {started:%Y-%m-%d %H:%M}",
        f"Tracks: {len(files)}",
        "",
    ]
    if all_segs:
        for s in all_segs:
            ts = started + dt.timedelta(seconds=s["start"])
            body_lines.append(f"[{ts:%H:%M:%S}] {s['speaker']}: {s['text']}")
    else:
        body_lines.append("(no speech detected)")

    headline = f"call recording {session}"
    result = session_doc.append_section(
        source="MEETING",
        headline=headline,
        metadata={
            "Session": session,
            "Started": started.strftime("%Y-%m-%d %H:%M"),
            "Tracks": str(len(files)),
            "Segments": str(len(all_segs)),
            "Transcribed": "faster-whisper large-v3 (Bangla -> English)",
        },
        body_paragraphs=body_lines,
    )
    print(f"\nAppended to session doc: {result['absolute_path']}")
    print(f"Section: {result['section']}")
    print(f"Lines added: {result['appended_paragraphs']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
