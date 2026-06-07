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

    def _request(self, url: str, params: dict | None, timeout: int, log_url: str) -> dict | None:
        """Shared GET path. Never raises; never logs the token or full delta URL."""
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
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                # Pass-through unchanged (None for get_url opaque delta URLs).
                params=params,
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            # log_url is redacted for get_url; never echo the bearer.
            logger.error("Graph GET %s failed: %s", log_url, type(e).__name__)
            return None

    def get(self, path: str, params: dict | None = None, timeout: int = 8) -> dict | None:
        """GET a v1.0-relative path (e.g. '/me/messages'). Never raises."""
        return self._request(f"{self.cfg.base_url}{path}", params, timeout, log_url=path)

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
