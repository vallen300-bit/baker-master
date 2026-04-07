# BRIEF: FIREFLIES-OOM-FIX — Stop Fireflies backfill from OOMing on deploy

## Context
Every `git push` triggers a deploy on Render. 60 seconds after startup, `backfill_fireflies()` runs a 30-day Fireflies transcript catch-up. This backfill:
1. Calls `backfill_transcripts_only()` which stores 50 transcripts to PG **AND** embeds each to Qdrant (20 chunks x 50 = 1000 Voyage AI calls)
2. Then iterates the SAME 50 transcripts again, running `pipeline.run()` for each (50 Claude/Gemini API calls + 50 more Qdrant embeddings)
3. If Render rolls two instances during deploy, both run the backfill concurrently

Result: memory goes 400MB → 2.28GB → 3.2GB → OOM in 10 minutes. Confirmed by Render metrics on 2026-04-07 instance `xx449` at 16:55-17:05 UTC.

The regular 15-minute poll path (`check_new_transcripts()`) is NOT affected — it processes 1-2 transcripts at a time and has proper dedup via `trigger_state.is_processed()`.

## Estimated time: ~1.5h
## Complexity: Medium
## Prerequisites: None

---

## Fix 1: Remove Qdrant embedding from `backfill_transcripts_only()`

### Problem
`backfill_transcripts_only()` docstring says "stores full transcripts to PostgreSQL only" but actually embeds every transcript to Qdrant too (lines 578-597). This is the first of two embedding passes that blow memory.

### Current State
File: `triggers/fireflies_trigger.py`, lines 578-597:
```python
            if success:
                # Embed in Qdrant for semantic search (with rate-limit delay)
                try:
                    import time as _time
                    _time.sleep(2)  # Voyage AI rate limit: avoid burst
                    embed_text = formatted["text"]
                    embed_metadata = {
                        "source": "fireflies",
                        "meeting_title": metadata.get("meeting_title", ""),
                        "date": metadata.get("date", ""),
                        "organizer": metadata.get("organizer", ""),
                        "participants": metadata.get("participants", ""),
                        "fireflies_id": source_id,
                        "content_type": "meeting_transcript",
                        "label": metadata.get("meeting_title", "meeting"),
                    }
                    store.store_document(embed_text, embed_metadata, collection="baker-conversations")
                    logger.info(f"Qdrant embed OK: {source_id} ({metadata.get('meeting_title', '?')})")
                except Exception as _e:
                    logger.error(f"Qdrant embed FAILED for {source_id}: {_e}")
```

### Implementation
**Delete lines 578-597** (the entire second `if success:` block with Qdrant embedding).

Replace with nothing. The first `if success:` block (line 575-576) that increments `stored` stays.

Also update the log message on line 599 to reflect PG-only:
```python
        logger.info(f"Transcript backfill complete: {stored} of {len(raw)} transcripts stored to PostgreSQL")
```

### Key Constraints
- Do NOT touch lines 565-576 (the PG store + counter). That stays.
- Do NOT touch the `fetch_transcripts()` call or the loop structure.
- The `/api/fireflies/backfill` endpoint calls this function directly — this fix makes that endpoint PG-only too, which is correct.

### Verification
After deploy, check logs for: `Transcript backfill complete: X of Y transcripts stored to PostgreSQL`
Should NOT see any `Qdrant embed OK` or `Capping N chunks to 20` log lines from this function.

---

## Fix 2: Remove `pipeline.run()` from `backfill_fireflies()`

### Problem
`backfill_fireflies()` calls `pipeline.run(trigger)` for each of ~50 transcripts (line 493). Each `pipeline.run()`:
- Calls Gemini Flash for classification/scoring
- Calls Claude Opus/Pro for analysis
- Retrieves context from Qdrant
- Embeds the interaction back to Qdrant

For 30-day-old transcripts, this is wasteful: ~$5-10 in API costs per deploy, plus ~2GB memory accumulation. The transcripts are already in PostgreSQL from the `backfill_transcripts_only()` call. New transcripts get full pipeline treatment via the regular 15-minute poll.

### Current State
File: `triggers/fireflies_trigger.py`, lines 492-496:
```python
            try:
                pipeline.run(trigger)
                ingested += 1
            except Exception as e:
                logger.error(f"Fireflies backfill: pipeline failed for {source_id}: {e}")
```

Also lines 440-441 (pipeline import/instantiation):
```python
        from orchestrator.pipeline import SentinelPipeline, TriggerEvent
        pipeline = SentinelPipeline()
```

