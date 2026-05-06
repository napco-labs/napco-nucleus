"""
NAPCO Nucleus — verification email sender.

One MCP tool:

    send_verification_email   Email the Requirements Verification .docx to
                              the client for review.

Standalone Gmail SMTP path — does NOT share STATE with the test-report
email tool. Honors NAPCO_NUCLEUS_DRY_RUN (no actual send).

Env vars:
    SMTP_HOST            default smtp.gmail.com
    SMTP_PORT            default 587
    SMTP_USER            required (auth user)
    SMTP_PASSWORD        required (Gmail App Password)
    SMTP_FROM            optional, defaults to SMTP_USER
    SMTP_FROM_NAME       optional display name (e.g. "NAPCO Nucleus")
    VERIFICATION_TO      default recipient (e.g. titucse@gmail.com)
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


_DEFAULT_BODY = (
    "Hi,\n\n"
    "Please find attached the requirements interpretation summary based on "
    "our recent discussions (email, Teams messages, and call). Please review "
    "and reply to this email confirming the interpretation, or send any "
    "corrections inline. Once confirmed, each item will be filed for "
    "development.\n\n"
    "Thanks."
)


# ─── send_verification_email ────────────────────────────────────────

@tool(
    "send_verification_email",
    "Send the Requirements Verification .docx to the client. Args: "
    "`docx_path` (REQUIRED — absolute or NN-relative path to the verification "
    "doc to attach), `to` (optional — defaults to VERIFICATION_TO env), "
    "`subject` (optional — defaults to 'Requirements Verification - <date>'), "
    "`body` (optional — defaults to a short review-and-confirm message). "
    "From: SMTP_FROM env (defaults to SMTP_USER). Returns {sent, to, "
    "from, subject, attachment} or {error}. Honors NAPCO_NUCLEUS_DRY_RUN.",
    {"docx_path": str, "to": str, "subject": str, "body": str},
)
async def send_verification_email_tool(args):
    docx_path = (args.get("docx_path") or "").strip()
    if not docx_path:
        return _text({"error": "docx_path is required"})

    p = Path(docx_path)
    if not p.is_absolute():
        # interpret as NN-relative
        p = Path(__file__).parent.parent / docx_path
    if not p.is_file():
        return _text({"error": f"Attachment not found: {p}"})

    to_addr = (args.get("to") or os.environ.get("VERIFICATION_TO") or "").strip()
    if not to_addr:
        return _text({"error": "Recipient missing — set VERIFICATION_TO env or pass `to`."})

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
        subject = f"Requirements Verification - {_today_stamp()}"
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
            task_name="requirement-collection:send_verification",
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
        logger.exception("send_verification_email failed")
        memory.log_activity(
            task_name="requirement-collection:send_verification",
            result=f"error:{type(e).__name__}",
            technical_details={"to": to_addr, "from": from_addr, "subject": subject,
                               "attachment": p.name, "error": str(e)},
        )
        return _text({"error": f"{type(e).__name__}: {e}",
                      "to": to_addr, "from": from_addr})

    memory.log_activity(
        task_name="requirement-collection:send_verification",
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


TOOLS = [send_verification_email_tool]
TOOL_NAMES = ["send_verification_email"]
