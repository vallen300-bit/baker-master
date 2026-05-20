# BRIEF: COCKPIT_ALERT_PROMPT_REWRITE_1

**Owner:** AH1 (lead)
**Target:** any free B-code (b1/b2/b3/b4)
**Type:** Tier-B prompt engineering — internal Baker only, no external surface change
**Date:** 2026-05-20
**Director-ratified:** 2026-05-20 ~14:30Z (this session, after Slack DM kill ratification batch)

### Surface contract: N/A — pure backend prompt-string change in `orchestrator/prompt_builder.py`; no user-clickable surface (no button, link, modal, panel, card, route, or Slack Block Kit action). Output is consumed by the existing alert rendering pipeline unchanged.

---

## Problem

Director's #cockpit Slack alerts read at "Haiku-level intelligence" — summary regurgitation, not strategic synthesis. Anchor: 2026-05-20 session — Director quote: *"the intelligence level of the advises i get in cockpit."*

Investigation surfaced two facts:
1. Most alert bodies are written by **Gemini 2.5 Pro** (T2 emails + handoff notes) — not Opus. Cheap-tier model. (`orchestrator/pipeline.py:476-500`)
2. The **prompt itself** at `orchestrator/prompt_builder.py:21-110` (`BAKER_SYSTEM_PROMPT`) gives the model NO structural guidance on what the alert `body` field should contain. It only specifies the JSON shape `{"body": "..."}` + tier rules. The model defaults to "summarize what happened" because that's what summarization-trained LLMs do absent specific framing.

Director-ratified path is **option 3 — fix the prompt, not the model.** Cheap, addressable, scales.

## Goal

Rewrite the `BAKER_SYSTEM_PROMPT` alert section to force strategic synthesis instead of summary. The same Gemini Pro that today produces *"Merz sent an email asking about Friday Zoom"* should produce *"Merz is signaling he feels out of the loop and wants alignment before he puts anything in writing to Aukera/JM"* — because the prompt explicitly demands the latter shape.

The sample text in the goal statement is taken verbatim from a Tier-1 Opus-generated alert in #cockpit on 2026-05-20 12:43 CEST (Merz Zoom request). The same model could produce that shape if the prompt asks for it.

## Acceptance criteria

1. `BAKER_SYSTEM_PROMPT` in `orchestrator/prompt_builder.py` adds a new `## ALERT BODY FORMAT` section (between current `## ALERT TIER RULES` and end-of-prompt) requiring the alert body include in order:
   1. **One-sentence strategic interpretation** — what does this mean for Dimitry? (NOT what happened)
   2. **Counterparty intent** (when applicable) — what is the sender/contact trying to accomplish?
   3. **Risk if ignored** — what breaks if Dimitry doesn't act in 48h? Be specific.
   4. **Suggested next move** — concrete, executable action with a name + timeframe.
2. Add 1-2 few-shot examples in the prompt showing the contrast: "❌ summary shape" vs "✅ strategic synthesis shape" for the same hypothetical input. Use real flavor — Aukera / MOHG / Hagenauer / Konstantinos / Merz — not generic placeholders.
3. New test `tests/test_alert_prompt_strategic_synthesis.py` asserts:
   - `BAKER_SYSTEM_PROMPT` contains the four required sub-elements
   - Few-shot examples are present
   - Existing tier-rule structure preserved (Tier 1/2/3 guidance untouched)
4. Ship-gate: literal `pytest tests/test_alert_prompt_strategic_synthesis.py -v` green. NOT pass-by-inspection.
5. **No model swap** — Gemini Pro stays the default routing for T2 triggers. The prompt change is the only lever.
6. **No JSON shape change** — `alerts: [{tier, title, body, action_required}]` schema preserved. Only the `body` content guidance changes.

## Out-of-scope (do NOT touch)

- Tier classification rules (lines ~81-109 of current prompt) — preserved verbatim
- Tier routing logic in `pipeline.py:466-500` — no model swap
- `outputs/formatters.py::format_alert_slack` — body formatting/Block Kit rendering unchanged
- DM channel posting (killed in PR #233 separately)
- Cockpit channel routing — unaffected
- Briefing format / cost reports — out of scope

## Test plan

1. Reproduce the gap: run the existing alert pipeline against a fixture email (e.g. Merz-style ask) and capture current `body` output for comparison.
2. Apply prompt rewrite.
3. Re-run against same fixture; confirm body now contains all four sub-elements.
4. Run full `pytest tests/test_prompt_builder*.py tests/test_alert*.py` to confirm no regressions on tier classification or JSON parsing.
5. If a "before vs after" sample fixture exists in tests, add explicit assertion on the new shape.

## Risks + mitigations

- **Risk:** Gemini Pro output drifts into verbose / structured / over-template form when given a 4-element required shape. **Mitigation:** keep the format guidance terse (4 lines max) + the few-shot examples are 2-3 sentences each, not multi-paragraph templates.
- **Risk:** breaks the existing `action_required` boolean inference. **Mitigation:** "Suggested next move" sub-element explicitly addresses action — should reinforce the boolean, not conflict.
- **Risk:** Director's tone preferences (warm but direct, no emojis, no sycophancy) get overridden by the new format guidance. **Mitigation:** new section is ADDITIVE to existing `## RESPONSE STYLE` block — that block stays intact.

## Code Brief Standards (mandatory)

- **API version/endpoint:** N/A — internal prompt change, no external API touch.
- **Deprecation check:** Gemini 2.5 Pro confirmed active as of 2026-05-20 (used in this morning's smoke #2 PASS on PR #231).
- **Fallback note:** None applicable. If Gemini fails, existing fail-open / Anthropic-fallback paths preserved.
- **Migration-vs-bootstrap DDL check:** N/A — no schema change.
- **Singleton:** N/A — no instance changes.
- **Post-merge script handoff:** N/A — no script invocation.
- **file:line citation verification:** all line references in this brief (e.g. `orchestrator/prompt_builder.py:21-110`) verified by Read tool at brief-authoring time.
- **Invocation-path audit (Amendment H):** prompt is consumed by `SentinelPromptBuilder.build_prompt` → `Pipeline.generate` → both Gemini and Anthropic paths use the same `system` field, so the prompt change applies to both providers uniformly. No mutation_source change, no write-path change. READ-ONLY-FOR-PROMPT change.

## Reporting

- Bus-post `lead` on PR open (`ship/cockpit-alert-prompt-rewrite-1` topic).
- Mailbox UPDATE `dispatched_by: lead`.
- Reply to sender rule applies — ship-report goes to `lead`.

## Expected build time

~30-45 min for a B-code: prompt edit + few-shot examples + 1 new test file + pytest verify.

---

**Anchor for ratification:** Director session 2026-05-20 ~14:30Z: *"go for 3 ( prompt correction )"* + *"ratified, go"* on the 5-item batch.
