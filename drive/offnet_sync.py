r"""
Off-network → central mirror.

For devs whose PC is NOT on the AEL LAN, the normal SMB push to the
central Samba share (\\172.16.205.123\nucleus-central) cannot work. Those
PCs instead point NUCLEUS_CENTRAL_PATH at a *local Google Drive-synced
folder* (e.g. G:\My Drive\NN-Offnet), so record_call.py / push_chat.py
drop their artifacts there and Google Drive for Desktop carries them up
to the cloud.

This module is the other side of that bridge: it runs ON central, reads
the same Drive folder via the service account, and mirrors every new file
DOWN into /srv/nucleus-central — preserving the exact relative layout the
dev produced:

    NN-Offnet/<Dev>/<YYYY-MM-DD>/calls/<session>_mic.wav
    NN-Offnet/<Dev>/<YYYY-MM-DD>/calls/<session>_speaker.wav
    NN-Offnet/<Dev>/<YYYY-MM-DD>/calls/<session>.json
    NN-Offnet/<Dev>/<YYYY-MM-DD>/chat/chat_<HHMM>-<HHMM>.docx
    NN-Offnet/<Dev>/<YYYY-MM-DD>/chat/attachments/...

Because the landing layout is byte-identical to what an on-LAN dev's SMB
push produces, the EXISTING transcribe loop + collect_central pipeline
pick the off-net dev up with no further special-casing — dual-track
Google STT, You/Other transcript, requirement identification, all of it.

This module does NOT transcribe or classify. It is a pure file mover.

Env vars:
    NN_OFFNET_FOLDER_ID     Drive folder ID of the shared "NN-Offnet"
                            root (from its URL). Required.
    NN_OFFNET_DEST          Local destination root. Defaults to
                            /data/nucleus-central (the container's mount
                            of /srv/nucleus-central on the host).
    NN_OFFNET_TRASH         "1"/"true"/"yes" (default) → trash each file
                            on Drive after it is safely mirrored, to
                            reclaim Drive space and avoid re-listing.
                            Set to "0" to keep the Drive copies.
    GOOGLE_CREDENTIALS_PATH / GOOGLE_SERVICE_ACCOUNT_JSON
                            Service-account key (same loader as
                            drive_ingester). The SA must have EDITOR on
                            the NN-Offnet folder (Editor, not Viewer, so
                            it can trash after ingest).

State:
    data/requirements/offnet-sync-processed.json
        { "processed": [{"file_id", "rel_path", "synced_at", "bytes"}] }
    A Drive file ID is mirrored at most once.

Run standalone:
    py -3 -m drive.offnet_sync
    py -3 -m drive.offnet_sync --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Reuse the service-account loader + download helper from the sibling
# ingester so there is exactly one Drive-auth code path.
from drive.drive_ingester import _drive_service, _download_file

_HERE = Path(__file__).parent.parent  # drive/<file> -> NN root
load_dotenv(_HERE / ".env", override=True)

logger = logging.getLogger(__name__)

STATE_PATH = _HERE / "data" / "requirements" / "offnet-sync-processed.json"
DEFAULT_DEST = "/data/nucleus-central"
FOLDER_MIME = "application/vnd.google-apps.folder"


# ───────────────────────── state helpers ──────────────────────────

def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"processed": []}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "processed" not in data:
            return {"processed": []}
        return data
    except Exception:
        return {"processed": []}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)
    tmp.replace(STATE_PATH)  # atomic on the same filesystem


def _seen_ids(state: dict) -> set[str]:
    return {e.get("file_id") for e in state.get("processed", [])}


# ───────────────────────── Drive walk ─────────────────────────────

def _list_children(drive, folder_id: str) -> list[dict]:
    """All non-trashed direct children (files AND subfolders) of a folder."""
    q = f"'{folder_id}' in parents and trashed = false"
    out: list[dict] = []
    page_token = None
    while True:
        resp = drive.files().list(
            q=q,
            fields=("nextPageToken,"
                    " files(id, name, mimeType, size, modifiedTime)"),
            pageSize=200,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            orderBy="name",
        ).execute()
        out.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def _walk(drive, folder_id: str, rel: Path = Path(".")):
    """Depth-first yield of (file_meta, rel_path) for every file under
    folder_id, with rel_path relative to the off-net root. Subfolders are
    recursed; Google-native docs (no real bytes) are skipped."""
    for child in _list_children(drive, folder_id):
        name = child.get("name") or child["id"]
        if child.get("mimeType") == FOLDER_MIME:
            yield from _walk(drive, child["id"], rel / name)
        elif (child.get("mimeType") or "").startswith("application/vnd.google-apps"):
            # Google-native (Docs/Sheets) have no downloadable bytes; the
            # off-net pipeline only ever produces real binaries (.wav/.json/
            # .docx), so anything native here is stray — skip it.
            logger.info(f"skip google-native {rel / name} ({child['mimeType']})")
        else:
            yield child, rel / name


def _trash(drive, file_id: str) -> None:
    drive.files().update(fileId=file_id, body={"trashed": True},
                         supportsAllDrives=True).execute()


# ─────────────────────────── Main ─────────────────────────────────

def sync_offnet(dry_run: bool = False) -> dict:
    folder_id = os.getenv("NN_OFFNET_FOLDER_ID")
    if not folder_id:
        return {"error": "NN_OFFNET_FOLDER_ID not set", "synced": 0, "files": []}

    dest_root = Path(os.getenv("NN_OFFNET_DEST", DEFAULT_DEST))
    trash = os.getenv("NN_OFFNET_TRASH", "1").strip().lower() in ("1", "true", "yes")

    drive = _drive_service()
    state = _load_state()
    seen = _seen_ids(state)

    results: list[dict] = []
    for meta, rel_path in _walk(drive, folder_id):
        fid = meta["id"]
        if fid in seen:
            continue  # already mirrored — never pull the same byte twice

        dst = dest_root / rel_path
        size_mb = int(meta.get("size") or 0) / 1e6
        logger.info(f"mirror {rel_path}  ({size_mb:.1f} MB)  id={fid}")

        if dry_run:
            results.append({"rel_path": rel_path.as_posix(), "id": fid,
                            "dry_run": True})
            continue

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Download to a temp sibling, then atomically rename — so a
            # half-downloaded WAV is never seen as "complete" by the
            # transcribe loop scanning the same tree.
            tmp = dst.with_name(dst.name + ".part")
            _download_file(drive, fid, tmp)
            tmp.replace(dst)
        except Exception as e:
            logger.exception(f"mirror failed for {rel_path}")
            results.append({"rel_path": rel_path.as_posix(), "id": fid,
                            "error": str(e)})
            try:
                if 'tmp' in dir() and tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            continue

        state["processed"].append({
            "file_id": fid,
            "rel_path": rel_path.as_posix(),
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "bytes": int(meta.get("size") or 0),
        })
        seen.add(fid)
        _save_state(state)  # persist after EACH file → crash-safe, idempotent

        if trash:
            try:
                _trash(drive, fid)
            except Exception as e:
                # Non-fatal: the file is safely on central; it just lingers
                # on Drive. State already records it so we won't re-pull.
                logger.warning(f"trash failed for {rel_path} (id={fid}): {e}")

        results.append({"rel_path": rel_path.as_posix(), "id": fid,
                        "dest": str(dst), "bytes": int(meta.get("size") or 0)})

    return {
        "synced": sum(1 for r in results if "dest" in r),
        "errors": sum(1 for r in results if "error" in r),
        "files": results,
    }


def _cli() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="List + report what would be mirrored, but do not "
                        "download, write, or trash anything.")
    args = p.parse_args()
    out = sync_offnet(dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    if out.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    _cli()
