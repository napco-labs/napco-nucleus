"""Stage new emails from IMAP into the central share.

Runs on MVPACCESS via Task Scheduler every 15 min (mirroring how the
chat-push cron runs on each dev's machine, and how the voice daemon
auto-uploads calls when a recording stops). Background capture; not
triggered by the operator.

What it does:
  1. Read REQ_IMAP_* creds from .env.
  2. Use the email_checkpoints table to find the last UID seen for
     this mailbox; SEARCH for UIDs > that.
  3. For each new email, build a plain-text record:

        From: <sender>
        To: <recipients>
        Subject: <subject>
        Received: <YYYY-MM-DD HH:MM>
        UID: <imap-uid>

        Body:
        <plain text body>

        Attachments (N):
          --- attachment: <filename> ---
          <extracted text>
          ...

     Save to <central>/email/<YYYY-MM-DD>/<HHMM>_<sender-slug>__<uid>.txt
  4. Update the email_checkpoints row so the next run only processes
     genuinely new messages.

The requirement-management workflow does its own live pull of the
same window, so this staging is purely an additive audit trail —
central now holds a permanent record of every email processed,
matching chat / calls / Drive staging.

Usage:
  py -3 -m tools.stage_email                    # incremental since checkpoint
  py -3 -m tools.stage_email --since 60         # last 60 minutes (manual)
  py -3 -m tools.stage_email --dry-run          # plan only
"""
from __future__ import annotations

import argparse
import datetime as dt
import email
import email.utils
import imaplib
import os
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_HERE / ".env", override=False)

import memory  # noqa: E402
from mail import requirements_inbox as ri  # noqa: E402
from tools._retry import retry as _retry_deco  # noqa: E402


_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _slug(s: str, max_len: int = 40) -> str:
    s = _SLUG_RE.sub("-", (s or "").strip()).strip("-").lower()
    return s[:max_len] or "x"


def _central_email_dir(received_dt: dt.datetime | None) -> Path | None:
    raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    if not raw:
        return None
    day = (received_dt or dt.datetime.now()).strftime("%Y-%m-%d")
    return Path(raw) / "email" / day


def _mailbox_key() -> str:
    user = (os.getenv("REQ_IMAP_USER") or "").strip()
    mb = (os.getenv("REQ_IMAP_MAILBOX") or "INBOX").strip()
    return f"{user}|{mb}"


@_retry_deco(attempts=3, base_delay=1.0)
def _imap_login_select() -> imaplib.IMAP4_SSL:
    host = (os.getenv("REQ_IMAP_HOST") or "imap.gmail.com").strip()
    port = int(os.getenv("REQ_IMAP_PORT", "993"))
    user = (os.getenv("REQ_IMAP_USER") or "").strip()
    pw = os.getenv("REQ_IMAP_PASSWORD") or ""
    mailbox = (os.getenv("REQ_IMAP_MAILBOX") or "INBOX").strip()
    if not user or not pw:
        raise RuntimeError("REQ_IMAP_USER / REQ_IMAP_PASSWORD must be set")
    m = imaplib.IMAP4_SSL(host, port)
    m.login(user, pw)
    typ, _ = m.select(mailbox, readonly=True)
    if typ != "OK":
        raise RuntimeError(f"IMAP SELECT failed: {typ}")
    return m


def _fetch_new_uids(m: imaplib.IMAP4_SSL, since_uid: int | None,
                    since_dt: dt.datetime | None) -> list[str]:
    """Use UID > since_uid if we have one (precise + cheap). Otherwise
    fall back to SINCE <date> + client-side dedup."""
    if since_uid is not None and since_uid > 0:
        # UID range search: UID since_uid+1:*
        typ, data = m.uid("SEARCH", None, f"UID {since_uid + 1}:*")
        if typ != "OK":
            return []
        return [u.decode() for u in (data[0] or b"").split() if u]
    # First run, no checkpoint — fall back to time window
    if since_dt is None:
        since_dt = dt.datetime.now() - dt.timedelta(hours=24)
    crit = ["SINCE", since_dt.strftime("%d-%b-%Y")]
    typ, data = m.uid("SEARCH", None, *crit)
    if typ != "OK":
        return []
    return [u.decode() for u in (data[0] or b"").split() if u]


