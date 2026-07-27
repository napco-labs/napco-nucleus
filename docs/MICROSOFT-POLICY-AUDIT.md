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

## What would actually close this — corrected 2026-07-27

An earlier draft of this file said one Business Basic licence "converts A, B
and D". That was too glib in two ways, corrected here.

**A licence alone fixes exactly one item: D.** A work/school account on a
company address is company-owned, recoverable, and signs into Teams normally.
That is a purchase, and it is done.

**A and B need a code rewrite; the licence only makes the rewrite possible.**
Buying it changes nothing on its own.

| Item | What the licence gives you | What you still have to build |
|---|---|---|
| A. IndexedDB extraction | Microsoft Graph: `Chat.Read` / `ChatMessage.Read` for chats, `CallRecords.Read.All` for call metadata | Replace `teams/reader.py`, `teams/calls.py`, `teams/list_chats.py` with Graph calls. Register an Entra app (free). Real work, not a config change. |
| B. UI automation sending | Graph `Chat.ReadWrite` to send as the user, or a registered Teams bot | Rewrite `auto_reply.py` / `notify.py` / `remind_devs.py` off `uiautomation`+`SendKeys`. The persona/canned/Claude logic survives; only the transport changes. |
| D. Personal account | Done on purchase | Nothing. |

**Business Basic does NOT give you sanctioned call recording.** Verified
against Microsoft's own docs: compliance recording requires **Business
Standard, Business Premium, E3, E5, A3/A5 or G3/G5** — Business Basic is
explicitly not eligible, and there is no standalone add-on that makes it
eligible. It also only works through a **Microsoft-certified third-party
recording partner** (NICE, Verint, Dubber, ASC and similar) running a
recording bot in the tenant. That is enterprise-priced software, not something
to build.

So the sanctioned recording path is far beyond USD 6/month and is not
realistically on the table.

**Why that may not matter to you.** Recording is item E, and item E is not a
Microsoft matter at all — loopback capture never touches Microsoft's wire and
produces no server-side signal. If the concern is strictly Microsoft risk,
the recording can stay exactly as it is and you lose nothing by never having
compliance recording.

Absent any of this, everything above is a knowingly accepted risk, not a
compliant configuration. The 2026-07-27 presence work reduced the probability
of being *noticed*. It did not make anything compliant, and it should not be
recorded as having done so.

Absent that, everything above is a knowingly accepted risk, not a compliant
configuration. The 2026-07-27 presence work reduced the probability of being
*noticed*. It did not make anything compliant, and it should not be recorded
as having done so.
