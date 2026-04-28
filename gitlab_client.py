"""
GitLab v4 REST client for the Requirement Management dimension.

Opens issues in a gitlab.com project using a Personal Access Token
scoped to `api`. Stateless — every call reads env each time so a
rotated token picks up on the next invocation without a restart.

Env vars:
    GITLAB_HOST          default https://gitlab.com
    GITLAB_PROJECT_ID    numeric ID or URL-encoded path (e.g. 17543210
                         or 'titucse%2Fmvp-access-backlog')
    GITLAB_TOKEN         PAT with `api` scope
    GITLAB_DEFAULT_LABELS  optional, comma-separated; merged with any
                           labels passed to create_issue()

This module is intentionally thin — no gitlab SDK dependency, just
`requests`. Keeps requirements.txt small and failure modes obvious.
"""
from __future__ import annotations

import logging
import os
from typing import Iterable
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

DEFAULT_HOST = "https://gitlab.com"
DEFAULT_TIMEOUT_S = 20


class GitLabConfigError(RuntimeError):
    """Raised when required env vars are missing."""


class GitLabAPIError(RuntimeError):
    """Raised when the GitLab API returns a non-2xx response."""


def _config() -> tuple[str, str, str, list[str]]:
    host = (os.getenv("GITLAB_HOST") or DEFAULT_HOST).rstrip("/")
    project = (os.getenv("GITLAB_PROJECT_ID") or "").strip()
    token = (os.getenv("GITLAB_TOKEN") or "").strip()
    if not project:
        raise GitLabConfigError("GITLAB_PROJECT_ID not set")
    if not token:
        raise GitLabConfigError("GITLAB_TOKEN not set")
    default_labels = [
        s.strip() for s in (os.getenv("GITLAB_DEFAULT_LABELS") or "").split(",")
        if s.strip()
    ]
    # GitLab accepts both a numeric ID and a URL-encoded "namespace/project"
    # path — we pass whatever the env gave us. If it contains a slash and
    # hasn't been URL-encoded, encode it.
    if "/" in project and "%2F" not in project:
        project = quote(project, safe="")
    return host, project, token, default_labels


def _merge_labels(extra: Iterable[str] | None, defaults: list[str]) -> str | None:
    pool = list(defaults)
    if extra:
        for lbl in extra:
            if lbl and lbl not in pool:
                pool.append(lbl)
    return ",".join(pool) if pool else None


