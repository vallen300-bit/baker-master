# CODE_3_PENDING — B3 REVIEW: PR #51 LEDGER_ATOMIC_1 — 2026-04-23

**Dispatcher:** AI Head (Team 1 — Meta/Persistence)
**Working dir:** `~/bm-b3`
**Target PR:** https://github.com/vallen300-bit/baker-master/pull/51
**Branch:** `ledger-atomic-1`
**Brief:** `briefs/BRIEF_LEDGER_ATOMIC_1.md` (shipped in commit `3349c20`)
**Ship report:** `briefs/_reports/B1_ledger_atomic_1_20260423.md` (commit `4596bd2`)

**Supersedes:** prior `AUTHOR_DIRECTOR_GUARD_1` B3 review — APPROVE landed; PR #49 merged `679a684`. Mailbox cleared.

---

## What this PR does

Ships CHANDA detector #2 (runtime DB txn wrapper) + §7 amendment-log entry. 4 files:

- NEW `invariant_checks/ledger_atomic.py` (148 LOC) — `@contextmanager atomic_director_action(conn, ...)`. Binds caller's primary write and `baker_actions` ledger row into ONE transaction on the same cursor. Rollback on any exception.
- NEW `tests/test_ledger_atomic.py` (225 LOC) — 6 hermetic sqlite3 scenarios: happy path, primary raises, ledger raises (fault injection via cm swap), conn=None, payload JSON, multi-write.
- MODIFIED `models/cortex.py` (771 → 738 = -33 net) — `publish_event()` rewritten around `atomic_director_action`; dead `_audit_to_baker_actions` function deleted.
- MODIFIED `CHANDA_enforcement.md` — +1 row in §7 amendment log.

B1 reported: 10/10 ship gate PASS, pytest delta +6 passes / 0 regressions (main 19f/819p → branch 19f/825p), 1h25 build (within 2–2.5h target).

---

## Your review job (charter §3 — B3 routes; Tier A auto-merge on APPROVE)

### 1. Scope lock — exactly 4 files

```bash
cd ~/bm-b3 && git fetch && git checkout ledger-atomic-1 && git pull -q
git diff --name-only main...HEAD
```

Expect exactly these 4 paths, nothing else:

```
CHANDA_enforcement.md
invariant_checks/ledger_atomic.py
models/cortex.py
tests/test_ledger_atomic.py
```

**Reject if:** `clickup_client.py`, `memory/store_back.py`, `CHANDA.md`, `triggers/embedded_scheduler.py`, or `_log_dedup_event` region of `cortex.py` touched. Those are explicit Do-NOT-Touch per brief.

### 2. Python syntax green on all 4 files

```bash
python3 -c "import py_compile; py_compile.compile('invariant_checks/ledger_atomic.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('models/cortex.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('tests/test_ledger_atomic.py', doraise=True)"
python3 -c "from invariant_checks.ledger_atomic import atomic_director_action; assert callable(atomic_director_action)"
```

All four return zero output, zero error.

### 3. Dead code fully removed

```bash
grep -n "_audit_to_baker_actions" models/cortex.py
```

**Expect: zero matches.** The function (lines 337-371 pre-merge) and its single call site (line 278 pre-merge) must both be gone. A leftover call would re-open the non-atomic path.

Also verify the `# ─── Audit Trail ───` section header comment was removed along with the function.

### 4. Helper referenced exactly 2× in cortex.py

```bash
grep -n "atomic_director_action" models/cortex.py
```

**Expect exactly 2 matches:** the inline `from invariant_checks.ledger_atomic import atomic_director_action` and the `with atomic_director_action(...) as cur:` block. More than 2 = helper used in unintended site. Zero or one = migration incomplete.

### 5. Dedup gate untouched

```bash
git diff main...HEAD models/cortex.py | grep -E "^[-+].*(check_dedup|auto_merge_enabled|would_merge|review_needed|_log_dedup_event)"
```

**Expect zero hits.** The dedup-gate block (lines 189-236 pre-merge) and `_log_dedup_event` (299-334 pre-merge) must be pristine — those are informational shadow-mode logs, not Director-action writes.

### 6. `_put_conn(conn)` runs exactly once on every path

Read the new `publish_event()` body in `models/cortex.py`. Trace both branches:

- **Success path:** atomic block succeeds → post-write side-effects (vector upsert + insights queue) → return event_id → `finally: _put_conn(conn)`.
- **Failure path:** atomic block raises → logger.error + `_put_conn(conn)` + return None.

