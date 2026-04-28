# B2 review — PR #46 hotfix/audit-singleton-pattern — 2026-04-23

**Reviewer:** Code Brisen #2
**PR:** https://github.com/vallen300-bit/baker-master/pull/46
**Branch:** `hotfix/audit-singleton-pattern` @ `e9079f7`
**Scope:** Fixes singleton-pattern violation introduced by PR #44 (commit `63af5b1`) in `triggers/ai_head_audit.py`

---

## Verdict: **APPROVE PR #46**

2-line production edit + 2-line test mock update + CODE_3_RETURN.md rewrite. Ship gate reproduces identically (6 passed in 0.04s, singleton hook green, syntax clean). Canonical pattern match confirmed.

---

## Ship gate — reproduced locally

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ python3 -m pytest tests/test_ai_head_weekly_audit.py -v
...
tests/test_ai_head_weekly_audit.py::test_module_imports PASSED           [ 16%]
tests/test_ai_head_weekly_audit.py::test_summary_is_plain_text_three_lines_max PASSED [ 33%]
tests/test_ai_head_weekly_audit.py::test_fresh_operating_yields_no_operating_stale_flag PASSED [ 50%]
tests/test_ai_head_weekly_audit.py::test_stale_operating_yields_flag PASSED [ 66%]
tests/test_ai_head_weekly_audit.py::test_run_weekly_audit_is_non_fatal_on_slack_failure PASSED [ 83%]
tests/test_ai_head_weekly_audit.py::test_ship_gate_verifies_scheduler_registration PASSED [100%]

============================== 6 passed in 0.04s ===============================

$ python3 -c "import py_compile; py_compile.compile('triggers/ai_head_audit.py', doraise=True)"
ai_head_audit.py OK
```

Output cmp-identical to CODE_3_RETURN.md (rev 9c70953).

---

## Per-change verdict

### ✅ `triggers/ai_head_audit.py` — 2-line edit

| Line | Before | After |
|---|---|---|
| 361 (`_write_audit_record`) | `store = SentinelStoreBack()` | `store = SentinelStoreBack._get_global_instance()` |
| 412 (`_update_slack_outcomes`) | `store = SentinelStoreBack()` | `store = SentinelStoreBack._get_global_instance()` |

Minimal, surgical. Both wrapped in the pre-existing try/except; rollback/non-fatal invariants untouched.

### ✅ Canonical pattern match

`SentinelStoreBack._get_global_instance()` is defined at `memory/store_back.py:45` (classmethod that lazy-inits `cls._instance = cls()`). Canonical call sites verified:

- `triggers/clickup_trigger.py:50, 446, 518`
- `triggers/browser_trigger.py:36`
- `triggers/state.py:25`

The two new sites in `ai_head_audit.py` match these verbatim. (Note: the user's dispatch mentioned `ingest_vault_matter.py:385` as a canonical reference — that path is `scripts/ingest_vault_matter.py`, only 154 lines, no `_get_global_instance` call. Likely a slip in the dispatch; the PR-body citations are the real canonical sites and they all check out.)

### ✅ `tests/test_ai_head_weekly_audit.py` — 2-line mock update

Lines 122–123:

```python
-    store_class_mock = MagicMock(return_value=store_instance)
+    store_class_mock = MagicMock()
+    store_class_mock._get_global_instance.return_value = store_instance
```

Correct adaptation: previously the mock mimicked `SentinelStoreBack()` (class-called-as-function → returns `store_instance`). Now that production calls `SentinelStoreBack._get_global_instance()`, the mock binds the return on the `_get_global_instance` attribute. Without this update the end-to-end non-fatal test would silently bind to a fresh `MagicMock()` and the `cur_mock.fetchone.return_value = (42,)` assertion would never fire — the change keeps the test exercising the real path.

Behavior proof: `test_run_weekly_audit_is_non_fatal_on_slack_failure` still returns `result["record_id"] == 42` (asserted line 139) and `slack_cockpit_ok=False, slack_dm_ok=False` — non-fatal end-to-end path intact.

### ✅ `briefs/_reports/CODE_3_RETURN.md` — doc rewrite

In-place overwrite of the PR #44 ship report to become the PR #46 ship report (+28 / -35). Matches repo convention — B3 paper trail reuses the `CODE_3_RETURN.md` slot per sprint. Content: literal pytest + singleton-hook + syntax check output + handoff pointing to AI Head #2.

---

## Invariants check

| Invariant | Status |
|---|---|
| No new SentinelStoreBack() direct instantiation in runtime code | ✅ `check_singletons.sh` green |
| Non-fatal try/except boundaries untouched | ✅ edits are inside pre-existing try blocks (lines 359, 410) |
| No change to rollback semantics | ✅ except-block rollback at lines 393, 426 still present |
| Read-only against vault_mirror | ✅ not in diff |
| SlackNotifier class additive-only | ✅ not in diff |
| CronTrigger UTC + coalesce/max_instances/replace/misfire | ✅ not in diff |
| Test still asserts record_id=42 end-to-end | ✅ line 139 passes |
| Ship gate = literal output, not "by inspection" | ✅ pytest + singleton + syntax all captured |

---

## Regression risk: low

- `_get_global_instance` lazy-inits on first call, so semantics under the hood are identical to `SentinelStoreBack()` for cold-start — just idempotent/pooled across callers now (which is the whole point; matches OOM-PHASE3 policy).
- Only 2 runtime lines touched; both inside existing non-fatal wrappers.
- Pre-push hook `scripts/check_singletons.sh` now passes → unblocks downstream AI Head #2 work per PR body.

## N-nits parked (non-blocking)

- **N1 — Dispatch typo `ingest_vault_matter.py:385`.** That path is under `scripts/`, file is 154 lines, no singleton call site. PR body's cited canonical sites (`clickup_trigger.py`, `browser_trigger.py`, `state.py`) are the real ones and all verify. Informational only.
- **N2 — CODE_3_RETURN.md is an in-place overwrite** rather than a new-dated sibling file. Matches repo convention (B3 reuses the slot). Non-blocking; worth considering per-PR naming later if paper trail gets squashed during audits.

---

## Decision

**APPROVE PR #46.** AI Head #2 Tier-A auto-merges (`gh pr merge 46 --squash`).

— B2
