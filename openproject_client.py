"""
NAPCO Nucleus — OpenProject API client.

Replaces gitlab_client.py (deleted 2026-04-28) so requirement-management
publishes to OpenProject Work Packages instead of GitLab Issues.

Public surface (intentionally narrow — same shape as the old GitLab
client so tools/requirements.py needs minimal changes):
    list_open_work_packages(*, project=None)  → [{title, id, web_url}]
    create_work_package(title, description, *, category=None,
                         type='Task', status='New', project=None)  → dict
    update_work_package(id, *, title=None, status=None,
                         category=None, project=None)               → dict
    add_work_package_comment(id, body)                              → dict
    default_project()                                               → str

Multi-project (2026-06-25): every public call takes an optional
`project` (slug or numeric id). When omitted it falls back to
`OPENPROJECT_PROJECT_ID`. This lets one run publish to BOTH
`mvp-access` and `cardaccess-4k` — requirements are routed per-task by
the caller (see tools/requirements.publish_tasks_to_backlog). Types and
categories are PER-PROJECT (cardaccess-4k has no categories; mvp-access
has AccessGroup/BadgeHolder/Personnel), so their lookup caches are keyed
by project; statuses and priorities are global.

Conventions:
    * HAL+JSON. References between resources are URIs in `_links` dicts.
    * Auth: HTTP Basic with username='apikey', password=<API key>.
    * Required env: OPENPROJECT_URL, OPENPROJECT_PROJECT_ID,
                    OPENPROJECT_API_KEY.
    * `OPENPROJECT_PROJECT_ID` (and the per-call `project`) accept either
      the numeric id or the project slug (`mvp-access` works);
      OpenProject's REST API resolves both transparently.

Errors:
    OpenProjectConfigError — env vars missing or invalid.
    OpenProjectAPIError    — non-2xx response from the OpenProject API.

NOT a tool — this module is a low-level HTTP wrapper. Tools live under
tools/ and orchestrate this client.

Note: the live instance (openproject.ael-bd.com) is fronted by
Cloudflare, whose bot rule 403s the bare `urllib` user-agent (error
1010). `requests`' default UA passes, but we set an explicit UA header
anyway so a future CF tightening can't silently break publishing.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests
from requests.auth import HTTPBasicAuth


logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30

# Explicit UA so Cloudflare's "banned client signature" rule (the one
# that 1010s bare urllib) can never catch us — see module docstring.
_HEADERS = {"User-Agent": "NAPCO-Nucleus/1.0 (requirement-management)"}


class OpenProjectError(RuntimeError):
    pass


class OpenProjectConfigError(OpenProjectError):
    pass


class OpenProjectAPIError(OpenProjectError):
    pass


# ─── Config ───────────────────────────────────────────────────────────

def _config(project: str | None = None) -> tuple[str, str, str, HTTPBasicAuth]:
    """Resolve (host, project, key, auth). `project` overrides the
    OPENPROJECT_PROJECT_ID default — pass a slug or numeric id to target
    a specific project; omit it to use the configured default."""
    host = os.getenv("OPENPROJECT_URL", "").rstrip("/")
    project = (project or os.getenv("OPENPROJECT_PROJECT_ID", "")).strip()
    key = os.getenv("OPENPROJECT_API_KEY", "").strip()
    missing = [name for name, val in (
        ("OPENPROJECT_URL", host),
        ("OPENPROJECT_PROJECT_ID", project),
        ("OPENPROJECT_API_KEY", key),
    ) if not val]
    if missing:
        raise OpenProjectConfigError(
            f"OpenProject env not set: missing {', '.join(missing)}"
        )
    return host, project, key, HTTPBasicAuth("apikey", key)


def default_project() -> str:
    """The configured fallback project (OPENPROJECT_PROJECT_ID).
    Raises OpenProjectConfigError if env is unset."""
    _, project, _, _ = _config()
    return project


# ─── Metadata caches (populated on first use) ─────────────────────────
#
# OpenProject types/statuses/categories/priorities are referenced by
# numeric id in the HAL `_links`. We resolve names → ids once per
# process and reuse. Types and categories are PER-PROJECT (keyed by the
# project slug/id the caller used); statuses and priorities are global.

_TYPE_CACHE: dict[str, dict[str, int]] = {}      # project → {name: id}
_CATEGORY_CACHE: dict[str, dict[str, int]] = {}  # project → {name: id}
_STATUS_CACHE: dict[str, int] = {}               # global
_PRIORITY_DEFAULT_ID: int | None = None          # global


def _list(host: str, auth: HTTPBasicAuth, path: str) -> list[dict]:
    r = requests.get(f"{host}{path}", auth=auth, headers=_HEADERS,
                     timeout=DEFAULT_TIMEOUT_S)
    if not r.ok:
        raise OpenProjectAPIError(f"GET {path} -> {r.status_code}: {r.text[:300]}")
    return r.json().get("_embedded", {}).get("elements", []) or []


def _ensure_global_caches() -> None:
    """Populate the global status + default-priority caches once."""
    global _PRIORITY_DEFAULT_ID
    if _STATUS_CACHE and _PRIORITY_DEFAULT_ID is not None:
        return
    host, _, _, auth = _config()

    if not _STATUS_CACHE:
        for s in _list(host, auth, "/api/v3/statuses"):
            name = (s.get("name") or "").strip()
            if name and s.get("id") is not None:
                _STATUS_CACHE[name.lower()] = int(s["id"])

    if _PRIORITY_DEFAULT_ID is None:
        priorities = _list(host, auth, "/api/v3/priorities")
        for p in priorities:
            if p.get("isDefault") and p.get("id") is not None:
                _PRIORITY_DEFAULT_ID = int(p["id"])
                break
        if _PRIORITY_DEFAULT_ID is None:
            for p in priorities:
                if (p.get("name") or "").strip().lower() == "normal" and p.get("id") is not None:
                    _PRIORITY_DEFAULT_ID = int(p["id"])
                    break
        if _PRIORITY_DEFAULT_ID is None and priorities:
            _PRIORITY_DEFAULT_ID = int(priorities[0]["id"])


def _ensure_project_caches(project: str) -> None:
    """Populate the per-project type + category caches once per project."""
    if project in _TYPE_CACHE and project in _CATEGORY_CACHE:
        return
    host, project, _, auth = _config(project)

    if project not in _TYPE_CACHE:
        d: dict[str, int] = {}
        for t in _list(host, auth, f"/api/v3/projects/{project}/types"):
            name = (t.get("name") or "").strip()
            if name and t.get("id") is not None:
                d[name.lower()] = int(t["id"])
        _TYPE_CACHE[project] = d

    if project not in _CATEGORY_CACHE:
        d = {}
        for c in _list(host, auth, f"/api/v3/projects/{project}/categories"):
            name = (c.get("name") or "").strip()
            if name and c.get("id") is not None:
                d[name.lower()] = int(c["id"])
        _CATEGORY_CACHE[project] = d


def _resolve_type(name: str | None, project: str) -> int:
    _ensure_project_caches(project)
    n = (name or "Task").strip().lower()
    cache = _TYPE_CACHE.get(project, {})
    if n not in cache:
        raise OpenProjectError(
            f"OpenProject type {name!r} not enabled in project {project!r}. "
            f"Available: {sorted(cache.keys())}"
        )
    return cache[n]


def _resolve_status(name: str) -> int:
    _ensure_global_caches()
    n = (name or "").strip().lower()
    if n not in _STATUS_CACHE:
        raise OpenProjectError(
            f"OpenProject status {name!r} not configured. "
            f"Available: {sorted(_STATUS_CACHE.keys())}"
        )
    return _STATUS_CACHE[n]


def _resolve_category(name: str | None, project: str) -> int | None:
    if not name:
        return None
    _ensure_project_caches(project)
    cache = _CATEGORY_CACHE.get(project, {})
    n = name.strip().lower()
    if n not in cache:
        # Don't raise — category mismatches (e.g. a feature label sent to
        # cardaccess-4k, which has no categories) are non-fatal; the WP is
        # still created, just uncategorised.
        logger.warning(
            "OpenProject category %r not configured in project %r. Available: %s",
            name, project, sorted(cache.keys()),
        )
        return None
    return cache[n]


def _wp_web_url(host: str, project: str, wp_id: int) -> str:
    return f"{host}/projects/{project}/work_packages/{wp_id}"


# ─── Public API ───────────────────────────────────────────────────────

def list_open_work_packages(per_page: int = 100, *,
                            project: str | None = None) -> list[dict]:
    """Return open work packages for `project` as [{title, id, web_url}].

    "Open" means status not flagged isClosed — we use the server-side
    `status` filter operator `o` ("open")."""
    host, project, _, auth = _config(project)
    filters = json.dumps([{"status": {"operator": "o", "values": []}}])
    r = requests.get(
        f"{host}/api/v3/projects/{project}/work_packages",
        auth=auth, headers=_HEADERS,
        params={"filters": filters, "pageSize": per_page},
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not r.ok:
        raise OpenProjectAPIError(
            f"GET work_packages -> {r.status_code}: {r.text[:300]}"
        )
    out: list[dict] = []
    for wp in r.json().get("_embedded", {}).get("elements", []):
        wp_id = wp.get("id")
        if wp_id is None:
            continue
        out.append({
            "title":   wp.get("subject") or "",
            "id":      wp_id,
            "web_url": _wp_web_url(host, project, int(wp_id)),
        })
    return out


def create_work_package(
    *,
    title: str,
    description: str,
    type: str = "Task",
    status: str = "New",
    category: str | None = None,
    project: str | None = None,
) -> dict:
    """POST a new work package into `project`. Returns {id, web_url, subject}."""
    host, project, _, auth = _config(project)
    _ensure_global_caches()

    body: dict[str, Any] = {
        "subject": title,
        "description": {"format": "markdown", "raw": description},
        "_links": {
            "type":   {"href": f"/api/v3/types/{_resolve_type(type, project)}"},
            "status": {"href": f"/api/v3/statuses/{_resolve_status(status)}"},
        },
    }
    if _PRIORITY_DEFAULT_ID is not None:
        body["_links"]["priority"] = {
            "href": f"/api/v3/priorities/{_PRIORITY_DEFAULT_ID}"
        }
    cat_id = _resolve_category(category, project)
    if cat_id is not None:
        body["_links"]["category"] = {"href": f"/api/v3/categories/{cat_id}"}

    r = requests.post(
        f"{host}/api/v3/projects/{project}/work_packages",
        auth=auth, headers=_HEADERS, json=body, timeout=DEFAULT_TIMEOUT_S,
    )
    if r.status_code not in (200, 201):
        raise OpenProjectAPIError(
            f"POST work_package -> {r.status_code}: {r.text[:400]}"
        )
    data = r.json()
    wp_id = int(data["id"])
    return {
        "id":      wp_id,
        "subject": data.get("subject"),
        "web_url": _wp_web_url(host, project, wp_id),
    }


def _get_lock_version(wp_id: int) -> int:
    host, _, _, auth = _config()
    r = requests.get(
        f"{host}/api/v3/work_packages/{wp_id}",
        auth=auth, headers=_HEADERS, timeout=DEFAULT_TIMEOUT_S,
    )
    if not r.ok:
        raise OpenProjectAPIError(
            f"GET work_package/{wp_id} -> {r.status_code}: {r.text[:300]}"
        )
    lv = r.json().get("lockVersion")
    if lv is None:
        raise OpenProjectAPIError(
            f"work_package/{wp_id} response has no lockVersion"
        )
    return int(lv)


def update_work_package(
    wp_id: int,
    *,
    title: str | None = None,
    status: str | None = None,
    category: str | None = None,
    project: str | None = None,
) -> dict:
    """PATCH an existing work package. Pulls lockVersion first
    (OpenProject's optimistic-concurrency requirement). `project` is only
    needed to resolve a category name → id; the PATCH endpoint itself is
    project-agnostic."""
    host, project, _, auth = _config(project)
    lock_version = _get_lock_version(wp_id)

    body: dict[str, Any] = {"lockVersion": lock_version, "_links": {}}
    if title is not None:
        body["subject"] = title
    if status is not None:
        body["_links"]["status"] = {
            "href": f"/api/v3/statuses/{_resolve_status(status)}"
        }
    if category is not None:
        cat_id = _resolve_category(category, project)
        if cat_id is not None:
            body["_links"]["category"] = {
                "href": f"/api/v3/categories/{cat_id}"
            }
    if not body["_links"]:
        del body["_links"]

    r = requests.patch(
        f"{host}/api/v3/work_packages/{wp_id}",
        auth=auth, headers=_HEADERS, json=body, timeout=DEFAULT_TIMEOUT_S,
    )
    if not r.ok:
        raise OpenProjectAPIError(
            f"PATCH work_package/{wp_id} -> {r.status_code}: {r.text[:400]}"
        )
    return r.json()


def add_work_package_comment(wp_id: int, body: str) -> dict:
    """Post a comment (journal entry) on a work package. The standard
    OpenProject endpoint for this is /api/v3/work_packages/:id/activities
    with {comment: {format, raw}}."""
    host, _, _, auth = _config()
    r = requests.post(
        f"{host}/api/v3/work_packages/{wp_id}/activities",
        auth=auth, headers=_HEADERS,
        json={"comment": {"format": "markdown", "raw": body}},
        timeout=DEFAULT_TIMEOUT_S,
    )
    if r.status_code not in (200, 201):
        raise OpenProjectAPIError(
            f"POST comment on /{wp_id} -> {r.status_code}: {r.text[:400]}"
        )
    return r.json()
