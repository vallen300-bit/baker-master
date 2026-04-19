# B2 KBL migrations sanity-check — REDIRECT

**Reviewer:** Code Brisen #2
**Date:** 2026-04-19 (evening)
**Task:** `briefs/_tasks/CODE_2_PENDING.md` @ `1af5546`
**Prod DB:** `neondb` on `ep-summer-sun-aih7ha4h-pooler.c-4.us-east-1.aws.neon.tech` (PostgreSQL 17.8)
**DATABASE_URL source:** `ssh macmini '~/.kbl.env'` (psycopg2 direct connect; no local psql)
**B1 report status:** not yet filed at audit time (B1 task still in progress per `briefs/_reports/B1_kbl_migrations_apply_20260419.md` absent); migrations appear to have been applied to prod (signal_queue now 35 cols + all expected migration-provisioned tables present).
**Verdict:** **REDIRECT** — two critical tables (`kbl_cost_ledger`, `kbl_log`) that are required for Steps 1–5 + /cost-rollup dashboard endpoint are still **ABSENT** in production. First signal through Step 1 will crash on `INSERT INTO kbl_cost_ledger`.

---

## Bottom line

B1's migration apply completed what the migration files contained:
signal_queue is now 35 columns, `kbl_cross_link_queue` + `kbl_circuit_breaker`
+ `feedback_ledger` + `kbl_layer0_hash_seen` + `kbl_layer0_review` +
`mac_mini_heartbeat` + `kbl_alert_dedupe` + `kbl_runtime_state` all
landed, CHECK constraint is the full 34-value set.

But two writer-referenced tables were never in the migration files
AND are currently absent from prod:

1. **`kbl_cost_ledger`** — referenced by **Step 1, Step 2, Step 3, Step 5,
   `kbl/cost.py`**, and the dashboard `/api/kbl/cost-rollup` endpoint.
   Absent → first INSERT crashes with `relation "kbl_cost_ledger" does
   not exist`. Step 1 is the first writer that hits it; every signal
   dies at triage.
2. **`kbl_log`** — referenced by `kbl/logging.py.emit_log()`. Absent →
   `emit_log` swallows the error (PG insert is wrapped in try/except +
   stderr-only fallback per `kbl/logging.py:108-109`), so pipeline
   doesn't crash, but ALL structured WARN/ERROR/CRITICAL logs stop
   persisting. This is CHANDA §2 Leg 2 capture plumbing going dark.

Provisioning origin:

| Table | Expected provisioning path | Present? |
|-------|--------------------------- |----------|
| `kbl_cost_ledger` | `memory/store_back.py:6505 _ensure_kbl_cost_ledger()` (app-boot) | **ABSENT** |
| `kbl_log` | `memory/store_back.py:6552 _ensure_kbl_log()` (app-boot) | **ABSENT** |

Neither has a corresponding `migrations/*.sql` file. Both are
provisioned at Baker app-boot via `SentinelStoreBack.__init__()` →
lines 193-194, which run on first `_get_global_instance()` call.
Either (a) the Baker Render service hasn't been restarted since those
`_ensure` methods were added to `store_back.py`, (b) init failed
earlier in the chain and never reached them, or (c) the pipeline-only
code path (`kbl/db.py get_conn()`) bypasses MemoryStore init entirely
→ explains why shadow-mode flip didn't catch it.

Either way: until these two tables exist, Step 1 will crash on the
first real signal. **Shadow mode cannot flip to true until this is
fixed.**

---

## REDIRECT item S1 — `kbl_cost_ledger` MISSING (blocker)

### Code paths that write to `kbl_cost_ledger` (all plain INSERTs, no fault-tolerance wrapper)

