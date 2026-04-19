---
title: KBL-B Step 6 Open Questions — AI Head Resolutions
voice: report
author: ai-head
created: 2026-04-19
---

# Step 6 Spec — OQ1-OQ8 Resolutions

**Source:** `briefs/_drafts/KBL_B_STEP6_FINALIZE_SPEC.md` @ `ffa2a26` §7.
**Resolver:** AI Head.
**Date:** 2026-04-19.
**Verdict per OQ:** all 8 ratified as B3 recommended.

---

| # | OQ | B3 recommendation | AI Head verdict |
|---|---|---|---|
| 1 | `sources` vs `source_id` naming | Keep `source_id` singular (Opus trained on it). Add `source_ids: list[str]` later if multi-source consolidation surfaces. | **Ratified.** Use `source_id`. `source_ids` deferred to Phase 2 re-authoring (would invalidate prompt cache). |
| 2 | `title` length 80 vs 160 chars | Relax to 160. Ex 6 title is 91 chars legitimately. | **Ratified.** R12 enforces 160. |
| 3 | `thread_continues` regex strictness | Lenient for `thread_continues` (`^wiki/.*\.md$`), tight for `target_vault_path` only | **Ratified.** Historical vault paths get leniency; new writes get full R20 validation. |
| 4 | `money_mentioned` structured vs string | Opus emits strings (preserves cache). Step 6 parser normalizes to `MoneyMention` model. | **Ratified.** B1 owns the ~30-line parser as Step 6 impl work. |
| 5 | Stub status values (`stub_auto` / `stub_cross_link` / `stub_inbox`) | 3 distinct values per provenance | **Ratified.** Director distinguishability is cheap + valuable. |
| 6 | Currency enum `{EUR, USD, CHF, GBP, RUB}` | Ship with these 5; extend when concrete signal surfaces need | **Ratified.** PLN/AED/JPY added when actual signals with those currencies land. |
| 7 | `null` primary_matter — valid? | R7 enforces null-primary ⇒ empty-related | **Ratified + clarified:** `primary_matter: null` is legitimate on `STUB_ONLY` path (Step 1 triage surfaces null when no matter identified). Step 5 stub writer emits `primary_matter: null` + `related_matters: []` + `status: stub_auto`. R7 coherence check enforces. |
| 8 | `⚠ CONTRADICTION:` marker validation | Leave freeform | **Ratified.** Over-constraining rare outputs creates false rejections. Marker's job is to flag to Director, not to be machine-parsed. |

---

## B1 implementation notes folded in

- `source_id`, not `sources` — `SilverFrontmatter.source_id: str` (not `list[str]`).
- Title max 160 chars in R12 validator.
- `thread_continues` validator: lenient `^wiki/.*\.md$`; `target_vault_path` validator: full canonical regex per R20.
- `money_mentioned` field stored as `list[str]` in DB (emitted raw by Opus); parser runs at Step 6 entry to produce `list[MoneyMention]` for validation + downstream use.
- 3 status enum values: `stub_auto`, `stub_cross_link`, `stub_inbox`.
- Currency `Literal['EUR', 'USD', 'CHF', 'GBP', 'RUB']` — no others yet.
- `primary_matter: Optional[MatterSlug]` — null allowed iff `related_matters == []` (R7).
- `⚠ CONTRADICTION:` marker — present/absent binary check only (body `.contains('⚠ CONTRADICTION:')`); no structural parse.

---

*Ratified 2026-04-19 by AI Head. B1 implements against this resolution set + `briefs/_drafts/KBL_B_STEP6_FINALIZE_SPEC.md`. No further OQ work needed before Step 6 impl.*
