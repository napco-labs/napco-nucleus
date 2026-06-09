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

# Marker dropped while a recording is in progress and removed on clean
# finalize. Its presence at daemon startup means the previous recording
# did NOT stop cleanly (the daemon — or the whole PC — died mid-call).
# voice_daemon reads this on boot to recover the orphaned audio instead
# of losing the call. Holds the recorder PID + the WAV paths + start time.
MARKER_FILE = Path(__file__).parent.parent / "data" / "teams" / ".recording_active"

# PortAudio error codes that mean "the device went away" (e.g. a USB
# headset unplugged and replugged into another port mid-call) rather
# than "we're done". On any of these we re-enumerate the devices and
# reopen the stream on the device's NEW port instead of ending the track.
#   -9988 paStreamIsStopped / stream closed   (the Atik mid-call replug)
#   -9986 paDeviceUnavailable
#   -9985 paIncompatibleStreamHostApi
#   -9999 paUnanticipatedHostError (generic WASAPI device-revoked)
#   -9978 paInternalError seen on hot-unplug
_DEVICE_LOST_ERRNOS = {-9988, -9986, -9985, -9984, -9978, -9999}

# How long to keep trying to rediscover a device that vanished mid-call
# before giving up on that track. Covers the seconds a dev spends moving
# the plug from one USB port to another.
try:
    _RECONNECT_WINDOW_S = float(os.environ.get("NUCLEUS_RECONNECT_WINDOW_S", "45"))
except ValueError:
    _RECONNECT_WINDOW_S = 45.0

# Seconds of ZERO speaker-loopback frames into an active call before we assume
# the WASAPI default output is a silent/idle device (e.g. a monitor or S/PDIF
# is the Windows default while the call audio is actually on the headset) and
# switch to whichever render endpoint is really delivering audio.
try:
    _SPEAKER_SILENT_SWITCH_S = float(os.environ.get("NUCLEUS_SPEAKER_SWITCH_S", "5"))
except ValueError:
    _SPEAKER_SILENT_SWITCH_S = 5.0

# Pa_Initialize / Pa_Terminate are reference-counted but not guaranteed
# thread-safe to call concurrently. Each track owns its own PyAudio
# instance and may re-init on reconnect, so serialize create/terminate.
_PA_LOCK = threading.Lock()


def _make_pyaudio() -> "pyaudio.PyAudio":
    """Create a fresh PyAudio instance under the global PA lock.

    A new instance re-runs Pa_Initialize, which is the ONLY way PortAudio
    re-enumerates a USB device that moved to a different port — so the
    reconnect path must build a new one, not reuse the old handle.
    """
    with _PA_LOCK:
        return pyaudio.PyAudio()


def _terminate_pa(p) -> None:
    if p is None:
        return
    with _PA_LOCK:
        try:
            p.terminate()
        except Exception:
            pass

# Registry property key that controls exclusive-mode on Windows audio devices.
_EXCL_MODE_PROP = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"
_MMDEV_BASE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
_CAPTURE_REG_PATH = _MMDEV_BASE + r"\Capture"   # mic / input endpoints
_RENDER_REG_PATH = _MMDEV_BASE + r"\Render"     # speaker / output endpoints

_HEADSET_KEYWORDS = [
    "headset", "headphone", "logitech", "logi", "jabra", "plantronics",
    "sennheiser", "bose", "hyperx", "corsair", "razer", "speakers",
]


def _find_audio_endpoints() -> list[tuple[str, str]]:
    """Return [(kind, guid), ...] for every ACTIVE audio endpoint.

    We free exclusive mode on ALL active render + capture endpoints rather than
    matching a headset by name — name/keyword matching missed the real device on
    some PCs (e.g. a Realtek/built-in mic), leaving the default mic OR speaker
    locked by Teams and that track recording 0 bytes (2026-06-08). Touching the
    actual default devices is the only reliable way; AllowExclusiveMode=0 on an
    unused device is harmless. MMDEVAPI InstanceIds encode the data-flow:
    {0.0.0.*}=render (speaker/out), {0.0.1.*}=capture (mic/in); the trailing
    {GUID} is the MMDevices registry key.
    """
    import re
    import subprocess
    import json
    # Single pipeline — a `foreach (...) {...} | ConvertTo-Json` block fails with
    # "An empty pipe element is not allowed" when passed via powershell -Command,
    # which silently made this return [] on every PC (so exclusive mode was never
    # actually disabled). Fixed 2026-06-08.
    script = (
        "Get-PnpDevice -Class AudioEndpoint -Status OK -ErrorAction SilentlyContinue "
        "| Select-Object FriendlyName, InstanceId | ConvertTo-Json -Depth 2"
    )
    found: list[tuple[str, str]] = []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        if not out:
            return found
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        for item in data:
            iid = item.get("InstanceId", "") or ""
            m = re.search(r"\{[0-9A-Fa-f\-]{36}\}$", iid)
            if not m:
                continue
            guid = m.group(0)
            if "{0.0.1" in iid:
                kind = "capture"
            elif "{0.0.0" in iid:
                kind = "render"
            else:  # fall back to the friendly name
                name = (item.get("FriendlyName") or "").lower()
                kind = "capture" if ("microphone" in name or "mic" in name) else "render"
            found.append((kind, guid))
    except Exception:
        pass
    return found


