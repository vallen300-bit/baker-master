"""
Sentinel AI — Whoop API Client (v2)
Read-only access to Whoop health data: Recovery, Sleep, Cycle (strain), Workouts.
OAuth2 token refresh flow with automatic rotation + PostgreSQL persistence.
"""
import logging
import os
import time
from typing import Optional

import httpx
import psycopg2

from config.settings import config

logger = logging.getLogger("sentinel.whoop")

# Rate limits: 100/min, 10,000/day
_RATE_WARN_THRESHOLD = 80   # warn at 80 remaining per minute
_RATE_PAUSE_THRESHOLD = 10  # pause at 10 remaining per minute


# -------------------------------------------------------
# Token Persistence (PostgreSQL)
# -------------------------------------------------------

def _ensure_token_table():
    """Create the whoop_tokens table if it doesn't exist."""
    try:
        conn = psycopg2.connect(**config.postgres.dsn_params)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS whoop_tokens (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    refresh_token TEXT NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    CONSTRAINT single_row CHECK (id = 1)
                )
            """)
        conn.close()
    except Exception as e:
        logger.warning(f"Could not ensure whoop_tokens table: {e}")


def _load_token_from_db() -> Optional[str]:
    """Load the latest refresh token from PostgreSQL. Returns None if not found."""
    try:
        conn = psycopg2.connect(**config.postgres.dsn_params)
        with conn.cursor() as cur:
            cur.execute("SELECT refresh_token FROM whoop_tokens WHERE id = 1")
            row = cur.fetchone()
        conn.close()
        if row:
            logger.info("Loaded Whoop refresh token from database")
            return row[0]
    except Exception as e:
        logger.warning(f"Could not load Whoop token from DB: {e}")
    return None


def _save_token_to_db(refresh_token: str):
    """Persist the rotated refresh token to PostgreSQL."""
    try:
        conn = psycopg2.connect(**config.postgres.dsn_params)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO whoop_tokens (id, refresh_token, updated_at)
                VALUES (1, %s, NOW())
                ON CONFLICT (id) DO UPDATE
                SET refresh_token = EXCLUDED.refresh_token,
                    updated_at = NOW()
            """, (refresh_token,))
        conn.close()
        logger.info("Whoop refresh token persisted to database")
    except Exception as e:
        logger.error(f"CRITICAL: Failed to persist Whoop refresh token to DB: {e}")


