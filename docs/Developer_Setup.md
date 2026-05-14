# NAPCO Nucleus — Developer Setup Guide

**Audience:** new dev getting started on Nucleus. By the end of this guide, your machine is recording Teams calls, pushing chat to central, and the daily Requirement Management draft will include your day's content automatically.

**Time:** ~25 minutes if everything goes smoothly.

**Asks for help from Titu:** the shared `.env` contents (with `GROQ_API_KEY`, Google creds, etc.) and the Samba password for `172.16.205.123`.

---

## What you'll have running when this is done

- **Voice daemon** — listens 24/7 for Teams calls and auto-records mic + speaker. No phrase / button — just open Teams and call.
- **Chat-push tasks** — three Scheduled Tasks that push your Teams chat to central (BD-local: every 2 hr 10:00→17:00, once at 17:30, every 30 min 18:00→24:00).
- **Cached Samba credentials** — so Windows mounts `\\172.16.205.123\nucleus-central\` without prompting.

Everything else (transcribe, email pull, Drive pull, daily Requirement Management, Claude verification email) runs on `172.16.205.123` (Ubuntu Linux). You don't have to set those up — they run for the whole team.

---

## Prerequisites

| Need | Version |
|---|---|
| Windows 10 / 11 | any |
| Python | 3.12+ from python.org — **NOT** the Microsoft Store stub |
| Git for Windows | any recent |
| Network | on the `172.16.205.*` AEL subnet (office or VPN) |
| MS Teams desktop app | logged in with your work account |
| Tesseract OCR | 5.x — used to OCR screenshots in Teams chat (Bangla pack included) |

If Python came from the Microsoft Store, `pyaudio` will fail to install. Get it from `https://www.python.org/downloads/`.

---

## Step 1 — Clone the repo

```powershell
# pick a drive with ~5 GB free; E:\ is the convention
cd E:\
mkdir Projects -Force
cd E:\Projects
git clone https://github.com/napco-labs/napco-nucleus.git NAPCO-Nucleus
cd E:\Projects\NAPCO-Nucleus
```

If `git clone` asks for a GitHub login, sign in with your `napco-labs` org membership. If you don't have access, ask Titu to add you to the org.

If you don't have an `E:` drive, use `C:` — but then **every command below that says `E:\Projects\NAPCO-Nucleus` needs to be your actual path.**

---

## Step 2 — Install Python dependencies

