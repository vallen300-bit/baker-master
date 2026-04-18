"""Minimal HTTP wrapper for Voyage AI's ``voyage-3`` embedding endpoint.

Used by Step 2 transcript/scan resolvers (KBL-B §4.3). Intentionally tiny
surface — one function, one exception. Degraded-mode policy lives in the
calling resolver, not here: this module raises ``VoyageUnavailableError``
on any transport-level problem and lets the caller decide what to do.

Env:
    VOYAGE_API_KEY       — required. KBL-A provisions this in secrets.
    VOYAGE_API_HOST      — optional override (for local testing / proxies).
                           Default: ``https://api.voyageai.com``.
    KBL_VOYAGE_MODEL     — optional model override. Default: ``voyage-3``.

Design note: we do not add retries here. Step 2's cost-vs-latency tradeoff
prefers failing fast to new-arc semantics over hanging on repeated 5xx.
If a retry policy is desired later, wrap this function at the call site.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from kbl.exceptions import VoyageUnavailableError

_DEFAULT_HOST = "https://api.voyageai.com"
_DEFAULT_MODEL = "voyage-3"
_DEFAULT_TIMEOUT = 10

_API_KEY_ENV = "VOYAGE_API_KEY"
_HOST_ENV = "VOYAGE_API_HOST"
_MODEL_ENV = "KBL_VOYAGE_MODEL"


def embed(
    text: str,
    *,
    model: str | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
    host: str | None = None,
    api_key: str | None = None,
) -> list[float]:
    """Return the embedding vector for ``text``.

    Args:
        text: text to embed. Empty strings raise ``ValueError`` — caller
            must short-circuit zero-length input before hitting the API.
        model: embedding model override. Defaults to env
            ``KBL_VOYAGE_MODEL`` or ``voyage-3``.
        timeout: HTTP timeout seconds. Default 10.
        host: API host override. Defaults to env ``VOYAGE_API_HOST`` or
            ``https://api.voyageai.com``.
        api_key: explicit API key. Defaults to ``VOYAGE_API_KEY`` env.

    Returns:
        Python list of floats — the embedding vector.

    Raises:
        ValueError: on empty text or missing API key.
        VoyageUnavailableError: on HTTP error, timeout, connection
            refused, or unparseable response envelope.
    """
    if not text:
        raise ValueError("voyage.embed requires non-empty text")
    key = api_key or os.environ.get(_API_KEY_ENV)
    if not key:
        raise ValueError(
            f"{_API_KEY_ENV} env var not set and no api_key passed"
        )
    resolved_host = (host or os.environ.get(_HOST_ENV) or _DEFAULT_HOST).rstrip("/")
    resolved_model = model or os.environ.get(_MODEL_ENV) or _DEFAULT_MODEL
    url = f"{resolved_host}/v1/embeddings"
    body = {
        "input": [text],
        "model": resolved_model,
        "input_type": "document",
    }
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise VoyageUnavailableError(
            f"Voyage HTTP {e.code} at {url}: {e.reason}"
        ) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise VoyageUnavailableError(f"Voyage unreachable at {url}: {e}") from e

    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as e:
        raise VoyageUnavailableError(
            f"Voyage returned non-JSON envelope: {e}"
        ) from e
    try:
        return list(data["data"][0]["embedding"])
    except (KeyError, IndexError, TypeError) as e:
        raise VoyageUnavailableError(
            f"Voyage response missing data[0].embedding: {raw[:200]}"
        ) from e
