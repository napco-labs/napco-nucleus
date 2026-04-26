"""Render the Infrastructure & Access Requirements memo as a PDF.

A clean, send-to-boss memo. Same content as the strategic plan's
Prerequisites & Open Items section, but presented as a focused two-page
note in plain typography.

Run:
    py -3 scripts/generate_requirements_memo.py
Output:
    docs/NAPCO-Nucleus-Infrastructure-Requirements.pdf
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as canvas_mod
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from generate_strategic_plan import (
    BODY,
    CONTENT_W,
    INK,
    MUTED,
    NAVY,
    OCHRE,
    RULE,
)


# --------------------------------------------------------------------------
# Paragraph styles — minimal, type-led
# --------------------------------------------------------------------------

TITLE = ParagraphStyle(
    "Title", fontName="Helvetica-Bold", fontSize=22, leading=26,
    textColor=NAVY, alignment=TA_LEFT, spaceAfter=2,
)
SUBTITLE = ParagraphStyle(
    "Subtitle", fontName="Helvetica-Oblique", fontSize=11.5, leading=15,
    textColor=OCHRE, alignment=TA_LEFT, spaceAfter=4,
)
META = ParagraphStyle(
    "Meta", fontName="Helvetica", fontSize=9.5, leading=13,
    textColor=MUTED, alignment=TA_LEFT, spaceAfter=18,
)
H1 = ParagraphStyle(
    "H1", fontName="Helvetica-Bold", fontSize=14.5, leading=18,
    textColor=NAVY, alignment=TA_LEFT, spaceBefore=12, spaceAfter=0,
)
SECTION_LEAD = ParagraphStyle(
    "SectionLead", fontName="Helvetica-Oblique", fontSize=10, leading=13,
    textColor=OCHRE, alignment=TA_LEFT, spaceBefore=4, spaceAfter=8,
)
H2 = ParagraphStyle(
    "H2", fontName="Helvetica-Bold", fontSize=11, leading=14,
    textColor=NAVY, alignment=TA_LEFT, spaceBefore=10, spaceAfter=4,
)
BODY_LEFT = ParagraphStyle(
    "BodyLeft", parent=BODY, alignment=TA_LEFT, fontSize=10.5, leading=14.5,
    spaceAfter=8,
)
BULLET = ParagraphStyle(
    "Bullet", fontName="Helvetica", fontSize=10, leading=14,
    textColor=INK, alignment=TA_LEFT, spaceAfter=3,
    leftIndent=14, firstLineIndent=-14,
)
CLOSING = ParagraphStyle(
    "Closing", fontName="Helvetica", fontSize=10.5, leading=15,
    textColor=NAVY, alignment=TA_LEFT, spaceAfter=4, spaceBefore=18,
)
SIGNOFF = ParagraphStyle(
    "Signoff", fontName="Helvetica-Oblique", fontSize=10.5, leading=14,
    textColor=INK, alignment=TA_LEFT, spaceAfter=0, spaceBefore=8,
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def section_heading(title, lead=None):
    """Bold navy H1 with a thin ochre rule beneath, optional italic lead."""
    h = Table([[Paragraph(title, H1)]], colWidths=[CONTENT_W])
    h.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, -1), (-1, -1), 1.2, OCHRE),
    ]))
    out = [h]
    if lead:
        out.append(Paragraph(lead, SECTION_LEAD))
    return out


def bullet(text):
    return Paragraph("&bull;&nbsp;&nbsp;" + text, BULLET)


# --------------------------------------------------------------------------
# Page chrome
# --------------------------------------------------------------------------

def on_page(canvas: canvas_mod.Canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(OCHRE)
    canvas.setLineWidth(1.2)
    canvas.line(20 * mm, h - 18 * mm, w - 20 * mm, h - 18 * mm)
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, 18 * mm, w - 20 * mm, 18 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        20 * mm, 13 * mm,
        "NAPCO Nucleus AI Agent  |  Infrastructure & Access Requirements",
    )
    canvas.drawRightString(w - 20 * mm, 13 * mm, f"Page {doc.page}")
    canvas.restoreState()


# --------------------------------------------------------------------------
# Content
# --------------------------------------------------------------------------

def header_block():
    return [
        Paragraph("Infrastructure &amp; Access Requirements", TITLE),
        Paragraph(
            "NAPCO Nucleus AI Agent &mdash; a memo for IT and leadership",
            SUBTITLE,
        ),
        Paragraph(
            "Mohammad Kamrul Hasan  &nbsp;&bull;&nbsp;  April 2026",
            META,
        ),
    ]


def intro():
    return [
        Paragraph(
            "NAPCO Nucleus AI Agent is a Claude-native automation platform "
            "built to take two day-to-day burdens off the team: turning "
            "client communications into actionable backlog items, and "
            "continuously validating the MVP Access platform through "
            "automated tests. The agent already runs seven scheduled "
            "workflows on a self-hosted Windows VM today.",
            BODY_LEFT,
        ),
        Paragraph(
            "This short memo lists the infrastructure and access we need "
            "from IT and operations to take the system from its current "
            "developer-run state into properly supported daily operations.",
            BODY_LEFT,
        ),
    ]


def section_one():
    out = []
    out.extend(section_heading(
        "1.  DevOps &amp; Release Automation (CI/CD)",
        "Stable foundations for the nightly build-and-deploy pipeline.",
    ))
    out.append(Paragraph(
        "The nightly TFS &rarr; MSBuild &rarr; IIS pipeline runs unattended "
        "at 22:00 BDT and primes the morning test cycle. If any of the "
        "items below moves without notice, the pipeline writes to nowhere "
        "and the next morning's tests all fail.",
        BODY_LEFT,
    ))

    out.append(Paragraph("Dedicated Deployment Server (IIS Host)", H2))
    out.append(bullet(
        "A stable IIS environment that will not be re-purposed without "
        "notice. The pipeline binds to a specific host; if it moves, every "
        "run after that fails until the configuration is reapplied."
    ))

    out.append(Paragraph("Static UNC Path for Build Artifacts", H2))
    out.append(bullet(
        "A fixed, persistent network path that the deploy step writes to. "
        "A documented, change-controlled path means any future move is "
        "planned, not a surprise that surfaces at 03:00 the next morning "
        "when E2E starts failing."
    ))

    out.append(Paragraph("TFS Access &mdash; Dedicated Service Account", H2))
    out.append(bullet(
        "<b>TFS_USERNAME / TFS_PASSWORD</b> &mdash; non-expiring credentials "
        "owned by the team, not tied to an individual."
    ))
    out.append(bullet("<b>TFS_URL</b> &mdash; the base collection endpoint."))
    out.append(bullet(
        "<b>TFS_PROJECT_PATH</b> &mdash; the branch the pipeline pulls from "
        "(for example, $/MVPAccess/Main)."
    ))
    out.append(bullet(
        "Read access on the MVPAccess project is sufficient; the pipeline "
        "does not write back to TFS."
    ))
    return out


def section_two():
    out = []
    out.extend(section_heading(
        "2.  Test Automation Environment",
        "Isolated and stable, so daily test results stay meaningful.",
    ))
    out.append(Paragraph(
        "Three test suites (functional, integration, end-to-end) run "
        "nightly against staging, plus a weekly load suite. Their value "
        "depends on the environments staying predictable from one run to "
        "the next.",
        BODY_LEFT,
    ))

    out.append(Paragraph(
        "Staging Environment &mdash; Manual &amp; Functional QA", H2))
    out.append(bullet(
        "A permanent, documented URL that is not silently moved between "
        "sprints. The test scripts hard-code the staging endpoint; a change "
        "without notice breaks every regression run that night."
    ))
    out.append(bullet(
        "Persistent test-data accounts with non-rotating credentials. When "
        "test accounts are reset, the suite fails overnight and we only "
        "find out the next morning."
    ))

    out.append(Paragraph(
        "Performance Sandbox &mdash; Load Testing", H2))
    out.append(bullet(
        "A dedicated load-test target that is separate from the staging "
        "environment used by manual QA. Today they share, which means the "
        "weekly Locust run can slow down whatever testing the QA team is "
        "doing on the same box."
    ))
    return out


def section_three():
    out = []
    out.extend(section_heading(
        "3.  Project Management &amp; Communication",
        "The pipes that carry requirements in and tasks out.",
    ))
    out.append(Paragraph(
        "The agent ingests requirements from email, Teams channels, and "
        "meeting recordings, splits them into ~3-hour atomic tasks, and "
        "pushes them to a backlog. Two pieces close that loop.",
        BODY_LEFT,
    ))

    out.append(Paragraph("Centralized Backlog", H2))
    out.append(bullet(
        "A single project-management tool that holds all user stories and "
        "technical tasks as the source of truth. Today the agent pushes "
        "3-hour atomic tasks to GitLab. The ask is that we agree this is "
        "the single backlog and do not fragment work across multiple "
        "tools &mdash; fragmentation defeats the agent's dedup logic."
    ))

    out.append(Paragraph("Power Automate License + Flow", H2))
    out.append(bullet(
        "A Power Automate workflow that forwards Microsoft Teams channel "
        "posts into the IMAP allowlist that the agent already polls."
    ))
    out.append(bullet(
        "The agent does not call the Microsoft Graph API directly. Power "
        "Automate is the bridge &mdash; without it, requirements raised in "
        "Teams never reach the agent's intake pipeline."
    ))
    return out


def closing():
    return [
        KeepTogether([
            Paragraph(
                "<b>The logic for the AI-driven workflows (Requirement "
                "Management and Test Automation) is fully developed.</b> "
                "Securing these infrastructure prerequisites is the final "
                "step required to move from the development phase to "
                "active, daily operations.",
                CLOSING,
            ),
            Paragraph(
                "Happy to walk through any of this in a short conversation.",
                SIGNOFF,
            ),
            Paragraph("&mdash; Mohammad Kamrul Hasan", SIGNOFF),
        ]),
    ]


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def build(out_path: Path):
    doc = BaseDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title="NAPCO Nucleus AI Agent — Infrastructure & Access Requirements",
        author="Mohammad Kamrul Hasan",
        subject="Infrastructure prerequisites for production operation",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  doc.width, doc.height, id="main")
    doc.addPageTemplates([
        PageTemplate(id="content", frames=[frame], onPage=on_page),
    ])

    story = []
    story.extend(header_block())
    story.extend(intro())
    story.extend(section_one())
    story.extend(section_two())
    story.extend(section_three())
    story.extend(closing())

    doc.build(story)


def main():
    here = Path(__file__).resolve().parent
    repo = here.parent
    out_dir = repo / "docs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "NAPCO-Nucleus-Infrastructure-Requirements.pdf"
    build(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
