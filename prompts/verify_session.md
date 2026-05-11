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
- `memory_stats()` — confirm requirements_seen has the rows from prior runs (this is the dedup table you'll consult in step 2.5).

### 1. Read the session doc

`read_pull_session()` (no args). Returns `{exists, session_path, started_at, label, section_count, sections, chars, content}`.

If `exists == false` → STOP and report "No active pull session — user must run pull commands first." Do not invent content.

If `section_count == 0` → STOP and report "Session is empty — no pulls have been added."

Otherwise capture `session_path`, `sections`, and `content` for the next step.

### 1.5 Identify the client(s) in scope (mandatory before identify)

Before extracting requirements, identify which client(s) the session is about. NAPCO Nucleus serves **multiple clients** — resolve `client_name` per-message using these conventions:

**Conventions:**

- Senders on `@napcosecurity.com` (Michael Carrieri, Siva, Richard Goldsobel, Salman Firoz, Robert Zhu, anyone else from that domain) → `client_name = "NAPCO Security"`. All such senders collapse to one bucket.
- Senders on `@ael-bd.com` are **also clients** (AEL-internal projects, not just dev-side forwards). Each AEL sender is their own bucket:
  - `assad@ael-bd.com` → `"Assaduz Zaman"`
  - `arzaman@ael-bd.com` → `"Atikur Zaman"`
  - `arhabib@ael-bd.com` → `"Ahsan Habib"`
  - `ihasan@ael-bd.com` → `"Isruk Hasan"`
  - `khasan@ael-bd.com` → `"Titu"`
  - any other `@ael-bd.com` → use the individual's full name as stated in the signature / From header.
- Override: if an `@ael-bd.com` message *explicitly says* it is forwarding a NAPCO Security ask (e.g. "FYI from Michael at NAPCO"), credit `"NAPCO Security"` instead of the AEL sender.
- Other domains: use the organization name from the signature or `client_name` from `MEETING` metadata.
- Teams chats: use the chat title or, for groups with NAPCO Security participants, `"NAPCO Security"`.

One session may mention more than one client; track each separately.

For EACH client you identify, call **two** memory tools in this order:

1. `get_client_history(client_name="<client>", limit=20)` — the requirements that client has raised in past sessions (regardless of confirmation status).
2. `get_open_items(client_name="<client>", max_age_days=30, limit=50)` — requirements drafted to that client recently but NOT yet confirmed (pending or unclear). This is the **in-flight backlog**.

Read both before step 2 and keep three questions in mind:

- **Recurring asks**: does this client *always* ask for X (e.g. audit logging, mobile parity, RBAC)? If they've raised the same thing 3+ times in history, treat its absence in today's session as a likely oversight worth flagging — not as confirmation that they're satisfied.
- **Follow-ups to open items**: if today's content references something in `get_open_items` (same topic, same scope), it's a follow-up — not a net-new ask. Don't draft it as a fresh requirement; instead, if the new content confirms the open item, surface that in your final reply so Titu knows to update the confirmation status manually (or call `remember_requirement` again with the SAME title to bump touch_count — the existing row's confirmation_status stays unless poll_replies has updated it).
- **Stale opens**: if an open item is more than 14 days old and today's session doesn't reference it, mention it in your final reply with the rec "still pending — consider following up with the client."

If both tools return 0 rows, this is a new client to NN's memory. Proceed without context — that's fine. Don't fabricate history.

### 2. Identify distinct requirements

Read the `content` returned from step 1 and extract every distinct **client requirement**. A requirement is a user-visible capability, change, bug fix, or deliverable the client asked for — NOT process chatter, greetings, scheduling, "thanks", calendar invites, daily test reports, or system-generated notifications.

Use the client history from step 1.5 as context: when a client's recurring ask is missing from today's session, you may surface it as a "verify with client" item in the verification doc rather than dropping it silently. Mark such items with a confidence ≤ 0.65 and an explicit rationale ("client has raised this in 3 prior sessions — confirming if still expected").

