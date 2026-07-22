"""Regenerate session.docx for the bangla_two_requirements case.

Two real requirements arriving through different channels: one in an
English client email (with a deadline), one stated in romanized Bangla
inside a Teams chat. Plus one chat window of pure noise. Tests
multi-channel extraction, Bangla-to-English translation of the
requirement title, and deadline capture.

Run from repo root:
    py -3 evals/cases/bangla_two_requirements/build_fixture.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools import _session_doc as session_doc  # noqa: E402


def build() -> Path:
    session_doc.reset(label="eval-bangla-two-requirements")

    # ─── Section 1: real requirement via email (with deadline) ───────
    session_doc.append_section(
        source="EMAIL",
        headline="from rahim@jamuna-retail.com — Daily sales report export",
        metadata={
            "From": "rahim@jamuna-retail.com",
            "Subject": "Daily sales report export",
            "Received": "2026-07-20 10:12",
            "Attachments": "0",
        },
        body_paragraphs=[
            "From: rahim@jamuna-retail.com",
            "Subject: Daily sales report export",
            "Received: 2026-07-20 10:12",
            "",
            "Body:",
            "Dear team,",
            "",
            "We need the daily sales report to export to both Excel and "
            "PDF, and the system should email it automatically to the "
            "manager group every night at 9 PM. This must be live before "
            "the Eid release on 15 August.",
            "",
            "Regards, Rahim",
        ],
        source_id="email/rahim-jamuna-retail.com/2026-07-20T1012/eval0101",
    )

    # ─── Section 2: real requirement via Teams chat (romanized Bangla) ─
    session_doc.append_section(
        source="TEAMS CHAT",
        headline="Jamuna Retail (chat #131) — 2026-07-20 11:40",
        metadata={
            "Conversation": "19:jkl...@thread.skype",
            "Msgs": "3",
            "Senders": "Rahim Uddin (Jamuna), Kamrul Hasan (Titu)",
        },
        body_paragraphs=[
            "--- chat: Jamuna Retail (chat #131) ---",
            "[11:40] Rahim Uddin (Jamuna): vai arekta jinish, kono item er "
            "stock 10 er niche gele amar phone e SMS alert lagbe",
            "[11:41] Kamrul Hasan (Titu): thik ache vai, note korlam",
            "[11:42] Rahim Uddin (Jamuna): thanks vai",
        ],
        source_id="chat/131-2026-07-20-1140/eval0102",
    )

    # ─── Section 3: chat noise (lunch chatter) ───────────────────────
    session_doc.append_section(
        source="TEAMS CHAT",
        headline="Engineering (chat #133) — 2026-07-20 13:02",
        metadata={
            "Conversation": "19:mno...@thread.skype",
            "Msgs": "2",
            "Senders": "Rabby Shaikh, Md Nasir Uddin",
        },
        body_paragraphs=[
            "--- chat: Engineering (chat #133) ---",
            "[13:02] Rabby Shaikh: lunch e ki khichuri ashce keu janen?",
            "[13:03] Md Nasir Uddin: hae vai, canteen e khichuri ar dim.",
        ],
        source_id="chat/133-2026-07-20-1302/eval0103",
    )

    src = session_doc.SESSION_PATH
    dst = _HERE / "session.docx"
    shutil.copy2(str(src), str(dst))
    return dst


def main():
    out = build()
    print(f"wrote {out}  ({out.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
