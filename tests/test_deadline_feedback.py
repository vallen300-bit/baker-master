"""DEADLINE_FEEDBACK_LOOP_1: pytest coverage for the feedback endpoint + persistence layer.

Skip-pattern: tests that require TEST_DATABASE_URL (live PG) are gated with
@pytest.mark.skipif. Pure-validation tests run unconditionally.
"""
import os
import pytest


def test_valid_feedback_types_whitelist():
    from models.deadline_feedback import VALID_FEEDBACK_TYPES
    assert VALID_FEEDBACK_TYPES == frozenset({"confirm", "mute", "wrong_matter", "wrong_deadline"})


def test_insert_feedback_rejects_invalid_type(monkeypatch):
    """Invalid feedback_type returns None without ever touching the DB."""
    from models import deadline_feedback as df_mod
    from models.deadline_feedback import insert_feedback

    call_count = {"n": 0}

    def fake_get_conn():
        call_count["n"] += 1
        return None

    # Patch the name as imported into deadline_feedback's namespace.
    monkeypatch.setattr(df_mod, "get_conn", fake_get_conn)
    result = insert_feedback(
        deadline_id=1, feedback_type="invalid_verb",
        original_matter_slug=None, corrected_matter_slug=None,
        original_description="test", original_source_type="test",
    )
    assert result is None
    assert call_count["n"] == 0  # type-check returns BEFORE get_conn is reached


@pytest.mark.skipif(
    not os.getenv("BAKER_VAULT_PATH"),
    reason="needs BAKER_VAULT_PATH to load slug registry",
)
def test_unknown_slug_normalize_returns_none():
    """Hallucinated slugs must normalize to None — gate for wrong_matter validation."""
    from kbl.slug_registry import normalize
    assert normalize("totally-fake-slug-9999") is None


def test_insert_feedback_returns_none_on_no_connection(monkeypatch):
    """When get_conn returns None, insert_feedback returns None (no crash)."""
    from models import deadline_feedback as df_mod
    from models.deadline_feedback import insert_feedback

    monkeypatch.setattr(df_mod, "get_conn", lambda: None)
    monkeypatch.setattr(df_mod, "put_conn", lambda c: None)
    result = insert_feedback(
        deadline_id=1, feedback_type="mute",
        original_matter_slug=None, corrected_matter_slug=None,
        original_description="test desc", original_source_type="test",
    )
    assert result is None


def test_degraded_write_increments_failure_counter(monkeypatch):
    """Fix B: degraded `get_conn → None` path bumps the observability counter by exactly 1."""
    from models import deadline_feedback as df_mod
    from models.deadline_feedback import (
        insert_feedback, get_write_failure_stats, reset_write_failure_stats,
    )

    reset_write_failure_stats()
    assert get_write_failure_stats()["count"] == 0

    monkeypatch.setattr(df_mod, "get_conn", lambda: None)
    monkeypatch.setattr(df_mod, "put_conn", lambda c: None)
    result = insert_feedback(
        deadline_id=1, feedback_type="mute",
        original_matter_slug=None, corrected_matter_slug=None,
        original_description="counter probe", original_source_type="test",
    )
    assert result is None
    stats = get_write_failure_stats()
    assert stats["count"] == 1
    assert stats["last_failure_at"] is not None
    # Cleanup so other tests see baseline.
    reset_write_failure_stats()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs live PG")
