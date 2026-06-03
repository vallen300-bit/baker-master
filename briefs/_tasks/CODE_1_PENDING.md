---
dispatch: M365_GRAPH_CLIENT_FOUNDATION_1
to: b1
from: lead
dispatched_by: lead
status: PENDING
dispatched_at: 2026-06-03T10:00:00Z
authored: 2026-06-03
brief_path: briefs/BRIEF_M365_GRAPH_CLIENT_FOUNDATION_1.md
target_repo: baker-master
estimated_time: ~2-3h
complexity: Medium
brief_version: v2 — codex-arch G0 PASS-WITH-NOTES (#1670); 3 #1668 folds + params exactness note applied
codex_pre_review: PASS-WITH-NOTES (codex-arch #1670) — flag-gate enforcement, no raw-bearer cache, get_url() for delta, secret+token caplog all confirmed
reply_to: lead
ship_topic: ship/m365-graph-client-foundation-1
program: BRIEF_M365_MIGRATION_PROGRAM (Phase 1 of 5)
anchor_chat: Director 2026-06-03 "go ... use Deputy, B codes, codex arch ... follow harness v2 ... use /write-brief sop" — Brisen migrated to Microsoft 365; Baker mail/calendar re-platform onto Microsoft Graph.
---

### Surface contract: N/A — pure backend module (auth client + config + tests); no clickable surface. Full block in brief Context.

# b1 dispatch — M365_GRAPH_CLIENT_FOUNDATION_1

Read `briefs/BRIEF_M365_GRAPH_CLIENT_FOUNDATION_1.md` end-to-end before any code. **Target repo: baker-master** (your `~/bm-b1` baker-master clone — files are `kbl/`, `config/settings.py`, `requirements.txt`, `tests/`).

Brief cleared **codex-arch G0 = PASS-WITH-NOTES** (#1670, 2026-06-03). All 3 prior findings + the params exactness note are already folded into the brief. No further pre-write review required.

**What this is:** Phase 1 of 5 in the Microsoft 365 migration. Brisen moved email+calendar from Google to M365. Build the **shared Microsoft Graph auth + REST client** that Phases 2-4 (mail poll / calendar / send) will reuse. It ships **DORMANT** behind `BAKER_USE_GRAPH` (default false) with **NO poller/scheduler/Gmail/EVOK wiring** — blast radius ~zero. Fully buildable + unit-testable NOW with mocks (no live Azure creds yet — those come from a separate external Phase 0).

**Scope (4 files, all in the brief with copy-pasteable skeleton):**
- `requirements.txt` — add `msal>=1.28.0` (keep `msgraph-sdk` commented; we use msal + existing `requests`).
- `config/settings.py` — add `GraphConfig` dataclass (mirrors `GeminiConfig`; reads `M365_TENANT_ID/CLIENT_ID/CLIENT_SECRET` + `BAKER_USE_GRAPH`).
- `kbl/graph_client.py` — NEW `GraphClient` (the brief's interface is binding: `is_configured/is_enabled/is_ready/_acquire_token/get/get_url/health`).
- `tests/test_graph_client.py` — NEW unit tests (mock MSAL + requests; no network). All 9 Test-AC cases.

**Load-bearing (do not regress — these are the G0 findings):**
1. `is_ready()` = `is_enabled() and is_configured()` is the ONLY gate. Creds present + `BAKER_USE_GRAPH=false` ⇒ NO MSAL construction, NO `requests.get`. Test it.
2. Do NOT cache the raw bearer on the instance. MSAL `acquire_token_for_client` owns the token cache/renewal.
3. `get_url(url)` passes opaque `@odata.nextLink`/`deltaLink` URLs unchanged (`params=None`) and NEVER logs the full URL/query (redacted marker only).
4. Neither `M365_CLIENT_SECRET` nor any `access_token` may appear in logs — caplog asserts on success AND failure paths.
5. Never-raise contract on `_acquire_token`/`get`/`get_url`.

**Constraints:** do NOT touch `triggers/*`, `scripts/extract_gmail.py`, `outputs/email_*.py`, the scheduler, or `triggers/exchange_*.py`. No secrets in code (env-name references only).

**Gates:** G1 (lead static review) → **G2 `/security-review` REQUIRED** (new credential acquisition + bearer-token handling — codex-arch confirmed) → G3 (architect, light).

**Ship:** open PR on `baker-master`; bus-post `ship/m365-graph-client-foundation-1` to `lead`. **Do NOT merge** (AH gate). Answer the done-rubric in the ship report: task class = backend foundation library; build AC (imports + is_ready gating + `pytest tests/test_graph_client.py -v` GREEN on a literal run); post-deploy AC = N/A this phase (no live creds until Phase 0) — state that explicitly, it is not a cop-out.