```powershell
cd E:\Projects\NAPCO-Nucleus
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

This pulls a few hundred MB (faster-whisper model loader, Claude SDK, Google APIs, etc.). Takes 3-5 min.

**Verify:**
```powershell
python -c "import claude_agent_sdk, faster_whisper, pyaudiowpatch, pycaw; print('deps OK')"
```
You should see `deps OK`. If not, fix the offending package before continuing.

---

## Step 3 — Install Tesseract (for chat screenshot OCR)

The chat-push task OCRs images shared in Teams chat. It needs the Tesseract binary on `PATH`.

```powershell
winget install UB-Mannheim.TesseractOCR
```

For Bangla screenshots, also install the Bangla language data — easiest path is to run the installer GUI from `C:\Program Files\Tesseract-OCR\` and check the "Bengali" language pack, or download `ben.traineddata` manually into `C:\Program Files\Tesseract-OCR\tessdata\`.

**Verify:**
```powershell
tesseract --version
```
Should print version 5.x. If `tesseract` is not recognized, close + reopen your terminal so it picks up the new PATH.

---

## Step 4 — Get the `.env` from Titu

The `.env` carries secrets that aren't in the repo — `GROQ_API_KEY`, Gmail SMTP password, Drive folder ID, OpenProject API key, etc. **Ask Titu** to send you the current `.env` over a private channel (not group chat).

Save it as:
```
E:\Projects\NAPCO-Nucleus\.env
```

Then **change one line** — your `NUCLEUS_DEV_NAME`:

| If you are | Edit `.env` to say |
|---|---|
| Assad | `NUCLEUS_DEV_NAME=Assad` |
| Rocky | `NUCLEUS_DEV_NAME=Rocky` |
| Ferdows | `NUCLEUS_DEV_NAME=Ferdows` |
| Titu | `NUCLEUS_DEV_NAME=Titu` |
| Atik | `NUCLEUS_DEV_NAME=Atik` |
| Isruk | `NUCLEUS_DEV_NAME=Isruk` |
| Amin | `NUCLEUS_DEV_NAME=Amin` |

This is the folder name your calls and chats land under on central. **Get it right — it tags every artifact you produce.**

Also confirm this line is correct (it should already be set):
```
NUCLEUS_CENTRAL_PATH=\\172.16.205.123\nucleus-central
```

---

## Step 5 — Cache the Samba credentials

`\\172.16.205.123\nucleus-central` is served by a Samba container on the Linux central. Windows needs the cred cached so background tasks can write to it without a prompt.

Ask Titu for the Samba password (the `nucleus` user — single shared account). Then:

```powershell
cmdkey /add:172.16.205.123 /user:nucleus /pass:<the_password_from_titu>
```

**Verify the share is reachable:**
```powershell
Test-Path \\172.16.205.123\nucleus-central
```
Should print `True`. If it prints `False` or hangs:
- Are you on the AEL subnet? Try `ping 172.16.205.123`
- Did `cmdkey` succeed? Run `cmdkey /list:172.16.205.123` and check.

**Verify your dev folder will be writable:**
```powershell
$you = (Select-String -Path E:\Projects\NAPCO-Nucleus\.env -Pattern '^NUCLEUS_DEV_NAME=').Line -replace 'NUCLEUS_DEV_NAME=',''
$today = Get-Date -Format "yyyy-MM-dd"
New-Item -ItemType Directory -Force "\\172.16.205.123\nucleus-central\$you\$today\calls" | Out-Null
"setup smoke test from $env:COMPUTERNAME" | Out-File "\\172.16.205.123\nucleus-central\$you\$today\calls\setup-test.txt"
Get-ChildItem "\\172.16.205.123\nucleus-central\$you\$today\calls\"
Remove-Item "\\172.16.205.123\nucleus-central\$you\$today\calls\setup-test.txt"
```
You should see your test file listed, then have it cleaned up. If anything errors, fix it before continuing — the daemon will fail the same way.

---

## Step 6 — Register the Voice Daemon Scheduled Task

This is what auto-records every Teams call.

```powershell
cd E:\Projects\NAPCO-Nucleus
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\register-voice-daemon-task.ps1
```

This:
- Registers a Scheduled Task `NAPCO Nucleus - Voice Daemon` that fires on every logon
- Wraps the daemon in a hidden VBS launcher so no cmd window pops up
- Redirects logs to `E:\Projects\NAPCO-Nucleus\logs\voice_daemon.log`

**Start it now** (without needing a logoff):
```powershell
Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
```

**Verify it's actually running:**
```powershell
Get-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon' | Select-Object State
```
Should say `Running`. If it says `Ready`, the task started and exited — see Troubleshooting.

---

## Step 7 — Register the Chat-Push Scheduled Tasks

This is what pushes your Teams chat content to central.

```powershell
cd E:\Projects\NAPCO-Nucleus
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\register-chat-push-task.ps1
```

This registers **three** tasks, all on your BD-local clock:

| Task | When it fires | Window pushed |
|---|---|---|
| `NAPCO Nucleus - Chat Push (Day)` | every 2 hr from 10:00 → 17:00 (fires at 10/12/14/16) | last 120 min |
| `NAPCO Nucleus - Chat Push (Transition)` | once at 17:30 | last 90 min (bridges 16→18) |
| `NAPCO Nucleus - Chat Push (Evening)` | every 30 min from 18:00 → 24:00 | last 30 min (US-client peak) |

Overnight 00:00–10:00 has no auto-push by design. If you have late-night chat that matters, run manually:
```powershell
cd E:\Projects\NAPCO-Nucleus
python -m teams.push_chat --last-minutes 600
```

---

## Step 8 — Verify the voice daemon is alive

Open a second terminal and tail the log:
```powershell
Get-Content E:\Projects\NAPCO-Nucleus\logs\voice_daemon.log -Wait -Tail 30
```

You should see lines like:
```
[voice] phrase list: 16 start phrase(s), 17 stop phrase(s)
[voice] loading faster-whisper base...
[voice] model loaded.
[voice] mic: 'Microphone (...)' @ 16000 Hz
[voice] Teams-only gate ON
[voice] trigger mode: auto
[voice] listening for start/stop phrases.
[voice] auto watcher: poll=2.0s, stop_debounce=2 polls, hard_cap=3600s
```

If you don't see those, the daemon didn't start. See Troubleshooting.

Leave that terminal open. It's your real-time view of the daemon for the next step.

---

## Step 9 — Make a test call (the real validation)

Call any colleague on Teams. A 30-second hello is enough.

In the tail terminal, within ~2 seconds of the call going active you should see:
```
[voice] watcher: rising edge — ms-teams.exe state=Active
[voice] Teams gate OK: ms-teams.exe state=Active
[voice] starting recorder...
[voice] recorder PID 1234
```

Hang up. Within ~6 seconds:
```
[voice] watcher: falling edge (off for 2 polls) — no Teams session in Active state
[voice] stop sentinel written (session ended); waiting for recorder to flush...
  mic normalize: peak 4200 -> 29225, gain +17.7 dB
  mic denoise: hpf<40Hz, 20 notches at multiples of 50Hz
