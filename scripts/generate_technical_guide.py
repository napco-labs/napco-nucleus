"""Render the complete technical guide for NAPCO Nucleus as a PDF.

Audience: engineering team. Covers architecture, the single-agent
execution model, the Python orchestrator, the Claude Agent SDK
integration, the MCP tool surface, the memory layer, prompts,
third-party integrations, the CI/CD execution model, the workflow
catalog, recipes for adding new workflows and tools, plus benefits,
demerits, and operational guardrails.

Run:
    py -3 scripts/generate_technical_guide.py
Output:
    docs/NAPCO-Nucleus-Technical-Guide.pdf
"""
from __future__ import annotations

from pathlib import Path

from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
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
OUT_PATH = ROOT / "docs" / "NAPCO-Nucleus-Technical-Guide.pdf"

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# Palette
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
CODE_BG = colors.HexColor("#1E2A38")

TITLE = ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=18,
                        leading=22, textColor=NAVY, alignment=TA_LEFT,
                        spaceAfter=4)
SUBTITLE = ParagraphStyle("Subtitle", fontName="Helvetica", fontSize=12,
                           leading=15, textColor=MUTED, alignment=TA_LEFT,
                           spaceAfter=10)
CREDIT_LBL = ParagraphStyle("CreditLbl", fontName="Helvetica", fontSize=8.5,
                             leading=11, textColor=MUTED, alignment=TA_LEFT,
                             spaceAfter=1)
CREDIT_NAME = ParagraphStyle("CreditName", fontName="Helvetica-Bold",
                              fontSize=12, leading=15, textColor=NAVY,
                              alignment=TA_LEFT, spaceAfter=0)
CREDIT_ROLE = ParagraphStyle("CreditRole", fontName="Helvetica", fontSize=9.5,
                              leading=12, textColor=INK, alignment=TA_LEFT,
                              spaceAfter=10)
H1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=16,
                     leading=19, textColor=NAVY, spaceBefore=2, spaceAfter=6)
H2 = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=12,
                     leading=15, textColor=NAVY, spaceBefore=4, spaceAfter=4)
CARD_HEAD = ParagraphStyle("CardHead", fontName="Helvetica-Bold", fontSize=11,
                            leading=14, textColor=WHITE)
CARD_BODY = ParagraphStyle("CardBody", fontName="Helvetica", fontSize=9.5,
                            leading=13, textColor=INK, spaceAfter=4)
BULLET = ParagraphStyle("Bullet", fontName="Helvetica", fontSize=9.5,
                         leading=13, textColor=INK, leftIndent=10,
                         bulletIndent=0, spaceAfter=2)
SMALL = ParagraphStyle("Small", fontName="Helvetica", fontSize=8.5,
                        leading=11, textColor=INK)
SMALL_MUTED = ParagraphStyle("SmallMuted", fontName="Helvetica", fontSize=8,
                              leading=10, textColor=MUTED)
NUMBER_BIG = ParagraphStyle("NumBig", fontName="Helvetica-Bold", fontSize=22,
                             leading=24, textColor=NAVY, alignment=TA_CENTER)
NUMBER_LBL = ParagraphStyle("NumLbl", fontName="Helvetica", fontSize=8,
                             leading=10, textColor=MUTED, alignment=TA_CENTER)
STEP_NUM = ParagraphStyle("StepNum", fontName="Helvetica-Bold", fontSize=12,
                           leading=14, textColor=WHITE, alignment=TA_CENTER)
STEP_TITLE = ParagraphStyle("StepTitle", fontName="Helvetica-Bold",
                             fontSize=10.5, leading=13, textColor=NAVY,
                             spaceAfter=2)
STEP_BODY = ParagraphStyle("StepBody", fontName="Helvetica", fontSize=9,
                            leading=12, textColor=INK)
CODE = ParagraphStyle("Code", fontName="Courier", fontSize=8.2, leading=10.5,
                       textColor=WHITE, alignment=TA_LEFT, leftIndent=4,
                       rightIndent=4, spaceBefore=2, spaceAfter=2)


# ── page chrome ─────────────────────────────────────────────────────

def _on_page(canvas: canvas_mod.Canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - 4, PAGE_W, 4, stroke=0, fill=1)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN, 8 * mm,
                      "NAPCO Nucleus  |  Technical Guide  |  Mohammad Kamrul Hasan")
    canvas.drawRightString(PAGE_W - MARGIN, 8 * mm, f"page {doc.page}")
    canvas.restoreState()


# ── primitives ──────────────────────────────────────────────────────

def card(header_text: str, body_flowables, header_color=NAVY) -> Table:
    if not isinstance(body_flowables, list):
        body_flowables = [body_flowables]
    inner = Table(
        [[Paragraph(header_text, CARD_HEAD)],
         [body_flowables]],
        colWidths=[CONTENT_W],
    )
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("LEFTPADDING", (0, 0), (-1, 0), 10),
        ("RIGHTPADDING", (0, 0), (-1, 0), 10),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
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
    t = Table([[Paragraph(value, NUMBER_BIG)],
               [Paragraph(label, NUMBER_LBL)]],
              rowHeights=[16 * mm, 6 * mm])
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


def step_box(num, title, body, accent):
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


def code_block(text: str) -> Table:
    para = Preformatted(text, CODE)
    t = Table([[para]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.3, CODE_BG),
    ]))
    return t


_KV_HDR_STYLE = ParagraphStyle("KvHdr", fontName="Helvetica-Bold", fontSize=9,
                                leading=11, textColor=WHITE)
_KV_CELL_STYLE = ParagraphStyle("KvCell", fontName="Helvetica", fontSize=8.5,
                                 leading=11, textColor=INK)


def kv_table(rows, header_color=NAVY, col_widths=None):
    if col_widths is None:
        col_widths = [CONTENT_W * 0.32, CONTENT_W * 0.68]

    # Wrap string cells as Paragraphs so long text wraps inside its
    # column instead of overflowing into neighboring cells.
    wrapped = []
    for i, row in enumerate(rows):
        style = _KV_HDR_STYLE if i == 0 else _KV_CELL_STYLE
        wrapped.append([
            Paragraph(c, style) if isinstance(c, str) else c
            for c in row
        ])

    tbl = Table(wrapped, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, SOFT]),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
    ]))
    return tbl


# ── visual diagrams ─────────────────────────────────────────────────

