# Requirement Management — End-to-End Flow

How the `requirement-management` workflow turns raw client text (emails, meeting recordings, PDFs, forwarded Teams messages) into ~3-hour tasks tracked as GitLab issues.

> **Note on notifications:** this workflow does **not** send email. Optional notification is a Teams digest via webhook. Emails are produced by the daily-report workflows.

---

## 1. Architecture — who talks to whom

```mermaid
flowchart TB
    user["You / cron<br/>(workflow_dispatch or<br/>every 2h, 09–17 BDT, Sun–Thu)"]
    gha["GitHub Actions<br/>requirement-management.yml"]
    runner["Self-hosted Windows runner<br/>test-runner @ 172.16.205.209"]
    agent["agent.py<br/>(Python orchestrator)"]
    cli["Claude CLI (local)<br/>via Claude Max — no API key"]
    mcp["napco-nucleus MCP server<br/>(in-process tools)"]
    db[("SQLite<br/>nucleus_memory.db")]
    imap[/"IMAP mailbox<br/>(allowlisted senders)"/]
    drive[/"Google Drive API"/]
    groq[/"Groq Whisper<br/>(audio → text)"/]
    pdf[/"pypdf<br/>(PDF → text, local)"/]
    gitlab[/"GitLab API<br/>(issues)"/]
    teams[/"Teams Incoming Webhook"/]
    repo[("GitHub repo<br/>main branch")]

    user -->|dispatch / schedule| gha
    gha -->|assigns job| runner
    runner -->|checkout · pip install · py agent.py| agent
    agent -->|stdio + MCP| cli
    cli -->|tool calls| mcp

    mcp --> imap
    mcp --> drive
    mcp --> groq
    mcp --> pdf
    mcp --> gitlab
    mcp --> teams
    mcp --> db

    runner -->|git commit + push<br/>nucleus_memory.db, data/requirements/| repo
```

---

## 2. Sequence — one full run, end to end

```mermaid
sequenceDiagram
    autonumber
    actor User as You / cron
    participant GHA as GitHub Actions
    participant Runner as Self-hosted runner
    participant Agent as agent.py
    participant Claude as Claude CLI (local)
    participant MCP as MCP tools
    participant Ext as External services
    participant DB as nucleus_memory.db
    participant Repo as GitHub repo

    User->>GHA: workflow_dispatch / cron fires
    GHA->>Runner: assign job
    Runner->>Runner: actions/checkout@v5
    Runner->>Runner: pip install -r requirements.txt
    Runner->>Agent: py -3 agent.py --task requirement-management
    Agent->>Agent: load_dotenv(.env)
    Agent->>MCP: register napco-nucleus server
    Agent->>Claude: open SDK client + send kickoff prompt

    Note over Claude: STEP 0 — memory check-in
    Claude->>MCP: recall_activity("publish_gitlab", limit=10)
    MCP->>DB: SELECT activity_logs
    Claude->>MCP: recall_activity("poll_email", limit=5)
    Claude->>MCP: memory_stats()

    Note over Claude: STEP 1 — ingest
    Claude->>MCP: poll_requirement_emails()
    MCP->>Ext: IMAP login + fetch new UIDs (allowlisted senders)
    MCP->>MCP: write *.txt to data/requirements/inbox/email/
    MCP->>DB: log_activity
    Claude->>MCP: ingest_drive_files()
    MCP->>Ext: Google Drive list new files
    MCP->>Ext: audio → Groq Whisper transcript
    MCP->>MCP: PDF → pypdf (local extraction)
    MCP->>MCP: write *.txt to inbox/{meetings,documents}/

    Note over Claude: STEP 2 — read inbox
    Claude->>MCP: read_requirement_inbox()
    MCP-->>Claude: files[] (source, filename, content)

    Note over Claude: STEP 3 — identify distinct requirements (LLM, no tool call)

    Note over Claude: STEP 4 — dedupe per requirement
    Claude->>MCP: search_requirements("<keyword>")
    MCP->>DB: FTS5 query on requirements_seen
    Note over Claude: skip if gitlab_issue_url found

    Note over Claude: STEP 5 — split into ~3-hour tasks (LLM, no tool call)<br/>tasks=[{title, description, acceptance_criteria,<br/>estimate_hours:3, source_ref, labels}, ...]

    Note over Claude: STEP 6 — publish
    Claude->>MCP: publish_tasks_to_gitlab(tasks)
    MCP->>MCP: snapshot → data/requirements/proposed-tasks.json
    MCP->>Ext: GitLab list_open_issue_titles
    loop per task
        MCP->>MCP: dedupe vs open titles
        MCP->>DB: dedupe vs requirements_seen
        MCP->>Ext: GitLab create_issue
        MCP->>DB: remember_requirement (iid + url)
    end
    MCP-->>Claude: {created, skipped, failed}

    Note over Claude: STEP 7 — digest + exit
    Claude->>MCP: send_teams_digest("Requirements processed: N → M tasks → K new issues")
    MCP->>Ext: POST Teams webhook
    Claude->>MCP: log_activity (final summary)
    Claude-->>Agent: stream done
    Agent-->>Runner: exit 0

    Note over Runner: POST-RUN — persist state back to git
    Runner->>Runner: git add nucleus_memory.db data/requirements/
    Runner->>Runner: git commit -m "requirement-management: <UTC>"
    Runner->>Runner: git pull --rebase origin main
    Runner->>Repo: git push
    GHA-->>User: run summary visible in Actions UI
```

