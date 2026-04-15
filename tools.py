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
    "write_file",
    "Write (or overwrite) a full file under a sibling project. Creates parent dirs as needed. Use for whole-file rewrites. For small edits, prefer edit_file.",
    {"project": str, "path": str, "content": str},
)
async def write_file_tool(args):
    full = _resolve_in_project(args["project"], args["path"])
    if not full:
        return _text({"error": "Invalid project or path."})
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="") as f:
        f.write(args["content"])
    return _text({
        "project": args["project"],
        "path": args["path"],
        "bytes_written": len(args["content"].encode("utf-8")),
        "action": "written",
    })


@tool(
    "edit_file",
    "Edit a file by exact string replacement. old_string must match exactly once. Safer than write_file for small changes.",
    {"project": str, "path": str, "old_string": str, "new_string": str},
)
async def edit_file_tool(args):
    full = _resolve_in_project(args["project"], args["path"])
    if not full:
        return _text({"error": "Invalid project or path."})
    if not os.path.isfile(full):
        return _text({"error": f"File not found: {args['path']}"})
    with open(full, "r", encoding="utf-8") as f:
        content = f.read()
    old = args["old_string"]
    new = args["new_string"]
    count = content.count(old)
    if count == 0:
        return _text({"error": "old_string not found in file."})
    if count > 1:
        return _text({"error": f"old_string matches {count} places — make it unique."})
    with open(full, "w", encoding="utf-8", newline="") as f:
        f.write(content.replace(old, new, 1))
    return _text({
        "project": args["project"],
        "path": args["path"],
        "action": "edited",
    })


