# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** Three-task delivery complete (Step 1 amend, §10 loop compliance, Fireflies search). All standing for B2 review / Director ruling.
**Task posted:** 2026-04-18
**Status:** OPEN

---

## Task: LAYER0-RULES-S1-S6 — Apply B2's 6 Should-Fix Items to Step 0 Layer 0 Rules

**Why now:** B2's Step 0 Layer 0 review (commit `e0f38ab`) returned READY with 6 should-fix items. Applying them parallel to their queue review cycles. Also addresses the 2 clarifying additions your own CHANDA audit recommended (explicit "not an alert" paragraph + Director-sender never-drop invariant).

### Source material to read

- `briefs/_reports/B2_step0_layer0_rules_review_20260418.md` — B2's review with all 6 items + architectural notes
- Your own CHANDA ack flags on Step 0 rules from `briefs/_reports/B3_chanda_ack_20260418.md` (2 clarifying items)

### Scope

**IN — B2's 6 should-fix items:**

1. **S1 — YAML relocation.** Move rule content from `baker-master/kbl/config/layer0_rules.yml` to `baker-vault/layer0_rules.yml`. Rationale per B2: matches SLUGS-1 precedent, Director edit path, no code redeploy, mirrors slug_registry loader pattern. Update your draft's file-path references to reflect the vault location. (B1 already built the loader pointing to `$BAKER_VAULT_PATH` — your relocation + their loader = integrated.)

2. **S2 — `baker_self_analysis_echo` anchor tightening.** Current spec catches phrases like *"I asked Baker"* in natural text. Re-anchor on Baker's actual storage-layer marker. B2 suggests: `baker_scan:` prefix in signal metadata, or `<!-- baker-output -->` frontmatter tag. Pick one, spec explicitly, add rationale.

3. **S3 — Topic-override alias awareness + short-slug safeguard.** Replace `_mentions_active_slug` naive split-0 match with `slug_registry.aliases_for()`. For slugs <4 chars (`mo-vie`, `ao`, `mrci`), require alias match not canonical-only match (prevents false whole-word matches like "ao" in arbitrary text).

4. **S4 — VIP soft-fail CLOSED not OPEN.** Your current draft says "Step 1 will be backstop" — but Layer 0 drops are terminal; signal never reaches Step 1. Flip to soft-fail-CLOSED (treat as VIP during VIP-service downtime — drops no one) OR document trade-off explicitly. Flip is simpler.

5. **S5 — Hash store spec.** 72h dedupe hash was referenced but undefined. Spec:
   - Table: `kbl_layer0_hash_seen` (already created by B1 in PR #5 / about to merge; schema: `content_hash PK TEXT, first_seen_at TIMESTAMPTZ, ttl_expires_at TIMESTAMPTZ, source_signal_id BIGINT, source_kind TEXT`)
   - Cleanup tick: cron-driven DELETE WHERE `ttl_expires_at < now()` on daily schedule
   - Normalization function: specify exactly what's normalized before hashing — lowercase, trim, strip trailing whitespace per line, collapse multiple spaces to one, drop standard sig blocks (`--\n...`) OR not — pick a deterministic recipe
   - Hash algorithm: sha256 hex
   - Cite in spec so B1's later impl matches your intended behavior

6. **S6 — Review queue spec.** Sampling without surfacing = noise. Spec:
   - Table: `kbl_layer0_review` (already created by B1 in PR #5)
   - Sampling rate: 1-in-50 dropped signals get a row (deterministic via signal.id % 50 == 0, or random-choice — pick one + justify)
   - Excerpt field: first 500 chars of payload content
   - Director review UI: out of scope for this draft (KBL-C owns the cockpit); spec only the DB-writer side
   - Review verdict values: `correct_drop`, `false_positive`, `ambiguous`

**IN — Your own CHANDA-audit clarifications (2 items):**

7. **C1 — "Not an alert" paragraph.** Add explicit clarifying paragraph: Layer 0 is a deterministic pre-LLM noise filter. It is NOT an alert mechanism (Inv 7 covers ayoniso alerts separately). Layer 0 drops are logged, 1-in-50 sampled for Director review per S6. Director does not receive a notification per drop.

8. **C2 — Director-sender never-drop invariant.** Add: signals where sender is Director (email from `dvallen@brisengroup.com`, `vallen300@gmail.com`, or WhatsApp from Director's number) are NEVER dropped by Layer 0, regardless of content shape. Rationale: Director's own queries / scan-throughs / test signals are always intended; Layer 0 must respect authorial intent.

**OUT**
- Re-opening the YAML+dispatcher pattern (B2 ratified as right shape)
- Re-opening D3 §247 10-30% drop rate ratification
- Rule implementation Python code (KBL-B Step 0 impl, separate ticket)
- Running any eval

### CHANDA pre-push self-check

- **Q1 Loop Test:** Layer 0 is UPSTREAM of loop reading (filter before Step 1). Rule changes don't modify Leg 1/2/3 mechanism. Pass.
- **Q2 Wish Test:** each item serves operational clarity / correctness / Inv-compliance. State tradeoff if any item has a convenience angle.
- **Inv 7 compliance:** C1 explicitly clarifies Layer 0 ≠ alert mechanism. No conflict.
- **Inv 4 compliance:** C2 preserves Director's authorial authority. No conflict.

### Reviewer

B2 (reviewer-separation). This cycles Step 0 Layer 0 through B2 twice, consistent with iterative review of same file.

### Timeline

~45-60 min for all 8 items.

### Dispatch back

> B3 Step 0 Layer 0 S1-S6 + C1-C2 applied — commit `<SHA>`. 8 items resolved. Ready for B2 re-review.

---

## Status after this task

You're clear. Director-ruling on Hagenauer candidate + hot.md content are parallel-tracking separately (Director's own session). Next B3 dispatch depends on B2 verdicts returning from their expanded queue.

---

*Posted 2026-04-18 by AI Head. B1 parallel-running LOOP-HELPERS-1 (PR #6). B2 working 4-review queue. Production-moving density held across all three agents.*
