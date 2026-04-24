"""
NAPCO Nucleus — Test Automation tools.

Thin re-export layer over tools_legacy.py for the Test Automation
dimension's 4 workflows (API Functional, API Integration, API Load,
MVP Access E2E).

Tools:
    run_load_tests          Locust multi-tier via API-Test
    run_api_tests           Newman/Postman collection
    run_integration_tests   pytest suite
    run_e2e_tests           Playwright full/easy/release
    run_single_e2e_test     One-spec run with tracing (Plan/Gen/Verify)
    run_tests_by_pattern    pytest -k filter
    find_flaky_tests        N repeats, flag oscillation
    check_api_health        ping /api/account/login
    check_all_endpoints_health   78-endpoint non-destructive probe
    list_known_bugs         pytest.mark.xfail registry
    test_inventory          counts per resource / category
    compare_with_last_run   regressions + newly-fixed
    analyze_test_failures   RCA cascade (regex heuristics — candidate
                            for Claude-first rewrite in a later pass)
"""
from __future__ import annotations

from tools_legacy import (  # noqa: F401
    run_load_tests_tool,
    run_api_tests_tool,
    run_integration_tests_tool,
    run_e2e_tests_tool,
    run_single_e2e_test_tool,
    run_tests_by_pattern_tool,
    find_flaky_tests_tool,
    check_api_health_tool,
    check_all_endpoints_health_tool,
    list_known_bugs_tool,
    test_inventory_tool,
    compare_with_last_run_tool,
    analyze_test_failures_tool,
)


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
    list_known_bugs_tool,
    test_inventory_tool,
    compare_with_last_run_tool,
    analyze_test_failures_tool,
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
    "list_known_bugs",
    "test_inventory",
    "compare_with_last_run",
    "analyze_test_failures",
]
