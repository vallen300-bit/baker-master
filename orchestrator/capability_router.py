"""
Capability Router — selects one or more capabilities for a task.

Fast path (mode=handle): pick best single capability → run directly.
Delegate path (mode=delegate): invoke decomposer → get capability list per sub-task.

Experience-informed: searches past decompositions before routing.
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import anthropic

from config.settings import config
from orchestrator.capability_registry import CapabilityDef, CapabilityRegistry

logger = logging.getLogger("baker.capability_router")


@dataclass
class RoutingPlan:
    """Output of the router — tells Baker what to run."""
    mode: str  # "fast" or "delegate"
    capabilities: list = field(default_factory=list)  # CapabilityDef list
    sub_tasks: list = field(default_factory=list)  # [{sub_task, capability_slug}, ...]
    experience_context: str = ""


class CapabilityRouter:
    def __init__(self):
        self.registry = CapabilityRegistry.get_instance()

    def route(self, text: str, domain: str = None, mode: str = None,
              scored: dict = None) -> Optional[RoutingPlan]:
        """
        Main entry point. Returns a RoutingPlan or None (generic RAG fallback).

        1. Try explicit trigger match (Director names a capability)
        2. If mode == "handle" → fast path (single best capability)
        3. If mode == "delegate" → delegate path (decompose + multi-capability)
        4. If mode == "escalate" → None (ask Director)
        5. If nothing matches → None (use generic RAG)
        """
        # 1. Explicit trigger match
        explicit = self.route_explicit(text)
        if explicit:
            logger.info(f"Route: explicit match → {explicit.slug}")
            return RoutingPlan(
                mode="fast",
                capabilities=[explicit],
            )

        # 2. Mode-based routing
        if mode == "escalate":
            return None  # Fall through to generic RAG

        if mode == "delegate":
            return self.route_delegate(text, domain, scored)

        # mode == "handle" or default
        cap = self.route_fast(text, domain, scored)
        if cap:
            return RoutingPlan(mode="fast", capabilities=[cap])

        return None  # No capability match — generic RAG

    def route_explicit(self, text: str) -> Optional[CapabilityDef]:
        """Regex match: 'have the finance agent analyze...' → finance capability."""
        pattern = re.compile(
            r"\b(?:have|ask|tell|get|use)\s+(?:the\s+)?(\w+)\s+(?:agent|capability)\b",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if match:
            hint = match.group(1).lower()
            cap = self.registry.get_by_slug(hint)
            if cap and cap.capability_type == "domain":
                return cap
            # Try matching hint against capability names
            for c in self.registry.get_all_active():
                if c.capability_type != "domain":
                    continue
                if hint in c.slug or hint in c.name.lower():
                    return c
        return None

    def route_fast(self, text: str, domain: str = None,
                   scored: dict = None) -> Optional[CapabilityDef]:
        """
        Pick the single best capability for a simple task.
        1. Try trigger pattern match across all domain capabilities
        2. If domain specified, get domain capabilities and score keyword overlap
        3. Return best match or None
        """
        # Try trigger patterns first (most specific)
        trigger_match = self.registry.match_trigger(text)
        if trigger_match:
            return trigger_match

        # Domain-scoped matching
        if domain:
            domain_caps = self.registry.get_by_domain(domain)
            if len(domain_caps) == 1:
                return domain_caps[0]
            if domain_caps:
                # Score by keyword overlap with role_description
                best = None
                best_score = 0
                text_words = set(text.lower().split())
                for cap in domain_caps:
                    desc_words = set(cap.role_description.lower().split())
                    overlap = len(text_words & desc_words)
                    if overlap > best_score:
                        best_score = overlap
                        best = cap
                if best and best_score >= 2:
                    return best

        return None

    def route_delegate(self, text: str, domain: str = None,
                       scored: dict = None) -> Optional[RoutingPlan]:
        """
        Complex task path:
        1. Retrieve similar past tasks from decomposition_log
        2. Call decomposer capability (Claude call with decomposition prompt)
        3. Decomposer returns: [{sub_task, capability_slug}, ...]
        4. Validate all slugs exist in registry
        5. Return RoutingPlan with sub_tasks and capabilities
        """
        decomposer = self.registry.get_decomposer()
        if not decomposer:
            logger.warning("No decomposer capability found — falling back to fast path")
            cap = self.route_fast(text, domain, scored)
            if cap:
                return RoutingPlan(mode="fast", capabilities=[cap])
            return None

        # Retrieve past experience
        experience = self._retrieve_experience(text, domain)

        # Build decomposer prompt with experience context
        system = decomposer.system_prompt
        if "{experience_context}" in system:
            system = system.replace("{experience_context}",
                                     experience or "No past patterns available yet.")

        try:
            claude = anthropic.Anthropic(api_key=config.claude.api_key)
            resp = claude.messages.create(
                model=config.claude.model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": text}],
            )
            raw = resp.content[0].text.strip()
            # Strip markdown code fences
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
            sub_tasks = json.loads(raw)
        except Exception as e:
            logger.error(f"Decomposer failed: {e}")
            cap = self.route_fast(text, domain, scored)
            if cap:
                return RoutingPlan(mode="fast", capabilities=[cap])
            return None

        # Validate and enforce max 4 sub-tasks
        if not isinstance(sub_tasks, list):
            sub_tasks = [sub_tasks]
        sub_tasks = sub_tasks[:4]

        # Validate slugs exist
        valid_sub_tasks = []
        capabilities = []
        seen_slugs = set()
        for st in sub_tasks:
            slug = st.get("capability_slug", "")
            cap = self.registry.get_by_slug(slug)
            if cap and cap.capability_type == "domain":
                valid_sub_tasks.append(st)
                if slug not in seen_slugs:
                    capabilities.append(cap)
                    seen_slugs.add(slug)
            else:
                logger.warning(f"Decomposer returned unknown slug '{slug}' — skipping")

        if not valid_sub_tasks:
            logger.warning("Decomposer produced no valid sub-tasks — falling back to fast")
            cap = self.route_fast(text, domain, scored)
            if cap:
                return RoutingPlan(mode="fast", capabilities=[cap])
            return None

        # Single sub-task → fast path (avoid unnecessary synthesis overhead)
        if len(valid_sub_tasks) == 1:
            return RoutingPlan(
                mode="fast",
                capabilities=capabilities,
                sub_tasks=valid_sub_tasks,
                experience_context=experience,
            )

        return RoutingPlan(
            mode="delegate",
            capabilities=capabilities,
            sub_tasks=valid_sub_tasks,
            experience_context=experience,
        )

    def _retrieve_experience(self, text: str, domain: str = None) -> str:
        """
        Search decomposition_log for similar past tasks.
        Returns formatted context string for the decomposer.
        """
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            logs = store.get_decomposition_logs(domain=domain, limit=10)
            if not logs:
                return ""

            # Simple keyword overlap scoring
            text_words = set(text.lower().split())
            scored = []
            for log in logs:
                task_words = set(log.get("original_task", "").lower().split())
                overlap = len(text_words & task_words)
                if overlap >= 2:
                    scored.append((overlap, log))

            scored.sort(key=lambda x: x[0], reverse=True)
            top = scored[:3]  # Top 3 most similar

            if not top:
                return ""

            parts = []
            for _, log in top:
                sub_tasks = log.get("sub_tasks", [])
                caps_used = log.get("capabilities_used", [])
                feedback = log.get("director_feedback", "none")
                quality = log.get("outcome_quality", "unknown")
                parts.append(
                    f"Task: \"{log.get('original_task', '?')}\" (domain: {log.get('domain', '?')})\n"
                    f"→ Sub-tasks: {json.dumps(sub_tasks)}\n"
                    f"→ Capabilities: {', '.join(caps_used)}\n"
                    f"→ Director feedback: {feedback} (quality: {quality})"
                )
            return "\n\n".join(parts)
        except Exception as e:
            logger.debug(f"Experience retrieval failed (non-fatal): {e}")
            return ""