# ─── Non-destructive probe list for check_all_endpoints_health ──────────
# Each tuple: (method, path_template, probe_type)
#   probe_type "list"        — expect 200, probes a list/collection GET
#   probe_type "get_by_id"   — expect 200|400|404 with a bogus id (endpoint wired up?)
#   probe_type "post_empty"  — send {} or bad payload, expect 400/422 (endpoint wired up?)
#   probe_type "put_bogus"   — PUT to a bogus id, expect 200|204|400|404 (accepts request)
#   probe_type "delete_bogus"— DELETE bogus id, expect 200|204|400|404|405|500 (reachable)
_ALL_ENDPOINT_PROBES = [
    # Auth
    ("POST", "/api/account/login", "special_login"),
    ("POST", "/api/Account/RefreshToken", "post_empty"),
    ("POST", "/api/Account/DealerLogin", "post_empty"),
    # Organization
    ("GET", "/api/PartitionGroup?page=1&pageSize=1", "list"),
    ("POST", "/api/PartitionGroup", "post_empty"),
    ("DELETE", "/api/PartitionGroup/99999999", "delete_bogus"),
    ("GET", "/api/DepartmentInfo?page=1&pageSize=1", "list"),
    ("POST", "/api/DepartmentInfo", "post_empty"),
    ("GET", "/api/DepartmentInfo/Details?id=99999999", "get_by_id"),
    ("PUT", "/api/DepartmentInfo/99999999", "put_bogus"),
    ("DELETE", "/api/DepartmentInfo/99999999", "delete_bogus"),
    ("GET", "/api/LocationInfo?page=1&pageSize=1", "list"),
    ("POST", "/api/LocationInfo", "post_empty"),
    ("GET", "/api/LocationInfo/Details?id=99999999", "get_by_id"),
    ("PUT", "/api/LocationInfo/99999999", "put_bogus"),
    ("DELETE", "/api/LocationInfo/99999999", "delete_bogus"),
    ("GET", "/api/Schedule?page=1&pageSize=1", "list"),
    ("POST", "/api/Schedule", "post_empty"),
    ("GET", "/api/Schedule/Details?id=99999999", "get_by_id"),
    ("PUT", "/api/Schedule/99999999", "put_bogus"),
    ("DELETE", "/api/Schedule/99999999", "delete_bogus"),
    ("GET", "/api/Holiday?page=1&pageSize=1", "list"),
    ("POST", "/api/Holiday", "post_empty"),
    ("GET", "/api/Holiday/Details?id=99999999", "get_by_id"),
    ("PUT", "/api/Holiday/99999999", "put_bogus"),
    ("DELETE", "/api/Holiday/99999999", "delete_bogus"),
    # Hardware
    ("GET", "/api/Panel?page=1&pageSize=1", "list"),
    ("GET", "/api/Panel/Details?id=99999999", "get_by_id"),
    ("GET", "/api/Reader?page=1&pageSize=1", "list"),
    ("GET", "/api/Reader/Details?id=99999999", "get_by_id"),
    # Access control
    ("GET", "/api/FacilityCode?page=1&pageSize=1", "list"),
    ("POST", "/api/FacilityCode", "post_empty"),
    ("GET", "/api/FacilityCode/Details?id=99999999", "get_by_id"),
    ("PUT", "/api/FacilityCode/99999999", "put_bogus"),
    ("DELETE", "/api/FacilityCode/99999999", "delete_bogus"),
    ("GET", "/api/AccessGroup?page=1&pageSize=1", "list"),
    ("POST", "/api/AccessGroup", "post_empty"),
    ("GET", "/api/AccessGroup/Details?id=99999999", "get_by_id"),
    ("PUT", "/api/AccessGroup/99999999", "put_bogus"),
    ("DELETE", "/api/AccessGroup/99999999", "delete_bogus"),
    ("GET", "/api/Role?page=1&pageSize=1", "list"),
    ("POST", "/api/Role", "post_empty"),
    ("GET", "/api/Role/Details?id=99999999", "get_by_id"),
    ("DELETE", "/api/Role/99999999", "delete_bogus"),
    ("GET", "/api/Operator?page=1&pageSize=1", "list"),
    ("POST", "/api/Operator", "post_empty"),
    ("GET", "/api/Operator/Details?id=99999999", "get_by_id"),
    ("PUT", "/api/Operator/99999999", "put_bogus"),
    ("DELETE", "/api/Operator/99999999", "delete_bogus"),
    ("GET", "/api/BadgeFormat?page=1&pageSize=1", "list"),
    ("GET", "/api/BadgeFormat/Details?id=99999999", "get_by_id"),
    # People & badges
    ("GET", "/api/Person?page=1&pageSize=1", "list"),
    ("POST", "/api/Person", "post_empty"),
    ("POST", "/api/Person/Search", "post_empty"),
    ("GET", "/api/Person/Details?id=99999999", "get_by_id"),
    ("PUT", "/api/Person/99999999", "put_bogus"),
    ("DELETE", "/api/Person/99999999", "delete_bogus"),
    ("GET", "/api/PersonImage?page=1&pageSize=1", "list"),
    ("POST", "/api/PersonImage", "post_empty"),
    ("PUT", "/api/PersonImage/99999999", "put_bogus"),
    ("DELETE", "/api/PersonImage/99999999", "delete_bogus"),
    ("GET", "/api/Badge?page=1&pageSize=1", "list"),
    ("POST", "/api/Badge", "post_empty"),
    ("POST", "/api/Badge/Search", "post_empty"),
    ("GET", "/api/Badge/Details?id=99999999", "get_by_id"),
    ("PUT", "/api/Badge/99999999", "put_bogus"),
    ("DELETE", "/api/Badge/99999999", "delete_bogus"),
    ("GET", "/api/BadgeAccess?page=1&pageSize=1", "list"),
    ("POST", "/api/BadgeAccess", "post_empty"),
    ("GET", "/api/BadgeAccess/Details?id=99999999", "get_by_id"),
    ("PUT", "/api/BadgeAccess/99999999", "put_bogus"),
    ("DELETE", "/api/BadgeAccess/99999999", "delete_bogus"),
    # Events & runtime
    ("GET", "/api/Event?page=1&pageSize=1&fromDate=2023-01-01 00:00:00.000&toDate=2030-12-31 23:59:59.999", "list"),
    ("GET", "/api/Event/EventClassDefinations", "list"),
    ("POST", "/api/Event/AddOtherEvent", "post_empty"),
    ("PUT", "/api/Event/Acknowledge/99999999", "put_bogus"),
    ("GET", "/api/Audit?page=1&pageSize=1", "list"),
    ("GET", "/api/DeviceStatus/panel", "list"),
    ("POST", "/api/ManualDoor/Execute", "post_empty"),
    ("POST", "/api/ManualRelay/Execute", "post_empty"),
]


