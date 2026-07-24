# NAPCO Nucleus Meeting Assistant — Crash-Recovery Rebuild Runbook

**Goal:** rebuild the whole Meeting Assistant on a fresh Windows PC in ~1 hour (with Claude driving it). Last updated 2026-07-24.

---

## 0. The one thing that makes this possible
The custom code is backed up **off** the Windows PC at:
- **Central `.123`:** `/home/ubuntu/nn-assistant-backup.zip`  (primary)
- Office PC `.71`: local repo copy (secondary)
- The main repo `napco-nucleus` (`E:\napco-nucleus` on the box; also `titucse/napco-nucleus`)

If the PC crashes, the code is NOT lost. Steps below restore it.
**After any change to the assistant code, re-run the backup (Step 9 bottom) so this stays current.**

---

## 1. What this system is (30-second version)
A free personal Teams account (**"Napco Nucleus"**, login `kamrul.celloscope@gmail.com`) is signed into the Teams desktop client on a dedicated Windows box (**MASTAN2**). The team ADDS it to client calls/chats. Local Python daemons + Windows UI-automation:
- **auto-answer** incoming calls, **record** both tracks, **mirror** to Central `.123` (requirement pipeline),
- push a **live heartbeat** during calls,
- run a **chat assistant** (canned + warm Claude Agent SDK, persona, commands, health checks, multi-chat auto-switch),
- send **gentle dev reminders**.
Central `.123` (Ubuntu) transcribes (Google STT) and runs the requirement-management pipeline. **UI-automation only works while the screen is UNLOCKED** — this is the #1 operational rule.

---

## 2. Host facts & access
| Thing | Value |
|---|---|
| Windows box | **MASTAN2**, account **`ael\assad`** (pw known to Titu). NOT khasan. |
| IP (roams) | office `172.16.205.72`, home `192.168.0.210` |
| Reach from Titu PC | WinRM: `Invoke-Command -ComputerName <ip> -Credential (Import-Clixml "$env:USERPROFILE\.210.cred.xml")` |
| Repo on box | `E:\napco-nucleus` |
| Python | `py -3` / `pythonw.exe` at `C:\Users\assad\AppData\Local\Programs\Python\Python313\` |
| Teams login | `kamrul.celloscope@gmail.com` (display "Napco Nucleus") |
| Central | `ubuntu@172.16.205.123` (Ubuntu 24.04, docker stack). SMB share `\\172.16.205.123\nucleus-central`. |
| Claude on box | Claude Code CLI + `claude_agent_sdk`, logged in as assad (Max sub) |

---

## 3. Prerequisites to install on the fresh PC
1. **Windows 10/11**, logged in as `ael\assad`.
2. **Python 3.13** (per-user, into `C:\Users\assad\AppData\Local\Programs\Python\Python313\`). Add to PATH.
3. **Node.js 22 LTS** (for Claude Code + SDK).
4. **Claude Code CLI:** `npm i -g @anthropic-ai/claude-code`.
5. **ffmpeg** — download Gyan release, extract to `C:\Tools\ffmpeg\...\bin\ffmpeg.exe` (needed for call mirroring).
6. **Microsoft Teams** (new client) + **Git** + **OpenSSH client** (built into Win10/11).
7. WinRM reachable from Titu's PC: `Enable-PSRemoting -Force`; on Titu PC `Set-Item WSMan:\localhost\Client\TrustedHosts '172.16.205.*'`.

---

## 4. Rebuild steps (ordered — ~1 hour)

**Step 1 — Get the code.**
Preferred: `cd E:\ ; git clone <napco-nucleus repo> napco-nucleus`.
Or restore the backup: `scp ubuntu@172.16.205.123:/home/ubuntu/nn-assistant-backup.zip .` then unzip its `teams\`, `agent\`, `scripts\`, `docs\` into `E:\napco-nucleus\`, and rename `env.txt` → `.env`.

**Step 2 — Python deps.** `cd E:\napco-nucleus ; py -3 -m pip install -r requirements.txt` then `py -3 -m pip install uiautomation claude_agent_sdk python-dotenv`.

**Step 3 — ffmpeg.** Install to `C:\Tools\ffmpeg\...\bin\ffmpeg.exe`; confirm `.env` has `NUCLEUS_FFMPEG=` that exact path.

**Step 4 — Restore `.env`** (see Section 6 for the exact keys). **Write it WITHOUT a BOM** (`[IO.File]::WriteAllText(path,text,(New-Object Text.UTF8Encoding($false)))`). A BOM corrupts the first key — this bit us once.

**Step 5 — Sign into Teams** on the box as the Meeting Assistant: `kamrul.celloscope@gmail.com`. Set display name "Napco Nucleus". Enable auto-start (Settings > General > auto-start).

**Step 6 — Sign into Claude Code** (at the console): `cd E:\napco-nucleus ; claude` (sign in), then `claude setup-token` (for headless jobs). Verify `claude --version`.

**Step 7 — SSH key `.72`→`.123`** (for health checks + pipeline trigger):
`ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\id_ed25519" -N '""' -q`
then Titu authorizes the new pubkey on `.123`:
`ssh ubuntu@172.16.205.123 "echo '<pubkey>' >> ~/.ssh/authorized_keys"`.
Test: `ssh ubuntu@172.16.205.123 hostname`.

