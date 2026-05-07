# Requirement Management Workflow
## On-Demand Model for NAPCO Nucleus

| | |
|---|---|
| **Owner** | Mohammad Kamrul Hasan (Titu) |
| **System** | NAPCO Nucleus (NN) |
| **Date** | 7 May 2026 |
| **Status** | Draft for management review |

---

## 1. Purpose

Client requirements arrive across fragmented channels — Microsoft Teams calls, Teams chats and DMs, email, and Google Drive. Consolidating them into auditable documents is presently a manual, time-consuming task. This workflow puts NAPCO Nucleus behind that capture, while keeping every outbound action under direct human control.

## 2. Operating Principles

Four non-negotiable principles govern this workflow.

- **User-triggered.** NAPCO Nucleus performs work only on explicit command. There is no scheduled background polling of any channel.
- **Human-in-the-loop.** Every requirement document is reviewed by Mohammad before any email draft is composed.
- **No automated outbound email.** NAPCO Nucleus prepares the draft and the attachment. Mohammad sends the email himself, from his own mail client.
- **Speaker attribution preserved on calls.** Mohammad's voice and the other party's voice are recorded on separate tracks so summaries cannot misattribute who said what.

## 3. Input Channels

| Channel | Mechanism | What it captures |
|---|---|---|
| **Teams audio calls** | Local recording — microphone + system loopback | Dual-track audio; transcribed and translated to English (faster-whisper large-v3) |
| **Teams messages** | Reads Teams desktop's local message cache | Group chats and DMs, queryable by chat name and time range |
| **Email** | IMAP poll of allowlisted senders | Message bodies (attachment parsing is future scope) |
| **Google Drive** | Drive API + content extractors | Audio (Whisper), PDF (pypdf), Word `.docx` (python-docx), plain text |

## 4. Core Workflow Steps

1. **Capture** — Mohammad triggers a read or a recording for the channel he wants.
2. **Process** — NAPCO Nucleus handles transcription, translation, or parsing as the channel requires.
3. **Output** — A structured Microsoft Word document is produced for Mohammad's review.
4. **Final action** — On request, NAPCO Nucleus composes a draft email with the document attached. Mohammad reviews and sends it manually.

## 5. Technical Foundation

The workflow reuses components already present in the `napco-labs` codebase. No new external services and no new self-hosted runners are required.

- **Teams Requirement Watcher (TRW)** — existing call-recording and call-transcription pipeline. Bangla → English translation is built in.
- **NAPCO Nucleus core** — existing Word document writers, IMAP email reader, and Google Drive content ingest.

## 6. Items Pending Approval

Before implementation continues, three items need confirmation:

1. The proposed on-demand operational model.
2. The designated Google Drive folder for audio archival.
3. Confirmation that direct OpenProject integration is **not** required at this stage.

---

*Prepared by Mohammad Kamrul Hasan — Senior Software Test Engineer, Adaptive Enterprise Limited*
