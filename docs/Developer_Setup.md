# NAPCO Nucleus — Developer Setup

Run every command below in **PowerShell** on your Windows dev PC.
Total time: ~25 min, mostly waiting for `pip install`.

## Three things Titu DMs you first

Never share these on group chat — they contain secrets.

1. **`.env`** — save inside your repo folder (`$NN\.env`) after Step 1.
2. **`google-credentials.json`** — save inside your repo folder (`$NN\google-credentials.json`).
3. **This PDF.**

The Samba password is inline in Step 5.

---

## Step 1 — Clone the repo

Pick install location. Set `$NN` to that path — every later step uses it.

```powershell
$NN = "E:\Projects\NAPCO-Nucleus"     # change if you want it elsewhere
mkdir (Split-Path $NN -Parent) -Force | Out-Null
git clone https://github.com/napco-labs/napco-nucleus.git $NN
Set-Location $NN
```

> `$NN` lives only in this PowerShell session. If you open a new shell later, set it again at the top. To persist across sessions: `[Environment]::SetEnvironmentVariable("NN", $NN, "User")` — then use `$env:NN` from any future shell.

---

## Step 2 — Install Python packages

```powershell
Set-Location $NN
python -m pip install -r requirements.txt
```

---

## Step 3 — Install Tesseract OCR

```powershell
winget install UB-Mannheim.TesseractOCR
```

Close and reopen PowerShell (re-set `$NN` after reopen).

---

## Step 4 — Place files + set your dev name

Save the two files Titu sent you into your repo folder:
- `$NN\.env`
- `$NN\google-credentials.json`

Open `.env` in Notepad. Find this line:
```
NUCLEUS_DEV_NAME=Titu
```
Replace `Titu` with **your** name. Use one exactly:
```
Assad   Rocky   Ferdows   Titu   Atik   Isruk   Amin
```
Save. Close.

---

## Step 5 — Cache Samba password (**critical**)

**Use REGULAR PowerShell, NOT admin.** The credential is stored per-user and must be in your normal session.

```powershell
cmdkey /add:172.16.205.123 /user:nucleus /pass:E7CqJOd1oHox7HTjxNp_osD_fSyUe59I
Test-Path \\172.16.205.123\nucleus-central
```

`Test-Path` **must print `True`**. If it prints `False`, your calls won't upload to central — stop and ping Titu.

---

## Step 6 — Install voice daemon

```powershell
Set-Location $NN
.\scripts\register-voice-daemon-task.ps1
Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
```

---

## Step 7 — Install chat-push tasks

```powershell
Set-Location $NN
.\scripts\register-chat-push-task.ps1
```

---

## Step 8 — Enable remote ops (admin one-time)

So Titu can manage your PC from his desk without you needing to be at the keyboard. Open **admin PowerShell** (right-click PowerShell → Run as administrator):

```powershell
Enable-PSRemoting -Force
Add-LocalGroupMember -Group "Remote Management Users" -Member "AEL\khasan"
```

If `Enable-PSRemoting` errors about network profile being "Public", use this instead:
```powershell
Enable-PSRemoting -Force -SkipNetworkProfileCheck
Add-LocalGroupMember -Group "Remote Management Users" -Member "AEL\khasan"
```

If `Add-LocalGroupMember` says "User already member", that's fine — already granted.

---

## Step 9 — Test

Make any Teams call (at least 20 seconds). Wait 2 minutes. Then:

```powershell
$you   = ((Select-String -Path "$NN\.env" -Pattern '^NUCLEUS_DEV_NAME=').Line -replace 'NUCLEUS_DEV_NAME=','').Trim()
$today = Get-Date -Format "yyyy-MM-dd"
Get-ChildItem "\\172.16.205.123\nucleus-central\$you\$today\calls\"
```

You should see `*_mic.wav`, `*_speaker.wav`, `*.json`, `*_transcript.md`.

**Setup complete.** Tell Titu you're done.

---

## If something fails

**Daemon log:**
```powershell
Get-Content "$NN\logs\voice_daemon.log" -Tail 50
```

**`scripts disabled on this system` in Step 6 or 7:**
```powershell
powershell.exe -ExecutionPolicy Bypass -File "$NN\scripts\register-voice-daemon-task.ps1"
```

**`Test-Path` returned `False` in Step 5:**
```powershell
ping 172.16.205.123
cmdkey /list:172.16.205.123
```
If cmdkey doesn't show a `nucleus` user, re-run Step 5 in a **non-admin** PowerShell.

**Mic missing from recordings:**
Teams → Settings → Devices → set Microphone to your Windows default input.

---

## Update later

```powershell
Set-Location $NN
git pull
python -m pip install -r requirements.txt
Stop-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
```

(Or just ask Titu to push the update remotely.)

---

