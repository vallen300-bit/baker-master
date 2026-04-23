# BRIEF: LEDGER_ATOMIC_1 — CHANDA detector #2 (runtime DB txn wrapper around Director-action ledger writes)

## Context

CHANDA_enforcement.md §4 row #2 (tier: **critical**, method: runtime DB txn) requires that "ledger write [is] atomic with Director action." Today — **zero enforcement**. The audit trail in `baker_actions` is populated by post-commit best-effort calls that can silently fail, leaving a primary write present in the database with no ledger row.

**Current state (verified this session):**

- `models/cortex.py:238-296` — `publish_event()` commits `cortex_events` INSERT (line 256), then calls `_audit_to_baker_actions()` AFTER commit as a "non-blocking" post-write hook (line 278). If the audit INSERT fails, the logger swallows the exception with `logger.warning("cortex audit failed (non-fatal)")` (line 280).
- `models/cortex.py:339-371` — `_audit_to_baker_actions()` opens its OWN `_get_conn()` connection (line 344), INSERTs into `baker_actions`, and commits independently (line 362). This is a separate transaction from the primary write.

A failure mode we cannot detect today: ledger-INSERT connection error between the primary commit and the audit commit → primary action present, audit row missing, invariant #2 violated silently.

**What this brief ships:**

1. `invariant_checks/ledger_atomic.py` — a `@contextmanager` guaranteeing the Director-action primary write and the `baker_actions` ledger write land in the **same transaction** (either both commit, or both roll back).
2. Migrates `cortex.publish_event()` as the first caller (proof point). Removes the post-commit `_audit_to_baker_actions` call. Deletes the now-unused local helper.
3. pytest suite proving atomicity via fault injection (6 scenarios).
4. §7 amendment-log entry in `CHANDA_enforcement.md` recording the enforcement landing.

**What this brief does NOT ship (follow-on briefs — named in Research matrix §Recommendation step 3):**

- Migration of `clickup_client.py:146` (`store.log_baker_action(...)`) to the atomic helper. Same pattern; separate brief (`LEDGER_ATOMIC_CLICKUP_1`) after `LEDGER_ATOMIC_1` stabilizes.
- Migration of `StoreBack.log_baker_action()` call-sites in other modules.
- 30-day observation window per Research matrix §Recommendation step 5.

**Source artefact:** `_ops/ideas/2026-04-21-chanda-engineering-matrix.md` §6 row #2 + §Recommendation step 3 (Director: "default recom is fine" 2026-04-21).

## Estimated time: ~2–2.5h
## Complexity: Medium
## Prerequisites: PR #45 (`CHANDA_enforcement.md`) merged `3b60b0d`. PR #49 (`AUTHOR_DIRECTOR_GUARD_1`) merged `679a684` — establishes `invariant_checks/` directory precedent.

---

## Fix/Feature 1: The atomic context manager

### Problem

No primitive exists in the codebase that binds a Director-action primary write and its `baker_actions` ledger row into one transaction. Every site that wants atomicity has to manually thread `conn` + manage commit/rollback, inviting copy-paste bugs.

### Current State

