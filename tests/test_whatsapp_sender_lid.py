"""Tests for outputs/whatsapp_sender.py LID resolution + audit logging.

Why this test exists: 2026-05-05 — sends to Kira (46761387271@c.us) silently
failed because her active WhatsApp chat had migrated to @lid. Sender now
resolves @c.us → @lid via whatsapp_lid_map and audits every attempt.

2026-05-08 — BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1 added Director phone-root
short-circuit + recipient-id assertion + asymmetric Director-fail-closed +
path_taken audit-row contract. New tests A/A2/C/D/E/F/G appended below.
"""
from unittest.mock import MagicMock, patch

import pytest

import outputs.whatsapp_sender as sender


def _mock_store(lookup_row):
    """Build a SentinelStoreBack mock whose cursor returns lookup_row."""
    cur = MagicMock()
    cur.fetchone.return_value = lookup_row
    conn = MagicMock()
    conn.cursor.return_value = cur
    store = MagicMock()
    store._get_conn.return_value = conn
    store._put_conn = MagicMock()
    return store, conn, cur


def test_resolve_returns_lid_when_phone_has_mapping():
    store, _, cur = _mock_store(("10110470463618@lid",))
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        result = sender._resolve_to_active_chat_id("46761387271@c.us")
    assert result == "10110470463618@lid"
    cur.execute.assert_called_once()
    sql_arg, params = cur.execute.call_args.args
    assert "FROM whatsapp_messages" in sql_arg
    assert "ORDER BY timestamp DESC" in sql_arg
    assert params == ("46761387271@c.us",)


def test_resolve_returns_input_when_no_mapping():
    store, _, _ = _mock_store(None)
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        result = sender._resolve_to_active_chat_id("99999999999@c.us")
    assert result == "99999999999@c.us"


def test_resolve_passes_through_non_cus_chat_ids():
    # Already an @lid or @s.whatsapp.net — no mapping needed
    assert sender._resolve_to_active_chat_id("10110470463618@lid") == "10110470463618@lid"
    assert sender._resolve_to_active_chat_id("") == ""


def test_resolve_fails_open_on_db_error():
    conn = MagicMock()
    conn.cursor.side_effect = RuntimeError("db down")
    store = MagicMock()
    store._get_conn.return_value = conn
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        result = sender._resolve_to_active_chat_id("46761387271@c.us")
    assert result == "46761387271@c.us"


def test_send_uses_resolved_chat_id_in_waha_call():
    store, _, _ = _mock_store(("10110470463618@lid",))
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        with patch.object(sender, "_log_send_to_baker_actions"):
            with patch("httpx.Client") as MockClient:
                client_inst = MockClient.return_value.__enter__.return_value
                resp = MagicMock()
                resp.is_success = True
                resp.status_code = 200
                client_inst.post.return_value = resp
                ok = sender.send_whatsapp(text="hi", chat_id="46761387271@c.us")
    assert ok is True
    posted = client_inst.post.call_args
    assert posted.kwargs["json"]["chatId"] == "10110470463618@lid"


def test_send_audits_failure_with_response_body():
    store, _, _ = _mock_store(None)  # no LID mapping for this number
    captured = {}

    def fake_log(**kwargs):
        captured.update(kwargs)

    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        with patch.object(sender, "_log_send_to_baker_actions", side_effect=fake_log):
            with patch("httpx.Client") as MockClient:
                client_inst = MockClient.return_value.__enter__.return_value
                resp = MagicMock()
                resp.is_success = False
                resp.status_code = 422
                resp.text = '{"error":"chat not found"}'
                client_inst.post.return_value = resp
                ok = sender.send_whatsapp(text="hi", chat_id="99999999999@c.us")
    assert ok is False
    assert captured["success"] is False
    assert captured["http_status"] == 422
    assert "chat not found" in captured["error_message"]