def _box(d, x, y, w, h, fill, label, sublabel=None,
         text_color=WHITE, label_size=8.5, sublabel_size=7):
    d.add(Rect(x, y, w, h, fillColor=fill, strokeColor=fill, rx=2, ry=2))
    if sublabel:
        d.add(String(x + w / 2, y + h / 2 + 2, label,
                     fontName="Helvetica-Bold", fontSize=label_size,
                     fillColor=text_color, textAnchor="middle"))
        d.add(String(x + w / 2, y + h / 2 - 7, sublabel,
                     fontName="Helvetica", fontSize=sublabel_size,
                     fillColor=text_color, textAnchor="middle"))
    else:
        d.add(String(x + w / 2, y + h / 2 - 2, label,
                     fontName="Helvetica-Bold", fontSize=label_size,
                     fillColor=text_color, textAnchor="middle"))


def _arrow(d, x1, y1, x2, y2, color=MUTED, label=None):
    import math
    d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=1.1))
    angle = math.atan2(y2 - y1, x2 - x1)
    head = 4
    ax1 = x2 - head * math.cos(angle - math.pi / 7)
    ay1 = y2 - head * math.sin(angle - math.pi / 7)
    ax2 = x2 - head * math.cos(angle + math.pi / 7)
    ay2 = y2 - head * math.sin(angle + math.pi / 7)
    d.add(Polygon([x2, y2, ax1, ay1, ax2, ay2],
                  fillColor=color, strokeColor=color))
    if label:
        midx = (x1 + x2) / 2
        midy = (y1 + y2) / 2 + 3
        d.add(String(midx, midy, label, fontName="Helvetica",
                     fontSize=6.5, fillColor=color, textAnchor="middle"))


def component_diagram() -> Drawing:
    """Component map: agent.py at center, surrounded by the things it
    talks to. 2 columns × 3 rows around the center, with hard horizontal
    separation so nothing overlaps the center box."""
    H = 110 * mm
    d = Drawing(CONTENT_W, H)
    cx = CONTENT_W / 2
    cy = H / 2

    # Center: agent.py
    aw, ah = 54 * mm, 14 * mm
    _box(d, cx - aw / 2, cy - ah / 2, aw, ah, NAVY,
         "agent.py", "Python orchestrator", label_size=10, sublabel_size=7.5)

    # Surrounding nodes
    bw, bh = 50 * mm, 12 * mm

    # Horizontal node center is far enough that node edge clears center
    # box edge with a visible gap. CONTENT_W ≈ 180mm, so a column offset
    # of 60mm puts the left node x range ≈ [5, 55] and the center box
    # left edge at cx - 27 ≈ 63 — a 8mm gap.
    col_offset = 60 * mm
    row_offset = 36 * mm

    nodes = [
        # (col, row, color, label, sublabel)
        (-1,  1, TEAL,   ".env / config",       "secrets, paths, CLI override"),
        ( 1,  1, GOLD,   "Claude Agent SDK",    "ClaudeSDKClient + MCP server"),
        (-1,  0, PURPLE, "MCP server",          "31 tools, in-process"),
        ( 1,  0, GREEN,  "Prompts",             "system.md + <task>.md"),
        (-1, -1, CORAL,  "GitHub Actions",      "9 workflows, self-hosted"),
        ( 1, -1, NAVY,   "nucleus_memory.db",   "SQLite + FTS5, in git"),
    ]

    for col, row, color, lab, sub in nodes:
        ncx = cx + col * col_offset
        ncy = cy + row * row_offset
        _box(d, ncx - bw / 2, ncy - bh / 2, bw, bh, color, lab, sub)

        # Source: the node edge facing the center box.
        # Target: the matching edge of the center box.
        if row == 0:
            # Middle row → arrow is horizontal into the side of agent.py
            sx = ncx + bw / 2 if col < 0 else ncx - bw / 2
            sy = ncy
            tx = cx - aw / 2 if col > 0 else cx + aw / 2
            ty = cy
        else:
            # Top/bottom row → arrow goes from the inner corner of the
            # node down/up into the top/bottom edge of agent.py.
            sx = ncx + (bw / 2 if col < 0 else -bw / 2)
            sy = ncy - bh / 2 if row > 0 else ncy + bh / 2
            tx = cx + (-aw / 2 + 6 * mm if col < 0 else aw / 2 - 6 * mm)
            ty = cy + ah / 2 if row > 0 else cy - ah / 2
        _arrow(d, sx, sy, tx, ty, color=MUTED)

    return d


def execution_lifecycle() -> Drawing:
    """The universal lifecycle every workflow follows. Linear
    horizontal flow with 8 boxes."""
    H = 50 * mm
    d = Drawing(CONTENT_W, H)
    bw = (CONTENT_W - 7 * 2 * mm) / 8
    bh = 22 * mm
    y = H - bh - 6 * mm
    palette = [NAVY, TEAL, CORAL, GREEN, GOLD, PURPLE, NAVY, TEAL]
    steps = [
        ("Trigger",    "cron / dispatch"),
        ("Checkout",   "actions/checkout"),
        ("Install",    "pip install"),
        ("Boot",       "py agent.py"),
        ("SDK open",   "Claude session"),
        ("Loop",       "tool calls"),
        ("Persist",    "git commit"),
        ("Push",       "to main"),
    ]
    for i, ((title, sub), color) in enumerate(zip(steps, palette)):
        x = i * (bw + 2 * mm)
        _box(d, x, y, bw, bh, color, title, sub, label_size=9, sublabel_size=6.8)
        if i < len(steps) - 1:
            ax_from = x + bw
            ax_to   = x + bw + 2 * mm
            _arrow(d, ax_from, y + bh / 2, ax_to, y + bh / 2, color=MUTED)
    # Title strip below
    d.add(String(CONTENT_W / 2, 4 * mm,
                 "Universal lifecycle — every workflow follows this shape",
                 fontName="Helvetica-Oblique", fontSize=8.5,
                 fillColor=MUTED, textAnchor="middle"))
    return d


# ── content ─────────────────────────────────────────────────────────

