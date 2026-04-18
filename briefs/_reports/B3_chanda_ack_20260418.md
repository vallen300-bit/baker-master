# B3 CHANDA.md Acknowledgment

**Read at commit:** `915f8ad`
**Timestamp:** 2026-04-18 10:00 UTC
**Author:** Code Brisen 3

---

## The three legs in my own words

1. **Compounding (Leg 1)** — When the pipeline compiles a Silver entry for a matter, it must first read every Gold entry already in that matter's wiki. Skipping this means each new entry is written against a blank slate; depth never accrues. For my prompt-engineering work, this binds **Step 5/6 prompts** (Opus / Sonnet synthesis) — they consume `wiki/<matter>/*.md` Gold as input context. Step 1 doesn't carry this leg directly; Steps 5/6 do.

2. **Capture (Leg 2)** — Every Director action against a card (promote, correct, ignore, ayoniso decision) writes a row to the feedback ledger ATOMICALLY. If the ledger row write fails, the Director-facing action returns failure. This binds the UI / API layer where Director actions originate. For my work, it binds **Step 7 commit semantics** and the Cockpit interaction layer — neither of which I've drafted, but I must NOT design rules elsewhere that allow a Director action to land without a corresponding ledger row.

3. **Flow-forward (Leg 3)** — Step 1 reads `hot.md` AND the feedback ledger on EVERY pipeline run. Not cached, not periodic, every run. This is the leg my Step 1 triage prompt MUST satisfy and currently does not. See compliance audit §3 below.

---

## Invariants most likely to bind my typical work

