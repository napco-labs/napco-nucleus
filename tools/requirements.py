"""
NAPCO Nucleus — Requirement Management tools.

Four MCP tools for the Project Management dimension:

    poll_requirement_emails  IMAP poll from allowlisted senders
    ingest_drive_files       Google Drive → Whisper / pypdf → inbox files
    read_requirement_inbox   Read all raw .txt files Claude will split
    publish_tasks_to_gitlab  Create GitLab issues (dedup against open +
                             SQLite requirements_seen)

Each tool is a thin wrapper around the deterministic module that does
the real work (requirements_inbox / drive_ingester / gitlab_client).
Claude-side reasoning happens in the prompts that call these tools.

Memory side-effects (best-effort, never block the primary flow):
    - Every call logs one activity_logs row
    - publish_tasks_to_gitlab also writes to requirements_seen on
      success so future runs can dedup via search_requirements
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from claude_agent_sdk import tool

import memory

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent.parent
_REQ_INBOX_ROOT = _HERE / "data" / "requirements" / "inbox"


def _text(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


# ─── poll_requirement_emails ────────────────────────────────────────

@tool(
    "poll_requirement_emails",
    "Fetch new requirement emails from the configured IMAP mailbox and "
    "save each one under data/requirements/inbox/email/ with a short "
    "header (source, from, received, subject) followed by the body. "
    "Filters by REQ_SENDER_ALLOWLIST — only emails from allowlisted "
    "senders are kept. Idempotent via UIDVALIDITY + since-UID "
    "checkpoint. Call this FIRST when the user asks you to process "
    "requirements.",
    {"dry_run": bool},
)
async def poll_requirement_emails_tool(args):
    import requirements_inbox  # lazy — keeps imaplib out of cold-start path
    dry_run = bool(args.get("dry_run", False))
    try:
        result = requirements_inbox.poll_requirement_inbox(dry_run=dry_run)
    except Exception as e:
        logger.exception("poll_requirement_emails failed")
        memory.log_activity(
            task_name="requirement-management:poll_email",
            result=f"error:{type(e).__name__}",
            technical_details={"error": str(e)},
        )
        return _text({"error": str(e), "ingested": 0})

    memory.log_activity(
        task_name="requirement-management:poll_email",
        result=f"ingested:{result.get('ingested', 0)}",
        technical_details={k: v for k, v in result.items() if k != "files"},
    )
    return _text(result)


# ─── ingest_drive_files ─────────────────────────────────────────────

@tool(
    "ingest_drive_files",
    "Download and ingest new files from the configured Google Drive "
    "folder. Audio/video files are transcribed via Groq Whisper and "
    "written to data/requirements/inbox/meetings/. PDFs are extracted "
    "via pypdf and written to data/requirements/inbox/documents/. "
    "Idempotent — a Drive file ID is never re-processed. Call this "
    "alongside poll_requirement_emails during the Requirement "
    "Management loop so both sources get captured before read_inbox.",
    {"dry_run": bool},
)
async def ingest_drive_files_tool(args):
    import drive_ingester  # lazy — avoids googleapiclient import on cold start
    dry_run = bool(args.get("dry_run", False))
    try:
        result = drive_ingester.process_new_drive_files(dry_run=dry_run)
    except Exception as e:
        logger.exception("ingest_drive_files failed")
        memory.log_activity(
            task_name="requirement-management:ingest_drive",
            result=f"error:{type(e).__name__}",
            technical_details={"error": str(e)},
        )
        return _text({"error": str(e), "processed": 0})

    memory.log_activity(
        task_name="requirement-management:ingest_drive",
        result=f"processed:{result.get('processed', 0)}",
        technical_details={k: v for k, v in result.items() if k != "files"},
    )
    return _text(result)


# ─── read_requirement_inbox ────────────────────────────────────────

@tool(
    "read_requirement_inbox",
    "Return the contents of every .txt file in data/requirements/inbox/ "
    "(email, meetings, chat, documents sub-folders). Use AFTER "
    "poll_requirement_emails + ingest_drive_files so you can read all "
    "pending raw requirement text in one call, then split it into "
    "~3-hour tasks and call publish_tasks_to_gitlab. Optional source= "
    "filter: email / meetings / chat / documents — defaults to all.",
    {"source": str},
)
async def read_requirement_inbox_tool(args):
    source = (args.get("source") or "").strip().lower()
    valid = {"email", "meetings", "chat", "documents"}
    sources = [source] if source in valid else sorted(valid)

    files = []
    for sub in sources:
        sub_dir = _REQ_INBOX_ROOT / sub
        if not sub_dir.is_dir():
            continue
        for name in sorted(os.listdir(sub_dir)):
            if name.startswith(".") or not name.endswith(".txt"):
                continue
            path = sub_dir / name
            try:
                content = path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"read {path} failed: {e}")
                continue
            files.append({
                "source": sub,
                "filename": name,
                "rel_path": str(path.relative_to(_HERE)).replace("\\", "/"),
                "chars": len(content),
                "content": content,
            })

    return _text({
        "sources_scanned": sources,
        "file_count": len(files),
        "files": files,
    })


# ─── publish_tasks_to_gitlab ───────────────────────────────────────

def _source_bucket(rel_path: str) -> str:
    """Infer the source bucket from a rel_path for memory recording."""
    p = (rel_path or "").replace("\\", "/")
    for sub in ("meetings", "documents", "chat", "email"):
        if f"/inbox/{sub}/" in p or p.startswith(f"data/requirements/inbox/{sub}/"):
            return sub
    return "email"


@tool(
    "publish_tasks_to_gitlab",
    "Create one GitLab issue per task in the configured project. Each "
    "task must be a dict with keys: title (required, <70 chars, "
    "imperative), description (required — why + context), "
    "acceptance_criteria (optional list of strings, appended as a "
    "bulleted section), estimate_hours (default 3), source_ref "
    "(optional — rel_path of the source file), labels (optional list, "
    "merged with GITLAB_DEFAULT_LABELS). Dedup in two layers: (1) "
    "skips any task whose title already exists as an open issue in "
    "GitLab; (2) skips any task whose normalized title is already in "
    "memory.requirements_seen with a prior issue URL. Writes each "
    "successful task to requirements_seen so future runs can fuzzy-"
    "match it. Honors NAPCO_NUCLEUS_DRY_RUN.",
    {"tasks": list},
)
async def publish_tasks_to_gitlab_tool(args):
    import gitlab_client  # lazy

    tasks = args.get("tasks") or []
    if not isinstance(tasks, list) or not tasks:
        return _text({"error": "tasks must be a non-empty list"})

    dry_run = os.environ.get("NAPCO_NUCLEUS_DRY_RUN") == "1"

    # 1. Title-based dedupe against currently-open GitLab issues.
    try:
        open_titles = {t.strip().lower()
                       for t in gitlab_client.list_open_issue_titles()}
    except gitlab_client.GitLabConfigError as e:
        memory.log_activity(
            task_name="requirement-management:publish_gitlab",
            result="error:config_missing",
            technical_details={"error": str(e)},
        )
        return _text({"error": f"GitLab config missing: {e}",
                      "created": [], "skipped_existing": [], "failed": []})
    except Exception as e:
        logger.exception("list_open_issue_titles failed")
        memory.log_activity(
            task_name="requirement-management:publish_gitlab",
            result=f"error:{type(e).__name__}",
            technical_details={"error": str(e)},
        )
        return _text({"error": f"GitLab list failed: {e}",
                      "created": [], "skipped_existing": [], "failed": []})

    created, skipped, failed = [], [], []

    for t in tasks:
        if not isinstance(t, dict):
            failed.append({"task": t, "error": "not a dict"})
            continue
        title = (t.get("title") or "").strip()
        description = (t.get("description") or "").strip()
        if not title or not description:
            failed.append({"task": t, "error": "title and description required"})
            continue

        # Exact-match dedupe against GitLab open issues.
        if title.lower() in open_titles:
            skipped.append({"title": title, "reason": "already open in GitLab"})
            continue

        # Fuzzy-match dedupe against memory (catches spelling variants
        # even if the original GitLab issue is now closed).
        prior = memory.search_requirements(title, limit=1)
        if prior and prior[0].get("gitlab_issue_iid"):
            skipped.append({
                "title": title,
                "reason": "already seen in memory",
                "prior_issue_url": prior[0].get("gitlab_issue_url"),
            })
            continue

        # Compose body: description + acceptance criteria + estimate + source.
        body_parts = [description]
        crit = t.get("acceptance_criteria") or []
        if isinstance(crit, list) and crit:
            body_parts.append("\n**Acceptance criteria**")
            for c in crit:
                body_parts.append(f"- {c}")
        est = t.get("estimate_hours") or 3
        body_parts.append(f"\n**Estimate:** ~{est} hours")
        src = (t.get("source_ref") or "").strip()
        if src:
            body_parts.append(f"\n*Source: `{src}`*")
        full_body = "\n".join(body_parts)
        labels = t.get("labels") if isinstance(t.get("labels"), list) else []
        # issue_type controls GitLab work-item subtype: "task" or "issue".
        # Defaults to None → GitLab creates a regular Issue work item.
        issue_type = t.get("issue_type") if isinstance(t.get("issue_type"), str) else None
        source_bucket = _source_bucket(src)

        if dry_run:
            created.append({"title": title, "iid": "DRY-RUN",
                            "web_url": None, "dry_run": True})
            memory.remember_requirement(
                title=title, source=source_bucket, source_ref=src,
                summary=description[:240],
            )
            open_titles.add(title.lower())
            continue

        try:
            issue = gitlab_client.create_issue(
                title=title, description=full_body, labels=labels,
                issue_type=issue_type,
            )
            iid = issue.get("iid")
            url = issue.get("web_url")
            created.append({"title": title, "iid": iid, "web_url": url})
            memory.remember_requirement(
                title=title, source=source_bucket, source_ref=src,
                summary=description[:240],
                gitlab_issue_iid=iid, gitlab_issue_url=url,
            )
            open_titles.add(title.lower())
        except Exception as e:
            logger.exception(f"create_issue failed for {title!r}")
            failed.append({"title": title, "error": str(e)})

    memory.log_activity(
        task_name="requirement-management:publish_gitlab",
        result=f"created={len(created)} skipped={len(skipped)} failed={len(failed)}",
        technical_details={
            "created_titles": [c["title"] for c in created],
            "skipped_count_by_reason": {
                "open_in_gitlab": sum(1 for s in skipped
                                      if s.get("reason") == "already open in GitLab"),
                "seen_in_memory": sum(1 for s in skipped
                                      if s.get("reason") == "already seen in memory"),
            },
            "dry_run": dry_run,
        },
    )

    return _text({
        "created": created,
        "skipped_existing": skipped,
        "failed": failed,
        "dry_run": dry_run,
    })


TOOLS = [
    poll_requirement_emails_tool,
    ingest_drive_files_tool,
    read_requirement_inbox_tool,
    publish_tasks_to_gitlab_tool,
]

TOOL_NAMES = [
    "poll_requirement_emails",
    "ingest_drive_files",
    "read_requirement_inbox",
    "publish_tasks_to_gitlab",
]
