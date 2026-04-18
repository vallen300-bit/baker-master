# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** §10 test fixtures shipped at `742f4a1` (10-signal end-to-end corpus).
**Task posted:** 2026-04-18
**Status:** OPEN — ritual acknowledgment task, short

---

## Task: CHANDA.md Onboarding — Read, Acknowledge, File Compliance Report

**Director adopted `CHANDA.md` today at `915f8ad`** — Gold file at repo root establishing KBL architectural intent. This is now the **inviolable root anchor** for every KBL session. From this commit forward, every agent startup ritual begins with CHANDA.md, *before* reading any mailbox task.

### What you must do

1. `git pull --ff-only origin main`
2. Read `CHANDA.md` end-to-end. It's one file, ~100 lines.
3. **Internalize §2 "The Learning Loop"** — the three legs (Compounding / Capture / Flow-forward). This is the main thing KBL exists to protect.
4. **Internalize §3 Invariants 1-10.** Pay particular attention to the ones that bind your empirical / prompt-engineering / rule-drafting work:
   - **Inv 1** (Gold is read before Silver is compiled, zero Gold is read *as* zero Gold) — relevant to every prompt you draft for Step 1, Step 3, Step 5, Step 6
   - **Inv 3** (Step 1 reads `hot.md` AND feedback ledger every run) — check your Step 1 triage prompt draft satisfies this; if not, flag
   - **Inv 10** (pipeline prompts do not self-modify — learning is through data) — rules out adaptive-prompt patterns you might otherwise propose
5. **Internalize §5 The Test.** Every prompt draft and every rule spec you author passes both:
   - **Q1 Loop Test:** does this change preserve all three legs? Any touch on reading pattern / ledger write / Step 1 integration → stop + flag + wait.
   - **Q2 Wish Test:** does this serve the wish or engineering convenience? Convenience → stop + flag + wait. Both → state the tradeoff in commit message.

### Deliverable

File: `briefs/_reports/B3_chanda_ack_20260418.md` — short, ~30 lines. Structure:

```markdown
# B3 CHANDA.md Acknowledgment

**Read at commit:** 915f8ad
**Timestamp:** <UTC>

## The three legs in my own words
1. <one sentence per leg — what it means for my prompt-engineering / empirical work>
2. ...
3. ...

## Invariants most likely to bind my typical work
- <inv number>: <how it shapes decisions in prompt/rule authoring>
- ...

## Compliance audit of my prior deliverables
- **Step 1 triage prompt (`KBL_B_STEP1_TRIAGE_PROMPT.md`):** does it satisfy Inv 1 (reads Gold) and Inv 3 (reads hot.md + feedback ledger)? If not, flag the gap.
- **Step 3 extract prompt (`KBL_B_STEP3_EXTRACT_PROMPT.md`):** any CHANDA conflict?
- **Step 0 Layer 0 rules (`KBL_B_STEP0_LAYER0_RULES.md`):** does the drop logic respect Inv 7 (ayoniso prompts, never overrides) and Inv 4 (author:director protection)?
- **§10 test fixtures (`KBL_B_TEST_FIXTURES.md`):** do the expected outcomes demonstrate loop compliance, or only pipeline mechanical compliance?

## Pre-push checklist I now run before every draft
- [ ] Q1 Loop Test passed (or flagged to AI Head)
- [ ] Q2 Wish Test passed (or tradeoff stated in commit body)
- [ ] <any additional check you adopt>

## Questions / tensions surfaced
<anything in CHANDA that conflicts with your prior drafts or with ratified decisions — flag, don't silently absorb. Specifically: does any of your Step 1 triage prompt need adjustment to explicitly surface the Gold-read + hot.md + ledger-read requirements, per Invariants 1 and 3?>
```

### Why this task exists + why the audit matters for you specifically

You have drafted **the most CHANDA-adjacent content of any agent**: Step 1 prompt (the heart of the Learning Loop), Step 3 extract, Step 0 rules, fixtures. If any of your prior work silently violates an invariant, it's better to catch it now and amend than to have AI Head fold it into KBL-B §6-13 and discover the conflict post-merge.

Director specifically invited critique during CHANDA adoption; if you think an invariant is wrong, flag — don't absorb silently.

### Status after this task

You return to stand-by per D1 ratification (standing-down-between-evals posture). When Step 1 / Step 3 prompts need to be revised for CHANDA compliance — which your audit may trigger — you'll be dispatched again.

### Timeline

~20-30 min total (10 min CHANDA read, 15 min compliance audit of four prior deliverables, 5 min commit + report).

### Dispatch back

> B3 CHANDA ack done — report at `briefs/_reports/B3_chanda_ack_20260418.md`, commit `<SHA>`. <any flags on prior drafts>

---

*Posted 2026-04-18 by AI Head. B1 doing the same ack task in parallel (CODE_1_PENDING.md). B2 still mid-Step-6-scope-challenge; B2 CHANDA ack will be queued after their verdict lands.*
