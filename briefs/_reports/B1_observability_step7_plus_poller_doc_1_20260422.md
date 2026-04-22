# B1 — OBSERVABILITY_STEP7_PLUS_POLLER_DOC_1 — ship report

**From:** Code Brisen #1
**To:** AI Head (reviewer: B3)
**Date:** 2026-04-22
**Branch:** `observability-step7-plus-poller-doc-1`
**Status:** SHIPPED — PR open, reviewer B3, full-suite pytest captured, zero regressions.

---

## Part A — Step 7 happy-path observability

### §before

`kbl/steps/step7_commit.py` emitted exactly **one** `emit_log` — the failure path at `_mark_commit_failed` (WARN on `commit_failed`). Every happy-path Step 7 completed silently. Successful deploys left no `kbl_log` trail; shadow-mode runs likewise (only `logger.info` → stdout, nothing in the table). This is the observability gap B2's CORTEX_GATE2 diagnostic flagged as gap #2.

### §after

7 happy-path `emit_log("INFO", _LOG_COMPONENT, signal_id, msg)` call sites added in `kbl/steps/step7_commit.py`, all inside `commit()`. Zero logic changes. Zero touches to `_git_add_commit` / `_git_push_with_retry` / `_atomic_write` / `_append_or_replace_stub` / `disable_push` branch structure / row state UPDATE at line ~260.

**Module constant added** (`kbl/steps/step7_commit.py:105`):

```python
_LOG_COMPONENT = "step7_commit"
```

Matches the `step5_opus._LOG_COMPONENT = "step5_opus"` pattern so `kbl_log WHERE component='step7_commit'` is the single predicate for all Step 7 trails.

**Call-site listing (file:line):**

| # | Line | Tag | Message shape |
|---|------|-----|---------------|
| 1 | `step7_commit.py:579` | Entry | `step7 entry: target={target_vault_path} primary_matter={primary_matter!r} stub_count={n}` |
| 2 | `step7_commit.py:606` | Vault lock acquired | `vault lock acquired: path={lock_path} timeout={flock_timeout}s` |
| 3 | `step7_commit.py:624` | Inv 4 guard pass | `inv4 guard pass: target={target_vault_path} (not Director-authored)` |
| 4 | `step7_commit.py:644` | Files written | `files written: main=1 stubs={n} final_markdown_len={n}` |
| 5 | `step7_commit.py:670` | Commit created | `commit created: sha={short_sha} message={message!r}` |
| 6a | `step7_commit.py:686` | Shadow-mode skip | `shadow-mode: skipping git push (BAKER_VAULT_DISABLE_PUSH=true, sha={short_sha})` — mirrors existing `logger.info` |
| 6b | `step7_commit.py:702` | Push success | `git push success: sha={short_sha} remote={git_remote} branch={_GIT_BRANCH}` |
| 7 | `step7_commit.py:716` | Signal completed | `signal completed: sha={short_sha} realized_stubs={n}` |

Only one of {6a, 6b} fires per call, per the `cfg.disable_push` gate. Brief asked for 6-8 sites; shipped 7 (entry + lock + guard + files + commit + {push-or-shadow} + completed).

**Preservation of existing trace:** the original `logger.info("step7 mock-mode: …")` line is kept intact (brief: "Keep both logs; don't replace logger.info"). The new shadow-mode `emit_log` is added alongside it so stdout traces are unchanged for anyone greeping the Render journal.

**What still emits WARN/ERROR:** `_mark_commit_failed` unchanged (WARN on any failure path, file line ~296). That's the existing gap-free failure trail.

---

## Part B — Fix stale `kbl/poller.py` reference

### §before

Two occurrences in `kbl/pipeline_tick.py` referenced a `kbl.poller` module that does not exist in this repo:

```python
# kbl/pipeline_tick.py:10-11 (module docstring)
``_process_signal_remote`` (Steps 1-6 only)
    Step 7 runs on Mac Mini via ``kbl.poller`` (direct import of
    ``step7_commit.commit``). ...
```

```python
# kbl/pipeline_tick.py:512 (function docstring)
Steps 1-6 only. Step 7 runs on Mac Mini via ``kbl.poller``. Do not
call from Mac Mini.
```

The actual Mac Mini Step 7 runner lives off-tree at `/Users/dimitry/baker-pipeline/poller.py` (AI Head verified earlier today via SSH).

### §after

Both occurrences rewritten with the off-tree path + LaunchAgent + wrapper + env-source + interval context the brief provided. No new file created; no code movement; docstring-only fix.

Module docstring (`kbl/pipeline_tick.py:10-24`):

```python
``_process_signal_remote`` (Steps 1-6 only)
    Step 7 runs on Mac Mini via the off-tree poller at
    ``/Users/dimitry/baker-pipeline/poller.py`` (LaunchAgent
    ``com.brisen.baker.poller``, 60s ``StartInterval``; wrapper at
    ``~/baker-pipeline/poller-wrapper.sh``, env source ``~/.kbl.env``).
    That runner imports ``kbl.steps.step7_commit.commit`` directly and
    processes ``awaiting_commit`` rows for the vault. The poller is
    intentionally off-tree because it is Mac-Mini-specific infra code,
    not pipeline logic — no ``kbl/poller.py`` module exists in this repo.
    ...
```

