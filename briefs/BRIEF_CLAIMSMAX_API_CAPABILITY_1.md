---
brief_id: CLAIMSMAX_API_CAPABILITY_1
trigger_class: MEDIUM
target_branch: b4/claimsmax-api-capability-1
matter_slug: claimsmax
cross_matter_usage: [mo-vie-am, hagenauer-rg7, cupial, ao, baker-internal]
dispatched_by: AH1
dispatched_at: 2026-05-16
director_auth: 2026-05-16 chat — "Please go ahead and write it into Baker's as a permanent capability"
---

# CLAIMSMAX_API_CAPABILITY_1 — Baker capability: ClaimsMax v1 REST API client + MCP tools

## Problem

ClaimsMax (`https://brisen.claimsmax.co.uk/api/v1/`) is a Brisen-owned investigation platform with **187,232 indexed documents + 173,944 emails + 1,397,864 chunks** covering Hagenauer/RG7, MO Vie, Brisen Development, MOHG, Cupial, and related corpora. Today only the web UI is usable; Baker has no programmatic access.

This brief wires the API into Baker as a permanent capability so every matter Desk (mo-vie-am, hagenauer-rg7, cupial, ao, etc.) can run searches and multi-step investigations directly via Baker MCP tools.

## Authentication

API key already provisioned. Lives in 1Password at `op://Passwords/blu6mh64ytmb3u2dznpwfj4tqa/credential` (item title: "ClaimsMax API key — Baker AI Head A1").

**AH1 will set the Render env var `CLAIMSMAX_API_KEY` before B4's merge** — B4 reads from `os.environ["CLAIMSMAX_API_KEY"]`, never hardcodes.

Auth pattern (per `~/Desktop/ClaimsMaxAPI.md`):

```
Authorization: Bearer cmx_<key>
```

## Scope

### 1. HTTP client (`kbl/claimsmax_client.py`)

Thin wrapper around requests/httpx with:

