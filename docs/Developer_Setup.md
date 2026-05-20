# NAPCO Nucleus — Developer Setup

Total time: ~15 min. Titu will DM you `.env` and `google-credentials.json` — never share these on group chat.

---

## Step 1 — Install Git

```powershell
winget install --id Git.Git -e --source winget
```

---

## Step 2 — Install Python 3.12

```powershell
winget install --id Python.Python.3.12 -e --source winget
```

---

## Step 3 — Clone the repo

```powershell
$NN = "E:\Projects\NAPCO-Nucleus"
[Environment]::SetEnvironmentVariable("NN", $NN, "User")
mkdir (Split-Path $NN -Parent) -Force | Out-Null
git clone https://github.com/napco-labs/napco-nucleus.git $NN
Set-Location $NN
```

---

## Step 4 — Place files + set your dev name

Copy `.env` and `google-credentials.json` (from Titu) into `$NN`.

Open `$NN\.env` in Notepad. Change this line to your name:
```
NUCLEUS_DEV_NAME=Titu
```
Valid names: `Assad   Rocky   Ferdows   Titu   Atik   Isruk   Amin`

---

## Step 5 — Install Python packages

```powershell
Set-Location $env:NN
python -m pip install -r requirements.txt
```

---

## Step 6 — Install voice daemon

```powershell
Set-Location $env:NN
.\scripts\install-voice-daemon.bat
```

---

## Step 7 — Install chat-push tasks

```powershell
Set-Location $env:NN
.\scripts\register-chat-push-task.ps1
```

---

## Step 8 — Test

Make any Teams call (at least 20 seconds). Wait 2 minutes. Then:

```powershell
$you   = ((Select-String -Path "$NN\.env" -Pattern '^NUCLEUS_DEV_NAME=').Line -replace 'NUCLEUS_DEV_NAME=','').Trim()
$today = Get-Date -Format "yyyy-MM-dd"
Get-ChildItem "\\172.16.205.123\nucleus-central\$you\$today\calls\"
```

You should see `*_mic.wav`, `*_speaker.wav`, `*.json`.

**Setup complete.** Tell Titu you're done.

---

## If something fails

**Daemon log:**
```powershell
Get-Content "$NN\logs\voice_daemon.log" -Tail 50
```

**`scripts disabled on this system` error:**
```powershell
powershell.exe -ExecutionPolicy Bypass -File "$NN\scripts\install-voice-daemon.bat"
```

**Calls not appearing on central:**
```powershell
ping 172.16.205.123
```
If the ping fails, you're not on the office network. Connect to VPN or come to the office.

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

---

## Uninstall

```powershell
Set-Location $NN
.\scripts\register-voice-daemon-task.ps1 -Unregister
.\scripts\register-chat-push-task.ps1 -Unregister
```

---

## Contact

Titu — `khasan@ael-bd.com`

---
---

# APPENDIX — Titu's remote-ops cheat sheet

> _**Not for the dev to run.** This is Titu's reference for managing dev PCs remotely once Step 8 (WinRM) is done._

## One-time WinRM setup on each dev PC (admin, done by Titu)

Open **admin PowerShell** on the dev's PC (right-click → Run as administrator):

```powershell
Enable-PSRemoting -Force
Add-LocalGroupMember -Group "Remote Management Users" -Member "AEL\khasan"
```

If `Enable-PSRemoting` errors about "Public" network:
```powershell
Enable-PSRemoting -Force -SkipNetworkProfileCheck
Add-LocalGroupMember -Group "Remote Management Users" -Member "AEL\khasan"
```

## One-time setup on Titu's PC

Already done on `.71`. For reference if ever reinstalled — **admin PowerShell**:
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

## Dev PC IP registry

| Dev | IP | NUCLEUS_DEV_NAME | Repo path |
|---|---|---|---|
| Titu (yours) | `172.16.205.71` | `Titu` | `E:\Projects\NAPCO-Nucleus` |
| Atik | `172.16.205.108` | `Atik` | `F:\Titu vai\napco-nucleus` |
| Rocky | `172.16.205.195` | `Rocky` | `D:\POC Projects\napco-nucleus` |
| Ferdows | ? | `Ferdows` | ? |
| Amin | ? | `Amin` | ? |
| Isruk | ? | `Isruk` | ? |
| Assad | ? | `Assad` | ? |

## Remote operations

Replace `<IP>` with the target PC's IP. Replace `<repo>` with the dev's repo path.

**Probe a dev PC:**
```powershell
Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {
    hostname; whoami
}
```

**Tail their voice daemon log:**
```powershell
Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {
    Get-Content "<repo>\logs\voice_daemon.log" -Tail 30
}
```

**Check Scheduled Task state:**
```powershell
Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {
    schtasks /query /tn "NAPCO Nucleus - Voice Daemon" /fo LIST
    schtasks /query /tn "NAPCO Nucleus - Chat Push (Day)" /fo LIST
}
```

**Apply `git pull` + restart daemon:**
```powershell
Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {
    Set-Location "<repo>"
    git pull
    Stop-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
    Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
}
```

**Recover stuck WAVs to central:**
```powershell
Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {
    $smb_pwd = ConvertTo-SecureString 'E7CqJOd1oHox7HTjxNp_osD_fSyUe59I' -AsPlainText -Force
    $smb_cred = New-Object PSCredential('nucleus', $smb_pwd)
    New-PSDrive -Name NN -PSProvider FileSystem -Root '\\172.16.205.123\nucleus-central' -Credential $smb_cred | Out-Null
    $today = Get-Date -Format "yyyy-MM-dd"
    $dest = "NN:\<DEV_NAME>\$today\calls"
    New-Item -ItemType Directory -Force -Path $dest -ErrorAction SilentlyContinue | Out-Null
    Get-ChildItem '<repo>\data\teams\calls\*' -ErrorAction SilentlyContinue | Copy-Item -Destination $dest -Force
    Get-ChildItem $dest | Select-Object Name, Length
    Remove-PSDrive NN
}
```

**Open an interactive remote shell:**
```powershell
Enter-PSSession -ComputerName <IP> -Credential $cred_at
# prompt becomes [<IP>]: PS> — type 'exit' when done
```

## Central host (.123) operations

```bash
ssh ubuntu@172.16.205.123                    # password: ayusuf

# Stack health
cd /home/ubuntu/napco-nucleus/deploy/linux-central
./status.sh

# Trigger daily-draft on demand
docker compose exec daily-draft python collect_central.py --client all --last-minutes 1440

# Safe redeploy after pushing a fix to main
./deploy.sh
./deploy.sh --runner   # also recreates the GHA runner container

# Tail a worker
docker compose logs -f --tail 100 transcribe
```

## Daily-draft email destination

Drafts land in **`khasan@ael-bd.com`** Gmail Drafts folder. Subject pattern: `Requirements Verification - YYYY-MM-DD`.