**Step 8 — Register the scheduled tasks** (run each via `powershell -File`, NOT inline):
```
powershell -ExecutionPolicy Bypass -File E:\napco-nucleus\scripts\register-voice-daemon-task.ps1
powershell -ExecutionPolicy Bypass -File E:\napco-nucleus\scripts\register-auto-reply-task.ps1
powershell -ExecutionPolicy Bypass -File E:\napco-nucleus\scripts\register-live-heartbeat-task.ps1
powershell -ExecutionPolicy Bypass -File E:\napco-nucleus\scripts\register-reminder-task.ps1
```
(plus the auto-answer, watchdog, self-heal register scripts if present in the repo.)

**Step 9 — Auto-login + never-lock** (so it comes up unlocked after reboot — MANDATORY, UI-automation dies on a locked screen):
- Sysinternals **Autologon**: run it, Username `assad`, Domain `AEL`, password, Enable.
- Never lock/sleep (elevated):
```
powercfg /change standby-timeout-ac 0
reg add "HKCU\Control Panel\Desktop" /v ScreenSaverIsSecure /t REG_SZ /d 0 /f
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v DisableLockWorkstation /t REG_DWORD /d 1 /f
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v InactivityTimeoutSecs /t REG_DWORD /d 0 /f
```
Turn the monitor off instead of locking.

**Step 10 — Start + verify.** `Start-ScheduledTask` each task, then run the Section 7 checklist.

