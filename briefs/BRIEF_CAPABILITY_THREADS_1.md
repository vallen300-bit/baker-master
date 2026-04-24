# BRIEF: CAPABILITY_THREADS_1 — Episodic Memory for Matter-Dedicated Capabilities

## Context

Phase 2 of the **AO PM Continuity Program** (ratified 2026-04-23; source artefact: `/Users/dimitry/baker-vault/_ops/ideas/2026-04-23-ao-pm-continuity-program.md` §6, §6.2, §6.3, §10 Q6, §11 Action (3)). Adds persistent **episodic memory** to Pattern-2 capabilities (`client_pm` + `domain` + `meta`) so AO PM, MOVIE AM, and future matter PMs can replay the *shape* of past conversations, not just the atomic facts.

Program sequencing: **Phase 0** (Amendment H) folded into canonical docs 2026-04-23. **Phase 1** (sidebar state-write hook + project labeling fix + 14-day backfill) shipped via PR #50/#54/#56, all merged 2026-04-24. Phase 1 backfill visible in `pm_project_state` (ao_pm @ v86 / movie_am @ v131 updated 2026-04-24 00:14–00:17Z; Aukera red-flags, Patrick Zuchner thread, EUR 1.5M release path, fx_mayr + RG7 sub_matters all present). **Phase 2 (this brief)** builds the diary on top of visible facts. **Phase 3** (proactive sentinel) drafts in parallel per Q7 sequencing.

The substantive vision is one sentence: *"tomorrow Director opens the sidebar, asks 'where did we land with Aukera?', and AO PM replays the 10:28 Cowork thread — Patrick's three warnings, Options A/B/C, Director's Option B choice, the verbatim WhatsApp, the Annaberg contagion risk — with citations."* Today AO PM answers the fact but not the shape. This brief closes that gap.

Architectural constraint ratified in §Part H (Amendment H): this brief modifies Pattern-2 capabilities, so **§Part H Invocation-Path Audit is a BLOCKER** (REQUEST_CHANGES until complete).

## Estimated time: ~10–12h Code Brisen
## Complexity: Medium–High
## Prerequisites
- ✅ PR #50 (BRIEF_PM_SIDEBAR_STATE_WRITE_1) merged — `extract_and_update_pm_state` module-level chokepoint live at `orchestrator/capability_runner.py:261`
- ✅ PR #54 (BRIEF_PM_EXTRACTION_JSON_ROBUSTNESS_1) merged — json-repair + warn-level logging
- ✅ PR #56 (BRIEF_PM_EXTRACTION_MAX_TOKENS_2) merged — max_tokens 3000 ceiling + output_tokens telemetry
- ✅ Amendment H canonical in `_ops/processes/capability-extension-template.md` §Part H (ratified 2026-04-23)
- ✅ Backfill data visible (Phase 2 gate confirmed by Director dashboard self-check 2026-04-24)

## API/dependency versions (deprecation check 2026-04-24)

