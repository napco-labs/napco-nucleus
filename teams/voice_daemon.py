"""Voice-activated trigger for call recording (MS Teams calls only).

Listens to the default mic, transcribes utterances with
faster-whisper, and triggers start/stop of the call recorder when it
hears either:

  1. The wake-word command  "nucleus <start|stop|...>"  (anchored, English),
  2. A configured natural call-bookend phrase, e.g. "Assalamualaikum"
     (start) or "Allah Hafez" (stop) — multilingual, substring match.

Teams-only gate
    The START trigger fires ONLY when MS Teams is actively in a call
    (i.e. ms-teams.exe / Teams.exe has an Active audio session). If
    Teams is just open in the background or you say the start phrase
    in a casual conversation, nothing happens. STOP is unconditional —
    if any recording is in progress, the stop phrase always halts it.
    Pass --allow-any-call to disable the gate.

Phrase list lives in `data/teams/voice_phrases.json`. Edit that file
to add or remove phrases — no code change needed. Default ships with
the BD-Bangla/Arabic call-bookend phrases.

Triggers
    start phrase  -> (Teams in a call?) spawn `python -m teams.record_call`
    stop phrase   -> write data/teams/.stop_recording sentinel

Run
    python -m teams.voice_daemon
    python -m teams.voice_daemon --model tiny       # fastest, less accurate
    python -m teams.voice_daemon --model base       # default — multilingual
    python -m teams.voice_daemon --model small      # most accurate, slower
    python -m teams.voice_daemon --allow-any-call   # disable Teams gate

Stop the daemon with Ctrl+C.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio

_HERE = Path(__file__).parent.parent
STOP_FILE = _HERE / "data" / "teams" / ".stop_recording"
PHRASE_FILE = _HERE / "data" / "teams" / "voice_phrases.json"

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
SPEECH_RMS = 500
SILENCE_TAIL_MS = 500
MIN_UTTERANCE_MS = 300
MAX_UTTERANCE_MS = 6000

WAKE_RE = re.compile(
    r"^\s*(?:hey\s+)?nucleus\b[\s,.:;!?-]*"
    r"(?P<verb>start|begin|record|recording|stop|end|close|finish|done)\b",
    re.IGNORECASE,
)
START_VERBS = {"start", "begin", "record", "recording"}
STOP_VERBS = {"stop", "end", "close", "finish", "done"}

DEFAULT_PHRASES = {
    "start": [
        "assalamualaikum",
        "assalamu alaikum",
        "assalam alaikum",
        "as salam alaikum",
        "as-salamu alaikum",
        "as salamu alaikum",
        "salaam alaikum",
        "salam alaikum",
    ],
    "stop": [
        "allah hafez",
        "allah hafiz",
        "khoda hafez",
        "khoda hafiz",
        "khuda hafez",
        "khuda hafiz",
    ],
}

_NORM_RE = re.compile(r"[^\w\s]+")

TEAMS_PROC_NAMES = {"ms-teams.exe", "teams.exe", "msteams.exe"}


def _teams_in_call() -> tuple[bool, str]:
    """Return (is_active, reason) using Windows Audio Session API.

    Active includes the ringtone phase — Teams renders the incoming-call
    ringtone through its own audio session, so a teammate saying the
    start phrase while the call is still ringing will trigger the
    recorder before the call is even answered (capturing the full
    "Assalamualaikum" greeting).

    Fail-closed: if we can't query audio sessions for any reason,
    return (False, error) so the gate stays on. Pass --allow-any-call
    to bypass.
    """
    try:
        from pycaw.pycaw import AudioUtilities  # lazy
    except Exception as e:
        return (False, f"pycaw import failed: {e}")
    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception as e:
        return (False, f"GetAllSessions failed: {e}")
    for s in sessions:
        if not s.Process:
            continue
        try:
            name = (s.Process.name() or "").lower()
        except Exception:
            continue
        if name in TEAMS_PROC_NAMES and s.State == 1:
            return (True, f"{name} state=Active")
    return (False, "no Teams session in Active state")


def _normalize(s: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace.

    Whisper produces different spellings/punctuation for the same phrase
    across utterances (e.g. "Assalamu alaikum.", "as-salamu alaikum,")
    so we strip down to a comparable form before substring matching."""
    s = s.lower()
    s = _NORM_RE.sub(" ", s)
    s = " ".join(s.split())
    return s


