"""Safe Render env-var writes — canonical Python path.

Anchor: 2026-05-17 catastrophic env-var wipe on baker-master
(srv-d6dgsbctgctc73f55730). A raw `PUT /v1/services/{id}/env-vars` with an
array body REPLACES the entire env-var set; this module forces the merge-mode
single-key path `PUT /v1/services/{id}/env-vars/{KEY}` that NEVER replaces.

Pointers:
- Rules entry: .claude/rules/python-backend.md
- Canonical pattern: baker-vault/_ops/agents/ai-head/LONGTERM.md "Render API gotchas"
- Brief: briefs/BRIEF_RENDER_ENV_WRITE_GUARD_1.md

Usage (Python):
    from tools.render_env_guard import safe_env_put
    safe_env_put("srv-...", "MY_VAR", "value")

Usage (CLI):
    python -m tools.render_env_guard srv-... MY_VAR value
"""
from __future__ import annotations

import os
import sys
from typing import Any

import httpx

RENDER_API_BASE = "https://api.render.com/v1"
DEFAULT_TIMEOUT_S = 30.0


class RenderEnvGuardError(Exception):
    pass


def forbid_array_put(payload: Any) -> None:
    if isinstance(payload, list):
        raise RenderEnvGuardError(
            "Use safe_env_put(service_id, KEY, value) — raw PUT /env-vars "
            "with array body REPLACES the entire env set. "
            "Anchor: 2026-05-17 wipe."
        )


def safe_env_put(
    service_id: str,
    key: str,
    value: str,
    render_key: str | None = None,
) -> dict:
    if not service_id or not key:
        raise RenderEnvGuardError("service_id and key are required")
    render_key = render_key or os.environ.get("RENDER_API_KEY")
    if not render_key:
        raise RenderEnvGuardError(
            "RENDER_API_KEY missing — set env or pass render_key="
        )
    url = f"{RENDER_API_BASE}/services/{service_id}/env-vars/{key}"
    body: dict[str, str] = {"value": value}
    forbid_array_put(body)
    try:
        resp = httpx.put(
            url,
            headers={
                "Authorization": f"Bearer {render_key}",
                "Accept": "application/json",
            },
            json=body,
            timeout=DEFAULT_TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        raise RenderEnvGuardError(f"Render API transport error: {exc}") from exc
    if resp.status_code >= 400:
        raise RenderEnvGuardError(
            f"Render API {resp.status_code}: {resp.text[:200]}"
        )
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}


def _main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write(
            "usage: python -m tools.render_env_guard <service_id> <key> <value>\n"
        )
        return 2
    service_id, key, value = argv
    result = safe_env_put(service_id, key, value)
    sys.stdout.write(f"OK: {key} upserted on {service_id}; response={result}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(_main(sys.argv[1:]))
    except RenderEnvGuardError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        sys.exit(1)
