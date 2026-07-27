# Recording disclosure and account ownership

Why this file exists: NAPCO Nucleus records Teams call audio through a virtual
loopback device. That capture does not trigger the Teams recording indicator, so
participants get no notification from Teams itself. The disclosure has to come
from us instead. This file is the wording, and the standing record of the
decision.

## 1. Automated disclosure (DONE, in code)

`mail/daily_rollup.py` appends `_DISCLOSURE` to every requirements rollup email,
including the "nothing found today" and coverage-note branches. Those emails
already go to the AEL team and to the client rep on Cc
(`NUCLEUS_ROLLUP_CC_REQS_ONLY`), so every recipient gets a dated, repeating
written notice.

It is deliberately **not** env-gated. A switch to turn the disclosure off would
defeat its purpose.

Current wording:

> How this was prepared: NAPCO Nucleus records and transcribes the AEL project
> team's MS Teams calls, and reads the project chats, email, and Google Drive
> files, so that what you ask for is captured accurately and nothing is missed.
> Recordings and transcripts are stored on AEL's internal server and are used
> only to prepare these requirement documents. If you would prefer any call not
> to be recorded, just say so and we will switch it off for that call.

## 2. Salman (the client) — TOLD DIRECTLY

**Confirmed by Titu, 2026-07-27: Salman has already been told directly that
calls are recorded.**

This matters because the rollup footer does not reach him. Salman is in the
recording boundary but is not on `NUCLEUS_ROLLUP_TO` or `NUCLEUS_ROLLUP_CC`, so
the automated disclosure covers the AEL team and `ayusuf@dcl-online.com` but
never reached the one recorded party outside AEL. The direct conversation is
what covers that, not the code.

If Salman is ever added to the rollup Cc, the footer covers him from then on
too. Not done — that changes who receives client requirement documents and is
Titu's call.

## 3. One-time announcement (TODO — Titu to send once)

The rollup footer covers people from here on. Send this once so the change is
explicit rather than something noticed in small print. Recipients: the AEL
people in the recording scope, plus the client rep. Salman is already covered
by the direct conversation above.

> Subject: How we capture requirements from our calls
>
> Hello all,
>
> A short note on how requirements get written up on this project.
>
> We use an internal assistant called NAPCO Nucleus. It records and transcribes
> our MS Teams project calls, and reads the project chats, email, and shared
> Drive files. It then drafts the Requirements Verification document you receive
> from us, so that what gets asked for on a call is captured accurately and
> nothing depends on somebody's memory or notes.
>
> Recordings and transcripts stay on AEL's own internal server. They are used
> only to prepare these requirement documents, and they are not shared outside
> the project.
>
> If you would rather a particular call was not recorded, just tell us at the
> start and we will switch it off for that call. Same if you would like a
> recording removed after the fact.
>
> Happy to answer any questions.
>
> Titu

## 4. Per-call practice

Say it out loud at the start of a call with anyone outside the seven-person
scope, especially the client. One sentence is enough: "Just so you know, we
record these calls so the requirements get written up accurately."

## 5. Account ownership

Teams currently runs as the personal Microsoft account
`titucse1982@gmail.com`. `ael-bd.com` has no Microsoft tenant (realm lookup
returns `NameSpaceType: Unknown`, OpenID discovery 400s, MX is Google
Workspace), so there is no work/school account available and no admin surface.

**The data is not at risk.** Recordings and transcripts mirror to
`\\172.16.205.123\nucleus-central`, which AEL owns. Verified 2026-07-27: the
2026-07-24 call's `_speaker.wav`, `_mic.wav`, and `_transcript.md` are all on
central. If the Microsoft account disappeared tomorrow, no captured data is
lost.

**What is at risk is the sign-in.** `.72` works only because it holds a Teams
session cached from before Microsoft removed fresh personal-account sign-in.
That session is effectively irreplaceable:

- Do not sign out of Teams on `.72`.
- Do not "fix" a Teams problem there by re-authenticating. A fresh personal
  sign-in will be refused and the assistant loses call access permanently.
- Do not reset the password on `titucse1982@gmail.com` unless you have to.

**The only durable fix** is one Microsoft 365 Business Basic licence (about
USD 6 per user per month) on a company-owned address such as
`napco-nucleus@ael-bd.com`. That gives a real work account, makes the sign-in
recoverable and company-owned, and is also the only route to the sanctioned
Graph and compliance-recording APIs instead of driving the Teams UI. Titu has
declined the spend so far; recorded here so the trade-off is a decision rather
than a drift.