Function docstring (`kbl/pipeline_tick.py:512-515`):

```python
Steps 1-6 only. Step 7 runs on Mac Mini via the off-tree poller at
``/Users/dimitry/baker-pipeline/poller.py`` (LaunchAgent
``com.brisen.baker.poller``) — see module docstring for details.
Do not call from Mac Mini.
```

`rg "kbl/poller\.py|from kbl\.poller|kbl\.poller" kbl/pipeline_tick.py` now only matches the new explanatory sentence ("no `kbl/poller.py` module exists in this repo") — no residual stale pointer.

---

## §test-matrix

3 new tests in `tests/test_step7_commit.py`:

| # | Test | Guards |
|---|------|--------|
| 1 | `test_step7_happy_path_logs_entry_with_target_path` | Entry INFO fires once with `target=<target_vault_path>`, `primary_matter`, `stub_count`. Component tag `step7_commit`, signal_id routed. No WARN/ERROR on happy path. |
| 2 | `test_step7_happy_path_push_success_fires_info` | With `BAKER_VAULT_DISABLE_PUSH=false`: `git push success` INFO fires exactly once (sha + remote + branch); shadow-mode INFO NOT emitted; terminal `signal completed` INFO fires. |
| 3 | `test_step7_shadow_mode_fires_info_not_warn` | With `BAKER_VAULT_DISABLE_PUSH=true` (fixture default): `shadow-mode: skipping git push` INFO fires exactly once (with `BAKER_VAULT_DISABLE_PUSH=true` + sha); push-success INFO NOT emitted; no WARN/ERROR; terminal `signal completed` still fires. |

All 3 use `patch("kbl.steps.step7_commit.emit_log")` + the existing `vault` fixture. Helper `_info_messages(mock_emit_log)` pulls the 4th-arg message off each INFO call for concise assertions.

Result:

```
$ /tmp/b1-venv/bin/pytest tests/test_step7_commit.py -q
..............................                                           [100%]
30 passed in 3.54s
```

27 pre-existing + 3 new = 30 green. No regressions in the existing Step 7 test suite.

---

## §test-results (full pytest — no-ship-by-inspection gate)

Run target: `/tmp/b1-venv/bin/pytest tests/ 2>&1 | tee /tmp/b1-pytest-step7-obs.log`

**Environment:** Python 3.12.12, pytest 9.0.3, asyncio mode=STRICT. Throwaway venv `/tmp/b1-venv` (same as PR #37/#38/#39/#41).

**Result:** `16 failed, 818 passed, 21 skipped, 19 warnings in 11.73s`

### Expected baseline match

Brief predicted `16 failed, 815 + 3 = 818 passed, 21 skipped`. Observed matches exactly. Zero new regressions.

### Failure triage — all 16 pre-existing on main

Same 16 pre-existing failures as PR #37/#38/#39/#41 baseline:

```
FAILED tests/test_1m_storeback_verify.py (×4)            (FileNotFound / ModuleNotFound — fixture+env)
FAILED tests/test_clickup_client.py::TestWriteSafety (×5) (wrong-space guard)
FAILED tests/test_clickup_integration.py (×3)            (voyageai env)
FAILED tests/test_scan_endpoint.py (×3)                  (auth env 401)
FAILED tests/test_scan_prompt.py (×1)                    (conversational prompt assertion)
```

### Full log

Saved to `/tmp/b1-pytest-step7-obs.log` on the B1 box. Head + tail:

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.33, asyncio-1.3.0, anyio-4.13.0
asyncio: mode=Mode.STRICT, debug=False, ...
collected 855 items
...
=========== 16 failed, 818 passed, 21 skipped, 19 warnings in 11.73s ===========
```

---

## §delivery checklist

- [x] Branch `observability-step7-plus-poller-doc-1` pushed
- [x] PR opened on baker-master (reviewer B3) — see §pr-url
- [x] Part A: `_LOG_COMPONENT = "step7_commit"` module constant added
- [x] Part A: 7 happy-path `emit_log` sites added (entry, lock, guard, files, commit, push-or-shadow, completed)
- [x] Part A: zero logic changes — `_git_add_commit` / `_git_push_with_retry` / `_atomic_write` / `_append_or_replace_stub` / `disable_push` branch / state UPDATE all untouched
- [x] Part A: existing `logger.info("step7 mock-mode: …")` kept intact (brief contract)
- [x] Part B: module docstring + function docstring rewritten with off-tree path + LaunchAgent + wrapper + env-source + interval
- [x] Part B: zero code changes — docstring-only
- [x] 3 regression tests added covering entry, push-success, shadow-mode gates
- [x] Full pytest output captured (`/tmp/b1-pytest-step7-obs.log`): `16 failed, 818 passed, 21 skipped` matches expected baseline exactly
- [x] Zero regressions; no changes to schema / env vars / `disable_push` default / commit-or-push logic / other steps
- [x] Timebox: shipped inside 90-min window

---

## §pr-url

https://github.com/vallen300-bit/baker-master/pull/43

— B1, 2026-04-22
