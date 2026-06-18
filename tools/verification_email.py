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
    VERIFICATION_CC      optional default Cc list (comma-separated)
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
    # ensure_ascii=False so Bangla reaches the agent as real UTF-8, not
    # \uXXXX escapes it can't decode in-sandbox (see requirements.py _text).
    return {"content": [{"type": "text",
                         "text": json.dumps(payload, ensure_ascii=False,
                                            default=str)}]}


def _today_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now_hhmm() -> str:
    return datetime.now().strftime("%H%M")


def _safe_recipient(addr: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", addr).strip("-").lower() or "recipient"


_DRAFTS_ROOT = Path(__file__).parent.parent / "data" / "requirements" / "drafts"
_TEMPLATES_DIR = Path(__file__).parent.parent / "data" / "templates"

# Built-in fallbacks when no template files exist on disk. These match
# the historical behaviour exactly so removing all template files
# leaves output unchanged.

_FALLBACK_BODY_SINGLE = (
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

_FALLBACK_BODY_BOTH = (
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


_TEMPLATE_INTRO_SINGLE = (
    "Attached is the requirements summary I prepared from our recent "
    "discussions across email, Teams, and our last call."
)

_TEMPLATE_INTRO_BOTH = (
    "Two attachments for your review:\n\n"
    "  1. Requirements Verification - the distinct items I extracted "
    "from our recent discussions.\n"
    "  2. Pull Session - the raw source material those items were "
    "drawn from (email, Teams chat, Drive files, and the call "
    "transcript), bundled together so you can cross-check anything "
    "that looks off."
)


_TEMPLATE_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _slugify_client(name: str) -> str:
    s = _TEMPLATE_SLUG_RE.sub("-", (name or "").strip()).strip("-")
    return s[:60].lower() or "default"


def _template_path_for(client_name: str | None) -> Path | None:
    """Resolve a per-client template, falling back to default. Returns
    the path that exists on disk, or None if no template files are
    present (caller uses the hard-coded fallback)."""
    candidates: list[Path] = []
    if client_name:
        slug = _slugify_client(client_name)
        candidates.append(_TEMPLATES_DIR / f"draft_{slug}.md")
        # AEL-internal stakeholders share one informal template
        if slug in {"assaduz-zaman", "atikur-zaman", "ahsan-habib",
                    "isruk-hasan", "titu"}:
            candidates.append(_TEMPLATES_DIR / "draft_internal.md")
    candidates.append(_TEMPLATES_DIR / "draft_default.md")
    for p in candidates:
        if p.is_file():
            return p
    return None


def _load_body(client_name: str | None, both_attachments: bool) -> str:
    """Compose the email body. Per-client template if present; built-in
    fallback otherwise. Supports the placeholders:

      {client_name}        — canonical client name as passed
      {greeting_name}      — short addressee (first name when known)
      {intro_one_or_both}  — the right intro block based on attachment count
      {greeting}           — pre-baked "Hi {greeting_name}," line
    """
    tpl = _template_path_for(client_name)
    if not tpl:
        return _FALLBACK_BODY_BOTH if both_attachments else _FALLBACK_BODY_SINGLE
    try:
        raw = tpl.read_text(encoding="utf-8")
    except Exception:
        return _FALLBACK_BODY_BOTH if both_attachments else _FALLBACK_BODY_SINGLE

    greeting_name = _greeting_name(client_name)
    intro = _TEMPLATE_INTRO_BOTH if both_attachments else _TEMPLATE_INTRO_SINGLE
    greeting = f"Hi {greeting_name}," if greeting_name else "Hi,"

    try:
        return raw.format(
            client_name=(client_name or ""),
            greeting_name=greeting_name,
            intro_one_or_both=intro,
            greeting=greeting,
        ).strip() + "\n"
    except (KeyError, IndexError):
        # Template referenced a placeholder we don't expose — fall back
        # silently rather than mangling the output.
        return (_FALLBACK_BODY_BOTH if both_attachments
                else _FALLBACK_BODY_SINGLE)


def _greeting_name(client_name: str | None) -> str:
    """Best-effort first-name greeting. Returns '' when ambiguous."""
    if not client_name:
        return ""
    name = client_name.strip()
    # Group identifiers don't take a first name greeting
    if name.lower() in {"napco security", "team"}:
        return "team"
    # Split on space; take first token if it looks like a personal name
    parts = name.split()
    if parts and parts[0][0:1].isupper():
        return parts[0]
    return ""


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
    "(optional — defaults to VERIFICATION_TO env), `cc` (optional — "
    "comma-separated; defaults to VERIFICATION_CC env), `subject` "
    "(optional — defaults to 'Requirements Verification - <date>'), "
    "`body` (optional — when omitted, looks up a per-client template "
    "from data/templates/draft_<slug>.md based on `client_name`, "
    "falling back to draft_default.md, then a hard-coded body), "
    "`client_name` (optional — drives template selection; pass the "
    "canonical client name from step 1.5). From: SMTP_FROM env. "
    "Returns {drafted, draft_path, to, cc, from, subject, attachments, "
    "template} or {error}.",
    {"docx_path": str, "session_docx_path": str,
     "to": str, "cc": str, "subject": str, "body": str,
     "client_name": str},
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

    cc_raw = (args.get("cc") or os.environ.get("VERIFICATION_CC") or "").strip()
    cc_list = [a.strip() for a in cc_raw.split(",") if a.strip()] if cc_raw else []
    cc_addr = ", ".join(cc_list)

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
    client_name = (args.get("client_name") or "").strip() or None
    tpl_used = "explicit-body"
    if body_arg:
        body = body_arg
    else:
        body = _load_body(client_name, both_attachments=bool(session_path))
        tpl_path = _template_path_for(client_name)
        tpl_used = (tpl_path.name if tpl_path else "fallback-builtin")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_addr
    if cc_addr:
        msg["Cc"] = cc_addr
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
            technical_details={"to": to_addr, "cc": cc_addr, "from": from_addr,
                               "subject": subject,
                               "attachments": attachment_names, "dry_run": True},
        )
        return _text({
            "drafted": False,
            "dry_run": True,
            "to": to_addr,
            "cc": cc_addr,
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
            technical_details={"to": to_addr, "cc": cc_addr, "from": from_addr,
                               "subject": subject,
                               "attachments": attachment_names, "error": str(e)},
        )
        return _text({"error": f"{type(e).__name__}: {e}",
                      "to": to_addr, "cc": cc_addr, "from": from_addr})

    rel = draft_path.relative_to(Path(__file__).parent.parent).as_posix()

    # Push into the user's IMAP Drafts folder so it appears in Outlook /
    # Gmail web alongside other drafts. .eml on disk is kept as a local
    # copy + audit trail.
    imap_result = append_draft(msg)

    memory.log_activity(
        task_name="requirement-collection:draft_verification",
        result="drafted" + ("+imap" if imap_result["appended"] else ""),
        technical_details={"to": to_addr, "cc": cc_addr, "from": from_addr,
                           "subject": subject,
                           "attachments": attachment_names, "draft_path": rel,
                           "client_name": client_name,
                           "template": tpl_used,
                           "imap_appended": imap_result["appended"],
                           "imap_folder": imap_result["folder"],
                           "imap_replaced": imap_result.get("replaced", 0),
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
        "imap_replaced": imap_result.get("replaced", 0),
        "imap_error": imap_result["error"],
        "to": to_addr,
        "cc": cc_addr,
        "from": from_addr,
        "subject": subject,
        "attachments": attachment_names,
        "client_name": client_name,
        "template": tpl_used,
        "next_step": next_step,
    })


TOOLS = [draft_verification_email_tool]
TOOL_NAMES = ["draft_verification_email"]
