# B1 Ship Report — BAKER_PROMPT_CACHING_1

**Brief:** `briefs/BRIEF_BAKER_PROMPT_CACHING_1.md` (commit `d086c8d`)
**Mailbox:** `briefs/_tasks/CODE_1_PENDING.md` (commit `6bcfba7`)
**Branch:** `b1/baker-prompt-caching-1`
**Date:** 2026-05-05
**Tier:** A (agent core touched + DB schema change)

---

## Cache-key audit findings (brief §"Cache-Key Audit Checklist")

Run before any code edit, per brief sequencing §1.

### Scope A — `TOOL_DEFINITIONS` / `AGENT_TOOLS` (`orchestrator/agent.py:38-846`)

- **CLEAN.** Programmatic scan of the `TOOL_DEFINITIONS = [ ... ]` literal
  (lines 38-842) found zero matches for `datetime`, `time.time`, `date.today`,
  `now()`, leading f-strings, or `.format(` calls.
- **CLEAN.** `AGENT_TOOLS` constructed once at module load via list
  comprehension (line 846); no `.append` / `.extend` / index-assign
  mutations elsewhere in the codebase (grep confirmed in `orchestrator/`).
- `matter_slug` appears only as a static parameter name inside tool
  schemas (e.g. agent.py:352) and SQL queries — never interpolated into
  the tool description string.
- `TOOL_DEFINITIONS` body length: 32,580 chars (~8K tokens — slightly
  larger than brief estimate of 3-5K).

### Scope B — `system_prompt` build paths (`outputs/dashboard.py`)

3 build sites identified:

1. **`_scan_chat_deep_agentic` (lines 8055, 8230-8235).** Inline build:
   `f"{SCAN_SYSTEM_PROMPT}\n## CURRENT TIME\n{now}\n\n{pre_stuffed}"` then
   wrapped by `build_mode_aware_prompt(..., mode="delegate")`.
2. **`_build_scan_system_prompt` (lines 8355-8396).** `f"{SCAN_SYSTEM_PROMPT}\n## CURRENT TIME\n{now}\n{domain_context}{deadline_block}"` (deadline_only branch) or includes `{context_block}` for legacy mode.
3. **`build_mode_aware_prompt` (`orchestrator/scan_prompt.py:329-365`).**
   Appends DB-sourced domain context, strategic priorities, communication
   prefs, mode extension. DB-stable across burst; no per-call dynamics.

### Findings — dynamic values inside `system_prompt`

| # | File:Line | Dynamic value | Cache impact | Resolution |
|---|---|---|---|---|
| F1 | `outputs/dashboard.py:8055` (deep) + `:8359` (scan) | `now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")` interpolated into prompt | Per-minute string change → cache miss across minute boundaries | **ACCEPTED** — minute granularity. Within a 2-3 min Director burst (10-30 turns), `{now}` repeats inside same minute → ~75-90% hit rate within burst. Brief §"Decision 4" already explicitly frames 5-min TTL realism + revisit if A7 < 60%. |
| F2 | `outputs/dashboard.py:8071-8210` (deep) | `pre_stuffed` retrieval blocks (recent emails / WhatsApp / meetings / decisions / prior conversations) — keyword-search results vs `req.question` | Per-question variation → cache miss across topically-different questions | **ACCEPTED** — within burst on similar topic, retrievals overlap. A7 measurement is the gate. |
| F3 | `outputs/dashboard.py:8375` (scan) | `deadline_block` from `get_active_deadlines(limit=15)` re-fetched per call | Refetched but rarely changes | **ACCEPTED** — content stable across burst. |
| F4 | `outputs/dashboard.py:8043, 8864-8865` | `domain_context` injected via `build_mode_aware_prompt` | Per-mode/domain variation | **ACCEPTED** — same domain across burst is the common case. |

**No blockers.** All findings fall under brief §"Decision 5" anticipated
audit outcomes, and §"Decision 9" / A6 + A7 measurement is the safety
gate. Kill switch (Decision 8) provides 30-second revert path if A7 < 60%.