# ----------------------------------------------------------------------------
# BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1 (v0.3) — incident regression tests
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("director_root", sorted(sender.DIRECTOR_PHONE_ROOTS))
@pytest.mark.parametrize("suffix", ["@c.us", "@s.whatsapp.net"])
def test_director_recipient_never_resolves_elsewhere_for_any_director_root(director_root, suffix):
    """Test A — Resolver-level regression for 2026-05-08 incident, parametrized
    over every digit-root in DIRECTOR_PHONE_ROOTS and every chat-id form that
    Director's number can take. Adding a new Director root to the set
    automatically covers a new test instance — no per-root hardcoding.

    Even if whatsapp_messages contains rows where sender=Director-form-X and
    chat_id=somebody-else's-thread, _resolve_to_active_chat_id must short-
    circuit and return the input unchanged.
    """
    store, _, _ = _mock_store(("447468357311@s.whatsapp.net",))
    form = f"{director_root}{suffix}"
    if not form.endswith("@c.us"):
        # Resolver only runs for @c.us inputs; @s.whatsapp.net is passthrough already.
        # Both forms must end up unchanged at the public boundary.
        assert sender._resolve_to_active_chat_id(form) == form
        return
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        result = sender._resolve_to_active_chat_id(form)
        assert result == form, (
            f"Director form {form!r} resolved to {result!r} — "
            f"short-circuit failed for root {director_root!r}; bug recurs."
        )


@pytest.mark.parametrize("director_root", sorted(sender.DIRECTOR_PHONE_ROOTS))
def test_e2e_send_never_posts_director_traffic_to_a_counterparty_for_any_director_root(director_root):
    """Test A2 — End-to-end regression: poison whatsapp_messages with
    sender=Director-root + chat_id=Marcus, then call send_whatsapp(text,
    "<root>@c.us"). Assert the HTTP POST chatId carries a Director-owned
    phone-root, NOT Marcus's chat. Parametrized over DIRECTOR_PHONE_ROOTS.
    """
    requested = f"{director_root}@c.us"
    store, _, _ = _mock_store(("447468357311@s.whatsapp.net",))
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        with patch.object(sender, "_log_send_to_baker_actions"):
            with patch("httpx.Client") as MockClient:
                client_inst = MockClient.return_value.__enter__.return_value
                resp = MagicMock()
                resp.is_success = True
                resp.status_code = 200
                client_inst.post.return_value = resp
                ok = sender.send_whatsapp(text="T1 alert body", chat_id=requested)

    assert ok is True
    posted = client_inst.post.call_args
    posted_chat_id = posted.kwargs["json"]["chatId"]
    assert sender._phone_root(posted_chat_id) in sender.DIRECTOR_PHONE_ROOTS, (
        f"send_whatsapp routed Director-root {director_root!r} traffic to a non-Director "
        f"chat (chatId={posted_chat_id!r}) — bug would recur in production."
    )
    assert "447468357311" not in posted_chat_id, (
        f"Marcus's digits found in posted chat_id={posted_chat_id!r} for root {director_root!r}."
    )


def test_send_aborts_when_resolved_chat_id_has_different_phone_root_and_no_lid_match():
    """Test C — Defence-in-depth: non-Director request where resolver returns
    a wrong chat_id (not @lid) and phone-roots disagree. send_whatsapp must
    NOT POST to WAHA. Audit row records path_taken='aborted_assertion_unsafe'.
    """
    captured = {}

    def fake_log(**kwargs):
        captured.update(kwargs)

    with patch.object(sender, "_resolve_to_active_chat_id", return_value="447468357311@s.whatsapp.net"):
        with patch.object(sender, "_log_send_to_baker_actions", side_effect=fake_log):
            with patch("httpx.Client") as MockClient:
                ok = sender.send_whatsapp(text="alert", chat_id="99999999999@c.us")
                assert ok is False
                MockClient.return_value.__enter__.return_value.post.assert_not_called()
                assert captured["success"] is False
                assert captured["path_taken"] == "aborted_assertion_unsafe"
                assert "recipient-id assertion FAILED" in captured["error_message"]