def _load_phrases() -> dict[str, list[str]]:
    """Load the phrase config, creating the default file if missing."""
    if not PHRASE_FILE.exists():
        PHRASE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PHRASE_FILE.write_text(
            json.dumps(DEFAULT_PHRASES, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[voice] wrote default phrase list to {PHRASE_FILE}")
    try:
        raw = json.loads(PHRASE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[voice] couldn't parse {PHRASE_FILE}: {e}; using defaults.")
        raw = DEFAULT_PHRASES
    out = {"start": [], "stop": []}
    for k in ("start", "stop"):
        for p in raw.get(k, []):
            n = _normalize(str(p))
            if n:
                out[k].append(n)
    return out


def _audio_to_float(buf: bytes) -> np.ndarray:
    return np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0


def _start_recording(state: dict) -> None:
    proc = state.get("proc")
    if proc and proc.poll() is None:
        print("[voice] already recording, ignoring start.")
        return
    if not state.get("allow_any_call", False):
        ok, reason = _teams_in_call()
        if not ok:
            print(f"[voice] start gated: {reason}. "
                  f"Pass --allow-any-call to disable the gate.")
            return
        print(f"[voice] Teams gate OK: {reason}")
    try:
        STOP_FILE.unlink()
    except FileNotFoundError:
        pass
    print("[voice] starting recorder...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "teams.record_call"],
        cwd=str(_HERE),
    )
    state["proc"] = proc
    print(f"[voice] recorder PID {proc.pid}")


def _stop_recording(state: dict) -> None:
    proc = state.get("proc")
    if not proc or proc.poll() is not None:
        print("[voice] no recording running, ignoring stop.")
        return
    STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    STOP_FILE.touch()
    print("[voice] stop sentinel written; waiting for recorder to flush...")
    try:
        proc.wait(timeout=10)
        print(f"[voice] recorder exited rc={proc.returncode}")
    except subprocess.TimeoutExpired:
        print("[voice] recorder didn't exit in 10s; leaving it.")


def _handle_transcript(text: str, state: dict, phrases: dict[str, list[str]]) -> None:
    text = text.strip()
    if not text:
        return
    print(f"[voice] heard: {text!r}")

    m = WAKE_RE.match(text)
    if m:
        verb = m.group("verb").lower()
        if verb in START_VERBS:
            print(f"[voice]   matched wake-word START verb {verb!r}")
            _start_recording(state)
            return
        if verb in STOP_VERBS:
            print(f"[voice]   matched wake-word STOP verb {verb!r}")
            _stop_recording(state)
            return

    norm = _normalize(text)
    for phrase in phrases.get("start", []):
        if phrase in norm:
            print(f"[voice]   matched START phrase {phrase!r}")
            _start_recording(state)
            return
    for phrase in phrases.get("stop", []):
        if phrase in norm:
            print(f"[voice]   matched STOP phrase {phrase!r}")
            _stop_recording(state)
            return


def _open_default_input(p: pyaudio.PyAudio) -> dict:
    return p.get_device_info_by_index(p.get_default_input_device_info()["index"])


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--model", default="base",
        help="faster-whisper model. 'base' (default, multilingual, ~150 MB) "
             "handles Bangla/Arabic call-bookend phrases reliably. Use "
             "'tiny' for faster + lighter (less accurate on uncommon names). "
             "Use 'small' for best accuracy (slower).",
    )
    ap.add_argument(
        "--allow-any-call", action="store_true",
        help="Disable the Teams-only gate. Start phrases will fire even "
             "when MS Teams is not in a call. Default: gate ON.",
    )
    args = ap.parse_args()

    phrases = _load_phrases()
    print(f"[voice] phrase list: "
          f"{len(phrases['start'])} start phrase(s), "
          f"{len(phrases['stop'])} stop phrase(s)")
    print(f"[voice]   start: {phrases['start']}")
    print(f"[voice]   stop:  {phrases['stop']}")

    print(f"[voice] loading faster-whisper {args.model}...")
    from faster_whisper import WhisperModel  # lazy
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    print("[voice] model loaded.")

    p = pyaudio.PyAudio()
    dev = _open_default_input(p)
    print(f"[voice] mic: {dev['name']!r} @ {SAMPLE_RATE} Hz")
    stream = p.open(
        format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
        input=True, frames_per_buffer=FRAME_SAMPLES,
        input_device_index=dev["index"],
    )

    if args.allow_any_call:
        print("[voice] Teams-only gate DISABLED (--allow-any-call).")
    else:
        print("[voice] Teams-only gate ON: start fires only while "
              "MS Teams is ringing or in a call.")
    print('[voice] listening for start/stop phrases. Ctrl+C to quit.')
    state: dict = {"proc": None, "allow_any_call": args.allow_any_call}

    buf: list[bytes] = []
    silent_frames = 0
    silence_tail_frames = SILENCE_TAIL_MS // FRAME_MS
    min_utt_frames = MIN_UTTERANCE_MS // FRAME_MS
    max_utt_frames = MAX_UTTERANCE_MS // FRAME_MS

    try:
        while True:
            data = stream.read(FRAME_SAMPLES, exception_on_overflow=False)
            samples = np.frombuffer(data, dtype=np.int16)
            rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))

            if rms >= SPEECH_RMS:
                if not buf:
                    pass
                buf.append(data)
                silent_frames = 0
                if len(buf) >= max_utt_frames:
                    audio = _audio_to_float(b"".join(buf))
                    segments, _ = model.transcribe(audio, beam_size=1)
                    text = " ".join(s.text for s in segments).strip()
                    _handle_transcript(text, state, phrases)
                    buf = []
                    silent_frames = 0
            elif buf:
                buf.append(data)
                silent_frames += 1
                if silent_frames >= silence_tail_frames:
                    if len(buf) >= min_utt_frames + silence_tail_frames:
                        audio = _audio_to_float(b"".join(buf))
                        segments, _ = model.transcribe(
                            audio, language="en", beam_size=1)
                        text = " ".join(s.text for s in segments).strip()
                        _handle_transcript(text, state, phrases)
                    buf = []
                    silent_frames = 0
    except KeyboardInterrupt:
        print("\n[voice] shutting down.")
    finally:
        proc = state.get("proc")
        if proc and proc.poll() is None:
            print("[voice] recorder still running; sending stop sentinel.")
            STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
            STOP_FILE.touch()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        try:
            stream.stop_stream(); stream.close()
        except Exception:
            pass
        p.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
