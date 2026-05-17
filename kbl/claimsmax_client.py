"""ClaimsMax v1 REST API client.

Wraps the ClaimsMax investigation platform (~187K docs / 173K emails / 1.4M
chunks) behind a thin synchronous Python interface. Used by `tools/claimsmax.py`
to expose MCP tools to Baker matter Desks.

Auth: bearer token from ``CLAIMSMAX_API_KEY`` env var, prefixed ``cmx_``.
Base URL: ``CLAIMSMAX_BASE_URL`` env var (default
``https://brisen.claimsmax.co.uk/api/v1/``).

Error surface:
    - 401 → ClaimsmaxAuthError
    - 404 → ClaimsmaxNotFoundError
    - 422 → ClaimsmaxValidationError
    - 429 → backoff per ``Retry-After`` (max 3 retries), then ClaimsmaxRateLimitError
    - 5xx → ClaimsmaxServerError (no retry)
    - timeout / network → ClaimsmaxTransportError
    - All HTTP calls wrapped try/except per repo hard rule.

``/ask`` is deliberately unimplemented — vendor bug pending Ellie Technologies
fix as of 2026-05-16 (temperature parameter deprecated server-side).
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx


# ─────────────────────────── exceptions ───────────────────────────


class ClaimsmaxError(RuntimeError):
    """Base class for any ClaimsMax client failure."""


class ClaimsmaxAuthError(ClaimsmaxError):
    """401 — API key missing, invalid, or revoked."""


class ClaimsmaxForbiddenError(ClaimsmaxError):
    """403 — caller lacks permission on this resource."""


class ClaimsmaxNotFoundError(ClaimsmaxError):
    """404 — doc_id / run_id not found."""


class ClaimsmaxValidationError(ClaimsmaxError):
    """422 — server rejected the request body."""


class ClaimsmaxRateLimitError(ClaimsmaxError):
    """429 — retry budget exhausted after honouring Retry-After."""


class ClaimsmaxServerError(ClaimsmaxError):
    """5xx — server-side failure; no retry."""


class ClaimsmaxTransportError(ClaimsmaxError):
    """Network failure / timeout below the HTTP layer."""


# ─────────────────────────── constants ───────────────────────────


_DEFAULT_BASE_URL = "https://brisen.claimsmax.co.uk/api/v1/"
_DEFAULT_TIMEOUT = 120.0  # investigations stream slow
_MAX_RETRIES = 3
_DEFAULT_RETRY_AFTER = 30.0  # fallback when header absent


# ─────────────────────────── client ───────────────────────────


class ClaimsmaxClient:
    """Synchronous httpx wrapper for ClaimsMax v1.

    Instantiation reads env at construction time; pass overrides explicitly
    for tests. The client is stateless — no session pooling needed at this
    request volume (caller is MCP tool dispatch, low rate).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _MAX_RETRIES,
        _sleep: Any = time.sleep,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("CLAIMSMAX_API_KEY", "")
        if not key:
            raise ClaimsmaxAuthError(
                "CLAIMSMAX_API_KEY not set; AH1 must set the Render env var before merge."
            )
        self._api_key = key
        self._base_url = (base_url or os.environ.get("CLAIMSMAX_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/") + "/"
        self._timeout = timeout
        self._max_retries = max_retries
        self._sleep = _sleep

    # ─────────────────────── private helpers ───────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        return self._base_url + path.lstrip("/")

    def _request(self, method: str, path: str, *, json: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        """Single HTTP round-trip with retry on 429.

        429 retry honours ``Retry-After`` (falls back to 30s); max
        ``self._max_retries`` retries. 5xx surfaces immediately. Other errors
        map to the ``Claimsmax*Error`` hierarchy.
        """
        attempt = 0
        last_429: Optional[httpx.Response] = None
        while True:
            attempt += 1
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.request(
                        method,
                        self._url(path),
                        headers=self._headers(),
                        json=json,
                        params=params,
                    )
            except httpx.TimeoutException as e:
                raise ClaimsmaxTransportError(f"timeout calling {method} {path}: {e}") from e
            except httpx.HTTPError as e:
                raise ClaimsmaxTransportError(f"transport error on {method} {path}: {e}") from e

            status = resp.status_code

            if 200 <= status < 300:
                if not resp.content:
                    return {}
                try:
                    return resp.json()
                except ValueError as e:
                    raise ClaimsmaxServerError(f"non-JSON body on {method} {path}: {e}") from e

            if status == 401:
                raise ClaimsmaxAuthError(_extract_detail(resp) or "401 — invalid or missing API key")
            if status == 403:
                raise ClaimsmaxForbiddenError(_extract_detail(resp) or "403 — forbidden")
            if status == 404:
                raise ClaimsmaxNotFoundError(_extract_detail(resp) or f"404 — not found: {path}")
            if status == 422:
                raise ClaimsmaxValidationError(_extract_detail(resp) or "422 — validation error")
            if status == 429:
                last_429 = resp
                if attempt > self._max_retries:
                    raise ClaimsmaxRateLimitError(
                        f"429 — retry budget ({self._max_retries}) exhausted: {_extract_detail(resp)}"
                    )
                wait = _parse_retry_after(resp.headers.get("Retry-After"))
                self._sleep(wait)
                continue
            if 500 <= status < 600:
                raise ClaimsmaxServerError(f"{status} on {method} {path}: {_extract_detail(resp)}")

            raise ClaimsmaxError(f"unexpected {status} on {method} {path}: {_extract_detail(resp)}")

    # ─────────────────────── public surface ───────────────────────

    def search(
        self,
        query: str,
        filters: Optional[dict] = None,
        mode: str = "natural",
        page: int = 1,
        per_page: int = 25,
        sort: str = "relevance",
        l3_tags_required: Optional[list[str]] = None,
    ) -> dict:
        """POST /search — hybrid full-text + semantic search."""
        body: dict[str, Any] = {
            "query": query,
            "mode": mode,
            "page": page,
            "per_page": per_page,
            "sort": sort,
        }
        if filters:
            body["filters"] = filters
        if l3_tags_required:
            body["l3_tags_required"] = l3_tags_required
        return self._request("POST", "search", json=body)

    def get_document(self, doc_id: str, include_text: bool = False) -> dict:
        """GET /documents/{doc_id} — full document metadata."""
        return self._request(
            "GET", f"documents/{doc_id}", params={"include_text": str(include_text).lower()}
        )

    def get_document_text(self, doc_id: str, page: int = 1, chars_per_page: int = 5000) -> dict:
        """GET /documents/{doc_id}/text — paginated extracted text."""
        return self._request(
            "GET",
            f"documents/{doc_id}/text",
            params={"page": page, "chars_per_page": chars_per_page},
        )

    def get_document_download_url(self, doc_id: str, presigned: bool = True) -> dict:
        """GET /documents/{doc_id}/download — presigned S3 URL (15-min expiry)."""
        return self._request(
            "GET",
            f"documents/{doc_id}/download",
            params={"presigned": str(presigned).lower()},
        )

    def investigate_start(
        self,
        query: str,
        language: str = "en",
        starting_doc_id: Optional[str] = None,
        max_iterations: int = 15,
        uploaded_context: Optional[str] = None,
        exclude_internal: bool = False,
    ) -> dict:
        """POST /investigate — fire-and-forget; returns ``{run_id, status}``."""
        body: dict[str, Any] = {
            "query": query,
            "language": language,
            "max_iterations": max_iterations,
            "exclude_internal": exclude_internal,
        }
        if starting_doc_id:
            body["starting_doc_id"] = starting_doc_id
        if uploaded_context:
            body["uploaded_context"] = uploaded_context
        return self._request("POST", "investigate", json=body)

    def investigate_status(self, run_id: str) -> dict:
        """GET /investigate/{run_id} — slim projection (no event log)."""
        return self._request("GET", f"investigate/{run_id}")

    def investigate_events(self, run_id: str) -> dict:
        """GET /investigate/{run_id}/events — full event log (can be large)."""
        return self._request("GET", f"investigate/{run_id}/events")

    def ask(self, *args: Any, **kwargs: Any) -> dict:
        """POST /ask — DISABLED pending vendor fix.

        ClaimsMax /ask endpoint disabled — vendor bug under repair (temperature
        deprecated server-side as of 2026-05-16). Re-enable when Ellie
        Technologies confirms fix.
        """
        raise NotImplementedError(
            "ClaimsMax /ask endpoint disabled — vendor bug under repair "
            "(temperature deprecated server-side as of 2026-05-16). "
            "Re-enable when Ellie Technologies confirms fix."
        )


# ─────────────────────────── helpers ───────────────────────────


def _extract_detail(resp: httpx.Response) -> str:
    """Best-effort extract of a human-readable error message from an HTTP response."""
    try:
        body = resp.json()
        if isinstance(body, dict):
            return str(body.get("detail") or body.get("error") or body)
        return str(body)
    except ValueError:
        return resp.text[:500]


def _parse_retry_after(header_value: Optional[str]) -> float:
    """Parse Retry-After header. Falls back to 30s if missing or unparseable."""
    if not header_value:
        return _DEFAULT_RETRY_AFTER
    try:
        return max(0.0, float(header_value))
    except (TypeError, ValueError):
        return _DEFAULT_RETRY_AFTER
