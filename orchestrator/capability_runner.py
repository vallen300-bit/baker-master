"""
Capability Runner — executes an agent loop with capability-specific config.

Reuses ToolExecutor from agent.py but filters tools per capability definition.
Reuses the same Claude API call pattern and AgentResult dataclass.

Two modes:
  run_single()     — one capability, one task (fast path, blocking)
  run_streaming()  — SSE streaming variant of run_single
  run_multi()      — multiple capabilities, sequential sub-tasks (delegate path)
  run_synthesizer()— combines multiple sub-results into one deliverable
"""
import json
import logging
import time
from typing import Generator, Optional

import anthropic

from config.settings import config
from orchestrator.agent import (
    TOOL_DEFINITIONS,
    AgentResult,
    ToolExecutor,
    _force_synthesis,
)
from orchestrator.capability_registry import CapabilityDef
from orchestrator.capability_router import RoutingPlan
from orchestrator.scan_prompt import SCAN_SYSTEM_PROMPT, build_mode_aware_prompt

logger = logging.getLogger("baker.capability_runner")

# Max sub-tasks in delegate path (safety bound)
MAX_SUB_TASKS = 4

# CORRECTION-MEMORY-1: Max corrections injected per prompt (anti-bloat)
MAX_CORRECTIONS_PER_PROMPT = 3

# ─────────────────────────────────────────────────
# PM Factory — Generic PM Configuration Registry
# ─────────────────────────────────────────────────
PM_REGISTRY_VERSION = 1  # Cowork #2: bump when registry schema changes

PM_REGISTRY = {
    "ao_pm": {
        "registry_version": 1,
        "name": "AO Project Manager",
        "view_dir": "data/ao_pm",
        "view_file_order": [
            "SCHEMA.md", "psychology.md", "investment_channels.md",
            "sensitive_issues.md", "communication_rules.md", "agenda.md",
        ],
        "state_label": "AO PM",
        "briefing_priority": 10,
        "contact_keywords": ["oskolkov", "andrey", "aelio", "aukera"],
        "entangled_matters": ["hagenauer", "rg7"],
        "briefing_section_title": "AO INVESTOR RELATIONSHIP STATUS",
        "briefing_email_patterns": ["oskolkov", "aelio"],
        "briefing_whatsapp_patterns": ["oskolkov", "andrey"],
        "briefing_deadline_patterns": [
            "oskolkov", "aelio", "aukera", "rg7", "capital call",
        ],
        "briefing_state_key": "pending_discussion_with_ao",
        "soul_md_keywords": ["oskolkov"],
        "signal_orbit_patterns": [
            r"buchwalder|gantey",
            r"pohanis|constantinos",
            r"ofenheimer|alric",
            r"@aelio\.",
            r"aukera",
        ],
        "signal_keyword_patterns": [
            r"capital.call",
            r"rg7|riemergasse",
            r"aelio|lcg",
            r"oskolkov|andrey",
            r"participation.agreement",
            r"shareholder.loan",
        ],
        "signal_whatsapp_senders": [
            r"oskolkov|andrey\s*o",
        ],
        "extraction_view_files": [
            "psychology.md", "investment_channels.md",
            "sensitive_issues.md", "communication_rules.md", "agenda.md",
        ],
        "extraction_system": (
            "Extract structured state updates AND wiki-worthy insights from "
            "this AO PM interaction. Return valid JSON only. No markdown fences."
        ),
        "extraction_state_schema": (
            "State updates: {\"sub_matters\": {}, \"open_actions\": [], "
            "\"red_flags\": [], \"relationship_state\": {}, \"summary\": \"...\"}"
        ),
        "peer_pms": ["movie_am"],
    },
    "movie_am": {
        "registry_version": 1,
        "name": "MOVIE Asset Manager",
        "view_dir": "data/movie_am",
        "view_file_order": [
            "SCHEMA.md", "agreements_framework.md", "operator_dynamics.md",
            "kpi_framework.md", "owner_obligations.md", "agenda.md",
        ],
        "state_label": "MOVIE AM",
        "briefing_priority": 20,
        "contact_keywords": [
            "francesco", "robin", "mario habicher", "rolf huebner",
            "mandarin oriental", "mohg",
        ],
        "entangled_matters": ["rg7"],
        "peer_pms": ["ao_pm"],
        "briefing_section_title": "MOVIE ASSET STATUS",
        "briefing_email_patterns": ["mandarin", "mohg", "mario.habicher"],
        "briefing_whatsapp_patterns": ["henri movie", "victor rodriguez", "rolf"],
        "briefing_deadline_patterns": [
            "mandarin", "movie", "hotel", "insurance", "warranty",
            "operating budget", "ff&e",
        ],
        "briefing_state_key": "open_approvals",
        "soul_md_keywords": ["movie", "mandarin", "riemergasse"],
        "signal_orbit_patterns": [
            r"mario\s*habicher",
            r"francesco|cefalu",
            r"robin\s*chalier",
            r"rolf\s*h[uü]bner",
            r"balazs|czepregi",
            r"@mohg\.",
            r"@mandarinoriental\.",
        ],
        "signal_keyword_patterns": [
            r"mandarin\s*oriental",
            r"\bmovie\b",
            r"rg7|riemergasse",
            r"\boccupancy\b.*\b(hotel|vienna)\b",
            r"\brevpar\b",
            r"\bgop\b.*\b(hotel|report|monthly)\b",
            r"\bff&?e\b",
            r"operating\s*budget",
            r"owner.?s?\s*approval",
            r"recovery\s*lab",
            r"warranty|gew[äa]hrleistung",
        ],
        "signal_whatsapp_senders": [
            r"rolf",
            r"henri\s*movie",
            r"victor\s*rodriguez",
        ],
        "extraction_view_files": [
            "agreements_framework.md", "operator_dynamics.md",
            "kpi_framework.md", "owner_obligations.md", "agenda.md",
        ],
        "extraction_system": (
            "Extract structured state updates AND wiki-worthy insights from "
            "this MOVIE Asset Manager interaction. Return valid JSON only. No markdown fences."
        ),
        "extraction_state_schema": (
            "State updates: {\"kpi_snapshot\": {}, \"open_approvals\": [], "
            "\"pending_reports\": [], \"red_flags\": [], \"open_actions\": [], "
            "\"relationship_state\": {}, \"summary\": \"...\"}"
        ),
    },
}


