---
status: OPEN
brief: cortex_v1_dry_run_cycle_1_retry
trigger_class: HIGH
dispatched_at: 2026-04-28T18:30:00Z
unblock_event: PR #77 merged 207aae4 (config-import fix); A /security-review NO FINDINGS; auto-deploy in flight
prior_attempt_cycle_id: 0e503e5e-f2e5-461a-acef-9f2482f6f2ee (BLOCKED on Phase 3a config import)
original_dispatched_at: 2026-04-28T18:05:00Z
dispatched_by: ai-head-a
director_authorization: 2026-04-28T~18:00Z "now"
target_matter_slug: oskolkov
target_plan_section: §2.1 (manual director-question trigger)
prerequisite_state: §1 cleared (deploy dep-d7of8n84un4s73bn2rb0 live; CORTEX_DRY_RUN=true / CORTEX_PIPELINE_ENABLED=false / CORTEX_LIVE_PIPELINE=true verified; matter_config_drift_weekly next_run 2026-05-04T11:00 UTC)
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: briefs/_reports/B3_dry_run_cycle_1_20260428.md
autopoll_eligible: false
---

# CODE_3_PENDING — B3: CORTEX V1 DRY_RUN — CYCLE 1 RETRY POST-PR-#77-MERGE — 2026-04-28

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b3`
**Plan:** [`briefs/_plans/CORTEX_V1_DRY_RUN_LAUNCH_PLAN_20260428.md`](../_plans/CORTEX_V1_DRY_RUN_LAUNCH_PLAN_20260428.md) §2.1 → §3
**Trigger class:** HIGH (first cycle on real matter — counts toward §6 Q1 ≥5 consecutive clean cycles only on retry success)

## Unblock event

PR #77 (`CORTEX_PHASE3_CONFIG_IMPORT_FIX_1`) merged `207aae4` 2026-04-28T~18:25Z:
- 2-line surgical fix (`from orchestrator import config` → `from config.settings import config`) in `cortex_phase3_reasoner.py:117` + `cortex_phase3_synthesizer.py:63`
- A /security-review NO FINDINGS posted (PR #77 comment 4338023426)
- 25/25 cortex_phase3_* tests still green
- Render auto-deploy on push to main triggered

## Pre-flight before re-fire

Verify the deploy carrying `207aae4` is LIVE before re-firing:

```bash
# Quickest check — Render dashboard shows deploy commit + status:
# https://dashboard.render.com/web/srv-d6dgsbctgctc73f55730/deploys

# OR via Render CLI on your machine:
render deploys list srv-d6dgsbctgctc73f55730 --limit 2

# OR poll Baker /api/health and watch checked_at advance past PR #77 merge time:
curl -s https://baker-master.onrender.com/api/health | jq '.checked_at'
# (deploy_sha not surfaced; use Render dashboard for SHA confirmation)
```

DO NOT re-fire until you've seen `207aae4` (or later) live on Render. Otherwise cycle will hit the same import defect.

## What you're executing

Plan §2.1 verbatim — manual director-question trigger via Python shell with prod env. Capture printed `cycle_id`, then run plan §3 validation queries against it.

## Execution path — pick one

**Option A — Render shell SSH (preferred, closest to prod):**

```bash
# From your local machine:
render ssh srv-d6dgsbctgctc73f55730
# (if `render` CLI not installed: brew install render-oss/render/render OR use Render dashboard "Shell" tab)

# Once shell'd in, run:
python3 - <<'PY'
import asyncio
from orchestrator.cortex_runner import maybe_run_cycle

async def main():
    cycle = await maybe_run_cycle(
        matter_slug="oskolkov",
        triggered_by="director",
        director_question=(
            "DRY_RUN cycle 1 — synthesize current state of the AO matter "
            "from cortex-config + curated. No live action required."
        ),
    )
    print(f"cycle_id={cycle.cycle_id} status={cycle.status} "
          f"current_phase={cycle.current_phase} "
          f"cost_tokens={cycle.cost_tokens} cost_dollars=${cycle.cost_dollars:.4f}")

asyncio.run(main())
PY
```

**Option B — local with `op run` for prod env (fallback):**

```bash
cd ~/bm-b3
git checkout main && git pull -q

# Build prod-env shim from 1Password — minimum vars:
export DATABASE_URL=$(op read 'op://Baker API Keys/DATABASE_URL/credential')
export BAKER_VAULT_PATH=/Users/dimitry/baker-vault
export ANTHROPIC_API_KEY=$(op read 'op://Baker API Keys/API Anthropic/credential' 2>/dev/null || echo "")
export CORTEX_DRY_RUN=true
export CORTEX_LIVE_PIPELINE=true
export CORTEX_PIPELINE_ENABLED=false