class WhoopClient:
    """Whoop API v2 wrapper — read-only polling client with OAuth2 token refresh."""

    _instance = None

    @classmethod
    def _get_global_instance(cls):
        """Return the module-level singleton. Lazy-init if needed."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._client_id = config.whoop.client_id
        self._client_secret = config.whoop.client_secret
        self._base_url = config.whoop.base_url
        self._token_url = config.whoop.token_url

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        # Rate limiting state
        self._request_count = 0
        self._rate_window_start = time.time()

        # Token loading priority: DB first (latest rotated), then env var (initial seed)
        _ensure_token_table()
        db_token = _load_token_from_db()
        if db_token:
            self._refresh_token = db_token
        else:
            self._refresh_token = config.whoop.refresh_token
            if self._refresh_token:
                # Seed the DB with the env var token on first run
                _save_token_to_db(self._refresh_token)

        if not self._refresh_token:
            logger.warning("WHOOP_REFRESH_TOKEN not set — Whoop client will not work")
        else:
            # Get initial access token
            self._refresh_access_token()

    # -------------------------------------------------------
    # OAuth2 Token Refresh
    # -------------------------------------------------------

    def _refresh_access_token(self):
        """POST to Whoop OAuth2 token endpoint with grant_type=refresh_token."""
        try:
            resp = httpx.post(
                self._token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            # Update refresh token if rotated — persist to DB immediately
            if "refresh_token" in data:
                self._refresh_token = data["refresh_token"]
                _save_token_to_db(self._refresh_token)
                logger.info("Whoop refresh token rotated — persisted to database")
            self._token_expires_at = time.time() + data.get("expires_in", 3600) - 300  # 5 min buffer
            logger.info("Whoop access token refreshed successfully")
        except httpx.HTTPStatusError as e:
            logger.error(f"Whoop token refresh failed (HTTP {e.response.status_code}): {e}")
            raise
        except Exception as e:
            logger.error(f"Whoop token refresh failed: {e}")
            raise

    def _ensure_token(self):
        """Refresh access token if expired or about to expire."""
        if not self._access_token or time.time() >= self._token_expires_at:
            self._refresh_access_token()

    # -------------------------------------------------------
    # Rate Limiting
    # -------------------------------------------------------

    def _check_rate_limit(self, response: httpx.Response = None):
        """Track rate limits via response headers and local counter."""
        now = time.time()
        # Reset counter every 60 seconds
        if now - self._rate_window_start > 60:
            self._request_count = 0
            self._rate_window_start = now

        self._request_count += 1

        if response is not None:
            remaining = response.headers.get("X-RateLimit-Remaining")
            reset_at = response.headers.get("X-RateLimit-Reset")

            if remaining is not None:
                remaining = int(remaining)
                if remaining <= _RATE_PAUSE_THRESHOLD:
                    sleep_secs = 60
                    if reset_at:
                        try:
                            sleep_secs = max(1, int(reset_at) - int(now))
                        except (ValueError, TypeError):
                            pass
                    logger.warning(
                        f"Whoop rate limit critical ({remaining} remaining) — sleeping {sleep_secs}s"
                    )
                    time.sleep(sleep_secs)
                elif remaining <= _RATE_WARN_THRESHOLD:
                    logger.warning(f"Whoop rate limit warning: {remaining} remaining this minute")

    # -------------------------------------------------------
    # Paginated GET Helper
    # -------------------------------------------------------

    def _paginated_get(self, endpoint: str, params: dict = None) -> list[dict]:
        """Fetch all pages from a paginated Whoop endpoint."""
        all_records = []
        params = dict(params) if params else {}

        while True:
            self._ensure_token()
            try:
                resp = httpx.get(
                    f"{self._base_url}{endpoint}",
                    params=params,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    timeout=30.0,
                )
            except httpx.RequestError as e:
                logger.error(f"Whoop request error for {endpoint}: {e}")
                break

            self._check_rate_limit(resp)

            # Handle specific HTTP errors
            if resp.status_code == 401:
                logger.warning("Whoop 401 — refreshing token and retrying once")
                self._refresh_access_token()
                resp = httpx.get(
                    f"{self._base_url}{endpoint}",
                    params=params,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    timeout=30.0,
                )
                if resp.status_code != 200:
                    logger.error(f"Whoop retry after 401 failed: {resp.status_code}")
                    break

            if resp.status_code == 404:
                logger.warning(f"Whoop 404 for {endpoint} — no data for this range")
                return []

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After", "60")
                try:
                    sleep_secs = int(retry_after)
                except (ValueError, TypeError):
                    sleep_secs = 60
                logger.warning(f"Whoop 429 rate limited — sleeping {sleep_secs}s and retrying")
                time.sleep(sleep_secs)
                continue  # retry same request

            if resp.status_code >= 500:
                logger.error(f"Whoop server error {resp.status_code} for {endpoint} — skipping")
                break

            resp.raise_for_status()
            data = resp.json()
            all_records.extend(data.get("records", []))

            next_token = data.get("next_token")
            if not next_token:
                break
            params["nextToken"] = next_token

        return all_records

    # -------------------------------------------------------
    # API Methods (Whoop API v2)
    # -------------------------------------------------------

    def get_recovery(self, start: str, end: str) -> list[dict]:
        """GET /v2/recovery — daily recovery records."""
        return self._paginated_get("/recovery", params={"start": start, "end": end})

    def get_sleep(self, start: str, end: str) -> list[dict]:
        """GET /v2/activity/sleep — sleep records with stage breakdown."""
        return self._paginated_get("/activity/sleep", params={"start": start, "end": end})

    def get_cycle(self, start: str, end: str) -> list[dict]:
        """GET /v2/cycle — physiological cycle (strain) data."""
        return self._paginated_get("/cycle", params={"start": start, "end": end})

    def get_workout(self, start: str, end: str) -> list[dict]:
        """GET /v2/activity/workout — workout records."""
        return self._paginated_get("/activity/workout", params={"start": start, "end": end})

    def get_user_profile(self) -> dict:
        """GET /v2/user/profile/basic — user profile for validation."""
        self._ensure_token()
        resp = httpx.get(
            f"{self._base_url}/user/profile/basic",
            headers={"Authorization": f"Bearer {self._access_token}"},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()
