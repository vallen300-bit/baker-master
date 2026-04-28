"""Tests for orchestrator/cortex_phase3_reasoner.py — Phase 3a meta-
reasoning + cap-5 enforcement (CORTEX_3T_FORMALIZE_1B).

Brief: ``briefs/BRIEF_CORTEX_3T_FORMALIZE_1B.md``.

Test strategy: captured-SQL stubs + module-level helper monkeypatching
(matches the 1A test-pollution mitigation pattern — patch
``cortex_phase3_reasoner._get_store`` / ``_call_opus`` / etc directly so
attribute pollution from earlier suite imports cannot bite).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from orchestrator import cortex_phase3_reasoner as reasoner


# --------------------------------------------------------------------------
# Captured-SQL stub harness (mirrors test_cortex_runner_phase126 shape)
# --------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, capability_rows: list | None = None):
        self.queries: list[tuple] = []
        self._capability_rows = capability_rows or []
        self._last_select_was_capabilities = False

    def execute(self, q, params=None):
        self.queries.append((q, params))
        self._last_select_was_capabilities = "FROM capability_sets" in q

    def fetchall(self):
        if self._last_select_was_capabilities:
            return list(self._capability_rows)
        return []

    def fetchone(self):
        return None

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cur=None):
        self.cur = cur or _FakeCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _FakeStore:
    def __init__(self, conn=None):
        self.conn = conn or _FakeConn()
        self.put_count = 0

    def _get_conn(self):
        return self.conn

    def _put_conn(self, conn):
        self.put_count += 1


@pytest.fixture
def patch_reasoner(monkeypatch):
    """Returns (set_caps, set_opus, get_store) — wires the reasoner module
    helpers to in-memory stubs."""
    holder = {
        "caps": [],
        "opus_response": ("", 0, 0, 0.0),
        "opus_calls": [],
    }
    store_holder = {"store": _FakeStore()}

    def _capabilities():
        return list(holder["caps"])

    def _call_opus(*, system_prompt, user_message, model=None, max_tokens=None,
                   source="", capability_id=None):
        holder["opus_calls"].append({
            "system_prompt": system_prompt,
            "user_message": user_message,
            "source": source,
        })
        return holder["opus_response"]

    monkeypatch.setattr(reasoner, "_load_active_domain_capabilities", _capabilities)
    monkeypatch.setattr(reasoner, "_call_opus", _call_opus)
    monkeypatch.setattr(reasoner, "_get_store", lambda: store_holder["store"])

    def set_caps(caps):
        holder["caps"] = caps

    def set_opus(text, in_tok=0, out_tok=0, cost=0.0):
        holder["opus_response"] = (text, in_tok, out_tok, cost)

    def get_store():
        return store_holder["store"]

    def opus_calls():
        return holder["opus_calls"]

    return set_caps, set_opus, get_store, opus_calls


# ==========================================================================
# 1. Regex matching
# ==========================================================================


def test_regex_match_picks_capabilities_with_pattern_hit(patch_reasoner):
    set_caps, set_opus, _, _ = patch_reasoner
    set_caps([
        {"slug": "legal", "trigger_patterns": [r"\blawsuit\b", r"\bcontract\b"]},
        {"slug": "finance", "trigger_patterns": [r"\binvoice\b"]},
    ])
    set_opus(json.dumps({"summary": "S", "signal_classification": "threat",
                         "reasoning_notes": "R"}))

    out = asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="c1", matter_slug="oskolkov",
        signal_text="They threatened a lawsuit yesterday",
        phase2_context={"matter_config": ""},
    ))
    assert "legal" in out.capabilities_to_invoke
    assert "finance" not in out.capabilities_to_invoke
    assert out.matched_evidence["legal"]


def test_regex_match_uses_re_ignorecase(patch_reasoner):
    """Regex must match upper-case signal text via re.IGNORECASE flag."""
    set_caps, set_opus, _, _ = patch_reasoner
    set_caps([{"slug": "legal", "trigger_patterns": [r"\blawsuit\b"]}])
    set_opus(json.dumps({"summary": "S", "signal_classification": "threat",
                         "reasoning_notes": "R"}))

    out = asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="c2", matter_slug="oskolkov",
        signal_text="LAWSUIT FILED",
        phase2_context={},
    ))
    assert "legal" in out.capabilities_to_invoke


def test_no_regex_match_returns_empty_pool(patch_reasoner):
    set_caps, set_opus, _, _ = patch_reasoner
    set_caps([{"slug": "legal", "trigger_patterns": [r"\blawsuit\b"]}])
    set_opus(json.dumps({"summary": "S", "signal_classification": "other",
                         "reasoning_notes": "R"}))

    out = asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="c3", matter_slug="x",
        signal_text="completely unrelated text",
        phase2_context={},
    ))
    assert out.capabilities_to_invoke == []


def test_bad_regex_does_not_crash(patch_reasoner):
    """Lesson #1 cousin: malformed pattern logs warning, doesn't break cycle."""
    set_caps, set_opus, _, _ = patch_reasoner
    set_caps([
        {"slug": "broken", "trigger_patterns": [r"["]},  # invalid regex
        {"slug": "ok", "trigger_patterns": [r"\bok\b"]},
    ])
    set_opus(json.dumps({"summary": "S", "signal_classification": "other",
                         "reasoning_notes": "R"}))

    out = asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="c4", matter_slug="x",
        signal_text="this is ok",
        phase2_context={},
    ))
    assert "ok" in out.capabilities_to_invoke
    assert "broken" not in out.capabilities_to_invoke


