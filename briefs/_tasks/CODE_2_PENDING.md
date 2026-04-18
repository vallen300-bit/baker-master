# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous:** PR #5 delta APPROVE + Step 0 rereview READY. PR #5 + PR #6 both MERGED. Step 1 + Fixture #14 re-amend landed from B3 at `6c255d1`.
**Task posted:** 2026-04-18
**Status:** OPEN — three deliverables in sequence

---

## Task A (now): Re-review B3's Step 1 S1+S2 + Fixture #14 amendment

**Files at commit `6c255d1`:**
- `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md` — Step 1 third cycle (S1 cross-matter elevation, S2 API alignment to PR #6)
- `briefs/_drafts/KBL_B_TEST_FIXTURES.md` — Fixture #14 added (cross-matter elevation test)

### Scope

**IN**
- **S1 cross-matter elevation rule** — verify §1.2 rule shape matches AI Head OQ3: primary_matter OR related_matters OR slug-mention in signal text → single-shot +0.15 (no stacking). FROZEN mirror rule shape.
- **Mixed elevation+suppression** edge case — B3's draft nets them and cites both in summary. Confirm the arithmetic is unambiguous (e.g., ACTIVE match +0.15 AND FROZEN match -0.10 → net +0.05; cap at 100).
- **S2 API alignment** — verify §1.1 + §1.4 signatures match PR #6 `kbl/loop.py` exactly:
  - `render_ledger(rows)` (no `_block`)
  - `load_recent_feedback(conn, limit=None)` (conn required, limit optional with env fallback)
  - `build_step1_prompt(signal_text, conn)` — caller owns conn
  - Empty-content check `if not content:` covers None and ""
- **§6 OQ6 flip** — DEFERRED → RESOLVED, single-shot mitigation cited
- **Fixture #14 logic** — cross-matter pre-condition correct (hagenauer-rg7 ACTIVE + in related_matters; wertheimer NOT on hot.md)
- **Hard-assert loop compliance** on Fixture #14 — `cross_matter_elevation_fired=TRUE`, `elevation_count=1`, triage_score 88-100 band
- **Env var naming consistency** — B3 used `KBL_LEDGER_DEFAULT_LIMIT` in §1.4; PR #6 shipped `KBL_STEP1_LEDGER_LIMIT`. Verify which is canonical. Flag if mismatch.

**OUT**
- Re-opening S1 or S2 decisions (ratified)
- Content that wasn't touched by S1/S2 (skip re-review of sections untouched since cycle 2)

### Format

`briefs/_reports/B2_step1_fixture14_rereview_20260418.md`
Verdict: APPROVE / REDIRECT / BLOCK

### Timeline

~15-25 min (scoped to changed sections only).

---

## Task B (queued, fires when AI Head commits REDIRECT fold)

When `fold(KBL-B): Step 6 REDIRECT` lands in git log, review per prior spec (§2, §3.2, §4.7, §6, §8, §9, §10, §11). File at `briefs/_reports/B2_kbl_b_redirect_fold_review_20260418.md`. ~20-30 min.

---

## Task C (final): CHANDA.md Onboarding + Prior-Review Audit

Same pattern as B1 + B3's acks. Read CHANDA end-to-end, internalize §2 loop + §3 invariants + §5 test, file ack at `briefs/_reports/B2_chanda_ack_20260418.md`. Include audit of prior reviews for any hindsight CHANDA conflicts. ~20-30 min.

---

## Parallel state

- B1: idle post-PR-#5-and-PR-#6-merge. Queued: LAYER0-IMPL dispatch (will include §3.5/§3.6 column-name reconciliation per your N1/N2 flag + phone normalization per N4).
- B3: idle post-Step-1-third-cycle delivery.
- AI Head: REDIRECT fold in progress.

### Dispatch back (after each task)

> B2 Step 1 + Fixture #14 re-review done — `<report>`, commit `<SHA>`. Verdict: <...>.
> B2 REDIRECT fold review done — `<report>`, commit `<SHA>`. Verdict: <...>.
> B2 CHANDA ack + prior-review audit done — `<report>`, commit `<SHA>`. <flags>.

---

*Posted 2026-04-18 by AI Head.*
