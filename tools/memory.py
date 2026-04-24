"""
NAPCO Nucleus — MCP tools exposing the SQLite memory module to Claude.

Read tools for recall + search. Writes happen as side-effects of
action tools (poll_requirement_emails, run_*_tests, etc.).

Tools exposed:
    recall_activity           — "What did I do recently on this task?"
    search_requirements       — "Have I seen this requirement before?"
    recall_test_runs          — "How did the last N runs of this suite do?"
    remember_requirement      — Explicitly record a requirement encountered
                                (used for requirements the agent chose NOT
                                to publish to GitLab — e.g., out of scope).
    memory_stats              — Row counts per table (health check).
"""
from __future__ import annotations

import json

from claude_agent_sdk import tool

import memory


def _text(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


@tool(
    "recall_activity",
    "Fetch recent activity_logs entries, newest first. task_name optionally "
    "filters (e.g., 'api-functional-test:run'). since is an ISO-8601 lower "
    "bound. limit caps rows (default 50).",
    {"task_name": str, "since": str, "limit": int},
)
async def recall_activity_tool(args):
    return _text(memory.recall_activity(
        task_name=args.get("task_name") or None,
        since=args.get("since") or None,
        limit=int(args.get("limit") or 50),
    ))


@tool(
    "search_requirements",
    "Full-text search over requirements_seen using SQLite FTS5 (Porter "
    "stemming, case-insensitive). Use BEFORE publishing a new task to "
    "GitLab to check if you've seen a near-duplicate before. Returns "
    "the stored title, source, summary, GitLab issue info (if any), and "
    "a snippet showing the matched phrase.",
    {"query": str, "limit": int},
)
async def search_requirements_tool(args):
    return _text(memory.search_requirements(
        query=args.get("query", ""),
        limit=int(args.get("limit") or 20),
    ))


@tool(
    "recall_test_runs",
    "Recent test-suite runs, newest first. task_name filters to one "
    "workflow (e.g., 'api-functional-test', 'e2e-test'). Returns ts, "
    "totals, duration, regressions, and PDF path so the daily report "
    "can cite exact run history.",
    {"task_name": str, "since": str, "limit": int},
)
async def recall_test_runs_tool(args):
    return _text(memory.recall_test_runs(
        task_name=args.get("task_name") or None,
        since=args.get("since") or None,
        limit=int(args.get("limit") or 20),
    ))


@tool(
    "remember_requirement",
    "Explicitly record that a requirement was encountered but intentionally "
    "NOT published to GitLab (e.g., out of scope, needs clarification, "
    "scheduled for later). The title is normalized so near-duplicates "
    "collapse. source is 'email', 'meetings', 'chat', or 'documents'. "
    "source_ref is the rel_path of the source file.",
    {"title": str, "source": str, "source_ref": str, "summary": str},
)
async def remember_requirement_tool(args):
    ok = memory.remember_requirement(
        title=args.get("title", ""),
        source=args.get("source", ""),
        source_ref=args.get("source_ref", ""),
        summary=args.get("summary", ""),
    )
    return _text({"remembered": ok})


@tool(
    "memory_stats",
    "Row counts per memory table. Use for health checks in the daily "
    "report and for confirming the DB is being written to.",
    {},
)
async def memory_stats_tool(args):
    return _text(memory.stats())


TOOLS = [
    recall_activity_tool,
    search_requirements_tool,
    recall_test_runs_tool,
    remember_requirement_tool,
    memory_stats_tool,
]

TOOL_NAMES = [
    "recall_activity",
    "search_requirements",
    "recall_test_runs",
    "remember_requirement",
    "memory_stats",
]
