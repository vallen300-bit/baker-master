---
role: B2
kind: diagnostic
brief: bridge_hot_md_match_drift
pr: n/a
head_sha: 99e3b91
verdict: DIAGNOSTIC_COMPLETE
date: 2026-04-21
tags: [bridge, hot_md, schema-drift, migration-runner, cortex-t3]
---

# B2 — `signal_queue.hot_md_match` schema drift (live BOOLEAN vs intended TEXT)

**Scope reminder:** read-only. No schema or code changes shipped. Stop-gap recommendations only.

---

## Root cause

**The live column is `BOOLEAN` because the app-boot bootstrap (`_ensure_signal_queue_base` in `memory/store_back.py:6213`) created it as `BOOLEAN` long before BRIDGE_HOT_MD_AND_TUNING_1 existed. The new migration's `ADD COLUMN IF NOT EXISTS hot_md_match TEXT` is a silent no-op — the `IF NOT EXISTS` guard sees the column already present and declines to touch its type. Bridge code then binds a text value (e.g. `"Lilienmatt"`) into a BOOLEAN column and every tick aborts.**

Intent-vs-implementation split:
- **Migration + bridge code + tests + B3 review** all agree on `TEXT` (verbatim matched pattern line).
- **Live DB + bootstrap DDL** is `BOOLEAN` (semantic from a pre-hot.md era: "did something match").

The BOOLEAN semantic is stale dead-code — grep shows zero current readers treat it as boolean.

---

## Evidence

### 1. Live column type (confirmed)

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name='signal_queue' AND column_name='hot_md_match';
-- → data_type: boolean, is_nullable: YES
```

### 2. Migration declaration (as shipped in PR #29)

`migrations/20260421_signal_queue_hot_md_match.sql:9`:

```sql
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS hot_md_match TEXT;
```

Intended as additive-nullable-TEXT. B3 PR #29 review (`B3_pr29_bridge_hot_md_review_20260421.md:129`) confirmed this reading verbatim: *"ADD COLUMN IF NOT EXISTS hot_md_match TEXT — additive, nullable, no default, no constraints."* No review-vs-reality drift at the **migration file** level — the drift is between migration and the **pre-existing bootstrap DDL**.

### 3. The pre-existing bootstrap — the actual source of the BOOLEAN

`memory/store_back.py:6190-6238` — `_ensure_signal_queue_base()`:

```python
cur.execute("""
    CREATE TABLE IF NOT EXISTS signal_queue (
        id                SERIAL PRIMARY KEY,
        ...
        hot_md_match      BOOLEAN,        # <-- line 6213
        ...
    )
""")
```

This runs on every app boot. In any deployment where the signal_queue table was created before PR #29 merged, `hot_md_match` was already a BOOLEAN column — almost certainly vestige from KBL-19's original spec where the axis was "did any hot pattern match" (binary), not "which line matched" (text).

Because `ADD COLUMN IF NOT EXISTS` is a presence check, not a type check, PostgreSQL saw the column present and did nothing. The migration logged as applied without altering anything.

### 4. Code intent — bridge binds TEXT

`kbl/bridge/alerts_to_signal.py`:

```python
# line 215
def hot_md_match(alert: dict, patterns: list[str]) -> Optional[str]:
    """Return the first hot.md pattern that matches alert title+body, else None."""
    ...
    for pattern in patterns:
        if pattern.lower() in haystack:
            return pattern          # str, not bool

# line 416  — mapper carries the string through
return {
    ...
    "hot_md_match": alert.get("hot_md_match"),   # Optional[str]
}

