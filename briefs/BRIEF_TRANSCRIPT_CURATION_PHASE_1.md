# BRIEF: TRANSCRIPT_CURATION_PHASE_1 — Slice-Level Data Layer (Postgres only)

## Context

Per canonical `_ops/processes/transcript-curation-architecture-v1.md` §1 (Q1 ratification: each transcript slice has ONE `primary_desk` + ZERO-OR-MORE `cross_ref_desks[]`) and §11 (Project-Room integration ratified 2026-05-23 pm). The current `meeting_transcripts` table carries a single `matter_slug` per row — structurally wrong per AID 5/5 source-class confirmation. A single transcript regularly touches multiple desks; we need slice-level granularity with primary owner + cross-refs + visibility + provenance.

This brief is **Phase 1 of a 4-phase sequence** (Director-ratified split 2026-05-23 evening):
- **Phase 1 (this brief)** — Schema + placeholder-row plumbing (Postgres only; no slicing, no LLM, no vault writes)
- **Phase 2** — Classifier (Gemini Pro per §2) + 3-branch write path + §11.7 hooks 1+2
- **Phase 3** — Backfill 33 mis-tagged transcripts + §11.7 hook 3 (room-existence precheck)
- **Phase 4** — Gold-set eval framework (E6) + override-rate metric

Upstream anchors: AH2 bus #771 (5 inheritance points + integration memo); architecture v1 doc commit baker-vault c9dc606; integration memo `_01_INBOX_FROM_CLAUDE/2026-05-23-aihead2-transcripts-into-rooms-integration.md`.

### Surface contract: N/A — pure backend (Postgres schema + internal store_back hook); no clickable surface introduced.

## Estimated time: ~4-5h
## Complexity: Low-Medium
## Prerequisites: none (additive only; no Phase 0 dependency)
## Dispatch target: b2 (b1 busy on BAKER_SUBSTACK_SEARCH_1 ~5-6h)

---

## Fix/Feature 1: `transcript_slices` table (E1 extended schema)

### Problem

No slice-level data model exists. Architecture v1 §1 + AID memo §1 Q3 require slice metadata (boundaries, primary_desk, cross_ref_desks[], visibility, confidence, statement_type, temporal fields, privilege_scope[]) — none of these have a home today.

### Current State

- `meeting_transcripts` (memory/store_back.py:1407) has columns: `id, title, meeting_date, duration, organizer, participants, summary, full_transcript, source, matter_slug, ingested_at` — single matter per row.
- 6 call sites of `store_meeting_transcript()`: 3× `triggers/fireflies_trigger.py` (lines 330, 540, 671), 2× `triggers/plaud_trigger.py` (lines 498, 718), 1× `triggers/youtube_ingest.py` (line 223).

### Implementation

**Step 1 — New migration `migrations/20260524_transcript_slices.sql`:**

```sql
-- TRANSCRIPT_CURATION_PHASE_1 — slice-level data layer
-- Per architecture v1 §1 (Q1 multi-desk routing) + E1 extended schema.
-- Additive only: existing meeting_transcripts table untouched (Phase 2 deprecates matter_slug).

CREATE TABLE IF NOT EXISTS transcript_slices (
    id TEXT PRIMARY KEY,
    transcript_id TEXT NOT NULL REFERENCES meeting_transcripts(id) ON DELETE CASCADE,

    -- Boundary metadata (Phase 1: whole-transcript placeholder; Phase 2 populates real boundaries)
    boundary_start INT NOT NULL DEFAULT 0,
    boundary_end INT NOT NULL DEFAULT 0,
    slice_text TEXT,
    chunk_header TEXT,

    -- Q1 multi-desk routing (Phase 2 populates via classifier)
    primary_desk TEXT,
    cross_ref_desks TEXT[] NOT NULL DEFAULT '{}',

    -- Q3 three-layer privacy (default desk-shared; Phase 2 routes personal slices)
    visibility TEXT NOT NULL DEFAULT 'desk-shared'
        CHECK (visibility IN ('desk-shared','director-personal','restricted')),

    -- Confidence scores (Phase 2 populates from boundary detector + classifier)
    confidence_boundary REAL,
    confidence_classifier REAL,

    -- E1 statement classification (Phase 2 populates)
    statement_type TEXT
        CHECK (statement_type IS NULL OR statement_type IN ('FACT','OPINION','DECISION','ACTION')),
    temporal_type TEXT,
    valid_at TIMESTAMPTZ,
    invalidated_by TEXT,

    -- Q7 privilege scope (Phase 2 populates)
    privilege_scope TEXT[] NOT NULL DEFAULT '{}',

    -- Routing provenance (Phase 2 populates: classifier model, version, override events)
    routing_provenance JSONB,

    -- Pipeline state machine
    status TEXT NOT NULL DEFAULT 'pending_classification'
        CHECK (status IN ('pending_classification','classified','overridden','quarantined')),

    -- §11.7 Hook 1: target_folder + cross_ref_stub_targets[] (Phase 2 populates)
    target_folder TEXT
        CHECK (target_folder IS NULL OR target_folder IN ('03_source_summaries','01_inbox','director-personal')),
    cross_ref_stub_targets JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_transcript_slices_status_primary_desk
    ON transcript_slices (status, primary_desk);
CREATE INDEX IF NOT EXISTS idx_transcript_slices_transcript_id
    ON transcript_slices (transcript_id);
CREATE INDEX IF NOT EXISTS idx_transcript_slices_visibility
    ON transcript_slices (visibility);
```

