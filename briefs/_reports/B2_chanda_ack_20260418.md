---
title: B2 CHANDA Ack + Prior-Review Audit
voice: report
author: code-brisen-2
created: 2026-04-18
---

# B2 CHANDA Ack + Prior-Review Audit

**From:** Code Brisen #2
**To:** AI Head (cc: Director)
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) Task C
**CHANDA file:** [`CHANDA.md`](../../CHANDA.md) @ commit `915f8ad` (promoted 2026-04-18 11:44 CEST)
**Prior reviews scanned:** 17 reports under `briefs/_reports/B2_*.md`
**Date:** 2026-04-18
**Time:** ~25 min

---

## 1. Acknowledgment

Read CHANDA.md end-to-end. Internalized §2 Learning Loop, §3 Invariants 1-10, §5 Pre-Push Test (Q1 Loop + Q2 Wish), §4 Iddhipāda ownership matrix.

The reviewer-separation matrix I operate under is the **Vīmaṃsā instrument** (Director's investigation arm) for code/design — independent reads on whether what got built matches the wish. My job is to fail loud at the Q1/Q2 boundary so Viriya/Citta drift gets caught before it compounds.

### What §2 means for me

The three legs are the only thing that distinguishes "system that runs" from "system that learns." When reviewing any change touching Leg 1 (Gold-read), Leg 2 (ledger-write atomicity), or Leg 3 (Step 1 reads hot.md + ledger every run), I flag **explicitly** — not as a should-fix, as a structural call-out. Same posture as my Step 6 scope challenge: if a step looks like it could degrade a leg, default to BLOCK until the rationale is on paper.

### What §3 means for me

Invariants 1-10 are non-negotiable. An "engineering reason to bend Inv N" is a **flag-to-Director moment**, not a REDIRECT I authorize on my own. My verdict authority is bounded by the invariants — APPROVE/REDIRECT live inside them; anything that touches them goes BLOCK + escalation note in the report body.

The two I expect to touch most often:
- **Inv 1** (Gold-read before Silver, zero-Gold IS zero-Gold): every loader/helper review checks zero-Gold sentinel paths
- **Inv 3** (Step 1 reads hot.md AND ledger every run): every Step 1 prompt + helper review checks for caching, missing reads, fallback-to-stale
- **Inv 10** (pipeline prompts don't self-modify; learning is through data): every prompt-touching review confirms helpers are read-only

### What §5 means for me

Q1 Loop Test runs **before** Q2 Wish Test. If a change touches the reading pattern (Leg 1), the ledger-write mechanism (Leg 2), or the Step 1 integration (Leg 3), the review must:
1. Cite the leg explicitly
2. Confirm Director pre-approval if intent is to modify it
3. Verify the authorization trail (dispatch → ratification) in the change description

Q2 catches convenience-driven changes that pass Q1 vacuously. Both must be cited where applicable.

---

## 2. Audit method

For each of the 17 prior B2 reviews:
1. Tag as **pre-CHANDA** (commit before `915f8ad` 11:44 CEST 2026-04-18) or **post-CHANDA**
2. Identify which CHANDA legs/invariants the change-under-review touches
3. Check whether the report cited the relevant CHANDA framing
4. Flag any reasoning that would conflict with CHANDA today

### Temporal split

| Cohort | Count | Files |
|---|---|---|
| **Pre-CHANDA-promote** | 9 | schema_fk_reconciliation, slugs1, pr1, pr1_reverify, skeleton, kbl_b_phase2, pr3, kbl_b_step1_step3_prompts, step0_layer0_rules (original) |
| **Post-CHANDA-promote** | 8 | step6_scope_challenge, pr4, pr5, pr5_delta, pr6, chanda_compliance_fold_review, step0_layer0_rules_rereview, step1_fixture14_rereview |

Pre-CHANDA reviews could not have cited the §5 Q1/Q2 framework — it didn't exist in the repo. Audit standard for those: did the **reasoning** align with what CHANDA later codified? Post-CHANDA reviews are held to the §5 citation standard.

---

## 3. Per-review audit

### Pre-CHANDA cohort (9 reviews)

| Report | Touched CHANDA surface? | Hindsight conflict? |
|---|---|---|
| `B2_schema_fk_reconciliation_20260417.md` | Inv 2 (ledger-write atomicity, schema-side) | **Soft drift, not a conflict.** I approved KBL-A's per-table `REFERENCES … ON DELETE SET NULL` as the right FK posture. PR #5 (post-CHANDA) chose **app-side validation, no PG FK** for the loop infrastructure tables, with explicit "Inv 2 atomicity preserved at writer boundary" rationale. Both stances are defensible at their times; the schema philosophy evolved between KBL-A and KBL-B/loop. Worth flagging as architectural drift, not a violation of either-era CHANDA. |
| `B2_slugs1_review_20260417.md` | Inv 4 (`author: director` files), Inv 5 (frontmatter) by adjacency (slugs.yml is in baker-vault) | None. SLUGS-1 added `slug_registry` reading from baker-vault; my approval included pattern-fidelity check against vault read shape. No agent writes to author:director files in SLUGS-1. ✓ |
| `B2_pr1_review_20260417.md` (KBL-A impl) | None directly — KBL-A is infrastructure (cron, env, secrets, gold-promote tick). The `gold_drain` mechanism it ships is **upstream of Leg 1** but doesn't read Gold itself. | None. My BLOCKER (env-var plumbing) and 5 should-fix items were operational, not architectural. |
| `B2_pr1_reverify_20260417.md` | Same as above | None. APPROVE on 10/10 fixes; no reasoning subject to CHANDA hindsight. |
| `B2_kbl_b_skeleton_review_20260418.md` (04:05 — pre-CHANDA-promote by ~7h) | **Touches the legs heavily** — defines the 8-step pipeline that Legs 1-3 are embedded in. | **Directionally CHANDA-aligned, not a conflict.** My B1 (Step 4 redundant LLM) finding has the same shape as my later Step 6 REDIRECT: don't add LLM ceremony to a step with no LLM-shaped semantic work. Both serve §2 (the wish for human-owned interpretation, machine where deterministic) and don't violate any Inv. The Step 4 finding pre-figured CHANDA's "convenience vs wish" Q2 test. ✓ |
| `B2_kbl_b_phase2_review_20260418.md` (07:27 — pre-CHANDA) | Touches Leg 1 (Gold-read in §4-5 contracts), Leg 2 (ledger-adjacent status migration) | None. My 3 blockers were per-step contract issues (`advance_stage` raises on terminal states; etc.) — operational, not loop-degrading. |
| `B2_pr3_review_20260418.md` (TCC install fix) | None | n/a — shell installer, no pipeline surface. |
| `B2_kbl_b_step1_step3_prompts_review_20260418.md` (09:16 — pre-CHANDA-promote by ~2h) | **Leg 3 directly** (Step 1 prompt design) — but at this point hot.md/ledger reads weren't yet wired into the Step 1 prompt. Q1/Q2 mentioned in this report refer to per-prompt OQs, **not CHANDA §5 tests** (false positive in my grep). | None — Leg 3 wiring landed later via the Inv-3 amend (`773f8c5`) and PR #6. My §6 review of the un-Inv-3-aware draft was correct at the time. |
| `B2_step0_layer0_rules_review_20260418.md` (09:38 — pre-CHANDA-promote by ~2h) | Inv 4 (author:director never modified — yml is config, not author:director), Inv 5 (frontmatter — n/a, layer 0 is pre-frontmatter) | None. My 6 should-fix items (S1 vault location, S2 baker-scan anchor, S3 alias-aware match, S4 VIP soft-fail closed, S5 hash store, S6 review queue) are all operational hardening, not loop-touching. The post-CHANDA re-review explicitly added C1 (Layer 0 ≠ alert layer, clarifies Inv 7 boundary) and C2 (Director-sender invariant) — cleanly extends, doesn't violate. ✓ |

**Pre-CHANDA cohort verdict:** **0 hindsight conflicts.** One soft drift (FK-vs-app-validation philosophy) worth recording.

### Post-CHANDA cohort (8 reviews)

| Report | Legs/Invs touched | Cited CHANDA? | Hindsight verdict |
|---|---|---|---|
| `B2_step6_scope_challenge_20260418.md` (12:02) | **Inv 6** (pipeline never skips Step 6) | Implicit — verdict preserves Step 6 in pipeline (deterministic, no LLM call). Doesn't cite CHANDA §5 by name. | **No conflict. Inv 6 satisfied** — Step 6 still fires, runs Pydantic validation + cross-link writes. The 8-step taxonomy is preserved; only the model dependency is dropped. Director ratified. ✓ Could have cited §5 Q2 (Wish Test: removing the LLM call serves the wish — no semantic work was happening) explicitly — soft retroactive flag. |
| `B2_pr4_review_20260418.md` (12:14) | None directly (pure-loader for Layer 0 rules) | ✓ Explicit: "CHANDA: no invariants violable in a pure-loader. ✓" | ✓ Clean. |
| `B2_pr5_review_20260418.md` (12:28) + delta (13:21) | **Leg 2** (feedback_ledger schema enables atomic ledger writes) | ✓ §5 of report is "CHANDA compliance" with explicit Inv 2 atomic-write loop verification | ✓ Clean. The S1 (`review_verdict` CHECK) finding hardens Inv 2 vocabulary. The BIGSERIAL delta cleanly preserves Leg 2 admittance. |
| `B2_pr5_delta_review_20260418.md` (13:03 — content folded into pr5_review §10) | Leg 2 (BIGSERIAL upgrade for FK type compatibility) | Implicit (continuation of pr5_review's CHANDA section) | ✓ |
| `B2_pr6_review_20260418.md` (13:06) | **Leg 1** (`load_hot_md`), **Leg 3** (`load_recent_feedback`, `render_ledger`) — the helpers Step 1 will compose | ✓ §5 explicit: Inv 1 zero-Gold sentinels verified per-surface; Inv 10 read-only pure-helper pattern | ✓ Clean. The 5 zero-Gold sentinel paths fully verified. Strong CHANDA posture. |
| `B2_chanda_compliance_fold_review_20260418.md` (13:11) | **Leg 3** (Inv 3 explicit fold into Step 1 prompt) | ✓ Cites §5 Q1 + Q2 by name with authorization trail audit | ✓ The reference example for how a Leg-touching review should look. |
| `B2_step0_layer0_rules_rereview_20260418.md` (13:26) | Inv 4 (author:director — Layer 0 yml is config, not author:director — clean), Inv 7 (alerts vs filter-layer — C1 clarification) | Implicit. C1 + C2 clarifications cited at the invariant level. | ✓ Clean. C1 explicitly distinguishes Layer 0 from the alert layer (Inv 7 boundary clarified, not crossed). |
| `B2_step1_fixture14_rereview_20260418.md` (13:33) | **Leg 3** (Step 1 reads hot.md + ledger; cross-matter elevation rule) | ✓ Cites the Q1 Loop Test authorization trail propagation from prior CHANDA-fold review. Verifies the env-var name, single-shot guard, and hard-assert loop compliance. | ✓ Clean. The S1-rereview env-var typo is operational hygiene, not a loop violation. |

**Post-CHANDA cohort verdict:** **0 conflicts.** One soft retroactive flag: my Step 6 scope challenge could have explicitly cited Q2 Wish Test framing (the "convenience vs wish" lens) — the substance is there, the citation is implicit. Future Inv 6-touching reviews should cite §5 by name.

---

## 4. Hindsight findings

### F1 — Schema-philosophy drift between KBL-A (pre-CHANDA) and PR #5 (post-CHANDA)

KBL-A schema (which I approved in `B2_schema_fk_reconciliation_20260417.md`) used PG-enforced FKs (`REFERENCES signal_queue(id) ON DELETE SET NULL`). PR #5 (post-CHANDA) chose app-side validation with no PG FK, citing CHANDA Inv 2 atomicity preserved at the writer boundary.

**Both stances were defensible at their respective times.** KBL-A predates the Inv 2 articulation; PR #5's stance is the CHANDA-codified posture. The drift is real but doesn't represent a hindsight conflict — KBL-A's tables are append-only too, and the FK enforcement is additive (one more safety net), not contradictory.

**Pre-flag for AI Head:** if KBL-A schema and KBL-B/loop schema ever need to be reconciled into a unified migration framework, the FK posture should be made consistent. Lean toward PR #5's stance (app-side validation; PG FK adds locking-under-ingest cost without proportionate integrity benefit for append-only ledgers).

### F2 — §5 Q1/Q2 citation discipline below standard in 6 of 8 post-CHANDA reviews

Of my 8 post-CHANDA reviews, only 1 (`chanda_compliance_fold_review`) cites Q1 Loop Test + Q2 Wish Test by name. The other 7 cite invariants directly (Inv 1, Inv 2, Inv 3, Inv 10) and the substance is right, but the §5 framework is implicit, not explicit.

**This is the working finding from this audit.** Going-forward standard: any review touching Leg 1, Leg 2, or Leg 3, or any Inv-1-10 surface, **explicitly cites §5 Q1/Q2** in the verdict summary. Not as ceremony — as an audit trail Director can scan to verify the gate fired.

### F3 — Two early reports have implicit zero-Gold reasoning that should be explicit going forward

`B2_pr1_review_20260417.md` and `B2_kbl_b_phase2_review_20260418.md` review code that handles missing-data states (env-var unset, status-migration corner cases). My approvals were operationally correct, but the **zero-Gold framing** (missing input is a valid state, not a failure) wasn't named. CHANDA Inv 1 makes this framing canonical.

**No backtracking needed** — the code shipped correctly. Just naming the lens going forward.

### F4 — One soft retroactive flag on Step 6 scope challenge

`B2_step6_scope_challenge_20260418.md` is the most consequential review I've authored — it triggered the Director-ratified REDIRECT that AI Head is now folding into KBL-B. It correctly preserves Inv 6 (Step 6 still fires, just deterministic). But the verdict body relies on Q2 Wish Test reasoning (convenience vs wish: Sonnet polish was cargo-culted convenience, not a wish-serving design) without naming Q2 explicitly. CHANDA §5 framing would have made the rationale tighter.

---

## 5. Going-forward review posture (commitments)

1. **§5 citation discipline.** Every review touching Leg 1/2/3 or Inv 1-10 cites Q1 Loop Test + Q2 Wish Test by name in the verdict summary. Format: "§5 Q1 Loop Test: <leg N affected? authorization trail?>; §5 Q2 Wish Test: <serves wish / convenience / both?>"
2. **Authorization trail audit.** When a change to Leg 1/2/3 is the **intent** (not a side effect), the report verifies the dispatch → Director pre-approval chain in the source mailbox/dispatch commit before APPROVE/REDIRECT.
3. **BLOCK as the default verdict on Inv 1-10 violations.** Even if the code "works," any change that admits a path violating an invariant gets BLOCK + escalation-to-Director note. My verdict authority does not include bypassing the invariants.
4. **Pre-flag F1 (schema philosophy)** when reviewing future schema migration work — confirm whether the change holds to PR #5's app-side-validation stance or reverts to KBL-A's PG-enforced-FK stance.
5. **Pre-CHANDA reviews not retroactively rewritten.** They're correctly scoped to their era; the audit serves to inform forward review posture, not to amend the historical record.

---

## 6. Summary

- **CHANDA read end-to-end:** ✓
- **§2 Learning Loop, §3 Invariants 1-10, §5 Q1/Q2 framework internalized:** ✓
- **17 prior B2 reviews audited:** 9 pre-CHANDA, 8 post-CHANDA
- **Hindsight conflicts:** **0** (zero violations, zero recommendations to retract)
- **Soft drifts noted:** 1 (F1 schema philosophy KBL-A → PR #5)
- **Citation-discipline gaps:** F2 (6 of 8 post-CHANDA reviews cite invariants but not §5 framework explicitly); F3 (2 early reports have implicit zero-Gold framing); F4 (Step 6 scope challenge could have cited Q2 Wish Test by name)
- **Going-forward commitments:** 5 (§5 citation discipline, authorization trail audit, BLOCK on Inv violations, F1 pre-flag, no retroactive rewrites)

The audit confirms my prior reviews are CHANDA-coherent in substance. The discipline gap is in citation explicitness, not in reasoning. Going forward, every review touching Leg 1/2/3 or Inv 1-10 will cite §5 Q1/Q2 by name.

CHANDA is now load-bearing for my verdict authority. Any change that would break a leg or violate an invariant gets BLOCK + flag-to-Director, not REDIRECT.

---

*Authored 2026-04-18 by Code Brisen #2. CHANDA.md @ `915f8ad` read end-to-end. 17 prior B2 reports under `briefs/_reports/B2_*.md` audited. No code changes; ack + audit only.*
