"""xAI Grok API client — Responses API + Live Search.

Wraps the xAI Grok HTTP API behind a thin synchronous Python interface used by
``tools/grok.py`` to expose three MCP tools to Baker matter Desks:

    - x_search    — Live Search over X/Twitter (source type ``x``)
    - web_search  — Live Search over the open web (source types ``web`` + ``news``)
    - ask         — plain Grok Responses-API call (no Live Search)

All three call the same ``POST /v1/responses`` endpoint. ``x_search`` /
``web_search`` set ``search_parameters`` on the request body to enable xAI's
native Live Search tool (NOT a function/tool entry — that's a separate xAI
feature ``tools=[{"type": "web_search"}]`` which is older). The native
``search_parameters`` form returns citations + structured source metadata
directly on the response and is the documented production path.

Auth: bearer token from ``XAI_API_KEY`` env var.
Base URL: ``XAI_BASE_URL`` env var (default ``https://api.x.ai/v1``).

Error surface (mirrors kbl.claimsmax_client):
    - 401 → GrokAuthError
    - 403 → GrokForbiddenError
    - 422 → GrokValidationError
    - 429 → backoff per ``Retry-After`` (max 3 retries), then GrokRateLimitError
    - 5xx → GrokServerError (no retry)
    - timeout / network → GrokTransportError
    - All HTTP calls wrapped try/except per repo hard rule.

Default model: ``grok-4.3`` — xAI's documented "most intelligent and fastest"
general-purpose model (1M context window). Reasoning model
``grok-4.20-0309-reasoning`` available via the ``model`` parameter on ``ask``.

Brief-§Scope divergences resolved here (bus-posted to lead as
grok-api-spec-mismatch 2026-05-17):
    - Search invocation: search_parameters dict, not tools=[{type:web_search}].
    - Model name: grok-4.3 default (brief said grok-4.20-reasoning).
    - X vs web: one client method per surface, all routed to /v1/responses.
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx


# ─────────────────────────── exceptions ───────────────────────────


class GrokError(RuntimeError):
    """Base class for any Grok client failure."""


class GrokAuthError(GrokError):
    """401 — API key missing, invalid, or revoked."""


class GrokForbiddenError(GrokError):
    """403 — caller lacks permission on this resource."""


class GrokValidationError(GrokError):
    """422 — server rejected the request body."""


class GrokRateLimitError(GrokError):
    """429 — retry budget exhausted after honouring Retry-After."""


class GrokServerError(GrokError):
    """5xx — server-side failure; no retry."""


class GrokTransportError(GrokError):
    """Network failure / timeout below the HTTP layer."""


# ─────────────────────────── constants ───────────────────────────


_DEFAULT_BASE_URL = "https://api.x.ai/v1"
_DEFAULT_TIMEOUT = 60.0
_MAX_RETRIES = 3
_DEFAULT_RETRY_AFTER = 30.0
_DEFAULT_MODEL = "grok-4.3"


# ─────────────────────────── client ───────────────────────────


class GrokClient:
    """Synchronous httpx wrapper for the xAI Grok Responses API.

    Instantiation reads env at construction time; pass overrides explicitly
    for tests. A single ``httpx.Client`` is held as instance state so its
    HTTPS connection pool is reused across requests (Live Search calls can
    take 5-20s each; pool reuse avoids per-call TLS handshake).

    Call ``close()`` to release the connection pool.
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
        key = api_key if api_key is not None else os.environ.get("XAI_API_KEY", "")
        if not key:
            raise GrokAuthError(
                "XAI_API_KEY not set; AH1 must set the Render env var before merge."
            )
        self._api_key = key
        self._base_url = (
            (base_url or os.environ.get("XAI_BASE_URL") or _DEFAULT_BASE_URL)
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

    def _request(self, method: str, path: str, *, json: Optional[dict] = None) -> dict:
        """Single HTTP round-trip with retry on 429.

        429 retry honours ``Retry-After`` (falls back to 30s); max
        ``self._max_retries`` retries. 5xx surfaces immediately. Other errors
        map to the ``Grok*Error`` hierarchy.
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._http_client.request(
                    method,
                    self._url(path),
                    headers=self._headers(),
                    json=json,
                )
            except httpx.TimeoutException as e:
                raise GrokTransportError(f"timeout calling {method} {path}: {e}") from e
            except httpx.HTTPError as e:
                raise GrokTransportError(f"transport error on {method} {path}: {e}") from e

            status = resp.status_code

            if 200 <= status < 300:
                if not resp.content:
                    return {}
                try:
                    return resp.json()
                except ValueError as e:
                    raise GrokServerError(f"non-JSON body on {method} {path}: {e}") from e

            if status == 401:
                raise GrokAuthError(_extract_detail(resp) or "401 — invalid or missing API key")
            if status == 403:
                raise GrokForbiddenError(_extract_detail(resp) or "403 — forbidden")
            if status == 422:
                raise GrokValidationError(_extract_detail(resp) or "422 — validation error")
            if status == 429:
                if attempt > self._max_retries:
                    raise GrokRateLimitError(
                        f"429 — retry budget ({self._max_retries}) exhausted: {_extract_detail(resp)}"
                    )
                wait = _parse_retry_after(resp.headers.get("Retry-After"))
                self._sleep(wait)
                continue
            if 500 <= status < 600:
                raise GrokServerError(f"{status} on {method} {path}: {_extract_detail(resp)}")

            raise GrokError(f"unexpected {status} on {method} {path}: {_extract_detail(resp)}")

    # ─────────────────────── public surface ───────────────────────

    def ask(
        self,
        prompt: str,
        model: str = _DEFAULT_MODEL,
        max_output_tokens: int = 4000,
        temperature: Optional[float] = None,
        instructions: Optional[str] = None,
    ) -> dict:
        """POST /responses — plain Grok call (no Live Search).

        Returns ``{text, model, status, tokens_in, tokens_out, total_tokens,
        cost_usd, raw_id}``. ``text`` is the flattened ``output[*].content[*].text``
        concatenation; full payload preserved in ``raw_id`` for the matter Desk
        to fetch via ``GET /v1/responses/{id}`` if it needs structured access.
        """
        body: dict[str, Any] = {
            "model": model,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if instructions:
            body["instructions"] = instructions
        return _shape_ask_response(self._request("POST", "responses", json=body), model)

    def x_search(
        self,
        query: str,
        max_results: int = 10,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        model: str = _DEFAULT_MODEL,
    ) -> dict:
        """POST /responses with search_parameters.sources=[{type:'x'}].

        Returns ``{summary, tweets: [...], model, tokens_in, tokens_out, cost_usd}``.
        Tweets are extracted from the response citations list where available;
        full citation payload is included on each tweet dict.
        """
        return _shape_search_response(
            self._request(
                "POST",
                "responses",
                json=_search_body(
                    query=query,
                    sources=[{"type": "x"}],
                    max_results=max_results,
                    from_date=from_date,
                    to_date=to_date,
                    model=model,
                ),
            ),
            model=model,
            kind="x",
        )

    def web_search(
        self,
        query: str,
        freshness_days: Optional[int] = 7,
        max_results: int = 10,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        model: str = _DEFAULT_MODEL,
        include_news: bool = True,
    ) -> dict:
        """POST /responses with search_parameters.sources=[{type:'web'} (+ news)].

        ``freshness_days`` is a convenience: when set and ``from_date`` is None,
        the client computes ``from_date = today - N days`` server-side via the
        from_date parameter on the xAI API. Set ``freshness_days=None`` to keep
        the full Live Search default window.

        Returns ``{summary, citations: [...], model, tokens_in, tokens_out, cost_usd}``.
        """
        if from_date is None and freshness_days is not None and freshness_days > 0:
            from_date = _utc_today_minus_days(freshness_days)
        sources: list[dict[str, Any]] = [{"type": "web"}]
        if include_news:
            sources.append({"type": "news"})
        return _shape_search_response(
            self._request(
                "POST",
                "responses",
                json=_search_body(
                    query=query,
                    sources=sources,
                    max_results=max_results,
                    from_date=from_date,
                    to_date=to_date,
                    model=model,
                ),
            ),
            model=model,
            kind="web",
        )


# ─────────────────────────── helpers ───────────────────────────


def _extract_detail(resp: httpx.Response) -> str:
    """Best-effort extract of a human-readable error message from an HTTP response."""
    try:
        body = resp.json()
        if isinstance(body, dict):
            return str(body.get("detail") or body.get("error") or body.get("message") or body)
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


def _utc_today_minus_days(days: int) -> str:
    """Return ISO-8601 date (YYYY-MM-DD) for today UTC minus N days."""
    import datetime as _dt

    d = _dt.datetime.now(_dt.timezone.utc).date() - _dt.timedelta(days=days)
    return d.isoformat()


def _search_body(
    *,
    query: str,
    sources: list[dict[str, Any]],
    max_results: int,
    from_date: Optional[str],
    to_date: Optional[str],
    model: str,
) -> dict[str, Any]:
    """Build the /responses request body for a Live Search call."""
    search_parameters: dict[str, Any] = {
        "mode": "on",
        "sources": sources,
        "max_search_results": max_results,
        "return_citations": True,
    }
    if from_date:
        search_parameters["from_date"] = from_date
    if to_date:
        search_parameters["to_date"] = to_date
    return {
        "model": model,
        "input": query,
        "search_parameters": search_parameters,
    }


def _shape_ask_response(payload: dict, model: str) -> dict:
    """Normalize /responses payload to the public ask() return shape."""
    usage = payload.get("usage") or {}
    tokens_in = int(usage.get("input_tokens") or 0)
    tokens_out = int(usage.get("output_tokens") or 0)
    total = int(usage.get("total_tokens") or (tokens_in + tokens_out))
    return {
        "text": _flatten_output_text(payload.get("output") or []),
        "model": payload.get("model") or model,
        "status": payload.get("status") or "",
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "total_tokens": total,
        "cost_usd": _cost_usd_from_usage(usage),
        "raw_id": payload.get("id") or "",
    }


def _shape_search_response(payload: dict, *, model: str, kind: str) -> dict:
    """Normalize a Live Search /responses payload to a slim search result dict.

    ``kind`` is ``"x"`` or ``"web"``. When ``kind == "x"``, returns ``{summary,
    tweets: [...], ...}``. Otherwise ``{summary, citations: [...], ...}``. Both
    shapes include token + cost metadata so the caller can budget per request.
    """
    citations = payload.get("citations") or []
    summary = _flatten_output_text(payload.get("output") or [])
    usage = payload.get("usage") or {}
    tokens_in = int(usage.get("input_tokens") or 0)
    tokens_out = int(usage.get("output_tokens") or 0)
    base = {
        "summary": summary,
        "model": payload.get("model") or model,
        "status": payload.get("status") or "",
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "total_tokens": int(usage.get("total_tokens") or (tokens_in + tokens_out)),
        "cost_usd": _cost_usd_from_usage(usage),
        "raw_id": payload.get("id") or "",
    }
    if kind == "x":
        base["tweets"] = [_shape_tweet_citation(c) for c in citations]
    else:
        base["citations"] = [_shape_web_citation(c) for c in citations]
    return base


def _flatten_output_text(output: list[Any]) -> str:
    """Concatenate ``output[*].content[*].text`` chunks into a single string.

    xAI returns ``output`` as a list of message objects, each with a ``content``
    list of typed blocks. Only ``output_text`` blocks contribute to the
    flattened result; reasoning blocks + tool-call blocks are dropped.
    """
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in ("output_text", "text"):
                txt = block.get("text")
                if isinstance(txt, str):
                    parts.append(txt)
    return "".join(parts)


def _shape_tweet_citation(citation: Any) -> dict[str, Any]:
    """Project an xAI citation entry into a tweet-shaped dict.

    xAI citations are returned as a list — entries may be plain URL strings
    (older shape) or dicts with structured metadata. We accept both and emit a
    stable shape: ``{url, author, date, text, engagement}``.
    """
    if isinstance(citation, str):
        return {"url": citation, "author": "", "date": "", "text": "", "engagement": {}}
    if not isinstance(citation, dict):
        return {"url": "", "author": "", "date": "", "text": "", "engagement": {}}
    return {
        "url": citation.get("url") or citation.get("link") or "",
        "author": citation.get("author") or citation.get("handle") or "",
        "date": citation.get("date") or citation.get("created_at") or "",
        "text": citation.get("text") or citation.get("snippet") or citation.get("title") or "",
        "engagement": {
            "favorites": citation.get("favorite_count") or citation.get("favorites") or 0,
            "views": citation.get("view_count") or citation.get("views") or 0,
            "reposts": citation.get("repost_count") or citation.get("reposts") or 0,
        },
    }


def _shape_web_citation(citation: Any) -> dict[str, Any]:
    """Project an xAI citation entry into a web-citation-shaped dict."""
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


def _cost_usd_from_usage(usage: dict[str, Any]) -> float:
    """Derive USD cost from the xAI usage block.

    Prefer the explicit ``cost_in_usd_ticks`` field when present. xAI ticks
    are denominated at 1 USD = 10^10 ticks (1 tick = $1e-10). Otherwise compute
    from token counts at the documented grok-4.3 rate ($1.25/M input,
    $2.50/M output) — same per-token rate applies to all text models as of
    2026-05-17. Returns 0.0 if usage is empty.
    """
    ticks = usage.get("cost_in_usd_ticks")
    if isinstance(ticks, (int, float)) and ticks > 0:
        return round(float(ticks) / 10_000_000_000.0, 12)
    tokens_in = float(usage.get("input_tokens") or 0)
    tokens_out = float(usage.get("output_tokens") or 0)
    return round((tokens_in * 1.25 + tokens_out * 2.50) / 1_000_000.0, 8)
