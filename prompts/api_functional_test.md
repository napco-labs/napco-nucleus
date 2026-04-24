# Task: API Functional Test

Dimension: Test Automation. Fires on-demand (workflow_dispatch) and pre-deploy.

Runs the Newman / Postman collection against the MVP Access API to verify every endpoint still honors its contract. Ships a PDF report to the team on completion.

---

## Loop

### 0. Memory check-in

- `recall_test_runs(task_name="api-functional-test", limit=5)` — last 5 runs. Use for trend context in the final summary.
- `recall_activity(task_name="api-functional-test:run", limit=3)` — any errors or retries in the last few runs?

### 1. Pre-flight

- `check_api_health()` — confirm the target API is reachable and credentials are valid. If this fails, stop cleanly and log the reason; don't run the full suite against a dead target.

### 2. Execute

`run_api_tests()` — runs the Newman collection once. AT MOST ONCE per invocation.

### 3. Interpret

- If all pass: note the counts + duration. No RCA needed.
- If any fail: read the failure details. For each failure, decide: real bug, environment issue, or flaky. Use `list_known_bugs()` to check if any failures match xfail entries. Don't invent root causes — if the failure doesn't have an obvious cause, say so.

### 4. Report

- `generate_pdf_report(summary=<your_executive_summary>)` — 2-3 paragraph summary:
  - Paragraph 1: headline verdict (pass rate, regressions vs last run from memory).
  - Paragraph 2: specific failures (endpoints, status codes, response bodies). Call out any clear backend bugs.
  - Paragraph 3 (optional): recommended next steps.
  Plain text, blank line between paragraphs, no markdown.
- `send_email_report()` — ships the PDF to `TEAM_EMAILS`.
- `send_teams_digest()` — one-line Teams card.

### 5. Log + exit

- `log_test_run(task_name="api-functional-test", total=..., passed=..., failed=..., skipped=..., duration_s=..., report_pdf_path=..., regressions_detected=...)` — drop a row into memory so tomorrow's Daily Report can cite it.
- `log_activity("api-functional-test:shipped", ...)` — final breadcrumb.

---

## Guardrails

- One full run per invocation. If re-running a subset, use `run_tests_by_pattern(pattern=...)` instead of `run_api_tests()`.
- Never claim a test is "fixed" without evidence from the current run's results.
- If `check_api_health` fails, do NOT skip it — stop the run and report the environment issue.
- NO em-dashes in the report body.
