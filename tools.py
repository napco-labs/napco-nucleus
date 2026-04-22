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
# Default to the parent folder of THIS project so a sibling layout works out
# of the box on any machine. Override with MVP_PROJECTS_ROOT if your projects
# live somewhere else.
_DEFAULT_PROJECTS_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
PROJECTS_ROOT = os.getenv("MVP_PROJECTS_ROOT", _DEFAULT_PROJECTS_ROOT)
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
import history         # noqa: E402 — per-run snapshot store + regression/flaky analysis
import coverage as _coverage  # noqa: E402 — swagger-vs-tests coverage
import bug_reporter   # noqa: E402 — markdown bug-draft generator
import patch_generator # noqa: E402 — self-healing unified-diff patches
import teams_notifier # noqa: E402 — optional digest to Microsoft Teams webhook

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


def _load_test_description():
    tiers = "/".join(_format_users(t["users"]) for t in config.LOAD_TEST_TIERS)
    rt = config.LOCUST_RUN_TIME
    total_sec = _parse_run_time_seconds(rt) * len(config.LOAD_TEST_TIERS)
    total_min = max(1, round(total_sec / 60))
    return (
        f"Run Locust load tests across all tiers ({tiers} users, {rt} each). "
        f"Returns per-tier summary. Takes ~{total_min} min total. "
        f"Call AT MOST ONCE per run."
    )


