"""Resolver helpers for the Brisen agent identity registry."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from orchestrator.agent_identity_data import AGENTS, DISPLAY_FORMAT, ROLE_TO_SLUG


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    display_name: str
    slug: str
    status: str
    bus_enabled: bool
    aliases: tuple[str, ...]
    scope: str
    runtime: str
    reports_to: str


def _from_mapping(row: dict[str, Any]) -> AgentIdentity:
    return AgentIdentity(
        agent_id=str(row["agent_id"]),
        display_name=str(row["display_name"]),
        slug=str(row["slug"]),
        status=str(row["status"]),
        bus_enabled=bool(row["bus_enabled"]),
        aliases=tuple(str(a) for a in row.get("aliases", ())),
        scope=str(row["scope"]),
        runtime=str(row["runtime"]),
        reports_to=str(row["reports_to"]),
    )


def _generated_agents() -> tuple[AgentIdentity, ...]:
    return tuple(_from_mapping(dict(row)) for row in AGENTS)


def load_registry(path: str | Path) -> tuple[AgentIdentity, ...]:
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict) or not isinstance(data.get("agents"), list):
        raise ValueError(f"agent registry has unexpected shape: {path}")
    return tuple(_from_mapping(row) for row in data["agents"])


def _role_map_for(agents: Iterable[AgentIdentity]) -> dict[str, str]:
    role_map: dict[str, str] = {}
    for agent in agents:
        variants = {
            agent.agent_id,
            agent.agent_id.upper(),
            agent.agent_id.lower(),
            agent.slug,
            agent.slug.upper(),
            agent.slug.replace("-", "_"),
            agent.slug.replace("-", "_").upper(),
            *agent.aliases,
            *(alias.upper() for alias in agent.aliases),
        }
        for variant in variants:
            role_map[variant] = agent.slug
    return role_map


def resolve_agent(value: str, registry_path: str | Path | None = None) -> AgentIdentity:
    """Resolve an agent ID, slug, or alias into one canonical agent identity."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("agent value is empty")

    if registry_path is None:
        agents = _generated_agents()
        role_map = ROLE_TO_SLUG
    else:
        agents = load_registry(registry_path)
        role_map = _role_map_for(agents)

    slug = role_map.get(raw, raw)
    by_slug = {agent.slug: agent for agent in agents}
    try:
        return by_slug[slug]
    except KeyError as exc:
        raise KeyError(f"unknown agent slug or alias: {value!r}") from exc


def identity_label(value: str, registry_path: str | Path | None = None) -> str:
    agent = resolve_agent(value, registry_path=registry_path)
    return DISPLAY_FORMAT.format(
        agent_id=agent.agent_id,
        display_name=agent.display_name,
        slug=agent.slug,
    )
