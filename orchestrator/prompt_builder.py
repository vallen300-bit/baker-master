"""
Sentinel AI — Prompt Builder (Step 3: Augmentation)
Assembles the full prompt from retrieved context within token budget.
This is the "A" in RAG — the Sentinel Orchestrator's core job.
"""
import json
import logging
from typing import Optional
from datetime import datetime, timezone

from memory.retriever import RetrievedContext
from config.settings import config

logger = logging.getLogger("sentinel.prompt_builder")


# ============================================================
# Baker System Prompt — The "Mind" Behind Sentinel
# ============================================================

BAKER_SYSTEM_PROMPT = """You are Baker — Dimitry Vallen's AI Chief of Staff at Brisen Group.

## WHO YOU SERVE
Dimitry Vallen — Chairman of Brisen Group (www.brisengroup.com). Big-picture strategist, not a technical specialist. Values direct communication, proactive risk flagging, and structured analysis.

## YOUR ROLE
You are a trusted senior advisor who:
- Challenges assumptions and plays devil's advocate, even when Dimitry seems confident
- Flags risks, pitfalls, and flawed logic before they become problems
- Provides bottom-line-first analysis: conclusion, then supporting detail
- Anticipates follow-up questions and addresses them proactively
- Uses the Problem → Cause → Solved State → Path Forward framework for complex issues

## RESPONSE STYLE
- Warm but direct, like a trusted advisor
- Numbered lists + bold headers for structure
- Half a page with structure for typical business questions
- Brief diagnosis (1-2 sentences) for problems, then solutions
- Never use emojis. Never be sycophantic.

## WHAT YOU KNOW
You have access to Dimitry's full context through Sentinel's memory:
- WhatsApp conversations with key contacts
- Email history and threads
- Meeting transcripts and action items
- Contact profiles with behavioral intelligence
- Active deals and their stages
- Historical decisions and their outcomes

## CRITICAL RULES
1. NEVER fabricate information. If you don't have context, say so.
2. External communications are ALWAYS draft-first — never send without approval.
3. Confidence scores are internal — never show them to Dimitry.
4. Flag anything that needs immediate attention with [ALERT] prefix.
5. When uncertain, qualify your analysis with confidence level (low/medium/high).

## OUTPUT FORMAT
Return structured JSON:
{
  "alerts": [{"tier": 1|2|3, "title": "...", "body": "...", "action_required": true|false}],
  "analysis": "...",  // main response text
  "draft_messages": [{"to": "...", "channel": "...", "content": "..."}],
  "contact_updates": [{"name": "...", "update": "..."}],
  "decisions_log": [{"decision": "...", "reasoning": "...", "confidence": "high|medium|low"}]
}

Tier 1 = Immediate action required (deal at risk, deadline today, critical response needed)
Tier 2 = Important, act within 24 hours
Tier 3 = Informational, review when convenient
"""


class SentinelPromptBuilder:
    """
    Assembles the full prompt for Claude from:
    - Baker system prompt (persona + rules)
    - Retrieved context (from Qdrant + PostgreSQL)
    - Current trigger data
    All within the 1M token budget.
    """

    def __init__(self):
        self.max_tokens = config.claude.max_context_tokens
        self.system_budget = config.claude.budget_system_prompt
        self.context_budget = config.claude.budget_retrieved_context
        self.output_budget = config.claude.budget_output
        self.buffer = config.claude.budget_buffer

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def _build_system_prompt(self, trigger_type: str) -> str:
        """Build the system prompt with Baker persona + trigger-specific instructions."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        trigger_instructions = {
            "email": "An email has arrived. Analyze sender, intent, urgency. Draft reply if needed.",
            "whatsapp": "A WhatsApp message was received. Assess relationship context and suggest response.",
            "meeting": "A meeting transcript is available. Extract action items, decisions, and follow-ups.",
            "calendar": "A calendar event is approaching. Prepare pre-meeting briefing.",
            "scheduled": "This is a scheduled check-in. Review all pending items and generate daily briefing.",
            "manual": "Dimitry is asking you directly. Answer the question using all available context.",
        }

        system = f"""{BAKER_SYSTEM_PROMPT}

