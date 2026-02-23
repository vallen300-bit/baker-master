"""
Sentinel AI — Todoist API Client
Read-only access to Todoist REST API v2 + Sync API v9.
Polls projects, tasks (active + completed), sections, labels, comments.
"""
import logging
import os
import time
from typing import Optional

import httpx

from config.settings import config

logger = logging.getLogger("sentinel.todoist")

# Rate limit: 450 requests/15 min
_RATE_LIMIT_WARN = 400


class TodoistClient:
    """Todoist API wrapper — read-only polling client."""

    _instance = None

    @classmethod
    def _get_global_instance(cls):
        """Return the module-level singleton. Lazy-init if needed."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._api_token = config.todoist.api_token
        if not self._api_token:
            logger.warning("TODOIST_API_TOKEN not set — Todoist client will not work")

        self._base_url = config.todoist.base_url
        self._sync_url = config.todoist.sync_url

        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {self._api_token}"},
            timeout=30.0,
        )

        # Rate limiting state
        self._request_count = 0
        self._rate_window_start = time.time()

    # -------------------------------------------------------
    # Rate limiting
    # -------------------------------------------------------

    def _check_rate_limit(self):
        """Track requests and warn when approaching Todoist rate limit."""
        now = time.time()
        # Reset counter every 15 minutes
        if now - self._rate_window_start > 900:
            self._request_count = 0
            self._rate_window_start = now

        self._request_count += 1

        if self._request_count >= _RATE_LIMIT_WARN:
            logger.warning(
                f"Todoist rate limit warning: {self._request_count} requests in 15 min window"
            )
            # Brief pause to stay safe
            time.sleep(2)

    # -------------------------------------------------------
    # REST API v2 methods
    # -------------------------------------------------------

    def _get(self, path: str, params: dict = None) -> list | dict:
        """GET request to Todoist REST API v2."""
        self._check_rate_limit()
        url = f"{self._base_url}{path}"
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def get_projects(self) -> list[dict]:
        """GET /rest/v2/projects — returns all projects."""
        return self._get("/projects")

    def get_tasks(self, project_id: str = None) -> list[dict]:
        """GET /rest/v2/tasks — returns all active tasks. Optional project_id filter."""
        params = {}
        if project_id:
            params["project_id"] = project_id
        return self._get("/tasks", params=params if params else None)

    def get_sections(self) -> list[dict]:
        """GET /rest/v2/sections — returns all sections."""
        return self._get("/sections")

    def get_labels(self) -> list[dict]:
        """GET /rest/v2/labels — returns all labels."""
        return self._get("/labels")

    def get_comments(self, task_id: str) -> list[dict]:
        """GET /rest/v2/comments?task_id={task_id} — returns comments for a task."""
        return self._get("/comments", params={"task_id": task_id})

    # -------------------------------------------------------
    # Sync API v9 (completed tasks)
    # -------------------------------------------------------

    def get_completed_tasks(self, since: str = None, limit: int = 200, offset: int = 0) -> list[dict]:
        """POST /sync/v9/completed/get_all — returns completed tasks.

        Args:
            since: ISO 8601 datetime string (e.g. '2026-02-22T00:00:00Z')
            limit: Max tasks per page (default 200)
            offset: Pagination offset

        Returns:
            List of completed task dicts from the 'items' key.
        """
        self._check_rate_limit()
        url = f"{self._sync_url}/completed/get_all"

        data = {"limit": limit, "offset": offset}
        if since:
            data["since"] = since

        resp = self._client.post(url, data=data)
        resp.raise_for_status()
        result = resp.json()
        # Sync API returns {"items": [...], "projects": {...}}
        return result.get("items", [])
