"""Build the Developer Setup Guide PDF (new-dev onboarding).

Faithful rendering of docs/Developer_Setup.md: eight sequential steps to wire
a new developer's Windows machine into the Nucleus pipeline (clone + deps +
Tesseract + .env + cached Samba creds + voice daemon + chat-push + test),
plus a short troubleshooting section, update + uninstall recipes, and a
single contact line.

Produces:
    docs/NAPCO-Nucleus-Developer-Setup.pdf

Run:  python docs/_build_developer_setup_pdf.py
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph,
    Spacer, Table, TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

# ── Palette (matches _build_setup_guide_pdf.py) ───────────────────
NAVY = colors.HexColor("#1F3A5F")
ACCENT = colors.HexColor("#3B6FB6")
SOFT_NAVY = colors.HexColor("#2E4D7A")
GREY_BORDER = colors.HexColor("#D8DEE6")
GREY_TEXT = colors.HexColor("#445064")
BODY_TEXT = colors.HexColor("#1F232B")
CODE_BG = colors.HexColor("#F4F6F9")
CODE_BORDER = colors.HexColor("#E1E6EE")
CALLOUT_BG = colors.HexColor("#FFF8E5")
CALLOUT_BAR = colors.HexColor("#E5A93B")
SUBTLE = colors.HexColor("#7A8499")
VERIFY_GREEN = colors.HexColor("#2F7A4D")

HERE = Path(__file__).parent
OUT = HERE / "NAPCO-Nucleus-Developer-Setup.pdf"

PAGE_W, PAGE_H = LETTER
MARGIN = 0.8 * inch
TITLE_BAR_H = 1.55 * inch
CONTENT_W = PAGE_W - 2 * MARGIN


# ── Page chrome ───────────────────────────────────────────────────

def first_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - TITLE_BAR_H, PAGE_W, TITLE_BAR_H, fill=1, stroke=0)
    canvas.setFillColor(ACCENT)
    canvas.rect(0, PAGE_H - TITLE_BAR_H, PAGE_W, 0.04 * inch, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 26)
    canvas.drawString(MARGIN, PAGE_H - TITLE_BAR_H + 0.7 * inch,
                      "NAPCO Nucleus")
    canvas.setFont("Helvetica", 13)
    canvas.setFillColor(colors.HexColor("#C8D4E6"))
    canvas.drawString(MARGIN, PAGE_H - TITLE_BAR_H + 0.42 * inch,
                      "Developer Setup Guide")
    canvas.setFont("Helvetica-Oblique", 10)
    canvas.setFillColor(colors.HexColor("#A4B4CC"))
    canvas.drawString(
        MARGIN, PAGE_H - TITLE_BAR_H + 0.18 * inch,
        "Eight steps. Run every command in PowerShell on your Windows dev PC.")
    _draw_footer(canvas, doc)
    canvas.restoreState()


def later_page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(1.2)
    canvas.line(MARGIN, PAGE_H - 0.5 * inch,
                MARGIN + 0.4 * inch, PAGE_H - 0.5 * inch)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(NAVY)
    canvas.drawString(MARGIN + 0.5 * inch, PAGE_H - 0.52 * inch,
                      "NAPCO Nucleus")
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(SUBTLE)
    canvas.drawString(MARGIN + 1.45 * inch, PAGE_H - 0.52 * inch,
                      "Developer Setup Guide")
    _draw_footer(canvas, doc)
    canvas.restoreState()


def _draw_footer(canvas, doc):
    canvas.setStrokeColor(GREY_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 0.6 * inch, PAGE_W - MARGIN, 0.6 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY_TEXT)
    canvas.drawString(MARGIN, 0.38 * inch,
                      "github.com/napco-labs/napco-nucleus")
    canvas.drawRightString(PAGE_W - MARGIN, 0.38 * inch,
                           f"Page {doc.page}")


# ── Reusable flowables ────────────────────────────────────────────

def _step_heading(label, title, accent=ACCENT):
    eyebrow_style = ParagraphStyle(
        "StepLabel", fontName="Helvetica-Bold", fontSize=8.5,
        textColor=accent, leading=10, spaceAfter=1, alignment=TA_LEFT,
    )
    title_style = ParagraphStyle(
        "StepTitle", fontName="Helvetica-Bold", fontSize=15.5,
        textColor=NAVY, leading=19, spaceBefore=0, spaceAfter=2,
    )
    return KeepTogether([
        Paragraph(label.upper(), eyebrow_style),
        Paragraph(title, title_style),
        HRFlowable(width=0.5 * inch, thickness=1.4, color=accent,
                   spaceBefore=0, spaceAfter=8, lineCap="round"),
    ])


def _section_heading(eyebrow, title):
    eyebrow_style = ParagraphStyle(
        "SecLabel", fontName="Helvetica-Bold", fontSize=8.5,
        textColor=ACCENT, leading=10, spaceAfter=1,
    )
    title_style = ParagraphStyle(
        "SecTitle", fontName="Helvetica-Bold", fontSize=15.5,
        textColor=NAVY, leading=19, spaceAfter=2,
    )
    return KeepTogether([
        Paragraph(eyebrow.upper(), eyebrow_style),
        Paragraph(title, title_style),
        HRFlowable(width=0.5 * inch, thickness=1.4, color=ACCENT,
                   spaceBefore=0, spaceAfter=8, lineCap="round"),
    ])


def _callout(html, body_style):
    bar_w = 0.08 * inch
    inner_w = CONTENT_W - bar_w
    t = Table(
        [["", Paragraph(html, body_style)]],
        colWidths=[bar_w, inner_w],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), CALLOUT_BAR),
        ("BACKGROUND", (1, 0), (1, -1), CALLOUT_BG),
        ("LEFTPADDING", (1, 0), (1, -1), 12),
        ("RIGHTPADDING", (1, 0), (1, -1), 12),
        ("TOPPADDING", (1, 0), (1, -1), 10),
        ("BOTTOMPADDING", (1, 0), (1, -1), 10),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 0),
        ("TOPPADDING", (0, 0), (0, -1), 0),
        ("BOTTOMPADDING", (0, 0), (0, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


# Escape characters that have meaning inside a reportlab Paragraph.
# The body is fine with normal text, but code blocks contain '<', '>', '&'
# which would be parsed as HTML. Newlines become <br/>.
def _esc(text: str) -> str:
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))


def _code(text, code_style):
    """Code block: monospace, soft bg, light border, accent left border.

    `text` is the raw verbatim shell snippet. We escape HTML metachars and
    convert newlines to <br/> so reportlab's Paragraph renders them.
    """
    html = _esc(text).replace("\n", "<br/>")
    t = Table([[Paragraph(html, code_style)]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, CODE_BORDER),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


def _where(html, where_style):
    """Italic 'Run in ...' hint that sits just above a code block."""
    return Paragraph(html, where_style)


def _verify(prefix, html, verify_style):
    """A 'Verify:' / 'Expected:' style hint, in green italic."""
    return Paragraph(f"<b>{prefix}</b> {html}", verify_style)


def _space(h=0.12):
    return Spacer(1, h * inch)


# ── Body ──────────────────────────────────────────────────────────

def build():
    body = ParagraphStyle(
        "Body", fontName="Helvetica", fontSize=10.5,
        leading=15, textColor=BODY_TEXT, spaceAfter=8, alignment=TA_LEFT,
    )
    intro = ParagraphStyle(
        "Intro", parent=body, fontSize=11, leading=16, textColor=SOFT_NAVY,
        spaceAfter=10,
    )
    code = ParagraphStyle(
        "Code", fontName="Courier", fontSize=9.0, leading=12.5,
        textColor=BODY_TEXT,
    )
    where_style = ParagraphStyle(
        "Where", fontName="Helvetica-Oblique", fontSize=10,
        leading=13.5, textColor=SOFT_NAVY, spaceAfter=4,
    )
    verify_style = ParagraphStyle(
        "Verify", fontName="Helvetica-Oblique", fontSize=10,
        leading=14, textColor=VERIFY_GREEN, spaceAfter=6, spaceBefore=2,
    )
    sub = ParagraphStyle(
        "Sub", fontName="Helvetica-Bold", fontSize=11.5,
        textColor=SOFT_NAVY, leading=14.5, spaceBefore=8, spaceAfter=4,
    )

    flow = []
    flow.append(_space(0.25))

    # ── Intro ─────────────────────────────────────────────────────
    flow.append(_section_heading("Start here", "Before you begin"))
    flow.append(Paragraph(
        "Run every command below in <b>PowerShell</b> on your Windows dev PC.",
        intro))
    flow.append(Paragraph("<b>What Titu sends you first</b>", body))
    flow.append(Paragraph(
        "Titu will DM you these two files privately "
        "(they contain secrets &mdash; never share them publicly):",
        body))
    flow.append(Paragraph(
        "1. <font face=\"Courier\">.env</font> &mdash; save inside your "
        "repo folder after Step 1 (<font face=\"Courier\">$NN\\.env</font>)<br/>"
        "2. <font face=\"Courier\">google-credentials.json</font> &mdash; "
        "save inside your repo folder "
        "(<font face=\"Courier\">$NN\\google-credentials.json</font>)",
        body))
    flow.append(Paragraph(
        "<i>The Samba password is provided inline in Step 5 below.</i>",
        body))

    # ── Step 1: Clone ─────────────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 1", "Clone the repo"))
    flow.append(Paragraph(
        "Pick where you want the repo installed. Set "
        "<font face=\"Courier\">$NN</font> to that path &mdash; every "
        "later step references <font face=\"Courier\">$NN</font>, so the "
        "install location is yours to decide.", body))
    flow.append(_where("Run in <b><i>PowerShell</i></b>:", where_style))
    flow.append(_code(
        "$NN = \"E:\\Projects\\NAPCO-Nucleus\"   "
        "# change this if you want it elsewhere\n"
        "mkdir (Split-Path $NN -Parent) -Force | Out-Null\n"
        "git clone https://github.com/napco-labs/napco-nucleus.git $NN\n"
        "Set-Location $NN",
        code))
    flow.append(Paragraph(
        "<i><font face=\"Courier\">$NN</font> only lives in the current "
        "PowerShell session. If you close PowerShell, set it again at "
        "the top of any new session before running the rest of the "
        "commands. To make it permanent across sessions:</i>", body))
    flow.append(_code(
        "[Environment]::SetEnvironmentVariable(\"NN\", $NN, \"User\")",
        code))
    flow.append(Paragraph(
        "<i>After that, use <font face=\"Courier\">$env:NN</font> from "
        "any future shell.</i>", body))

    # ── Step 2: Install Python packages ───────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 2", "Install Python packages"))
    flow.append(_where("Run in <b><i>PowerShell</i></b>:", where_style))
    flow.append(_code(
        "Set-Location $NN\n"
        "python -m pip install -r requirements.txt",
        code))

    # ── Step 3: Tesseract ─────────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 3", "Install Tesseract OCR"))
    flow.append(_where(
        "Run anywhere in <b><i>PowerShell</i></b>:", where_style))
    flow.append(_code("winget install UB-Mannheim.TesseractOCR", code))
    flow.append(Paragraph(
        "Then close and reopen PowerShell (re-set "
        "<font face=\"Courier\">$NN</font> after reopen).", body))

    # ── Step 4: .env ──────────────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 4",
                              "Place the files Titu sent you + set your dev name"))
    flow.append(Paragraph(
        "Save the two files from the &quot;What Titu sends you first&quot; "
        "section above into your repo folder:", body))
    flow.append(_code(
        "$NN\\.env\n"
        "$NN\\google-credentials.json",
        code))
    flow.append(Paragraph(
        "(Replace <font face=\"Courier\">$NN</font> with your actual path "
        "in your file manager &mdash; e.g. "
        "<font face=\"Courier\">E:\\Projects\\NAPCO-Nucleus\\.env</font>.)",
        body))
    flow.append(Paragraph(
        "Open the <font face=\"Courier\">.env</font> file in Notepad. "
        "Find this line:", body))
    flow.append(_code("NUCLEUS_DEV_NAME=Titu", code))
    flow.append(Paragraph(
        "Replace <font face=\"Courier\">Titu</font> with <b>your</b> name. "
        "Use one of these exactly:", body))
    flow.append(_code(
        "Assad   Rocky   Ferdows   Titu   Atik   Isruk   Amin", code))
    flow.append(Paragraph("Save. Close.", body))

    # ── Step 5: Samba cred ────────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 5", "Cache the Samba password"))
    flow.append(_where(
        "Run in <b><i>PowerShell</i></b>:",
        where_style))
    flow.append(_code(
        "cmdkey /add:172.16.205.123 /user:nucleus "
        "/pass:E7CqJOd1oHox7HTjxNp_osD_fSyUe59I", code))
    flow.append(Paragraph("Verify:", body))
    flow.append(_code(
        "Test-Path \\\\172.16.205.123\\nucleus-central", code))
    flow.append(_verify(
        "Expected output:",
        "<font face=\"Courier\">True</font>",
        verify_style))

    # ── Step 6: Voice daemon ──────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 6", "Install the voice daemon"))
    flow.append(_where("Run in <b><i>PowerShell</i></b>:", where_style))
    flow.append(_code(
        "Set-Location $NN\n"
        ".\\scripts\\register-voice-daemon-task.ps1\n"
        "Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'",
        code))

    # ── Step 7: Chat push ─────────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 7", "Install chat-push tasks"))
    flow.append(_where("Run in <b><i>PowerShell</i></b>:", where_style))
    flow.append(_code(
        "Set-Location $NN\n"
        ".\\scripts\\register-chat-push-task.ps1",
        code))

    # ── Step 8: Test ──────────────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 8", "Test"))
    flow.append(Paragraph(
        "Make a Teams call (any short call, at least 20 seconds). Wait "
        "2 minutes. Then run in <b><i>PowerShell</i></b>:", body))
    flow.append(_code(
        "$you   = ((Select-String -Path \"$NN\\.env\" "
        "-Pattern '^NUCLEUS_DEV_NAME=').Line -replace "
        "'NUCLEUS_DEV_NAME=','').Trim()\n"
        "$today = Get-Date -Format \"yyyy-MM-dd\"\n"
        "Get-ChildItem \"\\\\172.16.205.123\\nucleus-central\\$you\\$today\\"
        "calls\\\"",
        code))
    flow.append(_verify(
        "Expected:",
        "your call files (<font face=\"Courier\">*_mic.wav</font>, "
        "<font face=\"Courier\">*_speaker.wav</font>, "
        "<font face=\"Courier\">*.json</font>, "
        "<font face=\"Courier\">*_transcript.md</font>).",
        verify_style))
    # ── Step 9: Enable remote ops ─────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 9",
                              "Enable remote operations (admin one-time)"))
    flow.append(Paragraph(
        "So Titu can troubleshoot and update your PC remotely without "
        "bothering you again, run this <b>once in admin PowerShell</b> "
        "(right-click PowerShell &rarr; Run as administrator):", body))
    flow.append(_code("Enable-PSRemoting -Force", code))
    flow.append(Paragraph(
        "That's it. Opens the WinRM listener + firewall rule. After this, "
        "Titu can run diagnostics + apply fixes on your PC from his "
        "without you needing to be at the keyboard.", body))
    flow.append(_callout("<b>Setup is complete.</b>", body))

    # ── If a step fails ───────────────────────────────────────────
    flow.append(_space(0.22))
    flow.append(_step_heading("Help", "If a step fails"))

    flow.append(Paragraph("<b>Tail the voice daemon log:</b>", body))
    flow.append(_code(
        "Get-Content \"$NN\\logs\\voice_daemon.log\" -Tail 50",
        code))

    flow.append(Paragraph(
        "<b><font face=\"Courier\">scripts disabled on this system</font> "
        "error in Step 6 or 7:</b>", body))
    flow.append(_code(
        "powershell.exe -ExecutionPolicy Bypass -File "
        "\"$NN\\scripts\\register-voice-daemon-task.ps1\"",
        code))
    flow.append(Paragraph(
        "(Use the same form for "
        "<font face=\"Courier\">register-chat-push-task.ps1</font>.)", body))

    flow.append(Paragraph(
        "<b><font face=\"Courier\">Test-Path</font> in Step 5 returned "
        "<font face=\"Courier\">False</font>:</b>", body))
    flow.append(_code(
        "ping 172.16.205.123\n"
        "cmdkey /list:172.16.205.123",
        code))

    flow.append(Paragraph("<b>Mic missing from recordings:</b>", body))
    flow.append(Paragraph(
        "Teams &rarr; Settings &rarr; Devices &rarr; set Microphone to your "
        "Windows default input.", body))

    # ── Update the system later ───────────────────────────────────
    flow.append(_space(0.22))
    flow.append(_step_heading("Update", "Update the system later"))
    flow.append(_where(
        "Run in <b><i>PowerShell</i></b> (re-set "
        "<font face=\"Courier\">$NN</font> first if it's a fresh session):",
        where_style))
    flow.append(_code(
        "Set-Location $NN\n"
        "git pull\n"
        "python -m pip install -r requirements.txt\n"
        "Stop-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'\n"
        "Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'",
        code))

    # ── Uninstall ─────────────────────────────────────────────────
    flow.append(_space(0.22))
    flow.append(_step_heading("Uninstall", "Uninstall"))
    flow.append(_where(
        "Run in <b><i>PowerShell</i></b> (re-set "
        "<font face=\"Courier\">$NN</font> first if it's a fresh session):",
        where_style))
    flow.append(_code(
        "Set-Location $NN\n"
        ".\\scripts\\register-voice-daemon-task.ps1 -Unregister\n"
        ".\\scripts\\register-chat-push-task.ps1 -Unregister\n"
        "cmdkey /delete:172.16.205.123",
        code))

    # ── Contact ───────────────────────────────────────────────────
    flow.append(_space(0.22))
    flow.append(_step_heading("Contact", "Contact"))
    flow.append(Paragraph(
        "Titu &mdash; <font face=\"Courier\">khasan@ael-bd.com</font>", body))

    return flow


# ── Document ──────────────────────────────────────────────────────

def main():
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=LETTER,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=TITLE_BAR_H + 0.05 * inch,
        bottomMargin=0.75 * inch,
        title="NAPCO Nucleus — Developer Setup Guide",
        author="napco-labs",
    )
    frame_first = Frame(
        MARGIN, doc.bottomMargin,
        CONTENT_W,
        PAGE_H - TITLE_BAR_H - doc.bottomMargin - 0.05 * inch,
        id="first", showBoundary=0,
    )
    frame_later = Frame(
        MARGIN, doc.bottomMargin,
        CONTENT_W,
        PAGE_H - 0.85 * inch - doc.bottomMargin,
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
