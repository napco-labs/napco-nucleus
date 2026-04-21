# MVP Access AI Agent

[![Build + Deploy](https://github.com/titucse/MVP-Access-AI-Agent/actions/workflows/build-deploy.yml/badge.svg)](https://github.com/titucse/MVP-Access-AI-Agent/actions/workflows/build-deploy.yml)
[![Load Test](https://github.com/titucse/MVP-Access-AI-Agent/actions/workflows/load-test.yml/badge.svg)](https://github.com/titucse/MVP-Access-AI-Agent/actions/workflows/load-test.yml)
[![API Functional](https://github.com/titucse/MVP-Access-AI-Agent/actions/workflows/api-functional-test.yml/badge.svg)](https://github.com/titucse/MVP-Access-AI-Agent/actions/workflows/api-functional-test.yml)
[![API Integration](https://github.com/titucse/MVP-Access-AI-Agent/actions/workflows/integration-test.yml/badge.svg)](https://github.com/titucse/MVP-Access-AI-Agent/actions/workflows/integration-test.yml)
[![E2E](https://github.com/titucse/MVP-Access-AI-Agent/actions/workflows/e2e-test.yml/badge.svg)](https://github.com/titucse/MVP-Access-AI-Agent/actions/workflows/e2e-test.yml)
[![Daily Digest](https://github.com/titucse/MVP-Access-AI-Agent/actions/workflows/api-digest.yml/badge.svg)](https://github.com/titucse/MVP-Access-AI-Agent/actions/workflows/api-digest.yml)

AI-powered test orchestration agent for the MVP Access API + E2E test projects.

Uses the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python),
which authenticates via the local Claude Code CLI login — no API key required.

## What it does

Given a natural-language instruction, the agent drives the four sibling test
projects to run tests, review code, generate a PDF report, and email it to the team:

- **MVP-Access-API-Test** — Locust load tests, Newman/Postman API tests, pytest integration tests, reporting, email
- **MVP-Access-E2E-Test** — Playwright full E2E suite
- **MVP-Access-Easy-E2E-Test** — Playwright smoke/easy suite
- **MVP-Access-Release-Test** — Playwright release-candidate suite

## Prerequisites

1. [Claude Code CLI](https://docs.claude.com/claude-code) installed and logged in (`claude login`).
2. Python 3.10+.
3. The four sibling test projects cloned alongside this one under `E:/Projects/`.
4. `MVP-Access-API-Test/.env` populated (provides SMTP, `TEAM_EMAILS`, API creds).

## Setup

```bash
cd E:\Projects\MVP-Access-AI-Agent
pip install -r requirements.txt
```

## Usage

Either double-click `run_agent.bat` for the default full cycle, or from a terminal:

```bash
# Full cycle (API + integration + load + E2E + PDF + email) — ~30+ min
python main.py

# Specific prompts
python main.py "Review test_integration.py and tell me what's missing"
python main.py "Run the API tests and summarize the failures"
python main.py "Run the easy E2E suite and email the report"
```

## Architecture

- `main.py` — entry point. Creates an in-process MCP server with the tools, runs the Claude agent loop.
- `tools.py` — 8 tools exposed to Claude via `@tool` decorators:
  `run_load_tests`, `run_api_tests`, `run_integration_tests`, `run_e2e_tests`,
  `list_project_files`, `read_file`, `generate_pdf_report`, `send_email_report`.
- Reuses `MVP-Access-API-Test/agent/` code (config, report_generator, email_sender) via `sys.path`.
