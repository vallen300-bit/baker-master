"""
Sentinel AI — Main RAG Pipeline
Implements the 5-step flow from the Sentinel architecture:
  1. Trigger → 2. Retrieval → 3. Augmentation → 4. Generation → 5. Store Back
"""
import json
import logging
import re
from typing import Optional
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field

import anthropic

from config.settings import config
from memory.retriever import SentinelRetriever
from memory.store_back import SentinelStoreBack
from orchestrator.prompt_builder import SentinelPromptBuilder

logger = logging.getLogger("sentinel.pipeline")


# ============================================================
# Helpers
# ============================================================

def _match_matter_slug(title: str, body: str, store: SentinelStoreBack) -> Optional[str]:
    """
    Match alert title+body against matter_registry keywords to auto-assign matter_slug.
    Returns matter_name (used as slug) if a match is found, None otherwise.
    Uses case-insensitive matching: keywords as substrings, short keywords (<=3 chars)
    as word-boundary matches, people as partial name matches (last name sufficient).
    """
    import re as _re
    try:
        matters = store.get_matters(status="active")
        if not matters:
            return None

        search_text = (title + " " + (body or "")).lower()

        best_match = None
        best_score = 0

        for matter in matters:
            score = 0
            name = (matter.get("matter_name") or "").lower()
            keywords = matter.get("keywords") or []
            people = matter.get("people") or []

            # Match on matter name (strongest signal)
            if name and name in search_text:
                score += 3

            # Match on keywords — word-boundary for short terms, substring for longer
            for kw in keywords:
                if not kw:
                    continue
                kw_lower = kw.lower()
                if len(kw_lower) <= 3:
                    # Short keywords (BB, MO, AO) — require word boundary
                    if _re.search(r'\b' + _re.escape(kw_lower) + r'\b', search_text):
                        score += 2
                else:
                    if kw_lower in search_text:
                        score += 2

            # Match on people — check each name part (last name match is enough)
            for person in people:
                if not person:
                    continue
                person_lower = person.lower()
                # Full name match
                if person_lower in search_text:
                    score += 2
                    continue
                # Partial: any name part >= 4 chars (avoids matching "Mr", "Dr")
                for part in person_lower.split():
                    if len(part) >= 4 and part in search_text:
                        score += 1
                        break

            if score > best_score:
                best_score = score
                best_match = matter.get("matter_name")

        if best_score >= 1:  # Even a single person-name match is meaningful
            return best_match
        return None
    except Exception as e:
        logger.debug(f"Matter matching failed (non-fatal): {e}")
        return None


# Tag keyword groups for auto-tagging (COCKPIT-V3 Phase B)
_TAG_KEYWORDS = {
    "legal": ["lawsuit", "court", "litigation", "legal", "attorney", "lawyer", "claim", "dispute", "evidence"],
    "finance": ["loan", "interest", "cashflow", "cash flow", "budget", "invoice", "payment", "term sheet", "lp"],
    "deadline": ["deadline", "due date", "expires", "expiry", "overdue", "by end of"],
    "follow-up": ["follow up", "follow-up", "following up", "check in", "check-in"],
    "waiting-response": ["waiting for", "awaiting", "no response", "pending response", "haven't heard"],
    "contract": ["contract", "agreement", "lease", "mou", "memorandum", "signed", "signature"],
    "dispute": ["dispute", "arbitration", "mediation", "complaint", "grievance"],
    "compliance": ["compliance", "regulatory", "regulation", "audit", "finma", "license"],
    "meeting": ["meeting", "call", "session", "workshop", "conference"],
    "travel": ["flight", "airport", "airline", "boarding pass", "itinerary", "layover", "luggage"],
    "hr": ["employee", "hiring", "recruitment", "termination", "payroll"],
    "it": ["migration", "m365", "byod", "infrastructure", "server", "cloud"],
    "marketing": ["marketing", "campaign", "social media", "branding", "advertisement"],
    "sales": ["sales", "buyer", "prospect", "pitch", "showing", "pricing"],
    "investor": ["investor", "raise", "fund", "capital", "equity"],
}


def _auto_tag(title: str, body: str) -> list:
    """Auto-assign tags based on keyword matching. Max 5 tags per alert.
    Short keywords (≤3 chars) use word-boundary matching to avoid false positives
    (e.g. 'lp' in 'helpful', 'hr' in 'three')."""
    search_text = ((title or "") + " " + (body or "")).lower()
    matched = []
    for tag, keywords in _TAG_KEYWORDS.items():
        for kw in keywords:
            if len(kw) <= 3:
                if re.search(r'\b' + re.escape(kw) + r'\b', search_text):
                    matched.append(tag)
                    break
            else:
                if kw in search_text:
                    matched.append(tag)
                    break
    return matched[:5]


