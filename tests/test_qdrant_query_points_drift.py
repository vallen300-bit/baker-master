from __future__ import annotations

import sys
import types
from types import SimpleNamespace


class _Point:
    def __init__(self, payload: dict, score: float = 0.9):
        self.payload = payload
        self.score = score


class _QueryPointsOnlyQdrant:
    def __init__(self, points: list[_Point]):
        self.points = points
        self.calls: list[dict] = []

    def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(points=self.points)


def test_capability_runner_positive_examples_uses_query_points(monkeypatch):
    from orchestrator.capability_runner import CapabilityRunner

    qdrant = _QueryPointsOnlyQdrant([
        _Point({"content": "approved example response", "capability_slug": "ao_pm"})
    ])
    store = SimpleNamespace(
        qdrant=qdrant,
        _embed=lambda text: [0.1] * 1024,
    )
    fake_store_back = types.SimpleNamespace(
        SentinelStoreBack=types.SimpleNamespace(_get_global_instance=lambda: store)
    )
    monkeypatch.setitem(sys.modules, "memory.store_back", fake_store_back)

    runner = CapabilityRunner.__new__(CapabilityRunner)
    out = runner._get_positive_examples("ao_pm", "question", limit=2)

    assert "approved example response" in out
    assert qdrant.calls[0]["collection_name"] == "baker-task-examples"
    assert qdrant.calls[0]["query"] == [0.1] * 1024
    assert qdrant.calls[0]["limit"] == 2
    assert qdrant.calls[0]["score_threshold"] == 0.5
    assert "query_filter" in qdrant.calls[0]


def test_cortex_dedup_uses_query_points(monkeypatch):
    from models import cortex

    qdrant = _QueryPointsOnlyQdrant([
        _Point({"canonical_id": 42, "due_date": "2026-06-30"}, score=0.93)
    ])
    monkeypatch.setattr(cortex, "_get_qdrant", lambda: qdrant)
    monkeypatch.setattr(cortex, "_embed_text", lambda text: [0.2] * 1024)

    status, canonical_id = cortex.check_dedup(
        "pay the invoice",
        "invoice",
        due_date="2026-06-30",
    )

    assert (status, canonical_id) == ("auto_merge", 42)
    assert qdrant.calls[0]["collection_name"] == "cortex_obligations"
    assert qdrant.calls[0]["query"] == [0.2] * 1024
    assert qdrant.calls[0]["limit"] == 3
    assert qdrant.calls[0]["score_threshold"] == 0.85
    assert "query_filter" in qdrant.calls[0]
