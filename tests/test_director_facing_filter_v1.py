"""Pytest harness for director-facing-filter v1 (Phase 1) + v1.1 (Phase 2).

Each fixture in tests/fixtures/director-facing-filter/fixtures/*.json declares:
  - hook: which script under tests/fixtures/director-facing-filter/hooks/ to run
  - mode (optional): value written to ~/.claude/state/brisen-filter-mode before run
  - user_message (optional): UserPromptSubmit payload field
  - transcript (optional): list of dicts; serialized to JSONL transcript file
  - stop_hook_active (optional): if true, set in payload to test reentrancy guard
  - authority_profiles (optional): yaml dict written to baker-vault profiles path
  - standing_rules_pack (optional): text written to baker-vault standing-rules-pack.md
  - synthesis_markers_pack (optional): text written to ~/.claude/hooks/packs/synthesis-markers.txt
  - mock (optional, Phase 2): {behavior, verdict_json, op_fail} controlling mocked
    anthropic SDK + op CLI shim staged under tmp_path. Stages real call_validator.py
    + validator skill files automatically when hook is a Phase 2 hook.
  - pending_annotations (optional, Phase 2): list seeded to
    ~/.claude/state/pending-annotations.json before run
  - feasibility_tags (optional, Phase 2): dict seeded to
    ~/.claude/state/feasibility-tags.json (mtime set fresh) before run
  - expected: {
        exit_code, stdout_contains, stdout_not_contains, state_file_equals,
        pending_annotations_filter (Phase 2 — substring match in pending file),
        pending_annotations_cleared (Phase 2 — bool; file == "[]" after run),
    }

Hooks are invoked with HOME=<tmp_path> so all $HOME-rooted reads/writes are sandboxed.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import time

import pytest

try:
    import yaml
except ImportError:
    yaml = None

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "director-facing-filter"
FIXTURES_DIR = FIXTURE_ROOT / "fixtures"
HOOKS_DIR = FIXTURE_ROOT / "hooks"
LIB_DIR = FIXTURE_ROOT / "lib"
LIB_MOCK_DIR = FIXTURE_ROOT / "lib_mock"
LIB_MOCK_NO_SDK_DIR = FIXTURE_ROOT / "lib_mock_no_sdk"
SKILLS_SRC = FIXTURE_ROOT / "skills"

PHASE_2_HOOKS = {
    "stakeholder-authority-trigger.sh",
    "contract-gate-trigger.sh",
    "annotate-pending-checker.sh",
}


def _write_transcript(tmp_path: pathlib.Path, entries: list) -> pathlib.Path:
    path = tmp_path / "transcript.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return path


def _stage_phase2_support(tmp_path: pathlib.Path) -> None:
    """Lay out hook lib + skill files under tmp_path for Phase 2 hooks."""
    hooks_lib = tmp_path / ".claude" / "hooks" / "lib"
    hooks_lib.mkdir(parents=True, exist_ok=True)
    shutil.copy(LIB_DIR / "call_validator.py", hooks_lib / "call_validator.py")
    (hooks_lib / "__init__.py").write_text("")

    skills_dir = tmp_path / ".claude" / "skills"
    for skill_name in (
        "director-facing-filter-stakeholder-validator",
        "director-facing-filter-contract-validator",
    ):
        dest = skills_dir / skill_name
        dest.mkdir(parents=True, exist_ok=True)
        src = SKILLS_SRC / skill_name / "SKILL.md"
        if src.exists():
            shutil.copy(src, dest / "SKILL.md")


def _stage_op_shim(tmp_path: pathlib.Path) -> pathlib.Path:
    """Stage a mock `op` CLI binary under tmp_path/.fake-bin/. Returns the bin dir."""
    fake_bin = tmp_path / ".fake-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    op_shim = fake_bin / "op"
    op_shim.write_text(
        '#!/usr/bin/env bash\n'
        'if [ "${MOCK_OP_FAIL:-}" = "1" ]; then\n'
        '    echo "mocked: op CLI failed" >&2\n'
        '    exit 1\n'
        'fi\n'
        'echo "sk-ant-api03-mock-test-key-not-real"\n'
    )
    op_shim.chmod(0o755)
    return fake_bin


def _prepare_home(tmp_path: pathlib.Path, fx: dict) -> None:
    """Lay out tmp_path so it can serve as $HOME for hook subprocess."""
    state_dir = tmp_path / ".claude" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    if "mode" in fx:
        (state_dir / "brisen-filter-mode").write_text(fx["mode"])

    if "authority_profiles" in fx:
        if yaml is None:
            pytest.skip("PyYAML not installed; cannot stage authority-profiles fixture")
        prof_dir = tmp_path / "baker-vault" / "_ops" / "people"
        prof_dir.mkdir(parents=True, exist_ok=True)
        (prof_dir / "authority-profiles.yml").write_text(
            yaml.safe_dump({"authority_profiles": fx["authority_profiles"]}, allow_unicode=True),
            encoding="utf-8",
        )

    if "standing_rules_pack" in fx:
        rules_dir = tmp_path / "baker-vault" / "_ops" / "processes"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "standing-rules-pack.md").write_text(fx["standing_rules_pack"], encoding="utf-8")

    if "synthesis_markers_pack" in fx:
        packs_dir = tmp_path / ".claude" / "hooks" / "packs"
        packs_dir.mkdir(parents=True, exist_ok=True)
        (packs_dir / "synthesis-markers.txt").write_text(fx["synthesis_markers_pack"], encoding="utf-8")

    hook_name = fx.get("hook", "")
    if hook_name in PHASE_2_HOOKS:
        _stage_phase2_support(tmp_path)

    if "pending_annotations" in fx:
        (state_dir / "pending-annotations.json").write_text(
            json.dumps(fx["pending_annotations"]), encoding="utf-8"
        )

    if "feasibility_tags" in fx:
        ev_file = state_dir / "feasibility-tags.json"
        ev_file.write_text(json.dumps(fx["feasibility_tags"]), encoding="utf-8")
        # If fixture declares an explicit mtime-offset (seconds in past), use it;
        # else leave default (now) so freshness check passes.
        offset = fx.get("feasibility_tags_age_seconds", 0)
        if offset:
            stale = time.time() - offset
            os.utime(ev_file, (stale, stale))


def _build_payload(tmp_path: pathlib.Path, fx: dict) -> str:
    payload: dict = {}
    if "user_message" in fx:
        payload["user_message"] = fx["user_message"]
    if "transcript" in fx:
        tr = _write_transcript(tmp_path, fx["transcript"])
        payload["transcript_path"] = str(tr)
    if fx.get("stop_hook_active"):
        payload["stop_hook_active"] = True
    return json.dumps(payload)


def _build_env(tmp_path: pathlib.Path, fx: dict) -> dict:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    # Overriding HOME breaks python's user-site lookup. Pin real yaml site-packages
    # so hooks that `import yaml` still work under sandboxed HOME.
    if yaml is not None:
        site = str(pathlib.Path(yaml.__file__).resolve().parent.parent)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = site if not existing else f"{site}{os.pathsep}{existing}"

    hook_name = fx.get("hook", "")
    if hook_name in {"stakeholder-authority-trigger.sh", "contract-gate-trigger.sh"}:
        # Stage op shim + mock anthropic. Always — even when no `mock` block —
        # so tests cannot accidentally leak to the real Anthropic API.
        fake_bin = _stage_op_shim(tmp_path)
        env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

        mock = fx.get("mock", {}) or {}
        behavior = mock.get("behavior", "success")
        if behavior == "import_error":
            mock_pylib = LIB_MOCK_NO_SDK_DIR
        else:
            mock_pylib = LIB_MOCK_DIR
        # Prepend mock pylib so `import anthropic` resolves to the mock first.
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{mock_pylib}{os.pathsep}{existing}" if existing else str(mock_pylib)
        )
        env["MOCK_BEHAVIOR"] = behavior
        env["MOCK_VERDICT_JSON"] = mock.get(
            "verdict_json", '{"decision":"pass","reason":"default mock pass"}'
        )
        if mock.get("op_fail"):
            env["MOCK_OP_FAIL"] = "1"
    return env


@pytest.mark.parametrize("fixture_path", sorted(FIXTURES_DIR.glob("*.json")))
def test_fixture(fixture_path, tmp_path):
    """Run one hook against one fixture; assert expected output + side effects."""
    fx = json.loads(fixture_path.read_text(encoding="utf-8"))
    _prepare_home(tmp_path, fx)
    payload = _build_payload(tmp_path, fx)

    hook_path = HOOKS_DIR / fx["hook"]
    assert hook_path.exists(), f"hook missing: {hook_path}"

    env = _build_env(tmp_path, fx)

    result = subprocess.run(
        ["bash", str(hook_path)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )

    exp = fx["expected"]
    assert result.returncode == exp.get("exit_code", 0), (
        f"{fixture_path.name}: exit {result.returncode} != {exp.get('exit_code', 0)}; "
        f"stderr={result.stderr!r} stdout={result.stdout!r}"
    )
    if "stdout_contains" in exp:
        assert exp["stdout_contains"] in result.stdout, (
            f"{fixture_path.name}: stdout missing {exp['stdout_contains']!r}; got {result.stdout!r}"
        )
    if "stdout_not_contains" in exp:
        assert exp["stdout_not_contains"] not in result.stdout, (
            f"{fixture_path.name}: stdout unexpectedly contains {exp['stdout_not_contains']!r}"
        )
    if "state_file_equals" in exp:
        state = (tmp_path / ".claude" / "state" / "brisen-filter-mode").read_text().strip()
        assert state == exp["state_file_equals"], (
            f"{fixture_path.name}: state {state!r} != expected {exp['state_file_equals']!r}"
        )

    if "pending_annotations_filter" in exp:
        pending = tmp_path / ".claude" / "state" / "pending-annotations.json"
        assert pending.exists(), (
            f"{fixture_path.name}: pending-annotations.json missing"
        )
        try:
            entries = json.loads(pending.read_text(encoding="utf-8"))
        except Exception as e:
            pytest.fail(f"{fixture_path.name}: pending-annotations.json unreadable: {e}")
        assert any(
            (isinstance(e, dict) and e.get("filter") == exp["pending_annotations_filter"])
            for e in entries
        ), f"{fixture_path.name}: no entry with filter={exp['pending_annotations_filter']!r}; got {entries!r}"

    if exp.get("pending_annotations_cleared"):
        pending = tmp_path / ".claude" / "state" / "pending-annotations.json"
        assert pending.exists(), (
            f"{fixture_path.name}: pending-annotations.json should exist (cleared = empty list, not absent)"
        )
        content = pending.read_text(encoding="utf-8").strip()
        assert content in ("[]", "[ ]"), (
            f"{fixture_path.name}: pending-annotations.json should be cleared (`[]`); got {content!r}"
        )
