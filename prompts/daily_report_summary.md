# Task: Daily Report — Executive Summary

Dimension: Project Management. Fires once daily at **09:30 BDT (03:30 UTC)**.

This task ships ONE email: the **executive summary** to `SUMMARY_EMAILS` (leadership only — khasan + assad today, will grow). The detailed test report is a separate workflow (`daily-report-detailed`) that fires 30 minutes earlier at 09:00 BDT.

This is the at-a-glance dashboard. **6 short blocks, 3-4 lines each.** A leader skims it in 60 seconds. No pie charts, no tables, no marketing.

**Scope: 6 blocks** in this exact order — Requirement Management, API Functional, API Integration, API Load, MVP Access E2E, MVPAccess CICD. Runner-status surfaces inline in the executive intro only when something is broken; otherwise omitted.

---

## Loop

### 0. Memory check-in (mandatory)

- `memory_stats()` — sanity check.
- `recall_test_runs(since="<24h ago ISO>", limit=10)` — last 24h test runs.
- `recall_activity(task_name="mvpaccess-cicd", limit=1)` — last CICD result.
- `recall_activity(since="<24h ago ISO>", limit=100)` — for runner health, workflow error scan, AND today's `requirement-management:*` entries (poll_email / publish_backlog rows).

### 1. Runner sanity check (silent unless broken)

Use `recent_commits(project="ai-agent", count=5)` to confirm the runner is committing memory rows on schedule. Use `recall_activity(limit=10)` to see if any task has logged an `error:` row in the last hour. **If everything is green, do not mention runner status in the report at all.** If the runner went offline or any workflow errored, add a one-line note in the Executive Summary intro flagging it.

### 2. Compose the executive summary — 6 blocks, 3-4 lines each

Each block is **strictly 3-4 lines, plain text, no marketing**. Lead each block with the headline number. Always cite a verifiable source.

```
NAPCO Nucleus — Executive Summary, <today's date in BDT>

REQUIREMENT MANAGEMENT
<3-4 lines. Headline: total Work Packages filed today against
OpenProject mvp-access, broken down by Category (AccessGroup /
BadgeHolder / Personnel). Then a "Pipeline status" line:
"Email and Google Drive ingestion are operational; MS Teams
integration is planned (Power Automate bridge scaffolded)."
Flag any publish errors. Example headline: "9 work packages filed
today (AccessGroup 3, Personnel 3, BadgeHolder 3) from 1 ingested
email, 0 publish errors. OpenProject backlog at 172.16.205.123:8080.">

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
<Default framing (until prod credentials land):
"CICD pipeline is set up and tested locally. Production deployment is
awaiting environment access and credentials (TFS personal access
token, IIS deployment service account). Once credentials land no code
change is needed — the workflow runs on its existing 22:00 BDT
schedule."

If the workflow has actually been running successfully (post
credentials), replace with: 3-4 lines on last night's pull, build,
deploy, health check verdict, deployed commit hash.>
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
- REQUIREMENT MANAGEMENT: "9 work packages filed today (AccessGroup 3, Personnel 3, BadgeHolder 3) from 1 ingested email, 0 publish errors..."
- MVPACCESS CICD: "Last night's deploy succeeded at 22:18 BDT. 92 MB published. Health check returned 200 in 1.2s." (or default "set up and tested locally, awaiting environment access and credentials" framing if not yet wired).
