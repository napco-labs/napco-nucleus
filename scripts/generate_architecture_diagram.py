"""Render the NAPCO Nucleus + Digital Deputy architectural overview as a PDF.

Run:
    py -3 scripts/generate_architecture_diagram.py
Output:
    docs/Architecture-Overview.pdf
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as canvas_mod
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT_PATH = ROOT / "docs" / "Architecture-Overview.pdf"

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm

# ────────────────────────────── styles ──────────────────────────────

styles = getSampleStyleSheet()

H1 = ParagraphStyle(
    name="H1", parent=styles["Heading1"],
    fontName="Helvetica-Bold", fontSize=18, leading=22,
    spaceBefore=0, spaceAfter=8, textColor=colors.HexColor("#0F2547"),
)
H2 = ParagraphStyle(
    name="H2", parent=styles["Heading2"],
    fontName="Helvetica-Bold", fontSize=13, leading=17,
    spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#0F2547"),
)
BODY = ParagraphStyle(
    name="Body", parent=styles["BodyText"],
    fontName="Helvetica", fontSize=10, leading=14,
    alignment=TA_LEFT, spaceAfter=6,
)
SMALL = ParagraphStyle(
    name="Small", parent=BODY,
    fontSize=9, leading=12, textColor=colors.HexColor("#555555"),
)
DIAGRAM = ParagraphStyle(
    name="Diagram", parent=styles["Code"],
    fontName="Courier", fontSize=8, leading=10,
    textColor=colors.HexColor("#0F2547"),
    backColor=colors.HexColor("#F5F8FC"),
    borderPadding=8, leftIndent=0, rightIndent=0,
    spaceBefore=4, spaceAfter=8,
)


# ─────────────────────────── header / footer ────────────────────────

def _on_page(canvas: canvas_mod.Canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(colors.HexColor("#0F2547"))
    canvas.drawString(MARGIN, PAGE_H - MARGIN + 6 * mm,
                      "NAPCO Nucleus + Digital Deputy — Architectural Overview")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN + 6 * mm,
                           "2026-04-26")
    canvas.setStrokeColor(colors.HexColor("#CFD8E3"))
    canvas.setLineWidth(0.4)
    canvas.line(MARGIN, PAGE_H - MARGIN + 4 * mm,
                PAGE_W - MARGIN, PAGE_H - MARGIN + 4 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawCentredString(PAGE_W / 2, MARGIN - 6 * mm, f"page {doc.page}")
    canvas.restoreState()


# ───────────────────────────── content ──────────────────────────────

SHARED_DIAGRAM = """\
                    ┌──────────────────────────────────────────────┐
                    │  GitHub Actions  (self-hosted Windows runner)│
                    │  cron schedules + workflow_dispatch          │
                    └──────────────────┬───────────────────────────┘
                                       │ py -3 agent.py --task <name>
                                       ▼
              ┌────────────────────────────────────────────────────┐
              │                    agent.py                        │
              │  load .env (override=True) — build MCP server —    │
              │  load prompts/system.md + prompts/<task>.md —      │
              │  run ONE Claude Agent SDK turn — exit              │
              └─────┬────────────────────┬──────────────┬──────────┘
                    │                    │              │
                    │ uses               │ via          │ exposes
                    ▼                    ▼              ▼
          ┌──────────────────┐  ┌───────────────┐  ┌─────────────────┐
          │ Claude Agent SDK │  │  prompts/     │  │  tools/  (MCP)  │
          │  (Python)        │  │  system.md    │  │                 │
          └────────┬─────────┘  │  + per-task   │  │  memory         │
                   │            │  .md files    │  │  requirements   │
                   ▼            └───────────────┘  │  tests   (NN)   │
          ┌──────────────────┐                     │  files          │
          │ Claude Code CLI  │  ◄── reasoning ──   │  git            │
          │ (locally logged  │      happens here   │  report         │
          │  in — Claude Max │                     └────────┬────────┘
          │  subscription;   │                              │
          │  NO API KEY)     │                              │ side-effects
          └──────────────────┘                              │
                                                            ▼
                                                   ┌─────────────────┐
                                                   │  memory.py      │
                                                   │  SQLite + FTS5  │
                                                   │  *_memory.db    │
                                                   │  (committed)    │
                                                   └─────────────────┘
                                                            │
                                                            │ also reaches
                                                            ▼
                                            ┌──────────────────────────┐
                                            │  External systems        │
                                            │  (per-project below)     │
                                            └──────────────────────────┘