@tool(
    "check_all_endpoints_health",
    "Non-destructively probe EVERY API endpoint (78 total) and report healthy/slow/unhealthy. Uses bogus IDs and empty bodies — creates no data. Runs in ~20-60 seconds. Ideal morning / pre-deployment smoke check.",
    {},
)
async def check_all_endpoints_health_tool(_args):
    import base64
    import requests
    from datetime import datetime

    base_url = os.getenv("BASE_URL")
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    api_key = os.getenv("API_KEY")
    username = os.getenv("USER_ID")
    password = os.getenv("PASSWORD")
    account = os.getenv("COMPANY_ID")
    if not all([base_url, client_id, client_secret, api_key, username, password, account]):
        return _text({"error": "Missing required env vars — check MVP-Access-API-Test/.env"})

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    basic_headers = {"Authorization": f"Basic {basic}", "api-key": api_key, "Content-Type": "application/json"}

    # Log in
    try:
        lr = requests.post(
            f"{base_url}/api/account/login",
            json={"userName": username, "password": password, "account": int(account)},
            headers=basic_headers, timeout=10,
        )
    except Exception as e:
        return _text({"error": f"Login failed: {e}", "base_url": base_url})
    if lr.status_code != 200:
        return _text({"error": f"Login returned {lr.status_code}", "body": lr.text[:300]})
    token = lr.json().get("token") or lr.json().get("Token")
    bearer_headers = {"Authorization": f"Bearer {token}", "api-key": api_key, "Content-Type": "application/json"}

    PERF = 2.0
    results = []
    for method, path, probe in _ALL_ENDPOINT_PROBES:
        if probe == "special_login":
            # Already probed above; record success explicitly.
            results.append({
                "method": method, "path": path, "probe": probe,
                "status": lr.status_code, "elapsed_s": round(lr.elapsed.total_seconds(), 3),
                "verdict": "healthy" if lr.status_code == 200 else "broken",
            })
            continue

        kwargs = {"headers": bearer_headers, "timeout": 30}
        if method == "POST":
            kwargs["json"] = {}
        elif method == "PUT":
            kwargs["json"] = {}

        try:
            r = requests.request(method, f"{base_url}{path}", **kwargs)
            elapsed = r.elapsed.total_seconds()
            status = r.status_code
        except requests.exceptions.Timeout:
            results.append({"method": method, "path": path, "probe": probe,
                            "status": None, "elapsed_s": None, "verdict": "timeout"})
            continue
        except Exception as e:
            results.append({"method": method, "path": path, "probe": probe,
                            "status": None, "elapsed_s": None,
                            "verdict": "exception", "error": str(e)[:200]})
            continue

        # Decide verdict based on probe type
        if probe == "list":
            verdict = "healthy" if status == 200 else f"unhealthy_{status}"
        elif probe == "get_by_id":
            verdict = "healthy" if status in (200, 400, 404) else f"unhealthy_{status}"
        elif probe == "post_empty":
            # Expect 400 for bad payload. 401/403 = endpoint blocked us (still reachable).
            # 200/201 means API silently accepted {} which is a validation bug.
            if status in (400, 401, 403, 422):
                verdict = "healthy"
            elif status in (200, 201):
                verdict = "validation_gap"  # accepted empty body — bad
            else:
                verdict = f"unhealthy_{status}"
        elif probe == "put_bogus":
            verdict = "healthy" if status in (200, 204, 400, 404, 422) else f"unhealthy_{status}"
        elif probe == "delete_bogus":
            verdict = "healthy" if status in (200, 204, 400, 404, 405, 500) else f"unhealthy_{status}"
        else:
            verdict = "unknown_probe"

        # Layer on a perf warning
        if verdict == "healthy" and elapsed > PERF:
            verdict = "slow"

        results.append({
            "method": method, "path": path, "probe": probe,
            "status": status, "elapsed_s": round(elapsed, 3),
            "verdict": verdict,
        })

    # Aggregate counts
    counts = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    return _text({
        "base_url": base_url,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "total_endpoints": len(results),
        "counts": counts,
        "slowest": sorted([r for r in results if r["elapsed_s"] is not None],
                          key=lambda x: -x["elapsed_s"])[:5],
        "unhealthy": [r for r in results if r["verdict"] not in ("healthy",)],
        "results": results,
    })


