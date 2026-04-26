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

- Find the two most recent pytest reports yourself: `list_project_files(project="api-test", directory="reports", pattern="pytest_report*.json")`, take the two newest, then `read_file` each. Build a `{nodeid → outcome}` map for both. Tests that were `passed` previously and `failed` now are regressions; the reverse are newly-fixed.
- For any regression candidates, check if they've oscillated recently in memory. If `recall_test_runs` shows the same test flipping red↔green across recent runs, it's probably flaky, not a regression. Flag accordingly.
- Cross-check failures against xfail markers: `read_file(project="api-test", path="integration-tests/known_bugs.py")` and scan for `pytest.mark.xfail(...reason="...")` blocks. Known-bug failures aren't actionable; surface them in their own bucket.

### 4. Generate PDF (artifact only — NO email)

`generate_pdf_report(summary=<executive_summary>)` — 2-3 paragraphs:
- P1: pass rate today vs. 7-day average (from memory). Lead with regressions if any.
- P2: specific regressions named by test ID. Flaky tests called out separately. Known-bug failures in a third bucket.
- P3: if there are real regressions, name the commit / deploy that likely introduced them (use `recent_commits(project="MVP-Access-API-Test", count=10)` to scan recent changes).

**Do NOT call `send_email_report` or `send_teams_digest`.** The team receives one consolidated email per day from the Daily Report workflow.

### 5. Log + exit

- `log_test_run(task_name="api-integration-test", ...)` with full counts + `regressions_detected`. MANDATORY — Daily Report reads this.
- `log_activity("api-integration-test:finished", ...)`.

---

## Guardrails

- Do NOT run twice if the first run had transient errors. Mark the run as "degraded" in the log and move on.
- If regression count > 0, Teams digest should flag it with `⚠️` so on-call sees it in passing.
- NO em-dashes in reports.