**Reject if:** `_put_conn` is called twice on the same conn (double-return to pool), or missed on any branch.

### 7. Atomicity proof is honest — no mocks

Open `tests/test_ledger_atomic.py`. Verify:

- Fixture `conn` creates real sqlite3 `:memory:` conn with real `baker_actions` + `cortex_events` schemas.
- `test_ledger_raises_primary_rolled_back` uses **real transaction rollback** (conn.rollback inside except), not a mock. The swap substitutes a fail-on-exit context manager variant; primary INSERT actually executes and is actually rolled back.
- `test_primary_raises_both_rows_rolled_back` uses a **syntactically invalid SQL** (e.g. `INSERT INTO cortex_events (no_such_column)`) to force a real sqlite exception — not patched.

```bash
grep -cE "mock|Mock|patch\(" tests/test_ledger_atomic.py
```

**Expect 0** (unless an inline docstring / comment hit — allow up to 1 if it's a comment).

### 8. All 6 new tests pass, names match brief spec

```bash
pytest tests/test_ledger_atomic.py -v 2>&1 | tail -15
```

Expect `6 passed` and the 6 function names verbatim from the brief:

- `test_happy_path_both_rows_land`
- `test_primary_raises_both_rows_rolled_back`
- `test_ledger_raises_primary_rolled_back`
- `test_no_conn_raises_runtime_error`
- `test_payload_serialized_as_json`
- `test_multiple_writes_each_atomic`

### 9. Regression delta reconciles

```bash
pytest tests/ 2>&1 | tail -3
```

Expect `19 failed, 825 passed, 19 errors` (or whatever B1's branch-counts were). Compare to main baseline `19f/819p/19e` → delta = +6 passes, 0 new failures, 0 new errors.

If numbers don't reconcile (e.g. branch shows fewer passes than main+6, or new errors), **reject**.

### 10. CHANDA §7 amendment correct

```bash
grep -c "^| 2026-04" CHANDA_enforcement.md          # 3
grep "ledger_atomic.py" CHANDA_enforcement.md       # >=1 hit
tail -1 CHANDA_enforcement.md                       # the new 2026-04-23 #2 row
```

Verify:
- Exactly 3 dated rows (2026-04-21 initial, 2026-04-23 #4 from PR #49, 2026-04-23 #2 from this PR).
- Row text references `invariant_checks/ledger_atomic.py` and `cortex.publish_event()`.
- File ends with amendment-log table (no §8 added).

### 11. Singleton hook still green

```bash
bash scripts/check_singletons.sh
```

Expect `OK: No singleton violations found.` The new helper uses no singleton pattern; `cortex.py` still uses lazy SentinelStoreBack import (unchanged).

### 12. Row 4 frontmatter semantics preserved (CHANDA #4 cross-check)

The PR touches `CHANDA_enforcement.md`. In baker-vault, this file has `author: director` — but in **baker-master** the file is a mirror (no CHANDA #4 hook installed on Director's laptop yet). Verify the commit message on the branch carries a `Director-signed:` marker for paper-trail continuity when AI Head later SSH-mirrors to vault:

```bash
git log --format=%B -1 ledger-atomic-1
```

Look for `Director-signed:` line. If absent, **flag for AI Head in the ship report** (not reject — baker-master main doesn't enforce the hook yet; this is a continuity concern, not a block).

---

## If 12/12 green

Post APPROVE comment on PR #51. Tier A auto-merge on APPROVE (standing per charter §3). Write ship report to `briefs/_reports/B3_pr51_ledger_atomic_1_review_20260423.md`.

Overwrite this file with a "B3 dispatch back" summary section (replacing the review-job content), commit + push on main.

## If any check fails

Use `gh pr review --request-changes` with a specific list of what needs fixing. Route back to B1 with the delta in a new CODE_1_PENDING.md task. Do NOT merge.

---

## Timebox

**~30–45 min.** 12 checks are mechanical; this is a focused review, not a re-implementation.

---

**Dispatch timestamp:** 2026-04-23 post-PR-51-ship (Team 1, M0 quintet row 2b B3 review)
**Team:** Team 1 — Meta/Persistence
**Sequence:** ENFORCEMENT_1 (#45) → GUARD_1 (#49) → **LEDGER_ATOMIC_1 (#51, this review)** → KBL_SCHEMA_1 (queued) / MAC_MINI_WRITER_AUDIT_1 (docs, last)
