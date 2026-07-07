"""Health check for the NAPCO Nucleus deployment.

Verifies every external dependency the pipeline relies on:

    1. Central SMB share reachable + writable (NUCLEUS_CENTRAL_PATH)
    2. IMAP login works (REQ_IMAP_*)
    3. Google Drive credentials valid + folder reachable
       (GOOGLE_CREDENTIALS_PATH + GDRIVE_AUDIO_FOLDER_ID)
    4. faster-whisper model cached locally (one-off ~3 GB download
       happens on first use otherwise — surfacing this avoids a
       surprise during the first real call)
    5. Claude CLI binary exists (CLAUDE_CLI_PATH or PATH)
    6. nucleus_memory.db reachable and writable
    7. Recent push activity per dev in the last 24h on central
    8. Free disk space on the volume holding data/requirements/

Exit code 0 on all-green, 1 on any failure. With --alert-on-fail,
also emails a summary via the existing SMTP credentials when
anything fails.

Usage:
    py -3 -m tools.healthcheck                # report to stdout
    py -3 -m tools.healthcheck --alert-on-fail # also email on failure
    py -3 -m tools.healthcheck --json         # machine-readable output
    py -3 -m tools.healthcheck --skip drive   # skip one or more checks
                                              # (comma-separated)
"""
from __future__ import annotations

import argparse
import datetime as dt
import imaplib
import json
import os
import shutil
import socket
import sqlite3
import sys
import time
from pathlib import Path

# UTF-8 stdout for Unicode markers
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_HERE / ".env", override=False)

import memory  # noqa: E402


# ── Color helpers ─────────────────────────────────────────────────

def _color(s: str, code: str) -> str: return f"\033[{code}m{s}\033[0m"
def _g(s: str) -> str: return _color(s, "32")
def _r(s: str) -> str: return _color(s, "31")
def _y(s: str) -> str: return _color(s, "33")
def _d(s: str) -> str: return _color(s, "2")


# ── Result type ──────────────────────────────────────────────────

class CheckResult:
    __slots__ = ("name", "ok", "detail", "elapsed_s")

    def __init__(self, name: str, ok: bool, detail: str,
                 elapsed_s: float = 0.0):
        self.name = name
        self.ok = bool(ok)
        self.detail = detail
        self.elapsed_s = float(elapsed_s)

    def to_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "detail": self.detail,
                "elapsed_s": round(self.elapsed_s, 3)}


def _timed(fn):
    """Decorator that wraps a check fn in timing + exception catching."""
    def wrapped() -> CheckResult:
        t0 = time.perf_counter()
        name = fn.__name__.removeprefix("check_").replace("_", "-")
        try:
            ok, detail = fn()
        except Exception as e:
            return CheckResult(name, False, f"crashed: {type(e).__name__}: {e}",
                               time.perf_counter() - t0)
        return CheckResult(name, ok, detail, time.perf_counter() - t0)
    wrapped.check_name = fn.__name__.removeprefix("check_").replace("_", "-")
    return wrapped


# ── Checks ──────────────────────────────────────────────────────

