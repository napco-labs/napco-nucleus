"""Google Meet call detection — the Meet twin of voice_daemon's Teams gate.

Scope: MS Teams stays the default and its gate is untouched
(`TEAMS_PROC_NAMES` in voice_daemon). Meet capture is OFF unless
`NUCLEUS_ENABLE_MEET=1` is set, so the mere existence of this file
changes no other dev's machine. Greenlit by Titu 2026-07-29.

Why Meet is harder than Teams
    Teams is its own process, so "ms-teams.exe has an Active audio
    session" is an unambiguous "a call is up". Meet lives inside
    chrome.exe, which also plays YouTube, autoplay ads and notification
    sounds. Browser audio ALONE is not evidence of a call and must never
    be the trigger.

The signals, in order of trust

1. MIC HOLD (primary). Windows tracks live microphone usage per app in
   HKCU\\...\\CapabilityAccessManager\\ConsentStore\\microphone\\NonPackaged.
   While an app is holding the mic, its `LastUsedTimeStop` is 0. Chrome
   holds the mic for the whole Meet call — through silences, and through
   Meet's own mute button, which disables the track without releasing the
   device — and releases it on hangup. That is exactly "in a call", and
   watching a video never sets it.

2. MEET WINDOW (confirming). A visible top-level window owned by a
   browser process whose title looks like Meet. Latched for
   NUCLEUS_MEET_TITLE_LATCH_S (default 300s) because a Chrome window's
   title follows its ACTIVE tab: alt-tab away from the Meet tab mid-call
   and the title stops saying Meet while the call is still up.

3. RENDER AUDIO (fallback only). If the registry read fails we fall back
   to "browser has an Active render session" plus the title latch, with a
   NUCLEUS_MEET_SILENCE_GRACE_S (default 60s) grace so a quiet moment
   doesn't read as a hangup. Weaker — this is the path that can be fooled
   by a video playing with a stale Meet tab open — so it is never used
   while the registry signal is readable.

State values mirror voice_daemon's Teams states exactly:
     1 = Active   — a Meet call is up, safe to START recording
     0 = Inactive — Meet window present but no mic hold; KEEP an
                    in-progress recording alive, never start one
    -1 = None     — no Meet call

Fail-closed: every failure path returns -1, so a broken signal means "not
in a call" and nothing gets recorded by accident.

Self-test (run it while a Meet call is up, then again after hanging up):
    py -3 -m teams.meet
"""
from __future__ import annotations

import os
import re
import time

# Browsers that can host a Meet call. Override per machine with
# NUCLEUS_MEET_BROWSERS=chrome.exe,msedge.exe
BROWSER_PROCS_DEFAULT = ("chrome.exe", "msedge.exe", "brave.exe")

# Meet window titles look like:
#   "Meet - abc-defg-hij - Google Chrome"
#   "Meet - Weekly sync - Google Chrome"
#   "Google Meet - Google Chrome"
# The `meet` + dash form is deliberate: it matches "Meet - x" but NOT
# "Meeting notes.docx", which has no dash after the word.
_MEET_TITLE_RE = re.compile(
    r"(?:^|\W)(?:google\s+meet|meet\.google\.com|meet\s*[-–—]\s*\S)",
    re.IGNORECASE,
)

# A bare Meet room code ("abc-defg-hij") is an ID, not a client name.
_MEET_CODE_RE = re.compile(r"^[a-z]{3}-[a-z]{4}-[a-z]{3}$", re.IGNORECASE)

# Browser suffixes to strip off a window title before using it as a name.
_BROWSER_SUFFIXES = (
    " - Google Chrome", " - Microsoft​ Edge", " - Microsoft Edge",
    " - Brave", " — Mozilla Firefox", " - Mozilla Firefox",
)

_CONSENT_STORE = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager"
    r"\ConsentStore\microphone\NonPackaged"
)

# Module-level latches. The daemon is one long-lived process, so these
# persist across polls, which is the whole point.
_TITLE_LATCH = {"at": 0.0, "title": ""}
_MIC_ACTIVE_LATCH = {"at": 0.0}


def _env_flag(name: str, default: str = "0") -> bool:
    return (os.environ.get(name, default) or "").strip() == "1"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def meet_enabled() -> bool:
    """Master switch. Meet detection does nothing unless this is on."""
    return _env_flag("NUCLEUS_ENABLE_MEET")