def _travel_source_id(title: str, body: str) -> str:
    """TRAVEL-HYGIENE-1: Generate deterministic source_id for travel alerts from route + date."""
    import re as _re
    text = ((title or "") + " " + (body or "")).lower()
    # Extract date (YYYY-MM-DD or "march 26" style)
    date_match = _re.search(r'(\d{4}-\d{2}-\d{2})', text)
    if not date_match:
        # Try "month day" pattern
        months = {"january": "01", "february": "02", "march": "03", "april": "04",
                  "may": "05", "june": "06", "july": "07", "august": "08",
                  "september": "09", "october": "10", "november": "11", "december": "12"}
        for mname, mnum in months.items():
            m = _re.search(mname + r'\s+(\d{1,2})', text)
            if m:
                date_match = f"2026-{mnum}-{int(m.group(1)):02d}"
                break
        if not date_match:
            date_match = ""
    else:
        date_match = date_match.group(1)
    # Extract destination (city after → or "to")
    dest_match = _re.search(r'(?:→|to)\s+([a-z]+)', text)
    dest = dest_match.group(1) if dest_match else "unknown"
    if date_match:
        return f"travel:{dest}:{date_match}"
    return ""


def _find_existing_travel_alert(store, source_id: str, title: str):
    """TRAVEL-HYGIENE-1: Find existing pending travel alert by source_id or similar title."""
    conn = store._get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        # Check by source_id first (exact match)
        if source_id:
            cur.execute(
                "SELECT id FROM alerts WHERE source_id = %s AND status = 'pending' LIMIT 1",
                (source_id,),
            )
            row = cur.fetchone()
            if row:
                cur.close()
                return row[0]
        # Fallback: check by travel tag + similar title
        cur.execute("""
            SELECT id FROM alerts
            WHERE status = 'pending'
              AND (tags ? 'travel' OR title ILIKE '%%flight%%')
              AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC LIMIT 5
        """)
        from memory.store_back import _titles_similar
        for row in cur.fetchall():
            # We only have id here, need to check title similarity
            pass
        cur.close()
        return None
    except Exception:
        return None
    finally:
        store._put_conn(conn)


def _update_existing_travel_alert(store, alert_id: int, title: str, body: str, tier: int):
    """TRAVEL-HYGIENE-1: Update existing travel alert title/body/tier."""
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE alerts SET title = %s, body = %s, tier = LEAST(tier, %s), updated_at = NOW() WHERE id = %s",
            (title, body, tier, alert_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.warning(f"_update_existing_travel_alert failed: {e}")
    finally:
        store._put_conn(conn)


def _baker_already_commented(task_id: str, hours: int = 24) -> bool:
    """Check if Baker has posted a comment on this ClickUp task within the last N hours.
    Prevents duplicate comments caused by Baker's own comment bumping date_updated.
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM baker_actions
                WHERE action_type = 'post_comment'
                  AND target_task_id = %s
                  AND created_at > NOW() - make_interval(hours => %s)
            """, (task_id, hours))
            count = cur.fetchone()[0]
            cur.close()
            return count > 0
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Baker comment dedup check failed (allowing comment): {e}")
        return False


def _normalize_tier(raw_tier) -> int:
    """Normalize alert tier to integer 1/2/3. Defaults to 3 if invalid."""
    if isinstance(raw_tier, int) and raw_tier in (1, 2, 3):
        return raw_tier
    # Fallback: string mapping (defensive, prompt says integers)
    str_map = {"urgent": 1, "important": 2, "info": 3}
    if isinstance(raw_tier, str):
        mapped = str_map.get(raw_tier.lower())
        if mapped:
            logger.warning(f"Tier received as string '{raw_tier}', expected integer. Mapped to {mapped}.")
            return mapped
    logger.warning(f"Invalid tier value: {raw_tier!r}. Defaulting to 3.")
    return 3


_STRUCTURED_ACTIONS_PROMPT = """You are Baker, an AI Chief of Staff. Given an alert, produce structured actions the Director can select and execute.

Return ONLY valid JSON with this structure:
{
  "problem": "3-4 lines summarizing the issue",
  "cause": "2 lines — root cause analysis",
  "solution": "2-3 lines — what solved looks like",
  "parts": [
    {
      "label": "Group label (e.g. Legal defense, Financial response)",
      "actions": [
        {
          "label": "Short action name",
          "description": "One line explaining what this produces",
          "type": "draft|analyze|plan|specialist",
          "prompt": "The full prompt Baker should execute if Director selects this action"
        }
      ]
    }
  ]
}

Action types:
- "draft": produces an email, letter, memo, or message
- "analyze": produces a report, comparison, study, or review
- "plan": produces a ClickUp task structure, timeline, milestones
- "specialist": deep domain analysis requiring named capability

Rules:
- 2-4 parts, each with 1-3 actions
- Prompts must be self-contained — Baker will execute them independently
- Be specific: name people, reference documents, include context from the alert
- Every alert gets at least one "draft" action (communication is always needed)
"""


