"""Tests for orchestrator/cortex_phase4_proposal.py — CORTEX_3T_FORMALIZE_1C.

Coverage: Block Kit shape, per-file Gold checkboxes, structured-actions
rendering, DB persist SQL assertions, DRY_RUN gate, Slack post invocation.

Pattern mirrors tests/test_cortex_runner_phase126.py — fixture-only,
captured-SQL stubs, no live DB / Slack.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from orchestrator import cortex_phase4_proposal as p4


# --------------------------------------------------------------------------
# Captured-SQL stub harness
# --------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self):
        self.queries: list[tuple] = []

    def execute(self, q, params=None):
        self.queries.append((q, params))

    def fetchone(self):
        return None

    def close(self):
        pass


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _FakeStore:
    def __init__(self):
        self.conns: list[_FakeConn] = []

    def _get_conn(self):
        c = _FakeConn()
        self.conns.append(c)
        return c

    def _put_conn(self, c):
        pass


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(p4, "_get_store", lambda: store)
    return store


@pytest.fixture
def phase3c_stub():
    return SimpleNamespace(
        proposal_text="**Proposed:** Send the response now.",
        structured_actions=[
            {"action": "send_email", "rationale": "Time-sensitive ask"},
            {"action": "log_decision", "rationale": "Director ratified"},
        ],
    )


@pytest.fixture(autouse=True)
def _no_slack(monkeypatch):
    """Default: stub Slack so no real network call happens."""
    calls = []

    def _fake_post(card):
        calls.append(card)
        return True

    monkeypatch.setattr(p4, "_post_to_slack", _fake_post)
    return calls


@pytest.fixture(autouse=True)
def _force_dry_run_off(monkeypatch):
    monkeypatch.delenv("CORTEX_DRY_RUN", raising=False)


# --------------------------------------------------------------------------
# _build_blocks — Block Kit shape
# --------------------------------------------------------------------------


def test_build_blocks_includes_4_buttons_in_actions_block(phase3c_stub):
    blocks = p4._build_blocks(
        proposal_id="prop-1",
        cycle_id="cyc-1",
        matter_slug="oskolkov",
        proposal_text="hello",
        structured_actions=phase3c_stub.structured_actions,
        proposed_gold=[],
    )
    actions = [b for b in blocks if b.get("type") == "actions"]
    assert len(actions) == 1
    elements = actions[0]["elements"]
    action_ids = {el["action_id"] for el in elements}
    assert action_ids == {"cortex_approve", "cortex_edit", "cortex_refresh", "cortex_reject"}


def test_build_blocks_button_value_is_valid_json_with_ids(phase3c_stub):
    blocks = p4._build_blocks(
        proposal_id="prop-x", cycle_id="cyc-x", matter_slug="movie",
        proposal_text="t", structured_actions=[], proposed_gold=[],
    )
    actions = [b for b in blocks if b.get("type") == "actions"][0]
    btn = actions["elements"][0]
    parsed = json.loads(btn["value"])
    assert parsed["cycle_id"] == "cyc-x"
    assert parsed["proposal_id"] == "prop-x"


def test_build_blocks_truncates_long_proposal_text():
    long_text = "x" * 10_000
    blocks = p4._build_blocks(
        proposal_id="p", cycle_id="c", matter_slug="m",
        proposal_text=long_text, structured_actions=[], proposed_gold=[],
    )
    body = next(b for b in blocks if b.get("type") == "section")
    assert len(body["text"]["text"]) <= p4.SECTION_TEXT_LIMIT


def test_build_blocks_includes_gold_checkbox_group_when_proposed_gold_present():
    proposed_gold = [
        {"filename": "ao-funds-flow.md", "content": "x", "default_checked": True},
        {"filename": "ao-deadlines.md", "content": "y", "default_checked": True},
    ]
    blocks = p4._build_blocks(
        proposal_id="p", cycle_id="c", matter_slug="m",
        proposal_text="hi", structured_actions=[], proposed_gold=proposed_gold,
    )
    cb = [b for b in blocks if b.get("accessory", {}).get("type") == "checkboxes"]
    assert len(cb) == 1
    options = cb[0]["accessory"]["options"]
    assert {o["value"] for o in options} == {"ao-funds-flow.md", "ao-deadlines.md"}
    assert "initial_options" in cb[0]["accessory"]   # all checked by default


def test_build_blocks_caps_gold_options_at_slack_limit(monkeypatch):
    proposed_gold = [
        {"filename": f"file-{i}.md", "content": "", "default_checked": True}
        for i in range(20)
    ]
    blocks = p4._build_blocks(
        proposal_id="p", cycle_id="c", matter_slug="m",
        proposal_text="hi", structured_actions=[], proposed_gold=proposed_gold,
    )
    cb = next(b for b in blocks if b.get("accessory", {}).get("type") == "checkboxes")
    assert len(cb["accessory"]["options"]) == p4.MAX_GOLD_CHECKBOXES


def test_build_blocks_omits_gold_block_when_no_proposed_gold():
    blocks = p4._build_blocks(
        proposal_id="p", cycle_id="c", matter_slug="m",
        proposal_text="hi", structured_actions=[], proposed_gold=[],
    )
    assert all(b.get("accessory", {}).get("type") != "checkboxes" for b in blocks)


def test_build_blocks_includes_actions_summary_when_present(phase3c_stub):
    blocks = p4._build_blocks(
        proposal_id="p", cycle_id="c", matter_slug="m",
        proposal_text="hi",
        structured_actions=phase3c_stub.structured_actions,
        proposed_gold=[],
    )
    flat = json.dumps(blocks)
    assert "Proposed actions:" in flat
    assert "send_email" in flat


def test_build_blocks_payload_is_json_serializable(phase3c_stub):
    blocks = p4._build_blocks(
        proposal_id="p", cycle_id="c", matter_slug="m",
        proposal_text="hi",
        structured_actions=phase3c_stub.structured_actions,
        proposed_gold=[{"filename": "a.md", "content": "", "default_checked": True}],
    )
    json.dumps(blocks)   # raises if non-serializable


def test_build_blocks_total_block_count_under_50(phase3c_stub):
    blocks = p4._build_blocks(
        proposal_id="p", cycle_id="c", matter_slug="m",
        proposal_text="hi",
        structured_actions=phase3c_stub.structured_actions,
        proposed_gold=[
            {"filename": f"f{i}.md", "content": "", "default_checked": True}
            for i in range(20)
        ],
    )
    assert len(blocks) <= 50


# --------------------------------------------------------------------------
# _build_proposed_gold_entries — staging directory
# --------------------------------------------------------------------------


def test_proposed_gold_returns_empty_when_no_staging_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(p4, "STAGING_ROOT", tmp_path)
    result = p4._build_proposed_gold_entries(
        cycle_id="missing", matter_slug="m",
        structured_actions=[], proposal_text="",
    )
    assert result == []


def test_proposed_gold_reads_md_files(tmp_path, monkeypatch):
    monkeypatch.setattr(p4, "STAGING_ROOT", tmp_path)
    cycle_dir = tmp_path / "cyc-1"
    cycle_dir.mkdir()
    (cycle_dir / "alpha.md").write_text("alpha content")
    (cycle_dir / "bravo.md").write_text("bravo content")
    (cycle_dir / "skip.txt").write_text("not md")   # filtered

    result = p4._build_proposed_gold_entries(
        cycle_id="cyc-1", matter_slug="m",
        structured_actions=[], proposal_text="",
    )
    names = {e["filename"] for e in result}
    assert names == {"alpha.md", "bravo.md"}
    assert all(e["default_checked"] is True for e in result)


# --------------------------------------------------------------------------
# _persist_phase4 — captured-SQL assertion
# --------------------------------------------------------------------------


def test_persist_phase4_inserts_propose_artifact_and_updates_cycle(fake_store):
    card = p4.ProposalCard(
        proposal_id="prop-1", cycle_id="cyc-1", matter_slug="oskolkov",
        proposal_text="hi", structured_actions=[{"action": "x"}],
        proposed_gold_entries=[{"filename": "f.md"}],
        blocks=[{"type": "section"}],
    )
    p4._persist_phase4("cyc-1", card)
    assert len(fake_store.conns) == 1
    cur = fake_store.conns[0].cur
    sqls = [q[0] for q in cur.queries]
    assert any("INSERT INTO cortex_phase_outputs" in s and "'propose'" in s for s in sqls)
    assert any("UPDATE cortex_cycles" in s and "tier_b_pending" in s for s in sqls)
    assert fake_store.conns[0].committed is True


def test_persist_phase4_rolls_back_on_db_error(monkeypatch, fake_store):
    """If cursor.execute raises, conn.rollback fires before re-raise."""
    class BadCursor(_FakeCursor):
        def execute(self, q, params=None):
            raise RuntimeError("DB exploded")

    def bad_conn_factory():
        c = _FakeConn()
        c.cur = BadCursor()
        fake_store.conns.append(c)
        return c

    monkeypatch.setattr(fake_store, "_get_conn", bad_conn_factory)

    card = p4.ProposalCard(
        proposal_id="x", cycle_id="x", matter_slug="m",
        proposal_text="x", structured_actions=[],
        proposed_gold_entries=[], blocks=[],
    )
    with pytest.raises(RuntimeError):
        p4._persist_phase4("x", card)
    assert fake_store.conns[-1].rolled_back is True


# --------------------------------------------------------------------------
# run_phase4_propose — integration with DRY_RUN gate
# --------------------------------------------------------------------------


def test_dry_run_skips_slack_and_writes_marker(monkeypatch, fake_store, phase3c_stub):
    monkeypatch.setenv("CORTEX_DRY_RUN", "true")
    posted = []
    monkeypatch.setattr(p4, "_post_to_slack", lambda c: (posted.append(c), True)[1])

    card = asyncio.run(p4.run_phase4_propose(
        cycle_id="cyc-d", matter_slug="oskolkov", phase3c_result=phase3c_stub,
    ))
    assert posted == []
    assert card.dry_run is True
    sql_concat = "\n".join(q[0] for c in fake_store.conns for q in c.cur.queries)
    assert "dry_run_marker" in sql_concat


def test_non_dry_run_calls_slack_poster(monkeypatch, fake_store, phase3c_stub):
    monkeypatch.delenv("CORTEX_DRY_RUN", raising=False)
    posted = []
    monkeypatch.setattr(p4, "_post_to_slack", lambda c: (posted.append(c), True)[1])

    card = asyncio.run(p4.run_phase4_propose(
        cycle_id="cyc-r", matter_slug="oskolkov", phase3c_result=phase3c_stub,
    ))
    assert len(posted) == 1
    assert card.dry_run is False
    assert posted[0].cycle_id == "cyc-r"


def test_run_phase4_returns_card_with_uuid_proposal_id(monkeypatch, fake_store, phase3c_stub):
    card = asyncio.run(p4.run_phase4_propose(
        cycle_id="cyc-u", matter_slug="movie", phase3c_result=phase3c_stub,
    ))
    import uuid as _uuid
    _uuid.UUID(card.proposal_id)   # raises if not a UUID
    assert card.matter_slug == "movie"


def test_run_phase4_persists_card_artifact(monkeypatch, fake_store, phase3c_stub):
    asyncio.run(p4.run_phase4_propose(
        cycle_id="cyc-p", matter_slug="oskolkov", phase3c_result=phase3c_stub,
    ))
    inserts = [
        q for c in fake_store.conns for q in c.cur.queries
        if "INSERT INTO cortex_phase_outputs" in q[0]
    ]
    assert len(inserts) >= 1
