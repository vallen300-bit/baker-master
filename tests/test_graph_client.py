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
