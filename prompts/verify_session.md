# Task: Verify Pull Session — Identify Requirements + Draft Client Email

Dimension: Project Management. Local-only. Manual `workflow_dispatch` for now.

Goal: read the user's current pull-session Word document (the consolidated capture from Teams chats / emails / Drive files / meetings the user explicitly pulled), extract every distinct client requirement, write a flat numbered Requirements Verification Word doc, and draft ONE email to the client with that doc attached.

> **Inputs this task:** the pull-session doc only (`data/requirements/sessions/current.docx`).
> **Disabled this task:** OpenProject publish, Teams webhook, the auto-poll inbox flow (`poll_requirement_emails` / `ingest_drive_files` / `read_requirement_inbox`), the records-aggregation email. DO NOT call any of those — the user has already curated what they want identified.

---

## Loop

### 0. Memory check-in (mandatory)

- `recall_activity(task_name="requirement-collection:start_pull_session", limit=3)` — when did this session start?
- `recall_activity(task_name="requirement-collection:draft_verification", limit=5)` — recent drafts.

### 1. Read the session doc

`read_pull_session()` (no args). Returns `{exists, session_path, started_at, label, section_count, sections, chars, content}`.

If `exists == false` → STOP and report "No active pull session — user must run pull commands first." Do not invent content.

If `section_count == 0` → STOP and report "Session is empty — no pulls have been added."

Otherwise capture `session_path`, `sections`, and `content` for the next step.

### 2. Identify distinct requirements

Read the `content` returned from step 1 and extract every distinct **client requirement**. A requirement is a user-visible capability, change, bug fix, or deliverable the client asked for — NOT process chatter, greetings, scheduling, "thanks", calendar invites, daily test reports, or system-generated notifications.

For each requirement produce a dict with:
- `title`: short imperative phrase, <80 chars (e.g. "Allow access groups to inherit parent permissions").
- `summary`: ONE paragraph in plain English, no blank lines, no bullets, 2-4 sentences. Explain what the client wants and why, in language a developer can act on. Translate from Bangla to English if the source is Bangla — translate meaning, not literal words.
- `source_refs`: list of section titles from step 1 (the `sections` array) where this requirement appeared. A requirement raised in Teams and restated in email gets BOTH section titles.

If you cannot identify any requirements (e.g. the session was all process chatter), STOP and report "No requirements identified in this session — nothing drafted." Do not produce an empty verification doc, do not draft an email.

### 3. Write the Requirements Verification doc

`write_verification_docx(requirements=<list from step 2>)` — writes `data/requirements/Requirements Verification <YYYY-MM-DD>.docx`. Output shape is a flat numbered list, one paragraph per requirement: `1. <title> - <summary>`. Capture the returned `path`.

### 4. Draft ONE client email

`draft_verification_email(docx_path=<path from step 3>)`. Default recipient is `VERIFICATION_TO` env (configured by user). The tool:
- Writes a `.eml` to `data/requirements/drafts/<YYYY-MM-DD>/`
- Pushes the same message into the user's IMAP Drafts folder (Outlook / Gmail web)
- Returns `{drafted, draft_path, absolute_path, imap_appended, drafts_folder, ...}`

Both honor `NAPCO_NUCLEUS_DRY_RUN=1` for safe testing — they return `{drafted: false, dry_run: true, ...}` and write nothing.

### 5. Log + exit

Log a final `log_activity` row like:

"Session verify: N sections in pull doc → R requirements identified → 1 .eml draft (verification → <recipient>) {imap_appended | imap_failed}."

Surface in your final reply:
- Session doc path + started_at
- Section count + section titles
- Requirements identified (count + titles)
- Verification doc path
- Verification email draft path (absolute) + recipient + IMAP push status (so the user knows whether to look in Outlook Drafts or open the .eml directly)

---

## Output language rule

Titles and summaries MUST be written in English, even if the source transcript / chat / email is in Bangla, Malay, or any other language. Translate meaning, not literal words. Preserve proper nouns, endpoint names, field names, and exact client phrasing where it helps a developer understand scope.

## Tone

Plain developer English. No marketing voice, no "streamline / align / optimize" jargon. NO em-dashes (see system.md). Preserve concrete numbers, endpoints, field names. The client reads the verification doc — write like you respect their time.
