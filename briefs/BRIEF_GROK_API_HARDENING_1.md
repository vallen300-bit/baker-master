# BRIEF: GROK_API_HARDENING_1 — close 5 nits from PR #214 gate chain + prod smoke

## Context

PR #214 (`GROK_API_CAPABILITY_1`) shipped 2026-05-17 — baker-master squash `99db952c`, prod-live on `8d8adf99` since 15:59Z. Full prod smoke confirmed end-to-end functional (€0.018 of €250 burned). 4-gate review chain (AH2 static · AH2 `/security-review` · code-architecture-reviewer · feature-dev:code-reviewer 2nd-pass) cleared with 5 known non-blocking nits queued for a follow-up hardening pass. Director ratified filing this brief 2026-05-17 evening after seeing the propagation land (anchor: paired handover `session_handover_2026-05-17_late_aihead_a_grok_propagation_shipped.md`; Director quote "file grok api hardening now").

This brief closes the 5 nits in one B-code dispatch. The capability is operationally healthy today; this is quality-of-implementation work, not incident response.

## Estimated time: ~3-4h
## Complexity: Medium (5 fixes; M4 is the trickiest — migration-vs-bootstrap drift surface)
## Prerequisites: PR #214 merged (confirmed); `XAI_API_KEY` on Render (confirmed); `grok_realtime` row in `capability_sets` (confirmed via migration `20260517_grok_capability_set.sql`).

---

## Fix 1 (M1): document + harden the in-process client cache for `XAI_API_KEY` rotation

### Problem

`tools/grok.py:36-52` holds a module-level `_CLIENT: Optional[GrokClient]` initialized lazily on first dispatch. `GrokClient.__init__` reads `os.environ.get("XAI_API_KEY", "")` at construction time and stores it as instance state (`kbl/grok_client.py:118-123`). If Render env-var `XAI_API_KEY` rotates while the worker is running, the cached `_CLIENT` keeps using the old key until the next worker restart. Detection signal: 401s in logs after a key rotation.

A test-only hook exists at `tools/grok.py:55-64` (`_reset_client_for_tests`), but it is:
- Named `_for_tests`, signalling "not for production use".
- Undocumented in `.claude/docs/baker-mcp-api.md`.
- Not exposed as an MCP tool or HTTP endpoint, so there is no callable surface from a running worker.

### Current state

- `tools/grok.py:55-64` — `_reset_client_for_tests()` exists, closes the cached client + nulls the global.
- `_get_client()` rebuilds the client (and re-reads `XAI_API_KEY`) on next call after a reset.
- The mechanism is correct; only the discoverability + naming are wrong.

### Implementation

1. **Rename** `_reset_client_for_tests` → `reset_client_cache` in `tools/grok.py`. Keep a `_reset_client_for_tests = reset_client_cache` alias at the bottom of the module so the existing test (`tests/test_grok_client.py` does not currently call this hook by name but future tests might) and any external callers continue to work.
2. **Add a module-level docstring paragraph** explaining the rotation pattern: "After rotating `XAI_API_KEY` on Render, call `tools.grok.reset_client_cache()` (e.g. from a small admin endpoint or one-shot Render shell `python3 -c`) to force the next dispatch to re-read the env var. Otherwise the cached client survives until the worker restarts."
3. **Add a paragraph to `.claude/docs/baker-mcp-api.md` § "Grok real-time tools (3)"** documenting the rotation pattern under a new "Key rotation" sub-bullet so matter Desks (and AH1) know the operational sequence: `op item edit` → Render PUT → `reset_client_cache()` OR worker restart.

### Code snippet

```python
# tools/grok.py (replaces lines 55-64 + adds docstring fragment near module top)

def reset_client_cache() -> None:
    """Drop the cached GrokClient. Call after rotating XAI_API_KEY on Render
    so the next dispatch rebuilds the client and reads the fresh env var.

    Safe to call from any thread; no-op if no client is cached.
    """
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            try:
                _CLIENT.close()
            except Exception:
                pass
        _CLIENT = None


# Backwards-compat alias for any external callers that imported the underscore name.
_reset_client_for_tests = reset_client_cache
```

