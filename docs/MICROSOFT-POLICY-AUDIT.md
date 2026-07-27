# Microsoft policy audit — NAPCO Nucleus on .72

Audited 2026-07-27 by reading the code, not from memory. Scope: only what
touches Microsoft. Consent and privacy toward Salman / AEL / NAPCO are covered
separately in `RECORDING-DISCLOSURE.md` and are explicitly out of scope here.

Account under audit: personal Microsoft account `titucse1982@gmail.com`.
`ael-bd.com` has no Microsoft tenant, so no sanctioned API path exists.

**The only penalty Microsoft can apply is terminating that account.** It is
unrecoverable, because a fresh personal account can no longer sign into Teams.

## Severity and detectability are NOT the same ranking

The worst breach is the one Microsoft cannot see. The one most likely to get
the account killed is not the worst breach. Both rankings matter.

| # | What | Breach severity | Can Microsoft detect it? |
|---|---|---|---|
| A | Reading Teams' private IndexedDB | **Highest** | No — local file reads |
| B | UI-automating Teams to send messages | High | **Yes** — behavioural |
| C | Synthetic input to control presence | Medium | Partly — reduced 2026-07-27 |
| D | Personal account used commercially | Medium | Low |
| E | Loopback call recording | Not a Microsoft matter | No |

## A. Reading Teams' private IndexedDB store — worst in kind

`teams/reader.py`, `teams/calls.py`, `teams/list_chats.py` open

```
%LOCALAPPDATA%\Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams\
  EBWebView\WV2Profile_tfl\IndexedDB\https_teams.live.com_0.indexeddb.leveldb
```

directly, using **`ccl_chromium_reader`** — a Chromium **forensics** library,
the same class of tool used to recover browser artefacts in investigations.

What is extracted: chat message content, the conversation list, and call
history (`callId`, `callType`, `callDirection`, participant MRIs, display
names, start/end times).

Why this is the most serious item: it is not "using the service through the
interface provided" in any sense. It bypasses the application entirely and
reads Microsoft's client-side datastore as a filesystem artefact. Every other
item at least goes through the product.

Note `WV2Profile_tfl` = "Teams For Life", the **personal**-account profile.
This code is written specifically against the consumer client.

Also worth knowing: the read surface is the whole local store. The
seven-person recording boundary is applied *after* reading, in
`teams/_include.py`, not before.

**Can it be fixed without a tenant?** No. The sanctioned equivalent is
Microsoft Graph, which requires a work/school account. The only options are
keep it, or drop client-name resolution and chat ingest entirely.

## B. UI-automating Teams to send messages — most likely to get you banned

`teams/auto_reply.py`, `teams/notify.py`, `teams/remind_devs.py` drive the
Teams desktop client with `uiautomation` and `SendKeys`: `{Ctrl}n` for a new
chat, type the recipient, `{Enter}`, type the body, `{Enter}` to send.

This is the item with a real detection path. Microsoft cannot see the UIA
calls, but it sees the *output*: an account sending machine-composed replies
on machine-regular timing. Anti-abuse heuristics on consumer accounts are
built for exactly this shape.

Already working in your favour: NN replies **1:1 only** and never posts to a
group or meeting chat, which removes the most likely route to an abuse report
from another participant.

## C. Synthetic input to control presence — reduced 2026-07-27

`nudge_input()` in `teams/auto_reply.py` injects a mouse event via
`user32.mouse_event` to stop Teams reporting Away. It previously fired on a
fixed 50s interval every second the box was powered on, so presence was pinned
Available. That was the strongest bot signal in the system.

Now (`d2dfdb0`, `4b8e251`): jittered 30-70s, and only while there has been
real activity in the last 10 minutes — a message, or a call in progress. NN
starts Away and returns to Away between conversations. `.72` is powered
11:00-22:00, so overnight is naturally offline.

Residual: it is still synthetic input shaping what Microsoft reports as your
status. Lower risk now, not zero.

## D. Personal account used commercially

The Microsoft Services Agreement frames personal accounts as personal, non-
commercial use. This one runs a company's client-meeting assistant. Low
detection risk on its own, but it is the reason none of the sanctioned paths
(Graph, compliance recording, `Set-SPOTenant`) are available, and the reason a
ban would be unrecoverable.

## E. Loopback call recording — not a Microsoft matter

`teams/record_call.py` captures the default playback device via VB-CABLE. It
never touches Microsoft's wire and produces no server-side signal. Recording
your own speaker output is a consent question, not a Microsoft-terms question.
Handled in `RECORDING-DISCLOSURE.md`.

## What would actually close this

One Microsoft 365 Business Basic licence (~USD 6/user/month) on a company
address. That single change converts A from forensic extraction to Graph API
calls, B from UI automation to a registered bot, and D from a personal account
to a work account. Nothing else closes any of them.

Absent that, everything above is a knowingly accepted risk, not a compliant
configuration. The 2026-07-27 presence work reduced the probability of being
*noticed*. It did not make anything compliant, and it should not be recorded
as having done so.
