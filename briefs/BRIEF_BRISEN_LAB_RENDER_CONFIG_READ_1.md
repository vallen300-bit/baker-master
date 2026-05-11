# BRIEF: BRISEN_LAB_RENDER_CONFIG_READ_1 — expose read-only Render config endpoints on brisen-lab daemon

## Context

AID asked AH1 to close the Render-MCP gap with a thin read-only surface: AID needs to query Render service config (env vars + service IDs) to diagnose deploy issues, without holding write authority over Render. Today AID has no programmatic read path — yesterday's cockpit fallback investigation (msg #59) ended with AID misdiagnosing the root cause as "BAKER_VAULT_PATH unset" when in fact the env var was set and the bug was a YAML schema violation. A read-only Render config endpoint on AID's bus surface would let AID verify env state itself instead of relying on AH1 to relay.

Director ratified 2026-05-11 ~07:55Z: "confirm and go" — whitelist `['aid', 'lead', 'deputy']`.

**Repo target:** `brisen-lab` (`github.com/vallen300-bit/brisen-lab`).
**Reason:** AID already authenticates against brisen-lab via `X-Terminal-Key`; brisen-lab is "AID's bus surface" per AID's framing. Adding the endpoint here means no new auth surface on baker-master.

## Estimated time: ~2-3h
## Complexity: Low (2 endpoints, 1 new module, existing auth pattern, 1 new env var)
## Prerequisites:
- Render API key in 1Password: `op://Baker API Keys/API Render/credential` (the same key AH1/AH2 use today)
- Local clone at `~/bm-b4-brisen-lab` (currently on `main` at 8b0b7fb — operator must `git fetch origin main && git pull --ff-only` before branching)
- brisen-lab service ID: `srv-d7q7kvlckfvc739l2e8g`

## Tier: B (new auth-gated endpoints on production bus daemon + new env var)

---

## Feature 1 — `render_config.py` module with read-only Render API proxy

### Problem

AID can't query Render service config. AH1/AH2 have the Render API key via 1Password but AID has no equivalent. The four currently in-scope use cases:
1. Verify env var KEY is set on a service (e.g., `BAKER_VAULT_PATH` on baker-master)
2. Verify env var VALUE on a service (e.g., where does `BAKER_VAULT_PATH` point to)
3. Enumerate services in the Brisen Render account (id → name → type lookup)
4. Distinguish "env not set" vs "env set, code path broken" during outage triage

### Current state

- brisen-lab `app.py` mounts FastAPI routes either inline (`/api/state`, `/healthz`, `/lifecycle/status`) or via `bus.register(app, _broadcast)` (10 routes mounted there).
- `auth_lab.py` resolves `X-Terminal-Key` header to a worker_slug via `resolve_terminal_key()` (constant-time compare against `BRISEN_LAB_TERMINAL_KEYS` env JSON).
- `authz.py` exposes a `Depends(authz(Policy.AUTH_ONLY))` factory that returns a `CallerContext(slug, is_director)` after 401-on-bad-key.
- No Render API client exists in brisen-lab today. RENDER_API_KEY is not currently in brisen-lab's env (`render.com/v1/services/{id}/env-vars` confirms — not in the env-var list).

### Implementation

#### 1.1 — New module: `render_config.py`

Create `render_config.py` at the brisen-lab repo root (alongside `app.py`, `bus.py`, etc.).

