# NAPCO Nucleus — Architecture

A clean-architecture AI agent modeled on the Digital Deputy pattern, focused on **project management** and **test automation** for the MVP Access API + E2E test projects.

## Two dimensions, six workflows

| Dimension | Workflow | Cron (proposed) |
|---|---|---|
| Project Management | Requirement Management | every 2h during business hours |
| Project Management | Daily Report | 09:00 BDT daily |
| Test Automation | API Functional Test | on-demand + pre-deploy |
| Test Automation | API Integration Test | 02:00 BDT daily |
| Test Automation | API Load Test | Sun 03:00 BDT weekly (expensive) |
| Test Automation | MVP Access E2E Test | 04:00 BDT daily |

## Claude-first principle

Anything that is deciding, summarizing, classifying, or prioritizing goes through the Claude Agent SDK. Anything that is fetching, writing, or calling a protocol stays in Python.

Deleted in the refactor: `morning_brief.py` (1,732 lines of Python templating replaced by a ~200-line `prompts/daily_report.md` + Claude reasoning) and `teams_graph_client.py` (Power Automate forwards Teams channel messages to an allowlisted email, so the existing IMAP poller covers it — no new code needed).

## File layout

```
agent.py                  entry point: python agent.py --task <name>
config.py                 env accessors for SMTP, GitLab, Drive, paths
memory.py                 SQLite + FTS5 (activity_logs, requirements_seen,
                          test_run_history, email_checkpoints, drive_processed)
nucleus_memory.db         committed to repo (memory travels with clone)

drive_ingester.py         Drive → Groq Whisper / pypdf → inbox files
requirements_inbox.py     IMAP poller (UIDVALIDITY-safe)
gitlab_client.py          GitLab v4 REST wrapper

prompts/
  system.md               shared backbone (identity, tone, memory rule)
  requirement_management.md
  daily_report.md
  api_functional_test.md
  api_integration_test.md
  api_load_test.md
  e2e_test.md

tools/
  __init__.py             aggregates ALL_TOOLS + TOOL_NAMES
  memory.py               5 recall tools Claude calls to consult memory
  requirements.py         poll_requirement_emails, read_requirement_inbox,
                          publish_tasks_to_gitlab
  tests.py                run_api_tests, run_integration_tests,
                          run_load_tests, run_e2e_tests,
                          run_single_e2e_test, check_api_health,
                          check_all_endpoints_health, compare_with_last_run,
                          list_known_bugs, test_inventory, find_flaky_tests
  report.py               generate_pdf_report, send_email_report,
                          send_teams_digest, tail_nightly_log,
                          draft_standup_update, clean_reports_folder
  files.py                list_project_files, read_file, write_file,
                          edit_file, git_diff, git_commit_and_push,
                          recent_commits, explore_ui

data/
  requirements/
    inbox/                raw .txt artifacts (email / meetings / chat / documents)
                          NOTE: state.json + drive-processed.json are
                          retired — their state now lives in SQLite tables
                          email_checkpoints + drive_processed.

.github/workflows/
  requirement-management.yml
  daily-report.yml
  api-functional-test.yml
  api-integration-test.yml
  api-load-test.yml
  e2e-test.yml
  build-deploy.yml        non-agent CI, unchanged
```

## Runner strategy

All six agent workflows target `[self-hosted, vm-claude]`, reusing the self-hosted runner already registered for Digital Deputy's VM (`172.16.205.209`, `AEL\samin`). Secrets are pulled from `C:\actions-runner-secrets\` at the start of each run (see the "Restore local secrets" step). No `ANTHROPIC_API_KEY` is used anywhere — the VM has the Claude CLI logged into the Max subscription.

## Memory

SQLite at `nucleus_memory.db`, committed to the repo so `git clone` on any machine restores the agent's memory. Single writer (the VM), so no concurrent-write conflicts. Prompts open with a mandatory Step 0 "Memory check-in" — every task run consults `recall_activity` / `search_requirements` / `recall_test_runs` before doing fresh work.

FTS5 indexes (Porter stemming) let Claude fuzzy-match requirement titles so near-duplicates (`"Add SSO login"` vs `"add sso login path"`) collapse and don't re-ingest.

## Phases (this refactor)

1. **Inventory** — read existing code, map to new structure. *Done.*
2. **Branch + skeleton** — `agent.py`, `config.py`, `memory.py`, `tools/__init__.py`, `tools/memory.py`, `prompts/system.md`, `docs/ARCHITECTURE.md`. *This commit.*
3. **Port memory layer** — adapted from Digital Deputy with NAPCO-specific tables. *Done.*
4. **Migrate tools** — split current `tools.py` into `tools/{requirements,tests,report,files}.py`, apply Claude-first strip of hardcoded RCA + templating.
5. **Write prompts** — 6 task prompts, each with Step 0 memory check-in.
6. **Update workflows** — rename `integration-test` → `api-integration-test`, `load-test` → `api-load-test`, add `daily-report.yml`, retire `api-digest.yml`, add the secret-restore step to all six, target `[self-hosted, vm-claude]`.
7. **Test + merge** — `workflow_dispatch` each task on the branch, verify, merge to main.
