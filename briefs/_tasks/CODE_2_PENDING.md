# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous report:** [`briefs/_reports/B2_slugs1_review_20260417.md`](../_reports/B2_slugs1_review_20260417.md) — SLUGS-1 APPROVE, Director merging
**Task posted:** 2026-04-18
**Status:** OPEN — awaiting execution
**Supersedes:** SLUGS-1 review task (shipped)

---

## Task: KBL-B Skeleton Structural Review (§1-3 only)

### Purpose

I wrote the KBL-B pipeline skeleton at `briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md` @ commit `fb334f5`. It covers §1 purpose/scope, §2 8-step flow, §3 schema touches — about 500 lines. Per AI Head's own brief-quality discipline and the established review-then-ratify pattern (you deep-reviewed DECISIONS_PRE_KBL_A_V2 before Director ratified), this skeleton should get independent structural scrutiny before Director ratifies the 4 open asks at §end.

**Goal of this review:** catch architectural issues now, before I write §4-13 (~1500 more lines) on top of shaky foundations. The sooner a structural issue surfaces, the cheaper to fix.

### Why you, not B1 or B3

- You authored the KBL-A schema draft. You understand what schema shape real-world signal data takes and what `signal_queue` already carries.
- You reviewed DECISIONS_PRE_KBL_A_V2 — you have the ratified decisions indexed in your head.
- B1 is busy (pre-install verify + runbook). B3 is busy (D1 v3 eval).
- Reviewer-separation discipline: I wrote the skeleton; B2 (not me, not B1 the likely implementer) reviews.

---

## Scope

**IN — §1, §2, §3 only.** §4-13 are section outlines with empty bodies; no substantive content to review there yet.

- §1 Purpose + scope boundaries
- §2 8-step flow summaries (one paragraph per step: `layer0 → triage → resolve → extract → classify → opus_step5 → sonnet_step6 → claude_harness`)
- §3 Schema touches (10 new `signal_queue` columns, proposed stage+state CHECK split, optional `kbl_pipeline_run` table, indexes)
- The 4 "Asks of Director" at §end

**OUT**
- §4-13 empty outlines (nothing to review)
- The KBL-A brief itself (ratified, don't re-open)
- The ratified decisions (locked)
- D1 retry progress (B3's thread — independent)

---

## What to scrutinize

Think structurally, not nit-level. You're catching category errors, not typos. 5-10 strong critiques > 40 tiny nits.

### §1 Purpose / scope

- Is the IN/OUT split correct? Anything that KBL-B should own but is punted to KBL-C (or vice versa)?
- Is "KBL-B does NOT implement Layer 2 ALLOWED_MATTERS enforcement" actually true? §1.2 says it's a 1-line env check at Step 5 entry — do you agree, or is it bigger?
- Is the "~2000-3000 lines of Python across `kbl/steps/*.py`" estimate defensible given what KBL-A took?

### §2 Flow

- Are the 8 steps the right decomposition? In particular:
  - **Step 2 (resolve) via embeddings** — is this actually the right mechanism, or should it be lexical + metadata first with embeddings as a fallback? Voyage AI costs multiply across every signal.
  - **Step 3 (extract) separate from Step 1 (triage)** — I argued the split because Layer 0 drops before extract so extract costs less. You've seen real triage prompt JSON fields — would merging actually hurt throughput?
  - **Step 4 (classify) as a separate model call** — is this its own step, or can it be folded into Step 5's Opus prompt as a preamble section?
  - **Step 6 (Sonnet polish) separate from Step 5 (Opus)** — legitimate split, or over-engineered? Opus could self-produce vault-canonical frontmatter directly.

- Per-step I/O described at summary level. Any step whose output schema is *obvious* to you but I've left ambiguous?

- Failure modes: Step 5 `status=paused_cost_cap` re-queues for tomorrow. Does that interact correctly with KBL-A's circuit breaker? Or does the circuit breaker handle this case entirely and `paused_cost_cap` is dead state?

### §3 Schema

- **10 new `signal_queue` columns** — is this too much width on a hot queue table? Alternative: separate `signal_queue_step_outputs(signal_id, step, output_json)` keyed by step. What's the trade-off on read path (dashboard queries, resume semantics)?
- **Stage + state collapse** (§3.2): I proposed replacing a 24-value `status` CHECK with `stage TEXT` + `state TEXT` columns. Good idea or unnecessary churn? What does this do to existing queries that `WHERE status IN (...)`?
- **`kbl_pipeline_run` observability table** (§3.3): bike-shed — needed in KBL-B or pushable to KBL-C dashboard ticket?
- **Indexes**: is `GIN` on `resolved_thread_paths JSONB` actually performant for the queries we'd run, or should it be a normalized lookup table?
- **JSONB vs column**: `extracted_entities JSONB` — do you think some of the fields should be promoted to dedicated columns (e.g., `primary_money_amount NUMERIC`, `primary_deadline TIMESTAMPTZ`)?

### The 4 ratification asks at §end

Give your vote on each (as input to Director, not a deciding vote):

1. §1.2 scope boundary — confirm / redirect
2. §2 flow — confirm / redirect
3. §3.2 status collapse — yes / no
4. §3.3 `kbl_pipeline_run` — include / defer

State your position with one-paragraph reasoning each. Director reads yours + mine, then decides.

---

## Output format

File: `briefs/_reports/B2_kbl_b_skeleton_review_20260418.md`

Sections:

1. **Verdict:** READY FOR §4+ / REDIRECT NEEDED
2. **Blockers:** (category errors — things §4+ would have to unwrite if kept)
3. **Should-fix:** structural tightenings worth landing before Director ratifies
4. **Nice-to-have:** minor observations, nits, style
5. **The 4 ratification asks — your vote + reasoning**
6. **Open architectural questions:** things §1-3 doesn't address but §4-13 will need to — pre-flag them so AI Head can queue reader context for when those sections get written

Follow the pattern from your `B2_pr1_review_20260417.md` — structured, precise, actionable.

---

## Scope guardrails

- **Do NOT** propose specific prompt wordings (that's §6).
- **Do NOT** draft code (this is a design review, not implementation).
- **Do NOT** re-open the 15 ratified decisions. If you see conflict between §1-3 and a ratified decision, that's a blocker to report, not a reason to renegotiate the decision.
- **Do NOT** delay on "I'd need to see the prompt first" — if the architecture is right, the prompt can fit; if the architecture is wrong, no prompt saves it.

---

## Time budget

~30-45 min:

- 10 min read the skeleton + skim the decisions doc for affected sections
- 20 min scrutiny pass
- 10 min report writing

If you find yourself >1h in, stop + ship partial. Marginal returns.

---

## Dispatch back

Chat one-liner:

> B2 KBL-B skeleton review done — see `briefs/_reports/B2_kbl_b_skeleton_review_20260418.md`, commit `<SHA>`. Verdict: <READY | REDIRECT>. Votes on 4 asks: <y/y/y/y>.

---

*Dispatched 2026-04-18 by AI Head. Git identity: `Code Brisen 2` / `dvallen@brisengroup.com`.*
