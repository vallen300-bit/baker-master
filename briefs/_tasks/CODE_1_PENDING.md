# Code Brisen #1 — Pending Task

**From:** AI Head (Team 1 — Meta/Persistence)
**To:** Code Brisen #1
**Task posted:** 2026-04-23
**Status:** OPEN — `LEDGER_ATOMIC_1` (CHANDA detector #2 — runtime DB txn wrapper around Director-action ledger writes)

**Supersedes:** prior `AUTHOR_DIRECTOR_GUARD_1` task — shipped as PR #49, merged `679a684` 2026-04-23 07:19 UTC. Mailbox cleared.

---

## Brief-route note (charter §6A)

Full `/write-brief` 6-step protocol. Brief at `briefs/BRIEF_LEDGER_ATOMIC_1.md`.

Ships CHANDA detector #2 per Research Agent's 2026-04-21 engineering-matrix sequencing (Step 3 of 4 — ENFORCEMENT_1 PR #45 + GUARD_1 PR #49 already shipped). Also includes §7 amendment-log row in `CHANDA_enforcement.md`.

---

## Context (TL;DR)

`cortex.publish_event()` commits `cortex_events` INSERT then calls `_audit_to_baker_actions()` in a SEPARATE transaction (non-blocking, log-warn-on-fail). A connection error between commits leaves a Director action present with no ledger row — CHANDA invariant #2 silently violated.

Fix: ship `invariant_checks/ledger_atomic.py` — a `@contextmanager` binding primary write + `baker_actions` ledger row into ONE transaction. Migrate `cortex.publish_event()` as the first caller. Delete the dead `_audit_to_baker_actions` function. 6 pytest scenarios prove atomicity via fault injection.

## Action

Read `briefs/BRIEF_LEDGER_ATOMIC_1.md` end-to-end. All 4 implementation blocks (helper + cortex migration + pytest + CHANDA §7 row) have copy-pasteable content.

**Files to touch:**
- NEW `invariant_checks/ledger_atomic.py` — context manager (~100 LOC, verbatim from brief).
- MODIFIED `models/cortex.py` — replace lines 238-296 of `publish_event()` with atomic-block version; delete dead `_audit_to_baker_actions` (lines 337-371 incl. section header).
- NEW `tests/test_ledger_atomic.py` — 6 hermetic sqlite3-based tests (~170 LOC).
- MODIFIED `CHANDA_enforcement.md` — +1 amendment-log row.

**Non-negotiable invariants when migrating cortex.py:**
- Do NOT change `publish_event()` signature.
- Do NOT modify dedup-gate block (lines 189-236).
- Do NOT wrap `_log_dedup_event` — informational shadow-mode log, not a ledger write.
- Keep `upsert_obligation_vector` + `_auto_queue_insights` as post-write non-blocking side-effects (they ride AFTER the atomic block).
- `_put_conn(conn)` must run exactly once on every path.

**Inline import inside function body** (matches existing lazy-import pattern at cortex.py:18):
```python
from invariant_checks.ledger_atomic import atomic_director_action
```

**Pytest approach** — hermetic in-memory sqlite3. One monkeypatch fixture swaps the helper's INSERT SQL to sqlite-compatible `?` placeholders. See brief Feature 3 for full test bodies.

## Ship gate (literal output required in ship report)

**Baseline first** — run `pytest tests/ 2>&1 | tail -3` on `main` BEFORE branching; record the `N passed, M failed` line in the ship report as your baseline.

Then, after implementation:

```
python3 -c "import py_compile; py_compile.compile('invariant_checks/ledger_atomic.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('models/cortex.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('tests/test_ledger_atomic.py', doraise=True)"
python3 -c "from invariant_checks.ledger_atomic import atomic_director_action; assert callable(atomic_director_action)"
grep -n "_audit_to_baker_actions" models/cortex.py          # expect zero matches
grep -n "atomic_director_action" models/cortex.py           # expect exactly 2 (import + with)
pytest tests/test_ledger_atomic.py -v                       # expect 6 passed
pytest tests/ 2>&1 | tail -3                                # +6 passes vs baseline, 0 regressions
bash scripts/check_singletons.sh                            # OK
grep -c "^| 2026-04" CHANDA_enforcement.md                  # 3
grep "ledger_atomic.py" CHANDA_enforcement.md               # >=1 hit
tail -1 CHANDA_enforcement.md                               # new 2026-04-23 #2 row
```

**No "pass by inspection"** (per `feedback_no_ship_by_inspection.md`). Paste literal outputs.

## Ship shape

- **PR title:** `LEDGER_ATOMIC_1: CHANDA detector #2 atomic ledger txn wrapper (cortex.publish_event migrated)`
- **Branch:** `ledger-atomic-1`
- **Files:** 4 — 2 new (helper + pytest) + 2 modified (cortex.py + CHANDA_enforcement.md).
- **Commit style:** one clean squash-ready commit. Example: `chanda(detector#2): ledger_atomic context manager + cortex.publish_event migration`
- **Ship report:** `briefs/_reports/B1_ledger_atomic_1_20260423.md`. Include all 12 Ship-gate outputs (literal), `git diff --stat`, explicit line-count delta for `models/cortex.py`, and the pre-change baseline `pytest` line.

**Tier A auto-merge on B3 APPROVE + green CI** (standing per charter §3).

## Out of scope (explicit)

- **Do NOT** migrate `clickup_client.py:146` — follow-on brief (`LEDGER_ATOMIC_CLICKUP_1`).
- **Do NOT** migrate `StoreBack.log_baker_action()` call-sites in other modules.
- **Do NOT** refactor `memory/store_back.py:3360-3397` — standalone callers still need the current behaviour.
- **Do NOT** add a live-PG test lane — hermetic sqlite3 is the standard. Live-DB smoke is an AI Head post-merge observation, not a CI test.
- **Do NOT** wrap `_log_dedup_event` or `_auto_queue_insights` — not Director-action writes.
- **Do NOT** touch `CHANDA.md` — paired rewrite is `CHANDA_PLAIN_ENGLISH_REWRITE_1`.
- **Do NOT** add §8 to `CHANDA_enforcement.md` — append ONE ROW to §7 table only.
- **Do NOT** touch `triggers/embedded_scheduler.py`, `memory/store_back.py`, `clickup_client.py` — shared-file hotspots or unrelated.

## Timebox

**2–2.5h.** If >3.5h, stop and report — likely sqlite3 fixture friction in tests.

**Working dir:** `~/bm-b1`.

---

**Dispatch timestamp:** 2026-04-23 (Team 1, M0 quintet row 2b — CHANDA detector #2)
**Team:** Team 1 — Meta/Persistence
**Sequence:** CHANDA_ENFORCEMENT_1 (PR #45) → AUTHOR_DIRECTOR_GUARD_1 (PR #49) → **LEDGER_ATOMIC_1 (this)** → MAC_MINI_WRITER_AUDIT_1 (docs) + KBL_SCHEMA_1 (parallel, queued)
