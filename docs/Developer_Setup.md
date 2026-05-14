# NAPCO Nucleus — Developer Setup

Run every command below in **PowerShell** on your Windows dev PC.

## What Titu sends you first

Titu will DM you these two files privately (they contain secrets — never share them publicly):

1. **`.env`** — save at `E:\Projects\NAPCO-Nucleus\.env` (after Step 1 clones the repo)
2. **`google-credentials.json`** — save at `E:\Projects\NAPCO-Nucleus\google-credentials.json`

The Samba password is provided inline in Step 5 below.

---

## Step 1 — Clone the repo

Run in **PowerShell**:

```powershell
cd E:\
mkdir Projects -Force
cd E:\Projects
git clone https://github.com/napco-labs/napco-nucleus.git NAPCO-Nucleus
```

---

## Step 2 — Install Python packages

Run in **`E:\Projects\NAPCO-Nucleus`**:

```powershell
cd E:\Projects\NAPCO-Nucleus
python -m pip install -r requirements.txt
```

---

## Step 3 — Install Tesseract OCR

Run anywhere in **PowerShell**:

```powershell
winget install UB-Mannheim.TesseractOCR
```

Then close and reopen PowerShell.

---

## Step 4 — Place the files Titu sent you + set your dev name

Save the two files from the "What Titu sends you first" section above:

```
E:\Projects\NAPCO-Nucleus\.env
E:\Projects\NAPCO-Nucleus\google-credentials.json
```

Open the `.env` file in Notepad. Find this line:

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

Run in **`E:\Projects\NAPCO-Nucleus`**:

```powershell
cd E:\Projects\NAPCO-Nucleus
.\scripts\register-voice-daemon-task.ps1
Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
```

---

## Step 7 — Install chat-push tasks

Run in **`E:\Projects\NAPCO-Nucleus`**:

```powershell
cd E:\Projects\NAPCO-Nucleus
.\scripts\register-chat-push-task.ps1
```

---

## Step 8 — Test

Make a Teams call (any short call). Wait 2 minutes. Then run in **PowerShell**:

```powershell
$you  = (Select-String -Path E:\Projects\NAPCO-Nucleus\.env -Pattern '^NUCLEUS_DEV_NAME=').Line -replace 'NUCLEUS_DEV_NAME=',''
$today = Get-Date -Format "yyyy-MM-dd"
Get-ChildItem "\\172.16.205.123\nucleus-central\$you\$today\calls\"
```

Expected: your call files (`*_mic.wav`, `*_speaker.wav`, `*.json`, `*_transcript.md`).

Setup is complete.

---

## If a step fails

**Tail the voice daemon log:**
```powershell
Get-Content E:\Projects\NAPCO-Nucleus\logs\voice_daemon.log -Tail 50
```

**`scripts disabled on this system` error in Step 6 or 7:**
```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\register-voice-daemon-task.ps1
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

Run in **`E:\Projects\NAPCO-Nucleus`**:

```powershell
cd E:\Projects\NAPCO-Nucleus
git pull
python -m pip install -r requirements.txt
Stop-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'
```

---

## Uninstall

Run in **`E:\Projects\NAPCO-Nucleus`**:

```powershell
cd E:\Projects\NAPCO-Nucleus
.\scripts\register-voice-daemon-task.ps1 -Unregister
.\scripts\register-chat-push-task.ps1 -Unregister
cmdkey /delete:172.16.205.123
```

---

## Contact

Titu — `khasan@ael-bd.com`