def test_non_director_lid_db_unreachable_allows_send_alarms_slack_and_records_path_taken():
    """Test D — Non-Director DEGRADED path: resolver returns @lid for different
    phone-root, LID-map DB unreachable. Per HIGH 3b: send proceeds (no silent
    abort for Kira-style legitimate @lid contacts), Slack #cockpit alarm
    fires, audit row records path_taken='lid_map_unavailable_fallback'.
    """
    captured = {}

    def fake_log(**kwargs):
        captured.update(kwargs)

    with patch.object(sender, "_resolve_to_active_chat_id", return_value="10110470463618@lid"):
        with patch.object(sender, "_lid_belongs_to_phone", return_value=None):
            with patch.object(sender, "_alarm_slack_lid_db_degraded") as mock_alarm:
                with patch.object(sender, "_log_send_to_baker_actions", side_effect=fake_log):
                    with patch("httpx.Client") as MockClient:
                        client_inst = MockClient.return_value.__enter__.return_value
                        resp = MagicMock()
                        resp.is_success = True
                        resp.status_code = 200
                        client_inst.post.return_value = resp
                        ok = sender.send_whatsapp(text="hi Kira", chat_id="46761387271@c.us")
    assert ok is True
    MockClient.return_value.__enter__.return_value.post.assert_called_once()
    mock_alarm.assert_called_once()
    assert captured["path_taken"] == "lid_map_unavailable_fallback"


@pytest.mark.parametrize("director_root", sorted(sender.DIRECTOR_PHONE_ROOTS))
def test_director_target_lid_db_unreachable_collapses_to_fail_closed(director_root):
    """Test E — Director DEGRADED-grade collapses to UNSAFE (HIGH 3a, asymmetric
    fail-closed). When the requested chat_id's phone-root is in
    DIRECTOR_PHONE_ROOTS and the LID-map lookup is unreachable for an @lid
    resolution, the asymmetric policy must collapse to UNSAFE (no DEGRADED at
    Director's stake level). HTTP POST must NOT fire. Audit row must record
    path_taken='lid_map_unavailable_director_fail_closed'.

    Defence-in-depth: if the resolver short-circuit is ever bypassed by future
    refactor, the assertion layer must still fail closed for Director.
    """
    requested = f"{director_root}@c.us"
    captured = {}

    def fake_log(**kwargs):
        captured.update(kwargs)

    with patch.object(sender, "_resolve_to_active_chat_id", return_value="999999999999@lid"):
        with patch.object(sender, "_lid_belongs_to_phone", return_value=None):
            with patch.object(sender, "_alarm_slack_lid_db_degraded") as mock_alarm:
                with patch.object(sender, "_log_send_to_baker_actions", side_effect=fake_log):
                    with patch("httpx.Client") as MockClient:
                        ok = sender.send_whatsapp(text="director alert", chat_id=requested)
    assert ok is False
    MockClient.return_value.__enter__.return_value.post.assert_not_called()
    mock_alarm.assert_not_called()
    assert captured["path_taken"] == "lid_map_unavailable_director_fail_closed"


def test_phone_root_handles_edge_cases():
    """Test F (part 1) — _phone_root edge cases."""
    assert sender._phone_root("41799605092@c.us") == "41799605092"
    assert sender._phone_root("41799605092@s.whatsapp.net") == "41799605092"
    assert sender._phone_root("10110470463618@lid") == "10110470463618"
    assert sender._phone_root("") == ""
    assert sender._phone_root("not-a-chat-id") == ""
    assert sender._phone_root("@c.us") == ""


def test_director_phone_roots_set_includes_both_swiss_and_uk():
    """Test F (part 2) — DIRECTOR_PHONE_ROOTS literal sanity (HIGH-1 v0.3)."""
    assert "41799605092" in sender.DIRECTOR_PHONE_ROOTS
    assert "447588690632" in sender.DIRECTOR_PHONE_ROOTS
    assert sender._phone_root(sender.DIRECTOR_WHATSAPP) in sender.DIRECTOR_PHONE_ROOTS


