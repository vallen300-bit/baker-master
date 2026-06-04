# BRIEF: REINGEST_ASYNC_OFFLOAD_1 — stop the reingest endpoint from taking Baker down

## Context
`POST /api/documents/reingest-missing` (shipped in #291, `cb9b984`) is an `async def`
handler that calls the **synchronous** `ingest_text()` (chunk → Voyage embed → Qdrant
upsert) directly inside the request, in a per-candidate loop. On Baker's single Uvicorn
worker this blocks the event-loop thread for the entire batch — so `/health`, the
dashboard, search, and MCP all queue behind it and time out. A live `limit=50` backfill
run on 2026-06-04 made baker-master unresponsive for ~15 min and required a Render
restart to recover (AH1 incident, PINNED §A-LEAD-0603-PM3). Lesson #25 also flags
embedding catch-up as an OOM risk, so concurrent batches must be prevented.

This brief makes the embed loop run **off** the event loop and guards against
concurrent/overlapping runs. Scope is deliberately minimal (Option A, AH1-chosen over a
job-queue to avoid over-engineering a near-one-time recovery).

### Surface contract: N/A — backend-only fix to an admin JSON endpoint; no clickable/dashboard surface.

## Harness V2

- **Routed owner:** B-code (idle: b1). Single-file Python change in `outputs/dashboard.py` + 1 test file.
- **Task class:** production-facing bug fix (availability). NOT docs-only.
- **Context Contract:** all touch-points, signatures, and the exact diff are below; no discovery needed.
- **Done rubric (answer literally — NOT "tests pass"):**
  1. During a live `dry_run=false&limit=10` run against prod, a concurrent `GET /health`
     returns 200 in <3s (proves the worker is no longer blocked). Paste both timestamps.
  2. A second concurrent `POST .../reingest-missing?dry_run=false` returns
     `{"error":"backfill_in_progress"}` (proves the advisory lock holds).
  3. `embedded` count > 0 and `remaining_after` strictly decreases across two sequential calls.
- **Gate plan:** G0 codex-arch (brief) → G1 lead (pytest literal + live probe) → G2 /security-review → G3 codex (PR) → merge → **POST_DEPLOY_AC_VERDICT v1**.

## Estimated time: ~1h
## Complexity: Low
## Prerequisites: none (PR #291 already merged to main)

---

## Fix 1: Offload the embed loop to a thread + advisory lock + smaller default batch

### Problem
The write path (lines ~2071-2109 of `outputs/dashboard.py`) runs `ingest_text()`
synchronously inside the `async def` handler. The event loop is blocked for the whole
batch → total service unavailability on a single worker.

### Current State
`outputs/dashboard.py`:
- `2000` `async def documents_reingest_missing(limit: int = Query(50, ge=1, le=500), dry_run: bool = Query(True))`
- `2071-2109` the synchronous `for c in candidates:` embed loop (the blocking section).
- `2111-2131` `remaining_after` recount (fast SQL — leave on the event loop).
- `ingest_text` signature (verified, `tools/ingest/pipeline.py:369`):
  `ingest_text(full_text, filename, source_path, collection="baker-documents", file_hash=None, project=None, role=None, skip_dedup=False, verbose=False, document_id=None, matter_slug=None) -> IngestResult` (`.skipped`, `.skip_reason`).
- `asyncio` is already imported and `asyncio.to_thread(...)` is the established offload
  idiom in this file (e.g. lines 839, 978, 1110, 6138).

### Implementation

**Step 1 — add a module-level sync helper** (place it directly above the endpoint, near
the `_reingest_missing_counts` helper at line ~1975). This is the existing loop body
moved verbatim into a function so it can run in a thread:

```python
# REINGEST_ASYNC_OFFLOAD_1: run the blocking embed loop in a worker thread so the
# event loop (and /health, dashboard, search, MCP) stays responsive during a backfill.
def _reingest_embed_batch(candidates: list) -> dict:
    """Embed already-extracted full_text for each candidate. Pure ingest_text calls —
    no DB connection held. One failure must NOT abort the batch. Runs in a thread via
    asyncio.to_thread."""
    from tools.ingest.pipeline import ingest_text
    attempted = embedded = skipped_empty = skipped_dedup = 0
    failed = []
    for c in candidates:
        attempted += 1
        doc_id = c["id"]
        full_text = c.get("full_text") or ""
        if not full_text.strip():
            skipped_empty += 1
            continue
        try:
            result = ingest_text(
                full_text=full_text,
                filename=c.get("filename") or f"doc-{doc_id}",
                source_path=c.get("source_path") or c.get("filename") or f"doc-{doc_id}",
                file_hash=c.get("file_hash"),  # documents.file_hash, do NOT re-hash text
                document_id=doc_id,
                matter_slug=c.get("matter_slug"),
            )
        except Exception as ing_err:
            logger.error(f"reingest-missing id={doc_id} raised: {ing_err}")
            failed.append({"id": doc_id, "reason": str(ing_err)})
            continue
        reason = (result.skip_reason or "") if result.skipped else ""
        if not result.skipped:
            embedded += 1
        elif reason.startswith("Duplicate"):
            skipped_dedup += 1
        elif reason == "Empty text":
            skipped_empty += 1
        else:
            failed.append({"id": doc_id, "reason": reason or "skipped"})
    return {
        "attempted": attempted,
        "embedded": embedded,
        "skipped_empty": skipped_empty,
        "skipped_dedup": skipped_dedup,
        "failed": failed,
    }


# Session-level advisory lock key — only one reingest write-batch at a time across
# all workers (prevents the Lesson #25 compounding-memory OOM on overlapping batches).
_REINGEST_ADVISORY_LOCK_KEY = 0x5245494E  # ascii "REIN"
```

**Step 2 — lower the default + cap the ceiling** on the endpoint signature (line 2001).
Smaller batches keep each call short and memory bounded (Lesson #25):

```python
    limit: int = Query(10, ge=1, le=100),
```

**Step 3 — replace the synchronous write path.** Delete the current inline block from
`# --- Write path:` (~2071) through the end of the `for c in candidates:` loop (~2109) —
that includes the inline `from tools.ingest.pipeline import ingest_text` import and the
whole loop. Replace it with the advisory-locked, thread-offloaded version below.

> **G0 #1809 HIGH fold — the session lock MUST run on a DEDICATED DIRECT (non-pooled)
> connection.** `store._get_conn()` hands back the pgbouncer **transaction-mode** pool
> (`config.postgres.dsn_params`), which resets session state on every commit and would
> silently release a `pg_advisory_lock` (see `config/settings.py:192-200`
> `direct_dsn_params` docstring). Use `psycopg2.connect(**config.postgres.direct_dsn_params)`,
> acquire+release+**close** that same connection, and NEVER return it to the store pool.
> If `config.postgres.host_direct` is unset (direct endpoint unavailable), the pooled
> host cannot safely hold the lock — **fail loud** (`no_direct_dsn`) instead of claiming
> a false lock. `config` is already imported at `outputs/dashboard.py:29`
> (`from config.settings import config`).

```python
    # --- Write path: single-runner SESSION advisory lock on a DEDICATED DIRECT
    #     (non-pooled) connection. pgbouncer transaction-mode on the store pool resets
    #     session state on commit and would release the lock (codex G0 #1809 HIGH). ---
    import psycopg2
    from config.settings import config as _cfg
    if not getattr(_cfg.postgres, "host_direct", None):
        # Direct endpoint required for a session lock; pooled host is unsafe. Fail loud.
        return {
            "error": "no_direct_dsn",
            "reason": "session advisory lock requires a non-pooled (direct) Postgres endpoint; host_direct unset",
            "dry_run": False,
        }
    try:
        lock_conn = psycopg2.connect(**_cfg.postgres.direct_dsn_params)
        # MUST be autocommit (codex G0 #1815 HIGH): default psycopg2 (autocommit=False)
        # opens a transaction on the lock SELECT; the connection then sits
        # idle-in-transaction while the embed batch runs in the worker thread. Live
        # idle_in_transaction_session_timeout = 5min, so a slow batch (>5min) gets its
        # session killed and the advisory lock silently released → overlapping batch.
        # Precedent: triggers/scheduler_lease.py:63-67; BRIEF_SCHEDULER_SINGLETON_HARDEN_1.
        lock_conn.autocommit = True
    except Exception as conn_err:
        logger.error(f"reingest-missing direct connect failed: {conn_err}")
        try:
            lock_conn.close()  # may not be bound; guard
        except Exception:
            pass
        return {"error": "lock_connect_failed", "reason": str(conn_err), "dry_run": False}
    got_lock = False
    try:
        lc = lock_conn.cursor()
        lc.execute("SELECT pg_try_advisory_lock(%s)", (_REINGEST_ADVISORY_LOCK_KEY,))
        got_lock = bool(lc.fetchone()[0])
        lc.close()
        if not got_lock:
            return {
                "error": "backfill_in_progress",
                "reason": "another reingest batch holds the advisory lock",
                "dry_run": False,
            }
        # Blocking embed loop runs in a worker thread — event loop stays free.
        stats = await asyncio.to_thread(_reingest_embed_batch, candidates)
    except Exception as embed_err:
        logger.error(f"reingest-missing embed batch failed: {embed_err}")
        stats = {"attempted": 0, "embedded": 0, "skipped_empty": 0,
                 "skipped_dedup": 0, "failed": [{"id": None, "reason": str(embed_err)}]}
    finally:
        if got_lock:
            try:
                uc = lock_conn.cursor()
                uc.execute("SELECT pg_advisory_unlock(%s)", (_REINGEST_ADVISORY_LOCK_KEY,))
                uc.close()
            except Exception as unlock_err:
                logger.error(f"reingest-missing advisory unlock failed: {unlock_err}")
        # Dedicated connection — CLOSE it (session end also drops any held lock).
        # Never store._put_conn() this; it is not a pool connection.
        try:
            lock_conn.close()
        except Exception:
            pass

    attempted = stats["attempted"]
    embedded = stats["embedded"]
    skipped_empty = stats["skipped_empty"]
    skipped_dedup = stats["skipped_dedup"]
    failed = stats["failed"]
```

The existing `remaining_after` recount block (lines ~2111-2131) and the final `return`
dict (lines ~2133-2145) are UNCHANGED — `attempted/embedded/skipped_*/failed` are now
unpacked from `stats` above, so the return dict keys still resolve.

### Key Constraints
- Do NOT change the dry_run branch (lines 2054-2069) — it writes nothing, needs no lock.
- Do NOT change the candidate SELECT (2031-2038) or `_reingest_missing_counts` — fast SQL, stays on the event loop.
- The advisory lock MUST acquire + release on the **same** connection (`lock_conn`) — session-level locks are per-connection.
- Keep the lock scoped to the write path only; never around `dry_run`.
- `ingest_text` remains idempotent (dedup + deterministic point IDs) — re-running a partial batch is safe.
- One doc failing must not abort the batch (preserved in the helper).
- Every except block rolls back / cleans up (preserved above).

### Verification
- `pytest tests/test_reingest_missing_qdrant.py -v` — existing 11 must still pass (the refactor is behavior-preserving for the happy path).
- New test (Fix 2) proves the offload helper's failure-isolation contract.
- Live: see Done rubric.

---

## Fix 2: Test the offload helper

Add to `tests/test_reingest_missing_qdrant.py`:

```python
def test_reingest_embed_batch_isolates_failures(monkeypatch):
    """REINGEST_ASYNC_OFFLOAD_1: one doc raising must not abort the batch; counts classify."""
    import outputs.dashboard as dash

    class _Res:
        def __init__(self, skipped=False, reason=None):
            self.skipped = skipped; self.skip_reason = reason
    def _fake_ingest(**kw):
        if kw["document_id"] == 2:
            raise RuntimeError("voyage 429")
        if kw["document_id"] == 3:
            return _Res(skipped=True, reason="Duplicate (filename, file_hash)")
        return _Res(skipped=False)
    # helper imports `from tools.ingest.pipeline import ingest_text` at call time —
    # patch the source module attribute (verify this target resolves before asserting).
    monkeypatch.setattr("tools.ingest.pipeline.ingest_text", _fake_ingest)

    candidates = [
        {"id": 1, "filename": "a", "source_path": "a", "file_hash": "h1", "matter_slug": None, "full_text": "x"},
        {"id": 2, "filename": "b", "source_path": "b", "file_hash": "h2", "matter_slug": None, "full_text": "y"},
        {"id": 3, "filename": "c", "source_path": "c", "file_hash": "h3", "matter_slug": None, "full_text": "z"},
        {"id": 4, "filename": "d", "source_path": "d", "file_hash": "h4", "matter_slug": None, "full_text": "   "},
    ]
    stats = dash._reingest_embed_batch(candidates)
    assert stats["attempted"] == 4
    assert stats["embedded"] == 1          # doc 1
    assert stats["skipped_dedup"] == 1     # doc 3
    assert stats["skipped_empty"] == 1     # doc 4 (blank)
    assert len(stats["failed"]) == 1 and stats["failed"][0]["id"] == 2  # doc 2 raised
```

### Fix 2b — update the signature source-guard (G0 #1809 MED)
The existing source-introspection guard at `tests/test_reingest_missing_qdrant.py:43`
asserts the OLD signature and will now fail. Update it:

```python
    # was: assert "limit: int = Query(50, ge=1, le=500)" in decl
    assert "limit: int = Query(10, ge=1, le=100)" in decl
```

### Fix 2c — source-guards for the new invariants (cheap, match the file's existing style)
Add a source-introspection test that reads `outputs/dashboard.py` and asserts:

```python
def test_reingest_write_path_offloads_and_locks_on_direct_conn():
    """G0 #1809: write path must offload to a thread AND take the session lock on a
    dedicated DIRECT connection (never the pooled store conn)."""
    import inspect, outputs.dashboard as dash
    src = inspect.getsource(dash.documents_reingest_missing)
    assert "asyncio.to_thread(_reingest_embed_batch" in src        # offload
    assert "pg_try_advisory_lock" in src and "pg_advisory_unlock" in src
    assert "direct_dsn_params" in src                               # direct, not pooled
    assert "host_direct" in src                                     # fail-loud guard
    assert "store._put_conn(lock_conn)" not in src                 # NOT returned to pool
    assert "lock_conn.autocommit = True" in src                    # G0 #1815: no idle-in-txn lock drop
```

### Fix 2d — endpoint test: lock-held ⇒ backfill_in_progress (G0 #1809 MED)
Mock the direct connection so the lock returns False; adapt the client/store fixtures to
this file's existing harness (the suite already builds a fake store + candidate state —
reuse it; only `psycopg2.connect` and `config.postgres.host_direct` need mocking):

```python
def test_reingest_lock_held_returns_backfill_in_progress(monkeypatch, <existing client/store fixture>):
    monkeypatch.setattr("config.settings.config.postgres.host_direct", "direct.example", raising=False)

    class _LockCur:
        def execute(self, sql, params=None): self._sql = sql
        def fetchone(self):
            return (False,) if "pg_try_advisory_lock" in self._sql else (None,)
        def close(self): pass
    class _LockConn:
        def cursor(self): return _LockCur()
        def close(self): pass
    monkeypatch.setattr("psycopg2.connect", lambda **kw: _LockConn())

    # ... set up candidates so the write path is reached (dry_run=false) ...
    r = client.post("/api/documents/reingest-missing?dry_run=false&limit=10",
                    headers={"X-Baker-Key": <test key>})
    assert r.status_code == 200
    assert r.json().get("error") == "backfill_in_progress"
```

This test is **mandatory** (codex G0 #1815 MED — this endpoint is an incident fix; the
lock behavior must be proven, not just source-guarded). If the existing fixture cannot
reach the write path cleanly, do NOT silently drop it — escalate to AH1 to resolve the
fixture; G3 will not pass on source guards alone.

---

## Files Modified
- `outputs/dashboard.py` — add `_reingest_embed_batch` + lock key; lower default limit 50→10 (cap 500→100); replace sync write loop with a **direct-connection** advisory lock + `asyncio.to_thread` offload (`psycopg2` + `config` imported locally in the handler).
- `tests/test_reingest_missing_qdrant.py` — update the signature guard (2b); add the failure-isolation unit test (2a), the offload/lock source-guards (2c), and the lock-held endpoint test (2d).

## Do NOT Touch
- The dry_run branch, candidate SELECT, `_reingest_missing_counts`, `_REINGEST_MISSING_QDRANT_PREDICATE`, `_HAS_EXTRACTED_TEXT` — all correct as shipped in #291.
- `tools/ingest/pipeline.py` — `ingest_text` is consumed as-is.
- Any other endpoint.

## Quality Checkpoints (post-deploy)
1. Live `dry_run=false&limit=10` run completes; `embedded > 0`.
2. Concurrent `GET /health` returns 200 <3s DURING that run (the core fix).
3. Concurrent second `POST` returns `backfill_in_progress`.
4. Two sequential calls: `remaining_after` strictly decreases.
5. No Render OOM/restart during a run (watch deploy logs / memory).

## Verification SQL
```sql
-- remaining embeddable rows (should fall toward 0 as batches run); single COUNT, no LIMIT needed
SELECT COUNT(*) FROM documents d
WHERE d.full_text IS NOT NULL AND length(btrim(d.full_text)) > 0
  AND NOT EXISTS (
    SELECT 1 FROM ingestion_log il
    WHERE il.filename = d.filename AND il.file_hash = d.file_hash
  );
-- canonical source of truth = _REINGEST_MISSING_QDRANT_PREDICATE + _HAS_EXTRACTED_TEXT.
```

## POST_DEPLOY_AC_VERDICT v1 (B-code fills on prod, after merge+deploy)
- AC1 health-during-backfill: PASS/FAIL + the two timestamps.
- AC2 advisory-lock: PASS/FAIL + the `backfill_in_progress` response.
- AC3 convergence: PASS/FAIL + two `remaining_after` values.
- Overall: PASS only if all three pass on the live instance.