No matter-slug interpolation in tools or system prompt (Scope A clean,
Scope B does not insert any matter slug into the prefix).

---

## Implementation summary

### Change A + B (cache_control wiring)

`orchestrator/agent.py` — module-level constant + helper added at
top of file (just after `AGENT_TIMEOUT_SECONDS`):

```python
PROMPT_CACHE_ENABLED = os.getenv("BAKER_PROMPT_CACHE_ENABLED", "true").lower() == "true"

def _build_cached_system_and_tools(system_prompt, tools, model):
    from orchestrator.gemini_client import is_gemini_model
    if not PROMPT_CACHE_ENABLED or is_gemini_model(model):
        return system_prompt, tools
    system_value = [{"type": "text", "text": system_prompt,
                     "cache_control": {"type": "ephemeral"}}]
    if tools:
        tools_value = list(tools)
        tools_value[-1] = {**tools_value[-1],
                           "cache_control": {"type": "ephemeral"}}
    else:
        tools_value = tools
    return system_value, tools_value
```

Both call sites use the helper:
- `agent_loop` line 2287 → `claude.messages.create(... system=_system_value, tools=_tools_value, ...)`
- `run_agent_loop_streaming` line 2540 → same pattern with `_model` for Gemini guard

### Change B.1 (`_force_synthesis`)

Modified in place (line 2155): `_force_synthesis` now invokes
`_build_cached_system_and_tools(system_prompt, None, model)` itself, so
all 5 call sites (lines 2229, 2363, 2444, 2484, 2623) benefit
automatically with zero call-site changes. Synthesis path passes no
tools, so only the system block carries `cache_control`.

### Change C (telemetry + migration)

- `orchestrator/cost_monitor.py:calculate_cost_eur` — added two kwargs
  with defaults of 0:
  - `cache_creation_input_tokens` billed at 125% of standard input rate
  - `cache_read_input_tokens` billed at 10% of standard input rate
- `orchestrator/cost_monitor.py:log_api_cost` — same two kwargs added
  with defaults of 0; INSERT now writes both columns. Backwards
  compatible with all 35+ existing call sites (positional + kwarg).
- `orchestrator/cost_monitor.py:ensure_api_cost_log_table` — bootstrap
  DDL extended with `cache_creation_input_tokens INTEGER DEFAULT 0` +
  `cache_read_input_tokens INTEGER DEFAULT 0` + idempotent
  `ADD COLUMN IF NOT EXISTS` for existing DBs. Lesson #50 compliance:
  bootstrap matches migration exactly, type INTEGER, default 0.
- Agent loop `log_api_cost` calls (lines 2308 + 2565) extract
  `getattr(response.usage, "cache_creation_input_tokens", 0) or 0` and
  pass through.

### Migration

`migrations/20260505_140000_api_cost_log_cache_columns.sql` — two
idempotent `ADD COLUMN IF NOT EXISTS` statements. Filename uses
HHMMSS suffix `140000` to ensure ≥1s differentiation from B2's sibling
brief migration in `BRIEF_BAKER_COST_INSTRUMENTATION_1` (which adds
`matter_slug` to the same table). Both columns are independent → merge
order safe. Refresh `applied_migrations.lock` once after BOTH apply, in
apply-order, per brief §"Sibling-coupling".

### Cost-control runbook (AC A9)

`_ops/processes/cost-control-runbook.md` — kill-switch instructions,
A6/A7 verification SQL, daily/weekly spend visibility pointers.

### New test file

`tests/test_prompt_caching_1.py` — 9 tests:
- `_build_cached_system_and_tools` shape + kill switch + Gemini guard +
  empty-tools + tools-list-not-mutated
- `calculate_cost_eur` 90% discount + 125% premium math
- `log_api_cost` legacy-signature compatibility + cache kwargs
  pass-through

---

## Acceptance criteria

