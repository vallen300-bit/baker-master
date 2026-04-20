"""Tests for vault_mirror + MCP baker_vault_{list,read} tools.

Brief: ``briefs/BRIEF_SOT_OBSIDIAN_1_PHASE_D_VAULT_READ.md``.

Uses a local bare-repo + clone fixture instead of a live GitHub pull so
every test is hermetic. ``VAULT_MIRROR_PATH`` + ``VAULT_MIRROR_REMOTE``
env overrides route the module-under-test at the temp repo.

The B2 reviewer should check path-traversal + extension-allowlist cases
especially — regressions there give Cowork arbitrary file read on
Render's container.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest


SKILL_FIXTURE = """---
name: it-manager
description: test fixture for Phase D
---

# AI Dennis — IT Shadow Agent

Canonical test body.
""".strip() + "\n"

OPERATING_FIXTURE = """# AI Dennis — Operating\n\nOperating notes.\n"""
LONGTERM_FIXTURE = """# AI Dennis — Longterm\n\nLongterm memory.\n"""
REGISTRY_FIXTURE = "slug_registry:\n  version: 1\n  slugs: []\n"
BINARY_FIXTURE = b"\x89PNG\r\n\x1a\nfakebinary"


@pytest.fixture
def vault_mirror_repo(tmp_path, monkeypatch):
    """Create a bare source repo + clone it; point vault_mirror at the clone.

    Returns a dict:
      source_repo: Path to bare repo (simulated "origin")
      mirror_path: Path to working clone (what vault_mirror sees)
      module: freshly-imported vault_mirror with env overrides applied
    """
    source_repo = tmp_path / "baker-vault-origin.git"
    work = tmp_path / "baker-vault-work"
    mirror = tmp_path / "baker-vault-mirror"

    # Seed a working checkout so we have a commit to push.
    work.mkdir()
    (work / "_ops").mkdir()
    (work / "_ops" / "skills").mkdir()
    (work / "_ops" / "skills" / "it-manager").mkdir()
    (work / "_ops" / "skills" / "it-manager" / "SKILL.md").write_text(SKILL_FIXTURE)

    (work / "_ops" / "agents").mkdir()
    (work / "_ops" / "agents" / "ai-dennis").mkdir()
    (work / "_ops" / "agents" / "ai-dennis" / "OPERATING.md").write_text(OPERATING_FIXTURE)
    (work / "_ops" / "agents" / "ai-dennis" / "LONGTERM.md").write_text(LONGTERM_FIXTURE)
    (work / "_ops" / "agents" / "ai-dennis" / "INDEX.md").write_text("# Agents INDEX\n")

    # A registry-shaped yml under _ops/
    (work / "_ops" / "registries").mkdir()
    (work / "_ops" / "registries" / "slugs.yml").write_text(REGISTRY_FIXTURE)

    # A binary file under _ops/ — read tool must reject.
    (work / "_ops" / "skills" / "it-manager" / "image.png").write_bytes(BINARY_FIXTURE)

    # Init + commit + push to bare origin
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(source_repo)],
        check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=str(work),
        check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ["git", "add", "."], cwd=str(work),
        check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ["git", "commit", "-m", "seed"], cwd=str(work),
        check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(source_repo)], cwd=str(work),
        check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=str(work),
        check=True, capture_output=True, env=env,
    )

    monkeypatch.setenv("VAULT_MIRROR_PATH", str(mirror))
    monkeypatch.setenv("VAULT_MIRROR_REMOTE", str(source_repo))

    import vault_mirror
    importlib.reload(vault_mirror)
    vault_mirror._last_pull_at = None  # fixture-local reset
    vault_mirror.ensure_mirror()

    return {
        "source_repo": source_repo,
        "work": work,
        "mirror_path": mirror,
        "module": vault_mirror,
        "env": env,
    }


# --------------------------------------------------------------------------
# read_ops_file — brief's six core cases
# --------------------------------------------------------------------------


def test_read_happy_path_returns_content_and_sha(vault_mirror_repo):
    vm = vault_mirror_repo["module"]
    result = vm.read_ops_file("_ops/skills/it-manager/SKILL.md")
    assert result["path"] == "_ops/skills/it-manager/SKILL.md"
    assert result["content_utf8"] == SKILL_FIXTURE
    assert result["bytes"] == len(SKILL_FIXTURE.encode("utf-8"))
    assert result["sha256"] == hashlib.sha256(SKILL_FIXTURE.encode("utf-8")).hexdigest()
    assert result["truncated"] is False
    assert result.get("last_commit_sha")  # non-empty sha


