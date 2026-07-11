"""Tests for Stop hooks: recommendation-check + fail-loud-check.

Brief: STOP_HOOKS_RECOMMENDATION_AND_FAIL_LOUD_1.

Hooks live at:
  - tests/fixtures/recommendation-check.sh (canonical)
  - tests/fixtures/fail-loud-check.sh      (canonical)

Deployed user-global at ~/.claude/hooks/<name>.sh by Director pre-merge per
brief Sequencing step 8. Drift detection at the bottom of this file.

Each hook reads a stop-event JSON envelope from stdin
({"transcript_path": "...", ...}), walks the JSONL transcript backwards to
find the last `type: "assistant"` turn, applies a regex check on the joined
text content, and emits {"hookSpecificOutput": {"hookEventName": "Stop",
"additionalContext": "..."}} when a slip is detected. Silent + exit 0 on the
clean path.

Coverage (per brief §AC):
  A1/A4 — fixture exists, exec bit set, syntax-clean.
  A2 — recommendation-check warns when assistant text has question + no Recommendation.
  A3 — recommendation-check silent when Recommendation: line present.
  A5 — fail-loud warns when "completed" claim has no verification phrase.
  A6 — fail-loud silent when verification phrase present.
  A8 — drift-detection: deployed user-global matches the repo fixture (skipped on CI).
  A8b — drift-detection: repo fixture matches the baker-vault canonical-of-record
        (Option B, lead #8942; skipped when the vault path is absent, e.g. CI).

Plus defensive cases:
  - Both hooks silent when transcript path is missing / malformed.
  - Both hooks silent on assistant message with empty content.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REC_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "recommendation-check.sh"
FAIL_LOUD_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "fail-loud-check.sh"
USER_GLOBAL_REC = Path.home() / ".claude" / "hooks" / "recommendation-check.sh"
USER_GLOBAL_FAIL_LOUD = Path.home() / ".claude" / "hooks" / "fail-loud-check.sh"

# Option B (lead #8942): recommendation-check.sh is canonical-of-record in
# baker-vault at _ops/hooks/, matching the researcher-cage symlink convention.
# The ~/.claude/hooks copy is a symlink to this path. This fixture stays the
# hermetic test-execution source; the drift-check below keeps it byte-identical
# to the vault canonical. Path is resolved via BAKER_VAULT_PATH when set, else
# the conventional shared checkout — and the check SKIPS when absent (CI stays
# hermetic; vault is never wired into CI).
VAULT_REC = (
    Path(os.environ["BAKER_VAULT_PATH"]) if os.environ.get("BAKER_VAULT_PATH")
    else Path.home() / "baker-vault"
) / "_ops" / "hooks" / "recommendation-check.sh"


def _write_transcript(tmp_path: Path, assistant_text: str) -> Path:
    """Write a minimal Claude transcript JSONL with a single assistant turn."""
    path = tmp_path / "transcript.jsonl"
    turns = [
        {"type": "user", "message": {"content": "irrelevant prior turn"}},
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": assistant_text}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(t) for t in turns) + "\n")
    return path


def _run_hook(fixture: Path, transcript_path: Path) -> subprocess.CompletedProcess:
    payload = json.dumps({
        "hook_event_name": "Stop",
        "session_id": "test-session",
        "transcript_path": str(transcript_path),
        "cwd": str(transcript_path.parent),
    })
    # Hermetic: strip BAKER_ROLE so these Director-facing "should fire" cases are
    # deterministic regardless of the runner's shell. A b-code shell exports
    # BAKER_ROLE (e.g. "B4"), which the recommendation-check role exemption would
    # otherwise honour and silence the hook — a false negative that only shows up
    # off-CI. Role-exemption behaviour is covered explicitly below via
    # _run_hook_with_env.
    env = {k: v for k, v in os.environ.items() if k != "BAKER_ROLE"}
    return subprocess.run(
        ["bash", str(fixture)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=8,
        env=env,
    )


def _additional_context(stdout: str) -> str | None:
    """Parse the hook's stdout JSON envelope, return the warning text or None.

    Schema-tolerant: the hooks were revised 2026-05-12 to emit the Stop-hook
    block form ``{"decision":"block","reason":...}`` (the ``hookSpecificOutput``
    /``additionalContext`` field is not supported on Stop hooks). Fall back to
    the legacy shape so older fixtures still parse.
    """
    out = stdout.strip()
    if not out:
        return None
    payload = json.loads(out)
    if "reason" in payload:
        return payload["reason"]
    return payload.get("hookSpecificOutput", {}).get("additionalContext")


# ---------------------------------------------------------------------------
# A1 / A4 — fixture exists, exec bit set, syntax-clean
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture", [REC_FIXTURE, FAIL_LOUD_FIXTURE], ids=["recommendation", "fail-loud"])
def test_fixture_exists_executable_and_syntax_clean(fixture: Path) -> None:
    assert fixture.is_file(), f"fixture missing: {fixture}"
    mode = fixture.stat().st_mode
    assert mode & stat.S_IXUSR, f"exec bit not set on {fixture}"
    syntax = subprocess.run(["bash", "-n", str(fixture)], capture_output=True, text=True)
    assert syntax.returncode == 0, f"syntax error in {fixture}: {syntax.stderr}"


# ---------------------------------------------------------------------------
# A2 — recommendation-check warns on slip case
# ---------------------------------------------------------------------------

def test_recommendation_check_warns_on_question_without_recommendation(tmp_path):
    """Question + no Recommendation → warning emitted."""
    transcript = _write_transcript(
        tmp_path,
        "Should we ship now or wait? Both have tradeoffs.",
    )
    result = _run_hook(REC_FIXTURE, transcript)
    assert result.returncode == 0, result.stderr
    ctx = _additional_context(result.stdout)
    assert ctx is not None, f"expected warning, got silent: {result.stdout!r}"
    assert "Recommendation" in ctx
    assert "HARD RULE 2" in ctx


def test_recommendation_check_warns_on_numbered_options_without_recommendation(tmp_path):
    """Numbered list + no Recommendation → warning emitted."""
    transcript = _write_transcript(
        tmp_path,
        "Three paths forward.\n\n1. Patch in place\n2. Rewrite\n3. Defer\n\nLet me know.",
    )
    result = _run_hook(REC_FIXTURE, transcript)
    assert result.returncode == 0, result.stderr
    ctx = _additional_context(result.stdout)
    assert ctx is not None, f"expected warning, got silent: {result.stdout!r}"
    assert "Recommendation" in ctx


# ---------------------------------------------------------------------------
# A3 — recommendation-check silent when Recommendation: line present
# ---------------------------------------------------------------------------

def test_recommendation_check_silent_with_recommendation_line(tmp_path):
    """Question + explicit Recommendation: → silent no-op."""
    transcript = _write_transcript(
        tmp_path,
        "Should we ship now or wait?\n\n**Recommendation:** ship — the risk is bounded.",
    )
    result = _run_hook(REC_FIXTURE, transcript)
    assert result.returncode == 0, result.stderr
    assert _additional_context(result.stdout) is None, (
        f"expected silent, got: {result.stdout!r}"
    )


def test_recommendation_check_silent_on_no_question_no_options(tmp_path):
    """Plain status update with no question / list / options → silent."""
    transcript = _write_transcript(tmp_path, "Branch cut, hooks scaffolded.")
    result = _run_hook(REC_FIXTURE, transcript)
    assert result.returncode == 0, result.stderr
    assert _additional_context(result.stdout) is None


# ---------------------------------------------------------------------------
# A5 — fail-loud warns on slip case
# ---------------------------------------------------------------------------

def test_fail_loud_warns_on_completed_without_verification(tmp_path):
    """\"Completed\" claim with no verification phrase → warning emitted."""
    transcript = _write_transcript(
        tmp_path,
        "Completed the migration. All tests pass.",
    )
    result = _run_hook(FAIL_LOUD_FIXTURE, transcript)
    assert result.returncode == 0, result.stderr
    ctx = _additional_context(result.stdout)
    assert ctx is not None, f"expected warning, got silent: {result.stdout!r}"
    assert "Fail-loud" in ctx


