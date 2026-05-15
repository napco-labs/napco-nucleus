# NAPCO Nucleus — Claude Code instructions

This file is auto-loaded into every Claude Code session opened inside this repo. It tells you (Claude Code) how to recognize voice-command-style instructions from the developer and what to do when they're issued.

## Call recording — voice commands in chat

When the developer (the person typing into Claude Code) says any of these phrases — **case-insensitive, anywhere in the message** — start recording the Teams call on their machine immediately:

- `call start` / `record start` / `call record start`
- `start call` / `start record` / `start recording`
- `record` (as a standalone command)
- `start` (as a standalone command, when context is obviously about recording)
- `nucleus start`
- Bangla: `assalamualaikum`, `as-salamu alaikum`, `salaam alaikum`, `salam alaikum`

**Action — start:** Run this command in the background (so the dev's terminal stays interactive):

```bash
py -3 -m teams.record_call
```

Use `run_in_background=true` on the Bash call. Confirm to the developer with one sentence: *"Recording started — call audio is being captured on both tracks."*

When the developer says any of these — opposite intent:

- `call end` / `record end` / `call record end`
- `stop call` / `stop record` / `stop recording`
- `end call` / `end record` / `end recording`
- `stop` / `end` (as standalone commands when the recording context is active)
- `nucleus stop`
- Bangla: `allah hafez`, `allah hafiz`, `khoda hafez`, `khoda hafiz`

**Action — stop:** Run this command (foreground, fast):

```bash
py -3 -m teams.stop_recording
```

This drops a sentinel file the recorder polls every ~0.5s. The recorder closes the WAVs cleanly and uploads them to the central share (`NUCLEUS_CENTRAL_PATH` env). Confirm with one sentence: *"Recording stopped — files are being uploaded to the central share."*

### Important behavior rules

- **Don't ask for confirmation.** If the developer says "call start", they want it started — they're already on the call. Asking "are you sure?" defeats the point. Just run the command and confirm what happened.
- **Background mode for `record_call`** is non-negotiable. The recorder is a long-running process; if you run it foreground, you'll lock the developer's terminal for the whole call.
- **One recording at a time per machine.** If a recording is already running and the dev says "start", say so plainly — don't start a second one.
- **Don't gate on whether Teams has an active call from your side.** The voice daemon does that for audio triggers; for typed commands, trust the developer.

## Other common dev commands they might ask about

| Developer says | You run |
|---|---|
| "push my chat now" / "send chat to central" | `scripts\push-chat.bat` (last 15 min) — Scheduled Task names are now split: `'NAPCO Nucleus - Chat Push (Day)'` and `'NAPCO Nucleus - Chat Push (Evening)'`. |
| "verify install" / "check setup" | `py -3 -m tools.healthcheck` |
| "run it right now for X" / "do it right now X" | `py -3 do_it_now.py --client "X" --last-minutes 60` (defer to wider window if X is a multi-day client) |
| "review the draft" / "review session" | `py -3 -m tools.review_session` |
| "calibration report" / "show curve" | `py -3 -m tools.calibration_report` |
| "today's summary" | `py -3 -m tools.daily_summary` |
| "what did this cost" / "cost report" | `py -3 -m tools.cost_report --since 7d` |
| "poll replies" / "any client replies" | `py -3 -m tools.poll_replies --days 7` |
| "show latest trace" / "what just happened" | `py -3 -m tools.replay_trace --latest` |

## Project quick-orient (for new sessions)

- **Goal**: turn multi-channel client communications (Teams chat, Teams audio, email + attachments, Google Drive files) into a verified requirements doc + a Gmail draft to the client.
- **Topology** (since 2026-05-14 migration): each dev's machine captures and pushes; the **central host** is `172.16.205.123` (Ubuntu Linux, docker-compose stack) — six containers handle Samba share, transcribe loop, email + Drive stagers, the daily-draft Claude pass, and a GHA runner. The old MVPACCESS box (`.209`) is retired from Nucleus duty but kept alive for unrelated work.
- **Central share**: `\\172.16.205.123\nucleus-central\<dev>\<date>\` — chat .docx, attachments, call .wav + metadata.
- **Daily auto-fire** at 23:45 BD inside `nucleus-daily-draft` container runs `collect_central.py --client all --last-minutes 1440` (NOT `do_it_now.py` — that one SSHes to self).
- **Call recording trigger**: default is **automatic on Teams audio-session edge** (no phrase needed). Verbal phrases ("Assalamualaikum" / "Allah Hafez" / "nucleus start"...) remain armed as fallback, including the typed commands in the section above.
- **Recording scope**: MS Teams ONLY (`ms-teams.exe`, `teams.exe`, `msteams.exe`). Never widen to Zoom / Google Meet / etc. without explicit user greenlight.
- **Memory DB**: `nucleus_memory.db` (SQLite) holds `requirements_seen`, `activity_logs`, `requirement_reviews`, etc. On `.123` it's a named docker volume at `/state/`; on dev machines it's in `data/`.
- **Tracing**: every `pipeline.py` run writes `data/traces/<date>/<run_id>.jsonl`. Use `tools/replay_trace.py` to inspect.
- **Per-developer setup**: see `docs/Developer_Setup.md` (canonical, kept current). Older `docs/Setup_Guide.pdf` is being phased out. No secrets in dev `.env` — only `NUCLEUS_CENTRAL_PATH`.
- **Boss-facing deck**: the canonical "Requirement Management" presentation at `~/Downloads/NAPCO-Nucleus-Requirement-Management.pptx` is actually generated by `scripts/generate_system_overview_ppt.py` (file-name asymmetry — DON'T edit `generate_requirement_management_ppt.py` thinking it's the canonical; it's a team-facing variant Titu doesn't present from).

## Client identity & roster filter

NN serves multiple clients, not just one. Two buckets exist on the wire:

- **`@napcosecurity.com`** → `client_name = "NAPCO Security"`. All senders at
  this domain (Michael Carrieri, Salman Firoz, Siva, Richard Goldsobel, Robert
  Zhu) collapse into one bucket. NAPCO Security is the external client.
- **`@ael-bd.com`** → `client_name = <the individual's full name>`. AEL senders
  are NOT forwards on behalf of NAPCO — they are AEL-internal client requests,
  and each stakeholder is their own bucket. Don't lump them together.

Resolution order when tagging a message:

1. Sender domain matches `@napcosecurity.com` → `"NAPCO Security"`.
2. Sender domain matches `@ael-bd.com` → the individual's full name (canonical
   names sit alongside their addresses in `napco_config.REQUIREMENT_ROSTER`).
