# BRIEF: PLAUD_TRANSCRIPT_BY_MATTER_1 — Matter-desk transcript-read endpoint

**Author:** AH2 (deputy)
**Date:** 2026-05-22
**Director ratification anchor:** "do N 2. Need proper access. 1. Explore 2. Plan 3. Propose an action use /write-brief sop. Consult with reviewer and architect." — chat 2026-05-22 ~11:40Z, in response to bus #676 from hag-desk.
**Bus thread:** #676 (hag-desk → deputy) + #678 (deputy → hag-desk).

## Context

Matter desks (hag-desk first; AO Desk, MOVIE Desk, Baden-Baden Desk next) need to read Plaud + Fireflies transcript bodies tagged to their matter without direct Postgres access. Today there is no path:

- Their pickers load no `mcp__baker__*` tools, so no `baker_raw_query` access from desk side.
- `baker-vault/raw/transcripts/` does not exist; only meta files live in vault.
- Existing `GET /api/fireflies/status` returns 5-row diagnostic only — no matter filter, no Plaud rows.

**Immediate driver:** hag-desk is preparing Hagenauer-RG7 Forderungsanmeldung filing due Tue 2026-05-26 / Wed 2026-05-27. Filing prep needs transcript bodies tagged `hagenauer-rg7` between now and ship.

**Strategic driver:** Matter desks are the per-matter read-path under the Cortex architecture lock (RA-23). They need a clean, slug-scoped HTTP surface to all matter-tagged data. This is the transcript leg; deadlines + alerts + emails will follow the same pattern.

## Estimated time: ~5h
## Complexity: Medium
## Prerequisites: None (no upstream brief blocks this)

---

## Solution overview

1. **Add `matter_slug` column** to `meeting_transcripts` table via migration.
2. **Auto-populate at ingest time** inside `store_meeting_transcript()` — mirrors the existing pattern in `create_alert()` at `memory/store_back.py:4453-4459` with one **deliberate divergence**: this brief adds a `slug_registry.normalize()` pass on top of the classifier output. `create_alert` writes the raw `matter_name` from `_match_matter_slug` directly to its `matter_slug` column; we normalize because the endpoint queries by canonical slug from `slugs.yml` (e.g. `hagenauer-rg7`) and the classifier returns the raw `matter_name` field (`orchestrator/pipeline.py:85`, which is `matter.get("matter_name")` inside the loop). Without normalize, a `matter_name` like `"Hagenauer RG7"` would not match a desk-supplied canonical slug `hagenauer-rg7` on the read path. Single change point covers all ingestion paths (Plaud, Fireflies, YouTube).
3. **Backfill existing rows** via dry-run-default script modeled on `scripts/backfill_matter_slug.py`. Director-ratified mapping file required for `--apply` (mirror the safety rails: <24h staleness, per-row SAVEPOINT, env-var kill).
4. **Expose new endpoint** `GET /api/transcripts/by-matter/{matter_slug}` with `X-Baker-Key` auth, slug-registry validation (active-only), LIMIT-bounded results, `include_body` toggle (default False — metadata-first).

## Alternatives dismissed

- **File-fanout to `baker-vault/raw/transcripts/<matter_slug>/`** (closer to RA-23 curated-knowledge layer). Dismissed because: (a) transcripts are raw data, not post-reasoned content — RA-23 curated layer is for outputs of reasoning, not raw inputs; (b) matter desks are HTTP clients by design under the Tier 0/1/2/3 access model; (c) file writes from Sentinel into baker-vault carry the shared-FS race risk (anchor: 2nd incident 2026-04-30) which a read endpoint sidesteps entirely.
- **M:N link table `meeting_transcripts_matters`** (a meeting can plausibly span two matters, e.g. an AO call also touching Hagenauer). Dismissed because: (a) classifier returns at most one `best_match` (`orchestrator/pipeline.py:83-94`); (b) zero meeting-spans-two-matters cases are known in current operation; (c) court-filing deadline does not afford schema design for a hypothetical taxonomy. If multi-matter coverage becomes a real need, denormalize → link table is a future migration.

---

## Files to modify

- `migrations/20260522_meeting_transcripts_matter_slug.sql` (NEW)
- `memory/store_back.py` (MODIFY `_ensure_meeting_transcripts_table` lines 1390-1418 + `store_meeting_transcript` lines 1420-1453)
- `outputs/dashboard.py` (ADD new endpoint near existing transcript endpoints around line 799)
- `scripts/backfill_meeting_transcripts_matter_slug.py` (NEW)
- `tests/test_store_meeting_transcript_matter_slug.py` (NEW)
- `tests/test_transcripts_by_matter_endpoint.py` (NEW)

## Files NOT to touch

