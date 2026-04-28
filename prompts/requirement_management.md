# Task: Requirement Management

Dimension: Project Management. Fires twice daily, 12 hours apart, every day (01:00 BDT + 13:00 BDT).

Goal: collect raw client text from allowlisted requirement emails (currently only `khasan@ael-bd.com`), split each distinct requirement into ~3-hour workable tasks, and open each as an **OpenProject Work Package** in the `mvp-access` project's backlog with idempotent dedup.

> **Active inputs this iteration:** email only. Google Drive ingestion and Teams digest are disabled on purpose for current testing — DO NOT call `ingest_drive_files` and DO NOT call `send_teams_digest` even if `TEAMS_WEBHOOK_URL` is set.

---

## Loop

### 0. Memory check-in (mandatory)

- `recall_activity(task_name="requirement-management:publish_backlog", limit=10)` — what did I publish recently?
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

- **No fuzzy match, OR match has no `wp_url`** → this is a NEW requirement. Proceed to step 5 with type label `requirements` (or `Bug` if the source language is bug-shaped).
- **Fuzzy match WITH `wp_url` AND the source describes the SAME thing** (no material change — same scope, same numbers, same endpoints) → SKIP. Count it in the final summary as "skipped N already-filed requirements".
- **Fuzzy match WITH `wp_url` BUT the source describes a CHANGE** (different scope/numbers/endpoints, added/removed behavior) → DO NOT skip. Treat it as an update: proceed to step 5 with type label `updatedRequirements` and capture the prior work package's `wp_id` for `updates_prior_id`. The publish tool will then EDIT the existing OpenProject Work Package in place: swap the subject to the new title and post a comment with the new content. The old subject is preserved in OpenProject's Activity tab. Status is **not** changed (the role-based workflow on this instance restricts `New → In specification` for the API user — the subject change + the timestamped comment are the "updated" signal that the boss-facing dashboards use).

The "material change" test is a judgment call: read the prior summary in memory (returned by `search_requirements`) and compare to the current source. If a developer reading both side-by-side would say "the spec moved", it's an update; if they'd say "they're talking about the same item", it's a skip.

### 5. Split into 3-hour tasks

- If a requirement is clearly larger (e.g., "build SSO"), split into multiple 3-hour tasks: scaffolding, happy-path, edge-cases, tests.
- If a requirement is smaller than 3 hours AND part of a natural cluster, merge related small ones into a single task.
- If a requirement is smaller than 3 hours and can't be merged, ship it as-is with `estimate_hours` matching reality (1 or 2).
- Never invent requirements not present in the source text.

For each task produce a dict with:
- `title`: imperative, <70 chars (e.g., "Add SSO login path"). For `updatedRequirements` tasks, this is the NEW subject — it will REPLACE the existing Work Package's subject (the old subject is preserved in OpenProject's Activity tab).
- `description`: why + enough context from the source that a developer can start without asking back
- `acceptance_criteria`: 2-5 concrete bullet strings
- `estimate_hours`: int, usually 3
- `source_ref`: the `rel_path` of the source file from step 2
- `labels`: REQUIRED list of EXACTLY 2 strings — see Label classification below
- `updates_prior_id`: REQUIRED int for `updatedRequirements` tasks ONLY — the `wp_id` of the existing Work Package being revised, taken from step 4's fuzzy match. Omit for `requirements` and `Bug`.

#### Label classification (mandatory — every task carries 2 labels)

Pick exactly one **feature** label AND exactly one **type** label.

**Feature label (pick one — case-sensitive, must match the OpenProject Category exactly):**
- `AccessGroup` — access groups, group permissions, group membership, group-level rules
- `BadgeHolder` — badge issuance / revocation, badge-level data, badge holders
- `Personnel` — personnel records, employee data, personnel-level workflows

The publish tool sends this as the OpenProject **Category** field. The categories are pre-configured in Project Settings → Categories.

If a single requirement clearly affects two features, file ONE task PER feature with the matching label. If you genuinely cannot tell from the source which feature applies, do NOT guess — surface the ambiguity in your final reply and skip that requirement.

**Type label (pick one):**
- `requirements` — a NEW requirement (no fuzzy match found in step 4, OR the match has no `wp_url`). Maps to OpenProject **Type=Task**, **Status=New**.
- `Bug` — the source language indicates broken behavior: "bug", "defect", "regression", "not working", "wrong result", "error", "broken", "fails when", or equivalent. Maps to OpenProject **Type=Bug**, **Status=New**.
- `updatedRequirements` — the source describes a CHANGE to a requirement that already exists in `requirements_seen` (fuzzy match WITH a populated `wp_url`). Maps to OpenProject **subject change + comment** on the existing Work Package — **the publish tool does NOT create a new WP** for this case. Provide `updates_prior_id` so the publish tool knows which WP to revise.

Valid `labels` examples:
- `labels=["AccessGroup", "requirements"]` — new task on access groups
- `labels=["BadgeHolder", "Bug"]` — bug filed against badge holders
- `labels=["Personnel", "updatedRequirements"]` (with `updates_prior_id=42`) — client revised an existing personnel requirement

Invalid (do not produce):
- `["requirements"]` — missing feature label
- `["AccessGroup"]` — missing type label
- `["AccessGroup", "BadgeHolder", "requirements"]` — three labels not allowed
- `["accessGroup", "requirements"]` — feature label must be PascalCase to match OpenProject Category exactly

### 6. Publish

`publish_tasks_to_backlog(tasks=<list from step 5>)`. The tool:
- Calls OpenProject's `/api/v3/projects/mvp-access/work_packages` endpoint
- Snapshots the full submission to `data/requirements/proposed-tasks.json` for traceability
- Dedupes by subject against currently-open Work Packages (re-runs are safe)
- Dedupes fuzzy-match against `requirements_seen` in memory (catches spelling variants)
- Creates the rest as new Work Packages OR updates existing ones (for `updatedRequirements`)
- Writes each successful task to memory with its `wp_id` + `wp_url`. Also writes on dedup-skip-on-already-open so the memory self-heals after a reset.

Surface the counts (created / updated / skipped / failed) and any `web_url`s in your final reply so the user can click through to the OpenProject Backlogs view at `https://napco.openproject.com/projects/mvp-access/backlogs/backlog`.

### 7. Log + exit

Log a final `log_activity` row with a one-line summary like "Requirements processed: N files → M tasks → K new work packages, U updates in OpenProject." Exit.

> Teams digest (`send_teams_digest`) is disabled this iteration. Skip it.

---

## Output language rule

Task titles, descriptions, and acceptance criteria MUST be written in English, even if the source transcript / email is in Bangla, Malay, or any other language. Translate meaning, not literal words. Preserve proper nouns, endpoint names, field names, and exact client phrasing where it helps a developer understand scope.

## Tone

Plain developer English. No marketing voice, no "streamline / align / optimize" jargon. NO em-dashes (see system.md). Preserve concrete numbers, endpoints, field names.
