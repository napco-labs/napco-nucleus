"""
NAPCO Nucleus — Source-control tools.

Mechanical wrappers around the `git` CLI. Claude reads the diff and
decides what to commit; these tools just shell out.

Tools:
    git_diff             show uncommitted changes (stat + first 200 lines)
    git_commit_and_push  add -A, commit with given message, push
    recent_commits       last N commits across one of the projects
"""
from __future__ import annotations

import logging
import os
import subprocess

from claude_agent_sdk import tool

from tools._shared import PROJECT_PATHS, _text

logger = logging.getLogger(__name__)


def _project_map_with_self() -> dict:
    """PROJECT_PATHS plus 'ai-agent' → NN's own root, used by git tools."""
    m = dict(PROJECT_PATHS)
    m["ai-agent"] = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return m


# ─── git_diff ────────────────────────────────────────────────────────
@tool(
    "git_diff",
    "Show uncommitted changes in a project — useful after the agent edits code so the user can review. 'project' one of: api-test, e2e-full, e2e-easy, e2e-release, ai-agent. Returns up to ~200 lines of diff.",
    {"project": str},
)
async def git_diff_tool(args):
    project_map = _project_map_with_self()
    root = project_map.get(args["project"])
    if not root or not os.path.isdir(root):
        return _text({"error": f"Unknown project: {args['project']}"})
    try:
        proc = subprocess.run(
            ["git", "diff", "--stat"], cwd=root,
            capture_output=True, text=True, timeout=10,
        )
        proc2 = subprocess.run(
            ["git", "diff"], cwd=root,
            capture_output=True, text=True, timeout=10,
        )
        stat = proc.stdout or "(no changes)"
        diff = (proc2.stdout or "")
        diff_preview = "\n".join(diff.splitlines()[:200])
        truncated = len(diff.splitlines()) > 200
        return _text({
            "project": args["project"], "root": root,
            "stat": stat, "diff": diff_preview, "truncated": truncated,
        })
    except Exception as e:
        return _text({"error": str(e)})


# ─── git_commit_and_push ─────────────────────────────────────────────
@tool(
    "git_commit_and_push",
    "Commit the agent's pending changes in a project and push. Requires a commit message from the user (or you can infer one from the changes). Never use without user's explicit request. 'project' one of: api-test, e2e-full, e2e-easy, e2e-release, ai-agent.",
    {"project": str, "message": str},
)
async def git_commit_and_push_tool(args):
    project_map = _project_map_with_self()
    root = project_map.get(args["project"])
    if not root or not os.path.isdir(root):
        return _text({"error": f"Unknown project: {args['project']}"})
    message = (args.get("message") or "").strip()
    if not message:
        return _text({"error": "commit message required"})
    try:
        r1 = subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, text=True, timeout=10)
        if r1.returncode != 0:
            return _text({"step": "add", "error": r1.stderr})
        r2 = subprocess.run(
            ["git", "commit", "-m", message], cwd=root,
            capture_output=True, text=True, timeout=10,
        )
        if "nothing to commit" in (r2.stdout + r2.stderr).lower():
            return _text({"committed": False, "reason": "no changes to commit"})
        if r2.returncode != 0:
            return _text({"step": "commit", "error": r2.stderr})
        r3 = subprocess.run(["git", "push"], cwd=root, capture_output=True, text=True, timeout=60)
        return _text({
            "committed": True,
            "pushed": r3.returncode == 0,
            "commit_output": r2.stdout[-300:],
            "push_output": (r3.stdout + r3.stderr)[-300:],
        })
    except Exception as e:
        return _text({"error": str(e)})


# ─── recent_commits ──────────────────────────────────────────────────
@tool(
    "recent_commits",
    "Show the last N git commits across one of the projects — useful for 'what changed this week' status updates. 'project' one of: api-test, e2e-full, e2e-easy, e2e-release, ai-agent. Default count=10.",
    {"project": str, "count": int},
)
async def recent_commits_tool(args):
    project_map = _project_map_with_self()
    root = project_map.get(args["project"])
    if not root or not os.path.isdir(root):
        return _text({"error": f"Unknown project: {args['project']}"})
    count = int(args.get("count") or 10)
    try:
        proc = subprocess.run(
            ["git", "log", f"-{count}", "--pretty=format:%h|%an|%ar|%s"],
            cwd=root, capture_output=True, text=True, timeout=10,
        )
        commits = []
        for line in (proc.stdout or "").splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({"sha": parts[0], "author": parts[1],
                                "when": parts[2], "message": parts[3]})
        return _text({"project": args["project"], "commits": commits})
    except Exception as e:
        return _text({"error": str(e)})


TOOLS = [
    git_diff_tool,
    git_commit_and_push_tool,
    recent_commits_tool,
]

TOOL_NAMES = [
    "git_diff",
    "git_commit_and_push",
    "recent_commits",
]
