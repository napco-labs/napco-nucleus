"""
NAPCO Nucleus — internal aggregation email DRAFT writer.

One MCP tool:

    draft_aggregation_email   Build an .eml draft of the records-inbox
                              email (raw aggregation .docx attached) and
                              write it to disk for manual send.

Sibling of `draft_verification_email` — same draft path, different
default recipient, different tone (no "please verify" wording — this
is an internal records artifact, not a client-facing review).

Per the approved On-Demand workflow, NAPCO Nucleus does NOT send email
itself. For each draft it:

  1. writes a local .eml copy to data/requirements/drafts/<date>/  (audit trail)
  2. APPENDs the message to the user's IMAP Drafts folder so it appears
     in Outlook / Gmail web alongside other drafts, ready for manual send.

Env vars:
    SMTP_FROM            optional, From: header address (defaults to
                         REQ_IMAP_USER if available, else "nucleus@local")
    SMTP_FROM_NAME       optional display name (e.g. "NAPCO Nucleus")
    AGGREGATION_TO       default recipient (defaults to hasan.celloscope@gmail.com)
    REQ_IMAP_HOST/PORT/USER/PASSWORD   used by the IMAP draft push
    IMAP_DRAFTS_FOLDER   optional override (auto-detected via \\Drafts flag)
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from claude_agent_sdk import tool

import memory
from tools._imap_drafts import append_draft

logger = logging.getLogger(__name__)


def _text(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


def _today_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now_hhmm() -> str:
    return datetime.now().strftime("%H%M")


def _safe_recipient(addr: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", addr).strip("-").lower() or "recipient"


_DRAFTS_ROOT = Path(__file__).parent.parent / "data" / "requirements" / "drafts"

# No baked-in default recipient: forces every deployment to set
# AGGREGATION_TO in .env (or pass `to` explicitly). The previous
# hardcoded personal address was a rollout footgun -- a new dev PC
# without that env set would draft to someone's personal Gmail.
_DEFAULT_RECIPIENT = ""

_DEFAULT_BODY = (
    "Hi,\n\n"
    "Attached is today's raw aggregation from the requirement-collection "
    "cycle (email, Teams chats, call transcripts, attachments) bundled "
    "into one document for the records.\n\n"
    "Logged for traceability. No action needed on your end.\n\n"
    "Thanks"
)


# ─── draft_aggregation_email ────────────────────────────────────────

@tool(
    "draft_aggregation_email",
    "Write an .eml draft of the internal records email (raw aggregation "
    ".docx attached) to data/requirements/drafts/<date>/. NAPCO Nucleus "
    "does NOT send — the user opens the .eml in their mail client and "
    "sends manually. Args: `docx_path` (REQUIRED — absolute or NN-"
    "relative path to the aggregation .docx), `to` (optional — defaults "
    "to AGGREGATION_TO env or hasan.celloscope@gmail.com), `subject` "
    "(optional — defaults to 'Requirement Collection - Raw Bundle "
    "<date>'), `body` (optional — defaults to a short internal-records "
    "message). From: SMTP_FROM env. Returns {drafted, draft_path, to, "
    "from, subject, attachment} or {error}.",
    {"docx_path": str, "to": str, "subject": str, "body": str},
)
async def draft_aggregation_email_tool(args):
    docx_path = (args.get("docx_path") or "").strip()
    if not docx_path:
        return _text({"error": "docx_path is required"})

    p = Path(docx_path)
    if not p.is_absolute():
        p = Path(__file__).parent.parent / docx_path
    if not p.is_file():
        return _text({"error": f"Attachment not found: {p}"})

    to_addr = (
        args.get("to")
        or os.environ.get("AGGREGATION_TO")
        or _DEFAULT_RECIPIENT
    ).strip()
    if not to_addr:
        return _text({
            "error": "no recipient: pass `to` arg or set AGGREGATION_TO "
                     "in .env. There is no built-in default to prevent "
                     "drafts being misrouted to a personal address."
        })

    from_addr = (
        os.environ.get("SMTP_FROM")
        or os.environ.get("REQ_IMAP_USER")
        or "nucleus@local"
    ).strip()
    from_name = (os.environ.get("SMTP_FROM_NAME") or "NAPCO Nucleus").strip()
    sender = f"{from_name} <{from_addr}>" if from_name else from_addr

    subject = (args.get("subject") or "").strip()
    if not subject:
        subject = f"Requirement Collection - Raw Bundle {_today_stamp()}"
    body = (args.get("body") or "").strip() or _DEFAULT_BODY

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="napco-nucleus.local")
    msg.set_content(body)

    ctype, _ = mimetypes.guess_type(str(p))
    if not ctype:
        ctype = "application/octet-stream"
    maintype, subtype = ctype.split("/", 1)
    with p.open("rb") as f:
        msg.add_attachment(
            f.read(), maintype=maintype, subtype=subtype, filename=p.name
        )

    dry_run = os.environ.get("NAPCO_NUCLEUS_DRY_RUN") == "1"

    if dry_run:
        memory.log_activity(
            task_name="requirement-collection:draft_aggregation",
            result="dry_run",
            technical_details={"to": to_addr, "from": from_addr, "subject": subject,
                               "attachment": p.name, "dry_run": True},
        )
        return _text({
            "drafted": False,
            "dry_run": True,
            "to": to_addr,
            "from": from_addr,
            "subject": subject,
            "attachment": p.name,
        })

    day_dir = _DRAFTS_ROOT / _today_stamp()
    day_dir.mkdir(parents=True, exist_ok=True)
    draft_name = f"aggregation_{_now_hhmm()}_{_safe_recipient(to_addr)}.eml"
    draft_path = day_dir / draft_name

    try:
        with draft_path.open("wb") as f:
            f.write(bytes(msg))
    except Exception as e:
        logger.exception("draft_aggregation_email failed to write .eml")
        memory.log_activity(
            task_name="requirement-collection:draft_aggregation",
            result=f"error:{type(e).__name__}",
            technical_details={"to": to_addr, "from": from_addr, "subject": subject,
                               "attachment": p.name, "error": str(e)},
        )
        return _text({"error": f"{type(e).__name__}: {e}",
                      "to": to_addr, "from": from_addr})

    rel = draft_path.relative_to(Path(__file__).parent.parent).as_posix()

    # Push into the user's IMAP Drafts folder so it appears in Outlook /
    # Gmail web alongside other drafts. .eml on disk is kept as a local
    # copy + audit trail.
    imap_result = append_draft(msg)

    memory.log_activity(
        task_name="requirement-collection:draft_aggregation",
        result="drafted" + ("+imap" if imap_result["appended"] else ""),
        technical_details={"to": to_addr, "from": from_addr, "subject": subject,
                           "attachment": p.name, "draft_path": rel,
                           "imap_appended": imap_result["appended"],
                           "imap_folder": imap_result["folder"],
                           "imap_error": imap_result["error"]},
    )

    if imap_result["appended"]:
        next_step = (f"Open '{imap_result['folder']}' in your mail client — "
                     f"the draft is waiting there for review and send.")
    else:
        next_step = (f"IMAP push failed ({imap_result['error']}). "
                     f"Open the .eml file directly: {draft_path}")

    return _text({
        "drafted": True,
        "draft_path": rel,
        "absolute_path": str(draft_path),
        "imap_appended": imap_result["appended"],
        "drafts_folder": imap_result["folder"],
        "imap_error": imap_result["error"],
        "to": to_addr,
        "from": from_addr,
        "subject": subject,
        "attachment": p.name,
        "next_step": next_step,
    })


TOOLS = [draft_aggregation_email_tool]
TOOL_NAMES = ["draft_aggregation_email"]
