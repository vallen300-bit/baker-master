"""REPORT_SUCCESS_ARITY_FIX_1 — regression guard for the report_success() arity bug.

Before this fix, ``report_success(source: str)`` took ONE positional arg, but
four call sites passed a second observability ``payload`` arg:
  - orchestrator/roadmap_drift_sentinel.py:223  report_success("roadmap_drift_sentinel", payload)
  - triggers/embedded_scheduler.py:1515         report_success("wiki_lint", {...})
  - triggers/embedded_scheduler.py:1530         report_success("ao_pm_lint", {})
  - triggers/embedded_scheduler.py:1550         report_success("movie_am_lint", {})

Each raised ``TypeError`` swallowed by the caller's bare ``except``, so the
success was silently lost and any source that had ever failed stayed wedged
'down' forever (roadmap_drift_sentinel froze at its 2026-05-20
clickup_post_failed despite the daily ClickUp post succeeding ever since).

These tests verify the widened signature accepts the optional payload AND still
writes the 'healthy' upsert — including the PR #374 (95a4f8b) ``last_error_msg
= NULL`` clearing, which must not regress.
"""
import inspect

import triggers.sentinel_health as sh


class _FakeCursor:
    def __init__(self, recorder):
        self._recorder = recorder

    def execute(self, sql, params=None):
        self._recorder.append((sql, params))

    def fetchone(self):
        # Previous status read by report_success — return a non-'down' status so
        # no recovery alert path fires (keeps the test DB-isolated).
        return ("degraded",)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, recorder):
        self._recorder = recorder

    def cursor(self):
        return _FakeCursor(self._recorder)

    def commit(self):
        self._recorder.append(("__COMMIT__", None))

    def rollback(self):
        self._recorder.append(("__ROLLBACK__", None))


def _patch_db(monkeypatch):
    """Route report_success's DB helpers to an in-memory recorder."""
    recorder = []
    fake_conn = _FakeConn(recorder)
    monkeypatch.setattr(sh, "_get_conn", lambda: (fake_conn, object()))
    monkeypatch.setattr(sh, "_put_conn", lambda store, conn: None)
    monkeypatch.setattr(sh, "_ensure_table", lambda conn: None)
    return recorder


def test_signature_accepts_optional_payload():
    params = list(inspect.signature(sh.report_success).parameters)
    assert params[0] == "source"
    assert "payload" in params, "report_success must accept an optional payload arg"


def test_two_arg_call_does_not_raise_and_writes_healthy(monkeypatch):
    recorder = _patch_db(monkeypatch)
    # The exact 2-arg shape roadmap_drift_sentinel uses — must not raise.
    sh.report_success("roadmap_drift_sentinel", {"status": "no_drift", "pr_count": 2})

    upserts = [sql for sql, _ in recorder if "INSERT INTO sentinel_health" in sql]
    assert upserts, "expected the healthy upsert to execute"
    upsert_sql = upserts[0]
    assert "'healthy'" in upsert_sql
    assert "consecutive_failures = 0" in upsert_sql
    # PR #374 must not regress: recovery clears the stale error string.
    assert "last_error_msg = NULL" in upsert_sql
    assert ("__COMMIT__", None) in recorder


def test_all_four_known_caller_shapes(monkeypatch):
    # Mirror every live 2-arg call site — none may raise.
    for src, payload in [
        ("roadmap_drift_sentinel", {"status": "drift", "pr_count": 6}),
        ("wiki_lint", {"findings_count": 3}),
        ("ao_pm_lint", {}),
        ("movie_am_lint", {}),
    ]:
        _patch_db(monkeypatch)
        sh.report_success(src, payload)  # would have raised TypeError pre-fix


def test_one_arg_call_still_works(monkeypatch):
    # Backward-compat: existing 1-arg callers (e.g. todoist) keep working.
    recorder = _patch_db(monkeypatch)
    sh.report_success("todoist")
    assert any("INSERT INTO sentinel_health" in sql for sql, _ in recorder)