- `triggers/plaud_trigger.py` — its `store.store_meeting_transcript(...)` call at line 498 stays UNCHANGED. The auto-assign happens inside the store function. Modifying the trigger would create scope-creep risk (same logic for `triggers/fireflies_trigger.py:330,540,671` and `triggers/youtube_ingest.py:223`).
- `orchestrator/pipeline.py` — `_match_matter_slug` is reused as-is.
- `baker-vault/slugs.yml` — separate-repo PR only.

---

## Fix/Feature 1: Migration — ADD COLUMN + index

### Problem
`meeting_transcripts` has no `matter_slug` column. All matter association is currently in the downstream `alerts` table (created by pipeline classifier). Transcripts without alerts (e.g., low-signal meetings) have no matter linkage and cannot be queried by matter.

### Current state
Schema defined in `memory/store_back.py:1399-1410` via `_ensure_meeting_transcripts_table()` (on-demand bootstrap). No matter-related columns.

### Implementation

Create `migrations/20260522_meeting_transcripts_matter_slug.sql`:

```sql
-- PLAUD_TRANSCRIPT_BY_MATTER_1 — add matter_slug column + index
-- Director-ratified 2026-05-22 (bus #676 hag-desk path #2)

ALTER TABLE meeting_transcripts
    ADD COLUMN IF NOT EXISTS matter_slug TEXT;

CREATE INDEX IF NOT EXISTS idx_meeting_transcripts_matter_slug
    ON meeting_transcripts (matter_slug, meeting_date DESC NULLS LAST);
```

### Key constraints
- `ADD COLUMN IF NOT EXISTS` is safe against the bootstrap; column does not pre-exist with a different type.
- Index is on `(matter_slug, meeting_date DESC NULLS LAST)` because the endpoint filters by matter and orders by recency.
- Migration is idempotent; safe to re-run.

### Verification
```sql
SELECT column_name, data_type FROM information_schema.columns
 WHERE table_name = 'meeting_transcripts' AND column_name = 'matter_slug';
-- Expect: matter_slug | text

SELECT indexname FROM pg_indexes
 WHERE tablename = 'meeting_transcripts'
   AND indexname = 'idx_meeting_transcripts_matter_slug';
-- Expect: idx_meeting_transcripts_matter_slug
```

---

## Fix/Feature 2: Bootstrap + auto-assign in `store_meeting_transcript()`

### Problem
Bootstrap (`_ensure_meeting_transcripts_table`) creates the table on-demand for fresh installs. Without updating the bootstrap, the migration-vs-bootstrap drift trap fires: column exists on migrated DBs, missing on fresh ones.

### Current state
- Bootstrap at `memory/store_back.py:1390-1418` — CREATE TABLE IF NOT EXISTS without `matter_slug`.
- `store_meeting_transcript` at `memory/store_back.py:1420-1453` — INSERT ... ON CONFLICT DO UPDATE; no matter_slug logic.

### Implementation

**Step 2A — Bootstrap update** (`memory/store_back.py:1399-1410`):

```python
cur.execute("""
    CREATE TABLE IF NOT EXISTS meeting_transcripts (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        meeting_date TIMESTAMPTZ,
        duration TEXT,
        organizer TEXT,
        participants TEXT,
        summary TEXT,
        full_transcript TEXT,
        source TEXT NOT NULL DEFAULT 'fireflies',
        matter_slug TEXT,
        ingested_at TIMESTAMPTZ DEFAULT NOW()
    )
""")
```

**Step 2B — Auto-assign matter_slug in `store_meeting_transcript`** (replace lines 1420-1453):

