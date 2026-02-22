"""
Sentinel AI — Store Back Layer (Step 5)
Write-side counterpart to memory/retriever.py (read-side).
Handles all PostgreSQL structured writes + Qdrant interaction embeddings.

Uses psycopg2 (sync) with SimpleConnectionPool.
All writes use parameterized queries — no SQL injection risk.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.pool
import psycopg2.extras

import voyageai
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance

from config.settings import config

logger = logging.getLogger("sentinel.store_back")


class SentinelStoreBack:
    """Write layer for PostgreSQL structured memory + Qdrant vectors."""

    _instance = None

    @classmethod
    def _get_global_instance(cls):
        """Return the module-level singleton. Lazy-init if needed."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        # Qdrant (vector store)
        self.qdrant = QdrantClient(
            url=config.qdrant.url,
            api_key=config.qdrant.api_key,
        )
        self.voyage = voyageai.Client(api_key=config.voyage.api_key)

        # PostgreSQL connection pool
        self._pool = None
        self._init_pool()

    # -------------------------------------------------------
    # Connection pool management
    # -------------------------------------------------------

    def _init_pool(self):
        """Initialize psycopg2 connection pool."""
        try:
            self._pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=5,
                **config.postgres.dsn_params,
            )
            logger.info("PostgreSQL connection pool initialized")
        except Exception as e:
            logger.warning(f"PostgreSQL pool init failed (non-fatal): {e}")
            self._pool = None

    def _get_conn(self):
        """Get a connection from pool. Returns None if pool unavailable."""
        if self._pool is None:
            self._init_pool()
        if self._pool is None:
            return None
        try:
            return self._pool.getconn()
        except Exception as e:
            logger.warning(f"Failed to get PostgreSQL connection: {e}")
            return None

    def _put_conn(self, conn):
        """Return connection to pool."""
        if self._pool and conn:
            try:
                self._pool.putconn(conn)
            except Exception:
                pass

    # -------------------------------------------------------
    # Contact Intelligence
    # -------------------------------------------------------

    def upsert_contact(self, name: str, updates: dict) -> Optional[str]:
        """
        Update or insert a contact. Merges fields, doesn't overwrite NULLs.
        Returns contact UUID or None on failure.
        """
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping upsert_contact")
            return None
        try:
            cur = conn.cursor()

            # Build dynamic SET clause — only update non-None fields
            allowed_fields = {
                "phone", "email", "company", "role", "relationship",
                "language", "timezone", "communication_style",
                "response_pattern", "preferred_channel", "metadata",
            }
            set_parts = []
            values = [name]  # $1 = name

            idx = 2
            for field_name in allowed_fields:
                if field_name in updates and updates[field_name] is not None:
                    if field_name == "metadata":
                        # Merge JSONB instead of overwrite
                        set_parts.append(f"metadata = contacts.metadata || %s::jsonb")
                        values.append(json.dumps(updates[field_name]))
                    else:
                        set_parts.append(f"{field_name} = %s")
                        values.append(updates[field_name])
                    idx += 1

            # Handle active_deals array merge
            if "active_deals" in updates and updates["active_deals"]:
                set_parts.append(
                    "active_deals = ARRAY(SELECT DISTINCT unnest(contacts.active_deals || %s::text[]))"
                )
                values.append(updates["active_deals"])

            # Handle last_contact timestamp
            if "last_contact" in updates:
                set_parts.append("last_contact = %s")
                values.append(updates["last_contact"])

            # Always update updated_at
            set_parts.append("updated_at = NOW()")

            if not set_parts:
                set_parts = ["updated_at = NOW()"]

            set_clause = ", ".join(set_parts)

            sql = f"""
                INSERT INTO contacts (name, updated_at)
                VALUES (%s, NOW())
                ON CONFLICT (name) DO UPDATE SET {set_clause}
                RETURNING id
            """
            cur.execute(sql, values)
            row = cur.fetchone()
            conn.commit()
            cur.close()

            contact_id = str(row[0]) if row else None
            logger.info(f"Upserted contact: {name} → {contact_id}")
            return contact_id

        except Exception as e:
            conn.rollback()
            logger.error(f"upsert_contact failed for '{name}': {e}")
            return None
        finally:
            self._put_conn(conn)

    def get_contact_by_name(self, name: str) -> Optional[dict]:
        """Fuzzy lookup using pg_trgm similarity. Returns best match or None."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """
                SELECT *, similarity(name, %s) AS sim
                FROM contacts
                WHERE similarity(name, %s) > 0.3
                ORDER BY similarity(name, %s) DESC
                LIMIT 1
                """,
                (name, name, name),
            )
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_contact_by_name failed for '{name}': {e}")
            return None
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Decision Log
    # -------------------------------------------------------

    def log_decision(self, decision: str, reasoning: str,
                     confidence: str, trigger_type: str) -> Optional[int]:
        """Insert into decisions table. Returns decision ID."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping log_decision")
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO decisions (decision, reasoning, confidence, trigger_type, created_at)
                VALUES (%s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (decision, reasoning, confidence, trigger_type),
            )
            decision_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            logger.info(f"Logged decision #{decision_id}: {decision[:60]}...")
            return decision_id
        except Exception as e:
            conn.rollback()
            logger.error(f"log_decision failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def record_feedback(self, decision_id: int, accepted: bool,
                        rejection_reason: str = None):
        """Update decision with CEO feedback (learning loop)."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE decisions
                SET accepted = %s, rejection_reason = %s, feedback_at = NOW()
                WHERE id = %s
                """,
                (accepted, rejection_reason, decision_id),
            )
            conn.commit()
            cur.close()
            logger.info(f"Feedback recorded for decision #{decision_id}: accepted={accepted}")
        except Exception as e:
            conn.rollback()
            logger.error(f"record_feedback failed for #{decision_id}: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Trigger Log
    # -------------------------------------------------------

    def log_trigger(self, trigger_type: str, source_id: str,
                    content: str, contact_id: str = None,
                    priority: str = None) -> Optional[int]:
        """Log every pipeline execution. Returns trigger_log ID."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping log_trigger")
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO trigger_log (type, source_id, content, contact_id, priority, received_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (trigger_type, source_id, content,
                 contact_id if contact_id else None,
                 priority),
            )
            trigger_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            logger.info(f"Logged trigger #{trigger_id}: type={trigger_type}")
            return trigger_id
        except Exception as e:
            conn.rollback()
            logger.error(f"log_trigger failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def update_trigger_result(self, trigger_id: int, response_id: str,
                              pipeline_ms: int, tokens_in: int, tokens_out: int):
        """Update trigger_log after pipeline completes."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE trigger_log
                SET processed = TRUE, response_id = %s, pipeline_ms = %s,
                    tokens_in = %s, tokens_out = %s, processed_at = NOW()
                WHERE id = %s
                """,
                (response_id, pipeline_ms, tokens_in, tokens_out, trigger_id),
            )
            conn.commit()
            cur.close()
            logger.info(f"Updated trigger #{trigger_id}: {pipeline_ms}ms, {tokens_in}+{tokens_out} tokens")
        except Exception as e:
            conn.rollback()
            logger.error(f"update_trigger_result failed for #{trigger_id}: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Alerts
    # -------------------------------------------------------

    def create_alert(self, tier: int, title: str, body: str = None,
                     action_required: bool = False, trigger_id: int = None,
                     contact_id: str = None, deal_id: str = None) -> Optional[int]:
        """Insert into alerts table. Returns alert ID."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping create_alert")
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO alerts (tier, title, body, action_required,
                    trigger_id, contact_id, deal_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (tier, title, body, action_required,
                 trigger_id, contact_id if contact_id else None,
                 deal_id if deal_id else None),
            )
            alert_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            logger.info(f"Created alert #{alert_id}: tier={tier}, '{title}'")
            return alert_id
        except Exception as e:
            conn.rollback()
            logger.error(f"create_alert failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def get_pending_alerts(self, tier: int = None) -> list:
        """Fetch unresolved alerts, optionally filtered by tier."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if tier:
                cur.execute(
                    "SELECT * FROM alerts WHERE status = 'pending' AND tier = %s ORDER BY created_at DESC",
                    (tier,),
                )
            else:
                cur.execute(
                    "SELECT * FROM alerts WHERE status = 'pending' ORDER BY tier, created_at DESC"
                )
            rows = cur.fetchall()
            cur.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_pending_alerts failed: {e}")
            return []
        finally:
            self._put_conn(conn)

    def acknowledge_alert(self, alert_id: int):
        """Mark alert as acknowledged."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE alerts SET status = 'acknowledged', acknowledged_at = NOW() WHERE id = %s",
                (alert_id,),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            conn.rollback()
            logger.error(f"acknowledge_alert failed for #{alert_id}: {e}")
        finally:
            self._put_conn(conn)

    def resolve_alert(self, alert_id: int):
        """Mark alert as resolved."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE alerts SET status = 'resolved', resolved_at = NOW() WHERE id = %s",
                (alert_id,),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            conn.rollback()
            logger.error(f"resolve_alert failed for #{alert_id}: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Decisions
    # -------------------------------------------------------

    def get_recent_decisions(self, limit: int = 10) -> list:
        """Fetch recent decisions for dashboard display."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
            cur.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_recent_decisions failed: {e}")
            return []
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Deals
    # -------------------------------------------------------

    def upsert_deal(self, name: str, updates: dict) -> Optional[str]:
        """Update or insert a deal. Returns deal UUID."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()

            allowed_fields = {
                "status", "stage", "priority", "deal_value", "currency",
                "qualification_score", "qualification_notes", "metadata",
            }
            set_parts = []
            values = [name]

            for field_name in allowed_fields:
                if field_name in updates and updates[field_name] is not None:
                    if field_name == "metadata":
                        set_parts.append(f"metadata = deals.metadata || %s::jsonb")
                        values.append(json.dumps(updates[field_name]))
                    else:
                        set_parts.append(f"{field_name} = %s")
                        values.append(updates[field_name])

            set_parts.append("updated_at = NOW()")
            set_clause = ", ".join(set_parts)

            sql = f"""
                INSERT INTO deals (name, updated_at)
                VALUES (%s, NOW())
                ON CONFLICT (name) DO UPDATE SET {set_clause}
                RETURNING id
            """

            # deals.name is not unique in the schema, so use a different approach
            # First try to find existing deal by name
            cur.execute("SELECT id FROM deals WHERE name = %s LIMIT 1", (name,))
            existing = cur.fetchone()

            if existing:
                deal_id = str(existing[0])
                if set_parts:
                    update_sql = f"UPDATE deals SET {set_clause} WHERE name = %s"
                    update_values = values[1:] + [name]  # skip the first name, add name at end
                    cur.execute(update_sql, update_values)
            else:
                # Insert new deal
                insert_fields = ["name"]
                insert_values = [name]
                for field_name in allowed_fields:
                    if field_name in updates and updates[field_name] is not None:
                        insert_fields.append(field_name)
                        if field_name == "metadata":
                            insert_values.append(json.dumps(updates[field_name]))
                        else:
                            insert_values.append(updates[field_name])

                placeholders = ", ".join(["%s"] * len(insert_values))
                fields_str = ", ".join(insert_fields)
                cur.execute(
                    f"INSERT INTO deals ({fields_str}) VALUES ({placeholders}) RETURNING id",
                    insert_values,
                )
                deal_id = str(cur.fetchone()[0])

            conn.commit()
            cur.close()
            logger.info(f"Upserted deal: {name} → {deal_id}")
            return deal_id
        except Exception as e:
            conn.rollback()
            logger.error(f"upsert_deal failed for '{name}': {e}")
            return None
        finally:
            self._put_conn(conn)

    def get_active_deals(self) -> list:
        """All deals with status='active'."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM deals WHERE status = 'active' ORDER BY priority, created_at DESC")
            rows = cur.fetchall()
            cur.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_active_deals failed: {e}")
            return []
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Qdrant: Store interaction as embedding
    # -------------------------------------------------------

    def _embed(self, text: str) -> list[float]:
        result = self.voyage.embed(
            texts=[text],
            model=config.voyage.model,
            input_type="document",
        )
        return result.embeddings[0]

    def store_interaction(
        self,
        trigger_type: str,
        trigger_content: str,
        response_analysis: str,
        contact_name: Optional[str] = None,
    ):
        """Store a Sentinel interaction as a new vector in Qdrant."""
        collection = "sentinel-interactions"
        try:
            try:
                self.qdrant.get_collection(collection)
            except Exception:
                self.qdrant.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(
                        size=config.voyage.dimensions,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created collection: {collection}")

            text = (
                f"[{trigger_type}] {trigger_content}\n"
                f"[Analysis] {response_analysis}"
            )
            vector = self._embed(text[:8000])
            point_id = int(datetime.now(timezone.utc).timestamp() * 1000)

            self.qdrant.upsert(
                collection_name=collection,
                points=[PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "text": text,
                        "trigger_type": trigger_type,
                        "contact": contact_name or "unknown",
                        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )],
            )
            logger.info(f"Stored interaction {point_id} in {collection}")
        except Exception as e:
            logger.warning(f"store_interaction failed (non-fatal): {e}")

    # -------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------

    def close(self):
        """Close connection pool."""
        if self._pool:
            self._pool.closeall()
            logger.info("PostgreSQL connection pool closed")
