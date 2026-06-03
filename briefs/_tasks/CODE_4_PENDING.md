---
dispatch: M365_GRAPH_CERT_AUTH_1
target: b4
status: PENDING
from: cowork-ah1 (Director-directed 2026-06-03)
gate_G0: codex PASS — bus #1742 (rev2); the two #1735 blockers are folded
---

# CODE_4_PENDING — M365_GRAPH_CERT_AUTH_1

**b4 — MANDATORY before any reply:** Read this file + `~/baker-vault/_ops/agents/b4/orientation.md` + `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md`. Confirmation phrase: `"B4 oriented. Read: CODE_4_PENDING.md, MEMORY.md."`

## Context

### Surface contract: N/A — backend Graph certificate auth + host-pin, no UI surface.

Dennis (EVOK) issued a **certificate** (.pfx), not a client secret (production-preferred per program §Phase 0). Phase 1 has two gaps: (1) `GraphClient` is client-secret-only; (2) `_request` attaches the bearer to ANY URL before any host check — a latent credential-leak. This brief fixes both. codex G0 (#1742) PASSED rev2.

**Verified current state (now on main):**
- `config/settings.py:74-83` — `class GraphConfig` (tenant_id :77, client_id :78, client_secret :79, enabled :83). **GraphConfig lives here, NOT in graph_client.py.**
- `kbl/graph_client.py` — `is_configured()` :35; `_acquire_token()` :51 (`ConfidentialClientApplication(..., client_credential=self.cfg.client_secret)`); `_request()` :77 acquires token (:79) then `requests.get(url, headers={Authorization: Bearer})` (:83-85) with **no scheme/host check**; `get_url()` :101 passes any absolute URL to `_request` (:108).

## Estimated time: ~2h · Complexity: Low-Medium · Prereqs: Phase 1 merged (done). pfx password for LIVE test only.

---

## Fix 1: Certificate auth

### Problem
The issued cert is unusable; `GraphClient` authenticates only with a client secret.

### Implementation
1. **`config/settings.py` `GraphConfig`** — add (keep `client_secret`):
   - `cert_private_key: str = os.getenv("M365_CERT_PRIVATE_KEY", "")`  (PEM string)
   - `cert_path: str = os.getenv("M365_CERT_PATH", "")`  (PEM file path, alternative)
   - `cert_thumbprint: str = os.getenv("M365_CERT_THUMBPRINT", "")`  (SHA-1 hex)
2. **`graph_client.py:35 is_configured()`** — true if `tenant_id` AND `client_id` AND (`client_secret` OR ((`cert_private_key` OR `cert_path`) AND `cert_thumbprint`)).
3. **`graph_client.py:51 _acquire_token`** — when cert present, `client_credential = {"private_key": <cert_private_key, or pathlib read of cert_path>, "thumbprint": cert_thumbprint}`; else the existing secret path. **Cert precedence** when both set. Read `cert_path` inside the existing token try block (codex note).
4. **No new dependency** — MSAL accepts a PEM private-key string + precomputed thumbprint; `pathlib` reads the file.

### Constraints
Dormant behind `BAKER_USE_GRAPH` (default false). Never log key / secret / thumbprint — coarse error code only.

## Fix 2: Host-pin the bearer (security — closes a latent credential leak)

### Problem
`_request` acquires a token and sends `Authorization: Bearer` to ANY URL. `get_url("https://evil.example/...")` leaks the app token. codex mock-probe confirmed.

### Implementation
At the **TOP of `_request()`, BEFORE `_acquire_token()`**:
```python
from urllib.parse import urlparse  # module-level import
...
p = urlparse(url)
if p.scheme != "https" or p.hostname != "graph.microsoft.com":
    return None  # do NOT acquire token, do NOT requests.get, do NOT log the url
```

### Constraints
Guard runs before token acquisition. On reject: no token acquired, no `requests.get`, no URL / delta-token logged. Protects both `get()` and `get_url()` (shared `_request`).

## Acceptance criteria
1. Cert env + `BAKER_USE_GRAPH=true` → MSAL built with the cert dict (unit, mock MSAL, no network).
2. Secret-only → back-compat (unit).
3. Neither → `is_configured()` false, dormant.
4. `get_url` non-https URL → returns None; MSAL NOT called; `requests.get` NOT called; URL not logged (caplog assert).
5. `get_url` non-graph host (`https://evil.example`) → same as #4.
6. Valid `https://graph.microsoft.com` delta URL → passes through (existing test `tests/test_graph_client.py:160-172` stays green).
7. caplog sentinel: `private_key`, `thumbprint`, `client_secret`, token value NEVER appear in logs.
8. py3.12 literal-string test pass; `/security-review` CLEAR.

## Files Modified
- `config/settings.py` — `GraphConfig` cert fields.
- `kbl/graph_client.py` — cert credential in token path + host-pin guard in `_request`.
- `tests/test_graph_client.py` — cert/secret/neither selection; host-pin (non-https, non-graph, valid pass-through); caplog sentinels.

## Do NOT touch
- `BAKER_USE_GRAPH` default (false). Phase 2+ pollers (not built). Non-Graph mail paths.

## Gates
G0 codex PASS (#1742) → **G1 lead (unit, py3.12)** → G2 `/security-review` → G3 codex → merge. Dormant → no post-deploy AC until Phase-0 creds + Phase-2 LIVE test.

## Report back
On completion write `briefs/_reports/B4_M365_GRAPH_CERT_AUTH_1_<date>.md` + bus-post the ship to cowork-ah1 (dispatcher) and lead (owns merge gate).
