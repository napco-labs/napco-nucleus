"""Regenerate session.docx for the example_operator_management case.

One synthetic pull session: one client-PDF-via-email (real requirement),
plus three Teams-chat windows of pure noise. Tests that the identifier
extracts ONE real requirement and rejects three noise sources.

Run from repo root:
    py -3 evals/cases/example_operator_management/build_fixture.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Use the live session_doc module to build the fixture, then move the
# resulting file into this case folder. This guarantees the fixture
# layout matches exactly what production pulls produce.

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools import _session_doc as session_doc  # noqa: E402


def build() -> Path:
    # Fresh session
    session_doc.reset(label="eval-example-operator-management")

    # ─── Section 1: real client requirement (email + PDF attachment) ─
    session_doc.append_section(
        source="EMAIL",
        headline="from akib@acme.com — Operator Management — feature spec",
        metadata={
            "From": "akib@acme.com",
            "Subject": "Operator Management — feature spec",
            "Received": "2026-05-10 14:23",
            "Attachments": "1",
        },
        body_paragraphs=[
            "From: akib@acme.com",
            "Subject: Operator Management — feature spec",
            "Received: 2026-05-10 14:23",
            "",
            "Body:",
            "Hi team,",
            "",
            "Please find attached the spec for Operator Management. The "
            "key points: full CRUD on the operators table, server-side "
            "search across name + phone + outlet, role-based access "
            "control (admin can edit, supervisor can view, operators "
            "are read-only on their own record), and an audit log "
            "capturing who created / edited / deleted each operator "
            "with timestamps retained for 90 days.",
            "",
            "Let me know if anything is ambiguous before kickoff.",
            "",
            "Thanks, Akib",
            "",
            "Attachments (1):",
            "  --- attachment: Operator_spec.pdf ---",
            "  Operator Management — Functional Specification v1.0",
            "  ",
            "  1. CRUD operations on the operator entity (create, read, ",
            "     update, delete).",
            "  2. Search by name, phone number, or assigned outlet — ",
            "     server-side filtering, paginated results.",
            "  3. Role-based access control:",
            "     - Admin: full CRUD",
            "     - Supervisor: view + comment only",
            "     - Operator: view their own record",
            "  4. Audit log on every CRUD action — actor, timestamp, ",
            "     before/after snapshot. 90-day retention.",
        ],
        source_id="email/akib-acme.com/2026-05-10T1423/eval0001",
    )

    # ─── Section 2: chat noise (food chatter, Bangla romanized) ──────
    session_doc.append_section(
        source="TEAMS CHAT",
        headline="ContiHosting (chat #118) — 2026-05-09 13:36",
        metadata={
            "Conversation": "19:abc...@thread.skype",
            "Msgs": "4",
            "Senders": "Rabby Shaikh, Salman Ahmed Firoz",
        },
        body_paragraphs=[
            "--- chat: ContiHosting (chat #118) ---",
            "[13:36] Rabby Shaikh: vai phuska khaite jabo ki na bolen",
            "[13:37] Salman Ahmed Firoz: aaj na vai, ami fuska khabo na",
            "[13:38] Rabby Shaikh: are biryani niye chinta korte hobe na",
            "[13:39] Salman Ahmed Firoz: hahaha okay",
        ],
        source_id="chat/118-2026-05-09-1336/eval0002",
    )

    # ─── Section 3: chat noise (WFH announcement) ────────────────────
    session_doc.append_section(
        source="TEAMS CHAT",
        headline="Engineering (chat #124) — 2026-05-09 09:05",
        metadata={
            "Conversation": "19:def...@thread.skype",
            "Msgs": "1",
            "Senders": "Md Nasir Uddin",
        },
        body_paragraphs=[
            "--- chat: Engineering (chat #124) ---",
            "[09:05] Md Nasir Uddin: I am working from home today.",
        ],
        source_id="chat/124-2026-05-09-0905/eval0003",
    )

    # ─── Section 4: chat noise (internal process announcement) ───────
    session_doc.append_section(
        source="TEAMS CHAT",
        headline="Engineering (chat #120) — 2026-05-09 15:23",
        metadata={
            "Conversation": "19:ghi...@thread.skype",
            "Msgs": "2",
            "Senders": "Kamrul Hasan (Titu)",
        },
        body_paragraphs=[
            "--- chat: Engineering (chat #120) ---",
            "[15:23] Kamrul Hasan (Titu): Team, I have completed the "
            "Requirement Management workflow. Please review the PPT "
            "and complete your machine setup.",
            "[15:24] Kamrul Hasan (Titu): docs/Setup_Guide.pdf and "
            "docs/NAPCO-Nucleus-Requirement-Management.pptx in the repo.",
        ],
        source_id="chat/120-2026-05-09-1523/eval0004",
    )

    # Move the generated session.docx into this case folder.
    src = session_doc.SESSION_PATH
    dst = _HERE / "session.docx"
    shutil.copy2(str(src), str(dst))
    return dst


def main():
    out = build()
    print(f"wrote {out}  ({out.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
