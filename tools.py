"""
Tools exposed to the MVP Access AI agent via the Claude Agent SDK.

Wraps test-running + reporting code from MVP-Access-API-Test/agent/ (reused via
sys.path) and Playwright invocations for the three E2E projects.
"""

import os
import sys
import json
import glob
import logging
import subprocess
from datetime import datetime

from claude_agent_sdk import tool

# ---- Peer project locations ------------------------------------------------
PROJECTS_ROOT = r"E:\Projects"
API_TEST_PROJECT = os.path.join(PROJECTS_ROOT, "MVP-Access-API-Test")
E2E_PROJECTS = {
    "full":    os.path.join(PROJECTS_ROOT, "MVP-Access-E2E-Test"),
    "easy":    os.path.join(PROJECTS_ROOT, "MVP-Access-Easy-E2E-Test"),
    "release": os.path.join(PROJECTS_ROOT, "MVP-Access-Release-Test"),
}

# Reuse the API-Test project's agent/ code.
_API_AGENT_DIR = os.path.join(API_TEST_PROJECT, "agent")
if _API_AGENT_DIR not in sys.path:
    sys.path.insert(0, _API_AGENT_DIR)

import config  # noqa: E402 — from MVP-Access-API-Test/agent/
from run_all_tests import (  # noqa: E402
    run_load_tests_multi,
    run_api_tests,
    run_integration_tests,
)
from report_generator import generate_pdf_report as _generate_pdf  # noqa: E402
from email_sender import send_report_email  # noqa: E402

logger = logging.getLogger(__name__)

# In-memory cache of this run's results.
STATE: dict = {
    "load": None,
    "api": None,
    "integration": None,
    "e2e": None,
    "report_paths": [],
    "started_at": datetime.now(),
}

