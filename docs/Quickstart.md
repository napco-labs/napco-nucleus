# NAPCO Nucleus — Dev PC Setup Guide

What every teammate runs on their own machine to feed Teams chat + call recordings into the central pipeline on MVPACCESS. No Python knowledge needed. No secrets on your machine.

**Updated for the 2026-05 architecture.** If you set up before May 2026 and your machine has a task named `'NAPCO Nucleus - Chat Push'` (singular, no parens), see [Upgrading from the old single-task setup](#upgrading-from-the-old-single-task-setup) at the bottom.

---

## What this is

Two tiny background jobs on your machine:

1. **Three Scheduled Tasks** that push your recent Teams chat (+ any attachments you've downloaded) to the central share on MVPACCESS at different cadences during the day. See [the schedule](#chat-push-schedule).
2. **A voice daemon** that records your Teams calls when it hears a start/stop phrase (24×7 — no time window).

Both run in the background. Zaman triggers the heavy work (transcription, LLM identify, client email draft) on MVPACCESS — you just keep the two tasks alive on your laptop.

### What this asks for

- A path to clone the repo into (any path, **no spaces**).
- One line in `.env` (`NUCLEUS_CENTRAL_PATH`, pre-set).
- Teams stays open + signed in.

### What this does NOT ask for

- No Gmail App Password, IMAP credentials, Claude API key, or Groq key. Every secret lives on MVPACCESS.
- No port forwarding, no VPN configuration beyond what the company VPN already gives you for SMB access to `\\172.16.205.209\nucleus-central`.

---

## Prerequisites

- **Windows 10 or 11.** Teams chat ingest reads Teams' local IndexedDB cache — Windows-only.
- **Microsoft Teams desktop**, signed in, with every client chat opened at least once (so Teams populates its local cache).
- **Git for Windows** installed.
- **SMB access** to `\\172.16.205.209\nucleus-central`. Open File Explorer, paste that path, hit Enter. If it opens, you're good. If it prompts for credentials and your AD account doesn't work, ping Zaman.
- **Admin rights on your laptop**, just for step 4 (registering Scheduled Tasks). You don't need admin for day-to-day operation.

---

## Setup (~10 minutes if no surprises)

### Step 1 — Clone the repo

```
git clone https://github.com/napco-labs/napco-nucleus.git
cd napco-nucleus
```

You can clone anywhere — `C:\napco-nucleus`, `D:\Dev\NAPCO-Nucleus`, `%USERPROFILE%\source\repos\napco-nucleus`, whatever. The install scripts resolve paths relative to themselves; the location doesn't matter.

> **⚠ Avoid paths with spaces** (e.g., `C:\My Projects\…`). The `.bat` scripts mostly handle them but some edge cases bite. Pick a path without spaces and you'll save time.

### Step 2 — Run `setup.bat`

```
scripts\setup.bat
```

Or double-click it in File Explorer. It will:
- Install Python 3.12 if missing (UAC prompt — click **Yes**).
- Create `.venv\` and install all dependencies (~2 min).
- Open `.env` in Notepad for you to confirm one line.

If you see "Python not found" right after, **open a brand-new PowerShell window** and re-run `setup.bat`. The PATH change from a fresh Python install needs a new shell.

### Step 3 — Confirm `.env`

When `.env` opens in Notepad, the only line that matters is:

```
NUCLEUS_CENTRAL_PATH=\\172.16.205.209\nucleus-central
```

It's pre-filled. If you can open `\\172.16.205.209\nucleus-central` in Explorer, it's correct.

Optionally set `NUCLEUS_DEV_NAME` to a friendlier label than your Windows username — that's how your machine identifies itself in the central audit trail.

Save and close Notepad. The script prints **"Setup complete."**

### Step 4 — Register the chat-push Scheduled Tasks (admin)

This is the most common place to trip. Three rules:

1. **Use Administrator PowerShell, not regular PowerShell, not cmd.** Press `Win+X` → "**Terminal (Admin)**" or "**Windows PowerShell (Admin)**" → click **Yes** on the UAC prompt.
2. **Don't double-click `.ps1` files** — they open in Notepad by default. Run them through PowerShell.
3. The first run may need an execution-policy bypass for the current session.

From the admin PowerShell, `cd` into wherever you cloned the repo, then:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\register-chat-push-task.ps1
```

You should see **three** `Registered: …` lines — Day, Transition, Evening — followed by a coverage summary. The script unregisters any old `'NAPCO Nucleus - Chat Push'` task automatically.

#### Chat-push schedule

| Task | BD time | Cadence | Lookback |
|---|---|---|---|
| `… (Day)` | 10:00, 12:00, 14:00, 16:00 | every 2 hr | last 120 min |
| `… (Transition)` | 17:30 | once daily | last 90 min |
| `… (Evening)` | 18:00, 18:30, …, 24:00 | every 30 min | last 30 min |

Higher cadence in the evening — that's peak US-client interaction time.

To remove later: `.\scripts\register-chat-push-task.ps1 -Unregister`

### Step 5 — Start the voice daemon

Double-click `scripts\start-daemon.bat`. Leave the terminal window running (you can minimize it).

The daemon listens for any of these phrases (case-insensitive) and only fires when MS Teams is actually in a call:

- **Start**: "Assalamualaikum", "Salaam alaikum", "Nucleus start", "Start recording", "Record start", "Call start", "Start", "Record"
- **Stop**: "Allah Hafez", "Khoda Hafiz", "Nucleus stop", "Stop recording", "End recording", "Call end", "End", "Stop"

**Now 24×7** — no BD-time-window gate. Records whenever Teams is in a call and you say a start phrase.

To autostart on login, drop a shortcut to `scripts\start-daemon.bat` into `shell:startup` (Win+R → `shell:startup` → Enter → paste shortcut).

---

## Verify install

Three quick checks in **regular PowerShell** (not admin):

```powershell
# 1. Are all three Scheduled Tasks registered and Ready?
Get-ScheduledTask -TaskName 'NAPCO Nucleus*' | Select-Object TaskName, State
```
Expected: three rows — `(Day)`, `(Transition)`, `(Evening)`, all `Ready`. No plain `NAPCO Nucleus - Chat Push`, no `(Backfill)`.

```powershell
# 2. Is the voice daemon running?
Get-Process python -ErrorAction SilentlyContinue
```
Expected: at least one `python.exe` process. If you launched the daemon via the .bat, it'll be there.

```powershell
# 3. Fire one chat-push immediately and check it lands on central.
Start-ScheduledTask -TaskName 'NAPCO Nucleus - Chat Push (Evening)'
Start-Sleep 30
Get-ChildItem "\\172.16.205.209\nucleus-central\$env:USERNAME\$(Get-Date -Format yyyy-MM-dd)\chat\" -ErrorAction SilentlyContinue
```
Expected: a `chat_<HHMM>-<HHMM>.docx` file with a recent `LastWriteTime`. If empty, see [Troubleshooting](#troubleshooting).

---

## Common install gotchas

| Symptom | Cause | Fix |
|---|---|---|
| Double-clicked `.ps1` and it opened in Notepad | Windows file association | Right-click → "Run with PowerShell", or invoke explicitly: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\register-chat-push-task.ps1` |
| "cannot be loaded because running scripts is disabled on this system" | Execution policy | Run once before the script: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| "Access is denied" trying to Unregister an old task | Old task was admin-installed | You're not in admin PowerShell. Reopen as Administrator and retry. |
| `Register-ScheduledTask : Cannot create a file when that file already exists` (HRESULT 0x800700b7) | Orphan task XML on disk | The script's cleanup loop falls back to `schtasks /delete /tn "<name>" /f` automatically — just re-run the script and it'll heal itself. |
| `schtasks : ERROR: The filename, directory name, or volume label syntax is incorrect.` | Task name has a colon | Don't put `:` in a task name. None of our shipping tasks do; this only bites custom registrations. |
| Setup.bat says "Python not found" right after install | PATH not reloaded | Open a brand-new PowerShell and re-run the script. |
| `pip install` fails | Corporate proxy / VPN | Run setup.bat from inside your company VPN. |
| Path with spaces in clone location | Some `.bat` scripts handle them poorly | Re-clone to a space-free path (e.g., `C:\napco-nucleus`). |

---

## Day-to-day operation

| What you want | What you do |
|---|---|
| Get today's Teams chat into the central pipeline | **Nothing.** The Day/Transition/Evening crons handle it automatically during BD 10:00–24:00. The BD 00:00–10:00 gap is unscheduled — if late-night chat needs to land before 10:00, run `scripts\push-chat.bat` manually. |
| Record a Teams call | Say a start phrase ("Assalamualaikum" / "Start" / "Record start") when the call begins. Say a stop phrase ("Allah Hafez" / "Stop" / "End call") when it ends. Recording only fires when Teams is actually in a call. |
| Include a file from Teams chat | Click **Download** on the attachment in Teams. The chat-push picks it up from `~/Downloads` on the next cron tick. Files that aren't downloaded leave only their URL on central — the LLM can't read their content. |
| Pull updates after a `git pull` notice | Double-click `scripts\update.bat` |
| Run a quick ad-hoc push of recent chat | Double-click `scripts\push-chat.bat` (pushes last 15 min) |

### About chat attachments (this catches people)

The push captures chat **messages** + any files that are downloaded locally and live in `~/Downloads` with a matching filename/size. **If a file matters for a requirement, click Download on it in Teams.** Otherwise the LLM sees only the filename and URL, not the content.

---

## Troubleshooting

**Scheduled task ran but no file on central.**
Verify the SMB share is reachable: `Test-Path \\172.16.205.209\nucleus-central`. If False, get on the VPN or ask Zaman for share access.

**Voice daemon prints "no Teams session in Active state".**
That's the Teams-only gate working as designed — Teams must be ringing or in a call. Pass `--allow-any-call` to disable (rarely needed): `python -m teams.voice_daemon --allow-any-call`.

**Recording captured your voice but not the other party's.**
Open Teams → Settings → Devices → set Speaker to "Same as system / Default". Teams's separate "Communications Device" default makes Windows WASAPI loopback miss the other party.

**Teams chat ingest captures nothing even though I'm chatting.**
Teams reads its IndexedDB on disk. The chats you want captured must have been opened at least once in the desktop client (so Teams writes their content to disk). Open each client conversation in Teams once and let it load fully.

**Anything else.** Ping Zaman with the exact error message and which step you were on.

---

## Upgrading from the old single-task setup

If `Get-ScheduledTask -TaskName 'NAPCO Nucleus*'` shows a plain `NAPCO Nucleus - Chat Push` (singular, no parens) — you're on the pre-2026-05 single-task setup. Upgrade:

```powershell
cd <your repo path>
git pull
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\register-chat-push-task.ps1
```

The script unregisters the old `Chat Push` + `Chat Push (Backfill)` tasks and installs the new Day/Transition/Evening triple. Verify with the same `Get-ScheduledTask` command afterward — you should see exactly three tasks, all Ready.

---

For the MVPACCESS (agent host) setup — different machine, different role — see `docs/Central_Setup.md`.
