"""Build the Developer Setup Guide PDF (new-dev onboarding).

Faithful rendering of docs/Developer_Setup.md: nine sequential steps to wire
a new developer's Windows machine into the Nucleus pipeline (clone + deps +
Tesseract + .env + cached Samba creds + voice daemon + chat-push +
remote-ops enable + test), troubleshooting + update + uninstall recipes,
contact, plus an appendix containing Titu's remote-ops cheat sheet (one-time
WinRM setup on Titu's PC, credential header, dev PC IP registry table, six
remote one-liners, central host operations, daily-draft note).

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
    BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
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

# Appendix-specific accents (distinct from main-body navy/accent).
APPX_BAR = colors.HexColor("#5A3A8C")          # deep violet — appendix eyebrow
APPX_RULE = colors.HexColor("#8366B8")         # softer violet — section rule
APPX_BG = colors.HexColor("#F1ECFA")           # very pale violet — header bg
APPX_TABLE_HEAD = colors.HexColor("#3A2A5C")   # dark violet — table header bg
APPX_TABLE_ALT = colors.HexColor("#F8F5FC")    # alt row tint

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
        "Nine steps. Run every command in PowerShell on your Windows dev PC.")
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


def appendix_page(canvas, doc):
    """Later pages in the appendix get a violet accent rule instead of blue,
    plus an "Appendix" eyebrow tag so devs can tell at a glance this isn't
    something they're supposed to run."""
    canvas.saveState()
    canvas.setStrokeColor(APPX_RULE)
    canvas.setLineWidth(1.2)
    canvas.line(MARGIN, PAGE_H - 0.5 * inch,
                MARGIN + 0.4 * inch, PAGE_H - 0.5 * inch)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(APPX_BAR)
    canvas.drawString(MARGIN + 0.5 * inch, PAGE_H - 0.52 * inch,
                      "NAPCO Nucleus")
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(SUBTLE)
    canvas.drawString(MARGIN + 1.45 * inch, PAGE_H - 0.52 * inch,
                      "Appendix — Titu's remote-ops cheat sheet")
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


def _appendix_banner():
    """Full-width violet banner that visually divides the dev-facing
    setup from the appendix. Drawn as a Table for solid background."""
    eyebrow = ParagraphStyle(
        "AppxEyebrow", fontName="Helvetica-Bold", fontSize=9,
        textColor=colors.white, leading=11, spaceAfter=2,
    )
    title = ParagraphStyle(
        "AppxTitle", fontName="Helvetica-Bold", fontSize=18,
        textColor=colors.white, leading=22, spaceAfter=2,
    )
    sub = ParagraphStyle(
        "AppxSub", fontName="Helvetica-Oblique", fontSize=10,
        textColor=colors.HexColor("#E5DCF5"), leading=13,
    )
    inner = [
        Paragraph("APPENDIX", eyebrow),
        Paragraph("Titu's remote-ops cheat sheet", title),
        Paragraph(
            "<b>Not for the dev to run.</b> Reference for managing dev PCs "
            "remotely once they've completed Step 8.", sub),
    ]
    t = Table([[inner]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), APPX_BAR),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING", (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
    ]))
    return t


