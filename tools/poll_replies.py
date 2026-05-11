"""Poll IMAP for replies to verification emails, parse, update memory.

Closes the verification loop:

  1. Scan the inbox for emails in the last N days where the subject
     starts with "Re: Requirements Verification" or where In-Reply-To
     matches our verification draft patterns.
  2. For each matched reply, fetch its full body.
  3. Ask Claude (via the agent SDK + local CLI) to classify per
     pending-requirement: confirmed / needs_change / rejected /
     unclear. Match by title (semantic) — minor wording differences
     are fine.
  4. Apply each classification via memory.update_confirmation. Persists
     the reply UID so the same email can't double-update.

The pending-requirement pool comes from memory.pending_requirements
filtered by sender domain → client_name (NAPCO Security from
@napcosecurity.com; AEL-internal stakeholders from @ael-bd.com).

Usage:
    py -3 -m tools.poll_replies                    # last 7 days
    py -3 -m tools.poll_replies --days 14
    py -3 -m tools.poll_replies --dry-run          # parse + classify
                                                   # but don't write
                                                   # to memory
    py -3 -m tools.poll_replies --json             # machine-readable
"""
from __future__ import annotations

import argparse
import datetime as dt
import email
import email.utils
import imaplib
import json
import os
import re
import sys
from pathlib import Path

# UTF-8 stdout
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_HERE / ".env", override=False)

import anyio  # noqa: E402

import memory  # noqa: E402
import napco_config as nucleus_config  # noqa: E402
from tools._retry import retry as _retry_deco  # noqa: E402


# ── IMAP helpers ─────────────────────────────────────────────────

_SUBJECT_RE = re.compile(r"re:\s*requirements?\s+verification", re.IGNORECASE)


def _imap_login():
    host = (os.getenv("REQ_IMAP_HOST") or "imap.gmail.com").strip()
    port = int(os.getenv("REQ_IMAP_PORT", "993"))
    user = (os.getenv("REQ_IMAP_USER") or "").strip()
    pw = os.getenv("REQ_IMAP_PASSWORD") or ""
    mailbox = (os.getenv("REQ_IMAP_MAILBOX") or "INBOX").strip()
    if not user or not pw:
        raise RuntimeError("REQ_IMAP_USER / REQ_IMAP_PASSWORD must be set")
    m = imaplib.IMAP4_SSL(host, port)
    m.login(user, pw)
    m.select(mailbox, readonly=True)
    return m


def _imap_date(d: dt.date) -> str:
    return d.strftime("%d-%b-%Y")


