"""BRIEF_DOSSIER_ROOM_READ_1 tests.

Two surfaces under test:
  - kbl.curated_wiki_reader.read_room — overview-first, originals listing,
    summaries, curated, touches_siblings expansion (slug-family-gated), caps,
    authoritative vs weak header.
  - orchestrator.research_executor — _get_proposal SELECT includes matter_slug
    (Codex C1), resolver precedence (explicit > alias > metadata > none),
    generic-token alias rejection (C2 regression), authoritative-header gating
    (D2), runtime kill-flag, fault-tolerant prepend.

Pure unit — no DB, no anthropic, no live vault. tmp_path for the vault,
monkeypatched slug_registry, fake psycopg2 cursor for the SELECT assertion.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ─────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    return tmp_path


@pytest.fixture
def stub_registry(monkeypatch):
    """Minimal in-test slug registry covering the brief's marquee cases."""
    import kbl.slug_registry as sr

    canonical = {
        "nvidia": (),
        "nvidia-mohg": ("mohg-nvidia", "nvidia-mandarin"),
        "nvidia-corinthia": ("nvidia-corinthia-pairing",),
        "nvidia-ai-hotel": (),
        "mo-vie-am": ("mohg", "mandarin", "mandarin oriental"),
        "hagenauer-rg7": ("rg7",),
        "ao": ("oskolkov",),
    }

    alias_to_canonical = {}
    for slug, aliases in canonical.items():
        alias_to_canonical[slug] = slug
        for a in aliases:
            alias_to_canonical[a] = slug

    monkeypatch.setattr(sr, "canonical_slugs", lambda: set(canonical.keys()))
    monkeypatch.setattr(
        sr,
        "normalize",
        lambda raw: alias_to_canonical.get(raw.lower().strip()) if isinstance(raw, str) and raw else None,
    )
    monkeypatch.setattr(sr, "is_canonical", lambda s: s in canonical)
    monkeypatch.setattr(
        sr,
        "aliases_for",
        lambda s: list(canonical[s]) if s in canonical else (_ for _ in ()).throw(KeyError(s)),
    )
    return canonical


def _make_room(vault: Path, slug: str, files: dict[str, dict[str, str]]):
    """Build a matter room with subdirs.

    files: {subdir: {filename: body}, ...}. subdir ∈ {00_originals, 02_inventory,
    03_source_summaries, curated, ""} ("" places at room root, e.g. _people.md).
    """
    room = vault / "wiki" / "matters" / slug
    room.mkdir(parents=True, exist_ok=True)
    for sub, group in files.items():
        sub_dir = room / sub if sub else room
        sub_dir.mkdir(parents=True, exist_ok=True)
        for fname, body in group.items():
            (sub_dir / fname).write_text(body, encoding="utf-8")
    return room


# ─────────────────────────────────────────────────
# kbl.curated_wiki_reader.read_room
# ─────────────────────────────────────────────────


def test_read_room_returns_empty_when_room_missing(vault, stub_registry):
    from kbl.curated_wiki_reader import read_room
    assert read_room("nvidia-mohg") == ""


def test_read_room_prefers_overview_when_present(vault, stub_registry):
    from kbl.curated_wiki_reader import read_room, ROOM_HEADER_AUTHORITATIVE
    _make_room(vault, "nvidia", {
        "02_inventory": {
            "2026-05-30-nvidia-room-structure-overview.md":
                "---\nmatter: nvidia\n---\n# Overview\nParent room body.",
        },
        "curated": {"00_overview.md": "should not appear if overview used"},
    })
    out = read_room("nvidia")
    assert ROOM_HEADER_AUTHORITATIVE in out
    assert "Parent room body." in out
    # When overview present, curated/00_overview.md should not be added —
    # overview-first wins for the primary room.
    assert "should not appear if overview used" not in out


def test_read_room_lists_originals_and_reads_summaries_when_no_overview(vault, stub_registry):
    from kbl.curated_wiki_reader import read_room
    _make_room(vault, "nvidia-mohg", {
        "00_originals": {
            "2026-05-22-mohg-bick-ai-opportunities-in-hospitality-concept.pdf": "PDFBODY",
            "2026-05-14-storer-30min.html": "<html/>",
        },
        "03_source_summaries": {
            "bick-concept-summary.md": "Bick concept summary body line",
        },
    })
    out = read_room("nvidia-mohg")
    assert "00_originals/ (listing)" in out
    assert "2026-05-22-mohg-bick-ai-opportunities-in-hospitality-concept.pdf" in out
    # PDF body must NEVER be read — names only.
    assert "PDFBODY" not in out
    assert "Bick concept summary body line" in out