# Back-compat alias.
def _find_headset_audio_endpoints() -> list[tuple[str, str]]:
    return _find_audio_endpoints()


def _find_headset_guid_via_pnp() -> str | None:
    """Back-compat: first capture (mic) endpoint GUID, or None."""
    for kind, guid in _find_audio_endpoints():
        if kind == "capture":
            return guid
    return None


def _disable_exclusive_mode_for_mic() -> None:
    """Disable exclusive mode for BOTH the headset mic AND speaker endpoints.

    Teams can grab the OUTPUT (render) device in exclusive mode, which makes
    the WASAPI loopback capture 0 bytes — the speaker track came up empty
    while the mic recorded fine (2026-06-08). Disabling exclusive mode on the
    render endpoint too lets the loopback capture the remote party's audio.
    Writes AllowExclusiveMode=0 under the correct MMDevices hive (Capture or
    Render) for each headset endpoint GUID. Runs before every recording and
    on reconnect; works on any USB port. Windows-only; skips elsewhere.
    """
    if sys.platform != "win32":
        return
    try:
        import winreg
    except Exception:
        return
    endpoints = _find_audio_endpoints()
    if not endpoints:
        print("  [audio] no audio endpoints via PnP — skipping exclusive mode fix")
        return
    for kind, guid in endpoints:
        base = _RENDER_REG_PATH if kind == "render" else _CAPTURE_REG_PATH
        prop_path = f"{base}\\{guid}\\Properties"
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, prop_path,
                access=winreg.KEY_SET_VALUE | winreg.KEY_READ,
            ) as props:
                winreg.SetValueEx(props, _EXCL_MODE_PROP, 0, winreg.REG_DWORD, 0)
            print(f"  [audio] exclusive mode disabled for {kind} {guid}")
        except FileNotFoundError:
            pass  # endpoint not in this hive (unplugged) — skip quietly
        except Exception as e:
            print(f"  [audio] exclusive mode fix skipped for {kind} {guid}: {e}",
                  file=sys.stderr)


def resolve_loopback(p: pyaudio.PyAudio) -> dict:
    # Primary: PyAudioWPatch pairs the loopback to the WASAPI default output
    # device BY INDEX, so it works even when PortAudio can't read the device
    # friendly names. In some session contexts (notably a scheduled-task
    # daemon) the names come back as '{0.0.0.00000000}.{guid}' for the speaker
    # and 'baddevN [Loopback]' for the loopbacks — the old name-substring match
    # could then never succeed, the speaker thread raised, and the remote
    # party's audio was lost (2026-06-09, hit on both Atik .108 and Titu .71).
    try:
        lb = p.get_default_wasapi_loopback()
        if lb:
            return lb
    except Exception:
        pass
    # Fallback: default output is itself a loopback, or match it by name.
    try:
        speaker = p.get_device_info_by_index(p.get_default_output_device_info()["index"])
        if speaker.get("isLoopbackDevice"):
            return speaker
        name = speaker.get("name") or ""
        if name:
            for d in p.get_loopback_device_info_generator():
                if name in d["name"]:
                    return d
    except Exception:
        pass
    raise RuntimeError("No WASAPI loopback device found for default speaker.")


