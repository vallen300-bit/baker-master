# Cortex Stage 2 V1 — DRY_RUN launch plan + first-cycle monitoring checklist

**Date:** 2026-04-28
**Author:** Code Brisen #3 (b3) — built 1A (PR #71) + 1B (PR #72) + 1C (PR #74)
**Audience:** Director Dimitry Vallen, AI Head A
**Scope target:** post-merge of PR #74 (`CORTEX_3T_FORMALIZE_1C`)
**Source briefs:** `briefs/BRIEF_CORTEX_3T_FORMALIZE_1A.md`, `1B.md`, `1C.md`
**Source ship reports:** `briefs/_reports/B3_pr71_…1a_20260427.md`, `B3_pr72_…1b_20260428.md`, `B3_pr74_…1c_20260428.md`
**Architecture anchor:** `_ops/processes/cortex-architecture-final.md` (RA-23) + `_ops/ideas/2026-04-27-cortex-3t-formalize-spec.md` (RA-22)

This plan is **operational documentation of shipped V1**. It is the
literal Director-runnable checklist for the first AO matter cycle. No
new scope.

---

## 0. Hard preconditions before flipping any flag

| # | Precondition | Verification command | Pass criterion |
|---|---|---|---|
| 0.1 | PR #74 merged to `main` | `gh pr view 74 --json state` | `"state":"MERGED"` |
| 0.2 | Render `baker-master` deploy from post-merge `main` is `live` | `curl -s https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730/deploys?limit=1 -H "Authorization: Bearer $RENDER_API_KEY" \| jq '.[0].deploy.status'` | `"live"` |
| 0.3 | All three migrations applied on production Neon | `SELECT 'cortex_cycles', count(*) FROM cortex_cycles UNION ALL SELECT 'cortex_phase_outputs', count(*) FROM cortex_phase_outputs UNION ALL SELECT 'feedback_ledger', count(*) FROM feedback_ledger;` | All three return rows (count ≥ 0; tables exist) |
| 0.4 | `oskolkov` slug canonical in `baker-vault/slugs.yml` | `python3 -c "from kbl import slug_registry; print(slug_registry.is_canonical('oskolkov'))"` | `True` |
| 0.5 | Vault path resolvable inside Render container | `curl -s https://baker-master.onrender.com/api/health \| jq '.vault'` | non-null path |
| 0.6 | Mac Mini SSH-mirror NOT yet wired (`MAC_MINI_HOST` unset → log-only — desired for DRY_RUN) | Render env API GET — see §1.1 | `MAC_MINI_HOST` absent or empty |

---

## 1. Pre-flight checklist — environment variables on Render

### 1.1 Read current state

```bash
# Replace via 1Password if interactive shell:
RENDER_API_KEY=$(op read 'op://Private/Render API Key/credential')
SERVICE_ID=srv-d6dgsbctgctc73f55730

curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/$SERVICE_ID/env-vars" \
  | jq '.[] | .envVar | {key, value: (.value | tostring | .[0:6] + "…")}' \
  | grep -E "CORTEX_|SLACK_BOT_TOKEN|DATABASE_URL|BAKER_VAULT_PATH|AO_SIGNAL_DETECTOR_ENABLED|MAC_MINI_HOST"
```

### 1.2 Required env-var matrix (DRY_RUN target state)

The full set of env vars 1A/1B/1C touch, with the value each MUST hold for the first DRY_RUN cycle:

