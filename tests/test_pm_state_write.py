"""Ship gate for BRIEF_PM_SIDEBAR_STATE_WRITE_1.

Five required tests per §Ship Gate:
  1. test_extract_and_update_pm_state_tags_mutation_source
  2. test_sidebar_hook_fires_on_ao_pm
  3. test_sidebar_hook_skipped_for_non_pm_capability
  4. test_backfill_idempotency_skips_processed_rows
  5. test_flag_pm_signal_push_slack_only_when_requested

PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1 (2026-05-16) adds:
  6. test_detect_parallel_pm_key_catches_renamed_key
  7. test_detect_parallel_pm_key_ignores_exact_match
  8. test_update_pm_state_rejects_parallel_key_via_agent_tool
  9. test_update_pm_state_force_overrides_parallel_guard
 10. test_update_pm_state_patches_existing_key_via_agent_tool
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock


# ----------------------------- D1 ----------------------------------------


def test_extract_and_update_pm_state_tags_mutation_source(monkeypatch):
    """The mutation_source kwarg must flow through to the store call."""
    import orchestrator.capability_runner as cr

    # Fake Opus response: valid JSON with no wiki insights and no red_flags.
    fake_payload = json.dumps({
        "sub_matters": {}, "open_actions": [], "red_flags": [],
        "relationship_state": {}, "summary": "test summary",
        "wiki_insights": [],
    })
    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text=fake_payload)]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_msg
    monkeypatch.setattr(cr.anthropic, "Anthropic", lambda api_key=None: fake_client)

    captured = {}

    class _FakeStore:
        def update_pm_project_state(self, pm_slug, updates, summary, question,
                                    mutation_source, thread_id=None):
            # BRIEF_CAPABILITY_THREADS_1: thread_id kwarg added to the real
            # signature; accept-and-ignore here so this ship-gate test for
            # BRIEF_PM_SIDEBAR_STATE_WRITE_1 still pins mutation_source flow.
            captured["pm_slug"] = pm_slug
            captured["mutation_source"] = mutation_source
            captured["thread_id"] = thread_id
            return None  # history_row_id; not relevant to this test

        def _get_conn(self):
            return None  # stitcher's store helpers degrade to no-op

        def _put_conn(self, conn):
            pass

        def create_cross_pm_signal(self, **kwargs):  # noqa: D401
            pass

    class _FakeStoreClass:
        @staticmethod
        def _get_global_instance():
            return _FakeStore()

    # Patch SentinelStoreBack via sys.modules injection (lazy import inside fn).
    store_mod = MagicMock()
    store_mod.SentinelStoreBack = _FakeStoreClass
    monkeypatch.setitem(sys.modules, "memory.store_back", store_mod)

    # _get_extraction_dedup_context + _store_pending_insights are instance
    # methods — patch the throwaway runner the function constructs.
    monkeypatch.setattr(
        cr.CapabilityRunner, "_get_extraction_dedup_context",
        lambda self, slug: "",
    )
    monkeypatch.setattr(
        cr.CapabilityRunner, "_store_pending_insights",
        lambda self, slug, insights, q, s: None,
    )
    monkeypatch.setattr(cr.CapabilityRunner, "__init__", lambda self: None)

    out = cr.extract_and_update_pm_state(
        pm_slug="ao_pm", question="q", answer="a" * 200,
        mutation_source="sidebar",
    )

    assert out is not None
    assert captured["mutation_source"] == "sidebar"
    assert captured["pm_slug"] == "ao_pm"
    assert out["mutation_source"] == "sidebar"


# ----------------------------- D2 ----------------------------------------

def _sidebar_gate(cap_slug: str, ar, pm_registry: dict) -> bool:
    """Mirrors the D2 fast-path gate at dashboard.py verbatim in logic:

        if ar and ar.answer and cap.slug in PM_REGISTRY:
            ... fire hook ...

    Exposed as a pure predicate so the gate semantics can be unit-tested
    without loading the FastAPI app. Kept side-by-side with the inline
    check in outputs/dashboard.py; update both together or neither.
    """
    return bool(ar and getattr(ar, "answer", None) and cap_slug in pm_registry)


def test_sidebar_hook_fires_on_ao_pm():
    from orchestrator.capability_runner import PM_REGISTRY

    class _AR:
        answer = "Some AO PM analysis with enough substance."

    assert _sidebar_gate("ao_pm", _AR(), PM_REGISTRY) is True
    assert _sidebar_gate("movie_am", _AR(), PM_REGISTRY) is True

    # Also confirm the dashboard source still carries the inline gate +
    # extract_and_update_pm_state call.
    src = Path("outputs/dashboard.py").read_text()
    assert "PM-SIDEBAR-STATE-WRITE-1 D2" in src
    assert "cap.slug in PM_REGISTRY" in src
    assert 'mutation_source="sidebar"' in src
    assert 'mutation_source="decomposer"' in src


def test_sidebar_hook_skipped_for_non_pm_capability():
    from orchestrator.capability_runner import PM_REGISTRY

    class _AR:
        answer = "A finance answer."

    # `finance` is a domain capability, not in PM_REGISTRY.
    assert "finance" not in PM_REGISTRY
    assert _sidebar_gate("finance", _AR(), PM_REGISTRY) is False

    # Empty answer or missing ar → also skip.
    assert _sidebar_gate("ao_pm", None, PM_REGISTRY) is False

    class _AREmpty:
        answer = ""

    assert _sidebar_gate("ao_pm", _AREmpty(), PM_REGISTRY) is False


# ----------------------------- D4 ----------------------------------------

def test_backfill_idempotency_skips_processed_rows(monkeypatch, tmp_path):
    """Second run over the same rows must be a no-op (matched=0 new, all
    skipped as already-processed)."""
    from scripts import backfill_pm_state as bf

    # Fake rows: one ao_pm-tagged conversation, one 'general' conversation
    # whose question matches ao_pm signal patterns.
    rows = [
        (101, "Aukera status on the release", "Answer about Aukera " + "x" * 200,
         "ao_pm", "2026-04-22T10:00:00Z"),
        (102, "random finance question", "finance answer " + "x" * 200,
         "general", "2026-04-22T11:00:00Z"),
    ]

    # Simulated pm_backfill_processed state across "two runs".
    processed = set()

    class _FakeCur:
        def __init__(self):
            self._pending = []

        def execute(self, sql, params=None):  # noqa: D401
            sql_norm = " ".join(sql.split())
            if "FROM conversation_memory" in sql_norm:
                self._pending = list(rows)
            elif "FROM pm_backfill_processed" in sql_norm:
                self._pending = [(i,) for i in processed]
            elif "INSERT INTO pm_backfill_processed" in sql_norm:
                # (pm_slug, conv_id, tag)
                processed.add(params[1])
                self._pending = []

        def fetchall(self):
            out = self._pending
            self._pending = []
            return out

        def fetchone(self):
            out = self._pending[0] if self._pending else None
            self._pending = []
            return out

        def close(self):
            pass

    class _FakeConn:
        def cursor(self):
            return _FakeCur()

        def commit(self):
            pass

        def rollback(self):
            pass

    class _FakeStore:
        def _get_conn(self):
            return _FakeConn()

        def _put_conn(self, conn):
            pass

    class _FakeStoreClass:
        @staticmethod
        def _get_global_instance():
            return _FakeStore()

    store_mod = MagicMock()
    store_mod.SentinelStoreBack = _FakeStoreClass
    monkeypatch.setitem(sys.modules, "memory.store_back", store_mod)

    extract_calls = []

    def _fake_extract(**kwargs):
        extract_calls.append(kwargs["conversation_id"])
        return {
            "summary": "ok", "updates": {},
            "wiki_insights_count": 0,
            "mutation_source": kwargs["mutation_source"],
        }

    import orchestrator.capability_runner as cr
    monkeypatch.setattr(cr, "extract_and_update_pm_state", _fake_extract)

    # Simulate argv for argparse.
    monkeypatch.setattr(sys, "argv", [
        "backfill_pm_state.py", "ao_pm", "--since", "14d",
    ])

    # First run — both rows match and extract.
    bf.main()
    first_run = list(extract_calls)
    assert 101 in first_run
    assert len(processed) == len(first_run) >= 1

    # Second run — all rows already processed → no new extracts.
    extract_calls.clear()
    bf.main()
    assert extract_calls == [], (
        "Idempotency broken: backfill re-extracted already-processed rows"
    )


# ----------------------------- D6 ----------------------------------------

def test_flag_pm_signal_push_slack_only_when_requested(monkeypatch):
    """push_slack=False must NOT call post_to_channel; True must call it."""
    from orchestrator import pm_signal_detector as psd

    # Stub the SentinelStoreBack lookup so the state-update side effect is
    # a no-op inside flag_pm_signal.
    class _FakeStore:
        def update_pm_project_state(self, *a, **kw):
            pass

    class _FakeStoreClass:
        @staticmethod
        def _get_global_instance():
            return _FakeStore()

    store_mod = MagicMock()
    store_mod.SentinelStoreBack = _FakeStoreClass
    monkeypatch.setitem(sys.modules, "memory.store_back", store_mod)

    calls = []

    def _fake_post(channel_id, text):
        calls.append((channel_id, text))
        return True

    slack_mod = MagicMock()
    slack_mod.post_to_channel = _fake_post
    monkeypatch.setitem(sys.modules, "outputs.slack_notifier", slack_mod)

    # push_slack=False → zero Slack calls.
    psd.flag_pm_signal(
        "ao_pm", "email", "sender@example.com", "sample summary",
        push_slack=False,
    )
    assert calls == []

    # push_slack=True → one call to Director DM D0AFY28N030.
    psd.flag_pm_signal(
        "ao_pm", "meeting", "fireflies: Aukera budget call",
        "summary of the call", push_slack=True,
    )
    assert len(calls) == 1
    channel_id, text = calls[0]
    assert channel_id == "D0AFY28N030"
    assert "AO PM" in text
    assert "meeting" in text


# ----------------------------- PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1 -----------
# Layer 1 (tool description) is verified by source inspection; Layer 2
# (server-side similarity guard) is verified by these tests.


def test_detect_parallel_pm_key_catches_renamed_key():
    """SequenceMatcher catches `capital_call_EUR_7M` ~ `capital_calls`, and
    the token-overlap signal catches `'AO April Capital Tranche (EUR 2.5M)'`
    ~ `capital_calls` via the shared root token `capital`."""
    from memory.store_back import detect_parallel_pm_key

    existing = [
        "capital_calls", "sub_matters", "open_actions", "red_flags",
        "relationship_state",
    ]

    assert detect_parallel_pm_key("capital_call_EUR_7M", existing) == "capital_calls"
    assert detect_parallel_pm_key(
        "AO April Capital Tranche (EUR 2.5M)", existing
    ) == "capital_calls"
    # A genuinely new concept must NOT trigger the guard.
    assert detect_parallel_pm_key("rg7_equity", existing) is None
    assert detect_parallel_pm_key("financial_summary", existing) is None


def test_detect_parallel_pm_key_ignores_exact_match():
    """An exact (case/punctuation-insensitive) match is a legitimate patch,
    not a parallel — guard must return None so the merge proceeds."""
    from memory.store_back import detect_parallel_pm_key

    existing = ["capital_calls", "sub_matters"]
    assert detect_parallel_pm_key("capital_calls", existing) is None
    assert detect_parallel_pm_key("CAPITAL_CALLS", existing) is None
    assert detect_parallel_pm_key("Capital Calls", existing) is None


def _make_fake_store_with_state(state_json: dict, version: int = 1):
    """Bypass SentinelStoreBack.__init__ (which opens Qdrant/Voyage/Postgres)
    and return a minimal stand-in plus the cursor's executed-SQL log."""
    from memory.store_back import SentinelStoreBack

    fake = object.__new__(SentinelStoreBack)
    executed = []

    class _Cur:
        def __init__(self):
            self._next: list = []

        def execute(self, sql, params=None):
            sql_norm = " ".join(sql.split())
            executed.append((sql_norm, params))
            if "SELECT state_json, version FROM pm_project_state" in sql_norm:
                self._next = [(state_json, version)]
            elif "INSERT INTO pm_state_history" in sql_norm:
                self._next = [(424242,)]  # fake history id
            elif "UPDATE pm_project_state" in sql_norm:
                self.rowcount = 1
                self._next = []
            else:
                self._next = []

        def fetchone(self):
            return self._next[0] if self._next else None

        def close(self):
            pass

        rowcount = 1

    class _Conn:
        def __init__(self):
            self.committed = 0
            self.rolledback = 0

        def cursor(self):
            return _Cur()

        def commit(self):
            self.committed += 1

        def rollback(self):
            self.rolledback += 1

    conn_holder = {"conn": _Conn()}

    def _get_conn():
        return conn_holder["conn"]

    def _put_conn(_c):
        pass

    fake._get_conn = _get_conn  # type: ignore[attr-defined]
    fake._put_conn = _put_conn  # type: ignore[attr-defined]
    return fake, conn_holder, executed


