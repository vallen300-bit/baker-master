---
status: COMPLETE
brief: briefs/BRIEF_CORTEX_PHASE6_VAULT_RECONCILER_1.md
trigger_class: MEDIUM
dispatched_at: 2026-05-01T10:05:00Z
dispatched_by: ai-head-a
claimed_at: 2026-05-01T10:10:00Z
claimed_by: b4
last_heartbeat: 2026-05-01T11:30:00Z
completed_at: 2026-05-01T11:30:00Z
pr: https://github.com/vallen300-bit/baker-master/pull/144
ship_report: briefs/_reports/B4_cortex_phase6_vault_reconciler_1_20260501.md
blocker_question: null
autopoll_eligible: false
---

# CODE_4 — DISPATCH (CORTEX_PHASE6_VAULT_RECONCILER_1)

**Status:** COMPLETE — 2026-05-01T11:30Z by B4. PR [#144](https://github.com/vallen300-bit/baker-master/pull/144) opened on `b4/cortex-phase6-vault-reconciler-1`. Ship report: `briefs/_reports/B4_cortex_phase6_vault_reconciler_1_20260501.md`. Tier B autonomous merge pending AI Head A green check.

**Original status:** OPEN — 2026-05-01T10:05Z by AI Head A (Director-cleared 2026-05-01; B4 reserved for AI Head A)
**Brief:** `briefs/BRIEF_CORTEX_PHASE6_VAULT_RECONCILER_1.md` (~2-3h, MEDIUM, Tier B)
**Builder:** B4 (freshest Reflector context — surfaced the gap in CODE_4_PENDING handover §S2)
**Branch (cut from latest main):** `b4/cortex-phase6-vault-reconciler-1`
**Tier:** **Tier B** — autonomous merge on green per `_ops/processes/ai-head-autonomy-charter.md` §3
**autopoll_eligible:** false — paste-block dispatch; cold-start required

## Why this exists

Brief 3 (Reflector) shipped with an inherent gap (B4 surfaced it):
counter-increment + idempotency-marker INSERT happens in one txn, but the
vault write to `proposed-config-deltas.md` happens AFTER commit, in a
try/except that only logs. If the vault write throws (FS permissions, disk
full, mac-mini sync glitch), the cycle "looks complete" in PG but Director's
per-matter vault surface is silently missing. Subsequent sweeps then skip
because the marker is present.

This brief builds the cheap reconciler: read markers, check vault file
presence + cycle block, re-emit when missing. Pure vault-write replay; NO
counter touches; same-substring idempotency for race window.

## Task summary

Build `orchestrator/cortex_phase6_reconciler.py` (single-file module +
APScheduler wiring + tests). Brief has full spec including:
- File-by-file scope with line citations
- Pre-check / enumeration / re-emit logic
- Idempotency strategy (same-substring header match)
- Audit row format (action_type='cortex_reflector_reconcile')
- APScheduler wiring point in `triggers/embedded_scheduler.py:841`
  (immediately before BRIEF_MOVIE_AM_RETROFIT_1 D5 comment at line 842)
- V1 explicit drops (no counter rollback, no ClickUp reconciliation,
  no alerting threshold, no missing-marker backstop, no metrics dashboard)

Read the full brief before starting — the scheduler insertion point in
particular has a clarifying note about NOT inserting inside the existing
else-branch (the brief was self-audited + updated to call this out).

## Pre-flight checks

```bash
cd ~/bm-b4
git fetch origin
git status -sb                      # confirm clean working tree
git checkout main && git pull --ff-only origin main
gh pr list --state open --limit 20  # Lesson #54 precheck
git checkout -b b4/cortex-phase6-vault-reconciler-1
```

Expected: clean tree; PR list shows zero conflicting open PRs (the only
open PR pre-dispatch was B5's BRISEN_LAB_1 staging — separate repo, no
overlap).

## Dispatch steps

```bash
# Read brief in full (~250+ lines — complete spec)
cat briefs/BRIEF_CORTEX_PHASE6_VAULT_RECONCILER_1.md

# Implement per brief §Solution + §Implementation
# Key files:
#   orchestrator/cortex_phase6_reconciler.py (NEW)
#   triggers/embedded_scheduler.py (MOD — APScheduler job at line 841)
#   tests/test_cortex_phase6_reconciler.py (NEW)

# Quality checkpoints (brief §Quality Checkpoints + repo defaults):
pytest tests/test_cortex_phase6_reconciler.py -v
python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase6_reconciler.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"
bash scripts/check_singletons.sh

# Push + open PR
git push -u origin b4/cortex-phase6-vault-reconciler-1
gh pr create --title "feat(cortex): Phase 6 vault reconciler — drift detector for vault-write-outside-counter-txn (CORTEX_PHASE6_VAULT_RECONCILER_1)" \
  --body "<see brief §PR template>"
```

## Acceptance criteria

- New module `orchestrator/cortex_phase6_reconciler.py` per brief §Solution
- APScheduler job wired at `triggers/embedded_scheduler.py:841` (before line 842 comment)
- Tests cover: missing file → re-emit; present file with cycle block → no-op;
  present file without cycle block → re-emit; race-window idempotency
- `bash scripts/check_singletons.sh` green
- 200-row LIMIT per run respected (brief §Solution step 1)
- `baker_actions` audit row format matches brief §Audit
- PR opened with brief link in body
- Tier B — autonomous merge on green

## Hot rules to respect

- **Migrations are immutable.** Don't edit any existing migration file even
  if you need a comment update — write a new migration file instead. See
  `feedback_migration_file_immutability.md` (incident on this same date —
  PR #127 broke deploys via comment edit on PR #125's applied migration).
- **No raw `SentinelRetriever()` / `SentinelStoreBack()` instantiation** —
  use `_get_global_instance()`. CI guard catches this.
- **PostgreSQL: `conn.rollback()` in except blocks before any new query.**
- **All DB/API calls wrapped in try/except** — fault-tolerant or it doesn't ship.

## On completion

1. Open PR; AI Head A reviews + merges Tier B autonomous on green.
2. Update this mailbox to `status: COMPLETE` with PR link + ship-report path.
3. Ship report at `briefs/_reports/B4_cortex_phase6_vault_reconciler_1_<date>.md`.

## Companion context

- Briefs 1+2 SHIPPED today. Vault read+write live; 31 MCP tools.
- PR #142 (architect-nit followup) merged + deploying — completes #141
  feedback loop.
- Migration drift was caught + fixed today; lesson captured. Don't reopen.
- PR #135 (this brief itself) merged 2026-04-30; brief sits on main.
- B3 just freed up post-#142 ship; B4 has the Reflector context per CODE_4
  prior handover. Both could build this; B4 chosen for context affinity.