@tool(
    "run_load_tests",
    _load_test_description(),
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
        "duration_s": 0,
        "environment": {},
        "failures": [],           # rich shape — feeds the PDF failure cards
        "failure_samples": [],    # legacy shape — kept for back-compat
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

        # Environment block — pulled from .env (Playwright config falls back
        # to staging if PORTAL_URL isn't set, so we do the same here).
        result["environment"] = {
            "base_url": (
                os.getenv("PORTAL_URL")
                or os.getenv("BASE_URL")
                or "https://staging.mvpaccess.online"
            ),
            "browser": "Chromium (Desktop Chrome)",
            "viewport": "1920x1080",
            "project": (report.get("config") or {}).get("name") or "chromium",
        }

        # Dedupe failures by (file, line, title) so a retried-and-still-failed
        # test surfaces as ONE card with a `max_retry` chip rather than
        # N separate cards. We also pick up the `attachments` block so the
        # PDF can embed the latest screenshot + trace per failing test.
        failures_by_key: dict = {}

        def walk(suites):
            for s in suites or []:
                for spec in s.get("specs", []) or []:
                    spec_file = spec.get("file") or ""
                    spec_line = spec.get("line")
                    spec_title = spec.get("title", "")
                    for test in spec.get("tests", []) or []:
                        for res in test.get("results", []) or []:
                            status = res.get("status")
                            if status not in ("failed", "timedOut"):
                                continue
                            err_msg = (res.get("error") or {}).get("message") or ""
                            attachments = res.get("attachments") or []
                            shot = next(
                                (a.get("path") for a in attachments
                                 if a.get("name") == "screenshot" and a.get("path")),
                                None,
                            )
                            trace = next(
                                (a.get("path") for a in attachments
                                 if a.get("name") == "trace" and a.get("path")),
                                None,
                            )
                            key = (spec_file, spec_line, spec_title)
                            existing = failures_by_key.get(key)
                            retry = int(res.get("retry") or 0)
                            duration_ms = int(res.get("duration") or 0)
                            # Build a local repro command the developer can paste
                            repro = (
                                f"cd {os.path.basename(project_dir)} && "
                                f"npx playwright test {spec_file}"
                                + (f":{spec_line}" if spec_line else "")
                                + " --headed --project=chromium"
                            )
                            if existing is None:
                                failures_by_key[key] = {
                                    "title": spec_title,
                                    "file": spec_file,
                                    "line": spec_line,
                                    "status": status,
                                    "max_retry": retry,
                                    "duration_ms": duration_ms,
                                    "error": err_msg,
                                    "screenshot_path": shot,
                                    "trace_path": trace,
                                    "repro_command": repro,
                                }
                            else:
                                existing["max_retry"] = max(existing["max_retry"], retry)
                                # Prefer retry-run artifacts (they usually have the trace)
                                if retry > 0:
                                    if shot:  existing["screenshot_path"] = shot
                                    if trace: existing["trace_path"] = trace
                                if err_msg and not existing["error"]:
                                    existing["error"] = err_msg
                yield from walk(s.get("suites"))
        list(walk(report.get("suites", [])))

        result["failures"] = list(failures_by_key.values())
        # Back-compat legacy field — top 5 samples for any caller that still
        # reads `failure_samples` (e.g. the old PDF renderer).
        result["failure_samples"] = [
            {"name": f["title"], "message": (f.get("error") or "")[:300]}
            for f in result["failures"][:5]
        ]

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
    # Trim the returned summary so the agent's context doesn't balloon with
    # screenshot paths on every call. The full rich dict stays in STATE for
    # the PDF renderer.
    summary = {k: v for k, v in result.items() if k != "failures"}
    summary["failure_samples"] = result["failure_samples"]
    summary["failure_count"] = len(result["failures"])
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


# ─── RCA classifier (analyze_test_failures) ─────────────────────────────
#
# Cascading heuristics for failure classification. Order matters — first
# match wins; patterns are matched against a lower-cased error string.
# Each entry: (regex, class, owner_hint, rationale).
#
# Classes:
#   env       — network / DNS / TLS / server-down (the test never got a fair
#               chance, so don't blame the backend code or the test code)
#   data      — auth / fixture / pre-condition setup failed
#   test_bug  — selector breakage, import/syntax error in the test itself
#   real_bug  — 5xx, assertion mismatch on a healthy connection
#   flaky     — historically intermittent; cross-referenced from history.py
#   known_bug — already tracked in integration-tests/known_bugs.py
_FAILURE_HEURISTICS: list[tuple[str, str, str, str]] = [
    (r"readtimeout|read timed out|timeouterror: timed out|connectionrefused|"
     r"econnrefused|max retries exceeded|connection aborted|connection reset|"
     r"name or service not known|no route to host|network is unreachable|"
     r"no such host|getaddrinfo failed|nameresolutionerror",
     "env", "infra/backend",
     "Network/connection failure — target host unreachable or timing out"),
    (r"ssl: certificate|certificate verify failed|sslerror",
     "env", "infra",
     "TLS / certificate problem — likely env config, not a test bug"),
    (r"login failed|invalid credentials|authentication failed|"
     r"missing client_id|missing api[- ]?key",
     "data", "qa-data-setup",
     "Auth/credential setup failed before the test could run"),
    (r"locator\.[a-z]+: timeout|element\([^)]*\) not found|"
     r"strict mode violation|no element matches selector|"
     r"page\.goto: timeout|expected to be visible.*timeout|"
     r"test timeout of \d+ms exceeded",
     "test_bug", "qa-tests",
     "Playwright selector/locator issue — fragile test code"),
    (r"importerror|modulenotfounderror|syntaxerror|indentationerror",
     "test_bug", "qa-tests",
     "Python import/syntax error in the test code"),
    (r"\b50[023]\b.*server error|"
     r"assertionerror.*expected\s+(?:200|201|204).*\b500\b|"
     r"\binternalservererror\b|500 internal server error",
     "real_bug", "backend",
     "Server returned 5xx — backend defect"),
    (r"assertionerror|expected.*to (?:equal|be|have)",
     "real_bug", "backend",
     "Assertion mismatch — investigate as backend behaviour change"),
]


def _classify_failure(test_name: str, error_text: str,
                      known_patterns, flaky_lookup: dict) -> dict:
    """Cascade: known → flaky → heuristics → default real_bug."""
    import re as _re
    text = error_text or ""
    haystack = f"{test_name} {text}"

    if known_patterns and any(p.search(haystack) for p in known_patterns):
        return {"class": "known_bug", "owner": "tracked",
                "rationale": "Matches an entry in integration-tests/known_bugs.py"}

    if test_name and test_name in flaky_lookup:
        pct = flaky_lookup[test_name]
        return {"class": "flaky", "owner": "qa-investigation",
                "rationale": f"Stability {pct}% over last 10 runs"}

    low = text.lower()
    for pattern, klass, owner, why in _FAILURE_HEURISTICS:
        if _re.search(pattern, low):
            return {"class": klass, "owner": owner, "rationale": why}

    return {"class": "real_bug", "owner": "backend",
            "rationale": "Uncategorized failure — review manually"}


def _load_pytest_failures() -> list[dict]:
    path = os.path.join(config.REPORTS_DIR, "pytest_report.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for t in data.get("tests", []):
        outcome = t.get("outcome")
        if outcome not in ("failed", "error"):
            continue
        nodeid = t.get("nodeid", "?")
        msg = ""
        for stage in ("call", "setup", "teardown"):
            stage_data = t.get(stage) or {}
            crash = stage_data.get("crash") or {}
            if crash.get("message"):
                msg = crash["message"]
                break
            if not msg and stage_data.get("longrepr"):
                msg = stage_data["longrepr"]
        out.append({
            "test": nodeid.split("::", 1)[-1],
            "error": (msg or "")[:800],
            "source": "pytest",
            "outcome": outcome,
        })
    return out


def _load_newman_failures() -> list[dict]:
    path = os.path.join(config.REPORTS_DIR, "newman_report.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for fail in (data.get("run", {}).get("failures") or []):
        err = fail.get("error") or {}
        src = fail.get("source") or {}
        parent = fail.get("parent") or {}
        out.append({
            "test": f"{parent.get('name', '')} — {src.get('name', '') or err.get('test', '')}".strip(" —"),
            "error": (err.get("message") or err.get("name") or "")[:800],
            "source": "newman",
            "outcome": "failed",
        })
    return out


def _load_playwright_failures() -> list[dict]:
    out = []
    for suite, root in E2E_PROJECTS.items():
        for candidate in (
            os.path.join(root, "reports", "results.json"),
            os.path.join(root, "test-results", "results.json"),
        ):
            if not os.path.isfile(candidate):
                continue
            try:
                with open(candidate) as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue

            def _walk(suites):
                for s in suites or []:
                    for spec in s.get("specs", []) or []:
                        for test in spec.get("tests", []) or []:
                            for res in test.get("results", []) or []:
                                if res.get("status") in ("failed", "timedOut"):
                                    err = (res.get("error") or {}).get("message") or ""
                                    out.append({
                                        "test": f"[{suite}] {spec.get('title', '')}",
                                        "error": err[:800],
                                        "source": f"playwright-{suite}",
                                        "outcome": res.get("status"),
                                    })
                    yield from _walk(s.get("suites"))
            list(_walk(data.get("suites", [])))
            break
    return out


@tool(
    "analyze_test_failures",
    "Read the latest test artifacts (pytest_report.json, newman_report.json, "
    "Playwright results.json across the 3 E2E projects) and classify each "
    "failure as real_bug | flaky | env | data | test_bug | known_bug. "
    "Returns counts per class, top collapsed root causes, action "
    "recommendations, and the per-failure list with rationale + owner hint. "
    "Pure read; no test execution; runs in seconds. Use after a run (or on "
    "artifacts copied from CI) to know what to actually act on. Optional "
    "max_failures_per_class caps the per-class detail list (default 5).",
    {"max_failures_per_class": int},
)
async def analyze_test_failures_tool(args):
    cap = int((args or {}).get("max_failures_per_class") or 5)

    known_patterns = bug_reporter._known_bug_patterns()
    flaky_lookup = {}
    try:
        for f in history.compute_flaky_tests():
            flaky_lookup[f["name"]] = f["stability_pct"]
    except Exception as e:
        logger.warning(f"compute_flaky_tests failed: {e}")

    failures = (
        _load_pytest_failures()
        + _load_newman_failures()
        + _load_playwright_failures()
    )

    if not failures:
        return _text({
            "scope": "latest_artifacts",
            "total_failures": 0,
            "message": "No failures found in the latest reports — either "
                       "the suite is green or no run artifacts exist yet.",
        })

    classified = []
    for f in failures:
        verdict = _classify_failure(
            f["test"], f["error"], known_patterns, flaky_lookup,
        )
        classified.append({**f, **verdict})

    counts: dict = {}
    for f in classified:
        counts[f["class"]] = counts.get(f["class"], 0) + 1

    cause_groups: dict = {}
    for f in classified:
        key = (f["class"], f["rationale"])
        g = cause_groups.setdefault(key, {
            "class": f["class"], "rationale": f["rationale"],
            "owner": f["owner"], "count": 0,
            "sample_test": f["test"],
            "sample_error": f["error"][:200],
        })
        g["count"] += 1
    top_causes = sorted(cause_groups.values(), key=lambda x: -x["count"])[:5]

    actions = []
    if counts.get("env", 0) >= 5:
        actions.append(
            f"Likely env outage: {counts['env']} env-class failures. "
            "Run check_api_health before re-running the suite."
        )
    if counts.get("real_bug", 0) > 0:
        actions.append(
            f"{counts['real_bug']} real bug(s) — see top_root_causes for "
            "clusters; owner: backend."
        )
    if counts.get("flaky", 0) > 0:
        actions.append(
            f"{counts['flaky']} flaky test(s) — confirm with find_flaky_tests "
            "before filing."
        )
    if counts.get("test_bug", 0) > 0:
        actions.append(
            f"{counts['test_bug']} test-code issue(s) — owner: qa-tests."
        )
    if counts.get("data", 0) > 0:
        actions.append(
            f"{counts['data']} data/setup failure(s) — likely auth/fixture; "
            "owner: qa-data-setup."
        )
    if counts.get("known_bug", 0) > 0:
        actions.append(
            f"{counts['known_bug']} known-bug hit(s) — already tracked, no "
            "new action needed."
        )
    if not actions:
        actions.append("Review the failure list manually — heuristic rules "
                       "did not fire confidently.")

    by_class: dict = {}
    for f in classified:
        by_class.setdefault(f["class"], []).append({
            "test": f["test"],
            "source": f["source"],
            "owner": f["owner"],
            "rationale": f["rationale"],
            "error": f["error"][:200],
        })
    for k in by_class:
        by_class[k] = by_class[k][:cap]

    return _text({
        "scope": "latest_artifacts",
        "sources_seen": sorted({f["source"] for f in failures}),
        "total_failures": len(classified),
        "by_class": dict(sorted(counts.items(), key=lambda x: -x[1])),
        "top_root_causes": top_causes,
        "actions": actions,
        "failures_by_class": by_class,
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
    "Generate the consolidated PDF report from collected results. Pass a 2-3 "
    "paragraph executive summary (plain text, blank line between paragraphs) "
    "as `summary` — it renders right after the title page so developers see "
    "the headline findings before drilling into details. Returns the PDF path.",
    {"summary": str},
)
async def generate_pdf_report_tool(args):
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    timestamp = STATE["started_at"].strftime("%Y%m%d_%H%M%S")
    path = os.path.join(config.REPORTS_DIR, f"Test_Report_{timestamp}.pdf")

    # Pass None (not a SKIPPED placeholder) for tests that weren't run, so the
    # PDF generator can omit those sections entirely.
    summary = (args or {}).get("summary") if isinstance(args, dict) else None

    load_list = STATE["load"] or None
    api_result = STATE["api"]
    integ_result = STATE["integration"]
    e2e_result = STATE["e2e"]

    # Snapshot first so it includes today's data, then compare against the
    # previous snapshot (strictly older than the one we just wrote) to get
    # regressions. Flaky tests scan recent history including today.
    snap_path = history.save_snapshot(
        load_list, api_result, integ_result, e2e_result, STATE["started_at"]
    )
    with open(snap_path, encoding="utf-8") as f:
        current_snap = json.load(f)
    prev_snap = history.load_previous_snapshot(before_path=snap_path)
    regressions = history.compute_regressions(current_snap, prev_snap)
    flaky = history.compute_flaky_tests()
    coverage_report = _coverage.build_coverage_report()

    _generate_pdf(
        load_results_list=load_list,
        api_results=api_result,
        integration_results=integ_result,
        e2e_results=e2e_result,
        output_path=path,
        run_date=STATE["started_at"],
        summary=summary,
        regressions=regressions if prev_snap else None,
        flaky_tests=flaky,
        coverage=coverage_report,
    )
    STATE["report_paths"].append(path)

    # Drop any failures into a paste-ready markdown triage doc and attach it
    # alongside the PDF when we email.
    drafts_path = bug_reporter.write_bug_drafts(
        load_list, api_result, integ_result, e2e_result, STATE["started_at"]
    )
    if drafts_path:
        STATE["report_paths"].append(drafts_path)

    # Self-healing: generate git-applicable patches for fixable failures
    # (validation format errors, etc.) and attach them too.
    failures = list(bug_reporter.iter_failures(
        load_list, api_result, integ_result, e2e_result
    ))
    patches = patch_generator.generate_patches(failures)
    patch_path = patch_generator.write_patch_file(patches, STATE["started_at"])
    if patch_path:
        STATE["report_paths"].append(patch_path)

    return _text({
        "pdf_path": path,
        "exists": os.path.exists(path),
        "bug_drafts": drafts_path,
        "test_patches": patch_path,
        "patch_count": len(patches),
        "regressions": len(regressions) if regressions else 0,
        "flaky_tests": len(flaky),
        "coverage_pct": (coverage_report or {}).get("coverage_pct"),
    })


@tool(
    "send_teams_digest",
    "Post a short test-run digest to the TEAMS_WEBHOOK_URL env var (Microsoft Teams incoming webhook). Renders as a MessageCard with pass/fail counts, worst load tier, and regression count. Silent no-op if TEAMS_WEBHOOK_URL isn't set.",
    {},
)
async def send_teams_digest_tool(_args):
    pdf_path = STATE["report_paths"][0] if STATE["report_paths"] else None
    snap_paths = sorted(glob.glob(os.path.join(
        config.REPORTS_DIR, "history", "*.json")))
    prev = history.load_previous_snapshot(before_path=snap_paths[-1]) if snap_paths else None
    current = None
    if snap_paths:
        try:
            with open(snap_paths[-1], encoding="utf-8") as f:
                current = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    regressions = history.compute_regressions(current, prev) if current else []
    flaky = history.compute_flaky_tests()

    res = teams_notifier.post_digest(
        load_results_list=STATE["load"] or None,
        api_results=STATE["api"],
        integration_results=STATE["integration"],
        e2e_results=STATE["e2e"],
        regressions=regressions,
        flaky_tests=flaky,
        pdf_path=pdf_path,
        run_date=STATE["started_at"],
    )
    return _text(res)


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


# ---------------------------------------------------------------------------
# E2E Script Generation — Plan / Generate / Verify tools
# ---------------------------------------------------------------------------

@tool(
    "explore_ui",
    "Navigate to a page in the MVP Access app and return its accessibility snapshot "
    "(roles, names, states). Use this BEFORE writing any E2E test so you base selectors "
    "on real DOM, not guesses. 'suite' is full|easy|release (determines baseURL). "
    "'path' is the URL path e.g. '/Default.aspx'. If 'login_first' is true (default), "
    "the agent logs in before navigating.",
    {"suite": str, "path": str, "login_first": bool},
)
async def explore_ui_tool(args):
    suite = args.get("suite", "full")
    project_dir = E2E_PROJECTS.get(suite)
    if not project_dir or not os.path.isdir(project_dir):
        return _text({"error": f"Unknown E2E suite: {suite}"})

    url_path = args.get("path", "/")
    login_first = args.get("login_first", True)

    # Build a tiny Node script that launches Playwright, optionally logs in,
    # navigates to the target page, and dumps the accessibility tree.
    script = """
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const baseURL = process.env.BASE_URL || 'https://staging.mvpaccess.online';
"""
    if login_first:
        script += """
  // Log in first
  await page.goto(baseURL + '/Login.aspx');
  await page.locator('#txtAccount').fill(process.env.COMPANY_ID || '');
  await page.locator('#txtUserName').fill(process.env.USER_ID || '');
  await page.locator('#txtPassword').fill(process.env.PASSWORD || '');
  await page.evaluate(() => {
    const btn = document.getElementById('btnLogin');
    if (btn) btn.click();
  });
  await page.waitForURL(url => !url.toString().includes('Login.aspx'), { timeout: 15000 }).catch(() => {});
  await page.waitForLoadState('networkidle').catch(() => {});
"""
    script += f"""
  // Navigate to target
  await page.goto(baseURL + '{url_path}');
  await page.waitForLoadState('networkidle').catch(() => {{}});
  // Dump accessibility snapshot
  const snapshot = await page.accessibility.snapshot();
  console.log(JSON.stringify(snapshot, null, 2));
  await browser.close();
}})();
"""
    try:
        proc = subprocess.run(
            ["node", "-e", script],
            cwd=project_dir,
            capture_output=True, text=True,
            timeout=60, shell=True,
            env={**os.environ, "NODE_PATH": os.path.join(project_dir, "node_modules")},
        )
        stdout = (proc.stdout or "").strip()
        if proc.returncode != 0:
            return _text({
                "error": "Playwright exploration failed",
                "stderr": (proc.stderr or "")[-500:],
                "stdout": stdout[-500:],
            })
        try:
            tree = json.loads(stdout)
        except json.JSONDecodeError:
            tree = None
        return _text({
            "suite": suite,
            "path": url_path,
            "logged_in": login_first,
            "accessibility_tree": tree,
            "raw_length": len(stdout),
        })
    except subprocess.TimeoutExpired:
        return _text({"error": "Timed out exploring the UI (60s limit)"})
    except Exception as e:
        return _text({"error": str(e)})


@tool(
    "run_single_e2e_test",
    "Run a SINGLE Playwright spec file with tracing ON and return structured results. "
    "Use this to verify a newly-written test passes for the right reasons. "
    "'suite' is full|easy|release. 'spec_file' is relative to tests/ "
    "(e.g. '04-departments.spec.ts'). Returns pass/fail, failure messages, and trace path.",
    {"suite": str, "spec_file": str},
)
async def run_single_e2e_test_tool(args):
    suite = args.get("suite", "full")
    project_dir = E2E_PROJECTS.get(suite)
    if not project_dir or not os.path.isdir(project_dir):
        return _text({"error": f"Unknown E2E suite: {suite}"})

    spec = args.get("spec_file", "")
    spec_path = os.path.join(project_dir, "tests", spec)
    if not os.path.isfile(spec_path):
        return _text({"error": f"Spec not found: tests/{spec}"})

    trace_dir = os.path.join(project_dir, "test-results")
    cmd = [
        "npx", "playwright", "test",
        f"tests/{spec}",
        "--project=chromium",
        "--reporter=json",
        "--trace", "on",
        "--retries", "0",  # no retries — we want the raw result
    ]

    result = {
        "suite": suite, "spec_file": spec, "status": "FAILED",
        "total": 0, "passed": 0, "failed": 0,
        "duration_s": 0, "failures": [], "trace_dir": trace_dir,
    }

    try:
        proc = subprocess.run(
            cmd, cwd=project_dir, capture_output=True, text=True,
            timeout=120, shell=True,
        )
        stdout = proc.stdout or ""
        try:
            report = json.loads(stdout)
        except json.JSONDecodeError:
            idx = stdout.find("{")
            report = json.loads(stdout[idx:]) if idx >= 0 else {}

        stats = report.get("stats", {})
        result["total"] = stats.get("expected", 0) + stats.get("unexpected", 0) + stats.get("skipped", 0)
        result["passed"] = stats.get("expected", 0)
        result["failed"] = stats.get("unexpected", 0)
        result["duration_s"] = round(stats.get("duration", 0) / 1000.0, 1)

        # Extract failure messages
        def walk(suites):
            for s in suites or []:
                for sp in s.get("specs", []):
                    for t in sp.get("tests", []):
                        for r in t.get("results", []):
                            if r.get("status") in ("failed", "timedOut"):
                                err = (r.get("error") or {}).get("message", "")
                                result["failures"].append({
                                    "test": sp.get("title", ""),
                                    "error": err[:500],
                                    "status": r.get("status"),
                                })
                yield from walk(s.get("suites"))
        list(walk(report.get("suites", [])))

        if result["total"] > 0 and result["failed"] == 0:
            result["status"] = "PASSED"
        elif result["failed"] > 0:
            result["status"] = "PARTIAL"

        # Find trace zip files
        traces = glob.glob(os.path.join(trace_dir, "**", "trace.zip"), recursive=True)
        result["trace_files"] = [os.path.relpath(t, project_dir).replace("\\", "/") for t in traces[-3:]]

    except subprocess.TimeoutExpired:
        result["status"] = "TIMEOUT"
    except Exception as e:
        logger.exception("run_single_e2e_test error")
        result["error"] = str(e)

    return _text(result)


ALL_TOOLS = [
    # Pre-flight
    check_api_health_tool,
    check_all_endpoints_health_tool,
    # Test execution
    run_load_tests_tool, run_api_tests_tool, run_integration_tests_tool,
    run_tests_by_pattern_tool, find_flaky_tests_tool, run_e2e_tests_tool,
    # E2E script generation (Plan / Generate / Verify)
    explore_ui_tool, run_single_e2e_test_tool,
    # Code review + edits
    list_project_files_tool, read_file_tool, write_file_tool, edit_file_tool,
    # Source control
    git_diff_tool, git_commit_and_push_tool, recent_commits_tool,
    # Reporting + telemetry
    tail_nightly_log_tool, clean_reports_folder_tool, generate_pdf_report_tool,
    send_email_report_tool, send_teams_digest_tool,
    # Management / triage
    list_known_bugs_tool, test_inventory_tool,
    compare_with_last_run_tool, analyze_test_failures_tool,
    draft_standup_update_tool,
]

TOOL_NAMES = [
    "check_api_health", "check_all_endpoints_health",
    "run_load_tests", "run_api_tests", "run_integration_tests",
    "run_tests_by_pattern", "find_flaky_tests", "run_e2e_tests",
    "explore_ui", "run_single_e2e_test",
    "list_project_files", "read_file", "write_file", "edit_file",
    "git_diff", "git_commit_and_push", "recent_commits",
    "tail_nightly_log", "clean_reports_folder", "generate_pdf_report",
    "send_email_report", "send_teams_digest",
    "list_known_bugs", "test_inventory",
    "compare_with_last_run", "analyze_test_failures", "draft_standup_update",
]
