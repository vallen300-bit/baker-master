"""Tests for ``kbl.schemas.silver`` — Pydantic validation rules R1-R21."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
from pydantic import ValidationError

from kbl import slug_registry
from kbl.schemas.silver import (
    CrossLinkStub,
    MoneyMention,
    SilverDocument,
    SilverFrontmatter,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VAULT = FIXTURES / "vault_layer0"

_VALID_SLUG = "ao"
_VALID_SLUG_2 = "movie"
_VALID_SLUG_3 = "gamma"


@pytest.fixture(autouse=True)
def _vault(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BAKER_VAULT_PATH", str(VAULT))
    slug_registry.reload()
    yield
    slug_registry.reload()


def _utc(year: int = 2026, month: int = 4, day: int = 19, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)


def _base_fm_dict(**overrides: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = dict(
        title="Sample Silver entry",
        voice="silver",
        author="pipeline",
        created=_utc(),
        source_id="email:abc123",
        primary_matter=_VALID_SLUG,
        related_matters=[],
        vedana="routine",
        triage_score=50,
        triage_confidence=0.7,
    )
    d.update(overrides)
    return d


def _base_body(n: int = 500) -> str:
    return "x" * n


# --------------------------- happy path ---------------------------


def test_frontmatter_minimal_valid_parses() -> None:
    fm = SilverFrontmatter(**_base_fm_dict())
    assert fm.title == "Sample Silver entry"
    assert fm.voice == "silver"
    assert fm.author == "pipeline"
    assert fm.primary_matter == _VALID_SLUG


def test_document_minimal_valid_parses() -> None:
    doc = SilverDocument(
        frontmatter=SilverFrontmatter(**_base_fm_dict()),
        body=_base_body(),
    )
    assert len(doc.body) == 500


# --------------------------- R1 + R2: author + voice literals ---------------------------


def test_r1_author_director_rejected_structurally() -> None:
    """CHANDA Inv 4: Pydantic structurally rejects ``author: director``."""
    with pytest.raises(ValidationError, match="author"):
        SilverFrontmatter(**_base_fm_dict(author="director"))


def test_r2_voice_gold_rejected_structurally() -> None:
    """CHANDA Inv 8: Pydantic structurally rejects ``voice: gold``."""
    with pytest.raises(ValidationError, match="voice"):
        SilverFrontmatter(**_base_fm_dict(voice="gold"))


# --------------------------- R3 + R4: slug membership ---------------------------


def test_r3_primary_matter_unknown_slug_rejected() -> None:
    with pytest.raises(ValidationError, match="ACTIVE"):
        SilverFrontmatter(**_base_fm_dict(primary_matter="unknown-slug-xyz"))


def test_r3_primary_matter_shape_violation_rejected() -> None:
    """Regex rejects uppercase / trailing-dash shapes before registry check."""
    with pytest.raises(ValidationError):
        SilverFrontmatter(**_base_fm_dict(primary_matter="BADSLUG"))


def test_r3_primary_matter_none_allowed() -> None:
    """Null primary_matter is legitimate on stub_inbox path."""
    fm = SilverFrontmatter(
        **_base_fm_dict(
            primary_matter=None,
            related_matters=[],
            status="stub_inbox",
        )
    )
    assert fm.primary_matter is None


def test_r4_related_matters_unknown_slug_rejected() -> None:
    with pytest.raises(ValidationError, match="ACTIVE"):
        SilverFrontmatter(
            **_base_fm_dict(related_matters=[_VALID_SLUG_2, "not-a-slug"])
        )


# --------------------------- R5 + R6: primary in related ---------------------------


def test_r5_primary_matter_in_related_rejected() -> None:
    with pytest.raises(ValidationError, match="primary_matter"):
        SilverFrontmatter(
            **_base_fm_dict(primary_matter=_VALID_SLUG, related_matters=[_VALID_SLUG])
        )


def test_r6_related_matters_dedup_preserves_order() -> None:
    fm = SilverFrontmatter(
        **_base_fm_dict(
            primary_matter=_VALID_SLUG,
            related_matters=[_VALID_SLUG_2, _VALID_SLUG_3, _VALID_SLUG_2],
        )
    )
    assert fm.related_matters == [_VALID_SLUG_2, _VALID_SLUG_3]


# --------------------------- R7: null primary + empty related ---------------------------


def test_r7_null_primary_with_nonempty_related_rejected() -> None:
    with pytest.raises(ValidationError, match="null-matter"):
        SilverFrontmatter(
            **_base_fm_dict(primary_matter=None, related_matters=[_VALID_SLUG_2])
        )


# --------------------------- R8: vedana strict ---------------------------


def test_r8_vedana_outside_3_values_rejected() -> None:
    for bad in ("neutral", "unknown", "alert", ""):
        with pytest.raises(ValidationError, match="vedana"):
            SilverFrontmatter(**_base_fm_dict(vedana=bad))


# --------------------------- R9 + R10: triage bounds ---------------------------


def test_r9_triage_score_out_of_bounds_rejected() -> None:
    for bad in (-1, 101, 150):
        with pytest.raises(ValidationError, match="triage_score"):
            SilverFrontmatter(**_base_fm_dict(triage_score=bad))


def test_r10_triage_confidence_out_of_bounds_rejected() -> None:
    for bad in (-0.01, 1.01, 2.0):
        with pytest.raises(ValidationError, match="triage_confidence"):
            SilverFrontmatter(**_base_fm_dict(triage_confidence=bad))


# --------------------------- R11: created UTC ---------------------------


def test_r11_created_naive_rejected() -> None:
    naive = datetime(2026, 4, 19, 12, 0, 0)
    with pytest.raises(ValidationError, match="timezone"):
        SilverFrontmatter(**_base_fm_dict(created=naive))


def test_r11_created_non_utc_rejected() -> None:
    plus_2 = datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    with pytest.raises(ValidationError, match="UTC"):
        SilverFrontmatter(**_base_fm_dict(created=plus_2))


# --------------------------- R12: title shape ---------------------------


def test_r12_title_empty_rejected() -> None:
    with pytest.raises(ValidationError, match="empty"):
        SilverFrontmatter(**_base_fm_dict(title="   "))


def test_r12_title_over_160_chars_rejected() -> None:
    with pytest.raises(ValidationError, match="too long"):
        SilverFrontmatter(**_base_fm_dict(title="A" * 161))


def test_r12_title_trailing_period_rejected() -> None:
    with pytest.raises(ValidationError, match="period"):
        SilverFrontmatter(**_base_fm_dict(title="Some title."))


def test_r12_title_at_160_boundary_accepted() -> None:
    fm = SilverFrontmatter(**_base_fm_dict(title="A" * 160))
    assert len(fm.title) == 160


# --------------------------- R13: deadline ---------------------------


def test_r13_deadline_valid_iso_date_accepted() -> None:
    fm = SilverFrontmatter(**_base_fm_dict(deadline="2026-05-31"))
    assert fm.deadline == "2026-05-31"


def test_r13_deadline_malformed_rejected() -> None:
    # strptime accepts '2026-5-1' on Python — use unambiguously bad forms.
    for bad in ("5/31/2026", "May 31 2026", "2026-13-01", "not-a-date"):
        with pytest.raises(ValidationError, match="YYYY-MM-DD"):
            SilverFrontmatter(**_base_fm_dict(deadline=bad))


# --------------------------- STEP6_VALIDATION_HOTFIX_1: YAML scalar coercion ---------------------------
# Rationale: YAML 1.1 auto-parses unquoted ISO-date scalars as ``datetime.date``
# and bare-digit scalars as ``int``. ``SilverFrontmatter`` types both fields
# as ``str`` and Pydantic v2 does NOT coerce int/date→str. Without the
# ``mode='before'`` coercion validators, ~54% of finalize validation failures
# observed in prod kbl_log (48h window, 65/121 warns) hit this class.

from datetime import date as _date  # noqa: E402  — local import by design


def test_deadline_accepts_str_yyyy_mm_dd() -> None:
    """String input (already correctly quoted in YAML) passes through."""
    fm = SilverFrontmatter(**_base_fm_dict(deadline="2026-05-01"))
    assert fm.deadline == "2026-05-01"


def test_deadline_accepts_date_object() -> None:
    """YAML 1.1 ``deadline: 2026-05-01`` (unquoted) → ``datetime.date``
    → coerced back to ISO-8601 str by ``_deadline_coerce_to_str``."""
    fm = SilverFrontmatter(**_base_fm_dict(deadline=_date(2026, 5, 1)))
    assert fm.deadline == "2026-05-01"


def test_deadline_accepts_datetime_object() -> None:
    """Rare but possible: YAML 1.1 parses ``2026-05-01T12:00:00Z`` as
    ``datetime``. Coerce to date portion only (deadline has no time)."""
    fm = SilverFrontmatter(
        **_base_fm_dict(
            deadline=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        )
    )
    assert fm.deadline == "2026-05-01"


def test_source_id_accepts_str() -> None:
    """Producer side (Step 5 stub writers + step6 override) already casts
    to str; verify the already-str path still passes cleanly."""
    fm = SilverFrontmatter(**_base_fm_dict(source_id="68"))
    assert fm.source_id == "68"


def test_source_id_coerces_int() -> None:
    """YAML 1.1 ``source_id: 68`` (unquoted) → Python ``int`` →
    coerced to str by ``_source_id_coerce_to_str``. Defense-in-depth for
    any producer that forgets the str cast."""
    fm = SilverFrontmatter(**_base_fm_dict(source_id=68))
    assert fm.source_id == "68"


def test_source_id_coerces_large_int() -> None:
    """Large signal_ids (post-SERIAL-exhaustion / bigint column) still
    stringify cleanly — no scientific notation, no truncation."""
    fm = SilverFrontmatter(**_base_fm_dict(source_id=9_999_999_999))
    assert fm.source_id == "9999999999"


# --------------------------- R14: money cap ---------------------------


def test_r14_money_mentioned_over_3_rejected() -> None:
    with pytest.raises(ValidationError, match="capped at 3"):
        SilverFrontmatter(
            **_base_fm_dict(
                money_mentioned=[
                    MoneyMention(amount=100, currency="EUR"),
                    MoneyMention(amount=200, currency="USD"),
                    MoneyMention(amount=300, currency="CHF"),
                    MoneyMention(amount=400, currency="GBP"),
                ]
            )
        )


# --------------------------- R15: currency literal + amount ---------------------------


def test_r15_money_negative_rejected() -> None:
    with pytest.raises(ValidationError, match="positive"):
        MoneyMention(amount=-1, currency="EUR")


def test_r15_money_currency_outside_enum_rejected() -> None:
    with pytest.raises(ValidationError):
        MoneyMention(amount=100, currency="JPY")  # type: ignore[arg-type]


# --------------------------- R16: stub status literal ---------------------------


def test_r16_status_stub_auto_accepted() -> None:
    fm = SilverFrontmatter(**_base_fm_dict(status="stub_auto"))
    assert fm.status == "stub_auto"


def test_r16_status_unknown_value_rejected() -> None:
    with pytest.raises(ValidationError, match="status"):
        SilverFrontmatter(**_base_fm_dict(status="stub_bogus"))


# --------------------------- R17: body length bounds ---------------------------


def test_r17_body_under_300_rejected() -> None:
    with pytest.raises(ValidationError, match="too short"):
        SilverDocument(
            frontmatter=SilverFrontmatter(**_base_fm_dict()), body=_base_body(299)
        )


def test_r17_body_over_8000_rejected() -> None:
    with pytest.raises(ValidationError, match="too long"):
        SilverDocument(
            frontmatter=SilverFrontmatter(**_base_fm_dict()), body=_base_body(8001)
        )


# --------------------------- R18: forbidden body markers ---------------------------


def test_r18_body_voice_gold_marker_rejected() -> None:
    dirty = _base_body(400) + "\n\nvoice: gold trailing"
    with pytest.raises(ValidationError, match="forbidden self-promotion"):
        SilverDocument(
            frontmatter=SilverFrontmatter(**_base_fm_dict()),
            body=dirty,
        )


def test_r18_body_author_director_marker_rejected() -> None:
    dirty = _base_body(400) + "\nfake: author:director"
    with pytest.raises(ValidationError, match="forbidden self-promotion"):
        SilverDocument(
            frontmatter=SilverFrontmatter(**_base_fm_dict()), body=dirty
        )


# --------------------------- R19: stub status + body length coherence ---------------------------


def test_r19_stub_status_with_long_body_rejected() -> None:
    with pytest.raises(ValidationError, match="deterministic stub shape"):
        SilverDocument(
            frontmatter=SilverFrontmatter(**_base_fm_dict(status="stub_auto")),
            body=_base_body(601),
        )


def test_r19_stub_status_with_short_body_accepted() -> None:
    doc = SilverDocument(
        frontmatter=SilverFrontmatter(**_base_fm_dict(status="stub_auto")),
        body="stub body " + _base_body(300),  # 311 chars — under 600
    )
    assert doc.frontmatter.status == "stub_auto"


# --------------------------- R21: thread_continues lenient ---------------------------


def test_r21_thread_continues_valid_paths_accepted() -> None:
    fm = SilverFrontmatter(
        **_base_fm_dict(
            thread_continues=[
                "wiki/ao/2026-04-01_tonbach.md",
                "wiki/movie/2026-03-30_hma.md",
            ]
        )
    )
    assert len(fm.thread_continues) == 2


def test_r21_thread_continues_non_wiki_path_rejected() -> None:
    with pytest.raises(ValidationError, match="wiki"):
        SilverFrontmatter(
            **_base_fm_dict(thread_continues=["docs/other.md"])
        )


# --------------------------- CrossLinkStub ---------------------------


def test_cross_link_stub_render_shape() -> None:
    stub = CrossLinkStub(
        source_signal_id="42",
        source_path="wiki/ao/2026-04-19_tonbach.md",
        created=_utc(),
        vedana="opportunity",
        excerpt="AO tonbach capital call commit",
    )
    row = stub.render_stub_row()
    assert row.startswith("<!-- stub:signal_id=42 -->")
    assert "2026-04-19" in row
    assert "wiki/ao/2026-04-19_tonbach.md" in row
    assert "opportunity" in row
    assert "AO tonbach" in row


def test_cross_link_stub_excerpt_over_140_rejected() -> None:
    with pytest.raises(ValidationError, match="too long"):
        CrossLinkStub(
            source_signal_id="1",
            source_path="wiki/ao/x.md",
            created=_utc(),
            vedana="routine",
            excerpt="x" * 141,
        )


def test_cross_link_stub_excerpt_newline_rejected() -> None:
    with pytest.raises(ValidationError, match="single-line"):
        CrossLinkStub(
            source_signal_id="1",
            source_path="wiki/ao/x.md",
            created=_utc(),
            vedana="routine",
            excerpt="line1\nline2",
        )


# --------------------------- extra='forbid' ---------------------------


def test_frontmatter_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        SilverFrontmatter(**_base_fm_dict(bogus_field="x"))


# --------------------------- CHANDA invariants ---------------------------


def test_chanda_inv4_body_forbidden_marker_family() -> None:
    """Multiple capitalizations of the marker all rejected."""
    for bad in ("Voice: Gold", "VOICE: GOLD", "voice:gold"):
        body = _base_body(400) + "\n" + bad
        with pytest.raises(ValidationError):
            SilverDocument(
                frontmatter=SilverFrontmatter(**_base_fm_dict()), body=body
            )


def test_chanda_inv8_voice_silver_author_pipeline_enforced_at_type_level() -> None:
    """Positive: the only accepted tuple is (silver, pipeline). Any
    other combination fails at the Literal layer — a draft cannot
    auto-promote to Gold."""
    fm = SilverFrontmatter(**_base_fm_dict())
    assert fm.voice == "silver"
    assert fm.author == "pipeline"