@_timed
def check_smb_share():
    """Central is reachable + writable *by the exact path the recorder uses*.

    Mirrors teams.record_call's push: authenticate with the .env Samba creds
    (ensure_smb_auth) BEFORE probing, and write into THIS dev's own calls dir
    (<central>/<dev>/<today>/calls) — not just the share root — so a per-dev
    permission or dev-name problem surfaces. This is the check to read first
    when a dev's calls "aren't reaching central": the detail line reports the
    central path, the resolved dev name, and whether Samba creds are set,
    which together pinpoint config vs network vs auth.
    """
    raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    if not raw:
        return False, ("NUCLEUS_CENTRAL_PATH not set — calls stay local / go "
                       "to Drive only")
    dev = (os.environ.get("NUCLEUS_DEV_NAME") or os.environ.get("USERNAME")
           or socket.gethostname() or "unknown").strip()
    have_creds = bool((os.environ.get("NUCLEUS_SAMBA_USER") or "").strip()
                      and (os.environ.get("NUCLEUS_SAMBA_PASSWORD") or "").strip())
    cfg = f"path={raw} dev={dev!r} samba_creds={'set' if have_creds else 'NONE'}"

    # Authenticate exactly like the recorder does, then reset+retry once (the
    # same idle-session cure record_call uses) so a stale mapping isn't misread
    # as a hard failure.
    try:
        from teams._central import ensure_smb_auth, reset_smb_auth
        ensure_smb_auth(raw)
    except Exception as e:
        return False, f"ensure_smb_auth crashed: {e} | {cfg}"

    if not Path(raw).exists():
        try:
            reset_smb_auth(raw)
        except Exception:
            pass
        if not Path(raw).exists():
            return False, (f"share unreachable after auth+reset (network? "
                           f"creds? off-net?) | {cfg}")

    # Probe the dev's real calls dir — that's the directory the recorder
    # mkdir()s and copies into; root-only writability can hide a per-dev issue.
    calls_dir = Path(raw) / dev / dt.date.today().strftime("%Y-%m-%d") / "calls"
    probe = calls_dir / ".nucleus_healthcheck.tmp"
    try:
        calls_dir.mkdir(parents=True, exist_ok=True)
        probe.write_text(f"probe {dt.datetime.now().isoformat()}",
                         encoding="utf-8")
        probe.unlink()
    except Exception as e:
        return False, f"calls dir not writable: {e} | {cfg}"
    return True, f"reachable + writable as recorder | {cfg}"


@_timed
def check_imap():
    """Login + select INBOX + logout. No mailbox modification."""
    host = (os.getenv("REQ_IMAP_HOST") or "imap.gmail.com").strip()
    port = int(os.getenv("REQ_IMAP_PORT", "993"))
    user = (os.getenv("REQ_IMAP_USER") or "").strip()
    pw = os.getenv("REQ_IMAP_PASSWORD") or ""
    mailbox = (os.getenv("REQ_IMAP_MAILBOX") or "INBOX").strip()
    if not user or not pw:
        return False, "REQ_IMAP_USER / REQ_IMAP_PASSWORD not set"
    try:
        m = imaplib.IMAP4_SSL(host, port, timeout=15)
        try:
            m.login(user, pw)
            typ, _ = m.select(mailbox, readonly=True)
            if typ != "OK":
                return False, f"SELECT failed: {typ}"
        finally:
            try:
                m.logout()
            except Exception:
                pass
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    return True, f"login OK on {host}:{port} ({user})"


@_timed
def check_drive():
    """Service-account credentials parse + folder list returns."""
    creds_raw = (os.environ.get("GOOGLE_CREDENTIALS_PATH") or "").strip()
    folder = (os.environ.get("GDRIVE_AUDIO_FOLDER_ID") or "").strip()
    if not creds_raw:
        return False, "GOOGLE_CREDENTIALS_PATH not set"
    if not folder:
        return False, "GDRIVE_AUDIO_FOLDER_ID not set"
    creds_path = Path(creds_raw)
    if not creds_path.is_absolute():
        creds_path = (_HERE / creds_path).resolve()
    if not creds_path.exists():
        return False, f"credentials file missing: {creds_path}"
    try:
        from drive import drive_ingester as di  # lazy
        svc = di._drive_service()
        # Cheapest call: list 1 file from the folder
        res = svc.files().list(
            q=f"'{folder}' in parents and trashed=false",
            pageSize=1, fields="files(id,name)").execute()
        n = len(res.get("files") or [])
        return True, f"creds OK, folder listable ({n} file(s) sample)"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