@tool(
    "list_known_bugs",
    "List all entries in integration-tests/known_bugs.py (xfail markers) with their reasons — useful for triage / bug-review meetings and for deciding which API bugs to prioritize.",
    {},
)
async def list_known_bugs_tool(_args):
    import re
    kb_path = os.path.join(API_TEST_PROJECT, "integration-tests", "known_bugs.py")
    if not os.path.isfile(kb_path):
        return _text({"error": "known_bugs.py not found"})
    with open(kb_path, "r", encoding="utf-8") as f:
        content = f.read()
    # Grab name = pytest.mark.xfail(...reason="...", strict=...) blocks
    pattern = re.compile(
        r'^([A-Z][A-Z0-9_]+)\s*=\s*pytest\.mark\.xfail\([^)]*?reason=\s*"([^"]+)"',
        re.MULTILINE | re.DOTALL,
    )
    entries = [{"name": m.group(1), "reason": m.group(2)} for m in pattern.finditer(content)]
    return _text({"count": len(entries), "bugs": entries})


@tool(
    "test_inventory",
    "Summarize the test suite: total tests, count per resource, count per category (positive / unauthorized / not_found / etc.). Useful for coverage reviews and status reports.",
    {},
)
async def test_inventory_tool(_args):
    import re
    tests_dir = os.path.join(API_TEST_PROJECT, "integration-tests")
    test_files = sorted(glob.glob(os.path.join(tests_dir, "test_*.py")))
    per_resource = {}
    per_category = {
        "positive": 0, "unauthorized": 0, "bad_input": 0,
        "not_found": 0, "update": 0, "delete": 0,
        "idempotent": 0, "search": 0, "other": 0,
    }
    total = 0
    for path in test_files:
        name = os.path.basename(path).replace("test_", "").replace(".py", "")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        test_funcs = re.findall(r'^\s*def (test_\w+)\s*\(', content, re.MULTILINE)
        per_resource[name] = len(test_funcs)
        total += len(test_funcs)
        for fn in test_funcs:
            f_low = fn.lower()
            if "unauthorized" in f_low:
                per_category["unauthorized"] += 1
            elif "not_found" in f_low:
                per_category["not_found"] += 1
            elif "missing" in f_low or "rejected" in f_low or "bad" in f_low:
                per_category["bad_input"] += 1
            elif "idempot" in f_low:
                per_category["idempotent"] += 1
            elif "search" in f_low:
                per_category["search"] += 1
            elif "update" in f_low:
                per_category["update"] += 1
            elif "delete" in f_low:
                per_category["delete"] += 1
            elif "positive" in f_low or "create" in f_low or "list" in f_low or "details" in f_low:
                per_category["positive"] += 1
            else:
                per_category["other"] += 1
    return _text({
        "total_tests": total,
        "resource_count": len(per_resource),
        "per_resource": dict(sorted(per_resource.items(), key=lambda x: -x[1])),
        "per_category": per_category,
    })