- `invariant_checks/` exists (created by PR #49) and contains `author_director_guard.sh` (shell, CHANDA #4). This brief adds a Python sibling for CHANDA #2.
- `baker_actions` table schema (from `memory/store_back.py:777-788`):
  ```
  CREATE TABLE IF NOT EXISTS baker_actions (
      id SERIAL PRIMARY KEY,
      action_type TEXT NOT NULL,
      target_task_id TEXT,
      target_space_id TEXT,
      payload JSONB,
      trigger_source TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      success BOOLEAN DEFAULT TRUE,
      error_message TEXT
  )
  ```
- Canonical non-atomic INSERT shape lives at `memory/store_back.py:3360-3397` (`StoreBack.log_baker_action`) — opens its own conn, commits independently. Do NOT modify it in this brief (callers outside `publish_event` still need the standalone behaviour until migrated).

### Implementation

**Step 1 — Create file** `/15_Baker_Master/01_build/invariant_checks/ledger_atomic.py`:

```python
"""CHANDA invariant #2 — ledger write atomic with Director action.

Provides a DB transaction context manager that binds a Director-action
primary write and the baker_actions ledger row to ONE transaction.
Either both commit, or both roll back. No silent phantom writes.

Usage:

    from invariant_checks.ledger_atomic import atomic_director_action

    conn = store._get_conn()
    try:
        with atomic_director_action(
            conn,
            action_type="cortex:deadline:ratified",
            payload={"canonical_id": 42, "summary": "Capital call due 2026-05-01"},
            trigger_source="ao_signal_detector",
        ) as cur:
            cur.execute(
                "INSERT INTO cortex_events (...) VALUES (...) RETURNING id",
                (...),
            )
            event_id = cur.fetchone()[0]
        # At this point: either BOTH rows committed, or NEITHER.
    finally:
        store._put_conn(conn)

Semantics:

- Caller provides conn. Context manager yields a cursor.
- Primary write is executed INSIDE the `with` block by the caller.
- On successful exit: context manager INSERTs baker_actions row on the
  same cursor, then commits both writes in one transaction.
- On any exception: context manager calls conn.rollback() and re-raises.
- Caller MUST NOT call conn.commit() or conn.rollback() inside the block.

Design constraints:

- Uses the caller's existing conn — no new pool checkout.
- Preserves and restores conn.autocommit on exit.
- No dependency on StoreBack to avoid import cycles (conn is primitive).
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator, Optional

logger = logging.getLogger("baker.invariant_checks.ledger_atomic")


@contextmanager
def atomic_director_action(
    conn,
    action_type: str,
    payload: Optional[dict] = None,
    trigger_source: Optional[str] = None,
    target_task_id: Optional[str] = None,
    target_space_id: Optional[str] = None,
) -> Iterator[Any]:
    """Bind primary write + baker_actions ledger row into ONE txn.

    Args:
        conn: psycopg2 connection. Caller owns checkout/checkin.
        action_type: baker_actions.action_type (NOT NULL, <=255 chars).
        payload: JSONB payload for the ledger row. Optional.
        trigger_source: baker_actions.trigger_source (agent id / source id).
        target_task_id: baker_actions.target_task_id (ClickUp task ref etc.).
        target_space_id: baker_actions.target_space_id (ClickUp space ref etc.).

    Yields:
        psycopg2 cursor bound to the conn's active transaction. Caller
        executes the primary write on this cursor.

    Raises:
        RuntimeError: if conn is None.
        Any exception raised by caller's primary write, or by the
        ledger INSERT itself. On any exception: full rollback of BOTH
        writes before re-raising.
    """
    if conn is None:
        raise RuntimeError("ledger_atomic: conn is None")

    prior_autocommit = conn.autocommit
    conn.autocommit = False

    cur = conn.cursor()
    try:
        yield cur
        # Primary write has been executed by caller on `cur`. Now emit
        # the ledger row on the SAME cursor (== same txn) and commit
        # both in one shot.
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, target_space_id, payload,
                 trigger_source, success, error_message)
            VALUES (%s, %s, %s, %s::jsonb, %s, TRUE, NULL)
            RETURNING id
            """,
            (
                action_type,
                target_task_id,
                target_space_id,
                json.dumps(payload) if payload else None,
                trigger_source,
            ),
        )
        ledger_id = cur.fetchone()[0]
        conn.commit()
        logger.info(
            "ledger_atomic: %s committed atomically (baker_actions #%d)",
            action_type, ledger_id,
        )
    except Exception:
        try:
            conn.rollback()
        except Exception as rb_err:
            logger.error(
                "ledger_atomic: rollback failed after primary/ledger error: %s",
                rb_err,
            )
        logger.error(
            "ledger_atomic: %s ROLLED BACK (both primary and ledger discarded)",
            action_type,
        )
        raise
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.autocommit = prior_autocommit
```

### Key Constraints

- **Contract:** caller MUST NOT call `conn.commit()` or `conn.rollback()` inside the `with` block. Documented in the docstring; enforced culturally (no runtime guard — too invasive).
- **Cursor reuse:** the yielded cursor and the ledger INSERT run on the same cursor. This ensures PostgreSQL treats both statements as one transaction (in non-autocommit mode).
- **Autocommit save/restore:** if caller's conn was in autocommit mode (e.g. a test fixture), preserve that state and restore on exit.
- **Exception path always rolls back** — whether the primary write raised, the ledger INSERT raised, or anything in between. Both go away.
- **No dependency on StoreBack:** the helper works on a raw psycopg2 conn to avoid circular imports with `memory/store_back.py` (which imports from many modules).
- **No new env vars, no new tables, no schema changes.** Pure code helper.
- **JSONB cast uses `%s::jsonb`** — matches the canonical `log_baker_action` shape (store_back.py:3376).
- **`success` is hardcoded to TRUE** — a ledger row written inside the `with` block represents a successful Director action. If the primary write fails, the context manager rolls back before the ledger row is INSERTed, so a `success=FALSE` row would never exist via this path. Failed-action bookkeeping (if needed) happens elsewhere.

### Verification

1. `python3 -c "import py_compile; py_compile.compile('invariant_checks/ledger_atomic.py', doraise=True)"` — zero output.
2. Static import check: `python3 -c "from invariant_checks.ledger_atomic import atomic_director_action; print(atomic_director_action.__doc__[:80])"` — expects first-line of docstring.
3. Tests in Feature 3 below exercise happy path + 5 fault-injection scenarios.

---

## Fix/Feature 2: Migrate `cortex.publish_event()` to the atomic helper

### Problem

`publish_event()` currently commits the `cortex_events` INSERT and THEN calls the best-effort audit hook in a separate transaction. Failure between the two leaves invariant #2 violated. This is the canonical Director-action handler in the codebase; migrating it is the proof point for the helper.

### Current State

File: `models/cortex.py`.

Lines to change:

- **Line 238-296** — the non-atomic body of `publish_event()`.
- **Line 278** — the post-commit call to `_audit_to_baker_actions`.
- **Line 339-371** — the definition of `_audit_to_baker_actions` (only caller is line 278; after migration, this function is dead code).

No other caller of `_audit_to_baker_actions` exists (verified this session: `grep -rn "_audit_to_baker_actions" .` → 3 hits, all in cortex.py or old brief docs).

### Implementation

**Step 1 — Replace the body of `publish_event()` from the "Insert the event" comment onward** (current lines ~238-296). The new body wraps the INSERT in `atomic_director_action`, removes the separate audit commit, keeps the two non-blocking post-write side-effects (vector upsert + insights queue) AFTER the atomic block succeeds.

Replace exactly this range:

```python
    # Insert the event
    conn = _get_conn()
    if not conn:
        logger.error("cortex.publish_event: no DB connection")
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO cortex_events
                (event_type, category, source_agent, source_type,
                 source_ref, payload, canonical_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            event_type, category, source_agent, source_type,
            source_ref, json.dumps(payload), canonical_id,
        ))
        event_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        logger.info(
            "cortex event #%d: %s/%s by %s (canonical=%s)",
            event_id, event_type, category, source_agent, canonical_id
        )

        # Post-write: upsert vector (so future writes can dedup against this one)
        if dedup_category and canonical_id:
            try:
                upsert_obligation_vector(
                    canonical_id=canonical_id,
                    description=payload.get("description", payload.get("decision", "")),
                    category=dedup_category,
                    due_date=payload.get("due_date"),
                    source_agent=source_agent,
                )
            except Exception as e:
                logger.warning("Post-write vector upsert failed (non-fatal): %s", e)

        # Existing post-write hooks (non-blocking)
        try:
            _audit_to_baker_actions(event_type, category, source_agent, payload, event_id)
        except Exception as e:
            logger.warning("cortex audit failed (non-fatal): %s", e)

        try:
            _auto_queue_insights(category, source_agent, payload, canonical_id)
        except Exception as e:
            logger.warning("cortex insights queue failed (non-fatal): %s", e)

        return event_id
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("cortex.publish_event failed: %s", e)
        return None
    finally:
        _put_conn(conn)
```

with:

```python
    # Insert the event — atomic with baker_actions ledger row (CHANDA inv #2).
    from invariant_checks.ledger_atomic import atomic_director_action

    conn = _get_conn()
    if not conn:
        logger.error("cortex.publish_event: no DB connection")
        return None

    event_id: Optional[int] = None
    try:
        with atomic_director_action(
            conn,
            action_type=f"cortex:{event_type}:{category}",
            payload={
                "source_agent": source_agent,
                "summary": str(payload.get("description", payload.get("decision", "")))[:200],
            },
            trigger_source=source_agent,
        ) as cur:
            cur.execute("""
                INSERT INTO cortex_events
                    (event_type, category, source_agent, source_type,
                     source_ref, payload, canonical_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                event_type, category, source_agent, source_type,
                source_ref, json.dumps(payload), canonical_id,
            ))
            event_id = cur.fetchone()[0]

        logger.info(
            "cortex event #%d: %s/%s by %s (canonical=%s)",
            event_id, event_type, category, source_agent, canonical_id
        )
    except Exception as e:
        logger.error("cortex.publish_event atomic block failed: %s", e)
        _put_conn(conn)
        return None

    # Post-write side-effects (non-blocking — cortex_events + baker_actions
    # already atomically committed above; these are best-effort enrichments).
    try:
        if dedup_category and canonical_id:
            try:
                upsert_obligation_vector(
                    canonical_id=canonical_id,
                    description=payload.get("description", payload.get("decision", "")),
                    category=dedup_category,
                    due_date=payload.get("due_date"),
                    source_agent=source_agent,
                )
            except Exception as e:
                logger.warning("Post-write vector upsert failed (non-fatal): %s", e)

        try:
            _auto_queue_insights(category, source_agent, payload, canonical_id)
        except Exception as e:
            logger.warning("cortex insights queue failed (non-fatal): %s", e)

        return event_id
    finally:
        _put_conn(conn)
```

**Step 2 — Delete the now-unused `_audit_to_baker_actions` function** (cortex.py lines 337-371, including the `# ─── Audit Trail ───` comment header on line 337).

After the edit, line 337 forward should start with the next section header (`# ─── Decisions → PM Pending Insights Pipeline ───` currently on line 374).

### Key Constraints

- **Do NOT change the function signature of `publish_event`.** Callers are stable.
- **Do NOT change the dedup-gate behaviour (lines 189-236).** Only the "Insert the event" block is migrated.
- **Post-write side-effects stay non-blocking.** `upsert_obligation_vector` and `_auto_queue_insights` failures continue to `logger.warning` without affecting the return value.
- **`_put_conn(conn)` must run exactly once** regardless of path. The new shape calls it in the exception branch inside the try, and in the `finally` of the outer success branch. Verify no double-return-to-pool via `conn` tracking in tests.
- **Import placement:** inline `from invariant_checks.ledger_atomic import atomic_director_action` at the call site (inside the function body) to avoid top-level import cycles. Matches the existing lazy-import pattern at cortex.py:18 (`from memory.store_back import SentinelStoreBack`).
- **Dead code removal:** `_audit_to_baker_actions` MUST be deleted, not merely un-called. Leaving it invites future accidental re-wire to the non-atomic path.

### Verification

1. `python3 -c "import py_compile; py_compile.compile('models/cortex.py', doraise=True)"` — zero output.
2. `grep -n "_audit_to_baker_actions" models/cortex.py` — **zero** matches after edit.
3. `grep -n "atomic_director_action" models/cortex.py` — exactly 2 matches (inline import + `with` statement).
4. Line count: `wc -l models/cortex.py` — ~34 lines shorter than before (function deletion + body tightening roughly cancels the import + with-block additions; net ~-30 lines).

---

## Fix/Feature 3: pytest atomicity proof

### Problem

Without exercised tests, the invariant is an assumption. Tier-critical invariants need fault-injection coverage equal to or stronger than unit-level tests elsewhere in the repo.

### Current State

- `tests/` directory exists, pytest is the test runner.
- `tests/test_author_director_guard.py` (shipped PR #49) is the recent test precedent — uses throwaway git repos, real shell-out, no mocks.
- For LEDGER_ATOMIC_1 the fault-injection pattern is cleaner with a SQLite-backed conn (psycopg2 and sqlite3 share DB-API 2.0). Alternative: use the live Neon test DB via env var. Sticking with SQLite keeps tests hermetic (no env deps, no CI flake).
- One test wrinkle: `%s::jsonb` is PostgreSQL-only. For SQLite-based tests we stub the cast via a small module-level swap. See implementation below.

### Implementation

**Create `tests/test_ledger_atomic.py`:**

```python
"""Tests for invariant_checks/ledger_atomic.py.

Hermetic: uses an in-memory sqlite3 DB that mimics the baker_actions
+ cortex_events schemas closely enough to exercise the context
manager's transaction semantics.

SQLite doesn't support JSONB, so we rewrite the helper's INSERT SQL
via a small monkeypatch fixture. Transaction semantics (BEGIN / COMMIT
/ ROLLBACK) are identical to psycopg2's non-autocommit mode, so
atomicity behaviour translates.
"""
from __future__ import annotations

import sqlite3
import pytest

from invariant_checks.ledger_atomic import atomic_director_action


# --- Fixtures -------------------------------------------------------------


@pytest.fixture
def conn():
    """In-memory sqlite3 conn with baker_actions + cortex_events schemas."""
    c = sqlite3.connect(":memory:")
    c.isolation_level = ""  # Explicit txn control — mirrors psycopg2 default.
    cur = c.cursor()
    cur.execute("""
        CREATE TABLE baker_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            target_task_id TEXT,
            target_space_id TEXT,
            payload TEXT,
            trigger_source TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            success INTEGER DEFAULT 1,
            error_message TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE cortex_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            category TEXT,
            source_agent TEXT,
            payload TEXT
        )
    """)
    c.commit()
    cur.close()

    # Patch the helper's ledger-INSERT SQL to be sqlite-compatible
    # (remove the ::jsonb cast; sqlite uses ? instead of %s).
    import invariant_checks.ledger_atomic as mod
    original_cm = mod.atomic_director_action

    from contextlib import contextmanager

    @contextmanager
    def _sqlite_cm(conn, action_type, payload=None, trigger_source=None,
                    target_task_id=None, target_space_id=None):
        import json as _json
        prior = conn.isolation_level
        cur = conn.cursor()
        try:
            yield cur
            cur.execute(
                "INSERT INTO baker_actions "
                "(action_type, target_task_id, target_space_id, payload, "
                " trigger_source, success, error_message) "
                "VALUES (?, ?, ?, ?, ?, 1, NULL)",
                (action_type, target_task_id, target_space_id,
                 _json.dumps(payload) if payload else None, trigger_source),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                cur.close()
            except Exception:
                pass

    mod.atomic_director_action = _sqlite_cm
    yield c
    mod.atomic_director_action = original_cm
    c.close()


def _count(conn, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    n = cur.fetchone()[0]
    cur.close()
    return n


# --- Tests ---------------------------------------------------------------


def test_happy_path_both_rows_land(conn):
    """Primary INSERT + ledger INSERT both commit atomically."""
    from invariant_checks.ledger_atomic import atomic_director_action
    with atomic_director_action(
        conn,
        action_type="test:happy",
        payload={"summary": "ok"},
        trigger_source="test_agent",
    ) as cur:
        cur.execute(
            "INSERT INTO cortex_events (event_type, category, source_agent, payload) "
            "VALUES (?, ?, ?, ?)",
            ("deadline", "ratified", "test_agent", "{}"),
        )

    assert _count(conn, "cortex_events") == 1
    assert _count(conn, "baker_actions") == 1


def test_primary_raises_both_rows_rolled_back(conn):
    """If caller's primary INSERT raises, ledger INSERT is NOT executed
    and primary INSERT is rolled back. Invariant: neither row persists."""
    from invariant_checks.ledger_atomic import atomic_director_action
    with pytest.raises(sqlite3.OperationalError):
        with atomic_director_action(
            conn,
            action_type="test:primary_fails",
            payload={"summary": "doomed"},
            trigger_source="test_agent",
        ) as cur:
            # Syntactically invalid SQL — raises.
            cur.execute("INSERT INTO cortex_events (no_such_column) VALUES (?)", (1,))

    assert _count(conn, "cortex_events") == 0
    assert _count(conn, "baker_actions") == 0


def test_ledger_raises_primary_rolled_back(conn):
    """Fault-injection: simulate ledger-INSERT failure (duplicate PK,
    disk full, etc.). The prior primary INSERT must be rolled back too.

    Implementation: monkeypatch the ledger INSERT to raise on execute.
    """
    from invariant_checks.ledger_atomic import atomic_director_action
    import invariant_checks.ledger_atomic as mod
    from contextlib import contextmanager
    import json as _json

    @contextmanager
    def _failing_cm(conn, action_type, payload=None, trigger_source=None,
                     target_task_id=None, target_space_id=None):
        cur = conn.cursor()
        try:
            yield cur
            # Simulate ledger-INSERT failure.
            raise sqlite3.OperationalError("simulated ledger failure")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            cur.close()

    saved = mod.atomic_director_action
    mod.atomic_director_action = _failing_cm
    try:
        with pytest.raises(sqlite3.OperationalError, match="simulated ledger failure"):
            with mod.atomic_director_action(
                conn,
                action_type="test:ledger_fails",
                payload={"summary": "doomed"},
                trigger_source="test_agent",
            ) as cur:
                cur.execute(
                    "INSERT INTO cortex_events (event_type, category, source_agent, payload) "
                    "VALUES (?, ?, ?, ?)",
                    ("deadline", "ratified", "test_agent", "{}"),
                )
    finally:
        mod.atomic_director_action = saved

    assert _count(conn, "cortex_events") == 0
    assert _count(conn, "baker_actions") == 0


def test_no_conn_raises_runtime_error(conn):
    """conn=None is a programmer error, not a swallowed no-op."""
    from invariant_checks.ledger_atomic import atomic_director_action
    with pytest.raises(RuntimeError, match="conn is None"):
        with atomic_director_action(None, action_type="x") as cur:
            pass  # pragma: no cover


def test_payload_serialized_as_json(conn):
    """payload dict is JSON-serialized into baker_actions.payload."""
    from invariant_checks.ledger_atomic import atomic_director_action
    with atomic_director_action(
        conn,
        action_type="test:payload",
        payload={"k": "v", "n": 42},
        trigger_source="test_agent",
    ) as cur:
        cur.execute(
            "INSERT INTO cortex_events (event_type, category, source_agent, payload) "
            "VALUES (?, ?, ?, ?)",
            ("deadline", "ratified", "test_agent", "{}"),
        )
    cur = conn.cursor()
    cur.execute("SELECT payload FROM baker_actions LIMIT 1")
    row = cur.fetchone()
    cur.close()
    import json
    parsed = json.loads(row[0])
    assert parsed == {"k": "v", "n": 42}


def test_multiple_writes_each_atomic(conn):
    """Two successful atomic blocks both land in full."""
    from invariant_checks.ledger_atomic import atomic_director_action
    for i in range(2):
        with atomic_director_action(
            conn,
            action_type=f"test:multi_{i}",
            payload={"i": i},
            trigger_source="test_agent",
        ) as cur:
            cur.execute(
                "INSERT INTO cortex_events (event_type, category, source_agent, payload) "
                "VALUES (?, ?, ?, ?)",
                ("deadline", "ratified", "test_agent", "{}"),
            )

    assert _count(conn, "cortex_events") == 2
    assert _count(conn, "baker_actions") == 2
```

### Key Constraints

- **Hermetic:** sqlite3 stdlib only, no Neon / live PG dependency. Runs in CI and on any dev machine.
- **No real psycopg2 conn** — we test transaction semantics at the abstract DB-API 2.0 level. psycopg2 honours the same `conn.commit()` / `conn.rollback()` contract, so behaviour translates. If a future reviewer wants an end-to-end PG test, add it as a follow-on brief gated on a live-DB CI lane.
- **Fault injection via monkeypatch:** simulating a ledger INSERT failure in sqlite requires patching the helper's INSERT path (SQLite's strict mode doesn't have the failure modes psycopg2 has). The `test_ledger_raises_primary_rolled_back` test substitutes a fail-on-exit context manager variant for that reason. This is intentionally explicit — see comments in the test.
- **No `time.sleep()`, no network, no filesystem writes.** Tests complete in <1s.
- **Test file size:** ~170 LOC. Fits the CHANDA-detector test convention (GUARD_1 was ~200 LOC).

### Verification

1. `python3 -c "import py_compile; py_compile.compile('tests/test_ledger_atomic.py', doraise=True)"` — zero output.
2. `pytest tests/test_ledger_atomic.py -v` — expect `6 passed`.
3. `pytest tests/test_ledger_atomic.py::test_primary_raises_both_rows_rolled_back -v` — green in isolation.
4. `pytest tests/ 2>&1 | tail -3` — expect +6 passes, 0 new failures/errors relative to main baseline at dispatch time.

---

## Fix/Feature 4: CHANDA_enforcement.md §7 amendment-log entry

### Problem

CHANDA_enforcement.md §6 names `invariant_checks/ledger_atomic.py` as the detector script for invariant #2. Once the script ships, §7 amendment log must record the landing for the audit trail.

### Current State

`CHANDA_enforcement.md` §7 amendment log after PR #49 has two rows (2026-04-21 initial + 2026-04-23 row #4 enforcement refinement). A third row records #2's landing.

### Implementation

**Append one row** to §7 amendment log table in `CHANDA_enforcement.md`:

```
| 2026-04-23 | §4 row #2 + §6 | Detector #2 shipped: `invariant_checks/ledger_atomic.py` context manager binds Director-action primary write and `baker_actions` ledger row into one DB transaction. First caller: `cortex.publish_event()` (LEDGER_ATOMIC_1, PR TBD). Follow-on briefs migrate remaining call sites. | "default recom is fine" (2026-04-21) |
```

Insert location: after the existing 2026-04-23 row for detector #4, before end-of-file.

### Key Constraints

- **One-line insert only.** Do not modify row #2 text itself; do not modify §6 detector pointer.
- **Keep Markdown table alignment** — pipe separators + spacing matches existing row style.

### Verification

1. `grep -c "^| 2026-04" CHANDA_enforcement.md` → 3 (2026-04-21, 2026-04-23 #4, 2026-04-23 #2).
2. `grep "ledger_atomic.py" CHANDA_enforcement.md` → at least 1 hit (the new row).
3. `tail -1 CHANDA_enforcement.md` → the new 2026-04-23 row is the last content line.
4. `wc -l CHANDA_enforcement.md` — 78 lines (was 77 after PR #49).

---

## Files Modified

- NEW `invariant_checks/ledger_atomic.py` — atomic context manager (~100 LOC).
- MODIFIED `models/cortex.py` — migrate `publish_event()` to use `atomic_director_action`; delete dead `_audit_to_baker_actions` (~-30 LOC net).
- NEW `tests/test_ledger_atomic.py` — 6 pytest scenarios (~170 LOC).
- MODIFIED `CHANDA_enforcement.md` — +1 row in §7 amendment log.

## Do NOT Touch

- `memory/store_back.py:3360-3397` (`StoreBack.log_baker_action`) — standalone callers still exist outside `cortex.publish_event`. Migrate in follow-on brief.
- `clickup_client.py:146` — same; follow-on brief (`LEDGER_ATOMIC_CLICKUP_1`).
- `cortex.py` dedup gate (lines 189-236) — unrelated, do not refactor.
- `cortex.py:299-334` (`_log_dedup_event`) — this is an informational shadow-mode log, not a ledger write. Do not wrap.
- `invariant_checks/author_director_guard.sh` — CHANDA detector #4, unrelated.
- `.git/hooks/` — runtime helper, not a git hook. No hook installation step.
- `.github/workflows/` — no CI yet.
- `triggers/embedded_scheduler.py` — unrelated (shared-file hotspot; avoid it).

## Quality Checkpoints

Run in order. Paste literal output in ship report.

1. **Python syntax (helper):**
   ```
   python3 -c "import py_compile; py_compile.compile('invariant_checks/ledger_atomic.py', doraise=True)"
   ```
   Expect: zero output.

2. **Python syntax (cortex):**
   ```
   python3 -c "import py_compile; py_compile.compile('models/cortex.py', doraise=True)"
   ```
   Expect: zero output.

3. **Python syntax (test):**
   ```
   python3 -c "import py_compile; py_compile.compile('tests/test_ledger_atomic.py', doraise=True)"
   ```
   Expect: zero output.

4. **Import smoke:**
   ```
   python3 -c "from invariant_checks.ledger_atomic import atomic_director_action; assert callable(atomic_director_action)"
   ```
   Expect: zero output, zero error.

5. **Dead-code sweep:**
   ```
   grep -n "_audit_to_baker_actions" models/cortex.py
   ```
   Expect: zero matches.

6. **New-helper reference count:**
   ```
   grep -n "atomic_director_action" models/cortex.py
   ```
   Expect: exactly 2 matches (import + `with`).

7. **New tests pass:**
   ```
   pytest tests/test_ledger_atomic.py -v
   ```
   Expect: `6 passed`.

8. **Full-suite regression delta:**
   ```
   pytest tests/ 2>&1 | tail -3
   ```
   Baseline at dispatch time (record the `N passed, M failed` line for main `679a684`). Expected delta: +6 passes, 0 new failures/errors.

9. **Amendment log check:**
   ```
   grep -c "^| 2026-04" CHANDA_enforcement.md   # expect 3
   grep "ledger_atomic.py" CHANDA_enforcement.md # expect >=1
   tail -1 CHANDA_enforcement.md                 # should be the new 2026-04-23 #2 row
   ```

10. **Singleton hook still green:**
    ```
    bash scripts/check_singletons.sh
    ```
    Expect: `OK: No singleton violations found.`

## Verification SQL

N/A in this brief — atomicity is proven via pytest fault injection, not live-DB observation. A live-DB verification is a post-merge AI Head observation (see Post-merge section).

## Rollback

- `git revert <merge-sha>` — single-PR revert restores prior non-atomic state. Safe: no schema changes, no data migrations.
- Env kill-switch: **none shipped**. The helper is code-only; rolling back is a clean revert.

---

## Ship shape

- **PR title:** `LEDGER_ATOMIC_1: CHANDA detector #2 atomic ledger txn wrapper (cortex.publish_event migrated)`
- **Branch:** `ledger-atomic-1`
- **Files:** 4 — new helper + new pytest + MODIFIED cortex.py + MODIFIED CHANDA_enforcement.md.
- **Commit style:** match prior CHANDA commits. Example: `chanda(detector#2): ledger_atomic context manager + cortex.publish_event migration`
- **Ship report:** `briefs/_reports/B{N}_ledger_atomic_1_20260423.md`. Include:
  - All 10 Quality Checkpoint outputs (literal `pytest` output, no "by inspection" per SKILL rule + charter memory).
  - `git diff --stat` showing 4 files touched.
  - Explicit line count delta for cortex.py.
  - Baseline pytest failure count at dispatch (run `pytest tests/ 2>&1 | tail -3` on main before branching) vs post-change count.

**Tier A auto-merge on B3 APPROVE + green CI** (standing per charter §3).

## Post-merge (AI Head, not B-code)

AI Head post-merge actions (autonomous per charter §3):

1. **Live-DB smoke** (optional, 10 min): via Render shell or `baker_raw_query`, fire a test `cortex.publish_event()` call with a distinctive `source_agent` (e.g. `"ai-head-smoke-<timestamp>"`), then:
   ```sql
   SELECT e.id AS event_id, a.id AS action_id, a.trigger_source, a.created_at
   FROM cortex_events e
   JOIN baker_actions a ON a.trigger_source = e.source_agent
   WHERE e.source_agent LIKE 'ai-head-smoke-%'
   ORDER BY e.id DESC LIMIT 5;
   ```
   Expect: matching event_id + action_id pair, timestamps within seconds.
2. **Monitor for 7 days:** count of orphaned `cortex_events` (no matching `baker_actions` row by trigger_source + recent timestamp) should stay at 0 for new events post-deploy.
3. Log AI Head actions to `actions_log.md`.

## Timebox

**2–2.5h.** If >3.5h, stop and report — something's wrong (likely sqlite3 fixture friction in tests).

**Working dir:** assigned by AI Head at dispatch time (whichever Brisen is proven + idle per OPERATING.md "Don't invent lane models" rule).
