---
brief_id: RENDER_ENV_WIPE_PRECOMMIT_GUARD_1
agent: B3
date: 2026-05-20
status: SHIPPED
pr: 230
branch: b3/render-env-wipe-precommit-guard-1
base_sha: cf685cb
dispatched_by: lead
reply_target: lead
bus_topic: ship/render-env-wipe-precommit-guard-1
ack_bus_ids: [583, 586]
blocker_posted: 584
---

# B3 ship report — RENDER_ENV_WIPE_PRECOMMIT_GUARD_1

## What shipped

`.githooks/pre-commit` gains **Part 4**: scans staged diffs for the
`PUT /v1/services/{id}/env-vars` URL shape WITHOUT a `/KEY` suffix —
the array-form foot-cannon that caused the 2026-05-17 catastrophic wipe.
Layered above `tools/render_env_guard.safe_env_put()` (PR #216,
2026-05-17). The wrapper protects imported-Python paths; this hook
protects bash/curl/raw-httpx escape routes.

## Files

- `.githooks/pre-commit` — Part 4 inserted between Part 3's `fi` and
  Part 1's header. Allowlist exempts the guard's own code + tests +
  briefs + `tasks/lessons.md` + `python-backend.md` + the hook itself.
  Bypass: `git commit --no-verify` (documented in error message).
- `tests/test_pre_commit_env_guard.py` — NEW. 6 subprocess-driven
  scenarios against isolated `tmp_path` git repos.
- `.claude/rules/python-backend.md` — Render env-vars rule references
  Part 4.

## Pytest output (literal, Python 3.12)

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 6 items

tests/test_pre_commit_env_guard.py::test_positive_1_python_httpx_array_put_blocked PASSED [ 16%]
tests/test_pre_commit_env_guard.py::test_positive_2_bash_curl_array_put_blocked PASSED [ 33%]
tests/test_pre_commit_env_guard.py::test_negative_1_safe_env_put_call_passes PASSED [ 50%]
tests/test_pre_commit_env_guard.py::test_negative_2_single_key_url_passes PASSED [ 66%]
tests/test_pre_commit_env_guard.py::test_negative_3_allowlisted_render_env_guard_passes PASSED [ 83%]
tests/test_pre_commit_env_guard.py::test_negative_4_allowlisted_brief_passes PASSED [100%]

============================== 6 passed in 2.24s ==============================
```

Local Python 3.9 trips on `int | None` syntax in `memory/store_back.py`
conftest path (unrelated). Ran via `python3.12 -m pytest`.

## Manual smokes

### Part 4 POSITIVE — throwaway fixture blocked

```
scratch.py: httpx.put("https://api.render.com/v1/services/srv-test/env-vars", json=[])
git add + commit → BLOCKED (Part 4), EXIT=1
git reset + rm → clean
```

### Part 3 still functional — regression check

```
scratch_part3.py: MODEL = "claude-opus-4-20250514"
git add + commit → BLOCKED (Part 3), EXIT=1
git reset + rm → clean
```

### Invariants

```
$ git config core.hooksPath
.githooks
```

## Bus + dispatch flow

- Bus #583 (lead → b3, render-env-wipe-precommit-guard-1, 12:08 UTC) —
  ACKed; brief file + mailbox PENDING flip absent → posted blocker #584.
- Bus #586 (lead → b3, ROUND 2 with commit cf685cb landed, 12:17 UTC) —
  ACKed; pulled, claimed, built.
- Bus ship reply to lead on PR open (this report) — posted at PR open.

## Acceptance criteria

| Criterion | Status |
|---|---|
| Part 4 in `.githooks/pre-commit` between Part 3's `fi` and Part 1's `exec` | ✓ |
| Parts 1-3 untouched + still functional | ✓ (Part 3 manual smoke) |
| `tests/test_pre_commit_env_guard.py` — 6 scenarios | ✓ |
| `.claude/rules/python-backend.md` references Part 4 | ✓ |
| Literal pytest output | ✓ (in PR + above) |
| Manual POSITIVE smoke on Part 4 | ✓ |
| `git config core.hooksPath` returns `.githooks` | ✓ |

## Effort

~30 min (under the 45-60 min estimate).

## Next

Awaiting lead review + merge of PR #230.
