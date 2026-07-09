"""MOVIE_FLIGHT_GATE2_ACTIVATION_1 — two-factor per-matter routing tests.

Slice 1: the PURE resolver core (keyword->matter map + factor-B content set + two-factor
decision). No DB, no I/O. Director ruling #8154 (relayed lead #8154) + sign-off #8165.
"""
from __future__ import annotations

from orchestrator import airport_ticketing_bridge as bridge


# ---- Factor B: content keyword -> matter set ------------------------------------------------

def test_content_matter_set_movie_terms_map_to_movie():
    for term in ("Mandarin Oriental", "MOHG", "mo-vie", "MO Vienna"):
        assert bridge._content_matter_set(term, "") == {"movie"}, term


def test_content_matter_set_aukera_maps_to_aukera():
    assert bridge._content_matter_set("Aukera data room", "") == {"aukera"}


def test_content_matter_set_no_keyword_is_empty():
    assert bridge._content_matter_set("Weekly newsletter", "nothing relevant here") == set()


def test_content_matter_set_both_matters_when_both_present():
    got = bridge._content_matter_set("Mandarin Oriental + Aukera update", "")
    assert got == {"movie", "aukera"}


def test_content_matter_set_riemergasse_is_not_mapped():
    # lead #8165 Q2: riemergasse/rg7 deliberately excluded (building-address collision).
    assert bridge._content_matter_set("Riemergasse 7 works + RG7", "") == set()


# ---- Two-factor resolver --------------------------------------------------------------------

def test_two_factor_corroborated_single_matter_routes():
    assert bridge._two_factor_matter({"movie"}, {"movie"}, participant_fetched=True) == ("movie", "")


def test_two_factor_corroborates_regardless_of_participant_flag():
    # A keyword-lane arrival (participant_fetched=False) from a registered sender still corroborates.
    assert bridge._two_factor_matter({"aukera"}, {"aukera"}, participant_fetched=False) == ("aukera", "")


def test_two_factor_multi_matter_sender_resolved_by_content():
    # Director's Buchwalder example: sender in MOVIE + AO, MOVIE content -> MOVIE.
    assert bridge._two_factor_matter({"movie", "ao"}, {"movie"}, participant_fetched=True) == ("movie", "")


def test_two_factor_identity_only_goes_to_review():
    assert bridge._two_factor_matter({"movie"}, set(), participant_fetched=True) == (
        None,
        bridge.REVIEW_REASON_IDENTITY_ONLY,
    )


def test_two_factor_conflict_goes_to_review():
    # Identity says movie, content says aukera -> disjoint -> conflict.
    assert bridge._two_factor_matter({"movie"}, {"aukera"}, participant_fetched=True) == (
        None,
        bridge.REVIEW_REASON_CONFLICT,
    )


def test_two_factor_multi_match_goes_to_review():
    assert bridge._two_factor_matter({"movie", "aukera"}, {"movie", "aukera"}, participant_fetched=True) == (
        None,
        bridge.REVIEW_REASON_MULTI_MATCH,
    )


def test_two_factor_keyword_lane_no_identity_keeps_global():
    # Unregistered sender (A empty), content matches but no corroboration, not participant-fetched
    # -> (None, "") = today's global-desk behavior. This is the lilienmatt-regression shape.
    assert bridge._two_factor_matter(set(), {"movie"}, participant_fetched=False) == (None, "")


def test_two_factor_nothing_keeps_global():
    assert bridge._two_factor_matter(set(), set(), participant_fetched=False) == (None, "")


def test_review_desk_is_lead_and_not_reserved():
    from orchestrator.dispatcher import RESERVED_RECIPIENTS

    assert bridge._REVIEW_DESK == "lead"
    assert bridge._REVIEW_DESK not in RESERVED_RECIPIENTS
