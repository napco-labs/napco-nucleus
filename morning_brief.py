"""Morning Brief — 1-page reading-ready summary of last night's nightly
test run, delivered by email at 08:30 local time.

Audience: Lead QA / PM / Tech Lead reading before the standup. The brief
is data-driven, not a PDF — renders as HTML in the email client with
bold colored verdict, top 3 root-cause clusters, 7-day trend, and one
prioritized action item.

Scheduled via setup_morning_scheduler.bat -> Windows Task Scheduler.
Reads the latest artifacts from MVP-Access-API-Test/reports; reuses the
RCA classifier heuristics from this project's tools.py.

Recipient precedence:
    MORNING_BRIEF_TO env var → TEAM_EMAILS env var → error (no silent fail).
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import smtplib
import socket
import sys
from datetime import datetime, timedelta, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECTS_ROOT = os.getenv(
    "MVP_PROJECTS_ROOT", os.path.abspath(os.path.join(HERE, ".."))
)
_API_TEST = os.path.join(_PROJECTS_ROOT, "MVP-Access-API-Test")
_API_TEST_AGENT = os.path.join(_API_TEST, "agent")

# Make the sibling agent + our own modules importable
for path in (_API_TEST_AGENT, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

# Load the API-Test .env so SMTP, TEAM_EMAILS, BASE_URL etc. are available
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_API_TEST, ".env"))
except ImportError:
    pass

import config  # noqa: E402 — from MVP-Access-API-Test/agent/
import history  # noqa: E402
from tools import (  # noqa: E402 — reuse the RCA classifier
    _classify_failure, _load_pytest_failures,
    _load_newman_failures, _load_playwright_failures,
    bug_reporter,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("morning_brief")


# ─── Verdict / grade helpers (mirror report_generator.py) ────────────────

def _grade_from_counts(passed: int, failed: int, errors: int = 0,
                       skipped: int = 0, total: int = 0) -> str:
    bad = (failed or 0) + (errors or 0)
    if total <= 0:
        total = (passed or 0) + bad + (skipped or 0)
    if total == 0:
        return "SKIPPED"
    if (passed or 0) == 0 and bad > 0:
        return "CRITICAL"
    pct = (bad / total) * 100
    if pct == 0: return "PASSED"
    if pct < 5:  return "DEGRADED"
    if pct < 50: return "FAILED"
    return "CRITICAL"


def _grade_from_rate(fail_pct: float) -> str:
    if fail_pct <= 0:  return "PASSED"
    if fail_pct < 5:   return "DEGRADED"
    if fail_pct < 50:  return "FAILED"
    return "CRITICAL"


# Severity ranking so we can compute the overall verdict across suites
_RANK = {"PASSED": 0, "DEGRADED": 1, "FAILED": 2, "CRITICAL": 3, "SKIPPED": 0}

_GRADE_COLOR = {
    "PASSED":   ("#2e7d32", "#e8f5e9", "READY TO SHIP"),
    "DEGRADED": ("#ef6c00", "#fff8e1", "DEGRADED"),
    "FAILED":   ("#d84315", "#fbe9e7", "FAILED"),
    "CRITICAL": ("#c62828", "#ffebee", "CRITICAL"),
    "SKIPPED":  ("#9e9e9e", "#f5f5f5", "NO DATA"),
}


# ─── Load latest artifacts into a structured brief ───────────────────────

def _load_latest_results() -> dict:
    """Read last night's pytest / newman / playwright artifacts. Returns
    a dict mirroring the shape generate_pdf_report expects."""
    out = {"pytest": None, "newman": None, "playwright": None}

    # Latest pytest
    path = os.path.join(config.REPORTS_DIR, "pytest_report.json")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                out["pytest"] = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"pytest_report.json unreadable: {e}")

    # Latest newman
    path = os.path.join(config.REPORTS_DIR, "newman_report.json")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                out["newman"] = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"newman_report.json unreadable: {e}")

    # Playwright — 3 E2E projects, prefer the most recent
    pw_candidates = []
    for sub in ("MVP-Access-E2E-Test", "MVP-Access-Easy-E2E-Test",
                "MVP-Access-Release-Test"):
        for rel in ("reports/results.json", "test-results/results.json"):
            p = os.path.join(_PROJECTS_ROOT, sub, rel)
            if os.path.isfile(p):
                pw_candidates.append((os.path.getmtime(p), p))
    if pw_candidates:
        pw_candidates.sort(reverse=True)
        try:
            with open(pw_candidates[0][1], encoding="utf-8") as f:
                out["playwright"] = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"playwright json unreadable: {e}")

    return out


def _age_hours(path: str) -> float | None:
    if not os.path.isfile(path):
        return None
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    return (datetime.now() - mtime).total_seconds() / 3600.0


def _latest_pdf_path() -> str | None:
    pdfs = sorted(glob.glob(os.path.join(config.REPORTS_DIR, "Test_Report_*.pdf")),
                  key=os.path.getmtime, reverse=True)
    return pdfs[0] if pdfs else None


# ─── Per-suite grade + headline ──────────────────────────────────────────

def _api_view(newman_data: dict | None) -> dict:
    if not newman_data:
        return {"ran": False}
    run = newman_data.get("run", {}) or {}
    stats = run.get("stats", {}) or {}
    assertions = stats.get("assertions", {}) or {}
    total = int(assertions.get("total", 0) or 0)
    failed = int(assertions.get("failed", 0) or 0)
    passed = total - failed
    sev_5xx = 0
    for ex in run.get("executions", []) or []:
        code = int((ex.get("response") or {}).get("code", 0) or 0)
        if code >= 500:
            sev_5xx += 1
    grade = _grade_from_counts(passed, failed, total=total)
    if sev_5xx > 0 and grade in ("PASSED", "DEGRADED"):
        grade = "FAILED"
    return {
        "ran": True, "grade": grade,
        "passed": passed, "failed": failed, "total": total,
        "sev_5xx": sev_5xx,
        "headline": (f"{passed}/{total} assertions passed"
                     + (f" · {sev_5xx} endpoint(s) returning 5xx" if sev_5xx else "")),
    }


def _integration_view(pytest_data: dict | None) -> dict:
    if not pytest_data:
        return {"ran": False}
    s = pytest_data.get("summary", {}) or {}
    total = int(s.get("total", 0) or 0)
    passed = int(s.get("passed", 0) or 0)
    failed = int(s.get("failed", 0) or 0)
    errors = int(s.get("error", s.get("errors", 0)) or 0)
    grade = _grade_from_counts(passed, failed, errors, total)
    return {
        "ran": True, "grade": grade,
        "passed": passed, "failed": failed, "errors": errors, "total": total,
        "headline": (f"{passed}/{total} passed"
                     + (f" · {errors} setup errors" if errors else "")
                     + (f" · {failed} failed" if failed else "")),
    }


def _playwright_view(pw_data: dict | None) -> dict:
    if not pw_data:
        return {"ran": False}
    s = pw_data.get("stats", {}) or {}
    passed  = int(s.get("expected", 0) or 0)
    failed  = int(s.get("unexpected", 0) or 0)
    skipped = int(s.get("skipped", 0) or 0)
    total   = passed + failed + skipped
    grade = _grade_from_counts(passed, failed, skipped=skipped, total=total)
    return {
        "ran": True, "grade": grade,
        "passed": passed, "failed": failed, "skipped": skipped, "total": total,
        "headline": (f"{passed}/{total} passed"
                     + (f" · {failed} failed" if failed else "")
                     + (f" · {skipped} skipped" if skipped else "")),
    }


def _load_view() -> dict:
    """Parse the 4-5 loadtest_*.log files if present."""
    log_paths = sorted(glob.glob(os.path.join(config.REPORTS_DIR, "loadtest_*u_*.log")))
    if not log_paths:
        return {"ran": False}
    tiers = []
    for p in log_paths[-5:]:  # last 5 tier logs
        m = re.search(r"loadtest_(\d+)u_", os.path.basename(p))
        if not m:
            continue
        users = int(m.group(1))
        # Parse Aggregated row (cheap — just look for it)
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        agg_match = re.search(
            r"^\s*Aggregated\s+(\d+)\s+(\d+)\((\d+(?:\.\d+)?)%\)",
            content, re.MULTILINE,
        )
        if not agg_match:
            continue
        reqs = int(agg_match.group(1))
        fails = int(agg_match.group(2))
        fail_pct = float(agg_match.group(3))
        tiers.append({
            "users": users, "requests": reqs, "failures": fails,
            "fail_pct": fail_pct,
            "grade": _grade_from_rate(fail_pct),
        })
    if not tiers:
        return {"ran": False}
    worst = max(tiers, key=lambda t: t["fail_pct"])
    overall_grade = _grade_from_rate(worst["fail_pct"])
    return {
        "ran": True, "grade": overall_grade,
        "tiers": tiers,
        "worst": worst,
        "headline": (f"{len(tiers)} tiers run"
                     + (f" · worst {worst['users']:,} users at {worst['fail_pct']:.0f}% fail"
                        if worst["fail_pct"] > 0 else " · all healthy")),
    }


# ─── Root-cause clusters + trend ─────────────────────────────────────────

def _top_root_causes(max_groups: int = 3) -> list[dict]:
    """Collapse the day's failures by RCA class + first-line-of-error."""
    known = bug_reporter._known_bug_patterns()
    flaky_lookup = {}
    try:
        for f in history.compute_flaky_tests():
            flaky_lookup[f["name"]] = f.get("stability_pct", 0)
    except Exception:
        pass
    failures = (
        _load_pytest_failures()
        + _load_newman_failures()
        + _load_playwright_failures()
    )
    groups: dict = {}
    for f in failures:
        verdict = _classify_failure(f.get("test", ""), f.get("error", ""),
                                     known, flaky_lookup)
        # Build root-cause key from the first meaningful line of the error
        err = (f.get("error") or "").strip()
        first_line = ""
        for ln in err.splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("^"):
                first_line = ln[:160]
                break
        key = (verdict["class"], first_line)
        g = groups.setdefault(key, {
            "class": verdict["class"], "owner": verdict["owner"],
            "rationale": verdict["rationale"],
            "first_line": first_line or verdict["rationale"],
            "count": 0, "sample": f.get("test", ""),
        })
        g["count"] += 1
    return sorted(groups.values(), key=lambda g: -g["count"])[:max_groups]


