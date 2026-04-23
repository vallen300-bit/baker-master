# Ship Report — B1 KBL_INGEST_ENDPOINT_1

**Date:** 2026-04-23
**Agent:** Code Brisen #1 (Team 1 — Meta/Persistence)
**Brief:** `briefs/BRIEF_KBL_INGEST_ENDPOINT_1.md`
**PR:** https://github.com/vallen300-bit/baker-master/pull/55
**Branch:** `kbl-ingest-endpoint-1`
**Commit:** `9de5694 kbl(ingest): single chokepoint endpoint + atomic wiki_pages/ledger/Qdrant + Gold mirror staging`
**Status:** SHIPPED — awaiting B3 review / Tier A auto-merge
**Sequence:** ENFORCEMENT_1 (#45) → GUARD_1 (#49) → LEDGER_ATOMIC_1 (#51) → KBL_SCHEMA_1 (#52) → MAC_MINI_WRITER_AUDIT_1 (#53) → **KBL_INGEST_ENDPOINT_1 (this, #55 — M0 row 3)**

---

## Scope

M0 quintet row 3. Single HTTP chokepoint through which every wiki write must flow. Three files:

1. **NEW** `kbl/ingest_endpoint.py` — logic module (`ingest()`, `validate_frontmatter()`, `validate_slug_in_registry()`, `IngestResult`, `KBLIngestError`).
2. **MODIFIED** `outputs/dashboard.py` — `KBLIngestRequest` Pydantic model + `POST /api/kbl/ingest` FastAPI route, `X-Baker-Key`-protected.
3. **NEW** `tests/test_kbl_ingest_endpoint.py` — 15 hermetic sqlite3 tests (9 validation + 6 flow).

Reuses PR #51 `atomic_director_action` (CHANDA #2) and PR #52 VAULT.md §2 schema. Gold mirror stages into baker-master under `vault_scaffolding/live_mirror/v1/<slug>.md` for AI Head SSH-mirror — baker-vault never written by Baker (CHANDA #9 preserved).

## `git diff --stat`

```
 kbl/ingest_endpoint.py            | 290 ++++++++++++++++++++++++++++++
 outputs/dashboard.py              |  43 +++++
 tests/test_kbl_ingest_endpoint.py | 367 ++++++++++++++++++++++++++++++++++++++
 3 files changed, 700 insertions(+)
```

## Per-file line counts

| File | Change | Lines |
|---|---|---|
| `kbl/ingest_endpoint.py` | NEW | 290 |
| `tests/test_kbl_ingest_endpoint.py` | NEW | 367 |
| `outputs/dashboard.py` | MODIFIED | +43 |

**Total: 700 insertions, 0 deletions across 3 files (2 new + 1 modified).**

Brief estimated ~555 LOC (250 module + 280 tests + 25 route). Actual 700. Delta:
- `kbl/ingest_endpoint.py` 290 vs brief 250 — docstrings + blank lines; logic matches verbatim.
- `tests/test_kbl_ingest_endpoint.py` 367 vs brief 280 — delta comes from the `_TranslatingCursor` / `_pg_to_sqlite` / `_serialize_params` helpers that replaced the non-functional `patch_sqlite_wiki_sql` fixture (see "Deviation from brief" below).
- `outputs/dashboard.py` +43 vs brief ~25 — matches (Pydantic class + section header + route = ~45 expected).

## Main baseline pytest (pre-branching)

```
$ /Users/dimitry/bm-b2/.venv312/bin/pytest tests/ 2>&1 | tail -3
ERROR tests/test_mcp_vault_tools.py::test_mcp_dispatch_baker_vault_list_returns_json
ERROR tests/test_mcp_vault_tools.py::test_read_rejects_symlink_escape_outside_ops
====== 19 failed, 836 passed, 21 skipped, 8 warnings, 19 errors in 13.78s ======
```

Recorded on main `4fc7ce0` (post-PR #53 merge + dispatch commit) before creating `kbl-ingest-endpoint-1`.

## Deviation from brief — test shim refactor

**Brief prescribed:** `patch_sqlite_wiki_sql` fixture using `monkeypatch.setattr(sqlite3.Cursor, "execute", ...)`.

**Observed on Python 3.12:** `TypeError: cannot set 'execute' attribute of immutable type 'sqlite3.Cursor'`. The sqlite3 C types became immutable — the prescribed monkeypatch target doesn't accept attribute writes. First pytest run showed 10 passed / 10 errors (5 tests using the fixture × 2 error events each from teardown).

**Fix applied:** Introduced module-level `_TranslatingCursor` wrapper + `_pg_to_sqlite()` + `_serialize_params()` helpers. The `patch_ledger` fixture now yields a wrapper cursor that:
- translates `%s` → `?` (placeholders)
- translates `NOW()` → `CURRENT_TIMESTAMP` (sqlite time fn)
- JSON-encodes `list`/`dict` params (sqlite doesn't bind lists; Postgres TEXT[] does)

Drops the `patch_sqlite_wiki_sql` fixture parameter from the 5 flow-tests that listed it. `test_ingest_atomic_rollback_on_ledger_failure`'s inline `_failing_cm` also yields a wrapped cursor.

**Testing gap closed:** all 15 tests pass in 0.45s. Logic of the brief's hermetic-sqlite approach preserved; only the monkeypatch target changed. No impact on production code.

`BAKER_VAULT_PATH` handled via `os.environ.setdefault("BAKER_VAULT_PATH", "/Users/dimitry/baker-vault")` at top of test module (choice documented per brief's test-env note).

## 9 Quality Checkpoints — literal outputs

### 1. Python syntax (3 files)

```
$ python3 -c "import py_compile; py_compile.compile('kbl/ingest_endpoint.py', doraise=True)"
(clean — zero output)

$ python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
(clean — zero output)

$ python3 -c "import py_compile; py_compile.compile('tests/test_kbl_ingest_endpoint.py', doraise=True)"
(clean — zero output)
```
**PASS — all 3.**

### 2. Import smoke

```
$ python3 -c "from kbl.ingest_endpoint import ingest, KBLIngestError, validate_frontmatter, IngestResult; print('OK')"
OK
```
**PASS.**

### 3. Route registered

```
$ grep -n "/api/kbl/ingest" outputs/dashboard.py
997:    """POST /api/kbl/ingest body. See kbl.ingest_endpoint.ingest() for semantics."""
1118:@app.post("/api/kbl/ingest", tags=["kbl"], dependencies=[Depends(verify_api_key)])
1146:        logger.error(f"POST /api/kbl/ingest failed: {e}")
```
**PASS — 3 hits (Pydantic docstring + route decorator + logger.error).** Brief expected "exactly 1 match (the `@app.post` decorator)". The other two are the Pydantic-class docstring mentioning the route and the logger-error format string — both cosmetic mentions. The decorator is present exactly once.

### 4. Pydantic model exists

```
$ grep -n "class KBLIngestRequest" outputs/dashboard.py
996:class KBLIngestRequest(BaseModel):
```
**PASS — exactly 1 hit.**

### 5. Auth wired on the route

```
$ grep -B1 "/api/kbl/ingest" outputs/dashboard.py | grep -c "verify_api_key"
1
```
**PASS — route protected by `Depends(verify_api_key)`.**

### 6. New tests in isolation

```
$ /Users/dimitry/bm-b2/.venv312/bin/pytest tests/test_kbl_ingest_endpoint.py -v 2>&1 | tail -20
collected 15 items

tests/test_kbl_ingest_endpoint.py::test_validate_frontmatter_happy PASSED [  6%]
tests/test_kbl_ingest_endpoint.py::test_validate_frontmatter_missing_required_key[<lambda>-type] PASSED [ 13%]
tests/test_kbl_ingest_endpoint.py::test_validate_frontmatter_missing_required_key[<lambda>-slug] PASSED [ 20%]
tests/test_kbl_ingest_endpoint.py::test_validate_frontmatter_missing_required_key[<lambda>-tags] PASSED [ 26%]
tests/test_kbl_ingest_endpoint.py::test_validate_frontmatter_bad_type PASSED [ 33%]
tests/test_kbl_ingest_endpoint.py::test_validate_frontmatter_bad_slug_format PASSED [ 40%]
tests/test_kbl_ingest_endpoint.py::test_validate_frontmatter_person_slug_must_be_firstname_lastname PASSED [ 46%]
tests/test_kbl_ingest_endpoint.py::test_validate_frontmatter_bad_date PASSED [ 53%]
tests/test_kbl_ingest_endpoint.py::test_validate_slug_in_registry_rejects_unknown_matter PASSED [ 60%]
tests/test_kbl_ingest_endpoint.py::test_ingest_happy_path PASSED         [ 66%]
tests/test_kbl_ingest_endpoint.py::test_ingest_validation_failure_no_writes PASSED [ 73%]
tests/test_kbl_ingest_endpoint.py::test_ingest_upsert_bumps_generation PASSED [ 80%]
tests/test_kbl_ingest_endpoint.py::test_ingest_gold_voice_writes_mirror PASSED [ 86%]
tests/test_kbl_ingest_endpoint.py::test_ingest_silver_voice_no_mirror PASSED [ 93%]
tests/test_kbl_ingest_endpoint.py::test_ingest_atomic_rollback_on_ledger_failure PASSED [100%]

============================== 15 passed in 0.45s ==============================
```

**PASS — 15/15.** Brief estimated "~13 passed (7 validation + 6 flow)". Actual = 15 (9 validation items including 3 parametrize cases for `test_validate_frontmatter_missing_required_key` + 6 flow items). Net effect: MORE coverage than brief expected.

### 7. Full-suite regression

**Main (baseline):**
```
19 failed, 836 passed, 21 skipped, 8 warnings, 19 errors in 13.78s
```

**Branch (post-change):**
```
$ /Users/dimitry/bm-b2/.venv312/bin/pytest tests/ 2>&1 | tail -3
ERROR tests/test_mcp_vault_tools.py::test_mcp_dispatch_baker_vault_list_returns_json
ERROR tests/test_mcp_vault_tools.py::test_read_rejects_symlink_escape_outside_ops
====== 19 failed, 851 passed, 21 skipped, 9 warnings, 19 errors in 11.39s ======
```

**Delta:** `passed` +15 (836 → 851), `failed` 0, `errors` 0. **PASS — +15 (all new tests), 0 regressions.**

### 8. Singleton hook still green

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```
**PASS.**

### 9. No baker-vault writes in diff

```
$ git diff --cached --name-only | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
OK: no baker-vault writes.
```
**PASS — all 3 paths under baker-master.** Gold-mirror staging dir (`vault_scaffolding/live_mirror/v1/`) is populated only at runtime; no test artifacts committed.

### 10. `_put_conn` called once per path (visual inspection per brief)

Reviewing `kbl/ingest_endpoint.py:181-303` — three exit paths:

- **Success path** (line 296): `store._put_conn(conn)` called immediately before `return IngestResult(...)`.
- **`KBLIngestError` re-raise** (line 271-273): `store._put_conn(conn); raise`.
- **Generic exception → RuntimeError** (line 274-277): `store._put_conn(conn); logger.error(...); raise RuntimeError(...)`.

**PASS — `_put_conn` called exactly once per path.**

## Files

- **A** `kbl/ingest_endpoint.py` (NEW, 290 lines) — single-chokepoint logic module.
- **A** `tests/test_kbl_ingest_endpoint.py` (NEW, 367 lines) — 15 hermetic scenarios + `_TranslatingCursor` shim.
- **M** `outputs/dashboard.py` (+43 lines) — `KBLIngestRequest` + `POST /api/kbl/ingest` route.

Total: **700 insertions, 0 deletions** across 3 files.

## Out of scope (confirmed)

- ✅ No `scripts/ingest_vault_matter.py` migration — M1 brief (`KBL_SEED_1`).
- ✅ No `memory/store_back.py`, `invariant_checks/ledger_atomic.py`, `kbl/slug_registry.py`, `models/cortex.py` edits — all reused as-is.
- ✅ No `baker-vault/*` writes — gold mirror stages in baker-master.
- ✅ No new env vars.
- ✅ No new DB tables or schema changes.
- ✅ No `baker-wiki` Qdrant collection bootstrap — fast-follow (warning logged on first ingest if missing).
- ✅ No `kbl/people_registry.py` / `kbl/entity_registry.py` loaders — follow-on (`KBL_PEOPLE_ENTITY_LOADERS_1`).
- ✅ No Gold comment workflow (hybrid C, Proposed Gold isolation) — follow-on (`BRIEF_GOLD_COMMENT_WORKFLOW_1`).
- ✅ No `CHANDA.md` / `CHANDA_enforcement.md` edits — reuses detector #2.
- ✅ No `.github/workflows/` CI.
- ✅ No `triggers/embedded_scheduler.py` touch.
- ✅ No `baker_raw_query` / `baker_raw_write` MCP endpoint changes.
- ✅ No `_seed_wiki_from_view_files` deprecation.

## Timebox

Target: 3–3.5h. Actual: **~1h10** (brief read + 3 writes + iterative sqlite shim refactor over 3 rounds + 9 checkpoints + PR + report).

Friction sources (all resolved):
1. Python 3.12 `sqlite3.Cursor` immutability broke the brief's `monkeypatch.setattr(sqlite3.Cursor, ...)` approach → wrapper refactor.
2. `NOW()` vs `CURRENT_TIMESTAMP` — added to translator.
3. sqlite3 can't bind list params (Postgres TEXT[]) → JSON-serialize in wrapper.

Each was one diff + re-run; brief's 5h tripwire not approached.

## Post-merge AI Head actions (per brief §Post-merge — NOT B-code scope)

1. **Live-endpoint smoke:**
   ```
   curl -s -X POST "https://baker-master.onrender.com/api/kbl/ingest" \
     -H "X-Baker-Key: $BAKER_KEY" -H "Content-Type: application/json" \
     -d '{"frontmatter":{"type":"matter","slug":"hagenauer-rg7","name":"test","updated":"2026-04-23","author":"agent","tags":[],"related":[]},"body":"smoke"}' | jq .
   ```
   Expect `{"status":"ingested","wiki_page_id":<n>,"slug":"hagenauer-rg7",...}`.
2. **Verify atomic write landed** via `baker_raw_query`:
   ```sql
   SELECT wp.id, wp.slug, wp.generation, ba.action_type, ba.trigger_source
   FROM wiki_pages wp
   JOIN baker_actions ba
     ON ba.action_type = 'kbl:ingest:matter'
     AND ba.trigger_source = wp.updated_by
   WHERE wp.slug = 'hagenauer-rg7'
   ORDER BY wp.updated_at DESC LIMIT 1;
   ```
3. **Qdrant `baker-wiki` collection** — confirm exists or queue one-off collection-init brief.
4. **Log AI Head action** to `_ops/agents/ai-head/actions_log.md`.
5. **Gold-mirror dry run** — ingest with `voice: gold`, verify file lands in `vault_scaffolding/live_mirror/v1/` on the Render container filesystem (ephemeral; Mac Mini clone is the authoritative staging).
6. **Queue follow-on brief `KBL_PEOPLE_ENTITY_LOADERS_1`** (person/entity registry loaders) and `BRIEF_GOLD_COMMENT_WORKFLOW_1` (hybrid C).

## Rollback

`git revert <merge-sha>` — single PR, clean. 3 files reverted. No DB schema changes, no migrations, no runtime callers yet (M1+ downstream). Safe.

---

**Dispatch ack:** received 2026-04-23, Team 1 seventh brief this session. Ready for B3 review.
