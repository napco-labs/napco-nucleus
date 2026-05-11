"""Project the dollar cost of a pipeline run BEFORE calling Claude.

Reads the session doc (and the noise-filter output), estimates input
tokens via the standard ~4-chars-per-token approximation, and walks
each pipeline stage with the configured model to produce a per-stage
+ total dollar projection. Lets you trim the session before paying.

Usage:
    py -3 -m tools.cost_estimator                              # uses live session.docx
    py -3 -m tools.cost_estimator --session <path>             # custom path
    py -3 -m tools.cost_estimator --no-filter                  # estimate with all
                                                               # sections (worst case)
    py -3 -m tools.cost_estimator --json

The estimate uses the same per-model price table as tools/_cost.py.
Token counts are character-count divided by 4 — a conservative
estimate that's typically within 20% of true tiktoken counts for
English; Bangla runs slightly higher per char.

NOT a replacement for tools/cost_report.py (which reads actual
post-run telemetry from activity_logs). This is decision-time
projection; that's after-the-fact accounting.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

from tools._cost import estimate_cost  # noqa: E402
from tools._session_filter import filter_doc, parse_session_doc  # noqa: E402


# Roughly: 4 chars per token for English, 3 for Bangla. Use 4 as a
# conservative middle ground; we typically over-estimate cost by
# 10-25% which is the right side to err on.
_CHARS_PER_TOKEN = 4

# Per-stage typical OUTPUT token sizes (calibrated from observed
# runs). Overridable via env if your sessions trend differently.
_TYP_OUTPUT_TOKENS = {
    "extract": int(os.environ.get("NUCLEUS_TYP_OUTPUT_EXTRACT", "1500")),
    "critique": int(os.environ.get("NUCLEUS_TYP_OUTPUT_CRITIQUE", "1500")),
    "draft": int(os.environ.get("NUCLEUS_TYP_OUTPUT_DRAFT", "2000")),
}


def _model_for_stage(stage: str) -> str:
    env_map = {
        "extract": ("NUCLEUS_PIPELINE_EXTRACT_MODEL", "claude-haiku-4-5-20251001"),
        "critique": ("NUCLEUS_PIPELINE_CRITIQUE_MODEL", "claude-sonnet-4-6"),
        "draft": ("NUCLEUS_PIPELINE_DRAFT_MODEL", "claude-opus-4-7"),
    }
    var, default = env_map[stage]
    return (os.environ.get(var) or default).strip() or default


def _prompt_path(stage: str) -> Path:
    return _HERE / "prompts" / f"pipeline_{stage}.md"


def _tokens(s: str) -> int:
    return max(1, len(s) // _CHARS_PER_TOKEN)


def estimate(session_path: Path, *, apply_filter: bool = True) -> dict:
    """Project per-stage cost for one session run."""
    if apply_filter:
        session_text, filter_stats = filter_doc(session_path)
    else:
        # Worst case: include everything
        sections = parse_session_doc(session_path)
        from tools._session_filter import _rebuild_text  # type: ignore
        session_text = _rebuild_text(sections)
        filter_stats = {
            "total_sections": len(sections),
            "kept_sections": len(sections),
            "dropped_sections": 0,
            "kept_chars": len(session_text),
            "drops": [],
        }

    session_tokens = _tokens(session_text)

    stages_out: list[dict] = []
    total_cost = 0.0

    # Stage 1: Extract — sees system prompt + session text
    sys_extract = _prompt_path("extract").read_text(encoding="utf-8")
    in_tokens = _tokens(sys_extract) + session_tokens + 200  # +headers
    out_tokens = _TYP_OUTPUT_TOKENS["extract"]
    model = _model_for_stage("extract")
    cost = estimate_cost(model, in_tokens, out_tokens)
    stages_out.append({"stage": "extract", "model": model,
                        "input_tokens": in_tokens,
                        "output_tokens": out_tokens,
                        "cost_usd": cost})
    total_cost += cost

    # Stage 2: Critique — sees system prompt + candidate JSON + context
    sys_crit = _prompt_path("critique").read_text(encoding="utf-8")
    # Candidates roughly the size of stage-1 output; context (history +
    # open_items + requirements_seen) varies — assume ~500 tokens.
    in_tokens = _tokens(sys_crit) + _TYP_OUTPUT_TOKENS["extract"] + 500
    out_tokens = _TYP_OUTPUT_TOKENS["critique"]
    model = _model_for_stage("critique")
    cost = estimate_cost(model, in_tokens, out_tokens)
    stages_out.append({"stage": "critique", "model": model,
                        "input_tokens": in_tokens,
                        "output_tokens": out_tokens,
                        "cost_usd": cost})
    total_cost += cost

    # Stage 3: Draft — sees system prompt + final list, calls tools.
    # Tool-call rounds add input/output overhead; assume ~3 tool calls.
    sys_draft = _prompt_path("draft").read_text(encoding="utf-8")
    in_tokens = _tokens(sys_draft) + _TYP_OUTPUT_TOKENS["critique"] + 800
    out_tokens = _TYP_OUTPUT_TOKENS["draft"]
    model = _model_for_stage("draft")
    cost = estimate_cost(model, in_tokens, out_tokens)
    stages_out.append({"stage": "draft", "model": model,
                        "input_tokens": in_tokens,
                        "output_tokens": out_tokens,
                        "cost_usd": cost})
    total_cost += cost

    return {
        "session_path": str(session_path),
        "apply_filter": apply_filter,
        "filter_stats": filter_stats,
        "stages": stages_out,
        "total_cost_usd": round(total_cost, 4),
    }


def _color(s, c): return f"\033[{c}m{s}\033[0m"
def _b(s): return _color(s, "1")
def _g(s): return _color(s, "32")
def _y(s): return _color(s, "33")
def _d(s): return _color(s, "2")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--session",
        default=str(_HERE / "data" / "requirements"
                    / "sessions" / "current.docx"),
        help="Path to session.docx. Default: live session doc.")
    ap.add_argument("--no-filter", action="store_true",
                    help="Estimate without the noise filter (shows "
                         "what you'd pay if you sent the raw doc).")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="Machine-readable output.")
    args = ap.parse_args()

    session = Path(args.session)
    if not session.exists():
        print(f"session not found: {session}", file=sys.stderr)
        return 2

    if not args.no_filter:
        # Show both — filtered vs raw — so the saving is visible
        filtered = estimate(session, apply_filter=True)
        raw = estimate(session, apply_filter=False)
        if args.as_json:
            print(json.dumps({"filtered": filtered, "raw": raw},
                             indent=2, default=str))
            return 0
        _render(filtered, "FILTERED (noise dropped)")
        _render(raw, "RAW (worst-case, no filter)")
        saved = raw["total_cost_usd"] - filtered["total_cost_usd"]
        pct = (saved / raw["total_cost_usd"] * 100
               if raw["total_cost_usd"] else 0)
        print()
        print(_b(f"Filter saves ${saved:.4f} per run ({pct:.1f}%)"))
        return 0

    only = estimate(session, apply_filter=False)
    if args.as_json:
        print(json.dumps(only, indent=2, default=str))
        return 0
    _render(only, "RAW (no filter)")
    return 0


def _render(est: dict, label: str) -> None:
    print()
    print(_b(f"=== {label} ==="))
    fs = est["filter_stats"]
    print(_d(f"  sections: kept={fs.get('kept_sections', '?')} / "
             f"dropped={fs.get('dropped_sections', '?')}  "
             f"chars={fs.get('kept_chars', '?'):,}"))
    print()
    print(f"  {'stage':10s} {'model':38s} {'in_tok':>9s} {'out_tok':>9s} {'$':>9s}")
    for s in est["stages"]:
        cost_str = f"${s['cost_usd']:.4f}"
        if s["cost_usd"] > 0.05:
            cost_str = _y(cost_str)
        print(f"  {s['stage']:10s} {s['model']:38s} "
              f"{s['input_tokens']:>9,} {s['output_tokens']:>9,} "
              f"{cost_str:>9s}")
    print()
    print(_g(f"  Total: ${est['total_cost_usd']:.4f}"))


if __name__ == "__main__":
    sys.exit(main())
