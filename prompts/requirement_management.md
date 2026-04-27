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

### 4. Dedup vs. update — compare against prior work

**Before proposing any task, call `search_requirements("<keyword from the requirement>")`.** Then:

- **No fuzzy match, OR match has no `gitlab_issue_url`** → this is a NEW requirement. Proceed to step 5 with type `requirements` (or `Bug` if the source language is bug-shaped).
- **Fuzzy match WITH `gitlab_issue_url` AND the source describes the SAME thing** (no material change — same scope, same numbers, same endpoints) → SKIP. Count it in the final summary as "skipped N already-filed requirements".
- **Fuzzy match WITH `gitlab_issue_url` BUT the source describes a CHANGE** (different scope/numbers/endpoints, added/removed behavior) → DO NOT skip. Treat it as an update: proceed to step 5 with type `updatedRequirements` and capture the prior issue's `gitlab_issue_iid` for `updates_prior_iid`. The publish tool will then EDIT the existing GitLab work item in place (new title, swap labels, post a comment with the new content) — it does NOT create a new item. GitLab's native timeline preserves the full change history.

The "material change" test is a judgment call: read the prior summary in memory (returned by `search_requirements`) and compare to the current source. If a developer reading both side-by-side would say "the spec moved", it's an update; if they'd say "they're talking about the same item", it's a skip.

### 5. Split into 3-hour tasks

- If a requirement is clearly larger (e.g., "build SSO"), split into multiple 3-hour tasks: scaffolding, happy-path, edge-cases, tests.
- If a requirement is smaller than 3 hours AND part of a natural cluster, merge related small ones into a single task.
- If a requirement is smaller than 3 hours and can't be merged, ship it as-is with `estimate_hours` matching reality (1 or 2).
- Never invent requirements not present in the source text.

For each task produce a dict with:
- `title`: imperative, <70 chars (e.g., "Add SSO login path"). For `updatedRequirements` tasks, this is the NEW title — it will REPLACE the existing work item's title (the old title is preserved in GitLab's system-note timeline).
- `description`: why + enough context from the source that a developer can start without asking back
- `acceptance_criteria`: 2-5 concrete bullet strings
- `estimate_hours`: int, usually 3
- `source_ref`: the `rel_path` of the source file from step 2
- `labels`: REQUIRED list of EXACTLY 2 strings — see Label classification below
- `issue_type`: REQUIRED string — `"task"` for `requirements` / `updatedRequirements`, `"issue"` for `Bug`. This controls the GitLab work-item subtype.
- `updates_prior_iid`: REQUIRED int for `updatedRequirements` tasks ONLY — the `gitlab_issue_iid` of the existing work item being revised, taken from step 4's fuzzy match. Omit for `requirements` and `Bug`.

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
- `updatedRequirements` — the source describes a CHANGE to a requirement that already exists in `requirements_seen` (fuzzy match WITH a populated `gitlab_issue_url`). Set `issue_type="task"` and provide `updates_prior_iid` so the publish tool edits the existing work item in place (new title, swap labels from `requirements` to `updatedRequirements`, post a comment with the new content).

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
