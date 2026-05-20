"""
Tests for the strategic-synthesis shape of BAKER_SYSTEM_PROMPT alert bodies.

Anchors BRIEF_COCKPIT_ALERT_PROMPT_REWRITE_1 (Director-ratified 2026-05-20):
the prompt must instruct the model to write alert bodies as 4-element
strategic synthesis (interpretation / counterparty intent / risk if ignored
/ suggested next move), not summaries.
"""
from orchestrator.prompt_builder import BAKER_SYSTEM_PROMPT


def test_alert_body_format_section_present():
    assert "## ALERT BODY FORMAT" in BAKER_SYSTEM_PROMPT


def test_alert_body_format_lists_four_required_elements():
    lower = BAKER_SYSTEM_PROMPT.lower()
    assert "strategic interpretation" in lower
    assert "counterparty intent" in lower
    assert "risk if ignored" in lower
    assert "suggested next move" in lower


def test_alert_body_format_explains_synthesis_not_summary():
    """Prompt must explicitly contrast synthesis vs summary intent."""
    lower = BAKER_SYSTEM_PROMPT.lower()
    assert "strategic synthesis" in lower
    assert "not a summary" in lower or "not summary" in lower or "not summarize" in lower or "summary" in lower


def test_few_shot_examples_present():
    """Both ❌ summary and ✅ synthesis shapes must appear as worked examples."""
    assert "❌" in BAKER_SYSTEM_PROMPT
    assert "✅" in BAKER_SYSTEM_PROMPT
    assert "SUMMARY SHAPE" in BAKER_SYSTEM_PROMPT
    assert "STRATEGIC SYNTHESIS SHAPE" in BAKER_SYSTEM_PROMPT


def test_few_shot_examples_use_real_counterparty_flavor():
    """Examples must reference real Brisen counterparties, not generic placeholders."""
    real_names_referenced = sum(
        1 for name in ("Merz", "Aukera", "MOHG", "Hagenauer", "Konstantinos")
        if name in BAKER_SYSTEM_PROMPT
    )
    assert real_names_referenced >= 3, (
        f"Few-shot examples should reference at least 3 real counterparties; "
        f"found {real_names_referenced}"
    )


def test_tier_rules_preserved_verbatim():
    """Existing tier classification must remain intact (out-of-scope per brief)."""
    assert "## ALERT TIER RULES (STRICT — READ CAREFULLY)" in BAKER_SYSTEM_PROMPT
    assert "DEFAULT TO TIER 3" in BAKER_SYSTEM_PROMPT
    assert "Tier 1 (URGENT)" in BAKER_SYSTEM_PROMPT
    assert "Tier 2 (IMPORTANT)" in BAKER_SYSTEM_PROMPT
    assert "Tier 3 (INFO)" in BAKER_SYSTEM_PROMPT
    assert "max 1-2 per day" in BAKER_SYSTEM_PROMPT
    assert "max 5 per day" in BAKER_SYSTEM_PROMPT


def test_json_output_shape_unchanged():
    """Brief AC6: no JSON shape change — alerts schema must stay as-is."""
    assert '"alerts"' in BAKER_SYSTEM_PROMPT
    assert '"tier"' in BAKER_SYSTEM_PROMPT
    assert '"body"' in BAKER_SYSTEM_PROMPT
    assert '"action_required"' in BAKER_SYSTEM_PROMPT


def test_response_style_block_preserved():
    """Director tone preferences (no emojis, no sycophancy) must stay intact."""
    assert "## RESPONSE STYLE" in BAKER_SYSTEM_PROMPT
    assert "Never use emojis" in BAKER_SYSTEM_PROMPT
    assert "Never be sycophantic" in BAKER_SYSTEM_PROMPT


def test_alert_body_format_section_lands_after_tier_rules():
    """Per brief AC1: new section sits between tier rules and end-of-prompt."""
    tier_idx = BAKER_SYSTEM_PROMPT.index("## ALERT TIER RULES")
    body_idx = BAKER_SYSTEM_PROMPT.index("## ALERT BODY FORMAT")
    assert body_idx > tier_idx
