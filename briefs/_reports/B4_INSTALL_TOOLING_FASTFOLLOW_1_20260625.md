# B4 ship report — INSTALL_TOOLING_FASTFOLLOW_1

- **Dispatch:** bus #4315 from `lead` (2026-06-25)
- **Branch:** `b4/install-tooling-fastfollow-1-fix1`
- **PR:** #426 (FIX 1 only)
- **Ship bus post:** #4344 → lead

## FIX 1 — install_forge_push.sh co-deploys the identity sibling — SHIPPED

**Root cause.** `forge_snapshot_push.sh:15` sources `agent_identity_generated.sh` from its own `SCRIPT_DIR`. `install_forge_push.sh` copied only the worker to `~/Library/Application Support/baker/`, leaving the deployed slug list stale/missing → snapshot pusher 400s on newly-added slugs (`baden-baden-desk`, #4312/#4314).

**Change.**
- Co-deploy `agent_identity_generated.sh` next to the worker (`chmod 600`) + FATAL guard on missing source.
- `FORGE_INSTALL_DEPLOY_DIR` + `FORGE_INSTALL_DRYRUN` env hooks for safe testing; prod path unchanged.
- New `tests/test_install_forge_push.sh` (5 cases).

**Verification (literal).**
- `tests/test_install_forge_push.sh` → `All 5 cases PASS.`
- `tests/test_forge_snapshot_push.sh` → `All 23 cases PASS.` (unaffected)
- `bash -n` clean on both scripts.

**Done rubric.** Harness-done = PR merged + literal pytest/smoke green. PR #426 open; gate plan G2 codex MEDIUM → G3 AH2 (deputy) → G4 lead.

## FIX 2 — bus_post.sh staleness — ESCALATED, NOT SHIPPED

The brief's preferred fix (symlink `~/Desktop/baker-code/scripts/bus_post.sh` → `~/bm-b1/...`) is **proven non-functional**:
- `bus_post.sh` and the Desktop copy are byte-identical (3529b). The stale artifact is the **sibling** `agent_identity_generated.sh` (Desktop 0 baden refs / bm-b1 5; Desktop clone 19 commits behind).
- `bus_post.sh:18` derives `SCRIPT_DIR` from `$0`'s dirname and sources the sibling from there (line 20). A symlinked `bus_post.sh` keeps `$0` dirname = Desktop/scripts → still sources the stale Desktop identity.
- Scratch-dir proof: TEST A (symlink bus_post.sh only) → `unknown slug: baden-baden-desk`; TEST B (symlink the identity sibling) → validation passes.

Two working alternatives handed to lead (#4344): (a) symlink the identity sibling instead [1-step, TEST-B-proven, couples Desktop↔bm-b1]; (b) repoint footer/orientation refs to each agent's own clone [durable in-repo, no cross-clone coupling]. Lean (b). Awaiting lead's pick before building.

## SOP note (AC11 / Row 12)

Lives in baker-vault `_ops/processes/install-agent-to-brisen-lab-sop.md` — vault-side / AH-Director commit territory (CHANDA Inv 9). Draft one-liner handed to lead in #4344; not committed from this repo.
