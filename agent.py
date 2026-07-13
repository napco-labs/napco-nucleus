"""
NAPCO Nucleus — single-agent entry point.

Invoked by GitHub Actions workflows with a --task flag. Assembles the
system prompt from prompts/system.md + prompts/<task>.md, registers
the MCP tool set, runs one agent turn against the Claude Agent SDK,
exits.

Usage:
    python agent.py --task requirement-management
    python agent.py --task daily-report
    python agent.py --task api-functional-test
    python agent.py --task api-integration-test
    python agent.py --task api-load-test
    python agent.py --task e2e-test [--dry-run]

Exit codes:
    0 — clean finish (work done, or intentionally skipped)
    1 — error (auth, config, unreachable API, an SDK error result, or a work
        task that made zero tool calls — e.g. an expired token — so the caller
        can retry/escalate instead of treating an empty run as success)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

import anyio
from dotenv import load_dotenv


# Force UTF-8 output so Claude's arrows / em-dashes / non-Latin text
# don't crash the Windows cp1252 console. Safe no-op on Linux.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


_HERE = os.path.dirname(os.path.abspath(__file__))
# NN owns its own secrets — Digital-Deputy-style. .env at the project
# root is the single source of truth for SMTP, IMAP, GitLab, Google
# Drive, Groq, and Teams creds. override=True so a value in .env wins
# over an empty / placeholder env var inherited from the workflow shell.
load_dotenv(os.path.join(_HERE, ".env"), override=True)
sys.path.insert(0, _HERE)


TASKS = {
    "requirement-management",
    "verify_session",
    "agent_mode",
    "daily-report-detailed",
    "daily-report-summary",
    "api-functional-test",
    "api-integration-test",
    "api-load-test",
    "e2e-test",
}


# Tasks that MUST do real work via MCP tools on any healthy run. Even a run that
# finds zero requirements still calls several tools (memory check-in,
# read_pull_session, log_activity, ...). Zero tool calls on one of these means
# the agent never actually ran (auth/token failure) — see main().
_WORK_TASKS = {
    "requirement-management",
    "verify_session",
    "daily-report-detailed",
    "daily-report-summary",
    "api-functional-test",
    "api-integration-test",
    "api-load-test",
    "e2e-test",
}


TASK_KICKOFF = {
    "requirement-management":
        "Run the Requirement Management loop now. Follow the prompt: "
        "memory check-in, poll email + Drive, read the inbox, split "
        "requirements into 3-hour tasks, publish to GitLab, log, exit.",
    "verify_session":
        "Run the Verify Pull Session task now. Follow the prompt: "
        "memory check-in, read_pull_session, identify distinct client "
        "requirements from the consolidated session doc, write the "
        "Requirements Verification .docx, draft ONE client email "
        "(push to the user's IMAP Drafts folder), log, exit. Do NOT "
        "call the auto-poll tools (poll_requirement_emails / "
        "ingest_drive_files / read_requirement_inbox), do NOT draft "
        "the records-aggregation email.",
    "agent_mode":
        "(operator instruction supplied via --input or AGENT_INPUT env)",
    "daily-report-detailed":
        "Build today's Detailed Daily Test Report. Follow the prompt: "
        "memory check-in, read artifacts from the 4 test projects, "
        "compose the 6-section detailed report with pie charts, generate "
        "the PDF, email it to the FULL TEAM (TEAM_EMAILS), post a Teams "
        "digest, exit.",
    "daily-report-summary":
        "Build today's Executive Summary. Follow the prompt: memory "
        "check-in, compose the 7-block dashboard (3-4 lines each), "
        "generate the SHORT PDF, email it to LEADERSHIP ONLY "
        "(SUMMARY_EMAILS — khasan + assad), exit.",
    "api-functional-test":
        "Run the API Functional Test suite now. Pull the latest code if "
        "needed, execute run_api_tests, analyze failures, generate the "
        "PDF report, email it. Log the result to memory.",
    "api-integration-test":
        "Run the API Integration Test suite now. Execute "
        "run_integration_tests, compare with last run for regressions, "
        "generate the PDF report, email it. Log the result to memory.",
    "api-load-test":
        "Run the API Load Test suite now. Execute run_load_tests (multi-"
        "tier), find the capacity ceiling, generate the PDF report, "
        "email it. Log the result to memory.",
    "e2e-test":
        "Run the MVP Access E2E Test suite now. Execute run_e2e_tests, "
        "attach failure screenshots, generate the PDF report, email it "
        "to Dev and QA. Log the result to memory.",
}


def _load_prompt(task: str) -> str:
    with open(os.path.join(_HERE, "prompts", "system.md"), "r", encoding="utf-8") as f:
        system = f.read()
    task_file = os.path.join(_HERE, "prompts", task.replace("-", "_") + ".md")
    with open(task_file, "r", encoding="utf-8") as f:
        task_prompt = f.read()
    return system.rstrip() + "\n\n---\n\n" + task_prompt


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


def _count_tool_uses(msg) -> int:
    """Count tool_use blocks in an SDK message (assistant tool invocations)."""
    content = getattr(msg, "content", None)
    if content is None and isinstance(msg, dict):
        content = msg.get("content")
    if not isinstance(content, list):
        return 0
    n = 0
    for block in content:
        btype = (block.get("type") if isinstance(block, dict)
                 else getattr(block, "type", None))
        if btype == "tool_use" or type(block).__name__ == "ToolUseBlock":
            n += 1
    return n


def _result_error(msg):
    """If msg is a terminal SDK result message, return True/False for whether it
    carries an error flag; return None when msg isn't a result message."""
    is_result = (type(msg).__name__ == "ResultMessage"
                 or (isinstance(msg, dict) and msg.get("type") == "result"))
    if not is_result:
        return None
    is_err = getattr(msg, "is_error", None)
    if is_err is None and isinstance(msg, dict):
        is_err = msg.get("is_error")
    subtype = getattr(msg, "subtype", None)
    if subtype is None and isinstance(msg, dict):
        subtype = msg.get("subtype")
    if is_err is None and subtype is None:
        return None
    if is_err:
        return True
    # subtypes other than success (e.g. error_max_turns, error_during_execution)
    return bool(subtype) and subtype != "success"


