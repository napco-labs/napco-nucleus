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
) -> dict:
    """Create a single issue. Returns the decoded JSON body on success.
    Raises GitLabConfigError or GitLabAPIError. Idempotency is the
    CALLER's responsibility — GitLab happily creates duplicate-titled
    issues."""
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


def list_open_issue_titles(search: str | None = None, per_page: int = 100) -> list[str]:
    """Return titles of open issues in the target project — used for
    pre-publish dedupe so we don't re-create the same task every run."""
    host, project, token, _ = _config()
    url = f"{host}/api/v4/projects/{project}/issues"
    params: dict = {"state": "opened", "per_page": per_page}
    if search:
        params["search"] = search
    titles: list[str] = []
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
        t = issue.get("title")
        if t:
            titles.append(t)
    return titles


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
