# B3 CHANDA-Compliance Fold Review (B2)

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) Task B — batched review of B3's two-part Inv-3 + §10 loop-compliance amendment package
**Files reviewed:**
- Part 1: `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md` (commit `773f8c5` — Inv 3 amendment)
- Part 2: `briefs/_drafts/KBL_B_TEST_FIXTURES.md` (commit `f47e9a5` — §10 loop-compliance fold)
**Cross-referenced:** PR #6 `kbl/loop.py` (just reviewed @ `6c23d36`); my prior Step 1/3 prompts review; my prior scope-challenge report (REDIRECT verdict)
**Date:** 2026-04-18
**Time spent:** ~35 min

---

## 1. Verdict

**Part 1 (Step 1 prompt): REDIRECT** — 2 should-fix items, both small surface, both inline-appliable.
**Part 2 (§10 fixtures): APPROVE** — exemplary loop-compliance fold. Hard-assert pattern is exactly the right shape; one cross-link to Part 1's S1 fix.

The package as a whole is structurally sound — B3 understood Inv 3 in depth and produced fixtures that go beyond "pipeline ran" to "loop fired with measurable effect." The Part 1 issues are coordination misses (one with AI Head's OQ3 resolution, one with B1's actual `kbl/loop.py` API), not architectural problems.

CHANDA §5 Q1 + Q2 tests cited explicitly with authorization trail. ✓

---

## 2. Part 1 — Step 1 prompt amendment

### 2.1 Blockers

**None.**

### 2.2 Should-fix

#### S1 — Cross-matter elevation rule missing despite AI Head OQ3 ratification

**Location:** §1.2 "How to use `hot.md`" rules (lines 115-120); §6 OQ6 (line 377).

**The conflict.** AI Head's OQ3 answer to B3 (from the task brief): *"YES. Hot.md watch-list matters elevate triage_score if ANY extracted entity matches, not only primary_matter. ... if B3's draft doesn't handle this, flag as should-fix for Task B redirect."*

B3's §1.2 rules check only `primary_matter`:
> *"If the signal's primary_matter appears in hot.md as actively pressing, ELEVATE triage_score by 0.15..."*

B3's §6 OQ6 explicitly defers:
> *"Could expand to 'elevate by 0.10 if primary_matter OR any related_matters is on hot.md ACTIVE.' Deferred — risk of over-elevation noise; ship with primary-only logic for Phase 1."*

B3's deferral was authored before AI Head's OQ3 ratification reached B3. Per task brief, AI Head's resolution wins and the prompt should expand.

**Fix.** Two related changes:

1. **Rule update (§1.2).** Replace the bullet:
   > *"If the signal's primary_matter appears in hot.md as actively pressing, ELEVATE triage_score by 0.15 (cap at 100)."*
   
   with:
   > *"If the signal's primary_matter OR any extracted entity (slug found in `related_matters`, or any matter slug appearing as a whole word in the signal text) matches a hot.md ACTIVE entry, ELEVATE triage_score by 0.15 (cap at 100). Apply the elevation once per signal even if multiple matches occur — don't double-stack."*
   
   Same shape change for the FROZEN suppression rule.

2. **§6 OQ6 update.** Mark RESOLVED-by-AI-Head, not deferred. Document the over-elevation-noise mitigation: "single-shot elevation, no stacking" handles B3's original concern.

**Pairing with Part 2.** A matching fixture is needed to verify the cross-matter behavior. Either expand Fixture #11 (currently tests primary-matter elevation only) with a "Phase 2: cross-matter case" sub-scenario, OR add Fixture #14: signal where primary is OUT of hot.md but a `related_matters` entry IS on ACTIVE list. The behavioral assertion (`triage_score_observed` band-check + `triage_score_summary_cites_hot_md`) carries over directly. Cross-link this in the §10 amendment when S1 lands.

#### S2 — `kbl/loop.py` API mismatch (helper-function name)

**Location:** §1.1 builder code, §1.4 helper signatures.

