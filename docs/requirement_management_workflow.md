# Requirement Management Workflow — On-Demand Model

| | |
|---|---|
| **Owner** | Mohammad Kamrul Hasan (Titu) |
| **System** | NAPCO Nucleus (NN) |
| **Date** | 2026-05-07 |
| **Status** | Draft for management review |

---

## 1. Purpose

Today, client requirements arrive through several channels — Microsoft Teams audio calls, Teams group chats and DMs, email with PDF / Word attachments, and files placed in Google Drive. Capturing those requirements into one auditable document is currently a manual, time-consuming task.

This workflow uses NAPCO Nucleus to assist with that capture — without removing human review or letting anything leave the system without explicit approval.

## 2. Operating Principles

- **User-triggered, not scheduled.** NAPCO Nucleus performs work only when Mohammad issues a command. There is no automatic background polling of Teams, email, or Drive.
- **Human-in-the-loop.** Every requirement document is reviewed by Mohammad before any email is drafted or sent.
- **No automated outbound email.** NAPCO Nucleus prepares the draft email and the attached document. Mohammad sends the email manually from his own mail client.
- **Speaker attribution preserved on calls.** Recordings retain who said what — Mohammad versus the other party — so summaries are not ambiguous.

## 3. Input Channels

| Channel | Source | Notes |
|---|---|---|
| Teams audio calls | Microsoft Teams desktop on Mohammad's machine | Both 1:1 client calls and calls where multiple developers are joining are supported |
| Teams group chats and DMs | Microsoft Teams desktop's local message cache | Any group or DM, identified by name on the spot |
| Email (text + attachments) | Mohammad's mailbox `khasan@ael-bd.com` (additional inboxes can be added later) | Includes PDF and Word attachments |
| Google Drive files | A folder owned by `khasan@ael-bd.com` (location supplied per request) | Includes PDF, Word, and audio files placed by clients |

## 4. User Commands and System Behavior

The four supported commands. In each case Mohammad issues the command; NAPCO Nucleus performs only what is asked.

### 4.1 Read Teams messages

> "Read the Teams messages from `<group or DM>` for the last `<N>` hours" — or — "from `<start time>` to `<end time>`."

NAPCO Nucleus reads the requested messages from the Teams desktop's local cache, identifies the requirements within them, and presents a detailed summary on screen for Mohammad's review.

### 4.2 Read email

> "Read emails from `<sender>` / matching `<subject>` / between `<start time>` and `<end time>`."

NAPCO Nucleus reads matching emails from the configured mailbox, extracts requirements from the body and from any PDF / Word attachments, and presents a detailed summary on screen.

### 4.3 Read Drive files

> "Read the Drive file `<filename>`" — or — "Read Drive files in `<folder>` between `<start time>` and `<end time>`."

NAPCO Nucleus fetches the requested files from the specified Google Drive folder, extracts requirements from each, and presents a detailed summary on screen. Audio files are handled per Section 5.

### 4.4 Prepare email for manual send

> "Prepare the email with the attached document."

NAPCO Nucleus composes the email subject and body and attaches the Word document already produced. Mohammad reviews and **sends the email manually** from his mail client.

## 5. Audio Call Recording Flow

For Teams audio calls happening on Mohammad's machine, three commands cover the full lifecycle.

| Step | Command from Mohammad | NAPCO Nucleus action |
|---|---|---|
| 1 | "Start recording." | Begin recording — captures both Mohammad's microphone and the system speaker output (the other party's voice) as separate tracks so speaker attribution is preserved. |
| 2 | "Stop recording." | Finalise the audio files and upload them to the agreed Google Drive folder. |
| 3 | "Process the recording." | Retrieve the audio from Google Drive, run speech-to-text on it, translate the transcript to English (the call may be in Bangla), identify the requirements, and produce the same kind of Word document summary as the other channels. |

## 6. Outputs

For every "Read …" or "Process …" command, NAPCO Nucleus produces:

1. **A Microsoft Word document** containing the structured requirement summary, saved for Mohammad's review.
2. **The original raw material reference** — chat range, email message IDs, Drive file IDs, or audio session — so the source of every requirement is traceable.

When Mohammad asks for it, NAPCO Nucleus then prepares a draft email with that Word document attached. Mohammad sends the email himself.

## 7. Explicitly Out of Scope

To set boundaries clearly, NAPCO Nucleus will **not** do the following in this workflow:

- Automatic, scheduled collection of Teams messages, email, or Drive files
- Automatic sending of email — every email leaves Mohammad's mailbox manually, with his explicit action
- Publishing items to OpenProject or any other project-management system
- Replacing client conversations — this workflow is a structured capture aid, not a substitute for client engagement

## 8. Reuse of Existing Components

The workflow reuses components that are already in place inside the napco-labs codebase:

- **Teams Requirement Watcher (TRW):** existing call-recording and call-transcription pipeline (faster-whisper large-v3, Bangla → English)
- **NAPCO Nucleus tools:** existing Word-document writers, email-draft helpers, Google Drive integration, and IMAP email integration

No new self-hosted runners, no scheduled GitHub Actions workflows, and no new external services are required.

## 9. Open Items Pending Confirmation

Before development of this workflow is finalised, three items need confirmation:

1. The specific Google Drive folder for audio uploads (location).
2. The recurring Teams chats and DMs Mohammad expects to query most often (so they can be resolved by name reliably).
3. **Management approval of this workflow document** before further build work continues.

---

*Reviewed and prepared by Mohammad Kamrul Hasan. Please return any change requests directly to Mohammad.*
