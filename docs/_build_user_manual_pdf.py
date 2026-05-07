"""Build the User Manual PDF (colleague-facing).

Day-to-day commands for the on-demand requirement-management workflow.
Produces:
    docs/User_Manual.pdf

Run:  python docs/_build_user_manual_pdf.py
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
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

HERE = Path(__file__).parent
OUT = HERE / "User_Manual.pdf"

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
                      "NAPCO Nucleus — User Manual")
    canvas.setFont("Helvetica", 12)
    canvas.setFillColor(colors.HexColor("#C8D4E6"))
    canvas.drawString(MARGIN, PAGE_H - TITLE_BAR_H + 0.25 * inch,
                      "Requirement Management — On-demand pull-session workflow")
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
                      "NAPCO Nucleus — User Manual")
    canvas.drawRightString(PAGE_W - MARGIN, 0.35 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build():
    body = ParagraphStyle("Body", fontName="Helvetica", fontSize=10.5,
                          leading=14.5, textColor=BODY_TEXT, spaceAfter=8)
    h1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=14,
                        leading=18, textColor=NAVY, spaceBefore=12,
                        spaceAfter=6)
    h2 = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=11.5,
                        leading=15, textColor=NAVY, spaceBefore=8,
                        spaceAfter=4)
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

    # 1. How it works
    flow.append(Paragraph("1. How it works", h1))
    flow.append(Paragraph(
        "Four input channels — Microsoft Teams chats, Microsoft Teams "
        "audio calls, email, and Google Drive — feed into one consolidated "
        "Word document called the <i>pull session</i>. You pull from each "
        "channel by command, in any order, in any combination. When the "
        "session has the material you want, one final command identifies "
        "the requirements, writes a verification Word doc, and drafts a "
        "single email to the client. The draft lands in your Outlook "
        "Drafts folder for manual review and send.", body))
    flow.append(Paragraph(
        "<b>The system never sends mail on its own.</b> Every email "
        "leaves your mailbox manually, with your explicit click of Send.", body))

    # 2. Start a session
    flow.append(Paragraph("2. Start a pull session (optional)", h1))
    flow.append(Paragraph(
        "The session doc is created automatically the first time you "
        "pull. If you want a fresh session — for example, you finished "
        "yesterday's batch and want today's pulls in their own doc — "
        "reset explicitly:", body))
    flow.append(Paragraph(
        "python -c \"from tools._session_doc import reset; "
        "print(reset(label='today'))\"", code))
    flow.append(Paragraph(
        "The previous session doc is archived under "
        "data/requirements/sessions/archive/ with its label and timestamp. "
        "The fresh one starts at data/requirements/sessions/current.docx.", body))

    # 3. Pull from each channel
    flow.append(Paragraph("3. Pull from each channel", h1))

    # 3.1 Email
    flow.append(Paragraph("3.1 Email", h2))
    flow.append(Paragraph(
        "Pulls IMAP messages by sender, subject, and/or time window. "
        "Attached PDFs, .docx, and .txt files are extracted and appended "
        "to the email body so the LLM reads them inline.", body))
    flow.append(Paragraph(
        "python -m mail.pull_email [--from-sender ADDR]<br/>"
        "                          [--subject TEXT]<br/>"
        "                          [--last-minutes N]<br/>"
        "                          [--from-time HH:MM --to-time HH:MM]<br/>"
        "                          [--date YYYY-MM-DD]", code))

    email_examples = [
        [Paragraph("<b>Goal</b>", th), Paragraph("<b>Command</b>", th)],
        [Paragraph("All emails in last 15 minutes", td),
         Paragraph("--last-minutes 15", td)],
        [Paragraph("From a specific sender, last hour", td),
         Paragraph('--from-sender "client@example.com" --last-minutes 60', td)],
        [Paragraph("Specific subject, last 30 min", td),
         Paragraph('--subject "budget" --last-minutes 30', td)],
        [Paragraph("Manual time window today", td),
         Paragraph('--from-time "3 PM" --to-time "5 PM"', td)],
        [Paragraph("All filters combined", td),
         Paragraph('--from-sender "alice@ex.com" --subject "Q3" --last-minutes 60', td)],
    ]
    t = Table(email_examples, colWidths=[2.5 * inch, 4.5 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, GREY_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(t)

    # 3.2 Teams chat
    flow.append(Paragraph("3.2 Teams chat", h2))
    flow.append(Paragraph(
        "Reads messages from the local Teams desktop cache. Pick the "
        "chat by name (with CHAT_ALIASES), number, or full conversation_id. "
        "Optionally narrow to one sender's messages within that chat.", body))
    flow.append(Paragraph(
        "python -m teams.pull_chat (--name NAME | --number N | --id ID)<br/>"
        "                          [--sender NAME]<br/>"
        "                          [--last-minutes N]<br/>"
        "                          [--from-time HH:MM --to-time HH:MM]<br/>"
        "                          [--date YYYY-MM-DD]", code))

    chat_examples = [
        [Paragraph("<b>Goal</b>", th), Paragraph("<b>Command</b>", th)],
        [Paragraph("Last 15 min from a group", td),
         Paragraph('--name "ContiHosting" --last-minutes 15', td)],
        [Paragraph("Just one person's messages", td),
         Paragraph('--name "ContiHosting" --sender "Salman" --last-minutes 30', td)],
        [Paragraph("Manual window", td),
         Paragraph('--name "ContiHosting" --from-time "3 PM" --to-time "5 PM"', td)],
        [Paragraph("By chat number (when no alias)", td),
         Paragraph('--number 45 --last-minutes 30', td)],
    ]
    t = Table(chat_examples, colWidths=[2.5 * inch, 4.5 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, GREY_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(t)

    # 3.3 Drive
    flow.append(Paragraph("3.3 Google Drive", h2))
    flow.append(Paragraph(
        "Pulls and extracts content from files in your configured Drive "
        "folder. Handles PDF, plain text, .docx (modern Word), .doc "
        "(legacy Word, best-effort), and audio/video (transcribed via "
        "Groq Whisper).", body))
    flow.append(Paragraph(
        "python -m drive.pull_drive [--filename TEXT]<br/>"
        "                           [--last-files N]<br/>"
        "                           [--last-minutes N]<br/>"
        "                           [--from-time HH:MM --to-time HH:MM]<br/>"
        "                           [--date YYYY-MM-DD]", code))

    drive_examples = [
        [Paragraph("<b>Goal</b>", th), Paragraph("<b>Command</b>", th)],
        [Paragraph("Most recent file", td),
         Paragraph("--last-files 1", td)],
        [Paragraph("Most recent 3 files", td),
         Paragraph("--last-files 3", td)],
        [Paragraph("Files added in last 10 min", td),
         Paragraph("--last-minutes 10", td)],
        [Paragraph("By filename substring", td),
         Paragraph('--filename "budget"', td)],
        [Paragraph("Manual window", td),
         Paragraph('--from-time "3 PM" --to-time "9 PM"', td)],
    ]
    t = Table(drive_examples, colWidths=[2.5 * inch, 4.5 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, GREY_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(t)

    # 3.4 Audio call
    flow.append(Paragraph("3.4 Teams audio call", h2))
    flow.append(Paragraph(
        "Records both the system loopback (the other party's voice) "
        "and your microphone as separate WAV tracks, so the transcript "
        "preserves speaker attribution. Three steps:", body))
    flow.append(ListFlowable(
        [ListItem(Paragraph(
            "<b>Start recording.</b> "
            "<font face=\"Courier\">python -m teams.record_call</font> "
            "(leave it running in a terminal)", bullet_s), leftIndent=22),
         ListItem(Paragraph(
            "<b>Have the call.</b> The recorder captures everything until "
            "you stop it.", bullet_s), leftIndent=22),
         ListItem(Paragraph(
            "<b>Stop cleanly.</b> Either Ctrl+C in the recorder terminal, "
            "or run <font face=\"Courier\">python -m teams.stop_recording</font> "
            "from a different terminal.", bullet_s), leftIndent=22),
         ListItem(Paragraph(
            "<b>Transcribe and append.</b> "
            "<font face=\"Courier\">python pull_meeting.py</font>. "
            "Bangla and English are auto-detected; output is in English.",
            bullet_s), leftIndent=22)],
        bulletType="1", leftIndent=14,
    ))

    # 4. Inspecting / managing the session
    flow.append(Paragraph("4. Inspect or manage the session", h1))
    flow.append(Paragraph(
        "Open the live session doc directly:", body))
    flow.append(Paragraph(
        "data/requirements/sessions/current.docx", code))
    flow.append(Paragraph(
        "List the section titles already in it:", body))
    flow.append(Paragraph(
        "python -c \"from tools._session_doc import status; "
        "print(status())\"", code))

    # 5. Identify and draft
    flow.append(Paragraph("5. Identify requirements and draft the email", h1))
    flow.append(Paragraph("One command does everything from this point:", body))
    flow.append(Paragraph("python agent.py --task verify_session", code))
    flow.append(Paragraph(
        "Reads the session doc, identifies distinct client requirements, "
        "writes <i>Requirements Verification YYYY-MM-DD.docx</i>, drafts "
        "one email to the client (verification doc attached), and pushes "
        "the draft into your IMAP Drafts folder.", body))

    # 6. Review and send
    flow.append(Paragraph("6. Review and send", h1))
    flow.append(ListFlowable(
        [ListItem(Paragraph(
            "Open Outlook (or any IMAP-aware mail client).", bullet_s),
            leftIndent=22),
         ListItem(Paragraph(
            "Go to your Drafts folder.", bullet_s), leftIndent=22),
         ListItem(Paragraph(
            "Find the draft (subject \"Requirements Verification - "
            "YYYY-MM-DD\").", bullet_s), leftIndent=22),
         ListItem(Paragraph(
            "Read the attached Word doc, review the email body, edit "
            "anything you'd like to phrase differently.", bullet_s),
            leftIndent=22),
         ListItem(Paragraph(
            "Click Send.", bullet_s), leftIndent=22)],
        bulletType="1", leftIndent=14,
    ))

    # 7. Troubleshooting
    flow.append(Paragraph("7. Troubleshooting", h1))
    trouble = [
        [Paragraph("<b>Symptom</b>", th), Paragraph("<b>Likely cause</b>", th),
         Paragraph("<b>Fix</b>", th)],
        [Paragraph("\"No chat matching X\"", td),
         Paragraph("Empty title in IndexedDB", td),
         Paragraph("Add <font face=\"Courier\">X=NUMBER</font> to "
                   "CHAT_ALIASES in .env", td)],
        [Paragraph("0 chat messages but you sent one", td),
         Paragraph("Teams cache hasn't flushed yet", td),
         Paragraph("Wait ~5 sec, retry", td)],
        [Paragraph("IMAP login failed", td),
         Paragraph("Gmail App Password wrong/expired", td),
         Paragraph("Regenerate in Google Account &rarr; Security", td)],
        [Paragraph("\"GDRIVE_AUDIO_FOLDER_ID not set\"", td),
         Paragraph(".env missing the variable", td),
         Paragraph("Add it to .env and ensure the service account has "
                   "access to the folder", td)],
        [Paragraph("ModuleNotFoundError: faster_whisper", td),
         Paragraph("Dependencies not installed", td),
         Paragraph("<font face=\"Courier\">pip install -r requirements.txt</font>", td)],
        [Paragraph("Draft missing from Outlook Drafts", td),
         Paragraph("IMAP push failed (look at imap_error in tool output)", td),
         Paragraph("Open the .eml at "
                   "<font face=\"Courier\">data/requirements/drafts/&lt;date&gt;/</font> "
                   "directly", td)],
        [Paragraph("\"No *_mic.wav recordings\"", td),
         Paragraph("Recorder didn't capture or didn't stop cleanly", td),
         Paragraph("Re-run <font face=\"Courier\">python -m "
                   "teams.record_call</font>; verify it prints "
                   "Recording -&gt; ...", td)],
    ]
    t = Table(trouble, colWidths=[1.9 * inch, 1.9 * inch, 3.2 * inch],
              repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, GREY_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(t)

    return flow


def main():
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=LETTER,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=TITLE_BAR_H + 0.05 * inch,
        bottomMargin=0.7 * inch,
        title="NAPCO Nucleus — User Manual",
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
