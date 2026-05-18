# BRIEF: STALE_CYCLE_NUDGE_SENTINEL_1 — catch stale `tier_b_pending` Cortex cycles

## Context

Real scar 2026-05-05 → 2026-05-15: Oskolkov cycle `c4242a20-3ded-4885-8cba-d4fe3f0cff70` reached terminal status `tier_b_pending` 2026-05-05 with 10 proposed actions awaiting Director Tier-B ratification — then sat **10 days unratified** until a fresh Oskolkov cycle (f2954da4) accidentally resurfaced the same proposals. The russo_fr specialist on f2954da4 named the gap explicitly: "nudge sentinel for stale tier_b_pending cycles isn't built." Without the second cycle's accident, c4242a20 would still be stale today.

This brief builds the nudge sentinel. Small + low-risk. Director said "park" 2026-05-15; AH1 picked up next bench window per `_ops/agents/aihead1/PINNED.md §I`.

## Estimated time: ~1-2 builder-hours
## Complexity: Low
## Target: b4 (idle since BAKER_WA_PULL_API_1 #218 merged today; b3 busy on cowork-ah1 dispatch)
## Target repo: baker-master
## Matter slug: baker-internal
## Trigger class: LOW (one new APScheduler job + one helper module + one migration adding nullable column; ClickUp write under existing BAKER-space allowlist; no new external surface; no auth/DB schema change beyond additive column)

## Prerequisites
- ClickUp `clickup_client.create_task` already shipped (baker-master `clickup_client.py:272`).
- `cortex_cycles` table already carries `status` + `created_at` (orchestrator/cortex_runner.py).
- `BAKER_CLICKUP_READONLY=true` kill switch already wired — sentinel must respect it (skip cleanly).

---

## Items

### F1 — Migration: `cortex_cycles.last_nudge_at TIMESTAMPTZ NULL`

**Where:** `migrations/` (next available migration number; check `applied_migrations.lock`).

**Schema:** `ALTER TABLE cortex_cycles ADD COLUMN IF NOT EXISTS last_nudge_at TIMESTAMPTZ NULL;` (additive, idempotent, zero-downtime).

**Why:** anti-spam state. Without it, the sentinel re-fires every run and floods ClickUp with duplicate stale-cycle tasks.

---

### F2 — Sentinel module: `triggers/stale_cycle_nudge_sentinel.py`

**Contract:**

```python
def run_stale_cycle_nudge_sentinel() -> dict:
    """
    Daily APScheduler entry. Returns {"checked": N, "nudged": M, "skipped_readonly": bool}.

    Logic:
      1. If BAKER_CLICKUP_READONLY=true → return {"checked": 0, "nudged": 0, "skipped_readonly": True}.
      2. Query cortex_cycles WHERE status='tier_b_pending'
           AND created_at < NOW() - INTERVAL '3 days'
           AND (last_nudge_at IS NULL OR last_nudge_at < NOW() - INTERVAL '7 days')
         ORDER BY created_at ASC LIMIT 10.
      3. For each row: ClickUp create_task in BAKER space, list 901521426367 (Handoff Notes):
           - name: f"Stale tier_b_pending: {matter_slug} / {cycle_id[:8]} — {days_stale}d"
           - description: link to dashboard /cortex/cycle/{cycle_id} + matter slug + age in days
                          + "Action: ratify in dashboard or close cycle if abandoned"
           - tags: ["stale-cycle", "tier-b-pending", matter_slug]
      4. After successful ClickUp post: UPDATE cortex_cycles SET last_nudge_at=NOW() WHERE cycle_id=%s.
      5. Wrap each row's ClickUp + UPDATE in its own try/except — one row's failure must not block the others.
      6. Report via triggers.sentinel_health.report_success("stale_cycle_nudge") / report_failure on hard error.
    """
```

**Threshold tuning:**
- 3 days stale before first nudge: Director's typical ratification cadence is 1-2 days; 3 days = signal, not noise.
- 7 days re-nudge interval: avoids spam; surfaces persistent stalls without becoming wallpaper.
- LIMIT 10 per run: hard ceiling on ClickUp writes per fire (under the 10/cycle BAKER-space rule).

