# NAPCO Nucleus — Central Capture Setup

How to wire all 5 devs' machines + the MVPACCESS agent host into one
central pipeline so requirements that span multiple developers get
identified together instead of in fragments.

This is the deployment guide for the architecture in
`memory/project_nn_central_architecture.md`. Read that first if you
want the *why*; this doc is the step-by-step *how*.

There are three roles. Follow only the section(s) that apply to you.

---

## A) MVPACCESS (172.16.205.209) — the agent host

Done **once**. This machine:

- Receives every dev's WAV uploads + chat docs into a shared folder.
- Runs `collect_central.py` against the central tree to identify
  requirements per `(client, day)`.
- Holds the only authenticated Claude Max session — so identify runs
  here, not on dev laptops.

### A.1 Create the SMB share

Open **PowerShell as Administrator** on MVPACCESS:

```powershell
$root = "C:\nucleus-central"
New-Item -ItemType Directory -Path $root -Force | Out-Null
New-SmbShare -Name "nucleus-central" -Path $root `
    -FullAccess "AEL\samin" `
    -ChangeAccess "AEL\Domain Users"
icacls $root /grant "AEL\Domain Users:(OI)(CI)M" | Out-Null
```

(Replace `AEL\Domain Users` with whatever AD group covers the 5 devs
if you have a tighter one.)

### A.2 Open the SMB firewall rule

```powershell
Enable-NetFirewallRule -DisplayGroup "File and Printer Sharing"
```

If your domain has a strict outbound profile, add the dev subnet
explicitly:

```powershell
New-NetFirewallRule -DisplayName "Allow SMB from dev subnet" `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort 445 `
    -RemoteAddress 172.16.205.0/24
```

### A.3 Verify from a dev machine

From any of the 5 dev laptops (this guide has been smoke-tested from
the CLAUDE_CODE_HOST at `172.16.205.71`):

```powershell
Test-NetConnection -ComputerName 172.16.205.209 -Port 445
net use \\172.16.205.209\nucleus-central /user:AEL\<dev-username>
```

The first should report `TcpTestSucceeded: True`. The second should
prompt for password and then return `The command completed successfully.`

### A.4 Clone the repo + run setup on MVPACCESS

```powershell
cd C:\
git clone https://github.com/napco-labs/napco-nucleus.git
cd napco-nucleus
.\scripts\setup.bat
```

### A.5 .env on MVPACCESS

Open `.env` in Notepad and set:

```
# Where central captures land — point at LOCAL path on the agent host
NUCLEUS_CENTRAL_PATH=C:\nucleus-central

# Existing settings (already present from .env.example — confirm)
SMTP_USER=khasan@ael-bd.com
SMTP_PASSWORD=...
REQ_IMAP_USER=khasan@ael-bd.com
REQ_IMAP_PASSWORD=...
VERIFICATION_TO=titucse@gmail.com    # default client recipient
```

Note that on the AGENT HOST `NUCLEUS_CENTRAL_PATH` is the local
`C:\nucleus-central` (not a UNC path) — the agent reads files locally
from where the devs' SMB writes land.

### A.6 Verify Claude Max auth

```powershell
claude --version
```

If the CLI prompts for login, follow the OAuth flow. The Agent SDK
re-uses these tokens for all `verify_session` runs.

### A.7 Day-to-day: pulling per-client

```powershell
python collect_central.py --client "Susmoy"               # today
python collect_central.py --client "Acme" --day 2026-05-08
python collect_central.py --client all --no-identify      # inspect
```

Or double-click `scripts\central-pull.bat`.

---

## B) Each dev machine (5 teammates)

Done **once per teammate**.

### B.1 Clone + setup

```powershell
git clone https://github.com/napco-labs/napco-nucleus.git
cd napco-nucleus
.\scripts\setup.bat
```

### B.2 Add the central path to `.env`

Open `.env`, add:

```
NUCLEUS_CENTRAL_PATH=\\172.16.205.209\nucleus-central
# Optional friendly label (defaults to %USERNAME%)
# NUCLEUS_DEV_NAME=salman
```