# Verify env loaded:
python3 -c "import os; print('DB ok:', bool(os.getenv('DATABASE_URL'))); print('vault ok:', os.path.isdir(os.getenv('BAKER_VAULT_PATH','')))"

# Then run the same heredoc script as Option A.
```

## Capture (paste literal stdout into ship report)

The Python script's `print(...)` line — exact format:
```
cycle_id=<UUID> status=<...> current_phase=<...> cost_tokens=<int> cost_dollars=$<float>
```

Note the cycle_id — every §3 query keys off it.

## Then — run plan §3 validation against the captured cycle_id

Replace `<UUID>` placeholder in plan §3's 6 queries with the real cycle_id and execute via Baker MCP `baker_raw_query` (read-only). Paste literal SQL + literal result for each.

Cross-check expected timing/cost from plan §2.3:
- Total wall-clock: 25-65s
- Cost: $0.03-0.25 (driven by specialist count)
- Phase sequence: 1 sense → 2 load → 3a meta → 3b invocations → 3c synth → 4 propose (+ DRY_RUN marker artifact at phase_order=8)

## Pass criteria

- Cycle runs to terminal status (`tier_b_pending` for DRY_RUN, NOT `failed`)
- All 6 §3 queries return expected non-empty rows for THIS cycle_id
- `dry_run_marker` artifact present at phase_order=8
- No Slack DM (DRY_RUN gating verified)
- Cost within $0.25 ceiling
- Wall-clock within 65s
- No exceptions in Render logs (`render logs srv-d6dgsbctgctc73f55730 --tail 200 | grep -E "ERROR|Traceback|cortex"`)

## STOP criteria (fire rollback if any tripped)

Plan §4 lists 9 STOP criteria F1–F9. Most relevant for cycle 1:
- F1: cycle hits `status='failed'` (vs expected `tier_b_pending`)
- F4: cost > $1.00 (cycle 1 budget cap is $0.25; $1.00 is panic ceiling)
- F5: wall-clock > 300s timeout
- F6: GOLD write attempted (must NOT happen under DRY_RUN — Phase 5 stub-only)
- F7: Slack DM sent (must NOT happen under DRY_RUN)

If any tripped → flip `CORTEX_DRY_RUN→true` (already true), `CORTEX_LIVE_PIPELINE→false`, then dispatch decommission+rollback (or call A in chat for guidance — don't auto-rollback for cycle 1).

## Output

**Same ship report — append a new section, do NOT overwrite the BLOCKED attempt 1 narrative:**

`briefs/_reports/B3_dry_run_cycle_1_20260428.md`

Add a `## Cycle 1 retry — post-PR-#77-merge` section with:
- Re-fire timestamp + deploy SHA confirmed
- New cycle_id captured
- Plan §3 validation queries (all 6) re-executed against the new cycle_id with literal SQL + literal results
- DRY_RUN gating verification (dry_run_marker / Slack / GOLD / MAC_MINI)
- Promotion criteria contribution (1/5 only on PASS)

## Original output spec (still applies for the retry section)

Format:
```markdown
# B3 — Cortex V1 DRY_RUN — first cycle on AO matter — 2026-04-28

## Execution path
<Option A or B + actual command sequence>

## Cycle output
cycle_id=<UUID> status=<...> current_phase=<...> cost_tokens=<int> cost_dollars=$<float>
Wall-clock: <Ns>

## Render log excerpts (sentinel.cortex_*)
<grep output for the cycle_id timeframe>

## Plan §3 validation queries (against this cycle_id)
### Query 1 — cycle row final state
SQL: <literal>
Result: <literal>
Status: PASS / FAIL <reason>
... (repeat for queries 2-6)

## DRY_RUN gating verification
- dry_run_marker artifact at phase_order=8: PRESENT/MISSING
- Slack chat_postMessage: SKIPPED/FIRED
- GOLD write: SKIPPED/FIRED
- MAC_MINI propagate: SKIPPED/FIRED

## Verdict
PASS / PARTIAL / FAIL with one-line summary.

## Promotion-criteria contribution (plan §6)
- Q1 cycle ran cleanly: 1/5
- Cost < €0.50: 1/5
- p95 ≤ 60s: 1/5
- dry_run_marker present: 1/5
```

Notify A in chat with: cycle_id + verdict + cost + wall-clock.

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
