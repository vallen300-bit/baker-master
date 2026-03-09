"""
Capability Registry — loads capability definitions from DB.

Thread-safe singleton with 5-minute cache (same pattern as VIP cache
in decision_engine.py).

Capabilities are composable units of domain knowledge + tools + prompts.
Baker assembles one or more capabilities per task.
"""
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("baker.capability_registry")

CACHE_TTL = 300  # 5 minutes


@dataclass
class CapabilityDef:
    id: int
    slug: str
    name: str
    capability_type: str  # "domain" or "meta"
    domain: str
    role_description: str
    system_prompt: str
    tools: list = field(default_factory=list)
    output_format: str = "prose"
    autonomy_level: str = "recommend_wait"
    trigger_patterns: list = field(default_factory=list)
    max_iterations: int = 5
    timeout_seconds: float = 30.0
    active: bool = True
    use_thinking: bool = False  # SPECIALIST-THINKING-1: extended thinking for analytical specialists
    # Compiled regex patterns (not stored in DB, built at cache refresh)
    _compiled_patterns: list = field(default_factory=list, repr=False)


class CapabilityRegistry:
    """Singleton registry. Loads from DB, caches 5 min."""

    _instance = None
    _cache_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "CapabilityRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._cache: list[CapabilityDef] = []
        self._cache_time: float = 0
        self._by_slug: dict[str, CapabilityDef] = {}
        self._by_domain: dict[str, list[CapabilityDef]] = {}

    def _refresh_cache(self):
        """Reload capability definitions from PostgreSQL."""
        with self._cache_lock:
            if time.time() - self._cache_time < CACHE_TTL and self._cache:
                return  # Still fresh
            try:
                from memory.store_back import SentinelStoreBack
                store = SentinelStoreBack._get_global_instance()
                rows = store.get_capability_sets(active_only=True)
                caps = []
                by_slug = {}
                by_domain: dict[str, list[CapabilityDef]] = {}
                for row in rows:
                    tools = row.get("tools") or []
                    if isinstance(tools, str):
                        tools = json.loads(tools)
                    trigger_raw = row.get("trigger_patterns") or []
                    if isinstance(trigger_raw, str):
                        trigger_raw = json.loads(trigger_raw)
                    # Compile trigger patterns once
                    compiled = []
                    for pat in trigger_raw:
                        try:
                            compiled.append(re.compile(pat, re.IGNORECASE))
                        except re.error:
                            logger.warning(f"Bad regex in capability {row['slug']}: {pat}")

                    cap = CapabilityDef(
                        id=row["id"],
                        slug=row["slug"],
                        name=row["name"],
                        capability_type=row.get("capability_type", "domain"),
                        domain=row.get("domain", "projects"),
                        role_description=row.get("role_description", ""),
                        system_prompt=row.get("system_prompt", ""),
                        tools=tools,
                        output_format=row.get("output_format", "prose"),
                        autonomy_level=row.get("autonomy_level", "recommend_wait"),
                        trigger_patterns=trigger_raw,
                        max_iterations=row.get("max_iterations", 5),
                        timeout_seconds=row.get("timeout_seconds", 30.0),
                        active=row.get("active", True),
                        use_thinking=row.get("use_thinking", False),
                        _compiled_patterns=compiled,
                    )
                    caps.append(cap)
                    by_slug[cap.slug] = cap
                    by_domain.setdefault(cap.domain, []).append(cap)

                self._cache = caps
                self._by_slug = by_slug
                self._by_domain = by_domain
                self._cache_time = time.time()
                logger.info(f"Capability registry refreshed: {len(caps)} active capabilities")
            except Exception as e:
                logger.warning(f"Capability registry refresh failed (non-fatal): {e}")

    def get_all_active(self) -> list[CapabilityDef]:
        """Return all active capability definitions."""
        self._refresh_cache()
        return list(self._cache)

    def get_by_slug(self, slug: str) -> Optional[CapabilityDef]:
        """Look up a single capability by slug."""
        self._refresh_cache()
        return self._by_slug.get(slug)

    def get_by_domain(self, domain: str) -> list[CapabilityDef]:
        """Get all domain-type capabilities matching a domain."""
        self._refresh_cache()
        return [c for c in self._by_domain.get(domain, [])
                if c.capability_type == "domain"]

    def get_decomposer(self) -> Optional[CapabilityDef]:
        """Return the decomposer meta capability."""
        self._refresh_cache()
        return self._by_slug.get("decomposer")

    def get_synthesizer(self) -> Optional[CapabilityDef]:
        """Return the synthesizer meta capability."""
        self._refresh_cache()
        return self._by_slug.get("synthesizer")

    def match_trigger(self, text: str) -> Optional[CapabilityDef]:
        """Match text against all domain capabilities' trigger patterns.
        Returns the first match (most specific wins — patterns are ordered)."""
        self._refresh_cache()
        for cap in self._cache:
            if cap.capability_type != "domain":
                continue
            for rx in cap._compiled_patterns:
                if rx.search(text):
                    return cap
        return None

    def get_multiple(self, slugs: list[str]) -> list[CapabilityDef]:
        """Return multiple capabilities by slug list. Skips unknown slugs."""
        self._refresh_cache()
        return [self._by_slug[s] for s in slugs if s in self._by_slug]

    def merge_tools(self, capabilities: list[CapabilityDef]) -> list[str]:
        """Union of tool lists from multiple capabilities. Deduped, order preserved."""
        seen = set()
        merged = []
        for cap in capabilities:
            for tool in cap.tools:
                if tool not in seen:
                    seen.add(tool)
                    merged.append(tool)
        return merged
