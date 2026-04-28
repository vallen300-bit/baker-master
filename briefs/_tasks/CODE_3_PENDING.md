---
status: COMPLETE
brief: cortex_v1_dry_run_cycles_2_through_5
trigger_class: HIGH
dispatched_at: 2026-04-28T19:38:00Z
predecessor_pass: cycle_1_attempt_5 d91a2252-d65a-45f9-a7dc-1338fa4e0990 (PASS, $0.1519, 40.6s DB / 223s python cold-start, sales 14.8s × 1)
director_authorization: "no time left, we need to go into business with cortex"
target_matter_slug: oskolkov
goal: "Run 4 more consecutive clean cycles (2,3,4,5) to satisfy §6 Q1 N≥5 promotion gate. Same bland prompt; expect Phase 3a to pick from 10 active capabilities; russo_*+legal stay disabled."
claimed_at: 2026-04-28T19:48:00Z
claimed_by: b3
last_heartbeat: 2026-04-28T19:55:00Z
blocker_question: null
ship_report: briefs/_reports/B3_dry_run_cycle_1_20260428.md (continue appending sections per cycle)
verdict: PASS
promotion_gate_q1: "5/5 CLEARED"
cycle_ids:
  - cycle_1: d91a2252-d65a-45f9-a7dc-1338fa4e0990
  - cycle_2: 7729f6d2-20ab-45c5-96cb-42f9e44347db
  - cycle_3: 1dd70f9a-20a4-4538-ae74-e3666707c701
  - cycle_4: b010cf3a-82a3-40ce-9819-625086ea32f6
  - cycle_5: 972b788b-3158-496f-a162-2c0dbda28201
total_cost_dollars: 0.7378
p95_wall_db_seconds: 40.6
p50_wall_db_seconds: 37.8
all_dry_run_markers_present: true
slack_posts_under_dry_run: 0
gold_writes_under_dry_run: 0
phase3a_picks: "all 5 cycles picked ['sales'] (bland prompt's 'pipeline' regex hit deterministic)"
ready_for_live_flip: true
autopoll_eligible: false
---

# CODE_3_PENDING — B3: CORTEX V1 DRY_RUN — CYCLES 2 THROUGH 5 (lock in N=5 promotion gate) — 2026-04-28

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b3`
**Trigger class:** HIGH

## Predecessor

Cycle 1 attempt 5 PASS (`d91a2252`, $0.1519, 40.6s DB, sales specialist 14.8s × 1 attempt). All 7 artifacts incl. dry_run_marker. STOP F1-F9 clean.

§6 Q1 promotion progress: **1/5** ✓ — need 4 more consecutive clean cycles.

## Strategy

Run cycles 2-5 sequentially with the SAME bland prompt as cycle 1. Each cycle's Phase 3a may pick a different capability (or same `sales`). As long as the picked capability is in the 10 active set (NOT russo_* and NOT legal — those stay disabled), the cycle should complete cleanly.

If any cycle 2-5 hits a NEW capability that times out — surface to A; A disables that capability + dispatches the failing cycle's retry. Resume the count.

## Execution — single python3 session, all 4 cycles back-to-back

```bash
cd ~/bm-b3
git checkout main && git pull -q

export DATABASE_URL=$(op read 'op://Baker API Keys/DATABASE_URL/credential')
export BAKER_VAULT_PATH=/Users/dimitry/baker-vault
export ANTHROPIC_API_KEY=$(op read 'op://Baker API Keys/API Anthropic/credential' 2>/dev/null || echo "")
export CORTEX_DRY_RUN=true
export CORTEX_LIVE_PIPELINE=true
export CORTEX_PIPELINE_ENABLED=false

python3 - <<'PY'
import asyncio
from orchestrator.cortex_runner import maybe_run_cycle

async def main():
    results = []
    for n in [2, 3, 4, 5]:
        c = await maybe_run_cycle(
            matter_slug="oskolkov",
            triggered_by="director",
            director_question=f"Smoke test cycle {n}. No analysis required. Just confirm cycle pipeline executes end to end.",
        )
        line = f"cycle_{n}: cycle_id={c.cycle_id} status={c.status} current_phase={c.current_phase} cost_tokens={c.cost_tokens} cost_dollars=${c.cost_dollars:.4f}"
        print(line)
        results.append(line)
        if c.status == "failed":
            print(f"!! cycle {n} status=failed — STOP batch, surface to A")
            break
    print("---")
    print("BATCH SUMMARY:")
    for r in results:
        print(r)

asyncio.run(main())
PY
```

(Single python session = warm cache; cycles 3-5 should be ~15-30s each since Anthropic prompt cache is hot from cycle 2.)

## Per-cycle pass criteria

- status terminal: `tier_b_pending` (NOT `failed`)
- Wall-clock DB-side < 65s
- dry_run_marker artifact PRESENT
- No GOLD write
- No Slack DM
- Cost < $0.50

## Batch pass criteria — §6 Q1 promotion gate

- 4 sequential PASS cycles (cycles 2, 3, 4, 5)
- Combined with cycle 1 PASS = N=5 consecutive clean cycles
- 0 archive failures across the 5 cycles
- Per-cycle p95 ≤ 60s
- dry_run_marker every cycle

## STOP criteria

- Any cycle status='failed' → STOP batch, surface cycle_id + which Phase 3a capability picked. Don't fire next cycle. A disables culprit + dispatches retry.
- Cost > $0.50 on any cycle → STOP, surface
- GOLD write fired → STOP

## Output

Append 4 sections to `briefs/_reports/B3_dry_run_cycle_1_20260428.md`:

```markdown
## Cycle 2 — N=5 promotion sequence (1/4)
- cycle_id: <UUID>
- Phase 3a picked: <list>
- Wall-clock DB-side: <Ns>
- Cost: $<float>
- dry_run_marker: PRESENT
- Verdict: PASS / FAIL

## Cycle 3 — N=5 promotion sequence (2/4)
... (same shape)

## Cycle 4 — N=5 promotion sequence (3/4)
...

## Cycle 5 — N=5 promotion sequence (4/4) — LAST
...

## §6 promotion gate Q1 final tally
- 5 / 5 consecutive clean cycles: PASS / FAIL
- 0 archive failures: PASS / FAIL
- Per-cycle p95: <Ns>
- Cost ceiling: <$max>
- All 5 dry_run_markers PRESENT: PASS / FAIL
- Verdict: PROMOTION GATE Q1 CLEARED / BLOCKED
```

Notify A with: 5 cycle_ids + verdict + total cost + p95 wall-clock.

## After all 5 PASS — A's next move

§6 promotion sequence triggers (A executes):
1. Flip `CORTEX_DRY_RUN=false` via Render env PUT
2. Flip `CORTEX_PIPELINE_ENABLED=true` (enables auto-dispatch from alerts_to_signal)
3. Render redeploy
4. Cortex goes LIVE on AO matter

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
