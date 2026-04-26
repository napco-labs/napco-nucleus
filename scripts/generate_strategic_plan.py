"""Render the NAPCO Nucleus AI Agent — Operational Blueprint as a PDF.

Run:
    py -3 scripts/generate_strategic_plan.py
Output:
    docs/NAPCO-Nucleus-Strategic-Plan.pdf
"""
from __future__ import annotations

import math
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as canvas_mod
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import Flowable


# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------

NAVY = colors.HexColor("#1F3864")
NAVY_DEEP = colors.HexColor("#15294A")
OCHRE = colors.HexColor("#C68F35")
INK = colors.HexColor("#1B1B1B")
MUTED = colors.HexColor("#5A5A5A")
RULE = colors.HexColor("#D9D9D9")
SOFT_BG = colors.HexColor("#F2F2F8")
TABLE_HDR = colors.HexColor("#E9EDF5")
GREEN_LIVE = colors.HexColor("#1F6F37")
PILL_GREEN_BG = colors.HexColor("#DCEFE0")
AMBER = colors.HexColor("#B8860B")

# Dimension accents
TEAL = colors.HexColor("#0E7C7B")
TEAL_TINT = colors.HexColor("#E0F1F1")
CORAL = colors.HexColor("#C24D2C")
CORAL_TINT = colors.HexColor("#FBE7DF")
PURPLE = colors.HexColor("#5B3C88")
PURPLE_TINT = colors.HexColor("#EDE6F5")
SLATE = colors.HexColor("#36506E")
SLATE_TINT = colors.HexColor("#E5ECF2")

# Architecture diagram
BOX_FILL = colors.HexColor("#EAF0FA")
BOX_FILL_FUTURE = colors.HexColor("#FBF2DE")
BOX_FILL_LLM = colors.HexColor("#FFF7E1")
BOX_FILL_EXT = colors.HexColor("#F4F4F4")

PRINCIPLE_ACCENTS = [NAVY, TEAL, CORAL, OCHRE, PURPLE, GREEN_LIVE]

CONTENT_W = 170 * mm  # frame width on A4 with 20 mm side margins


# --------------------------------------------------------------------------
# Paragraph styles
# --------------------------------------------------------------------------

styles = getSampleStyleSheet()

BODY = ParagraphStyle(
    "Body", parent=styles["BodyText"], fontName="Helvetica",
    fontSize=10.5, leading=14.5, textColor=INK, alignment=TA_JUSTIFY,
    spaceAfter=8,
)
H1_BANNER_TXT = ParagraphStyle(
    "H1Banner", parent=BODY, fontName="Helvetica-Bold",
    fontSize=18, leading=22, textColor=colors.white, alignment=TA_LEFT,
    spaceAfter=0, spaceBefore=0,
)
SUB_AFTER_BANNER = ParagraphStyle(
    "SubBanner", parent=BODY, fontName="Helvetica-Oblique",
    fontSize=10.5, leading=13, textColor=OCHRE, alignment=TA_LEFT,
    spaceAfter=8, spaceBefore=2,
)
H3 = ParagraphStyle(
    "H3", parent=styles["Heading3"], fontName="Helvetica-Bold",
    fontSize=12.5, leading=16, textColor=NAVY, spaceAfter=4, spaceBefore=10,
)
TITLE = ParagraphStyle(
    "Title", parent=styles["Title"], fontName="Helvetica-Bold",
    fontSize=34, leading=40, textColor=colors.white, alignment=TA_CENTER,
    spaceAfter=4,
)
TITLE_SUB = ParagraphStyle(
    "TitleSub", parent=styles["Normal"], fontName="Helvetica",
    fontSize=18, leading=22, textColor=OCHRE, alignment=TA_CENTER,
    spaceAfter=24,
)
META_LABEL = ParagraphStyle(
    "MetaLabel", parent=styles["Normal"], fontName="Helvetica",
    fontSize=10, leading=14, textColor=MUTED, alignment=TA_CENTER,
)
META_VAL = ParagraphStyle(
    "MetaVal", parent=styles["Normal"], fontName="Helvetica-Bold",
    fontSize=11.5, leading=15, textColor=INK, alignment=TA_CENTER,
    spaceAfter=10,
)
CALLOUT = ParagraphStyle(
    "Callout", parent=BODY, fontName="Helvetica-Oblique",
    backColor=SOFT_BG, borderPadding=10, leftIndent=0, rightIndent=0,
    textColor=NAVY,
)


# --------------------------------------------------------------------------
# Reusable building blocks
# --------------------------------------------------------------------------

def section_header(title, subtitle=None, bg=NAVY, accent=OCHRE):
    """A full-width colored banner with reversed-out title and an accent stripe."""
    banner = Table(
        [[Paragraph(title, H1_BANNER_TXT)]],
        colWidths=[CONTENT_W],
    )
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LINEBELOW", (0, -1), (-1, -1), 3, accent),
    ]))
    out = [banner]
    if subtitle:
        out.append(Spacer(1, 4))
        out.append(Paragraph(subtitle, SUB_AFTER_BANNER))
    out.append(Spacer(1, 6))
    return out


def principle(label, body, accent):
    """A colored side-bar bullet for the Core Principles list."""
    label_style = ParagraphStyle(
        "PrincipleLabel", parent=BODY, fontName="Helvetica-Bold",
        fontSize=10.5, leading=14, textColor=accent, alignment=TA_LEFT,
        spaceAfter=2,
    )
    body_style = ParagraphStyle(
        "PrincipleBody", parent=BODY, fontSize=10, leading=14,
        alignment=TA_LEFT, spaceAfter=0,
    )
    inner = [
        [Paragraph(label, label_style)],
        [Paragraph(body, body_style)],
    ]
    tbl = Table(inner, colWidths=[CONTENT_W - 6])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (0, 0), 7),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
        ("TOPPADDING", (0, 1), (0, 1), 0),
        ("LINEBEFORE", (0, 0), (0, -1), 4, accent),
    ]))
    return [KeepTogether([tbl, Spacer(1, 4)])]