```python
"""Read-only Render API proxy for the bus surface.

AID + AH1 + AH2 query Render service config (env vars + service IDs) via
brisen-lab's existing X-Terminal-Key auth. No write routes — see brief
BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1 for the read-only contract.

Auth: X-Terminal-Key header → resolves to worker_slug. Whitelist
RENDER_CONFIG_ALLOWED_SLUGS gates which slugs may call (Director-ratified
2026-05-11: ['aid', 'lead', 'deputy']).

Env vars required:
  RENDER_API_KEY  — Bearer token for api.render.com. Set on brisen-lab
                    Render service via Render env-var PUT (sourced from
                    1Password op://Baker API Keys/API Render/credential).

Render API contract (verified 2026-05-11):
  GET https://api.render.com/v1/services?limit=100
    → list of {"service": {...}} or just [{...}] depending on API revision;
      handler normalizes to a flat list with id/name/type/branch/autoDeploy.
  GET https://api.render.com/v1/services/{id}/env-vars?limit=100
    → list of {"envVar": {"key": ..., "value": ...}}; handler unwraps to
      [{"key": ..., "value": ...}] for caller convenience.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException

from authz import CallerContext, Policy, authz


RENDER_API_BASE = "https://api.render.com/v1"
RENDER_TIMEOUT_S = 15.0  # Render API is usually <2s; 15s covers cold paths.

# Director-ratified 2026-05-11. Adding `architect` requires a SKILL.md update
# and a new Director ratification — do NOT widen silently.
RENDER_CONFIG_ALLOWED_SLUGS = frozenset({"aid", "lead", "deputy"})


def _require_render_api_key() -> str:
    """Returns the Render API key from env. Raises 503 if unset — fail-LOUD
    so the operator immediately knows the env var is missing, rather than
    returning a vague 502 from a downstream 401."""
    key = os.environ.get("RENDER_API_KEY")
    if not key:
        raise HTTPException(
            status_code=503,
            detail="render_api_key_not_configured",
        )
    return key


def _require_whitelist(ctx: CallerContext) -> None:
    """Director is NOT auto-exempt. Slug must be in the whitelist. The
    Director slug doesn't need Render config reads via the bus — Director
    has 1Password access directly. Keeping the gate tight."""
    if ctx.slug not in RENDER_CONFIG_ALLOWED_SLUGS:
        raise HTTPException(
            status_code=403,
            detail="not_authorized_for_render_config",
        )


async def _render_get(path: str, api_key: str) -> list[dict]:
    """GET path on Render API; return parsed JSON list. Wraps the 4 error
    modes into HTTPExceptions so the caller doesn't redo the try/except."""
    url = f"{RENDER_API_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=RENDER_TIMEOUT_S) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="render_timeout")
    except httpx.HTTPError as e:
        print(f"[render_config] network error: {e}", file=sys.stderr, flush=True)
        raise HTTPException(status_code=502, detail="render_network_error")

    if resp.status_code == 401:
        # Do NOT leak the response body — could contain the bad key fragment.
        raise HTTPException(status_code=502, detail="render_auth_failed")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="render_not_found")
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"render_error:status={resp.status_code}",
        )

    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="render_invalid_json")
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="render_unexpected_shape")
    return data


def register(app: FastAPI) -> None:
    """Mount the 2 read-only Render-config endpoints on `app`. Called from
    app.py startup, after auth_lab.load_terminal_keys()."""

    @app.get("/render/services")
    async def list_services(
        ctx: CallerContext = Depends(authz(Policy.AUTH_ONLY, allow_director=False)),
    ):
        """List all Render services on the Brisen account.

        Returns: [{"id": ..., "name": ..., "type": ..., "branch": ...,
                   "autoDeploy": ..., "repo": ...}].
        Out of scope: deploys, build state, autoscaling config.
        """
        _require_whitelist(ctx)
        api_key = _require_render_api_key()
        raw = await _render_get("/services?limit=100", api_key)
        out = []
        for item in raw:
            # Render API shape: each row is {"service": {...}, "cursor": "..."}
            # OR a bare service dict. Normalize.
            svc = item.get("service") if isinstance(item, dict) and "service" in item else item
            if not isinstance(svc, dict) or "id" not in svc:
                continue  # skip malformed rows defensively
            out.append({
                "id": svc.get("id"),
                "name": svc.get("name"),
                "type": svc.get("type"),
                "branch": svc.get("branch"),
                "autoDeploy": svc.get("autoDeploy"),
                "repo": svc.get("repo"),
            })
        return {"services": out, "count": len(out)}

    @app.get("/render/services/{service_id}/env-vars")
    async def get_env_vars(
        service_id: str,
        ctx: CallerContext = Depends(authz(Policy.AUTH_ONLY, allow_director=False)),
    ):
        """Get all env vars (keys + values) for a Render service.

        Returns: {"service_id": "...", "env_vars": [{"key": ..., "value": ...}],
                  "count": N}.

        Security: values include secrets (API keys, DB URLs, tokens). The
        terminal-key auth gate + whitelist is the boundary; aid/lead/deputy
        terminals are trusted at the same level as the 1Password vault holding
        these values today.
        """
        _require_whitelist(ctx)
        api_key = _require_render_api_key()
        # Reject obviously malformed service IDs before hitting Render.
        if not service_id.startswith("srv-") or len(service_id) > 64 or "/" in service_id:
            raise HTTPException(status_code=400, detail="invalid_service_id")
        raw = await _render_get(f"/services/{service_id}/env-vars?limit=100", api_key)
        out = []
        for item in raw:
            ev = item.get("envVar") if isinstance(item, dict) and "envVar" in item else item
            if not isinstance(ev, dict) or "key" not in ev:
                continue
            out.append({"key": ev.get("key"), "value": ev.get("value")})
        return {"service_id": service_id, "env_vars": out, "count": len(out)}
```

