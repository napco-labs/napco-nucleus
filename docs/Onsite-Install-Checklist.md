# Onsite install checklist — Atik & Isruk (recording-only, local folder)

For Titu, to run in person at each dev's PC. **One shot — no second visit.** Read this
whole page once before you sit down. Everything below is copy-paste; nothing needs
judgment calls on-site except picking a drive letter in Step 1.

Total time per PC: ~10 minutes.

---

## What this installs

Just call recording + mirroring to central (the "recording-only" flow already built
into the repo, `scripts/setup-recorder.bat`). NOT the full dev environment — no
global Python packages, no chat-push, no local pipeline. Everything lives inside one
folder you create; nothing is written outside it *except one system-wide audio
registry setting* (see next box). Uninstalling later = delete the folder + remove one
scheduled task (see bottom).

> ### ⚠️ Run everything as Administrator — this is the #1 thing that breaks the visit
>
> The recorder disables **exclusive mode** on the PC's audio devices (a write to
> `HKEY_LOCAL_MACHINE`). Without it, Teams can grab the speaker/mic in exclusive
> mode and you get **0-byte recordings** — the exact bug we're fixing. That registry
> write, and registering the autostart task at highest privilege, **both need admin.**
>
> - **Open PowerShell with "Run as administrator"** for every step below.
> - The dev should ideally be a **local admin** on their PC. If they are NOT, recording
>   still works after this admin setup (the setting persists), **but** if they later
>   plug in a *different* headset, exclusive mode won't auto-disable on it until an
>   admin re-runs setup. Note the headset they use today.
> - Use the **Teams desktop app**, not Teams-in-a-browser — the recorder detects the
>   `ms-teams.exe` audio session; the web client isn't detected.

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

4. **Confirm you can get admin on each PC** (see the ⚠️ box above). Either the dev is
   a local admin, or bring/arrange the admin credential. Without admin the recordings
   can come out 0-byte and you'd have to come back — the whole point of one-shot.

---

## AT EACH PC — Step 1: pick a drive and create the folder

Open PowerShell **as Administrator** (Start → type "PowerShell" → right-click → *Run
as administrator*; accept the UAC prompt). Confirm the title bar says
"Administrator". Then check which local drive has space (D:, E:, or F: — whichever
exists and isn't the system drive):

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
# The share only accepts the 'nucleus' Samba user, and Windows blocks
# anonymous/guest browse — so authenticate the session FIRST, or the listing
# below (and File Explorer) will say "access denied" even though recording works.
$u   = ((Select-String -Path .\.env -Pattern '^NUCLEUS_SAMBA_USER=').Line     -replace '^NUCLEUS_SAMBA_USER=','').Trim()
$p   = ((Select-String -Path .\.env -Pattern '^NUCLEUS_SAMBA_PASSWORD=').Line -replace '^NUCLEUS_SAMBA_PASSWORD=','').Trim()
net use \\172.16.205.123\nucleus-central /user:$u $p

$you = ((Select-String -Path .\.env -Pattern '^NUCLEUS_DEV_NAME=').Line -replace 'NUCLEUS_DEV_NAME=','').Trim()
Get-ChildItem "\\172.16.205.123\nucleus-central\$you\$(Get-Date -Format 'yyyy-MM-dd')\calls\" | Select-Object Name, Length
```

You should see three files per call: `*_mic.wav`, `*_speaker.wav`, `*.json`.

> **"Access denied" / can't open the share in File Explorer?** That's expected until
> you run the `net use ... /user:nucleus` line above — the share refuses guest access.
> It does **not** mean recording is broken; the recorder authenticates itself on every
> upload. Once you've run `net use`, both File Explorer and the listing work.

**The real success test is the `Length` column — BOTH `_mic.wav` AND `_speaker.wav`
must be greater than 0.** A 0-byte track = the exclusive-mode fix didn't apply
(almost always: PowerShell wasn't run as admin, or the dev isn't a local admin). If
either track is 0 bytes:
1. Confirm the PowerShell title bar says "Administrator". If not, close it, reopen as
   admin, re-run `.\scripts\setup-recorder.bat`, and make a fresh test call.
2. If it's still 0 bytes and the dev is a standard (non-admin) user, have their admin
   run the setup once, or temporarily grant admin — the audio-registry fix needs it.

If the `.json` is missing but both WAVs are non-zero, wait another minute and re-run —
`.json` lands last, after both WAVs finish uploading.

**If nothing shows up at all:**

```powershell
Get-Content .\logs\voice_daemon.log -Tail 50
```

- Look for `[voice] Teams gate OK (connected call, Active audio)` — if missing, the
  daemon never saw an active call. Check it's the **Teams desktop app** (not browser),
  and Teams → Settings → Devices → Microphone is a real device (the Windows default
  input), not a virtual/"Default Communications" device.
- Look for `[audio] exclusive mode disabled for ...` — if instead you see
  `exclusive mode fix skipped ... Access is denied`, that confirms the admin problem
  above.
- Tell network vs. auth problems apart:
  - `ping 172.16.205.123` **times out** → network/VPN issue, the PC can't reach central.
  - `ping` works but the share says **"access denied" / "not accessible"** → auth, not
    network. Run the `net use \\172.16.205.123\nucleus-central /user:nucleus ...` line
    from Step 7. The recorder is unaffected (it authenticates itself); this only blocks
    your manual browse.

---

## Done — tell Titu (yourself) it's confirmed

Once Step 7 shows all three files **with both WAVs non-zero**, this PC is fully wired:
every Teams call from now on mirrors to central automatically, gets transcribed
(Google STT Chirp v2), and feeds the requirement pipeline — no further action needed
on this machine.

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
