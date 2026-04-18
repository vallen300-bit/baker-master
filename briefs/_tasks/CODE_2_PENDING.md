# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous:** All prior tasks done (PR #4/5/6 reviews, Step 0 rereview, Step 1+Fixture 14 rereview, CHANDA ack). PR #7 (LAYER0-IMPL) just landed from B1.
**Task posted:** 2026-04-18
**Status:** OPEN — two deliverables in sequence

---

## Task A (now): Review PR #7 — LAYER0-IMPL

**PR:** https://github.com/vallen300-bit/baker-master/pull/7
**Branch:** `layer0-impl`
**Head:** `7342617`
**Tests:** 84/84 new (31 director_identity + 27 dedupe + 26 eval) + 1 live-PG skip; related suite 137/137

### Scope of review

**IN**
- **`kbl/layer0.py`** — evaluator: `evaluate()`, `_process_layer0()`, first-match-wins ordering, never-drop invariant chain (scan → Director → primary_matter_hint → VIP CLOSED → slug/alias topic override CLOSED)
- **`baker/director_identity.py`** — `is_director_sender()` — email variants + WhatsApp digit-only normalization
- **`kbl/layer0_dedupe.py`** — `normalize_for_hash` / `has_seen_recent` / `insert_hash` / `cleanup_expired`
- **Side effects audit:**
  - Hash INSERT on PASS only (S5 preserves legit copies)
  - Review INSERT on DROP when `signal.id % 50 == 0` (S6 deterministic)
  - Review row columns match PR #5 schema exactly (`dropped_by_rule`, `signal_excerpt`, `source_kind`, `created_at`) — N1/N2 from your Step 0 rereview
- **CHANDA compliance:**
  - Inv 4: Director-sender short-circuit enforces author-director authority at intake
  - Inv 7: Layer 0 ≠ alert (review queue is audit); log-only on drop
  - Inv 1: zero-match case → PASS (not error)
  - Inv 10: rules are data, evaluator is stable code — no self-modification

**Specific scrutiny**

1. **Phone normalization correctness** — verify the regex strips all non-digits and handles `+` prefix, `@c.us` WAHA suffix, space-separated format, and that comparison uses the canonical `41799605092` form.
2. **Never-drop ordering (§3.2)** — B1 implemented scan → Director → primary_matter_hint → VIP → slug/alias override. Is that the right order semantically? E.g., if signal is from Director AND has VIP-service-downtime, Director check wins — verify.
3. **Hash-store TTL correctness** — 72h default, `ttl_expires_at > now()` check, cleanup idempotent
4. **Review queue determinism** — `signal.id % 50 == 0` means sample hits signals 0, 50, 100, ... Is that the intended distribution vs hashing the signal content? B3 spec'd this; if you disagree, flag.
5. **Error paths** — what happens on DB unavailable during hash read / review insert? PASS-fail-open vs CLOSED? Verify explicitly.
6. **Integration with existing `kbl/slug_registry.py`** — does `is_director_sender` / topic-override logic use `slug_registry.aliases_for()` per S3?

### Format

`briefs/_reports/B2_pr7_review_20260418.md`
Verdict: APPROVE / REDIRECT (list inline-appliable fixes) / BLOCK

### Timeline

~30-40 min. PR #7 is the largest KBL-B impl unit to date.

---

## Task B (queued, fires when AI Head commits REDIRECT fold)

When `fold(KBL-B): Step 6 REDIRECT` lands in git log, review per prior spec (§2, §3.2, §4.7, §6, §8, §9, §10, §11). File at `briefs/_reports/B2_kbl_b_redirect_fold_review_20260418.md`. ~20-30 min.

---

## Parallel state

- B1: idle post-PR-#7-ship.
- B3: working STEP5-OPUS-PROMPT draft (~60-90 min).
- AI Head: REDIRECT fold in progress.

### Dispatch back

> B2 PR #7 review done — `briefs/_reports/B2_pr7_review_20260418.md`, commit `<SHA>`. Verdict: <...>.
> B2 REDIRECT fold review done — `briefs/_reports/B2_kbl_b_redirect_fold_review_20260418.md`, commit `<SHA>`. Verdict: <...>.

---

*Posted 2026-04-18 by AI Head.*
