# Task: API Integration Test

Dimension: Test Automation. Fires nightly at 02:00 BDT.

Runs the pytest integration suite end-to-end: login, data creation, cross-endpoint flows, cleanup. Distinguishes real bugs from flakies and regressions using memory of prior runs.

---

## Loop

### 0. Memory check-in

- `recall_test_runs(task_name="api-integration-test", limit=7)` — week of history for regression context.
- `recall_activity(task_name="api-integration-test:run", limit=3)` — any recent crashes?

### 1. Pre-flight

`check_api_health()` — target alive + auth valid. If fail, stop.

### 2. Execute

`run_integration_tests()` — runs pytest once. AT MOST ONCE per invocation.

### 3. Regression + flaky analysis

- `compare_with_last_run()` — surfaces tests that went green→red (regression) or red→green (newly-fixed) since last run.
- For any regression candidates, check if they've oscillated recently in memory. If `recall_test_runs` shows the same test flipping red↔green across recent runs, it's probably flaky, not a regression. Flag accordingly.
- `list_known_bugs()` — cross-check failures against xfail markers. Known-bug failures aren't actionable; surface them separately.

### 4. Report

`generate_pdf_report(summary=<executive_summary>)` — 2-3 paragraphs:
- P1: pass rate today vs. 7-day average (from memory). Lead with regressions if any.
- P2: specific regressions named by test ID. Flaky tests called out separately. Known-bug failures in a third bucket.
- P3: if there are real regressions, name the commit / deploy that likely introduced them (use `recent_commits(project="MVP-Access-API-Test", count=10)` to scan recent changes).

Then: `send_email_report()`, `send_teams_digest()`.

### 5. Log + exit

- `log_test_run(task_name="api-integration-test", ...)` with full counts + `regressions_detected`.
- `log_activity("api-integration-test:shipped", ...)`.

---

## Guardrails

- Do NOT run twice if the first run had transient errors. Mark the run as "degraded" in the log and move on.
- If regression count > 0, Teams digest should flag it with `⚠️` so on-call sees it in passing.
- NO em-dashes in reports.
