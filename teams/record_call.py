"""Record system loopback (call audio) + microphone to two WAV files.

Two ways to stop:
  1. Ctrl+C in this terminal
  2. Create the sentinel file `data/teams/.stop_recording` (lets a separate
     process — e.g. an agent running `python -m teams.stop_recording` —
     stop a recording started in the background)

  data/teams/calls/<YYYYMMDD-HHMMSS>_speaker.wav  -- system speaker output
  data/teams/calls/<YYYYMMDD-HHMMSS>_mic.wav      -- default input mic
  data/teams/calls/<YYYYMMDD-HHMMSS>.json         -- metadata sidecar

After stop, this script:
  1. Resolves the client(s) by walking Teams IndexedDB Event/Call entries
     near the recording start time (teams.calls.resolve_client_for_recording).
  2. Writes a metadata sidecar JSON next to the WAVs.
  3. If NUCLEUS_CENTRAL_PATH is set, copies all three files to
     <central>/<dev>/<YYYY-MM-DD>/calls/  for the agent host to identify.

Run: python -m teams.record_call
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import socket
import sys
import threading
import time
import wave
from pathlib import Path

import pyaudiowpatch as pyaudio

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

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


def _write_metadata_and_upload(
    *,
    out_dir: Path,
    stamp: str,
    started_dt: datetime.datetime,
    ended_dt: datetime.datetime,
    spk_path: Path,
    mic_path: Path,
) -> None:
    """Resolve client info, write the JSON sidecar, optionally push to central.

    Best-effort everywhere — never raises. If client resolution fails,
    metadata.client_name = "(unknown)". If upload fails, log + continue.
    """
    started_at_ms = int(started_dt.timestamp() * 1000)
    ended_at_ms = int(ended_dt.timestamp() * 1000)
    duration_s = round((ended_at_ms - started_at_ms) / 1000.0, 1)

    # Resolve client via Teams IndexedDB. Best-effort.
    client_info: dict = {"matched": False, "reason": "resolver not run"}
    try:
        from teams.calls import resolve_client_for_recording
        client_info = resolve_client_for_recording(
            started_at_ms, window_seconds=180)
    except Exception as e:
        client_info = {"matched": False, "reason": f"resolver error: {e}"}

    if client_info.get("matched"):
        print(f"  client: {client_info.get('client_name')} "
              f"(call_id={client_info.get('call_id')[:8]}..., "
              f"delta={client_info.get('delta_seconds'):.1f}s)")
    else:
        print(f"  client: (unknown) [{client_info.get('reason')}]")

    metadata = {
        "session": stamp,
        "dev_name": _dev_name(),
        "hostname": socket.gethostname(),
        "started_at": started_dt.isoformat(timespec="seconds"),
        "ended_at": ended_dt.isoformat(timespec="seconds"),
        "started_at_ms": started_at_ms,
        "ended_at_ms": ended_at_ms,
        "duration_seconds": duration_s,
        "files": {
            "mic": mic_path.name if mic_path.exists() else None,
            "speaker": spk_path.name if spk_path.exists() else None,
            "mic_size_bytes": (mic_path.stat().st_size if mic_path.exists() else 0),
            "speaker_size_bytes": (spk_path.stat().st_size if spk_path.exists() else 0),
        },
        "client_info": client_info,
        "client_name": client_info.get("client_name", "(unknown)"),
    }

    meta_path = out_dir / f"{stamp}.json"
    try:
        meta_path.write_text(
            json.dumps(metadata, indent=2, default=str), encoding="utf-8")
        print(f"  metadata: {meta_path.name}")
    except Exception as e:
        print(f"  metadata write FAILED: {e}", file=sys.stderr)
        return

    # Optional central push
    central_dir = _central_calls_dir()
    if central_dir is None:
        print("  central upload: skipped (NUCLEUS_CENTRAL_PATH not set)")
        return
    try:
        central_dir.mkdir(parents=True, exist_ok=True)
        for src in (mic_path, spk_path, meta_path):
            if not src.exists():
                continue
            dst = central_dir / src.name
            shutil.copy2(str(src), str(dst))
            size_mb = src.stat().st_size / 1024 / 1024
            print(f"  -> {dst}  ({size_mb:.1f} MB)")
        print(f"  central upload: OK ({central_dir})")
    except Exception as e:
        print(f"  central upload FAILED: {e}", file=sys.stderr)
        print(f"  WAVs + metadata are still local at {out_dir}", file=sys.stderr)


def _dev_name() -> str:
    raw = (os.environ.get("NUCLEUS_DEV_NAME") or "").strip()
    if raw:
        return raw
    return (os.environ.get("USERNAME") or os.environ.get("USER")
            or socket.gethostname() or "unknown").strip()


def _central_calls_dir() -> Path | None:
    raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    if not raw:
        return None
    day = datetime.date.today().strftime("%Y-%m-%d")
    return Path(raw) / _dev_name() / day / "calls"


def main() -> int:
    out_dir = Path(__file__).parent.parent / "data" / "teams" / "calls"
    out_dir.mkdir(parents=True, exist_ok=True)
    started_dt = datetime.datetime.now()
    stamp = started_dt.strftime("%Y%m%d-%H%M%S")
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

    # Resolve client + write metadata + push to central if configured.
    _write_metadata_and_upload(
        out_dir=out_dir,
        stamp=stamp,
        started_dt=started_dt,
        ended_dt=datetime.datetime.now(),
        spk_path=spk_path,
        mic_path=mic_path,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
