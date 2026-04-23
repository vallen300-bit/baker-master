"""
Baker Cortex v2 — Event Bus + Semantic Dedup Gate
CORTEX-PHASE-2A: publish_event() + audit + decisions→insights pipeline.
CORTEX-PHASE-2B: Qdrant semantic dedup gate + shadow mode.
CORTEX-PHASE-3: Wiki lint + intent feed dashboard.
Behind tool_router_enabled + auto_merge_enabled feature flags.
"""
import hashlib
import json
import logging
from typing import Optional

logger = logging.getLogger("baker.cortex")


def _get_store():
    """Get SentinelStoreBack singleton."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _get_conn():
    store = _get_store()
    return store._get_conn()


def _put_conn(conn):
    store = _get_store()
    store._put_conn(conn)


# ─── Qdrant Semantic Dedup Gate (Phase 2B) ───

def _get_qdrant():
    """Get Qdrant client singleton."""
    from qdrant_client import QdrantClient
    from config.settings import config
    if not hasattr(_get_qdrant, '_client'):
        if not config.qdrant.url:
            _get_qdrant._client = None
        else:
            _get_qdrant._client = QdrantClient(
                url=config.qdrant.url,
                api_key=config.qdrant.api_key,
            )
    return _get_qdrant._client


def _embed_text(text: str) -> list:
    """Embed text using Voyage AI. Returns 1024-dim vector."""
    import voyageai
    from config.settings import config
    if not config.voyage.api_key:
        return []
    client = voyageai.Client(api_key=config.voyage.api_key)
    result = client.embed(
        texts=[text[:2000]],  # Cap at 2000 chars to control cost
        model=config.voyage.model,  # "voyage-3"
        input_type="document",
    )
    return result.embeddings[0]


def check_dedup(
    description: str,
    category: str,
    due_date: str = None,
    amount: float = None,
) -> tuple:
    """
    Unconditional semantic check before any shared write.
    Returns: ('new', None) | ('auto_merge', canonical_id) | ('review', canonical_id)

    Thresholds:
    - >= 0.92: auto-merge (same obligation, different words)
    - 0.85-0.92: human review queue
    - < 0.85: definitely new

    Field override: if dates or amounts differ, NEVER auto-merge.
    """
    qdrant = _get_qdrant()
    if not qdrant:
        return ('new', None)

    try:
        embedding = _embed_text(description)
        if not embedding:
            return ('new', None)

        from qdrant_client.models import Filter, FieldCondition, MatchValue

        results = qdrant.search(
            collection_name="cortex_obligations",
            query_vector=embedding,
            query_filter=Filter(
                must=[FieldCondition(key="category", match=MatchValue(value=category))]
            ),
            score_threshold=0.85,  # Floor — below this, definitely new
            limit=3,
        )

        if not results:
            return ('new', None)

        best = results[0]
        score = best.score
        existing = best.payload

        # NEVER auto-merge if structured fields differ
        if due_date and existing.get('due_date') and due_date != existing['due_date']:
            return ('new', None)  # Different dates = different obligation
        if amount and existing.get('amount') and abs(amount - existing['amount']) > 0.01:
            return ('new', None)  # Different amounts = different obligation

        if score >= 0.92:
            return ('auto_merge', existing.get('canonical_id'))
        elif score >= 0.85:
            return ('review', existing.get('canonical_id'))
        else:
            return ('new', None)

    except Exception as e:
        logger.warning("check_dedup failed (non-fatal, treating as new): %s", e)
        return ('new', None)


def upsert_obligation_vector(
    canonical_id: int,
    description: str,
    category: str,
    due_date: str = None,
    source_agent: str = None,
):
    """Write/update the Qdrant vector for an obligation."""
    qdrant = _get_qdrant()
    if not qdrant:
        return

    try:
        embedding = _embed_text(description)
        if not embedding:
            return

        from qdrant_client.models import PointStruct

        point_id = f"{category}_{canonical_id}"
        numeric_id = int(hashlib.sha256(point_id.encode()).hexdigest()[:16], 16)
        qdrant.upsert(
            collection_name="cortex_obligations",
            points=[PointStruct(
                id=numeric_id,  # Deterministic hash — survives Render restarts
                vector=embedding,
                payload={
                    "canonical_id": canonical_id,
                    "category": category,
                    "description": description[:500],
                    "due_date": due_date,
                    "source_agent": source_agent,
                    "point_key": point_id,
                },
            )],
        )
        logger.info("cortex: upserted vector for %s", point_id)
    except Exception as e:
        logger.warning("upsert_obligation_vector failed (non-fatal): %s", e)


# ─── Event Bus Core ───

def publish_event(
    event_type: str,
    category: str,
    source_agent: str,
    source_type: str,
    payload: dict,
    source_ref: str = None,
    canonical_id: int = None,
) -> Optional[int]:
    """
    Publish an event to the Cortex event bus.
    This is the SINGLE entry point for all coordinated writes.

    PHASE-2B: Pre-write semantic dedup gate for deadlines/decisions.
    Shadow mode (auto_merge_enabled=false): logs dedup decisions, doesn't block.
    Live mode (auto_merge_enabled=true): score >= 0.92 → skip write.

    Returns: event ID or None on failure.
    """
    # CORTEX-PHASE-2B: Pre-write semantic dedup gate
    dedup_category = category if category in ("deadline", "decision") else None
    dedup_result = ('new', None)

    if dedup_category:
        try:
            dedup_result = check_dedup(
                description=payload.get("description", payload.get("decision", "")),
                category=dedup_category,
                due_date=payload.get("due_date"),
                amount=payload.get("amount"),
            )
        except Exception as e:
            logger.warning("Dedup gate failed (non-fatal): %s", e)
            dedup_result = ('new', None)

        # Check auto_merge_enabled flag
        store = _get_store()
        auto_merge = store.get_cortex_config('auto_merge_enabled', False)

        if dedup_result[0] == 'auto_merge':
            if auto_merge:
                # LIVE MODE: Actually merge — skip the write, return existing
                logger.info(
                    "cortex DEDUP: auto-merge %s into canonical #%s (score >= 0.92)",
                    category, dedup_result[1]
                )
                _log_dedup_event(event_type, category, source_agent, payload,
                                 dedup_result, "merged")
                return dedup_result[1]  # Return existing canonical_id
            else:
                # SHADOW MODE: Log but don't block
                logger.info(
                    "cortex SHADOW: would_merge %s into canonical #%s (auto_merge OFF)",
                    category, dedup_result[1]
                )
                _log_dedup_event(event_type, category, source_agent, payload,
                                 dedup_result, "would_merge")
                # Fall through to normal insert

        elif dedup_result[0] == 'review':
            logger.info(
                "cortex DEDUP: review_needed %s — similar to canonical #%s (0.85-0.92)",
                category, dedup_result[1]
            )
            _log_dedup_event(event_type, category, source_agent, payload,
                             dedup_result, "review_needed")
            # Fall through to normal insert (Director reviews later)

    # Insert the event — atomic with baker_actions ledger row (CHANDA inv #2).
    from invariant_checks.ledger_atomic import atomic_director_action

    conn = _get_conn()
    if not conn:
        logger.error("cortex.publish_event: no DB connection")
        return None

    event_id: Optional[int] = None
    try:
        with atomic_director_action(
            conn,
            action_type=f"cortex:{event_type}:{category}",
            payload={
                "source_agent": source_agent,
                "summary": str(payload.get("description", payload.get("decision", "")))[:200],
            },
            trigger_source=source_agent,
        ) as cur:
            cur.execute("""
                INSERT INTO cortex_events
                    (event_type, category, source_agent, source_type,
                     source_ref, payload, canonical_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                event_type, category, source_agent, source_type,
                source_ref, json.dumps(payload), canonical_id,
            ))
            event_id = cur.fetchone()[0]

        logger.info(
            "cortex event #%d: %s/%s by %s (canonical=%s)",
            event_id, event_type, category, source_agent, canonical_id
        )
    except Exception as e:
        logger.error("cortex.publish_event atomic block failed: %s", e)
        _put_conn(conn)
        return None

    # Post-write side-effects (non-blocking — cortex_events + baker_actions
    # already atomically committed above; these are best-effort enrichments).
    try:
        if dedup_category and canonical_id:
            try:
                upsert_obligation_vector(
                    canonical_id=canonical_id,
                    description=payload.get("description", payload.get("decision", "")),
                    category=dedup_category,
                    due_date=payload.get("due_date"),
                    source_agent=source_agent,
                )
            except Exception as e:
                logger.warning("Post-write vector upsert failed (non-fatal): %s", e)

        try:
            _auto_queue_insights(category, source_agent, payload, canonical_id)
        except Exception as e:
            logger.warning("cortex insights queue failed (non-fatal): %s", e)

        return event_id
    finally:
        _put_conn(conn)


