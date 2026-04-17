# Schema FK Reconciliation — pre-staged schema v3

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) @ commit `16608b2`
**Date:** 2026-04-17
**Related commits:** `8782813` (schema v3 — landed before the task mailbox was formalized)

---

## TL;DR

Schema reconciled and pushed. All four required changes applied verbatim. psql dry-run **not executed** — local toolchain gap + `signal_queue` base table not yet bootstrapped on Render DB. Alternate structural checks pass. One naming-convention drift vs KBL-A §5 worth reconciling.

---

## Changes applied (commit `8782813`, file `briefs/_drafts/KBL_A_SCHEMA.sql`)

| # | Change | Location in file |
|---|---|---|
| 1 | `kbl_cost_ledger.signal_id`: `BIGINT` (no FK) → `INTEGER REFERENCES signal_queue(id) ON DELETE SET NULL` | §3, line 126 |
| 2 | `kbl_log.signal_id`: same | §4, line 156 |
| 3 | NEW table `kbl_alert_dedupe` (alert_key PK, first_seen, last_sent, send_count) | §5 (new section) |
| 4 | Header bumped to v3; caveat comment about "FK pending ID-type reconciliation" removed; cross-references updated to `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF_DRAFT.md §5` (commit `942c347`) | Top of file |

Section numbering shifted: `gold_promote_queue` is now §6 (was §5) to accommodate the new `kbl_alert_dedupe`.

---

## Signal-queue ID type — validated

KBL-19 spec ([`ARCHITECTURE_CORTEX_3T_KBL_UNIFIED.md:264`](../ARCHITECTURE_CORTEX_3T_KBL_UNIFIED.md)) declares `id SERIAL PRIMARY KEY`. In PostgreSQL, `SERIAL` expands to `INTEGER` (max 2.1B). KBL-A §5 locks this explicitly ("no bump to BIGSERIAL"). My reconciliation matches. No "wishful thinking" — type reflects KBL-19.

---

## Acceptance criterion — psql dry-run status: NOT EXECUTED

The task acceptance called for:

```bash
psql $DATABASE_URL -c "BEGIN; \i briefs/_drafts/KBL_A_SCHEMA.sql; ROLLBACK;"
```

**Three blockers to running it:**

1. **No `psql` on this workstation.** Not installed locally (`which psql` → not found; `brew list | grep postgres` → empty). Installing it is trivial but out of scope for the 15-min time budget.
2. **No `DATABASE_URL` accessible.** Local env has no Postgres creds. I'd need to SSH into a Render instance or the Mac Mini (if it has the URL set), or be handed the DSN.
3. **`signal_queue` does not exist on Render's DB yet.** Verified via `mcp__baker__baker_raw_query`:
   ```sql
   SELECT table_name FROM information_schema.tables WHERE table_name='signal_queue';
   -- No results found.
   ```
   Even if I had `psql` + creds, the first `ALTER TABLE signal_queue` would fail — not because my schema is wrong, but because KBL-A bootstrap (which creates signal_queue from KBL-19 spec) hasn't run yet. The pre-staged schema is explicitly designed to run **after** signal_queue is bootstrapped; the ordering constraint is documented in my v3 header.

**Recommended verification path for when KBL-A dispatches:**

Instead of the pure dry-run, wrap it in a shell that bootstraps a minimal signal_queue first:

```bash
psql $DATABASE_URL <<'SQL'
BEGIN;

-- Temporary KBL-19 shell (match production bootstrap shape):
CREATE TABLE IF NOT EXISTS signal_queue (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    source          TEXT,
    signal_type     TEXT,
    matter          TEXT,
    summary         TEXT,
    triage_score    INT,
    vedana          TEXT,
    hot_md_match    BOOLEAN,
    payload         JSONB,
    priority        TEXT DEFAULT 'normal',
    status          TEXT DEFAULT 'pending',
    stage           TEXT,
    enriched_summary TEXT,
    result          TEXT,
    wiki_page_path  TEXT,
    card_id         TEXT,
    ayoniso_alert   BOOLEAN DEFAULT FALSE,
    ayoniso_type    TEXT,
    processed_at    TIMESTAMPTZ,
    ttl_expires_at  TIMESTAMPTZ
);

\i briefs/_drafts/KBL_A_SCHEMA.sql

ROLLBACK;
SQL
```