def test_fail_loud_warns_on_shipped_without_verification(tmp_path):
    transcript = _write_transcript(tmp_path, "Shipped — should be fine.")
    result = _run_hook(FAIL_LOUD_FIXTURE, transcript)
    assert result.returncode == 0, result.stderr
    ctx = _additional_context(result.stdout)
    assert ctx is not None


# ---------------------------------------------------------------------------
# A6 — fail-loud silent when verification phrase present
# ---------------------------------------------------------------------------

def test_fail_loud_silent_with_verification_phrase(tmp_path):
    """\"Completed\" + verification phrase (`verified`) → silent."""
    transcript = _write_transcript(
        tmp_path,
        "Completed. 12 passed, 0 skipped — verified golden path + 3 edge cases.",
    )
    result = _run_hook(FAIL_LOUD_FIXTURE, transcript)
    assert result.returncode == 0, result.stderr
    assert _additional_context(result.stdout) is None, (
        f"expected silent, got: {result.stdout!r}"
    )


def test_fail_loud_silent_with_literal_pytest_phrase(tmp_path):
    """\"Tests pass\" + 'literal pytest output' → silent."""
    transcript = _write_transcript(
        tmp_path,
        "Tests pass. Literal pytest output: 8 passed in 0.42s.",
    )
    result = _run_hook(FAIL_LOUD_FIXTURE, transcript)
    assert result.returncode == 0, result.stderr
    assert _additional_context(result.stdout) is None


