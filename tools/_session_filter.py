"""Pre-LLM noise filter for the pull-session document.

The most expensive thing the pipeline does is read content the LLM
will then dismiss as noise. A real client requirement might be one
section out of seven; the other six are food chatter, WFH notes,
internal-process announcements, and one-line acknowledgements.
Passing those to Claude pays full Extract-stage tokens for content
the Critic was going to throw away anyway.

This filter drops obvious noise BEFORE the prompt is built. Two
mechanisms:

  1. Length floor — sections with fewer than NUCLEUS_MIN_BODY_CHARS
     of body text get dropped (default 80). Catches "WFH today",
     "thanks!", short reaction-only chats.

  2. Pattern regex — sections whose body matches any
     NUCLEUS_NOISE_PATTERNS regex get dropped. Default patterns
     cover the food-chat / casual-banter cases seen in real runs.
     User can override / extend via:
        - env: NUCLEUS_NOISE_PATTERNS=regex1|regex2|regex3
        - file: data/noise_patterns.json (list of regex strings;
          loaded if env not set)

Sections from EMAIL or DRIVE channels are NEVER filtered by the
length floor — a one-line client email saying "approved" is signal,
not noise. Only TEAMS CHAT sections are length-filtered.

Returns a (kept, dropped) tuple of section dicts so callers can
log + display what got cut. Each section dict carries 'source',
'headline', 'metadata', 'body_lines', and (for kept items) the
original 'source_id'.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


_DEFAULT_NOISE_PATTERNS = [
    # Bangla romanized food/casual chatter
    r"\bphuska|fuchka|fuska\b",
    r"\bbiriyani|biryani\b",
    r"\b(allah|khoda) hafez\b",  # farewell, not a requirement
    # English short-form casual
    r"^\s*(thanks|ok|got it|sounds good|cool)\b[\s.!?]*$",
    r"^\s*(working from home|wfh|out of office|ooo)\b",
    # Internal-process announcements that aren't client requirements
    r"\b(requirement management workflow|setup_guide\.pdf|quickstart\.md)\b",
]

_LENGTH_FLOOR_DEFAULT = 80
_LENGTH_FLOOR_CHANNELS = {"TEAMS CHAT", "TEAMS ATTACHMENT"}


def _load_patterns() -> list[re.Pattern]:
    """Compile noise patterns from env (preferred) or
    data/noise_patterns.json (fallback) or built-in defaults."""
    raw = (os.environ.get("NUCLEUS_NOISE_PATTERNS") or "").strip()
    sources: list[str] = []
    if raw:
        # Pipe-separated regexes
        sources = [p for p in raw.split("|") if p.strip()]
    else:
        path = (Path(__file__).parent.parent
                / "data" / "noise_patterns.json")
        if path.exists():
            try:
                sources = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(sources, list):
                    sources = []
            except Exception as e:
                logger.warning("noise_patterns.json parse failed: %s", e)
                sources = []
        if not sources:
            sources = _DEFAULT_NOISE_PATTERNS
    compiled: list[re.Pattern] = []
    for s in sources:
        try:
            compiled.append(re.compile(s, re.IGNORECASE | re.MULTILINE))
        except re.error as e:
            logger.warning("skipping invalid noise pattern %r: %s", s, e)
    return compiled


def _length_floor() -> int:
    try:
        return int(os.environ.get("NUCLEUS_MIN_BODY_CHARS",
                                   str(_LENGTH_FLOOR_DEFAULT)))
    except ValueError:
        return _LENGTH_FLOOR_DEFAULT


def parse_session_doc(path: Path) -> list[dict]:
    """Parse a session .docx into a list of section dicts. Each:
        {source, headline, metadata, body_lines, source_id}
    Uses the visible structure: Heading 1 starts a section, the next
    paragraph carries Source ID + metadata, the rest is body until
    the next Heading 1."""
    from docx import Document  # lazy
    doc = Document(str(path))
    sections: list[dict] = []
    current: dict | None = None
    for p in doc.paragraphs:
        style = (p.style.name if p.style else "") or ""
        text = p.text or ""
        if style.startswith("Heading 1"):
            if current is not None:
                sections.append(current)
            # Heading format: "SOURCE — headline"
            split = text.split("—", 1)
            source = (split[0] if split else text).strip()
            headline = (split[1].strip() if len(split) > 1 else "")
            current = {
                "source": source.upper(),
                "headline": headline,
                "metadata": {},
                "body_lines": [],
                "source_id": "",
            }
            continue
        if current is None:
            continue
        # Metadata block usually appears right after the heading
        if "Source ID:" in text and not current["source_id"]:
            # Pull "Source ID: <id>" then key/value pairs separated by " | "
            for chunk in text.split("|"):
                chunk = chunk.strip()
                if ":" in chunk:
                    k, v = chunk.split(":", 1)
                    k, v = k.strip(), v.strip()
                    if k == "Source ID":
                        current["source_id"] = v
                    else:
                        current["metadata"][k] = v
            continue
        if text.strip():
            current["body_lines"].append(text)
    if current is not None:
        sections.append(current)
    return sections


def filter_sections(sections: list[dict]) -> tuple[list[dict], list[dict]]:
    """Apply the noise + length-floor filters. Returns (kept, dropped).
    Each dropped section gets a 'drop_reason' field for inspection."""
    floor = _length_floor()
    patterns = _load_patterns()

    kept: list[dict] = []
    dropped: list[dict] = []

    for s in sections:
        source = (s.get("source") or "").upper()
        body = "\n".join(s.get("body_lines") or [])
        body_chars = len(body.strip())

        # Length floor — chat-only
        if source in _LENGTH_FLOOR_CHANNELS and body_chars < floor:
            dropped.append({**s, "drop_reason": (
                f"length-floor: {body_chars} chars < {floor}")})
            continue

        # Pattern noise — across all sources
        matched: str | None = None
        for pat in patterns:
            if pat.search(body):
                matched = pat.pattern
                break
        if matched:
            dropped.append({**s, "drop_reason": (
                f"pattern: {matched}")})
            continue

        kept.append(s)

    return kept, dropped


def filter_session_text(session_text: str) -> tuple[str, dict]:
    """Convenience: take the raw concatenated session text (as
    pipeline.py reads it today), do a best-effort parse, filter, and
    return the trimmed text plus a stats dict for logging."""
    # We can't actually parse the .docx structure from raw text reliably.
    # The richer entry point is filter_doc() below, used by pipeline.py.
    # Here we just count chars for reporting when the .docx isn't available.
    return session_text, {
        "filtered": False,
        "note": "filter_session_text is a no-op; use filter_doc() instead",
    }


def filter_doc(session_path: Path) -> tuple[str, dict]:
    """Full path: parse the .docx, filter sections, return the
    rebuilt plain-text session content + stats for logging.

    The rebuilt text mirrors what _read_session_text would produce
    for the KEPT sections — same heading order, same metadata block,
    same body lines."""
    sections = parse_session_doc(session_path)
    kept, dropped = filter_sections(sections)
    rebuilt = _rebuild_text(kept)
    stats = {
        "total_sections": len(sections),
        "kept_sections": len(kept),
        "dropped_sections": len(dropped),
        "kept_chars": len(rebuilt),
        "drops": [
            {"source": d.get("source"),
             "headline": d.get("headline"),
             "reason": d.get("drop_reason"),
             "body_chars": len("\n".join(d.get("body_lines") or [])),
            } for d in dropped
        ],
    }
    return rebuilt, stats


def _rebuild_text(kept: list[dict]) -> str:
    out: list[str] = []
    for s in kept:
        out.append(f"{s['source']} — {s['headline']}")
        meta_parts: list[str] = []
        if s.get("source_id"):
            meta_parts.append(f"Source ID: {s['source_id']}")
        for k, v in (s.get("metadata") or {}).items():
            meta_parts.append(f"{k}: {v}")
        if meta_parts:
            out.append("   |   ".join(meta_parts))
        out.extend(s.get("body_lines") or [])
        out.append("")  # spacer
    return "\n".join(out)
