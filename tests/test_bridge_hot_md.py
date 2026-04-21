"""Hot.md axis — BRIDGE_HOT_MD_AND_TUNING_1.

Covers:

* ``load_hot_md_patterns`` parse rules (comment / blank / bullet / 4-char floor)
* ``hot_md_match`` substring semantics + case-insensitivity + ordering
* Axis-5 integration through ``should_bridge`` (alert with ``hot_md_match``
  key populated → promotes even when all other axes miss)
* Stop-list wins over hot.md (stop-list still overrides permissive axes)
* Mapper persists ``hot_md_match`` into the signal_queue row
* ``_insert_signal_if_new`` binds the new column into its INSERT
* Vault-mirror miss returns ``[]`` (defensive, non-fatal)

Brief: ``briefs/BRIEF_BRIDGE_HOT_MD_AND_TUNING_1.md``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from kbl.bridge import alerts_to_signal as bridge


# --------------------------------------------------------------------------
# Parser — load_hot_md_patterns
# --------------------------------------------------------------------------


def _fake_read_ops(content: str):
    """Return a patch object that makes load_hot_md_patterns see ``content``."""
    record = {
        "path": "_ops/hot.md",
        "content_utf8": content,
        "bytes": len(content.encode()),
        "truncated": False,
        "sha256": "x" * 64,
        "last_commit_sha": "abc",
    }
    return patch("vault_mirror.read_ops_file", return_value=record)


def test_load_empty_hot_md_returns_empty_list():
    """Empty content → no patterns → axis 5 never fires."""
    with _fake_read_ops(""):
        assert bridge.load_hot_md_patterns() == []


def test_load_comments_and_blank_lines_ignored():
    content = """
    # Hot.md — Director's current-week priorities
    #
    # One priority per line, plain English.

    Hagenauer
    # another comment

    SNB policy
    """
    with _fake_read_ops(content):
        patterns = bridge.load_hot_md_patterns()
    assert patterns == ["Hagenauer", "SNB policy"]


def test_load_strips_leading_bullets():
    content = "- Oskolkov\n* MOVIE Aukera\n  * indented\n-  spaced bullet"
    with _fake_read_ops(content):
        patterns = bridge.load_hot_md_patterns()
    # bullet-stripped and retrimmed
    assert "Oskolkov" in patterns
    assert "MOVIE Aukera" in patterns
    assert "spaced bullet" in patterns
    # only first bullet marker stripped; "indented" comes through after
    # leading whitespace trim then first-char bullet strip
    assert "indented" in patterns


def test_load_enforces_min_pattern_length():
    """Patterns shorter than 4 chars must not load — prevents catastrophic matches."""
    content = "EU\nRE\nok\nHagenauer"
    with _fake_read_ops(content):
        patterns = bridge.load_hot_md_patterns()
    assert patterns == ["Hagenauer"]


def test_load_swallows_vault_mirror_miss():
    """Any VaultPathError / read failure returns ``[]``, never raises."""
    from vault_mirror import VaultPathError

    with patch("vault_mirror.read_ops_file", side_effect=VaultPathError("gone")):
        assert bridge.load_hot_md_patterns() == []


def test_load_swallows_not_found_record():
    """Vault returns error=not_found (scaffold file missing) → [] not raise."""
    with patch(
        "vault_mirror.read_ops_file",
        return_value={"path": "_ops/hot.md", "error": "not_found"},
    ):
        assert bridge.load_hot_md_patterns() == []


def test_load_swallows_truncated_oversize():
    """Vault returns truncated=True (128KB cap) → defensive [] not a partial match."""
    with patch(
        "vault_mirror.read_ops_file",
        return_value={
            "path": "_ops/hot.md",
            "content_utf8": "",
            "truncated": True,
            "bytes": 200000,
        },
    ):
        assert bridge.load_hot_md_patterns() == []


# --------------------------------------------------------------------------
# Matcher — hot_md_match
# --------------------------------------------------------------------------


def _alert(**overrides):
    base = {
        "id": 1,
        "tier": 3,
        "title": "irrelevant title",
        "body": None,
        "matter_slug": None,
        "source": "test_source",
        "source_id": "src-1",
        "tags": [],
        "structured_actions": None,
        "contact_id": None,
        "created_at": datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


def test_match_returns_none_on_empty_patterns():
    assert bridge.hot_md_match(_alert(title="anything"), []) is None


def test_match_substring_case_insensitive():
    alert = _alert(title="Email about Hagenauer settlement", body="see attached")
    assert bridge.hot_md_match(alert, ["Hagenauer"]) == "Hagenauer"
    # lowercase pattern also matches title casing
    assert bridge.hot_md_match(alert, ["hagenauer"]) == "hagenauer"


def test_match_checks_body_as_well_as_title():
    alert = _alert(
        title="generic subject",
        body="Director asked about SNB policy on Monday",
    )
    # "SNB" alone is below the 4-char floor (ignored); the multi-word
    # phrase Director would actually have typed carries through.
    assert bridge.hot_md_match(alert, ["SNB policy"]) == "SNB policy"


def test_match_returns_first_pattern_in_order():
    """Director's ordering of hot.md carries: top-of-file wins ties."""
    alert = _alert(title="Hagenauer update + SNB policy memo", body=None)
    # "Hagenauer" listed first in patterns → wins even though SNB also matches
    assert bridge.hot_md_match(alert, ["Hagenauer", "SNB policy"]) == "Hagenauer"
    # reversed order → SNB wins
    assert bridge.hot_md_match(alert, ["SNB policy", "Hagenauer"]) == "SNB policy"


