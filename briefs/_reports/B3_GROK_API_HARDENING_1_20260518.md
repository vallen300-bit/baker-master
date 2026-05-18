---
brief_id: GROK_API_HARDENING_1
worker: b3
dispatcher: lead
branch: b3/grok-api-hardening-1
head_commit: 41e2c6e
pr: 217
pr_url: https://github.com/vallen300-bit/baker-master/pull/217
opened_at: 2026-05-18T07:54Z
status: PR_OPEN — awaiting 4-gate review chain
bus_msgs:
  - dispatch: 378 (lead → b3)
  - pr_open: 381 (b3 → lead, topic pr-open/grok-api-hardening-1)
---

# B3 — GROK_API_HARDENING_1 ship report

## What shipped

5 fixes per `briefs/BRIEF_GROK_API_HARDENING_1.md`. All gated behind PR #217; nothing merged.

| ID | File(s) | Change |
|---|---|---|
| M1 | `tools/grok.py`, `.claude/docs/baker-mcp-api.md` | Rename `_reset_client_for_tests` → `reset_client_cache` + identity-preserving alias + module docstring + Key Rotation doc paragraph. |
| M3 | `kbl/grok_client.py`, `tools/grok.py` | `timeout` kwarg threaded through `_request` → `ask` / `x_search` / `web_search` → `httpx.Client.request`. Dispatcher validates `timeout_seconds` in `(0, 300]` (booleans rejected). 3 MCP inputSchemas extended. |
| M4 | `migrations/20260518_capability_sets_archive_no_trigger_patterns.sql` (NEW), `memory/store_back.py:_ensure_capability_sets_table` | UPDATE clears existing archive-row `trigger_patterns`; ADD CONSTRAINT `capability_sets_archive_no_trigger_patterns` enforces emptiness on archive rows. Bootstrap mirrors migration (Lesson #50). |
| MED | `kbl/grok_client.py:_shape_search_response`, new `_extract_inline_annotations` + `_merge_citations_by_url` | Merge top-level `payload["citations"]` with inline `output[*].content[*].annotations` `url_citation`/`citation` entries; dedup by URL; first-seen order. |
| LOW | `tests/test_grok_client.py`, `.claude/docs/baker-mcp-api.md` | Probabilistic-failure note above the BTC smoke assert + Smoke Testing doc paragraph. |

## Quality checkpoints

1. **pytest** — `python3.12 -m pytest tests/test_grok_client.py tests/test_capability_sets_constraints.py -v`
   ```
   ======================== 46 passed, 4 skipped in 0.18s =========================
   ```
   Breakdown: 28 prior Grok tests preserved; 13 new Grok tests added (2 M1 + 4 M3 + 5 MED + 2 live skips); 5 new M4 tests (2 live-PG round-trip + 3 parse-level). 4 skipped = 2 live Grok smokes (need `TEST_XAI_API_KEY`) + 2 live-PG round-trips (need `TEST_DATABASE_URL` or `NEON_API_KEY`).
2. **compile-clean** — `python3.12 -c "import py_compile; py_compile.compile('kbl/grok_client.py', doraise=True); py_compile.compile('tools/grok.py', doraise=True); py_compile.compile('memory/store_back.py', doraise=True); py_compile.compile('tests/test_grok_client.py', doraise=True); py_compile.compile('tests/test_capability_sets_constraints.py', doraise=True)"` → `ALL OK`.
3. **singletons** — `bash scripts/check_singletons.sh` → `OK: No singleton violations found.`
4. **Live migration apply (brief checkpoint #5)** — **NOT RUN locally.** No `TEST_DATABASE_URL` set, no `NEON_API_KEY` in 1Password, no Docker/Podman/Colima/local-PG on this builder. Parse-level checks confirmed:
   - Migration file shape (UP / DOWN sections, ordering of UPDATE before ADD CONSTRAINT verified after stripping SQL comments).
   - `_ensure_capability_sets_table` block contains the constraint name + UPDATE — drift detector PASSES.
   - Idempotency guards (`jsonb_array_length > 0` filter on UPDATE; `pg_constraint NOT EXISTS` on ADD CONSTRAINT) verified by reading.
   Live-PG round-trip will exercise via CI ephemeral Neon branch (per `tests/conftest.py::needs_live_pg`).

## Test deviation note

Brief specified +11 new tests (2 M1 + 4 M3 + 3 MED + 2 M4). Shipped 14:

- M1 = 2 ✓ (matches)
- M3 = 4 ✓ (matches)
- **MED = 5** (3 brief-spec + 2 bonus helper-coverage: `_extract_inline_annotations` non-url filter + `_merge_citations_by_url` non-URL-entry preservation; both touch the dedup/order invariants the brief calls out as constraints)
- **M4 = 5** (2 brief-spec live-PG round-trips + 3 bonus parse-level drift detectors: `test_migration_file_exists`, `test_migration_orders_update_before_constraint`, `test_store_back_bootstrap_in_sync_with_migration`; these are Lesson #50 hygiene and run without a DB).

Extra tests are additive — no existing test removed/renamed. If gates push back, the 5 bonus tests can be deleted in a fold; they are not load-bearing for the core fix.

## What was NOT touched (per brief `Do NOT touch`)

- `migrations/20260517_grok_capability_set.sql` (applied in prod)
- `migrations/20260517_claimsmax_capability_set.sql` (claimsmax archive row handled by same UPDATE filter)
- `tasks/lessons.md` (append-only; nothing to add)
- `_ops/skills/ai-head/SKILL.md`, matter desk `LONGTERM.md` (already updated this session in baker-vault)
- `capability_type='archive'` invariant on `grok_realtime` (preserved)
- `_CLIENT` / `_CLIENT_LOCK` lazy double-checked-lock pattern (preserved; rotation reset is additive)
- Cortex Phase 3 routing (`orchestrator/cortex_phase3_reasoner.py`, `orchestrator/capability_registry.py`) — out of scope

## Gate chain

Per brief + `_ops/skills/ai-head/SKILL.md` §Code-reviewer 2nd-pass Protocol trigger #2 (DB schema change):

1. AH2 static lane (cross-lane review).
2. AH2 `/security-review`.
3. `code-architecture-reviewer`.
4. `feature-dev:code-reviewer` 2nd-pass — **MANDATORY**.

All four must clear before merge. Bus-post `lead` already fired on PR open; ship-post will follow on merge.

## Bus posts

- Dispatch: msg #378 (`lead` → `b3`, topic `dispatch/grok-api-hardening-1`) — claimed implicitly by this PR.
- PR open: msg #381 (`b3` → `lead`, topic `pr-open/grok-api-hardening-1`).
- Ship: deferred until merge — topic `ship/grok-api-hardening-1`.
