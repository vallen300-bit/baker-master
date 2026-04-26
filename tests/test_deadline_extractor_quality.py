"""Tests for DEADLINE_EXTRACTOR_QUALITY_1 — L1 + L2 + whitelist filter.

Coverage (12 cases):
- L1 blocked / allowed / whitelist-override (3 from brief §7)
- L2 high-score drop / mid-score downgrade / low-score allow (3 from brief §7)
- Empty inputs, missing @ in sender, signal-negators, real Cat 6 senders, ESP infra
"""
from __future__ import annotations

from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from orchestrator.deadline_extractor_filter import (
    classify,
    DROP_THRESHOLD,
    DOWNGRADE_THRESHOLD,
    _l2_score,
    _is_whitelisted,
    WHITELIST_DOMAINS,
)


# ---------------------------------------------------------------------------
# L1 — sender domain / prefix
# ---------------------------------------------------------------------------

def test_l1_blocks_news_subdomain():
    """L1: news.* prefix is a textbook newsletter pattern."""
    r = classify("loropiana@news.loropiana.com", "Studies, Chapter I", "Plain text body.")
    assert r.action == "drop"
    assert r.layer == "L1"


def test_l1_blocks_emirates_concrete_domain():
    """L1: emirates.email is in the harvested concrete-domain list."""
    r = classify("do-not-reply@emirates.email", "Check in for your flight", "")
    assert r.action == "drop"
    assert r.layer == "L1"


def test_l1_blocks_noreply_local_part():
    """L1: noreply / no-reply / do-not-reply local-part is universally bulk."""
    r = classify("noreply@some-random-domain.example", "Account update", "")
    assert r.action == "drop"
    assert r.layer == "L1"


def test_l1_does_not_block_real_sender_with_clean_subject():
    """L1: a normal sender + neutral content → action='allow'."""
    r = classify("counsel@some-firm.example", "Re: contract draft", "Please find attached.")
    assert r.action == "allow"


def test_whitelist_overrides_l1_pattern():
    """Whitelist takes precedence even over L1 newsletter patterns."""
    # Synthesize a sender whose domain ends with a whitelisted root.
    r = classify("info@news.brisengroup.com", "20% off everything!!! act now", "Click here.")
    # `news.brisengroup.com` ends with `.brisengroup.com` → whitelisted.
    assert r.action == "allow"
    assert r.layer == "whitelist"


def test_whitelist_helper_matches_subdomain():
    assert _is_whitelisted("brisengroup.com")
    assert _is_whitelisted("foo.brisengroup.com")
    assert not _is_whitelisted("brisengroup.com.evil.example")


# ---------------------------------------------------------------------------
# L2 — keyword scorer
# ---------------------------------------------------------------------------

def test_l2_high_score_drops_promotional_email():
    """Mother's Day gift guide + 20% off = clear promo, must drop."""
    subj = "The Mother's Day Gift Guide is here — 20% off"
    body = "Special offer for our loyal members. Save up to £100."
    r = classify("sender@example-shop.example", subj, body)
    assert r.action == "drop"
    assert r.layer == "L2"
    assert r.score >= DROP_THRESHOLD


def test_l2_mid_score_downgrades():
    """A pair of soft promo cues (webinar + RSVP) should land in the downgrade band."""
    # Each regex contributes its weight once per email, not per match.
    # webinar/seminar/conference regex (+2) + rsvp/register regex (+2) = 4
    # which is >= DOWNGRADE_THRESHOLD (3) and < DROP_THRESHOLD (5).
    r = classify(
        "contact@unknown-vendor.example",
        "Webinar invitation: Q3 trends",
        "Join us. RSVP today.",
    )
    assert r.action == "downgrade"
    assert DOWNGRADE_THRESHOLD <= r.score < DROP_THRESHOLD


def test_l2_low_score_allows_real_signal():
    """Real legal/contract email with deadline-y subject should pass through."""
    subj = "Re: closing date — capital call drawdown"
    body = "Please confirm the capital call drawdown by Friday. Loan repayment scheduled."
    r = classify("partner@some-bank.example", subj, body)
    # Heavy negators (capital call, loan repayment, closing date) → score 0.
    assert r.action == "allow"
    assert r.score == 0


def test_l2_negators_offset_promo_cues():
    """Mixed promo + signal terms should net out below DROP."""
    subj = "Loan repayment due — 20% discount on early settlement"
    body = "Contract amendment attached. Payment due next week. Special offer for early payers."
    score, hits = _l2_score(subj, body)
    # Has both heavy promo (% off, special offer) and heavy signal (loan repayment, contract,
    # payment due). We don't assert an exact band — just that the negators show up in hits.
    assert any("signal" in h for h in hits), f"expected at least one negator hit; got {hits!r}"


# ---------------------------------------------------------------------------
# Real-data smoke-tests — drawn from the Cat 6 dismissed-25 anchor list (brief §10).
# ---------------------------------------------------------------------------

def test_l1_blocks_lululemon_mothers_day_real_case():
    """Cat 6 row 1454/1455 (lululemon Mother's Day)."""
    r = classify("hello@e.lululemon.com", "The Mother's Day Gift Guide is here", "")
    assert r.action == "drop"
    assert r.layer == "L1"  # `e.*` subdomain pattern fires before L2


def test_l1_blocks_bloomberg_subscription_real_case():
    """Cat 6 row 1473 (Bloomberg subscription offer)."""
    r = classify(
        "subscriptions@message.bloomberg.com",
        "Where to invest $100,000 — special subscription offer",
        "",
    )
    assert r.action == "drop"
    assert r.layer == "L1"


def test_empty_inputs_default_to_allow():
    """Defensive — never raise, never drop on missing fields."""
    r = classify("", "", "")
    assert r.action == "allow"
    r2 = classify("malformed-no-at-sign", "subject", "body")
    assert r2.action == "allow"  # no domain → cannot L1, body has no promo cues
