"""Anthropic tool-use orchestrator for RechargeReport.

Single entry point: generate_recharge_report(facts_for_trade, model_tier="high").
- Loads canonical scaffold template (read-only).
- Calls claude-opus-4-7 (high) or claude-sonnet-4-6 (routine) via tool-use,
  strict=True, prompt-caching on tool def + scaffold.
- Adaptive extended thinking (effort="high") for Mehrkosten reasoning.
- Validates rendered markdown; one repair retry on ValidationError;
  surfaces to human on second failure.
"""
import logging
import os
from pathlib import Path
from typing import Literal

import anthropic

from .renderer import CANONICAL_TEMPLATE_PATH, render_to_markdown
from .schema import RechargeReport
from .validator import RechargeReportValidationError, validate_recharge_report

log = logging.getLogger(__name__)

MODEL_HIGH = "claude-opus-4-7"
MODEL_ROUTINE = "claude-sonnet-4-6"
# SPECIALIST-THINKING-2: Opus 4.7/4.8 reject manual {"type":"enabled",
# "budget_tokens":N} with HTTP 400; adaptive thinking is the only accepted mode
# and thinking depth is controlled by output_config.effort, not a token budget.
# "high" (the API default) keeps full reasoning depth for this low-volume,
# quality-critical Director-facing report. Live-verified 2026-05-31.
EXTENDED_THINKING_EFFORT = "high"


class RechargeReportGenerationError(Exception):
    """Raised after final validation failure (post-retry)."""


def _system_prompt(scaffold_text: str) -> list[dict]:
    """Cached system block: scaffold + tone guide. Cache hits on every subsequent trade."""
    return [
        {
            "type": "text",
            "text": (
                "You are producing the Director-facing Pichler/HEAD-4 recharge-failure "
                "report. Use the canonical scaffold below. Emit ONLY a single tool call "
                "with the 11 schema fields. Do not narrate around the tool call. Do not "
                "propose new sections. Declarative tone, no bullets within paragraphs, "
                "no subordinate headings.\n\n"
                "CANONICAL SCAFFOLD (do not modify):\n\n" + scaffold_text
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def generate_recharge_report(
    facts_for_trade: str,
    model_tier: Literal["high", "routine"] = "high",
    template_path: Path = CANONICAL_TEMPLATE_PATH,
) -> str:
    """Return rendered markdown that has PASSED canonical validation. Blocks otherwise."""
    scaffold_text = template_path.read_text(encoding="utf-8")
    model = MODEL_HIGH if model_tier == "high" else MODEL_ROUTINE
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    tool = {
        "name": "emit_recharge_report",
        "description": "Emit the 11-section Pichler/HEAD-4 recharge-failure report.",
        "strict": True,
        "input_schema": {
            **RechargeReport.model_json_schema(),
            "additionalProperties": False,
        },
        "cache_control": {"type": "ephemeral"},
    }

    def _call(repair_note: str = "") -> RechargeReport:
        user_content = (
            facts_for_trade
            if not repair_note
            else (
                facts_for_trade
                + "\n\nREPAIR NOTE: Prior attempt failed validation:\n"
                + repair_note
                + "\n\nRetry with corrected structure. Emit only the tool call."
            )
        )
        resp = client.messages.create(
            model=model,
            max_tokens=8_192,
            system=_system_prompt(scaffold_text),
            tools=[tool],
            tool_choice={"type": "auto"},
            thinking={"type": "adaptive"},
            output_config={"effort": EXTENDED_THINKING_EFFORT},
            messages=[{"role": "user", "content": user_content}],
        )
        tool_use_block = next(
            (b for b in resp.content if getattr(b, "type", "") == "tool_use"),
            None,
        )
        if tool_use_block is None:
            raise RechargeReportGenerationError("Model returned no tool_use block")
        return RechargeReport.model_validate(tool_use_block.input)

    report = _call()
    markdown = render_to_markdown(report, template_path)
    try:
        validate_recharge_report(markdown)
        return markdown
    except RechargeReportValidationError as e:
        log.warning("First-pass validation failed: %s", e)
        report = _call(repair_note=str(e))
        markdown = render_to_markdown(report, template_path)
        try:
            validate_recharge_report(markdown)
            return markdown
        except RechargeReportValidationError as e2:
            raise RechargeReportGenerationError(
                f"Validation failed twice; surfacing to human review. Last error:\n{e2}"
            ) from e2
