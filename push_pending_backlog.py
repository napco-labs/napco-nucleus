"""Push the pending backlog to OpenProject after manual review.

Reads data/requirements/pending-backlog-<date>.json (defaults to today,
or use --date YYYY-MM-DD to pick a specific file), prints each task,
asks for confirmation, then calls publish_tasks_to_backlog.

Usage
    py -3 push_pending_backlog.py                   # today's pending file
    py -3 push_pending_backlog.py --date 2026-07-01 # specific date
    py -3 push_pending_backlog.py --dry-run         # simulate, create nothing
    py -3 push_pending_backlog.py --yes             # skip confirmation prompt
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env", override=True)
sys.path.insert(0, str(_HERE))

_REQ_DIR = _HERE / "data" / "requirements"


def _find_pending(date: str) -> Path | None:
    p = _REQ_DIR / f"pending-backlog-{date}.json"
    return p if p.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=None,
                    help="YYYY-MM-DD. Default: today.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Simulate — print what would be created, create nothing.")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="Skip the confirmation prompt and push immediately.")
    args = ap.parse_args()

    date = args.date or dt.date.today().strftime("%Y-%m-%d")
    pending_path = _find_pending(date)

    if pending_path is None:
        # Try yesterday if today has none (pipeline may have run after midnight)
        yday = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
        alt = _find_pending(yday)
        if alt:
            print(f"[push] No pending file for {date}; using {yday} instead.")
            date = yday
            pending_path = alt
        else:
            print(f"[FAIL] No pending-backlog file found for {date}.")
            print(f"       Run the pipeline first: py -3 agent.py --task verify_session")
            return 1

    payload = json.loads(pending_path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") or []

    if not tasks:
        print(f"[push] {pending_path.name} has 0 tasks — nothing to push.")
        return 0

    print(f"\nPending backlog: {pending_path.name}  ({len(tasks)} task(s))\n")
    for i, t in enumerate(tasks, 1):
        proj = t.get("project", "?")
        title = t.get("title", "(no title)")
        conf = t.get("confidence", "?")
        est = t.get("estimate_hours", "?")
        client = t.get("client_name", "")
        print(f"  {i}. [{proj}] {title}")
        print(f"     confidence={conf}  estimate={est}h  client={client}")

    if args.dry_run:
        print("\n[dry-run] Would push the above tasks. No changes made.")
        return 0

    if not args.yes:
        print()
        ans = input("Push these tasks to OpenProject? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("[push] Aborted.")
            return 0

    # Set DRY_RUN env if needed (already handled above, but belt-and-suspenders)
    if args.dry_run:
        os.environ["NAPCO_NUCLEUS_DRY_RUN"] = "1"

    import openproject_client as op_client
    import memory

    dry = args.dry_run

    _PROJECT_ALIASES = {
        "mvp-access": "mvp-access", "mvp access": "mvp-access",
        "mvpaccess": "mvp-access", "mvp": "mvp-access",
        "cardaccess-4k": "cardaccess-4k", "cardaccess 4k": "cardaccess-4k",
        "card-access-4k": "cardaccess-4k", "ca4k": "cardaccess-4k",
        "cardaccess": "cardaccess-4k",
    }

    def _route(task: dict) -> str:
        raw = (task.get("project") or "").strip().lower()
        return _PROJECT_ALIASES.get(raw, raw or op_client.default_project())

    # Per-project open-WP dedup cache
    _open_cache: dict[str, tuple[dict, set]] = {}

    def _open_for(project: str) -> tuple[dict, set]:
        if project not in _open_cache:
            wps = op_client.list_open_work_packages(project=project)
            by_title = {w["title"].strip().lower(): w for w in wps if w.get("title")}
            _open_cache[project] = (by_title, set(by_title.keys()))
        return _open_cache[project]

    _FEATURE_CATS = {"AccessGroup", "BadgeHolder", "Personnel"}
    created, skipped, failed = [], [], []

    for t in tasks:
        title = (t.get("title") or "").strip()
        description = (t.get("description") or "").strip()
        if not title:
            failed.append({"task": t, "error": "no title"})
            continue

        task_project = _route(t)
        try:
            open_by_title, open_titles = _open_for(task_project)
        except Exception as e:
            failed.append({"title": title, "error": f"list_open_work_packages: {e}"})
            continue

        # Dedup: exact title already open
        if title.lower() in open_titles:
            ex = open_by_title.get(title.lower(), {})
            skipped.append({"title": title, "reason": "already open",
                            "id": ex.get("id"), "url": ex.get("web_url")})
            print(f"  [skip] {title!r} — already in {task_project}")
            continue

        # Dedup: in memory with a known WP id
        prior = memory.search_requirements(title, limit=1)
        if prior and prior[0].get("wp_id"):
            skipped.append({"title": title, "reason": "seen in memory",
                            "url": prior[0].get("wp_url")})
            print(f"  [skip] {title!r} — already in memory (wp_id={prior[0]['wp_id']})")
            continue

        labels = t.get("labels") if isinstance(t.get("labels"), list) else []
        op_cat = next((l for l in labels if l in _FEATURE_CATS), None)
        op_type = "Bug" if "Bug" in labels else "Task"
        est = t.get("estimate_hours") or 3
        src = (t.get("source_ref") or "").strip()

        body_parts = [description, f"\n**Estimate:** ~{est} hours"]
        if src:
            body_parts.append(f"\n*Source: `{src}`*")
        full_body = "\n".join(body_parts)

        if dry:
            print(f"  [dry] would create [{task_project}] {title!r}")
            created.append({"title": title, "project": task_project, "dry_run": True})
            open_titles.add(title.lower())
            continue

        try:
            wp = op_client.create_work_package(
                title=title, description=full_body,
                type=op_type, status="New", category=op_cat,
                project=task_project,
            )
            wp_id = wp.get("id")
            url = wp.get("web_url")
            created.append({"title": title, "id": wp_id,
                            "web_url": url, "project": task_project})
            memory.remember_requirement(
                title=title,
                source=("meetings" if "call/" in src else
                        "email" if "email/" in src else "chat"),
                source_ref=src,
                summary=description[:240],
                wp_id=wp_id, wp_url=url,
            )
            open_titles.add(title.lower())
            print(f"  [OK] Created #{wp_id} [{task_project}] {title!r}")
            if url:
                print(f"       {url}")
        except Exception as e:
            failed.append({"title": title, "error": str(e)})
            print(f"  [FAIL] {title!r}: {e}", file=sys.stderr)

    print(f"\n[push] Done: {len(created)} created, {len(skipped)} skipped, {len(failed)} failed.")

    if failed:
        print("\nFailed items:")
        for f in failed:
            print(f"  - {f.get('title') or f.get('task')}: {f.get('error')}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