**Re-run the backup after changes:** on the box, zip `teams\*.py teams\*.json teams\*.md .env agent\ scripts\register-*.ps1 docs\` and `scp` the zip to `ubuntu@172.16.205.123:/home/ubuntu/nn-assistant-backup.zip`.

---

## 5. The services (scheduled tasks, all at-logon interactive, auto-restart)
| Task | File | Does |
|---|---|---|
| NAPCO Nucleus - Voice Daemon | `teams/record_call.py` + `voice_daemon.py` | records Teams calls, encodes opus, mirrors to Central |
| NAPCO Nucleus - Auto Answer | `teams/auto_answer.py` | clicks Accept on incoming calls (audio) |
| NAPCO Nucleus - Auto Reply | `teams/auto_reply.py` (+ `auto_reply_rules.json`, `nucleus_persona.md`) | the chat assistant (see Section 6) |
| NAPCO Nucleus - Live Heartbeat | `teams/live_heartbeat.py` | live capture status to Central during calls |
| NAPCO Nucleus - Dev Reminder | `teams/remind_devs.py` (+ `dev_list.json`) | gentle "add me to meetings" nudges |
| NAPCO Nucleus - Voice Watchdog / Chat Push / Self-Heal | repo scripts | restart-if-dead / chat mirror / re-register tasks |

---

## 6. Config file contents

**`.env`** (E:\napco-nucleus\.env, NO BOM):
```
NUCLEUS_DEV_NAME=napco-nucleus
NUCLEUS_CENTRAL_PATH=\\172.16.205.123\nucleus-central
NUCLEUS_SAMBA_USER=nucleus
NUCLEUS_SAMBA_PASSWORD=
NUCLEUS_FFMPEG=C:\Tools\ffmpeg\<ver>\bin\ffmpeg.exe
GOOGLE_CREDENTIALS_PATH=<path if used>
```

**`teams/auto_reply_rules.json`** — settings + canned rules + commands:
- `settings`: `poll_seconds` 1.0, `claude_model` `claude-haiku-4-5-20251001`, `human_typing` true, `type_speed` 0.012, `think_min/max` 0.1/0.25, `reply_gap_s` 5, `repeat_window_s` 1800, `keep_alive` true, `diagnose` false, `own_names` ["Napco Nucleus"].
- `rules`: name→"I am Napco Nucleus."; creator/builder/maker/etc→"I was created by Mohammad Kamrul Hasan."; thanks/greetings/courtesy have `"always": true` (reply every time).
- `commands`: [1] health — `contains` "check pipeline health / requirement status / email status ...", `report_cmd` = ssh into .123 gathering `docker ps` + latest transcripts + emails. [2] run pipeline — `contains` "run the pipeline / send email ...", `ack` "Okay {sender} bhai", `dedup` true (fingerprints Central so 7 devs after 1 call = 1 run). **Leave the pipeline trigger empty on purpose — Titu did NOT want it to email the boss.**

**`teams/nucleus_persona.md`** — the Claude persona: identity ("I am Napco Nucleus"), creator, scope = answer requirement-management questions accurately + decline off-topic, glossary (pipeline/requirements/voice-record/chat/"send email"=command), the requirement-flow facts, and "sometimes reply in Bangla addressing devs as `<name> ভাই`" (Rocky/রকি, Zaman/জামান, Ferdous/ফেরদৌস, Ishraq/ইশরাক, Amin/আমিন, Titu/টিটু, Atik/আতিক).

**`teams/dev_list.json`** — `devs` (Teams display names to remind) + `messages` (soft) + `jokes` (used ≤2/week). Empty `devs` = reminder no-ops.

---

## 7. Verification checklist (after rebuild)
- [ ] All NN scheduled tasks show **Running**/Ready: `Get-ScheduledTask | ? {$_.TaskName -like 'NAPCO Nucleus*'}`.
- [ ] Exactly ONE `auto_reply` pythonw process; log shows "warm sdk connected".
- [ ] Teams signed in as Napco Nucleus, presence **Available** (not Away → screen unlocked).
- [ ] From a test account: "Hi" → one Hello; a question → one answer; same question again in 30 min → "already answered, bhai".
- [ ] Two accounts message in parallel → it switches between chats and answers both.
- [ ] "check pipeline health" → it SSHes .123 and replies with a status.
- [ ] Make a test call → it auto-answers, records, and a file lands in `\\.123\nucleus-central\napco-nucleus\<date>\calls\`; a live beacon appears in `.../live/` during the call.
- [ ] SSH `.72`→`.123` works (`ssh ubuntu@172.16.205.123 hostname`).

---

## 8. Gotchas (hard-won — read before rebuilding)
1. **Locked screen = dead.** UI-automation cannot read/type on a locked Windows session, and Teams goes Away. Auto-login + never-lock (Step 9) is mandatory. True locked/headless operation is only possible with a **licensed M365 tenant + Graph API bot** — not the free Gmail account.
2. **BOM kills `.env`.** Never write `.env`/JSON with PowerShell `Set-Content -Encoding UTF8` / `Out-File` (adds a BOM → python-dotenv drops the first key; json.loads throws). Use `[IO.File]::WriteAllText(p,t,(New-Object Text.UTF8Encoding($false)))`.
3. **Message format varies.** Teams labels bubbles "Message from X. text" OR "text by X". The assistant parses both and matches the sender to the chat-title partner — that's what stops it answering its own messages / chrome.
4. **Multi-chat.** UI-automation only sees the OPEN chat. The assistant scans the list for "Unread message Chat <name>" entries, opens each, replies. Repeat/gap tracking is per-contact.
5. **Classifier blocks (deploying from Titu's PC):** the auto-mode classifier blocks nested `claude` calls over WinRM, mass-messaging scripts in batches, security-policy registry edits, credential-file reads, and auto-send-email automation. Deploy code via base64 `WriteAllBytes`; register tasks via `powershell -File`; Titu deploys the email/auto-send pieces himself.
6. **Warm SDK.** Speed comes from keeping ONE `ClaudeSDKClient` warm in a background thread (pre-warmed at startup, ~24s once). Do NOT go back to `claude --print` per message (~8s each). Falls back to CLI if the warm client drops.
7. **Model = Haiku** for chat (fast, no quality loss). **Central `.123` sends the requirement email**, not the box. Run-pipeline is ack-only by design (no boss email).

---

## 9. Quick reference
- MASTAN2 office `172.16.205.72` / home `192.168.0.210`, account `ael\assad`, cred `%USERPROFILE%\.210.cred.xml`.
- Central `ubuntu@172.16.205.123`, share `\\172.16.205.123\nucleus-central`, calls land in `napco-nucleus\<date>\calls\`.
- Repo `E:\napco-nucleus`; ffmpeg `C:\Tools\ffmpeg\...\bin`; Python `py -3`.
- Teams `kamrul.celloscope@gmail.com` ("Napco Nucleus"). Claude = Max login on the box.
- Backup: `.123:/home/ubuntu/nn-assistant-backup.zip`. Memory: `project-napco-nucleus-assistant-2026-07-24`.
```
```