def test_read_path_traversal_is_rejected(vault_mirror_repo):
    """`_ops/../CHANDA.md` escapes — must raise VaultPathError."""
    vm = vault_mirror_repo["module"]
    with pytest.raises(vm.VaultPathError):
        vm.read_ops_file("_ops/../CHANDA.md")


def test_read_absolute_path_is_rejected(vault_mirror_repo):
    vm = vault_mirror_repo["module"]
    with pytest.raises(vm.VaultPathError):
        vm.read_ops_file("/etc/passwd")


def test_read_out_of_scope_prefix_is_rejected(vault_mirror_repo):
    """Path that doesn't start with `_ops/` — must raise."""
    vm = vault_mirror_repo["module"]
    with pytest.raises(vm.VaultPathError):
        vm.read_ops_file("wiki/someone.md")


def test_read_nonexistent_returns_not_found(vault_mirror_repo):
    """404-shaped dict — NOT an exception, per brief."""
    vm = vault_mirror_repo["module"]
    result = vm.read_ops_file("_ops/skills/nonexistent/SKILL.md")
    assert result == {
        "path": "_ops/skills/nonexistent/SKILL.md",
        "error": "not_found",
    }


def test_read_binary_extension_is_rejected(vault_mirror_repo):
    """Extension-allowlist blocks .png even though it lives under _ops/."""
    vm = vault_mirror_repo["module"]
    with pytest.raises(vm.VaultPathError, match="extension not allowed"):
        vm.read_ops_file("_ops/skills/it-manager/image.png")


def test_read_oversize_returns_metadata_only(vault_mirror_repo, monkeypatch):
    """File > MAX_FILE_BYTES returns truncated=True with empty content."""
    vm = vault_mirror_repo["module"]
    big_path = vault_mirror_repo["mirror_path"] / "_ops" / "skills" / "it-manager" / "BIG.md"
    big_path.write_text("A" * (vm.MAX_FILE_BYTES + 10))

    result = vm.read_ops_file("_ops/skills/it-manager/BIG.md")
    assert result["truncated"] is True
    assert result["content_utf8"] == ""
    assert result["sha256"] is None
    assert result["bytes"] > vm.MAX_FILE_BYTES


def test_read_registry_yml_is_allowed(vault_mirror_repo):
    """slugs.yml is part of the allowlist — not just .md files."""
    vm = vault_mirror_repo["module"]
    result = vm.read_ops_file("_ops/registries/slugs.yml")
    assert result["content_utf8"] == REGISTRY_FIXTURE
    assert result["truncated"] is False


# --------------------------------------------------------------------------
# list_ops_files
# --------------------------------------------------------------------------


def test_list_ops_root_returns_all_allowed_files(vault_mirror_repo):
    vm = vault_mirror_repo["module"]
    paths = vm.list_ops_files("_ops/")
    assert "_ops/skills/it-manager/SKILL.md" in paths
    assert "_ops/agents/ai-dennis/OPERATING.md" in paths
    assert "_ops/agents/ai-dennis/LONGTERM.md" in paths
    assert "_ops/agents/ai-dennis/INDEX.md" in paths
    assert "_ops/registries/slugs.yml" in paths
    # Binary must NOT appear in listing (extension allowlist).
    assert "_ops/skills/it-manager/image.png" not in paths


def test_list_ops_agents_subdir(vault_mirror_repo):
    vm = vault_mirror_repo["module"]
    paths = vm.list_ops_files("_ops/agents/")
    assert all(p.startswith("_ops/agents/") for p in paths)
    assert "_ops/agents/ai-dennis/OPERATING.md" in paths


def test_list_out_of_scope_is_rejected(vault_mirror_repo):
    vm = vault_mirror_repo["module"]
    with pytest.raises(vm.VaultPathError):
        vm.list_ops_files("wiki/")


def test_list_traversal_is_rejected(vault_mirror_repo):
    vm = vault_mirror_repo["module"]
    with pytest.raises(vm.VaultPathError):
        vm.list_ops_files("_ops/../")


# --------------------------------------------------------------------------
# Mirror management: status, sync_tick idempotency
# --------------------------------------------------------------------------


