"""Fault-tolerant Cloudflare R2 object-storage helpers.

The module is safe to import when boto3 or R2 env vars are absent. Callers get
structured ``{"ok": False, "error": ...}`` results instead of exceptions.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_REQUIRED_ENV = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
)
_OPTIONAL_ENDPOINT_ENV = "R2_ENDPOINT"
_MAX_PRESIGN_SECONDS = 300
_MAX_SINGLE_OBJECT_BYTES = 5 * 1024 * 1024 * 1024


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def missing_config() -> list[str]:
    """Return missing required config names. Values are never returned."""
    return [name for name in _REQUIRED_ENV if not _env(name)]


def _endpoint_url() -> str:
    explicit = _env(_OPTIONAL_ENDPOINT_ENV)
    if explicit:
        return explicit.rstrip("/")
    return f"https://{_env('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com"


def storage_enabled() -> bool:
    """True when enough env config exists to attempt R2 operations."""
    return not missing_config()


def _error(code: str, *, detail: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": code}
    if detail:
        out["detail"] = detail
    return out


def _clamp_expires(expires: int) -> int:
    try:
        n = int(expires)
    except (TypeError, ValueError):
        n = _MAX_PRESIGN_SECONDS
    return max(1, min(n, _MAX_PRESIGN_SECONDS))


def _validate_key(key: str) -> str:
    key = (key or "").strip()
    parts = [p for p in key.split("/") if p]
    if (
        not key
        or len(key) > 1024
        or key.startswith("/")
        or "\\" in key
        or "\n" in key
        or "\r" in key
        or any(p in (".", "..") for p in parts)
    ):
        raise ValueError("invalid_key")
    return key


def _validate_content_type(content_type: str) -> str:
    content_type = (content_type or "").strip()
    if (
        not content_type
        or "/" not in content_type
        or "\n" in content_type
        or "\r" in content_type
    ):
        raise ValueError("invalid_content_type")
    return content_type


def _load_boto3():
    import boto3

    return boto3


def _load_config_class():
    from botocore.config import Config

    return Config


def _client():
    boto3 = _load_boto3()
    Config = _load_config_class()
    return boto3.client(
        "s3",
        endpoint_url=_endpoint_url(),
        aws_access_key_id=_env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            connect_timeout=2,
            read_timeout=3,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def storage_health(*, probe: bool = True) -> dict[str, Any]:
    """Return ``{"status": ok|disabled|error}`` without exposing secrets."""
    missing = missing_config()
    if missing:
        return {"status": "disabled", "missing": missing}
    try:
        client = _client()
        if probe:
            client.head_bucket(Bucket=_env("R2_BUCKET"))
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 - health must degrade, never raise.
        logger.warning("object_storage health check failed: %s", type(exc).__name__)
        return {"status": "error", "error": type(exc).__name__}


def put_object(key: str, data: bytes | bytearray | memoryview, content_type: str) -> dict[str, Any]:
    """Upload bytes server-side. Returns structured error on any failure."""
    if not storage_enabled():
        return _error("disabled", detail="R2 config missing")
    try:
        key = _validate_key(key)
        content_type = _validate_content_type(content_type)
        if isinstance(data, str):
            raise ValueError("data_must_be_bytes")
        body = bytes(data)
        if len(body) > _MAX_SINGLE_OBJECT_BYTES:
            raise ValueError("object_too_large")
        _client().put_object(
            Bucket=_env("R2_BUCKET"),
            Key=key,
            Body=body,
            ContentType=content_type,
        )
        return {"ok": True, "key": key, "size_bytes": len(body)}
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("object_storage put_object failed: %s", type(exc).__name__)
        return _error("put_failed", detail=type(exc).__name__)


def get_object(key: str) -> dict[str, Any]:
    """Download an object's bytes server-side. Structured error on any failure.

    Returns ``{"ok": True, "data": bytes, "content_type": str, "size_bytes": int}``
    on success, or ``{"ok": False, "error": ...}``. Used by the attachment read
    path to resolve ``storage='r2'`` rows (whose bytes are NOT in Neon) so text
    extraction can run on the real payload. Fault-tolerant: never raises.
    """
    if not storage_enabled():
        return _error("disabled", detail="R2 config missing")
    try:
        key = _validate_key(key)
        resp = _client().get_object(Bucket=_env("R2_BUCKET"), Key=key)
        body = resp["Body"].read()
        return {
            "ok": True,
            "data": body,
            "content_type": resp.get("ContentType"),
            "size_bytes": len(body),
            "key": key,
        }
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("object_storage get_object failed: %s", type(exc).__name__)
        return _error("get_failed", detail=type(exc).__name__)


def generate_presigned_put(
    key: str,
    content_type: str,
    max_bytes: int,
    expires: int = _MAX_PRESIGN_SECONDS,
) -> dict[str, Any]:
    """Generate a direct-browser PUT grant with signed type/length headers.

    Cloudflare R2 supports presigned PUT URLs, not presigned POST form uploads.
    For V1, ``max_bytes`` is the exact byte length the browser must send; callers
    should pass ``File.size`` after enforcing their own upper cap. The signed
    Content-Type and Content-Length headers make tampering fail signature checks.
    """
    if not storage_enabled():
        return _error("disabled", detail="R2 config missing")
    try:
        key = _validate_key(key)
        content_type = _validate_content_type(content_type)
        max_bytes = int(max_bytes)
        if max_bytes <= 0 or max_bytes > _MAX_SINGLE_OBJECT_BYTES:
            raise ValueError("invalid_max_bytes")
        expires = _clamp_expires(expires)
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(max_bytes),
        }
        url = _client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": _env("R2_BUCKET"),
                "Key": key,
                "ContentType": content_type,
                "ContentLength": max_bytes,
            },
            ExpiresIn=expires,
            HttpMethod="PUT",
        )
        return {
            "ok": True,
            "method": "PUT",
            "url": url,
            "headers": headers,
            "key": key,
            "content_type": content_type,
            "max_bytes": max_bytes,
            "expires": expires,
        }
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("object_storage presigned upload failed: %s", type(exc).__name__)
        return _error("presign_put_failed", detail=type(exc).__name__)


def generate_presigned_get(key: str, expires: int = _MAX_PRESIGN_SECONDS) -> dict[str, Any]:
    """Generate a short-lived direct read URL."""
    if not storage_enabled():
        return _error("disabled", detail="R2 config missing")
    try:
        key = _validate_key(key)
        expires = _clamp_expires(expires)
        url = _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": _env("R2_BUCKET"), "Key": key},
            ExpiresIn=expires,
        )
        return {"ok": True, "url": url, "key": key, "expires": expires}
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("object_storage presigned get failed: %s", type(exc).__name__)
        return _error("presign_get_failed", detail=type(exc).__name__)


def delete_object(key: str) -> dict[str, Any]:
    """Delete an object. Missing objects are treated as successful S3 deletes."""
    if not storage_enabled():
        return _error("disabled", detail="R2 config missing")
    try:
        key = _validate_key(key)
        _client().delete_object(Bucket=_env("R2_BUCKET"), Key=key)
        return {"ok": True, "key": key}
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("object_storage delete failed: %s", type(exc).__name__)
        return _error("delete_failed", detail=type(exc).__name__)