# ==========================================================================
# 2. Cap-5 enforcement (RA-23 Q4)
# ==========================================================================


def test_cap5_enforced_when_more_than_five_match(patch_reasoner):
    """Hard cap: 8 matching capabilities → only top-5 returned."""
    set_caps, set_opus, _, _ = patch_reasoner
    # Build 8 capabilities all matching a single pattern
    caps = [{"slug": f"cap{i}", "trigger_patterns": [r"\bgo\b"]} for i in range(8)]
    set_caps(caps)
    set_opus(json.dumps({"summary": "S", "signal_classification": "request",
                         "reasoning_notes": "R"}))

    out = asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="c5", matter_slug="x",
        signal_text="please go now",
        phase2_context={},
    ))
    assert len(out.capabilities_to_invoke) == 5


def test_cap5_ranking_prefers_more_hits(patch_reasoner):
    """Heuristic ranking: capabilities with more pattern hits rank higher."""
    set_caps, set_opus, _, _ = patch_reasoner
    set_caps([
        {"slug": "a", "trigger_patterns": [r"\bone\b"]},
        {"slug": "b", "trigger_patterns": [r"\bone\b", r"\btwo\b", r"\bthree\b"]},
        {"slug": "c", "trigger_patterns": [r"\bone\b", r"\btwo\b"]},
        {"slug": "d", "trigger_patterns": [r"\bone\b"]},
        {"slug": "e", "trigger_patterns": [r"\bone\b"]},
        {"slug": "f", "trigger_patterns": [r"\bone\b"]},
    ])
    set_opus(json.dumps({"summary": "S", "signal_classification": "other",
                         "reasoning_notes": "R"}))

    out = asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="c6", matter_slug="x",
        signal_text="one two three",
        phase2_context={},
    ))
    # b has 3 hits, c has 2, a/d/e/f tie at 1 — b + c MUST be in top-5
    assert "b" in out.capabilities_to_invoke
    assert "c" in out.capabilities_to_invoke
    assert len(out.capabilities_to_invoke) == 5


# ==========================================================================
# 3. cortex-config opt-in (games_relevant)
# ==========================================================================


def test_games_relevant_opt_in_adds_game_theory(patch_reasoner):
    """games_relevant: true + negotiation-class signal → game_theory added."""
    set_caps, set_opus, _, _ = patch_reasoner
    set_caps([])  # no domain capability matches
    set_opus(json.dumps({"summary": "S", "signal_classification": "request",
                         "reasoning_notes": "R"}))

    out = asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="c7", matter_slug="oskolkov",
        signal_text="They sent a counter-offer at 10M",
        phase2_context={"matter_config": "games_relevant: true"},
    ))
    assert "game_theory" in out.capabilities_to_invoke


def test_games_relevant_opt_in_skipped_when_no_negotiation_signal(patch_reasoner):
    set_caps, set_opus, _, _ = patch_reasoner
    set_caps([])
    set_opus(json.dumps({"summary": "S", "signal_classification": "status",
                         "reasoning_notes": "R"}))

    out = asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="c8", matter_slug="oskolkov",
        signal_text="just a status update",
        phase2_context={"matter_config": "games_relevant: true"},
    ))
    assert "game_theory" not in out.capabilities_to_invoke


