"""
NAPCO Nucleus — File + Source Control tools.

Thin re-export layer over tools_legacy.py so the agent gets these tools
under the new tools/ package namespace while the underlying code stays
working verbatim. A future pass will migrate implementations inline
here and delete tools_legacy.py.

Tools:
    list_project_files, read_file, write_file, edit_file
    git_diff, git_commit_and_push, recent_commits
    explore_ui   (Playwright accessibility-tree capture for E2E planning)
"""
from __future__ import annotations

from tools_legacy import (  # noqa: F401
    list_project_files_tool,
    read_file_tool,
    write_file_tool,
    edit_file_tool,
    git_diff_tool,
    git_commit_and_push_tool,
    recent_commits_tool,
    explore_ui_tool,
)


TOOLS = [
    list_project_files_tool,
    read_file_tool,
    write_file_tool,
    edit_file_tool,
    git_diff_tool,
    git_commit_and_push_tool,
    recent_commits_tool,
    explore_ui_tool,
]

TOOL_NAMES = [
    "list_project_files",
    "read_file",
    "write_file",
    "edit_file",
    "git_diff",
    "git_commit_and_push",
    "recent_commits",
    "explore_ui",
]
