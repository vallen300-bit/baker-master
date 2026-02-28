"""
Sentinel AI — Main RAG Pipeline
Implements the 5-step flow from the Sentinel architecture:
  1. Trigger → 2. Retrieval → 3. Augmentation → 4. Generation → 5. Store Back
"""
import json
import logging
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
        """Retrieve all relevant context for this trigger."""
        return self.retriever.retrieve_for_trigger(
            trigger_text=trigger.content,
            trigger_type=trigger.type,
            contact_name=trigger.contact_name,
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

    def generate(self, prompt: dict, max_output_tokens: int = 8192) -> str:
        """Send assembled prompt to Claude and get response."""
        logger.info(
            f"Calling Claude API: model={config.claude.model}, "
            f"≈{prompt['metadata']['tokens_estimated']} input tokens"
        )

        response = self.claude.messages.create(
            model=config.claude.model,
            max_tokens=max_output_tokens,
            system=prompt["system"],
            messages=prompt["messages"],
            extra_headers={"anthropic-beta": config.claude.beta_header},
        )

        raw_text = response.content[0].text
        logger.info(
            f"Claude responded: {response.usage.input_tokens} in, "
            f"{response.usage.output_tokens} out"
        )
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
            # 1. Log this trigger
            trigger_log_id = self.store.log_trigger(
                trigger_type=trigger.type,
                source_id=trigger.source_id,
                content=trigger.content[:1000],
                contact_id=trigger.contact_id,
                priority=trigger.priority,
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
            if response.alerts:
                for alert in response.alerts:
                    tier = _normalize_tier(alert.get("tier"))
                    self.store.create_alert(
                        tier=tier,
                        title=alert.get("title", "Untitled alert"),
                        body=alert.get("body", ""),
                        action_required=alert.get("action_required", False),
                        trigger_id=trigger_log_id,
                    )
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
                trigger_content=trigger.content[:500],
                response_analysis=response.analysis[:500],
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

        # Step 2: Retrieve
        contexts = self.retrieve_context(trigger)
        from collections import Counter
        coll_counts = Counter(c.metadata.get("collection", "?") for c in contexts)
        stats_line = ", ".join(f"{coll}: {n}" for coll, n in coll_counts.most_common())
        logger.info(f"Step 2 complete: {len(contexts)} contexts retrieved [{stats_line}]")

        # Step 3: Augment (build prompt)
        prompt = self.build_prompt(trigger, contexts)
        logger.info(f"Step 3 complete: prompt assembled ({prompt['metadata']['tokens_estimated']} tokens)")

        # Step 4: Generate
        raw_response = self.generate(prompt)
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
