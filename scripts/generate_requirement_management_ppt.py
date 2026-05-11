"""NAPCO Nucleus — Requirement Management deck (team-facing).

12 slides, 16:9. Tells the team how client requirements get captured,
identified, and turned into a verification email. Minimal text per
slide so Titu drives the narration; speaker notes carry the talking
points.

Run:
    python scripts\\generate_requirement_management_ppt.py
Output:
    docs\\NAPCO-Nucleus-Requirement-Management.pptx
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "docs" / "NAPCO-Nucleus-Requirement-Management.pptx"

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)

# Palette — matches the Central-Architecture deck
NAVY   = RGBColor(0x1F, 0x4E, 0x79)
TEAL   = RGBColor(0x2E, 0x8A, 0x8A)
CORAL  = RGBColor(0xE0, 0x78, 0x56)
GREEN  = RGBColor(0x4A, 0x7A, 0x4A)
GOLD   = RGBColor(0xC9, 0x96, 0x2B)
PURPLE = RGBColor(0x6A, 0x4C, 0x93)
INK    = RGBColor(0x22, 0x22, 0x22)
MUTED  = RGBColor(0x6B, 0x77, 0x85)
SOFT   = RGBColor(0xF5, 0xF7, 0xFA)
RULE   = RGBColor(0xD5, 0xDC, 0xE5)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)


# ── helpers ────────────────────────────────────────────────────────

def solid(shape, color):
    shape.fill.solid()
    shape.fill.fore_color.rgb = color


def no_fill(shape):
    shape.fill.background()


def no_line(shape):
    shape.line.fill.background()


def line(shape, color, width_pt=0.75):
    shape.line.color.rgb = color
    shape.line.width = Pt(width_pt)


def set_text(tf, text, size=24, bold=False, color=INK,
             align=PP_ALIGN.LEFT, font="Calibri"):
    tf.clear()
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = text
    r.font.name = font
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color


def add_para(tf, text, size=18, bold=False, color=INK,
             align=PP_ALIGN.LEFT, space_before=0, font="Calibri"):
    p = tf.add_paragraph()
    p.alignment = align
    if space_before:
        p.space_before = Pt(space_before)
    r = p.add_run()
    r.text = text
    r.font.name = font
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color


def add_textbox(slide, x, y, w, h, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0)
    tf.margin_right = Inches(0)
    tf.margin_top = Inches(0)
    tf.margin_bottom = Inches(0)
    tf.vertical_anchor = anchor
    return tf


def add_rect(slide, x, y, w, h, fill_color=None, line_color=None,
             line_width=0.75, rounded=False):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE
    rect = slide.shapes.add_shape(shape_type, x, y, w, h)
    if fill_color is None:
        no_fill(rect)
    else:
        solid(rect, fill_color)
    if line_color is None:
        no_line(rect)
    else:
        line(rect, line_color, line_width)
    rect.text_frame.margin_left = Inches(0.1)
    rect.text_frame.margin_right = Inches(0.1)
    rect.text_frame.margin_top = Inches(0.05)
    rect.text_frame.margin_bottom = Inches(0.05)
    return rect


def add_arrow(slide, x1, y1, x2, y2, color=NAVY, width_pt=2.0):
    conn = slide.shapes.add_connector(2, x1, y1, x2, y2)
    conn.line.color.rgb = color
    conn.line.width = Pt(width_pt)
    return conn


def base_slide(prs, title_text, subtitle_text=None):
    blank = prs.slide_layouts[6]
    s = prs.slides.add_slide(blank)
    add_rect(s, Inches(0), Inches(0), SLIDE_W, Inches(0.18), fill_color=NAVY)
    tf = add_textbox(s, Inches(0.6), Inches(0.35), Inches(12), Inches(0.7))
    set_text(tf, title_text, size=28, bold=True, color=NAVY)
    if subtitle_text:
        add_para(tf, subtitle_text, size=14, color=MUTED, space_before=2)
    add_rect(s, Inches(0.6), Inches(7.05), Inches(12.1), Inches(0.02),
             fill_color=RULE)
    return s


def set_speaker_notes(slide, text):
    notes = slide.notes_slide.notes_text_frame
    notes.clear()
    p = notes.paragraphs[0]
    p.text = text


def add_chip(slide, x, y, w, h, text, color):
    rect = add_rect(slide, x, y, w, h, fill_color=color, rounded=True)
    tf = rect.text_frame
    set_text(tf, text, size=11, bold=True, color=WHITE,
             align=PP_ALIGN.CENTER)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    return rect


def add_box(slide, x, y, w, h, title, lines, accent=NAVY):
    container = add_rect(slide, x, y, w, h, fill_color=WHITE, line_color=RULE)
    add_rect(slide, x, y, Inches(0.08), h, fill_color=accent)
    tf = add_textbox(slide, x + Inches(0.18), y + Inches(0.12),
                     w - Inches(0.28), h - Inches(0.24))
    set_text(tf, title, size=14, bold=True, color=accent)
    for ln in lines:
        add_para(tf, ln, size=11, color=INK, space_before=2)
    return container


# ── slides ─────────────────────────────────────────────────────────

def slide_title(prs):
    s = prs.slide_layouts[6]
    s = prs.slides.add_slide(s)
    add_rect(s, Inches(0), Inches(0), SLIDE_W, SLIDE_H, fill_color=NAVY)
    tf = add_textbox(s, Inches(0.8), Inches(2.4), Inches(11.7), Inches(1.5))
    set_text(tf, "NAPCO Nucleus", size=58, bold=True, color=WHITE)
    add_para(tf, "Requirement Management Workflow",
             size=28, color=WHITE)
    tf2 = add_textbox(s, Inches(0.8), Inches(4.4), Inches(11.7), Inches(1.5))
    set_text(tf2, "Client conversations -> one verification email, "
                  "end-to-end.",
             size=18, color=RGBColor(0xC8, 0xD2, 0xE0))
    tf3 = add_textbox(s, Inches(0.8), Inches(6.8), Inches(11.7), Inches(0.4))
    set_text(tf3, "Mohammad Kamrul Hasan (Titu)   |   "
                  "Adaptive Enterprise / NAPCO labs",
             size=12, color=RGBColor(0x9C, 0xAB, 0xBE))
    set_speaker_notes(s, (
        "Open with the framing: requirements come at us from multiple "
        "channels and multiple people. Today's deck shows how NAPCO "
        "Nucleus stitches all of that back together into one verification "
        "email that I review and send to the client myself. The team's "
        "involvement is small but important -- I'll explain exactly what "
        "I need from each of you."
    ))


def slide_problem(prs):
    s = base_slide(prs, "The problem",
                   "A single client requirement is rarely in one place.")
    add_chip(s, Inches(0.8), Inches(1.6), Inches(2.4), Inches(0.6),
             "Client", CORAL)
    add_chip(s, Inches(0.8), Inches(2.55), Inches(2.4), Inches(0.6),
             "Dev 1", NAVY)
    add_chip(s, Inches(0.8), Inches(3.30), Inches(2.4), Inches(0.6),
             "Dev 2", NAVY)
    add_chip(s, Inches(0.8), Inches(4.05), Inches(2.4), Inches(0.6),
             "Dev 3", NAVY)

    channels = [
        ("Teams chat",  CORAL,  "\"Make the login flow log failed attempts\""),
        ("Teams call",  TEAL,   "\"...and also keep audit timestamps in UTC\""),
        ("Email",       GOLD,   "PDF attached: \"Requirement spec v2\""),
        ("Drive",       PURPLE, "Spreadsheet of edge cases dropped in folder"),
    ]
    for i, (name, color, quote) in enumerate(channels):
        y = Inches(1.6 + i * 1.20)
        add_chip(s, Inches(4.2), y, Inches(2.0), Inches(0.6), name, color)
        tf = add_textbox(s, Inches(6.5), y, Inches(6.4), Inches(0.6),
                         anchor=MSO_ANCHOR.MIDDLE)
        set_text(tf, quote, size=12, color=INK)

    add_rect(s, Inches(0.6), Inches(6.4), Inches(12.1), Inches(0.5),
             fill_color=SOFT, line_color=RULE)
    tf = add_textbox(s, Inches(0.8), Inches(6.45), Inches(11.7), Inches(0.4),
                     anchor=MSO_ANCHOR.MIDDLE)
    set_text(tf, "Nobody has all the pieces. Stitching them by hand is "
                 "slow and error-prone.",
             size=12, color=MUTED)

    set_speaker_notes(s, (
        "Today, a single requirement might mention something in a Teams "
        "chat with Dev 2, get clarified in a call with Dev 1, and arrive "
        "fully formed as a PDF in my inbox. By the time I notice all "
        "three exist I've already lost a day. The cost isn't just time "
        "-- it's that pieces get dropped silently."
    ))


def slide_solution(prs):
    s = base_slide(prs, "The solution",
                   "One pipeline, four channels in, one verification email out.")
    boxes = [
        ("CAPTURE",   "Every dev machine + agent host pulls "
                      "chat, calls, email, and Drive into one document.",
                      NAVY),
        ("IDENTIFY",  "Claude reads the document and extracts a "
                      "deduped, structured requirement list.",
                      TEAL),
        ("VERIFY",    "Titu reviews the list, edits if needed, "
                      "and clicks Send when satisfied.",
                      GREEN),
        ("DELIVER",   "Client receives an email asking them to "
                      "confirm. Nothing leaves Gmail without Titu.",
                      CORAL),
    ]
    box_w = Inches(2.85)
    box_h = Inches(3.6)
    gap = Inches(0.25)
    start_x = Inches(0.7)
    y = Inches(1.7)
    for i, (title, body, color) in enumerate(boxes):
        x = start_x + (box_w + gap) * i
        add_box(s, x, y, box_w, box_h, title, [body], accent=color)
        if i < len(boxes) - 1:
            ax1 = x + box_w + Inches(0.02)
            ax2 = ax1 + gap - Inches(0.04)
            add_arrow(s, ax1, y + box_h / 2, ax2, y + box_h / 2,
                      color=MUTED, width_pt=2.2)

    tf = add_textbox(s, Inches(0.7), Inches(5.7), Inches(12.0), Inches(0.8),
                     anchor=MSO_ANCHOR.MIDDLE)
    set_text(tf, "Human-in-the-loop at the Verify step. Nothing is auto-sent.",
             size=14, bold=True, color=NAVY, align=PP_ALIGN.CENTER)

    set_speaker_notes(s, (
        "Four stages. Capture is the only one running in the background. "
        "Identify is one LLM call, on my command. Verify is me reading "
        "the document. Deliver is me clicking Send. The team is in "
        "Capture only -- the rest is on me."
    ))


def slide_channels(prs):
    s = base_slide(prs, "The four input channels",
                   "All four stage to central automatically. No operator action.")
    channels = [
        ("Teams chat",
         "Read from each dev's local Teams cache. No API, no token.",
         "Every 15 min during BD 18:00-01:00 + 18:00 backfill (1080 min).",
         CORAL),
        ("Teams calls",
         "Voice daemon records mic + speaker as separate tracks.",
         "On \"stop\" / \"Allah Hafez\". Gated to BD 18:00-01:00.",
         TEAL),
        ("Email",
         "IMAP poll of khasan@ael-bd.com on the agent host.",
         "Auto-staged to central every 15 min, 24x7. UID-checkpointed.",
         GOLD),
        ("Google Drive",
         "Service-account read of one shared folder.",
         "Auto-staged to central every 15 min, 24x7, +5 min offset.",
         PURPLE),
    ]
    w = Inches(5.8)
    h = Inches(2.55)
    positions = [
        (Inches(0.6), Inches(1.5)),
        (Inches(6.95), Inches(1.5)),
        (Inches(0.6), Inches(4.25)),
        (Inches(6.95), Inches(4.25)),
    ]
    for (title, l1, l2, color), (x, y) in zip(channels, positions):
        add_box(s, x, y, w, h, title, [l1, "", l2], accent=color)

    set_speaker_notes(s, (
        "All four channels stage to central in the background -- nothing "
        "to remember. Chat + calls on each dev's PC are gated to the BD "
        "evening window (18:00-01:00); a once-daily 18:00 backfill "
        "sweeps any daytime chat so nothing is lost. Email + Drive run "
        "24x7 from the agent host (offset by 5 min to avoid API "
        "contention). Dev machines never hold Gmail or Drive "
        "credentials -- those live on the agent host. The Requirement "
        "Management workflow reads from the central store when I'm "
        "ready to draft."
    ))


def slide_dev_setup(prs):
    s = base_slide(prs, "What every developer does -- once",
                   "Five steps. Ten minutes. No secrets.")
    steps = [
        ("1", "Clone the repo",
         "git clone https://github.com/napco-labs/napco-nucleus"),
        ("2", "Run scripts\\setup.bat",
         "Python, venv, deps, .env. No App Password needed."),
        ("3", "Confirm one line in .env",
         "NUCLEUS_CENTRAL_PATH=\\\\172.16.205.209\\nucleus-central"),
        ("4", "Register the 15-min chat-push",
         ".\\scripts\\register-chat-push-task.ps1"),
        ("5", "Start the voice daemon",
         "Double-click scripts\\start-daemon.bat"),
    ]
    y = Inches(1.55)
    row_h = Inches(0.95)
    for num, head, body in steps:
        add_chip(s, Inches(0.7), y, Inches(0.7), Inches(0.7), num, NAVY)
        tf = add_textbox(s, Inches(1.6), y, Inches(11.0), Inches(0.7),
                         anchor=MSO_ANCHOR.MIDDLE)
        set_text(tf, head, size=16, bold=True, color=NAVY)
        add_para(tf, body, size=12, color=MUTED, space_before=2)
        y = y + row_h

    add_rect(s, Inches(0.6), Inches(6.55), Inches(12.1), Inches(0.45),
             fill_color=SOFT, line_color=RULE)
    tf = add_textbox(s, Inches(0.8), Inches(6.58), Inches(11.7), Inches(0.4),
                     anchor=MSO_ANCHOR.MIDDLE)
    set_text(tf, "Full walk-through: docs/Setup_Guide.pdf in the repo.",
             size=12, color=MUTED)

    set_speaker_notes(s, (
        "I have a PDF that goes through every step in detail. The two "
        "things to keep an eye on: register the cron with admin "
        "PowerShell -- it's a one-line script -- and leave the voice "
        "daemon running. Otherwise calls won't get captured."
    ))


def slide_daily(prs):
    s = base_slide(prs, "What every developer does -- daily",
                   "Mostly nothing. The system does the work.")

    rows = [
        ("Get your chat / attachments to central",
         "Nothing -- the 15-minute cron handles it"),
        ("Record a Teams call",
         "Say \"Start recording\" when the call begins, "
         "\"Stop\" when it ends"),
        ("Include a file from Teams chat",
         "Click \"Download\" on the attachment so it lands in ~/Downloads"),
        ("Update to the latest code",
         "Double-click scripts\\update.bat after a git pull notice"),
    ]
    y = Inches(1.7)
    for what, how in rows:
        add_rect(s, Inches(0.6), y, Inches(12.1), Inches(1.0),
                 fill_color=WHITE, line_color=RULE)
        tf1 = add_textbox(s, Inches(0.9), y + Inches(0.15),
                          Inches(5.0), Inches(0.7),
                          anchor=MSO_ANCHOR.MIDDLE)
        set_text(tf1, what, size=14, bold=True, color=NAVY)
        tf2 = add_textbox(s, Inches(6.1), y + Inches(0.15),
                          Inches(6.6), Inches(0.7),
                          anchor=MSO_ANCHOR.MIDDLE)
        set_text(tf2, how, size=13, color=INK)
        y = y + Inches(1.15)

    set_speaker_notes(s, (
        "I want everyone to internalise: you don't run any command "
        "during the day. Your machine pushes chat every 15 minutes; the "
        "voice daemon listens for the start / stop phrases; downloads "
        "land in ~/Downloads automatically when you click. That's it."
    ))


def slide_titu_command(prs):
    s = base_slide(prs, "What I do",
                   "One command, end-to-end, on demand.")
    add_rect(s, Inches(0.6), Inches(1.7), Inches(12.1), Inches(1.05),
             fill_color=NAVY)
    tf = add_textbox(s, Inches(0.8), Inches(1.85), Inches(11.7), Inches(0.8),
                     anchor=MSO_ANCHOR.MIDDLE)
    set_text(tf, "GHA: Run workflow \"Requirement Management\"   "
                 "or   scripts\\requirement-management.bat",
             size=18, bold=True, color=WHITE, font="Consolas")

    steps = [
        ("1", "Push my local Teams chat to central (force-flush)"),
        ("2", "Walk central: chat + calls + already-staged email + Drive"),
        ("3", "Transcribe every new call (Whisper chunked, parallel)"),
        ("4", "Bangla -> English happens inline at identify time"),
        ("5", "Claude extracts requirements -> drafts verification email"),
        ("6", "Draft lands in [Gmail]/Drafts for me to review and send"),
    ]
    y = Inches(3.05)
    for num, body in steps:
        add_chip(s, Inches(0.8), y, Inches(0.55), Inches(0.55),
                 num, TEAL)
        tf = add_textbox(s, Inches(1.55), y, Inches(11.0), Inches(0.55),
                         anchor=MSO_ANCHOR.MIDDLE)
        set_text(tf, body, size=14, color=INK)
        y = y + Inches(0.6)

    set_speaker_notes(s, (
        "One workflow. Two triggers, same code path: the GitHub Actions "
        "\"Requirement Management\" workflow on the self-hosted runner, "
        "or scripts\\requirement-management.bat on my own machine. "
        "Email + Drive are already on central (auto-staged every 15 min), "
        "so the workflow just walks what's there, transcribes new calls, "
        "and asks Claude to identify + draft. Output is one verification "
        "email in [Gmail]/Drafts -- I read it, edit it, send it, or skip it."
    ))


def slide_architecture(prs):
    s = base_slide(prs, "Where the work happens",
                   "Per-dev push + agent-host central pull + LLM identify.")

    # Three columns
    col_w = Inches(3.85)
    col_h = Inches(4.6)
    y = Inches(1.55)
    xs = [Inches(0.6), Inches(4.75), Inches(8.9)]

    add_box(s, xs[0], y, col_w, col_h, "Dev machines (x N)", [
        "Read local Teams IndexedDB",
        "15-min cron pushes chat + attachments",
        "Voice daemon records calls",
        "Writes to \\\\172.16.205.209\\nucleus-central",
        "No secrets. No API keys.",
    ], accent=NAVY)

    add_box(s, xs[1], y, col_w, col_h, "Agent host (MVPACCESS)", [
        "Pulls email from Gmail (IMAP)",
        "Pulls files from Google Drive",
        "Walks the central share daily",
        "Transcribes calls with Whisper large-v3",
        "Aggregates into one .docx session",
    ], accent=TEAL)

    add_box(s, xs[2], y, col_w, col_h, "LLM identify + draft", [
        "Claude Max -- local CLI on MVPACCESS",
        "Extracts deduped requirement list",
        "Writes Requirements Verification .docx",
        "Builds verification email .eml",
        "IMAP APPEND to [Gmail]/Drafts",
    ], accent=CORAL)

    add_arrow(s, xs[0] + col_w + Inches(0.02), y + col_h / 2,
              xs[1] - Inches(0.04), y + col_h / 2,
              color=MUTED, width_pt=2.5)
    add_arrow(s, xs[1] + col_w + Inches(0.02), y + col_h / 2,
              xs[2] - Inches(0.04), y + col_h / 2,
              color=MUTED, width_pt=2.5)

    set_speaker_notes(s, (
        "Three responsibilities, three machines / processes. Dev "
        "machines push -- only push. Agent host pulls and aggregates. "
        "LLM identifies and drafts. Each layer has the smallest "
        "permissions it needs."
    ))


def slide_outputs(prs):
    s = base_slide(prs, "What you get back",
                   "Three artifacts, every run.")
    out_w = Inches(3.85)
    out_h = Inches(4.6)
    y = Inches(1.55)
    xs = [Inches(0.6), Inches(4.75), Inches(8.9)]

    add_box(s, xs[0], y, out_w, out_h, "Raw session document", [
        "Word .docx",
        "Every email body, attachment text,",
        "chat message, call transcript",
        "Audit trail -- read this if",
        "the LLM output is surprising",
    ], accent=NAVY)

    add_box(s, xs[1], y, out_w, out_h, "Requirements verification doc", [
        "Word .docx",
        "Numbered, deduped requirement list",
        "Ready to attach to the client email",
        "Re-runs dedupe against previous",
        "runs via requirements_seen memory",
    ], accent=TEAL)

    add_box(s, xs[2], y, out_w, out_h, "Draft email in [Gmail]/Drafts", [
        "Standard Gmail draft",
        "Verification doc attached",
        "Pre-filled subject + body",
        "I review -> edit -> send",
        "Nothing is auto-sent",
    ], accent=CORAL)

    set_speaker_notes(s, (
        "Three artifacts. The raw doc is the audit trail. The "
        "requirements doc is what the client will see. The draft is "
        "ready to send. If I find an issue, I can re-run with a "
        "different window or fix the source data and try again."
    ))


def slide_out_of_scope(prs):
    s = base_slide(prs, "What it does NOT do",
                   "Setting boundaries clearly.")
    items = [
        ("Auto-send emails",
         "Every outbound email leaves my mailbox with my explicit click."),
        ("Auto-poll Teams / Email / Drive",
         "The 15-min cron is a chat-push only; the identify pipeline runs on command."),
        ("Push to OpenProject",
         "OpenProject ingest is manual today; auto only when we hit >=80% monthly accuracy."),
        ("Replace client conversations",
         "This is a capture aid. Real client engagement still happens with humans."),
    ]
    y = Inches(1.65)
    for what, why in items:
        add_rect(s, Inches(0.6), y, Inches(12.1), Inches(1.15),
                 fill_color=WHITE, line_color=RULE)
        add_rect(s, Inches(0.6), y, Inches(0.08), Inches(1.15),
                 fill_color=CORAL)
        tf = add_textbox(s, Inches(0.9), y + Inches(0.15),
                         Inches(11.5), Inches(0.85))
        set_text(tf, what, size=15, bold=True, color=NAVY)
        add_para(tf, why, size=12, color=MUTED, space_before=2)
        y = y + Inches(1.30)

    set_speaker_notes(s, (
        "Worth being explicit about boundaries so expectations are right. "
        "This system isn't trying to replace anyone or anything. It is "
        "a capture aid that I drive."
    ))


def slide_roadmap(prs):
    s = base_slide(prs, "Roadmap",
                   "Human-in-the-loop today. Slower-and-correct first.")
    rows = [
        ("Now",
         "Each Requirement Management run produces a draft I review. "
         "Calibration loop, conflict detection, per-run cost telemetry are in.",
         "Manual, predictable, auditable. Cost ~$0.06/run.",
         NAVY),
        ("Next",
         "Tighter dedup across re-runs + Teams attachment auto-resolve "
         "from the in-Teams preview cache",
         "Less manual cleanup before sending.",
         TEAL),
        ("Later", "Auto-publish to OpenProject -- only after >=80% "
                  "monthly accuracy on the requirements doc",
         "Only when we trust the output. Quality gate, not deadline gate.",
         GOLD),
        ("Aspirational", "Auto-send the verification email to clients",
         "Only after the auto-publish step is rock solid.",
         CORAL),
    ]
    y = Inches(1.55)
    for when, what, why, color in rows:
        add_rect(s, Inches(0.6), y, Inches(12.1), Inches(1.20),
                 fill_color=WHITE, line_color=RULE)
        add_chip(s, Inches(0.8), y + Inches(0.32), Inches(1.5),
                 Inches(0.55), when, color)
        tf = add_textbox(s, Inches(2.55), y + Inches(0.15),
                         Inches(10.0), Inches(0.95))
        set_text(tf, what, size=14, bold=True, color=NAVY)
        add_para(tf, why, size=11, color=MUTED, space_before=2)
        y = y + Inches(1.32)

    set_speaker_notes(s, (
        "I'm not chasing automation for its own sake. The order is: "
        "stabilise the manual flow, then layer dedup and convenience, "
        "then layer auto-publish behind an accuracy gate, then -- only "
        "if it's rock solid -- consider auto-send. None of this happens "
        "without measurable wins on the earlier step."
    ))


def slide_what_we_need(prs):
    s = base_slide(prs, "What I need from each of you",
                   "Three small things.")
    items = [
        ("1", "Run setup.bat once",
         "Ten minutes. No secrets. The PDF in docs/ walks you through it."),
        ("2", "Leave Teams open + signed in",
         "The chat ingest reads Teams' own local cache."),
        ("3", "Click \"Download\" on chat files that matter",
         "If a teammate shares a PDF in chat, click Download so we can extract it. "
         "Otherwise only the URL gets captured."),
    ]
    y = Inches(1.8)
    for num, head, body in items:
        add_chip(s, Inches(0.7), y, Inches(0.75), Inches(0.75), num, GREEN)
        tf = add_textbox(s, Inches(1.65), y, Inches(11.0), Inches(0.75),
                         anchor=MSO_ANCHOR.MIDDLE)
        set_text(tf, head, size=18, bold=True, color=NAVY)
        add_para(tf, body, size=12, color=MUTED, space_before=2)
        y = y + Inches(1.55)

    set_speaker_notes(s, (
        "Three things, kept deliberately small. Setup once. Keep Teams "
        "open. Click Download. That's the whole ask. Everything else -- "
        "the pulling, the transcribing, the identifying, the drafting "
        "-- is on the system and on me."
    ))


def slide_close(prs):
    s = prs.slide_layouts[6]
    s = prs.slides.add_slide(s)
    add_rect(s, Inches(0), Inches(0), SLIDE_W, SLIDE_H, fill_color=NAVY)
    tf = add_textbox(s, Inches(0.8), Inches(3.0), Inches(11.7), Inches(1.5))
    set_text(tf, "Questions?", size=64, bold=True, color=WHITE)
    tf2 = add_textbox(s, Inches(0.8), Inches(4.3), Inches(11.7), Inches(1.5))
    set_text(tf2, "Then let's run a live one.",
             size=24, color=RGBColor(0xC8, 0xD2, 0xE0))
    tf3 = add_textbox(s, Inches(0.8), Inches(6.8), Inches(11.7), Inches(0.4))
    set_text(tf3, "github.com/napco-labs/napco-nucleus",
             size=12, color=RGBColor(0x9C, 0xAB, 0xBE))
    set_speaker_notes(s, (
        "Wrap on questions, then offer a live run -- do_it_now.py with "
        "the seeded test data so the team can see the verification doc "
        "and the draft email appear."
    ))


# ── main ───────────────────────────────────────────────────────────

def main():
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    slide_title(prs)
    slide_problem(prs)
    slide_solution(prs)
    slide_channels(prs)
    slide_dev_setup(prs)
    slide_daily(prs)
    slide_titu_command(prs)
    slide_architecture(prs)
    slide_outputs(prs)
    slide_out_of_scope(prs)
    slide_roadmap(prs)
    slide_what_we_need(prs)
    slide_close(prs)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
