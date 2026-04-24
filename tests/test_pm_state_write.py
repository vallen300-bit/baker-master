"""Ship gate for BRIEF_PM_SIDEBAR_STATE_WRITE_1.

Five required tests per §Ship Gate:
  1. test_extract_and_update_pm_state_tags_mutation_source
  2. test_sidebar_hook_fires_on_ao_pm
  3. test_sidebar_hook_skipped_for_non_pm_capability
  4. test_backfill_idempotency_skips_processed_rows
  5. test_flag_pm_signal_push_slack_only_when_requested
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
