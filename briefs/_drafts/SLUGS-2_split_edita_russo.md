# SLUGS-2 — Split `edita-russo` Composite Slug

**From:** Code Brisen 3
**To:** AI Head
**Date:** 2026-04-18
**Trigger:** Director ratification session for v3 eval slug descriptions revealed design defect
**Priority:** Medium — doesn't block D1 ratification, but blocks clean KBL-B matter routing

---

## Problem

The SLUGS-1 canonical slug `edita-russo` groups two **distinct, unrelated entities**:

1. **Edita Vallen** — Director's wife, co-owner of all Brisen projects, COO of Brisen Group.
2. **Russo** — Geneva-based Swiss tax advisor (external counterparty, unrelated to Edita).

Director confirmed in live session 2026-04-18:
> *"Edita Vallen is separate from Russo. Russo is just a tax advisor on Swiss matters. It should not be Edita-Russo. They are separate."*

## Why this matters

- Signals that mention Edita's role as COO (operational, family-office-internal) route to the same slug as signals from Russo (external Swiss tax correspondence).
- KBL-B Step 2 (entity resolve) cannot disambiguate because the slug itself is ambiguous.
- Future per-matter views, routing rules, and audit trails all inherit the defect.
- Any LLM prompt containing this slug with a proper description becomes self-contradictory (the description has to be a disjunction, which degrades model accuracy for both).

## Proposed fix

Split into two canonical active slugs:

```yaml
  - slug: edita
    status: active
    description: "Edita Vallen — Director's wife, co-owner of all Brisen projects, COO of Brisen Group"
    aliases: ["edita vallen"]

  - slug: russo
    status: active
    description: "Russo — Geneva-based Swiss tax advisor (external counterparty)"
    aliases: []
```

Mark `edita-russo` as:

```yaml
  - slug: edita-russo
    status: retired
    description: "DEPRECATED — split 2026-04-18 into `edita` + `russo`. Do not use for new signals."
    aliases: []
```

Per baker-vault schema comment: `retired` status means "NOT offered, still accepted (historical signals), not routed" — exactly the right behavior for migration.

## Migration

- No historical labeled signals currently use `edita-russo` in the v3 eval set (confirmed: not in `outputs/kbl_eval_set_20260417_labeled.jsonl`).
- PostgreSQL `*_signals` tables: need one-time UPDATE to re-route any rows tagged `edita-russo` to the right new slug. Count likely zero or very small — Director can adjudicate ambiguous rows in a 2-min review.
- `scripts/run_kbl_eval.py:MATTER_ALIASES` — no entry for `edita-russo` currently, no change needed.

## Effort

- **15 min** — baker-vault PR (edit slugs.yml, run schema validator, push, open PR).
- **5 min** — Director review & merge.
- **(if any historical rows)** — 10-min backfill script.

## Out-of-scope for this note

- Adding new aliases or splitting other slugs. If Director's ratification session surfaced other composite-slug problems (I don't believe it did — the other 8 were all single-entity), those are separate SLUGS-N items.
- Moving `MATTER_ALIASES` out of `run_kbl_eval.py` and into `kbl/slug_registry.normalize()`. That's a separate B3-flagged item (v3 report §5b) and also belongs in follow-up PR after SLUGS-1 merges.

---

*Dispatching this to AI Head for decision on whether to spawn SLUGS-2 as its own brief or bundle into an existing KBL-B phase.*
