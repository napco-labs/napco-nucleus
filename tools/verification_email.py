"""
NAPCO Nucleus — verification email DRAFT writer.

One MCP tool:

    draft_verification_email   Build an .eml draft of the client-facing
                               verification email (Requirements Verification
                               .docx attached) and write it to disk for
                               manual send.

Per the approved On-Demand workflow, NAPCO Nucleus does NOT send email
itself. For each draft it:

  1. writes a local .eml copy to data/requirements/drafts/<date>/  (audit trail)
  2. APPENDs the message to the user's IMAP Drafts folder so it appears
     in Outlook / Gmail web alongside other drafts, ready for manual send.

Env vars:
    SMTP_FROM            optional, From: header address (defaults to
                         REQ_IMAP_USER if available, else "nucleus@local")
    SMTP_FROM_NAME       optional display name (e.g. "NAPCO Nucleus")
    VERIFICATION_TO      default recipient (e.g. titucse@gmail.com)
    REQ_IMAP_HOST/PORT/USER/PASSWORD   used by the IMAP draft push
    IMAP_DRAFTS_FOLDER   optional override (auto-detected via \\Drafts flag)
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

_DEFAULT_BODY_SINGLE = (
    "Hi,\n\n"
    "Attached is the requirements summary I prepared from our recent "
    "discussions across email, Teams, and our last call.\n\n"
    "Please take a few minutes to review each item and let me know "
    "whether the interpretation matches what you intended. If anything "
    "needs adjusting (wording, scope, what's in or what's out), just "
    "reply with the changes inline and I will revise before the items "
    "move into the development backlog.\n\n"
    "Looking forward to your reply.\n\n"
    "Thanks"
)

_DEFAULT_BODY_BOTH = (
    "Hi,\n\n"
    "Two attachments for your review:\n\n"
    "  1. Requirements Verification - the distinct items I extracted "
    "from our recent discussions.\n"
    "  2. Pull Session - the raw source material those items were "
    "drawn from (email, Teams chat, Drive files, and the call "
    "transcript), bundled together so you can cross-check anything "
    "that looks off.\n\n"
    "Please take a few minutes to go through the verification list and "
    "let me know whether each item matches what you intended. If "
    "anything needs adjusting (wording, scope, what's in or what's "
    "out), just reply with the changes inline and I will revise before "
    "the items move into the development backlog.\n\n"
    "Looking forward to your reply.\n\n"
    "Thanks"
)


# ─── draft_verification_email ───────────────────────────────────────

@tool(
    "draft_verification_email",
    "Write an .eml draft of the client-facing verification email to "
    "data/requirements/drafts/<date>/. Attaches the Requirements "
    "Verification .docx; if `session_docx_path` is also provided, "
    "attaches the raw pull-session .docx as a SECOND attachment so the "
    "client can cross-check the verification items against their source "
    "material. NAPCO Nucleus does NOT send — the user opens the .eml in "
    "their mail client, reviews, and sends manually. Args: `docx_path` "
    "(REQUIRED — verification doc path), `session_docx_path` (optional "
    "— raw pull-session .docx for the second attachment), `to` "
    "(optional — defaults to VERIFICATION_TO env), `subject` (optional "
    "— defaults to 'Requirements Verification - <date>'), `body` "
    "(optional — auto-selected based on whether one or two attachments "
    "are passed). From: SMTP_FROM env. Returns {drafted, draft_path, "
    "to, from, subject, attachments} or {error}.",
    {"docx_path": str, "session_docx_path": str,
     "to": str, "subject": str, "body": str},
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

    # Optional second attachment: the raw pull-session doc
    session_path: Path | None = None
    raw_arg = (args.get("session_docx_path") or "").strip()
    if raw_arg:
        sp = Path(raw_arg)
        if not sp.is_absolute():
            sp = Path(__file__).parent.parent / raw_arg
        if not sp.is_file():
            return _text({"error": f"Session attachment not found: {sp}"})
        session_path = sp

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
    body_arg = (args.get("body") or "").strip()
    if body_arg:
        body = body_arg
    else:
        body = _DEFAULT_BODY_BOTH if session_path else _DEFAULT_BODY_SINGLE

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="napco-nucleus.local")
    msg.set_content(body)

    def _attach(path: Path, display_name: str | None = None) -> None:
        ctype, _enc = mimetypes.guess_type(str(path))
        if not ctype:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        with path.open("rb") as f:
            msg.add_attachment(
                f.read(), maintype=maintype, subtype=subtype,
                filename=display_name or path.name,
            )

    _attach(p)
    if session_path:
        _attach(session_path,
                display_name=f"Pull Session {_today_stamp()}.docx")

    dry_run = os.environ.get("NAPCO_NUCLEUS_DRY_RUN") == "1"

    attachment_names = [p.name] + (
        [f"Pull Session {_today_stamp()}.docx"] if session_path else []
    )

    if dry_run:
        memory.log_activity(
            task_name="requirement-collection:draft_verification",
            result="dry_run",
            technical_details={"to": to_addr, "from": from_addr, "subject": subject,
                               "attachments": attachment_names, "dry_run": True},
        )
        return _text({
            "drafted": False,
            "dry_run": True,
            "to": to_addr,
            "from": from_addr,
            "subject": subject,
            "attachments": attachment_names,
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
                               "attachments": attachment_names, "error": str(e)},
        )
        return _text({"error": f"{type(e).__name__}: {e}",
                      "to": to_addr, "from": from_addr})

    rel = draft_path.relative_to(Path(__file__).parent.parent).as_posix()

    # Push into the user's IMAP Drafts folder so it appears in Outlook /
    # Gmail web alongside other drafts. .eml on disk is kept as a local
    # copy + audit trail.
    imap_result = append_draft(msg)

    memory.log_activity(
        task_name="requirement-collection:draft_verification",
        result="drafted" + ("+imap" if imap_result["appended"] else ""),
        technical_details={"to": to_addr, "from": from_addr, "subject": subject,
                           "attachments": attachment_names, "draft_path": rel,
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
        "attachments": attachment_names,
        "next_step": next_step,
    })


TOOLS = [draft_verification_email_tool]
TOOL_NAMES = ["draft_verification_email"]
