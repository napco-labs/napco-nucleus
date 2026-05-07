"""Build the Sandbox Setup Guide PDF (colleague-facing).

Per-channel setup walkthrough from a fresh clone to first successful pull.
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
                      "NAPCO Nucleus — Sandbox Setup")
    canvas.setFont("Helvetica", 12)
    canvas.setFillColor(colors.HexColor("#C8D4E6"))
    canvas.drawString(MARGIN, PAGE_H - TITLE_BAR_H + 0.25 * inch,
                      "From git clone to your first requirement draft, channel by channel")
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
                      "NAPCO Nucleus — Sandbox Setup Guide")
    canvas.drawRightString(PAGE_W - MARGIN, 0.35 * inch, f"Page {doc.page}")
    canvas.restoreState()


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
    tdcode = ParagraphStyle("TDC", fontName="Courier", fontSize=9,
                            textColor=BODY_TEXT, leading=12)
    bullet_s = ParagraphStyle("Bullet", parent=body, fontSize=10.5,
                              leading=14, leftIndent=16, bulletIndent=4,
                              spaceAfter=3)

    flow = []
    flow.append(Spacer(1, 0.3 * inch))

    # ── Section 1: Prerequisites ────────────────────────────────────
    flow.append(Paragraph("1. Prerequisites", h1))
    flow.append(Paragraph(
        "Before cloning, make sure your machine has:", body))
    items = [
        "<b>Windows 10 or 11.</b> Teams chat ingest reads the local IndexedDB cache, which is Windows-only.",
        "<b>Python 3.11 or newer.</b> Confirm with <font face=\"Courier\">python --version</font>.",
        "<b>Git for Windows.</b>",
        "<b>Microsoft Teams desktop</b>, signed in to your work account, with the chats you'll be pulling already open.",
        "<b>Microsoft Outlook</b> (or another IMAP-aware mail client) configured for the same Gmail account you'll authenticate below. Drafts will appear here for manual send.",
        "<b>A Gmail account</b> — used as the IMAP poller and the From identity on outgoing drafts.",
        "<b>~5 GB free disk space</b> for the Whisper model + workspace.",
    ]
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_s), leftIndent=14, value="circle") for t in items],
        bulletType="bullet", leftIndent=10,
    ))

    # ── Section 2: Clone + install ──────────────────────────────────
    flow.append(Paragraph("2. Clone the repo and install dependencies", h1))
    flow.append(Paragraph(
        "Open PowerShell or Git Bash and run:", body))
    flow.append(Paragraph(
        "git clone https://github.com/napco-labs/napco-nucleus.git<br/>"
        "cd napco-nucleus<br/>"
        "python -m venv .venv<br/>"
        ".venv\\Scripts\\activate<br/>"
        "pip install -r requirements.txt", code))
    flow.append(Paragraph(
        "3 to 5 minutes. The heaviest deps are faster-whisper and onnxruntime "
        "(used for audio transcription); everything else is small.", body))
    flow.append(Paragraph(
        "Create your .env file in the project root. Start empty — the sections "
        "below tell you which variables to add as you set up each channel:", body))
    flow.append(Paragraph(
        "type nul > .env  &nbsp;&nbsp;(PowerShell)<br/>"
        "touch .env       &nbsp;&nbsp;(Git Bash)", code))

    # ── Section 3: Channel 1 — Email ────────────────────────────────
    flow.append(Paragraph("3. Channel 1 — Email", h1))
    flow.append(Paragraph(
        "Used for both pulling email content and pushing email drafts "
        "into your Drafts folder. Authentication is via Gmail App "
        "Password — your normal Google password will not work, because "
        "Google blocks IMAP login with a regular password when 2FA is on.", body))

    flow.append(Paragraph("3.1 Generate a Gmail App Password", h2))
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_s), leftIndent=22) for t in [
            "Open <font face=\"Courier\">https://myaccount.google.com/security</font>.",
            "Confirm 2-Step Verification is ON. (If not, turn it on first — App Passwords are gated on 2SV.)",
            "Click <b>App passwords</b>. (Search if you don't see it.)",
            "Pick <b>Mail</b> as the app, give it a label like \"NAPCO Nucleus\", click <b>Create</b>.",
            "Copy the 16-character password Google shows you. You won't see it again.",
        ]],
        bulletType="1", leftIndent=14,
    ))

    flow.append(Paragraph("3.2 Add to .env", h2))
    flow.append(Paragraph(
        "REQ_IMAP_HOST=imap.gmail.com<br/>"
        "REQ_IMAP_PORT=993<br/>"
        "REQ_IMAP_USER=your.address@gmail.com<br/>"
        "REQ_IMAP_PASSWORD=&lt;the 16-char app password, no spaces&gt;<br/>"
        "SMTP_FROM=your.address@gmail.com<br/>"
        "SMTP_FROM_NAME=Your Name<br/>"
        "VERIFICATION_TO=client@example.com", code))
    flow.append(Paragraph(
        "<b>Smoke test.</b> Make sure IMAP login works:", body))
    flow.append(Paragraph(
        "python -m mail.pull_email --last-minutes 5", code))
    flow.append(Paragraph(
        "Should print \"Pulling emails from mailbox...\" and either match "
        "0 or N emails. \"IMAP login failed\" means the App Password is "
        "wrong; regenerate.", body))

    # ── Section 4: Channel 2 — Google Drive ─────────────────────────
    flow.append(Paragraph("4. Channel 2 — Google Drive", h1))
    flow.append(Paragraph(
        "The Drive ingester reads files from one specified folder using "
        "a Google service account. The service account needs read access "
        "to that folder; you grant it by sharing the folder with the "
        "service account's email.", body))

    flow.append(Paragraph("4.1 Create a service account + JSON key", h2))
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_s), leftIndent=22) for t in [
            "Open <font face=\"Courier\">https://console.cloud.google.com/</font>.",
            "Select or create a project (any project — this is a free identity).",
            "Navigate <b>IAM &amp; Admin</b> → <b>Service Accounts</b> → <b>Create Service Account</b>. Give it a name like \"napco-nucleus-drive\".",
            "Skip the role-grant step (no project-level role needed).",
            "On the new account's <b>Keys</b> tab, click <b>Add Key</b> → <b>Create new key</b> → <b>JSON</b>. A JSON file downloads.",
            "Note the <font face=\"Courier\">client_email</font> field inside the JSON (looks like <font face=\"Courier\">name@project.iam.gserviceaccount.com</font>).",
            "Save the JSON somewhere outside the repo — for example "
            "<font face=\"Courier\">C:\\Users\\&lt;you&gt;\\google-credentials.json</font>.",
        ]],
        bulletType="1", leftIndent=14,
    ))

    flow.append(Paragraph("4.2 Enable the Drive API on the project", h2))
    flow.append(Paragraph(
        "Cloud Console → <b>APIs &amp; Services</b> → <b>Enable APIs and "
        "Services</b> → search \"Google Drive API\" → <b>Enable</b>. "
        "Same-project as the service account.", body))

    flow.append(Paragraph("4.3 Share your Drive folder with the service account", h2))
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_s), leftIndent=22) for t in [
            "Create or pick a folder in Google Drive that will hold your incoming files.",
            "Right-click → Share. Paste the service account's <font face=\"Courier\">client_email</font>. Permission: <b>Viewer</b> is enough; <b>Editor</b> is fine if you ever want write access.",
            "Open the folder; copy the ID from the URL: "
            "<font face=\"Courier\">drive.google.com/drive/folders/&lt;THIS_PART&gt;</font>.",
        ]],
        bulletType="1", leftIndent=14,
    ))

    flow.append(Paragraph("4.4 Add to .env", h2))
    flow.append(Paragraph(
        "GOOGLE_CREDENTIALS_PATH=C:\\Users\\&lt;you&gt;\\google-credentials.json<br/>"
        "GDRIVE_AUDIO_FOLDER_ID=&lt;the folder ID&gt;<br/>"
        "# Required only if you'll have audio in the folder:<br/>"
        "GROQ_API_KEY=&lt;groq key from console.groq.com&gt;", code))
    flow.append(Paragraph(
        "<b>Smoke test.</b> List one file from the folder:", body))
    flow.append(Paragraph(
        "python -m drive.pull_drive --last-files 1", code))
    flow.append(Paragraph(
        "If the folder is empty, prints \"Matched 0 of 0\". "
        "If the service account isn't shared, you'll get a 404 from Google.", body))

    # ── Section 5: Channel 3 — Teams chat ───────────────────────────
    flow.append(Paragraph("5. Channel 3 — Teams chat", h1))
    flow.append(Paragraph(
        "No API or token. The reader walks the local IndexedDB that "
        "Teams desktop populates when it's signed in. So the only setup "
        "is having the right chats already loaded in your Teams desktop "
        "and adding name aliases for any chat with a blank title.", body))

    flow.append(Paragraph("5.1 Pre-flight", h2))
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_s), leftIndent=22) for t in [
            "Open the Teams desktop app and sign in.",
            "Navigate into each chat or group you intend to pull from at least once. Teams only fully syncs a chat's messages to the local cache after it has been opened.",
            "Optional: leave Teams running. The reader works fine while Teams is open (no file lock).",
        ]],
        bulletType="bullet", leftIndent=14,
    ))

    flow.append(Paragraph("5.2 First-time chat discovery", h2))
    flow.append(Paragraph(
        "From the project root:", body))
    flow.append(Paragraph(
        "python -m teams.list_chats", code))
    flow.append(Paragraph(
        "Walks the IndexedDB and writes <font face=\"Courier\">"
        "data/teams/chats.txt</font> listing every chat with its registry "
        "number, conversation_id, and participants. Note the chat numbers "
        "of the groups you'll pull from.", body))

    flow.append(Paragraph("5.3 CHAT_ALIASES — add names you can type", h2))
    flow.append(Paragraph(
        "Many group chats — especially older legacy threads — have empty "
        "titles in the cache. To call them by name, add aliases to .env. "
        "Format is comma-separated <font face=\"Courier\">alias=identifier</font> "
        "where identifier is a chat number or a full conversation_id.", body))
    flow.append(Paragraph(
        "Example for a group called Acme (chat #45) with three members:", body))
    flow.append(Paragraph(
        "CHAT_ALIASES=Acme=45,Alice=45,Bob=45,Charlie=45", code))
    flow.append(Paragraph(
        "Each member name resolves to the same group chat. You can also "
        "narrow to one person's messages with "
        "<font face=\"Courier\">--sender Alice</font> when pulling.", body))

    flow.append(Paragraph("5.4 Smoke test", h2))
    flow.append(Paragraph(
        "python -m teams.pull_chat --name Acme --last-minutes 60", code))
    flow.append(Paragraph(
        "Should resolve the alias and print \"Messages in window: N\". "
        "If you get \"No chat matching ...\", either the alias is missing "
        "from .env or the chat hasn't been opened in Teams desktop yet.", body))

    # ── Section 6: Channel 4 — Teams audio call ─────────────────────
    flow.append(Paragraph("6. Channel 4 — Teams audio call", h1))
    flow.append(Paragraph(
        "Records two WAV tracks — your microphone and the system speaker "
        "loopback — so the transcript distinguishes \"You\" from \"Other\". "
        "Transcription runs locally with faster-whisper large-v3 (Bangla "
        "→ English). No cloud API needed.", body))

    flow.append(Paragraph("6.1 Pre-flight", h2))
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_s), leftIndent=22) for t in [
            "Confirm your default microphone works (any voice app you normally use).",
            "Confirm your default speakers / headset are configured. The recorder uses Windows WASAPI loopback to capture whatever is playing — so the call audio must come through the same speakers.",
            "No driver install needed: PyAudioWPatch ships its own native binary.",
        ]],
        bulletType="bullet", leftIndent=14,
    ))

    flow.append(Paragraph("6.2 One-time Whisper download (~3 GB)", h2))
    flow.append(Paragraph(
        "First run downloads the model to "
        "<font face=\"Courier\">C:\\Users\\&lt;you&gt;\\.cache\\huggingface\\hub</font>. "
        "Pre-cache it so your first real meeting doesn't wait for the download:", body))
    flow.append(Paragraph(
        "python -c \"from faster_whisper import WhisperModel; "
        "WhisperModel('large-v3', device='cpu', compute_type='int8')\"", code))
    flow.append(Paragraph(
        "Subsequent loads are 3-5 seconds.", body))

    flow.append(Paragraph("6.3 Smoke test (record + transcribe a 10-second clip)", h2))
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_s), leftIndent=22) for t in [
            "Run <font face=\"Courier\">python -m teams.record_call</font> in one terminal.",
            "Talk for ~10 seconds. Play any audio through your speakers if you also want a 'speaker' track.",
            "In a second terminal: <font face=\"Courier\">python -m teams.stop_recording</font>. The recorder closes the WAVs and exits.",
            "Transcribe and append: <font face=\"Courier\">python pull_meeting.py</font>. Confirms speaker labels (You / Other) in the output.",
        ]],
        bulletType="1", leftIndent=14,
    ))

    # ── Section 7: First end-to-end run ─────────────────────────────
    flow.append(Paragraph("7. First end-to-end run", h1))
    flow.append(Paragraph(
        "With all channels set up, do one full pass to see the whole "
        "pipeline producing a real client email draft:", body))
    flow.append(ListFlowable(
        [ListItem(Paragraph(t, bullet_s), leftIndent=22) for t in [
            "Have a 1-minute Teams call with someone, talk through one or two requirements.",
            "Send yourself a test email with a simple requirement-flavored ask.",
            "Drop a small PDF or .txt file with another requirement into the Drive folder.",
            "Stop the recording (<font face=\"Courier\">python -m teams.stop_recording</font>).",
            "Pull each channel: <br/>"
            "<font face=\"Courier\">python -m teams.pull_chat --name &lt;group&gt; --last-minutes 30</font><br/>"
            "<font face=\"Courier\">python -m mail.pull_email --last-minutes 30</font><br/>"
            "<font face=\"Courier\">python -m drive.pull_drive --last-files 1</font><br/>"
            "<font face=\"Courier\">python pull_meeting.py</font>",
            "Identify and draft: <font face=\"Courier\">python agent.py --task verify_session</font>.",
            "Open Outlook → Drafts. The verification email + attached Word doc should be there. Send it (or don't — it's still your call).",
        ]],
        bulletType="1", leftIndent=14,
    ))

    # ── Section 8: You're set ───────────────────────────────────────
    flow.append(Paragraph("8. You're set up", h1))
    flow.append(Paragraph(
        "Open the User Manual for day-to-day reference: per-channel command "
        "options, time-window flags, sender filters, and troubleshooting. "
        "When you upgrade the project, run "
        "<font face=\"Courier\">git pull</font> and then "
        "<font face=\"Courier\">pip install -r requirements.txt</font> to "
        "pick up any new dependencies.", body))

    return flow


def main():
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=LETTER,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=TITLE_BAR_H + 0.05 * inch,
        bottomMargin=0.7 * inch,
        title="NAPCO Nucleus — Sandbox Setup Guide",
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
