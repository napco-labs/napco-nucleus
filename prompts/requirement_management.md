# Task: Requirement Management

Dimension: Project Management. Fires every 2 hours during business hours.

Goal: collect raw client text from three sources (allowlisted requirement emails, Google Drive meeting recordings + PDFs, Teams channel messages forwarded by Power Automate into the same email inbox), split each distinct requirement into ~3-hour workable tasks, and open each as a GitLab issue with idempotent dedup.

---

## Loop

### 0. Memory check-in (mandatory)

- `recall_activity(task_name="requirement-management:publish_gitlab", limit=10)` — what did I publish recently?
- `recall_activity(task_name="requirement-management:poll_email", limit=5)` — when did I last poll and what did I get?
- `memory_stats()` — confirm the DB is being written to.

### 1. Ingest new inputs

- `poll_requirement_emails()` — fetches new emails from allowlisted senders into `data/requirements/inbox/email/`. If it errors (missing env vars, auth failure), report and continue — Drive is still processable.
- `ingest_drive_files()` — downloads new audio/video + PDF from the configured Drive folder. Audio goes through Groq Whisper → `data/requirements/inbox/meetings/`. PDF goes through pypdf → `data/requirements/inbox/documents/`.

### 2. Read the inbox

`read_requirement_inbox()` (no args — returns every source). Each returned file has `source` (email / meetings / chat / documents), `filename`, `rel_path`, `content`. If `file_count == 0`, stop and tell the user the inbox is empty.

### 3. Identify distinct requirements

For each file, read the content and identify every distinct requirement. A "requirement" is a user-visible capability, change, bug fix, or deliverable the client asked for — NOT process chatter, greetings, scheduling, or small-talk. Ignore those.

### 4. Dedup against prior work

**Before proposing any task, call `search_requirements("<keyword from the requirement>")`.** If the result includes a row with a populated `gitlab_issue_url`, the requirement was already filed — skip it and tell the user in the final summary ("skipped N already-filed requirements").

### 5. Split into 3-hour tasks

- If a requirement is clearly larger (e.g., "build SSO"), split into multiple 3-hour tasks: scaffolding, happy-path, edge-cases, tests.
- If a requirement is smaller than 3 hours AND part of a natural cluster, merge related small ones into a single task.
- If a requirement is smaller than 3 hours and can't be merged, ship it as-is with `estimate_hours` matching reality (1 or 2).
- Never invent requirements not present in the source text.

For each task produce a dict with:
- `title`: imperative, <70 chars (e.g., "Add SSO login path")
- `description`: why + enough context from the source that a developer can start without asking back
- `acceptance_criteria`: 2-5 concrete bullet strings
- `estimate_hours`: int, usually 3
- `source_ref`: the `rel_path` of the source file from step 2
- `labels`: optional list of strings (e.g., `["auth"]`, `["bug"]`)

### 6. Publish

`publish_tasks_to_gitlab(tasks=<list from step 5>)`. The tool:
- Snapshots the full submission to `data/requirements/proposed-tasks.json` for traceability
- Dedupes by title against currently-open GitLab issues (re-runs are safe)
- Dedupes fuzzy-match against `requirements_seen` in memory (catches spelling variants)
- Creates the rest
- Writes each successful task to memory with its issue IID + URL

Surface the counts (created / skipped / failed) and any `web_urls` in your final reply so the user can click through.

### 7. Digest + exit

If `TEAMS_WEBHOOK_URL` is set, call `send_teams_digest` with a one-line summary like "Requirements processed: N files → M tasks → K new issues in GitLab." Log a final `log_activity` row with the same summary. Exit.

---

## Output language rule

Task titles, descriptions, and acceptance criteria MUST be written in English, even if the source transcript / email is in Bangla, Malay, or any other language. Translate meaning, not literal words. Preserve proper nouns, endpoint names, field names, and exact client phrasing where it helps a developer understand scope.

## Tone

Plain developer English. No marketing voice, no "streamline / align / optimize" jargon. NO em-dashes (see system.md). Preserve concrete numbers, endpoints, field names.
