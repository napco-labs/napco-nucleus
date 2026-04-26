"""Render the NAPCO Nucleus architectural overview as a PDF.

Card-based layout. Each section is a small colored block with a
header bar and a white body. Single column, tight spacing, scannable.

Run:
    py -3 scripts/generate_nn_architecture.py
Output:
    docs/NN-Architecture.pdf
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as canvas_mod
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT_PATH = ROOT / "docs" / "NN-Architecture.pdf"

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# Color palette
NAVY    = colors.HexColor("#1F4E79")
TEAL    = colors.HexColor("#2E8A8A")
CORAL   = colors.HexColor("#E07856")
GREEN   = colors.HexColor("#4A7A4A")
GOLD    = colors.HexColor("#C9962B")
PURPLE  = colors.HexColor("#6A4C93")
INK     = colors.HexColor("#222222")
MUTED   = colors.HexColor("#6B7785")
SOFT    = colors.HexColor("#F5F7FA")
WHITE   = colors.white
RULE    = colors.HexColor("#D5DCE5")

# Paragraph styles
TITLE = ParagraphStyle(
    name="Title", fontName="Helvetica-Bold", fontSize=24, leading=28,
    textColor=NAVY, alignment=TA_LEFT, spaceAfter=2,
)
SUBTITLE = ParagraphStyle(
    name="Subtitle", fontName="Helvetica", fontSize=12, leading=15,
    textColor=MUTED, alignment=TA_LEFT, spaceAfter=4,
)
BYLINE = ParagraphStyle(
    name="Byline", fontName="Helvetica-Bold", fontSize=10, leading=13,
    textColor=NAVY, alignment=TA_LEFT, spaceAfter=10,
)
CARD_HEAD = ParagraphStyle(
    name="CardHead", fontName="Helvetica-Bold", fontSize=11, leading=14,
    textColor=WHITE, alignment=TA_LEFT,
)
CARD_BODY = ParagraphStyle(
    name="CardBody", fontName="Helvetica", fontSize=9.5, leading=13,
    textColor=INK, alignment=TA_LEFT, spaceAfter=4,
)
BULLET = ParagraphStyle(
    name="Bullet", fontName="Helvetica", fontSize=9.5, leading=13,
    textColor=INK, leftIndent=10, bulletIndent=0, spaceAfter=2,
)
NUMBER_BIG = ParagraphStyle(
    name="NumBig", fontName="Helvetica-Bold", fontSize=22, leading=24,
    textColor=NAVY, alignment=TA_CENTER,
)
NUMBER_LBL = ParagraphStyle(
    name="NumLbl", fontName="Helvetica", fontSize=8, leading=10,
    textColor=MUTED, alignment=TA_CENTER,
)
STEP_NUM = ParagraphStyle(
    name="StepNum", fontName="Helvetica-Bold", fontSize=12, leading=14,
    textColor=WHITE, alignment=TA_CENTER,
)
STEP_TITLE = ParagraphStyle(
    name="StepTitle", fontName="Helvetica-Bold", fontSize=10.5, leading=13,
    textColor=NAVY, alignment=TA_LEFT, spaceAfter=2,
)
STEP_BODY = ParagraphStyle(
    name="StepBody", fontName="Helvetica", fontSize=9, leading=12,
    textColor=INK, alignment=TA_LEFT,
)
QUOTE = ParagraphStyle(
    name="Quote", fontName="Helvetica-Oblique", fontSize=10.5, leading=14,
    textColor=NAVY, alignment=TA_LEFT, leftIndent=4, spaceAfter=6,
)


def _on_page(canvas: canvas_mod.Canvas, doc):
    canvas.saveState()
    # Top accent stripe
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - 4, PAGE_W, 4, stroke=0, fill=1)
    # Footer
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN, 8 * mm,
                      "NAPCO Nucleus  |  Mohammad Kamrul Hasan, AI-Augmented QA Architect")
    canvas.drawRightString(PAGE_W - MARGIN, 8 * mm, f"page {doc.page}")
    canvas.restoreState()


def card(header_text: str, body_flowables, header_color=NAVY) -> Table:
    """A bordered card: colored header bar with white text, white body
    with light border. body_flowables can be one Paragraph or a list."""
    if not isinstance(body_flowables, list):
        body_flowables = [body_flowables]
    inner = Table(
        [[Paragraph(header_text, CARD_HEAD)],
         [body_flowables]],
        colWidths=[CONTENT_W],
    )
    inner.setStyle(TableStyle([
        # Header row
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("LEFTPADDING", (0, 0), (-1, 0), 10),
        ("RIGHTPADDING", (0, 0), (-1, 0), 10),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        # Body row
        ("BACKGROUND", (0, 1), (-1, 1), WHITE),
        ("LEFTPADDING", (0, 1), (-1, 1), 10),
        ("RIGHTPADDING", (0, 1), (-1, 1), 10),
        ("TOPPADDING", (0, 1), (-1, 1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, RULE),
    ]))
    return inner


def metric_box(value: str, label: str, color) -> Table:
    """A small metric box: big number on top, label below, colored top border."""
    t = Table(
        [[Paragraph(value, NUMBER_BIG)],
         [Paragraph(label, NUMBER_LBL)]],
        rowHeights=[16 * mm, 6 * mm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT),
        ("LINEABOVE", (0, 0), (-1, 0), 3, color),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("VALIGN", (0, 1), (-1, 1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def metrics_row(items) -> Table:
    """A horizontal row of metric boxes."""
    cells = [metric_box(v, l, c) for v, l, c in items]
    n = len(cells)
    col_w = (CONTENT_W - (n - 1) * 4) / n
    t = Table([cells], colWidths=[col_w] * n)
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def step_box(num: int, title: str, body: str, accent) -> Table:
    """A numbered step block: circle-ish badge on left, title + body on right."""
    badge = Table([[Paragraph(str(num), STEP_NUM)]],
                  colWidths=[8 * mm], rowHeights=[8 * mm])
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), accent),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    text = [Paragraph(title, STEP_TITLE), Paragraph(body, STEP_BODY)]
    t = Table([[badge, text]], colWidths=[12 * mm, CONTENT_W - 12 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def value_card(title: str, body: str, accent) -> Table:
    """One of the closing 'value delivered' cards."""
    t = Table(
        [[Paragraph(title, ParagraphStyle("vcT", parent=CARD_HEAD, fontSize=10))],
         [Paragraph(body, CARD_BODY)]],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("BACKGROUND", (0, 1), (-1, 1), SOFT),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, 1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
    ]))
    return t


def value_row(items) -> Table:
    cells = [value_card(t, b, c) for t, b, c in items]
    n = len(cells)
    col_w = (CONTENT_W - (n - 1) * 4) / n
    t = Table([cells], colWidths=[col_w] * n)
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def build():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT_PATH),
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 4, bottomMargin=MARGIN,
        title="NAPCO Nucleus Architecture",
        author="Mohammad Kamrul Hasan",
    )
    frame = Frame(MARGIN, MARGIN, CONTENT_W, PAGE_H - 2 * MARGIN - 4,
                  id="main", showBoundary=0,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="Default", frames=[frame], onPage=_on_page)])

    story: list = []

    # ── Title block
    story.append(Paragraph("NAPCO Nucleus", TITLE))
    story.append(Paragraph("An AI agent platform for MVP Access engineering", SUBTITLE))
    story.append(Paragraph(
        "Built by Mohammad Kamrul Hasan &nbsp;&middot;&nbsp; "
        "AI-Augmented QA Architect &nbsp;&middot;&nbsp; April 2026",
        BYLINE,
    ))

    # ── Tagline card
    story.append(card(
        "WHAT IT IS",
        Paragraph(
            "An AI agent that reads our client emails and meeting recordings "
            "every two hours, files them as tasks in GitLab, runs our test "
            "suites every night, classifies the failures, and ships two "
            "consolidated emails every morning. A short executive summary "
            "for leadership and a detailed test report for the team. Real "
            "production deployment, not a prototype.",
            CARD_BODY,
        ),
        header_color=NAVY,
    ))
    story.append(Spacer(1, 6))

    # ── Metrics row
    story.append(metrics_row([
        ("9",     "WORKFLOWS",    NAVY),
        ("31",    "MCP TOOLS",    TEAL),
        ("2",     "DIMENSIONS",   CORAL),
        ("2",     "DAILY EMAILS", GREEN),
        ("$200",  "PER MONTH",    GOLD),
    ]))
    story.append(Spacer(1, 8))

    # ── Two dimensions
    story.append(card(
        "TWO OPERATIONAL DIMENSIONS",
        [
            Paragraph(
                "<b>1. Project Management.</b> Pulls client requirements out "
                "of email and Drive recordings every two hours. Splits each "
                "one into 3-hour tasks. Files them in GitLab with two-layer "
                "dedup so re-runs never duplicate.",
                CARD_BODY,
            ),
            Spacer(1, 4),
            Paragraph(
                "<b>2. Test Automation.</b> Runs API Functional, API "
                "Integration, API Load, and MVP Access E2E suites on "
                "schedule. Classifies failures as real bug, regression, "
                "flaky, environment, or known issue. Composes one Daily "
                "Report PDF every morning at 09:00 BDT.",
                CARD_BODY,
            ),
        ],
        header_color=TEAL,
    ))
    story.append(Spacer(1, 6))

    # ── How it works (steps)
    story.append(card(
        "HOW ONE RUN WORKS",
        [
            step_box(1, "Trigger fires",
                     "GitHub Actions cron or workflow_dispatch starts the run on the self-hosted Windows runner.",
                     NAVY),
            step_box(2, "agent.py boots",
                     "Loads .env with override semantics, builds the MCP server, loads the system prompt plus the task prompt.",
                     TEAL),
            step_box(3, "Claude reasons",
                     "The Claude Agent SDK opens a session against the locally-installed Claude Code CLI. No API key. Cost is fixed monthly.",
                     CORAL),
            step_box(4, "Tools run",
                     "Claude calls MCP tools as needed. Each tool wraps one external system: IMAP, Drive, GitLab, Newman, pytest, Playwright, Locust, SMTP.",
                     GREEN),
            step_box(5, "Memory persists",
                     "Activity log, requirements seen, test history all written to nucleus_memory.db (SQLite plus FTS5). The DB is committed to the repo.",
                     GOLD),
            step_box(6, "Process exits",
                     "One Claude turn per process. Clean shutdown. The next workflow starts with full memory of every prior run.",
                     PURPLE),
        ],
        header_color=NAVY,
    ))

    story.append(PageBreak())

    # ── Page 2: workflows table
    story.append(card(
        "THE EIGHT WORKFLOWS",
        [
            Paragraph(
                "Each one runs on its own schedule and writes to memory. "
                "The Daily Report reads memory and composes one consolidated "
                "picture every morning.",
                CARD_BODY,
            ),
        ],
        header_color=CORAL,
    ))
    story.append(Spacer(1, 4))

    wf_data = [
        ["#", "Workflow", "Schedule", "What it does"],
        ["1", "API Functional Test", "02:00 BDT daily",
         "Newman and Postman collection across the API surface."],
        ["2", "API Integration Test", "02:00 BDT daily",
         "pytest integration suite with regression diff against prior runs."],
        ["3", "API Load Test", "02:00 BDT daily",
         "Locust multi-tier from 10 to 10,000 users with server-recovery cooldowns."],
        ["4", "MVP Access E2E Test", "02:00 BDT daily",
         "Playwright full suite. Failure screenshots embedded in the PDF."],
        ["5", "Daily Report (Detailed)", "09:00 BDT daily",
         "Composes the 4-test detailed PDF and emails it to the FULL TEAM."],
        ["6", "Daily Report (Summary)", "09:30 BDT daily",
         "6-block executive summary (4 tests + CICD + Runner) to LEADERSHIP."],
        ["7", "Requirement Management", "Every 2h business hours",
         "IMAP plus Drive ingest. Splits requirements into 3h tasks. Files in GitLab."],
        ["8", "MVPAccess CICD", "22:00 BDT daily",
         "TFS pull, MSBuild Release, IIS deploy via UNC, health check, memory log."],
        ["9", "Probe Runner Filesystem", "Manual",
         "Diagnostic. Inspects runner state during triage."],
    ]
    col_widths = [7 * mm, 40 * mm, 32 * mm, 101 * mm]
    tbl = Table(wf_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, SOFT]),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
    ]))
    story.append(tbl)

    story.append(Spacer(1, 8))

    # ── 31 tools card
    story.append(card(
        "THE 31 MCP TOOLS",
        [
            Paragraph(
                "Every tool wraps one external system. Tools do not contain "
                "logic. Reasoning lives in the prompts.",
                CARD_BODY,
            ),
        ],
        header_color=PURPLE,
    ))
    story.append(Spacer(1, 4))

    tool_data = [
        ["Submodule", "N", "What it does"],
        ["memory",       "5", "Recall activity logs, search requirements, recall test runs, write memory rows."],
        ["requirements", "4", "Poll IMAP, ingest Drive recordings, read inbox, publish to GitLab."],
        ["tests",        "9", "Run Newman, pytest, Locust tiers, Playwright suites, single specs, health probes."],
        ["files",        "5", "List, read, write, edit files in sibling projects. Capture Playwright a11y snapshots."],
        ["git",          "3", "Diff, commit and push, recent commits across any project."],
        ["report",       "5", "Generate PDF, send email, post Teams card, tail logs, clean reports folder."],
    ]
    col_widths2 = [25 * mm, 12 * mm, 143 * mm]
    tbl2 = Table(tool_data, colWidths=col_widths2, repeatRows=1)
    tbl2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PURPLE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, SOFT]),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
    ]))
    story.append(tbl2)

    story.append(PageBreak())

    # ── Page 3: principles
    story.append(card(
        "ARCHITECTURAL PRINCIPLES",
        [
            Paragraph("•&nbsp;&nbsp;<b>Single source of truth for secrets.</b> One .env at the project root, gitignored. The agent never reaches into another project for credentials.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>No ANTHROPIC_API_KEY anywhere.</b> Reasoning runs through the local Claude Code CLI under a Claude Max subscription. Cost is fixed monthly, not per token.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Memory committed to the repo.</b> nucleus_memory.db lives in git. Cloning the project on a new machine instantly recovers prior context and dedup state.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Algorithms in prompts, not Python.</b> Tools wrap I/O only. Classification, summarization, and regression analysis happen in markdown that Claude executes.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>One Claude turn per process.</b> agent.py loads, runs ONE turn, exits. Clean memory, no leaked state, easy to reason about.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Two consolidated emails per day.</b> At 09:00 BDT the detailed test report goes to the full team. At 09:30 BDT a 7-block executive summary goes to leadership.", BULLET),
        ],
        header_color=GREEN,
    ))
    story.append(Spacer(1, 8))

    # ── Tech stack card
    story.append(card(
        "TECH STACK",
        [
            Paragraph(
                "<b>Reasoning:</b> Claude Agent SDK, Claude Code CLI, Claude Max subscription. "
                "<b>Runtime:</b> Python 3.13, GitHub Actions on a self-hosted Windows VM runner. "
                "<b>Memory:</b> SQLite with FTS5 fuzzy search. "
                "<b>Reporting:</b> Reportlab. "
                "<b>Tests it orchestrates:</b> Newman, pytest, Locust, Playwright. "
                "<b>External integrations:</b> IMAP and SMTP (Gmail), Google Drive API, Groq Whisper, GitLab REST v4, Microsoft Teams webhook.",
                CARD_BODY,
            ),
        ],
        header_color=GOLD,
    ))
    story.append(Spacer(1, 8))

    # ── Value delivered (3 cards in a row)
    story.append(Paragraph("WHAT THIS DELIVERS", ParagraphStyle(
        "ValueHead", fontName="Helvetica-Bold", fontSize=12, leading=14,
        textColor=NAVY, spaceAfter=6,
    )))
    story.append(value_row([
        ("FOR THE TEAM",
         "Client requirements arrive in GitLab within two hours. Test results land in one morning email instead of six fragments scattered through the night.",
         NAVY),
        ("FOR LEADERSHIP",
         "One source of truth for what changed, what tested, what regressed, what shipped, what the client asked for. Every morning. Nothing fabricated.",
         TEAL),
        ("FOR THE QA ROLE",
         "A working demonstration that one architect who knows how to direct AI ships production infrastructure that previously required a senior dev team.",
         CORAL),
    ]))

    story.append(Spacer(1, 10))

    # ── Closing line
    story.append(card(
        "THE THESIS",
        Paragraph(
            "QA architect plus AI equals senior developer team output. "
            "NAPCO Nucleus is the proof.",
            QUOTE,
        ),
        header_color=PURPLE,
    ))

    doc.build(story)
    return OUT_PATH


if __name__ == "__main__":
    out = build()
    print(f"Wrote {out}")