| AC | Status | Evidence |
|---|---|---|
| **A1** ≥4 `cache_control` matches in agent.py | ✅ | `grep -c cache_control orchestrator/agent.py` → 6 (2 real ephemeral blocks + 4 docstring/comment refs) |
| **A2** Migration applies clean + lock refreshed | ⏸ Apply-time gate | `migrations/20260505_140000_api_cost_log_cache_columns.sql` ready. AH1 applies in prod alongside B2 sibling, then refreshes lock once via `scripts/refresh_applied_migrations_lock.py`. |
| **A3** Cache-key audit findings recorded | ✅ | This report §"Cache-key audit findings" — 4 dynamic-value findings, all ACCEPTED with justification, 0 blockers. |
| **A4** Kill-switch works | ✅ unit-tested | `tests/test_prompt_caching_1.py::test_build_kill_switch_returns_passthrough` — `BAKER_PROMPT_CACHE_ENABLED=false` → plain string + tool list. Manual prod test pending env-var flip per Sequencing step 7. |
| **A5** Telemetry columns populate | ⏸ Live-traffic gate | Schema + write path landed. `SELECT cache_read_input_tokens FROM api_cost_log WHERE source='agent_loop_streaming' ORDER BY logged_at DESC LIMIT 5` runnable post-deploy. |
| **A6** ≥€4/day savings vs baseline | ⏸ +24h gate | Pre-/post-ship SQL queued in runbook. Measured at +24h post env-var flip per Sequencing step 8. |
| **A7** ≥60% cache savings ratio | ⏸ +24h gate | SQL queued in runbook. |
| **A8** No quality regression | ⏸ Manual gate | 10 prompt eyeball-test pending Director post-deploy. |
| **A9** Cost-control runbook landed | ✅ | `_ops/processes/cost-control-runbook.md` |
| **A10** `feature-dev:code-reviewer` 2nd-pass | ⏸ Reviewer gate | AH1 dispatches per brief Sequencing §"Reviewer SLA". |

---

## Live pytest output (Lesson #52 — no by-inspection)

Filtered to test files exercising the changed code paths
(`orchestrator/cost_monitor.py`, `orchestrator/agent.py` helper). Full
suite has 129 pre-existing collection errors / failures from Python 3.9
vs 3.11+ syntax (`int | None` PEP 604) — environmental, identical on
`main`.

