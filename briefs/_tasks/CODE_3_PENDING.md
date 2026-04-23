# CODE_3_PENDING — B3 REVIEW: PR #55 KBL_INGEST_ENDPOINT_1 — 2026-04-24

**Dispatcher:** AI Head (Team 1 — Meta/Persistence)
**Working dir:** `~/bm-b3`
**Target PR:** https://github.com/vallen300-bit/baker-master/pull/55
**Branch:** `kbl-ingest-endpoint-1`
**Brief:** `briefs/BRIEF_KBL_INGEST_ENDPOINT_1.md` (shipped in commit `453a9e5`)
**Ship report:** `briefs/_reports/B1_kbl_ingest_endpoint_1_20260423.md` (commit `22c3615`)

**Supersedes:** prior `MAC_MINI_WRITER_AUDIT_1` B3 review — APPROVE landed; PR #53 merged `327dbab`. Mailbox cleared.

---

## What this PR does

Ships M0 quintet row 3 — single HTTP chokepoint for wiki writes. 3 files, 700 insertions / 0 deletions.

- NEW `kbl/ingest_endpoint.py` (290 LOC) — `ingest()` entrypoint, `validate_frontmatter()`, `validate_slug_in_registry()`, `IngestResult`, `KBLIngestError`. Reuses `atomic_director_action` (PR #51) for wiki_pages + baker_actions atomicity.
- MODIFIED `outputs/dashboard.py` (+43 LOC) — `KBLIngestRequest` Pydantic model + `@app.post("/api/kbl/ingest", ...)` handler protected by `verify_api_key`.
- NEW `tests/test_kbl_ingest_endpoint.py` (367 LOC) — 15 hermetic sqlite3 scenarios (brief spec'd 13; B1 added 2 more per ship report).

B1 reported: 9/9 ship gate PASS. **One documented deviation (non-semantic):** brief's fixture used `monkeypatch.setattr(sqlite3.Cursor.execute, ...)` which fails on Python 3.12 (C-level immutable type). B1 refactored to a `_TranslatingCursor` wrapper yielded from the `patch_ledger` fixture, handling `%s→?`, `NOW()→CURRENT_TIMESTAMP`, and list-param JSON-serialization. Logic preserved; only monkeypatch target changed. **Accept** — cleaner than the brief's approach. (Captured as Rule-candidate for Mon audit.)

Pytest delta: 836 → 851 passed (+15), 0 regressions.

---

## Your review job (charter §3 — B3 routes; Tier A auto-merge on APPROVE)

### 1. Scope lock — exactly 3 files

```bash
cd ~/bm-b3 && git fetch && git checkout kbl-ingest-endpoint-1 && git pull -q
git diff --name-only main...HEAD
```

Expect exactly these 3 paths, nothing else:

```
kbl/ingest_endpoint.py
outputs/dashboard.py
tests/test_kbl_ingest_endpoint.py
```

**Reject if:** `scripts/ingest_vault_matter.py`, `memory/store_back.py`, `invariant_checks/ledger_atomic.py`, `kbl/slug_registry.py`, `models/cortex.py`, `CHANDA*.md`, `vault_scaffolding/`, or any `baker-vault/` path touched. All explicit Do-NOT-Touch per brief.

### 2. Python syntax on all 3 files

```bash
python3 -c "import py_compile; py_compile.compile('kbl/ingest_endpoint.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('tests/test_kbl_ingest_endpoint.py', doraise=True)"
```

Zero output, zero error.

### 3. Import smoke

```bash
python3 -c "from kbl.ingest_endpoint import ingest, KBLIngestError, validate_frontmatter, validate_slug_in_registry, IngestResult; print('OK')"
```

Expect: `OK`.

### 4. Route registered + Pydantic model present + auth wired

```bash
grep -n "/api/kbl/ingest" outputs/dashboard.py              # expect 1
grep -n "class KBLIngestRequest" outputs/dashboard.py       # expect 1
grep -B1 "/api/kbl/ingest" outputs/dashboard.py | grep -c "verify_api_key"  # expect 1
```

All three expected counts match. Missing `verify_api_key` is a HARD REJECT (unauth endpoint).

### 5. Atomic-block discipline — `atomic_director_action` used correctly

```bash
grep -n "atomic_director_action" kbl/ingest_endpoint.py
```

Expect 2 matches: inline import inside `ingest()` + `with atomic_director_action(...) as cur:` block. Same pattern as `cortex.publish_event()` post-PR #51.

### 6. `_put_conn(conn)` runs exactly once on every path

Read the `ingest()` function body. Trace three exit paths:
- **Success:** atomic block OK → Qdrant upsert (non-blocking) → Gold mirror (non-blocking) → `store._put_conn(conn)` → return `IngestResult`.
- **KBLIngestError re-raise:** validation failed inside atomic block → `store._put_conn(conn)` → raise.
- **Generic exception:** atomic block died → `store._put_conn(conn)` → raise `RuntimeError`.

**Reject if** any path misses `_put_conn` or calls it twice.

```bash
grep -n "_put_conn" kbl/ingest_endpoint.py
```

Expect 3 matches (one per exit path). Not 2, not 4.

### 7. No mocks in tests — real rollback proof

```bash
grep -cE "mock|Mock|patch\(" tests/test_kbl_ingest_endpoint.py
```

Expect **0 or 1** (the one hit should be `monkeypatch` which is pytest's built-in — not `unittest.mock`). `monkeypatch.setattr` is acceptable for fixture swaps; `Mock()` / `patch()` is not, per the LEDGER_ATOMIC_1 precedent.

Verify at least one test genuinely forces rollback:
```bash
grep -n "rollback\|OperationalError" tests/test_kbl_ingest_endpoint.py
```

Expect at least 2 matches.

### 8. 15 tests pass in isolation

```bash
pytest tests/test_kbl_ingest_endpoint.py -v 2>&1 | tail -25
```

Expect `15 passed`. Names should cover: happy path, missing key(s), bad type, bad slug format, person slug rule, bad date, unknown matter slug, upsert generation bump, gold voice mirror write, silver voice no-mirror, atomic rollback on ledger failure, validation failure no writes. Two extra beyond brief's 13 — inspect names + assertions; should be genuine coverage additions.

### 9. Regression delta reconciles — 836 → 851

```bash
pytest tests/ 2>&1 | tail -3
```

Expect `<19 or similar> failed, 851 passed, <19> errors`. Delta = +15 passes, 0 new failures/errors. If branch shows fewer passes than main+15, reject.

### 10. No baker-vault writes in diff

```bash
git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
```

Expect: `OK: no baker-vault writes.`

### 11. Gold-mirror path semantics

Inspect `_write_gold_mirror` in `kbl/ingest_endpoint.py`:
- Target dir defaults to `<repo-root>/vault_scaffolding/live_mirror/v1/`.
- Writes `<slug>.md` containing the REASSEMBLED frontmatter + body.
- `mkdir parents=True, exist_ok=True` — idempotent.
- Non-blocking wrt main ingest flow (exception logged, not raised).

```bash
grep -n "gold_mirrored" tests/test_kbl_ingest_endpoint.py
```

Expect ≥ 2 matches (gold-positive + gold-negative test cases).

### 12. Lazy imports — no top-level circular imports

```bash
grep -n "^import\|^from" kbl/ingest_endpoint.py
```

Top-level imports should NOT include `memory.store_back`, `invariant_checks.ledger_atomic`, `models.cortex`, or `qdrant_client`. Those live inside function bodies per the `cortex.py:18-24` precedent.

### 13. Singleton hook still green

```bash
bash scripts/check_singletons.sh
```

Expect: `OK: No singleton violations found.`

### 14. Public surface shape

```bash
grep -n "^class\|^@dataclass\|^def " kbl/ingest_endpoint.py
```

Expect: `@dataclass IngestResult`, `class KBLIngestError(ValueError)`, `def validate_frontmatter`, `def validate_slug_in_registry`, `def ingest`, `def _reassemble`, `def _upsert_vector`, `def _write_gold_mirror`.

### 15. Deviation inspection — `_TranslatingCursor` wrapper

B1's ship report documents the Python 3.12 compat fix. Inspect the fixture:

```bash
grep -nA 30 "class _TranslatingCursor\|def patch_ledger" tests/test_kbl_ingest_endpoint.py | head -60
```

Confirm:
- Wraps a real `sqlite3.Cursor` (no type-mutation on the stdlib class).
- Translates `%s` → `?`, `NOW()` → `CURRENT_TIMESTAMP`, list params → JSON.
- Yielded inside the context manager returned by `patch_ledger`.
- No silent changes to business logic — only SQL-dialect adapter.

**ACCEPTABLE** per AI Head dispatch note. Python 3.12 compat + cleaner than original brief proposal.

---

## If 15/15 green

Post APPROVE on PR #55. Tier A auto-merge on APPROVE (standing per charter §3). Write ship report to `briefs/_reports/B3_pr55_kbl_ingest_endpoint_1_review_20260424.md`.

Overwrite this file with a "B3 dispatch back" summary section. Commit + push on main.

## If any check fails

`gh pr review --request-changes` with a specific list. Route back to B1 via new CODE_1_PENDING.md. Do NOT merge.

---

## Timebox

**~35–45 min.** 15 checks, mix of mechanical + inspection.

---

**Dispatch timestamp:** 2026-04-24 post-PR-55-ship (Team 1, M0 quintet row 3 B3 review)
**Team:** Team 1 — Meta/Persistence
**Sequence:** ENFORCEMENT_1 (#45) → GUARD_1 (#49) → LEDGER_ATOMIC_1 (#51) → KBL_SCHEMA_1 (#52) → MAC_MINI_WRITER_AUDIT_1 (#53) → **KBL_INGEST_ENDPOINT_1 (#55, this review)** → remaining M0: PROMPT_CACHE_AUDIT_1 + CITATIONS_API_SCAN_1.
