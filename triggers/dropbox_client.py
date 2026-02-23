"""
Sentinel AI — Dropbox API Client (Read-Only)
Polls /Baker-Feed/ for new and modified files via Dropbox API v2.
Uses OAuth2 refresh tokens (short-lived access tokens, mandatory since Sep 2021).
No Dropbox Python SDK — uses httpx with raw HTTP endpoints (same pattern as Todoist).

API: Dropbox API v2 — https://www.dropbox.com/developers/documentation/http/overview
Deprecation check date: 2026-03-23
"""
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx

from config.settings import config

logger = logging.getLogger("sentinel.dropbox")

# Rate limit: ~1000 requests / 10 min for individual users
_RATE_LIMIT_WINDOW = 600  # 10 minutes
_RATE_LIMIT_WARN = 800
_RATE_LIMIT_PAUSE = 950


class DropboxClient:
    """Dropbox API v2 wrapper — read-only polling client with OAuth2 token refresh."""

    _instance = None

    @classmethod
    def _get_global_instance(cls):
        """Return the module-level singleton. Lazy-init if needed."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._app_key = config.dropbox.app_key
        self._app_secret = config.dropbox.app_secret
        self._refresh_token = config.dropbox.refresh_token

        if not self._refresh_token:
            logger.warning("DROPBOX_REFRESH_TOKEN not set — Dropbox client will not work")

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        # Rate limiting state
        self._request_count = 0
        self._rate_window_start = time.time()

        # HTTP client (no auth header yet — set per-request after token refresh)
        self._client = httpx.Client(timeout=60.0)

        # Initial token fetch
        if self._refresh_token:
            try:
                self._refresh_access_token()
            except Exception as e:
                logger.error(f"Initial Dropbox token refresh failed: {e}")

    # -------------------------------------------------------
    # OAuth2 Token Refresh
    # -------------------------------------------------------

    def _refresh_access_token(self):
        """POST to Dropbox OAuth2 token endpoint with grant_type=refresh_token."""
        resp = httpx.post(
            "https://api.dropboxapi.com/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._app_key,
                "client_secret": self._app_secret,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        # Expire 5 min early as safety buffer
        self._token_expires_at = time.time() + data.get("expires_in", 14400) - 300
        logger.info("Dropbox access token refreshed successfully")

    def _ensure_token(self):
        """Refresh access token if expired or about to expire."""
        if not self._access_token or time.time() >= self._token_expires_at:
            self._refresh_access_token()

    def _auth_headers(self) -> dict:
        """Return Authorization header with current access token."""
        self._ensure_token()
        return {"Authorization": f"Bearer {self._access_token}"}

    # -------------------------------------------------------
    # Rate Limiting
    # -------------------------------------------------------

    def _check_rate_limit(self):
        """Track requests and warn/pause when approaching Dropbox rate limit."""
        now = time.time()
        if now - self._rate_window_start > _RATE_LIMIT_WINDOW:
            self._request_count = 0
            self._rate_window_start = now

        self._request_count += 1

        if self._request_count >= _RATE_LIMIT_PAUSE:
            logger.warning(
                f"Dropbox rate limit PAUSE: {self._request_count} requests in {_RATE_LIMIT_WINDOW}s window — sleeping 60s"
            )
            time.sleep(60)
        elif self._request_count >= _RATE_LIMIT_WARN:
            logger.warning(
                f"Dropbox rate limit warning: {self._request_count} requests in {_RATE_LIMIT_WINDOW}s window"
            )
            time.sleep(2)

    # -------------------------------------------------------
    # API Methods (Dropbox API v2 — raw HTTP)
    # -------------------------------------------------------

    def _api_post(self, url: str, json_body: dict) -> dict:
        """POST to Dropbox API with auth, rate limiting, and auto-retry on 401."""
        self._check_rate_limit()
        headers = {**self._auth_headers(), "Content-Type": "application/json"}

        resp = self._client.post(url, headers=headers, json=json_body)

        # Auto-refresh on 401 and retry once
        if resp.status_code == 401:
            logger.info("Dropbox 401 — refreshing token and retrying")
            self._refresh_access_token()
            headers = {**self._auth_headers(), "Content-Type": "application/json"}
            self._check_rate_limit()
            resp = self._client.post(url, headers=headers, json=json_body)

        # Handle 429 rate limit
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            logger.warning(f"Dropbox 429 — sleeping {retry_after}s")
            time.sleep(retry_after)
            self._check_rate_limit()
            resp = self._client.post(url, headers=headers, json=json_body)

        resp.raise_for_status()
        return resp.json()

    def list_folder(self, path: str, cursor: Optional[str] = None) -> tuple[list[dict], str]:
        """List folder contents or continue from cursor.

        First call (cursor=None): POST /2/files/list_folder
        Subsequent calls: POST /2/files/list_folder/continue

        Handles has_more pagination internally.
        409 (path not found) returns empty — folder may not exist yet.

        Returns:
            (entries, new_cursor) — entries is a flat list of all file/folder metadata dicts.
        """
        all_entries = []

        try:
            if cursor:
                data = self._api_post(
                    "https://api.dropboxapi.com/2/files/list_folder/continue",
                    {"cursor": cursor},
                )
            else:
                data = self._api_post(
                    "https://api.dropboxapi.com/2/files/list_folder",
                    {"path": path, "recursive": True, "include_deleted": False},
                )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                logger.warning(f"Dropbox list_folder 409 — folder '{path}' may not exist yet")
                return [], cursor or ""
            raise

        all_entries.extend(data.get("entries", []))
        new_cursor = data.get("cursor", "")

        # Paginate if has_more
        while data.get("has_more", False):
            data = self._api_post(
                "https://api.dropboxapi.com/2/files/list_folder/continue",
                {"cursor": new_cursor},
            )
            all_entries.extend(data.get("entries", []))
            new_cursor = data.get("cursor", "")

        logger.info(f"Dropbox list_folder: {len(all_entries)} entries returned")
        return all_entries, new_cursor

    def download_file(self, path: str, dest_dir: Path) -> Path:
        """Download a file from Dropbox to a local directory.

        POST https://content.dropboxapi.com/2/files/download
        Uses Dropbox-API-Arg header for path specification.

        Returns:
            Path to the downloaded file.
        """
        import json as json_mod

        self._check_rate_limit()
        self._ensure_token()

        filename = Path(path).name
        dest_path = dest_dir / filename

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Dropbox-API-Arg": json_mod.dumps({"path": path}),
        }

        # Stream download to avoid loading large files into memory
        with self._client.stream("POST", "https://content.dropboxapi.com/2/files/download", headers=headers) as resp:
            # Auto-refresh on 401
            if resp.status_code == 401:
                resp.close()
                self._refresh_access_token()
                headers["Authorization"] = f"Bearer {self._access_token}"
                self._check_rate_limit()
                with self._client.stream("POST", "https://content.dropboxapi.com/2/files/download", headers=headers) as resp2:
                    resp2.raise_for_status()
                    with open(dest_path, "wb") as f:
                        for chunk in resp2.iter_bytes(chunk_size=65536):
                            f.write(chunk)
                return dest_path

            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)

        return dest_path