### Implementation
1. **Delete lines 440-441** (pipeline import + instantiation)
2. **Replace lines 492-496** with a simple marker that increments `ingested`:
```python
            # OOM-FIX: Skip pipeline.run() for backfill transcripts.
            # Month-old meetings don't need real-time Claude/Gemini analysis.
            # New transcripts get full pipeline via 15-min check_new_transcripts() poll.
            ingested += 1
```

3. **Keep lines 467-473** (TriggerEvent construction) — actually, since we no longer call `pipeline.run()`, we don't need the TriggerEvent either. But `trigger_state` marking still uses `source_id`. Let me check... Actually, looking at the code, the dedup is via `trigger_state.is_processed("meeting", source_id)` on line 460, and the trigger is only used in `pipeline.run()`. Since we're removing `pipeline.run()`, we should also mark the transcript as processed so it doesn't get re-processed on the next backfill cycle:

Replace lines 467-496 with:
```python
            # OOM-FIX: Skip full pipeline for backfill transcripts.
            # Month-old meetings don't need real-time Claude/Gemini analysis.
            # New transcripts get full pipeline via 15-min check_new_transcripts() poll.
            # Mark as processed so next backfill skips it.
            trigger_state.mark_processed("meeting", source_id)
            ingested += 1
```

4. **Remove the `TriggerEvent` import** from line 440. Keep only what's needed:
```python
        from scripts.extract_fireflies import fetch_transcripts, format_transcript, transcript_date
```
(This import is already on line 431 — just remove lines 440-441 entirely.)

### Key Constraints
- Keep the PG store (lines 476-490) — transcripts still go to PostgreSQL
- Keep deadline extraction (lines 498-508) — deadlines are still extracted from backfill
- Keep commitment extraction (lines 510-519) — commitments are still extracted
- The only thing removed is `pipeline.run()` and its associated `TriggerEvent` construction

### Verification
After deploy, logs should show:
- `Fireflies backfill complete: ingested X of Y transcripts (skipped Z duplicates)`
- NO `pipeline` or `SentinelPipeline` log lines during backfill
- Memory should stay under 600MB during backfill (vs 3.2GB before)

---

## Fix 3: Add `conn.rollback()` to `store_meeting_transcript()` except block

### Problem
Missing `conn.rollback()` in the except block leaves the PostgreSQL connection in a dirty transaction state. Next query on the pooled connection fails with "current transaction is aborted, commands ignored until end of transaction block". This is Lesson #2/#3 from lessons.md.

### Current State
File: `memory/store_back.py`, lines 847-849:
```python
        except Exception as e:
            logger.error(f"store_meeting_transcript failed: {e}")
            return False
```

### Implementation
Add `conn.rollback()`:
```python
        except Exception as e:
            conn.rollback()
            logger.error(f"store_meeting_transcript failed: {e}")
            return False
```

### Key Constraints
- The `finally: self._put_conn(conn)` on line 850-851 stays unchanged.
- This follows the exact same pattern as every other method in store_back.py.

### Verification
Search for all except blocks in store_back.py that return without `conn.rollback()`:
```bash
grep -n "except Exception" memory/store_back.py | head -20
```
This fix addresses the one in `store_meeting_transcript`. If others are found, fix them too.

---

## Fix 4: Add PostgreSQL advisory lock to prevent concurrent backfills

### Problem
During Render deploy rollover, two instances briefly run simultaneously. Both start the 60s delayed backfill, causing double memory usage and duplicate work. The `_backfill_running` flag is process-local — it doesn't protect across instances.

### Current State
File: `triggers/fireflies_trigger.py`, lines 421-422:
```python
    _backfill_running = True
    logger.info("Fireflies backfill: starting 30-day catch-up...")
```

### Implementation
Add a PostgreSQL advisory lock at the top of `backfill_fireflies()`, after the API key check (after line 419):

```python
    # OOM-FIX: Prevent concurrent backfills across Render instances during deploy
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_lock(867531)")  # unique ID for fireflies backfill
            got_lock = cur.fetchone()[0]
            cur.close()
            store._put_conn(conn)
            if not got_lock:
                logger.info("Fireflies backfill: another instance holds the lock, skipping")
                return
    except Exception as _e:
        logger.warning(f"Advisory lock check failed (non-fatal, proceeding): {_e}")
```

