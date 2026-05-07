"""
On-demand meeting pull — invoke TRW's transcribe_call.py (its own venv
has faster-whisper) on the latest call recording, then append the
speaker-labeled transcript to NN's pull-session doc.

Mic track  -> "You"
Speaker track (system loopback / other party) -> "Other"

Usage:
    python pull_meeting.py                           # latest TRW session
    python pull_meeting.py --session 20260507-184500 # specific session

Env:
    TRW_ROOT     default E:\\Projects\\Teams-Requirement-Watcher
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env", override=True)

from tools import _session_doc as session_doc  # noqa: E402

DEFAULT_TRW_ROOT = Path(
    os.environ.get("TRW_ROOT")
    or r"E:\Projects\Teams-Requirement-Watcher"
)


def _find_latest_session(calls_dir: Path) -> str | None:
    sessions = sorted({p.name.split("_")[0]
                       for p in calls_dir.glob("*_mic.wav")})
    return sessions[-1] if sessions else None


def _parse_transcript_md(md: str) -> list[tuple[str, str, str]]:
    """Parse TRW's transcript .md into (timestamp, speaker, text) tuples.

    TRW format:
        **<Speaker> [DD-MM-YYYY HH:MM AM/PM]:**
        > line 1
        > line 2

    Returns [] if nothing matched (caller falls back to raw text)."""
    blocks: list[tuple[str, str, str]] = []
    pattern = re.compile(
        r"\*\*(\w+)\s+\[([^\]]+)\]:\*\*\s*\n((?:>\s*.+\n?)+)",
        flags=re.MULTILINE,
    )
    for m in pattern.finditer(md):
        speaker, ts_str, body = m.group(1), m.group(2), m.group(3)
        # Strip leading "> " from each body line, join into one
        text = "\n".join(
            ln.lstrip("> ").rstrip()
            for ln in body.splitlines()
            if ln.strip()
        )
        blocks.append((ts_str, speaker, text))
    return blocks


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--session", default=None,
                   help="TRW session stamp (YYYYMMDD-HHMMSS). Default: latest.")
    p.add_argument("--trw-root", default=str(DEFAULT_TRW_ROOT),
                   help=f"TRW project root. Default: {DEFAULT_TRW_ROOT}")
    args = p.parse_args()

    trw_root = Path(args.trw_root)
    calls_dir = trw_root / "data" / "calls"
    if not calls_dir.is_dir():
        print(f"TRW calls dir not found: {calls_dir}", file=sys.stderr)
        return 1

    session = args.session or _find_latest_session(calls_dir)
    if not session:
        print(f"No *_mic.wav recordings in {calls_dir}.\n"
              f"Run TRW's record_call.py first.", file=sys.stderr)
        return 1

    files = sorted(calls_dir.glob(f"{session}_*.wav"))
    if not files:
        print(f"No files for session {session} in {calls_dir}", file=sys.stderr)
        return 1

    # Resolve TRW's Python — prefer its .venv if present.
    venv_py = trw_root / ".venv" / "Scripts" / "python.exe"
    py_exe = str(venv_py) if venv_py.is_file() else sys.executable

    # Tell TRW's transcribe_call.py where to drop its .md
    out_dir = _HERE / "data" / "requirements" / "_meeting_tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = out_dir / f"{session}_transcript.md"
    if transcript_path.exists():
        transcript_path.unlink()

    env = os.environ.copy()
    env["MEETING_OUT_DIR"] = str(out_dir)

    print(f"Session:    {session}  ({len(files)} track(s))")
    print(f"Using:      {py_exe}")
    print(f"This will load faster-whisper large-v3 (~3 GB on first run) "
          f"and transcribe on CPU. Expect a few minutes.")

    cmd = [py_exe, "transcribe_call.py", session]
    try:
        proc = subprocess.run(cmd, cwd=str(trw_root), env=env)
    except FileNotFoundError as e:
        print(f"Could not invoke {py_exe}: {e}", file=sys.stderr)
        return 1
    if proc.returncode != 0:
        print(f"transcribe_call.py exited {proc.returncode}", file=sys.stderr)
        return proc.returncode

    if not transcript_path.is_file():
        print(f"Expected transcript not found at {transcript_path}",
              file=sys.stderr)
        return 1

    md = transcript_path.read_text(encoding="utf-8")
    blocks = _parse_transcript_md(md)

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
    if blocks:
        for ts_str, speaker, text in blocks:
            body_lines.append(f"[{ts_str}] {speaker}: {text}")
    else:
        # Parser didn't recognize anything — fall back to raw markdown
        body_lines.append("--- raw transcript ---")
        for ln in md.splitlines():
            body_lines.append(ln)

    headline = f"call recording {session}"
    result = session_doc.append_section(
        source="MEETING",
        headline=headline,
        metadata={
            "Session": session,
            "Started": started.strftime("%Y-%m-%d %H:%M"),
            "Tracks": str(len(files)),
            "Segments": str(len(blocks)),
            "Transcribed": "faster-whisper large-v3 (Bangla -> English)",
        },
        body_paragraphs=body_lines,
    )
    print(f"\nAppended to session doc: {result['absolute_path']}")
    print(f"Section: {result['section']}")
    print(f"Lines added: {result['appended_paragraphs']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
