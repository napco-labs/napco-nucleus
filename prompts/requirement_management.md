# Task: Requirement Management — Collect, Aggregate, Verify

Dimension: Project Management. Local-only (Teams chat ingest needs the desktop cache). Manual `workflow_dispatch` for now — schedule disabled 2026-05-05; OpenProject publish paused 2026-05-06.

Goal: collect every raw input that arrived since the last run (email, Google Drive, Teams chat, audio meetings), bundle it all into one Word document for traceability, identify the distinct requirements, write a flat numbered list summary for the client, and email both docs out.

> **Active inputs this iteration:** email + Google Drive + Teams chat + audio meetings.
> **Disabled this iteration:** OpenProject publish (`publish_tasks_to_backlog`) and Teams webhook (`send_teams_digest`) — DO NOT call either. The "track to OpenProject" stage is a human's job for now.

---

## Loop

### 0. Memory check-in (mandatory)

- `recall_activity(task_name="requirement-collection:write_aggregation", limit=5)` — what was the last collection cycle?
- `recall_activity(task_name="requirement-collection:send_verification", limit=5)` — what did we last send for client verification?
- `recall_activity(task_name="requirement-management:poll_email", limit=5)` — last email poll checkpoint.
- `memory_stats()` — confirm the DB is being written to.

### 1. Collect from every channel

NN owns email + Google Drive collection. Teams chat and call transcripts are produced by **Teams-Requirement-Watcher** (sibling project) running on the same machine — TRW writes directly into NN's `data/requirements/inbox/chat/` and `inbox/meetings/`, so they appear in step 2's read with no extra ingest tool needed here.

If a tool errors with missing env vars, log the error and continue with the channels that ARE available — partial collection is fine, total failure is not.

- **Email**: `poll_requirement_emails()` — fetches new emails from allowlisted senders into `data/requirements/inbox/email/`. PDF / Word / plain-text attachments are extracted to text and appended to each email body so the LLM reads them inline.
- **Google Drive**: `ingest_drive_files()` — pulls audio/video → Whisper → `inbox/meetings/`, PDF → pypdf → `inbox/documents/`, Word docs `.docx` → python-docx → `inbox/documents/`, plain text `.txt` → `inbox/documents/`.
- **Teams chat & call transcripts**: produced by TRW out-of-band. NN does NOT call any ingest tool for these. If the user wants a fresh chat dump or call transcript before this run, they invoke `dump_chat.py <number>` or `transcribe_call.py` from TRW themselves.

### 2. Read the inbox

`read_requirement_inbox()` (no args). Returns every file across all channels, each with `source` (email / chat / meeting / document), `filename`, `rel_path`, `content`. If `file_count == 0`, log it and stop — nothing to bundle.

### 3. Write the raw aggregation docx

Build the `sources` argument from the inbox: a list of dicts with `channel` (one of email/chat/meeting/document), `filename`, `content` (the full text). Map each `source` field from step 2 to the matching `channel`.

`write_aggregation_docx(sources=<list>)` — writes `data/requirements/aggregation_<YYYY-MM-DD>.docx`. This is the traceability artifact: every raw input, verbatim, grouped by channel. Capture the returned `path`.

### 4. Identify distinct requirements

Read each inbox file's content and extract every distinct **client requirement**. A requirement is a user-visible capability, change, bug fix, or deliverable the client asked for — NOT process chatter, greetings, scheduling, "thanks", calendar invites, daily test reports, or system-generated notifications.

For each requirement produce a dict with:
- `title`: short imperative phrase, <80 chars (e.g., "Allow access groups to inherit parent permissions").
- `summary`: ONE paragraph in plain English, no blank lines, no bullets, 2-4 sentences. Explain what the client wants and why, in language a developer can act on. Translate from Bangla to English if the source is Bangla — translate meaning, not literal words.
- `source_refs`: list of `rel_path` strings from step 2 (one or more sources where this requirement appeared).

If a requirement clearly came from multiple channels (e.g. raised in a Teams chat, restated in email), include all of them in `source_refs`.

If you cannot identify any requirements (e.g. inbox was all process chatter), proceed to step 5 with an empty list — the verification doc will not be produced and the client email will be skipped, but the aggregation doc + records email still go out.

### 5. Write the verification docx

Only if step 4 produced at least one requirement.

`write_verification_docx(requirements=<list from step 4>)` — writes `data/requirements/Requirements Verification <YYYY-MM-DD>.docx`. Output shape is a flat numbered list, one paragraph per requirement: `1. <title> - <summary>`. Capture the returned `path`.

### 6. Draft the two emails (manual send by user)

NAPCO Nucleus does NOT send email itself (per the approved On-Demand workflow). It writes `.eml` drafts to `data/requirements/drafts/<YYYY-MM-DD>/` AND pushes each one into the user's IMAP Drafts folder so the draft appears in Outlook / Gmail web ready for manual review and send.

The aggregation draft is always produced (records artifact). The verification draft is produced only if step 5 ran.

- **Aggregation → records inbox**: `draft_aggregation_email(docx_path=<path from step 3>)`. Default recipient is `hasan.celloscope@gmail.com` (env `AGGREGATION_TO`). Internal records tone — no "please verify" wording.
- **Verification → client**: `draft_verification_email(docx_path=<path from step 5>)`. Default recipient is `titucse@gmail.com` (env `VERIFICATION_TO`). Asks the client to reply confirming the interpretation or send corrections.

Both honor `NAPCO_NUCLEUS_DRY_RUN=1` for safe testing — they return `{drafted: false, dry_run: true, ...}` and write nothing to disk.

Surface the absolute path of each `.eml` so the user can click to open it.

### 7. Log + exit

Log a final `log_activity` row with a one-line summary like:
"Collection cycle: N inbox files (E email / C chat / M meeting / D document) → R requirements identified → 2 .eml drafts written (1 verification, 1 aggregation) for manual send."

Surface in your final reply:
- Aggregation doc path
- Verification doc path (or "skipped — no requirements identified")
- Both `.eml` draft paths (absolute) + recipients + drafted/dry-run status
- Per-channel ingest counts from step 1

---

## Output language rule

Titles and summaries MUST be written in English, even if the source transcript / chat / email is in Bangla, Malay, or any other language. Translate meaning, not literal words. Preserve proper nouns, endpoint names, field names, and exact client phrasing where it helps a developer understand scope.

## Tone

Plain developer English. No marketing voice, no "streamline / align / optimize" jargon. NO em-dashes (see system.md). Preserve concrete numbers, endpoints, field names. The client reads the verification doc — write like you respect their time.
