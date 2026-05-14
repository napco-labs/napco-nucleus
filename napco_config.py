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

import email.message
import email.utils
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


# ─── Central store (multi-dev capture aggregation) ─────────────────
def central_root() -> Path | None:
    """Root of the central capture store (UNC or local path).

    Set NUCLEUS_CENTRAL_PATH in .env to enable per-dev push of WAVs +
    chat docs + metadata. Unset = each dev keeps captures local only.
    Typical value: \\\\172.16.205.209\\nucleus-central  (the agent VM
    where Claude is authenticated and identify runs).
    """
    raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    return Path(raw) if raw else None


def dev_name() -> str:
    """Per-dev identifier used as the top-level folder under central_root.

    Defaults to the OS username so two teammates never clash. Override
    with NUCLEUS_DEV_NAME if you want a friendly label (e.g. 'salman').
    """
    raw = (os.environ.get("NUCLEUS_DEV_NAME") or "").strip()
    if raw:
        return raw
    # Fallback: derive from OS username. Strip + lowercase so different
    # PCs ($USERNAME may be "Kamrul.Hasan" / "kamrul.hasan" / etc.) end
    # up in ONE folder on central, not three.
    fallback = (os.environ.get("USERNAME")
                or os.environ.get("USER")
                or "unknown")
    return fallback.strip().lower().replace(" ", "-") or "unknown"


def central_dev_day_dir(day: str | None = None) -> Path | None:
    """Helper: <central>/<dev>/<YYYY-MM-DD>/. Returns None if central
    isn't configured. Day defaults to today (local time)."""
    root = central_root()
    if root is None:
        return None
    if day is None:
        from datetime import date
        day = date.today().strftime("%Y-%m-%d")
    return root / dev_name() / day


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


# ─── Requirement-management roster filter ──────────────────────────
#
# Rule set 2026-05-12 (Titu's wording): any one of these emails
# included in sender or receiver can be a requirements email; one or
# more than one of these emails as sender or receiver counts as a
# requirement email. Operationally: process only if >=1 roster address
# is in From / To / Cc / Bcc. Zero matches => skip.
#
# Lives in code (not env) so all dev machines share one source of
# truth — update via PR when the working group changes.
#
# NAPCO Security (client) + AEL (us) working group around the
# "Integrations Spreadsheet" engagement. Lower-cased; matching is
# case-insensitive on the bare address (display names ignored).
REQUIREMENT_ROSTER: tuple[str, ...] = (
    # NAPCO Security
    "mcarrieri@napcosecurity.com",   # Michael Carrieri
    "siva@napcosecurity.com",         # Thangarajah Sivapokaran
    "rgoldsobel@napcosecurity.com",   # Richard Goldsobel
    "safiroz@napcosecurity.com",      # Salman A. Firoz
    "rzhu@napcosecurity.com",         # Robert Zhu
    # AEL
    "assad@ael-bd.com",               # Assaduz Zaman
    "arzaman@ael-bd.com",             # Atikur Zaman
    "arhabib@ael-bd.com",             # Ahsan Habib
    "ihasan@ael-bd.com",              # Isruk Hasan
    "khasan@ael-bd.com",              # Mohammad Kamrul Hasan (Titu)
    "mferdows@ael-bd.com",            # Mostafa J Ferdows
    "samin@ael-bd.com",               # Sheikh Amin
)


def requirement_roster() -> set[str]:
    """Lowercased roster as a set, optionally extended with extras from
    the NUCLEUS_ROSTER_EXTRA env var (comma-separated). Use the env var
    for ad-hoc additions on a single machine — promote to the code
    constant once it's a permanent change."""
    extra_raw = (os.environ.get("NUCLEUS_ROSTER_EXTRA") or "").strip()
    extras = {a.strip().lower() for a in extra_raw.split(",") if a.strip()}
    return {a.lower() for a in REQUIREMENT_ROSTER} | extras


def _msg_addresses(msg: email.message.Message) -> set[str]:
    """Bare lowercased addresses from From + To + Cc + Bcc headers."""
    headers: list[str] = []
    for field in ("From", "To", "Cc", "Bcc"):
        for raw in msg.get_all(field, []) or []:
            if raw:
                headers.append(raw)
    out: set[str] = set()
    for _name, addr in email.utils.getaddresses(headers):
        a = (addr or "").strip().lower()
        if a:
            out.add(a)
    return out


def email_passes_roster_filter(msg: email.message.Message) -> bool:
    """True iff at least one roster address appears in From/To/Cc/Bcc."""
    return bool(_msg_addresses(msg) & requirement_roster())


# ─── OpenProject + Drive + IMAP env sanity ─────────────────────────
def validate_requirement_env() -> dict:
    """Quick sanity check for the requirement-management dimension.
    Returns a dict of what's set / what's missing. Not an assertion."""
    req = [
        "REQ_IMAP_USER", "REQ_IMAP_PASSWORD", "REQ_SENDER_ALLOWLIST",
        "GDRIVE_AUDIO_FOLDER_ID",
        "GROQ_API_KEY",
        "OPENPROJECT_URL", "OPENPROJECT_PROJECT_ID", "OPENPROJECT_API_KEY",
    ]
    status = {k: bool(os.environ.get(k)) for k in req}
    # Google credentials can come from either a file path (preferred,
    # DD-style) OR an inline JSON blob (legacy / GHA secret). Treat
    # either one as satisfying the requirement.
    status["GOOGLE_CREDENTIALS"] = bool(
        os.environ.get("GOOGLE_CREDENTIALS_PATH")
        or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    )
    return status
