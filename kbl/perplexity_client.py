"""Perplexity Sonar API client — cited web-grounded answers.

Wraps the Perplexity HTTP API behind a thin synchronous Python interface used by
``tools/perplexity.py`` to expose one MCP tool:

    - ask — a single Sonar chat-completions call that returns a cited answer

Perplexity speaks the OpenAI chat-completions shape:
``POST /chat/completions`` with ``{model, messages:[{role, content}], ...}``.
The response carries ``choices[0].message.content`` (the answer text), a
top-level ``citations`` list (URLs) and/or ``search_results`` (``{title, url,
date}``), plus a ``usage`` block (``prompt_tokens`` / ``completion_tokens``).

Auth: bearer token from ``PERPLEXITY_API_KEY`` env var.
Base URL: ``PERPLEXITY_BASE_URL`` env var (default ``https://api.perplexity.ai``).

Error surface (mirrors kbl.grok_client):
    - 401 → PerplexityAuthError
    - 403 → PerplexityForbiddenError
    - 422 → PerplexityValidationError
    - 429 → backoff per ``Retry-After`` (max 3 retries), then PerplexityRateLimitError
    - 5xx → PerplexityServerError (no retry)
    - timeout / network → PerplexityTransportError
    - All HTTP calls wrapped try/except per repo hard rule.

Default model: ``sonar`` — Perplexity's lightweight web-grounded model. ``sonar-pro``
and ``sonar-reasoning-pro`` are reachable via the ``model`` parameter (the older
``sonar-reasoning`` was deprecated by Perplexity 2025-12-15).

Cost: Perplexity Sonar billing is token cost PLUS a per-request search fee, so the
response carries an authoritative ``usage.cost`` block (``total_cost`` /
``request_cost``). ``ask`` surfaces the exact ``total_cost`` as ``cost_usd`` (with
``cost_is_external = True``); when the block is absent it falls back to a token-rate
estimate plus any reported ``request_cost``. The governed dispatcher records that
exact USD figure so the daily total + circuit breaker do not undercount (G0 #2443).

Key rotation: ``PerplexityClient.__init__`` reads ``PERPLEXITY_API_KEY`` once at
construction. After rotating the key on Render, call
``tools.perplexity.reset_client_cache()`` to drop the cached client so the next
dispatch re-reads the fresh env var (mirrors ``tools.grok.reset_client_cache``).
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx


# ─────────────────────────── exceptions ───────────────────────────


class PerplexityError(RuntimeError):
    """Base class for any Perplexity client failure."""


class PerplexityAuthError(PerplexityError):
    """401 — API key missing, invalid, or revoked."""


class PerplexityForbiddenError(PerplexityError):
    """403 — caller lacks permission on this resource."""


class PerplexityValidationError(PerplexityError):
    """422 — server rejected the request body."""


class PerplexityRateLimitError(PerplexityError):
    """429 — retry budget exhausted after honouring Retry-After."""


class PerplexityServerError(PerplexityError):
    """5xx — server-side failure; no retry."""


class PerplexityTransportError(PerplexityError):
    """Network failure / timeout below the HTTP layer."""


# ─────────────────────────── constants ───────────────────────────


_DEFAULT_BASE_URL = "https://api.perplexity.ai"
_DEFAULT_TIMEOUT = 60.0
_MAX_RETRIES = 3
_DEFAULT_RETRY_AFTER = 30.0
_DEFAULT_MODEL = "sonar"


# ─────────────────────────── client ───────────────────────────


class PerplexityClient:
    """Synchronous httpx wrapper for the Perplexity Sonar chat-completions API.

    Instantiation reads env at construction time; pass overrides explicitly for
    tests. A single ``httpx.Client`` is held as instance state so its HTTPS
    connection pool is reused across requests. Call ``close()`` to release it.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _MAX_RETRIES,
        _sleep: Any = time.sleep,
        _http_client: Optional[httpx.Client] = None,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("PERPLEXITY_API_KEY", "")
        if not key:
            raise PerplexityAuthError(
                "PERPLEXITY_API_KEY not set; AH1 must set the Render env var before merge."
            )
        self._api_key = key
        self._base_url = (
            (base_url or os.environ.get("PERPLEXITY_BASE_URL") or _DEFAULT_BASE_URL)
            .rstrip("/")
        )
        self._timeout = timeout
        self._max_retries = max_retries
        self._sleep = _sleep
        self._http_client = (
            _http_client if _http_client is not None else httpx.Client(timeout=self._timeout)
        )

    def close(self) -> None:
        """Release the underlying httpx connection pool."""
        try:
            self._http_client.close()
        except Exception:
            pass

    # ─────────────────────── private helpers ───────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        return self._base_url + "/" + path.lstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        """Single HTTP round-trip with retry on 429.

        429 retry honours ``Retry-After`` (falls back to 30s); max
        ``self._max_retries`` retries. 5xx surfaces immediately. Other errors
        map to the ``Perplexity*Error`` hierarchy.

        ``timeout`` overrides the client default for this call only; pass
        ``None`` to inherit the per-instance default. Per-attempt semantics —
        bounds each individual HTTP attempt, NOT the total wall-clock across
        retries (mirrors GrokClient._request).
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                request_kwargs: dict[str, Any] = {
                    "headers": self._headers(),
                    "json": json,
                }
                if timeout is not None:
                    request_kwargs["timeout"] = timeout
                resp = self._http_client.request(
                    method,
                    self._url(path),
                    **request_kwargs,
                )
            except httpx.TimeoutException as e:
                raise PerplexityTransportError(f"timeout calling {method} {path}: {e}") from e
            except httpx.HTTPError as e:
                raise PerplexityTransportError(f"transport error on {method} {path}: {e}") from e

            status = resp.status_code

            if 200 <= status < 300:
                if not resp.content:
                    return {}
                try:
                    return resp.json()
                except ValueError as e:
                    raise PerplexityServerError(f"non-JSON body on {method} {path}: {e}") from e

            if status == 401:
                raise PerplexityAuthError(_extract_detail(resp) or "401 — invalid or missing API key")
            if status == 403:
                raise PerplexityForbiddenError(_extract_detail(resp) or "403 — forbidden")
            if status == 422:
                raise PerplexityValidationError(_extract_detail(resp) or "422 — validation error")
            if status == 429:
                if attempt > self._max_retries:
                    raise PerplexityRateLimitError(
                        f"429 — retry budget ({self._max_retries}) exhausted: {_extract_detail(resp)}"
                    )
                wait = _parse_retry_after(resp.headers.get("Retry-After"))
                self._sleep(wait)
                continue
            if 500 <= status < 600:
                raise PerplexityServerError(f"{status} on {method} {path}: {_extract_detail(resp)}")

            raise PerplexityError(f"unexpected {status} on {method} {path}: {_extract_detail(resp)}")

    # ─────────────────────── public surface ───────────────────────

    def ask(
        self,
        prompt: str,
        model: str = _DEFAULT_MODEL,
        max_tokens: int = 4000,
        search_domain_filter: Optional[list[str]] = None,
        instructions: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        """POST /chat/completions — a single Sonar call.

        Returns ``{text, citations: [...], model, status, tokens_in, tokens_out,
        total_tokens, cost_usd, cost_is_external, raw_id}``. ``cost_usd`` is the
        provider's exact billed total when ``cost_is_external`` is True, else a
        token-rate estimate plus any reported request fee. ``text`` is
        ``choices[0].message.content``;
        ``citations`` is the merged + de-duplicated list of cited web sources
        (``{url, title, date, snippet}``).

        ``search_domain_filter`` restricts (or, with a leading ``-``, blocks) the
        web sources Perplexity may cite. ``instructions`` becomes a leading system
        message. ``timeout`` overrides the per-instance default for this call only.
        """
        messages: list[dict[str, Any]] = []
        if instructions:
            messages.append({"role": "system", "content": instructions})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if search_domain_filter:
            body["search_domain_filter"] = list(search_domain_filter)
        return _shape_ask_response(
            self._request("POST", "chat/completions", json=body, timeout=timeout),
            model,
        )


# ─────────────────────────── helpers ───────────────────────────


def _extract_detail(resp: httpx.Response) -> str:
    """Best-effort extract of a human-readable error message from an HTTP response."""
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err)
            return str(err or body.get("detail") or body.get("message") or body)
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


