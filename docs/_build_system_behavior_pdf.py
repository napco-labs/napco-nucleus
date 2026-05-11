"""Build the System Behavior PDF — executive-facing overview.

Describes how NAPCO Nucleus actually operates: what runs automatically,
what the operator does, what the system produces. Aimed at someone
who isn't reading the code — a stakeholder who wants to know
"if Titu turns this on tomorrow, what actually happens?"

Produces:
    docs/NAPCO-Nucleus-System-Behavior.pdf

Run:  py -3 docs/_build_system_behavior_pdf.py
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


# ── Palette (matches Setup_Guide for visual consistency) ──────────
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
GREEN = colors.HexColor("#2E7D5F")
AMBER = colors.HexColor("#B8771F")

HERE = Path(__file__).parent
OUT = HERE / "NAPCO-Nucleus-System-Behavior.pdf"

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
                      "System Behavior  |  Requirement Management Workflow")
    canvas.setFont("Helvetica-Oblique", 10)
    canvas.setFillColor(colors.HexColor("#A4B4CC"))
    canvas.drawString(MARGIN, PAGE_H - TITLE_BAR_H + 0.18 * inch,
                      "What runs automatically, what Titu triggers manually, what the system produces")
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
                      "System Behavior · Requirement Management")
    _draw_footer(canvas, doc)
    canvas.restoreState()


def _draw_footer(canvas, doc):
    canvas.setStrokeColor(GREY_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 0.6 * inch, PAGE_W - MARGIN, 0.6 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY_TEXT)
    canvas.drawString(MARGIN, 0.38 * inch,
                      "Adaptive Enterprise Limited  |  Prepared by Mohammad Kamrul Hasan (Titu)")
    canvas.drawRightString(PAGE_W - MARGIN, 0.38 * inch, f"Page {doc.page}")


# ── Reusable flowables ────────────────────────────────────────────

def _section_heading(label, title):
    eyebrow = ParagraphStyle(
        "Eyebrow", fontName="Helvetica-Bold", fontSize=8.5,
        textColor=ACCENT, leading=10, spaceAfter=1, alignment=TA_LEFT,
    )
    title_style = ParagraphStyle(
        "Title", fontName="Helvetica-Bold", fontSize=15.5,
        textColor=NAVY, leading=19, spaceBefore=0, spaceAfter=2,
    )
    return KeepTogether([
        Paragraph(label.upper(), eyebrow),
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


def _callout(html, body_style, color=CALLOUT_BAR, bg=CALLOUT_BG):
    bar_w = 0.08 * inch
    inner_w = CONTENT_W - bar_w
    t = Table(
        [["", Paragraph(html, body_style)]],
        colWidths=[bar_w, inner_w],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), color),
        ("BACKGROUND", (1, 0), (1, -1), bg),
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


def _bullets(items, bullet_style):
    return ListFlowable(
        [ListItem(Paragraph(t, bullet_style), leftIndent=18,
                  bulletColor=ACCENT) for t in items],
        bulletType="bullet", start="bulletchar",
        leftIndent=14, bulletFontSize=10, bulletOffsetY=-1,
    )


def _table(rows, *, col_widths, header=True):
    tbl = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("BOX", (0, 0), (-1, -1), 0.6, GREY_BORDER),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, GREY_BORDER) if header else
        ("LINEBELOW", (0, 0), (-1, 0), 0, GREY_BORDER),
        ("LINEBEFORE", (1, 0), (1, -1), 0.4, GREY_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
        style.append(("TEXTCOLOR", (0, 0), (-1, 0), colors.white))
    for i in range(1 if header else 0, len(rows)):
        if (i - (1 if header else 0)) % 2 == 1:
            style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    tbl.setStyle(TableStyle(style))
    return tbl


def _space(h=0.12):
    return Spacer(1, h * inch)


# ── Body ──────────────────────────────────────────────────────────

def build():
    body = ParagraphStyle(
        "Body", fontName="Helvetica", fontSize=10.5,
        leading=15, textColor=BODY_TEXT, spaceAfter=8, alignment=TA_LEFT,
    )
    intro = ParagraphStyle(
        "Intro", parent=body, fontSize=11, leading=16,
        textColor=SOFT_NAVY, spaceAfter=10,
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

    # ── What this is ────────────────────────────────────────────
    flow.append(_section_heading("Overview", "What this document covers"))
    flow.append(Paragraph(
        "NAPCO Nucleus turns the client communications that arrive every "
        "day &mdash; Teams chat, Teams audio calls, email, and Google "
        "Drive files &mdash; into a verified requirements document and "
        "a ready-to-send client email. This document explains exactly "
        "what runs automatically, what Titu triggers manually, and what "
        "the system produces on each run.",
        intro))

    flow.append(_callout(
        "<b>One operator action.</b> Background processes capture content "
        "into a shared store. The operator clicks <b>Run workflow</b> on "
        "GitHub when they want a verification email drafted. The agent "
        "never sends &mdash; every email leaves Gmail with an explicit "
        "click from Titu.",
        body))

    # ── Section 1: Capture (automatic, all four channels) ────────
    flow.append(_space(0.15))
    flow.append(_section_heading("Capture",
                                  "How each input channel reaches central"))
    flow.append(Paragraph(
        "All four channels stage their content into a single shared "
        "store (the central share at <font face='Courier'>"
        "\\\\172.16.205.209\\nucleus-central</font>). No operator action "
        "is required for capture &mdash; it happens continuously.",
        body))

    flow.append(_table(
        [
            [Paragraph("Channel", th),
             Paragraph("Mechanism", th),
             Paragraph("Cadence", th),
             Paragraph("Lands at", th)],
            [Paragraph("<b>Teams chat</b>", td),
             Paragraph("Reads each dev's local Teams cache (no API, no "
                       "token). Bundles recent messages + attachments "
                       "the dev has downloaded.", td),
             Paragraph("Every 15 min, per dev's PC, BD 18:00&ndash;01:00 only "
                       "(once-daily 18:00 backfill catches the daytime gap)", td),
             Paragraph("<font face='Courier'>&lt;central&gt;/&lt;dev&gt;/"
                       "&lt;date&gt;/chat/</font>", td)],
            [Paragraph("<b>Teams calls</b>", td),
             Paragraph("Voice daemon listens for &ldquo;start recording&rdquo; "
                       "/ &ldquo;Allah Hafez&rdquo; phrases during a Teams "
                       "call. Records mic + speaker as separate tracks. "
                       "Auto-uploads on stop.", td),
             Paragraph("On call start/stop, per dev's PC, BD 18:00&ndash;01:00 "
                       "only (gate matches the chat-push window)", td),
             Paragraph("<font face='Courier'>&lt;central&gt;/&lt;dev&gt;/"
                       "&lt;date&gt;/calls/</font>", td)],
            [Paragraph("<b>Email</b>", td),
             Paragraph("IMAP poll of <font face='Courier'>khasan@ael-bd.com"
                       "</font>. Extracts body + attachment text (PDF / "
                       "Word / Excel / TXT).", td),
             Paragraph("Every 15 min, on the agent host (MVPACCESS)", td),
             Paragraph("<font face='Courier'>&lt;central&gt;/email/"
                       "&lt;date&gt;/</font>", td)],
            [Paragraph("<b>Google Drive</b>", td),
             Paragraph("Service-account read of the configured folder. "
                       "Downloads each new file; same extractor stack as "
                       "email attachments.", td),
             Paragraph("Every 15 min, +5 min offset, on MVPACCESS", td),
             Paragraph("<font face='Courier'>&lt;central&gt;/drive/"
                       "&lt;date&gt;/</font>", td)],
        ],
        col_widths=[0.95 * inch, 2.6 * inch, 1.55 * inch,
                    CONTENT_W - 0.95 * inch - 2.6 * inch - 1.55 * inch],
    ))

    flow.append(_space(0.08))
    flow.append(Paragraph(
        "Each channel uses a dedup record (UID checkpoint for email, "
        "file-id for Drive, per-message ID for chat, per-stamp filename "
        "for calls) so re-runs never duplicate the same content. "
        "Failures on one channel never block another &mdash; if Drive is "
        "unreachable, email + chat + calls still flow.",
        body))

    flow.append(_callout(
        "<b>Dev-machine capture is on a BD evening clock.</b> The chat "
        "push (15-min cron) and the voice daemon recorder only fire "
        "during BD 18:00&ndash;01:00 &mdash; that's the active work "
        "window. A one-shot 18:00 chat backfill (<font face='Courier'>"
        "--last-minutes 1080</font>) catches any daytime messages on "
        "the next window open, so nothing is lost. Email + Drive "
        "stagers on the agent host run 24&times;7 and are not "
        "subject to this gate. Manual triggers "
        "(<font face='Courier'>scripts\\requirement-management.bat</font>, "
        "<font face='Courier'>--allow-any-call</font> on the voice "
        "daemon) bypass the window for ad-hoc / demo use.",
        body))

    # ── Section 2: Trigger ───────────────────────────────────────
    flow.append(_space(0.15))
    flow.append(_section_heading("Trigger",
                                  "The one workflow Titu runs manually"))

    flow.append(Paragraph(
        "Identification of requirements + drafting of the client email "
        "is on-demand. It runs only when Titu clicks the <b>Requirement "
        "Management</b> button in the GitHub Actions tab "
        "(<font face='Courier'>napco-labs/napco-nucleus</font> repository). "
        "There is <b>no schedule</b>, no auto-fire, no cron for the "
        "identify step.",
        body))

    flow.append(_callout(
        "<b>Two ways to trigger the same pipeline.</b><br/>"
        "&bull; <b>GitHub Actions UI</b> &mdash; click &ldquo;Run "
        "workflow&rdquo; on the Requirement Management workflow, fill "
        "the client name and time window, click Run.<br/>"
        "&bull; <b>Local one-click</b> &mdash; double-click "
        "<font face='Courier'>scripts\\requirement-management.bat</font> "
        "on Titu's machine. Same result.",
        body))

    flow.append(_sub_heading("Inputs the operator provides"))
    flow.append(_table(
        [
            [Paragraph("Input", th),
             Paragraph("Purpose", th),
             Paragraph("Default", th)],
            [Paragraph("<b>client</b>", td),
             Paragraph("Substring filter on client name. Pass <font face='Courier'>"
                       "all</font> to process every client in scope.", td),
             Paragraph("<font face='Courier'>all</font>", td)],
            [Paragraph("<b>last_minutes</b>", td),
             Paragraph("How far back to look for chat / email / Drive content. "
                       "<font face='Courier'>2880</font> = 48 hours, "
                       "<font face='Courier'>60</font> = last hour, etc.", td),
             Paragraph("<font face='Courier'>2880</font>", td)],
            [Paragraph("<b>day</b>", td),
             Paragraph("Date of recordings to scan (YYYY-MM-DD). Empty means today.", td),
             Paragraph("today", td)],
            [Paragraph("<b>dry_run</b>", td),
             Paragraph("If <font face='Courier'>true</font>: collect + transcribe "
                       "but skip identify + draft. Useful for diagnostics.", td),
             Paragraph("<font face='Courier'>false</font>", td)],
        ],
        col_widths=[1.1 * inch, 4.0 * inch, CONTENT_W - 1.1 * inch - 4.0 * inch],
    ))

    # ── Section 3: Action sequence ──────────────────────────────
    flow.append(_space(0.15))
    flow.append(_section_heading("Action",
                                  "What happens when Titu clicks Run"))

    flow.append(Paragraph(
        "The workflow executes on a self-hosted runner on MVPACCESS, "
        "pulls the latest code from <font face='Courier'>main</font>, "
        "and walks through the eight steps below. Typical wall-clock: "
        "1&ndash;3 minutes if no calls fall in the window; 15&ndash;25 "
        "minutes if a 1-hour Bangla call needs transcribing.",
        body))

    steps = [
        ("Walk the central share",
         "Enumerate today's chat .docx files, call .wav + .json pairs, "
         "and chat attachments for every developer."),
        ("Reset the unified session document",
         "Start a clean session.docx so this run's output is independent "
         "of any prior run."),
        ("Pull fresh email + Drive",
         "Live IMAP and Drive API calls catch anything that landed in "
         "the last 15 minutes since the staging cron last ran."),
        ("Transcribe call recordings",
         "Whisper large-v3, chunked into 5-minute pieces and run in "
         "parallel across 4 CPU threads. Bangla audio is transcribed "
         "verbatim; Claude translates meaning to English in step 6. "
         "Low-confidence segments are flagged for the reviewer."),
        ("Assemble the unified session document",
         "Append each call transcript + chat + email + Drive file as a "
         "labelled section with a stable Source ID for citation."),
        ("Identify requirements",
         "Claude reads the session doc, resolves the client (NAPCO "
         "Security for @napcosecurity.com, internal AEL stakeholders "
         "by individual name), pulls the client's past requirements + "
         "open in-flight items, and extracts each new requirement with: "
         "title, summary, source citations, confidence, rationale, "
         "priority (P0-P3), severity (S1-S3), audio time ranges, and "
         "conflict flags against prior items."),
        ("Write the verification document",
         "<font face='Courier'>Requirements Verification &lt;date&gt;.docx</font> "
         "&mdash; a numbered list, one paragraph per requirement, with "
         "citation + confidence + audio links shown below each item."),
        ("Draft the client email",
         "Builds an .eml with two attachments (the verification doc + "
         "the raw session doc), picks the right tone template based on "
         "client name (formal for NAPCO Security, informal for AEL "
         "stakeholders), pushes the draft to [Gmail]/Drafts. A prior "
         "same-subject draft is replaced so re-runs don't pile up."),
    ]
    rows = [[Paragraph("Step", th), Paragraph("What it does", th)]]
    for i, (name, desc) in enumerate(steps, 1):
        rows.append([Paragraph(f"<b>{i}. {name}</b>", td),
                     Paragraph(desc, td)])
    flow.append(_table(rows, col_widths=[1.9 * inch, CONTENT_W - 1.9 * inch]))

    # ── Section 4: Artifacts ────────────────────────────────────
    flow.append(_space(0.15))
    flow.append(_section_heading("Output",
                                  "What every run produces"))

    flow.append(_table(
        [
            [Paragraph("Artifact", th),
             Paragraph("Audience", th),
             Paragraph("Notes", th)],
            [Paragraph("<b>Verification document</b>", td),
             Paragraph("Client", td),
             Paragraph("Numbered list of requirements with confidence + "
                       "priority badges; attached to the verification email.", td)],
            [Paragraph("<b>Pull session document</b>", td),
             Paragraph("Client (optional) + reviewer", td),
             Paragraph("Raw source material the requirements were drawn "
                       "from. Lets the client cross-check anything that "
                       "looks off.", td)],
            [Paragraph("<b>Gmail draft</b>", td),
             Paragraph("Operator (Titu)", td),
             Paragraph("Lives in <font face='Courier'>[Gmail]/Drafts</font>. "
                       "Operator reviews + edits + sends manually. The "
                       "agent never sends.", td)],
            [Paragraph("<b>Memory update</b>", td),
             Paragraph("System (internal)", td),
             Paragraph("Each requirement recorded against the client so "
                       "the next run dedupes and surfaces follow-ups.", td)],
            [Paragraph("<b>Pipeline trace</b>", td),
             Paragraph("Operator (debug only)", td),
             Paragraph("Per-stage record of what Claude saw + said + "
                       "called. Replayable when an output is surprising.", td)],
        ],
        col_widths=[1.65 * inch, 1.6 * inch, CONTENT_W - 1.65 * inch - 1.6 * inch],
    ))

    # ── Section 5: Quality + uncertainty ────────────────────────
    flow.append(_space(0.15))
    flow.append(_section_heading("Quality",
                                  "How the system surfaces its own uncertainty"))

    flow.append(Paragraph(
        "Speech-to-text and language-model extraction are imperfect, "
        "especially on real client audio with accent and background "
        "noise. The system is built around human-in-the-loop review &mdash; "
        "the operator always reviews the draft before sending. To make "
        "that review fast, the system explicitly marks the lines that "
        "deserve closer attention:",
        body))

    flow.append(_bullets([
        "<b>Uncertain audio segments</b> &mdash; transcript lines where "
        "Whisper's per-segment confidence was low get an "
        "<i>(uncertain)</i> tag so the reviewer knows where to re-listen.",
        "<b>Low-confidence requirements</b> &mdash; items the model "
        "rates below 0.75 are shown in amber with a "
        "<i>(review)</i> marker in the verification document.",
        "<b>Conflict warnings</b> &mdash; if today's content "
        "contradicts an open item from a prior session, a "
        "<b>&#9888; Possible conflict</b> line is shown.",
        "<b>Audio anchors</b> &mdash; for any requirement extracted from "
        "a call, the document shows the exact <font face='Courier'>"
        "HH:MM:SS-HH:MM:SS</font> range so the reviewer can pull a "
        "30-second snippet for spot-check.",
        "<b>Calibration feedback</b> &mdash; the system tracks how "
        "often the reviewer keeps vs. rejects items by confidence "
        "band, and feeds that signal into the next run's prompt so "
        "the model's stated confidence becomes more accurate over time.",
    ], bullet_s))

    # ── Section 6: What the operator does ───────────────────────
    flow.append(_space(0.15))
    flow.append(_section_heading("Operator",
                                  "Titu's daily role"))

    flow.append(_table(
        [
            [Paragraph("Action", th), Paragraph("Frequency", th)],
            [Paragraph("Keep Teams desktop signed in", td),
             Paragraph("Continuously (background only)", td)],
            [Paragraph("Voice daemon running on laptop", td),
             Paragraph("Continuously; active recording only fires "
                       "during BD 18:00&ndash;01:00", td)],
            [Paragraph("Say a phrase like &ldquo;start recording&rdquo; "
                       "/ &ldquo;Allah Hafez&rdquo; on Teams calls", td),
             Paragraph("Per client call (a few seconds of effort)", td)],
            [Paragraph("Click &ldquo;Run workflow&rdquo; on Requirement "
                       "Management in GitHub Actions", td),
             Paragraph("Whenever a verification email is needed", td)],
            [Paragraph("Review the draft email in [Gmail]/Drafts, "
                       "edit if needed, click Send", td),
             Paragraph("Once per run (typically 3&ndash;10 minutes per "
                       "session)", td)],
        ],
        col_widths=[CONTENT_W * 0.58, CONTENT_W * 0.42],
    ))

    flow.append(_space(0.08))
    flow.append(Paragraph(
        "All other behaviour &mdash; capture, transcription, requirement "
        "extraction, conflict detection, memory of past sessions &mdash; "
        "happens automatically on the agent host. The team's daily work "
        "is unaffected: developers carry on having client calls and "
        "exchanging chat messages exactly as before. The system "
        "observes, organizes, and produces a draft. Titu approves "
        "and sends.",
        body))

    # ── Section 7: Reliability ──────────────────────────────────
    flow.append(_space(0.15))
    flow.append(_section_heading("Reliability",
                                  "How the system handles failure"))

    flow.append(_bullets([
        "<b>Retry with backoff</b> on transient IMAP / Drive / SMTP "
        "failures &mdash; a single network blip never costs a run.",
        "<b>Per-stage timeouts</b> &mdash; a stuck stage aborts cleanly "
        "instead of blocking indefinitely.",
        "<b>Cross-process locking</b> &mdash; if Titu clicks Run "
        "Workflow twice within seconds, the second invocation waits "
        "for the first to finish instead of corrupting shared state.",
        "<b>Idempotent draft replacement</b> &mdash; re-running for the "
        "same day replaces the prior Gmail draft instead of stacking "
        "duplicates.",
        "<b>Per-run trace artifact</b> &mdash; if a run fails, the raw "
        "session document is uploaded for debugging.",
    ], bullet_s))

    # ── Closing ─────────────────────────────────────────────────
    flow.append(_space(0.18))
    flow.append(_callout(
        "<b>Bottom line.</b> The system captures every channel "
        "automatically, requires one click from Titu when a draft is "
        "needed, and produces a verification email ready for his "
        "review. It is conservative about its own accuracy &mdash; "
        "uncertainty is surfaced, never hidden, and no email leaves "
        "Gmail without Titu's explicit action.",
        body, color=ACCENT, bg=LIGHT_BLUE))

    return flow


# ── Document ──────────────────────────────────────────────────────

def main():
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=LETTER,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=TITLE_BAR_H + 0.05 * inch,
        bottomMargin=0.75 * inch,
        title="NAPCO Nucleus — System Behavior",
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
