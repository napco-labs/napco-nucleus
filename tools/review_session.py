"""Interactive reviewer for a verification doc — feeds the
calibration loop.

For each predicted requirement in the latest (or specified) JSON
sidecar:

    (k)eep      — send to client as-is
    (e)dit      — keep but reword the title; you provide the new one
    (r)eject    — false positive, do not send
    (s)kip      — defer this one for later
    (p)lay      — extract + play the call audio snippet(s) for this
                  requirement (uses the time_ranges from the sidecar).
                  Only shown when the requirement has MEETING sources.
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
    py -3 -m tools.review_session --no-audio            # disable [p]lay
                                                        # (headless / CI)
    py -3 -m tools.review_session --track both          # play mic+speaker

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
from tools import audio_snippet  # noqa: E402


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
    "p": "play", "play": "play",
    "q": "quit", "quit": "quit", "exit": "quit",
}


def _meeting_ranges(req: dict) -> list[dict]:
    """Return the subset of req['time_ranges'] that point at MEETING
    Source IDs (i.e. real call recordings). Other entries are ignored."""
    out: list[dict] = []
    for tr in req.get("time_ranges") or []:
        if not isinstance(tr, dict):
            continue
        sid = (tr.get("source_id") or "").strip()
        start = (tr.get("start") or "").strip()
        end = (tr.get("end") or "").strip()
        if not sid or not start or not end:
            continue
        if not sid.startswith("call/"):
            continue
        out.append({"source_id": sid, "start": start, "end": end})
    return out


def _play_snippets(req: dict, track: str, padding: float) -> None:
    """Extract + play the audio snippets for a requirement. Prints a
    note and returns silently if nothing is playable."""
    ranges = _meeting_ranges(req)
    if not ranges:
        print(_amber("   no MEETING time_ranges on this requirement — "
                     "nothing to play."))
        return
    for i, tr in enumerate(ranges, 1):
        try:
            paths = audio_snippet.extract_snippet(
                source_id=tr["source_id"],
                start=tr["start"],
                end=tr["end"],
                track=track,
                padding_s=padding,
            )
        except Exception as e:
            print(_amber(f"   ! range {i}/{len(ranges)} "
                         f"({tr['start']}-{tr['end']}): {e}"))
            continue
        if not paths:
            print(_amber(f"   ! range {i}/{len(ranges)}: no snippet produced "
                         f"(missing track on central?)"))
            continue
        for p in paths:
            size_kb = p.stat().st_size / 1024
            print(f"   {_dim('->')} {p.name}  ({size_kb:.1f} KB)")
        ok = audio_snippet.play_audio(paths[0])
        if not ok:
            print(_amber(f"   ! couldn't auto-open {paths[0].name}; "
                         f"open it manually from {paths[0].parent}"))


def _confidence_color(c: float | None) -> str:
    if c is None:
        return _dim("(no confidence)")
    if c >= 0.90:
        return _green(f"{c:.2f}")
    if c >= 0.75:
        return f"{c:.2f}"
    return _amber(f"{c:.2f} (review)")


def _prompt_decision(i: int, total: int, req: dict, *,
                     audio_enabled: bool, audio_track: str,
                     audio_padding: float
                     ) -> tuple[str, str | None, str]:
    """Show one requirement, prompt for a decision. Returns
    (decision, edited_title_or_None, notes)."""
    title = (req.get("title") or "").strip() or "(no title)"
    summary = (req.get("summary") or "").strip()
    rationale = (req.get("rationale") or "").strip()
    confidence = req.get("confidence")
    sources = req.get("source_refs") or []
    ranges = _meeting_ranges(req) if audio_enabled else []
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
    if ranges:
        preview = ", ".join(f"{r['start']}-{r['end']}" for r in ranges[:2])
        if len(ranges) > 2:
            preview += f", +{len(ranges) - 2} more"
        print(_dim(f"   Audio:   {len(ranges)} range(s) ({preview})"))
        print(_dim("   [k]eep  [e]dit  [r]eject  [s]kip  "
                   "[p]lay audio  [q]uit"))
    else:
        print(_dim("   [k]eep  [e]dit  [r]eject  [s]kip  [q]uit"))

    while True:
        raw = input("   > ").strip().lower()
        d = _DECISION_ALIASES.get(raw)
        if d is None:
            print(_amber(
                "   ? Type k/e/r/s/p/q (or accept/edit/reject/skip/play/quit)"))
            continue
        if d == "play":
            if not audio_enabled:
                print(_amber("   audio disabled (--no-audio)."))
                continue
            _play_snippets(req, track=audio_track, padding=audio_padding)
            continue  # stay on this requirement
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


def review(sidecar_path: Path, *,
           audio_enabled: bool = True,
           audio_track: str = "speaker",
           audio_padding: float = 2.0) -> int:
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
    if audio_enabled:
        n_with_audio = sum(1 for r in reqs
                           if isinstance(r, dict) and _meeting_ranges(r))
        print(_dim(f"  audio:   on, track={audio_track}, "
                   f"{n_with_audio}/{len(reqs)} item(s) have call ranges"))
    else:
        print(_dim("  audio:   off (--no-audio)"))

    decisions = {"keep": 0, "edit": 0, "reject": 0, "skip": 0}
    quit_early = False
    for idx, req in enumerate(reqs, 1):
        if not isinstance(req, dict):
            continue
        d, edited, notes = _prompt_decision(
            idx, len(reqs), req,
            audio_enabled=audio_enabled,
            audio_track=audio_track,
            audio_padding=audio_padding,
        )
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
    ap.add_argument("--no-audio", dest="audio_enabled",
                    action="store_false",
                    help="Disable the [p]lay action (headless / CI use).")
    ap.set_defaults(audio_enabled=True)
    ap.add_argument("--track", default="speaker",
                    choices=("mic", "speaker", "both"),
                    help="Which track to extract on [p]lay. Default "
                         "'speaker' (the client; most useful for "
                         "review).")
    ap.add_argument("--padding", type=float, default=2.0,
                    help="Seconds padded on each side of a snippet. "
                         "Default 2.0.")
    args = ap.parse_args()

    sidecar = _resolve_sidecar(args)
    if not sidecar:
        print(_red("No sidecar found. Run a verify_session first, or "
                   "pass --sidecar <path>."), file=sys.stderr)
        return 2
    return review(sidecar,
                  audio_enabled=args.audio_enabled,
                  audio_track=args.track,
                  audio_padding=args.padding)


if __name__ == "__main__":
    sys.exit(main())
