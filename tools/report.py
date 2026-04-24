"""
NAPCO Nucleus — Reporting + Telemetry tools.

Thin re-export layer over tools_legacy.py. The generate_pdf_report +
send_email_report + send_teams_digest chain is the deterministic
plumbing that every task workflow uses to ship its final artifact.

Tools:
    generate_pdf_report     Builds the full PDF (regressions, pies,
                            coverage, bug drafts, patch files)
    send_email_report       SMTP send of latest PDF to TEAM_EMAILS
    send_teams_digest       Short card to the Teams webhook
    tail_nightly_log        Read last N lines of logs/nightly_*.log
    draft_standup_update    5-bullet plain-text summary for standup
    clean_reports_folder    Delete old artifacts, reset STATE
"""
from __future__ import annotations

from tools_legacy import (  # noqa: F401
    generate_pdf_report_tool,
    send_email_report_tool,
    send_teams_digest_tool,
    tail_nightly_log_tool,
    draft_standup_update_tool,
    clean_reports_folder_tool,
)


TOOLS = [
    generate_pdf_report_tool,
    send_email_report_tool,
    send_teams_digest_tool,
    tail_nightly_log_tool,
    draft_standup_update_tool,
    clean_reports_folder_tool,
]

TOOL_NAMES = [
    "generate_pdf_report",
    "send_email_report",
    "send_teams_digest",
    "tail_nightly_log",
    "draft_standup_update",
    "clean_reports_folder",
]
