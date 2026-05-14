"""Voice-activated + auto trigger for call recording (MS Teams calls only).

Two trigger modes (--trigger-mode, default `auto`):

  auto    -> Recording starts/stops based on MS Teams audio-session state
             alone. The moment Teams enters a call (or starts ringing),
             recording begins. When Teams' audio session ends, recording
             stops. Phrase matching also stays armed in this mode so a
             dev can still say "stop recording" to end early.

  phrase  -> Legacy behavior. Recording fires only on a recognized phrase
             (wake-word `nucleus <verb>` or natural bookend like
             "Assalamualaikum" / "Allah Hafez"). The Teams-in-call gate
             still applies to start.

In either mode the daemon also listens for the wake-word and call-bookend
phrases below for early-stop convenience.

  1. Wake-word command  "nucleus <start|stop|...>"  (anchored, English),
  2. Configured natural call-bookend phrase, e.g. "Assalamualaikum"
     (start) or "Allah Hafez" (stop) — multilingual, substring match.

Teams-only gate
    The START trigger fires ONLY when MS Teams is actively in a call
    (i.e. ms-teams.exe / Teams.exe has an Active audio session). If
    Teams is just open in the background or you say the start phrase
    in a casual conversation, nothing happens. STOP is unconditional —
    if any recording is in progress, the stop phrase always halts it.
    Pass --allow-any-call to disable the gate (phrase mode only).

Hard cap (--max-call-seconds, default 3600)
    Any single recording is auto-stopped after this many seconds even
    if the call continues. Guards against a stuck audio-session state.

Phrase list lives in `data/teams/voice_phrases.json`. Edit that file
to add or remove phrases — no code change needed. Default ships with
the BD-Bangla/Arabic call-bookend phrases.

Run
    python -m teams.voice_daemon
    python -m teams.voice_daemon --model tiny           # fastest, less accurate
    python -m teams.voice_daemon --model base           # default — multilingual
    python -m teams.voice_daemon --model small          # most accurate, slower
    python -m teams.voice_daemon --trigger-mode phrase  # legacy phrase-only
    python -m teams.voice_daemon --allow-any-call       # disable Teams gate

Stop the daemon with Ctrl+C.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
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
        # Bangla / Bengali greetings
        "assalamualaikum",
        "assalamu alaikum",
        "assalam alaikum",
        "as salam alaikum",
        "as-salamu alaikum",
        "as salamu alaikum",
        "salaam alaikum",
        "salam alaikum",
        # English triggers
        "nucleus start",
        "start record",
        "start recording",
        "start call",
        "record start",
        "call start",
        "record",
        "start",
    ],
    "stop": [
        # Bangla / Bengali farewells
        "allah hafez",
        "allah hafiz",
        "khoda hafez",
        "khoda hafiz",
        "khuda hafez",
        "khuda hafiz",
        # English triggers
        "nucleus stop",
        "stop record",
        "stop recording",
        "end record",
        "end recording",
        "end call",
        "record end",
        "call end",
        "stop call",
        "end",
        "stop",
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


def _excluded_active_call() -> tuple[bool, str]:
    """If the currently-active Teams call resolves to a conversation_id
    in NUCLEUS_EXCLUDE_CHATS, return (True, reason). If no call is
    resolvable yet or no exclusions are configured, return (False, ...).
    Fail-open: if the resolver errors, we record (better to capture a
    legit call than silently drop one)."""
    from teams._exclude import excluded_conversation_ids
    excluded = excluded_conversation_ids()
    if not excluded:
        return (False, "no exclusions configured")
    try:
        from teams import calls as _calls
        import time as _time
        info = _calls.resolve_client_for_recording(
            int(_time.time() * 1000), window_seconds=120,
        )
    except Exception as e:
        return (False, f"resolver error (recording anyway): {e}")
    if not info.get("matched"):
        return (False, f"no active call resolved ({info.get('reason')})")
    cid = info.get("conversation_id") or ""
    if cid in excluded:
        client = info.get("client_name") or "(unknown)"
        return (True, f"call in excluded chat {cid} (client={client})")
    return (False, f"active call cid={cid} is not excluded")


def _start_recording(state: dict) -> None:
    with state["lock"]:
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
            excluded, exc_reason = _excluded_active_call()
            if excluded:
                print(f"[voice] start gated: {exc_reason}. "
                      f"(NUCLEUS_EXCLUDE_CHATS) Pass --allow-any-call to bypass.")
                return
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
        state["call_started_at"] = time.monotonic()
        print(f"[voice] recorder PID {proc.pid}")


def _stop_recording(state: dict, reason: str = "") -> None:
    with state["lock"]:
        proc = state.get("proc")
        if not proc or proc.poll() is not None:
            print("[voice] no recording running, ignoring stop.")
            return
        STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        STOP_FILE.touch()
        suffix = f" ({reason})" if reason else ""
        print(f"[voice] stop sentinel written{suffix}; waiting for recorder to flush...")
        try:
            proc.wait(timeout=10)
            print(f"[voice] recorder exited rc={proc.returncode}")
        except subprocess.TimeoutExpired:
            print("[voice] recorder didn't exit in 10s; leaving it.")
        state["call_started_at"] = None


def _audio_session_watcher(state: dict, stop_evt: threading.Event,
                           poll_interval_s: float = 2.0,
                           stop_debounce: int = 2,
                           max_call_seconds: int = 3600) -> None:
    """Background thread: drive start/stop purely from Teams audio-session state.

    Rising edge (off->on)  : start recording immediately (capture from t=0).
    Falling edge debounced : stop after `stop_debounce` consecutive off polls
                             so brief mid-call session blips don't end the
                             recording prematurely.
    Hard cap               : if a single recording exceeds max_call_seconds,
                             stop it. Does not auto-resume — safety guard
                             against a stuck Active state in pycaw.
    """
    print(f"[voice] auto watcher: poll={poll_interval_s}s, "
          f"stop_debounce={stop_debounce} polls, "
          f"hard_cap={max_call_seconds}s")
    last_active = False
    off_streak = 0
    while not stop_evt.is_set():
        try:
            active, reason = _teams_in_call()
        except Exception as e:
            print(f"[voice] watcher: _teams_in_call errored: {e}")
            active = False
            reason = f"watcher exception: {e}"

        if active and not last_active:
            print(f"[voice] watcher: rising edge — {reason}")
            _start_recording(state)
            off_streak = 0
        elif active:
            off_streak = 0
            started_at = state.get("call_started_at")
            proc = state.get("proc")
            if (started_at is not None and proc is not None
                    and proc.poll() is None):
                elapsed = time.monotonic() - started_at
                if elapsed >= max_call_seconds:
                    print(f"[voice] watcher: hard cap hit "
                          f"(elapsed={elapsed:.0f}s >= {max_call_seconds}s)")
                    _stop_recording(state, reason="hard cap")
                    # No auto-resume: keep last_active=True (sticky) so the
                    # still-Active session can't trigger a new rising edge.
                    # State resets naturally when the call actually ends and
                    # we see the falling edge.
                    off_streak = 0
                    stop_evt.wait(poll_interval_s)
                    continue
        else:
            if last_active:
                off_streak += 1
                if off_streak >= stop_debounce:
                    proc = state.get("proc")
                    if proc is not None and proc.poll() is None:
                        print(f"[voice] watcher: falling edge "
                              f"(off for {off_streak} polls) — {reason}")
                        _stop_recording(state, reason="session ended")
                    off_streak = 0
                    last_active = False
                # else: still debouncing, leave last_active=True
            else:
                off_streak = 0

        if active:
            last_active = True
        stop_evt.wait(poll_interval_s)


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
    ap.add_argument(
        "--trigger-mode",
        default=os.environ.get("NUCLEUS_VOICE_TRIGGER_MODE", "auto"),
        choices=("auto", "phrase"),
        help="auto (default): start/stop on Teams audio-session edges. "
             "phrase: legacy — only fire on a recognized phrase. "
             "Env: NUCLEUS_VOICE_TRIGGER_MODE.",
    )
    ap.add_argument(
        "--max-call-seconds", type=int,
        default=int(os.environ.get("NUCLEUS_MAX_CALL_SECONDS", "3600")),
        help="Hard cap per recording (auto mode). Default 3600s (1h). "
             "Env: NUCLEUS_MAX_CALL_SECONDS.",
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
    print(f"[voice] trigger mode: {args.trigger_mode}")
    print('[voice] listening for start/stop phrases. Ctrl+C to quit.')
    state: dict = {
        "proc": None,
        "allow_any_call": args.allow_any_call,
        "lock": threading.Lock(),
        "call_started_at": None,
    }

    watcher_stop = threading.Event()
    watcher_thread: threading.Thread | None = None
    if args.trigger_mode == "auto":
        watcher_thread = threading.Thread(
            target=_audio_session_watcher,
            args=(state, watcher_stop),
            kwargs={"max_call_seconds": args.max_call_seconds},
            daemon=True,
            name="audio-session-watcher",
        )
        watcher_thread.start()

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
        watcher_stop.set()
        if watcher_thread is not None:
            watcher_thread.join(timeout=5)
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