| File | Line | Columns referenced |
|------|------|--------------------|
| `kbl/cost.py` | 160 | signal_id, step, model, input_tokens, output_tokens, latency_ms, cost_usd, success, metadata |
| `kbl/steps/step1_triage.py` | 491 | signal_id, step='triage', model, input_tokens, output_tokens, latency_ms, cost_usd=0, success |
| `kbl/steps/step2_resolve.py` | 126 | signal_id, step='resolve', model, input_tokens, NULL, latency_ms, cost_usd, success |
| `kbl/steps/step3_extract.py` | 496 | signal_id, step='extract', model, input_tokens, output_tokens, latency_ms, cost_usd=0, success |
| `kbl/steps/step5_opus.py` | 347 | signal_id, step='opus_step5', model, input_tokens, output_tokens, latency_ms, cost_usd, success, metadata |

### Code paths that read `kbl_cost_ledger`

| File | Line | Purpose |
|------|------|---------|
| `kbl/cost_gate.py` | 144 | `SELECT COALESCE(SUM(cost_usd), 0) FROM kbl_cost_ledger WHERE ts::date = (NOW() AT TIME ZONE 'UTC')::date` — daily cap check |
| `outputs/dashboard.py` | (cost-rollup endpoint) | 24h window SUM for dashboard |

### Schema (from `memory/store_back.py:6514-6540`, not yet applied)

```sql
CREATE TABLE IF NOT EXISTS kbl_cost_ledger (
    id             BIGSERIAL PRIMARY KEY,
    ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signal_id      INTEGER REFERENCES signal_queue(id) ON DELETE SET NULL,
    step           TEXT NOT NULL,
    model          TEXT,
    input_tokens   INT,
    output_tokens  INT,
    latency_ms     INT,
    cost_usd       NUMERIC(10,6) NOT NULL DEFAULT 0,
    success        BOOLEAN NOT NULL DEFAULT TRUE,
    metadata       JSONB
);
CREATE INDEX IF NOT EXISTS idx_cost_ledger_day ON kbl_cost_ledger ((ts::date));
CREATE INDEX IF NOT EXISTS idx_cost_ledger_signal ON kbl_cost_ledger (signal_id, ts) WHERE signal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cost_ledger_step_day ON kbl_cost_ledger (step, (ts::date));
```

### Concrete fix options

**Option A (recommended, fastest):** Ship a new migration file
`migrations/20260419_kbl_cost_ledger.sql` + `migrations/20260419_kbl_log.sql`
that literally copies the CREATE TABLE + CREATE INDEX blocks from
`memory/store_back.py:6514-6580`. Apply via the same B1 pattern
(psql + `ON_ERROR_STOP=1`). ~5 min.