def _generate_structured_actions(claude_client, title: str, body: str, tier: int) -> dict:
    """Generate structured actions JSON for an alert using Haiku (fast + cheap)."""
    try:
        resp = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=_STRUCTURED_ACTIONS_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Alert (Tier {tier}): {title}\n\n{body}",
            }],
        )
        # PHASE-4A: Log Haiku cost
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens,
                         resp.usage.output_tokens, source="structured_actions")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        parsed = json.loads(raw)
        # Validate minimal structure
        if "parts" in parsed and isinstance(parsed["parts"], list):
            logger.info(f"Generated structured actions: {len(parsed['parts'])} parts")
            return parsed
        logger.warning("Structured actions missing 'parts' key — discarding")
        return None
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Structured actions generation error: {e}")
        return None


# ============================================================
# Data Models
# ============================================================

@dataclass
class TriggerEvent:
    """An incoming trigger that starts the pipeline."""
    type: str           # email, whatsapp, meeting, calendar, scheduled, manual
    content: str        # the actual content (email body, message, query)
    source_id: str      # unique ID from source system
    contact_name: Optional[str] = None
    contact_id: Optional[str] = None
    priority: Optional[str] = None  # will be classified by orchestrator
    timestamp: str = ""
    metadata: dict = field(default_factory=dict)  # carrier for trigger-specific context
    # DECISION-ENGINE-1A: Scored fields (populated by score_trigger)
    domain: Optional[str] = None
    urgency_score: Optional[int] = None
    tier: Optional[int] = None
    mode: Optional[str] = None
    override_applied: Optional[str] = None
    scoring_reasoning: Optional[str] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class SentinelResponse:
    """Structured response from the pipeline."""
    alerts: list        # tier 1/2/3 alerts
    analysis: str       # main response text
    draft_messages: list  # suggested drafts
    contact_updates: list  # profile updates to store back
    decisions_log: list  # decisions made
    raw_response: str   # full Claude response
    metadata: dict      # pipeline metadata (tokens, timing, etc.)


# ============================================================
# Main Pipeline
# ============================================================

