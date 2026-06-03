"""Auto-transcribe new calls landing on the central share.

Runs on the agent host as a Scheduled Task every couple of minutes.
Walks <NUCLEUS_CENTRAL_PATH>/<dev>/<date>/calls/ for the configured day
window, finds every completed call session that doesn't yet have a
transcript, and transcribes it in place using Google STT.

Completion signal:
    <session>.json exists.
    record_call.py copies mic.wav -> speaker.wav -> <session>.json in
    that order, so the metadata JSON only lands after both WAVs are
    fully on central. That's the "this call is done uploading" marker.

Idempotent — sessions that already have <session>_transcript.md next to
the WAVs are skipped. Cross-process safe via tools._lock.file_lock; a
second invocation while one is running aborts immediately so the
2-minute cron can't pile up overlapping runs.

Usage:
    py -3 -m tools.transcribe_calls
    py -3 -m tools.transcribe_calls --days 3
    py -3 -m tools.transcribe_calls --dry-run
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


MAX_TRANSCRIBE_FAILURES = 5


def _failure_count(calls_dir: Path, session: str) -> int:
    p = calls_dir / f"{session}.transcribe_failures"
    try:
        return int(p.read_text().strip())
    except Exception:
        return 0


def _increment_failure(calls_dir: Path, session: str) -> int:
    p = calls_dir / f"{session}.transcribe_failures"
    count = _failure_count(calls_dir, session) + 1
    try:
        p.write_text(str(count))
    except OSError:
        pass
    return count


def _write_failed_transcript(calls_dir: Path, session: str) -> None:
    out = calls_dir / f"{session}_transcript.md"
    try:
        started = dt.datetime.strptime(session, "%Y%m%d-%H%M%S")
    except ValueError:
        started = dt.datetime.now()
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# Call transcript — {session}\n\n")
        f.write(f"_Started_: {started:%Y-%m-%d %H:%M}  \n")
        f.write(f"_Status_: TRANSCRIPTION FAILED after "
                f"{MAX_TRANSCRIBE_FAILURES} attempts — "
                f"requirements from this call are unavailable.\n\n")
        f.write("---\n\n")
        f.write("(No transcript available — Google STT failed repeatedly. "
                "Check audio quality and API credentials.)\n")


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


def _post_correct_segments(segments: list[dict]) -> list[dict]:
    """Ask Claude to fix obvious ASR errors using NN domain vocabulary.

    Strictly fails open — any parse drift or CLI failure returns the
    original segments unchanged so a bad post-correction never blocks
    transcription. Opt-out: NUCLEUS_TRANSCRIBE_POSTCORRECT=0 in .env.
    """
    if os.environ.get("NUCLEUS_TRANSCRIBE_POSTCORRECT", "1") == "0":
        return segments
    if not segments:
        return segments

    cli = (os.environ.get("CLAUDE_CLI_PATH")
           or os.path.expanduser("~/.local/bin/claude"))
    if not os.path.exists(cli):
        return segments

    rendered = "\n".join(
        f"{i+1}|{s['speaker']}|{s['text']}"
        for i, s in enumerate(segments)
    )
    prompt = (
        "You are cleaning up automatic speech-recognition (ASR) output "
        "from Google STT. Below are numbered transcript lines from a "
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


def _transcribe_session_via_google_stt(session: str, calls_dir: Path,
                                        output_dir: Path) -> Path:
    """Transcribe one session via Google STT, write transcript .md."""
    from tools.google_stt import google_transcribe  # lazy
    mic = calls_dir / f"{session}_mic.wav"
    spk = calls_dir / f"{session}_speaker.wav"
    if not mic.exists() or not spk.exists():
        raise FileNotFoundError(
            f"Missing mic.wav and/or speaker.wav for {session}")

    mic_segs = google_transcribe(mic, "You")
    spk_segs = google_transcribe(spk, "Other")
    all_segs = sorted(mic_segs + spk_segs, key=lambda s: s["start"])
    all_segs = _post_correct_segments(all_segs)

    try:
        started = dt.datetime.strptime(session, "%Y%m%d-%H%M%S")
    except ValueError:
        started = dt.datetime.now()

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"{session}_transcript.md"
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# Call transcript — {session}\n\n")
        f.write(f"_Started_: {started:%Y-%m-%d %H:%M}  \n")
        f.write(f"_Source_: {mic.name}, {spk.name}  \n")
        f.write(f"_Transcribed by Google STT_\n\n")
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
    args = ap.parse_args()

    root = _central_root()
    if root is None:
        print("NUCLEUS_CENTRAL_PATH not set; aborting.", file=sys.stderr)
        return 2
    if not root.exists():
        print(f"Central path not reachable: {root}", file=sys.stderr)
        return 2

    print(f"Transcribe calls — central={root}  days={args.days}  backend=Google STT")

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

        ok, failed, skipped = 0, 0, 0
        for calls_dir, session in work:
            try:
                _transcribe_session_via_google_stt(
                    session=session,
                    calls_dir=calls_dir,
                    output_dir=calls_dir,
                )
                ok += 1
                print(f"  [google-stt] {session}")
            except Exception as e:
                count = _increment_failure(calls_dir, session)
                print(f"  FAILED {session} (attempt {count}): {e}",
                      file=sys.stderr)
                if count >= MAX_TRANSCRIBE_FAILURES:
                    print(f"  [poison-pill] {session} failed {count}x — "
                          f"writing failed transcript to stop retrying.",
                          file=sys.stderr)
                    _write_failed_transcript(calls_dir, session)
                    skipped += 1
                else:
                    failed += 1

        print(f"  done: ok={ok}  failed={failed}  poison-pill={skipped}")
        memory.log_activity(
            task_name="transcribe-calls:run",
            result=f"ok:{ok}/failed:{failed}/skipped:{skipped}",
            technical_details={"ok": ok, "failed": failed,
                               "skipped": skipped, "days": args.days})
        return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
