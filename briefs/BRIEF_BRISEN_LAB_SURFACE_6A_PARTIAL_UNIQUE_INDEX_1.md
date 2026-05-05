# BRIEF: BRISEN-LAB-SURFACE-6A-PARTIAL-UNIQUE-INDEX-1 — DB-level enforcement of "at most one active session_key per worker_slug"

## Context

Surface 6 (V0.3.7 Item 3 bundle, brisen-lab merge `bc1e3e6` 2026-05-05) ships atomic UPDATE+INSERT in `register_session_pubkey()` to expire prior rows + insert the new row in a single transaction. Solves the unbounded-row-accumulation problem (V0.3.7 per-prompt re-registration → 50-200× V0.3.6 row rate).

**Open race (gate-4 LOW L1, code-reviewer agent flagged on PR #157):** two concurrent `POST /auth/register-session-pubkey` calls for the same `worker_slug` under default psycopg2 READ COMMITTED isolation can BOTH pass the UPDATE step with zero matching rows in their respective snapshots, then both INSERT → two active rows for the same worker_slug at end-of-cascade. Bypasses Surface 6's intent.

This brief lands a **partial unique index** on `(worker_slug) WHERE expired_at IS NULL` so the DB rejects the second INSERT with `UniqueViolation`. Surface 6a is the **pre-cutover gate** — must ship before `BRISEN_LAB_V2_ENABLED=true` is flipped.

**Estimated time:** ~3-4 hours
**Complexity:** Low (single migration + small handler change + 1 regression test)
**Prerequisites:** brisen-lab main HEAD `bc1e3e6` (Surface 6 merged)
**Tier:** A (DB schema change with no auth-surface change; `feature-dev:code-reviewer` standard pass; `/security-review` NOT mandatory — NOT auth-touching beyond hardening existing surface)

**Director ratification:** 2026-05-05 chat ("agreed" → "go Surface 6a") — pre-cutover gate per V2_BRIDGE_1 cascade path-forward.

---

## Design Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Partial unique index, not full table unique** | `WHERE expired_at IS NULL` so historical (expired) rows for the same worker_slug remain valid. Matches Surface 6's "expire prior + insert new" semantics. |
| 2 | **Migration uses `CREATE UNIQUE INDEX CONCURRENTLY`** | Avoids table-write lock during index creation. Production `brisen_lab_session_keys` is small today (rows: a few hundred max) so plain `CREATE` would also work, but CONCURRENTLY is best practice for a hot table behind cutover-flag-gated traffic. |
| 3 | **Index name: `uq_session_keys_worker_active`** | Distinct from existing non-unique `idx_session_keys_worker_active`. Both can coexist temporarily; old index dropped in same migration after new one creates clean. |
| 4 | **Drop old non-unique partial index `idx_session_keys_worker_active`** | New unique index satisfies the same query path (`SELECT ... WHERE worker_slug=%s AND expired_at IS NULL`). Keeping both wastes space + adds write-cost on every INSERT/UPDATE. |
| 5 | **Handler change: catch `psycopg2.errors.UniqueViolation` specifically** | Returns structured `409 Conflict` with `error="concurrent_registration_lost_race"`. Generic `except Exception` → 400 still wraps everything else. **Architect post-WRITE correction:** the V0.3.7 hook does NOT retry on non-200 today (verified at `.claude/hooks/user-prompt-submit-confirm.py:216-217` — `if resp.status_code != 200: return None`). 409 today = silent fail-open → next ratify_decision hits 403. Feature 5 (NEW, this brief) adds single retry-on-409 with jitter to make the gate idempotent under contention. Cross-repo scope: 1 file in baker-master, alongside brisen-lab migration + handler. |
| 6 | **Regression test: concurrent INSERT scenario** | Two threads call `_register()` simultaneously against the test DB (using existing `TEST_DATABASE_URL_BRISEN_LAB` infrastructure). Asserts: exactly ONE row remains active post-race; the loser receives 409 with the expected error string. |
| 7 | **Migration filename + lock refresh** | `migrations/<UTC-timestamp>_session_keys_partial_unique_index.sql`. Refresh `applied_migrations.lock` from prod after apply per migration-immutability rule. **Verify timestamp differs by ≥1s from any sibling migrations to avoid collision.** |
| 8 | **NOT in scope: serializable isolation level for `_register()`** | Considered + rejected. SERIALIZABLE adds `could not serialize access` retry burden across the entire endpoint surface; partial unique index is the surgical primitive that addresses THIS race without ripple. |
| 9 | **NOT in scope: rate-limiting per worker_slug** | Different concern. If concurrent registration spam becomes operational pain, separate brief. |
| 10 | **Pre-cutover blocker:** `BRISEN_LAB_V2_ENABLED=true` flip MUST NOT happen until this brief ships clean. Documented in `_ops/processes/v2-bridge-cutover-runbook.md` (NEW or amended in this brief). |

---

## Feature 1: Migration — partial unique index

### Problem
Surface 6 prevents app-level row accumulation but DOES NOT prevent concurrent race producing duplicate active rows.

### Implementation

**NEW file:** `migrations/<UTC-timestamp>_session_keys_partial_unique_index.sql` (in brisen-lab repo, NOT baker-master)

```sql
-- BRISEN-LAB-SURFACE-6A-PARTIAL-UNIQUE-INDEX-1
-- DB-level enforcement: at most one active session_key per worker_slug.
-- Closes Surface 6 race window (concurrent register-session-pubkey calls).
-- Replaces existing non-unique idx_session_keys_worker_active with unique variant.

-- Step 1: create new unique partial index (concurrent, idempotent)
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_session_keys_worker_active
    ON brisen_lab_session_keys (worker_slug)
    WHERE expired_at IS NULL;

-- Step 2: drop old non-unique partial index (CONCURRENTLY for symmetry / online-safety)
DROP INDEX CONCURRENTLY IF EXISTS idx_session_keys_worker_active;

-- Step 3 (post-apply verification — NOT in migration file; runs as separate ship-report check):
-- SELECT indisvalid FROM pg_index WHERE indexrelid = 'uq_session_keys_worker_active'::regclass;
-- Must return TRUE. CONCURRENTLY can leave INVALID indexes on duplicate-mid-build that
-- silently mask future re-runs via IF NOT EXISTS. If FALSE: DROP INDEX uq_session_keys_worker_active;
-- clean duplicates; re-run migration.
```

**CRITICAL pre-work — verify migration runner handles CONCURRENTLY:** B-code MUST inspect `~/bm-b4-brisen-lab/start.sh` (or whichever script applies migrations on Render boot) BEFORE writing the migration. `CREATE/DROP INDEX CONCURRENTLY` cannot run inside a transaction block. If the runner wraps every `.sql` file in `BEGIN…COMMIT`, the migration fails with `cannot run inside a transaction block`. Two paths if so: (a) modify the runner to detect `CONCURRENTLY` keyword + execute outside transaction, OR (b) split into two files — `<ts>_create_uq_session_keys.sql` (CONCURRENTLY-aware path) and `<ts>_drop_idx_session_keys.sql`. **Ship-blocker if not resolved.** Surface this finding to AH1 if runner is incompatible — design check before code work.

**Pre-apply check:** if there are existing duplicate active rows in prod (Surface 6 race already fired before this brief lands), the unique index creation will FAIL with constraint violation. Check + clean first:

```sql
-- Run BEFORE migration; expect 0 rows
SELECT worker_slug, COUNT(*)
FROM brisen_lab_session_keys
WHERE expired_at IS NULL
GROUP BY worker_slug
HAVING COUNT(*) > 1;
```

If any rows return: pick the most recently registered as winner, mark others `expired_at = NOW()`, then re-run the migration.

### Key constraints
- **Idempotent:** `IF NOT EXISTS` + `IF EXISTS` on both steps.
- **Online-safe:** CONCURRENTLY allows reads + writes during creation.
- **No data loss:** existing rows untouched.
- **Old index drop is safe:** new unique index covers the same `WHERE expired_at IS NULL` query path; pg planner picks unique index automatically.

---

## Feature 2: Handler — UniqueViolation handling

### Problem
Generic `except Exception → 400` swallows the race-loser case with non-specific error.

### Implementation

**File:** `bus.py` (brisen-lab repo, lines 641-672 — `_register()` + outer try/except)

Update outer try/except in `register_session_pubkey()`:

```python
try:
    out = await asyncio.to_thread(_register)
except psycopg2.errors.UniqueViolation:
    # Surface 6a: concurrent registration lost the race.
    # Hook MAY retry SessionStart; the winning registration's session_id
    # is what the worker uses going forward.
    raise HTTPException(
        status_code=409,
        detail={"error": "concurrent_registration_lost_race"},
    )
except Exception as e:
    # FK violation → unknown worker_slug. Surface 400 (deploy hygiene
    # — should never hit if seed ran).
    print(f"[register_session_pubkey] {e}", file=sys.stderr, flush=True)
    raise HTTPException(status_code=400, detail="register_failed")
```

Import addition at top of `bus.py`:

```python
import psycopg2.errors
```

(or `from psycopg2 import errors as pg_errors` if more idiomatic; B-code chooses).

### Key constraints
- **psycopg2 version pin verification:** `psycopg2.errors.UniqueViolation` requires psycopg2 ≥ 2.8. **Verify `requirements.txt` pins ≥2.8 explicitly before relying on this import.** Fallback if pin uncertain: catch generic `psycopg2.Error` and check `e.pgcode == '23505'` (PostgreSQL SQLSTATE for unique violation — version-stable).
- **Status 409 (Conflict)** chosen over 400 / 503 / 429. 503 implies daemon outage (consumer back-off long); 429 implies rate-limit (consumer respects Retry-After); 409 is the precise semantic — "your request would create a duplicate." Brief Q2 architect-confirmed.
- **Observability:** emit `print(f"[register_session_pubkey] 409 race-loser worker={worker_slug}", file=sys.stderr, flush=True)` on the 409 branch. Without this, the cutover-runbook §4 "409 ratio >1% suggests storm" check is unmeasurable. Optionally also emit a `baker_actions` audit row with `action_type='session_key_race_lost'` if the daemon has audit infra wired (verify against existing `baker_actions` write paths in brisen-lab).
- **Caller behavior — see Feature 5.** V0.3.7 hook does NOT retry 4xx/5xx today (verified at baker-master `.claude/hooks/user-prompt-submit-confirm.py:216-217` returning `None`). Feature 5 adds retry-on-409 with jitter; without it, race-loser silently fails fail-open until next SessionStart fire.

---

## Feature 3: Regression test

### Problem
No test asserts the race is closed.

### Implementation

**NEW file:** `tests/test_surface6a_partial_unique_index.py` (brisen-lab repo)

Test cases:

1. **`test_concurrent_registration_only_one_winner`** — fork 2 threads calling `_register()` for same worker_slug simultaneously; assert exactly 1 active row remains; assert loser receives `psycopg2.errors.UniqueViolation` (or 409 if going through HTTP).
2. **`test_sequential_registration_succeeds`** — call `_register()` twice in sequence for same worker_slug; assert second call expires first row + creates new one (Surface 6 unchanged behavior).
3. **`test_different_workers_no_conflict`** — call `_register()` for worker_slug=A then worker_slug=B; assert both succeed, both have 1 active row.
4. **`test_409_response_on_concurrent_loser`** — full HTTP-level test; confirm 409 with `{"error": "concurrent_registration_lost_race"}` body shape.

Use existing `TEST_DATABASE_URL_BRISEN_LAB` infrastructure + `conftest.py` patterns. Tests skip if env-var absent (per existing convention).

### Key constraints
- **Real concurrency, deterministic via `threading.Barrier(2)`:** align both threads at the moment-just-before `cur.execute(UPDATE…)` so they enter the race window simultaneously. Without barrier, threads can serialize → false GREEN.
- **Loop the test 20× and assert all 20 produce exactly-one-winner.** Single-shot run is flaky on test-DB latency; loop catches non-deterministic schedule cases.
- **Real Postgres only — reject SQLite at conftest.** Partial unique indexes with `WHERE` predicates do NOT behave identically across engines. `TEST_DATABASE_URL_BRISEN_LAB` must be Postgres-shaped; conftest assertion: `assert dsn.startswith('postgres') or dsn.startswith('postgresql')`.
- **Test setup must seed `brisen_lab_worker_authority`** with the test worker_slugs (FK requirement).
- **Cleanup:** drop test rows in teardown to avoid index pollution across test runs.

---

## Feature 5: Hook retry-on-409 (NEW per architect post-WRITE)

### Problem
Without hook retry, race-loser receives 409 → V0.3.7 hook returns `None` → that prompt's ratify_decision attempts hit 403 (auth chain failed) → silent fail-open until next SessionStart. Under V0.3.7's per-prompt re-registration cadence, two prompts fired within milliseconds (legitimate user behavior — paste two messages fast) BOTH register concurrently → 50% probability one loses the race per back-to-back prompt pair. **Race is common, not edge case.** Architect Q3 flagged this as critical.

### Implementation

**File:** `.claude/hooks/user-prompt-submit-confirm.py` (baker-master repo, NOT brisen-lab)

Locate `_run_auth_chain()` function (~line 168-267 per architect verification). Find the call to `POST /auth/register-session-pubkey` (~line 216 area where `if resp.status_code != 200: return None`). Wrap with single retry on 409:

```python
import random
import time

def _register_with_retry(httpx_client, daemon_url, payload, max_retries: int = 1):
    """Register session pubkey with single retry on 409 race-loss."""
    for attempt in range(max_retries + 1):
        resp = httpx_client.post(daemon_url, json=payload, timeout=5.0)
        if resp.status_code == 200:
            return resp
        if resp.status_code == 409 and attempt < max_retries:
            # Surface 6a race-loser; retry once with jitter to break tie.
            time.sleep(random.uniform(0.05, 0.15))  # 50-150ms jitter
            continue
        return None  # other failure modes (4xx/5xx) — fail-open per V0.3.7 design
    return None
```

Replace existing direct call with `resp = _register_with_retry(client, url, payload)`.

### Key constraints
- **Max-retry = 1.** If both attempts hit 409, treat as systemic contention (concurrent registration storm); log + fail-open. Two retries doesn't materially improve odds and risks SessionStart latency.
- **Jitter required** to break ties between competing workers. Without jitter, retries collide deterministically → same race lost again.
- **`time.sleep` synchronous OK** in SessionStart hook (not async event loop context).
- **Fail-open preserved** for all non-409 non-200 paths — Surface 6a is the ONLY change to retry semantics. Prior behavior on 4xx/5xx other than 409: unchanged.

### Cross-repo coordination
Brief now spans 3 files across 2 repos:
- `migrations/<ts>_session_keys_partial_unique_index.sql` (brisen-lab, NEW)
- `bus.py` lines 641-672 (brisen-lab, EDIT)
- `.claude/hooks/user-prompt-submit-confirm.py` (baker-master, EDIT)

PR strategy: TWO PRs, one per repo. Merge order: brisen-lab FIRST (migration + handler land in production behind `BRISEN_LAB_V2_ENABLED=false`, dormant), then baker-master (hook retry composes against the now-409-emitting daemon).

---

## Feature 4: Cutover runbook update

### Problem
The pre-cutover gate ordering must be Director-readable.

### Implementation

**NEW (or amended if exists):** `_ops/processes/v2-bridge-cutover-runbook.md` (vault, not repo).

Sections:
1. **Pre-cutover gates** (in order):
   - Surface 6a partial unique index migration applied to prod brisen-lab DB
   - `applied_migrations.lock` refreshed
   - Regression test green in CI
   - Production sanity check: `SELECT worker_slug, COUNT(*) FROM brisen_lab_session_keys WHERE expired_at IS NULL GROUP BY worker_slug HAVING COUNT(*) > 1` returns 0 rows
2. **Cutover procedure:** Render env-var flip `BAKER_PROMPT_CACHE_ENABLED` not affected; specifically `BRISEN_LAB_V2_ENABLED=true` on the brisen-lab daemon service.
3. **Rollback procedure:** `BRISEN_LAB_V2_ENABLED=false` on Render → service auto-reload → V2 endpoints return 503 → consumer-side fail-open AC6 paste-block fallback resumes.
4. **Verification post-cutover:** observe baker_actions for `whatsapp_send` with `claim_received` outcome; check brisen-lab daemon logs for register-session-pubkey 200 vs 409 ratio (409 should be rare; >1% suggests concurrent registration storm).

Director-facing language; no engineering jargon.

---

## Acceptance Criteria

| AC | Description | Verification |
|---|---|---|
| **A1** | Migration `<UTC-timestamp>_session_keys_partial_unique_index.sql` applies clean to brisen-lab DB | `applied_migrations.lock` updated post-apply; sanity SELECT returns 0 duplicate-active rows |
| **A2** | Handler change: `UniqueViolation` caught + returns 409 | grep `UniqueViolation` in `bus.py`; manual curl reproduces 409 response shape |
| **A3** | All 4 regression tests GREEN | Literal pytest output |
| **A4** | Existing brisen-lab pytest suite still GREEN (no regressions) | Full `pytest` run, literal output |
| **A5** | `feature-dev:code-reviewer` standard pass clean | Standard pass; auth-surface NOT touched (existing endpoint hardened) |
| **A6** | Cutover runbook landed at `_ops/processes/v2-bridge-cutover-runbook.md` | File exists in baker-vault; Director-readable |
| **A7** | `BRISEN_LAB_V2_ENABLED=false` UNCHANGED on Render brisen-lab service | Render env state confirmed; cutover gated on Director ratification AFTER this brief ships |
| **A8** | Post-apply prod sanity check — automated one-liner | `psql $PROD_URL -c "SELECT worker_slug, COUNT(*) FROM brisen_lab_session_keys WHERE expired_at IS NULL GROUP BY worker_slug HAVING COUNT(*) > 1"` returns empty result. Output pasted verbatim into ship report — no transcription. |
| **A9** | `pg_index.indisvalid = TRUE` for `uq_session_keys_worker_active` post-apply | `psql $PROD_URL -c "SELECT indisvalid FROM pg_index WHERE indexrelid = 'uq_session_keys_worker_active'::regclass"` returns `t`. INVALID index = ship-blocker (CONCURRENTLY left it broken; cleanup + retry). |
| **A10** | Feature 5 hook retry-on-409 lands in baker-master `.claude/hooks/user-prompt-submit-confirm.py` | grep `_register_with_retry` returns the helper; manual race-test reproduces single retry path |
| **A11** | Migration rollback path documented | Cutover runbook §Rollback includes: `DROP INDEX uq_session_keys_worker_active; CREATE INDEX idx_session_keys_worker_active ON brisen_lab_session_keys (worker_slug) WHERE expired_at IS NULL;` (recreates non-unique partial index). |
| **A12** | 409 observability emits to stderr | `print(f"[register_session_pubkey] 409 race-loser worker={worker_slug}", ..., flush=True)` on the 409 branch; verifiable via Render log tail post-cutover. |

**Ship gate:** literal pytest GREEN + A1-A8 all met. Migration applies clean to prod = ship-blocker; if duplicate rows exist pre-apply, B-code clean first then re-apply.

---

## Open questions for AH1 (none expected)

None. Single migration + small handler change. If the migration runner doesn't auto-detect CONCURRENTLY (couldn't run inside transaction block), B-code surfaces that as a blocker.

