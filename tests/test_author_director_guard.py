"""Tests for invariant_checks/author_director_guard.sh.

Each test creates a throwaway git repo in a tmp dir, stages a mutation,
runs the hook script with a synthesized commit message, and asserts the
exit code + (where relevant) the stderr content.

No mocks — real git, real script.
"""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

HOOK_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "invariant_checks"
    / "author_director_guard.sh"
)


def _init_repo(tmp_path: Path) -> Path:
    """Initialize a fresh git repo in tmp_path and return its path."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    return tmp_path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _stage(repo: Path, *paths: str) -> None:
    subprocess.run(["git", "add", *paths], cwd=repo, check=True)


def _commit_clean(repo: Path, msg: str = "seed") -> None:
    """Make a seed commit (bypassing our hook for seeding)."""
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=repo, check=True)


def _run_hook(repo: Path, commit_msg: str) -> subprocess.CompletedProcess:
    """Run the hook with COMMIT_EDITMSG containing commit_msg."""
    msg_path = repo / ".git" / "COMMIT_EDITMSG"
    msg_path.write_text(commit_msg)
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT), str(msg_path)],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def test_non_md_file_passes(tmp_path: Path):
    """Scenario 1: staged change is a .py file — hook exits 0."""
    repo = _init_repo(tmp_path)
    _write(repo / "README.md", "# seed\n")
    _stage(repo, "README.md")
    _commit_clean(repo)
    _write(repo / "code.py", "print('hi')\n")
    _stage(repo, "code.py")
    result = _run_hook(repo, "feat: add code.py")
    assert result.returncode == 0, result.stderr


def test_unprotected_md_passes(tmp_path: Path):
    """Scenario 2: staged .md file with no author:director frontmatter — allow."""
    repo = _init_repo(tmp_path)
    _write(repo / "README.md", "# seed\n")
    _stage(repo, "README.md")
    _commit_clean(repo)
    _write(repo / "notes.md", textwrap.dedent("""
        ---
        author: agent
        ---
        notes body
    """).lstrip())
    _stage(repo, "notes.md")
    result = _run_hook(repo, "docs: add notes")
    assert result.returncode == 0, result.stderr


def test_protected_md_without_marker_rejects(tmp_path: Path):
    """Scenario 3: touch author:director file, no marker — reject."""
    repo = _init_repo(tmp_path)
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: director
        ---
        original body
    """).lstrip())
    _stage(repo, "hot.md")
    _commit_clean(repo, "seed hot.md")
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: director
        ---
        modified body
    """).lstrip())
    _stage(repo, "hot.md")
    result = _run_hook(repo, "tweak: hot.md body")
    assert result.returncode == 1
    assert "CHANDA invariant #4" in result.stdout
    assert "hot.md" in result.stdout


def test_protected_md_with_marker_allows(tmp_path: Path):
    """Scenario 4: touch author:director file WITH marker — allow."""
    repo = _init_repo(tmp_path)
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: director
        ---
        original body
    """).lstrip())
    _stage(repo, "hot.md")
    _commit_clean(repo, "seed hot.md")
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: director
        ---
        updated body
    """).lstrip())
    _stage(repo, "hot.md")
    msg = 'wiki(hot.md): Monday update\n\nDirector-signed: "rewrite hot.md Monday"\n'
    result = _run_hook(repo, msg)
    assert result.returncode == 0, result.stderr + result.stdout


def test_frontmatter_toggle_bypass_blocked(tmp_path: Path):
    """Scenario 5: attempt bypass by removing author:director from frontmatter.

    Pre-version has author:director; staged version drops it. Hook must
    still detect via pre-version check.
    """
    repo = _init_repo(tmp_path)
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: director
        ---
        body
    """).lstrip())
    _stage(repo, "hot.md")
    _commit_clean(repo, "seed")
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: agent
        ---
        body
    """).lstrip())
    _stage(repo, "hot.md")
    result = _run_hook(repo, "toggle: drop author flag")
    assert result.returncode == 1
    assert "CHANDA invariant #4" in result.stdout


def test_body_false_positive_ignored(tmp_path: Path):
    """Scenario 6: 'author: director' appears in BODY, not frontmatter.

    E.g. a fenced code block quoting another file. Must not trigger.
    """
    repo = _init_repo(tmp_path)
    _write(repo / "README.md", "# seed\n")
    _stage(repo, "README.md")
    _commit_clean(repo)
    content = (
        "---\n"
        "author: agent\n"
        "---\n"
        "\n"
        "This doc references the hot.md invariant. Example frontmatter:\n"
        "\n"
        "```yaml\n"
        "author: director\n"
        "```\n"
    )
    _write(repo / "doc.md", content)
    _stage(repo, "doc.md")
    result = _run_hook(repo, "docs: add example")
    assert result.returncode == 0, result.stderr + result.stdout
