"""AI_HOTEL_RESEARCH_FINDINGS_1 — render researched answers on AI Hotel cards.

Source guards cover the stale-branch hazard from this dispatch: reapply only the
research-findings UI while preserving delete, rotate, EXIF, and readable titles.
"""

from __future__ import annotations

from pathlib import Path


def _html() -> str:
    return Path("outputs/static/ai-hotel.html").read_text()


def test_research_findings_renderer_and_styles_exist():
    html = _html()

    assert ".rf-head" in html
    assert ".rf-meta" in html
    assert ".rf-flag" in html
    assert ".rf-need" in html
    assert ".rf-src" in html
    assert "function renderResearchFindings(b, rf)" in html
    assert ".innerHTML" not in html


def test_site_card_badge_replaces_to_research_prompt_when_researched():
    html = _html()
    card = html[html.index("function buildNoteCard(c)"):html.index("function updatePhotoThumbs(")]

    assert "v.research_findings&&typeof v.research_findings==='object'" in card
    assert "bits.push('✓ researched')" in card
    assert "researchCount(v.unknowns_to_research)" in card
    assert card.index("v.research_findings") < card.index("researchCount(v.unknowns_to_research)")


def test_detail_skips_raw_research_object_and_superseded_unknowns():
    html = _html()
    start = html.index("function openNoteDetail(c)")
    detail = html[start:html.index("renderPhotos(b, c)", start)]

    assert "const rf=fr.values.research_findings;" in detail
    assert "if(k==='research_findings')return;" in detail
    assert "if(k==='unknowns_to_research'&&rf&&typeof rf==='object')return;" in detail
    assert "if(rf&&typeof rf==='object')renderResearchFindings(b,rf);" in detail
    assert detail.index("if(k==='research_findings')return;") < detail.index("String(val)")
    assert detail.index("if(!any)b.appendChild") < detail.index("renderResearchFindings(b,rf)")


def test_research_renderer_is_fail_soft_and_text_only():
    html = _html()
    renderer = html[html.index("function renderResearchFindings(b, rf)"):html.index("function openNoteDetail(c)")]

    assert "if(!rf||typeof rf!=='object')return;" in renderer
    assert "Array.isArray(rf.answers)?rf.answers:[]" in renderer
    assert "Array.isArray(rf.flags)?rf.flags:[]" in renderer
    assert "String(rf.headline)" in renderer
    assert "String(val)" in renderer
    assert "String(f)" in renderer
    assert ".innerHTML" not in renderer


def test_research_patch_preserves_latest_main_field_note_controls():
    html = _html()

    assert "AI_HOTEL_READABLE_CARD_TITLE_1" in html
    assert "function cardTitle(c)" in html
    assert "Delete field note" in html
    assert "function deleteNoteCard(c, btn)" in html
    assert "lbox-rotate" in html
    assert "Rotate photo clockwise" in html
    assert "image-orientation:from-image" in html
