"""Tests for ``kbl.steps.step6_finalize`` — orchestration, UPSERT,
transaction contract, CHANDA Inv 9 zero-FS-write guarantee."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from kbl import slug_registry
from kbl.exceptions import FinalizationError
from kbl.schemas.silver import MoneyMention, SilverDocument, SilverFrontmatter
from kbl.steps import step6_finalize
from kbl.steps.step6_finalize import (
    FinalizeResult,
    _parse_money_string,
    _serialize_final_markdown,
    _split_frontmatter,
    _title_to_slug,
    build_target_vault_path,
    finalize,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VAULT = FIXTURES / "vault_layer0"

_VALID_SLUG = "ao"
_VALID_SLUG_2 = "movie"


@pytest.fixture(autouse=True)
def _vault(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BAKER_VAULT_PATH", str(VAULT))
    slug_registry.reload()
    yield
    slug_registry.reload()


# --------------------------- draft builders ---------------------------


def _full_synthesis_draft(
    primary: Optional[str] = _VALID_SLUG,
    related: Optional[List[str]] = None,
    vedana: str = "opportunity",
    title: str = "AO Tonbach commit April tranche",
    body: str = "body " * 80,  # 400 chars
    money: Optional[List[str]] = None,
    status: Optional[str] = None,
) -> str:
    related = related or []
    money = money or []
    yaml_lines = [
        "---",
        f"title: {title}",
        "voice: silver",
        "author: pipeline",
        "created: 2026-04-19T12:00:00+00:00",
        "source_id: email:abc123",
        f"primary_matter: {primary if primary else 'null'}",
        f"related_matters: [{', '.join(related)}]",
        f"vedana: {vedana}",
    ]
    if money:
        yaml_lines.append("money_mentioned:")
        for m in money:
            yaml_lines.append(f"  - {m!r}")
    if status:
        yaml_lines.append(f"status: {status}")
    yaml_lines.append("---")
    return "\n".join(yaml_lines) + "\n\n" + body


# --------------------------- _mock_conn ---------------------------


def _mock_conn(
    opus_draft: str = "",
    step_5_decision: str = "full_synthesis",
    triage_score: int = 55,
    triage_confidence: float = 0.72,
    finalize_retry_count: int = 0,
) -> MagicMock:
    """MagicMock conn: first SELECT returns signal_queue row; UPSERT
    tracked via conn._calls. Commit/rollback auto-tracked."""
    conn = MagicMock()
    calls: List[Tuple[str, Any]] = []

    def _make_cursor() -> MagicMock:
        cur = MagicMock()

        def _execute(sql: str, params: Any = None) -> None:
            calls.append((sql, params))
            s = sql.lower()
            if "from signal_queue where id" in s:
                cur.fetchone.return_value = (
                    opus_draft,
                    step_5_decision,
                    triage_score,
                    triage_confidence,
                    finalize_retry_count,
                )
            elif "finalize_retry_count" in s and "returning" in s:
                cur.fetchone.return_value = (finalize_retry_count + 1,)
            else:
                cur.fetchone.return_value = None

        cur.execute.side_effect = _execute
        return cur

    def _cursor() -> MagicMock:
        ctx = MagicMock()
        ctx.__enter__.return_value = _make_cursor()
        ctx.__exit__.return_value = False
        return ctx

    conn.cursor.side_effect = _cursor
    conn._calls = calls
    return conn


def _sql_calls(conn: MagicMock, needle: str) -> List[Tuple[str, Any]]:
    n = needle.lower()
    return [c for c in conn._calls if n in c[0].lower()]


# --------------------------- _title_to_slug ---------------------------


def test_title_to_slug_basic() -> None:
    assert _title_to_slug("AO Tonbach commit") == "ao-tonbach-commit"


def test_title_to_slug_strips_punctuation() -> None:
    assert _title_to_slug("€1.2M!") == "1-2m"


def test_title_to_slug_collapses_spaces_and_dashes() -> None:
    assert _title_to_slug("Hello   world---again") == "hello-world-again"


def test_title_to_slug_empty_fallback() -> None:
    assert _title_to_slug("   ") == "untitled"
    assert _title_to_slug("!!!") == "untitled"


def test_title_to_slug_60_char_cap() -> None:
    long = "ao " * 40
    assert len(_title_to_slug(long)) <= 60


# --------------------------- build_target_vault_path ---------------------------


def test_build_target_vault_path_canonical() -> None:
    fm = SilverFrontmatter(
        title="AO Tonbach commit",
        voice="silver",
        author="pipeline",
        created=datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc),
        source_id="email:1",
        primary_matter=_VALID_SLUG,
        related_matters=[],
        vedana="opportunity",
        triage_score=55,
        triage_confidence=0.7,
    )
    path = build_target_vault_path(fm)
    assert path == "wiki/ao/2026-04-19_ao-tonbach-commit.md"


def test_build_target_vault_path_inbox_for_null_primary() -> None:
    fm = SilverFrontmatter(
        title="Unclassifiable noise",
        voice="silver",
        author="pipeline",
        created=datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc),
        source_id="email:1",
        primary_matter=None,
        related_matters=[],
        vedana="routine",
        triage_score=20,
        triage_confidence=0.3,
        status="stub_inbox",
    )
    path = build_target_vault_path(fm)
    assert path.startswith("wiki/_inbox/")


def test_build_target_vault_path_collision_suffix() -> None:
    fm = SilverFrontmatter(
        title="AO Tonbach commit",
        voice="silver",
        author="pipeline",
        created=datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc),
        source_id="email:1",
        primary_matter=_VALID_SLUG,
        related_matters=[],
        vedana="opportunity",
        triage_score=55,
        triage_confidence=0.7,
    )
    path = build_target_vault_path(fm, source_id_short="abc12")
    assert path.endswith("_abc12.md")


# --------------------------- money parser ---------------------------


def test_parse_money_iso_prefix() -> None:
    mm = _parse_money_string("EUR 1200000")
    assert mm is not None
    assert mm.amount == 1_200_000
    assert mm.currency == "EUR"


def test_parse_money_iso_suffix() -> None:
    mm = _parse_money_string("3000 GBP")
    assert mm is not None
    assert mm.amount == 3000
    assert mm.currency == "GBP"


def test_parse_money_symbol_prefix() -> None:
    mm = _parse_money_string("€1200000")
    assert mm is not None
    assert mm.amount == 1_200_000
    assert mm.currency == "EUR"

    mm2 = _parse_money_string("£3000")
    assert mm2 is not None
    assert mm2.currency == "GBP"


def test_parse_money_shorthand() -> None:
    mm = _parse_money_string("CHF 800K")
    assert mm is not None
    assert mm.amount == 800_000
    assert mm.currency == "CHF"

    mm2 = _parse_money_string("€1.2M")
    assert mm2 is not None
    assert mm2.amount == 1_200_000
    assert mm2.currency == "EUR"


def test_parse_money_thousand_separators() -> None:
    assert _parse_money_string("EUR 1,200,000").amount == 1_200_000  # type: ignore[union-attr]
    assert _parse_money_string("EUR 1_200_000").amount == 1_200_000  # type: ignore[union-attr]


def test_parse_money_unknown_currency_returns_none() -> None:
    assert _parse_money_string("JPY 8000000") is None
    assert _parse_money_string("¥8000000") is None


def test_parse_money_malformed_returns_none() -> None:
    for bad in ("", "not money", "1.2 something", "EUR abc"):
        assert _parse_money_string(bad) is None


def test_parse_money_negative_or_zero_returns_none() -> None:
    assert _parse_money_string("EUR 0") is None


# --------------------------- _split_frontmatter ---------------------------


def test_split_frontmatter_empty_draft_raises() -> None:
    with pytest.raises(FinalizationError, match="empty"):
        _split_frontmatter("")


def test_split_frontmatter_missing_fence_raises() -> None:
    with pytest.raises(FinalizationError, match="frontmatter fence"):
        _split_frontmatter("no frontmatter here")


def test_split_frontmatter_malformed_yaml_raises() -> None:
    with pytest.raises(FinalizationError, match="YAML"):
        _split_frontmatter("---\n: : : bad\n---\nbody\n")


def test_split_frontmatter_non_mapping_rejected() -> None:
    # YAML list at top level, not dict.
    with pytest.raises(FinalizationError, match="mapping"):
        _split_frontmatter("---\n- a\n- b\n---\nbody\n")


# --------------------------- finalize happy path ---------------------------


def test_finalize_full_synthesis_writes_final_and_upserts_cross_links() -> None:
    draft = _full_synthesis_draft(
        primary=_VALID_SLUG,
        related=[_VALID_SLUG_2],
        body="Rich body " * 60,  # ~600 chars
    )
    conn = _mock_conn(opus_draft=draft)

    result = finalize(signal_id=42, conn=conn)

    assert isinstance(result, FinalizeResult)
    assert result.terminal_state == "awaiting_commit"
    assert result.target_vault_path.startswith("wiki/ao/2026-04-19_")
    assert result.cross_link_count == 1

    # final_markdown write.
    writes = _sql_calls(conn, "final_markdown")
    assert any("target_vault_path" in c[0].lower() for c in writes)

    # Cross-link UPSERT was fired for the one related matter.
    upserts = _sql_calls(conn, "insert into kbl_cross_link_queue")
    assert len(upserts) == 1
    assert upserts[0][1][1] == _VALID_SLUG_2


def test_finalize_stub_auto_happy_path_writes_without_cross_links() -> None:
    # Stub body must be ≥300 (R17) and ≤600 (R19).
    draft = _full_synthesis_draft(
        primary=_VALID_SLUG,
        related=[],
        body=("Short stub body — noise-band triage result. " * 7)[:450],
        status="stub_auto",
    )
    conn = _mock_conn(opus_draft=draft, step_5_decision="stub_only")

    result = finalize(signal_id=7, conn=conn)

    assert result.terminal_state == "awaiting_commit"
    assert result.cross_link_count == 0
    upserts = _sql_calls(conn, "insert into kbl_cross_link_queue")
    assert upserts == []


def test_finalize_stub_inbox_null_primary_writes_inbox_path() -> None:
    draft = _full_synthesis_draft(
        primary=None,
        related=[],
        body=("Inbox routed signal — low triage score. " * 8)[:450],
        status="stub_inbox",
    )
    conn = _mock_conn(opus_draft=draft, step_5_decision="skip_inbox")

    result = finalize(signal_id=8, conn=conn)

    assert result.target_vault_path.startswith("wiki/_inbox/")
    assert result.cross_link_count == 0


# --------------------------- state provenance gate ---------------------------


def test_finalize_status_on_full_synthesis_flips_terminal() -> None:
    """Opus emitted status on full_synthesis — pipeline bug, straight
    to finalize_failed terminal (no R3 retry; issue is deterministic)."""
    draft = _full_synthesis_draft(
        primary=_VALID_SLUG,
        related=[],
        body="x" * 400,
        status="stub_auto",  # Opus shouldn't emit this
    )
    conn = _mock_conn(opus_draft=draft, step_5_decision="full_synthesis")

    with pytest.raises(FinalizationError, match="reserved for stub writers"):
        finalize(signal_id=10, conn=conn)

    # Commit-before-raise.
    assert conn.commit.call_count == 1
    terminals = [
        c for c in conn._calls
        if c[1] == ("finalize_failed", 10)
    ]
    assert terminals


def test_finalize_stub_decision_missing_status_flips_terminal() -> None:
    draft = _full_synthesis_draft(
        primary=_VALID_SLUG,
        related=[],
        body="x" * 400,
        status=None,  # stub writer bug — missing status
    )
    conn = _mock_conn(opus_draft=draft, step_5_decision="stub_only")

    with pytest.raises(FinalizationError, match="stub writer should have set"):
        finalize(signal_id=11, conn=conn)

    assert conn.commit.call_count == 1


# --------------------------- validation failure routing ---------------------------


def test_finalize_invalid_vedana_routes_to_opus_failed_with_retry_bump() -> None:
    draft = _full_synthesis_draft(
        primary=_VALID_SLUG, vedana="neutral", body="x" * 400
    )
    conn = _mock_conn(opus_draft=draft, finalize_retry_count=0)

    with pytest.raises(FinalizationError, match="validation failed"):
        finalize(signal_id=12, conn=conn)

    # Retry bump happened; state went to opus_failed (retry 1 < max 3).
    assert conn.commit.call_count == 1
    opus_failed = [c for c in conn._calls if c[1] == ("opus_failed", 12)]
    assert opus_failed


def test_finalize_retry_exhaustion_routes_to_finalize_failed() -> None:
    """On the 3rd retry the state flips to finalize_failed terminal."""
    draft = _full_synthesis_draft(
        primary=_VALID_SLUG, vedana="neutral", body="x" * 400
    )
    conn = _mock_conn(opus_draft=draft, finalize_retry_count=2)

    with pytest.raises(FinalizationError):
        finalize(signal_id=13, conn=conn)

    assert conn.commit.call_count == 1
    terminal = [c for c in conn._calls if c[1] == ("finalize_failed", 13)]
    assert terminal


def test_finalize_missing_frontmatter_fence_routes_to_opus_failed() -> None:
    conn = _mock_conn(opus_draft="no frontmatter here at all")

    with pytest.raises(FinalizationError, match="frontmatter fence"):
        finalize(signal_id=14, conn=conn)

    assert conn.commit.call_count == 1


def test_finalize_missing_signal_row_raises_lookup_error() -> None:
    conn = MagicMock()

    def _make_cursor() -> MagicMock:
        cur = MagicMock()
        cur.execute.side_effect = lambda sql, params=None: None
        cur.fetchone.return_value = None
        return cur

    def _cursor() -> MagicMock:
        ctx = MagicMock()
        ctx.__enter__.return_value = _make_cursor()
        ctx.__exit__.return_value = False
        return ctx

    conn.cursor.side_effect = _cursor

    with pytest.raises(LookupError):
        finalize(signal_id=999, conn=conn)


def test_finalize_null_opus_draft_raises() -> None:
    conn = _mock_conn(opus_draft=None)  # type: ignore[arg-type]

    with pytest.raises(FinalizationError, match="opus_draft_markdown is NULL"):
        finalize(signal_id=15, conn=conn)


# --------------------------- cross-link UPSERT idempotency ---------------------------


def test_cross_link_upsert_fires_on_conflict_do_update() -> None:
    """The UPSERT SQL must contain ``ON CONFLICT ... DO UPDATE`` —
    rerun-safe at the PG layer (Option C idempotency contract)."""
    draft = _full_synthesis_draft(
        primary=_VALID_SLUG,
        related=[_VALID_SLUG_2, "gamma"],
        body="x" * 500,
    )
    conn = _mock_conn(opus_draft=draft)

    finalize(signal_id=20, conn=conn)

    upserts = _sql_calls(conn, "insert into kbl_cross_link_queue")
    assert len(upserts) == 2
    for sql, params in upserts:
        s = sql.lower()
        assert "on conflict (source_signal_id, target_slug)" in s
        assert "do update" in s
        assert "realized_at = null" in s


def test_cross_link_stub_row_contains_signal_id_marker() -> None:
    draft = _full_synthesis_draft(
        primary=_VALID_SLUG,
        related=[_VALID_SLUG_2],
        body="x" * 500,
    )
    conn = _mock_conn(opus_draft=draft)

    finalize(signal_id=21, conn=conn)

    upserts = _sql_calls(conn, "insert into kbl_cross_link_queue")
    _, params = upserts[0]
    stub_row = params[2]
    assert "<!-- stub:signal_id=21 -->" in stub_row
    assert _VALID_SLUG in stub_row  # source path contains primary matter slug


# --------------------------- CHANDA Inv 9: zero FS writes ---------------------------


def test_chanda_inv9_finalize_performs_zero_fs_writes() -> None:
    """Inv 9 (Mac Mini single writer) — Step 6 on Render MUST NOT write
    to the filesystem. Assert ``open``/``tempfile``/``os.rename`` are
    never called during a successful finalize."""
    draft = _full_synthesis_draft(
        primary=_VALID_SLUG,
        related=[_VALID_SLUG_2],
        body="x" * 500,
    )
    conn = _mock_conn(opus_draft=draft)

    # Warm the slug_registry cache BEFORE patching builtins.open so the
    # Pydantic slug validator doesn't try to re-read slugs.yml through
    # a MagicMock (would hang on yaml.safe_load of a mock file).
    slug_registry.active_slugs()

    # Patch a broad set of FS-WRITE surfaces; they should all remain
    # uncalled. ``builtins.open`` is not patched because the cache warm
    # above was the only read path finalize() would hit; open() is too
    # broad a surface to mock globally (stdlib logging, psycopg2, etc.
    # touch it). The file-write primitives below are the actual Inv 9
    # contract.
    with patch("os.rename") as m_rename, \
         patch("os.replace") as m_replace, \
         patch("os.makedirs") as m_makedirs, \
         patch("tempfile.NamedTemporaryFile") as m_ntf, \
         patch("pathlib.Path.write_text") as m_wt, \
         patch("pathlib.Path.write_bytes") as m_wb:
        finalize(signal_id=30, conn=conn)

    assert m_rename.call_count == 0, "os.rename() was called"
    assert m_replace.call_count == 0, "os.replace() was called"
    assert m_makedirs.call_count == 0, "os.makedirs() was called"
    assert m_ntf.call_count == 0, "tempfile.NamedTemporaryFile was called"
    assert m_wt.call_count == 0, "Path.write_text was called"
    assert m_wb.call_count == 0, "Path.write_bytes was called"


def test_chanda_inv9_finalize_never_imports_filesystem_tempfile_helper() -> None:
    """Secondary pin: the step6_finalize module must not expose a helper
    that writes files. Keyword scan its public symbols."""
    # Safety net — if someone adds FS IO later, they'll need to justify
    # it against this test + Inv 9.
    src = (
        Path(step6_finalize.__file__).read_text(encoding="utf-8")
    )
    # Explicit guards on write-path APIs. Read operations elsewhere are
    # fine; this only rejects write-to-vault surfaces.
    forbidden = ("NamedTemporaryFile", ".write_text", ".write_bytes", "os.rename", "os.replace")
    for pat in forbidden:
        assert pat not in src, (
            f"step6_finalize.py contains forbidden FS-write surface '{pat}'"
        )


# --------------------------- CHANDA Inv 1: zero-Gold safe ---------------------------


def test_chanda_inv1_zero_gold_finalizes_without_crash() -> None:
    """Inv 1: a full_synthesis Silver draft with NO prior Gold references
    must finalize cleanly. Step 6 never reads Gold — this is mostly a
    sanity check that no accidental Gold-path dependency crept in."""
    draft = _full_synthesis_draft(
        primary=_VALID_SLUG,
        related=[],  # no cross-links either
        body="First Silver entry for this matter — no prior Gold exists. " * 6,
    )
    conn = _mock_conn(opus_draft=draft)

    result = finalize(signal_id=50, conn=conn)

    assert result.terminal_state == "awaiting_commit"


# --------------------------- CHANDA Inv 8: voice + author structurally pinned ---------------------------


def test_chanda_inv8_final_markdown_always_silver_pipeline() -> None:
    draft = _full_synthesis_draft(
        primary=_VALID_SLUG, related=[], body="x" * 500
    )
    conn = _mock_conn(opus_draft=draft)

    finalize(signal_id=60, conn=conn)

    writes = _sql_calls(conn, "final_markdown")
    # First param is final_markdown.
    final_md = writes[0][1][0]
    assert "voice: silver" in final_md
    assert "author: pipeline" in final_md
    assert "voice: gold" not in final_md
    assert "author: director" not in final_md


# --------------------------- transaction-boundary contract ---------------------------


def test_finalize_happy_path_does_not_commit() -> None:
    draft = _full_synthesis_draft(primary=_VALID_SLUG, related=[], body="x" * 500)
    conn = _mock_conn(opus_draft=draft)

    finalize(signal_id=70, conn=conn)

    # Caller-owns-commit — no internal commit on happy path.
    assert conn.commit.call_count == 0


def test_finalize_error_routing_commits_before_raise() -> None:
    draft = _full_synthesis_draft(
        primary=_VALID_SLUG, vedana="neutral", body="x" * 400
    )
    conn = _mock_conn(opus_draft=draft)

    with pytest.raises(FinalizationError):
        finalize(signal_id=71, conn=conn)

    # Terminal state flip committed before raise (mirrors Step 5 pattern).
    assert conn.commit.call_count == 1


# --------------------------- serializer shape ---------------------------


def test_serialize_final_markdown_ordered_keys() -> None:
    """Field order must match SilverFrontmatter declaration — readers
    (Step 7 + Director's eye) both rely on it."""
    doc = SilverDocument(
        frontmatter=SilverFrontmatter(
            title="Test",
            voice="silver",
            author="pipeline",
            created=datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc),
            source_id="email:1",
            primary_matter=_VALID_SLUG,
            related_matters=[],
            vedana="routine",
            triage_score=50,
            triage_confidence=0.7,
            money_mentioned=[MoneyMention(amount=1000, currency="EUR")],
        ),
        body="x" * 400,
    )
    md = _serialize_final_markdown(doc)
    assert md.startswith("---\ntitle: Test\nvoice: silver\nauthor: pipeline\n")
    assert "triage_score: 50" in md
    assert "money_mentioned" in md
    assert md.endswith("\n")
