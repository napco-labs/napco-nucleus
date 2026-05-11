"""Resolve Teams chat-attachment URIObjects to local files on disk.

Teams chat messages with shared files carry a URIObject:
    {name, kind, size_bytes, url}

The URL points at a CDN endpoint that requires a Bearer token from the
Teams desktop client, so we can't download it ourselves. But when the
user actually clicks "Download" on a chat attachment, Teams writes the
file to the OS Downloads folder under its OriginalName. This module
scans candidate directories for files matching (name, size_bytes) so we
can copy them to central alongside the chat .docx.

Limitations
- Only finds attachments the user has actually downloaded. Files that
  were sent in chat but never opened locally are invisible to us.
- Matches by exact filename + size. If size_bytes is 0 (Teams sometimes
  omits FileSize on tiny URIObjects), falls back to name-only match.
- If two files share name+size, picks the most recent mtime.

Candidate dirs
- $NUCLEUS_DOWNLOADS_PATH (override, comma-separated)
- ~/Downloads
- ~/Downloads/Teams       (if it exists)
- ~/Documents/Teams       (if it exists)
"""
from __future__ import annotations

import os
from pathlib import Path


MAX_BYTES = 100 * 1024 * 1024  # skip anything > 100 MB


def default_search_dirs() -> list[Path]:
    """Where to look for downloaded Teams chat attachments."""
    override = (os.environ.get("NUCLEUS_DOWNLOADS_PATH") or "").strip()
    if override:
        return [Path(p.strip()) for p in override.split(",") if p.strip()]
    home = Path.home()
    candidates = [
        home / "Downloads",
        home / "Downloads" / "Teams",
        home / "Documents" / "Teams",
    ]
    return [p for p in candidates if p.exists()]


def gather_attachments(chat_blocks: list[dict]) -> list[dict]:
    """Walk chat_blocks, return a deduped list of attachment dicts.

    Each attachment dict has {name, kind, size_bytes, url}. Dedupe key is
    the URL (Teams reuses the URL across forwards of the same file).
    """
    seen: dict[str, dict] = {}
    for blk in chat_blocks:
        for m in blk.get("msgs", []):
            att = m.get("attachment")
            if not att or not att.get("url"):
                continue
            seen.setdefault(att["url"], att)
    return list(seen.values())


def _candidates(name: str, search_dirs: list[Path]) -> list[Path]:
    out: list[Path] = []
    for d in search_dirs:
        try:
            if not d.exists():
                continue
        except OSError:
            continue
        # Exact name match
        exact = d / name
        if exact.is_file():
            out.append(exact)
        # Browsers / Teams often append " (1)", " (2)" on dup downloads.
        # Match those too — same stem, same suffix.
        stem, dot, ext = name.rpartition(".")
        if dot:
            try:
                for p in d.glob(f"{stem} (*).{ext}"):
                    if p.is_file():
                        out.append(p)
            except OSError:
                pass
    return out


def resolve_local(att: dict, search_dirs: list[Path] | None = None) -> Path | None:
    """Find a local file matching the URIObject's name (+ size if known).

    Returns the best-matching Path, or None if no candidate qualifies.
    """
    name = (att.get("name") or "").strip()
    if not name or name == "(no name)":
        return None
    if search_dirs is None:
        search_dirs = default_search_dirs()
    if not search_dirs:
        return None

    candidates = _candidates(name, search_dirs)
    if not candidates:
        return None

    target_size = int(att.get("size_bytes") or 0)

    def _score(p: Path) -> tuple[int, float]:
        # Prefer (1) size match if we have a target, then (2) most recent.
        try:
            st = p.stat()
        except OSError:
            return (0, 0.0)
        size_ok = 1 if (target_size and st.st_size == target_size) else 0
        # If we have a target size and it doesn't match, demote heavily.
        if target_size and not size_ok:
            return (-1, st.st_mtime)
        return (size_ok, st.st_mtime)

    best = max(candidates, key=_score)
    try:
        st = best.stat()
    except OSError:
        return None
    if target_size and st.st_size != target_size:
        # Name matched but size didn't — refuse rather than risk wrong file.
        return None
    if st.st_size > MAX_BYTES:
        return None
    return best


def resolve_all(chat_blocks: list[dict],
                search_dirs: list[Path] | None = None) -> list[dict]:
    """Resolve every attachment in chat_blocks. Returns one dict per
    attachment: {name, kind, size_bytes, url, local_path or None,
    resolved (bool), reason (str if not resolved)}."""
    if search_dirs is None:
        search_dirs = default_search_dirs()
    out: list[dict] = []
    for att in gather_attachments(chat_blocks):
        rec = dict(att)
        local = resolve_local(att, search_dirs) if search_dirs else None
        if local is None:
            rec["local_path"] = None
            rec["resolved"] = False
            rec["reason"] = (
                "no search dirs"
                if not search_dirs
                else "no matching file in Downloads"
            )
        else:
            rec["local_path"] = local
            rec["resolved"] = True
            rec["reason"] = ""
        out.append(rec)
    return out