def _appx_heading(number, title):
    """Numbered violet sub-section header inside the appendix."""
    num_style = ParagraphStyle(
        "AppxNum", fontName="Helvetica-Bold", fontSize=9,
        textColor=APPX_BAR, leading=11, spaceAfter=1,
    )
    title_style = ParagraphStyle(
        "AppxSecTitle", fontName="Helvetica-Bold", fontSize=14,
        textColor=APPX_BAR, leading=17, spaceBefore=0, spaceAfter=2,
    )
    return KeepTogether([
        Paragraph(f"APPENDIX · {number}", num_style),
        Paragraph(title, title_style),
        HRFlowable(width=0.5 * inch, thickness=1.4, color=APPX_RULE,
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


def _code_appx(text, code_style):
    """Code block variant for the appendix — violet left rule instead of blue,
    to visually reinforce that this is reference material, not dev-facing."""
    html = _esc(text).replace("\n", "<br/>")
    t = Table([[Paragraph(html, code_style)]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, CODE_BORDER),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, APPX_RULE),
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
    appx_body = ParagraphStyle(
        "AppxBody", parent=body, textColor=BODY_TEXT,
    )
    appx_note = ParagraphStyle(
        "AppxNote", parent=body, fontName="Helvetica-Oblique",
        textColor=GREY_TEXT,
    )
    tbl_head_style = ParagraphStyle(
        "TblHead", fontName="Helvetica-Bold", fontSize=9.5,
        textColor=colors.white, leading=12, alignment=TA_LEFT,
    )
    tbl_cell_style = ParagraphStyle(
        "TblCell", fontName="Helvetica", fontSize=9.5,
        textColor=BODY_TEXT, leading=12, alignment=TA_LEFT,
    )
    tbl_cell_code = ParagraphStyle(
        "TblCellCode", fontName="Courier", fontSize=9,
        textColor=BODY_TEXT, leading=12, alignment=TA_LEFT,
    )

    flow = []
    flow.append(_space(0.25))

    # ── Intro ─────────────────────────────────────────────────────
    flow.append(_section_heading("Start here", "Before you begin"))
    flow.append(Paragraph(
        "Run every command below in <b>PowerShell</b> on your Windows dev PC. "
        "Total time: ~25 min, mostly waiting for "
        "<font face=\"Courier\">pip install</font>.",
        intro))
    flow.append(Paragraph("<b>Three things Titu DMs you first</b>", body))
    flow.append(Paragraph(
        "Never share these on group chat &mdash; they contain secrets.", body))
    flow.append(Paragraph(
        "1. <font face=\"Courier\">.env</font> &mdash; save inside your "
        "repo folder (<font face=\"Courier\">$NN\\.env</font>) after Step 1.<br/>"
        "2. <font face=\"Courier\">google-credentials.json</font> &mdash; "
        "save inside your repo folder "
        "(<font face=\"Courier\">$NN\\google-credentials.json</font>).<br/>"
        "3. <b>This PDF.</b>",
        body))
    flow.append(Paragraph(
        "<i>The Samba password is inline in Step 5.</i>",
        body))

    # ── Step 1: Clone ─────────────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 1", "Clone the repo"))
    flow.append(Paragraph(
        "Pick install location. Set <font face=\"Courier\">$NN</font> to "
        "that path &mdash; every later step uses it.", body))
    flow.append(_where("Run in <b><i>PowerShell</i></b>:", where_style))
    flow.append(_code(
        "$NN = \"E:\\Projects\\NAPCO-Nucleus\"     "
        "# change if you want it elsewhere\n"
        "mkdir (Split-Path $NN -Parent) -Force | Out-Null\n"
        "git clone https://github.com/napco-labs/napco-nucleus.git $NN\n"
        "Set-Location $NN",
        code))
    flow.append(Paragraph(
        "<i><font face=\"Courier\">$NN</font> lives only in this PowerShell "
        "session. If you open a new shell later, set it again at the top. "
        "To persist across sessions:</i>", body))
    flow.append(_code(
        "[Environment]::SetEnvironmentVariable(\"NN\", $NN, \"User\")",
        code))
    flow.append(Paragraph(
        "<i>Then use <font face=\"Courier\">$env:NN</font> from any future "
        "shell.</i>", body))

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
        "Close and reopen PowerShell (re-set "
        "<font face=\"Courier\">$NN</font> after reopen).", body))

    # ── Step 4: .env ──────────────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 4",
                              "Place files + set your dev name"))
    flow.append(Paragraph(
        "Save the two files Titu sent you into your repo folder:", body))
    flow.append(_code(
        "$NN\\.env\n"
        "$NN\\google-credentials.json",
        code))
    flow.append(Paragraph(
        "Open <font face=\"Courier\">.env</font> in Notepad. Find this line:",
        body))
    flow.append(_code("NUCLEUS_DEV_NAME=Titu", code))
    flow.append(Paragraph(
        "Replace <font face=\"Courier\">Titu</font> with <b>your</b> name. "
        "Use one exactly:", body))
    flow.append(_code(
        "Assad   Rocky   Ferdows   Titu   Atik   Isruk   Amin", code))
    flow.append(Paragraph("Save. Close.", body))

    # ── Step 5: Samba cred ────────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 5",
                              "Cache Samba password (critical)"))
    flow.append(Paragraph(
        "<b>Use REGULAR PowerShell, NOT admin.</b> The credential is stored "
        "per-user and must be in your normal session.", body))
    flow.append(_where("Run in <b><i>PowerShell</i></b>:", where_style))
    flow.append(_code(
        "cmdkey /add:172.16.205.123 /user:nucleus "
        "/pass:E7CqJOd1oHox7HTjxNp_osD_fSyUe59I\n"
        "Test-Path \\\\172.16.205.123\\nucleus-central",
        code))
    flow.append(_verify(
        "Expected:",
        "<font face=\"Courier\">Test-Path</font> <b>must print "
        "<font face=\"Courier\">True</font></b>. If it prints "
        "<font face=\"Courier\">False</font>, your calls won't upload to "
        "central &mdash; stop and ping Titu.",
        verify_style))

    # ── Step 6: Voice daemon ──────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 6", "Install voice daemon"))
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

    # ── Step 8: Enable remote ops ─────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 8",
                              "Enable remote ops (admin one-time)"))
    flow.append(Paragraph(
        "So Titu can manage your PC from his desk without you needing to "
        "be at the keyboard. Open <b>admin PowerShell</b> (right-click "
        "PowerShell &rarr; Run as administrator):", body))
    flow.append(_code(
        "Enable-PSRemoting -Force\n"
        "Add-LocalGroupMember -Group \"Remote Management Users\" "
        "-Member \"AEL\\khasan\"",
        code))
    flow.append(Paragraph(
        "If <font face=\"Courier\">Enable-PSRemoting</font> errors about "
        "network profile being &quot;Public&quot;, use this instead:", body))
    flow.append(_code(
        "Enable-PSRemoting -Force -SkipNetworkProfileCheck\n"
        "Add-LocalGroupMember -Group \"Remote Management Users\" "
        "-Member \"AEL\\khasan\"",
        code))
    flow.append(Paragraph(
        "If <font face=\"Courier\">Add-LocalGroupMember</font> says "
        "&quot;User already member&quot;, that's fine &mdash; already granted.",
        body))

    # ── Step 9: Test ──────────────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Step 9", "Test"))
    flow.append(Paragraph(
        "Make any Teams call (at least 20 seconds). Wait 2 minutes. Then:",
        body))
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
        "you should see <font face=\"Courier\">*_mic.wav</font>, "
        "<font face=\"Courier\">*_speaker.wav</font>, "
        "<font face=\"Courier\">*.json</font>, "
        "<font face=\"Courier\">*_transcript.md</font>.",
        verify_style))
    flow.append(_callout(
        "<b>Setup complete.</b> Tell Titu you're done.", body))

    # ── If something fails ────────────────────────────────────────
    flow.append(_space(0.22))
    flow.append(_step_heading("Help", "If something fails"))

    flow.append(Paragraph("<b>Daemon log:</b>", body))
    flow.append(_code(
        "Get-Content \"$NN\\logs\\voice_daemon.log\" -Tail 50",
        code))

    flow.append(Paragraph(
        "<b><font face=\"Courier\">scripts disabled on this system</font> "
        "in Step 6 or 7:</b>", body))
    flow.append(_code(
        "powershell.exe -ExecutionPolicy Bypass -File "
        "\"$NN\\scripts\\register-voice-daemon-task.ps1\"",
        code))

    flow.append(Paragraph(
        "<b><font face=\"Courier\">Test-Path</font> returned "
        "<font face=\"Courier\">False</font> in Step 5:</b>", body))
    flow.append(_code(
        "ping 172.16.205.123\n"
        "cmdkey /list:172.16.205.123",
        code))
    flow.append(Paragraph(
        "If cmdkey doesn't show a <font face=\"Courier\">nucleus</font> "
        "user, re-run Step 5 in a <b>non-admin</b> PowerShell.", body))

    flow.append(Paragraph("<b>Mic missing from recordings:</b>", body))
    flow.append(Paragraph(
        "Teams &rarr; Settings &rarr; Devices &rarr; set Microphone to your "
        "Windows default input.", body))

    # ── Update the system later ───────────────────────────────────
    flow.append(_space(0.22))
    flow.append(_step_heading("Update", "Update later"))
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
    flow.append(Paragraph(
        "<i>(Or just ask Titu to push the update remotely.)</i>", body))

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

    # ══════════════════════════════════════════════════════════════
    # APPENDIX — Titu's remote-ops cheat sheet
    # ══════════════════════════════════════════════════════════════
    flow.append(PageBreak())
    # Switch later-page chrome to the appendix variant for everything below.
    flow.append(_NextPageTemplate("Appendix"))
    flow.append(_space(0.1))
    flow.append(_appendix_banner())
    flow.append(_space(0.2))

    # A.1 — One-time setup on Titu's PC
    flow.append(_appx_heading("A.1", "One-time setup on Titu's PC"))
    flow.append(Paragraph(
        "Already done on <font face=\"Courier\">.71</font>. For reference "
        "if Titu ever reinstalls &mdash; <b>admin PowerShell</b>:", appx_body))
    flow.append(_code_appx(
        "Start-Service WinRM\n"
        "Set-Service WinRM -StartupType Automatic\n"
        "Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "
        "'172.16.205.*' -Force",
        code))

    # A.2 — Credential header
    flow.append(_space(0.15))
    flow.append(_appx_heading("A.2", "Credential header"))
    flow.append(Paragraph(
        "Paste at the top of any new PowerShell session before running the "
        "commands below:", appx_body))
    flow.append(_code_appx(
        "$pwd_at = ConvertTo-SecureString '606549' -AsPlainText -Force\n"
        "$cred_at = New-Object PSCredential('AEL\\khasan', $pwd_at)",
        code))

    # A.3 — Dev PC IP registry table
    flow.append(_space(0.15))
    flow.append(_appx_heading("A.3",
                              "Dev PC IP registry (fill in as you onboard)"))
    flow.append(_ip_registry_table(
        tbl_head_style, tbl_cell_style, tbl_cell_code))

    # A.4 — Remote operations
    flow.append(_space(0.18))
    flow.append(_appx_heading("A.4", "Remote operations"))
    flow.append(Paragraph(
        "Replace <font face=\"Courier\">&lt;IP&gt;</font> with the target "
        "PC's IP from the table above. Replace "
        "<font face=\"Courier\">&lt;repo&gt;</font> with the dev's repo path.",
        appx_body))

    flow.append(Paragraph(
        "<b>Probe a dev PC (sanity check):</b>", appx_body))
    flow.append(_code_appx(
        "Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {\n"
        "    hostname; whoami; \"OS: "
        "$((Get-CimInstance Win32_OperatingSystem).Caption)\"\n"
        "}",
        code))

    flow.append(Paragraph(
        "<b>Tail their voice daemon log:</b>", appx_body))
    flow.append(_code_appx(
        "Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {\n"
        "    Get-Content \"<repo>\\logs\\voice_daemon.log\" -Tail 30\n"
        "}",
        code))

    flow.append(Paragraph(
        "<b>Check Scheduled Task state</b> "
        "(<font face=\"Courier\">schtasks</font> &mdash; "
        "<font face=\"Courier\">Get-ScheduledTask</font> needs admin "
        "remotely)<b>:</b>", appx_body))
    flow.append(_code_appx(
        "Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {\n"
        "    schtasks /query /tn \"NAPCO Nucleus - Voice Daemon\" /fo LIST\n"
        "    schtasks /query /tn \"NAPCO Nucleus - Chat Push (Day)\" /fo LIST\n"
        "}",
        code))

    flow.append(Paragraph(
        "<b>Apply <font face=\"Courier\">git pull</font> + restart their "
        "daemon:</b>", appx_body))
    flow.append(_code_appx(
        "Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {\n"
        "    Set-Location \"<repo>\"\n"
        "    git pull\n"
        "    Stop-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'\n"
        "    Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'\n"
        "}",
        code))

    flow.append(Paragraph(
        "<b>Recover stuck WAVs to central</b> (when the dev's "
        "<font face=\"Courier\">cmdkey</font> wasn't set up correctly "
        "&mdash; <font face=\"Courier\">cmdkey</font> can't be done via "
        "WinRM, but <font face=\"Courier\">New-PSDrive</font> with explicit "
        "cred works)<b>:</b>", appx_body))
    flow.append(_code_appx(
        "Invoke-Command -ComputerName <IP> -Credential $cred_at -ScriptBlock {\n"
        "    $smb_pwd = ConvertTo-SecureString "
        "'E7CqJOd1oHox7HTjxNp_osD_fSyUe59I' -AsPlainText -Force\n"
        "    $smb_cred = New-Object PSCredential('nucleus', $smb_pwd)\n"
        "    New-PSDrive -Name NN -PSProvider FileSystem -Root "
        "'\\\\172.16.205.123\\nucleus-central' -Credential $smb_cred | Out-Null\n"
        "    $today = Get-Date -Format \"yyyy-MM-dd\"\n"
        "    $dest = \"NN:\\<DEV_NAME>\\$today\\calls\"     "
        "# replace <DEV_NAME>\n"
        "    New-Item -ItemType Directory -Force -Path $dest "
        "-ErrorAction SilentlyContinue | Out-Null\n"
        "    Get-ChildItem '<repo>\\data\\teams\\calls\\*' "
        "-ErrorAction SilentlyContinue | Copy-Item -Destination $dest -Force\n"
        "    Get-ChildItem $dest | Select-Object Name, Length\n"
        "    Remove-PSDrive NN\n"
        "}",
        code))

    flow.append(Paragraph(
        "<b>Open an interactive remote shell</b> (good for debugging)<b>:</b>",
        appx_body))
    flow.append(_code_appx(
        "Enter-PSSession -ComputerName <IP> -Credential $cred_at\n"
        "# prompt becomes [<IP>]: PS> -- type commands; runs on their PC\n"
        "# 'exit' when done",
        code))

    # A.5 — Central host (.123) operations
    flow.append(_space(0.18))
    flow.append(_appx_heading("A.5", "Central host (.123) operations"))
    flow.append(_code_appx(
        "ssh ubuntu@172.16.205.123                    # password: ayusuf\n"
        "\n"
        "# Stack health\n"
        "cd /home/ubuntu/napco-nucleus/deploy/linux-central\n"
        "./status.sh\n"
        "\n"
        "# Trigger daily-draft on demand (instead of waiting for BD 23:45)\n"
        "docker compose exec daily-draft python collect_central.py "
        "--client all --last-minutes 1440\n"
        "\n"
        "# Safe redeploy (after pushing a fix to main)\n"
        "./deploy.sh           # core stack only\n"
        "./deploy.sh --runner  # also recreates the GHA runner container\n"
        "\n"
        "# Tail one worker\n"
        "docker compose logs -f --tail 100 transcribe",
        code))

    # A.6 — Daily-draft email destination
    flow.append(_space(0.18))
    flow.append(_appx_heading("A.6", "Daily-draft email destination"))
    flow.append(Paragraph(
        "Drafts land in <b><font face=\"Courier\">khasan@ael-bd.com</font></b> "
        "Gmail Drafts folder (configured via "
        "<font face=\"Courier\">VERIFICATION_TO</font> in "
        "<font face=\"Courier\">.env</font> on "
        "<font face=\"Courier\">.123</font>). Subject pattern: "
        "<font face=\"Courier\">Requirements Verification - YYYY-MM-DD</font>.",
        appx_body))

    return flow


