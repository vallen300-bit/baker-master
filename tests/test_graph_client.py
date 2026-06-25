"""M365_GRAPH_CLIENT_FOUNDATION_1: unit tests for the dormant Microsoft Graph client.

No network. MSAL + requests are mocked. Covers the 9 Test-AC cases in the brief:
flag-gating, no-forever-cache, opaque delta-URL pass-through, secret scrubbing,
never-raise contract, and health() shapes.
"""
import logging
from unittest import mock

import pytest

from config.settings import GraphConfig
from kbl.graph_client import GraphClient

# Recognizable sentinels — asserted to NEVER appear in logs.
SECRET = "SUPER_SECRET_VALUE_123"
TOKEN = "ACCESS_TOKEN_VALUE_XYZ"
CERT_KEY = "-----BEGIN PRIVATE KEY-----\nPRIVATE_KEY_PEM_BODY_456\n-----END PRIVATE KEY-----"
THUMBPRINT = "ABCDEF0123456789THUMBPRINT"

MSAL_PATH = "kbl.graph_client.ConfidentialClientApplication"
REQUESTS_PATH = "kbl.graph_client.requests"


def _ready_cfg(**over) -> GraphConfig:
    """A fully-configured, flag-ON config (creds + BAKER_USE_GRAPH=true)."""
    base = dict(
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret=SECRET,
        enabled=True,
    )
    base.update(over)
    return GraphConfig(**base)


def _cert_cfg(**over) -> GraphConfig:
    """A cert-authed, flag-ON config (no client_secret)."""
    base = dict(
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="",
        cert_private_key=CERT_KEY,
        cert_thumbprint=THUMBPRINT,
        enabled=True,
    )
    base.update(over)
    return GraphConfig(**base)


def _ok_response(payload=None):
    """A mock requests.Response that succeeds and returns JSON."""
    resp = mock.MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload if payload is not None else {"value": []}
    return resp


# ---------------------------------------------------------------------------
# 1. is_configured() / is_enabled() gating
# ---------------------------------------------------------------------------
def test_is_configured_all_set():
    assert GraphClient(_ready_cfg()).is_configured() is True


@pytest.mark.parametrize("missing", ["tenant_id", "client_id", "client_secret"])
def test_is_configured_missing_one(missing):
    cfg = _ready_cfg(**{missing: ""})
    assert GraphClient(cfg).is_configured() is False


def test_is_enabled_reflects_flag():
    assert GraphClient(_ready_cfg(enabled=True)).is_enabled() is True
    assert GraphClient(_ready_cfg(enabled=False)).is_enabled() is False


def test_is_ready_requires_both():
    assert GraphClient(_ready_cfg()).is_ready() is True
    assert GraphClient(_ready_cfg(enabled=False)).is_ready() is False
    assert GraphClient(_ready_cfg(client_secret="")).is_ready() is False


