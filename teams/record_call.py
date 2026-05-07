"""Record system loopback (call audio) + microphone to two WAV files.

Two ways to stop:
  1. Ctrl+C in this terminal
  2. Create the sentinel file `data/teams/.stop_recording` (lets a separate
     process — e.g. an agent running `python -m teams.stop_recording` —
     stop a recording started in the background)

  data/teams/calls/<YYYYMMDD-HHMMSS>_speaker.wav  -- system speaker output
  data/teams/calls/<YYYYMMDD-HHMMSS>_mic.wav      -- default input mic

Run: python -m teams.record_call
"""
from __future__ import annotations

import datetime
import sys
import threading
import time
import wave
from pathlib import Path

import pyaudiowpatch as pyaudio

CHUNK = 1024
STOP_FILE = Path(__file__).parent.parent / "data" / "teams" / ".stop_recording"


def resolve_loopback(p: pyaudio.PyAudio) -> dict:
    speaker = p.get_device_info_by_index(p.get_default_output_device_info()["index"])
    if speaker.get("isLoopbackDevice"):
        return speaker
    for d in p.get_loopback_device_info_generator():
        if speaker["name"] in d["name"]:
            return d
    raise RuntimeError("No WASAPI loopback device found for default speaker.")


def record(p: pyaudio.PyAudio, dev: dict, path: Path, stop: threading.Event, label: str) -> None:
    rate = int(dev["defaultSampleRate"])
    channels = int(dev["maxInputChannels"])
    stream = p.open(
        format=pyaudio.paInt16,
        channels=channels,
        rate=rate,
        frames_per_buffer=CHUNK,
        input=True,
        input_device_index=dev["index"],
    )
    print(f"  [{label:7}] {path.name}  {rate}Hz {channels}ch  {dev['name']!r}")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
        wf.setframerate(rate)
        while not stop.is_set():
            wf.writeframes(stream.read(CHUNK, exception_on_overflow=False))
    stream.stop_stream()
    stream.close()


def main() -> int:
    out_dir = Path(__file__).parent.parent / "data" / "teams" / "calls"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    spk_path = out_dir / f"{stamp}_speaker.wav"
    mic_path = out_dir / f"{stamp}_mic.wav"

    # Clear any leftover stop sentinel so we don't terminate immediately
    STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STOP_FILE.exists():
        STOP_FILE.unlink()

    p = pyaudio.PyAudio()
    try:
        loopback = resolve_loopback(p)
        mic = p.get_default_input_device_info()

        stop = threading.Event()
        threads = [
            threading.Thread(target=record, args=(p, loopback, spk_path, stop, "speaker"), daemon=True),
            threading.Thread(target=record, args=(p, mic, mic_path, stop, "mic"), daemon=True),
        ]

        print(f"Recording -> {out_dir.resolve()}")
        print(f"Stop with Ctrl+C, or `touch {STOP_FILE}`\n")
        for t in threads:
            t.start()

        try:
            while all(t.is_alive() for t in threads):
                if STOP_FILE.exists():
                    print("\nStop sentinel detected — stopping...")
                    STOP_FILE.unlink()
                    stop.set()
                    break
                for t in threads:
                    t.join(timeout=0.5)
            for t in threads:
                t.join()
        except KeyboardInterrupt:
            print("\nStopping...")
            stop.set()
            for t in threads:
                t.join()
    finally:
        p.terminate()

    print()
    for path in (spk_path, mic_path):
        size = path.stat().st_size / 1024 / 1024 if path.exists() else 0
        print(f"  {path}  ({size:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