---

## Sequencing

1. B-code claims brief (likely B4 — same V2_BRIDGE lane, fresh context).
2. Read brief cover-to-cover.
3. **Pre-work — verify migration runner handles CONCURRENTLY** (per Feature 1 critical pre-work): inspect brisen-lab `start.sh` / migration runner script. If runner wraps `.sql` files in BEGIN/COMMIT, surface to AH1 as design-blocker BEFORE writing migration.
4. **Pre-apply prod sanity check:** run the duplicate-detect SELECT against prod brisen-lab DB. If duplicates exist, surface to AH1; clean first.
5. Author migration file (CONCURRENTLY-aware).
6. Apply locally against `TEST_DATABASE_URL_BRISEN_LAB`; verify clean apply + `pg_index.indisvalid = TRUE`.
7. Implement Feature 2 handler change (brisen-lab `bus.py`) + Feature 3 regression tests + Feature 5 hook retry (baker-master `.claude/hooks/user-prompt-submit-confirm.py`).
8. Live pytest GREEN both repos.
9. Open TWO PRs: brisen-lab + baker-master.
10. AH1 reviews + merges. **Merge order: brisen-lab FIRST** (migration + handler land dormant behind `BRISEN_LAB_V2_ENABLED=false`), THEN baker-master (hook retry composes against now-409-emitting daemon).
11. Apply migration to prod brisen-lab DB; refresh `applied_migrations.lock`.
12. Post-apply prod sanity checks (A8 + A9 — automated one-liners pasted into ship report).
13. Cutover runbook landed in vault (Feature 4).
14. **AH1-Terminal performs Tier-B `BRISEN_LAB_V2_ENABLED=true` env-var flip on Render brisen-lab service AFTER Director explicit ratification.** This brief does NOT auto-flip the cutover env-var — that requires a separate Director "go" per Tier-B charter.

