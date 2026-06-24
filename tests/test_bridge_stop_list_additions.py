"""Stop-list additions — BRIDGE_HOT_MD_AND_TUNING_1.

Each new pattern in ``STOPLIST_TITLE_PATTERNS`` is pinned to a realistic
Batch #1 dismissal sample so the stop-list stops quietly regressing as
we add more noise patterns. Additive-only contract: the existing 11
stop-list patterns must continue to match (snapshot regression guard).

Brief: ``briefs/BRIEF_BRIDGE_HOT_MD_AND_TUNING_1.md`` §3.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kbl.bridge import alerts_to_signal as bridge


def _alert(title: str):
    return {
        "id": 1,
        "tier": 1,                  # permissive axis — stop-list must override
        "title": title,
        "body": None,
        "matter_slug": "movie",     # permissive axis
        "source": "email",
        "source_id": f"src-{title}",
        "tags": [],
        "structured_actions": None,
        "contact_id": None,
        "created_at": datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc),
    }


# --------------------------------------------------------------------------
# New patterns — each hand-picked from the Batch #1 dismissal trail
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Cigar market outlook Q2",                        # cigar market
        "Weekly luxury cigar review",                     # luxury cigar
        "Cigar industry consolidates amid new rules",     # cigar industry
        "Phone scam wave hits German retirees",           # phone scam
        "New phone scams targeting bank customers",       # phone scams
        "Fresh wave of scams hits European banking",      # scam (standalone)
        "SMS scams up 40% in Q1 — new data",              # scams standalone
        "Global fuel price jumps 6% overnight",           # fuel price
        "Austria considers new fuel tax brackets",        # fuel tax
        "Germany energy policy draft leaked",             # energy policy
        "Retail market update — March 2026",              # retail market update
        "European retail-chain turnover softens",         # retail-chain turnover
        "TK Maxx expands German footprint",               # TK Maxx
        "TKMaxx rumored merger with Zalando",             # TKMaxx (no space)
    ],
    ids=[
        "cigar-market", "luxury-cigar", "cigar-industry",
        "phone-scam", "phone-scams", "bare-scam", "bare-scams",
        "fuel-price", "fuel-tax",
        "energy-policy",
        "retail-market-update", "retail-chain-turnover",
        "tk-maxx", "tkmaxx-nospace",
    ],
)
def test_new_stoplist_pattern_matches(title):
    """Each title comes from Batch #1 noise — stop-list must now drop them."""
    alert = _alert(title)
    assert bridge._is_stoplist_noise(alert) is True, (
        f"new stop-list pattern failed to match: {title!r}"
    )
    assert bridge.should_bridge(alert, set(), set()) is False


# --------------------------------------------------------------------------
# Regression guard — the original 11 patterns still match
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Complimentary breakfast at Mandarin",
        "Redeem your bonus today",
        "MEGA SALE 50% off everything",
        "Sotheby's spring auction preview",
        "Stan Manoukian: new wines will be available",
        "Medal Engraving service",
        "Preview ends Friday",
        "Hotel Express Deals — last call",
        "Forbes Under 30 nominations",
        "Wine o'clock starts now",
        "Use code TAKEITOUTSIDE for 10% off",
    ],
    ids=[
        "complimentary", "redeem", "sale",
        "sotheby", "will-be-available", "medal-engraving",
        "preview-ends", "hotel-express", "forbes",
        "wine-oclock", "takeitoutside",
    ],
)
def test_existing_stoplist_patterns_unchanged(title):
    """Additive-only contract — brief §Key Constraints."""
    assert bridge._is_stoplist_noise(_alert(title)) is True


# --------------------------------------------------------------------------
# False-positive guards — common legitimate titles must NOT stop-list
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Hagenauer insolvency settlement hearing set",
        "Oskolkov capital call confirmed",
        "Brisen Hotels quarterly review",
        "MOVIE HMA amendment signed",
        "Aukera term sheet finalized",
    ],
    ids=[
        "hagenauer", "oskolkov", "brisen-hotels",
        "movie-hma", "aukera-term",
    ],
)
def test_legit_matter_titles_do_not_stop_list(title):
    """Matter-relevant titles must not accidentally match the new patterns."""
    assert bridge._is_stoplist_noise(_alert(title)) is False


# --------------------------------------------------------------------------
# MARKETING_NOISE_FILTER_1 — marketing / no-reply / newsletter / survey / promo.
# Real prod alert titles (alerts.status='pending', 2026-06-24); sender + subject
# sit verbatim inside the proactive_pm_sentinel / deadline_cadence title.
# --------------------------------------------------------------------------


# Real prod titles the filter MUST drop.
MARKETING_NOISE_TITLES = [
    "Quiet thread [ao_pm]: email: noreply-eh@highq.com — E+H Rechtsanwälte GmbH Daily site alert",
    "Quiet thread [movie_am]: email: MIO »OBSERVER« — Mandarin Oriental Wien - Ihr »OBSERVER« Pass",
    "Quiet thread [movie_am]: email: Atelier 7 - Brasserie — How was your experience at Atelier 7",
    "Quiet thread [movie_am]: email: MOVIE Reservations — RE: Your upcoming stay at Mandarin Oriental",
    "Due tomorrow: Use code 'FLIKISTART50' for 50% off any monthly plan.",
]


@pytest.mark.parametrize("title", MARKETING_NOISE_TITLES)
def test_marketing_noise_is_stoplisted(title):
    """proactive_pm_sentinel / deadline_cadence marketing rows must be dropped."""
    assert (
        bridge._is_stoplist_noise(
            {"source": "proactive_pm_sentinel", "title": title}
        )
        is True
    ), f"marketing noise failed to stop-list: {title!r}"


# Real matter signal the filter MUST NOT drop (false-positive guards).
MATTER_SIGNAL_TITLES = [
    # genuine inbound prospect replies to MO Residences sales — REAL pipeline
    "Quiet thread [movie_am]: email: Jernej Omahen — Re: Your Interest in Mandarin Oriental Residences, Vienna",
    "Quiet thread [movie_am]: email: Ines Wöckl — Re: Your Interest in Mandarin Oriental Residences, Vienna",
    # real matter correspondence
    "Quiet thread [movie_am]: email: Thomas Bauer — RG7 Schlussabrechnung",
    "Waiting on counterparty [ao_pm]: whatsapp_outbound: Director outbound — Merz deadline confirmed",
    # Brisengroup sales-lead auto-sends — OUT of scope for v1 (Open Item); MUST stay until Director rules
    "Quiet thread [movie_am]: email: Mykola Borsak | Brisengroup — Your Interest in Mandarin Oriental Residences",
]


@pytest.mark.parametrize("title", MATTER_SIGNAL_TITLES)
def test_matter_signal_not_stoplisted(title):
    """Real prospect replies + matter mail + out-of-scope sales rows must pass."""
    assert (
        bridge._is_stoplist_noise(
            {"source": "proactive_pm_sentinel", "title": title}
        )
        is False
    ), f"matter signal wrongly stop-listed: {title!r}"
