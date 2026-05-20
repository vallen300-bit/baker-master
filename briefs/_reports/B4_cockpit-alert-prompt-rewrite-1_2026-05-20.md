---
brief_id: COCKPIT_ALERT_PROMPT_REWRITE_1
builder: b4
date: 2026-05-20
pr: 234
pr_url: https://github.com/vallen300-bit/baker-master/pull/234
branch: b4/cockpit-alert-prompt-rewrite-1
commit: c90ca48
status: SHIPPED (awaiting AH1 review + merge)
---

# B4 completion report — cockpit-alert-prompt-rewrite-1

## What shipped
- `orchestrator/prompt_builder.py`: added `## ALERT BODY FORMAT` section between `## ALERT TIER RULES` and end-of-prompt. Forces 4-element strategic synthesis on every alert body:
  1. Strategic interpretation (what does this mean for Dimitry)
  2. Counterparty intent (what is the sender trying to accomplish)
  3. Risk if ignored (specific named consequence at 48h)
  4. Suggested next move (concrete executable action + recipient + timeframe)
- Two contrasting few-shot examples (`❌ SUMMARY SHAPE` vs `✅ STRATEGIC SYNTHESIS SHAPE`) using real Brisen counterparties: Merz / Aukera / MOHG / Hagenauer / Konstantinos.
- `tests/test_alert_prompt_strategic_synthesis.py`: 9 assertions covering presence of new section, 4 required elements, both ❌/✅ examples, real-counterparty flavor, tier-rule preservation, JSON shape preservation, RESPONSE STYLE preservation, ordering invariant.

## Test verification (literal output, not by inspection)
- New tests: `python3.12 -m pytest tests/test_alert_prompt_strategic_synthesis.py -v` → **9 passed in 0.02s**
- Regression coverage: `python3.12 -m pytest tests/test_prompt_cache_audit.py tests/test_prompt_caching_1.py tests/test_scan_prompt.py tests/test_alerts_to_signal_cortex_dispatch.py tests/test_bridge_alerts_to_signal.py tests/test_dashboard_alert_fold.py -v` → **86 passed, 1 failed in 28.48s**
- Single failure: `test_scan_prompt.py::test_prompt_is_conversational_no_json_requirement` — pre-existing on `main` without this PR's changes (verified via `git stash` baseline). Tests `SCAN_SYSTEM_PROMPT` (different prompt, different file). Out-of-scope for this brief.

## Brief acceptance criteria — all met
| AC | Status |
|----|--------|
| 1. New `## ALERT BODY FORMAT` section between tier rules and end | ✅ |
| 2. Two contrasting few-shot examples with real Brisen flavor | ✅ |
| 3. Test file asserts 4 sub-elements + few-shots + tier preservation | ✅ |
| 4. Literal `pytest` green, no pass-by-inspection | ✅ |
| 5. No model swap (Gemini Pro still T2 default) | ✅ — pipeline.py untouched |
| 6. No JSON shape change | ✅ — alerts schema preserved verbatim |

## Out-of-scope respected
- Tier classification rules (verbatim) — preserved
- `pipeline.py:466-500` model routing — untouched
- `formatters.py::format_alert_slack` — untouched
- DM channel posting (killed in PR #233) — untouched
- Cockpit channel routing — untouched

## Notes for AH1
- Pre-existing `test_scan_prompt` failure on main is a separate prompt file; flagging here for visibility, not blocking this PR. Recommend separate brief if Director wants it fixed.
- Risk-mitigation note from brief: kept format guidance terse (4 elements × 1-2 sentences each, total 4-8 sentences) to avoid Gemini drifting into over-structured/over-templated bodies. Few-shot examples are 3-4 sentences of flowing prose each, not bulleted templates.