[voice] recorder exited rc=0
```

**Check central** — your WAVs should be there:
```powershell
$you = (Select-String -Path E:\Projects\NAPCO-Nucleus\.env -Pattern '^NUCLEUS_DEV_NAME=').Line -replace 'NUCLEUS_DEV_NAME=',''
$today = Get-Date -Format "yyyy-MM-dd"
Get-ChildItem "\\172.16.205.123\nucleus-central\$you\$today\calls\" | Format-Table Name, Length, LastWriteTime
```

You should see `<stamp>_mic.wav`, `<stamp>_speaker.wav`, `<stamp>.json`. Within ~2 minutes a `<stamp>_transcript.md` will also appear (transcribed by the worker on `.123` via Groq).

**If you've gotten this far: you're done.** Your machine is fully wired into the Nucleus pipeline.

---

## Troubleshooting

### Voice daemon shows `Ready` (not `Running`)

The daemon started and exited. Most common cause: missing dependency or a config error. Check the log:
```powershell
Get-Content E:\Projects\NAPCO-Nucleus\logs\voice_daemon.log -Tail 50
```

The last few lines tell you what went wrong. Common issues:
- `ModuleNotFoundError` — `pip install -r requirements.txt` didn't finish. Retry it.
- `pyaudio` errors — you have the Microsoft Store Python. Uninstall it; install from python.org.
- Mic permission denied — Windows Settings → Privacy → Microphone → allow desktop apps.

Once fixed, re-start:
```powershell
Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
```

### `Test-Path \\172.16.205.123\nucleus-central` says `False`

- Are you on the AEL subnet? `ping 172.16.205.123` should respond.
- Are creds cached? `cmdkey /list:172.16.205.123` should show user `nucleus`. If not, repeat Step 5.
- Is `.123` reachable on port 445? `Test-NetConnection 172.16.205.123 -Port 445`. If "closed," the Samba container is down — ping Titu.

### Calls aren't appearing on central

1. Did the daemon detect the call? Look in the log for `rising edge`. If absent, the daemon's Teams audio-session probe didn't fire — check that Teams is actually playing audio (a chat voice note doesn't count as a call).
2. Did the recorder finish? Look for `recorder exited rc=0` and the size-listing line. If `rc != 0`, the recorder crashed mid-call.
3. Did central upload succeed? Look for the line `central upload: OK (\\172.16.205.123\nucleus-central\...)`. If you see `central upload FAILED`, Samba auth broke — re-do Step 5.

### "I made a call and only a `_speaker.wav` showed up — no `_mic.wav`"

Your mic input device isn't picking up audio. Most common cause: Teams is using a different mic than the one Windows reports as "default input." Open Teams → Settings → Devices → set Microphone to the same device Windows reports as default. Restart the daemon.

### Local disk filling up

`E:\Projects\NAPCO-Nucleus\data\teams\calls\` accumulates WAVs (~10 MB each). They're copied to central, but the local copies aren't auto-deleted. Once a week or so, clear it:
```powershell
Remove-Item E:\Projects\NAPCO-Nucleus\data\teams\calls\* -Force
```

---

## Where to look when something breaks

| Symptom | Look here |
|---|---|
| Voice daemon won't start | `E:\Projects\NAPCO-Nucleus\logs\voice_daemon.log` |
| Chat-push not firing | `Get-ScheduledTask -TaskName 'NAPCO Nucleus - Chat Push *'` |
| Calls land locally but not on central | Samba creds (Step 5), `ping 172.16.205.123` |
| No transcript appears next to your WAVs | Ask Titu — that's the `nucleus-transcribe` container on `.123`, not your machine |
| Daily Requirement Management email didn't arrive | Same — `.123` runs that at BD 23:45 |

---

## How to update when there's a new version

Whenever Titu announces "pull and re-register":
```powershell
cd E:\Projects\NAPCO-Nucleus
git pull
python -m pip install -r requirements.txt        # only if requirements changed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\register-voice-daemon-task.ps1
Stop-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
```

`record_call.py` re-reads the repo on every call, so most code updates take effect on the next call automatically. The daemon itself only re-reads on restart.

---

## How to uninstall

If you're leaving the team or rebuilding your PC:
```powershell
cd E:\Projects\NAPCO-Nucleus
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\register-voice-daemon-task.ps1 -Unregister
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\register-chat-push-task.ps1 -Unregister
cmdkey /delete:172.16.205.123
```
Then delete `E:\Projects\NAPCO-Nucleus\` if you want.

---

## Who to ask

| Topic | Contact |
|---|---|
| `.env`, Samba password, GitHub access | Titu (`titucse@gmail.com`) |
| Linux central host (`.123`) issues | Titu (or check `https://github.com/napco-labs/napco-nucleus` issues) |
| Voice daemon bugs / mic problems | File an issue on GitHub with the relevant log excerpt |
| Anything else | Ask in the team Teams channel |
