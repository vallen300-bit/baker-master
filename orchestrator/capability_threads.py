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


def surface_from_mutation_source(src: str) -> str:
    """Map a ``mutation_source`` tag to the canonical ``capability_turns.surface``
    value (CHECK-constrained — see migrations/20260424_capability_threads.sql)."""
    if src == "sidebar":
        return "sidebar"
    if src == "decomposer":
        return "decomposer"
    if src == "opus_auto":
        return "opus_auto"
    if src and src.startswith("pm_signal_"):
        return "signal"
    if src == "agent_tool":
        return "agent_tool"
    if src and src.startswith("backfill_"):
        return "backfill"
    return "other"


def extract_entity_cluster(question: str, answer: str, pm_slug: str) -> dict:
    """Lightweight keyword extraction from PM_REGISTRY patterns.

    NO LLM call — keeps stitch latency sub-50ms. Returns {pattern: match_count}.
    Import is lazy to avoid circular dependency (capability_runner imports this module).
    """
    from orchestrator.capability_runner import PM_REGISTRY
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
        cosine = _qdrant_cosine_for_thread(retriever, query_vec, pm_slug, str(cand["thread_id"]))
        entity_overlap = _jaccard_overlap(new_entities, cand.get("entity_cluster") or {})
        recency = _recency_weight(cand["last_turn_at"])
        score = _score_candidate(cosine, entity_overlap, recency)
        scored.append({
            "thread_id": str(cand["thread_id"]),
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
        result = retriever.qdrant.query_points(
            collection_name="baker-conversations",
            query=query_vec,
            limit=3,
            query_filter=qfilter,
            score_threshold=0.0,
        )
        points = getattr(result, "points", None) or []
        if not points:
            return 0.0
        return float(points[0].score)
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
            text = f"Question: {question}\n\nAnswer: {(answer or '')[:4000]}"
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
