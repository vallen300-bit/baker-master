"""
ART-1: Auto-Research Trigger (Session 30)

Detects when a VIP WhatsApp message contains forwarded intelligence
about a person, company, or legal matter that would benefit from a
multi-specialist research dossier.

Flow:
  1. VIP WhatsApp arrives (tier <= 2, >200 chars)
  2. Haiku classifies: is this a research trigger?
  3. If yes → create research_proposal (status='proposed')
  4. Dashboard card + push: "Shall I run a full dossier on [subject]?"
  5. Director taps "Run Dossier" → execution engine (Batch 2)

Cost: ~EUR 0.01 per classification (Haiku). Only runs on VIP messages >200 chars.
"""
import json
import logging
from datetime import datetime, timezone

import anthropic

from config.settings import config

logger = logging.getLogger("baker.research_trigger")


# ─────────────────────────────────────────────────
# Table setup
# ─────────────────────────────────────────────────

def _ensure_research_proposals_table():
    """Create research_proposals table if not exists."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS research_proposals (
                    id SERIAL PRIMARY KEY,
                    trigger_source VARCHAR(20),
                    trigger_ref TEXT,
                    subject_name TEXT NOT NULL,
                    subject_type VARCHAR(20),
                    context TEXT,
                    specialists JSONB,
                    status VARCHAR(20) DEFAULT 'proposed',
                    director_customization JSONB,
                    deliverable_path TEXT,
                    deliverable_summary TEXT,
                    error_message TEXT,
                    send_to JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    approved_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_rp_status
                ON research_proposals(status) WHERE status IN ('proposed', 'running')
            """)
            # Migration: add error_message column if table already exists without it
            cur.execute("""
                ALTER TABLE research_proposals ADD COLUMN IF NOT EXISTS error_message TEXT
            """)
            # DOSSIER-PIPELINE-1: Add matter_slug column for matter linking
            cur.execute("""
                ALTER TABLE research_proposals ADD COLUMN IF NOT EXISTS matter_slug TEXT
            """)
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Could not ensure research_proposals table: {e}")


# ─────────────────────────────────────────────────
# Haiku classification
# ─────────────────────────────────────────────────

_CLASSIFY_PROMPT = """You are Baker, AI Chief of Staff for the Chairman of Brisen Group (luxury real estate, hotel development).

Analyze this message and determine if Baker should proactively research any people, companies, or matters mentioned. There are TWO trigger types:

TYPE 1 — FORWARDED INTELLIGENCE:
Message contains forwarded/copy-pasted content about a person, company, or legal matter (articles, legal letters, competitor info, media coverage). Always trigger.

TYPE 2 — NEW COUNTERPARTY / MEETING PREP:
Message mentions specific people with company affiliations who the Director will meet, negotiate with, or needs to understand. This includes: investor representatives, counterparties, developers, lawyers, brokers, or anyone the Director hasn't dealt with before. These people need profiling BEFORE the meeting.

Criteria for YES (either type):
- Names specific people with company/role context
- People are counterparties, investors, developers, lawyers, or new business contacts
- An upcoming meeting, visit, or negotiation is mentioned or implied
- The context involves deals, disputes, acquisitions, litigation, or investment
- Contains forwarded articles, legal documents, media coverage, or business intelligence

Criteria for NO:
- Only mentions people the Director works with daily (internal team)
- Pure logistics (restaurant, flight, hotel booking) with no counterparty context
- Casual greetings, birthday wishes, personal chat
- Message is only about scheduling without naming new external parties

If YES, return:
{"is_trigger": true, "trigger_type": "intelligence|meeting_prep", "subject_name": "Full Name or Company", "subject_type": "person|company|legal_matter", "context": "One sentence: who they are, why they matter, what's the business context", "suggested_specialists": ["research", "profiling", "legal", "pr_branding"]}

For meeting_prep triggers, always include "profiling" in suggested_specialists.
If multiple people need profiling, use the most senior person as subject_name and mention others in context.

If NO, return:
{"is_trigger": false}

Return ONLY valid JSON, nothing else."""


