# BRIEF_AH1_AUTO_ROLLOVER_WIRING_1

**Dispatched by:** deputy (AH2) · **Target:** b3 · **Date:** 2026-07-04
**Harness-V2:** small-fix / infra-config. **Task class:** infra-config (picker + vault only; NO baker-master prod code). **Done-state class:** picker-wired + vault-committed + dry-run-verified (no prod deploy → POST_DEPLOY_AC N/A, security-review N/A). Ship report must answer the Acceptance criteria below.

## Context
Director wants lead (AH1) to auto **stop + respawn** when his context approaches the window limit — "restart himself" so he never runs on a bloated context. **Context Contract:**
- **Already built:** `context-threshold-check.sh` (Stop hook, tested + live in the deputy picker `bm-aihead2/.claude/hooks/`) reads `rollover_window_tokens` from settings.json and fires a soft reminder at ~70% of the window, a hard `decision:block` instruction at ~85%. Checkpoint-respawn V1 protocol at `~/baker-vault/_ops/processes/worker-checkpoint-respawn.md` (workers today). Lead's picker already has `rollover_window_tokens: 1000000`.
- **Director-ratified thresholds:** keep **70% soft / 85% hard** (script default). Do **NOT** set 50% — lead holds live multi-PR arcs; flat 50% doubles restart frequency and fragments live work. Soft band = roll at next arc boundary; 85% hard floor forces it only if still mid-run.

## Problem
Lead's picker has **no Stop hook wired** — `Stop hooks: NONE` in both `~/bm-aihead1/.claude/settings.json` and the Dropbox picker `~/Vallen Dropbox/Dimitry vallen/bm-aihead1/.claude/settings.json`. So the threshold never fires for lead and he cannot auto-checkpoint/respawn. Lead-side rollover was deliberately deferred as V2 in the original design; this brief ships it.

## Files to touch
1. `~/bm-aihead1/.claude/hooks/context-threshold-check.sh` — copy from `bm-aihead2/.claude/hooks/context-threshold-check.sh` if absent. First check whether the Dropbox picker path symlinks to `~/bm-aihead1` (as role-context files do); if symlinked, one copy covers both — report which.
2. `~/bm-aihead1/.claude/settings.json` (+ Dropbox picker copy if not symlinked) — add the `Stop` block mirroring deputy's: `context-threshold-check.sh`, timeout 10. JSON-validate after.
3. `~/baker-vault/_ops/agents/aihead1/orientation.md` — add a `## Rollover (auto stop + respawn)` block: at 70% finish the current arc then roll; at 85% checkpoint NOW. Lead's checkpoint = his existing `pin` close artifact (PINNED §A + paired handover) — reuse it, do not invent a new schema. Then bus-post `kind=respawn-request` topic `rollover/respawn`; wake daemon spawns the successor; successor drains bus → reads PINNED §A + latest handover → resumes. Reference the worker process doc. Path-scoped commit — do NOT touch lead's PINNED.md or baker-os-v2 files (both have live uncommitted edits).

## Verification
- Dry-run: feed the hook a synthetic Stop payload with ~720k then ~860k token transcript vs the 1M window → soft reminder fires at the first, hard-block at the second. Paste both JSON outputs.
- Confirm wake-handler `isAliasLive` + spawn covers the `lead` slug (per 2026-06-22 wake arc); no change expected — state the confirmation.
- JSON-validate both settings.json edits.

## Acceptance criteria
- [ ] `context-threshold-check.sh` present in lead's picker hooks (state paths / symlink resolution).
- [ ] Stop hook wired in lead's settings.json (both locations or symlink-covered); JSON valid.
- [ ] Dry-run soft (70%) + hard (85%) outputs pasted.
- [ ] `## Rollover` block committed to lead's orientation.md (vault main, path-scoped; PINNED.md + baker-os-v2 untouched).
- [ ] Respawn-request convention + poison-loop guard documented: successor increments `attempt`; at `attempt ≥ 3` it does NOT resume — escalates to Director + deputy with checkpoint + last error as prose (worker doc F4).
- [ ] Thresholds stay 70/85 (NOT 50%). No forced live lead respawn in test.
- **Gate plan:** G0 self-test (synthetic payload, both bands) → G1 deputy cross-lane review on return → no prod merge → lead approves the picker flip before it's active.
