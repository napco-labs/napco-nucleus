# Onsite install checklist — Atik & Isruk (recording-only, local folder)

For Titu, to run in person at each dev's PC. **One shot — no second visit.** Read this
whole page once before you sit down. Everything below is copy-paste; nothing needs
judgment calls on-site except picking a drive letter in Step 1.

Total time per PC: ~10 minutes.

---

## What this installs

Just call recording + mirroring to central (the "recording-only" flow already built
into the repo, `scripts/setup-recorder.bat`). NOT the full dev environment — no
global installs, no chat-push, no local pipeline. Everything lives inside one folder
you create; nothing touches the system outside it. Uninstalling later = delete the
folder + remove one scheduled task (see bottom).

---

## BEFORE you leave your desk (prep — do this first, at your own PC)

1. **Pick each dev's `NUCLEUS_DEV_NAME`** — must be exactly `Atik` or `Isruk` (matches
   the names the pipeline already expects; check `E:\Projects\NAPCO-Nucleus\.env` line
   `NUCLEUS_EXCLUDE_CHATS` area for the full valid list if unsure).

2. **Prepare two `.env` files**, one per dev — copy your own `.env` and change ONLY
   this line in each copy:
   ```
   NUCLEUS_DEV_NAME=Atik
   ```
   (and a second copy with `NUCLEUS_DEV_NAME=Isruk`). Save them somewhere you can
   carry — a USB stick, or OneDrive if both PCs are on the office network already.
   **Do not share `.env` over group chat** (it has the Samba password).

3. Confirm both PCs are on the **office network** (172.16.205.x) or can reach it —
   the recorder needs `\\172.16.205.123\nucleus-central` reachable. If a PC is
   sometimes off-net, that's fine (retry logic exists) but the first verify step
   below needs it reachable at least once.

---

## AT EACH PC — Step 1: pick a drive and create the folder

Open a **normal PowerShell window** (no admin needed). Check which local drive has
space (D:, E:, or F: — whichever exists and isn't the system drive):

```powershell
Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}
```

Pick the first one with room (a few hundred MB is enough). Say it's `D:` — then:

```powershell
$NN = "D:\napco-nucleus"
New-Item -ItemType Directory -Force -Path $NN | Out-Null
Set-Location $NN
```

(Swap `D:` for `E:` or `F:` if that's the drive you picked — keep the folder name
`napco-nucleus` exactly, directly on the drive root, not nested in another folder.)

---

## Step 2: confirm Python is installed

```powershell
python --version
```

If that fails (`not recognized`):

```powershell
winget install --id Python.Python.3.12 -e --source winget
```

Then **close and reopen PowerShell** (PATH only updates in new windows), `cd` back
into the folder from Step 1, and re-run `python --version` to confirm.

---

## Step 3: install Git (if not already there)

```powershell
git --version
```

If that fails:

```powershell
winget install --id Git.Git -e --source winget
```

Close/reopen PowerShell again if it was just installed, `cd` back into `D:\napco-nucleus`.

---

## Step 4: clone the repo into this folder

```powershell
git clone https://github.com/napco-labs/napco-nucleus.git .
```

(The trailing `.` clones straight into the current folder instead of making a
nested subfolder — important, since we already created `napco-nucleus` in Step 1.)

---

## Step 5: drop in this dev's `.env`

Copy the correct prepared `.env` (from the prep step — `Atik`'s or `Isruk`'s) into
this folder so the path is:

```
D:\napco-nucleus\.env
```

Quick check it landed and has the right name:

```powershell
Select-String -Path .\.env -Pattern '^NUCLEUS_DEV_NAME='
```

Should print `NUCLEUS_DEV_NAME=Atik` (or `Isruk`) — confirm it matches the PC you're
actually sitting at before continuing.

---

## Step 6: run the one-click installer

```powershell
.\scripts\setup-recorder.bat
```

This creates a **local-only** `.venv` inside the folder, installs just the recording
dependencies into it (nothing global), and registers the voice daemon to autostart
at login. Takes ~2 minutes. Watch for `[OK]` lines; if you see `[FAIL]`, stop and
read the message — most likely Python isn't on PATH yet (redo Step 2).

---

## Step 7: verify — make a real test call

Have the dev make (or join) any Teams call, **at least 20 seconds**, then hang up.
Wait 2 minutes, then:

```powershell
$you = ((Select-String -Path .\.env -Pattern '^NUCLEUS_DEV_NAME=').Line -replace 'NUCLEUS_DEV_NAME=','').Trim()
Get-ChildItem "\\172.16.205.123\nucleus-central\$you\$(Get-Date -Format 'yyyy-MM-dd')\calls\"
```

You should see three files per call: `*_mic.wav`, `*_speaker.wav`, `*.json`. If the
`.json` is missing, wait another minute and re-run the check — it lands last, after
both WAVs finish uploading.

**If nothing shows up at all:**

```powershell
Get-Content .\logs\voice_daemon.log -Tail 50
```

Look for `[voice] Teams gate OK (connected call, Active audio)` — if that line is
missing, the daemon never saw an active call (check Teams audio device settings:
Settings → Devices → Microphone must be the Windows default input, not a virtual
device). If you see `ping 172.16.205.123` timing out, the PC isn't on the office
network/VPN.

---

## Done — tell Titu (yourself) it's confirmed

Once Step 7 shows all three files, this PC is fully wired: every Teams call from now
on mirrors to central automatically, gets transcribed (Google STT Chirp v2), and
feeds the requirement pipeline — no further action needed on this machine.

---

## If you ever need to remove it later

```powershell
Set-Location D:\napco-nucleus
.\scripts\register-voice-daemon-task.ps1 -Unregister
```

Then delete the whole `D:\napco-nucleus` folder — nothing was written anywhere else
on the machine (only the one scheduled task + this one folder).

---

## Reference — full path registry (fill in after each visit)

| Dev | PC / IP | NUCLEUS_DEV_NAME | Local repo path |
|---|---|---|---|
| Atik | ? | `Atik` | `D:\napco-nucleus` *(confirm actual drive used)* |
| Isruk | ? | `Isruk` | `D:\napco-nucleus` *(confirm actual drive used)* |

Update `docs/Developer_Setup.md`'s "Dev PC IP registry" table with the final IP and
path once you're back at your desk, so future remote troubleshooting has it.
