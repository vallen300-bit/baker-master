"""
Sentinel AI — ClickUp API Client
Read all 6 workspaces, write BAKER space only.
All writes audited to baker_actions table.
"""
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("sentinel.clickup")

# BAKER space — the only space Baker is allowed to write to
_BAKER_SPACE_ID = "901510186446"

# Rate limit: ClickUp allows 100 requests/minute per token
_RATE_LIMIT_MAX = 100
_RATE_LIMIT_WARN = 90  # sleep when approaching limit
_MAX_WRITES_PER_CYCLE = 10


class ClickUpClient:
    """ClickUp API wrapper with read-all / write-BAKER-only safety."""

    _instance = None

    @classmethod
    def _get_global_instance(cls):
        """Return the module-level singleton. Lazy-init if needed."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._api_key = os.getenv("CLICKUP_API_KEY", "")
        if not self._api_key:
            logger.warning("CLICKUP_API_KEY not set — ClickUp client will not work")

        self._base_url = "https://api.clickup.com/api/v2"
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={"Authorization": self._api_key},
            timeout=30.0,
        )

        # Rate limiting state
        self._request_count = 0
        self._rate_window_start = time.time()

        # Write cycle counter (reset each poll cycle)
        self._cycle_write_count = 0

    # -------------------------------------------------------
    # Rate limiting
    # -------------------------------------------------------

    def _check_rate_limit(self):
        """Sleep if approaching ClickUp's 100 req/min limit."""
        now = time.time()
        elapsed = now - self._rate_window_start

        # Reset counter every 60 seconds
        if elapsed >= 60:
            self._request_count = 0
            self._rate_window_start = now
            return

        if self._request_count >= _RATE_LIMIT_WARN:
            sleep_time = 60 - elapsed
            if sleep_time > 0:
                logger.info(f"Rate limit approaching ({self._request_count} reqs) — sleeping {sleep_time:.1f}s")
                time.sleep(sleep_time)
            self._request_count = 0
            self._rate_window_start = time.time()

    def _request(self, method: str, path: str, **kwargs) -> Optional[dict]:
        """
        Make an API request with rate limiting and error handling.
        Returns parsed JSON or None on failure.
        """
        self._check_rate_limit()
        self._request_count += 1

        backoff = 1
        max_backoff = 30
        max_retries = 4

        for attempt in range(max_retries):
            try:
                resp = self._client.request(method, path, **kwargs)

                if resp.status_code == 429:
                    logger.warning(f"ClickUp 429 rate limited — backoff {backoff}s (attempt {attempt + 1})")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)
                    continue

                if resp.status_code >= 400:
                    logger.error(f"ClickUp API {method} {path} → {resp.status_code}: {resp.text[:200]}")
                    return None

                return resp.json()

            except httpx.TimeoutException:
                logger.error(f"ClickUp API timeout: {method} {path} (attempt {attempt + 1})")
                time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            except Exception as e:
                logger.error(f"ClickUp API error: {method} {path} — {e}")
                return None

        logger.error(f"ClickUp API exhausted retries: {method} {path}")
        return None

    # -------------------------------------------------------
    # Write safety
    # -------------------------------------------------------

    def _check_write_allowed(self, space_id: str, action_type: str):
        """
        Enforce write safety rules. Raises on violation.
        1. Kill switch env var
        2. BAKER space only
        3. Max writes per cycle
        """
        # Kill switch
        if os.getenv("BAKER_CLICKUP_READONLY", "").lower() == "true":
            raise RuntimeError("ClickUp writes disabled by kill switch")

        # BAKER space only
        if str(space_id) != _BAKER_SPACE_ID:
            raise ValueError("Write attempted outside BAKER space")

        # Max writes per cycle
        if self._cycle_write_count >= _MAX_WRITES_PER_CYCLE:
            logger.warning(f"Max writes per cycle ({_MAX_WRITES_PER_CYCLE}) exceeded — skipping {action_type}")
            raise RuntimeError(f"Max writes per cycle exceeded ({_MAX_WRITES_PER_CYCLE})")

    def _log_action(self, action_type: str, target_task_id: str,
                    target_space_id: str, payload: dict,
                    trigger_source: str, success: bool = True,
                    error_message: str = None):
        """Log write action to baker_actions table."""
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            store.log_baker_action(
                action_type=action_type,
                target_task_id=target_task_id,
                target_space_id=target_space_id,
                payload=payload,
                trigger_source=trigger_source,
                success=success,
                error_message=error_message,
            )
        except Exception as e:
            logger.error(f"Failed to log baker action: {e}")

    def reset_cycle_counter(self):
        """Reset the per-cycle write counter. Call at the start of each poll cycle."""
        self._cycle_write_count = 0

    # -------------------------------------------------------
    # Read methods (all 6 workspaces)
    # -------------------------------------------------------

    def get_spaces(self, workspace_id: str) -> list:
        """GET /team/{workspace_id}/space — returns list of spaces."""
        data = self._request("GET", f"/team/{workspace_id}/space")
        if data and "spaces" in data:
            return data["spaces"]
        return []

    def get_lists(self, space_id: str) -> list:
        """
        Get all lists in a space — both folderless lists and lists inside folders.
        GET /space/{space_id}/list + GET /space/{space_id}/folder then lists within.
        """
        all_lists = []

        # Folderless lists
        data = self._request("GET", f"/space/{space_id}/list")
        if data and "lists" in data:
            all_lists.extend(data["lists"])

        # Folders, then lists inside each folder
        folders_data = self._request("GET", f"/space/{space_id}/folder")
        if folders_data and "folders" in folders_data:
            for folder in folders_data["folders"]:
                folder_id = folder.get("id")
                if folder_id:
                    folder_lists = self._request("GET", f"/folder/{folder_id}/list")
                    if folder_lists and "lists" in folder_lists:
                        all_lists.extend(folder_lists["lists"])

        return all_lists

    def get_tasks(self, list_id: str, date_updated_gt: int = None) -> list:
        """
        GET /list/{list_id}/task — returns tasks with optional watermark filter.
        date_updated_gt: Unix timestamp in milliseconds.
        """
        params = {"include_closed": "true"}
        if date_updated_gt is not None:
            params["date_updated_gt"] = str(date_updated_gt)

        data = self._request("GET", f"/list/{list_id}/task", params=params)
        if data and "tasks" in data:
            return data["tasks"]
        return []

    def get_task_comments(self, task_id: str) -> list:
        """GET /task/{task_id}/comment — returns list of comments."""
        data = self._request("GET", f"/task/{task_id}/comment")
        if data and "comments" in data:
            return data["comments"]
        return []

    def get_task_detail(self, task_id: str) -> Optional[dict]:
        """GET /task/{task_id} — returns full task detail."""
        return self._request("GET", f"/task/{task_id}")

    # -------------------------------------------------------
    # Write methods (BAKER space ONLY — 901510186446)
    # -------------------------------------------------------

    def _resolve_space_id_for_task(self, task_id: str) -> Optional[str]:
        """Look up the space_id for a task by fetching its detail."""
        detail = self.get_task_detail(task_id)
        if detail and "space" in detail:
            return detail["space"].get("id")
        return None

    def _resolve_space_id_for_list(self, list_id: str) -> Optional[str]:
        """Look up the space_id for a list by fetching list detail."""
        data = self._request("GET", f"/list/{list_id}")
        if data and "space" in data:
            return data["space"].get("id")
        return None

    def create_task(self, list_id: str, name: str, description: str = None,
                    priority: int = None, assignees: list = None,
                    tags: list = None, due_date: int = None,
                    status: str = None) -> Optional[dict]:
        """POST /list/{list_id}/task — BAKER space only."""
        space_id = self._resolve_space_id_for_list(list_id)
        self._check_write_allowed(space_id, "create_task")

        payload = {"name": name}
        if description:
            payload["description"] = description
        if priority is not None:
            payload["priority"] = priority
        if assignees:
            payload["assignees"] = assignees
        if tags:
            payload["tags"] = tags
        if due_date is not None:
            payload["due_date"] = due_date
        if status:
            payload["status"] = status

        result = self._request("POST", f"/list/{list_id}/task", json=payload)

        success = result is not None
        self._cycle_write_count += 1
        self._log_action(
            action_type="create_task",
            target_task_id=result.get("id") if result else None,
            target_space_id=space_id,
            payload=payload,
            trigger_source="clickup_client",
            success=success,
        )
        return result

    def update_task(self, task_id: str, **kwargs) -> Optional[dict]:
        """PUT /task/{task_id} — BAKER space only."""
        space_id = self._resolve_space_id_for_task(task_id)
        self._check_write_allowed(space_id, "update_task")

        result = self._request("PUT", f"/task/{task_id}", json=kwargs)

        success = result is not None
        self._cycle_write_count += 1
        self._log_action(
            action_type="update_task",
            target_task_id=task_id,
            target_space_id=space_id,
            payload=kwargs,
            trigger_source="clickup_client",
            success=success,
        )
        return result

    def post_comment(self, task_id: str, comment_text: str) -> Optional[dict]:
        """POST /task/{task_id}/comment — BAKER space only."""
        space_id = self._resolve_space_id_for_task(task_id)
        self._check_write_allowed(space_id, "post_comment")

        payload = {"comment_text": comment_text}
        result = self._request("POST", f"/task/{task_id}/comment", json=payload)

        success = result is not None
        self._cycle_write_count += 1
        self._log_action(
            action_type="post_comment",
            target_task_id=task_id,
            target_space_id=space_id,
            payload=payload,
            trigger_source="clickup_client",
            success=success,
        )
        return result

    def add_tag(self, task_id: str, tag_name: str) -> Optional[dict]:
        """POST /task/{task_id}/tag/{tag_name} — BAKER space only."""
        space_id = self._resolve_space_id_for_task(task_id)
        self._check_write_allowed(space_id, "add_tag")

        result = self._request("POST", f"/task/{task_id}/tag/{tag_name}")

        success = result is not None
        self._cycle_write_count += 1
        self._log_action(
            action_type="add_tag",
            target_task_id=task_id,
            target_space_id=space_id,
            payload={"tag_name": tag_name},
            trigger_source="clickup_client",
            success=success,
        )
        return result

    def remove_tag(self, task_id: str, tag_name: str) -> Optional[dict]:
        """DELETE /task/{task_id}/tag/{tag_name} — BAKER space only."""
        space_id = self._resolve_space_id_for_task(task_id)
        self._check_write_allowed(space_id, "remove_tag")

        result = self._request("DELETE", f"/task/{task_id}/tag/{tag_name}")

        success = result is not None
        self._cycle_write_count += 1
        self._log_action(
            action_type="remove_tag",
            target_task_id=task_id,
            target_space_id=space_id,
            payload={"tag_name": tag_name},
            trigger_source="clickup_client",
            success=success,
        )
        return result

    # -------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------

    def close(self):
        """Close the HTTP client."""
        self._client.close()
        logger.info("ClickUp client closed")