def create_issue(
    title: str,
    description: str,
    labels: Iterable[str] | None = None,
    due_date: str | None = None,
    assignee_ids: Iterable[int] | None = None,
    issue_type: str | None = None,
) -> dict:
    """Create a single work item. Returns the decoded JSON body on
    success. Raises GitLabConfigError or GitLabAPIError. Idempotency is
    the CALLER's responsibility — GitLab happily creates duplicate-
    titled issues.

    issue_type controls which work-item subtype gets created:
        - "issue"     (default) — a regular Issue work item
        - "task"      — a Task work item (visible under /-/work_items)
        - "incident"  — an Incident
        - "test_case" — a Test Case
    """
    host, project, token, default_labels = _config()
    url = f"{host}/api/v4/projects/{project}/issues"
    payload: dict = {"title": title, "description": description}
    merged = _merge_labels(labels, default_labels)
    if merged:
        payload["labels"] = merged
    if due_date:
        payload["due_date"] = due_date
    if assignee_ids:
        payload["assignee_ids"] = list(assignee_ids)
    if issue_type:
        payload["issue_type"] = issue_type

    r = requests.post(
        url,
        headers={"PRIVATE-TOKEN": token},
        json=payload,
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not r.ok:
        raise GitLabAPIError(
            f"POST {url} -> {r.status_code}: {r.text[:400]}"
        )
    return r.json()


def list_open_issues(search: str | None = None, per_page: int = 100) -> list[dict]:
    """Return open issues with the fields the publish path needs for
    dedupe + memory backfill: title, iid, web_url. The caller can derive
    a title-only set if it wants; carrying iid + web_url lets the
    dedup-skip branch upsert memory.requirements_seen so a reset DB
    self-heals on the next run."""
    host, project, token, _ = _config()
    url = f"{host}/api/v4/projects/{project}/issues"
    params: dict = {"state": "opened", "per_page": per_page}
    if search:
        params["search"] = search
    issues: list[dict] = []
    # One page is enough for Phase 1; if the backlog grows past 100 we'll
    # paginate via the Link header.
    r = requests.get(
        url,
        headers={"PRIVATE-TOKEN": token},
        params=params,
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not r.ok:
        raise GitLabAPIError(
            f"GET {url} -> {r.status_code}: {r.text[:400]}"
        )
    for issue in r.json():
        title = issue.get("title")
        if not title:
            continue
        issues.append({
            "title":   title,
            "iid":     issue.get("iid"),
            "web_url": issue.get("web_url"),
        })
    return issues


def list_open_issue_titles(search: str | None = None, per_page: int = 100) -> list[str]:
    """Backwards-compat shim. Prefer `list_open_issues` for new code."""
    return [i["title"] for i in list_open_issues(search=search, per_page=per_page)]


def update_issue(
    iid: int,
    title: str | None = None,
    description: str | None = None,
    add_labels: Iterable[str] | None = None,
    remove_labels: Iterable[str] | None = None,
) -> dict:
    """PUT /projects/:id/issues/:iid. Updates a single field set on an
    existing work item. GitLab automatically writes a system note for
    every change (title diff, label add, label remove), so the timeline
    becomes our change-log without any extra work on our side.

    Pass title to replace the current title. Pass add_labels /
    remove_labels (iterables of label names) to mutate labels without
    overwriting unrelated ones. Returns the decoded JSON body of the
    updated issue."""
    host, project, token, _ = _config()
    url = f"{host}/api/v4/projects/{project}/issues/{iid}"
    payload: dict = {}
    if title is not None:
        payload["title"] = title
    if description is not None:
        payload["description"] = description
    if add_labels:
        payload["add_labels"] = ",".join(add_labels)
    if remove_labels:
        payload["remove_labels"] = ",".join(remove_labels)
    if not payload:
        return {"iid": iid, "noop": True}
    r = requests.put(
        url,
        headers={"PRIVATE-TOKEN": token},
        json=payload,
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not r.ok:
        raise GitLabAPIError(
            f"PUT {url} -> {r.status_code}: {r.text[:400]}"
        )
    return r.json()


def add_issue_note(iid: int, body: str) -> dict:
    """POST /projects/:id/issues/:iid/notes. Posts a comment on the
    issue. The note is timestamped server-side and shown in the issue's
    discussion timeline alongside the system notes that update_issue
    produces. Used to log the source content of a revision next to the
    label/title swap."""
    host, project, token, _ = _config()
    url = f"{host}/api/v4/projects/{project}/issues/{iid}/notes"
    r = requests.post(
        url,
        headers={"PRIVATE-TOKEN": token},
        json={"body": body},
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not r.ok:
        raise GitLabAPIError(
            f"POST {url} -> {r.status_code}: {r.text[:400]}"
        )
    return r.json()


def project_identity() -> dict:
    """Smoke-test helper: returns {host, project, name, web_url} so the
    caller can verify creds + project ID resolve before any writes."""
    host, project, token, _ = _config()
    url = f"{host}/api/v4/projects/{project}"
    r = requests.get(
        url,
        headers={"PRIVATE-TOKEN": token},
        timeout=DEFAULT_TIMEOUT_S,
    )
    if not r.ok:
        raise GitLabAPIError(
            f"GET {url} -> {r.status_code}: {r.text[:400]}"
        )
    data = r.json()
    return {
        "host": host,
        "project_id": data.get("id"),
        "path_with_namespace": data.get("path_with_namespace"),
        "web_url": data.get("web_url"),
    }