def test_read_room_authoritative_vs_weak_header(vault, stub_registry):
    from kbl.curated_wiki_reader import (
        read_room,
        ROOM_HEADER_AUTHORITATIVE,
        ROOM_HEADER_WEAK,
    )
    _make_room(vault, "nvidia-mohg", {
        "03_source_summaries": {"x.md": "content"},
    })
    auth = read_room("nvidia-mohg", authoritative=True)
    weak = read_room("nvidia-mohg", authoritative=False)
    assert ROOM_HEADER_AUTHORITATIVE in auth
    assert ROOM_HEADER_AUTHORITATIVE not in weak
    assert ROOM_HEADER_WEAK in weak


def test_read_room_expands_touches_siblings_within_family(vault, stub_registry):
    from kbl.curated_wiki_reader import read_room
    # nvidia parent room cites a sibling via touches_siblings.
    _make_room(vault, "nvidia", {
        "02_inventory": {
            "2026-05-30-nvidia-room-structure-overview.md":
                "---\nmatter: nvidia\ntouches_siblings: [nvidia-mohg]\n---\nParent.",
        },
    })
    _make_room(vault, "nvidia-mohg", {
        "curated": {"01_thesis.md": "MOHG thesis sibling body marker"},
    })
    out = read_room("nvidia")
    assert "Parent." in out
    assert "MOHG thesis sibling body marker" in out
    assert "wiki/matters/nvidia-mohg/curated/01_thesis.md" in out


def test_read_room_ignores_touches_siblings_outside_family(vault, stub_registry):
    from kbl.curated_wiki_reader import read_room
    # nvidia overview maliciously references hagenauer-rg7 — family-gate blocks it.
    _make_room(vault, "nvidia", {
        "02_inventory": {
            "2026-05-30-nvidia-room-structure-overview.md":
                "---\nmatter: nvidia\ntouches_siblings: [hagenauer-rg7]\n---\nParent.",
        },
    })
    _make_room(vault, "hagenauer-rg7", {
        "curated": {"01_facts.md": "RG7 LEAK MARKER must not appear"},
    })
    out = read_room("nvidia")
    assert "Parent." in out
    assert "RG7 LEAK MARKER must not appear" not in out


def test_read_room_total_char_cap_enforced(vault, stub_registry):
    from kbl.curated_wiki_reader import read_room
    # 9 files at 5000 chars each → 45000 > total cap (32000 default). Expect
    # truncation marker and final digest under cap.
    files = {f"f{i}.md": "x" * 5000 for i in range(9)}
    _make_room(vault, "nvidia-mohg", {
        "03_source_summaries": files,
    })
    out = read_room("nvidia-mohg")
    # Header + instruction overhead; the digest itself is bounded by cap +
    # per-file cap (8000). Hard ceiling: 9 files * 8000 = 72K BUT total_char_cap
    # gates it at 32K + small overhead.
    assert len(out) < 36000  # generous bound around 32K cap + headers + 8 file rels


def test_read_room_file_cap_enforced(vault, stub_registry):
    from kbl.curated_wiki_reader import read_room
    # 12 files but file_cap default 8 → truncation marker.
    files = {f"f{i}.md": f"body{i}" for i in range(12)}
    _make_room(vault, "nvidia-mohg", {
        "03_source_summaries": files,
    })
    out = read_room("nvidia-mohg")
    assert "room digest truncated" in out


def test_read_room_invalid_slug_returns_empty(vault, stub_registry):
    from kbl.curated_wiki_reader import read_room
    assert read_room("../../../etc/passwd") == ""
    assert read_room("BOGUS_NOT_IN_REGISTRY") == ""


def test_read_room_no_vault_env_returns_empty(monkeypatch, stub_registry):
    from kbl.curated_wiki_reader import read_room
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)
    assert read_room("nvidia-mohg") == ""


# ─────────────────────────────────────────────────
# Resolver — strict precedence
# ─────────────────────────────────────────────────


