"""Interactive reviewer for a verification doc — feeds the
calibration loop.

For each predicted requirement in the latest (or specified) JSON
sidecar:

    (k)eep      — send to client as-is
    (e)dit      — keep but reword the title; you provide the new one
    (r)eject    — false positive, do not send
    (s)kip      — defer this one for later
    (q)uit      — stop here, any unreviewed items stay unreviewed

Decisions persist to memory.requirement_reviews. Over time those
rows let calibration_report.py answer: are the LLM's stated
confidence numbers actually accurate?

Usage:
    py -3 -m tools.review_session                       # latest sidecar
    py -3 -m tools.review_session --sidecar <path>      # specific JSON
    py -3 -m tools.review_session --docx <path>         # auto-resolve
                                                        # sidecar from
                                                        # docx path

Aliases also accepted: 'a' for keep (accept), 'n' for reject (no), '1'
for keep, '0' for reject. Empty input defaults to 'k'.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

# Windows cmd.exe defaults to cp1252; the Unicode markers below need
# UTF-8. Reconfigure stdout/err if available (Python 3.7+).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

import memory  # noqa: E402


_REQ_DIR = _HERE / "data" / "requirements"


def _today_stamp() -> str:
    return dt.date.today().strftime("%Y-%m-%d")


def _latest_sidecar() -> Path | None:
    """Pick the most-recent Requirements Verification *.json under
    data/requirements/. Lets the user just run the command without
    naming a file."""
    if not _REQ_DIR.exists():
        return None
    candidates = sorted(_REQ_DIR.glob("Requirements Verification *.json"))
    return candidates[-1] if candidates else None


def _resolve_sidecar(args) -> Path | None:
    if args.sidecar:
        return Path(args.sidecar)
    if args.docx:
        return Path(args.docx).with_suffix(".json")
    return _latest_sidecar()


def _color(text: str, code: str) -> str:
    # Bare-bones ANSI — works on Windows Terminal / VS Code / modern
    # cmd.exe. Falls back gracefully on terminals that don't render it.
    return f"\033[{code}m{text}\033[0m"


def _bold(s: str) -> str:   return _color(s, "1")
def _dim(s: str) -> str:    return _color(s, "2")
def _green(s: str) -> str:  return _color(s, "32")
def _amber(s: str) -> str:  return _color(s, "33")
def _red(s: str) -> str:    return _color(s, "31")


_DECISION_ALIASES = {
    "k": "keep", "keep": "keep", "1": "keep", "a": "keep", "accept": "keep",
    "": "keep",  # default
    "e": "edit", "edit": "edit",
    "r": "reject", "reject": "reject", "0": "reject", "n": "reject", "no": "reject",
    "s": "skip", "skip": "skip",
    "q": "quit", "quit": "quit", "exit": "quit",
}


def _confidence_color(c: float | None) -> str:
    if c is None:
        return _dim("(no confidence)")
    if c >= 0.90:
        return _green(f"{c:.2f}")
    if c >= 0.75:
        return f"{c:.2f}"
    return _amber(f"{c:.2f} (review)")


def _prompt_decision(i: int, total: int, req: dict) -> tuple[str, str | None, str]:
    """Show one requirement, prompt for a decision. Returns
    (decision, edited_title_or_None, notes)."""
    title = (req.get("title") or "").strip() or "(no title)"
    summary = (req.get("summary") or "").strip()
    rationale = (req.get("rationale") or "").strip()
    confidence = req.get("confidence")
    sources = req.get("source_refs") or []
    try:
        conf_val = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        conf_val = None

    print()
    print(_bold(f"[{i}/{total}] {title}"))
    if summary:
        for ln in _wrap(summary, 76):
            print(f"   {ln}")
    if rationale:
        print(_dim(f"   Why: {rationale}"))
    if sources:
        print(_dim(f"   Sources: {', '.join(str(s) for s in sources[:3])}"
                   + ("…" if len(sources) > 3 else "")))
    print(f"   Confidence: {_confidence_color(conf_val)}")
    print(_dim("   [k]eep  [e]dit  [r]eject  [s]kip  [q]uit"))

    while True:
        raw = input("   > ").strip().lower()
        d = _DECISION_ALIASES.get(raw)
        if d is None:
            print(_amber(
                "   ? Type k/e/r/s/q (or accept/edit/reject/skip/quit)"))
            continue
        if d == "edit":
            new = input("   new title (empty = cancel edit): ").strip()
            if not new:
                continue
            notes = input("   notes (optional): ").strip()
            return ("edit", new, notes)
        if d in ("keep", "reject"):
            notes = input(_dim("   notes (optional, Enter to skip): ")).strip()
            return (d, None, notes)
        return (d, None, "")


def _wrap(text: str, width: int) -> list[str]:
    out: list[str] = []
    line = ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        out.append(line)
    return out


def review(sidecar_path: Path) -> int:
    if not sidecar_path.exists():
        print(_red(f"sidecar not found: {sidecar_path}"), file=sys.stderr)
        return 2
    try:
        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(_red(f"failed to parse {sidecar_path}: {e}"), file=sys.stderr)
        return 2

    reqs = data.get("requirements") or []
    if not reqs:
        print(_dim("No requirements in this sidecar — nothing to review."))
        return 0

    docx_path = data.get("docx_path") or ""
    print(_bold(f"Reviewing {len(reqs)} requirement(s)"))
    print(_dim(f"  sidecar: {sidecar_path}"))
    if docx_path:
        print(_dim(f"  docx:    {docx_path}"))

    decisions = {"keep": 0, "edit": 0, "reject": 0, "skip": 0}
    quit_early = False
    for idx, req in enumerate(reqs, 1):
        if not isinstance(req, dict):
            continue
        d, edited, notes = _prompt_decision(idx, len(reqs), req)
        if d == "quit":
            quit_early = True
            print(_dim("\nquit — remaining items left unreviewed."))
            break
        memory.record_review(
            requirement_title=req.get("title") or "",
            decision=d,
            predicted_confidence=req.get("confidence"),
            source_refs=req.get("source_refs") or [],
            edited_title=edited,
            reviewer_notes=notes,
            sidecar_path=str(sidecar_path),
            docx_path=docx_path,
        )
        decisions[d] = decisions.get(d, 0) + 1
        emoji = {"keep": _green("✓"), "edit": _amber("✎"),
                 "reject": _red("✗"), "skip": _dim("—")}.get(d, "?")
        print(f"   {emoji} recorded.")

    print()
    print(_bold("Review summary"))
    for d in ("keep", "edit", "reject", "skip"):
        print(f"  {d:7s} {decisions.get(d, 0)}")
    if quit_early:
        unreviewed = len(reqs) - sum(decisions.values())
        if unreviewed:
            print(_amber(f"  unreviewed: {unreviewed}"))
    print(_dim("\nRun  py -3 -m tools.calibration_report  to see the curve."))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sidecar", default=None,
                    help="Path to a Requirements Verification *.json "
                         "sidecar. Default: most-recent under "
                         "data/requirements/.")
    ap.add_argument("--docx", default=None,
                    help="Alternative: path to the .docx; the sidecar "
                         "is derived by swapping the suffix.")
    args = ap.parse_args()

    sidecar = _resolve_sidecar(args)
    if not sidecar:
        print(_red("No sidecar found. Run a verify_session first, or "
                   "pass --sidecar <path>."), file=sys.stderr)
        return 2
    return review(sidecar)


if __name__ == "__main__":
    sys.exit(main())
