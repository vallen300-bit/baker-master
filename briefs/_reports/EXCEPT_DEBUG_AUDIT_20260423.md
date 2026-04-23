# EXCEPT_DEBUG_AUDIT — BRIEF_PM_EXTRACTION_JSON_ROBUSTNESS_1 D0 — 2026-04-23

**Author:** Code Brisen #2
**Branch:** `hotfix/pm-extraction-json-robustness-1`
**Method:** `grep -rn "except Exception" orchestrator/ triggers/ outputs/ memory/ --include="*.py" -A 1 | grep -B 1 "logger\.debug"` + targeted `grep -n "logger\.debug" orchestrator/capability_runner.py -B 1`.
**Scope of D0:** classify silencers only. No code edits in D0.

---

## Classification rule (from brief §D0)

| Bucket | Definition | D4 action |
|---|---|---|
| **A** | Extraction failure — LLM→JSON roundtrip, regex extract, prompt→structured-output roundtrip | Promote `debug` → `warning` with `type(e).__name__` |
| **B** | State-write failure — DB write, pool acquisition, commit | Keep `debug` (state-write failures surface via parent capability log) |
| **C** | Non-critical ancillary — metrics logging, cost tracking, decomposition logging | Keep `debug` |

---

## Summary

**Total Bucket A surfaced: 3** (≤5 threshold — all promoted in D4 of this brief.)

| # | file:line | function | Bucket | In D4? | Why |
|---|---|---|---|---|---|
| 1 | `orchestrator/capability_runner.py:315` | `extract_and_update_pm_state` outer catch | A | ✅ | Wraps full LLM→JSON→state-write chain for PM_REGISTRY client_pm. 11-day silent failure incident proves need. |
| 2 | `orchestrator/capability_runner.py:408` | `extract_correction_from_feedback` outer catch | A | ✅ | LLM call to Flash + `_json.loads(raw)` on line 387. Same silent-swallow class. |
| 3 | `orchestrator/capability_runner.py:1326` | `CapabilityRunner._maybe_store_insight` outer catch | A | ✅ | LLM call + `_json.loads` extraction site. Same class. |

---

## Full grep pass — classification

### `orchestrator/capability_runner.py` (primary target)

| Line | Surrounding function / label | Bucket | Notes |
|---|---|---|---|
| 315 | `extract_and_update_pm_state` outer except | **A** | **D4 promote.** Brief's primary target. |
| 331 | Correction circuit-breaker guard | n/a | `logger.debug("Circuit breaker blocked correction extraction")` — control-flow log, not an `except:` silencer. Out of scope. |
| 343 | `extract_correction_from_feedback` no-comment early return | n/a | Same — control-flow log. |
| 384 | `extract_correction_from_feedback` null-result early return | n/a | Same — control-flow log. |
| 408 | `extract_correction_from_feedback` outer except | **A** | **D4 promote.** |
| 911 | `_run_delegate` decomposition-log except | **C** | Brief seed confirms Bucket C. Decomposition logging is metrics. |
| 1326 | `_maybe_store_insight` outer except | **A** | **D4 promote.** Brief seed. |
| 1356 | `_store_russo_document` outer except | **B** | DB INSERT into `documents` table. State-write. Keep debug. |
| 1896 | Pending-insight inner store fallback | **B** | Inner DB fallback inside `_store_pending_insights`. State-write. |
| 1900 | `_store_pending_insights` outer except | **B** | Brief seed Bucket B. Keep debug. |

### `orchestrator/` other modules — Bucket A audit

Cross-scan confirmed **no additional Bucket-A silent catches** in:
- `orchestrator/action_completion_detector.py:91,121` (DB reads, Bucket B)
- `orchestrator/initiative_engine.py:244` (calendar fetch — Bucket C, ancillary to morning brief)
- Other `orchestrator/*.py` hits are either `logger.warning`/`logger.error` already, or Bucket B/C.

### `triggers/` — overflow candidates (NOT in D4 scope)

These are Bucket-A-ish LLM extraction paths that currently use `logger.debug`, but belong to the `trigger_state` fan-out layer (meeting/commitment/deadline pipelines), not the PM state path. The brief's rule — "if >5 Bucket-A total, queue overflow" — applies to *total* count. Since the 3 primary sites are already the whole D4 scope, these are explicitly queued for a follow-up brief rather than included here.

| file:line | function | Rationale |
|---|---|---|
| `triggers/plaud_trigger.py:380,569` | `meeting signal detection failed` | Bucket A (LLM relevance classification). Suggest follow-up promote. |
| `triggers/plaud_trigger.py:414` | `Deadline extraction failed for Plaud` | Bucket A. Follow-up. |
| `triggers/plaud_trigger.py:426` | `Commitment extraction failed for Plaud` | Bucket A. Follow-up. |
| `triggers/plaud_trigger.py:439` | `Director commitment extraction failed for Plaud` | Bucket A. Follow-up. |
| `triggers/clickup_trigger.py:350` | `Deadline extraction failed for task` | Bucket A. Follow-up. |
| `triggers/clickup_trigger.py:373` | `ClickUp deadline sync failed` | Bucket A. Follow-up. |
| `triggers/youtube_ingest.py:252` | `meeting signal detection failed` | Bucket A. Follow-up. |
| `outputs/dashboard.py:200` | `Correction extraction failed (non-fatal)` | Duplicate silencer on top of `capability_runner.py:407-408` at the dashboard fire-and-forget caller. Follow-up. |
| `outputs/dashboard.py:226` | `Positive example embedding failed` | Bucket A edge (embedding roundtrip). Follow-up. |

**Recommended follow-up brief name:** `LOGGER_LEVEL_PROMOTE_TRIGGERS_1` — would promote these 9 trigger-layer silencers in a dedicated pass with full trigger-path regression harness. Out of scope for this hot-fix per brief §D4 rule.

### `memory/store_back.py`, `triggers/*`, `outputs/*` — Bucket B + C swept

All remaining `except Exception: logger.debug` hits in these directories are either:
- DB writes/reads with explicit `conn.rollback()` on error (Bucket B, keep debug — the caller logs at info/warning),
- Non-fatal ancillary pipelines (deadline sync status, cost logging, metrics emit — Bucket C).

No surprises. No additional Bucket-A silencers beyond the 9 trigger-layer overflow entries above.

---

## Why the brief's 3 primary sites are the right D4 scope

1. All 3 live in `orchestrator/capability_runner.py` — one file, one import, atomic diff, reversible.
2. All 3 are LLM→JSON roundtrips that PR #50's post-merge verification proved are the *actual* silent-failure surface for the PM state path.
3. Promoting them adds a grep-able `type(e).__name__` forensic anchor — matches Director's 2026-04-23 directive: *"un-mute silent swallows so 11-day blackouts like this one can't recur on any of the three LLM roundtrips that share the pattern."*
4. Promoting trigger-layer sites in the same PR would mingle two failure classes (PM state extraction vs meeting/deadline extraction) and expand the surface area beyond the hot-fix's stated scope (brief §Do NOT Touch: `scripts/backfill_pm_state.py`, `outputs/dashboard.py`, etc.).

---

## Bucket count vs threshold

- Bucket A in primary target (`capability_runner.py`): **3** → ≤5 ✓ → all promoted in D4.
- Bucket A surfaced elsewhere (trigger layer): **9** → queued for `LOGGER_LEVEL_PROMOTE_TRIGGERS_1` follow-up brief.
- Bucket B / Bucket C: untouched in D4 per brief rule.

— B2, 2026-04-23
