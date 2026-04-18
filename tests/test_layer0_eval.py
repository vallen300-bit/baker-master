"""Tests for kbl.layer0 — Step 0 evaluator.

Covers:
    - never-drop invariants (scan, Director, VIP soft-fail CLOSED, slug/alias override)
    - rule walk (first-match-wins; drop on each rule in fixture ruleset)
    - short-slug alias-aware topic override (S3)
    - 1-in-50 review sampling (S6) via _process_layer0
    - content-hash insert-on-PASS-only (S5) via _process_layer0
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kbl import layer0, layer0_dedupe, layer0_rules, slug_registry
from kbl.layer0 import (
    Layer0Decision,
    Signal,
    _process_layer0,
    evaluate,
)

FIXTURES = Path(__file__).parent / "fixtures"
RULESET_YML = FIXTURES / "layer0_rules_evaluator_test.yml"
VAULT_LAYER0 = FIXTURES / "vault_layer0"


# ------------------------------ fixtures ------------------------------


@pytest.fixture(autouse=True)
def _reset_caches_and_vault(monkeypatch: pytest.MonkeyPatch):
    """Clear both layer0_rules + slug_registry caches and point the vault at
    the evaluator fixture vault so the S3 topic-override check resolves
    deterministically instead of triggering S4 soft-fail-CLOSED pass-through
    (which would mask rule-walk bugs)."""
    layer0_rules.reload()
    slug_registry.reload()
    monkeypatch.setenv("BAKER_VAULT_PATH", str(VAULT_LAYER0))
    yield
    layer0_rules.reload()
    slug_registry.reload()


@pytest.fixture
def ruleset():
    return layer0_rules.load_layer0_rules(RULESET_YML)


@pytest.fixture
def vault_env() -> None:
    """Kept for explicit-intent tests; vault is already set by autouse."""
    return None


@pytest.fixture
def no_vip(monkeypatch: pytest.MonkeyPatch):
    """Force VIP checker to return False — isolates rule-walk behaviour."""
    return lambda payload: False


def _email(sender: str, body: str = "", sid: int = 1, **payload) -> Signal:
    pl = {"sender": sender, **payload}
    return Signal(id=sid, source="email", raw_content=body, payload=pl)


def _wa(sender: str = "+43 664 111 2233", body: str = "", sid: int = 1, **payload) -> Signal:
    pl = {"sender": sender, **payload}
    return Signal(id=sid, source="whatsapp", raw_content=body, payload=pl)


def _meeting(body: str = "", sid: int = 1, **payload) -> Signal:
    return Signal(id=sid, source="meeting", raw_content=body, payload=payload)


# ------------------------------ never-drop invariants ------------------------------


def test_scan_source_always_passes(ruleset, no_vip) -> None:
    sig = Signal(id=1, source="scan", raw_content="baker_scan: anything", payload={})
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "pass"


def test_director_email_short_circuits_to_pass(ruleset, no_vip) -> None:
    """C2 Inv 5: Director-authored content NEVER dropped regardless of shape."""
    sig = _email(
        sender="dvallen@brisengroup.com",
        body="baker_scan: this would trigger the echo rule",
    )
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "pass"


def test_director_whatsapp_short_circuits_to_pass(ruleset, no_vip) -> None:
    sig = _wa(sender="41799605092@c.us", body="ok")
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "pass"


def test_primary_matter_hint_short_circuits_to_pass(ruleset, no_vip) -> None:
    sig = _email(
        sender="spammer@bulk-newsletter.test",
        body="Would have dropped",
        primary_matter_hint="hagenauer",
    )
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "pass"


def test_vip_sender_passes(ruleset) -> None:
    """VIP override short-circuits rule walk."""
    vip_checker = lambda payload: payload.get("sender") == "wertheimer@chanel.test"
    sig = _email(
        sender="wertheimer@chanel.test",
        body="Proposal — routed via Mailchimp domain",
    )
    decision = evaluate(sig, ruleset=ruleset, vip_checker=vip_checker)
    assert decision.verdict == "pass"


def test_vip_lookup_failure_passes_signal_through(ruleset) -> None:
    """S4 soft-fail CLOSED: VIP resolver raises → treat as VIP (pass)."""

    def failing_vip(payload):
        raise ConnectionError("vip service down")

    sig = _email(
        sender="spammer@bulk-newsletter.test",
        body="Would normally drop",
    )
    decision = evaluate(sig, ruleset=ruleset, vip_checker=failing_vip)
    assert decision.verdict == "pass"


# ------------------------------ topic override (S3) ------------------------------


def test_slug_alias_topic_override_passes(ruleset, vault_env, no_vip) -> None:
    """Newsletter sender + content mentions MO Vienna via alias → topic override."""
    sig = _email(
        sender="newsletters@bulk-newsletter.test",
        body="Mandarin Oriental Vienna announces a new suite category...",
    )
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "pass"


def test_short_slug_canonical_only_does_NOT_trigger_override(
    ruleset, vault_env, no_vip
) -> None:
    """S3 safeguard: 'ao' appearing in arbitrary Portuguese text MUST NOT fire
    the override — canonical `ao` is <4 chars, alias required."""
    sig = _email(
        sender="newsletters@bulk-newsletter.test",
        body="O CEO disse 'ao tempo certo, vamos avaliar' durante a palestra.",
    )
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "drop"
    assert decision.rule_name == "email_newsletter_domain"


def test_short_slug_alias_DOES_trigger_override(
    ruleset, vault_env, no_vip
) -> None:
    """S3 positive: 'Oskolkov' is an alias of short-slug `ao` → fires override."""
    sig = _email(
        sender="newsletters@bulk-newsletter.test",
        body="UAE investor Andrey Oskolkov backs new Geneva fund...",
    )
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "pass"


def test_slug_registry_outage_passes_through(ruleset, vault_env, no_vip) -> None:
    """S4 parallel: slug-registry read failure → pass-through (not drop)."""
    sig = _email(
        sender="newsletters@bulk-newsletter.test",
        body="nothing about any matter",
    )
    with patch.object(
        layer0, "_mentions_active_slug_or_alias", side_effect=ConnectionError("down")
    ):
        decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "pass"


# ------------------------------ rule walk ------------------------------


def test_pass_happy_path_no_rule_matches(ruleset, no_vip) -> None:
    """Email from a non-blocklisted sender with real content — passes."""
    sig = _email(
        sender="client@clientco.test",
        body="Please review the attached draft by Friday.",
    )
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "pass"


def test_drop_email_newsletter_domain(ruleset, no_vip) -> None:
    sig = _email(
        sender="newsletters@bulk-newsletter.test",
        body="Daily Briefing — 12 stories today.",
    )
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "drop"
    assert decision.rule_name == "email_newsletter_domain"
    assert decision.detail and "blocklist" in decision.detail


def test_drop_wa_status_broadcast(ruleset, no_vip) -> None:
    sig = _wa(
        sender="+43 664 111 2233",
        body="Announcing a long-form status update that is not short.",
        chat_id="status@broadcast",
    )
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "drop"
    assert decision.rule_name == "wa_status_broadcast"


def test_drop_wa_minimum_content_length(ruleset, no_vip) -> None:
    """First applicable rule wins — both wa_status and wa_min could apply,
    but the status rule is listed first. Here chat_id doesn't match
    status, so wa_minimum_content_length fires instead."""
    sig = _wa(sender="+43 664 111 2233", body="ok", chat_id="12345@c.us")
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "drop"
    assert decision.rule_name == "wa_minimum_content_length"


def test_drop_baker_self_analysis_echo_email(ruleset, no_vip) -> None:
    sig = _email(
        sender="client@clientco.test",
        body="baker_scan: Daily summary 2026-04-18 — 12 signals processed.",
    )
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "drop"
    assert decision.rule_name == "baker_self_analysis_echo"


def test_drop_meeting_quality_floor(ruleset, no_vip) -> None:
    body = ("Unknown: garbled. " * 30).strip()
    sig = _meeting(body=body, duration_sec=960)
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "drop"
    assert decision.rule_name == "meeting_quality_floor"


def test_first_match_wins_email(ruleset, no_vip) -> None:
    """Both newsletter-domain AND baker_scan echo rules could match; the
    domain rule appears FIRST in the fixture so it wins."""
    sig = _email(
        sender="newsletters@bulk-newsletter.test",
        body="baker_scan: would also match the cross-source echo rule",
    )
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "drop"
    assert decision.rule_name == "email_newsletter_domain"


def test_source_filter_respected(ruleset, no_vip) -> None:
    """Meeting source signal should not fire email-source rules even if the
    sender matches — content has enough lexical diversity to pass the
    transcript quality floor, so PASS."""
    sig = Signal(
        id=1,
        source="meeting",
        raw_content=(
            "The quarterly review opened with a walkthrough of the pipeline "
            "health dashboard. Draft clauses for the upcoming term sheet "
            "were circulated; legal flagged two items needing follow-up by "
            "Friday. Budget variance figures were presented alongside a "
            "revised forecast for the next two quarters. Hotel opening "
            "confirmed on schedule with soft-launch planned early next month. "
            "Food and beverage overruns discussed at length; corrective "
            "actions assigned. Security posture reviewed. Meeting ended on "
            "time with a clean action-item list shared to all attendees."
        ),
        payload={"sender": "noreply@bulk-newsletter.test", "duration_sec": 600},
    )
    decision = evaluate(sig, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "pass"


# ------------------------------ _process_layer0 ------------------------------


def test_process_layer0_inserts_hash_on_pass(ruleset, no_vip) -> None:
    """S5 discipline: hash INSERT happens on PASS, NOT on DROP."""
    sig = _email(
        sender="client@clientco.test",
        body="Fresh client-relevant content about project scheduling.",
        sid=7,
    )
    conn = MagicMock()
    with patch.object(layer0_dedupe, "has_seen_recent", return_value=False), patch.object(
        layer0_dedupe, "insert_hash"
    ) as m_insert:
        decision = _process_layer0(sig, conn, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "pass"
    assert m_insert.called
    kwargs = m_insert.call_args.kwargs
    assert kwargs["source_signal_id"] == 7
    assert kwargs["source_kind"] == "email"


def test_process_layer0_no_hash_insert_on_drop(ruleset, no_vip) -> None:
    """S5: drops MUST NOT be inserted into dedupe store — prevents false
    positive drops from suppressing future legitimate copies."""
    sig = _email(
        sender="newsletters@bulk-newsletter.test",
        body="Daily briefing",
        sid=3,  # not a multiple of 50 — also skips review sample
    )
    conn = MagicMock()
    with patch.object(layer0_dedupe, "insert_hash") as m_insert, patch.object(
        layer0_dedupe, "kbl_layer0_review_insert"
    ) as m_review:
        decision = _process_layer0(sig, conn, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "drop"
    m_insert.assert_not_called()
    m_review.assert_not_called()


def test_process_layer0_writes_review_row_at_multiple_of_50(
    ruleset, no_vip
) -> None:
    sig = _email(
        sender="newsletters@bulk-newsletter.test",
        body="Daily briefing",
        sid=50,
    )
    conn = MagicMock()
    with patch.object(layer0_dedupe, "kbl_layer0_review_insert") as m_review:
        _process_layer0(sig, conn, ruleset=ruleset, vip_checker=no_vip)
    assert m_review.called
    kwargs = m_review.call_args.kwargs
    assert kwargs["signal_id"] == 50
    assert kwargs["dropped_by_rule"] == "email_newsletter_domain"
    assert kwargs["source_kind"] == "email"


def test_process_layer0_no_review_when_id_not_multiple_of_50(
    ruleset, no_vip
) -> None:
    sig = _email(
        sender="newsletters@bulk-newsletter.test",
        body="Daily briefing",
        sid=51,
    )
    conn = MagicMock()
    with patch.object(layer0_dedupe, "kbl_layer0_review_insert") as m_review:
        _process_layer0(sig, conn, ruleset=ruleset, vip_checker=no_vip)
    m_review.assert_not_called()


def test_process_layer0_duplicate_hash_drops_second_occurrence(
    ruleset, no_vip
) -> None:
    """S5: duplicate_content_hash rule fires when has_seen_recent returns True."""
    sig = _email(
        sender="client@clientco.test",
        body="Unique-looking content once, duplicate on the second call.",
        sid=2,
    )
    conn = MagicMock()
    with patch.object(layer0_dedupe, "has_seen_recent", return_value=True), patch.object(
        layer0_dedupe, "insert_hash"
    ):
        decision = _process_layer0(sig, conn, ruleset=ruleset, vip_checker=no_vip)
    assert decision.verdict == "drop"
    assert decision.rule_name == "duplicate_content_hash"


def test_process_layer0_clears_conn_from_payload_after_evaluate(
    ruleset, no_vip
) -> None:
    """Defensive: the _kbl_conn stashing helper must not leak into the
    payload the caller keeps a reference to."""
    sig = _email(
        sender="client@clientco.test",
        body="Fresh client content about scheduling.",
        sid=11,
    )
    conn = MagicMock()
    with patch.object(layer0_dedupe, "has_seen_recent", return_value=False), patch.object(
        layer0_dedupe, "insert_hash"
    ):
        _process_layer0(sig, conn, ruleset=ruleset, vip_checker=no_vip)
    assert "_kbl_conn" not in sig.payload


# ------------------------------ Decision dataclass ------------------------------


def test_decision_is_immutable() -> None:
    d = Layer0Decision(verdict="pass")
    with pytest.raises(Exception):
        d.verdict = "drop"  # type: ignore[misc]


def test_decision_rule_name_and_detail_default_none() -> None:
    d = Layer0Decision(verdict="pass")
    assert d.rule_name is None
    assert d.detail is None
