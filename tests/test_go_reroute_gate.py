"""CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1 (E3) — worker-side GO-reroute gate tests.

The lead binding rider (#10036) makes FALSE-POSITIVE tests MANDATORY: a ratify_required
message, a Tier-B/C message, and a genuine Director business question must NEVER be
rerouted. True-positive: a GO/confirm on already-dispatched work IS rerouted to the
sender's superior. Exercises the pure `decide_reroute` plus the CLI + real-registry
`resolve_reports_to`.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE_PATH = REPO_ROOT / "scripts" / "go_reroute_gate.py"

spec = importlib.util.spec_from_file_location("go_reroute_gate", GATE_PATH)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


# --- TRUE POSITIVES: reroute fires --------------------------------------------

@pytest.mark.parametrize("body", [
    "🟢 GO? merge PR #164",
    "Confirm I should start job #9033",
    "await your go on the dispatched brief CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1",
    "permission to proceed on /jobs/412",
    "ok to merge PR #540?",
])
def test_reroute_fires_on_go_about_dispatched_work(body):
    target, reason = gate.decide_reroute("director", body, "lead", disabled=False)
    assert target == "lead"
    assert reason == "reroute_go_on_dispatched_work"


# --- FALSE POSITIVES (MANDATORY): must NOT reroute ----------------------------

def test_ratify_required_not_rerouted():
    target, reason = gate.decide_reroute(
        "director", "ratify_required: approve merge of PR #164", "lead")
    assert target is None
    assert reason == "protected_veto"


def test_tier_b_not_rerouted():
    target, reason = gate.decide_reroute(
        "director", "Tier-B prerogative — confirm the Cortex design change on job #12",
        "lead")
    assert target is None
    assert reason == "protected_veto"


def test_tier_c_not_rerouted():
    target, reason = gate.decide_reroute(
        "director", "Tier C sign-off needed, confirm PR #9", "lead")
    assert target is None
    assert reason == "protected_veto"


@pytest.mark.parametrize("body", [
    "Should we accept AO's €600k offer?",          # money
    "confirm we should sell the Vienna asset (job #12)",  # counterparty/business + confirm + jobref
    "permission to wire the CHF 200k deposit for PR #4",  # money/wire
    "ok to sign the external email to Aukera re dispatch",  # external send / sign
])
def test_business_question_not_rerouted(body):
    target, reason = gate.decide_reroute("director", body, "lead")
    assert target is None
    assert reason == "protected_veto"


def test_bare_go_without_jobref_not_rerouted():
    # Conservative: a GO with no referenced already-dispatched work is NOT rerouted.
    target, reason = gate.decide_reroute("director", "🟢 GO?", "lead")
    assert target is None
    assert reason == "no_jobref"


def test_fyi_with_jobref_but_no_go_not_rerouted():
    target, reason = gate.decide_reroute(
        "director", "Update on job #9033: build done, tests green.", "lead")
    assert target is None
    assert reason == "no_go_pattern"


def test_non_director_recipient_not_rerouted():
    target, reason = gate.decide_reroute("lead", "🟢 GO? merge PR #1", "lead")
    assert target is None
    assert reason == "not_director_recipient"


def test_top_level_sender_not_rerouted():
    # A seat that reports to the Director (lead) has the Director as its legitimate
    # GO channel — nothing to reroute to.
    target, reason = gate.decide_reroute(
        "director", "🟢 GO? merge PR #1", "Director")
    assert target is None
    assert reason == "sender_is_top_level"


def test_kill_switch_disables_gate():
    target, reason = gate.decide_reroute(
        "director", "🟢 GO? merge PR #164", "lead", disabled=True)
    assert target is None
    assert reason == "kill_switch"


# --- registry resolution ------------------------------------------------------

def test_reports_to_resolution_real_registry():
    # b-codes report to lead; lead reports to Director.
    assert gate.resolve_reports_to("b3") == "lead"
    assert gate.resolve_reports_to("lead") == "Director"
    # alias resolution (deputy alias aihead2 -> lead)
    assert gate.resolve_reports_to("aihead2") == "lead"


def test_reports_to_unknown_slug_is_none():
    assert gate.resolve_reports_to("nope-not-a-seat", agents=[]) is None


# --- CLI (stdout contract bus_post.sh depends on) -----------------------------

def _run_cli(recipient, body, sender, env_extra=None):
    import os
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(GATE_PATH), recipient, body, sender],
        capture_output=True, text=True, env=env,
    )


def test_cli_reroutes_prints_superior():
    r = _run_cli("director", "🟢 GO? merge PR #164", "b3")
    assert r.returncode == 0
    assert r.stdout.strip() == "lead"


def test_cli_no_reroute_prints_original_recipient():
    r = _run_cli("director", "Should we accept the €600k offer?", "b3")
    assert r.returncode == 0
    assert r.stdout.strip() == "director"


def test_cli_kill_switch_prints_original():
    r = _run_cli("director", "🟢 GO? merge PR #164", "b3",
                 env_extra={"BAKER_GO_REROUTE_DISABLED": "1"})
    assert r.returncode == 0
    assert r.stdout.strip() == "director"


def test_cli_non_director_passthrough():
    r = _run_cli("lead", "🟢 GO? merge PR #164", "b3")
    assert r.returncode == 0
    assert r.stdout.strip() == "lead"
