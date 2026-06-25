"""M365_GRAPH_CLIENT_FOUNDATION_1: shared Microsoft Graph auth + REST client.

Phase 1 of 5 in the Microsoft 365 migration. Provides the shared Graph
auth + REST surface that Phases 2-4 (mail poll / calendar / send) sit on.

Ships DORMANT: inert unless M365_* env present AND BAKER_USE_GRAPH=true.
Never raises to callers — every external call returns None + logs on failure.
"""
from __future__ import annotations

import hashlib
import logging
import pathlib
import time
from urllib.parse import urlparse

import requests
from msal import ConfidentialClientApplication

from config.settings import GraphConfig

logger = logging.getLogger(__name__)


class GraphClient:
    """Microsoft Graph client-credentials auth + thin REST GET surface.

    The flag gate (`is_ready`) is the single guard: no token is acquired and
    no HTTP is issued unless BAKER_USE_GRAPH is on AND M365_* creds are set.
    MSAL's ConfidentialClientApplication owns the app-token cache/renewal —
    the raw bearer is never cached on the instance.
    """

    def __init__(self, config: GraphConfig | None = None) -> None:
        self.cfg = config or GraphConfig()
        # MSAL app holds the token cache; we never cache the raw bearer ourselves.
        self._app = None
        self._app_cache_key = None

    def _has_cert(self) -> bool:
        """True if a cert credential (inline PEM or path) + thumbprint are present."""
        return bool((self.cfg.cert_private_key or self.cfg.cert_path) and self.cfg.cert_thumbprint)

    @staticmethod
    def _fingerprint(value: str) -> str:
        """Stable non-secret cache token for credential identity checks."""
        if not value:
            return ""
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _cert_path_identity(self) -> tuple:
        cert_path = self.cfg.cert_path
        if not cert_path:
            return ("",)
        try:
            stat = pathlib.Path(cert_path).stat()
            return (cert_path, stat.st_mtime_ns, stat.st_size)
        except OSError:
            return (cert_path,)

    def _current_app_cache_key(self) -> tuple:
        """Current Graph auth identity; changing env/creds forces MSAL rebuild."""
        if self._has_cert():
            credential_identity = (
                "cert",
                self._fingerprint(self.cfg.cert_private_key),
                self._cert_path_identity(),
                self.cfg.cert_thumbprint,
            )
        else:
            credential_identity = ("secret", self._fingerprint(self.cfg.client_secret))
        return (
            self.cfg.tenant_id,
            self.cfg.client_id,
            self.cfg.authority_tmpl,
            tuple(self.cfg.scope),
            credential_identity,
        )

    def is_configured(self) -> bool:
        """True if tenant_id + client_id + a usable credential are present.

        A usable credential is EITHER a client_secret OR a certificate
        (inline PEM or PEM file path) paired with its thumbprint.
        """
        if not (self.cfg.tenant_id and self.cfg.client_id):
            return False
        return bool(self.cfg.client_secret) or self._has_cert()

    def is_enabled(self) -> bool:
        """Reflects the BAKER_USE_GRAPH flag (GraphConfig.enabled)."""
        return bool(self.cfg.enabled)

    def is_ready(self) -> bool:
        """The single gate. Creds present is NOT enough — the flag must be on too.

        Nothing acquires a token or issues HTTP unless this returns True
        (finding 1: enforce the flag, do not merely document it).
        """
        return self.is_enabled() and self.is_configured()

    def _acquire_token(self) -> str | None:
        """Return a valid bearer token, or None. Never raises.

        finding 1: returns None unless is_ready() — no MSAL construction when gated.
        finding 2: does NOT cache the bearer on self. MSAL returns a valid cached
        token and auto-renews from the secret/cert when expired.
        """
        if not self.is_ready():
            return None
        try:
            app_cache_key = self._current_app_cache_key()
            if self._app is None or self._app_cache_key != app_cache_key:
                # Cert takes precedence over client_secret when both are set.
                if self._has_cert():
                    private_key = self.cfg.cert_private_key or pathlib.Path(
                        self.cfg.cert_path
                    ).read_text()
                    credential = {
                        "private_key": private_key,
                        "thumbprint": self.cfg.cert_thumbprint,
                    }
                else:
                    credential = self.cfg.client_secret
                self._app = ConfidentialClientApplication(
                    self.cfg.client_id,
                    authority=self.cfg.authority_tmpl.format(tenant=self.cfg.tenant_id),
                    client_credential=credential,
                )
                self._app_cache_key = app_cache_key
            result = self._app.acquire_token_for_client(scopes=self.cfg.scope)
            if "access_token" in result:
                return result["access_token"]
            # Log only the coarse error code — never error_description or the secret.
            logger.error("Graph token acquisition failed: %s", result.get("error"))
            return None
        except Exception as e:
            logger.error("Graph token acquisition exception: %s", type(e).__name__)
            return None

    def _request(
        self,
        url: str,
        params: dict | None,
        timeout: int,
        log_url: str,
        extra_headers: dict | None = None,
        redact_url: bool = True,
    ) -> dict | None:
        """Shared GET path. Never raises; never logs the token or full delta URL.

        extra_headers: optional non-auth request headers merged on top of the
        bearer (e.g. ``Prefer: IdType="ImmutableId"`` for immutable-id-form
        message reads). The Authorization header is always set last so a caller
        can never override / strip the bearer.

        redact_url: when True (get_url / opaque delta+next links), failures log
        ONLY the redacted marker — never the URL, status body, or final URL, since
        delta/next tokens are sensitive. When False (get / v1.0-relative paths),
        failures additionally log the HTTP status + final URL + Graph error body.
        These carry no secrets (message ids are not credentials; the bearer lives
        in request headers, never the response body) and are the diagnostic that
        tells us WHY a fetch failed instead of a bare exception class name
        (M365_GRAPH_ATTACHMENT diagnosis: smoking-gun was a swallowed status/body).
        """
        # Host-pin BEFORE acquiring a token: never attach the app bearer to a
        # non-Graph URL (latent credential leak via get_url). On reject: no token
        # acquired, no requests.get, and the rejected URL is NOT logged.
        p = urlparse(url)
        if p.scheme != "https" or p.hostname != "graph.microsoft.com":
            logger.error("Graph GET rejected: non-Graph URL (%s)", log_url)
            return None
        token = self._acquire_token()
        if not token:
            return None
        try:
            headers = dict(extra_headers) if extra_headers else {}
            # Auth set LAST — caller-supplied headers can never strip the bearer.
            headers["Authorization"] = f"Bearer {token}"
            resp = requests.get(
                url,
                headers=headers,
                # Pass-through unchanged (None for get_url opaque delta URLs).
                params=params,
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            # log_url is redacted for get_url; never echo the bearer.
            if redact_url:
                logger.error("Graph GET %s failed: %s", log_url, type(e).__name__)
                return None
            # Non-redacted (v1.0-relative) path: surface the actual cause —
            # HTTP status, the EXACT final URL requests built, and Graph's error
            # body (its error JSON, e.g. {"error":{"code":...}}). No secrets here.
            resp_obj = getattr(e, "response", None)
            status = getattr(resp_obj, "status_code", None)
            final_url = getattr(resp_obj, "url", None)
            body = None
            if resp_obj is not None:
                try:
                    body = resp_obj.text[:1000]
                except Exception:
                    body = None
            logger.error(
                "Graph GET %s failed: %s status=%s url=%s body=%s",
                log_url, type(e).__name__, status, final_url, body,
            )
            return None

    def get(
        self,
        path: str,
        params: dict | None = None,
        timeout: int = 8,
        extra_headers: dict | None = None,
    ) -> dict | None:
        """GET a v1.0-relative path (e.g. '/me/messages'). Never raises.

        extra_headers forwards non-auth request headers (see ``_request``).
        """
        return self._request(
            f"{self.cfg.base_url}{path}",
            params,
            timeout,
            log_url=path,
            extra_headers=extra_headers,
            redact_url=False,
        )

    @staticmethod
    def _retry_after_seconds(resp_obj, attempt: int, base_delay: float, cap: float = 60.0) -> float:
        """Backoff for a 429/503: honor the Retry-After header if present
        (seconds form), else exponential ``base_delay * 2**attempt``, capped."""
        if resp_obj is not None:
            ra = resp_obj.headers.get("Retry-After") if getattr(resp_obj, "headers", None) else None
            if ra:
                try:
                    return min(float(int(ra)), cap)
                except (TypeError, ValueError):
                    pass
        return min(base_delay * (2 ** attempt), cap)

    def get_bytes(
        self,
        path: str,
        timeout: int = 30,
        extra_headers: dict | None = None,
        max_retries: int = 0,
        base_delay: float = 1.0,
    ) -> tuple[bytes, str | None] | None:
        """GET a v1.0-relative path expecting RAW BYTES (not JSON). Never raises.

        For ``/messages/{id}/attachments/{id}/$value`` — returns the attachment's
        raw bytes (fileAttachment file bytes; rfc822 itemAttachment .eml MIME).
        Returns ``(content_bytes, content_type)`` on 2xx, or ``None`` on any
        non-retryable failure (e.g. referenceAttachment $value 405 — caller
        leaves the row metadata_only). No base64 inflation: ``resp.content`` is
        the exact bytes.

        ``max_retries`` (>0, used by the backfill) retries 429/503 ONLY, with
        exponential backoff that honors the ``Retry-After`` header. Forward ingest
        passes 0 (a transient 429 records metadata_only and the backfill recovers
        it later — a poll cycle must not block on backoff).

        Same host-pin + bearer discipline as ``_request``; a longer default
        timeout (large PDFs). HTTP status + final URL + Graph error body are
        logged on failure (no secrets) so a skip is diagnosable, never silent.
        """
        url = f"{self.cfg.base_url}{path}"
        # Host-pin BEFORE acquiring a token (latent credential-leak guard).
        p = urlparse(url)
        if p.scheme != "https" or p.hostname != "graph.microsoft.com":
            logger.error("Graph GET(bytes) rejected: non-Graph URL (%s)", path)
            return None
        token = self._acquire_token()
        if not token:
            return None
        headers = dict(extra_headers) if extra_headers else {}
        headers["Authorization"] = f"Bearer {token}"
        attempt = 0
        while True:
            try:
                # requests strips Authorization on cross-host redirects (Graph
                # $value may 302 to pre-authed blob storage) — safe by default.
                resp = requests.get(url, headers=headers, timeout=timeout)
                resp.raise_for_status()
                return resp.content, resp.headers.get("Content-Type")
            except Exception as e:
                resp_obj = getattr(e, "response", None)
                status = getattr(resp_obj, "status_code", None)
                if status in (429, 503) and attempt < max_retries:
                    delay = self._retry_after_seconds(resp_obj, attempt, base_delay)
                    logger.warning(
                        "Graph GET(bytes) %s -> %s; backoff %.1fs (attempt %d/%d)",
                        path, status, delay, attempt + 1, max_retries,
                    )
                    time.sleep(delay)
                    attempt += 1
                    continue
                final_url = getattr(resp_obj, "url", None)
                body = None
                if resp_obj is not None:
                    try:
                        body = resp_obj.text[:500]
                    except Exception:
                        body = None
                logger.error(
                    "Graph GET(bytes) %s failed: %s status=%s url=%s body=%s",
                    path, type(e).__name__, status, final_url, body,
                )
                return None

    def get_url(self, url: str, timeout: int = 8) -> dict | None:
        """GET an opaque absolute Graph URL (Phase-2 @odata.nextLink / deltaLink).

        finding 3: the query string is preserved by passing params=None, and the
        full URL is NEVER logged (delta tokens are sensitive) — only a redacted
        marker reaches the log. Never raises.
        """
        return self._request(url, None, timeout, log_url="<delta/next-link redacted>")

    def health(self) -> dict:
        """Shape for a future /api/graph_health probe (endpoint NOT added this phase)."""
        token_ok = bool(self._acquire_token()) if self.is_ready() else False
        return {
            "enabled": self.is_enabled(),
            "configured": self.is_configured(),
            "token_acquired": token_ok,
            "error": None,
        }
