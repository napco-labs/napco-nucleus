# Task: Requirement Management

Dimension: Project Management. Fires every 2 hours during business hours.

Goal: collect raw client text from allowlisted requirement emails (currently only `khasan@ael-bd.com`), split each distinct requirement into ~3-hour workable tasks, and open each as a GitLab issue with idempotent dedup.

> **Active inputs this iteration:** email only. Google Drive ingestion and Teams digest are disabled on purpose for current testing — DO NOT call `ingest_drive_files` and DO NOT call `send_teams_digest` even if `TEAMS_WEBHOOK_URL` is set.

---

## Loop

### 0. Memory check-in (mandatory)

- `recall_activity(task_name="requirement-management:publish_gitlab", limit=10)` — what did I publish recently?
- `recall_activity(task_name="requirement-management:poll_email", limit=5)` — when did I last poll and what did I get?
- `memory_stats()` — confirm the DB is being written to.

### 1. Ingest new inputs

- `poll_requirement_emails()` — fetches new emails from allowlisted senders into `data/requirements/inbox/email/`. If it errors (missing env vars, auth failure), report and stop.

> Drive ingestion (`ingest_drive_files`) is disabled this iteration. Skip it.

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
- `labels`: REQUIRED list of EXACTLY 2 strings — see Label classification below
- `issue_type`: REQUIRED string — `"task"` for `requirements` / `updatedRequirements`, `"issue"` for `Bug`. This controls the GitLab work-item subtype.

#### Label classification (mandatory — every task carries 2 labels)

Pick exactly one feature label AND exactly one type label.

**Feature label (pick one — case-sensitive, must match GitLab exactly):**
- `accessGroup` — access groups, group permissions, group membership, group-level rules
- `badgeHolder` — badge issuance / revocation, badge-level data, badge holders
- `personnel` — personnel records, employee data, personnel-level workflows

If a single requirement clearly affects two features, file ONE task PER feature with the matching label. If you genuinely cannot tell from the source which feature applies, do NOT guess — surface the ambiguity in your final reply and skip that requirement.

**Type label (pick one):**
- `requirements` — a NEW requirement (no fuzzy match found in step 4, OR the match has no `gitlab_issue_url`). Set `issue_type="task"`.
- `Bug` — the source language indicates broken behavior: "bug", "defect", "regression", "not working", "wrong result", "error", "broken", "fails when", or equivalent. Set `issue_type="issue"`.
- `updatedRequirements` — the source describes a CHANGE to a requirement that already exists in `requirements_seen` (fuzzy match WITH a populated `gitlab_issue_url`). Set `issue_type="task"`.

> **Known limitation today:** `publish_tasks_to_gitlab` dedups fuzzy matches with prior issue URLs and SKIPS them — so an `updatedRequirements`-classified task will be labeled in the dict but no GitLab issue will be filed. Record the classification in your final reply (`updated: N` count) and continue. The dedup-vs-update behavior will change in a follow-up iteration.

Valid `labels` + `issue_type` examples:
- `labels=["accessGroup", "requirements"]`, `issue_type="task"` — new task on access groups
- `labels=["badgeHolder", "Bug"]`, `issue_type="issue"` — bug filed against badge holders
- `labels=["personnel", "updatedRequirements"]`, `issue_type="task"` — client changed an existing personnel requirement

Invalid (do not produce):
- `["requirements"]` — missing feature label
- `["accessGroup"]` — missing type label
- `["accessGroup", "badgeHolder", "requirements"]` — three labels not allowed
- `["AccessGroup", "Requirements"]` — case must match GitLab exactly

### 6. Publish

`publish_tasks_to_gitlab(tasks=<list from step 5>)`. The tool:
- Snapshots the full submission to `data/requirements/proposed-tasks.json` for traceability
- Dedupes by title against currently-open GitLab issues (re-runs are safe)
- Dedupes fuzzy-match against `requirements_seen` in memory (catches spelling variants)
- Creates the rest
- Writes each successful task to memory with its issue IID + URL

Surface the counts (created / skipped / failed) and any `web_urls` in your final reply so the user can click through.

### 7. Log + exit

Log a final `log_activity` row with a one-line summary like "Requirements processed: N files → M tasks → K new issues in GitLab." Exit.

> Teams digest (`send_teams_digest`) is disabled this iteration. Skip it.

---

## Output language rule

Task titles, descriptions, and acceptance criteria MUST be written in English, even if the source transcript / email is in Bangla, Malay, or any other language. Translate meaning, not literal words. Preserve proper nouns, endpoint names, field names, and exact client phrasing where it helps a developer understand scope.

## Tone

Plain developer English. No marketing voice, no "streamline / align / optimize" jargon. NO em-dashes (see system.md). Preserve concrete numbers, endpoints, field names.
