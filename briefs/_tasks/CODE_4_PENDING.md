---
status: PENDING
brief: briefs/BRIEF_PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1.md
brief_id: PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1
trigger_class: LOW (tool-description + small server-side validator; no auth/DB-schema/external-surface touch)
dispatched_at: 2026-05-16T08:50:00Z
dispatched_by: ai-head-2 (AH2) — Director redirect "use b1 or b4"
target: b4
prior_brief_complete: |
  SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1 shipped as PR #207 (merged
  2026-05-16, commit d8e9d2a) + ship report d807d5b. Mailbox flip to
  COMPLETE was pending AH1 housekeeping; this dispatch overwrites the
  slot with the new brief. The shipped scheduler work is preserved in
  briefs/_reports/ and is unaffected by this overwrite.
context: |
  Director live-corrected Baker 2026-05-16 08:12Z after stale AO capital-
  call answer in a meeting-prep briefing. Baker's _update_pm_state tool
  then wrote TWO NEW top-level keys (capital_call_EUR_7M + "AO April
  Capital Tranche (EUR 2.5M)") to pm_project_state.ao_pm.state_json
  BESIDE the stale capital_calls field — instead of patching the
  existing key.

  state_json now has three parallel facts about capital-call status.
  Future Opus reads will see all three; risk that next query picks the
  wrong one. The merge logic in store_back.py:5654-5658 is correct — the
  bug is upstream in the LLM's choice of new key names. Fix:
  tool-description instruction + server-side Levenshtein-similarity
  guard.

  Sister brief AO_PM_READ_CURATED_WIKI_1 is going to B1 in parallel
  (fixes the read-side root cause). Independent merge; either order.

  Sidecar after merge: AH1 or AH2 runs one-shot SQL to consolidate
  today's three parallel facts into the canonical capital_calls field.
  Track in tasks/lessons.md as 2026-05-16 scar.
review_chain:
  - AH1 cross-lane review (tool-description / prompt-engineering change;
    verify instructional language doesn't bloat tokens past budget)
  - NO /security-review (no auth/perimeter touch — pure tool semantics +
    similarity validator)
ship_gate: see brief §"Ship gate"
acceptance: see brief §"Acceptance criteria"
estimated: small · ~1-2 hours · 1 PR · Tier-B
branch_suggestion: b4/pm-state-update-patch-not-parallel-1
---

# CODE_4_PENDING — PM state-update parallel-keys fix — 2026-05-16

**Dispatched by:** AH2 (deputy) under Director redirect 2026-05-16 ~08:50Z ("use b1 or b4")
**Working dir:** `~/bm-b4`
**Branch:** `b4/pm-state-update-patch-not-parallel-1` off `main`

Pre-flight:
1. `git pull --ff-only origin main` in `~/bm-b4`.
2. Read `briefs/BRIEF_PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1.md` end-to-end.

---

## Scope (summary — see brief for full detail)

**Layer 1 (primary):** update `_update_pm_state` tool description in `orchestrator/agent.py` (around lines 967/971/2063 — the tool dispatch + the method definition). Add an explicit instruction: *"Before constructing `updates`, inspect existing state_json. Patch existing top-level keys when the same fact is already represented under a different name. Only introduce a new top-level key for a genuinely new concept not covered by any existing field."* Add a worked example.

**Layer 2 (defense-in-depth):** in `memory/store_back.py:update_pm_project_state`, before applying the merge, compute Levenshtein similarity between each NEW top-level key in `updates` and existing top-level keys in `state_json`. If similarity > 0.7 AND no exact-key match for the same semantic, REJECT the write with a structured error UNLESS `force=true` is set.

Both layers shipped together as one PR.

## Background context (read before starting)

- Empirical proof of the bug: query `SELECT jsonb_pretty(state_json) FROM pm_project_state WHERE pm_slug = 'ao_pm'`. The `capital_calls` field is byte-identical across versions 1-139 ("status: fully_funded — confirmed by Constantinos 03.04.2026"). The new parallel keys `capital_call_EUR_7M` + `"AO April Capital Tranche (EUR 2.5M)"` appeared at version 139 (2026-05-16 08:12:31Z) per `pm_state_history` row #337 (`mutation_source = agent_tool`).
- Director catch at chat 2026-05-16 08:12Z is the trigger; this is the write-side fix. Sister brief (AO_PM_READ_CURATED_WIKI_1, B1 lane) is the read-side fix.

## Out of scope

- Cleanup of today's existing parallel keys — separate housekeeping task (AH1/AH2 one-shot SQL post-merge).
- MOVIE-AM tool description — same pattern may apply; verify post-merge, ship separately if needed.
- Changing the merge logic itself (`store_back.py:5654-5658`) — bug is upstream, not in merge.

## Reporting

- Bus-post `deputy` (AH2) on PR open + ship.
- After AH1 cross-lane review verdict, post AH1 verdict to bus + flip mailbox to COMPLETE.

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## UPDATE — 2026-05-16T09:55:00Z — AH1 REQUEST_CHANGES rework pushed

PR #209 reworked at commit `ead947a` addressing both HIGH findings from
AH1 cross-lane review (bus msg #294):

- **HIGH-1** — connection double-put on rejection path: removed manual
  `_put_conn(conn)` from rejection branch in `update_pm_project_state`;
  enclosing `try/finally` now solely owns connection cleanup. Matches
  the function's success-path pattern (line 5809).
- **HIGH-2** — token-overlap denominator: `detect_parallel_pm_key` now
  uses harmonic mean `2*|shared|/(|new|+|ek|)` instead of
  `|shared|/min(|new|,|ek|)`. Preserves `capital_call_EUR_7M` →
  `capital_calls` catch (both single-token, harmonic = 1.0). Lets
  through false-positive `leverage` vs
  `leverage_decline_attribution_to_2024_baseline` (harmonic = 0.4).
- **New regression test**: `test_detect_parallel_pm_key_single_shared_token_does_not_overblock`
  pins both AH1's worked example (`tranche_overview` vs `tranches_2026`)
  and the conceptual false-positive class.
- **Trade-off noted**: `'AO April Capital Tranche (EUR 2.5M)'` against
  `capital_calls` (harmonic = 0.667) now falls through Layer 2; Layer 1
  (tool-description prompt) carries that catch. Documented in
  `detect_parallel_pm_key` docstring + updated assertion in
  `test_detect_parallel_pm_key_catches_renamed_key`.
- **Deferred** (per AH1 "defer MED/LOW unless trivially bundled"): M1
  positional-arg in `update_ao_project_state` · M2 docstring force-fwd
  note · M3 `_Cur` rowcount default · L2 baker_actions truncation
  300/500. Flag for follow-up ticket.

Ship gate: `python3.12 -m pytest tests/test_pm_state_write.py -v` →
11/11 green (0.32s). `py_compile memory/store_back.py` → OK.

Ship report addendum committed at `briefs/_reports/B4_PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1_20260516.md`.
Bus-post pending to `lead` with topic `ship/pm-state-update-patch-not-parallel-1-rework`.
