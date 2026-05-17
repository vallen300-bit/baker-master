"""Tests for tools/render_env_guard.py — anchor 2026-05-17 env-var wipe."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tools.render_env_guard import (
    RENDER_API_BASE,
    RenderEnvGuardError,
    forbid_array_put,
    safe_env_put,
)


def _mock_response(status_code: int = 200, json_body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {"ok": True}
    resp.text = ""
    return resp


def test_forbid_array_put_raises_on_list():
    with pytest.raises(RenderEnvGuardError) as exc_info:
        forbid_array_put([{"key": "A", "value": "1"}])
    assert "REPLACES" in str(exc_info.value)
    assert "2026-05-17" in str(exc_info.value)


def test_forbid_array_put_passes_on_dict():
    forbid_array_put({"value": "1"})


def test_forbid_array_put_passes_on_empty_dict():
    forbid_array_put({})


def test_safe_env_put_issues_merge_mode_url_and_body():
    with patch("tools.render_env_guard.httpx.put") as mock_put:
        mock_put.return_value = _mock_response(200, {"key": "FOO", "value": "bar"})
        result = safe_env_put("srv-abc", "FOO", "bar", render_key="test-key")
    assert result == {"key": "FOO", "value": "bar"}
    mock_put.assert_called_once()
    call = mock_put.call_args
    assert call.args[0] == f"{RENDER_API_BASE}/services/srv-abc/env-vars/FOO"
    assert call.kwargs["json"] == {"value": "bar"}
    assert call.kwargs["headers"]["Authorization"] == "Bearer test-key"


def test_safe_env_put_raises_on_4xx():
    with patch("tools.render_env_guard.httpx.put") as mock_put:
        resp = _mock_response(401)
        resp.text = "unauthorized"
        mock_put.return_value = resp
        with pytest.raises(RenderEnvGuardError) as exc_info:
            safe_env_put("srv-abc", "FOO", "bar", render_key="bad-key")
    assert "401" in str(exc_info.value)


def test_safe_env_put_raises_on_5xx():
    with patch("tools.render_env_guard.httpx.put") as mock_put:
        resp = _mock_response(503)
        resp.text = "service unavailable"
        mock_put.return_value = resp
        with pytest.raises(RenderEnvGuardError) as exc_info:
            safe_env_put("srv-abc", "FOO", "bar", render_key="ok-key")
    assert "503" in str(exc_info.value)


def test_safe_env_put_missing_api_key(monkeypatch):
    monkeypatch.delenv("RENDER_API_KEY", raising=False)
    with pytest.raises(RenderEnvGuardError) as exc_info:
        safe_env_put("srv-abc", "FOO", "bar")
    assert "RENDER_API_KEY" in str(exc_info.value)


def test_safe_env_put_picks_up_env_key(monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "env-key")
    with patch("tools.render_env_guard.httpx.put") as mock_put:
        mock_put.return_value = _mock_response(200)
        safe_env_put("srv-abc", "FOO", "bar")
    assert mock_put.call_args.kwargs["headers"]["Authorization"] == "Bearer env-key"


def test_safe_env_put_rejects_empty_service_id():
    with pytest.raises(RenderEnvGuardError):
        safe_env_put("", "FOO", "bar", render_key="k")


def test_safe_env_put_rejects_empty_key():
    with pytest.raises(RenderEnvGuardError):
        safe_env_put("srv-abc", "", "bar", render_key="k")