"""

NN_DIAGRAM = """\
                           tools/
                             │
            ┌────────────────┼─────────────────────┬─────────────┐
            ▼                ▼                     ▼             ▼
     requirements/        tests/                files/         report/
            │                │                     │             │
   ┌────────┼─────────┐      │ shells / imports    │             │
   ▼        ▼         ▼      ▼                     ▼             ▼
 IMAP    Google     GitLab  ┌─────────────────────┐    SMTP    Teams
(Gmail)  Drive +    (issue  │ Sibling projects:   │  (Gmail)  webhook
         Groq       create) │ — MVP-Access-API-   │  ▼  ▼     (optional)
         Whisper            │   Test (Python)     │  team email
                            │ — MVP-Access-E2E-   │
                            │   Test (Playwright) │
                            │ — Easy-E2E (PW)     │
                            │ — Release-Test (PW) │
                            └─────────────────────┘
"""

DD_DIAGRAM = """\
                           tools/
                             │
            ┌────────────────┼──────────────────┬─────────────┐
            ▼                ▼                  ▼             ▼
        search/           apply/             track/         report/
       (web fetch)      (compose +         (Sheets writer)    │
            │            send email)            │             ▼
            ▼                │                  ▼          SMTP × 2
    Companies / job          ▼            Google Sheets    identities
    boards (HTTPS)        SMTP × 2        (deputy tracker  (BUSINESS_*
                          (BUSINESS or     for jobs/        + PERSONAL_*)
                           PERSONAL        importers/         ▼  ▼
                           identity)       recruiters)       team email
                              │                              + your inbox
                              ▼
                     IMAP poll for replies
                     (same Gmail accounts)
