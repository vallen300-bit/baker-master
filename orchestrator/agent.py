"""
Baker AI — Agentic RAG Loop (AGENTIC-RAG-1)

Replaces single-pass "retrieve everything then call Claude once" with a
tool-use loop where Claude decides what to retrieve.  Typically 1-2
iterations for simple questions, up to max_iterations for complex ones.

Two entry points:
  run_agent_loop()           — blocking, returns AgentResult  (WhatsApp)
  run_agent_loop_streaming() — generator yielding text tokens  (Scan SSE)

Feature flag: BAKER_AGENTIC_RAG=true  (env var on Render).
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Generator, Optional

import anthropic

from config.settings import config

logger = logging.getLogger("baker.agent")

_AGENTIC_RAG = os.getenv("BAKER_AGENTIC_RAG", "false").lower() == "true"

# Hard wall-clock timeout (PM review item #1).
# If the agent loop exceeds this, we abandon and fall back to single-pass.
AGENT_TIMEOUT_SECONDS = float(os.getenv("BAKER_AGENT_TIMEOUT", "10"))


# ─────────────────────────────────────────────────
# Tool Definitions (Anthropic format)
# ─────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "search_memory",
        "description": (
            "Broad semantic search across ALL of Baker's stored knowledge "
            "(WhatsApp, emails, meetings, contacts, deals, projects, documents, "
            "health, interactions, ClickUp, Todoist).  Returns the top results "
            "ranked by relevance.\n\n"
            "Use for:\n"
            "- 'What do we know about the Atlas deal?'\n"
            "- 'Any context on Hagenauer?'\n"
            "- 'What has Baker stored about the LP fundraise?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Semantic search query — use natural language.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results per collection (default 8).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_meetings",
        "description": (
            "Search meeting transcripts (Fireflies) by keyword or get recent "
            "meetings.  Searches title, participants, organizer, and full "
            "transcript text.\n\n"
            "Use for:\n"
            "- 'What did we discuss with Hagenauer?'\n"
            "- 'Last meeting notes'\n"
            "- 'What was decided in the board call?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search in transcripts. Omit or leave empty for recent meetings.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 5).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_emails",
        "description": (
            "Search email messages by keyword or get recent emails.  Searches "
            "subject, sender, and full body.\n\n"
            "Use for:\n"
            "- 'Any emails from Marco about the contract?'\n"
            "- 'What did the lawyer send last week?'\n"
            "- 'Show me recent emails'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search in emails. Omit or leave empty for recent emails.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 5).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_whatsapp",
        "description": (
            "Search WhatsApp messages by keyword or get recent messages.  "
            "Searches sender name and message text.\n\n"
            "Use for:\n"
            "- 'What did Marco say on WhatsApp?'\n"
            "- 'Any WhatsApp messages about the Zurich trip?'\n"
            "- 'Recent WhatsApp messages'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search in WhatsApp messages. Omit or leave empty for recent messages.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 5).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_contact",
        "description": (
            "Look up a contact profile by name.  Returns role, company, email, "
            "phone, relationship tier, communication style, and notes.\n\n"
            "Use for:\n"
            "- 'Who is Thomas Hagenauer?'\n"
            "- 'What's Marco's email?'\n"
            "- 'Tell me about our relationship with Wertheimer'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Contact name (fuzzy match supported).",
                },
            },
            "required": ["name"],
        },
    },
    # STEP1B: 3 new retrieval tools (tools 6-8)
    {
        "name": "get_deadlines",
        "description": (
            "Get all active deadlines and upcoming dates from Baker's deadline "
            "tracker.  Returns every active and pending deadline ordered by due "
            "date — no keyword needed.\n\n"
            "Use for:\n"
            "- 'What deadlines do I have coming up?'\n"
            "- 'What's due this week?'\n"
            "- 'Any upcoming submission deadlines?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_clickup_tasks",
        "description": (
            "Search ClickUp tasks by keyword, status, or list name.  Searches "
            "task name and description across all synced workspaces.\n\n"
            "Use for:\n"
            "- 'What ClickUp tasks are open for Hagenauer?'\n"
            "- 'Show me high priority tasks'\n"
            "- 'Any tasks about the MO Vienna permit?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search in task name and description.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (e.g. 'open', 'in progress'). Optional.",
                },
                "priority": {
                    "type": "string",
                    "description": "Filter by priority (e.g. 'urgent', 'high'). Optional.",
                },
                "list_name": {
                    "type": "string",
                    "description": "Filter by ClickUp list name (partial match). Optional.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 10).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_deals_insights",
        "description": (
            "Search active deals and strategic insights.  Returns results from "
            "both the deals pipeline and the insights table (strategic analysis "
            "stored by Claude Code / Cowork sessions).\n\n"
            "Use for:\n"
            "- 'What is the status of the Wertheimer deal?'\n"
            "- 'Any strategic analysis on LP fundraise?'\n"
            "- 'Show me active deals'\n"
            "- 'What insights do we have on ClaimsMax?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search insights. Deals are always returned in full.",
                },
            },
            "required": ["query"],
        },
    },
]


# ─────────────────────────────────────────────────
# Tool Executor
# ─────────────────────────────────────────────────

class ToolExecutor:
    """Maps tool names to retriever methods, formats results for Claude."""

    def __init__(self):
        from memory.retriever import SentinelRetriever
        self._retriever = SentinelRetriever()

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """
        Execute a tool and return formatted text.
        Catches all exceptions per-tool (PM review item #4) so Claude
        gets a structured error and can try an alternative.
        """
        try:
            if tool_name == "search_memory":
                return self._search_memory(tool_input)
            elif tool_name == "search_meetings":
                return self._search_meetings(tool_input)
            elif tool_name == "search_emails":
                return self._search_emails(tool_input)
            elif tool_name == "search_whatsapp":
                return self._search_whatsapp(tool_input)
            elif tool_name == "get_contact":
                return self._get_contact(tool_input)
            elif tool_name == "get_deadlines":
                return self._get_deadlines(tool_input)
            elif tool_name == "get_clickup_tasks":
                return self._get_clickup_tasks(tool_input)
            elif tool_name == "search_deals_insights":
                return self._search_deals_insights(tool_input)
            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return json.dumps({"error": f"{tool_name} unavailable: {str(e)}"})

    # -- Individual tool implementations --

    def _search_memory(self, inp: dict) -> str:
        query = inp.get("query", "")
        limit = inp.get("limit", 8)
        contexts = self._retriever.search_all_collections(
            query=query,
            limit_per_collection=limit,
            score_threshold=0.3,
        )
        return self._format_contexts(contexts, "MEMORY")

    def _search_meetings(self, inp: dict) -> str:
        query = inp.get("query", "")
        limit = inp.get("limit", 5)
        if query:
            results = self._retriever.get_meeting_transcripts(query, limit=limit)
        else:
            results = self._retriever.get_recent_meeting_transcripts(limit=limit)
        return self._format_contexts(results, "MEETINGS")

    def _search_emails(self, inp: dict) -> str:
        query = inp.get("query", "")
        limit = inp.get("limit", 5)
        if query:
            results = self._retriever.get_email_messages(query, limit=limit)
        else:
            results = self._retriever.get_recent_emails(limit=limit)
        return self._format_contexts(results, "EMAILS")

    def _search_whatsapp(self, inp: dict) -> str:
        query = inp.get("query", "")
        limit = inp.get("limit", 5)
        if query:
            results = self._retriever.get_whatsapp_messages(query, limit=limit)
        else:
            results = self._retriever.get_recent_whatsapp(limit=limit)
        return self._format_contexts(results, "WHATSAPP")

    def _get_contact(self, inp: dict) -> str:
        name = inp.get("name", "")
        result = self._retriever.get_contact_profile(name)
        if result:
            return result.content
        return json.dumps({"result": f"No contact found matching '{name}'"})

    # -- STEP1B: 3 new tool implementations --

    def _get_deadlines(self, inp: dict) -> str:
        try:
            from models.deadlines import get_active_deadlines
            deadlines = get_active_deadlines(limit=50)
        except Exception as e:
            return json.dumps({"error": f"Deadlines unavailable: {str(e)}"})

        if not deadlines:
            return "[No active deadlines found]"

        lines = [f"--- DEADLINES ({len(deadlines)} active) ---"]
        for dl in deadlines:
            due = dl.get("due_date")
            due_str = due.strftime("%Y-%m-%d") if due else "TBD"
            priority = (dl.get("priority") or "normal").upper()
            status = dl.get("status", "active")
            desc = dl.get("description", "")
            lines.append(f"[{priority}] {due_str}: {desc} ({status})")
        return "\n".join(lines)

    def _get_clickup_tasks(self, inp: dict) -> str:
        query = inp.get("query", "")
        results = self._retriever.get_clickup_tasks_search(
            query=query,
            status=inp.get("status"),
            priority=inp.get("priority"),
            list_name=inp.get("list_name"),
            limit=inp.get("limit", 10),
        )
        return self._format_contexts(results, "CLICKUP TASKS")

    def _search_deals_insights(self, inp: dict) -> str:
        query = inp.get("query", "")
        deals = self._retriever.get_active_deals()
        insights = self._retriever.get_insights(query, limit=5) if query else []
        combined = deals + insights
        if not combined:
            return "[No deals or insights found]"
        return self._format_contexts(combined, "DEALS & INSIGHTS")

    @staticmethod
    def _format_contexts(contexts, label: str) -> str:
        if not contexts:
            return f"[No {label.lower()} results found]"
        parts = [f"--- {label} ({len(contexts)} results) ---"]
        for ctx in contexts:
            source = ctx.source.upper()
            ctx_label = ctx.metadata.get("label", "unknown")
            date_str = ctx.metadata.get("date", "")
            meta = f" [{date_str}]" if date_str else ""
            # Cap individual results at 2000 chars to keep tool results reasonable
            content = ctx.content[:2000]
            parts.append(f"[{source}] {ctx_label}{meta}: {content}")
        return "\n".join(parts)


# ─────────────────────────────────────────────────
# Agent Result
# ─────────────────────────────────────────────────

@dataclass
class AgentResult:
    """Returned by run_agent_loop()."""
    answer: str
    tool_calls: list = field(default_factory=list)   # [{name, input, duration_ms}]
    iterations: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    elapsed_ms: int = 0
    timed_out: bool = False


# ─────────────────────────────────────────────────
# Agent Loop — Blocking (WhatsApp)
# ─────────────────────────────────────────────────

def run_agent_loop(
    question: str,
    system_prompt: str,
    history: Optional[list] = None,
    max_iterations: int = 3,
) -> AgentResult:
    """
    Blocking agent loop.  Returns AgentResult with the final text answer.
    Used by WhatsApp (_handle_director_question).
    """
    t0 = time.time()
    executor = ToolExecutor()
    claude = anthropic.Anthropic(api_key=config.claude.api_key)

    messages = []
    for msg in (history or []):
        role = msg.get("role", "user") if isinstance(msg, dict) else "user"
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    tool_log = []
    total_in = 0
    total_out = 0

    for iteration in range(max_iterations):
        # Timeout check (PM review item #1)
        elapsed = time.time() - t0
        if elapsed > AGENT_TIMEOUT_SECONDS:
            logger.warning(f"Agent loop timed out after {elapsed:.1f}s, {iteration} iterations")
            return AgentResult(
                answer="",
                tool_calls=tool_log,
                iterations=iteration,
                total_input_tokens=total_in,
                total_output_tokens=total_out,
                elapsed_ms=int(elapsed * 1000),
                timed_out=True,
            )

        response = claude.messages.create(
            model=config.claude.model,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
            tools=TOOL_DEFINITIONS,
        )

        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens

        # Check stop reason
        if response.stop_reason == "end_turn":
            # Extract text from content blocks
            text_parts = [b.text for b in response.content if b.type == "text"]
            answer = "".join(text_parts)
            elapsed_ms = int((time.time() - t0) * 1000)
            logger.info(
                f"Agent loop done: {iteration + 1} iterations, "
                f"{len(tool_log)} tool calls, {elapsed_ms}ms, "
                f"tokens: {total_in}in/{total_out}out"
            )
            return AgentResult(
                answer=answer,
                tool_calls=tool_log,
                iterations=iteration + 1,
                total_input_tokens=total_in,
                total_output_tokens=total_out,
                elapsed_ms=elapsed_ms,
            )

        if response.stop_reason == "tool_use":
            # Build assistant message with all content blocks
            assistant_content = []
            tool_uses = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                    tool_uses.append(block)

            messages.append({"role": "assistant", "content": assistant_content})

            # Execute tools and build tool_result message
            tool_results = []
            for tu in tool_uses:
                tool_t0 = time.time()
                result_text = executor.execute(tu.name, tu.input)
                tool_ms = int((time.time() - tool_t0) * 1000)
                tool_log.append({
                    "name": tu.name,
                    "input": tu.input,
                    "duration_ms": tool_ms,
                })
                logger.info(f"Tool {tu.name}: {tool_ms}ms")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_text,
                })

            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason — treat as done
        text_parts = [b.text for b in response.content if b.type == "text"]
        answer = "".join(text_parts) or "I wasn't able to complete the search."
        elapsed_ms = int((time.time() - t0) * 1000)
        return AgentResult(
            answer=answer,
            tool_calls=tool_log,
            iterations=iteration + 1,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            elapsed_ms=elapsed_ms,
        )

    # Exhausted max_iterations without end_turn — return whatever we have
    elapsed_ms = int((time.time() - t0) * 1000)
    logger.warning(f"Agent loop hit max_iterations ({max_iterations})")
    return AgentResult(
        answer="I searched multiple sources but couldn't fully resolve your question. Here's what I found so far.",
        tool_calls=tool_log,
        iterations=max_iterations,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        elapsed_ms=elapsed_ms,
    )


# ─────────────────────────────────────────────────
# Agent Loop — Streaming (Scan SSE)
# ─────────────────────────────────────────────────

def run_agent_loop_streaming(
    question: str,
    system_prompt: str,
    history: Optional[list] = None,
    max_iterations: int = 5,
) -> Generator[dict, None, AgentResult]:
    """
    Streaming agent loop for Scan SSE.

    Yields dicts:
      {"token": "text chunk"}   — stream to client
      {"tool_call": "name"}     — optional: frontend can show loading indicator

    Returns AgentResult (accessible after generator exhaustion via .value on
    StopIteration, but the caller should track state via the yielded dicts).

    The final AgentResult is also yielded as {"_agent_result": AgentResult}.
    """
    t0 = time.time()
    executor = ToolExecutor()
    claude = anthropic.Anthropic(api_key=config.claude.api_key)

    messages = []
    for msg in (history or []):
        role = msg.get("role", "user") if isinstance(msg, dict) else "user"
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    tool_log = []
    total_in = 0
    total_out = 0
    full_answer = ""

    for iteration in range(max_iterations):
        # Timeout check
        elapsed = time.time() - t0
        if elapsed > AGENT_TIMEOUT_SECONDS:
            logger.warning(f"Agent streaming timed out after {elapsed:.1f}s")
            result = AgentResult(
                answer=full_answer,
                tool_calls=tool_log,
                iterations=iteration,
                total_input_tokens=total_in,
                total_output_tokens=total_out,
                elapsed_ms=int(elapsed * 1000),
                timed_out=True,
            )
            yield {"_agent_result": result}
            return

        # Use non-streaming API to get tool_use blocks reliably
        # (streaming with tools is tricky — partial tool_use blocks)
        response = claude.messages.create(
            model=config.claude.model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=TOOL_DEFINITIONS,
        )

        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens

        if response.stop_reason == "end_turn":
            # Stream the final text to client
            for block in response.content:
                if block.type == "text" and block.text:
                    full_answer += block.text
                    yield {"token": block.text}

            elapsed_ms = int((time.time() - t0) * 1000)
            logger.info(
                f"Agent streaming done: {iteration + 1} iterations, "
                f"{len(tool_log)} tool calls, {elapsed_ms}ms, "
                f"tokens: {total_in}in/{total_out}out"
            )
            result = AgentResult(
                answer=full_answer,
                tool_calls=tool_log,
                iterations=iteration + 1,
                total_input_tokens=total_in,
                total_output_tokens=total_out,
                elapsed_ms=elapsed_ms,
            )
            yield {"_agent_result": result}
            return

        if response.stop_reason == "tool_use":
            # Notify frontend of tool call (loading indicator)
            assistant_content = []
            tool_uses = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                    # Stream any thinking text that comes before tool calls
                    if block.text:
                        full_answer += block.text
                        yield {"token": block.text}
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                    tool_uses.append(block)
                    yield {"tool_call": block.name}

            messages.append({"role": "assistant", "content": assistant_content})

            # Execute tools
            tool_results = []
            for tu in tool_uses:
                tool_t0 = time.time()
                result_text = executor.execute(tu.name, tu.input)
                tool_ms = int((time.time() - tool_t0) * 1000)
                tool_log.append({
                    "name": tu.name,
                    "input": tu.input,
                    "duration_ms": tool_ms,
                })
                logger.info(f"Tool {tu.name}: {tool_ms}ms")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_text,
                })

            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop — stream whatever text we got
        for block in response.content:
            if block.type == "text" and block.text:
                full_answer += block.text
                yield {"token": block.text}
        break

    elapsed_ms = int((time.time() - t0) * 1000)
    result = AgentResult(
        answer=full_answer,
        tool_calls=tool_log,
        iterations=max_iterations,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        elapsed_ms=elapsed_ms,
    )
    yield {"_agent_result": result}


def is_agentic_rag_enabled() -> bool:
    """Check feature flag — can be called from dashboard.py and waha_webhook.py."""
    return _AGENTIC_RAG
