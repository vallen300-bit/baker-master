# CODE_3_PENDING — BRISEN_LAB_FORGE_PUSH_REVIVE_1 — 2026-05-11

**Brief:** `briefs/BRIEF_BRISEN_LAB_FORGE_PUSH_REVIVE_1.md`
**Repo:** `baker-master` (this repo — adds Mac Mini-side scripts under `scripts/`)
**Working dir:** `~/bm-b3` (your primary clone)
**Branch:** create new `b3/brisen-lab-forge-push-revive-1` off latest `main`

**Supersedes:** prior CODE_3 slot (BRIEF_CORTEX_TIER_B_ATOMICITY_V1, status SHIPPED_FOLD_OK 2026-05-10, PR #182 merged). That work is complete and archived in git history.

## Pre-step (mandatory)
```bash
cd ~/bm-b3
git fetch origin main
git checkout main
git pull --ff-only
git checkout -b b3/brisen-lab-forge-push-revive-1
```

## Scope (~2h)
Read the brief at `briefs/BRIEF_BRISEN_LAB_FORGE_PUSH_REVIVE_1.md`. Mac Mini-side daemon that POSTs snapshot data to `https://brisen-lab.onrender.com/api/snapshot` every 30s. The endpoint is alive — only the writer died. Four new files:

1. `scripts/forge_snapshot_push.sh` — worker script (~120 lines bash).
2. `scripts/launchd/com.baker.forge-snapshot-push.plist` — launchd template with `__FORGE_KEY__` placeholder.
3. `scripts/install_forge_push.sh` — installer with idempotent unload+reload.
4. `tests/test_forge_snapshot_push.sh` — smoke test (script does not crash + state collection succeeds in tmpdir).

## Ship requirements
- `bash -n` syntax-clean on all 3 shell scripts.
- `bash tests/test_forge_snapshot_push.sh` passes.
- Manual dry-run section in brief is achievable (you should run it).
- PR title: `feat(scripts): revive Mac Mini → Brisen Lab forge_snapshots writer (BRISEN_LAB_FORGE_PUSH_REVIVE_1)`.
- Bus-post on ship: `BAKER_ROLE=b3 ~/Desktop/baker-code/scripts/bus_post.sh lead "<ship summary with PR link + commit + bash -n output>" ship/BRISEN_LAB_FORGE_PUSH_REVIVE_1`.

## What NOT to do
- Do NOT install the launchd agent yourself — that's AH1's post-merge step on Mac Mini (you'd need AH1's shell env to substitute FORGE_KEY).
- Do NOT touch `brisen-lab-staging/app.py` — endpoint already works.
- Do NOT commit FORGE_KEY value anywhere. Only the `__FORGE_KEY__` placeholder in the template.
- No fenced `**TO: AH1-App PL**` paste-block at end of ship report (PL ship-report contract RETIRED 2026-05-11).
- No fenced wake-paste (Rule 0.5 RETIRED 2026-05-11). Bus-post is the wake.

## Heartbeat
12h cadence binding per SKILL.md. If you hit a blocker, bus-post `blocker/BRISEN_LAB_FORGE_PUSH_REVIVE_1` to `lead`.

— lead (AH1)
