# Task: MVP Access E2E Test

Dimension: Test Automation. Fires nightly at 04:00 BDT.

Runs the Playwright end-to-end suite against a deployed environment. The PDF report attaches failure screenshots so Dev can see exactly what the UI looked like when the test broke.

---

## Loop

### 0. Memory check-in

- `recall_test_runs(task_name="e2e-test", limit=7)` — week of history.
- `recall_activity(task_name="e2e-test:run", limit=3)` — any recent crashes?

### 1. Execute

`run_e2e_tests(suite="full")` — runs the Playwright full suite once. AT MOST ONCE per invocation. The tool returns structured results with `failures` including screenshot + trace file paths.

### 2. Analyze failures

For each failure:
- Read the test name + error message
- Check if the screenshot is available (should be for most Playwright failures)
- Check `list_known_bugs()` to see if it matches a documented xfail
- Use `compare_with_last_run()` to distinguish regressions from ongoing-known-failures

**Flaky detection:** If `recall_test_runs` shows the same test flipping red↔green across the last 3-5 runs, it's flaky. Flag it separately in the report; don't count it toward "real regressions".

### 3. Report

`generate_pdf_report(summary=<executive_summary>)` — 2-3 paragraphs:
- P1: pass rate, regressions vs last run. Lead with any auth-flow / critical-path failures.
- P2: specific failing tests, grouped by suspected root cause (auth, navigation, data race, timing). Attach screenshots via the PDF generator.
- P3: flaky tests summary + known-bug passes.

Then: `send_email_report()`, `send_teams_digest()`.

### 4. Log + exit

- `log_test_run(task_name="e2e-test", suite="full", ...)`.
- `log_activity("e2e-test:shipped", ...)`.

---

## Writing new E2E tests (Plan / Generate / Verify)

When the user asks you to write / create / generate an E2E test instead of running the suite, follow system.md's Plan / Generate / Verify workflow. Don't skip `explore_ui` — real accessibility tree beats guessing selectors.

---

## Guardrails

- Never silently drop a failing test because "it looks flaky". If unsure, surface it in the report with the flaky tag AND the regression tag and let the reviewer decide.
- If the entire suite fails (>50%), that's usually an environment problem (wrong URL, auth down, CDN down) — say so in the report instead of listing 100 individual failures.
- NO em-dashes in reports.