def _get_matter_context_for_classification() -> str:
    """Get a brief summary of active matters to help Haiku understand business context."""
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return ""
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT matter_name, description, keywords
                FROM matter_registry
                WHERE status = 'active'
                ORDER BY matter_name
                LIMIT 20
            """)
            matters = cur.fetchall()
            cur.close()
            if not matters:
                return ""
            lines = ["\n\nACTIVE BUSINESS MATTERS (use this context to assess importance):"]
            for m in matters:
                keywords = m.get("keywords") or []
                if isinstance(keywords, str):
                    try:
                        keywords = json.loads(keywords)
                    except Exception:
                        keywords = []
                kw = ", ".join(keywords[:5]) if keywords else ""
                desc = m.get("description", "")[:100]
                lines.append(f"- {m['matter_name']}: {desc}" + (f" [{kw}]" if kw else ""))
            return "\n".join(lines)
        finally:
            store._put_conn(conn)
    except Exception:
        return ""


def classify_research_trigger(message_body: str, sender_name: str) -> dict:
    """Classify if a message is a research trigger. Returns classification dict."""
    if not message_body or len(message_body) < 200:
        return {"is_trigger": False}

    try:
        # Inject active matters for business context
        matter_context = _get_matter_context_for_classification()

        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=_CLASSIFY_PROMPT + matter_context,
            messages=[{"role": "user", "content": f"From: {sender_name}\n\n{message_body[:3000]}"}],
        )

        # Log cost
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(
                "claude-haiku-4-5-20251001", resp.usage.input_tokens,
                resp.usage.output_tokens, source="research_trigger_classify",
            )
        except Exception:
            pass

        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        result = json.loads(raw)
        return result

    except json.JSONDecodeError:
        logger.debug("Research trigger classification: JSON parse failed")
        return {"is_trigger": False}
    except Exception as e:
        logger.debug(f"Research trigger classification failed: {e}")
        return {"is_trigger": False}


# ─────────────────────────────────────────────────
# Proposal creation
# ─────────────────────────────────────────────────

def create_research_proposal(
    classification: dict,
    trigger_source: str = "whatsapp",
    trigger_ref: str = None,
    sender_name: str = None,
) -> int:
    """Create a research proposal from classification result. Returns proposal ID or None."""
    _ensure_research_proposals_table()

    if not classification.get("is_trigger"):
        return None

    subject_name = classification.get("subject_name", "Unknown")
    subject_type = classification.get("subject_type", "person")
    context = classification.get("context", "")
    specialists = classification.get("suggested_specialists", ["research", "legal", "profiling"])

    # Dedup: don't re-propose same subject within 7 days
    # Fuzzy: extract primary name (first word or name before "/" or "(") and match
    def _extract_primary_name(name: str) -> str:
        """Extract the core subject name for dedup matching."""
        # "Patrick Piras / Core Service SA / Brisengroup" → "Patrick Piras"
        # "Bernhard Steinkopf (Campus Schlüterstrasse)" → "Bernhard Steinkopf"
        # "Hagenauer" → "Hagenauer"
        n = name.strip()
        for sep in ("/", "(", " - ", " — ", " and ", " & "):
            if sep in n:
                n = n.split(sep)[0].strip()
        # Remove trailing punctuation
        n = n.rstrip(" ,;:")
        return n

    primary_name = _extract_primary_name(subject_name)

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            # Fuzzy dedup: check if any proposal contains this primary name
            cur.execute("""
                SELECT id, subject_name FROM research_proposals
                WHERE (LOWER(subject_name) LIKE %s OR LOWER(%s) LIKE '%%' || LOWER(subject_name) || '%%')
                  AND status NOT IN ('skipped')
                  AND created_at > NOW() - INTERVAL '7 days'
                LIMIT 1
            """, (f"%{primary_name.lower()}%", primary_name.lower()))
            existing = cur.fetchone()
            if existing:
                logger.info(f"Research proposal for '{subject_name}' matches existing '{existing[1]}' (id={existing[0]}) — skipping")
                cur.close()
                return None

            # Insert
            cur.execute("""
                INSERT INTO research_proposals
                    (trigger_source, trigger_ref, subject_name, subject_type,
                     context, specialists)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                trigger_source,
                trigger_ref,
                subject_name[:200],
                subject_type[:20],
                context[:500],
                json.dumps(specialists),
            ))
            proposal_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            logger.info(f"Research proposal created: id={proposal_id}, subject='{subject_name}'")
            return proposal_id
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"create_research_proposal failed: {e}")
        return None


