"""Tests for the inline-dispatch WARN-level pass in .githooks/brief_sop_check.sh.

Brief: dispatched by lead #14741 off the AH2 HARNESS_V2_ADOPTION_AUDIT 2026-07-21.

Gap closed: the hook trigger excluded `briefs/_tasks/CODE_<N>_PENDING.md`, so inline
mailbox dispatches escaped the Harness V2 adoption check entirely (5/8 sampled
production PRs shipped inline with no formal brief). The fix adds a SEPARATE
WARN-level pass over CODE_<N>_PENDING dispatches that flags missing HV2 essentials
(Context Contract, task class, done rubric/done-state, gate plan / post-deploy AC)
WITHOUT blocking — so an incident fix dispatched inline is never stalled. It escalates
to a hard block only when BAKER_BRIEF_SOP_INLINE_HARD_BLOCK=1 (default 0).

The hook uses `git diff --cached` + `git show :path`, so each test builds a throwaway
git repo, stages a synthetic file, and runs the real hook against it.
"""
from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".githooks" / "brief_sop_check.sh"

COMPLIANT_INLINE = """\
# CODE_1_PENDING — SYNTHETIC_INLINE_DISPATCH_1

## Context
Synthetic inline dispatch for the brief-sop inline-warn test.

Context Contract: routed owner b3, small-fix-production.
task_class: small-fix-production
Done-state class: merged to main, codex PASS.
Gate Plan: G0 codex, G2 security-review.
"""

# Missing all four HV2 essentials (>=2 missing => flagged).
NONCOMPLIANT_INLINE = """\
# CODE_1_PENDING — SYNTHETIC_INLINE_DISPATCH_2

## Context
Just do the thing. No harness evidence here.
"""

NA_ESCAPE_INLINE = """\
Harness-V2: N/A — docs-only inline dispatch, no production code.

# CODE_1_PENDING — SYNTHETIC_INLINE_DISPATCH_3
Nothing to enforce.
"""

# A formal brief missing 3+ of the 5 SOP headers — used to prove the existing
# hard-block path is untouched by the inline change.
BAD_FORMAL_BRIEF = """\
# BRIEF — SYNTHETIC_BAD_FORMAL

## Context
Only a context header; missing Problem / Files / Verification / Quality.
"""


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    hooks_dir = tmp_path / ".githooks"
    hooks_dir.mkdir()
    dest = hooks_dir / "brief_sop_check.sh"
    shutil.copy2(HOOK, dest)
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR)
    return dest


def _stage(tmp_path: Path, rel: str, content: str) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    subprocess.run(["git", "add", rel], cwd=tmp_path, check=True)


def _run(tmp_path: Path, hook: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    import os

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(hook)], cwd=tmp_path, capture_output=True, text=True, env=env
    )


def test_inline_noncompliant_warns_but_does_not_block(tmp_path):
    hook = _init_repo(tmp_path)
    _stage(tmp_path, "briefs/_tasks/CODE_1_PENDING.md", NONCOMPLIANT_INLINE)
    r = _run(tmp_path, hook)
    assert r.returncode == 0, f"inline dispatch must NOT block (warn-only): {r.stderr}"
    assert "WARN [brief-sop-check]" in r.stderr
    assert "Harness V2 essentials missing" in r.stderr
    assert "CODE_1_PENDING.md" in r.stderr


def test_inline_compliant_is_clean(tmp_path):
    hook = _init_repo(tmp_path)
    _stage(tmp_path, "briefs/_tasks/CODE_1_PENDING.md", COMPLIANT_INLINE)
    r = _run(tmp_path, hook)
    assert r.returncode == 0
    assert "Harness V2 essentials missing" not in r.stderr


def test_inline_hard_block_mode_blocks(tmp_path):
    hook = _init_repo(tmp_path)
    _stage(tmp_path, "briefs/_tasks/CODE_1_PENDING.md", NONCOMPLIANT_INLINE)
    r = _run(tmp_path, hook, {"BAKER_BRIEF_SOP_INLINE_HARD_BLOCK": "1"})
    assert r.returncode == 1, "hard-block mode must block a non-compliant inline dispatch"
    assert "BLOCKED" in r.stderr


def test_inline_na_escape_hatch(tmp_path):
    hook = _init_repo(tmp_path)
    _stage(tmp_path, "briefs/_tasks/CODE_1_PENDING.md", NA_ESCAPE_INLINE)
    r = _run(tmp_path, hook, {"BAKER_BRIEF_SOP_INLINE_HARD_BLOCK": "1"})
    assert r.returncode == 0
    assert "Harness V2 essentials missing" not in r.stderr


def test_state_flip_complete_is_not_checked(tmp_path):
    # CODE_1_COMPLETE is a state-flip, not a fresh dispatch — must be excluded.
    hook = _init_repo(tmp_path)
    _stage(tmp_path, "briefs/_tasks/CODE_1_COMPLETE.md", NONCOMPLIANT_INLINE)
    r = _run(tmp_path, hook, {"BAKER_BRIEF_SOP_INLINE_HARD_BLOCK": "1"})
    assert r.returncode == 0, "state-flip file must not be checked"
    assert "WARN [brief-sop-check]" not in r.stderr


def test_formal_brief_hardblock_still_fires(tmp_path):
    # Regression: the inline change must not weaken the formal-brief hard block.
    hook = _init_repo(tmp_path)
    _stage(tmp_path, "briefs/BRIEF_SYNTHETIC_BAD.md", BAD_FORMAL_BRIEF)
    r = _run(tmp_path, hook)
    assert r.returncode == 1, "formal brief missing 3+ SOP headers must still hard-block"
    assert "BLOCKED (brief-sop-check)" in r.stderr