def browser_procs() -> set[str]:
    raw = (os.environ.get("NUCLEUS_MEET_BROWSERS") or "").strip()
    if not raw:
        return {p.lower() for p in BROWSER_PROCS_DEFAULT}
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def title_allowed(title: str) -> bool:
    """Optional meeting-name allowlist (NUCLEUS_MEET_TITLE_ALLOW).

    Meet gives us no participant list, so the Teams member allowlist
    (NUCLEUS_INCLUDE_MEMBERS, the 7-person recording boundary) cannot be
    applied to a Meet call — there is nothing to match against. This is
    the only narrowing mechanism Meet has: comma-separated substrings
    matched case-insensitively against the meeting name.

    Unset = every Meet call is recorded (Titu's call, 2026-07-29).
    """
    raw = (os.environ.get("NUCLEUS_MEET_TITLE_ALLOW") or "").strip()
    if not raw:
        return True
    toks = [t.strip().lower() for t in raw.split(",") if t.strip()]
    t = (title or "").lower()
    return any(tok in t for tok in toks)


# --------------------------------------------------------------------------
# Signal 2: a browser window whose title looks like Meet
# --------------------------------------------------------------------------

def _enum_browser_windows() -> list[tuple[int, str]]:
    """Return [(pid, title)] for every visible top-level window.

    ctypes argtypes are set explicitly: HWND is a 64-bit pointer and the
    ctypes default would marshal it as a 32-bit int, truncating handles
    and silently returning empty titles on a 64-bit Python.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    out: list[tuple[int, str]] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append((int(pid.value), buf.value))
        except Exception:
            pass
        return True

    user32.EnumWindows(proc(_cb), 0)
    return out


def meet_window_title() -> str:
    """Title of a LIVE Meet window right now, or "" if none is showing.

    Requires the window's owning process to be a browser, so a document
    or chat message that happens to mention Meet can't trigger anything.
    """
    try:
        import psutil  # ships with pycaw
    except Exception:
        return ""
    wanted = browser_procs()
    try:
        windows = _enum_browser_windows()
    except Exception:
        return ""
    names: dict[int, str] = {}
    for pid, title in windows:
        if not title or not _MEET_TITLE_RE.search(title):
            continue
        if pid not in names:
            try:
                names[pid] = (psutil.Process(pid).name() or "").lower()
            except Exception:
                names[pid] = ""
        if names[pid] in wanted:
            return title
    return ""


def latched_meet_title() -> tuple[str, bool]:
    """(title, live). Refreshes the latch when a Meet window is visible.

    `live` is True when a Meet window is showing this instant, False when
    we're serving a title remembered from within the latch window (the
    user alt-tabbed away from the Meet tab).
    """
    title = meet_window_title()
    if title:
        _TITLE_LATCH["at"] = time.time()
        _TITLE_LATCH["title"] = title
        return (title, True)
    latch_s = _env_float("NUCLEUS_MEET_TITLE_LATCH_S", 300.0)
    if _TITLE_LATCH["title"] and (time.time() - _TITLE_LATCH["at"]) <= latch_s:
        return (str(_TITLE_LATCH["title"]), False)
    return ("", False)


# --------------------------------------------------------------------------
# Signal 1: the browser is holding the microphone (primary)
# --------------------------------------------------------------------------

def browser_mic_active() -> tuple[bool | None, str]:
    """(True/False/None, reason) — is a browser holding the mic right now?

    None means "couldn't read the signal" (not Windows, registry gone,
    permissions), which is distinct from False and sends the caller to
    the render-audio fallback. Values are FILETIMEs; a LastUsedTimeStop
    of 0 means the app has the device open right now.
    """
    try:
        import winreg
    except Exception as e:
        return (None, f"winreg unavailable: {e}")
    wanted = browser_procs()
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CONSENT_STORE)
    except OSError as e:
        return (None, f"consent store unreadable: {e}")
    try:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            # Subkey names are exe paths with '\' replaced by '#'.
            exe = sub.rsplit("#", 1)[-1].lower()
            if exe not in wanted:
                continue
            try:
                k = winreg.OpenKey(root, sub)
            except OSError:
                continue
            try:
                stop, _ = winreg.QueryValueEx(k, "LastUsedTimeStop")
            except OSError:
                continue
            finally:
                k.Close()
            if int(stop) == 0:
                return (True, f"{exe} is holding the mic")
        return (False, "no browser is holding the mic")
    finally:
        root.Close()


# --------------------------------------------------------------------------
# Signal 3: browser render audio (fallback only)
# --------------------------------------------------------------------------

def browser_render_active() -> tuple[bool, str]:
    """(active, reason) — does a browser have an Active render session?

    Fallback signal only. True for a Meet call, but equally true for a
    YouTube tab, which is why it is never the primary trigger.
    """
    try:
        from pycaw.pycaw import AudioUtilities
    except Exception as e:
        return (False, f"pycaw import failed: {e}")
    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception as e:
        return (False, f"GetAllSessions failed: {e}")
    wanted = browser_procs()
    for s in sessions:
        if not s.Process:
            continue
        try:
            name = (s.Process.name() or "").lower()
        except Exception:
            continue
        if name in wanted and s.State == 1:
            return (True, f"{name} render session Active")
    return (False, "no browser render session Active")


# --------------------------------------------------------------------------
# Combined state
# --------------------------------------------------------------------------

def meet_call_state() -> tuple[int, str, str]:
    """(state, reason, meeting_title) using the same state codes as Teams.

    Fail-closed: anything unexpected returns -1.
    """
    if not meet_enabled():
        return (-1, "meet disabled (NUCLEUS_ENABLE_MEET != 1)", "")
    try:
        title, live = latched_meet_title()
        mic, mic_reason = browser_mic_active()

        if mic is True:
            _MIC_ACTIVE_LATCH["at"] = time.time()
            if title:
                where = "visible" if live else "latched"
                return (1, f"{mic_reason}, Meet window {where}", title)
            # Mic held by a browser but no Meet window anywhere: some other
            # browser call (Zoom web, Whereby). Out of scope, don't record.
            return (-1, f"{mic_reason} but no Meet window", "")

        if mic is False:
            # Authoritative "not in a call". A Meet window may still be
            # sitting open on the leave screen -> Inactive, which keeps an
            # in-progress recording alive but never starts one.
            if title and live:
                return (0, "Meet window open, mic not held", title)
            return (-1, mic_reason, "")

        # mic is None -> registry signal unreadable, use the weaker path.
        render, render_reason = browser_render_active()
        grace_s = _env_float("NUCLEUS_MEET_SILENCE_GRACE_S", 60.0)
        within_grace = (time.time() - _MIC_ACTIVE_LATCH["at"]) <= grace_s
        if render and title:
            _MIC_ACTIVE_LATCH["at"] = time.time()
            return (1, f"[fallback] {render_reason}, Meet window present", title)
        if title and within_grace:
            return (0, "[fallback] Meet window present, audio idle", title)
        if title and live:
            return (0, "[fallback] Meet window open, no audio", title)
        return (-1, f"[fallback] {render_reason}", "")
    except Exception as e:
        return (-1, f"meet state exception: {e}", "")


def meeting_name_from_title(title: str) -> str:
    """Best-effort client/meeting name from a Meet window title.

    "Meet - Weekly sync - Google Chrome" -> "Weekly sync"
    "Meet - abc-defg-hij - Google Chrome" -> ""  (a room code is an ID,
    not a name; the caller falls back to "(unknown)", which the pipeline
    already handles.)
    """
    t = (title or "").strip()
    if not t:
        return ""
    for suffix in _BROWSER_SUFFIXES:
        if t.lower().endswith(suffix.lower()):
            t = t[: -len(suffix)].strip()
            break
    # A bare join URL is an ID too ("meet.google.com/abc-defg-hij"), which
    # is what the title shows before the meeting is named.
    t = re.sub(r"^https?://", "", t, flags=re.IGNORECASE).strip()
    if re.match(r"^meet\.google\.com/", t, flags=re.IGNORECASE):
        return ""
    t = re.sub(r"^(?:google\s+)?meet\s*[-–—]\s*", "", t,
               flags=re.IGNORECASE).strip()
    if not t or t.lower() in ("meet", "google meet"):
        return ""
    if _MEET_CODE_RE.match(t):
        return ""
    return t


def main() -> int:
    """Self-test: print every signal so a live call can be verified by eye."""
    # Load .env the way the daemon does, so the self-test reports what the
    # daemon would actually see rather than a bare environment.
    try:
        from pathlib import Path
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env", override=True)
    except Exception:
        pass
    print("NUCLEUS_ENABLE_MEET =", os.environ.get("NUCLEUS_ENABLE_MEET", "(unset)"))
    print("browsers watched     =", ", ".join(sorted(browser_procs())))
    mic, mic_reason = browser_mic_active()
    print(f"mic hold             = {mic}  [{mic_reason}]")
    title = meet_window_title()
    print(f"meet window (live)   = {title or '(none)'}")
    render, render_reason = browser_render_active()
    print(f"render audio         = {render}  [{render_reason}]")
    st, reason, t = meet_call_state()
    label = {1: "ACTIVE (would record)", 0: "INACTIVE (would keep, not start)",
             -1: "NONE (would not record)"}.get(st, str(st))
    print(f"-> state {st} = {label}")
    print(f"   reason: {reason}")
    print(f"   meeting title: {t or '(none)'}")
    print(f"   client name  : {meeting_name_from_title(t) or '(unknown)'}")
    print(f"   title allowed: {title_allowed(t)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