def test_resolver_explicit_dominates_context_guess(stub_registry):
    """Codex C1 — explicit matter_slug dominates."""
    from orchestrator.research_executor import _resolve_matter_slug
    # context names a different canonical slug, explicit wins.
    slug, path = _resolve_matter_slug(
        proposal_matter_slug="nvidia-mohg",
        subject_name="Raphael Bick",
        context="MOHG mandarin oriental nvidia-corinthia",
    )
    assert slug == "nvidia-mohg"
    assert path == "explicit"


def test_resolver_explicit_normalises_alias_to_canonical(stub_registry):
    from orchestrator.research_executor import _resolve_matter_slug
    # Explicit column with an alias still resolves to canonical authoritatively.
    slug, path = _resolve_matter_slug(
        proposal_matter_slug="mohg-nvidia",
        subject_name="x",
        context="y",
    )
    assert slug == "nvidia-mohg"
    assert path == "explicit"


def test_resolver_rejects_generic_single_token_alias_regression(stub_registry):
    """Codex C2 hard-gate — bare 'MOHG' must NOT resolve to mo-vie-am authoritatively."""
    from orchestrator.research_executor import _resolve_matter_slug
    slug, path = _resolve_matter_slug(
        proposal_matter_slug=None,
        subject_name="MOHG concept paper",
        context="The MOHG / Mandarin Oriental hotel group is an opportunity.",
    )
    # Resolver may return None (no metadata files in this test) or fall back to
    # metadata. What it MUST NOT do: return mo-vie-am with path='alias'
    # (authoritative). 'mohg' and 'mandarin' aliases on mo-vie-am are single-token,
    # explicitly REJECTED by _authoritative_match.
    assert (slug, path) != ("mo-vie-am", "alias")
    assert path != "alias" or slug != "mo-vie-am"


def test_resolver_accepts_composite_alias_authoritative(stub_registry):
    from orchestrator.research_executor import _resolve_matter_slug
    # `mohg-nvidia` is a composite alias of nvidia-mohg — accepted authoritatively.
    slug, path = _resolve_matter_slug(
        proposal_matter_slug=None,
        subject_name="meeting with MOHG team",
        context="Re: mohg-nvidia partnership next steps",
    )
    assert slug == "nvidia-mohg"
    assert path == "alias"


def test_resolver_accepts_exact_canonical_authoritative(stub_registry):
    from orchestrator.research_executor import _resolve_matter_slug
    slug, path = _resolve_matter_slug(
        proposal_matter_slug=None,
        subject_name="x",
        context="See nvidia-corinthia thread",
    )
    assert slug == "nvidia-corinthia"
    assert path == "alias"


def test_resolver_metadata_fallback_is_non_authoritative(vault, stub_registry):
    """C3 — when metadata-only path resolves, caller must use weak header.

    Test surface: resolver returns path='grep' so the caller selects weak header.
    """
    from orchestrator.research_executor import _resolve_matter_slug
    # Build a metadata-only signal: nvidia-mohg's _people.md mentions Bick,
    # no other matter does. No mention of canonical/composite alias in haystack.
    _make_room(vault, "nvidia-mohg", {
        "": {
            "_people.md": "Raphael Bick — Head of Information and AI at MOHG",
            "cortex-config.md": "---\nmatter_slug: nvidia-mohg\nentities: [mohg-raphael-bick]\n---\nbody",
        },
    })
    slug, path = _resolve_matter_slug(
        proposal_matter_slug=None,
        subject_name="Raphael Bick",
        context="MOHG concept paper opportunity in hospitality.",
    )
    assert slug == "nvidia-mohg"
    assert path == "grep"


def test_resolver_metadata_lookup_reads_only_frontmatter_and_people(vault, stub_registry):
    """C3 hard-gate — metadata-only path must NEVER read room bodies.

    Plant a unique sentinel in a room body (curated/03_source_summaries/00_originals)
    such that ONLY a body-scan implementation would let it influence resolution.
    The resolver must remain blind to it.
    """
    from orchestrator.research_executor import _metadata_lookup
    sentinel = "ULTRA_UNIQUE_BODY_SENTINEL_DO_NOT_MATCH_ON_THIS"
    _make_room(vault, "ao", {
        "curated": {"01.md": f"matter discusses {sentinel}"},
        "03_source_summaries": {"02.md": f"see {sentinel}"},
        "00_originals": {"03.txt": sentinel},
        "": {"_people.md": "regular people content (no sentinel here)\n"},
    })
    # If metadata scan were body-reading, "matter discusses {sentinel}" would match.
    candidate = _metadata_lookup(
        subject_name=sentinel,  # subject name itself contains the sentinel
        context="",
    )
    # Must NOT resolve to ao via room-body match — only frontmatter + _people.md.
    # The subject is the sentinel itself; _people.md doesn't contain it, frontmatter
    # of any cortex-config doesn't contain it. So no candidate.
    assert candidate is None