def test_default_config_reads_env_after_construction(monkeypatch):
    for name in (
        "M365_TENANT_ID",
        "M365_CLIENT_ID",
        "M365_CLIENT_SECRET",
        "M365_CERT_PRIVATE_KEY",
        "M365_CERT_PATH",
        "M365_CERT_THUMBPRINT",
        "BAKER_USE_GRAPH",
        "M365_MAIL_USER",
    ):
        monkeypatch.delenv(name, raising=False)

    cfg = GraphConfig()
    client = GraphClient(cfg)
    assert client.is_ready() is False
    assert cfg.mail_user == "dvallen@brisengroup.com"

    monkeypatch.setenv("M365_TENANT_ID", "tenant-env")
    monkeypatch.setenv("M365_CLIENT_ID", "client-env")
    monkeypatch.setenv("M365_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("BAKER_USE_GRAPH", "true")
    monkeypatch.setenv("M365_MAIL_USER", "graph@example.com")

    assert cfg.tenant_id == "tenant-env"
    assert cfg.client_id == "client-env"
    assert cfg.client_secret == SECRET
    assert cfg.mail_user == "graph@example.com"
    assert client.is_enabled() is True
    assert client.is_configured() is True
    assert client.is_ready() is True


def test_acquire_token_uses_env_changed_after_construction(monkeypatch):
    for name in (
        "M365_TENANT_ID",
        "M365_CLIENT_ID",
        "M365_CLIENT_SECRET",
        "M365_CERT_PRIVATE_KEY",
        "M365_CERT_PATH",
        "M365_CERT_THUMBPRINT",
        "BAKER_USE_GRAPH",
    ):
        monkeypatch.delenv(name, raising=False)

    client = GraphClient(GraphConfig())
    monkeypatch.setenv("M365_TENANT_ID", "tenant-env")
    monkeypatch.setenv("M365_CLIENT_ID", "client-env")
    monkeypatch.setenv("M365_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("BAKER_USE_GRAPH", "true")

    with mock.patch(MSAL_PATH) as m_msal:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        assert client._acquire_token() == TOKEN
        args, kwargs = m_msal.call_args
        assert args[0] == "client-env"
        assert kwargs["authority"] == "https://login.microsoftonline.com/tenant-env"
        assert kwargs["client_credential"] == SECRET


def test_acquire_token_rebuilds_msal_when_env_credentials_change(monkeypatch):
    for name in (
        "M365_TENANT_ID",
        "M365_CLIENT_ID",
        "M365_CLIENT_SECRET",
        "M365_CERT_PRIVATE_KEY",
        "M365_CERT_PATH",
        "M365_CERT_THUMBPRINT",
        "BAKER_USE_GRAPH",
    ):
        monkeypatch.delenv(name, raising=False)

    client = GraphClient(GraphConfig())
    monkeypatch.setenv("M365_TENANT_ID", "tenant-1")
    monkeypatch.setenv("M365_CLIENT_ID", "client-1")
    monkeypatch.setenv("M365_CLIENT_SECRET", "secret-1")
    monkeypatch.setenv("BAKER_USE_GRAPH", "true")

    with mock.patch(MSAL_PATH) as m_msal:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        assert client._acquire_token() == TOKEN

        monkeypatch.setenv("M365_TENANT_ID", "tenant-2")
        monkeypatch.setenv("M365_CLIENT_ID", "client-2")
        monkeypatch.setenv("M365_CLIENT_SECRET", "secret-2")
        assert client.cfg.tenant_id == "tenant-2"
        assert client.cfg.client_id == "client-2"
        assert client.cfg.client_secret == "secret-2"
        assert client._acquire_token() == TOKEN

        assert m_msal.call_count == 2
        first_args, first_kwargs = m_msal.call_args_list[0]
        second_args, second_kwargs = m_msal.call_args_list[1]
        assert first_args[0] == "client-1"
        assert first_kwargs["authority"] == "https://login.microsoftonline.com/tenant-1"
        assert first_kwargs["client_credential"] == "secret-1"
        assert second_args[0] == "client-2"
        assert second_kwargs["authority"] == "https://login.microsoftonline.com/tenant-2"
        assert second_kwargs["client_credential"] == "secret-2"


def test_constructor_values_override_later_env_changes(monkeypatch):
    cfg = GraphConfig(
        tenant_id="",
        client_id="fixed-client",
        client_secret="",
        enabled=False,
        mail_user="fixed@example.com",
    )
    monkeypatch.setenv("M365_TENANT_ID", "tenant-env")
    monkeypatch.setenv("M365_CLIENT_ID", "client-env")
    monkeypatch.setenv("M365_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("BAKER_USE_GRAPH", "true")
    monkeypatch.setenv("M365_MAIL_USER", "graph@example.com")

    assert cfg.tenant_id == ""
    assert cfg.client_id == "fixed-client"
    assert cfg.client_secret == ""
    assert cfg.enabled is False
    assert cfg.mail_user == "fixed@example.com"
    assert GraphClient(cfg).is_ready() is False


# ---------------------------------------------------------------------------
# 2. Flag enforcement (finding 1): creds present + flag OFF ⇒ no MSAL, no HTTP
# ---------------------------------------------------------------------------
def test_flag_off_no_token_no_msal_no_http():
    cfg = _ready_cfg(enabled=False)  # creds fully present, flag off
    client = GraphClient(cfg)
    assert client.is_configured() is True
    assert client.is_ready() is False

    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        assert client._acquire_token() is None
        assert client.get("/me/messages") is None
        assert client.get_url("https://graph.microsoft.com/v1.0/me/messages?$skiptoken=abc") is None

        assert m_msal.called is False
        assert m_requests.get.called is False


# ---------------------------------------------------------------------------
# 3. _acquire_token success
# ---------------------------------------------------------------------------
def test_acquire_token_success():
    client = GraphClient(_ready_cfg())
    with mock.patch(MSAL_PATH) as m_msal:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        assert client._acquire_token() == TOKEN
        m_msal.assert_called_once()


# ---------------------------------------------------------------------------
# 4. _acquire_token failure → None, no raise
# ---------------------------------------------------------------------------
def test_acquire_token_failure_returns_none():
    client = GraphClient(_ready_cfg())
    with mock.patch(MSAL_PATH) as m_msal:
        m_msal.return_value.acquire_token_for_client.return_value = {"error": "invalid_client"}
        assert client._acquire_token() is None  # no raise


def test_acquire_token_exception_returns_none():
    client = GraphClient(_ready_cfg())
    with mock.patch(MSAL_PATH) as m_msal:
        m_msal.return_value.acquire_token_for_client.side_effect = RuntimeError("boom")
        assert client._acquire_token() is None  # never raises


# ---------------------------------------------------------------------------
# 5. No forever-cache (finding 2): no raw bearer on the instance; MSAL owns caching
# ---------------------------------------------------------------------------
def test_no_raw_bearer_cached_on_instance():
    client = GraphClient(_ready_cfg())
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        m_requests.get.return_value = _ok_response()

        client.get("/me/messages")
        client.get("/me/messages")

        # MSAL is consulted on every call — the client never short-circuits on a
        # stale instance bearer.
        assert m_msal.return_value.acquire_token_for_client.call_count == 2
        # No attribute holds the raw token.
        assert "_token" not in client.__dict__
        assert not any(getattr(v, "__class__", None) is str and v == TOKEN
                       for v in client.__dict__.values())


# ---------------------------------------------------------------------------
# 6. get() success and failure
# ---------------------------------------------------------------------------
def test_get_success_returns_dict():
    client = GraphClient(_ready_cfg())
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        m_requests.get.return_value = _ok_response({"value": [{"id": "1"}]})

        out = client.get("/me/messages")
        assert out == {"value": [{"id": "1"}]}
        called_url = m_requests.get.call_args[0][0]
        assert called_url == "https://graph.microsoft.com/v1.0/me/messages"


def test_get_failure_returns_none_no_raise():
    client = GraphClient(_ready_cfg())
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        m_requests.get.side_effect = TimeoutError("timed out")
        assert client.get("/me/messages") is None  # never raises


def _err_response(status=400, body='{"error":{"code":"ErrorX"}}', url="https://graph.microsoft.com/v1.0/x"):
    """A mock Response whose raise_for_status() raises a real HTTPError w/ .response."""
    import requests as _rq

    resp = mock.MagicMock()
    resp.status_code = status
    resp.text = body
    resp.url = url
    err = _rq.exceptions.HTTPError("boom")
    err.response = resp
    resp.raise_for_status.side_effect = err
    return resp


# M365_GRAPH_ATTACHMENT diagnosis: get() (v1.0-relative, non-redacted) failures
# must surface the HTTP status + final URL + Graph error body — the bare exception
# class name swallowed the smoking gun. Message ids are not secrets; the bearer
# lives in request headers, never the response body.
def test_get_failure_logs_status_url_and_body(caplog):
    client = GraphClient(_ready_cfg())
    att_url = "https://graph.microsoft.com/v1.0/users/svc%40x.com/messages/AAMkID%3D%3D/attachments"
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        m_requests.get.return_value = _err_response(
            status=400, body='{"error":{"code":"ErrorInvalidIdMalformed"}}', url=att_url
        )
        with caplog.at_level(logging.ERROR):
            assert client.get("/users/svc%40x.com/messages/AAMkID%3D%3D/attachments") is None
    assert "status=400" in caplog.text
    assert "ErrorInvalidIdMalformed" in caplog.text
    assert att_url in caplog.text
    assert TOKEN not in caplog.text


# get_url() (delta/next links) stays redacted even when the HTTP error carries a
# response body/url — never leak the delta token via status-body logging.
def test_get_url_failure_redacts_even_with_response_body(caplog):
    client = GraphClient(_ready_cfg())
    delta_url = "https://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=SENSITIVE_DELTA_abc123"
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        m_requests.get.return_value = _err_response(
            status=400, body="SENSITIVE_DELTA_abc123 in body", url=delta_url
        )
        with caplog.at_level(logging.ERROR):
            assert client.get_url(delta_url) is None
    assert "redacted" in caplog.text
    assert "SENSITIVE_DELTA_abc123" not in caplog.text
    assert delta_url not in caplog.text


# M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1: get(extra_headers=...) merges non-auth
# headers (e.g. Prefer: IdType="ImmutableId") on top of the bearer, and the
# bearer is set LAST so a caller can never strip or override it.
def test_get_extra_headers_merge_without_clobbering_bearer():
    client = GraphClient(_ready_cfg())
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        m_requests.get.return_value = _ok_response({"value": []})

        # Caller even tries to override Authorization — must NOT win.
        client.get(
            "/me/messages",
            extra_headers={"Prefer": 'IdType="ImmutableId"', "Authorization": "Bearer EVIL"},
        )
        sent = m_requests.get.call_args.kwargs["headers"]
        assert sent["Prefer"] == 'IdType="ImmutableId"'
        assert sent["Authorization"] == f"Bearer {TOKEN}"   # bearer preserved, EVIL ignored


def test_get_without_extra_headers_sends_only_bearer():
    client = GraphClient(_ready_cfg())
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        m_requests.get.return_value = _ok_response({"value": []})
        client.get("/me/messages")
        sent = m_requests.get.call_args.kwargs["headers"]
        assert sent == {"Authorization": f"Bearer {TOKEN}"}


# ---------------------------------------------------------------------------
# 7. get_url() (finding 3): opaque URL passed unchanged; never logged
# ---------------------------------------------------------------------------
def test_get_url_passes_opaque_url_unchanged():
    client = GraphClient(_ready_cfg())
    delta_url = "https://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=SENSITIVE_DELTA_abc123"
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        m_requests.get.return_value = _ok_response()

        client.get_url(delta_url)

        # Exact URL passed through; params explicitly None (query preserved in URL).
        args, kwargs = m_requests.get.call_args
        assert args[0] == delta_url
        assert kwargs["params"] is None


def test_get_url_failure_logs_redacted_marker_not_url(caplog):
    client = GraphClient(_ready_cfg())
    delta_url = "https://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=SENSITIVE_DELTA_abc123"
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        m_requests.get.side_effect = TimeoutError("timed out")

        with caplog.at_level(logging.DEBUG):
            assert client.get_url(delta_url) is None

        assert "redacted" in caplog.text
        assert "SENSITIVE_DELTA_abc123" not in caplog.text
        assert delta_url not in caplog.text


# ---------------------------------------------------------------------------
# 8. Secret-scrub: neither client_secret nor access_token reach logs
# ---------------------------------------------------------------------------
def test_secret_and_token_never_logged_success_path(caplog):
    client = GraphClient(_ready_cfg())
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        m_requests.get.return_value = _ok_response()
        with caplog.at_level(logging.DEBUG):
            client.get("/me/messages")
            client.health()
    assert SECRET not in caplog.text
    assert TOKEN not in caplog.text


def test_secret_and_token_never_logged_failure_path(caplog):
    client = GraphClient(_ready_cfg())
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        # token acquisition fails, then a request also fails
        m_msal.return_value.acquire_token_for_client.return_value = {"error": "invalid_client"}
        m_requests.get.side_effect = TimeoutError("timed out")
        with caplog.at_level(logging.DEBUG):
            client._acquire_token()
            client.get("/me/messages")
            client.get_url("https://graph.microsoft.com/v1.0/x?$deltatoken=zzz")
    assert SECRET not in caplog.text
    assert TOKEN not in caplog.text


# ---------------------------------------------------------------------------
# 9. health() shapes
# ---------------------------------------------------------------------------
def test_health_unconfigured():
    client = GraphClient(_ready_cfg(tenant_id="", client_id="", client_secret="", enabled=True))
    h = client.health()
    assert h == {"enabled": True, "configured": False, "token_acquired": False, "error": None}


def test_health_configured_but_flag_off():
    client = GraphClient(_ready_cfg(enabled=False))
    with mock.patch(MSAL_PATH) as m_msal:
        h = client.health()
        assert h == {"enabled": False, "configured": True, "token_acquired": False, "error": None}
        assert m_msal.called is False  # flag off ⇒ no MSAL construction


def test_health_ready_but_token_fail():
    client = GraphClient(_ready_cfg())
    with mock.patch(MSAL_PATH) as m_msal:
        m_msal.return_value.acquire_token_for_client.return_value = {"error": "invalid_client"}
        h = client.health()
        assert h == {"enabled": True, "configured": True, "token_acquired": False, "error": None}


def test_health_ready_token_ok():
    client = GraphClient(_ready_cfg())
    with mock.patch(MSAL_PATH) as m_msal:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        h = client.health()
        assert h == {"enabled": True, "configured": True, "token_acquired": True, "error": None}


# ---------------------------------------------------------------------------
# Build AC: import-safe + inert with no env set
# ---------------------------------------------------------------------------
def test_default_client_inert_without_env(monkeypatch):
    # A GraphConfig with empty creds + default flag must be unconfigured and not ready.
    cfg = GraphConfig(tenant_id="", client_id="", client_secret="", enabled=False)
    client = GraphClient(cfg)
    assert client.is_configured() is False
    assert client.is_ready() is False
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        assert client.get("/me") is None
        assert m_msal.called is False
        assert m_requests.get.called is False


# ---------------------------------------------------------------------------
# 10. Certificate auth (M365_GRAPH_CERT_AUTH_1 Fix 1)
# ---------------------------------------------------------------------------
def test_cert_configured_without_secret():
    # AC1/AC3: cert (inline PEM + thumbprint) is a usable credential; no secret needed.
    assert GraphClient(_cert_cfg()).is_configured() is True


def test_cert_path_configured_without_inline_key():
    cfg = _cert_cfg(cert_private_key="", cert_path="/etc/secrets/graph.pem")
    assert GraphClient(cfg).is_configured() is True


def test_cert_missing_thumbprint_not_configured():
    # Cert material without a thumbprint is not a usable credential.
    cfg = _cert_cfg(cert_thumbprint="")
    assert GraphClient(cfg).is_configured() is False


def test_neither_secret_nor_cert_not_configured():
    # AC3: no secret + no cert ⇒ unconfigured, dormant.
    cfg = _ready_cfg(client_secret="")
    assert GraphClient(cfg).is_configured() is False
    assert GraphClient(cfg).is_ready() is False


def test_acquire_token_builds_msal_with_cert_dict():
    # AC1: MSAL constructed with the cert credential dict (mock MSAL, no network).
    client = GraphClient(_cert_cfg())
    with mock.patch(MSAL_PATH) as m_msal:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        assert client._acquire_token() == TOKEN
        _, kwargs = m_msal.call_args
        assert kwargs["client_credential"] == {
            "private_key": CERT_KEY,
            "thumbprint": THUMBPRINT,
        }


def test_acquire_token_cert_path_read_from_file(tmp_path):
    pem = tmp_path / "graph.pem"
    pem.write_text(CERT_KEY)
    client = GraphClient(_cert_cfg(cert_private_key="", cert_path=str(pem)))
    with mock.patch(MSAL_PATH) as m_msal:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        assert client._acquire_token() == TOKEN
        _, kwargs = m_msal.call_args
        assert kwargs["client_credential"]["private_key"] == CERT_KEY
        assert kwargs["client_credential"]["thumbprint"] == THUMBPRINT


def test_cert_takes_precedence_over_secret_when_both_set():
    # Cert precedence: both present ⇒ MSAL gets the cert dict, not the secret string.
    client = GraphClient(_cert_cfg(client_secret=SECRET))
    with mock.patch(MSAL_PATH) as m_msal:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        client._acquire_token()
        _, kwargs = m_msal.call_args
        assert isinstance(kwargs["client_credential"], dict)
        assert kwargs["client_credential"]["thumbprint"] == THUMBPRINT


def test_secret_only_still_builds_with_string_credential():
    # AC2: back-compat — secret-only config still authenticates with the raw secret.
    client = GraphClient(_ready_cfg())
    with mock.patch(MSAL_PATH) as m_msal:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        client._acquire_token()
        _, kwargs = m_msal.call_args
        assert kwargs["client_credential"] == SECRET


def test_cert_material_never_logged(caplog):
    # AC7: private_key + thumbprint never reach logs, success or failure path.
    client = GraphClient(_cert_cfg())
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        m_msal.return_value.acquire_token_for_client.return_value = {"error": "invalid_client"}
        m_requests.get.side_effect = TimeoutError("timed out")
        with caplog.at_level(logging.DEBUG):
            client._acquire_token()
            client.get("/me/messages")
    assert "PRIVATE_KEY_PEM_BODY_456" not in caplog.text
    assert THUMBPRINT not in caplog.text
    assert TOKEN not in caplog.text


# ---------------------------------------------------------------------------
# 11. Host-pin the bearer (M365_GRAPH_CERT_AUTH_1 Fix 2)
# ---------------------------------------------------------------------------
def test_get_url_non_https_rejected_before_token(caplog):
    # AC4: http:// URL ⇒ None; MSAL NOT called; requests.get NOT called; URL not logged.
    client = GraphClient(_ready_cfg())
    bad_url = "http://graph.microsoft.com/v1.0/me/messages"
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        with caplog.at_level(logging.DEBUG):
            assert client.get_url(bad_url) is None
        assert m_msal.called is False
        assert m_requests.get.called is False
        assert bad_url not in caplog.text


def test_get_url_non_graph_host_rejected_before_token(caplog):
    # AC5: foreign host ⇒ None; no MSAL; no requests.get; URL not logged (no token leak).
    client = GraphClient(_ready_cfg())
    evil_url = "https://evil.example/v1.0/me/messages?$deltatoken=STEAL_ME"
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        with caplog.at_level(logging.DEBUG):
            assert client.get_url(evil_url) is None
        assert m_msal.called is False
        assert m_requests.get.called is False
        assert "evil.example" not in caplog.text
        assert "STEAL_ME" not in caplog.text


def test_get_url_valid_graph_host_passes_through():
    # AC6: a valid graph.microsoft.com delta URL still passes the guard and is fetched.
    client = GraphClient(_ready_cfg())
    delta_url = "https://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=abc"
    with mock.patch(MSAL_PATH) as m_msal, mock.patch(REQUESTS_PATH) as m_requests:
        m_msal.return_value.acquire_token_for_client.return_value = {"access_token": TOKEN}
        m_requests.get.return_value = _ok_response()
        assert client.get_url(delta_url) == {"value": []}
        assert m_requests.get.call_args[0][0] == delta_url
