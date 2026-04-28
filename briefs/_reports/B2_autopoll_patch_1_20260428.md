# Ship Report — AUTOPOLL_PATCH_1

**B-code:** B2
**Brief:** `briefs/BRIEF_AUTOPOLL_PATCH_1.md`
**Branch:** `autopoll-patch-1`
**Authority:** AI Head A cross-team review of PR #69 surfaced 3 OBS findings; AI Head B (M2 lane) drafted patch brief; Director cleared for ship via paste-block wake.
**Date:** 2026-04-28

## What shipped

Three surgical fixes folded into the merged-to-main autopoll v1 (PR #69 squashed as `af97a86`):

1. **OBS-1 (HIGH)** — idle-counter persistence via `~/.autopoll_state/{b_code}.yaml`. Added `read_idle_count`, `increment_idle_count`, `reset_idle_count` to `scripts/autopoll_state.py`. Q2 stop condition #2 (3 consecutive idle wakes → STOP) now structurally implementable across stateless wakes.
2. **OBS-2 (MEDIUM)** — protocol-doc fix. Phase 3 step 8 push-reject path now `git reset --hard origin/main && git pull --rebase --quiet` before re-reading state. Avoids dirty-tree deadlock on LWW-Q6 conflicts.
3. **OBS-3 (LOW)** — `_split_frontmatter` wraps `yaml.safe_load` in `try/except yaml.YAMLError as e: raise ValueError(...) from e`. Existing catchers in `read_state` and `find_stale_claims` continue to work on malformed YAML; AI Head A watchdog no longer crashes on a single bad mailbox.

## Files modified

- `scripts/autopoll_state.py` — +43 LOC (3 new functions + 4-line YAMLError wrap)
- `_ops/processes/b-code-autopoll-protocol.md` — 4 surgical edits (Phase 1 step 2, Phase 2 step 4 tail, Phase 3 step 5a, Phase 3 step 8)
- `tests/test_autopoll_state.py` — +56 LOC (5 new tests #21-#25, plus `_split_frontmatter` import)

## Quality Checkpoint #1 — pytest 25/25 green

```
$ python3 -m pytest tests/test_autopoll_state.py -v
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
collecting ... collected 25 items

tests/test_autopoll_state.py::test_read_state_parses_frontmatter PASSED  [  4%]
tests/test_autopoll_state.py::test_read_state_missing_frontmatter_raises PASSED [  8%]
tests/test_autopoll_state.py::test_read_state_unterminated_frontmatter_raises PASSED [ 12%]
tests/test_autopoll_state.py::test_transition_open_to_in_progress_auto_populates_claimed_at PASSED [ 16%]
tests/test_autopoll_state.py::test_transition_explicit_claimed_at_is_respected PASSED [ 20%]
tests/test_autopoll_state.py::test_transition_illegal_open_to_complete_rejected PASSED [ 24%]
tests/test_autopoll_state.py::test_transition_invalid_status_rejected PASSED [ 28%]
tests/test_autopoll_state.py::test_transition_legal_chain_in_progress_to_blocked_to_in_progress PASSED [ 32%]
tests/test_autopoll_state.py::test_transition_complete_to_retired_legal_then_terminal PASSED [ 36%]
tests/test_autopoll_state.py::test_transition_in_progress_to_open_for_stale_recovery PASSED [ 40%]
tests/test_autopoll_state.py::test_body_preservation_byte_perfect_after_round_trip PASSED [ 44%]
tests/test_autopoll_state.py::test_heartbeat_updates_field_only PASSED   [ 48%]
tests/test_autopoll_state.py::test_find_stale_claims_empty_dir_returns_empty PASSED [ 52%]
tests/test_autopoll_state.py::test_find_stale_claims_skips_open_and_fresh PASSED [ 56%]
tests/test_autopoll_state.py::test_find_stale_claims_returns_only_stale PASSED [ 60%]
tests/test_autopoll_state.py::test_find_stale_claims_skips_no_heartbeat_yet PASSED [ 64%]
tests/test_autopoll_state.py::test_legal_transitions_table_matches_brief PASSED [ 68%]
tests/test_autopoll_state.py::test_push_state_transition_dual_channel_high_signal PASSED [ 72%]
tests/test_autopoll_state.py::test_push_state_transition_low_signal_skips_dm PASSED [ 76%]
tests/test_autopoll_state.py::test_push_state_transition_silent_on_import_failure PASSED [ 80%]
tests/test_autopoll_state.py::test_idle_count_starts_at_zero PASSED      [ 84%]
tests/test_autopoll_state.py::test_increment_idle_count_returns_new_value PASSED [ 88%]
tests/test_autopoll_state.py::test_reset_idle_count_clears_state PASSED  [ 92%]
tests/test_autopoll_state.py::test_idle_count_per_b_code_isolation PASSED [ 96%]
tests/test_autopoll_state.py::test_split_frontmatter_malformed_yaml_raises_valueerror PASSED [100%]

============================== 25 passed in 0.28s ==============================
```

## Quality Checkpoint #2 — syntax check

```
$ python3 -c "import py_compile; py_compile.compile('scripts/autopoll_state.py', doraise=True)" && echo "syntax OK"
syntax OK
```

## Quality Checkpoint #3 — idle-counter API smoke test

```
$ rm -rf ~/.autopoll_state
$ python3 -c "from scripts.autopoll_state import read_idle_count, increment_idle_count, reset_idle_count; \
    assert read_idle_count('b3') == 0; \
    assert increment_idle_count('b3') == 1; \
    assert increment_idle_count('b3') == 2; \
    assert read_idle_count('b3') == 2; \
    assert read_idle_count('b2') == 0; \
    reset_idle_count('b3'); \
    assert read_idle_count('b3') == 0; \
    print('idle counter API OK')"
idle counter API OK
$ rm -rf ~/.autopoll_state
```

Per-B-code isolation verified (b3 counter doesn't bleed into b2). State dir cleaned up after.

## Quality Checkpoint #4 — YAMLError → ValueError

```
$ python3 -c "
from scripts.autopoll_state import read_idle_count, _split_frontmatter
assert read_idle_count('b1') == 0
try:
    _split_frontmatter('---\nkey: [unclosed\n---\n')
except ValueError as e:
    assert 'malformed YAML' in str(e)
print('AUTOPOLL_PATCH_1 verified')
"
AUTOPOLL_PATCH_1 verified
```

## Quality Checkpoint #5 — protocol doc references

`_ops/processes/b-code-autopoll-protocol.md` Phase 1 step 2 references `read_idle_count('bN')`; Phase 2 step 4 tail references `increment_idle_count('bN')`; Phase 3 step 5a references `reset_idle_count('bN')`. All function names + arg shape match the API exactly. Phase 3 step 8 references `git reset --hard origin/main && git pull --rebase --quiet`. ✓

## Quality Checkpoint #7 — no commits to ~/.autopoll_state

`~/.autopoll_state/` lives at `$HOME`, outside any git repo. `git status` after smoke test shows only the 4 intentional files modified (`autopoll_state.py`, `protocol.md`, `test_autopoll_state.py`, `CODE_2_PENDING.md`) plus 3 pre-existing untracked report files unrelated to this patch.

## Lessons applied

- Lesson #34 / #42 / #44 — literal pytest stdout in ship report, no "by inspection".
- Lesson #47 — patch brief had explicit file:line refs; no codebase grep needed (this is a folding patch on already-merged code).
- Lesson #50 — patch lands BEFORE first overnight autopoll window opens (Q7 cohort B2 + B3 + AI Head A), so the OBS-1 stop-condition #2 gap never reaches production-affecting state.
- Lesson #52 — `/security-review` MANDATORY before merge. Trigger class LOW (no auth, DB writes, secrets, external API). Solo lane-owner pass sufficient — second-pair-review trigger NOT met.

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
