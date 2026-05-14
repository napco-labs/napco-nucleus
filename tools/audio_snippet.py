"""Extract a small WAV snippet from a recorded call.

Given a Source ID and a clock-time range, locate the underlying call
WAVs on the central share, compute the offset into the file, and
write a snippet to data/requirements/_snippets/. Used by the review
workflow so the reviewer can spot-check a requirement against its
source audio without scrubbing the full 1-hour call.

A MEETING Source ID looks like:
    call/<dev>-<YYYYMMDD>-<HHMMSS>/<hash>

The clock-time range is what the transcript lines carry, e.g.:
    [10:23:01] You: ...

So with source_id="call/Titu-20260511-101500/abc12345" and the range
10:23:01-10:23:14, this tool:
  1. Parses dev="Titu", call_start = 10:15:00 on 2026-05-11
  2. Computes segment offsets: 8m1s start, 8m14s end
  3. Reads <central>/Titu/2026-05-11/calls/20260511-101500_mic.wav
     and _speaker.wav at those offsets
  4. Writes the chosen track(s) to a snippet WAV

CLI:
    py -3 -m tools.audio_snippet \\
        --source-id "call/Titu-20260511-101500/abc12345" \\
        --start 10:23:01 --end 10:23:14
    py -3 -m tools.audio_snippet ... --track speaker     # other party only
    py -3 -m tools.audio_snippet ... --track mic         # your voice only
    py -3 -m tools.audio_snippet ... --track both        # both files (default)
    py -3 -m tools.audio_snippet ... --padding 3         # +/- 3s on each side
    py -3 -m tools.audio_snippet ... --play              # auto-open in default
                                                         # player after write

Falls back gracefully if the central path / source WAV isn't reachable.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import wave
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_HERE / ".env", override=False)


_SNIPPETS_DIR = _HERE / "data" / "requirements" / "_snippets"


# ── Source-ID parsing ────────────────────────────────────────────

# Stamp anchored to the end of the dev/stamp segment so dev names that
# contain hyphens (e.g. "Atikur-Z", "Kamrul-H") aren't truncated at the
# first hyphen. The stamp shape '\d{8}-\d{6}' is unambiguous, so we
# anchor the regex on it from the right.
_CALL_SOURCE_RE = re.compile(
    r"^call/(?P<dev>.+)-(?P<stamp>\d{8}-\d{6})/(?P<hash>[a-zA-Z0-9]+)$"
)


def parse_call_source_id(source_id: str) -> dict:
    """Returns {dev, stamp, hash, call_started_at, date_dir}. Raises
    ValueError on a non-call Source ID."""
    m = _CALL_SOURCE_RE.match((source_id or "").strip())
    if not m:
        raise ValueError(
            f"source_id is not a MEETING ID: {source_id!r} "
            f"(expected 'call/<dev>-<YYYYMMDD>-<HHMMSS>/<hash>')")
    dev = m.group("dev")
    stamp = m.group("stamp")
    try:
        call_started_at = dt.datetime.strptime(stamp, "%Y%m%d-%H%M%S")
    except ValueError as e:
        raise ValueError(f"bad call stamp in {source_id!r}: {e}")
    return {
        "dev": dev,
        "stamp": stamp,
        "hash": m.group("hash"),
        "call_started_at": call_started_at,
        "date_dir": call_started_at.strftime("%Y-%m-%d"),
    }


# ── Time parsing ──────────────────────────────────────────────────

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


def parse_hhmmss(s: str) -> dt.time:
    """Accept HH:MM or HH:MM:SS. Returns a datetime.time."""
    m = _TIME_RE.match((s or "").strip())
    if not m:
        raise ValueError(f"can't parse time {s!r}; try '10:23' or '10:23:14'")
    h, mn, sc = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    return dt.time(h, mn, sc)


def clock_to_offset_seconds(clock: str, call_started_at: dt.datetime) -> float:
    """Convert a wall-clock time string ('10:23:01') to seconds offset
    from the call start. The clock value is assumed to be on the same
    date as call_started_at."""
    t = parse_hhmmss(clock)
    asked = dt.datetime.combine(call_started_at.date(), t)
    return (asked - call_started_at).total_seconds()


# ── Snippet extraction ──────────────────────────────────────────

def _central_path() -> Path:
    raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    if not raw:
        raise RuntimeError("NUCLEUS_CENTRAL_PATH not set")
    return Path(raw)


def locate_call_wavs(source_id: str) -> dict:
    """Resolve a MEETING Source ID to the underlying WAV paths on
    central. Returns {dev, stamp, mic, speaker, meta}. Missing tracks
    come back as None."""
    info = parse_call_source_id(source_id)
    central = _central_path()
    calls_dir = central / info["dev"] / info["date_dir"] / "calls"
    if not calls_dir.exists():
        raise RuntimeError(f"calls dir not found: {calls_dir}")
    mic = calls_dir / f"{info['stamp']}_mic.wav"
    spk = calls_dir / f"{info['stamp']}_speaker.wav"
    meta = calls_dir / f"{info['stamp']}.json"
    return {
        **info,
        "calls_dir": calls_dir,
        "mic": mic if mic.exists() else None,
        "speaker": spk if spk.exists() else None,
        "meta": meta if meta.exists() else None,
    }


def _extract_wav_range(src: Path, dst: Path,
                       start_s: float, end_s: float) -> None:
    """Copy a [start_s, end_s] slice of `src` into `dst`, preserving
    sample rate / channels / bit depth."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(src), "rb") as w:
        framerate = w.getframerate()
        nchannels = w.getnchannels()
        sampwidth = w.getsampwidth()
        total_frames = w.getnframes()
        start_frame = max(0, int(start_s * framerate))
        end_frame = min(total_frames, int(end_s * framerate))
        if end_frame <= start_frame:
            raise ValueError(
                f"empty range: {start_s:.1f}s-{end_s:.1f}s on "
                f"{src.name} (length {total_frames / framerate:.1f}s)")
        w.setpos(start_frame)
        frames = w.readframes(end_frame - start_frame)
    with wave.open(str(dst), "wb") as cw:
        cw.setnchannels(nchannels)
        cw.setsampwidth(sampwidth)
        cw.setframerate(framerate)
        cw.writeframes(frames)


