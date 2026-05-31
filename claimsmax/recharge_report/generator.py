"""Anthropic tool-use orchestrator for RechargeReport.

Reads SKILL.md + spine.md + V3 HTML template at runtime; bundles into a cached
system block. Entry: generate_recharge_report()."""
import logging
import os
from pathlib import Path
from typing import Literal

import anthropic

from .renderer import CANONICAL_TEMPLATE_PATH, render_to_html
from .schema import RechargeReport
from .validator import RechargeReportValidationError, validate_recharge_report_html

log = logging.getLogger(__name__)

MODEL_HIGH = os.environ.get("KBL_ANTHROPIC_MODEL", "claude-opus-4-8")  # OPUS_4_8_UPGRADE_1
MODEL_ROUTINE = "claude-sonnet-4-6"

_VAULT = Path(os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault")))
SKILL_FILE_PATH = _VAULT / "_ops/skills/pichler-report-english/SKILL.md"
SPINE_FILE_PATH = _VAULT / "_ops/skills/pichler-report/spine.md"

_PER_SECTION_TARGETS = (
    "PER-SECTION TARGETS (lift first-pass success):\n"
    "  1. parties: 120-160 words, HTML <ol> with 2-4 <li> items.\n"
    "  2. background: 100-140 words, HTML <ol> with 4-6 short numbered items.\n"
    "  3. what_happened: 250-320 words, 3-5 short <p> paragraphs, no bullets.\n"
    "  4. what_hag_failed: 80-120 words, HTML <ul>, max 3 bullets, duplicates removed.\n"
    "  5. evidence_chain: 5-9 rows total.\n"
    "  6. amount_claimed: 3-6 line items + 1 total + 0-3 sub rows.\n"
    "  7. amount_claimed_notes: <=100 words, 2 short <p>.\n"
    "  8. delta_conflict: 60-120 words, single paragraph, lead with conflict, end with resolution path.\n"
    "  9. arguments: 5-8 items, each with bolded headline + 2-3 short body lines separated by <br>.\n"
)


class RechargeReportGenerationError(Exception):
    """Raised after final validation failure (post-retry)."""


def _read_skill_bundle(template_path: Path) -> tuple[str, str, str]:
    """Read the 3-file skill bundle. Raises FileNotFoundError on any missing file."""
    for p in (SKILL_FILE_PATH, SPINE_FILE_PATH, template_path):
        if not p.exists():
            raise FileNotFoundError(f"Skill bundle file missing: {p}")
    return (
        SKILL_FILE_PATH.read_text(encoding="utf-8"),
        SPINE_FILE_PATH.read_text(encoding="utf-8"),
        template_path.read_text(encoding="utf-8"),
    )


def _system_prompt(skill_md: str, spine_md: str, template_html: str) -> list[dict]:
    """Cached system block: skill + spine + V3 HTML template + per-section targets."""
    text = (
        "You are producing the Director-facing Pichler V3 recharge-failure report "
        "for an English-reading counterparty audience. Comply with the canonical "
        "pichler-report-english skill, the shared spine, and the V3 HTML binding "
        "contract. Emit ONLY a single tool call with the schema fields. Do not "
        "narrate around the tool call. Do not propose new sections.\n\n"
        "=== SKILL: pichler-report-english ===\n\n" + skill_md + "\n\n"
        "=== SPINE (shared with bilingual sibling) ===\n\n" + spine_md + "\n\n"
        "=== V3 HTML BINDING TEMPLATE ===\n\n" + template_html + "\n\n"
        + _PER_SECTION_TARGETS
    )
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def generate_recharge_report(
    facts_for_trade: str,
    model_tier: Literal["high", "routine"] = "high",
    template_path: Path = CANONICAL_TEMPLATE_PATH,
) -> str:
    """Return rendered HTML that has PASSED canonical V3 validation. Blocks otherwise."""
    skill_md, spine_md, template_html = _read_skill_bundle(template_path)
    model = MODEL_HIGH if model_tier == "high" else MODEL_ROUTINE
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    # Anthropic strict tool-use rejects array minItems/maxItems > 1, which would
    # forbid our exactly-3 claim_figures triplet. Strict mode dropped; Pydantic
    # extra="forbid" + min/max_length on every list catch all drift at
    # model_validate() time below.
    tool = {
        "name": "emit_recharge_report",
        "description": "Emit the 7-section Pichler V3 EN recharge-failure report.",
        "input_schema": {
            **RechargeReport.model_json_schema(),
            "additionalProperties": False,
        },
        "cache_control": {"type": "ephemeral"},
    }

    def _call(repair_note: str = "") -> RechargeReport:
        user_content = facts_for_trade if not repair_note else (
            facts_for_trade
            + "\n\nREPAIR NOTE: Prior attempt failed validation:\n"
            + repair_note
            + "\n\nRetry with corrected structure. Emit only the tool call."
        )
        resp = client.messages.create(
            model=model,
            max_tokens=8_192,
            system=_system_prompt(skill_md, spine_md, template_html),
            tools=[tool],
            tool_choice={"type": "auto"},
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": user_content}],
        )
        block = next((b for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
        if block is None:
            raise RechargeReportGenerationError("Model returned no tool_use block")
        return RechargeReport.model_validate(block.input)

    report = _call()
    rendered = render_to_html(report, template_path)
    try:
        validate_recharge_report_html(rendered)
        return rendered
    except RechargeReportValidationError as e:
        log.warning("First-pass validation failed: %s", e)
        report = _call(repair_note=str(e))
        rendered = render_to_html(report, template_path)
        try:
            validate_recharge_report_html(rendered)
            return rendered
        except RechargeReportValidationError as e2:
            raise RechargeReportGenerationError(
                f"Validation failed twice; surfacing to human review. Last error:\n{e2}"
            ) from e2
