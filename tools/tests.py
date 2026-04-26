"""
NAPCO Nucleus — Test Automation tools.

Tools the agent calls to execute the four MVP-Access test suites
(API Functional / Integration / Load via the MVP-Access-API-Test
sibling, and E2E via the three Playwright sibling projects), plus
the lightweight pre-flight + targeted-run helpers.

Tools:
    run_load_tests              Locust multi-tier
    run_api_tests               Newman/Postman collection
    run_integration_tests       pytest suite
    run_e2e_tests               Playwright (suite=full|easy|release)
    run_single_e2e_test         One-spec run with tracing
    run_tests_by_pattern        pytest -k filter
    find_flaky_tests            N repeats, flag oscillation
    check_api_health            ping /api/account/login
    check_all_endpoints_health  78-endpoint non-destructive probe
"""
from __future__ import annotations

import glob
import json
import logging
import os
import subprocess
import sys

from claude_agent_sdk import tool

from tools._shared import (
    E2E_PROJECTS,
    API_TEST_PROJECT,
    STATE,
    _text,
    _summarize_load,
    _summarize_api,
    _summarize_integration,
    _format_users,
    _parse_run_time_seconds,
    config,
    run_load_tests_multi,
    run_api_tests as _run_api_tests,
    run_integration_tests as _run_integration_tests,
)

logger = logging.getLogger(__name__)


# ─── run_load_tests ────────────────────────────────────────────────────
def _load_test_description():
    # Sibling MVP-Access-API-Test/agent may not be on sys.path (e.g. on a
    # CI runner that checks out only this repo for the Requirement
    # Management workflow). Fall back to a generic description rather
    # than crashing at module-import time.
    if config is None:
        return (
            "Run Locust load tests across all tiers. Requires the sibling "
            "MVP-Access-API-Test project to be available; will fail at call "
            "time if not. Call AT MOST ONCE per run."
        )
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


# ─── run_api_tests ─────────────────────────────────────────────────────
@tool(
    "run_api_tests",
    "Run the Postman/Newman API test collection. Returns pass/fail counts.",
    {},
)
async def run_api_tests_tool(_args):
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    result = _run_api_tests()
    STATE["api"] = result
    return _text(_summarize_api(result))


# ─── run_integration_tests ─────────────────────────────────────────────
@tool(
    "run_integration_tests",
    "Run pytest integration tests. Returns pass/fail counts and failure messages.",
    {},
)
async def run_integration_tests_tool(_args):
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    result = _run_integration_tests()
    STATE["integration"] = result
    return _text(_summarize_integration(result))


# ─── run_e2e_tests ─────────────────────────────────────────────────────
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

    cmd = ["npx", "playwright", "test", "--reporter=json", "--headed"]
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


# ─── run_single_e2e_test ──────────────────────────────────────────────
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
        "--reporter=json",
        "--trace", "on",
        "--retries", "0",
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

        traces = glob.glob(os.path.join(trace_dir, "**", "trace.zip"), recursive=True)
        result["trace_files"] = [os.path.relpath(t, project_dir).replace("\\", "/") for t in traces[-3:]]

    except subprocess.TimeoutExpired:
        result["status"] = "TIMEOUT"
    except Exception as e:
        logger.exception("run_single_e2e_test error")
        result["error"] = str(e)

    return _text(result)


# ─── run_tests_by_pattern ─────────────────────────────────────────────
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
        summary["failures"] = [
            t["nodeid"].split("::", 1)[-1]
            for t in report.get("tests", [])
            if t.get("outcome") == "failed"
        ][:10]
    summary["stdout_tail"] = (proc.stdout or "")[-500:]
    return _text(summary)


# ─── find_flaky_tests ─────────────────────────────────────────────────
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
    outcomes: dict = {}
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


# ─── check_api_health ─────────────────────────────────────────────────
@tool(
    "check_api_health",
    "Quickly ping the API login endpoint (no heavy tests) to confirm the server is reachable and credentials work. Use as a pre-flight check before any test run.",
    {},
)
async def check_api_health_tool(_args):
    import base64
    base64.b64encode(f"{os.getenv('CLIENT_ID')}:{os.getenv('CLIENT_SECRET')}".encode()).decode()
    try:
        resp = subprocess.run(
            ["python", "-c", (
                "import os, requests, base64; "
                "b = base64.b64encode(f'{os.getenv(\"CLIENT_ID\")}:{os.getenv(\"CLIENT_SECRET\")}'.encode()).decode(); "
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


# ─── check_all_endpoints_health ───────────────────────────────────────
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

        if probe == "list":
            verdict = "healthy" if status == 200 else f"unhealthy_{status}"
        elif probe == "get_by_id":
            verdict = "healthy" if status in (200, 400, 404) else f"unhealthy_{status}"
        elif probe == "post_empty":
            if status in (400, 401, 403, 422):
                verdict = "healthy"
            elif status in (200, 201):
                verdict = "validation_gap"
            else:
                verdict = f"unhealthy_{status}"
        elif probe == "put_bogus":
            verdict = "healthy" if status in (200, 204, 400, 404, 422) else f"unhealthy_{status}"
        elif probe == "delete_bogus":
            verdict = "healthy" if status in (200, 204, 400, 404, 405, 500) else f"unhealthy_{status}"
        else:
            verdict = "unknown_probe"

        if verdict == "healthy" and elapsed > PERF:
            verdict = "slow"

        results.append({
            "method": method, "path": path, "probe": probe,
            "status": status, "elapsed_s": round(elapsed, 3),
            "verdict": verdict,
        })

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


TOOLS = [
    run_load_tests_tool,
    run_api_tests_tool,
    run_integration_tests_tool,
    run_e2e_tests_tool,
    run_single_e2e_test_tool,
    run_tests_by_pattern_tool,
    find_flaky_tests_tool,
    check_api_health_tool,
    check_all_endpoints_health_tool,
]

TOOL_NAMES = [
    "run_load_tests",
    "run_api_tests",
    "run_integration_tests",
    "run_e2e_tests",
    "run_single_e2e_test",
    "run_tests_by_pattern",
    "find_flaky_tests",
    "check_api_health",
    "check_all_endpoints_health",
]