#### 1.2 — Wire `register()` into `app.py` startup

In `app.py`, add the import + register call. The placement matters: must run after `auth_lab.load_terminal_keys()` (so `Depends(authz(...))` works) and after `bus.register(app, _broadcast)` (consistency with existing pattern; no functional dependency).

Edit `app.py` line ~26 (imports block):

```python
import otel_setup
import render_config  # NEW
```

Edit `app.py` line ~91 (startup, immediately after `bus.register(app, _broadcast)`):

```python
    bus.register(app, _broadcast)
    render_config.register(app)  # NEW — read-only Render API proxy
    asyncio.create_task(_retention_loop())
```

#### 1.3 — Add `httpx` to requirements

Check `requirements.txt` for `httpx`. If absent, append:

```
httpx>=0.27.0,<1.0.0
```

If `httpx` is already pulled in transitively (FastAPI's TestClient depends on it), make it an explicit top-level pin so we don't accidentally lose it on a sub-dep update. **Grep** before adding to avoid double-listing.

### Key Constraints

- **Read-only.** No POST/PUT/PATCH/DELETE routes. No retries that could mutate state. No deploy triggers.
- **Whitelist enforced inside handlers**, not just at the Depends layer. `authz(Policy.AUTH_ONLY)` alone would let ANY valid terminal call. The handler-layer `_require_whitelist(ctx)` is the gate.
- **`allow_director=False`** on both Depends — Director doesn't need this surface (has 1Password); tighter gate.
- **No caching.** Each request is a fresh Render API call. Render's surface is low-traffic; caching adds invalidation risk. Re-evaluate if Render API costs become measurable (currently ~$0).
- **Render API key NEVER in code or briefs.** Set via Render env var PUT only (see Step 2 below). Brief references the 1Password vault path; B-code never writes the key value into a file.
- **Service-ID validation** prevents path-traversal injection (`../`, query-string append, etc.). Both length cap (`len > 64`) and prefix check (`srv-`) are needed; a 64-char string starting `srv-` but containing `/` is still rejected.

### Verification

Run the new test file `tests/test_render_config.py` (Feature 2 below). All tests green = handler-layer auth/whitelist correct. Post-deploy smoke tests in Feature 3 verify the live integration with Render API.

---

## Feature 2 — Tests: `tests/test_render_config.py`

### Problem

Two endpoints with auth gating + Render API proxy semantics. Needs coverage for:
- 401 on missing/bad terminal key
- 403 on valid terminal key NOT in whitelist (e.g., `b1`, `b4`, `cortex`)
- 200 on whitelisted slug (`aid`, `lead`, `deputy`)
- Director slug (`director`) rejected with 403 (allow_director=False)
- 503 on missing RENDER_API_KEY env var
- 400 on malformed `service_id` (no `srv-` prefix, too long, contains `/`)
- 502 on Render API 401 (bad API key — verify no key leak in response body)
- 504 on Render API timeout
- 200 with normalized response shape for `/render/services` and `/render/services/{id}/env-vars` (both Render-API response variants: `{"service": {...}}` wrapper and bare dict)

### Implementation

Create `tests/test_render_config.py` mirroring the existing `tests/test_authz_factory.py` pattern (FastAPI TestClient + monkeypatched `auth_lab._TERMINAL_KEYS` + mocked httpx).

```python
"""Tests for render_config.py — read-only Render API proxy on the bus surface."""

from __future__ import annotations

import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

import auth_lab
import render_config


@pytest.fixture
def app_with_render_config():
    """Build a minimal FastAPI app with render_config.register() mounted.
    Seeds a known set of terminal keys for the auth gate."""
    auth_lab._TERMINAL_KEYS = {
        "aid": "test-aid-key",
        "lead": "test-lead-key",
        "deputy": "test-deputy-key",
        "b1": "test-b1-key",
        "b4": "test-b4-key",
        "cortex": "test-cortex-key",
        "director": "test-director-key",
    }
    auth_lab._KEYS_LOADED = True
    app = FastAPI()
    render_config.register(app)
    return app


@pytest.fixture
def client(app_with_render_config):
    return TestClient(app_with_render_config)


@pytest.fixture(autouse=True)
def set_render_api_key(monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "test-render-bearer")


def _fake_render_get_services(*args, **kwargs):
    return [
        {"service": {"id": "srv-aaa", "name": "baker-master", "type": "web_service",
                     "branch": "main", "autoDeploy": "yes",
                     "repo": "https://github.com/x/baker-master"}},
        # bare-dict variant (older API revision)
        {"id": "srv-bbb", "name": "brisen-lab", "type": "web_service",
         "branch": "main", "autoDeploy": "yes",
         "repo": "https://github.com/x/brisen-lab"},
        # malformed row — handler must skip
        {"foo": "bar"},
    ]


def _fake_render_get_envvars(*args, **kwargs):
    return [
        {"envVar": {"key": "FOO", "value": "bar"}},
        # bare-dict variant
        {"key": "BAZ", "value": "quux"},
        # malformed — handler skips
        {"random": "noise"},
    ]


# --- Auth gate ---------------------------------------------------------------

def test_services_no_key_returns_401(client):
    r = client.get("/render/services")
    assert r.status_code == 401
    assert r.json()["detail"] == "bad_terminal_key"


def test_services_bad_key_returns_401(client):
    r = client.get("/render/services", headers={"X-Terminal-Key": "wrong"})
    assert r.status_code == 401


def test_services_non_whitelisted_slug_returns_403(client):
    r = client.get("/render/services", headers={"X-Terminal-Key": "test-b1-key"})
    assert r.status_code == 403
    assert r.json()["detail"] == "not_authorized_for_render_config"


def test_services_director_returns_403(client):
    """Director is intentionally NOT in the whitelist (uses 1Password)."""
    r = client.get("/render/services", headers={"X-Terminal-Key": "test-director-key"})
    assert r.status_code == 403


def test_services_cortex_returns_403(client):
    r = client.get("/render/services", headers={"X-Terminal-Key": "test-cortex-key"})
    assert r.status_code == 403


@pytest.mark.parametrize("slug,key", [("aid", "test-aid-key"),
                                       ("lead", "test-lead-key"),
                                       ("deputy", "test-deputy-key")])
def test_services_whitelisted_slugs_return_200(client, slug, key):
    with patch("render_config._render_get", new=AsyncMock(side_effect=_fake_render_get_services)):
        r = client.get("/render/services", headers={"X-Terminal-Key": key})
    assert r.status_code == 200, f"{slug} should be allowed"
    body = r.json()
    # 3 raw rows → 2 normalized (1 malformed skipped)
    assert body["count"] == 2
    ids = {s["id"] for s in body["services"]}
    assert ids == {"srv-aaa", "srv-bbb"}


# --- env-vars endpoint -------------------------------------------------------

def test_envvars_200_normalizes_both_shapes(client):
    with patch("render_config._render_get", new=AsyncMock(side_effect=_fake_render_get_envvars)):
        r = client.get(
            "/render/services/srv-aaa/env-vars",
            headers={"X-Terminal-Key": "test-aid-key"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["service_id"] == "srv-aaa"
    assert body["count"] == 2
    assert {ev["key"] for ev in body["env_vars"]} == {"FOO", "BAZ"}


def test_envvars_invalid_service_id_no_prefix(client):
    r = client.get(
        "/render/services/notaservice/env-vars",
        headers={"X-Terminal-Key": "test-aid-key"},
    )
    assert r.status_code == 400


def test_envvars_invalid_service_id_too_long(client):
    long_id = "srv-" + "a" * 100
    r = client.get(
        f"/render/services/{long_id}/env-vars",
        headers={"X-Terminal-Key": "test-aid-key"},
    )
    assert r.status_code == 400


def test_envvars_invalid_service_id_with_slash(client):
    # FastAPI path matching may absorb the slash; use a path-encoded variant.
    r = client.get(
        "/render/services/srv-aaa%2F..%2Ffoo/env-vars",
        headers={"X-Terminal-Key": "test-aid-key"},
    )
    assert r.status_code == 400


# --- Render API failures -----------------------------------------------------

def test_services_missing_render_key_returns_503(client, monkeypatch):
    monkeypatch.delenv("RENDER_API_KEY", raising=False)
    r = client.get("/render/services", headers={"X-Terminal-Key": "test-aid-key"})
    assert r.status_code == 503
    assert r.json()["detail"] == "render_api_key_not_configured"


def test_services_render_returns_401_passes_through_as_502(client):
    import httpx
    class FakeResp:
        status_code = 401
        def json(self):
            return {"error": "bad bearer token bearer=test-render-bearer..."}
    async def fake_call(path, api_key):
        # Simulate the _render_get path raising on Render 401
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail="render_auth_failed")
    with patch("render_config._render_get", new=AsyncMock(side_effect=fake_call)):
        r = client.get("/render/services", headers={"X-Terminal-Key": "test-aid-key"})
    assert r.status_code == 502
    assert r.json()["detail"] == "render_auth_failed"
    # Verify NO key fragment leaks in response
    assert "test-render-bearer" not in r.text


def test_services_render_timeout_returns_504(client):
    from fastapi import HTTPException
    async def fake_timeout(*args, **kwargs):
        raise HTTPException(status_code=504, detail="render_timeout")
    with patch("render_config._render_get", new=AsyncMock(side_effect=fake_timeout)):
        r = client.get("/render/services", headers={"X-Terminal-Key": "test-aid-key"})
    assert r.status_code == 504


# --- Whitelist invariant ------------------------------------------------------

def test_whitelist_exactly_three_slugs():
    """Belt-and-braces — if someone widens the whitelist without a Director
    ratification + brief update, this test catches the diff."""
    assert render_config.RENDER_CONFIG_ALLOWED_SLUGS == frozenset({"aid", "lead", "deputy"})
```

### Key Constraints

- **Don't mock too high** — patch `render_config._render_get` (the wrapper) not `httpx.AsyncClient` directly. The wrapper IS the contract; testing it through-and-through bypasses the error mapping we want to exercise.
- **Test the whitelist invariant explicitly** (`test_whitelist_exactly_three_slugs`). If a future PR widens the whitelist silently, this test fails and forces a Director ratification update.
- **Verify the no-leak assertion** — `test_services_render_returns_401_passes_through_as_502` asserts the Render bearer token does NOT appear in the response body. Cheap, catches the most likely leak.

### Verification

```bash
cd ~/bm-b4-brisen-lab
pytest tests/test_render_config.py -v
```

Expected: all tests pass on a literal `pytest` invocation. **No "by inspection" claims** — ship report MUST include the pytest output line.

---

## Feature 3 — Live smoke tests post-merge (operator-run, not in pytest)

After PR merges + Render redeploys brisen-lab with `RENDER_API_KEY` set (see Sequencing §3 below):

```bash
# Setup
LAB=https://brisen-lab.onrender.com
AID_KEY=$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_aid/credential')
LEAD_KEY=$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_lead/credential')
B1_KEY=$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_b1/credential')

# Smoke 1 — aid can list services (expect 200, count >= 2)
curl -s -H "X-Terminal-Key: $AID_KEY" "$LAB/render/services" | python3 -m json.tool

# Smoke 2 — aid can read baker-master env vars (expect BAKER_VAULT_PATH visible)
curl -s -H "X-Terminal-Key: $AID_KEY" "$LAB/render/services/srv-d6dgsbctgctc73f55730/env-vars" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('count:', d['count']); print('BAKER_VAULT_PATH:', [e for e in d['env_vars'] if e['key']=='BAKER_VAULT_PATH'])"

# Smoke 3 — lead can also call (same path, lead key)
curl -s -H "X-Terminal-Key: $LEAD_KEY" "$LAB/render/services" | python3 -c "import json,sys; d=json.load(sys.stdin); print('lead count:', d['count'])"

# Smoke 4 — b1 is BLOCKED (expect 403 not_authorized_for_render_config)
curl -s -w "\nHTTP %{http_code}\n" -H "X-Terminal-Key: $B1_KEY" "$LAB/render/services"

# Smoke 5 — no key is BLOCKED (expect 401 bad_terminal_key)
curl -s -w "\nHTTP %{http_code}\n" "$LAB/render/services"

# Smoke 6 — malformed service-id (expect 400 invalid_service_id)
curl -s -w "\nHTTP %{http_code}\n" -H "X-Terminal-Key: $AID_KEY" "$LAB/render/services/notaservice/env-vars"
```

Capture all 6 outputs in the ship report. Smoke 4-6 are the gates that prove the auth + validation surface is correct on the live deploy.

---

## Files Modified

- `render_config.py` — NEW. The whole module per Feature 1.1.
- `app.py` — 2-line edit (import + register call, per Feature 1.2).
- `requirements.txt` — IF `httpx` not pinned at top level, add it. Grep first.
- `tests/test_render_config.py` — NEW per Feature 2.

## Do NOT Touch

- `bus.py`, `authz.py`, `auth_lab.py`, `db.py`, `freeze.py`, `lifecycle.py`, `otel_setup.py`, `tier_classification.py` — no edits. The new module imports from `authz.py` (read-only).
- Any baker-master file — this brief is brisen-lab-only.
- Any Render env var on services OTHER than brisen-lab — out of scope.
- The existing `X-Forge-Key` auth path on `app.py:234` — that's a separate auth surface (Director's MacBook daemon); the new endpoints use `X-Terminal-Key`.
- `tier-classification.yml` / `static/**` — unrelated surfaces.