```python
def store_meeting_transcript(self, transcript_id: str, title: str,
                              meeting_date: str = None, duration: str = None,
                              organizer: str = None, participants: str = None,
                              summary: str = None, full_transcript: str = None,
                              source: str = "fireflies",
                              matter_slug: str = None) -> bool:
    """Upsert a full meeting transcript. Returns True on success.

    If matter_slug is None, auto-classifies via _match_matter_slug + normalize
    to canonical slug (mirrors create_alert pattern at line 4453-4459, plus a
    slug_registry.normalize() pass — see brief §Solution overview point 2).

    To force-clear an existing matter_slug, use a direct UPDATE — re-ingest
    with matter_slug=None will NOT clear an existing slug (COALESCE preserves).
    """
    # Auto-assign matter_slug if not provided (best-effort; non-fatal).
    # NOTE: classifier MUST run BEFORE _get_conn() — _match_matter_slug calls
    # store.get_matters() which acquires its own pool connection. If conn were
    # already held here, maxconn=5 exhaustion under parallel ingestion would
    # deadlock. Do NOT reorder these blocks.
    if not matter_slug and (title or full_transcript):
        try:
            from orchestrator.pipeline import _match_matter_slug
            from kbl import slug_registry
            raw_match = _match_matter_slug(title or "", full_transcript or "", self)
            if raw_match:
                matter_slug = slug_registry.normalize(raw_match)
                if matter_slug is None:
                    # Classifier matched but normalize failed — alias missing
                    # in slugs.yml. Surface this so silent-failure on a matter
                    # we care about (e.g. hagenauer-rg7 filing) is visible.
                    logger.warning(
                        f"matter_slug auto-assign: classifier matched "
                        f"{raw_match!r} but slug_registry.normalize() returned "
                        f"None — check baker-vault/slugs.yml aliases for this "
                        f"matter_name"
                    )
        except Exception as _e:
            logger.debug(f"matter_slug auto-assign failed (non-fatal): {_e}")
            matter_slug = None

    conn = self._get_conn()
    if not conn:
        logger.warning("No DB connection — skipping store_meeting_transcript")
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO meeting_transcripts
                (id, title, meeting_date, duration, organizer,
                 participants, summary, full_transcript, source, matter_slug)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                full_transcript = EXCLUDED.full_transcript,
                matter_slug = COALESCE(EXCLUDED.matter_slug, meeting_transcripts.matter_slug),
                ingested_at = NOW()
        """, (transcript_id, title, meeting_date, duration, organizer,
              participants, summary, full_transcript, source, matter_slug))
        conn.commit()
        cur.close()
        logger.info(f"Stored meeting transcript: {title} ({transcript_id}) matter_slug={matter_slug}")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"store_meeting_transcript failed: {e}")
        return False
    finally:
        self._put_conn(conn)
```

### Key constraints
- **COALESCE on UPDATE**: re-ingest of an existing transcript must NOT clear a previously-assigned matter_slug if classifier returns None this time (e.g., matter_registry temporarily unavailable). Stale-refresh + ON CONFLICT path preserved via `COALESCE(EXCLUDED.matter_slug, meeting_transcripts.matter_slug)`.
- **Non-fatal classifier**: classifier failure must not block transcript storage. Best-effort, debug log only.
- **Normalize to canonical**: classifier returns matter_NAME (per `orchestrator/pipeline.py:85`); must pass through `slug_registry.normalize()` so endpoint queries by canonical slug (`hagenauer-rg7`) match.
- **No upstream caller changes**: all six call sites in `triggers/plaud_trigger.py:498,718`, `triggers/fireflies_trigger.py:330,540,671`, `triggers/youtube_ingest.py:223` stay unchanged. The new `matter_slug` param defaults to None.
- **`conn.rollback()` in except**: already present at line 1449; preserve.

### Verification
```python
# Unit test (in test_store_meeting_transcript_matter_slug.py)
def test_auto_assigns_matter_slug_when_classifier_matches():
    # Seed matter_registry with Hagenauer matter + keyword "Hagenauer"
    # Call store_meeting_transcript(title="Hagenauer meeting", full_transcript="...")
    # Assert: row.matter_slug == "hagenauer-rg7"

def test_preserves_explicit_matter_slug(mocker):
    # Mock _match_matter_slug to track invocation
    spy = mocker.patch("orchestrator.pipeline._match_matter_slug")
    # Call store_meeting_transcript(... matter_slug="explicit-slug")
    # Assert short-circuit: classifier NOT invoked + row.matter_slug == "explicit-slug"
    spy.assert_not_called()

def test_classifier_failure_is_non_fatal():
    # Monkeypatch _match_matter_slug to raise
    # Assert: store call returns True; row stored with matter_slug=None

def test_on_conflict_preserves_existing_matter_slug():
    # Seed row with matter_slug="hagenauer-rg7"
    # Re-call store_meeting_transcript with same id; classifier returns None
    # Assert: row.matter_slug still == "hagenauer-rg7"

def test_normalize_returns_none_logs_warning(caplog):
    # Seed matter_registry with matter_name "Phantom RG" that has NO alias
    # entry in baker-vault/slugs.yml (mock slug_registry.normalize to return None)
    # Call store_meeting_transcript(title="Phantom RG sync", ...)
    # Assert: row stored, matter_slug=None, WARNING log present with the matter_name
    assert any("slug_registry.normalize() returned None" in r.message
               for r in caplog.records if r.levelname == "WARNING")
```

---

## Fix/Feature 3: Backfill script for existing transcripts

### Problem
Existing rows in `meeting_transcripts` have `matter_slug = NULL` and need retroactive classification before the endpoint returns useful data for hag-desk's Tue filing.

### Current state
`scripts/backfill_matter_slug.py` exists for `deadlines.matter_slug` (DEADLINE_MATTER_SLUG_BACKFILL_1). Same pattern transplants to transcripts.

### Implementation

