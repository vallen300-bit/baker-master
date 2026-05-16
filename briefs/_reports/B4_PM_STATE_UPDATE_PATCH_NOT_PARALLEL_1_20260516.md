---
brief: BRIEF_PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1
mailbox_commit: 419dc6d
dispatched_by: AH2 (deputy) under Director redirect 2026-05-16 ~08:50Z
dispatched_at: 2026-05-16T08:50:00Z
claimed_at: 2026-05-16T08:58:00Z
shipped_at: 2026-05-16T09:07:00Z
status: PR_OPEN
pr: https://github.com/vallen300-bit/baker-master/pull/209
branch: b4/pm-state-update-patch-not-parallel-1
commit: 427eea3
trigger_class: LOW
reviewer: AH1 cross-lane (no /security-review per brief)
bus_post: msg #286 (topic ship/pm-state-update-patch-not-parallel-1 → lead)
---

# B4 ship report — PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1

## What shipped

Two-layer fix for the agent-tool `_update_pm_state` parallel-key bug that
Director caught 2026-05-16 08:12Z (stale AO capital-call answer; Baker then
wrote two NEW top-level keys to `pm_project_state.ao_pm.state_json` instead
of patching the existing `capital_calls` field).

### Layer 1 — tool description (LLM-prompt-engineering, primary)

`orchestrator/agent.py` — `update_ao_state` (line 757) and `update_pm_state`
(line 801) tool descriptions now explicitly instruct the LLM to inspect the
existing state and patch existing keys when the same fact is already
represented. Includes worked example (`capital_calls` → patch in place;
do not add `capital_call_EUR_7M` or `April Capital Tranche`). Schema gets
a new optional `force` boolean for genuine new-concept writes.

`_update_pm_state` handler (line 2063) forwards `force` from input to
`update_pm_project_state` and JSON-serialises any rejection-dict so the LLM
sees the structured error in the next turn.

### Layer 2 — server-side similarity guard (defence-in-depth)

`memory/store_back.py`:

- New module-level helper `detect_parallel_pm_key(new_key, existing_keys,
  threshold=0.7)` — uses max-of `difflib.SequenceMatcher.ratio` and
  shared-significant-token (length ≥ 6, alphabetic) overlap. Catches both
  the rename pattern (`capital_call_EUR_7M` ~ `capital_calls`) and the
  long-form pattern (`"AO April Capital Tranche (EUR 2.5M)"` via the
  shared root `capital`).
- `update_pm_project_state` gets a `force: bool = False` kwarg. When
  `mutation_source == 'agent_tool'` and `force=False`, every new top-level
  key in `updates` is checked against existing top-level keys; first
  candidate that clears the threshold short-circuits the merge with a
  structured-error dict and logs the rejection to `baker_actions`.
- Exact-match (case / punctuation-insensitive) is a legitimate patch — the
  helper returns None so the merge proceeds normally.
- Other callers (`extract_and_update_pm_state` in `capability_runner.py`,
  `flag_pm_signal` in `pm_signal_detector.py`, the deprecated
  `update_ao_project_state` wrapper) construct updates from fixed schemas
  and pass `mutation_source ∈ {sidebar, decomposer, pm_signal_*, auto, …}`
  — all bypass the guard. Zero blast radius outside the agent-tool path.

## Hard ship gate — evidence

### 1. py_compile both modules

```
$ python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True); py_compile.compile('orchestrator/agent.py', doraise=True); print('OK')"
OK
```

### 2. Literal pytest — `tests/test_pm_state_write.py` all green

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b4
plugins: langsmith-0.7.38, anyio-4.12.1
collected 10 items

