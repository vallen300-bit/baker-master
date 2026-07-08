#!/usr/bin/env python3
"""Generate Baker bus identity artifacts from the vault agent registry."""
from __future__ import annotations

import argparse
import hashlib
import shlex
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency is present in Baker envs.
    raise SystemExit("PyYAML is required to generate agent identity artifacts") from exc

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = Path("/Users/dimitry/baker-vault/_ops/registries/agent_registry.yml")

PY_DATA_PATH = REPO_ROOT / "orchestrator" / "agent_identity_data.py"
SH_DATA_PATH = REPO_ROOT / "scripts" / "agent_identity_generated.sh"
DRAIN_HOOK_PATH = REPO_ROOT / "tests" / "fixtures" / "session-start-bus-drain.sh"

SYSTEM_RECIPIENT_SLUGS = ("director", "daemon", "dispatcher")
# System slugs that are NOT fleet agents (no picker / RACI, so not in the
# registry) but ARE allowed to SEND on the bus. `daemon` is the server-side
# sentinel/scheduler sender (e.g. cursor_stall_sentinel posts job-stall alerts as
# daemon). `director` is deliberately EXCLUDED — Director must never auto-send.
# These are emitted into the role-resolution maps (Python ROLE_TO_SLUG, shell
# agent_identity_resolve_role, drain-hook case) so bus_post.sh BAKER_ROLE=daemon
# resolves instead of exiting 1. (codex G3 follow-up FIX 1.)
SYSTEM_SENDER_SLUGS = ("daemon", "dispatcher")
GENERATED_BLOCK_BEGIN = "# BEGIN GENERATED AGENT IDENTITY ROLE MAP"
GENERATED_BLOCK_END = "# END GENERATED AGENT IDENTITY ROLE MAP"


def _load_registry(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict) or not isinstance(data.get("agents"), list):
        raise SystemExit(f"registry has unexpected shape: {path}")
    return data, hashlib.sha256(raw).hexdigest()


def _bus_agents(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in registry["agents"] if bool(a.get("bus_enabled"))]


def _role_patterns(agent: dict[str, Any]) -> list[str]:
    """Return accepted BAKER_ROLE inputs for one agent.

    Registry aliases and agent IDs are authoritative inputs. We add common
    shell/operator variants from the canonical slug so existing pickers keep
    working without separate hand-maintained cases.
    """
    values: list[str] = []

    def add(value: object) -> None:
        text = str(value).strip()
        if text and text not in values:
            values.append(text)

    agent_id = str(agent["agent_id"])
    add(agent_id)
    add(agent_id.upper())
    add(agent_id.lower())

    slug = str(agent["slug"])
    add(slug)
    add(slug.upper())
    add(slug.replace("-", "_"))
    add(slug.replace("-", "_").upper())
    for alias in agent.get("aliases") or []:
        add(alias)
        add(str(alias).upper())
    return values


def _system_sender_patterns(slug: str) -> list[str]:
    """Accepted BAKER_ROLE inputs for a non-agent system sender (e.g. daemon)."""
    out: list[str] = []
    for value in (slug, slug.upper(), slug.replace("-", "_"),
                  slug.replace("-", "_").upper()):
        if value not in out:
            out.append(value)
    return out


