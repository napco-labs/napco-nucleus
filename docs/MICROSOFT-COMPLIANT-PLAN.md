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

### 3. "Record when NN is added to a meeting" — one workflow change
This is the only real constraint. In Teams, an **external participant cannot
start a recording**. If a colleague on a personal account organises the
meeting and merely adds NN, NN cannot record it.

**So NN must be the organiser.** Practically: NN's account creates the meeting
(easy to automate — `POST /me/onlineMeetings` returns a join link) and
everyone joins that link as guests. Nobody needs a licence to join.

If you would rather not change who schedules, the alternative is a real-time
media bot with `Calls.AccessMedia.All`, which needs Azure hosting, a public
HTTPS endpoint and a .NET media stack. Not worth it for one user. Recommend
the organiser change.

### 4. Live heartbeat — untouched
It writes a JSON beacon to the SMB share during a capture. It never touches
Microsoft. Keep exactly as is. (It will need repointing at the Graph-based
capture flow, but the mechanism stays.)

## What this eliminates

| Audit item | After |
|---|---|
| A. IndexedDB forensic reads | Gone — Graph chat APIs |
| B. UIA automation sending | Gone — Graph message send |
| C. Synthetic input for presence | Gone — a Graph service needs no desktop session at all |
| D. Personal account, commercial use | Gone — work account |
| E. Loopback recording | Gone — Teams' own recording |

`.72` stops needing an unlocked interactive session with Teams running. That
removes the entire class of failure that has been costing recordings.

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
