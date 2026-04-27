"""Render the Requirement Management end-to-end flow as a PDF.

Colorful, presentation-grade. Built from the same palette and helpers
as generate_nn_architecture.py so the output matches the rest of the
NN deck.

Pages:
    1. Title + the 7 actors (architecture)
    2. Visual swimlane: one full run, end to end (boxes + arrows)
    3. Step-by-step (numbered step boxes)
    4. Who-commands-whom table + guardrails

Run:
    py -3 scripts/generate_requirement_flow.py
Output:
    docs/Requirement-Management-Flow.pdf
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
    Spacer,
    Table,
    TableStyle,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT_PATH = ROOT / "docs" / "Requirement-Management-Flow.pdf"

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# Palette (matches generate_nn_architecture.py)
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

TITLE = ParagraphStyle(
    name="Title", fontName="Helvetica-Bold", fontSize=22, leading=26,
    textColor=NAVY, alignment=TA_LEFT, spaceAfter=2,
)
SUBTITLE = ParagraphStyle(
    name="Subtitle", fontName="Helvetica", fontSize=11, leading=14,
    textColor=MUTED, alignment=TA_LEFT, spaceAfter=4,
)
BYLINE = ParagraphStyle(
    name="Byline", fontName="Helvetica-Bold", fontSize=9.5, leading=12,
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
SECTION_HEAD = ParagraphStyle(
    name="SectionHead", fontName="Helvetica-Bold", fontSize=12, leading=14,
    textColor=NAVY, alignment=TA_LEFT, spaceAfter=4,
)


def _on_page(canvas: canvas_mod.Canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - 4, PAGE_W, 4, stroke=0, fill=1)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN, 8 * mm,
                      "NAPCO Nucleus  |  Requirement Management Flow")
    canvas.drawRightString(PAGE_W - MARGIN, 8 * mm, f"page {doc.page}")
    canvas.restoreState()


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


def step_box(num: int, title: str, body: str, accent) -> Table:
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


# ─── Visual diagram helpers ─────────────────────────────────────────

def _box(d, x, y, w, h, fill, label, sublabel=None,
         text_color=WHITE, label_size=8.5, sublabel_size=7):
    """Draw a rounded rectangle with a label centered inside it."""
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
    """Straight arrow with arrowhead at (x2, y2)."""
    d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=1.1))
    # Arrowhead
    import math
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


def architecture_diagram() -> Drawing:
    """High-level: 7 layers showing who calls who. CONTENT_W wide."""
    H = 95 * mm
    d = Drawing(CONTENT_W, H)
    W = CONTENT_W
    bw = 50 * mm   # box width
    bh = 9 * mm    # box height
    cx = W / 2     # center x

    layers = [
        ("You / cron",                "workflow_dispatch · every 2h, 09–17 BDT", NAVY),
        ("GitHub Actions",            "requirement-management.yml",              TEAL),
        ("Self-hosted Windows runner","test-runner @ 172.16.205.209",            CORAL),
        ("agent.py (Python)",         "load .env · register MCP · open SDK",     GREEN),
        ("Claude CLI (local)",        "via Claude Max — no API key",             GOLD),
        ("napco-nucleus MCP server",  "in-process tools",                        PURPLE),
        ("External services + DB",    "IMAP · Drive · Groq · GitLab · Teams · SQLite", NAVY),
    ]

    n = len(layers)
    gap = (H - n * bh) / (n + 1)
    arrow_label = [
        "dispatch / cron",
        "assigns job",
        "py agent.py --task …",
        "stdio + kickoff prompt",
        "tool calls (MCP)",
        "HTTP / IMAP / SDK",
        None,
    ]

    positions = []
    for i, (label, sub, color) in enumerate(layers):
        y = H - gap - bh - i * (bh + gap)
        x = cx - bw / 2
        _box(d, x, y, bw, bh, color, label, sub)
        positions.append((cx, y, y + bh))

    for i in range(n - 1):
        _, _, top_curr = positions[i]
        _, bot_next, _ = positions[i + 1]
        _arrow(d, cx, positions[i][1], cx, positions[i + 1][2] + 0,
               color=MUTED, label=arrow_label[i])

    return d


def swimlane_diagram() -> Drawing:
    """Step 1–7 of the run shown left-to-right with the actor doing
    the work and the call(s) it makes."""
    H = 175 * mm
    d = Drawing(CONTENT_W, H)
    W = CONTENT_W

    # Lane setup
    lane_titles = [
        ("You / cron",         NAVY),
        ("GitHub Actions",     TEAL),
        ("Runner + agent.py",  CORAL),
        ("Claude (LLM)",       GOLD),
        ("MCP tools",          PURPLE),
        ("External / DB",      GREEN),
    ]
    n_lanes = len(lane_titles)
    lane_w = W / n_lanes
    header_h = 9 * mm

    # Lane backgrounds
    for i, (title, color) in enumerate(lane_titles):
        x = i * lane_w
        # Header
        d.add(Rect(x, H - header_h, lane_w, header_h,
                   fillColor=color, strokeColor=color))
        d.add(String(x + lane_w / 2, H - header_h / 2 - 2.5, title,
                     fontName="Helvetica-Bold", fontSize=8.5,
                     fillColor=WHITE, textAnchor="middle"))
        # Body alternating soft fill for readability
        body_color = SOFT if i % 2 == 0 else WHITE
        d.add(Rect(x, 0, lane_w, H - header_h,
                   fillColor=body_color, strokeColor=RULE, strokeWidth=0.3))

    # Each row = one event in the run. (lane_index, label, color)
    events = [
        (0, "fire trigger",                               NAVY),
        (1, "dispatch job",                               TEAL),
        (2, "checkout · pip install · py agent.py",       CORAL),
        (2, "load .env · register MCP · open SDK",        CORAL),
        (3, "kickoff prompt received",                    GOLD),
        (3, "STEP 0: memory check-in",                    GOLD),
        (4, "recall_activity · memory_stats",             PURPLE),
        (5, "SQLite query",                               GREEN),
        (3, "STEP 1: ingest sources",                     GOLD),
        (4, "poll_requirement_emails",                    PURPLE),
        (5, "IMAP fetch (allowlist)",                     GREEN),
        (4, "ingest_drive_files",                         PURPLE),
        (5, "Drive · Groq Whisper · pypdf",               GREEN),
        (3, "STEP 2: read inbox",                         GOLD),
        (4, "read_requirement_inbox",                     PURPLE),
        (3, "STEP 3-4: identify + dedupe (LLM)",          GOLD),
        (4, "search_requirements (FTS5)",                 PURPLE),
        (3, "STEP 5: split into ~3h tasks (LLM)",         GOLD),
        (3, "STEP 6: publish",                            GOLD),
        (4, "publish_tasks_to_gitlab",                    PURPLE),
        (5, "GitLab create_issue · remember",             GREEN),
        (3, "STEP 7: digest + exit",                      GOLD),
        (4, "send_teams_digest · log_activity",           PURPLE),
        (5, "Teams webhook · SQLite",                     GREEN),
        (2, "post-run: git commit + push",                CORAL),
        (1, "run summary visible",                        TEAL),
    ]

    row_h = (H - header_h - 4 * mm) / len(events)
    box_h = row_h * 0.78
    box_w = lane_w * 0.86

    centers = []
    for i, (lane, label, color) in enumerate(events):
        y = H - header_h - 2 * mm - (i + 1) * row_h + (row_h - box_h) / 2
        x = lane * lane_w + (lane_w - box_w) / 2
        d.add(Rect(x, y, box_w, box_h,
                   fillColor=color, strokeColor=color, rx=2, ry=2))
        d.add(String(x + box_w / 2, y + box_h / 2 - 2.5, label,
                     fontName="Helvetica-Bold", fontSize=6.8,
                     fillColor=WHITE, textAnchor="middle"))
        centers.append((x + box_w / 2, y + box_h / 2,
                        x, y, x + box_w, y + box_h))

    # Connect each event to the next with a thin arrow
    for i in range(len(events) - 1):
        _, _, x1l, y1b, x1r, y1t = centers[i]
        _, _, x2l, y2b, x2r, y2t = centers[i + 1]
        # Exit from bottom of source, enter top of target
        sx = (x1l + x1r) / 2
        sy = y1b
        tx = (x2l + x2r) / 2
        ty = y2t
        if abs(sx - tx) < 1:
            _arrow(d, sx, sy, tx, ty, color=MUTED)
        else:
            # L-shaped: down from source, across, then arrow down into target
            mid_y = (sy + ty) / 2
            d.add(Line(sx, sy, sx, mid_y, strokeColor=MUTED, strokeWidth=0.9))
            d.add(Line(sx, mid_y, tx, mid_y, strokeColor=MUTED, strokeWidth=0.9))
            _arrow(d, tx, mid_y, tx, ty, color=MUTED)

    return d


def build():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT_PATH),
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 4, bottomMargin=MARGIN,
        title="Requirement Management Flow",
        author="Mohammad Kamrul Hasan",
    )
    frame = Frame(MARGIN, MARGIN, CONTENT_W, PAGE_H - 2 * MARGIN - 4,
                  id="main", showBoundary=0,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="Default", frames=[frame], onPage=_on_page)])

    story: list = []

    # ── Title block
    story.append(Paragraph("Requirement Management — End-to-End Flow", TITLE))
    story.append(Paragraph(
        "How NAPCO Nucleus turns raw client text into 3-hour GitLab tasks",
        SUBTITLE,
    ))
    story.append(Paragraph(
        "Mohammad Kamrul Hasan &nbsp;&middot;&nbsp; "
        "AI-Augmented QA Architect &nbsp;&middot;&nbsp; April 2026",
        BYLINE,
    ))

    # ── What it does
    story.append(card(
        "WHAT THIS WORKFLOW DOES",
        Paragraph(
            "Every two hours during business hours, a Claude-powered agent "
            "polls the allowlisted IMAP mailbox, downloads new audio recordings "
            "and PDFs from Google Drive, transcribes the audio with Groq Whisper, "
            "splits each distinct requirement into ~3-hour tasks, and files them "
            "as GitLab issues with two-layer dedup. A short Teams digest is "
            "posted after completion if the webhook is configured.",
            CARD_BODY,
        ),
        header_color=NAVY,
    ))
    story.append(Spacer(1, 6))

    # ── Architecture diagram
    story.append(card(
        "1. ARCHITECTURE — WHO TALKS TO WHOM",
        architecture_diagram(),
        header_color=TEAL,
    ))

    story.append(PageBreak())

    # ── Swimlane diagram
    story.append(card(
        "2. ONE FULL RUN — SWIMLANE VIEW",
        swimlane_diagram(),
        header_color=CORAL,
    ))

    story.append(PageBreak())

    # ── Step-by-step
    story.append(card(
        "3. THE LOOP, STEP BY STEP",
        [
            step_box(0, "Memory check-in (mandatory)",
                     "recall_activity for publish_gitlab and poll_email; memory_stats. "
                     "Confirms the DB is being written and shows what was published recently.",
                     NAVY),
            step_box(1, "Ingest new inputs",
                     "poll_requirement_emails fetches IMAP messages from allowlisted senders. "
                     "ingest_drive_files downloads new Drive audio (→ Groq Whisper) and PDFs (→ pypdf). "
                     "Idempotent via UIDVALIDITY checkpoint and Drive file-ID tracking.",
                     TEAL),
            step_box(2, "Read the inbox",
                     "read_requirement_inbox returns every .txt file across email, meetings, "
                     "chat, documents subfolders. If file_count is 0, stop and report the inbox is empty.",
                     CORAL),
            step_box(3, "Identify distinct requirements (LLM)",
                     "Claude reads each file and extracts user-visible capabilities, changes, "
                     "bug fixes, deliverables. Process chatter, greetings, scheduling are ignored.",
                     GREEN),
            step_box(4, "Dedup against prior work",
                     "search_requirements per candidate against memory.requirements_seen "
                     "(SQLite + FTS5 fuzzy match). Skip anything with an existing GitLab issue URL.",
                     GOLD),
            step_box(5, "Split into ~3-hour tasks (LLM)",
                     "Larger requirements split into multiple 3-hour tasks. Smaller related items "
                     "get merged. Each task gets title, description, acceptance_criteria, "
                     "estimate_hours, source_ref, optional labels.",
                     PURPLE),
            step_box(6, "Publish to GitLab",
                     "publish_tasks_to_gitlab snapshots the submission, dedupes against open "
                     "issue titles AND fuzzy memory, creates the rest, writes each created task "
                     "back to memory with iid + url. Honors NAPCO_NUCLEUS_DRY_RUN.",
                     NAVY),
            step_box(7, "Digest + exit",
                     "send_teams_digest with one-line summary if TEAMS_WEBHOOK_URL is set. "
                     "Final log_activity row. Process exits. Runner commits memory + inbox files "
                     "back to main.",
                     TEAL),
        ],
        header_color=GREEN,
    ))

    story.append(PageBreak())

    # ── Cheat sheet
    story.append(card(
        "4. WHO COMMANDS WHOM — CHEAT SHEET",
        Paragraph(
            "Each layer issues one kind of instruction to the layer below it. "
            "Claude is the <b>decider</b>. MCP tools are the <b>hands</b>. "
            "GitHub Actions is the <b>scheduler</b>. The runner is the <b>machine</b>.",
            CARD_BODY,
        ),
        header_color=PURPLE,
    ))
    story.append(Spacer(1, 4))

    cheat_data = [
        ["Layer", "Actor", "Command issued", "To whom"],
        ["0", "You / cron",
         "workflow_dispatch or schedule fire", "GitHub Actions"],
        ["1", "GitHub Actions",
         "run this job", "Self-hosted Windows runner"],
        ["2", "Runner shell",
         "py -3 agent.py --task requirement-management", "Python agent.py"],
        ["3", "agent.py",
         "client.query(\"Run the Requirement Mgmt loop now…\")",
         "Claude CLI (local, Claude Max)"],
        ["4", "Claude (LLM)",
         "MCP tool calls: poll_emails, ingest_drive, read_inbox, search, publish, digest, log",
         "napco-nucleus MCP server"],
        ["5", "MCP tool fns",
         "HTTP / IMAP / SDK calls", "IMAP, Drive, Groq, GitLab, Teams, SQLite"],
        ["6", "Runner shell (post)",
         "git commit && git push", "GitHub repo"],
    ]
    col_widths = [10 * mm, 30 * mm, 80 * mm, 60 * mm]
    tbl = Table(cheat_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
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
    story.append(tbl)
    story.append(Spacer(1, 10))

    # ── Guardrails
    story.append(card(
        "5. GUARDRAILS",
        [
            Paragraph("•&nbsp;&nbsp;<b>Idempotency.</b> IMAP uses UIDVALIDITY plus since-UID checkpoint. Drive never re-processes a file ID. GitLab dedup runs in two layers: open-title match plus fuzzy match against requirements_seen in memory.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Dry-run mode.</b> workflow_dispatch accepts dry_run=true. Tools check NAPCO_NUCLEUS_DRY_RUN=1 and short-circuit every mutation: no SMTP, no GitLab create, no git push. Memory still logs the dry run.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Concurrency.</b> Workflow group requirement-management with cancel-in-progress=false. Runs queue, never overlap.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>State persistence.</b> nucleus_memory.db and data/requirements/ get committed back to main after every run, so the next run inherits the previous run's checkpoints and dedup history.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Allowlist.</b> Only IMAP senders in REQ_SENDER_ALLOWLIST are ingested. Random inbound mail is dropped.", BULLET),
            Paragraph("•&nbsp;&nbsp;<b>Language.</b> Task titles, descriptions, acceptance criteria are always written in English even when the source is Bangla, Malay, or any other language.", BULLET),
        ],
        header_color=GOLD,
    ))

    doc.build(story)
    return OUT_PATH


if __name__ == "__main__":
    out = build()
    print(f"Wrote {out}")
