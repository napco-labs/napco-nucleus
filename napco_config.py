"""
NAPCO Nucleus — runtime configuration.

Reads env vars loaded from .env at startup and exposes typed accessors
for the things agent.py and the tools need to reach:

  - SMTP identity for outbound email (report delivery)
  - GitLab API (requirement backlog)
  - Google Drive (requirement audio / PDF ingestion)
  - Groq (Whisper transcription)
  - IMAP (requirement email poll)
  - Sibling test-project paths (MVP-Access-API-Test, E2E, Easy-E2E, Release)
  - Teams webhook (digest post — Power Automate handles inbound)

Per Digital Deputy's pattern: one SMTP identity (business/work),
secrets loaded from .env (never committed), config is read-every-call
(no module-level state) so rotations pick up without a restart.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_HERE = Path(__file__).parent


@dataclass(frozen=True)
class SmtpIdentity:
    from_address: str
    from_name: str           # display name in the From header
    auth_user_env: str
    auth_pass_env: str
    host_env: str
    port_env: str


# The agent sends reports from Mohammad's work email. Display name
# "NAPCO Nucleus" so the From header renders as:
#   NAPCO Nucleus <khasan@ael-bd.com>
# instead of a raw address.
SMTP_DEFAULT = SmtpIdentity(
    from_address=os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "")),
    from_name=os.environ.get("SMTP_FROM_NAME", "NAPCO Nucleus"),
    auth_user_env="SMTP_USER",
    auth_pass_env="SMTP_PASSWORD",
    host_env="SMTP_HOST",
    port_env="SMTP_PORT",
)


def smtp_for(dimension: str | None = None) -> SmtpIdentity:
    """All dimensions ship from the same identity today. The argument is
    kept for symmetry with Digital Deputy's multi-identity split in
    case we need to fork later."""
    return SMTP_DEFAULT


def smtp_from_display() -> str:
    """Formatted 'Name <address>' for the From header — what recipients see."""
    sid = SMTP_DEFAULT
    if sid.from_name and sid.from_address:
        return f"{sid.from_name} <{sid.from_address}>"
    return sid.from_address or sid.from_name


# ─── Sibling test-project paths ─────────────────────────────────────
def projects_root() -> Path:
    """Root dir containing the 4 sibling test projects. Override with
    MVP_PROJECTS_ROOT env var; default is the parent of this file's dir."""
    raw = os.environ.get("MVP_PROJECTS_ROOT")
    return Path(raw) if raw else _HERE.parent


def api_test_dir() -> Path:    return projects_root() / "MVP-Access-API-Test"
def e2e_test_dir() -> Path:    return projects_root() / "MVP-Access-E2E-Test"
def easy_e2e_dir() -> Path:    return projects_root() / "MVP-Access-Easy-E2E-Test"
def release_test_dir() -> Path: return projects_root() / "MVP-Access-Release-Test"


# ─── Reports folder ─────────────────────────────────────────────────
def reports_dir() -> Path:
    """Where generated PDF + artifacts land. Inherits from the API-Test
    project's agent config when possible; falls back to local /reports."""
    try:
        import sys
        sys.path.insert(0, str(api_test_dir() / "agent"))
        import config as api_cfg  # type: ignore
        return Path(api_cfg.REPORTS_DIR)
    except Exception:
        return _HERE / "reports"


# ─── Report recipients ──────────────────────────────────────────────
def report_to() -> list[str]:
    """Who gets the daily report + per-run test reports."""
    raw = (os.environ.get("TEAM_EMAILS")
           or os.environ.get("REPORT_TO")
           or "").strip()
    return [e.strip() for e in raw.split(",") if e.strip()]


# ─── Teams webhook ──────────────────────────────────────────────────
def teams_webhook_url() -> str | None:
    return os.environ.get("TEAMS_WEBHOOK_URL") or None


# ─── Claude CLI path ────────────────────────────────────────────────
def claude_cli_path() -> str | None:
    """Path to the locally-authenticated Claude CLI (so the agent runs
    against the Max subscription, not API credits). Digital Deputy's
    pattern — the SDK is happy with a string or None."""
    raw = os.environ.get(
        "CLAUDE_CLI_PATH",
        os.path.expandvars(r"%USERPROFILE%\.local\bin\claude.exe"),
    )
    return raw if os.path.exists(raw) else None


# ─── GitLab + Drive + IMAP env sanity ───────────────────────────────
def validate_requirement_env() -> dict:
    """Quick sanity check for the requirement-management dimension.
    Returns a dict of what's set / what's missing. Not an assertion."""
    req = [
        "REQ_IMAP_USER", "REQ_IMAP_PASSWORD", "REQ_SENDER_ALLOWLIST",
        "GOOGLE_SERVICE_ACCOUNT_JSON", "GDRIVE_AUDIO_FOLDER_ID",
        "GROQ_API_KEY",
        "GITLAB_PROJECT_ID", "GITLAB_TOKEN",
    ]
    return {k: bool(os.environ.get(k)) for k in req}