def extract_snippet(*, source_id: str, start: str, end: str,
                    track: str = "speaker",
                    padding_s: float = 2.0) -> list[Path]:
    """Extract one or two WAV snippets for a Source ID + time range.

    track:
      "speaker" — the OTHER party (the client; most useful for review)
      "mic"     — your voice
      "both"    — both files (returns 2 paths)
    """
    located = locate_call_wavs(source_id)
    call_started = located["call_started_at"]
    start_s = clock_to_offset_seconds(start, call_started) - padding_s
    end_s = clock_to_offset_seconds(end, call_started) + padding_s
    if end_s <= start_s:
        raise ValueError(f"end ({end}) is not after start ({start})")

    targets: list[tuple[str, Path | None]] = []
    if track == "both":
        targets = [("mic", located.get("mic")),
                   ("speaker", located.get("speaker"))]
    elif track == "mic":
        targets = [("mic", located.get("mic"))]
    elif track == "speaker":
        targets = [("speaker", located.get("speaker"))]
    else:
        raise ValueError(f"track must be mic/speaker/both, got {track!r}")

    _SNIPPETS_DIR.mkdir(parents=True, exist_ok=True)
    out_paths: list[Path] = []
    safe_start = start.replace(":", "")
    safe_end = end.replace(":", "")
    for label, src in targets:
        if src is None:
            print(f"  ! no {label} track present for {source_id}",
                  file=sys.stderr)
            continue
        dst = _SNIPPETS_DIR / (
            f"{located['stamp']}_{safe_start}-{safe_end}_{label}.wav"
        )
        _extract_wav_range(src, dst, start_s, end_s)
        out_paths.append(dst)
    return out_paths


# ── OS-level play helper (review_session uses this) ────────────

def play_audio(path: Path) -> bool:
    """Open `path` in the OS default audio player. Returns True if
    the spawn succeeded; doesn't wait for the player to close."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
            return True
        # Linux / WSL — try xdg-open
        subprocess.Popen(["xdg-open", str(path)])
        return True
    except Exception as e:
        print(f"  ! could not auto-play {path}: {e}", file=sys.stderr)
        return False


# ── CLI ─────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-id", required=True,
                    help="MEETING Source ID, e.g. "
                         "'call/Titu-20260511-101500/abc12345'")
    ap.add_argument("--start", required=True,
                    help="Start clock time, e.g. '10:23:01'")
    ap.add_argument("--end", required=True,
                    help="End clock time, e.g. '10:23:14'")
    ap.add_argument("--track", default="speaker",
                    choices=("mic", "speaker", "both"),
                    help="Which track(s) to extract. Default speaker "
                         "(the other party — most useful for review).")
    ap.add_argument("--padding", type=float, default=2.0,
                    help="Seconds padded on each side. Default 2.0.")
    ap.add_argument("--play", action="store_true",
                    help="Open the snippet in the OS default player "
                         "after writing.")
    args = ap.parse_args()

    try:
        paths = extract_snippet(
            source_id=args.source_id, start=args.start, end=args.end,
            track=args.track, padding_s=args.padding,
        )
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not paths:
        print("no snippets produced.")
        return 1

    for p in paths:
        size_kb = p.stat().st_size / 1024
        print(f"wrote {p}  ({size_kb:.1f} KB)")

    if args.play:
        play_audio(paths[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
