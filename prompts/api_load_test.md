# Task: API Load Test

Dimension: Test Automation. Fires weekly on Sunday 03:00 BDT (expensive, not nightly).

Runs a multi-tier Locust load test to find the capacity ceiling of the MVP Access API. The report emphasizes the ceiling, not the pass rate — the goal is to identify where the system degrades and why.

---

## Loop

### 0. Memory check-in

- `recall_test_runs(task_name="api-load-test", limit=8)` — 8 weeks of history. Use this to plot capacity trend.
- `recall_activity(task_name="api-load-test:run", limit=3)`.

### 1. Pre-flight

- `check_api_health()` — target alive.
- `check_all_endpoints_health()` — 78-endpoint non-destructive probe. If any endpoint is already failing before load, flag it — running load against a broken endpoint produces misleading results.

### 2. Execute

`run_load_tests()` — runs all configured tiers (e.g., 100 / 500 / 1000 concurrent users). AT MOST ONCE per invocation. Long-running (15-30 min typical).

### 3. Interpret

- Read the aggregated stats per tier: average response time, p95, p99, failures, RPS.
- Identify the tier where degradation starts (response time doubles, or failure rate crosses 5%). That's the capacity ceiling.
- Compare to the last few runs from memory. Is the ceiling trending up, down, or flat? Is a specific endpoint degrading faster than others?

### 4. Report

`generate_pdf_report(summary=<executive_summary>)` — 2-3 paragraphs:
- P1: this week's ceiling. If it moved meaningfully vs last week (>20% in either direction), lead with the delta and a hypothesis (recent deploy? schema change? infra change?).
- P2: per-endpoint drill-down. Name the endpoints that degraded first. Flag any that regressed vs last week.
- P3: recommendations. Concrete — e.g., "index the `access_log.user_id` column" not "optimize database".

Then: `send_email_report()`, `send_teams_digest()`.

### 5. Log + exit

- `log_test_run(task_name="api-load-test", duration_s=..., notes="ceiling=<tier>, p99_at_ceiling=<ms>")`.
- `log_activity("api-load-test:shipped", ...)`.

---

## Guardrails

- Never claim a load improvement without comparing to at least 2 prior runs — one run vs one run is noise.
- If the load test can't reach the highest tier (e.g., target refused connections well before the ceiling), the report must say so explicitly; don't pretend degradation at tier 2 is the real ceiling.
- NO em-dashes in reports.