**Step 2 — Bootstrap function in `memory/store_back.py`** (mirror `_ensure_meeting_transcripts_table` at line 1398; place immediately after it):

```python
def _ensure_transcript_slices_table(self):
    """Create transcript_slices table if it doesn't exist.

    Per architecture v1 §1 + §11. Schema MUST match
    migrations/20260524_transcript_slices.sql exactly (migration-vs-bootstrap
    drift trap — Lesson #7).
    """
    conn = self._get_conn()
    if not conn:
        logger.warning("No DB connection — cannot ensure transcript_slices table")
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transcript_slices (
                id TEXT PRIMARY KEY,
                transcript_id TEXT NOT NULL REFERENCES meeting_transcripts(id) ON DELETE CASCADE,
                boundary_start INT NOT NULL DEFAULT 0,
                boundary_end INT NOT NULL DEFAULT 0,
                slice_text TEXT,
                chunk_header TEXT,
                primary_desk TEXT,
                cross_ref_desks TEXT[] NOT NULL DEFAULT '{}',
                visibility TEXT NOT NULL DEFAULT 'desk-shared'
                    CHECK (visibility IN ('desk-shared','director-personal','restricted')),
                confidence_boundary REAL,
                confidence_classifier REAL,
                statement_type TEXT
                    CHECK (statement_type IS NULL OR statement_type IN ('FACT','OPINION','DECISION','ACTION')),
                temporal_type TEXT,
                valid_at TIMESTAMPTZ,
                invalidated_by TEXT,
                privilege_scope TEXT[] NOT NULL DEFAULT '{}',
                routing_provenance JSONB,
                status TEXT NOT NULL DEFAULT 'pending_classification'
                    CHECK (status IN ('pending_classification','classified','overridden','quarantined')),
                target_folder TEXT
                    CHECK (target_folder IS NULL OR target_folder IN ('03_source_summaries','01_inbox','director-personal')),
                cross_ref_stub_targets JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_transcript_slices_status_primary_desk
                ON transcript_slices (status, primary_desk)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_transcript_slices_transcript_id
                ON transcript_slices (transcript_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_transcript_slices_visibility
                ON transcript_slices (visibility)
        """)
        conn.commit()
        cur.close()
        logger.info("transcript_slices table verified")
    except Exception as e:
        conn.rollback()
        logger.warning(f"Could not ensure transcript_slices table: {e}")
    finally:
        self._put_conn(conn)
```

Wire `_ensure_transcript_slices_table()` into the same bootstrap path that already calls `_ensure_meeting_transcripts_table()` (grep for the latter — call site is in `__init__` / lazy-bootstrap path). Add the new call immediately after.

### Key Constraints

