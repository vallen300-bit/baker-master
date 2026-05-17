---
brief_id: RENDER_ENV_WRITE_GUARD_1
status: SHIPPED (awaiting review)
ship_date: 2026-05-17
b_code: B3
pr: https://github.com/vallen300-bit/baker-master/pull/216
branch: b3/render-env-write-guard-1
commit: 7611276
target_branch: main
trigger_class: LOW-MEDIUM
---

# B3 — Ship report: RENDER_ENV_WRITE_GUARD_1

## TL;DR

Shipped PR #216. New `tools/render_env_guard.py` exports `safe_env_put()` + `forbid_array_put()` + `__main__` CLI. 10 unit tests all green. Rule entry updated. Vault-side LONGTERM.md note flagged to AH1 (B3 doesn't write vault `_ops/`).

## Files changed

| File | Status | LOC |
|---|---|---|
| `tools/render_env_guard.py` | new | ~95 |
| `tests/test_render_env_guard.py` | new | ~99 |
| `.claude/rules/python-backend.md` | edit | +1 line (pointer added) |

Net: +194 / -1.

## Ship-gate pytest output (literal)

```
$ python3.12 -m pytest tests/test_render_env_guard.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /opt/homebrew/opt/python@3.12/bin/python3.12
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.38, anyio-4.12.1
collecting ... collected 10 items

tests/test_render_env_guard.py::test_forbid_array_put_raises_on_list PASSED [ 10%]
tests/test_render_env_guard.py::test_forbid_array_put_passes_on_dict PASSED [ 20%]
tests/test_render_env_guard.py::test_forbid_array_put_passes_on_empty_dict PASSED [ 30%]
tests/test_render_env_guard.py::test_safe_env_put_issues_merge_mode_url_and_body PASSED [ 40%]
tests/test_render_env_guard.py::test_safe_env_put_raises_on_4xx PASSED   [ 50%]
tests/test_render_env_guard.py::test_safe_env_put_raises_on_5xx PASSED   [ 60%]
tests/test_render_env_guard.py::test_safe_env_put_missing_api_key PASSED [ 70%]
tests/test_render_env_guard.py::test_safe_env_put_picks_up_env_key PASSED [ 80%]
tests/test_render_env_guard.py::test_safe_env_put_rejects_empty_service_id PASSED [ 90%]
tests/test_render_env_guard.py::test_safe_env_put_rejects_empty_key PASSED [100%]

============================== 10 passed in 0.02s ==============================
```

No "by inspection". 10/10 green.

## Acceptance criteria checklist

| # | Criterion | Status |
|---|---|---|
| 1 | `tools/render_env_guard.py` exporting `safe_env_put()` (single-key merge-mode PUT, returns parsed JSON, raises on 4xx/5xx) | ✅ |
| 2 | `__main__` CLI invokable as `python -m tools.render_env_guard <sid> <key> <value>` | ✅ |
| 3 | `forbid_array_put(payload)` raises `RenderEnvGuardError` on list with the prescribed error message including "REPLACES" + "2026-05-17 wipe" anchor | ✅ |
| 4 | Module docstring pointing to LONGTERM.md + brief + 2026-05-17 wipe anchor | ✅ |
| 5 | `tests/test_render_env_guard.py` covers URL/body/list-vs-dict | ✅ (10 tests; superset of spec) |
| 6 | `.claude/rules/python-backend.md` references `tools.render_env_guard` | ✅ |
| 7 | Note in `_ops/agents/ai-head/LONGTERM.md` Render section | ⚠️ flagged for AH1 — vault-side, out of B3 write scope per CLAUDE.md |
| 8 | Literal `pytest tests/test_render_env_guard.py -v` green | ✅ (above) |

## Implementation notes / deviations

- **HTTP library:** brief sketch uses `requests`; repo uses `httpx>=0.27.0` (`requirements.txt`). Switched to `httpx` to align with repo idiom. Behavior identical. Mocks adjusted accordingly (`tools.render_env_guard.httpx.put`).
- **Extra defensive checks beyond brief:** empty `service_id` / empty `key` raise (prevents URL malformation); transport errors caught + wrapped to `RenderEnvGuardError`.
- **`forbid_array_put` invariant on dict body:** called inside `safe_env_put` as a tripwire — should never trip on the canonical dict body, but documents the invariant in code.
- **LONGTERM.md (vault-side) note:** NOT included in this PR. Per `bm-b3/CLAUDE.md` "Out of scope: `_ops/` (vault-side, when present) — Director + Mac Mini commit per CHANDA Inv 9", B3 does not write vault `_ops/`. AH1 should add the pointer in a vault-side commit. Suggested wording:
  > `tools/render_env_guard.py` in baker-master is the canonical Python path — `safe_env_put(service_id, key, value)`. Anchor: 2026-05-17 catastrophic wipe (32 → 0).

## What this brief does NOT do (confirmed)

- Does not touch Render API itself.
- Does not block bash/curl invocations directly.
- Does not delete or alter any existing env-var write code paths.
- Does not introduce a server-side audit hook.

## Review chain

- AH1 cross-lane review (per dispatch).
- AH2 static + judgment call on `/security-review` (per dispatch).
- AH1's judgment on whether trigger-class LOW-MEDIUM fires 2nd-pass `feature-dev:code-reviewer`.

## Next

- Awaiting AH1 review + merge.
- LONGTERM.md vault-side pointer for AH1.