class SentinelPipeline:
    """
    The main orchestrator. Runs the full RAG pipeline for each trigger.
    """

    def __init__(self):
        self.retriever = SentinelRetriever()
        self.prompt_builder = SentinelPromptBuilder()
        self.claude = anthropic.Anthropic(api_key=config.claude.api_key)
        self.store = SentinelStoreBack()

    # -------------------------------------------------------
    # Step 1: Classify Trigger
    # -------------------------------------------------------

    def classify_trigger(self, trigger: TriggerEvent) -> TriggerEvent:
        """
        Classify and score the incoming trigger.
        Sets priority based on heuristics before sending to Claude.
        """
        # Simple heuristic priority scoring
        # (Phase 2: replace with ML classifier)
        high_priority_signals = [
            "urgent", "asap", "deadline", "risk", "problem",
            "payment", "contract", "sign", "approve", "alert",
        ]
        content_lower = trigger.content.lower()

        if any(signal in content_lower for signal in high_priority_signals):
            trigger.priority = "high"
        elif trigger.type in ("email", "whatsapp"):
            trigger.priority = "medium"
        else:
            trigger.priority = "low"

        logger.info(f"Trigger classified: type={trigger.type}, priority={trigger.priority}")
        return trigger

    # -------------------------------------------------------
    # Step 2: Retrieve (delegates to SentinelRetriever)
    # -------------------------------------------------------

    def retrieve_context(self, trigger: TriggerEvent):
        """Retrieve all relevant context for this trigger.
        Baker 3.0: uses context_selector for smart source filtering."""
        # Build context plan (Baker 3.0 Item 2)
        context_plan = None
        try:
            from orchestrator.context_selector import select_context
            context_plan = select_context(
                query=trigger.content or "",
                matter=getattr(trigger, "matter", None),
                contact=trigger.contact_name,
                channel_of_origin=trigger.type or "dashboard",
            )
        except Exception as _sel_err:
            logger.warning(f"Context selector failed (falling back to full retrieval): {_sel_err}")

        return self.retriever.retrieve_for_trigger(
            trigger_text=trigger.content,
            trigger_type=trigger.type,
            contact_name=trigger.contact_name,
            context_plan=context_plan,
        )

    # -------------------------------------------------------
    # Step 3: Augment (delegates to SentinelPromptBuilder)
    # -------------------------------------------------------

    def build_prompt(self, trigger, contexts):
        """Assemble the prompt within token budget."""
        return self.prompt_builder.build_prompt(
            trigger_type=trigger.type,
            trigger_content=trigger.content,
            retrieved_contexts=contexts,
        )

    # -------------------------------------------------------
    # Step 4: Generate (Claude API call)
    # -------------------------------------------------------

    # Trigger types that should use Haiku instead of Opus (cost optimization)
    # COST-OPT-WAVE1: rss_article_new (not rss_article) matches actual trigger type from rss_trigger.py
    _HAIKU_TRIGGER_TYPES = {"dropbox_file_new", "dropbox_file_modified", "rss_article", "rss_article_new"}

    def generate(self, prompt: dict, max_output_tokens: int = 8192,
                 trigger_type: str = None) -> str:
        """Send assembled prompt to Claude and get response.
        Uses Haiku for low-value triggers (document ingestion, RSS) to cut costs."""
        # COST-OPT-1: Route document ingestion to Haiku (~EUR 0.002/call vs EUR 1.31)
        if trigger_type in self._HAIKU_TRIGGER_TYPES:
            model = "claude-haiku-4-5-20251001"
        else:
            model = config.claude.model

        logger.info(
            f"Calling Claude API: model={model}, "
            f"≈{prompt['metadata']['tokens_estimated']} input tokens"
        )

        response = self.claude.messages.create(
            model=model,
            max_tokens=max_output_tokens,
            system=prompt["system"],
            messages=prompt["messages"],
            extra_headers={"anthropic-beta": config.claude.beta_header} if model == config.claude.model else {},
        )

        raw_text = response.content[0].text
        logger.info(
            f"Claude responded: {response.usage.input_tokens} in, "
            f"{response.usage.output_tokens} out"
        )
        # PHASE-4A: Log pipeline API cost
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(model, response.usage.input_tokens,
                         response.usage.output_tokens, source="pipeline")
        except Exception:
            pass
        return raw_text

    # -------------------------------------------------------
    # Step 5: Store Back (learning loop)
    # -------------------------------------------------------

    def store_back(self, trigger: TriggerEvent, response: SentinelResponse):
        """
        Write new learnings back to memory.
        - Trigger log → PostgreSQL
        - Contact updates → PostgreSQL
        - Decisions → PostgreSQL
        - Alerts → PostgreSQL
        - Interaction embedding → Qdrant
        All operations are fault-tolerant — pipeline continues if DB is down.
        """
        trigger_log_id = None

        try:
            # 1. Log this trigger (with Decision Engine scored fields)
            trigger_log_id = self.store.log_trigger(
                trigger_type=trigger.type,
                source_id=trigger.source_id,
                content=trigger.content,
                contact_id=trigger.contact_id,
                priority=trigger.priority,
                domain=trigger.domain,
                urgency_score=trigger.urgency_score,
                tier=trigger.tier,
                mode=trigger.mode,
                scoring_reasoning=trigger.scoring_reasoning,
            )
        except Exception as e:
            logger.warning(f"Store-back: log_trigger failed (non-fatal): {e}")

        try:
            # 2. Store contact updates
            if response.contact_updates:
                logger.info(f"Storing {len(response.contact_updates)} contact updates")
                for update in response.contact_updates:
                    contact_name = update.pop("name", None)
                    if contact_name:
                        self.store.upsert_contact(contact_name, update)
        except Exception as e:
            logger.warning(f"Store-back: contact updates failed (non-fatal): {e}")

        try:
            # 3. Store decisions
            if response.decisions_log:
                logger.info(f"Storing {len(response.decisions_log)} decisions")
                for decision in response.decisions_log:
                    self.store.log_decision(
                        decision=decision.get("decision", ""),
                        reasoning=decision.get("reasoning", ""),
                        confidence=decision.get("confidence", "medium"),
                        trigger_type=trigger.type,
                    )
        except Exception as e:
            logger.warning(f"Store-back: decisions failed (non-fatal): {e}")

        try:
            # 4. Create alerts from response
            # ALERT-BATCH-1: Suppress individual alerts for document ingestion triggers.
            # The Dropbox trigger creates a batch summary alert instead.
            _BATCH_TRIGGER_TYPES = {"dropbox_file_new", "dropbox_file_modified"}
            if response.alerts and trigger.type not in _BATCH_TRIGGER_TYPES:
                for alert in response.alerts:
                    tier = _normalize_tier(alert.get("tier"))
                    alert_title = alert.get("title", "Untitled alert")
                    alert_body = alert.get("body", "")
                    # ALERT-DEDUP-2: Skip if similar pending alert exists within 24h
                    if self.store.alert_title_dedup(alert_title, hours=24):
                        continue
                    # COCKPIT-V3 A2: Auto-assign matter_slug by keyword matching
                    matter_slug = _match_matter_slug(alert_title, alert_body, self.store)
                    if matter_slug:
                        logger.info(f"Auto-assigned alert to matter '{matter_slug}'")
                    # COCKPIT-V3 B1: Auto-tag by keyword matching
                    tags = _auto_tag(alert_title, alert_body)

                    # TRAVEL-HYGIENE-1: For travel alerts, use deterministic source_id and upsert
                    _source_id = None
                    if "travel" in tags:
                        _source_id = _travel_source_id(alert_title, alert_body)
                        if _source_id:
                            _existing = _find_existing_travel_alert(self.store, _source_id, alert_title)
                            if _existing:
                                _update_existing_travel_alert(self.store, _existing, alert_title, alert_body, tier)
                                logger.info(f"TRAVEL-HYGIENE-1: updated existing travel alert #{_existing} instead of creating new")
                                continue

                    alert_id = self.store.create_alert(
                        tier=tier,
                        title=alert_title,
                        body=alert_body,
                        action_required=alert.get("action_required", False),
                        trigger_id=trigger_log_id,
                        matter_slug=matter_slug,
                        tags=tags,
                        source="pipeline",
                        source_id=_source_id,
                    )
                    # COCKPIT-ALERT-UI: generate structured actions for T1/T2/T3 alerts
                    if alert_id and tier <= 3:
                        try:
                            sa = _generate_structured_actions(
                                self.claude,
                                alert.get("title", ""),
                                alert.get("body", ""),
                                tier,
                            )
                            if sa:
                                self.store.update_alert_structured_actions(alert_id, sa)
                        except Exception as sa_err:
                            logger.warning(f"Structured actions generation failed for alert #{alert_id} (non-fatal): {sa_err}")
                    # AUTONOMOUS-CHAINS-1: Run autonomous action chain for T1/T2 with matched matter
                    if alert_id and tier <= 2 and matter_slug:
                        try:
                            from orchestrator.chain_runner import maybe_run_chain
                            maybe_run_chain(
                                trigger_type=trigger.type,
                                trigger_content=trigger.content,
                                alert_id=alert_id,
                                alert_title=alert_title,
                                alert_body=alert_body,
                                alert_tier=tier,
                                matter_slug=matter_slug,
                            )
                        except Exception as chain_err:
                            logger.warning(f"Chain runner failed for alert #{alert_id} (non-fatal): {chain_err}")
        except Exception as e:
            logger.warning(f"Store-back: alerts failed (non-fatal): {e}")

        try:
            # 4b. Deliver real-time alerts to Slack (Tier 1 + Tier 2 only)
            if response.alerts:
                from outputs.slack_notifier import SlackNotifier
                notifier = SlackNotifier()
                for alert in response.alerts:
                    alert_tier = _normalize_tier(alert.get("tier"))
                    if alert_tier <= 2:
                        notifier.post_alert({
                            "tier": alert_tier,
                            "title": alert.get("title", "Untitled"),
                            "body": alert.get("body", ""),
                            "action_required": alert.get("action_required", False),
                            "contact_name": trigger.contact_name,
                            "deal_name": alert.get("deal_name"),
                        })
        except Exception as e:
            logger.warning(f"Store-back: Slack alert delivery failed (non-fatal): {e}")

        try:
            # 5. Update trigger log with results
            if trigger_log_id:
                self.store.update_trigger_result(
                    trigger_id=trigger_log_id,
                    response_id=str(trigger_log_id),
                    pipeline_ms=response.metadata.get("pipeline_duration_ms", 0),
                    tokens_in=response.metadata.get("tokens_estimated", 0),
                    tokens_out=0,
                )
        except Exception as e:
            logger.warning(f"Store-back: trigger result update failed (non-fatal): {e}")

        try:
            # 6. Embed interaction in Qdrant
            self.store.store_interaction(
                trigger_type=trigger.type,
                trigger_content=trigger.content,
                response_analysis=response.analysis,
                contact_name=trigger.contact_name,
                full_content=trigger.content,
            )
        except Exception as e:
            logger.warning(f"Store-back: Qdrant interaction store failed (non-fatal): {e}")

        logger.info("Store-back complete")

    # -------------------------------------------------------
    # Step 6: ClickUp Write Actions (M3)
    # -------------------------------------------------------

    def _execute_clickup_actions(self, trigger: TriggerEvent, response: SentinelResponse):
        """
        Execute autonomous ClickUp write actions for ClickUp-sourced triggers.
        Only writes to BAKER space (901510186446). Kill switch: BAKER_CLICKUP_READONLY=true.
        """
        import os

        # Only act on ClickUp triggers
        if not trigger.type.startswith("clickup_"):
            return

        # Kill switch
        if os.getenv("BAKER_CLICKUP_READONLY", "").lower() == "true":
            logger.info("ClickUp write actions skipped (BAKER_CLICKUP_READONLY=true)")
            return

        # Extract source task_id from trigger source_id (format: "clickup:<task_id>")
        source_task_id = None
        if trigger.source_id and trigger.source_id.startswith("clickup:"):
            source_task_id = trigger.source_id.split(":", 1)[1]

        if not source_task_id:
            logger.debug("No ClickUp task ID in trigger — skipping write actions")
            return

        try:
            from clickup_client import ClickUpClient
            client = ClickUpClient._get_global_instance()
        except Exception as e:
            logger.warning(f"ClickUp client init failed — skipping write actions: {e}")
            return

        # Determine highest alert tier from response
        max_tier = 3
        if response.alerts:
            tiers = [_normalize_tier(a.get("tier")) for a in response.alerts]
            max_tier = min(tiers) if tiers else 3

        # Dedup: skip if Baker already commented on this task in the last 24h
        if _baker_already_commented(source_task_id):
            logger.info(f"M3: Skipping comment — Baker already commented on {source_task_id} recently")
            return

        try:
            if trigger.type == "clickup_handoff_note":
                # Handoff notes: post acknowledgment comment
                client.post_comment(
                    source_task_id,
                    "[Baker] Handoff note received and processed. Alert created.",
                )
                logger.info(f"M3: Posted acknowledgment comment on handoff note {source_task_id}")

            elif max_tier == 1:
                # T1: Add "urgent" tag
                client.add_tag(source_task_id, "urgent")
                logger.info(f"M3: Added 'urgent' tag to task {source_task_id}")

            elif max_tier == 2:
                # T2: Post status comment with analysis summary
                summary = (response.analysis or "")[:300]
                if summary:
                    client.post_comment(
                        source_task_id,
                        f"[Baker] Status update processed. Summary: {summary}",
                    )
                    logger.info(f"M3: Posted status comment on task {source_task_id}")

        except RuntimeError as e:
            # Kill switch or max writes exceeded — expected, just log
            logger.info(f"M3: ClickUp write skipped — {e}")
        except ValueError as e:
            # Non-BAKER space write attempt — expected safety guard
            logger.info(f"M3: ClickUp write blocked — {e}")
        except Exception as e:
            logger.warning(f"M3: ClickUp write action failed (non-fatal): {e}")

    # -------------------------------------------------------
    # Parse Claude's response into structured format
    # -------------------------------------------------------

    def parse_response(self, raw_response: str, metadata: dict) -> SentinelResponse:
        """Parse Claude's JSON response into SentinelResponse."""
        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError:
            # Claude sometimes wraps JSON in markdown code blocks
            import re
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_response)
            if json_match:
                parsed = json.loads(json_match.group(1))
            else:
                # Fallback: treat entire response as analysis text
                parsed = {
                    "alerts": [],
                    "analysis": raw_response,
                    "draft_messages": [],
                    "contact_updates": [],
                    "decisions_log": [],
                }

        return SentinelResponse(
            alerts=parsed.get("alerts", []),
            analysis=parsed.get("analysis", ""),
            draft_messages=parsed.get("draft_messages", []),
            contact_updates=parsed.get("contact_updates", []),
            decisions_log=parsed.get("decisions_log", []),
            raw_response=raw_response,
            metadata=metadata,
        )

    # -------------------------------------------------------
    # Step S3: Slack thread reply for @Baker mentions
    # -------------------------------------------------------

    def _post_slack_thread_reply(self, trigger: TriggerEvent, response: SentinelResponse):
        """Post Baker's analysis as a Slack thread reply for @Baker mentions (S3)."""
        try:
            from outputs.slack_notifier import SlackNotifier
            channel_id = trigger.metadata.get("channel_id", "")
            thread_ts = trigger.metadata.get("thread_ts", "")
            if not channel_id or not thread_ts:
                logger.warning("S3: missing channel_id or thread_ts in trigger metadata")
                return
            reply_text = (response.analysis or "I've processed this — check the Cockpit for details.")[:3000]
            notifier = SlackNotifier()
            ok = notifier.post_thread_reply(channel_id, thread_ts, reply_text)
            if ok:
                logger.info(f"S3: thread reply posted to {channel_id} ts={thread_ts}")
        except Exception as e:
            logger.warning(f"S3: Slack thread reply failed (non-fatal): {e}")

    # -------------------------------------------------------
    # Full Pipeline Execution
    # -------------------------------------------------------

    def run(self, trigger: TriggerEvent) -> SentinelResponse:
        """
        Execute the complete Sentinel RAG pipeline:
        Trigger → Retrieve → Augment → Generate → Store Back
        """
        import time
        start = time.time()

        logger.info(f"{'='*60}")
        logger.info(f"SENTINEL PIPELINE START: {trigger.type} from {trigger.contact_name or 'unknown'}")
        logger.info(f"{'='*60}")

        # Step 1: Classify
        trigger = self.classify_trigger(trigger)

        # Step 1b: Score (Decision Engine — DECISION-ENGINE-1A)
        try:
            from orchestrator.decision_engine import score_trigger
            scored = score_trigger(
                trigger.content, trigger.contact_name or "",
                trigger.type, trigger.metadata,
            )
            trigger.domain = scored["domain"]
            trigger.urgency_score = scored["urgency_score"]
            trigger.tier = scored["tier"]
            trigger.mode = scored["mode"]
            trigger.override_applied = scored.get("override_applied")
            trigger.scoring_reasoning = scored.get("reasoning")
            logger.info(
                f"Decision Engine: domain={trigger.domain} score={trigger.urgency_score} "
                f"tier={trigger.tier} mode={trigger.mode}"
            )
        except Exception as e:
            logger.warning(f"Decision Engine failed (non-fatal, continuing): {e}")

        # ALERT-DEDUP-1: Alert digest email DISABLED.
        # Was sending ~48 digest emails/day (every 30 min) — Director stopped reading them.
        # Real-time alerts go to Slack (with dedup). Daily briefing email at 08:00 CET
        # covers everything. Re-enable by uncommenting and restoring digest_flush in scheduler.
        # if trigger.priority == "high":
        #     try:
        #         from outputs.email_alerts import send_alert_email
        #         send_alert_email(trigger)
        #     except Exception as _e:
        #         logger.warning(f"Alert digest routing failed (non-fatal): {_e}")

        # Step 2: Retrieve
        contexts = self.retrieve_context(trigger)
        from collections import Counter
        coll_counts = Counter(c.metadata.get("collection", "?") for c in contexts)
        stats_line = ", ".join(f"{coll}: {n}" for coll, n in coll_counts.most_common())
        logger.info(f"Step 2 complete: {len(contexts)} contexts retrieved [{stats_line}]")

        # Step 3: Augment (build prompt)
        prompt = self.build_prompt(trigger, contexts)
        logger.info(f"Step 3 complete: prompt assembled ({prompt['metadata']['tokens_estimated']} tokens)")

        # Step 4: Generate (COST-OPT-1: Haiku for document/RSS triggers)
        raw_response = self.generate(prompt, trigger_type=trigger.type)
        logger.info(f"Step 4 complete: Claude responded")

        # Parse response
        response = self.parse_response(raw_response, {
            **prompt["metadata"],
            "pipeline_duration_ms": int((time.time() - start) * 1000),
            "trigger_type": trigger.type,
            "trigger_priority": trigger.priority,
        })

        # Step 5: Store back
        self.store_back(trigger, response)
        logger.info(f"Step 5 complete: stored back")

        # Step 5b: Baker 3.0 — real-time extraction (non-blocking background)
        if trigger.type in ("email", "whatsapp", "slack", "calendar"):
            try:
                from orchestrator.extraction_engine import extract_signal
                extract_signal(
                    source_channel=trigger.type,
                    source_id=trigger.source_id or "",
                    content=trigger.content or "",
                    tier=getattr(trigger, "tier", 3),
                )
            except Exception as _ext_err:
                logger.warning(f"Extraction engine hook failed (non-fatal): {_ext_err}")

        # Step 6: ClickUp write actions (M3)
        self._execute_clickup_actions(trigger, response)
        logger.info(f"Step 6 complete: ClickUp actions processed")

        # Step 7: Slack thread reply for @Baker mentions (S3)
        if trigger.type == "slack" and trigger.metadata.get("is_mention"):
            self._post_slack_thread_reply(trigger, response)
            logger.info("Step 7 complete: Slack thread reply posted")

        total_ms = int((time.time() - start) * 1000)
        logger.info(f"SENTINEL PIPELINE COMPLETE: {total_ms}ms total")

        return response