This both proves the schema applies cleanly AND catches any interaction bugs with the KBL-19 base (CHECK constraint collisions, index name clashes, FK target-type mismatch).

**Alternate checks I did run (and pass):**

| Check | Result |
|---|---|
| File parses as text (no encoding glitches) | pass |
| `BEGIN`/`COMMIT` balanced | pass (1 of each) |
| `CREATE TABLE` count matches intent | 5 (runtime_state, cost_ledger, log, alert_dedupe, gold_promote) — pass |
| `REFERENCES signal_queue` count | 2 (cost_ledger, log) — pass |
| All statements terminate with `;` | pass (final-inflight-check reports 0) |
| FK targets `signal_queue(id)` which is `SERIAL` (INTEGER) — type-match | pass (both FK columns declared `INTEGER`) |
| `ON DELETE SET NULL` requires nullable FK columns — both `signal_id` columns are nullable (no `NOT NULL`) | pass |

---

## Concerns

### 1. FK constraint naming drift (minor — one-line fix either way)

KBL-A §5 lines 189 and 195 show FKs as **named** constraints:

```sql
ALTER TABLE kbl_cost_ledger
    ADD CONSTRAINT fk_cost_ledger_signal
    FOREIGN KEY (signal_id) REFERENCES signal_queue(id) ON DELETE SET NULL;
```

My v3 declares the FK **inline** in `CREATE TABLE`, which makes Postgres auto-name them `kbl_cost_ledger_signal_id_fkey` and `kbl_log_signal_id_fkey`. Both approaches work; both constraints behave identically. But the rollback SQL in my header assumes the auto-name, while KBL-A §5 uses the explicit name.

**Recommendation:** pick one for tidiness. Either:
- (a) KBL-A `_ensure_kbl_cost_ledger` uses inline FK (matches my draft; rollback per my header), OR
- (b) I switch to the `ADD CONSTRAINT fk_cost_ledger_signal` form (matches KBL-A §5's explicit-name style) and update rollback.

Option (b) is more readable in `\d` output and more conventional for named-constraint shops. Happy to switch if requested. Not a blocker either way.

### 2. Signal-queue bootstrap is now a hard prerequisite

With inline FKs, the `_ensure_` order becomes load-bearing at the SQL layer (not just the code layer). If anyone ever calls `_ensure_kbl_cost_ledger` before `_ensure_signal_queue_additions` (or before KBL-19 bootstrap), the CREATE TABLE fails cryptically with "relation signal_queue does not exist". Mitigation already in my v3 header, but worth an R1 confirm that `SentinelStoreBack` enforces the order.

### 3. `TRUNCATE signal_queue` will now fail without `CASCADE`

Not a change in my draft — a natural consequence of the ON-DELETE-SET-NULL FK. Ops running `TRUNCATE signal_queue` to reset dev state will hit:

```
ERROR: cannot truncate a table referenced in a foreign key constraint
```

and must use `TRUNCATE signal_queue, kbl_cost_ledger, kbl_log RESTART IDENTITY` or `TRUNCATE signal_queue CASCADE`. Worth a one-line note in whatever dev-reset doc KBL-A produces.

### 4. Forward-compat: INTEGER ceiling is generous but not infinite

`INTEGER` = 2^31 - 1 = 2.1B signals. At KBL's projected scale (a few hundred per day), that's ~11M years of headroom. No concern for Phase 1. If KBL-C ever ingests high-volume social / market-data feeds at millions per day, revisit at that point. Purely informational.

---

## What I did not do

- **Did not change FK to explicit-name form.** The task spec didn't mandate a specific form; inline FK is functionally equivalent. Flagged above for reconciliation if preferred.
- **Did not add `kbl_alert_dedupe` purge SQL.** Per KBL-A §5 comment, purge is a scheduled script (`kbl-purge-dedupe.sh`), not schema.
- **Did not apply the schema.** Pre-stage only per task instructions.

---

## Standing by

Per task §"What to do AFTER this task": waiting on Code Brisen #1's R1 review verdict on KBL-A. No proactive work from me until next `CODE_2_PENDING.md` update.
