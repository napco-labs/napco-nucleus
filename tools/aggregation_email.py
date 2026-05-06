"""
NAPCO Nucleus — internal aggregation email sender.

One MCP tool:

    send_aggregation_email   Email the raw aggregation Word document to
                             the internal records inbox so we have a copy
                             of every collection cycle's source material.

Sibling of `send_verification_email` — same SMTP path, different default
recipient, different tone (no "please verify" wording — this is an
internal records artifact, not a client-facing review).

Env vars:
    SMTP_HOST            default smtp.gmail.com
    SMTP_PORT            default 587
    SMTP_USER            required (auth user)
    SMTP_PASSWORD        required (Gmail App Password)
    SMTP_FROM            optional, defaults to SMTP_USER
    SMTP_FROM_NAME       optional display name (e.g. "NAPCO Nucleus")
    AGGREGATION_TO       default recipient (defaults to hasan.celloscope@gmail.com)
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from claude_agent_sdk import tool

import memory

logger = logging.getLogger(__name__)


def _text(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


def _today_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d")


_DEFAULT_RECIPIENT = "hasan.celloscope@gmail.com"

_DEFAULT_BODY = (
    "Internal records — raw aggregation of every source ingested in the "
    "latest requirement-collection cycle (email, Teams chat, call "
    "transcripts, attachments). Attached for traceability. No action "
    "required.\n"
)


# ─── send_aggregation_email ─────────────────────────────────────────

@tool(
    "send_aggregation_email",
    "Email the raw aggregation Word doc to the internal records inbox. "
    "Args: `docx_path` (REQUIRED — absolute or NN-relative path to the "
    "aggregation .docx), `to` (optional — defaults to AGGREGATION_TO env "
    "or hasan.celloscope@gmail.com), `subject` (optional — defaults to "
    "'Requirement Collection - Raw Bundle <date>'), `body` (optional — "
    "defaults to a short internal-records message). From: SMTP_FROM env. "
    "Honors NAPCO_NUCLEUS_DRY_RUN. Returns {sent, to, from, subject, "
    "attachment} or {error}.",
    {"docx_path": str, "to": str, "subject": str, "body": str},
)
async def send_aggregation_email_tool(args):
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

    host = (os.environ.get("SMTP_HOST") or "smtp.gmail.com").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = (os.environ.get("SMTP_USER") or "").strip()
    password = os.environ.get("SMTP_PASSWORD") or ""
    if not user or not password:
        return _text({"error": "SMTP_USER and SMTP_PASSWORD must be set"})

    from_addr = (os.environ.get("SMTP_FROM") or user).strip()
    from_name = (os.environ.get("SMTP_FROM_NAME") or "NAPCO Nucleus").strip()
    sender = f"{from_name} <{from_addr}>" if from_name else from_addr

    subject = (args.get("subject") or "").strip()
    if not subject:
        subject = f"Requirement Collection - Raw Bundle {_today_stamp()}"
    body = (args.get("body") or "").strip() or _DEFAULT_BODY

    dry_run = os.environ.get("NAPCO_NUCLEUS_DRY_RUN") == "1"

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    ctype, _ = mimetypes.guess_type(str(p))
    if not ctype:
        ctype = "application/octet-stream"
    maintype, subtype = ctype.split("/", 1)
    with p.open("rb") as f:
        msg.add_attachment(
            f.read(), maintype=maintype, subtype=subtype, filename=p.name
        )

    if dry_run:
        memory.log_activity(
            task_name="requirement-collection:send_aggregation",
            result="dry_run",
            technical_details={"to": to_addr, "from": from_addr, "subject": subject,
                               "attachment": p.name, "dry_run": True},
        )
        return _text({
            "sent": False,
            "dry_run": True,
            "to": to_addr,
            "from": from_addr,
            "subject": subject,
            "attachment": p.name,
        })

    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(user, password)
            s.send_message(msg)
    except Exception as e:
        logger.exception("send_aggregation_email failed")
        memory.log_activity(
            task_name="requirement-collection:send_aggregation",
            result=f"error:{type(e).__name__}",
            technical_details={"to": to_addr, "from": from_addr, "subject": subject,
                               "attachment": p.name, "error": str(e)},
        )
        return _text({"error": f"{type(e).__name__}: {e}",
                      "to": to_addr, "from": from_addr})

    memory.log_activity(
        task_name="requirement-collection:send_aggregation",
        result="sent",
        technical_details={"to": to_addr, "from": from_addr, "subject": subject,
                           "attachment": p.name},
    )
    return _text({
        "sent": True,
        "to": to_addr,
        "from": from_addr,
        "subject": subject,
        "attachment": p.name,
    })


TOOLS = [send_aggregation_email_tool]
TOOL_NAMES = ["send_aggregation_email"]