async def run_agent(task: str, dry_run: bool) -> dict | None:
    # Code-level dry-run safety: tools check this env var and short-circuit
    # any mutating path (SMTP send, GitLab issue create, etc.).
    if dry_run:
        os.environ["NAPCO_NUCLEUS_DRY_RUN"] = "1"

    from claude_agent_sdk import (
        ClaudeAgentOptions,
        ClaudeSDKClient,
        create_sdk_mcp_server,
    )

    import napco_config as nucleus_config
    from tools import ALL_TOOLS, TOOL_NAMES

    server = create_sdk_mcp_server(
        name="napco-nucleus",
        version="0.1.0",
        tools=ALL_TOOLS,
    )
    allowed = [f"mcp__napco-nucleus__{n}" for n in TOOL_NAMES]
    allowed.extend(["WebSearch", "WebFetch"])

    system_prompt = _load_prompt(task)
    # Calibration feedback — only injected for identify-style tasks
    # that actually emit confidence numbers. The advice is empty until
    # enough review decisions accumulate (default >=10 per bucket).
    if task == "verify_session":
        try:
            import memory as _memory  # lazy
            advice = _memory.calibration_advice(min_decisions=10)
        except Exception:
            advice = ""
        if advice:
            system_prompt += "\n\n---\n\n" + advice
    if dry_run:
        system_prompt += (
            "\n\n---\n\n"
            "**DRY-RUN MODE.** Perform every step of the loop EXCEPT the "
            "actual mutations (no SMTP send, no GitLab issue create, no "
            "git commit/push). Simulate by printing what would have "
            "happened. Still call memory recall / search tools and "
            "log_activity so the DB reflects a real dry-run."
        )

    options_kwargs: dict = {
        "system_prompt": system_prompt,
        "mcp_servers": {"napco-nucleus": server},
        "allowed_tools": allowed,
    }
    # Pin the model for requirement identification — Titu wants Opus doing
    # the verify_session identify step (highest-quality extraction from the
    # combined all-dev pull-session doc). Bumped 4.7 -> 4.8 2026-07-02.
    # Override per-deploy via NUCLEUS_AGENT_MODEL (set it empty to fall
    # back to the SDK default).
    agent_model = os.environ.get("NUCLEUS_AGENT_MODEL", "claude-opus-4-8").strip()
    if agent_model:
        options_kwargs["model"] = agent_model
    cli_path = nucleus_config.claude_cli_path()
    if cli_path:
        options_kwargs["cli_path"] = cli_path

    options = ClaudeAgentOptions(**options_kwargs)

    if task == "agent_mode":
        # The operator's free-form instruction is the kickoff message.
        user_input = (os.environ.get("AGENT_INPUT") or "").strip()
        if not user_input:
            print("agent_mode: --input was empty and AGENT_INPUT env "
                  "is not set. Nothing to do.", file=sys.stderr)
            return
        kickoff = user_input
    else:
        kickoff = TASK_KICKOFF[task]
    tool_calls = 0
    result_error = False
    async with ClaudeSDKClient(options=options) as client:
        await client.query(kickoff)
        async for msg in client.receive_response():
            tool_calls += _count_tool_uses(msg)
            err = _result_error(msg)
            if err is not None:
                result_error = err
            text = _extract_text(msg)
            if text:
                print(text)
    return {"tool_calls": tool_calls, "result_error": result_error}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="NAPCO Nucleus agent entry point")
    parser.add_argument("--task", required=True, choices=sorted(TASKS))
    parser.add_argument("--dry-run", action="store_true",
                        help="Run the loop but skip mutating actions.")
    parser.add_argument("--input", default=None,
                        help="Free-form instruction for agent_mode. "
                             "Alternative: set AGENT_INPUT env. Ignored "
                             "for non-agent_mode tasks.")
    args = parser.parse_args()

    # For agent_mode, expose the instruction via env so run_agent can
    # pick it up without changing its signature (which other tasks rely on).
    if args.task == "agent_mode" and args.input:
        os.environ["AGENT_INPUT"] = args.input

    print(f"=== NAPCO Nucleus: task={args.task} dry_run={args.dry_run} ===\n", flush=True)
    status = anyio.run(run_agent, args.task, args.dry_run)
    print("\n=== Done ===", flush=True)

    # Success is NOT "the loop finished" — an expired OAuth/Max token or a 401
    # surfaces as an error result (or as the model emitting text and doing
    # nothing), and used to exit 0. That produced silent empty Gmail drafts that
    # looked like success for a week (see collect_central.py). Fail loudly so the
    # caller (collect_central / draft-loop) retries or escalates instead:
    #   * an SDK result flagged is_error, or
    #   * a work task that made ZERO tool calls (a healthy run always calls
    #     several tools even when it finds no requirements).
    if status is None:
        return 0  # agent_mode with no input / intentionally-skipped run
    if status.get("result_error"):
        print("agent.py: SDK returned an error result — failing so the caller "
              "can escalate.", file=sys.stderr)
        return 1
    if args.task in _WORK_TASKS and status.get("tool_calls", 0) == 0:
        print("agent.py: task made ZERO tool calls — the agent did no work "
              "(likely expired token / 401 / refusal). Failing so the caller "
              "escalates instead of sending an empty result.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