def _decode_header(raw) -> str:
    if not raw:
        return ""
    from email.header import decode_header, make_header
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _body_text(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if ctype == "text/plain" and "attachment" not in disp:
                try:
                    payload = part.get_payload(decode=True) or b""
                    return payload.decode(
                        part.get_content_charset() or "utf-8",
                        errors="replace")
                except Exception:
                    continue
        # Fallback: any text/html collapsed to text
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    payload = part.get_payload(decode=True) or b""
                    raw_html = payload.decode(
                        part.get_content_charset() or "utf-8",
                        errors="replace")
                    return _strip_html(raw_html)
                except Exception:
                    continue
        return ""
    try:
        payload = msg.get_payload(decode=True) or b""
        return payload.decode(
            msg.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return ""


def _strip_html(html: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    s = re.sub(r"</p\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


def _sender_to_client(sender: str) -> str | None:
    """Map an email From header to a canonical client_name following
    the verify_session prompt conventions."""
    s = (sender or "").lower()
    if "@napcosecurity.com" in s:
        return "NAPCO Security"
    # AEL-internal: map specific addresses we know
    aliases = {
        "assad@ael-bd.com":   "Assaduz Zaman",
        "arzaman@ael-bd.com": "Atikur Zaman",
        "arhabib@ael-bd.com": "Ahsan Habib",
        "ihasan@ael-bd.com":  "Isruk Hasan",
        "khasan@ael-bd.com":  "Titu",
    }
    for addr, name in aliases.items():
        if addr in s:
            return name
    return None


@_retry_deco(attempts=3, base_delay=1.0)
def fetch_replies(days: int) -> list[dict]:
    """Return raw reply dicts: {uid, from, subject, received, body,
    in_reply_to, references}. Retried on transient IMAP errors."""
    end_dt = dt.datetime.now()
    start_dt = end_dt - dt.timedelta(days=days)

    out: list[dict] = []
    m = _imap_login()
    try:
        crit = ["SINCE", _imap_date(start_dt.date())]
        typ, data = m.uid("SEARCH", None, *crit)
        if typ != "OK":
            return out
        uids = (data[0] or b"").split()
        for uid_b in uids:
            uid = uid_b.decode()
            typ, msg_data = m.uid("FETCH", uid, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if not isinstance(raw, bytes):
                continue
            msg = email.message_from_bytes(raw)
            subject = _decode_header(msg.get("Subject"))
            if not subject or not _SUBJECT_RE.search(subject):
                continue
            sender = _decode_header(msg.get("From"))
            date_hdr = msg.get("Date") or ""
            try:
                received = email.utils.parsedate_to_datetime(date_hdr)
                if received:
                    received = received.astimezone().replace(tzinfo=None)
            except Exception:
                received = None
            out.append({
                "uid": uid,
                "from": sender,
                "subject": subject,
                "received": (received.strftime("%Y-%m-%d %H:%M")
                             if received else ""),
                "body": _body_text(msg),
                "in_reply_to": (msg.get("In-Reply-To") or "").strip(),
                "references": (msg.get("References") or "").strip(),
            })
    finally:
        try:
            m.logout()
        except Exception:
            pass
    return out


# ── Claude-as-classifier ────────────────────────────────────────

CLASSIFIER_SYSTEM = """\
You classify a client's reply to a Requirements Verification email
against the list of pending requirements that were drafted to that
client. Per requirement, decide: did the client confirm it as written,
ask for a change, reject it, or leave it unclear / not mention it?

You will receive in the user message:

{
  "client_name": "<canonical client name>",
  "reply_text": "<the body of the client's reply, plain text>",
  "pending_requirements": [
    {"id": 12, "title": "...", "summary": "..."},
    ...
  ]
}

For EACH pending requirement, return one classification:

- "confirmed"     — client explicitly agrees with the requirement as
                    written
- "needs_change"  — client agrees with the intent but asks for changes
                    (scope, wording, priority, timing)
- "rejected"      — client says don't do this
- "unclear"       — client didn't mention this requirement, OR
                    mentioned it ambiguously
- "not_mentioned" — same as unclear; use when the reply simply doesn't
                    reference this requirement at all (more honest
                    than guessing "unclear")

Return EXACTLY this JSON shape, no prose, no markdown fences:

{
  "classifications": [
    {
      "id": <int requirement id>,
      "status": "confirmed" | "needs_change" | "rejected" | "unclear" | "not_mentioned",
      "notes": "<one short sentence quoting or paraphrasing the relevant client text; empty if not mentioned>"
    },
    ...
  ]
}

Be conservative. If the client said "approved" without enumerating
specific items, mark every requirement "confirmed" with a note quoting
the approval line. If the client said "looks good but item 3 needs
adjustment", mark items 1/2/4/5 as confirmed and item 3 as
needs_change. If the reply is acknowledgement only ("got it, will
review"), mark everything "unclear" — they haven't actually agreed.
"""


def _extract_text(msg) -> str:
    out: list[str] = []
    content = getattr(msg, "content", None)
    if isinstance(content, list):
        for block in content:
            t = getattr(block, "text", None)
            if isinstance(t, str):
                out.append(t)
    t = getattr(msg, "text", None)
    if isinstance(t, str):
        out.append(t)
    return "\n".join(out)


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


async def _classify_via_claude(client_name: str, reply_text: str,
                                pending: list[dict]) -> list[dict]:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient  # lazy

    options_kwargs = {"system_prompt": CLASSIFIER_SYSTEM}
    cli_path = nucleus_config.claude_cli_path()
    if cli_path:
        options_kwargs["cli_path"] = cli_path
    options = ClaudeAgentOptions(**options_kwargs)

    payload = {
        "client_name": client_name,
        "reply_text": reply_text,
        "pending_requirements": [
            {"id": r["id"],
             "title": r["title"],
             "summary": (r.get("summary") or "")[:240]}
            for r in pending
        ],
    }

    chunks: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(json.dumps(payload, ensure_ascii=False))
        async for msg in client.receive_response():
            t = _extract_text(msg)
            if t:
                chunks.append(t)

    raw = _strip_fences("".join(chunks))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"classifier non-JSON. err={e}. raw[:400]={raw[:400]!r}")
    out = data.get("classifications") or []
    if not isinstance(out, list):
        raise RuntimeError(f"classifier bad shape: {type(out).__name__}")
    return out


# ── Orchestration ───────────────────────────────────────────────

def _color(s: str, code: str) -> str: return f"\033[{code}m{s}\033[0m"
def _g(s: str) -> str: return _color(s, "32")
def _y(s: str) -> str: return _color(s, "33")
def _r(s: str) -> str: return _color(s, "31")
def _d(s: str) -> str: return _color(s, "2")


def process_reply(reply: dict, dry_run: bool) -> dict:
    """Match reply -> client -> pending requirements -> classify ->
    apply. Returns a result dict."""
    client = _sender_to_client(reply["from"])
    if not client:
        return {"uid": reply["uid"], "from": reply["from"],
                "status": "no_client_match",
                "reason": "could not resolve sender to a known client"}

    pending = memory.pending_requirements(client_name=client, limit=200)
    if not pending:
        return {"uid": reply["uid"], "client": client,
                "status": "no_pending",
                "reason": f"no pending requirements for {client}"}

    body = (reply.get("body") or "").strip()
    if not body:
        return {"uid": reply["uid"], "client": client,
                "status": "empty_body"}

    try:
        classifications = anyio.run(
            _classify_via_claude, client, body, pending)
    except Exception as e:
        return {"uid": reply["uid"], "client": client,
                "status": "classifier_error",
                "error": f"{type(e).__name__}: {e}"}

    applied: list[dict] = []
    confirmed_at = (reply.get("received") or "").strip() or None
    for c in classifications:
        rid = c.get("id")
        status = c.get("status") or "unclear"
        if status == "not_mentioned":
            status = "unclear"
        notes = c.get("notes") or ""
        if status == "unclear":
            applied.append({"id": rid, "status": status,
                            "applied": False, "reason": "no-op for unclear"})
            continue
        if dry_run:
            applied.append({"id": rid, "status": status,
                            "applied": False, "reason": "dry-run"})
            continue
        ok = memory.update_confirmation(
            requirement_id=rid, status=status, notes=notes,
            email_uid=reply["uid"], confirmed_at=confirmed_at)
        applied.append({"id": rid, "status": status, "applied": bool(ok)})

    return {"uid": reply["uid"], "client": client,
            "status": "processed",
            "classifications": classifications,
            "applied": applied}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7,
                    help="Look back N days. Default: 7.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Classify but do NOT write to memory.")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="Machine-readable output.")
    args = ap.parse_args()

    if not args.as_json:
        print(f"\nPolling INBOX for verification replies "
              f"(last {args.days} day(s))…")
    try:
        replies = fetch_replies(days=args.days)
    except Exception as e:
        print(_r(f"IMAP error: {type(e).__name__}: {e}"), file=sys.stderr)
        return 2

    if not args.as_json:
        print(f"Matched {len(replies)} candidate reply email(s).")

    if not replies:
        return 0

    results: list[dict] = []
    for r in replies:
        if not args.as_json:
            print()
            print(_d(f"--- reply uid={r['uid']} from {r['from'][:60]} "
                     f"received {r['received']} ---"))
        res = process_reply(r, dry_run=args.dry_run)
        results.append(res)
        if args.as_json:
            continue
        status = res["status"]
        if status == "no_client_match":
            print(_y(f"  skipped: {res['reason']}"))
        elif status == "no_pending":
            print(_d(f"  no pending requirements for {res['client']}"))
        elif status == "empty_body":
            print(_y("  empty body"))
        elif status == "classifier_error":
            print(_r(f"  classifier failed: {res['error']}"))
        elif status == "processed":
            for a in res["applied"]:
                marker = (_g("✓") if a.get("applied")
                          else _d("·") if a.get("reason") == "dry-run"
                          else _y("—"))
                print(f"  {marker} id={a['id']:>4}  {a['status']:14s}"
                      + (f"  ({a['reason']})" if a.get("reason") else ""))

    if args.as_json:
        print(json.dumps({"days": args.days, "dry_run": args.dry_run,
                          "results": results}, indent=2, default=str))

    counts = memory.confirmation_counts()
    if not args.as_json:
        print()
        print("Confirmation state across requirements_seen:")
        for k in ("pending", "confirmed", "needs_change", "rejected", "unclear"):
            print(f"  {k:14s} {counts.get(k, 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
