"""Render the NAPCO Nucleus presentation Study Guide as a PDF.

Card-based, colorful, scannable layout. Same design language as the
architecture PDF.

Read this 3 times before presenting. Everything you need to answer
hard questions confidently is in here.

Run:
    py -3 scripts/generate_study_guide.py
Output:
    docs/Presentation-Study-Guide.pdf
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
    Spacer,
    Table,
    TableStyle,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT_PATH = ROOT / "docs" / "Presentation-Study-Guide.pdf"

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# Brand palette (matches architecture PDF)
NAVY    = colors.HexColor("#1F4E79")
TEAL    = colors.HexColor("#2E8A8A")
CORAL   = colors.HexColor("#E07856")
GREEN   = colors.HexColor("#4A7A4A")
GOLD    = colors.HexColor("#C9962B")
PURPLE  = colors.HexColor("#6A4C93")
INK     = colors.HexColor("#222222")
MUTED   = colors.HexColor("#6B7785")
SOFT    = colors.HexColor("#F5F7FA")
WHITE   = colors.white
RULE    = colors.HexColor("#D5DCE5")
HIGHLIGHT = colors.HexColor("#FFF8E1")  # soft yellow for callouts

TITLE = ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=24, leading=28,
                       textColor=NAVY, alignment=TA_LEFT, spaceAfter=2)
SUBTITLE = ParagraphStyle("Subtitle", fontName="Helvetica", fontSize=12, leading=15,
                          textColor=MUTED, alignment=TA_LEFT, spaceAfter=4)
BYLINE = ParagraphStyle("Byline", fontName="Helvetica-Bold", fontSize=10, leading=13,
                        textColor=NAVY, alignment=TA_LEFT, spaceAfter=10)
CARD_HEAD = ParagraphStyle("CardHead", fontName="Helvetica-Bold", fontSize=11, leading=14,
                           textColor=WHITE, alignment=TA_LEFT)
CARD_BODY = ParagraphStyle("CardBody", fontName="Helvetica", fontSize=9.5, leading=13,
                           textColor=INK, alignment=TA_LEFT, spaceAfter=4)
BULLET = ParagraphStyle("Bullet", fontName="Helvetica", fontSize=9.5, leading=13,
                        textColor=INK, leftIndent=10, bulletIndent=0, spaceAfter=3)
QUOTE = ParagraphStyle("Quote", fontName="Helvetica-Oblique", fontSize=10.5, leading=14,
                       textColor=NAVY, alignment=TA_LEFT, leftIndent=4, spaceAfter=6)
QA_Q = ParagraphStyle("QA_Q", fontName="Helvetica-Bold", fontSize=10, leading=13,
                      textColor=NAVY, alignment=TA_LEFT, spaceAfter=2)
QA_A = ParagraphStyle("QA_A", fontName="Helvetica", fontSize=9.5, leading=13,
                      textColor=INK, alignment=TA_LEFT, spaceAfter=8, leftIndent=10)
NUMBER_BIG = ParagraphStyle("NumBig", fontName="Helvetica-Bold", fontSize=22, leading=24,
                            textColor=NAVY, alignment=TA_CENTER)
NUMBER_LBL = ParagraphStyle("NumLbl", fontName="Helvetica", fontSize=8, leading=10,
                            textColor=MUTED, alignment=TA_CENTER)


def _on_page(canvas: canvas_mod.Canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - 4, PAGE_W, 4, stroke=0, fill=1)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN, 8 * mm,
                      "Study Guide  |  Mohammad Kamrul Hasan, AI-Augmented QA Architect")
    canvas.drawRightString(PAGE_W - MARGIN, 8 * mm, f"page {doc.page}")
    canvas.restoreState()


def card(header_text: str, body_flowables, header_color=NAVY, body_bg=WHITE) -> Table:
    if not isinstance(body_flowables, list):
        body_flowables = [body_flowables]
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
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, RULE),
    ]))
    return inner


def metric_box(value, label, color):
    t = Table([[Paragraph(value, NUMBER_BIG)], [Paragraph(label, NUMBER_LBL)]],
              rowHeights=[16 * mm, 6 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT),
        ("LINEABOVE", (0, 0), (-1, 0), 3, color),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def metrics_row(items):
    cells = [metric_box(v, l, c) for v, l, c in items]
    n = len(cells)
    col_w = (CONTENT_W - (n - 1) * 4) / n
    t = Table([cells], colWidths=[col_w] * n)
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def qa_pair(q: str, a: str) -> list:
    return [Paragraph(f"Q. {q}", QA_Q), Paragraph(a, QA_A)]


def build():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT_PATH), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 4, bottomMargin=MARGIN,
        title="NAPCO Nucleus Study Guide",
        author="Mohammad Kamrul Hasan",
    )
    frame = Frame(MARGIN, MARGIN, CONTENT_W, PAGE_H - 2 * MARGIN - 4,
                  id="main", showBoundary=0,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="Default", frames=[frame], onPage=_on_page)])

    s: list = []

    # ── Title block
    s.append(Paragraph("Study Guide", TITLE))
    s.append(Paragraph("Read this 3 times before you walk in", SUBTITLE))
    s.append(Paragraph(
        "Mohammad Kamrul Hasan &nbsp;&middot;&nbsp; AI-Augmented QA Architect "
        "&nbsp;&middot;&nbsp; April 2026",
        BYLINE,
    ))

    # ── Audience card
    s.append(card("YOUR AUDIENCE", [
        Paragraph(
            "Your team and your boss have <b>heard</b> about AI agents. They have not "
            "<b>seen</b> one work in practice on real company data. That gap is your opening. "
            "They walk in skeptical or curious. You need them to walk out thinking "
            "<i>we have one of these now, and Mohammad built it.</i>",
            CARD_BODY,
        ),
        Spacer(1, 4),
        Paragraph(
            "<b>Lead with working software, not theory.</b> First thing they should see is "
            "the agent doing something visible whose result is verifiable in our actual "
            "systems (GitLab, email inbox, memory DB). Theory comes after.",
            CARD_BODY,
        ),
    ], header_color=NAVY))
    s.append(Spacer(1, 6))

    # ── Opening line card
    s.append(card("YOUR OPENING LINE", Paragraph(
        '"You have all heard about AI agents this past year. The Anthropic and OpenAI '
        'announcements, the demos, the LinkedIn posts. Tonight you are going to see one '
        'running on our infrastructure, on our data, doing real work for our team. Not a '
        'slide deck about what AI might do. A working agent that filed thirteen real '
        'client requirements into our GitLab backlog this morning, from emails and meeting '
        'recordings, while we slept. I am Mohammad. I am a QA architect by trade. I designed '
        'and shipped this end-to-end by directing AI through Claude Code. Let me show you '
        'what that looks like."',
        QUOTE,
    ), header_color=CORAL))
    s.append(Spacer(1, 6))

    # ── Thesis card
    s.append(card("THE THESIS YOU ARE PROVING", [
        Paragraph(
            '<i>"A QA architect who knows how to direct AI now ships production '
            'infrastructure that previously required a senior developer team. This is not '
            'a marginal productivity gain. It is a different kind of professional. NAPCO '
            'Nucleus is the proof."</i>',
            QUOTE,
        ),
        Spacer(1, 4),
        Paragraph(
            "Stay on this thesis the entire talk. Every demo step, every architecture "
            "choice, every hard answer anchors back to it. <b>QA architect plus AI equals "
            "senior dev team output.</b>",
            CARD_BODY,
        ),
    ], header_color=PURPLE, body_bg=HIGHLIGHT))

    s.append(PageBreak())

    # ── Numbers to know cold
    s.append(card("NUMBERS TO KNOW COLD", Paragraph(
        "If asked any of these, answer instantly without looking down.",
        CARD_BODY,
    ), header_color=NAVY))
    s.append(Spacer(1, 4))
    s.append(metrics_row([
        ("9",     "WORKFLOWS",       NAVY),
        ("31",    "MCP TOOLS",       TEAL),
        ("4",     "TESTS AT 2AM",    CORAL),
        ("2",     "DAILY EMAILS",    GREEN),
        ("$200",  "PER MONTH",       GOLD),
    ]))
    s.append(Spacer(1, 8))

    # ── Architecture in one paragraph
    s.append(card("ARCHITECTURE IN ONE PARAGRAPH (memorize this)", Paragraph(
        "NAPCO Nucleus is an AI agent built on the Claude Agent SDK that runs as nine "
        "scheduled GitHub Actions workflows on a self-hosted Windows runner. It serves "
        "two operational dimensions for the MVP Access engineering org: <b>Project "
        "Management</b> (ingest client requirements from email and Drive recordings, "
        "split into 3-hour tasks, publish to GitLab with two-layer dedup) and <b>Test "
        "Automation</b> (orchestrate the 4 test suites at 02:00 BDT every night, then "
        "ship two consolidated emails the next morning at 09:00 and 09:30). Reasoning "
        "runs on the local Claude Code CLI under a Claude Max subscription. State persists "
        "in a committed SQLite database with FTS5. 31 MCP tools are exposed. Real production "
        "deployment, not a prototype.",
        CARD_BODY,
    ), header_color=TEAL))
    s.append(Spacer(1, 6))

    # ── Engineering decisions
    s.append(card("THE 6 ENGINEERING DECISIONS (each with a why)", [
        Paragraph("•&nbsp;&nbsp;<b>Claude Max via local CLI, not API key.</b> Reasoning is essentially free at the margin. Eight scheduled workflows fire 30 times a day. On the API that would be real money. Fixed monthly cost wins clearly at our scale.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>Algorithms in prompts, not Python.</b> Tools wrap I/O only. Classification, summarization, regression analysis happen in markdown that Claude executes. Behavior changes by editing markdown, not Python.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>Memory committed to git.</b> SQLite + FTS5 in the repo. Clone the project, you have the agent's full history. Disaster recovery is git clone. Zero infrastructure to provision.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>Self-hosted runner.</b> Direct access to staging behind VPN, direct access to TFS, direct access to IIS UNC paths. None reachable from a hosted runner without complex tunneling. Secrets stay on our infra.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>One Claude turn per process.</b> agent.py loads, runs ONE turn, exits. Clean process isolation. Memory is the explicit connection between turns.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>Two consolidated emails per day, not one per workflow.</b> 09:00 BDT detailed test report to the team. 09:30 BDT executive summary to leadership. Higher signal-to-noise than six fragments scattered across the night.", BULLET),
    ], header_color=GREEN))

    s.append(PageBreak())

    # ── 9 workflows table
    s.append(card("THE 9 WORKFLOWS (know each one)", Paragraph(
        "All 4 tests fire at 02:00 BDT. Reports go out at 09:00 and 09:30 BDT.",
        CARD_BODY,
    ), header_color=CORAL))
    s.append(Spacer(1, 4))
    wf_data = [
        ["#", "Workflow", "Schedule", "What it does"],
        ["1", "API Functional Test", "02:00 BDT", "Newman / Postman across the API surface."],
        ["2", "API Integration Test", "02:00 BDT", "pytest with regression diff."],
        ["3", "API Load Test", "02:00 BDT", "Locust 5 tiers, 10 to 10K users with cooldowns."],
        ["4", "MVP Access E2E Test", "02:00 BDT", "Playwright full suite. Screenshots on failure."],
        ["5", "Daily Report Detailed", "09:00 BDT", "4-test detailed PDF to the FULL TEAM."],
        ["6", "Daily Report Summary", "09:30 BDT", "6-block dashboard to LEADERSHIP."],
        ["7", "Requirement Management", "Every 2h biz hrs", "IMAP + Drive ingest. Files in GitLab."],
        ["8", "MVPAccess CICD", "22:00 BDT", "TFS pull, MSBuild, IIS deploy via UNC."],
        ["9", "Probe Runner Filesystem", "Manual", "Diagnostic for runner triage."],
    ]
    col_widths = [7 * mm, 40 * mm, 28 * mm, 105 * mm]
    tbl = Table(wf_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, SOFT]),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
    ]))
    s.append(tbl)

    s.append(Spacer(1, 8))

    # ── Vocabulary
    s.append(card("VOCABULARY (use these words confidently)", [
        Paragraph("•&nbsp;&nbsp;<b>MCP</b>: Model Context Protocol. Anthropic's spec for tool integration. Each NN tool is wrapped with @tool() and registered with the MCP server. The Claude CLI discovers and calls them.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>Claude Agent SDK</b>: Anthropic's Python library for building agents. ClaudeAgentOptions, ClaudeSDKClient, create_sdk_mcp_server.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>FTS5</b>: SQLite full-text search. Enables fuzzy matching so 'add SSO to staging' is caught as a duplicate of 'staging Azure SSO integration'.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>Self-hosted runner</b>: A GitHub Actions runner installed on your own machine. Required for access to private resources (staging, TFS, IIS) that hosted runners cannot reach.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>Idempotency / dedup</b>: Running the same operation twice has the same effect as once. NN's requirement-management is idempotent via two-layer check: title-match against open issues plus FTS5 fuzzy-match against requirements_seen.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>Whisper</b>: Speech-to-text. NN uses Groq's Whisper API to transcribe meeting recordings dropped in the Drive folder.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>Override semantics</b>: load_dotenv(override=True) means values in .env take precedence over inherited shell env. Local .env beats stale GHA secret values.", BULLET),
    ], header_color=GOLD))

    s.append(PageBreak())

    # ── Hard Q&A part 1
    s.append(card("HARD QUESTIONS - PART 1 (rehearse out loud)", [
        *qa_pair(
            "Did you write all this Python yourself? Are you really a developer?",
            "I am a QA architect, not a developer by trade. That is the whole point of "
            "NAPCO Nucleus. I designed the system: every workflow, every prompt, every "
            "architectural decision, every trade-off. The Python implementation was "
            "AI-assisted. I directed Claude through Claude Code CLI to write the code "
            "under my specs. That is the new model. A QA architect who directs AI ships "
            "production infrastructure that previously required a senior dev team. The "
            "GitLab issues are real. The reports are real. The deploy pipeline is real. "
            "They exist because I built the system. The language they are written in "
            "happens to be Python via AI partnership."
        ),
        *qa_pair(
            "Why not just use GitHub Copilot, Cursor, or ChatGPT?",
            "Those are interactive coding assistants. A human types, the AI suggests. "
            "NN is the opposite. It runs unattended on a schedule, reads its own state "
            "from memory, takes actions, ships artifacts. No human in the loop per run. "
            "Different tool category."
        ),
        *qa_pair(
            "What if the AI makes a mistake? Wrong classification, wrong issue title?",
            "Two layers protect us. First, every action is auditable: activity_logs in "
            "memory, GHA run logs, git commits, GitLab issue history. We can trace what "
            "the agent did and why. Second, mutating tools (publish_tasks_to_gitlab, "
            "send_email_report) all support a dry_run mode. We use dry-run extensively "
            "in development. Mistakes happen but they are visible and reversible."
        ),
        *qa_pair(
            "How much does this cost?",
            "About $200 per month for the Claude Max subscription. Fixed regardless of "
            "how many times the agent runs. Self-hosted runner is on existing hardware, "
            "zero added cost. Groq Whisper is metered but cheap. GitLab and Google use "
            "existing seats. Compared to API-key billing where 30 daily runs would cost "
            "meaningfully more, the Claude Max model wins clearly at our scale."
        ),
    ], header_color=PURPLE))

    s.append(PageBreak())

    # ── Hard Q&A part 2
    s.append(card("HARD QUESTIONS - PART 2", [
        *qa_pair(
            "Is our data safe? Where does it go?",
            "Emails read from our Gmail via IMAP (app password we control). Drive "
            "recordings transcribed via Groq (audio sent, transcript returned, audio "
            "not retained per their policy). Text reasoning sent to Anthropic via the "
            "Claude CLI under our Max subscription terms. Memory database stays on our "
            "self-hosted runner and in our git repo. Nothing leaves our control except "
            "for the LLM reasoning calls and audio transcription. Both are commercial "
            "subscriptions with explicit data-handling terms."
        ),
        *qa_pair(
            "What happens if Claude is down?",
            "The workflow fails cleanly with the API error message logged to GHA. The "
            "next scheduled run picks up where the failed one left off because memory "
            "is checkpoint-based. Daily Report degrades gracefully: if it cannot compose "
            "a fresh executive summary, it sends a shorter status email noting the outage."
        ),
        *qa_pair(
            "Why not a deterministic Python script instead of an AI?",
            "We had one. 1,961 lines of regex heuristics and hardcoded if-else trees in "
            "tools_legacy.py. Maintaining it meant editing Python every time a new failure "
            "pattern appeared. The new design moves classification into prompts. New failure "
            "category? Markdown edit, no code review. The agent also does things "
            "deterministic code cannot: reading a 30-page meeting transcript and extracting "
            "actionable requirements."
        ),
        *qa_pair(
            "How do you debug it when something goes wrong?",
            "Three levels. (1) GHA UI shows every workflow run with full stdout and "
            "stderr. (2) memory.recall_activity() lets me query what the agent did in "
            "the last X hours for task Y. (3) prompts/ are version-controlled markdown. "
            "I can read exactly what Claude was instructed to do at any point in history."
        ),
    ], header_color=PURPLE))

    s.append(PageBreak())

    # ── Hard Q&A part 3
    s.append(card("HARD QUESTIONS - PART 3", [
        *qa_pair(
            "What if the agent runs in a loop or runs up costs?",
            "Three guardrails. (1) GHA workflow timeouts (15-60 min per workflow). "
            "(2) Tool descriptions explicitly say AT MOST ONCE per run for expensive "
            "operations. (3) Claude Max is fixed monthly cost, so a runaway loop cannot "
            "surprise us with a bill."
        ),
        *qa_pair(
            "Can you explain why the agent made a particular decision?",
            "Yes. Every Claude turn is logged by GHA (full reasoning trace plus tool call "
            "sequence). Every tool call's args and result are in activity_logs. For any "
            "GitLab issue NN created, I can show you the original email or transcript text, "
            "the prompt that asked Claude to split it, and the JSON of tasks Claude proposed."
        ),
        *qa_pair(
            "How do you know it is doing useful work and not theater?",
            "Concrete proof: 13 GitLab issues created today from email plus meeting "
            "recordings, each linked back to source. 27 backend test failures classified "
            "into known-bug, regression, flaky, data-issue buckets. The load test surfaced "
            "staging strain at 100 users, a real performance signal we acted on. None of "
            "these are demoware. They are in our actual GitLab and our actual reports."
        ),
        *qa_pair(
            "What is still rough?",
            "Three things. (1) The GHA self-hosted runner currently runs as a Windows "
            "user that cannot see the sibling test project trees. A permission fix is "
            "needed. (2) The CICD workflow needs IT to add 6 secrets (TFS plus IIS) before "
            "it can actually deploy. The YAML is production-ready, the credentials are "
            "not there. (3) E2E test stability. Playwright is sensitive to timing on "
            "staging. We have flaky tests we are working through. Roadmap addresses all three."
        ),
    ], header_color=PURPLE))

    s.append(PageBreak())

    # ── How to look credible
    s.append(card("HOW TO LOOK CREDIBLE - PRESENTATION TACTICS", [
        Paragraph("•&nbsp;&nbsp;<b>Pre-flight 30 minutes before.</b> Open the terminal. Have nucleus_memory.db open in DB Browser. Have GitHub repo, GitLab project, Drive folder in browser tabs.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>Narrate while live tools run.</b> 'It is polling IMAP first... now downloading from Drive... now Claude is splitting this email into three tasks...' Silent waiting feels broken; narrated waiting feels like a tour.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>If something breaks, name it immediately.</b> 'OK this just failed because X. Watch what the agent does. See how it logs the error to memory and exits cleanly?' Failure handled openly is MORE credible than a perfect demo.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>Pause 2 seconds before answering hard questions.</b> Looks thoughtful, not slow. Then name the trade-off: 'Good question. We considered Y and chose X because of Z.'", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>Refer to files by name.</b> 'That is in tools/_shared.py at line 50.' Not 'somewhere in the codebase'. Specificity equals mastery.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>If you do not know, say 'let me check'.</b> Open the file, look it up. Far better than guessing.", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>Concrete before abstract.</b> 'Here are 13 GitLab issues NN created today.' Then: 'Now let me show you HOW.'", BULLET),
        Paragraph("•&nbsp;&nbsp;<b>End with the ask.</b> If you want IT to grant runner permissions, DevOps to add CICD secrets, or your boss to approve Claude Max as a line item, say so explicitly in the closing 30 seconds.", BULLET),
    ], header_color=TEAL))
    s.append(Spacer(1, 6))

    # ── One-line for the boss
    s.append(card("THE ONE LINE FOR THE BOSS", Paragraph(
        '"NAPCO Nucleus is an AI agent I architected for the MVP Access team. It reads '
        'our client emails and meeting recordings every two hours, files them as tasks in '
        'GitLab, runs our test suites every night at 02:00, classifies the failures, and '
        'emails two consolidated reports each morning. Built on Claude. Runs on our own '
        'hardware. Costs about two hundred dollars a month flat. Created thirteen real '
        'tasks from this morning\'s inbox while we slept. I designed it. AI implemented '
        'it under my direction. This is what a QA architect can ship now."',
        QUOTE,
    ), header_color=NAVY, body_bg=HIGHLIGHT))

    doc.build(s)
    return OUT_PATH


if __name__ == "__main__":
    out = build()
    print(f"Wrote {out}")