- **Migration-vs-bootstrap drift (Lesson #7):** Bootstrap function CREATE TABLE statement MUST be byte-for-byte equivalent to migration SQL. If you edit one and not the other, prod will silently diverge. Verify with `diff <(grep -A 30 'CREATE TABLE.*transcript_slices' migrations/20260524_transcript_slices.sql) <(grep -A 30 'CREATE TABLE IF NOT EXISTS transcript_slices' memory/store_back.py)` — should match.
- `conn.rollback()` in except (Lesson: PostgreSQL connection-pool poisoning).
- No `ALTER` statements — table is brand new. ADD COLUMN IF NOT EXISTS pattern is for Phase 2+ where we extend.

### Verification

```sql
-- After deploy, confirm table exists with all columns
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'transcript_slices'
ORDER BY ordinal_position
LIMIT 50;

-- Confirm indexes
SELECT indexname FROM pg_indexes
WHERE tablename = 'transcript_slices';
-- Expected: idx_transcript_slices_status_primary_desk, idx_transcript_slices_transcript_id, idx_transcript_slices_visibility, plus primary key index
```

---

## Fix/Feature 2: Placeholder slice write hook

### Problem

Every new transcript ingested must get a placeholder slice row so Phase 2 has a queue to process. Without this, Phase 2 would need a separate "find unclassified transcripts" scan; the placeholder pattern keeps the slice state machine clean from day 1.

### Current State

`store_meeting_transcript()` (memory/store_back.py:1439) is the single write path for all 6 call sites. End of function commits the row.

### Implementation

**Step 3 — Add `store_transcript_slice_placeholder()` method in `memory/store_back.py`** (place immediately after `store_meeting_transcript`):

```python
def store_transcript_slice_placeholder(self, transcript_id: str, full_transcript_len: int) -> bool:
    """Insert ONE placeholder slice row for a freshly-ingested transcript.

    Phase 1 stub: boundary covers whole transcript (0 → full_transcript_len),
    status='pending_classification', primary_desk=NULL. Phase 2 classifier
    will either UPDATE this row with real boundaries+desk OR delete + insert
    multiple sliced rows (TBD in Phase 2 brief).

    Returns True on success, False on failure. NEVER raises — placeholder
    insert failure must NOT roll back the parent transcript write.
    """
    if not transcript_id:
        return False
    slice_id = f"{transcript_id}:placeholder"
    conn = self._get_conn()
    if not conn:
        logger.warning("No DB connection — cannot insert transcript_slices placeholder")
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO transcript_slices
                (id, transcript_id, boundary_start, boundary_end, status)
            VALUES (%s, %s, 0, %s, 'pending_classification')
            ON CONFLICT (id) DO NOTHING
        """, (slice_id, transcript_id, max(int(full_transcript_len or 0), 0)))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        conn.rollback()
        logger.warning(f"transcript_slices placeholder insert failed for {transcript_id}: {e}")
        return False
    finally:
        self._put_conn(conn)
```

**Step 4 — Hook placeholder write into `store_meeting_transcript()`** end. Locate the success-return path of `store_meeting_transcript` (around memory/store_back.py:1439+; grep for the function definition + final `return True` / `return success`). Just before the `return` on the success path:

```python
# TRANSCRIPT_CURATION_PHASE_1 — emit slice placeholder row for Phase 2 classifier queue.
# Non-fatal: placeholder failure does NOT roll back transcript write.
try:
    self.store_transcript_slice_placeholder(
        transcript_id=transcript_id,
        full_transcript_len=len(full_transcript) if full_transcript else 0,
    )
except Exception as e:
    logger.warning(f"transcript_slices placeholder hook raised (non-fatal): {e}")
```

### Key Constraints

- **Single-source-of-truth pattern:** ALL placeholder writes flow through `store_meeting_transcript`'s post-commit hook. Do NOT add direct calls to `store_transcript_slice_placeholder` from `triggers/*.py` files. Trigger files stay untouched.
- **Non-fatal:** placeholder failure logs + returns False. The parent transcript write is NOT rolled back. This preserves the existing 100% transcript-ingest success rate.
- **Idempotency:** `ON CONFLICT (id) DO NOTHING` handles re-ingest cleanly. A given `transcript_id` always maps to exactly one `transcript_id:placeholder` row until Phase 2 expands it.
- Lesson #7 (migration-bootstrap drift): no schema touches in this function — UPDATE/INSERT only.

### Verification

```sql
-- Confirm placeholder rows arrive 1:1 with new transcripts after deploy
SELECT
    (SELECT COUNT(*) FROM meeting_transcripts WHERE ingested_at > NOW() - INTERVAL '24 hours') AS new_transcripts,
    (SELECT COUNT(*) FROM transcript_slices WHERE created_at > NOW() - INTERVAL '24 hours' AND id LIKE '%:placeholder') AS placeholder_slices
LIMIT 1;
-- Expected: counts equal (within seconds of each other) once a new Plaud/Fireflies ingestion fires.

-- Confirm boundary span covers the transcript
SELECT ts.id, ts.boundary_start, ts.boundary_end, length(mt.full_transcript) AS transcript_len
FROM transcript_slices ts
JOIN meeting_transcripts mt ON mt.id = ts.transcript_id
WHERE ts.id LIKE '%:placeholder'
ORDER BY ts.created_at DESC
LIMIT 5;
-- Expected: boundary_end matches length(full_transcript) for each row.
```

---

## Fix/Feature 3: Tests

### Implementation

**Step 5 — New test file `tests/test_transcript_slices_placeholder.py`:**

```python
"""TRANSCRIPT_CURATION_PHASE_1 — verify placeholder slice row creation.

Tests live under TEST_DATABASE_URL (CI auto-provisions ephemeral Neon branch)
or auto-skip locally if TEST_DATABASE_URL unset.
"""
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set; live-PG tests auto-skip",
)


def _get_store():
    # _get_global_instance is a classmethod on SentinelStoreBack — call on the class, not module-level.
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def test_transcript_slices_table_exists():
    """Bootstrap creates table with all E1 columns."""
    store = _get_store()
    store._ensure_transcript_slices_table()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'transcript_slices'
        """)
        cols = {row[0] for row in cur.fetchall()}
        expected = {
            "id", "transcript_id", "boundary_start", "boundary_end", "slice_text",
            "chunk_header", "primary_desk", "cross_ref_desks", "visibility",
            "confidence_boundary", "confidence_classifier", "statement_type",
            "temporal_type", "valid_at", "invalidated_by", "privilege_scope",
            "routing_provenance", "status", "target_folder",
            "cross_ref_stub_targets", "created_at", "updated_at",
        }
        missing = expected - cols
        assert not missing, f"Missing columns: {missing}"
        cur.close()
    finally:
        store._put_conn(conn)


def test_placeholder_inserted_on_transcript_store():
    """store_meeting_transcript triggers placeholder write."""
    store = _get_store()
    store._ensure_meeting_transcripts_table()
    store._ensure_transcript_slices_table()
    tid = "test_phase1_placeholder_001"
    ok = store.store_meeting_transcript(
        transcript_id=tid,
        title="Phase 1 placeholder test",
        full_transcript="alpha beta gamma " * 20,
        source="test",
    )
    assert ok is True
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, transcript_id, boundary_start, boundary_end, status
            FROM transcript_slices
            WHERE transcript_id = %s LIMIT 1
        """, (tid,))
        row = cur.fetchone()
        assert row is not None, "placeholder row missing"
        assert row[0] == f"{tid}:placeholder"
        assert row[2] == 0
        assert row[3] > 0
        assert row[4] == "pending_classification"
        cur.close()
    finally:
        store._put_conn(conn)
        # cleanup
        conn2 = store._get_conn()
        try:
            cur = conn2.cursor()
            cur.execute("DELETE FROM meeting_transcripts WHERE id = %s", (tid,))
            conn2.commit()
            cur.close()
        finally:
            store._put_conn(conn2)


def test_placeholder_idempotent_on_reingest():
    """Re-ingesting same transcript_id does not create duplicate placeholder."""
    store = _get_store()
    store._ensure_meeting_transcripts_table()
    store._ensure_transcript_slices_table()
    tid = "test_phase1_placeholder_idempotent_001"
    for _ in range(3):
        store.store_meeting_transcript(
            transcript_id=tid,
            title="idempotent",
            full_transcript="text",
            source="test",
        )
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM transcript_slices WHERE transcript_id = %s", (tid,))
        count = cur.fetchone()[0]
        assert count == 1, f"expected 1 placeholder, got {count}"
        cur.close()
    finally:
        store._put_conn(conn)
        conn2 = store._get_conn()
        try:
            cur = conn2.cursor()
            cur.execute("DELETE FROM meeting_transcripts WHERE id = %s", (tid,))
            conn2.commit()
            cur.close()
        finally:
            store._put_conn(conn2)


def test_placeholder_failure_does_not_break_transcript_write():
    """If placeholder insert fails, transcript still commits."""
    store = _get_store()
    store._ensure_meeting_transcripts_table()
    # Don't create transcript_slices table — placeholder insert will fail; transcript should still land.
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS transcript_slices CASCADE")
        conn.commit()
        cur.close()
    finally:
        store._put_conn(conn)
    tid = "test_phase1_placeholder_resilient_001"
    ok = store.store_meeting_transcript(
        transcript_id=tid,
        title="resilient",
        full_transcript="text",
        source="test",
    )
    assert ok is True, "transcript write must succeed even when placeholder fails"
    # restore for downstream tests
    store._ensure_transcript_slices_table()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM meeting_transcripts WHERE id = %s", (tid,))
        conn.commit()
        cur.close()
    finally:
        store._put_conn(conn)
```

### Verification

```bash
pytest tests/test_transcript_slices_placeholder.py -v
# Expected: 4 passed (or 4 skipped locally if TEST_DATABASE_URL unset)
```

---

## Files Modified

- `migrations/20260524_transcript_slices.sql` — NEW; table + 3 indexes
- `memory/store_back.py` — NEW `_ensure_transcript_slices_table()` + `store_transcript_slice_placeholder()` + 5-line hook at end of `store_meeting_transcript` success path
- `tests/test_transcript_slices_placeholder.py` — NEW; 4 tests

## Do NOT Touch

- `triggers/fireflies_trigger.py` — placeholder flows via shared `store_meeting_transcript` path; no per-trigger changes
- `triggers/plaud_trigger.py` — same
- `triggers/youtube_ingest.py` — same
- `meeting_transcripts` table schema — additive only; `matter_slug` column stays (Phase 2 deprecates, not Phase 1)
- Vault filesystem (`baker-vault/wiki/`) — Phase 1 is Postgres-only
- Classifier / Gemini Pro infrastructure — Phase 2
- `kbl/slug_registry.py` — Phase 2 (when classifier needs to validate primary_desk against canonical slugs)
- `_match_matter_slug` auto-classifier in `store_back.py` — unchanged; Phase 2 supersedes

## Quality Checkpoints

1. Migration SQL applies cleanly on a fresh DB (`psql -f migrations/20260524_transcript_slices.sql`)
2. Bootstrap function CREATE TABLE statement byte-equivalent to migration (run the diff command in §"Key Constraints" of Feature 1)
3. `pytest tests/test_transcript_slices_placeholder.py -v` — 4 tests pass on literal output (NO "by inspection")
4. Full pytest suite passes (`pytest`) — no regression in existing transcript tests
5. Singleton guard passes: `bash scripts/check_singletons.sh`
6. Syntax check: `python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"`
7. After deploy: verification SQL queries in Feature 1 + Feature 2 return expected results
8. Render deploy succeeds; `meeting_transcripts` ingestion still working (sanity-check a recent Plaud or Fireflies ingestion produces 1 meeting_transcripts row + 1 transcript_slices placeholder row)
9. No new Render env vars required (Phase 2 will add `GEMINI_API_KEY` if not present)

## Verification SQL (post-deploy)

```sql
-- Confirm table + indexes
SELECT table_name FROM information_schema.tables WHERE table_name = 'transcript_slices';
SELECT indexname FROM pg_indexes WHERE tablename = 'transcript_slices' ORDER BY indexname;

-- Confirm placeholder pattern working 1:1 with transcript ingest (run ~30 min after first new ingestion)
SELECT
    DATE_TRUNC('hour', mt.ingested_at) AS hr,
    COUNT(DISTINCT mt.id) AS transcripts,
    COUNT(DISTINCT ts.id) FILTER (WHERE ts.id LIKE '%:placeholder') AS placeholders
FROM meeting_transcripts mt
LEFT JOIN transcript_slices ts ON ts.transcript_id = mt.id
WHERE mt.ingested_at > NOW() - INTERVAL '24 hours'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 24;
-- Expected: transcripts == placeholders for every hour with ingestion activity.
```

## Acceptance criteria

- **AC1** — migration file lands at `migrations/20260524_transcript_slices.sql` with the exact SQL above; runs clean on fresh DB
- **AC2** — `transcript_slices` table verified in production via Feature 1 verification SQL (22 columns, 3 named indexes + PK)
- **AC3** — `pytest tests/test_transcript_slices_placeholder.py -v` produces literal pass output (4 passed or 4 skipped); paste output verbatim in ship report
- **AC4** — `pytest` full suite passes; paste tail of output in ship report
- **AC5** — `bash scripts/check_singletons.sh` exits 0
- **AC6** — post-deploy verification SQL (24h placeholder/transcript count) shows 1:1 match — AH1 Tier-B post-deploy smoke (out-of-scope for ship report; ship on AC1-AC5)

## Reply target

```yaml
dispatched_by: lead
dispatched_at: <ISO timestamp on dispatch>
ship_report_routes_to: lead
```

## Gate chain (AH2 cross-lane review per #771)

- gate-1 architecture-review (AH2)
- gate-2 code-reviewer 2nd-pass (AH2)
- gate-3 /security-review (additive Postgres schema + no new external surfaces — expected NO_FINDINGS)
- gate-4 AH1 final review + merge

MEDIUM trigger class per AH2's #771 framing.

## Reference

- Canonical pattern: `_ops/processes/transcript-curation-architecture-v1.md` §1 + §11
- Integration memo: `_01_INBOX_FROM_CLAUDE/2026-05-23-aihead2-transcripts-into-rooms-integration.md`
- AH2 dispatch: bus #771 (5 inheritance points)
- Phase split rationale: Director ratification 2026-05-23 evening (4-phase brief sequence, this is Phase 1)
- Lesson #7: migration-vs-bootstrap drift trap
- baker-vault commit: c9dc606 (§11 fold)