def workflow_card(title, process, action, result, accent=OCHRE, tint=SOFT_BG):
    """A workflow Process / Action / Result card with a colored accent strip."""
    title_style = ParagraphStyle(
        "WFTitle", parent=BODY, fontName="Helvetica-Bold",
        fontSize=12.5, leading=16, textColor=accent, alignment=TA_LEFT,
        spaceAfter=4, spaceBefore=4,
    )
    label_style = ParagraphStyle(
        "WFLabel", parent=BODY, fontName="Helvetica-Bold",
        fontSize=10, leading=13, textColor=accent, alignment=TA_LEFT,
        spaceAfter=0,
    )
    body_style = ParagraphStyle(
        "WFBody", parent=BODY, fontSize=10, leading=14, alignment=TA_LEFT,
        spaceAfter=0,
    )

    data = [
        [Paragraph("Process", label_style), Paragraph(process, body_style)],
        [Paragraph("Action", label_style), Paragraph(action, body_style)],
        [Paragraph("Result", label_style), Paragraph(result, body_style)],
    ]
    tbl = Table(data, colWidths=[26 * mm, CONTENT_W - 26 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), tint),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
        ("LINEBEFORE", (0, 0), (0, -1), 4, accent),
    ]))
    return KeepTogether([Paragraph(title, title_style), tbl, Spacer(1, 8)])


def styled_table(rows, col_widths, header_bg=NAVY, header_fg=colors.white,
                 zebra=True, accent_below_header=OCHRE):
    """Wrap each cell in a Paragraph and apply consistent header styling."""
    cell_body = ParagraphStyle(
        "TblBody", parent=BODY, fontSize=9.5, leading=13,
        alignment=TA_LEFT, spaceAfter=0,
    )
    cell_label = ParagraphStyle(
        "TblLabel", parent=BODY, fontName="Helvetica-Bold", fontSize=9.5,
        leading=13, textColor=NAVY, alignment=TA_LEFT, spaceAfter=0,
    )
    hdr = ParagraphStyle(
        "TblHdr", parent=BODY, fontName="Helvetica-Bold", fontSize=10,
        leading=13, textColor=header_fg, alignment=TA_LEFT, spaceAfter=0,
    )

    def wrap(cell, is_hdr, is_first_col):
        if isinstance(cell, Paragraph):
            return cell
        if is_hdr:
            return Paragraph(cell, hdr)
        if is_first_col:
            return Paragraph(cell, cell_label)
        return Paragraph(cell, cell_body)

    wrapped = [
        [wrap(c, r == 0, j == 0) for j, c in enumerate(row)]
        for r, row in enumerate(rows)
    ]

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, 0), 2, accent_below_header),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, RULE),
    ]
    if zebra:
        style.append(("ROWBACKGROUNDS", (0, 1), (-1, -1),
                      [colors.white, colors.HexColor("#FAFAFC")]))
    tbl = Table(wrapped, colWidths=col_widths)
    tbl.setStyle(TableStyle(style))
    return tbl


def open_items_card(category, items, accent, tint):
    """A category card with a colored left strip and a tight bullet list."""
    cat_style = ParagraphStyle(
        "OpenCat", parent=BODY, fontName="Helvetica-Bold",
        fontSize=12, leading=15, textColor=accent, alignment=TA_LEFT,
        spaceAfter=4, spaceBefore=0,
    )
    item_style = ParagraphStyle(
        "OpenItem", parent=BODY, fontSize=9.5, leading=13,
        alignment=TA_LEFT, spaceAfter=2, leftIndent=14, firstLineIndent=-14,
    )

    inner = [[Paragraph(category, cat_style)]]
    for item in items:
        inner.append([Paragraph("&bull;&nbsp;&nbsp;" + item, item_style)])

    tbl = Table(inner, colWidths=[CONTENT_W - 6])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), tint),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 0),
        ("LINEBEFORE", (0, 0), (0, -1), 4, accent),
    ]))
    return KeepTogether([tbl, Spacer(1, 6)])


