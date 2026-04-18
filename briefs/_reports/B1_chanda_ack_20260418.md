# B1 CHANDA.md Acknowledgment

**Read at commit:** 915f8ad (`CHANDA.md` adoption) / resynced at 1b0e502 after misfire on already-merged SLUGS-1
**Timestamp:** 2026-04-18 ~10:15 UTC

---

## The three legs in my own words

1. **Compounding (Leg 1):** Before I generate or modify anything in Silver, the pipeline I'm touching must have read every Gold card for the matter first. No "skip the read for perf", no "load lazily on first hit" — the read pattern *is* the contract. If I write a Silver-generation path that doesn't load Gold, I've quietly removed the interest from the interest-bearing account.
2. **Capture (Leg 2):** Whenever the Director does anything that expresses judgment (promote, correct, ignore, dismiss), the feedback ledger must get that row *or* the action fails. No best-effort writes, no "we'll retry tomorrow". If ledger write can fail silently, Director's judgment evaporates and Leg 1 reads an empty account forever after.
3. **Flow-forward (Leg 3):** Step 1 on every pipeline tick loads `hot.md` *and* the feedback ledger — both, every run, unconditionally. Not on schedule, not on cache invalidation, not "if recently changed". If I see code that short-circuits either read, I've broken the path by which past judgment reaches future classification.

Break one leg → system keeps producing output, looks fine on the dashboard, stops learning.

---

## Invariants most likely to bind my typical work

- **Inv 4 (`author: director` files never modified by agents):** I don't edit CHANDA.md, I don't edit any other Director-authored wiki file, full stop. Even if a task seems to require it (typo fix, broken link), I flag and wait. Bootstrap exception at `915f8ad` was one-shot.
- **Inv 9 (Mac Mini single writer; Render → `wiki_staging` only):** When I touch pipeline wiring, storage paths, or KBL-B implementation, writes to wiki must route through Mac Mini. Render code that writes anywhere but `wiki_staging` is a bug regardless of what the test says.
- **Inv 10 (pipeline prompts do not self-modify):** If I'm tempted to add "adaptive prompt" logic — per-matter prompt tweaks, auto-tuning from recent signals, etc. — I stop. Learning flows through data (the ledger), not through code rewriting its own prompts. This one bites because it's a plausible-looking optimization path.
- **Inv 2 (atomic ledger-or-fail for Director actions):** Same binding as Leg 2 but worth restating: any new Director-action endpoint I build has the ledger write in the same transaction as the primary effect, or the action fails loudly. No try/except around the ledger write.
- **Inv 5 (every wiki file has frontmatter; missing = failure):** When I write tools that emit wiki files, frontmatter is required, not optional. Parser that defaults to `{}` on missing frontmatter is a bug.

Inv 6 (never skip Step 6) and Inv 8 (no auto-promotion) bind less often for me directly but constrain KBL-B work once I start implementing.

---

## Pre-push checklist I now run before every commit

- [ ] **Q1 Loop Test:** Does this change touch Leg 1 read pattern, Leg 2 ledger write, or Leg 3 Step-1 integration? If yes → stop, flag to AI Head, wait. If no → document briefly why it's orthogonal.
- [ ] **Q2 Wish Test:** Does this serve the wish or engineering convenience? Convenience alone → stop, flag. Both → state the tradeoff in the commit body.
- [ ] **Inv 4 check:** Did I modify any file with `author: director` in frontmatter? If yes → revert + flag.
- [ ] **Inv 10 check:** Does any code I added mutate a pipeline prompt based on runtime data? If yes → revert + flag.
- [ ] **Verify-before-done:** run the actual flow end-to-end, not just type-check or unit tests. Four Principles #4.

---

## Questions / tensions surfaced

1. **SLUGS-1 residual catalogue vs. CHANDA.** The SLUGS-2 catalogue I filed at `briefs/_drafts/SLUGS_2_RESIDUAL_CATALOGUE.md` recommends a schema extension to `slugs.yml` (add `paths:` field) that would pull matter→path mappings out of `tools/document_pipeline.py`. That schema evolution touches the registry that Step 1 consumes — it's adjacent to Leg 3's "Step 1 reads hot.md + feedback ledger" contract. Not the same file, but the same pipeline read-path. I think this is clearly a **Q1 trigger** when it's implemented, not just a schema refactor. Flagging so AI Head tracks it pre-SLUGS-2 dispatch.

2. **`hot.md` location and maintenance.** CHANDA §2 Leg 3 says `~/baker-vault/wiki/hot.md` is Director-curated in Phase 1 and pipeline-maintained from Phase 3. I haven't seen that file in any PR I've touched yet, and `briefs/PLAN_VAULT_OBSIDIAN_V2.md` may or may not already cover it. No conflict — just noting the file doesn't exist in my working copy and I'd like to know the expected creation point (Director adds it manually before first tick? KBL-B creates it as part of install?). Not urgent, but it's a contract I'll need to honor in KBL-B work.

3. **Inv 10 vs. `_build_step1_prompt()`.** The function I just rebased builds the Step 1 prompt dynamically from the slug registry. That's *registry-driven*, not *runtime-learning-driven* — the registry itself is Director-curated data, not Silver-generated output — so I read this as compatible with Inv 10. But it sits in the grey zone between "prompt is a fixed string" and "prompt adapts at runtime". I want to state my reading explicitly so Director can correct if the distinction I'm drawing is wrong: data-driven prompt construction from a Gold-like source = OK; any pipeline-generated rewriting of prompts = not OK.

4. **Reflexive process error I just made.** Immediately before this ack, I reported SLUGS-1 rebased + ready-to-merge on a branch that had been merged ~14 hours earlier. I did not run `gh pr view 2 --json state` before reporting. Adding that to my checklist: **before reporting any PR-related work "ready for merge," run `gh pr view <N>` and confirm `state == OPEN` and the head matches mine.** This is a direct consequence of skipping the Q1 discipline at the meta level (jumped to action on a stale assumption).

---

*Ritual acknowledged. Returning to stand-by. Next session starts with `cat CHANDA.md` before `cat briefs/_tasks/CODE_1_PENDING.md`.*
