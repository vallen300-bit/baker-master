"""Unit tests for the legacy-slug alert-side fold helpers added by
COCKPIT_SIDEBAR_LEGACY_SLUG_ALIAS_FIX_1."""

import os
import pathlib

# Point slug_registry at the real baker-vault checkout BEFORE importing dashboard.
os.environ.setdefault(
    "BAKER_VAULT_PATH",
    str(pathlib.Path.home() / "baker-vault"),
)

from outputs.dashboard import (  # noqa: E402
    LEGACY_DISPLAY_LABEL_ALIASES,
    _canonicalize_alert_slug,
    _fold_alerts_to_canonical,
)


class TestCanonicalizeAlertSlug:
    def test_registered_alias_resolves_via_tier1(self):
        # ``movie_am`` is an alias of ``mo-vie-am`` in baker-vault/slugs.yml.
        assert _canonicalize_alert_slug("movie_am") == "mo-vie-am"

    def test_canonical_slug_passes_through(self):
        # ``hagenauer-rg7`` is itself canonical; normalize should return it.
        assert _canonicalize_alert_slug("hagenauer-rg7") == "hagenauer-rg7"

    def test_free_text_label_via_tier2_map(self):
        assert _canonicalize_alert_slug("Oskolkov-RG7") == "hagenauer-rg7"

    def test_free_text_label_mandarin_oriental_sales(self):
        assert _canonicalize_alert_slug("Mandarin Oriental Sales") == "mo-vie-exit"

    def test_unknown_string_returns_none(self):
        assert _canonicalize_alert_slug("some-random-string-not-in-any-registry") is None

    def test_ungrouped_sentinel_returns_none(self):
        assert _canonicalize_alert_slug("_ungrouped") is None

    def test_empty_string_returns_none(self):
        assert _canonicalize_alert_slug("") is None

    def test_legacy_display_label_aliases_dict_is_populated(self):
        # Smoke: guard against accidental constant deletion.
        assert "Oskolkov-RG7" in LEGACY_DISPLAY_LABEL_ALIASES
        assert LEGACY_DISPLAY_LABEL_ALIASES["Oskolkov-RG7"] == "hagenauer-rg7"


class TestFoldAlertsToCanonical:
    def test_legacy_alias_folds_to_canonical_bucket(self):
        alerts = {
            "movie_am": {
                "matter_slug": "movie_am",
                "item_count": 136,
                "new_count": 45,
                "worst_tier": 2,
            }
        }
        folded, unmapped = _fold_alerts_to_canonical(alerts)
        assert "mo-vie-am" in folded
        assert folded["mo-vie-am"]["item_count"] == 136
        assert folded["mo-vie-am"]["new_count"] == 45
        assert folded["mo-vie-am"]["worst_tier"] == 2
        assert unmapped == {}

    def test_two_raw_slugs_collapse_to_same_canonical_sum_counts(self):
        # Both ``hagenauer`` (alias) and ``hagenauer-rg7`` (canonical) → hagenauer-rg7.
        alerts = {
            "hagenauer": {
                "matter_slug": "hagenauer",
                "item_count": 5,
                "new_count": 1,
                "worst_tier": 3,
            },
            "hagenauer-rg7": {
                "matter_slug": "hagenauer-rg7",
                "item_count": 10,
                "new_count": 2,
                "worst_tier": 1,
            },
        }
        folded, unmapped = _fold_alerts_to_canonical(alerts)
        assert "hagenauer-rg7" in folded
        assert folded["hagenauer-rg7"]["item_count"] == 15
        assert folded["hagenauer-rg7"]["new_count"] == 3
        assert folded["hagenauer-rg7"]["worst_tier"] == 1  # MIN
        assert unmapped == {}

    def test_unknown_string_routes_to_unmapped(self):
        alerts = {
            "not-a-real-slug-anywhere": {
                "matter_slug": "not-a-real-slug-anywhere",
                "item_count": 3,
                "new_count": 0,
                "worst_tier": None,
            }
        }
        folded, unmapped = _fold_alerts_to_canonical(alerts)
        assert folded == {}
        assert "not-a-real-slug-anywhere" in unmapped

    def test_ungrouped_routes_to_unmapped(self):
        alerts = {
            "_ungrouped": {
                "matter_slug": "_ungrouped",
                "item_count": 28,
                "new_count": 2,
                "worst_tier": 1,
            }
        }
        folded, unmapped = _fold_alerts_to_canonical(alerts)
        assert folded == {}
        assert "_ungrouped" in unmapped
        assert unmapped["_ungrouped"]["item_count"] == 28

    def test_free_text_label_folds_via_tier2_map(self):
        alerts = {
            "Oskolkov-RG7": {
                "matter_slug": "Oskolkov-RG7",
                "item_count": 8,
                "new_count": 2,
                "worst_tier": 2,
            }
        }
        folded, unmapped = _fold_alerts_to_canonical(alerts)
        assert "hagenauer-rg7" in folded
        assert folded["hagenauer-rg7"]["item_count"] == 8
        assert unmapped == {}

    def test_worst_tier_min_handles_none(self):
        alerts = {
            "hagenauer": {
                "matter_slug": "hagenauer",
                "item_count": 1,
                "new_count": 0,
                "worst_tier": None,
            },
            "hagenauer-rg7": {
                "matter_slug": "hagenauer-rg7",
                "item_count": 1,
                "new_count": 0,
                "worst_tier": 2,
            },
        }
        folded, _unmapped = _fold_alerts_to_canonical(alerts)
        # ``None`` from ``hagenauer`` must NOT overwrite ``2`` from canonical row.
        assert folded["hagenauer-rg7"]["worst_tier"] == 2

    def test_mixed_mapped_and_unmapped_partition_correctly(self):
        alerts = {
            "movie_am": {
                "matter_slug": "movie_am",
                "item_count": 100,
                "new_count": 10,
                "worst_tier": 1,
            },
            "totally-unknown": {
                "matter_slug": "totally-unknown",
                "item_count": 5,
                "new_count": 1,
                "worst_tier": 3,
            },
            "_ungrouped": {
                "matter_slug": "_ungrouped",
                "item_count": 7,
                "new_count": 0,
                "worst_tier": None,
            },
        }
        folded, unmapped = _fold_alerts_to_canonical(alerts)
        assert set(folded.keys()) == {"mo-vie-am"}
        assert set(unmapped.keys()) == {"totally-unknown", "_ungrouped"}

    def test_empty_input_returns_two_empty_dicts(self):
        folded, unmapped = _fold_alerts_to_canonical({})
        assert folded == {}
        assert unmapped == {}

    def test_collapsing_fold_does_not_mutate_input_rows(self):
        # Guard: helper must not mutate caller's dicts; tests Tier-1 fold collision.
        row_a = {"matter_slug": "hagenauer", "item_count": 5, "new_count": 1, "worst_tier": 3}
        row_b = {"matter_slug": "hagenauer-rg7", "item_count": 10, "new_count": 2, "worst_tier": 1}
        alerts = {"hagenauer": row_a, "hagenauer-rg7": row_b}
        _fold_alerts_to_canonical(alerts)
        assert row_a["item_count"] == 5
        assert row_b["item_count"] == 10