B3's builder calls `render_ledger_block(ledger_rows)`. B1's actual `kbl/loop.py` (PR #6 @ `6c23d36`, just reviewed) ships `render_ledger(rows)` — no `_block` suffix. Same goes for the `load_recent_feedback` signature: B3's §1.4 says `def load_recent_feedback(limit: int = 20) -> list[dict]`; B1's actual implementation is `def load_recent_feedback(conn: Any, limit: Optional[int] = None) -> list[dict]` — takes a `conn` argument that B3 doesn't pass.

If §1.1's builder is copy-pasted into `kbl/prompts/step1_triage.py` as-is, **it crashes on first call**:
- `ImportError: cannot import name 'render_ledger_block'` — function doesn't exist
- `TypeError: load_recent_feedback() missing 1 required positional argument: 'conn'`

**Fix.** Three small edits to §1.1 + §1.4:

1. Rename `render_ledger_block` → `render_ledger` everywhere (one ref in §1.1 import, one in §1.1 call, one in §1.4 spec)
2. Add `conn` parameter handling: builder needs to acquire a psycopg2 conn (or take it as a builder arg). Either pattern:
   - **(a)** `build_step1_prompt(signal_text: str, conn: Any) -> str` — caller owns conn
   - **(b)** Builder uses a module-level conn pool (acceptable if KBL-B impl wires one)
3. Update §1.4 to mirror B1's actual signatures verbatim: drop the helper-signature spec entirely and replace with a one-line pointer (`See kbl/loop.py for canonical signatures — these are the production helpers, not illustrations`)

This is a coordination miss between B3's draft and B1's PR #6 (which landed concurrently). Not a design issue — just synchronization. (a) is cleaner; (b) requires KBL-B impl to expose a pool primitive that doesn't yet exist. Lean (a).

### 2.3 Nice-to-have

#### N1 — Elevation rule wording: "0.15" is unitless

§1.2: *"ELEVATE triage_score by 0.15 (cap at 1.00 / score 100)"*

Worked Example A demonstrates `50 + 0.15 × 100 = 65` — so 0.15 is a fraction-of-full-scale, multiplied by 100 to add to score. But the rule reads ambiguously: a model could interpret "by 0.15" as adding 0.15 directly (50 → 50.15) or as 15% relative (50 → 57.5).

The worked example clarifies, but the rule itself is the model-facing prompt — clearer to write *"ELEVATE triage_score by 15 points (e.g., 50 → 65, capped at 100)"*. Same for ±0.10 suppression: *"SUPPRESS triage_score by 10 points"*.

#### N2 — `triage_confidence` rubric updated for hot.md/ledger reinforcement

§1.2 rubric for `triage_confidence ≥ 0.9`: *"clear matter + clear vedana, hot.md AND/OR ledger reinforced your choice."*

This adds reinforcement as a confidence-boost lever. Reasonable, but unverified empirically (D1 tested confidence without hot.md/ledger context). Worth flagging as "post-Phase-1 calibration item" in §6 — same posture as the existing OQ2.

#### N3 — Worked Example B contradicts labeled set

§1.5 Example B explicitly notes: *"This MAY contradict the labeled-set ground truth for that specific row. ... the ledger wins for production triage. ... The labeled set wins for D1 measurement; production decisioning is a separate runtime concern."*

This is the right posture, but it implies that **Phase 1 production triage will diverge from D1 measurement** in cases where the ledger has already corrected. Worth an explicit note in §5 (cost estimate) or §6 (open questions): "expect divergence between live production accuracy and re-eval accuracy as the ledger compounds. Re-evals on the labeled set are a snapshot of the LLM, not a measure of the loop."

#### N4 — Inv 3 read on Layer-0-dropped signals

The prompt builder fires `load_hot_md()` + `load_recent_feedback()` even when Step 0 has dropped the signal? Let me check the call graph:

- Step 0 (`layer0`) runs deterministic rules on signal_queue rows; on drop, sets `state='dropped_layer0'` and stops the pipeline.
- Step 1 (`triage`) only fires if Step 0 didn't drop.
- `build_step1_prompt()` is called inside Step 1 only.

So `load_hot_md` + `load_recent_feedback` fire only when Step 1 fires. Layer-0-dropped signals don't read hot.md / ledger. **This is correct** per the §10 fixtures (#1, #2 mark `hot_md_loaded` as N/A for drops). Fixture coverage matches builder behavior.

Just confirming — no fix needed. Worth noting in §1.1's docstring: *"This builder is invoked by Step 1 only. Layer 0 drops bypass this entirely (no hot.md/ledger read for dropped signals)."* Cosmetic clarification.

### 2.4 Confirmations

| Item | Status |
|---|---|
| Inv 3 (read on every Step 1 call) | ✓ §1.1 builder reads both; comment forbids caching explicitly |
| Inv 1 (zero-Gold safe) | ✓ both reads have None/[] sentinel handlers; "(no current-priorities cache available)" + "(no recent Director actions)" placeholders |
| Post-REDIRECT cross-link weight | ✓ §1.2 explicit: *"Step 6 is a deterministic finalization step (REDIRECT, ratified 2026-04-18). It does NOT re-evaluate or expand your cross-link choices."* |
| Authorization trail (CHANDA §5 Q1) | ✓ §1.3 cites B3 ack `e9eb04e` → AI Head dispatch `3c78f8c` → Director pre-approval explicit |
| Q2 Wish Test | ✓ §1.3 second paragraph addresses both legs (compounding judgment + reproducibility) |
| Empirical baseline preserved | ✓ §2.1 v3 levers retained; §2.2 changes table extends, doesn't replace |
| Worked examples corpus-grounded | ✓ Examples A/B/C drawn from labeled set (Constantinos drawdown style, MRCI line 23, EH letter line 8) |
| Token/latency estimates realistic | ✓ +800 tokens → +1-3s on Gemma 8B is consistent with prior measurements |
| Cost telemetry additions (hot_md_chars, ledger_rows_count) | ✓ Smart operational hygiene |
| Prior B2 review S2 (retry semantics) | ✓ §3 row 1 explicit reference: "(B2 review S2 fix, 2026-04-18)" |

### 2.5 CHANDA §5 Q1 Loop Test — citation audit

§1.3 cites the test explicitly:
> *"Q1 Loop Test: This change DIRECTLY MODIFIES Leg 3 (Step 1's reading pattern). ... Director pre-approved amend-now at the prior turn ... This commit is the remedy, not a new deviation. Authorization trail: B3 ack identified gap → AI Head dispatched amend-now → Director pre-approval explicit in dispatch language."*

Q2 Wish Test:
> *"This change serves the wish (compounding judgment via machine throughput → Step 1 must read what Director has decided + currently cares about) AND engineering convenience (it makes Step 1 self-contained / reproducible per signal). Both legs of Q2 satisfied."*

Both tests passed with citations. Authorization is clean.

---

## 3. Part 2 — §10 fixtures loop-compliance amendment

### 3.1 Blockers

**None.**

### 3.2 Should-fix

**None.**

### 3.3 Nice-to-have

#### N1 — Cross-link to Part 1 S1 (cross-matter elevation fixture)

If/when Part 1 S1 lands (cross-matter elevation rule), a matching fixture is needed. Two options:
- **(a)** Add Fixture #14: signal where `primary_matter` is OUT of hot.md ACTIVE list but a `related_matters` entry IS on it. Assert `triage_score` band shows the elevation fired via the cross-matter path.
- **(b)** Expand Fixture #11 with a Phase-2 sub-scenario testing the cross-matter case.

Either is fine. (a) is cleaner separation; (b) keeps fixture count tighter. Defer the call until Part 1 S1 is resolved.

#### N2 — Mock Ollama for Fixtures #11 + #12 must be loop-aware

§2 item 2: *"For #11, #12: mock must produce hot-md-aware / ledger-aware outputs (not just replay v3); see Loop Compliance assertions for the model behavior expected."*

This is correct. But it's a real implementation effort — the mock can't just `replay_recorded_response(signal_id)`; it needs to inspect the prompt, detect hot.md presence, and modulate the score accordingly. Worth flagging the implementation cost: the §10 implementer will need either:
- A scripted mock that returns hardcoded canned responses per fixture (tightly coupled to fixture content)
- A live Gemma run for #11/#12 (defeats the mock's purpose for fast tests)
- A "smart mock" that interprets the prompt structure (most robust, most work)

Recommend: scripted mock per fixture. Document this in §2 item 2 explicitly so the §10 implementer doesn't underestimate scope.

### 3.4 Confirmations

| Item | Status |
|---|---|
| Loop Compliance tables on every fixture #1-#13 | ✓ verified |
| Hard-assert posture (§2.A) | ✓ explicit: "pytest treats Loop Compliance rows as hard assertions, not soft checks" |
| Fixture #11 (hot.md elevation) tests behavior, not just presence | ✓ `triage_score_observed` band-check + `triage_score_summary_cites_hot_md` |
| Fixture #12 (ledger correction propagation) tests behavior | ✓ `primary_matter_observed=null` overrides v3 baseline `mrci`; `triage_summary_cites_ledger` |
| Fixture #13 (zero-Gold first-signal case) guards against optimization | ✓ `step5_did_NOT_skip_gold_load` hard-assert |
| Inv 3 reads asserted on all Step-1-firing fixtures | ✓ #3-#13 all assert `hot_md_loaded TRUE` + `feedback_ledger_queried TRUE` |
| Inv 1 reads asserted on zero-Gold cases | ✓ #5 (Phase 2 wertheimer first signal), #13 (synthetic isolated case) |
| Leg 2 deferral to separate atomicity test file | ✓ §7 explicit: "Director-action ingress is upstream of Step 0 ... Leg 2 belongs in a separate `tests/test_feedback_ledger_atomicity.py` suite" |
| Source distribution still representative | ✓ #11 WhatsApp-style, #12 email, #13 WhatsApp — matches 50-signal corpus mix |
| New harness needs documented (§2 items 7-10) | ✓ hot.md content fixture, ledger pre-seeding helper, wiki-dir wipe helper, assert_loop_compliance helper |

### 3.5 Leg 2 boundary call — agree

B3 parks Leg 2 atomicity tests to `tests/test_feedback_ledger_atomicity.py`. Per §7:
> *"Director-action ingress is upstream of Step 0 (Cockpit / API / Scan). Leg 2 belongs in a separate ... suite, not the end-to-end pipeline fixtures."*

**Agreed.** Three reasons:
1. **Different test surface.** §10 pipeline fixtures test the read-heavy data flow Steps 0→7. Leg 2 atomicity tests the write-side transaction boundary (`BEGIN; INSERT INTO feedback_ledger; <primary effect>; COMMIT;` — atomic or both fail). Different harness needs (real PG transaction vs mocked clients).
2. **Different consumer.** Leg 2 writers live in KBL-C (Cockpit endpoints, API, Scan handlers) — none in KBL-B. Testing them inside KBL-B's §10 forces premature coupling.
3. **Better fault isolation.** A bug in `feedback_ledger` write atomicity should fail an atomicity test, not a pipeline fixture. Mixing them dilutes which suite owns which class of failure.

The risk of this deferral: Leg 2 testing could fall through the cracks if no KBL-C ticket explicitly owns it. **Pre-flag for AI Head:** confirm the KBL-C/Cockpit ticket inventory has a `test_feedback_ledger_atomicity.py` deliverable.

### 3.6 Worked example fidelity

§1.5 Examples A/B/C in Part 1 → matched to Fixtures #11/#12/#? in Part 2:
- Example A (Constantinos drawdown + hot.md elevation) ↔ Fixture #11 ✓ same scenario, same expected behavior
- Example B (MRCI Saldenliste + ledger correction) ↔ Fixture #12 ✓ same scenario, same expected behavior
- Example C (zero-Gold baseline EH letter) ↔ no direct fixture (it's a baseline, doesn't need a separate fixture beyond the existing #4)

The Part 1 worked examples and Part 2 fixtures are coherent. ✓

---

## 4. Token/latency cost validation

§5 Part 1 estimate:
- Prompt tokens: ~1500-1900 (was ~900-1100). Worst case +900.
- Latency: ~7-18s/call (was ~6-15s). +1-3s.

**Cross-checked against PR #6 fixture sizes:**
- `tests/fixtures/hot_md_sample.md` — 8 lines, ~750 chars, ~190 tokens
- 20 ledger rows at ~100 chars each ≈ 2000 chars ≈ 500 tokens

So worst-realistic is ~900 token addition (10× hot.md size + verbose ledger). Estimate is conservative but plausible. ✓

Latency: Gemma 8B local on macmini at temp=0 with prompt-caching disabled (Ollama doesn't cache) processes ~150 tokens/s. +700-900 tokens × 150/s ≈ +5-6s upper bound. B3's +1-3s estimate may underestimate worst case; flag for Phase-1-close re-measurement. **Not a blocker** — even +5s/signal × 50 signals/day = 4 min/day cumulative, easily absorbed.

---

## 5. Per-OQ resolution audit

| AI Head OQ resolution | B3 Part 1 application | B3 Part 2 application |
|---|---|---|
| OQ1 hot.md schema for Phase 3 | DEFER — §6 OQ4 says "Recommend Director adopts a 3-bucket convention now" | n/a |
| OQ2 ledger sampling beyond 20 | env-var (`KBL_STEP1_LEDGER_LIMIT=20`) — §1.4 spec + §6 OQ5 | n/a |
| OQ3 cross-matter elevation | **MISSED** — §1.2 still primary-only; §6 OQ6 still says "deferred" | **MISSED** — no cross-matter fixture |

OQ3 miss is the only S1. OQ1 + OQ2 applied correctly.

---

## 6. Summary

| Part | Verdict | Blockers | Should-fix | Nice-to-have | Confirmations |
|---|---|---|---|---|---|
| Part 1 (Step 1 prompt) | **REDIRECT** | 0 | 2 (cross-matter elevation; loop.py API mismatch) | 4 | 11 |
| Part 2 (§10 fixtures) | **APPROVE** | 0 | 0 | 2 | 11 |

**Cross-cutting:** S1 fix in Part 1 should land alongside a matching Part 2 fixture (N1 in Part 2). Both can land in the same revision touch.

**CHANDA compliance:**
- §5 Q1 + Q2 tests both cited with authorization trail (Part 1)
- Inv 1 zero-Gold reads enforced via behavioral assertions (Part 2 #5, #13)
- Inv 3 hot.md + ledger reads enforced on every Step-1-firing fixture (Part 2 #3-#13)
- Inv 10 (template stability) preserved — helpers read only, no template mutation (verified in PR #6 review)
- Leg 2 atomicity correctly scoped out — separate test file boundary

**Coordination flags:**
- Part 1 S2 is a name mismatch with B1's PR #6 — landed concurrently, neither party saw the other's commit. Merge-window artifact, not a design issue.
- Part 1 S1 is the only design-level miss — AI Head's OQ3 ratification didn't propagate to B3's draft.
- Pre-flag for AI Head: confirm KBL-C/Cockpit ticket inventory has explicit `test_feedback_ledger_atomicity.py` ownership so Leg 2 doesn't fall through the cracks.

The package is mergeable after Part 1's two should-fixes. The Loop Compliance hard-assert pattern in Part 2 should set the convention for all future §10-style fixture suites — it's the right shape for pinning architectural invariants at test time.

---

*Reviewed 2026-04-18 by Code Brisen #2. Cross-checked against `kbl/loop.py` PR #6 @ `6c23d36` (just reviewed), `briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md` §4.2 + §4.5, and CHANDA §5 Q1/Q2 framework. No code changes; design + draft review only.*