3. Body explicitly says "forwarding NAPCO's ask" → override to `"NAPCO Security"`.
4. Other domains → infer from content, prefer organization name when stated.

Spelling matters — `requirements_seen` dedup is normalized, but
`get_client_history` does case-insensitive *exact* match on the bucket name.

### Requirement-management roster filter

Not every email at `@napcosecurity.com` or `@ael-bd.com` is requirements work.
`mail/pull_email.py` only keeps a message when **≥1 address from
`napco_config.REQUIREMENT_ROSTER`** appears in **From, To, Cc, or Bcc**. Zero
matches → silently skipped; the count surfaces in the run summary.

Override mechanisms:

- `python -m mail.pull_email --ignore-roster ...` — one-off bypass for debug
  pulls. Requirement-management runs should not use this.
- `NUCLEUS_ROSTER_EXTRA=a@x.com,b@y.com` in `.env` — per-machine additions.
  Promote to `REQUIREMENT_ROSTER` in `napco_config.py` once the change is
  permanent so the whole team picks it up.

Roster is in code (`napco_config.REQUIREMENT_ROSTER`), single source of truth.
Update via PR when the working group changes.

## Style conventions for code in this repo

- Python 3.11+; Windows-targeted (Teams ingest reads Windows IndexedDB).
- Lazy imports inside functions for heavy deps (faster-whisper, python-docx, etc.) so import time stays fast.
- `_session_doc.append_section()` is the single canonical way to add content to the pull-session doc.
- Source IDs follow `<channel>/<headline-slug>/<8-char-sha1>` — never paraphrase, always copy verbatim.
- New tools live in `tools/`, prefixed with `_` if they're helpers not meant for direct CLI use.

## What NOT to do

- Don't write to `central` directly — go through `push_chat.py` or `record_call.py`.
- Don't add `ANTHROPIC_API_KEY` as a secret. Claude calls go through the local CLI on each user's machine, or through MVPACCESS's authenticated session for the identify pipeline.
- Don't bypass the Drafts review step. The agent never sends client emails directly — drafts only.
- Don't change prompts in `prompts/` casually. Each change can shift calibration; run `evals/run.py` to verify after a prompt change.
