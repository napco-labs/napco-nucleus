# NAPCO Nucleus — Quickstart for Teammates

Five steps to get your machine streaming Teams chat, attachments, and call recordings into the central agent on MVPACCESS. No Python knowledge needed.

## What this is

Your machine runs two tiny background jobs:

1. A **15-minute scheduled task** that pushes your recent Teams chat (+ any attachments you've downloaded) to a shared folder on MVPACCESS.
2. A **voice daemon** that records your Teams calls when it hears the start/stop phrases.

That's it. Titu triggers the heavy work (LLM identify + client email draft) from the agent host. You just keep these two running.

## First-time setup (~10 minutes)

### 1. Prerequisites

- **Windows 10 or 11** (Teams chat ingest is Windows-only — it reads Teams' local IndexedDB)
- **MS Teams desktop**, signed in, with the client chats already opened at least once
- **Git for Windows** installed
- **Network access** to the central share (you should be able to open `\\172.16.205.209\nucleus-central` in File Explorer). If not, ping Titu for credentials.

### 2. Clone the repo

```
git clone https://github.com/napco-labs/napco-nucleus.git
cd napco-nucleus
```

### 3. Double-click `scripts\setup.bat`

It will:
- Install Python 3.12 if missing (UAC prompt — click Yes)
- Create `.venv\` and install all dependencies
- Open `.env` in Notepad (pre-filled — **no secrets needed**)

> **No Gmail App Password, no API key, nothing private.** The agent host (MVPACCESS) owns every credential — pulling email, posting drafts, hitting the LLM all happen there. Your machine only writes Teams chat/calls into a network folder using your normal Windows login.

In Notepad, just confirm `NUCLEUS_CENTRAL_PATH` matches the team's share (it ships pre-set to `\\172.16.205.209\nucleus-central`). Optionally set `NUCLEUS_DEV_NAME` to a friendlier label than your Windows username. Save and close.

You're done when you see "Setup complete."

### 4. Register the 15-min chat-push as a Windows scheduled task

In an **admin PowerShell** (Start → "PowerShell" → right-click → Run as administrator), from inside the repo:

```
.\scripts\register-chat-push-task.ps1
```

This creates a "NAPCO Nucleus - Chat Push" entry in Task Scheduler that runs every 15 min, even when you're not logged in. To verify: Task Scheduler → Task Scheduler Library → look for the entry.

To remove later: `.\scripts\register-chat-push-task.ps1 -Unregister`

### 5. Start the voice daemon

Double-click `scripts\start-daemon.bat`. Leave the terminal window running. (To autostart on login, drop a shortcut to the .bat into `shell:startup`.)

## You're set. Verify it's working.

Run `Start-ScheduledTask -TaskName 'NAPCO Nucleus - Chat Push'` in PowerShell to fire one push immediately. Then look at `\\172.16.205.209\nucleus-central\<your name>\<today's date>\chat\` — you should see a `chat_<HHMM>-<HHMM>.docx` appear within ~30 seconds. If you don't, see Troubleshooting.

## Day-to-day

| What you want | What you do |
|---|---|
| Get your activity into the central pipeline | **Nothing** — the cron handles it every 15 min |
| Record a Teams call | Say a start phrase ("Start", "Start recording", or "Assalamualaikum") when the call begins; a stop phrase ("Stop", "End call", or "Allah Hafez") when it ends. Full list below. The daemon only records during real Teams calls. |
| Include a file someone shared in Teams chat | Click **Download** on the chat attachment. Files in your `~/Downloads` matching the chat's filename + size get auto-pushed to central on the next cron tick. |
| Pull updates after a `git pull` notice | Double-click `scripts\update.bat` |
| Run an ad-hoc local pull (your own session, not the team's) | Double-click `scripts\pull-now.bat` |

### Voice phrases

The daemon listens for any of these (case-insensitive):

- **Start recording** — "Assalamualaikum", "Salaam alaikum", "Nucleus start", "Start recording", "Start record", "Start call", "Record start", "Call start", "Start", "Record"
- **Stop recording** — "Allah Hafez", "Khoda Hafiz", "Nucleus stop", "Stop recording", "Stop record", "End recording", "End record", "End call", "Record end", "Call end", "End", "Stop"

Recording only fires when MS Teams has an active call (ringing or in-progress). Saying any phrase with Teams idle does nothing — by design. To edit phrases, open `data\teams\voice_phrases.json` and restart the daemon.

### About chat attachments (important!)

The system pushes Teams chat files **only if you've downloaded them locally**. If a teammate shares `requirements.pdf` in chat and you never click "Download" on it, the file's content won't reach the LLM — only its filename and a URL will. **If a file matters for a client requirement, click Download**.

## Troubleshooting

- **"Python not found"** after running setup.bat: open a brand-new PowerShell and re-run setup. The PATH change from winget needs a fresh shell.
- **Scheduled task ran but no file on central**: check the SMB share is reachable from your machine (`Test-Path \\172.16.205.209\nucleus-central`). If not, get an account on MVPACCESS from Titu.
- **Voice daemon prints "no Teams session in Active state"**: that's the Teams-only gate working as designed. Pass `--allow-any-call` to disable: `python -m teams.voice_daemon --allow-any-call`.
- **Recording captured your voice but nothing else**: Teams → Settings → Devices → set Speaker = "Same as system / Default". Teams's separate Communications Device default makes the WASAPI loopback miss the other party.
- **"pip install failed"** in setup.bat: usually a corporate proxy issue. Run setup.bat again from inside your VPN.

For anything else, ping Titu.