- **Inv 1** — Gold-read-before-Silver. Binds Step 5/6 prompt builders. My Step 1/3/0 work doesn't compile Silver, but my fixture #4/#5/#6/#8 expectations should reflect this — Step 5 OPUS firing in those fixtures must include reading prior `wiki/<matter>/*.md` files into Opus's context.
- **Inv 3** — Step 1 reads hot.md + ledger every run. **My Step 1 triage prompt currently violates this.** See §3.
- **Inv 4** — `author: director` files never modified by agents. Binds wiki write logic in Step 7. My Layer 0 rules don't write files, so OK there; but my fixture #6 Phase-2 commit-path note about wiki updates needs an explicit "do not touch `author: director` headers" assertion.
- **Inv 7** — Ayoniso alerts are prompts, not overrides. Binds the alert-routing layer (not yet drafted by me). My Layer 0 noise-drop rules are NOT ayoniso alerts (they're deterministic noise filtering before any LLM sees the signal); a clarifying paragraph in the Layer 0 draft would prevent confusion.
- **Inv 10** — Pipeline prompts do not self-modify. Learning is through data. My Step 1 prompt's dynamic slug-registry sourcing IS data-driven (registry is data, not prompt edit), so OK. My Layer 0 rules-as-YAML is human-edit, not self-modifying, so OK.

---

## Compliance audit of my prior deliverables

### Step 1 triage prompt (`KBL_B_STEP1_TRIAGE_PROMPT.md` @ commit `cd8abab`)

**Inv 1 (Gold-read):** Not directly applicable — Step 1 doesn't compile Silver, it triages. Step 5/6 carry Inv 1.

**Inv 3 (hot.md + ledger every run):** **VIOLATED.** ❌

The prompt builder `build_step1_prompt(signal_text)` only reads slug registry. It does NOT load:
- `~/baker-vault/wiki/hot.md` — Director's current-priorities cache
- The feedback ledger (recent N rows of Director actions on past triage outputs)

Both are required by Leg 3 / Inv 3 verbatim: *"Step 1 reads `hot.md` AND the feedback ledger on every pipeline run."*

**Specific gap:** the prompt template `_STEP1_TEMPLATE` should include a `{hot_md_block}` and `{feedback_ledger_recent}` placeholder, and the builder should load both at call time. Without this, Director's current focus (e.g., "Hagenauer schlussabrechnung this week is everything") can't influence triage scoring, and prior corrections (e.g., Director re-classifying `mrci → null`) don't propagate to similar future signals.

**Why this matters for the loop:** Without ledger-read, Step 1 keeps making the same mistakes. Without hot.md-read, Step 1 can't elevate triage scores for Director's currently-pressing matters even when content alone reads as routine.

**Recommended remedy (NOT applied — flagging only per task instructions):**

```python
def build_step1_prompt(signal_text: str) -> str:
    slugs   = active_slugs()
    glossary = "\n".join(f"  {s.ljust(maxw)}— {describe(s)}" for s in slugs)
    hot_md  = _load_hot_md()                        # NEW — reads ~/baker-vault/wiki/hot.md
    ledger  = _load_recent_feedback(limit=20)       # NEW — last 20 Director actions
    return _STEP1_TEMPLATE.format(
        signal=signal_text.replace('"', "'")[:3000],
        slug_glossary=glossary,
        hot_md_block=hot_md or "(no current-priorities cache available)",
        feedback_ledger_recent=_render_ledger(ledger) or "(no recent Director actions)",
    )
```

And the template needs two new sections explaining how the model should USE hot.md and ledger context — without those, the model receives the data but doesn't know it's a steering signal for triage_score and matter selection.

**Will await dispatch to apply** the remedy. Patching now would skip the Q1 Loop Test discussion — this is the core of Leg 3 and warrants AI Head review, not a unilateral B3 patch.

### Step 3 extract prompt (`KBL_B_STEP3_EXTRACT_PROMPT.md` @ `5c8ba37` after S1 fix)

**CHANDA conflict:** None direct.

Step 3 is mechanical entity extraction. It doesn't compile Silver (Inv 1), doesn't decide alerts (Inv 7), doesn't modify Director files (Inv 4). The prompt is data-driven (no self-modification — Inv 10 OK).

**Soft observation:** extraction quality affects Step 5 Silver-compilation quality, so Inv 1's binding of Step 5 indirectly cares about Step 3 output. But the prompt itself is invariant-clean.

### Step 0 Layer 0 rules (`KBL_B_STEP0_LAYER0_RULES.md` @ `6341b94`)

**Inv 7 (ayoniso alerts are prompts, never overrides):** No conflict, but **needs clarifying paragraph.** Layer 0 is a deterministic noise filter (drops newsletters, garbled ASR) BEFORE any LLM call. It is not an "alert" mechanism. The risk in CHANDA terms is silent overrides — Layer 0 drops things Director never sees. The current draft mitigates via:
- VIP sender allowlist (§3.1)
- Topic override (§3.2 invariant #4)
- 1-in-50 sampling for Director spot-check (§3.3)

These are good but the draft should EXPLICITLY state "Layer 0 is not an alert; alerts are Inv 7-bound and live elsewhere in the pipeline. Layer 0 silent-drops are bounded by the §3 safeguards."

**Inv 4 (author: director files never modified):** Layer 0 doesn't write files at all (only updates `signal_queue.state`). So no direct binding. **One adjacent concern:** Director-originated content (Dimitry sending himself an email, Director writing a note that re-enters as a signal) must NEVER be Layer-0-dropped. My current rules cover this implicitly (Director's own dvallen@brisengroup.com is not on any blocklist), but the draft would benefit from an explicit `email_sender_in_director_addresses` never-drop invariant alongside the existing scan / VIP / pre-tagged / slug-mention invariants.

**Inv 10 (no self-modifying prompts):** N/A — Layer 0 has no LLM call. YAML rules are human-edit data, not self-modifying code. Clean.

### §10 test fixtures (`KBL_B_TEST_FIXTURES.md` @ `742f4a1`)

**Loop compliance vs mechanical compliance:** **PARTIAL — mostly mechanical.**

The fixtures verify that signals flow through Steps 0-7 with the right per-step outputs. They do NOT verify that the Learning Loop legs are exercised. Specifically:

- **Leg 1 missing:** No fixture asserts that Step 5 Opus reads `wiki/<matter>/*.md` Gold before drafting. Fixtures #4, #5, #8 just say "Opus fires" — they should also assert "Opus's input context includes `wiki/hagenauer-rg7/*.md`" (or similar by-matter Gold load).
- **Leg 2 missing:** No fixture exercises a Director action that triggers a feedback-ledger write. The end-to-end test should include at least one fixture where a hypothetical Director action ("Director promotes Silver to Gold on the wiki entry produced by fixture #4") is asserted to write a ledger row. Without this, Leg 2 is not pytest-covered.
- **Leg 3 missing:** No fixture asserts Step 1 reads hot.md + ledger. Once the Step 1 prompt is patched (per §3 above), fixtures #3, #4, #5, #8 should additionally assert: "Step 1 builder loads hot.md and recent feedback ledger before invoking the model."

**Recommended remedy:** add a "Loop Compliance" row to each fixture card. Will apply in next dispatch if AI Head wants the fixtures upgraded; for now flagged only.

---

## Pre-push checklist I now run before every draft

- [ ] **Q1 Loop Test passed** — does this change preserve all three legs (Compounding / Capture / Flow-forward)? If touches Step 1 read pattern, ledger write, or Step 5/6 Gold-read → STOP, flag to AI Head.
- [ ] **Q2 Wish Test passed** — does this serve the wish (compounding human judgment via machine throughput) or engineering convenience? Convenience-only → STOP, flag. Both → state the tradeoff in the commit body.
- [ ] **Inv 4 check** — does this change touch any `author: director` file? If yes → STOP.
- [ ] **Inv 10 check** — does this change introduce any prompt that modifies itself or other prompts based on runtime data? Data-driven prompt builders (registry, hot.md, ledger) are OK; LLM-rewriting-prompts is NOT.

---

## Questions / tensions surfaced

1. **Step 1 prompt lacks hot.md + feedback-ledger integration — Inv 3 violation.** Most important finding of this audit. Flagged in §3 above. Awaiting AI Head dispatch to author the patch (involves new helper functions `_load_hot_md`, `_load_recent_feedback`, `_render_ledger`, plus a template-rewrite that explains to the model how to USE the steering data).

2. **Fixtures don't exercise the loop.** §10 fixtures pass mechanically through Steps 0-7 but never assert that Leg 1 (Step 5 reads matter Gold), Leg 2 (Director action → ledger row), or Leg 3 (Step 1 reads hot.md + ledger) actually fire. Pytest as I've spec'd it would happily green while the Learning Loop is broken. Awaiting AI Head dispatch to upgrade fixtures with Loop-Compliance rows.

3. **CHANDA §1 says "the wiki is the interest-bearing account"** — that framing implies the Step 7 commit semantics matter enormously (it's the deposit mechanism). My fixtures only specify `target_vault_path` template, not the interest-bearing properties (wiki entry frontmatter completeness, cross-link pointer integrity, source-ID round-trippability). KBL-B §7 will land these; my fixtures should align once §7 is canonical.

4. **No tension with any invariant — but a question on Inv 10 scope:** "Pipeline prompts do not self-modify. Learning is through data." My Step 1 prompt's `slug_glossary` string is BUILT from `slug_registry.describe()`. When SLUGS-2 lands and `edita`/`russo` split, the prompt string changes — but the prompt CODE / TEMPLATE doesn't change, only the data interpolated into it. Confirming: this is data-driven, not self-modification, and complies with Inv 10. Asking for AI Head confirmation that this reading is correct and that my dynamic-glossary design pattern is canonical.

5. **CHANDA invites critique** — I have one. The §5 Q1/Q2 tests are excellent guardrails for new work but are silent on **legacy work brought in from elsewhere** (other repositories, prior eval artifacts, vendor SDK examples). My Step 1 prompt is partly inherited from v1/v2/v3 eval prompts which predated CHANDA. The audit just caught one Inv 3 gap — there could be others in code I haven't authored that imports my drafts. Suggest: when CHANDA evolves (§6), add a §7 covering "audit cadence for legacy / inherited work." Not urgent; flagging for the next CHANDA edit.

---

*Filed by Code Brisen 3, 2026-04-18 10:00 UTC. Two non-trivial flags raised: Step 1 Inv 3 violation + §10 fixture loop-compliance gap. Both await AI Head dispatch to remedy. Returning to standby per D1 ratification posture.*