def test_mirror_status_after_ensure(vault_mirror_repo):
    vm = vault_mirror_repo["module"]
    status = vm.mirror_status()
    assert status["vault_mirror_last_pull"] is not None
    assert status["vault_mirror_commit_sha"]
    assert len(status["vault_mirror_commit_sha"]) == 40  # full sha


def test_sync_tick_pulls_new_commit(vault_mirror_repo):
    """Make a new commit in the source, run sync_tick, assert HEAD advances."""
    vm = vault_mirror_repo["module"]
    before_sha = vm.mirror_status()["vault_mirror_commit_sha"]

    # Push a new commit from a second working clone so we don't disturb
    # the first one (simulates another B-code pushing to baker-vault).
    work2 = vault_mirror_repo["work"].parent / "work2"
    env = vault_mirror_repo["env"]
    subprocess.run(
        ["git", "clone", str(vault_mirror_repo["source_repo"]), str(work2)],
        check=True, capture_output=True, env=env,
    )
    (work2 / "_ops" / "skills" / "it-manager" / "ADDED.md").write_text("# new\n")
    subprocess.run(["git", "add", "."], cwd=str(work2), check=True, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "add"], cwd=str(work2), check=True, capture_output=True, env=env)
    subprocess.run(["git", "push", "origin", "main"], cwd=str(work2), check=True, capture_output=True, env=env)

    vm.sync_tick()

    after_sha = vm.mirror_status()["vault_mirror_commit_sha"]
    assert after_sha != before_sha
    # New file must now be readable via the mirror.
    result = vm.read_ops_file("_ops/skills/it-manager/ADDED.md")
    assert result["content_utf8"] == "# new\n"


def test_sync_interval_clamps_to_floor(monkeypatch):
    """Env under 60 is clamped up to 60."""
    monkeypatch.setenv("VAULT_SYNC_INTERVAL_SECONDS", "10")
    import vault_mirror
    importlib.reload(vault_mirror)
    assert vault_mirror.sync_interval_seconds() == vault_mirror.SYNC_INTERVAL_FLOOR_SECONDS


def test_sync_interval_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("VAULT_SYNC_INTERVAL_SECONDS", raising=False)
    import vault_mirror
    importlib.reload(vault_mirror)
    assert vault_mirror.sync_interval_seconds() == vault_mirror.DEFAULT_SYNC_INTERVAL_SECONDS


# --------------------------------------------------------------------------
# MCP dispatch — end-to-end: TOOLS registered + _dispatch routes correctly
# --------------------------------------------------------------------------


def test_mcp_tools_registered():
    """Both vault tools appear in the baker_mcp TOOLS list."""
    from baker_mcp.baker_mcp_server import TOOLS
    names = {t.name for t in TOOLS}
    assert "baker_vault_list" in names
    assert "baker_vault_read" in names


def test_mcp_dispatch_baker_vault_read_happy(vault_mirror_repo):
    from baker_mcp.baker_mcp_server import _dispatch
    output = _dispatch(
        "baker_vault_read",
        {"path": "_ops/skills/it-manager/SKILL.md"},
    )
    parsed = json.loads(output)
    assert parsed["path"] == "_ops/skills/it-manager/SKILL.md"
    assert parsed["content_utf8"] == SKILL_FIXTURE


def test_mcp_dispatch_baker_vault_read_traversal_returns_error_string(vault_mirror_repo):
    from baker_mcp.baker_mcp_server import _dispatch
    output = _dispatch("baker_vault_read", {"path": "_ops/../CHANDA.md"})
    assert output.startswith("Error:")
    assert "escapes" in output or "_ops" in output


def test_mcp_dispatch_baker_vault_read_missing_path_arg(vault_mirror_repo):
    from baker_mcp.baker_mcp_server import _dispatch
    output = _dispatch("baker_vault_read", {})
    assert output.startswith("Error:")
    assert "path" in output


def test_mcp_dispatch_baker_vault_list_returns_json(vault_mirror_repo):
    from baker_mcp.baker_mcp_server import _dispatch
    output = _dispatch("baker_vault_list", {"prefix": "_ops/agents/"})
    parsed = json.loads(output)
    assert parsed["prefix"] == "_ops/agents/"
    assert "_ops/agents/ai-dennis/OPERATING.md" in parsed["paths"]