Every section in the session doc begins with a metadata block that includes a `Source ID:` value like `email/Acme-2026-05-10/abc12345`, `chat/123/1330-1345/def67890`, or `call/Titu-20260511-101500/ghi24680`. These IDs are the **machine-readable citation tokens** you cite per requirement. Use them, not free-text section titles.

For each requirement produce a dict with:
- `title`: short imperative phrase, <80 chars (e.g. "Allow access groups to inherit parent permissions").
- `summary`: ONE paragraph in plain English, no blank lines, no bullets, 2-4 sentences. Explain what the client wants and why, in language a developer can act on. Translate from Bangla to English if the source is Bangla — translate meaning, not literal words.
- `source_refs`: list of `Source ID` values (exact strings from the metadata blocks) where this requirement appeared. A requirement raised in Teams and restated in email gets BOTH Source IDs. If you saw the requirement in only one section, that's one ID — but it must be the precise Source ID, not a paraphrase.
- `confidence`: float between 0.0 and 1.0. How certain are you this is a real client requirement and not noise? Use the rubric: ≥0.90 the client stated it explicitly in plain words; 0.75-0.89 implied but unambiguous in context; 0.50-0.74 inferred from indirect signals (the reviewer should sanity-check before sending); below 0.50 you should probably drop the item entirely.
- `rationale`: ONE short sentence (<160 chars) on what makes this a requirement rather than chatter. The reviewer reads this when the confidence is low.
- `priority`: one of `P0` / `P1` / `P2` / `P3`. P0 = blocking with a stated deadline within 2 weeks; P1 = client signalled urgency without a date; P2 = standard (the default — use when no urgency signal); P3 = "nice to have", explicitly low priority. Default to `P2` when uncertain.
- `severity`: one of `S1` / `S2` / `S3`. S1 = production / security / compliance / revenue impact; S2 = material workflow impact with workaround available; S3 = cosmetic / minor / DX polish. Default to `S2` when uncertain.
- `conflicts_with`: list of Source IDs or open-item ids this requirement contradicts (from step 1.5 open_items and history). Empty list when no conflict. Be conservative — only flag actual contradictions (e.g. "retain audit logs 30 days" vs "retain audit logs 90 days"), not minor wording differences.

If you cannot identify any requirements (e.g. the session was all process chatter), STOP and report "No requirements identified in this session — nothing drafted." Do not produce an empty verification doc, do not draft an email.

### 2.5 Dedup against memory (mandatory before drafting)

For EACH candidate requirement from step 2, call `search_requirements(query="<title>", limit=3)`. If the search returns a hit whose stored title closely matches the candidate (same intent, same scope — minor wording differences are fine), the requirement was already drafted in a prior session. SKIP it. Do not include it in the verification doc.

The remaining requirements (those NOT found in `requirements_seen`) are the NEW ones for this session. Only those go forward to step 3.

If ALL candidates were dedup hits, STOP and report "All identified requirements were already drafted in prior sessions. No new requirements to verify." Do not produce an empty verification doc, do not draft an email.

### 3. Write the Requirements Verification doc

`write_verification_docx(requirements=<list from step 2>)` — writes `data/requirements/Requirements Verification <YYYY-MM-DD>.docx`. Output shape is a flat numbered list, one paragraph per requirement: `1. <title> - <summary>`, followed by a small grey citation/confidence/rationale line.

Pass ALL five fields per requirement (title, summary, source_refs, confidence, rationale) — the tool now renders confidence and rationale in the doc, and items below 0.75 are highlighted in amber so the reviewer reads them carefully. The tool returns `{path, requirement_count, mean_confidence, low_confidence_count}` — capture all four; surface `mean_confidence` and `low_confidence_count` in the final reply so the reviewer can decide whether to send as-is or re-pull with more data.

### 4. Draft ONE client email — with TWO attachments

