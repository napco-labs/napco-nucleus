# Task: Daily Report

Dimension: Project Management. Fires once daily at 09:00 BDT.

**This is the ONLY email the team gets per day.** The 4 test workflows (api-functional, api-integration, api-load, e2e) run their tests and write results to memory but do NOT send individual emails. Your job is to pull their results together into one consolidated report.

Replaces the old `morning_brief.py` Python template script. The report still lands in stakeholders' inboxes, but now the executive summary is reasoned by Claude rather than templated by f-string — better signal-to-noise for a busy reader.

Output: ONE PDF emailed to `TEAM_EMAILS` (CSV in env) from the configured SMTP identity, plus ONE Teams digest.

---

## Loop

### 0. Memory check-in (mandatory)

Today's report is basically a read of the last 24 hours of memory. Load it all first:

- `memory_stats()` — sanity check (are the tables populated?).
- `recall_activity(since="<24h ago ISO>", limit=200)` — every action the agent took yesterday. This is the spine of the report.
- `recall_test_runs(since="<24h ago ISO>", limit=20)` — **every test run from today across all 4 test workflows (api-functional, api-integration, api-load, e2e)**. This is THE source of truth for the Test Automation section, because those workflows no longer send their own emails. Use `report_pdf_path` from each row to attach the per-run PDF to this consolidated email (or link to it).
- `recall_activity(task_name="requirement-management:publish_gitlab", limit=10)` — recent backlog pushes for the Project Management section.

### 1. Read fresh artifacts

Call `read_file` on the latest reports in `MVP-Access-API-Test/reports/`:
- `pytest_report.json` (integration run)
- `newman_report.json` (API functional run)
- Playwright `results.json` from `MVP-Access-E2E-Test/test-results/` and sibling projects
- The most recent load-test log in `reports/`

Skip any that are missing or older than 24 hours. Don't fabricate data — if a suite hasn't run today, say so in the report.

### 2. Compare vs. yesterday

For integration + API runs: `compare_with_last_run()` to surface regressions + newly-fixed tests.

### 3. Compose the report — SIX sections, single PDF

The final PDF is ONE consolidated document with the structure below. Write each section yourself (Claude-first — no f-string templates). Every claim must be anchored to a source: a file path, a GitLab issue link, an `activity_logs` row, or a `test_run_history` row. No "strong performance", no "looks good". Use numbers.

```
# NAPCO Nucleus — Daily Report, <today's date in BDT>

## Executive Summary
<2-3 sentences. Lead with the verdict: what works, what broke, what
needs human attention. If regressions were detected, lead with them.>

## 1. Requirement Management
<Narrative paragraph describing today's requirement activity. Tone:
warm, confident, clear — the stakeholders reading this want to know
their requests are being honored.>
<Example shape:
  "Today we captured N new client requirements from email, Drive
  meeting recordings, and Teams channel posts. Every requirement
  was split into 3-hour tasks and tracked in the GitLab backlog.
  The team has K issues open at the start of tomorrow, and no
  message has been dropped."
  Then: 3-5 bullet points with specifics (source → task count →
  GitLab IIDs) sourced from recall_activity(
  task_name="requirement-management:publish_gitlab").>

## 2. API Functional Test
<Pie chart: pass / fail / skip from the most recent run. Counts,
duration, regressions by test ID, known-bug failures separated,
flaky tests called out. Link to the per-run PDF artifact.>

## 3. API Integration Test
<Same shape. Lead with regressions vs. 7-day average from
recall_test_runs(task_name="api-integration-test", limit=7).>

## 4. API Load Test
<Pie chart here is optional — prefer a tier/RPS block if the latest
run wasn't today (load is weekly). Capacity ceiling + week-over-week
delta if available.>

## 5. MVP Access E2E Test
<Pie chart. Failing tests grouped by suspected root cause. Reference
the per-run PDF (which carries the failure screenshots).>

## 6. CICD — Build + Deploy
<One paragraph confirming last night's MVP Access CICD result.
Source: recall_activity(task_name="mvpaccess-cicd", limit=1). If the
deploy succeeded, say so clearly and cite the GitHub Actions run URL.
If it failed, lead with the failure and surface the error from
technical_details.>
```

**Rule: the 4 test sections MUST each have a pie chart** — pass / fail / skipped breakdown. The `generate_pdf_report` tool handles the actual PDF rendering, including per-suite pie charts, when you pass it the structured summary above.

### 4. Ship

- `generate_pdf_report(summary=<your_markdown>)` — produces the unified PDF with the 6 sections above.
- `send_email_report()` — emails the PDF to `TEAM_EMAILS`. The From header should render as `NAPCO Nucleus <khasan@ael-bd.com>` (via `SMTP_FROM_NAME` + `SMTP_FROM` env vars). Recipients come from the `TEAM_EMAILS` env var (CSV). Currently one address while we validate end-to-end; will expand back to the full team once stable.
- `send_teams_digest()` — one-line Teams card (no-op if `TEAMS_WEBHOOK_URL` isn't set).
- `log_activity("daily-report:shipped", "sent_to=<count>_recipients", <pdf_path>)` — final breadcrumb.

### 5. Exit

Log any failures explicitly (IMAP auth, PDF generation, SMTP). A partial report is better than no report. Degrade gracefully — if the PDF generator fails, still send a plain-text email with the executive summary.

---

## Tone

Plain developer English. No em-dashes. One line per bullet. Treat the reader as a senior peer with 5 minutes to scan.
