# Task: Daily Report — Executive Summary

Dimension: Project Management. Fires once daily at **09:30 BDT (03:30 UTC)**.

This task ships ONE email: the **executive summary** to `SUMMARY_EMAILS` (leadership only — khasan + assad today, will grow). The detailed test report is a separate workflow (`daily-report-detailed`) that fires 30 minutes earlier at 09:00 BDT.

This is the at-a-glance dashboard. **6 short blocks, 3-4 lines each.** A leader skims it in 60 seconds. No pie charts, no tables, no marketing.

**Scope: 4 tests + CICD + Runner Status.** Specifically: API Functional, API Integration, API Load, MVP Access E2E, MVPAccess CICD, and the self-hosted runner's health.

---

## Loop

### 0. Memory check-in (mandatory)

- `memory_stats()` — sanity check.
- `recall_test_runs(since="<24h ago ISO>", limit=10)` — last 24h test runs.
- `recall_activity(task_name="mvpaccess-cicd", limit=1)` — last CICD result.
- `recall_activity(since="<24h ago ISO>", limit=100)` — for runner health and workflow error scan.

### 1. Check VM runner status

Use `recent_commits(project="ai-agent", count=5)` to confirm the runner is committing memory rows on schedule. Use `recall_activity(limit=10)` to see if any task has logged an `error:` row in the last hour. Compose a one-line health verdict like: "Self-hosted Windows runner online, last commit 14 minutes ago, no errors in the last 24 hours."

### 2. Compose the executive summary — 6 blocks, 3-4 lines each

Each block is **strictly 3-4 lines, plain text, no marketing**. Lead each block with the headline number. Always cite a verifiable source.

```
NAPCO Nucleus — Executive Summary, <today's date in BDT>

API FUNCTIONAL TEST
<3-4 lines: pass rate today vs. yesterday, headline number of failures,
whether any new regressions surfaced, link to the per-run PDF.>

API INTEGRATION TEST
<3-4 lines: pass rate, regressions if any, link to the per-run PDF.>

API LOAD TEST
<3-4 lines: capacity ceiling tier, worst latency, comparison with the
prior day's run.>

MVP ACCESS E2E TEST
<3-4 lines: pass rate, count of failures grouped by suspected root cause,
any browser-specific failures.>

MVPACCESS CICD
<If CICD has not been wired up yet (TFS secrets missing): one line
"CICD pipeline production-ready but awaiting IT credentials. See readiness
checklist." Once live: 3-4 lines on last night's pull, build, deploy,
health check verdict, deployed commit hash.>

VM RUNNER STATUS
<3-4 lines: self-hosted Windows runner uptime, last successful commit,
whether any workflow failed in the last 24 hours and which.>
```

### 3. Ship

- `generate_pdf_report(summary=<your_executive_summary_markdown>)` — produces the SHORT PDF.
- `send_email_report()` — emails the PDF to `SUMMARY_EMAILS` (leadership only). Make sure `os.environ["TEAM_EMAILS"]` is temporarily replaced with the value of `SUMMARY_EMAILS` before this call so the existing send_email_report tool reads the right recipient list. Restore `TEAM_EMAILS` after.
- `log_activity("daily-report-summary:shipped", "sent_to=<count>_leadership_recipients", <pdf_path>)` — final breadcrumb.

### 4. Exit

If memory check-in returns empty (DB just initialized): ship a stub summary saying "no historical data yet, this is the first run" rather than fabricating numbers.

---

## Tone

Plain English. Each block stands alone. A leader reading only the LOAD TEST block should still understand it. No "strong performance", no "looks good". Use numbers. No em-dashes.

Lead each block with the headline number. Examples:

- API FUNCTIONAL TEST: "288 of 315 tests passed today (91.4%), down 0.3 points from yesterday..."
- VM RUNNER STATUS: "Self-hosted Windows runner online, last successful commit 14 minutes ago, zero errored workflows in the last 24 hours..."
- MVPACCESS CICD: "Last night's deploy succeeded at 22:18 BDT. 92 MB published. Health check returned 200 in 1.2s."
