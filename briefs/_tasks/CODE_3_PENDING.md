# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** STEP5-OPUS S1 author rename applied + APPROVE'd at `02e5063`. Idle since.
**Task posted:** 2026-04-18 (late afternoon)
**Status:** OPEN

---

## Task: SLUGS-V9-FOLD — Update worked examples + present_signal menu for slugs.yml v9

### Why

Director's Fireflies indexing session (baker-research) bumped `baker-vault/slugs.yml` v1 → v9 this afternoon:
- **`theailogy` retired** (not a matter; personal AI playbook)
- **`mo-vie` → `mo-vie-am`** (rename cascaded into hot.md)
- **14 new slugs added**

Your `KBL_B_STEP5_OPUS_PROMPT.md` worked examples still reference `mo-vie` and `theailogy`. Worked examples are **few-shot demonstrations** fed to Opus at inference — Opus will confidently produce retired slugs on real signals, and the slug-registry validator will reject them. **Load-bearing — must fix before Step 5 impl lands.**

`scripts/present_signal.py` has the same problem (human-labeling menu only, not runtime-critical, but bundle it into the same commit for cleanliness).

### Scope

**IN**

1. **`briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md`** — worked examples fold:
   - Every `mo-vie` (standalone, not `mo-vie-am`, not `mo-vie-exit`) → `mo-vie-am`. Scan all 3 worked examples + any prose references. Preserve `mo-vie-exit` (still an active slug in v9).
   - Every `theailogy` → pick a sensible v9 replacement OR drop the reference. Your call — `theailogy` appears in worked example #2 as `related_matters: [theailogy]` (cross-reference for AI-platform work). Current v9 slugs that could fit: `m365` (infra/platform), `nvidia` (AI compute), or simply drop the cross-ref line. Lean: replace with **`m365`** since the example is about MO Vienna's AI platform build — M365 migration is the live tech-infra thread. If the specific example doesn't fit any v9 slug cleanly, remove the cross-ref bullet entirely; worked example survives without it.
   - Update `hot.md` ACTIVE / BACKBURNER blocks inside the worked-example inputs to reflect current hot.md shape (reference `/Users/dimitry/baker-vault/wiki/hot.md` as the current source of truth — Director's v9 state, committed today).
   - Any vault path `wiki/mo-vie/...` → `wiki/mo-vie-am/...` (cascades into the thread-continuation references).

2. **`scripts/present_signal.py`** — menu cleanup:
   - Line 21: `("3", "mo-vie")` → `("3", "mo-vie-am")`
   - Line 29: remove `"theailogy"` from `EXTRA_MATTERS_BY_NAME`. Add any of the 14 new v9 slugs that would help labeling workflow, at your discretion (optional — safe to just remove `theailogy` and ship). Verify `mo-vie` removed from `EXTRA_MATTERS_BY_NAME` if present.

3. **No test changes required** — neither file has runtime tests. Your self-check: re-read `baker-vault/slugs.yml` v9 locally before committing to confirm no other retired slugs survived in your touched files.

### CHANDA pre-push

- **Q1 Loop Test:** template worked-examples are prompt data, not loop mechanics. No Leg touched. Pass.
- **Q2 Wish Test:** serves wish — prevents Opus from emitting retired slugs that would fail validator → signal stuck in `opus_failed`. Fix preserves the loop-flow contract. Pass.
- **Inv 10 (pipeline prompts don't self-modify):** your edit is draft-time authoring, not runtime self-modification. Pass.
- **Inv 4 (author-director files untouched):** neither `hot.md` nor `slugs.yml` is modified by this task — you **read** them to ground your edits, but the writes are in `KBL_B_STEP5_OPUS_PROMPT.md` (author: pipeline-prep) + `scripts/present_signal.py` (agent-owned).

### Branch + PR

- Option A: push directly to `main` as a small-surface commit (no PR). This is the pattern for brief/prompt drafts that aren't code-executing.
- Option B: branch `slugs-v9-fold` + PR #13 + B2 APPROVE + merge. Higher rigor.

**Lean (A)** — prompt draft editing has no CI risk, and the fold is mechanical. Commit message cites v9 source of truth.

### Reviewer

B2 delta if (B). Self-review if (A), with commit message making the diff legible.

### Timeline

~20-30 min (scan + rename + verify + commit).

### Dispatch back

> B3 SLUGS-V9-FOLD landed — `KBL_B_STEP5_OPUS_PROMPT.md` + `scripts/present_signal.py` at commit `<SHA>`. All `mo-vie` → `mo-vie-am`, `theailogy` {replaced with m365 | dropped}, hot.md blocks synced to v9 state.

---

*Posted 2026-04-18 (late afternoon) by AI Head. Small fold. Director's slugs.yml v9 is the source of truth at `/Users/dimitry/baker-vault/slugs.yml`.*