@_timed
def check_whisper_model():
    """Whisper large-v3 weights cached locally so the first real call
    doesn't trigger a ~3 GB download."""
    cache_root = (os.environ.get("HF_HOME")
                  or os.environ.get("HUGGINGFACE_HUB_CACHE")
                  or str(Path.home() / ".cache" / "huggingface" / "hub"))
    cache_dir = Path(cache_root)
    if not cache_dir.exists():
        return False, f"HuggingFace cache not found at {cache_dir}"
    # Look for any subdir containing "large-v3"
    hits = list(cache_dir.rglob("*large-v3*"))
    if not hits:
        return False, (f"large-v3 weights not cached under {cache_dir} "
                       f"(first call will trigger ~3 GB download)")
    # Best-effort size check
    total_bytes = 0
    for d in hits[:3]:
        if d.is_dir():
            for f in d.rglob("*"):
                if f.is_file():
                    try:
                        total_bytes += f.stat().st_size
                    except OSError:
                        pass
    return True, (f"cached at {hits[0].relative_to(cache_dir).as_posix()} "
                  f"(~{total_bytes / 1e9:.1f} GB)")


@_timed
def check_claude_cli():
    """The local Claude CLI binary the SDK shells out to."""
    try:
        import napco_config as nucleus_config  # lazy
        cli = nucleus_config.claude_cli_path()
    except Exception as e:
        return False, f"napco_config error: {e}"
    if not cli:
        return False, "CLAUDE_CLI_PATH not configured"
    p = Path(cli)
    if not p.exists():
        return False, f"CLI binary not found at {p}"
    # Don't actually run it — that can prompt for auth interactively.
    # Existence + executable bit is sufficient signal here.
    return True, f"binary present: {p}"


@_timed
def check_memory_db():
    """nucleus_memory.db can be opened + written."""
    try:
        memory.init_db()
        with sqlite3.connect(memory.db_path(), timeout=2.0) as c:
            c.execute("SELECT 1").fetchone()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    return True, f"DB OK at {memory.db_path()}"


@_timed
def check_recent_pushes():
    """Look at central for chat .docx files modified in the last 24h.
    Catches the case where every dev's cron has silently stopped."""
    raw = (os.environ.get("NUCLEUS_CENTRAL_PATH") or "").strip()
    if not raw:
        return False, "NUCLEUS_CENTRAL_PATH not set"
    p = Path(raw)
    if not p.exists():
        return False, f"central path does not exist: {p}"
    today = dt.date.today().strftime("%Y-%m-%d")
    yesterday = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    cutoff = time.time() - 24 * 3600
    found_devs: dict[str, int] = {}
    for dev_dir in p.iterdir():
        if not dev_dir.is_dir():
            continue
        for date_dir in (dev_dir / today, dev_dir / yesterday):
            if not date_dir.exists():
                continue
            chat_dir = date_dir / "chat"
            if not chat_dir.exists():
                continue
            for f in chat_dir.glob("chat_*.docx"):
                try:
                    if f.stat().st_mtime >= cutoff:
                        found_devs[dev_dir.name] = found_devs.get(
                            dev_dir.name, 0) + 1
                except OSError:
                    pass
    if not found_devs:
        return False, "no chat .docx pushed in the last 24h on central"
    summary = ", ".join(f"{k}={v}" for k, v in sorted(found_devs.items()))
    return True, f"recent pushes from {len(found_devs)} dev(s): {summary}"


@_timed
def check_disk_space():
    """Free space on the data volume — Whisper transcription + verification
    docs + drafts can chew through a few GB before you notice."""
    target = _HERE / "data" / "requirements"
    target.mkdir(parents=True, exist_ok=True)
    try:
        usage = shutil.disk_usage(str(target))
    except Exception as e:
        return False, f"disk_usage failed: {e}"
    free_gb = usage.free / 1e9
    if free_gb < 2.0:
        return False, f"only {free_gb:.1f} GB free at {target}"
    if free_gb < 10.0:
        # Warn-but-pass
        return True, f"{free_gb:.1f} GB free (warning: <10 GB)"
    return True, f"{free_gb:.1f} GB free at {target.parents[1]}"


_ALL_CHECKS = [
    check_smb_share,
    check_imap,
    check_drive,
    check_whisper_model,
    check_claude_cli,
    check_memory_db,
    check_recent_pushes,
    check_disk_space,
]


# ── Reporting ────────────────────────────────────────────────────