**PG safety:** `conn.rollback()` in every except block before any new query (per `.claude/rules/python-backend.md`). LIMIT on the SELECT.

---

### F3 — Scheduler wiring

**Where:** `triggers/embedded_scheduler.py` (after the existing `daily_briefing` job around L282-288 — consistent ordering with other once-daily UTC jobs).

```python
from triggers.stale_cycle_nudge_sentinel import run_stale_cycle_nudge_sentinel
scheduler.add_job(
    run_stale_cycle_nudge_sentinel,
    CronTrigger(hour=7, minute=0, timezone="UTC"),
    id="stale_cycle_nudge", name="Stale tier_b_pending cycle nudge",
    coalesce=True, max_instances=1, replace_existing=True,
)
logger.info("Registered: stale_cycle_nudge (daily 07:00 UTC)")
```

07:00 UTC chosen because (a) after `daily_briefing` 06:00 UTC + `wiki_lint` 06:30 UTC so Director's morning brief surface lands first, (b) ClickUp tasks appear in Director's board before workday CET start (09:00 CET).

---

## Acceptance criteria

1. F1 + F2 + F3 implemented per contracts above.
2. **Live dry-run** (with `BAKER_CLICKUP_READONLY=true`): module imports clean, query executes, returns `{"checked": N, "nudged": 0, "skipped_readonly": True}` without ClickUp writes.
3. **Live wet-run** (`BAKER_CLICKUP_READONLY` unset, only against a seeded test row): one ClickUp task created in BAKER space list 901521426367, `last_nudge_at` updated on the row.
4. **Anti-spam smoke:** second wet-run against same row within 7 days returns 0 nudged.
5. All existing tests still pass. New tests: ≥6 (see Test Plan below).

## Test plan

In `tests/test_stale_cycle_nudge_sentinel.py`:
- `test_skipped_when_clickup_readonly` — env var set → returns skipped_readonly=True, zero PG writes.
- `test_returns_zero_when_no_stale_cycles` — empty matching set → 0 nudged, no ClickUp call.
- `test_nudges_cycle_older_than_threshold` — seeded row with created_at = NOW() - 4 days, last_nudge_at NULL → 1 nudged, ClickUp called once, last_nudge_at set.
- `test_skips_cycle_nudged_within_window` — last_nudge_at = NOW() - 3 days → 0 nudged.
- `test_renudges_cycle_after_window` — last_nudge_at = NOW() - 8 days → 1 nudged.
- `test_one_row_failure_does_not_block_others` — 3 stale rows; ClickUp mock raises on row 2 → rows 1 + 3 nudged, row 2 reported failure, no cross-contamination.

All tests use `monkeypatch` against `clickup_client.create_task` + an isolated test DB row in `cortex_cycles`. Live-PG tests skip cleanly without `TEST_DATABASE_URL` per repo convention.

## Ship gate

- PR opened against baker-master main from branch `b4/stale-cycle-nudge-sentinel-1`.
- Trigger class LOW → AH2 Gate 1 + Gate 2 (`/security-review`) required; Gate 3 + Gate 4 NOT required.
- Commit identity: Code Brisen #4 <b4@brisengroup.com>.
- Standard contract: no `--no-verify`, never bypass hooks.
- Bus-post `ship/stale-cycle-nudge-sentinel-1` to `lead` on PR open.

## Out of scope (do NOT include)

- Auto-ratification / auto-close logic — Director-only authority (Tier B prerogative §4).
- Slack push for stale cycles — ClickUp is the chosen surface this round; Slack can be a future fast-follow if Director asks.
- Bus-post to `lead` on every stale-cycle — ClickUp is the Director-eyeball surface; bus would be noise for inter-agent traffic.
- WAHA / Gmail / email notification paths — same rationale, ClickUp is the single surface this round.

---

**Anchor:** Director ratification 2026-05-18 chat — "go" on AH1 recommendation to draft stale-cycle nudge sentinel as next item (punch-list item #7). Russo_fr finding documented in `_ops/agents/ai-head/CYCLE_REGISTER.md` lines 76+97. Scar cycle: c4242a20 10-day stall 2026-05-05 → 2026-05-15.