---

## 3. Who commands whom — cheat-sheet

| Layer | Actor | Command it issues | To whom |
|---|---|---|---|
| 0 | You / cron | `workflow_dispatch` or schedule fire | GitHub Actions |
| 1 | GitHub Actions | "run this job" | Self-hosted Windows runner |
| 2 | Runner shell | `py -3 agent.py --task requirement-management` | Python `agent.py` |
| 3 | `agent.py` | `client.query("Run the Requirement Mgmt loop now…")` | Claude CLI (local, Claude Max) |
| 4 | Claude (the LLM) | tool calls via MCP (`poll_requirement_emails`, `ingest_drive_files`, `read_requirement_inbox`, `search_requirements`, `publish_tasks_to_gitlab`, `send_teams_digest`, `log_activity`) | `napco-nucleus` MCP server (in-process) |
| 5 | MCP tool fns | HTTP / IMAP / SDK calls | IMAP, Google Drive, Groq, GitLab, Teams, SQLite |
| 6 | Runner shell (post-step) | `git commit && git push` | GitHub repo |

**Who does what:** Claude is the *decider* — it reads inbox files, identifies real requirements, splits them into 3-hour tasks, writes the titles and descriptions. The MCP tools are the *hands* — IMAP, Drive, Groq, GitLab, SQLite. GitHub Actions is the *scheduler*. The self-hosted runner is the *machine* the whole thing runs on.

---

## 4. Key guardrails

- **Idempotency:** IMAP uses UIDVALIDITY + since-UID checkpoint; Drive never re-processes a file ID; GitLab dedup runs in two layers (open-issue title match + fuzzy match against `requirements_seen` in memory).
- **Dry-run:** `workflow_dispatch` accepts `dry_run=true`. Tools check `NAPCO_NUCLEUS_DRY_RUN=1` and short-circuit any mutation (no SMTP, no GitLab create, no git push). Memory still logs the dry run.
- **Concurrency:** workflow group `requirement-management` with `cancel-in-progress: false` — runs queue, never overlap.
- **State persistence:** `nucleus_memory.db` and `data/requirements/` get committed back to `main` after every run, so the next run has the previous run's checkpoints and dedupe history.
- **Allowlist:** only IMAP senders in `REQ_SENDER_ALLOWLIST` are ingested. Random inbound mail is dropped.
- **Language:** task titles / descriptions / acceptance criteria are always written in English even when the source is Bangla / Malay / etc.