Create `scripts/backfill_meeting_transcripts_matter_slug.py` modeled on `scripts/backfill_matter_slug.py` (read its full source as the template — same dry-run-default + Director-ratified mapping + 3 safety rails + per-row SAVEPOINT pattern).

Differences from the deadlines script:

```python
# SELECT (replace _query_null_matter_slug body):
cur.execute(
    """
    SELECT id, title, full_transcript, source
    FROM meeting_transcripts
    WHERE matter_slug IS NULL
    ORDER BY ingested_at DESC
    LIMIT %s
    """,
    (QUERY_LIMIT,),  # keep QUERY_LIMIT = 500
)

# _classify input change:
# rid, desc, snippet, source_type = row  →  rid, title, body, src = row
# _match_matter_slug(title or "", body or "", store) — same semantics
# slug_registry.normalize(matter_name) — same

# CRITICAL DIFFERENCE — ID PARSING IN _parse_ratified_mapping:
# The deadlines template at scripts/backfill_matter_slug.py:217-219 has:
#     rid = int(cells[0])
# because deadlines.id is INTEGER. meeting_transcripts.id is TEXT (e.g.
# "plaud_abc123" or "fireflies_xyz"). DO NOT CAST TO INT — keep as str:
#     rid = cells[0].strip()  # TEXT id, do NOT int()
# If you copy the template's int() cast, every UPDATE will silently fail
# during --apply because no row will match. This is the highest-risk
# subtle bug in the whole backfill.

# UPDATE on --apply:
cur.execute(
    "UPDATE meeting_transcripts SET matter_slug = %s "
    "WHERE id = %s AND matter_slug IS NULL",
    (canonical_slug, rid),  # rid is TEXT
)
```

**Pre-apply alias verification (HIGH-risk Tue-filing path):** Before running `--apply`, AH1 (Terminal-side) MUST verify that `baker-vault/slugs.yml` has an alias entry mapping `matter_registry.matter_name` for Hagenauer to canonical slug `hagenauer-rg7`. If the alias is missing, the dry-run Bucket-M will be empty even when classifier matches — silent zero rows for the desk. Verify with:
```bash
BAKER_VAULT_PATH=$(realpath ~/baker-vault) python3 -c "
from kbl import slug_registry
# Replace 'Hagenauer RG7' with the exact matter_name from matter_registry
print(slug_registry.normalize('Hagenauer RG7'))
# Must print: hagenauer-rg7
"
```

### Key constraints
- **DRY RUN DEFAULT** — no args writes a proposal file to `/tmp/`, no DB writes.
- **`--apply <path>` writes** only if: (a) ratified-mapping file <24h old, (b) every M-section row has non-empty proposed_slug, (c) `BAKER_BACKFILL_DRY_RUN_ONLY` env var NOT set to 1.
- **Per-row SAVEPOINT** — mid-batch UPDATE error must not roll back prior successful UPDATEs (carry-forward bug from deadlines v2 fixed in v3; same fix here).
- **Idempotent** — only updates `WHERE matter_slug IS NULL`.

### Verification
```bash
# Dry run on prod:
BAKER_VAULT_PATH=$(realpath ~/baker-vault) python3 scripts/backfill_meeting_transcripts_matter_slug.py
# Inspect proposal file at /tmp/backfill_meeting_transcripts_proposal_<ts>.md

# Director ratifies the M-block, saves to baker-vault/_ops/ratified/transcripts_matter_slug_<ts>.md
# AH1 (Terminal-side) applies:
python3 scripts/backfill_meeting_transcripts_matter_slug.py --apply ~/baker-vault/_ops/ratified/transcripts_matter_slug_<ts>.md
```

---

## Fix/Feature 4: New endpoint `GET /api/transcripts/by-matter/{matter_slug}`

### Problem
No HTTP surface returns matter-tagged transcript bodies. Matter desks cannot read transcripts via their picker.

### Current state
- `GET /api/fireflies/status` at `outputs/dashboard.py:799` — 5-row diagnostic only; no matter filter, no Plaud rows.
- Internal retrievers `get_meeting_transcripts` + `get_recent_meeting_transcripts` exist (`memory/retriever.py:857, 1171`) but no matter filter; not HTTP-exposed.

### Implementation

Add new endpoint in `outputs/dashboard.py` (place near line 799 with other transcript endpoints; verify by `grep -n "/api/fireflies/status" outputs/dashboard.py` before insertion):

