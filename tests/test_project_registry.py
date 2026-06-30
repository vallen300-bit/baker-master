"""PROJECT_NUMBER_REGISTRY_1 — live-PG behaviour tests.

Vertical tests for ``kbl.project_registry_store`` — register + the three
resolvers (one hard lane, two soft-lane primitives).

Live-PG via the ``needs_live_pg`` fixture: auto-skips when neither
``TEST_DATABASE_URL`` nor ``NEON_API_KEY`` + ``NEON_PROJECT_ID`` is set
(see ``tests/conftest.py``). CI provisions an ephemeral Neon branch.

Slug validation runs against a fixture vault (``tests/fixtures/vault`` —
alpha/beta/gamma), never the production ``slugs.yml``, mirroring
``tests/test_slug_registry.py``: tests must not couple to the live slug list.
"""
from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

from kbl import slug_registry
from kbl import project_registry_store as reg
from kbl.db import get_conn

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "vault"
CANONICAL_SLUG = "alpha"  # canonical in the fixture vault


@pytest.fixture
def store(needs_live_pg, monkeypatch):
    """Point ``get_conn`` at the live-PG branch + ``slug_registry`` at the
    fixture vault, then hand back a clean ``project_registry`` table.

    The table is net-new (library primitive, no prod caller, no deploy), so a
    full ``DELETE`` is safe and makes the bounded soft-lane scans deterministic.
    """
    monkeypatch.setenv("DATABASE_URL", needs_live_pg)
    monkeypatch.setenv("BAKER_VAULT_PATH", str(FIXTURE_VAULT))
    slug_registry.reload()

    conn = psycopg2.connect(needs_live_pg)
    try:
        reg.ensure_project_registry_table(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM project_registry")
        conn.commit()
    finally:
        conn.close()

    yield reg
    slug_registry.reload()


def _register(**kwargs) -> str:
    """Register through a real short-lived connection (register_project takes
    an explicit conn + does its own commit)."""
    with get_conn() as conn:
        return reg.register_project(conn, **kwargs)


# --- hard lane --------------------------------------------------------------


def test_resolve_project_number_hard_lane(store):
    """A registered number in free text clears to its desk owner."""
    _register(
        project_number="BB-AUK-001",
        desk_owner="baden-baden-desk",
        matter_slug=CANONICAL_SLUG,
    )
    got = reg.resolve_project_number("Re: BB-AUK-001 funding")
    assert got is not None
    assert got["project_number"] == "BB-AUK-001"
    assert got["desk_owner"] == "baden-baden-desk"
    assert got["matter_slug"] == CANONICAL_SLUG


def test_resolve_tolerant_separators(store):
    """'bb auk 001' and 'BB-AUK001' both resolve to the same registered row."""
    _register(
        project_number="BB-AUK-001",
        desk_owner="baden-baden-desk",
        matter_slug=CANONICAL_SLUG,
    )
    spaced = reg.resolve_project_number("update on bb auk 001")
    tight = reg.resolve_project_number("BB-AUK001")
    assert spaced is not None and tight is not None
    assert spaced["project_number"] == tight["project_number"] == "BB-AUK-001"


def test_hard_lane_rejects_unregistered_number_and_sender_only(store):
    """Guardrail (codex #4680): number-alone never clears + sender-only never
    clears the hard lane.

    - A number-shaped string absent from the registry returns None
      (false-positive guard — a regex hit is not a clearance).
    - Text carrying only a known participant's email but NO project number
      returns None from the hard lane (sender-only is forbidden as a clear).
    """
    _register(
        project_number="BB-AUK-001",
        desk_owner="baden-baden-desk",
        matter_slug=CANONICAL_SLUG,
        participants=[{"channel": "email", "value": "balazs@brisengroup.com"}],
    )
    # unregistered number-shaped token -> not cleared
    assert reg.resolve_project_number("ref ZZ-XX-99") is None
    # known sender, no number -> hard lane does not clear from sender alone
    assert reg.resolve_project_number(
        "email from balazs@brisengroup.com with no project number"
    ) is None


# --- register guards --------------------------------------------------------


def test_register_rejects_noncanonical_slug(store):
    """matter_slug must validate via slug_registry.is_canonical (AC5)."""
    with get_conn() as conn:
        with pytest.raises(ValueError):
            reg.register_project(
                conn,
                project_number="BB-AUK-002",
                desk_owner="baden-baden-desk",
                matter_slug="not-a-canonical-slug",
            )


def test_register_rejects_bad_format(store):
    """A project_number missing the matter segment ('BB-001') is rejected."""
    with get_conn() as conn:
        with pytest.raises(ValueError):
            reg.register_project(
                conn,
                project_number="BB-001",
                desk_owner="baden-baden-desk",
                matter_slug=CANONICAL_SLUG,
            )


def test_register_rejects_desk_owner_prefix_mismatch(store):
    """Codex G3 F1: the desk prefix is the routing authority — a desk_owner that
    contradicts the prefix is rejected, never silently stored. A BB number can
    never be owned by a non-BB desk."""
    with get_conn() as conn:
        with pytest.raises(ValueError):
            reg.register_project(
                conn,
                project_number="BB-AUK-001",
                desk_owner="movie-desk",  # contradicts BB prefix
                matter_slug=CANONICAL_SLUG,
            )


# --- soft-lane primitives ---------------------------------------------------


def test_resolve_by_participant_soft(store):
    """Soft-lane signal #1: an active project is found by {channel, value}.
    Returns a list of candidates (never an authoritative clear)."""
    _register(
        project_number="BB-AUK-001",
        desk_owner="baden-baden-desk",
        matter_slug=CANONICAL_SLUG,
        participants=[{"channel": "email", "value": "balazs@brisengroup.com"}],
    )
    hits = reg.resolve_by_participant("email", "balazs@brisengroup.com")
    assert isinstance(hits, list)
    assert any(h["project_number"] == "BB-AUK-001" for h in hits)


def test_resolve_by_alias_soft(store):
    """Soft-lane signal #2: a registered alias appearing as a word in the text
    surfaces the project (one of several signals Box 5 combines)."""
    _register(
        project_number="BB-AUK-001",
        desk_owner="baden-baden-desk",
        matter_slug=CANONICAL_SLUG,
        aliases=["annaberg", "aukera annaberg"],
    )
    hits = reg.resolve_by_alias("notes on Annaberg this week")
    assert isinstance(hits, list)
    assert any(h["project_number"] == "BB-AUK-001" for h in hits)


@pytest.mark.parametrize(
    "text",
    [
        "Annaberg: update",
        "(Annaberg)",
        "Aukera-Annaberg update",
    ],
)
def test_resolve_by_alias_matches_through_punctuation(store, text):
    """Codex G3 F2: alias matching uses a true word boundary, not space-padding,
    so real subjects with punctuation still hit the soft lane (no false holds)."""
    _register(
        project_number="BB-AUK-001",
        desk_owner="baden-baden-desk",
        matter_slug=CANONICAL_SLUG,
        aliases=["annaberg", "aukera annaberg"],
    )
    hits = reg.resolve_by_alias(text)
    assert any(h["project_number"] == "BB-AUK-001" for h in hits), text
