# Getting NN fully legitimate on ONE licence

Written 2026-07-27 after verifying each claim against Microsoft's own docs.
Constraint set by Titu: keep recording, keep live heartbeat, keep auto-reply,
keep call recording when NN is added to a meeting, and **only one paid user**
— the other seven colleagues stay on their personal Gmail Teams accounts.

## Recommendation

**Buy one Microsoft 365 Business Basic licence (~USD 6/user/month) for NN
only, on a new tenant, and move NN from "driving the Teams client" to
"calling Microsoft Graph".**

That single change removes every Microsoft breach in
`MICROSOFT-POLICY-AUDIT.md`. Total cost about USD 72/year. No Azure
subscription, no Teams Phone, no E3/E5, no certified recording partner.

## Verified facts this rests on

| Claim | Status |
|---|---|
| Business Basic includes Teams meeting recording + transcription, stored in OneDrive | Verified |
| Graph meeting recording/transcript APIs are **no longer metered** since 2025-08-25, no billing config needed | Verified on Microsoft Learn (`/graph/teams-licenses`, top banner) |
| Work accounts can chat with **unmanaged personal** Teams accounts | Verified — Teams admin centre, Users > External access |
| Compliance recording needs Business Standard/Premium/E3/E5 + certified partner | Verified — **and we do not need it**, see below |

We do **not** need compliance recording. That is for regulated capture of all
calls. We only need our own meetings recorded, which is ordinary Teams
recording and is included.

## Use `onmicrosoft.com`, do not touch `ael-bd.com`

`ael-bd.com` is Google Workspace with Google MX. Do **not** add it to the new
M365 tenant — that invites a mail-routing conflict for no gain. Create the
tenant with its own `<name>.onmicrosoft.com` domain and give NN an address
like `nucleus@napconucleus.onmicrosoft.com`, display name **Napco Nucleus**.
Zero DNS changes, zero risk to existing mail.

## What happens to each of your four wants

### 1. Auto-reply — keeps working, gets legitimate
Turn on **External access → allow unmanaged Teams accounts** so the seven
colleagues on personal Gmail can chat NN exactly as they do today. NN then
reads and replies through Graph (`GET /me/chats`, `POST /chats/{id}/messages`,
delegated `Chat.Read` / `ChatMessage.Send`), driven by change notifications
instead of polling a window.

Kills breach **B** (UIA + SendKeys) and breach **A** (IndexedDB scraping) in
one move. The persona, canned rules, dedup and Claude logic are unchanged —
only the transport swaps out. This is the natural place to hang Claude Code.

### 2. Call recording — Teams records it, NN fetches it
Stop the loopback capture entirely. Instead:
- Meetings get **Record automatically** switched on in meeting options.
- Teams records **and transcribes**, files land in NN's OneDrive.
- NN pulls both through Graph:
  `GET /users/{id}/onlineMeetings/{id}/recordings/{id}/content` and
  `.../transcripts/{id}/content`. Free since 2025-08-25.

This is strictly better than what we have. No VB-CABLE, no muted-speaker
failure mode, no unlocked desktop session, no Speaker Guard, and Teams shows
its own recording banner so consent stops being a thing we have to bolt on.

### 3. "Record when NN is added to a meeting" — CORRECTED 2026-07-27

An earlier draft said "NN must be the organiser". Titu killed that: **NN never
initiates. Colleagues and clients start the calls and add NN.** The organiser
change is not available, so that plan was wrong.

**The structural truth: no amount of money makes this sanctioned.** For a
meeting organised by a *personal* Microsoft account, there is no Microsoft
path for a third party to record it:

- Teams recording rights belong to the organiser's organisation. A consumer
  organiser has no organisation, and NN is an external guest in their meeting.
- Compliance recording only covers calls of users **inside your own tenant**.
  Your colleagues will never be in your tenant.
- A `Calls.AccessMedia.All` media bot can only join meetings in its own
  tenant, and needs Azure hosting besides.

