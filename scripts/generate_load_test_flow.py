"""Generate a one-page colorful diagram showing how NAPCO Nucleus
orchestrates the API Load Test end-to-end (functional + integration
follow the same pattern, just with different runner functions).

Output: docs/load-test-flow.pdf (landscape A4).
"""
from __future__ import annotations

import math
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT  = os.path.join(_ROOT, "docs", "load-test-flow.pdf")


# Design tokens (match the presentation deck)
NAVY   = colors.HexColor("#1F4E79")
TEAL   = colors.HexColor("#2E8A8A")
CORAL  = colors.HexColor("#E07856")
GREEN  = colors.HexColor("#4A7A4A")
GOLD   = colors.HexColor("#C9962B")
PURPLE = colors.HexColor("#6A4C93")
SOFT   = colors.HexColor("#F5F7FA")
HIGH   = colors.HexColor("#FFF8E1")
INK    = colors.HexColor("#1A1A1A")
MUTED  = colors.HexColor("#5B6573")
RULE   = colors.HexColor("#D0D2D6")
WHITE  = colors.white

PAGE_W, PAGE_H = landscape(A4)


def _box(c, x, y, w, h, fill, label, sub=None, *,
         label_size=12, sub_size=9, label_color=WHITE,
         sub_color=None):
    """Rounded colored box with a centered label and optional sub-line."""
    c.setFillColor(fill)
    c.roundRect(x, y, w, h, 5, fill=1, stroke=0)
    c.setFillColor(label_color)
    c.setFont("Helvetica-Bold", label_size)
    if sub:
        c.drawCentredString(x + w / 2, y + h / 2 + 2, label)
        c.setFillColor(sub_color or label_color)
        c.setFont("Helvetica", sub_size)
        c.drawCentredString(x + w / 2, y + h / 2 - sub_size - 2, sub)
    else:
        c.drawCentredString(x + w / 2, y + h / 2 - label_size / 3, label)


def _soft_box(c, x, y, w, h, label, lines, accent_color):
    """Soft-grey body with a colored top accent stripe and a list of
    bullet lines (used for the Locust loop block + the results block)."""
    c.setFillColor(SOFT)
    c.roundRect(x, y, w, h, 5, fill=1, stroke=0)
    # accent stripe on top
    stripe_h = 4
    c.setFillColor(accent_color)
    c.roundRect(x, y + h - stripe_h, w, stripe_h, 2, fill=1, stroke=0)
    # title
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x + 8, y + h - 18, label)
    # lines
    c.setFillColor(INK)
    c.setFont("Helvetica", 9)
    line_y = y + h - 32
    for line in lines:
        c.drawString(x + 12, line_y, line)
        line_y -= 11