@tool(
    "compare_with_last_run",
    "Compare the MOST RECENT pytest run to the previous one. Flags new failures (regressions) and newly-passing tests (fixed). Reads pytest_report.json files from the reports folder.",
    {},
)
async def compare_with_last_run_tool(_args):
    reports = sorted(
        glob.glob(os.path.join(config.REPORTS_DIR, "pytest_report*.json")),
        key=os.path.getmtime, reverse=True,
    )
    if len(reports) < 2:
        return _text({
            "error": "need at least 2 pytest_report.json files; only found "
                     f"{len(reports)}. Run the suite twice first.",
            "available": [os.path.basename(p) for p in reports],
        })
    with open(reports[0]) as f: current = json.load(f)
    with open(reports[1]) as f: previous = json.load(f)

    def outcomes(report):
        return {t["nodeid"]: t.get("outcome", "?") for t in report.get("tests", [])}

    cur_map = outcomes(current)
    prev_map = outcomes(previous)
    all_ids = set(cur_map) | set(prev_map)
    regressions, fixed, new_tests, removed = [], [], [], []
    for tid in all_ids:
        cur = cur_map.get(tid)
        prev = prev_map.get(tid)
        if cur is None:
            removed.append(tid.split("::", 1)[-1])
        elif prev is None:
            new_tests.append(tid.split("::", 1)[-1])
        elif prev == "passed" and cur == "failed":
            regressions.append(tid.split("::", 1)[-1])
        elif prev == "failed" and cur == "passed":
            fixed.append(tid.split("::", 1)[-1])
    return _text({
        "current_report": os.path.basename(reports[0]),
        "previous_report": os.path.basename(reports[1]),
        "regressions_count": len(regressions),
        "regressions": regressions[:20],
        "fixed_count": len(fixed),
        "fixed": fixed[:20],
        "new_tests_count": len(new_tests),
        "removed_tests_count": len(removed),
    })


@tool(
    "draft_standup_update",
    "Produce a 5-bullet summary of the most recent test run suitable for a daily stand-up or weekly status email. Reads the latest pytest_report.json.",
    {},
)
async def draft_standup_update_tool(_args):
    reports = sorted(
        glob.glob(os.path.join(config.REPORTS_DIR, "pytest_report*.json")),
        key=os.path.getmtime, reverse=True,
    )
    if not reports:
        return _text({"error": "No pytest_report.json — run tests first."})
    with open(reports[0]) as f:
        report = json.load(f)
    s = report.get("summary", {})
    duration = report.get("duration", 0)
    failed_tests = [
        t["nodeid"].split("::", 1)[-1]
        for t in report.get("tests", [])
        if t.get("outcome") == "failed"
    ]
    bullets = [
        f"Total: {s.get('total', 0)} tests, {s.get('passed', 0)} passed, "
        f"{s.get('failed', 0)} failed, {s.get('xfailed', 0)} xfail (known bugs).",
        f"Duration: {duration:.0f}s",
        f"Source: {os.path.basename(reports[0])}",
    ]
    if failed_tests:
        bullets.append(f"Failures ({len(failed_tests)}): " + ", ".join(failed_tests[:5]))
    else:
        bullets.append("No real failures — suite is green.")
    bullets.append(f"Known-bug count: {s.get('xfailed', 0)} (see list_known_bugs tool).")
    return _text({"standup_bullets": bullets})