tests/test_pm_state_write.py::test_extract_and_update_pm_state_tags_mutation_source PASSED [ 10%]
tests/test_pm_state_write.py::test_sidebar_hook_fires_on_ao_pm PASSED    [ 20%]
tests/test_pm_state_write.py::test_sidebar_hook_skipped_for_non_pm_capability PASSED [ 30%]
tests/test_pm_state_write.py::test_backfill_idempotency_skips_processed_rows PASSED [ 40%]
tests/test_pm_state_write.py::test_flag_pm_signal_push_slack_only_when_requested PASSED [ 50%]
tests/test_pm_state_write.py::test_detect_parallel_pm_key_catches_renamed_key PASSED [ 60%]
tests/test_pm_state_write.py::test_detect_parallel_pm_key_ignores_exact_match PASSED [ 70%]
tests/test_pm_state_write.py::test_update_pm_state_rejects_parallel_key_via_agent_tool PASSED [ 80%]
tests/test_pm_state_write.py::test_update_pm_state_force_overrides_parallel_guard PASSED [ 90%]
tests/test_pm_state_write.py::test_update_pm_state_patches_existing_key_via_agent_tool PASSED [100%]

======================== 10 passed, 2 warnings in 0.23s ========================
```

Tests #1–#5 are the pre-existing BRIEF_PM_SIDEBAR_STATE_WRITE_1 ship-gate
suite — confirms no regression from the change. Tests #6–#10 are the new
PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1 acceptance suite (brief §"Acceptance
criteria" items 3, 4, 5 plus two helper-unit tests for the new
`detect_parallel_pm_key` function).

### 3. Brief acceptance criteria — coverage

| # | Criterion | Coverage |
|---|---|---|
| 1 | Tool description instructs LLM to inspect + patch | `orchestrator/agent.py` lines 757-805 (update_ao_state) + 815-870 (update_pm_state) — worked example + preferred-key list |
| 2 | Server-side guard rejects similarity > 0.7 without force=true | `memory/store_back.py` `detect_parallel_pm_key()` + agent_tool branch in `update_pm_project_state` |
| 3 | Unit test: parallel key → structured error rejection | `test_update_pm_state_rejects_parallel_key_via_agent_tool` |
| 4 | Unit test: force=True → write succeeds | `test_update_pm_state_force_overrides_parallel_guard` |
| 5 | Unit test: existing-key patch succeeds | `test_update_pm_state_patches_existing_key_via_agent_tool` |
| 6 | Backfill/cleanup test (separate ticket) | Out of scope — AH1/AH2 one-shot SQL post-merge per brief |

## Out of scope (per brief)

- Cleanup of today's three existing parallel keys (`capital_call_EUR_7M`,
  `"AO April Capital Tranche (EUR 2.5M)"`, plus the stale `capital_calls`
  reconciliation) — AH1/AH2 housekeeping SQL after merge.
- MOVIE-AM tool description — same pattern may apply; verify post-merge.
- Changing the merge logic itself (`store_back.py:5654-5658`) — bug is
  upstream, merge is faithful.
- Sister brief `AO_PM_READ_CURATED_WIKI_1` — independent B1 lane.

## Decisions logged inline (no Director consult required — Tier-B)

- **Guard scope = `mutation_source == 'agent_tool'` only.** The brief
  doesn't pin a scope; "every caller passes `force=True` to opt out" was
  the alternative. Chose narrow scope because the bug Director caught is
  exclusively on the agent-tool path; other callers build updates from
  fixed schemas and have never produced parallel keys empirically.
  Zero-regression default, with the `force` parameter still available as
  the escape hatch on the LLM path.
- **Similarity metric = `difflib.SequenceMatcher.ratio()` (stdlib).** The
  brief says "Levenshtein / token overlap"; SequenceMatcher uses
  Ratcliff-Obershelp not Levenshtein but the brief is explicitly metric-
  agnostic ("similarity score"). No new dependency. Confirmed empirically
  on the two real cases.
- **Combined signal = max(ratio, shared-significant-token-overlap).** The
  rename case (`capital_call_EUR_7M`) clears the ratio threshold; the
  long-form case (`"AO April Capital Tranche…"`) only clears the
  token-overlap signal because of string-length skew. Combining both is
  necessary to catch both empirical cases without dropping the threshold
  so low it false-positives on every new key.

## Reporting

- Bus-post `lead` on PR open — msg #286, topic `ship/pm-state-update-patch-not-parallel-1`.
- After AH1 cross-lane review verdict: post verdict to bus + flip mailbox
  to COMPLETE.

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