def live_pill():
    """A rounded green pill saying LIVE."""
    style = ParagraphStyle(
        "LivePill", parent=BODY, fontName="Helvetica-Bold",
        fontSize=8.5, leading=11, textColor=GREEN_LIVE,
        alignment=TA_CENTER, spaceAfter=0,
    )
    p = Paragraph("LIVE", style)
    t = Table([[p]], colWidths=[14 * mm], rowHeights=[6 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PILL_GREEN_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, GREEN_LIVE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


# --------------------------------------------------------------------------
# Architecture diagram flowable
# --------------------------------------------------------------------------

class ArchitectureDiagram(Flowable):
    """Multi-box architecture diagram with labeled arrows, drawn from scratch."""

    def __init__(self, width=170 * mm, height=210 * mm):
        super().__init__()
        self.width = width
        self.height = height

    def _box(self, c, x, y, w, h, title, subtitle, fill, border=NAVY,
             title_color=NAVY, dashed=False):
        c.setStrokeColor(border)
        c.setFillColor(fill)
        c.setLineWidth(1.1)
        if dashed:
            c.setDash(3, 3)
        else:
            c.setDash()
        c.roundRect(x, y, w, h, 4, stroke=1, fill=1)
        c.setDash()

        c.setFillColor(title_color)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(x + w / 2, y + h - 13, title)

        c.setFillColor(MUTED)
        c.setFont("Helvetica", 8)
        if isinstance(subtitle, str):
            subtitle = [subtitle]
        line_y = y + h - 25
        for line in subtitle:
            c.drawCentredString(x + w / 2, line_y, line)
            line_y -= 10

    def _arrow(self, c, x1, y1, x2, y2, label=None, dashed=False):
        c.setStrokeColor(NAVY)
        c.setFillColor(NAVY)
        c.setLineWidth(1.0)
        c.setDash(3, 3) if dashed else c.setDash()
        c.line(x1, y1, x2, y2)
        ang = math.atan2(y2 - y1, x2 - x1)
        ah = 5
        c.setDash()
        p = c.beginPath()
        p.moveTo(x2, y2)
        p.lineTo(x2 - ah * math.cos(ang - 0.4), y2 - ah * math.sin(ang - 0.4))
        p.lineTo(x2 - ah * math.cos(ang + 0.4), y2 - ah * math.sin(ang + 0.4))
        p.close()
        c.drawPath(p, stroke=0, fill=1)
        if label:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2 + 4
            c.setFont("Helvetica-Oblique", 7.5)
            tw = c.stringWidth(label, "Helvetica-Oblique", 7.5)
            c.setFillColor(colors.white)
            c.rect(mx - tw / 2 - 2, my - 2, tw + 4, 9, stroke=0, fill=1)
            c.setFillColor(MUTED)
            c.drawCentredString(mx, my, label)

    def _l_arrow(self, c, points, label=None, dashed=False):
        c.setStrokeColor(NAVY)
        c.setFillColor(NAVY)
        c.setLineWidth(1.0)
        c.setDash(3, 3) if dashed else c.setDash()
        for (x1, y1), (x2, y2) in zip(points[:-1], points[1:]):
            c.line(x1, y1, x2, y2)
        c.setDash()
        (x1, y1), (x2, y2) = points[-2], points[-1]
        ang = math.atan2(y2 - y1, x2 - x1)
        ah = 5
        p = c.beginPath()
        p.moveTo(x2, y2)
        p.lineTo(x2 - ah * math.cos(ang - 0.4), y2 - ah * math.sin(ang - 0.4))
        p.lineTo(x2 - ah * math.cos(ang + 0.4), y2 - ah * math.sin(ang + 0.4))
        p.close()
        c.drawPath(p, stroke=0, fill=1)
        if label:
            best = max(zip(points[:-1], points[1:]),
                       key=lambda seg: (seg[0][0] - seg[1][0]) ** 2
                       + (seg[0][1] - seg[1][1]) ** 2)
            (sx1, sy1), (sx2, sy2) = best
            mx = (sx1 + sx2) / 2
            my = (sy1 + sy2) / 2 + 4
            c.setFont("Helvetica-Oblique", 7.5)
            tw = c.stringWidth(label, "Helvetica-Oblique", 7.5)
            c.setFillColor(colors.white)
            c.rect(mx - tw / 2 - 2, my - 2, tw + 4, 9, stroke=0, fill=1)
            c.setFillColor(MUTED)
            c.drawCentredString(mx, my, label)

    def draw(self):
        c = self.canv
        W, H = self.width, self.height

        bw_lg = 70 * mm
        bw_md = 55 * mm
        bh_md = 22 * mm

        # Row 1
        wp_x, wp_y = 5 * mm, H - bh_md
        gl_x, gl_y = W - bw_md - 5 * mm, H - bh_md
        self._box(c, wp_x, wp_y, bw_md, bh_md, "Working PC",
                  ["Develop, review,", "trigger workflow_dispatch"], BOX_FILL)
        self._box(c, gl_x, gl_y, bw_md, bh_md, "GitLab (task sink)",
                  ["Three-hour atomic tasks", "from requirements"],
                  BOX_FILL_FUTURE, border=OCHRE, title_color=OCHRE)

        # Row 2
        gh_w = bw_lg
        gh_x = (W - gh_w) / 2
        gh_y = H - bh_md - 18 * mm - bh_md
        self._box(c, gh_x, gh_y, gh_w, bh_md, "GitHub Actions",
                  ["Scheduler / orchestrator", "cron + workflow_dispatch"],
                  BOX_FILL)

        # Row 3
        vm_w = bw_lg
        vm_x = (W - vm_w) / 2 - 22 * mm
        vm_y = gh_y - 22 * mm - bh_md
        self._box(c, vm_x, vm_y, vm_w, bh_md, "Self-hosted Windows VM",
                  ["agent.py + Claude Agent SDK",
                   "Claude CLI logged in (Max plan)"], BOX_FILL)
        cl_w = bw_md
        cl_x = vm_x + vm_w + 10 * mm
        cl_y = vm_y
        self._box(c, cl_x, cl_y, cl_w, bh_md, "Claude Opus 4.7",
                  ["via Claude CLI", "(Anthropic cloud)"], BOX_FILL_LLM,
                  border=OCHRE, title_color=OCHRE)

        # Row 4
        col_y = vm_y - 22 * mm - bh_md
        in_w = bw_md - 5 * mm
        in_x = 5 * mm
        self._box(c, in_x, col_y, in_w, bh_md, "Inputs",
                  ["Google Drive (audio + PDF)",
                   "Gmail IMAP allowlist",
                   "Teams via Power Automate"], BOX_FILL_EXT,
                  border=MUTED, title_color=NAVY)
        mem_w = bw_md - 5 * mm
        mem_x = (W - mem_w) / 2
        self._box(c, mem_x, col_y, mem_w, bh_md, "Memory",
                  ["SQLite + FTS5 dedup",
                   "Activity, requirements,",
                   "test runs, checkpoints"], BOX_FILL)
        sib_w = bw_md - 5 * mm
        sib_x = W - sib_w - 5 * mm
        self._box(c, sib_x, col_y, sib_w, bh_md, "Sibling test projects",
                  ["MVP-Access-API-Test",
                   "E2E / Easy-E2E / Release"], BOX_FILL_EXT,
                  border=MUTED, title_color=NAVY)

        # Row 5
        out_y = col_y - 22 * mm - bh_md
        out_w = bw_lg + 10 * mm
        out_x = (W - out_w) / 2
        self._box(c, out_x, out_y, out_w, bh_md, "Outputs",
                  ["GitLab issues  •  SMTP email reports (PDF)  •  Teams digest"],
                  BOX_FILL)

        # Arrows
        self._arrow(c, wp_x + bw_md / 2, wp_y, gh_x + 18 * mm, gh_y + bh_md,
                    label="git push")
        self._arrow(c, gh_x + gh_w / 2, gh_y, vm_x + vm_w / 2, vm_y + bh_md,
                    label="dispatch + cron")
        self._arrow(c, vm_x + vm_w, vm_y + bh_md * 0.65,
                    cl_x, cl_y + bh_md * 0.65, label="prompt")
        self._arrow(c, cl_x, cl_y + bh_md * 0.35,
                    vm_x + vm_w, vm_y + bh_md * 0.35, label="response")
        self._arrow(c, in_x + in_w / 2, col_y + bh_md,
                    vm_x + vm_w * 0.25, vm_y, label="ingest")
        self._arrow(c, sib_x + sib_w / 2, col_y + bh_md,
                    vm_x + vm_w * 0.75, vm_y, label="invoke")
        self._arrow(c, vm_x + vm_w * 0.5, vm_y,
                    mem_x + mem_w / 2, col_y + bh_md, label="read / write")
        self._arrow(c, mem_x + mem_w / 2, col_y,
                    out_x + out_w / 2, out_y + bh_md, label="ship")

        right_gutter = W - 2 * mm
        self._l_arrow(c, [
            (out_x + out_w, out_y + bh_md / 2),
            (right_gutter, out_y + bh_md / 2),
            (right_gutter, gl_y + bh_md / 2),
            (gl_x + bw_md, gl_y + bh_md / 2),
        ], label="issues", dashed=True)


# --------------------------------------------------------------------------
# Cover hero flowable — colored block behind the title
# --------------------------------------------------------------------------

class CoverHero(Flowable):
    """A 3D cover hero — drop shadow, bevel highlights, layered ochre stripe,
    and a text drop shadow for the title."""

    def __init__(self, width=CONTENT_W, height=75 * mm):
        super().__init__()
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        W, H = self.width, self.height

        # 3D palette
        SHADOW = colors.HexColor("#9CA0AE")
        NAVY_HIGHLIGHT = colors.HexColor("#2C4F87")
        NAVY_DEEPER = colors.HexColor("#0A1530")
        OCHRE_SHADOW = colors.HexColor("#7B5621")

        # Geometry — the navy block is inset 3pt from each side so the drop
        # shadow can extend beyond it without leaving the flowable bounds.
        block_left = 3
        block_w = W - 6
        block_bot = 18 * mm
        block_top = H - 4 * mm
        block_h = block_top - block_bot
        cx = block_left + block_w / 2

        ochre_y = 13.5 * mm
        ochre_h = 3.5 * mm

        # 1) Drop shadow under the navy block
        c.setFillColor(SHADOW)
        c.roundRect(block_left + 4, block_bot - 4, block_w, block_h, 6,
                    stroke=0, fill=1)

        # 2) Main navy block
        c.setFillColor(NAVY_DEEP)
        c.roundRect(block_left, block_bot, block_w, block_h, 6,
                    stroke=0, fill=1)

        # 3) Top bevel highlight — narrow lighter band just below the top edge
        c.setFillColor(NAVY_HIGHLIGHT)
        c.rect(block_left + 5, block_top - 8, block_w - 10, 4,
               stroke=0, fill=1)

        # 4) Bottom depth shadow — narrow darker band just above the base
        c.setFillColor(NAVY_DEEPER)
        c.rect(block_left + 5, block_bot + 3, block_w - 10, 3,
               stroke=0, fill=1)

        # 5) Ochre stripe with its own drop shadow
        c.setFillColor(OCHRE_SHADOW)
        c.rect(block_left + 4, ochre_y - 3, block_w, ochre_h,
               stroke=0, fill=1)
        c.setFillColor(OCHRE)
        c.rect(block_left, ochre_y, block_w, ochre_h, stroke=0, fill=1)

        # 6) Title — drop shadow + white text
        title = "NAPCO Nucleus AI Agent"
        c.setFont("Helvetica-Bold", 30)
        title_y = block_bot + block_h / 2 - 10
        c.setFillColor(NAVY_DEEPER)
        c.drawCentredString(cx + 1.8, title_y - 1.8, title)
        c.setFillColor(colors.white)
        c.drawCentredString(cx, title_y, title)

        # 7) Subtitle below the ochre stripe — soft ochre shadow + ochre text
        sub = "Operational Blueprint"
        c.setFont("Helvetica", 18)
        c.setFillColor(OCHRE_SHADOW)
        c.drawCentredString(cx + 1, 3, sub)
        c.setFillColor(OCHRE)
        c.drawCentredString(cx, 4, sub)


# --------------------------------------------------------------------------
# Page chrome
# --------------------------------------------------------------------------

def on_page(canvas: canvas_mod.Canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(OCHRE)
    canvas.setLineWidth(1.4)
    canvas.line(20 * mm, h - 18 * mm, w - 20 * mm, h - 18 * mm)
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(20 * mm, 18 * mm, w - 20 * mm, 18 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 13 * mm,
                      "NAPCO Nucleus AI Agent  |  Mohammad Kamrul Hasan")
    canvas.drawRightString(w - 20 * mm, 13 * mm, f"Page {doc.page}")
    canvas.restoreState()


def on_cover(canvas: canvas_mod.Canvas, doc):
    canvas.saveState()
    w, h = A4
    # Top + bottom ochre rules frame the page
    canvas.setStrokeColor(OCHRE)
    canvas.setLineWidth(2)
    canvas.line(20 * mm, h - 25 * mm, w - 20 * mm, h - 25 * mm)
    canvas.line(20 * mm, 25 * mm, w - 20 * mm, 25 * mm)
    # Corner accent squares
    canvas.setFillColor(OCHRE)
    canvas.rect(20 * mm - 1, h - 25 * mm - 4, 4, 4, stroke=0, fill=1)
    canvas.rect(w - 20 * mm - 3, h - 25 * mm - 4, 4, 4, stroke=0, fill=1)
    canvas.rect(20 * mm - 1, 25 * mm, 4, 4, stroke=0, fill=1)
    canvas.rect(w - 20 * mm - 3, 25 * mm, 4, 4, stroke=0, fill=1)
    canvas.restoreState()


# --------------------------------------------------------------------------
# Content
# --------------------------------------------------------------------------

def cover_story():
    return [
        Spacer(1, 38 * mm),
        CoverHero(),
        Spacer(1, 22 * mm),
        Paragraph("Architect", META_LABEL),
        Paragraph("Mohammad Kamrul Hasan", META_VAL),
        Spacer(1, 4),
        Paragraph("Focus", META_LABEL),
        Paragraph(
            "Project Management  |  Test Automation  |  DevOps / Release Automation",
            META_VAL,
        ),
        Spacer(1, 14 * mm),
        Paragraph("April 2026", META_LABEL),
        PageBreak(),
    ]


def overview():
    out = []
    out.extend(section_header(
        "Overview",
        "What NAPCO Nucleus AI Agent does and why it exists.",
    ))
    out.extend([
        Paragraph(
            "NAPCO Nucleus AI Agent is a Claude-native AI deputy built to remove the "
            "daily friction from three operational dimensions inside NAPCO: "
            "<b>Project Management</b> (requirement intake and stakeholder reporting), "
            "<b>Test Automation</b> (API functional, integration, load, and "
            "end-to-end testing of the MVP Access platform), and "
            "<b>DevOps / Release Automation</b> (the nightly TFS pull, .NET build, "
            "and IIS deploy that primes the test cycle). It runs on a self-hosted "
            "Windows VM under GitHub Actions, calls Claude Opus 4.7 through the "
            "locally authenticated Claude CLI, and ships its outputs as PDF email "
            "reports, GitLab issues, and an optional Teams digest.",
            BODY,
        ),
        Paragraph(
            "The architecture is borrowed from the Digital Deputy framework but tuned "
            "for a single-engineer use case at NAPCO. The agent does the heavy lifting "
            "(transcription, dedupe, splitting, analysis, reporting) so that the "
            "engineer stays focused on judgment work: which regression is real, which "
            "requirement needs clarification, which release is ready to ship.",
            BODY,
        ),
        Paragraph(
            "All seven workflows are live in production, scheduled on the self-hosted "
            "runner, and observable through a single SQLite memory store and one "
            "consolidated morning email.",
            BODY,
        ),
    ])

    out.extend(section_header("Core Principles",
                              "The rules every workflow inherits.",
                              bg=NAVY))

    principles = [
        ("Claude does the reasoning, Python does the doing.",
         "Every agent run is a single Claude Agent SDK turn. The Python tools handle "
         "deterministic work (file reads, API calls, SQL writes, SMTP sends); Claude "
         "handles judgment (splitting requirements, analyzing failures, drafting reports)."),
        ("Memory at every gate.",
         "Every prompt opens with a mandatory check-in to <i>nucleus_memory.db</i>. "
         "The agent never cold-starts: it recalls past activity, prior requirements, "
         "and recent test trends before doing fresh work."),
        ("Idempotent by construction.",
         "Requirements are deduped via FTS5 fuzzy match before they hit GitLab. "
         "Test runs are keyed by date and suite. Re-running a workflow is safe; it "
         "will not double-write."),
        ("One email per day.",
         "The four test workflows write results to memory but do <i>not</i> send "
         "per-run emails. The Daily Report consolidates everything into a single "
         "morning PDF so the team's inbox stays clean."),
        ("No API keys in CI.",
         "Reasoning is billed against the engineer's Claude Max subscription via the "
         "locally authenticated CLI on the self-hosted runner. The cloud runner has "
         "no Anthropic credentials and never will."),
        ("Dry run is a first-class mode.",
         "<i>--dry-run</i> on any task runs every step except the mutating ones (no "
         "SMTP send, no GitLab create, no git push). Used on every prompt change "
         "before promoting it to the schedule."),
    ]
    for i, (label, body) in enumerate(principles):
        out.extend(principle(label, body, PRINCIPLE_ACCENTS[i % len(PRINCIPLE_ACCENTS)]))

    out.append(PageBreak())
    return out


def architecture_section():
    out = []
    out.extend(section_header(
        "System Architecture",
        "How the pieces talk to each other when a workflow fires.",
        bg=NAVY,
    ))
    out.append(ArchitectureDiagram())
    out.append(Spacer(1, 6))
    out.append(Paragraph(
        "The working PC is the development surface. GitHub Actions is the scheduler "
        "that fires workflows on cron or on demand. Each workflow targets the "
        "self-hosted Windows VM, where <i>agent.py</i> loads the shared "
        "<i>system.md</i> plus the task-specific prompt and runs one Claude Agent "
        "SDK turn against Claude Opus 4.7 (via the locally authenticated Claude "
        "CLI). Claude calls back into 36 MCP tools (memory, requirements, tests, "
        "report, files) which read inputs from Google Drive, Gmail IMAP, and four "
        "sibling test projects, write state to <i>nucleus_memory.db</i>, and ship "
        "outputs as GitLab issues, SMTP-delivered PDF reports, and an optional "
        "Teams digest.",
        BODY,
    ))
    out.append(PageBreak())
    return out


def architecture_table():
    rows = [
        ["Layer", "Description"],
        ["Reasoning core",
         "Claude Agent SDK running against Claude Opus 4.7. The agent handles all "
         "judgment work: requirement splitting, fuzzy dedup gating, test-failure "
         "root cause, report drafting."],
        ["Persistent memory",
         "SQLite (nucleus_memory.db) with FTS5 indices over activity_logs, "
         "requirements_seen, test_run_history, email_checkpoints, drive_processed. "
         "Committed to the repo so memory travels with git clone."],
        ["Tools layer",
         "36 MCP tools split across five submodules &mdash; memory, requirements, "
         "tests, report, files. The agent calls them; they wrap deterministic "
         "helpers (IMAP, Drive, Whisper, GitLab, SMTP, Newman, Locust, pytest, "
         "Playwright)."],
        ["Orchestration",
         "GitHub Actions on a self-hosted Windows runner. Seven workflow files: six "
         "task workflows plus a probe-runner health check. Concurrency groups "
         "prevent overlapping runs of the same task."],
        ["Inputs",
         "Gmail IMAP with sender allowlist, Google Drive folder for audio meetings "
         "(routed through Groq Whisper) and PDFs (parsed via pypdf), and four "
         "sibling test projects under E:/Projects/ that the test workflows invoke."],
        ["Outputs",
         "GitLab issues (three-hour atomic tasks), PDF email reports through SMTP, "
         "and an optional Microsoft Teams digest webhook for at-a-glance status."],
    ]
    out = []
    out.extend(section_header(
        "Architecture at a Glance",
        "Six layers, one consistent operational posture.",
        bg=NAVY,
    ))
    out.append(styled_table(rows, [38 * mm, CONTENT_W - 38 * mm]))
    out.append(PageBreak())
    return out


def dim1_section():
    out = []
    out.extend(section_header(
        "Dimension 1 &mdash; Project Management",
        "Requirement flow and stakeholder visibility.",
        bg=TEAL,
    ))
    out.append(workflow_card(
        "Workflow 1.1 &mdash; Requirement Management",
        "Fires every two hours during business hours (09:00&ndash;17:00 BDT, "
        "Sunday&ndash;Thursday). Polls Gmail IMAP for emails from an allowlisted "
        "sender set and scans a designated Google Drive folder for new meeting "
        "audio (routed through Groq Whisper, model whisper-large-v3-turbo, 25 MB "
        "per file) and PDFs (parsed via pypdf).",
        "Claude reads the requirement inbox, fuzzy-matches each candidate against "
        "the FTS5 index of past requirements to suppress duplicates, splits "
        "approved items into ~3-hour atomic tasks with acceptance criteria, and "
        "calls the GitLab v4 REST API.",
        "Tasks land in the GitLab backlog with title-based idempotent dedup. "
        "Drive files and email message-ids are checkpointed in memory so a re-run "
        "never re-ingests. The development team always opens the day to "
        "actionable, scope-bounded items.",
        accent=TEAL, tint=TEAL_TINT,
    ))
    out.append(workflow_card(
        "Workflow 1.2 &mdash; Daily Report",
        "Fires at 09:00 BDT every day. Reads the last 24 hours of activity from "
        "memory (recall_activity, recall_test_runs) and pulls the latest test "
        "artifacts from the four sibling MVP Access test projects.",
        "Claude composes an executive-style summary, a per-suite section for "
        "every test family that ran in the window, and a CICD section that "
        "highlights regressions against the seven-day trend. ReportLab renders "
        "the unified PDF with consistent typography and a NAPCO-branded header.",
        "A single email goes to the team via SMTP at ~09:05 BDT, carrying one PDF "
        "attachment that covers Requirement Management, API Functional, API "
        "Integration, API Load, E2E, and CICD in one place. The same digest can "
        "be optionally posted to a Teams channel.",
        accent=TEAL, tint=TEAL_TINT,
    ))
    out.append(PageBreak())
    return out


def dim2_section():
    out = []
    out.extend(section_header(
        "Dimension 2 &mdash; Test Automation",
        "Continuous quality on the MVP Access platform.",
        bg=CORAL,
    ))
    out.append(workflow_card(
        "Workflow 2.1 &mdash; API Functional Test",
        "Triggered on demand via workflow_dispatch (typically before a release "
        "cut). Drives the Newman/Postman suite that lives in MVP-Access-API-Test.",
        "Runs the full functional contract suite, captures responses and "
        "assertions, and asks Claude to classify any failures (true regression, "
        "data-drift, environment).",
        "Writes a structured run record to test_run_history and stages a section "
        "for the next morning's Daily Report. No standalone email &mdash; the "
        "consolidated 09:00 BDT digest carries the result.",
        accent=CORAL, tint=CORAL_TINT,
    ))
    out.append(workflow_card(
        "Workflow 2.2 &mdash; API Integration Test",
        "Fires at 02:00 BDT every day. Runs the pytest integration suite "
        "(MVP-Access-API-Test) end-to-end against the staging stack.",
        "Compares the run against a seven-day trend stored in memory; Claude "
        "flags newly failing endpoints versus flaky-but-known ones, and notes "
        "throughput shifts in the report.",
        "Stages an Integration section for the Daily Report and persists a "
        "trend-able row in test_run_history. Repeated failures across days "
        "promote the case to the regression callout in the digest.",
        accent=CORAL, tint=CORAL_TINT,
    ))
    out.append(workflow_card(
        "Workflow 2.3 &mdash; API Load Test",
        "Fires at 03:00 BDT every Monday. Drives the multi-tier Locust suite "
        "(MVP-Access-API-Test) that ramps load to find the capacity ceiling.",
        "Captures per-tier latency, RPS, and failure rate; Claude annotates the "
        "result against the previous Monday's ceiling and notes any regression in "
        "the saturation point.",
        "Weekly capacity row written to test_run_history. Monday's Daily Report "
        "carries the load section so leadership sees the platform's headroom in "
        "one place each week.",
        accent=CORAL, tint=CORAL_TINT,
    ))
    out.append(workflow_card(
        "Workflow 2.4 &mdash; MVP Access E2E Test",
        "Fires at 04:00 BDT every day. Drives Playwright suites across "
        "MVP-Access-E2E-Test (full), Easy-E2E-Test (smoke), and Release-Test "
        "(release candidates).",
        "Captures screenshots on failure and routes them as PDF inline images. "
        "Claude reads the trace and proposes the most likely root cause (selector "
        "drift, data setup, server 5xx) for each failed scenario.",
        "Stages an E2E section for the Daily Report with failure thumbnails "
        "embedded. The morning digest is one click away from the offending step.",
        accent=CORAL, tint=CORAL_TINT,
    ))
    out.append(PageBreak())
    return out


def dim3_section():
    out = []
    out.extend(section_header(
        "Dimension 3 &mdash; DevOps / Release Automation",
        "Fresh builds, deployed before the test cycle starts.",
        bg=SLATE,
    ))
    out.append(workflow_card(
        "Workflow 3.1 &mdash; MVP Access Build &amp; Deploy (CICD)",
        "Fires at 22:00 BDT every day on the self-hosted Windows runner. Pulls "
        "the latest MVP Access application code from on-prem TFS using the "
        "configured TFS_URL and a service account credential.",
        "Builds the .NET solution with MSBuild on the same runner, then deploys "
        "the build output to the IIS server over a UNC share at IIS_DEPLOY_PATH. "
        "A concurrency group prevents overlapping build-deploy runs.",
        "Emails a deploy-complete notification to the team. The 22:00 BDT slot is "
        "intentionally upstream of the 02:00 / 04:00 BDT test cycle, so the "
        "API Integration, Load, and E2E suites always exercise the freshest "
        "build of the day.",
        accent=SLATE, tint=SLATE_TINT,
    ))
    out.append(PageBreak())
    return out


def tech_stack_section():
    rows = [
        ["Category", "Components"],
        ["Reasoning",
         "Claude Opus 4.7 via the local Claude CLI. Claude Agent SDK "
         "(claude-agent-sdk) for the agent loop. MCP tool servers for the 36 "
         "in-house tools."],
        ["Orchestration",
         "GitHub Actions on a self-hosted Windows runner. Seven workflow files: "
         "six task workflows plus a probe-runner. Cron schedules for daily and "
         "weekly cadence; workflow_dispatch for manual triggers."],
        ["Runtime",
         "Python 3.10+ via the py launcher. Windows Server VM at AEL\\samin. "
         "Local Claude CLI authenticated against the engineer's Claude Max "
         "subscription."],
        ["Persistent memory",
         "SQLite + FTS5 (nucleus_memory.db). Tables: activity_logs, "
         "requirements_seen, test_run_history, email_checkpoints, "
         "drive_processed. The DB is committed to the repo so memory survives "
         "runner replacement."],
        ["Inputs &mdash; Drive",
         "google-api-python-client + google-auth (service account). Audio routed "
         "to Groq Whisper (whisper-large-v3-turbo, 25 MB cap). PDFs parsed with "
         "pypdf."],
        ["Inputs &mdash; mail",
         "Gmail IMAP polling on a sender allowlist. Power Automate forwards "
         "Microsoft Teams channel messages into the same allowlist so one "
         "ingester covers both."],
        ["Test runners",
         "Newman (Postman) for functional API. pytest for integration. Locust "
         "for load. Playwright for E2E across the three sibling test projects."],
        ["Build &amp; deploy",
         "MSBuild against the .NET solution on the self-hosted Windows runner. "
         "On-prem TFS for source pull. IIS deployment over a UNC share to the "
         "production-style staging server."],
        ["Reporting",
         "ReportLab for PDF generation. SMTP over TLS (Gmail / Workspace) for "
         "delivery. Optional Microsoft Teams webhook for the morning digest."],
        ["Backlog sink",
         "GitLab v4 REST API (thin requests wrapper). Three-hour atomic tasks "
         "pushed into the project backlog with title-based idempotent dedup."],
        ["Developer tooling",
         "GitHub CLI (gh), Git, PowerShell + Bash inside workflow steps, RDP "
         "for VM access, .env contract documented in .env.example."],
    ]
    out = []
    out.extend(section_header(
        "Technology Stack",
        "Every component currently in production.",
        bg=PURPLE,
    ))
    out.append(styled_table(rows, [38 * mm, CONTENT_W - 38 * mm],
                            header_bg=PURPLE))
    out.append(PageBreak())
    return out


def prereq_section():
    out = []
    out.extend(section_header(
        "Prerequisites &amp; Open Items",
        "What we need from IT and leadership to keep this running.",
        bg=AMBER,
    ))

    out.append(open_items_card(
        "DevOps / Release Automation (CICD)",
        [
            "Dedicated deployment server (IIS host) with a stable UNC path for "
            "the build output.",
            "TFS service-account credentials (TFS_USERNAME, TFS_PASSWORD) with "
            "read access on $/MVPAccess.",
            "Network openings: VM &rarr; on-prem TFS, and VM &rarr; IIS server "
            "over SMB.",
            "TFS client (tf.exe / Team Explorer Everywhere) installed on the "
            "self-hosted runner.",
            "Matching .NET Framework Developer Pack and MSBuild version on the "
            "runner.",
            "Antivirus exclusions on the build workspace and the deploy share "
            "(Defender / ESET routinely quarantines fresh DLLs).",
            "IIS app-pool ownership &mdash; confirmation of who recycles the "
            "pool after each deploy.",
            "Documented rollback procedure for a bad deploy (no automatic "
            "rollback today).",
            "Build artifact retention so older versions can be redeployed "
            "without rebuilding from TFS history.",
        ],
        accent=SLATE, tint=SLATE_TINT,
    ))

    out.append(open_items_card(
        "Test Automation",
        [
            "Stable staging environment URL and test-data accounts that are "
            "not silently rotated.",
            "Defined cadence or trigger for refreshing the staging database "
            "so tests do not drift into false greens.",
            "Sandbox or load-test target separate from staging so weekly "
            "Locust runs do not disturb manual QA.",
        ],
        accent=CORAL, tint=CORAL_TINT,
    ))

    out.append(open_items_card(
        "Project Management",
        [
            "Power Automate license and flow that forwards Teams channel "
            "posts into the IMAP allowlist.",
            "Google Workspace service account with Drive scope on a "
            "team-owned requirement folder (not a personal account).",
            "GitLab project token with <i>api</i> scope, owned by a team "
            "account so it survives an individual leaving.",
            "Allowlisted stakeholder / client email senders kept current as "
            "projects onboard.",
        ],
        accent=TEAL, tint=TEAL_TINT,
    ))

    out.append(open_items_card(
        "Infrastructure (cross-cutting)",
        [
            "VM uptime SLA &mdash; the AEL\\samin VM must stay on 24/7 with "
            "autologon (no formal SLA today).",
            "Runner-service health monitoring beyond the hourly probe-runner "
            "(alert when the GitHub Actions service stops on the VM).",
            "Documented disaster-recovery procedure if the VM is destroyed "
            "(today: runner re-registration and secret reapply are manual).",
            "Credential rotation policy for TFS, GitLab, Google service "
            "account, SMTP, and Groq.",
        ],
        accent=NAVY, tint=colors.HexColor("#EAF0FA"),
    ))

    out.append(open_items_card(
        "Process / Governance",
        [
            "On-call ownership for &ldquo;the morning email did not "
            "arrive&rdquo; or &ldquo;the deploy notification did not come "
            "through.&rdquo;",
            "Incident escalation path if the agent silently produces bad "
            "output for two days running.",
            "Access-review cadence to confirm service accounts only retain "
            "the access they actually need.",
        ],
        accent=PURPLE, tint=PURPLE_TINT,
    ))

    out.append(PageBreak())
    return out


def status_section():
    p = live_pill
    rows = [
        ["Workflow", "Schedule", "Status", "Notes"],
        ["1.1 Requirement Management",
         "Every 2h, 09&ndash;17 BDT, Sun&ndash;Thu",
         p(),
         "IMAP + Drive ingest, Whisper transcription, FTS5 dedup, GitLab issue "
         "push with title-keyed idempotency."],
        ["1.2 Daily Report",
         "09:00 BDT daily",
         p(),
         "Single consolidated PDF email covering all six dimensions; optional "
         "Teams digest via webhook."],
        ["2.1 API Functional Test",
         "workflow_dispatch",
         p(),
         "Newman/Postman suite, Claude failure-classification, run recorded to "
         "test_run_history."],
        ["2.2 API Integration Test",
         "02:00 BDT daily",
         p(),
         "pytest integration suite vs 7-day trend; regressions promoted to "
         "morning digest."],
        ["2.3 API Load Test",
         "03:00 BDT Mondays",
         p(),
         "Multi-tier Locust suite; capacity ceiling tracked week over week."],
        ["2.4 MVP Access E2E Test",
         "04:00 BDT daily",
         p(),
         "Playwright Full + Easy + Release variants; failure screenshots "
         "embedded in the daily PDF."],
        ["3.1 MVP Access Build &amp; Deploy",
         "22:00 BDT daily",
         p(),
         "TFS pull &rarr; MSBuild &rarr; IIS deploy over UNC. Upstream of the "
         "test cycle so 02:00 / 04:00 BDT suites exercise the freshest build."],
        ["&mdash; Probe Runner",
         "Hourly",
         p(),
         "Health check on the self-hosted runner; alerts if the VM falls off "
         "the actions queue."],
    ]

    cell_body = ParagraphStyle(
        "StatusBody", parent=BODY, fontSize=9, leading=12, alignment=TA_LEFT,
        spaceAfter=0,
    )
    cell_label = ParagraphStyle(
        "StatusLabel", parent=BODY, fontName="Helvetica-Bold", fontSize=9.5,
        leading=12, textColor=NAVY, alignment=TA_LEFT, spaceAfter=0,
    )
    hdr = ParagraphStyle(
        "StatusHdr", parent=BODY, fontName="Helvetica-Bold", fontSize=10,
        leading=13, textColor=colors.white, alignment=TA_LEFT, spaceAfter=0,
    )

    def wrap(cell, r, j):
        if isinstance(cell, (Paragraph, Table)):
            return cell
        if r == 0:
            return Paragraph(cell, hdr)
        if j == 0:
            return Paragraph(cell, cell_label)
        return Paragraph(cell, cell_body)

    wrapped = [
        [wrap(c, r, j) for j, c in enumerate(row)]
        for r, row in enumerate(rows)
    ]

    tbl = Table(
        wrapped,
        colWidths=[42 * mm, 32 * mm, 18 * mm, CONTENT_W - 42 * mm - 32 * mm - 18 * mm],
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, 0), 2, OCHRE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#FAFAFC")]),
        ("ALIGN", (2, 1), (2, -1), "CENTER"),
    ]))

    out = []
    out.extend(section_header(
        "Operational Status",
        "All seven task workflows are live in production today.",
        bg=GREEN_LIVE,
    ))
    out.append(tbl)
    out.append(Spacer(1, 12))
    out.append(Paragraph(
        "<i>One repo, one VM, one morning email. The platform is built to grow: "
        "additional dimensions can be added by writing a prompt and registering "
        "tools, without disturbing the workflows already running. Next on the "
        "roadmap: a release-readiness dimension that joins the API and E2E "
        "signals into a single go / no-go recommendation per release "
        "candidate.</i>",
        CALLOUT,
    ))
    return out


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
        title="NAPCO Nucleus AI Agent — Operational Blueprint",
        author="Mohammad Kamrul Hasan",
        subject="NAPCO Nucleus AI Agent operational blueprint",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  doc.width, doc.height, id="main")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame], onPage=on_cover),
        PageTemplate(id="content", frames=[frame], onPage=on_page),
    ])

    story = [NextPageTemplate("content")]
    story.extend(cover_story())
    story.extend(overview())
    story.extend(architecture_section())
    story.extend(architecture_table())
    story.extend(dim1_section())
    story.extend(dim2_section())
    story.extend(dim3_section())
    story.extend(tech_stack_section())
    story.extend(prereq_section())
    story.extend(status_section())

    doc.build(story)


def main():
    here = Path(__file__).resolve().parent
    repo = here.parent
    out_dir = repo / "docs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "NAPCO-Nucleus-Strategic-Plan.pdf"
    build(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