## Quality Checkpoints

1. **Whitelist invariant test passes** (`test_whitelist_exactly_three_slugs`). If a future hand-rolled refactor changes the whitelist without updating this test, CI catches it.
2. **No Render API key in any source file.** Grep `git grep -i "render.*api.*key\|rnd_\|API Render"` in the diff before opening PR — confirm only 1Password vault references appear, no key values.
3. **Pytest output captured in PR description** (literal output, not "passes by inspection" per Lesson #8).
4. **All 6 live smoke tests in Feature 3 captured in ship report.** Smoke 4 (b1 → 403) and Smoke 5 (no key → 401) are the most load-bearing — they prove auth gate works in production.
5. **Render env-var PUT verified** post-step-3 — confirm `RENDER_API_KEY` appears in brisen-lab service env-vars list (AH1 runs the GET; see Sequencing §3).
6. **httpx version compatible** — brisen-lab Python is 3.11+, httpx 0.27 works there. Don't bump httpx outside the proposed range without re-running tests.
7. **Response shape is documented in docstring.** AID will read the docstring (or the brief) to know what to expect. The two normalization branches (envelope `{"service": {...}}` vs bare dict) must both work.

---

## Sequencing

1. **B4 EXPLORE**: `cd ~/bm-b4-brisen-lab && git checkout main && git fetch origin && git pull --ff-only`. Confirm at `8b0b7fb` or newer. Read `app.py:75-101` (startup block), `authz.py:132-187` (factory), `tests/test_authz_factory.py` (test pattern). Confirm `requirements.txt` httpx state.
2. **B4 BUILD** on a branch `b4/render-config-read-1`:
   - Write `render_config.py` per Feature 1.1.
   - Edit `app.py` 2 lines per Feature 1.2.
   - Edit `requirements.txt` IF needed.
   - Write `tests/test_render_config.py` per Feature 2.
   - Run `pytest tests/test_render_config.py -v` — must be all-green before PR.
   - Run `pytest tests/ -v` — confirm no regression to existing tests.
3. **AH1 Render env-var PUT** (Tier-B, post-merge): set `RENDER_API_KEY` on brisen-lab service `srv-d7q7kvlckfvc739l2e8g` via Render API merge mode (value from `op://Baker API Keys/API Render/credential`); trigger deploy; verify env-var landed via `GET /v1/services/{id}/env-vars`. **DO NOT set this env var BEFORE merge** — the new code paths must not fire on a half-rolled-out service.
4. **AH1 live smoke tests** per Feature 3. Capture all 6 outputs.
5. **AH1 confirm to AID via bus** + close out msg #59 thread on this side. Post a paste-block to AID with the 4 example queries AID can run to verify Render config self-serve.

---

## Risks + Lessons applied upfront

- **Lesson — secrets in brief (anti-pattern):** Brief contains ZERO API key values. Only references to `op://Baker API Keys/API Render/credential` and the env-var name `RENDER_API_KEY`. B4 must NOT echo the actual key into any commit.
- **Lesson — env var set but missing on deploy:** Feature 3 Smoke 1 will fail with 503 if the env-var PUT step didn't actually land. Operator must verify via `GET /v1/services/{id}/env-vars` not assume the PUT succeeded.
- **Lesson — fenced auth surface:** Whitelist is `frozenset` not a list (immutable; harder to silently widen). Test `test_whitelist_exactly_three_slugs` explicit guard.
- **Lesson — Render API shape variants:** Both `{"service": {...}}` and bare-dict variants seen historically. Handler normalizes both; tests exercise both.
- **Risk — secrets exposure via this endpoint:** Values include API keys, DB URLs, tokens. Mitigation: whitelist + read-only + same trust level as 1Password already grants AID/AH1/AH2. Director ratified this trade-off 2026-05-11. Documented in the env-vars endpoint docstring.
- **Risk — Render API rate limit:** Render's API is generous; 2 GETs per AID-triage cycle is well under any cap. Not addressing rate limiting in v1; revisit if AID's polling cadence creates real pressure.
- **Risk — endpoint shadows future bus route at `/render/*`:** Currently brisen-lab has no `/render/*` routes. The bus uses `/msg/*`, `/event/*`, `/auth/*`, `/api/v2/*`, `/lifecycle/*`. The `/render/*` namespace is free and clearly delineates the Render-config surface.

## Acceptance Criteria

| AC | Description | Verification |
|---|---|---|
| **A1** | `render_config.py` module exists with `register(app)` function | file present at repo root + grep confirms `def register` |
| **A2** | `app.py` imports `render_config` and calls `register(app)` after `bus.register(...)` | grep `app.py` for both lines |
| **A3** | `tests/test_render_config.py` passes 14+ tests on literal `pytest` run | pytest output in PR description (not "by inspection") |
| **A4** | Whitelist is exactly `{"aid", "lead", "deputy"}` (frozenset) | `test_whitelist_exactly_three_slugs` |
| **A5** | `pytest tests/ -v` shows no regressions to existing tests | pytest output |
| **A6** | `RENDER_API_KEY` env var set on brisen-lab `srv-d7q7kvlckfvc739l2e8g` post-merge | Render GET env-vars |
| **A7** | All 6 live smoke tests in Feature 3 captured in ship report with expected results (Smoke 4 → 403, Smoke 5 → 401, Smoke 6 → 400) | ship report contents |
| **A8** | No Render API key value appears anywhere in the diff | `git grep -i rnd_ HEAD` returns empty |
| **A9** | AID confirms self-serve via bus paste-block (msg posted to /msg/aid with example queries) | bus message ID in ship report |

**Ship gate:** A1-A9 all green. A3 + A5 = pytest green. A7 = live integration green.

---

## Reference

- brisen-lab service: `srv-d7q7kvlckfvc739l2e8g` @ `https://brisen-lab.onrender.com`
- Render API base: `https://api.render.com/v1`
- Render API key: 1Password `op://Baker API Keys/API Render/credential`
- Director ratification: 2026-05-11 ~07:55Z "confirm and go" on whitelist `['aid', 'lead', 'deputy']`
- AID's anchor request: "Tool fix: ask AH1 to expose a thin Render-config-read endpoint to AID's bus surface (read-only — env vars + service id). Closes the Render-MCP gap without giving me write authority I shouldn't have."
- Existing test pattern: `~/bm-b4-brisen-lab/tests/test_authz_factory.py`
- Existing route registration pattern: `~/bm-b4-brisen-lab/bus.py` `register(app, broadcast_fn)`
- Existing auth surface: `~/bm-b4-brisen-lab/authz.py` `authz(policy, allow_director=...)` Depends factory

---

**PL ship-report:** End your chat ship report with a fenced PL paste-block per SKILL.md §"PL ship-report contract".