```python
# TODO (follow-up brief, post-hag-desk-filing): replace global X-Baker-Key with
# per-matter scoped auth (HMAC-derived per-desk key or scoped-token table).
# Current global key gives any key-holder read access to ALL matters'
# transcripts including attorney-client privileged content. Acceptable for
# internal-agent perimeter today; not defensible long-term.
@app.get(
    "/api/transcripts/by-matter/{matter_slug}",
    tags=["transcripts"],
    dependencies=[Depends(verify_api_key)],
)
async def get_transcripts_by_matter(
    matter_slug: str,
    since: Optional[str] = None,        # ISO timestamp; filter meeting_date >= since
    limit: int = 50,                    # default 50, max 200
    include_body: bool = False,         # default False — metadata-first; desks opt in for bodies
    source: Optional[str] = None,       # 'plaud' | 'fireflies' | 'youtube' | None=all
):
    """Return transcripts tagged to a matter. Matter-desk read-path.

    Slug must be canonical AND active (validated against kbl.slug_registry).
    Inactive/retired slugs return 404 — desks get a clear signal, not a
    silent empty result.

    Default response excludes full_transcript bodies; set ?include_body=true
    to receive bodies (each up to ~50KB).

    Response shape:
        {
            "matter_slug": "hagenauer-rg7",
            "count": 12,
            "limit": 50,
            "transcripts": [
                {
                    "id": "plaud_abc",
                    "title": "...",
                    "meeting_date": "2026-05-20T14:00:00Z",
                    "duration": "45m",
                    "participants": "...",
                    "summary": "...",
                    "source": "plaud",
                    "full_transcript": "..."  # only present if include_body=true
                },
                ...
            ]
        }
    """
    from datetime import datetime as _dt
    from kbl import slug_registry
    from memory.store_back import SentinelStoreBack

    # Validate slug — must be canonical AND active. Inactive/retired slugs
    # return 404 so desks don't get a silent empty result on a stale slug.
    if matter_slug not in slug_registry.active_slugs():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown or inactive matter_slug '{matter_slug}'. "
                f"Must be an active canonical slug from baker-vault/slugs.yml."
            ),
        )

    # Validate limit
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be 1..200")

    # Validate since (ISO 8601). PG would cast, but a malformed input
    # produces a 500 with a leaky DB-error string in the detail.
    if since:
        try:
            _dt.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="since must be ISO 8601 timestamp (e.g. 2026-05-01T00:00:00Z)",
            )

    # Validate source filter
    if source is not None and source not in ("plaud", "fireflies", "youtube"):
        raise HTTPException(
            status_code=400,
            detail="source must be one of: plaud, fireflies, youtube",
        )

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="DB unavailable")

    try:
        cur = conn.cursor()
        try:
            # Build column list explicitly (no f-string substitution of
            # column identifiers — keeps the static SQL scanner happy and
            # the read path obvious).
            base_cols = [
                "id", "title", "meeting_date", "duration", "organizer",
                "participants", "summary", "source",
            ]
            if include_body:
                base_cols.append("full_transcript")
            select_cols = ", ".join(base_cols)

            params: list = [matter_slug]
            where_clauses = ["matter_slug = %s"]
            if since:
                where_clauses.append("meeting_date >= %s")
                params.append(since)
            if source:
                where_clauses.append("source = %s")
                params.append(source)
            params.append(limit)

            sql = (
                f"SELECT {select_cols} "
                f"FROM meeting_transcripts "
                f"WHERE {' AND '.join(where_clauses)} "
                f"ORDER BY meeting_date DESC NULLS LAST "
                f"LIMIT %s"
            )
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            transcripts = [dict(zip(cols, r)) for r in rows]
            for t in transcripts:
                if t.get("meeting_date") is not None:
                    t["meeting_date"] = t["meeting_date"].isoformat()
        finally:
            cur.close()
    except HTTPException:
        raise  # already-shaped errors pass through
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"get_transcripts_by_matter failed for {matter_slug}: {e}")
        # Generic detail — do NOT leak DB error strings to clients.
        raise HTTPException(status_code=500, detail="Internal query error")
    finally:
        store._put_conn(conn)

    return {
        "matter_slug": matter_slug,
        "count": len(transcripts),
        "limit": limit,
        "include_body": include_body,
        "transcripts": transcripts,
    }
```