def _notify_research_proposal(proposal_id: int, subject_name: str, context: str, specialists: list):
    """Create dashboard alert with structured_actions for research proposal."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()

        specialist_names = {
            "research": "Research", "legal": "Legal",
            "profiling": "People Intel", "pr_branding": "PR & Branding",
            "asset_management": "Asset Mgmt", "finance": "Finance",
            "sales": "Sales", "communications": "Communications",
        }
        spec_list = ", ".join(specialist_names.get(s, s) for s in specialists)

        alert_body = (
            f"**Intelligence detected about {subject_name}.**\n\n"
            f"{context}\n\n"
            f"**Proposed specialists:** {spec_list}"
        )

        structured = {
            "research_proposal_id": proposal_id,
            "subject_name": subject_name,
            "specialists": specialists,
        }

        store.create_alert(
            tier=2,
            title=f"Research dossier: {subject_name}",
            body=alert_body,
            action_required=True,
            tags=["research"],
            source="research",
            source_id=f"research-proposal-{proposal_id}",
            structured_actions=structured,
        )
        logger.info(f"Research proposal alert created for '{subject_name}'")
    except Exception as e:
        logger.warning(f"Research proposal notification failed: {e}")


# ─────────────────────────────────────────────────
# Content pre-filter (cheap regex gate before Haiku)
# ─────────────────────────────────────────────────

import re as _re

# Patterns that suggest intelligence or counterparty profiling need
_INTELLIGENCE_PATTERNS = _re.compile(
    r'(?:'
    r'forwarded|weitergeleitet|'       # forwarded message markers
    r'FW:|Fwd:|WG:|'                   # email forward prefixes
    r'lawsuit|litigation|Klage|Rechtsstreit|'  # legal
    r'acquisition|Akquisition|Übernahme|'      # deals
    r'due\s*diligence|term\s*sheet|LOI|'       # deal terms
    r'article|Artikel|press|Presse|media|'     # media coverage
    r'court|Gericht|arbitration|Schiedsgericht|'  # courts
    r'claim|Forderung|dispute|Streit|'         # disputes
    r'competitor|Wettbewerber|'                # competitive intel
    r'investigation|Ermittlung|'               # investigations
    r'bankrupt|Insolvenz|insolvent|'           # financial distress
    r'fraud|Betrug|'                           # fraud
    r'regulatory|Regulierung|compliance|'      # regulatory
    r'counterparty|Gegenpartei|'               # counterparties
    r'subcontractor|Subunternehmer|Nachunternehmer|'  # construction
    r'ImmoFokus|Immobilien|Gewerbe|'           # real estate media
    r'GmbH|AG|Ltd|LLC|Corp|S\.A\.|'           # company suffixes
    r'Dr\.|Mag\.|RA\s|Rechtsanwalt|'          # professional titles
    r'managing\s*director|Geschäftsführer|'    # executive titles
    r'CEO|CFO|COO|CTO|partner|director|'       # C-suite
    r'investor|Investor|representatives|'       # investor context
    r'visit|Besuch|meeting\s*with|treffen|'    # upcoming meetings
    r'negotiate|Verhandlung|'                  # negotiations
    r'developer|Entwickler|Bauträger|'         # developers
    r'project\s+[A-Z]|Projekt\s+[A-Z]'        # named projects
    r')',
    _re.IGNORECASE
)

# Patterns that suggest casual/non-research content
_CASUAL_PATTERNS = _re.compile(
    r'(?:'
    r'good\s*morning|guten\s*morgen|'
    r'happy\s*birthday|alles\s*gute|'
    r'restaurant|dinner|lunch|breakfast|'
    r'thank\s*you|danke|merci|'
    r'see\s*you|bis\s*bald|'
    r'flight\s*landed|arrived|angekommen'
    r')',
    _re.IGNORECASE
)


def _passes_content_prefilter(message_body: str) -> bool:
    """
    Cheap regex pre-filter: does the message look like it might contain
    forwarded intelligence? This runs before the Haiku classification
    to keep costs near zero on casual messages.
    """
    if not message_body or len(message_body) < 200:
        return False

    # Must have at least one intelligence-related pattern
    if not _INTELLIGENCE_PATTERNS.search(message_body):
        return False

    # If it's overwhelmingly casual, skip
    casual_matches = len(_CASUAL_PATTERNS.findall(message_body))
    intel_matches = len(_INTELLIGENCE_PATTERNS.findall(message_body))
    if casual_matches > intel_matches and casual_matches >= 3:
        return False

    return True


# ─────────────────────────────────────────────────
# Main hook — called from waha_webhook.py
# ─────────────────────────────────────────────────

def check_research_trigger(message_body: str, sender_name: str, msg_id: str, tier: int = 3):
    """
    Check if a WhatsApp message contains forwarded intelligence worthy
    of a multi-specialist research dossier.

    Content-driven (not sender-driven): any message >200 chars that passes
    the regex pre-filter gets classified by Haiku. The pre-filter costs
    nothing; the Haiku call costs ~EUR 0.01 and only fires when the
    content looks like intelligence.
    """
    if not message_body or len(message_body) < 200:
        return

    # Cheap regex pre-filter — skip casual messages
    if not _passes_content_prefilter(message_body):
        return

    try:
        classification = classify_research_trigger(message_body, sender_name)
        if not classification.get("is_trigger"):
            logger.debug(f"WhatsApp from {sender_name}: not a research trigger (Haiku rejected)")
            return

        logger.info(f"Research trigger detected from {sender_name}: {classification.get('subject_name')}")

        proposal_id = create_research_proposal(
            classification=classification,
            trigger_source="whatsapp",
            trigger_ref=f"wa-{msg_id}",
            sender_name=sender_name,
        )

        if proposal_id:
            _notify_research_proposal(
                proposal_id,
                classification.get("subject_name", "Unknown"),
                classification.get("context", ""),
                classification.get("suggested_specialists", []),
            )

    except Exception as e:
        logger.warning(f"Research trigger check failed (non-fatal): {e}")


# ─────────────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────────────

def get_research_proposals(status: str = None, days: int = 14) -> list:
    """Get research proposals for API/dashboard."""
    _ensure_research_proposals_table()
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if status:
                cur.execute(f"""
                    SELECT * FROM research_proposals
                    WHERE status = %s
                      AND created_at > NOW() - INTERVAL '{int(days)} days'
                    ORDER BY created_at DESC LIMIT 50
                """, (status,))
            else:
                cur.execute(f"""
                    SELECT * FROM research_proposals
                    WHERE created_at > NOW() - INTERVAL '{int(days)} days'
                    ORDER BY created_at DESC LIMIT 50
                """)
            results = []
            for r in cur.fetchall():
                row = dict(r)
                for key in ("created_at", "approved_at", "completed_at"):
                    if row.get(key) and hasattr(row[key], "isoformat"):
                        row[key] = row[key].isoformat()
                results.append(row)
            cur.close()
            return results
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"get_research_proposals failed: {e}")
        return []


def respond_to_research_proposal(proposal_id: int, response: str) -> bool:
    """Approve or skip a research proposal."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            now = datetime.now(timezone.utc)
            if response == "approved":
                cur.execute("""
                    UPDATE research_proposals
                    SET status = 'approved', approved_at = %s
                    WHERE id = %s
                """, (now, proposal_id))
            elif response == "skipped":
                cur.execute("""
                    UPDATE research_proposals
                    SET status = 'skipped'
                    WHERE id = %s
                """, (proposal_id,))
            else:
                return False
            conn.commit()
            cur.close()
            return True
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"respond_to_research_proposal failed: {e}")
        return False
