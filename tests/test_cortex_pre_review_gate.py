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
        # CORTEX_PRE_REVIEW_GATE_2: record_decision now returns bool. True =
        # "this caller claimed the row" → endpoint proceeds to fire cycle.
        record_calls.append((signal_id, action, matter_slug))
        return True

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


# ================================================================
# CORTEX_PRE_REVIEW_GATE_2_HARDEN — atomic claim + Slack unfurl off
# ================================================================

# ----------------------------------------------------------------
# Test 8 — atomic claim: first call wins, second call loses
# ----------------------------------------------------------------

def test_record_decision_claim_then_loser(monkeypatch):
    """First record_decision returns True (claimed via INSERT...RETURNING).
    Second concurrent call for same signal_id returns False (lost the race)."""
    import triggers.cortex_pre_review_gate as g

    # Single mock cursor whose fetchone returns: 1st call → row tuple (claim),
    # 2nd call → None (NOT EXISTS predicate fired, no row inserted).
    fake_cur = MagicMock()
    fake_cur.fetchone.side_effect = [(1,), None]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur

    fake_store = MagicMock()
    fake_store._get_conn.return_value = fake_conn
    fake_store._put_conn = MagicMock()

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=fake_store,
    ):
        first = g.record_decision(
            signal_id=42, action="approve", matter_slug="oskolkov",
        )
        second = g.record_decision(
            signal_id=42, action="approve", matter_slug="oskolkov",
        )

    assert first is True, "first call MUST claim the decision row"
    assert second is False, "second call MUST lose the race (no row inserted)"


# ----------------------------------------------------------------
# Test 9 — race-loser at endpoint level does NOT fire the cycle
# ----------------------------------------------------------------

def test_gate_decide_endpoint_race_loser_does_not_fire_cycle(monkeypatch):
    """Endpoint must NOT schedule the BackgroundTask when record_decision
    returns False (race lost). This is the core mitigation against double-fire
    of the $4 cycle (CORTEX_PRE_REVIEW_GATE_2 Blocker 1)."""
    monkeypatch.setenv("CORTEX_GATE_SECRET", "test-secret-32-characters-long-XX")
    import importlib
    import triggers.cortex_pre_review_gate as g
    importlib.reload(g)

    from fastapi.testclient import TestClient
    from outputs.dashboard import app

    exp = int(time.time()) + 3600
    tok = g.sign_token(signal_id=999, action="approve", expires_at=exp)

    cycle_fire_mock = AsyncMock()

    with patch(
        "triggers.cortex_pre_review_gate.already_decided", return_value=None,
    ), patch(
        "triggers.cortex_pre_review_gate.lookup_matter_slug",
        return_value="oskolkov",
    ), patch(
        # Loser path: record_decision returns False (concurrent caller won).
        "triggers.cortex_pre_review_gate.record_decision", return_value=False,
    ), patch(
        "outputs.dashboard.maybe_run_cycle", new=cycle_fire_mock,
    ):
        client = TestClient(app)
        resp = client.get(
            f"/api/cortex/gate/decide"
            f"?signal_id=999&action=approve&exp={exp}&token={tok}",
        )

    assert resp.status_code == 200, resp.text
    assert "Already decided" in resp.text, (
        "Race-loser MUST be told 'Already decided' rather than 'Cycle started'"
    )
    # The actual mitigation: BackgroundTask did NOT call maybe_run_cycle.
    # If background_tasks.add_task fired with the loser, this would have
    # been awaited inside the TestClient's lifespan exit.
    cycle_fire_mock.assert_not_awaited()


# ----------------------------------------------------------------
# Test 10 — post_gate disables Slack URL unfurl on the gate DM
# ----------------------------------------------------------------

def test_post_gate_disables_slack_unfurl(monkeypatch):
    """post_gate MUST call post_to_channel with unfurl_links=False AND
    unfurl_media=False. Closes Blocker 2 (Slackbot-LinkExpanding GETs the
    signed Yes/Skip URLs the moment we post the message → would auto-fire
    record_decision + cycle without Director ever tapping)."""
    monkeypatch.setenv("CORTEX_GATE_SECRET", "test-secret-32-characters-long-XX")
    import importlib
    import triggers.cortex_pre_review_gate as g
    importlib.reload(g)

    captured: dict = {}

    def _fake_post(channel, text, *, unfurl_links=None, unfurl_media=None):
        captured["channel"] = channel
        captured["text"] = text
        captured["unfurl_links"] = unfurl_links
        captured["unfurl_media"] = unfurl_media
        return True

    with patch(
        "triggers.cortex_pre_review_gate.already_decided", return_value=None,
    ), patch(
        "triggers.cortex_pre_review_gate._signal_preview", return_value="preview",
    ), patch(
        "outputs.slack_notifier.post_to_channel", side_effect=_fake_post,
    ):
        ok = g.post_gate(signal_id=42, matter_slug="oskolkov")

    assert ok is True
    assert captured["unfurl_links"] is False, (
        "MUST suppress unfurl_links — Slack's URL preview fetcher will GET "
        "every link in a posted message; our gate URLs are side-effecting "
        "GETs and would auto-fire the cycle without Director taps."
    )
    assert captured["unfurl_media"] is False, (
        "MUST suppress unfurl_media for symmetry (defense in depth — any "
        "future media-link addition gets the same protection)."
    )
