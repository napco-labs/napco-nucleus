"""evals/run.py — orchestrator for the NAPCO Nucleus eval harness.

For each case in `evals/cases/<name>/`:

  1. Archive whatever is currently in data/requirements/sessions/
     current.docx (via session_doc.reset) — production state safe.
  2. Copy the case's session.docx into the live session path.
  3. Spawn `agent.py --task verify_session --dry-run` with
     NAPCO_NUCLEUS_EVAL_MODE=1 and NAPCO_NUCLEUS_DRY_RUN=1 in env so
     identify runs but no email draft / requirements_seen write
     happens.
  4. Read the JSON sidecar written by write_verification_docx.
  5. Score predicted vs expected via evals/score.score_case (uses
     Claude as judge unless --skip-llm-judge).
  6. Aggregate; write evals/results/<timestamp>.json; print a summary
     table.

Usage:
    py -3 -m evals.run                          # run all cases
    py -3 -m evals.run --case <case_name>       # one case
    py -3 -m evals.run --no-replay              # skip identify; score
                                                # whatever sidecar JSON
                                                # is already at
                                                # data/requirements/
                                                # Requirements Verification
                                                # <today>.json
    py -3 -m evals.run --skip-llm-judge         # skip LLM-as-judge;
                                                # just record counts and
                                                # confidence stats

Exit code 0 if all cases ran (regardless of pass/fail). Non-zero if a
case errored before scoring (missing fixture, agent crashed, etc.).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

from evals import score as eval_score  # noqa: E402
from tools import _session_doc as session_doc  # noqa: E402


CASES_DIR = _HERE / "cases"
RESULTS_DIR = _HERE / "results"
DATA_REQ_DIR = _ROOT / "data" / "requirements"


# ── Helpers ────────────────────────────────────────────────────────

def _git_commit() -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip() or "unknown"
    except Exception:
        pass
    return "unknown"


def _ts() -> str:
    return dt.datetime.now().strftime("%Y%m%dT%H%M%S")


def _today_stamp() -> str:
    return dt.date.today().strftime("%Y-%m-%d")


def _sidecar_path() -> Path:
    return DATA_REQ_DIR / f"Requirements Verification {_today_stamp()}.json"


def _verification_docx_path() -> Path:
    return DATA_REQ_DIR / f"Requirements Verification {_today_stamp()}.docx"


# ── Case discovery ─────────────────────────────────────────────────

def discover_cases(case_filter: str | None = None) -> list[dict]:
    """List runnable cases. Each case is a dict with name, session
    fixture path, expected.json path."""
    out: list[dict] = []
    if not CASES_DIR.exists():
        return out
    for case_dir in sorted(CASES_DIR.iterdir()):
        if not case_dir.is_dir():
            continue
        if case_filter and case_dir.name != case_filter:
            continue
        session_path = case_dir / "session.docx"
        expected_path = case_dir / "expected.json"
        if not session_path.exists():
            print(f"[skip] {case_dir.name}: missing session.docx",
                  file=sys.stderr)
            continue
        if not expected_path.exists():
            print(f"[skip] {case_dir.name}: missing expected.json",
                  file=sys.stderr)
            continue
        out.append({
            "name": case_dir.name,
            "dir": case_dir,
            "session_fixture": session_path,
            "expected_path": expected_path,
        })
    return out


# ── One case ──────────────────────────────────────────────────────

def _stage_fixture(session_fixture: Path, case_name: str) -> Path:
    """Archive the current production session, then drop the fixture
    in as the new current.docx. Returns the staged path."""
    session_doc.reset(label=f"eval-{case_name}-{_ts()}")
    shutil.copy2(str(session_fixture), str(session_doc.SESSION_PATH))
    return session_doc.SESSION_PATH


def _clear_today_verification_outputs() -> None:
    """Remove today's verification doc + sidecar so a stale file from a
    previous run isn't mistaken for this run's output."""
    for p in (_verification_docx_path(), _sidecar_path()):
        try:
            if p.exists():
                p.unlink()
        except Exception as e:
            print(f"  ! couldn't remove {p}: {e}", file=sys.stderr)


def _run_agent_verify_session(timeout_s: int = 600) -> dict:
    """Spawn agent.py --task verify_session --dry-run with eval env.
    Returns {returncode, stdout_tail, stderr_tail}."""
    env = os.environ.copy()
    env["NAPCO_NUCLEUS_EVAL_MODE"] = "1"
    env["NAPCO_NUCLEUS_DRY_RUN"] = "1"
    cmd = [sys.executable, "agent.py", "--task", "verify_session",
           "--dry-run"]
    try:
        proc = subprocess.run(
            cmd, env=env, cwd=str(_ROOT),
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "returncode": -1,
            "stdout_tail": (e.stdout or "")[-2000:] if isinstance(e.stdout, str) else "",
            "stderr_tail": f"timeout after {timeout_s}s",
            "timed_out": True,
        }
    return {
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-1000:],
        "timed_out": False,
    }


def _read_sidecar() -> dict:
    """Load the predicted-requirements JSON sidecar written by
    write_verification_docx. Empty dict (count=0, requirements=[]) if
    the file doesn't exist (the identifier correctly emitted no
    requirements)."""
    p = _sidecar_path()
    if not p.exists():
        return {"requirement_count": 0, "requirements": [], "missing": True}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"requirement_count": 0, "requirements": [],
                "parse_error": str(e)}


def run_case(case: dict, *, no_replay: bool, skip_llm_judge: bool) -> dict:
    name = case["name"]
    print(f"\n=== case: {name} ===")

    expected_doc = json.loads(case["expected_path"].read_text(encoding="utf-8"))

    if no_replay:
        print(f"[{name}] --no-replay: skipping identify, scoring current sidecar")
        agent_result = {"returncode": None, "stdout_tail": "(skipped)",
                        "stderr_tail": "", "timed_out": False,
                        "skipped": True}
    else:
        print(f"[{name}] staging fixture: {case['session_fixture'].name}")
        _clear_today_verification_outputs()
        _stage_fixture(case["session_fixture"], name)
        print(f"[{name}] running agent.py verify_session (eval+dry-run env)…")
        agent_result = _run_agent_verify_session()
        print(f"[{name}] agent exited rc={agent_result['returncode']}")
        if agent_result.get("timed_out"):
            print(f"[{name}] !! TIMED OUT", file=sys.stderr)

    predicted_doc = _read_sidecar()
    print(f"[{name}] predicted requirements: "
          f"{predicted_doc.get('requirement_count', 0)}")
    print(f"[{name}] expected requirements:  "
          f"{len(expected_doc.get('expected_requirements') or [])}")

    if skip_llm_judge:
        score = {
            "predicted_count": predicted_doc.get("requirement_count", 0),
            "expected_count": len(expected_doc.get("expected_requirements") or []),
            "note": "scoring skipped (--skip-llm-judge)",
        }
    else:
        try:
            score = eval_score.score_case(expected_doc, predicted_doc)
        except Exception as e:
            score = {"error": f"{type(e).__name__}: {e}"}
            print(f"[{name}] scorer error: {e}", file=sys.stderr)

    _print_case_summary(name, score)

    return {
        "case_name": name,
        "case_dir": str(case["dir"].relative_to(_ROOT).as_posix()),
        "expected_path": str(case["expected_path"].relative_to(_ROOT).as_posix()),
        "session_fixture_path": str(case["session_fixture"].relative_to(_ROOT).as_posix()),
        "agent": agent_result,
        "predicted_doc": predicted_doc,
        "score": score,
    }


def _print_case_summary(name: str, score: dict) -> None:
    if "error" in score:
        print(f"[{name}] SCORE: error — {score['error']}")
        return
    bits = [
        f"pred={score.get('predicted_count')}",
        f"exp={score.get('expected_count')}",
    ]
    p = score.get("precision")
    r = score.get("recall")
    f1 = score.get("f1")
    if p is not None and r is not None and f1 is not None:
        bits.append(f"P={p:.2f}")
        bits.append(f"R={r:.2f}")
        bits.append(f"F1={f1:.2f}")
    cc = score.get("citation_correctness")
    if cc is not None:
        bits.append(f"cite={cc:.2f}")
    mc = score.get("mean_predicted_confidence")
    if mc is not None:
        bits.append(f"conf={mc:.2f}")
    ex = score.get("extra_count")
    if ex:
        bits.append(f"extras={ex}")
    miss = score.get("missed_recall_count")
    if miss:
        bits.append(f"missed={miss}")
    cfv = score.get("confidence_floor_violations") or []
    if cfv:
        bits.append(f"floor-violations={len(cfv)}")
    print(f"[{name}] SCORE: " + "  ".join(bits))


# ── Aggregate + write results ─────────────────────────────────────

def _mean(values: list) -> float | None:
    cleaned = [v for v in values if isinstance(v, (int, float))]
    return (sum(cleaned) / len(cleaned)) if cleaned else None


def _summarize(case_results: list[dict]) -> dict:
    scores = [c["score"] for c in case_results if "score" in c]
    scored = [s for s in scores if "error" not in s and s.get("precision") is not None]

    return {
        "case_count": len(case_results),
        "scored_count": len(scored),
        "errored_count": sum(1 for s in scores if "error" in s),
        "mean_precision": _mean([s.get("precision") for s in scored]),
        "mean_recall": _mean([s.get("recall") for s in scored]),
        "mean_f1": _mean([s.get("f1") for s in scored]),
        "mean_citation_correctness": _mean(
            [s.get("citation_correctness") for s in scored]),
        "mean_predicted_confidence": _mean(
            [s.get("mean_predicted_confidence") for s in scored]),
        "total_extras": sum((s.get("extra_count") or 0) for s in scored),
        "total_missed_recall": sum((s.get("missed_recall_count") or 0)
                                   for s in scored),
        "total_floor_violations": sum(
            len(s.get("confidence_floor_violations") or []) for s in scored),
    }


def _write_results(case_results: list[dict], options: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = _ts()
    out = {
        "run_id": run_id,
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "options": options,
        "cases": case_results,
        "summary": _summarize(case_results),
    }
    path = RESULTS_DIR / f"{run_id}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False,
                               default=str),
                    encoding="utf-8")
    return path


def _print_run_summary(case_results: list[dict], result_path: Path) -> None:
    s = _summarize(case_results)
    print("\n" + "=" * 60)
    print("EVAL RUN SUMMARY")
    print("=" * 60)
    print(f"Cases run:           {s['case_count']}")
    print(f"Cases scored:        {s['scored_count']}")
    if s["errored_count"]:
        print(f"Cases errored:       {s['errored_count']}")
    for key, label in [
        ("mean_precision", "Mean precision"),
        ("mean_recall", "Mean recall"),
        ("mean_f1", "Mean F1"),
        ("mean_citation_correctness", "Mean citation correctness"),
        ("mean_predicted_confidence", "Mean predicted confidence"),
    ]:
        v = s.get(key)
        print(f"{label:25s} {v:.3f}" if v is not None else f"{label:25s} —")
    if s["total_extras"]:
        print(f"Total false positives:  {s['total_extras']}")
    if s["total_missed_recall"]:
        print(f"Total missed:           {s['total_missed_recall']}")
    if s["total_floor_violations"]:
        print(f"Confidence-floor violations: {s['total_floor_violations']}")
    print(f"\nResults: {result_path.relative_to(_ROOT).as_posix()}")


# ── Main ──────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", default=None,
                    help="Run only the case with this name (matches "
                         "evals/cases/<name>/). Default: all cases.")
    ap.add_argument("--no-replay", action="store_true",
                    help="Skip the identify run; score whatever JSON "
                         "sidecar is currently in data/requirements/.")
    ap.add_argument("--skip-llm-judge", action="store_true",
                    help="Skip the LLM-as-judge scoring step; just "
                         "record predicted/expected counts and "
                         "confidence stats. Useful when iterating on "
                         "the runner itself without paying for Claude "
                         "calls.")
    args = ap.parse_args()

    options = {
        "case_filter": args.case,
        "no_replay": args.no_replay,
        "skip_llm_judge": args.skip_llm_judge,
    }

    cases = discover_cases(args.case)
    if not cases:
        target = f"case '{args.case}'" if args.case else "any cases"
        print(f"No runnable cases found ({target}).", file=sys.stderr)
        return 2

    print(f"Discovered {len(cases)} case(s).")

    case_results: list[dict] = []
    for case in cases:
        try:
            r = run_case(case,
                          no_replay=args.no_replay,
                          skip_llm_judge=args.skip_llm_judge)
        except Exception as e:
            print(f"[{case['name']}] !! unhandled error: {e}",
                  file=sys.stderr)
            r = {"case_name": case["name"], "error": f"{type(e).__name__}: {e}"}
        case_results.append(r)

    result_path = _write_results(case_results, options)
    _print_run_summary(case_results, result_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
