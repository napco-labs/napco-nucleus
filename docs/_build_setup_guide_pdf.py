"""Build the team-onboarding Setup Guide PDF (colleague-facing).

Mirrors docs/Quickstart.md (2026-05 architecture): five steps to get
a teammate's machine streaming Teams chat + attachments + call
recordings to the central agent on MVPACCESS, plus the install
gotchas that bit real-world rollouts.

Produces:
    docs/Setup_Guide.pdf

Run:  python docs/_build_setup_guide_pdf.py
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
    Spacer, Table, TableStyle, ListFlowable, ListItem,
)
from reportlab.platypus.flowables import HRFlowable

# ── Palette ───────────────────────────────────────────────────────
NAVY = colors.HexColor("#1F3A5F")
ACCENT = colors.HexColor("#3B6FB6")
SOFT_NAVY = colors.HexColor("#2E4D7A")
LIGHT_BLUE = colors.HexColor("#E8F0FA")
ZEBRA = colors.HexColor("#F7F9FC")
GREY_BORDER = colors.HexColor("#D8DEE6")
GREY_TEXT = colors.HexColor("#445064")
BODY_TEXT = colors.HexColor("#1F232B")
CODE_BG = colors.HexColor("#F4F6F9")
CODE_BORDER = colors.HexColor("#E1E6EE")
CALLOUT_BG = colors.HexColor("#FFF8E5")
CALLOUT_BAR = colors.HexColor("#E5A93B")
SUBTLE = colors.HexColor("#7A8499")

HERE = Path(__file__).parent
OUT = HERE / "Setup_Guide.pdf"

PAGE_W, PAGE_H = LETTER
MARGIN = 0.8 * inch
TITLE_BAR_H = 1.55 * inch
CONTENT_W = PAGE_W - 2 * MARGIN


# ── Page chrome ───────────────────────────────────────────────────

def first_page(canvas, doc):
    canvas.saveState()
    # Title bar
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - TITLE_BAR_H, PAGE_W, TITLE_BAR_H, fill=1, stroke=0)
    # Thin accent stripe at the bottom of the title bar
    canvas.setFillColor(ACCENT)
    canvas.rect(0, PAGE_H - TITLE_BAR_H, PAGE_W, 0.04 * inch, fill=1, stroke=0)
    # Title
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 26)
    canvas.drawString(MARGIN, PAGE_H - TITLE_BAR_H + 0.7 * inch,
                      "NAPCO Nucleus")
    canvas.setFont("Helvetica", 13)
    canvas.setFillColor(colors.HexColor("#C8D4E6"))
    canvas.drawString(MARGIN, PAGE_H - TITLE_BAR_H + 0.42 * inch,
                      "Team Onboarding  |  Setup Guide")
    canvas.setFont("Helvetica-Oblique", 10)
    canvas.setFillColor(colors.HexColor("#A4B4CC"))
    canvas.drawString(MARGIN, PAGE_H - TITLE_BAR_H + 0.18 * inch,
                      "Five steps to stream Teams chat, attachments, and calls into the central pipeline  ·  2026-05")
    _draw_footer(canvas, doc)
    canvas.restoreState()


def later_page(canvas, doc):
    canvas.saveState()
    # Slim header rule with project mark
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
                      "Team Onboarding · Setup Guide")
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
    """STEP N (small caps, accent) + section title (navy) + underline rule.
    Returned as a single Flowable group so the unit stays together."""
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


def _section_heading(title):
    """A non-numbered heading (used for 'What this is')."""
    eyebrow_style = ParagraphStyle(
        "SecLabel", fontName="Helvetica-Bold", fontSize=8.5,
        textColor=ACCENT, leading=10, spaceAfter=1,
    )
    title_style = ParagraphStyle(
        "SecTitle", fontName="Helvetica-Bold", fontSize=15.5,
        textColor=NAVY, leading=19, spaceAfter=2,
    )
    return KeepTogether([
        Paragraph("OVERVIEW", eyebrow_style),
        Paragraph(title, title_style),
        HRFlowable(width=0.5 * inch, thickness=1.4, color=ACCENT,
                   spaceBefore=0, spaceAfter=8, lineCap="round"),
    ])


def _sub_heading(title):
    style = ParagraphStyle(
        "Sub", fontName="Helvetica-Bold", fontSize=11.5,
        textColor=SOFT_NAVY, leading=14.5, spaceBefore=10, spaceAfter=4,
    )
    return Paragraph(title, style)


def _callout(html, body_style):
    """Yellow callout with a thick left accent bar."""
    bar_w = 0.08 * inch
    inner_w = CONTENT_W - bar_w
    t = Table(
        [["", Paragraph(html, body_style)]],
        colWidths=[bar_w, inner_w],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), CALLOUT_BAR),
        ("BACKGROUND", (1, 0), (1, -1), CALLOUT_BG),
        ("LINEABOVE", (0, 0), (-1, 0), 0, colors.transparent),
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


def _code(text, code_style):
    """Code block: monospace, soft bg, light border."""
    t = Table([[Paragraph(text, code_style)]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, CODE_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


def _bullets(items, bullet_style):
    """Bulleted list with colored disc bullets, even indent."""
    return ListFlowable(
        [ListItem(Paragraph(t, bullet_style), leftIndent=18,
                  bulletColor=ACCENT) for t in items],
        bulletType="bullet", start="bulletchar",
        leftIndent=14, bulletFontSize=10, bulletOffsetY=-1,
    )


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
        "Code", fontName="Courier", fontSize=9.5, leading=13,
        textColor=BODY_TEXT,
    )
    th = ParagraphStyle(
        "TH", fontName="Helvetica-Bold", fontSize=9.8,
        textColor=colors.white, leading=12,
    )
    td = ParagraphStyle(
        "TD", fontName="Helvetica", fontSize=9.8,
        textColor=BODY_TEXT, leading=13.5, spaceAfter=0,
    )
    bullet_s = ParagraphStyle(
        "Bullet", parent=body, fontSize=10.5, leading=14.5,
        leftIndent=0, spaceAfter=4,
    )

    flow = []
    flow.append(_space(0.25))

    # ── Overview ────────────────────────────────────────────────────
    flow.append(_section_heading("What this is"))
    flow.append(Paragraph(
        "Your machine runs two small background jobs:", intro))
    flow.append(_bullets([
        "<b>Three Scheduled Tasks</b> that push your recent Teams chat (and any "
        "attachments you've downloaded) to the central share on MVPACCESS at "
        "different cadences across the day &mdash; see the schedule in Step 4.",
        "<b>A voice daemon</b> that records your Teams calls when it hears a "
        "start/stop phrase. Now <b>24&times;7</b> (no BD-time-window gate).",
    ], bullet_s))
    flow.append(_space(0.05))
    flow.append(Paragraph(
        "That's it. Zaman triggers the heavy work &mdash; transcription, LLM "
        "identify, and the client email draft &mdash; on MVPACCESS. You just "
        "keep these two running on your laptop.", body))
    flow.append(_space(0.05))
    flow.append(_callout(
        "<b>No secrets on your machine.</b> No Gmail App Password, IMAP "
        "credentials, Claude API key, or Groq key. Every secret lives on "
        "MVPACCESS. Your laptop only needs network access to the central "
        "SMB share, which uses your normal Windows login.", body))

    # ── Step 1: Prerequisites ──────────────────────────────────────
    flow.append(_space(0.15))
    flow.append(_step_heading("Step 1", "Prerequisites"))
    flow.append(_bullets([
        "<b>Windows 10 or 11.</b> Teams chat ingest reads Teams' local IndexedDB cache &mdash; Windows-only.",
        "<b>MS Teams desktop</b>, signed in, with every client chat opened at least once "
        "(so Teams populates its local cache).",
        "<b>Git for Windows.</b>",
        "<b>SMB access</b> to <font face=\"Courier\">\\\\172.16.205.209\\nucleus-central</font>. "
        "Open File Explorer, paste that path, hit Enter. If it opens, you're good.",
        "<b>Admin rights on your laptop</b>, just for Step 4 (Scheduled Task registration).",
    ], bullet_s))

    # ── Step 2: Clone ──────────────────────────────────────────────
    flow.append(_space(0.15))
    flow.append(_step_heading("Step 2", "Clone the repo"))
    flow.append(Paragraph(
        "Open PowerShell or Git Bash and run:", body))
    flow.append(_code(
        "git clone https://github.com/napco-labs/napco-nucleus.git<br/>"
        "cd napco-nucleus", code))
    flow.append(Paragraph(
        "You can clone <b>anywhere</b> &mdash; "
        "<font face=\"Courier\">C:\\napco-nucleus</font>, "
        "<font face=\"Courier\">D:\\Dev\\NAPCO-Nucleus</font>, "
        "<font face=\"Courier\">%USERPROFILE%\\source\\repos\\napco-nucleus</font>, whatever. "
        "Scripts resolve paths relative to themselves; the location doesn't matter.", body))
    flow.append(_callout(
        "<b>Avoid paths with spaces</b> (e.g. <font face=\"Courier\">C:\\My Projects\\</font>). "
        "The .bat scripts mostly handle them but some edge cases bite. "
        "Pick a path without spaces and save yourself time.", body))

    # ── Step 3: setup.bat ─────────────────────────────────────────
    flow.append(_space(0.15))
    flow.append(_step_heading("Step 3", "Run  scripts\\setup.bat"))
    flow.append(Paragraph("Either of these works:", body))
    flow.append(_code("scripts\\setup.bat", code))
    flow.append(Paragraph("Or double-click <font face=\"Courier\">setup.bat</font> in File Explorer. It will:", body))
    flow.append(_bullets([
        "Install Python 3.12 if missing (UAC prompt &mdash; click <b>Yes</b>).",
        "Create <font face=\"Courier\">.venv\\</font> and install all dependencies (~2 min).",
        "Open <font face=\"Courier\">.env</font> in Notepad for you to confirm one line.",
    ], bullet_s))
    flow.append(_space(0.05))
    flow.append(Paragraph(
        "If you see &ldquo;Python not found&rdquo; right after, "
        "<b>open a brand-new PowerShell</b> and re-run "
        "<font face=\"Courier\">setup.bat</font>. PATH changes from a fresh "
        "Python install need a new shell.", body))
    flow.append(_space(0.08))
    flow.append(Paragraph(
        "In Notepad, the only line that matters is "
        "<font face=\"Courier\">NUCLEUS_CENTRAL_PATH=\\\\172.16.205.209\\nucleus-central</font>. "
        "It's pre-filled. Optionally set "
        "<font face=\"Courier\">NUCLEUS_DEV_NAME</font> to a friendlier label "
        "than your Windows username. Save and close &mdash; you'll see "
        "&ldquo;Setup complete.&rdquo;", body))

    # ── Step 4: Register the chat-push tasks ──────────────────────
    flow.append(_space(0.15))
    flow.append(_step_heading(
        "Step 4", "Register the chat-push Scheduled Tasks (admin)"))
    flow.append(Paragraph(
        "This is the most common place to trip. Three rules:", body))
    flow.append(_bullets([
        "<b>Use Administrator PowerShell</b>, not regular PowerShell, not cmd. "
        "Press <b>Win+X</b> &rarr; <b>Terminal (Admin)</b> &rarr; click <b>Yes</b> on UAC.",
        "<b>Don't double-click .ps1 files</b> &mdash; they open in Notepad by default. "
        "Run them through PowerShell instead.",
        "<b>You may need an execution-policy bypass</b> for the current session.",
    ], bullet_s))
    flow.append(_space(0.05))
    flow.append(Paragraph(
        "From admin PowerShell, <font face=\"Courier\">cd</font> into wherever "
        "you cloned the repo. <b>Always wrap the path in double quotes</b> "
        "&mdash; the same command works whether your path has spaces or not:", body))
    flow.append(_code(
        "cd \"E:\\Projects\\NAPCO-Nucleus\"<br/>"
        "Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass<br/>"
        ".\\scripts\\register-chat-push-task.ps1", code))
    flow.append(Paragraph(
        "Replace the path with wherever you actually cloned the repo &mdash; e.g. "
        "<font face=\"Courier\">cd \"C:\\napco-nucleus\"</font>, "
        "<font face=\"Courier\">cd \"D:\\Dev\\NAPCO-Nucleus\"</font>.", body))
    flow.append(Paragraph(
        "You should see <b>three</b> &ldquo;Registered: &hellip;&rdquo; lines "
        "&mdash; Day, Transition, Evening &mdash; plus a coverage summary. "
        "The script unregisters any old "
        "<font face=\"Courier\">'NAPCO Nucleus - Chat Push'</font> task automatically.", body))

    # Chat-push schedule table
    flow.append(_sub_heading("Chat-push schedule"))
    sch_rows = [
        [Paragraph("Task", th), Paragraph("BD time", th),
         Paragraph("Cadence", th), Paragraph("Lookback", th)],
        [Paragraph("&hellip; (Day)", td),
         Paragraph("10:00, 12:00, 14:00, 16:00", td),
         Paragraph("every 2 hr", td),
         Paragraph("last 120 min", td)],
        [Paragraph("&hellip; (Transition)", td),
         Paragraph("17:30", td),
         Paragraph("once daily", td),
         Paragraph("last 90 min", td)],
        [Paragraph("&hellip; (Evening)", td),
         Paragraph("18:00, 18:30, &hellip;, 24:00", td),
         Paragraph("every 30 min", td),
         Paragraph("last 30 min", td)],
    ]
    sch = Table(sch_rows,
                colWidths=[1.4 * inch, 2.0 * inch, 1.4 * inch,
                           CONTENT_W - 1.4 * inch - 2.0 * inch - 1.4 * inch],
                repeatRows=1)
    sch_style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, GREY_BORDER),
        ("LINEBELOW", (0, 0), (-1, 0), 0, GREY_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for i in range(1, len(sch_rows)):
        if i % 2 == 1:
            sch_style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    sch.setStyle(TableStyle(sch_style))
    flow.append(sch)
    flow.append(_space(0.05))
    flow.append(Paragraph(
        "Higher cadence in the evening &mdash; that's peak US-client interaction time.", body))
    flow.append(Paragraph("To remove later:", body))
    flow.append(_code(".\\scripts\\register-chat-push-task.ps1 -Unregister", code))

    # ── Step 5: Voice daemon ──────────────────────────────────────
    flow.append(_space(0.15))
    flow.append(_step_heading("Step 5", "Install the voice daemon (autostart)"))
    flow.append(Paragraph(
        "Double-click <font face=\"Courier\">"
        "scripts\\install-voice-daemon.bat</font>. It registers "
        "<b>NAPCO Nucleus - Voice Daemon</b> as a Windows Scheduled Task "
        "that fires on every logon, restarts on crash, and starts the "
        "daemon immediately so you don't have to log out and back in. "
        "A console window appears with the daemon's logs &mdash; you can "
        "minimize it.", body))
    flow.append(Paragraph(
        "The daemon listens for start/stop phrases (case-insensitive) and "
        "only fires the recorder when MS Teams is actually in a call. Now "
        "<b>24&times;7</b> &mdash; no BD-time-window gate.", body))
    flow.append(Paragraph("To remove later:", body))
    flow.append(_code(
        "scripts\\uninstall-voice-daemon.bat", code))

    # ── Verify ────────────────────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Verify", "Three quick checks"))
    flow.append(Paragraph("1. All three Scheduled Tasks registered and Ready?", body))
    flow.append(_code(
        "Get-ScheduledTask -TaskName 'NAPCO Nucleus*' |<br/>"
        "    Select-Object TaskName, State", code))
    flow.append(Paragraph(
        "Expected: three rows &mdash; (Day), (Transition), (Evening), all Ready. "
        "No plain <font face=\"Courier\">NAPCO Nucleus - Chat Push</font>, no (Backfill).", body))
    flow.append(_space(0.05))
    flow.append(Paragraph("2. Voice daemon running?", body))
    flow.append(_code("Get-Process python -ErrorAction SilentlyContinue", code))
    flow.append(Paragraph(
        "Expected: at least one python.exe process.", body))
    flow.append(_space(0.05))
    flow.append(Paragraph(
        "3. Fire one chat-push immediately and check central:", body))
    flow.append(_code(
        "Start-ScheduledTask -TaskName 'NAPCO Nucleus - Chat Push (Evening)'<br/>"
        "Start-Sleep 30<br/>"
        "Get-ChildItem \"\\\\172.16.205.209\\nucleus-central\\$env:USERNAME\\"
        "$(Get-Date -Format yyyy-MM-dd)\\chat\\\"", code))
    flow.append(Paragraph(
        "Expected: a <font face=\"Courier\">chat_&lt;HHMM&gt;-&lt;HHMM&gt;.docx</font> "
        "file with a recent <i>LastWriteTime</i>.", body))

    # ── Common install gotchas table ──────────────────────────────
    flow.append(_space(0.2))
    flow.append(_step_heading("Gotchas", "Common install issues"))
    g_rows = [
        [Paragraph("Symptom", th), Paragraph("Fix", th)],
        [Paragraph("Double-clicked a .ps1 and it opened in Notepad", td),
         Paragraph("Right-click &rarr; &ldquo;Run with PowerShell&rdquo;, or invoke explicitly: "
                   "<font face=\"Courier\">powershell.exe -NoProfile "
                   "-ExecutionPolicy Bypass -File scripts\\register-chat-push-task.ps1</font>", td)],
        [Paragraph("&ldquo;running scripts is disabled on this system&rdquo;", td),
         Paragraph("Run once before the script: "
                   "<font face=\"Courier\">Set-ExecutionPolicy -Scope Process "
                   "-ExecutionPolicy Bypass</font>", td)],
        [Paragraph("&ldquo;Access is denied&rdquo; on Unregister-ScheduledTask", td),
         Paragraph("Not in admin PowerShell. Reopen as Administrator and retry.", td)],
        [Paragraph("HRESULT 0x800700b7 (ERROR_ALREADY_EXISTS) on Register-ScheduledTask", td),
         Paragraph("Orphan task XML on disk. The script's cleanup falls back to "
                   "<font face=\"Courier\">schtasks /delete</font> automatically &mdash; "
                   "just re-run the script and it heals itself.", td)],
        [Paragraph("Setup.bat says &ldquo;Python not found&rdquo; right after install", td),
         Paragraph("Open a brand-new PowerShell and re-run the script. "
                   "PATH change needs a fresh shell.", td)],
        [Paragraph("<font face=\"Courier\">pip install</font> fails", td),
         Paragraph("Corporate proxy / VPN issue. Re-run from inside your company VPN.", td)],
        [Paragraph("Path with spaces in clone location", td),
         Paragraph("Some .bat scripts handle them poorly. Re-clone to a space-free "
                   "path (e.g. <font face=\"Courier\">C:\\napco-nucleus</font>).", td)],
    ]
    g_tbl = Table(g_rows, colWidths=[2.5 * inch, CONTENT_W - 2.5 * inch], repeatRows=1)
    g_style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, GREY_BORDER),
        ("LINEBELOW", (0, 0), (-1, 0), 0, GREY_BORDER),
        ("LINEBEFORE", (1, 0), (1, -1), 0.4, GREY_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for i in range(1, len(g_rows)):
        if i % 2 == 1:
            g_style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    g_tbl.setStyle(TableStyle(g_style))
    flow.append(g_tbl)

    # ── Day-to-day table ──────────────────────────────────────────
    flow.append(_space(0.2))
    flow.append(_step_heading("Day-to-day", "What you do, what NN does"))
    d_rows = [
        [Paragraph("What you want", th), Paragraph("What you do", th)],
        [Paragraph("Get today's Teams chat into the pipeline", td),
         Paragraph("<b>Nothing.</b> Day/Transition/Evening crons handle BD 10:00&ndash;24:00 "
                   "automatically. The BD 00:00&ndash;10:00 gap is unscheduled &mdash; if late-night "
                   "chat needs to land before 10:00, run "
                   "<font face=\"Courier\">scripts\\push-chat.bat</font> manually.", td)],
        [Paragraph("Record a Teams call", td),
         Paragraph(
             "Say a start phrase (<b>&ldquo;Assalamualaikum&rdquo;</b> / "
             "<b>&ldquo;Start&rdquo;</b> / <b>&ldquo;Record start&rdquo;</b>) when "
             "the call begins. Say a stop phrase (<b>&ldquo;Allah Hafez&rdquo;</b> / "
             "<b>&ldquo;Stop&rdquo;</b> / <b>&ldquo;End call&rdquo;</b>) when it "
             "ends. Recording only fires when Teams is actually in a call.", td)],
        [Paragraph("Include a file from Teams chat", td),
         Paragraph(
             "Click <b>Download</b> on the attachment in Teams. The chat-push picks it "
             "up from <font face=\"Courier\">~/Downloads</font> on the next cron tick. "
             "Files that aren't downloaded leave only their URL on central &mdash; "
             "the LLM can't read their content.", td)],
        [Paragraph("Pull updates after a <font face=\"Courier\">git pull</font> notice", td),
         Paragraph("Double-click <font face=\"Courier\">scripts\\update.bat</font>", td)],
        [Paragraph("Ad-hoc push of recent chat", td),
         Paragraph("Double-click <font face=\"Courier\">scripts\\push-chat.bat</font> (pushes last 15 min)", td)],
    ]
    d_tbl = Table(d_rows, colWidths=[2.5 * inch, CONTENT_W - 2.5 * inch], repeatRows=1)
    d_style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, GREY_BORDER),
        ("LINEBELOW", (0, 0), (-1, 0), 0, GREY_BORDER),
        ("LINEBEFORE", (1, 0), (1, -1), 0.4, GREY_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for i in range(1, len(d_rows)):
        if i % 2 == 1:
            d_style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    d_tbl.setStyle(TableStyle(d_style))
    flow.append(d_tbl)

    # Voice phrases + attachments
    flow.append(_sub_heading("Voice phrases"))
    flow.append(Paragraph(
        "The daemon listens for any of these (case-insensitive):", body))
    flow.append(_bullets([
        "<b>Start recording</b> &mdash; &ldquo;Assalamualaikum&rdquo;, "
        "&ldquo;Salaam alaikum&rdquo;, &ldquo;Nucleus start&rdquo;, "
        "&ldquo;Start recording&rdquo;, &ldquo;Record start&rdquo;, "
        "&ldquo;Call start&rdquo;, &ldquo;Start&rdquo;, &ldquo;Record&rdquo;",
        "<b>Stop recording</b> &mdash; &ldquo;Allah Hafez&rdquo;, "
        "&ldquo;Khoda Hafiz&rdquo;, &ldquo;Nucleus stop&rdquo;, "
        "&ldquo;Stop recording&rdquo;, &ldquo;End recording&rdquo;, "
        "&ldquo;Call end&rdquo;, &ldquo;End&rdquo;, &ldquo;Stop&rdquo;",
    ], bullet_s))
    flow.append(Paragraph(
        "Recording only fires when MS Teams has an active call. Saying "
        "any phrase with Teams idle does nothing &mdash; by design. To edit "
        "phrases, open <font face=\"Courier\">data\\teams\\voice_phrases.json</font> "
        "and restart the daemon.", body))

    flow.append(_sub_heading("About chat attachments"))
    flow.append(_callout(
        "The push captures chat messages plus any files that are downloaded locally "
        "and live in <font face=\"Courier\">~/Downloads</font> with a matching "
        "filename/size. <b>If a file matters for a requirement, click Download on it "
        "in Teams.</b> Otherwise the LLM sees only the filename and URL, not the content.",
        body))

    # ── Troubleshooting ───────────────────────────────────────────
    flow.append(_space(0.2))
    flow.append(_step_heading("Help", "Troubleshooting"))
    flow.append(_bullets([
        "<b>Scheduled task ran but no file on central</b> &mdash; verify "
        "<font face=\"Courier\">Test-Path \\\\172.16.205.209\\nucleus-central</font>. "
        "If False, get on the VPN or ask Zaman for share access.",
        "<b>&ldquo;no Teams session in Active state&rdquo;</b> &mdash; the Teams-only "
        "gate working as designed. Teams must be ringing or in a call. Pass "
        "<font face=\"Courier\">--allow-any-call</font> to disable.",
        "<b>Recording captured your voice but not the other party's</b> &mdash; "
        "<i>Teams &rarr; Settings &rarr; Devices</i>, set Speaker to "
        "&ldquo;Same as system / Default&rdquo;. The separate "
        "Communications Device default makes WASAPI loopback miss the other party.",
        "<b>Teams chat ingest captures nothing even though you're chatting</b> &mdash; "
        "every chat must have been opened at least once in the desktop client so "
        "Teams writes its content to disk. Open each conversation once and let it load.",
    ], bullet_s))
    flow.append(_space(0.05))
    flow.append(Paragraph(
        "For anything else, ping <b>Zaman</b> with the exact error message and which step you were on.", body))

    # ── Upgrading from old setup ─────────────────────────────────
    flow.append(_space(0.2))
    flow.append(_step_heading("Upgrade", "From the pre-2026-05 single-task setup"))
    flow.append(Paragraph(
        "If <font face=\"Courier\">Get-ScheduledTask -TaskName 'NAPCO Nucleus*'</font> "
        "shows a plain <font face=\"Courier\">NAPCO Nucleus - Chat Push</font> "
        "(singular, no parens), you're on the pre-2026-05 single-task setup. Upgrade:",
        body))
    flow.append(_code(
        "cd \"E:\\Projects\\NAPCO-Nucleus\"   # replace with your actual clone path<br/>"
        "git pull<br/>"
        "Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass<br/>"
        ".\\scripts\\register-chat-push-task.ps1", code))
    flow.append(Paragraph(
        "The script unregisters the old <font face=\"Courier\">Chat Push</font> + "
        "<font face=\"Courier\">Chat Push (Backfill)</font> tasks and installs "
        "the new Day/Transition/Evening triple. Verify with the same "
        "<font face=\"Courier\">Get-ScheduledTask</font> command afterward &mdash; "
        "you should see exactly three tasks, all Ready.", body))

    # ── Notes ─────────────────────────────────────────────────────
    flow.append(_space(0.25))
    flow.append(_step_heading("Notes", "Three things to keep in mind"))

    note_num_style = ParagraphStyle(
        "NoteNum", fontName="Helvetica-Bold", fontSize=11,
        textColor=colors.white, leading=14, alignment=1,
    )
    note_title_style = ParagraphStyle(
        "NoteTitle", fontName="Helvetica-Bold", fontSize=12,
        textColor=NAVY, leading=15, spaceAfter=3,
    )
    note_body_style = ParagraphStyle(
        "NoteBody", parent=body, fontSize=10.5, leading=14.5,
        spaceAfter=0,
    )

    def _note(num, title, body_html):
        badge = Table([[Paragraph(num, note_num_style)]],
                      colWidths=[0.36 * inch], rowHeights=[0.36 * inch])
        badge.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), ACCENT),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        content = [Paragraph(title, note_title_style),
                   Paragraph(body_html, note_body_style)]
        row = Table([[badge, content]],
                    colWidths=[0.5 * inch, CONTENT_W - 0.5 * inch])
        row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (0, 0), "TOP"),
            ("VALIGN", (1, 0), (1, 0), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (0, 0), 1),
            ("TOPPADDING", (1, 0), (1, 0), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (1, 0), (1, 0), 12),
        ]))
        return KeepTogether([row, Spacer(1, 0.18 * inch)])

    flow.append(_note(
        "1",
        "Drive folder for requirement files",
        "Drop any client-supplied PDF, Word doc, audio recording, or "
        "plain text into this Google Drive folder. The agent host "
        "pulls everything in this folder during each run and extracts "
        "the text for requirement identification.<br/>"
        '<font face="Courier" color="#1F3A5F">'
        "https://drive.google.com/drive/u/0/folders/"
        "1u7Y2I17VKRnyoBRTY97_W81Lt7Hp5PK3</font>"
    ))
    flow.append(_note(
        "2",
        "Email destination for requirements",
        "Any email forwarded to or addressed to "
        '<b><font face="Courier" color="#1F3A5F">'
        "khasan@ael-bd.com</font></b> "
        "is automatically picked up by the system. Body text plus "
        "any PDF / Word / Excel / text attachments get extracted and "
        "fed into the requirement identifier."
    ))
    flow.append(_note(
        "3",
        "Teams chat, attachments, and calls are auto-shipped",
        "Once setup is complete, your MS Teams chats, the files you "
        "download from chat, and any calls you record (with the "
        "voice phrases) are <b>automatically sent to central</b> "
        "where requirement management runs. You don't have to manually "
        "export, copy, or forward anything &mdash; just keep Teams open "
        "and the voice daemon running."
    ))

    return flow


# ── Document ──────────────────────────────────────────────────────

def main():
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=LETTER,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=TITLE_BAR_H + 0.05 * inch,
        bottomMargin=0.75 * inch,
        title="NAPCO Nucleus — Team Onboarding Setup Guide",
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
