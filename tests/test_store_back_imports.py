"""BACKFILL_SENTINEL_HEARTBEAT_FIX_1 — FIX 1 regression.

`memory/store_back.py` declared a method `... -> int | None:` WITHOUT
`from __future__ import annotations`. On Python 3.9 the `int | None` union is
evaluated at class-definition time -> `TypeError: unsupported operand type(s)
for |: 'type' and 'NoneType'`, which breaks `import memory.store_back`.

`orchestrator.job_heartbeat._store()` imports memory.store_back and swallows the
exception, so `beat()` silently became a no-op and `job_heartbeats` never got
rows for the 4 backfill jobs (only the sentinel's own meta-heartbeat, written
server-side under a newer Python). This test fails on Python 3.9 pre-fix and
passes on every interpreter post-fix.
"""
import importlib


def test_store_back_imports_cleanly():
    sb = importlib.import_module("memory.store_back")
    assert hasattr(sb, "SentinelStoreBack")


def test_job_heartbeat_can_import_store_back():
    # _store() must reach memory.store_back without the union TypeError. We import
    # the module directly here (it must not raise) and confirm beat() is callable.
    from orchestrator import job_heartbeat
    import memory.store_back  # must not raise on the runtime Python
    assert callable(job_heartbeat.beat)
    assert callable(job_heartbeat.read)
