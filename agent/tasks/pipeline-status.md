# Task: Requirement-management pipeline status (read-only)

You are the Napco Nucleus operations agent on MASTAN2. Produce a short,
plain-language status of the requirement pipeline so Titu can see health at a
glance. Read-only: do not modify any pipeline state.

Steps:
1. On central (\\172.16.205.123\nucleus-central\napco-nucleus\), for today and
   yesterday, check:
   - calls\  : how many calls captured (opus/wav + .json)
   - which have a *_transcript.md (transcribed) vs not
   - live\   : any call currently recording right now
2. Flag anything stuck: audio present but no transcript after a while;
   a call that never mirrored; a live beacon that hasn't updated.
3. Write a 5-8 line summary to logs\agent\pipeline-status-<date>.txt and print
   it. Include counts (captured / transcribed / stuck) and the timestamp of the
   most recent capture.

Keep it short and factual. No changes, just a status readout.
