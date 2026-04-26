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


def _titles_similar(t1: str, t2: str, threshold: int = 3) -> bool:
    """ALERT-DEDUP-2: Check if two alert titles are about the same topic.
    Returns True if they share >= threshold significant words (len > 3, not stopwords)."""
    _stopwords = {'the', 'this', 'that', 'from', 'with', 'about', 'your', 'baker',
                  'alert', 'action', 'required', 'update', 'status', 'new', 'follow'}
    words1 = set(w.lower() for w in (t1 or '').split() if len(w) > 3 and w.lower() not in _stopwords)
    words2 = set(w.lower() for w in (t2 or '').split() if len(w) > 3 and w.lower() not in _stopwords)
    overlap = len(words1 & words2)
    return overlap >= threshold


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

        # WHATSAPP-LID-RESOLUTION-1: Ensure LID mapping cache table exists
        self._ensure_whatsapp_lid_map_table()

        # SLACK-STRUCTURED-1: Ensure slack_messages table exists
        self._ensure_slack_messages_table()

        # Ensure baker-slack Qdrant collection exists
        self._ensure_collection("baker-slack", size=1024)

        # Ensure insights table exists (INSIGHT-1)
        self._ensure_insights_table()

        # Ensure baker-health Qdrant collection exists (used by health data if re-enabled)
        self._ensure_collection("baker-health", size=1024)

        # Ensure baker-browser Qdrant collection exists (BROWSER-1)
        self._ensure_collection("baker-browser", size=1024)

        # CORRECTION-MEMORY-1 Phase 2: Positive task examples for episodic retrieval
        self._ensure_collection("baker-task-examples", size=1024)

        # STEP1C: Ensure baker_tasks table exists
        self._ensure_baker_tasks_table()

        # DECISION-ENGINE-1A: Ensure decision engine columns exist
        self._ensure_decision_engine_columns()

        # RETRIEVAL-FIX-1: Ensure matter_registry table exists
        self._ensure_matter_registry_table()

        # STEP3: Ensure director_preferences table + VIP profile columns
        self._ensure_director_preferences_table()
        self._ensure_vip_profile_columns()

        # BRANCH_HYGIENE_1: audit log for stale-branch deletions
        self._ensure_branch_hygiene_log_table()

        # AGENT-FRAMEWORK-1: Ensure capability framework tables
        self._ensure_capability_sets_table()
        self._ensure_capability_runs_table()
        self._ensure_decomposition_log_table()
        self._ensure_baker_tasks_capability_columns()
        self._ensure_baker_tasks_complexity_columns()
        self._ensure_alerts_v3_columns()
        self._ensure_alert_threads_table()
        self._ensure_alert_artifacts_table()
        self._ensure_commitments_table()

        # SPECIALIST-UPGRADE-1A/1B: Document intelligence
        self._ensure_documents_table()
        self._ensure_document_extractions_table()
        self._ensure_doc_pipeline_jobs_table()
        self._ensure_baker_insights_table()

        # BRIEF_AI_HEAD_WEEKLY_AUDIT_1: Weekly AI Head self-audit records
        self._ensure_ai_head_audits_table()

        # BRIEF_AUDIT_SENTINEL_1: Persistent APScheduler job execution log
        self._ensure_scheduler_executions_table()

        # BRIEF_PM_SIDEBAR_STATE_WRITE_1 D4: backfill idempotency guard
        self._ensure_pm_backfill_processed_table()

        # CORRECTION-MEMORY-1: Learned corrections from Director feedback
        self._ensure_baker_corrections_table()

        # PHASE-4A: Cost monitor + agent observability tables
        self._ensure_cost_and_metrics_tables()

        # E3: Web Push subscriptions
        self._ensure_push_subscriptions_table()

        # TRIP-INTELLIGENCE-1: Trip lifecycle tables
        self._ensure_trips_table()
        self._ensure_trip_contacts_table()
        self._seed_location_preferences()

        # MEETINGS-DETECT-1: Detected meetings from Director messages
        self._ensure_detected_meetings_table()

        # WEALTH-MANAGER: Wealth tracking tables
        self._ensure_wealth_tables()

        # PM-FACTORY: Generic persistent state for all PM capabilities
        self._ensure_pm_project_state_table()

        # PM-KNOWLEDGE-ARCH-1: Pending insights for PM knowledge bases
        self._ensure_pm_pending_insights_table()

        # CROSS-PM-SIGNALS: Inter-PM communication bus
        self._ensure_pm_cross_signals_table()

        # CORTEX-PHASE-1A: Wiki infrastructure
        self._ensure_wiki_pages_table()
        self._ensure_cortex_config_table()

        # CORTEX-PHASE-2A: Event bus
        self._ensure_cortex_events_table()

        # CORTEX-PHASE-2B: Qdrant dedup collection
        self._ensure_cortex_obligations_collection()

        # KBL-A: infrastructure schema (§5 of KBL-A brief).
        # DDL for kbl_cost_ledger / kbl_log lives in
        # migrations/20260419_add_kbl_cost_ledger_and_kbl_log.sql — no longer
        # ensured from Python (lesson #37).
        self._ensure_signal_queue_base()
        self._ensure_signal_queue_additions()
        self._ensure_kbl_runtime_state()
        self._ensure_kbl_alert_dedupe()
        self._ensure_gold_promote_queue()

        # GOLD_COMMENT_WORKFLOW_1: weekly audit + write-failure tables
        self._ensure_gold_audits_table()
        self._ensure_gold_write_failures_table()

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
            # TAGGING-OVERHAUL-1: content_class for pre-Haiku triage
            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_class VARCHAR(20) DEFAULT 'document'")
            # WEALTH-MANAGER: owner column for access control (dimitry/edita/shared)
            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner VARCHAR(20) DEFAULT 'shared'")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents(owner)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_content_class ON documents(content_class)")
            # DOCUMENT-DEDUP-1: content_hash for text-based dedup
            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash)")
            # FTS: tsvector column + GIN index for full-text search
            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS search_vector tsvector")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_fts ON documents USING GIN(search_vector)")
            # Auto-populate search_vector on INSERT/UPDATE via trigger
            cur.execute("""
                CREATE OR REPLACE FUNCTION documents_search_vector_update() RETURNS trigger AS $$
                BEGIN
                    NEW.search_vector := to_tsvector('simple', COALESCE(NEW.full_text, ''));
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
            """)
            cur.execute("""
                DO $$ BEGIN
                    CREATE TRIGGER documents_search_vector_trigger
                    BEFORE INSERT OR UPDATE OF full_text ON documents
                    FOR EACH ROW EXECUTE FUNCTION documents_search_vector_update();
                EXCEPTION WHEN duplicate_object THEN NULL;
                END $$
            """)
            conn.commit()
            cur.close()
            logger.info("documents table verified (with FTS index)")
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
                            token_count: int = 0, owner: str = "shared"):
        """Store full document text in PostgreSQL. Returns document ID or None.
        DOCUMENT-DEDUP-1: Content-hash dedup on extracted text (SHA-256 of first 10K chars).
        """
        conn = self._get_conn()
        if not conn:
            return None
        try:
            # Compute content hash for dedup
            import hashlib
            content_hash = None
            if full_text and len(full_text.strip()) > 30:
                normalized = full_text[:10000].strip().lower()
                content_hash = hashlib.sha256(normalized.encode()).hexdigest()

                # Check for existing document with same content (different file_hash but same text)
                cur = conn.cursor()
                cur.execute("SELECT id FROM documents WHERE content_hash = %s LIMIT 1", (content_hash,))
                existing = cur.fetchone()
                cur.close()
                if existing:
                    logger.info(f"Document dedup: skipping duplicate content (hash={content_hash[:16]}, existing id={existing[0]}, file={filename})")
                    return existing[0]

            cur = conn.cursor()
            cur.execute("""
                INSERT INTO documents (source_path, filename, file_hash, full_text, token_count, search_vector, owner, content_hash)
                VALUES (%s, %s, %s, %s, %s, to_tsvector('simple', COALESCE(%s, '')), %s, %s)
                ON CONFLICT (file_hash) DO UPDATE SET
                    source_path = EXCLUDED.source_path,
                    full_text = EXCLUDED.full_text,
                    token_count = EXCLUDED.token_count,
                    search_vector = EXCLUDED.search_vector,
                    owner = COALESCE(EXCLUDED.owner, documents.owner),
                    content_hash = EXCLUDED.content_hash,
                    ingested_at = NOW()
                RETURNING id
            """, (source_path, filename, file_hash, full_text, token_count, full_text, owner, content_hash))
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
            # CROSSLINK-IDEMPOTENT-1B: Dedup existing rows before adding unique constraint
            cur.execute("""
                DELETE FROM document_extractions a USING document_extractions b
                WHERE a.id < b.id
                  AND a.document_id = b.document_id
                  AND a.extraction_type = b.extraction_type
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_extractions_uq
                ON document_extractions(document_id, extraction_type)
            """)
            # EXTRACTION-VALIDATION-1: validated flag for Pydantic-checked rows
            cur.execute("ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS validated BOOLEAN DEFAULT FALSE")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_doc_extractions_validated
                ON document_extractions(validated) WHERE validated = TRUE
            """)
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

    def _ensure_doc_pipeline_jobs_table(self):
        """PIPELINE-JOBQUEUE-1: DB-backed job queue for document pipeline."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS doc_pipeline_jobs (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER NOT NULL REFERENCES documents(id),
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_dpj_status ON doc_pipeline_jobs(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_dpj_doc ON doc_pipeline_jobs(document_id)")
            # Partial unique index: only one pending/running job per document
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_dpj_doc_active
                ON doc_pipeline_jobs(document_id)
                WHERE status IN ('pending', 'running')
            """)
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure doc_pipeline_jobs table: {e}")
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

    def _ensure_ai_head_audits_table(self):
        """BRIEF_AI_HEAD_WEEKLY_AUDIT_1: Weekly self-audit records for AI Head.

        Populated by the embedded_scheduler _ai_head_weekly_audit_job.
        One row per audit run (Mondays 09:00 UTC).
        """
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ai_head_audits (
                    id SERIAL PRIMARY KEY,
                    ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    drift_items JSONB NOT NULL DEFAULT '[]'::jsonb,
                    lesson_patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
                    summary_text TEXT NOT NULL,
                    slack_cockpit_ok BOOLEAN NOT NULL DEFAULT FALSE,
                    slack_dm_ok BOOLEAN NOT NULL DEFAULT FALSE,
                    mirror_last_pull_at TIMESTAMPTZ,
                    mirror_head_sha TEXT
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_head_audits_ran_at "
                "ON ai_head_audits(ran_at DESC)"
            )
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure ai_head_audits table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_gold_audits_table(self):
        """GOLD_COMMENT_WORKFLOW_1: weekly Gold corpus audit records.

        Populated by orchestrator/gold_audit_job._gold_audit_sentinel_job.
        One row per audit run (Mondays 09:30 UTC).
        """
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gold_audits (
                    id            SERIAL PRIMARY KEY,
                    ran_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    issues_count  INT NOT NULL DEFAULT 0,
                    payload_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_gold_audits_ran_at "
                "ON gold_audits(ran_at DESC)"
            )
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure gold_audits table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_gold_write_failures_table(self):
        """GOLD_COMMENT_WORKFLOW_1: failure log for gold_writer.append guards."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gold_write_failures (
                    id            SERIAL PRIMARY KEY,
                    attempted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    target_path   TEXT NOT NULL,
                    error         TEXT NOT NULL,
                    caller_stack  TEXT,
                    payload_jsonb JSONB DEFAULT '{}'::jsonb
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_gold_write_failures_attempted_at "
                "ON gold_write_failures(attempted_at DESC)"
            )
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure gold_write_failures table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_scheduler_executions_table(self):
        """BRIEF_AUDIT_SENTINEL_1: Persistent log of APScheduler job executions.

        Populated by the extended embedded_scheduler._job_listener on every
        EVENT_JOB_EXECUTED / EVENT_JOB_ERROR. One row per fire. Used by
        ai_head_audit_sentinel (Mon 10:00 UTC) to verify weekly audit fired.

        Retention: 90-day delete in nightly cleanup (Phase 2 brief; not this one).
        """
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scheduler_executions (
                    id SERIAL PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    fired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ,
                    status TEXT NOT NULL,
                    error_msg TEXT,
                    outputs_summary JSONB NOT NULL DEFAULT '{}'::jsonb
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_scheduler_executions_job_fired "
                "ON scheduler_executions(job_id, fired_at DESC)"
            )
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure scheduler_executions table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_pm_backfill_processed_table(self):
        """BRIEF_PM_SIDEBAR_STATE_WRITE_1 D4: idempotency guard for
        scripts/backfill_pm_state.py.

        Tracks which (pm_slug, conversation_id) pairs have been processed so
        repeat runs of the backfill script are no-ops. PK enforces the
        uniqueness; ON CONFLICT DO NOTHING on insert avoids races when two
        backfill runs overlap.
        """
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pm_backfill_processed (
                    pm_slug TEXT NOT NULL,
                    conversation_id INTEGER NOT NULL,
                    processed_at TIMESTAMPTZ DEFAULT NOW(),
                    mutation_source TEXT,
                    PRIMARY KEY (pm_slug, conversation_id)
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_pm_backfill_processed_pm "
                "ON pm_backfill_processed(pm_slug)"
            )
            conn.commit()
            cur.close()
            logger.info("pm_backfill_processed table verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure pm_backfill_processed table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_baker_corrections_table(self):
        """CORRECTION-MEMORY-1: Learned corrections from Director feedback.
        Anti-bloat: max 5 per capability, 90-day expiry, retrieval tracking."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS baker_corrections (
                    id SERIAL PRIMARY KEY,
                    baker_task_id INTEGER NOT NULL,
                    capability_slug VARCHAR(50),
                    applies_to VARCHAR(50) NOT NULL DEFAULT 'capability',
                    correction_type VARCHAR(20) NOT NULL,
                    director_comment TEXT,
                    learned_rule TEXT NOT NULL,
                    matter_slug VARCHAR(200),
                    retrieval_count INTEGER DEFAULT 0,
                    last_retrieved_at TIMESTAMPTZ,
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '90 days')
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_baker_corrections_slug ON baker_corrections(capability_slug)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_baker_corrections_active ON baker_corrections(active) WHERE active = TRUE")
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure baker_corrections table: {e}")
        finally:
            self._put_conn(conn)

    def store_correction(self, baker_task_id: int, capability_slug: str,
                         correction_type: str, director_comment: str,
                         learned_rule: str, matter_slug: str = None,
                         applies_to: str = "capability") -> bool:
        """Store a learned correction. Enforces max 5 active per capability."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            # Anti-bloat: cap at 5 active corrections per capability.
            # Archive least-used when exceeded.
            cur.execute("""
                SELECT id FROM baker_corrections
                WHERE capability_slug = %s AND active = TRUE
                ORDER BY retrieval_count ASC, created_at ASC
            """, (capability_slug,))
            existing = cur.fetchall()
            if len(existing) >= 5:
                archive_id = existing[0][0]
                cur.execute(
                    "UPDATE baker_corrections SET active = FALSE WHERE id = %s",
                    (archive_id,),
                )
                logger.info(f"Archived correction #{archive_id} (cap 5 per capability)")

            cur.execute("""
                INSERT INTO baker_corrections
                    (baker_task_id, capability_slug, applies_to, correction_type,
                     director_comment, learned_rule, matter_slug)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (baker_task_id, capability_slug, applies_to, correction_type,
                  director_comment, learned_rule, matter_slug))
            conn.commit()
            cur.close()
            logger.info(
                f"Stored correction for {capability_slug} from task #{baker_task_id}: "
                f"{learned_rule[:80]}"
            )
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"store_correction failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    def get_relevant_corrections(self, capability_slug: str, limit: int = 3) -> list:
        """Retrieve active corrections for a capability (+ global ones).
        Updates retrieval stats for decay tracking."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, learned_rule, matter_slug, correction_type, applies_to
                FROM baker_corrections
                WHERE active = TRUE
                  AND (expires_at IS NULL OR expires_at > NOW())
                  AND (capability_slug = %s OR applies_to = 'all')
                ORDER BY
                    CASE WHEN applies_to = 'all' THEN 0 ELSE 1 END,
                    retrieval_count DESC,
                    created_at DESC
                LIMIT %s
            """, (capability_slug, limit))
            rows = cur.fetchall()

            # Update retrieval stats — frequently used corrections survive longer
            if rows:
                ids = [r[0] for r in rows]
                cur.execute("""
                    UPDATE baker_corrections
                    SET retrieval_count = retrieval_count + 1,
                        last_retrieved_at = NOW()
                    WHERE id = ANY(%s)
                """, (ids,))
                conn.commit()

            cur.close()
            return [
                {"id": r[0], "learned_rule": r[1], "matter_slug": r[2],
                 "correction_type": r[3], "applies_to": r[4]}
                for r in rows
            ]
        except Exception as e:
            logger.error(f"get_relevant_corrections failed: {e}")
            return []
        finally:
            self._put_conn(conn)

    def expire_stale_corrections(self) -> int:
        """Archive corrections not retrieved in 90 days. Called by consolidation job."""
        conn = self._get_conn()
        if not conn:
            return 0
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE baker_corrections
                SET active = FALSE
                WHERE active = TRUE
                  AND expires_at IS NOT NULL
                  AND expires_at < NOW()
                RETURNING id
            """)
            expired = cur.fetchall()
            conn.commit()
            cur.close()
            if expired:
                logger.info(f"Expired {len(expired)} stale corrections")
            return len(expired)
        except Exception as e:
            conn.rollback()
            logger.error(f"expire_stale_corrections failed: {e}")
            return 0
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

    def _ensure_branch_hygiene_log_table(self):
        """Create branch_hygiene_log table if it doesn't exist.

        Mirrors migrations/20260426_branch_hygiene_log.sql column-for-column.
        Used by scripts/branch_hygiene.py for L1/L2/L3 audit trail.
        """
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — cannot ensure branch_hygiene_log")
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS branch_hygiene_log (
                    id              BIGSERIAL PRIMARY KEY,
                    branch_name     TEXT        NOT NULL,
                    last_commit_sha TEXT        NOT NULL,
                    deleted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    layer           TEXT        NOT NULL,
                    reason          TEXT        NOT NULL DEFAULT '',
                    age_days        INT         NOT NULL DEFAULT 0,
                    actor           TEXT        NOT NULL DEFAULT 'branch_hygiene'
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_branch_hygiene_log_deleted_at "
                "ON branch_hygiene_log (deleted_at DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_branch_hygiene_log_layer "
                "ON branch_hygiene_log (layer)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_branch_hygiene_log_branch_name "
                "ON branch_hygiene_log (branch_name)"
            )
            conn.commit()
            cur.close()
            logger.info("branch_hygiene_log table verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure branch_hygiene_log table: {e}")
        finally:
            self._put_conn(conn)

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
            conn.rollback()
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
                    sender_name = COALESCE(EXCLUDED.sender_name, email_messages.sender_name),
                    sender_email = COALESCE(EXCLUDED.sender_email, email_messages.sender_email),
                    subject = COALESCE(EXCLUDED.subject, email_messages.subject),
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
            # WHATSAPP-MEDIA-DROPBOX-1: media metadata columns
            cur.execute("""
                ALTER TABLE whatsapp_messages
                ADD COLUMN IF NOT EXISTS media_mimetype TEXT,
                ADD COLUMN IF NOT EXISTS media_dropbox_path TEXT,
                ADD COLUMN IF NOT EXISTS media_size_bytes INTEGER
            """)
            conn.commit()
            cur.close()
            logger.info("whatsapp_messages table verified")
        except Exception as e:
            logger.warning(f"Could not ensure whatsapp_messages table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_whatsapp_lid_map_table(self):
        """WHATSAPP-LID-RESOLUTION-1: Create LID→phone cache table."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS whatsapp_lid_map (
                    lid TEXT PRIMARY KEY,
                    phone TEXT,
                    resolved_at TIMESTAMPTZ DEFAULT NOW(),
                    source TEXT DEFAULT 'api'
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_lid_map_phone
                    ON whatsapp_lid_map (phone)
            """)
            conn.commit()
            cur.close()
            logger.info("whatsapp_lid_map table verified")
        except Exception as e:
            logger.warning(f"Could not ensure whatsapp_lid_map table: {e}")
        finally:
            self._put_conn(conn)

    def store_whatsapp_message(self, msg_id: str, sender: str = None,
                               sender_name: str = None, chat_id: str = None,
                               full_text: str = None, timestamp: str = None,
                               is_director: bool = False,
                               media_mimetype: str = None,
                               media_dropbox_path: str = None,
                               media_size_bytes: int = None) -> bool:
        """Upsert a full WhatsApp message. Returns True on success."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO whatsapp_messages
                    (id, sender, sender_name, chat_id, full_text, timestamp, is_director,
                     media_mimetype, media_dropbox_path, media_size_bytes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    full_text = EXCLUDED.full_text,
                    media_mimetype = COALESCE(EXCLUDED.media_mimetype, whatsapp_messages.media_mimetype),
                    media_dropbox_path = COALESCE(EXCLUDED.media_dropbox_path, whatsapp_messages.media_dropbox_path),
                    media_size_bytes = COALESCE(EXCLUDED.media_size_bytes, whatsapp_messages.media_size_bytes),
                    ingested_at = NOW()
            """, (msg_id, sender, sender_name, chat_id, full_text, timestamp, is_director,
                  media_mimetype, media_dropbox_path, media_size_bytes))
            conn.commit()
            cur.close()
            return True
        except Exception as e:
            logger.error(f"store_whatsapp_message failed: {e}")
            conn.rollback()
            return False
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # LID Resolution Cache (WHATSAPP-LID-RESOLUTION-1)
    # -------------------------------------------------------

    def get_lid_phone(self, lid: str) -> Optional[str]:
        """Look up cached phone number for a @lid ID. Returns @c.us format or None."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("SELECT phone FROM whatsapp_lid_map WHERE lid = %s LIMIT 1", (lid,))
            row = cur.fetchone()
            cur.close()
            return row[0] if row else None
        except Exception as e:
            logger.warning(f"LID cache lookup failed: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            return None
        finally:
            self._put_conn(conn)

    def cache_lid_phone(self, lid: str, phone: str, source: str = "api") -> None:
        """Cache a @lid → @c.us mapping. Upsert — updates if exists."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO whatsapp_lid_map (lid, phone, source, resolved_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (lid) DO UPDATE SET phone = EXCLUDED.phone, resolved_at = NOW()
            """, (lid, phone, source))
            conn.commit()
            cur.close()
        except Exception as e:
            logger.warning(f"LID cache write failed: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Slack Messages (SLACK-STRUCTURED-1)
    # -------------------------------------------------------

    def _ensure_slack_messages_table(self):
        """Create slack_messages table for structured Slack storage."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS slack_messages (
                    id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    channel_name TEXT,
                    user_id TEXT,
                    user_name TEXT,
                    full_text TEXT,
                    thread_ts TEXT,
                    received_at TIMESTAMPTZ,
                    ingested_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_slack_messages_channel ON slack_messages(channel_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_slack_messages_received ON slack_messages(received_at)")
            conn.commit()
            cur.close()
            logger.info("slack_messages table verified")
        except Exception as e:
            logger.warning(f"Could not ensure slack_messages table: {e}")
        finally:
            self._put_conn(conn)

    def store_slack_message(self, msg_id: str, channel_id: str, channel_name: str = None,
                            user_id: str = None, user_name: str = None,
                            full_text: str = None, thread_ts: str = None,
                            received_at=None) -> bool:
        """SLACK-STRUCTURED-1: Upsert a Slack message. Returns True on success."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO slack_messages (id, channel_id, channel_name, user_id, user_name,
                    full_text, thread_ts, received_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (msg_id, channel_id, channel_name, user_id, user_name,
                  full_text, thread_ts, received_at))
            conn.commit()
            cur.close()
            return True
        except Exception as e:
            conn.rollback()
            logger.debug(f"store_slack_message failed: {e}")
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
        "complexity", "complexity_confidence", "complexity_override",
        "complexity_reasoning",
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
            # TRIP-INTELLIGENCE-1: location for Radar card
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS primary_location VARCHAR(100)")
            # F3: Communication cadence tracking
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS avg_inbound_gap_days FLOAT")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS last_inbound_at TIMESTAMPTZ")
            # C1: LinkedIn enrichment data
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS linkedin_url TEXT")
            cur.execute("ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS location VARCHAR(200)")
            # Performance: GIN index for pg_trgm similarity() on name lookups
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_vip_contacts_name_trgm ON vip_contacts USING gin (name gin_trgm_ops)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_vip_contacts_name_lower ON vip_contacts (LOWER(name))")
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
                    direction VARCHAR(20),
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
            # INTERACTION-PIPELINE-1: unique constraint + performance indexes
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_ci_source_ref
                ON contact_interactions (source_ref) WHERE source_ref IS NOT NULL
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_ci_timestamp
                ON contact_interactions (timestamp DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_ci_direction
                ON contact_interactions (contact_id, direction, timestamp DESC)
            """)
            # Migration: widen direction column for 'bidirectional' (was VARCHAR(10))
            cur.execute("""
                ALTER TABLE contact_interactions ALTER COLUMN direction TYPE VARCHAR(20)
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

    # -- INTERACTION-PIPELINE-1: Contact interaction extraction --

    def record_interaction(self, contact_id: int, channel: str, direction: str,
                           timestamp, subject: str = None,
                           source_ref: str = None,
                           sentiment: str = None) -> bool:
        """Insert a contact interaction and update last_contact_date. Idempotent by source_ref."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            # Insert interaction (skip if source_ref already exists)
            cur.execute(
                """INSERT INTO contact_interactions
                   (contact_id, channel, direction, timestamp, subject, source_ref, sentiment)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (contact_id, channel, direction, timestamp,
                 (subject[:200] if subject else None), source_ref, sentiment),
            )
            # Update last_contact_date if this is more recent
            if cur.rowcount > 0:
                cur.execute(
                    """UPDATE vip_contacts
                       SET last_contact_date = GREATEST(last_contact_date, %s)
                       WHERE id = %s""",
                    (timestamp, contact_id),
                )
            conn.commit()
            cur.close()
            return True
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.debug(f"record_interaction failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    def match_contact_by_name(self, name: str, email: str = None,
                               whatsapp_id: str = None) -> Optional[int]:
        """Find a contact_id by name, email, or WhatsApp ID. Returns id or None."""
        if not name and not email and not whatsapp_id:
            return None
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            # Try exact email match first (most reliable)
            if email:
                cur.execute(
                    "SELECT id FROM vip_contacts WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                    (email,),
                )
                row = cur.fetchone()
                if row:
                    cur.close()
                    return row[0]

            # Try WhatsApp ID match
            if whatsapp_id:
                cur.execute(
                    "SELECT id FROM vip_contacts WHERE whatsapp_id = %s LIMIT 1",
                    (whatsapp_id,),
                )
                row = cur.fetchone()
                if row:
                    cur.close()
                    return row[0]

            # Try exact name match
            if name:
                cur.execute(
                    "SELECT id FROM vip_contacts WHERE LOWER(name) = LOWER(%s) LIMIT 1",
                    (name,),
                )
                row = cur.fetchone()
                if row:
                    cur.close()
                    return row[0]

                # Try reversed name ("Vallen Dimitry" → "Dimitry Vallen")
                parts = name.strip().split()
                if len(parts) == 2:
                    reversed_name = f"{parts[1]} {parts[0]}"
                    cur.execute(
                        "SELECT id FROM vip_contacts WHERE LOWER(name) = LOWER(%s) LIMIT 1",
                        (reversed_name,),
                    )
                    row = cur.fetchone()
                    if row:
                        cur.close()
                        return row[0]

                # Try last-name match (only for multi-word names to avoid false positives)
                if len(parts) >= 2:
                    last_name = parts[-1]
                    if len(last_name) >= 3:  # Skip very short last names
                        cur.execute(
                            """SELECT id FROM vip_contacts
                               WHERE LOWER(name) LIKE '%%' || LOWER(%s) || '%%'
                               LIMIT 1""",
                            (last_name,),
                        )
                        row = cur.fetchone()
                        if row:
                            cur.close()
                            return row[0]

            cur.close()
            return None
        except Exception as e:
            logger.debug(f"match_contact_by_name failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def backfill_interactions(self) -> dict:
        """Backfill contact_interactions from email_messages, whatsapp_messages, meeting_transcripts.
        Returns counts per channel. Idempotent (skips existing source_refs)."""
        conn = self._get_conn()
        if not conn:
            return {"error": "no connection"}
        try:
            cur = conn.cursor()
            counts = {}

            # 1. Emails → interactions
            cur.execute("""
                INSERT INTO contact_interactions (contact_id, channel, direction, timestamp, subject, source_ref)
                SELECT
                    vc.id,
                    'email',
                    CASE WHEN LOWER(em.sender_email) LIKE '%%@brisengroup.com' THEN 'outbound' ELSE 'inbound' END,
                    em.received_date,
                    LEFT(em.subject, 200),
                    'email:' || em.message_id
                FROM email_messages em
                JOIN vip_contacts vc ON (
                    LOWER(em.sender_name) = LOWER(vc.name)
                    OR LOWER(em.sender_email) = LOWER(vc.email)
                    OR (POSITION(' ' IN vc.name) > 0 AND LOWER(em.sender_name) = LOWER(
                        SPLIT_PART(vc.name, ' ', 2) || ' ' || SPLIT_PART(vc.name, ' ', 1)
                    ))
                )
                WHERE em.received_date IS NOT NULL
                ON CONFLICT DO NOTHING
            """)
            counts["email"] = cur.rowcount

            # 2. WhatsApp → interactions
            cur.execute("""
                INSERT INTO contact_interactions (contact_id, channel, direction, timestamp, subject, source_ref)
                SELECT
                    vc.id,
                    'whatsapp',
                    CASE WHEN wm.is_director THEN 'outbound' ELSE 'inbound' END,
                    wm.timestamp,
                    LEFT(wm.full_text, 200),
                    'wa:' || wm.id
                FROM whatsapp_messages wm
                JOIN vip_contacts vc ON (
                    LOWER(wm.sender_name) = LOWER(vc.name)
                    OR wm.sender = vc.whatsapp_id
                    OR (vc.whatsapp_id IS NOT NULL AND wm.chat_id = vc.whatsapp_id)
                )
                WHERE wm.timestamp IS NOT NULL
                ON CONFLICT DO NOTHING
            """)
            counts["whatsapp"] = cur.rowcount

            # 3. Meetings → interactions
            cur.execute("""
                INSERT INTO contact_interactions (contact_id, channel, direction, timestamp, subject, source_ref)
                SELECT
                    vc.id,
                    'meeting',
                    'bidirectional',
                    mt.meeting_date,
                    LEFT(mt.title, 200),
                    'meeting:' || mt.id || ':' || vc.id
                FROM meeting_transcripts mt
                JOIN vip_contacts vc ON (
                    LOWER(mt.participants) LIKE '%%' || LOWER(vc.name) || '%%'
                    OR (POSITION(' ' IN vc.name) > 0
                        AND LOWER(mt.participants) LIKE '%%' || LOWER(SPLIT_PART(vc.name, ' ', 2)) || '%%')
                )
                WHERE mt.meeting_date IS NOT NULL
                ON CONFLICT DO NOTHING
            """)
            counts["meeting"] = cur.rowcount

            # 4. Sync last_contact_date from interactions
            cur.execute("""
                UPDATE vip_contacts vc
                SET last_contact_date = sub.max_ts
                FROM (
                    SELECT contact_id, MAX(timestamp) as max_ts
                    FROM contact_interactions
                    GROUP BY contact_id
                ) sub
                WHERE vc.id = sub.contact_id
                  AND (vc.last_contact_date IS NULL OR vc.last_contact_date < sub.max_ts)
            """)
            counts["contacts_updated"] = cur.rowcount

            conn.commit()
            cur.close()

            total = counts.get("email", 0) + counts.get("whatsapp", 0) + counts.get("meeting", 0)
            logger.info(f"Backfill interactions: {total} total ({counts})")
            return counts
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"backfill_interactions failed: {e}")
            return {"error": str(e)}
        finally:
            self._put_conn(conn)

    def sync_last_contact_dates(self) -> int:
        """Sync last_contact_date from contact_interactions. Returns count updated."""
        conn = self._get_conn()
        if not conn:
            return 0
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE vip_contacts vc
                SET last_contact_date = sub.max_ts
                FROM (
                    SELECT contact_id, MAX(timestamp) as max_ts
                    FROM contact_interactions
                    GROUP BY contact_id
                ) sub
                WHERE vc.id = sub.contact_id
                  AND (vc.last_contact_date IS NULL OR vc.last_contact_date < sub.max_ts)
            """)
            count = cur.rowcount
            conn.commit()
            cur.close()
            if count > 0:
                logger.info(f"Synced last_contact_date for {count} contacts")
            return count
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"sync_last_contact_dates failed: {e}")
            return 0
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

            # CORTEX-PHASE-1A: Add wiki_config for agent knowledge routing
            cur.execute("ALTER TABLE capability_sets ADD COLUMN IF NOT EXISTS wiki_config JSONB DEFAULT '{}'::jsonb")

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

            # CORTEX-PHASE-1A: Set wiki_config for AO PM and MOVIE AM
            import json as _json_wc
            cur.execute("""
                UPDATE capability_sets SET wiki_config = %s
                WHERE slug = 'ao_pm' AND (wiki_config IS NULL OR wiki_config = '{}'::jsonb)
            """, (_json_wc.dumps({
                "matters": ["hagenauer", "ao", "morv", "balgerstrasse"],
                "shared_docs": [
                    "documents/hma-mo-vienna",
                    "documents/ftc-table-v008",
                    "documents/participation-agreement",
                    "documents/hagenauer-insolvency"
                ],
                "compiled_state": ["deadlines-active", "decisions-recent", "contacts-vip"]
            }),))

            cur.execute("""
                UPDATE capability_sets SET wiki_config = %s
                WHERE slug = 'movie_am' AND (wiki_config IS NULL OR wiki_config = '{}'::jsonb)
            """, (_json_wc.dumps({
                "matters": ["movie", "rg7"],
                "shared_docs": [
                    "documents/hma-mo-vienna",
                    "documents/movie-operating-budget"
                ],
                "compiled_state": ["deadlines-active", "decisions-recent", "contacts-vip"]
            }),))

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

    # -------------------------------------------------------
    # CORTEX-PHASE-1A: Wiki Infrastructure
    # -------------------------------------------------------

    def _ensure_wiki_pages_table(self):
        """Create wiki_pages table + indexes. Auto-seed if empty. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wiki_pages (
                    id BIGSERIAL PRIMARY KEY,
                    slug TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    agent_owner TEXT,
                    page_type TEXT NOT NULL,
                    matter_slugs TEXT[],
                    backlinks TEXT[],
                    generation INT DEFAULT 1,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_by TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wiki_pages_type ON wiki_pages(page_type)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wiki_pages_owner ON wiki_pages(agent_owner)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wiki_pages_matter ON wiki_pages USING GIN(matter_slugs)")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_wiki_pages_slug ON wiki_pages(slug)")

            # Auto-seed if table is empty (Option C — same pattern as _seed_capability_sets)
            cur.execute("SELECT COUNT(*) FROM wiki_pages")
            if cur.fetchone()[0] == 0:
                self._seed_wiki_from_view_files(cur)

            conn.commit()
            cur.close()
            logger.info("wiki_pages table verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure wiki_pages table: {e}")
        finally:
            self._put_conn(conn)

    def _seed_wiki_from_view_files(self, cur):
        """Seed wiki_pages from existing view files. Called once if table is empty."""
        import os

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        pm_configs = {
            "ao_pm": {
                "view_dir": "data/ao_pm",
                "files": [
                    "SCHEMA.md", "psychology.md", "investment_channels.md",
                    "financing_to_completion.md", "sensitive_issues.md",
                    "communication_rules.md", "agenda.md", "ftc-table-explanations.md",
                ],
                "matter_slugs": ["ao", "hagenauer"],
            },
            "movie_am": {
                "view_dir": "data/movie_am",
                "files": [
                    "SCHEMA.md", "agreements_framework.md", "operator_dynamics.md",
                    "kpi_framework.md", "owner_obligations.md", "agenda.md",
                ],
                "matter_slugs": ["movie", "rg7"],
            },
        }

        total = 0
        for pm_slug, cfg in pm_configs.items():
            view_path = os.path.join(base_dir, cfg["view_dir"])
            if not os.path.isdir(view_path):
                logger.warning("wiki seed: %s not found, skipping", view_path)
                continue

            for fname in cfg["files"]:
                fpath = os.path.join(view_path, fname)
                if not os.path.isfile(fpath):
                    logger.info("wiki seed: %s not found, skipping", fname)
                    continue

                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()

                # Build slug: SCHEMA.md → index, psychology.md → psychology
                base = fname.replace(".md", "").lower().replace("_", "-").replace(" ", "-")
                if base == "schema":
                    base = "index"
                slug = f"{pm_slug}/{base}"

                title = fname.replace(".md", "").replace("_", " ").title()
                if fname == "SCHEMA.md":
                    title = f"{pm_slug.upper().replace('_', ' ')} — Index"

                cur.execute("""
                    INSERT INTO wiki_pages (slug, title, content, agent_owner, page_type, matter_slugs, updated_by)
                    VALUES (%s, %s, %s, %s, 'agent_knowledge', %s, 'auto_seed')
                    ON CONFLICT (slug) DO NOTHING
                """, (slug, title, content, pm_slug, cfg["matter_slugs"]))

                if cur.rowcount > 0:
                    total += 1

        logger.info("wiki seed: %d pages seeded from view files", total)

    def _ensure_cortex_config_table(self):
        """Create cortex_config table with feature flags. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cortex_config (
                    key TEXT PRIMARY KEY,
                    value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            # Seed feature flags — only if not present (idempotent)
            cur.execute("""
                INSERT INTO cortex_config (key, value) VALUES
                    ('wiki_context_enabled', 'false'::jsonb),
                    ('auto_merge_enabled', 'false'::jsonb),
                    ('tool_router_enabled', 'false'::jsonb)
                ON CONFLICT (key) DO NOTHING
            """)
            conn.commit()
            cur.close()
            logger.info("cortex_config table verified (3 feature flags)")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure cortex_config table: {e}")
        finally:
            self._put_conn(conn)

    def get_cortex_config(self, key: str, default=None):
        """Read a Cortex feature flag. Returns Python value (bool/str/dict)."""
        conn = self._get_conn()
        if not conn:
            return default
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM cortex_config WHERE key = %s LIMIT 1", (key,))
            row = cur.fetchone()
            cur.close()
            if row:
                import json as _json_cc
                return _json_cc.loads(row[0]) if isinstance(row[0], str) else row[0]
            return default
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"get_cortex_config({key}) failed: {e}")
            return default
        finally:
            self._put_conn(conn)

    def _ensure_cortex_events_table(self):
        """CORTEX-PHASE-2A: Append-only event bus for shared writes."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cortex_events (
                    id BIGSERIAL PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    source_agent TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT,
                    payload JSONB NOT NULL,
                    refers_to BIGINT,
                    canonical_id INTEGER,
                    qdrant_id TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_cortex_events_type
                ON cortex_events(event_type, created_at)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_cortex_events_category
                ON cortex_events(category, created_at)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_cortex_events_agent
                ON cortex_events(source_agent, created_at)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_cortex_events_refers
                ON cortex_events(refers_to) WHERE refers_to IS NOT NULL
            """)
            # Add source_agent to deadlines and decisions (nullable — won't break existing inserts)
            cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS source_agent TEXT")
            cur.execute("ALTER TABLE decisions ADD COLUMN IF NOT EXISTS source_agent TEXT")

            # CORTEX-PHASE-3: Lint results table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cortex_lint_results (
                    id          SERIAL PRIMARY KEY,
                    finding_type TEXT NOT NULL,
                    severity    TEXT DEFAULT 'warning',
                    slug_or_ref TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status      TEXT DEFAULT 'open',
                    created_at  TIMESTAMPTZ DEFAULT NOW(),
                    resolved_at TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_lint_results_status
                ON cortex_lint_results (status, severity)
            """)

            conn.commit()
            cur.close()
            logger.info("cortex_events table verified (+ source_agent columns + cortex_lint_results)")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure cortex_events table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_cortex_obligations_collection(self):
        """CORTEX-PHASE-2B: Create Qdrant collection for semantic dedup."""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import VectorParams, Distance
            from config.settings import config

            if not config.qdrant.url or not config.qdrant.api_key:
                logger.warning("Qdrant not configured — skipping cortex_obligations collection")
                return

            client = QdrantClient(url=config.qdrant.url, api_key=config.qdrant.api_key)
            try:
                client.get_collection("cortex_obligations")
                logger.info("cortex_obligations collection already exists")
            except Exception:
                client.create_collection(
                    collection_name="cortex_obligations",
                    vectors_config=VectorParams(
                        size=1024,  # Voyage AI voyage-3
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created cortex_obligations Qdrant collection")
        except Exception as e:
            logger.warning(f"Could not ensure cortex_obligations collection: {e}")

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

    def _ensure_baker_tasks_complexity_columns(self):
        """COMPLEXITY-ROUTER-1: Add complexity classification columns. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS complexity VARCHAR(10)")
            cur.execute("ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS complexity_confidence FLOAT")
            cur.execute("ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS complexity_override VARCHAR(50)")
            cur.execute("ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS complexity_reasoning TEXT")
            conn.commit()
            cur.close()
            logger.info("baker_tasks complexity columns verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure baker_tasks complexity columns: {e}")
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
            # SIDEBAR-RESTRUCTURE-1: Add category column
            cur.execute("ALTER TABLE matter_registry ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'inbox'")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_matter_registry_name "
                "ON matter_registry(matter_name)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_matter_registry_status "
                "ON matter_registry(status)"
            )
            # SIDEBAR-RESTRUCTURE-1: Seed categories (idempotent — only updates where category='inbox')
            _project_matters = (
                "Mandarin Oriental Asset Management", "Mandarin Oriental Sales",
                "Mandarin Oriental Dispute", "Mandarin Oriental Hotel Dispute",
                "Hagenauer", "Kempinski Kitzbühel Acquisition", "Kempinski KitzbüHel Acquisition",
                "Cap Ferrat Villa", "Oskolkov-RG7", "FX Mayr",
                "Financing Vienna & Baden-Baden", "Wertheimer LP",
                "Lanas", "ClaimsMax", "Alric", "Cupial",
                "NVIDIA-GTC-2026", "Annaberg Restructuring",
                "Mandarin Oriental", "AlpenGold Davos",
            )
            _ops_matters = (
                "Austrian Tax & Corporate", "Swiss Tax & Banking",
                "German Property Tax", "Cyprus Holding Structure",
                "Family Wealth Overview", "Microsoft 365 Migration",
                "Baker", "Brisen-AI", "Owner's Lens",
            )
            for _pm in _project_matters:
                cur.execute(
                    "UPDATE matter_registry SET category = 'project' WHERE matter_name = %s AND category = 'inbox'",
                    (_pm,),
                )
            for _om in _ops_matters:
                cur.execute(
                    "UPDATE matter_registry SET category = 'operations' WHERE matter_name = %s AND category = 'inbox'",
                    (_om,),
                )
            conn.commit()

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
        # Auto-assign matter_slug if not provided
        if not matter_slug and (title or body):
            try:
                from orchestrator.pipeline import _match_matter_slug
                matter_slug = _match_matter_slug(title or "", body or "", self)
            except Exception:
                pass  # non-fatal — matter assignment is best-effort
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping create_alert")
            return None
        try:
            cur = conn.cursor()
            # Dedup guard: skip if same source+source_id exists within 1 hour
            if source and source_id:
                cur.execute(
                    "SELECT id FROM alerts WHERE source = %s AND source_id = %s "
                    "AND created_at > NOW() - INTERVAL '1 hour' LIMIT 1",
                    (source, source_id),
                )
                if cur.fetchone():
                    cur.close()
                    logger.info(f"Alert dedup: skipped duplicate source={source} source_id={source_id}")
                    return None
            # ALERT-DEDUP-2: Matter-slug + title similarity dedup (7-day window)
            # If same matter has a pending alert with similar title, update it instead of creating new
            if matter_slug:
                cur.execute(
                    """SELECT id, title, body FROM alerts
                       WHERE matter_slug = %s AND status = 'pending'
                         AND created_at > NOW() - INTERVAL '7 days'
                       ORDER BY created_at DESC LIMIT 1""",
                    (matter_slug,),
                )
                _existing = cur.fetchone()
                if _existing and _titles_similar(_existing[1], title):
                    _existing_id = _existing[0]
                    cur.execute(
                        "UPDATE alerts SET body = %s, updated_at = NOW(), tier = LEAST(tier, %s) WHERE id = %s",
                        (body, tier, _existing_id),
                    )
                    conn.commit()
                    cur.close()
                    logger.info(f"Alert dedup (matter+title): updated existing #{_existing_id} instead of creating new — matter={matter_slug}")
                    return _existing_id
            # ALERT-DEDUP-3: Universal title-based dedup (all sources)
            # Normalize title: strip common prefixes for better matching
            import re as _re
            _dedup_title = _re.sub(
                r'^(Intelligence:\s*|Commitment due today:\s*|OVERDUE:\s*|DUE TODAY:\s*|Due in 48h:\s*)',
                '', title or '', flags=_re.IGNORECASE,
            ).strip()
            _dedup_prefix = _dedup_title[:50].lower()
            if _dedup_prefix:
                cur.execute(
                    """SELECT id FROM alerts
                       WHERE status = 'pending'
                         AND LOWER(LEFT(regexp_replace(title,
                               '^(Intelligence:\\s*|Commitment due today:\\s*|OVERDUE:\\s*|DUE TODAY:\\s*|Due in 48h:\\s*)',
                               '', 'i'), 50)) = %s
                         AND created_at > NOW() - INTERVAL '6 hours'
                       LIMIT 1""",
                    (_dedup_prefix,),
                )
                if cur.fetchone():
                    cur.close()
                    logger.info(f"Alert dedup (title): similar pending alert exists — skipping: {_dedup_prefix}...")
                    return None
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
            # Web Push to all subscribers (T1 + T2)
            if tier <= 2:
                try:
                    self._send_web_push_all(alert_id, tier, title)
                except Exception as e:
                    logger.warning(f"Web Push failed (non-fatal): {e}")
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

    def alert_exists_recent(self, source: str, source_id: str, hours: int = 4) -> bool:
        """Check if an alert with this source + source_id was created within the last N hours."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM alerts WHERE source = %s AND source_id = %s "
                "AND created_at > NOW() - make_interval(hours => %s) LIMIT 1",
                (source, source_id, hours),
            )
            exists = cur.fetchone() is not None
            cur.close()
            return exists
        except Exception as e:
            logger.warning(f"alert_exists_recent check failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    def alert_title_dedup(self, title: str, hours: int = 24) -> bool:
        """Check if a pending alert with the same title prefix (first 60 chars) exists within N hours.
        ALERT-DEDUP-2: Prevents duplicate pipeline alerts from repeated trigger processing.
        """
        if not title:
            return False
        prefix = title[:60]
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM alerts WHERE status = 'pending' "
                "AND LEFT(title, 60) = %s "
                "AND created_at > NOW() - make_interval(hours => %s) LIMIT 1",
                (prefix, hours),
            )
            exists = cur.fetchone() is not None
            cur.close()
            if exists:
                logger.info(f"Alert title dedup: similar pending alert found — skipping: {prefix}...")
            return exists
        except Exception as e:
            logger.warning(f"alert_title_dedup check failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    def get_pending_alerts(self, tier: int = None, limit: int = 100) -> list:
        """Fetch unresolved alerts, optionally filtered by tier. Capped at limit."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if tier:
                cur.execute(
                    "SELECT * FROM alerts WHERE status = 'pending' AND tier = %s ORDER BY created_at DESC LIMIT %s",
                    (tier, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM alerts WHERE status = 'pending' ORDER BY tier, created_at DESC LIMIT %s",
                    (limit,),
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
        # ALERT-DEDUP-2: auto-dismiss related alerts
        self.dismiss_related_alerts(alert_id)

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
        # ALERT-DEDUP-2: auto-dismiss related alerts
        self.dismiss_related_alerts(alert_id)

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
        # ALERT-DEDUP-2: auto-dismiss related alerts
        self.dismiss_related_alerts(alert_id)

    def dismiss_related_alerts(self, alert_id: int):
        """ALERT-DEDUP-2: After acting on an alert, dismiss other pending alerts about the same topic.
        Excludes browser_transaction alerts (need explicit confirmation)."""
        conn = self._get_conn()
        if not conn:
            return 0
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Get the acted-on alert
            cur.execute("SELECT matter_slug, title, source FROM alerts WHERE id = %s", (alert_id,))
            alert = cur.fetchone()
            if not alert:
                cur.close()
                return 0

            dismissed_total = 0

            # Strategy 1: Same matter_slug → dismiss all older pending (except browser_transaction)
            if alert['matter_slug']:
                cur.execute("""
                    UPDATE alerts SET status = 'dismissed', exit_reason = 'auto-dismiss-related', resolved_at = NOW()
                    WHERE matter_slug = %s AND status = 'pending' AND id != %s
                      AND (source IS NULL OR source != 'browser_transaction')
                    """, (alert['matter_slug'], alert_id))
                dismissed_total += cur.rowcount

            # Strategy 2: Similar title (3+ significant words overlap) → dismiss
            title_words = [w.lower() for w in (alert['title'] or '').split()
                           if len(w) > 3 and w.lower() not in ('the', 'this', 'that', 'from', 'with', 'about', 'your', 'baker', 'alert')]
            if len(title_words) >= 3:
                # Use first 3 keywords in a LIKE pattern
                pattern = '%' + '%'.join(title_words[:3]) + '%'
                cur.execute("""
                    UPDATE alerts SET status = 'dismissed', exit_reason = 'auto-dismiss-similar', resolved_at = NOW()
                    WHERE status = 'pending' AND id != %s
                      AND LOWER(title) LIKE %s
                      AND (source IS NULL OR source != 'browser_transaction')
                    """, (alert_id, pattern))
                dismissed_total += cur.rowcount

            conn.commit()
            cur.close()
            if dismissed_total > 0:
                logger.info(f"ALERT-DEDUP-2: auto-dismissed {dismissed_total} related alerts after acting on #{alert_id}")
            return dismissed_total
        except Exception as e:
            conn.rollback()
            logger.error(f"dismiss_related_alerts failed for #{alert_id}: {e}")
            return 0
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
        Short content → single vector. Long content → chunked into multiple vectors.
        Capped at 20 chunks max — full text lives in PostgreSQL, Qdrant is just for search."""
        try:
            chunk_pairs = self._embed_chunked(content)
            # Cap chunks to prevent disk bloat (QDRANT-CLEANUP-1).
            # Full text is in PostgreSQL; Qdrant only needs enough chunks to find the doc.
            MAX_CHUNKS = 20
            if len(chunk_pairs) > MAX_CHUNKS:
                logger.info(
                    f"Capping {len(chunk_pairs)} chunks to {MAX_CHUNKS} for {collection} "
                    f"(content: {len(content):,} chars)"
                )
                chunk_pairs = chunk_pairs[:MAX_CHUNKS]
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
            # RUSSO-MEMORY-1: Owner column for memory separation (dimitry/edita)
            cur.execute("""
                ALTER TABLE conversation_memory
                ADD COLUMN IF NOT EXISTS owner VARCHAR(20) DEFAULT 'dimitry'
            """)
            conn.commit()
            cur.close()
            logger.info("conversation_memory table verified (with owner column)")
        except Exception as e:
            logger.warning(f"Could not ensure conversation_memory table: {e}")
        finally:
            self._put_conn(conn)

    def log_conversation(self, question, answer="", answer_length=0, project="general", chunk_count=1, owner="dimitry"):
        """Catalogue a scan conversation in PostgreSQL + embed to Qdrant (B1)."""
        conn = self._get_conn()
        if not conn:
            logger.warning("No DB connection — skipping log_conversation")
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO conversation_memory
                    (question, answer, answer_length, project, chunk_count, owner)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (question, answer, answer_length, project, chunk_count, owner or "dimitry"))
            conn.commit()
            cur.close()
        except Exception as e:
            logger.error(f"Failed to log conversation: {e}")
        finally:
            self._put_conn(conn)

        # B1: Embed Q+A into Qdrant baker-conversations for semantic retrieval
        if question and answer and len(answer) > 50:
            try:
                import threading
                def _embed():
                    try:
                        from datetime import datetime, timezone
                        text = f"Question: {question}\n\nAnswer: {answer[:4000]}"
                        metadata = {
                            "source": "conversation",
                            "project": project,
                            "question": question[:500],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        self.store_document(text, metadata, collection="baker-conversations")
                        logger.info(f"B1: Conversation embedded to Qdrant ({len(text)} chars)")
                    except Exception as e:
                        logger.warning(f"B1: Conversation embedding failed (non-fatal): {e}")
                threading.Thread(target=_embed, daemon=True).start()
            except Exception:
                pass  # threading import or start failed — non-fatal

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

    def get_relevant_conversations(self, question: str, limit: int = 5) -> list:
        """DEEP-MODE-2: Fetch prior conversations relevant to the current question.

        Uses ILIKE keyword match on conversation_memory.question + answer.
        Excludes last hour to avoid duplicating the current session.
        Returns list of dicts: [{question, answer, created_at}, ...] newest-first.
        Fault-tolerant: returns [] on any failure.
        """
        conn = self._get_conn()
        if not conn:
            return []
        try:
            import re
            # Extract significant keywords (3+ chars, skip stop words)
            _STOP = {"the", "and", "for", "are", "but", "not", "you", "all",
                      "can", "had", "her", "was", "one", "our", "out", "has",
                      "how", "its", "may", "new", "now", "old", "see", "who",
                      "did", "get", "let", "say", "she", "too", "use", "what",
                      "where", "when", "which", "why", "with", "about", "could",
                      "from", "have", "been", "some", "than", "that", "them",
                      "then", "they", "this", "will", "would", "there", "their",
                      "these", "those", "should", "baker", "tell", "show",
                      "give", "know", "does", "status", "update", "please"}
            terms = [w for w in re.findall(r'\b\w{3,}\b', question.lower()) if w not in _STOP]
            if not terms:
                return []

            # Build ILIKE conditions: match any keyword in question or answer
            like_clauses = []
            params = []
            for term in terms[:6]:  # cap at 6 keywords to keep query fast
                like_clauses.append("(question ILIKE %s OR answer ILIKE %s)")
                params.extend([f"%{term}%", f"%{term}%"])

            where = " OR ".join(like_clauses)

            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(f"""
                SELECT question, answer, created_at
                FROM conversation_memory
                WHERE ({where})
                  AND created_at < NOW() - INTERVAL '1 hour'
                  AND answer IS NOT NULL AND LENGTH(answer) > 50
                ORDER BY created_at DESC
                LIMIT %s
            """, params + [limit])
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        except Exception as e:
            logger.warning(f"get_relevant_conversations failed: {e}")
            return []
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # E3: Web Push subscriptions
    # -------------------------------------------------------

    def _ensure_push_subscriptions_table(self):
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS push_subscriptions (
                    id SERIAL PRIMARY KEY,
                    endpoint TEXT NOT NULL UNIQUE,
                    p256dh TEXT NOT NULL,
                    auth TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    last_used_at TIMESTAMPTZ
                )
            """)
            conn.commit()
            cur.close()
        except Exception as e:
            conn.rollback()
            logger.warning(f"push_subscriptions table init failed: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # MEETINGS-DETECT-1: Detected meetings from Director messages
    # -------------------------------------------------------

    def _ensure_detected_meetings_table(self):
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS detected_meetings (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    participant_names TEXT[],
                    meeting_date DATE,
                    meeting_time TEXT,
                    location TEXT,
                    status TEXT DEFAULT 'pending',
                    source TEXT NOT NULL,
                    source_ref TEXT,
                    raw_text TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    dismissed BOOLEAN DEFAULT FALSE
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_detected_meetings_date ON detected_meetings(meeting_date)")
            conn.commit()
            cur.close()
        except Exception as e:
            conn.rollback()
            logger.warning(f"_ensure_detected_meetings_table failed: {e}")
        finally:
            self._put_conn(conn)

    def insert_detected_meeting(self, title: str, participant_names: list = None,
                                meeting_date=None, meeting_time: str = None,
                                location: str = None, status: str = "pending",
                                source: str = "ask_baker", source_ref: str = None,
                                raw_text: str = None) -> int:
        """MEETINGS-DETECT-1: Store a detected meeting. Returns meeting ID."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            # MEETINGS-DETECT-2: Source ref dedup — don't process same email twice
            if source_ref:
                cur.execute("SELECT id FROM detected_meetings WHERE source_ref = %s LIMIT 1", (source_ref,))
                if cur.fetchone():
                    cur.close()
                    logger.info(f"Meeting dedup: source_ref {source_ref} already exists — skipping")
                    return None
            # LANDING-FIXES-1: Status simplification — only confirmed or proposed
            if status not in ('confirmed', 'proposed'):
                status = 'proposed'
            # Dedup: check for existing meeting with same date + similar title (exact OR fuzzy 30-char prefix)
            if meeting_date and title:
                cur.execute("""
                    SELECT id FROM detected_meetings
                    WHERE meeting_date = %s AND dismissed = FALSE AND status != 'cancelled'
                      AND (LOWER(title) = LOWER(%s) OR LOWER(LEFT(title, 30)) = LOWER(LEFT(%s, 30)))
                    LIMIT 1
                """, (meeting_date, title, title))
                existing = cur.fetchone()
                if existing:
                    # Update existing instead of creating duplicate
                    cur.execute("""
                        UPDATE detected_meetings
                        SET meeting_time = COALESCE(%s, meeting_time),
                            location = COALESCE(%s, location),
                            status = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (meeting_time, location, status, existing[0]))
                    conn.commit()
                    cur.close()
                    logger.info(f"MEETINGS-DETECT-1: updated existing detected meeting #{existing[0]}")
                    return existing[0]
            # LANDING-FIXES-1: Participant-based dedup — same date + overlapping participants
            if meeting_date and participant_names:
                import psycopg2.extras as _pxe
                cur2 = conn.cursor(cursor_factory=_pxe.RealDictCursor)
                cur2.execute("""
                    SELECT id, participant_names FROM detected_meetings
                    WHERE meeting_date = %s AND dismissed = FALSE AND status != 'cancelled'
                """, (meeting_date,))
                for _row in cur2.fetchall():
                    _existing_parts = set(p.lower() for p in (_row.get("participant_names") or []))
                    _new_parts = set(p.lower() for p in (participant_names or []))
                    if _existing_parts and _new_parts and _existing_parts & _new_parts:
                        cur2.close()
                        cur.execute("""
                            UPDATE detected_meetings SET
                                meeting_time = COALESCE(%s, meeting_time),
                                location = COALESCE(%s, location),
                                status = %s, updated_at = NOW()
                            WHERE id = %s
                        """, (meeting_time, location, status, _row["id"]))
                        conn.commit()
                        cur.close()
                        logger.info(f"LANDING-FIXES-1: deduped meeting by participants → #{_row['id']}")
                        return _row["id"]
                cur2.close()

            cur.execute("""
                INSERT INTO detected_meetings
                    (title, participant_names, meeting_date, meeting_time, location,
                     status, source, source_ref, raw_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (title, participant_names, meeting_date, meeting_time, location,
                  status, source, source_ref, raw_text))
            row = cur.fetchone()
            conn.commit()
            cur.close()
            mid = row[0] if row else None
            logger.info(f"MEETINGS-DETECT-1: created detected meeting #{mid}: {title}")
            return mid
        except Exception as e:
            conn.rollback()
            logger.error(f"insert_detected_meeting failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def get_detected_meetings(self, days_ahead: int = 14) -> list:
        """MEETINGS-DETECT-1: Get upcoming detected meetings. No limit — all within window.
        LANDING-FIXES-1: Status simplified to confirmed/proposed only. Deduped by date+title."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT * FROM detected_meetings
                WHERE dismissed = FALSE
                  AND status != 'cancelled'
                  AND meeting_date BETWEEN CURRENT_DATE AND CURRENT_DATE + make_interval(days => %s)
                ORDER BY meeting_date ASC, meeting_time ASC NULLS LAST
            """, (days_ahead,))
            raw = [dict(r) for r in cur.fetchall()]
            cur.close()
            # LANDING-FIXES-1: Deduplicate by date + first 30 chars of title
            seen = {}
            deduped = []
            for m in raw:
                key = str(m.get("meeting_date", "")) + "|" + (m.get("title") or "")[:30].lower().strip()
                if key in seen:
                    # Keep the one with more detail
                    existing = seen[key]
                    if (m.get("meeting_time") and not existing.get("meeting_time")) or \
                       (m.get("location") and not existing.get("location")):
                        deduped = [m if x is existing else x for x in deduped]
                        seen[key] = m
                    continue
                seen[key] = m
                deduped.append(m)
            return deduped
        except Exception as e:
            logger.error(f"get_detected_meetings failed: {e}")
            return []
        finally:
            self._put_conn(conn)

    # WEALTH-MANAGER: Wealth tracking tables
    # -------------------------------------------------------

    def _ensure_wealth_tables(self):
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wealth_positions (
                    id SERIAL PRIMARY KEY,
                    owner VARCHAR(20) DEFAULT 'shared',
                    category VARCHAR(30),
                    name TEXT NOT NULL,
                    current_value NUMERIC(15,2),
                    currency VARCHAR(3) DEFAULT 'EUR',
                    valuation_date DATE,
                    valuation_source TEXT,
                    notes TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wealth_tax_calendar (
                    id SERIAL PRIMARY KEY,
                    owner VARCHAR(20) DEFAULT 'shared',
                    jurisdiction VARCHAR(30),
                    obligation TEXT NOT NULL,
                    due_date DATE NOT NULL,
                    status VARCHAR(20) DEFAULT 'upcoming',
                    advisor TEXT,
                    notes TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit()
            cur.close()
            logger.info("Wealth tables verified (wealth_positions, wealth_tax_calendar)")
        except Exception as e:
            conn.rollback()
            logger.warning(f"Wealth tables init failed: {e}")
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # PM-FACTORY: Generic PM persistent state
    # -------------------------------------------------------

    def _ensure_pm_project_state_table(self):
        """PM-FACTORY: Generic persistent state for all PM capabilities."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            # Keep old AO tables (still referenced by ao_signal_detector)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ao_project_state (
                    id SERIAL PRIMARY KEY,
                    state_key TEXT NOT NULL DEFAULT 'current',
                    state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    version INTEGER DEFAULT 1,
                    last_run_at TIMESTAMPTZ,
                    last_question TEXT,
                    last_answer_summary TEXT,
                    run_count INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_ao_project_state_key "
                "ON ao_project_state(state_key)"
            )
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ao_state_history (
                    id SERIAL PRIMARY KEY,
                    version INTEGER NOT NULL,
                    state_json_before JSONB NOT NULL,
                    mutation_source TEXT,
                    mutation_summary TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            # New generic table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pm_project_state (
                    id SERIAL PRIMARY KEY,
                    pm_slug TEXT NOT NULL,
                    state_key TEXT NOT NULL DEFAULT 'current',
                    state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    version INTEGER DEFAULT 1,
                    last_run_at TIMESTAMPTZ,
                    last_question TEXT,
                    last_answer_summary TEXT,
                    run_count INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_pm_project_state_slug_key "
                "ON pm_project_state(pm_slug, state_key)"
            )
            # Generic audit trail
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pm_state_history (
                    id SERIAL PRIMARY KEY,
                    pm_slug TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    state_json_before JSONB NOT NULL,
                    mutation_source TEXT,
                    mutation_summary TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            # MIGRATION: Copy existing AO data if old table exists and new doesn't have it
            cur.execute("""
                DO $$ BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'ao_project_state')
                       AND NOT EXISTS (SELECT 1 FROM pm_project_state WHERE pm_slug = 'ao_pm' LIMIT 1) THEN
                        INSERT INTO pm_project_state
                            (pm_slug, state_key, state_json, version, last_run_at,
                             last_question, last_answer_summary, run_count, created_at, updated_at)
                        SELECT 'ao_pm', state_key, state_json, version, last_run_at,
                               last_question, last_answer_summary, run_count, created_at, updated_at
                        FROM ao_project_state;
                    END IF;
                END $$
            """)
            # MIGRATION: Copy audit trail
            cur.execute("""
                DO $$ BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'ao_state_history')
                       AND NOT EXISTS (SELECT 1 FROM pm_state_history WHERE pm_slug = 'ao_pm' LIMIT 1) THEN
                        INSERT INTO pm_state_history
                            (pm_slug, version, state_json_before, mutation_source, mutation_summary, created_at)
                        SELECT 'ao_pm', version, state_json_before, mutation_source, mutation_summary, created_at
                        FROM ao_state_history;
                    END IF;
                END $$
            """)
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure pm_project_state table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_pm_pending_insights_table(self):
        """PM-KNOWLEDGE-ARCH-1: Queue for insights awaiting review before PM knowledge base update."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pm_pending_insights (
                    id              SERIAL PRIMARY KEY,
                    pm_slug         TEXT NOT NULL,
                    insight         TEXT NOT NULL,
                    target_file     TEXT,
                    target_section  TEXT,
                    source_question TEXT,
                    source_summary  TEXT,
                    confidence      TEXT DEFAULT 'medium',
                    status          TEXT DEFAULT 'pending',
                    reviewed_at     TIMESTAMPTZ,
                    review_note     TEXT,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_pm_pending_slug_status "
                "ON pm_pending_insights(pm_slug, status)"
            )
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure pm_pending_insights table: {e}")
        finally:
            self._put_conn(conn)

    def get_pm_project_state(self, pm_slug: str) -> dict:
        """PM-FACTORY: Read PM project state by slug."""
        conn = self._get_conn()
        if not conn:
            return {}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT * FROM pm_project_state WHERE pm_slug = %s AND state_key = 'current' LIMIT 1",
                (pm_slug,)
            )
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else {}
        except Exception as e:
            logger.warning(f"get_pm_project_state({pm_slug}) failed: {e}")
            return {}
        finally:
            self._put_conn(conn)

    def update_pm_project_state(self, pm_slug: str, updates: dict, summary: str = "",
                                question: str = "",
                                mutation_source: str = "auto",
                                thread_id: Optional[str] = None):
        """PM-FACTORY: Upsert PM project state with audit trail + optimistic locking.

        BRIEF_CAPABILITY_THREADS_1: optional ``thread_id`` threaded into
        pm_state_history INSERT so state snapshots link to the originating thread.
        Callers that don't care about threads pass ``thread_id=None`` (default);
        existing rows stay NULL — zero impact on legacy behaviour.

        Returns ``pm_state_history.id`` of the newly-inserted audit row on success,
        or ``None`` on first-ever insert (no history row is created for the
        initial pm_project_state insert) or on any error.
        """
        max_retries = 3
        for attempt in range(max_retries):
            conn = self._get_conn()
            if not conn:
                return None
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT state_json, version FROM pm_project_state "
                    "WHERE pm_slug = %s AND state_key = 'current'",
                    (pm_slug,)
                )
                row = cur.fetchone()
                if row:
                    existing = row[0] if isinstance(row[0], dict) else json.loads(row[0] or '{}')
                    current_version = row[1] or 1

                    # Audit trail: snapshot before mutation
                    cur.execute("""
                        INSERT INTO pm_state_history
                            (pm_slug, version, state_json_before, mutation_source,
                             mutation_summary, thread_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (pm_slug, current_version, json.dumps(existing, default=str),
                          mutation_source, summary[:500], thread_id))
                    history_row_id = cur.fetchone()[0]

                    # Merge updates into fresh read
                    for k, v in updates.items():
                        if isinstance(v, dict) and isinstance(existing.get(k), dict):
                            existing[k].update(v)
                        else:
                            existing[k] = v

                    # Optimistic lock
                    cur.execute("""
                        UPDATE pm_project_state
                        SET state_json = %s, version = %s, last_run_at = NOW(),
                            run_count = run_count + 1, last_question = %s,
                            last_answer_summary = %s, updated_at = NOW()
                        WHERE pm_slug = %s AND state_key = 'current' AND version = %s
                    """, (json.dumps(existing, default=str), current_version + 1,
                          question[:500], summary[:500], pm_slug, current_version))

                    if cur.rowcount == 0:
                        conn.rollback()
                        cur.close()
                        self._put_conn(conn)
                        if attempt < max_retries - 1:
                            logger.warning(
                                f"PM state ({pm_slug}) version conflict, retry {attempt + 1}/{max_retries}"
                            )
                            continue
                        else:
                            logger.error(f"PM state ({pm_slug}) update failed after max retries")
                            return None
                    conn.commit()
                    cur.close()
                    return history_row_id  # success with audit row
                else:
                    cur.execute("""
                        INSERT INTO pm_project_state (pm_slug, state_key, state_json, version,
                            last_run_at, run_count, last_question, last_answer_summary)
                        VALUES (%s, 'current', %s, 1, NOW(), 1, %s, %s)
                    """, (pm_slug, json.dumps(updates, default=str), question[:500], summary[:500]))
                    conn.commit()
                    cur.close()
                    return None  # first-ever insert — no history row
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.warning(f"update_pm_project_state({pm_slug}) failed: {e}")
                return None
            finally:
                self._put_conn(conn)

    def get_ao_project_state(self) -> dict:
        """DEPRECATED: Use get_pm_project_state('ao_pm'). Kept for backward compat."""
        return self.get_pm_project_state("ao_pm")

    def update_ao_project_state(self, updates: dict, summary: str = "",
                                question: str = "",
                                mutation_source: str = "auto"):
        """DEPRECATED: Use update_pm_project_state('ao_pm', ...). Kept for backward compat."""
        return self.update_pm_project_state("ao_pm", updates, summary, question, mutation_source)

    def get_pending_insights(self, pm_slug: str, status: str = "pending",
                             limit: int = 20) -> list:
        """PM-KNOWLEDGE-ARCH-1: Get pending insights for a PM."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, insight, target_file, target_section, confidence,
                       source_question, created_at
                FROM pm_pending_insights
                WHERE pm_slug = %s AND status = %s
                ORDER BY created_at DESC LIMIT %s
            """, (pm_slug, status, limit))
            rows = cur.fetchall()
            cur.close()
            return [
                {
                    "id": r[0], "insight": r[1], "target_file": r[2],
                    "target_section": r[3], "confidence": r[4],
                    "source_question": r[5],
                    "created_at": r[6].isoformat() if r[6] else None,
                }
                for r in rows
            ]
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"get_pending_insights failed: {e}")
            return []
        finally:
            self._put_conn(conn)

    def update_pending_insight_status(self, insight_id: int, new_status: str,
                                      review_note: str = "") -> bool:
        """PM-KNOWLEDGE-ARCH-1: Approve/reject/promote a pending insight."""
        if new_status not in ("approved", "rejected", "promoted"):
            return False
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE pm_pending_insights
                SET status = %s, reviewed_at = NOW(), review_note = %s
                WHERE id = %s AND status = 'pending'
            """, (new_status, review_note[:500] if review_note else "", insight_id))
            affected = cur.rowcount
            conn.commit()
            cur.close()
            return affected > 0
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"update_pending_insight_status failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # CROSS-PM SIGNAL BUS
    # -------------------------------------------------------

    def _ensure_pm_cross_signals_table(self):
        """Create inter-PM communication signal table."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pm_cross_signals (
                    id          SERIAL PRIMARY KEY,
                    source_pm   TEXT NOT NULL,
                    target_pm   TEXT NOT NULL,
                    signal_type TEXT DEFAULT 'info',
                    signal_text TEXT NOT NULL,
                    context     TEXT,
                    status      TEXT DEFAULT 'active',
                    created_at  TIMESTAMPTZ DEFAULT NOW(),
                    consumed_at TIMESTAMPTZ
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_cross_signals_target "
                "ON pm_cross_signals(target_pm, status)"
            )
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure pm_cross_signals table: {e}")
        finally:
            self._put_conn(conn)

    def create_cross_pm_signal(self, source_pm: str, target_pm: str,
                                signal_type: str, signal_text: str,
                                context: str = "") -> int | None:
        """Insert a cross-PM signal with 7-day dedup."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            # Dedup: skip if identical signal_text exists for same pair within 7 days
            cur.execute("""
                SELECT id FROM pm_cross_signals
                WHERE source_pm = %s AND target_pm = %s
                  AND signal_text = %s
                  AND created_at > NOW() - INTERVAL '7 days'
                LIMIT 1
            """, (source_pm, target_pm, signal_text[:500]))
            if cur.fetchone():
                cur.close()
                return None  # duplicate
            cur.execute("""
                INSERT INTO pm_cross_signals (source_pm, target_pm, signal_type, signal_text, context)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (source_pm, target_pm, signal_type, signal_text[:500], (context or "")[:500]))
            row = cur.fetchone()
            conn.commit()
            cur.close()
            return row[0] if row else None
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"create_cross_pm_signal failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def get_cross_pm_signals(self, target_pm: str, status: str = "active",
                              limit: int = 10) -> list:
        """Fetch inbound cross-PM signals for a given PM."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id, source_pm, signal_type, signal_text, context, created_at
                FROM pm_cross_signals
                WHERE target_pm = %s AND status = %s
                ORDER BY created_at DESC LIMIT %s
            """, (target_pm, status, limit))
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"get_cross_pm_signals failed: {e}")
            return []
        finally:
            self._put_conn(conn)

    def consume_cross_pm_signal(self, signal_id: int) -> bool:
        """Mark a cross-PM signal as consumed."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE pm_cross_signals
                SET status = 'consumed', consumed_at = NOW()
                WHERE id = %s AND status = 'active'
            """, (signal_id,))
            affected = cur.rowcount
            conn.commit()
            cur.close()
            return affected > 0
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"consume_cross_pm_signal failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    def store_push_subscription(self, endpoint: str, p256dh: str, auth: str) -> bool:
        """Upsert a Web Push subscription."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO push_subscriptions (endpoint, p256dh, auth)
                VALUES (%s, %s, %s)
                ON CONFLICT (endpoint) DO UPDATE SET
                    p256dh = EXCLUDED.p256dh,
                    auth = EXCLUDED.auth,
                    last_used_at = NOW()
            """, (endpoint, p256dh, auth))
            conn.commit()
            cur.close()
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"store_push_subscription failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    def get_all_push_subscriptions(self) -> list:
        """Return all active push subscriptions."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor()
            cur.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions")
            rows = cur.fetchall()
            cur.close()
            return [{"endpoint": r[0], "p256dh": r[1], "auth": r[2]} for r in rows]
        except Exception as e:
            logger.error(f"get_all_push_subscriptions failed: {e}")
            return []
        finally:
            self._put_conn(conn)

    def remove_push_subscription(self, endpoint: str):
        """Remove a stale subscription (410 Gone from push service)."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (endpoint,))
            conn.commit()
            cur.close()
        except Exception as e:
            conn.rollback()
            logger.error(f"remove_push_subscription failed: {e}")
        finally:
            self._put_conn(conn)

    def _should_throttle_push(self, tier: int) -> bool:
        """Check quiet hours, daily cap, cooldown. T1 bypasses all throttles."""
        if tier <= 1:
            return False  # T1 always breaks through

        now = datetime.now(timezone.utc)
        hour_utc = now.hour

        # Quiet hours: 21:00-06:00 UTC (22:00-07:00 CET)
        quiet_start = getattr(config.web_push, 'quiet_start_utc', 21)
        quiet_end = getattr(config.web_push, 'quiet_end_utc', 6)
        if quiet_start <= hour_utc or hour_utc < quiet_end:
            return True

        conn = self._get_conn()
        if conn:
            try:
                cur = conn.cursor()
                # Daily cap: max 8 pushes (count T1/T2 alerts created today)
                daily_cap = getattr(config.web_push, 'daily_cap', 8)
                cur.execute("""
                    SELECT COUNT(*) FROM alerts
                    WHERE tier <= 2 AND created_at > CURRENT_DATE
                """)
                today_count = cur.fetchone()[0]
                if today_count >= daily_cap:
                    cur.close()
                    return True

                # Cooldown: 15 min between pushes
                cooldown_min = getattr(config.web_push, 'cooldown_minutes', 15)
                cur.execute("""
                    SELECT MAX(created_at) FROM alerts
                    WHERE tier <= 2 AND created_at > NOW() - INTERVAL '1 hour'
                """)
                last_push = cur.fetchone()[0]
                cur.close()
                if last_push:
                    elapsed = (now - last_push).total_seconds() / 60.0
                    if elapsed < cooldown_min:
                        return True
            except Exception as e:
                logger.debug(f"Throttle check failed (non-fatal): {e}")
            finally:
                self._put_conn(conn)

        return False

    def _send_web_push_all(self, alert_id: int, tier: int, title: str):
        """Send Web Push notification to all registered subscriptions."""
        import json as _json

        # Throttle check — T1 always breaks through
        if self._should_throttle_push(tier):
            logger.debug(f"Push throttled for alert {alert_id} (tier={tier})")
            return

        try:
            from pywebpush import webpush, WebPushException
        except ImportError:
            logger.debug("pywebpush not installed — skipping Web Push")
            return

        vapid_private = config.web_push.vapid_private_key
        vapid_email = config.web_push.vapid_contact_email
        if not vapid_private or not vapid_email:
            logger.debug("VAPID keys not configured — skipping Web Push")
            return

        subs = self.get_all_push_subscriptions()
        if not subs:
            return

        payload = _json.dumps({
            "id": alert_id,
            "tier": tier,
            "title": title[:200],
            "url": "/mobile",
        })

        for sub in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub["endpoint"],
                        "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                    },
                    data=payload,
                    vapid_private_key=vapid_private,
                    vapid_claims={"sub": f"mailto:{vapid_email}"},
                    timeout=5,
                )
            except WebPushException as e:
                if "410" in str(e) or "404" in str(e):
                    self.remove_push_subscription(sub["endpoint"])
                    logger.info(f"Removed expired push subscription: {sub['endpoint'][:60]}...")
                else:
                    logger.warning(f"Web Push failed for {sub['endpoint'][:60]}: {e}")
            except Exception as e:
                logger.warning(f"Web Push error: {e}")

    # -------------------------------------------------------
    # TRIP-INTELLIGENCE-1: Trip lifecycle
    # -------------------------------------------------------

    def _ensure_trips_table(self):
        """Create trips table. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trips (
                    id SERIAL PRIMARY KEY,
                    destination VARCHAR(200),
                    origin VARCHAR(200),
                    category VARCHAR(20) DEFAULT 'meeting',
                    status VARCHAR(20) DEFAULT 'planned',
                    start_date DATE,
                    end_date DATE,
                    event_name VARCHAR(200),
                    strategic_objective TEXT,
                    calendar_event_ids JSONB DEFAULT '[]',
                    notes JSONB DEFAULT '[]',
                    auto_context JSONB DEFAULT '[]',
                    outcomes JSONB DEFAULT '[]',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_trips_status
                ON trips(status) WHERE status IN ('planned', 'confirmed')
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_trips_dates
                ON trips(start_date, end_date)
            """)
            conn.commit()
            cur.close()
            logger.info("Trips table verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure trips table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_trip_contacts_table(self):
        """Create trip_contacts table. Idempotent."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trip_contacts (
                    id SERIAL PRIMARY KEY,
                    trip_id INTEGER REFERENCES trips(id) ON DELETE CASCADE,
                    contact_id INTEGER REFERENCES vip_contacts(id),
                    role VARCHAR(50),
                    roi_type VARCHAR(50),
                    roi_score INTEGER,
                    outreach_status VARCHAR(20) DEFAULT 'none',
                    notes TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_trip_contacts_trip
                ON trip_contacts(trip_id)
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_trip_contacts_unique
                ON trip_contacts(trip_id, contact_id)
            """)
            conn.commit()
            cur.close()
            logger.info("Trip contacts table verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure trip_contacts table: {e}")
        finally:
            self._put_conn(conn)

    def _seed_location_preferences(self):
        """Seed commute/home city preferences if not already set."""
        seeds = [
            ("domain_context", "commute_cities", "Vienna, Frankfurt"),
            ("domain_context", "home_city", "Zurich"),
            ("domain_context", "home_cities", "Zurich, Geneva"),
        ]
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            for category, key, value in seeds:
                cur.execute(
                    """INSERT INTO director_preferences (category, pref_key, pref_value)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (category, pref_key) DO NOTHING""",
                    (category, key, value),
                )
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.debug(f"Location preference seeding skipped: {e}")
        finally:
            self._put_conn(conn)

    def upsert_trip(self, destination: str, origin: str = None,
                    start_date=None, end_date=None, category: str = "meeting",
                    calendar_event_ids: list = None, event_name: str = None,
                    strategic_objective: str = None) -> Optional[dict]:
        """Create or match a trip. Idempotent by destination + overlapping dates.
        Returns the trip dict."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Try to find existing trip by calendar_event_id
            if calendar_event_ids:
                for cal_id in calendar_event_ids:
                    if cal_id:
                        cur.execute(
                            """SELECT * FROM trips
                               WHERE calendar_event_ids ? %s
                                 AND status IN ('planned', 'confirmed')
                               LIMIT 1""",
                            (cal_id,),
                        )
                        existing = cur.fetchone()
                        if existing:
                            cur.close()
                            return dict(existing)

            # Try to find by destination + overlapping dates
            if destination and start_date:
                cur.execute(
                    """SELECT * FROM trips
                       WHERE LOWER(destination) = LOWER(%s)
                         AND status IN ('planned', 'confirmed')
                         AND start_date <= %s::date + INTERVAL '1 day'
                         AND (end_date IS NULL OR end_date >= %s::date - INTERVAL '1 day')
                       LIMIT 1""",
                    (destination, start_date, start_date),
                )
                existing = cur.fetchone()
                if existing:
                    # Merge calendar_event_ids
                    if calendar_event_ids:
                        merged = list(set(
                            (existing.get("calendar_event_ids") or []) + calendar_event_ids
                        ))
                        cur.execute(
                            "UPDATE trips SET calendar_event_ids = %s::jsonb, updated_at = NOW() WHERE id = %s",
                            (json.dumps(merged), existing["id"]),
                        )
                        conn.commit()
                    cur.close()
                    return dict(existing)

            # Create new trip
            cal_ids_json = json.dumps(calendar_event_ids or [])
            cur.execute(
                """INSERT INTO trips (destination, origin, category, start_date, end_date,
                                      event_name, strategic_objective, calendar_event_ids)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                   RETURNING *""",
                (destination, origin, category, start_date, end_date,
                 event_name, strategic_objective, cal_ids_json),
            )
            trip = dict(cur.fetchone())
            conn.commit()
            cur.close()
            logger.info(f"Created trip #{trip['id']}: {destination} ({start_date})")
            return trip
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"upsert_trip failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def get_active_trips(self) -> list:
        """All trips with status planned/confirmed, plus completed trips still in progress.
        Completed trips disappear the day after end_date (same logic as travel alert midnight-CET expiry)."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT * FROM trips
                WHERE status IN ('planned', 'confirmed')
                   OR (status = 'completed' AND COALESCE(end_date, start_date) >= CURRENT_DATE)
                ORDER BY start_date ASC NULLS LAST
                LIMIT 50
            """)
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        except Exception as e:
            logger.error(f"get_active_trips failed: {e}")
            return []
        finally:
            self._put_conn(conn)

    def get_trip(self, trip_id: int) -> Optional[dict]:
        """Get a single trip with its contacts."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM trips WHERE id = %s", (trip_id,))
            trip = cur.fetchone()
            if not trip:
                cur.close()
                return None
            trip = dict(trip)

            # Fetch linked contacts with VIP profile data
            cur.execute("""
                SELECT tc.*, vc.name as contact_name, vc.role as contact_role,
                       vc.tier as contact_tier, vc.role_context as contact_role_context,
                       vc.expertise as contact_expertise
                FROM trip_contacts tc
                LEFT JOIN vip_contacts vc ON vc.id = tc.contact_id
                WHERE tc.trip_id = %s
                ORDER BY tc.roi_score DESC NULLS LAST
            """, (trip_id,))
            trip["contacts"] = [dict(r) for r in cur.fetchall()]
            cur.close()
            return trip
        except Exception as e:
            logger.error(f"get_trip failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def update_trip(self, trip_id: int, **kwargs) -> Optional[dict]:
        """Partial update of a trip. Returns updated trip dict."""
        allowed = {"destination", "origin", "category", "status", "start_date",
                    "end_date", "event_name", "strategic_objective"}
        conn = self._get_conn()
        if not conn:
            return None
        try:
            set_parts = []
            values = []
            for k, v in kwargs.items():
                if k in allowed and v is not None:
                    set_parts.append(f"{k} = %s")
                    values.append(v)
            if not set_parts:
                return self.get_trip(trip_id)
            set_parts.append("updated_at = NOW()")
            values.append(trip_id)

            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                f"UPDATE trips SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                values,
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            if row:
                logger.info(f"Updated trip #{trip_id}: {list(kwargs.keys())}")
                return dict(row)
            return None
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"update_trip failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def add_trip_note(self, trip_id: int, text: str, source: str = "manual") -> bool:
        """Append a note to a trip's notes JSONB array."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            note = json.dumps({
                "text": text,
                "source": source,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            cur = conn.cursor()
            cur.execute(
                """UPDATE trips
                   SET notes = notes || %s::jsonb,
                       updated_at = NOW()
                   WHERE id = %s""",
                (f"[{note}]", trip_id),
            )
            affected = cur.rowcount
            conn.commit()
            cur.close()
            return affected > 0
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"add_trip_note failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    def add_trip_contact(self, trip_id: int, contact_id: int,
                         role: str = "counterparty", roi_type: str = None,
                         roi_score: int = None, notes: str = None) -> Optional[dict]:
        """Add a contact to a trip. Returns the trip_contact row or None."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                INSERT INTO trip_contacts (trip_id, contact_id, role, roi_type, roi_score, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (trip_id, contact_id) DO UPDATE SET
                    role = COALESCE(EXCLUDED.role, trip_contacts.role),
                    roi_type = COALESCE(EXCLUDED.roi_type, trip_contacts.roi_type),
                    roi_score = COALESCE(EXCLUDED.roi_score, trip_contacts.roi_score),
                    notes = COALESCE(EXCLUDED.notes, trip_contacts.notes)
                RETURNING *
            """, (trip_id, contact_id, role, roi_type, roi_score, notes))
            row = cur.fetchone()
            conn.commit()
            # Fetch the contact name for the response
            if row:
                row = dict(row)
                cur.execute("SELECT name, role FROM vip_contacts WHERE id = %s", (contact_id,))
                vc = cur.fetchone()
                if vc:
                    row["contact_name"] = vc["name"]
                    row["contact_role"] = vc["role"]
            cur.close()
            logger.info(f"Added contact #{contact_id} to trip #{trip_id}")
            return row
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"add_trip_contact failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def link_to_trip_context(self, content: str, source_type: str,
                              source_ref: str, timestamp=None) -> Optional[int]:
        """TRIP-INTELLIGENCE-1: Auto-link content to an active trip if it mentions the destination.
        Appends to trip.auto_context JSONB. Returns trip_id if linked, None otherwise."""
        if not content:
            return None
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Get active trips
            cur.execute("""
                SELECT id, destination, start_date, end_date
                FROM trips
                WHERE status IN ('planned', 'confirmed')
                  AND destination IS NOT NULL
                LIMIT 20
            """)
            trips = cur.fetchall()
            content_lower = content.lower()

            for trip in trips:
                dest = (trip["destination"] or "").lower()
                if not dest or len(dest) < 3:
                    continue
                if dest not in content_lower:
                    continue

                # Found a match — append to auto_context
                ctx_entry = json.dumps({
                    "type": source_type,
                    "ref": source_ref,
                    "summary": content[:200],
                    "timestamp": str(timestamp) if timestamp else datetime.now(timezone.utc).isoformat(),
                })
                cur.execute(
                    """UPDATE trips
                       SET auto_context = auto_context || %s::jsonb,
                           updated_at = NOW()
                       WHERE id = %s""",
                    (f"[{ctx_entry}]", trip["id"]),
                )
                conn.commit()
                cur.close()
                logger.debug(f"Linked content to trip #{trip['id']} ({trip['destination']})")
                return trip["id"]

            cur.close()
            return None
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.debug(f"link_to_trip_context failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def auto_complete_trips(self) -> int:
        """Auto-complete trips where end_date has passed. Returns count updated."""
        conn = self._get_conn()
        if not conn:
            return 0
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE trips
                SET status = 'completed', updated_at = NOW()
                WHERE status = 'confirmed'
                  AND end_date < CURRENT_DATE - INTERVAL '1 day'
            """)
            count = cur.rowcount
            conn.commit()
            cur.close()
            if count > 0:
                logger.info(f"Auto-completed {count} trips")
            return count
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"auto_complete_trips failed: {e}")
            return 0
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # Browser Actions (BROWSER-AGENT-1 Phase 3)
    # -------------------------------------------------------

    def _ensure_browser_actions_table(self):
        """Create browser_actions table if not exists."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS browser_actions (
                    id SERIAL PRIMARY KEY,
                    action_type VARCHAR(20) NOT NULL,
                    url TEXT,
                    target_selector TEXT,
                    target_text TEXT,
                    fill_value TEXT,
                    description TEXT NOT NULL,
                    screenshot_b64 TEXT,
                    status VARCHAR(30) DEFAULT 'pending_confirmation',
                    alert_id INTEGER,
                    baker_task_id INTEGER,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    confirmed_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    expires_at TIMESTAMPTZ,
                    result TEXT,
                    error TEXT
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_ba_status
                ON browser_actions(status) WHERE status = 'pending_confirmation'
            """)
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure browser_actions table: {e}")
        finally:
            self._put_conn(conn)

    def create_browser_action(self, action_type: str, description: str,
                              url: str = None, target_selector: str = None,
                              target_text: str = None, fill_value: str = None,
                              screenshot_b64: str = None,
                              baker_task_id: int = None) -> Optional[int]:
        """Queue a browser action for Director confirmation.

        Returns the action ID, or None on failure.
        """
        self._ensure_browser_actions_table()
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO browser_actions
                    (action_type, url, target_selector, target_text,
                     fill_value, description, screenshot_b64, status,
                     baker_task_id, created_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending_confirmation', %s, NOW(), NOW() + INTERVAL '10 minutes')
                RETURNING id
                """,
                (action_type, url, target_selector, target_text,
                 fill_value, description, screenshot_b64, baker_task_id),
            )
            action_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            logger.info(f"Created browser_action #{action_id}: {action_type} — {description[:60]}")
            return action_id
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"create_browser_action failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def get_browser_action(self, action_id: int) -> Optional[dict]:
        """Get a browser action by ID."""
        self._ensure_browser_actions_table()
        conn = self._get_conn()
        if not conn:
            return None
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM browser_actions WHERE id = %s", (action_id,))
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_browser_action failed: {e}")
            return None
        finally:
            self._put_conn(conn)

    def get_pending_browser_actions(self) -> list:
        """Get all pending browser actions (not expired)."""
        self._ensure_browser_actions_table()
        conn = self._get_conn()
        if not conn:
            return []
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Auto-expire old actions
            cur.execute("""
                UPDATE browser_actions SET status = 'expired'
                WHERE status = 'pending_confirmation' AND expires_at < NOW()
            """)
            conn.commit()
            cur.execute("""
                SELECT id, action_type, url, target_selector, target_text,
                       fill_value, description, status, alert_id,
                       created_at, expires_at
                FROM browser_actions
                WHERE status = 'pending_confirmation'
                ORDER BY created_at DESC
                LIMIT 20
            """)
            rows = cur.fetchall()
            cur.close()
            return [dict(r) for r in rows]
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"get_pending_browser_actions failed: {e}")
            return []
        finally:
            self._put_conn(conn)

    def update_browser_action(self, action_id: int, status: str,
                              result: str = None, error: str = None) -> bool:
        """Update a browser action's status."""
        self._ensure_browser_actions_table()
        conn = self._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            ts_field = ""
            if status == "confirmed":
                ts_field = ", confirmed_at = NOW()"
            elif status in ("completed", "failed", "cancelled", "expired"):
                ts_field = ", completed_at = NOW()"
            cur.execute(
                f"""
                UPDATE browser_actions
                SET status = %s, result = COALESCE(%s, result),
                    error = COALESCE(%s, error) {ts_field}
                WHERE id = %s
                """,
                (status, result, error, action_id),
            )
            conn.commit()
            cur.close()
            return True
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"update_browser_action failed: {e}")
            return False
        finally:
            self._put_conn(conn)

    # -------------------------------------------------------
    # KBL-A infrastructure (schema — §5 of KBL-A brief)
    # -------------------------------------------------------

    def _ensure_signal_queue_base(self):
        """KBL-19 base table (Cortex 3T bridge between Tier 1 and Tier 2).

        Creates signal_queue from the KBL-19 spec if it doesn't already exist.
        Idempotent via CREATE TABLE IF NOT EXISTS. KBL-A additions in
        _ensure_signal_queue_additions layer on top. id stays SERIAL (INTEGER)
        per KBL-A §5 FK reconciliation decision.
        """
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS signal_queue (
                    id                SERIAL PRIMARY KEY,
                    created_at        TIMESTAMPTZ DEFAULT NOW(),
                    source            TEXT,
                    signal_type       TEXT,
                    matter            TEXT,
                    summary           TEXT,
                    triage_score      INT,
                    vedana            TEXT,
                    hot_md_match      TEXT,
                    payload           JSONB,
                    priority          TEXT DEFAULT 'normal',
                    status            TEXT DEFAULT 'pending',
                    stage             TEXT,
                    enriched_summary  TEXT,
                    result            TEXT,
                    wiki_page_path    TEXT,
                    card_id           TEXT,
                    ayoniso_alert     BOOLEAN DEFAULT FALSE,
                    ayoniso_type      TEXT,
                    processed_at      TIMESTAMPTZ,
                    ttl_expires_at    TIMESTAMPTZ
                )
            """)
            conn.commit()
            cur.close()
            logger.info("signal_queue base table verified (KBL-19)")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure signal_queue base table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_signal_queue_additions(self):
        """KBL-A §5: additive columns + expanded CHECK + 3 indexes on signal_queue."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            # Columns (additive, idempotent)
            cur.execute("ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS primary_matter TEXT")
            cur.execute(
                "ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS related_matters JSONB "
                "NOT NULL DEFAULT '[]'::jsonb"
            )
            cur.execute(
                "ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS triage_confidence NUMERIC(3,2)"
            )
            # R1.B1: started_at for claim-time latency metrics
            cur.execute("ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ")

            # BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1 (2026-04-21 evening):
            # Reconcile hot_md_match type if a legacy bootstrap DDL
            # created it as BOOLEAN. BRIDGE_HOT_MD_AND_TUNING_1 semantics
            # require TEXT (the verbatim matched pattern line), but the
            # pre-existing BOOLEAN declaration in `_ensure_signal_queue_base`
            # caused `ADD COLUMN IF NOT EXISTS hot_md_match TEXT` in
            # 20260421_signal_queue_hot_md_match.sql to silently no-op.
            # Defense-in-depth layer on top of the
            # 20260421b_alter_hot_md_match_to_text.sql migration: even if
            # the migration ledger is stale for whatever reason, the
            # bootstrap self-heals the live column to TEXT on every boot.
            # Idempotent: no-op when already TEXT.
            cur.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                         WHERE table_name = 'signal_queue'
                           AND column_name = 'hot_md_match'
                           AND data_type  = 'boolean'
                    ) THEN
                        ALTER TABLE signal_queue
                            ALTER COLUMN hot_md_match TYPE TEXT
                            USING hot_md_match::text;
                    END IF;
                END $$;
                """
            )

            # triage_confidence range CHECK
            cur.execute(
                "ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_triage_confidence_range"
            )
            cur.execute("""
                ALTER TABLE signal_queue ADD CONSTRAINT signal_queue_triage_confidence_range
                CHECK (triage_confidence IS NULL OR (triage_confidence >= 0 AND triage_confidence <= 1))
            """)

            # Expanded status CHECK: KBL-A 8 legacy + KBL-B 26 per-step states.
            # Mirror of migrations/20260418_expand_signal_queue_status_check.sql
            # — the two MUST stay in sync. Keeps this constraint re-asserted
            # on every app boot so the migration can't be silently reverted.
            cur.execute("ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_status_check")
            cur.execute("""
                ALTER TABLE signal_queue ADD CONSTRAINT signal_queue_status_check
                CHECK (status IN (
                    -- KBL-A legacy
                    'pending','processing','done','failed','expired',
                    'classified-deferred','failed-reviewed','cost-deferred',
                    -- KBL-B Layer 0
                    'dropped_layer0',
                    -- KBL-B Step 1 triage
                    'awaiting_triage','triage_running','triage_failed','triage_invalid',
                    'routed_inbox',
                    -- KBL-B Step 2 resolve
                    'awaiting_resolve','resolve_running','resolve_failed',
                    -- KBL-B Step 3 extract
                    'awaiting_extract','extract_running','extract_failed',
                    -- KBL-B Step 4 classify
                    'awaiting_classify','classify_running','classify_failed',
                    -- KBL-B Step 5 opus
                    'awaiting_opus','opus_running','opus_failed','paused_cost_cap',
                    -- KBL-B Step 6 finalize
                    'awaiting_finalize','finalize_running','finalize_failed',
                    -- KBL-B Step 7 commit
                    'awaiting_commit','commit_running','commit_failed',
                    -- KBL-B terminal
                    'completed'
                ))
            """)

            # Indexes
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_queue_primary_matter
                    ON signal_queue (primary_matter)
                    WHERE primary_matter IS NOT NULL
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_queue_related_matters_gin
                    ON signal_queue USING gin (related_matters)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_queue_status_priority
                    ON signal_queue (status, priority, created_at)
            """)
            conn.commit()
            cur.close()
            logger.info("signal_queue KBL-A additions applied (4 columns, 2 CHECKs, 3 indexes)")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure signal_queue KBL-A additions: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_kbl_runtime_state(self):
        """KBL-A §5 / D8: key-value runtime flags. Seeded with 6 boot defaults."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kbl_runtime_state (
                    key         TEXT PRIMARY KEY,
                    value       TEXT NOT NULL,
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_by  TEXT
                )
            """)
            # Seed canonical keys; ON CONFLICT preserves live values across re-runs.
            cur.execute("""
                INSERT INTO kbl_runtime_state (key, value, updated_by) VALUES
                    ('anthropic_circuit_open', 'false', 'kbl_a_bootstrap'),
                    ('anthropic_5xx_counter',  '0',     'kbl_a_bootstrap'),
                    ('qwen_active',            'false', 'kbl_a_bootstrap'),
                    ('qwen_active_since',      '',      'kbl_a_bootstrap'),
                    ('qwen_swap_count_today',  '0',     'kbl_a_bootstrap'),
                    ('mac_mini_heartbeat',     '',      'kbl_a_bootstrap')
                ON CONFLICT (key) DO NOTHING
            """)
            conn.commit()
            cur.close()
            logger.info("kbl_runtime_state table verified (6 seed keys)")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure kbl_runtime_state table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_kbl_alert_dedupe(self):
        """KBL-A §5: 5-min bucket dedupe for CRITICAL alerts (D15) and
        cost threshold alerts (D14 — 80/95/100%% day-scoped).
        Purged nightly via scripts/kbl-purge-dedupe.sh on Mac Mini."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kbl_alert_dedupe (
                    alert_key   TEXT PRIMARY KEY,
                    first_seen  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_sent   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    send_count  INTEGER NOT NULL DEFAULT 1
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_alert_dedupe_last_sent
                    ON kbl_alert_dedupe (last_sent)
            """)
            conn.commit()
            cur.close()
            logger.info("kbl_alert_dedupe table verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure kbl_alert_dedupe table: {e}")
        finally:
            self._put_conn(conn)

    def _ensure_gold_promote_queue(self):
        """KBL-A §5 / D2: Director /gold WhatsApp promotion queue.
        WAHA inserts, Mac Mini cron drains via FOR UPDATE SKIP LOCKED."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gold_promote_queue (
                    id            SERIAL PRIMARY KEY,
                    path          TEXT NOT NULL,
                    requested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    wa_msg_id     TEXT,
                    processed_at  TIMESTAMPTZ,
                    result        TEXT,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_gold_queue_pending
                    ON gold_promote_queue (requested_at)
                    WHERE processed_at IS NULL
            """)
            conn.commit()
            cur.close()
            logger.info("gold_promote_queue table verified")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not ensure gold_promote_queue table: {e}")
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