def test_resolver_unresolved_fails_closed(stub_registry):
    from orchestrator.research_executor import _resolve_matter_slug
    slug, path = _resolve_matter_slug(
        proposal_matter_slug=None,
        subject_name="nobody special",
        context="no slug-shaped tokens here",
    )
    assert slug is None
    assert path == "none"


def test_resolver_explicit_invalid_falls_through_to_alias(stub_registry):
    """An explicit column carrying a non-canonical garbage value must not
    poison resolution — fall through to step 2."""
    from orchestrator.research_executor import _resolve_matter_slug
    slug, path = _resolve_matter_slug(
        proposal_matter_slug="not-a-real-slug-xyz",
        subject_name="x",
        context="nvidia-mohg",
    )
    assert slug == "nvidia-mohg"
    assert path == "alias"


# ─────────────────────────────────────────────────
# _get_proposal — SQL assertion (Lesson #42 pattern)
# ─────────────────────────────────────────────────


def test_get_proposal_select_includes_matter_slug(monkeypatch):
    """Codex C1 acceptance — captured SQL must SELECT matter_slug."""
    captured_sql = {}

    class FakeCursor:
        def __init__(self):
            self._row = {
                "id": 1, "subject_name": "Raphael Bick", "subject_type": "person",
                "context": "MOHG context", "specialists": [],
                "trigger_source": None, "trigger_ref": None, "matter_slug": "nvidia-mohg",
            }

        def execute(self, sql, params=None):
            captured_sql["sql"] = sql
            captured_sql["params"] = params

        def fetchone(self):
            return self._row

        def close(self):
            pass

    class FakeConn:
        def cursor(self, **_kw):
            return FakeCursor()

    class FakeStore:
        def _get_conn(self):
            return FakeConn()

        def _put_conn(self, conn):
            pass

    # Pin sys.modules['memory.store_back'] to the real module + patch the real
    # class. An earlier suite test (test_ai_head_weekly_audit) replaces the
    # module with a MagicMock without restoring; _get_proposal re-imports
    # `from memory.store_back import SentinelStoreBack` inside its body, so a
    # dotted-string monkeypatch alone is not enough. conftest.py uses the same
    # _REAL_STORE_BACK_MOD pin for its Tier-B fixture.
    import sys
    import memory.store_back as _sb_mod
    monkeypatch.setitem(sys.modules, "memory.store_back", _sb_mod)
    monkeypatch.setattr(
        _sb_mod.SentinelStoreBack,
        "_get_global_instance",
        classmethod(lambda cls: FakeStore()),
    )

    from orchestrator.research_executor import _get_proposal
    row = _get_proposal(42)
    assert row is not None
    assert row["matter_slug"] == "nvidia-mohg"
    # SQL-string assertion — must SELECT matter_slug (Lesson #42).
    assert "matter_slug" in captured_sql["sql"]
    assert "FROM research_proposals" in captured_sql["sql"]


# ─────────────────────────────────────────────────
# Runtime kill-flag at call-site
# ─────────────────────────────────────────────────


