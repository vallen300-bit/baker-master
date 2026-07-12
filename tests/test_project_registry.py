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


def test_register_rejects_trailing_junk(store):
    """Codex G3 F3: register uses fullmatch — trailing text is rejected, not
    silently stored (which would persist a row the hard lane can never reach)."""
    with get_conn() as conn:
        with pytest.raises(ValueError):
            reg.register_project(
                conn,
                project_number="BB-AUK-001 extra",
                desk_owner="baden-baden-desk",
                matter_slug=CANONICAL_SLUG,
            )


def test_register_canonicalizes_and_round_trips(store):
    """Codex G3 F3: stored display form + match_key are canonicalized from the
    matched groups, so a tolerant input ('BB-AUK001') round-trips — the hard lane
    resolves it via the canonical 'BB-AUK-001'."""
    returned = _register(
        project_number="BB-AUK001",
        desk_owner="baden-baden-desk",
        matter_slug=CANONICAL_SLUG,
    )
    assert returned == "BB-AUK-001"
    got = reg.resolve_project_number("re: BB-AUK-001 update")
    assert got is not None
    assert got["project_number"] == "BB-AUK-001"


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


# --- F4: deterministic text-order hard lane ---------------------------------


def test_resolve_project_number_text_order_deterministic(store):
    """Codex G3 F4: with several registered numbers in one text, the
    earliest-occurring one wins — deterministically, regardless of which DB row
    the planner would return first."""
    _register(
        project_number="AO-MOV-002", desk_owner="ao-desk", matter_slug=CANONICAL_SLUG,
    )
    _register(
        project_number="BB-AUK-001", desk_owner="baden-baden-desk",
        matter_slug=CANONICAL_SLUG,
    )
    fwd = reg.resolve_project_number("AO-MOV-002 then BB-AUK-001")
    rev = reg.resolve_project_number("BB-AUK-001 then AO-MOV-002")
    assert fwd is not None and fwd["project_number"] == "AO-MOV-002"
    assert rev is not None and rev["project_number"] == "BB-AUK-001"


def test_resolve_project_number_returns_first_registered_not_first_regex_hit(store):
    """Codex G3 F4: an earlier unregistered regex hit is skipped — the first
    *registered* match in text order is returned, not merely the first regex hit."""
    _register(
        project_number="BB-AUK-001", desk_owner="baden-baden-desk",
        matter_slug=CANONICAL_SLUG,
    )
    got = reg.resolve_project_number("ref ZZ-XX-99 see BB-AUK-001")
    assert got is not None and got["project_number"] == "BB-AUK-001"


# --- self-audit regressions (codex G3 re-gate#2) ----------------------------


def test_resolvers_exclude_retired_rows(store):
    """Self-audit: a row flipped to status='retired' is excluded by all three
    resolvers (the status='active' filter holds across hard + soft lanes)."""
    _register(
        project_number="BB-AUK-001", desk_owner="baden-baden-desk",
        matter_slug=CANONICAL_SLUG,
        participants=[{"channel": "email", "value": "x@brisengroup.com"}],
        aliases=["annaberg"],
    )
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE project_registry SET status = 'retired' "
                "WHERE project_number = %s",
                ("BB-AUK-001",),
            )
        conn.commit()
    assert reg.resolve_project_number("re: BB-AUK-001 update") is None
    assert reg.resolve_by_participant("email", "x@brisengroup.com") == []
    assert reg.resolve_by_alias("notes on annaberg") == []


def test_resolve_by_participant_deterministic_order(store):
    """Self-audit (soft-lane ordering): multiple projects sharing a participant
    come back in a deterministic order (ORDER BY project_number)."""
    shared = [{"channel": "email", "value": "shared@brisengroup.com"}]
    _register(
        project_number="BB-AUK-001", desk_owner="baden-baden-desk",
        matter_slug=CANONICAL_SLUG, participants=shared,
    )
    _register(
        project_number="AO-MOV-002", desk_owner="ao-desk",
        matter_slug=CANONICAL_SLUG, participants=shared,
    )
    nums = [h["project_number"] for h in
            reg.resolve_by_participant("email", "shared@brisengroup.com")]
    assert nums == ["AO-MOV-002", "BB-AUK-001"]  # sorted, deterministic


