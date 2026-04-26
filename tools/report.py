"""
NAPCO Nucleus — Reporting + telemetry tools.

Mechanical plumbing only. Claude composes the executive summary and
classifies failures in the prompt; these tools just render the PDF,
ship the email, post the Teams card, and tail logs.

Tools:
    generate_pdf_report   build the consolidated PDF (calls sibling
                          report_generator + history snapshot)
    send_email_report     SMTP send of latest PDF to TEAM_EMAILS
    send_teams_digest     short MessageCard to TEAMS_WEBHOOK_URL
    tail_nightly_log      tail logs/nightly_YYYY-MM-DD.log
    clean_reports_folder  wipe pdf/csv/json/xlsx in REPORTS_DIR
"""
from __future__ import annotations

import glob
import json
import logging
import os

from claude_agent_sdk import tool

from tools._shared import (
    STATE,
    _text,
    config,
    _generate_pdf,
    send_report_email,
    history,
    _coverage,
    bug_reporter,
    patch_generator,
    teams_notifier,
)

logger = logging.getLogger(__name__)


# ─── clean_reports_folder ────────────────────────────────────────────
@tool(
    "clean_reports_folder",
    "Delete all existing PDF / JSON / CSV report artifacts in the API-Test reports/ folder before a fresh run. Use when the user asks for a clean report or fresh output.",
    {},
)
async def clean_reports_folder_tool(_args):
    deleted = []
    for pattern in ("*.pdf", "*.csv", "*.json", "*.xlsx"):
        for f in glob.glob(os.path.join(config.REPORTS_DIR, pattern)):
            try:
                os.remove(f)
                deleted.append(os.path.basename(f))
            except Exception as e:
                logger.warning(f"Failed to delete {f}: {e}")
    STATE["report_paths"] = []
    return _text({"deleted": deleted, "deleted_count": len(deleted)})


# ─── generate_pdf_report ─────────────────────────────────────────────
@tool(
    "generate_pdf_report",
    "Generate the consolidated PDF report from collected results. Pass a 2-3 "
    "paragraph executive summary (plain text, blank line between paragraphs) "
    "as `summary` — it renders right after the title page so developers see "
    "the headline findings before drilling into details. Returns the PDF path.",
    {"summary": str},
)
async def generate_pdf_report_tool(args):
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    timestamp = STATE["started_at"].strftime("%Y%m%d_%H%M%S")
    path = os.path.join(config.REPORTS_DIR, f"Test_Report_{timestamp}.pdf")

    summary = (args or {}).get("summary") if isinstance(args, dict) else None

    load_list = STATE["load"] or None
    api_result = STATE["api"]
    integ_result = STATE["integration"]
    e2e_result = STATE["e2e"]

    snap_path = history.save_snapshot(
        load_list, api_result, integ_result, e2e_result, STATE["started_at"]
    )
    with open(snap_path, encoding="utf-8") as f:
        current_snap = json.load(f)
    prev_snap = history.load_previous_snapshot(before_path=snap_path)
    regressions = history.compute_regressions(current_snap, prev_snap)
    flaky = history.compute_flaky_tests()
    coverage_report = _coverage.build_coverage_report()

    _generate_pdf(
        load_results_list=load_list,
        api_results=api_result,
        integration_results=integ_result,
        e2e_results=e2e_result,
        output_path=path,
        run_date=STATE["started_at"],
        summary=summary,
        regressions=regressions if prev_snap else None,
        flaky_tests=flaky,
        coverage=coverage_report,
    )
    STATE["report_paths"].append(path)

    drafts_path = bug_reporter.write_bug_drafts(
        load_list, api_result, integ_result, e2e_result, STATE["started_at"]
    )
    if drafts_path:
        STATE["report_paths"].append(drafts_path)

    failures = list(bug_reporter.iter_failures(
        load_list, api_result, integ_result, e2e_result
    ))
    patches = patch_generator.generate_patches(failures)
    patch_path = patch_generator.write_patch_file(patches, STATE["started_at"])
    if patch_path:
        STATE["report_paths"].append(patch_path)

    return _text({
        "pdf_path": path,
        "exists": os.path.exists(path),
        "bug_drafts": drafts_path,
        "test_patches": patch_path,
        "patch_count": len(patches),
        "regressions": len(regressions) if regressions else 0,
        "flaky_tests": len(flaky),
        "coverage_pct": (coverage_report or {}).get("coverage_pct"),
    })


