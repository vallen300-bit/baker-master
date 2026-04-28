# Ship Report — B_CODE_AUTOPOLL_1 (B1, 2026-04-27)

**Brief:** `briefs/BRIEF_B_CODE_AUTOPOLL_1.md` (commit `8ca8b7e`)
**Branch:** `b-code-autopoll-1`
**Builder:** Code Brisen #1
**Trigger class:** MEDIUM (cross-team review pre-merge per
`_ops/ideas/2026-04-24-b1-situational-review-trigger.md`)

## EXPLORE (per dispatch §"Critical pre-build EXPLORE")

- `python3 -c "import yaml; print(yaml.__version__)"` → `6.0.3` ✓
- `grep pyyaml requirements.txt` → `PyYAML>=6.0` present ✓
- `outputs/slack_notifier.py:111` → `def post_to_channel(channel_id: str,
  text: str) -> bool` matches brief ✓
- `outputs/slack_notifier.py:115` → Director DM `D0AFY28N030` ref ✓
- `config/settings.py:201` → `cockpit_channel_id` default `C0AF4FVN3FB` ✓
- `_ops/processes/` did not exist; created.
- `git log --oneline --grep='autopoll'` → empty (greenfield, per dispatch).

## Ship gate — literal `pytest tests/test_autopoll_state.py -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0 -- /Library/Developer/CommandLineTools/usr/bin/python3
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b1
plugins: anyio-4.12.1, mock-3.15.1, langsmith-0.4.37
collecting ... collected 20 items

tests/test_autopoll_state.py::test_read_state_parses_frontmatter PASSED  [  5%]
tests/test_autopoll_state.py::test_read_state_missing_frontmatter_raises PASSED [ 10%]
tests/test_autopoll_state.py::test_read_state_unterminated_frontmatter_raises PASSED [ 15%]
tests/test_autopoll_state.py::test_transition_open_to_in_progress_auto_populates_claimed_at PASSED [ 20%]
tests/test_autopoll_state.py::test_transition_explicit_claimed_at_is_respected PASSED [ 25%]
tests/test_autopoll_state.py::test_transition_illegal_open_to_complete_rejected PASSED [ 30%]
tests/test_autopoll_state.py::test_transition_invalid_status_rejected PASSED [ 35%]
tests/test_autopoll_state.py::test_transition_legal_chain_in_progress_to_blocked_to_in_progress PASSED [ 40%]
tests/test_autopoll_state.py::test_transition_complete_to_retired_legal_then_terminal PASSED [ 45%]
tests/test_autopoll_state.py::test_transition_in_progress_to_open_for_stale_recovery PASSED [ 50%]
tests/test_autopoll_state.py::test_body_preservation_byte_perfect_after_round_trip PASSED [ 55%]
tests/test_autopoll_state.py::test_heartbeat_updates_field_only PASSED   [ 60%]
tests/test_autopoll_state.py::test_find_stale_claims_empty_dir_returns_empty PASSED [ 65%]
tests/test_autopoll_state.py::test_find_stale_claims_skips_open_and_fresh PASSED [ 70%]
tests/test_autopoll_state.py::test_find_stale_claims_returns_only_stale PASSED [ 75%]
tests/test_autopoll_state.py::test_find_stale_claims_skips_no_heartbeat_yet PASSED [ 80%]
tests/test_autopoll_state.py::test_legal_transitions_table_matches_brief PASSED [ 85%]
tests/test_autopoll_state.py::test_push_state_transition_dual_channel_high_signal PASSED [ 90%]
tests/test_autopoll_state.py::test_push_state_transition_low_signal_skips_dm PASSED [ 95%]
tests/test_autopoll_state.py::test_push_state_transition_silent_on_import_failure PASSED [100%]

