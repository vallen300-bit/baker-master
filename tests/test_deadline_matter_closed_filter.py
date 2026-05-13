"""DEADLINE_SIGNAL_HYGIENE_1 Scope B tests — matter-closed JOIN filter.

These tests assert the SQL surface of the filter rather than executing it
against live Postgres: we check that the active-deadline queries in
vault_scanner.py + outputs/dashboard.py + orchestrator/* contain the
required LEFT JOIN matter_registry + triple-OR guard.

The brief's required behavioural cases (closed → excluded, active → kept,
NULL slug → kept) are encoded as predicate tests against the SQL string.

T1. Closed-matter deadline excluded — query has `m.status = 'active'` arm
T2. Active-matter deadline kept — query has `m.status IS NULL` arm (covers
    the case where the matter_registry row is missing entirely)
T3. Unclassified (matter_slug IS NULL) deadline kept — `d.matter_slug IS NULL` arm
T4. Multi-site coverage — count of LEFT JOIN sites matches expectation
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (_REPO / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# T1+T2+T3 — every active-deadline surface query has the triple-OR guard
# ---------------------------------------------------------------------------


REQUIRED_SITES = [
    "triggers/vault_scanner.py",
    "outputs/dashboard.py",
    "triggers/briefing_trigger.py",
    "triggers/calendar_trigger.py",
    "orchestrator/chain_runner.py",
    "orchestrator/initiative_engine.py",
    "orchestrator/obligation_generator.py",
    "orchestrator/risk_detector.py",
    "orchestrator/weekly_digest.py",
]


def test_triple_or_guard_present_in_every_filtered_site():
    """The matter-closed exclusion requires the triple-OR. Each site that
    we marked as 'current attention' must carry that guard."""
    expected = "d.matter_slug IS NULL OR m.status IS NULL OR m.status = 'active'"
    for rel in REQUIRED_SITES:
        body = _read(rel)
        assert expected in body, (
            f"{rel}: missing matter-closed triple-OR guard. The query is the "
            f"surface that leaks Cupial-like closed-matter deadlines into the "
            f"active list."
        )


def test_left_join_matter_registry_present_in_every_filtered_site():
    expected_join = "LEFT JOIN matter_registry m"
    for rel in REQUIRED_SITES:
        body = _read(rel)
        assert expected_join in body, (
            f"{rel}: missing LEFT JOIN matter_registry m"
        )


def test_join_predicate_uses_lower_replace():
    """matter_registry.matter_name is 'Cupial'; deadlines.matter_slug is
    'cupial'. The JOIN must normalize both via LOWER(REPLACE) — anchored
    in the existing dashboard precedent at line 3961."""
    expected_predicate = (
        "LOWER(REPLACE(m.matter_name, ' ', '-')) = LOWER(d.matter_slug)"
    )
    for rel in REQUIRED_SITES:
        body = _read(rel)
        assert expected_predicate in body, (
            f"{rel}: JOIN predicate must use LOWER(REPLACE(...)) to match "
            f"display-case vs slug-case."
        )


# ---------------------------------------------------------------------------
# T4 — vault_scanner has 2 filtered query sites (per brief)
# ---------------------------------------------------------------------------


def test_vault_scanner_has_two_filtered_sites():
    """Brief §B1 names two sites in vault_scanner: the per-desk DM query
    and the broader scan. Both must carry the filter."""
    body = _read("triggers/vault_scanner.py")
    assert body.count("LEFT JOIN matter_registry m") >= 2, (
        "vault_scanner.py must filter both active-deadline query sites"
    )


# ---------------------------------------------------------------------------
# T5 — dashboard.py has filter on every active-deadline current-attention site
# ---------------------------------------------------------------------------


def test_dashboard_active_surface_queries_all_filtered():
    """Each `FROM deadlines d` (filtered alias form) implies the filter
    was applied. Count must be >=5 (cockpit count + brief + overdue +
    travel + dossier obligations + trip + AO pack)."""
    body = _read("outputs/dashboard.py")
    filtered_count = body.count("LEFT JOIN matter_registry m")
    assert filtered_count >= 5, (
        f"dashboard.py expected >=5 current-attention filter sites; "
        f"found {filtered_count}"
    )
