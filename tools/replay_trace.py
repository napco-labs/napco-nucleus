"""Inspect a structured trace from a pipeline / verify_session run.

Usage:
    py -3 -m tools.replay_trace --latest        # most recent run
    py -3 -m tools.replay_trace --run <run_id>
    py -3 -m tools.replay_trace --grep "audit"  # search response text
    py -3 -m tools.replay_trace --list          # list today's runs
    py -3 -m tools.replay_trace --json --run <id>  # raw dump

Each trace is a JSONL file at data/traces/<date>/<run_id>.jsonl with
one record per Claude SDK call plus run_meta / run_finish bookends.
The replay command pretty-prints the chain so you can debug "why did
the LLM say X?" by seeing exactly what it received and produced at
each stage.

This is the foundation for every quality improvement from here on:
when a run produces a bad output, replay shows you which stage drifted
and what prompt context could be tightened.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

from tools._trace import list_traces, find_trace, latest_trace  # noqa: E402


def _color(s, c): return f"\033[{c}m{s}\033[0m"
def _b(s): return _color(s, "1")
def _d(s): return _color(s, "2")
def _g(s): return _color(s, "32")
def _y(s): return _color(s, "33")
def _r(s): return _color(s, "31")
def _c(s): return _color(s, "36")


def _load_records(path: Path) -> list[dict]:
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _shorten(text: str, max_chars: int = 600) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 60]
    return cut + f"\n…[truncated, {len(text) - len(cut)} more chars]"


def _render_call(rec: dict, full: bool) -> None:
    stage = rec.get("stage") or "?"
    model = rec.get("model") or "?"
    elapsed = rec.get("elapsed_s")
    cost = rec.get("cost_usd")
    err = rec.get("error")
    usage = rec.get("usage") or {}
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    n_tools = len(rec.get("tool_calls") or [])

    header = (f"  STAGE: {_b(stage):20s}  model={model}  "
              f"elapsed={elapsed}s  in_tok={in_tok}  out_tok={out_tok}  "
              f"cost=${cost:.4f}  tools={n_tools}"
              if isinstance(cost, (int, float)) else
              f"  STAGE: {_b(stage):20s}  model={model}  "
              f"elapsed={elapsed}s  tools={n_tools}")
    if err:
        header += _r("  ERROR")
    print()
    print(header)
    if err:
        print(_r(f"    error: {err}"))

    # System prompt (truncated unless full)
    sys_p = rec.get("system_prompt") or ""
    if sys_p:
        print(_d("    --- system_prompt ---"))
        print(_d(_shorten(sys_p, 99999 if full else 400)))

    # User prompt
    user_p = rec.get("user_prompt") or ""
    if user_p:
        print(_d("    --- user_prompt ---"))
        print(_d(_shorten(user_p, 99999 if full else 800)))

    # Tool calls
    tool_calls = rec.get("tool_calls") or []
    if tool_calls:
        print(_y(f"    --- tool_calls ({len(tool_calls)}) ---"))
        for tc in tool_calls:
            kind = tc.get("kind") or "?"
            name = tc.get("name") or ""
            inp = tc.get("input") or tc.get("data") or ""
            inp_short = (json.dumps(inp, default=str, ensure_ascii=False)
                         if not isinstance(inp, str) else inp)
            inp_short = _shorten(inp_short, 99999 if full else 240)
            label = f"{kind}/{name}" if name else kind
            print(_y(f"      • {label}: {inp_short}"))

    # Response
    resp = rec.get("response_text") or ""
    if resp:
        print(_g("    --- response ---"))
        print(_g(_shorten(resp, 99999 if full else 1200)))


def _summary(records: list[dict]) -> None:
    meta = next((r for r in records if r.get("kind") == "run_meta"), {})
    finish = next((r for r in records if r.get("kind") == "run_finish"), {})
    calls = [r for r in records if r.get("stage")]

    total_in = sum((r.get("usage") or {}).get("input_tokens", 0)
                   for r in calls)
    total_out = sum((r.get("usage") or {}).get("output_tokens", 0)
                    for r in calls)
    total_cost = sum(r.get("cost_usd") or 0 for r in calls)
    elapsed = sum(r.get("elapsed_s") or 0 for r in calls)

    print(_b(f"\nRun: {meta.get('run_id', '?')}"))
    print(f"  label:       {meta.get('label', '?')}")
    print(f"  host:        {meta.get('host', '?')}")
    print(f"  started:     {meta.get('started_at', '?')}")
    if finish:
        print(f"  finished:    {finish.get('finished_at', '?')}")
    print(f"  calls:       {len(calls)}")
    print(f"  total time:  {elapsed:.2f}s")
    print(f"  total tok:   in={total_in:,}  out={total_out:,}")
    print(f"  total cost:  ${total_cost:.4f}")
    errors = [r for r in calls if r.get("error")]
    if errors:
        print(_r(f"  errors:      {len(errors)}"))


def _grep(records: list[dict], needle: str) -> None:
    needle_l = needle.lower()
    hits = 0
    for rec in records:
        if rec.get("kind") in ("run_meta", "run_finish"):
            continue
        resp = (rec.get("response_text") or "").lower()
        if needle_l in resp:
            hits += 1
            print()
            print(_b(f"  HIT in stage={rec.get('stage')}"))
            # Print the line containing the match
            for line in (rec.get("response_text") or "").split("\n"):
                if needle_l in line.lower():
                    print(_g(f"    {line.strip()}"))
                    break
    print()
    print(_b(f"  {hits} hit(s) for {needle!r}"))


def _list_today() -> None:
    today = dt.date.today()
    files = list_traces(today)
    if not files:
        print(_d(f"No traces on {today}."))
        return
    print(_b(f"\nTraces from {today}:"))
    for f in files:
        try:
            with f.open("r", encoding="utf-8") as fp:
                first = fp.readline()
                meta = json.loads(first)
                label = meta.get("label", "?")
        except Exception:
            label = "?"
        size_kb = f.stat().st_size / 1024
        print(f"  {f.stem:30s}  {label:30s}  {size_kb:6.1f} KB")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--run", help="run_id to load (try --list for options)")
    g.add_argument("--latest", action="store_true",
                   help="Load the most recent trace.")
    g.add_argument("--list", dest="list_only", action="store_true",
                   help="List today's traces and exit.")
    ap.add_argument("--grep", help="Search for a substring in response text.")
    ap.add_argument("--full", action="store_true",
                    help="Don't truncate prompt / response text.")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="Dump raw JSONL records.")
    args = ap.parse_args()

    if args.list_only:
        _list_today()
        return 0

    if args.run:
        path = find_trace(args.run)
        if not path:
            print(_r(f"No trace with run_id {args.run!r} in the last 30 days."),
                  file=sys.stderr)
            return 2
    elif args.latest:
        path = latest_trace()
        if not path:
            print(_r("No traces found in the last 30 days."), file=sys.stderr)
            return 2
    else:
        path = latest_trace()
        if not path:
            print(_r("No traces found. Run pipeline.py to populate."),
                  file=sys.stderr)
            return 2

    records = _load_records(path)
    if args.as_json:
        for rec in records:
            print(json.dumps(rec, ensure_ascii=False, default=str))
        return 0

    print(_d(f"Trace file: {path}"))
    _summary(records)

    if args.grep:
        _grep(records, args.grep)
        return 0

    for rec in records:
        if rec.get("kind") in ("run_meta", "run_finish"):
            continue
        _render_call(rec, full=args.full)
    return 0


if __name__ == "__main__":
    sys.exit(main())
