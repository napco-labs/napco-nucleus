"""Cost telemetry for claude_agent_sdk calls.

Captures `usage` (input + output tokens) off response messages,
estimates dollar cost from a model-tier price table, and logs each
call to activity_logs with structured details. A separate reporter
(`tools/cost_report.py`) aggregates over a time window.

Defensive: token counts may be `None` if a particular SDK version
or response message doesn't expose them — we still log a zero entry
so the call-count signal is preserved.

Pricing (USD per 1M tokens) is configurable via env vars; defaults
reflect Anthropic's published rates as of early 2026. Update the
defaults when Anthropic changes pricing.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ── Pricing table (USD per million tokens) ────────────────────────

_DEFAULT_PRICES = {
    # Per Anthropic published rates (1M tokens basis).
    # Override any of these via env: NUCLEUS_PRICE_<MODELKEY>_IN / _OUT.
    "claude-haiku-4-5-20251001":  {"in": 0.80, "out":  4.00},
    "claude-haiku-4-5":           {"in": 0.80, "out":  4.00},
    "claude-sonnet-4-6":          {"in": 3.00, "out": 15.00},
    "claude-opus-4-7":            {"in": 15.00, "out": 75.00},
    "claude-opus-4-7[1m]":        {"in": 15.00, "out": 75.00},
}

_UNKNOWN_MODEL_FALLBACK = {"in": 3.00, "out": 15.00}  # Sonnet-tier


def _model_key(name: str) -> str:
    """Normalise model name for the price lookup."""
    return (name or "unknown").strip()


def _price(model: str, direction: str) -> float:
    """Get per-1M-token price for a model + direction (in|out).
    Env override: NUCLEUS_PRICE_<safe-model>_<IN|OUT>."""
    key = _model_key(model)
    safe = "".join(c if c.isalnum() else "_" for c in key).upper()
    env_var = f"NUCLEUS_PRICE_{safe}_{direction.upper()}"
    if env_var in os.environ:
        try:
            return float(os.environ[env_var])
        except ValueError:
            pass
    if key in _DEFAULT_PRICES:
        return _DEFAULT_PRICES[key][direction]
    # Fuzzy: strip a trailing date or [1m] suffix and try again
    base = key.split("[", 1)[0]
    base = "-".join(base.split("-")[:4])  # claude-haiku-4-5
    if base in _DEFAULT_PRICES:
        return _DEFAULT_PRICES[base][direction]
    return _UNKNOWN_MODEL_FALLBACK[direction]


# ── Usage extraction from SDK messages ────────────────────────────

def extract_usage(msg: Any) -> dict | None:
    """Pull {input_tokens, output_tokens, ...} from an SDK response
    message. SDK versions vary; we try several shapes defensively."""
    # Direct attribute (most current SDKs)
    usage = getattr(msg, "usage", None)
    if usage is not None:
        return _normalise(usage)
    # Some SDKs nest under .message.usage
    inner = getattr(msg, "message", None)
    if inner is not None:
        usage = getattr(inner, "usage", None)
        if usage is not None:
            return _normalise(usage)
    # Dict-like
    if isinstance(msg, dict):
        if "usage" in msg:
            return _normalise(msg["usage"])
    return None


def _normalise(usage: Any) -> dict | None:
    """Convert various usage shapes into a stable dict with the keys
    input_tokens / output_tokens / cache_read_input_tokens /
    cache_creation_input_tokens. Missing fields → None."""
    if usage is None:
        return None
    def _get(k: str):
        v = (getattr(usage, k, None) if not isinstance(usage, dict)
             else usage.get(k))
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    return {
        "input_tokens": _get("input_tokens"),
        "output_tokens": _get("output_tokens"),
        "cache_read_input_tokens": _get("cache_read_input_tokens"),
        "cache_creation_input_tokens": _get("cache_creation_input_tokens"),
    }


# ── Cost computation ──────────────────────────────────────────────

def estimate_cost(model: str, input_tokens: int | None,
                  output_tokens: int | None,
                  cache_read_input_tokens: int | None = None,
                  cache_creation_input_tokens: int | None = None) -> float:
    """Estimated USD cost for one call. Returns 0.0 if both token
    counts are None (the SDK didn't report usage). Cache-read tokens
    are billed at 10% of the regular input rate (Anthropic pricing);
    cache-creation at 125% (25% surcharge). Missing fields treated
    as 0."""
    p_in = _price(model, "in") / 1_000_000
    p_out = _price(model, "out") / 1_000_000
    cost = 0.0
    if input_tokens:
        cost += input_tokens * p_in
    if output_tokens:
        cost += output_tokens * p_out
    if cache_read_input_tokens:
        cost += cache_read_input_tokens * p_in * 0.10
    if cache_creation_input_tokens:
        cost += cache_creation_input_tokens * p_in * 1.25
    return round(cost, 6)


# ── Per-call accumulator ──────────────────────────────────────────

class CallTelemetry:
    """Accumulates usage across the messages of one SDK call.
    Use as a single-call buffer; call .log(stage, model) when done."""
    __slots__ = ("_totals",)

    def __init__(self):
        self._totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "messages_with_usage": 0,
            "messages_total": 0,
        }

    def observe(self, msg: Any) -> None:
        self._totals["messages_total"] += 1
        u = extract_usage(msg)
        if not u:
            return
        for k in ("input_tokens", "output_tokens",
                  "cache_read_input_tokens",
                  "cache_creation_input_tokens"):
            v = u.get(k)
            if isinstance(v, int):
                self._totals[k] += v
        self._totals["messages_with_usage"] += 1

    def totals(self) -> dict:
        return dict(self._totals)

    def cost(self, model: str) -> float:
        return estimate_cost(
            model,
            input_tokens=self._totals["input_tokens"] or None,
            output_tokens=self._totals["output_tokens"] or None,
            cache_read_input_tokens=
                self._totals["cache_read_input_tokens"] or None,
            cache_creation_input_tokens=
                self._totals["cache_creation_input_tokens"] or None,
        )

    def log(self, *, stage: str, model: str,
            extra: dict | None = None) -> None:
        """Persist to memory.activity_logs as task_name='claude_call:<stage>'."""
        try:
            import memory  # lazy
        except Exception:
            return
        cost_usd = self.cost(model)
        details = {**self._totals, "model": model,
                   "cost_usd": cost_usd, "stage": stage}
        if extra:
            details.update(extra)
        result = (f"in={self._totals['input_tokens']} "
                  f"out={self._totals['output_tokens']} "
                  f"cost=${cost_usd:.4f}")
        try:
            memory.log_activity(
                task_name=f"claude_call:{stage}",
                result=result,
                technical_details=details,
            )
        except Exception as e:
            logger.warning("cost log failed: %s", e)
