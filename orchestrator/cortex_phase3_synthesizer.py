"""Cortex Phase 3c — synthesis.

Combines:
  - matter cortex-config (the absorbed PM/AM brain)
  - Phase 2 load context (curated knowledge + recent activity)
  - Phase 3a meta-reasoning
  - Phase 3b specialist outputs (≤5)

Produces a unified Director-readable proposal text + structured action
recommendations. Persists a ``synthesis`` artifact and flips the cycle
status to ``proposed`` (1C's Phase 4 picks up from there).

Brief: ``briefs/BRIEF_CORTEX_3T_FORMALIZE_1B.md``.

EXPLORE deltas vs the brief snippet:
  - Uses ``claude-opus-4-6`` (production model 2026-04-28; brief said
    4.7, but model bumps are out of scope per brief).
  - LLM call goes through the same ``_call_opus`` shape as Phase 3a
    so cost monitor wiring is consistent.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

PHASE3C_MODEL = "claude-opus-4-6"
PHASE3C_MAX_TOKENS = 4000


@dataclass
class Phase3cResult:
    proposal_text: str
    structured_actions: list[dict] = field(default_factory=list)
    cost_tokens: int = 0
    cost_dollars: float = 0.0


# --------------------------------------------------------------------------
# Patchable module-level helpers
# --------------------------------------------------------------------------


def _get_store():
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _call_opus(
    *,
    system_prompt: str,
    user_message: str,
    model: str = PHASE3C_MODEL,
    max_tokens: int = PHASE3C_MAX_TOKENS,
    source: str = "cortex_phase3c",
) -> tuple[str, int, int, float]:
    """Direct Anthropic call. Mirror of phase3a helper for consistency."""
    import anthropic
    from config.settings import config
    from orchestrator.cost_monitor import log_api_cost

    client = anthropic.Anthropic(api_key=config.claude.api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    in_tokens = getattr(resp.usage, "input_tokens", 0) or 0
    out_tokens = getattr(resp.usage, "output_tokens", 0) or 0
    text = resp.content[0].text.strip() if resp.content else ""
    try:
        cost_eur = log_api_cost(
            model=model,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            source=source,
            capability_id="synthesizer",
        )
    except Exception as e:
        logger.error(f"log_api_cost failed (non-fatal): {e}")
        cost_eur = None
    return text, in_tokens, out_tokens, float(cost_eur or 0.0)


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


async def run_phase3c_synthesize(
    *,
    cycle_id: str,
    matter_slug: str,
    signal_text: str,
    phase2_context: dict[str, Any],
    phase3a_result,
    phase3b_result,
) -> Phase3cResult:
    """Phase 3c entry point.

    Loads the synthesizer system_prompt from capability_sets (Director
    ratified absorption per RA-23 §1), bundles all artifacts into a
    single user message, calls Opus, extracts the trailing JSON block
    of structured_actions, and persists a synthesis artifact + flips
    cycle status to 'proposed'.
    """
    synth_prompt = _load_synthesizer_prompt() or _DEFAULT_SYNTH_PROMPT

    user_msg = _build_user_message(
        matter_slug=matter_slug,
        signal_text=signal_text,
        phase2_context=phase2_context,
        phase3a_result=phase3a_result,
        phase3b_result=phase3b_result,
    )

    try:
        proposal_text, in_tok, out_tok, cost = _call_opus(
            system_prompt=synth_prompt,
            user_message=user_msg,
            source="cortex_phase3c",
        )
    except Exception as e:
        logger.error(f"Phase 3c LLM call failed for cycle {cycle_id}: {e}")
        proposal_text = (
            "[Phase 3c LLM unavailable]\n\n"
            f"Specialists invoked: "
            f"{[o.capability_slug for o in phase3b_result.outputs]}\n"
            "Manual synthesis required."
        )
        in_tok = out_tok = 0
        cost = 0.0

    structured = _extract_actions(proposal_text)

    result = Phase3cResult(
        proposal_text=proposal_text,
        structured_actions=structured,
        cost_tokens=int(in_tok) + int(out_tok),
        cost_dollars=float(cost),
    )

    _persist_phase3c(cycle_id, result)
    return result


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------


_DEFAULT_SYNTH_PROMPT = (
    "You are the Cortex synthesizer. Combine the matter brain + Phase 2 "
    "context + Phase 3a meta-reasoning + Phase 3b specialist outputs "
    "into a unified proposal for the Director. Be concise, decision-"
    "ready, and end with a JSON code block listing structured_actions."
)


def _load_synthesizer_prompt() -> str:
    """SELECT system_prompt FROM capability_sets WHERE slug='synthesizer'."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return ""
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT system_prompt FROM capability_sets "
            "WHERE slug='synthesizer' AND active=TRUE LIMIT 1"
        )
        row = cur.fetchone()
        cur.close()
        return (row[0] or "") if row else ""
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"_load_synthesizer_prompt failed: {e}")
        return ""
    finally:
        store._put_conn(conn)