## Uninstall

```powershell
Set-Location $NN
.\scripts\register-voice-daemon-task.ps1 -Unregister
.\scripts\register-chat-push-task.ps1 -Unregister
cmdkey /delete:172.16.205.123
```

---

## Contact

Titu — `khasan@ael-bd.com`

---
---

# APPENDIX — Titu's remote-ops cheat sheet

> _**Not for the dev to run.** This is Titu's reference for managing dev PCs remotely once they've completed Step 8._

## One-time setup on Titu's PC

Already done on `.71`. For reference if Titu ever reinstalls: **admin PowerShell**:
```powershell
Start-Service WinRM
Set-Service WinRM -StartupType Automatic
Set-Item WSMan:\localhost\Client\TrustedHosts -Value '172.16.205.*' -Force
```

## Credential header

Paste at the top of any new PowerShell session before running the commands below:
```powershell
$pwd_at = ConvertTo-SecureString '606549' -AsPlainText -Force
$cred_at = New-Object PSCredential('AEL\khasan', $pwd_at)
```

## Dev PC IP registry (fill in as you onboard)

| Dev | IP | NUCLEUS_DEV_NAME | Repo path |
|---|---|---|---|
| Titu (yours) | `172.16.205.71` | `Titu` | `E:\Projects\NAPCO-Nucleus` |
| Atik | `172.16.205.108` | `Atik` | `F:\Titu vai\napco-nucleus` |
| Rocky | ? | `Rocky` | ? |
| Ferdows | ? | `Ferdows` | ? |
| Amin | ? | `Amin` | ? |
| Isruk | ? | `Isruk` | ? |
| Assad | ? | `Assad` | ? |

## Remote operations

Replace `<IP>` with the target PC's IP from the table above. Replace `<repo>` with the dev's repo path.

**Probe a dev PC (sanity check):**
```powershell
Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {
    hostname; whoami; "OS: $((Get-CimInstance Win32_OperatingSystem).Caption)"
}
```

**Tail their voice daemon log:**
```powershell
Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {
    Get-Content "<repo>\logs\voice_daemon.log" -Tail 30
}
```

**Check Scheduled Task state (`schtasks` — `Get-ScheduledTask` needs admin remotely):**
```powershell
Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {
    schtasks /query /tn "NAPCO Nucleus - Voice Daemon" /fo LIST
    schtasks /query /tn "NAPCO Nucleus - Chat Push (Day)" /fo LIST
}
```

**Apply `git pull` + restart their daemon:**
```powershell
Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {
    Set-Location "<repo>"
    git pull
    Stop-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
    Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
}
```

**Recover stuck WAVs to central** (when the dev's `cmdkey` wasn't set up correctly — `cmdkey` can't be done via WinRM, but `New-PSDrive` with explicit cred works):
```powershell
Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {
    $smb_pwd = ConvertTo-SecureString 'E7CqJOd1oHox7HTjxNp_osD_fSyUe59I' -AsPlainText -Force
    $smb_cred = New-Object PSCredential('nucleus', $smb_pwd)
    New-PSDrive -Name NN -PSProvider FileSystem -Root '\\172.16.205.123\nucleus-central' -Credential $smb_cred | Out-Null
    $today = Get-Date -Format "yyyy-MM-dd"
    $dest = "NN:\<DEV_NAME>\$today\calls"     # replace <DEV_NAME>
    New-Item -ItemType Directory -Force -Path $dest -ErrorAction SilentlyContinue | Out-Null
    Get-ChildItem '<repo>\data\teams\calls\*' -ErrorAction SilentlyContinue | Copy-Item -Destination $dest -Force
    Get-ChildItem $dest | Select-Object Name, Length
    Remove-PSDrive NN
}
```

**Open an interactive remote shell** (good for debugging):
```powershell
Enter-PSSession -ComputerName <IP> -Credential $cred_at
# prompt becomes [<IP>]: PS> — type commands; runs on their PC
# 'exit' when done
```

## Central host (.123) operations

```bash
ssh ubuntu@172.16.205.123                    # password: ayusuf

# Stack health
cd /home/ubuntu/napco-nucleus/deploy/linux-central
./status.sh

# Trigger daily-draft on demand (instead of waiting for BD 23:45)
docker compose exec daily-draft python collect_central.py --client all --last-minutes 1440

# Safe redeploy (after pushing a fix to main)
./deploy.sh           # core stack only
./deploy.sh --runner  # also recreates the GHA runner container

# Tail one worker
docker compose logs -f --tail 100 transcribe
```

## Daily-draft email destination

Drafts land in **`khasan@ael-bd.com`** Gmail Drafts folder (configured via `VERIFICATION_TO` in `.env` on `.123`). Subject pattern: `Requirements Verification - YYYY-MM-DD`.
