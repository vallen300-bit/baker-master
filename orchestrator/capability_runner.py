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

    # ─────────────────────────────────────────────
    # Fast Path: Single Capability (blocking)
    # ─────────────────────────────────────────────

    def run_single(self, capability: CapabilityDef, question: str,
                   history: list = None, domain: str = None,
                   mode: str = None) -> AgentResult:
        """
        Fast path — one capability, one question.
        Builds system prompt from capability definition.
        Filters tools to capability's tool list.
        Same agent loop structure as run_agent_loop() in agent.py.
        """
        t0 = time.time()
        timeout = capability.timeout_seconds
        max_iter = capability.max_iterations
        system = self._build_system_prompt(capability, domain, mode)
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

            response = self.claude.messages.create(
                model=config.claude.model,
                max_tokens=4096,
                system=system,
                messages=messages,
                tools=tools,
            )
            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens

            if response.stop_reason == "end_turn":
                text_parts = [b.text for b in response.content if b.type == "text"]
                answer = "".join(text_parts)
                elapsed_ms = int((time.time() - t0) * 1000)
                logger.info(
                    f"Capability {capability.slug} done: {iteration + 1} iter, "
                    f"{len(tool_log)} tools, {elapsed_ms}ms"
                )
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
                    result_text = self.executor.execute(tu.name, tu.input)
                    tool_ms = int((time.time() - tool_t0) * 1000)
                    tool_log.append({
                        "name": tu.name, "input": tu.input,
                        "duration_ms": tool_ms,
                    })
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
                      mode: str = None) -> Generator[dict, None, None]:
        """
        SSE streaming variant for Scan dashboard.
        Yields {"token": text}, {"tool_call": name}, {"_agent_result": AgentResult}.
        """
        t0 = time.time()
        timeout = capability.timeout_seconds
        max_iter = capability.max_iterations
        system = self._build_system_prompt(capability, domain, mode)
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

            response = self.claude.messages.create(
                model=config.claude.model,
                max_tokens=4096,
                system=system,
                messages=messages,
                tools=tools,
            )
            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens

            if response.stop_reason == "end_turn":
                for block in response.content:
                    if block.type == "text" and block.text:
                        full_answer += block.text
                        yield {"token": block.text}
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
                    result_text = self.executor.execute(tu.name, tu.input)
                    tool_ms = int((time.time() - tool_t0) * 1000)
                    tool_log.append({
                        "name": tu.name, "input": tu.input,
                        "duration_ms": tool_ms,
                    })
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
                  mode: str = None) -> AgentResult:
        """
        Sequential execution of multiple sub-tasks, each with its own capability.
        Results are accumulated and passed to the synthesizer.
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
                                     domain=domain, mode=mode)
            sub_results.append({"slug": slug, "sub_task": sub_task_text, "result": result})
            all_tool_calls.extend(result.tool_calls)
            total_in += result.total_input_tokens
            total_out += result.total_output_tokens

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
                              domain: str = None, mode: str = None) -> str:
        """
        Build system prompt for a capability run.
        1. If capability.system_prompt is non-empty → use it verbatim
        2. Otherwise → base_prompt + capability role injection
        3. Apply build_mode_aware_prompt() for domain/mode/preferences
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
            f"relevant information before answering."
        )
        enriched = base + role_injection

        # Apply DB preferences + domain/mode extensions
        return build_mode_aware_prompt(enriched, domain=domain, mode=mode)

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