def _probe_active_loopback(p: pyaudio.PyAudio, exclude_index=None,
                           probe_s: float = 1.5) -> dict | None:
    """Return a render-endpoint loopback that is ACTIVELY delivering frames.

    Used as a self-heal when the WASAPI default-output loopback stays silent
    during a live call — meaning the Windows default output is an idle device
    (monitor / S/PDIF) but the call audio is really playing on another endpoint
    (the headset). We open each other loopback briefly and pick the first one
    that has frames available, i.e. the endpoint something is actually playing
    to. Returns None if no endpoint is delivering audio.
    """
    try:
        candidates = list(p.get_loopback_device_info_generator())
    except Exception:
        return None
    for d in candidates:
        if exclude_index is not None and d.get("index") == exclude_index:
            continue
        s = None
        try:
            rate = int(d["defaultSampleRate"])
            ch = int(d.get("maxInputChannels", 0)) or 2
            s = p.open(format=pyaudio.paInt16, channels=ch, rate=rate,
                       frames_per_buffer=CHUNK, input=True,
                       input_device_index=d["index"])
            deadline = time.monotonic() + probe_s
            while time.monotonic() < deadline:
                if s.get_read_available() >= CHUNK:
                    return d
                time.sleep(0.03)
        except Exception:
            pass
        finally:
            try:
                if s is not None:
                    s.stop_stream()
                    s.close()
            except Exception:
                pass
    return None


def _resolve_device(p: pyaudio.PyAudio, label: str) -> dict:
    """Resolve the input device for a track on a *fresh* PyAudio instance.

    Called both at startup and after a mid-call reconnect. Because it
    re-runs against a re-enumerated PyAudio, a headset that was moved to
    another USB port is rediscovered by IDENTITY (its name), not by a
    stale device index — this is the "find the device, register its new
    port" idea applied live, mid-call.

      speaker -> the WASAPI loopback of the default output device.
      mic     -> the known headset (Logitech/Jabra/...) by name if present,
                 else the system default input.
    """
    if label == "speaker":
        return resolve_loopback(p)
    # mic: follow the physical headset across ports by matching its name,
    # so unplug-and-replug-elsewhere still lands on the same device.
    try:
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if int(info.get("maxInputChannels", 0)) > 0 and any(
                kw in (info.get("name") or "").lower() for kw in _HEADSET_KEYWORDS
            ):
                return info
    except Exception:
        pass
    return p.get_default_input_device_info()


def _errno_of(e: OSError):
    """Best-effort extraction of the integer PortAudio error code."""
    if e.args and isinstance(e.args[0], int):
        return e.args[0]
    if getattr(e, "errno", None) is not None:
        return e.errno
    return None


