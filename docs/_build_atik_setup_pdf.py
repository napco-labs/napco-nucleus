import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "NAPCO-Nucleus-Setup-Atik.pdf")

NAVY = colors.HexColor("#1F3A5F")
BLUE = colors.HexColor("#2E6DB4")
LIGHT = colors.HexColor("#EAF1F8")
GREY = colors.HexColor("#5B6470")
GREEN = colors.HexColor("#1E7A46")
CODEBG = colors.HexColor("#F4F6F9")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Title"], fontSize=19, textColor=NAVY,
                    spaceAfter=2, leading=23)
SUB = ParagraphStyle("SUB", parent=ss["Normal"], fontSize=10, textColor=GREY,
                     spaceAfter=10)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12.5, textColor=BLUE,
                    spaceBefore=11, spaceAfter=4)
BODY = ParagraphStyle("BODY", parent=ss["Normal"], fontSize=10.2, leading=15,
                      spaceAfter=5, textColor=colors.HexColor("#222222"))
CODE = ParagraphStyle("CODE", parent=ss["Code"], fontSize=9.3, leading=13,
                      textColor=colors.HexColor("#10233B"),
                      backColor=CODEBG, borderPadding=(6, 6, 6, 6),
                      spaceBefore=2, spaceAfter=7, leftIndent=2)
NOTE = ParagraphStyle("NOTE", parent=BODY, fontSize=9.6, textColor=GREY)
STEP = ParagraphStyle("STEP", parent=H2, fontSize=12.5, textColor=NAVY,
                      spaceBefore=12)


def code(txt):
    return Paragraph(txt.replace("\n", "<br/>"), CODE)


story = []
story.append(Paragraph("NAPCO Nucleus &mdash; Setup Guide for Atik", H1))
story.append(Paragraph("Record-and-push developer PC &bull; Project kept on the "
                       "C: drive &bull; ~15 minutes", SUB))
story.append(HRFlowable(width="100%", thickness=1.2, color=BLUE, spaceAfter=9))

story.append(Paragraph(
    "Your PC only <b>records</b> Teams calls and <b>uploads</b> them to the "
    "central server. Follow the steps in order. Titu will send you two files "
    "&mdash; <b>.env</b> and <b>google-credentials.json</b> &mdash; over direct "
    "message (never on group chat).", BODY))

# Step 1
story.append(Paragraph("Step 1 &mdash; Install Git, Python and ffmpeg", STEP))
story.append(Paragraph("Open <b>PowerShell</b> and run these three lines "
                       "(accept any prompts):", BODY))
story.append(code(
    "winget install --id Git.Git -e --source winget\n"
    "winget install --id Python.Python.3.12 -e --source winget\n"
    "winget install --id Gyan.FFmpeg -e --source winget"))
story.append(Paragraph("ffmpeg is important &mdash; it shrinks each recording "
                       "about 15&times; so your disk stays small. After this, "
                       "<b>close and reopen PowerShell</b> so the new tools are "
                       "found.", NOTE))

# Step 2
story.append(Paragraph("Step 2 &mdash; Download the project to your C: drive", STEP))
story.append(code(
    "git clone https://github.com/napco-labs/napco-nucleus.git C:\\napco-nucleus"))
story.append(Paragraph("The whole project now lives in "
                       "<b>C:\\napco-nucleus</b>.", BODY))

# Step 3
story.append(Paragraph("Step 3 &mdash; Add the two files from Titu", STEP))
story.append(Paragraph(
    "Copy the <b>.env</b> and <b>google-credentials.json</b> files Titu sent "
    "you into the folder <b>C:\\napco-nucleus</b> (paste them right beside the "
    "other files, not in a sub-folder).", BODY))

# Step 4
story.append(Paragraph("Step 4 &mdash; Run the one-click setup", STEP))
story.append(Paragraph("In File Explorer, open "
                       "<b>C:\\napco-nucleus\\scripts</b> and "
                       "<b>double-click <font face='Courier'>first-time-setup.bat"
                       "</font></b>.", BODY))
story.append(Paragraph("A black window opens and does everything automatically. "
                       "When it asks, type:", BODY))
info = [
    [Paragraph("<b>When it asks for&hellip;</b>", NOTE),
     Paragraph("<b>Type this</b>", NOTE)],
    [Paragraph("Your dev name", BODY), Paragraph("<b>Atik</b>", BODY)],
    [Paragraph("Napco share password", BODY),
     Paragraph("the password Titu gave you", BODY)],
]
ti = Table(info, colWidths=[70*mm, 96*mm])
ti.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#C4D2E2")),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("LEFTPADDING", (0, 0), (-1, -1), 7),
]))
story.append(ti)
story.append(Spacer(1, 4))
story.append(Paragraph("If it shows an error about tasks or permissions, "
                       "<b>right-click the .bat &rarr; Run as administrator</b> "
                       "and let it finish. When the window says setup finished "
                       "and the checks are green, you are done.", NOTE))

# Step 5
story.append(Paragraph("Step 5 &mdash; Test it", STEP))
story.append(Paragraph("Make any Teams call for at least 20 seconds, wait about "
                       "2 minutes, then run this in PowerShell:", BODY))
story.append(code(
    "explorer \\\\172.16.205.123\\nucleus-central\\Atik\\"))
story.append(Paragraph("Open today's date &rarr; <b>calls</b> folder. If you see "
                       "files ending in <b>_mic.wav</b>, <b>_speaker.wav</b> and "
                       "<b>.json</b>, it is working. Tell Titu you are done.", BODY))

# Troubleshooting
story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#C4D2E2"),
                        spaceBefore=8, spaceAfter=6))
story.append(Paragraph("If something does not work", H2))
tb = [
    [Paragraph("<b>Problem</b>", NOTE), Paragraph("<b>Fix</b>", NOTE)],
    [Paragraph("Nothing appears on the server", BODY),
     Paragraph("Run <font face='Courier'>ping 172.16.205.123</font>. If it "
               "fails you are not on the office network &mdash; connect to "
               "office LAN / VPN.", BODY)],
    [Paragraph("No microphone in the recording", BODY),
     Paragraph("Teams &rarr; Settings &rarr; Devices &rarr; set Microphone to "
               "your Windows default input.", BODY)],
    [Paragraph("&ldquo;scripts disabled on this system&rdquo;", BODY),
     Paragraph("Right-click <font face='Courier'>first-time-setup.bat</font> "
               "&rarr; Run as administrator.", BODY)],
]
tt = Table(tb, colWidths=[55*mm, 111*mm])
tt.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CODEBG]),
    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#C4D2E2")),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("LEFTPADDING", (0, 0), (-1, -1), 7),
]))
story.append(tt)

story.append(Spacer(1, 8))
bl = ParagraphStyle("BL", parent=BODY, textColor=GREEN,
                    fontName="Helvetica-Bold", fontSize=10)
story.append(Paragraph("Questions? Message Titu &mdash; khasan@ael-bd.com", bl))

doc = SimpleDocTemplate(OUT, pagesize=A4, topMargin=16*mm, bottomMargin=15*mm,
                        leftMargin=17*mm, rightMargin=17*mm,
                        title="NAPCO Nucleus - Setup for Atik")
doc.build(story)
print("[OK] wrote " + OUT)