```
$ python3 -m pytest tests/test_prompt_caching_1.py tests/test_prompt_cache_audit.py tests/test_cost_gate.py -v

============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
collected 40 items

tests/test_prompt_caching_1.py::test_calculate_cost_eur_zero_cache_matches_legacy_formula PASSED
tests/test_prompt_caching_1.py::test_calculate_cost_eur_cache_read_billed_at_10_percent PASSED
tests/test_prompt_caching_1.py::test_calculate_cost_eur_cache_creation_billed_at_125_percent PASSED
tests/test_prompt_caching_1.py::test_build_caches_system_and_marks_last_tool PASSED
tests/test_prompt_caching_1.py::test_build_kill_switch_returns_passthrough PASSED
tests/test_prompt_caching_1.py::test_build_gemini_guard_returns_passthrough PASSED
tests/test_prompt_caching_1.py::test_build_handles_empty_tools PASSED
tests/test_prompt_caching_1.py::test_log_api_cost_accepts_legacy_signature PASSED
tests/test_prompt_caching_1.py::test_log_api_cost_passes_cache_kwargs_to_calc PASSED
tests/test_prompt_cache_audit.py::test_audit_script_exits_zero_and_writes_report PASSED
tests/test_prompt_cache_audit.py::test_audit_identifies_cached_call_site PASSED
tests/test_prompt_cache_audit.py::test_cache_control_block_shape_in_anthropic_client PASSED
tests/test_prompt_cache_audit.py::test_cache_control_present_in_three_hot_sites PASSED
tests/test_prompt_cache_audit.py::test_log_cache_usage_fires_baker_action PASSED
tests/test_prompt_cache_audit.py::test_log_cache_usage_silent_on_missing_store PASSED
tests/test_prompt_cache_audit.py::test_log_cache_usage_silent_on_malformed_usage PASSED
tests/test_prompt_cache_audit.py::test_audit_classifies_below_threshold PASSED
tests/test_cost_gate.py::test_daily_cap_default_is_50_eur PASSED
tests/test_cost_gate.py::test_daily_cap_env_override PASSED
tests/test_cost_gate.py::test_daily_cap_malformed_falls_back PASSED
tests/test_cost_gate.py::test_daily_cap_negative_falls_back PASSED
tests/test_cost_gate.py::test_failure_threshold_default_is_3 PASSED
tests/test_cost_gate.py::test_failure_threshold_env_override PASSED
tests/test_cost_gate.py::test_estimate_zero_for_empty_signal PASSED
tests/test_cost_gate.py::test_estimate_grows_with_signal_size PASSED
tests/test_cost_gate.py::test_estimate_tolerates_missing_keys PASSED
tests/test_cost_gate.py::test_circuit_closed_below_threshold PASSED
tests/test_cost_gate.py::test_circuit_open_at_threshold_without_probe PASSED
tests/test_cost_gate.py::test_circuit_closes_after_probe_reset PASSED
tests/test_cost_gate.py::test_circuit_stays_open_inside_probe_cooldown PASSED
tests/test_cost_gate.py::test_can_fire_step5_fire_on_healthy_state PASSED
tests/test_cost_gate.py::test_can_fire_step5_daily_cap_exceeded PASSED
tests/test_cost_gate.py::test_can_fire_step5_circuit_open_before_cap_check PASSED
tests/test_cost_gate.py::test_can_fire_step5_uses_estimate_against_today_sum PASSED
tests/test_cost_gate.py::test_record_opus_failure_increments_and_returns_count PASSED
tests/test_cost_gate.py::test_record_opus_success_resets_counter PASSED
tests/test_cost_gate.py::test_reset_opus_circuit_wipes_state PASSED
tests/test_cost_gate.py::test_record_opus_failure_does_not_commit PASSED
tests/test_cost_gate.py::test_record_opus_success_does_not_commit PASSED
tests/test_cost_gate.py::test_can_fire_step5_does_not_commit PASSED

======================== 40 passed, 1 warning in 18.54s ========================
```

Full-suite regression check: branch failures (129) ⊆ baseline-`main`
failures (136). Diff `comm -23 branch baseline` = empty. My branch
introduces zero new failures and resolves seven (the new test file's
prod code).

---

## Files changed

```
 orchestrator/agent.py                                                 | +47 lines
 orchestrator/cost_monitor.py                                          | +44 -10 lines
 _ops/processes/cost-control-runbook.md                                | NEW (102 lines)
 migrations/20260505_140000_api_cost_log_cache_columns.sql             | NEW (28 lines)
 tests/test_prompt_caching_1.py                                        | NEW (160 lines)
 briefs/_reports/B1_baker_prompt_caching_20260505.md                   | NEW (this file)
```

---

## Hand-off

PR opens against `main` from `b1/baker-prompt-caching-1`. AH1 owns:
1. Live pytest GREEN spot-check (link above).
2. AH2 `/security-review` (Tier-A trigger §1+§2 — agent core + DB schema).
3. Architect spot-check.
4. `feature-dev:code-reviewer` 2nd-pass.
5. Merge → deploy with `BAKER_PROMPT_CACHE_ENABLED=false` for one cycle.
6. After 1h clean cycle, flip env-var to `true`. Record flip timestamp.
7. +24h: run A6 + A7 SQL (queued in runbook); revert via env-var if either fails.
8. Signal AH1 to proceed with `BRIEF_BAKER_COST_INSTRUMENTATION_1` (B2 sibling).

**Mailbox hygiene:** AH1 marks `briefs/_tasks/CODE_1_PENDING.md` COMPLETE
on PR merge per `_ops/processes/b-code-dispatch-coordination.md` §3.
