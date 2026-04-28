"""
NAPCO Nucleus — OpenProject API client.

Replaces gitlab_client.py (deleted 2026-04-28) so requirement-management
publishes to OpenProject Work Packages instead of GitLab Issues.

Public surface (intentionally narrow — same shape as the old GitLab
client so tools/requirements.py needs minimal changes):
    list_open_work_packages()                 → [{title, id, web_url}]
    create_work_package(title, description, *, category=None,
                         type='Task', status='New')          → dict
    update_work_package(id, *, title=None, status=None,
                         category=None)                       → dict
    add_work_package_comment(id, body)                        → dict

Conventions:
    * HAL+JSON. References between resources are URIs in `_links` dicts.
    * Auth: HTTP Basic with username='apikey', password=<API key>.
    * Required env: OPENPROJECT_URL, OPENPROJECT_PROJECT_ID,
                    OPENPROJECT_API_KEY.
    * `OPENPROJECT_PROJECT_ID` accepts either the numeric id or the
      project slug (`mvp-access` works); OpenProject's REST API resolves
      both transparently.
    * lookup caches for type/status/category/priority are populated on
      first use and reused for the rest of the process.

Errors:
    OpenProjectConfigError — env vars missing or invalid.
    OpenProjectAPIError    — non-2xx response from the OpenProject API.

NOT a tool — this module is a low-level HTTP wrapper. Tools live under
tools/ and orchestrate this client.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Iterable

import requests
from requests.auth import HTTPBasicAuth


logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30


class OpenProjectError(RuntimeError):
    pass


class OpenProjectConfigError(OpenProjectError):
    pass


class OpenProjectAPIError(OpenProjectError):
    pass


# ─── Config ───────────────────────────────────────────────────────────

def _config() -> tuple[str, str, str, HTTPBasicAuth]:
    host = os.getenv("OPENPROJECT_URL", "").rstrip("/")
    project = os.getenv("OPENPROJECT_PROJECT_ID", "").strip()
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


# ─── Metadata caches (populated on first use) ─────────────────────────
#
# OpenProject types/statuses/categories/priorities are referenced by
# numeric id in the HAL `_links`. We resolve names → ids once per
# process and reuse. Cache stays warm for the duration of the agent run.

_TYPE_CACHE: dict[str, int] = {}
_STATUS_CACHE: dict[str, int] = {}
_CATEGORY_CACHE: dict[str, int] = {}
_PRIORITY_DEFAULT_ID: int | None = None


def _ensure_meta_caches() -> None:
    global _PRIORITY_DEFAULT_ID
    if _TYPE_CACHE and _STATUS_CACHE and _CATEGORY_CACHE and _PRIORITY_DEFAULT_ID is not None:
        return

    host, project, _, auth = _config()

    def _list(path: str) -> list[dict]:
        r = requests.get(f"{host}{path}", auth=auth, timeout=DEFAULT_TIMEOUT_S)
        if not r.ok:
            raise OpenProjectAPIError(
                f"GET {path} -> {r.status_code}: {r.text[:300]}"
            )
        return r.json().get("_embedded", {}).get("elements", []) or []

    # Types are per-project (only those enabled for the project show up).
    if not _TYPE_CACHE:
        for t in _list(f"/api/v3/projects/{project}/types"):
            name = (t.get("name") or "").strip()
            if name and t.get("id") is not None:
                _TYPE_CACHE[name.lower()] = int(t["id"])

    # Statuses are global.
    if not _STATUS_CACHE:
        for s in _list("/api/v3/statuses"):
            name = (s.get("name") or "").strip()
            if name and s.get("id") is not None:
                _STATUS_CACHE[name.lower()] = int(s["id"])

    # Categories are per-project.
    if not _CATEGORY_CACHE:
        for c in _list(f"/api/v3/projects/{project}/categories"):
            name = (c.get("name") or "").strip()
            if name and c.get("id") is not None:
                _CATEGORY_CACHE[name.lower()] = int(c["id"])

    # Priorities are global. Pick the one flagged isDefault, fall back
    # to "Normal", fall back to the first listed.
    if _PRIORITY_DEFAULT_ID is None:
        priorities = _list("/api/v3/priorities")
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


def _resolve_type(name: str | None) -> int:
    _ensure_meta_caches()
    n = (name or "Task").strip().lower()
    if n not in _TYPE_CACHE:
        raise OpenProjectError(
            f"OpenProject type {name!r} not enabled in project. "
            f"Available: {sorted(_TYPE_CACHE.keys())}"
        )
    return _TYPE_CACHE[n]


def _resolve_status(name: str) -> int:
    _ensure_meta_caches()
    n = (name or "").strip().lower()
    if n not in _STATUS_CACHE:
        raise OpenProjectError(
            f"OpenProject status {name!r} not configured. "
            f"Available: {sorted(_STATUS_CACHE.keys())}"
        )
    return _STATUS_CACHE[n]


def _resolve_category(name: str | None) -> int | None:
    if not name:
        return None
    _ensure_meta_caches()
    n = name.strip().lower()
    if n not in _CATEGORY_CACHE:
        # Don't raise — category mismatches surface in the publish tool's
        # `failed` list and are not fatal for the rest of the batch.
        logger.warning(
            "OpenProject category %r not configured. Available: %s",
            name, sorted(_CATEGORY_CACHE.keys()),
        )
        return None
    return _CATEGORY_CACHE[n]


def _wp_web_url(host: str, project: str, wp_id: int) -> str:
    return f"{host}/projects/{project}/work_packages/{wp_id}"


# ─── Public API ───────────────────────────────────────────────────────

def list_open_work_packages(per_page: int = 100) -> list[dict]:
    """Return open work packages as [{title, id, web_url}].

    "Open" here means status not flagged isClosed. We rely on the
    `status` filter operator `o` ("open") which OpenProject implements
    server-side."""
    host, project, _, auth = _config()
    filters = json.dumps([{"status": {"operator": "o", "values": []}}])
    r = requests.get(
        f"{host}/api/v3/projects/{project}/work_packages",
        auth=auth,
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
) -> dict:
    """POST a new work package. Returns {id, web_url, subject}."""
    host, project, _, auth = _config()
    _ensure_meta_caches()

    body: dict[str, Any] = {
        "subject": title,
        "description": {"format": "markdown", "raw": description},
        "_links": {
            "type":   {"href": f"/api/v3/types/{_resolve_type(type)}"},
            "status": {"href": f"/api/v3/statuses/{_resolve_status(status)}"},
        },
    }
    if _PRIORITY_DEFAULT_ID is not None:
        body["_links"]["priority"] = {
            "href": f"/api/v3/priorities/{_PRIORITY_DEFAULT_ID}"
        }
    cat_id = _resolve_category(category)
    if cat_id is not None:
        body["_links"]["category"] = {"href": f"/api/v3/categories/{cat_id}"}

    r = requests.post(
        f"{host}/api/v3/projects/{project}/work_packages",
        auth=auth, json=body, timeout=DEFAULT_TIMEOUT_S,
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
        auth=auth, timeout=DEFAULT_TIMEOUT_S,
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
) -> dict:
    """PATCH an existing work package. Pulls lockVersion first
    (OpenProject's optimistic-concurrency requirement)."""
    host, _, _, auth = _config()
    lock_version = _get_lock_version(wp_id)

    body: dict[str, Any] = {"lockVersion": lock_version, "_links": {}}
    if title is not None:
        body["subject"] = title
    if status is not None:
        body["_links"]["status"] = {
            "href": f"/api/v3/statuses/{_resolve_status(status)}"
        }
    if category is not None:
        cat_id = _resolve_category(category)
        if cat_id is not None:
            body["_links"]["category"] = {
                "href": f"/api/v3/categories/{cat_id}"
            }
    if not body["_links"]:
        del body["_links"]

    r = requests.patch(
        f"{host}/api/v3/work_packages/{wp_id}",
        auth=auth, json=body, timeout=DEFAULT_TIMEOUT_S,
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
        auth=auth,
        json={"comment": {"format": "markdown", "raw": body}},
        timeout=DEFAULT_TIMEOUT_S,
    )
    if r.status_code not in (200, 201):
        raise OpenProjectAPIError(
            f"POST comment on /{wp_id} -> {r.status_code}: {r.text[:400]}"
        )
    return r.json()
