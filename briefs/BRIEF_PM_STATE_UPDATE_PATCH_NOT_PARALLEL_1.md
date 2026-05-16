# BRIEF: PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1 — `_update_pm_state` tool must patch existing keys, not create parallel ones

**Status:** V0.1 — ready to dispatch
**Author:** AH2 (terminal session, 2026-05-16)
**Reviewer:** AH1 cross-lane (no `/security-review` mandate — tool-description + validator change, no auth/perimeter touch)
**Target build lane:** B2 (BRIEF_CAPABILITY_THREADS_1 author lane) or B4
**Tier:** B (small — tool prompt-engineering + server-side validator; ~1-2 hours)
**Branch convention:** `b<N>/pm-state-update-patch-not-parallel-1`
**Trigger:** Director live-correction conversation 2026-05-16 08:12Z. Baker received "ao transferred 2.5 m - you need to check with AO PM" and called `_update_pm_state` to apply the correction. The tool wrote TWO NEW top-level keys to `pm_project_state.ao_pm.state_json` (`capital_call_EUR_7M` + `"AO April Capital Tranche (EUR 2.5M)"`), leaving the existing stale `capital_calls` field (`"status: fully_funded — confirmed by Constantinos 03.04.2026"`) untouched. State now contains both stale and corrected facts — risk that the next AO-PM query picks the wrong one.

---

## Problem

`orchestrator/agent.py:2063 _update_pm_state` delegates to `memory/store_back.py:5610 update_pm_project_state`. The merge logic at `store_back.py:5654-5658`:

```python
for k, v in updates.items():
    if isinstance(v, dict) and isinstance(existing.get(k), dict):
        existing[k].update(v)
    else:
        existing[k] = v
```

This is a faithful shallow top-level merge. If the LLM-constructed `updates` dict uses a NEW top-level key name (e.g., `capital_call_EUR_7M` instead of the existing `capital_calls`), the merge correctly appends the new key. The merge logic is not the bug.

**The bug is upstream — in the tool description / system prompt.** The LLM (Opus) chose new key names because:
1. No instruction telling it to inspect existing keys before constructing updates.
2. No instruction that semantically-equivalent facts should patch the existing key.
3. The tool description (in agent.py around line 967-971 where the tool is dispatched) likely does not show the existing state_json shape at decision time, so the LLM constructs from scratch.

Empirical proof (today's mutation, agent.py:2063 invoked at 2026-05-16 08:12:31Z):

| Existing key | Existing value | LLM's update | Result |
|---|---|---|---|
| `capital_calls` | `{status: "fully_funded — confirmed by Constantinos 03.04.2026", source_of_truth: "..."}` | not referenced | UNTOUCHED (stale) |
| (none) | — | `capital_call_EUR_7M: {status: "april_tranche_received", tranches: [...]}` | NEW top-level key added |
| (none) | — | `"AO April Capital Tranche (EUR 2.5M)": {status: "received", detail: "..."}` | NEW top-level key added |

Now state_json has three parallel facts about capital calls. Future Opus reads will see all three. Worse, `capital_call_EUR_7M` and `"AO April Capital Tranche (EUR 2.5M)"` are themselves redundant — both encode the same fact at different granularities.

## Fix — two layers

**Layer 1 (primary): tool-description + system-prompt instruction.**
Update the `_update_pm_state` tool description (wherever it's registered as an Anthropic tool — likely in agent.py around the dispatch site lines 967/971) to:

1. State explicitly: *"Before constructing `updates`, inspect the existing state_json (use `_get_pm_state` first if not already loaded). Patch existing keys when the same fact is already represented under a different name. Only introduce a new top-level key for a genuinely new concept not covered by any existing field."*
2. Add a worked example showing patch-vs-new-key decisions.
3. Add a JSON-schema-style hint: `"prefer_existing_keys": ["capital_calls", "investment_channels", "rg7_equity", "financial_summary", "ao_psychology", ...]` derived from the live state's top-level shape.

**Layer 2 (defense-in-depth): server-side similarity guard.**
In `update_pm_project_state`, before applying the merge:

1. For each `k` in `updates` that does NOT match an existing key, compute a similarity score against existing top-level keys (Levenshtein distance / token overlap). If score > threshold AND no existing-key match for the same semantic, REJECT the write with a structured error: `{"error": "Possible parallel key. 'capital_call_EUR_7M' looks similar to existing 'capital_calls'. Patch the existing key, or override with `force=true`."}`.
2. The agent.py wrapper catches the error and surfaces it back to the LLM, which then retries with the correct key.
3. Log the rejection to `baker_actions` for audit.

Layer 1 alone catches ~80% of cases. Layer 2 catches the remainder + provides scar-tissue for future LLM regressions.

## Acceptance criteria

1. Tool description for `_update_pm_state` explicitly instructs the LLM to inspect existing keys + patch instead of parallel.
2. Server-side similarity guard rejects writes where a new top-level key has Levenshtein-similarity > 0.7 to an existing key without `force=true`.
3. Unit test: simulate an LLM call passing `updates = {"capital_call_EUR_7M": {...}}` against an existing state with `capital_calls`. Assert: rejected with structured error.
4. Unit test: same as 3 but with `force=true`. Assert: write succeeds.
5. Unit test: passing `updates = {"capital_calls": {"status": "april_tranche_received_2026-04-24"}}`. Assert: existing `capital_calls` patched.
6. Backfill / cleanup test (one-off, separate ticket): consolidate the existing `capital_call_EUR_7M` + `"AO April Capital Tranche (EUR 2.5M)"` parallel keys into the canonical `capital_calls` field. Track as a separate housekeeping commit, not in this PR.

## Out of scope

- The cleanup of the EXISTING parallel keys created today (separate housekeeping task — small, can be done by AH1/AH2 via single SQL UPDATE after this PR merges).
- Curated wiki read-path fix (sister brief: `AO_PM_READ_CURATED_WIKI_1`). Independent change.
- Changing the merge logic itself (`store_back.py:5654-5658`) — the bug is upstream, not in the merge.
- MOVIE-AM tool description (same pattern; ship separately if it has the same bug — verify post-merge).

## Ship gate

1. `pytest tests/test_pm_state_write.py -v` — all green; +3 new tests per acceptance #3-5.
2. `python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"` — passes.
3. PR description includes literal pytest stdout.
4. AH1 cross-lane review — tool-description change is prompt-engineering territory; verify the instructional language doesn't bloat tokens past meaningful budget.
5. Post-merge cleanup task: AH1 or AH2 runs one-shot SQL to consolidate today's parallel keys into `capital_calls`. Record in tasks/lessons.md as scar-tissue from 2026-05-16.

## Files touched

**Modify (in-repo):**
- `orchestrator/agent.py` — tool description / docstring at `_update_pm_state` definition + tool-registration site (around lines 967/971/2063). Add `force` parameter.
- `memory/store_back.py:update_pm_project_state` — add similarity guard before merge. ~20 lines.
- `tests/test_pm_state_write.py` — add 3 new tests per acceptance criteria.

**Do NOT touch:**
- `pm_state_history` schema or insert logic.
- `extract_and_update_pm_state` (the Opus auto-extraction path) — it constructs updates from extraction, not from agent-tool, and is a separate concern.
- `pm_signal_detector.py`.
- Dashboard sidebar rendering.

## Estimated complexity

Small · ~1-2 hours · 1 PR · Tier-B prompt-engineering + small validator · no `/security-review` re-pass (no auth/perimeter touch; pure tool semantics).

## Sister brief

`AO_PM_READ_CURATED_WIKI_1` — fixes the read-side root cause that triggered today's incident. Independent merge.
