"""Structured tracing for Claude calls.

Every pipeline / verify_session run gets a unique `run_id`. Within
a run, each Claude SDK call (extract / critique / draft) gets its
own trace, capturing:

  - run_id, stage, timestamp_start, timestamp_end
  - model used
  - system_prompt + user_prompt (the exact text sent)
  - response: list of text chunks observed
  - tool_calls: each tool invocation + arguments + return value
  - usage: input/output/cache tokens
  - cost_usd (estimate)
  - error (if the call failed)

Output: one JSON record appended per call to
    data/traces/<YYYY-MM-DD>/<run_id>.jsonl

Replayability:
    py -3 -m tools.replay_trace --run <run_id>     # pretty-print
    py -3 -m tools.replay_trace --latest           # latest run
    py -3 -m tools.replay_trace --grep "audit"     # search response text

Tracing is best-effort — failures here never block the run. If the
SDK doesn't surface a particular message shape, the trace just
records less detail.

Use as a context manager around the call site:

    with trace_run("pipeline-extract") as run:
        with run.trace_call(stage="extract", model="haiku-4-5",
                            system_prompt=sys, user_prompt=usr) as t:
            async for msg in client.receive_response():
                t.observe_message(msg)
            t.set_response(response_text)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import socket
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_HERE = Path(__file__).parent.parent
_TRACES_ROOT = _HERE / "data" / "traces"


def _today_dir() -> Path:
    return _TRACES_ROOT / dt.date.today().strftime("%Y-%m-%d")


def _new_run_id() -> str:
    """Time-prefixed for sortability, short hash for uniqueness."""
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    short = uuid.uuid4().hex[:8]
    return f"{stamp}-{short}"


def _trace_enabled() -> bool:
    """Set NAPCO_NUCLEUS_TRACE=0 to disable tracing entirely."""
    v = os.environ.get("NAPCO_NUCLEUS_TRACE", "1").strip().lower()
    return v not in ("0", "false", "no", "off", "")


# ── Per-call trace ────────────────────────────────────────────────

class CallTrace:
    """One Claude SDK call. Lives inside a Run."""
    __slots__ = ("_run", "_record", "_start_ts")

    def __init__(self, run: "Run", stage: str, model: str | None,
                 system_prompt: str, user_prompt: str):
        self._run = run
        self._start_ts = time.perf_counter()
        self._record: dict = {
            "run_id": run.run_id,
            "stage": stage,
            "model": model or "default",
            "timestamp_start": dt.datetime.now().isoformat(timespec="seconds"),
            "timestamp_end": None,
            "elapsed_s": None,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response_chunks": [],
            "tool_calls": [],
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "messages_with_usage": 0,
                "messages_total": 0,
            },
            "cost_usd": 0.0,
            "error": None,
        }

    # ── Observation hooks ────────────────────────────────────────

    def observe_message(self, msg: Any) -> None:
        """Inspect one SDK response message; extract usage, text, and
        any tool-call payload. Defensive about SDK shape."""
        self._record["usage"]["messages_total"] += 1
        # Usage
        try:
            from tools._cost import extract_usage  # lazy
            u = extract_usage(msg)
        except Exception:
            u = None
        if u:
            for k in ("input_tokens", "output_tokens",
                      "cache_read_input_tokens",
                      "cache_creation_input_tokens"):
                v = u.get(k)
                if isinstance(v, int):
                    self._record["usage"][k] += v
            self._record["usage"]["messages_with_usage"] += 1

        # Tool calls (best-effort across SDK shapes)
        for attr in ("tool_use_block", "tool_call", "tool_input"):
            tc = getattr(msg, attr, None)
            if tc:
                self._record["tool_calls"].append({
                    "kind": attr,
                    "data": _safe_serialize(tc),
                })
                break

        # Some SDKs nest tool calls under `content` as ToolUseBlock items
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            for block in content:
                btype = type(block).__name__
                if "Tool" in btype:
                    self._record["tool_calls"].append({
                        "kind": btype,
                        "name": getattr(block, "name", None),
                        "input": _safe_serialize(getattr(block, "input", None)),
                    })

    def add_response_chunk(self, text: str) -> None:
        if isinstance(text, str) and text:
            self._record["response_chunks"].append(text)

    def set_error(self, err: BaseException) -> None:
        self._record["error"] = f"{type(err).__name__}: {err}"

    # ── Finalisation ─────────────────────────────────────────────

    def _finalize(self) -> None:
        self._record["elapsed_s"] = round(
            time.perf_counter() - self._start_ts, 3)
        self._record["timestamp_end"] = dt.datetime.now().isoformat(
            timespec="seconds")
        # Compute cost from usage
        try:
            from tools._cost import estimate_cost  # lazy
            u = self._record["usage"]
            self._record["cost_usd"] = estimate_cost(
                self._record["model"],
                input_tokens=u["input_tokens"] or None,
                output_tokens=u["output_tokens"] or None,
                cache_read_input_tokens=u["cache_read_input_tokens"] or None,
                cache_creation_input_tokens=u["cache_creation_input_tokens"] or None,
            )
        except Exception as e:
            logger.warning("cost estimation in trace failed: %s", e)
        # Collapse chunks for compactness — full text is the join
        chunks = self._record["response_chunks"]
        self._record["response_text"] = "".join(chunks)
        # Keep chunks separately in case caller wants per-event view
        self._record["response_chunk_count"] = len(chunks)
        del self._record["response_chunks"]
        self._run._write_record(self._record)


def _safe_serialize(v: Any) -> Any:
    """Best-effort JSON-serialisable conversion. Falls back to repr()
    for anything weird."""
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        if isinstance(v, dict):
            return {str(k): _safe_serialize(val) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return [_safe_serialize(x) for x in v]
        return repr(v)


# ── Run-level trace ──────────────────────────────────────────────

class Run:
    """A single pipeline / verify_session run. Owns the trace file."""

    def __init__(self, label: str, run_id: str | None = None,
                 enabled: bool = True):
        self.run_id = run_id or _new_run_id()
        self.label = label
        self.enabled = enabled and _trace_enabled()
        self._trace_path: Path | None = None
        if self.enabled:
            _today_dir().mkdir(parents=True, exist_ok=True)
            self._trace_path = _today_dir() / f"{self.run_id}.jsonl"
            self._write_meta()

    def _write_meta(self) -> None:
        meta = {
            "kind": "run_meta",
            "run_id": self.run_id,
            "label": self.label,
            "host": socket.gethostname(),
            "started_at": dt.datetime.now().isoformat(timespec="seconds"),
            "trace_schema_version": 1,
        }
        self._write_record(meta)

    def _write_record(self, rec: dict) -> None:
        if not self.enabled or not self._trace_path:
            return
        try:
            with self._trace_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str))
                f.write("\n")
        except Exception as e:
            logger.warning("trace write failed: %s", e)

    @contextmanager
    def trace_call(self, *, stage: str, model: str | None,
                   system_prompt: str, user_prompt: str):
        """Context-manage one Claude call. Yields a CallTrace the
        caller observes events on."""
        if not self.enabled:
            yield _NoOpCall()
            return
        t = CallTrace(self, stage, model, system_prompt, user_prompt)
        try:
            yield t
        except BaseException as e:
            t.set_error(e)
            t._finalize()
            raise
        else:
            t._finalize()

    @property
    def trace_path(self) -> Path | None:
        return self._trace_path


class _NoOpCall:
    """Stand-in when tracing is disabled — keeps the call sites uniform."""
    def observe_message(self, *_a, **_k): pass
    def add_response_chunk(self, *_a, **_k): pass
    def set_error(self, *_a, **_k): pass


# ── Convenience entry points ─────────────────────────────────────

@contextmanager
def trace_run(label: str, run_id: str | None = None):
    """Open a Run context. Usage:

        with trace_run("pipeline-multi-agent") as run:
            ...
            with run.trace_call(stage="extract", ...) as t:
                ...
    """
    run = Run(label, run_id=run_id)
    try:
        yield run
    finally:
        # Append a terminal record so readers know when the run ended
        run._write_record({
            "kind": "run_finish",
            "run_id": run.run_id,
            "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
        })


def list_traces(day: dt.date | None = None) -> list[Path]:
    target = (_TRACES_ROOT / (day or dt.date.today()).strftime("%Y-%m-%d"))
    if not target.exists():
        return []
    return sorted(target.glob("*.jsonl"))


def find_trace(run_id: str) -> Path | None:
    """Locate a trace by run_id — looks in today's folder first, then
    walks back up to 30 days."""
    today = dt.date.today()
    for back in range(31):
        d = today - dt.timedelta(days=back)
        candidate = (_TRACES_ROOT / d.strftime("%Y-%m-%d")
                      / f"{run_id}.jsonl")
        if candidate.exists():
            return candidate
    return None


def latest_trace() -> Path | None:
    """Most recent trace file. Walks back up to 30 days."""
    today = dt.date.today()
    for back in range(31):
        d = today - dt.timedelta(days=back)
        dir_ = _TRACES_ROOT / d.strftime("%Y-%m-%d")
        if not dir_.exists():
            continue
        files = sorted(dir_.glob("*.jsonl"))
        if files:
            return files[-1]
    return None