### Key constraints

- Do NOT change `GrokClient.__init__` env-read behaviour — it correctly raises `GrokAuthError` when `XAI_API_KEY` is empty.
- Do NOT add a per-call env-read in `_get_client()` — that would defeat the connection-pool reuse the cache is there to provide (Live Search calls take 5-20s; rebuilding `httpx.Client` per call burns TLS).
- Backwards-compat alias is mandatory — silent renames break callers (Lesson #4 / #12 patterns).

### Verification

- New test in `tests/test_grok_client.py`: `test_reset_client_cache_picks_up_rotated_key` — sets `XAI_API_KEY=key-1`, calls `_get_client()`, asserts `Authorization` header contains `key-1`; rotates `XAI_API_KEY=key-2`, calls `_get_client()` (still cached → still `key-1`); calls `reset_client_cache()`, calls `_get_client()`, asserts header now contains `key-2`.
- New test: `test_reset_client_cache_alias_still_works` — asserts `tools.grok._reset_client_for_tests is tools.grok.reset_client_cache` (identity).

---

## Fix 2 (M3): expose per-call `timeout_seconds` override at MCP surface

### Problem

`kbl/grok_client.py:113` defaults `timeout=60.0` and bakes it into `httpx.Client(timeout=self._timeout)` at construction. Per-call timeout is not overridable. gate-3 (code-architecture-reviewer) flagged this as "most important architecture concern not to miss": long-running Live Search calls (X feed sweeps, multi-domain web search) can stack against the default and starve other dispatches sharing the same worker.

### Current state

- `GrokClient.__init__(timeout=60.0)` → `httpx.Client(timeout=...)` (line 132).
- `_request()` calls `self._http_client.request(method, url, headers=..., json=...)` — no `timeout` kwarg threaded through.
- Three MCP tools (`baker_grok_x_search` / `baker_grok_web_search` / `baker_grok_ask`) accept no `timeout_seconds` arg in their inputSchemas.

### Implementation

1. **`kbl/grok_client.py:_request()`** — accept an optional `timeout: Optional[float] = None` kwarg; pass it to `self._http_client.request(...)` only when not `None`. httpx accepts per-request `timeout` overrides via the `timeout` kwarg on `request()`.
2. **`kbl/grok_client.py:ask` / `x_search` / `web_search`** — each accepts an optional `timeout: Optional[float] = None` kwarg, forwards it to `self._request("POST", "responses", json=body, timeout=timeout)`.
3. **`tools/grok.py:dispatch_grok`** — reads `args.get("timeout_seconds")`, validates it is a positive number ≤ 300 (cap; defensive against caller passing 99999), forwards to client method calls. Invalid value → return `"Error: timeout_seconds must be a positive number ≤ 300"`.
4. **`tools/grok.py:GROK_TOOLS` inputSchemas** — add `timeout_seconds: {"type": "number", "description": "Per-call timeout in seconds (default 60, max 300).", "minimum": 1, "maximum": 300}` to all three tool schemas.

### Code snippet — request wrapper

```python
# kbl/grok_client.py — modified _request signature + body lines 154-203

def _request(
    self,
    method: str,
    path: str,
    *,
    json: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> dict:
    """Single HTTP round-trip with retry on 429.

    ``timeout`` overrides the client default for this call only; pass None
    to use ``self._timeout``. Capped server-side at 300s (caller's
    responsibility — _request trusts the passed value).
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            request_kwargs = {
                "headers": self._headers(),
                "json": json,
            }
            if timeout is not None:
                request_kwargs["timeout"] = timeout
            resp = self._http_client.request(
                method,
                self._url(path),
                **request_kwargs,
            )
        except httpx.TimeoutException as e:
            raise GrokTransportError(f"timeout calling {method} {path}: {e}") from e
        # ... rest of body unchanged ...
```

### Key constraints

- Cap at 300s at the dispatcher (`tools/grok.py`), NOT in the client. Client is reusable in non-MCP contexts where higher timeouts may be legitimate.
- Do NOT change the default 60s — existing callers depend on it.
- Validation in `dispatch_grok` must reject `0`, negative, non-numeric, and `> 300` values; emit a clear `Error:` string per the existing dispatcher contract (line 252 pattern).

### Verification

- New test: `test_dispatch_grok_passes_timeout_seconds_to_client` — monkeypatch `_get_client` with a mock that records calls; dispatch with `{"prompt": "x", "timeout_seconds": 30}`; assert the client method was called with `timeout=30`.
- New test: `test_dispatch_grok_rejects_invalid_timeout` — three sub-cases: negative, zero, > 300, non-numeric. Each returns `"Error: timeout_seconds"` prefix and does NOT invoke the client.
- New test: `test_grok_client_request_passes_timeout_to_httpx` — mock `httpx.Client.request`, call `client.ask("x", timeout=10)`, assert `request` was called with `timeout=10` kwarg.
- New test: `test_grok_client_default_timeout_when_omitted` — no timeout passed, mock asserts NO `timeout` kwarg sent (so httpx uses the client default).

---

## Fix 3 (M4): DB-level guard against `trigger_patterns` hijack on `capability_type='archive'` rows

### Problem

`capability_sets.trigger_patterns` is a `jsonb` column matched against incoming signals by `orchestrator/capability_registry.py:78-100` for `capability_type='domain'` rows that participate in Cortex Phase 3 routing. The `grok_realtime` row is correctly typed `'archive'` (excluded from Phase 3 auto-routing per the C1 fix mirrored from ClaimsMax PR #213). HOWEVER: the row's `trigger_patterns` column currently contains `["grok", "x search", "twitter search", "real-time web", "realtime news"]` (per `migrations/20260517_grok_capability_set.sql:51`). If any future operator (or migration bug) ever flips `capability_type` to `'domain'`, those generic patterns would immediately hijack matter routing — generic words like `"grok"` and `"real-time web"` are not safe for routing.

### Current state

- No DB-level constraint enforces empty `trigger_patterns` on `archive`-type rows.
- `memory/store_back.py:2811-2899` (`_ensure_capability_sets_table`) bootstraps the table; no CHECK constraint.
- The `claimsmax_archive` row (PR #213 ROUND_2) has the same shape — also vulnerable. **Fix covers both rows.**

### Implementation

Two-step migration (data fix first, then constraint) — otherwise the CHECK fails to apply against existing data.

**Step A — `migrations/20260518_capability_sets_archive_no_trigger_patterns.sql`**:

```sql
-- == migrate:up ==
-- GROK_API_HARDENING_1 (M4) — defense in depth against future capability_type
-- flip on archive rows. Strip trigger_patterns from any 'archive'-type row,
-- then add a CHECK constraint that prevents future writes from carrying
-- patterns on archive rows.
--
-- Why: trigger_patterns are routing-signals for Cortex Phase 3 (capability_type='domain').
-- Archive rows are MCP-invoked, not Phase-3-routed. The patterns are dead code on
-- archive rows but become live routing-hijackers the moment capability_type flips.
-- Patterns like "grok", "x search", "claimsmax" are too generic to safely re-activate.
--
-- Companion bootstrap update in memory/store_back.py:_ensure_capability_sets_table
-- ensures fresh databases land with the same constraint.

-- Step 1: clear patterns on existing archive rows. Idempotent.
UPDATE capability_sets
SET trigger_patterns = '[]'::jsonb,
    updated_at = NOW()
WHERE capability_type = 'archive'
  AND trigger_patterns IS NOT NULL
  AND jsonb_array_length(trigger_patterns) > 0;

-- Step 2: add the CHECK constraint. Idempotent via NOT EXISTS guard.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'capability_sets_archive_no_trigger_patterns'
    ) THEN
        ALTER TABLE capability_sets
        ADD CONSTRAINT capability_sets_archive_no_trigger_patterns
        CHECK (
            capability_type <> 'archive'
            OR trigger_patterns IS NULL
            OR jsonb_array_length(trigger_patterns) = 0
        );
    END IF;
END $$;

-- == migrate:down ==
-- ALTER TABLE capability_sets DROP CONSTRAINT IF EXISTS capability_sets_archive_no_trigger_patterns;
-- (No restoration of stripped patterns on rollback — they were dead code anyway.)
```

**Step B — `memory/store_back.py:_ensure_capability_sets_table`** — add the same CHECK constraint via `ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS` pattern. Insert after the existing `CREATE INDEX` block at line 2841, before the `ALTER TABLE ... ADD COLUMN IF NOT EXISTS use_thinking` line:

```python
# memory/store_back.py — insert after line 2841

# GROK_API_HARDENING_1 (M4): archive-type rows must not carry trigger_patterns.
# Generic patterns on a row whose capability_type flips back to 'domain' would
# hijack Cortex Phase 3 routing.
cur.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'capability_sets_archive_no_trigger_patterns'
        ) THEN
            ALTER TABLE capability_sets
            ADD CONSTRAINT capability_sets_archive_no_trigger_patterns
            CHECK (
                capability_type <> 'archive'
                OR trigger_patterns IS NULL
                OR jsonb_array_length(trigger_patterns) = 0
            );
        END IF;
    END $$;
""")
```

### Key constraints

- **Migration order matters:** Step 1 (UPDATE) MUST run before Step 2 (ALTER TABLE ADD CONSTRAINT), otherwise the constraint validation fails on existing archive rows and the migration aborts. The SQL above is structured to run them sequentially in one file — DO blocks execute in declaration order within a migration.
- **Bootstrap must match migration** (Lesson #50 migration-vs-bootstrap drift). Both update in same brief.
- **`claimsmax_archive` row gets cleaned by the same UPDATE** — verify post-migration that ClaimsMax MCP tools still dispatch correctly (they invoke directly via `baker_claimsmax_*` MCP names, NOT via `trigger_patterns` matching). Verification SQL below.
- **Do NOT modify the seed migration** `20260517_grok_capability_set.sql` — already applied in prod; editing applied migrations is forbidden per repo hard rule. The new migration `20260518_*` overrides the seed's pattern list via UPDATE.

### Verification

- New test: `test_capability_sets_archive_no_trigger_patterns_constraint_blocks_insert` — `tests/test_capability_sets_constraints.py` (new file). Bootstrap the schema (via `_ensure_capability_sets_table()` against a temp test DB), attempt to `INSERT INTO capability_sets` with `capability_type='archive'` AND non-empty `trigger_patterns` → expect `psycopg2.errors.CheckViolation`. Then attempt the same insert with `trigger_patterns='[]'::jsonb` → succeeds.
- New test: `test_capability_sets_domain_can_still_have_trigger_patterns` — same setup, INSERT with `capability_type='domain'` and `trigger_patterns=["legal", "tax"]` → succeeds.
- Post-migration verification SQL (in brief Verification SQL section below).

---

## Fix 4 (MED): citation extraction from `output[*].content[*].annotations` (xAI Agent Tools API inline format)

### Problem

`kbl/grok_client.py:_shape_search_response` (line 346-372) reads citations from `payload.get("citations")` only (top-level). xAI's Agent Tools API delivers structured citations inline in `output[*].content[*].annotations` with `[[1]](URL)` format on `web_search` calls — this is what prod smoke 5 (BTC forced real-time) revealed: the model emitted inline citations in summary text but the structured `citations[]` field returned by Baker came back empty. Result: matter Desks expecting `citations[]` for downstream rendering (links, footnotes) see an empty list while seeing inline-summary URLs in the text.

Severity MED — operationally visible to any Desk that wants the structured `citations[]` field. Not a security issue.

### Current state

- `_shape_search_response` reads `payload.get("citations") or []`.
- `_flatten_output_text` walks `output[*].content[*]` for text blocks but does NOT extract `annotations`.
- Annotations live alongside text blocks: `{"type": "output_text", "text": "...", "annotations": [{"type": "url_citation", "url": "...", "title": "..."}]}` per xAI docs.

### Implementation

**`kbl/grok_client.py`** — `_shape_search_response`:

```python
def _shape_search_response(payload: dict, *, model: str, kind: str) -> dict:
    """Normalize a Live Search /responses payload to a slim search result dict.
    ... (existing docstring) ...

    Citations are merged from two sources:
      1) top-level ``payload["citations"]`` (older response shape)
      2) inline ``output[*].content[*].annotations`` (Agent Tools API, current shape)
    De-duplicated by URL to avoid double-counting when xAI emits both.
    """
    top_level_citations = payload.get("citations") or []
    inline_citations = _extract_inline_annotations(payload.get("output") or [])
    citations = _merge_citations_by_url(top_level_citations, inline_citations)
    summary = _flatten_output_text(payload.get("output") or [])
    # ... rest unchanged using `citations` instead of bare `payload.get("citations")` ...
```

**New helpers** (append below existing helpers):

```python
def _extract_inline_annotations(output: list[Any]) -> list[dict]:
    """Extract URL citation annotations from output[*].content[*].annotations.

    xAI Agent Tools API attaches citations as ``{"type": "url_citation",
    "url": "...", "title": "...", "start_index": N, "end_index": M}`` on each
    output_text block that references a search hit. We flatten them into a
    single ordered list, preserving first-seen order across blocks.
    """
    out: list[dict] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            annotations = block.get("annotations")
            if not isinstance(annotations, list):
                continue
            for ann in annotations:
                if not isinstance(ann, dict):
                    continue
                if ann.get("type") not in ("url_citation", "citation"):
                    continue
                out.append(ann)
    return out


def _merge_citations_by_url(*sources: list[Any]) -> list[Any]:
    """Merge multiple citation lists, deduplicating by ``url``.

    Preserves first-seen order. Entries without a discoverable URL are kept
    (they may be plain strings or malformed dicts) since dropping them silently
    would lose data. String entries are compared by their own value as URL.
    """
    seen: set[str] = set()
    out: list[Any] = []
    for src in sources:
        for c in src:
            url = ""
            if isinstance(c, str):
                url = c
            elif isinstance(c, dict):
                url = str(c.get("url") or c.get("link") or "")
            if url and url in seen:
                continue
            if url:
                seen.add(url)
            out.append(c)
    return out
```

### Key constraints

- **De-duplicate by URL** — xAI may return the same citation in both top-level + inline. Counting it twice would mislead matter Desks tracking source breadth.
- **Preserve first-seen ordering** — citations appear in the order Grok cited them in the summary. Reordering breaks `[1]`/`[2]` mapping if a Desk renders footnotes.
- **Tweet vs web citation shapes are still post-processed by `_shape_tweet_citation` / `_shape_web_citation`** — the merge happens BEFORE the shaping pass, so both inline + top-level entries get the same projection.
- Backwards-compat: when `annotations` is absent (older response payloads), behaviour is identical to current code.

### Verification

- New test: `test_web_search_extracts_inline_annotations` — response body with empty top-level `citations` but `output[0].content[0].annotations = [{"type": "url_citation", "url": "https://example.com/a", "title": "A"}]` → `out["citations"]` has 1 entry with `url="https://example.com/a"`, `title="A"`.
- New test: `test_web_search_merges_top_level_and_inline_dedup` — response has `citations=["https://example.com/a"]` AND inline `annotations=[{"url": "https://example.com/a", "title": "A"}, {"url": "https://example.com/b", "title": "B"}]` → final `out["citations"]` has exactly 2 entries (`a` from top-level kept, `a` from inline dropped, `b` from inline kept). Order preserved.
- New test: `test_x_search_extracts_inline_annotations` — same pattern but for `kind="x"`; `out["tweets"]` populated from inline.
- Existing test `test_web_search_citations_are_shaped` still passes (top-level path unchanged in behaviour).

---

## Fix 5 (LOW): document BTC smoke probabilistic-failure mode

### Problem

`tests/test_grok_client.py::test_live_grok_web_search_smoke` (line 542-569) uses a date-current BTC query to force the Live Search tool to fire. Model occasionally answers from training inference rather than firing the tool — when this happens, `citations=[]` and the test fails. gate-4 flagged this as a probabilistic false-positive class during PR #214 review.

Severity LOW — only fires when an operator runs the env-gated smoke (`TEST_XAI_API_KEY`); CI never runs it; production code path is unaffected.

### Implementation

1. **Inline comment in `tests/test_grok_client.py`** above the BTC assertion: explain the probabilistic nature, the workaround (re-run; if 2+ runs fail in a row, suspect a real wire-format regression).
2. **Paragraph in `.claude/docs/baker-mcp-api.md` § "Grok real-time tools (3)"** under a new "Smoke testing" sub-bullet explaining: live smoke test exists at `tests/test_grok_client.py::test_live_grok_web_search_smoke`, env-gated, may probabilistically false-positive when the model answers date-current queries from training instead of firing the search tool, retry once before treating a failure as a wire-format regression.

### Code snippet

```python
# tests/test_grok_client.py — insert above line 564 (the citations >= 1 assert)

# Probabilistic-failure note: the model may occasionally answer date-current
# queries from training rather than firing the web_search tool. A single
# failure here is NOT proof of a wire-format regression — re-run once before
# investigating. Two consecutive failures suggest a real wire issue.
assert len(out["citations"]) >= 1, (
    "live grok web_search returned zero citations — the web_search tool did "
    "not execute (model answered from inference). Wire-format regression."
)
```

### Verification

- Diff visible on the file (no new test for documentation-only change).

---

## Files Modified

- `kbl/grok_client.py` — M3 (`_request` + `ask` / `x_search` / `web_search` accept optional `timeout`); MED (`_shape_search_response` + new `_extract_inline_annotations` + new `_merge_citations_by_url` helpers)
- `tools/grok.py` — M1 (rename `_reset_client_for_tests` → `reset_client_cache`, keep alias, add docstring); M3 (`dispatch_grok` reads + validates `timeout_seconds` arg, threads to client; 3 inputSchemas extended)
- `memory/store_back.py` — M4 (CHECK constraint added to `_ensure_capability_sets_table` bootstrap, ~line 2842)
- `migrations/20260518_capability_sets_archive_no_trigger_patterns.sql` — M4 NEW migration (UPDATE existing rows + ADD CONSTRAINT)
- `tests/test_grok_client.py` — new tests for M1 (2), M3 (4), MED (3); LOW inline comment
- `tests/test_capability_sets_constraints.py` — NEW file, 2 tests for M4
- `.claude/docs/baker-mcp-api.md` — M1 key-rotation paragraph + LOW smoke-probabilistic paragraph in §Grok

## Do NOT Touch

- `migrations/20260517_grok_capability_set.sql` — already applied in prod; editing applied migrations forbidden per repo hard rule.
- `migrations/20260517_claimsmax_capability_set.sql` — claimsmax archive row is fixed by the same M4 UPDATE (covers both rows by `capability_type='archive'` filter); migration file itself unchanged.
- `tasks/lessons.md` — append-only; nothing to add from this brief.
- `_ops/skills/ai-head/SKILL.md` — already updated this session (Grok row landed in commit `704495b`).
- 7 matter desk LONGTERM.md files — already updated this session.
- `capability_type='archive'` invariant on the `grok_realtime` row — preserved by design.
- `_CLIENT` / `_CLIENT_LOCK` global identity — keep the lazy double-checked-lock pattern; rotation reset is a separate operation, not a replacement.
- Cortex Phase 3 routing (`orchestrator/cortex_phase3_reasoner.py`, `orchestrator/capability_registry.py`) — out of scope; archive rows already excluded.

## Quality Checkpoints

1. `pytest tests/test_grok_client.py -v` — 28 existing tests still pass; 9 new tests (2 M1 + 4 M3 + 3 MED) all pass.
2. `pytest tests/test_capability_sets_constraints.py -v` — 2 new tests pass.
3. `python3 -c "import py_compile; py_compile.compile('kbl/grok_client.py', doraise=True); py_compile.compile('tools/grok.py', doraise=True); py_compile.compile('memory/store_back.py', doraise=True)"` — clean.
4. `bash scripts/check_singletons.sh` — unaffected; no new `SentinelRetriever` / `SentinelStoreBack` instantiations.
5. Apply migration locally to a clean test DB AND a copy-of-prod test DB: confirm the UPDATE clears the 2 existing archive rows' `trigger_patterns` and the CHECK constraint applies without error.
6. After Render deploy: query `/api/capabilities?type=archive` — both `grok_realtime` + `claimsmax_archive` rows still appear, `trigger_patterns` = `[]`, `active=true`, MCP tools still callable.
7. `baker_grok_ask` live-smoke call with `matter_slug="theailogy"` — confirms cost-monitor still attributes correctly.
8. `baker_grok_web_search` live-smoke call with a clearly-date-current query (`"What is today's BTC/USD spot price? Cite at least one source."`) — confirms `citations[]` now populated either from top-level OR from inline annotations (whichever xAI returns this time).
9. `baker_grok_ask` with `timeout_seconds=5` and a deliberately-long prompt — confirms timeout fires; expect `Grok: timeout calling POST responses` error string returned.
10. After rotating `XAI_API_KEY` on Render (NOT executed as part of this brief — separate Tier-B): call a small admin entrypoint or shell `python3 -c "from tools.grok import reset_client_cache; reset_client_cache()"` and verify next dispatch succeeds with the new key.

## Verification SQL

```sql
-- Confirm M4 UPDATE landed: both archive rows have empty trigger_patterns.
SELECT slug, capability_type, trigger_patterns
FROM capability_sets
WHERE capability_type = 'archive'
ORDER BY slug;
-- Expected: 2 rows (claimsmax_archive, grok_realtime), trigger_patterns = []

-- Confirm M4 CHECK constraint exists.
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conname = 'capability_sets_archive_no_trigger_patterns';
-- Expected: 1 row showing the CHECK definition.

-- Negative test: a manual INSERT with archive + patterns should fail.
-- (Run in psql, not in a real session — illustrative only.)
-- INSERT INTO capability_sets (slug, name, capability_type, domain, role_description, tools, output_format, trigger_patterns, active)
-- VALUES ('test_archive_block', 't', 'archive', 'd', 'r', '[]'::jsonb, 'json', '["test"]'::jsonb, false);
-- Expected: ERROR — new row violates check constraint capability_sets_archive_no_trigger_patterns
```

## Reporting

- `dispatched_by: lead` (AH1-Terminal). Workers obey reply-to-sender rule (BUS_REPLY_TO_SENDER_RULE_1 landed baker-vault `9562cad`).
- Bus-post `lead` on PR open with topic `pr-open/grok-api-hardening-1`.
- Bus-post `lead` on ship-report with topic `ship/grok-api-hardening-1`.
- Standard 4-gate review chain applies: AH2 static + AH2 `/security-review` + code-architecture-reviewer + `feature-dev:code-reviewer` 2nd-pass. Migration touches DB schema → 2nd-pass MANDATORY per SKILL.md §Code-reviewer 2nd-pass Protocol trigger #2.

## Cross-references

- PR #214 squash `99db952c` (baker-master); Render deploy `8d8adf99`.
- PINNED §Q (paired handover anchor): `_ops/agents/aihead1/PINNED.md` (delete §Q when this brief's PR merges).
- Paired handover: `_ops/agents/aihead1/handover-archive/2026-05/session_handover_2026-05-17_late_aihead_a_grok_propagation_shipped.md`.
- AID architect-review on the same 5 nits: bus #376 (informer/grok-capability-shipped) — AID may surface delta-vs-AH1 framing; fold any disagreement before brief dispatches to a B-code.
- Canonical usage spec: `.claude/docs/baker-mcp-api.md` § "Grok real-time tools (3)" — update under M1 (key rotation) + LOW (smoke probabilistic).
- ClaimsMax archive precedent: PR #213 ROUND_2 (commit `3cbc287`) — same `capability_type='archive'` invariant.

## Lessons referenced

- Lesson #50 (migration-vs-bootstrap drift) — M4 enforces matching bootstrap + migration.
- Lesson #68 (cost-governor wiring pattern, written this session) — pre-call `check_circuit_breaker` + post-call `log_api_cost` already in `tools/grok.py:206-279`; preserve unchanged.
- `feedback_b_code_preflight_needs_ah1_verification.md` — any spec divergence the implementing B-code surfaces must be independently verified by AH1 before greenlight, not trusted-by-default.