def test_insert_feedback_round_trip():
    """Live-PG: insert + read back."""
    from models.deadline_feedback import insert_feedback, get_recent_feedback
    fid = insert_feedback(
        deadline_id=99999, feedback_type="mute",
        original_matter_slug="hagenauer-rg7", corrected_matter_slug=None,
        original_description="test fixture", original_source_type="test",
    )
    assert fid is not None and isinstance(fid, int)
    rows = get_recent_feedback(limit=20)
    assert any(r["id"] == fid for r in rows)
    found = next(r for r in rows if r["id"] == fid)
    assert found["feedback_type"] == "mute"
    assert found["original_matter_slug"] == "hagenauer-rg7"


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs live PG")
def test_endpoint_writes_corpus_row():
    """End-to-end via FastAPI TestClient: POST /api/deadlines/{id}/feedback writes row."""
    from fastapi.testclient import TestClient
    from outputs.dashboard import app
    from models.deadlines import insert_deadline
    from datetime import datetime

    api_key = os.getenv("BAKER_API_KEY", "")
    if not api_key:
        pytest.skip("needs BAKER_API_KEY")
    client = TestClient(app)

    did = insert_deadline(
        description="test feedback fixture",
        due_date=datetime.now(),
        source_type="test", source_id="test-feedback-1",
        confidence="high",
    )
    assert did is not None

    r = client.post(
        f"/api/deadlines/{did}/feedback",
        headers={"X-Baker-Key": api_key, "Content-Type": "application/json"},
        json={"feedback_type": "wrong_matter", "corrected_matter_slug": "hagenauer-rg7"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["feedback_id"] is not None


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs live PG")
def test_endpoint_rejects_unknown_feedback_type():
    """Invalid feedback_type returns 400 with whitelist hint."""
    from fastapi.testclient import TestClient
    from outputs.dashboard import app
    from models.deadlines import insert_deadline
    from datetime import datetime

    api_key = os.getenv("BAKER_API_KEY", "")
    if not api_key:
        pytest.skip("needs BAKER_API_KEY")
    client = TestClient(app)

    did = insert_deadline(
        description="reject-test fixture", due_date=datetime.now(),
        source_type="test", source_id="test-feedback-reject", confidence="high",
    )
    r = client.post(
        f"/api/deadlines/{did}/feedback",
        headers={"X-Baker-Key": api_key, "Content-Type": "application/json"},
        json={"feedback_type": "nonsense"},
    )
    assert r.status_code == 400


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs live PG")
def test_dismiss_endpoint_writes_mute_corpus_row():
    """Backward-compat: existing /dismiss endpoint also writes a 'mute' feedback row."""
    from fastapi.testclient import TestClient
    from outputs.dashboard import app
    from models.deadlines import insert_deadline
    from models.deadline_feedback import get_recent_feedback
    from datetime import datetime

    api_key = os.getenv("BAKER_API_KEY", "")
    if not api_key:
        pytest.skip("needs BAKER_API_KEY")
    client = TestClient(app)

    did = insert_deadline(
        description="dismiss-compat fixture", due_date=datetime.now(),
        source_type="test", source_id="test-dismiss-compat", confidence="high",
    )
    r = client.post(f"/api/deadlines/{did}/dismiss", headers={"X-Baker-Key": api_key})
    assert r.status_code == 200
    rows = get_recent_feedback(limit=50)
    assert any(rw["deadline_id"] == did and rw["feedback_type"] == "mute" for rw in rows)


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs live PG")
def test_complete_endpoint_writes_confirm_corpus_row():
    """Backward-compat: existing /complete endpoint also writes a 'confirm' feedback row."""
    from fastapi.testclient import TestClient
    from outputs.dashboard import app
    from models.deadlines import insert_deadline
    from models.deadline_feedback import get_recent_feedback
    from datetime import datetime

    api_key = os.getenv("BAKER_API_KEY", "")
    if not api_key:
        pytest.skip("needs BAKER_API_KEY")
    client = TestClient(app)

    did = insert_deadline(
        description="complete-compat fixture", due_date=datetime.now(),
        source_type="test", source_id="test-complete-compat", confidence="high",
    )
    r = client.post(f"/api/deadlines/{did}/complete", headers={"X-Baker-Key": api_key})
    assert r.status_code == 200
    rows = get_recent_feedback(limit=50)
    assert any(rw["deadline_id"] == did and rw["feedback_type"] == "confirm" for rw in rows)
