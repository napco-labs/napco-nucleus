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
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table,
    TableStyle, ListFlowable, ListItem,
)

NAVY = colors.HexColor("#1F3A5F")
ACCENT = colors.HexColor("#3B6FB6")
LIGHT_BLUE = colors.HexColor("#E8F0FA")
GREY_BORDER = colors.HexColor("#D8DEE6")
GREY_TEXT = colors.HexColor("#445064")
BODY_TEXT = colors.HexColor("#1F232B")
CODE_BG = colors.HexColor("#F2F4F7")
CALLOUT_BG = colors.HexColor("#FFF8E5")
CALLOUT_BORDER = colors.HexColor("#E5C66B")

HERE = Path(__file__).parent
OUT = HERE / "Setup_Guide.pdf"

PAGE_W, PAGE_H = LETTER
MARGIN = 0.75 * inch
TITLE_BAR_H = 1.4 * inch


def first_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - TITLE_BAR_H, PAGE_W, TITLE_BAR_H, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 24)
    canvas.drawString(MARGIN, PAGE_H - TITLE_BAR_H + 0.55 * inch,
                      "NAPCO Nucleus — Team Onboarding")
    canvas.setFont("Helvetica", 12)
    canvas.setFillColor(colors.HexColor("#C8D4E6"))
    canvas.drawString(MARGIN, PAGE_H - TITLE_BAR_H + 0.25 * inch,
                      "Five steps to stream Teams chat, attachments, and calls to the central agent")
    canvas.setStrokeColor(GREY_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 0.55 * inch, PAGE_W - MARGIN, 0.55 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY_TEXT)
    canvas.drawString(MARGIN, 0.35 * inch,
                      "NAPCO Nucleus  |  github.com/napco-labs/napco-nucleus")
    canvas.drawRightString(PAGE_W - MARGIN, 0.35 * inch, f"Page {doc.page}")
    canvas.restoreState()


def later_page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(GREY_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 0.55 * inch, PAGE_W - MARGIN, 0.55 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY_TEXT)
    canvas.drawString(MARGIN, 0.35 * inch,
                      "NAPCO Nucleus — Team Onboarding")
    canvas.drawRightString(PAGE_W - MARGIN, 0.35 * inch, f"Page {doc.page}")
    canvas.restoreState()


