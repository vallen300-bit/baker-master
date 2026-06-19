from __future__ import annotations

import uuid

import pytest

from kbl import object_storage as storage


_R2_ENV = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    "R2_ENDPOINT",
)


class _FakeConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeClient:
    def __init__(self):
        self.calls = []

    def head_bucket(self, **kwargs):
        self.calls.append(("head_bucket", kwargs))

    def put_object(self, **kwargs):
        self.calls.append(("put_object", kwargs))

    def generate_presigned_url(self, *args, **kwargs):
        self.calls.append(("generate_presigned_url", args, kwargs))
        return "https://example.invalid/signed"

    def delete_object(self, **kwargs):
        self.calls.append(("delete_object", kwargs))


class _FakeBoto3:
    def __init__(self, client):
        self.client_obj = client
        self.client_kwargs = None

    def client(self, *args, **kwargs):
        self.client_kwargs = {"args": args, "kwargs": kwargs}
        return self.client_obj


def _clear_r2_env(monkeypatch):
    for name in _R2_ENV:
        monkeypatch.delenv(name, raising=False)


def _set_r2_env(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-access")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret-never-return")
    monkeypatch.setenv("R2_BUCKET", "test-bucket")


def _patch_fake_client(monkeypatch):
    client = _FakeClient()
    fake_boto3 = _FakeBoto3(client)
    monkeypatch.setattr(storage, "_load_boto3", lambda: fake_boto3)
    monkeypatch.setattr(storage, "_load_config_class", lambda: _FakeConfig)
    return client, fake_boto3


def test_disabled_without_env_imports_and_degrades(monkeypatch):
    _clear_r2_env(monkeypatch)

    assert storage.storage_enabled() is False
    assert storage.storage_health() == {
        "status": "disabled",
        "missing": [
            "R2_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET",
        ],
    }
    assert storage.put_object("ai-hotel/test.txt", b"hi", "text/plain")["error"] == "disabled"
    assert storage.generate_presigned_get("ai-hotel/test.txt")["error"] == "disabled"
    assert storage.generate_presigned_put("ai-hotel/test.txt", "text/plain", 10)["error"] == "disabled"
    assert storage.delete_object("ai-hotel/test.txt")["error"] == "disabled"


def test_client_uses_r2_endpoint_region_auto_and_never_returns_secret(monkeypatch):
    _clear_r2_env(monkeypatch)
    _set_r2_env(monkeypatch)
    _, fake_boto3 = _patch_fake_client(monkeypatch)

    result = storage.put_object("ai-hotel/test.txt", b"hello", "text/plain")

    assert result == {"ok": True, "key": "ai-hotel/test.txt", "size_bytes": 5}
    kwargs = fake_boto3.client_kwargs["kwargs"]
    assert kwargs["endpoint_url"] == "https://test-account.r2.cloudflarestorage.com"
    assert kwargs["region_name"] == "auto"
    assert "test-secret-never-return" not in str(result)


def test_presigned_put_uses_signed_put_headers_for_size_and_content_type(monkeypatch):
    _clear_r2_env(monkeypatch)
    _set_r2_env(monkeypatch)
    client, _ = _patch_fake_client(monkeypatch)

    result = storage.generate_presigned_put(
        "ai-hotel/capture-1/video.webm",
        "video/webm",
        max_bytes=12345,
        expires=999,
    )

    assert result["ok"] is True
    assert result["method"] == "PUT"
    assert result["expires"] == 300
    assert result["headers"] == {
        "Content-Type": "video/webm",
        "Content-Length": "12345",
    }
    call = client.calls[-1]
    assert call[0] == "generate_presigned_url"
    args = call[1]
    kwargs = call[2]
    assert args == ("put_object",)
    assert kwargs["Params"]["ContentType"] == "video/webm"
    assert kwargs["Params"]["ContentLength"] == 12345
    assert kwargs["HttpMethod"] == "PUT"


def test_invalid_key_and_content_type_fail_structured(monkeypatch):
    _clear_r2_env(monkeypatch)
    _set_r2_env(monkeypatch)
    _patch_fake_client(monkeypatch)

    assert storage.generate_presigned_get("../secret")["error"] == "invalid_key"
    assert storage.generate_presigned_put("x", "bad", 10)["error"] == "invalid_content_type"
    assert storage.generate_presigned_put("x", "video/webm", 0)["error"] == "invalid_max_bytes"


def test_health_endpoint_exposes_disabled_status(monkeypatch):
    try:
        from fastapi.testclient import TestClient
        import outputs.dashboard as dash
    except Exception as exc:  # pragma: no cover - local py3.9 import guard.
        pytest.skip(f"outputs.dashboard unimportable: {exc}")

    _clear_r2_env(monkeypatch)
    resp = TestClient(dash.app).get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["object_storage"]["status"] == "disabled"


def test_live_r2_roundtrip_when_env_present(monkeypatch):
    if not storage.storage_enabled():
        pytest.skip("R2 env absent")

    key = f"ai-hotel/test/{uuid.uuid4().hex}.txt"
    try:
        put = storage.put_object(key, b"r2-roundtrip", "text/plain")
        assert put["ok"] is True, put
        got = storage.generate_presigned_get(key)
        assert got["ok"] is True, got

        import httpx

        resp = httpx.get(got["url"], timeout=10)
        assert resp.status_code == 200
        assert resp.content == b"r2-roundtrip"
    finally:
        storage.delete_object(key)
