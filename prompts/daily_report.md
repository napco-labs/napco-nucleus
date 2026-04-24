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
- `newman_report.json` (API run)
- Playwright `results.json` from `MVP-Access-E2E-Test/test-results/` and sibling projects
- The most recent load-test log in `reports/`

Skip any that are missing or older than 24 hours. Don't fabricate data — if a suite hasn't run today, say so in the report.

### 2. Compare vs. yesterday

For integration + API runs: `compare_with_last_run()` to surface regressions + newly-fixed tests.

### 3. Compose the summary

Draft the report body as markdown with this shape:

```
# Daily Report — <today's date in BDT>

## Executive Summary
<2-3 sentences. Lead with the verdict: what worked, what broke, what needs human attention. If regressions were detected, lead with them.>

## Action Items
<bullet list of anything that needs Mohammad / the team to act:
  - failed tests that look like real bugs (vs flakies)
  - new human-reply requirement emails waiting for clarification
  - GitLab issues created in the last 24h that reference blocked dependencies>

## Test Automation
<per-suite block: API / Integration / Load / E2E>
  - counts (pass / fail / skip)
  - duration
  - regressions (if any) — name them with the test IDs
  - flaky tests detected
  - link to PDF if generated today

## Project Management
<requirement ingestion status>
  - emails polled / files ingested
  - distinct requirements found
  - tasks published to GitLab (link by IID)
  - skipped-as-duplicate count

## Market Technology Scan (optional)
<if you can, 2-3 bullet observations about tools / stacks mentioned in today's requirement sources that would be worth aligning the test stack with. Anchor every observation to a source file path.>
```

**Rule: every claim in the report body must be anchored to a source — a file path, a GitLab issue link, a `recall_*` result. No "looks good", no "strong performance". Use numbers.**

### 4. Ship

- `generate_pdf_report(summary=<your_markdown>)` — produces the PDF.
- `send_email_report()` — emails the latest PDF to `TEAM_EMAILS`.
- `send_teams_digest()` — posts a one-line card to the Teams channel (no-op if `TEAMS_WEBHOOK_URL` isn't set).
- `log_activity("daily-report:shipped", "sent_to=<count>_recipients", <pdf_path>)` — final breadcrumb.

### 5. Exit

Log any failures explicitly (IMAP auth, PDF generation, SMTP). A partial report is better than no report. Degrade gracefully — if the PDF generator fails, still send a plain-text email with the executive summary.

---

## Tone

Plain developer English. No em-dashes. One line per bullet. Treat the reader as a senior peer with 5 minutes to scan.
