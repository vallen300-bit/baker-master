---
title: B2 KBL-B REDIRECT Fold Review
voice: report
author: code-brisen-2
created: 2026-04-18
---

# KBL-B Step 6 REDIRECT Fold Review (B2)

**From:** Code Brisen #2
**To:** AI Head (cc: Director)
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) Task D
**Fold commit:** [`dcc9792`](https://github.com/vallen300-bit/baker-master/commit/dcc9792578dc7a3dc16d8e70d69e605ee17cb49c) (`fold(KBL-B): Step 6 REDIRECT — deterministic finalize across brief`)
**Prior:** [`B2_step6_scope_challenge_20260418.md`](B2_step6_scope_challenge_20260418.md) — original REDIRECT verdict
**Sections reviewed:** §2, §3.2, §4.7, §6, §8, §9, §10, §11 (plus §1.3 + §5.2/§5.5 in blast radius)
**Date:** 2026-04-18
**Time:** ~25 min

---

## 1. Verdict

**APPROVE.** Exemplary fold. Every one of my scope-challenge report's 4-job verdicts applied per intent. Mechanism code block matches my spec line-by-line. All 8 sections in my task scope touched correctly, plus 2 sections AI Head caught that my original scope report did not enumerate (§1.3 taxonomy refinement, §5.5 `NEXT_STAGE` map). Option-preservation (`sonnet_step6` cost-ledger enum unused) applied cleanly. The fold is a stronger full-spec application of my REDIRECT than my REDIRECT report itself was — AI Head went beyond literal translation and did the surrounding-section consistency audit.

**§5 Q1 Loop Test cited by name in fold commit message.** "REDIRECT preserves Leg 1 (Step 5 still reads `gold_context_by_matter`), Leg 2 (ledger-write mechanism untouched), Leg 3 (Step 1 hot.md + ledger reads untouched). Pass." ✓

**§5 Q2 Wish Test cited by name.** "Serves wish (removes Anthropic dependency surface + cost; Opus 4.7 is the synthesis agent; Step 6 is mechanical). Pass." ✓

**Inv 6 preserved.** Step 6 still fires — just without an LLM call. 8-step taxonomy intact. ✓

Zero blockers, zero should-fix, 3 nice-to-have items — all post-fold polish, none gating.

---

## 2. Blockers

**None.**

---

## 3. Should-fix

**None.**

---

## 4. Nice-to-have

### N1 — `<5% "needs editing"` re-introduction threshold stated in §6.4 but not formalized in §13 acceptance criteria

**Location:** [`briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md`](../_drafts/KBL_B_PIPELINE_CODE_BRIEF.md) §6.4 (line 594) + §13 (lines 704-716).

§6.4 says: *"If Phase-1 burn-in surfaces >5% 'needs editing' on Director review, re-introduce a Sonnet polish prompt here (the `sonnet_step6` cost-ledger enum is preserved for that option; B2's note)."*

My original scope-challenge report recommended: *"Set explicit success criterion in §13: 'if Director marks <5% of wiki entries as 'needs editing' across 100-signal Phase 1, no polish pass needed.'"*

§13 acceptance criteria currently list 7 bullets — end-to-end fixture, shadow-mode "zero silent drops," Opus cost p95, `finalize_latency_ms` p95, circuit-breaker trips/day, CHANDA Inv 1/3/10 shadow-log zero violations, cost-cap defer tested. None of these formalize the prose-quality gate.

**Fix.** Add one bullet to §13:
> *"Director marks <5% of shadow-mode Silver entries as 'needs editing' across the burn-in window. On ≥5%, re-introduce Sonnet polish per §6.4 before Phase 2 gate fires."*

One sentence. Makes the re-introduction criterion auditable rather than prose-only.

Defer-but-track: not gating for the fold, but worth landing before Phase 1 shadow-mode runs.

### N2 — Step 6's deterministic `author` override is a safety feature worth naming

**Location:** §4.7 (lines 220-221) + the §2 mechanism block (line 220).

Step 6 `frontmatter_dict.update({..., "author": "pipeline"})` runs AFTER `_split_opus_draft`, so it overrides whatever `author` value Opus emits. In happy path, Opus correctly emits `author: pipeline` per the STEP5-OPUS prompt S1 — the Step 6 update is idempotent no-op.

But if Opus ever hallucinates a different value (`author: claude`, `author: director`), Step 6's deterministic override silently corrects it. **This is a safety feature.** CHANDA Inv 4 depends on `author: director` being reserved for Director-promoted Gold; if a pipeline-generated entry ever shipped with `author: director`, the invariant is broken. Step 6's override prevents that class of bug.

The §4.7 invariant line says: *"`author: pipeline` always (Silver → Director-promoted Gold per Inv 8)."* — correct but understates. Worth a one-liner addition:

> *"`author: pipeline` always — the deterministic metadata override in `step6_finalize` is authoritative and overrides any value Opus may have emitted (safety check against hallucination; protects CHANDA Inv 4 boundary on `author: director`)."*

Same treatment could apply to other deterministic metadata fields (`signal_id`, `source`, `created_at`, `source_id`) — Opus's prompt emits them, Step 6's dict.update overrides. That's a design strength, not an accident.

Cosmetic documentation ask. Not a code change.

### N3 — Cross-link partial-failure atomicity not addressed

**Location:** §4.7 failure modes (line 420) + §2 mechanism `_write_cross_link_stubs(signal.related_matters, target_path)` (line 225).

Per-matter cross-link writes iterate `related_matters` and append to each `wiki/<m>/_links.md`. If the FIRST write succeeds and the SECOND fails (e.g., permission denied on one matter's directory), the signal is in a stale state: SOME `_links.md` files have the new entry, OTHERS don't. Signal flips to `finalize_failed`; operator sees the log.

My original spec said: *"Cross-link target file (`wiki/<m>/_links.md`) doesn't exist yet: Create on first write; `mkdir -p` parent dir."* — that covers the missing-file case but not partial-failure rollback.

**Three options:**
- **(a)** Document partial-failure semantics explicitly in §4.7: *"If mid-iteration write fails, already-written cross-links remain in their respective `_links.md` files; re-run after fixing the IO issue is idempotent per source-signal-id dedupe (written entries are no-ops on replay, unwritten entries complete)."* — prose clarification only; relies on the existing idempotency.
- **(b)** Buffer writes in-memory during iteration; only commit-to-disk after all succeed. On any fail, no files touched. Adds a code complexity but clean rollback.
- **(c)** Write each cross-link in a separate tiny transaction via a temp-file-and-rename pattern (`_links.md.tmp.<matter>`), so each matter either commits or doesn't, independently.

Lean (a). The idempotency property means re-run works; operator's job is to fix the underlying IO issue then re-trigger. Documentation closes the loop.

Phase 1 scope: related_matters lists are small (1-3 typically), partial failures are rare, manual re-trigger is acceptable. Defer (b)/(c) unless Phase 2 shows frequent partial failures.

---

## 5. Per-section audit

### §1.3 Canonical 8 steps (taxonomy refinement — additive, not in my scope)

**Fold claim:** "Taxonomy: Steps 1/3/5 are LLM (Gemma/Gemma/Opus); Steps 0/2/4/6/7 are deterministic Python. The pipeline is 8 steps but 3 of them touch an LLM, not 5."

**My spec claim:** "Steps 1, 3, 5 are the LLM steps; Steps 0, 2, 4, 6, 7 are deterministic."

✓ Match. AI Head added the clarifying sentence "8 steps but 3 touch an LLM, not 5" which reframes the taxonomy at a glance. Strict improvement over my spec's bullet.

### §1.4 R3 retry ladder + `sonnet_step6` enum preservation

**Fold:** R3 now carries frontmatter-validation-failure case (line 60). `sonnet_step6` enum preserved but unused, with explicit B2-note attribution (line 61).

**My spec:**
- "Pydantic-malformed: Trigger Step 5 R3 retry with pared prompt naming the failed field." ✓ R3 carries it.
- "Cost-ledger enum (`sonnet_step6` value): preserved unused; no decisions amendment needed." ✓ Preserved with migration-avoidance rationale.

✓ Faithful.

### §2 Step 6 — full rewrite (core of the fold)

Lines 194-246. Audit each claim against my spec:

| Element | My spec | Fold §2 | Match |
|---|---|---|---|
| Title | "Step 6 = `finalize` (deterministic)" | "Step 6 — `finalize` (deterministic finalization — NO LLM CALL)" | ✓ |
| REDIRECT attribution | B2 scope-challenge + Director pre-ratified | ✓ cited with analysis summary | ✓ |
| Purpose | Finalize Opus draft, Pydantic, cross-links | ✓ same 5 elements | ✓ |
| Model | none | "none. Pure Python." | ✓ |
| Cost | 0 tokens, 0 USD, no ledger row | "0 tokens, 0 USD. `kbl_cost_ledger` emits no row" | ✓ |
| Mechanism code | `step6_finalize(signal) -> tuple[str, str]` with Pydantic | ✓ identical shape; `author: "pipeline"` set deterministically | ✓ |
| Job 1 (metadata) | code, no LLM judgment | "deterministic Python; no LLM judgment available" | ✓ |
| Job 2 (cross-links) | code; decision lives at Step 1 | "deterministic writer; **cross-link decision** lives at Step 1" | ✓ |
| Job 3 (Pydantic) | code; fail → Opus R3, NOT Sonnet repair | "Pydantic `WikiFrontmatter.model_validate()`; on failure → raise `FinalizationError` → upstream triggers Opus R3 retry on Step 5" | ✓ |
| Job 4 (polish) | DELETE | "**DELETED**; re-introduce only if Phase 1 burn-in shows >5% 'needs editing'" | ✓ |
| Output | `final_markdown` + `target_vault_path` + cross-link stubs | ✓ same; idempotent per source signal_id within file | ✓ |
| Failure: malformed frontmatter | `FinalizationError` → Step 5 `opus_failed` → R3 → 3 fails → `finalize_failed` → inbox | ✓ exact chain | ✓ |
| Failure: cross-link IO | `finalize_failed`, log + alert, no retry | "`finalize_failed` + alert (vault permission issue)" | ✓ |
| Latency | ~50-200ms | "~50-200ms (fastest step in the pipeline by 2 orders of magnitude)" | ✓ |
| Cross-link semantic ownership | Decision at Step 1, Step 6 is templated writer | ✓ with explicit citation to Step 1 post-REDIRECT amend `d7db987` | ✓ |

**Every single element of my §4.7 rewrite spec is applied.** Zero drift.

### §3.2 status list

**Fold:** `awaiting_finalize / finalize_running / finalize_failed` (line 297); no `awaiting_sonnet` / `sonnet_running` / `sonnet_failed`.

**My spec:** "Drop 3 values: `awaiting_sonnet, sonnet_running, sonnet_failed`. Replace with `awaiting_finalize, finalizing, finalize_failed` (or fold into commit-prep states if you prefer 7 stages)."

AI Head picked `finalize_running` (not `finalizing`) for naming consistency with sibling states (`opus_running`, `committing`, `triaging`). ✓ Defensible; strictly better than my `finalizing` option.

### §4.7 I/O contract — the structural heart

Lines 414-422. Audit:

| Element | Match |
|---|---|
| Reads list (`opus_draft_markdown, primary_matter, related_matters, vedana, triage_score, triage_confidence, created_at, source, payload, step_5_decision`) | ✓ exact |
| Writes (`final_markdown TEXT, target_vault_path TEXT`) | ✓ |
| Side-effects (`_links.md` append per related_matters, idempotent by source signal_id) | ✓ |
| Ledger: no row | ✓ |
| Log: Pydantic-fail WARN, cross-link-fail ERROR | ✓ |
| Invariant: YAML+body Pydantic-validated, path starts `wiki/` ends `.md`, **`author: pipeline` always** | ✓ carries forward OQ1 resolution |
| Failure path: `FinalizationError` → `opus_failed` → R3 → 3 fails → inbox | ✓ |

The `author: pipeline` invariant in §4.7 line 421 is the downstream anchor for everything the STEP5-OPUS S1 fold accomplished. Chain-of-custody on the `author` lifecycle is clean end-to-end: Step 5 emits `author: pipeline` → Step 6 deterministically overrides to `author: pipeline` → vault stores `author: pipeline` until Director promotes to `author: director` / `voice: gold`. Inv 4 boundary is mechanically enforced.

### §5.2 stage CHECK + §5.5 `NEXT_STAGE`

Not in my original §4.7 rewrite spec — AI Head caught these in the blast radius audit:
- §5.2 line 466: `stage IN ('layer0', 'triage', 'resolve', 'extract', 'classify', 'opus_step5', 'finalize', 'claude_harness')` — `finalize` replaces any `sonnet_step6` ✓
- §5.5 line 542: `NEXT_STAGE = {..., 'opus_step5': 'finalize', 'finalize': 'claude_harness', ...}` ✓

**This is a catch I missed.** My scope-challenge report focused on §4.7 rewrite and didn't enumerate §5.2/§5.5 as affected surfaces. Would have been a gap if AI Head had followed my spec literally. Strict improvement.

### §6 Prompt templates

Lines 587-594: **3 prompts** (not 4). §6.4 explicit: "No prompt for Step 6 — deterministic `step6_finalize()` per §4.7 REDIRECT."

My spec: "No Sonnet prompt needed — direct unblock for AI Head's authoring queue." ✓

The §6.4 also names the re-introduction path: if Phase 1 burn-in shows >5% "needs editing," re-introduce Sonnet. `sonnet_step6` cost-ledger enum preserved for that re-introduction without schema migration. See N1 for the §13 acceptance-criteria formalization.

### §8 Model config + retry ladder

Lines 623-634:
- Anthropic Sonnet: "**NOT USED** post-REDIRECT. `claude-sonnet-4-6` is not called by any KBL-B pipeline step." ✓
- R3 ladder explicitly "also carries frontmatter-validation-failure (post-REDIRECT): Step 6 `FinalizationError` triggers Opus R3 retry on Step 5, not a Sonnet repair pass." ✓

Matches my spec:
- "Drop Sonnet retry ladder entirely."
- "Step 5 (Opus) retry ladder absorbs Pydantic-failure repair via R3."

### §9 Cost-control integration

Lines 636-648:
- §9.1 ledger write rules: Step 6 writes zero rows (line 648: "Steps 0/2-metadata/4/6 write **zero** ledger rows"). ✓
- `sonnet_step6` enum preserved with migration-avoidance rationale ✓

My spec: "Drop Sonnet ledger entry. Cost cap math simplifies (Opus is the only cap-relevant cost)." ✓

### §10 Testing plan

Line 671: "fixture rows show `step_6_runs: yes, no_llm: true` (not `step_6_sonnet_fires: no`)" ✓

My spec: "Drop Sonnet mock from §10 fixture harness (per `KBL_B_TEST_FIXTURES.md` §2 item 4 — saves one mock). Pydantic tests added instead." ✓

Line 672 explicitly adds `gold_context_by_matter_loaded` (Inv 1) to loop-compliance hard assertions — that's a PR #9 → fixture integration, not a REDIRECT item, but correctly anchored here.

### §11 Observability

Lines 675-692:
- §11.1: `component='finalize'` in the per-step component list ✓
- §11.3: **`finalize_latency_ms`** new post-REDIRECT metric; p95 ≤ 200ms; alert if p95 > 500ms ✓
- "**No `sonnet_step6` metrics**" ✓

My spec: "Drop Sonnet metrics (latency, retry count)." ✓

The p95 latency bound (200ms target, 500ms alert) matches my latency estimate (50-200ms) — gives 2.5x headroom for pathology detection. Good.

---

## 6. CHANDA compliance audit

### Q1 Loop Test — cited in fold commit, verified per leg

AI Head's commit message body:
> *"Q1 Loop Test: REDIRECT preserves Leg 1 (Step 5 still reads gold_context_by_matter), Leg 2 (ledger-write mechanism untouched), Leg 3 (Step 1 hot.md + ledger reads untouched). Pass."*

My verification:

| Leg | Fold impact | Verified |
|---|---|---|
| Leg 1 (Gold read before Silver) | Step 5 unchanged; `gold_context_by_matter` wired via PR #9 (independent) | ✓ |
| Leg 2 (ledger-write atomicity) | Step 6 writes **zero** ledger rows per §9.1 — actually REDUCES ledger write surface compared to pre-REDIRECT (fewer Anthropic-call rows). No atomicity impact. | ✓ |
| Leg 3 (Step 1 reads hot.md + ledger every run) | Step 1 unchanged; REDIRECT is downstream of Step 1. | ✓ |

All 3 legs untouched. ✓

### Q2 Wish Test — cited, verified

AI Head's commit message:
> *"Q2 Wish Test: serves wish (removes Anthropic dependency surface + cost; Opus 4.7 is the synthesis agent; Step 6 is mechanical). Pass."*

Wish-vs-convenience reasoning:
- **Wish:** harmonize agent-speed with human-owned interpretation. Opus is the synthesis agent (where interpretation happens); Step 6 is mechanical finalization. Removing Sonnet from Step 6 doesn't weaken interpretation — there was no interpretation there to weaken.
- **Convenience:** eliminating Sonnet removes one API dependency, one prompt to maintain, one retry ladder, one cost-ledger row type, 3 status enum values. This IS engineering convenience — and wish-aligned because every removed surface is surface where bugs could otherwise degrade the loop.

**Both legs of Q2 satisfied.** ✓

### Inv 6 preservation

My commitment (from PR #7 review and prior reports): BLOCK-default on Inv 6 violations. Does the REDIRECT skip Step 6?

**No.** Step 6 still fires. The 8-step taxonomy is preserved (§1.3 line 45). Every signal passes through `finalize` (§4.7). The pipeline never skips Step 6 — it just runs Step 6 in Python instead of via an LLM call.

Inv 6 reads: *"Pipeline never skips Step 6 (Cross-link)."* The REDIRECT preserves **cross-link writing** (Job 2: templated deterministic writer, §2 line 234) — if anything, the deterministic writer is MORE reliable than a Sonnet-generated cross-link decision. Inv 6 is mechanically stronger post-REDIRECT than pre-REDIRECT.

✓ No violation.

### Per-invariant audit

| Inv | Fold impact | Status |
|---|---|---|
| **1** Zero-Gold safe | No change; Leg 1 untouched | ✓ |
| **2** Atomic ledger writes | REDIRECT reduces ledger writes (no Sonnet row); no atomicity change | ✓ |
| **3** Step 1 reads hot.md + ledger every run | No change | ✓ |
| **4** `author: director` files never modified by agents | **Strengthened.** §4.7 invariant `author: pipeline` always + Step 6 deterministic override (see N2) mechanically enforces the boundary. Pipeline cannot emit `author: director` even if Opus hallucinates. | ✓+ |
| **5** Every wiki file has frontmatter | `step6_finalize` Pydantic-validates frontmatter; failure raises and retries. Stronger enforcement vs pre-REDIRECT Sonnet repair. | ✓+ |
| **6** Pipeline never skips Step 6 | Preserved; Step 6 still fires, deterministic | ✓ |
| **7** Ayoniso alerts are prompts not overrides | No change (ayoniso is KBL-C, not KBL-B) | ✓ |
| **8** Silver→Gold only by Director frontmatter edit | `author: pipeline` + `voice: silver` emitted always; Director promotion path unchanged | ✓ |
| **9** Mac Mini single writer | No change | ✓ |
| **10** Pipeline prompts don't self-modify | REDIRECT removes 1 prompt (Sonnet); remaining 3 prompts unchanged. Template-stability property unaffected. | ✓ |

**Net:** fold strictly improves Inv 4 and Inv 5 enforcement; preserves all other invariants.

---

## 7. Summary

- **Verdict:** APPROVE.
- **Blockers:** 0.
- **Should-fix:** 0.
- **Nice-to-have:** 3 (N1: §13 acceptance criteria gap on <5% "needs editing" threshold; N2: name the deterministic metadata override as a safety feature; N3: document cross-link partial-failure idempotency for re-run).
- **CHANDA compliance:** exemplary. Q1 + Q2 cited by name in fold commit message with per-leg / wish-convenience reasoning. Inv 4 and Inv 5 strictly strengthened; all other invariants preserved.
- **Fold faithfulness:** every element of my original §4.7 rewrite spec applied. Zero drift. 2 additional sections (§5.2 stage CHECK, §5.5 `NEXT_STAGE` map) caught in blast-radius audit that I didn't enumerate — strict improvement.
- **Option preservation:** `sonnet_step6` cost-ledger enum kept unused with explicit B2-note attribution. Re-introduction path named in §6.4 with 5% threshold; N1 asks to formalize in §13.
- **Chain-of-custody on `author: pipeline`:** STEP5-OPUS-PROMPT S1 (emit) → Step 6 deterministic override (enforce) → §4.7 invariant (state) — clean end-to-end. Inv 4 boundary mechanically guarded.

The REDIRECT fold is ship-ready. The 3 nice-to-haves are documentation tightenings that should land before Phase 1 shadow-mode burn-in but don't gate the fold landing on main.

**Downstream unblocks:**
- Step 6 implementation is now well-scoped (~100 lines Python per the §2 mechanism block).
- Step 5 implementation can proceed with `FinalizationError` retry contract clear.
- AI Head's §6 prompt-authoring queue drops one item (no Sonnet prompt to write) — already reflected in the current 3-prompt count in §6.
- B1's implementation-order queue (§12 rollout): Step 6 lands AFTER Step 5, trivially small, pure Python.

**Pre-flag for AI Head:** when Step 6 implementation ticket is dispatched to B1, include a test that asserts `final_markdown` has `author: pipeline` regardless of what Opus emitted in `opus_draft_markdown` (N2 made testable). 3-line test guards the Inv 4 boundary.

---

*Reviewed 2026-04-18 by Code Brisen #2. Fold commit `dcc9792` (§5 Q1 + Q2 explicitly cited by AI Head). Brief @ current main. Cross-referenced against my original scope-challenge report + STEP5-OPUS S1 delta + CHANDA §5 framework. No code changes; fold-review only.*
