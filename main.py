"""
AI-powered test orchestration agent for the MVP Access API + E2E test projects.

Uses the Claude Agent SDK (rides on the local Claude Code CLI login — so it
bills against your Claude subscription, not API credits).

Run:
    python main.py "run all tests and email me the report"
    python main.py "review the integration tests for issues"
"""

import os
import sys
import logging
import argparse
import anyio

# Force UTF-8 on Windows console so arrows/emojis in agent output don't crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))
load_dotenv(os.path.join(_HERE, "..", "MVP-Access-API-Test", ".env"))

sys.path.insert(0, _HERE)

from claude_agent_sdk import (  # noqa: E402
    ClaudeAgentOptions,
    ClaudeSDKClient,
    create_sdk_mcp_server,
)
import tools as agent_tools  # noqa: E402

SYSTEM_PROMPT = """You are the MVP Access test-automation agent.

You orchestrate four sibling projects under E:/Projects/:
  - MVP-Access-API-Test         (Locust, Newman, pytest, reporting, email)
  - MVP-Access-E2E-Test         (Playwright — full suite)
  - MVP-Access-Easy-E2E-Test    (Playwright — smoke/easy)
  - MVP-Access-Release-Test     (Playwright — release candidates)

The user will ask you to run tests, review code, or both. Use the available tools
to execute the work yourself — do not describe what the user should do.

Guidelines:
  - When asked for "all tests" or a "full report": run API → Integration → Load
    → E2E (full), then generate the PDF, then email it.
  - Each test tool should be called AT MOST ONCE per run — they are expensive.
  - For code review, use list_project_files + read_file to examine real code,
    then give concrete, file-specific findings.
  - After tests run, interpret failures in plain language before generating
    the report. Flag regressions or suspicious patterns.
  - Always generate the PDF report before emailing.
  - generate_pdf_report now also produces bug-draft markdown and a
    self-healing .patch file (if fixable validation errors were detected).
    Both get attached to the email automatically — mention them in the
    executive summary so developers know to look at the attachments.
  - After emailing, call send_teams_digest to drop a short card in the Teams
    channel (no-ops automatically if TEAMS_WEBHOOK_URL isn't configured).
  - When calling generate_pdf_report, ALWAYS pass a 2-3 paragraph executive
    summary as the `summary` argument. Write it for a developer audience:
      • Paragraph 1 — the headline verdict (what worked, what broke, the
        capacity ceiling if it's a load test). If regressions vs last run are
        detected (the report has a Regressions section), lead with them.
      • Paragraph 2 — the most important specific findings (which endpoints
        regressed, the failure rate at each tier, any clear backend bugs vs.
        load-generator artifacts). Call out any flaky tests surfaced in the
        report so developers know which results to trust.
      • Paragraph 3 (optional) — recommended next steps for the dev team.
    Plain text only, blank line between paragraphs. No markdown.
  - Be concise in status updates. Save detail for the email summary.

Write permissions (write_file, edit_file):
  - Only modify files when the user explicitly asks you to "fix", "apply", "patch",
    "update", "edit", or "change" code. For pure "review", "check", "analyze",
    "look at" requests, report findings WITHOUT writing anything.
  - All four projects are in git, so edits are undoable — but still prefer
    edit_file (targeted) over write_file (whole-file rewrite) when possible.
  - After making edits, summarize what you changed and in which files.
  - Do not commit or push. The user will review and commit the changes themselves.
"""


async def run_agent(user_prompt: str, verbose: bool = True) -> None:
    server = create_sdk_mcp_server(
        name="mvp-tester",
        version="1.0.0",
        tools=agent_tools.ALL_TOOLS,
    )

    allowed = [f"mcp__mvp-tester__{n}" for n in agent_tools.TOOL_NAMES]

    # Point at the user's installed claude.exe (which is logged in), not the
    # SDK's bundled copy (which has no login session). Override with
    # CLAUDE_CLI_PATH if claude.exe lives somewhere non-standard.
    user_claude = os.getenv(
        "CLAUDE_CLI_PATH",
        os.path.expandvars(r"%USERPROFILE%\.local\bin\claude.exe"),
    )

    options_kwargs = {
        "system_prompt": SYSTEM_PROMPT,
        "mcp_servers": {"mvp-tester": server},
        "allowed_tools": allowed,
    }
    if os.path.exists(user_claude):
        options_kwargs["cli_path"] = user_claude
    options = ClaudeAgentOptions(**options_kwargs)

    async with ClaudeSDKClient(options=options) as client:
        await client.query(user_prompt)
        async for msg in client.receive_response():
            if verbose:
                # Pretty-print text blocks; skip low-value events
                text = _extract_text(msg)
                if text:
                    print(text)


def _extract_text(msg) -> str:
    """Best-effort extraction of displayable text from an SDK message object."""
    content = getattr(msg, "content", None)
    if content is None and isinstance(msg, dict):
        content = msg.get("content")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                t = getattr(block, "text", None)
                if t:
                    parts.append(t)
        return "\n".join(p for p in parts if p)
    if isinstance(content, str):
        return content
    return ""


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="MVP Access AI test agent (Claude Agent SDK)")
    parser.add_argument(
        "prompt",
        nargs="?",
        default="Run all tests (API, Integration, Load, E2E full suite), generate the PDF report, and email it to the team.",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    print(f"\n=== AI Agent: {args.prompt}\n")
    anyio.run(run_agent, args.prompt, not args.quiet)
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