def test_games_relevant_false_does_not_opt_in(patch_reasoner):
    set_caps, set_opus, _, _ = patch_reasoner
    set_caps([])
    set_opus(json.dumps({"summary": "S", "signal_classification": "request",
                         "reasoning_notes": "R"}))

    out = asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="c9", matter_slug="movie",
        signal_text="They sent a counter-offer",
        phase2_context={"matter_config": "games_relevant: false"},
    ))
    assert "game_theory" not in out.capabilities_to_invoke


# ==========================================================================
# 4. LLM fallback + cost accumulation
# ==========================================================================


def test_llm_failure_falls_back_to_heuristic(patch_reasoner, monkeypatch):
    """When _llm_meta_reason raises, fallback emits non-LLM result + 0 cost."""
    set_caps, _, _, _ = patch_reasoner
    set_caps([{"slug": "legal", "trigger_patterns": [r"\blegal\b"]}])

    def _boom(**_kw):
        raise RuntimeError("anthropic dead")
    monkeypatch.setattr(reasoner, "_llm_meta_reason", _boom)

    out = asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="cx", matter_slug="x", signal_text="legal matters",
        phase2_context={},
    ))
    assert "legal" in out.capabilities_to_invoke
    assert out.cost_tokens == 0
    assert out.cost_dollars == 0.0
    assert "fallback" in out.summary.lower() or "fallback" in out.reasoning_notes.lower()


def test_cost_tokens_accumulated_from_llm_response(patch_reasoner):
    set_caps, set_opus, _, _ = patch_reasoner
    set_caps([{"slug": "a", "trigger_patterns": [r"\bx\b"]}])
    set_opus(
        text=json.dumps({"summary": "S", "signal_classification": "other",
                         "reasoning_notes": "R"}),
        in_tok=100, out_tok=50, cost=0.0123,
    )

    out = asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="cy", matter_slug="x", signal_text="x",
        phase2_context={},
    ))
    assert out.cost_tokens == 150
    assert out.cost_dollars == pytest.approx(0.0123)


def test_llm_response_non_json_falls_back_to_text_summary(patch_reasoner):
    set_caps, set_opus, _, _ = patch_reasoner
    set_caps([{"slug": "a", "trigger_patterns": [r"\ba\b"]}])
    set_opus("not json at all", in_tok=10, out_tok=5)

    out = asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="cz", matter_slug="x", signal_text="a thing",
        phase2_context={},
    ))
    # Falls back: summary = first 200 chars of text, classification = 'other'
    assert out.signal_classification == "other"
    assert "not json" in out.summary


# ==========================================================================
# 5. Persistence (SQL-assertion tests, Lesson #42)
# ==========================================================================


def test_persist_writes_meta_reason_artifact(patch_reasoner):
    set_caps, set_opus, get_store, _ = patch_reasoner
    set_caps([])
    set_opus(json.dumps({"summary": "S", "signal_classification": "other",
                         "reasoning_notes": "R"}))

    asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="ck", matter_slug="x", signal_text="",
        phase2_context={},
    ))
    queries = get_store().conn.cur.queries
    insert_sql = next((q[0] for q in queries if "INSERT INTO cortex_phase_outputs" in q[0]),
                      None)
    assert insert_sql is not None
    assert "'reason', 3, 'meta_reason'" in insert_sql


def test_persist_bumps_cycle_cost(patch_reasoner):
    set_caps, set_opus, get_store, _ = patch_reasoner
    set_caps([])
    set_opus(json.dumps({"summary": "", "signal_classification": "other",
                         "reasoning_notes": ""}), in_tok=200, out_tok=100, cost=0.05)

    asyncio.run(reasoner.run_phase3a_meta_reason(
        cycle_id="cM", matter_slug="x", signal_text="",
        phase2_context={},
    ))
    queries = get_store().conn.cur.queries
    update_sql = next((q for q in queries if "UPDATE cortex_cycles" in q[0]), None)
    assert update_sql is not None
    assert "cost_tokens = cost_tokens" in update_sql[0]
    assert update_sql[1] == (300, 0.05, "cM")


def test_no_db_conn_returns_empty_capabilities(monkeypatch):
    """If _get_store().conn is None, capability load returns []."""
    class _NoConnStore:
        def _get_conn(self):
            return None
        def _put_conn(self, c):
            pass
    monkeypatch.setattr(reasoner, "_get_store", lambda: _NoConnStore())
    out = reasoner._load_active_domain_capabilities()
    assert out == []
