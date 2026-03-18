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
)
from orchestrator.capability_registry import CapabilityDef
from orchestrator.capability_router import RoutingPlan
from orchestrator.scan_prompt import SCAN_SYSTEM_PROMPT, build_mode_aware_prompt

logger = logging.getLogger("baker.capability_runner")

# Max sub-tasks in delegate path (safety bound)
MAX_SUB_TASKS = 4


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

    # ─────────────────────────────────────────────
    # Fast Path: Single Capability (blocking)
    # ─────────────────────────────────────────────

    def run_single(self, capability: CapabilityDef, question: str,
                   history: list = None, domain: str = None,
                   mode: str = None,
                   entity_context: str = "") -> AgentResult:
        """
        Fast path — one capability, one question.
        Builds system prompt from capability definition.
        Filters tools to capability's tool list.
        Same agent loop structure as run_agent_loop() in agent.py.
        """
        t0 = time.time()
        timeout = capability.timeout_seconds
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
                return AgentResult(
                    answer="", tool_calls=tool_log, iterations=iteration,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    elapsed_ms=int(elapsed * 1000), timed_out=True,
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

            # Build API params — SPECIALIST-THINKING-1: add extended thinking
            api_params = {
                "model": config.claude.model,
                "max_tokens": 4096,
                "system": system,
                "messages": messages,
                "tools": tools,
            }
            if capability.use_thinking:
                api_params["thinking"] = {"type": "enabled", "budget_tokens": 10000}
                api_params["max_tokens"] = max(api_params["max_tokens"], 16000)

            response = self.claude.messages.create(**api_params)
            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens

            # PHASE-4A: Log API cost (includes thinking tokens if present)
            self._log_api_cost(config.claude.model, response.usage.input_tokens,
                               response.usage.output_tokens,
                               source="capability_runner",
                               capability_id=capability.slug)

            if response.stop_reason == "end_turn":
                text_parts = [b.text for b in response.content if b.type == "text"]
                answer = "".join(text_parts)
                elapsed_ms = int((time.time() - t0) * 1000)
                logger.info(
                    f"Capability {capability.slug} done: {iteration + 1} iter, "
                    f"{len(tool_log)} tools, {elapsed_ms}ms"
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

        # Exhausted iterations
        return AgentResult(
            answer="", tool_calls=tool_log, iterations=max_iter,
            total_input_tokens=total_in, total_output_tokens=total_out,
            elapsed_ms=int((time.time() - t0) * 1000),
        )

    # ─────────────────────────────────────────────
    # Fast Path: Single Capability (SSE streaming)
    # ─────────────────────────────────────────────

    def run_streaming(self, capability: CapabilityDef, question: str,
                      history: list = None, domain: str = None,
                      mode: str = None,
                      entity_context: str = "") -> Generator[dict, None, None]:
        """
        SSE streaming variant for Scan dashboard.
        Yields {"token": text}, {"tool_call": name}, {"_agent_result": AgentResult}.
        """
        t0 = time.time()
        timeout = capability.timeout_seconds
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
                result = AgentResult(
                    answer=full_answer, tool_calls=tool_log,
                    iterations=iteration,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    elapsed_ms=int(elapsed * 1000), timed_out=True,
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

            # Build API params — SPECIALIST-THINKING-1: add extended thinking
            api_params = {
                "model": config.claude.model,
                "max_tokens": 4096,
                "system": system,
                "messages": messages,
                "tools": tools,
            }
            if capability.use_thinking:
                api_params["thinking"] = {"type": "enabled", "budget_tokens": 10000}
                api_params["max_tokens"] = max(api_params["max_tokens"], 16000)

            response = self.claude.messages.create(**api_params)
            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens

            # PHASE-4A: Log API cost (includes thinking tokens if present)
            self._log_api_cost(config.claude.model, response.usage.input_tokens,
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
            f"- Never fabricate citations — if no source, state the fact without a citation\n"
            f"- A response with zero citations is unacceptable if you retrieved any sources"
        )
        enriched = base + role_injection

        # LEARNING-LOOP: Inject past feedback for this capability
        feedback_context = self._get_capability_feedback(capability.slug)
        if feedback_context:
            enriched += f"\n\n## PAST FEEDBACK ON YOUR RESPONSES\n{feedback_context}\n"

        # SPECIALIST-UPGRADE-1B: Inject shared Baker team insights
        insights = self._get_shared_insights(capability.slug, domain)
        if insights:
            enriched += f"\n\n## BAKER TEAM INSIGHTS\n{insights}\n"

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

    def _maybe_store_insight(self, capability, question: str, answer: str,
                              baker_task_id: int = None):
        """Auto-extract key findings from specialist response. Entirely non-fatal."""
        try:
            # Guards
            if len(answer) < 200:
                return
            if capability.slug in ("decomposer", "synthesizer"):
                return
            allowed, _ = self._check_circuit_breaker()
            if not allowed:
                return

            _HAIKU = "claude-haiku-4-5-20251001"
            prompt = (
                "Extract 1-3 key factual findings from this specialist response. "
                "Only extract concrete facts: amounts, dates, legal positions, decisions, deadlines. "
                "Skip opinions, hedging, generic statements. "
                "Return JSON array: [{\"content\": \"...\", \"matter_slug\": \"...\"|null, "
                "\"confidence\": \"high\"|\"medium\"|\"low\"}]. "
                "Return empty array [] if no concrete findings.\n\n"
                f"Question: {question[:500]}\n\nResponse:\n{answer[:4000]}"
            )

            resp = self.claude.messages.create(
                model=_HAIKU,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            self._log_api_cost(
                _HAIKU, resp.usage.input_tokens, resp.usage.output_tokens,
                source="auto_insight", capability_id=capability.slug,
            )

            raw = resp.content[0].text.strip()
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
