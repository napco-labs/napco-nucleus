"""NAPCO Nucleus — aggregated MCP tool registry.

Each submodule exposes its own TOOLS list and TOOL_NAMES; this package
collects them so the SDK MCP server can be built with one call.

Phase 2 scaffold: only memory tools wired in. Phase 4 will add
requirements, tests, report, files.
"""
from __future__ import annotations

from tools.memory import TOOLS as _MEMORY_TOOLS, TOOL_NAMES as _MEMORY_NAMES

# Phase 4 additions (imports wired when modules land):
# from tools.requirements import TOOLS as _REQ_TOOLS, TOOL_NAMES as _REQ_NAMES
# from tools.tests        import TOOLS as _TEST_TOOLS, TOOL_NAMES as _TEST_NAMES
# from tools.report       import TOOLS as _RPT_TOOLS, TOOL_NAMES as _RPT_NAMES
# from tools.files        import TOOLS as _FILE_TOOLS, TOOL_NAMES as _FILE_NAMES

ALL_TOOLS: list = [*_MEMORY_TOOLS]
TOOL_NAMES: list[str] = [*_MEMORY_NAMES]