def _build_user_message(
    *,
    matter_slug: str,
    signal_text: str,
    phase2_context: dict,
    phase3a_result,
    phase3b_result,
) -> str:
    """Pack artifacts into a single message for the synthesizer LLM call."""
    matter_brain = (phase2_context or {}).get("matter_config", "")[:8000]
    parts = [
        f"# Cortex Cycle Synthesis — {matter_slug}\n",
        f"## Signal\n{signal_text or '(empty)'}\n",
        f"## Matter Brain (absorbed cortex-config)\n{matter_brain}\n",
        "## Phase 3a Meta-Reasoning",
        f"- Summary: {getattr(phase3a_result, 'summary', '')}",
        f"- Classification: {getattr(phase3a_result, 'signal_classification', '')}",
        f"- Reasoning: {getattr(phase3a_result, 'reasoning_notes', '')}",
        "",
        "## Phase 3b Specialist Outputs",
    ]
    for out in getattr(phase3b_result, "outputs", []):
        status = "OK" if getattr(out, "success", False) else "FAILED"
        parts.append(f"### {out.capability_slug} ({status})")
        if out.success:
            parts.append((out.output_text or "")[:4000])
        else:
            parts.append(f"_(failed: {out.error})_")
        parts.append("")
    parts.append(
        "## Required Output Format\n"
        "Produce the unified proposal in markdown.\n"
        "End with a JSON code block containing structured_actions:\n"
        "```json\n"
        '[{"action": "...", "rationale": "...", "target": "...", "deadline": "YYYY-MM-DD"}]\n'
        "```"
    )
    return "\n".join(parts)


def _extract_actions(proposal_text: str) -> list[dict]:
    """Extract trailing ```json [...] ``` block. Returns [] on miss/parse-fail."""
    if not proposal_text:
        return []
    m = re.search(r"```json\s*(\[.*?\])\s*```", proposal_text, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    try:
        parsed = json.loads(m.group(1))
        if isinstance(parsed, list):
            return parsed
        return []
    except Exception as e:
        logger.warning(f"Failed to parse structured_actions JSON: {e}")
        return []


def _persist_phase3c(cycle_id: str, result: Phase3cResult) -> None:
    """INSERT synthesis artifact + flip cycle status to 'proposed'.

    Persistence failures log + raise (caller marks cycle status='failed'
    so Phase 6 archives the terminal state).
    """
    payload = json.dumps({
        "proposal_text": result.proposal_text,
        "structured_actions": result.structured_actions,
        "cost_tokens": result.cost_tokens,
        "cost_dollars": result.cost_dollars,
    }, default=str)
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        logger.warning(f"_persist_phase3c: no DB conn for cycle {cycle_id}")
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order,
                artifact_type, payload)
            VALUES (%s, 'reason', 5, 'synthesis', %s::jsonb)
            """,
            (cycle_id, payload),
        )
        cur.execute(
            """
            UPDATE cortex_cycles
            SET status='proposed',
                current_phase='reason',
                cost_tokens = cost_tokens + %s,
                cost_dollars = cost_dollars + %s
            WHERE cycle_id=%s
            """,
            (result.cost_tokens, result.cost_dollars, cycle_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"_persist_phase3c failed for cycle {cycle_id}: {e}")
        raise
    finally:
        store._put_conn(conn)
