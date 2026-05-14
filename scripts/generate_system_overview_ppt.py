"""NAPCO Nucleus — end-to-end system-overview deck.

Stakeholder-facing explainer of how Nucleus works today, after the
2026-05-14 move of the central host from Windows MVPACCESS (.209) to
the Ubuntu 24.04 box at .123. 14 slides, 16:9, terse on the slide
itself so the boss drives narration. Speaker notes carry the detail.

Self-contained: every helper that the deck needs is in this file,
matching the convention of the other generators in scripts/.

Run:
    python scripts\\generate_system_overview_ppt.py
Output:
    docs\\NAPCO-Nucleus-System-Overview.pptx
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
OUT = ROOT / "docs" / "NAPCO-Nucleus-System-Overview.pptx"

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)

# Palette — match docs/NAPCO-Nucleus-Presentation.pptx
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
    conn = slide.shapes.add_connector(2, x1, y1, x2, y2)  # 2 = STRAIGHT
    conn.line.color.rgb = color
    conn.line.width = Pt(width_pt)
    return conn


def base_slide(prs, title_text, subtitle_text=None):
    blank = prs.slide_layouts[6]
    s = prs.slides.add_slide(blank)
    # Top accent bar
    add_rect(s, Inches(0), Inches(0), SLIDE_W, Inches(0.18), fill_color=NAVY)
    # Title
    tf = add_textbox(s, Inches(0.6), Inches(0.35), Inches(12), Inches(0.7))
    set_text(tf, title_text, size=28, bold=True, color=NAVY)
    if subtitle_text:
        add_para(tf, subtitle_text, size=14, color=MUTED, space_before=2)
    # Footer rule
    add_rect(s, Inches(0.6), Inches(7.05), Inches(12.1), Inches(0.02), fill_color=RULE)
    return s


def set_speaker_notes(slide, text):
    notes = slide.notes_slide.notes_text_frame
    notes.clear()
    p = notes.paragraphs[0]
    p.text = text


def add_chip(slide, x, y, w, h, text, color, font_size=11):
    """Small pill with white text used for role labels."""
    rect = add_rect(slide, x, y, w, h, fill_color=color, rounded=True)
    tf = rect.text_frame
    set_text(tf, text, size=font_size, bold=True, color=WHITE,
             align=PP_ALIGN.CENTER)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    return rect


def add_box(slide, x, y, w, h, title, lines, accent=NAVY,
            title_size=14, body_size=11):
    """Title-bar + content box used for the architecture diagrams."""
    container = add_rect(slide, x, y, w, h, fill_color=WHITE, line_color=RULE)
    # accent stripe on left
    add_rect(slide, x, y, Inches(0.08), h, fill_color=accent)
    tf = add_textbox(slide, x + Inches(0.18), y + Inches(0.1),
                     w - Inches(0.25), h - Inches(0.2))
    set_text(tf, title, size=title_size, bold=True, color=accent)
    for ln in lines:
        add_para(tf, ln, size=body_size, color=INK, space_before=2)
    return container


# ── slides ─────────────────────────────────────────────────────────

def slide_title(prs):
    s = prs.slide_layouts[6]
    s = prs.slides.add_slide(s)
    add_rect(s, Inches(0), Inches(0), SLIDE_W, SLIDE_H, fill_color=NAVY)
    tf = add_textbox(s, Inches(0.8), Inches(2.3), Inches(11.7), Inches(1.5))
    set_text(tf, "NAPCO Nucleus", size=58, bold=True, color=WHITE)
    add_para(tf, "How It Works", size=34, color=WHITE)
    tf2 = add_textbox(s, Inches(0.8), Inches(4.4), Inches(11.7), Inches(1.4))
    set_text(tf2, "From Teams call to client requirement, hands-off.",
             size=20, color=RGBColor(0xC8, 0xD2, 0xE0))
    tf3 = add_textbox(s, Inches(0.8), Inches(6.7), Inches(11.7), Inches(0.5))
    set_text(tf3, "2026-05-14   |   Adaptive Enterprise / NAPCO labs",
             size=12, color=RGBColor(0x9C, 0xAB, 0xBE))
    set_speaker_notes(s, (
        "Set the frame. Nucleus is the system that takes everything the "
        "team says, types, mails or shares with a client over the course "
        "of a day, and -- with one human review step -- produces a "
        "verification email back to the client confirming what we heard. "
        "It runs hands-off; the developers don't change their workflow. "
        "Today is 2026-05-14 -- the day the central host moved from the "
        "Windows MVPACCESS box to a Linux docker stack on .123. The deck "
        "explains the whole pipeline end-to-end."
    ))


def slide_cast(prs):
    s = base_slide(prs, "The cast",
                   "One client. Seven developers. One central pipeline.")

    # Client column on the left
    tf = add_textbox(s, Inches(0.8), Inches(1.7), Inches(4.0), Inches(0.5))
    set_text(tf, "Client", size=14, bold=True, color=MUTED)
    add_chip(s, Inches(0.8), Inches(2.3), Inches(3.8), Inches(0.9),
             "Salman", CORAL, font_size=20)

    # Pipeline pill in the middle
    add_chip(s, Inches(5.4), Inches(3.7), Inches(2.5), Inches(0.7),
             "Nucleus", NAVY, font_size=16)

    # Devs column on the right
    tf2 = add_textbox(s, Inches(8.7), Inches(1.7), Inches(4.0), Inches(0.5))
    set_text(tf2, "Developers (7)", size=14, bold=True, color=MUTED)
    devs = ["Assad", "Rocky", "Ferdows", "Titu", "Atik", "Isruk", "Amin"]
    for i, d in enumerate(devs):
        row, col = divmod(i, 2)
        x = Inches(8.7 + col * 2.0)
        y = Inches(2.3 + row * 0.75)
        add_chip(s, x, y, Inches(1.8), Inches(0.6), d, NAVY, font_size=14)

    # Faint arrows to the pipeline
    add_arrow(s, Inches(4.6), Inches(2.75),
              Inches(5.4), Inches(4.0), color=CORAL, width_pt=2)
    for i in range(7):
        row, col = divmod(i, 2)
        x_from = Inches(8.7 + col * 2.0)
        y_from = Inches(2.6 + row * 0.75)
        add_arrow(s, x_from, y_from, Inches(7.9), Inches(4.0),
                  color=NAVY, width_pt=1.0)

    # Caption
    tf3 = add_textbox(s, Inches(0.8), Inches(5.6), Inches(11.7), Inches(1.4))
    set_text(tf3,
             "Every dev's Teams calls, chats, emails and shared files "
             "feed the same place. One pass per day stitches them back "
             "into one verification email.",
             size=14, color=MUTED)
    set_speaker_notes(s, (
        "Today the active roster is Salman as the client and seven "
        "developers on our side -- Assad, Rocky, Ferdows, Titu, Atik, "
        "Isruk, and Amin. Each developer has their own conversations "
        "with Salman across Teams calls, Teams chats, email threads, "
        "and the shared Google Drive folder. None of those developers "
        "hears the whole picture; we used to lose requirements in the "
        "gaps. Nucleus is the answer to that fragmentation: every "
        "channel from every dev flows into one central pipeline, and "
        "the daily run reconciles them into a single artefact."
    ))


def slide_four_channel_flow(prs):
    s = base_slide(prs, "The four-channel flow",
                   "CAPTURE everywhere. IDENTIFY once. VERIFY by hand. DELIVER.")

    # Top row: four capture sources
    sources = [
        ("Teams chat", TEAL),
        ("Teams calls", PURPLE),
        ("Email", CORAL),
        ("Drive", GOLD),
    ]
    src_y = Inches(1.6)
    src_w = Inches(2.6)
    gap = Inches(0.3)
    total_w = 4 * 2.6 + 3 * 0.3
    src_x0 = (13.333 - total_w) / 2
    for i, (name, color) in enumerate(sources):
        x = Inches(src_x0 + i * (2.6 + 0.3))
        add_chip(s, x, src_y, src_w, Inches(0.7), name, color, font_size=16)

    # Down arrows into CAPTURE bar
    for i in range(4):
        x = Inches(src_x0 + i * (2.6 + 0.3) + 1.3)
        add_arrow(s, x, Inches(2.4), x, Inches(2.9),
                  color=MUTED, width_pt=1.5)

    # The four-stage pipeline
    stages = [
        ("CAPTURE", TEAL,
         "Voice daemon, chat-push, Gmail IMAP, Drive watcher."),
        ("IDENTIFY", PURPLE,
         "verify_session reads the whole day, scopes per client."),
        ("VERIFY", GOLD,
         "Human reviews the Gmail draft, edits if needed."),
        ("DELIVER", GREEN,
         "Send. Reply gets parsed back through tools.poll_replies."),
    ]
    pipe_y = Inches(2.95)
    pipe_h = Inches(1.4)
    pipe_w = Inches(2.85)
    pipe_gap = Inches(0.2)
    total_pw = 4 * 2.85 + 3 * 0.2
    pipe_x0 = (13.333 - total_pw) / 2
    for i, (name, color, sub) in enumerate(stages):
        x = Inches(pipe_x0 + i * (2.85 + 0.2))
        add_box(s, x, pipe_y, pipe_w, pipe_h, name, [sub],
                accent=color, title_size=18, body_size=11)
        if i < 3:
            x_arr = Inches(pipe_x0 + i * (2.85 + 0.2) + 2.85)
            add_arrow(s, x_arr, Inches(2.95 + 1.4 / 2),
                      x_arr + Inches(0.2), Inches(2.95 + 1.4 / 2),
                      color=NAVY, width_pt=2.5)

    # Bottom annotation
    tf = add_textbox(s, Inches(0.8), Inches(5.4), Inches(11.7), Inches(1.6))
    set_text(tf, "One client requirement can span multiple developers "
                 "and multiple channels.", size=15, bold=True, color=NAVY)
    add_para(tf,
             "Half a feature mentioned on a Teams call with Rocky, the "
             "rest typed into an email reply to Atik. Without a single "
             "reconciliation pass, no one ever sees the whole thing.",
             size=13, color=MUTED, space_before=6)
    set_speaker_notes(s, (
        "Four capture channels, all feeding the same identification pass. "
        "Teams chat is pushed by a per-dev cron in three BD-local windows "
        "across the day. Teams calls come in via the voice daemon on each "
        "dev PC. Email is pulled by IMAP on the central host every 15 "
        "minutes. Drive is pulled by a Drive watcher on the central host "
        "every 15 minutes. Once captured, IDENTIFY happens ONCE per day "
        "-- not five times, not seven times -- because cross-developer "
        "fragments only resolve when the model can see them all together. "
        "VERIFY is the human-in-the-loop gate: the boss reviews the Gmail "
        "draft and clicks send. DELIVER is the round trip -- when Salman "
        "replies, the reply gets parsed back into the pipeline so the "
        "next day's identification knows what's already confirmed."
    ))


def slide_voice_capture(prs):
    s = base_slide(prs, "Voice capture on each dev PC",
                   "Auto-trigger on Teams audio. No wake word needed.")

    # Left: the trigger
    add_box(s, Inches(0.5), Inches(1.5), Inches(5.8), Inches(5.3),
            "voice_daemon.py (per dev PC)", [
                "Watches MS Teams audio-session state via pycaw.",
                "  -> session becomes Active  =>  start recording",
                "  -> session ends            =>  stop recording",
                "",
                "No verbal phrase needed in `auto` mode.",
                "Wake words still accepted as an early-stop shortcut",
                "  (\"nucleus stop\", \"Allah Hafez\", ...).",
                "",
                "Records two WAV tracks:",
                "  - mic.wav      (your voice)",
                "  - speaker.wav  (their voice via WASAPI loopback)",
            ], accent=TEAL, title_size=15, body_size=12)

    # Right: post-processing
    add_box(s, Inches(6.6), Inches(1.5), Inches(6.2), Inches(5.3),
            "Post-record pipeline (on stop)", [
                "1. Comb-notch denoise at 50 Hz + harmonics.",
                "      removes mains hum from cheap USB cards.",
                "",
                "2. Peak normalize mic.wav to -1 dBFS.",
                "      consistent loudness for Whisper.",
                "",
                "3. Drop calls under 20 seconds.",
                "      ringtone-only / accidental triggers.",
                "",
                "4. Hard cap at 1 hour per recording.",
                "      guards against a stuck audio-session state.",
                "",
                "5. Resolve client via Teams IndexedDB.",
                "      every WAV lands self-labeled.",
                "",
                "6. Copy to central share with metadata sidecar.",
            ], accent=GREEN, title_size=15, body_size=12)
    set_speaker_notes(s, (
        "Each developer runs the voice daemon at the start of the day "
        "from start-daemon.bat. The daemon's auto mode -- which is the "
        "default since the 2026-05-13 change -- watches Teams' audio "
        "session via pycaw. The instant Teams starts producing audio "
        "(call ringing counts), recording begins; the instant Teams' "
        "session ends, recording stops. The developers don't have to "
        "say anything special. Post-processing strips mains hum at 50 "
        "Hz and its harmonics, normalizes the mic track so Whisper sees "
        "consistent levels, and drops anything under 20 seconds as "
        "almost certainly an accidental ring-and-drop. The hard 1-hour "
        "cap prevents one stuck audio session from filling the share "
        "with junk. The IndexedDB resolver was the trick we shipped in "
        "April -- it auto-tags every recording with the client name so "
        "the central pipeline can scope per client without anyone "
        "labeling manually."
    ))


def slide_where_call_lands(prs):
    s = base_slide(prs, "Where the call lands",
                   "Samba share on .123. One folder per dev, per day.")

    # Left: dev PC chip
    add_chip(s, Inches(0.6), Inches(2.6), Inches(2.6), Inches(1.0),
             "Dev PC\n(voice_daemon)", TEAL, font_size=14)

    # Arrow
    add_arrow(s, Inches(3.3), Inches(3.1), Inches(5.3), Inches(3.1),
              color=NAVY, width_pt=3)
    tf_lbl = add_textbox(s, Inches(3.3), Inches(2.5), Inches(2.0), Inches(0.5))
    set_text(tf_lbl, "SMB / Samba", size=12, bold=True,
             color=NAVY, align=PP_ALIGN.CENTER)
    tf_lbl2 = add_textbox(s, Inches(3.3), Inches(3.3), Inches(2.0), Inches(0.5))
    set_text(tf_lbl2, "(port 445)", size=10, color=MUTED, align=PP_ALIGN.CENTER)

    # Right: central tree
    add_box(s, Inches(5.4), Inches(1.5), Inches(7.4), Inches(5.3),
            r"\\172.16.205.123\nucleus-central\\", [
                r"    salman\\2026-05-14\\",
                "        calls\\",
                "            20260514-100432_mic.wav",
                "            20260514-100432_speaker.wav",
                "            20260514-100432_transcript.md",
                "            20260514-100432.json     (metadata)",
                "        chat\\",
                "            chat_2026-05-14_1000-1015.docx",
                "        email\\        (staged on .123)",
                "        drive\\        (staged on .123)",
                "    rocky\\2026-05-14\\",
                "        calls\\ ...",
                "    isruk\\2026-05-14\\",
                "        ...",
                "",
                "metadata.client_name comes from the IndexedDB resolver.",
                "collect_central uses substring match on this field",
                "to scope by client.",
            ], accent=PURPLE, title_size=13, body_size=11)
    set_speaker_notes(s, (
        "The Samba container on .123 serves the same UNC path that the "
        "old MVPACCESS share served. Every dev PC has it mapped at "
        "boot. After a call ends and the post-record steps complete, "
        "the daemon copies the mic, speaker, and metadata files into "
        "the dev's day folder over SMB. The transcript .md gets written "
        "later by the transcribe worker on .123 once Groq finishes "
        "processing the WAVs. The layout is the load-bearing convention "
        "for the whole pipeline -- everything downstream is just a walk "
        "of this tree filtered by date and client name."
    ))


def slide_central_host(prs):
    s = base_slide(prs, "The .123 Linux central host",
                   "Ubuntu 24.04. Six containers. One docker-compose stack.")

    # Header strip with host path
    tf = add_textbox(s, Inches(0.6), Inches(1.4), Inches(12.2), Inches(0.5))
    set_text(tf, "/home/ubuntu/napco-nucleus/deploy/linux-central/",
             size=13, color=MUTED, font="Consolas")

    # Six containers in two rows of three
    containers = [
        ("nucleus-samba", TEAL,
         "Serves SMB share to dev PCs.\nHost network mode (port 445)."),
        ("nucleus-transcribe", PURPLE,
         "Loop: walks /data for new calls.\nGroq first, faster-whisper fallback."),
        ("nucleus-stage-email", CORAL,
         "15-min cadence.\nGmail IMAP -> per-dev /email/ folders."),
        ("nucleus-stage-drive", GOLD,
         "15-min cadence.\nDrive folder -> per-dev /drive/ folders."),
        ("nucleus-daily-draft", GREEN,
         "Fires at BD 23:45.\nRuns collect_central.py --client all."),
        ("nucleus-gha-runner", NAVY,
         "Org-scoped self-hosted runner.\nLabels: linux, nucleus-central."),
    ]
    col_w = Inches(4.05)
    col_h = Inches(2.0)
    col_gap = Inches(0.15)
    x0 = Inches(0.5)
    y0 = Inches(2.0)
    for i, (name, color, body) in enumerate(containers):
        row, col = divmod(i, 3)
        x = x0 + col * (col_w + col_gap)
        y = y0 + Inches(row * 2.15)
        add_box(s, x, y, col_w, col_h, name, body.split("\n"),
                accent=color, title_size=14, body_size=11)

    # Bind-mounts strip at the bottom
    tf2 = add_textbox(s, Inches(0.6), Inches(6.35), Inches(12.2), Inches(0.7))
    set_text(tf2, "Bind mounts:", size=12, bold=True, color=NAVY)
    add_para(tf2,
             "/srv/nucleus-central  -> /data/nucleus-central     "
             "(everyone shares this dir, Samba serves it)",
             size=11, color=INK, font="Consolas", space_before=1)
    add_para(tf2,
             "/srv/nucleus-data     -> /app/data                 "
             "(writable overlay of repo's data/, holds session docs + locks)",
             size=11, color=INK, font="Consolas", space_before=1)
    add_para(tf2,
             "nucleus-state (vol)   -> /state                    "
             "(sqlite memory db; survives `compose down`)",
             size=11, color=INK, font="Consolas", space_before=1)
    add_para(tf2,
             "/home/ubuntu/.claude  -> /root/.claude  (read-only) "
             "(Claude Max-tier auth, every worker inherits)",
             size=11, color=INK, font="Consolas", space_before=1)
    set_speaker_notes(s, (
        "This is the single biggest change of the week: the agent host "
        "moved off Windows MVPACCESS onto the existing Linux box at "
        ".123 that already hosts the OpenProject stack. The whole "
        "thing is a docker-compose file, six services, one shared "
        "image (`nucleus-worker:latest`) plus the third-party Samba "
        "and GitHub runner containers. The repo itself is bind-mounted "
        "read-only -- `git pull` on the host updates every worker "
        "without an image rebuild. Bind mounts are designed so we can "
        "`docker compose down` and `up` without losing state: the "
        "sqlite memory database lives in a named volume, the central "
        "share lives on the host filesystem, and the Claude auth tree "
        "is mounted in from the ubuntu user's home directory."
    ))


def slide_transcription_pipeline(prs):
    s = base_slide(prs, "Transcription pipeline",
                   "Groq primary. faster-whisper fallback. Same model on both.")

    # Two boxes, primary vs fallback
    add_box(s, Inches(0.5), Inches(1.5), Inches(6.1), Inches(5.3),
            "Primary: Groq Whisper (cloud)", [
                "Model:       whisper-large-v3",
                "Endpoint:    api.groq.com/openai/v1/audio/translations",
                "Hardware:    Groq LPU (GPU class)",
                "Throughput:  ~30 s per call (typical 3-min call)",
                "Cost:        free tier, 8 hours of audio/day",
                "Limit:       file size capped at 25 MB",
                "",
                "Calls translation endpoint (Bangla speech -> English text)",
                "in one round trip; no separate transcribe + translate step.",
                "",
                "If GROQ_API_KEY missing, rate-limited, network error, or",
                "file > 25 MB: silent fallback to faster-whisper.",
            ], accent=GREEN, title_size=15, body_size=12)

    add_box(s, Inches(6.8), Inches(1.5), Inches(6.0), Inches(5.3),
            "Fallback: faster-whisper (local CPU)", [
                "Model:       whisper-large-v3 (int8 quantized)",
                "Hardware:    CPU on .123 (no GPU on this host)",
                "Throughput:  ~10 min per call",
                "Cost:        free, no external dependency",
                "Load:        ~3 GB model, loaded LAZILY",
                "",
                "Only fires when Groq fails. On normal days the int8 model",
                "is never loaded -- we save the ~3 GB allocation entirely.",
                "",
                "Same model lineage as Groq's, so transcript quality is",
                "consistent across the boundary -- only the latency",
                "differs.",
            ], accent=GOLD, title_size=15, body_size=12)
    set_speaker_notes(s, (
        "Transcription is where the daily pipeline used to bottleneck on "
        "the Windows host -- a 3-minute Bangla call took about 10 minutes "
        "to transcribe on CPU with faster-whisper. Groq is the same "
        "whisper-large-v3 model running on their LPU hardware; we hit "
        "their translation endpoint, which folds Bangla speech -> English "
        "text into one round trip. A typical call comes back in about 30 "
        "seconds. The free tier gives us 8 hours of audio per day, which "
        "comfortably covers the team's actual call volume. If Groq fails "
        "for ANY reason -- missing key, network blip, rate limit, file "
        "over 25 MB -- the worker falls back to the local faster-whisper "
        "on CPU. The fallback is correct but slow; on bursty days that's "
        "fine because we have hours before the 23:45 daily draft fires."
    ))


def slide_email_drive_chat(prs):
    s = base_slide(prs, "Email, Drive, and chat capture",
                   "Periodic pulls on .123. Chat push on dev PCs.")

    # Three columns
    add_box(s, Inches(0.5), Inches(1.5), Inches(4.05), Inches(5.3),
            "Teams chat (per-dev push)", [
                "Where:    each dev PC",
                "Trigger:  Windows Task Scheduler",
                "Windows:  3 BD-local windows/day",
                "    - Day       (~10:00 BD)",
                "    - Transition(~14:00 BD)",
                "    - Evening   (~20:00 BD)",
                "",
                "Each push bundles every Teams chat",
                "the dev exchanged since the last",
                "push, writes a .docx per window, and",
                "copies to central:",
                "  /<dev>/<date>/chat/",
            ], accent=TEAL, title_size=14, body_size=11)

    add_box(s, Inches(4.65), Inches(1.5), Inches(4.05), Inches(5.3),
            "Email (Gmail IMAP)", [
                "Where:    nucleus-stage-email on .123",
                "Trigger:  loop, 15-min cadence",
                "",
                "Pulls every new mail thread the team",
                "had with the client. Each thread is",
                "saved as a structured .docx with",
                "attachments fanned out:",
                "  /<dev>/<date>/email/",
                "      thread_<id>.docx",
                "      thread_<id>__att1.pdf",
                "      ...",
                "",
                "PDFs + legacy .doc bodies are byte-",
                "scanned and inlined so verify_session",
                "sees the full content, not just the",
                "filename.",
            ], accent=CORAL, title_size=14, body_size=11)

    add_box(s, Inches(8.8), Inches(1.5), Inches(4.05), Inches(5.3),
            "Drive (Google Drive)", [
                "Where:    nucleus-stage-drive on .123",
                "Trigger:  loop, 15-min cadence",
                "",
                "Watches the shared client folder.",
                "New files copy into:",
                "  /<dev>/<date>/drive/",
                "",
                "Audio uploads (.m4a, .mp3, .wav)",
                "are re-transcribed through the same",
                "Groq pipeline -- so a voice note in",
                "the shared folder gets a transcript",
                "alongside, just like a call would.",
                "",
                "Drive transcripts and call transcripts",
                "are tracked separately so we don't",
                "double-count.",
            ], accent=GOLD, title_size=14, body_size=11)
    set_speaker_notes(s, (
        "Three capture channels that are independent of the voice "
        "daemon. Teams chat is the only channel still pushed from "
        "dev PCs (the chat database lives in each user's Teams app "
        "data, so we have to walk it on their machine); three BD-local "
        "windows per day balance freshness against API rate limits. "
        "Email is pulled by the stage-email container on .123 every "
        "15 minutes via Gmail IMAP -- threads are saved as structured "
        ".docx with attachments fanned out and PDFs inlined so the "
        "downstream model actually sees the content. Drive is similar "
        "but for Google Drive; the wrinkle is that voice notes "
        "uploaded to the shared folder get sent through Groq too, so "
        "an audio file in the Drive folder ends up with a transcript "
        "next to it just like a Teams call recording would."
    ))


def slide_daily_requirement_management(prs):
    s = base_slide(prs, "Daily Requirement Management",
                   "BD 23:45 on .123. One pass aggregates the whole day.")

    # Timeline of the daily run
    tf = add_textbox(s, Inches(0.8), Inches(1.5), Inches(11.7), Inches(0.6))
    set_text(tf, "Container nucleus-daily-draft, TZ=Asia/Dhaka, sleep-until-target loop:",
             size=14, color=MUTED)

    # Step boxes in a horizontal flow
    steps = [
        ("23:45 BD", NAVY,
         "Loop wakes.\nFires once.\nSleeps until 23:45 tomorrow."),
        ("collect_central.py", TEAL,
         "--client all\n--last-minutes 1440\n(walks last 24h)"),
        ("Aggregate", PURPLE,
         "Read every .md / .docx in central tree.\nGroup by client.\nWrite Pull Session <date>.docx."),
        ("verify_session", GREEN,
         "Claude Agent SDK\non the session doc.\nIdentify + draft."),
        ("Gmail Drafts", GOLD,
         "One .eml per client\nlands in your Drafts\nready for review."),
    ]
    box_w = Inches(2.4)
    gap = Inches(0.15)
    total = 5 * 2.4 + 4 * 0.15
    x0 = (13.333 - total) / 2
    y_steps = Inches(2.3)
    for i, (title, color, body) in enumerate(steps):
        x = Inches(x0 + i * (2.4 + 0.15))
        add_box(s, x, y_steps, box_w, Inches(2.7), title, body.split("\n"),
                accent=color, title_size=14, body_size=11)
        if i < 4:
            x_arr = Inches(x0 + i * (2.4 + 0.15) + 2.4)
            add_arrow(s, x_arr, Inches(2.3 + 2.7 / 2),
                      x_arr + Inches(0.15), Inches(2.3 + 2.7 / 2),
                      color=NAVY, width_pt=2.5)

    # Cost annotation
    tf2 = add_textbox(s, Inches(0.8), Inches(5.4), Inches(11.7), Inches(1.6))
    set_text(tf2, "Typical run: 7 devs, 1 client, full day of capture.",
             size=14, bold=True, color=NAVY)
    add_para(tf2,
             "Session document around 16k characters. One Claude pass. "
             "Target cost ~$0.06 per run. Walks come in under 60 seconds.",
             size=12, color=MUTED, space_before=4)
    add_para(tf2,
             "Same workhorse script runs ad-hoc -- collect_central.py "
             "--client \"Salman\" --day 2026-05-14 -- if you want a "
             "mid-day rebuild without waiting for 23:45.",
             size=12, color=MUTED, space_before=4)
    set_speaker_notes(s, (
        "The daily run is the heartbeat of the system. Container TZ "
        "is Asia/Dhaka so the wall clock IS BD; a simple sleep-until-"
        "target loop replaces the old Windows Task Scheduler entry. "
        "At 23:45 it shells out to collect_central.py with --client "
        "all and --last-minutes 1440 -- the workhorse script that "
        "walks the central tree, groups everything that touched each "
        "client in the last 24 hours, and writes a single Pull Session "
        ".docx. That doc is what gets handed to the verify_session task "
        "on the Claude Agent SDK. The whole run targets about six "
        "cents on Anthropic's pricing because we're scoping tightly "
        "and using prompt caching."
    ))


def slide_claude_identifies(prs):
    s = base_slide(prs, "Claude identifies and drafts",
                   "One Claude Agent SDK session per client. ~16k chars in.")

    add_box(s, Inches(0.5), Inches(1.5), Inches(6.1), Inches(5.3),
            "Input: Pull Session <date>.docx", [
                "  Calls section (transcripts, in time order)",
                "  Chats section (per chat window)",
                "  Emails section (subject + body + inlined attachments)",
                "  Drive section (file names + audio transcripts)",
                "",
                "Around 16k characters for a typical full day.",
                "",
                "Pre-filtered before Claude sees it:",
                "  - system notifications stripped",
                "  - recorder test snippets dropped",
                "  - peer-to-peer dev chatter dropped",
                "  - already-confirmed requirements (from previous",
                "    days' replies) marked as resolved.",
            ], accent=NAVY, title_size=15, body_size=12)

    add_box(s, Inches(6.7), Inches(1.5), Inches(6.1), Inches(5.3),
            "Output: per-client artefacts", [
                "1. Requirements Verification <date>.docx",
                "      a numbered list of what the team heard.",
                "      one entry per requirement, with the",
                "      source pointer (call timestamp, chat",
                "      thread, email subject).",
                "",
                "2. .eml draft in Gmail Drafts",
                "      To:      <client>@<domain>",
                "      Subject: Requirements Verification <date>",
                "      Body:    bullet summary",
                "      Attach:  the .docx above",
                "      Attach:  the Pull Session source doc",
                "",
                "Memory: writes new state to sqlite at",
                "      /state/nucleus_memory.db",
            ], accent=GOLD, title_size=15, body_size=12)
    set_speaker_notes(s, (
        "Inside the verify_session task, Claude is doing one job: read "
        "the day's collated source material and pick out the things that "
        "are actually client requirements -- as distinct from noise like "
        "system notifications, recorder-test snippets, peer-to-peer dev "
        "chatter, or already-confirmed items from prior days. The output "
        "is two artefacts per client per day. The .docx is the curated "
        "list with source pointers so the client can cross-check. The "
        ".eml is the verification email itself, with both the curated "
        ".docx and the raw Pull Session attached -- the raw source is "
        "deliberately included so the client can audit anything that "
        "looks off. State written to the sqlite memory db lives in the "
        "named docker volume; it survives container restarts."
    ))


def slide_human_in_the_loop(prs):
    s = base_slide(prs, "Human in the loop",
                   "Review the draft. Send. Reply gets parsed back.")

    # Three steps as horizontal cards
    steps = [
        ("Review", NAVY,
         "Open Gmail Drafts.\nRead the curated .docx.\nSpot-check anything questionable\nagainst the Pull Session doc."),
        ("Send", GREEN,
         "Click send when satisfied.\nNo auto-send -- the human gate\nis deliberate.\nSalman gets the email + 2 attachments."),
        ("Parse the reply", PURPLE,
         "Salman replies in Gmail.\ntools.poll_replies picks it up,\nupdates the sqlite memory db,\nfeeds tomorrow's run."),
    ]
    cw = Inches(4.0)
    gap = Inches(0.2)
    total = 3 * 4.0 + 2 * 0.2
    x0 = (13.333 - total) / 2
    y = Inches(1.8)
    for i, (title, color, body) in enumerate(steps):
        x = Inches(x0 + i * (4.0 + 0.2))
        add_box(s, x, y, cw, Inches(3.4), title, body.split("\n"),
                accent=color, title_size=18, body_size=13)
        if i < 2:
            x_arr = Inches(x0 + i * (4.0 + 0.2) + 4.0)
            add_arrow(s, x_arr, Inches(1.8 + 3.4 / 2),
                      x_arr + Inches(0.2), Inches(1.8 + 3.4 / 2),
                      color=NAVY, width_pt=2.5)

    # Bottom annotation
    tf = add_textbox(s, Inches(0.8), Inches(5.7), Inches(11.7), Inches(1.4))
    set_text(tf, "The loop closes automatically.",
             size=15, bold=True, color=NAVY)
    add_para(tf,
             "Replies are matched back to the verification email by "
             "thread id, parsed for accept/reject/clarify-on-each-line, "
             "and written into the same sqlite memory the next day's "
             "Pull Session reads from. Items confirmed yesterday don't "
             "re-surface today.",
             size=13, color=MUTED, space_before=6)
    set_speaker_notes(s, (
        "This is the only manual step in the whole pipeline. The "
        "deliberate design choice is that the system never sends mail "
        "to a client without a human pressing send. You open Gmail "
        "Drafts -- the .eml is already there -- skim the curated "
        ".docx, cross-check anything that looks weird against the Pull "
        "Session source doc, edit if needed, and send. Once Salman "
        "replies, tools.poll_replies (which runs on the central host) "
        "matches the reply by thread id, parses line-by-line "
        "accept/reject/clarify, and writes the deltas into the "
        "sqlite memory. Tomorrow's daily run reads that memory before "
        "drafting the next verification email, so confirmed items "
        "don't get re-asked."
    ))


def slide_tools_and_tech(prs):
    s = base_slide(prs, "Tools and technologies",
                   "Boring tech, deliberately. One Python stack end-to-end.")

    # Categories
    cats = [
        ("Runtime", TEAL, [
            "Python 3.12",
            "Ubuntu 24.04 LTS (.123)",
            "Windows 11 (dev PCs)",
            "Docker + docker-compose",
        ]),
        ("AI / transcription", PURPLE, [
            "Anthropic Claude Opus (Max-tier)",
            "Claude Agent SDK",
            "Groq API (whisper-large-v3)",
            "faster-whisper int8 (fallback)",
        ]),
        ("Storage / share", GOLD, [
            "Samba (SMB / port 445)",
            "sqlite (memory.db)",
            "python-docx (artefacts)",
            "Named docker volume (state)",
        ]),
        ("Capture surfaces", CORAL, [
            "MS Teams (pycaw, IndexedDB)",
            "Gmail IMAP + OAuth",
            "Google Drive API + OAuth",
            "Windows Task Scheduler (chat push)",
        ]),
        ("Ops", GREEN, [
            "GitHub Actions (self-hosted runner)",
            "docker-compose .env config",
            "git pull -> RO bind-mount = hot reload",
            "tools.healthcheck (CLI status)",
        ]),
        ("Auth", NAVY, [
            "Claude Max-tier (.claude bind-mounted RO)",
            "Gmail OAuth refresh tokens",
            "Drive OAuth (same project)",
            "Samba single shared user (Phase 1)",
        ]),
    ]
    cw = Inches(4.05)
    ch = Inches(2.55)
    gap = Inches(0.15)
    x0 = Inches(0.5)
    y0 = Inches(1.5)
    for i, (name, color, items) in enumerate(cats):
        row, col = divmod(i, 3)
        x = x0 + col * (cw + gap)
        y = y0 + Inches(row * 2.7)
        add_box(s, x, y, cw, ch, name, items, accent=color,
                title_size=14, body_size=12)
    set_speaker_notes(s, (
        "Nothing exotic in the stack. The whole system is one Python "
        "codebase running in docker containers on Linux, with a small "
        "Windows footprint on each dev PC for the parts that have to "
        "live next to Teams. Anthropic + Groq are the only paid "
        "external services -- and Groq is currently free-tier. Gmail "
        "and Drive use ordinary OAuth refresh tokens against a single "
        "Google Cloud project. Self-hosted GitHub Actions on .123 "
        "means CI runs in the same network neighborhood as the "
        "containers, which keeps deploys simple."
    ))


def slide_status_today(prs):
    s = base_slide(prs, "What .123 actually does today",
                   "Live as of 2026-05-14. Six containers up. Four channels active.")

    # Status row
    statuses = [
        ("6 / 6", "containers up", GREEN),
        ("4 / 4", "capture channels active", GREEN),
        ("~$0.06", "target cost per daily run", GOLD),
        ("~30 s", "per call via Groq", TEAL),
    ]
    box_w = Inches(2.95)
    gap = Inches(0.2)
    total = 4 * 2.95 + 3 * 0.2
    x0 = (13.333 - total) / 2
    y = Inches(1.6)
    for i, (big, label, color) in enumerate(statuses):
        x = Inches(x0 + i * (2.95 + 0.2))
        container = add_rect(s, x, y, box_w, Inches(1.7),
                             fill_color=WHITE, line_color=RULE)
        add_rect(s, x, y, box_w, Inches(0.12), fill_color=color)
        tf_big = add_textbox(s, x + Inches(0.1), y + Inches(0.3),
                             box_w - Inches(0.2), Inches(0.8))
        set_text(tf_big, big, size=30, bold=True, color=color,
                 align=PP_ALIGN.CENTER)
        tf_lbl = add_textbox(s, x + Inches(0.1), y + Inches(1.05),
                             box_w - Inches(0.2), Inches(0.5))
        set_text(tf_lbl, label, size=12, color=MUTED, align=PP_ALIGN.CENTER)

    # The loop ran today
    add_box(s, Inches(0.5), Inches(3.6), Inches(6.1), Inches(3.2),
            "The loop ran today", [
                "Daily draft fired at 23:45 BD on .123.",
                "  collect_central --client all --last-minutes 1440",
                "  walked the central tree in under a minute.",
                "  one Pull Session doc per client.",
                "  one verify_session run per client.",
                "  one .eml landed in Gmail Drafts.",
                "",
                "Memory updated: /state/nucleus_memory.db",
            ], accent=GREEN, title_size=15, body_size=12)

    # Health snapshot
    add_box(s, Inches(6.7), Inches(3.6), Inches(6.1), Inches(3.2),
            "Health snapshot", [
                "nucleus-samba         -- serving share",
                "nucleus-transcribe    -- idle, queue empty",
                "nucleus-stage-email   -- last pull <15 min ago",
                "nucleus-stage-drive   -- last pull <15 min ago",
                "nucleus-daily-draft   -- next fire 23:45 BD",
                "nucleus-gha-runner    -- registered, idle",
                "",
                "Run `python -m tools.healthcheck` on .123 for the",
                "live version of this snapshot.",
            ], accent=NAVY, title_size=15, body_size=12)
    set_speaker_notes(s, (
        "Status check, fact-by-fact, for the boss. Everything that was "
        "supposed to be running on the Linux host today IS running on "
        "the Linux host today. The cost target is around six cents per "
        "daily run on Anthropic pricing -- well inside the budget we "
        "discussed. Groq is doing roughly 30 seconds per call, which "
        "is the speed-up that let us move off the Windows host: the "
        "old CPU faster-whisper run was the slowest stage of the day "
        "by a wide margin. The healthcheck CLI gives a live version of "
        "the right-hand snapshot any time we want to spot-check the "
        "host without SSHing in for `docker ps`."
    ))


def slide_whats_next(prs):
    s = base_slide(prs, "What's next",
                   "Roster, onboarding, retire .209, automate the send loop.")

    nexts = [
        ("Extend the client roster", CORAL, [
            "Salman is client #1 today.",
            "Add a second client without changing code:",
            "  Drive folder + email alias + ",
            "  metadata.client_name on calls,",
            "  collect_central is per-client already.",
        ]),
        ("Dev-PC onboarding", TEAL, [
            "Bring all 7 devs onto the daemon:",
            "  scripts\\setup.bat",
            "  net use \\\\172.16.205.123\\nucleus-central",
            "  scripts\\start-daemon.bat",
            "About 10 minutes per teammate.",
        ]),
        ("Retire MVPACCESS (.209)", PURPLE, [
            "Confirm a full week of green on .123.",
            "Decommission the .209 Scheduled Tasks.",
            "Keep .209's nucleus-central archive RO",
            "  for the historical record, then power it down.",
        ]),
        ("Automate verify -> send", GOLD, [
            "Track accuracy of the human-edit deltas",
            "  for the next N daily drafts.",
            "When accuracy crosses the agreed threshold,",
            "  flip a feature flag to auto-send for",
            "  routine confirmations only.",
        ]),
        ("Future integrations", NAVY, [
            "OpenProject publishing (auto-create tasks",
            "  for newly-confirmed requirements).",
            "Calendar-aware capture (cross-reference",
            "  meeting invites against call recordings).",
            "Slack / Discord channels (if a client uses them).",
        ]),
        ("Operational hardening", GREEN, [
            "Backups for /srv/nucleus-central and",
            "  the sqlite memory volume.",
            "Per-dev Samba accounts (drop the shared user).",
            "Prometheus exporter on healthcheck for",
            "  alerting on stuck containers.",
        ]),
    ]
    cw = Inches(4.05)
    ch = Inches(2.6)
    gap = Inches(0.15)
    x0 = Inches(0.5)
    y0 = Inches(1.45)
    for i, (name, color, items) in enumerate(nexts):
        row, col = divmod(i, 3)
        x = x0 + col * (cw + gap)
        y = y0 + Inches(row * 2.75)
        add_box(s, x, y, cw, ch, name, items, accent=color,
                title_size=14, body_size=11)
    set_speaker_notes(s, (
        "Six tracks for the next phase, ordered roughly by what unblocks "
        "what. First two are pure rollout work -- adding a second client "
        "and onboarding the remaining devs onto the voice daemon. Then "
        "retiring the old Windows agent host once .123 has a full week "
        "of clean runs. The big policy question is automating verify "
        "-> send: we want to keep the human gate for now, but once we "
        "have a track record of human-edit deltas being trivial for "
        "routine confirmations, we can flip a feature flag and let the "
        "system auto-send those while keeping human review for new "
        "asks. Future integrations + operational hardening are the "
        "long tail -- OpenProject auto-publishing of confirmed reqs is "
        "the highest-value of those."
    ))


# ── build ──────────────────────────────────────────────────────────

def build():
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    slide_title(prs)
    slide_cast(prs)
    slide_four_channel_flow(prs)
    slide_voice_capture(prs)
    slide_where_call_lands(prs)
    slide_central_host(prs)
    slide_transcription_pipeline(prs)
    slide_email_drive_chat(prs)
    slide_daily_requirement_management(prs)
    slide_claude_identifies(prs)
    slide_human_in_the_loop(prs)
    slide_tools_and_tech(prs)
    slide_status_today(prs)
    slide_whats_next(prs)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT))
    print(f"Wrote: {OUT}")
    print(f"  slides: {len(prs.slides)}")


if __name__ == "__main__":
    build()
