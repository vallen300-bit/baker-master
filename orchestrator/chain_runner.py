"""
AUTONOMOUS-CHAINS-1 — Plan-Execute-Verify Chain Runner

Trigger-initiated autonomous action chains for Baker.
When a T1/T2 event is detected with a matched matter, Baker generates
a multi-step action plan, executes it using existing tools, verifies
outcomes, and reports to Director.

Kill switch: BAKER_CHAINS_ENABLED=false (default).

Entry point: maybe_run_chain() — called from pipeline.py after alert creation.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import anthropic

from config.settings import config

logger = logging.getLogger("baker.chain_runner")

# Director WhatsApp ID (same as waha_webhook.py)
DIRECTOR_WHATSAPP = "41799605092@c.us"


# ─────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────

@dataclass
class ChainStep:
    """A single step in an action chain."""
    tool: str
    input: dict
    purpose: str
    auto_execute: bool = True
    # Populated after execution
    result: str = ""
    success: bool = False
    elapsed_ms: int = 0
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class ChainResult:
    """Outcome of a full chain execution."""
    chain_id: Optional[int] = None  # baker_tasks ID
    trigger_type: str = ""
    matter_slug: str = ""
    assessment: str = ""
    steps: list = field(default_factory=list)  # List[ChainStep]
    director_summary: str = ""
    total_steps: int = 0
    completed_steps: int = 0
    write_actions: int = 0
    elapsed_ms: int = 0
    aborted: bool = False
    abort_reason: str = ""


# ─────────────────────────────────────────────────
# Write-action classification
# ─────────────────────────────────────────────────

_WRITE_TOOLS = {"draft_email", "create_deadline", "create_calendar_event", "clickup_create"}
_ALWAYS_AUTO = {"create_deadline", "create_calendar_event", "clickup_create"}
_NEEDS_APPROVAL = {"draft_email"}  # External emails queued, internal auto-send


# ─────────────────────────────────────────────────
# Rate limiter — prevent runaway chains
# ─────────────────────────────────────────────────

_chain_timestamps: list = []  # timestamps of recent chains


def _check_rate_limit() -> bool:
    """Return True if under the max_chains_per_hour limit."""
    now = time.time()
    cutoff = now - 3600
    _chain_timestamps[:] = [t for t in _chain_timestamps if t > cutoff]
    if len(_chain_timestamps) >= config.chains.max_chains_per_hour:
        logger.warning(
            f"Chain rate limit hit ({len(_chain_timestamps)} chains in last hour, "
            f"max {config.chains.max_chains_per_hour})"
        )
        return False
    return True


# ─────────────────────────────────────────────────
# Planning Prompt
# ─────────────────────────────────────────────────

_CHAIN_PLANNING_PROMPT = """You are Baker, an AI Chief of Staff for Dimitry Vallen (Chairman, Brisen Group).
An event has been detected that may require autonomous action. Generate a structured action plan.

Available tools (use exact names):
READ tools (always auto_execute: true):
- search_memory: Broad semantic search across all knowledge
- search_meetings: Search meeting transcripts
- search_emails: Search email messages
- search_whatsapp: Search WhatsApp messages
- get_contact: Look up a contact profile
- get_deadlines: Get active deadlines
- get_clickup_tasks: Search ClickUp tasks
- search_deals_insights: Search deals and insights
- get_matter_context: Get matter with connected people and recent comms
- search_documents: Search full documents
- query_baker_data: SQL queries on Baker's structured data

WRITE tools:
- draft_email: Draft email for Director approval (auto_execute: false)
- create_deadline: Create a tracked deadline (auto_execute: true)
- create_calendar_event: Block calendar time (auto_execute: true)
- clickup_create: Create a ClickUp task in BAKER space (auto_execute: true)

Rules:
- Max 5 steps. Be ruthlessly efficient — don't search if context already has the info.
- Start with get_matter_context (it returns people, keywords, recent emails/WA in one call).
- Read tools are always auto_execute: true.
- draft_email is always auto_execute: false (Director approves before sending).
- create_deadline, create_calendar_event, clickup_create are auto_execute: true.
- Do NOT include steps that duplicate info already provided in the context.
- Only add write steps if there's a clear, specific action to take. Don't create deadlines for things already tracked.
- Prefer 3-4 focused steps over 6-7 broad ones.
- director_summary: 2-3 lines for WhatsApp. Bottom-line first.
- Each step can reference results from previous steps — they execute sequentially.

Example chain (good):
1. get_matter_context → pulls people, recent emails, WA for the matter
2. search_emails → find the specific email that triggered this alert
3. draft_email → draft a follow-up based on what was found
Total: 3 steps, focused, fast.