# ============================================================
# Convenience function for manual queries (Baker mode)
# ============================================================

def ask_baker(question: str, contact: str = None) -> SentinelResponse:
    """
    Quick way to ask Baker a question with full context retrieval.
    Use this from CLI or scripts.
    """
    pipeline = SentinelPipeline()
    trigger = TriggerEvent(
        type="manual",
        content=question,
        source_id="manual-query",
        contact_name=contact,
    )
    return pipeline.run(trigger)


def auto_dismiss_past_travel():
    """TRAVEL-HYGIENE-1: Dismiss travel alerts where departure day has passed.
    Director override: expire at midnight AFTER departure day in Europe/Zurich timezone.
    Runs every hour via scheduler."""
    from zoneinfo import ZoneInfo
    import re as _re
    try:
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            director_tz = ZoneInfo("Europe/Zurich")
            today_local = datetime.now(director_tz).date()

            # Find all pending travel alerts
            cur.execute("""
                SELECT id, title, body, created_at FROM alerts
                WHERE status = 'pending'
                  AND (tags ? 'travel' OR title ILIKE '%%flight%%' OR title ILIKE '%%departure%%')
            """)
            rows = cur.fetchall()
            dismissed = 0
            for row in rows:
                text = ((row.get("title") or "") + " " + (row.get("body") or "")).lower()
                # Try to extract travel date from text
                travel_date = None
                # Pattern 1: YYYY-MM-DD
                dm = _re.search(r'(\d{4}-\d{2}-\d{2})', text)
                if dm:
                    try:
                        travel_date = datetime.strptime(dm.group(1), "%Y-%m-%d").date()
                    except ValueError:
                        pass
                # Pattern 2: "month day" (e.g., "march 26")
                if not travel_date:
                    months = {"january": 1, "february": 2, "march": 3, "april": 4,
                              "may": 5, "june": 6, "july": 7, "august": 8,
                              "september": 9, "october": 10, "november": 11, "december": 12}
                    for mname, mnum in months.items():
                        m = _re.search(mname + r'\s+(\d{1,2})', text)
                        if m:
                            try:
                                travel_date = datetime(2026, mnum, int(m.group(1))).date()
                            except ValueError:
                                pass
                            break
                # Pattern 3: "day month" (e.g., "26 March")
                if not travel_date:
                    for mname, mnum in months.items():
                        m = _re.search(r'(\d{1,2})\s+' + mname, text)
                        if m:
                            try:
                                travel_date = datetime(2026, mnum, int(m.group(1))).date()
                            except ValueError:
                                pass
                            break

                # Dismiss if travel date is before today (midnight CET has passed)
                if travel_date and travel_date < today_local:
                    cur.execute(
                        "UPDATE alerts SET status = 'dismissed', exit_reason = 'travel-expired', resolved_at = NOW() WHERE id = %s",
                        (row['id'],),
                    )
                    dismissed += 1

            conn.commit()
            cur.close()
            if dismissed:
                logger.info(f"TRAVEL-HYGIENE-1: auto-dismissed {dismissed} past travel alerts (midnight CET)")
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"auto_dismiss_past_travel failed: {e}")


