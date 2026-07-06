# BRIEF: BAKER_OS_V2_C1_PICKER_FOLDER_WIRING_1 — picker folders visible without hand-linking

dispatched_by: lead
reply_to: lead (bus topic `baker-os-v2/c1-picker-folder-wiring`)
Harness-V2: task class = small feature (install tooling) · Context Contract below · done rubric §Verification · gate plan: codex bus review (reasoning_effort=medium) → lead merge. POST_DEPLOY_AC_VERDICT: N/A — local install tooling, no Render deploy.

## Context
ClickUp C1 (86cakdynn), Baker OS V2 rollout. During the cowork-bb-desk install, the new picker folder was invisible to the Director's Cowork app picker until hand-linked, and the generated identity snapshot path fell back to the generic `/Users/dimitry/baker-vault`. Fleet rollout (D6) will install 4+ more desks — this must be scripted, not remembered. Roadmap §3 C1.

**Repo:** baker-master (this repo, your clone).

## Estimated time: ~2.5h · Complexity: Low-Medium · Prerequisites: none

## Current state (verified 2026-07-06)
- `scripts/generate_agent_identity_artifacts.py:108-122` `_snapshot_path_for()` — hardcoded per-agent map; unknown slugs fall back to `/Users/dimitry/baker-vault` (line 121). `cowork-bb-desk` is NOT in the map ⇒ wrong snapshot path in `scripts/agent_identity_generated.sh` (`cowork-bb-desk:/Users/dimitry/baker-vault`).
- Install SOP (`baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` AC1, lines 33-34) — picker dir creation is a MANUAL step; no script; symlink pattern (`~/bm-<slug>` → Dropbox workspace when Dropbox-backed) not automated.
- Working example symlink: `~/bm-ben` → `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-ben`.

## Engineering craft gates
- Diagnose: N/A — not a bug hunt; root cause already established (manual step + fallback path).
- Prototype: N/A — target shape is the existing bm-ben symlink pattern; no design uncertainty.
- TDD/verification: applies — public interface = new `scripts/install_picker_dir.sh` + generator behavior; write the generator test first (see Verification 1), then implement.

## Fix 1 — generator reads explicit paths, fails loud on unknowns
In `generate_agent_identity_artifacts.py`:
1. Add `cowork-bb-desk: /Users/dimitry/bm-cowork-bb-desk` to the explicit map.
2. Change the silent `/Users/dimitry/baker-vault` fallback: keep it for known service-class agents (list them explicitly), but for any slug not in either list **print a WARNING to stderr naming the slug** and still emit the fallback (do not break generation). Fail-loud, not fail-hard.
3. Regenerate artifacts (`python3 scripts/generate_agent_identity_artifacts.py --write`) and commit the regenerated `agent_identity_generated.sh`.

## Fix 2 — `scripts/install_picker_dir.sh <slug> [--dropbox]`
New idempotent script:
- Default: `mkdir -p ~/bm-<slug>` if absent.
- `--dropbox`: create `"/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-<slug>"` if absent, then `ln -s` it to `~/bm-<slug>` (skip + report if a real dir already occupies the target — NEVER delete or overwrite an existing dir; print what it found and exit 1).
- Always end by printing a 3-line checklist: picker dir state, symlink state, reminder to add the slug to `_snapshot_path_for()` + regenerate.
- Idempotent: second run = no-op with "already wired" output.

## Fix 3 — SOP AC1 patch (docs)
Prepare (do not push to vault yourself) a patch block for `install-agent-to-brisen-lab-sop.md` AC1 replacing the manual step with the script invocation + the regenerate step. Deliver the patch text in your completion report; lead applies to vault.

## Key constraints
- NEVER delete/move an existing `~/bm-*` dir or Dropbox folder — create-or-report only.
- Do not touch the wake-handler (separate brief, b1) or `agent_registry.yml` (vault-side, lead's lane).
- Secrets: none involved; keep it that way.

## Verification (done rubric)
1. Generator test: run generator on current registry → `cowork-bb-desk` resolves to `/Users/dimitry/bm-cowork-bb-desk`; an invented slug triggers the stderr WARNING (show both outputs).
2. `install_picker_dir.sh testslug-zz` twice → dir created once, second run no-op; then clean up the test dir.
3. `install_picker_dir.sh testslug-zz --dropbox` in a safe temp HOME or with a test prefix if feasible; otherwise document the manual dry-run reasoning honestly.
4. `bash -n` both scripts; existing singleton guard `bash scripts/check_singletons.sh` still passes.

## Files modified
- `scripts/generate_agent_identity_artifacts.py` · `scripts/agent_identity_generated.sh` (regenerated) · `scripts/install_picker_dir.sh` (new)
## Do NOT touch
- `tools/wake-handler/` (brisen-lab repo — b1's brief) · `baker-vault/_ops/registries/agent_registry.yml` (lead merges vault) · any existing `~/bm-*` contents.