Example chain (bad):
1. search_memory → too broad
2. search_emails → overlaps with matter context
3. search_whatsapp → overlaps with matter context
4. get_contact → already in matter context
5. get_deadlines → unnecessary unless deadline-related
6. draft_email → finally does something useful
Total: 6 steps, 4 are redundant.

Return ONLY valid JSON:
{
  "assessment": "2-3 sentence situation assessment",
  "urgency": "Why this needs attention now",
  "steps": [
    {
      "tool": "tool_name",
      "input": {"param": "value"},
      "purpose": "Why this step is needed",
      "auto_execute": true
    }
  ],
  "director_summary": "Short WhatsApp message for Director"
}"""


# ─────────────────────────────────────────────────
# Qualification — should this trigger start a chain?
# ─────────────────────────────────────────────────

def should_chain(trigger_type: str, alert_tier: int, matter_slug: str) -> bool:
    """Only high-value, context-rich events get chains."""
    if not config.chains.enabled:
        return False
    if alert_tier > 2:
        return False
    if not matter_slug:
        return False
    if trigger_type in ("dropbox_file_new", "dropbox_file_modified", "rss_article"):
        return False
    if not _check_rate_limit():
        return False
    # Circuit breaker
    try:
        from orchestrator.cost_monitor import check_circuit_breaker
        allowed, _ = check_circuit_breaker()
        if not allowed:
            logger.info("Chain skipped — cost circuit breaker active")
            return False
    except Exception:
        pass
    return True


# ─────────────────────────────────────────────────
# Planning — generate action plan via Claude
# ─────────────────────────────────────────────────

def _build_planning_context(
    trigger_content: str,
    alert_title: str,
    alert_body: str,
    matter_slug: str,
) -> str:
    """Assemble context for the planning prompt."""
    parts = [
        f"## EVENT\nAlert: {alert_title}\n{alert_body}",
        f"\nTrigger content:\n{trigger_content[:2000]}",
    ]

    # Pull matter context
    try:
        from memory.retriever import SentinelRetriever
        retriever = SentinelRetriever()
        matter = retriever.get_matter_context(matter_slug)
        if matter:
            parts.append(
                f"\n## MATTER: {matter.get('matter_name', matter_slug)}\n"
                f"Description: {matter.get('description', 'N/A')}\n"
                f"People: {', '.join(matter.get('people', []))}\n"
                f"Keywords: {', '.join(matter.get('keywords', []))}"
            )
    except Exception as e:
        logger.debug(f"Matter context fetch failed: {e}")

    # Pull active deadlines for this matter
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("""
                    SELECT description, due_date, priority, status
                    FROM deadlines
                    WHERE status = 'active'
                      AND (description ILIKE %s OR description ILIKE %s)
                    ORDER BY due_date ASC
                    LIMIT 5
                """, (f"%{matter_slug}%", f"%{matter_slug.replace('_', ' ')}%"))
                deadlines = cur.fetchall()
                cur.close()
                if deadlines:
                    dl_lines = ["\n## ACTIVE DEADLINES"]
                    for dl in deadlines:
                        due = dl["due_date"].strftime("%Y-%m-%d") if dl.get("due_date") else "TBD"
                        dl_lines.append(f"- [{dl.get('priority', 'normal').upper()}] {due}: {dl['description']}")
                    parts.append("\n".join(dl_lines))
            finally:
                store._put_conn(conn)
    except Exception as e:
        logger.debug(f"Deadline fetch for chain context failed: {e}")

    # Weekly priorities (most important — shapes the chain's focus)
    try:
        from orchestrator.priority_manager import format_priorities_for_prompt
        priority_text = format_priorities_for_prompt()
        if priority_text:
            parts.append(f"\n{priority_text}")
    except Exception:
        pass

    # Director preferences (long-term strategic context)
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        prefs = store.get_preferences(category="strategic_priority")
        if prefs:
            pref_lines = ["\n## DIRECTOR PREFERENCES"]
            for p in prefs[:5]:
                pref_lines.append(f"- {p.get('pref_key', '')}: {p.get('pref_value', '')}")
            parts.append("\n".join(pref_lines))
    except Exception:
        pass

    return "\n".join(parts)


def _generate_plan(
    claude_client: anthropic.Anthropic,
    context: str,
) -> Optional[dict]:
    """Call Claude to generate a structured action plan."""
    try:
        resp = claude_client.messages.create(
            model=config.claude.model,
            max_tokens=2048,
            system=_CHAIN_PLANNING_PROMPT,
            messages=[{"role": "user", "content": context}],
        )
        # Log cost
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(
                config.claude.model, resp.usage.input_tokens,
                resp.usage.output_tokens, source="chain_planner",
            )
        except Exception:
            pass

        raw = resp.content[0].text.strip()
        # Strip markdown code fences
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        plan = json.loads(raw)

        # Validate structure
        if not isinstance(plan.get("steps"), list):
            logger.warning("Chain plan missing 'steps' list")
            return None
        if len(plan["steps"]) > config.chains.max_steps:
            plan["steps"] = plan["steps"][:config.chains.max_steps]
            logger.info(f"Chain plan truncated to {config.chains.max_steps} steps")

        # Enforce auto_execute rules
        for step in plan["steps"]:
            tool = step.get("tool", "")
            if tool in _NEEDS_APPROVAL:
                step["auto_execute"] = False
            elif tool not in _WRITE_TOOLS:
                step["auto_execute"] = True

        logger.info(
            f"Chain plan generated: {len(plan['steps'])} steps, "
            f"assessment: {plan.get('assessment', '')[:80]}"
        )
        return plan

    except json.JSONDecodeError as e:
        logger.error(f"Chain plan JSON parse failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Chain plan generation failed: {e}")
        return None


# ─────────────────────────────────────────────────
# Execution — run each step via ToolExecutor
# ─────────────────────────────────────────────────

def _adapt_write_steps(plan: dict, read_results: list) -> dict:
    """After read steps complete, adapt write step inputs using gathered context.
    Uses Haiku for fast, cheap adaptation (~EUR 0.002)."""
    write_steps = [s for s in plan.get("steps", []) if s.get("tool") in _WRITE_TOOLS]
    if not write_steps or not read_results:
        return plan

    # Build context from read results
    context_parts = []
    for step_result in read_results:
        if step_result.get("success") and step_result.get("result"):
            context_parts.append(f"[{step_result['tool']}]: {step_result['result'][:1000]}")

    if not context_parts:
        return plan

    context = "\n\n".join(context_parts)

    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        adapt_prompt = (
            "Based on the information gathered below, refine the write action inputs. "
            "Return ONLY a JSON array of updated write steps with the same structure.\n\n"
            f"Original assessment: {plan.get('assessment', '')}\n\n"
            f"Gathered context:\n{context[:3000]}\n\n"
            f"Write steps to refine:\n{json.dumps(write_steps, indent=2)}"
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": adapt_prompt}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens,
                         resp.usage.output_tokens, source="chain_adapt")
        except Exception:
            pass

        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        adapted = json.loads(raw)
        if isinstance(adapted, list):
            # Replace write steps in the plan
            write_idx = 0
            for i, step in enumerate(plan["steps"]):
                if step.get("tool") in _WRITE_TOOLS and write_idx < len(adapted):
                    plan["steps"][i]["input"] = adapted[write_idx].get("input", step["input"])
                    write_idx += 1
            logger.info(f"Chain write steps adapted based on {len(read_results)} read results")
    except Exception as e:
        logger.debug(f"Chain adaptation failed (using original plan): {e}")

    return plan


def _execute_plan(plan: dict, timeout: float) -> ChainResult:
    """Execute a chain plan step by step with context forwarding."""
    from orchestrator.agent import ToolExecutor
    from orchestrator.agent_metrics import log_tool_call

    executor = ToolExecutor()
    t0 = time.time()

    result = ChainResult(
        assessment=plan.get("assessment", ""),
        director_summary=plan.get("director_summary", ""),
        total_steps=len(plan.get("steps", [])),
    )

    # Phase 1: Execute read steps
    read_results = []
    write_step_indices = []
    for i, step_def in enumerate(plan.get("steps", [])):
        if step_def.get("tool") in _WRITE_TOOLS:
            write_step_indices.append(i)
        else:
            read_results.append({"index": i, **step_def})

    # Phase 2: Adapt write steps based on read results (after all reads complete)
    # This happens inline during execution — read steps run first, then adaptation, then writes

    read_completed = []

    for i, step_def in enumerate(plan.get("steps", [])):
        # Timeout check
        elapsed = time.time() - t0
        if elapsed > timeout:
            result.aborted = True
            result.abort_reason = f"Timeout after {elapsed:.1f}s at step {i + 1}"
            logger.warning(result.abort_reason)
            break

        tool = step_def.get("tool", "")
        tool_input = step_def.get("input", {})
        purpose = step_def.get("purpose", "")
        auto_execute = step_def.get("auto_execute", True)

        step = ChainStep(
            tool=tool,
            input=tool_input,
            purpose=purpose,
            auto_execute=auto_execute,
        )

        # Adapt write steps when transitioning from reads to writes
        if tool in _WRITE_TOOLS and read_completed and not getattr(result, '_adapted', False):
            result._adapted = True
            try:
                plan = _adapt_write_steps(plan, read_completed)
                # Refresh this step's input from adapted plan
                tool_input = plan["steps"][i].get("input", tool_input)
                logger.info("Chain: write steps adapted from read context")
            except Exception as e:
                logger.debug(f"Chain adaptation skipped: {e}")

        # Validate tool exists
        valid_tools = {
            "search_memory", "search_meetings", "search_emails", "search_whatsapp",
            "get_contact", "get_deadlines", "get_clickup_tasks", "search_deals_insights",
            "get_matter_context", "search_documents", "query_baker_data",
            "draft_email", "create_deadline", "create_calendar_event", "clickup_create",
            "web_search", "read_document", "enrich_linkedin",
        }
        if tool not in valid_tools:
            step.skipped = True
            step.skip_reason = f"Unknown tool: {tool}"
            result.steps.append(step)
            logger.warning(f"Chain step {i + 1} skipped: unknown tool '{tool}'")
            continue

        # Execute with per-tool timeout (30s max per tool)
        step_t0 = time.time()
        tool_ok = True
        tool_err = None
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(executor.execute, tool, tool_input)
                step.result = future.result(timeout=30)
            step.success = True
            if tool in _WRITE_TOOLS:
                result.write_actions += 1
        except concurrent.futures.TimeoutError:
            tool_ok = False
            tool_err = f"Tool {tool} timed out after 30s"
            step.result = f"Error: {tool_err}"
            step.success = False
            logger.warning(f"Chain step {i + 1} ({tool}) timed out after 30s")
        except Exception as e:
            tool_ok = False
            tool_err = str(e)[:500]
            step.result = f"Error: {tool_err}"
            step.success = False
            logger.error(f"Chain step {i + 1} ({tool}) failed: {e}")

        step.elapsed_ms = int((time.time() - step_t0) * 1000)
        result.steps.append(step)
        result.completed_steps += 1

        # Track read results for write step adaptation
        if step.success and tool not in _WRITE_TOOLS:
            read_completed.append({
                "tool": tool,
                "success": True,
                "result": step.result[:2000],
            })

        # Log tool call metrics
        try:
            log_tool_call(
                tool, latency_ms=step.elapsed_ms,
                success=tool_ok, error_message=tool_err,
                source="chain_runner",
            )
        except Exception:
            pass

        logger.info(
            f"Chain step {i + 1}/{result.total_steps}: {tool} "
            f"({'OK' if step.success else 'FAIL'}, {step.elapsed_ms}ms) — {purpose[:60]}"
        )

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result


# ─────────────────────────────────────────────────
# Verification — check outcomes
# ─────────────────────────────────────────────────

def _verify_chain(result: ChainResult) -> str:
    """Verify chain outcomes and return summary."""
    failed = [s for s in result.steps if not s.success and not s.skipped]
    skipped = [s for s in result.steps if s.skipped]

    if result.aborted:
        return f"ABORTED: {result.abort_reason}"
    if failed:
        fail_tools = ", ".join(s.tool for s in failed)
        return f"PARTIAL: {result.completed_steps}/{result.total_steps} steps, failed: {fail_tools}"
    if skipped:
        return f"COMPLETED with {len(skipped)} skipped steps"
    return "COMPLETED: all steps successful"


# ─────────────────────────────────────────────────
# Notification — WhatsApp to Director
# ─────────────────────────────────────────────────

def _notify_director(result: ChainResult):
    """Send WA notification if chain had write actions (per Director preference)."""
    notify_mode = config.chains.notify_mode

    should_notify = False
    if notify_mode == "always":
        should_notify = True
    elif notify_mode == "write_actions_only":
        should_notify = result.write_actions > 0
    elif notify_mode == "t1_only":
        # Caller would need to pass tier — for now treat same as write_actions_only
        should_notify = result.write_actions > 0

    if not should_notify:
        logger.info("Chain notification skipped (no write actions, mode=write_actions_only)")
        return

    summary = result.director_summary or result.assessment
    if not summary:
        summary = f"Chain completed: {result.completed_steps}/{result.total_steps} steps"

    # Add write action count
    if result.write_actions > 0:
        action_types = []
        for s in result.steps:
            if s.tool in _WRITE_TOOLS and s.success:
                if s.tool == "draft_email":
                    action_types.append("email draft queued")
                elif s.tool == "create_deadline":
                    action_types.append("deadline created")
                elif s.tool == "create_calendar_event":
                    action_types.append("calendar event created")
                elif s.tool == "clickup_create":
                    action_types.append("ClickUp task created")
        if action_types:
            summary += f"\n\nActions: {', '.join(action_types)}"

    verification = _verify_chain(result)
    if "FAIL" in verification or "ABORT" in verification:
        summary += f"\n({verification})"

    # Send via WAHA
    try:
        from outputs.whatsapp_sender import send_whatsapp
        # Prefix with chain indicator
        wa_text = f"[Chain] {summary}"
        send_whatsapp(wa_text[:1500])
        logger.info("Chain notification sent to Director via WhatsApp")
    except Exception as e:
        logger.warning(f"Chain WA notification failed (non-fatal): {e}")


# ─────────────────────────────────────────────────
# Logging — store chain results in baker_tasks
# ─────────────────────────────────────────────────

def _log_chain(
    result: ChainResult,
    trigger_type: str,
    matter_slug: str,
    alert_id: Optional[int],
) -> Optional[int]:
    """Log chain execution to baker_tasks table."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()

        # Build deliverable text
        deliverable_parts = [
            f"**Assessment:** {result.assessment}",
            f"\n**Verification:** {_verify_chain(result)}",
            f"\n**Steps ({result.completed_steps}/{result.total_steps}):**",
        ]
        for i, step in enumerate(result.steps):
            status = "OK" if step.success else ("SKIP" if step.skipped else "FAIL")
            deliverable_parts.append(
                f"  {i + 1}. [{status}] {step.tool}: {step.purpose} ({step.elapsed_ms}ms)"
            )
        if result.write_actions > 0:
            deliverable_parts.append(f"\n**Write actions:** {result.write_actions}")

        deliverable = "\n".join(deliverable_parts)

        # Create baker_task
        task_id = store.create_baker_task(
            domain=matter_slug,
            tier=1,  # Chains only run for T1/T2
            mode="chain",
            task_type="chain",
            title=f"Chain: {result.assessment[:80]}",
            description=result.director_summary,
            source="chain_runner",
            channel="pipeline",
            status="completed",
        )

        if task_id:
            store.update_baker_task(
                task_id,
                deliverable=deliverable[:8000],
                agent_iterations=result.total_steps,
                agent_tool_calls=result.completed_steps,
                agent_elapsed_ms=result.elapsed_ms,
            )
            logger.info(f"Chain logged as baker_task #{task_id}")

        return task_id
    except Exception as e:
        logger.warning(f"Chain logging failed (non-fatal): {e}")
        return None