| Env var | DRY_RUN value | Default | Owner | Purpose | Source file |
|---|---|---|---|---|---|
| `CORTEX_DRY_RUN` | **`true`** | `false` | 1C | Phase 4 skips Slack post + writes `dry_run_marker`; Phase 5 `cortex_approve` skips execute / GOLD / propagate | `orchestrator/cortex_phase4_proposal.py:50` + `cortex_phase5_act.py:31` |
| `CORTEX_PIPELINE_ENABLED` | **`false`** | `false` | 1C/A2 | Gates `_dispatch_cortex_for_inserted` at `kbl/bridge/alerts_to_signal.py:495`. Off = no auto-dispatch from incoming bridged signals; manual triggers only. | `triggers/cortex_pipeline.py` (added in 1C) |
| `CORTEX_LIVE_PIPELINE` | **`true`** | `false` | 1A | Inside `triggers.cortex_pipeline.maybe_trigger_cortex` — flips the runner from dormant-stub to actually calling `maybe_run_cycle`. Required `true` so manual `maybe_trigger_cortex` calls actually execute the cycle. | `triggers/cortex_pipeline.py:23-25` |
| `CORTEX_CYCLE_TIMEOUT_SECONDS` | `300` (default) | `300` | 1A | Hard 5-min `asyncio.wait_for` cap on the entire cycle | `orchestrator/cortex_runner.py:34` |
| `CORTEX_DRIFT_AUDIT_ENABLED` | `true` (default) | `true` | 1C | Mon 11:00 UTC drift job registration | `triggers/embedded_scheduler.py` (1C-added block) |
| `CORTEX_DRIFT_THRESHOLD_DAYS` | `30` (default) | `30` | 1C | Drift age threshold | `orchestrator/cortex_drift_audit.py:21` |
| `MAC_MINI_HOST` | **unset** | unset | 1C | Absent → curated propagation log-only (desired for DRY_RUN). Set later post-promotion. | `orchestrator/cortex_phase5_act.py:336` |
| `SLACK_BOT_TOKEN` | (existing prod token) | required | global | Phase 4 `chat_postMessage` — irrelevant under DRY_RUN but must be present so the non-DRY path is testable later | `outputs/slack_notifier.py:127` |
| `BAKER_VAULT_PATH` | (existing prod path) | required | global | Slug registry + Phase 2 loaders + drift audit + GOLD proposer | `kbl/slug_registry.py:59`, `kbl/gold_proposer.py:53`, `orchestrator/cortex_drift_audit.py:24` |
| `DATABASE_URL` | (existing prod Neon) | required | global | All phase persistence | `memory/store_back.py` |
| `BAKER_API_KEY` | (existing prod key) | required | global | `POST /cortex/cycle/{id}/action` `X-Baker-Key` auth | `outputs/dashboard.py:95` |
| `AO_SIGNAL_DETECTOR_ENABLED` | (leave existing) | true | legacy | Pre-decommission — orthogonal to Cortex; Steps 34-35 turn it off **after** DRY_RUN promotion | (legacy) |

### 1.3 Apply DRY_RUN flag set (Render API merge mode)

Per `.claude/rules/python-backend.md` ("Render env vars: use MCP merge mode, NEVER raw PUT") — use the `baker_render_env_merge` MCP tool, OR the Render env-vars PATCH endpoint, NEVER a raw PUT (that would wipe other env vars).

**Option A — Baker MCP merge (preferred, atomic):**
```bash
curl -s -X POST "https://baker-master.onrender.com/mcp?key=$BAKER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_render_env_merge","arguments":{"service_id":"srv-d6dgsbctgctc73f55730","updates":{"CORTEX_DRY_RUN":"true","CORTEX_PIPELINE_ENABLED":"false","CORTEX_LIVE_PIPELINE":"true"}}}}'
```

**Option B — Render API PATCH (manual fallback):**
```bash
RENDER_API_KEY=$(op read 'op://Private/Render API Key/credential')
curl -fsS -X PATCH "https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730/env-vars" \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '[
    {"key":"CORTEX_DRY_RUN","value":"true"},
    {"key":"CORTEX_PIPELINE_ENABLED","value":"false"},
    {"key":"CORTEX_LIVE_PIPELINE","value":"true"}
  ]'
```

Trigger redeploy after env merge:
```bash
curl -fsS -X POST "https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730/deploys" \
  -H "Authorization: Bearer $RENDER_API_KEY"
```

### 1.4 Re-verify post-deploy

```bash
# Wait for deploy live, then read back:
curl -s https://baker-master.onrender.com/api/health | jq '.deploy_sha'

# Confirm flags are seen by the running process via a simple cortex-aware endpoint
# (after PR #74 merge, /api/health returns scheduler.jobs which must include
# matter_config_drift_weekly):
curl -s "https://baker-master.onrender.com/api/health/scheduler" \
  -H "X-Baker-Key: $BAKER_API_KEY" \
  | jq '.jobs[] | select(.id == "matter_config_drift_weekly")'
# Expected: one row, next_run_time = next Monday 11:00 UTC
```

---

## 2. First-cycle test plan on AO matter

### 2.1 Trigger source — manual director-question (recommended for first cycle)

We do NOT rely on auto-dispatch from `alerts_to_signal` for the first cycle, because:

1. `CORTEX_PIPELINE_ENABLED=false` keeps the `_dispatch_cortex_for_inserted` call site dormant (Amendment A2 default).
2. Manual triggering gives a known signal text → known specialist set → bounded cost ceiling.
3. Reproducible — cycle can be re-fired identically if the first run is inconclusive.