============================== 20 passed in 0.07s ==============================
```

20 / 20 PASS (brief required ≥12).

## Quality Checkpoints

| # | Check | Result |
|---|---|---|
| 1 | `pytest tests/test_autopoll_state.py -v` ≥12 tests green | ✓ 20/20 (literal stdout above) |
| 2 | `py_compile scripts/autopoll_state.py` exit 0 | ✓ |
| 3 | `read_state('briefs/_tasks/CODE_1_PENDING.md')` returns dict with `status` | ✓ — `{'status': 'OPEN', 'brief': 'briefs/BRIEF_B_CODE_AUTOPOLL_1.md', ...}` (CODE_3 retrofit deferred to AI Head A per dispatch) |
| 4 | autopoll-protocol exists, ≥7 Phase sections | ✓ 7 phases |
| 5 | autopoll-startup includes paste-blocks for `b2`, `b3`, `aihead1` | ✓ 3 blocks |
| 6 | `tasks/lessons.md` ends with Lesson #50 | ✓ `grep -c '^### 50\.' tasks/lessons.md` → 1 |
| 7 | `scripts/autopoll_state.py` zero DB writes | ✓ `grep -E "psycopg\|conn\|cursor\|store_back"` empty |
| 8 | `scripts/autopoll_state.py` zero secret refs | ✓ `grep -iE "password\|token\|secret\|api.key"` empty (only `BAKER_OVERNIGHT_CHANNEL_ID` via `os.getenv`, which is a public channel ID) |
| 9 | PR description includes Q1-Q8 + Lesson #50 quote + Lesson #48 not removed | AI Head A responsibility — PR description below conforms |
| 10 | `/security-review` on PR before merge | AI Head A responsibility |

## Q1-Q8 defaults (Director ratified 2026-04-27)

- Q1 = 900s wake interval
- Q2 = both stop conditions (`OVERNIGHT_AUTONOMY_UNTIL` AND 3-idle counter)
- Q3 = multi-stage block (`BLOCKED-AI-HEAD-Q` distinct from `BLOCKED-DIRECTOR-Q`)
- Q4 = both Slack channels (DM `D0AFY28N030` for high-signal,
  `BAKER_OVERNIGHT_CHANNEL_ID` for every transition)
- Q5 = 60-min stale-claim recovery
- Q6 = last-writer-wins on git push race
- Q7 = B2 + B3 + AI Head A only first overnight
- Q8 = Lesson #48 window-scoped exception (NOT removed) → Lesson #50

## Files modified

NEW:
- `scripts/autopoll_state.py` (state machine helper, ~155 LOC)
- `tests/test_autopoll_state.py` (20 pytest cases)
- `_ops/processes/b-code-autopoll-protocol.md` (Phase 1-7 + hard rules)
- `_ops/processes/b-code-autopoll-startup.md` (b2/b3/aihead1 paste-blocks)

UPDATE:
- `briefs/_tasks/README.md` (state-machine schema + transitions section)
- `tasks/lessons.md` (append Lesson #50)

NOT TOUCHED (per dispatch):
- `outputs/slack_notifier.py` — IMPORT only
- `config/settings.py` — `BAKER_OVERNIGHT_CHANNEL_ID` read directly via
  `os.getenv`
- `briefs/_tasks/CODE_2_PENDING.md` / `CODE_3_PENDING.md` — retrofit
  deferred to AI Head A post-merge per dispatch
- `_ops/processes/b-code-dispatch-coordination.md`,
  `triggers/embedded_scheduler.py`, all production Cortex / sentinel
  code

## Notes

- Local Python is 3.9.6; brief sample helper used PEP 604 union syntax
  (`str | Path`). Added `from __future__ import annotations` so the
  annotations stay deferred and tests run on 3.9 + 3.11.
- PyYAML `safe_load` auto-coerces ISO timestamp strings to
  `datetime.datetime`. `find_stale_claims` handles both string and
  datetime inputs in `last_heartbeat`.
- `push_state_transition` wraps both the `outputs.slack_notifier`
  import and the actual `post_to_channel` calls in try/except — silent
  skip on any failure, matches the brief's "best-effort, never raises"
  contract and `outputs/slack_notifier.py:142-144` non-fatal invariant.

## Co-authorship

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