_PROJECT_PATHS = {
    "api-test":    API_TEST_PROJECT,
    "e2e-full":    E2E_PROJECTS["full"],
    "e2e-easy":    E2E_PROJECTS["easy"],
    "e2e-release": E2E_PROJECTS["release"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _text(obj) -> dict:
    """Return-format helper for @tool — must yield {'content': [{'type':'text', ...}]}."""
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
    root = _PROJECT_PATHS.get(project_key)
    if not root:
        return None
    rel = (rel_path or ".").replace("\\", "/").lstrip("/")
    full = os.path.abspath(os.path.join(root, rel))
    if not full.startswith(os.path.abspath(root)):
        return None
    return full


# ---------------------------------------------------------------------------
# @tool definitions
# ---------------------------------------------------------------------------
@tool(
    "run_load_tests",
    "Run Locust load tests across all tiers (1K/10K/50K users). Returns per-tier summary. Takes 10+ min. Call AT MOST ONCE per run.",
    {},
)
async def run_load_tests_tool(_args):
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    results = run_load_tests_multi()
    STATE["load"] = results
    return _text(_summarize_load(results))


@tool(
    "run_api_tests",
    "Run the Postman/Newman API test collection. Returns pass/fail counts.",
    {},
)
async def run_api_tests_tool(_args):
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    result = run_api_tests()
    STATE["api"] = result
    return _text(_summarize_api(result))


@tool(
    "run_integration_tests",
    "Run pytest integration tests. Returns pass/fail counts and failure messages.",
    {},
)
async def run_integration_tests_tool(_args):
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    result = run_integration_tests()
    STATE["integration"] = result
    return _text(_summarize_integration(result))


@tool(
    "run_e2e_tests",
    "Run Playwright E2E tests. suite is one of: full | easy | release.",
    {"suite": str},
)
async def run_e2e_tests_tool(args):
    suite = args.get("suite", "full")
    project_dir = E2E_PROJECTS.get(suite)
    if not project_dir or not os.path.isdir(project_dir):
        return _text({"status": "ERROR", "error": f"Unknown/missing E2E suite: {suite}"})

    cmd = ["npx", "playwright", "test", "--project=chromium", "--reporter=json"]
    result = {
        "suite": suite, "status": "FAILED",
        "total": 0, "passed": 0, "failed": 0, "skipped": 0,
        "duration_s": 0, "failure_samples": [],
    }

    try:
        proc = subprocess.run(
            cmd, cwd=project_dir, capture_output=True, text=True,
            timeout=1800, shell=True,
        )
        stdout = proc.stdout or ""
        try:
            report = json.loads(stdout)
        except json.JSONDecodeError:
            idx = stdout.find("{")
            report = json.loads(stdout[idx:]) if idx >= 0 else {}

        stats = report.get("stats", {})
        result["total"] = (
            stats.get("expected", 0) + stats.get("unexpected", 0) + stats.get("skipped", 0)
        )
        result["passed"] = stats.get("expected", 0)
        result["failed"] = stats.get("unexpected", 0)
        result["skipped"] = stats.get("skipped", 0)
        result["duration_s"] = round(stats.get("duration", 0) / 1000.0, 1)

        def walk(suites):
            for s in suites or []:
                for spec in s.get("specs", []):
                    for test in spec.get("tests", []):
                        for res in test.get("results", []):
                            if res.get("status") in ("failed", "timedOut"):
                                err = (res.get("error") or {}).get("message", "")
                                result["failure_samples"].append({
                                    "name": spec.get("title", ""),
                                    "message": err[:300],
                                })
                yield from walk(s.get("suites"))
        list(walk(report.get("suites", [])))

        if result["total"] > 0 and result["failed"] == 0:
            result["status"] = "PASSED"
        elif result["failed"] > 0:
            result["status"] = "PARTIAL"

    except subprocess.TimeoutExpired:
        result["status"] = "TIMEOUT"
    except Exception as e:
        logger.exception("E2E tool error")
        result["error"] = str(e)

    STATE["e2e"] = result
    summary = dict(result)
    summary["failure_samples"] = result["failure_samples"][:5]
    return _text(summary)


@tool(
    "list_project_files",
    "List files under a sibling project (api-test, e2e-full, e2e-easy, e2e-release). directory is relative to project root. pattern defaults to '*.py'.",
    {"project": str, "directory": str, "pattern": str},
)
async def list_project_files_tool(args):
    full = _resolve_in_project(args["project"], args["directory"])
    if not full:
        return _text({"error": "Invalid project or directory."})
    if not os.path.isdir(full):
        return _text({"error": f"Not a directory: {args['directory']}"})
    pattern = args.get("pattern") or "*.py"
    matches = glob.glob(os.path.join(full, "**", pattern), recursive=True)
    root = _PROJECT_PATHS[args["project"]]
    return _text([os.path.relpath(m, root).replace("\\", "/") for m in matches][:200])


@tool(
    "read_file",
    "Read a file under a sibling project for code review. Truncates at 200KB.",
    {"project": str, "path": str},
)
async def read_file_tool(args):
    full = _resolve_in_project(args["project"], args["path"])
    if not full:
        return _text({"error": "Invalid project or path."})
    if not os.path.isfile(full):
        return _text({"error": f"File not found: {args['path']}"})
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(200_000)
    return _text({
        "project": args["project"],
        "path": args["path"],
        "content": content,
        "truncated": len(content) == 200_000,
    })


@tool(
    "generate_pdf_report",
    "Generate the consolidated PDF report from collected results. Returns the PDF path.",
    {},
)
async def generate_pdf_report_tool(_args):
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    timestamp = STATE["started_at"].strftime("%Y%m%d_%H%M%S")
    path = os.path.join(config.REPORTS_DIR, f"Test_Report_{timestamp}.pdf")

    load_list = STATE["load"] or []
    api_result = STATE["api"] or {
        "status": "SKIPPED", "total": 0, "passed": 0, "failed": 0,
        "skipped": 0, "duration_ms": 0, "requests": [], "failures": [],
    }
    integ_result = STATE["integration"] or {
        "status": "SKIPPED", "total": 0, "passed": 0, "failed": 0,
        "skipped": 0, "errors": 0, "duration": 0, "tests": [], "failures": [],
    }

    _generate_pdf(
        load_results_list=load_list,
        api_results=api_result,
        integration_results=integ_result,
        output_path=path,
        run_date=STATE["started_at"],
    )
    STATE["report_paths"].append(path)
    return _text({"pdf_path": path, "exists": os.path.exists(path)})


@tool(
    "send_email_report",
    "Email the latest generated PDF to TEAM_EMAILS (from MVP-Access-API-Test/.env).",
    {"summary": str},
)
async def send_email_report_tool(args):
    if not STATE["report_paths"]:
        return _text({"error": "No report generated yet. Call generate_pdf_report first."})
    if not config.TEAM_EMAILS:
        return _text({"error": "TEAM_EMAILS not configured in MVP-Access-API-Test/.env."})
    send_report_email(STATE["report_paths"], STATE["started_at"])
    return _text({
        "sent_to": config.TEAM_EMAILS,
        "attachments": [os.path.basename(p) for p in STATE["report_paths"]],
        "summary_included": bool((args or {}).get("summary")),
    })


ALL_TOOLS = [
    run_load_tests_tool,
    run_api_tests_tool,
    run_integration_tests_tool,
    run_e2e_tests_tool,
    list_project_files_tool,
    read_file_tool,
    generate_pdf_report_tool,
    send_email_report_tool,
]

TOOL_NAMES = [
    "run_load_tests", "run_api_tests", "run_integration_tests", "run_e2e_tests",
    "list_project_files", "read_file", "generate_pdf_report", "send_email_report",
]