def test_kill_flag_disabled_skips_room_read(monkeypatch, stub_registry):
    """Runtime kill-flag at call-site (NOT module env) — disables injection without redeploy."""
    class FakeStore:
        def get_preferences(self, category=None):
            assert category == "feature_flags"
            return [{"pref_key": "dossier_room_read_enabled", "pref_value": "false"}]

    # Pin sys.modules['memory.store_back'] to the real module + patch the real
    # class. An earlier suite test (test_ai_head_weekly_audit) replaces the
    # module with a MagicMock without restoring; _get_proposal re-imports
    # `from memory.store_back import SentinelStoreBack` inside its body, so a
    # dotted-string monkeypatch alone is not enough. conftest.py uses the same
    # _REAL_STORE_BACK_MOD pin for its Tier-B fixture.
    import sys
    import memory.store_back as _sb_mod
    monkeypatch.setitem(sys.modules, "memory.store_back", _sb_mod)
    monkeypatch.setattr(
        _sb_mod.SentinelStoreBack,
        "_get_global_instance",
        classmethod(lambda cls: FakeStore()),
    )

    # Even with an explicit valid slug, kill-flag short-circuits.
    from orchestrator.research_executor import _resolve_and_prepend_room
    block = _resolve_and_prepend_room("nvidia-mohg", "x", "y")
    assert block == ""


def test_kill_flag_default_enabled_when_pref_missing(monkeypatch, vault, stub_registry):
    """Default = enabled (fail-open). Missing preference must NOT block injection."""
    class FakeStore:
        def get_preferences(self, category=None):
            return []  # no flag

    # Pin sys.modules['memory.store_back'] to the real module + patch the real
    # class. An earlier suite test (test_ai_head_weekly_audit) replaces the
    # module with a MagicMock without restoring; _get_proposal re-imports
    # `from memory.store_back import SentinelStoreBack` inside its body, so a
    # dotted-string monkeypatch alone is not enough. conftest.py uses the same
    # _REAL_STORE_BACK_MOD pin for its Tier-B fixture.
    import sys
    import memory.store_back as _sb_mod
    monkeypatch.setitem(sys.modules, "memory.store_back", _sb_mod)
    monkeypatch.setattr(
        _sb_mod.SentinelStoreBack,
        "_get_global_instance",
        classmethod(lambda cls: FakeStore()),
    )

    _make_room(vault, "nvidia-mohg", {
        "03_source_summaries": {"x.md": "VISIBLE BODY MARKER"},
    })
    from orchestrator.research_executor import _resolve_and_prepend_room
    block = _resolve_and_prepend_room("nvidia-mohg", "x", "y")
    assert "VISIBLE BODY MARKER" in block


def test_kill_flag_fault_tolerant_on_pref_error(monkeypatch, vault, stub_registry):
    """Flag check failure must fail-open (default enabled), not block."""
    class FakeStore:
        def get_preferences(self, category=None):
            raise RuntimeError("DB down")

    # Pin sys.modules['memory.store_back'] to the real module + patch the real
    # class. An earlier suite test (test_ai_head_weekly_audit) replaces the
    # module with a MagicMock without restoring; _get_proposal re-imports
    # `from memory.store_back import SentinelStoreBack` inside its body, so a
    # dotted-string monkeypatch alone is not enough. conftest.py uses the same
    # _REAL_STORE_BACK_MOD pin for its Tier-B fixture.
    import sys
    import memory.store_back as _sb_mod
    monkeypatch.setitem(sys.modules, "memory.store_back", _sb_mod)
    monkeypatch.setattr(
        _sb_mod.SentinelStoreBack,
        "_get_global_instance",
        classmethod(lambda cls: FakeStore()),
    )

    _make_room(vault, "nvidia-mohg", {
        "03_source_summaries": {"y.md": "ANOTHER MARKER"},
    })
    from orchestrator.research_executor import _resolve_and_prepend_room
    block = _resolve_and_prepend_room("nvidia-mohg", "x", "y")
    assert "ANOTHER MARKER" in block


# ─────────────────────────────────────────────────
# Final prompt budget assert (AC7)
# ─────────────────────────────────────────────────


def test_final_prompt_budget_within_cap(vault, stub_registry, monkeypatch):
    """AC7 — `source_text[:3000]` + `context` + digest must stay within budget.

    Tighter: digest alone must respect ROOM_TOTAL_CHAR_CAP (~8K tokens ≈ 32K chars).
    """
    from kbl.curated_wiki_reader import read_room, ROOM_TOTAL_CHAR_CAP
    # Plant 10 oversize files; total cap should clamp.
    _make_room(vault, "nvidia-mohg", {
        "03_source_summaries": {f"x{i}.md": "y" * 10000 for i in range(10)},
    })
    digest = read_room("nvidia-mohg")
    # Generous bound: total cap + headers + path strings. Real ceiling ~33K.
    assert len(digest) < ROOM_TOTAL_CHAR_CAP + 4000
