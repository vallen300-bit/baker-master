"""Tests for CORTEX_PRE_REVIEW_GATE_1.

Brief: briefs/BRIEF_CORTEX_PRE_REVIEW_GATE_1.md

Coverage:
1. sign_token / verify_token roundtrip — happy path
2. verify_token rejects expired token
3. verify_token rejects bad signature
4. verify_token rejects unknown action
5. sign_token / verify_token returns 'gate_disabled' when CORTEX_GATE_SECRET unset
6. already_decided returns prior decision when baker_actions row exists
7. /api/cortex/gate/decide endpoint full happy path (approve flow)
"""
import os
import time
from unittest.mock import patch, AsyncMock, MagicMock

# Set secret BEFORE importing the gate module so module-level reads pick it up.
# The tests reload the module within the unset-secret test to flip state.
os.environ["CORTEX_GATE_SECRET"] = "test-secret-32-characters-long-XX"

from triggers.cortex_pre_review_gate import (
    sign_token, verify_token, GATE_TTL_SECONDS,
)


# ----------------------------------------------------------------
# Test 1 — happy path roundtrip
# ----------------------------------------------------------------

def test_sign_verify_roundtrip():
    """sign_token + verify_token round-trip cleanly with valid secret + future exp."""
    exp = int(time.time()) + 3600
    tok = sign_token(signal_id=42, action="approve", expires_at=exp)
    assert tok, "sign_token should return non-empty when secret is set"
    ok, err = verify_token(signal_id=42, action="approve", expires_at=exp, token=tok)
    assert ok is True
    assert err == ""


# ----------------------------------------------------------------
# Test 2 — expired token rejected
# ----------------------------------------------------------------

def test_verify_expired():
    """verify_token rejects a token whose expires_at is in the past."""
    exp = int(time.time()) - 60  # 1 min ago
    tok = sign_token(signal_id=42, action="approve", expires_at=exp)
    ok, err = verify_token(signal_id=42, action="approve", expires_at=exp, token=tok)
    assert ok is False
    assert err == "expired"


# ----------------------------------------------------------------
# Test 3 — bad signature rejected (constant-time compare)
# ----------------------------------------------------------------

def test_verify_bad_signature():
    """verify_token rejects a forged token via hmac.compare_digest."""
    exp = int(time.time()) + 3600
    ok, err = verify_token(
        signal_id=42, action="approve", expires_at=exp, token="garbage",
    )
    assert ok is False
    assert err == "bad_signature"


# ----------------------------------------------------------------
# Test 4 — unknown action rejected
# ----------------------------------------------------------------

def test_verify_unknown_action():
    """verify_token rejects any action outside {approve, skip}."""
    exp = int(time.time()) + 3600
    ok, err = verify_token(signal_id=42, action="DELETE", expires_at=exp, token="x")
    assert ok is False
    assert err == "invalid_action"


# ----------------------------------------------------------------
# Test 5 — secret unset disables the gate
# ----------------------------------------------------------------

def test_secret_unset_disables_gate(monkeypatch):
    """When CORTEX_GATE_SECRET is unset/short, sign returns '' and verify
    returns ('gate_disabled')."""
    monkeypatch.delenv("CORTEX_GATE_SECRET", raising=False)
    import importlib
    import triggers.cortex_pre_review_gate as g
    importlib.reload(g)
    assert g.sign_token(
        signal_id=1, action="approve", expires_at=int(time.time()) + 60,
    ) == ""
    ok, err = g.verify_token(
        signal_id=1, action="approve", expires_at=int(time.time()) + 60, token="x",
    )
    assert ok is False
    assert err == "gate_disabled"
    # Restore the env + module state for downstream tests.
    monkeypatch.setenv("CORTEX_GATE_SECRET", "test-secret-32-characters-long-XX")
    importlib.reload(g)


# ----------------------------------------------------------------
# Test 6 — already_decided returns prior decision
# ----------------------------------------------------------------

def test_already_decided_returns_prior(monkeypatch):
    """already_decided returns 'approved' when a baker_actions row exists."""
    import triggers.cortex_pre_review_gate as g

    fake_cur = MagicMock()
    fake_cur.fetchone.return_value = ("cortex:gate:approved",)
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur

    fake_store = MagicMock()
    fake_store._get_conn.return_value = fake_conn
    fake_store._put_conn = MagicMock()

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=fake_store,
    ):
        result = g.already_decided(signal_id=42)
    assert result == "approved"


# ----------------------------------------------------------------
# Test 7 — endpoint full happy path (approve flow)
# ----------------------------------------------------------------

def test_gate_decide_endpoint_approve_flow(monkeypatch):
    """/api/cortex/gate/decide?action=approve returns 200 'Cycle started'
    + schedules a background task. Token is signed; not already decided;
    matter_slug resolves to 'oskolkov'; record_decision is called."""
    monkeypatch.setenv("CORTEX_GATE_SECRET", "test-secret-32-characters-long-XX")
    import importlib
    import triggers.cortex_pre_review_gate as g
    importlib.reload(g)

    from fastapi.testclient import TestClient
    from outputs.dashboard import app

    exp = int(time.time()) + 3600
    tok = g.sign_token(signal_id=999, action="approve", expires_at=exp)

    record_calls = []

    def _fake_record(*, signal_id, action, matter_slug):
        record_calls.append((signal_id, action, matter_slug))

    with patch(
        "triggers.cortex_pre_review_gate.already_decided", return_value=None,
    ), patch(
        "triggers.cortex_pre_review_gate.lookup_matter_slug",
        return_value="oskolkov",
    ), patch(
        "triggers.cortex_pre_review_gate.record_decision", new=_fake_record,
    ), patch(
        "outputs.dashboard.maybe_run_cycle",
        new=AsyncMock(return_value=MagicMock(
            cycle_id="bg-cycle-1",
            status="tier_b_pending",
            cost_dollars=4.0,
        )),
    ):
        client = TestClient(app)
        resp = client.get(
            f"/api/cortex/gate/decide"
            f"?signal_id=999&action=approve&exp={exp}&token={tok}",
        )

    assert resp.status_code == 200, resp.text
    assert "Cycle started" in resp.text
    assert len(record_calls) == 1
    assert record_calls[0] == (999, "approve", "oskolkov")
