"""
Sentinel AI — Todoist API Client
Read-only access to Todoist API v1 (unified endpoint).
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
    # API v1 methods
    # -------------------------------------------------------

    def _get(self, path: str, params: dict = None) -> list | dict:
        """GET request to Todoist API v1."""
        self._check_rate_limit()
        url = f"{self._base_url}{path}"
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _get_list(self, path: str, params: dict = None) -> list[dict]:
        """GET request that unwraps API v1 paginated envelope.

        API v1 returns {"results": [...], "next_cursor": "..."} for list endpoints.
        This method unwraps to return a flat list, auto-paginating if next_cursor is present.
        Falls back gracefully if the response is already a plain list (future-proofing).
        """
        all_results = []
        current_params = dict(params) if params else {}

        while True:
            data = self._get(path, current_params if current_params else None)

            # Handle envelope: {"results": [...], "next_cursor": "..."}
            if isinstance(data, dict):
                results = data.get("results", data.get("items", []))
                all_results.extend(results)

                next_cursor = data.get("next_cursor")
                if next_cursor:
                    current_params["cursor"] = next_cursor
                    continue
                break
            elif isinstance(data, list):
                # Already a flat list (backward compat)
                all_results.extend(data)
                break
            else:
                logger.warning(f"Unexpected response type from {path}: {type(data)}")
                break

        return all_results

    def get_projects(self) -> list[dict]:
        """GET /api/v1/projects — returns all projects."""
        return self._get_list("/projects")

    def get_tasks(self, project_id: str = None) -> list[dict]:
        """GET /api/v1/tasks — returns all active tasks. Optional project_id filter."""
        params = {}
        if project_id:
            params["project_id"] = project_id
        return self._get_list("/tasks", params=params if params else None)

    def get_sections(self, project_id: str = None) -> list[dict]:
        """GET /api/v1/sections — returns all sections. Optional project_id filter."""
        params = {}
        if project_id:
            params["project_id"] = project_id
        return self._get_list("/sections", params=params if params else None)

    def get_labels(self) -> list[dict]:
        """GET /api/v1/labels — returns all labels."""
        return self._get_list("/labels")

    def get_comments(self, task_id: str) -> list[dict]:
        """GET /api/v1/comments?task_id={task_id} — returns comments for a task."""
        return self._get_list("/comments", params={"task_id": task_id})

    # -------------------------------------------------------
    # Completed tasks (API v1)
    # -------------------------------------------------------

    def get_completed_tasks(self, since: str = None, limit: int = 200, offset: int = 0) -> list[dict]:
        """GET /api/v1/tasks/completed — returns completed tasks.

        Args:
            since: ISO 8601 datetime string (e.g. '2026-02-22T00:00:00Z')
            limit: Max tasks per page (default 200)
            offset: Pagination offset

        Returns:
            List of completed task dicts.
        """
        params = {"limit": limit, "offset": offset}
        if since:
            params["since"] = since

        result = self._get("/tasks/completed", params=params)

        # v1 returns {"results": [...]} or {"items": [...]} or a list
        if isinstance(result, list):
            return result
        return result.get("results", result.get("items", []))
