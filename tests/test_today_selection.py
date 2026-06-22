"""BAKER_DASHBOARD_V2_SELECTION_ENGINE_1: tests for the deterministic Today
selection layer (``orchestrator/today_selection.py``).

Pure in-memory logic — no DB, no model. Proves: trusted-only, untrusted excluded,
deterministic duplicate collapse, lane caps + over-cap accounting, stable
ordering across repeated calls, the documented ranking mapping, stable empty
state, ``limit_per_lane`` bounds, a selected_reason on every visible card, and
the explainable selection-summary accounting identity.

Ranking field mapping under test (brief §"Ranking requirements" -> schema):
  1. priority/critical -> ``state`` (ratified > verified) + ``critical`` lane
  2. due/overdue       -> ``due_at`` ascending, NULLS LAST
  3. confidence        -> ``confidence`` (high > medium > low)
  4. recency           -> ``updated_at`` descending
  5. final tie-break   -> ``id`` descending
"""
from __future__ import annotations

import orchestrator.today_selection as s
import orchestrator.today_v2 as t


def _row(**kw):
    base = dict(
        id=1, state="verified", item_type="deadline", claim="c", why_matters=None,
        next_action=None, owner=None, due_at=None, confidence="high",
        matter_slug="ao", people=[], source_type="email", source_trust="vip",
        source_refs=[], verification_summary="s", counterargument="x",
        dismiss_reason=None, signal_candidate_id=None, created_by="system",
        extraction_model="gemini-2.5-pro", source_model=None,
        created_at="2026-06-22T00:00:00Z", updated_at="2026-06-22T00:00:00Z",
    )
    base.update(kw)
    return base


def _all_cards(payload):
    return [c for lane in t.LANES for c in payload["lanes"][lane]]


def _identity_holds(summary):
    return (
        summary["selected"]
        + summary["duplicates_collapsed"]
        + summary["excluded_unknown_lane"]
        + summary["excluded_over_cap"]
        == summary["total_trusted_considered"]
    )


# --- units -----------------------------------------------------------------

def test_normalize_claim_collapses_whitespace_and_case():
    assert s.normalize_claim("  Pay   the\n SW  spec. ") == "pay the sw spec."
    assert s.normalize_claim("PAY THE SW SPEC.") == "pay the sw spec."
    assert s.normalize_claim(None) == ""
    assert s.normalize_claim("") == ""


def test_dedup_key_prefers_candidate_id_then_claim_tuple():
    assert s.dedup_key(_row(signal_candidate_id=7, claim="anything")) == ("cand", 7)
    k = s.dedup_key(_row(matter_slug="ao", item_type="Deadline", claim=" Pay  SW "))
    assert k == ("claim", "ao", "deadline", "pay sw")


def test_rank_key_is_total_order_and_deterministic():
    # ratified outranks verified regardless of other fields
    rat = s.rank_key(_row(id=1, state="ratified", confidence="low", due_at=None))
    ver = s.rank_key(_row(id=2, state="verified", confidence="high", due_at="2026-06-23T00:00:00Z"))
    assert rat < ver
    # within the same state: earlier due_at wins; None sorts last
    early = s.rank_key(_row(id=1, state="verified", due_at="2026-06-23T00:00:00Z"))
    late = s.rank_key(_row(id=2, state="verified", due_at="2026-07-01T00:00:00Z"))
    none_due = s.rank_key(_row(id=3, state="verified", due_at=None))
    assert early < late < none_due


# --- trusted-only / untrusted excluded -------------------------------------

def test_untrusted_states_excluded_from_selection():
    rows = [
        _row(id=1, state="candidate", item_type="deadline", claim="CAND-LEAK"),
        _row(id=2, state="dismissed", item_type="meeting", claim="DISM-LEAK"),
        _row(id=3, state="verified", item_type="deadline", claim="real promise"),
        _row(id=4, state="ratified", item_type="meeting", claim="real meeting"),
    ]
    payload = s.select_today_payload(rows, limit_per_lane=5)
    claims = [c["claim"] for c in _all_cards(payload)]
    assert "CAND-LEAK" not in claims and "DISM-LEAK" not in claims
    assert payload["counts"]["total"] == 2
    assert payload["selection_summary"]["total_trusted_considered"] == 2