def _log_dedup_event(
    event_type: str, category: str, source_agent: str,
    payload: dict, dedup_result: tuple, dedup_action: str,
):
    """Log dedup decisions to cortex_events for shadow mode analysis."""
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO cortex_events
                (event_type, category, source_agent, source_type,
                 payload, refers_to)
            VALUES (%s, %s, %s, 'dedup_gate', %s, %s)
        """, (
            dedup_action,  # "would_merge", "merged", "review_needed"
            category,
            source_agent,
            json.dumps({
                **payload,
                "dedup_score": ">=0.92" if dedup_result[0] == "auto_merge" else "0.85-0.92",
                "matched_canonical": dedup_result[1],
            }),
            dedup_result[1],  # refers_to = canonical_id of the matched obligation
        ))
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("_log_dedup_event failed: %s", e)
    finally:
        _put_conn(conn)


# ─── Decisions → PM Pending Insights Pipeline ───

# Map: keyword patterns → PM slugs that should receive the insight
PM_MATTER_KEYWORDS = {
    "ao_pm": [
        "oskolkov", "andrey", "aelio", "aukera", "capital call",
        "hagenauer", "lilienmatt", "balgerstrasse", "rg7", "riemergasse",
        "participation agreement", "rosfinmonitoring",
    ],
    "movie_am": [
        "movie", "mandarin oriental", "mohg", "mario habicher",
        "francesco", "robin", "rolf", "operator", "occupancy",
        "revpar", "ff&e", "warranty",
    ],
}

# Map: keyword → target view file for the insight
INSIGHT_TARGET_FILES = {
    "capital call": "agenda.md",
    "hagenauer": "agenda.md",
    "lilienmatt": "agenda.md",
    "balgerstrasse": "agenda.md",
    "aukera": "agenda.md",
    "rosfinmonitoring": "psychology.md",
    "co-ownership": "psychology.md",
    "udmurtia": "psychology.md",
    "oskolkov": "agenda.md",
    "movie": "agenda.md",
    "mandarin": "agenda.md",
    "occupancy": "kpi_framework.md",
    "revpar": "kpi_framework.md",
    "warranty": "owner_obligations.md",
    "operator": "operator_dynamics.md",
}


def _auto_queue_insights(
    category: str, source_agent: str, payload: dict,
    canonical_id: int = None,
):
    """
    When a decision is stored, check if it matches any PM's matters.
    If yes, auto-queue as pm_pending_insight targeting the right view file.
    """
    if category != "decision":
        return  # Only decisions trigger insight queueing for now

    decision_text = payload.get("decision", "")
    if not decision_text:
        return

    decision_lower = decision_text.lower()

    for pm_slug, keywords in PM_MATTER_KEYWORDS.items():
        matched_keywords = [kw for kw in keywords if kw in decision_lower]
        if not matched_keywords:
            continue

        # Find best target file
        target_file = "agenda.md"  # default
        for kw, tf in INSIGHT_TARGET_FILES.items():
            if kw in decision_lower:
                target_file = tf
                break

        # Queue the insight
        conn = _get_conn()
        if not conn:
            continue
        try:
            cur = conn.cursor()
            # Check for duplicate (same pm_slug + same text in last 24h)
            cur.execute("""
                SELECT id FROM pm_pending_insights
                WHERE pm_slug = %s AND status = 'pending'
                  AND insight = %s
                  AND created_at > NOW() - INTERVAL '24 hours'
                LIMIT 1
            """, (pm_slug, decision_text))
            if cur.fetchone():
                cur.close()
                _put_conn(conn)
                continue  # Already queued

            cur.execute("""
                INSERT INTO pm_pending_insights
                    (pm_slug, insight, target_file, target_section,
                     source_question, confidence, status)
                VALUES (%s, %s, %s, %s, %s, 'medium', 'pending')
            """, (
                pm_slug,
                decision_text,
                target_file,
                f"Auto-queued from decision (matched: {', '.join(matched_keywords[:3])})",
                f"cortex:{source_agent}:decision#{canonical_id}",
            ))
            conn.commit()
            cur.close()
            logger.info(
                "cortex: auto-queued insight for %s from decision (matched: %s, target: %s)",
                pm_slug, matched_keywords[:3], target_file,
            )
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("_auto_queue_insights failed for %s: %s", pm_slug, e)
        finally:
            _put_conn(conn)


# ─── Convenience Wrappers (Phase 2B-ii) ───

def cortex_create_deadline(
    description: str,
    due_date,  # datetime or str
    source_type: str,
    source_agent: str,
    confidence: str = "medium",
    priority: str = "normal",
    source_id: str = None,
    source_snippet: str = None,
) -> Optional[int]:
    """
    Create a deadline through the Cortex event bus.
    1. INSERT via legacy insert_deadline()
    2. Set source_agent on the row
    3. Publish event (dedup + audit + vector upsert)

    Returns deadline ID or None. publish_event failure is non-fatal.
    """
    from models.deadlines import insert_deadline
    from datetime import datetime, timezone

    # Normalize due_date to datetime
    if isinstance(due_date, str):
        try:
            due_date = datetime.fromisoformat(due_date)
            if due_date.tzinfo is None:
                due_date = due_date.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            logger.warning("cortex_create_deadline: invalid due_date %s", due_date)
            return None

    # 1. Legacy INSERT
    dl_id = insert_deadline(
        description=description,
        due_date=due_date,
        source_type=source_type,
        confidence=confidence,
        priority=priority,
        source_id=source_id,
        source_snippet=source_snippet,
    )
    if not dl_id:
        return None

    # 2. Set source_agent
    try:
        conn = _get_conn()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE deadlines SET source_agent = %s WHERE id = %s",
                (source_agent, dl_id),
            )
            conn.commit()
            cur.close()
            _put_conn(conn)
    except Exception as e:
        logger.warning("cortex_create_deadline: source_agent update failed: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        _put_conn(conn)

    # 3. Publish event (non-fatal)
    due_str = due_date.strftime("%Y-%m-%d") if hasattr(due_date, 'strftime') else str(due_date)
    try:
        publish_event(
            event_type="accepted",
            category="deadline",
            source_agent=source_agent,
            source_type=source_type,
            payload={
                "description": description,
                "due_date": due_str,
                "priority": priority,
                "confidence": confidence,
            },
            source_ref=source_id,
            canonical_id=dl_id,
        )
    except Exception as e:
        logger.warning("cortex_create_deadline: publish_event failed (non-fatal): %s", e)

    return dl_id


def cortex_store_decision(
    decision: str,
    source_agent: str,
    reasoning: str = "",
    confidence: str = "high",
    trigger_type: str = "pipeline",
    project: str = "",
) -> Optional[int]:
    """
    Store a decision through the Cortex event bus.
    1. INSERT via legacy log_decision()
    2. Set source_agent on the row
    3. Publish event (dedup + audit + insights pipeline)

    Returns decision ID or None. publish_event failure is non-fatal.
    """
    # 1. Legacy INSERT
    store = _get_store()
    dec_id = store.log_decision(
        decision=decision,
        reasoning=reasoning,
        confidence=confidence,
        trigger_type=trigger_type,
    )
    if not dec_id:
        return None

    # 2. Set source_agent
    try:
        conn = _get_conn()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE decisions SET source_agent = %s WHERE id = %s",
                (source_agent, dec_id),
            )
            conn.commit()
            cur.close()
            _put_conn(conn)
    except Exception as e:
        logger.warning("cortex_store_decision: source_agent update failed: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        _put_conn(conn)

    # 3. Publish event (non-fatal)
    try:
        publish_event(
            event_type="accepted",
            category="decision",
            source_agent=source_agent,
            source_type=trigger_type,
            payload={
                "decision": decision,
                "reasoning": reasoning,
                "confidence": confidence,
                "project": project,
            },
            canonical_id=dec_id,
        )
    except Exception as e:
        logger.warning("cortex_store_decision: publish_event failed (non-fatal): %s", e)

    return dec_id


# ─── Wiki Lint (CORTEX-PHASE-3) ───

def run_wiki_lint() -> list[dict]:
    """
    Periodic wiki health check. Detects stale pages, orphan VIPs,
    generation mismatches, broken backlinks.
    Returns list of finding dicts.
    """
    findings = []
    conn = _get_conn()
    if not conn:
        logger.error("run_wiki_lint: no DB connection")
        return findings
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # ── 1. STALE PAGES — agent_knowledge not updated in 14+ days ──
        cur.execute("""
            SELECT slug, title, updated_at
            FROM wiki_pages
            WHERE page_type = 'agent_knowledge'
              AND updated_at < NOW() - INTERVAL '14 days'
            LIMIT 50
        """)
        for row in cur.fetchall():
            findings.append({
                "finding_type": "stale_page",
                "severity": "warning",
                "slug_or_ref": row["slug"],
                "description": f"Page '{row['title']}' last updated {row['updated_at'].strftime('%Y-%m-%d')} (>14 days ago)",
            })

        # ── 2. ORPHAN VIPs — contacts not mentioned in any wiki page ──
        cur.execute("SELECT string_agg(content, ' ') AS all_content FROM wiki_pages LIMIT 1")
        all_content_row = cur.fetchone()
        all_content = (all_content_row["all_content"] or "").lower() if all_content_row else ""

        cur.execute("SELECT name FROM vip_contacts WHERE name IS NOT NULL LIMIT 100")
        for row in cur.fetchall():
            name_lower = row["name"].lower()
            parts = name_lower.split()
            last_name = parts[-1] if parts else name_lower
            if len(last_name) > 2 and last_name not in all_content:
                findings.append({
                    "finding_type": "orphan_vip",
                    "severity": "info",
                    "slug_or_ref": row["name"],
                    "description": f"VIP '{row['name']}' not mentioned in any wiki page",
                })

        # ── 3. GENERATION BEHIND — cortex events newer than compiled pages ──
        cur.execute("""
            SELECT wp.slug, wp.updated_at,
                   (SELECT MAX(ce.created_at) FROM cortex_events ce
                    WHERE ce.category = CASE
                        WHEN wp.slug LIKE 'deadlines%%' THEN 'deadline'
                        WHEN wp.slug LIKE 'decisions%%' THEN 'decision'
                        ELSE 'unknown'
                    END) AS latest_event_at
            FROM wiki_pages wp
            WHERE wp.page_type = 'compiled_state'
            LIMIT 20
        """)
        for row in cur.fetchall():
            if row["latest_event_at"] and row["latest_event_at"] > row["updated_at"]:
                findings.append({
                    "finding_type": "generation_behind",
                    "severity": "warning",
                    "slug_or_ref": row["slug"],
                    "description": f"Compiled page '{row['slug']}' is behind latest Cortex event ({row['latest_event_at'].strftime('%Y-%m-%d %H:%M')})",
                })

        # ── 4. BROKEN BACKLINKS — referenced slugs that don't exist ──
        cur.execute("SELECT slug FROM wiki_pages LIMIT 500")
        existing_slugs = {r["slug"] for r in cur.fetchall()}

        cur.execute("SELECT slug, backlinks FROM wiki_pages WHERE backlinks IS NOT NULL AND array_length(backlinks, 1) > 0 LIMIT 100")
        for row in cur.fetchall():
            for link in (row["backlinks"] or []):
                if link not in existing_slugs:
                    findings.append({
                        "finding_type": "broken_backlink",
                        "severity": "warning",
                        "slug_or_ref": row["slug"],
                        "description": f"Page '{row['slug']}' has backlink to non-existent '{link}'",
                    })

        # ── 5. MISSING INDEX — PM agents without an index page ──
        cur.execute("""
            SELECT DISTINCT agent_owner FROM wiki_pages
            WHERE agent_owner IS NOT NULL
            LIMIT 20
        """)
        for row in cur.fetchall():
            agent = row["agent_owner"]
            cur.execute("SELECT 1 FROM wiki_pages WHERE slug = %s LIMIT 1", (f"{agent}/index",))
            if not cur.fetchone():
                findings.append({
                    "finding_type": "missing_index",
                    "severity": "warning",
                    "slug_or_ref": agent,
                    "description": f"Agent '{agent}' has wiki pages but no index page at '{agent}/index'",
                })

        conn.commit()

        # ── Store findings (clear old open, insert new) ──
        cur.execute("DELETE FROM cortex_lint_results WHERE status = 'open'")
        for f in findings:
            cur.execute("""
                INSERT INTO cortex_lint_results (finding_type, severity, slug_or_ref, description)
                VALUES (%s, %s, %s, %s)
            """, (f["finding_type"], f["severity"], f["slug_or_ref"], f["description"]))
        conn.commit()
        cur.close()

        logger.info("wiki_lint: %d findings stored", len(findings))
        return findings

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("run_wiki_lint failed: %s", e)
        return findings
    finally:
        _put_conn(conn)