`draft_verification_email(docx_path=<path from step 3>, session_docx_path=<session_path from step 1>, client_name="<the client identified in step 1.5>")`.

Pass `client_name` — the tool uses it to look up `data/templates/draft_<slug>.md` for tone (formal for NAPCO Security, informal for AEL-internal stakeholders) and to address the email correctly. Without `client_name` you get the default template.

Two attachments go into ONE email:
1. **Requirements Verification .docx** (the curated list from step 3)
2. **Pull Session .docx** — the raw aggregation of email + Teams chat + Drive + meeting transcript that the items were drawn from. Pass `session_docx_path` = the `session_path` value returned by `read_pull_session` in step 1.

Default recipient is `VERIFICATION_TO` env. The tool:
- Writes one `.eml` to `data/requirements/drafts/<YYYY-MM-DD>/` with both files attached
- Pushes the same message into the user's IMAP Drafts folder (Outlook / Gmail web)
- Returns `{drafted, draft_path, absolute_path, imap_appended, drafts_folder, attachments, ...}` — note `attachments` is a list with both filenames

The default email body is auto-selected based on whether one or two attachments are passed; for two it explains both attachments to the client.

Honors `NAPCO_NUCLEUS_DRY_RUN=1` for safe testing — returns `{drafted: false, dry_run: true, ...}` and writes nothing.

### 4.5 Remember each NEW requirement (mandatory after drafting)

For EACH requirement that went into the verification doc (i.e. those that survived step 2.5), call:

`remember_requirement(title="<title>", source="<lowercase channel: email | meetings | chat | documents>", source_ref="<the rel_path / Source ID of the strongest source for this requirement>", summary="<the same summary used in the doc, truncated to <= 240 chars>", client_name="<client identified in step 1.5>")`

`client_name` is REQUIRED when you identified the client in step 1.5 (which you should have for almost every session). Without it, this requirement won't appear in `get_client_history` next time — defeating the client-aware memory loop. Use the same spelling consistently across runs (e.g. always "Acme", not "Acme Corp" one time and "Acme" another).

This writes the requirement into `requirements_seen` so the NEXT collect_all run will dedup it in step 2.5. Do not skip this — without it, the same requirement gets re-drafted on the next run.

Pick the source value from the section the requirement primarily came from: `EMAIL` → `email`, `TEAMS CHAT` → `chat`, `MEETING` → `meetings`, `DRIVE` → `documents`.

### 5. Log + exit

Log a final `log_activity` row like:

"Session verify: N sections in pull doc → R requirements identified → 1 .eml draft (verification → <recipient>) {imap_appended | imap_failed}."

Surface in your final reply:
- Session doc path + started_at
- Section count + section titles
- Requirements identified (count + titles)
- **Mean confidence + low-confidence count** from the verification-doc tool's return value
- Verification doc path
- Verification email draft path (absolute) + recipient + IMAP push status (so the user knows whether to look in Outlook Drafts or open the .eml directly)
- If `low_confidence_count > 0`, explicitly call out the titles of those items in the reply so the reviewer knows which ones to scrutinise before sending.

At the very end of the reply, suggest running the calibration loop:

> Next: when you've decided which requirements to keep, edit, or reject, run `py -3 -m tools.review_session` to log your decisions. They feed the confidence-calibration curve (`py -3 -m tools.calibration_report`) so the LLM's stated confidence becomes more trustworthy over time.

---

## Output language rule

Titles and summaries MUST be written in English, even if the source transcript / chat / email is in Bangla, Malay, or any other language. Translate meaning, not literal words. Preserve proper nouns, endpoint names, field names, and exact client phrasing where it helps a developer understand scope.

## Tone

Plain developer English. No marketing voice, no "streamline / align / optimize" jargon. NO em-dashes (see system.md). Preserve concrete numbers, endpoints, field names. The client reads the verification doc — write like you respect their time.