So the recording **stays as loopback capture**, and that is the correct answer
rather than a compromise — because recording was never the Microsoft problem.
It is audit item E: local audio off our own sound device, never touching
Microsoft's wire, no server-side signal. The exposure it carries is consent,
which is handled (see `RECORDING-DISCLOSURE.md`, Salman told directly).

**The licence is still worth buying.** It clears A, B, C and D — the four items
that genuinely are Microsoft breaches. It just does not, and cannot, clear E.

### 3b. The residual: how NN joins the meeting

With chat on Graph, the last piece of UI automation left is *joining* a
meeting NN is added to. Two routes:

- **Keep the UIA auto-answer.** Honest residual breach, much smaller surface
  than today (one click path, no message sending, no store scraping).
- **Microsoft Teams Rooms Basic (free, up to 25 rooms).** Teams Rooms
  endpoints auto-answer incoming meeting invites natively via
  `Set-CsTeamsCallingPolicy -AutoAnswerEnabledType Enabled`. If NN runs as a
  Rooms endpoint this becomes a supported feature instead of a UIA hack.
  **NOT yet verified** that this works for our shape — the docs describe it
  for Teams Phones and Rooms devices, not desktop clients. Worth one
  afternoon's test before relying on it.

### 4. Live heartbeat — untouched
It writes a JSON beacon to the SMB share during a capture. It never touches
Microsoft. Keep exactly as is. (It will need repointing at the Graph-based
capture flow, but the mechanism stays.)

## What this eliminates

| Audit item | After |
|---|---|
| A. IndexedDB forensic reads | Gone — Graph chat APIs |
| B. UIA automation sending | Gone — Graph message send |
| C. Synthetic input for presence | Gone — chat no longer needs a desktop session |
| D. Personal account, commercial use | Gone — work account |
| E. Loopback recording | **Stays.** Cannot be bought into compliance while the organisers are consumer accounts. Not a Microsoft-terms matter anyway. |

Four of five. `.72` still needs an interactive session for the call capture
and the join, so Speaker Guard and the unlocked-screen requirement stay. The
chat half stops needing the desktop entirely and can move off `.72` to a
service — including onto `.123`.

## Check these BEFORE you pay

1. **Which chats does NN actually need to see?** Graph shows only chats NN is
   a **member** of. Today it reads its own local store, which is the same set
   — but confirm `teams/reader.py`'s monitored group chats are ones NN is
   genuinely in. If it is reading anything it is not a member of, that
   capability does not survive, and one licence cannot buy it back.
2. **External access to unmanaged accounts must be allowed** by the tenant
   admin (you). Microsoft is tightening federation controls between July and
   September 2026 — confirm the toggle is available when you set up.
3. **Transcript language.** Teams transcription on Bangla-heavy calls may be
   weaker than Chirp. Test one real call before retiring the Chirp path. If
   Teams transcription is not good enough, keep pulling the **recording** via
   Graph and keep sending it to Chirp — still fully legitimate, since the
   breach was never the transcription, it was how the audio was obtained.

## Migration order

1. Buy the licence, create the tenant on `onmicrosoft.com`, enable external
   access to unmanaged accounts. Nothing breaks; NN keeps running as-is.
2. Get the seven colleagues chatting with the new NN account. Run the old and
   new side by side.
3. Rewrite the chat path onto Graph. Retire `reader.py`, `list_chats.py`, and
   the UIA send path in `auto_reply.py` / `notify.py` / `remind_devs.py`.
4. Switch meeting creation to NN's account with auto-record on. Verify one
   real call end to end, including transcript quality.
5. Retire `record_call.py`, VB-CABLE, Speaker Guard, and the presence
   keep-alive. Delete `calls.py`'s IndexedDB resolver — Graph gives
   participants directly.

Steps 1 and 2 are reversible and cost one month's licence to try. Do those
first and prove the chat path before committing to steps 3 to 5.
