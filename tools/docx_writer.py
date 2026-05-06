"""
NAPCO Nucleus — Word document writers for requirement collection.

Two MCP tools:

    write_aggregation_docx     Raw text per channel (email/chat/meeting/document)
                               for traceability — what came in.
    write_verification_docx    Identified requirements as 2-5 paragraph summaries
                               for client verification — what we think they said.

Both write into data/requirements/ with a date stamp. The agent passes
already-prepared structured input — no LLM reasoning happens here.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import tool

import memory

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent.parent
_OUT_DIR = _HERE / "data" / "requirements"


def _text(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


def _today_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ─── write_aggregation_docx ─────────────────────────────────────────

@tool(
    "write_aggregation_docx",
    "Write the raw aggregation Word document — one section per channel "
    "(email / chat / meeting / document) listing every collected source "
    "with filename + full text. This is the traceability artifact the "
    "human reviewer reads alongside the verification doc. Input `sources` "
    "is a list of dicts with keys: channel (one of email/chat/meeting/"
    "document), filename (str), content (str — the full extracted text). "
    "Output path defaults to data/requirements/aggregation_<YYYY-MM-DD>.docx. "
    "Returns {path, channel_counts, total_sources}.",
    {"sources": list, "output_path": str},
)
async def write_aggregation_docx_tool(args):
    from docx import Document  # lazy
    from docx.shared import Pt

    sources = args.get("sources") or []
    if not isinstance(sources, list):
        return _text({"error": "sources must be a list"})

    out_path = args.get("output_path")
    if not out_path:
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = str(_OUT_DIR / f"aggregation_{_today_stamp()}.docx")

    doc = Document()

    title = doc.add_heading("Requirement Collection — Raw Aggregation", level=0)
    sub = doc.add_paragraph()
    sub.add_run(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}").italic = True
    doc.add_paragraph(
        "This document collects every raw input the agent ingested across "
        "Email, Teams chat, and Teams call audio (transcribed). Use it to "
        "verify nothing was missed before reviewing the Verification doc."
    )
    doc.add_paragraph()

    channel_order = ["email", "chat", "meeting", "document"]
    channel_titles = {
        "email": "Email",
        "chat": "Teams Chat",
        "meeting": "Teams Call (Transcribed)",
        "document": "Documents / Attachments",
    }
    bucket: dict[str, list[dict]] = {c: [] for c in channel_order}
    for s in sources:
        if not isinstance(s, dict):
            continue
        ch = (s.get("channel") or "").strip().lower()
        if ch not in bucket:
            ch = "document"
        bucket[ch].append(s)

    counts: dict[str, int] = {}
    for ch in channel_order:
        items = bucket[ch]
        counts[ch] = len(items)
        if not items:
            continue
        doc.add_heading(f"{channel_titles[ch]} ({len(items)})", level=1)
        for s in items:
            fname = (s.get("filename") or "(unnamed)").strip()
            content = (s.get("content") or "").strip()
            doc.add_heading(fname, level=2)
            if not content:
                p = doc.add_paragraph()
                p.add_run("(empty)").italic = True
                continue
            for line in content.splitlines():
                p = doc.add_paragraph(line)
                for run in p.runs:
                    run.font.size = Pt(10)
        doc.add_paragraph()

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)

    memory.log_activity(
        task_name="requirement-collection:write_aggregation",
        result=f"sources={len(sources)} path={Path(out_path).name}",
        technical_details={"channel_counts": counts, "path": out_path},
    )

    return _text({
        "path": out_path,
        "channel_counts": counts,
        "total_sources": len(sources),
    })


# ─── write_verification_docx ────────────────────────────────────────

@tool(
    "write_verification_docx",
    "Write the client-facing verification Word document. Each requirement "
    "gets a heading + a 2-5 paragraph summary in plain prose (NOT bullets). "
    "Tone: neutral developer English, no jargon, no marketing voice. "
    "Input `requirements` is a list of dicts with keys: title (str — short "
    "<80 chars), summary (str — 2-5 paragraphs separated by blank lines), "
    "source_refs (optional list of source filenames so the client can trace "
    "back). Output filename format is 'Requirements Verification <YYYY-MM-DD>.docx' "
    "in data/requirements/. Returns {path, requirement_count}.",
    {"requirements": list, "output_path": str},
)
async def write_verification_docx_tool(args):
    from docx import Document  # lazy
    from docx.shared import Pt

    reqs = args.get("requirements") or []
    if not isinstance(reqs, list) or not reqs:
        return _text({"error": "requirements must be a non-empty list"})

    out_path = args.get("output_path")
    if not out_path:
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = str(_OUT_DIR / f"Requirements Verification {_today_stamp()}.docx")

    doc = Document()

    doc.add_heading("Requirements Verification", level=0)
    sub = doc.add_paragraph()
    sub.add_run(f"Date: {datetime.now().strftime('%Y-%m-%d')}").italic = True

    intro = doc.add_paragraph()
    intro.add_run(
        "Below are the requirements identified from your recent communications "
        "(email, Teams messages, and call discussions). Please review each "
        "summary and reply to confirm the interpretation, or send corrections. "
        "Each item will be tracked separately once you confirm."
    )
    doc.add_paragraph()

    for i, r in enumerate(reqs, 1):
        if not isinstance(r, dict):
            continue
        title = (r.get("title") or "").strip() or f"Requirement {i}"
        summary = (r.get("summary") or "").strip()
        source_refs = r.get("source_refs") or []

        doc.add_heading(f"{i}. {title}", level=1)

        if summary:
            for para in [p.strip() for p in summary.split("\n\n") if p.strip()]:
                doc.add_paragraph(para)
        else:
            p = doc.add_paragraph()
            p.add_run("(no summary supplied)").italic = True

        if isinstance(source_refs, list) and source_refs:
            ref_p = doc.add_paragraph()
            ref_run = ref_p.add_run("Sources: " + ", ".join(str(s) for s in source_refs))
            ref_run.italic = True
            ref_run.font.size = Pt(9)

        doc.add_paragraph()

    closing = doc.add_paragraph()
    closing.add_run(
        "Please reply to this email confirming the above interpretation is "
        "correct, or send any corrections inline. Once confirmed, each item "
        "will be filed for development."
    )

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)

    memory.log_activity(
        task_name="requirement-collection:write_verification",
        result=f"requirements={len(reqs)} path={Path(out_path).name}",
        technical_details={"path": out_path, "titles": [r.get("title") for r in reqs if isinstance(r, dict)]},
    )

    return _text({
        "path": out_path,
        "requirement_count": len(reqs),
    })


TOOLS = [
    write_aggregation_docx_tool,
    write_verification_docx_tool,
]

TOOL_NAMES = [
    "write_aggregation_docx",
    "write_verification_docx",
]
