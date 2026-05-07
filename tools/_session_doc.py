"""
Pull-session Word document — single consolidated artifact that every
on-demand pull command (Teams chat, email, Drive file) appends to.

A "session" is a logical grouping of pulls the user wants identified
together. The session resets ONLY when the user explicitly commands
"start a new session" — pulls otherwise keep appending to the same doc
across days, terminals, and tool calls.

Layout:
    data/requirements/sessions/current.docx              <- the live session doc
    data/requirements/sessions/.current_meta.json        <- start time + label
    data/requirements/sessions/archive/<timestamp>.docx  <- previous sessions

Format inside current.docx:
    Title  : "Pull Session — started <timestamp>"
    Heading1 per pull section, e.g.:
        "TEAMS CHAT — ContiHosting (chat #123)"
        "EMAIL — from titucse@gmail.com (subject: 'budget')"
        "DRIVE — file requirements_v2.pdf"
    Each section: small metadata block, then the raw content as paragraphs.

Used by:
    - TRW: pull_chat.py
    - NN:  pull_email.py, pull_drive.py
    - NN:  the verify-session prompt (reads only this file)
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor

# ── Paths ─────────────────────────────────────────────────────────────
_NN_ROOT = Path(__file__).parent.parent
SESSIONS_DIR = _NN_ROOT / "data" / "requirements" / "sessions"
SESSION_PATH = SESSIONS_DIR / "current.docx"
META_PATH = SESSIONS_DIR / ".current_meta.json"
ARCHIVE_DIR = SESSIONS_DIR / "archive"

# ── Style constants ───────────────────────────────────────────────────
_NAVY = RGBColor(0x1F, 0x3A, 0x5F)
_GREY = RGBColor(0x55, 0x60, 0x70)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _load_meta() -> dict:
    if not META_PATH.exists():
        return {}
    try:
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_meta(meta: dict) -> None:
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")


def _create_empty(label: str | None = None) -> dict:
    """Initialize a fresh session doc and meta. Returns the meta dict."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    started = _now_iso()
    meta = {
        "started_at": started,
        "label": label or "",
        "session_path": str(SESSION_PATH.relative_to(_NN_ROOT).as_posix()),
    }

    doc = Document()
    title = doc.add_heading("Pull Session", level=0)
    sub = doc.add_paragraph()
    r = sub.add_run(f"Started {started}")
    r.italic = True
    r.font.color.rgb = _GREY
    if label:
        sub.add_run(f"   |   Label: {label}").italic = True
    doc.add_paragraph()  # spacer
    doc.save(str(SESSION_PATH))

    _save_meta(meta)
    return meta


def get_or_create() -> Path:
    """Return the current session doc path, creating it if absent."""
    if not SESSION_PATH.exists():
        _create_empty()
    return SESSION_PATH


def reset(label: str | None = None) -> dict:
    """Archive the current session (if any) and start a fresh one.

    Returns: {archived_to: str|None, new_started_at: str, new_label: str}
    """
    archived_to = None
    if SESSION_PATH.exists():
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        old_meta = _load_meta()
        old_label = (old_meta.get("label") or "").strip()
        suffix = f"_{old_label}" if old_label else ""
        # Sanitize label for filename
        suffix = "".join(c for c in suffix if c.isalnum() or c in "-_")[:32]
        target = ARCHIVE_DIR / f"session_{_stamp()}{suffix}.docx"
        shutil.move(str(SESSION_PATH), str(target))
        archived_to = str(target.relative_to(_NN_ROOT).as_posix())
        try:
            META_PATH.unlink()
        except Exception:
            pass

    meta = _create_empty(label=label)
    return {
        "archived_to": archived_to,
        "new_started_at": meta["started_at"],
        "new_label": meta.get("label", ""),
        "session_path": meta["session_path"],
    }


def append_section(
    *,
    source: str,                # "TEAMS CHAT" / "EMAIL" / "DRIVE" / "MEETING"
    headline: str,              # e.g. 'ContiHosting (chat #123)' or 'from titucse@gmail.com'
    metadata: dict[str, str],   # key→value rows shown under the heading
    body_paragraphs: list[str], # the actual content (timestamps, message text, etc.)
) -> dict:
    """Append one pull section to the current session doc. Creates the doc
    if it doesn't exist yet (lazy-init session = first pull starts it)."""
    path = get_or_create()
    doc = Document(str(path))

    # Heading
    h = doc.add_heading(f"{source.upper()} — {headline}", level=1)

    # Metadata block
    if metadata:
        meta_p = doc.add_paragraph()
        meta_p.paragraph_format.space_after = Pt(2)
        first = True
        for k, v in metadata.items():
            if not first:
                meta_p.add_run("   |   ")
            first = False
            kr = meta_p.add_run(f"{k}: ")
            kr.bold = True
            kr.font.size = Pt(9)
            kr.font.color.rgb = _GREY
            vr = meta_p.add_run(str(v))
            vr.font.size = Pt(9)
            vr.font.color.rgb = _GREY

    # Body
    for line in body_paragraphs:
        if not line.strip():
            doc.add_paragraph()
            continue
        doc.add_paragraph(line)

    # Trailing spacer between sections
    doc.add_paragraph()

    doc.save(str(path))

    return {
        "session_path": str(path.relative_to(_NN_ROOT).as_posix()),
        "absolute_path": str(path),
        "section": f"{source.upper()} — {headline}",
        "appended_paragraphs": len([p for p in body_paragraphs if p.strip()]),
    }


def status() -> dict:
    """Cheap inspection helper — what's currently in the session?"""
    if not SESSION_PATH.exists():
        return {"exists": False}
    meta = _load_meta()
    doc = Document(str(SESSION_PATH))
    section_titles = [p.text for p in doc.paragraphs
                      if p.style.name.startswith("Heading 1")]
    return {
        "exists": True,
        "session_path": str(SESSION_PATH.relative_to(_NN_ROOT).as_posix()),
        "absolute_path": str(SESSION_PATH),
        "started_at": meta.get("started_at"),
        "label": meta.get("label", ""),
        "section_count": len(section_titles),
        "sections": section_titles,
    }
