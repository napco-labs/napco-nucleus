# Task: Daily Report — Detailed Test Report

Dimension: Project Management. Fires once daily at **09:00 BDT (03:00 UTC)**.

This task ships ONE email: the **detailed daily test report** to `TEAM_EMAILS` (the full engineering team). The shorter executive summary is a separate workflow (`daily-report-summary`) that fires 30 minutes later at 09:30 BDT.

**Scope: the 4 test workflows + Requirement Management.** Specifically: API Functional, API Integration, API Load, MVP Access E2E, plus today's Requirement Management ingestion (work packages filed against OpenProject, by category). CICD status is NOT in this report; it belongs in the executive summary.

The 4 test workflows all fire at 02:00 BDT and finish by ~04:00 BDT, so by the time this report runs at 09:00 BDT every test result of the day is already in memory and on disk. Requirement Management fires twice daily (07:00 + 19:00 UTC) so its activity is also in memory by report time.

---

## Loop

### 0. Memory check-in (mandatory)

- `memory_stats()` — sanity check.
- `recall_test_runs(since="<24h ago ISO>", limit=20)` — every test run from today across all 4 test workflows. Source of truth.
- `recall_activity(since="<24h ago ISO>", limit=100)` — find the 4 test workflows' run/finished entries AND today's Requirement Management activity (`task_name` starts with `requirement-management:` — e.g. `requirement-management:poll_email`, `requirement-management:publish_backlog`).

### 1. Read fresh artifacts

Call `read_file` on the latest reports in `MVP-Access-API-Test/reports/`:
- `pytest_report.json` (integration)
- `newman_report.json` (functional)
- Playwright `results.json` from `MVP-Access-E2E-Test/test-results/`
- The most recent load test log

Skip any that are missing or older than 24 hours. If a suite did not run today, say so honestly. Never fabricate data.

### 2. Compare vs. yesterday

For integration + API runs: `list_project_files(project="api-test", directory="reports", pattern="pytest_report*.json")` to find the two most recent reports. `read_file` each. Build `{nodeid → outcome}` maps for both. Tests that were `passed` previously and `failed` now are regressions; the reverse are newly fixed.

### 3. Compose the detailed report — 4 sections, one PDF

Each section has full detail with a pie chart. Write each section yourself, no f-string templates. Every claim anchored to a source.

```
NAPCO Nucleus — Daily Test Report, <today's date in BDT>

## Executive Summary
<2-3 sentences. Lead with the verdict: what works, what broke, what
needs human attention. If regressions were detected, lead with them.>

## 1. API Functional Test
<Pie chart: pass / fail / skip from the most recent run. Counts,
duration, regressions by test ID, known-bug failures separated,
flaky tests called out. Link to the per-run PDF artifact.>

## 2. API Integration Test
<Same shape. Lead with regressions vs. 7-day average from
recall_test_runs(task_name="api-integration-test", limit=7).>

## 3. API Load Test
<Pie chart on tier outcomes. Capacity ceiling tier, worst latency,
week-over-week delta if available.>

## 4. MVP Access E2E Test
<Pie chart. Failing tests grouped by suspected root cause. Reference
the per-run PDF (which carries the failure screenshots).>

## 5. Requirement Management — Today's Ingestion
<Lead with the headline number: how many Work Packages were filed in
OpenProject today, broken down by Category (AccessGroup / BadgeHolder /
Personnel) and Type (Task / Bug / updatedRequirements).
Then: how many emails were polled and how many were ingested vs.
skipped (off-allowlist, dedup hits). If `requirements_seen` was reset
or any publish errored, surface it explicitly. Cite each WP by id and
title; link the OpenProject project URL `http://172.16.205.123:8080/projects/mvp-access/work_packages`.
3 to 6 lines plus the per-category breakdown.>
```

**The 4 test sections MUST each have a pie chart** — pass / fail / skipped breakdown. Section 5 (Requirement Management) is text-only — no pie chart needed.

### 4. Ship

- `generate_pdf_report(summary=<your_markdown>)` — produces the unified PDF.
- `send_email_report()` — emails the PDF to `TEAM_EMAILS`. The From header renders as `NAPCO Nucleus <khasan@ael-bd.com>`.
- `send_teams_digest()` — one-line Teams card (no-op if `TEAMS_WEBHOOK_URL` is not set).
- `log_activity("daily-report-detailed:shipped", "sent_to=<count>_recipients", <pdf_path>)` — final breadcrumb.

### 5. Exit

Log any failures explicitly (PDF generation, SMTP). A partial report is better than no report. Degrade gracefully — if the PDF generator fails, still send a plain-text email with the executive summary.

---

## Tone

Plain developer English. No em-dashes. One line per bullet. Treat the reader as a senior peer with 5 minutes to scan. Always cite a source.