@tool(
    "recent_commits",
    "Show the last N git commits across one of the projects — useful for 'what changed this week' status updates. 'project' one of: api-test, e2e-full, e2e-easy, e2e-release, ai-agent. Default count=10.",
    {"project": str, "count": int},
)
async def recent_commits_tool(args):
    project_map = dict(_PROJECT_PATHS)
    project_map["ai-agent"] = os.path.dirname(os.path.abspath(__file__))
    root = project_map.get(args["project"])
    if not root or not os.path.isdir(root):
        return _text({"error": f"Unknown project: {args['project']}"})
    count = int(args.get("count") or 10)
    try:
        proc = subprocess.run(
            ["git", "log", f"-{count}", "--pretty=format:%h|%an|%ar|%s"],
            cwd=root, capture_output=True, text=True, timeout=10,
        )
        commits = []
        for line in (proc.stdout or "").splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({"sha": parts[0], "author": parts[1],
                                "when": parts[2], "message": parts[3]})
        return _text({"project": args["project"], "commits": commits})
    except Exception as e:
        return _text({"error": str(e)})


@tool(
    "check_api_health",
    "Quickly ping the API login endpoint (no heavy tests) to confirm the server is reachable and credentials work. Use as a pre-flight check before any test run.",
    {},
)
async def check_api_health_tool(_args):
    import base64
    basic = base64.b64encode(f"{os.getenv('CLIENT_ID')}:{os.getenv('CLIENT_SECRET')}".encode()).decode()
    try:
        resp = subprocess.run(
            ["python", "-c", (
                "import os, requests, base64; "
                f"b = base64.b64encode(f'{{os.getenv(\"CLIENT_ID\")}}:{{os.getenv(\"CLIENT_SECRET\")}}'.encode()).decode(); "
                f"r = requests.post('{os.getenv('BASE_URL')}/api/account/login', "
                "json={'userName': os.getenv('USER_ID'), 'password': os.getenv('PASSWORD'), "
                "'account': int(os.getenv('COMPANY_ID'))}, "
                "headers={'Authorization': f'Basic {b}', 'api-key': os.getenv('API_KEY'), "
                "'Content-Type': 'application/json'}, timeout=10); "
                "print(r.status_code, r.elapsed.total_seconds())"
            )],
            cwd=API_TEST_PROJECT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        out = (resp.stdout or "").strip()
        if not out:
            return _text({"healthy": False, "error": resp.stderr[-300:] if resp.stderr else "no output"})
        code, elapsed = out.split()
        return _text({
            "healthy": code == "200",
            "base_url": os.getenv("BASE_URL"),
            "status_code": int(code),
            "response_time_s": float(elapsed),
        })
    except Exception as e:
        return _text({"healthy": False, "error": str(e)})


@tool(
    "run_tests_by_pattern",
    "Run integration tests matching a pytest -k expression (e.g. 'unauthorized', 'person and create', 'not test_delete'). Much faster than running the full suite when you want to target specific tests. 'scope' is 'integration' or 'api-test-project' (defaults to integration).",
    {"pattern": str},
)
async def run_tests_by_pattern_tool(args):
    pattern = args["pattern"]
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    json_report = os.path.join(config.REPORTS_DIR, "pytest_pattern_report.json")
    cmd = [
        sys.executable, "-m", "pytest", config.INTEGRATION_TEST_DIR,
        "-k", pattern, "-v", "--tb=short",
        "--json-report", f"--json-report-file={json_report}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    summary = {"exit_code": proc.returncode, "pattern": pattern}
    if os.path.exists(json_report):
        with open(json_report) as f:
            report = json.load(f)
        s = report.get("summary", {})
        summary.update({
            "total": s.get("total", 0),
            "passed": s.get("passed", 0),
            "failed": s.get("failed", 0),
            "skipped": s.get("skipped", 0),
            "xfailed": s.get("xfailed", 0),
        })
        # Include failed test names
        summary["failures"] = [
            t["nodeid"].split("::", 1)[-1]
            for t in report.get("tests", [])
            if t.get("outcome") == "failed"
        ][:10]
    summary["stdout_tail"] = (proc.stdout or "")[-500:]
    return _text(summary)


@tool(
    "find_flaky_tests",
    "Run a pytest -k pattern N times in a row and report which tests passed sometimes and failed sometimes (flakes). Use when suspecting intermittent failures. Default N=5.",
    {"pattern": str, "runs": int},
)
async def find_flaky_tests_tool(args):
    pattern = args["pattern"]
    runs = int(args.get("runs") or 5)
    if runs < 2 or runs > 20:
        return _text({"error": "runs must be between 2 and 20"})
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    outcomes: dict = {}  # test_id -> list of outcomes
    for i in range(runs):
        json_report = os.path.join(config.REPORTS_DIR, f"flaky_{i}.json")
        cmd = [
            sys.executable, "-m", "pytest", config.INTEGRATION_TEST_DIR,
            "-k", pattern, "-q", "--json-report",
            f"--json-report-file={json_report}",
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if os.path.exists(json_report):
            with open(json_report) as f:
                report = json.load(f)
            for t in report.get("tests", []):
                outcomes.setdefault(t["nodeid"], []).append(t.get("outcome", "?"))
            os.remove(json_report)
    flaky, stable_pass, stable_fail = [], 0, 0
    for tid, outs in outcomes.items():
        passed = sum(1 for o in outs if o == "passed")
        failed = sum(1 for o in outs if o == "failed")
        if passed > 0 and failed > 0:
            flaky.append({"test": tid.split("::", 1)[-1], "pass": passed, "fail": failed,
                          "total": len(outs)})
        elif failed == 0:
            stable_pass += 1
        else:
            stable_fail += 1
    return _text({
        "pattern": pattern, "runs": runs,
        "stable_passing": stable_pass,
        "stable_failing": stable_fail,
        "flaky_count": len(flaky),
        "flaky_tests": sorted(flaky, key=lambda x: x["fail"], reverse=True),
    })


@tool(
    "git_diff",
    "Show uncommitted changes in a project — useful after the agent edits code so the user can review. 'project' one of: api-test, e2e-full, e2e-easy, e2e-release, ai-agent. Returns up to ~200 lines of diff.",
    {"project": str},
)
async def git_diff_tool(args):
    project_map = dict(_PROJECT_PATHS)
    project_map["ai-agent"] = os.path.dirname(os.path.abspath(__file__))
    root = project_map.get(args["project"])
    if not root or not os.path.isdir(root):
        return _text({"error": f"Unknown project: {args['project']}"})
    try:
        proc = subprocess.run(
            ["git", "diff", "--stat"], cwd=root,
            capture_output=True, text=True, timeout=10,
        )
        proc2 = subprocess.run(
            ["git", "diff"], cwd=root,
            capture_output=True, text=True, timeout=10,
        )
        stat = proc.stdout or "(no changes)"
        diff = (proc2.stdout or "")
        diff_preview = "\n".join(diff.splitlines()[:200])
        truncated = len(diff.splitlines()) > 200
        return _text({
            "project": args["project"], "root": root,
            "stat": stat, "diff": diff_preview, "truncated": truncated,
        })
    except Exception as e:
        return _text({"error": str(e)})


@tool(
    "git_commit_and_push",
    "Commit the agent's pending changes in a project and push. Requires a commit message from the user (or you can infer one from the changes). Never use without user's explicit request. 'project' one of: api-test, e2e-full, e2e-easy, e2e-release, ai-agent.",
    {"project": str, "message": str},
)
async def git_commit_and_push_tool(args):
    project_map = dict(_PROJECT_PATHS)
    project_map["ai-agent"] = os.path.dirname(os.path.abspath(__file__))
    root = project_map.get(args["project"])
    if not root or not os.path.isdir(root):
        return _text({"error": f"Unknown project: {args['project']}"})
    message = (args.get("message") or "").strip()
    if not message:
        return _text({"error": "commit message required"})
    try:
        r1 = subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, text=True, timeout=10)
        if r1.returncode != 0:
            return _text({"step": "add", "error": r1.stderr})
        r2 = subprocess.run(
            ["git", "commit", "-m", message], cwd=root,
            capture_output=True, text=True, timeout=10,
        )
        if "nothing to commit" in (r2.stdout + r2.stderr).lower():
            return _text({"committed": False, "reason": "no changes to commit"})
        if r2.returncode != 0:
            return _text({"step": "commit", "error": r2.stderr})
        r3 = subprocess.run(["git", "push"], cwd=root, capture_output=True, text=True, timeout=60)
        return _text({
            "committed": True,
            "pushed": r3.returncode == 0,
            "commit_output": r2.stdout[-300:],
            "push_output": (r3.stdout + r3.stderr)[-300:],
        })
    except Exception as e:
        return _text({"error": str(e)})


@tool(
    "tail_nightly_log",
    "Show the last N lines of today's (or yesterday's) nightly log file so the user can see what the scheduled run did. Default N=80.",
    {"day": str, "lines": int},
)
async def tail_nightly_log_tool(args):
    from datetime import datetime
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    day = (args.get("day") or "today").lower()
    if day == "today":
        stamp = datetime.now().strftime("%Y-%m-%d")
    elif day == "yesterday":
        from datetime import timedelta
        stamp = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        stamp = day
    lines = int(args.get("lines") or 80)
    path = os.path.join(log_dir, f"nightly_{stamp}.log")
    if not os.path.isfile(path):
        existing = sorted(glob.glob(os.path.join(log_dir, "nightly_*.log")))[-3:]
        return _text({
            "error": f"No log for {stamp}",
            "available_logs": [os.path.basename(p) for p in existing],
        })
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    tail_lines = content.splitlines()[-lines:]
    return _text({"log_file": path, "total_lines": len(content.splitlines()),
                  "tail": "\n".join(tail_lines)})


@tool(
    "clean_reports_folder",
    "Delete all existing PDF / JSON / CSV report artifacts in the API-Test reports/ folder before a fresh run. Use when the user asks for a clean report or fresh output.",
    {},
)
async def clean_reports_folder_tool(_args):
    import glob
    deleted = []
    for pattern in ("*.pdf", "*.csv", "*.json", "*.xlsx"):
        for f in glob.glob(os.path.join(config.REPORTS_DIR, pattern)):
            try:
                os.remove(f)
                deleted.append(os.path.basename(f))
            except Exception as e:
                logger.warning(f"Failed to delete {f}: {e}")
    # Reset the in-memory report_paths so subsequent generate_pdf_report starts clean
    STATE["report_paths"] = []
    return _text({"deleted": deleted, "deleted_count": len(deleted)})


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
    # Pre-flight
    check_api_health_tool,
    check_all_endpoints_health_tool,
    # Test execution
    run_load_tests_tool, run_api_tests_tool, run_integration_tests_tool,
    run_tests_by_pattern_tool, find_flaky_tests_tool, run_e2e_tests_tool,
    # Code review + edits
    list_project_files_tool, read_file_tool, write_file_tool, edit_file_tool,
    # Source control
    git_diff_tool, git_commit_and_push_tool, recent_commits_tool,
    # Reporting + telemetry
    tail_nightly_log_tool, clean_reports_folder_tool, generate_pdf_report_tool,
    send_email_report_tool,
    # Management / triage
    list_known_bugs_tool, test_inventory_tool,
    compare_with_last_run_tool, draft_standup_update_tool,
]

TOOL_NAMES = [
    "check_api_health", "check_all_endpoints_health",
    "run_load_tests", "run_api_tests", "run_integration_tests",
    "run_tests_by_pattern", "find_flaky_tests", "run_e2e_tests",
    "list_project_files", "read_file", "write_file", "edit_file",
    "git_diff", "git_commit_and_push", "recent_commits",
    "tail_nightly_log", "clean_reports_folder", "generate_pdf_report",
    "send_email_report",
    "list_known_bugs", "test_inventory",
    "compare_with_last_run", "draft_standup_update",
]