### B.3 Mount the share once (so Windows caches the credential)

Run **once** in PowerShell as the dev's logged-in user:

```powershell
net use \\172.16.205.209\nucleus-central /user:AEL\<dev-username> /persistent:yes
```

This stores the credential so scheduled tasks running as the same user
can reach the share without prompting.

### B.4 Register the chat-push scheduled task

Run **once**, also in PowerShell:

```powershell
.\scripts\register-chat-push-task.ps1
```

This installs two Windows Task Scheduler entries:

- **"NAPCO Nucleus - Chat Push"** runs `scripts\push-chat.bat` every 15
  minutes, active only during BD 18:00–01:00.
- **"NAPCO Nucleus - Chat Push (Backfill)"** runs
  `scripts\push-chat-backfill.bat` once per day at 18:00 with
  `--last-minutes 1080` (18 hours), so anything that arrived during the
  daytime gap is captured at window open.

Verify with:

```powershell
Get-ScheduledTask -TaskName "NAPCO Nucleus - Chat Push"
Get-ScheduledTask -TaskName "NAPCO Nucleus - Chat Push (Backfill)"
Start-ScheduledTask -TaskName "NAPCO Nucleus - Chat Push"  # run now to test
```

### B.5 Day-to-day

- Double-click `scripts\start-daemon.bat` at the start of each day.
  The voice daemon listens for the call-bookend phrases.
- During calls: say "Assalamualaikum" / "Allah Hafez" naturally.
  Recording starts/stops; WAVs + metadata.json land locally; the
  recorder copies them to `\\172.16.205.209\nucleus-central\<dev>\<date>\calls\`
  on stop.
- Chat is pushed automatically every 15 min by the scheduled task
  during BD 18:00–01:00; an 18:00 backfill catches the daytime gap.
- That's it. No manual upload step.

---

## C) Mohammad (you) — daily verification flow

After the day's calls + chats have flowed in, on MVPACCESS:

```powershell
cd C:\napco-nucleus
.\scripts\central-pull.bat "Susmoy"
```

Or for every client in one pass, run it once per client:

```powershell
python collect_central.py --client "Susmoy"
python collect_central.py --client "Acme"
```

(`--client all` works too but bundles every client's calls into one
verification doc, which usually isn't what you want.)

Each run produces:
- A unified session doc at `data\requirements\sessions\current.docx`
  with all sources for that client + day
- A Requirements Verification .docx
- An .eml draft pushed into Gmail Drafts

You review and send. Done.

---

## Troubleshooting

**"client_name: (unknown)" on every recording.**
The IndexedDB call-event resolver couldn't find a Teams call near the
recording start time. Common causes:

- The dev tested with `--allow-any-call` outside an actual Teams call.
- Recording started *long before* Teams logged the Event/Call (rare;
  the resolver searches ±3 minutes by default).
- Old Teams / Teams Classic running instead of new MS Teams. The
  resolver looks at `MSTeams_8wekyb3d8bbwe`; classic Teams uses a
  different IndexedDB path.

Inspect the resolver state directly:

```powershell
python -c "from teams.calls import resolve_client_for_recording; import time; print(resolve_client_for_recording(int(time.time()*1000), window_seconds=600))"
```

**"central upload FAILED" in the recorder log.**
Either the share isn't mounted, the user's password expired, or the
firewall on MVPACCESS has dropped the dev subnet. The local WAVs are
preserved at `data\teams\calls\` — re-run the recorder upload manually
once the share is reachable again, or copy the files yourself.

**Scheduled chat task shows "0 msg(s) total" forever.**
The dev's Teams desktop probably hasn't synced new chats to IndexedDB
yet. New Teams writes the cache lazily; the desktop client must be
running for fresh messages to show up. If Teams is closed all day, the
chat push has nothing to push.

**Nothing matches when you filter by client.**
Use `--client all` first to confirm there ARE calls in the central
tree for that day. If yes, check the metadata's `client_name` field —
the resolver may have produced a different display name than what you
typed (e.g. "Susmoy Saha" vs just "Susmoy"). Substring match is
case-insensitive, but typos still fail.
