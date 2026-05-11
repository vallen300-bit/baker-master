# CODE_3_PENDING — BRISEN_LAB_FORGE_PUSH_FOLD_1 — 2026-05-11

**Brief:** `briefs/BRIEF_BRISEN_LAB_FORGE_PUSH_FOLD_1.md`
**Repo:** `baker-master` (this repo)
**Working dir:** `~/bm-b3` (your primary clone)
**Branch:** create new `b3/brisen-lab-forge-push-fold-1` off latest `main`
**Base SHA:** `0189390` or newer (PR #187 squash, post-merge)

**Supersedes:** prior CODE_3 slot (BRIEF_BRISEN_LAB_FORGE_PUSH_REVIVE_1, PR #187 merged + daemon live on Mac Mini).

## Pre-step (mandatory)
```bash
cd ~/bm-b3
git fetch origin main
git checkout main
git pull --ff-only
# verify PR #187 is in: should see scripts/forge_snapshot_push.sh
git log --oneline -5 | grep BRISEN_LAB_FORGE_PUSH_REVIVE_1
git checkout -b b3/brisen-lab-forge-push-fold-1
```

## Scope (~1h, 3 fixes)
Read the brief at `briefs/BRIEF_BRISEN_LAB_FORGE_PUSH_FOLD_1.md`. Three folds on PR #187:

1. **TCC fix** — installer deploys worker script to `~/Library/Application Support/baker/` (instead of running launchd against repo path under `~/Desktop` which TCC blocks). Plist gets `__WORKER_PATH__` placeholder substituted by installer. Mirrors the canonical/deployed pattern of the stop hooks.
2. **`sed` → Python substitution** — `install_forge_push.sh` replaces the `sed "s|...|..."` pattern with `python3 ... str.replace(...)`. Unconditionally safe regardless of FORGE_KEY content.
3. **Smoke test exercises the fake fixture** — add `TERMINALS_OVERRIDE` env var to the worker script (5 lines), rewrite the test to set it pointing at a fake `$TMPDIR/fake-b9` repo + assert the script processed ONLY the override, not the 6 production aliases.

## Ship requirements
- `bash -n` syntax-clean on `install_forge_push.sh` and `forge_snapshot_push.sh`.
- `bash tests/test_forge_snapshot_push.sh` passes (now actually verifies fixture override).
- `grep -c 'sed' scripts/install_forge_push.sh` = 0.
- `grep '__WORKER_PATH__' scripts/launchd/com.baker.forge-snapshot-push.plist` = 1 match.
- PR title: `feat(scripts): forge-push fold — TCC deploy, Python substitution, fixture-exercising smoke test (BRISEN_LAB_FORGE_PUSH_FOLD_1)`.
- Bus-post on ship: `BAKER_ROLE=b3 ~/Desktop/baker-code/scripts/bus_post.sh lead "<ship summary>" ship/BRISEN_LAB_FORGE_PUSH_FOLD_1`.

## What NOT to do
- Do NOT reinstall the daemon yourself — that's AH1's post-merge step on Mac Mini.
- Do NOT touch `app.py` or `db.py` on brisen-lab side — pure Mac Mini change.
- Do NOT add fenced `**TO: AH1-App PL**` paste-block (PL ship-report contract RETIRED 2026-05-11).
- Do NOT add wake-paste (Rule 0.5 RETIRED 2026-05-11). Bus is the wake.
- Do NOT rename or move the canonical repo script — only the installer changes how it's deployed.

## Heartbeat
12h cadence. If you hit a blocker, bus-post `blocker/BRISEN_LAB_FORGE_PUSH_FOLD_1` to `lead`.

— lead (AH1)