def _role_to_slug(bus_agents: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for agent in bus_agents:
        slug = str(agent["slug"])
        for pattern in _role_patterns(agent):
            existing = out.get(pattern)
            if existing is not None and existing != slug:
                raise SystemExit(f"BAKER_ROLE pattern {pattern!r} maps to both {existing!r} and {slug!r}")
            out[pattern] = slug
    # System senders (daemon) — not agents, but resolvable as bus senders.
    for slug in SYSTEM_SENDER_SLUGS:
        for pattern in _system_sender_patterns(slug):
            existing = out.get(pattern)
            if existing is not None and existing != slug:
                raise SystemExit(f"BAKER_ROLE pattern {pattern!r} maps to both {existing!r} and {slug!r}")
            out[pattern] = slug
    return out


VAULT_FALLBACK_PATH = "/Users/dimitry/baker-vault"

# Slugs that legitimately resolve to the generic vault fallback snapshot path
# (no dedicated `~/bm-<slug>` picker snapshot registered). Enumerated explicitly
# so that a genuinely NEW slug — e.g. a fleet-rollout desk install (D6) — is not
# silently swallowed by the fallback but instead triggers a fail-loud stderr
# WARNING (see _snapshot_path_for). Add a slug here only after deliberately
# deciding it should share the vault snapshot path; otherwise give it an
# explicit path above. (BAKER_OS_V2_C1_PICKER_FOLDER_WIRING_1.)
KNOWN_FALLBACK_SLUGS = frozenset({
    "aid",
    "b5",
    "researcher",
    # librarian (AG-209): picker ~/bm-librarian is a plain dir with no .git
    # (install_picker_dir.sh mkdir-only), so the forge pusher would skip it and
    # the card would stay grey — the RESEARCHER_ON_BUS_1 foot-gun. Its findings
    # commit to baker-vault (wiki/_library/), so ~/baker-vault is its real work
    # repo, exactly like researcher. SOP Row 12 hard rule (picker-without-git ->
    # ~/baker-vault) wins over brief Row 1's literal "explicit ~/bm-librarian".
    "librarian",
    "codex",
    "codex-arch",
    "russo-ai",
    "deep55",
    "ben",
    "hag-desk",
    "origination-desk",
    "ao-desk",
    "movie-desk",
    "baden-baden-desk",
    "brisen-desk",
    "bb-finance",
    "CM-1",
    "CM-2",
    "CM-3",
    "CM-4",
    "hag-filer",
})


def _snapshot_path_for(agent: dict[str, Any]) -> str | None:
    slug = str(agent["slug"])
    runtime = str(agent.get("runtime") or "")
    if runtime == "service":
        return None
    if slug in {"lead", "cowork-ah1"}:
        return "/Users/dimitry/bm-aihead1"
    if slug in {"deputy", "deputy-codex"}:
        return "/Users/dimitry/bm-aihead2"
    if slug in {"b1", "b2", "b3", "b4"}:
        return f"/Users/dimitry/bm-{slug},/Users/dimitry/bm-{slug}-brisen-lab"
    if slug in {"clerk", "clerk-haiku"}:
        return "/Users/dimitry/bm-clerk"
    if slug == "cowork-bb-desk":
        return "/Users/dimitry/bm-cowork-bb-desk"
    if slug in KNOWN_FALLBACK_SLUGS:
        return VAULT_FALLBACK_PATH
    # Fail-loud, not fail-hard: an unrecognised slug still gets a usable path so
    # generation never breaks mid-rollout, but we name it on stderr so the
    # installer wires an explicit snapshot path (or adds it to
    # KNOWN_FALLBACK_SLUGS) instead of shipping a silent wrong path.
    print(
        f"WARNING: agent slug {slug!r} has no explicit snapshot path and is not "
        f"in KNOWN_FALLBACK_SLUGS; emitting fallback {VAULT_FALLBACK_PATH!r}. "
        f"Add it to _snapshot_path_for() in "
        f"scripts/generate_agent_identity_artifacts.py.",
        file=sys.stderr,
    )
    return VAULT_FALLBACK_PATH


def _snapshot_terminals(bus_agents: list[dict[str, Any]]) -> tuple[str, ...]:
    entries: list[str] = []
    for agent in bus_agents:
        path = _snapshot_path_for(agent)
        if path:
            entries.append(f"{agent['slug']}:{path}")
    return tuple(entries)


def _py_literal(value: Any) -> str:
    if isinstance(value, tuple):
        if not value:
            return "()"
        items = ", ".join(_py_literal(v) for v in value)
        if len(value) == 1:
            items += ","
        return f"({items})"
    if isinstance(value, list):
        return _py_literal(tuple(value))
    if isinstance(value, dict):
        parts = ", ".join(f"{k!r}: {_py_literal(v)}" for k, v in value.items())
        return "{" + parts + "}"
    return repr(value)


def render_python_data(registry: dict[str, Any], registry_path: Path, registry_sha: str) -> str:
    bus_agents = _bus_agents(registry)
    agents = tuple(
        {
            "agent_id": str(agent["agent_id"]),
            "display_name": str(agent["display_name"]),
            "slug": str(agent["slug"]),
            "status": str(agent["status"]),
            "bus_enabled": bool(agent["bus_enabled"]),
            "aliases": tuple(str(a) for a in (agent.get("aliases") or ())),
            "scope": str(agent["scope"]),
            "runtime": str(agent["runtime"]),
            "reports_to": str(agent["reports_to"]),
        }
        for agent in registry["agents"]
    )
    bus_slugs = tuple(str(agent["slug"]) for agent in bus_agents)
    valid_slugs = SYSTEM_RECIPIENT_SLUGS + bus_slugs
    role_to_slug = _role_to_slug(bus_agents)
    snapshot = _snapshot_terminals(bus_agents)
    updated_at = str(registry.get("updated_at", ""))
    display_format = str(registry.get("display_format", "{agent_id} {display_name} [{slug}]"))

    return (
        '"""Generated agent identity data. Do not edit by hand.\n\n'
        f"Source: {registry_path}\n"
        f"SHA256: {registry_sha}\n"
        'Regenerate with: python3 scripts/generate_agent_identity_artifacts.py --write\n'
        '"""\n'
        "from __future__ import annotations\n\n"
        f"REGISTRY_SOURCE_PATH = {str(registry_path)!r}\n"
        f"REGISTRY_SHA256 = {registry_sha!r}\n"
        f"REGISTRY_UPDATED_AT = {updated_at!r}\n"
        f"DISPLAY_FORMAT = {display_format!r}\n"
        f"SYSTEM_RECIPIENT_SLUGS = {_py_literal(SYSTEM_RECIPIENT_SLUGS)}\n"
        f"SYSTEM_SENDER_SLUGS = {_py_literal(SYSTEM_SENDER_SLUGS)}\n"
        f"AGENTS = {_py_literal(agents)}\n"
        f"BUS_AGENT_SLUGS = {_py_literal(bus_slugs)}\n"
        f"VALID_BUS_SLUGS = {_py_literal(valid_slugs)}\n"
        f"ROLE_TO_SLUG = {_py_literal(dict(sorted(role_to_slug.items())))}\n"
        f"SNAPSHOT_TERMINALS = {_py_literal(snapshot)}\n"
    )


def _shell_array(name: str, values: tuple[str, ...]) -> str:
    body = " ".join(shlex.quote(v) for v in values)
    return f"{name}=({body})"


def _case_pattern(patterns: list[str]) -> str:
    return "|".join(shlex.quote(p) for p in patterns)


def render_shell_data(registry: dict[str, Any], registry_path: Path, registry_sha: str) -> str:
    bus_agents = _bus_agents(registry)
    bus_slugs = tuple(str(agent["slug"]) for agent in bus_agents)
    valid_slugs = SYSTEM_RECIPIENT_SLUGS + bus_slugs
    snapshot = _snapshot_terminals(bus_agents)

    lines = [
        "#!/usr/bin/env bash",
        "# Generated agent identity data. Do not edit by hand.",
        f"# Source: {registry_path}",
        f"# SHA256: {registry_sha}",
        "# Regenerate with: python3 scripts/generate_agent_identity_artifacts.py --write",
        "",
        _shell_array("AGENT_IDENTITY_SYSTEM_RECIPIENT_SLUGS", SYSTEM_RECIPIENT_SLUGS),
        _shell_array("AGENT_IDENTITY_BUS_AGENT_SLUGS", bus_slugs),
        _shell_array("AGENT_IDENTITY_VALID_SLUGS", valid_slugs),
        _shell_array("AGENT_IDENTITY_SNAPSHOT_TERMINALS", snapshot),
        "",
        "agent_identity_is_valid_slug() {",
        "  case \"${1:-}\" in",
        f"    {_case_pattern(list(valid_slugs))}) return 0 ;;",
        "    *) return 1 ;;",
        "  esac",
        "}",
        "",
        "agent_identity_resolve_role() {",
        "  case \"${1:-}\" in",
    ]
    for agent in bus_agents:
        lines.append(f"    {_case_pattern(_role_patterns(agent))}) printf '%s\\n' {shlex.quote(str(agent['slug']))} ;;")
    for slug in SYSTEM_SENDER_SLUGS:
        lines.append(f"    {_case_pattern(_system_sender_patterns(slug))}) printf '%s\\n' {shlex.quote(slug)} ;;")
    lines.extend(
        [
            "    *) return 1 ;;",
            "  esac",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def render_drain_role_block(registry: dict[str, Any], registry_path: Path, registry_sha: str) -> str:
    lines = [
        GENERATED_BLOCK_BEGIN,
        f"# Generated from {registry_path}",
        f"# SHA256: {registry_sha}",
        "case \"${BAKER_ROLE:-}\" in",
    ]
    for agent in _bus_agents(registry):
        lines.append(f"    {_case_pattern(_role_patterns(agent))}) SLUG={shlex.quote(str(agent['slug']))} ;;")
    for slug in SYSTEM_SENDER_SLUGS:
        lines.append(f"    {_case_pattern(_system_sender_patterns(slug))}) SLUG={shlex.quote(slug)} ;;")
    lines.extend(
        [
            "    *)",
            "        # No BAKER_ROLE → silent no-op. Cwd-based fallback intentionally NOT",
            "        # mirrored here to avoid auto-draining for sessions not meant to be on",
            "        # the fleet bus (e.g. Director's own Cowork sessions).",
            "        exit 0",
            "        ;;",
            "esac",
            GENERATED_BLOCK_END,
        ]
    )
    return "\n".join(lines)


def update_drain_hook(existing: str, generated_block: str) -> str:
    start = existing.find(GENERATED_BLOCK_BEGIN)
    end = existing.find(GENERATED_BLOCK_END)
    if start == -1 or end == -1 or end < start:
        raise SystemExit(f"generated block markers missing in {DRAIN_HOOK_PATH}")
    end += len(GENERATED_BLOCK_END)
    return existing[:start] + generated_block + existing[end:]


def build_outputs(registry_path: Path) -> dict[Path, str]:
    registry, registry_sha = _load_registry(registry_path)
    hook_existing = DRAIN_HOOK_PATH.read_text()
    return {
        PY_DATA_PATH: render_python_data(registry, registry_path, registry_sha),
        SH_DATA_PATH: render_shell_data(registry, registry_path, registry_sha),
        DRAIN_HOOK_PATH: update_drain_hook(
            hook_existing,
            render_drain_role_block(registry, registry_path, registry_sha),
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write generated artifacts")
    mode.add_argument("--check", action="store_true", help="fail if generated artifacts drift")
    args = parser.parse_args()

    outputs = build_outputs(args.registry)
    drifted: list[Path] = []
    for path, expected in outputs.items():
        if args.write:
            if not path.exists() or path.read_text() != expected:
                path.write_text(expected)
            continue
        if not path.exists() or path.read_text() != expected:
            drifted.append(path)

    if drifted:
        print("agent identity generated artifact drift:", file=sys.stderr)
        for path in drifted:
            print(f"  {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        print("Run: python3 scripts/generate_agent_identity_artifacts.py --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
