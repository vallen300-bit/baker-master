"""Cortex Phase 3a — meta-reasoning + capability selection.

Reads signal text + Phase 2 load context, decides which domain
capabilities (≤5 per RA-23 Q4) should be invoked in Phase 3b. Persists
a `meta_reason` artifact to ``cortex_phase_outputs`` and bumps the
cycle row's running cost.

Brief: ``briefs/BRIEF_CORTEX_3T_FORMALIZE_1B.md``.

EXPLORE deviations from the brief snippet (Lesson #44):
  - Brief used "claude-opus-4-7"; production model 2026-04-28 is
    ``claude-opus-4-6`` (verified at ``capability_runner.py:317``).
    "Out of scope" of 1A/1B/1C says no model bump.
  - ``log_api_cost`` returns EUR (not USD) — column name is ``cost_dollars``
    per 1A migration; we keep the column name but record EUR values.
  - Module-level ``_get_store`` / ``_load_active_domain_capabilities`` /
    ``_call_opus`` make the LLM call + DB call patchable in tests
    without fighting attribute pollution from suite-wide imports
    (per the test-pollution mitigation discovered during 1A).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

CAP5_LIMIT = 5  # RA-23 Q4 hard cap — never exceed even via LLM rank
PHASE3A_MAX_TOKENS = 2048
PHASE3A_MODEL = "claude-opus-4-6"

# Generic always-on patterns gating the games_relevant cortex-config opt-in.
# Without a negotiation-class signal, game_theory is not auto-added.
_GAME_THEORY_GATE_PATTERNS = (
    r"\boffer\b", r"\bproposal\b", r"\bsettlement\b",
    r"\bnegotiation\b", r"\bcounterparty\b",
)


@dataclass
class Phase3aResult:
    summary: str
    signal_classification: str
    capabilities_to_invoke: list[str]   # capped at CAP5_LIMIT
    reasoning_notes: str
    matched_evidence: dict[str, list[str]] = field(default_factory=dict)
    cost_tokens: int = 0
    cost_dollars: float = 0.0


# --------------------------------------------------------------------------
# Module-level helpers — patchable in tests
# --------------------------------------------------------------------------


def _get_store():
    """Resolve the SentinelStoreBack singleton via canonical accessor."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _load_active_domain_capabilities() -> list[dict]:
    """SELECT slug + trigger_patterns from active domain capabilities.

    LIMIT 30 (Lesson #1). On any DB error, returns []; the cycle proceeds
    with an empty candidate pool (Phase 3a still emits a meta_reason
    artifact, just one with capabilities_to_invoke=[]).
    """
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT slug, trigger_patterns
            FROM capability_sets
            WHERE active=TRUE AND capability_type='domain'
            LIMIT 30
            """
        )
        rows = cur.fetchall()
        cur.close()
        return [{"slug": r[0], "trigger_patterns": r[1] or []} for r in rows]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"_load_active_domain_capabilities failed: {e}")
        return []
    finally:
        store._put_conn(conn)


def _call_opus(
    *,
    system_prompt: str,
    user_message: str,
    model: str = PHASE3A_MODEL,
    max_tokens: int = PHASE3A_MAX_TOKENS,
    source: str = "cortex_phase3a",
    capability_id: str | None = None,
) -> tuple[str, int, int, float]:
    """Direct Anthropic Messages API call. Returns (text, in, out, cost_eur).

    Mirrors the canonical extraction pattern at
    ``capability_runner.py:315-356``. Cost is logged via cost_monitor
    (Prometheus / billing), and the cost_eur is also returned so the
    caller can accumulate into ``cortex_cycles.cost_dollars``.
    """
    import anthropic
    from orchestrator import config
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
            capability_id=capability_id,
        )
    except Exception as e:
        logger.error(f"log_api_cost failed (non-fatal): {e}")
        cost_eur = None
    return text, in_tokens, out_tokens, float(cost_eur or 0.0)


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


async def run_phase3a_meta_reason(
    *,
    cycle_id: str,
    matter_slug: str,
    signal_text: str,
    phase2_context: dict[str, Any],
) -> Phase3aResult:
    """Phase 3a entry point.

    Algorithm:
      1. Load active domain capabilities + their trigger_patterns
      2. Regex-match candidates from the signal_text (re.IGNORECASE)
      3. Add cortex-config opt-ins (games_relevant: true → game_theory
         iff signal also matches a generic negotiation-class pattern)
      4. Cap-5: if pool > 5, sort by hit-count descending, take top-5
      5. LLM produces summary + classification + reasoning_notes
      6. Persist meta_reason artifact + bump cycle cost
    """
    capabilities = _load_active_domain_capabilities()

    candidate_pool: list[str] = []
    matched_evidence: dict[str, list[str]] = {}
    for cap in capabilities:
        slug = cap["slug"]
        patterns = cap.get("trigger_patterns") or []
        if not isinstance(patterns, list):
            patterns = []
        hits: list[str] = []
        for p in patterns:
            try:
                if re.search(p, signal_text or "", re.IGNORECASE):
                    hits.append(p)
            except re.error as e:
                logger.warning(f"Phase 3a: bad regex {p!r} on {slug}: {e}")
        if hits:
            candidate_pool.append(slug)
            matched_evidence[slug] = hits

    # Cortex-config opt-in: games_relevant + negotiation-class signal
    matter_config_text = (phase2_context or {}).get("matter_config", "") or ""
    if "games_relevant: true" in matter_config_text and "game_theory" not in candidate_pool:
        if any(re.search(p, signal_text or "", re.IGNORECASE)
               for p in _GAME_THEORY_GATE_PATTERNS):
            candidate_pool.append("game_theory")
            matched_evidence["game_theory"] = ["cortex-config:games_relevant"]

    # Cap-5 enforcement (heuristic — sort by hit count descending)
    if len(candidate_pool) > CAP5_LIMIT:
        candidate_pool = sorted(
            candidate_pool,
            key=lambda s: len(matched_evidence.get(s, [])),
            reverse=True,
        )[:CAP5_LIMIT]
        logger.info(
            "Phase 3a cycle=%s: pool>%d, heuristic ranked → %s",
            cycle_id, CAP5_LIMIT, candidate_pool,
        )

    # LLM produces summary + classification + reasoning_notes for the
    # selected set. On LLM failure, fall back to a deterministic stub
    # (cycle still proceeds — fail-forward is core 1B behavior).
    try:
        summary, classification, reasoning, in_tok, out_tok, cost = _llm_meta_reason(
            signal_text=signal_text,
            matter_slug=matter_slug,
            selected_capabilities=candidate_pool,
            matched_evidence=matched_evidence,
            phase2_context=phase2_context,
        )
    except Exception as e:
        logger.error(f"Phase 3a LLM call failed for cycle {cycle_id}: {e}")
        summary = f"[fallback] regex-matched {len(candidate_pool)} capabilities"
        classification = "uncategorized"
        reasoning = f"LLM unavailable; heuristic-only selection. Error: {e}"
        in_tok = out_tok = 0
        cost = 0.0

    result = Phase3aResult(
        summary=summary,
        signal_classification=classification,
        capabilities_to_invoke=candidate_pool,
        reasoning_notes=reasoning,
        matched_evidence=matched_evidence,
        cost_tokens=int(in_tok) + int(out_tok),
        cost_dollars=float(cost),
    )

    _persist_phase3a(cycle_id, result)
    return result


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------


def _llm_meta_reason(
    *,
    signal_text: str,
    matter_slug: str,
    selected_capabilities: list[str],
    matched_evidence: dict[str, list[str]],
    phase2_context: dict[str, Any],
) -> tuple[str, str, str, int, int, float]:
    """LLM produces summary + signal_classification + reasoning_notes.

    Returns: (summary, classification, reasoning_notes, in_tokens, out_tokens, cost_eur).
    JSON parse failures fall back to using the raw text as ``summary``.
    """
    system = (
        "You are the Cortex meta-reasoner for matter '" + matter_slug + "'. "
        "Given a signal, the regex-selected domain capabilities, and the "
        "matter brain, produce concise meta-reasoning. Output strict JSON "
        "with fields: summary (≤200 chars), signal_classification (one "
        "of: opportunity, threat, request, status, other), reasoning_notes."
    )
    matter_config_excerpt = (phase2_context or {}).get("matter_config", "")[:4000]
    user = (
        f"Signal:\n{signal_text or '(empty)'}\n\n"
        f"Selected capabilities: {selected_capabilities}\n"
        f"Regex evidence: {json.dumps(matched_evidence)[:1000]}\n\n"
        f"Matter brain (excerpt):\n{matter_config_excerpt}\n\n"
        "Return JSON only, no prose."
    )
    text, in_tok, out_tok, cost = _call_opus(
        system_prompt=system,
        user_message=user,
        source="cortex_phase3a",
    )
    summary = text[:200] if text else ""
    classification = "other"
    reasoning = text
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            summary = str(parsed.get("summary", summary))[:200]
            classification = str(parsed.get("signal_classification", classification))
            reasoning = str(parsed.get("reasoning_notes", reasoning))
    except Exception as e:
        logger.warning(f"Phase 3a LLM JSON parse failed (using text fallback): {e}")
    return summary, classification, reasoning, in_tok, out_tok, cost


def _persist_phase3a(cycle_id: str, result: Phase3aResult) -> None:
    """INSERT meta_reason artifact + bump running cycle cost.

    Persistence failures log + raise (caller marks cycle status='failed').
    """
    payload = json.dumps({
        "summary": result.summary,
        "signal_classification": result.signal_classification,
        "capabilities_to_invoke": result.capabilities_to_invoke,
        "reasoning_notes": result.reasoning_notes,
        "matched_evidence": result.matched_evidence,
        "cost_tokens": result.cost_tokens,
        "cost_dollars": result.cost_dollars,
    }, default=str)
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        logger.warning(f"_persist_phase3a: no DB conn for cycle {cycle_id}")
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order,
                artifact_type, payload)
            VALUES (%s, 'reason', 3, 'meta_reason', %s::jsonb)
            """,
            (cycle_id, payload),
        )
        cur.execute(
            """
            UPDATE cortex_cycles
            SET current_phase='reason',
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
        logger.error(f"_persist_phase3a failed for cycle {cycle_id}: {e}")
        raise
    finally:
        store._put_conn(conn)