def _parse_message(m: imaplib.IMAP4_SSL, uid: str) -> dict | None:
    typ, msg_data = m.uid("FETCH", uid, "(RFC822 UID)")
    if typ != "OK" or not msg_data or not msg_data[0]:
        return None
    raw = msg_data[0][1]
    if not isinstance(raw, bytes):
        return None
    msg = email.message_from_bytes(raw)
    from_hdr = ri._decode(msg.get("From"))
    from_addr = ri._extract_from_address(from_hdr)
    subj = ri._decode(msg.get("Subject")) or "(no subject)"
    to_hdr = ri._decode(msg.get("To")) or ""
    date_hdr = msg.get("Date") or ""
    try:
        received = email.utils.parsedate_to_datetime(date_hdr)
        received = received.astimezone().replace(tzinfo=None) if received else None
    except Exception:
        received = None
    body = ri._body_text(msg)
    attachments = ri._extract_attachments(msg)
    return {
        "uid": uid,
        "from": from_addr,
        "from_header": from_hdr,
        "to": to_hdr,
        "subject": subj,
        "received": received,
        "received_str": (received.strftime("%Y-%m-%d %H:%M")
                         if received else "(no date)"),
        "body": body,
        "attachments": attachments,
    }


def _stage_one(e: dict, dry_run: bool) -> dict:
    central_dir = _central_email_dir(e.get("received"))
    if central_dir is None:
        return {"uid": e["uid"], "status": "skipped",
                "reason": "NUCLEUS_CENTRAL_PATH not set"}
    received = e.get("received") or dt.datetime.now()
    hhmm = received.strftime("%H%M")
    sender_slug = _slug(e["from"])
    fname = f"{hhmm}_{sender_slug}__{e['uid']}.txt"
    target = central_dir / fname

    if target.exists():
        return {"uid": e["uid"], "status": "already_staged",
                "path": str(target)}

    lines: list[str] = []
    lines.append(f"From: {e['from_header'] or e['from']}")
    lines.append(f"To: {e['to']}")
    lines.append(f"Subject: {e['subject']}")
    lines.append(f"Received: {e['received_str']}")
    lines.append(f"UID: {e['uid']}")
    lines.append("")
    lines.append("Body:")
    body = (e.get("body") or "(empty)").strip()
    lines.append(body)
    atts = e.get("attachments") or []
    if atts:
        lines.append("")
        lines.append(f"Attachments ({len(atts)}):")
        for fname2, text in atts:
            lines.append(f"  --- attachment: {fname2} ---")
            for ln in (text or "(empty)").splitlines():
                lines.append(f"  {ln}")

    if dry_run:
        return {"uid": e["uid"], "status": "dry_run",
                "path": str(target),
                "size_chars": sum(len(s) for s in lines)}

    try:
        central_dir.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines), encoding="utf-8")
    except Exception as exc:
        return {"uid": e["uid"], "status": "error",
                "error": f"{type(exc).__name__}: {exc}"}
    return {"uid": e["uid"], "status": "staged",
            "path": str(target),
            "size_kb": target.stat().st_size / 1024}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", type=int, default=None,
                    help="Force-look-back N minutes ignoring the "
                         "checkpoint (manual one-shot). Default: use "
                         "the email_checkpoints UID.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan + show what would be staged, no writes.")
    args = ap.parse_args()

    key = _mailbox_key()
    if not key.startswith("|"):
        print(f"Stage email — mailbox key: {key}")
    else:
        print("REQ_IMAP_USER not set; aborting.", file=sys.stderr)
        return 2

    checkpoint = memory.get_email_checkpoint(key) or {}
    since_uid = None
    since_dt = None
    if args.since is not None:
        since_dt = dt.datetime.now() - dt.timedelta(minutes=args.since)
    else:
        last_uid_raw = checkpoint.get("last_uid")
        try:
            since_uid = int(last_uid_raw) if last_uid_raw else None
        except ValueError:
            since_uid = None

    print(f"  since_uid={since_uid}  since_dt={since_dt}")

    try:
        m = _imap_login_select()
    except Exception as e:
        print(f"IMAP error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    # UIDVALIDITY check (mirrors mail/requirements_inbox.py).
    # If Gmail/IMAP rebuilds the UID-space, our stored since_uid points
    # at the wrong message and we'd silently skip everything new. When
    # the server's UIDVALIDITY differs from what's in the checkpoint,
    # drop since_uid and fall back to the time window so the next run
    # re-ingests recent history. Always record the server's current
    # UIDVALIDITY back into the checkpoint.
    import re as _re
    mailbox = (os.getenv("REQ_IMAP_MAILBOX") or "INBOX").strip()
    server_uidvalidity: str | None = None
    try:
        typ, uidval_data = m.status(mailbox, "(UIDVALIDITY)")
        if typ == "OK" and uidval_data:
            m_ = _re.search(r"UIDVALIDITY (\d+)", uidval_data[0].decode())
            if m_:
                server_uidvalidity = m_.group(1)
    except Exception as e:
        print(f"  WARN: UIDVALIDITY probe failed ({e}); proceeding with "
              f"stored since_uid", file=sys.stderr)
    stored_uidvalidity = checkpoint.get("uidvalidity")
    if (server_uidvalidity and stored_uidvalidity
            and server_uidvalidity != stored_uidvalidity):
        print(f"  UIDVALIDITY changed ({stored_uidvalidity} -> "
              f"{server_uidvalidity}); resetting since_uid and falling "
              f"back to 24h time window")
        since_uid = None
        if since_dt is None:
            since_dt = dt.datetime.now() - dt.timedelta(hours=24)

    try:
        uids = _fetch_new_uids(m, since_uid, since_dt)
        print(f"  matched {len(uids)} new UID(s)")
        if not uids:
            return 0

        results: list[dict] = []
        max_uid_seen = since_uid or 0
        for uid in uids:
            try:
                e = _parse_message(m, uid)
            except Exception as exc:
                results.append({"uid": uid, "status": "parse_error",
                                "error": f"{type(exc).__name__}: {exc}"})
                continue
            if not e:
                continue
            # Per-message _stage_one guard. _stage_one writes to the
            # Samba share \\172.16.205.123\nucleus-central\... so an
            # unreachable share / disk error would previously kill the
            # loop AND skip the checkpoint update, causing next run to
            # re-fetch every email in the window (duplication).
            try:
                r = _stage_one(e, dry_run=args.dry_run)
            except Exception as exc:
                r = {"uid": uid, "status": "error",
                     "error": f"{type(exc).__name__}: {exc}"}
            results.append(r)
            try:
                max_uid_seen = max(max_uid_seen, int(uid))
            except ValueError:
                pass

        # Update checkpoint (unless dry-run). Store the SERVER's
        # current UIDVALIDITY -- if we just reset on a UIDVALIDITY
        # change, this is what makes the next run see the new value
        # as "stored" and not loop into another reset.
        # Guarded so a transient sqlite failure here doesn't drop a
        # traceback past the IMAP logout in finally:.
        if not args.dry_run and max_uid_seen > (since_uid or 0):
            try:
                memory.set_email_checkpoint(
                    mailbox_key=key,
                    uidvalidity=server_uidvalidity or checkpoint.get("uidvalidity"),
                    last_uid=str(max_uid_seen),
                )
                print(f"  updated checkpoint -> last_uid={max_uid_seen}")
            except Exception as exc:
                print(f"  ! checkpoint write failed: {type(exc).__name__}: "
                      f"{exc} -- next run may re-stage some emails",
                      file=sys.stderr)
    finally:
        try:
            m.logout()
        except Exception:
            pass

    staged = sum(1 for r in results if r["status"] == "staged")
    dry = sum(1 for r in results if r["status"] == "dry_run")
    errors = sum(1 for r in results if r["status"] in
                 ("error", "parse_error"))
    print(f"\nResult: staged={staged} dry_run={dry} errors={errors}")
    for r in results:
        if r["status"] in ("error", "parse_error"):
            print(f"  ! uid {r['uid']}: {r.get('error')}", file=sys.stderr)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