# --- duplicate collapse ----------------------------------------------------

def test_duplicate_collapse_by_candidate_id():
    rows = [
        _row(id=1, state="verified", signal_candidate_id=99, claim="v copy"),
        _row(id=2, state="ratified", signal_candidate_id=99, claim="r copy"),
    ]
    payload = s.select_today_payload(rows, limit_per_lane=5)
    cards = payload["lanes"]["promises"]
    # one canonical survives; ratified is the better-ranked winner
    assert len(cards) == 1
    assert cards[0]["id"] == 2 and cards[0]["state"] == "ratified"
    assert cards[0]["duplicate_count"] == 1
    assert payload["duplicates_collapsed"] == 1
    assert "+1 similar" in cards[0]["selected_reason"]


def test_duplicate_collapse_by_normalized_claim():
    rows = [
        _row(id=1, state="verified", matter_slug="ao", item_type="deadline",
             claim="Pay the SW spec."),
        _row(id=2, state="verified", matter_slug="ao", item_type="deadline",
             claim="  pay   the sw  spec.  "),  # same after normalization
        _row(id=3, state="verified", matter_slug="ao", item_type="deadline",
             claim="A different promise"),
    ]
    payload = s.select_today_payload(rows, limit_per_lane=5)
    assert payload["counts"]["promises"] == 2
    assert payload["duplicates_collapsed"] == 1
    assert _identity_holds(payload["selection_summary"])


def test_distinct_matter_does_not_collapse():
    rows = [
        _row(id=1, matter_slug="ao", item_type="deadline", claim="same text"),
        _row(id=2, matter_slug="movie", item_type="deadline", claim="same text"),
    ]
    payload = s.select_today_payload(rows, limit_per_lane=5)
    assert payload["counts"]["promises"] == 2
    assert payload["duplicates_collapsed"] == 0


# --- lane caps + over-cap accounting ---------------------------------------

def test_lane_cap_enforced_and_over_cap_counted():
    rows = [_row(id=i, state="verified", item_type="deadline", claim=f"p{i}")
            for i in range(7)]
    payload = s.select_today_payload(rows, limit_per_lane=5)
    assert payload["counts"]["promises"] == 5
    summ = payload["selection_summary"]
    assert summ["excluded_over_cap"] == 2
    assert summ["excluded_unknown_lane"] == 0
    assert payload["excluded_count"] == 2
    assert _identity_holds(summ)


def test_unknown_lane_counted_excluded():
    rows = [
        _row(id=1, state="verified", item_type="deadline"),
        _row(id=2, state="verified", item_type="weird_unmapped_type"),
    ]
    payload = s.select_today_payload(rows, limit_per_lane=5)
    assert payload["counts"]["excluded"] == 1
    assert payload["selection_summary"]["excluded_unknown_lane"] == 1
    assert _identity_holds(payload["selection_summary"])


# --- ranking / ordering ----------------------------------------------------

def test_within_lane_ranking_order():
    rows = [
        _row(id=1, state="verified", item_type="deadline", claim="A",
             due_at="2026-07-01T00:00:00Z", confidence="high"),
        _row(id=2, state="ratified", item_type="deadline", claim="B",
             due_at=None, confidence="low"),
        _row(id=3, state="verified", item_type="deadline", claim="C",
             due_at="2026-06-25T00:00:00Z", confidence="high"),
    ]
    payload = s.select_today_payload(rows, limit_per_lane=5)
    order = [c["claim"] for c in payload["lanes"]["promises"]]
    # ratified first (B); then verified by earlier due (C before A)
    assert order == ["B", "C", "A"]
    # rank is 1-based within the lane
    assert [c["rank"] for c in payload["lanes"]["promises"]] == [1, 2, 3]


