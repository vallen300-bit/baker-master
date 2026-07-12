# DESIGN — Researcher Continuation Queue (tranche-2 item #5)

**For:** codex design-gate (design-PASS required before build, Director rule #9255 / dispatch #9299).
**Builder:** b1. **Source brief:** `~/baker-vault/wiki/research/2026-07-12-researcher-capability-extension-brief.md` @22ab300 (item #5).
**Status:** DESIGN — no code written yet; awaiting codex design-PASS.

## Problem

The researcher method emits deferrals as **prose only** — they are "merely mentioned" in the report and lost. Multi-pass topics never compound; deferred work evaporates. Item #5 = save each deferral as a **real structured follow-up brief artifact**.

## Where deferrals are emitted today (method.md @ current, anchors)

- Step 0 / §9 trigger (line 214): *"Ambiguous → SHORT … can ask for FULL follow-up"* — a deferred FULL pass.
- Step 8 Synthesis (line 74): *"Gap-flag / Open Q's for Director."*
- SHORT Shape §3 "Top risk or gap" + §5 offer line *"Request deep-dive on [specific aspect]?"* (lines 184–186).
- FULL Shape §6 "Open questions for Director" + §7 "gaps remaining" (lines 202–203).
- Standing rules (lines 125, 130): *"Ship partial with honest gap log"*; *"Ship partial at ceiling."*

All are deferral emission points. None currently produce a pickup-able artifact.

## Proposed design

Add a mandatory **Step 8.6 "Continuation capture"** to `method.md`: when any deferral of a defined class exists, the researcher writes a structured continuation-brief file **in addition** to mentioning it in the report. In-cage (writes only to `wiki/research/**`), proposal-only (promotion to a real assignment routes via lead/deputy — never auto-dispatched).

### Artifact

- Path: `wiki/research/_continuation/<YYYY-MM-DD>-<topic-slug>-cont.md` (new subfolder inside the existing write-cage).
- One file per parent report; append a new dated section if a continuation already exists for the same parent (multi-pass compounding).

### Schema

```
---
type: research-continuation
parent_report: wiki/research/<...>.md
parent_date: YYYY-MM-DD
topic: <slug>
status: open            # open | promoted | dropped
created_by: researcher
---
## Deferred items
| # | deferred item | class | why deferred | suggested channels | est effort | priority |
```

Deferral **class** is a closed set: `ceiling-hit` (budget/time cut a channel) · `offer-line` (deep-dive offered, not done) · `required-source-skipped` (coverage-ledger gap) · `shape-upgrade` (ambiguous-SHORT that warrants FULL) · `open-question` (needs Director/source input).

### Trigger (ship-gate)

At Step 8.6: if the tranche-1 coverage ledger marks any channel partial/unavailable, OR the report carries an offer-line / gap-flag / open-Q, a continuation file MUST exist — else the report is labeled `continuation-missing` (parallels the coverage-ledger `incomplete` label already merged in tranche-1). Zero-deferral reports skip cleanly (no empty file written).

### Build shape (the decision I want codex to rule on)

- **Option A (lean, recommended):** `method.md` Step 8.6 addition + a template file (`wiki/research/_continuation/_TEMPLATE.md`) + a cage-safe `validate_continuation.sh` helper that checks the file exists + schema-conforms when deferrals are present. No new skill surface; mirrors the coverage-ledger pattern already shipped in tranche-1.
- **Option B (heavier):** a new `research-continuation-queue` skill invoked at Step 8.6 that renders the file from the coverage ledger + report deferrals. Reusable but adds a skill surface.

Recommendation: **A** — matches the merged coverage-ledger mechanic, stays proposal-only, no new runtime/tool verbs.

### Cage / safety (unchanged, per Director standing rule)

Writes only to `wiki/research/_continuation/**` (inside existing write-cage). No new tool verbs, no send, no auto-dispatch. Promotion of a continuation to a live assignment is a lead/deputy routing act — preserves the no-self-task + lethal-trifecta split.

## Questions for codex

1. Subfolder `_continuation/` vs a sibling `<report>-cont.md` next to the parent — preference?
2. Enforcement: `validate_continuation.sh` as a real ship-gate (fail-closed) vs method-prose-only?
3. Should the promoted-continuation reuse the **tranche-1 intake-manifest (#2) schema**, so a promoted continuation is a drop-in new intake (closes the loop)? I lean yes.
4. Build venue confirm: this is a **baker-vault** change (method.md + template + helper under `_ops`/`wiki`), not baker-master — correct?

Once codex returns design-PASS (with rulings on 1–4), I build item-1 as its own PR, codex build-gate, lead merge.