if __name__ == "__main__":
    import argparse
    from collections import Counter

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")

    parser = argparse.ArgumentParser(description="Sentinel RAG Pipeline")
    parser.add_argument("query", nargs="?", default="What deals and projects are active?")
    parser.add_argument("--dry-run", action="store_true", help="Retrieval only, skip Claude API call")
    parser.add_argument("--contact", default=None, help="Contact name for context retrieval")
    args = parser.parse_args()

    if args.dry_run:
        pipeline = SentinelPipeline()
        trigger = TriggerEvent(
            type="manual", content=args.query,
            source_id="dry-run", contact_name=args.contact,
        )
        trigger = pipeline.classify_trigger(trigger)
        contexts = pipeline.retrieve_context(trigger)
        coll_counts = Counter(c.metadata.get("collection", "?") for c in contexts)
        print(f"\n{'='*50}")
        print(f"DRY RUN — {len(contexts)} contexts retrieved")
        for coll, count in coll_counts.most_common():
            print(f"  {coll}: {count}")
        print(f"  Total tokens: ~{sum(c.token_estimate for c in contexts)}")
        print(f"{'='*50}")
    else:
        response = ask_baker(args.query, args.contact)
        print(response.analysis)


# ============================================================
# Alert Auto-Expiry (COCKPIT-V3 Phase C)
# ============================================================

