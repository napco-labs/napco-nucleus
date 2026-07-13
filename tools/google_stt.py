"""Google Cloud Speech-to-Text backend for call transcription.

The SOLE call-transcription engine. Bangla->English is done downstream by
Claude, not by the STT. HARD RULE: this must run on Chirp (chirp_2, v2) —
never silently downgrade to a non-Chirp model.

Uses the v1 *synchronous* REST endpoint authenticated with a plain API
key, so NO service account and NO GCS bucket are required (the
long-running recognizer would need both). Because sync `recognize` caps
at ~60 s / 10 MB per request, each track is converted to 16 kHz mono
LINEAR16 and segmented into <=55 s chunks via ffmpeg, recognized
chunk-by-chunk, and stitched back onto a continuous timeline.

Returns the SAME segment shape as the other backends:

    [{"start": float, "end": float, "text": str, "speaker": label}, ...]

so collect_central._segs_to_body_lines renders it identically. Output is
Bangla (bn-BD) verbatim — Claude translates downstream where context
recovers meaning, matching the repo's transcribe-not-translate rule
(Whisper's translate head and Groq's English output are both weaker on
Bangla than transcribe-then-Claude).

Auth: prefers a service-account JSON (GOOGLE_STT_CREDENTIALS) and mints a
short-lived OAuth bearer token via google-auth; falls back to a plain
API key (GOOGLE_STT_API_KEY) passed as a ?key= query param.

Env knobs:
    GOOGLE_STT_CREDENTIALS  path to a service-account JSON (preferred)
    GOOGLE_STT_API_KEY      API key, used only if no SA creds are set
    GOOGLE_STT_LANGUAGE     default "bn-BD"
    GOOGLE_STT_MODEL        default "chirp_2" (Chirp 2 on the v2 API — best
                            for Bangla; needs a project_id via
                            GOOGLE_STT_CREDENTIALS/GOOGLE_STT_PROJECT. Set
                            "latest_long" or "default" to use the v1 models.)
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

GOOGLE_STT_URL = "https://speech.googleapis.com/v1/speech:recognize"
CHUNK_SECONDS = 55       # strictly < the 60 s sync-recognize cap
TARGET_RATE = 16000      # Google recommends 16 kHz mono
DEFAULT_LANGUAGE = "bn-BD"
DEFAULT_MODEL = "chirp_2"   # Chirp 2 (v2) — ~2x better Bangla coverage than latest_long
_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def _resolve_auth() -> tuple[dict, dict]:
    """Return (query_params, headers) for authenticating STT requests.

    Service-account JSON (GOOGLE_STT_CREDENTIALS) is preferred — it mints
    a bearer token via google-auth. Otherwise an API key is used.
    """
    creds_path = os.getenv("GOOGLE_STT_CREDENTIALS")
    if creds_path and Path(creds_path).exists():
        from google.oauth2 import service_account  # lazy
        from google.auth.transport.requests import Request  # lazy
        creds = service_account.Credentials.from_service_account_file(
            creds_path, scopes=[_SCOPE])
        creds.refresh(Request())
        return {}, {"Authorization": f"Bearer {creds.token}"}
    api_key = os.getenv("GOOGLE_STT_API_KEY")
    if api_key:
        return {"key": api_key}, {}
    raise RuntimeError("Set GOOGLE_STT_CREDENTIALS (service-account JSON) "
                       "or GOOGLE_STT_API_KEY")


def _segment_to_16k_mono(wav_path: Path,
                         out_dir: Path) -> list[tuple[Path, float]]:
    """ffmpeg: downmix->mono, resample->16 kHz, split into CHUNK_SECONDS
    LINEAR16 WAVs. Returns [(chunk_path, start_offset_seconds), ...].

    PCM WAV has no keyframes, so the segmenter cuts exactly on
    segment_time — chunk i therefore starts at i * CHUNK_SECONDS.
    """
    pattern = str(out_dir / f"{wav_path.stem}_g%05d.wav")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(wav_path),
        "-ac", "1", "-ar", str(TARGET_RATE), "-c:a", "pcm_s16le",
        "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
        pattern,
    ]
    subprocess.run(cmd, check=True, timeout=1800)
    chunks = sorted(out_dir.glob(f"{wav_path.stem}_g*.wav"))
    return [(c, float(i * CHUNK_SECONDS)) for i, c in enumerate(chunks)]


def _chunk_duration_s(chunk_path: Path) -> float:
    with wave.open(str(chunk_path), "rb") as w:
        fr = w.getframerate() or TARGET_RATE
        return w.getnframes() / float(fr)


def _recognize_chunk(chunk_path: Path, params: dict, headers: dict,
                     language: str, model: str) -> str:
    """POST one <=55 s chunk to the sync recognizer, return its text."""
    import requests  # lazy
    with open(chunk_path, "rb") as f:
        content = base64.b64encode(f.read()).decode("ascii")
    config = {
        "encoding": "LINEAR16",
        "sampleRateHertz": TARGET_RATE,
        "audioChannelCount": 1,
        "languageCode": language,
        "enableAutomaticPunctuation": True,
    }
    # Mixed Bangla/English calls: NAPCO Security clients speak English while
    # the dev side speaks Bangla. alternativeLanguageCodes lets Google
    # auto-detect per utterance instead of mangling English as Bangla.
    alts = [a.strip() for a in
            os.getenv("GOOGLE_STT_ALT_LANGUAGES", "en-US,en-IN").split(",")
            if a.strip() and a.strip() != language]
    if alts:
        config["alternativeLanguageCodes"] = alts[:3]  # API caps at 3
    if model:
        config["model"] = model
    body = {"config": config, "audio": {"content": content}}
    import time as _time
    for _attempt in range(3):
        r = requests.post(GOOGLE_STT_URL, params=params, headers=headers,
                          json=body, timeout=300)
        if r.status_code == 200:
            break
        if r.status_code in (429, 500, 502, 503) and _attempt < 2:
            wait = (5, 15)[_attempt]
            print(f"  [google-stt] {r.status_code} on attempt {_attempt+1}; "
                  f"retrying in {wait}s...")
            _time.sleep(wait)
            continue
        raise RuntimeError(f"Google STT {r.status_code}: {r.text[:300]}")
    payload = r.json()
    parts: list[str] = []
    for res in payload.get("results", []):
        alts = res.get("alternatives") or []
        if alts and (alts[0].get("transcript") or "").strip():
            parts.append(alts[0]["transcript"].strip())
    return " ".join(parts).strip()


def _project_id() -> str:
    """Project for the v2 recognizer path — from the SA JSON or env."""
    creds = os.getenv("GOOGLE_STT_CREDENTIALS")
    if creds and Path(creds).exists():
        import json
        pid = json.load(open(creds)).get("project_id")
        if pid:
            return pid
    return os.getenv("GOOGLE_STT_PROJECT", "")


def _recognize_chunk_v2(chunk_path: Path, params: dict, headers: dict,
                        language: str, model: str, region: str,
                        project: str) -> str:
    """POST one <=55 s chunk to the Speech-to-Text v2 recognizer (Chirp 2
    et al). Uses the `_` inline recognizer + autoDecodingConfig."""
    import requests  # lazy
    with open(chunk_path, "rb") as f:
        content = base64.b64encode(f.read()).decode("ascii")
    # Chirp 2 requires a SINGLE language code — multiple codes return a
    # 400 on language_codes. bn-BD handles the mixed Bangla/English calls
    # well on its own (it keeps English terms verbatim). Use "auto" via
    # GOOGLE_STT_LANGUAGE if you want automatic language detection instead.
    body = {
        "config": {
            "model": model,
            "languageCodes": [language],
            "features": {"enableAutomaticPunctuation": True},
            "autoDecodingConfig": {},
        },
        "content": content,
    }
    url = (f"https://{region}-speech.googleapis.com/v2/projects/{project}"
           f"/locations/{region}/recognizers/_:recognize")
    # Retry transient errors just like the v1 path — without this a single
    # 429/5xx on any chunk of a long call propagated out and discarded the
    # ENTIRE call transcript.
    import time as _time
    for _attempt in range(3):
        r = requests.post(url, params=params, headers=headers, json=body,
                          timeout=300)
        if r.status_code == 200:
            break
        if r.status_code in (429, 500, 502, 503) and _attempt < 2:
            wait = (5, 15)[_attempt]
            print(f"  [google-stt v2] {r.status_code} on attempt "
                  f"{_attempt+1}; retrying in {wait}s...")
            _time.sleep(wait)
            continue
        raise RuntimeError(f"Google STT v2 {r.status_code}: {r.text[:300]}")
    parts: list[str] = []
    for res in r.json().get("results", []):
        alts = res.get("alternatives") or []
        if alts and (alts[0].get("transcript") or "").strip():
            parts.append(alts[0]["transcript"].strip())
    return " ".join(parts).strip()


def google_transcribe(wav_path: Path | None, label: str,
                      language: str | None = None) -> list[dict]:
    """Transcribe one WAV track via Google STT. Returns segments
    [{start,end,text,speaker}] on a continuous timeline. Raises on a
    hard failure (missing creds, ffmpeg error, API error) — Google STT is
    the only engine, so the caller surfaces the error rather than falling back.
    """
    if wav_path is None:
        return []
    params, headers = _resolve_auth()
    language = language or os.getenv("GOOGLE_STT_LANGUAGE", DEFAULT_LANGUAGE)
    model = os.getenv("GOOGLE_STT_MODEL", DEFAULT_MODEL)
    # Chirp / Chirp 2 live on the v2 API (best for Bangla); classic models
    # (default, latest_long) stay on v1.
    use_v2 = model.startswith("chirp")
    region = os.getenv("GOOGLE_STT_REGION", "us-central1")
    project = _project_id() if use_v2 else ""
    # HARD RULE: Chirp (chirp_2, v2) is the only acceptable model. Chirp needs
    # a project_id (from the SA JSON or GOOGLE_STT_PROJECT). We must NOT
    # silently downgrade to a non-Chirp v1 model when it can't be resolved —
    # that would produce forbidden output. Fail loudly so the misconfig gets
    # fixed instead.
    if use_v2 and not project:
        raise RuntimeError(
            "Chirp STT requires a project_id but none could be resolved. "
            "Set GOOGLE_STT_PROJECT (or provide GOOGLE_STT_CREDENTIALS, a "
            "service-account JSON whose project_id is used). Refusing to "
            "fall back to a non-Chirp model (hard rule).")

    try:
        concurrency = max(1, int(os.getenv("GOOGLE_STT_CONCURRENCY", "8")))
    except ValueError:
        concurrency = 8

    def _do(item: tuple[Path, float]) -> dict | None:
        chunk_path, offset = item
        dur = _chunk_duration_s(chunk_path)
        try:
            if use_v2:
                text = _recognize_chunk_v2(chunk_path, params, headers,
                                           language, model, region, project)
            else:
                text = _recognize_chunk(chunk_path, params, headers,
                                        language, model)
        except Exception as e:
            # One chunk failing (after its own retries) must NOT discard the
            # whole call — return a gap marker so the good chunks survive and
            # the caller can tell partial loss from total failure.
            print(f"  [google-stt] chunk @ {int(offset)}s failed: "
                  f"{str(e)[:200]}", file=sys.stderr)
            return {"__error__": True, "start": offset,
                    "end": offset + dur, "speaker": label, "err": str(e)[:200]}
        if not text:
            return None
        return {
            "start": offset,
            "end": offset + dur,
            "text": text,
            "speaker": label,
        }

    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="gstt_") as td:
        chunks = _segment_to_16k_mono(wav_path, Path(td))
        # Recognize chunks concurrently — the bearer token is shared and the
        # sync endpoint handles parallel requests. Per-chunk failures are
        # captured (not raised) so a single bad chunk can't lose the call.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            for seg in ex.map(_do, chunks):
                if seg is not None:
                    results.append(seg)

    good = [s for s in results if not s.get("__error__")]
    failed = [s for s in results if s.get("__error__")]
    # Every recognized chunk errored (and it wasn't just silence) — a genuine
    # transcription failure, not a quiet call. Raise so the caller counts it
    # (collect_central stt_failures) instead of reading it as "no speech".
    if failed and not good:
        raise RuntimeError(
            f"Google STT: all {len(failed)} chunk(s) failed to transcribe; "
            f"last error: {failed[0].get('err')}")
    # Partial success: keep the good segments and turn each failed chunk into a
    # visible, flagged gap marker so a reviewer/LLM sees a requirement may live
    # in the lost span rather than silently missing it.
    segments: list[dict] = list(good)
    for s in failed:
        segments.append({
            "start": s["start"],
            "end": s["end"],
            "speaker": s["speaker"],
            "text": (f"(~{int(s['end'] - s['start'])}s of audio could not be "
                     f"transcribed here — requirements in this span may be "
                     f"missing)"),
            "uncertain": True,
        })
    segments.sort(key=lambda s: s["start"])
    return segments
