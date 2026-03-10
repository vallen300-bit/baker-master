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

        # Ensure meeting_transcripts table exists (ARCH-3)
        self._ensure_meeting_transcripts_table()

        # Ensure email_messages table exists (ARCH-6)
        self._ensure_email_messages_table()

        # Ensure whatsapp_messages table exists (ARCH-7)
        self._ensure_whatsapp_messages_table()

        # Ensure insights table exists (INSIGHT-1)
        self._ensure_insights_table()

        # Ensure Whoop tables exist
        self._ensure_whoop_tables()

        # Ensure baker-health Qdrant collection exists
        self._ensure_collection("baker-health", size=1024)

        # Ensure baker-browser Qdrant collection exists (BROWSER-1)
        self._ensure_collection("baker-browser", size=1024)

        # STEP1C: Ensure baker_tasks table exists
        self._ensure_baker_tasks_table()

        # DECISION-ENGINE-1A: Ensure decision engine columns exist
        self._ensure_decision_engine_columns()

        # RETRIEVAL-FIX-1: Ensure matter_registry table exists
        self._ensure_matter_registry_table()

        # STEP3: Ensure director_preferences table + VIP profile columns
        self._ensure_director_preferences_table()
        self._ensure_vip_profile_columns()

        # AGENT-FRAMEWORK-1: Ensure capability framework tables
        self._ensure_capability_sets_table()
        self._ensure_capability_runs_table()
        self._ensure_decomposition_log_table()
        self._ensure_baker_tasks_capability_columns()
        self._ensure_alerts_v3_columns()
        self._ensure_alert_threads_table()
        self._ensure_alert_artifacts_table()
        self._ensure_commitments_table()

        # SPECIALIST-UPGRADE-1A/1B: Document intelligence
        self._ensure_documents_table()
        self._ensure_document_extractions_table()
        self._ensure_baker_insights_table()

        # PHASE-4A: Cost monitor + agent observability tables
        self._ensure_cost_and_metrics_tables()

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
        """Return connection to pool. Rollback any uncommitted transaction first
        to prevent returning a dirty connection that poisons the next caller."""
        if self._pool and conn:
            try:
                conn.rollback()  # No-op if already committed, safe always
            except Exception:
                pass
            try:
                self._pool.putconn(conn)
            except Exception:
                pass

    def _ensure_cost_and_metrics_tables(self):
        """PHASE-4A: Create api_cost_log + agent_tool_calls tables."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            from orchestrator.cost_monitor import ensure_api_cost_log_table
            from orchestrator.agent_metrics import ensure_agent_tool_calls_table
            ensure_api_cost_log_table(conn)
            ensure_agent_tool_calls_table(conn)
        except Exception as e:
            logger.warning(f"Could not ensure Phase 4A tables: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_documents_table(self):
        """SPECIALIST-UPGRADE-1A: Full document text storage."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id SERIAL PRIMARY KEY,
                    source_path TEXT,
                    filename VARCHAR(500),
                    file_hash VARCHAR(64) UNIQUE,
                    document_type VARCHAR(50),
                    language VARCHAR(10),
                    matter_slug VARCHAR(200),
                    parties TEXT[],
                    tags TEXT[],
                    full_text TEXT,
                    page_count INTEGER,
                    token_count INTEGER,
                    ingested_at TIMESTAMPTZ DEFAULT NOW(),
                    classified_at TIMESTAMPTZ,
                    extracted_at TIMESTAMPTZ
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_matter ON documents(matter_slug)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(document_type)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(file_hash)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_path)")
            conn.commit()
            cur.close()
            logger.info("documents table verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure documents table: {e}")
        finally:
            self._put_conn(conn)

    def store_document_full(self, source_path: str, filename: str,
                            file_hash: str, full_text: str,
                            token_count: int = 0):
        """Store full document text in PostgreSQL. Returns document ID or None."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO documents (source_path, filename, file_hash, full_text, token_count)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (file_hash) DO UPDATE SET
                    source_path = EXCLUDED.source_path,
                    full_text = EXCLUDED.full_text,
                    token_count = EXCLUDED.token_count,
                    ingested_at = NOW()
                RETURNING id
            """, (source_path, filename, file_hash, full_text, token_count))
            row = cur.fetchone()
            conn.commit()
            cur.close()
            return row[0] if row else None
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"store_document_full failed (non-fatal): {e}")
            return None
        finally:
            self._put_conn(conn)

    def _ensure_document_extractions_table(self):
        """SPECIALIST-UPGRADE-1B: Structured extraction results."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS document_extractions (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER REFERENCES documents(id),
                    extraction_type VARCHAR(50),
                    structured_data JSONB,
                    confidence VARCHAR(20),
                    extracted_by VARCHAR(50),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_doc_extractions_doc ON document_extractions(document_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_doc_extractions_type ON document_extractions(extraction_type)")
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure document_extractions table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_baker_insights_table(self):
        """SPECIALIST-UPGRADE-1B: Shared specialist insights."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS baker_insights (
                    id SERIAL PRIMARY KEY,
                    insight_type VARCHAR(30) NOT NULL,
                    content TEXT NOT NULL,
                    matter_slug VARCHAR(200),
                    source_capability VARCHAR(50),
                    source_task_id INTEGER,
                    confidence VARCHAR(20) DEFAULT 'medium',
                    validated_by VARCHAR(50),
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    expires_at TIMESTAMPTZ
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_baker_insights_matter ON baker_insights(matter_slug)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_baker_insights_active ON baker_insights(active) WHERE active = TRUE")
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure baker_insights table: {e}")
        finally:
            self._put_conn(conn)

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
                    analysis_text TEXT,
                    token_count INTEGER DEFAULT 0,
                    chunk_count INTEGER DEFAULT 0,
                    cost_usd NUMERIC(10,4) DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            # ARCH-5: Add analysis_text column to existing tables
            cur.execute("""
                ALTER TABLE deep_analyses
                ADD COLUMN IF NOT EXISTS analysis_text TEXT
            """)
            conn.commit()
            cur.close()
            logger.info("deep_analyses table verified")
        except Exception as e:
            logger.warning(f"Could not ensure deep_analyses table: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Meeting Transcripts (ARCH-3)
    # -------------------------------------------------------

    def _ensure_meeting_transcripts_table(self):
        """Create meeting_transcripts table if it doesn't exist."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — cannot ensure meeting_transcripts table")
            return
        try:
            cur = conn.cursor()
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
                    ingested_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit()
            cur.close()
            logger.info("meeting_transcripts table verified")
        except Exception as e:
            logger.warning(f"Could not ensure meeting_transcripts table: {e}")
        finally:
            self._put_conn(conn)

    def store_meeting_transcript(self, transcript_id: str, title: str,
                                  meeting_date: str = None, duration: str = None,
                                  organizer: str = None, participants: str = None,
                                  summary: str = None, full_transcript: str = None,
                                  source: str = "fireflies") -> bool:
        """Upsert a full meeting transcript. Returns True on success."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping store_meeting_transcript")
            return False
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO meeting_transcripts
                    (id, title, meeting_date, duration, organizer,
                     participants, summary, full_transcript, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    full_transcript = EXCLUDED.full_transcript,
                    ingested_at = NOW()
            """, (transcript_id, title, meeting_date, duration, organizer,
                  participants, summary, full_transcript, source))
            conn.commit()
            cur.close()
            logger.info(f"Stored meeting transcript: {title} ({transcript_id})")
            return True
        except Exception as e:
            logger.error(f"store_meeting_transcript failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Email Messages (ARCH-6)
    # -------------------------------------------------------

    def _ensure_email_messages_table(self):
        """Create email_messages table if it doesn't exist."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_messages (
                    message_id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    sender_name TEXT,
                    sender_email TEXT,
                    subject TEXT,
                    full_body TEXT,
                    received_date TIMESTAMPTZ,
                    priority TEXT,
                    ingested_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit()
            cur.close()
            logger.info("email_messages table verified")
        except Exception as e:
            logger.warning(f"Could not ensure email_messages table: {e}")
        finally:
            self._put_conn(conn)

    def store_email_message(self, message_id: str, thread_id: str = None,
                            sender_name: str = None, sender_email: str = None,
                            subject: str = None, full_body: str = None,
                            received_date: str = None, priority: str = None) -> bool:
        """Upsert a full email message. Returns True on success."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO email_messages
                    (message_id, thread_id, sender_name, sender_email,
                     subject, full_body, received_date, priority)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_id) DO UPDATE SET
                    full_body = EXCLUDED.full_body,
                    ingested_at = NOW()
            """, (message_id, thread_id, sender_name, sender_email,
                  subject, full_body, received_date, priority))
            conn.commit()
            cur.close()
            return True
        except Exception as e:
            logger.error(f"store_email_message failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # WhatsApp Messages (ARCH-7)
    # -------------------------------------------------------

    def _ensure_whatsapp_messages_table(self):
        """Create whatsapp_messages table if it doesn't exist."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS whatsapp_messages (
                    id TEXT PRIMARY KEY,
                    sender TEXT,
                    sender_name TEXT,
                    chat_id TEXT,
                    full_text TEXT,
                    timestamp TIMESTAMPTZ,
                    is_director BOOLEAN DEFAULT FALSE,
                    ingested_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit()
            cur.close()
            logger.info("whatsapp_messages table verified")
        except Exception as e:
            logger.warning(f"Could not ensure whatsapp_messages table: {e}")
        finally:
            self._put_conn(conn)

    def store_whatsapp_message(self, msg_id: str, sender: str = None,
                               sender_name: str = None, chat_id: str = None,
                               full_text: str = None, timestamp: str = None,
                               is_director: bool = False) -> bool:
        """Upsert a full WhatsApp message. Returns True on success."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO whatsapp_messages
                    (id, sender, sender_name, chat_id, full_text, timestamp, is_director)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    full_text = EXCLUDED.full_text,
                    ingested_at = NOW()
            """, (msg_id, sender, sender_name, chat_id, full_text, timestamp, is_director))
            conn.commit()
            cur.close()
            return True
        except Exception as e:
            logger.error(f"store_whatsapp_message failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Insights (INSIGHT-1 — Claude Code → Baker memory)
    # -------------------------------------------------------

    def _ensure_insights_table(self):
        """Create insights table if it doesn't exist."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS insights (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT[] DEFAULT '{}',
                    source TEXT NOT NULL DEFAULT 'claude-code',
                    project TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit()
            cur.close()
            logger.info("insights table verified")
        except Exception as e:
            logger.warning(f"Could not ensure insights table: {e}")
        finally:
            self._put_conn(conn)

    def store_insight(self, title: str, content: str, tags: list = None,
                      source: str = "claude-code", project: str = None) -> Optional[int]:
        """
        Store a strategic insight/analysis to PostgreSQL + Qdrant.
        Returns insight ID on success.
        """
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO insights (title, content, tags, source, project)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (title, content, tags or [], source, project))
            insight_id = cur.fetchone()[0]
            conn.commit()
            cur.close()

            # Also embed to Qdrant for semantic search
            try:
                embed_metadata = {
                    "source": "insight",
                    "title": title,
                    "tags": ",".join(tags) if tags else "",
                    "project": project or "",
                    "insight_id": str(insight_id),
                    "content_type": "strategic_insight",
                    "label": title,
                    "origin": source,
                }
                self.store_document(content, embed_metadata, collection="baker-conversations")
            except Exception as _e:
                logger.warning(f"Insight Qdrant embed failed (PostgreSQL saved): {_e}")

            logger.info(f"Stored insight #{insight_id}: {title}")
            return insight_id
        except Exception as e:
            logger.error(f"store_insight failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def get_insights(self, query: str = None, project: str = None,
                     limit: int = 10) -> list:
        """Search insights by keyword or project. Returns list of dicts."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if query:
                cur.execute(
                    """SELECT id, title, content, tags, source, project, created_at
                       FROM insights
                       WHERE title ILIKE %s OR content ILIKE %s
                       ORDER BY created_at DESC LIMIT %s""",
                    (f"%{query}%", f"%{query}%", limit),
                )
            elif project:
                cur.execute(
                    """SELECT id, title, content, tags, source, project, created_at
                       FROM insights WHERE project = %s
                       ORDER BY created_at DESC LIMIT %s""",
                    (project, limit),
                )
            else:
                cur.execute(
                    """SELECT id, title, content, tags, source, project, created_at
                       FROM insights ORDER BY created_at DESC LIMIT %s""",
                    (limit,),
                )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        except Exception as e:
            logger.error(f"get_insights failed: {e}")
            return []
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
    # STEP1C: Baker Tasks table + CRUD
    # -------------------------------------------------------

    def _ensure_baker_tasks_table(self):
        """Create baker_tasks table if it doesn't exist."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — cannot ensure baker_tasks table")
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS baker_tasks (
                    id              SERIAL PRIMARY KEY,
                    trigger_log_id  INTEGER,
                    domain          TEXT,
                    urgency_score   INTEGER,
                    tier            INTEGER,
                    mode            TEXT NOT NULL,
                    task_type       TEXT NOT NULL DEFAULT 'question',
                    title           TEXT NOT NULL,
                    description     TEXT,
                    sender          TEXT,
                    source          TEXT,
                    channel         TEXT,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    deliverable     TEXT,
                    error_message   TEXT,
                    agent_iterations    INTEGER,
                    agent_tool_calls    INTEGER,
                    agent_input_tokens  INTEGER,
                    agent_output_tokens INTEGER,
                    agent_elapsed_ms    INTEGER,
                    director_feedback   TEXT,
                    feedback_comment    TEXT,
                    feedback_at         TIMESTAMPTZ,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    started_at      TIMESTAMPTZ,
                    completed_at    TIMESTAMPTZ
                );
                CREATE INDEX IF NOT EXISTS idx_baker_tasks_status ON baker_tasks(status);
                CREATE INDEX IF NOT EXISTS idx_baker_tasks_created ON baker_tasks(created_at DESC);
            """)
            conn.commit()
            cur.close()
            logger.info("Baker tasks table verified (baker_tasks)")
        except Exception as e:
            logger.warning(f"Could not ensure baker_tasks table: {e}")
        finally:
            self._put_conn(conn)

    def create_baker_task(self, domain=None, urgency_score=None, tier=None,
                          mode="escalate", task_type="question", title="",
                          description=None, sender=None, source=None,
                          channel=None, status="in_progress",
                          trigger_log_id=None) -> Optional[int]:
        """INSERT into baker_tasks. Returns task ID."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping create_baker_task")
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO baker_tasks
                    (trigger_log_id, domain, urgency_score, tier, mode,
                     task_type, title, description, sender, source, channel,
                     status, started_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        CASE WHEN %s = 'in_progress' THEN NOW() ELSE NULL END)
                RETURNING id
                """,
                (
                    trigger_log_id, domain, urgency_score, tier, mode,
                    task_type, title, description, sender, source, channel,
                    status, status,
                ),
            )
            task_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            logger.info(f"Created baker_task #{task_id}: {mode}/{domain} — {title[:60]}")
            return task_id
        except Exception as e:
            conn.rollback()
            logger.error(f"create_baker_task failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    _TASK_UPDATE_FIELDS = {
        "status", "deliverable", "error_message",
        "agent_iterations", "agent_tool_calls",
        "agent_input_tokens", "agent_output_tokens", "agent_elapsed_ms",
        "director_feedback", "feedback_comment",
        "capability_slugs", "decomposition", "capability_slug",
    }

    def update_baker_task(self, task_id: int, **kwargs) -> bool:
        """UPDATE baker_tasks with explicit column whitelist. No arbitrary kwargs."""
        # Filter to allowed fields only
        updates = {k: v for k, v in kwargs.items()
                   if k in self._TASK_UPDATE_FIELDS and v is not None}
        if not updates:
            return False

        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping update_baker_task")
            return False
        try:
            cur = conn.cursor()
            set_clauses = []
            values = []
            for col, val in updates.items():
                set_clauses.append(f"{col} = %s")
                values.append(val)

            # Auto-set timestamps based on status transitions
            new_status = updates.get("status")
            if new_status == "in_progress":
                set_clauses.append("started_at = NOW()")
            elif new_status in ("completed", "failed"):
                set_clauses.append("completed_at = NOW()")

            # Auto-set feedback_at when director_feedback is provided
            if "director_feedback" in updates:
                set_clauses.append("feedback_at = NOW()")

            values.append(task_id)
            sql = f"UPDATE baker_tasks SET {', '.join(set_clauses)} WHERE id = %s"
            cur.execute(sql, values)
            conn.commit()

            # AGENT-FRAMEWORK-1: Propagate feedback to decomposition_log
            if "director_feedback" in updates:
                try:
                    feedback = updates["director_feedback"]
                    quality = "good" if feedback in ("accepted", "good") else "partial" if feedback == "revised" else "poor"
                    cur2 = conn.cursor()
                    cur2.execute(
                        """UPDATE decomposition_log
                           SET director_feedback = %s, feedback_at = NOW(),
                               outcome_quality = %s
                           WHERE baker_task_id = %s""",
                        (feedback, quality, task_id),
                    )
                    conn.commit()
                    cur2.close()
                except Exception as _fb_e:
                    logger.debug(f"Feedback propagation to decomposition_log failed (non-fatal): {_fb_e}")

            cur.close()
            logger.info(f"Updated baker_task #{task_id}: {list(updates.keys())}")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"update_baker_task failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    def get_baker_tasks(self, status=None, mode=None, limit=20) -> list:
        """SELECT from baker_tasks with optional filters. Returns list of dicts."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            conditions = []
            values = []
            if status:
                conditions.append("status = %s")
                values.append(status)
            if mode:
                conditions.append("mode = %s")
                values.append(mode)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            values.append(limit)
            cur.execute(
                f"SELECT * FROM baker_tasks {where} ORDER BY created_at DESC LIMIT %s",
                values,
            )
            rows = cur.fetchall()
            cur.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_baker_tasks failed: {e}")
            return []
        finally:
            self._put_conn(conn)

    def get_baker_task_by_id(self, task_id: int) -> Optional[dict]:
        """Get a single baker_task by ID. Returns dict or None."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM baker_tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_baker_task_by_id failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # DECISION-ENGINE-1A: Decision Engine column migrations
    # -------------------------------------------------------

    def _ensure_decision_engine_columns(self):
        """Add scored columns to vip_contacts and trigger_log. Idempotent."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — cannot ensure Decision Engine columns")
            return
        try:
            cur = conn.cursor()

            # vip_contacts: add tier + domain columns
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS tier INTEGER DEFAULT 2")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS domain VARCHAR(20) DEFAULT 'network'")

            # trigger_log: add scored fields
            cur.execute("ALTER TABLE trigger_log ADD COLUMN IF NOT EXISTS domain VARCHAR(20)")
            cur.execute("ALTER TABLE trigger_log ADD COLUMN IF NOT EXISTS urgency_score INTEGER")
            cur.execute("ALTER TABLE trigger_log ADD COLUMN IF NOT EXISTS tier INTEGER")
            cur.execute("ALTER TABLE trigger_log ADD COLUMN IF NOT EXISTS mode VARCHAR(20)")
            cur.execute("ALTER TABLE trigger_log ADD COLUMN IF NOT EXISTS scoring_reasoning TEXT")

            # Set Tier 1 VIPs (6 Director-confirmed) — safe: only upgrades tier, no deletes
            cur.execute("""
                UPDATE vip_contacts SET tier = 1
                WHERE LOWER(name) IN (
                    'edita vallen', 'alric ofenheimer', 'christophe buchwalder',
                    'andrey oskolkov', 'constantinos pohanis', 'christian merz'
                ) AND (tier IS NULL OR tier != 1)
            """)

            # C2 fix: VIP dedup removed from startup — was destructive on every deploy.
            # Run one-time dedup via: POST /api/admin/dedup-vips or manual SQL.

            conn.commit()
            cur.close()
            logger.info("Decision Engine columns verified (vip_contacts + trigger_log)")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure Decision Engine columns: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # STEP3: Director Preferences + VIP Profile Columns
    # -------------------------------------------------------

    def _ensure_director_preferences_table(self):
        """Create director_preferences table if it doesn't exist. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS director_preferences (
                    id          SERIAL PRIMARY KEY,
                    category    TEXT NOT NULL,
                    pref_key    TEXT NOT NULL,
                    pref_value  TEXT NOT NULL,
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(category, pref_key)
                )
            """)
            conn.commit()
            cur.close()
            logger.info("director_preferences table verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure director_preferences table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_vip_profile_columns(self):
        """Add profile + networking columns to vip_contacts. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            # Original profile columns
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS role_context TEXT")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS communication_pref TEXT DEFAULT 'email'")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS expertise TEXT")
            # NETWORKING-PHASE-1: extended columns
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS contact_type VARCHAR(20)")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS relationship_score INTEGER DEFAULT 0")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS net_worth_tier VARCHAR(20)")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS investment_thesis TEXT")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS personal_interests TEXT[]")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS gatekeeper_name VARCHAR(200)")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS gatekeeper_contact VARCHAR(200)")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS last_contact_date TIMESTAMPTZ")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS sentiment_trend VARCHAR(20)")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS source_of_introduction TEXT")
            conn.commit()
            cur.close()
            logger.info("vip_contacts profile + networking columns verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure VIP profile columns: {e}")
        finally:
            self._put_conn(conn)

        # NETWORKING-PHASE-1: contact_interactions + networking_events tables
        self._ensure_networking_tables()

    def _ensure_networking_tables(self):
        """Create contact_interactions and networking_events tables. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS contact_interactions (
                    id SERIAL PRIMARY KEY,
                    contact_id INTEGER REFERENCES vip_contacts(id),
                    channel VARCHAR(30),
                    direction VARCHAR(10),
                    timestamp TIMESTAMPTZ NOT NULL,
                    subject TEXT,
                    sentiment VARCHAR(20),
                    source_ref TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_contact_interactions_contact
                ON contact_interactions (contact_id, timestamp DESC)
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS networking_events (
                    id SERIAL PRIMARY KEY,
                    event_name VARCHAR(300) NOT NULL,
                    dates_start DATE,
                    dates_end DATE,
                    location VARCHAR(200),
                    category VARCHAR(50),
                    brisen_relevance_score INTEGER DEFAULT 5,
                    source_url TEXT,
                    notes TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit()
            cur.close()
            logger.info("Networking tables verified (contact_interactions, networking_events)")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure networking tables: {e}")
        finally:
            self._put_conn(conn)

    # -- Director Preferences CRUD --

    def upsert_preference(self, category: str, key: str, value: str) -> bool:
        """Insert or update a Director preference. Returns True on success."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO director_preferences (category, pref_key, pref_value)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (category, pref_key)
                   DO UPDATE SET pref_value = EXCLUDED.pref_value,
                                 updated_at = NOW()""",
                (category, key, value),
            )
            conn.commit()
            cur.close()
            logger.info(f"Upserted preference {category}/{key}")
            return True
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"upsert_preference failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    def get_preferences(self, category: str = None) -> list:
        """Get Director preferences, optionally filtered by category. Returns list of dicts."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if category:
                cur.execute(
                    """SELECT id, category, pref_key, pref_value, updated_at
                       FROM director_preferences
                       WHERE category = %s
                       ORDER BY category, pref_key""",
                    (category,),
                )
            else:
                cur.execute(
                    """SELECT id, category, pref_key, pref_value, updated_at
                       FROM director_preferences
                       ORDER BY category, pref_key"""
                )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        except Exception as e:
            logger.warning(f"get_preferences failed (non-fatal): {e}")
            return []
        finally:
            self._put_conn(conn)

    def delete_preference(self, category: str, key: str) -> bool:
        """Delete a Director preference by category + key. Returns True if deleted."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM director_preferences WHERE category = %s AND pref_key = %s",
                (category, key),
            )
            deleted = cur.rowcount
            conn.commit()
            cur.close()
            return deleted > 0
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"delete_preference failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    # -- VIP Profile Update --

    def update_vip_profile(self, name: str, **kwargs) -> Optional[dict]:
        """Update a VIP contact's profile fields. Only provided fields are updated.
        Allowed: tier, domain, role_context, communication_pref, expertise.
        Returns the updated row as dict, or None on failure/not found."""
        allowed = {"tier", "domain", "role_context", "communication_pref", "expertise"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return None
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            set_parts = []
            params = []
            for col, val in updates.items():
                set_parts.append(f"{col} = %s")
                params.append(val)
            params.append(name.lower())

            cur.execute(
                f"""UPDATE vip_contacts SET {', '.join(set_parts)}
                    WHERE LOWER(name) = %s
                    RETURNING *""",
                params,
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            if row:
                logger.info(f"Updated VIP profile for '{name}': {list(updates.keys())}")
                return dict(row)
            return None
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"update_vip_profile failed for '{name}': {e}")
            return None
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # AGENT-FRAMEWORK-1: Capability Framework Tables
    # -------------------------------------------------------

    def _ensure_capability_sets_table(self):
        """Create capability_sets table + indexes. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS capability_sets (
                    id                  SERIAL PRIMARY KEY,
                    slug                TEXT NOT NULL UNIQUE,
                    name                TEXT NOT NULL,
                    capability_type     TEXT NOT NULL DEFAULT 'domain',
                    domain              TEXT NOT NULL,
                    role_description    TEXT NOT NULL,
                    system_prompt       TEXT DEFAULT '',
                    tools               JSONB DEFAULT '[]'::jsonb,
                    output_format       TEXT DEFAULT 'prose',
                    autonomy_level      TEXT DEFAULT 'recommend_wait',
                    trigger_patterns    JSONB DEFAULT '[]'::jsonb,
                    max_iterations      INTEGER DEFAULT 5,
                    timeout_seconds     REAL DEFAULT 30.0,
                    active              BOOLEAN DEFAULT TRUE,
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_capability_sets_slug ON capability_sets(slug)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_capability_sets_domain ON capability_sets(domain)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_capability_sets_type ON capability_sets(capability_type)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_capability_sets_active ON capability_sets(active) WHERE active = TRUE")

            # SPECIALIST-THINKING-1: Add use_thinking column
            cur.execute("ALTER TABLE capability_sets ADD COLUMN IF NOT EXISTS use_thinking BOOLEAN DEFAULT FALSE")

            # Seed data — only if table is empty
            cur.execute("SELECT COUNT(*) FROM capability_sets")
            if cur.fetchone()[0] == 0:
                self._seed_capability_sets(cur)

            # SPECIALIST-THINKING-1: Set use_thinking for analytical specialists
            cur.execute("""
                UPDATE capability_sets SET use_thinking = TRUE
                WHERE slug IN ('legal', 'finance', 'profiling', 'sales', 'asset_management', 'research')
                  AND use_thinking = FALSE
            """)

            conn.commit()
            cur.close()
            logger.info("capability_sets table verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure capability_sets table: {e}")
        finally:
            self._put_conn(conn)

    def _seed_capability_sets(self, cur):
        """Insert 13 capability sets (11 domain + 2 meta). Called once on first deploy.
        Updated Session 14: all 11 PM-approved specs, slug renames, profiling + pr_branding added."""
        import json as _json
        seed = [
            # META capabilities
            {
                "slug": "decomposer", "name": "Task Decomposer",
                "capability_type": "meta", "domain": "meta",
                "role_description": "Analyzes incoming tasks and breaks them into independent sub-issues. For each sub-issue, identifies which capability set should handle it.",
                "system_prompt": "You are Baker's task decomposer. Given a complex task, break it into independent sub-issues.\n\nFor each sub-issue, specify:\n1. A clear, self-contained sub-task description\n2. The capability_slug that should handle it\n\nAvailable capability slugs: sales, finance, legal, asset_management, profiling, research, communications, pr_branding, marketing, ai_dev\n\nRules:\n- If the task is simple (single domain, single question), return it as ONE sub-task with ONE capability. Do NOT over-decompose.\n- Only decompose when the task genuinely spans multiple domains or requires multiple independent analyses.\n- Each sub-task must be self-contained.\n- Maximum 4 sub-tasks.\n\nReturn JSON array: [{\"sub_task\": \"...\", \"capability_slug\": \"...\"}]\n\n## PAST PATTERNS\n{experience_context}",
                "tools": _json.dumps([]),
                "output_format": "json", "autonomy_level": "auto_execute",
                "trigger_patterns": _json.dumps([]),
                "max_iterations": 1, "timeout_seconds": 15.0,
            },
            {
                "slug": "synthesizer", "name": "Result Synthesizer",
                "capability_type": "meta", "domain": "meta",
                "role_description": "Combines results from multiple capability runs into one coherent, unified deliverable for the Director.",
                "system_prompt": "You are Baker's result synthesizer. You receive results from multiple capability runs that analyzed different aspects of the Director's task.\n\nYour job:\n1. Combine all results into ONE coherent answer\n2. Resolve any contradictions between results (flag if unresolvable)\n3. Remove redundancy\n4. Structure the output: bottom-line first, then supporting detail per domain\n5. Cite which capability produced each finding\n\nThe Director expects: warm but direct, like a trusted advisor. Bottom-line first.",
                "tools": _json.dumps([]),
                "output_format": "prose", "autonomy_level": "auto_execute",
                "trigger_patterns": _json.dumps([]),
                "max_iterations": 1, "timeout_seconds": 15.0,
            },
            # DOMAIN capabilities (11 — all PM-approved, Session 14)
            {
                "slug": "sales", "name": "Sales Capability",
                "capability_type": "domain", "domain": "projects",
                "role_description": "Sales and investor relations for the Brisen Group — MORV residences, introducer pipeline, LP/investor relations, deal origination, property sales, business development.",
                "tools": _json.dumps(["search_memory", "search_emails", "web_search", "read_document", "search_whatsapp", "get_contact", "get_matter_context", "search_deals_insights"]),
                "trigger_patterns": _json.dumps([r"sales|buyer|prospect|MORV|investor|LP|deal|acquisition|pipeline"]),
                "output_format": "prose", "autonomy_level": "recommend_wait",
            },
            {
                "slug": "finance", "name": "Finance Capability",
                "capability_type": "domain", "domain": "chairman",
                "role_description": "Finance Director capability — group financial oversight, project tracking, investor/lender relations, tax/audit/accounting coordination.",
                "tools": _json.dumps(["search_memory", "search_emails", "search_meetings", "get_contact", "get_matter_context", "search_deals_insights", "get_deadlines", "web_search", "read_document"]),
                "trigger_patterns": _json.dumps([r"invoice|payment|cash.?flow|budget|bank|tax|audit|capital.call|loan|covenant|financial.statement|kyc"]),
                "output_format": "prose", "autonomy_level": "recommend_wait",
            },
            {
                "slug": "legal", "name": "Legal Capability",
                "capability_type": "domain", "domain": "projects",
                "role_description": "Legal capability across 5 jurisdictions — construction/project law, corporate/governance, real estate, contracts, regulatory, litigation/disputes.",
                "tools": _json.dumps(["search_memory", "search_emails", "web_search", "read_document", "search_meetings", "get_contact", "get_matter_context", "get_deadlines", "get_clickup_tasks"]),
                "trigger_patterns": _json.dumps([r"legal|lawyer|litigation|dispute|claim|contract|Gew.hrleistung|court|Buchwalder|Ofenheimer|Hagenauer"]),
                "output_format": "prose", "autonomy_level": "recommend_wait",
            },
            {
                "slug": "asset_management", "name": "Asset Management Capability",
                "capability_type": "domain", "domain": "projects",
                "role_description": "Asset management — property operations, portfolio performance, fund admin, insurance/risk, property tax, capex/maintenance.",
                "tools": _json.dumps(["search_memory", "search_emails", "web_search", "read_document", "search_meetings", "get_contact", "get_matter_context", "search_deals_insights", "get_deadlines"]),
                "trigger_patterns": _json.dumps([r"asset.management|property.management|valuation|NOI|KPI|NAV|insurance|capex|maintenance|Mandarin.Oriental"]),
                "output_format": "prose", "autonomy_level": "recommend_wait",
            },
            {
                "slug": "it", "name": "IT Infrastructure Capability",
                "capability_type": "domain", "domain": "projects",
                "role_description": "IT infrastructure and systems — M365, cybersecurity, hardware, vendor management (BCOMM/EVOK), AI infrastructure, domains/DNS.",
                "tools": _json.dumps(["search_memory", "search_emails", "web_search", "read_document", "search_whatsapp", "search_meetings", "get_contact", "get_matter_context", "get_clickup_tasks", "get_deadlines"]),
                "trigger_patterns": _json.dumps([r"M365|Microsoft|Entra|MFA|security|BCOMM|EVOK|Baker|Render|DNS|laptop|hardware"]),
                "output_format": "prose", "autonomy_level": "recommend_wait",
            },
            {
                "slug": "profiling", "name": "Strategic Profiling",
                "capability_type": "domain", "domain": "chairman",
                "role_description": "Strategic intelligence and psychological profiling — counterparty dossiers, negotiation tactics, game theory, relationship intelligence, adversarial analysis.",
                "tools": _json.dumps(["search_memory", "search_emails", "web_search", "read_document", "search_meetings", "search_whatsapp", "get_contact"]),
                "trigger_patterns": _json.dumps([r"profile|dossier|negotiat|BATNA|game.theory|approach|how.to.handle|adversar|Oskolkov|Hagenauer"]),
                "output_format": "prose", "autonomy_level": "proactive_flag",
            },
            {
                "slug": "research", "name": "Research Capability",
                "capability_type": "domain", "domain": "network",
                "role_description": "Market, competitive, and deal intelligence — competitor tracking, price intelligence, regulatory monitoring, industry research, OSINT/buyer research.",
                "tools": _json.dumps(["web_search", "search_memory", "search_emails", "search_meetings", "get_contact", "get_matter_context", "search_deals_insights", "read_document", "get_clickup_tasks"]),
                "trigger_patterns": _json.dumps([r"competitor|market|benchmark|hotel.rate|ADR|RevPAR|regulat|CSRD|luxury.hotel|buyer.research|deal.pipeline"]),
                "output_format": "prose", "autonomy_level": "proactive_flag",
            },
            {
                "slug": "communications", "name": "Communications Capability",
                "capability_type": "domain", "domain": "chairman",
                "role_description": "Communications drafting and coordination — email management, investor comms, proposals/pitches, internal team comms, PR, meeting prep/follow-up.",
                "tools": _json.dumps(["search_memory", "search_emails", "search_whatsapp", "search_meetings", "get_contact", "get_matter_context", "read_document", "web_search", "get_clickup_tasks"]),
                "trigger_patterns": _json.dumps([r"draft|write|reply|email|investor.update|proposal|pitch|team.update|meeting.prep|translate"]),
                "output_format": "prose", "autonomy_level": "recommend_wait",
            },
            {
                "slug": "pr_branding", "name": "PR & Branding",
                "capability_type": "domain", "domain": "network",
                "role_description": "Brand strategy, reputation management, public image — positioning, media relations, visual identity, digital presence, investor/partner perception.",
                "tools": _json.dumps(["web_search", "search_memory", "search_emails", "search_meetings", "read_document", "get_contact"]),
                "trigger_patterns": _json.dumps([r"brand|reputation|media|press|logo|design|LinkedIn|social.media|credibility|institutional"]),
                "output_format": "prose", "autonomy_level": "proactive_flag",
            },
            {
                "slug": "marketing", "name": "Marketing Capability",
                "capability_type": "domain", "domain": "network",
                "role_description": "Marketing strategy and collateral — capability marketing, MO leverage, residence marketing, digital/lead gen, events, campaign analytics.",
                "tools": _json.dumps(["web_search", "search_memory", "search_emails", "read_document", "get_contact", "get_clickup_tasks", "search_meetings"]),
                "trigger_patterns": _json.dumps([r"marketing|campaign|lead.generation|residence.brochure|MO.brand|event.marketing|ROI"]),
                "output_format": "prose", "autonomy_level": "recommend_wait",
            },
            {
                "slug": "ai_dev", "name": "AI Development Capability",
                "capability_type": "domain", "domain": "projects",
                "role_description": "AI strategy (Project clAIm) + Baker system development — capability framework, tools/integrations, automation, monitoring.",
                "tools": _json.dumps(["search_memory", "search_emails", "search_meetings", "get_clickup_tasks", "get_matter_context", "web_search", "read_document"]),
                "trigger_patterns": _json.dumps([r"Baker|clAIm|AI.strategy|capability|Code.300|integration|MCP|automation|prompt|monitoring"]),
                "output_format": "prose", "autonomy_level": "recommend_wait",
            },
        ]
        for cap in seed:
            cols = list(cap.keys())
            vals = [cap[c] for c in cols]
            placeholders = ", ".join(["%s"] * len(cols))
            col_names = ", ".join(cols)
            cur.execute(
                f"INSERT INTO capability_sets ({col_names}) VALUES ({placeholders}) ON CONFLICT (slug) DO NOTHING",
                vals,
            )
        logger.info(f"Seeded {len(seed)} capability sets")

    def _ensure_capability_runs_table(self):
        """Create capability_runs table. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS capability_runs (
                    id                  SERIAL PRIMARY KEY,
                    baker_task_id       INTEGER,
                    capability_slug     TEXT NOT NULL,
                    sub_task            TEXT,
                    answer              TEXT,
                    tools_used          JSONB DEFAULT '[]'::jsonb,
                    retrieved_docs      JSONB DEFAULT '[]'::jsonb,
                    iterations          INTEGER,
                    input_tokens        INTEGER,
                    output_tokens       INTEGER,
                    elapsed_ms          INTEGER,
                    status              TEXT NOT NULL DEFAULT 'running',
                    error_message       TEXT,
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at        TIMESTAMPTZ
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_capability_runs_slug ON capability_runs(capability_slug)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_capability_runs_task ON capability_runs(baker_task_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_capability_runs_created ON capability_runs(created_at DESC)")
            conn.commit()
            cur.close()
            logger.info("capability_runs table verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure capability_runs table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_decomposition_log_table(self):
        """Create decomposition_log table. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS decomposition_log (
                    id                  SERIAL PRIMARY KEY,
                    baker_task_id       INTEGER,
                    original_task       TEXT NOT NULL,
                    domain              TEXT,
                    sub_tasks           JSONB NOT NULL,
                    capabilities_used   JSONB NOT NULL,
                    director_feedback   TEXT,
                    feedback_at         TIMESTAMPTZ,
                    outcome_quality     TEXT,
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_decomp_log_created ON decomposition_log(created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_decomp_log_domain ON decomposition_log(domain)")
            conn.commit()
            cur.close()
            logger.info("decomposition_log table verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure decomposition_log table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_baker_tasks_capability_columns(self):
        """Add capability_slugs + decomposition columns to baker_tasks. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS capability_slugs JSONB DEFAULT '[]'::jsonb")
            cur.execute("ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS decomposition JSONB")
            cur.execute("ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS capability_slug TEXT")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_baker_tasks_capability ON baker_tasks USING gin(capability_slugs)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_baker_tasks_cap_slug ON baker_tasks(capability_slug)")
            conn.commit()
            cur.close()
            logger.info("baker_tasks capability columns verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure baker_tasks capability columns: {e}")
        finally:
            self._put_conn(conn)

    # -- Capability CRUD helpers --

    def insert_capability_run(self, baker_task_id=None, capability_slug="",
                              sub_task=None, status="running") -> Optional[int]:
        """INSERT a capability_run record. Returns ID."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO capability_runs
                   (baker_task_id, capability_slug, sub_task, status)
                   VALUES (%s, %s, %s, %s)
                   RETURNING id""",
                (baker_task_id, capability_slug, sub_task, status),
            )
            run_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            return run_id
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"insert_capability_run failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def update_capability_run(self, run_id: int, **kwargs) -> bool:
        """UPDATE a capability_run. Allowed: answer, tools_used, retrieved_docs,
        iterations, input_tokens, output_tokens, elapsed_ms, status, error_message."""
        allowed = {"answer", "tools_used", "retrieved_docs", "iterations",
                    "input_tokens", "output_tokens", "elapsed_ms", "status",
                    "error_message"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return False
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            set_parts = []
            params = []
            for col, val in updates.items():
                set_parts.append(f"{col} = %s")
                params.append(val)
            if updates.get("status") in ("completed", "failed", "timed_out"):
                set_parts.append("completed_at = NOW()")
            params.append(run_id)
            cur.execute(
                f"UPDATE capability_runs SET {', '.join(set_parts)} WHERE id = %s",
                params,
            )
            conn.commit()
            cur.close()
            return True
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"update_capability_run failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    def insert_decomposition_log(self, baker_task_id=None, original_task="",
                                  domain=None, sub_tasks=None,
                                  capabilities_used=None) -> Optional[int]:
        """INSERT a decomposition_log record. Returns ID."""
        import json as _json
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO decomposition_log
                   (baker_task_id, original_task, domain, sub_tasks, capabilities_used)
                   VALUES (%s, %s, %s, %s, %s)
                   RETURNING id""",
                (baker_task_id, original_task, domain,
                 _json.dumps(sub_tasks or []), _json.dumps(capabilities_used or [])),
            )
            log_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            return log_id
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"insert_decomposition_log failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def get_capability_sets(self, active_only: bool = True) -> list:
        """Get all capability_sets rows as dicts."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if active_only:
                cur.execute("SELECT * FROM capability_sets WHERE active = TRUE ORDER BY slug")
            else:
                cur.execute("SELECT * FROM capability_sets ORDER BY slug")
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        except Exception as e:
            logger.warning(f"get_capability_sets failed (non-fatal): {e}")
            return []
        finally:
            self._put_conn(conn)

    def get_capability_runs(self, capability_slug: str = None,
                            limit: int = 20) -> list:
        """Get recent capability runs. Optional filter by slug."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if capability_slug:
                cur.execute(
                    """SELECT * FROM capability_runs
                       WHERE capability_slug = %s
                       ORDER BY created_at DESC LIMIT %s""",
                    (capability_slug, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM capability_runs ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        except Exception as e:
            logger.warning(f"get_capability_runs failed (non-fatal): {e}")
            return []
        finally:
            self._put_conn(conn)

    def get_decomposition_logs(self, domain: str = None,
                                limit: int = 20) -> list:
        """Get recent decomposition logs. Optional filter by domain."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if domain:
                cur.execute(
                    """SELECT * FROM decomposition_log
                       WHERE domain = %s
                       ORDER BY created_at DESC LIMIT %s""",
                    (domain, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM decomposition_log ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        except Exception as e:
            logger.warning(f"get_decomposition_logs failed (non-fatal): {e}")
            return []
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # RETRIEVAL-FIX-1: Matter Registry
    # -------------------------------------------------------

    def _ensure_matter_registry_table(self):
        """Create matter_registry table + seed data if empty. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS matter_registry (
                    id              SERIAL PRIMARY KEY,
                    matter_name     TEXT NOT NULL UNIQUE,
                    description     TEXT,
                    people          TEXT[] NOT NULL DEFAULT '{}',
                    keywords        TEXT[] NOT NULL DEFAULT '{}',
                    projects        TEXT[] NOT NULL DEFAULT '{}',
                    status          TEXT NOT NULL DEFAULT 'active',
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_matter_registry_name "
                "ON matter_registry(matter_name)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_matter_registry_status "
                "ON matter_registry(status)"
            )

            # Seed data — only if table is empty (first deploy)
            cur.execute("SELECT COUNT(*) FROM matter_registry")
            count = cur.fetchone()[0]
            if count == 0:
                self._seed_matter_registry(cur)

            conn.commit()
            cur.close()
            logger.info("matter_registry table verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure matter_registry table: {e}")
        finally:
            self._put_conn(conn)

    def _seed_matter_registry(self, cur):
        """Insert initial matters. Called once on first deploy."""
        seed = [
            {
                "matter_name": "Cupial",
                "description": "Handover & defect dispute on MOVIE Residences Tops 4, 5, 6, 18. Escrow release. HEC commission.",
                "people": ["Hassa", "Ofenheimer", "Caroly", "Cupial-Zgryzek", "Groschl", "Leitner"],
                "keywords": ["cupial", "kupial", "snagging", "escrow", "defect", "top 4", "top 5", "top 6", "top 18", "handover", "movie residences", "hec commission"],
                "projects": ["hagenauer"],
            },
            {
                "matter_name": "Hagenauer",
                "description": "Construction project — permit, final account, defect rectification.",
                "people": ["Hagenauer", "Ofenheimer", "Arndt"],
                "keywords": ["hagenauer", "permit", "baubewilligung", "final account", "schlussrechnung"],
                "projects": ["hagenauer"],
            },
            {
                "matter_name": "Wertheimer LP",
                "description": "Chanel family office LP opportunity — fundraise, SFO structure.",
                "people": ["Wertheimer", "Christophe"],
                "keywords": ["wertheimer", "sfo", "chanel", "lp", "fundraise", "family office"],
                "projects": ["brisen-lp"],
            },
            {
                "matter_name": "FX Mayr",
                "description": "FX Mayr acquisition — Lilienmatt, MRCI partnership.",
                "people": ["Oskolkov", "Buchwalder", "Edita"],
                "keywords": ["fx mayr", "acquisition", "lilienmatt", "mrci"],
                "projects": ["fx-mayr"],
            },
            {
                "matter_name": "ClaimsMax",
                "description": "Claims management AI — Philip's project, UBM strategy, Jurkovic pitch.",
                "people": ["Philip"],
                "keywords": ["claimsmax", "claims", "ubm", "jurkovic"],
                "projects": ["claimsmax"],
            },
        ]
        for m in seed:
            cur.execute(
                """INSERT INTO matter_registry
                   (matter_name, description, people, keywords, projects)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (matter_name) DO NOTHING""",
                (m["matter_name"], m["description"],
                 m["people"], m["keywords"], m["projects"]),
            )
        logger.info(f"Seeded {len(seed)} matters into matter_registry")

    # -- Matter Registry CRUD --

    def create_matter(self, matter_name: str, description: str = None,
                      people: list = None, keywords: list = None,
                      projects: list = None) -> Optional[int]:
        """Insert a new matter. Returns matter ID on success."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO matter_registry
                   (matter_name, description, people, keywords, projects)
                   VALUES (%s, %s, %s, %s, %s)
                   RETURNING id""",
                (matter_name, description,
                 people or [], keywords or [], projects or []),
            )
            matter_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            logger.info(f"Created matter '{matter_name}' (id={matter_id})")
            return matter_id
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"Failed to create matter '{matter_name}': {e}")
            return None
        finally:
            self._put_conn(conn)

    def update_matter(self, matter_id: int, **kwargs) -> bool:
        """Update a matter by ID. Allowed fields: matter_name, description,
        people, keywords, projects, status. Returns True on success."""
        allowed = {"matter_name", "description", "people", "keywords",
                    "projects", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return False
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            set_parts = []
            params = []
            for col, val in updates.items():
                set_parts.append(f"{col} = %s")
                params.append(val)
            set_parts.append("updated_at = NOW()")
            params.append(matter_id)

            cur.execute(
                f"UPDATE matter_registry SET {', '.join(set_parts)} WHERE id = %s",
                params,
            )
            conn.commit()
            affected = cur.rowcount
            cur.close()
            return affected > 0
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"Failed to update matter id={matter_id}: {e}")
            return False
        finally:
            self._put_conn(conn)

    def get_matters(self, status: str = "active") -> list:
        """Get all matters, optionally filtered by status. Returns list of dicts."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT id, matter_name, description, people, keywords,
                          projects, status, created_at, updated_at
                   FROM matter_registry
                   WHERE status = %s
                   ORDER BY matter_name""",
                (status,),
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        except Exception as e:
            logger.warning(f"get_matters failed (non-fatal): {e}")
            return []
        finally:
            self._put_conn(conn)

    def get_matter_by_name(self, name: str) -> Optional[dict]:
        """Look up a single matter by exact name (case-insensitive)."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT id, matter_name, description, people, keywords,
                          projects, status, created_at, updated_at
                   FROM matter_registry
                   WHERE LOWER(matter_name) = LOWER(%s)""",
                (name,),
            )
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None
        except Exception as e:
            logger.warning(f"get_matter_by_name failed (non-fatal): {e}")
            return None
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
                    priority: str = None,
                    domain: str = None, urgency_score: int = None,
                    tier: int = None, mode: str = None,
                    scoring_reasoning: str = None) -> Optional[int]:
        """Log every pipeline execution. Returns trigger_log ID.
        DECISION-ENGINE-1A: Now includes scored fields."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping log_trigger")
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO trigger_log
                    (type, source_id, content, contact_id, priority, received_at,
                     domain, urgency_score, tier, mode, scoring_reasoning)
                VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (trigger_type, source_id, content,
                 contact_id if contact_id else None,
                 priority, domain, urgency_score, tier, mode,
                 scoring_reasoning),
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

    def _ensure_alerts_v3_columns(self):
        """Add V3 columns to alerts table if missing. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            for col, defn in [
                ("matter_slug", "TEXT"),
                ("exit_reason", "TEXT"),
                ("tags", "JSONB DEFAULT '[]'::jsonb"),
                ("board_status", "TEXT DEFAULT 'new'"),
                ("travel_date", "DATE"),
                ("source_id", "TEXT"),
            ]:
                cur.execute(f"""
                    ALTER TABLE alerts ADD COLUMN IF NOT EXISTS {col} {defn}
                """)
            conn.commit()
            cur.close()
            logger.info("alerts V3 columns verified")
        except Exception as e:
            conn.rollback()
            logger.warning(f"Could not ensure alerts V3 columns: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_alert_threads_table(self):
        """Create alert_threads table if missing. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alert_threads (
                    id SERIAL PRIMARY KEY,
                    alert_id INTEGER REFERENCES alerts(id) NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_alert_threads_alert ON alert_threads(alert_id)
            """)
            conn.commit()
            cur.close()
            logger.info("alert_threads table verified")
        except Exception as e:
            conn.rollback()
            logger.warning(f"Could not ensure alert_threads table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_alert_artifacts_table(self):
        """Create alert_artifacts table if missing. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alert_artifacts (
                    id SERIAL PRIMARY KEY,
                    alert_id INTEGER REFERENCES alerts(id),
                    matter_slug TEXT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    format TEXT DEFAULT 'md',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_alert_artifacts_matter ON alert_artifacts(matter_slug)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_alert_artifacts_alert ON alert_artifacts(alert_id)")
            conn.commit()
            cur.close()
            logger.info("alert_artifacts table verified")
        except Exception as e:
            conn.rollback()
            logger.warning(f"Could not ensure alert_artifacts table: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Phase 3C: Commitments table
    # -------------------------------------------------------

    def _ensure_commitments_table(self):
        """Create commitments table if missing. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS commitments (
                    id SERIAL PRIMARY KEY,
                    description TEXT NOT NULL,
                    assigned_to TEXT,
                    assigned_by TEXT DEFAULT 'director',
                    due_date DATE,
                    source_type TEXT NOT NULL,
                    source_id TEXT,
                    source_context TEXT,
                    matter_slug TEXT,
                    status TEXT DEFAULT 'open',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_commitments_status ON commitments(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_commitments_due ON commitments(due_date)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_commitments_assigned ON commitments(assigned_to)")
            conn.commit()
            cur.close()
            logger.info("commitments table verified")
        except Exception as e:
            conn.rollback()
            logger.warning(f"Could not ensure commitments table: {e}")
        finally:
            self._put_conn(conn)

    def store_commitment(self, description: str, assigned_to: str = None,
                         assigned_by: str = "director", due_date=None,
                         source_type: str = "", source_id: str = "",
                         source_context: str = "", matter_slug: str = None) -> Optional[int]:
        """Insert a commitment. Returns commitment ID. Dedup on source_id + description."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            # Dedup check: same source_id and similar description
            if source_id:
                cur.execute(
                    "SELECT id FROM commitments WHERE source_id = %s AND LOWER(description) = LOWER(%s) LIMIT 1",
                    (source_id, description),
                )
                if cur.fetchone():
                    cur.close()
                    return None  # duplicate
            cur.execute(
                """
                INSERT INTO commitments (description, assigned_to, assigned_by, due_date,
                    source_type, source_id, source_context, matter_slug, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'open')
                RETURNING id
                """,
                (description, assigned_to, assigned_by, due_date,
                 source_type, source_id, source_context, matter_slug),
            )
            cid = cur.fetchone()[0]
            conn.commit()
            cur.close()
            logger.info(f"Commitment #{cid} stored: '{description[:60]}' assigned_to={assigned_to}")
            return cid
        except Exception as e:
            conn.rollback()
            logger.error(f"store_commitment failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def create_alert(self, tier: int, title: str, body: str = None,
                     action_required: bool = False, trigger_id: int = None,
                     contact_id: str = None, deal_id: str = None,
                     structured_actions: dict = None,
                     matter_slug: str = None, tags: list = None,
                     source: str = None, source_id: str = None) -> Optional[int]:
        """Insert into alerts table. Returns alert ID.
        source: identifies the subsystem that created this alert
            (e.g. 'email_trigger', 'calendar_prep', 'vip_sla', 'deadline_cadence',
             'commitment_check', 'rss_intelligence', 'calendar_protection', 'pipeline').
        source_id: optional dedup key — if set, checked before insert to prevent duplicates.
        """
        if source_id:
            if self.alert_source_id_exists(source, source_id):
                logger.info(f"Alert dedup: source_id {source_id} already exists — skipping")
                return None
        # T1 daily cap: max 5 T1 alerts per day — excess auto-downgraded to T2
        if tier == 1:
            try:
                _cap_conn = self._get_conn()
                if _cap_conn:
                    try:
                        _cap_cur = _cap_conn.cursor()
                        _cap_cur.execute("SELECT COUNT(*) FROM alerts WHERE tier = 1 AND status = 'pending' AND created_at >= CURRENT_DATE")
                        t1_today = _cap_cur.fetchone()[0]
                        _cap_cur.close()
                    finally:
                        self._put_conn(_cap_conn)
                    if t1_today >= 5:
                        logger.info(f"T1 daily cap reached ({t1_today}/5) — downgrading to T2: {title[:60]}")
                        tier = 2
            except Exception:
                pass  # cap check failed — proceed with original tier
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping create_alert")
            return None
        try:
            cur = conn.cursor()
            import json as _json
            sa_json = _json.dumps(structured_actions) if structured_actions else None
            tags_json = _json.dumps(tags) if tags else '[]'
            cur.execute(
                """
                INSERT INTO alerts (tier, title, body, action_required,
                    trigger_id, contact_id, deal_id, structured_actions,
                    matter_slug, tags, source, source_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (tier, title, body, action_required,
                 trigger_id, contact_id if contact_id else None,
                 deal_id if deal_id else None, sa_json, matter_slug, tags_json,
                 source, source_id),
            )
            alert_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            logger.info(f"Created alert #{alert_id}: tier={tier}, matter={matter_slug}, '{title}'")
            # T1: Invalidate morning narrative cache + push to WhatsApp
            if tier == 1:
                try:
                    from outputs.dashboard import invalidate_morning_narrative
                    invalidate_morning_narrative()
                except Exception:
                    pass  # dashboard module may not be loaded in all contexts
                # Push T1 alerts to Director via WhatsApp (always reachable)
                try:
                    from outputs.whatsapp_sender import send_whatsapp
                    wa_text = f"*T1 Alert:* {title}"
                    if body:
                        wa_text += f"\n{body[:300]}"
                    send_whatsapp(wa_text)
                except Exception as e:
                    logger.warning(f"T1 WhatsApp push failed (non-fatal): {e}")
            return alert_id
        except Exception as e:
            conn.rollback()
            logger.error(f"create_alert failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def alert_source_id_exists(self, source: str, source_id: str) -> bool:
        """Check if an alert with this source + source_id already exists (for dedup)."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM alerts WHERE source = %s AND source_id = %s LIMIT 1",
                (source, source_id),
            )
            exists = cur.fetchone() is not None
            cur.close()
            return exists
        except Exception as e:
            logger.warning(f"alert_source_id_exists check failed: {e}")
            return False
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
        """Mark alert as resolved (real issue, handled)."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE alerts SET status = 'resolved', exit_reason = 'resolved', resolved_at = NOW() WHERE id = %s",
                (alert_id,),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            conn.rollback()
            logger.error(f"resolve_alert failed for #{alert_id}: {e}")
        finally:
            self._put_conn(conn)

    def dismiss_alert(self, alert_id: int):
        """Mark alert as dismissed (noise, not relevant)."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE alerts SET status = 'dismissed', exit_reason = 'dismissed', resolved_at = NOW() WHERE id = %s",
                (alert_id,),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            conn.rollback()
            logger.error(f"dismiss_alert failed for #{alert_id}: {e}")
        finally:
            self._put_conn(conn)

    def update_alert_structured_actions(self, alert_id: int, structured_actions: dict):
        """Store structured actions JSON on an existing alert."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            import json as _json
            cur = conn.cursor()
            cur.execute(
                "UPDATE alerts SET structured_actions = %s WHERE id = %s",
                (_json.dumps(structured_actions), alert_id),
            )
            conn.commit()
            cur.close()
            logger.info(f"Updated structured_actions for alert #{alert_id}")
        except Exception as e:
            conn.rollback()
            logger.error(f"update_alert_structured_actions failed for #{alert_id}: {e}")
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

    # Voyage-3 max: 32K tokens per text (~120K chars).
    _EMBED_CHAR_LIMIT = 120_000

    def _embed(self, text: str) -> list[float]:
        """Embed a single text that fits within Voyage-3's 32K token limit."""
        if len(text) > self._EMBED_CHAR_LIMIT:
            text = text[:self._EMBED_CHAR_LIMIT]
        result = self.voyage.embed(
            texts=[text],
            model=config.voyage.model,
            input_type="document",
        )
        return result.embeddings[0]

    @staticmethod
    def _chunk_text(text: str, max_tokens: int = 500, overlap_tokens: int = 50) -> list[str]:
        """Split text into overlapping chunks (~500 tokens each).
        Same algorithm as bulk_ingest.chunk_text, inlined to avoid import side-effects."""
        est_tokens = len(text) // 4
        if est_tokens <= max_tokens:
            return [text]

        max_chars = max_tokens * 4
        overlap_chars = overlap_tokens * 4
        chunks = []
        start = 0

        while start < len(text):
            end = start + max_chars
            if end < len(text):
                search_region = text[start + (max_chars // 2):end]
                for delim in [". ", ".\n", "?\n", "!\n", "\n\n", "? ", "! "]:
                    last_break = search_region.rfind(delim)
                    if last_break != -1:
                        end = start + (max_chars // 2) + last_break + len(delim)
                        break
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - overlap_chars
            if start <= (end - max_chars):
                start = end - (max_chars // 2)

        return chunks

    def _embed_chunked(self, text: str) -> list[tuple[str, list[float]]]:
        """
        Embed text of any length by chunking first.
        Short texts (<= 32K tokens) get a single embedding (fast path).
        Long texts are split into ~500-token overlapping chunks, each embedded separately.
        Returns list of (chunk_text, vector) tuples.
        """
        chunks = self._chunk_text(text)

        results = []
        for chunk in chunks:
            vector = self._embed(chunk)
            results.append((chunk, vector))
        return results

    def store_interaction(
        self,
        trigger_type: str,
        trigger_content: str,
        response_analysis: str,
        contact_name: Optional[str] = None,
        full_content: Optional[str] = None,
    ):
        """Store a Sentinel interaction as vectors in Qdrant.
        Short content → single vector. Long content → chunked into multiple vectors."""
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
            embed_text = full_content or snippet_text
            base_payload = {
                "trigger_type": trigger_type,
                "contact": contact_name or "unknown",
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            chunk_pairs = self._embed_chunked(embed_text)
            base_id = int(datetime.now(timezone.utc).timestamp() * 1000)
            points = []

            for i, (chunk, vector) in enumerate(chunk_pairs):
                payload = {
                    **base_payload,
                    "text": chunk,
                    "chunk_index": i,
                    "total_chunks": len(chunk_pairs),
                }
                if i == 0 and full_content:
                    payload["full_content"] = full_content
                points.append(PointStruct(
                    id=base_id + i,
                    vector=vector,
                    payload=payload,
                ))

            self.qdrant.upsert(
                collection_name=collection,
                points=points,
            )
            logger.info(
                f"Stored interaction in {collection}: "
                f"{len(points)} chunk(s), base_id={base_id}"
            )
        except Exception as e:
            logger.warning(f"store_interaction failed (non-fatal): {e}")

    # -------------------------------------------------------
    # Deep Analysis: store document chunks + catalogue record
    # -------------------------------------------------------

    def store_document(self, content, metadata, collection="baker-documents"):
        """Embed and store a document in Qdrant.
        Short content → single vector. Long content → chunked into multiple vectors."""
        try:
            chunk_pairs = self._embed_chunked(content)
            points = []

            for i, (chunk, vector) in enumerate(chunk_pairs):
                point_id = str(uuid.uuid4())
                chunk_payload = {
                    "content": chunk,
                    **metadata,
                    "chunk_index": i,
                    "total_chunks": len(chunk_pairs),
                }
                points.append(PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=chunk_payload,
                ))

            self.qdrant.upsert(
                collection_name=collection,
                points=points,
            )
            if len(points) > 1:
                logger.info(
                    f"Stored {len(points)} chunks in {collection} "
                    f"(content: {len(content):,} chars)"
                )
        except Exception as e:
            logger.error(f"Failed to store document in {collection}: {e}")

    def log_deep_analysis(self, analysis_id, topic, source_documents, prompt,
                          token_count=0, chunk_count=0, cost_usd=0,
                          analysis_text=""):
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
                     analysis_text, token_count, chunk_count, cost_usd)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (analysis_id) DO UPDATE SET
                    topic = EXCLUDED.topic,
                    analysis_text = EXCLUDED.analysis_text,
                    token_count = EXCLUDED.token_count,
                    chunk_count = EXCLUDED.chunk_count,
                    cost_usd = EXCLUDED.cost_usd
            """, (analysis_id, topic, json.dumps(source_documents),
                  prompt, analysis_text, token_count, chunk_count, cost_usd))
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
                    answer TEXT,
                    answer_length INTEGER DEFAULT 0,
                    project TEXT DEFAULT 'general',
                    chunk_count INTEGER DEFAULT 1,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            # ARCH-5: Add answer column to existing tables
            cur.execute("""
                ALTER TABLE conversation_memory
                ADD COLUMN IF NOT EXISTS answer TEXT
            """)
            conn.commit()
            cur.close()
            logger.info("conversation_memory table verified")
        except Exception as e:
            logger.warning(f"Could not ensure conversation_memory table: {e}")
        finally:
            self._put_conn(conn)

    def log_conversation(self, question, answer="", answer_length=0, project="general", chunk_count=1):
        """Catalogue a scan conversation in PostgreSQL."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping log_conversation")
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO conversation_memory
                    (question, answer, answer_length, project, chunk_count)
                VALUES (%s, %s, %s, %s, %s)
            """, (question, answer, answer_length, project, chunk_count))
            conn.commit()
            cur.close()
        except Exception as e:
            logger.error(f"Failed to log conversation: {e}")
        finally:
            self._put_conn(conn)

    def get_recent_conversations(self, limit: int = 5) -> list:
        """
        WA-SEND-1: Fetch most recent conversation turns for short-term memory.
        Returns list of dicts: [{question, answer, created_at}, ...] newest-first.
        """
        conn = self._get_conn()
        if not conn:
            return []
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT question, answer, created_at
                FROM conversation_memory
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        except Exception as e:
            logger.warning(f"get_recent_conversations failed: {e}")
            return []
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