def test_id_is_final_tiebreaker():
    # identical state/due/confidence/updated -> higher id ranks first
    rows = [
        _row(id=5, state="verified", item_type="deadline", claim="low-id"),
        _row(id=9, state="verified", item_type="deadline", claim="high-id"),
    ]
    payload = s.select_today_payload(rows, limit_per_lane=5)
    order = [c["id"] for c in payload["lanes"]["promises"]]
    assert order == [9, 5]


def test_ordering_stable_across_repeated_calls():
    rows = [_row(id=i, state="verified", item_type="deadline", claim=f"p{i}",
                 due_at=f"2026-06-{10 + (i % 5):02d}T00:00:00Z")
            for i in range(12)]
    a = s.select_today_payload(rows, limit_per_lane=5)
    b = s.select_today_payload(list(reversed(rows)), limit_per_lane=5)
    assert [c["id"] for c in a["lanes"]["promises"]] == [c["id"] for c in b["lanes"]["promises"]]


# --- empty / bounds / reason -----------------------------------------------

def test_empty_state_stable_shape():
    payload = s.select_today_payload([], limit_per_lane=5)
    assert payload["status"] == "ok"
    assert payload["lanes"] == {lane: [] for lane in t.LANES}
    assert payload["counts"]["total"] == 0
    assert payload["duplicates_collapsed"] == 0
    assert payload["excluded_count"] == 0
    summ = payload["selection_summary"]
    assert summ["total_trusted_considered"] == 0 and summ["selected"] == 0
    assert summ["limit_per_lane"] == 5
    assert _identity_holds(summ)


def test_limit_per_lane_bounds_respected():
    rows = [_row(id=i, state="verified", item_type="deadline", claim=f"p{i}")
            for i in range(25)]
    # invalid -> default 5
    p0 = s.select_today_payload(rows, limit_per_lane=0)
    assert p0["counts"]["promises"] == 5
    assert p0["selection_summary"]["limit_per_lane"] == 5
    # absurd -> clamped to 20
    p999 = s.select_today_payload(rows, limit_per_lane=999)
    assert p999["counts"]["promises"] == 20
    assert p999["selection_summary"]["limit_per_lane"] == 20


def test_every_visible_card_has_selected_reason():
    rows = [
        _row(id=1, state="ratified", item_type="critical", claim="crit",
             due_at="2026-06-25T00:00:00Z", confidence="high"),
        _row(id=2, state="verified", item_type="meeting", claim="mtg", confidence="medium"),
        _row(id=3, state="verified", item_type="travel", claim="trip", due_at=None,
             confidence=None),
    ]
    payload = s.select_today_payload(rows, limit_per_lane=5)
    for card in _all_cards(payload):
        assert card.get("selected_reason"), f"card {card.get('id')} missing reason"
        assert card["selected_reason"].startswith(("Ratified", "Verified"))
    crit = payload["lanes"]["critical"][0]
    assert "due 2026-06-25" in crit["selected_reason"]
    assert "high confidence" in crit["selected_reason"]


def test_full_accounting_identity_mixed():
    rows = [
        # 2 collapse into 1 (same candidate)
        _row(id=1, state="verified", signal_candidate_id=42, item_type="deadline", claim="d1"),
        _row(id=2, state="verified", signal_candidate_id=42, item_type="deadline", claim="d2"),
        # 3 more distinct promises -> with cap 2, 2 selected + over-cap
        _row(id=3, state="verified", item_type="deadline", claim="d3"),
        _row(id=4, state="verified", item_type="deadline", claim="d4"),
        # unknown lane
        _row(id=5, state="verified", item_type="mystery", claim="m1"),
        # untrusted (not considered)
        _row(id=6, state="candidate", item_type="deadline", claim="cand"),
    ]
    payload = s.select_today_payload(rows, limit_per_lane=2)
    summ = payload["selection_summary"]
    assert summ["total_trusted_considered"] == 5  # id 6 excluded as untrusted
    assert summ["duplicates_collapsed"] == 1
    assert summ["excluded_unknown_lane"] == 1
    assert _identity_holds(summ)
    assert payload["excluded_count"] == summ["excluded_unknown_lane"] + summ["excluded_over_cap"]
