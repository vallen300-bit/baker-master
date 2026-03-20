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
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Could not ensure research_proposals table: {e}")


# ─────────────────────────────────────────────────
# Haiku classification
# ─────────────────────────────────────────────────

_CLASSIFY_PROMPT = """You are Baker, AI Chief of Staff. Analyze this WhatsApp message and determine if it contains forwarded or copy-pasted intelligence about a person, company, or legal matter that would benefit from a multi-specialist research dossier.

Criteria for YES:
- Contains forwarded/copy-pasted content (not casual conversation)
- About an identifiable person OR company OR legal matter
- Contains claims, legal actions, media coverage, business intelligence, or counterparty information
- Would benefit from deep research (profiling, legal analysis, PR/media scan, background check)

Criteria for NO:
- Casual conversation, greetings, scheduling
- Simple status updates or questions
- Already-processed information (meeting notes, task updates)
- Short messages (<3 sentences of substance)

If YES, return:
{"is_trigger": true, "subject_name": "Full Name or Company", "subject_type": "person|company|legal_matter", "context": "One sentence explaining what was forwarded and why it matters", "suggested_specialists": ["research", "legal", "profiling", "pr_branding"]}

If NO, return:
{"is_trigger": false}

Return ONLY valid JSON, nothing else."""


def classify_research_trigger(message_body: str, sender_name: str) -> dict:
    """Classify if a WhatsApp message is a research trigger. Returns classification dict."""
    if not message_body or len(message_body) < 200:
        return {"is_trigger": False}

    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_CLASSIFY_PROMPT,
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
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id FROM research_proposals
                WHERE LOWER(subject_name) = LOWER(%s)
                  AND status NOT IN ('skipped')
                  AND created_at > NOW() - INTERVAL '7 days'
                LIMIT 1
            """, (subject_name,))
            existing = cur.fetchone()
            if existing:
                logger.info(f"Research proposal for '{subject_name}' already exists (id={existing[0]}) — skipping")
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
    """Create dashboard alert + push notification for research proposal."""
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
            f"**Proposed specialists:** {spec_list}\n\n"
            f"Open the Actions tab to approve or skip this research."
        )

        store.create_alert(
            tier=2,
            title=f"Research trigger: {subject_name} — run dossier?",
            body=alert_body,
            action_required=True,
            tags=["research_trigger", "dossier"],
            source="research_trigger",
            source_id=f"research-proposal-{proposal_id}",
        )
        logger.info(f"Research proposal alert created for '{subject_name}'")
    except Exception as e:
        logger.warning(f"Research proposal notification failed: {e}")


# ─────────────────────────────────────────────────
# Content pre-filter (cheap regex gate before Haiku)
# ─────────────────────────────────────────────────

import re as _re

# Patterns that suggest forwarded intelligence (not casual chat)
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
    r'Dr\.|Mag\.|RA\s|Rechtsanwalt'           # professional titles
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
                    ORDER BY created_at DESC LIMIT 20
                """, (status,))
            else:
                cur.execute(f"""
                    SELECT * FROM research_proposals
                    WHERE created_at > NOW() - INTERVAL '{int(days)} days'
                    ORDER BY created_at DESC LIMIT 20
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