def record(path: Path, stop: threading.Event, label: str,
           reconnect_window_s: float | None = None) -> None:
    """Record one track to `path`, SURVIVING a mid-call device change.

    Owns its own PyAudio instance so it can terminate + re-init — the only
    way PortAudio re-enumerates a USB device moved to a new port — without
    disturbing the other track. On a "device lost" read error the stream is
    reopened against the rediscovered device and writing CONTINUES into the
    same WAV. So an Atik-style mid-call replug no longer truncates the call:
    the gap during the unplug is a few seconds of silence, then audio
    resumes, instead of the track dying outright.

    A genuinely fatal error (or the device not returning within
    reconnect_window_s) still ends just this track; the main loop keeps the
    other side going.
    """
    if reconnect_window_s is None:
        reconnect_window_s = _RECONNECT_WINDOW_S

    p = _make_pyaudio()
    stream = None
    try:
        dev = _resolve_device(p, label)
        # Lock the WAV format to the FIRST successful open. Reconnects
        # request this same rate/channels (WASAPI shared mode converts),
        # so the single output WAV stays internally consistent even if the
        # reattached device reports a different native format.
        rate = int(dev["defaultSampleRate"])
        channels = int(dev["maxInputChannels"]) or 1
        sampwidth = p.get_sample_size(pyaudio.paInt16)
        stream = p.open(
            format=pyaudio.paInt16, channels=channels, rate=rate,
            frames_per_buffer=CHUNK, input=True,
            input_device_index=dev["index"],
        )
        print(f"  [{label:7}] {path.name}  {rate}Hz {channels}ch  {dev['name']!r}")

        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(rate)
            lost_since = None  # monotonic time the device first went away
            frames_written = 0          # frames written to this track so far
            nonsilent_seen = False      # did we ever capture a non-zero sample?
            t_start = time.monotonic()
            tried_loopback_switch = False  # speaker self-heal attempted?
            while not stop.is_set():
                # --- Reconnect state: stream is down, try to rebuild it ---
                if stream is None:
                    now = time.monotonic()
                    if now - lost_since > reconnect_window_s:
                        print(f"  [{label:7}] device did not come back within "
                              f"{reconnect_window_s:.0f}s; ending this track.",
                              file=sys.stderr)
                        break
                    if stop.wait(1.0):  # brief backoff between attempts; honors stop
                        break
                    try:
                        p = _make_pyaudio()
                        # The new port's endpoint may have exclusive mode
                        # re-enabled — clear it again so Teams can't hold the
                        # mic and lock us out.
                        if label == "mic":
                            _disable_exclusive_mode_for_mic()
                        dev = _resolve_device(p, label)
                        stream = p.open(
                            format=pyaudio.paInt16, channels=channels, rate=rate,
                            frames_per_buffer=CHUNK, input=True,
                            input_device_index=dev["index"],
                        )
                        lost_since = None
                        print(f"  [{label:7}] reconnected -> {dev['name']!r} "
                              f"(port re-registered); recording resumes.")
                    except Exception as re:
                        # Device still mid-replug / not back yet. Drop the
                        # half-built instance and retry until the window ends.
                        _terminate_pa(p)
                        p = None
                        print(f"  [{label:7}] reconnect attempt failed "
                              f"({re}); retrying...", file=sys.stderr)
                    continue

                # --- Speaker self-heal: default output is a SILENT device ---
                # If the speaker loopback produced ZERO frames a few seconds
                # into the (already-Active) call, the Windows default output
                # isn't where the call audio is playing — switch to whatever
                # render endpoint is actually delivering audio (the headset).
                if (label == "speaker" and not tried_loopback_switch
                        and frames_written == 0
                        and time.monotonic() - t_start >= _SPEAKER_SILENT_SWITCH_S):
                    tried_loopback_switch = True  # one shot — don't thrash
                    alt = _probe_active_loopback(p, exclude_index=dev.get("index"))
                    if alt is not None:
                        print(f"  [speaker] default output silent for "
                              f"{_SPEAKER_SILENT_SWITCH_S:.0f}s — switching to "
                              f"active endpoint {alt['name']!r}.", file=sys.stderr)
                        try:
                            stream.stop_stream()
                            stream.close()
                        except Exception:
                            pass
                        try:
                            stream = p.open(
                                format=pyaudio.paInt16, channels=channels,
                                rate=rate, frames_per_buffer=CHUNK, input=True,
                                input_device_index=alt["index"],
                            )
                            dev = alt
                        except Exception as se:
                            print(f"  [speaker] switch failed ({se}); ending "
                                  f"this track.", file=sys.stderr)
                            break

                # --- Normal path: non-blocking, stop-aware read + write -----
                # WASAPI loopback only delivers frames while the endpoint is
                # active; a blocking read() hangs on post-call silence so the
                # recorder never finalizes (the 'stuck recorder' / 0-byte
                # tracks). Poll what's available and stay responsive to stop.
                try:
                    if stream.get_read_available() < CHUNK:
                        if stop.wait(0.05):
                            break
                        continue
                    data = stream.read(CHUNK, exception_on_overflow=False)
                except OSError as e:
                    errno = _errno_of(e)
                    if errno not in _DEVICE_LOST_ERRNOS:
                        # Not a hot-unplug — a real, non-recoverable error.
                        print(f"  [{label:7}] stream.read failed ({e!r}); "
                              f"ending this track. The other side keeps "
                              f"recording.", file=sys.stderr)
                        break
                    # Device lost mid-call (e.g. Atik moved the USB plug).
                    # Tear the dead stream + instance down so the rebuilt
                    # PyAudio re-enumerates the device on its NEW port, then
                    # fall into the reconnect state above.
                    print(f"  [{label:7}] device lost ({errno}) — likely a "
                          f"mid-call port change. Re-finding the device and "
                          f"reopening on its new port...", file=sys.stderr)
                    try:
                        stream.close()
                    except Exception:
                        pass
                    stream = None
                    _terminate_pa(p)
                    p = None
                    lost_since = time.monotonic()
                    continue

                wf.writeframes(data)
                frames_written += CHUNK
                if not nonsilent_seen and any(data):
                    nonsilent_seen = True

            # Loud, non-silent failure: make a missing/empty speaker track
            # obvious in the log instead of a mysterious 0-byte file.
            if label == "speaker":
                if frames_written == 0:
                    print("  [speaker] WARNING: captured 0 frames — no render "
                          "endpoint delivered audio (is the call device the "
                          "Windows default output?). Speaker track is empty.",
                          file=sys.stderr)
                elif not nonsilent_seen:
                    print("  [speaker] WARNING: captured only silence — the "
                          "call audio may be on a different output device.",
                          file=sys.stderr)
    finally:
        try:
            if stream is not None:
                stream.stop_stream()
                stream.close()
        except Exception:
            pass
        _terminate_pa(p)


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


