# NAPCO Nucleus — short recorder install

The 5-minute version. Installs call recording + mirroring to central only.
Full detail and troubleshooting: [Onsite-Install-Checklist.md](Onsite-Install-Checklist.md).

**Per-dev values:**

| Dev | PC | NUCLEUS_DEV_NAME | Folder |
|---|---|---|---|
| Atik | `172.16.205.108` | `Atik` | `C:\napco-nucleus` |
| Isruk | ? | `Isruk` | `C:\napco-nucleus` |

---

## Prep (at your own desk, before you go)

Copy your `.env`, change one line, carry it on a USB stick:

```
NUCLEUS_DEV_NAME=Atik
```

Do not send `.env` over chat — it holds the Samba password.

---

## At the dev's PC

Open PowerShell **as Administrator** (right-click, *Run as administrator*).
Title bar must say "Administrator" — without admin you get 0-byte recordings
and a second visit. Use the **Teams desktop app**, not Teams in a browser.

### 1. Folder

```powershell
$NN = "C:\napco-nucleus"
New-Item -ItemType Directory -Force -Path $NN | Out-Null
Set-Location $NN
```

### 2. Prerequisites

```powershell
python --version
git --version
```

If either is missing, install it, then **close and reopen PowerShell as admin** and
`Set-Location C:\napco-nucleus` again:

```powershell
winget install --id Python.Python.3.12 -e --source winget
winget install --id Git.Git -e --source winget
```

### 3. Clone

```powershell
git clone https://github.com/napco-labs/napco-nucleus.git .
```

### 4. Drop in the `.env`

Copy the prepared file to `C:\napco-nucleus\.env`, then confirm it is the right dev:

```powershell
Select-String -Path .\.env -Pattern '^NUCLEUS_DEV_NAME='
```

Must print the dev whose PC you are sitting at.

### 5. Install

```powershell
.\scripts\setup-recorder.bat
```

Creates a local `.venv`, installs recording deps, registers the autostart task.
Watch for `[OK]` lines. `[FAIL]` is almost always Python not on PATH — redo step 2.

### 6. Verify with a real call

Have the dev make a Teams call of **at least 20 seconds**, hang up, wait 2 minutes:

```powershell
$u = ((Select-String -Path .\.env -Pattern '^NUCLEUS_SAMBA_USER=').Line -replace '^NUCLEUS_SAMBA_USER=','').Trim()
$p = ((Select-String -Path .\.env -Pattern '^NUCLEUS_SAMBA_PASSWORD=').Line -replace '^NUCLEUS_SAMBA_PASSWORD=','').Trim()
net use \\172.16.205.123\nucleus-central /user:$u $p

$you = ((Select-String -Path .\.env -Pattern '^NUCLEUS_DEV_NAME=').Line -replace 'NUCLEUS_DEV_NAME=','').Trim()
$today = Get-Date -Format 'yyyy-MM-dd'
Get-ChildItem "\\172.16.205.123\nucleus-central\$you\$today\calls\" | Select-Object Name, Length
```

**Pass = three files, and BOTH `_mic.wav` and `_speaker.wav` have Length greater than 0.**

- 0-byte track → PowerShell was not admin. Reopen as admin, re-run step 5, make a fresh call.
- `.json` missing but both WAVs non-zero → wait a minute, re-run. It lands last.
- "Access denied" browsing the share → expected until the `net use` line above. Recording is unaffected.
- Nothing at all → `Get-Content .\logs\voice_daemon.log -Tail 50` and see the full checklist.

Once both WAVs are non-zero the PC is done — every call mirrors, transcribes, and
feeds the pipeline automatically.

---

## Uninstall

```powershell
Set-Location C:\napco-nucleus
.\scripts\register-voice-daemon-task.ps1 -Unregister
```

Then delete the folder. Nothing else was written to the machine.
