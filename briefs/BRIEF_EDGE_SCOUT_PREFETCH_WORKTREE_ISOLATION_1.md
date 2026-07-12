# BRIEF: EDGE_SCOUT_PREFETCH_WORKTREE_ISOLATION_1 — port the isolated-worktree commit pattern to the LIVE edge-scout prefetch job

> Authored by deputy (AH2, bus-health owner) per lead order #9602/#9612. **Assigned: b2** (owns
> the f27da57 fix this ports). **HARD DEADLINE: merged + Mini-deployed BEFORE Fri 2026-07-17 17:00Z**
> (next scheduled fire). Independent codex gate before lead merge (#9255).

dispatched_by: lead
assigned_to: b2
task_class: backend-reliability (launchd prefetch job: shared-vault write safety)
Harness-V2: Context Contract + done rubric + gate plan inline.
effort: low (mechanical port of a proven fix)

## Context

**Context Contract.** Two artifacts, SAME fix: (1) the repo source of `edge-scout-prefetch.sh`, and (2) the deployed copy on the Mac Mini at `~/Library/Application Support/baker/edge-scout-prefetch.sh`. The fix is a direct port of b2's already-merged `f27da57` (vault #176), which fixed the identical anti-pattern in `research-monitors-prefetch.sh`. No new logic — copy the proven pattern.

**Finding (deputy #9519, lead-accepted #9602):** the LIVE `com.baker.edge-scout-prefetch` launchd job (Fridays 17:00 UTC; last ran 2026-07-11 17:00, pushed OK) runs, on the SHARED `~/baker-vault` checkout:
```
cd "$VAULT_DIR"                # shared /Users/dimitry/baker-vault
git fetch origin main
git reset --hard origin/main   # ⚠️ destroys any uncommitted shared-vault state
mkdir -p "$CACHE_DIR"
...
cd "$VAULT_DIR"
git add "$CACHE_REL"
git commit -m "cache(edge-scout): pre-fetch $ISO_NOW"
git push origin main           # ⚠️ direct push to main from the shared checkout
```
This is the ORIGINAL of the item-12 anti-pattern (b2 confirmed #12 was copied from here). It violates the vault-writer worktree-isolation rule (#157): the `reset --hard` runs BEFORE any commit hook, so #157's guard does not catch it, and it force-writes to main outside the isolated-worktree discipline.

**Risk:** latent, not imminent — the Mini vault is currently clean and next fire is Fri 07-17 17:00Z (~5 days). But ANY uncommitted work in the Mini shared vault at fire time gets nuked. Fix before that fire.

## Problem

`edge-scout-prefetch.sh` mutates + commits + pushes on the shared `~/baker-vault` working tree, exactly the pattern #157 forbids. It must instead commit from an isolated detached worktree of `origin/main`, never touching the shared checkout.

## Fix (port f27da57)

Apply the same structure b2 shipped in `research-monitors-prefetch.sh` (f27da57):
- Add `cleanup_worktree()` + `trap cleanup_worktree EXIT`.
- Create an isolated worktree: `git -C "$VAULT_DIR" worktree add --detach "$WORKTREE" origin/main`.
- Write the cache into the WORKTREE, `git -C "$WORKTREE" add/commit`, `git -C "$WORKTREE" push origin HEAD:main`.
- REMOVE the `cd "$VAULT_DIR"; git reset --hard origin/main` on the shared checkout entirely — the worktree is a fresh detached checkout of origin/main, so no reset is needed.
- Keep the existing fail-loud guards (skip-commit-if-no-changes; the dry-run path if present).
- Cross-check the two scripts converge on ONE pattern (surface-conflicts rule) — ideally factor a shared helper if both live in the same repo, else keep them structurally identical and note it.

## Files Modified

- Repo source: `edge-scout-prefetch.sh` (locate its tracked path — likely `scripts/` in baker-master or the vault; confirm which repo owns it).
- Deployed copy: `~/Library/Application Support/baker/edge-scout-prefetch.sh` on the Mini (redeploy after merge — the launchd job runs the DEPLOYED copy, not the repo copy, so a repo-only merge does NOT fix production).

## Verification

1. **Unit/static:** the fixed script contains NO `git reset --hard` on `$VAULT_DIR` and NO `cd "$VAULT_DIR"; git commit/push`; all git write-ops target the isolated `$WORKTREE`; cleanup trap present.
2. **Dry-run (safe):** `--dry-run` (if present) still fetches to a temp dir, no git ops — fetch path unaffected.
3. **Scratch-clone live run:** run the fixed non-dry-run script with `BAKER_VAULT_PATH` = a SCRATCH clone (NOT the real shared vault); confirm it (a) leaves the scratch shared working tree untouched (no reset damage), (b) commits + pushes from the worktree, (c) cleans up the worktree on exit. (Mirror the item-12 scratch-verify deputy is running.)
4. **Deployed-copy check:** after redeploy to the Mini, `diff` the deployed copy against the merged source = identical; the launchd plist still points at the deployed path.
5. **Post-deploy AC:** emit `POST_DEPLOY_AC_VERDICT v1` to lead confirming repo + Mini copy both fixed BEFORE Fri 07-17 17:00Z. Deputy (bus-health owner) confirms on the Mini.

## Quality Checkpoints / Acceptance criteria

- **done rubric:** (1) shared-checkout reset/commit/push removed; (2) all writes via isolated worktree + cleanup trap; (3) scratch-clone run proves no shared-tree damage + successful worktree push; (4) BOTH repo source AND Mini deployed copy fixed (a repo-only fix does NOT stop the live job); (5) `POST_DEPLOY_AC_VERDICT v1` before Fri 07-17 17:00Z.
- **done-state class:** live production launchd job with shared-vault write side-effects → deployed-copy verification required, not repo-merge alone.
- **gate plan:** deputy authors → b2 implements (owns f27da57) → **independent Claude-side review by lead BEFORE merge** (was "independent codex verify"; changed 2026-07-12 per Director codex-suspension order #9711 — codex seats unavailable until Director lifts; #9255 independent-verdict-before-merge rule still holds, Claude-side) → lead merges → **redeploy to Mini** → deputy verifies deployed copy on the Mini before the Friday fire.
- **Harness-V2:** covered inline.

## Cross-links

- Ports `f27da57` (vault #176, research-monitors-prefetch.sh worktree fix).
- Deputy finding #9519; lead acceptance + order #9602/#9612.
- Same lane as the aidennis-edge-scout consumer (reads the cache this job writes).