# ─── send_email_report ───────────────────────────────────────────────
@tool(
    "send_email_report",
    "Email the latest generated PDF to TEAM_EMAILS (from MVP-Access-API-Test/.env).",
    {"summary": str},
)
async def send_email_report_tool(args):
    if not STATE["report_paths"]:
        return _text({"error": "No report generated yet. Call generate_pdf_report first."})
    if not config.TEAM_EMAILS:
        return _text({"error": "TEAM_EMAILS not configured in MVP-Access-API-Test/.env."})
    send_report_email(STATE["report_paths"], STATE["started_at"])
    return _text({
        "sent_to": config.TEAM_EMAILS,
        "attachments": [os.path.basename(p) for p in STATE["report_paths"]],
        "summary_included": bool((args or {}).get("summary")),
    })


# ─── send_teams_digest ───────────────────────────────────────────────
@tool(
    "send_teams_digest",
    "Post a short test-run digest to the TEAMS_WEBHOOK_URL env var (Microsoft Teams incoming webhook). Renders as a MessageCard with pass/fail counts, worst load tier, and regression count. Silent no-op if TEAMS_WEBHOOK_URL isn't set.",
    {},
)
async def send_teams_digest_tool(_args):
    pdf_path = STATE["report_paths"][0] if STATE["report_paths"] else None
    snap_paths = sorted(glob.glob(os.path.join(
        config.REPORTS_DIR, "history", "*.json")))
    prev = history.load_previous_snapshot(before_path=snap_paths[-1]) if snap_paths else None
    current = None
    if snap_paths:
        try:
            with open(snap_paths[-1], encoding="utf-8") as f:
                current = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    regressions = history.compute_regressions(current, prev) if current else []
    flaky = history.compute_flaky_tests()

    res = teams_notifier.post_digest(
        load_results_list=STATE["load"] or None,
        api_results=STATE["api"],
        integration_results=STATE["integration"],
        e2e_results=STATE["e2e"],
        regressions=regressions,
        flaky_tests=flaky,
        pdf_path=pdf_path,
        run_date=STATE["started_at"],
    )
    return _text(res)


# ─── tail_nightly_log ────────────────────────────────────────────────
@tool(
    "tail_nightly_log",
    "Show the last N lines of today's (or yesterday's) nightly log file so the user can see what the scheduled run did. Default N=80.",
    {"day": str, "lines": int},
)
async def tail_nightly_log_tool(args):
    from datetime import datetime, timedelta
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
    log_dir = os.path.abspath(log_dir)
    day = (args.get("day") or "today").lower()
    if day == "today":
        stamp = datetime.now().strftime("%Y-%m-%d")
    elif day == "yesterday":
        stamp = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        stamp = day
    lines = int(args.get("lines") or 80)
    path = os.path.join(log_dir, f"nightly_{stamp}.log")
    if not os.path.isfile(path):
        existing = sorted(glob.glob(os.path.join(log_dir, "nightly_*.log")))[-3:]
        return _text({
            "error": f"No log for {stamp}",
            "available_logs": [os.path.basename(p) for p in existing],
        })
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    tail_lines = content.splitlines()[-lines:]
    return _text({"log_file": path, "total_lines": len(content.splitlines()),
                  "tail": "\n".join(tail_lines)})


TOOLS = [
    generate_pdf_report_tool,
    send_email_report_tool,
    send_teams_digest_tool,
    tail_nightly_log_tool,
    clean_reports_folder_tool,
]

TOOL_NAMES = [
    "generate_pdf_report",
    "send_email_report",
    "send_teams_digest",
    "tail_nightly_log",
    "clean_reports_folder",
]