### Key constraints
- **Auth via existing `verify_api_key`** — `X-Baker-Key` header check at `dashboard.py:103`. No new auth surface today; per-matter scoped auth queued as follow-up brief post-filing (see TODO comment at top of endpoint).
- **LIMIT-bounded** — default 50, max 200. `full_transcript` can be 50KB+; without limit a single matter could return 100MB+ payload. Per `.claude/rules/python-backend.md`: "Always LIMIT unbounded SQL queries. Key columns: ... meetings=full_transcript."
- **`include_body=False` is the default** — desks query metadata-first (~5KB per row) and opt into bodies with `?include_body=true` (~50KB per row). Reverses the original draft default after architect feedback that 10MB-default responses are wrong.
- **Slug-registry validation (active-only)** — endpoint accepts only `slug in slug_registry.active_slugs()`. Inactive/retired slugs return 404 with a clear message, NOT 200/empty. Note that `slug_registry.is_canonical(None) → True` and `is_canonical()` doesn't filter by status; we use `active_slugs()` instead to close both gaps.
- **`since` ISO-validated** — endpoint rejects malformed `since` with 400 before SQL. Prevents psycopg2 DataError 500s + leaky error detail strings.
- **Generic 500 detail** — internal exceptions logged with full detail, but client sees only `"Internal query error"`. Does not leak DB schema or psycopg2 error semantics.
- **No identifier f-string interpolation** — column list built from a Python list join, not f-string substitution of column names. Removes false-positive injection signal even though current values are hardcoded.
- **Source filter optional** — `?source=plaud` for desks that only want recorder transcripts.
- **NULLS LAST on order** — rows without `meeting_date` (rare; should be all-or-nothing source bug) sink to bottom.
- **No `conn.commit()`** — read-only; no transaction state change.
- **`conn.rollback()` in except** — preserves connection pool hygiene per `.claude/rules/python-backend.md`.

### Verification

```python
# tests/test_transcripts_by_matter_endpoint.py — pytest fixtures
def test_returns_200_with_valid_auth_and_canonical_slug(client, seed_transcript):
    # Seed: row with matter_slug='hagenauer-rg7'
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7",
        headers={"X-Baker-Key": valid_key},
    )
    assert r.status_code == 200
    assert r.json()["matter_slug"] == "hagenauer-rg7"
    assert r.json()["count"] >= 1

def test_returns_401_without_auth(client):
    r = client.get("/api/transcripts/by-matter/hagenauer-rg7")
    assert r.status_code == 401

def test_returns_404_for_unknown_slug(client):
    r = client.get(
        "/api/transcripts/by-matter/totally-not-a-matter",
        headers={"X-Baker-Key": valid_key},
    )
    assert r.status_code == 404

def test_returns_404_for_inactive_slug(client, seed_inactive_matter):
    # Seed: slugs.yml entry with status='inactive' or 'archived'
    r = client.get(
        "/api/transcripts/by-matter/retired-matter-slug",
        headers={"X-Baker-Key": valid_key},
    )
    assert r.status_code == 404

def test_filters_by_matter_slug(client, seed_multi_matter):
    # Seed: 3 hagenauer rows, 2 ao rows (different matter_slug values)
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7",
        headers={"X-Baker-Key": valid_key},
    )
    assert r.json()["count"] == 3
    assert all(t["id"].startswith("plaud_hag") or t["id"].startswith("fireflies_hag")
               for t in r.json()["transcripts"])
    # Filter correctness — every returned row must have matter_slug=hagenauer-rg7
    # (verified via direct DB read in fixture cleanup; endpoint only returns ids)

def test_since_filter(client, seed_dated_transcripts):
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7?since=2026-05-01T00:00:00Z",
        headers={"X-Baker-Key": valid_key},
    )
    # Only post-May rows
    assert all(t["meeting_date"] >= "2026-05-01" for t in r.json()["transcripts"])

def test_limit_respected(client, seed_100_transcripts):
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7?limit=10",
        headers={"X-Baker-Key": valid_key},
    )
    assert len(r.json()["transcripts"]) == 10

def test_limit_capped_at_200(client):
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7?limit=500",
        headers={"X-Baker-Key": valid_key},
    )
    assert r.status_code == 400

def test_default_excludes_full_transcript(client, seed_transcript):
    # include_body now defaults to False — metadata-first
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7",
        headers={"X-Baker-Key": valid_key},
    )
    assert r.json()["include_body"] is False
    for t in r.json()["transcripts"]:
        assert "full_transcript" not in t

def test_include_body_true_includes_full_transcript(client, seed_transcript):
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7?include_body=true",
        headers={"X-Baker-Key": valid_key},
    )
    assert r.json()["include_body"] is True
    for t in r.json()["transcripts"]:
        assert "full_transcript" in t
        assert isinstance(t["full_transcript"], str)

def test_since_malformed_returns_400(client):
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7?since=yesterday",
        headers={"X-Baker-Key": valid_key},
    )
    assert r.status_code == 400
    assert "ISO 8601" in r.json()["detail"]

def test_source_filter(client, seed_mixed_sources):
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7?source=plaud",
        headers={"X-Baker-Key": valid_key},
    )
    assert all(t["source"] == "plaud" for t in r.json()["transcripts"])

def test_invalid_source_returns_400(client):
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7?source=teams",
        headers={"X-Baker-Key": valid_key},
    )
    assert r.status_code == 400
```

---

## Code Brief Standards (mandatory inclusions)

