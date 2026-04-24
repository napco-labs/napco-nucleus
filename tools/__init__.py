"""NAPCO Nucleus — aggregated MCP tool registry.

Each submodule exposes its own TOOLS list and TOOL_NAMES; this package
collects them so the SDK MCP server can be built with one call.

All 5 submodules wired. Requirements + memory are native NAPCO code.
Files + tests + report re-export from tools_legacy.py pending a later
Claude-first rewrite (e.g., stripping the hardcoded RCA cascade in
analyze_test_failures).
"""
from __future__ import annotations

from tools.memory       import TOOLS as _MEMORY_TOOLS, TOOL_NAMES as _MEMORY_NAMES
from tools.requirements import TOOLS as _REQ_TOOLS,    TOOL_NAMES as _REQ_NAMES
from tools.tests        import TOOLS as _TEST_TOOLS,   TOOL_NAMES as _TEST_NAMES
from tools.report       import TOOLS as _RPT_TOOLS,    TOOL_NAMES as _RPT_NAMES
from tools.files        import TOOLS as _FILE_TOOLS,   TOOL_NAMES as _FILE_NAMES

ALL_TOOLS: list = [
    *_MEMORY_TOOLS, *_REQ_TOOLS, *_TEST_TOOLS, *_RPT_TOOLS, *_FILE_TOOLS,
]
TOOL_NAMES: list[str] = [
    *_MEMORY_NAMES, *_REQ_NAMES, *_TEST_NAMES, *_RPT_NAMES, *_FILE_NAMES,
]