And release the lock in the `finally` block (add before line 529):
```python
    finally:
        # Release advisory lock
        try:
            conn = store._get_conn()
            if conn:
                cur = conn.cursor()
                cur.execute("SELECT pg_advisory_unlock(867531)")
                cur.close()
                store._put_conn(conn)
        except Exception:
            pass  # Lock auto-releases on connection close
        _backfill_running = False
```

**NOTE:** The `store` variable needs to be accessible in `finally`. Move its initialization before the try block, or use a module-level helper. Simplest: wrap the lock acquisition in a helper function.

Actually, simpler approach — use `pg_try_advisory_xact_lock` with a dedicated connection that stays open for the duration:

Replace the advisory lock approach with a simpler pattern. Add at the top of `backfill_fireflies()`, after line 419:

```python
    # OOM-FIX: Prevent concurrent backfills across Render deploy overlap
    from memory.store_back import SentinelStoreBack
    _lock_store = SentinelStoreBack._get_global_instance()
    _lock_conn = _lock_store._get_conn()
    if _lock_conn:
        try:
            _lock_cur = _lock_conn.cursor()
            _lock_cur.execute("SELECT pg_try_advisory_lock(867531)")
            if not _lock_cur.fetchone()[0]:
                logger.info("Fireflies backfill: another instance holds the lock, skipping")
                _lock_cur.close()
                _lock_store._put_conn(_lock_conn)
                return
            _lock_cur.close()
        except Exception as _e:
            logger.warning(f"Advisory lock check failed (proceeding anyway): {_e}")
            _lock_store._put_conn(_lock_conn)
            _lock_conn = None
```

And in the `finally` block (line 528-529), add lock release:
```python
    finally:
        _backfill_running = False
        # Release advisory lock
        if _lock_conn:
            try:
                _lc = _lock_conn.cursor()
                _lc.execute("SELECT pg_advisory_unlock(867531)")
                _lc.close()
                _lock_store._put_conn(_lock_conn)
            except Exception:
                pass
```

### Key Constraints
- Advisory lock ID `867531` is arbitrary but unique. Don't reuse it elsewhere.
- `pg_try_advisory_lock` is non-blocking — returns false immediately if locked.
- Lock auto-releases if the connection is dropped (Render kill), so no deadlock risk.
- If the lock check itself fails (network issue), we proceed anyway — better to risk double-run than to skip backfill entirely.

### Verification
After deploy, check logs. During deploy rollover, one instance should log:
`Fireflies backfill: another instance holds the lock, skipping`

---

## Files Modified
- `triggers/fireflies_trigger.py` — Remove Qdrant embedding from backfill_transcripts_only, remove pipeline.run from backfill_fireflies, add advisory lock
- `memory/store_back.py` — Add conn.rollback() to store_meeting_transcript except block

## Do NOT Touch
- `outputs/dashboard.py` — Startup code is correct (single call, 60s delay, daemon thread)
- `triggers/embedded_scheduler.py` — Scheduler config is correct (DEPLOY-FIX-1 already removed next_run_time=now)
- `orchestrator/pipeline.py` — No changes needed
- `memory/store_back.py` `store_document()` — The UUID issue doesn't matter once backfill stops embedding. Future improvement: deterministic IDs.

## Quality Checkpoints
1. After deploy, memory stays under 800MB during backfill (was 3.2GB before)
2. `Transcript backfill complete` log shows PG-only (no Qdrant embed lines)
3. No `pipeline` log lines during backfill period (first 5 minutes after startup)
4. Regular 15-minute `check_new_transcripts` still runs normally with full pipeline
5. New transcripts (created after deploy) still get Qdrant embedding + pipeline analysis via regular poll
6. Syntax check: `python3 -c "import py_compile; py_compile.compile('triggers/fireflies_trigger.py', doraise=True)"`
7. Syntax check: `python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"`

## Verification SQL
```sql
-- Confirm transcripts are still being stored to PostgreSQL
SELECT id, title, meeting_date, ingested_at
FROM meeting_transcripts
ORDER BY ingested_at DESC
LIMIT 5;

-- Confirm advisory lock is not stuck
SELECT * FROM pg_locks WHERE locktype = 'advisory' AND objid = 867531;
```

## Cost Impact
- **Saves ~$5-10 per deploy** in Claude/Gemini API calls (50 pipeline.run() calls removed)
- **Saves ~1000 Voyage AI embedding calls per deploy** (50 transcripts x 20 chunks removed from backfill_transcripts_only)
- **Net API cost change:** Significant reduction. Regular poll path unchanged.