---

## Reference

- Surface 6 implementation: `bus.py:641-672` `_register()` (brisen-lab `bc1e3e6`)
- Existing partial index: `db.py:198-200` `idx_session_keys_worker_active` (non-unique, will be replaced)
- Schema: `db.py:190-200` `brisen_lab_session_keys` table DDL
- Gate-4 LOW L1 finding source: `feature-dev:code-reviewer` agent on PR #157 (a07ab8c0a75168417)
- V2_BRIDGE_1 brief: `briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_1.md` (V0.3.7 ship 2026-05-05)
- Cascade actions_log: `~/baker-vault/_ops/agents/ai-head/actions_log.md` "V2_BRIDGE_1 cross-repo merge cascade (steps 1-2 of 4)" 2026-05-05
- Migration immutability lesson: `tasks/lessons.md` Lesson #50

---

# V0.2 Amendment — Bootstrap-pattern pivot (Director-ratified 2026-05-05)

> **Trigger:** B4 design-blocker escalation 2026-05-05 (Tier-B #7). Brief V0.1 assumed brisen-lab has a migration runner (`migrations/` dir + `applied_migrations.lock` + CONCURRENTLY-aware applier). **It does not.** Schema bootstraps via `db.bootstrap()` calling `SCHEMA_V2_SQL` as one big string from `app.py:80` (`@app.on_event("startup")`) inside an implicit psycopg2 transaction. Existing `idx_session_keys_worker_active` itself was created via the bootstrap path (`db.py:198-200`), not via a migration file.
>
> **Director ratification:** Option A (adapt to bootstrap pattern, drop CONCURRENTLY) selected over (B) build mini-migration runner — gold-plating; (C) apply DDL out-of-band via psql — loses audit trail.
>
> Brief V0.1 Decision §2 already foresaw this fallback: *"Production `brisen_lab_session_keys` is small (rows: a few hundred max) so plain `CREATE` would also work."* This amendment formalizes that fallback.

## Amendment §A — Feature 1 implementation (REPLACES V0.1 §Implementation)

**File touched:** `db.py` (brisen-lab repo, branch `b4/brisen-lab-surface-6a-partial-unique-index-1`).

**Action:** add the partial unique index + drop-old-index pair inline in `SCHEMA_V2_SQL` (the same string that already houses the existing non-unique partial index at `db.py:198-200`). Bootstrap reapplies on next deploy via `db.bootstrap()` startup hook.

```sql
-- Inside SCHEMA_V2_SQL (db.py), replacing the prior non-unique partial index block:
CREATE UNIQUE INDEX IF NOT EXISTS uq_session_keys_worker_active
    ON brisen_lab_session_keys (worker_slug)
    WHERE expired_at IS NULL;

DROP INDEX IF EXISTS idx_session_keys_worker_active;
```

**Why no CONCURRENTLY:** CONCURRENTLY cannot run inside a transaction block, and `db.bootstrap()` executes the whole SCHEMA_V2_SQL inside an implicit psycopg2 transaction. Plain `CREATE` is acceptable per Decision §2 (small table, hundreds of rows max — lock impact is microseconds).

**Why `IF NOT EXISTS` + `IF EXISTS`:** idempotent re-bootstrap on every container start. Matches the rest of SCHEMA_V2_SQL's pattern.

## Amendment §B — Critical pre-work (REPLACES V0.1 Feature 1 §"CRITICAL pre-work")

V0.1 mandated B-code inspect `start.sh` / migration runner for CONCURRENTLY-incompatibility. **Pre-work outcome already known:** brisen-lab has no runner; bootstrap-pattern. No file inspection needed; no design escalation pathway needed (this amendment IS the resolution).

## Amendment §C — Acceptance Criteria deltas

**Dropped (migration-runner-specific):**
- ~~A1: Migration file applies clean; `applied_migrations.lock` updated~~
- ~~A8: Migration filename ≥1s timestamp separation; lock-file refresh~~
- ~~A9: `pg_index.indisvalid = TRUE` post-CONCURRENTLY~~
- ~~A11: Migration rollback documented (SQL-level)~~ (replaced — see new A11' below)

**Replacement A1' — Bootstrap-pattern verification (ships in place of A1):**
| **A1'** | `SCHEMA_V2_SQL` in `db.py` contains `CREATE UNIQUE INDEX IF NOT EXISTS uq_session_keys_worker_active ... WHERE expired_at IS NULL` AND `DROP INDEX IF EXISTS idx_session_keys_worker_active` | grep both lines in `db.py`; bootstrap reapplies on container restart |

**Replacement A8' — Post-deploy schema verification (ships in place of A8 + A9):**
| **A8'** | Post-deploy: `psql $DATABASE_URL -c "\d brisen_lab_session_keys"` shows `uq_session_keys_worker_active` listed as `UNIQUE` partial index (`WHERE expired_at IS NULL`); `idx_session_keys_worker_active` no longer present | Manual verification step in cutover runbook §"Pre-cutover checklist" (Feature 4) |

**Replacement A9' — Duplicate-detect query returns 0 rows (ships in place of A9):**
| **A9'** | Post-deploy: `SELECT worker_slug, COUNT(*) FROM brisen_lab_session_keys WHERE expired_at IS NULL GROUP BY worker_slug HAVING COUNT(*) > 1;` returns 0 rows | Verifies no duplicate-active state survived the rebootstrap |

**Replacement A11' — Bootstrap-pattern rollback documentation (ships in place of A11):**
| **A11'** | Cutover runbook §Rollback documents: revert the `db.py` change in a follow-up commit (re-add old `idx_session_keys_worker_active` non-unique, drop `uq_session_keys_worker_active`); deploy → bootstrap reapplies revert | Code-level rollback, not SQL-level — matches the bootstrap-pattern primitive |

**Unchanged ACs:** A2, A3, A4, A5, A6, A7, A10, A12 (handler 409, regression tests, hook retry-on-409, observability — all application-side, independent of migration mechanics).

## Amendment §D — Architect post-WRITE folds (status under V0.2)

| Architect fold | V0.2 status |
|---|---|
| Feature 5 hook retry-on-409 with jitter (max-retry=1) | **STAYS** — application-side, unchanged |
| Migration: DROP CONCURRENTLY symmetry + `pg_index.indisvalid` post-CONCURRENTLY check + runner CONCURRENTLY-handling verification | **MOOT** — no migration runner; CONCURRENTLY dropped; `indisvalid` check N/A under bootstrap-pattern |
| psycopg2 ≥2.8 pin OR SQLSTATE '23505' fallback | **STAYS** — application-side, Feature 2 handler 409 path |
| Test determinism: `threading.Barrier(2)` + 20× loop + reject SQLite at conftest | **STAYS** — Feature 3 regression test |
| Observability: stderr log on 409 branch | **STAYS** — Feature 2 + AC A12 |
| Migration rollback path documented in cutover runbook | **REWRITTEN** — see A11' (code-level revert, not SQL-level) |

## Amendment §E — Sequencing (UPDATES V0.1 §Sequencing)

**Replaces V0.1 step 3 (pre-work runner inspection) + step 5 (author migration file):**

3. ~~Pre-work — verify migration runner~~ — DROPPED. Bootstrap-pattern confirmed.
5. ~~Author migration file~~ — REPLACED with: edit `db.py` `SCHEMA_V2_SQL` to add `CREATE UNIQUE INDEX IF NOT EXISTS uq_session_keys_worker_active ... WHERE expired_at IS NULL` + `DROP INDEX IF EXISTS idx_session_keys_worker_active`.

**Replaces V0.1 step 12 (post-apply A8 + A9 sanity checks):**

12. Post-deploy A8' (`\d` schema verification) + A9' (duplicate-detect SELECT) — automated one-liners pasted into ship report.

**Steps 1-2, 4, 6-11, 13-14 unchanged.** Director Tier-B ratification on `BRISEN_LAB_V2_ENABLED=true` flip (step 14) unchanged.

## Amendment §F — Net effect summary

- **Files touched (brisen-lab):** `db.py` only (1 SQL block edit). No `migrations/` dir created. No `applied_migrations.lock` touched.
- **Files touched (baker-master):** Feature 5 hook retry-on-409 unchanged from V0.1.
- **Risk delta:** lower than V0.1 — no migration-runner infra to verify; no CONCURRENTLY race to monitor; replaced with surgical SQL primitive matching V0.3.7's existing pattern.
- **Brief intent (DB-level race close on session_keys) preserved.**

**End V0.2 amendment.**