def build():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT_PATH),
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 4, bottomMargin=MARGIN,
        title="NAPCO Nucleus — Technical Guide",
        author="Mohammad Kamrul Hasan",
    )
    frame = Frame(MARGIN, MARGIN, CONTENT_W, PAGE_H - 2 * MARGIN - 4,
                  id="main", showBoundary=0,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="Default", frames=[frame], onPage=_on_page)])

    s: list = []

    # ─── Page 1: Title + Executive summary ────────────────────────
    s.append(Paragraph(
        "NAPCO Nucleus: An Autonomous Intelligent Orchestrator", TITLE))
    s.append(Paragraph(
        "The Digital Deputy Framework for Enterprise QA &amp; Project Governance",
        SUBTITLE))
    s.append(Paragraph("Developed &amp; Engineered by:", CREDIT_LBL))
    s.append(Paragraph("Mohammad Kamrul Hasan", CREDIT_NAME))
    s.append(Paragraph(
        "AI-Augmented QA Architect &nbsp;|&nbsp; Adaptive Enterprise Limited",
        CREDIT_ROLE))
    s.append(card(
        "WHAT THIS DOCUMENT IS",
        Paragraph(
            "End-to-end technical reference for the NAPCO Nucleus AI agent. "
            "Covers the architectural pattern, the universal execution "
            "lifecycle, the Python orchestrator, the Claude Agent SDK "
            "integration, the MCP tool surface, the SQLite memory layer, "
            "every third-party integration, the CI/CD execution model, the "
            "9 workflows, recipes for adding new workflows and tools, plus "
            "concrete benefits and demerits. Written for engineers who will "
            "operate, debug, or extend the system.",
            CARD_BODY,
        ),
        header_color=NAVY,
    ))
    s.append(Spacer(1, 6))
    s.append(metrics_row([
        ("9",   "WORKFLOWS",     NAVY),
        ("31",  "MCP TOOLS",     TEAL),
        ("6",   "TOOL MODULES",  CORAL),
        ("8",   "PROMPTS",       GREEN),
        ("~3.6k", "PYTHON LOC",  GOLD),
    ]))
    s.append(Spacer(1, 8))
    s.append(card(
        "EXECUTIVE THESIS",
        [
            Paragraph(
                "<b>Reasoning lives in prompts. Tools wrap I/O.</b> The Python "
                "code in NN does no algorithmic work. It exposes capabilities "
                "(IMAP poll, GitLab create issue, run Locust tier, send PDF "
                "email, etc.) and Claude orchestrates them by reading a "
                "task-specific prompt. To change behavior, you edit a markdown "
                "file. To add capability, you wrap one external system as a tool.",
                CARD_BODY,
            ),
            Paragraph(
                "<b>One Claude turn per process.</b> agent.py boots, runs ONE "
                "turn through the SDK, exits. No daemons, no orchestration "
                "framework, no multi-agent graph. State persists between runs "
                "via SQLite committed to git, not via a long-running process.",
                CARD_BODY,
            ),
            Paragraph(
                "<b>Single-source secrets.</b> One .env at the project root. "
                "No ANTHROPIC_API_KEY anywhere — reasoning runs through the "
                "local Claude Code CLI under a Claude Max subscription, so "
                "monthly cost is fixed.",
                CARD_BODY,
            ),
        ],
        header_color=TEAL,
    ))

    s.append(PageBreak())

    # ─── Page 2: Architecture ─────────────────────────────────────
    s.append(Paragraph("1. Architecture", H1))
    s.append(card(
        "COMPONENT MAP",
        component_diagram(),
        header_color=NAVY,
    ))
    s.append(Spacer(1, 6))
    s.append(card(
        "DESIGN CONSTRAINTS THAT SHAPED THE CODEBASE",
        [
            Paragraph("•&nbsp;&nbsp;<b>One agent, many prompts.</b> Not a multi-agent graph. The same agent.py loads a different prompt per workflow.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Tools must be safe to call repeatedly.</b> Idempotency is enforced inside each tool (UID checkpoints, Drive file-ID tracking, GitLab title dedup, fuzzy memory dedup).", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Memory survives the process.</b> The agent has no in-RAM state. Anything that should persist gets written to SQLite mid-run; the runner commits the DB back to git after every workflow.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Prompts are human-editable contracts.</b> Anyone can change the loop in a workflow by editing markdown. Code review for prompt changes is a markdown diff.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Tools never reason.</b> Every algorithmic decision (which requirements are real, how to split into 3-hour tasks, why a test failure is flaky vs. real, how to phrase a regression summary) lives in a prompt. Python only does I/O.", BULLET),
        ],
        header_color=PURPLE,
    ))

    s.append(PageBreak())

    # ─── Page 3: Universal execution lifecycle ───────────────────
    s.append(Paragraph("2. End-to-end execution lifecycle", H1))
    s.append(card(
        "THE UNIVERSAL LIFECYCLE",
        execution_lifecycle(),
        header_color=CORAL,
    ))
    s.append(Spacer(1, 4))
    s.append(card(
        "WHAT HAPPENS IN EACH PHASE",
        [
            step_box(1, "Trigger fires",
                     "GitHub Actions schedule (cron) or workflow_dispatch starts the job. The job is pinned to the self-hosted Windows runner via runs-on: [self-hosted, Windows].",
                     NAVY),
            step_box(2, "Repo checkout",
                     "actions/checkout@v5 clones the repo onto the runner. Includes the latest nucleus_memory.db and data/ committed by prior runs — that's how memory crosses runs.",
                     TEAL),
            step_box(3, "Dependencies",
                     "py -3 -m pip install -r requirements.txt installs claude-agent-sdk, requests, google-api-python-client, pypdf, python-dotenv. Fast on warm runner.",
                     CORAL),
            step_box(4, "agent.py boots",
                     "Loads .env at project root with override=True so .env wins over empty workflow env vars. Forces UTF-8 stdout/stderr to survive Windows cp1252 console.",
                     GREEN),
            step_box(5, "Claude SDK session opens",
                     "create_sdk_mcp_server registers all 31 tools as 'napco-nucleus'. ClaudeSDKClient opens a session against the local Claude Code CLI (no API key). System prompt = system.md + <task>.md.",
                     GOLD),
            step_box(6, "The loop runs",
                     "client.query(kickoff) sends the task-specific kickoff message. Claude reads the prompt, calls MCP tools as needed, streams results back. agent.py prints text blocks as they arrive.",
                     PURPLE),
            step_box(7, "State persists",
                     "Every meaningful tool call wrote to nucleus_memory.db during the run. Final workflow step stages nucleus_memory.db + data/ subfolders, commits with timestamp, rebases onto origin/main.",
                     NAVY),
            step_box(8, "Push to main",
                     "git push lands the new memory state on origin/main. The next workflow that runs (any workflow) gets the updated state at checkout. Concurrency group prevents overlapping pushes.",
                     TEAL),
        ],
        header_color=GREEN,
    ))

    s.append(PageBreak())

    # ─── Page 4: Python orchestrator (agent.py) ──────────────────
    s.append(Paragraph("3. The Python orchestrator (agent.py)", H1))
    s.append(card(
        "RESPONSIBILITY",
        Paragraph(
            "agent.py is 198 lines. It does five things: load secrets, "
            "register tools, build the prompt, open one SDK session, exit. "
            "It contains no business logic. Adding a new workflow means "
            "adding two strings (TASK + KICKOFF) — nothing else.",
            CARD_BODY,
        ),
        header_color=NAVY,
    ))
    s.append(Spacer(1, 6))
    s.append(Paragraph("Entry-point shape", H2))
    s.append(code_block(
        "TASKS = {\n"
        '    "requirement-management",\n'
        '    "daily-report-detailed", "daily-report-summary",\n'
        '    "api-functional-test", "api-integration-test",\n'
        '    "api-load-test", "e2e-test",\n'
        "}\n\n"
        'TASK_KICKOFF = {  # one-line instruction Claude receives first\n'
        '    "requirement-management":\n'
        '        "Run the Requirement Management loop now. ...",\n'
        '    "daily-report-detailed":\n'
        '        "Build today\'s Detailed Daily Test Report. ...",\n'
        "    # ... one entry per task\n"
        "}\n\n"
        "async def run_agent(task, dry_run):\n"
        "    if dry_run:\n"
        '        os.environ["NAPCO_NUCLEUS_DRY_RUN"] = "1"\n'
        "    server = create_sdk_mcp_server(\n"
        '        name="napco-nucleus", version="0.1.0", tools=ALL_TOOLS)\n'
        '    allowed = [f"mcp__napco-nucleus__{n}" for n in TOOL_NAMES]\n'
        '    allowed.extend(["WebSearch", "WebFetch"])\n'
        "    options = ClaudeAgentOptions(\n"
        "        system_prompt=_load_prompt(task),\n"
        '        mcp_servers={"napco-nucleus": server},\n'
        "        allowed_tools=allowed,\n"
        "    )\n"
        "    async with ClaudeSDKClient(options=options) as client:\n"
        "        await client.query(TASK_KICKOFF[task])\n"
        "        async for msg in client.receive_response():\n"
        "            print(_extract_text(msg))"
    ))

    s.append(Spacer(1, 4))
    s.append(card(
        "WHY ONE TURN PER PROCESS",
        [
            Paragraph("•&nbsp;&nbsp;<b>Clean state.</b> No leaked context between workflows. The 02:00 functional run cannot poison the 09:00 daily-report run.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Easy to reason about.</b> Each run is a function call — input prompt, output side effects. No long-running daemon to babysit.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Crash-safe.</b> Process death between tool calls leaves SQLite in a consistent state because every tool flushes before returning. Restart and re-run.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Cost-bounded.</b> A workflow can't accidentally loop forever — the SDK session closes when the prompt's loop ends, and timeout-minutes: 25 in the YAML caps the worst case.", BULLET),
        ],
        header_color=TEAL,
    ))

    s.append(PageBreak())

    # ─── Page 5: Claude Agent SDK ─────────────────────────────────
    s.append(Paragraph("4. Claude Agent SDK integration", H1))
    s.append(card(
        "SDK SURFACE NN USES",
        [
            Paragraph(
                "Three imports do all the work: <b>ClaudeAgentOptions</b> "
                "(session config), <b>ClaudeSDKClient</b> (the session "
                "context manager), and <b>create_sdk_mcp_server</b> (wraps "
                "Python functions as MCP tools). Tools are registered with "
                "the @tool decorator from the SDK.",
                CARD_BODY,
            ),
        ],
        header_color=GOLD,
    ))
    s.append(Spacer(1, 6))

    s.append(Paragraph("How a tool is registered", H2))
    s.append(code_block(
        "from claude_agent_sdk import tool\n\n"
        "@tool(\n"
        '    "search_requirements",  # tool name Claude sees\n'
        '    "Fuzzy search requirements_seen by title. Returns the most "\n'
        '    "recent N rows with their gitlab_issue_url if present.",\n'
        '    {"query": str, "limit": int},  # arg schema\n'
        ")\n"
        "async def search_requirements_tool(args):\n"
        '    rows = memory.search_requirements(args["query"],\n'
        '                                       limit=args.get("limit", 5))\n'
        '    return {"content": [{"type": "text",\n'
        '                          "text": json.dumps(rows, default=str)}]}'
    ))

    s.append(Spacer(1, 6))
    s.append(card(
        "TRANSPORT MODEL — NO ANTHROPIC_API_KEY",
        [
            Paragraph(
                "The SDK normally talks to api.anthropic.com using "
                "ANTHROPIC_API_KEY. NN does not set that variable. Instead, "
                "<b>napco_config.claude_cli_path()</b> resolves the path to "
                "the locally-installed Claude Code CLI binary, and the SDK "
                "is configured with <b>cli_path=...</b>. The CLI handles "
                "auth via the user's Claude Max subscription session, so "
                "every run is metered against the monthly subscription, not "
                "billed per token.",
                CARD_BODY,
            ),
            Paragraph(
                "Consequence: cost is fixed (~$200/mo). Consequence: NN "
                "cannot run on a CI host that has no Claude Max session. "
                "That is why workflows pin to the self-hosted Windows "
                "runner, where the CLI is logged in 24/7.",
                CARD_BODY,
            ),
        ],
        header_color=PURPLE,
    ))

    s.append(PageBreak())

    # ─── Page 6: MCP tool catalog ─────────────────────────────────
    s.append(Paragraph("5. The MCP tool surface (31 tools, 6 modules)", H1))
    s.append(card(
        "MODULE COMPOSITION",
        Paragraph(
            "Tools are grouped by responsibility. Each module exposes "
            "<b>TOOLS</b> (the registered functions) and <b>TOOL_NAMES</b> "
            "(for the allowlist). tools/__init__.py concatenates them into "
            "ALL_TOOLS so agent.py registers the entire surface in one call.",
            CARD_BODY,
        ),
        header_color=PURPLE,
    ))
    s.append(Spacer(1, 4))

    tool_data = [
        ["Module", "N", "Responsibility", "Representative tools"],
        ["memory",       "5", "SQLite-backed cross-run continuity",
         "log_activity, recall_activity, search_requirements, recall_test_runs, memory_stats"],
        ["requirements", "4", "Email + Drive ingestion → GitLab",
         "poll_requirement_emails, ingest_drive_files, read_requirement_inbox, publish_tasks_to_gitlab"],
        ["tests",        "9", "Test execution + health probes",
         "run_api_tests, run_integration_tests, run_load_tests, run_e2e_tests, run_single_e2e_test, ..."],
        ["files",        "5", "Sibling-project file IO + Playwright a11y",
         "list_files, read_file, write_file, edit_file, explore_ui"],
        ["git",          "3", "Read-only git context across projects",
         "git_diff, git_recent_commits, git_commit_and_push"],
        ["report",       "5", "PDF + email + Teams + log tail + cleanup",
         "generate_pdf_report, send_email, send_teams_digest, tail_log, clean_reports"],
    ]
    s.append(kv_table(tool_data, header_color=PURPLE,
                       col_widths=[22 * mm, 10 * mm, 50 * mm, 98 * mm]))

    s.append(Spacer(1, 8))
    s.append(card(
        "TOOL CONTRACT (THE INVARIANTS)",
        [
            Paragraph("•&nbsp;&nbsp;<b>Wrap one external system per tool.</b> No tool calls another tool. Composition is Claude's job, not Python's.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Side effects log to memory.</b> Every tool calls memory.log_activity inside a try/except so a memory write never breaks the primary flow.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Honor NAPCO_NUCLEUS_DRY_RUN.</b> Mutating tools (publish_tasks_to_gitlab, send_email, git_commit_and_push) check the env var and short-circuit.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Return the SDK envelope.</b> Every tool returns {\"content\": [{\"type\": \"text\", \"text\": json.dumps(...)}]}. Helper _text() in tools/_shared.py enforces this.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Lazy heavy imports.</b> imaplib, googleapiclient, requests for GitLab, Playwright runner all imported inside the tool fn. Keeps cold-start sub-second.", BULLET),
        ],
        header_color=NAVY,
    ))

    s.append(PageBreak())

    # ─── Page 7: Memory layer ─────────────────────────────────────
    s.append(Paragraph("6. The memory layer", H1))
    s.append(card(
        "WHY SQLITE IN GIT",
        Paragraph(
            "nucleus_memory.db is committed to main after every workflow. "
            "Cloning the project on a new machine instantly recovers prior "
            "context: every requirement ever filed, every test run with "
            "regressions, every IMAP UID checkpoint, every Drive file ID "
            "already processed. No external state store, no Redis, no "
            "Postgres. The repo is the database.",
            CARD_BODY,
        ),
        header_color=NAVY,
    ))
    s.append(Spacer(1, 6))
    s.append(Paragraph("Schema (the load-bearing tables)", H2))

    schema = [
        ["Table", "Purpose"],
        ["activity_logs",
         "Every meaningful action with task_name (e.g. requirement-management:publish_gitlab), result string, technical_details JSON blob, timestamp. Drives the daily report's 'what NN did' section."],
        ["requirements_seen",
         "One row per requirement ever processed. Normalized title plus FTS5 virtual table for fuzzy match. gitlab_issue_iid + gitlab_issue_url populated on success. Powers the dedup that stops duplicate issues across runs."],
        ["test_run_history",
         "One row per suite-run: pass/fail counts, duration, PDF artifact path, regression set. Daily report reads this for trend graphs."],
        ["email_checkpoints",
         "IMAP UIDVALIDITY + last UID per (host, user) pair. Idempotency key for poll_requirement_emails."],
        ["drive_processed",
         "Set of Google Drive file IDs already ingested. Idempotency key for ingest_drive_files."],
    ]
    s.append(kv_table(schema, header_color=NAVY,
                       col_widths=[40 * mm, CONTENT_W - 40 * mm]))

    s.append(Spacer(1, 8))
    s.append(card(
        "FTS5 — WHY FUZZY MATCHING MATTERS",
        Paragraph(
            "Clients describe the same requirement different ways across "
            "weeks. Exact title match would file three duplicate GitLab "
            "issues for 'Add SSO login', 'Implement single sign-on', and "
            "'Add SSO support'. The FTS5 index over normalized titles plus "
            "summary text lets search_requirements catch close variants. "
            "publish_tasks_to_gitlab uses this as its second dedup layer — "
            "after exact match against currently-open GitLab issues.",
            CARD_BODY,
        ),
        header_color=GOLD,
    ))

    s.append(PageBreak())

    # ─── Page 8: Prompts ──────────────────────────────────────────
    s.append(Paragraph("7. Prompts — algorithms in markdown", H1))
    s.append(card(
        "STRUCTURE",
        Paragraph(
            "Every task gets a system prompt + a task prompt, concatenated "
            "at runtime. <b>prompts/system.md</b> defines who Claude is "
            "(NAPCO Nucleus), the project layout, the two operational "
            "dimensions, the core principles (Claude-first, one-shot per "
            "run, artifacts over adjectives, mandatory memory check-in), "
            "tone rules (no em-dashes, plain dev English, English-only "
            "output). <b>prompts/&lt;task&gt;.md</b> defines the actual "
            "loop for that workflow — numbered steps, required tool calls, "
            "decision rules, output format.",
            CARD_BODY,
        ),
        header_color=GREEN,
    ))
    s.append(Spacer(1, 6))
    s.append(Paragraph("The 8 prompt files", H2))

    prompts = [
        ["File", "Workflow it drives"],
        ["system.md",                "Concatenated to every task. The shared backbone."],
        ["requirement_management.md","Fires every 2h. IMAP+Drive ingest → 3h tasks → GitLab issues."],
        ["daily_report_detailed.md", "09:00 BDT. 6-section detailed PDF to the full team."],
        ["daily_report_summary.md",  "09:30 BDT. 7-block executive dashboard to leadership."],
        ["api_functional_test.md",   "02:00 BDT. Newman + Postman collection, classify failures."],
        ["api_integration_test.md",  "02:00 BDT. pytest integration suite with regression diff."],
        ["api_load_test.md",         "02:00 BDT. Locust multi-tier 10–10,000 users."],
        ["e2e_test.md",              "02:00 BDT. Playwright full suite + failure screenshots."],
    ]
    s.append(kv_table(prompts, header_color=GREEN,
                       col_widths=[55 * mm, CONTENT_W - 55 * mm]))

    s.append(Spacer(1, 8))
    s.append(card(
        "WHY THIS WORKS",
        [
            Paragraph("•&nbsp;&nbsp;<b>Behavior changes are markdown diffs.</b> Adjusting how tasks split, how failures classify, what goes in the report — all PR-reviewable as plain English.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Constraints encoded in prompts.</b> 'Memory check-in mandatory.' 'Title under 70 chars.' 'NO em-dashes.' Things that would be brittle validation code become natural-language rules Claude follows.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>One ground truth per workflow.</b> If you want to know what API Functional Test does, you read api_functional_test.md. The Python tools are leaf operations only.", BULLET),
        ],
        header_color=TEAL,
    ))

    s.append(PageBreak())

    # ─── Page 9: Third-party integrations ─────────────────────────
    s.append(Paragraph("8. Third-party integrations", H1))
    integrations = [
        ["Integration", "Library", "Used for"],
        ["IMAP",                "stdlib imaplib",
         "Pull allowlisted requirement emails. Idempotent via UIDVALIDITY + since-UID checkpoint stored in memory.email_checkpoints."],
        ["Google Drive",        "google-api-python-client",
         "List + download new audio/video and PDFs from a configured folder. Service-account auth via google-credentials.json."],
        ["Groq Whisper",        "requests (REST)",
         "Audio + video transcription. Cheap, fast. Result becomes a .txt file under data/requirements/inbox/meetings/."],
        ["pypdf",               "pypdf",
         "Local PDF text extraction. No external call. Result becomes .txt under inbox/documents/."],
        ["GitLab",              "requests (REST v4)",
         "list_open_issue_titles + create_issue. PAT with api scope. Stateless — every call re-reads env so token rotation is hot."],
        ["Microsoft Teams",     "requests",
         "Incoming webhook for the optional one-line digest after requirement-management completes."],
        ["Gmail SMTP",          "stdlib smtplib",
         "Outbound email of the daily report PDFs. App-password auth. Used by send_email tool only."],
        ["Newman (Postman CLI)","subprocess",
         "API functional test execution. Reads a Postman collection + environment from MVP-Access-API-Test."],
        ["pytest",              "subprocess",
         "API integration test execution. Test files live in MVP-Access-API-Test/tests/integration."],
        ["Locust",              "subprocess",
         "Load testing in tiers (10, 100, 1k, 10k users). Multi-stage with cooldowns to find the capacity ceiling."],
        ["Playwright",          "subprocess",
         "E2E test execution across Easy / Release / full suites. Failure screenshots embedded in the PDF report."],
        ["TFS + MSBuild",       "subprocess",
         "MVP Access CICD workflow only. tf get latest, MSBuild Release config, IIS deploy via UNC, health check."],
        ["GitHub Actions",      "(scheduler)",
         "Cron + manual triggers. 9 workflows. All pinned to runs-on: [self-hosted, Windows]."],
        ["Self-hosted runner",  "(machine)",
         "Windows VM at 172.16.205.209. Has the Claude Code CLI logged into Claude Max, Python 3.13, all test runners installed."],
    ]
    s.append(kv_table(integrations, header_color=NAVY,
                       col_widths=[32 * mm, 42 * mm, CONTENT_W - 74 * mm]))

    s.append(PageBreak())

    # ─── Page 10: CI/CD execution model ───────────────────────────
    s.append(Paragraph("9. CI/CD execution model", H1))
    s.append(card(
        "WORKFLOW SHAPE (UNIVERSAL)",
        Paragraph(
            "Every NN workflow has the same five steps in YAML: checkout, "
            "install, run agent.py with --task, optional follow-on (e.g. "
            "log copy), commit + push memory state. Differences are: cron "
            "schedule, the --task flag, and which secrets get exposed via "
            "env: at job level.",
            CARD_BODY,
        ),
        header_color=CORAL,
    ))
    s.append(Spacer(1, 6))
    s.append(Paragraph("Canonical workflow YAML", H2))
    s.append(code_block(
        "name: <Display Name>\n"
        "on:\n"
        "  schedule:\n"
        "    - cron: '<utc-cron>'\n"
        "  workflow_dispatch:\n"
        "    inputs:\n"
        "      dry_run:\n"
        "        type: choice\n"
        "        options: ['false', 'true']\n\n"
        "permissions:\n"
        "  contents: write\n\n"
        "concurrency:\n"
        "  group: <task-name>\n"
        "  cancel-in-progress: false\n\n"
        "jobs:\n"
        "  run:\n"
        "    runs-on: [self-hosted, Windows]\n"
        "    timeout-minutes: 25\n"
        "    env:\n"
        "      # only the secrets this task needs\n"
        "      ...\n"
        "    steps:\n"
        "      - uses: actions/checkout@v5\n"
        "      - run: py -3 -m pip install -r requirements.txt\n"
        "      - run: py -3 agent.py --task <task-name>\n"
        "        shell: pwsh\n"
        "      - name: Commit state changes\n"
        "        if: always()\n"
        "        shell: pwsh\n"
        "        run: |\n"
        "          git add nucleus_memory.db data/...\n"
        "          git commit -m \"<task>: $(Get-Date -Format ...)\"\n"
        "          git pull --rebase origin main\n"
        "          git push"
    ))

    s.append(Spacer(1, 4))
    s.append(card(
        "OPERATIONAL GUARDRAILS",
        [
            Paragraph("•&nbsp;&nbsp;<b>Concurrency groups.</b> Each workflow declares a group named after its task. cancel-in-progress: false means runs queue, never overlap.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>timeout-minutes.</b> 25 minutes for most workflows; load test gets longer. Caps runaway cost in the unlikely event a prompt loops.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>contents: write.</b> Required because the post-run step commits memory back to the repo. No other elevated permissions.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Self-hosted only.</b> All workflows pin to runs-on: [self-hosted, Windows]. Cloud runners cannot run NN — no Claude Max session, no Newman/Locust/Playwright pre-installed, no UNC path access for IIS deploy.", BULLET),
        ],
        header_color=PURPLE,
    ))

    s.append(PageBreak())

    # ─── Page 11: Workflow catalog ────────────────────────────────
    s.append(Paragraph("10. The 9 workflows", H1))
    workflows = [
        ["#", "Workflow", "Schedule (UTC / BDT)", "What it does"],
        ["1", "API Functional Test",        "20:00 / 02:00",
         "Newman + Postman collection across the API surface."],
        ["2", "API Integration Test",       "20:00 / 02:00",
         "pytest integration suite with regression diff vs. prior runs."],
        ["3", "API Load Test",              "20:00 / 02:00",
         "Locust multi-tier 10 → 10,000 users with server-recovery cooldowns."],
        ["4", "MVP Access E2E Test",        "20:00 / 02:00",
         "Playwright full suite. Failure screenshots embedded in PDF."],
        ["5", "Daily Report (Detailed)",    "03:00 / 09:00",
         "Reads memory + the 4 test PDFs. Composes 6-section detailed PDF. Emails full team."],
        ["6", "Daily Report (Summary)",     "03:30 / 09:30",
         "7-block executive dashboard. Emails leadership only."],
        ["7", "Requirement Management",     "Every 2h, 09–17 BDT, Sun–Thu",
         "IMAP + Drive ingest. Splits into 3-hour tasks. Files GitLab issues with two-layer dedup."],
        ["8", "MVPAccess CICD",             "16:00 / 22:00",
         "TFS pull, MSBuild Release, IIS deploy via UNC, health check, memory log."],
        ["9", "Probe Runner Filesystem",    "Manual",
         "Diagnostic. Inspects runner state during triage."],
    ]
    s.append(kv_table(workflows, header_color=NAVY,
                       col_widths=[7 * mm, 38 * mm, 38 * mm, CONTENT_W - 83 * mm]))

    s.append(Spacer(1, 8))
    s.append(card(
        "TWO OPERATIONAL DIMENSIONS",
        [
            Paragraph(
                "<b>Project Management dimension.</b> Workflows 5, 6, 7. "
                "Read state from the world (email, Drive, prior runs), "
                "produce reports + GitLab issues. Where strategy meets execution.",
                CARD_BODY,
            ),
            Paragraph(
                "<b>Test Automation dimension.</b> Workflows 1, 2, 3, 4, 8. "
                "Run suites, classify failures, deploy releases. Pure execution.",
                CARD_BODY,
            ),
        ],
        header_color=TEAL,
    ))

    s.append(PageBreak())

    # ─── Page 12: Adding a new workflow / new tool ────────────────
    s.append(Paragraph("11. Adding a new workflow", H1))
    s.append(card(
        "RECIPE",
        [
            step_box(1, "Write the prompt",
                     "Create prompts/&lt;new_task&gt;.md. Define the loop: memory check-in (mandatory), the steps, the dedup rule, the output contract. Match tone of existing prompts.",
                     NAVY),
            step_box(2, "Wire agent.py",
                     "Add the task name to TASKS set. Add a one-line kickoff message to TASK_KICKOFF dict. No other Python changes if existing tools cover the I/O.",
                     TEAL),
            step_box(3, "If new I/O is needed",
                     "Add a tool — see section 12. Otherwise skip.",
                     CORAL),
            step_box(4, "Author the workflow YAML",
                     "Copy an existing workflow file in .github/workflows/. Update name, cron, env: secrets the task needs, the --task flag, and the post-run commit pattern.",
                     GREEN),
            step_box(5, "Add secrets",
                     "If the task needs new env vars, add them to GitHub Actions secrets AND to the runner's local .env. agent.py loads .env with override=True so .env wins for local runs.",
                     GOLD),
            step_box(6, "Dry-run first",
                     "Trigger via workflow_dispatch with dry_run=true. Verify the loop logs to memory but does not mutate. Inspect activity_logs.",
                     PURPLE),
            step_box(7, "First scheduled run + monitor",
                     "Switch to live. Tail logs from the runner. Confirm the post-run commit landed on main with the new state.",
                     NAVY),
        ],
        header_color=GREEN,
    ))

    s.append(PageBreak())

    # ─── Page 13: Adding a new MCP tool ───────────────────────────
    s.append(Paragraph("12. Adding a new MCP tool", H1))
    s.append(card(
        "RECIPE",
        [
            step_box(1, "Pick the right module",
                     "memory / requirements / tests / files / git / report. If none fit, create tools/&lt;new&gt;.py with the same shape.",
                     NAVY),
            step_box(2, "Write the function",
                     "@tool decorator with name, description, arg schema. Lazy-import any heavy library inside the fn. Wrap external call in try/except. Always log_activity. Honor NAPCO_NUCLEUS_DRY_RUN if mutating.",
                     TEAL),
            step_box(3, "Return the SDK envelope",
                     'Use _text(payload) helper from tools/_shared.py. It produces {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}.',
                     CORAL),
            step_box(4, "Append to TOOLS + TOOL_NAMES",
                     "Both lists at the bottom of the module file. tools/__init__.py picks them up automatically — no edits there.",
                     GREEN),
            step_box(5, "Update the prompt that calls it",
                     "Add the tool name + when to call it to the relevant prompts/&lt;task&gt;.md. Without this, Claude does not know the tool exists.",
                     GOLD),
            step_box(6, "Smoke-test locally",
                     "py -3 agent.py --task &lt;task&gt; --dry-run from the repo root. Watch the streamed text for the tool call result.",
                     PURPLE),
        ],
        header_color=PURPLE,
    ))
    s.append(Spacer(1, 6))
    s.append(card(
        "TOOL TEMPLATE",
        code_block(
            "from claude_agent_sdk import tool\n"
            "import memory\n"
            "from tools._shared import _text\n\n"
            "@tool(\n"
            '    "do_thing",\n'
            '    "What it does, in one sentence Claude can act on.",\n'
            '    {"arg1": str, "arg2": int},\n'
            ")\n"
            "async def do_thing_tool(args):\n"
            "    if os.environ.get(\"NAPCO_NUCLEUS_DRY_RUN\") == \"1\":\n"
            "        return _text({\"dry_run\": True})\n"
            "    try:\n"
            "        result = backend.run(args[\"arg1\"], args[\"arg2\"])\n"
            "    except Exception as e:\n"
            "        memory.log_activity(task_name=\"do_thing\",\n"
            "                            result=f\"error:{type(e).__name__}\")\n"
            "        return _text({\"error\": str(e)})\n"
            "    memory.log_activity(task_name=\"do_thing\",\n"
            "                        result=f\"ok:{result.summary}\")\n"
            "    return _text(result.to_dict())\n\n"
            "TOOLS = [do_thing_tool]\n"
            "TOOL_NAMES = [\"do_thing\"]"
        ),
        header_color=NAVY,
    ))

    s.append(PageBreak())

    # ─── Page 14: Benefits ────────────────────────────────────────
    s.append(Paragraph("13. Benefits", H1))
    s.append(card(
        "WHAT THIS ARCHITECTURE BUYS",
        [
            Paragraph("•&nbsp;&nbsp;<b>Behavior-via-prompt.</b> Adjusting how requirements are split, how failures classified, what shows up in the executive summary — all happen in markdown PRs. No deploy, no release.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Cost-bounded reasoning.</b> Claude Max subscription is fixed monthly. Per-token API billing is not in the budget. NN's cost ceiling does not depend on traffic.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Single-machine deployment.</b> One self-hosted runner, one repo, one .env. No K8s, no message queue, no service mesh. The whole platform fits in one VM and one git repo.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Memory in git.</b> Audit trail, dedup history, run history all version-controlled. Forensic question 'what did NN file last Tuesday?' answered with a git log + a sqlite query.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Idempotent by construction.</b> Every ingestion path has a checkpoint or file-ID. Every publish path has two-layer dedup. Re-running any workflow is safe.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Tool surface stays small.</b> 31 tools across 6 modules cover both dimensions. Reasoning logic that would inflate Python LOC lives in markdown.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>One Claude turn per process.</b> No session leak, no context bleed, no need to manage long-lived agent state. Process boundary IS the state boundary.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Standard CI/CD.</b> Workflows are vanilla GitHub Actions YAML. Anyone who knows Actions can read a NN workflow without learning a new orchestrator.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Multi-language input.</b> Bangla, Malay, mixed-script chat — Claude reads it. Outputs are always English by prompt rule. No translation pipeline needed.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Two consolidated emails per day.</b> 09:00 detailed report to the team, 09:30 executive summary to leadership. Replaces the previous 6-fragments-overnight reality.", BULLET),
        ],
        header_color=GREEN,
    ))

    s.append(PageBreak())

    # ─── Page 15: Demerits / known limits ─────────────────────────
    s.append(Paragraph("14. Demerits and known limitations", H1))
    s.append(card(
        "WHAT THIS ARCHITECTURE COSTS",
        [
            Paragraph("•&nbsp;&nbsp;<b>Single-machine bottleneck.</b> Self-hosted runner is a single VM. If it goes down, every workflow stops until it's back. No automatic failover.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Claude Max session is a hidden dependency.</b> If the Claude Code CLI on the runner logs out, every workflow fails until somebody re-authenticates interactively. There is no headless retry path.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Non-determinism.</b> Same input does not guarantee same output. Two consecutive runs may classify the same failure slightly differently. Acceptable for reports, problematic for invariants.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Prompt drift.</b> A small markdown edit can change behavior subtly across all consumers. There is no automated regression suite for prompt changes — only dry-run and manual review.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Memory growth.</b> nucleus_memory.db grows monotonically. No retention policy yet. Repo size will eventually feel it. Vacuum or pruning is on the roadmap.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Tooling-language coupling.</b> Tools are Python. Tests are TypeScript (Playwright) and JS (Newman). Crossing that boundary is via subprocess, not in-process — debugging is log-driven.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Secrets fan-out.</b> Every secret has to live in two places: GitHub Actions secrets (for the workflow env) and the runner's .env (for local re-runs). Rotation is a two-step manual process.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Limited concurrency.</b> Only one job at a time per workflow group. The runner cannot parallelize the four 02:00 test runs — they queue on the same machine.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>No multi-tenant story.</b> Allowlists, project paths, GitLab project ID are hard-coded for MVP Access. Onboarding a second product would require config refactoring.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Hard-to-test reasoning.</b> Unit tests cover tools (I/O wrappers). The reasoning lives in prompts. Validating a prompt change is observational, not assertive.", BULLET),
        ],
        header_color=CORAL,
    ))

    s.append(PageBreak())

    # ─── Page 16: Tech stack + closing ────────────────────────────
    s.append(Paragraph("15. Tech stack at a glance", H1))
    s.append(card(
        "EVERYTHING NN DEPENDS ON",
        [
            Paragraph("<b>Reasoning:</b> Claude Agent SDK · Claude Code CLI · Claude Max subscription.", CARD_BODY),
            Paragraph("<b>Runtime:</b> Python 3.13 · GitHub Actions · self-hosted Windows VM runner.", CARD_BODY),
            Paragraph("<b>Memory:</b> SQLite + FTS5. Committed to git.", CARD_BODY),
            Paragraph("<b>Reporting:</b> Reportlab.", CARD_BODY),
            Paragraph("<b>Tests it orchestrates:</b> Newman · pytest · Locust · Playwright.", CARD_BODY),
            Paragraph("<b>External integrations:</b> IMAP · Gmail SMTP · Google Drive API · Groq Whisper · GitLab REST v4 · Microsoft Teams webhook · TFS · MSBuild · IIS.", CARD_BODY),
            Paragraph("<b>Python deps:</b> claude-agent-sdk · python-dotenv · requests · google-api-python-client · google-auth · pypdf.", CARD_BODY),
        ],
        header_color=GOLD,
    ))
    s.append(Spacer(1, 8))

    s.append(Paragraph("16. Closing", H1))
    s.append(card(
        "THE THESIS, RESTATED",
        Paragraph(
            "QA architect plus AI equals senior developer team output. "
            "NAPCO Nucleus is the proof: 9 production workflows, 31 tools, "
            "~3.6k Python LOC, two consolidated emails per day, every "
            "client requirement filed in GitLab within two hours of being "
            "spoken on a call. Built and operated by one person, because "
            "the reasoning lives in prompts, not in code that needs a team "
            "to maintain.",
            ParagraphStyle("Closing", fontName="Helvetica-Oblique",
                            fontSize=11, leading=15, textColor=NAVY),
        ),
        header_color=PURPLE,
    ))

    doc.build(s)
    return OUT_PATH


if __name__ == "__main__":
    out = build()
    print(f"Wrote {out}")