## CURRENT CONTEXT
- Timestamp: {now}
- Trigger type: {trigger_type}
- Instruction: {trigger_instructions.get(trigger_type, trigger_instructions['manual'])}
"""
        return system

    def _select_context_within_budget(
        self,
        contexts: list[RetrievedContext],
        budget_tokens: int,
    ) -> list[RetrievedContext]:
        """
        Select the highest-relevance contexts that fit within token budget.
        This is Sentinel's token budget management from the architecture.
        """
        selected = []
        tokens_used = 0

        for ctx in contexts:
            if tokens_used + ctx.token_estimate > budget_tokens:
                logger.info(
                    f"Token budget reached: {tokens_used}/{budget_tokens}. "
                    f"Dropping {len(contexts) - len(selected)} lower-relevance contexts."
                )
                break
            selected.append(ctx)
            tokens_used += ctx.token_estimate

        return selected

    def _format_context_block(self, contexts: list[RetrievedContext]) -> str:
        """Format selected contexts into a readable block for the prompt."""
        if not contexts:
            return "[No relevant context found in memory]"

        sections = {}
        for ctx in contexts:
            source = ctx.source.upper()
            if source not in sections:
                sections[source] = []
            sections[source].append(ctx)

        blocks = []
        for source, items in sections.items():
            blocks.append(f"\n{'='*60}")
            blocks.append(f"SOURCE: {source} ({len(items)} items)")
            blocks.append(f"{'='*60}")
            for item in items:
                label = item.metadata.get("label", "unknown")
                # Build compact metadata line from available fields
                meta_parts = []
                md = item.metadata
                if md.get("date"):
                    meta_parts.append(f"Date: {md['date']}")
                if md.get("participants"):
                    p = md["participants"]
                    meta_parts.append(f"Participants: {', '.join(p) if isinstance(p, list) else p}")
                if md.get("person_type"):
                    meta_parts.append(f"Type: {md['person_type']}")
                if md.get("role"):
                    meta_parts.append(f"Role: {md['role']}")
                if md.get("deal_stage"):
                    meta_parts.append(f"Stage: {md['deal_stage']}")
                if md.get("status"):
                    meta_parts.append(f"Status: {md['status']}")
                if md.get("source"):
                    meta_parts.append(f"Source: {md['source']}")
                meta_str = f" | {' | '.join(meta_parts)}" if meta_parts else ""
                blocks.append(f"\n--- [{source}] {label} (relevance: {item.score:.3f}){meta_str} ---")
                blocks.append(item.content)

        return "\n".join(blocks)

    def build_prompt(
        self,
        trigger_type: str,
        trigger_content: str,
        retrieved_contexts: list[RetrievedContext],
    ) -> dict:
        """
        Build the complete prompt for Claude API call.
        Returns {"system": str, "messages": list} ready for anthropic.messages.create().
        """
        # 1. System prompt (Baker persona)
        system_prompt = self._build_system_prompt(trigger_type)
        system_tokens = self._estimate_tokens(system_prompt)

        # 2. Calculate remaining budget for context
        trigger_tokens = self._estimate_tokens(trigger_content)
        available_for_context = (
            self.max_tokens
            - system_tokens
            - trigger_tokens
            - self.output_budget
            - self.buffer
        )

        logger.info(
            f"Token budget: system={system_tokens}, trigger={trigger_tokens}, "
            f"available_for_context={available_for_context}, output_reserved={self.output_budget}"
        )

        # 3. Select contexts within budget (already sorted by relevance)
        selected = self._select_context_within_budget(
            retrieved_contexts, available_for_context
        )

        # 4. Format the context block
        context_block = self._format_context_block(selected)

        # 5. Assemble the user message
        user_message = f"""## RETRIEVED MEMORY CONTEXT
{context_block}

## CURRENT TRIGGER ({trigger_type.upper()})
{trigger_content}

## INSTRUCTION
Analyze the trigger using all retrieved context. Follow Baker's output format.
"""

        total_tokens = system_tokens + self._estimate_tokens(user_message)
        logger.info(
            f"Final prompt: {total_tokens} tokens input, "
            f"{len(selected)}/{len(retrieved_contexts)} contexts included"
        )

        return {
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
            "metadata": {
                "trigger_type": trigger_type,
                "contexts_included": len(selected),
                "contexts_total": len(retrieved_contexts),
                "tokens_estimated": total_tokens,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
