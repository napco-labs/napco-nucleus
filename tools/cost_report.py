"""Cost report — aggregate per-Claude-call telemetry from activity_logs.

Reads rows where task_name starts with 'claude_call:' (written by
tools/_cost.py during pipeline.py / agent.py runs) and rolls up
spend by stage, model, and day.

Usage:
    py -3 -m tools.cost_report                   # last 7 days
    py -3 -m tools.cost_report --since 30d
    py -3 -m tools.cost_report --json
    py -3 -m tools.cost_report --by stage,model  # group by (default: stage)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

import memory  # noqa: E402


def _parse_since(s: str) -> dt.timedelta:
    s = (s or "7d").strip().lower()
    m = re.fullmatch(r"(\d+)\s*([smhd])?", s)
    if not m:
        raise ValueError(f"bad --since {s!r}; try '7d' or '24h'")
    n, unit = int(m.group(1)), (m.group(2) or "d")
    return dt.timedelta(seconds={"s": 1, "m": 60,
                                  "h": 3600, "d": 86400}[unit] * n)


def _fetch_calls(since: dt.timedelta) -> list[dict]:
    cutoff = dt.datetime.now() - since
    cutoff_sql = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    rows: list[dict] = []
    try:
        with sqlite3.connect(memory.db_path()) as c:
            c.row_factory = sqlite3.Row
            res = c.execute(
                "SELECT id, task_name, result, technical_details, timestamp "
                "FROM activity_logs "
                "WHERE task_name LIKE 'claude_call:%' "
                "AND timestamp >= ? "
                "ORDER BY timestamp",
                (cutoff_sql,),
            ).fetchall()
            for r in res:
                d = dict(r)
                try:
                    d["details"] = json.loads(d.get("technical_details") or "{}")
                except Exception:
                    d["details"] = {}
                d["stage"] = d["task_name"].split(":", 1)[1] \
                    if ":" in d["task_name"] else d["task_name"]
                rows.append(d)
    except Exception as e:
        print(f"DB error: {e}", file=sys.stderr)
    return rows


def _group_by(rows: list[dict], keys: list[str]) -> dict[tuple, dict]:
    """Aggregate calls by the given key list."""
    agg: dict[tuple, dict] = {}
    for r in rows:
        d = r["details"]
        key_vals = tuple(
            r.get(k) or d.get(k) or ""
            for k in keys
        )
        slot = agg.setdefault(key_vals, {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cost_usd": 0.0,
        })
        slot["calls"] += 1
        for f in ("input_tokens", "output_tokens",
                  "cache_read_input_tokens",
                  "cache_creation_input_tokens"):
            v = d.get(f, 0)
            if isinstance(v, (int, float)):
                slot[f] += int(v)
        c = d.get("cost_usd", 0)
        if isinstance(c, (int, float)):
            slot["cost_usd"] += float(c)
    return agg


def _color(s, c): return f"\033[{c}m{s}\033[0m"
def _b(s): return _color(s, "1")
def _d(s): return _color(s, "2")
def _g(s): return _color(s, "32")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="7d",
                    help="Window. Try '7d', '30d', '24h'. Default 7d.")
    ap.add_argument("--by", default="stage",
                    help="Group by comma-separated keys: stage, model, "
                         "day. Default 'stage'.")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="Machine-readable output.")
    args = ap.parse_args()

    try:
        since = _parse_since(args.since)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    rows = _fetch_calls(since)
    if args.as_json:
        # Add a synthetic 'day' field for grouping
        for r in rows:
            r["day"] = r["timestamp"][:10] if r["timestamp"] else ""
        keys = [k.strip() for k in args.by.split(",") if k.strip()]
        agg = _group_by(rows, keys)
        out = {
            "since": args.since,
            "row_count": len(rows),
            "groups": [
                {"key": dict(zip(keys, k)), **v}
                for k, v in sorted(agg.items())
            ],
            "totals": {
                "calls": sum(g["calls"] for g in agg.values()),
                "input_tokens": sum(g["input_tokens"] for g in agg.values()),
                "output_tokens": sum(g["output_tokens"] for g in agg.values()),
                "cost_usd": round(sum(g["cost_usd"] for g in agg.values()), 4),
            },
        }
        print(json.dumps(out, indent=2, default=str))
        return 0

    print(_b(f"\nClaude API cost report — since {args.since}"))
    print(_d(f"Window starts: {(dt.datetime.now() - since).isoformat(timespec='seconds')}"))
    print()
    if not rows:
        print(_d("No claude_call:* entries in activity_logs for this window."))
        print(_d("Run pipeline.py to populate."))
        return 0

    for r in rows:
        r["day"] = r["timestamp"][:10] if r["timestamp"] else ""

    keys = [k.strip() for k in args.by.split(",") if k.strip()]
    agg = _group_by(rows, keys)

    header = "  " + "  ".join(f"{k:14s}" for k in keys) + \
             "  calls   in_tok    out_tok    cost"
    print(_d(header))
    print(_d("  " + "─" * (len(header) + 4)))

    total_calls = 0
    total_in = 0
    total_out = 0
    total_cost = 0.0
    for k, v in sorted(agg.items()):
        key_str = "  ".join(f"{(kk or '?'):14s}" for kk in k)
        cost = v["cost_usd"]
        line = (f"  {key_str}  {v['calls']:5d}  "
                f"{v['input_tokens']:8d}  {v['output_tokens']:8d}  "
                f"${cost:7.4f}")
        if cost > 0.10:
            line = _color(line, "33")  # amber on the bigger items
        print(line)
        total_calls += v["calls"]
        total_in += v["input_tokens"]
        total_out += v["output_tokens"]
        total_cost += cost

    print()
    print(_b(
        f"Total calls: {total_calls}   "
        f"in: {total_in:,} tok   out: {total_out:,} tok   "
        f"cost: ${total_cost:.4f}"
    ))
    if since.total_seconds() >= 7 * 86400:
        per_day = total_cost / (since.total_seconds() / 86400)
        print(_d(f"  ~${per_day:.4f}/day projected at current rate"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
