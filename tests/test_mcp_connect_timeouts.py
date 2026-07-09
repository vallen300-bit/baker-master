"""CM_SQL_SURFACE_502 2b — the MCP SQL surface must connect with hard timeouts.

Follow-up to the event-loop offload (PR #496): offloading the blocking dispatch
to a worker thread stops one slow query from freezing the whole loop, but a
heavy ``documents.full_text`` scan could still wedge its own worker thread and
hold a pooler backend open indefinitely. Lead ruling #7646 (bus
infra/cm-sql-surface-502) ratified capping it:

  - statement_timeout = 15s  — over-length queries fail fast + loud.
  - connect_timeout   = 5s   — fail fast on a cold/unreachable backend.

Both are applied via libpq connect params (``options=-c statement_timeout=...``)
rather than a post-connect ``SET``: a session GUC leaks through Neon's pgbouncer
transaction-mode pool to unrelated callers (RCA 2026-04-29, documented inline in
``_query``). These tests pin that so it cannot silently regress to a leaking
``SET`` or drop the caps entirely.

Source-level assertions run in any Python. The functional test imports the MCP
server module and skips cleanly where the ``mcp`` SDK is not installed (same skip
contract as tests/test_mcp_eventloop_offload.py's behavioural test).
"""
from __future__ import annotations

from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "baker_mcp" / "baker_mcp_server.py"


def _server_importable() -> bool:
    try:
        import baker_mcp.baker_mcp_server  # noqa: F401

        return True
    except Exception:
        return False


# ─── Source-level: the caps are present, via connect params not a SET ─────────

def test_statement_and_connect_timeout_constants_pinned_in_source():
    src = _SRC.read_text()
    # 15_000 ms == 15s statement_timeout, 5s connect_timeout — lead ruling #7646.
    assert "_STATEMENT_TIMEOUT_MS = 15_000" in src
    assert "_CONNECT_TIMEOUT_S = 5" in src


def test_conn_params_apply_timeouts_via_options_in_source():
    src = _SRC.read_text()
    # connect_timeout rides as a top-level libpq param.
    assert 'params["connect_timeout"] = _CONNECT_TIMEOUT_S' in src
    # statement_timeout rides the startup packet via options=-c ... (NOT a SET).
    assert 'params["options"] = f"-c statement_timeout={_STATEMENT_TIMEOUT_MS}"' in src


def test_statement_timeout_never_applied_as_runtime_set():
    """statement_timeout must ride connect options, never a runtime SQL ``SET``.

    A session GUC issued after connect leaks through the pgbouncer
    transaction-mode pool to unrelated callers (RCA 2026-04-29). Guard against a
    regression that "fixes" the timeout with ``cur.execute("SET
    statement_timeout = ...")`` instead of the ``options=`` startup param. (Bare
    ``set_session(...)`` appears only in ``_query``'s explanatory docstring, so
    we match the specific SQL form, not that substring.)
    """
    src = _SRC.read_text()
    lowered = src.lower()
    assert "set statement_timeout" not in lowered
    assert "set session statement_timeout" not in lowered


# ─── Functional: _get_conn_params actually carries the caps (both env paths) ──

@pytest.mark.skipif(not _server_importable(), reason="mcp SDK not installed")
def test_get_conn_params_database_url_path_carries_timeouts(monkeypatch):
    from baker_mcp.baker_mcp_server import (
        _CONNECT_TIMEOUT_S,
        _STATEMENT_TIMEOUT_MS,
        _get_conn_params,
    )

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://u:p@example.test:5432/sentinel?sslmode=require"
    )
    params = _get_conn_params()

    assert params["connect_timeout"] == _CONNECT_TIMEOUT_S == 5
    assert params["options"] == f"-c statement_timeout={_STATEMENT_TIMEOUT_MS}"
    assert "statement_timeout=15000" in params["options"]
    # existing behaviour preserved
    assert params["host"] == "example.test"
    assert params["sslmode"] == "require"


@pytest.mark.skipif(not _server_importable(), reason="mcp SDK not installed")
def test_get_conn_params_split_env_path_carries_timeouts(monkeypatch):
    from baker_mcp.baker_mcp_server import _get_conn_params

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "split.test")
    monkeypatch.setenv("POSTGRES_DB", "sentinel")
    monkeypatch.setenv("POSTGRES_USER", "sentinel")
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    params = _get_conn_params()

    assert params["connect_timeout"] == 5
    assert "statement_timeout=15000" in params["options"]
    assert params["host"] == "split.test"