def _drive_scenario(sender_module, scenario: str) -> None:
    """Test G helper — set up scenario-specific mocks + invoke send_whatsapp.
    Each scenario must produce exactly one audit row with the expected
    path_taken value. Outer test patches _log_send_to_baker_actions and
    httpx.Client; this helper layers the per-scenario resolver/lid mocks.
    """
    if scenario == "director_short_circuit":
        # Director-target, resolver short-circuits naturally on phone-root.
        sender_module.send_whatsapp(text="director smoke", chat_id=sender_module.DIRECTOR_WHATSAPP)
        return
    if scenario == "clean_resolver_return":
        # Non-Director, resolver maps to @lid, lid_belongs confirms TRUE.
        with patch.object(sender_module, "_resolve_to_active_chat_id", return_value="10110470463618@lid"):
            with patch.object(sender_module, "_lid_belongs_to_phone", return_value=True):
                sender_module.send_whatsapp(text="kira", chat_id="46761387271@c.us")
        return
    if scenario == "phone_root_mismatch":
        # Non-Director, resolver returns wrong-root non-@lid address.
        with patch.object(sender_module, "_resolve_to_active_chat_id", return_value="447468357311@s.whatsapp.net"):
            sender_module.send_whatsapp(text="alert", chat_id="99999999999@c.us")
        return
    if scenario == "non_director_lid_db_err":
        # Non-Director, resolver returns @lid different-root, lid_belongs returns None.
        with patch.object(sender_module, "_resolve_to_active_chat_id", return_value="10110470463618@lid"):
            with patch.object(sender_module, "_lid_belongs_to_phone", return_value=None):
                with patch.object(sender_module, "_alarm_slack_lid_db_degraded"):
                    sender_module.send_whatsapp(text="kira", chat_id="46761387271@c.us")
        return
    if scenario == "director_lid_db_err":
        # Director, force resolver around the short-circuit; lid_belongs returns None.
        with patch.object(sender_module, "_resolve_to_active_chat_id", return_value="999999999999@lid"):
            with patch.object(sender_module, "_lid_belongs_to_phone", return_value=None):
                with patch.object(sender_module, "_alarm_slack_lid_db_degraded"):
                    sender_module.send_whatsapp(text="director alert", chat_id=sender_module.DIRECTOR_WHATSAPP)
        return
    raise ValueError(f"Unknown scenario: {scenario}")


@pytest.mark.parametrize("scenario,expected_path", [
    ("director_short_circuit",  "short_circuit_director"),
    ("clean_resolver_return",   "resolver_returned_clean"),
    ("phone_root_mismatch",     "aborted_assertion_unsafe"),
    ("non_director_lid_db_err", "lid_map_unavailable_fallback"),
    ("director_lid_db_err",     "lid_map_unavailable_director_fail_closed"),
])
def test_path_taken_audit_row_written_exactly_once_per_scenario(scenario, expected_path):
    """Test G — Every code path writes exactly ONE baker_actions row whose
    payload.path_taken matches the expected value. No path writes zero rows.
    No path writes >1 row. Forensic reconstruction post-incident is unambiguous.
    """
    captured_audits = []

    def capture(**kwargs):
        captured_audits.append(kwargs)

    with patch.object(sender, "_log_send_to_baker_actions", side_effect=capture):
        with patch("httpx.Client") as MockClient:
            client_inst = MockClient.return_value.__enter__.return_value
            resp = MagicMock()
            resp.is_success = True
            resp.status_code = 200
            client_inst.post.return_value = resp
            _drive_scenario(sender, scenario)
    assert len(captured_audits) == 1, (
        f"Scenario {scenario!r} wrote {len(captured_audits)} audit rows; expected 1."
    )
    assert captured_audits[0]["path_taken"] == expected_path, (
        f"Scenario {scenario!r}: audit row path_taken="
        f"{captured_audits[0]['path_taken']!r} expected={expected_path!r}."
    )