**Option B:** Issue ad-hoc CREATE TABLE via psql on prod, skip the
migration file (matches what B1 did for the 3 PR #16 ALTERs).
Equivalent outcome; leaves the migrations/ directory short the
source-of-truth files. Inferior for future audits.

**Option C:** Bounce Baker service on Render → `MemoryStore.__init__()`
fires → `_ensure_kbl_cost_ledger` + `_ensure_kbl_log` create the tables
in-app. Fragile: relies on the FastAPI server importing + instantiating
MemoryStore at boot, which the pipeline_tick path may not do. If earlier
`_ensure` in the chain fails, we never reach cost_ledger/log.

**Recommendation: Option A.** Makes migrations/ directory authoritative
for the full schema; unblocks AI Head's B3 `MIGRATION_RUNNER_1` brief
(the startup-hook migration runner needs a declarative migration list,
not hidden app-boot methods).

---

## REDIRECT item S2 — `kbl_log` MISSING (non-crash but silent logging gap)

### Code path

`kbl/logging.py:87-109` wraps the `INSERT INTO kbl_log` in its own
try/except with a stderr fallback:

```python
try:
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO kbl_log (level, component, signal_id, message, metadata) ..."
                )
            conn.commit()
        except Exception:
            conn.rollback(); raise
except Exception as e:
    sys.stderr.write(f"[kbl.logging] PG kbl_log insert failed: {e}\n")
```

**Impact:** Pipeline doesn't crash on kbl_log absence, but:

- Every Step 1-7 WARN/ERROR/CRITICAL bypasses PG persistence — only
  stdlib stderr.
- Dashboard `/api/kbl/log` endpoint (if any) returns empty.
- CHANDA §2 Leg 2 capture plumbing is dark — no Director-visible
  evidence of pipeline errors.
- `kbl/steps/step7_commit.py:_mark_commit_failed` emits `emit_log("WARN",
  "commit", signal_id, f"commit_failed: {reason}")` (line 292) — this
  would be silently dropped.

**Severity:** Lower than S1 — no crash, just observability hole.
But it's still a CHANDA Leg 2 capture gap. Task §4 explicitly flags
either-missing as a "CHANDA §2 Leg 2 blocker, do NOT approve".

### Concrete fix

Pair with S1 fix in `migrations/20260419_kbl_log.sql` per shape at
`memory/store_back.py:6562-6580`:

```sql
CREATE TABLE IF NOT EXISTS kbl_log (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level      TEXT NOT NULL CHECK (level IN ('WARN','ERROR','CRITICAL')),
    component  TEXT NOT NULL,
    signal_id  INTEGER REFERENCES signal_queue(id) ON DELETE SET NULL,
    message    TEXT NOT NULL,
    metadata   JSONB
);
CREATE INDEX IF NOT EXISTS idx_kbl_log_day_level ON kbl_log ((ts::date), level);
CREATE INDEX IF NOT EXISTS idx_kbl_log_component ON kbl_log (component, ts);
```

---

## Dispatch naming-drift clarification (non-blocking)

Task text line 27 says:

> kbl_log and kbl_feedback_ledger presence. Confirm these tables exist post-migration (they should be in 20260418_loop_infrastructure.sql).

**Two factual corrections:**

1. **`kbl_feedback_ledger` does not exist anywhere in the code or
   migrations.** The actual table name is `feedback_ledger` (no `kbl_`
   prefix), created by `migrations/20260418_loop_infrastructure.sql:50`.
   It IS **PRESENT** in prod, all 8 columns correct. Task text appears
   to be a naming typo.
2. **`kbl_log` is NOT in `20260418_loop_infrastructure.sql`.** That
   migration creates `feedback_ledger` + `kbl_layer0_hash_seen` +
   `kbl_layer0_review`, nothing else. `kbl_log` is provisioned by
   `memory/store_back.py` app-boot path — absent in prod per S2 above.

Not a finding on B1's apply — a dispatch-text error. Worth correcting
in next-task text.

---

## Per-step signal_queue column coverage ✓ (all clean)

Walked every `UPDATE signal_queue SET <col>` across `kbl/layer0.py`
(no writes), `kbl/steps/step1_triage.py`, `step2_resolve.py`,
`step3_extract.py`, `step4_classify.py`, `step5_opus.py`,
`step6_finalize.py`, `step7_commit.py`. Every column referenced is
present in the applied schema:

| Step | Columns written | Verdict |
|------|----------------|---------|
| Layer 0 | (no signal_queue writes — only kbl_layer0_hash_seen + kbl_layer0_review) | ✓ |
| Step 1 | status, primary_matter, related_matters, vedana, triage_score, triage_confidence, triage_summary | ✓ all 35-col schema |
| Step 2 | status, resolved_thread_paths | ✓ |
| Step 3 | status, extracted_entities | ✓ |
| Step 4 | status, step_5_decision, cross_link_hint | ✓ |
| Step 5 | status, opus_draft_markdown | ✓ |
| Step 6 | status, final_markdown, target_vault_path, finalize_retry_count (defensive ALTER IF NOT EXISTS inline at line 425) | ✓ — finalize_retry_count NOT in migration but created on first hit, intentional per code comment |
| Step 7 | status, committed_at, commit_sha, opus_draft_markdown=NULL, final_markdown=NULL (defensive ALTER IF NOT EXISTS at lines 252, 256 — redundant now that B1 pre-applied the 3 PR #16 ALTERs) | ✓ |

All `signal_queue` writer columns exist in applied schema.

---

## Per-table shape audits

### `signal_queue` (35 cols, matches B1 task §6 expected count)

35 columns present. Key KBL-B columns verified:

- `primary_matter TEXT`, `related_matters JSONB` (drifted from TEXT[] in
  migration file — see N3 below), `vedana TEXT`, `triage_score INTEGER`
  (pre-existing from KBL-A), `triage_confidence NUMERIC` with range
  CHECK (0..1), `triage_summary TEXT` — all per Step 1 migration. ✓
- `resolved_thread_paths JSONB NOT NULL DEFAULT '[]'::jsonb` — per Step 2 migration. ✓
- `extracted_entities JSONB NOT NULL DEFAULT '{}'::jsonb` — per Step 3 migration. ✓
- `step_5_decision TEXT`, `cross_link_hint BOOLEAN NOT NULL DEFAULT FALSE` — per Step 4 migration. ✓
- `opus_draft_markdown TEXT` — per Step 5 migration. ✓
- `final_markdown TEXT`, `target_vault_path TEXT` — per Step 6 migration. ✓
- `commit_sha TEXT`, `committed_at TIMESTAMPTZ` — per B1's 3 ad-hoc PR #16 ALTERs. ✓
- `id` is now `bigint` with `nextval('signal_queue_id_seq'::regclass)` — loop-infrastructure migration's BIGINT upgrade applied. ✓

### CHECK constraint ✓ (34 values, exact match)

```
signal_queue_status_check:
  CHECK ((status = ANY (ARRAY[
    'pending','processing','done','failed','expired',
    'classified-deferred','failed-reviewed','cost-deferred',
    'dropped_layer0',
    'awaiting_triage','triage_running','triage_failed','triage_invalid','routed_inbox',
    'awaiting_resolve','resolve_running','resolve_failed',
    'awaiting_extract','extract_running','extract_failed',
    'awaiting_classify','classify_running','classify_failed',
    'awaiting_opus','opus_running','opus_failed','paused_cost_cap',
    'awaiting_finalize','finalize_running','finalize_failed',
    'awaiting_commit','commit_running','commit_failed',
    'completed'])))
```

Count: 34 values. Matches brief exactly. ✓

### `kbl_cross_link_queue` ✓

7 columns matching migration (source_signal_id BIGINT NOT NULL,
target_slug TEXT NOT NULL, stub_row TEXT NOT NULL, vedana TEXT,
source_path TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT
NOW(), realized_at TIMESTAMPTZ).

FK: `kbl_cross_link_queue_source_signal_id_fkey: FOREIGN KEY (source_signal_id)
REFERENCES signal_queue(id) ON DELETE CASCADE` ✓ (matches migration,
preserves signal_queue authority).

Step 6 UPSERT at `kbl/steps/step6_finalize.py:458-469` references:
source_signal_id, target_slug, stub_row, vedana, source_path,
created_at (updated in ON CONFLICT DO UPDATE SET), realized_at — all
present. ✓

Step 7 mark-realized at `step7_commit.py:270-276`: `UPDATE
kbl_cross_link_queue SET realized_at = NOW() WHERE source_signal_id =
%s AND target_slug = ANY(%s)` — all columns present. ✓

Indexes:
- PK `(source_signal_id, target_slug)` ✓
- `idx_kbl_cross_link_queue_unrealized` = partial on `(created_at) WHERE realized_at IS NULL` ✓ (matches spec)
- `idx_kbl_cross_link_queue_target_slug` = `(target_slug, created_at DESC)` ✓ (matches spec)

### `feedback_ledger` ✓ (task meant "kbl_feedback_ledger" — naming typo)

8 columns matching migration. ✓

### `kbl_circuit_breaker` ✓ + seeded

6 columns matching migration. One seed row present:
`('opus_step5', 0, None, 'kbl_b_step5_bootstrap')` — correct per
migration INSERT ON CONFLICT DO NOTHING. ✓

### `mac_mini_heartbeat` ✓

4 columns (id BIGSERIAL PK, created_at TIMESTAMPTZ, host TEXT, version
TEXT). Index `idx_mac_mini_heartbeat_created_at (created_at DESC)`
present. ✓

### `kbl_alert_dedupe` ✓ (present, pre-existing from KBL-A)

Schema verified; no writes in this audit.

### `kbl_runtime_state` ✓ (present, pre-existing from KBL-A)

Used by `kbl/pipeline_tick.py:main()` for `get_state("anthropic_circuit_open")`
and `get_state("cost_circuit_open")` circuit checks. Table present;
actual row-level semantics not audited here (outside scope).

---

## N-level observations (non-blocking, record for polish)

### N1. Missing index: `signal_queue.committed_at`

Dashboard `/api/kbl/silver-landed` endpoint sorts by `committed_at DESC
LIMIT 50` (per my PR #17 review). Currently no dedicated index;
PostgreSQL will use a sequential scan. With `signal_queue` at 0 rows
this is fine, but worth adding now while it's free:

```sql
CREATE INDEX IF NOT EXISTS idx_signal_queue_committed_at
    ON signal_queue (committed_at DESC)
    WHERE committed_at IS NOT NULL;
```

Polish PR, post-shadow-mode-flip.

### N2. `kbl_cost_ledger.created_at` naming drift vs `ts`

Task text §6 says "`kbl_cost_ledger.created_at`" but the schema
(store_back.py:6516) uses `ts` not `created_at`. The existing index
`idx_cost_ledger_day` is on `((ts::date))` — which is the right
expression for the daily-window query in `cost_gate.py:_today_spent`
and dashboard `/cost-rollup`. No fix needed; task text is imprecise.

### N3. `related_matters` column type drift

Migration file `20260418_step1_signal_queue_columns.sql:37` says:

```sql
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS related_matters TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
```

Actual schema: `related_matters JSONB NOT NULL DEFAULT '[]'::jsonb`.

Explanation: KBL-A provisioned the column as JSONB first (see
`memory/store_back.py._ensure_signal_queue_additions`), so the Step 1
migration's `IF NOT EXISTS` made it a no-op. Writer code
(`step1_triage.py:469`) passes `list(result.related_matters)` which
psycopg2 adapts to either JSONB or TEXT[] seamlessly — functional
behavior is identical either way.

Migration comment at lines 21-24 explicitly acknowledges this drift:

> related_matters TEXT[] (dispatch) — KBL_A_SCHEMA.sql v3 uses JSONB;
> we take the dispatch word here and let a future reconciliation PR
> align the two when KBL-A lands. The writer already handles both
> shapes via psycopg2's native adaptation.

Not a bug, just documented drift. Phase 2 cleanup candidate.

### N4. `finalize_retry_count` defensive ADD COLUMN inline (Step 6)

`kbl/steps/step6_finalize.py:425-427`:

```sql
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS finalize_retry_count INT NOT NULL DEFAULT 0
```

Column NOT in any migration — intentional per module docstring (R3
coordination with Step 5). Will be created on first Step 6 R3
retry hit. Safe (idempotent IF NOT EXISTS), but worth noting that
the migrations/ directory does not describe the full schema — Step 6
+ Step 7 `commit_sha`/`committed_at` historically followed this
defensive pattern. The pre-applied PR #16 ALTERs closed the Step 7
gap; the Step 6 gap remains but is low-risk.

### N5. `commit_sha` + `committed_at` now redundantly guarded

`kbl/steps/step7_commit.py:252-258` still runs `ALTER TABLE ... ADD
COLUMN IF NOT EXISTS committed_at TIMESTAMPTZ` + same for `commit_sha`
on every `_mark_completed` call. Now that B1 pre-applied those ALTERs,
these are always no-ops, but they still execute. Moving them to a
one-time startup hook (the B3 `MIGRATION_RUNNER_1` brief just landed
— `cd0cdfe`) would eliminate per-signal overhead. Polish, not
blocker.

---

## Cross-check against B1's self-report

**Status:** B1's report file `briefs/_reports/B1_kbl_migrations_apply_20260419.md`
**not yet filed** at audit timestamp. B1 is still in the dispatch
window — migrations are evidently applied to prod (schema state
matches expected post-apply per my independent queries above), but
the report-writeup step isn't done.

Once B1 files, the cross-check I'd run:

- B1 reports signal_queue cols = 35 → matches my 35. ✓
- B1 reports CHECK constraint values = 34 → matches my 34. ✓
- B1 lists tables present → compare against my list above.
- **B1 will NOT have flagged the `kbl_cost_ledger` + `kbl_log` absence**
  because the task scoped B1 to applying 9 files + 3 ALTERs, none of
  which created those two tables. That gap is a dispatch-design miss,
  not a B1 execution miss.

---

## Queries run (reproducibility)

All queries executed against prod Neon via `psycopg2` direct connect,
DATABASE_URL fetched from Mac Mini `~/.kbl.env`. Audit script at
`/tmp/schema_audit.py`; raw output at `/tmp/schema_audit.txt`.
Summary of queries:

1. `SELECT table_name FROM information_schema.tables WHERE table_schema='public'` — full table inventory.
2. `SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_name=X ORDER BY ordinal_position` — per-table shape for signal_queue, kbl_cost_ledger, kbl_cross_link_queue, feedback_ledger, kbl_log, kbl_circuit_breaker.
3. `SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='signal_queue'::regclass AND contype='c'` — CHECK constraint.
4. `SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' AND tablename IN (...)` — index inventory.
5. `SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='kbl_cross_link_queue'::regclass AND contype='f'` — FK verification.
6. `SELECT * FROM kbl_circuit_breaker` — seed-row verification.

---

## Dispatch

**REDIRECT.** Blocker for shadow-mode-true flip:

1. **S1 (must-fix):** Create `kbl_cost_ledger` on prod via migration
   file `migrations/20260419_kbl_cost_ledger.sql` (copy shape from
   `memory/store_back.py:6514-6540`) + apply. **First signal crashes
   Step 1 without this.**

2. **S2 (must-fix per CHANDA §2 Leg 2):** Create `kbl_log` on prod via
   migration file `migrations/20260419_kbl_log.sql` (copy shape from
   `memory/store_back.py:6562-6580`) + apply. Pipeline won't crash
   (emit_log is fault-tolerant), but structured log persistence is
   dark.

**Recommendation:** Bundle S1 + S2 into a single PR from B1 →
two-migration apply + verification output → B2 re-review (~5 min
each). Feeds cleanly into B3's `MIGRATION_RUNNER_1_BRIEF.md` startup
hook design (the runner needs every schema artifact in `migrations/`,
not hidden in `store_back.py`).

**On REDIRECT:** AI Head takes this to Director to authorize the
S1+S2 create+apply. Once applied, re-run this audit — should flip to
APPROVE with the two new tables present. Shadow mode remains safe to
flip AFTER S1+S2 complete.

Also flag dispatch-text corrections to AI Head:
- "kbl_feedback_ledger" in task text is a typo; actual table name is
  `feedback_ledger` (no prefix) and is correctly provisioned.
- "kbl_log should be in 20260418_loop_infrastructure.sql" is incorrect;
  that migration provisions feedback_ledger + kbl_layer0_hash_seen +
  kbl_layer0_review only.

Tab closing after push per directive.
