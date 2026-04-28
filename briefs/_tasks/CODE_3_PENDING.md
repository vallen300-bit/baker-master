---
status: OPEN
brief: rollback_dry_rehearsal
trigger_class: LOW
dispatched_at: 2026-04-28T16:00:00Z
dispatched_by: ai-head-a
target_script: scripts/cortex_rollback_v1.sh
prerequisite_pr: 75
prerequisite_state: MERGED 2026-04-28T~15:55Z (squash 1ec079b)
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: null
autopoll_eligible: false
---

# CODE_3_PENDING — B3: PRE-LAUNCH ROLLBACK DRY REHEARSAL — 2026-04-28

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b3`
**Plan §:** [`briefs/_plans/CORTEX_V1_DRY_RUN_LAUNCH_PLAN_20260428.md`](../_plans/CORTEX_V1_DRY_RUN_LAUNCH_PLAN_20260428.md) §5.2
**Trigger class:** LOW (operational verification — no diff, no merge gate)

## §2 pre-dispatch busy-check (AI Head A verified)

- **B3 prior state:** COMPLETE — PR #75 second-pair review APPROVE shipped (`0749697` + `2d87838`). PR #75 merged `1ec079b`. IDLE.
- **Other B-codes:** B1 IDLE; B2 (App) IDLE.
- **Lesson #50 review-in-flight pre-check:** N/A (verification, not review).

## What you're doing

Walk b3's own §5.2 mandatory pre-launch dry rehearsal of `scripts/cortex_rollback_v1.sh` end-to-end. Gate before DRY_RUN promotion criteria can run live (per §6 Q4: "rollback drill PASS = §5.2 walked end-to-end at least once").

Self-review acceptable: you wrote the plan and the script — you verify the runbook. AI Head A reviews the ship report.

## Steps (literal, paste output verbatim into ship report)

```bash
cd ~/bm-b3
git checkout main
git pull -q

# Step 1 — file present, executable, parses cleanly
ls -l scripts/cortex_rollback_v1.sh
bash -n scripts/cortex_rollback_v1.sh
echo "exit=$?"

# Step 2 — invoked without `confirm` must print usage banner and exit 1
bash scripts/cortex_rollback_v1.sh
echo "exit=$?"
```

**Step 3 — `op://` path verification (NEEDS DIRECTOR):**
You cannot run `op` against Director's 1Password vault. Surface the exact two commands Director must paste in his own terminal:

```bash
op read 'op://Private/Render API Key/credential' | head -c 8 ; echo
op read 'op://Private/Baker DB URL/credential' | head -c 12 ; echo
```

In your ship report, list both commands under a "Director to verify" callout. AI Head A will relay to Director and capture the result back in the report.

**Step 4 — sandbox-fire (optional):** Your judgment call. If you have a non-prod Render service slot to safely fire against, do it and paste output. If not, write "deferred — no non-prod target available; live execution is gated behind Director auth + 4 hard preconditions per plan §5.3".

## Pass criteria

- Step 1: file mode includes `x`, `bash -n` exit 0
- Step 2: usage banner prints, exit 1
- Step 3: 2 `op read` commands surfaced cleanly for Director (block at end of report)
- Step 4: explicit decision documented (fired / deferred with reason)

## Output

Ship report: `briefs/_reports/B3_rollback_dry_rehearsal_20260428.md`

Format:
```markdown
# B3 — Cortex V1 rollback script dry rehearsal — 2026-04-28

## Step 1 — file/parse verification
<literal stdout>

## Step 2 — usage-banner check
<literal stdout>

## Step 3 — Director op:// verification (NEEDS DIRECTOR)
<exact 2 commands + brief explanation of expected output>

## Step 4 — sandbox-fire decision
<fired+output OR deferred+reason>

## Verdict
PASS / FAIL / PARTIAL — and what's blocking promotion gate Q4 if not PASS.
```

Then notify A in chat with verdict line + one-line summary. A relays Step 3 to Director and folds the response back into the report.

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