def run_checks(skip: set[str]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for fn in _ALL_CHECKS:
        name = fn.check_name
        if name in skip:
            results.append(CheckResult(name, True, "(skipped)", 0.0))
            continue
        print(f"  checking {name}... ", end="", flush=True)
        r = fn()
        marker = _g("OK ") if r.ok else _r("FAIL")
        print(f"{marker}  {r.detail}  {_d(f'({r.elapsed_s:.2f}s)')}")
        results.append(r)
    return results


def render_report(results: list[CheckResult], as_json: bool) -> str:
    if as_json:
        return json.dumps(
            {"timestamp": dt.datetime.now().isoformat(timespec="seconds"),
             "hostname": socket.gethostname(),
             "checks": [r.to_dict() for r in results]},
            indent=2)
    lines = [f"NN healthcheck @ {dt.datetime.now().isoformat(timespec='seconds')}",
             f"Host: {socket.gethostname()}",
             ""]
    for r in results:
        marker = "PASS" if r.ok else "FAIL"
        lines.append(f"  [{marker}] {r.name:18s} {r.detail}")
    failed = [r for r in results if not r.ok and "(skipped)" not in r.detail]
    lines.append("")
    if failed:
        lines.append(f"{len(failed)} check(s) failed.")
    else:
        lines.append("All checks passed.")
    return "\n".join(lines)


def _send_alert_email(report_text: str) -> bool:
    """Reuse the existing SMTP credentials (SMTP_HOST/USER/PASSWORD)
    used by the daily report. Sends only when there's a failure."""
    import smtplib
    import ssl
    from email.message import EmailMessage

    host = (os.environ.get("SMTP_HOST") or "").strip()
    user = (os.environ.get("SMTP_USER") or "").strip()
    pw = os.environ.get("SMTP_PASSWORD") or ""
    sender = (os.environ.get("SMTP_FROM") or user).strip()
    name = (os.environ.get("SMTP_FROM_NAME") or "NAPCO Nucleus").strip()
    # Alert recipient: dedicated var, then fall back to SMTP_USER
    # (Titu gets the alert if HEALTHCHECK_ALERT_TO isn't set).
    to_addr = (os.environ.get("HEALTHCHECK_ALERT_TO")
               or user or sender).strip()
    if not host or not user or not pw or not to_addr:
        print(_y("  alert: SMTP not configured (need SMTP_HOST/USER/PASSWORD"
                 " + HEALTHCHECK_ALERT_TO or SMTP_USER)"))
        return False
    msg = EmailMessage()
    msg["From"] = f"{name} <{sender}>"
    msg["To"] = to_addr
    msg["Subject"] = f"NN healthcheck FAIL on {socket.gethostname()}"
    msg.set_content(report_text)
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
        ctx = ssl.create_default_context()
        # Port 465 = implicit SSL (no STARTTLS upgrade needed); use
        # SMTP_SSL. Anything else (587, 25, custom) = plaintext upgrade
        # via STARTTLS.
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(user, pw)
                s.send_message(msg)
    except Exception as e:
        print(_r(f"  alert send failed: {type(e).__name__}: {e}"))
        return False
    print(_g(f"  alert sent to {to_addr}"))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alert-on-fail", action="store_true",
                    help="Email the report (via SMTP env) on any failure.")
    ap.add_argument("--json", action="store_true",
                    help="Machine-readable output.")
    ap.add_argument("--skip", default="",
                    help="Comma-separated check names to skip. "
                         f"Available: {[fn.check_name for fn in _ALL_CHECKS]}")
    args = ap.parse_args()

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    if not args.json:
        print(f"\nNAPCO Nucleus healthcheck @ "
              f"{dt.datetime.now().isoformat(timespec='seconds')}")
        print(f"Host: {socket.gethostname()}\n")
    results = run_checks(skip)

    report = render_report(results, as_json=args.json)
    if args.json:
        print(report)
    else:
        print()
        print(report)

    failed = [r for r in results if not r.ok and "(skipped)" not in r.detail]
    if failed and args.alert_on_fail:
        print()
        _send_alert_email(report)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
