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
import os

from claude_agent_sdk import tool

import memory


def _eval_mode() -> bool:
    """True when NAPCO_NUCLEUS_EVAL_MODE=1 — the eval harness sets this
    so identify runs don't poison requirements_seen / activity_logs."""
    return (os.environ.get("NAPCO_NUCLEUS_EVAL_MODE") or "").strip() == "1"


def _text(payload) -> dict:
    # ensure_ascii=False so Bangla reaches the agent as real UTF-8, not
    # \uXXXX escapes it can't decode in-sandbox (see requirements.py _text).
    return {"content": [{"type": "text",
                         "text": json.dumps(payload, ensure_ascii=False,
                                            default=str)}]}


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
    "source_ref is the rel_path of the source file. client_name "
    "(optional) is the client this requirement belongs to — inferred "
    "from the source channel (email sender domain, chat group, call "
    "metadata). When set, the requirement contributes to "
    "get_client_history for context-aware identification next time.",
    {"title": str, "source": str, "source_ref": str, "summary": str,
     "client_name": str},
)
async def remember_requirement_tool(args):
    if _eval_mode():
        # Eval harness: pretend success so the verify_session flow
        # completes normally, but do NOT write to requirements_seen.
        # Otherwise re-running the same fixture would dedup against
        # itself on the second run.
        return _text({"remembered": False, "eval_mode": True,
                      "note": "skipped DB write (NAPCO_NUCLEUS_EVAL_MODE=1)"})
    ok = memory.remember_requirement(
        title=args.get("title", ""),
        source=args.get("source", ""),
        source_ref=args.get("source_ref", ""),
        summary=args.get("summary", ""),
        client_name=args.get("client_name") or None,
    )
    return _text({"remembered": ok})


@tool(
    "get_client_history",
    "Recent requirements previously identified for one client. Use "
    "this as CONTEXT during step 2 (identify) — not for dedup. Lets "
    "you spot recurring asks the client always raises (e.g. 'they "
    "always want audit logging — flag if missing this session') and "
    "tell follow-ups apart from net-new asks. Match is "
    "case-insensitive on client_name. Returns up to `limit` rows "
    "(default 20), most recent first.",
    {"client_name": str, "limit": int},
)
async def get_client_history_tool(args):
    raw_limit = args.get("limit") or 20
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = 20
    rows = memory.get_client_history(
        client_name=args.get("client_name") or "",
        limit=limit,
    )
    return _text({"client_name": args.get("client_name") or "",
                  "count": len(rows), "requirements": rows})


@tool(
    "get_open_items",
    "Cross-session continuity: requirements drafted to a client "
    "recently but NOT yet confirmed (pending or unclear status). Call "
    "during identify, AFTER get_client_history, to see what's still "
    "in flight. If today's input references one of these items (same "
    "topic, same scope) treat it as a follow-up, not a net-new ask — "
    "and update the existing requirement's confirmation_status if the "
    "client now confirmed/changed it. Filters: client_name "
    "(case-insensitive exact match; omit for all clients), "
    "max_age_days (default 30 — items older are stale, not "
    "in-flight), limit (default 50).",
    {"client_name": str, "max_age_days": int, "limit": int},
)
async def get_open_items_tool(args):
    raw_age = args.get("max_age_days") or 30
    raw_limit = args.get("limit") or 50
    try:
        max_age = int(raw_age)
    except (TypeError, ValueError):
        max_age = 30
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = 50
    rows = memory.open_items(
        client_name=args.get("client_name") or None,
        max_age_days=max_age,
        limit=limit,
    )
    return _text({"client_name": args.get("client_name") or "",
                  "max_age_days": max_age,
                  "count": len(rows), "open_items": rows})


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
    get_client_history_tool,
    get_open_items_tool,
    memory_stats_tool,
]

TOOL_NAMES = [
    "recall_activity",
    "search_requirements",
    "recall_test_runs",
    "remember_requirement",
    "get_client_history",
    "get_open_items",
    "memory_stats",
]
