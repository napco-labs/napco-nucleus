# Task: Daily pipeline health check (runs 1 PM) with alerting

You are the Napco Nucleus ops agent on MASTAN2. Check the WHOLE requirement
pipeline end to end, including mirroring. If anything is genuinely BROKEN, alert.
If everything is fine (or simply idle), do NOT alert - just print a one-line OK.

## Stages to check
1. MIRRORING (call recordings reaching central):
   - Is the "NAPCO Nucleus - Voice Daemon" scheduled task Running on this box?
   - SSH ubuntu@172.16.205.123 and look under
     /srv/nucleus-central/napco-nucleus/<recent dates>/calls/ - do captured
     calls (wav/opus + .json) arrive? A call whose audio is there but has NO
     _transcript.md after a reasonable time = a problem downstream.
2. TRANSCRIBE: on .123, is the `nucleus-transcribe` container Up? (docker ps)
   Are recent calls getting a `_transcript.md`?
3. REQUIREMENTS: is requirement identification producing output? Check the
   requirement-management pipeline the way the repo defines it (see
   docs/requirement-management-flow.md), e.g. recent runs / requirement docs /
   GitLab issues, and that the relevant container(s) on .123 are Up.
4. EMAIL / notify: is the email path healthy (the daily-draft / mail relay on
   .123 reachable, no crash-loop)?

IMPORTANT: distinguish BROKEN (a service is down, a container is not Up, or
items are STUCK - audio with no transcript, transcript with no requirement)
from IDLE (no client calls happened today is NOT broken). Only alert on real
breakage.

## If (and only if) something is BROKEN
1. EMAIL khasan@ael-bd.com. Subject: "[ALERT] Napco Nucleus pipeline issue".
   Body: which stage is broken and the evidence. Use the project's existing mail
   relay - SSH to .123 and send via the NN Gmail SMTP relay that the pipeline
   already uses (creds are in the daily-draft container env; do not print them).
2. TEAMS: ping Titu -
   py -3 -m teams.notify titucse@hotmail.com "[ALERT] Napco Nucleus pipeline: <one-line what is broken>"

## Always
Print a short summary: what you checked, healthy or broken per stage, and any
alerts you sent. Be accurate and do not invent problems.
