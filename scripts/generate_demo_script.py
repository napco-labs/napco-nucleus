"""Render the live demo script as a PDF.

Card-based, colorful. Same design language as the Architecture and
Study Guide PDFs.

Each demo segment has: timing, what to type, what to say while it
runs, what to expect to see, what to do if it breaks.

Run:
    py -3 scripts/generate_demo_script.py
Output:
    docs/Presentation-Live-Demo-Script.pdf
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as canvas_mod
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT_PATH = ROOT / "docs" / "Presentation-Live-Demo-Script.pdf"

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# Brand palette
NAVY    = colors.HexColor("#1F4E79")
TEAL    = colors.HexColor("#2E8A8A")
CORAL   = colors.HexColor("#E07856")
GREEN   = colors.HexColor("#4A7A4A")
GOLD    = colors.HexColor("#C9962B")
PURPLE  = colors.HexColor("#6A4C93")
RED     = colors.HexColor("#B5483A")
INK     = colors.HexColor("#222222")
MUTED   = colors.HexColor("#6B7785")
SOFT    = colors.HexColor("#F5F7FA")
WHITE   = colors.white
RULE    = colors.HexColor("#D5DCE5")
WARN_BG = colors.HexColor("#FFF1E6")
GO_BG   = colors.HexColor("#EAF4EA")
SAY_BG  = colors.HexColor("#EFF3F8")

TITLE = ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=22, leading=26,
                       textColor=NAVY, spaceAfter=2)
SUBTITLE = ParagraphStyle("Subtitle", fontName="Helvetica", fontSize=12, leading=15,
                          textColor=MUTED, spaceAfter=4)
BYLINE = ParagraphStyle("Byline", fontName="Helvetica-Bold", fontSize=10, leading=13,
                        textColor=NAVY, spaceAfter=10)
CARD_HEAD = ParagraphStyle("CardHead", fontName="Helvetica-Bold", fontSize=11, leading=14,
                           textColor=WHITE)
CARD_BODY = ParagraphStyle("CardBody", fontName="Helvetica", fontSize=9.5, leading=13,
                           textColor=INK, spaceAfter=4)
LABEL = ParagraphStyle("Label", fontName="Helvetica-Bold", fontSize=8.5, leading=11,
                       textColor=NAVY, spaceAfter=2)
SAY = ParagraphStyle("Say", fontName="Helvetica-Oblique", fontSize=10, leading=13,
                     textColor=NAVY, alignment=TA_LEFT, leftIndent=4, rightIndent=4)
CMD = ParagraphStyle("Cmd", fontName="Courier-Bold", fontSize=9, leading=12,
                     textColor=colors.HexColor("#0A2540"),
                     backColor=colors.HexColor("#E8EEF5"),
                     borderPadding=4, leftIndent=0, rightIndent=0)
EXPECT = ParagraphStyle("Expect", fontName="Helvetica", fontSize=9, leading=12,
                        textColor=INK, leftIndent=10, bulletIndent=0, spaceAfter=2)
FALLBACK = ParagraphStyle("Fallback", fontName="Helvetica", fontSize=9, leading=12,
                          textColor=colors.HexColor("#7A3A2C"), leftIndent=10,
                          bulletIndent=0, spaceAfter=2)
TIMING = ParagraphStyle("Timing", fontName="Helvetica-Bold", fontSize=9, leading=11,
                        textColor=WHITE, alignment=TA_CENTER)


def _on_page(canvas: canvas_mod.Canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - 4, PAGE_W, 4, stroke=0, fill=1)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN, 8 * mm,
                      "Live Demo Script  |  Mohammad Kamrul Hasan, AI-Augmented QA Architect")
    canvas.drawRightString(PAGE_W - MARGIN, 8 * mm, f"page {doc.page}")
    canvas.restoreState()


def card(header_text: str, body_flowables, header_color=NAVY, body_bg=WHITE,
         timing: str = None) -> Table:
    if not isinstance(body_flowables, list):
        body_flowables = [body_flowables]
    if timing:
        # header has two columns: title + timing chip
        head_row = Table(
            [[Paragraph(header_text, CARD_HEAD), Paragraph(timing, TIMING)]],
            colWidths=[CONTENT_W - 30 * mm, 30 * mm],
        )
        head_row.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), header_color),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        outer = Table(
            [[head_row], [body_flowables]],
            colWidths=[CONTENT_W],
        )
        outer.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, 0), 10),
            ("RIGHTPADDING", (0, 0), (-1, 0), 10),
            ("TOPPADDING", (0, 0), (-1, 0), 5),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
            ("BACKGROUND", (0, 0), (-1, 0), header_color),
            ("BACKGROUND", (0, 1), (-1, 1), body_bg),
            ("LEFTPADDING", (0, 1), (-1, 1), 10),
            ("RIGHTPADDING", (0, 1), (-1, 1), 10),
            ("TOPPADDING", (0, 1), (-1, 1), 8),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
            ("BOX", (0, 0), (-1, -1), 0.4, RULE),
        ]))
        return outer
    inner = Table(
        [[Paragraph(header_text, CARD_HEAD)],
         [body_flowables]],
        colWidths=[CONTENT_W],
    )
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("LEFTPADDING", (0, 0), (-1, 0), 10),
        ("RIGHTPADDING", (0, 0), (-1, 0), 10),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("BACKGROUND", (0, 1), (-1, 1), body_bg),
        ("LEFTPADDING", (0, 1), (-1, 1), 10),
        ("RIGHTPADDING", (0, 1), (-1, 1), 10),
        ("TOPPADDING", (0, 1), (-1, 1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
    ]))
    return inner


def section(title: str, body, color, body_bg=SAY_BG):
    """A small typed-content block: green for DO, blue for SAY, red for FALLBACK."""
    return Table(
        [[Paragraph(title, LABEL)], [body]],
        colWidths=[CONTENT_W - 20 * mm],
    )


def build():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT_PATH), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 4, bottomMargin=MARGIN,
        title="NAPCO Nucleus Live Demo Script",
        author="Mohammad Kamrul Hasan",
    )
    frame = Frame(MARGIN, MARGIN, CONTENT_W, PAGE_H - 2 * MARGIN - 4,
                  id="main", showBoundary=0,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="Default", frames=[frame], onPage=_on_page)])

    s: list = []

    # ── Title
    s.append(Paragraph("Live Demo Script", TITLE))
    s.append(Paragraph("30 to 40 minute presentation, second by second", SUBTITLE))
    s.append(Paragraph(
        "Mohammad Kamrul Hasan &nbsp;&middot;&nbsp; AI-Augmented QA Architect "
        "&nbsp;&middot;&nbsp; April 2026",
        BYLINE,
    ))

    # ── Schedule overview
    s.append(card("YOUR 35-MINUTE PLAN", [
        Paragraph("•&nbsp;&nbsp;<b>0 to 4 min:</b> &nbsp; Open + architecture overview", EXPECT),
        Paragraph("•&nbsp;&nbsp;<b>4 to 12 min:</b> &nbsp; Demo 1 — Requirement Management LIVE", EXPECT),
        Paragraph("•&nbsp;&nbsp;<b>12 to 21 min:</b> &nbsp; Demo 2 — API Functional Test LIVE", EXPECT),
        Paragraph("•&nbsp;&nbsp;<b>21 to 25 min:</b> &nbsp; Demo 3 — Memory in action", EXPECT),
        Paragraph("•&nbsp;&nbsp;<b>25 to 29 min:</b> &nbsp; Engineering decisions (4 trade-offs)", EXPECT),
        Paragraph("•&nbsp;&nbsp;<b>29 to 32 min:</b> &nbsp; Value + roadmap + the ask", EXPECT),
        Paragraph("•&nbsp;&nbsp;<b>32 to 40 min:</b> &nbsp; Q and A", EXPECT),
    ], header_color=NAVY))
    s.append(Spacer(1, 6))

    # ── Pre-flight
    s.append(card("PRE-FLIGHT (do this 30 minutes before audience arrives)", [
        Paragraph("•&nbsp;&nbsp;Open terminal at <font face='Courier' size='9'>E:/Projects/NAPCO-Nucleus</font>. Activate venv if needed.", EXPECT),
        Paragraph("•&nbsp;&nbsp;Open DB Browser for SQLite. Load <font face='Courier' size='9'>nucleus_memory.db</font>.", EXPECT),
        Paragraph("•&nbsp;&nbsp;Open browser tabs: GitHub repo (Actions tab), GitLab project (titucs/mvp-access), Drive folder, your inbox.", EXPECT),
        Paragraph("•&nbsp;&nbsp;Open <font face='Courier' size='9'>NN-Architecture.pdf</font> on screen for the overview.", EXPECT),
        Paragraph("•&nbsp;&nbsp;Send yourself a fake requirement email from a different address (e.g., titucse@gmail.com) to khasan@ael-bd.com. Subject: 'Add a Forgot Password link to the login page'. Body: '~2 hours of work, no priority. Send by end of week.' This becomes the demo trigger.", EXPECT),
        Paragraph("•&nbsp;&nbsp;Run <font face='Courier' size='9'>py -3 agent.py --task requirement-management --dry-run</font> ONCE silently to warm imports + verify auth.", EXPECT),
        Paragraph("•&nbsp;&nbsp;Close anything visually noisy. Cell phone on silent. Notifications muted.", EXPECT),
    ], header_color=GOLD, body_bg=WARN_BG))

    s.append(PageBreak())

    # ── Opening (0-4 min)
    s.append(card("OPENING — ARCHITECTURE OVERVIEW", [
        Paragraph(
            '<b>SAY (verbatim, slowly, calmly):</b> "You have all heard about AI agents '
            'this past year. The Anthropic and OpenAI announcements, the demos, the '
            'LinkedIn posts. Tonight you are going to see one running on our infrastructure, '
            'on our data, doing real work for our team. Not a slide deck about what AI '
            'might do. A working agent that filed thirteen real client requirements into '
            'our GitLab backlog this morning, from emails and meeting recordings, while '
            'we slept. I am Mohammad. I am a QA architect by trade. I designed and shipped '
            'this end to end by directing AI through Claude Code. Let me show you what '
            'that looks like."',
            SAY,
        ),
        Spacer(1, 4),
        Paragraph(
            "<b>SHOW (3 min):</b> Switch to NN-Architecture.pdf page 1. Walk through the "
            "metrics row (9 workflows, 31 tools, 4 tests at 2am, 2 daily emails, $200/month). "
            "Then point at the 'How one run works' card. Spend 30 seconds on each step.",
            CARD_BODY,
        ),
        Paragraph(
            "<b>TRANSITION:</b> 'OK enough talking about it. Let me show you the agent "
            "actually doing something.'",
            CARD_BODY,
        ),
    ], header_color=NAVY, timing="0 - 4 MIN"))
    s.append(Spacer(1, 6))

    # ── Demo 1 — Requirement Management (4-12 min)
    s.append(card("DEMO 1 — REQUIREMENT MANAGEMENT (LIVE)", [
        Paragraph("<b>SAY:</b> 'I just sent myself an email with a fake client requirement. Watch the agent pick it up.'", SAY),
        Spacer(1, 4),
        Paragraph("<b>TYPE in terminal:</b>", LABEL),
        Preformatted("py -3 agent.py --task requirement-management --dry-run", CMD),
        Spacer(1, 4),
        Paragraph(
            "<b>NARRATE WHILE IT RUNS (~3 min):</b> 'See those log lines? It is connecting "
            "to our Gmail mailbox via IMAP... now it is checking the Drive folder for new "
            "recordings... now Claude is reading the inbox files...' Pause. 'Now Claude "
            "is splitting each email into 3-hour tasks. Watch the JSON come back.' Pause "
            "again. 'And now it is checking each task against memory to see if we have "
            "filed it before. Idempotent dedup. Re-running this never duplicates work.'",
            CARD_BODY,
        ),
        Paragraph("<b>EXPECT TO SEE:</b>", LABEL),
        Paragraph("•&nbsp;&nbsp;Logs from requirements_inbox connecting to imap.gmail.com", EXPECT),
        Paragraph("•&nbsp;&nbsp;'Found N ingestable file(s)' from drive_ingester", EXPECT),
        Paragraph("•&nbsp;&nbsp;Claude narrating its splitting decisions", EXPECT),
        Paragraph("•&nbsp;&nbsp;'created: X, skipped: Y, failed: 0' summary at the end", EXPECT),
        Spacer(1, 4),
        Paragraph("<b>SHOW (after run finishes):</b> Switch to GitLab tab. Refresh. Point at the new issue or the most recent one. 'Here is the actual issue, in our actual project. The body has the source file reference. The estimate is in the body. The labels are applied.'", CARD_BODY),
        Spacer(1, 4),
        Paragraph("<b>FALLBACK if the run fails:</b>", LABEL),
        Paragraph("•&nbsp;&nbsp;'OK this just failed because X. Watch how the agent logs the error to memory and exits cleanly. That is by design. Failures are visible, not silent.' Then open DB Browser, show the activity_logs row with result='error:...'", FALLBACK),
        Paragraph("•&nbsp;&nbsp;Backup demo: 'Let me show you what an earlier run produced.' Refresh GitLab and point at the 13 issues from this morning's automatic run.", FALLBACK),
    ], header_color=TEAL, timing="4 - 12 MIN"))

    s.append(PageBreak())

    # ── Demo 2 — API Functional Test (12-21 min)
    s.append(card("DEMO 2 — API FUNCTIONAL TEST (LIVE)", [
        Paragraph("<b>SAY:</b> 'Now let me show you the test side. This is the agent running our Newman / Postman collection against the live API. Notice that I am about to run it just like the scheduled 02:00 BDT cron does, no special handling.'", SAY),
        Spacer(1, 4),
        Paragraph("<b>TYPE in terminal:</b>", LABEL),
        Preformatted("py -3 agent.py --task api-functional-test", CMD),
        Spacer(1, 4),
        Paragraph(
            "<b>NARRATE WHILE IT RUNS (~6 min):</b> 'Pre-flight check first. The agent is "
            "pinging the login endpoint to make sure the server is alive before burning a "
            "test budget on a dead target.' Pause. 'Now Newman is firing. You will see one "
            "of these for every request that fails an assertion.' Pause. 'And here is the "
            "interesting part. Once Newman finishes, the agent is going to open known_bugs.py, "
            "match each failure against the xfail markers, and tell you which failures are "
            "real bugs versus which ones are already tracked.' Wait for results. Then: "
            "'288 of 315 passed. 27 failed. The agent is going to interpret each failure now.'",
            CARD_BODY,
        ),
        Paragraph("<b>EXPECT TO SEE:</b>", LABEL),
        Paragraph("•&nbsp;&nbsp;'API health check passed: server at ... responded in Xms'", EXPECT),
        Paragraph("•&nbsp;&nbsp;Newman test output streaming through", EXPECT),
        Paragraph("•&nbsp;&nbsp;'API Test: PARTIAL — 288/315 passed' summary line", EXPECT),
        Paragraph("•&nbsp;&nbsp;Claude reasoning aloud about specific failures", EXPECT),
        Paragraph("•&nbsp;&nbsp;PDF path printed at the end", EXPECT),
        Spacer(1, 4),
        Paragraph("<b>SHOW (after run finishes):</b> Open the generated PDF. Point at one failure card. 'See the classification: real_bug versus known_bug. The reasoning column is Claude saying why. This is what the test team will read tomorrow morning.'", CARD_BODY),
        Spacer(1, 4),
        Paragraph("<b>FALLBACK if the run hangs or fails:</b>", LABEL),
        Paragraph("•&nbsp;&nbsp;Ctrl-C. Then: 'OK that is the network or the API being slow. Let me show you a result from earlier today.' Open the email I auto-sent earlier showing 91.4% pass rate.", FALLBACK),
        Paragraph("•&nbsp;&nbsp;Backup demo: open <font face='Courier' size='9'>MVP-Access-API-Test/reports/Test_Report_20260426_*.pdf</font> directly.", FALLBACK),
    ], header_color=CORAL, timing="12 - 21 MIN"))

    s.append(PageBreak())

    # ── Demo 3 — Memory (21-25 min)
    s.append(card("DEMO 3 — MEMORY IN ACTION", [
        Paragraph("<b>SAY:</b> 'Now the secret sauce. Every run I just did wrote rows to a SQLite database. That database is committed to the git repo. It is the agent\\'s memory across runs.'", SAY),
        Spacer(1, 4),
        Paragraph("<b>SHOW:</b> Switch to DB Browser. Already has nucleus_memory.db open.", LABEL),
        Paragraph("•&nbsp;&nbsp;Click the activity_logs table. Scroll to today. Point: 'Every action the agent took, with timestamp and result.'", EXPECT),
        Paragraph("•&nbsp;&nbsp;Click requirements_seen. 'Every requirement it has filed, with normalized titles for fuzzy dedup. This is why re-running never creates duplicates.'", EXPECT),
        Paragraph("•&nbsp;&nbsp;Click test_run_history. 'Every test run, with pass / fail counts and the PDF path. This is what the morning Daily Report reads from.'", EXPECT),
        Spacer(1, 4),
        Paragraph("<b>SAY:</b> 'And because the database lives in git, when the runner picks up tomorrow morning at 02:00, it has full memory of every prior run. No external database to provision. Disaster recovery is git clone.'", SAY),
        Spacer(1, 4),
        Paragraph("<b>FALLBACK:</b>", LABEL),
        Paragraph("•&nbsp;&nbsp;If DB Browser hangs: 'Let me query it from the terminal instead.' Run <font face='Courier' size='9'>py -3 -c \"import memory; print(memory.stats())\"</font>", FALLBACK),
    ], header_color=PURPLE, timing="21 - 25 MIN"))

    s.append(Spacer(1, 6))

    # ── Engineering decisions (25-29 min)
    s.append(card("ENGINEERING DECISIONS (4 TRADE-OFFS, ~1 MIN EACH)", [
        Paragraph("<b>SAY:</b> 'Now I want to spend 4 minutes on the engineering decisions, because the engineers in the room will care about these.'", SAY),
        Spacer(1, 4),
        Paragraph("<b>1. Claude Max via local CLI, not ANTHROPIC_API_KEY.</b> 'Cost is fixed monthly, not per token. Eight scheduled workflows fire 30 times a day. On the API that would be real money. About $200 a month flat.'", CARD_BODY),
        Paragraph("<b>2. Algorithms in prompts, not Python.</b> 'I deleted 638 lines of regex-based heuristics last week and moved that work into prompts. Adding a new failure category is a markdown edit, not a code review.'", CARD_BODY),
        Paragraph("<b>3. Memory committed to git.</b> 'The SQLite database is in the repo. Cloning the project gives you the agent\\'s full history. Disaster recovery is git clone.'", CARD_BODY),
        Paragraph("<b>4. Self-hosted runner.</b> 'Direct access to staging behind VPN, direct access to TFS, direct access to IIS UNC paths. None reachable from a hosted runner. Secrets stay on our infrastructure.'", CARD_BODY),
    ], header_color=GREEN, timing="25 - 29 MIN"))

    s.append(PageBreak())

    # ── Closing (29-32 min)
    s.append(card("VALUE + ROADMAP + THE ASK", [
        Paragraph("<b>SAY (value, ~90 seconds):</b>", LABEL),
        Paragraph(
            '"What this delivers today: 13 client requirements automatically filed in '
            'GitLab from this morning. 27 backend bugs classified across the test suite. '
            'A 100-user load test that surfaced real staging strain we acted on. A '
            'consolidated daily report that replaces six fragmented per-suite emails. '
            'And it does this every day on a fixed monthly cost."',
            SAY,
        ),
        Spacer(1, 4),
        Paragraph("<b>SAY (roadmap, ~60 seconds):</b>", LABEL),
        Paragraph(
            '"What is next: fix the runner permission so all four test workflows can see '
            'the sibling test code. Plug TFS and IIS credentials into the CICD workflow '
            'so we own the deploy cycle too. Add Teams chat as a third requirement intake '
            'source. Add fixture self-healing for E2E so when staging changes a button '
            'text, the agent updates the selector instead of the test failing."',
            SAY,
        ),
        Spacer(1, 4),
        Paragraph("<b>SAY (the ask, ~30 seconds):</b>", LABEL),
        Paragraph(
            '"To unlock the next phase I need three operational things from this team: '
            '(1) IT to grant the runner service account read access to E:/Projects, '
            '(2) DevOps to add the six TFS and IIS secrets to GHA, '
            '(3) approval to keep the Claude Max subscription as a line item. '
            'Once those land, NAPCO Nucleus owns the full code-to-test-to-deploy cycle '
            'every night."',
            SAY,
        ),
    ], header_color=NAVY, timing="29 - 32 MIN"))
    s.append(Spacer(1, 6))

    # ── Q&A guidance (32-40 min)
    s.append(card("Q AND A SURVIVAL", [
        Paragraph("•&nbsp;&nbsp;<b>Pause 2 seconds before answering.</b> Looks thoughtful, not slow.", EXPECT),
        Paragraph("•&nbsp;&nbsp;<b>Anchor every answer back to the thesis.</b> 'QA architect plus AI equals senior dev team output.'", EXPECT),
        Paragraph("•&nbsp;&nbsp;<b>For the developer-question (most likely): own the AI partnership.</b> See Study Guide page 4. 'I designed it. AI implemented under my direction. The system is real, the issues are in GitLab, the reports are in your inbox.'", EXPECT),
        Paragraph("•&nbsp;&nbsp;<b>If you do not know:</b> 'Let me check.' Open the file, look it up. Better than guessing.", EXPECT),
        Paragraph("•&nbsp;&nbsp;<b>If someone challenges hard:</b> 'Good question. We considered Y and chose X because of Z.' Always name the alternative.", EXPECT),
    ], header_color=PURPLE, timing="32 - 40 MIN"))
    s.append(Spacer(1, 6))

    # ── Closing line
    s.append(card("FINAL LINE WHEN Q&A WINDS DOWN", Paragraph(
        '"Thank you. The agent is going to keep running every two hours and every '
        'morning. The next Daily Report will land in your inbox at 09:00 tomorrow. '
        'Open it and tell me what you want changed."',
        SAY,
    ), header_color=NAVY))

    doc.build(s)
    return OUT_PATH


if __name__ == "__main__":
    out = build()
    print(f"Wrote {out}")
