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


def _atomic_replace_wav(src_tmp: Path, dst: Path) -> None:
    """Atomically replace `dst` with `src_tmp`. On Windows os.replace is
    atomic on the same volume; on POSIX it's atomic period. Either way,
    a process death mid-write leaves dst untouched and src_tmp orphaned
    (cleanable on next run) instead of a corrupt dst."""
    os.replace(str(src_tmp), str(dst))

import numpy as np
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


def _denoise_mic_wav(path: Path,
                     mains_hz: float = 50.0,
                     max_harmonic_hz: float = 1000.0,
                     notch_width_hz: float = 4.0,
                     hpf_cutoff_hz: float = 40.0) -> None:
    """Remove mains hum + low-freq rumble from an int16 mic WAV (FFT, in place).

    Bangladesh / Europe / most of Asia is on a 50 Hz grid; the US +
    parts of the Americas are 60 Hz. Set NUCLEUS_MIC_MAINS_HZ=60 in
    .env to switch. A poorly-grounded USB sound card picks up mains
    and its odd harmonics (50, 150, 250, 350 Hz...) which sound like
    a continuous "system" hum/buzz once normalize boosts the signal.

    This filter:
      1. High-pass below hpf_cutoff_hz to kill DC offset + sub-audible.
      2. Narrow notches at every multiple of mains_hz up to
         max_harmonic_hz. Notches are notch_width_hz wide each, which
         is narrow enough not to dent speech (~85+ Hz fundamental,
         formants well away from the comb).
    """
    try:
        with wave.open(str(path), "rb") as wf:
            params = wf.getparams()
            n_frames = wf.getnframes()
            n_channels = wf.getnchannels()
            sr = wf.getframerate()
            if n_frames == 0:
                return
            frames = wf.readframes(n_frames)
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
        samples = samples.reshape(-1, n_channels)
        freqs = np.fft.rfftfreq(samples.shape[0], 1.0 / sr)
        mask = np.ones_like(freqs)

        # High-pass below hpf_cutoff_hz (kills DC and sub-audible rumble).
        mask[freqs < hpf_cutoff_hz] = 0.0

        # Notch every multiple of mains_hz up to max_harmonic_hz.
        half_w = notch_width_hz / 2.0
        f = mains_hz
        notch_count = 0
        while f <= max_harmonic_hz and f < sr / 2:
            mask[(freqs >= f - half_w) & (freqs <= f + half_w)] = 0.0
            notch_count += 1
            f += mains_hz

        out = np.empty_like(samples)
        for ch in range(n_channels):
            spec = np.fft.rfft(samples[:, ch])
            out[:, ch] = np.fft.irfft(spec * mask, n=samples.shape[0])
        out = np.clip(out.reshape(-1), -32768, 32767).astype(np.int16)
        # Write to a sibling temp file then atomic-rename so a process
        # death mid-write can't leave a corrupt or partially-truncated
        # WAV in the canonical path.
        tmp_path = path.with_suffix(path.suffix + ".denoise.tmp")
        try:
            with wave.open(str(tmp_path), "wb") as wf:
                wf.setparams(params)
                wf.writeframes(out.tobytes())
            _atomic_replace_wav(tmp_path, path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        print(f"  mic denoise: hpf<{hpf_cutoff_hz:.0f}Hz, "
              f"{notch_count} notches at multiples of {mains_hz:.0f}Hz "
              f"(width {notch_width_hz:.1f}Hz, up to {max_harmonic_hz:.0f}Hz)")
    except Exception as e:
        print(f"  mic denoise FAILED: {e}", file=sys.stderr)


def _normalize_mic_wav(path: Path, target_dbfs: float = 1.0,
                       max_gain_db: float = 30.0) -> None:
    """Peak-normalize an int16 PCM mic WAV to target dBFS in-place.

    Teams applies AGC on the outgoing call audio but our recorder
    captures raw mic, so the mic WAV ends up much quieter than the
    speaker loopback (which is post-AGC). Normalizing on disk after
    the recording stops adapts per-PC and per-call without clipping
    risk in the realtime path.

    `max_gain_db` caps the scale factor so a quiet/silent recording
    doesn't blow up the noise floor. `target_dbfs` is the peak target;
    at +1 dBFS a small percentage of transient peaks land slightly
    past int16 max and get hard-clipped by np.clip below -- perceived
    loudness bumps ~2 dB vs the prior -1 dBFS target, no distortion
    on speech since transients are sparse.

    Override via env: NUCLEUS_MIC_TARGET_DBFS, NUCLEUS_MIC_MAX_GAIN_DB.
    """
    # Honor env overrides so a noisy PC can dial down without an
    # edit + redeploy. Numeric parse failures fall back to defaults.
    try:
        target_dbfs = float(os.environ.get(
            "NUCLEUS_MIC_TARGET_DBFS", str(target_dbfs)))
    except ValueError:
        pass
    try:
        max_gain_db = float(os.environ.get(
            "NUCLEUS_MIC_MAX_GAIN_DB", str(max_gain_db)))
    except ValueError:
        pass
    try:
        with wave.open(str(path), "rb") as wf:
            params = wf.getparams()
            n_frames = wf.getnframes()
            if n_frames == 0:
                return
            frames = wf.readframes(n_frames)
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
        peak = float(np.max(np.abs(samples)))
        if peak < 1.0:
            return  # silent
        target_peak = 32768.0 * (10 ** (target_dbfs / 20.0))
        scale = target_peak / peak
        max_scale = 10 ** (max_gain_db / 20.0)
        scale = min(scale, max_scale)
        if abs(scale - 1.0) < 0.01:
            return  # negligible
        gain_db = 20.0 * float(np.log10(scale))
        samples = np.clip(samples * scale, -32768, 32767).astype(np.int16)
        # Temp-write + atomic-rename so a crash here can't corrupt the
        # WAV that denoise just successfully produced.
        tmp_path = path.with_suffix(path.suffix + ".normalize.tmp")
        try:
            with wave.open(str(tmp_path), "wb") as wf:
                wf.setparams(params)
                wf.writeframes(samples.tobytes())
            _atomic_replace_wav(tmp_path, path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        print(f"  mic normalize: peak {peak:.0f} -> "
              f"{int(peak * scale)}, gain {gain_db:+.1f} dB")
    except Exception as e:
        print(f"  mic normalize FAILED: {e}", file=sys.stderr)


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
    from teams._central import ensure_smb_auth
    ensure_smb_auth(os.environ.get("NUCLEUS_CENTRAL_PATH", ""))
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

    ended_dt = datetime.datetime.now()
    duration_s = (ended_dt - started_dt).total_seconds()

    # Mic post-processing on the recorder side. Order matters:
    #   1. Denoise FIRST -- kills mains hum + sub-audible rumble. If we
    #      normalize first, peak amplitude includes hum -> headroom
    #      wasted on noise instead of speech.
    #   2. Normalize -- bring speech peak to a reasonable dBFS.
    # Both toggleable via env so a dev can disable them if needed.
    if mic_path.exists() and mic_path.stat().st_size > 0:
        if os.environ.get("NUCLEUS_MIC_DENOISE", "1") != "0":
            try:
                mains_hz = float(os.environ.get("NUCLEUS_MIC_MAINS_HZ", "50"))
            except ValueError:
                mains_hz = 50.0
            _denoise_mic_wav(mic_path, mains_hz=mains_hz)
        if os.environ.get("NUCLEUS_MIC_NORMALIZE", "1") != "0":
            _normalize_mic_wav(mic_path)

    # Discard sessions shorter than the configured minimum (default 20s).
    # In auto-trigger mode the daemon fires on any Teams audio-session
    # edge — that includes a ringing-then-declined call and brief voice
    # notes / playback. A short WAV would waste Whisper time on central.
    try:
        min_duration_s = float(os.environ.get("NUCLEUS_CALL_MIN_DURATION_S", "20"))
    except ValueError:
        min_duration_s = 20.0
    if duration_s < min_duration_s:
        print(f"  duration {duration_s:.1f}s < min {min_duration_s:.1f}s — "
              f"discarding WAVs, skipping metadata + upload.")
        for path in (spk_path, mic_path):
            try:
                if path.exists():
                    path.unlink()
            except Exception as e:
                print(f"  delete {path.name} FAILED: {e}", file=sys.stderr)
        return 0

    # Resolve client + write metadata + push to central if configured.
    _write_metadata_and_upload(
        out_dir=out_dir,
        stamp=stamp,
        started_dt=started_dt,
        ended_dt=ended_dt,
        spk_path=spk_path,
        mic_path=mic_path,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
