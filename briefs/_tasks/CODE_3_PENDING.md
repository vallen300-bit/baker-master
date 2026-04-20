# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-20 (afternoon, post-Phase-D-ship — parallelizing with B2 on Phase C)
**Status:** OPEN — SOT Phase D review (two-PR pair, reassigned from B2)

---

## Task: Review the Phase D PR pair — vault-read MCP tools for Cowork

B2 is on Phase C review. You take Phase D. Parallelizing clears the SOT queue faster.

**PR pair** (must be reviewed together — coupled):
- **baker-master PR #28** @ `237d8c7` — branch `sot-obsidian-1-phase-d-vault-read`. MCP tools + mirror + scheduler + tests.
- **baker-vault PR #6** @ `707555e` — branch `sot-obsidian-1-phase-d-operating-append`. AI Dennis OPERATING.md consumption doc (required by brief §Cowork-side consumption doc).

**Shipped by:** B1.
**Ship report:** `briefs/_reports/B1_sot_phase_d_ship_20260420.md` on baker-master (commit `592b07d`).
**Brief:** `briefs/BRIEF_SOT_OBSIDIAN_1_PHASE_D_VAULT_READ.md` at commit `d6a50ef` in baker-master.

---

## Scope summary (from B1's ship report)

- `vault_mirror.py` — clone/pull baker-vault into `/opt/render/project/src/baker-vault-mirror/`; realpath-based traversal guard; 128 KB cap; `.md/.yml/.yaml/.txt` allowlist.
- Two new MCP tools on existing Baker MCP: `baker_vault_list` + `baker_vault_read`.
- FastAPI startup hook (fatal on first-clone fail, non-fatal on subsequent pull); `vault_sync_tick` APScheduler job (env `VAULT_SYNC_INTERVAL_SECONDS` default 300, floor 60); `/health` extended with `vault_mirror_last_pull` + `vault_mirror_commit_sha`.
- 21 new tests via hermetic bare-repo fixture + 1 amended regression on `test_startup_call_order` for CI hermeticity.
- `_ops/` secret audit: 14 hits, all concept docs, zero secret values.

---

## B1's three flagged design calls (you decide)

1. **Single `vault_mirror.py` module** rather than `baker_vault/` package (brief §Fix/Feature 1 "principle 3"). Check: is the module's internal structure clean enough that a future sibling tool (`baker_vault_write` in a distant future brief) could import and extend cleanly? If yes, accept. If the module is tangled, REDIRECT to extract a package.

2. **Module-level `_git_lock`** to serialize startup + tick (instead of filesystem flock). Check: does the lock cover both the startup hook and the scheduler tick? Any path where the lock is dropped between clone and first read? Filesystem flock would survive process restart; module lock does not — is that OK given the mirror is re-cloned on restart anyway? Likely yes, but verify.

3. **Lazy imports inside dispatch/wrapper branches** (matches `_kbl_bridge_tick_job` pattern). Check: does this lazy-import pattern prevent circular imports, OR is it just copy-paste of the bridge pattern? If the latter, eager imports at module top would be cleaner. Your call.

All three are defensible. Architectural judgment — brief ratification authorized reasonable deviation.

---

## Verdict focus (beyond deviations)

- **Path safety is load-bearing.** Does the test suite cover: traversal (`../`), absolute paths (`/etc/passwd`), symlink escapes (if any symlinks inside `_ops/`), binary files (e.g. PNG), oversize files (>128 KB), nonexistent paths? If any is missing, REDIRECT.
- **Mirror is read-only.** No `git push` anywhere in `vault_mirror.py`. Grep to confirm.
- **Scheduler job floor.** `VAULT_SYNC_INTERVAL_SECONDS` must be clamped to ≥60s — tests prove?
- **First-clone fatality.** Startup hook must block FastAPI boot if first clone fails (otherwise MCP starts and returns empty/errors — confusing). Post-first-clone pull failures non-fatal (mirror stays at last known HEAD). Both paths tested?
- **Tool output shapes:** `baker_vault_read` returns `{path, content_utf8, sha256, bytes, last_commit_sha}` per brief §2. `baker_vault_list` returns list of relative paths. Verify.
- **Secret audit:** B1 reports 14 concept-doc hits. Spot-check 3 of them to confirm they're docs not values.
- **`/health` shape:** `vault_mirror_last_pull` (ISO timestamp) and `vault_mirror_commit_sha` (full SHA). Present on green deploy? (You can't verify live without waiting for merge + deploy — confirm code writes the keys to the health dict.)
- **Cowork doc append (baker-vault PR #6):** content matches brief §4 call pattern exactly. New section titled "Reading your canonical files (Cowork)" in `_ops/agents/ai-dennis/OPERATING.md`? Frontmatter `updated` bumped to 2026-04-20?

**Reviewer-separation:** B1 implemented. You just shipped Phase C (unrelated). Clean to review.

## Reports

- baker-master PR #28 review: `briefs/_reports/B3_pr28_phase_d_master_review_20260420.md` on baker-master.
- baker-vault PR #6 review: `_reports/B3_pr6_phase_d_vault_review_20260420.md` on baker-vault.

Verdict can be combined (single verdict covering both PRs) if coupled; otherwise separate. **Both PRs must APPROVE together for AI Head to merge** — merging one without the other leaves Cowork with tools but no doc, OR doc pointing at nonexistent tools.

AI Head auto-merges both on combined APPROVE per Tier A. Day 1 verification happens on AI Head immediately post-merge.

## After this

Phase E (CHANDA Inv 9 refinement + pipeline frontmatter filter) is the last SOT phase. Tier B — Director explicit auth required before anyone touches CHANDA.md.

Close both tabs after reports shipped.