"""


def build():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT_PATH),
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 6 * mm, bottomMargin=MARGIN + 6 * mm,
        title="NAPCO Nucleus + Digital Deputy — Architectural Overview",
        author="NAPCO Nucleus",
    )
    frame = Frame(
        MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN - 6 * mm,
        id="main", showBoundary=0,
    )
    doc.addPageTemplates([PageTemplate(id="Default", frames=[frame], onPage=_on_page)])

    story: list = []

    # ── Title block
    story.append(Paragraph(
        "NAPCO Nucleus &amp; Digital Deputy",
        ParagraphStyle("Title", parent=H1, fontSize=22, leading=28,
                       spaceAfter=4, textColor=colors.HexColor("#0F2547")),
    ))
    story.append(Paragraph(
        "Architectural Overview",
        ParagraphStyle("Subtitle", parent=H1, fontSize=14, leading=18,
                       spaceAfter=12, textColor=colors.HexColor("#506B8E")),
    ))
    story.append(Paragraph(
        "Two Claude-Agent-SDK projects, one architecture. "
        "This document captures the layout that NN and DD both follow, "
        "then notes where they diverge — by domain, external systems, and "
        "tools — so a third agent built to the same pattern can be stood up "
        "by swapping only the tool surface and prompts.",
        BODY,
    ))
    story.append(Spacer(1, 4 * mm))

    # ── Section 1: shared architecture
    story.append(Paragraph("1. Shared architecture", H2))
    story.append(Paragraph(
        "Both projects follow the same four-layer shape: a GitHub Actions "
        "trigger fires <font face='Courier' size='9'>agent.py</font>, which "
        "loads a prompt, builds an MCP tool server, and runs a single "
        "Claude Agent SDK turn. Claude reasons; tools wrap external I/O. "
        "Memory is SQLite-with-FTS5, committed to the repo so state travels "
        "with <font face='Courier' size='9'>git clone</font>.",
        BODY,
    ))
    story.append(Preformatted(SHARED_DIAGRAM, DIAGRAM))
    story.append(Paragraph("Principles both projects share:", H2))
    bullets = [
        "One <font face='Courier' size='9'>.env</font> at the project root "
        "is the single source of truth for secrets (Digital-Deputy-style).",
        "One <font face='Courier' size='9'>google-credentials.json</font> "
        "at the project root holds the Google service-account key.",
        "Claude Code CLI does the LLM work, authenticated via your Claude "
        "Max subscription. No <font face='Courier' size='9'>ANTHROPIC_API_KEY</font> "
        "is set anywhere.",
        "The memory database is committed to the repo, so cloning the "
        "project on a new machine instantly recovers prior context.",
        "Algorithmic work lives in PROMPTS, not Python. Tools wrap I/O "
        "(call an API, read a file, run a command). Reasoning, "
        "classification, summarization — all done by Claude in the prompt.",
    ]
    for b in bullets:
        story.append(Paragraph(f"&bull;&nbsp;&nbsp;{b}", BODY))

    # ── Section 2: divergence table
    story.append(PageBreak())
    story.append(Paragraph("2. Where DD and NN diverge", H2))
    story.append(Paragraph(
        "Same skeleton; different muscles. The table below lists every "
        "concern that differs and what each project does instead.",
        BODY,
    ))

    table_data = [
        ["Concern", "Digital Deputy (DD)", "NAPCO Nucleus (NN)"],
        ["Domain",
         "Job search + SATUMM business outreach + recruiter tracking",
         "Test automation + project management for MVP Access"],
        ["Workflows",
         "6: daily-report, find-importers, find-exporters, find-recruiters, job-search, monthly-archive",
         "8: daily-report, requirement-management, api-functional-test, api-integration-test, api-load-test, e2e-test, mvpaccess-cicd, probe-runner"],
        ["Prompts", "system.md + 5 task prompts", "system.md + 6 task prompts"],
        ["Tools",
         "memory, search, apply, track, guards, report",
         "memory, requirements, tests, files, git, report"],
        ["Outbound email",
         "SMTP × 2 identities (BUSINESS_* SATUMM, PERSONAL_* jobs)",
         "SMTP × 1 identity (NAPCO Nucleus <khasan@ael-bd.com>)"],
        ["Inbound email", "IMAP for reply polling", "IMAP for requirement intake"],
        ["Structured data",
         "Google Sheets (sheets.py)",
         "Google Drive folder (recordings + PDFs)"],
        ["Issue tracker", "—", "GitLab (gitlab_client.py)"],
        ["AI services",
         "Claude only (via local CLI)",
         "Claude (CLI) + Groq Whisper (audio→text)"],
        ["Side-projects",
         "None — DD owns its own work",
         "4 sibling test projects: API-Test (Python import via sys.path), 3× E2E (Playwright via subprocess)"],
        ["Memory DB", "deputy_memory.db", "nucleus_memory.db"],
        ["Trigger cadence",
         "Business hours + daily + monthly",
         "Every 2h + daily + weekly"],
    ]

    col_widths = [38 * mm, 65 * mm, 65 * mm]
    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F2547")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F5F8FC")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CFD8E3")),
    ]))
    story.append(tbl)

    # ── Section 3: NN external dependencies
    story.append(PageBreak())
    story.append(Paragraph("3. NAPCO Nucleus — external dependency map", H2))
    story.append(Paragraph(
        "What NN's six tool submodules actually reach out to. The four "
        "sibling test projects are reached two ways: API-Test via Python "
        "<font face='Courier' size='9'>sys.path</font> injection (NN imports "
        "its functions and runs them in-process); the three E2E projects "
        "via <font face='Courier' size='9'>subprocess.run([\"npx\", \"playwright\", \"test\"])</font>.",
        BODY,
    ))
    story.append(Preformatted(NN_DIAGRAM, DIAGRAM))

    # ── Section 4: DD external dependencies
    story.append(Paragraph("4. Digital Deputy — external dependency map", H2))
    story.append(Paragraph(
        "What DD's tools reach out to. DD's signature is the dual-identity "
        "outbound email: the same agent runs as "
        "<font face='Courier' size='9'>contact@satumm.com</font> for trade "
        "outreach (find-importers, find-exporters) and as "
        "<font face='Courier' size='9'>titucse@gmail.com</font> for the "
        "personal job search (find-recruiters, job-search), with separate "
        "send-rate caps and identity headers.",
        BODY,
    ))
    story.append(Preformatted(DD_DIAGRAM, DIAGRAM))

    # ── Section 5: closing
    story.append(Paragraph("5. What this means in practice", H2))
    story.append(Paragraph(
        "Structurally, the two projects are interchangeable. Same auth "
        "pattern, same memory pattern, same trigger pattern, same Claude "
        "reasoning + Python I/O division. The only project-specific code "
        "is the <font face='Courier' size='9'>tools/</font> submodules and "
        "the <font face='Courier' size='9'>prompts/</font> markdown files. "
        "When a third agent comes along, you copy the skeleton and only "
        "swap those two folders.",
        BODY,
    ))
    story.append(Paragraph(
        "The current refactor (commit "
        "<font face='Courier' size='9'>5133ab9</font>) deletes 638 net "
        "lines of Python in NN by moving five algorithmic tools "
        "(failure RCA classifier, standup formatter, regression diff, test "
        "inventory, known-bug list) out of code and into prompts. Claude "
        "now reads the same JSON files those tools used to scan and "
        "reasons over them directly. Behavior changes by editing markdown, "
        "not Python.",
        BODY,
    ))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "Generated 2026-04-26. Source: scripts/generate_architecture_diagram.py",
        SMALL,
    ))

    doc.build(story)
    return OUT_PATH


if __name__ == "__main__":
    out = build()
    print(f"Wrote {out}")