# --- BOX5_SCHEMA_FOUNDATION_1: BB pilot seed -------------------------------


def test_seed_bb_pilot_registry_constants_consistent():
    """Pure check: the seed's desk_owner must equal the desk derived from its
    project number's prefix (BB -> baden-baden-desk), and its matter_slug must be
    the Director-ratified canonical 'aukera' (BRIEF-D correction; 'annaberg' stays
    a human alias only). Catches a silent drift between the seed constants and
    #439's DESK_CODES authority."""
    import scripts.seed_bb_pilot_registry as seed
    assert seed.PROJECT_NUMBER == "BB-AUK-001"
    assert seed.MATTER_SLUG == "aukera"
    prefix = seed.PROJECT_NUMBER.split("-", 1)[0]
    assert prefix == "BB"
    assert seed.DESK_OWNER == reg.DESK_CODES[prefix] == "baden-baden-desk"


def test_fa_desk_code_routes_to_arm():
    """FA (Flight Academy) desk-code registration — FA-ACA-### numbers route to the
    ARM Chief-Pilot desk. Guards the DESK_CODES authority for the Flight Academy
    install (vault side landed @bacd50f; slugs.yml has flight-academy @ v24)."""
    assert reg.DESK_CODES["FA"] == "arm"
    prefix = "FA-ACA-001".split("-", 1)[0]
    assert prefix == "FA"
    assert reg.DESK_CODES[prefix] == "arm"


# --- BOX5_HARD_FAST_LANE_1: extract_project_codes (pure regex, NO live PG) -----


def test_extract_project_codes_distinct_order():
    """Case 1 — DISTINCT valid-shaped codes in first-occurrence text order."""
    assert reg.extract_project_codes("AO-MOV-002 then BB-AUK-001") == [
        "AO-MOV-002", "BB-AUK-001",
    ]
    assert reg.extract_project_codes("ref ZZ-XX-99 see BB-AUK-001") == [
        "ZZ-XX-99", "BB-AUK-001",
    ]
    assert reg.extract_project_codes("") == []
    assert reg.extract_project_codes("no code here at all") == []


def test_extract_project_codes_dedup_and_conflict_count():
    """Case 2 — tolerant separators collapse to one canonical code; two DISTINCT
    codes are the >1 conflict trigger the hard lane refuses to fast-board."""
    # 'bb auk 001' and 'BB-AUK001' are the same code -> single entry.
    assert reg.extract_project_codes("bb auk 001 and BB-AUK001") == ["BB-AUK-001"]
    # two distinct codes -> len(set)>1 -> conflict gate fires.
    assert len(set(reg.extract_project_codes("AO-MOV-002 and BB-AUK-001"))) == 2


def test_seed_mechanism_one_row_desk_routing_idempotent(store):
    """Mirror of the seed's register_project call (the fixture-vault canonical slug
    stands in for the real 'annaberg' — same validation path, CI-safe). Proves
    done-rubric #8 structurally: one BBAUK001 row, BB desk routing, idempotent."""
    for _ in range(2):  # second run upserts -> still exactly one row
        _register(
            project_number="BB-AUK-001",
            desk_owner="baden-baden-desk",
            matter_slug=CANONICAL_SLUG,
            aliases=["annaberg", "aukera annaberg"],
        )
    got = reg.resolve_project_number("re: BB-AUK-001 funding")
    assert got is not None
    assert got["project_number"] == "BB-AUK-001"
    assert got["desk_code"] == "BB"
    assert got["desk_owner"] == "baden-baden-desk"
    assert got["status"] == "active"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM project_registry WHERE match_key = %s",
                ("BBAUK001",),
            )
            assert cur.fetchone()[0] == 1
