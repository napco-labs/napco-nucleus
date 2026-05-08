# NAPCO Nucleus — Quickstart for Teammates

Five clicks to get running. No Python knowledge required.

## First-time setup (~10 minutes)

1. **Clone the repo** (one-time, anywhere on your machine):

   ```
   git clone https://github.com/napco-labs/napco-nucleus.git
   cd napco-nucleus
   ```

2. **Double-click `scripts\setup.bat`**.

   It will:
   - Install Python 3.12 if missing (UAC prompt — click Yes)
   - Create a virtualenv at `.venv\`
   - Install all Python dependencies
   - Open `.env` in Notepad — fill in your IMAP user + password (your work Gmail, with an app password). Save and close.
   - Optionally pre-download the Whisper models (~3 GB total, one-time). Say Y when asked unless you're on a slow connection.

   You're done when you see "Setup complete."

## Day-to-day

| What you want | What you double-click |
|---|---|
| Start the voice daemon (listens for "Assalamualaikum" → records, "Allah Hafez" → stops) | `scripts\start-daemon.bat` |
| Pull recent activity into a session doc (chat + email + drive + last call) | `scripts\pull-now.bat` |
| Update to the latest code (after a `git pull` notice from Mohammad) | `scripts\update.bat` |

## Voice phrases

The daemon ships with these triggers:

- **Start recording**: "Assalamualaikum" / "Salaam alaikum" / "Nucleus start"
- **Stop recording**: "Allah Hafez" / "Khoda Hafiz" / "Nucleus stop"

Recording only fires if MS Teams has an active call (ringing or in-progress). Saying the start phrase when Teams is just open in the background does nothing — by design.

To add or change phrases, open `data\teams\voice_phrases.json` and edit the JSON. Restart the daemon to pick up changes.

## If something goes wrong

- **"Python not found"** after setup: open a brand-new PowerShell window and re-run `setup.bat`. The PATH change from winget needs a fresh shell.
- **"pip install failed"**: usually a corporate proxy issue. Run `setup.bat` again from inside your VPN.
- **Voice daemon prints "no Teams session in Active state"** when you say a phrase: that's the Teams-only gate working as designed. The daemon will only fire during real Teams calls. Pass `--allow-any-call` to disable: `python -m teams.voice_daemon --allow-any-call`.
- **Recording captured your voice but nothing else**: in MS Teams → Settings → Devices, set Speaker = "Same as system / Default". Teams's separate Communications Device default makes the loopback miss the other party's audio.

For anything else, ping Mohammad.