# ─────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────

def maybe_run_chain(
    trigger_type: str,
    trigger_content: str,
    alert_id: int,
    alert_title: str,
    alert_body: str,
    alert_tier: int,
    matter_slug: str,
):
    """
    Called from pipeline.py after alert creation.
    Qualifies the trigger, generates a plan, executes it, verifies, reports.
    Runs synchronously (pipeline is already per-trigger).
    """
    # 1. QUALIFY
    if not should_chain(trigger_type, alert_tier, matter_slug):
        return

    logger.info(
        f"{'=' * 50}\n"
        f"CHAIN START: {alert_title[:60]} (matter={matter_slug}, tier={alert_tier})\n"
        f"{'=' * 50}"
    )
    _chain_timestamps.append(time.time())

    # 2. PLAN
    try:
        claude_client = anthropic.Anthropic(api_key=config.claude.api_key)
    except Exception as e:
        logger.error(f"Chain aborted — Claude client init failed: {e}")
        return

    context = _build_planning_context(
        trigger_content=trigger_content,
        alert_title=alert_title,
        alert_body=alert_body,
        matter_slug=matter_slug,
    )

    plan = _generate_plan(claude_client, context)
    if not plan:
        logger.warning("Chain aborted — planning failed")
        return

    # 3. EXECUTE
    chain_result = _execute_plan(plan, timeout=config.chains.timeout_seconds)
    chain_result.trigger_type = trigger_type
    chain_result.matter_slug = matter_slug

    # 4. VERIFY
    verification = _verify_chain(chain_result)
    logger.info(f"Chain verification: {verification}")

    # 5. LOG
    task_id = _log_chain(chain_result, trigger_type, matter_slug, alert_id)
    chain_result.chain_id = task_id

    # 6. REPORT
    _notify_director(chain_result)

    logger.info(
        f"CHAIN COMPLETE: {chain_result.completed_steps}/{chain_result.total_steps} steps, "
        f"{chain_result.write_actions} write actions, {chain_result.elapsed_ms}ms total"
    )
