# Code Brisen #1 — Pending Task

**From:** AI Head (Team 1 — Meta/Persistence)
**To:** Code Brisen #1
**Task posted:** 2026-04-23
**Status:** OPEN — `KBL_INGEST_ENDPOINT_1` (M0 quintet row 3 — single HTTP chokepoint for wiki writes)

**Supersedes:** prior `MAC_MINI_WRITER_AUDIT_1` task — shipped as PR #53, merged `327dbab` 2026-04-23. Mailbox cleared.

---

## Brief-route note (charter §6A)

Full `/write-brief` 6-step protocol. Brief at `briefs/BRIEF_KBL_INGEST_ENDPOINT_1.md`.

Closes M0 row 3 — unblocks downstream M1 seed migration, M2 sentinel auto-stubs, M3 Cortex-3T reasoning writes. Reuses PR #51's `atomic_director_action` (CHANDA #2). Reuses PR #52's VAULT.md §2 schema. Bundles Gold-mirror staging path per OPERATING.md row 3 "Includes Gold mirror integration."

---

## Context (TL;DR)

Build the **single HTTP chokepoint** through which every wiki write flows. `POST /api/kbl/ingest` on Baker's FastAPI app:
- Validates 7-field frontmatter (VAULT.md §2) + 3-way taxonomy + slug format
- Checks MATTER slug in `slugs.yml` (via existing `kbl.slug_registry.is_canonical`). Person/entity format-only (registry loaders deferred to `KBL_PEOPLE_ENTITY_LOADERS_1`).
- Writes `wiki_pages` UPSERT + `baker_actions` ledger atomically via `atomic_director_action` (PR #51). CHANDA #2 preserved.
- Post-atomic: Qdrant vector upsert (non-blocking), Gold-mirror when `voice=gold` (stages file to `vault_scaffolding/live_mirror/v1/<slug>.md` for AI Head SSH-mirror — CHANDA #9 preserved).

## Action

Read `briefs/BRIEF_KBL_INGEST_ENDPOINT_1.md` end-to-end. 3 features with fully copy-pasteable content:

1. **NEW** `kbl/ingest_endpoint.py` — logic module. `ingest()`, `validate_frontmatter()`, `validate_slug_in_registry()`, `IngestResult`, `KBLIngestError`. ~250 LOC. Verbatim in brief Feature 1.

2. **MODIFIED** `outputs/dashboard.py` — add `KBLIngestRequest` Pydantic class (near existing request models) + `@app.post("/api/kbl/ingest", ...)` handler (near `/api/matters` block, ~line 1104). ~25 LOC added. Verbatim in brief Feature 2.

3. **NEW** `tests/test_kbl_ingest_endpoint.py` — 13 hermetic sqlite3 tests (7 validation + 6 flow). Uses `patch_sqlite_wiki_sql` fixture to translate `%s` → `?` at cursor-execute level. Fault-injection pattern matches `test_ledger_atomic.py`. ~280 LOC. Verbatim in brief Feature 3.

**Non-negotiable invariants:**
- Do NOT touch `scripts/ingest_vault_matter.py` (M1 cutover).
- Do NOT touch `memory/store_back.py`, `invariant_checks/ledger_atomic.py`, `kbl/slug_registry.py`, `models/cortex.py` — all reused as-is.
- Do NOT write to `baker-vault/` (CHANDA #9). Gold mirror stages in baker-master under `vault_scaffolding/live_mirror/v1/`.
- `_put_conn(conn)` must run exactly once on every return/raise path in `ingest()` — success, KBLIngestError re-raise, generic exception.
- Inline (lazy) imports for `SentinelStoreBack`, `atomic_director_action`, `_embed_text`, `_get_qdrant` per `cortex.py:18-24` precedent — avoid circular imports.
- Person slug rule = firstname-lastname regex (`PERSON_SLUG_RE`) enforced at frontmatter validation.

**Test env requirement:** `test_validate_slug_in_registry_rejects_unknown_matter` needs `BAKER_VAULT_PATH=/Users/dimitry/baker-vault` set at test run. If your env lacks it, either export locally before `pytest` OR add a pytest fixture/conftest that sets it. Either is fine; note the choice in ship report.

## Ship gate (literal output required in ship report)

**Baseline first** — `pytest tests/ 2>&1 | tail -3` on `main` BEFORE branching.

After implementation:

```bash
# 1. Python syntax (3 files)
python3 -c "import py_compile; py_compile.compile('kbl/ingest_endpoint.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('tests/test_kbl_ingest_endpoint.py', doraise=True)"

# 2. Import smoke
python3 -c "from kbl.ingest_endpoint import ingest, KBLIngestError, validate_frontmatter, IngestResult; print('OK')"

# 3. Route registered
grep -n "/api/kbl/ingest" outputs/dashboard.py              # expect 1

# 4. Pydantic model exists
grep -n "class KBLIngestRequest" outputs/dashboard.py       # expect 1

# 5. Auth wired on the route
grep -B1 "/api/kbl/ingest" outputs/dashboard.py | grep -c "verify_api_key"  # expect 1

# 6. New tests in isolation
pytest tests/test_kbl_ingest_endpoint.py -v 2>&1 | tail -20   # expect 13 passed

# 7. Full-suite regression
pytest tests/ 2>&1 | tail -3                                  # +13 vs baseline, 0 regressions

# 8. Singleton hook
bash scripts/check_singletons.sh                              # OK

# 9. No baker-vault writes
git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
```

**No "pass by inspection"** (per `feedback_no_ship_by_inspection.md`). Paste literal outputs.

## Ship shape

- **PR title:** `KBL_INGEST_ENDPOINT_1: POST /api/kbl/ingest single wiki-write chokepoint (CHANDA #2 atomic + Gold mirror)`
- **Branch:** `kbl-ingest-endpoint-1`
- **Files:** 3 — 2 new + 1 modified.
- **Commit style:** one squash-ready commit. `kbl(ingest): single chokepoint endpoint + atomic wiki_pages/ledger/Qdrant + Gold mirror staging`
- **Ship report:** `briefs/_reports/B1_kbl_ingest_endpoint_1_20260423.md`. Include all 9 ship-gate outputs literal + baseline pytest line + `git diff --stat` + explicit line-count per file.

**Tier A auto-merge on B3 APPROVE + green CI** (standing per charter §3).

## Out of scope (explicit)

- **Do NOT** ship `kbl/people_registry.py` / `kbl/entity_registry.py` loaders — follow-on `KBL_PEOPLE_ENTITY_LOADERS_1`.
- **Do NOT** implement the Gold comment workflow (hybrid C, Proposed Gold isolation, DV-only initials) — separate brief `BRIEF_GOLD_COMMENT_WORKFLOW_1`. This brief only stages a file when `voice=gold`; authorship + comment-merge semantics are out of scope.
- **Do NOT** migrate `scripts/ingest_vault_matter.py` callers to the new endpoint — M1 brief.
- **Do NOT** touch `baker_raw_query` / `baker_raw_write` MCP endpoints.
- **Do NOT** deprecate `_seed_wiki_from_view_files` — it's empty-DB bootstrap only.
- **Do NOT** add `.github/workflows/` CI.
- **Do NOT** add `baker-wiki` Qdrant collection bootstrap — if the collection doesn't exist at first ingest, the warning log captures it and AI Head adds a tiny one-off collection-init brief. Out of this brief's scope.
- **Do NOT** touch `CHANDA.md` / `CHANDA_enforcement.md` — no invariant changes; reuses existing #2 detector.
- **Do NOT** touch `triggers/embedded_scheduler.py` — shared-file hotspot.

## Timebox

**3–3.5h.** If >5h, stop and report — likely sqlite3 SQL-translation friction (ON CONFLICT + %s → ?) or a route-registration conflict in dashboard.py.

**Working dir:** `~/bm-b1`.

---

**Dispatch timestamp:** 2026-04-23 post-M0-row-2-closure (Team 1, M0 quintet row 3 — KBL ingest endpoint)
**Team:** Team 1 — Meta/Persistence
**Sequence:** ENFORCEMENT_1 (#45) → GUARD_1 (#49) → LEDGER_ATOMIC_1 (#51) → KBL_SCHEMA_1 (#52) → MAC_MINI_WRITER_AUDIT_1 (#53) → **KBL_INGEST_ENDPOINT_1 (this)** → (remaining M0: PROMPT_CACHE_AUDIT_1, CITATIONS_API_SCAN_1)
