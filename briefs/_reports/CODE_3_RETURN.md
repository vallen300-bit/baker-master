# CODE_3_RETURN — HOTFIX audit-singleton-pattern — 2026-04-23

**From:** Code Brisen #3
**To:** AI Head #2
**Branch:** `hotfix/audit-singleton-pattern` (off main)
**Scope:** Introduced by BRIEF_AI_HEAD_WEEKLY_AUDIT_1 (PR #44, commit 63af5b1)

---

## Change — 2 lines in `triggers/ai_head_audit.py`

| Location | Before | After |
|---|---|---|
| line 361 (`_write_audit_record`) | `store = SentinelStoreBack()` | `store = SentinelStoreBack._get_global_instance()` |
| line 412 (`_update_slack_outcomes`) | `store = SentinelStoreBack()` | `store = SentinelStoreBack._get_global_instance()` |

Test-only update: `tests/test_ai_head_weekly_audit.py` lines 122–124 — mock
now binds `_get_global_instance.return_value = store_instance` instead of
`MagicMock(return_value=store_instance)`.

Canonical pattern confirmed: `triggers/clickup_trigger.py:50,446,518`,
`triggers/browser_trigger.py:36`, `triggers/state.py:25`.

## Ship gate — literal output

```
$ python3 -m pytest tests/test_ai_head_weekly_audit.py -v
/Users/dimitry/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0 -- /Library/Developer/CommandLineTools/usr/bin/python3
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: anyio-4.12.1, mock-3.15.1, langsmith-0.4.37
collecting ... collected 6 items

tests/test_ai_head_weekly_audit.py::test_module_imports PASSED           [ 16%]
tests/test_ai_head_weekly_audit.py::test_summary_is_plain_text_three_lines_max PASSED [ 33%]
tests/test_ai_head_weekly_audit.py::test_fresh_operating_yields_no_operating_stale_flag PASSED [ 50%]
tests/test_ai_head_weekly_audit.py::test_stale_operating_yields_flag PASSED [ 66%]
tests/test_ai_head_weekly_audit.py::test_run_weekly_audit_is_non_fatal_on_slack_failure PASSED [ 83%]
tests/test_ai_head_weekly_audit.py::test_ship_gate_verifies_scheduler_registration PASSED [100%]

============================== 6 passed in 0.05s ===============================
```

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

```
$ python3 -c "import py_compile; py_compile.compile('triggers/ai_head_audit.py', doraise=True)"
(no output — clean)
```

**6 passed. Singleton hook green. Not "by inspection."**

## Handoff

PR opened against main. B2 reviews. On APPROVE + green CI, AI Head #2 merges (Tier A).

---
**Timestamp:** 2026-04-23
