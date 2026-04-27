"""
NAPCO Nucleus — shared internal state for the tools/ package.

Module-level setup that every tool submodule needs:
  - Sibling project paths (MVP-Access-API-Test, the 3 E2E variants)
  - sys.path injection so MVP-Access-API-Test/agent/* is importable
  - Lazy / fault-tolerant imports of the sibling agent modules
  - In-process STATE dict (carries test results between tool calls)
  - Helpers for shaping tool return values and summarizing results

Importing this module triggers the sibling imports once. tools/tests.py,
tools/analysis.py, tools/files.py, tools/git.py and tools/report.py
all pull from here so the sibling imports never fire twice.

Underscore prefix keeps it out of the public tools/ namespace — nothing
outside the package should import it directly.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime

logger = logging.getLogger(__name__)

# ---- Peer project locations ------------------------------------------------
# Default to the parent folder of THIS package's parent (i.e. NN's parent).
# Override with MVP_PROJECTS_ROOT if the sibling layout differs (e.g. on a
# CI runner where the checkout lives somewhere other than E:\Projects\).
_NN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DEFAULT_PROJECTS_ROOT = os.path.abspath(os.path.join(_NN_ROOT, ".."))
PROJECTS_ROOT = os.getenv("MVP_PROJECTS_ROOT", _DEFAULT_PROJECTS_ROOT)
API_TEST_PROJECT = os.path.join(PROJECTS_ROOT, "MVP-Access-API-Test")
E2E_PROJECTS = {
    "full":    os.path.join(PROJECTS_ROOT, "MVP-Access-E2E-Test"),
    "easy":    os.path.join(PROJECTS_ROOT, "MVP-Access-Easy-E2E-Test"),
    "release": os.path.join(PROJECTS_ROOT, "MVP-Access-Release-Test"),
}

# Shared map for tools that accept a project= arg. ai-agent (NN itself) is
# added by individual tools when needed (e.g. git_diff, recent_commits).
PROJECT_PATHS = {
    "api-test":    API_TEST_PROJECT,
    "e2e-full":    E2E_PROJECTS["full"],
    "e2e-easy":    E2E_PROJECTS["easy"],
    "e2e-release": E2E_PROJECTS["release"],
}

# ---- Sibling agent imports (fault-tolerant) -------------------------------
# NN reuses the API-Test project's agent/ Python modules: config, the test
# runners, the PDF/email plumbing, history snapshots, coverage, bug-reporter,
# self-healing patch-generator, and the Teams digest. They are imported here
# lazily so that NN still runs (for Requirement Management, Daily Report)
# when the sibling isn't on disk — e.g. on a CI runner that checks NN out
# alone. Test-orchestration tools fail at call time with a clear error.
_API_AGENT_DIR = os.path.join(API_TEST_PROJECT, "agent")
if _API_AGENT_DIR not in sys.path:
    sys.path.insert(0, _API_AGENT_DIR)

TEST_INFRA_AVAILABLE = False
try:
    import config  # noqa: E402 — sibling MVP-Access-API-Test/agent/config.py
    from run_all_tests import (  # noqa: E402
        run_load_tests_multi,
        run_api_tests,
        run_integration_tests,
    )
    from report_generator import generate_pdf_report as _generate_pdf  # noqa: E402
    from email_sender import send_report_email  # noqa: E402
    import history         # noqa: E402 — per-run snapshot store + regression/flaky analysis
    import coverage as _coverage  # noqa: E402 — swagger-vs-tests coverage
    import bug_reporter   # noqa: E402 — markdown bug-draft generator
    import patch_generator # noqa: E402 — self-healing unified-diff patches
    import teams_notifier # noqa: E402 — optional digest to Microsoft Teams webhook
    TEST_INFRA_AVAILABLE = True
except ImportError as _test_infra_err:
    logger.warning(
        f"Sibling MVP-Access-API-Test/agent not on sys.path — "
        f"test-orchestration tools will fail at call time: {_test_infra_err} "
        f"(resolved path: {_API_AGENT_DIR}, "
        f"exists={os.path.isdir(_API_AGENT_DIR)}, "
        f"PROJECTS_ROOT={PROJECTS_ROOT}, "
        f"MVP_PROJECTS_ROOT env={os.getenv('MVP_PROJECTS_ROOT') or '(unset)'})"
    )
    config = None  # type: ignore[assignment]
    run_load_tests_multi = run_api_tests = run_integration_tests = None  # type: ignore[assignment]
    _generate_pdf = None  # type: ignore[assignment]
    send_report_email = None  # type: ignore[assignment]
    history = None  # type: ignore[assignment]
    _coverage = None  # type: ignore[assignment]
    bug_reporter = None  # type: ignore[assignment]
    patch_generator = None  # type: ignore[assignment]
    teams_notifier = None  # type: ignore[assignment]


# ---- In-process STATE -----------------------------------------------------
# Carries test results between tool calls in a single agent run. The PDF
# generator + email sender + Teams digest all read from this; cleaned by
# clean_reports_folder.
STATE: dict = {
    "load": None,
    "api": None,
    "integration": None,
    "e2e": None,
    "report_paths": [],
    "started_at": datetime.now(),
    "requirements": {
        "last_poll": None,
        "last_ingested": 0,
        "last_published": [],
        "last_proposed_tasks_path": None,
    },
}


# ---- Tool return-shape helpers --------------------------------------------
def _text(obj) -> dict:
    """Format helper for @tool — returns the MCP-required content shape."""
    return {"content": [{"type": "text", "text": json.dumps(obj, default=str)}]}


def _summarize_load(results_list):
    return [
        {
            "tier": r["tier"],
            "status": r["status"],
            "users": r["users"],
            "total_requests": r["total_requests"],
            "total_failures": r["total_failures"],
            "avg_response_time_ms": round(r["avg_response_time"], 1),
            "requests_per_sec": round(r["requests_per_sec"], 1),
            "error_types": len(r.get("error_details", [])),
        }
        for r in results_list
    ]


def _summarize_api(result):
    return {
        "status": result["status"],
        "total": result["total"],
        "passed": result["passed"],
        "failed": result["failed"],
        "duration_ms": result.get("duration_ms", 0),
        "failure_samples": result.get("failures", [])[:5],
    }


def _summarize_integration(result):
    return {
        "status": result["status"],
        "total": result["total"],
        "passed": result["passed"],
        "failed": result["failed"],
        "skipped": result["skipped"],
        "errors": result["errors"],
        "duration_s": round(result.get("duration", 0), 1),
        "failure_samples": [
            {"name": f["name"], "message": (f.get("message") or "")[:300]}
            for f in result.get("failures", [])[:5]
        ],
    }


def _resolve_in_project(project_key: str, rel_path: str):
    """Resolve a relative path under one of PROJECT_PATHS, refusing escapes."""
    root = PROJECT_PATHS.get(project_key)
    if not root:
        return None
    rel = (rel_path or ".").replace("\\", "/").lstrip("/")
    full = os.path.abspath(os.path.join(root, rel))
    if not full.startswith(os.path.abspath(root)):
        return None
    return full


def _format_users(n):
    return f"{n // 1000}K" if n >= 1000 and n % 1000 == 0 else str(n)


def _parse_run_time_seconds(s):
    s = (s or "").strip().lower()
    unit = s[-1] if s and s[-1] in ("s", "m", "h") else "s"
    try:
        n = int(s[:-1] if unit in ("s", "m", "h") else s)
    except ValueError:
        return 0
    return n * {"s": 1, "m": 60, "h": 3600}[unit]
