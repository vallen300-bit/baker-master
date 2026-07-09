"""MCP_EVENTLOOP_OFFLOAD_502_FIX_1 — the remote MCP endpoint must not block the loop.

Root cause of the intermittent CM SQL/documents 502 (bus infra/cm-sql-surface-502,
diagnosis b1 #7644): ``POST /mcp`` (``mcp_streamable_http``) is an ``async`` endpoint
but ran the fully-synchronous, blocking dispatch ``_handle_mcp_message`` ->
``_dispatch`` -> ``_query`` (blocking psycopg2) DIRECTLY on the single uvicorn event
loop. A heavy ``documents`` query (``full_text`` up to 8.4 MB/row, seq scan, LIMIT 500
-> ~12 MB / 4.4 s) froze the whole loop; concurrent requests from the 4 CM seats +
health queued behind it and were killed by Render's edge timeout -> 502.

Fix: offload the blocking dispatch to a worker thread via ``asyncio.to_thread`` — the
same pattern used ~15x elsewhere in dashboard.py. These tests pin that behaviour so it
cannot silently regress back to an inline (loop-blocking) call.

Source-level assertions run in any Python; the behavioural TestClient test skips cleanly
when ``outputs.dashboard`` cannot import (Python 3.9 PEP-604 chain — same skip contract
as tests/test_cortex_action_endpoint.py).
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "outputs" / "dashboard.py"


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401

        return True
    except Exception:
        return False


# ─── Source-level: the /mcp endpoint offloads the blocking dispatch ───

def test_mcp_endpoint_offloads_dispatch_to_thread_in_source():
    src = _SRC.read_text()
    # The endpoint region: from the route decorator to the next top-level def.
    start = src.index('@app.post("/mcp"')
    end = src.index("\n@app.", start + 1)
    endpoint = src[start:end]
    # Must offload _handle_mcp_message via asyncio.to_thread (never inline-call it
    # on the event loop). Both the single and batch paths.
    assert "asyncio.to_thread(_handle_mcp_message" in endpoint, (
        "the /mcp endpoint must offload _handle_mcp_message via asyncio.to_thread "
        "(loop-blocking dispatch was the CM-502 root cause — b1 #7644)"
    )
    # Guard against the regression shape: a bare inline call `_handle_mcp_message(`
    # that is NOT wrapped in asyncio.to_thread must not appear in the endpoint.
    for line in endpoint.splitlines():
        if "_handle_mcp_message(" in line and "asyncio.to_thread" not in line:
            pytest.fail(
                f"inline (loop-blocking) dispatch call in /mcp endpoint: {line.strip()!r}"
            )


# ─── Behavioural: dispatch actually runs off the event-loop thread ───

@pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable (Python 3.9 PEP-604 chain — clears on 3.10+)",
)
def test_mcp_tools_call_runs_dispatch_off_event_loop(monkeypatch):
    from fastapi.testclient import TestClient
    from outputs import dashboard

    # Capture the event-loop thread ident from inside a trivial coroutine hop so we
    # can prove the blocking dispatch runs on a DIFFERENT (worker) thread.
    loop_thread_box: dict[str, int] = {}
    dispatch_thread_box: dict[str, int] = {}

    def _fake_dispatch(name, arguments):
        dispatch_thread_box["ident"] = threading.get_ident()
        return f"ok:{name}"

    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", "test-key")
    monkeypatch.setattr(
        dashboard, "_get_mcp_module", lambda: {"tools": [], "dispatch": _fake_dispatch}
    )

    # Wrap asyncio.to_thread so we (a) record the loop thread that scheduled it and
    # (b) confirm the offload target is _handle_mcp_message.
    real_to_thread = dashboard.asyncio.to_thread
    offload_targets: list = []

    async def _spy_to_thread(fn, *args, **kwargs):
        loop_thread_box["ident"] = threading.get_ident()
        offload_targets.append(getattr(fn, "__name__", repr(fn)))
        return await real_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(dashboard.asyncio, "to_thread", _spy_to_thread)

    client = TestClient(dashboard.app)
    resp = client.post(
        "/mcp",
        headers={"X-Baker-Key": "test-key"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "baker_raw_query", "arguments": {"sql": "SELECT 1"}},
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["content"][0]["text"] == "ok:baker_raw_query"
    # The blocking dispatch was offloaded via to_thread...
    assert "_handle_mcp_message" in offload_targets
    # ...and actually executed on a worker thread, not the event-loop thread.
    assert dispatch_thread_box.get("ident") is not None
    assert loop_thread_box.get("ident") is not None
    assert dispatch_thread_box["ident"] != loop_thread_box["ident"]
