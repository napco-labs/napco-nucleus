"""Build the team-onboarding Setup Guide PDF (colleague-facing).

Mirrors docs/Quickstart.md: five steps to get a teammate's machine
streaming Teams chat + attachments + call recordings to the central
agent on MVPACCESS.

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
                      "Five steps to stream Teams chat, attachments, and calls to the central agent")
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
        "A <b>15-minute scheduled task</b> that pushes your recent Teams chat "
        "(and any attachments you've downloaded) to a shared folder on MVPACCESS.",
        "A <b>voice daemon</b> that records your Teams calls when it hears "
        "the start/stop phrases.",
    ], bullet_s))
    flow.append(_space(0.05))
    flow.append(Paragraph(
        "That's it. Titu triggers the heavy work — LLM identify and the "
        "client email draft — from the agent host. You just keep these "
        "two running.", body))

    # ── Step 1: Prerequisites ──────────────────────────────────────
    flow.append(_space(0.15))
    flow.append(_step_heading("Step 1", "Prerequisites"))
    flow.append(_bullets([
        "<b>Windows 10 or 11.</b> Teams chat ingest reads Teams' local IndexedDB cache, which is Windows-only.",
        "<b>MS Teams desktop</b>, signed in, with the client chats already opened at least once.",
        "<b>Git for Windows.</b>",
        "<b>Network access to the central share.</b> You should be able to open "
        "<font face=\"Courier\">\\\\172.16.205.209\\nucleus-central</font> in File Explorer. "
        "If not, ping Titu for credentials.",
    ], bullet_s))

    # ── Step 2: Clone ──────────────────────────────────────────────
    flow.append(_space(0.15))
    flow.append(_step_heading("Step 2", "Clone the repo"))
    flow.append(Paragraph(
        "Open PowerShell or Git Bash and run:", body))
    flow.append(_code(
        "git clone https://github.com/napco-labs/napco-nucleus.git<br/>"
        "cd napco-nucleus", code))

    # ── Step 3: setup.bat ─────────────────────────────────────────
    flow.append(_space(0.15))
    flow.append(_step_heading("Step 3", "Double-click  scripts\\setup.bat"))
    flow.append(Paragraph("It will:", body))
    flow.append(_bullets([
        "Install Python 3.12 if missing (UAC prompt — click <b>Yes</b>).",
        "Create a virtualenv at <font face=\"Courier\">.venv\\</font> and install all dependencies.",
        "Open <font face=\"Courier\">.env</font> in Notepad — pre-filled, "
        "<b>no secrets needed</b>.",
    ], bullet_s))
    flow.append(_space(0.05))
    flow.append(_callout(
        "<b>No Gmail App Password, no API key, nothing private.</b> The "
        "agent host (MVPACCESS) owns every credential — pulling email, "
        "posting drafts, hitting the LLM all happen there. Your machine "
        "only writes Teams chat and calls into a network folder using "
        "your normal Windows login.", body))
    flow.append(_space(0.1))
    flow.append(Paragraph(
        "In Notepad, just confirm <font face=\"Courier\">NUCLEUS_CENTRAL_PATH</font> "
        "matches the team's share (ships pre-set to "
        "<font face=\"Courier\">\\\\172.16.205.209\\nucleus-central</font>). Optionally set "
        "<font face=\"Courier\">NUCLEUS_DEV_NAME</font> to a friendlier label "
        "than your Windows username. Save and close.", body))
    flow.append(Paragraph(
        "You're done with this step when you see &ldquo;Setup complete.&rdquo;",
        body))

    # ── Step 4: Register the cron ─────────────────────────────────
    flow.append(_space(0.15))
    flow.append(_step_heading("Step 4", "Register the 15-min chat-push"))
    flow.append(Paragraph(
        "In an <b>admin PowerShell</b> (Start → &ldquo;PowerShell&rdquo; → "
        "right-click → <i>Run as administrator</i>), from inside the repo:",
        body))
    flow.append(_code(".\\scripts\\register-chat-push-task.ps1", code))
    flow.append(Paragraph(
        "Creates a &ldquo;NAPCO Nucleus - Chat Push&rdquo; entry in Task "
        "Scheduler that runs every 15 min, even when you're not logged in. "
        "To verify: <i>Task Scheduler → Task Scheduler Library</i> — look "
        "for the entry.", body))
    flow.append(Paragraph("To remove later:", body))
    flow.append(_code(
        ".\\scripts\\register-chat-push-task.ps1 -Unregister", code))

    # ── Step 5: Voice daemon ──────────────────────────────────────
    flow.append(_space(0.15))
    flow.append(_step_heading("Step 5", "Start the voice daemon"))
    flow.append(Paragraph(
        "Double-click <font face=\"Courier\">scripts\\start-daemon.bat</font>. "
        "Leave the terminal window running.", body))
    flow.append(Paragraph(
        "To autostart on login, drop a shortcut to the .bat into "
        "<font face=\"Courier\">shell:startup</font> "
        "(Win+R → type that → drop the shortcut into the folder that opens).",
        body))

    # ── Verify ────────────────────────────────────────────────────
    flow.append(_space(0.15))
    flow.append(_step_heading("Verify", "Confirm it's working", accent=ACCENT))
    flow.append(Paragraph("Fire one push immediately:", body))
    flow.append(_code(
        "Start-ScheduledTask -TaskName 'NAPCO Nucleus - Chat Push'", code))
    flow.append(Paragraph(
        "Then look at "
        "<font face=\"Courier\">\\\\172.16.205.209\\nucleus-central\\&lt;your name&gt;\\"
        "&lt;today's date&gt;\\chat\\</font> — you should see a "
        "<font face=\"Courier\">chat_&lt;HHMM&gt;-&lt;HHMM&gt;.docx</font> appear "
        "within ~30 seconds. If you don't, see Troubleshooting.", body))

    # ── Day-to-day table ──────────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_step_heading("Day-to-day", "What you do, what NN does"))

    rows = [
        [Paragraph("What you want", th), Paragraph("What you do", th)],
        [Paragraph("Get your activity into the central pipeline", td),
         Paragraph("<b>Nothing</b> — the cron handles it every 15 min.", td)],
        [Paragraph("Record a Teams call", td),
         Paragraph(
             "Say a start phrase (e.g. <b>&ldquo;Start&rdquo;</b>, "
             "<b>&ldquo;Start recording&rdquo;</b>, or "
             "<b>&ldquo;Assalamualaikum&rdquo;</b>) when the call begins; "
             "a stop phrase (e.g. <b>&ldquo;Stop&rdquo;</b>, "
             "<b>&ldquo;End call&rdquo;</b>, or "
             "<b>&ldquo;Allah Hafez&rdquo;</b>) when it ends. Full list "
             "below. The daemon only records during real Teams calls.", td)],
        [Paragraph("Include a file someone shared in Teams chat", td),
         Paragraph(
             "Click <b>Download</b> on the chat attachment. Files in your "
             "<font face=\"Courier\">~/Downloads</font> matching the chat's "
             "filename + size get auto-pushed on the next cron tick.", td)],
        [Paragraph("Pull updates after a <font face=\"Courier\">git pull</font> notice", td),
         Paragraph("Double-click <font face=\"Courier\">scripts\\update.bat</font>", td)],
        [Paragraph("Run an ad-hoc local pull (your own session, not the team's)", td),
         Paragraph("Double-click <font face=\"Courier\">scripts\\pull-now.bat</font>", td)],
    ]
    tbl = Table(rows, colWidths=[2.5 * inch, CONTENT_W - 2.5 * inch],
                repeatRows=1)
    tbl_style = [
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
    # Zebra striping for body rows
    for i in range(1, len(rows)):
        if i % 2 == 1:
            tbl_style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    tbl.setStyle(TableStyle(tbl_style))
    flow.append(tbl)

    # Voice phrases + attachments
    flow.append(_sub_heading("Voice phrases"))
    flow.append(Paragraph(
        "The daemon listens for any of these (case-insensitive):", body))
    flow.append(_bullets([
        "<b>Start recording</b> — &ldquo;Assalamualaikum&rdquo;, "
        "&ldquo;Salaam alaikum&rdquo;, &ldquo;Nucleus start&rdquo;, "
        "&ldquo;Start recording&rdquo;, &ldquo;Start record&rdquo;, "
        "&ldquo;Start call&rdquo;, &ldquo;Record start&rdquo;, "
        "&ldquo;Call start&rdquo;, &ldquo;Start&rdquo;, &ldquo;Record&rdquo;",
        "<b>Stop recording</b> — &ldquo;Allah Hafez&rdquo;, "
        "&ldquo;Khoda Hafiz&rdquo;, &ldquo;Nucleus stop&rdquo;, "
        "&ldquo;Stop recording&rdquo;, &ldquo;Stop record&rdquo;, "
        "&ldquo;End recording&rdquo;, &ldquo;End record&rdquo;, "
        "&ldquo;End call&rdquo;, &ldquo;Record end&rdquo;, "
        "&ldquo;Call end&rdquo;, &ldquo;End&rdquo;, &ldquo;Stop&rdquo;",
    ], bullet_s))
    flow.append(Paragraph(
        "Recording only fires when MS Teams has an active call. Saying "
        "any phrase with Teams idle does nothing — by design. To edit "
        "phrases, open <font face=\"Courier\">data\\teams\\voice_phrases.json</font> "
        "and restart the daemon.", body))

    flow.append(_sub_heading("About chat attachments"))
    flow.append(_callout(
        "The system pushes Teams chat files <b>only if you've downloaded "
        "them locally</b>. If a teammate shares "
        "<font face=\"Courier\">requirements.pdf</font> in chat and you "
        "never click &ldquo;Download&rdquo; on it, the file's content "
        "won't reach the LLM — only its filename and a URL will. "
        "<b>If a file matters for a client requirement, click Download.</b>",
        body))

    # ── Troubleshooting ───────────────────────────────────────────
    flow.append(_space(0.2))
    flow.append(_step_heading("Help", "Troubleshooting"))
    flow.append(_bullets([
        "<b>&ldquo;Python not found&rdquo;</b> after running setup.bat — open a "
        "brand-new PowerShell window and re-run setup. The PATH change from "
        "winget needs a fresh shell.",
        "<b>Scheduled task ran but no file on central</b> — check the SMB "
        "share is reachable: "
        "<font face=\"Courier\">Test-Path \\\\172.16.205.209\\nucleus-central</font>. "
        "If it returns False, get an account on MVPACCESS from Titu.",
        "<b>Voice daemon prints &ldquo;no Teams session in Active state&rdquo;</b> "
        "when you say a phrase — that's the Teams-only gate working as designed. "
        "Pass <font face=\"Courier\">--allow-any-call</font> to disable: "
        "<font face=\"Courier\">python -m teams.voice_daemon --allow-any-call</font>.",
        "<b>Recording captured your voice but nothing else</b> — "
        "<i>Teams → Settings → Devices</i>, set Speaker to "
        "&ldquo;Same as system / Default&rdquo;. Teams's separate "
        "Communications Device default makes the WASAPI loopback miss "
        "the other party.",
        "<b>&ldquo;pip install failed&rdquo;</b> in setup.bat — usually a "
        "corporate proxy issue. Run setup.bat again from inside your VPN.",
    ], bullet_s))
    flow.append(_space(0.05))
    flow.append(Paragraph(
        "For anything else, ping <b>Titu</b>.", body))

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