def test_fail_loud_silent_when_no_completion_claim(tmp_path):
    """No claim words → silent (nothing to verify)."""
    transcript = _write_transcript(tmp_path, "Investigating root cause.")
    result = _run_hook(FAIL_LOUD_FIXTURE, transcript)
    assert result.returncode == 0, result.stderr
    assert _additional_context(result.stdout) is None


# ---------------------------------------------------------------------------
# Defensive: missing / malformed transcript path → silent + exit 0
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture", [REC_FIXTURE, FAIL_LOUD_FIXTURE], ids=["recommendation", "fail-loud"])
def test_hook_silent_when_transcript_path_missing(fixture: Path, tmp_path):
    payload = json.dumps({"hook_event_name": "Stop", "session_id": "x"})
    result = subprocess.run(
        ["bash", str(fixture)],
        input=payload, capture_output=True, text=True, timeout=8,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


@pytest.mark.parametrize("fixture", [REC_FIXTURE, FAIL_LOUD_FIXTURE], ids=["recommendation", "fail-loud"])
def test_hook_silent_when_transcript_file_missing(fixture: Path, tmp_path):
    payload = json.dumps({
        "hook_event_name": "Stop",
        "transcript_path": str(tmp_path / "does-not-exist.jsonl"),
    })
    result = subprocess.run(
        ["bash", str(fixture)],
        input=payload, capture_output=True, text=True, timeout=8,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


@pytest.mark.parametrize("fixture", [REC_FIXTURE, FAIL_LOUD_FIXTURE], ids=["recommendation", "fail-loud"])
def test_hook_silent_when_input_is_garbage(fixture: Path):
    result = subprocess.run(
        ["bash", str(fixture)],
        input="not-json-at-all", capture_output=True, text=True, timeout=8,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Role exemption — recommendation requirement is Director-facing only.
# B-codes (b1..b5), codex, codex-arch, architect are NOT Director-facing
# (HARD RULE, Director 2026-05-29). The exemption must resolve the role
# case-insensitively: Cowork/Terminal profiles export BAKER_ROLE uppercase
# (e.g. "B4"), and because a set-but-unmatched value skips the cwd fallback,
# an uppercase role would otherwise fire the hook. Anchor: b3 #8286 —
# uppercase-BAKER_ROLE bug misfired on a b4 reply.
# ---------------------------------------------------------------------------

def _run_hook_with_env(fixture: Path, transcript_path: Path, extra_env: dict) -> subprocess.CompletedProcess:
    payload = json.dumps({
        "hook_event_name": "Stop",
        "session_id": "test-session",
        "transcript_path": str(transcript_path),
        "cwd": str(transcript_path.parent),  # tmp_path — does NOT match bm-b* pattern
    })
    env = {**os.environ, **extra_env}
    return subprocess.run(
        ["bash", str(fixture)],
        input=payload, capture_output=True, text=True, timeout=8, env=env,
    )


@pytest.mark.parametrize("role", ["B4", "B1", "B5", "CODEX", "CODEX-ARCH", "Architect", "b4", "codex"])
def test_recommendation_check_exempts_bcode_role_case_insensitive(tmp_path, role):
    """Non-Director-facing role (any case) → silent even with question + no Recommendation."""
    transcript = _write_transcript(
        tmp_path,
        "Should we ship now or wait? Both have tradeoffs.",
    )
    result = _run_hook_with_env(REC_FIXTURE, transcript, {"BAKER_ROLE": role})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", (
        f"role {role!r} should be exempt but hook fired: {result.stdout!r}"
    )


def test_recommendation_check_still_fires_for_director_facing_role(tmp_path):
    """A Director-facing role (e.g. lead) is NOT exempt — hook still fires."""
    transcript = _write_transcript(
        tmp_path,
        "Should we ship now or wait? Both have tradeoffs.",
    )
    result = _run_hook_with_env(REC_FIXTURE, transcript, {"BAKER_ROLE": "lead"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != "", "Director-facing role should still fire the hook"


# ---------------------------------------------------------------------------
# A8 — drift detection: deployed user-global hooks match repo fixtures
# Skipped on CI / boxes without ~/.claude/hooks/<name>.sh deployed.
# ---------------------------------------------------------------------------

def test_user_global_recommendation_matches_repo():
    if not USER_GLOBAL_REC.exists():
        pytest.skip(
            f"user-global hook not deployed at {USER_GLOBAL_REC} "
            "(expected on CI; Director ratifies cp pre-merge)"
        )
    assert REC_FIXTURE.read_bytes() == USER_GLOBAL_REC.read_bytes(), (
        "drift detected: ~/.claude/hooks/recommendation-check.sh differs from "
        "tests/fixtures/recommendation-check.sh — re-run "
        "`cp tests/fixtures/recommendation-check.sh ~/.claude/hooks/recommendation-check.sh`"
    )


def test_user_global_fail_loud_matches_repo():
    if not USER_GLOBAL_FAIL_LOUD.exists():
        pytest.skip(
            f"user-global hook not deployed at {USER_GLOBAL_FAIL_LOUD} "
            "(expected on CI; Director ratifies cp pre-merge)"
        )
    assert FAIL_LOUD_FIXTURE.read_bytes() == USER_GLOBAL_FAIL_LOUD.read_bytes(), (
        "drift detected: ~/.claude/hooks/fail-loud-check.sh differs from "
        "tests/fixtures/fail-loud-check.sh — re-run "
        "`cp tests/fixtures/fail-loud-check.sh ~/.claude/hooks/fail-loud-check.sh`"
    )


# ---------------------------------------------------------------------------
# A8b — drift detection vs the baker-vault canonical-of-record (Option B, #8942)
# recommendation-check.sh is authored in baker-vault _ops/hooks/; the fixture
# here must stay byte-identical to it. Skipped when the vault path is absent
# (CI / boxes without a baker-vault checkout) — vault is never wired into CI.
# ---------------------------------------------------------------------------

def test_vault_canonical_recommendation_matches_repo():
    if not VAULT_REC.exists():
        pytest.skip(
            f"baker-vault canonical not present at {VAULT_REC} "
            "(expected on CI; set BAKER_VAULT_PATH on boxes with a checkout)"
        )
    assert REC_FIXTURE.read_bytes() == VAULT_REC.read_bytes(), (
        "drift detected: tests/fixtures/recommendation-check.sh differs from the "
        f"baker-vault canonical-of-record at {VAULT_REC}. The vault copy is "
        "canonical (Option B, lead #8942) — reconcile the fixture to it "
        "(both must stay byte-identical so the deployed symlink matches)."
    )
