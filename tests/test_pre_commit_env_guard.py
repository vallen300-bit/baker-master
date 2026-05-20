"""Pre-commit Part 4 — render env-var wipe-pattern guard tests.

Anchor: 2026-05-17 catastrophic env-var wipe on baker-master. Part 4 of
`.githooks/pre-commit` blocks raw `PUT /v1/services/{id}/env-vars` (array
body, no /KEY suffix) at commit time. Layered above
`tools.render_env_guard.safe_env_put()` runtime wrapper.

Each test sets up an isolated tmp git repo, installs the pre-commit hook,
stages a fixture file, and asserts the hook's exit code + stderr.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SRC = REPO_ROOT / ".githooks" / "pre-commit"


def _init_repo(tmp_path: Path) -> Path:
    """Initialize a temp git repo with the pre-commit hook installed."""
    subprocess.run(
        ["git", "init", "--initial-branch=main", "-q"],
        cwd=tmp_path, check=True,
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    hook_dir = tmp_path / ".githooks"
    hook_dir.mkdir()
    shutil.copy(HOOK_SRC, hook_dir / "pre-commit")
    os.chmod(hook_dir / "pre-commit", 0o755)
    subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"],
        cwd=tmp_path, check=True,
    )
    # initial commit so HEAD exists
    (tmp_path / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"],
        cwd=tmp_path, check=True,
    )
    return tmp_path


def _commit_fixture(repo: Path, rel_path: str, content: str) -> subprocess.CompletedProcess:
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    subprocess.run(["git", "add", rel_path], cwd=repo, check=True)
    return subprocess.run(
        ["git", "commit", "-m", "fixture"],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def test_positive_1_python_httpx_array_put_blocked(tmp_path):
    repo = _init_repo(tmp_path)
    content = (
        'import httpx\n'
        'sid = "srv-xxx"\n'
        'httpx.put(f"https://api.render.com/v1/services/{sid}/env-vars", '
        'json=[{"key": "K", "value": "V"}])\n'
    )
    result = _commit_fixture(repo, "danger.py", content)
    assert result.returncode == 1, f"expected block, got rc={result.returncode}; stderr={result.stderr}"
    assert "Part 4" in result.stderr, f"stderr missing Part 4 marker: {result.stderr}"


def test_positive_2_bash_curl_array_put_blocked(tmp_path):
    repo = _init_repo(tmp_path)
    content = (
        '#!/usr/bin/env bash\n'
        "curl -X PUT https://api.render.com/v1/services/srv-xxx/env-vars "
        "-d '[{\"key\":\"K\",\"value\":\"V\"}]'\n"
    )
    result = _commit_fixture(repo, "danger.sh", content)
    assert result.returncode == 1, f"expected block, got rc={result.returncode}; stderr={result.stderr}"
    assert "Part 4" in result.stderr, f"stderr missing Part 4 marker: {result.stderr}"


def test_negative_1_safe_env_put_call_passes(tmp_path):
    repo = _init_repo(tmp_path)
    content = (
        'from tools.render_env_guard import safe_env_put\n'
        'safe_env_put("srv-xxx", "MY_KEY", "value")\n'
    )
    result = _commit_fixture(repo, "use_wrapper.py", content)
    assert result.returncode == 0, f"expected pass, got rc={result.returncode}; stderr={result.stderr}"


def test_negative_2_single_key_url_passes(tmp_path):
    repo = _init_repo(tmp_path)
    content = (
        'import httpx\n'
        'sid = "srv-xxx"\n'
        'httpx.put(f"https://api.render.com/v1/services/{sid}/env-vars/MY_KEY", '
        'json={"value": "v"})\n'
    )
    result = _commit_fixture(repo, "safe.py", content)
    assert result.returncode == 0, f"expected pass, got rc={result.returncode}; stderr={result.stderr}"


def test_negative_3_allowlisted_render_env_guard_passes(tmp_path):
    repo = _init_repo(tmp_path)
    content = (
        '"""Docstring references PUT /v1/services/{id}/env-vars URL for context."""\n'
        'pass\n'
    )
    result = _commit_fixture(repo, "tools/render_env_guard.py", content)
    assert result.returncode == 0, f"expected pass, got rc={result.returncode}; stderr={result.stderr}"


def test_negative_4_allowlisted_brief_passes(tmp_path):
    repo = _init_repo(tmp_path)
    content = (
        "# BRIEF X\n\n"
        "References `/v1/services/srv-xxx/env-vars` array PUT (the wipe pattern) in prose.\n"
    )
    result = _commit_fixture(repo, "briefs/BRIEF_X.md", content)
    assert result.returncode == 0, f"expected pass, got rc={result.returncode}; stderr={result.stderr}"
