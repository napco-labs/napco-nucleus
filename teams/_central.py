"""Shared helpers for pushing files to the Nucleus central Samba share."""
from __future__ import annotations

import os
import platform
import subprocess


def ensure_smb_auth(unc_root: str) -> None:
    """On Windows: mount the Samba share with explicit creds from .env.

    Reads NUCLEUS_SAMBA_USER and NUCLEUS_SAMBA_PASSWORD from the
    environment.  If both are set, calls ``net use \\\\server\\share``
    so that subsequent shutil.copy2 calls can reach the share without
    relying on a pre-stored cmdkey credential.

    Safe to call multiple times — ``net use`` is idempotent when the
    share is already connected.  No-op on Linux/macOS (the .123 worker
    reaches the share via the container volume mount, not SMB).
    """
    if platform.system() != "Windows":
        return
    user = os.environ.get("NUCLEUS_SAMBA_USER", "").strip()
    pwd = os.environ.get("NUCLEUS_SAMBA_PASSWORD", "").strip()
    if not (user and pwd):
        return

    from pathlib import Path
    parts = Path(unc_root).parts
    if len(parts) < 2 or not parts[0].startswith("\\\\"):
        return
    share = str(Path(parts[0]) / parts[1])  # e.g. \\172.16.205.123\nucleus-central

    try:
        result = subprocess.run(
            ["net", "use", share, f"/user:{user}", pwd],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0 and "already" not in result.stdout.lower():
            # Non-zero but not "already connected" — print but don't raise.
            # The copy will fail with a clearer error if auth truly failed.
            import sys
            print(f"  [smb-auth] net use returned {result.returncode}: "
                  f"{result.stdout.strip() or result.stderr.strip()}",
                  file=sys.stderr)
    except Exception as exc:
        import sys
        print(f"  [smb-auth] net use failed: {exc}", file=sys.stderr)
