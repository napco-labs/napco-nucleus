"""
NAPCO Nucleus — verification email DRAFT writer.

One MCP tool:

    draft_verification_email   Build an .eml draft of the client-facing
                               verification email (Requirements Verification
                               .docx attached) and write it to disk for
                               manual send.

Per the approved On-Demand workflow, NAPCO Nucleus does NOT send email
itself. It produces an .eml draft on disk; the user opens that file in
their own mail client, reviews, and sends it manually.

Output:
    data/requirements/drafts/<YYYY-MM-DD>/verification_<HHMM>_<recipient>.eml

Env vars:
    SMTP_FROM            optional, From: header address (defaults to
                         REQ_IMAP_USER if available, else "nucleus@local")
    SMTP_FROM_NAME       optional display name (e.g. "NAPCO Nucleus")
    VERIFICATION_TO      default recipient (e.g. titucse@gmail.com)
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from claude_agent_sdk import tool

import memory

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

_DEFAULT_BODY = (
    "Hi,\n\n"
    "Please find attached the requirements interpretation summary based on "
    "our recent discussions (email, Teams messages, and call). Please review "
    "and reply to this email confirming the interpretation, or send any "
    "corrections inline. Once confirmed, each item will be filed for "
    "development.\n\n"
    "Thanks."
)


# ─── draft_verification_email ───────────────────────────────────────

@tool(
    "draft_verification_email",
    "Write an .eml draft of the client-facing verification email "
    "(Requirements Verification .docx attached) to data/requirements/"
    "drafts/<date>/. NAPCO Nucleus does NOT send — the user opens the "
    ".eml in their mail client, reviews, and sends manually. Args: "
    "`docx_path` (REQUIRED — absolute or NN-relative path to the "
    "verification doc to attach), `to` (optional — defaults to "
    "VERIFICATION_TO env), `subject` (optional — defaults to "
    "'Requirements Verification - <date>'), `body` (optional — defaults "
    "to a short review-and-confirm message). From: SMTP_FROM env. "
    "Returns {drafted, draft_path, to, from, subject, attachment} or "
    "{error}.",
    {"docx_path": str, "to": str, "subject": str, "body": str},
)
async def draft_verification_email_tool(args):
    docx_path = (args.get("docx_path") or "").strip()
    if not docx_path:
        return _text({"error": "docx_path is required"})

    p = Path(docx_path)
    if not p.is_absolute():
        p = Path(__file__).parent.parent / docx_path
    if not p.is_file():
        return _text({"error": f"Attachment not found: {p}"})

    to_addr = (args.get("to") or os.environ.get("VERIFICATION_TO") or "").strip()
    if not to_addr:
        return _text({"error": "Recipient missing — set VERIFICATION_TO env or pass `to`."})

    from_addr = (
        os.environ.get("SMTP_FROM")
        or os.environ.get("REQ_IMAP_USER")
        or "nucleus@local"
    ).strip()
    from_name = (os.environ.get("SMTP_FROM_NAME") or "NAPCO Nucleus").strip()
    sender = f"{from_name} <{from_addr}>" if from_name else from_addr

    subject = (args.get("subject") or "").strip()
    if not subject:
        subject = f"Requirements Verification - {_today_stamp()}"
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
            task_name="requirement-collection:draft_verification",
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
    draft_name = f"verification_{_now_hhmm()}_{_safe_recipient(to_addr)}.eml"
    draft_path = day_dir / draft_name

    try:
        with draft_path.open("wb") as f:
            f.write(bytes(msg))
    except Exception as e:
        logger.exception("draft_verification_email failed to write .eml")
        memory.log_activity(
            task_name="requirement-collection:draft_verification",
            result=f"error:{type(e).__name__}",
            technical_details={"to": to_addr, "from": from_addr, "subject": subject,
                               "attachment": p.name, "error": str(e)},
        )
        return _text({"error": f"{type(e).__name__}: {e}",
                      "to": to_addr, "from": from_addr})

    rel = draft_path.relative_to(Path(__file__).parent.parent).as_posix()
    memory.log_activity(
        task_name="requirement-collection:draft_verification",
        result="drafted",
        technical_details={"to": to_addr, "from": from_addr, "subject": subject,
                           "attachment": p.name, "draft_path": rel},
    )
    return _text({
        "drafted": True,
        "draft_path": rel,
        "absolute_path": str(draft_path),
        "to": to_addr,
        "from": from_addr,
        "subject": subject,
        "attachment": p.name,
        "next_step": "Open the .eml in your mail client, review, and send manually.",
    })


TOOLS = [draft_verification_email_tool]
TOOL_NAMES = ["draft_verification_email"]
