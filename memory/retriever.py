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
                    time.sleep(1)  # rate-limit safety net
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

        # Sort by relevance score (highest first)
        all_contexts.sort(key=lambda c: c.score, reverse=True)
        return all_contexts

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
        """Retrieve structured contact profile from PostgreSQL using fuzzy match."""
        try:
            conn = self._get_pg_conn()
            cur = conn.cursor()
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
                    metadata={"type": "deal", "name": deal.get("name")},
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
    # Combined Retrieval
    # ----------------------------------------------------------------

    def retrieve_for_trigger(
        self,
        trigger_text: str,
        trigger_type: str,
        contact_name: Optional[str] = None,
        project: Optional[str] = None,
        role: Optional[str] = None,
    ) -> list[RetrievedContext]:
        """
        Full retrieval pipeline for a trigger event.
        Combines semantic search + structured data.
        """
        contexts = []

        # 1. Semantic search across all vector collections
        semantic_results = self.search_all_collections(
            query=trigger_text,
            limit_per_collection=10,
            score_threshold=0.3,
            project=project,
            role=role,
        )
        contexts.extend(semantic_results)

        # 2. Contact profile if we know who this is about
        if contact_name:
            profile = self.get_contact_profile(contact_name)
            if profile:
                contexts.insert(0, profile)

        # 3. Active deals (always included for CEO context)
        deals = self.get_active_deals()
        contexts.extend(deals)

        # 4. CEO preferences
        prefs = self.get_ceo_preferences()
        if prefs:
            contexts.append(prefs)

        # 5. Pending alerts (situational awareness)
        alerts = self.get_pending_alerts()
        contexts.extend(alerts)

        # 6. Recent decisions (continuity)
        decisions = self.get_recent_decisions(limit=5)
        contexts.extend(decisions)

        logger.info(
            f"Total retrieved: {len(contexts)} contexts, "
            f"≈{sum(c.token_estimate for c in contexts)} tokens"
        )
        return contexts