- Base URL from `CLAIMSMAX_BASE_URL` env var (default `https://brisen.claimsmax.co.uk/api/v1/`)
- Bearer auth from `CLAIMSMAX_API_KEY` env var
- Default request timeout 120s (investigations stream slow)
- 429 backoff: honour `Retry-After` header, max 3 retries
- 5xx: surface error, no retry
- All HTTP calls wrapped try/except per repo hard rule (fault-tolerant or it doesn't ship)

Public methods:

- `search(query, filters=None, mode="natural", page=1, per_page=25, sort="relevance", l3_tags_required=None)` → dict
- `get_document(doc_id, include_text=False)` → dict
- `get_document_text(doc_id, page=1, chars_per_page=5000)` → dict
- `get_document_download_url(doc_id, presigned=True)` → dict
- `investigate_start(query, language="en", starting_doc_id=None, max_iterations=15, uploaded_context=None, exclude_internal=False)` → dict `{run_id, status}`
- `investigate_status(run_id)` → dict (slim projection per spec)
- `investigate_events(run_id)` → dict (full event log; optional)
- `ask(...)` → raises `NotImplementedError("ClaimsMax /ask endpoint disabled — vendor bug under repair (temperature deprecated server-side as of 2026-05-16). Re-enable when Ellie Technologies confirms fix.")`

### 2. MCP tools (`tools/claimsmax.py` — new module)

Follow the existing `baker_*` tool pattern (see `.claude/docs/baker-mcp-api.md` for the 24-tool convention). Register four tools:

| Tool | Args | Returns |
|---|---|---|
| `baker_claimsmax_search` | `query, filters?, mode?, per_page?` | top results: `[{doc_id, filename, doc_date, l1, l2, snippet, score}]` + total |
| `baker_claimsmax_investigate` | `query, language?, starting_doc_id?` | `{run_id, status}` (fire-and-forget) |
| `baker_claimsmax_check_investigation` | `run_id` | `{status, step_count, title, report, error}` |
| `baker_claimsmax_get_document` | `doc_id, include_text?` | full metadata (+ extracted text if requested) |

Register in the same tool registry pattern as existing `baker_*` tools — read `tools/__init__.py` and one existing tool module (e.g. `tools/<existing>.py`) before authoring.

### 3. Capability set registration

Insert a new row into `capability_sets` via migration:

- `capability_type`: pick the right enum (read `migrations/` for canonical values — likely `domain`)
- `name`: `claimsmax_archive`
- `description`: "Search and investigate Brisen's ClaimsMax document archive (187k docs / 173k emails / Hagenauer-RG7 / MO-Vie / Brisen-Development / Cupial corpora)"
- `active`: `true`

Add the migration following the existing migration pattern; do NOT edit any applied migration.

### 4. Tests (`tests/test_claimsmax_client.py`)

Mocked tests (no live-API dependency by default):

- ☐ Happy path: `search` returns parsed dict
- ☐ 401: raises `ClaimsmaxAuthError`
- ☐ 429: backs off per `Retry-After` then retries (mock 1 retry succeeds)
- ☐ 5xx: surfaces `ClaimsmaxServerError`
- ☐ `investigate_start` → `investigate_status` flow (mock state transition)
- ☐ `ask()` raises `NotImplementedError`

Optional `@pytest.mark.claimsmax_live` marker for opt-in smoke tests against the real API (requires `CLAIMSMAX_API_KEY` env in local dev only — gated; auto-skip in CI).

### 5. Documentation

Append a new section to `.claude/docs/baker-mcp-api.md`:

- 4 new tools listed in the same table format as existing tools
- Sample queries (one per tool)
- Note on `/ask` being disabled pending vendor fix
- Pointer to the API spec at `~/Desktop/ClaimsMaxAPI.md`

## Acceptance criteria

1. ☐ `kbl/claimsmax_client.py` exists with 8 methods (7 implemented + `ask()` placeholder)
2. ☐ 4 MCP tools registered and callable via standard Baker MCP entry point
3. ☐ Capability set row inserted via new migration
4. ☐ All HTTP calls try/except wrapped; 429 retry verified by test
5. ☐ Tests pass: `pytest tests/test_claimsmax_client.py -v`
6. ☐ `.claude/docs/baker-mcp-api.md` updated
7. ☐ Zero hardcoded keys; `CLAIMSMAX_API_KEY` read from env at startup; failing import if absent at boot is fine (matches existing env-var-required pattern)
8. ☐ Render env var set by AH1 before merge (separate Tier B action; not in B4 scope but B4's ship report should note completion blocker)

## Constraints (hard)

- **Never include the API key in any code, fixture, log, commit, or PR diff.** Env var only. PR review will hard-block on any `cmx_` literal.
- Surgical edits — touch `kbl/`, `tools/`, `tests/`, `.claude/docs/`, `migrations/`, plus minimum lines of `outputs/dashboard.py` (or wherever MCP tools register) to wire imports. Nothing else.
- Follow existing MCP tool registration pattern — do not invent a new pattern.
- Per repo hard rules: fault-tolerant or it doesn't ship. Compile-clean ≠ done.
- Do not implement `/ask` — placeholder only.

## Reporting back

Standard PR lifecycle:
1. Open PR against `main`, request review from AH1 via bus.
2. AH1 runs `/security-review` (mandatory per Lesson #52) + `/code-review`.
3. AH1 sets Render env var `CLAIMSMAX_API_KEY` before merge.
4. Merge on green.
5. Post-merge smoke: AH1 fires one live `baker_claimsmax_search` against the prod Render deploy and confirms result count > 0.

## References

- Full API spec: `~/Desktop/ClaimsMaxAPI.md`
- 1Password key: `op://Passwords/blu6mh64ytmb3u2dznpwfj4tqa/credential`
- Today's live tests (2026-05-16): `/search` 370 hits "Pagitsch defects" in 7.3s; `/investigate` 47 steps / 3.5min on TOP 18 cooling-ceiling question (returned full structured report).
- Vendor bug filed with Philip Vallen → Ellie Technologies same day re: `/ask` `temperature` deprecation.