Trigger via `python3` shell on the Render service or local dev pointed at production Neon:

```bash
# Director runs from Render shell or `op run` with prod env:
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

Capture the printed `cycle_id` — every validation query in §3 keys off it.

### 2.2 Alternative trigger — manual `signal_queue` INSERT (Amendment A2 path test)

Used in cycle 2+ to validate the `alerts_to_signal` → `cortex_pipeline.maybe_dispatch` wire-up. **Do NOT use for cycle 1** (couples two unknowns).

```sql
-- Set CORTEX_PIPELINE_ENABLED=true first, then:
INSERT INTO signal_queue (
    source, signal_type, matter, primary_matter,
    summary, priority, status, stage, payload, hot_md_match
) VALUES (
    'manual_test', 'director_question', 'oskolkov', 'oskolkov',
    'DRY_RUN cycle 2 — synthesize AO matter status', 3,
    'new', 'classified',
    '{"alert_id": "dry-run-cycle-2", "alert_source_id": "manual"}'::jsonb,
    NULL
) RETURNING id;
```

The bridge tick won't fire this row (it's already in `signal_queue`), but `_dispatch_cortex_for_inserted` is invoked from inside `run_bridge_tick` after each tick's commits. To exercise it, instead INSERT into `alerts` and let the bridge tick map it — that's the canonical end-to-end test.

### 2.3 Expected Phase 1→6 sequence with timing budget

| Phase | Order | What runs | DB writes | Timing budget | Cost budget |
|---|---|---|---|---|---|
| 1 sense | 1 | `_phase1_sense` — INSERT cycle row (status='in_flight', current_phase='sense') + INSERT phase artifact (phase='sense', phase_order=1, artifact_type='cycle_init') | `cortex_cycles` (1) + `cortex_phase_outputs` (1) | <100ms | $0 |
| 2 load | 2 | `_phase2_load` — `load_phase2_context` reads vault `wiki/matters/oskolkov/cortex-config.md` + `curated/*.md` + recent emails/whatsapp/meetings; INSERT phase artifact + UPDATE `last_loaded_at` | `cortex_phase_outputs` (1) + `cortex_cycles` (1 UPDATE) | 200ms-1.5s (vault I/O + 5 SQL queries) | $0 |
| 3a meta-reason | 3 | `run_phase3a_meta_reason` — Anthropic Opus call, picks ≤5 capabilities | `cortex_phase_outputs` (1, artifact_type='meta_reason') | 5-15s | ~$0.005-0.015 |
| 3b specialist invocations | 4 | `run_phase3b_invocations` — N parallel capability runs (cap-5) | `cortex_phase_outputs` (1, artifact_type='specialist_invocations') + N capability_runs rows | 10-30s | ~$0.01-0.05 per cap, total $0.02-0.20 |
| 3c synthesis | 5 | `run_phase3c_synthesize` — Anthropic Opus call → `proposal_text` + `structured_actions`; status flips to `proposed` | `cortex_phase_outputs` (1, artifact_type='synthesis') + `cortex_cycles` (1 UPDATE status='proposed') | 8-15s | ~$0.005-0.015 |
| 4 propose | 7 | `_phase4_propose` → `run_phase4_propose` — builds Block Kit blocks + INSERTs proposal_card artifact + UPDATEs cycle to `tier_b_pending`. **Under DRY_RUN: skips `chat_postMessage` + INSERTs `dry_run_marker` artifact at phase_order=8.** | `cortex_phase_outputs` (1 proposal_card + 1 dry_run_marker) + `cortex_cycles` (1 UPDATE status='tier_b_pending') | <500ms | $0 |
| 6 archive | (skipped on Phase 4 success — Phase 5 owns archive) | n/a in DRY_RUN observation window | n/a | n/a | $0 |

**Total DRY_RUN cycle budget:** ~25-65s wall-clock; **~$0.03-0.25 per cycle** (driven by specialist count + per-cap input length).

**Hard timeout:** 300s (`CORTEX_CYCLE_TIMEOUT_SECONDS`). Cycle that times out goes to `status='failed'` via best-effort UPDATE in `maybe_run_cycle`'s except block.

### 2.4 Expected log lines (sentinel.cortex_*)

Per phase, look for these stdout signatures from the Render `baker-master` log stream:

```
Phase 1:    "Cortex cycle <UUID> Phase 1 sense persisted"
Phase 2:    "Cortex cycle <UUID> Phase 2 loaded N curated files"   (N = file count)
Phase 3a:   "Cortex Phase 3a: capabilities_to_invoke=[…]"
Phase 3b:   "Cortex Phase 3b: invoked N capabilities (cost_tokens=…)"
Phase 3c:   "Cortex Phase 3c: synthesis cost_tokens=… cost_dollars=…"
Phase 4:    "[CORTEX_DRY_RUN] Would post Slack card for cycle <UUID> matter=oskolkov (N gold entries, M structured actions) — skipping"
            (this exact prefix `[CORTEX_DRY_RUN]` is the canary that DRY_RUN is honored — see cortex_phase4_proposal.py:104)
Archive:    (none — Phase 5 button-press would archive; for DRY_RUN observation we leave the cycle at tier_b_pending)
```

If the Phase 4 line does NOT include `[CORTEX_DRY_RUN]` prefix → DRY_RUN flag did NOT propagate; **STOP** (see §4.3).

---

## 3. Validation queries (run after each cycle)

Replace `<CYCLE_ID>` with the UUID returned in §2.1 print statement.

### 3.1 Cycle row final state

```sql
SELECT cycle_id, matter_slug, triggered_by,
       current_phase, status,
       proposal_id, director_action,
       cost_tokens, cost_dollars,
       started_at, completed_at,
       (completed_at - started_at)::interval AS wall_clock
FROM cortex_cycles
WHERE cycle_id = '<CYCLE_ID>'::uuid;
```

**Expected for clean DRY_RUN cycle:**
- `current_phase` = `'propose'`
- `status` = `'tier_b_pending'`
- `proposal_id` IS NOT NULL (UUID set by Phase 4)
- `director_action` IS NULL (no button pressed yet)
- `cost_tokens` between 5,000–50,000
- `cost_dollars` between 0.03–0.25
- `completed_at` IS NULL (Phase 5 owns archive on the button-press path; cycle is intentionally pending)
- `wall_clock` IS NULL (uses `completed_at`)

### 3.2 Per-phase artifact presence

```sql
SELECT phase, phase_order, artifact_type,
       jsonb_typeof(payload) AS payload_kind,
       length(payload::text) AS payload_size_bytes,
       created_at
FROM cortex_phase_outputs
WHERE cycle_id = '<CYCLE_ID>'::uuid
ORDER BY phase_order, created_at;
```

**Expected rows for clean DRY_RUN cycle (in order):**

| phase | phase_order | artifact_type |
|---|---|---|
| sense | 1 | cycle_init |
| load | 2 | phase2_context |
| reason | 3 | meta_reason |
| reason | 4 | specialist_invocations |
| reason | 5 | synthesis |
| propose | 7 | proposal_card |
| propose | 8 | **dry_run_marker** ← canary; absent → DRY_RUN was NOT honored |

If the `dry_run_marker` row at phase_order=8 is missing **STOP** (§4.3).

### 3.3 Cost accumulation sanity

```sql
SELECT matter_slug,
       count(*) AS cycles_today,
       sum(cost_tokens) AS total_tokens,
       sum(cost_dollars) AS total_dollars_eur_equiv,
       avg(cost_dollars)::numeric(10,4) AS avg_per_cycle
FROM cortex_cycles
WHERE matter_slug = 'oskolkov'
  AND started_at >= CURRENT_DATE
GROUP BY matter_slug;
```

**Hard ceiling for DRY_RUN week:** ≤ €0.50 per cycle, ≤ €5 per day. Above either → **STOP** + investigate prompt size in `cortex_phase3_synthesizer.py` (likely a context-window inflation bug).

### 3.4 Final terminal status confirmation (after Director button press, post-DRY_RUN)

In DRY_RUN we do **not** drive the cycle to `archive` automatically — Phase 4 success means cycle sits at `tier_b_pending`. To complete a single cycle end-to-end during DRY_RUN, Director can simulate a button press by hitting the action endpoint:

```bash
# DRY_RUN approval simulation (no Slack post happened, so Director acts directly):
curl -s -X POST "https://baker-master.onrender.com/cortex/cycle/<CYCLE_ID>/action" \
  -H "X-Baker-Key: $BAKER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"action":"approve","selected_gold_files":[]}' | jq
```

**Expected response:** `{"status":"ok","action":"approve","result":{"status":"dry_run_approved",...}}`

Verify final state:
```sql
SELECT cycle_id, status, director_action, current_phase, completed_at
FROM cortex_cycles
WHERE cycle_id = '<CYCLE_ID>'::uuid;
-- Expected: status='approved', director_action='gold_approved',
--           current_phase='archive', completed_at=NOW()-ish
```

```sql
SELECT phase, phase_order, artifact_type
FROM cortex_phase_outputs
WHERE cycle_id = '<CYCLE_ID>'::uuid
  AND phase_order >= 9
ORDER BY phase_order;
-- Expected: (archive, 10, final_archive)
```

### 3.5 Bridge wire-up (Amendment A2) sanity — when CORTEX_PIPELINE_ENABLED is later flipped on

```sql
-- Verify post-commit dispatch is firing for newly bridged signals:
SELECT s.id AS signal_id, s.matter, s.created_at AS bridged_at,
       c.cycle_id, c.started_at AS cycle_started, c.status
FROM signal_queue s
LEFT JOIN cortex_cycles c ON c.trigger_signal_id = s.id
WHERE s.created_at >= NOW() - INTERVAL '15 minutes'
  AND s.matter = 'oskolkov'
ORDER BY s.created_at DESC
LIMIT 10;
-- After flag flip: every recent oskolkov signal should have a paired cycle row
-- (within ~5s of bridged_at). Missing pairs → maybe_dispatch did not fire.
```

### 3.6 Drift audit job registered

```sql
-- After deploy, the matter_config_drift_weekly job must appear in
-- scheduler_executions on each Monday 11:00 UTC firing.
SELECT job_id, fired_at, status
FROM scheduler_executions
WHERE job_id = 'matter_config_drift_weekly'
ORDER BY fired_at DESC LIMIT 5;
-- For the first DRY_RUN week the job may not have fired yet (depends on
-- when the Monday lands relative to launch). The scheduler-level smoke
-- check is /api/health/scheduler in §1.4.
```

---

## 4. Monitoring during the first cycle

### 4.1 Render logs to tail

```bash
# Stream the live log; filter for cortex sentinel logs (canonical logger name):
RENDER_API_KEY=$(op read 'op://Private/Render API Key/credential')
SERVICE_ID=srv-d6dgsbctgctc73f55730
curl -N -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/$SERVICE_ID/logs?direction=forward&type=app" \
  | grep -E "cortex_runner|cortex_phase|cortex_phase4|cortex_phase5|alerts_to_signal|CORTEX_DRY_RUN"
```

Or via the Render UI: **Dashboard → baker-master → Logs**, filter `cortex` in the search box.

### 4.2 Slack channel — clarification

**Under DRY_RUN, Phase 4 does NOT post the Slack card.** The line in the Render log:

```
[CORTEX_DRY_RUN] Would post Slack card for cycle <UUID> matter=oskolkov (N gold entries, M structured actions) — skipping
```

is the canonical signal that the proposal **would have been** posted. Do NOT watch the Director DM (D0AFY28N030) for cycle 1 — there will be no message. Watch the Render log for the `[CORTEX_DRY_RUN]` line instead.

After flipping `CORTEX_DRY_RUN=false` (post-promotion §6), the Director DM **will** receive a Block Kit card with 4 buttons. Subsequent button-presses route through `POST /cortex/cycle/{id}/action`.

### 4.3 STOP criteria — failure modes that should halt the cycle

Stop the launch (no further cycles fired; rollback gate held open) on any of:

| # | Trigger | Detection | Stop action |
|---|---|---|---|
| F1 | Phase 4 log line missing `[CORTEX_DRY_RUN]` prefix | Render log search returns the "Would post" line **without** the bracketed prefix | Re-check env vars (§1.4); the flag did not propagate. Halt before next cycle. |
| F2 | `dry_run_marker` artifact absent at phase_order=8 | §3.2 query missing the row | Same — DRY_RUN gate failed. Halt. |
| F3 | Real Slack post arrives in Director DM | Director sees a Block Kit card during DRY_RUN | DRY_RUN flag was not honored — set `CORTEX_DRY_RUN=true` again, redeploy, do NOT continue. |
| F4 | `cost_dollars` > €0.50 for the cycle | §3.3 query result | Specialist-prompt size regression — halt and inspect `cortex_phase3_synthesizer.py` context build. |
| F5 | Wall-clock > 60s for an unattended cycle (or the 300s timeout fires) | Render log shows `Cortex cycle timed out after 300s` | One specialist or vault read is hung — halt and inspect Phase 2/3b. |
| F6 | Cycle row stuck at `current_phase='reason'` and `status='in_flight'` >5min | §3.1 query returns this combination | Phase 3 internal failure handling didn't fire. Halt. |
| F7 | `_phase6_archive` log shows itself failing (`Phase 6 archive itself failed for cycle …`) | Render log search | Archive is the safety net; if it fails the cycle row will be inconsistent. Halt and inspect. |
| F8 | `kbl/bridge/alerts_to_signal.py` errors increase post-deploy | `SELECT errors FROM trigger_watermarks WHERE source='alerts_to_signal_bridge'` (or scheduler_executions for `alerts_to_signal_bridge_tick`) | Amendment A2 dispatch has a regression. Halt. Specifically check that `CORTEX_PIPELINE_ENABLED=false` (DRY_RUN should have kept dispatch dormant). |
| F9 | Phase 5 endpoint returns 5xx on `approve`/`edit`/`refresh`/`reject` | Manual curl in §3.4 returns non-200 | Endpoint regression. Halt. |

**Stop action when triggered:** flip `CORTEX_LIVE_PIPELINE=false` (halts new cycles) before further investigation. Full rollback (§5) is reserved for cases where the legacy `ao_signal_detector` decommission has already happened — in DRY_RUN it has NOT, so the F-criteria above only require flag flips, not table renames.

```bash
# Soft stop (DRY_RUN era — pre-decommission):
curl -fsS -X PATCH "https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730/env-vars" \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '[{"key":"CORTEX_LIVE_PIPELINE","value":"false"}]'
curl -fsS -X POST "https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730/deploys" \
  -H "Authorization: Bearer $RENDER_API_KEY"
```

---

## 5. Rollback drill — `scripts/cortex_rollback_v1.sh`

### 5.1 When to fire the script

The full rollback script is reserved for the **post-decommission** phase (Steps 34-35, AFTER DRY_RUN promotion). During DRY_RUN itself:

- F1–F7 above → flag flip is sufficient (the legacy path is untouched).
- F8 (Amendment A2 bridge regression) → flag flip + commit revert if the regression is in code.

The rollback **script** becomes the right tool only when `ao_signal_detector` is `disabled=true` AND `ao_project_state` has been frozen and renamed. Until those two operations happen in production, the script is a documentation + drill artifact.

### 5.2 Pre-launch dry rehearsal of the rollback script (mandatory)

Before the first DRY_RUN cycle, walk through the script against a stub env to confirm the runbook works:

```bash
# 1. Verify the file exists post-PR-#74-merge, is executable, and parses cleanly:
ls -l ~/bm-b3/scripts/cortex_rollback_v1.sh
bash -n ~/bm-b3/scripts/cortex_rollback_v1.sh

# 2. Run without `confirm` — must print usage and exit 1:
bash ~/bm-b3/scripts/cortex_rollback_v1.sh
# Expected: usage banner; exit code 1.

# 3. Verify `op://` paths resolve in Director's actual 1Password vault:
op read 'op://Private/Render API Key/credential' | head -c 8 ; echo
op read 'op://Private/Baker DB URL/credential' | head -c 12 ; echo
# If either fails → fix the path BEFORE the live decommission step. The script's
# # TODO comment at line 47 calls this out explicitly.

# 4. (Optional) sandbox-fire against a non-prod Render service to confirm the
# PATCH + redeploy + Slack DM path works end-to-end without touching production.
```

### 5.3 Live execution (post-decommission only)

```bash
# All four conditions must hold before this is run:
# (a) Step 34 — ao_signal_detector disabled
# (b) Step 35 — ao_project_state frozen as ao_project_state_legacy_frozen_<date>
# (c) DRY_RUN promotion criteria met (see §6)
# (d) Director gives explicit fire authorization

bash ~/bm-b3/scripts/cortex_rollback_v1.sh confirm
```

**What it does (in order, with timestamps):**

1. ISO timestamp: START
2. Render PATCH env vars: `AO_SIGNAL_DETECTOR_ENABLED=true`, `CORTEX_LIVE_PIPELINE=false`, `CORTEX_PIPELINE_ENABLED=false`
3. ISO timestamp: env vars updated
4. Postgres: rename most-recent `ao_project_state_legacy_frozen_*` back to `ao_project_state`
5. Render redeploy
6. ISO timestamp: redeploy triggered
7. Slack DM Director: "⚠️ Cortex V1 rollback executed — verify within 5 min."
8. ISO timestamp: DONE

<5 min RTO target. The script is `set -euo pipefail` — first failure halts; partial states are recoverable manually.

### 5.4 Verification post-rollback

```bash
# (a) Confirm legacy detector firing again:
curl -s "https://baker-master.onrender.com/api/health/scheduler" \
  -H "X-Baker-Key: $BAKER_API_KEY" \
  | jq '.jobs[] | select(.id == "ao_signal_detector")'
# Expected: row present, next_run_time near future.
```

```sql
-- (b) Confirm ao_project_state table restored:
SELECT count(*) FROM ao_project_state;
-- Expected: non-zero pre-decommission row count.

-- (c) Confirm no new cortex cycles being created:
SELECT max(started_at) FROM cortex_cycles;
-- Expected: max(started_at) = pre-rollback timestamp; nothing newer.
```

```bash
# (d) Confirm Director received Slack DM at D0AFY28N030.
```

---

## 6. Promotion criteria — DRY_RUN passes when

DRY_RUN observation period: **1 week** (Mon–Sun) of normal Director activity on AO matter, with manually-triggered cycles spaced approximately every 2-3 days.

### 6.1 Quantitative gates (all must hold)

| # | Gate | Target | Source |
|---|---|---|---|
| G1 | Consecutive clean cycles | **N ≥ 5** consecutive cycles complete to `tier_b_pending` (or `approved` after manual button press) without F1–F9 firing | `cortex_cycles` query §3.1 |
| G2 | Phase 6 archive failures | **0** instances of `Phase 6 archive itself failed for cycle …` in Render logs over the observation week | Render log grep |
| G3 | Per-cycle cost ceiling | **≤ €0.50** average across the N cycles, **≤ €1.00** worst case | §3.3 query |
| G4 | Per-cycle wall-clock | p95 **≤ 60s**; p99 **≤ 120s**; no 300s timeouts | computed from `cortex_cycles.completed_at - started_at` |
| G5 | DRY_RUN canary present | `dry_run_marker` artifact at phase_order=8 in **every** cycle's `cortex_phase_outputs` | §3.2 query for each cycle |
| G6 | Endpoint round-trip | Manual `POST /cortex/cycle/{id}/action` for each of the 4 actions (approve / edit / refresh / reject) returns 200 + matches expected handler result shape | §3.4 + curl tests for the other 3 actions |
| G7 | Drift audit fires Monday | One row in `scheduler_executions` for `job_id='matter_config_drift_weekly'` with `status='executed'` for the observation Monday | §3.6 query |

### 6.2 Qualitative gates

| # | Gate | Description |
|---|---|---|
| Q1 | Director ACK on first proposed card | Even though DRY_RUN skips the Slack post, the Director must read the **content of the proposal_card payload** (§3.2 returns the JSON) for cycle 1 and confirm in writing that the proposal_text + structured_actions + proposed_gold_entries are sensible. This is the substitute for "Director clicked the button" during DRY_RUN. |
| Q2 | No Gold-write surprise | `kbl.gold_proposer.propose` writes go to `wiki/matters/oskolkov/proposed-gold.md` — confirm under the `## Proposed Gold (agent-drafted)` section ONLY, never to a ratified Gold path. (DRY_RUN approve skips Gold writes; this gate becomes meaningful post-flip.) |
| Q3 | No bridge regression | `alerts_to_signal_bridge` `bridged` count over the observation week within ±20% of the prior 4-week baseline. Amendment A2 wired in 1C must not have changed the bridge tick's keep-rate. |
| Q4 | Rollback drill PASS | §5.2 walked end-to-end at least once before live promotion; both `op://` paths verified by Director. |

### 6.3 Promotion sequence (when all gates clear)

```bash
# Step 1 — flip DRY_RUN off (cycles now post Slack cards + execute Phase 5 fully):
curl -s -X POST "https://baker-master.onrender.com/mcp?key=$BAKER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_render_env_merge","arguments":{"service_id":"srv-d6dgsbctgctc73f55730","updates":{"CORTEX_DRY_RUN":"false"}}}}'

# Step 2 — redeploy:
curl -fsS -X POST "https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730/deploys" \
  -H "Authorization: Bearer $RENDER_API_KEY"

# Step 3 — fire one manual cycle and verify Director DM receives the Block Kit card.
# Verify SLACK_BOT_TOKEN delivered the post:
#   `Director DM D0AFY28N030 → "Cortex proposal — oskolkov"` header appears.

# Step 4 — flip CORTEX_PIPELINE_ENABLED on so incoming bridged signals
# auto-trigger cycles (Amendment A2 hot path):
curl -s -X POST "https://baker-master.onrender.com/mcp?key=$BAKER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_render_env_merge","arguments":{"service_id":"srv-d6dgsbctgctc73f55730","updates":{"CORTEX_PIPELINE_ENABLED":"true"}}}}'

# Step 5 — redeploy + observe; rollback script remains the safety net for the
# decommission-era F-criteria (F8 specifically). Steps 34-35 (legacy detector
# disable + ao_project_state freeze) are deliberately separate Director-consult
# changes and NOT part of this promotion sequence.
```

### 6.4 Post-promotion observation

After `CORTEX_DRY_RUN=false` + `CORTEX_PIPELINE_ENABLED=true` go live:

- Watch the first 10 auto-triggered cycles in Render logs.
- Verify each one's Phase 4 line is now `cortex_phase4 Slack post ok` (or equivalent — the `[CORTEX_DRY_RUN]` prefix should be **gone**).
- §3.5 query (bridge wire-up sanity) must show every recent `oskolkov` signal pairing with a cycle row within ~5s.

If any of the post-promotion cycles fails F1–F9: flip `CORTEX_LIVE_PIPELINE=false` immediately (single env PATCH, no script needed). Investigate. Re-promote only after fix.

---

## Appendix A — Reference table of artifact types written by V1

| phase | phase_order | artifact_type | Where written |
|---|---|---|---|
| sense | 1 | cycle_init | `cortex_runner._phase1_sense` |
| load | 2 | phase2_context | `cortex_runner._phase2_load` |
| reason | 3 | meta_reason | `cortex_phase3_reasoner.run_phase3a_meta_reason` |
| reason | 4 | specialist_invocations | `cortex_phase3_invoker.run_phase3b_invocations` |
| reason | 5 | synthesis | `cortex_phase3_synthesizer.run_phase3c_synthesize` |
| propose | 7 | proposal_card | `cortex_phase4_proposal._persist_phase4` |
| propose | 8 | dry_run_marker | `cortex_phase4_proposal._mark_dry_run` (DRY_RUN only) |
| propose | 9 | director_edit | `cortex_phase5_act.cortex_edit` (only on Edit button) |
| archive | 10 | final_archive | `cortex_phase5_act._archive_cycle` (post button-press) OR `cortex_runner._phase6_archive` (failure path) |

## Appendix B — Cycle status state machine

```
                  ┌─────────────────────────────────────────────┐
                  │                                             ▼
in_flight ──> proposed ──> tier_b_pending ──> {approved,rejected,modified}
   │              │              │                        │
   │              ▼              │                        ▼
   └─────────> failed ◀──────────┘                     archive (terminal)
                  │
                  ▼
              archive (terminal)
```

- `in_flight` → set in `_phase1_sense`
- `proposed` → set after `Phase 3c` synthesis success
- `tier_b_pending` → set inside `_phase4_propose` (and DB UPDATE in `_persist_phase4`)
- `approved` / `rejected` / `modified` → set by `_archive_cycle` from Phase 5 handlers
- `failed` → set on any phase exception; Phase 6 archive runs via the `finally` branch

## Appendix C — Files touched by V1

| Layer | File | Sub-brief |
|---|---|---|
| Migrations | `migrations/20260428_cortex_cycles.sql` | 1A |
| Migrations | `migrations/20260428_cortex_phase_outputs.sql` | 1A |
| Runner | `orchestrator/cortex_runner.py` | 1A + 1B + 1C |
| Phase 2 loader | `orchestrator/cortex_phase2_loaders.py` | 1A |
| Phase 3a | `orchestrator/cortex_phase3_reasoner.py` | 1B |
| Phase 3b | `orchestrator/cortex_phase3_invoker.py` | 1B |
| Phase 3c | `orchestrator/cortex_phase3_synthesizer.py` | 1B |
| Phase 4 | `orchestrator/cortex_phase4_proposal.py` | 1C |
| Phase 5 | `orchestrator/cortex_phase5_act.py` | 1C |
| Drift audit | `orchestrator/cortex_drift_audit.py` | 1C |
| Endpoint | `outputs/dashboard.py` (`POST /cortex/cycle/{id}/action`) | 1C |
| Bridge wire | `kbl/bridge/alerts_to_signal.py` (Amendment A2) | 1C |
| Pipeline | `triggers/cortex_pipeline.py` (`maybe_dispatch` + `maybe_trigger_cortex`) | 1A + 1C |
| Scheduler | `triggers/embedded_scheduler.py` (drift weekly job) | 1C |
| Rollback | `scripts/cortex_rollback_v1.sh` | 1C |

---

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