def _shape_ask_response(payload: dict, model: str) -> dict:
    """Normalize a /chat/completions payload to the public ask() return shape."""
    choices = payload.get("choices") or []
    text = ""
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                text = content
    usage = payload.get("usage") or {}
    tokens_in = int(usage.get("prompt_tokens") or 0)
    tokens_out = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (tokens_in + tokens_out))
    resolved_model = payload.get("model") or model
    return {
        "text": text,
        "citations": _merge_citations(payload),
        "model": resolved_model,
        "status": (choices[0].get("finish_reason") if choices and isinstance(choices[0], dict) else "") or "",
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "total_tokens": total,
        "cost_usd": _cost_usd_from_usage(usage, resolved_model),
        "cost_is_external": _external_cost_usd(usage) is not None,
        "raw_id": payload.get("id") or "",
    }


def _merge_citations(payload: dict) -> list[dict[str, Any]]:
    """Merge Perplexity's two citation shapes into one ordered, de-duplicated list.

    ``search_results`` (rich: ``{title, url, date}``) is preferred over the bare
    ``citations`` URL-string list on a URL tie — same first-source-wins dedup as
    kbl.grok_client._merge_citations_by_url. Entries without a URL are kept.
    """
    rich = payload.get("search_results")
    bare = payload.get("citations")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for src in (rich if isinstance(rich, list) else [], bare if isinstance(bare, list) else []):
        for c in src:
            shaped = _shape_citation(c)
            url = shaped.get("url") or ""
            if url and url in seen:
                continue
            if url:
                seen.add(url)
            out.append(shaped)
    return out


