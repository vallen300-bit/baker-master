# B3 Review — PR #55 KBL_INGEST_ENDPOINT_1 — 2026-04-24

**Reviewer:** Code Brisen #3 (B3)
**PR:** https://github.com/vallen300-bit/baker-master/pull/55
**Branch:** `kbl-ingest-endpoint-1` @ `9de5694`
**Main compared:** `03d02db`
**Brief:** `briefs/BRIEF_KBL_INGEST_ENDPOINT_1.md` (commit `453a9e5`)
**B1 ship report:** `briefs/_reports/B1_kbl_ingest_endpoint_1_20260423.md`
**Verdict:** **APPROVE** — 15/15 checks green.

---

## Check 1 — Scope lock ✅

```
git diff --name-only main...HEAD
kbl/ingest_endpoint.py
outputs/dashboard.py
tests/test_kbl_ingest_endpoint.py
```

Exactly 3 files. Zero drift into `scripts/ingest_vault_matter.py`, `memory/store_back.py`, `invariant_checks/ledger_atomic.py`, `kbl/slug_registry.py`, `models/cortex.py`, `CHANDA*.md`, `vault_scaffolding/`, or `baker-vault/`.

## Check 2 — Python syntax ✅

All 3 `py_compile` runs clean. One pre-existing non-blocking SyntaxWarning (`invalid escape sequence '\['` in `outputs/dashboard.py:2484` — regex in SQL literal, unrelated to this PR's diff).

## Check 3 — Import smoke ✅

```
python -c "from kbl.ingest_endpoint import ingest, KBLIngestError, validate_frontmatter, validate_slug_in_registry, IngestResult; print('OK')"
→ OK
```

## Check 4 — Route registered + Pydantic + auth wired ✅

- `class KBLIngestRequest(BaseModel)` at line 996
- `@app.post("/api/kbl/ingest", tags=["kbl"], dependencies=[Depends(verify_api_key)])` at line 1118
- `verify_api_key` in decorator one line above the route — confirmed (grep-B1 count = 1)

Note: `/api/kbl/ingest` appears 3 times total in the file (line 997 docstring, line 1118 route, line 1146 log message) — all legitimate, single registered route.

## Check 5 — `atomic_director_action` used correctly ✅

```
grep -n "atomic_director_action" kbl/ingest_endpoint.py
155:    from invariant_checks.ledger_atomic import atomic_director_action
164:        with atomic_director_action(
```

Exactly 2 matches: lazy import inside `ingest()` + single `with` block. Matches `cortex.publish_event()` pattern post-PR #51.

## Check 6 — `_put_conn(conn)` accounting ✅

```
grep -n "_put_conn" kbl/ingest_endpoint.py
204:        store._put_conn(conn)
207:        store._put_conn(conn)
228:    store._put_conn(conn)
```

Exactly 3 matches — one per exit path:
- Line 204: `KBLIngestError` re-raise path → `_put_conn` then raise
- Line 207: generic exception path → `_put_conn` then `raise RuntimeError`
- Line 228: success path (after Qdrant + Gold mirror) → `_put_conn` then `return IngestResult`

No double-call, no missed branch.

## Check 7 — No mocks, real rollback ✅

```
grep -cE "mock|Mock|patch\(" tests/test_kbl_ingest_endpoint.py → 0
grep -c "rollback\|OperationalError" tests/test_kbl_ingest_endpoint.py → 4
```

Zero `Mock()` / `patch()` usage. 4 hits on `rollback/OperationalError` — `test_ingest_atomic_rollback_on_ledger_failure` raises real `sqlite3.OperationalError("simulated ledger failure")` and asserts real `conn.rollback()`. Honest shell-out atomicity proof.

## Check 8 — 15 tests pass in isolation ✅

```
pytest tests/test_kbl_ingest_endpoint.py -v
============================== 15 passed in 0.80s ==============================
```

Coverage spread:
- Validation: happy, missing-key (parametrized on `type`, `slug`, `tags`), bad-type, bad-slug-format, person-slug-firstname-lastname, bad-date
- Registry: unknown-matter rejection
- Ingest: happy path, validation-failure-no-writes, upsert-bumps-generation, gold-voice-mirror-written, silver-voice-no-mirror, atomic-rollback-on-ledger-failure

15 total (brief spec'd 13; parametrized `missing_required_key` yields 3 variants of 1 test function, which accounts for the +2 beyond brief).

## Check 9 — Regression delta ✅

```
=== BRANCH kbl-ingest-endpoint-1 @ 9de5694 ===
19 failed, 851 passed, 21 skipped, 8 warnings, 19 errors in 13.78s

=== MAIN @ 03d02db ===
19 failed, 836 passed, 21 skipped, 9 warnings, 19 errors in 13.74s
```

**Delta: +15 passes, 0 new failures, 0 new errors.** Exact match to B1 ship report (836 → 851).

## Check 10 — No baker-vault writes ✅

```
git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)"
→ OK: no baker-vault writes.
```

CHANDA #9 preserved.

## Check 11 — Gold-mirror path semantics ✅

```
grep -n "gold_mirrored" tests/test_kbl_ingest_endpoint.py
272:    assert result.gold_mirrored is False   (silver-voice case)
317:    assert result.gold_mirrored is True    (gold-voice case)
333:    assert result.gold_mirrored is False   (gold-voice but...)
```

3 hits covering both positive and negative sides. `_write_gold_mirror` (line 281 in ingest_endpoint.py) inspected: idempotent `mkdir parents=True, exist_ok=True`, writes reassembled frontmatter+body, non-blocking wrt main flow.

## Check 12 — Lazy imports, no circular risk ✅

```
grep -n "^import\|^from" kbl/ingest_endpoint.py
19: from __future__ import annotations
21: import hashlib
22: import logging
23: import re
24: from dataclasses import dataclass
25: from pathlib import Path
26: from typing import Optional
```

Top level is stdlib + typing only. `memory.store_back`, `invariant_checks.ledger_atomic`, `models.cortex`, `qdrant_client` all deferred to function bodies. Matches `cortex.py:18-24` precedent.

## Check 13 — Singleton hook ✅

```
bash scripts/check_singletons.sh
→ OK: No singleton violations found.
```

## Check 14 — Public surface shape ✅

```
41:@dataclass
42:class IngestResult:
50:class KBLIngestError(ValueError):
54:def validate_frontmatter(fm: dict) -> None:
97:def validate_slug_in_registry(fm: dict) -> None:
113:def ingest(...)
240:def _reassemble(fm: dict, body: str) -> str:
247:def _upsert_vector(client, fm: dict, body: str, wiki_page_id: int) -> Optional[int]:
281:def _write_gold_mirror(fm: dict, body: str, mirror_root: Optional[Path]) -> Path:
```

All 8 spec'd symbols present at expected line ranges.

## Check 15 — `_TranslatingCursor` deviation ✅

Inspected `class _TranslatingCursor` (line 118) + `patch_ledger` fixture (line 150):

- **Wraps** a real `sqlite3.Cursor` via `__init__(self, real)` + `self._real = real`. No mutation of the stdlib type.
- **Translates** via `_pg_to_sqlite(sql)` call in `execute()` / `executemany()` (`%s → ?`, `NOW() → CURRENT_TIMESTAMP`) plus `_serialize_params(params)` (list → JSON).
- **Yields** `wrapped` from the `@contextmanager _sqlite_cm(...)` at line 160.
- **Rollback** path at line 176 on any exception, then re-raise.
- **Delegation** fallback via `__getattr__` (line 145) for any unwrapped cursor methods.
- **No business-logic change** — adapter pattern only, isolated to the test fixture.

**Docstring cites the root cause** (line 121-124): *"Python 3.12 makes sqlite3.Cursor immutable — we can't monkeypatch its execute method directly"*. Valid motivation, cleaner than the brief's original proposal.

**ACCEPTABLE** per AI Head dispatch. Rule-candidate for Mon audit (how tests should stage Postgres→sqlite dialect translation without mutating stdlib types).

## Decision

**APPROVE PR #55.** 15/15 checks green. Scope tight (3 files), syntax clean, imports lazy per `cortex.py` precedent, route auth-protected via `verify_api_key`, atomic block reuses PR #51 infrastructure with correct 3-path `_put_conn` accounting, no `Mock()/patch()` (only pytest's `monkeypatch` for the fixture swap), real rollback proof via `sqlite3.OperationalError`, 15/15 tests pass with broad coverage (validation + registry + atomic + gold-mirror both voices), regression delta +15/0 exactly matches B1, CHANDA #9 preserved, singleton hook clean, public surface matches spec, `_TranslatingCursor` wrapper is a legitimate Python 3.12 compat fix that leaves business logic untouched.

**M0 quintet row 3 CLOSED** with this merge. Tier A auto-merge greenlit per charter §3.

— B3, 2026-04-24