def _arrow(c, x1, y1, x2, y2, color=MUTED, width=1.4):
    c.setStrokeColor(color)
    c.setLineWidth(width)
    c.line(x1, y1, x2, y2)
    # Arrowhead
    angle = math.atan2(y2 - y1, x2 - x1)
    ah = 7
    c.setFillColor(color)
    p = c.beginPath()
    p.moveTo(x2, y2)
    p.lineTo(x2 - ah * math.cos(angle - math.pi / 7),
             y2 - ah * math.sin(angle - math.pi / 7))
    p.lineTo(x2 - ah * math.cos(angle + math.pi / 7),
             y2 - ah * math.sin(angle + math.pi / 7))
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def _label(c, x, y, text, size=8, color=MUTED, bold=False):
    c.setFillColor(color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(x, y, text)


def main():
    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    c = canvas.Canvas(_OUT, pagesize=landscape(A4))

    # ── Title ─────────────────────────────────────────────────────
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(1 * cm, PAGE_H - 1.1 * cm,
                 "How NAPCO Nucleus runs the API Load Test")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 10)
    c.drawString(1 * cm, PAGE_H - 1.6 * cm,
                 "Same pattern for Functional (Newman) and Integration (pytest) — "
                 "different runner function, same orchestration path.")

    # ── Geometry ─────────────────────────────────────────────────
    # Left column for the flow, right column for annotations.
    flow_x   = 1 * cm
    flow_w   = 17.5 * cm
    annot_x  = flow_x + flow_w + 0.7 * cm
    annot_w  = PAGE_W - annot_x - 1 * cm

    # Vertical bands top→bottom
    y_trigger = PAGE_H - 3.0 * cm
    y_nn      = PAGE_H - 5.0 * cm
    y_prompt  = PAGE_H - 7.5 * cm
    y_sibling = PAGE_H - 9.8 * cm
    y_loop    = PAGE_H - 14.0 * cm
    y_api     = PAGE_H - 16.0 * cm
    y_out     = PAGE_H - 18.7 * cm

    # ── Layer 1: Trigger row (3 options) ─────────────────────────
    trig_w = (flow_w - 2 * 0.4 * cm) / 3
    trig_h = 1.2 * cm
    triggers = [
        ("Cron schedule",       "GitHub Actions",         NAVY),
        ("Manual",              "gh workflow run …",      NAVY),
        ("Local",               "py -3 agent.py --task api-load-test", NAVY),
    ]
    for i, (lab, sub, col) in enumerate(triggers):
        x = flow_x + i * (trig_w + 0.4 * cm)
        _box(c, x, y_trigger, trig_w, trig_h, col, lab, sub,
             label_size=11, sub_size=8.5)

    # ── Layer 2: NN agent ────────────────────────────────────────
    nn_w = 12 * cm
    nn_h = 1.4 * cm
    nn_x = flow_x + (flow_w - nn_w) / 2
    _box(c, nn_x, y_nn, nn_w, nn_h, NAVY,
         "NAPCO Nucleus  agent.py",
         "Claude Agent SDK   ·   31 MCP tools   ·   self-hosted Windows VM runner (or your laptop)",
         label_size=14, sub_size=9.5)

    # Arrows triggers → NN
    nn_top = y_nn + nn_h
    for i in range(3):
        x = flow_x + i * (trig_w + 0.4 * cm) + trig_w / 2
        _arrow(c, x, y_trigger, x, y_nn + nn_h, color=MUTED, width=1.2)

    # ── Layer 3: Prompt + MCP tool (side by side) ────────────────
    pair_gap = 0.5 * cm
    pair_w = (nn_w - pair_gap) / 2
    pair_h = 1.5 * cm
    prompt_x = nn_x
    tool_x = nn_x + pair_w + pair_gap
    _box(c, prompt_x, y_prompt, pair_w, pair_h, TEAL,
         "prompts/api_load_test.md",
         "tells the agent what steps to do",
         label_size=12, sub_size=9)
    _box(c, tool_x, y_prompt, pair_w, pair_h, CORAL,
         "tools/tests.py — run_load_tests",
         "MCP tool the agent calls to actually run the test",
         label_size=12, sub_size=9)

    # Arrow from NN down splitting to two
    _arrow(c, nn_x + nn_w / 2, y_nn,
              prompt_x + pair_w / 2, y_prompt + pair_h, color=MUTED)
    _arrow(c, nn_x + nn_w / 2, y_nn,
              tool_x + pair_w / 2, y_prompt + pair_h, color=MUTED)

    # ── Layer 4: Sibling project ────────────────────────────────
    sib_w = nn_w
    sib_h = 1.3 * cm
    _box(c, nn_x, y_sibling, sib_w, sib_h, PURPLE,
         "MVP-Access-API-Test / agent / run_all_tests.py",
         "the actual runner — imported from the SIBLING project, not from NN",
         label_size=12, sub_size=9)

    # Arrow tool → sibling (via "imports" label)
    _arrow(c, tool_x + pair_w / 2, y_prompt,
              nn_x + sib_w / 2, y_sibling + sib_h, color=PURPLE, width=1.6)
    _label(c, tool_x + pair_w / 2 - 1.5 * cm, y_sibling + sib_h + 0.4 * cm,
           "imports run_load_tests_multi", size=9, color=PURPLE, bold=True)

    # ── Layer 5: Locust loop block ──────────────────────────────
    loop_x = nn_x
    loop_w = sib_w
    loop_h = 3.4 * cm
    _soft_box(c, loop_x, y_loop, loop_w, loop_h,
              "for each tier  in  [10, 100, 500, 1000, 5000, 10000]:",
              [
                  "1. spawn  locust -f locustfiles/<file>.py --users <tier> --spawn-rate <r> --run-time 5m --host <API_BASE_URL>",
                  "2. capture  requests, failures, p50 / p95 / p99 latency per endpoint",
                  "3. sleep 5 minutes  (cooldown — let staging recover)",
                  "4. probe API health  (check_api_health)  before next tier; abort if unhealthy",
              ],
              GREEN)

    # Arrow sibling → loop
    _arrow(c, nn_x + sib_w / 2, y_sibling,
              loop_x + loop_w / 2, y_loop + loop_h, color=MUTED)

    # ── Layer 6: API ─────────────────────────────────────────────
    api_w = 9 * cm
    api_h = 1.2 * cm
    api_x = flow_x + (flow_w - api_w) / 2
    _box(c, api_x, y_api, api_w, api_h, GOLD,
         "Staging API @ API_BASE_URL",
         "the system under test — receives the load each tier produces",
         label_size=12, sub_size=9)

    # Arrow loop → api (each tier hits the API)
    _arrow(c, loop_x + loop_w / 2, y_loop,
              api_x + api_w / 2, y_api + api_h, color=GOLD, width=1.6)
    _label(c, api_x + api_w / 2 - 1.6 * cm, y_api + api_h + 0.3 * cm,
           "HTTP requests at increasing concurrency",
           size=9, color=GOLD, bold=True)

    # ── Layer 7: Results back up to NN ──────────────────────────
    out_pair_w = (loop_w - 0.5 * cm) / 2
    out_h = 1.4 * cm
    pdf_x  = nn_x
    mem_x  = nn_x + out_pair_w + 0.5 * cm
    _box(c, pdf_x, y_out, out_pair_w, out_h, CORAL,
         "PDF report",
         "reports/api-load-test/<ts>.pdf  with tier table + ceiling analysis",
         label_size=12, sub_size=9)
    _box(c, mem_x, y_out, out_pair_w, out_h, TEAL,
         "nucleus_memory.db",
         "test_run_history  +  activity_logs  rows  (committed to git)",
         label_size=12, sub_size=9)

    # Curve / arrows api → results (results flow up the call stack)
    _arrow(c, api_x + api_w / 2, y_api,
              pdf_x + out_pair_w / 2, y_out + out_h, color=MUTED, width=1.2)
    _arrow(c, api_x + api_w / 2, y_api,
              mem_x + out_pair_w / 2, y_out + out_h, color=MUTED, width=1.2)
    _label(c, api_x + api_w / 2 - 2 * cm, y_api - 0.4 * cm,
           "results bubble back up through sibling → tool → NN agent",
           size=8.5, color=MUTED)

    # ── Right-side annotations ──────────────────────────────────
    ay = PAGE_H - 3.0 * cm

    def _note(title, body_lines, accent):
        nonlocal ay
        h = 0.9 * cm + len(body_lines) * 11 + 6
        # left accent bar
        c.setFillColor(accent)
        c.roundRect(annot_x, ay - h, 4, h, 1, fill=1, stroke=0)
        # body
        c.setFillColor(SOFT)
        c.roundRect(annot_x + 5, ay - h, annot_w - 5, h, 4, fill=1, stroke=0)
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(annot_x + 12, ay - 18, title)
        c.setFillColor(INK)
        c.setFont("Helvetica", 8.5)
        ly = ay - 32
        for ln in body_lines:
            c.drawString(annot_x + 12, ly, ln)
            ly -= 11
        ay -= h + 0.35 * cm

    _note(
        "Functional + Integration — same path",
        [
            "tools/tests.py also exposes",
            "  run_api_tests       (Newman + Postman)",
            "  run_integration_tests  (pytest)",
            "Each maps to its own NN workflow.",
        ],
        TEAL,
    )

    _note(
        "Why GHA failed earlier",
        [
            "GitHub Actions runner only checks out",
            "the napco-nucleus repo. Sibling at",
            "E:\\Projects\\MVP-Access-API-Test\\ does",
            "not exist on the runner.",
            "NN's import of run_load_tests_multi",
            "throws WinError 267. Agent aborts",
            "pre-flight before spawning Locust.",
        ],
        CORAL,
    )

    _note(
        "Why local works",
        [
            "Your laptop has BOTH projects at",
            "E:\\Projects\\NAPCO-Nucleus\\  +",
            "E:\\Projects\\MVP-Access-API-Test\\.",
            "MVP_PROJECTS_ROOT in .env points",
            "PROJECT_PATHS at the right place.",
            "Sibling import succeeds, Locust",
            "subprocess spawns, API gets hit.",
        ],
        GREEN,
    )

    _note(
        "Fix for GHA",
        [
            "Add  actions/checkout@v5  step that",
            "pulls titucse/MVP-Access-API-Test",
            "into the workspace, then set",
            "MVP_PROJECTS_ROOT: ${{ github.workspace }}.",
            "Same pattern requirement-management",
            "uses today.",
        ],
        GOLD,
    )

    _note(
        "Memory wins",
        [
            "Every successful run writes a row to",
            "test_run_history with tier results.",
            "Next run can compare ceilings and",
            "produce a regression-or-not verdict",
            "in the PDF without re-asking the user.",
        ],
        PURPLE,
    )

    # ── Footer ──────────────────────────────────────────────────
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    c.drawString(1 * cm, 0.6 * cm,
                 "NAPCO Nucleus  ·  Mohammad Kamrul Hasan  ·  Adaptive Enterprise Limited")
    c.drawRightString(PAGE_W - 1 * cm, 0.6 * cm,
                       "Generated 2026-04-28  ·  Architecture diagram for boss-demo prep")

    c.save()
    print(f"Wrote: {_OUT}")


if __name__ == "__main__":
    main()
