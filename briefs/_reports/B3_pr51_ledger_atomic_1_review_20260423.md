# B3 Review — PR #51 LEDGER_ATOMIC_1 — 2026-04-23

**Reviewer:** Code Brisen #3 (B3)
**PR:** https://github.com/vallen300-bit/baker-master/pull/51
**Branch:** `ledger-atomic-1` @ `2b75f77`
**Main compared:** `c53a188`
**Brief:** `briefs/BRIEF_LEDGER_ATOMIC_1.md` (commit `3349c20`)
**B1 ship report:** `briefs/_reports/B1_ledger_atomic_1_20260423.md`
**Verdict:** **APPROVE** — 12/12 checks green (check 12 flagged, non-blocking).

---

## Check 1 — Scope lock ✅

```
git diff --name-only main...HEAD
CHANDA_enforcement.md
invariant_checks/ledger_atomic.py
models/cortex.py
tests/test_ledger_atomic.py
```

Exactly 4 files. No `clickup_client.py`, `memory/store_back.py`, `CHANDA.md`, `triggers/embedded_scheduler.py`, `.github/workflows/` drift.

## Check 2 — Python syntax ✅

All four `py_compile` runs: zero output, zero error.
- `invariant_checks/ledger_atomic.py`: OK
- `models/cortex.py`: OK
- `tests/test_ledger_atomic.py`: OK
- Import check `from invariant_checks.ledger_atomic import atomic_director_action; assert callable(atomic_director_action)`: OK

## Check 3 — Dead code removed ✅

```
grep -n "_audit_to_baker_actions\|# ─── Audit Trail ───" models/cortex.py
→ 0 matches
```

Function + call site + section-header comment all gone.

## Check 4 — Helper referenced exactly 2× ✅

```
grep -n "atomic_director_action" models/cortex.py
239:    from invariant_checks.ledger_atomic import atomic_director_action
248:        with atomic_director_action(
```

Exactly 2 matches as specified: lazy import at top of publish_event, then single `with` block.

## Check 5 — Dedup gate untouched ✅

```
git diff main...HEAD models/cortex.py | grep -E "^[-+].*(check_dedup|auto_merge_enabled|would_merge|review_needed|_log_dedup_event)"
→ (empty)
```

Dedup-gate block (pre-merge 189-236) + `_log_dedup_event` (pre-merge 299-334) both pristine.

## Check 6 — `_put_conn(conn)` exactly once per path ✅

Traced new `publish_event()` body (cortex.py:236-300):

**Success path:**
1. `conn = _get_conn()` at line 241
2. `with atomic_director_action(...) as cur:` succeeds, `event_id` set
3. `logger.info` (line 271)
4. Falls through to outer `try:` post-write side-effects (line 279)
5. `return event_id` (line 297) → `finally: _put_conn(conn)` (line 299) — **1 call**

**Failure path (atomic block raises):**
1. `conn = _get_conn()` at line 241
2. `with atomic_director_action(...)` raises
3. `except Exception as e:` at line 275
4. `logger.error` (line 276)
5. `_put_conn(conn)` (line 277) — **1 call**
6. `return None` — exits before outer try/finally is entered

No double-call on either branch. Outer try/finally is only entered on success path.

## Check 7 — No mocks in test file ✅

```
grep -cE "mock|Mock|patch\(" tests/test_ledger_atomic.py
→ 0
```

Zero hits. Real sqlite3 `:memory:` connections throughout. Fault injection via context-manager swap (not mock), invalid SQL for real sqlite exceptions.

## Check 8 — 6/6 tests pass, names match spec ✅

```
pytest tests/test_ledger_atomic.py -v
============================== 6 passed in 0.02s ==============================
```

All 6 names verbatim from brief:
- ✅ `test_happy_path_both_rows_land`
- ✅ `test_primary_raises_both_rows_rolled_back`
- ✅ `test_ledger_raises_primary_rolled_back`
- ✅ `test_no_conn_raises_runtime_error`
- ✅ `test_payload_serialized_as_json`
- ✅ `test_multiple_writes_each_atomic`

## Check 9 — Regression delta ✅

```
=== BRANCH ledger-atomic-1 @ 2b75f77 ===
19 failed, 825 passed, 21 skipped, 8 warnings, 19 errors in 12.23s

=== MAIN @ c53a188 ===
19 failed, 819 passed, 21 skipped, 8 warnings, 19 errors in 11.69s
```

**Delta: +6 passes, 0 new failures, 0 new errors.** Exact match to B1's reported numbers.

## Check 10 — CHANDA §7 amendment ✅

- `grep -c "^| 2026-04" CHANDA_enforcement.md` → **3** (2026-04-21 initial + 2026-04-23 #4 from PR #49 + 2026-04-23 #2 from this PR)
- `grep -c "ledger_atomic.py" CHANDA_enforcement.md` → **2** (1 in §6 detector pointers + 1 in new row)
- `grep -c "publish_event" CHANDA_enforcement.md` → **1** (new row cites first caller)
- `grep -c "§8\|^## §8" CHANDA_enforcement.md` → **0** (still §7-capped)

Tail row:
```
| 2026-04-23 | §4 row #2 + §6 | Detector #2 shipped: `invariant_checks/ledger_atomic.py` context manager binds Director-action primary write and `baker_actions` ledger row into one DB transaction. First caller: `cortex.publish_event()` (LEDGER_ATOMIC_1, PR TBD). Follow-on briefs migrate remaining call sites. | "default recom is fine" (2026-04-21) |
```

## Check 11 — Singleton hook ✅

```
bash scripts/check_singletons.sh
→ OK: No singleton violations found.
```

New helper uses no singleton pattern; `cortex.py` still uses lazy `SentinelStoreBack` imports unchanged.

## Check 12 — Commit marker (flagged, non-blocking) ⚠️

```
git log --format=%B -1 ledger-atomic-1 | grep -E "^Director-signed:"
→ (not found)
```

**Commit `2b75f77` does NOT carry a `Director-signed:` marker.** Per dispatch, baker-master main doesn't enforce CHANDA #4 yet, so this is **not a reject** — flagging for AI Head's awareness. Continuity concern only when later SSH-mirroring to baker-vault (where `author: director` applies).

**Recommendation to AI Head:** When vault-mirror happens, either (a) re-author the vault-side commit with a Director-signed marker citing the brief's authorization, or (b) add a `Director-signed:` trailer in AI Head's own mirror commit message.

## Decision

**APPROVE PR #51.** 11/12 checks green, check 12 flagged non-blocking per dispatch. Scope tight (4 files exact), syntax clean, dead code removed, helper used exactly where specified, dedup gate untouched, `_put_conn` accounting correct (1 call per path), no mocks, 6/6 tests pass with exact names, regression delta matches B1 (+6 / 0), CHANDA amendment properly formatted, singleton hook clean.

Tier A auto-merge greenlit per charter §3.

— B3, 2026-04-23