def test_update_pm_state_rejects_parallel_key_via_agent_tool():
    """Acceptance #3: agent-tool write with a parallel key gets a structured
    error back; no UPDATE is issued against pm_project_state."""
    fake, conn_holder, executed = _make_fake_store_with_state(
        {"capital_calls": {"status": "fully_funded"}, "sub_matters": {}}
    )

    result = fake.update_pm_project_state(
        "ao_pm",
        {"capital_call_EUR_7M": {"status": "april_tranche_received"}},
        summary="test write — LLM invented a parallel key",
        mutation_source="agent_tool",
    )

    assert isinstance(result, dict), f"expected rejection dict, got {result!r}"
    assert result.get("error") == "parallel_key_rejected"
    assert result.get("rejected_key") == "capital_call_EUR_7M"
    assert result.get("similar_to") == "capital_calls"
    # No UPDATE to pm_project_state must have fired.
    update_sqls = [s for s, _ in executed if s.startswith("UPDATE pm_project_state")]
    assert update_sqls == [], (
        "Parallel-key write must not reach the pm_project_state UPDATE"
    )


def test_update_pm_state_force_overrides_parallel_guard():
    """Acceptance #4: same shape as #3 but with force=True the write goes
    through — pm_state_history INSERT + pm_project_state UPDATE both fire."""
    fake, conn_holder, executed = _make_fake_store_with_state(
        {"capital_calls": {"status": "fully_funded"}}
    )

    result = fake.update_pm_project_state(
        "ao_pm",
        {"capital_call_EUR_7M": {"status": "april_tranche_received"}},
        summary="force-write — Director-ratified genuine new concept",
        mutation_source="agent_tool",
        force=True,
    )

    assert result == 424242, (
        f"force=True must return the history-row id, got {result!r}"
    )
    history_inserts = [s for s, _ in executed if "INSERT INTO pm_state_history" in s]
    state_updates = [s for s, _ in executed if s.startswith("UPDATE pm_project_state")]
    assert len(history_inserts) == 1
    assert len(state_updates) == 1


def test_update_pm_state_patches_existing_key_via_agent_tool():
    """Acceptance #5: when updates target an existing key, the merge proceeds
    normally — no guard rejection."""
    fake, conn_holder, executed = _make_fake_store_with_state(
        {"capital_calls": {"status": "fully_funded"}}
    )

    result = fake.update_pm_project_state(
        "ao_pm",
        {"capital_calls": {"status": "april_tranche_received_2026_04_24"}},
        summary="patching existing capital_calls",
        mutation_source="agent_tool",
    )

    assert result == 424242
    state_updates = [s for s, _ in executed if s.startswith("UPDATE pm_project_state")]
    assert len(state_updates) == 1
