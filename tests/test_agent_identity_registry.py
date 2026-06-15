from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from orchestrator.agent_identity_data import (
    BUS_AGENT_SLUGS,
    ROLE_TO_SLUG,
    SNAPSHOT_TERMINALS,
    SYSTEM_SENDER_SLUGS,
    VALID_BUS_SLUGS,
)
from orchestrator.agent_identity_registry import identity_label, resolve_agent

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / "scripts" / "generate_agent_identity_artifacts.py"
REGISTRY = Path("/Users/dimitry/baker-vault/_ops/registries/agent_registry.yml")


def test_identity_label_disambiguates_codex_variants():
    assert identity_label("codex") == "AG-202 Codex Rev [codex]"
    assert identity_label("codex-arch") == "AG-203 Codex Arch [codex-arch]"
    assert identity_label("AG-203") == "AG-203 Codex Arch [codex-arch]"


def test_aliases_resolve_to_canonical_slugs():
    assert resolve_agent("hagenauer-desk").slug == "hag-desk"
    assert resolve_agent("research-agent").slug == "researcher"
    assert resolve_agent("ai-dennis").slug == "aid"
    assert resolve_agent("CM_1").slug == "CM-1"
    assert resolve_agent("AO_DESK").slug == "ao-desk"
    assert resolve_agent("RUSSO_AI").slug == "russo-ai"


def test_agent_ids_resolve_to_canonical_slugs():
    assert resolve_agent("AG-203").slug == "codex-arch"
    assert resolve_agent("ag-203").slug == "codex-arch"
    assert resolve_agent("AG-004").slug == "deputy-codex"
    assert resolve_agent("AG-003").slug == "deputy"
    assert identity_label("AG-004") == "AG-004 Codex Deputy [deputy-codex]"
    assert identity_label("AG-003") == "AG-003 Deputy [deputy]"
    assert identity_label("AG-206") == "AG-206 Russo AI [russo-ai]"


def test_bus_sets_include_clerk_haiku_and_exclude_reserved_or_legacy_architect():
    assert "clerk-haiku" in VALID_BUS_SLUGS
    assert "clerk-haiku" in BUS_AGENT_SLUGS
    assert "ao-desk" in VALID_BUS_SLUGS
    assert "ao-desk" in BUS_AGENT_SLUGS
    assert "russo-ai" in VALID_BUS_SLUGS
    assert "russo-ai" in BUS_AGENT_SLUGS
    assert "russo-it" not in VALID_BUS_SLUGS
    assert "russo-it" not in BUS_AGENT_SLUGS
    assert "b5" not in VALID_BUS_SLUGS
    assert "architect" not in VALID_BUS_SLUGS


def test_snapshot_terminals_include_generated_registry_agents():
    assert "codex-arch:/Users/dimitry/baker-vault" in SNAPSHOT_TERMINALS
    assert "clerk:/Users/dimitry/bm-clerk" in SNAPSHOT_TERMINALS
    assert "clerk-haiku:/Users/dimitry/bm-clerk" in SNAPSHOT_TERMINALS
    assert "ao-desk:/Users/dimitry/baker-vault" in SNAPSHOT_TERMINALS
    assert "russo-ai:/Users/dimitry/baker-vault" in SNAPSHOT_TERMINALS
    assert all(not item.startswith("cortex:") for item in SNAPSHOT_TERMINALS)


def test_daemon_resolves_as_bus_sender_director_does_not():
    # codex G3 follow-up FIX 1: daemon must resolve as a SENDER role (so
    # bus_post.sh BAKER_ROLE=daemon posts instead of exiting 1), while director
    # stays recipient-only (must never auto-send).
    assert "daemon" in SYSTEM_SENDER_SLUGS
    assert ROLE_TO_SLUG.get("daemon") == "daemon"
    assert ROLE_TO_SLUG.get("DAEMON") == "daemon"
    assert "director" not in SYSTEM_SENDER_SLUGS
    assert "director" not in ROLE_TO_SLUG  # recipient-only, not a sender
    # daemon remains a valid recipient; no duplication in VALID_BUS_SLUGS
    assert "daemon" in VALID_BUS_SLUGS
    assert list(VALID_BUS_SLUGS).count("daemon") == 1
    # daemon is a system sender, NOT a fleet bus agent
    assert "daemon" not in BUS_AGENT_SLUGS


def test_shell_resolve_role_handles_daemon():
    script = REPO_ROOT / "scripts" / "agent_identity_generated.sh"
    out = subprocess.run(
        ["bash", "-c",
         f". {script}; agent_identity_resolve_role daemon"],
        capture_output=True, text=True, timeout=10,
    )
    assert out.returncode == 0
    assert out.stdout.strip() == "daemon"
    # director must NOT resolve as a sender
    out2 = subprocess.run(
        ["bash", "-c",
         f". {script}; agent_identity_resolve_role director"],
        capture_output=True, text=True, timeout=10,
    )
    assert out2.returncode != 0


def test_generated_artifacts_match_vault_registry():
    assert REGISTRY.exists(), f"missing canonical registry: {REGISTRY}"
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--registry", str(REGISTRY), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
