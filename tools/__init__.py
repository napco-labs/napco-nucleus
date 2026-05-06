"""NAPCO Nucleus — aggregated MCP tool registry.

Each submodule exposes its own TOOLS list and TOOL_NAMES; this package
collects them so the SDK MCP server can be built with one call.

Submodules:
    memory       SQLite-backed activity_logs / requirements_seen / etc.
    requirements Email + Drive ingestion → GitLab publish
    tests        Locust / Newman / pytest / Playwright runners + health probes
    files        list / read / write / edit + Playwright accessibility snapshot
    git          git diff / commit / push / log
    report       PDF / SMTP / Teams / log tail / artifact cleanup

Algorithmic work (failure RCA, standup summaries, regression analysis,
test inventory, known-bug listing) lives in the prompts now — Claude
reads the same JSON files the old tools used to scan and reasons over
them directly. That keeps the tool surface small and lets behavior
evolve via prompt edits instead of code changes.
"""
from __future__ import annotations

from tools.memory             import TOOLS as _MEMORY_TOOLS,    TOOL_NAMES as _MEMORY_NAMES
from tools.requirements       import TOOLS as _REQ_TOOLS,       TOOL_NAMES as _REQ_NAMES
from tools.tests              import TOOLS as _TEST_TOOLS,      TOOL_NAMES as _TEST_NAMES
from tools.files              import TOOLS as _FILE_TOOLS,      TOOL_NAMES as _FILE_NAMES
from tools.git                import TOOLS as _GIT_TOOLS,       TOOL_NAMES as _GIT_NAMES
from tools.report             import TOOLS as _RPT_TOOLS,       TOOL_NAMES as _RPT_NAMES
from tools.docx_writer        import TOOLS as _DOCX_TOOLS,      TOOL_NAMES as _DOCX_NAMES
from tools.verification_email import TOOLS as _VERIFY_TOOLS,    TOOL_NAMES as _VERIFY_NAMES
from tools.aggregation_email  import TOOLS as _AGG_TOOLS,       TOOL_NAMES as _AGG_NAMES

# Teams chat ingest + audio transcription live in Teams-Requirement-Watcher
# (sibling project). TRW runs locally and writes its outputs directly into
# NN's data/requirements/inbox/{chat,meetings}/ so the agent picks them up
# via read_requirement_inbox without NN duplicating TRW's reader logic.

ALL_TOOLS: list = [
    *_MEMORY_TOOLS, *_REQ_TOOLS, *_TEST_TOOLS,
    *_FILE_TOOLS, *_GIT_TOOLS, *_RPT_TOOLS,
    *_DOCX_TOOLS, *_VERIFY_TOOLS, *_AGG_TOOLS,
]
TOOL_NAMES: list[str] = [
    *_MEMORY_NAMES, *_REQ_NAMES, *_TEST_NAMES,
    *_FILE_NAMES, *_GIT_NAMES, *_RPT_NAMES,
    *_DOCX_NAMES, *_VERIFY_NAMES, *_AGG_NAMES,
]
