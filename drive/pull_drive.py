"""
On-demand Google Drive pull — fetch matching files from the configured
Drive folder, extract content, and append to the pull-session doc.

File types handled:
    PDF                .pdf            (pypdf)
    Plain text         .txt            (direct read)
    Word               .docx           (python-docx)
    Word legacy        .doc            (byte-scan, best-effort)
    Audio / video      .mp3 .mp4 .m4a .wav .webm .mkv ...  (Groq Whisper)

Filters (all optional, AND'd):
    --filename "<text>"        substring match on filename
    --last-files N             keep only the N most recently created of the matches
    --last-minutes N           createdTime within last N min (now - N min .. now)
    --from-time "<HH:MM>"      manual createdTime window start (with --date)
    --to-time "<HH:MM>"        manual createdTime window end (with --date)
    --date YYYY-MM-DD          target date for the manual window (default today)

Examples:
    python -m drive.pull_drive --last-files 1
    python -m drive.pull_drive --last-files 3
    python -m drive.pull_drive --last-minutes 10
    python -m drive.pull_drive --filename "budget"
    python -m drive.pull_drive --from-time "3 PM" --to-time "9 PM"

Differs from the auto-poll model (drive_ingester.py): explicitly user-
commanded with filters, writes ONE consolidated section into the
session doc instead of one .txt per file in inbox/.

Env vars (same as drive_ingester.py):
    GOOGLE_CREDENTIALS_PATH    service-account JSON path
    GDRIVE_AUDIO_FOLDER_ID     folder to scan
    GROQ_API_KEY               required only if matched files include audio
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).parent.parent  # drive/<file> -> NN root
load_dotenv(_HERE / ".env", override=True)

from drive import drive_ingester as di  # noqa: E402
from tools import _session_doc as session_doc  # noqa: E402


def _parse_time(s: str) -> dt.time:
    s = s.strip().upper().replace(".", "")
    for fmt in ("%H:%M", "%I:%M %p", "%I %p", "%I:%M%p", "%I%p"):
        try:
            return dt.datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized time {s!r}.")


def _matches_filters(file: dict, *, name_substr: str | None,
                     from_dt: dt.datetime | None,
                     to_dt: dt.datetime | None) -> bool:
    if name_substr:
        if name_substr.lower() not in (file.get("name") or "").lower():
            return False
    if from_dt or to_dt:
        ct_str = file.get("createdTime") or ""
        try:
            # createdTime is ISO 8601 with Z suffix
            ct = dt.datetime.fromisoformat(ct_str.replace("Z", "+00:00"))
            ct_local = ct.astimezone().replace(tzinfo=None)
        except Exception:
            return False
        if from_dt and ct_local < from_dt:
            return False
        if to_dt and ct_local > to_dt:
            return False
    return True


def _extract(tmp_path: Path, kind: str) -> str:
    if kind == "audio":
        return di._transcribe_via_groq(tmp_path)
    if kind == "pdf":
        return di._extract_pdf_text(tmp_path)
    if kind == "docx":
        return di._extract_docx_text(tmp_path)
    if kind == "doc":
        return di._extract_doc_text(tmp_path)
    if kind == "txt":
        return di._extract_txt_text(tmp_path)
    if kind == "xlsx":
        return di._extract_xlsx_text(tmp_path)
    if kind == "xls":
        return di._extract_xls_text(tmp_path)
    return ""


def _created_local(file: dict) -> dt.datetime | None:
    ct_str = file.get("createdTime") or ""
    try:
        ct = dt.datetime.fromisoformat(ct_str.replace("Z", "+00:00"))
        return ct.astimezone().replace(tzinfo=None)
    except Exception:
        return None


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--filename", default=None,
                   help="Filename substring filter")
    p.add_argument("--last-files", type=int, default=None,
                   help="Take the N most recently created files matching "
                        "the other filters. E.g. --last-files 3")
    p.add_argument("--last-minutes", type=int, default=None,
                   help="Files whose createdTime is within the last N "
                        "minutes (now - N min .. now). Supersedes "
                        "--from-time / --to-time / --date.")
    p.add_argument("--from-time", dest="from_t", default=None,
                   help="Start of createdTime window (HH:MM or '3 PM')")
    p.add_argument("--to-time", dest="to_t", default=None,
                   help="End of createdTime window (HH:MM or '5 PM')")
    p.add_argument("--date", default=None,
                   help="Target date YYYY-MM-DD (default today, used with time filter)")
    args = p.parse_args()

    # Resolve absolute (start_dt, end_dt) window if any time filter set.
    from_dt = to_dt = None
    target_date = None
    if args.last_minutes is not None:
        if args.last_minutes <= 0:
            print("--last-minutes must be > 0", file=sys.stderr)
            return 1
        to_dt = dt.datetime.now()
        from_dt = to_dt - dt.timedelta(minutes=args.last_minutes)
        target_date = from_dt.date()
    elif args.from_t or args.to_t or args.date:
        target_date = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
                       if args.date else dt.date.today())
        from_t = _parse_time(args.from_t) if args.from_t else dt.time(0, 0)
        to_t = _parse_time(args.to_t) if args.to_t else dt.time(23, 59)
        from_dt = dt.datetime.combine(target_date, from_t)
        to_dt = dt.datetime.combine(target_date, to_t)

    folder_id = os.getenv("GDRIVE_AUDIO_FOLDER_ID")
    if not folder_id:
        print("GDRIVE_AUDIO_FOLDER_ID not set", file=sys.stderr)
        return 2

    print(f"Listing Drive folder {folder_id}...")
    print(f"  Filename:    {args.filename or '(any)'}")
    if args.last_minutes is not None:
        print(f"  Last:        {args.last_minutes} min "
              f"({from_dt:%Y-%m-%d %H:%M:%S} -> {to_dt:%H:%M:%S})")
    elif from_dt:
        print(f"  CreatedTime: {from_dt:%Y-%m-%d %H:%M} -> {to_dt:%H:%M}")
    if args.last_files is not None:
        print(f"  Top-N:       most recent {args.last_files} of matches")

    drive = di._drive_service()
    listed = di._list_ingestable_files(drive, folder_id)
    matched = [f for f in listed
               if _matches_filters(f, name_substr=args.filename,
                                   from_dt=from_dt, to_dt=to_dt)]

    # Apply --last-files: sort by createdTime desc, take top N
    if args.last_files is not None:
        if args.last_files <= 0:
            print("--last-files must be > 0", file=sys.stderr)
            return 1
        matched.sort(key=lambda f: _created_local(f) or dt.datetime.min,
                     reverse=True)
        matched = matched[: args.last_files]

    print(f"  Matched: {len(matched)} of {len(listed)} ingestable file(s)")

    if not matched:
        return 0

    # Download + extract each match
    tmp_dir = _HERE / "data" / "requirements" / "_drive_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    body_lines: list[str] = []
    extracted_count = 0
    for i, f in enumerate(matched, 1):
        fid = f["id"]
        name = f["name"]
        kind = di._classify(f)
        tmp_path = tmp_dir / f"{fid}-{Path(name).name}"
        print(f"  [{i}/{len(matched)}] downloading {name} ({kind})...")
        try:
            di._download_file(drive, fid, tmp_path)
        except Exception as e:
            body_lines += ["", f"--- File {i}: {name} ---",
                           f"[download failed: {e}]"]
            continue
        try:
            text = _extract(tmp_path, kind)
        except Exception as e:
            body_lines += ["", f"--- File {i}: {name} ({kind}) ---",
                           f"[extract failed: {e}]"]
            continue
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass

        body_lines += ["", f"--- File {i}: {name} ({kind}) ---",
                       f"Drive ID: {fid}",
                       f"Created: {f.get('createdTime')}",
                       ""]
        for ln in (text or "(empty extraction)").splitlines():
            body_lines.append(ln)
        extracted_count += 1

    headline_parts = []
    if args.filename:
        headline_parts.append(f"filename '{args.filename}'")
    if from_dt:
        headline_parts.append(f"created {from_dt:%H:%M}-{to_dt:%H:%M}")
    headline = "  ".join(headline_parts) or "(no filter)"

    result = session_doc.append_section(
        source="DRIVE",
        headline=headline,
        metadata={
            "Date filter": str(target_date) if (from_dt or args.date) else "(any)",
            "Files matched": str(len(matched)),
            "Files extracted": str(extracted_count),
        },
        body_paragraphs=body_lines,
    )
    print(f"\nAppended to session doc: {result['absolute_path']}")
    print(f"Section: {result['section']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
