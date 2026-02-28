"""
Sentinel AI — Store Back Layer (Step 5)
Write-side counterpart to memory/retriever.py (read-side).
Handles all PostgreSQL structured writes + Qdrant interaction embeddings.

Uses psycopg2 (sync) with SimpleConnectionPool.
All writes use parameterized queries — no SQL injection risk.
"""
import json
import logging
import uuid
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

        # Ensure ClickUp tables exist
        self._ensure_clickup_tables()

        # Ensure deep_analyses table exists
        self._ensure_deep_analyses_table()

        # Ensure baker-documents Qdrant collection exists
        self._ensure_collection("baker-documents", size=1024)  # Voyage AI voyage-3 dimension

        # Ensure baker-clickup Qdrant collection exists
        self._ensure_collection("baker-clickup", size=1024)

        # Ensure Todoist tables exist
        self._ensure_todoist_tables()

        # Ensure baker-todoist Qdrant collection exists
        self._ensure_collection("baker-todoist", size=1024)

        # Ensure baker-conversations Qdrant collection exists (CONV-MEM-1)
        self._ensure_collection("baker-conversations", size=1024)

        # Ensure conversation_memory PostgreSQL table exists (CONV-MEM-1)
        self._ensure_conversation_memory_table()

        # Ensure Whoop tables exist
        self._ensure_whoop_tables()

        # Ensure baker-health Qdrant collection exists
        self._ensure_collection("baker-health", size=1024)

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
    # ClickUp table initialization
    # -------------------------------------------------------

    def _ensure_clickup_tables(self):
        """Create clickup_tasks and baker_actions tables if they don't exist."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — cannot ensure ClickUp tables")
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS clickup_tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    status TEXT,
                    priority TEXT,
                    due_date TIMESTAMPTZ,
                    date_created TIMESTAMPTZ,
                    date_updated TIMESTAMPTZ,
                    list_id TEXT,
                    list_name TEXT,
                    space_id TEXT,
                    workspace_id TEXT,
                    assignees JSONB DEFAULT '[]',
                    tags JSONB DEFAULT '[]',
                    comment_count INTEGER DEFAULT 0,
                    last_synced TIMESTAMPTZ DEFAULT NOW(),
                    baker_tier TEXT,
                    baker_writable BOOLEAN DEFAULT FALSE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS baker_actions (
                    id SERIAL PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    target_task_id TEXT,
                    target_space_id TEXT,
                    payload JSONB,
                    trigger_source TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    success BOOLEAN DEFAULT TRUE,
                    error_message TEXT
                )
            """)
            conn.commit()
            cur.close()
            logger.info("ClickUp tables verified (clickup_tasks, baker_actions)")
        except Exception as e:
            logger.warning(f"Could not ensure ClickUp tables: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Todoist table initialization
    # -------------------------------------------------------

    def _ensure_todoist_tables(self):
        """Create todoist_tasks table if it doesn't exist."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — cannot ensure Todoist tables")
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS todoist_tasks (
                    todoist_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    description TEXT,
                    project_id TEXT,
                    project_name TEXT,
                    section_id TEXT,
                    section_name TEXT,
                    priority INTEGER DEFAULT 1,
                    priority_label TEXT DEFAULT 'normal',
                    due_date TEXT,
                    labels JSONB DEFAULT '[]',
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    last_synced TIMESTAMPTZ DEFAULT NOW(),
                    content_hash TEXT
                )
            """)
            conn.commit()
            cur.close()
            logger.info("Todoist tables verified (todoist_tasks)")
        except Exception as e:
            logger.warning(f"Could not ensure Todoist tables: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Qdrant collection helper
    # -------------------------------------------------------

    def _ensure_collection(self, name: str, size: int = 1024):
        """Create a Qdrant collection if it doesn't already exist."""
        try:
            self.qdrant.get_collection(name)
        except Exception:
            try:
                self.qdrant.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=size,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created Qdrant collection: {name}")
            except Exception as e:
                logger.warning(f"Could not create Qdrant collection '{name}': {e}")

    # -------------------------------------------------------
    # Deep Analyses table initialization
    # -------------------------------------------------------

    def _ensure_deep_analyses_table(self):
        """Create deep_analyses table if it doesn't exist."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — cannot ensure deep_analyses table")
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS deep_analyses (
                    analysis_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    source_documents JSONB DEFAULT '[]',
                    prompt TEXT,
                    token_count INTEGER DEFAULT 0,
                    chunk_count INTEGER DEFAULT 0,
                    cost_usd NUMERIC(10,4) DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit()
            cur.close()
            logger.info("deep_analyses table verified")
        except Exception as e:
            logger.warning(f"Could not ensure deep_analyses table: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # ClickUp helpers
    # -------------------------------------------------------

    def upsert_clickup_task(self, task_data: dict) -> Optional[str]:
        """INSERT ... ON CONFLICT (id) DO UPDATE for clickup_tasks. Returns task ID."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping upsert_clickup_task")
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO clickup_tasks
                    (id, name, description, status, priority, due_date,
                     date_created, date_updated, list_id, list_name,
                     space_id, workspace_id, assignees, tags,
                     comment_count, last_synced, baker_tier, baker_writable)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s::jsonb, %s::jsonb, %s, NOW(), %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    priority = EXCLUDED.priority,
                    due_date = EXCLUDED.due_date,
                    date_updated = EXCLUDED.date_updated,
                    list_id = EXCLUDED.list_id,
                    list_name = EXCLUDED.list_name,
                    space_id = EXCLUDED.space_id,
                    workspace_id = EXCLUDED.workspace_id,
                    assignees = EXCLUDED.assignees,
                    tags = EXCLUDED.tags,
                    comment_count = EXCLUDED.comment_count,
                    last_synced = NOW(),
                    baker_tier = EXCLUDED.baker_tier,
                    baker_writable = EXCLUDED.baker_writable
                RETURNING id
                """,
                (
                    task_data.get("id"),
                    task_data.get("name"),
                    task_data.get("description"),
                    task_data.get("status"),
                    task_data.get("priority"),
                    task_data.get("due_date"),
                    task_data.get("date_created"),
                    task_data.get("date_updated"),
                    task_data.get("list_id"),
                    task_data.get("list_name"),
                    task_data.get("space_id"),
                    task_data.get("workspace_id"),
                    json.dumps(task_data.get("assignees", [])),
                    json.dumps(task_data.get("tags", [])),
                    task_data.get("comment_count", 0),
                    task_data.get("baker_tier"),
                    task_data.get("baker_writable", False),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            task_id = row[0] if row else None
            logger.info(f"Upserted ClickUp task: {task_data.get('name', '?')[:60]} → {task_id}")
            return task_id
        except Exception as e:
            conn.rollback()
            logger.error(f"upsert_clickup_task failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Todoist helpers
    # -------------------------------------------------------

    def upsert_todoist_task(self, task_data: dict) -> Optional[tuple]:
        """INSERT ... ON CONFLICT (todoist_id) DO UPDATE for todoist_tasks.

        Returns (todoist_id, content_changed) tuple where content_changed is True
        if the content_hash differs from the stored value (meaning Qdrant re-embed needed).
        Returns None if no DB connection or on error.
        """
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping upsert_todoist_task")
            return None
        try:
            cur = conn.cursor()
            # First check if task exists and get current content_hash
            cur.execute(
                "SELECT content_hash FROM todoist_tasks WHERE todoist_id = %s",
                (task_data.get("todoist_id"),),
            )
            existing = cur.fetchone()
            old_hash = existing[0] if existing else None
            new_hash = task_data.get("content_hash")
            content_changed = (old_hash != new_hash)

            cur.execute(
                """
                INSERT INTO todoist_tasks
                    (todoist_id, content, description, project_id, project_name,
                     section_id, section_name, priority, priority_label,
                     due_date, labels, status, created_at, completed_at,
                     last_synced, content_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s, %s, %s, NOW(), %s)
                ON CONFLICT (todoist_id) DO UPDATE SET
                    content = EXCLUDED.content,
                    description = EXCLUDED.description,
                    project_id = EXCLUDED.project_id,
                    project_name = EXCLUDED.project_name,
                    section_id = EXCLUDED.section_id,
                    section_name = EXCLUDED.section_name,
                    priority = EXCLUDED.priority,
                    priority_label = EXCLUDED.priority_label,
                    due_date = EXCLUDED.due_date,
                    labels = EXCLUDED.labels,
                    status = EXCLUDED.status,
                    created_at = EXCLUDED.created_at,
                    completed_at = EXCLUDED.completed_at,
                    last_synced = NOW(),
                    content_hash = EXCLUDED.content_hash
                RETURNING todoist_id
                """,
                (
                    task_data.get("todoist_id"),
                    task_data.get("content"),
                    task_data.get("description"),
                    task_data.get("project_id"),
                    task_data.get("project_name"),
                    task_data.get("section_id"),
                    task_data.get("section_name"),
                    task_data.get("priority", 1),
                    task_data.get("priority_label", "normal"),
                    task_data.get("due_date"),
                    json.dumps(task_data.get("labels", [])),
                    task_data.get("status", "active"),
                    task_data.get("created_at"),
                    task_data.get("completed_at"),
                    new_hash,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            todoist_id = row[0] if row else None
            if todoist_id:
                logger.info(
                    f"Upserted Todoist task: {task_data.get('content', '?')[:60]} "
                    f"(changed={content_changed})"
                )
                return (todoist_id, content_changed)
            return None
        except Exception as e:
            conn.rollback()
            logger.error(f"upsert_todoist_task failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Whoop table initialization
    # -------------------------------------------------------

    def _ensure_whoop_tables(self):
        """Create whoop_records table if it doesn't exist."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — cannot ensure Whoop tables")
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS whoop_records (
                    whoop_id TEXT PRIMARY KEY,
                    record_type TEXT NOT NULL,
                    recorded_at TIMESTAMPTZ NOT NULL,
                    recovery_score REAL,
                    hrv_rmssd REAL,
                    resting_hr REAL,
                    spo2 REAL,
                    skin_temp REAL,
                    strain REAL,
                    sleep_total_ms BIGINT,
                    sleep_efficiency REAL,
                    kilojoule REAL,
                    avg_hr REAL,
                    max_hr REAL,
                    score_state TEXT,
                    raw_json JSONB,
                    content_hash TEXT,
                    last_synced TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit()
            cur.close()
            logger.info("Whoop tables verified (whoop_records)")
        except Exception as e:
            logger.warning(f"Could not ensure Whoop tables: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Whoop helpers
    # -------------------------------------------------------

    def upsert_whoop_record(self, record_data: dict) -> str:
        """INSERT ... ON CONFLICT (whoop_id) DO UPDATE for whoop_records.

        Checks content_hash first — returns 'skipped' if unchanged, 'upserted' otherwise.
        Returns 'error' on failure.
        """
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping upsert_whoop_record")
            return "error"
        try:
            cur = conn.cursor()
            # Check existing content_hash for dedup
            cur.execute(
                "SELECT content_hash FROM whoop_records WHERE whoop_id = %s",
                (record_data.get("whoop_id"),),
            )
            existing = cur.fetchone()
            old_hash = existing[0] if existing else None
            new_hash = record_data.get("content_hash")

            if old_hash == new_hash and old_hash is not None:
                cur.close()
                return "skipped"

            cur.execute(
                """
                INSERT INTO whoop_records
                    (whoop_id, record_type, recorded_at,
                     recovery_score, hrv_rmssd, resting_hr, spo2, skin_temp,
                     strain, sleep_total_ms, sleep_efficiency,
                     kilojoule, avg_hr, max_hr, score_state,
                     raw_json, content_hash, last_synced)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s::jsonb, %s, NOW())
                ON CONFLICT (whoop_id) DO UPDATE SET
                    record_type = EXCLUDED.record_type,
                    recorded_at = EXCLUDED.recorded_at,
                    recovery_score = EXCLUDED.recovery_score,
                    hrv_rmssd = EXCLUDED.hrv_rmssd,
                    resting_hr = EXCLUDED.resting_hr,
                    spo2 = EXCLUDED.spo2,
                    skin_temp = EXCLUDED.skin_temp,
                    strain = EXCLUDED.strain,
                    sleep_total_ms = EXCLUDED.sleep_total_ms,
                    sleep_efficiency = EXCLUDED.sleep_efficiency,
                    kilojoule = EXCLUDED.kilojoule,
                    avg_hr = EXCLUDED.avg_hr,
                    max_hr = EXCLUDED.max_hr,
                    score_state = EXCLUDED.score_state,
                    raw_json = EXCLUDED.raw_json,
                    content_hash = EXCLUDED.content_hash,
                    last_synced = NOW()
                """,
                (
                    record_data.get("whoop_id"),
                    record_data.get("record_type"),
                    record_data.get("recorded_at"),
                    record_data.get("recovery_score"),
                    record_data.get("hrv_rmssd"),
                    record_data.get("resting_hr"),
                    record_data.get("spo2"),
                    record_data.get("skin_temp"),
                    record_data.get("strain"),
                    record_data.get("sleep_total_ms"),
                    record_data.get("sleep_efficiency"),
                    record_data.get("kilojoule"),
                    record_data.get("avg_hr"),
                    record_data.get("max_hr"),
                    record_data.get("score_state"),
                    json.dumps(record_data.get("raw_json", {})),
                    new_hash,
                ),
            )
            conn.commit()
            cur.close()
            logger.info(
                f"Upserted Whoop record: {record_data.get('record_type')} "
                f"{record_data.get('whoop_id', '?')[:20]}"
            )
            return "upserted"
        except Exception as e:
            conn.rollback()
            logger.error(f"upsert_whoop_record failed: {e}")
            return "error"
        finally:
            self._put_conn(conn)

    def log_baker_action(self, action_type: str, target_task_id: str = None,
                         target_space_id: str = None, payload: dict = None,
                         trigger_source: str = None, success: bool = True,
                         error_message: str = None) -> Optional[int]:
        """INSERT into baker_actions audit log. Returns action ID."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping log_baker_action")
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO baker_actions
                    (action_type, target_task_id, target_space_id, payload,
                     trigger_source, success, error_message)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
                RETURNING id
                """,
                (
                    action_type,
                    target_task_id,
                    target_space_id,
                    json.dumps(payload) if payload else None,
                    trigger_source,
                    success,
                    error_message,
                ),
            )
            action_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            logger.info(f"Logged baker action #{action_id}: {action_type}")
            return action_id
        except Exception as e:
            conn.rollback()
            logger.error(f"log_baker_action failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def get_clickup_tasks(self, workspace_id: str = None, space_id: str = None,
                          list_id: str = None, status: str = None,
                          priority: str = None, limit: int = 50,
                          offset: int = 0) -> list:
        """Query clickup_tasks with optional filters. Returns list of dicts."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            where_parts = []
            params = []
            if workspace_id:
                where_parts.append("workspace_id = %s")
                params.append(workspace_id)
            if space_id:
                where_parts.append("space_id = %s")
                params.append(space_id)
            if list_id:
                where_parts.append("list_id = %s")
                params.append(list_id)
            if status:
                where_parts.append("status = %s")
                params.append(status)
            if priority:
                where_parts.append("priority = %s")
                params.append(priority)
            where_clause = " AND ".join(where_parts) if where_parts else "TRUE"
            params.extend([limit, offset])
            cur.execute(
                f"""
                SELECT * FROM clickup_tasks
                WHERE {where_clause}
                ORDER BY date_updated DESC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                params,
            )
            rows = cur.fetchall()
            cur.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_clickup_tasks failed: {e}")
            return []
        finally:
            self._put_conn(conn)

    def get_clickup_task(self, task_id: str) -> Optional[dict]:
        """Get a single ClickUp task by ID. Returns dict or None."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM clickup_tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_clickup_task failed for '{task_id}': {e}")
            return None
        finally:
            self._put_conn(conn)

    def get_clickup_sync_status(self) -> dict:
        """Get sync health: last poll per workspace, total count."""
        conn = self._get_conn()
        if not conn:
            return {"workspaces": [], "total_tasks": 0, "health": "no_connection"}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """
                SELECT workspace_id, COUNT(*) AS task_count,
                       MAX(last_synced) AS last_synced
                FROM clickup_tasks
                GROUP BY workspace_id
                ORDER BY workspace_id
                """
            )
            rows = cur.fetchall()
            cur.close()
            workspaces = [dict(r) for r in rows]
            total = sum(r["task_count"] for r in workspaces)
            return {
                "workspaces": workspaces,
                "total_tasks": total,
                "health": "ok" if workspaces else "no_data",
            }
        except Exception as e:
            logger.error(f"get_clickup_sync_status failed: {e}")
            return {"workspaces": [], "total_tasks": 0, "health": "error"}
        finally:
            self._put_conn(conn)

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
        full_content: Optional[str] = None,
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

            snippet_text = (
                f"[{trigger_type}] {trigger_content}\n"
                f"[Analysis] {response_analysis}"
            )
            # Embed full content when available for richer retrieval
            embed_text = (full_content or snippet_text)[:8000]
            vector = self._embed(embed_text)
            point_id = int(datetime.now(timezone.utc).timestamp() * 1000)

            payload = {
                "text": snippet_text,
                "trigger_type": trigger_type,
                "contact": contact_name or "unknown",
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if full_content:
                payload["full_content"] = full_content[:8000]

            self.qdrant.upsert(
                collection_name=collection,
                points=[PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )],
            )
            logger.info(f"Stored interaction {point_id} in {collection}")
        except Exception as e:
            logger.warning(f"store_interaction failed (non-fatal): {e}")

    # -------------------------------------------------------
    # Deep Analysis: store document chunks + catalogue record
    # -------------------------------------------------------

    def store_document(self, content, metadata, collection="baker-documents"):
        """Embed and store a document chunk in Qdrant."""
        try:
            embedding = self._embed(content[:8000])
            point_id = str(uuid.uuid4())
            self.qdrant.upsert(
                collection_name=collection,
                points=[PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={"content": content, **metadata},
                )],
            )
        except Exception as e:
            logger.error(f"Failed to store document in {collection}: {e}")

    def log_deep_analysis(self, analysis_id, topic, source_documents, prompt,
                          token_count=0, chunk_count=0, cost_usd=0):
        """Catalogue a completed deep analysis in PostgreSQL."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping log_deep_analysis")
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO deep_analyses
                    (analysis_id, topic, source_documents, prompt,
                     token_count, chunk_count, cost_usd)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (analysis_id) DO UPDATE SET
                    topic = EXCLUDED.topic,
                    token_count = EXCLUDED.token_count,
                    chunk_count = EXCLUDED.chunk_count,
                    cost_usd = EXCLUDED.cost_usd
            """, (analysis_id, topic, json.dumps(source_documents),
                  prompt[:500], token_count, chunk_count, cost_usd))
            conn.commit()
            cur.close()
        except Exception as e:
            logger.error(f"Failed to log deep analysis: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Conversation Memory (CONV-MEM-1)
    # -------------------------------------------------------

    def _ensure_conversation_memory_table(self):
        """Create conversation_memory table if it doesn't exist."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — cannot ensure conversation_memory table")
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversation_memory (
                    id SERIAL PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer_length INTEGER DEFAULT 0,
                    project TEXT DEFAULT 'general',
                    chunk_count INTEGER DEFAULT 1,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit()
            cur.close()
            logger.info("conversation_memory table verified")
        except Exception as e:
            logger.warning(f"Could not ensure conversation_memory table: {e}")
        finally:
            self._put_conn(conn)

    def log_conversation(self, question, answer_length=0, project="general", chunk_count=1):
        """Catalogue a scan conversation in PostgreSQL."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping log_conversation")
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO conversation_memory
                    (question, answer_length, project, chunk_count)
                VALUES (%s, %s, %s, %s)
            """, (question[:500], answer_length, project, chunk_count))
            conn.commit()
            cur.close()
        except Exception as e:
            logger.error(f"Failed to log conversation: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------

    def close(self):
        """Close connection pool."""
        if self._pool:
            self._pool.closeall()
            logger.info("PostgreSQL connection pool closed")
