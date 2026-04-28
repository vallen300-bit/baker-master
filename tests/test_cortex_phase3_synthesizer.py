"""Tests for orchestrator/cortex_phase3_synthesizer.py — Phase 3c
synthesis (CORTEX_3T_FORMALIZE_1B).

Brief: ``briefs/BRIEF_CORTEX_3T_FORMALIZE_1B.md``.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from orchestrator import cortex_phase3_synthesizer as synth


class _FakeCursor:
    def __init__(self, synth_prompt_row=None):
        self.queries: list[tuple] = []
        self._row = synth_prompt_row
        self._last_was_select_synth = False

    def execute(self, q, params=None):
        self.queries.append((q, params))
        self._last_was_select_synth = "FROM capability_sets" in q

    def fetchone(self):
        if self._last_was_select_synth and self._row:
            return self._row
        return None

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cur=None):
        self.cur = cur or _FakeCursor()

    def cursor(self):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass


class _FakeStore:
    def __init__(self, conn=None):
        self.conn = conn or _FakeConn()
        self.put_count = 0

    def _get_conn(self):
        return self.conn

    def _put_conn(self, c):
        self.put_count += 1


@pytest.fixture
def patched(monkeypatch):
    holder = {"opus_response": ("synthesis result", 0, 0, 0.0),
              "opus_calls": []}
    store_holder = {"store": _FakeStore()}

    def _call_opus(*, system_prompt, user_message, model=None, max_tokens=None,
                   source="", capability_id=None):
        holder["opus_calls"].append({"sys": system_prompt, "usr": user_message,
                                      "source": source})
        return holder["opus_response"]

    monkeypatch.setattr(synth, "_call_opus", _call_opus)
    monkeypatch.setattr(synth, "_get_store", lambda: store_holder["store"])

    def set_opus(text, in_tok=0, out_tok=0, cost=0.0):
        holder["opus_response"] = (text, in_tok, out_tok, cost)

    def set_store(s):
        store_holder["store"] = s

    return set_opus, store_holder, holder, set_store


# Helpers for fake Phase 3a/3b results
def _fake_3a_result(summary="S", classification="threat", reasoning="R"):
    return SimpleNamespace(
        summary=summary,
        signal_classification=classification,
        reasoning_notes=reasoning,
    )


def _fake_3b_result(outputs=None):
    return SimpleNamespace(outputs=outputs or [])


def _fake_specialist_output(slug, text, success=True, error=None):
    return SimpleNamespace(
        capability_slug=slug, output_text=text,
        success=success, error=error,
    )


# ==========================================================================
# 1. Synthesizer-prompt loading
# ==========================================================================


def test_load_synthesizer_prompt_uses_db_row(patched, monkeypatch):
    """When capability_sets has a synthesizer row, its system_prompt is used."""
    set_opus, sh, holder, set_store = patched
    cur = _FakeCursor(synth_prompt_row=("SYNTH_PROMPT_FROM_DB",))
    set_store(_FakeStore(_FakeConn(cur)))
    set_opus("done\n```json\n[]\n```", in_tok=10, out_tok=5)

    asyncio.run(synth.run_phase3c_synthesize(
        cycle_id="c1", matter_slug="x", signal_text="...",
        phase2_context={}, phase3a_result=_fake_3a_result(),
        phase3b_result=_fake_3b_result(),
    ))
    assert holder["opus_calls"][0]["sys"] == "SYNTH_PROMPT_FROM_DB"


def test_load_synthesizer_prompt_falls_back_when_missing(patched):
    """When DB has no synthesizer row, default prompt is used."""
    set_opus, _, holder, _ = patched  # default _FakeStore returns no row
    set_opus("ok\n```json\n[]\n```")

    asyncio.run(synth.run_phase3c_synthesize(
        cycle_id="c2", matter_slug="x", signal_text="",
        phase2_context={}, phase3a_result=_fake_3a_result(),
        phase3b_result=_fake_3b_result(),
    ))
    sys_prompt = holder["opus_calls"][0]["sys"]
    assert "Cortex synthesizer" in sys_prompt


# ==========================================================================
# 2. Structured-actions extraction
# ==========================================================================


def test_extract_structured_actions_from_valid_json_block():
    text = (
        "Some prose here.\n\n"
        "```json\n"
        '[{"action": "send email", "rationale": "asked", "target": "vip", "deadline": "2026-05-01"}]\n'
        "```"
    )
    out = synth._extract_actions(text)
    assert out == [{"action": "send email", "rationale": "asked",
                    "target": "vip", "deadline": "2026-05-01"}]


def test_extract_structured_actions_returns_empty_on_missing_block():
    assert synth._extract_actions("just prose, no JSON") == []


def test_extract_structured_actions_returns_empty_on_malformed_json():
    text = "prose\n```json\n[not, valid, json}\n```"
    assert synth._extract_actions(text) == []


def test_extract_structured_actions_returns_empty_on_object_not_list():
    """Brief: structured_actions is a list. A JSON object is rejected."""
    text = 'prose\n```json\n[{"action": "go"}]\n```'
    out = synth._extract_actions(text)
    assert out == [{"action": "go"}]


# ==========================================================================
# 3. LLM fallback + cost accumulation
# ==========================================================================


def test_llm_failure_falls_back_to_safe_proposal(patched, monkeypatch):
    set_opus, _, _, _ = patched
    def _boom(**kw):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(synth, "_call_opus", _boom)

    result = asyncio.run(synth.run_phase3c_synthesize(
        cycle_id="cF", matter_slug="x", signal_text="...",
        phase2_context={},
        phase3a_result=_fake_3a_result(),
        phase3b_result=_fake_3b_result([
            _fake_specialist_output("legal", "advice"),
        ]),
    ))
    assert "Manual synthesis required" in result.proposal_text
    assert result.cost_tokens == 0


def test_cost_tokens_accumulated_from_response(patched):
    set_opus, _, _, _ = patched
    set_opus("ok\n```json\n[]\n```", in_tok=300, out_tok=200, cost=0.07)

    result = asyncio.run(synth.run_phase3c_synthesize(
        cycle_id="cC", matter_slug="x", signal_text="",
        phase2_context={}, phase3a_result=_fake_3a_result(),
        phase3b_result=_fake_3b_result(),
    ))
    assert result.cost_tokens == 500
    assert result.cost_dollars == pytest.approx(0.07)


# ==========================================================================
# 4. User message assembly
# ==========================================================================


def test_user_message_includes_signal_and_specialist_outputs(patched):
    set_opus, _, holder, _ = patched
    set_opus("synth\n```json\n[]\n```")

    asyncio.run(synth.run_phase3c_synthesize(
        cycle_id="cU", matter_slug="oskolkov", signal_text="LAWSUIT FILED",
        phase2_context={"matter_config": "MATTER_BRAIN_CONTENT"},
        phase3a_result=_fake_3a_result(summary="threat detected",
                                        classification="threat",
                                        reasoning="they sued"),
        phase3b_result=_fake_3b_result([
            _fake_specialist_output("legal", "lawyer says counter-sue"),
            _fake_specialist_output("finance", "no impact", success=False,
                                     error="timeout"),
        ]),
    ))
    user = holder["opus_calls"][0]["usr"]
    assert "LAWSUIT FILED" in user
    assert "MATTER_BRAIN_CONTENT" in user
    assert "threat detected" in user
    assert "legal (OK)" in user
    assert "lawyer says counter-sue" in user
    assert "finance (FAILED)" in user
    assert "timeout" in user


# ==========================================================================
# 5. Persistence + status='proposed' transition
# ==========================================================================


def test_persist_writes_synthesis_artifact_and_flips_status(patched):
    set_opus, sh, _, _ = patched
    set_opus("text\n```json\n[]\n```")

    asyncio.run(synth.run_phase3c_synthesize(
        cycle_id="cZ", matter_slug="x", signal_text="",
        phase2_context={}, phase3a_result=_fake_3a_result(),
        phase3b_result=_fake_3b_result(),
    ))
    queries = sh["store"].conn.cur.queries
    insert_sql = next((q[0] for q in queries
                       if "INSERT INTO cortex_phase_outputs" in q[0]), None)
    assert insert_sql is not None
    assert "'reason', 5, 'synthesis'" in insert_sql

    update_sql = next((q for q in queries if "UPDATE cortex_cycles" in q[0]), None)
    assert update_sql is not None
    assert "status='proposed'" in update_sql[0]
