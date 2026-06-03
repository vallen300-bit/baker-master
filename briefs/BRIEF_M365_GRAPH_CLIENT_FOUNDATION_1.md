---
type: ops
author: aihead1
created: 2026-06-03
status: DISPATCHABLE v2 — codex-arch G0 PASS-WITH-NOTES (#1670); params exactness note folded
program: BRIEF_M365_MIGRATION_PROGRAM
phase: 1 of 5
---

# BRIEF: M365_GRAPH_CLIENT_FOUNDATION_1 — Microsoft Graph auth client (dormant, flag-gated)

## Context
Brisen migrated email + calendar to Microsoft 365 (Director ask 2026-06-03). Baker has **no
Microsoft Graph integration** — `msgraph-sdk` is commented out (`requirements.txt:76`), and env
scaffolding `M365_CLIENT_ID/SECRET/TENANT_ID` (`config/.env.example:31-33`) is read by nothing.
This is **Phase 1** of the parallel-run migration program: build the shared Graph auth + REST
client that Phases 2-4 (mail poll / calendar / send) will all sit on. It ships **dormant** behind
`BAKER_USE_GRAPH` (default false), with **no poller wiring and no Gmail/EVOK changes** — so blast
radius is ~zero. It is **fully buildable + unit-testable now with mocks**, before the Azure app
registration (Phase 0) provisions live credentials.

### Surface contract: N/A — pure backend module (auth client + config + tests); no dashboard/clickable surface.

## Estimated time: ~2-3h
## Complexity: Medium
## Prerequisites: none for build (mocked). Live token check deferred to Phase 2 (needs Phase 0 Azure creds).

---

## Context Contract

### Router
- Routed owner: B-code (idle build worker; lead assigns on G0 PASS per engineering-router).
- Why this owner: self-contained new backend module + unit tests; standard B-code build work.
- Alternatives explicitly rejected: AID-T (Director 2026-06-03: AID-T is enquiry-only, not an engineer); lead-build (orchestrator lane, not implementation).

### Problem Evidence
- User-visible problem or desired outcome: Baker must read/send M365 mail+calendar via Graph; today it cannot — no Graph client exists.
- Evidence / repro / source: `grep -rn "graph.microsoft\|msal\|ConfidentialClientApplication" .` → no real hits; `requirements.txt:76` `# msgraph-sdk` commented; `config/.env.example:31-33` M365_* declared but unconsumed (verified 2026-06-03).
- Current behavior verified by: 4-agent audit 2026-06-03 + direct grep/read.

### Current State
- Existing code/docs searched: `config/settings.py` (GeminiConfig/GmailConfig dataclass pattern, lines 64-132), `requirements.txt:54-76`, `config/.env.example`.
- Existing implementation or prior brief checked: none — `git log --grep` for m365/graph = empty (verified 2026-06-03).
- Code graph search: N/A — rg/Read enough.
- DB schema verified: N/A — Phase 1 touches no DB.
- API/function contracts verified: MSAL `ConfidentialClientApplication(client_id, authority, client_credential).acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])` returns dict with `access_token` or `error`/`error_description`. Graph REST base `https://graph.microsoft.com/v1.0`.

### Interface (interface-first)
- Public interface — new module `kbl/graph_client.py`:
  - `class GraphClient:`
    - `def __init__(self, config: GraphConfig | None = None) -> None`
    - `def is_configured(self) -> bool` — True only if tenant_id + client_id + client_secret all present.
    - `def is_enabled(self) -> bool` — returns `cfg.enabled` (`BAKER_USE_GRAPH`).
    - `def is_ready(self) -> bool` — `is_enabled() and is_configured()`. **The single gate; nothing acquires a token unless this is True.** (codex-arch G0 #1668 finding 1 — flag must be enforced, not just documented.)
    - `def _acquire_token(self) -> str | None` — returns None unless `is_ready()`; else MSAL `acquire_token_for_client(scopes)`. **Do NOT cache the raw bearer on the instance** — MSAL's `ConfidentialClientApplication` owns the app-token cache and returns a valid cached token (it auto-renews from secret/cert). Never raises. (codex-arch G0 #1668 finding 2 — no forever-cached bearer.)
    - `def get(self, path: str, params: dict | None = None, timeout: int = 8) -> dict | None` — GET `{base_url}{path}` (v1.0-relative path). Never raises.
    - `def get_url(self, url: str, timeout: int = 8) -> dict | None` — GET an **opaque absolute Graph URL** (Phase-2 delta `@odata.nextLink` / `@odata.deltaLink`); preserves the query string exactly; **never logs the full URL or query** (delta tokens are sensitive). Never raises. (codex-arch G0 #1668 finding 3.)
    - `def health(self) -> dict` — `{"enabled": bool, "configured": bool, "token_acquired": bool, "error": str|None}` for a future `/api/graph_health` probe (endpoint NOT added this phase).
- What this module hides from callers: token acquisition, MSAL's cache/renewal, authority URL, bearer header, base URL, timeout + error handling, the flag gate.
- Callers must NOT need to know: MSAL, the authority URL, how/where the token is cached, Graph host, the delta-URL opacity rule.

### Stable Paths
- Files expected to change:
  - `requirements.txt` — add `msal>=1.28.0` (uncomment/keep `msgraph-sdk` line OFF; we use msal + existing `requests`, NOT the heavy SDK).
  - `config/settings.py` — add `GraphConfig` dataclass (mirror `GeminiConfig`).
  - `kbl/graph_client.py` — NEW module (the interface above).
  - `tests/test_graph_client.py` — NEW unit tests (mocked MSAL + requests).
- Files explicitly NOT to touch: `triggers/*` (no poller wiring this phase), `scripts/extract_gmail.py`, `outputs/email_*.py`, `triggers/exchange_*.py`, the scheduler. No Gmail/EVOK change.
- Volatile files: none (`dashboard.py` untouched).

### Constraints
- Repo hard rules: all external calls in try/except; no secrets in code (reference env names only); no `--no-verify`.
- Security / auth limits: client secret read from env ONLY (`M365_CLIENT_SECRET`); never logged, never echoed in `health()` error strings (scrub before return). No token written to disk.
- Migration / singleton / try-except rules: `get()` and `_acquire_token()` must never raise to the caller — return None + log. No DB, so no rollback needed.
- Flag: `BAKER_USE_GRAPH` (default `"false"`) on `GraphConfig.enabled`; module is import-safe and inert when false/unconfigured.
- UI pre-brief: N/A.

### Acceptance Criteria
- Build AC: `python3 -c "import py_compile; py_compile.compile('kbl/graph_client.py', doraise=True)"` clean; `from kbl.graph_client import GraphClient` imports with no env set; `GraphClient().is_configured()` and `.is_ready()` return False when M365_* unset.
- Test AC: `pytest tests/test_graph_client.py -v` passes — covers:
  1. `is_configured()` gating (all-set vs missing-one); `is_enabled()` reflects `BAKER_USE_GRAPH`.
  2. **Flag enforcement (finding 1):** creds present BUT `BAKER_USE_GRAPH=false` → `is_ready()` False → `_acquire_token()`/`get()`/`get_url()` return None, **MSAL ConfidentialClientApplication is NEVER constructed and requests.get is NEVER called** (assert via mock `.called is False`).
  3. `_acquire_token` success (ready + mock MSAL returns `access_token`) → token returned.
  4. `_acquire_token` failure (mock MSAL returns `{"error": "invalid_client"}`) → None, no raise.
  5. **No forever-cache (finding 2):** assert `self._token` does not exist / no raw bearer stored on the instance; two `get()` calls each invoke `acquire_token_for_client` (MSAL owns caching) — the client does not short-circuit on a stale instance bearer.
  6. `get()` success (mock requests 200 → dict) and failure (timeout/500 → None, no raise).
  7. **`get_url()` (finding 3):** opaque absolute URL passed through unchanged (assert requests.get called with that exact URL, `params=None`); on failure the log contains the redacted marker, **not** the URL/query.
  8. **Secret-scrub:** `caplog` contains neither the `client_secret` value NOR any `access_token` value across success and failure paths.
  9. `health()` shapes for: unconfigured, configured-but-flag-off, ready-but-token-fail.
- Post-deploy AC: **N/A this phase — no live Azure credentials until Phase 0 registration.** Module ships dormant (`BAKER_USE_GRAPH=false`, M365_* empty). First live token acquisition AC moves to Phase 2 when creds are provisioned. (Stated per Harness V2 — not a "tests pass" cop-out; the surface is genuinely inert until Phase 0.)
- Done-state terminal class: code-merged (dormant library; no runtime behavior change to verify in prod).

### Gate Plan
- G0 / Codex: codex-arch reviews this brief (architecture of the auth client + secret handling).
- G1 / static review: lead — signatures, import-safety, flag-off inertness, secret-scrub.
- G2 / security-review: YES — new credential acquisition + secret handling path. Run `/security-review` on the PR (isolated clone).
- G3 / Architect: light — new external-integration module; confirm interface boundary + reversibility.

### Bus + Writeback
- dispatched_by: lead (aihead1)
- Expected ship-report recipient: lead
- Bus topics: dispatch `dispatch/m365-graph-client-foundation-1`; ship `ship/m365-graph-client-foundation-1`.
- Memory/writeback: on merge, append `tasks/lessons.md` only if a build surprise occurs; update `BRIEF_M365_MIGRATION_PROGRAM` Phase 1 → DONE.

---

## Implementation notes (copy-pasteable scaffolding — B-code adapts, signatures are owned by this brief)

### 1. `requirements.txt` — add msal (keep msgraph-sdk OFF)
```
msal>=1.28.0              # M365_GRAPH_CLIENT_FOUNDATION_1: OAuth2 client-credentials for Microsoft Graph
# msgraph-sdk>=1.0.0      # intentionally NOT used — raw Graph REST via requests is lighter + easier to mock
```

### 2. `config/settings.py` — add GraphConfig (mirror GeminiConfig, place near it)
```python
@dataclass
class GraphConfig:
    """M365_GRAPH_CLIENT_FOUNDATION_1: Microsoft Graph (M365) configuration. Dormant until Phase 0 creds + BAKER_USE_GRAPH=true."""
    tenant_id: str = os.getenv("M365_TENANT_ID", "")
    client_id: str = os.getenv("M365_CLIENT_ID", "")
    client_secret: str = os.getenv("M365_CLIENT_SECRET", "")
    base_url: str = "https://graph.microsoft.com/v1.0"
    authority_tmpl: str = "https://login.microsoftonline.com/{tenant}"
    scope: List[str] = field(default_factory=lambda: ["https://graph.microsoft.com/.default"])
    enabled: bool = os.getenv("BAKER_USE_GRAPH", "false").lower() == "true"
```

### 3. `kbl/graph_client.py` — NEW (skeleton; B-code completes per interface)
```python
"""M365_GRAPH_CLIENT_FOUNDATION_1: shared Microsoft Graph auth + REST client.
Dormant until M365_* env present AND BAKER_USE_GRAPH=true. Never raises to callers."""
import logging
import requests
from msal import ConfidentialClientApplication
from config.settings import GraphConfig

logger = logging.getLogger(__name__)


class GraphClient:
    def __init__(self, config: GraphConfig | None = None) -> None:
        self.cfg = config or GraphConfig()
        self._app = None  # MSAL app holds the token cache; we never cache the raw bearer ourselves

    def is_configured(self) -> bool:
        return bool(self.cfg.tenant_id and self.cfg.client_id and self.cfg.client_secret)

    def is_enabled(self) -> bool:
        return bool(self.cfg.enabled)

    def is_ready(self) -> bool:
        # The single gate. Creds present is NOT enough — flag must be on too.
        return self.is_enabled() and self.is_configured()

    def _acquire_token(self) -> str | None:
        if not self.is_ready():            # finding 1: enforce the flag, not just is_configured()
            return None
        try:
            if self._app is None:
                self._app = ConfidentialClientApplication(
                    self.cfg.client_id,
                    authority=self.cfg.authority_tmpl.format(tenant=self.cfg.tenant_id),
                    client_credential=self.cfg.client_secret,
                )
            # finding 2: do NOT cache the bearer on self. MSAL returns a valid cached token
            # and auto-renews from the secret/cert when expired.
            result = self._app.acquire_token_for_client(scopes=self.cfg.scope)
            if "access_token" in result:
                return result["access_token"]
            logger.error("Graph token acquisition failed: %s", result.get("error"))  # never log error_description / secret
            return None
        except Exception as e:
            logger.error("Graph token acquisition exception: %s", type(e).__name__)
            return None

    def _request(self, url: str, params: dict | None, timeout: int, log_url: str) -> dict | None:
        token = self._acquire_token()
        if not token:
            return None
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params,            # pass-through unchanged (None for get_url opaque delta URLs) — codex-arch #1670 exactness note
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("Graph GET %s failed: %s", log_url, type(e).__name__)  # log_url is redacted for get_url
            return None

    def get(self, path: str, params: dict | None = None, timeout: int = 8) -> dict | None:
        return self._request(f"{self.cfg.base_url}{path}", params, timeout, log_url=path)

    def get_url(self, url: str, timeout: int = 8) -> dict | None:
        # finding 3: opaque nextLink/deltaLink absolute URL; query preserved by passing params=None.
        # Never log the full URL (delta tokens are sensitive) — log only a redacted marker.
        return self._request(url, None, timeout, log_url="<delta/next-link redacted>")

    def health(self) -> dict:
        token_ok = bool(self._acquire_token()) if self.is_ready() else False
        return {"enabled": self.is_enabled(), "configured": self.is_configured(),
                "token_acquired": token_ok, "error": None}
```

### 4. `tests/test_graph_client.py` — NEW (mock MSAL + requests; no network)
Cover the 6 Test-AC cases. Use `unittest.mock.patch` on `kbl.graph_client.ConfidentialClientApplication` and `kbl.graph_client.requests`. Assert `is_configured()` gating via a `GraphConfig` built with explicit values; assert `_acquire_token` returns None (not raise) on `{"error": "invalid_client"}`; assert no secret value appears in caplog.

## Files Modified
- `requirements.txt` — add `msal`.
- `config/settings.py` — add `GraphConfig`.
- `kbl/graph_client.py` — NEW.
- `tests/test_graph_client.py` — NEW.

## Do NOT Touch
- `triggers/*`, `scripts/extract_gmail.py`, `outputs/email_*.py`, scheduler — no wiring this phase.
- `triggers/exchange_*.py` — EVOK retirement is Phase 5.

## Quality Checkpoints
1. `from kbl.graph_client import GraphClient` succeeds with zero env set (import-safe).
2. `is_ready()` is the ONLY gate: creds present + flag off → no token, no MSAL build, no HTTP (finding 1).
3. No raw bearer cached on the instance; MSAL owns token validity/renewal (finding 2).
4. `get_url()` passes opaque delta/nextLink URLs unchanged and never logs them (finding 3).
5. Neither `M365_CLIENT_SECRET` nor any `access_token` ever reaches logs (caplog asserts).
6. `BAKER_USE_GRAPH` defaults false; module inert; no scheduler/poller/Gmail/EVOK touched.
7. `pytest tests/test_graph_client.py -v` green on a literal run (not "by inspection").

## Verification (B-code proves it works)
```
python3 -c "import py_compile; py_compile.compile('kbl/graph_client.py', doraise=True)"
python3 -c "from kbl.graph_client import GraphClient; print(GraphClient().is_configured())"  # -> False
pytest tests/test_graph_client.py -v
```