def extract_correction_from_feedback(task: dict):
    """CORRECTION-MEMORY-1: Extract a learned rule from Director feedback.
    Called async (fire-and-forget) when Director rejects/revises a task with a comment.
    Uses Haiku for extraction — cheap, fast, non-fatal."""
    try:
        import json as _json
        from orchestrator.cost_monitor import log_api_cost, check_circuit_breaker

        allowed, _ = check_circuit_breaker()
        if not allowed:
            logger.debug("Circuit breaker blocked correction extraction")
            return

        task_id = task.get("id")
        feedback = task.get("director_feedback", "")
        comment = task.get("feedback_comment", "")
        title = task.get("title", "")
        deliverable = task.get("deliverable", "")
        cap_slug = task.get("capability_slug", "")

        # Guard: need a comment to extract a meaningful rule
        if not comment or not comment.strip():
            logger.debug(f"No comment on task #{task_id} — skipping correction extraction")
            return

        from orchestrator.gemini_client import call_flash

        prompt = (
            "A Director gave feedback on an AI specialist's response. "
            "Extract ONE concise, reusable correction rule that the specialist should "
            "follow in ALL future similar situations.\n\n"
            "Rules for extraction:\n"
            "- The rule must be actionable and specific (not vague like 'do better')\n"
            "- If the correction is about a specific person/contact, include their name\n"
            "- If the correction applies to ALL specialists (not just this one), set applies_to='all'\n"
            "- If no useful rule can be extracted, return null\n\n"
            f"Specialist: {cap_slug}\n"
            f"Task: {title[:200]}\n"
            f"Response excerpt: {(deliverable or '')[:1500]}\n"
            f"Feedback: {feedback}\n"
            f"Director comment: {comment}\n\n"
            'Return JSON: {"learned_rule": "...", "matter_slug": "..."|null, '
            '"applies_to": "capability"|"all"} or null if no useful rule.'
        )

        resp = call_flash(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        log_api_cost(
            "gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens,
            source="correction_extraction", capability_id=cap_slug or "unknown",
        )

        raw = resp.text.strip()
        # Strip markdown fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        if raw.lower() in ("null", "none", "{}"):
            logger.debug(f"No useful correction from task #{task_id}")
            return

        result = _json.loads(raw)
        if not isinstance(result, dict) or not result.get("learned_rule"):
            return

        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        store.store_correction(
            baker_task_id=task_id,
            capability_slug=cap_slug or "general",
            correction_type=feedback,
            director_comment=comment,
            learned_rule=result["learned_rule"],
            matter_slug=result.get("matter_slug"),
            applies_to=result.get("applies_to", "capability"),
        )
        logger.info(
            f"CORRECTION-MEMORY-1: Extracted rule from task #{task_id}: "
            f"{result['learned_rule'][:80]}"
        )

    except Exception as e:
        logger.debug(f"Correction extraction failed (non-fatal): {e}")


class CapabilityRunner:
    def __init__(self):
        self.executor = ToolExecutor()
        self.claude = anthropic.Anthropic(api_key=config.claude.api_key)
        # PHASE-4A: lazy imports for cost + metrics
        from orchestrator.cost_monitor import log_api_cost, check_circuit_breaker
        from orchestrator.agent_metrics import log_tool_call
        self._log_api_cost = log_api_cost
        self._check_circuit_breaker = check_circuit_breaker
        self._log_tool_call = log_tool_call

    def _get_model_config(self, complexity: str = None) -> dict:
        """COMPLEXITY-ROUTER-1: Return model config based on complexity classification.
        In shadow mode, always returns deep config (current behavior)."""
        cc = config.complexity
        if cc.shadow_mode or complexity != "fast":
            return {
                "model": config.claude.model,
                "max_tokens": 4096,
                "tool_limit": None,
                "timeout": cc.deep_timeout,
            }
        return {
            "model": cc.fast_model,
            "max_tokens": cc.fast_max_tokens,
            "tool_limit": cc.fast_tool_limit,
            "timeout": cc.fast_timeout,
        }

    # ─────────────────────────────────────────────
    # Fast Path: Single Capability (blocking)
    # ─────────────────────────────────────────────

    def run_single(self, capability: CapabilityDef, question: str,
                   history: list = None, domain: str = None,
                   mode: str = None,
                   entity_context: str = "",
                   complexity: str = None) -> AgentResult:
        """
        Fast path — one capability, one question.
        Builds system prompt from capability definition.
        Filters tools to capability's tool list.
        Same agent loop structure as run_agent_loop() in agent.py.
        """
        t0 = time.time()
        # COMPLEXITY-ROUTER-1: Model config based on complexity
        mc = self._get_model_config(complexity)
        _model = mc["model"]
        _max_tokens = mc["max_tokens"]
        _tool_limit = mc["tool_limit"]
        timeout = mc["timeout"] if complexity else capability.timeout_seconds
        max_iter = capability.max_iterations
        system = self._build_system_prompt(capability, domain, mode, question=question, entity_context=entity_context)
        tools = self._get_filtered_tools(capability)

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

        for iteration in range(max_iter):
            elapsed = time.time() - t0
            if elapsed > timeout:
                logger.warning(f"Capability {capability.slug} timed out after {elapsed:.1f}s")
                # AGENTIC-LOOP-FIX: Force synthesis if we gathered research
                answer = ""
                if tool_log:
                    synth, s_in, s_out = _force_synthesis(
                        self.claude, _model, system, messages,
                        max_tokens=_max_tokens, reason="timeout")
                    total_in += s_in
                    total_out += s_out
                    answer = synth
                return AgentResult(
                    answer=answer, tool_calls=tool_log, iterations=iteration,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    elapsed_ms=int((time.time() - t0) * 1000),
                    timed_out=bool(not answer),
                )

            # PHASE-4A: Circuit breaker check
            allowed, _daily = self._check_circuit_breaker()
            if not allowed:
                logger.error(f"Capability {capability.slug} blocked by cost circuit breaker")
                return AgentResult(
                    answer="Baker API budget exceeded for today. Resuming tomorrow.",
                    tool_calls=tool_log, iterations=iteration,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    elapsed_ms=int((time.time() - t0) * 1000),
                )

            # COMPLEXITY-ROUTER-1: Enforce tool limit on fast path
            if _tool_limit and len(tool_log) >= _tool_limit:
                logger.info(f"Capability {capability.slug} hit tool limit ({_tool_limit}) on fast path")
                # AGENTIC-LOOP-FIX: Force synthesis with gathered research
                answer = ""
                if tool_log:
                    synth, s_in, s_out = _force_synthesis(
                        self.claude, _model, system, messages,
                        max_tokens=_max_tokens, reason="tool_limit")
                    total_in += s_in
                    total_out += s_out
                    answer = synth
                return AgentResult(
                    answer=answer, tool_calls=tool_log, iterations=iteration,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    elapsed_ms=int((time.time() - t0) * 1000),
                )

            # Build API params — SPECIALIST-THINKING-1: add extended thinking
            api_params = {
                "model": _model,
                "max_tokens": _max_tokens,
                "system": system,
                "messages": messages,
                "tools": tools,
            }
            if capability.use_thinking and complexity != "fast":
                api_params["thinking"] = {"type": "enabled", "budget_tokens": 10000}
                api_params["max_tokens"] = max(api_params["max_tokens"], 16000)

            response = self.claude.messages.create(**api_params)
            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens

            # PHASE-4A: Log API cost (includes thinking tokens if present)
            self._log_api_cost(_model, response.usage.input_tokens,
                               response.usage.output_tokens,
                               source="capability_runner",
                               capability_id=capability.slug)

            if response.stop_reason == "end_turn":
                text_parts = [b.text for b in response.content if b.type == "text"]
                answer = "".join(text_parts)
                elapsed_ms = int((time.time() - t0) * 1000)
                logger.info(
                    f"Capability {capability.slug} done ({complexity or 'deep'}): "
                    f"{iteration + 1} iter, {len(tool_log)} tools, {elapsed_ms}ms, model={_model}"
                )
                # Auto-insight extraction (fire-and-forget)
                import threading
                threading.Thread(
                    target=self._maybe_store_insight,
                    args=(capability, question, answer),
                    daemon=True,
                ).start()
                return AgentResult(
                    answer=answer, tool_calls=tool_log,
                    iterations=iteration + 1,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    elapsed_ms=elapsed_ms,
                )

            if response.stop_reason == "tool_use":
                assistant_content = []
                tool_uses = []
                for block in response.content:
                    if block.type == "thinking":
                        continue  # SPECIALIST-THINKING-1: skip thinking blocks
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use", "id": block.id,
                            "name": block.name, "input": block.input,
                        })
                        tool_uses.append(block)

                messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for tu in tool_uses:
                    tool_t0 = time.time()
                    tool_ok = True
                    tool_err = None
                    try:
                        result_text = self.executor.execute(tu.name, tu.input)
                    except Exception as e:
                        tool_ok = False
                        tool_err = str(e)[:500]
                        result_text = f"Error: {tool_err}"
                    tool_ms = int((time.time() - tool_t0) * 1000)
                    tool_log.append({
                        "name": tu.name, "input": tu.input,
                        "duration_ms": tool_ms,
                    })
                    # PHASE-4A: Log tool call
                    self._log_tool_call(tu.name, latency_ms=tool_ms,
                                        success=tool_ok, error_message=tool_err,
                                        source="capability_runner",
                                        capability_id=capability.slug)
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": tu.id,
                        "content": result_text,
                    })
                messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop
            text_parts = [b.text for b in response.content if b.type == "text"]
            return AgentResult(
                answer="".join(text_parts) or "",
                tool_calls=tool_log, iterations=iteration + 1,
                total_input_tokens=total_in, total_output_tokens=total_out,
                elapsed_ms=int((time.time() - t0) * 1000),
            )

        # AGENTIC-LOOP-FIX: Exhausted iterations — force synthesis
        answer = ""
        if tool_log:
            synth, s_in, s_out = _force_synthesis(
                self.claude, _model, system, messages,
                max_tokens=_max_tokens, reason="max_iterations")
            total_in += s_in
            total_out += s_out
            answer = synth
        return AgentResult(
            answer=answer, tool_calls=tool_log, iterations=max_iter,
            total_input_tokens=total_in, total_output_tokens=total_out,
            elapsed_ms=int((time.time() - t0) * 1000),
        )

    # ─────────────────────────────────────────────
    # Fast Path: Single Capability (SSE streaming)
    # ─────────────────────────────────────────────

    def run_streaming(self, capability: CapabilityDef, question: str,
                      history: list = None, domain: str = None,
                      mode: str = None,
                      entity_context: str = "",
                      complexity: str = None) -> Generator[dict, None, None]:
        """
        SSE streaming variant for Scan dashboard.
        Yields {"token": text}, {"tool_call": name}, {"_agent_result": AgentResult}.
        """
        t0 = time.time()
        # COMPLEXITY-ROUTER-1: Model config based on complexity
        mc = self._get_model_config(complexity)
        _model = mc["model"]
        _max_tokens = mc["max_tokens"]
        _tool_limit = mc["tool_limit"]
        timeout = mc["timeout"] if complexity else capability.timeout_seconds
        max_iter = capability.max_iterations
        system = self._build_system_prompt(capability, domain, mode, question=question, entity_context=entity_context)
        tools = self._get_filtered_tools(capability)

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

        for iteration in range(max_iter):
            elapsed = time.time() - t0
            if elapsed > timeout:
                # AGENTIC-LOOP-FIX: Force synthesis if we gathered research
                if tool_log:
                    synth, s_in, s_out = _force_synthesis(
                        self.claude, _model, system, messages,
                        max_tokens=_max_tokens, reason="timeout")
                    total_in += s_in
                    total_out += s_out
                    if synth:
                        yield {"token": "\n\n"}
                        yield {"token": synth}
                        full_answer = synth
                result = AgentResult(
                    answer=full_answer, tool_calls=tool_log,
                    iterations=iteration,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    elapsed_ms=int((time.time() - t0) * 1000),
                    timed_out=bool(not tool_log),
                )
                yield {"_agent_result": result}
                return

            # PHASE-4A: Circuit breaker check
            allowed, _daily = self._check_circuit_breaker()
            if not allowed:
                yield {"token": "Baker API budget exceeded for today. Resuming tomorrow."}
                result = AgentResult(
                    answer="Baker API budget exceeded for today. Resuming tomorrow.",
                    tool_calls=tool_log, iterations=iteration,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    elapsed_ms=int((time.time() - t0) * 1000),
                )
                yield {"_agent_result": result}
                return

            # COMPLEXITY-ROUTER-1: Enforce tool limit on fast path
            if _tool_limit and len(tool_log) >= _tool_limit:
                logger.info(f"Capability {capability.slug} hit tool limit ({_tool_limit}) on fast path")
                # AGENTIC-LOOP-FIX: Force synthesis with gathered research
                synth, s_in, s_out = _force_synthesis(
                    self.claude, _model, system, messages,
                    max_tokens=_max_tokens, reason="tool_limit")
                total_in += s_in
                total_out += s_out
                if synth:
                    yield {"token": "\n\n"}
                    yield {"token": synth}
                    full_answer = synth
                result = AgentResult(
                    answer=full_answer, tool_calls=tool_log, iterations=iteration,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    elapsed_ms=int((time.time() - t0) * 1000),
                )
                yield {"_agent_result": result}
                return

            # Build API params — SPECIALIST-THINKING-1: add extended thinking
            api_params = {
                "model": _model,
                "max_tokens": _max_tokens,
                "system": system,
                "messages": messages,
                "tools": tools,
            }
            if capability.use_thinking and complexity != "fast":
                api_params["thinking"] = {"type": "enabled", "budget_tokens": 10000}
                api_params["max_tokens"] = max(api_params["max_tokens"], 16000)

            response = self.claude.messages.create(**api_params)
            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens

            # PHASE-4A: Log API cost (includes thinking tokens if present)
            self._log_api_cost(_model, response.usage.input_tokens,
                               response.usage.output_tokens,
                               source="capability_runner_streaming",
                               capability_id=capability.slug)

            if response.stop_reason == "end_turn":
                for block in response.content:
                    # SPECIALIST-THINKING-1: skip thinking blocks (internal reasoning)
                    if block.type == "thinking":
                        continue
                    if block.type == "text" and block.text:
                        full_answer += block.text
                        yield {"token": block.text}
                # Auto-insight extraction (fire-and-forget)
                import threading
                threading.Thread(
                    target=self._maybe_store_insight,
                    args=(capability, question, full_answer),
                    daemon=True,
                ).start()
                result = AgentResult(
                    answer=full_answer, tool_calls=tool_log,
                    iterations=iteration + 1,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    elapsed_ms=int((time.time() - t0) * 1000),
                )
                yield {"_agent_result": result}
                return

            if response.stop_reason == "tool_use":
                assistant_content = []
                tool_uses = []
                for block in response.content:
                    if block.type == "thinking":
                        continue  # SPECIALIST-THINKING-1: skip thinking blocks
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                        if block.text:
                            full_answer += block.text
                            yield {"token": block.text}
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use", "id": block.id,
                            "name": block.name, "input": block.input,
                        })
                        tool_uses.append(block)
                        yield {"tool_call": block.name}

                messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for tu in tool_uses:
                    tool_t0 = time.time()
                    tool_ok = True
                    tool_err = None
                    try:
                        result_text = self.executor.execute(tu.name, tu.input)
                    except Exception as e:
                        tool_ok = False
                        tool_err = str(e)[:500]
                        result_text = f"Error: {tool_err}"
                    tool_ms = int((time.time() - tool_t0) * 1000)
                    tool_log.append({
                        "name": tu.name, "input": tu.input,
                        "duration_ms": tool_ms,
                    })
                    # PHASE-4A: Log tool call
                    self._log_tool_call(tu.name, latency_ms=tool_ms,
                                        success=tool_ok, error_message=tool_err,
                                        source="capability_runner_streaming",
                                        capability_id=capability.slug)
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": tu.id,
                        "content": result_text,
                    })
                messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop
            for block in response.content:
                if block.type == "text" and block.text:
                    full_answer += block.text
                    yield {"token": block.text}
            break

        # AGENTIC-LOOP-FIX: Max iterations exhausted — force synthesis
        if tool_log:
            synth, s_in, s_out = _force_synthesis(
                self.claude, _model, system, messages,
                max_tokens=_max_tokens, reason="max_iterations")
            total_in += s_in
            total_out += s_out
            if synth:
                yield {"token": "\n\n"}
                yield {"token": synth}
                full_answer = synth

        result = AgentResult(
            answer=full_answer, tool_calls=tool_log, iterations=max_iter,
            total_input_tokens=total_in, total_output_tokens=total_out,
            elapsed_ms=int((time.time() - t0) * 1000),
        )
        yield {"_agent_result": result}

    # ─────────────────────────────────────────────
    # Delegate Path: Multi-Capability (sequential v1)
    # ─────────────────────────────────────────────

    def run_multi(self, plan: RoutingPlan, question: str,
                  history: list = None, domain: str = None,
                  mode: str = None, baker_task_id: int = None,
                  entity_context: str = "") -> AgentResult:
        """
        Sequential execution of multiple sub-tasks, each with its own capability.
        Results are accumulated and passed to the synthesizer.
        Logs decomposition to decomposition_log for experience-informed retrieval.
        """
        from orchestrator.capability_registry import CapabilityRegistry

        t0 = time.time()
        sub_results = []
        all_tool_calls = []
        total_in = 0
        total_out = 0

        for i, st in enumerate(plan.sub_tasks[:MAX_SUB_TASKS]):
            sub_task_text = st.get("sub_task", question)
            slug = st.get("capability_slug", "")
            cap = CapabilityRegistry.get_instance().get_by_slug(slug)
            if not cap:
                logger.warning(f"Skipping unknown capability slug: {slug}")
                continue

            logger.info(f"Delegate sub-task {i + 1}/{len(plan.sub_tasks)}: {slug} — {sub_task_text[:80]}")
            result = self.run_single(cap, sub_task_text, history=history,
                                     domain=domain, mode=mode,
                                     entity_context=entity_context)
            sub_results.append({"slug": slug, "sub_task": sub_task_text, "result": result})
            all_tool_calls.extend(result.tool_calls)
            total_in += result.total_input_tokens
            total_out += result.total_output_tokens

        # Log decomposition to experience table (non-fatal)
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            caps_used = list({sr["slug"] for sr in sub_results})
            store.insert_decomposition_log(
                baker_task_id=baker_task_id,
                original_task=question[:1000],
                domain=domain,
                sub_tasks=plan.sub_tasks,
                capabilities_used=caps_used,
            )
        except Exception as e:
            logger.debug(f"Decomposition logging failed (non-fatal): {e}")

        if not sub_results:
            return AgentResult(
                answer="No capability results produced.",
                elapsed_ms=int((time.time() - t0) * 1000),
            )

        # Single sub-result → pass through (no synthesizer overhead)
        if len(sub_results) == 1:
            r = sub_results[0]["result"]
            return AgentResult(
                answer=r.answer, tool_calls=all_tool_calls,
                iterations=r.iterations,
                total_input_tokens=total_in, total_output_tokens=total_out,
                elapsed_ms=int((time.time() - t0) * 1000),
            )

        # Multiple results → synthesize
        synth = self.run_synthesizer(sub_results, question)
        total_in += synth.total_input_tokens
        total_out += synth.total_output_tokens
        all_tool_calls.extend(synth.tool_calls)

        return AgentResult(
            answer=synth.answer, tool_calls=all_tool_calls,
            iterations=sum(sr["result"].iterations for sr in sub_results) + synth.iterations,
            total_input_tokens=total_in, total_output_tokens=total_out,
            elapsed_ms=int((time.time() - t0) * 1000),
        )

    def run_synthesizer(self, sub_results: list, original_question: str) -> AgentResult:
        """
        Invoke the synthesizer capability to combine sub-results.
        """
        from orchestrator.capability_registry import CapabilityRegistry
        synth_cap = CapabilityRegistry.get_instance().get_synthesizer()
        if not synth_cap:
            # Fallback: concatenate results
            parts = []
            for sr in sub_results:
                parts.append(f"## {sr['slug'].upper()}: {sr['sub_task']}\n{sr['result'].answer}")
            return AgentResult(answer="\n\n".join(parts))

        # Build synthesis input
        parts = [f"Original question: {original_question}\n"]
        for i, sr in enumerate(sub_results):
            parts.append(
                f"--- Result from {sr['slug']} capability ---\n"
                f"Sub-task: {sr['sub_task']}\n"
                f"Answer:\n{sr['result'].answer}\n"
            )
        synthesis_input = "\n".join(parts)

        return self.run_single(synth_cap, synthesis_input)

    # ─────────────────────────────────────────────
    # Prompt & Tool Helpers
    # ─────────────────────────────────────────────

    def _build_system_prompt(self, capability: CapabilityDef,
                              domain: str = None, mode: str = None,
                              question: str = None,
                              entity_context: str = "") -> str:
        """
        Build system prompt for a capability run.
        1. If capability.system_prompt is non-empty → use it verbatim
        2. Otherwise → base_prompt + capability role injection
        3. Apply build_mode_aware_prompt() for domain/mode/preferences
        4. RICHER-CONTEXT-1: Inject entity context from question
        5. SPECIALIST-DEEP-1: Inject pre-fetched entity_context if provided
        """
        if capability.system_prompt:
            # Meta capabilities (decomposer, synthesizer) use their own prompt
            # For non-meta capabilities with custom prompts (e.g. Russo AI), inject tax optimization
            if capability.slug not in ("decomposer", "synthesizer"):
                prompt = capability.system_prompt
                # PM-FACTORY: Inject view files + live state for any PM
                if capability.slug in PM_REGISTRY:
                    pm_slug = capability.slug
                    pm_config = PM_REGISTRY[pm_slug]
                    label = pm_config.get("state_label", pm_slug)
                    # View files: stable compiled intelligence
                    view_ctx = self._load_pm_view_files(pm_slug)
                    if view_ctx:
                        prompt += f"\n\n# {label} VIEW (from {pm_config['view_dir']}/)\n{view_ctx}\n"
                    # Live state: dynamic data
                    state_ctx = self._get_pm_project_state_context(pm_slug)
                    if state_ctx:
                        prompt += f"\n\n# LIVE STATE (from PostgreSQL)\n{state_ctx}\n"
                    # PM-KNOWLEDGE-ARCH-1: Pending insights
                    pending_ctx = self._get_pending_insights_context(pm_slug)
                    if pending_ctx:
                        prompt += f"\n\n# KNOWLEDGE COMPOUNDING\n{pending_ctx}\n"
                    # CROSS-PM-SIGNALS: Inject peer PM state + signals
                    cross_pm_ctx = self._get_cross_pm_context(pm_slug)
                    if cross_pm_ctx:
                        prompt += f"\n\n# CROSS-PM AWARENESS\n{cross_pm_ctx}\n"
                    # PM-KNOWLEDGE-ARCH-1: Promotion instructions
                    if pending_ctx:
                        prompt += (
                            "\n\n## KNOWLEDGE COMPOUNDING INSTRUCTIONS\n"
                            "When Director says 'promote #N' or 'approve #N':\n"
                            "1. Confirm which insight is being promoted and its target view file\n"
                            "2. Use the update_pending_insight tool with status='approved'\n"
                            "3. Tell Director exactly: 'Insight #{N} approved. Queued for Code Brisen "
                            "to merge into {target_file} → {target_section}. It will appear in your "
                            "next view file update.'\n\n"
                            "When Director says 'reject #N':\n"
                            "1. Use the update_pending_insight tool with status='rejected'\n"
                            "2. ALWAYS ask for a reason and store it in review_note — this teaches "
                            "the extraction model what NOT to re-discover\n\n"
                            "When Director says 'show pending' or 'what insights are waiting':\n"
                            "1. Use the get_pending_insights tool to fetch full list\n"
                            "2. Format as numbered list with ID, insight, target file, date\n"
                        )
                prompt += (
                    "\n\n## TAX OPTIMIZATION (always consider)\n"
                    "In every analysis, proactively identify tax optimization opportunities. "
                    "Flag potential savings, structuring alternatives, or cross-border tax efficiencies "
                    "relevant to the question — even if not explicitly asked."
                )
                return prompt
            return capability.system_prompt

        # Domain capabilities: inject role into base Scan prompt
        base = SCAN_SYSTEM_PROMPT
        role_injection = (
            f"\n\n## CAPABILITY ROLE: {capability.name}\n"
            f"{capability.role_description}\n\n"
            f"Focus your analysis on this domain. Use your tools to retrieve "
            f"relevant information before answering.\n\n"
            f"## CITATION RULES (MANDATORY)\n"
            f"You MUST cite sources for every factual claim. This is non-negotiable.\n\n"
            f"Format: [Source: label] inline after the fact it supports.\n"
            f"Source labels come from [SOURCE:label]...[/SOURCE] tags in tool results.\n\n"
            f"Examples:\n"
            f'- "The TC contract termination is expected Saturday 15 March [Source: Email from Ofenheimer, 12 Mar 2026]."\n'
            f'- "Outstanding amount is approximately EUR 4.85M [Source: Meeting transcript, 25 Feb 2026]."\n'
            f'- "Hagenauer filed for debtor moratorium in Germany [Source: WhatsApp from Ofenheimer, 6 Mar 2026]."\n\n'
            f"Rules:\n"
            f"- Cite after EACH specific fact (dates, amounts, decisions, quotes)\n"
            f"- Use the exact source label from the tool results\n"
            f"- If you cannot cite a source for a claim, mark it [unverified]\n"
            f"- Never fabricate citations — only cite sources you actually retrieved\n"
            f"- A response with zero citations is unacceptable if you retrieved any sources\n"
            f"- End your response with a ## Sources section listing all cited sources"
        )
        enriched = base + role_injection

        # CORRECTION-MEMORY-1: Inject learned corrections (high-signal, rule-based)
        corrections_context = self._get_learned_corrections(capability.slug)
        if corrections_context:
            enriched += f"\n\n## LEARNED CORRECTIONS (MANDATORY)\n{corrections_context}\n"

        # LEARNING-LOOP: Inject raw past feedback as fallback context
        feedback_context = self._get_capability_feedback(capability.slug)
        if feedback_context:
            enriched += f"\n\n## PAST FEEDBACK ON YOUR RESPONSES\n{feedback_context}\n"

        # SPECIALIST-UPGRADE-1B: Inject shared Baker team insights
        insights = self._get_shared_insights(capability.slug, domain)
        if insights:
            enriched += f"\n\n## BAKER TEAM INSIGHTS\n{insights}\n"

        # CORRECTION-MEMORY-1 Phase 2: Inject similar positive examples (episodic retrieval)
        if question:
            examples_ctx = self._get_positive_examples(capability.slug, question)
            if examples_ctx:
                enriched += f"\n\n## APPROVED EXAMPLES (quality reference)\n{examples_ctx}\n"

        # B3: Inject relevant past decisions when question references a known matter
        if question:
            decisions_ctx = self._get_relevant_decisions(question)
            if decisions_ctx:
                enriched += f"\n\n## PAST DECISIONS (from Director/Cowork sessions)\n{decisions_ctx}\n"

        # RICHER-CONTEXT-1: Inject entity context (people/matters from question)
        if question and not entity_context:
            # Only auto-detect if no pre-fetched context was provided
            try:
                from orchestrator.scan_prompt import build_entity_context
                entity_ctx = build_entity_context(question)
                if entity_ctx:
                    enriched += entity_ctx
            except Exception:
                pass

        # SPECIALIST-DEEP-1: Inject pre-fetched context (emails, WA, meetings, etc.)
        if entity_context:
            enriched += f"\n\n{entity_context}"

        # TAX-OPT-1: Universal tax optimization awareness
        enriched += (
            "\n\n## TAX OPTIMIZATION (always consider)\n"
            "In every analysis, proactively identify tax optimization opportunities. "
            "Flag potential savings, structuring alternatives, or cross-border tax efficiencies "
            "relevant to the Director's question — even if not explicitly asked."
        )

        # CITATION-CONFIDENCE-1: Trailing reminder (stays fresh in context window)
        enriched += "\n\nREMINDER: Cite every factual claim with [Source: label]. Mark uncitable claims [unverified]. End with ## Sources."

        # Apply DB preferences + domain/mode extensions
        return build_mode_aware_prompt(enriched, domain=domain, mode=mode)

    def _get_capability_feedback(self, slug: str, limit: int = 3) -> str:
        """Fetch recent Director feedback on tasks handled by this capability (LEARNING-LOOP)."""
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return ""
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT title, director_feedback, feedback_comment
                    FROM baker_tasks
                    WHERE capability_slug = %s
                      AND director_feedback IS NOT NULL
                      AND director_feedback != 'accepted'
                    ORDER BY feedback_at DESC
                    LIMIT %s
                """, (slug, limit))
                rows = cur.fetchall()
                cur.close()
                if not rows:
                    return ""
                parts = ["The Director gave feedback on past responses from this capability:"]
                for title, feedback, comment in rows:
                    line = f"- Task \"{(title or '')[:80]}\": {feedback}"
                    if comment:
                        line += f" — \"{comment}\""
                    parts.append(line)
                parts.append("Adjust your approach based on this feedback.")
                return "\n".join(parts)
            finally:
                store._put_conn(conn)
        except Exception:
            return ""

    def _get_learned_corrections(self, slug: str) -> str:
        """CORRECTION-MEMORY-1: Retrieve learned corrections for this capability.
        Returns formatted string for prompt injection.
        Updates retrieval stats so frequently-used corrections survive decay."""
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            corrections = store.get_relevant_corrections(
                slug, limit=MAX_CORRECTIONS_PER_PROMPT
            )
            if not corrections:
                return ""
            parts = [
                "The Director has corrected past responses. "
                "You MUST follow these rules — they override your defaults:"
            ]
            for c in corrections:
                scope = "[ALL SPECIALISTS] " if c["applies_to"] == "all" else ""
                matter = f"[{c['matter_slug']}] " if c.get("matter_slug") else ""
                parts.append(f"- {scope}{matter}{c['learned_rule']}")
            return "\n".join(parts)
        except Exception:
            return ""

    def _get_positive_examples(self, slug: str, question: str, limit: int = 2) -> str:
        """CORRECTION-MEMORY-1 Phase 2: Retrieve similar past tasks that Director accepted.
        Uses Qdrant semantic search on baker-task-examples collection."""
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            if not store.qdrant:
                return ""
            # Embed current question for similarity search
            q_vector = store._embed(question[:500])
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            results = store.qdrant.search(
                collection_name="baker-task-examples",
                query_vector=q_vector,
                query_filter=Filter(must=[
                    FieldCondition(key="capability_slug", match=MatchValue(value=slug)),
                ]),
                limit=limit,
                score_threshold=0.5,
            )
            if not results:
                # Fallback: search without capability filter
                results = store.qdrant.search(
                    collection_name="baker-task-examples",
                    query_vector=q_vector,
                    limit=limit,
                    score_threshold=0.6,
                )
            if not results:
                return ""
            parts = [
                "Here are similar past tasks where the Director approved the response. "
                "Use these as quality examples:"
            ]
            for r in results:
                content = r.payload.get("content", "")
                # Truncate to avoid prompt bloat
                if len(content) > 800:
                    content = content[:800] + "..."
                parts.append(f"\n---\n{content}")
            return "\n".join(parts)
        except Exception:
            return ""

    def _maybe_store_insight(self, capability, question: str, answer: str,
                              baker_task_id: int = None):
        """Auto-extract key findings from specialist response. Entirely non-fatal.
        RUSSO-MEMORY-1: Also auto-save Russo AI outputs as documents for Edita.
        """
        try:
            # Guards
            if len(answer) < 200:
                return
            if capability.slug in ("decomposer", "synthesizer"):
                return

            # RUSSO-MEMORY-1: Save Russo AI outputs as documents
            if capability.slug.startswith("russo_"):
                self._store_russo_document(capability, question, answer)

            # PM-FACTORY: Auto-update any PM state
            if capability.slug in PM_REGISTRY:
                self._auto_update_pm_state(capability.slug, question, answer)

            allowed, _ = self._check_circuit_breaker()
            if not allowed:
                return

            from orchestrator.gemini_client import call_flash
            _insight_system = (
                "Extract 1-3 key factual findings from this specialist response. "
                "Only extract concrete facts: amounts, dates, legal positions, decisions, deadlines. "
                "Skip opinions, hedging, generic statements. "
                "Return JSON array: [{\"content\": \"...\", \"matter_slug\": \"...\"|null, "
                "\"confidence\": \"high\"|\"medium\"|\"low\"}]. "
                "Return empty array [] if no concrete findings."
            )
            _insight_content = f"Question: {question[:500]}\n\nResponse:\n{answer[:4000]}"

            resp = call_flash(
                messages=[{"role": "user", "content": _insight_content}],
                max_tokens=500,
                system=_insight_system,
            )
            self._log_api_cost(
                "gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens,
                source="auto_insight", capability_id=capability.slug,
            )

            raw = resp.text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()

            import json
            findings = json.loads(raw)
            if not isinstance(findings, list) or not findings:
                return

            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return
            try:
                cur = conn.cursor()
                stored = 0
                for f in findings:
                    if not isinstance(f, dict) or not f.get("content"):
                        continue
                    if f.get("confidence") == "low":
                        continue
                    cur.execute("""
                        INSERT INTO baker_insights
                            (insight_type, content, matter_slug, source_capability,
                             source_task_id, confidence, validated_by)
                        VALUES ('finding', %s, %s, %s, %s, %s, 'auto')
                    """, (
                        f["content"],
                        f.get("matter_slug"),
                        capability.slug,
                        baker_task_id,
                        f.get("confidence", "medium"),
                    ))
                    stored += 1
                conn.commit()
                cur.close()
                if stored:
                    logger.info(f"Auto-stored {stored} insights from {capability.slug}")
            finally:
                store._put_conn(conn)

        except Exception as e:
            logger.debug(f"Auto-insight extraction failed (non-fatal): {e}")

    def _store_russo_document(self, capability, question: str, answer: str):
        """RUSSO-MEMORY-1: Save Russo AI specialist output as a document for Edita."""
        try:
            from memory.store_back import SentinelStoreBack
            from datetime import datetime, timezone
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return
            try:
                cur = conn.cursor()
                title = f"Russo AI ({capability.name}): {question[:100]}"
                content = f"## Question\n{question}\n\n## Analysis\n{answer}"
                cur.execute("""
                    INSERT INTO documents
                        (title, content, doc_type, source, owner, created_at)
                    VALUES (%s, %s, 'russo_ai_analysis', %s, 'edita', NOW())
                """, (
                    title[:300],
                    content,
                    f"capability:{capability.slug}",
                ))
                conn.commit()
                cur.close()
                logger.info(f"Russo AI document stored: {title[:60]}")
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.debug(f"Russo document store failed (non-fatal): {e}")

    def _get_shared_insights(self, slug: str, domain: str = None, limit: int = 5) -> str:
        """Fetch active shared insights relevant to all specialists (SPECIALIST-UPGRADE-1B)."""
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return ""
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT content, source_capability, matter_slug, validated_by
                    FROM baker_insights
                    WHERE active = TRUE
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY
                        CASE WHEN validated_by = 'director' THEN 0 ELSE 1 END,
                        created_at DESC
                    LIMIT %s
                """, (limit,))
                rows = cur.fetchall()
                cur.close()
                if not rows:
                    return ""
                parts = ["Baker's accumulated insights (shared across all specialists):"]
                for content, source_cap, matter, validated in rows:
                    prefix = "[Director-confirmed] " if validated == "director" else ""
                    matter_tag = f"[{matter}] " if matter else ""
                    parts.append(f"- {prefix}{matter_tag}{content}")
                return "\n".join(parts)
            finally:
                store._put_conn(conn)
        except Exception:
            return ""

    def _get_relevant_decisions(self, question: str, limit: int = 5) -> str:
        """B3: Fetch past decisions relevant to the question's matter context."""
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return ""
            try:
                cur = conn.cursor()
                # Search decisions by keyword match against question
                words = [w for w in question.lower().split() if len(w) > 3][:5]
                if not words:
                    return ""
                # Build OR condition for word matching
                conditions = " OR ".join(["decision ILIKE %s"] * len(words))
                params = [f"%{w}%" for w in words]
                params.append(limit)
                cur.execute(f"""
                    SELECT decision, project, reasoning, created_at
                    FROM decisions
                    WHERE confidence != 'low'
                      AND ({conditions})
                    ORDER BY created_at DESC
                    LIMIT %s
                """, params)
                rows = cur.fetchall()
                cur.close()
                if not rows:
                    return ""
                parts = ["Relevant past decisions stored by Baker:"]
                for decision, project, reasoning, created_at in rows:
                    date_str = created_at.strftime("%Y-%m-%d") if created_at else ""
                    tag = f"[{project}] " if project else ""
                    parts.append(f"- {tag}{decision} ({date_str})")
                    if reasoning:
                        parts.append(f"  Reasoning: {reasoning[:200]}")
                return "\n".join(parts)
            finally:
                store._put_conn(conn)
        except Exception:
            return ""

    # ─────────────────────────────────────────────────
    # AO-PM-1: AO Project Manager helpers
    # ─────────────────────────────────────────────────

    def _load_pm_view_files(self, pm_slug: str) -> str:
        """PM-FACTORY: Load view files for any PM from data/{pm_slug}/ directory."""
        import os
        config = PM_REGISTRY.get(pm_slug)
        if not config:
            logger.warning("PM %s not in PM_REGISTRY — cannot load view files", pm_slug)
            return ""
        view_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), config["view_dir"])
        if not os.path.isdir(view_dir):
            logger.warning("PM %s view directory not found: %s", pm_slug, view_dir)
            return ""

        parts = []
        for fname in config["view_file_order"]:
            fpath = os.path.join(view_dir, fname)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                    parts.append(f"## VIEW FILE: {fname}\n{content}")
                except Exception as e:
                    logger.warning("Failed to read PM view file %s/%s: %s", pm_slug, fname, e)

        return "\n\n---\n\n".join(parts) if parts else ""

    def _get_pm_project_state_context(self, pm_slug: str) -> str:
        """PM-FACTORY: Format persistent PM state for system prompt injection."""
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            state = store.get_pm_project_state(pm_slug)
            if not state:
                return ""
            sj = state.get("state_json", {})
            if isinstance(sj, str):
                import json
                sj = json.loads(sj)
            parts = []
            parts.append(f"Last run: {state.get('last_run_at', 'never')}")
            parts.append(f"Run count: {state.get('run_count', 0)}")
            if state.get("last_answer_summary"):
                parts.append(f"Last interaction: {state['last_answer_summary']}")

            # Relationship state (works for any PM)
            rs = sj.get("relationship_state", {})
            if rs:
                for key, val in rs.items():
                    if val and val != "unknown":
                        label = key.replace("_", " ").title()
                        parts.append(f"{label}: {val}")

            actions = sj.get("open_actions", [])
            if actions:
                parts.append(f"Open actions ({len(actions)}):")
                for a in actions[:5]:
                    parts.append(f"  - {a}")
            flags = sj.get("red_flags", [])
            if flags:
                parts.append(f"Active red flags ({len(flags)}):")
                for rf in flags[:5]:
                    parts.append(f"  - {rf}")

            # Cross-matter awareness (if PM has entangled matters)
            config = PM_REGISTRY.get(pm_slug, {})
            entangled = config.get("entangled_matters", [])
            if entangled:
                cross_matter = self._get_cross_matter_alerts(entangled)
                if cross_matter:
                    label = config.get("state_label", pm_slug.upper())
                    parts.append(f"\n## CROSS-MATTER ALERTS (affect {label})")
                    parts.append(cross_matter)

            return "\n".join(parts)
        except Exception:
            return ""

    def _get_cross_matter_alerts(self, matters: list) -> str:
        """PM-FACTORY: Fetch developments from entangled matters."""
        if not matters:
            return ""
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return ""
            try:
                cur = conn.cursor()
                placeholders = ", ".join(["%s"] * len(matters))
                cur.execute(f"""
                    SELECT content, created_at FROM baker_insights
                    WHERE matter_slug IN ({placeholders})
                      AND active = TRUE
                    ORDER BY created_at DESC LIMIT 5
                """, tuple(matters))
                rows = cur.fetchall()
                if not rows:
                    return ""
                parts = []
                for content, created_at in rows:
                    date_str = created_at.strftime("%Y-%m-%d") if created_at else ""
                    parts.append(f"- [{date_str}] {content[:200]}")
                cur.execute(f"""
                    SELECT decision, created_at FROM decisions
                    WHERE project IN ({placeholders})
                    ORDER BY created_at DESC LIMIT 3
                """, tuple(matters))
                dec_rows = cur.fetchall()
                for decision, created_at in dec_rows:
                    date_str = created_at.strftime("%Y-%m-%d") if created_at else ""
                    parts.append(f"- [Decision {date_str}] {decision[:200]}")
                return "\n".join(parts) if parts else ""
            finally:
                store._put_conn(conn)
        except Exception:
            return ""

    def _get_cross_pm_context(self, pm_slug: str) -> str:
        """CROSS-PM-SIGNALS: Read peer PM states + active inbound signals."""
        config = PM_REGISTRY.get(pm_slug, {})
        peers = config.get("peer_pms", [])
        if not peers:
            return ""
        try:
            from memory.store_back import SentinelStoreBack
            import json as _json
            store = SentinelStoreBack._get_global_instance()
            parts = []

            for peer in peers:
                peer_config = PM_REGISTRY.get(peer, {})
                peer_label = peer_config.get("state_label", peer.upper())

                peer_state = store.get_pm_project_state(peer)
                sj = peer_state.get("state_json", {})
                if isinstance(sj, str):
                    sj = _json.loads(sj)

                peer_parts = []
                if sj.get("red_flags"):
                    flags = [str(rf)[:150] for rf in sj["red_flags"][:5]]
                    peer_parts.append("Red flags: " + "; ".join(flags))
                if sj.get("open_actions"):
                    actions = [str(a)[:100] for a in sj["open_actions"][:3]]
                    peer_parts.append("Open actions: " + "; ".join(actions))
                if sj.get("summary"):
                    peer_parts.append(f"Summary: {str(sj['summary'])[:300]}")
                if sj.get("kpi_snapshot"):
                    peer_parts.append(f"KPIs: {_json.dumps(sj['kpi_snapshot'])[:300]}")

                if peer_parts:
                    parts.append(f"## {peer_label} STATE (peer PM)\n" + "\n".join(peer_parts))

            # Active inbound signals
            signals = store.get_cross_pm_signals(pm_slug, status="active", limit=5)
            if signals:
                sig_lines = []
                for s in signals:
                    src_label = PM_REGISTRY.get(s["source_pm"], {}).get("state_label", s["source_pm"])
                    sig_lines.append(f"- [{s['signal_type']}] from {src_label}: {s['signal_text'][:200]}")
                parts.append("## INBOUND CROSS-PM SIGNALS\n" + "\n".join(sig_lines))
                parts.append(
                    "(These signals are from your peer PM. Incorporate relevant ones "
                    "into your analysis. If Director confirms an action on a signal, "
                    "update your state accordingly.)"
                )

            return "\n\n".join(parts) if parts else ""
        except Exception:
            return ""

    def _get_pending_insights_context(self, pm_slug: str) -> str:
        """PM-KNOWLEDGE-ARCH-1: Load pending insights for system prompt injection.
        Cowork refinement #2: Cap at 5 most recent, show total count."""
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return ""
            try:
                cur = conn.cursor()
                # Get total count first
                cur.execute("""
                    SELECT COUNT(*) FROM pm_pending_insights
                    WHERE pm_slug = %s AND status = 'pending'
                """, (pm_slug,))
                total_count = cur.fetchone()[0] or 0
                if total_count == 0:
                    cur.close()
                    return ""

                # Fetch top 5 most recent (Cowork #2: 10 is noise, 5 is actionable)
                cur.execute("""
                    SELECT id, insight, target_file, confidence, created_at
                    FROM pm_pending_insights
                    WHERE pm_slug = %s AND status = 'pending'
                    ORDER BY created_at DESC LIMIT 5
                """, (pm_slug,))
                rows = cur.fetchall()
                cur.close()

                parts = [f"## PENDING INSIGHTS ({total_count} total awaiting Director review)"]
                parts.append("These are facts YOU discovered that haven't been promoted to view files yet.")
                parts.append("Do NOT re-discover these. If Director asks to promote/reject, update their status.\n")
                for row_id, insight, target_file, confidence, created_at in rows:
                    date_str = created_at.strftime("%Y-%m-%d") if created_at else ""
                    parts.append(f"- **#{row_id}** [{date_str}] {insight}")
                    if target_file:
                        parts.append(f"  → Target: {target_file} (confidence: {confidence})")
                if total_count > 5:
                    parts.append(f"\n({total_count - 5} more — say 'show all pending' for full list)")
                return "\n".join(parts)
            finally:
                store._put_conn(conn)
        except Exception:
            return ""

    def _auto_update_pm_state(self, pm_slug: str, question: str, answer: str):
        """PM-FACTORY: Auto-update PM state after each run via Anthropic Opus.
        PM-KNOWLEDGE-ARCH-1: Also extract wiki-worthy insights for pending review."""
        try:
            import json
            config = PM_REGISTRY.get(pm_slug)
            if not config:
                return

            existing_context = self._get_extraction_dedup_context(pm_slug)

            extraction_files = config.get("extraction_view_files", [])
            view_file_list = ", ".join(extraction_files) if extraction_files else "view files"
            label = config.get("state_label", pm_slug)

            extraction_system = config.get(
                "extraction_system",
                f"Extract structured state updates AND wiki-worthy insights from "
                f"this {label} interaction. Return valid JSON only. No markdown fences."
            )
            state_schema = config.get(
                "extraction_state_schema",
                "State updates: {\"sub_matters\": {}, \"open_actions\": [], "
                "\"red_flags\": [], \"relationship_state\": {}, \"summary\": \"...\"}"
            )

            resp = self.claude.messages.create(
                model="claude-opus-4-6",
                max_tokens=700,
                system=extraction_system,
                messages=[{"role": "user", "content": (
                    f"Extract state updates from this {label} interaction.\n\n"
                    f"Question: {question[:500]}\n\nAnswer: {answer[:3000]}\n\n"
                    f"Return JSON with TWO sections:\n"
                    f"1. {state_schema}\n"
                    f"2. Wiki insights — facts or rules discovered that should become PERMANENT "
                    f"knowledge in the view files. Only include if:\n"
                    f"   - It's a confirmed fact, not speculation\n"
                    f"   - It would be useful in future PM invocations\n"
                    f"   - It's not already obvious from the question context\n"
                    f"   - It's >50 characters (no trivial observations)\n\n"
                    f"Confidence levels:\n"
                    f"   - high = directly stated by Director OR confirmed by document\n"
                    f"   - medium = inferred from Q&A pattern with supporting evidence\n"
                    f"   - low = speculative or single-instance observation (will be dropped)\n\n"
                    f"Available view files: {view_file_list}\n\n"
                    f"{existing_context}"
                    f"Return: {{\"sub_matters\": {{}}, \"open_actions\": [], \"red_flags\": [], "
                    f"\"relationship_state\": {{}}, \"summary\": \"...\", "
                    f"\"wiki_insights\": [{{\"insight\": \"...\", \"target_file\": \"...\", "
                    f"\"target_section\": \"...\", \"confidence\": \"high|medium\"}}]}}\n"
                    f"Return empty wiki_insights array if nothing wiki-worthy.\n"
                    f"Only include fields with NEW information. Be concise."
                )}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.split("\n")[1:-1])
            updates = json.loads(raw)

            # CRITICAL: Pop wiki insights BEFORE state update
            wiki_insights = updates.pop("wiki_insights", [])
            summary = updates.pop("summary", f"{label} interaction")

            # State update
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            store.update_pm_project_state(pm_slug, updates, summary, question[:500],
                                          mutation_source="opus_auto")
            logger.info(f"PM state ({pm_slug}) auto-updated (Opus): {summary}")

            # Store wiki insights as pending
            if wiki_insights and isinstance(wiki_insights, list):
                self._store_pending_insights(pm_slug, wiki_insights, question, summary)

            # CROSS-PM-SIGNALS: Auto-signal peer PMs on new red flags
            import re as _re
            peer_pms = config.get("peer_pms", [])
            new_flags = updates.get("red_flags", [])
            if peer_pms and new_flags:
                signal_count = 0
                for peer in peer_pms:
                    peer_kw = PM_REGISTRY.get(peer, {}).get("signal_keyword_patterns", [])
                    for flag in new_flags:
                        if signal_count >= 3:
                            break
                        flag_str = str(flag)
                        for pattern in peer_kw:
                            if _re.search(pattern, flag_str, _re.IGNORECASE):
                                store.create_cross_pm_signal(
                                    source_pm=pm_slug, target_pm=peer,
                                    signal_type="red_flag",
                                    signal_text=flag_str[:500],
                                    context=f"Auto-detected from {label} state update",
                                )
                                signal_count += 1
                                break  # one signal per flag per peer

        except Exception as e:
            logger.debug(f"PM state ({pm_slug}) auto-update failed (non-fatal): {e}")

    def _get_extraction_dedup_context(self, pm_slug: str) -> str:
        """PM-KNOWLEDGE-ARCH-1: Build dedup + rejection context for Opus extraction.
        Cowork #1: Feed existing pending insights so Opus can self-dedup.
        Cowork #4: Feed rejected insights so Opus learns what NOT to re-extract."""
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return ""
            try:
                cur = conn.cursor()
                parts = []

                # Current pending insights (don't re-extract these)
                cur.execute("""
                    SELECT insight FROM pm_pending_insights
                    WHERE pm_slug = %s AND status = 'pending'
                    ORDER BY created_at DESC LIMIT 10
                """, (pm_slug,))
                pending = [r[0] for r in cur.fetchall()]
                if pending:
                    items = "; ".join(p[:80] for p in pending)
                    parts.append(
                        f"ALREADY PENDING (do NOT re-extract): {items}\n"
                    )

                # Recently rejected insights (learn from Director's rejections)
                cur.execute("""
                    SELECT insight, review_note FROM pm_pending_insights
                    WHERE pm_slug = %s AND status = 'rejected'
                    ORDER BY reviewed_at DESC LIMIT 5
                """, (pm_slug,))
                rejected = cur.fetchall()
                if rejected:
                    items = "; ".join(
                        f"{r[0][:60]} (reason: {r[1][:40]})" if r[1]
                        else r[0][:80]
                        for r in rejected
                    )
                    parts.append(
                        f"REJECTED BY DIRECTOR (do NOT re-extract): {items}\n"
                    )

                cur.close()
                return "\n".join(parts) + "\n" if parts else ""
            finally:
                store._put_conn(conn)
        except Exception:
            return ""

    def _store_pending_insights(self, pm_slug: str, insights: list,
                                question: str, summary: str):
        """PM-KNOWLEDGE-ARCH-1: Store wiki-worthy insights in pending queue.
        Deduplicates via Opus self-dedup context (Cowork #1) + ILIKE fallback.
        Cowork missed-risk: minimum length filter to prevent trivial observations."""
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return
            try:
                cur = conn.cursor()
                stored = 0
                for item in insights[:3]:  # Max 3 insights per interaction
                    if not isinstance(item, dict) or not item.get("insight"):
                        continue
                    insight_text = item["insight"][:1000]
                    target_file = item.get("target_file", "")[:100]
                    target_section = item.get("target_section", "")[:200]
                    confidence = item.get("confidence", "medium")

                    # Guard: skip low-confidence
                    if confidence not in ("high", "medium"):
                        continue

                    # Cowork missed-risk: minimum length to prevent trivial insights
                    if len(insight_text.strip()) < 50:
                        continue

                    # Dedup fallback: ILIKE check on first 80 chars within 7 days
                    cur.execute("""
                        SELECT id FROM pm_pending_insights
                        WHERE pm_slug = %s
                          AND status IN ('pending', 'approved')
                          AND created_at > NOW() - INTERVAL '7 days'
                          AND insight ILIKE %s
                        LIMIT 1
                    """, (pm_slug, f"%{insight_text[:80]}%"))
                    if cur.fetchone():
                        continue  # Duplicate — skip

                    cur.execute("""
                        INSERT INTO pm_pending_insights
                            (pm_slug, insight, target_file, target_section,
                             source_question, source_summary, confidence)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (pm_slug, insight_text, target_file, target_section,
                          question[:500], summary[:500], confidence))
                    stored += 1
                conn.commit()
                cur.close()
                if stored:
                    logger.info(f"PM-KNOWLEDGE: Stored {stored} pending insights for {pm_slug}")
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.debug(f"Failed to store pending insights: {e}")
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.debug(f"Pending insight storage failed (non-fatal): {e}")

    def _get_filtered_tools(self, capability: CapabilityDef) -> list[dict]:
        """
        Filter TOOL_DEFINITIONS to capability's tool list.
        Empty list → all tools (backward compat).
        """
        if not capability.tools:
            return TOOL_DEFINITIONS
        return [t for t in TOOL_DEFINITIONS if t["name"] in capability.tools]

    def _get_merged_tools(self, capabilities: list[CapabilityDef]) -> list[dict]:
        """
        Merge tool lists from multiple capabilities. Deduped by name.
        """
        from orchestrator.capability_registry import CapabilityRegistry
        merged_names = CapabilityRegistry.get_instance().merge_tools(capabilities)
        if not merged_names:
            return TOOL_DEFINITIONS
        return [t for t in TOOL_DEFINITIONS if t["name"] in merged_names]