def _weekly_trend(window_days: int = 7) -> dict:
    """Scan reports/history snapshots to compute pass-rate trend."""
    hist_dir = os.path.join(config.REPORTS_DIR, "history")
    if not os.path.isdir(hist_dir):
        return {"have_data": False}
    snaps = sorted(glob.glob(os.path.join(hist_dir, "*.json")),
                   key=os.path.getmtime)
    if len(snaps) < 2:
        return {"have_data": False}
    cutoff = datetime.now() - timedelta(days=window_days)
    recent = [s for s in snaps if datetime.fromtimestamp(os.path.getmtime(s)) >= cutoff]
    if len(recent) < 2:
        return {"have_data": False}
    rates = []
    for snap_path in recent:
        try:
            with open(snap_path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        # Approximate pass rate across all three test categories
        total_pass = total_seen = 0
        for cat in ("api", "integration", "e2e"):
            section = d.get(cat) or {}
            tests = section.get("tests") or {}
            for _name, status in tests.items():
                total_seen += 1
                if status in ("passed", "pass", "expected", "PASS"):
                    total_pass += 1
        if total_seen:
            rates.append((datetime.fromtimestamp(os.path.getmtime(snap_path)),
                         total_pass / total_seen * 100))
    if len(rates) < 2:
        return {"have_data": False}
    today_rate = rates[-1][1]
    avg_rate = sum(r for _, r in rates) / len(rates)
    trend = "declining" if today_rate < avg_rate - 5 else \
            "improving" if today_rate > avg_rate + 5 else "stable"
    return {
        "have_data": True,
        "today_pct": round(today_rate, 1),
        "avg_pct": round(avg_rate, 1),
        "trend": trend,
        "samples": len(rates),
    }


def _action_item(api, integ, load, pw, root_causes, trend) -> dict:
    """One prioritized action item: what should be done today."""
    # Priority 1: server capacity (CRITICAL load)
    if load.get("ran") and load.get("grade") == "CRITICAL":
        worst = load.get("worst", {})
        return {
            "priority": "HIGH",
            "text": (f"Load tier {worst.get('users', 0):,} users at "
                     f"{worst.get('fail_pct', 0):.0f}% failure — auth/throttling "
                     f"layer collapses under concurrency. Escalate to backend "
                     f"team for a capacity fix before the next release."),
        }
    # Priority 2: server unreachable (CRITICAL integration, env-dominant)
    if integ.get("ran") and integ.get("grade") == "CRITICAL":
        env_root = next((r for r in root_causes if r["class"] == "env"), None)
        if env_root:
            return {
                "priority": "HIGH",
                "text": (f"{env_root['count']} tests errored with "
                         f"'{env_root['rationale']}'. Restore API "
                         f"connectivity and re-run integration — the current "
                         f"report has no real quality signal."),
            }
    # Priority 3: 5xx in API
    if api.get("ran") and api.get("sev_5xx", 0) > 0:
        return {
            "priority": "HIGH",
            "text": (f"{api['sev_5xx']} API endpoint(s) returning 5xx — "
                     f"backend defects to triage before release. See the "
                     f"attached report's Failed Requests section."),
        }
    # Priority 4: declining trend
    if trend.get("have_data") and trend.get("trend") == "declining":
        return {
            "priority": "MEDIUM",
            "text": (f"Pass rate has declined to {trend['today_pct']}% vs a "
                     f"{trend['avg_pct']}% 7-day average. Review new "
                     f"regressions since last week."),
        }
    # Priority 5: E2E failures
    if pw.get("ran") and pw.get("failed", 0) > 0:
        return {
            "priority": "MEDIUM",
            "text": (f"{pw['failed']} E2E scenario(s) failing. Likely a UI "
                     f"regression or a selector issue — each failure card in "
                     f"the report has a repro command."),
        }
    # Default
    return {
        "priority": "LOW",
        "text": "No critical findings. Suggest spot-checking flaky tests and "
                "known-bug list to keep the queue short.",
    }


def compute_brief() -> dict:
    results = _load_latest_results()
    api = _api_view(results["newman"])
    integ = _integration_view(results["pytest"])
    pw = _playwright_view(results["playwright"])
    load = _load_view()

    # Overall grade = worst among suites that ran
    suites_ran = [s for s in (api, integ, pw, load) if s.get("ran")]
    if suites_ran:
        overall = max(suites_ran, key=lambda s: _RANK.get(s.get("grade", "SKIPPED"), 0))
        overall_grade = overall.get("grade", "SKIPPED")
    else:
        overall_grade = "SKIPPED"

    root_causes = _top_root_causes(max_groups=3)
    trend = _weekly_trend(window_days=7)
    action = _action_item(api, integ, load, pw, root_causes, trend)

    pdf = _latest_pdf_path()
    pdf_age_h = _age_hours(pdf) if pdf else None

    return {
        "now": datetime.now(),
        "overall_grade": overall_grade,
        "api": api,
        "integration": integ,
        "load": load,
        "playwright": pw,
        "root_causes": root_causes,
        "trend": trend,
        "action": action,
        "pdf_path": pdf,
        "pdf_age_hours": pdf_age_h,
        "stale": (pdf_age_h is None) or (pdf_age_h > 30),
    }


# ─── Render HTML ─────────────────────────────────────────────────────────

def _row(label: str, value: str, grade: str) -> str:
    fg, bg, _ = _GRADE_COLOR.get(grade, _GRADE_COLOR["SKIPPED"])
    return (
        f'<tr><td style="padding:8px 10px; border-bottom:1px solid #eee;">'
        f'{label}</td>'
        f'<td style="padding:8px 10px; border-bottom:1px solid #eee; color:#455a64;">'
        f'{value}</td>'
        f'<td style="padding:8px 10px; border-bottom:1px solid #eee; text-align:right;">'
        f'<span style="display:inline-block; padding:3px 10px; border-radius:3px; '
        f'background:{bg}; color:{fg}; font-weight:bold; font-size:11px; '
        f'border:1px solid {fg};">{grade}</span>'
        f'</td></tr>'
    )


def render_html(brief: dict) -> str:
    grade = brief["overall_grade"]
    fg, bg, label = _GRADE_COLOR.get(grade, _GRADE_COLOR["SKIPPED"])
    now = brief["now"]
    pdf_age_h = brief.get("pdf_age_hours")
    pdf_age_str = (
        f"{int(pdf_age_h)} h ago" if (pdf_age_h and pdf_age_h < 48)
        else (f"{int(pdf_age_h/24)} days ago" if pdf_age_h else "unknown")
    )

    # By-suite rows
    rows = []
    if brief["api"].get("ran"):
        rows.append(_row("API (Newman)", brief["api"]["headline"],
                         brief["api"]["grade"]))
    else:
        rows.append(_row("API (Newman)", "did not run", "SKIPPED"))
    if brief["integration"].get("ran"):
        rows.append(_row("Integration (pytest)", brief["integration"]["headline"],
                         brief["integration"]["grade"]))
    else:
        rows.append(_row("Integration (pytest)", "did not run", "SKIPPED"))
    if brief["load"].get("ran"):
        rows.append(_row("Load (Locust)", brief["load"]["headline"],
                         brief["load"]["grade"]))
    else:
        rows.append(_row("Load (Locust)", "did not run", "SKIPPED"))
    if brief["playwright"].get("ran"):
        rows.append(_row("E2E (Playwright)", brief["playwright"]["headline"],
                         brief["playwright"]["grade"]))
    else:
        rows.append(_row("E2E (Playwright)", "did not run", "SKIPPED"))

    # Root causes
    rc_list_html = ""
    if brief["root_causes"]:
        items = []
        for rc in brief["root_causes"]:
            rc_fg, _, _ = _GRADE_COLOR.get(
                {"env": "CRITICAL", "real_bug": "FAILED",
                 "test_bug": "DEGRADED", "data": "DEGRADED",
                 "flaky": "DEGRADED", "known_bug": "SKIPPED"}.get(rc["class"], "FAILED"),
                _GRADE_COLOR["FAILED"],
            )
            # Show the actual error line (first_line) rather than the
            # generic rationale — distinguishes multiple clusters of the
            # same class that have different underlying errors.
            detail = (rc.get("first_line") or rc.get("rationale") or "").strip()
            items.append(
                f'<li style="margin:6px 0; line-height:1.5;">'
                f'<span style="color:{rc_fg}; font-weight:bold;">'
                f'{rc["class"].upper().replace("_", " ")} ×{rc["count"]}</span> '
                f'— <code style="font-size:12px; background:#f5f5f5; padding:1px 4px; '
                f'border-radius:2px;">{detail[:140]}</code> '
                f'<span style="color:#9e9e9e; font-size:12px;">· owner: {rc["owner"]}</span>'
                f'</li>'
            )
        rc_list_html = (
            '<h2 style="font-size:14px; margin:22px 0 6px; color:#16213e; '
            'text-transform:uppercase; letter-spacing:0.5px;">'
            'Top Root Causes</h2>'
            f'<ol style="padding-left:20px; margin:0; color:#263238;">{"".join(items)}</ol>'
        )

    # Trend
    trend_html = ""
    t = brief["trend"]
    if t.get("have_data"):
        trend_color = {"declining": "#c62828", "improving": "#2e7d32",
                       "stable": "#616161"}.get(t["trend"], "#616161")
        trend_html = (
            '<h2 style="font-size:14px; margin:22px 0 6px; color:#16213e; '
            'text-transform:uppercase; letter-spacing:0.5px;">'
            '7-Day Trend</h2>'
            f'<p style="margin:0; color:#263238;">'
            f'Pass rate today: <strong>{t["today_pct"]}%</strong> · '
            f'7-day avg: <strong>{t["avg_pct"]}%</strong> · '
            f'Trend: <strong style="color:{trend_color}; '
            f'text-transform:uppercase;">{t["trend"]}</strong>'
            f' <span style="color:#9e9e9e; font-size:12px;">'
            f'({t["samples"]} snapshots)</span></p>'
        )

    # Action
    action = brief["action"]
    action_pri_color = {"HIGH": "#c62828", "MEDIUM": "#ef6c00",
                        "LOW": "#616161"}.get(action["priority"], "#616161")

    stale_warning = ""
    if brief.get("stale"):
        stale_warning = (
            '<div style="background:#fff3e0; border-left:4px solid #ef6c00; '
            'padding:10px 14px; margin:14px 0; color:#bf360c; '
            'font-size:13px;">'
            f'<strong>⚠ Stale data:</strong> the latest report is '
            f'{pdf_age_str}. Check that the nightly task is running.'
            '</div>'
        )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<title>MVP Access Morning Brief</title>
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; color:#263238; max-width:680px; margin:0 auto; padding:20px; background:#ffffff;">

  <div style="border-bottom:2px solid #16213e; padding-bottom:12px; margin-bottom:4px;">
    <h1 style="font-size:22px; margin:0; color:#16213e;">MVP Access — Morning Brief</h1>
    <div style="color:#616161; font-size:12px; margin-top:4px;">
      {now.strftime("%A, %B %d, %Y")} · last nightly {pdf_age_str}
    </div>
  </div>

  {stale_warning}

  <div style="padding:16px; border-radius:4px; text-align:center; margin:14px 0; background:{bg}; border:2px solid {fg};">
    <div style="font-size:18px; font-weight:bold; color:{fg}; letter-spacing:0.5px;">{label}</div>
  </div>

  <h2 style="font-size:14px; margin:22px 0 6px; color:#16213e; text-transform:uppercase; letter-spacing:0.5px;">By Suite</h2>
  <table style="border-collapse:collapse; width:100%; font-size:13px;">
    {''.join(rows)}
  </table>

  {rc_list_html}
  {trend_html}

  <h2 style="font-size:14px; margin:22px 0 6px; color:#16213e; text-transform:uppercase; letter-spacing:0.5px;">Action Today</h2>
  <div style="background:#f7f9fc; border-left:4px solid {action_pri_color}; padding:12px 14px; margin:4px 0;">
    <span style="display:inline-block; padding:2px 8px; border-radius:3px; background:{action_pri_color}; color:white; font-weight:bold; font-size:11px; margin-right:8px;">{action["priority"]}</span>
    <span style="color:#263238; font-size:14px; line-height:1.6;">{action["text"]}</span>
  </div>

  <div style="margin-top:32px; padding-top:12px; border-top:1px solid #e0e0e0; font-size:11px; color:#9e9e9e; text-align:center;">
    Reported by <strong>MVP Access AI Agent</strong> · Brief generated at {now.strftime("%H:%M")} · Full report attached
  </div>

</body></html>
"""


def render_plaintext(brief: dict) -> str:
    """Plain-text fallback for email clients that don't render HTML."""
    grade = brief["overall_grade"]
    lines = [
        "MVP Access — Morning Brief",
        brief["now"].strftime("%A, %B %d, %Y"),
        "=" * 60,
        f"Overall: {grade}",
        "",
        "By Suite:",
    ]
    for name, view in (("API (Newman)",         brief["api"]),
                       ("Integration (pytest)", brief["integration"]),
                       ("Load (Locust)",        brief["load"]),
                       ("E2E (Playwright)",     brief["playwright"])):
        if view.get("ran"):
            lines.append(f"  [{view['grade']:>8s}] {name:22s} {view['headline']}")
        else:
            lines.append(f"  [SKIPPED ] {name:22s} did not run")
    if brief["root_causes"]:
        lines.extend(["", "Top Root Causes:"])
        for i, rc in enumerate(brief["root_causes"], 1):
            detail = (rc.get("first_line") or rc.get("rationale") or "").strip()
            lines.append(f"  {i}. [{rc['class']}] x{rc['count']} — "
                         f"{detail[:120]} (owner: {rc['owner']})")
    t = brief["trend"]
    if t.get("have_data"):
        lines.extend(["", "7-Day Trend:",
                      f"  Today {t['today_pct']}% · avg {t['avg_pct']}% · {t['trend']}"])
    a = brief["action"]
    lines.extend(["", f"Action [{a['priority']}]:", f"  {a['text']}", ""])
    return "\n".join(lines)


# ─── Send email ─────────────────────────────────────────────────────────

def send_brief(brief: dict):
    recipients_raw = (
        os.getenv("MORNING_BRIEF_TO")
        or os.getenv("TEAM_EMAILS")
        or ""
    ).strip()
    if not recipients_raw:
        raise RuntimeError(
            "No recipients configured. Set MORNING_BRIEF_TO or TEAM_EMAILS "
            "in MVP-Access-API-Test/.env."
        )
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("EMAIL_FROM", smtp_user or "no-reply@localhost")
    if not smtp_user or not smtp_pass:
        raise RuntimeError(
            "SMTP_USER / SMTP_PASSWORD missing. Set them in "
            "MVP-Access-API-Test/.env."
        )

    grade = brief["overall_grade"]
    subject = (f"MVP Access · {grade} · "
               f"Morning Brief {brief['now'].strftime('%Y-%m-%d')}")

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(render_plaintext(brief), "plain", "utf-8"))
    msg.attach(MIMEText(render_html(brief), "html", "utf-8"))

    # Attach the full PDF if available and fresh-ish
    pdf_path = brief.get("pdf_path")
    if pdf_path and os.path.isfile(pdf_path):
        with open(pdf_path, "rb") as f:
            part = MIMEBase("application", "pdf")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition",
                        f'attachment; filename="{os.path.basename(pdf_path)}"')
        msg.attach(part)
        logger.info(f"Attached report: {os.path.basename(pdf_path)}")

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as s:
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.sendmail(sender, recipients, msg.as_string())
    logger.info(f"Morning brief sent to {len(recipients)} recipient(s): "
                f"{', '.join(recipients)}")


def main():
    logger.info(f"Morning Brief starting on {socket.gethostname()} "
                f"at {datetime.now().isoformat(timespec='seconds')}")
    brief = compute_brief()
    logger.info(f"Overall grade: {brief['overall_grade']} "
                f"(pdf_age_hours={brief.get('pdf_age_hours')})")
    if os.getenv("MORNING_BRIEF_DRY_RUN") == "1":
        print(render_plaintext(brief))
        return
    send_brief(brief)


if __name__ == "__main__":
    main()