def run_alert_expiry_check():
    """Auto-expire stale alerts + reactivate snoozed alerts. Called every hour by scheduler.
    Rules:
    - Snoozed alerts past snoozed_until → reactivated to 'pending'
    - T3/T4 alerts older than 48 hours → expired
    - T2 alerts older than 48 hours → expired
    - T1 alerts older than 7 days → expired
    - Travel-tagged alerts NEVER auto-expire (handled by travel_date)
    """
    try:
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            logger.warning("Alert expiry: no DB connection")
            return
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Reactivate snoozed alerts whose snooze time has passed
            cur.execute("""
                UPDATE alerts
                SET status = 'pending', snoozed_until = NULL
                WHERE status = 'snoozed'
                  AND snoozed_until IS NOT NULL
                  AND snoozed_until <= NOW()
            """)
            reactivated = cur.rowcount
            if reactivated > 0:
                conn.commit()
                logger.info(f"Snooze reactivation: {reactivated} alerts woke up")
            # Find stale T2/T3/T4 alerts older than 48h + T1 older than 7 days
            cur.execute("""
                SELECT id, tier, tags FROM alerts
                WHERE status = 'pending'
                  AND exit_reason IS NULL
                  AND (
                    (tier >= 2 AND created_at < NOW() - INTERVAL '48 hours')
                    OR (tier = 1 AND created_at < NOW() - INTERVAL '7 days')
                  )
            """)
            candidates = cur.fetchall()

            expired_count = 0
            for row in candidates:
                # Skip travel-tagged alerts — they never auto-expire
                tags = row.get("tags") or []
                if isinstance(tags, str):
                    import json as _json
                    try:
                        tags = _json.loads(tags)
                    except Exception:
                        tags = []
                if "travel" in tags:
                    continue

                cur.execute(
                    "UPDATE alerts SET status = 'dismissed', exit_reason = 'expired' WHERE id = %s",
                    (row["id"],),
                )
                expired_count += 1

            conn.commit()
            cur.close()
            logger.info(f"Alert expiry check complete: {expired_count} expired out of {len(candidates)} candidates")
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"Alert expiry check failed: {e}")
