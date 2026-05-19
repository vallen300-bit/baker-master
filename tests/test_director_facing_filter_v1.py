"""Pytest harness for director-facing-filter-v1.

Each fixture in tests/fixtures/director-facing-filter/fixtures/*.json declares:
  - hook: which script under tests/fixtures/director-facing-filter/hooks/ to run
  - mode (optional): value written to ~/.claude/state/brisen-filter-mode before run
  - user_message (optional): UserPromptSubmit payload field
  - transcript (optional): list of dicts; serialized to JSONL transcript file
  - stop_hook_active (optional): if true, set in payload to test reentrancy guard
  - authority_profiles (optional): yaml dict written to baker-vault profiles path
  - standing_rules_pack (optional): text written to baker-vault standing-rules-pack.md
  - synthesis_markers_pack (optional): text written to ~/.claude/hooks/packs/synthesis-markers.txt
  - expected: { exit_code, stdout_contains, stdout_not_contains, state_file_equals }

Hooks are invoked with HOME=<tmp_path> so all $HOME-rooted reads/writes are sandboxed.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest

try:
    import yaml
except ImportError:
    yaml = None

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "director-facing-filter"
FIXTURES_DIR = FIXTURE_ROOT / "fixtures"
HOOKS_DIR = FIXTURE_ROOT / "hooks"


def _write_transcript(tmp_path: pathlib.Path, entries: list) -> pathlib.Path:
    path = tmp_path / "transcript.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return path


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


@pytest.mark.parametrize("fixture_path", sorted(FIXTURES_DIR.glob("*.json")))
def test_fixture(fixture_path, tmp_path):
    """Run one hook against one fixture; assert expected output + side effects."""
    fx = json.loads(fixture_path.read_text(encoding="utf-8"))
    _prepare_home(tmp_path, fx)
    payload = _build_payload(tmp_path, fx)

    hook_path = HOOKS_DIR / fx["hook"]
    assert hook_path.exists(), f"hook missing: {hook_path}"

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    # Overriding HOME breaks python's user-site lookup. Pin the real site-packages
    # path so hooks that `import yaml` still work under the sandboxed HOME.
    if yaml is not None:
        site = str(pathlib.Path(yaml.__file__).resolve().parent.parent)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = site if not existing else f"{site}{os.pathsep}{existing}"

    result = subprocess.run(
        ["bash", str(hook_path)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
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
