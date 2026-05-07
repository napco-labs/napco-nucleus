"""One-shot: build the Requirement Management Workflow proposal PDF.

Uses reportlab. Output is a polished, single-document PDF intended for
management review. Mirrors the layout of the original draft PDF (navy
header bar, subtitle, metadata table, sectioned body) but with cleaned-
up content verified against the actual NAPCO Nucleus + TRW codebase.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table,
    TableStyle, KeepTogether, ListFlowable, ListItem,
)

# ─── Colors (sampled from original PDF) ───────────────────────────────
NAVY = colors.HexColor("#1F3A5F")
NAVY_DARK = colors.HexColor("#16294A")
ACCENT = colors.HexColor("#3B6FB6")
LIGHT_BLUE = colors.HexColor("#E8F0FA")
GREY_BORDER = colors.HexColor("#D8DEE6")
GREY_TEXT = colors.HexColor("#445064")
BODY_TEXT = colors.HexColor("#1F232B")

# ─── Output ───────────────────────────────────────────────────────────
HERE = Path(__file__).parent
OUT = HERE / "Requirement_Management_Workflow_Proposal.pdf"

# ─── Page template with title-bar header on first page ────────────────
PAGE_W, PAGE_H = LETTER
MARGIN = 0.75 * inch
TITLE_BAR_H = 1.4 * inch


def first_page(canvas, doc):
    canvas.saveState()
    # Navy title bar
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - TITLE_BAR_H, PAGE_W, TITLE_BAR_H, fill=1, stroke=0)
    # Title
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 26)
    canvas.drawString(MARGIN, PAGE_H - TITLE_BAR_H + 0.55 * inch,
                      "Requirement Management Workflow")
    # Subtitle
    canvas.setFont("Helvetica", 13)
    canvas.setFillColor(colors.HexColor("#C8D4E6"))
    canvas.drawString(MARGIN, PAGE_H - TITLE_BAR_H + 0.25 * inch,
                      "On-Demand Model for NAPCO Nucleus (NN)")
    # Footer rule
    canvas.setStrokeColor(GREY_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 0.55 * inch, PAGE_W - MARGIN, 0.55 * inch)
    # Footer text
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY_TEXT)
    canvas.drawString(MARGIN, 0.35 * inch,
                      "Prepared by Assad Zaman  |  Senior Software Test Engineer  |  Adaptive Enterprise Limited")
    canvas.drawRightString(PAGE_W - MARGIN, 0.35 * inch, f"Page {doc.page}")
    canvas.restoreState()


def later_page(canvas, doc):
    canvas.saveState()
    # Footer rule
    canvas.setStrokeColor(GREY_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 0.55 * inch, PAGE_W - MARGIN, 0.55 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY_TEXT)
    canvas.drawString(MARGIN, 0.35 * inch,
                      "Requirement Management Workflow  |  NAPCO Nucleus  |  Draft for Review")
    canvas.drawRightString(PAGE_W - MARGIN, 0.35 * inch, f"Page {doc.page}")
    canvas.restoreState()


# ─── Build flowables ──────────────────────────────────────────────────
def build():
    base = getSampleStyleSheet()["Normal"]

    body = ParagraphStyle(
        "Body", parent=base, fontName="Helvetica", fontSize=10.5,
        leading=15, textColor=BODY_TEXT, spaceAfter=8, alignment=TA_LEFT,
    )
    h1 = ParagraphStyle(
        "H1", parent=base, fontName="Helvetica-Bold", fontSize=15,
        leading=20, textColor=NAVY, spaceBefore=14, spaceAfter=8,
        leftIndent=10, borderPadding=4,
    )
    bullet_style = ParagraphStyle(
        "Bullet", parent=body, fontSize=10.5, leading=15,
        leftIndent=18, bulletIndent=6, spaceAfter=4,
    )
    th = ParagraphStyle(
        "TH", parent=body, fontName="Helvetica-Bold", fontSize=10,
        textColor=NAVY_DARK, leading=13,
    )
    td = ParagraphStyle(
        "TD", parent=body, fontName="Helvetica", fontSize=10,
        textColor=BODY_TEXT, leading=13, spaceAfter=0,
    )
    italic_small = ParagraphStyle(
        "FootByline", parent=body, fontName="Helvetica-Oblique", fontSize=9,
        textColor=GREY_TEXT, alignment=TA_CENTER, spaceBefore=14,
    )

    flow = []

    # ── Spacing under title bar
    flow.append(Spacer(1, 0.45 * inch))

    # ── Metadata table
    meta = [
        [Paragraph("<b>Owner</b>", th), Paragraph("Assad Zaman", td),
         Paragraph("<b>Date</b>", th), Paragraph("7 May 2026", td)],
        [Paragraph("<b>System</b>", th), Paragraph("NAPCO Nucleus (NN)", td),
         Paragraph("<b>Status</b>", th), Paragraph('<font color="#1F3A5F"><b>DRAFT FOR REVIEW</b></font>', td)],
    ]
    meta_tbl = Table(meta, colWidths=[0.9 * inch, 2.7 * inch, 0.9 * inch, 2.5 * inch])
    meta_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, GREY_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    flow.append(meta_tbl)
    flow.append(Spacer(1, 0.25 * inch))

    # ── 1. Purpose
    flow.append(Paragraph("1. Purpose", h1))
    flow.append(Paragraph(
        "Client requirements arrive across fragmented channels — Microsoft Teams calls, "
        "Teams chats and DMs, email, and Google Drive. Consolidating them into auditable "
        "documents is presently a manual, time-consuming task. This workflow puts "
        "<b>NAPCO Nucleus</b> behind that capture, while keeping every outbound action under "
        "direct human control.", body))

    # ── 2. Operating Principles
    flow.append(Paragraph("2. Operating Principles", h1))
    flow.append(Paragraph(
        "Four non-negotiable principles govern this workflow:", body))
    principles = [
        "<b>User-triggered.</b> NAPCO Nucleus performs work only on explicit command. "
        "There is no scheduled background polling of any channel.",
        "<b>Human-in-the-loop.</b> Every requirement document is reviewed by Assad "
        "before any email draft is composed.",
        "<b>No automated outbound email.</b> NAPCO Nucleus prepares the draft and the "
        "attachment. Assad sends the email himself, from his own mail client.",
        "<b>Speaker attribution preserved on calls.</b> Assad's voice and the other "
        "party's voice are recorded on separate tracks so summaries cannot misattribute "
        "who said what.",
    ]
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_style), leftIndent=18, value="circle") for t in principles],
        bulletType="bullet", start="circle", leftIndent=12,
    ))

    # ── 3. Input Channels
    flow.append(Paragraph("3. Input Channels", h1))
    channels_header = [
        Paragraph("<b>Channel</b>", th),
        Paragraph("<b>Mechanism</b>", th),
        Paragraph("<b>What it captures</b>", th),
    ]
    channels_rows = [
        [Paragraph("<b>Teams audio calls</b>", td),
         Paragraph("Local recording — microphone + system loopback", td),
         Paragraph("Dual-track audio; transcribed and translated to English "
                   "(faster-whisper large-v3)", td)],
        [Paragraph("<b>Teams messages</b>", td),
         Paragraph("Reads Teams desktop's local message cache", td),
         Paragraph("Group chats and DMs, queryable by chat name and time range", td)],
        [Paragraph("<b>Email</b>", td),
         Paragraph("IMAP poll of allowlisted senders", td),
         Paragraph("Message bodies, plus PDF / Word .docx / plain text attachments extracted to text", td)],
        [Paragraph("<b>Google Drive</b>", td),
         Paragraph("Drive API + content extractors", td),
         Paragraph("Audio (Whisper), PDF (pypdf), Word .docx (python-docx), plain text", td)],
    ]
    channels_tbl = Table(
        [channels_header] + channels_rows,
        colWidths=[1.3 * inch, 2.3 * inch, 3.4 * inch],
        repeatRows=1,
    )
    channels_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, GREY_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    flow.append(channels_tbl)

    # ── 4. Core Workflow Steps
    flow.append(Paragraph("4. Core Workflow Steps", h1))
    steps = [
        "<b>Capture.</b> Assad triggers a read or recording for the channel he wants.",
        "<b>Process.</b> NAPCO Nucleus handles transcription, translation, or parsing as the channel requires.",
        "<b>Output.</b> A structured Microsoft Word document is produced for Assad's review.",
        "<b>Final action.</b> On request, NAPCO Nucleus composes a draft email with the document attached. Assad reviews and sends it manually.",
    ]
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_style), leftIndent=22) for t in steps],
        bulletType="1", leftIndent=14,
    ))

    # ── 5. Technical Foundation
    flow.append(Paragraph("5. Technical Foundation", h1))
    flow.append(Paragraph(
        "The workflow reuses components already present in the <i>napco-labs</i> codebase. "
        "No new external services and no new self-hosted runners are required.", body))
    foundation = [
        "<b>Teams Requirement Watcher (TRW)</b> — existing call-recording and "
        "call-transcription pipeline. Bangla → English translation is built in.",
        "<b>NAPCO Nucleus core</b> — existing Word document writers, IMAP email reader, "
        "and Google Drive content ingest.",
    ]
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_style), leftIndent=18) for t in foundation],
        bulletType="bullet", leftIndent=12,
    ))

    # ── 6. Items Pending Approval (keep together so it doesn't split)
    pending = []
    pending.append(Paragraph("6. Items Pending Approval", h1))
    pending.append(Paragraph(
        "Before implementation continues, three items need confirmation:", body))
    items = [
        "The proposed on-demand operational model.",
        "The designated Google Drive folder for audio archival.",
        "Confirmation that direct OpenProject integration is <b>not</b> required at this stage.",
    ]
    pending.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_style), leftIndent=22) for t in items],
        bulletType="1", leftIndent=14,
    ))
    flow.append(KeepTogether(pending))

    return flow


def main() -> None:
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=LETTER,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=TITLE_BAR_H + 0.05 * inch,
        bottomMargin=0.7 * inch,
        title="Requirement Management Workflow",
        author="Assad Zaman",
        subject="On-Demand Model for NAPCO Nucleus",
    )

    frame_first = Frame(
        MARGIN, doc.bottomMargin,
        PAGE_W - 2 * MARGIN,
        PAGE_H - TITLE_BAR_H - doc.bottomMargin - 0.05 * inch,
        id="first", showBoundary=0,
    )
    frame_later = Frame(
        MARGIN, doc.bottomMargin,
        PAGE_W - 2 * MARGIN,
        PAGE_H - 0.7 * inch - doc.bottomMargin,
        id="later", showBoundary=0,
    )

    doc.addPageTemplates([
        PageTemplate(id="First", frames=[frame_first], onPage=first_page),
        PageTemplate(id="Later", frames=[frame_later], onPage=later_page),
    ])

    doc.build(build())
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
