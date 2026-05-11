"""Print the confidence-calibration curve from requirement_reviews.

For every confidence bucket, shows how often you actually kept (or
edited) the LLM's predictions vs. rejected them. If the model is
well-calibrated, the accept rate in each bucket should be close to
the bucket's midpoint — predictions at 0.90 should be kept ~90% of
the time.

Usage:
    py -3 -m tools.calibration_report
    py -3 -m tools.calibration_report --recent 20   # show the last
                                                    # 20 review rows
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows cmd.exe defaults to cp1252; the box-drawing chars below need
# UTF-8. Reconfigure stdout/err if available (Python 3.7+).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

import memory  # noqa: E402


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def _bold(s: str) -> str:  return _color(s, "1")
def _dim(s: str) -> str:   return _color(s, "2")
def _green(s: str) -> str: return _color(s, "32")
def _amber(s: str) -> str: return _color(s, "33")
def _red(s: str) -> str:   return _color(s, "31")


def _bar(rate: float | None, width: int = 20) -> str:
    if rate is None:
        return _dim(" " * width)
    filled = int(round(rate * width))
    return "█" * filled + _dim("·" * (width - filled))


def _calibration_quality(bucket_lo: float, bucket_hi: float,
                         accept_rate: float | None,
                         decided: int) -> str:
    """Brief verbal verdict on this bucket."""
    if decided < 3:
        return _dim("(need more data)")
    if accept_rate is None:
        return _dim("—")
    midpoint = (bucket_lo + min(bucket_hi, 1.0)) / 2
    delta = accept_rate - midpoint
    if abs(delta) <= 0.10:
        return _green("calibrated")
    if delta > 0.10:
        return _amber(f"underconfident (+{delta:+.0%})")
    return _red(f"overconfident ({delta:+.0%})")


def print_curve() -> None:
    buckets = memory.calibration_buckets()
    total_decided = sum(b["decided"] for b in buckets)
    total_kept = sum(b["keep"] + b["edit"] for b in buckets)
    overall_accept = (total_kept / total_decided) if total_decided else None

    print(_bold("Calibration curve"))
    print()
    header = (f"  {'Confidence':14s} {'Decisions':10s} "
              f"{'Accept rate':12s}  Distribution           Verdict")
    print(_dim(header))
    print(_dim("  " + "─" * (len(header) + 4)))

    for b in buckets:
        lo, hi = b["lo"], min(b["hi"], 1.0)
        band = f"{lo:.2f}–{hi:.2f}"
        decided = b["decided"]
        if decided == 0:
            print(f"  {band:14s} {_dim('— no data —'):s}")
            continue
        rate = b["accept_rate"]
        rate_str = f"{rate:.0%}" if rate is not None else "—"
        bar = _bar(rate)
        verdict = _calibration_quality(lo, hi, rate, decided)
        print(f"  {band:14s} {decided:<10d} {rate_str:12s} {bar}  {verdict}")
        # Breakdown
        bits = []
        if b["keep"]:
            bits.append(_green(f"keep {b['keep']}"))
        if b["edit"]:
            bits.append(_amber(f"edit {b['edit']}"))
        if b["reject"]:
            bits.append(_red(f"reject {b['reject']}"))
        if b["skip"]:
            bits.append(_dim(f"skip {b['skip']}"))
        if bits:
            print(_dim(f"  {'':14s} ") + " · ".join(bits))

    print()
    if overall_accept is not None:
        print(_bold(
            f"Overall: {total_kept}/{total_decided} kept-or-edited "
            f"({overall_accept:.0%}) across {len(buckets)} bucket(s)."
        ))
    else:
        print(_dim("No decided reviews yet — run "
                   "py -3 -m tools.review_session first."))


def print_recent(n: int) -> None:
    rows = memory.recent_reviews(limit=n)
    if not rows:
        print(_dim("No recent reviews."))
        return
    print(_bold(f"Recent {len(rows)} review(s)"))
    print()
    for r in rows:
        d = r["decision"]
        marker = {"keep": _green("✓"), "edit": _amber("✎"),
                  "reject": _red("✗"), "skip": _dim("—")}.get(d, "?")
        conf = r["predicted_confidence"]
        conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else "—"
        title = (r["requirement_title"] or "(no title)")[:70]
        print(f"  {marker} {conf_s}  {r['reviewed_at'][:19]}  {title}")
        notes = (r["reviewer_notes"] or "").strip()
        if notes:
            print(_dim(f"      note: {notes}"))
        if r.get("edited_title"):
            print(_dim(f"      edited -> {r['edited_title']}"))


def print_confirmation_state() -> None:
    """Closed-loop confirmation signal from clients. Complements the
    review curve (which is internal reviewer judgement) with the
    external client verdict."""
    counts = memory.confirmation_counts()
    if not counts:
        print(_dim("\nNo confirmation data yet "
                   "— run `py -3 -m tools.poll_replies` after the "
                   "client has replied to a verification email."))
        return
    print()
    print(_bold("Client confirmation state (across requirements_seen)"))
    print()
    total = sum(counts.values())
    order = ["confirmed", "needs_change", "rejected", "unclear", "pending"]
    color_map = {
        "confirmed": _green,
        "needs_change": _amber,
        "rejected": _red,
        "unclear": _dim,
        "pending": _dim,
    }
    for k in order:
        n = counts.get(k, 0)
        if n == 0:
            continue
        pct = (n / total) if total else 0
        bar = _bar(pct)
        line = f"  {k:14s} {n:4d}  ({pct:.0%})  {bar}"
        print(color_map.get(k, _dim)(line))
    if total:
        print()
        print(_dim(f"  total tracked: {total}"))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recent", type=int, default=0,
                    help="Show the last N review rows instead of the curve.")
    ap.add_argument("--no-confirmation", action="store_true",
                    help="Skip the client-confirmation state section "
                         "(useful for terse output).")
    args = ap.parse_args()

    if args.recent and args.recent > 0:
        print_recent(args.recent)
    else:
        print_curve()
        if not args.no_confirmation:
            print_confirmation_state()
    return 0


if __name__ == "__main__":
    sys.exit(main())