# line 523  — INSERT binds the string
signal_row.get("hot_md_match"),                  # bound as 10th param
```

Every writing code path treats the value as `Optional[str]`. Nowhere does the producer ever pass a boolean.

### 5. Downstream readers — zero

Grep across `kbl/steps/**` and the whole repo for `hot_md_match`:

```
kbl/steps/               → 0 matches
kbl/bridge/alerts_to_signal.py → producer only
memory/store_back.py      → bootstrap DDL (BOOLEAN)
tests/test_bridge_hot_md.py → asserts str round-trip
tests/test_bridge_alerts_to_signal.py → asserts column present
```

No step reads it. No `WHERE hot_md_match = true` anywhere. No `WHERE hot_md_match = '...'` either. The column is **write-only today** — designed for later analytics surfaces ("which hot.md entries are actually firing") per the BRIDGE_HOT_MD_AND_TUNING_1 brief §129. The fix direction is unconstrained by downstream consumers.

### 6. kbl_log — blast size

```sql
SELECT COUNT(*), MIN(ts), MAX(ts)
FROM kbl_log
WHERE component='alerts_to_signal_bridge'
  AND level='ERROR'
  AND message ILIKE '%invalid input syntax for type boolean%';
-- → total_errors: 479
-- → first_error: 2026-04-21 03:16:42.151705+00:00
-- → last_error:  2026-04-21 07:14:42.709936+00:00
-- → span:         ~238 min (~4 hours), 239 distinct minutes
```

Exact message (truncated for readability; all 479 are byte-identical except ts):

```
bridge tick failed: invalid input syntax for type boolean: "Lilienmatt"
LINE 6: ...at": "2026-04-21T03:16:38.990284+00:00"}'::jsonb, 'Lilienmat...
                                                             ^
```

The problem alert: one `deadline_cadence` row at `2026-04-21 03:16:38.990284`, matter_slug `lilienmat...`. Because hot.md contains `Lilienmatt` as a Director priority (matched substring), every bridge tick re-reads this alert, re-runs the matcher, re-hits the BOOLEAN wall, and rolls back — so the watermark never advances, so the same alert is re-tried on the next tick ad infinitum.

### 7. Impact assessment

- **Cycles missed since merge:** 479 ERROR rows over ~238 min with a 60s bridge tick → every tick since the Lilienmatt alert arrived has failed. Including a second tick some minutes (the distinct-minutes count of 239 is ~half the error count, so each minute records the APScheduler 60s fire + a ~second-fire overlap).
- **Signals dropped:** **zero.** The bridge INSERT is inside a single transaction per tick; the error raises, the tick rolls back, watermark stays pinned at its pre-Lilienmatt value. 15 alerts have arrived since the block started (03:16:42 → 07:14); all 15 are still in the `alerts` table waiting. On the first successful tick after the fix, they'll be processed in watermark order.
- **signal_queue state:** 16 rows total, 0 inserted in the last 4 hours, all with `hot_md_match IS NULL` — confirms the bridge has been cleanly stalled, not partially writing.
- **Log noise:** ~2 ERROR/min in `kbl_log` for 4 h (already 479 rows). Not critical but crowding the signal/noise ratio for other diagnostics.

### 8. Gate 1 impact — none

16 signals already in queue pre-date the block; Gate 1 (≥5-10 signals end-to-end Steps 1-7) is gated on `STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1` unblocking those existing rows, not on new bridge deposits. Per AI Head's framing: side-effect on Gate 1 is **zero**. Flagging for the record.

---

## Fix direction — TEXT

Change the **live column** to TEXT; fix the bootstrap DDL to match. Do NOT change the bridge code (it's already right).

**Rationale:**
- All code + tests + reviewer intent + migration say TEXT.
- Zero current readers would break on TEXT (there are no readers).
- The planned analytics surface ("which hot.md entries are firing?") needs the string, not a boolean.
- Coercing bridge to boolean (`bool(alert.get("hot_md_match"))`) would silently destroy the attribution and bake the BOOLEAN mistake in permanently. That's the wrong direction.

**One-liner shape (for the fix brief, not to ship from here):**

```sql
-- Requires explicit USING because there's no implicit bool→text cast.
-- All live values are NULL (confirmed: 16/16 rows NULL), so USING NULL is safe.
ALTER TABLE signal_queue
    ALTER COLUMN hot_md_match TYPE TEXT USING hot_md_match::text;
```

Paired with: update `memory/store_back.py:6213` to `hot_md_match TEXT,` so a fresh-DB boot lands the same type, and add a belt-and-suspenders `ALTER COLUMN ... TYPE TEXT` inside `_ensure_signal_queue_additions` (idempotent: `pg_typeof` check or wrap in an advisory-locked DO block) to self-heal on any already-deployed instance whose migration ran as a no-op.

---

## Stop-gap recommendations (not shipped)

Call-outs for the fix brief; none of these is a B2 action.

1. **Fix the migration runner's `ADD COLUMN IF NOT EXISTS` assumption.** The broader lesson: `ADD COLUMN IF NOT EXISTS` only guards presence, not shape. Any migration that follows a `_ensure_*_base` DDL path needs to actively reconcile types, not just be additive. Suggest the fix brief include a test that boots a fresh DB, then boots an old DB (with the legacy BOOLEAN), and asserts the column ends up TEXT in both cases.
2. **Add a schema-conformance boot check.** When `_ensure_signal_queue_base` runs, assert `pg_typeof(hot_md_match) = 'text'` (and any other column whose type has changed since KBL-19). Log WARN + self-heal with ALTER COLUMN TYPE (guarded by a one-time advisory lock). This is the same pattern STATUS-CHECK-EXPAND-1 used to re-assert the CHECK constraint on every boot — apply it to types too.
3. **Graceful degradation for the bridge.** Wrap the INSERT in try/except `psycopg2.errors.InvalidTextRepresentation`: on hit, advance the watermark past the offending alert and emit ERROR instead of rollback. Otherwise one malformed alert can block the entire bridge for the column's lifetime — exactly what happened here. Not a replacement for fixing the type, but a layered defense so no single alert can freeze the producer for hours again.
4. **Inventory drift check.** Quick one-off: dump `information_schema.columns` for signal_queue vs the union of all migration + bootstrap declarations, diff by column. If `hot_md_match` drifted on this column there may be others. The 35-column schema snapshot in `B2_pipeline_diagnostic_20260421.md` can serve as the reference side.
5. **Back-fill (optional, cosmetic).** After the ALTER COLUMN TYPE, the 16 existing NULL rows will stay NULL. That's correct — none of them actually matched hot.md before the column was added. No back-fill needed.

---

## Unblock effort estimate

**XS (<1h).** Tiny surgery: one ALTER COLUMN TYPE migration + one bootstrap-DDL edit + a regression test. No data migration (all rows NULL), no downstream consumer to coordinate with. The only reason it's XS-not-trivial is the need to land and deploy a migration (Migration Runner picks it up on boot) and wait for the next Render cycle.

---

## Proposed next brief

**`BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1`** — land a migration `ALTER TABLE signal_queue ALTER COLUMN hot_md_match TYPE TEXT USING hot_md_match::text;`, fix the BOOLEAN declaration in `memory/store_back.py:6213` to TEXT, add a boot-time type-reconciliation helper to `_ensure_signal_queue_additions`, and include a unit test that asserts `pg_typeof(hot_md_match) = 'text'` after running the full ensure-chain. Recovery: no rows to reset — the producer will drain the 15 stalled alerts on the next successful tick.

Suggested sequencing inside that brief: (1) write the migration + wire it into the runner; (2) add the `_ensure_*_additions` reconciliation so already-booted instances self-heal even if the migration ledger says "already applied"; (3) add the type-conformance regression test; (4) fix the BOOLEAN in `_ensure_signal_queue_base` so fresh DBs are correct from minute zero; (5) deploy; (6) tail `kbl_log` for one bridge cycle to confirm INSERTs resume + the 15 stranded alerts drain.

---

## Side observations (not blocking)

- **N1.** The migration-vs-bootstrap split is a systemic trap. Every `_ensure_*_base` in `store_back.py` duplicates DDL already covered by some migration. When the two drift (type change, constraint change, default change), the migration's `IF NOT EXISTS` / `ADD CONSTRAINT IF NOT EXISTS` path hides it. Recommend the fix brief note in `tasks/lessons.md`: "CREATE TABLE IF NOT EXISTS bootstrap and ALTER TABLE migrations must be reconciled — one must be the single source of type truth. Prefer migrations; make bootstrap a thin assert-or-create shim that errors loudly on type drift."
- **N2.** B3's PR #29 review was correct about the file on disk but didn't boot-test against a pre-existing `signal_queue`. Live-PG test matrix needs a scenario: "apply migration to a DB where the target column already exists with a different type." That scenario would have caught this pre-merge. Suggest including it in the fix brief's regression set.
- **N3.** The bridge's transactional rollback is why signals are preserved, not dropped. Same pattern as the Step 1 `raw_content` block: an upstream failure stalls the producer, which sounds bad but is actually the safe behaviour. Keep this pattern — do not "resilience" it into a silent-swallow.
- **N4.** Log volume from this incident (479 ERROR rows in 4 h, ~2/min) is high enough that if this were a production-grade alerting channel we'd want rate-limiting via `check_alert_dedupe` — the same bucket pattern `pipeline_tick.py` uses for the anthropic-circuit-open WARN (15-min bucket). The bridge's catch-all doesn't dedupe. Optional hardening; not a Gate 1 blocker.

---

## Next cycle

Closing tab per standing instruction #9. AI Head owns: (a) writing `BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1` brief, (b) dispatching to B1 (or auto-applying via Migration Runner if scoped small), (c) queuing me for the eventual review. The 15 alerts accumulated during the outage will drain automatically on the first successful bridge tick post-fix.