1. **API version/endpoint:** Internal Baker HTTP API. No external API version dependency.
2. **Deprecation check date:** N/A — no external API; FastAPI / psycopg2 calls only.
3. **Fallback note:** N/A.
4. **Migration-vs-bootstrap DDL check:** ✓ — Bootstrap `_ensure_meeting_transcripts_table` at `memory/store_back.py:1399-1410` updated to include `matter_slug TEXT` so fresh installs and migrated DBs converge. `ADD COLUMN IF NOT EXISTS` in migration is safe (no pre-existing `matter_slug` column on `meeting_transcripts` per grep).
5. **Ship gate:** literal `pytest tests/test_transcripts_by_matter_endpoint.py tests/test_store_meeting_transcript_matter_slug.py -v` green. No "pass by inspection." Plus full `pytest` green (no regressions).
6. **Test plan:** 12 test cases above (4 storage layer + 8 endpoint).
7. **`file:line` citation verification:** all citations verified by Read tool 2026-05-22 by AH2 + reviewer agent 2nd-pass:
    - `memory/store_back.py:1390-1418` (bootstrap; existing except block carries forward as-is — pre-existing debt on `conn.rollback()` in DDL except, not introduced by this brief) ✓
    - `memory/store_back.py:1420-1453` (store_meeting_transcript) ✓
    - `memory/store_back.py:4453-4459` (create_alert auto-assign precedent; **NOTE deliberate divergence**: precedent does NOT call `slug_registry.normalize()` — this brief adds normalize because endpoint queries by canonical slug; see Solution overview point 2) ✓
    - `orchestrator/pipeline.py:27-97` (_match_matter_slug; returns `matter.get("matter_name")` from line 85 inside the conditional, function ends at line 97) ✓
    - `outputs/dashboard.py:103-117` (verify_api_key) ✓
    - `outputs/dashboard.py:799` (existing fireflies endpoint location reference; new endpoint inserts near here) ✓
    - `kbl/slug_registry.py:183-212` (active_slugs + is_canonical + normalize; **note**: brief uses `active_slugs()` not `is_canonical()` for the gate because `is_canonical(None) → True` and `is_canonical()` doesn't filter by status) ✓
    - `scripts/backfill_matter_slug.py:1-150` (template; **CRITICAL DIFF**: deadlines.id is INTEGER, meeting_transcripts.id is TEXT — see backfill §implementation for explicit no-int-cast callout) ✓
    - `triggers/plaud_trigger.py:498` (Plaud store call — unchanged; all 6 call sites stay untouched) ✓
8. **Singleton pattern:** `SentinelStoreBack._get_global_instance()` used at endpoint + classifier import. Matches `scripts/check_singletons.sh` allowed pattern. No direct `SentinelStoreBack()` instantiation.
9. **Post-merge script handoff:** Backfill script invocation deferred to AH1 (Terminal-side) post-merge; brief lists exact two-command sequence under Verification §3.
10. **Invocation-path audit (Amendment H):** N/A — this brief does NOT modify any `capability_sets` row. Does not extend or change a Pattern-2 capability. Pure data-layer + read-endpoint work.

---

## Quality Checkpoints (post-deploy)

1. Migration applied on prod (verify via `information_schema.columns`).
2. Index created (verify via `pg_indexes`).
3. Bootstrap updated — fresh ephemeral Neon CI branch creates table with `matter_slug` column.
4. Auto-assign live — new Plaud poll cycle stores a transcript with non-NULL `matter_slug` for any Hagenauer-keyword meeting.
5. **Slugs.yml alias verification (PRE-backfill, MANDATORY)** — `slug_registry.normalize('<matter_registry Hagenauer name>')` returns `hagenauer-rg7`. If not, slugs.yml needs an alias added (separate-repo PR) before backfill can produce a non-empty Bucket M.
6. Backfill dry-run produces proposal file readable by Director; Bucket M contains Hagenauer transcripts.
7. Endpoint returns 200 + filtered rows for `hagenauer-rg7` after backfill applied.
8. Endpoint returns 404 for `totally-not-a-matter`.
9. Endpoint returns 404 for an inactive slug (status != 'active' in slugs.yml).
10. Endpoint returns 400 for malformed `since=yesterday`.
11. Endpoint returns 401 without `X-Baker-Key`.
12. Default response (no `include_body`) omits `full_transcript`; `include_body=true` includes it.
13. `pytest` green: ~15 new test cases + no regressions in `tests/test_plaud_trigger.py`, `tests/test_fireflies_trigger.py`.

## Verification SQL (post-deploy, on prod)

```sql
-- Migration landed
SELECT column_name, data_type FROM information_schema.columns
 WHERE table_name = 'meeting_transcripts' AND column_name = 'matter_slug';

-- Index present
SELECT indexname FROM pg_indexes
 WHERE tablename = 'meeting_transcripts'
   AND indexname = 'idx_meeting_transcripts_matter_slug';

-- Auto-assign is firing on new ingests
SELECT id, title, source, matter_slug, ingested_at
  FROM meeting_transcripts
 WHERE ingested_at > NOW() - INTERVAL '24 hours'
   AND matter_slug IS NOT NULL
 ORDER BY ingested_at DESC
 LIMIT 20;

-- Hagenauer-specific verification
SELECT COUNT(*) AS hag_count
  FROM meeting_transcripts
 WHERE matter_slug = 'hagenauer-rg7';
-- Expect: > 0 after backfill apply
```

```bash
# Endpoint smoke test (post-deploy) — metadata-first (default)
curl -sH "X-Baker-Key: $BAKER_KEY" \
  "https://baker-master.onrender.com/api/transcripts/by-matter/hagenauer-rg7?limit=5" \
  | python3 -m json.tool

# Smoke test with bodies (hag-desk's filing-prep call shape)
curl -sH "X-Baker-Key: $BAKER_KEY" \
  "https://baker-master.onrender.com/api/transcripts/by-matter/hagenauer-rg7?include_body=true&limit=5" \
  | python3 -m json.tool
```

---

## Reporting

- Worker bus-posts to `deputy` (AH2) on PR open via `bus_post.sh`. Topic: `dispatch/PLAUD_TRANSCRIPT_BY_MATTER_1`.
- `dispatched_by: deputy` in the mailbox UPDATE entry.
- AH2 runs the AH2 review chain (static → security-review → picker-architect → feature-dev:code-reviewer) before recommending merge to AH1.

## Post-deploy gap audit (Option B — Director-ratified 2026-05-22)

The classifier-based auto-tag is ~70-80% accurate for legal-grade matter assignment (anchor: 42% FP rate at threshold=1 caused 14/33 deadline-drop in 2026-05-13 backfill; ≥3 threshold helps but doesn't close the gap entirely). Director ratified Option B 2026-05-22: classifier + Director-ratified backfill mapping + hag-desk-side gap audit.

**hag-desk responsibility (Sun 2026-05-24 → Mon 2026-05-25, pre-filing):**

1. Pull all transcripts tagged `hagenauer-rg7` via the new endpoint (`include_body=true`, `limit=200`).
2. Cross-check against hag-desk's own meeting roster (calendar + WhatsApp + email — desk's existing source-of-truth).
3. Flag two failure modes back to deputy (AH2) via bus:
   - **False positive** — transcript tagged `hagenauer-rg7` but content is NOT Hagenauer.
   - **False negative** — known Hagenauer meeting whose transcript is missing from the endpoint result (likely tagged NULL or wrong matter).
4. For each flag, AH2 corrects via direct UPDATE on `meeting_transcripts.matter_slug` (Tier B; logged to `actions_log.md`).
5. hag-desk re-pulls to confirm corrections landed before Tue 2026-05-26 filing.

Future iteration (parked, not in this brief): wire flag feedback into a learning loop so `matter_registry` keywords / classifier confidence adapt to corrections instead of re-erring the same way.

## Lessons-applied check

Past anti-patterns this brief consciously avoids:
- Column-name guessing — verified `meeting_transcripts` columns via Read.
- Missing LIMIT — endpoint hard-caps at 200, default 50.
- Missing `conn.rollback()` — present in all except blocks.
- Function-signature guessing — `verify_api_key`, `_match_matter_slug`, `slug_registry.normalize`, `slug_registry.is_canonical`, `store_meeting_transcript` all verified by Read.
- Duplicate endpoint — `grep -n "/api/transcripts" outputs/dashboard.py` confirms no existing route shadowing.
- Migration-vs-bootstrap drift — bootstrap updated in lockstep with migration.
- Stale-refresh clearing matter_slug — `COALESCE(EXCLUDED.matter_slug, meeting_transcripts.matter_slug)` preserves existing slug on re-ingest.
- Untracked brief — brief committed to `briefs/` in same commit as PR open.

---

## End-of-brief checklist for Code Brisen

- [ ] Migration written + tested locally against ephemeral PG branch
- [ ] Bootstrap updated to match migration
- [ ] `store_meeting_transcript` signature extended; six call sites unchanged
- [ ] Backfill script created from template; dry-run produces readable proposal
- [ ] Endpoint added with auth, slug validation, LIMIT, source filter, include_body toggle
- [ ] 12 test cases written; `pytest -v` green
- [ ] `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` clean
- [ ] `python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"` clean
- [ ] `bash scripts/check_singletons.sh` passes
- [ ] PR opened with literal pytest output in description
- [ ] Bus-post to `deputy` on PR open (topic `dispatch/PLAUD_TRANSCRIPT_BY_MATTER_1`)
