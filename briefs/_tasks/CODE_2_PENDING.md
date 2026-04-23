# CODE_2_PENDING — PM_EXTRACTION_JSON_ROBUSTNESS_1 — 2026-04-23

**Dispatcher:** AI Head #2 (Team 2)
**Working dir:** `~/bm-b2`
**Brief:** `briefs/BRIEF_PM_EXTRACTION_JSON_ROBUSTNESS_1.md` (baker-master main after this dispatch lands)
**Target PR:** new branch `hotfix/pm-extraction-json-robustness-1`
**Complexity:** Low (~2-3h)

**Supersedes:** prior `PM_SIDEBAR_STATE_WRITE_1` task (shipped as PR #50, merged `596f1861`). Mailbox reset.

---

## Why this hot-fix

Phase 1 post-merge verification 2026-04-23: backfill produced 0/5 extractions. Debug trace: `extract_and_update_pm_state` fails silently on real-world Opus output with `"Expecting property name enclosed in double quotes"` at char positions 1892-2254.

Root cause: pre-existing fragility inherited by PR #50 from the original `_auto_update_pm_state`. `logger.debug(...)` on the outer `except Exception` has silenced the failures in production since 2026-04-12 (`pm_state_history` proves it: last `opus_auto` ao_pm row is 2026-04-12; zero ever for movie_am). Tonight we fix the parser + unmute the log.

**Phase 2 gate:** Director directive 2026-04-23 — `BRIEF_CAPABILITY_THREADS_1` drafts are gated on **this hot-fix merging AND the backfill re-running successfully**, not just on this PR merging. AI Head will re-run the backfill post-merge; if it extracts ≥3 rows for ao_pm, Phase 2 proceeds.

---

## Working-tree setup (B2)

```bash
cd ~/bm-b2 && git fetch origin && git pull --rebase origin main
git checkout -b hotfix/pm-extraction-json-robustness-1
```

---

## What you implement (6 deliverables — full spec in brief)

Read `briefs/BRIEF_PM_EXTRACTION_JSON_ROBUSTNESS_1.md` end-to-end before first commit.

| Deliverable | One-line scope |
|---|---|
| **D0** | Read-only grep audit of `except Exception: logger.debug(...)` in `orchestrator/`, `triggers/`, `outputs/`, `memory/`. Classify A/B/C per brief. Output `briefs/_reports/EXCEPT_DEBUG_AUDIT_20260423.md` with table. NO code edits in D0. |
| **D1** | `max_tokens=700` → `max_tokens=1500` in the `claude.messages.create` call inside `extract_and_update_pm_state`. |
| **D2** | New module-level helper `_robust_json_parse_object(text) -> dict \| None` in `orchestrator/capability_runner.py`. Mirror `orchestrator/extraction_engine.py:554` style. Add Pass-4 regex repair for unquoted keys + trailing commas. Return `None` on failure (NOT `{}`). |
| **D3** | Replace the inline `json.loads(raw)` site inside `extract_and_update_pm_state` with `_robust_json_parse_object(raw)`; on None, `logger.warning(...)` with raw-text preview + `return None`. Delete the now-redundant markdown-fence strip (the helper handles it). |
| **D4** | Promote `logger.debug` → `logger.warning` on ALL Bucket-A sites from D0 audit. Include `type(e).__name__` in each message. **If Bucket-A count >5, STOP and queue overflow in a follow-up brief — note in D0 report.** Bucket B (state-write) + Bucket C (metrics/cost) stay at `debug`. |
| **D5** | New `tests/test_pm_extraction_robustness.py` — minimum 5 tests per brief §D5 (well-formed / markdown fence / unquoted keys / trailing comma / unparseable). |

---

## Mandatory compliance — AI Head SKILL Rules

- **Rule 7 (file:line verify):** `extraction_engine.py:554` is the style mirror; open it before writing D2.
- **Rule 8 (singleton):** no new `SentinelStoreBack()` calls — nothing in this brief instantiates stores.
- **Rule 10 (Part H):** this brief references PR #50's Part H audit by citation — do NOT re-audit; PR body line: *"Part H compliance by reference to PR #50 — same 6 callers, same mutation_source tags, zero new invocation paths."*
- **Python regex:** use `re.IGNORECASE` flag, NOT inline `(?i)` (lesson from existing rules).

---

## Acceptance criteria (testable)

### Syntax + hooks
```bash
$ python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True); print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### Unit tests (ship gate)
```bash
$ python3 -m pytest tests/test_pm_extraction_robustness.py -v
```

Minimum 5 passes per brief §D5:
1. `test_parse_well_formed_json_object`
2. `test_parse_json_in_markdown_fence`
3. `test_parse_unquoted_property_names` — Opus's most common real-world failure
4. `test_parse_trailing_comma`
5. `test_parse_unparseable_returns_none` — must return `None`, NOT `{}`

### Regression delta
```bash
$ python3 -m pytest 2>&1 | tail -3
# branch passes = main passes + 5 (your new tests)
# branch failures == main failures (zero)
```

Compare against main at `596f1861` (PR #50 merge). Record both numbers in CODE_2_RETURN.md.

### Scope discipline
- Files modified must match brief §Files Modified exactly.
- Do NOT touch `scripts/backfill_pm_state.py`, `outputs/dashboard.py` sidebar hooks, `extraction_engine.py`, PM_REGISTRY, schema, or Anthropic SDK.
- Do NOT touch `_auto_update_pm_state` 11-line delegator — it already forwards to the extractor.

---

## Dispatch protocol

1. Pull main (above).
2. Branch `hotfix/pm-extraction-json-robustness-1`.
3. Read the brief end-to-end.
4. Commit per-deliverable OR single commit — your call. Use standard `Co-Authored-By` trailer.
5. Push branch + open PR. PR title: `PM_EXTRACTION_JSON_ROBUSTNESS_1: repair Opus JSON parse + un-mute log`. PR body: brief §Scope table + literal ship-gate output + cite PR #50 for Part H by reference.
6. Ship report: `briefs/_reports/CODE_2_RETURN.md` on your branch (you'll overwrite your prior PR #50 return file — that's fine; the merged file lives on main).
7. Tag AI Head #2: `@ai-head-2 ready for review`.

AI Head #2 runs `/security-review` + merges on APPROVE + green (Tier A). **Then re-runs the backfill** per brief §Post-merge sequence. Phase 2 unlocks ONLY if backfill extracts ≥3 rows for ao_pm.

---

## Key lesson to absorb (will become SKILL Rule 11 candidate at Monday 2026-04-27 audit)

**Briefs touching Opus JSON extraction must validate against real-world output samples, not code inspection alone.** The AI Head authoring PR #50 copied `json.loads(raw)` verbatim from `_auto_update_pm_state` without validating it against live Opus output — a 60-second test call would have caught the 11-day silent failure. Do not repeat this in your D2 test design: each of the 5 ship-gate tests uses a realistic Opus failure mode, not just happy-path.

---

## Hard deadline

None declared — but Phase 2 drafts are blocked on this hot-fix landing AND backfill re-running green. Keep moving.

— AI Head #2