def _callout(text, body):
    """Render a yellow callout box."""
    t = Table([[Paragraph(text, body)]], colWidths=[PAGE_W - 2 * MARGIN - 0.2 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CALLOUT_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, CALLOUT_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def build():
    body = ParagraphStyle("Body", fontName="Helvetica", fontSize=10.5,
                          leading=14.5, textColor=BODY_TEXT, spaceAfter=8)
    h1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=14,
                        leading=18, textColor=NAVY, spaceBefore=12,
                        spaceAfter=6)
    h2 = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=11.5,
                        leading=15, textColor=NAVY, spaceBefore=8, spaceAfter=4)
    code = ParagraphStyle("Code", fontName="Courier", fontSize=9,
                          leading=12, textColor=BODY_TEXT, leftIndent=8,
                          rightIndent=8, spaceBefore=4, spaceAfter=8,
                          backColor=CODE_BG, borderPadding=6)
    th = ParagraphStyle("TH", fontName="Helvetica-Bold", fontSize=9.5,
                        textColor=NAVY, leading=12)
    td = ParagraphStyle("TD", fontName="Helvetica", fontSize=9.5,
                        textColor=BODY_TEXT, leading=13)
    bullet_s = ParagraphStyle("Bullet", parent=body, fontSize=10.5,
                              leading=14, leftIndent=16, bulletIndent=4,
                              spaceAfter=3)

    flow = []
    flow.append(Spacer(1, 0.3 * inch))

    # ── What this is ────────────────────────────────────────────────
    flow.append(Paragraph("What this is", h1))
    flow.append(Paragraph(
        "Your machine runs two tiny background jobs:", body))
    flow.append(ListFlowable([
        ListItem(Paragraph(
            "A <b>15-minute scheduled task</b> that pushes your recent "
            "Teams chat (+ any attachments you've downloaded) to a "
            "shared folder on MVPACCESS.", bullet_s), leftIndent=14),
        ListItem(Paragraph(
            "A <b>voice daemon</b> that records your Teams calls when "
            "it hears the start/stop phrases.", bullet_s), leftIndent=14),
    ], bulletType="bullet", leftIndent=10))
    flow.append(Paragraph(
        "That's it. Titu triggers the heavy work (LLM identify + "
        "client email draft) from the agent host. You just keep these "
        "two running.", body))

    # ── Section 1: Prerequisites ────────────────────────────────────
    flow.append(Paragraph("1. Prerequisites", h1))
    items = [
        "<b>Windows 10 or 11.</b> Teams chat ingest reads Teams' local IndexedDB cache, which is Windows-only.",
        "<b>MS Teams desktop</b>, signed in, with the client chats already opened at least once.",
        "<b>Git for Windows.</b>",
        "<b>Network access to the central share.</b> You should be able to open <font face=\"Courier\">\\\\MVPACCESS\\nucleus</font> in File Explorer. If not, ping Titu for credentials.",
    ]
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_s), leftIndent=14, value="circle") for t in items],
        bulletType="bullet", leftIndent=10,
    ))

    # ── Section 2: Clone ────────────────────────────────────────────
    flow.append(Paragraph("2. Clone the repo", h1))
    flow.append(Paragraph(
        "Open PowerShell or Git Bash and run:", body))
    flow.append(Paragraph(
        "git clone https://github.com/napco-labs/napco-nucleus.git<br/>"
        "cd napco-nucleus", code))

    # ── Section 3: setup.bat ────────────────────────────────────────
    flow.append(Paragraph("3. Double-click scripts\\setup.bat", h1))
    flow.append(Paragraph("It will:", body))
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_s), leftIndent=14, value="circle") for t in [
            "Install Python 3.12 if missing (UAC prompt — click Yes).",
            "Create a virtualenv at <font face=\"Courier\">.venv\\</font> and install all dependencies.",
            "Open <font face=\"Courier\">.env</font> in Notepad — pre-filled, <b>no secrets needed</b>.",
        ]],
        bulletType="bullet", leftIndent=10,
    ))
    flow.append(_callout(
        "<b>No Gmail App Password, no API key, nothing private.</b> "
        "The agent host (MVPACCESS) owns every credential — pulling "
        "email, posting drafts, hitting the LLM all happen there. "
        "Your machine only writes Teams chat/calls into a network "
        "folder using your normal Windows login.", body))
    flow.append(Spacer(1, 0.08 * inch))
    flow.append(Paragraph(
        "In Notepad, just confirm <font face=\"Courier\">NUCLEUS_CENTRAL_PATH</font> "
        "matches the team's share (it ships pre-set to "
        "<font face=\"Courier\">\\\\MVPACCESS\\nucleus</font>). Optionally set "
        "<font face=\"Courier\">NUCLEUS_DEV_NAME</font> to a friendlier label "
        "than your Windows username. Save and close.", body))
    flow.append(Paragraph(
        "You're done with this step when you see \"Setup complete.\"", body))

    # ── Section 4: Register the cron ────────────────────────────────
    flow.append(Paragraph("4. Register the 15-min chat-push", h1))
    flow.append(Paragraph(
        "In an <b>admin PowerShell</b> (Start → \"PowerShell\" → "
        "right-click → Run as administrator), from inside the repo:", body))
    flow.append(Paragraph(
        ".\\scripts\\register-chat-push-task.ps1", code))
    flow.append(Paragraph(
        "Creates a \"NAPCO Nucleus - Chat Push\" entry in Task "
        "Scheduler that runs every 15 min, even when you're not "
        "logged in. To verify: Task Scheduler → Task Scheduler "
        "Library → look for the entry.", body))
    flow.append(Paragraph(
        "To remove later:", body))
    flow.append(Paragraph(
        ".\\scripts\\register-chat-push-task.ps1 -Unregister", code))

    # ── Section 5: Start the voice daemon ───────────────────────────
    flow.append(Paragraph("5. Start the voice daemon", h1))
    flow.append(Paragraph(
        "Double-click <font face=\"Courier\">scripts\\start-daemon.bat</font>. "
        "Leave the terminal window running. To autostart on login, "
        "drop a shortcut to the .bat into <font face=\"Courier\">shell:startup</font> "
        "(Win+R → type that → drop the shortcut into the folder that opens).", body))

    # ── Section 6: Verify ───────────────────────────────────────────
    flow.append(Paragraph("6. Verify it's working", h1))
    flow.append(Paragraph(
        "Fire one push immediately:", body))
    flow.append(Paragraph(
        "Start-ScheduledTask -TaskName 'NAPCO Nucleus - Chat Push'", code))
    flow.append(Paragraph(
        "Then look at <font face=\"Courier\">\\\\MVPACCESS\\nucleus\\&lt;your name&gt;\\"
        "&lt;today's date&gt;\\chat\\</font> — you should see a "
        "<font face=\"Courier\">chat_&lt;HHMM&gt;-&lt;HHMM&gt;.docx</font> appear "
        "within ~30 seconds. If you don't, see Troubleshooting.", body))

    # ── Section 7: Day-to-day ───────────────────────────────────────
    flow.append(Paragraph("7. Day-to-day", h1))

    day_rows = [
        [Paragraph("What you want", th), Paragraph("What you do", th)],
        [Paragraph("Get your activity into the central pipeline", td),
         Paragraph("<b>Nothing</b> — the cron handles it every 15 min", td)],
        [Paragraph("Record a Teams call", td),
         Paragraph("Say <b>\"Assalamualaikum\"</b> / <b>\"Nucleus start\"</b> "
                   "when the call begins; <b>\"Allah Hafez\"</b> / "
                   "<b>\"Nucleus stop\"</b> when it ends. The daemon only "
                   "records during real Teams calls.", td)],
        [Paragraph("Include a file someone shared in Teams chat", td),
         Paragraph("Click <b>Download</b> on the chat attachment. Files in "
                   "your <font face=\"Courier\">~/Downloads</font> matching "
                   "the chat's filename + size get auto-pushed on the next "
                   "cron tick.", td)],
        [Paragraph("Pull updates after a <font face=\"Courier\">git pull</font> notice", td),
         Paragraph("Double-click <font face=\"Courier\">scripts\\update.bat</font>", td)],
        [Paragraph("Run an ad-hoc local pull (your own session, not the team's)", td),
         Paragraph("Double-click <font face=\"Courier\">scripts\\pull-now.bat</font>", td)],
    ]
    tbl = Table(day_rows, colWidths=[2.3 * inch, 4.4 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.5, GREY_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, GREY_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    flow.append(tbl)

    flow.append(Paragraph("7.1 Voice phrases", h2))
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_s), leftIndent=14, value="circle") for t in [
            "<b>Start recording:</b> \"Assalamualaikum\" / \"Salaam alaikum\" / \"Nucleus start\"",
            "<b>Stop recording:</b> \"Allah Hafez\" / \"Khoda Hafiz\" / \"Nucleus stop\"",
        ]],
        bulletType="bullet", leftIndent=10,
    ))
    flow.append(Paragraph(
        "Recording only fires when MS Teams has an active call. "
        "Saying the phrase with Teams idle does nothing — by design. "
        "To edit phrases, open <font face=\"Courier\">data\\teams\\voice_phrases.json</font> "
        "and restart the daemon.", body))

    flow.append(Paragraph("7.2 About chat attachments (important!)", h2))
    flow.append(_callout(
        "The system pushes Teams chat files <b>only if you've downloaded "
        "them locally</b>. If a teammate shares <font face=\"Courier\">requirements.pdf</font> "
        "in chat and you never click \"Download\" on it, the file's "
        "content won't reach the LLM — only its filename and a URL will. "
        "<b>If a file matters for a client requirement, click Download.</b>", body))

    # ── Section 8: Troubleshooting ──────────────────────────────────
    flow.append(Spacer(1, 0.1 * inch))
    flow.append(Paragraph("8. Troubleshooting", h1))
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_s), leftIndent=14, value="circle") for t in [
            "<b>\"Python not found\"</b> after running setup.bat: open a brand-new PowerShell and re-run setup. The PATH change from winget needs a fresh shell.",
            "<b>Scheduled task ran but no file on central:</b> check the SMB share is reachable (<font face=\"Courier\">Test-Path \\\\MVPACCESS\\nucleus</font>). If not, get an account on MVPACCESS from Titu.",
            "<b>Voice daemon prints \"no Teams session in Active state\"</b> when you say a phrase: that's the Teams-only gate working as designed. Pass <font face=\"Courier\">--allow-any-call</font> to disable: <font face=\"Courier\">python -m teams.voice_daemon --allow-any-call</font>.",
            "<b>Recording captured your voice but nothing else:</b> Teams → Settings → Devices → set Speaker = \"Same as system / Default\". Teams's separate Communications Device default makes the WASAPI loopback miss the other party.",
            "<b>\"pip install failed\"</b> in setup.bat: usually a corporate proxy issue. Run setup.bat again from inside your VPN.",
        ]],
        bulletType="bullet", leftIndent=10,
    ))
    flow.append(Paragraph(
        "For anything else, ping Titu.", body))

    return flow


def main():
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=LETTER,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=TITLE_BAR_H + 0.05 * inch,
        bottomMargin=0.7 * inch,
        title="NAPCO Nucleus — Team Onboarding Setup Guide",
        author="napco-labs",
    )
    frame_first = Frame(MARGIN, doc.bottomMargin,
                        PAGE_W - 2 * MARGIN,
                        PAGE_H - TITLE_BAR_H - doc.bottomMargin - 0.05 * inch,
                        id="first", showBoundary=0)
    frame_later = Frame(MARGIN, doc.bottomMargin,
                        PAGE_W - 2 * MARGIN,
                        PAGE_H - 0.7 * inch - doc.bottomMargin,
                        id="later", showBoundary=0)
    doc.addPageTemplates([
        PageTemplate(id="First", frames=[frame_first], onPage=first_page),
        PageTemplate(id="Later", frames=[frame_later], onPage=later_page),
    ])
    doc.build(build())
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
