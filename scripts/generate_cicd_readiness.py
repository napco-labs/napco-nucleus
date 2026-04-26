"""Render the MVPAccess CICD readiness checklist as a one-page PDF.

Run:
    py -3 scripts/generate_cicd_readiness.py
Output:
    docs/CICD-Readiness-Checklist.pdf
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as canvas_mod
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT_PATH = ROOT / "docs" / "CICD-Readiness-Checklist.pdf"

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm

styles = getSampleStyleSheet()

H1 = ParagraphStyle(
    name="H1", parent=styles["Heading1"],
    fontName="Helvetica-Bold", fontSize=18, leading=22,
    spaceAfter=4, textColor=colors.HexColor("#0F2547"),
)
SUB = ParagraphStyle(
    name="Sub", parent=styles["Heading2"],
    fontName="Helvetica", fontSize=11, leading=15,
    spaceAfter=10, textColor=colors.HexColor("#506B8E"),
)
H2 = ParagraphStyle(
    name="H2", parent=styles["Heading2"],
    fontName="Helvetica-Bold", fontSize=12, leading=16,
    spaceBefore=12, spaceAfter=4, textColor=colors.HexColor("#0F2547"),
)
BODY = ParagraphStyle(
    name="Body", parent=styles["BodyText"],
    fontName="Helvetica", fontSize=10, leading=14,
    alignment=TA_LEFT, spaceAfter=6,
)
SMALL = ParagraphStyle(
    name="Small", parent=BODY,
    fontSize=9, leading=12, textColor=colors.HexColor("#555555"),
)


def _on_page(canvas: canvas_mod.Canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(colors.HexColor("#0F2547"))
    canvas.drawString(MARGIN, PAGE_H - MARGIN + 6 * mm,
                      "MVPAccess CICD — Readiness Checklist")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN + 6 * mm,
                           "2026-04-26")
    canvas.setStrokeColor(colors.HexColor("#CFD8E3"))
    canvas.setLineWidth(0.4)
    canvas.line(MARGIN, PAGE_H - MARGIN + 4 * mm,
                PAGE_W - MARGIN, PAGE_H - MARGIN + 4 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawCentredString(PAGE_W / 2, MARGIN - 6 * mm,
                             "NAPCO Nucleus — Project Management dimension")
    canvas.restoreState()


def build():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT_PATH),
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 6 * mm, bottomMargin=MARGIN + 6 * mm,
        title="MVPAccess CICD — Readiness Checklist",
        author="NAPCO Nucleus",
    )
    frame = Frame(
        MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN - 6 * mm,
        id="main", showBoundary=0,
    )
    doc.addPageTemplates([PageTemplate(id="Default", frames=[frame], onPage=_on_page)])

    story: list = []

    story.append(Paragraph("MVPAccess CICD — Readiness Checklist", H1))
    story.append(Paragraph(
        "Operational runway to launch the daily build-and-deploy pipeline",
        SUB,
    ))

    story.append(Paragraph(
        "<b>What this pipeline will do once live:</b> at 22:00 BDT every "
        "evening, pull the latest MVP Access code from the on-prem TFS "
        "server, build the .NET solution with MSBuild on a self-hosted "
        "Windows runner, deploy the build output to the IIS server over "
        "a UNC share with a graceful-offline marker, and log the deploy "
        "result into NAPCO Nucleus memory so the next morning's Daily "
        "Report can cite a precise build/deploy status alongside the "
        "test outcomes. This frees the team from manually triggering "
        "deploys before E2E runs and gives the engineering org one "
        "single timeline of code -> build -> deploy -> test in memory.",
        BODY,
    ))

    story.append(Paragraph("Outstanding items", H2))
    story.append(Paragraph(
        "All code is in place; the workflow file is committed at "
        "<font face='Courier' size='9'>.github/workflows/mvpaccess-cicd.yml</font>. "
        "The runway below is purely operational — credentials, runner "
        "tooling, and network paths.",
        BODY,
    ))

    table_data = [
        ["#", "Item", "Owner", "Effort", "Status"],
        ["1", "Add GHA secret: TFS_URL", "DevOps", "2 min", "open"],
        ["2", "Add GHA secret: TFS_PROJECT_PATH (e.g. $/MVPAccess/Main)", "DevOps", "2 min", "open"],
        ["3", "Add GHA secret: TFS_USERNAME", "DevOps", "2 min", "open"],
        ["4", "Add GHA secret: TFS_PASSWORD (service account)", "DevOps", "2 min", "open"],
        ["5", "Add GHA secret: SOLUTION_FILE (e.g. src/MVPAccess.sln)", "Dev Lead", "1 min", "open"],
        ["6", "Add GHA secret: IIS_DEPLOY_PATH (UNC like \\\\iis-server\\c$\\inetpub\\wwwroot\\MVPAccess)", "DevOps + Infra", "2 min", "open"],
        ["7", "Verify Visual Studio Build Tools + tf.exe on the runner (Get-Command MSBuild, Get-Command tf)", "Infra", "5 min", "open"],
        ["8", "Verify runner -> TFS reachability (network, port 8080 typical)", "Infra", "5 min", "open"],
        ["9", "Verify runner -> IIS UNC reachability + write permission for the runner service account", "Infra", "10 min", "open"],
        ["10", "Manual workflow_dispatch dry-run; confirm pull + build succeed end-to-end (skip deploy first)", "Dev Lead", "30 min", "blocked by 1-9"],
        ["11", "Enable the 22:00 BDT cron schedule for production", "DevOps", "1 min", "blocked by 10"],
    ]

    col_widths = [10 * mm, 92 * mm, 26 * mm, 18 * mm, 24 * mm]
    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F2547")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F5F8FC")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CFD8E3")),
    ]))
    story.append(tbl)

    story.append(Paragraph("Total runway estimate", H2))
    story.append(Paragraph(
        "Items 1-9 are roughly <b>30 minutes of operational work</b> "
        "spread across DevOps and Infra. Item 10 (the dry-run) needs "
        "another <b>30 minutes</b> with the Dev Lead present. Once "
        "green, item 11 is a one-line schedule activation. Realistic "
        "go-live: <b>same business day</b> if all three teams are "
        "available; otherwise within one business day.",
        BODY,
    ))

    story.append(Paragraph("Risks", H2))
    story.append(Paragraph(
        "<b>Service account scope:</b> the runner currently runs as a "
        "Windows user that does not have read access to the sibling "
        "test project trees. The same account will need write access "
        "to the IIS UNC path. Coordinate one permission change rather "
        "than two.",
        BODY,
    ))
    story.append(Paragraph(
        "<b>tf.exe availability:</b> tf.exe ships with the Team "
        "Explorer component of Visual Studio. If only Build Tools is "
        "installed on the runner, tf.exe is missing and step 1 of the "
        "workflow fails. Easy to verify in 30 seconds with vswhere.",
        BODY,
    ))
    story.append(Paragraph(
        "<b>Build duration:</b> the workflow has a 60-minute timeout. "
        "The two prior attempts (2026-04-24, 2026-04-25) both hit it. "
        "Likely root cause is item 7 (tf.exe missing) blocking the pull "
        "step indefinitely; once fixed, the build itself should comfortably "
        "fit the budget.",
        BODY,
    ))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "Once items 1-11 are checked off, the 22:00 BDT slot is owned "
        "by the agent and the daily build-deploy-report cycle runs without "
        "human touch. This is the last piece of the NAPCO Nucleus rollout "
        "that requires IT coordination; everything else is self-contained.",
        BODY,
    ))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "Generated 2026-04-26. Source: scripts/generate_cicd_readiness.py",
        SMALL,
    ))

    doc.build(story)
    return OUT_PATH


if __name__ == "__main__":
    out = build()
    print(f"Wrote {out}")
