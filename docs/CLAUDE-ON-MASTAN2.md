# Claude Code as the operations agent on MASTAN2 (.72 / 192.168.0.210)

MASTAN2 already has Claude Code (v2.1.211) + Node v22 installed. This is the
"brain" that operates the Meeting Assistant, alongside the always-on daemons
(the "reflexes").

## Layers
- Reflexes (24/7 scheduled tasks, no Claude): Voice Daemon, Auto Answer,
  Auto Reply, Live Heartbeat. These run by themselves.
- Brain (Claude Code, on demand or scheduled): reminders, pipeline status,
  dynamic decisions, tuning. This doc is about the brain.

## One-time login (do this at the console / RDP on MASTAN2 as ael\assad)
1. Open PowerShell.
2. `cd E:\napco-nucleus`
3. Interactive use:  `claude`   -> follow the auth prompt (sign in).
4. For scheduled/headless jobs also run once:  `claude setup-token`
   (creates a long-lived token so `claude --print` works unattended).
5. Verify:  `claude --version`  and try:  `claude --print "say hello"`

## Running an agent task
```
cd E:\napco-nucleus
.\agent\agent-run.ps1 -Task pipeline-status       # read-only status
.\agent\agent-run.ps1 -Task remind-add-nucleus    # drafts a reminder (no send)
```
Output is logged to `logs\agent\<task>-<stamp>.log`.

- Normal (safe) mode asks before actions. For a reviewed task that must act
  unattended, add `-Autonomous` (passes --dangerously-skip-permissions).

## Add your own tasks
Drop a new prompt file in `agent\tasks\<name>.md` describing what to do in plain
English, then `.\agent\agent-run.ps1 -Task <name>`. No code needed.

## Schedule it (optional, once logged in)
Task Scheduler -> daily action:
`powershell.exe -File E:\napco-nucleus\agent\agent-run.ps1 -Task pipeline-status`

## Safety defaults baked in
- Reminders produce a DRAFT for Titu to review; nothing is auto-sent.
- Status tasks are read-only.
- Switch a specific channel to auto-send only when you explicitly decide to.