def _write_marker(stamp: str, out_dir: Path, started_dt: datetime.datetime,
                  spk_path: Path, mic_path: Path) -> None:
    """Record that a capture is in progress so a crash can be recovered."""
    try:
        MARKER_FILE.parent.mkdir(parents=True, exist_ok=True)
        MARKER_FILE.write_text(json.dumps({
            "stamp": stamp,
            "pid": os.getpid(),
            "out_dir": str(out_dir),
            "spk_path": str(spk_path),
            "mic_path": str(mic_path),
            "started_at": started_dt.isoformat(timespec="seconds"),
            "started_at_ms": int(started_dt.timestamp() * 1000),
        }, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  [marker] write failed (crash recovery disabled "
              f"for this call): {e}", file=sys.stderr)


def _clear_marker() -> None:
    try:
        MARKER_FILE.unlink()
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"  [marker] clear failed: {e}", file=sys.stderr)


def _repair_wav_header(path: Path) -> bool:
    """Rewrite the RIFF/data sizes of a WAV left unclosed by a crash.

    The `wave` writer fills the RIFF + data chunk sizes only on close(). A
    process killed mid-call leaves a 44-byte PCM header with stale (often
    zero) sizes even though every captured sample IS on disk after the
    header. We recompute both size fields from the real file length so the
    audio becomes readable/transcribable. Returns True if the file now
    looks like a valid non-empty WAV.
    """
    try:
        size = path.stat().st_size
        if size < 44:
            return False
        with open(path, "r+b") as f:
            head = f.read(44)
            if head[0:4] != b"RIFF" or head[8:12] != b"WAVE":
                return False
            # Standard 44-byte PCM header: 'data' length tag at offset 40,
            # audio bytes follow at 44. (Our writer always emits this layout.)
            if head[36:40] != b"data":
                return False
            data_bytes = size - 44
            riff_size = size - 8
            f.seek(4)
            f.write(riff_size.to_bytes(4, "little"))
            f.seek(40)
            f.write(data_bytes.to_bytes(4, "little"))
        return data_bytes > 0
    except Exception as e:
        print(f"  [recover] WAV header repair failed for {path.name}: {e}",
              file=sys.stderr)
        return False


def _postprocess_and_upload(*, out_dir: Path, stamp: str,
                            started_dt: datetime.datetime,
                            ended_dt: datetime.datetime,
                            spk_path: Path, mic_path: Path) -> int:
    """Mic denoise/normalize, min-duration discard, then metadata + upload.

    Shared by the normal end-of-call path and the crash-recovery finalize
    so both behave identically. Returns 0 always (best-effort).
    """
    duration_s = (ended_dt - started_dt).total_seconds()

    # Mic post-processing. Order: denoise FIRST (kill hum before measuring
    # peak), then normalize. Both toggleable via env.
    if mic_path.exists() and mic_path.stat().st_size > 0:
        if os.environ.get("NUCLEUS_MIC_DENOISE", "1") != "0":
            try:
                mains_hz = float(os.environ.get("NUCLEUS_MIC_MAINS_HZ", "50"))
            except ValueError:
                mains_hz = 50.0
            _denoise_mic_wav(mic_path, mains_hz=mains_hz)
        if os.environ.get("NUCLEUS_MIC_NORMALIZE", "1") != "0":
            _normalize_mic_wav(mic_path)

    # Discard sessions shorter than the configured minimum (default 20s) —
    # ringing-then-declined, voice notes, playback blips. Keeps junk off
    # central even though we now START FROM THE RING.
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

    _write_metadata_and_upload(
        out_dir=out_dir, stamp=stamp,
        started_dt=started_dt, ended_dt=ended_dt,
        spk_path=spk_path, mic_path=mic_path,
    )
    return 0


def finalize_orphan() -> int:
    """Recover a recording the daemon/PC died on — called at daemon boot.

    Reads MARKER_FILE, repairs the unclosed WAV headers so the partial
    audio is usable, then runs the same post-process + upload as a normal
    call. The few seconds lost at the crash instant are unavoidable, but
    the rest of the call is preserved and pushed to central instead of
    being thrown away. Always clears the marker so we don't loop.
    """
    if not MARKER_FILE.exists():
        print("[recover] no in-progress marker — nothing to finalize.")
        return 0
    try:
        m = json.loads(MARKER_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[recover] marker unreadable ({e}); clearing it.", file=sys.stderr)
        _clear_marker()
        return 0

    stamp = m.get("stamp", "")
    out_dir = Path(m.get("out_dir", str(
        Path(__file__).parent.parent / "data" / "teams" / "calls")))
    spk_path = Path(m["spk_path"]) if m.get("spk_path") else out_dir / f"{stamp}_speaker.wav"
    mic_path = Path(m["mic_path"]) if m.get("mic_path") else out_dir / f"{stamp}_mic.wav"

    try:
        started_dt = datetime.datetime.fromisoformat(m["started_at"])
    except Exception:
        started_dt = datetime.datetime.now()

    print(f"[recover] finalizing orphaned recording {stamp} "
          f"(crash mid-call) — repairing WAV headers...")

    any_audio = False
    for p in (spk_path, mic_path):
        if p.exists() and _repair_wav_header(p):
            any_audio = True
            print(f"  [recover] repaired {p.name} "
                  f"({p.stat().st_size/1024/1024:.1f} MB)")

    if not any_audio:
        print("[recover] no recoverable audio on disk; clearing marker.")
        _clear_marker()
        return 0

    # ended_dt = latest WAV mtime (best estimate of when capture stopped).
    try:
        mtimes = [p.stat().st_mtime for p in (spk_path, mic_path) if p.exists()]
        ended_dt = datetime.datetime.fromtimestamp(max(mtimes)) if mtimes \
            else datetime.datetime.now()
    except Exception:
        ended_dt = datetime.datetime.now()

    _postprocess_and_upload(
        out_dir=out_dir, stamp=stamp,
        started_dt=started_dt, ended_dt=ended_dt,
        spk_path=spk_path, mic_path=mic_path,
    )
    _clear_marker()
    print(f"[recover] orphaned recording {stamp} finalized.")
    return 0


def main() -> int:
    if "--finalize-orphan" in sys.argv[1:]:
        return finalize_orphan()
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

    # Clear exclusive mode for the headset up front. Each track now owns
    # its own PyAudio instance and re-resolves its device on reconnect, so
    # a mid-call USB port change is recovered inside record() itself.
    _disable_exclusive_mode_for_mic()

    # Drop the in-progress marker BEFORE the first sample is written so a
    # crash at any point after this is recoverable on the next daemon boot.
    _write_marker(stamp, out_dir, started_dt, spk_path, mic_path)

    stop = threading.Event()
    threads = [
        threading.Thread(target=record, args=(spk_path, stop, "speaker"), daemon=True),
        threading.Thread(target=record, args=(mic_path, stop, "mic"), daemon=True),
    ]

    print(f"Recording -> {out_dir.resolve()}")
    print(f"Stop with Ctrl+C, or `touch {STOP_FILE}`\n")
    for t in threads:
        t.start()

    try:
        # Keep recording as long as AT LEAST ONE track is still alive.
        # Previously this was `all(...)` which meant a single failed
        # stream killed the whole session (see record() OSError guard
        # for the failure mode this protects against).
        while any(t.is_alive() for t in threads):
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

    print()
    for path in (spk_path, mic_path):
        size = path.stat().st_size / 1024 / 1024 if path.exists() else 0
        print(f"  {path}  ({size:.1f} MB)")

    ended_dt = datetime.datetime.now()

    # Post-process + discard-if-too-short + metadata + central upload.
    # Shared with the crash-recovery finalize path so both behave the same.
    try:
        _postprocess_and_upload(
            out_dir=out_dir, stamp=stamp,
            started_dt=started_dt, ended_dt=ended_dt,
            spk_path=spk_path, mic_path=mic_path,
        )
    finally:
        # Clean exit — drop the in-progress marker so the next daemon boot
        # doesn't treat this finished call as an orphan to recover.
        _clear_marker()
    return 0


if __name__ == "__main__":
    sys.exit(main())
