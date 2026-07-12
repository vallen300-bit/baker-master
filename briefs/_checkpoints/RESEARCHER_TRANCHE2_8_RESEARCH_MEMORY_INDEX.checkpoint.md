---
brief_id: RESEARCHER_TRANCHE2_8_RESEARCH_MEMORY_INDEX
dispatch: lead #9721 (Director parallelism) + #9894 (priority-now) + #9898 (design APPROVED, rulings)
owner: b2
attempt: 2
updated: 2026-07-12
status: SHIPPED (attempt 2) — build complete, 2 PRs open awaiting lead merge (baker-master#542, baker-vault#186). Ship report briefs/_reports/B2_RESEARCH_MEMORY_INDEX_20260712.md; bus ship lead #9936. Item-8 build lane DONE; remaining lane = edge-scout PR #183 (Fri 2026-07-17).
---

# Checkpoint — Researcher Tranche-2 #8 Research memory / index

## What's done
- **Design APPROVED by lead #9898.** Option B (vault-wiki JSON manifest + regen + grep/jq).
  Design doc: `briefs/_design/DESIGN_RESEARCHER_TRANCHE2_8_RESEARCH_MEMORY_INDEX.md`
  (committed on branch `b2/researcher-research-memory-index-design`, **PR #541** baker-master).
- **Lead's 3 §5 rulings (build to these):**
  1. Regen ownership = **BOTH** researcher-on-ship + Mac-Mini weekly backstop.
  2. `_index.md` = **REGENERATE from the manifest** (single source of truth — do not hand-maintain).
  3. Semantic search = **DEFER past ~300 docs**; log as a design note in the build.
  - Cage: **additive IS_VETTED exact-path entries ONLY**, no cage weakening — flag them
    explicitly in the build PR for gate focus.
- Cage-gotcha resolved: `researcher_write_cage.sh` is a PreToolUse hook on Write|Edit|MultiEdit
  ONLY — it does NOT gate bash-spawned writes (those go through `researcher_bash_cage.sh`
  exact-path IS_VETTED). `_index.json` under `wiki/research/` is in-cage for both paths.

## What's left — BUILD item-8 (Option B, to lead's rulings)
1. `scripts/regen_research_index.sh` (baker-master) — scan `$BAKER_VAULT_PATH/wiki/research/*.md`
   (excl `_index.*`), parse heterogeneous frontmatter best-effort, emit `wiki/research/_index.json`
   (machine SoT) + regenerate `wiki/research/_index.md` (human view, from same manifest).
   Deterministic order (date desc, path). Fail-LOUD: the 2 no-frontmatter reports flagged
   (`flags:["no-frontmatter"]`), NOT dropped. No env/arg config path.
2. `scripts/search_research_index.sh` — READ-ONLY jq/grep over `_index.json`; args=keywords;
   returns path+date+title+summary. No writes/ack/arg-exec (mirror check_source_monitors.sh).
3. Cage: 2 additive IS_VETTED exact-path entries in `_ops/hooks/researcher_bash_cage.sh`
   for regen + search. Additive only. Flag in PR.
4. Mac-Mini weekly regen: launchd plist (mirror edge-scout/research-monitors prefetch pattern).
5. Tests: heterogeneous-frontmatter parse; no-frontmatter flagged-not-dropped; deterministic/
   idempotent regen; search returns correct subset; empty-corpus clean.
6. `_index.json` initial regen committed (58/60 have frontmatter; 60 total reports as of 07-12).

## Key paths / commits
- Design branch `b2/researcher-research-memory-index-design` @ committed doc (PR #541, design-only).
- Source brief: `~/baker-vault/wiki/research/2026-07-12-researcher-capability-extension-brief.md`
  @22ab300 (item #8, §5 Q3).
- Prior-art: `research-monitors-prefetch.sh` (f27da57), `check_source_monitors.sh` (vetted reader),
  `research_commit.sh` (in-cage git write), `researcher_bash_cage.sh` IS_VETTED case.
- Rails: build on NEW branch (baker-master scripts+tests) + vault worktree (cage+_index.json);
  two-gate Claude-side review (codex suspended #9711); **lead merges, NO self-merge**.

## SECOND LANE — edge-scout worktree fix (#9647), HARD DEADLINE Fri 2026-07-17 17:00Z
- **BUILT + PUSHED already** (prior seat, killed by 19:52 refresh sweep before PR):
  branch `b2/edge-scout-prefetch-worktree-isolation` @ **1219f06**, worktree
  `/private/tmp/b2-edge-scout-wt`. **PR #183 baker-vault OPEN** (opened this seat).
- Ports f27da57 into `scripts/edge-scout-prefetch.sh` (+36/-10, one file). Static AC clean
  (no reset --hard / cd-VAULT-commit on shared checkout); `bash -n` OK; `--dry-run` 4/4 feeds.
- **Left:** ~~(a) scratch-clone non-dry-run verify~~ **DONE 2026-07-12 (bus lead #9939 / deputy
  #9940):** isolated fake-origin + scratch clone, PR-branch script non-dry-run — 4/4 feeds,
  worktree-isolated commit pushed HEAD:main to FAKE origin, scratch uncommitted sentinel
  SURVIVED (#157 risk fixed), real ~/baker-vault untouched. (b) lead Claude-side review of
  PR #183 (PENDING lead); (c) Mini deployed-copy redeploy
  (`~/Library/Application Support/baker/edge-scout-prefetch.sh`) — deputy verifies on Mini
  (PENDING deputy); (d) POST_DEPLOY_AC_VERDICT v1 before the Friday fire (after Mini redeploy).

## Next concrete step (successor)
Item-8 SHIPPED (baker-master#542 + baker-vault#186, awaiting lead merge). Edge-scout
scratch-verify DONE; only external steps remain (lead review, deputy Mini redeploy,
POST_DEPLOY_AC after redeploy). If both PRs merged + edge-scout deployed → arc COMPLETE.
Otherwise: poll PR #542/#186 merge status + chase deputy on Mini redeploy before Fri 07-17 17:00Z.
