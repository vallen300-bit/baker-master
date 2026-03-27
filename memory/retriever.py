"""
Sentinel AI — Memory Retriever (Step 2: Retrieval)
Searches Qdrant vector DB and PostgreSQL for relevant context.
This is the "R" in RAG.
"""
import json
import logging
import time
from typing import Optional
from dataclasses import dataclass

import voyageai
from qdrant_client import QdrantClient
from qdrant_client.models import ScoredPoint, Filter, FieldCondition, MatchValue

from config.settings import config

logger = logging.getLogger("sentinel.retriever")


@dataclass
class RetrievedContext:
    """A single piece of retrieved context with metadata."""
    content: str
    source: str          # "whatsapp", "email", "meeting", "document", "postgres"
    score: float         # relevance score (0-1)
    metadata: dict       # contact, date, collection, etc.
    token_estimate: int  # rough token count for budget management

    def __repr__(self):
        return f"<Context source={self.source} score={self.score:.3f} tokens≈{self.token_estimate}>"


class SentinelRetriever:
    """
    Retrieves relevant context from all memory sources.
    Implements semantic search (Qdrant) + structured queries (PostgreSQL).
    """

    def __init__(self):
        # Qdrant client (vector search)
        self.qdrant = QdrantClient(
            url=config.qdrant.url,
            api_key=config.qdrant.api_key,
        )
        # Voyage AI embedder
        self.voyage = voyageai.Client(api_key=config.voyage.api_key)
        # PostgreSQL connection (lazy init)
        self._pg_pool = None

    def _embed_query(self, query: str) -> list[float]:
        """Embed a query string using Voyage AI."""
        result = self.voyage.embed(
            texts=[query],
            model=config.voyage.model,
            input_type="query",
        )
        return result.embeddings[0]

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~4 chars per token for English."""
        return len(text) // 4

    # ----------------------------------------------------------------
    # Qdrant Vector Search (semantic)
    # ----------------------------------------------------------------

    def search_collection(
        self,
        query_vector: list[float],
        collection: str,
        limit: int = 20,
        score_threshold: float = 0.3,
        project: Optional[str] = None,
        role: Optional[str] = None,
    ) -> list[RetrievedContext]:
        """Search a single Qdrant collection with a pre-computed embedding vector."""
        conditions = []
        if project:
            conditions.append(FieldCondition(key="project", match=MatchValue(value=project)))
        if role:
            conditions.append(FieldCondition(key="role", match=MatchValue(value=role)))
        query_filter = Filter(must=conditions) if conditions else None

        results = self.qdrant.query_points(
            collection_name=collection,
            query=query_vector,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=query_filter,
        )

        contexts = []
        for point in results.points:
            payload = point.payload or {}
            content = payload.get("text", payload.get("content", ""))

            # Dynamic source from collection name
            source = collection.replace("baker-", "").replace("sentinel-", "")

            # Label: same logic as baker_rag.py
            label = (
                payload.get("name")
                or payload.get("deal_name")
                or payload.get("project")
                or payload.get("meeting_title")
                or payload.get("chat_name")
                or payload.get("subject")
                or payload.get("title")
                or "unknown"
            )

            metadata = {k: v for k, v in payload.items() if k not in ("text", "content")}
            metadata["collection"] = collection
            metadata["label"] = label
            metadata["point_id"] = str(point.id)

            contexts.append(RetrievedContext(
                content=content,
                source=source,
                score=point.score,
                metadata=metadata,
                token_estimate=self._estimate_tokens(content),
            ))
        return contexts

    def search_all_collections(
        self,
        query: str,
        limit_per_collection: int = 10,
        score_threshold: float = 0.3,
        project: Optional[str] = None,
        role: Optional[str] = None,
    ) -> list[RetrievedContext]:
        """Search ALL Qdrant collections and merge results by relevance."""
        # Embed once — avoids N Voyage API calls (one per collection)
        query_vector = self._embed_query(query)
        logger.info("Query embedded (1 Voyage call for all collections)")

        all_contexts = []
        for i, coll in enumerate(config.qdrant.collections):
            try:
                if i > 0:
                    time.sleep(0.05)  # minimal safety net (Qdrant Cloud needs no rate limit)
                results = self.search_collection(
                    query_vector=query_vector,
                    collection=coll,
                    limit=limit_per_collection,
                    score_threshold=score_threshold,
                    project=project,
                    role=role,
                )
                all_contexts.extend(results)
                logger.info(f"Retrieved {len(results)} results from {coll}")
            except Exception as e:
                logger.warning(f"Failed to search {coll}: {e}")
                continue

        # THREE-TIER-MEMORY: Add Tier 2 + Tier 3 results from PostgreSQL
        # Only if Qdrant results are sparse (< 8 results above threshold)
        strong_results = [c for c in all_contexts if c.score >= 0.5]
        if len(strong_results) < 8:
            tier_contexts = self._search_memory_tiers(query, project)
            all_contexts.extend(tier_contexts)
            if tier_contexts:
                logger.info(f"THREE-TIER-MEMORY: added {len(tier_contexts)} results from Tier 2/3")

        # RETRIEVAL-RERANK-1: Boost scores by term match, name match, recency
        all_contexts = self._rerank_results(all_contexts, query)

        # Sort by relevance score (highest first)
        all_contexts.sort(key=lambda c: c.score, reverse=True)

        # ARCH-3: Enrich top results with full source text from PostgreSQL
        all_contexts = self._enrich_with_full_text(all_contexts)

        return all_contexts

    def _rerank_results(self, contexts: list["RetrievedContext"],
                        query: str) -> list["RetrievedContext"]:
        """RETRIEVAL-RERANK-1: Boost Qdrant scores with lexical + recency signals.

        Pure Python — zero API cost. Applied BEFORE enrichment so the best
        results get enriched with full text.

        Boosts (additive, capped so we never exceed 1.0):
          +0.15  exact query term match (>=2 significant terms found in content)
          +0.20  proper name match (capitalized multi-word term from query in content)
          +0.10  recent (<7 days) | +0.05 semi-recent (<30 days)
        """
        import re
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)

        # Extract significant query terms (3+ chars, skip stop words)
        _STOP = {"the", "and", "for", "are", "but", "not", "you", "all",
                 "can", "had", "her", "was", "one", "our", "out", "has",
                 "his", "how", "its", "may", "new", "now", "old", "see",
                 "way", "who", "did", "get", "let", "say", "she", "too",
                 "use", "what", "where", "when", "which", "why", "with",
                 "about", "could", "from", "have", "been", "some", "than",
                 "that", "them", "then", "they", "this", "will", "would",
                 "there", "their", "these", "those", "should", "baker",
                 "tell", "show", "give", "know", "does", "status", "update"}
        q_lower = query.lower()
        terms = [w for w in re.findall(r'\b\w{3,}\b', q_lower) if w not in _STOP]

        # Extract proper names: capitalized words from original query (2+ chars)
        proper_names = re.findall(r'\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*\b', query)
        proper_lower = [n.lower() for n in proper_names]

        for ctx in contexts:
            boost = 0.0
            content_lower = ctx.content.lower()

            # 1. Exact query term match: >=2 significant terms found
            if terms:
                matched = sum(1 for t in terms if t in content_lower)
                if matched >= 2:
                    boost += 0.15

            # 2. Proper name match: any capitalized name from query in content
            if proper_lower:
                if any(name in content_lower for name in proper_lower):
                    boost += 0.20

            # 3. B2: Smooth recency decay (Session 26)
            # Exponential decay: +0.15 today → +0.10 at 7d → +0.05 at 30d → +0.01 at 90d → 0 at 180d+
            import math
            date_str = (ctx.metadata.get("date")
                        or ctx.metadata.get("timestamp")
                        or ctx.metadata.get("created_at")
                        or ctx.metadata.get("ingested_at")
                        or "")
            if date_str:
                try:
                    ds = str(date_str).strip()
                    if "T" in ds or " " in ds:
                        ds = ds[:10]
                    doc_date = datetime.strptime(ds, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    age_days = max((now - doc_date).days, 0)
                    if age_days < 180:
                        # Decay: 0.15 * e^(-age_days/30)
                        recency_boost = 0.15 * math.exp(-age_days / 30.0)
                        boost += recency_boost
                except (ValueError, TypeError):
                    pass

            if boost > 0:
                ctx.score = min(ctx.score + boost, 1.0)

        return contexts

    def _search_memory_tiers(self, query: str, project: Optional[str] = None) -> list["RetrievedContext"]:
        """THREE-TIER-MEMORY: Search Tier 2 summaries + Tier 3 institutional from PostgreSQL.
        Results get reduced scores (0.7x for Tier 2, 0.5x for Tier 3) so active data is preferred."""
        results = []
        try:
            from memory.store_back import SentinelStoreBack
            import psycopg2.extras
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return results
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

                # Build search terms for text matching
                import re
                _stop = {"the", "and", "for", "are", "but", "not", "you", "all", "can",
                         "has", "how", "its", "what", "where", "when", "which", "with",
                         "about", "baker", "tell", "show", "give", "know", "status"}
                terms = [w for w in re.findall(r'\b\w{3,}\b', query.lower()) if w not in _stop]
                if not terms:
                    cur.close()
                    return results

                # Build ILIKE conditions for top 3 query terms
                like_conditions = " OR ".join(
                    [f"summary ILIKE %s" for _ in terms[:3]]
                )
                like_params = [f"%{t}%" for t in terms[:3]]

                # Tier 2: memory_summaries (recent compressed, 0.7x weight)
                matter_filter = ""
                matter_params = []
                if project:
                    matter_filter = " AND matter_slug ILIKE %s"
                    matter_params = [f"%{project}%"]

                cur.execute(f"""
                    SELECT matter_slug, contact_name, summary, period_start, period_end,
                           interaction_count, 2 as tier
                    FROM memory_summaries
                    WHERE ({like_conditions}){matter_filter}
                    ORDER BY updated_at DESC
                    LIMIT 5
                """, like_params + matter_params)

                for row in cur.fetchall():
                    summary_text = row.get("summary", "")
                    # Score based on how many terms match (max ~0.7)
                    match_count = sum(1 for t in terms if t in summary_text.lower())
                    score = min(0.7, 0.3 + (match_count * 0.1))
                    results.append(RetrievedContext(
                        content=summary_text[:2000],
                        source="tier2_summary",
                        score=score,
                        metadata={
                            "collection": "memory_summaries",
                            "matter_slug": row.get("matter_slug", ""),
                            "contact_name": row.get("contact_name", ""),
                            "tier": 2,
                            "period": f"{row.get('period_start', '')} to {row.get('period_end', '')}",
                            "label": f"[Tier 2] {row.get('matter_slug', '')}",
                        },
                        token_estimate=self._estimate_tokens(summary_text[:2000]),
                    ))

                # Tier 3: memory_institutional (permanent knowledge, 0.5x weight)
                cur.execute(f"""
                    SELECT matter_slug, brief, period_start, period_end, 3 as tier
                    FROM memory_institutional
                    WHERE ({like_conditions}){matter_filter}
                    ORDER BY updated_at DESC
                    LIMIT 3
                """, like_params + matter_params)

                for row in cur.fetchall():
                    brief_text = row.get("brief", "")
                    match_count = sum(1 for t in terms if t in brief_text.lower())
                    score = min(0.5, 0.2 + (match_count * 0.1))
                    results.append(RetrievedContext(
                        content=brief_text[:1500],
                        source="tier3_institutional",
                        score=score,
                        metadata={
                            "collection": "memory_institutional",
                            "matter_slug": row.get("matter_slug", ""),
                            "tier": 3,
                            "period": f"{row.get('period_start', '')} to {row.get('period_end', '')}",
                            "label": f"[Tier 3] {row.get('matter_slug', '')}",
                        },
                        token_estimate=self._estimate_tokens(brief_text[:1500]),
                    ))

                cur.close()
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.debug(f"THREE-TIER-MEMORY: tier search failed (non-fatal): {e}")
        return results

    def _enrich_with_full_text(self, contexts: list["RetrievedContext"]) -> list["RetrievedContext"]:
        """
        For top-scoring meeting/email/document chunks from Qdrant, replace
        truncated content with full source text from PostgreSQL.
        SPECIALIST-UPGRADE-1A: added document enrichment + increased limits.
        """
        enriched_ids = set()  # avoid duplicating the same source

        for i, ctx in enumerate(contexts[:15]):  # scan top 15 candidates
            if len(enriched_ids) >= 5:  # max 5 full-text enrichments
                break

            try:
                # Meeting transcripts — match by fireflies_id in metadata
                fireflies_id = ctx.metadata.get("fireflies_id") or ctx.metadata.get("transcript_id")
                if fireflies_id and fireflies_id not in enriched_ids:
                    full = self._get_full_meeting_transcript(fireflies_id)
                    if full:
                        contexts[i] = RetrievedContext(
                            content=full,
                            source=ctx.source,
                            score=ctx.score,
                            metadata={**ctx.metadata, "enriched": True},
                            token_estimate=self._estimate_tokens(full),
                        )
                        enriched_ids.add(fireflies_id)
                        logger.info(f"Enriched meeting {fireflies_id} with full transcript")
                        continue

                # Emails — match by source_id (message_id) in trigger_log
                source_id = ctx.metadata.get("message_id") or ctx.metadata.get("source_id")
                collection = ctx.metadata.get("collection", "")
                is_email = "email" in collection or ctx.source in ("email", "emails", "conversations")
                if is_email and source_id and source_id not in enriched_ids:
                    full = self._get_full_trigger_content(source_id)
                    if full:
                        contexts[i] = RetrievedContext(
                            content=full,
                            source=ctx.source,
                            score=ctx.score,
                            metadata={**ctx.metadata, "enriched": True},
                            token_estimate=self._estimate_tokens(full),
                        )
                        enriched_ids.add(source_id)
                        logger.info(f"Enriched email {source_id} with full content")
                        continue

                # Documents — match by source_path or filename (SPECIALIST-UPGRADE-1A)
                is_document = "document" in collection
                source_path = ctx.metadata.get("source_path", "")
                filename_meta = ctx.metadata.get("filename", ctx.metadata.get("label", ""))
                if is_document and (source_path or filename_meta):
                    doc_key = source_path or filename_meta
                    if doc_key not in enriched_ids:
                        full = self._get_full_document_text(source_path, filename_meta)
                        if full:
                            contexts[i] = RetrievedContext(
                                content=full,
                                source=ctx.source,
                                score=ctx.score,
                                metadata={**ctx.metadata, "enriched": True},
                                token_estimate=self._estimate_tokens(full),
                            )
                            enriched_ids.add(doc_key)
                            logger.info(f"Enriched document {doc_key} with full text")
                            continue

            except Exception as e:
                logger.debug(f"Enrichment failed for context {i} (non-fatal): {e}")

        return contexts

    def _get_full_meeting_transcript(self, transcript_id: str) -> Optional[str]:
        """Fetch full transcript text from meeting_transcripts table."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT full_transcript FROM meeting_transcripts WHERE id = %s",
                (transcript_id,),
            )
            row = cur.fetchone()
            cur.close()
            return row[0] if row and row[0] else None
        except Exception as e:
            logger.debug(f"Full transcript lookup failed for {transcript_id}: {e}")
            self._pg_pool = None
            return None

    def _get_full_trigger_content(self, source_id: str) -> Optional[str]:
        """Fetch full content from trigger_log by source_id."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT content FROM trigger_log WHERE source_id = %s ORDER BY received_at DESC LIMIT 1",
                (source_id,),
            )
            row = cur.fetchone()
            cur.close()
            return row[0] if row and row[0] else None
        except Exception as e:
            logger.debug(f"Full trigger content lookup failed for {source_id}: {e}")
            self._pg_pool = None
            return None

    def _get_full_document_text(self, source_path: str = None,
                                filename: str = None) -> Optional[str]:
        """Fetch full document text from documents table (SPECIALIST-UPGRADE-1A).
        DOC-TRIAGE-1: Excludes media_asset type — no point enriching image descriptions."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            if source_path:
                cur.execute(
                    "SELECT full_text FROM documents WHERE source_path = %s"
                    " AND COALESCE(document_type, '') != 'media_asset' LIMIT 1",
                    (source_path,),
                )
            elif filename:
                cur.execute(
                    "SELECT full_text FROM documents WHERE filename = %s"
                    " AND COALESCE(document_type, '') != 'media_asset'"
                    " ORDER BY ingested_at DESC LIMIT 1",
                    (filename,),
                )
            else:
                cur.close()
                return None
            row = cur.fetchone()
            cur.close()
            return row[0] if row and row[0] else None
        except Exception as e:
            logger.debug(f"Full document lookup failed: {e}")
            self._pg_pool = None
            return None

    # ----------------------------------------------------------------
    # PostgreSQL Structured Queries
    # ----------------------------------------------------------------

    def _get_pg_conn(self):
        """Lazy-init PostgreSQL connection."""
        if self._pg_pool is None:
            import psycopg2
            self._pg_pool = psycopg2.connect(**config.postgres.dsn_params)
        return self._pg_pool

    def get_contact_profile(self, contact_name: str) -> Optional[RetrievedContext]:
        """Retrieve structured contact profile from PostgreSQL.
        Searches both contacts and vip_contacts tables.
        Full-name matches are preferred over first-name-only matches."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()

            # Search VIP contacts first (richer profiles)
            cur.execute(
                """
                SELECT id, name, role, email, whatsapp_id, tier, domain,
                       role_context, communication_pref, expertise
                FROM vip_contacts
                WHERE LOWER(name) = LOWER(%s)
                   OR similarity(name, %s) > 0.35
                ORDER BY
                    CASE WHEN LOWER(name) = LOWER(%s) THEN 0 ELSE 1 END,
                    similarity(name, %s) DESC
                LIMIT 1
                """,
                (contact_name, contact_name, contact_name, contact_name),
            )
            vip_row = cur.fetchone()
            if vip_row:
                cols = ["id", "name", "role", "email", "whatsapp_id", "tier",
                        "domain", "role_context", "communication_pref", "expertise"]
                profile = {c: v for c, v in zip(cols, vip_row) if v is not None}
                content = json.dumps(profile, default=str, indent=2)
                cur.close()
                return RetrievedContext(
                    content=f"[VIP CONTACT PROFILE] {content}",
                    source="postgres",
                    score=1.0,
                    metadata={"type": "vip_contact_profile", "name": profile.get("name")},
                    token_estimate=self._estimate_tokens(content),
                )

            # Fallback: old contacts table
            cur.execute(
                """
                SELECT id, name, role, company, email, phone, relationship_tier,
                       communication_style, response_pattern, timezone,
                       last_contact, notes, metadata
                FROM contacts
                WHERE similarity(name, %s) > 0.3
                ORDER BY similarity(name, %s) DESC
                LIMIT 1
                """,
                (contact_name, contact_name),
            )
            row = cur.fetchone()
            cur.close()
            if row:
                cols = [
                    "id", "name", "role", "company", "email", "phone",
                    "relationship_tier", "communication_style", "response_pattern",
                    "timezone", "last_contact", "notes", "metadata",
                ]
                profile = {c: v for c, v in zip(cols, row) if v is not None}
                content = json.dumps(profile, default=str, indent=2)
                return RetrievedContext(
                    content=f"[CONTACT PROFILE] {content}",
                    source="postgres",
                    score=1.0,
                    metadata={"type": "contact_profile", "name": profile.get("name")},
                    token_estimate=self._estimate_tokens(content),
                )
        except Exception as e:
            logger.warning(f"PostgreSQL contact lookup failed (non-fatal): {e}")
            self._pg_pool = None
        return None

    def get_active_deals(self) -> list[RetrievedContext]:
        """Retrieve all active deals from PostgreSQL."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT d.id, d.name, d.status, d.stage, d.deal_value,
                       d.currency, d.priority, d.metadata,
                       bc.name AS buyer_name, sc.name AS seller_name
                FROM deals d
                LEFT JOIN contacts bc ON d.buyer_contact_id = bc.id
                LEFT JOIN contacts sc ON d.seller_contact_id = sc.id
                WHERE d.status = 'active'
                ORDER BY d.priority DESC NULLS LAST
                """
            )
            rows = cur.fetchall()
            cols = [
                "id", "name", "status", "stage", "deal_value",
                "currency", "priority", "metadata",
                "buyer_name", "seller_name",
            ]
            cur.close()
            contexts = []
            for row in rows:
                deal = {c: v for c, v in zip(cols, row) if v is not None}
                content = json.dumps(deal, default=str, indent=2)
                contexts.append(RetrievedContext(
                    content=f"[ACTIVE DEAL] {content}",
                    source="postgres",
                    score=1.0,
                    metadata={"type": "deal", "label": deal.get("name"), "name": deal.get("name")},
                    token_estimate=self._estimate_tokens(content),
                ))
            return contexts
        except Exception as e:
            logger.warning(f"PostgreSQL deals lookup failed (non-fatal): {e}")
            self._pg_pool = None
            return []

    def get_ceo_preferences(self) -> Optional[RetrievedContext]:
        """Retrieve CEO preferences and settings."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT key, value FROM preferences WHERE user_role = 'ceo'"
            )
            rows = cur.fetchall()
            cur.close()
            if rows:
                prefs = {row[0]: row[1] for row in rows}
                content = json.dumps(prefs, indent=2)
                return RetrievedContext(
                    content=f"[CEO PREFERENCES] {content}",
                    source="postgres",
                    score=1.0,
                    metadata={"type": "preferences"},
                    token_estimate=self._estimate_tokens(content),
                )
        except Exception as e:
            logger.warning(f"PostgreSQL preferences lookup failed (non-fatal): {e}")
            self._pg_pool = None
        return None

    def get_pending_alerts(self) -> list[RetrievedContext]:
        """Retrieve unresolved alerts for pipeline awareness."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, tier, title, body, action_required, created_at
                FROM alerts
                WHERE status = 'open'
                ORDER BY tier ASC, created_at DESC
                LIMIT 10
                """
            )
            rows = cur.fetchall()
            cols = ["id", "tier", "title", "body", "action_required", "created_at"]
            cur.close()
            if rows:
                alerts = [{c: v for c, v in zip(cols, row) if v is not None} for row in rows]
                content = json.dumps(alerts, default=str, indent=2)
                return [RetrievedContext(
                    content=f"[PENDING ALERTS ({len(alerts)})] {content}",
                    source="postgres",
                    score=1.0,
                    metadata={"type": "pending_alerts", "count": len(alerts)},
                    token_estimate=self._estimate_tokens(content),
                )]
        except Exception as e:
            logger.warning(f"PostgreSQL alerts lookup failed (non-fatal): {e}")
            self._pg_pool = None
        return []

    def get_recent_decisions(self, limit: int = 5) -> list[RetrievedContext]:
        """Retrieve recent decisions for continuity awareness."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, decision, reasoning, confidence, trigger_type, created_at
                FROM decisions
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            cols = ["id", "decision", "reasoning", "confidence", "trigger_type", "created_at"]
            cur.close()
            if rows:
                decisions = [{c: v for c, v in zip(cols, row) if v is not None} for row in rows]
                content = json.dumps(decisions, default=str, indent=2)
                return [RetrievedContext(
                    content=f"[RECENT DECISIONS ({len(decisions)})] {content}",
                    source="postgres",
                    score=0.9,
                    metadata={"type": "recent_decisions", "count": len(decisions)},
                    token_estimate=self._estimate_tokens(content),
                )]
        except Exception as e:
            logger.warning(f"PostgreSQL decisions lookup failed (non-fatal): {e}")
            self._pg_pool = None
        return []

    # ----------------------------------------------------------------
    # Meeting Transcripts (ARCH-3 — full text from PostgreSQL)
    # ----------------------------------------------------------------

    def get_meeting_transcripts(self, query: str, limit: int = 5) -> list[RetrievedContext]:
        """Search meeting_transcripts table by keyword match on title, participants, or full text."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, title, meeting_date, duration, organizer, participants,
                       summary, full_transcript
                FROM meeting_transcripts
                WHERE title ILIKE %s
                   OR participants ILIKE %s
                   OR organizer ILIKE %s
                   OR full_transcript ILIKE %s
                ORDER BY ingested_at DESC
                LIMIT %s
                """,
                (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", limit),
            )
            rows = cur.fetchall()
            cols = ["id", "title", "meeting_date", "duration", "organizer",
                    "participants", "summary", "full_transcript"]
            cur.close()

            contexts = []
            for row in rows:
                data = {c: v for c, v in zip(cols, row) if v is not None}
                # Use full transcript as content, capped at token budget
                transcript_text = data.get("full_transcript", "")
                title = data.get("title", "Unknown Meeting")
                date = data.get("meeting_date", "")
                date_str = str(date)[:10] if date else ""

                content = (
                    f"[MEETING TRANSCRIPT] {title} ({date_str})\n"
                    f"Organizer: {data.get('organizer', '?')}\n"
                    f"Participants: {data.get('participants', '?')}\n"
                    f"Duration: {data.get('duration', '?')}\n\n"
                    f"{transcript_text}"
                )

                contexts.append(RetrievedContext(
                    content=content,
                    source="meeting",
                    score=0.95,  # High score — direct keyword match
                    metadata={
                        "type": "meeting_transcript",
                        "label": title,
                        "date": date_str,
                        "meeting_id": data.get("id"),
                    },
                    token_estimate=self._estimate_tokens(content),
                ))
            return contexts
        except Exception as e:
            logger.warning(f"Meeting transcript search failed (non-fatal): {e}")
            self._pg_pool = None
            return []

    # ----------------------------------------------------------------
    # Email Messages (ARCH-6 — full text from PostgreSQL)
    # ----------------------------------------------------------------

    def get_email_messages(self, query: str, limit: int = 5) -> list[RetrievedContext]:
        """Search email_messages table by keyword match on subject, sender, or body."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT message_id, thread_id, sender_name, sender_email,
                       subject, full_body, received_date
                FROM email_messages
                WHERE subject ILIKE %s
                   OR sender_name ILIKE %s
                   OR sender_email ILIKE %s
                   OR full_body ILIKE %s
                ORDER BY received_date DESC NULLS LAST
                LIMIT %s
                """,
                (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", limit),
            )
            rows = cur.fetchall()
            cols = ["message_id", "thread_id", "sender_name", "sender_email",
                    "subject", "full_body", "received_date"]
            cur.close()

            contexts = []
            for row in rows:
                data = {c: v for c, v in zip(cols, row) if v is not None}
                body = data.get("full_body", "")
                subject = data.get("subject", "No subject")
                sender = data.get("sender_name") or data.get("sender_email") or "Unknown"
                date = data.get("received_date", "")
                date_str = str(date)[:10] if date else ""

                content = (
                    f"[EMAIL] From: {sender} | Subject: {subject} ({date_str})\n\n"
                    f"{body}"
                )
                contexts.append(RetrievedContext(
                    content=content,
                    source="email",
                    score=0.95,
                    metadata={
                        "type": "email_message",
                        "label": subject,
                        "date": date_str,
                        "message_id": data.get("message_id"),
                        "sender": sender,
                    },
                    token_estimate=self._estimate_tokens(content),
                ))
            return contexts
        except Exception as e:
            logger.warning(f"Email message search failed (non-fatal): {e}")
            self._pg_pool = None
            return []

    def get_recent_emails(self, limit: int = 5) -> list[RetrievedContext]:
        """Get the N most recent emails by date."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT message_id, sender_name, sender_email, subject, full_body, received_date
                FROM email_messages
                ORDER BY received_date DESC NULLS LAST
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            cols = ["message_id", "sender_name", "sender_email", "subject", "full_body", "received_date"]
            cur.close()

            contexts = []
            for row in rows:
                data = {c: v for c, v in zip(cols, row) if v is not None}
                body = data.get("full_body", "")
                subject = data.get("subject", "No subject")
                sender = data.get("sender_name") or data.get("sender_email") or "Unknown"
                date = data.get("received_date", "")
                date_str = str(date)[:10] if date else ""

                content = (
                    f"[EMAIL] From: {sender} | Subject: {subject} ({date_str})\n\n"
                    f"{body}"
                )
                contexts.append(RetrievedContext(
                    content=content,
                    source="email",
                    score=0.85,
                    metadata={
                        "type": "email_message",
                        "label": subject,
                        "date": date_str,
                        "message_id": data.get("message_id"),
                    },
                    token_estimate=self._estimate_tokens(content),
                ))
            return contexts
        except Exception as e:
            logger.warning(f"Recent email fetch failed (non-fatal): {e}")
            self._pg_pool = None
            return []

    # ----------------------------------------------------------------
    # WhatsApp Messages (ARCH-7 — full text from PostgreSQL)
    # ----------------------------------------------------------------

    def get_whatsapp_messages(self, query: str, limit: int = 5) -> list[RetrievedContext]:
        """Search whatsapp_messages table by keyword match on sender, text."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, sender, sender_name, full_text, timestamp
                FROM whatsapp_messages
                WHERE sender_name ILIKE %s
                   OR full_text ILIKE %s
                ORDER BY timestamp DESC NULLS LAST
                LIMIT %s
                """,
                (f"%{query}%", f"%{query}%", limit),
            )
            rows = cur.fetchall()
            cols = ["id", "sender", "sender_name", "full_text", "timestamp"]
            cur.close()

            contexts = []
            for row in rows:
                data = {c: v for c, v in zip(cols, row) if v is not None}
                text = data.get("full_text", "")
                sender = data.get("sender_name") or data.get("sender") or "Unknown"
                date = data.get("timestamp", "")
                date_str = str(date)[:10] if date else ""

                content = f"[WHATSAPP] {sender} ({date_str}): {text}"
                contexts.append(RetrievedContext(
                    content=content,
                    source="whatsapp",
                    score=0.95,
                    metadata={
                        "type": "whatsapp_message",
                        "label": f"WhatsApp: {sender}",
                        "date": date_str,
                        "msg_id": data.get("id"),
                    },
                    token_estimate=self._estimate_tokens(content),
                ))
            return contexts
        except Exception as e:
            logger.warning(f"WhatsApp message search failed (non-fatal): {e}")
            self._pg_pool = None
            return []

    def get_recent_whatsapp(self, limit: int = 5) -> list[RetrievedContext]:
        """Get the N most recent WhatsApp messages by date."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, sender, sender_name, full_text, timestamp
                FROM whatsapp_messages
                ORDER BY timestamp DESC NULLS LAST
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            cols = ["id", "sender", "sender_name", "full_text", "timestamp"]
            cur.close()

            contexts = []
            for row in rows:
                data = {c: v for c, v in zip(cols, row) if v is not None}
                text = data.get("full_text", "")
                sender = data.get("sender_name") or data.get("sender") or "Unknown"
                date = data.get("timestamp", "")
                date_str = str(date)[:10] if date else ""

                content = f"[WHATSAPP] {sender} ({date_str}): {text}"
                contexts.append(RetrievedContext(
                    content=content,
                    source="whatsapp",
                    score=0.85,
                    metadata={
                        "type": "whatsapp_message",
                        "label": f"WhatsApp: {sender}",
                        "date": date_str,
                    },
                    token_estimate=self._estimate_tokens(content),
                ))
            return contexts
        except Exception as e:
            logger.warning(f"Recent WhatsApp fetch failed (non-fatal): {e}")
            self._pg_pool = None
            return []

    # ----------------------------------------------------------------
    # Strategic Insights (INSIGHT-1)
    # ----------------------------------------------------------------

    def get_insights(self, query: str, limit: int = 5) -> list[RetrievedContext]:
        """Search insights table by keyword match on title or content."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, title, content, tags, source, project, created_at
                FROM insights
                WHERE title ILIKE %s OR content ILIKE %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (f"%{query}%", f"%{query}%", limit),
            )
            rows = cur.fetchall()
            cols = ["id", "title", "content", "tags", "source", "project", "created_at"]
            cur.close()

            contexts = []
            for row in rows:
                data = {c: v for c, v in zip(cols, row) if v is not None}
                title = data.get("title", "Untitled")
                content = data.get("content", "")
                date = data.get("created_at", "")
                date_str = str(date)[:10] if date else ""

                full = f"[STRATEGIC INSIGHT] {title} ({date_str})\n\n{content}"
                contexts.append(RetrievedContext(
                    content=full,
                    source="insight",
                    score=0.95,
                    metadata={
                        "type": "insight",
                        "label": title,
                        "date": date_str,
                        "insight_id": data.get("id"),
                        "project": data.get("project"),
                    },
                    token_estimate=self._estimate_tokens(full),
                ))
            return contexts
        except Exception as e:
            logger.warning(f"Insight search failed (non-fatal): {e}")
            self._pg_pool = None
            return []

    def get_recent_meeting_transcripts(self, limit: int = 5) -> list[RetrievedContext]:
        """Get the N most recent meeting transcripts by date — no keyword needed."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, title, meeting_date, duration, organizer, participants,
                       summary, full_transcript
                FROM meeting_transcripts
                ORDER BY ingested_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            cols = ["id", "title", "meeting_date", "duration", "organizer",
                    "participants", "summary", "full_transcript"]
            cur.close()

            contexts = []
            for row in rows:
                data = {c: v for c, v in zip(cols, row) if v is not None}
                transcript_text = data.get("full_transcript", "")
                title = data.get("title", "Unknown Meeting")
                date = data.get("meeting_date", "")
                date_str = str(date)[:10] if date else ""

                content = (
                    f"[MEETING TRANSCRIPT] {title} ({date_str})\n"
                    f"Organizer: {data.get('organizer', '?')}\n"
                    f"Participants: {data.get('participants', '?')}\n"
                    f"Duration: {data.get('duration', '?')}\n\n"
                    f"{transcript_text}"
                )

                contexts.append(RetrievedContext(
                    content=content,
                    source="meeting",
                    score=0.9,
                    metadata={
                        "type": "meeting_transcript",
                        "label": title,
                        "date": date_str,
                        "meeting_id": data.get("id"),
                    },
                    token_estimate=self._estimate_tokens(content),
                ))
            return contexts
        except Exception as e:
            logger.warning(f"Recent meeting transcript fetch failed (non-fatal): {e}")
            self._pg_pool = None
            return []

    # ----------------------------------------------------------------
    # ClickUp Tasks (STEP1B — keyword search on PostgreSQL)
    # ----------------------------------------------------------------

    def get_clickup_tasks_search(
        self,
        query: str,
        status: str = None,
        priority: str = None,
        list_name: str = None,
        limit: int = 10,
    ) -> list[RetrievedContext]:
        """Search clickup_tasks table by keyword (ILIKE on name + description).
        Optional filters: status, priority, list_name (partial match)."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()

            if query:
                where_parts = ["(name ILIKE %s OR description ILIKE %s)"]
                params: list = [f"%{query}%", f"%{query}%"]
            else:
                where_parts = ["1=1"]
                params: list = []

            if status:
                where_parts.append("status ILIKE %s")
                params.append(f"%{status}%")
            if priority:
                where_parts.append("priority ILIKE %s")
                params.append(f"%{priority}%")
            if list_name:
                where_parts.append("list_name ILIKE %s")
                params.append(f"%{list_name}%")

            where_clause = " AND ".join(where_parts)
            params.append(limit)

            cur.execute(
                f"""
                SELECT id, name, description, status, priority,
                       due_date, list_name, assignees, tags, date_updated
                FROM clickup_tasks
                WHERE {where_clause}
                ORDER BY date_updated DESC NULLS LAST
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
            cols = [
                "id", "name", "description", "status", "priority",
                "due_date", "list_name", "assignees", "tags", "date_updated",
            ]
            cur.close()

            contexts = []
            for row in rows:
                data = {c: v for c, v in zip(cols, row) if v is not None}
                name = data.get("name", "Untitled Task")
                status_val = data.get("status", "unknown")
                priority_val = data.get("priority", "normal")
                due = data.get("due_date")
                due_str = str(due)[:10] if due else "no due date"
                list_val = data.get("list_name", "")
                description = data.get("description", "")
                date_updated = data.get("date_updated")
                date_str = str(date_updated)[:10] if date_updated else ""

                content = (
                    f"[CLICKUP TASK] {name}\n"
                    f"Status: {status_val} | Priority: {priority_val} | "
                    f"Due: {due_str} | List: {list_val}\n"
                )
                if description:
                    content += f"Description: {description}\n"

                contexts.append(RetrievedContext(
                    content=content,
                    source="clickup",
                    score=0.95,
                    metadata={
                        "type": "clickup_task",
                        "label": name,
                        "date": date_str,
                        "task_id": data.get("id"),
                        "status": status_val,
                        "list_name": list_val,
                    },
                    token_estimate=self._estimate_tokens(content),
                ))
            return contexts
        except Exception as e:
            logger.warning(f"ClickUp task search failed (non-fatal): {e}")
            self._pg_pool = None
            return []

    # ----------------------------------------------------------------
    # RETRIEVAL-FIX-1: Matter Registry Expansion
    # ----------------------------------------------------------------

    def expand_query_via_matters(self, query: str) -> list[str]:
        """Look up the matter registry. If query matches a matter name, keyword,
        or person, return all associated people + keywords as additional search
        terms. Returns empty list on no match or error (non-fatal)."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            q_lower = query.lower().strip()
            if not q_lower:
                return []
            # Match if: query equals matter name, OR query contains a matter name,
            # OR a matter name contains the query, OR query matches a keyword/person.
            # This handles multi-word agent queries like "Cupial dispute".
            q_like = f"%{q_lower}%"
            cur.execute(
                """SELECT people, keywords FROM matter_registry
                   WHERE status = 'active'
                     AND (LOWER(matter_name) ILIKE %s
                          OR %s ILIKE '%%' || LOWER(matter_name) || '%%'
                          OR %s = ANY(SELECT LOWER(unnest(keywords)))
                          OR %s = ANY(SELECT LOWER(unnest(people)))
                          OR EXISTS (
                              SELECT 1 FROM unnest(keywords) k
                              WHERE %s ILIKE '%%' || LOWER(k) || '%%'
                          ))""",
                (q_like, q_lower, q_lower, q_lower, q_lower),
            )
            rows = cur.fetchall()
            cur.close()
            if not rows:
                return []

            # Merge people first (most useful for email/WA sender matching),
            # then keywords. Deduplicated, preserving priority order.
            seen = set()
            expanded_people = []
            expanded_keywords = []
            for people, keywords in rows:
                for p in (people or []):
                    p_key = p.lower()
                    if p_key not in seen and p_key != q_lower:
                        seen.add(p_key)
                        expanded_people.append(p)
                for k in (keywords or []):
                    k_key = k.lower()
                    if k_key not in seen and k_key != q_lower:
                        seen.add(k_key)
                        expanded_keywords.append(k)

            result = expanded_people + expanded_keywords
            logger.info(
                f"Matter expansion for '{query}': {len(result)} terms "
                f"({len(expanded_people)} people + {len(expanded_keywords)} keywords) "
                f"from {len(rows)} matter(s)"
            )
            return result
        except Exception as e:
            logger.debug(f"Matter expansion failed (non-fatal): {e}")
            self._pg_pool = None
            return []

    def get_matter_context(self, query: str) -> Optional[dict]:
        """Look up a matter by name or keyword. Returns full matter record
        or None. Used by the agent's get_matter_context tool."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            q_lower = query.lower().strip()
            if not q_lower:
                return None
            q_like = f"%{q_lower}%"
            cur.execute(
                """SELECT id, matter_name, description, people, keywords,
                          projects, status
                   FROM matter_registry
                   WHERE status = 'active'
                     AND (LOWER(matter_name) ILIKE %s
                          OR %s ILIKE '%%' || LOWER(matter_name) || '%%'
                          OR %s = ANY(SELECT LOWER(unnest(keywords)))
                          OR %s = ANY(SELECT LOWER(unnest(people)))
                          OR EXISTS (
                              SELECT 1 FROM unnest(keywords) k
                              WHERE %s ILIKE '%%' || LOWER(k) || '%%'
                          ))
                   LIMIT 1""",
                (q_like, q_lower, q_lower, q_lower, q_lower),
            )
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None
        except Exception as e:
            logger.debug(f"get_matter_context failed (non-fatal): {e}")
            self._pg_pool = None
            return None

    # ----------------------------------------------------------------
    # Combined Retrieval
    # ----------------------------------------------------------------

    def retrieve_for_trigger(
        self,
        trigger_text: str,
        trigger_type: str,
        contact_name: Optional[str] = None,
        project: Optional[str] = None,
        role: Optional[str] = None,
        context_plan: dict = None,
    ) -> list[RetrievedContext]:
        """
        Full retrieval pipeline for a trigger event.
        Combines semantic search + structured data.

        Baker 3.0: If context_plan is provided (from context_selector),
        only queries sources that are not 'skip' and respects per-source limits.
        If context_plan is None, queries everything (backward compatible).
        """
        from orchestrator.context_selector import should_skip_source, get_source_limit

        contexts = []

        # 1. Semantic search across all vector collections
        if not should_skip_source(context_plan, "semantic"):
            sem_limit = get_source_limit(context_plan, "semantic", default=10)
            semantic_results = self.search_all_collections(
                query=trigger_text,
                limit_per_collection=sem_limit,
                score_threshold=0.3,
                project=project,
                role=role,
            )
            contexts.extend(semantic_results)

        # 2. Contact profile if we know who this is about
        if not should_skip_source(context_plan, "contacts"):
            plan_contact = (context_plan or {}).get("contact") if context_plan else None
            lookup_name = contact_name or plan_contact
            if lookup_name:
                profile = self.get_contact_profile(lookup_name)
                if profile:
                    contexts.insert(0, profile)

        # 3. Meeting transcripts (ARCH-3 — keyword match + recent)
        if not should_skip_source(context_plan, "meetings"):
            mtg_limit = get_source_limit(context_plan, "meetings", default=3)
            transcripts = self.get_meeting_transcripts(trigger_text, limit=mtg_limit)
            contexts.extend(transcripts)
            recent = self.get_recent_meeting_transcripts(limit=min(mtg_limit, 3))
            existing_ids = {c.metadata.get("meeting_id") for c in transcripts}
            for r in recent:
                if r.metadata.get("meeting_id") not in existing_ids:
                    contexts.append(r)

        # 4. Email messages (ARCH-6 — keyword match + recent)
        if not should_skip_source(context_plan, "emails"):
            email_limit = get_source_limit(context_plan, "emails", default=3)
            emails = self.get_email_messages(trigger_text, limit=email_limit)
            contexts.extend(emails)
            recent_emails = self.get_recent_emails(limit=min(email_limit, 3))
            existing_email_ids = {c.metadata.get("message_id") for c in emails}
            for r in recent_emails:
                if r.metadata.get("message_id") not in existing_email_ids:
                    contexts.append(r)

        # 5. WhatsApp messages (ARCH-7 — keyword match + recent)
        if not should_skip_source(context_plan, "whatsapp"):
            wa_limit = get_source_limit(context_plan, "whatsapp", default=3)
            wa_msgs = self.get_whatsapp_messages(trigger_text, limit=wa_limit)
            contexts.extend(wa_msgs)
            recent_wa = self.get_recent_whatsapp(limit=min(wa_limit, 3))
            existing_wa_ids = {c.metadata.get("msg_id") for c in wa_msgs}
            for r in recent_wa:
                if r.metadata.get("msg_id") not in existing_wa_ids:
                    contexts.append(r)

        # 6. Strategic insights (INSIGHT-1 — keyword match)
        if not should_skip_source(context_plan, "insights"):
            insights = self.get_insights(trigger_text, limit=3)
            contexts.extend(insights)

        # 7. Active deals
        if not should_skip_source(context_plan, "deals"):
            deals = self.get_active_deals()
            contexts.extend(deals)

        # 8. CEO preferences
        if not should_skip_source(context_plan, "preferences"):
            prefs = self.get_ceo_preferences()
            if prefs:
                contexts.append(prefs)

        # 9. Pending alerts (situational awareness)
        if not should_skip_source(context_plan, "alerts"):
            alerts = self.get_pending_alerts()
            contexts.extend(alerts)

        # 10. Recent decisions (continuity)
        if not should_skip_source(context_plan, "decisions"):
            decisions = self.get_recent_decisions(limit=5)
            contexts.extend(decisions)

        logger.info(
            f"Total retrieved: {len(contexts)} contexts, "
            f"≈{sum(c.token_estimate for c in contexts)} tokens"
            f"{' (context selector active)' if context_plan else ''}"
        )
        return contexts