def _ip_registry_table(head_style, cell_style, cell_code):
    """Render the dev PC IP registry as a real reportlab Table."""
    headers = ["Dev", "IP", "NUCLEUS_DEV_NAME", "Repo path"]
    rows = [
        ("Titu (yours)", "172.16.205.71", "Titu",
         "E:\\Projects\\NAPCO-Nucleus"),
        ("Atik", "172.16.205.108", "Atik", "F:\\Titu vai\\napco-nucleus"),
        ("Rocky", "?", "Rocky", "?"),
        ("Ferdows", "?", "Ferdows", "?"),
        ("Amin", "?", "Amin", "?"),
        ("Isruk", "?", "Isruk", "?"),
        ("Assad", "?", "Assad", "?"),
    ]

    header_row = [Paragraph(h, head_style) for h in headers]
    body_rows = []
    for dev, ip, name, repo in rows:
        body_rows.append([
            Paragraph(dev, cell_style),
            Paragraph(ip, cell_code),
            Paragraph(name, cell_code),
            Paragraph(repo, cell_code),
        ])

    # Tunable column widths — keep IP narrow, dev name + repo wider.
    col_widths = [
        1.25 * inch,  # Dev
        1.30 * inch,  # IP
        1.55 * inch,  # NUCLEUS_DEV_NAME
        CONTENT_W - (1.25 + 1.30 + 1.55) * inch,  # Repo path
    ]

    data = [header_row] + body_rows
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), APPX_TABLE_HEAD),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, APPX_BAR),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, GREY_BORDER),
        ("BOX", (0, 0), (-1, -1), 0.5, GREY_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ])
    # Zebra-stripe the body rows (alternate tint for readability).
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.add("BACKGROUND", (0, i), (-1, i), APPX_TABLE_ALT)
    t.setStyle(style)
    return t


# ── Page-template switching flowable ──────────────────────────────
#
# reportlab needs a NextPageTemplate flowable to switch chrome mid-document
# (we want the appendix pages to use the violet-accented header instead of
# the blue one). Import lazily so the rest of the file stays small.

from reportlab.platypus import NextPageTemplate as _NextPageTemplate  # noqa: E402


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
    frame_appendix = Frame(
        MARGIN, doc.bottomMargin,
        CONTENT_W,
        PAGE_H - 0.85 * inch - doc.bottomMargin,
        id="appendix", showBoundary=0,
    )
    doc.addPageTemplates([
        PageTemplate(id="First", frames=[frame_first], onPage=first_page),
        PageTemplate(id="Later", frames=[frame_later], onPage=later_page),
        PageTemplate(id="Appendix", frames=[frame_appendix],
                     onPage=appendix_page),
    ])
    doc.build(build())
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
