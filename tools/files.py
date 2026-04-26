"""
NAPCO Nucleus — File + UI inspection tools.

Mechanical I/O wrappers — Claude does the reasoning, these tools just
move bytes. list/read/write/edit operate on the four sibling project
roots; explore_ui spawns Playwright headless to dump an accessibility
snapshot before Claude writes a new spec.

Tools:
    list_project_files   glob a directory in a sibling project
    read_file            read up to 200KB from a sibling file
    write_file           overwrite (creates parents)
    edit_file            exact-match string replacement (must be unique)
    explore_ui           Playwright headless → accessibility tree JSON
"""
from __future__ import annotations

import glob
import json
import logging
import os
import subprocess

from claude_agent_sdk import tool

from tools._shared import (
    E2E_PROJECTS,
    PROJECT_PATHS,
    _text,
    _resolve_in_project,
)

logger = logging.getLogger(__name__)


# ─── list_project_files ──────────────────────────────────────────────
@tool(
    "list_project_files",
    "List files under a sibling project (api-test, e2e-full, e2e-easy, e2e-release). directory is relative to project root. pattern defaults to '*.py'.",
    {"project": str, "directory": str, "pattern": str},
)
async def list_project_files_tool(args):
    full = _resolve_in_project(args["project"], args["directory"])
    if not full:
        return _text({"error": "Invalid project or directory."})
    if not os.path.isdir(full):
        return _text({"error": f"Not a directory: {args['directory']}"})
    pattern = args.get("pattern") or "*.py"
    matches = glob.glob(os.path.join(full, "**", pattern), recursive=True)
    root = PROJECT_PATHS[args["project"]]
    return _text([os.path.relpath(m, root).replace("\\", "/") for m in matches][:200])


# ─── read_file ───────────────────────────────────────────────────────
@tool(
    "read_file",
    "Read a file under a sibling project for code review. Truncates at 200KB.",
    {"project": str, "path": str},
)
async def read_file_tool(args):
    full = _resolve_in_project(args["project"], args["path"])
    if not full:
        return _text({"error": "Invalid project or path."})
    if not os.path.isfile(full):
        return _text({"error": f"File not found: {args['path']}"})
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(200_000)
    return _text({
        "project": args["project"],
        "path": args["path"],
        "content": content,
        "truncated": len(content) == 200_000,
    })


# ─── write_file ──────────────────────────────────────────────────────
@tool(
    "write_file",
    "Write (or overwrite) a full file under a sibling project. Creates parent dirs as needed. Use for whole-file rewrites. For small edits, prefer edit_file.",
    {"project": str, "path": str, "content": str},
)
async def write_file_tool(args):
    full = _resolve_in_project(args["project"], args["path"])
    if not full:
        return _text({"error": "Invalid project or path."})
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="") as f:
        f.write(args["content"])
    return _text({
        "project": args["project"],
        "path": args["path"],
        "bytes_written": len(args["content"].encode("utf-8")),
        "action": "written",
    })


# ─── edit_file ───────────────────────────────────────────────────────
@tool(
    "edit_file",
    "Edit a file by exact string replacement. old_string must match exactly once. Safer than write_file for small changes.",
    {"project": str, "path": str, "old_string": str, "new_string": str},
)
async def edit_file_tool(args):
    full = _resolve_in_project(args["project"], args["path"])
    if not full:
        return _text({"error": "Invalid project or path."})
    if not os.path.isfile(full):
        return _text({"error": f"File not found: {args['path']}"})
    with open(full, "r", encoding="utf-8") as f:
        content = f.read()
    old = args["old_string"]
    new = args["new_string"]
    count = content.count(old)
    if count == 0:
        return _text({"error": "old_string not found in file."})
    if count > 1:
        return _text({"error": f"old_string matches {count} places — make it unique."})
    with open(full, "w", encoding="utf-8", newline="") as f:
        f.write(content.replace(old, new, 1))
    return _text({
        "project": args["project"],
        "path": args["path"],
        "action": "edited",
    })


# ─── explore_ui ──────────────────────────────────────────────────────
@tool(
    "explore_ui",
    "Navigate to a page in the MVP Access app and return its accessibility snapshot "
    "(roles, names, states). Use this BEFORE writing any E2E test so you base selectors "
    "on real DOM, not guesses. 'suite' is full|easy|release (determines baseURL). "
    "'path' is the URL path e.g. '/Default.aspx'. If 'login_first' is true (default), "
    "the agent logs in before navigating.",
    {"suite": str, "path": str, "login_first": bool},
)
async def explore_ui_tool(args):
    suite = args.get("suite", "full")
    project_dir = E2E_PROJECTS.get(suite)
    if not project_dir or not os.path.isdir(project_dir):
        return _text({"error": f"Unknown E2E suite: {suite}"})

    url_path = args.get("path", "/")
    login_first = args.get("login_first", True)

    script = """
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const baseURL = process.env.BASE_URL || 'https://staging.mvpaccess.online';
"""
    if login_first:
        script += """
  await page.goto(baseURL + '/Login.aspx');
  await page.locator('#txtAccount').fill(process.env.COMPANY_ID || '');
  await page.locator('#txtUserName').fill(process.env.USER_ID || '');
  await page.locator('#txtPassword').fill(process.env.PASSWORD || '');
  await page.evaluate(() => {
    const btn = document.getElementById('btnLogin');
    if (btn) btn.click();
  });
  await page.waitForURL(url => !url.toString().includes('Login.aspx'), { timeout: 15000 }).catch(() => {});
  await page.waitForLoadState('networkidle').catch(() => {});
"""
    script += f"""
  await page.goto(baseURL + '{url_path}');
  await page.waitForLoadState('networkidle').catch(() => {{}});
  const snapshot = await page.accessibility.snapshot();
  console.log(JSON.stringify(snapshot, null, 2));
  await browser.close();
}})();
"""
    try:
        proc = subprocess.run(
            ["node", "-e", script],
            cwd=project_dir,
            capture_output=True, text=True,
            timeout=60, shell=True,
            env={**os.environ, "NODE_PATH": os.path.join(project_dir, "node_modules")},
        )
        stdout = (proc.stdout or "").strip()
        if proc.returncode != 0:
            return _text({
                "error": "Playwright exploration failed",
                "stderr": (proc.stderr or "")[-500:],
                "stdout": stdout[-500:],
            })
        try:
            tree = json.loads(stdout)
        except json.JSONDecodeError:
            tree = None
        return _text({
            "suite": suite,
            "path": url_path,
            "logged_in": login_first,
            "accessibility_tree": tree,
            "raw_length": len(stdout),
        })
    except subprocess.TimeoutExpired:
        return _text({"error": "Timed out exploring the UI (60s limit)"})
    except Exception as e:
        return _text({"error": str(e)})


TOOLS = [
    list_project_files_tool,
    read_file_tool,
    write_file_tool,
    edit_file_tool,
    explore_ui_tool,
]

TOOL_NAMES = [
    "list_project_files",
    "read_file",
    "write_file",
    "edit_file",
    "explore_ui",
]