def _shape_citation(citation: Any) -> dict[str, Any]:
    """Project a Perplexity citation (URL string or ``{title,url,date}`` dict) to a
    stable shape ``{url, title, date, snippet}``."""
    if isinstance(citation, str):
        return {"url": citation, "title": "", "date": "", "snippet": ""}
    if not isinstance(citation, dict):
        return {"url": "", "title": "", "date": "", "snippet": ""}
    return {
        "url": citation.get("url") or citation.get("link") or "",
        "title": citation.get("title") or "",
        "date": citation.get("date") or citation.get("published_at") or "",
        "snippet": citation.get("snippet") or citation.get("description") or "",
    }


def _external_cost_usd(usage: dict[str, Any]) -> Optional[float]:
    """Exact USD cost Perplexity reports in ``usage.cost.total_cost``, or ``None``.

    Perplexity Sonar's billed total = token cost + per-request search fee, and the
    API returns that authoritative figure here. ``None`` (block absent or non-
    numeric) signals the caller to fall back to the token-rate estimate.
    """
    cost = usage.get("cost")
    if isinstance(cost, dict):
        total = cost.get("total_cost")
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            return float(total)
    return None


def _request_fee_usd(usage: dict[str, Any]) -> float:
    """Per-request search fee Perplexity reports in ``usage.cost.request_cost``.

    Used only in the token-estimate fallback (when ``total_cost`` is absent) so the
    estimate still includes the non-token request fee. Returns 0.0 when unreported.
    """
    cost = usage.get("cost")
    if isinstance(cost, dict):
        fee = cost.get("request_cost")
        if isinstance(fee, (int, float)) and not isinstance(fee, bool):
            return float(fee)
    return 0.0


def _cost_usd_from_usage(usage: dict[str, Any], model: str) -> float:
    """Best-available USD cost for a Perplexity call.

    Prefers the EXACT external total Perplexity bills (``usage.cost.total_cost``),
    which already folds in the per-request search fee. When that block is absent,
    falls back to a token-rate estimate PLUS any reported ``request_cost`` so the
    fee is not silently dropped (G0 #2443 H1 — the governor must not undercount).
    Returns 0.0 if usage is empty.
    """
    external = _external_cost_usd(usage)
    if external is not None:
        return round(external, 8)
    rates = {
        "sonar": (1.00, 1.00),
        "sonar-pro": (3.00, 15.00),
        "sonar-reasoning-pro": (2.00, 8.00),
    }
    rate_in, rate_out = rates.get(model, rates["sonar"])
    tokens_in = float(usage.get("prompt_tokens") or 0)
    tokens_out = float(usage.get("completion_tokens") or 0)
    token_cost = (tokens_in * rate_in + tokens_out * rate_out) / 1_000_000.0
    return round(token_cost + _request_fee_usd(usage), 8)
