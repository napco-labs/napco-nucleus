# NAPCO Nucleus

[![MVPAccess CICD](https://github.com/titucse/napco-nucleus/actions/workflows/mvpaccess-cicd.yml/badge.svg)](https://github.com/titucse/napco-nucleus/actions/workflows/mvpaccess-cicd.yml)
[![Requirement Management](https://github.com/titucse/napco-nucleus/actions/workflows/requirement-management.yml/badge.svg)](https://github.com/titucse/napco-nucleus/actions/workflows/requirement-management.yml)
[![Daily Report](https://github.com/titucse/napco-nucleus/actions/workflows/daily-report.yml/badge.svg)](https://github.com/titucse/napco-nucleus/actions/workflows/daily-report.yml)
[![API Functional](https://github.com/titucse/napco-nucleus/actions/workflows/api-functional-test.yml/badge.svg)](https://github.com/titucse/napco-nucleus/actions/workflows/api-functional-test.yml)
[![API Integration](https://github.com/titucse/napco-nucleus/actions/workflows/api-integration-test.yml/badge.svg)](https://github.com/titucse/napco-nucleus/actions/workflows/api-integration-test.yml)
[![API Load](https://github.com/titucse/napco-nucleus/actions/workflows/api-load-test.yml/badge.svg)](https://github.com/titucse/napco-nucleus/actions/workflows/api-load-test.yml)
[![E2E](https://github.com/titucse/napco-nucleus/actions/workflows/e2e-test.yml/badge.svg)](https://github.com/titucse/napco-nucleus/actions/workflows/e2e-test.yml)

AI automation agent for Mohammad Kamrul Hasan at Adaptive Enterprise Limited. Two operational dimensions — Project Management and Test Automation — spanning six scheduled workflows. Modeled on the Digital Deputy architecture.

Uses the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python), which authenticates via the local Claude Code CLI login — no API key required.

## Dimensions and workflows

| Dimension | Workflow | Schedule | File |
|---|---|---|---|
| Project Management | Requirement Management | every 2h 09:00-17:00 BDT (Sun-Thu) | `prompts/requirement_management.md` |
| Project Management | Daily Report | 09:00 BDT daily | `prompts/daily_report.md` |
| Test Automation | API Functional Test | workflow_dispatch | `prompts/api_functional_test.md` |
| Test Automation | API Integration Test | 02:00 BDT daily | `prompts/api_integration_test.md` |
| Test Automation | API Load Test | 03:00 BDT Mondays | `prompts/api_load_test.md` |
| Test Automation | MVP Access E2E Test | 04:00 BDT daily | `prompts/e2e_test.md` |

**One email per day.** The 4 test workflows write their results to memory but do NOT send per-run emails. The Daily Report workflow reads today's `test_run_history` and ships a single consolidated email to the team.

## What it drives

Four sibling test projects under `E:/Projects/`:

- **MVP-Access-API-Test** — Locust load, Newman/Postman API, pytest integration, reporting, email
- **MVP-Access-E2E-Test** — Playwright full E2E suite
- **MVP-Access-Easy-E2E-Test** — Playwright smoke / easy
- **MVP-Access-Release-Test** — Playwright release candidates

Plus the Requirement Management pipeline: client emails (IMAP) + Google Drive audio recordings + PDFs → transcribed via Groq Whisper → split into ~3-hour tasks by Claude → pushed as GitLab issues.

## Prerequisites

1. [Claude Code CLI](https://docs.claude.com/claude-code) installed and logged in (`claude login`).
2. Python 3.10+ (the VM uses `py -3` launcher).
3. The four sibling test projects cloned under `E:/Projects/`.
4. `.env` populated (see `.env.example` for the full contract).

## Setup

```bash
cd E:/Projects/NAPCO-Nucleus
py -3 -m pip install -r requirements.txt
```

## Usage

Scheduled runs fire automatically on the self-hosted Windows runner. For manual / on-demand runs:

```bash
py -3 agent.py --task requirement-management
py -3 agent.py --task daily-report
py -3 agent.py --task api-functional-test
py -3 agent.py --task api-integration-test [--dry-run]
py -3 agent.py --task api-load-test
py -3 agent.py --task e2e-test
```

The `--dry-run` flag sets `NAPCO_NUCLEUS_DRY_RUN=1` and tells the agent to run every step EXCEPT the mutating actions (no SMTP send, no GitLab issue create, no git push).

## Architecture

- `agent.py` — entry point. Loads the shared `prompts/system.md` plus task prompt, registers the MCP tool set, runs one Claude Agent SDK turn, exits.
- `memory.py` — SQLite + FTS5 persistent memory (activity_logs, requirements_seen with fuzzy dedup, test_run_history, email_checkpoints, drive_processed). Committed to the repo as `nucleus_memory.db` so memory travels with `git clone`.
- `tools/` — 36 MCP tools organized into 5 submodules: `memory`, `requirements`, `tests`, `report`, `files`. Claude calls these; they wrap the deterministic helpers.
- `prompts/` — 6 task prompts + shared `system.md`. Each task opens with a mandatory memory check-in so Claude never cold-starts.
- `tools_legacy.py` — the monolithic 30-tool module that `tests.py` / `report.py` / `files.py` currently re-export from. Being migrated inline over time.

See `docs/ARCHITECTURE.md` for the full layout and Phase-by-phase migration notes.
