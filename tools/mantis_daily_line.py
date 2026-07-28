"""mantis-daily-line — one short read-only line about Mantis activity.

Answers "what moved in the bug tracker, and what is stuck?" in a form
short enough to sit at the top of a daily brief.

  py -3 -m tools.mantis_daily_line               # print to stdout
  py -3 -m tools.mantis_daily_line --send        # email it
  py -3 -m tools.mantis_daily_line --since 48h   # widen the window

Reports work artifacts (issues opened, resolved, stuck), never people.
There is deliberately no per-assignee breakdown: the brief exists to
surface what needs attention, and a per-person scorecard both invites
gaming and makes the team hostile to the tool that produces it. If a
per-person view is ever asked for, that is a decision to take
explicitly with the team, not a flag to bolt on here.

READ-ONLY BY CONSTRUCTION: every call goes through _get(), which issues
GET only. Mantis write operations (create/update/resolve) stay manual —
same boundary as the Gmail no-auto-send rule.

Environment:
  MANTIS_URL         base, e.g. http://47.21.23.228:81/mantisbt/2242
  MANTIS_API_TOKEN   token from api_tokens_page.php (read perms enough)
  MANTIS_PROJECTS    optional comma-separated project names to include
  MANTIS_STUCK_HOURS optional, default 48 — feedback age that counts as stuck
  BRIEF_TO           recipients for --send (comma-separated)
  SMTP_*             reused from the existing mail config
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys

import requests

TIMEOUT = 20
PAGE_SIZE = 100
MAX_PAGES = 20  # 2000 issues; guard against a runaway pager
CRITICAL = {"critical", "blocker"}


class MantisConfigError(RuntimeError):
    pass


def _config() -> tuple[str, dict]:
    base = (os.getenv("MANTIS_URL") or "").strip().rstrip("/")
    token = (os.getenv("MANTIS_API_TOKEN") or "").strip()
    if not base:
        raise MantisConfigError("MANTIS_URL is not set")
    if not token:
        raise MantisConfigError(
            "MANTIS_API_TOKEN is not set - mint one at "
            "<MANTIS_URL>/api_tokens_page.php and store it in .env"
        )
    return base, {"Authorization": token, "Accept": "application/json"}


def _get(path: str, params: dict | None = None) -> dict:
    """The only HTTP verb this module uses."""
    base, headers = _config()
    r = requests.get(f"{base}{path}", headers=headers, params=params or {}, timeout=TIMEOUT)
    if r.status_code == 401:
        raise MantisConfigError("Mantis rejected the token (401) - it may be revoked")
    r.raise_for_status()
    return r.json()


def _parse_since(s: str) -> dt.timedelta:
    m = re.fullmatch(r"(\d+)\s*([hd])", s.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError("use forms like 24h or 7d")
    n, unit = int(m.group(1)), m.group(2)
    return dt.timedelta(hours=n) if unit == "h" else dt.timedelta(days=n)


def _ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fetch_issues() -> list[dict]:
    """Page through issues. Mantis returns newest-updated first."""
    out: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        data = _get("/api/rest/issues", {"page_size": PAGE_SIZE, "page": page})
        batch = data.get("issues") or []
        out.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    return out


def _wanted_projects() -> set[str]:
    raw = (os.getenv("MANTIS_PROJECTS") or "").strip()
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def gather(since: dt.timedelta) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - since
    stuck_hours = int(os.getenv("MANTIS_STUCK_HOURS") or 48)
    stuck_cutoff = now - dt.timedelta(hours=stuck_hours)
    only = _wanted_projects()

    opened: list[dict] = []
    resolved: list[dict] = []
    critical_open: list[dict] = []
    stuck: list[dict] = []
    per_project: dict[str, int] = {}

    for issue in _fetch_issues():
        project = ((issue.get("project") or {}).get("name") or "?").strip()
        if only and project.lower() not in only:
            continue

        status = ((issue.get("status") or {}).get("name") or "").lower()
        severity = ((issue.get("severity") or {}).get("name") or "").lower()
        created = _ts(issue.get("created_at"))
        updated = _ts(issue.get("updated_at"))
        closed = status in {"resolved", "closed"}

        if created and created >= cutoff:
            opened.append(issue)
            per_project[project] = per_project.get(project, 0) + 1
        if closed and updated and updated >= cutoff:
            resolved.append(issue)
        if not closed and severity in CRITICAL:
            critical_open.append(issue)
        if status == "feedback" and updated and updated < stuck_cutoff:
            stuck.append(issue)

    return {
        "now": now,
        "since": since,
        "stuck_hours": stuck_hours,
        "opened": opened,
        "resolved": resolved,
        "critical_open": critical_open,
        "stuck": stuck,
        "per_project": per_project,
    }


def _label(issue: dict) -> str:
    summary = (issue.get("summary") or "").strip()
    if len(summary) > 70:
        summary = summary[:67] + "..."
    return f"  #{issue.get('id')} {summary}"


def render(data: dict) -> str:
    day = data["now"].astimezone().strftime("%Y-%m-%d")
    hours = int(data["since"].total_seconds() // 3600)
    lines = [f"Mantis - last {hours}h (as of {day})", ""]

    lines.append(f"  Opened:            {len(data['opened'])}")
    lines.append(f"  Resolved/closed:   {len(data['resolved'])}")
    lines.append(f"  Open critical:     {len(data['critical_open'])}")
    lines.append(f"  Stuck in feedback: {len(data['stuck'])} (>{data['stuck_hours']}h)")

    if data["per_project"]:
        lines.append("")
        lines.append("  New by project:")
        for project, count in sorted(data["per_project"].items(), key=lambda kv: -kv[1]):
            lines.append(f"    {project}: {count}")

    if data["critical_open"]:
        lines.append("")
        lines.append("  Needs attention - open critical:")
        lines.extend(_label(i) for i in data["critical_open"][:10])

    if data["stuck"]:
        lines.append("")
        lines.append(f"  Waiting on feedback >{data['stuck_hours']}h:")
        lines.extend(_label(i) for i in data["stuck"][:10])

    if not (data["opened"] or data["resolved"] or data["critical_open"] or data["stuck"]):
        lines.append("")
        lines.append("  Nothing moved and nothing is stuck.")

    return "\n".join(lines)


def _send_email(text: str) -> bool:
    """Mirrors tools.daily_summary._send_email so SMTP config stays in one shape."""
    import smtplib
    from email.message import EmailMessage

    host = (os.environ.get("SMTP_HOST") or "").strip()
    user = (os.environ.get("SMTP_USER") or "").strip()
    pw = os.environ.get("SMTP_PASSWORD") or ""
    sender = (os.environ.get("SMTP_FROM") or user).strip()
    name = (os.environ.get("SMTP_FROM_NAME") or "NAPCO Nucleus").strip()
    port = int(os.environ.get("SMTP_PORT") or 465)
    to = [t.strip() for t in (os.environ.get("BRIEF_TO") or "").split(",") if t.strip()]

    if not (host and user and to):
        print("[FAIL] SMTP_HOST / SMTP_USER / BRIEF_TO must be set to send", file=sys.stderr)
        return False

    msg = EmailMessage()
    msg["Subject"] = f"Mantis daily line - {dt.datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = f"{name} <{sender}>"
    msg["To"] = ", ".join(to)
    msg.set_content(text)

    with smtplib.SMTP_SSL(host, port, timeout=30) as s:
        s.login(user, pw)
        s.send_message(msg)
    print(f"[OK] sent to {len(to)} recipient(s)")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only Mantis daily line.")
    ap.add_argument("--since", type=_parse_since, default="24h",
                    help="window, e.g. 24h or 7d (default 24h)")
    ap.add_argument("--send", action="store_true", help="email it to BRIEF_TO")
    args = ap.parse_args(argv)

    since = args.since if isinstance(args.since, dt.timedelta) else _parse_since(args.since)

    try:
        text = render(gather(since))
    except MantisConfigError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2
    except requests.RequestException as e:
        print(f"[FAIL] Mantis unreachable: {e}", file=sys.stderr)
        return 1

    print(text)
    if args.send and not _send_email(text):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