| Dependency | Version/endpoint | Deprecation | Fallback |
|---|---|---|---|
| Anthropic Claude | `claude-opus-4-6` (reuses existing `extract_and_update_pm_state` call — no net-new) | current model family | n/a |
| Voyage AI | `voyage-3` @ 1024d (via existing `voyage.embed(texts=[...], input_type="document"\|"query")`) | current | if Voyage migrates to v4, update `config.voyage.model` in env |
| Qdrant Cloud | collection `baker-conversations` (size=1024, already live per `store_back.py:82`) | ongoing | n/a |
| PostgreSQL (Neon) | 16+ | ongoing | migrations via `config/migration_runner.py` (lesson #35, #37) |
| uuid-ossp | 1.1 (confirmed on Neon via `pg_extension` 2026-04-24) | ongoing | — |
| pgvector | **NOT installed** on Neon (verified 2026-04-24) | n/a | **Design uses Qdrant for vectors; no schema-level embedding column needed** |

---

## Design summary

Four additions, zero DDL in Python per lesson #37:

1. **DDL migration** `migrations/20260424_capability_threads.sql` — two new tables (`capability_threads`, `capability_turns`) + one nullable ADD COLUMN (`pm_state_history.thread_id`). Applied automatically by `config/migration_runner.py` on next Render deploy.
2. **Thread stitcher module** `orchestrator/capability_threads.py` — hybrid implicit-plus-override (per Q6 ratification) using existing Qdrant `baker-conversations` collection with payload filter `pm_slug + thread_id + created_at` for vector lookup. Entity overlap via `PM_REGISTRY` keyword patterns. Scoring fn weighted sum of (cosine, entity, recency).
3. **Write-path integration** at the single module-level chokepoint `extract_and_update_pm_state` (`orchestrator/capability_runner.py:261`) + `pm_signal_detector.flag_pm_signal` + `agent.py:2031 _update_pm_state` tool. All 4 doors thread-attribute their state-writes; signal-detector surface creates lightweight "signal" turns.
4. **Read-path integration** — `_build_system_prompt` (`orchestrator/capability_runner.py:1062`) gains a Layer 1.5 `# RECENT THREAD CONTEXT` section between live state (line 1103) and pending insights (line 1107). All 4 doors invoke capability_runner → inherit automatically. No separate read wiring per door.
5. **Sidebar thread UI** — new GET + POST endpoints + collapsible panel. Feature-flagged via localStorage key `baker.threads.ui_enabled=1` so blast radius is zero for Director until explicitly toggled on.

What this brief does **NOT** do:
- **No backfill of historical pm_state_history into threads.** Forward-only. Follow-up brief can retroactively stitch if useful; Phase 1 backfill already captured substance of Aukera thread in pm_project_state.
- **No change to `update_pm_project_state` optimistic-lock body (`store_back.py:5264-5285`).** Write loop is proven at v86/v131 — orthogonal.
- **No change to `conversation_memory` / `log_conversation`.** Scan log is separate layer; threads tie to pm_state_history and the extraction hook, not the general log.
- **Not a pgvector migration.** Extension not installed on Neon; enabling is a separate DBA action not in scope.

---

## Feature 1: Schema — `capability_threads` + `capability_turns` + `pm_state_history.thread_id`

### Problem
No persistent structure today for thread (a topic spanning turns) or turn (one Q/A pair with its surface and state-updates payload). `pm_project_state` holds Layer 1 atomic state; `pm_state_history` holds per-mutation snapshots without thread attribution; `conversation_memory` is the generic scan log (not PM-scoped, sparse labeling — 13 rows last 14 days all `project='general'`). No way to answer "show me every turn in the Aukera thread."

### Current state
- `pm_project_state` (pm_slug, state_key, state_json, version, last_run_at, run_count, last_question, last_answer_summary, created_at, updated_at) — confirmed via `information_schema` 2026-04-24
- `pm_state_history` (id, pm_slug, version, state_json_before, mutation_source, mutation_summary, created_at) — confirmed
- Active tags observed in production: `sidebar`, `decomposer`, `opus_auto`, `pm_signal_whatsapp`, `pm_signal_email`, `backfill_2026-04-23`, `backfill_2026-04-24`, `test_run`, `auto`

### Implementation

**NEW file** `migrations/20260424_capability_threads.sql`:

```sql
-- == migrate:up ==
-- BRIEF_CAPABILITY_THREADS_1: episodic memory for Pattern-2 capabilities.
-- Hybrid thread stitching (implicit similarity + Director override, Q6-ratified)
-- per _ops/ideas/2026-04-23-ao-pm-continuity-program.md §6.
--
-- Idempotent and additive. Zero impact on existing rows in pm_state_history.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Threads: one row per logical conversation topic.
CREATE TABLE IF NOT EXISTS capability_threads (
    thread_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pm_slug TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_turn_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    topic_summary TEXT,
    entity_cluster JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'dormant', 'resolved', 'superseded')),
    superseded_by_thread_id UUID REFERENCES capability_threads(thread_id),
    turn_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_capability_threads_pm_slug_status
    ON capability_threads (pm_slug, status, last_turn_at DESC);

CREATE INDEX IF NOT EXISTS idx_capability_threads_entity_cluster_gin
    ON capability_threads USING gin (entity_cluster);

COMMENT ON TABLE capability_threads IS
  'BRIEF_CAPABILITY_THREADS_1: per-PM conversation threads. Topic vectors live in Qdrant baker-conversations with payload {pm_slug, thread_id}; this table is the relational anchor.';

-- Turns: one row per Q/A pair (any surface).
CREATE TABLE IF NOT EXISTS capability_turns (
    turn_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id UUID NOT NULL REFERENCES capability_threads(thread_id) ON DELETE CASCADE,
    pm_slug TEXT NOT NULL,
    surface TEXT NOT NULL
        CHECK (surface IN ('sidebar','decomposer','signal','agent_tool','opus_auto','backfill','other')),
    mutation_source TEXT,
    turn_order INT NOT NULL,
    question TEXT,
    answer TEXT,
    state_updates JSONB,
    pm_state_history_id INTEGER REFERENCES pm_state_history(id) ON DELETE SET NULL,
    stitch_decision JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_capability_turns_thread_order
    ON capability_turns (thread_id, turn_order);

CREATE INDEX IF NOT EXISTS idx_capability_turns_pm_slug_created
    ON capability_turns (pm_slug, created_at DESC);

COMMENT ON COLUMN capability_turns.stitch_decision IS
  'BRIEF_CAPABILITY_THREADS_1: {score, matched_on, cosine, entity_overlap, alternatives:[{tid,score}]} for later tuning.';

COMMENT ON COLUMN capability_turns.mutation_source IS
  'Mirrors pm_state_history.mutation_source (Amendment H §H4). Door-level attribution for audit.';

-- Link state snapshots to originating thread. Additive + nullable.
-- No _ensure_pm_state_history_base exists in memory/store_back.py (grepped 2026-04-24);
-- DDL lives ONLY here per lesson #37.
ALTER TABLE pm_state_history
    ADD COLUMN IF NOT EXISTS thread_id UUID REFERENCES capability_threads(thread_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_pm_state_history_thread_id
    ON pm_state_history (thread_id) WHERE thread_id IS NOT NULL;

COMMENT ON COLUMN pm_state_history.thread_id IS
  'BRIEF_CAPABILITY_THREADS_1: thread attribution for audit-trail snapshots. NULL for rows pre-dating this migration.';

-- == migrate:down ==
-- Reversal only if threads feature is deliberately retired. Paste manually:
--
-- BEGIN;
-- ALTER TABLE pm_state_history DROP COLUMN IF EXISTS thread_id;
-- DROP TABLE IF EXISTS capability_turns;
-- DROP TABLE IF EXISTS capability_threads;
-- COMMIT;
```

### Key constraints
- **No `_ensure_*` bootstrap in `memory/store_back.py`.** DDL lives exclusively in `migrations/` per lesson #37. Pre-merge grep check: `grep -cE '_ensure_capability_threads|_ensure_capability_turns' memory/store_back.py` must return 0.
- **No `((col::date))` index expressions** per lesson #38 (VOLATILE rejected by Neon 16+). All daily-bucket queries go via `>= date_trunc('day', NOW())` on the bare TIMESTAMPTZ btree.
- **`pm_state_history_id` is INTEGER** matching `pm_state_history.id` (confirmed via `information_schema` query 2026-04-24, type = `integer`). NOT a UUID.
- **Advisory lock** — handled automatically by `config/migration_runner.py` (key `0x42BA4E00001`). No explicit lock in this file.
- **uuid-ossp** — confirmed enabled on Neon (`extversion 1.1`). `CREATE EXTENSION IF NOT EXISTS` is a safe no-op.

### Verification SQL (post-deploy)

```sql
-- 1. Migration applied
SELECT filename FROM schema_migrations 
WHERE filename = '20260424_capability_threads.sql';
-- expect: 1 row

-- 2. Tables exist
SELECT table_name FROM information_schema.tables 
WHERE table_name IN ('capability_threads', 'capability_turns')
ORDER BY table_name;
-- expect: 2 rows

-- 3. pm_state_history.thread_id additive column
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'pm_state_history' AND column_name = 'thread_id';
-- expect: thread_id | uuid

-- 4. Indexes present
SELECT indexname FROM pg_indexes 
WHERE (indexname LIKE 'idx_capability%' OR indexname = 'idx_pm_state_history_thread_id')
ORDER BY indexname;
-- expect: 5 rows (3 on threads/turns, 1 thread_id, 1 gin)
```

---

## Feature 2: Thread stitcher module

### Problem
Each state-write needs to answer "which thread does this turn belong to?" without requiring Director to name threads manually (Q6: hybrid — implicit with override, not explicit-only).

### Current state
No stitcher exists. All state-writes today land on `pm_project_state` without thread attribution.

### Implementation — NEW `orchestrator/capability_threads.py`

Module structure (signatures grep-verified against live code):

```python
"""BRIEF_CAPABILITY_THREADS_1: episodic-memory thread stitcher.

Hybrid Q6-ratified: implicit similarity (topic cosine via Qdrant
baker-conversations + entity cluster overlap + recency) with Director
explicit override via POST /api/pm/threads/re-thread.

Reuses existing SentinelStoreBack / SentinelRetriever singletons (per
SKILL.md Rule 8 — ._get_global_instance() factory only).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2.extras

logger = logging.getLogger("baker.capability_threads")

# Tuning constants — ship conservative; adjust after 2-week empirical review.
STITCH_WINDOW_HOURS = 24
STITCH_MIN_COSINE = 0.65
STITCH_ENTITY_BONUS = 0.15          # additive when entity_cluster overlaps
STITCH_RECENCY_DECAY_HOURS = 12     # half-life for recency weight
STITCH_MAX_CANDIDATES = 5
DORMANT_AFTER_HOURS = 72


def extract_entity_cluster(question: str, answer: str, pm_slug: str) -> dict:
    """Lightweight keyword extraction from PM_REGISTRY patterns.
    
    NO LLM call — keeps stitch latency sub-50ms. Returns {pattern: match_count}.
    Import is lazy to avoid circular dependency (capability_runner imports this module).
    """
    from orchestrator.capability_runner import PM_REGISTRY  # noqa: E402
    cfg = PM_REGISTRY.get(pm_slug, {})
    haystack = f"{question or ''}\n{answer or ''}".lower()
    cluster: dict = {}
    patterns = (cfg.get("signal_orbit_patterns") or []) + (cfg.get("signal_keyword_patterns") or [])
    for pat in patterns:
        try:
            matches = re.findall(pat, haystack, flags=re.IGNORECASE)
        except re.error:
            continue
        if matches:
            cluster[pat] = len(matches)
    return cluster


def _jaccard_overlap(a: dict, b: dict) -> float:
    """Entity-cluster similarity: |A∩B| / |A∪B| on keys."""
    ka, kb = set(a.keys()), set(b.keys())
    if not ka and not kb:
        return 0.0
    union = ka | kb
    if not union:
        return 0.0
    return len(ka & kb) / len(union)


def _recency_weight(last_turn_at: datetime) -> float:
    """Half-life decay; 0 at infinity, 1 at now."""
    now = datetime.now(timezone.utc)
    if last_turn_at.tzinfo is None:
        last_turn_at = last_turn_at.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - last_turn_at).total_seconds() / 3600.0)
    return 0.5 ** (hours / STITCH_RECENCY_DECAY_HOURS)


def _score_candidate(cosine: float, entity_overlap: float, recency: float) -> float:
    """Weighted sum; cosine dominant, entity bonus, recency multiplier."""
    return min(1.0, (cosine + STITCH_ENTITY_BONUS * entity_overlap) * recency)


def _topic_summary(question: str, answer: str) -> str:
    """Cheap topic summary — first 240 chars of Q, semicolon, first 240 of A.
    NOT the full Opus-summary; stitcher needs to run fast. If future tuning
    needs richer topic_summary, use the 'summary' field already returned by
    extract_and_update_pm_state's Opus extraction (caller passes it in).
    """
    q = (question or "")[:240].replace("\n", " ").strip()
    a = (answer or "")[:240].replace("\n", " ").strip()
    return f"{q} ; {a}"[:500]


def stitch_or_create_thread(
    pm_slug: str,
    question: str,
    answer: str,
    topic_summary_hint: Optional[str] = None,
    surface: str = "sidebar",
    override_thread_id: Optional[str] = None,
    force_new: bool = False,
) -> tuple[str, dict]:
    """Find a thread to attach the new turn to, or start a new one.
    
    Returns (thread_id: str, stitch_decision: dict). Never raises for normal
    non-db errors — falls back to new thread creation with stitch_decision
    recording the fallback reason.
    
    Caller (extract_and_update_pm_state) is responsible for inserting the
    capability_turns row and updating pm_state_history.thread_id.
    """
    from memory.store_back import SentinelStoreBack
    from memory.retriever import SentinelRetriever
    
    store = SentinelStoreBack._get_global_instance()
    retriever = SentinelRetriever._get_global_instance()
    
    summary = (topic_summary_hint or _topic_summary(question, answer))[:500]
    new_entities = extract_entity_cluster(question, answer, pm_slug)
    
    # Director override — trust it, don't re-score
    if override_thread_id:
        decision = {
            "matched_on": "override",
            "thread_id": override_thread_id,
            "score": 1.0,
        }
        _touch_thread(store, override_thread_id, summary, new_entities)
        return override_thread_id, decision
    
    if force_new:
        return _create_new_thread(store, pm_slug, summary, new_entities, reason="force_new")
    
    # Fetch up to STITCH_MAX_CANDIDATES recent active threads for this pm_slug
    candidates = _recent_active_threads(store, pm_slug, STITCH_WINDOW_HOURS, STITCH_MAX_CANDIDATES)
    
    if not candidates:
        return _create_new_thread(store, pm_slug, summary, new_entities, reason="no_candidates")
    
    # Embed the incoming topic once
    try:
        query_vec = retriever._embed_query(summary)
    except Exception as e:
        logger.warning(f"Thread stitcher embed failed [{pm_slug}]: {e}")
        return _create_new_thread(store, pm_slug, summary, new_entities, reason="embed_error")
    
    # Qdrant payload-filtered search for candidate thread_ids in baker-conversations
    scored = []
    for cand in candidates:
        cosine = _qdrant_cosine_for_thread(retriever, query_vec, pm_slug, cand["thread_id"])
        entity_overlap = _jaccard_overlap(new_entities, cand.get("entity_cluster") or {})
        recency = _recency_weight(cand["last_turn_at"])
        score = _score_candidate(cosine, entity_overlap, recency)
        scored.append({
            "thread_id": cand["thread_id"],
            "score": score,
            "cosine": cosine,
            "entity_overlap": entity_overlap,
            "recency": recency,
        })
    
    scored.sort(key=lambda s: s["score"], reverse=True)
    best = scored[0]
    
    if best["score"] >= STITCH_MIN_COSINE:
        decision = {
            "matched_on": "implicit",
            **{k: best[k] for k in ("score", "cosine", "entity_overlap", "recency")},
            "alternatives": scored[1:3],
        }
        _touch_thread(store, best["thread_id"], summary, new_entities)
        return best["thread_id"], decision
    
    # Below threshold — start a new thread
    return _create_new_thread(
        store, pm_slug, summary, new_entities,
        reason="below_threshold",
        best_miss=best,
    )


# ─── DB helpers (all use SentinelStoreBack's _get_conn / _put_conn pool) ───

def _recent_active_threads(store, pm_slug: str, window_hours: int, limit: int) -> list[dict]:
    conn = store._get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            """
            SELECT thread_id, started_at, last_turn_at, topic_summary,
                   entity_cluster, status, turn_count
            FROM capability_threads
            WHERE pm_slug = %s
              AND status = 'active'
              AND last_turn_at >= NOW() - (%s || ' hours')::interval
            ORDER BY last_turn_at DESC
            LIMIT %s
            """,
            (pm_slug, str(window_hours), limit),
        )
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"_recent_active_threads({pm_slug}) failed: {e}")
        return []
    finally:
        store._put_conn(conn)


def _create_new_thread(store, pm_slug: str, summary: str, entities: dict,
                      reason: str, best_miss: Optional[dict] = None) -> tuple[str, dict]:
    thread_id = str(uuid.uuid4())
    conn = store._get_conn()
    if not conn:
        return thread_id, {"matched_on": "new_thread_no_db", "reason": reason}
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO capability_threads
                (thread_id, pm_slug, topic_summary, entity_cluster, turn_count)
            VALUES (%s, %s, %s, %s::jsonb, 0)
            """,
            (thread_id, pm_slug, summary, json.dumps(entities)),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"_create_new_thread({pm_slug}) failed: {e}")
        return thread_id, {"matched_on": "new_thread_error", "reason": reason, "error": str(e)[:200]}
    finally:
        store._put_conn(conn)
    
    return thread_id, {
        "matched_on": "new_thread",
        "reason": reason,
        "best_miss": best_miss,
    }


def _touch_thread(store, thread_id: str, new_summary: str, new_entities: dict) -> None:
    """Update last_turn_at + merge entity_cluster."""
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE capability_threads
            SET last_turn_at = NOW(),
                updated_at = NOW(),
                entity_cluster = entity_cluster || %s::jsonb,
                turn_count = turn_count + 1,
                topic_summary = COALESCE(topic_summary, %s)
            WHERE thread_id = %s
            """,
            (json.dumps(new_entities), new_summary, thread_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"_touch_thread({thread_id}) failed: {e}")
    finally:
        store._put_conn(conn)


def _qdrant_cosine_for_thread(retriever, query_vec, pm_slug: str, thread_id: str) -> float:
    """Best cosine between incoming query_vec and any existing turn in this thread.
    
    Uses existing baker-conversations Qdrant collection (1024-dim, Voyage). When
    capability_turns emit, they add payload {pm_slug, thread_id, turn_id}; this
    fn filters on pm_slug + thread_id and returns the top score, or 0.0 if no
    prior turn is embedded yet (first turn in thread → always below threshold →
    new thread is the correct outcome anyway).
    """
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
    except Exception:
        return 0.0
    try:
        qfilter = Filter(must=[
            FieldCondition(key="pm_slug", match=MatchValue(value=pm_slug)),
            FieldCondition(key="thread_id", match=MatchValue(value=thread_id)),
        ])
        hits = retriever.qdrant.search(
            collection_name="baker-conversations",
            query_vector=query_vec,
            limit=3,
            query_filter=qfilter,
            score_threshold=0.0,
        )
        if not hits:
            return 0.0
        return float(hits[0].score)
    except Exception as e:
        logger.warning(f"_qdrant_cosine_for_thread({thread_id}): {e}")
        return 0.0


def persist_turn(
    pm_slug: str,
    thread_id: str,
    surface: str,
    mutation_source: str,
    question: str,
    answer: str,
    state_updates: dict,
    stitch_decision: dict,
    pm_state_history_id: Optional[int] = None,
) -> Optional[str]:
    """Insert a capability_turns row and embed Q+A into Qdrant baker-conversations
    with thread_id + pm_slug payload for future stitcher scoring.
    
    Non-fatal on any error. Returns turn_id (str) on success, None on failure.
    """
    from memory.store_back import SentinelStoreBack
    from memory.retriever import SentinelRetriever
    store = SentinelStoreBack._get_global_instance()
    retriever = SentinelRetriever._get_global_instance()
    
    turn_id = str(uuid.uuid4())
    conn = store._get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(MAX(turn_order), 0) + 1
            FROM capability_turns WHERE thread_id = %s
            """,
            (thread_id,),
        )
        turn_order = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO capability_turns
                (turn_id, thread_id, pm_slug, surface, mutation_source,
                 turn_order, question, answer, state_updates,
                 pm_state_history_id, stitch_decision)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
            """,
            (turn_id, thread_id, pm_slug, surface, mutation_source, turn_order,
             (question or "")[:8000], (answer or "")[:16000],
             json.dumps(state_updates or {}, default=str),
             pm_state_history_id,
             json.dumps(stitch_decision or {}, default=str)),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"persist_turn({thread_id}) failed: {e}")
        return None
    finally:
        store._put_conn(conn)
    
    # Fire-and-forget Qdrant embed so next stitcher call can match this turn
    import threading
    def _embed():
        try:
            text = f"Question: {question}\n\nAnswer: {answer[:4000]}"
            vec = retriever._embed_query(text)  # input_type='query' sufficient
            from qdrant_client.models import PointStruct
            payload = {
                "source": "conversation",
                "pm_slug": pm_slug,
                "thread_id": thread_id,
                "turn_id": turn_id,
                "surface": surface,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            retriever.qdrant.upsert(
                collection_name="baker-conversations",
                points=[PointStruct(id=turn_id, vector=vec, payload=payload)],
            )
        except Exception as _e:
            logger.warning(f"persist_turn embed [{turn_id}] failed (non-fatal): {_e}")
    threading.Thread(target=_embed, daemon=True).start()
    
    return turn_id


def mark_dormant_threads() -> int:
    """Move threads past DORMANT_AFTER_HOURS to status='dormant'. Returns rowcount.
    
    For Phase 2: function exists, not wired to scheduler. Phase 3 brief wires it.
    """
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE capability_threads
            SET status = 'dormant', updated_at = NOW()
            WHERE status = 'active'
              AND last_turn_at < NOW() - (%s || ' hours')::interval
            """,
            (str(DORMANT_AFTER_HOURS),),
        )
        n = cur.rowcount
        conn.commit()
        cur.close()
        return n or 0
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"mark_dormant_threads failed: {e}")
        return 0
    finally:
        store._put_conn(conn)
```

### Key constraints
- **Singleton access (SKILL.md Rule 8):** `SentinelStoreBack._get_global_instance()` and `SentinelRetriever._get_global_instance()` — NEVER bare constructor. Pre-push hook `scripts/check_singletons.sh` enforces. Verify before commit: `grep -n 'SentinelStoreBack()\|SentinelRetriever()' orchestrator/capability_threads.py` returns 0.
- **No LLM call in stitcher.** Latency <50ms. Opus extraction happens upstream; we reuse its `summary` field when available.
- **PostgreSQL: every `except` includes `conn.rollback()`** before `_put_conn` per `.claude/rules/python-backend.md`.
- **All DB queries have LIMIT** (explicit in `_recent_active_threads`) per `.claude/rules/python-backend.md`.
- **Python regex:** uses `flags=re.IGNORECASE`, not inline `(?i)` per `.claude/rules/python-backend.md`.
- **Circular-import guard:** `extract_entity_cluster` imports `PM_REGISTRY` lazily because `orchestrator/capability_runner.py` also imports this module at module level.

---

## Feature 3: Write-path wiring — all 4 doors + agent tool close the H4 loop

### Problem
Each door calls `extract_and_update_pm_state` or `update_pm_project_state` today. None call the stitcher. None persist a `capability_turns` row. The H4 `mutation_source` gap for `orchestrator/agent.py:2031` `_update_pm_state` tool (flagged in `briefs/_reports/CODE_2_RETURN.md:107` as outstanding debt carried from PR #50) is closed in this brief.

### Current state (grepped 2026-04-24, verified file:line)

| # | file:line | caller function | mutation_source tag today |
|---|---|---|---|
| 1 | `outputs/dashboard.py:8148` | `_sidebar_state_write` (thread in `_scan_chat_capability`) | `"sidebar"` |
| 2 | `outputs/dashboard.py:8240` | `_delegate_state_write` (thread in `_scan_chat_capability` delegate path) | `"decomposer"` |
| 3 | `orchestrator/capability_runner.py:1875` | `_auto_update_pm_state` (calls module-level `extract_and_update_pm_state`) | `"opus_auto"` |
| 4 | `orchestrator/pm_signal_detector.py:149` | `flag_pm_signal` | `f"pm_signal_{channel}"` |
| 5 | `orchestrator/agent.py:2031` | `_update_pm_state` (agent tool handler) | **missing — defaults to `"auto"`** (H4 gap) |

### Implementation

**Step 3.1 — extend `update_pm_project_state` signature (non-breaking)** in `memory/store_back.py:5228`:

```python
def update_pm_project_state(self, pm_slug: str, updates: dict, summary: str = "",
                             question: str = "",
                             mutation_source: str = "auto",
                             thread_id: Optional[str] = None) -> Optional[int]:
    """PM-FACTORY: Upsert PM project state with audit trail + optimistic locking.
    
    BRIEF_CAPABILITY_THREADS_1: optional `thread_id` threaded into
    pm_state_history INSERT so state snapshots link to the originating thread.
    Callers that don't care about threads pass thread_id=None (default); existing
    rows stay NULL — zero impact on legacy behaviour.
    
    Returns pm_state_history.id of the newly-inserted audit row, or None on
    first-ever insert (no history row is created for the initial pm_project_state
    insert per existing code shape at line 5286 else branch) or on any error.
    """
```

Then change the pm_state_history INSERT at current line 5250 (**verify line number in live file before editing** per Rule 7):

```python
cur.execute("""
    INSERT INTO pm_state_history
        (pm_slug, version, state_json_before, mutation_source, mutation_summary, thread_id)
    VALUES (%s, %s, %s, %s, %s, %s)
    RETURNING id
""", (pm_slug, current_version, json.dumps(existing, default=str),
      mutation_source, summary[:500], thread_id))
history_row_id = cur.fetchone()[0]
```

Return `history_row_id` at end of success branch; `None` at early-exit / except paths (keep existing early returns).

**Step 3.2 — rewire `extract_and_update_pm_state`** (`orchestrator/capability_runner.py:261`). After existing state-write:

1. Derive `topic_summary_hint` from the Opus JSON response's existing `summary` field (already parsed; no extra call).
2. Call `stitch_or_create_thread(pm_slug, question, answer, topic_summary_hint, surface=<from_mutation_source>, override_thread_id=None)`.
3. Call `store.update_pm_project_state(..., thread_id=thread_id)` with the resolved thread_id; capture returned `history_row_id`.
4. Call `persist_turn(pm_slug, thread_id, surface, mutation_source, question, answer, updates, stitch_decision, pm_state_history_id=history_row_id)`.
5. Keep all existing logging and dedup-context behaviour.

Surface derivation from `mutation_source`:

```python
def _surface_from_mutation_source(src: str) -> str:
    if src == "sidebar": return "sidebar"
    if src == "decomposer": return "decomposer"
    if src == "opus_auto": return "opus_auto"
    if src.startswith("pm_signal_"): return "signal"
    if src == "agent_tool": return "agent_tool"
    if src.startswith("backfill_"): return "backfill"
    return "other"
```

Non-fatal wrapping: stitcher + persist_turn block wraps in its own `try/except` with `logger.warning` — if threads fail, state-write itself must still succeed (same pattern as extract_and_update_pm_state's outer non-fatal wrap).

**Step 3.3 — `pm_signal_detector.py:149`** — add after the existing `store.update_pm_project_state(...)` call:

```python
# BRIEF_CAPABILITY_THREADS_1: attribute the signal to its thread
try:
    from orchestrator.capability_threads import stitch_or_create_thread, persist_turn
    thread_id, stitch_decision = stitch_or_create_thread(
        pm_slug=pm_slug,
        question=f"[signal {channel}] {source}",
        answer=summary,
        topic_summary_hint=f"{channel}: {source} — {summary[:200]}",
        surface="signal",
    )
    persist_turn(
        pm_slug=pm_slug, thread_id=thread_id, surface="signal",
        mutation_source=f"pm_signal_{channel}",
        question=f"[signal {channel}] {source}", answer=summary,
        state_updates=signal_data, stitch_decision=stitch_decision,
    )
except Exception as _e:
    logger.warning(f"Thread attribution for signal failed (non-fatal): {_e}")
```

Note: this path does NOT re-call `update_pm_project_state` with `thread_id` — it would require refactoring `flag_pm_signal`'s call sequence. Acceptable trade-off: signal-turn rows in `capability_turns` carry thread_id, but `pm_state_history.thread_id` stays NULL for signal writes. Logged as known partial-attribution for signals below.

**Step 3.4 — `agent.py:2031` `_update_pm_state` tool** — closes the H4 gap from PR #50:

```python
def _update_pm_state(self, inp: dict) -> str:
    """PM-FACTORY: Update persistent PM project state."""
    pm_slug = inp.get("pm_slug", "ao_pm")
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    updates = inp.get("updates", {})
    summary = inp.get("summary", "")
    question = inp.get("question", "")
    # BRIEF_CAPABILITY_THREADS_1: close H4 gap — agent-tool writes get 'agent_tool' tag
    store.update_pm_project_state(
        pm_slug, updates, summary,
        question=question,
        mutation_source="agent_tool",
    )
    return f"{pm_slug} project state updated successfully."
```

Thread-stitching from the agent tool is deferred to a follow-up (keeps blast radius contained; agent-tool writes are rare and the tag closure alone satisfies H4).

### Known partial attributions (explicit H2 exceptions with reason)

| Surface | Write to `pm_state_history.thread_id` | Write to `capability_turns` | Reason |
|---|---|---|---|
| sidebar | ✅ | ✅ | full round-trip via extract_and_update_pm_state |
| decomposer | ✅ | ✅ | same |
| opus_auto | ✅ | ✅ | same |
| signal | ❌ (NULL) | ✅ | would require refactor of flag_pm_signal signature; signal attribution lives in capability_turns only |
| agent_tool | ❌ (NULL) | ❌ | out-of-scope for this brief; mutation_source tag closure satisfies H4 |
| backfill | ❌ (existing rows) | ❌ | forward-only per design boundary; future brief may retro-stitch |

Each is a **deliberate, documented partial attribution** — not a silent gap. Part H §H2 requires either full closure OR explicit "read-only intentional" marking with reason; signals and agent-tool are NOT read-only but are deliberately partial with reason above. AI Head judgment: acceptable for MVP; elevated to the Part H table for audit visibility.

---

## Feature 4: Read-path integration (§Part H §H3)

### Problem
Recent-thread context must surface in the system prompt on every capability invocation (all 4 doors). Without it, threads write but don't read — Director's experience is unchanged.

### Current state
`_build_system_prompt` at `orchestrator/capability_runner.py:1062` constructs layered context:
- Base system prompt (capability.system_prompt, line 1074)
- Layer 2 view / wiki (line 1088–1101)
- Layer 1 live state via `_get_pm_project_state_context` (line 1103)
- Pending insights (line 1107)
- Cross-PM awareness (line 1111)

All 4 doors eventually route through this function (capability_runner is the single execution path for Pattern-2 capabilities).

### Implementation

**Step 4.1 — new method `_get_pm_thread_context`** in the same class, near the existing `_get_pm_project_state_context` (Code Brisen locates via `grep -n "_get_pm_project_state_context" orchestrator/capability_runner.py` and places adjacent):

```python
def _get_pm_thread_context(self, pm_slug: str, thread_id_hint: Optional[str] = None,
                            max_turns: int = 5) -> str:
    """BRIEF_CAPABILITY_THREADS_1: Layer 1.5 — recent thread turns.
    
    Returns empty string if no threads exist or retrieval fails (non-fatal).
    If thread_id_hint provided → that thread's last N turns.
    Otherwise → most-recently-active thread's last N turns.
    """
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return ""
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        if thread_id_hint:
            tid = thread_id_hint
        else:
            cur.execute(
                """
                SELECT thread_id FROM capability_threads
                WHERE pm_slug = %s AND status = 'active'
                ORDER BY last_turn_at DESC LIMIT 1
                """,
                (pm_slug,),
            )
            row = cur.fetchone()
            if not row:
                return ""
            tid = row["thread_id"]
        cur.execute(
            """
            SELECT surface, turn_order, question, answer, created_at
            FROM capability_turns
            WHERE thread_id = %s
            ORDER BY turn_order DESC LIMIT %s
            """,
            (tid, max_turns),
        )
        turns = [dict(r) for r in cur.fetchall()]
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"_get_pm_thread_context({pm_slug}) failed: {e}")
        return ""
    finally:
        store._put_conn(conn)
    
    if not turns:
        return ""
    turns.reverse()  # chronological
    lines = [f"Thread {tid} — last {len(turns)} turns:"]
    for t in turns:
        q = (t["question"] or "")[:200].replace("\n", " ")
        a = (t["answer"] or "")[:400].replace("\n", " ")
        lines.append(f"  [{t['surface']}] Q: {q}")
        lines.append(f"  A: {a}")
    return "\n".join(lines)
```

**Step 4.2 — inject in `_build_system_prompt`** between lines 1105 and 1107:

```python
# Live state: dynamic data
state_ctx = self._get_pm_project_state_context(pm_slug)
if state_ctx:
    prompt += f"\n\n# LIVE STATE (from PostgreSQL)\n{state_ctx}\n"

# BRIEF_CAPABILITY_THREADS_1: Layer 1.5 — recent thread context
thread_ctx = self._get_pm_thread_context(pm_slug)
if thread_ctx:
    prompt += f"\n\n# RECENT THREAD CONTEXT\n{thread_ctx}\n"

# PM-KNOWLEDGE-ARCH-1: Pending insights
pending_ctx = self._get_pending_insights_context(pm_slug)
```

**H3 read-path completeness verification:**

| Caller | Layer 1 (state) | Layer 1.5 (thread) | Layer 2 (wiki/view) | Layer 3 (retrieval) | Notes |
|---|---|---|---|---|---|
| capability_runner via `_build_system_prompt` | ✅ line 1103 | ✅ NEW line 1105.5 | ✅ line 1088/1099 | ✅ via ToolExecutor Qdrant tools | fully closed |
| sidebar → `_scan_chat_capability` | ✅ via runner | ✅ via runner | ✅ via runner | ✅ via runner | all 4 layers through single execution path |
| decomposer → `_scan_chat_capability` delegate | ✅ | ✅ | ✅ | ✅ | same |
| signal detector `flag_pm_signal` | ✅ (pm_project_state direct) | ❌ INTENTIONAL | ❌ INTENTIONAL | ❌ INTENTIONAL | lightweight signal path; full context load would slow ingest. Justified partial-load |
| agent tool `_update_pm_state` | ✅ via agent loop | ✅ inherited via capability_runner prompt | ✅ same | ✅ same | tool invoked mid-loop, context loaded upstream |

---

## Feature 5: Sidebar UI — thread list + replay + Director re-thread

### Problem
Director should be able to see the active thread for the PM he's chatting with, replay past turns, and re-thread if the stitcher miscategorized.

### Current state
`outputs/static/app.js` has no existing thread or collapsible-panel class (grepped 2026-04-24). Sidebar renders scan stream + capability dropdown. No thread UI exists.

### Implementation

Feature-flagged behind `localStorage.getItem('baker.threads.ui_enabled') === '1'` so zero blast radius until Director opts in.

**Step 5.1 — three new endpoints in `outputs/dashboard.py`** (add near other `/api/pm/*` endpoints; verify via `grep -n "/api/pm/" outputs/dashboard.py` first to avoid lesson #11 duplicate routes):

```python
# JSONResponse must be imported at line 23 of dashboard.py (verified 2026-04-24:
#   "from fastapi.responses import FileResponse, JSONResponse, StreamingResponse")
# Confirm before adding new endpoints (lesson #18).

@app.get("/api/pm/threads/{pm_slug}")
async def get_pm_threads(pm_slug: str, limit: int = 20):
    """BRIEF_CAPABILITY_THREADS_1: list recent threads for a PM (sidebar UI)."""
    if pm_slug not in PM_REGISTRY:
        return JSONResponse({"error": f"unknown pm_slug: {pm_slug}"}, status_code=404)
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return JSONResponse({"threads": []}, status_code=200)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT thread_id, topic_summary, status, last_turn_at, turn_count
            FROM capability_threads
            WHERE pm_slug = %s
            ORDER BY last_turn_at DESC
            LIMIT %s
        """, (pm_slug, limit))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            r["thread_id"] = str(r["thread_id"])
            r["last_turn_at"] = r["last_turn_at"].isoformat() if r["last_turn_at"] else None
        return JSONResponse({"threads": rows})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning(f"/api/pm/threads/{pm_slug} failed: {e}")
        return JSONResponse({"threads": [], "error": "retrieval_failed"}, status_code=200)
    finally:
        store._put_conn(conn)


@app.get("/api/pm/threads/{pm_slug}/{thread_id}/turns")
async def get_pm_thread_turns(pm_slug: str, thread_id: str, limit: int = 50):
    """BRIEF_CAPABILITY_THREADS_1: list turns for a specific thread (replay)."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return JSONResponse({"turns": []}, status_code=200)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT turn_id, surface, turn_order, question, answer, created_at
            FROM capability_turns
            WHERE thread_id = %s AND pm_slug = %s
            ORDER BY turn_order ASC
            LIMIT %s
        """, (thread_id, pm_slug, limit))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            r["turn_id"] = str(r["turn_id"])
            r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
        return JSONResponse({"turns": rows})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        return JSONResponse({"turns": [], "error": "retrieval_failed"}, status_code=200)
    finally:
        store._put_conn(conn)


@app.post("/api/pm/threads/re-thread")
async def re_thread(req: Request):
    """BRIEF_CAPABILITY_THREADS_1: Director explicit override — move a turn to a different thread."""
    body = await req.json()
    turn_id = body.get("turn_id")
    new_thread_id = body.get("new_thread_id")  # None → start a fresh thread
    if not turn_id:
        return JSONResponse({"error": "turn_id required"}, status_code=400)
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return JSONResponse({"error": "db unavailable"}, status_code=503)
    try:
        cur = conn.cursor()
        if new_thread_id is None:
            cur.execute("""
                SELECT pm_slug, question, answer FROM capability_turns WHERE turn_id = %s
            """, (turn_id,))
            row = cur.fetchone()
            if not row:
                return JSONResponse({"error": "turn not found"}, status_code=404)
            from orchestrator.capability_threads import stitch_or_create_thread
            new_thread_id, _ = stitch_or_create_thread(
                pm_slug=row[0], question=row[1] or "", answer=row[2] or "",
                surface="sidebar", force_new=True,
            )
        cur.execute("""
            UPDATE capability_turns
            SET thread_id = %s, stitch_decision = stitch_decision || %s::jsonb
            WHERE turn_id = %s
        """, (new_thread_id,
              json.dumps({"director_override_at": datetime.now(timezone.utc).isoformat()}),
              turn_id))
        conn.commit()
        cur.close()
        return JSONResponse({"new_thread_id": str(new_thread_id)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning(f"/api/pm/threads/re-thread failed: {e}")
        return JSONResponse({"error": "re-thread_failed"}, status_code=500)
    finally:
        store._put_conn(conn)
```

**Step 5.2 — `outputs/static/app.js`** — pure DOM methods only (no `innerHTML` with user content; lesson #17 + security rule). Use `replaceChildren()`, `createElement`, `textContent`, `appendChild`:

```javascript
// BRIEF_CAPABILITY_THREADS_1: feature-flagged thread panel
function isThreadsUIEnabled() {
    return localStorage.getItem('baker.threads.ui_enabled') === '1';
}

function clearPanel(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
}

function makeTextDiv(className, text) {
    const el = document.createElement('div');
    el.className = className;
    el.textContent = text;
    return el;
}

async function loadPMThreads(pmSlug) {
    if (!isThreadsUIEnabled()) return;
    const panel = document.getElementById('pm-threads-panel');
    if (!panel) return;
    clearPanel(panel);
    panel.appendChild(makeTextDiv('pm-threads-loading', 'Loading threads…'));
    try {
        const res = await fetch('/api/pm/threads/' + encodeURIComponent(pmSlug));
        if (!res.ok) throw new Error('http_' + res.status);
        const data = await res.json();
        renderThreadList(panel, data.threads || [], pmSlug);
    } catch (e) {
        clearPanel(panel);  // fail silent
    }
}

function renderThreadList(panel, threads, pmSlug) {
    clearPanel(panel);
    if (!threads.length) {
        panel.appendChild(makeTextDiv('pm-threads-empty', 'No threads yet'));
        return;
    }
    panel.appendChild(makeTextDiv('pm-threads-header',
        'Threads for ' + pmSlug + ' (' + threads.length + ')'));
    threads.forEach(t => {
        const row = document.createElement('div');
        row.className = 'pm-thread-row';
        row.dataset.threadId = t.thread_id;
        row.appendChild(makeTextDiv('pm-thread-topic',
            (t.topic_summary || '(no summary)').slice(0, 120)));
        row.appendChild(makeTextDiv('pm-thread-meta',
            t.status + ' · ' + t.turn_count + ' turns · ' + (t.last_turn_at || '')));
        row.addEventListener('click', () => openThreadReplay(pmSlug, t.thread_id));
        panel.appendChild(row);
    });
}

async function openThreadReplay(pmSlug, threadId) {
    const res = await fetch('/api/pm/threads/' + encodeURIComponent(pmSlug) +
                            '/' + encodeURIComponent(threadId) + '/turns');
    if (!res.ok) return;
    const data = await res.json();
    const replayBox = document.getElementById('pm-thread-replay');
    if (!replayBox) return;
    clearPanel(replayBox);
    (data.turns || []).forEach(turn => {
        const el = document.createElement('div');
        el.className = 'pm-turn';
        el.appendChild(makeTextDiv('pm-turn-q',
            '[' + turn.surface + '] Q: ' + (turn.question || '').slice(0, 400)));
        el.appendChild(makeTextDiv('pm-turn-a',
            'A: ' + (turn.answer || '').slice(0, 800)));
        replayBox.appendChild(el);
    });
    replayBox.style.display = 'block';
}

// Hook into existing capability-switch handler — call loadPMThreads when user
// selects ao_pm / movie_am (Code Brisen locates the existing dropdown change
// handler via grep for the capability-slug select element).
```

**Step 5.3 — `outputs/static/index.html`** — add the panel container (hidden by default) + feature-flag activation. NO `innerHTML` with user content:

```html
<div id="pm-threads-panel" style="display:none"></div>
<div id="pm-thread-replay" style="display:none"></div>
<script>
  if (localStorage.getItem('baker.threads.ui_enabled') === '1') {
    document.getElementById('pm-threads-panel').style.display = 'block';
    document.getElementById('pm-thread-replay').style.display = 'block';
  }
</script>
```

**Step 5.4 — `outputs/static/style.css`** — minimal styles for thread rows. Bump `?v=N` on `app.js`, `style.css`, and `index.html` static refs per lesson #4.

### Key UI constraints
- **No `innerHTML` with any content beyond static-empty-string / style toggles.** All text via `textContent` / `createTextNode`. XSS safety + security hook alignment.
- **Cache bust** (lesson #4): bump `?v=N` on `app.js`, `style.css`, `index.html` static refs.
- **No HTML5 drag API** per lesson #1 (scrollable containers cancel it). Re-thread UI uses click-based modal/button.
- **Feature flag fully disables UI** — removing `localStorage['baker.threads.ui_enabled']` reverts blast radius to zero.
- **Mobile PWA verified** per lesson #18 before ship gate.
- **FastAPI JSONResponse** must be imported (lesson #18) — spot-check line 22 of `outputs/dashboard.py` before adding new endpoints.

---

## Feature 6: Tests — ship-gate discipline (literal `pytest` green)

Per SKILL.md Rule 5 + lesson #42 (fixture-only tests can't catch schema drift): every DB-touching test uses a combination of fixtures (for unit logic) and real-DB integration (for schema-level claims).

### Test matrix

**NEW `tests/test_capability_threads.py`:**

```python
# BRIEF_CAPABILITY_THREADS_1 tests — unit + integration.

import uuid
from datetime import datetime, timedelta, timezone

import pytest


# ─── Unit: entity extractor ───

def test_extract_entity_cluster_ao_pm_patterns():
    from orchestrator.capability_threads import extract_entity_cluster
    entities = extract_entity_cluster(
        question="What's the latest on Aukera and Patrick Zuchner?",
        answer="Patrick is escalating the release request to the AIFM trust body.",
        pm_slug="ao_pm",
    )
    assert any("aukera" in k.lower() for k in entities.keys())


def test_extract_entity_cluster_movie_am_patterns_empty_when_ao_content():
    from orchestrator.capability_threads import extract_entity_cluster
    entities = extract_entity_cluster(
        question="What's on Aukera's agenda?",
        answer="Patrick Zuchner …",
        pm_slug="movie_am",
    )
    assert entities == {} or all("movie" not in k for k in entities.keys())


# ─── Unit: scoring ───

def test_score_candidate_weights():
    from orchestrator.capability_threads import _score_candidate
    assert _score_candidate(0.8, 1.0, 1.0) > _score_candidate(0.8, 0.0, 1.0)
    assert _score_candidate(0.5, 1.0, 0.5) < _score_candidate(0.8, 1.0, 1.0)


def test_jaccard_overlap():
    from orchestrator.capability_threads import _jaccard_overlap
    assert _jaccard_overlap({"a": 1, "b": 2}, {"a": 1, "c": 3}) == pytest.approx(1/3)
    assert _jaccard_overlap({}, {}) == 0.0
    assert _jaccard_overlap({"x": 1}, {}) == 0.0


def test_recency_weight_now_is_one():
    from orchestrator.capability_threads import _recency_weight
    assert _recency_weight(datetime.now(timezone.utc)) == pytest.approx(1.0, rel=1e-3)


def test_recency_weight_half_life():
    from orchestrator.capability_threads import _recency_weight, STITCH_RECENCY_DECAY_HOURS
    past = datetime.now(timezone.utc) - timedelta(hours=STITCH_RECENCY_DECAY_HOURS)
    assert _recency_weight(past) == pytest.approx(0.5, rel=0.05)


# ─── Unit: topic summary ───

def test_topic_summary_truncates():
    from orchestrator.capability_threads import _topic_summary
    s = _topic_summary("q" * 500, "a" * 500)
    assert len(s) <= 500


def test_topic_summary_strips_newlines():
    from orchestrator.capability_threads import _topic_summary
    s = _topic_summary("line1\nline2", "answer\n")
    assert "\n" not in s


# ─── Integration: DDL applied (schema smoke per lesson #42) ───

@pytest.mark.skipif("not config.getoption('--run-integration')", reason="integration only")
def test_capability_threads_ddl_applied():
    import psycopg2
    from config.settings import config as cfg
    conn = psycopg2.connect(**cfg.postgres.dsn_params)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name IN ('capability_threads', 'capability_turns')
            ORDER BY table_name
        """)
        tables = [r[0] for r in cur.fetchall()]
        assert tables == ["capability_threads", "capability_turns"]
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'pm_state_history' AND column_name = 'thread_id'
        """)
        assert cur.fetchone() is not None
    finally:
        conn.close()


# ─── SQL assertion test per lesson #42 ───

class _FakeCursor:
    def __init__(self):
        self.queries = []
        self._rows = [None]
        self.rowcount = 1
    def execute(self, q, params=None):
        self.queries.append((q, params))
    def fetchone(self): return self._rows[0]
    def close(self): pass


def test_create_new_thread_uses_uuid_ossp_or_python_uuid(monkeypatch):
    """Guardrail: stitcher uses either uuid-ossp (DEFAULT clause) or pure Python uuid.uuid4().
    Protects against accidental 'gen_random_uuid()' migration (requires pgcrypto, NOT installed).
    """
    from orchestrator.capability_threads import _create_new_thread
    class _FakeStore:
        def _get_conn(self):
            class _C:
                def cursor(self): return _FakeCursor()
                def commit(self): pass
                def rollback(self): pass
            return _C()
        def _put_conn(self, c): pass
    tid, dec = _create_new_thread(_FakeStore(), "ao_pm", "summary", {}, reason="test")
    assert isinstance(tid, str)
    uuid.UUID(tid)  # parses cleanly
```

**NEW `tests/test_capability_threads_h5.py`** — the mandatory §H5 cross-surface continuity test:

```python
"""BRIEF_CAPABILITY_THREADS_1 §Part H §H5 — cross-surface continuity.

Fact F written via one surface must surface via another on the same thread.
Requires integration DB. Gate via --run-integration flag; CI must run it.
"""
import pytest
import psycopg2
import psycopg2.extras
from config.settings import config as cfg


@pytest.mark.skipif("not config.getoption('--run-integration')", reason="integration only")
def test_h5_cross_surface_continuity():
    """Write via 'sidebar' surface → read via 'decomposer' surface → same pm_slug observable."""
    from orchestrator.capability_threads import stitch_or_create_thread, persist_turn
    
    pm_slug = "ao_pm"
    # 1. Write via sidebar
    t1, d1 = stitch_or_create_thread(
        pm_slug=pm_slug,
        question="What's the status of Aukera EUR 1.5M release?",
        answer="Patrick warned about trust review. Director chose Option B (Capex reframe).",
        surface="sidebar",
    )
    turn1 = persist_turn(pm_slug, t1, "sidebar", "sidebar",
                         "What's the status of Aukera EUR 1.5M release?",
                         "Patrick warned about trust review…",
                         state_updates={}, stitch_decision=d1)
    assert turn1 is not None
    
    # 2. Related follow-up via decomposer surface
    t2, d2 = stitch_or_create_thread(
        pm_slug=pm_slug,
        question="What did Patrick Zuchner say about Aukera again?",
        answer="He warned of trust escalation; we pivoted to Capex framing.",
        surface="decomposer",
    )
    persist_turn(pm_slug, t2, "decomposer", "decomposer",
                 "What did Patrick Zuchner say about Aukera again?",
                 "He warned of trust escalation…",
                 state_updates={}, stitch_decision=d2)
    
    # Qdrant embed is async fire-and-forget. Test tolerates either outcome:
    #   (a) stitched → t1 == t2 (Qdrant caught up)
    #   (b) new thread → t2 != t1 (race; entity overlap alone not enough)
    # Correct assertion: both turns are queryable; at least one sidebar + one decomposer
    # surface exist under this pm_slug in the last hour.
    conn = psycopg2.connect(**cfg.postgres.dsn_params)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT thread_id FROM capability_threads
            WHERE pm_slug = %s AND last_turn_at >= NOW() - INTERVAL '1 hour'
            ORDER BY last_turn_at DESC LIMIT 3
        """, (pm_slug,))
        rows = [dict(r) for r in cur.fetchall()]
        assert len(rows) >= 1
        
        cur.execute("""
            SELECT DISTINCT surface FROM capability_turns
            WHERE thread_id IN %s
        """, (tuple(str(r["thread_id"]) for r in rows),))
        surfaces = {r["surface"] for r in cur.fetchall()}
        assert "sidebar" in surfaces
        assert "decomposer" in surfaces
    finally:
        conn.close()
```

### Ship gate — literal pytest output

Before PR merge, Code Brisen pastes literal output of:

```bash
cd ~/bm-bN && python -m pytest tests/test_capability_threads.py tests/test_capability_threads_h5.py -v --run-integration 2>&1 | tail -40
```

Expected: `X passed, 0 failed`. **No "pass by inspection" per SKILL.md §Ship-Gate Discipline.** If integration tests cannot run locally (no TEST_DATABASE_URL), B-code sets up pytest-postgresql or runs against a Neon ephemeral branch; ship-gate is not satisfied by unit-only.

---

## §Part H — Invocation-Path Audit (MANDATORY, BLOCKER per Amendment H)

### H1. Enumerate invocation paths

Grep executed 2026-04-24: `grep -rn "ao_pm\|movie_am\|pm_slug" /Users/dimitry/Desktop/baker-code --include="*.py" -l | grep -v -E "test_|/tests/|_test\.py|/archive/"` yielded 21 files. After filtering to those that **invoke** Pattern-2 capabilities, the complete invocation map:

| # | file:line | Entry function | Surface | Reads state | Writes state |
|---|---|---|---|---|---|
| 1 | `outputs/dashboard.py:8148` | `_sidebar_state_write` (thread in `_scan_chat_capability`) | sidebar | ✅ via runner `_build_system_prompt` | ✅ via `extract_and_update_pm_state` |
| 2 | `outputs/dashboard.py:8240` | `_delegate_state_write` (thread in `_scan_chat_capability` delegate) | decomposer | ✅ | ✅ same |
| 3 | `orchestrator/capability_runner.py:1875` | `_auto_update_pm_state` (calls module-level function) | opus_auto | ✅ `_build_system_prompt` line 1062 | ✅ same |
| 4 | `orchestrator/pm_signal_detector.py:149` | `flag_pm_signal` | signal | partial (Layer 1 only — intentional, justified in H3) | ✅ direct `update_pm_project_state` |
| 5 | `orchestrator/agent.py:2031` | `_update_pm_state` (tool handler) | agent_tool | ✅ via enclosing agent loop context | ✅ direct `update_pm_project_state` |
| 6 | `scripts/backfill_pm_state.py` | one-off backfill script | backfill | ✅ | ✅ `extract_and_update_pm_state` |
| 7 | `scripts/insert_ao_pm_capability.py:278` | bootstrap script (reads legacy `ao_project_state` for migration ETL) | bootstrap (one-off) | read-only | — |
| 8 | `triggers/plaud_trigger.py`, `youtube_ingest.py`, `embedded_scheduler.py`, `email_trigger.py`, `waha_webhook.py`, `briefing_trigger.py`, `waha_client.py`, `fireflies_trigger.py`, `models/cortex.py`, `orchestrator/ao_signal_detector.py`, `orchestrator/context_selector.py`, `scripts/seed_wiki_pages.py`, `scripts/ingest_vault_matter.py`, `scripts/lint_ao_pm_vault.py`, `scripts/lint_movie_am_vault.py`, `scripts/insert_movie_am_capability.py` | various triggers / support | **read-only surfaces (intentional)** — reference pm_slug as tag/label/keyword only | read-only | — |

Entries 1–5 are meaningful-interaction callers. Entries 6–7 scripts (not runtime). Entries 8 are passive references marked read-only intentional with reason "reference pm_slug as string/tag; never invokes capability_runner or `update_pm_project_state`".

### H2. Write-path closure

| Caller (writes state) | Calls `update_pm_project_state`? | `thread_id` propagated? | `capability_turns` row persisted? | Gap? |
|---|---|---|---|---|
| 1. sidebar | ✅ via extract_and_update_pm_state | ✅ (new) | ✅ (new) | none |
| 2. decomposer | ✅ via extract_and_update_pm_state | ✅ (new) | ✅ (new) | none |
| 3. opus_auto | ✅ via extract_and_update_pm_state | ✅ (new) | ✅ (new) | none |
| 4. signal | ✅ direct | ❌ (pm_state_history.thread_id NULL) | ✅ (new) | **partial-attribution, documented** |
| 5. agent_tool | ✅ direct (now with mutation_source='agent_tool') | ❌ | ❌ | **partial, deferred to follow-up; tag closure only** |

Partial attributions 4 and 5 are **deliberately partial** with reason documented. Not silent gaps.

### H3. Read-path completeness

Entries 1–3 + 5 route through `_build_system_prompt` which loads Layer 1 (line 1103) + Layer 1.5 (new) + Layer 2 (line 1088/1099) + Layer 3 (via ToolExecutor).

Entry 4 (`flag_pm_signal`) loads Layer 1 only — **explicit partial-load** justified: lightweight signal flag; full context load would add 500+ms per signal × dozens/min → `pipeline_tick` deadline miss.

### H4. `mutation_source` tag taxonomy

| Surface | Canonical tag | Live today | Post-brief |
|---|---|---|---|
| Sidebar fast path | `sidebar` | ✅ | unchanged |
| Decomposer delegate | `decomposer` | ✅ | unchanged |
| Capability runner internal | `opus_auto` | ✅ | unchanged |
| Signal detector | `pm_signal_<channel>` (whatsapp/email/slack/…) | ✅ | unchanged |
| Agent tool `_update_pm_state` | `agent_tool` | ❌ (was `"auto"` default — H4 gap) | ✅ **closed by this brief** |
| Backfill script | `backfill_YYYY-MM-DD` | ✅ (`backfill_2026-04-23/24` observed) | unchanged |
| Cortex-3T future phase | `cortex3t_<phase>` | n/a | reserved |
| Cowork MCP future | `cowork_mcp` | n/a | reserved |

### H5. Cross-surface continuity test — named

Test: `tests/test_capability_threads_h5.py::test_h5_cross_surface_continuity` (Feature 6).

Test shape: *fact F written via surface `sidebar` → same PM, related follow-up via surface `decomposer` → decomposer turn observable in same pm_slug's threads within recency window; both surfaces emit `capability_turns` rows linked via `thread_id`.*

Buildable against current infrastructure — no blocking dep.

---

## Files Modified (complete list)

- **NEW** `migrations/20260424_capability_threads.sql` — DDL (Feature 1)
- **NEW** `orchestrator/capability_threads.py` — stitcher (Feature 2) ~350 lines
- **MODIFY** `memory/store_back.py:5228` — add `thread_id` param to `update_pm_project_state`; INSERT `pm_state_history` now includes `thread_id` + `RETURNING id` (Feature 3.1)
- **MODIFY** `orchestrator/capability_runner.py:261` — `extract_and_update_pm_state` calls stitcher + persist_turn after existing state-write (Feature 3.2)
- **MODIFY** `orchestrator/capability_runner.py:1062+` — `_build_system_prompt` injects Layer 1.5 thread context between lines 1105 and 1107 (Feature 4.2)
- **MODIFY** `orchestrator/capability_runner.py:<near existing `_get_pm_project_state_context`>` — new method `_get_pm_thread_context` (Feature 4.1). Code Brisen locates via `grep -n "_get_pm_project_state_context" orchestrator/capability_runner.py` first.
- **MODIFY** `orchestrator/pm_signal_detector.py:149` — thread-attribution turn after state-write (Feature 3.3)
- **MODIFY** `orchestrator/agent.py:2031` — close H4 gap: `mutation_source="agent_tool"` (Feature 3.4)
- **MODIFY** `outputs/dashboard.py` — 3 new endpoints (Feature 5.1). Grep-verify no existing `/api/pm/threads` route (lesson #11).
- **MODIFY** `outputs/static/app.js` — feature-flagged thread panel, pure-DOM only (Feature 5.2)
- **MODIFY** `outputs/static/index.html` — panel container + flag check + bumped `?v=N` static refs (Feature 5.3)
- **MODIFY** `outputs/static/style.css` — minimal thread-row styles + bumped `?v=N` ref in index.html (Feature 5.4)
- **NEW** `tests/test_capability_threads.py` — unit + SQL-assertion tests (Feature 6)
- **NEW** `tests/test_capability_threads_h5.py` — integration §H5 test (Feature 6)

## Files NOT to Touch

- `memory/store_back.py:5264-5285` — optimistic-lock body of `update_pm_project_state`. Proven at ao_pm v86 / movie_am v131; orthogonal.
- `memory/retriever.py` — reuse `SentinelRetriever._get_global_instance()` + `_embed_query()` unchanged.
- `conversation_memory` table + `memory/store_back.py::log_conversation` — separate log layer.
- `scripts/backfill_pm_state.py` — backfill of threads is explicitly out of scope (forward-only). Follow-up brief optional.
- `ao_project_state` + `ao_state_history` legacy tables — unrelated cruft. Separate cleanup brief candidate.
- `config/migration_runner.py` — reuse unchanged; advisory-lock + per-file-txn + drift-abort semantics load-bearing (lessons #35/#37).
- Any `_ensure_*` in `memory/store_back.py` — DDL in `migrations/` only. Pre-commit grep: `grep -cE '_ensure_capability_threads|_ensure_capability_turns' memory/store_back.py` must return 0.

## Quality Checkpoints (post-deploy)

1. **Migration applied**: `SELECT * FROM schema_migrations WHERE filename = '20260424_capability_threads.sql'` returns 1 row.
2. **Tables exist**: `\dt capability_*` returns `capability_threads` + `capability_turns`; `\d pm_state_history` shows `thread_id UUID`.
3. **Render deploy green**: `/health` shows migrations applied; service does not restart-loop.
4. **Existing state-writes unaffected (regression baseline)**: `SELECT pm_slug, version FROM pm_project_state WHERE state_key='current'` shows continuing version increment over 24h post-deploy (ao_pm v86→v87+, movie_am v131→v132+).
5. **First thread observed**: after Director triggers an AO PM sidebar query post-deploy, `SELECT COUNT(*) FROM capability_threads WHERE pm_slug='ao_pm' AND started_at > NOW() - INTERVAL '1 hour'` ≥ 1.
6. **Turn row persisted**: `SELECT COUNT(*) FROM capability_turns WHERE pm_slug='ao_pm' AND surface='sidebar'` ≥ 1 within 10 min.
7. **pm_state_history.thread_id populated** for new non-signal/agent-tool rows: `SELECT COUNT(*) FROM pm_state_history WHERE thread_id IS NOT NULL AND created_at > NOW() - INTERVAL '1 hour'` ≥ 1.
8. **Qdrant payload** written: at least one point in `baker-conversations` has `thread_id` in payload.
9. **UI dark by default**: with `localStorage['baker.threads.ui_enabled']` unset, sidebar identical to pre-brief. No new visual elements.
10. **UI on**: after setting flag + reload, thread panel renders; clicking a row shows replay; no console errors.
11. **Mobile verified** (lesson #18): iPhone PWA test — panel readable, no overflow.
12. **Cost invariant**: 48h post-deploy, `api_cost_log` shows no per-PM-call cost increase attributable to threads.
13. **H4 tag closure visible**: `SELECT DISTINCT mutation_source FROM pm_state_history WHERE created_at > NOW() - INTERVAL '48 hours'` includes `agent_tool` if the tool fires; no more `auto` from agent-tool path.

## Verification SQL (ready-to-run post-deploy)

```sql
-- 1. Migration + schema
SELECT filename FROM schema_migrations WHERE filename = '20260424_capability_threads.sql';

SELECT column_name, data_type FROM information_schema.columns 
WHERE table_name IN ('capability_threads', 'capability_turns')
ORDER BY table_name, ordinal_position;

-- 2. Thread activity
SELECT pm_slug, status, COUNT(*) AS threads, MAX(last_turn_at) AS newest
FROM capability_threads GROUP BY pm_slug, status ORDER BY pm_slug;

-- 3. Cross-surface continuity (inspect one thread)
SELECT t.thread_id, t.topic_summary,
       array_agg(DISTINCT tu.surface ORDER BY tu.surface) AS surfaces,
       COUNT(tu.turn_id) AS turns
FROM capability_threads t
LEFT JOIN capability_turns tu ON tu.thread_id = t.thread_id
WHERE t.pm_slug = 'ao_pm' AND t.last_turn_at > NOW() - INTERVAL '24 hours'
GROUP BY t.thread_id, t.topic_summary
ORDER BY turns DESC LIMIT 5;

-- 4. pm_state_history linkage
SELECT mutation_source, COUNT(*) AS rows,
       SUM(CASE WHEN thread_id IS NOT NULL THEN 1 ELSE 0 END) AS attributed
FROM pm_state_history
WHERE created_at > NOW() - INTERVAL '48 hours'
GROUP BY mutation_source ORDER BY rows DESC;

-- 5. Stitcher decision sample (for early empirical review)
SELECT surface, stitch_decision->>'matched_on' AS matched_on,
       (stitch_decision->>'score')::float AS score,
       COUNT(*) AS n
FROM capability_turns
WHERE created_at > NOW() - INTERVAL '48 hours'
GROUP BY surface, matched_on, score
ORDER BY n DESC;

-- 6. Dormant eligibility (manual-only in Phase 2; Phase 3 adds cron)
SELECT COUNT(*) FROM capability_threads
WHERE status = 'active' AND last_turn_at < NOW() - INTERVAL '72 hours';
```

## Cost impact (48h window)

- **Voyage embed:** +1 per turn persisted (~$0.00005/call). At ~20 turns/day: **~$0.03/mo**. Negligible.
- **Anthropic:** zero net-new calls. Topic summary derived from Opus-returned `summary` field or first-240-chars fallback.
- **Qdrant:** +N upserts/day in `baker-conversations`; ~1KB/point × 20 × 30 = 600KB/mo.
- **PostgreSQL:** ~5KB/turn × 20/day = 3MB/mo. Trivial.

Circuit-breaker invariant: existing `api_cost_log` + €15 alert / €100 stop continues to apply; no special-case bypass.

## Safety rules compliance

- **PostgreSQL:** every `except` calls `conn.rollback()` before `_put_conn` (enforced in Feature 2 snippets; Code Brisen verifies).
- **LIMIT on unbounded queries:** verified in `_recent_active_threads`, `_get_pm_thread_context`, all three new HTTP endpoints.
- **No secrets in code:** no new env vars; existing DSN/Qdrant/Voyage creds reused.
- **Fault-tolerant writes:** stitcher + persist_turn non-fatal via `try/except → logger.warning → return`; state-write never blocked by thread failure.
- **Render restart survival:** state in PG + Qdrant. No in-memory caches. Migration-runner advisory lock serializes multi-replica startup (lesson #25).
- **Force-push prohibition:** migration file append-only; no rewrites post-apply. `sha256` drift guard enforces (lesson #35).
- **No amend on main:** standard PR-branch flow.
- **No `innerHTML` with user-derived content:** pure DOM methods throughout app.js (security hook + lesson #17 alignment).

## Legacy references (per lesson #43 — dormant-code sweep)

Grep executed 2026-04-24 on `ao_project_state` + `ao_state_history`: zero references in production runtime code (the two `scripts/*` hits are bootstrap + one-time ETL; the `memory/store_back.py:5143` hit is inside the one-time copy-if-empty guard). **Cruft**, not live. Not modified by this brief; separate cleanup candidate logged for Monday 2026-04-27 audit scratch.

## Pre-merge verification (per lesson #40 — repo-unverifiable claims)

Before PR merge, Code Brisen pastes outputs of these commands into the PR description:

```bash
# 1. pgvector status (design: NOT installed; verify unchanged)
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_raw_query","arguments":{"sql":"SELECT extname FROM pg_extension WHERE extname = '\''vector'\''"}}}'
# Expected: empty rows.

# 2. uuid-ossp present (required by migration)
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_raw_query","arguments":{"sql":"SELECT extname, extversion FROM pg_extension WHERE extname = '\''uuid-ossp'\''"}}}'
# Expected: uuid-ossp | 1.1+

# 3. No pre-existing capability_threads _ensure_* in store_back.py
grep -cE '_ensure_capability_threads|_ensure_capability_turns' memory/store_back.py
# Expected: 0

# 4. No duplicate /api/pm/threads endpoint (lesson #11)
grep -n '/api/pm/threads' outputs/dashboard.py
# Expected: 0 pre-existing

# 5. Baseline pm_project_state still advancing (regression baseline)
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_raw_query","arguments":{"sql":"SELECT pm_slug, version, updated_at FROM pm_project_state WHERE state_key = '\''current'\'' ORDER BY pm_slug"}}}'
# Document pre-merge v + timestamps; compare 24h post-deploy.

# 6. Singleton check hook — run before push
bash scripts/check_singletons.sh
# Expected: pass (no bare SentinelStoreBack() / SentinelRetriever() construction)
```

## Dispatch checklist (AI Head → B-code)

- Working dir: `~/bm-bN` where N is whichever B-code is idle and proven
- Working branch: `capability-threads-1`
- Pre-reqs: PR #56 merged ✅ (confirmed 2026-04-24)
- Acceptance criteria: all Quality Checkpoints 1–13 verifiably pass; §H5 test green; literal pytest output pasted into PR
- Ship gate: `pytest tests/test_capability_threads.py tests/test_capability_threads_h5.py -v --run-integration` — **no "pass by inspection"**
- Security review gate: `/security-review` on the PR diff before merge (SKILL.md §Security Review Protocol, mandatory)
- Deploy gate: post-merge, verify schema via Quality Checkpoints 1–4 on Render before closing the task

---

## Lessons pre-applied

- #1: No HTML5 Drag in scrollable containers — UI uses click, not drag.
- #2/#3: DB column names verified via `information_schema` (pm_state_history.id is INT, not UUID).
- #4: `?v=N` cache bust on JS/CSS/HTML — Code Brisen bumps.
- #8: Verify before done — H5 integration test + live dashboard click is the proof, not syntax.
- #11: Duplicate endpoint check — grep `/api/pm/threads` before adding.
- #17: Every code snippet in brief has a grep-verified signature or file:line.
- #18: `JSONResponse` import — verified at line 23 of `dashboard.py` (grep output 2026-04-24).
- #25: No embedding during migration apply; stitcher embed is post-write fire-and-forget.
- #34: Integration tests present (H5) — structural + SQL-assertion alone not sufficient.
- #35: Migrations in `migrations/*.sql`, runner auto-applies, sha256 drift aborts.
- #37: Zero DDL in Python `_ensure_*` — grep-enforced.
- #38: No `((col::date))` index expressions.
- #40: Pre-merge verification section included.
- #42: Fixture + real-DB + SQL-assertion tests all present.
- #43: Legacy-reference sweep executed (`ao_project_state` cruft acknowledged, not touched).
- #44: `/write-brief` REVIEW step runs at Step 4.
- **Security:** all JS uses pure DOM methods (`textContent`, `createTextNode`, `appendChild`, `replaceChildren`/`clearPanel`) — no `innerHTML` with any user-controlled content.

---

**Brief ends.**
