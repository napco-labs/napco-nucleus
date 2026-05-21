"""Auto-transcribe new calls landing on the central share.

Runs on the agent host (MVPACCESS) as a Scheduled Task every couple of
minutes. Walks <NUCLEUS_CENTRAL_PATH>/<dev>/<date>/calls/ for the
configured day window, finds every completed call session that doesn't
yet have a transcript, and transcribes it in place.

Backend selection (per session, transparent to caller):
    1. Try Groq Whisper translations API (whisper-large-v3 — same model
       as our local faster-whisper, but on Groq's GPUs => ~hundreds of
       times faster). Free tier on Groq allows 8 hr of audio/day, which
       covers typical AEL call volume.
    2. On ANY Groq failure (rate limit / 429, network, file > 25 MB,
       missing GROQ_API_KEY, etc.) fall back to local faster-whisper
       on CPU. Slower but reliable and free.

This means the daily 23:45 BD pipeline gets Groq-speed transcripts on
normal days and is still correct on bursty days when Groq hits its
free-tier ceiling. The faster-whisper model is loaded LAZILY — if all
sessions succeed via Groq we never pay the ~3 GB model-load cost.

Completion signal:
    <session>.json exists.
    record_call.py copies mic.wav -> speaker.wav -> <session>.json in
    that order, so the metadata JSON only lands after both WAVs are
    fully on central. That's the "this call is done uploading" marker.

Idempotent — sessions that already have <session>_transcript.md next to
the WAVs are skipped. Cross-process safe via tools._lock.file_lock; a
second invocation while one is running aborts immediately so the
2-minute cron can't pile up overlapping Whisper runs.

Usage:
    py -3 -m tools.transcribe_calls
    py -3 -m tools.transcribe_calls --days 3
    py -3 -m tools.transcribe_calls --dry-run
    py -3 -m tools.transcribe_calls --no-groq    # force faster-whisper
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import subprocess
import sys
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

import memory  # noqa: E402
from tools._lock import file_lock  # noqa: E402

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/audio/translations"
GROQ_MODEL_DEFAULT = "whisper-large-v3"  # turbo can't translate; do not change
GROQ_MAX_BYTES = 25 * 1024 * 1024
# Headroom under the 25 MB cap for the WAV header + multipart envelope.
GROQ_CHUNK_HEADROOM_BYTES = 1 * 1024 * 1024

# Domain prompt — primes Whisper for NN's vocabulary so technical proper
# nouns, product names, and team names land cleanly instead of as
# phonetic guesses. The /translations endpoint expects the prompt in
# English (output language). Override via NUCLEUS_TRANSCRIBE_PROMPT env
# var if a deployment needs different vocabulary (e.g. another client's
# product lineup).
GROQ_DEFAULT_PROMPT = (
    "MS Arcules DVR, MVP Access, NAPCO Security, HTS, OpenProject. "
    "Titu, Atik, Rocky, Isruk, Mahmed, Sheikh Amin, Salman, Assad, "
    "Ahsan Habib, Mostafa, Michael Carrieri, Siva, Richard Goldsobel, "
    "Robert Zhu."
)


def _central_root() -> Path | None:
    raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    return Path(raw) if raw else None


def _day_dirs(root: Path, days: int) -> list[Path]:
    """Today + the previous (days-1) days for every dev folder under root."""
    today = dt.date.today()
    out: list[Path] = []
    try:
        dev_dirs = [d for d in root.iterdir() if d.is_dir()]
    except OSError as e:
        logger.error("cannot list central root %s: %s", root, e)
        return out
    for dev in dev_dirs:
        for i in range(days):
            day = (today - dt.timedelta(days=i)).strftime("%Y-%m-%d")
            calls = dev / day / "calls"
            if calls.exists():
                out.append(calls)
    return out


def _pending_sessions(calls_dir: Path) -> list[str]:
    """Session prefixes (e.g. '20260513-203305') with metadata present
    but no transcript yet."""
    pending: list[str] = []
    for meta in sorted(calls_dir.glob("*.json")):
        session = meta.stem
        if (calls_dir / f"{session}_transcript.md").exists():
            continue
        if not (calls_dir / f"{session}_mic.wav").exists():
            continue
        if not (calls_dir / f"{session}_speaker.wav").exists():
            continue
        pending.append(session)
    return pending


def _scan(root: Path, days: int) -> list[tuple[Path, str]]:
    work: list[tuple[Path, str]] = []
    for calls_dir in _day_dirs(root, days):
        for session in _pending_sessions(calls_dir):
            work.append((calls_dir, session))
    return work


# ─── Groq backend ───────────────────────────────────────────────────

def _split_wav_by_size(wav_path: Path, max_bytes: int,
                       out_dir: Path) -> list[tuple[Path, float]]:
    """Slice a WAV into chunks each strictly smaller than max_bytes.

    Returns [(chunk_path, start_offset_seconds), ...] in order. Each
    chunk is a valid standalone WAV with its own header. Caller is
    responsible for cleaning up chunk_path's parent directory.
    """
    import wave
    chunks: list[tuple[Path, float]] = []
    with wave.open(str(wav_path), "rb") as w:
        n_channels = w.getnchannels()
        sample_width = w.getsampwidth()
        framerate = w.getframerate()
        total_frames = w.getnframes()
        bytes_per_frame = n_channels * sample_width
        target_data_bytes = max(bytes_per_frame,
                                max_bytes - GROQ_CHUNK_HEADROOM_BYTES)
        frames_per_chunk = max(1, target_data_bytes // bytes_per_frame)
        idx = 0
        pos = 0
        while pos < total_frames:
            n = min(frames_per_chunk, total_frames - pos)
            w.setpos(pos)
            raw = w.readframes(n)
            chunk_path = out_dir / f"{wav_path.stem}.chunk{idx:02d}.wav"
            with wave.open(str(chunk_path), "wb") as out:
                out.setnchannels(n_channels)
                out.setsampwidth(sample_width)
                out.setframerate(framerate)
                out.writeframes(raw)
            chunks.append((chunk_path, pos / float(framerate)))
            pos += n
            idx += 1
    return chunks


def _groq_translate_one(wav_path: Path, label: str,
                        time_offset_s: float = 0.0) -> list[dict]:
    """POST a single ≤25 MB WAV to Groq. Adds time_offset_s to every
    segment timestamp so chunked uploads stitch back into a continuous
    transcript timeline.
    """
    import requests  # lazy — drive_ingester already pulls this in
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")
    model = os.getenv("GROQ_TEAMS_WHISPER_MODEL") or GROQ_MODEL_DEFAULT

    prompt = (os.getenv("NUCLEUS_TRANSCRIBE_PROMPT") or
              GROQ_DEFAULT_PROMPT).strip()
    with open(wav_path, "rb") as f:
        files = {"file": (wav_path.name, f, "audio/wav")}
        data = {
            "model": model,
            "response_format": "verbose_json",
            # temperature=0 keeps decoding deterministic — same input,
            # same transcript on every retry. Whisper's default 0 is
            # already fine, set explicitly so callers can't drift.
            "temperature": "0",
        }
        if prompt:
            data["prompt"] = prompt
        headers = {"Authorization": f"Bearer {api_key}"}
        r = requests.post(GROQ_URL, headers=headers, files=files,
                          data=data, timeout=300)

    if r.status_code != 200:
        raise RuntimeError(
            f"Groq {r.status_code}: {r.text[:300]}")

    payload = r.json()
    out: list[dict] = []
    for s in payload.get("segments", []):
        text = (s.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "start": float(s.get("start", 0.0)) + time_offset_s,
            "end": float(s.get("end", 0.0)) + time_offset_s,
            "text": text,
            "speaker": label,
        })
    return out


def _groq_translate(wav_path: Path, label: str) -> list[dict]:
    """POST a WAV to Groq's translations endpoint, return segments.

    Files over the Groq per-call 25 MB cap are split into ≤24 MB
    chunks, sent one-at-a-time, and re-stitched on the receiving side
    with adjusted timestamps. A 60-minute mic.wav (~115 MB at 16 kHz
    mono 16-bit) becomes ~5 sequential uploads.

    Each segment: {start: float, end: float, text: str, speaker: label}.
    Raises on any non-200 response so the caller can fall back to
    faster-whisper for the whole session.
    """
    size = wav_path.stat().st_size
    if size <= GROQ_MAX_BYTES - GROQ_CHUNK_HEADROOM_BYTES:
        return _groq_translate_one(wav_path, label, time_offset_s=0.0)

    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="nucleus_groq_chunks_"))
    try:
        chunks = _split_wav_by_size(wav_path, GROQ_MAX_BYTES, tmp)
        print(f"  [groq-chunk] {wav_path.name} {size / 1e6:.1f} MB "
              f"-> {len(chunks)} chunk(s)")
        all_segs: list[dict] = []
        for chunk_path, offset in chunks:
            all_segs.extend(_groq_translate_one(
                chunk_path, label, time_offset_s=offset))
        return all_segs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _post_correct_segments(segments: list[dict]) -> list[dict]:
    """Ask Claude to fix obvious ASR errors using NN domain vocabulary.

    Sends the transcript as numbered lines, asks Claude to return the
    same number of lines with corrected text. Strictly fails open --
    any parse drift or CLI failure returns the original segments
    unchanged so a bad post-correction never blocks transcription.

    Opt-out: NUCLEUS_TRANSCRIBE_POSTCORRECT=0 in .env.
    """
    if os.environ.get("NUCLEUS_TRANSCRIBE_POSTCORRECT", "1") == "0":
        return segments
    if not segments:
        return segments

    cli = (os.environ.get("CLAUDE_CLI_PATH")
           or os.path.expanduser("~/.local/bin/claude"))
    if not os.path.exists(cli):
        # On dev PCs the CLI lives at %USERPROFILE%\.local\bin\claude.exe;
        # on .123 (the only place transcribe runs in prod) it's the
        # path above. Either way, skip silently if not present.
        return segments

    # Numbered render keeps the one-to-one mapping cheap to parse.
    rendered = "\n".join(
        f"{i+1}|{s['speaker']}|{s['text']}"
        for i, s in enumerate(segments)
    )
    prompt = (
        "You are cleaning up automatic speech-recognition (ASR) output "
        "from Whisper. Below are numbered transcript lines from a "
        "software-development call at NAPCO Nucleus / AEL-BD (the team "
        "builds the MS Arcules DVR integration, MVP Access, OpenProject "
        "and related tools). Speakers often mix English and Bengali.\n\n"
        "Your job: fix obvious mishearings of proper nouns, product "
        "names and technical jargon using the domain context below. "
        "Do NOT invent content, do NOT rephrase the meaning, do NOT "
        "merge or split lines. If a line is already correct, return "
        "it unchanged.\n\n"
        "Known vocabulary: MS Arcules DVR, MVP Access, NAPCO Security, "
        "HTS, OpenProject, Nucleus. Team: Titu, Atik (Atikur), Rocky, "
        "Isruk, Mahmed, Sheikh Amin, Salman, Assad, Ahsan Habib, "
        "Mostafa, Michael Carrieri, Siva, Richard Goldsobel, Robert "
        "Zhu. Tech: stored procedure, changeset, drop-down, integration "
        "page, partition field, conversation thread.\n\n"
        "Output rules: return EXACTLY the same number of lines, each "
        "in the format `<n>|<speaker>|<corrected text>`. No prose, no "
        "markdown, no explanations. Just the lines.\n\n"
        "Lines to clean:\n" + rendered
    )

    try:
        r = subprocess.run(
            [cli, "--print", "--max-turns", "1", prompt],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  [postcorrect] CLI call failed ({type(e).__name__}: {e}); "
              f"using original segments.", file=sys.stderr)
        return segments

    if r.returncode != 0:
        print(f"  [postcorrect] CLI rc={r.returncode}; using original "
              f"segments.\n  stderr: {(r.stderr or '')[:200]}",
              file=sys.stderr)
        return segments

    parsed: list[dict] = []
    expected = len(segments)
    for raw in (r.stdout or "").splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        try:
            idx = int(parts[0]) - 1
        except ValueError:
            continue
        if idx < 0 or idx >= expected:
            continue
        new_text = parts[2].strip()
        if not new_text:
            continue
        parsed.append({"_idx": idx, "_text": new_text})

    if len(parsed) != expected:
        print(f"  [postcorrect] parse mismatch ({len(parsed)} of "
              f"{expected} lines returned); using original segments.",
              file=sys.stderr)
        return segments

    out = []
    by_idx = {p["_idx"]: p["_text"] for p in parsed}
    for i, s in enumerate(segments):
        if i in by_idx:
            out.append({**s, "text": by_idx[i]})
        else:
            out.append(s)
    print(f"  [postcorrect] Claude cleaned {expected} segment(s).")
    return out


def _transcribe_session_via_groq(session: str, calls_dir: Path,
                                  output_dir: Path) -> Path:
    """Transcribe one session via Groq, write transcript .md next to
    the WAVs (matching faster-whisper's markdown format exactly so
    downstream readers don't care which backend produced it)."""
    mic = calls_dir / f"{session}_mic.wav"
    spk = calls_dir / f"{session}_speaker.wav"
    if not mic.exists() or not spk.exists():
        raise FileNotFoundError(
            f"Missing mic.wav and/or speaker.wav for {session}")

    mic_segs = _groq_translate(mic, label="You")
    spk_segs = _groq_translate(spk, label="Other")
    all_segs = sorted(mic_segs + spk_segs, key=lambda s: s["start"])
    all_segs = _post_correct_segments(all_segs)

    try:
        started = dt.datetime.strptime(session, "%Y%m%d-%H%M%S")
    except ValueError:
        started = dt.datetime.now()

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"{session}_transcript.md"
    model = os.getenv("GROQ_TEAMS_WHISPER_MODEL") or GROQ_MODEL_DEFAULT
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# Call transcript — {session}\n\n")
        f.write(f"_Started_: {started:%Y-%m-%d %H:%M}  \n")
        f.write(f"_Source_: {mic.name}, {spk.name}  \n")
        f.write(f"_Translated to English by Groq {model}_\n\n")
        f.write("---\n\n")
        for s in all_segs:
            ts = started + dt.timedelta(seconds=s["start"])
            f.write(f"**{s['speaker']} [{ts:%d-%m-%Y %I:%M %p}]:**  \n")
            f.write(f"> {s['text']}\n\n")
    return out


# ─── main ───────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=2,
                    help="How many days back to scan (default: 2 — "
                         "today + yesterday, catches calls that ended "
                         "across midnight).")
    ap.add_argument("--dry-run", action="store_true",
                    help="List pending sessions without transcribing.")
    ap.add_argument("--no-groq", action="store_true",
                    help="Skip Groq entirely, use local faster-whisper "
                         "directly. For debugging / Groq outages.")
    args = ap.parse_args()

    root = _central_root()
    if root is None:
        print("NUCLEUS_CENTRAL_PATH not set; aborting.", file=sys.stderr)
        return 2
    if not root.exists():
        print(f"Central path not reachable: {root}", file=sys.stderr)
        return 2

    use_groq = not args.no_groq and bool(os.getenv("GROQ_API_KEY"))
    backend_hint = "Groq + faster-whisper fallback" if use_groq else "faster-whisper only"
    print(f"Transcribe calls — central={root}  days={args.days}  backend={backend_hint}")

    work = _scan(root, args.days)
    if not work:
        print("  nothing to transcribe.")
        memory.log_activity(
            task_name="transcribe-calls:scan",
            result="ok:0",
            technical_details={"pending": 0, "days": args.days})
        return 0

    print(f"  pending: {len(work)} session(s)")
    for calls_dir, session in work:
        print(f"    {calls_dir.parent.parent.name}/{calls_dir.parent.name}/{session}")

    if args.dry_run:
        memory.log_activity(
            task_name="transcribe-calls:scan",
            result=f"dry_run:{len(work)}",
            technical_details={"pending": len(work), "days": args.days})
        return 0

    with file_lock("transcribe_calls", block=False) as got:
        if not got:
            print("  another transcribe-calls run is in progress; "
                  "skipping this tick.")
            memory.log_activity(
                task_name="transcribe-calls:scan",
                result="skipped:locked",
                technical_details={"pending": len(work)})
            return 0

        # faster-whisper model is loaded LAZILY — only when a Groq attempt
        # actually fails (or --no-groq). Most days this stays None and we
        # skip the ~3 GB model load entirely.
        fw_model = None
        _fw_transcribe = None

        def _ensure_fw():
            nonlocal fw_model, _fw_transcribe
            if fw_model is not None:
                return
            from teams.transcribe_call import load_model, transcribe_session  # noqa
            print("  loading faster-whisper (one-time per run)...")
            fw_model = load_model()
            _fw_transcribe = transcribe_session

        ok_groq, ok_fw, failed = 0, 0, 0
        for calls_dir, session in work:
            done_via = None

            if use_groq:
                try:
                    _transcribe_session_via_groq(
                        session=session,
                        calls_dir=calls_dir,
                        output_dir=calls_dir,
                    )
                    done_via = "groq"
                    ok_groq += 1
                    print(f"  [groq] {session}")
                except Exception as e:
                    logger.warning("Groq failed for %s: %s — "
                                   "falling back to faster-whisper",
                                   session, e)
                    print(f"  [groq-fail] {session}: {e}")

            if done_via is None:
                try:
                    _ensure_fw()
                    _fw_transcribe(
                        session=session,
                        calls_dir=calls_dir,
                        output_dir=calls_dir,
                        model=fw_model,
                    )
                    done_via = "faster-whisper"
                    ok_fw += 1
                    print(f"  [fw] {session}")
                except Exception as e:
                    logger.exception("faster-whisper fallback failed: %s/%s",
                                     calls_dir, session)
                    print(f"  FAILED {session}: {e}", file=sys.stderr)
                    failed += 1

        print(f"  done: groq={ok_groq}  fw={ok_fw}  failed={failed}")
        memory.log_activity(
            task_name="transcribe-calls:run",
            result=f"groq:{ok_groq}/fw:{ok_fw}/failed:{failed}",
            technical_details={"groq": ok_groq, "fw": ok_fw,
                               "failed": failed, "days": args.days})
        return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
