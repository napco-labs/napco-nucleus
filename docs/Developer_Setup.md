# NAPCO Nucleus — Developer Setup

Run every command below in **PowerShell** on your Windows dev PC.

## What Titu sends you first

Titu will DM you these two files privately (they contain secrets — never share them publicly):

1. **`.env`** — save inside your repo folder after Step 1 (`$NN\.env`)
2. **`google-credentials.json`** — save inside your repo folder (`$NN\google-credentials.json`)

The Samba password is provided inline in Step 5 below.

---

## Step 1 — Clone the repo

Pick where you want the repo installed. Set `$NN` to that path — every later step references `$NN`, so the install location is yours to decide.

Run in **PowerShell**:

```powershell
$NN = "E:\Projects\NAPCO-Nucleus"   # change this if you want it elsewhere (e.g. "F:\dev\napco-nucleus")
mkdir (Split-Path $NN -Parent) -Force | Out-Null
git clone https://github.com/napco-labs/napco-nucleus.git $NN
Set-Location $NN
```

> `$NN` only lives in the **current PowerShell session**. If you close PowerShell, set it again at the top of any new session before running the rest of the commands. Or stash it permanently with:
> ```powershell
> [Environment]::SetEnvironmentVariable("NN", $NN, "User")
> ```
> after which you can use `$env:NN` from any future shell.

---

## Step 2 — Install Python packages

Run in **PowerShell**:

```powershell
Set-Location $NN
python -m pip install -r requirements.txt
```

---

## Step 3 — Install Tesseract OCR

Run anywhere in **PowerShell**:

```powershell
winget install UB-Mannheim.TesseractOCR
```

Then close and reopen PowerShell (re-set `$NN` after reopen).

---

## Step 4 — Place the files Titu sent you + set your dev name

Save the two files from the "What Titu sends you first" section above into your repo folder:

```
$NN\.env
$NN\google-credentials.json
```

(Replace `$NN` with the actual path in your file manager — e.g. `E:\Projects\NAPCO-Nucleus\.env`.)

Open `.env` in Notepad. Find this line:

```
NUCLEUS_DEV_NAME=Titu
```

Replace `Titu` with **your** name. Use one of these exactly:

```
Assad   Rocky   Ferdows   Titu   Atik   Isruk   Amin
```

Save. Close.

---

## Step 5 — Cache the Samba password

Run in **PowerShell**:

```powershell
cmdkey /add:172.16.205.123 /user:nucleus /pass:E7CqJOd1oHox7HTjxNp_osD_fSyUe59I
```

Verify:

```powershell
Test-Path \\172.16.205.123\nucleus-central
```

Expected output: `True`

---

## Step 6 — Install the voice daemon

Run in **PowerShell**:

```powershell
Set-Location $NN
.\scripts\register-voice-daemon-task.ps1
Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
```

---

## Step 7 — Install chat-push tasks

Run in **PowerShell**:

```powershell
Set-Location $NN
.\scripts\register-chat-push-task.ps1
```

---

## Step 8 — Test

Make a Teams call (any short call, at least 20 seconds). Wait 2 minutes. Then run in **PowerShell**:

```powershell
$you   = ((Select-String -Path "$NN\.env" -Pattern '^NUCLEUS_DEV_NAME=').Line -replace 'NUCLEUS_DEV_NAME=','').Trim()
$today = Get-Date -Format "yyyy-MM-dd"
Get-ChildItem "\\172.16.205.123\nucleus-central\$you\$today\calls\"
```

Expected: your call files (`*_mic.wav`, `*_speaker.wav`, `*.json`, `*_transcript.md`).

---

## Step 9 — Enable remote operations (admin one-time)

So Titu can troubleshoot and update your PC remotely without bothering you again, run this **once in admin PowerShell** (right-click PowerShell → Run as administrator):

```powershell
Enable-PSRemoting -Force
```

That's it. Opens the WinRM listener + firewall rule. After this, Titu can run diagnostics + apply fixes on your PC from his without you needing to be at the keyboard.

Setup is complete.

---

## If a step fails

**Tail the voice daemon log:**
```powershell
Get-Content "$NN\logs\voice_daemon.log" -Tail 50
```

**`scripts disabled on this system` error in Step 6 or 7:**
```powershell
powershell.exe -ExecutionPolicy Bypass -File "$NN\scripts\register-voice-daemon-task.ps1"
```
(Use the same form for `register-chat-push-task.ps1`.)

**`Test-Path` in Step 5 returned `False`:**
```powershell
ping 172.16.205.123
cmdkey /list:172.16.205.123
```

**Mic missing from recordings:**
Teams → Settings → Devices → set Microphone to your Windows default input.

---

## Update the system later

Run in **PowerShell** (re-set `$NN` first if it's a fresh session):

```powershell
Set-Location $NN
git pull
python -m pip install -r requirements.txt
Stop-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
```

---

## Uninstall

Run in **PowerShell** (re-set `$NN` first if it's a fresh session):

```powershell
Set-Location $NN
.\scripts\register-voice-daemon-task.ps1 -Unregister
.\scripts\register-chat-push-task.ps1 -Unregister
cmdkey /delete:172.16.205.123
```

---

## Contact

Titu — `khasan@ael-bd.com`