def test_match_skips_patterns_below_floor():
    """Guard against bad-pattern smuggling (parser already filters, but belt+suspenders)."""
    alert = _alert(title="EU commission report")
    assert bridge.hot_md_match(alert, ["EU"]) is None


def test_match_no_match_returns_none():
    alert = _alert(title="weather update")
    assert bridge.hot_md_match(alert, ["Hagenauer", "SNB"]) is None


def test_match_handles_empty_title_and_body():
    """No haystack → no match, no crash."""
    alert = _alert(title="", body=None)
    assert bridge.hot_md_match(alert, ["Hagenauer"]) is None


# --------------------------------------------------------------------------
# should_bridge integration — axis 5 alongside the other 4
# --------------------------------------------------------------------------


def test_hot_md_hit_alone_passes_filter():
    """Tier 3, no matter, no VIP, no promote-type — hot.md alone is sufficient."""
    alert = _alert(hot_md_match="Hagenauer")
    assert bridge.should_bridge(alert, set(), set()) is True


def test_hot_md_absent_does_not_promote_on_its_own():
    """Without any axis hit, alert is dropped."""
    alert = _alert()
    assert bridge.should_bridge(alert, set(), set()) is False


def test_stoplist_still_overrides_hot_md_match():
    """Brief §1: stop-list overrides permissive axes — hot.md included."""
    alert = _alert(
        title="Complimentary wine event — Hagenauer restaurant",
        hot_md_match="Hagenauer",
    )
    assert bridge.should_bridge(alert, set(), set()) is False


# --------------------------------------------------------------------------
# Mapper + INSERT binding
# --------------------------------------------------------------------------


def test_map_alert_carries_hot_md_match_through():
    alert = _alert(tier=1, matter_slug="movie", hot_md_match="Oskolkov")
    row = bridge.map_alert_to_signal(alert)
    assert row["hot_md_match"] == "Oskolkov"


def test_map_alert_hot_md_match_null_when_absent():
    """Other-axis promotes must leave the column NULL."""
    alert = _alert(tier=1, matter_slug="movie")
    row = bridge.map_alert_to_signal(alert)
    assert row["hot_md_match"] is None


def test_insert_signal_includes_hot_md_match_in_sql_and_params():
    """The INSERT column list and bound params must both carry the new column."""
    captured = {}

    class _Cur:
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

        def fetchone(self):
            return (42,)

    row = bridge.map_alert_to_signal(
        _alert(id=77, tier=1, matter_slug="movie", hot_md_match="Hagenauer")
    )
    assert bridge._insert_signal_if_new(_Cur(), row) is True

    assert "hot_md_match" in captured["sql"]
    # The hot_md_match value is bound as the 10th positional arg
    # (matches the column order in the INSERT). Assert it appears
    # somewhere in the param tuple to avoid coupling tests to bind index.
    assert "Hagenauer" in captured["params"]
