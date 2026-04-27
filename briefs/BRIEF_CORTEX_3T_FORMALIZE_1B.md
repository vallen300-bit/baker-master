# BRIEF: CORTEX_3T_FORMALIZE_1B — Phase 3a/3b/3c (reason / invoke / synthesize)

**Milestone:** Cortex Stage 2 V1 (Steps 18-21 in `_ops/processes/cortex-stage2-v1-tracker.md`)
**Source spec:** `_ops/ideas/2026-04-27-cortex-3t-formalize-spec.md` + `_ops/processes/cortex-architecture-final.md`
**Estimated time:** ~12h
**Complexity:** High (LLM call orchestration + cap-5 enforcement + 60s/2-retry resilience + cost instrumentation)
**Trigger class:** MEDIUM (LLM API calls + cross-capability coordination + token-cost writes) → B1 second-pair-review pre-merge
**Prerequisites:** `BRIEF_CORTEX_3T_FORMALIZE_1A` shipped (cycle row + Phase 2 load context available)
**Companion sub-briefs:** 1A (foundation, must ship first) + 1C (Phase 4/5 + scheduler + dry-run + rollback)

---

## Context

Sub-brief **1B of 3**. 1A landed cycle persistence + Phase 1/2/6. 1B fills Phase 3 (the brain) — 3a meta-reasoning + 3b specialist invocation + 3c synthesis. 1C will land Phase 4 proposal card + Phase 5 act + scheduler + dry-run + rollback.

Phase 3 is where Cortex actually thinks: it reads the Phase 2 load context, decides which domain capabilities to invoke (capped at 5 per cycle per Director RA-23 Q4), invokes them with 60s timeout / 2 retries / fail-forward (Q5), and synthesizes results into a unified proposal text ready for Phase 4 proposal card.

Anthropic Memory dead per Director 2026-04-28 — uses Claude Opus 4.7 + Gemini Pro via existing `orchestrator.gemini_client.call_pro()` only.

---

## Problem

Cortex 1A persists cycle + load context but cannot reason. The cycle row sits at status `awaiting_reason` indefinitely. Without Phase 3, no proposals can be generated and Cortex Stage 2 V1 is non-functional.

## Solution

Build 3 new modules:

1. `orchestrator/cortex_phase3_reasoner.py` — Phase 3a. Reads cycle's `phase2_load_context` + signal text. LLM call to Claude Opus produces meta-reasoning JSON: `{summary, signal_classification, capabilities_to_invoke[≤5], reasoning_notes}`. Capabilities selected from active `capability_sets` rows whose `trigger_patterns` regex match the signal text OR matter cortex-config explicitly opts in (e.g. `games_relevant: true` on AO matter activates `game_theory` for negotiation signals).

2. `orchestrator/cortex_phase3_invoker.py` — Phase 3b. Iterates the 3a-selected capabilities; invokes each via existing `orchestrator.capability_runner.run_single()` (verified signature line 198) with `httpx.Timeout(connect=10, read=60)` and 2 retries on `httpx.TimeoutException`. Each successful invocation persists output to `cortex_phase_outputs` row + writes a curated knowledge file at `wiki/matters/<slug>/curated/<capability>-<date>.md` (NOTE: wiki write happens via Mac Mini mirror in 1C; 1B writes to `outputs/cortex_proposed_curated/<cycle_id>/<file>.md` for Phase 5 to relocate later).

3. `orchestrator/cortex_phase3_synthesizer.py` — Phase 3c. Reads matter-config absorbed brain (Task 3 cortex-config.md content) + 3a meta-reasoning + 3b specialist outputs. LLM call (Claude Opus) produces unified proposal text + structured action recommendations. Persists to `cortex_phase_outputs` row + sets cycle status to `proposed` (handoff point to 1C's Phase 4).

Modify `orchestrator/cortex_runner.py` to replace the Phase 3 stub from 1A with real calls. Cost metric (`cost_tokens` + `cost_dollars`) accumulates across 3a + 3b + 3c LLM calls and is written to `cortex_cycles` row at Phase 6 archive (1A wires the column write; 1B populates the values).

---

## Fix/Feature 1: Phase 3a — Meta-reasoning + cap-5 enforcement

### Problem
No code today decides which domain capabilities are relevant to a signal. AO PM previously hardcoded `delegate_to_capability` calls; Cortex needs symmetric capability selection.

### Current State
- `capability_sets` table has 23 rows, with `trigger_patterns` jsonb array per row (verified via Task 3 query).
- 13 active domain capabilities post-Task-3: russo_ai, russo_at/ch/cy/de/fr/lu, research, finance, legal, marketing, pr_branding, sales + new game_theory (id=25).
- `wiki/matters/<slug>/cortex-config.md` has `games_relevant: true` (oskolkov) or `false` (other matters per Director ratification).
- LLM client `orchestrator.gemini_client.call_pro` verified at `orchestrator/gemini_client.py:140` per BAKER_MCP_EXTENSION_1 brief EXPLORE; we'll prefer Anthropic Claude Opus for Phase 3a meta (already used in capability_runner).

### Implementation

Create `orchestrator/cortex_phase3_reasoner.py` (~200 LOC).

```python
"""Cortex Phase 3a — meta-reasoning + capability selection.

Reads signal + Phase 2 load context, decides which domain capabilities
(≤5 per RA-23 Q4) should be invoked in Phase 3b. Returns JSON with
selected capabilities + reasoning notes.
"""
import json
import logging
import re
from typing import Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

CAP5_LIMIT = 5  # RA-23 Q4 ratified


@dataclass
class Phase3aResult:
    summary: str
    signal_classification: str
    capabilities_to_invoke: list[str]   # capped at CAP5_LIMIT
    reasoning_notes: str
    cost_tokens: int = 0
    cost_dollars: float = 0.0


async def run_phase3a_meta_reason(
    *,
    cycle_id: str,
    matter_slug: str,
    signal_text: str,
    phase2_context: dict[str, Any],
) -> Phase3aResult:
    """Meta-reasoning entry point.

    Algorithm:
    1. Load active capability_sets (where active=TRUE, capability_type='domain').
    2. For each capability, check if any trigger_patterns regex matches signal_text.
       Build candidate_pool (regex hits).
    3. Add cortex-config opt-ins (e.g., games_relevant=true → add game_theory if not already).
    4. If candidate_pool > CAP5_LIMIT, LLM ranks; else use all.
    5. LLM produces summary + classification + reasoning_notes for the selected set.

    Returns Phase3aResult.
    """
    # Step 1: load active domain capabilities + their trigger_patterns
    capabilities = await _load_active_domain_capabilities()

    # Step 2: regex match
    candidate_pool: list[str] = []
    matched_evidence: dict[str, list[str]] = {}
    for cap in capabilities:
        slug = cap["slug"]
        patterns = cap.get("trigger_patterns") or []
        if not isinstance(patterns, list):
            patterns = []
        hits = [p for p in patterns if re.search(p, signal_text or "", re.IGNORECASE)]
        if hits:
            candidate_pool.append(slug)
            matched_evidence[slug] = hits

    # Step 3: cortex-config opt-ins
    matter_config_text = (phase2_context or {}).get("matter_config", "")
    if "games_relevant: true" in matter_config_text and "game_theory" not in candidate_pool:
        # Auto-add game_theory if matter is game-relevant AND signal matches generic
        # negotiation-class patterns (always-relevant for AO/MOVIE)
        if any(re.search(p, signal_text or "", re.IGNORECASE)
               for p in [r"\boffer\b", r"\bproposal\b", r"\bsettlement\b",
                         r"\bnegotiation\b", r"\bcounterparty\b"]):
            candidate_pool.append("game_theory")

    # Step 4: cap-5 enforcement
    if len(candidate_pool) > CAP5_LIMIT:
        # LLM ranks (call Claude Opus with the candidate_pool + matched_evidence + signal)
        candidate_pool = await _llm_rank_candidates(
            signal_text=signal_text,
            matter_slug=matter_slug,
            candidates=candidate_pool,
            matched_evidence=matched_evidence,
            phase2_context=phase2_context,
        )
        candidate_pool = candidate_pool[:CAP5_LIMIT]

    # Step 5: LLM produces final summary + classification + reasoning
    result = await _llm_meta_reason(
        signal_text=signal_text,
        matter_slug=matter_slug,
        selected_capabilities=candidate_pool,
        matched_evidence={k: v for k, v in matched_evidence.items() if k in candidate_pool},
        phase2_context=phase2_context,
    )
    result.capabilities_to_invoke = candidate_pool

    # Persist Phase 3a output
    await _persist_phase3a(cycle_id, result, matched_evidence)

    return result


async def _load_active_domain_capabilities() -> list[dict]:
    """SELECT slug, trigger_patterns FROM capability_sets
       WHERE active=TRUE AND capability_type='domain'."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack()
    conn = store._get_conn()
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
        return [{"slug": r[0], "trigger_patterns": r[1]} for r in rows]
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to load active domain capabilities: {e}")
        return []
    finally:
        store._put_conn(conn)


async def _llm_rank_candidates(
    *, signal_text, matter_slug, candidates, matched_evidence, phase2_context,
) -> list[str]:
    """Stub: when candidates > CAP5_LIMIT, call Claude Opus to rank by relevance.
    For V1, simple heuristic: count regex hits per capability (more hits = higher rank).
    Override only via LLM if heuristic ties produce >5 candidates."""
    ranked = sorted(candidates, key=lambda s: len(matched_evidence.get(s, [])), reverse=True)
    if len(ranked) > CAP5_LIMIT:
        # Could escalate to LLM here; V1 trusts heuristic
        logger.info(f"Phase 3a: heuristic-ranked {len(candidates)} candidates → top-{CAP5_LIMIT}: {ranked[:CAP5_LIMIT]}")
    return ranked


async def _llm_meta_reason(
    *, signal_text, matter_slug, selected_capabilities, matched_evidence, phase2_context,
) -> Phase3aResult:
    """Call Claude Opus with structured prompt. Returns Phase3aResult."""
    # B-CODE: copy the exact LLM call pattern from capability_runner.py:run_single
    # (verified signature; uses anthropic_client + cost_monitor)
    # Stub here — real impl in B-code with verified signatures
    raise NotImplementedError("B-code: implement using existing anthropic_client + cost_monitor pattern")


async def _persist_phase3a(cycle_id: str, result: Phase3aResult, matched_evidence: dict) -> None:
    """INSERT row into cortex_phase_outputs (phase=reason, phase_order=3, artifact_type=meta_reason)."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        payload = {
            "summary": result.summary,
            "signal_classification": result.signal_classification,
            "capabilities_to_invoke": result.capabilities_to_invoke,
            "reasoning_notes": result.reasoning_notes,
            "matched_evidence": matched_evidence,
            "cost_tokens": result.cost_tokens,
            "cost_dollars": result.cost_dollars,
        }
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'reason', 3, 'meta_reason', %s::jsonb)
            """,
            (cycle_id, json.dumps(payload, default=str)),
        )
        cur.execute(
            "UPDATE cortex_cycles SET current_phase='reason', cost_tokens = cost_tokens + %s, "
            "cost_dollars = cost_dollars + %s WHERE cycle_id=%s",
            (result.cost_tokens, result.cost_dollars, cycle_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"_persist_phase3a failed for cycle {cycle_id}: {e}")
        raise
    finally:
        store._put_conn(conn)
```

### EXPLORE step before coding (Lesson #44)
B-code MUST grep:
- `capability_runner.run_single` to copy the canonical anthropic_client call pattern
- `cost_monitor.log_api_cost` signature for cost write
- Existing examples of jsonb-payload INSERT (Phase 1A's `_phase1_sense` is one)

### Key Constraints
- `re.IGNORECASE` flag mandatory (not inline `(?i)` per Lesson + python regex anti-pattern)
- LIMIT 30 on capability_sets SELECT
- Cap-5 is a HARD limit — never exceed even via LLM rank
- LLM cost MUST flow through `cost_monitor.log_api_cost` for Prometheus/billing

---

## Fix/Feature 2: Phase 3b — Specialist invocation (60s / 2-retry / fail-forward)

### Problem
Phase 3a selects up to 5 capabilities; Phase 3b actually invokes them with bounded resilience.

### Current State
- `orchestrator.capability_runner.run_single(capability_slug, ...) -> str` (verified line 198, sync). Returns capability output as string.
- No timeout / retry wrapping today; capability_runner inherits whatever timeout the underlying LLM client uses.

### Implementation

Create `orchestrator/cortex_phase3_invoker.py` (~150 LOC).

```python
"""Cortex Phase 3b — invoke selected specialists with 60s/2-retry/fail-forward."""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SPECIALIST_TIMEOUT_S = 60          # RA-23 Q5 ratified
SPECIALIST_MAX_RETRIES = 2         # RA-23 Q5 ratified


@dataclass
class SpecialistOutput:
    capability_slug: str
    output_text: str
    success: bool
    cost_tokens: int = 0
    cost_dollars: float = 0.0
    error: str | None = None
    duration_seconds: float = 0.0


@dataclass
class Phase3bResult:
    outputs: list[SpecialistOutput] = field(default_factory=list)
    total_cost_tokens: int = 0
    total_cost_dollars: float = 0.0


async def run_phase3b_invocations(
    *,
    cycle_id: str,
    matter_slug: str,
    signal_text: str,
    capabilities_to_invoke: list[str],
    phase2_context: dict,
) -> Phase3bResult:
    """Invoke each capability sequentially (cap-5 keeps total cycle time bounded).

    Per capability: run_single wrapped in asyncio.wait_for(60s) + 2 retries on TimeoutError.
    On final failure: persist failure row, continue to next capability (fail-forward).
    """
    result = Phase3bResult()
    for slug in capabilities_to_invoke:
        out = await _invoke_one(
            cycle_id=cycle_id,
            matter_slug=matter_slug,
            signal_text=signal_text,
            capability_slug=slug,
            phase2_context=phase2_context,
        )
        result.outputs.append(out)
        result.total_cost_tokens += out.cost_tokens
        result.total_cost_dollars += out.cost_dollars
        await _persist_specialist_output(cycle_id, out)

    # Update cycle row with cumulative Phase 3b cost
    await _bump_cycle_cost(cycle_id, result.total_cost_tokens, result.total_cost_dollars)
    return result


async def _invoke_one(
    *, cycle_id, matter_slug, signal_text, capability_slug, phase2_context,
) -> SpecialistOutput:
    """One capability invocation with 60s timeout + 2 retries."""
    import time
    from orchestrator.capability_runner import run_single

    last_err: str | None = None
    for attempt in range(1, SPECIALIST_MAX_RETRIES + 2):  # 1 + 2 retries = 3 attempts
        t0 = time.monotonic()
        try:
            output_text = await asyncio.wait_for(
                asyncio.to_thread(
                    run_single,
                    capability_slug,
                    # B-CODE: pass canonical kwargs after grep'ing run_single's actual signature
                    # — the subagent code map shows it's sync with multiple positional/kwarg
                    # context-loading args. Copy the call pattern from existing invocations
                    # in chain_runner.py._execute_plan (line 413).
                ),
                timeout=SPECIALIST_TIMEOUT_S,
            )
            elapsed = time.monotonic() - t0
            # Cost: B-CODE — extract from capability_runner's cost_monitor write OR
            # the LLM response object. Stub here.
            return SpecialistOutput(
                capability_slug=capability_slug,
                output_text=output_text or "",
                success=True,
                cost_tokens=0,  # B-CODE fill from cost_monitor
                cost_dollars=0.0,
                duration_seconds=elapsed,
            )
        except asyncio.TimeoutError:
            last_err = f"timeout after {SPECIALIST_TIMEOUT_S}s on attempt {attempt}"
            logger.warning(f"Phase 3b {capability_slug} attempt {attempt}: {last_err}")
        except Exception as e:
            last_err = f"exception on attempt {attempt}: {e}"
            logger.warning(f"Phase 3b {capability_slug} attempt {attempt}: {last_err}")

    # All retries failed — fail-forward (do NOT raise)
    return SpecialistOutput(
        capability_slug=capability_slug,
        output_text="",
        success=False,
        error=last_err,
        duration_seconds=0.0,
    )


async def _persist_specialist_output(cycle_id: str, out: SpecialistOutput) -> None:
    """INSERT cortex_phase_outputs row + write outputs/cortex_proposed_curated/<cycle_id>/<cap>.md."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        payload = {
            "capability_slug": out.capability_slug,
            "success": out.success,
            "output_text": out.output_text,
            "error": out.error,
            "cost_tokens": out.cost_tokens,
            "cost_dollars": out.cost_dollars,
            "duration_seconds": out.duration_seconds,
        }
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'reason', 4, 'specialist_invocation', %s::jsonb)
            """,
            (cycle_id, json.dumps(payload, default=str)),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"_persist_specialist_output failed: {e}")
    finally:
        store._put_conn(conn)

    # Also write proposed curated file for Phase 5 to relocate (1C territory)
    if out.success and out.output_text:
        try:
            today = datetime.now(timezone.utc).date().isoformat()
            staging_dir = Path("outputs/cortex_proposed_curated") / cycle_id
            staging_dir.mkdir(parents=True, exist_ok=True)
            staging_file = staging_dir / f"{out.capability_slug}-{today}.md"
            staging_file.write_text(
                f"# {out.capability_slug} output — cycle {cycle_id} — {today}\n\n{out.output_text}\n",
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Failed to write staging curated file: {e}")


async def _bump_cycle_cost(cycle_id: str, tokens: int, dollars: float) -> None:
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE cortex_cycles SET cost_tokens = cost_tokens + %s, "
            "cost_dollars = cost_dollars + %s WHERE cycle_id=%s",
            (tokens, dollars, cycle_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"_bump_cycle_cost failed: {e}")
    finally:
        store._put_conn(conn)
```

### Key Constraints
- `asyncio.wait_for` wraps each invocation, NOT the whole 3b loop (5×60s = 5 min worst case, but cap-5 + serial keeps it bounded)
- 5-min absolute cycle timeout (1A's outer wrap) is the umbrella; 3b's serial cap-5 fits inside
- **Lesson #44:** `run_single` exact signature MUST be re-verified in EXPLORE — subagent code map may have miss-signature; brief snippet uses positional only as placeholder
- Fail-forward = do NOT raise on capability failure; record error + continue. Phase 3c synthesis works on partial outputs.
- Staging dir `outputs/cortex_proposed_curated/<cycle_id>/` is intentionally ephemeral; 1C Phase 5 propagates to canonical wiki via Mac Mini SSH-mirror

---

## Fix/Feature 3: Phase 3c — Synthesis

### Problem
Phase 3a meta-reasoning + Phase 3b specialist outputs are raw artifacts. Phase 3c combines them with the matter's absorbed PM brain (cortex-config.md content) into a unified, Director-readable proposal text.

### Current State
- `capability_sets.slug='synthesizer'` exists with system_prompt (498 chars) — Director ratified absorption into Cortex Core (RA-23 §1).
- 1B absorbs synthesizer logic = uses synthesizer's system_prompt as the Phase 3c LLM system prompt.

### Implementation

Create `orchestrator/cortex_phase3_synthesizer.py` (~120 LOC).

```python
"""Cortex Phase 3c — synthesis. Absorbed synthesizer logic per RA-23.

Combines:
- Matter cortex-config (the absorbed AO PM / MOVIE AM brain)
- Phase 2 load context (curated knowledge + recent activity)
- Phase 3a meta-reasoning (signal classification + reasoning notes)
- Phase 3b specialist outputs (≤5)
→ unified proposal text + structured action recommendations.
"""
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Phase3cResult:
    proposal_text: str
    structured_actions: list[dict]   # [{action, rationale, target, deadline}, ...]
    cost_tokens: int = 0
    cost_dollars: float = 0.0


async def run_phase3c_synthesize(
    *,
    cycle_id: str,
    matter_slug: str,
    signal_text: str,
    phase2_context: dict,
    phase3a_result,        # Phase3aResult
    phase3b_result,        # Phase3bResult
) -> Phase3cResult:
    """Call Claude Opus with absorbed synthesizer prompt + all artifacts."""
    # 1. Load synthesizer system prompt from capability_sets
    synth_prompt = await _load_synthesizer_prompt()

    # 2. Build user message bundling artifacts
    user_msg = _build_user_message(
        matter_slug=matter_slug,
        signal_text=signal_text,
        phase2_context=phase2_context,
        phase3a_result=phase3a_result,
        phase3b_result=phase3b_result,
    )

    # 3. LLM call (Claude Opus per architecture §6 cache structure breakpoint 3)
    # B-CODE: copy anthropic_client call pattern from capability_runner
    proposal_text, cost_tokens, cost_dollars = await _llm_synthesize(synth_prompt, user_msg)

    # 4. Extract structured_actions from proposal_text (JSON block at the end)
    structured = _extract_actions(proposal_text)

    result = Phase3cResult(
        proposal_text=proposal_text,
        structured_actions=structured,
        cost_tokens=cost_tokens,
        cost_dollars=cost_dollars,
    )

    await _persist_phase3c(cycle_id, result)
    return result


async def _load_synthesizer_prompt() -> str:
    """SELECT system_prompt FROM capability_sets WHERE slug='synthesizer' AND active=TRUE."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT system_prompt FROM capability_sets WHERE slug='synthesizer' AND active=TRUE LIMIT 1"
        )
        row = cur.fetchone()
        cur.close()
        return (row[0] or "") if row else ""
    except Exception as e:
        conn.rollback()
        logger.error(f"_load_synthesizer_prompt failed: {e}")
        return ""
    finally:
        store._put_conn(conn)


def _build_user_message(*, matter_slug, signal_text, phase2_context, phase3a_result, phase3b_result) -> str:
    """Pack artifacts into a single user message for Phase 3c LLM call."""
    parts = [
        f"# Cortex Cycle Synthesis — {matter_slug}\n",
        f"## Signal\n{signal_text}\n",
        f"## Matter Brain (absorbed cortex-config)\n{phase2_context.get('matter_config', '')[:8000]}\n",
        f"## Phase 3a Meta-Reasoning\n",
        f"- Summary: {phase3a_result.summary}\n",
        f"- Classification: {phase3a_result.signal_classification}\n",
        f"- Reasoning: {phase3a_result.reasoning_notes}\n",
        f"## Phase 3b Specialist Outputs\n",
    ]
    for out in phase3b_result.outputs:
        parts.append(f"### {out.capability_slug} ({'OK' if out.success else 'FAILED'})\n")
        parts.append(out.output_text[:4000] if out.success else f"_(failed: {out.error})_\n")
    parts.append(
        "\n## Required Output Format\n"
        "Produce the unified proposal in markdown.\n"
        "End with a JSON code block containing structured_actions:\n"
        "```json\n"
        '[{"action": "...", "rationale": "...", "target": "...", "deadline": "YYYY-MM-DD"}, ...]\n'
        "```\n"
    )
    return "\n".join(parts)


async def _llm_synthesize(system_prompt: str, user_msg: str) -> tuple[str, int, float]:
    """Call Claude Opus via anthropic_client (signature copied from capability_runner)."""
    # B-CODE: implement using existing anthropic_client.call_opus or equivalent
    raise NotImplementedError("B-code: implement using existing anthropic_client + cost_monitor pattern")


def _extract_actions(proposal_text: str) -> list[dict]:
    """Extract trailing ```json block; return [] if missing/malformed."""
    import re
    m = re.search(r"```json\s*(\[.*?\])\s*```", proposal_text, re.DOTALL)
    if not m:
        return []
    try:
        return json.loads(m.group(1))
    except Exception as e:
        logger.warning(f"Failed to parse structured_actions: {e}")
        return []


async def _persist_phase3c(cycle_id: str, result: Phase3cResult) -> None:
    """INSERT phase=reason artifact_type=synthesis + flip cycle status to 'proposed'."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        payload = {
            "proposal_text": result.proposal_text,
            "structured_actions": result.structured_actions,
            "cost_tokens": result.cost_tokens,
            "cost_dollars": result.cost_dollars,
        }
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'reason', 5, 'synthesis', %s::jsonb)
            """,
            (cycle_id, json.dumps(payload, default=str)),
        )
        cur.execute(
            """
            UPDATE cortex_cycles
            SET status='proposed', current_phase='reason',
                cost_tokens = cost_tokens + %s, cost_dollars = cost_dollars + %s
            WHERE cycle_id=%s
            """,
            (result.cost_tokens, result.cost_dollars, cycle_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"_persist_phase3c failed: {e}")
        raise
    finally:
        store._put_conn(conn)
```

---

## Fix/Feature 4: Wire Phase 3 into `cortex_runner.py`

### Implementation
Modify `orchestrator/cortex_runner.py` (1A-shipped). Replace the Phase 3 stub block with real calls. Insertion point: after `_phase2_load(cycle)` returns, before `_phase6_archive(cycle)`.

```python
# In _run_cycle_inner, replace 1A stub with:
cycle.current_phase = "reason"
try:
    from orchestrator.cortex_phase3_reasoner import run_phase3a_meta_reason
    from orchestrator.cortex_phase3_invoker import run_phase3b_invocations
    from orchestrator.cortex_phase3_synthesizer import run_phase3c_synthesize

    # 3a — meta-reasoning + capability selection
    phase3a = await run_phase3a_meta_reason(
        cycle_id=cycle.cycle_id,
        matter_slug=cycle.matter_slug,
        signal_text=cycle.phase2_load_context.get("signal_text", ""),  # pulled from Phase 2 context
        phase2_context=cycle.phase2_load_context,
    )
    cycle.cost_tokens += phase3a.cost_tokens
    cycle.cost_dollars += phase3a.cost_dollars

    # 3b — specialist invocations (cap-5)
    phase3b = await run_phase3b_invocations(
        cycle_id=cycle.cycle_id,
        matter_slug=cycle.matter_slug,
        signal_text=cycle.phase2_load_context.get("signal_text", ""),
        capabilities_to_invoke=phase3a.capabilities_to_invoke,
        phase2_context=cycle.phase2_load_context,
    )
    cycle.cost_tokens += phase3b.total_cost_tokens
    cycle.cost_dollars += phase3b.total_cost_dollars

    # 3c — synthesis
    phase3c = await run_phase3c_synthesize(
        cycle_id=cycle.cycle_id,
        matter_slug=cycle.matter_slug,
        signal_text=cycle.phase2_load_context.get("signal_text", ""),
        phase2_context=cycle.phase2_load_context,
        phase3a_result=phase3a,
        phase3b_result=phase3b,
    )
    cycle.cost_tokens += phase3c.cost_tokens
    cycle.cost_dollars += phase3c.cost_dollars
    cycle.status = "proposed"  # handoff to 1C Phase 4
except Exception as e:
    logger.error(f"Phase 3 failed for cycle {cycle.cycle_id}: {e}")
    cycle.status = "failed"
    cycle.aborted_reason = f"phase3_error: {e}"
    # Continue to Phase 6 archive — failure is recorded
```

### EXPLORE step before coding
B-code MUST also ensure 1A's `_phase2_load` populates `cycle.phase2_load_context['signal_text']` — if 1A omitted this, brief amendment for 1A is required. Verify by running 1A pytest first then grepping `_phase2_load` for `signal_text` write.

---

## Files Modified

**Create (3):**
- `orchestrator/cortex_phase3_reasoner.py`
- `orchestrator/cortex_phase3_invoker.py`
- `orchestrator/cortex_phase3_synthesizer.py`

**Modify (1):**
- `orchestrator/cortex_runner.py` — replace Phase 3 stub block (1A line ref `cycle.status = "awaiting_reason"`) with real calls

**Tests (NEW):**
- `tests/test_cortex_phase3_reasoner.py` (≥10 cases: cap-5 enforcement, regex match, opt-in `games_relevant`, no-match fallback, LLM fallback)
- `tests/test_cortex_phase3_invoker.py` (≥10 cases: timeout/retry/fail-forward, success path, partial-failure, staging file write)
- `tests/test_cortex_phase3_synthesizer.py` (≥6 cases: synthesizer-prompt-load, JSON action extract, structured-actions parse fail, cost accumulation, status transition)

## Files NOT to touch
- `orchestrator/chain_runner.py` — no edits
- `orchestrator/capability_runner.py` — `run_single` reused as-is
- 1A migrations / Phase 1/2/6 code — no edits (1B builds on 1A's cycle row)
- Slack endpoints / proposal card — 1C territory
- Wiki write paths — 1C territory (1B writes to staging dir only)

---

## Code Brief Standards (mandatory)

- **API version:** Anthropic Claude Opus + Gemini Pro via existing clients (`anthropic_client`, `gemini_client.call_pro`); production-active 2026-04-28
- **Deprecation check date:** 2026-04-28 verified — Claude Opus 4.7 + Gemini 2.5 Pro both production-wired
- **Fallback:** Phase 3 LLM failure → cycle status='failed' + Phase 6 archive still runs (status preserved); cap-5 hit doesn't raise (heuristic ranks)
- **DDL drift check:** N/A (1B adds no Postgres tables; only writes existing `cortex_phase_outputs` from 1A)
- **Literal pytest output mandatory:** Ship report MUST include literal `pytest tests/test_cortex_phase3_*.py -v` stdout. ≥26 tests. NO "by inspection."
- **Function-signature verification (Lesson #44):** B-code MUST grep before coding:
  - `def run_single` in `orchestrator/capability_runner.py` (verified line 198 in subagent map; re-confirm exact kwargs)
  - `cost_monitor.log_api_cost` signature
  - `anthropic_client.call_opus` (or canonical Opus call) — copy pattern verbatim from `capability_runner`
- **Cost instrumentation:** every Phase 3a/3b/3c LLM call MUST flow tokens + dollars through cost_monitor AND accumulate into `cortex_cycles.cost_tokens` / `cost_dollars`

## Verification criteria

1. `pytest tests/test_cortex_phase3_*.py -v` ≥26 tests pass, 0 regressions in `tests/test_cortex_runner_phase126.py` (1A's tests).
2. End-to-end Python REPL test: `await maybe_run_cycle(matter_slug='oskolkov', triggered_by='director', director_question='AO threatens late fee')` → returns CortexCycle with status='proposed' (NOT 'awaiting_reason'), 5+ rows in cortex_phase_outputs (sense, load, meta_reason, ≥1 specialist_invocation, synthesis), cost_tokens > 0, cost_dollars > 0.
3. Cap-5 enforcement: signal text matching 8 capability triggers → only top-5 invoked. Verified by `SELECT COUNT(DISTINCT payload->>'capability_slug') FROM cortex_phase_outputs WHERE artifact_type='specialist_invocation' AND cycle_id=<id>` ≤ 5.
4. Specialist timeout test: stub `run_single` to sleep 70s → 60s timeout fires + 2 retries + final SpecialistOutput.success=False (NOT exception); cycle continues.
5. Specialist failure: 1 capability fails → other 4 still complete → Phase 3c synthesizes from partial outputs.
6. Cost accumulation: cycle's `cost_tokens` = sum(phase3a, phase3b, phase3c, phase4 if any) and matches `SELECT SUM(payload->>'cost_tokens') FROM cortex_phase_outputs WHERE cycle_id=<id>`.
7. `python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase3_reasoner.py', doraise=True); ..."` exits 0 for all 3 new modules.

## Quality Checkpoints

1. Cap-5 is enforced in Phase 3a — never invoked >5 specialists per cycle (verified by test + production query)
2. `re.IGNORECASE` flag used (no inline `(?i)`)
3. Fail-forward: 1 specialist failure ≠ cycle failure
4. Cost flows to both `cortex_cycles.cost_tokens` AND `cost_monitor.log_api_cost` (no double-count or missing-write)
5. Synthesizer system_prompt loaded from `capability_sets.slug='synthesizer'` row (not hardcoded)
6. Phase 3c JSON extraction graceful: malformed JSON → `[]`, not crash
7. Staging dir `outputs/cortex_proposed_curated/<cycle_id>/` created with parents=True, exist_ok=True
8. 1A's outer 5-min `asyncio.wait_for` still wraps the cycle (1B inherits — verify by stub test)
9. Status transitions: in_flight → reason (during 3a) → proposed (after 3c) OR failed (on Phase 3 exception)
10. No new entries in `requirements.txt`

## Verification SQL

```sql
-- After E2E REPL test, expected output:
SELECT phase, phase_order, artifact_type, payload->>'capability_slug' AS slug
FROM cortex_phase_outputs
WHERE cycle_id=(SELECT cycle_id FROM cortex_cycles WHERE matter_slug='oskolkov' ORDER BY started_at DESC LIMIT 1)
ORDER BY phase_order;
-- Expected ≥5 rows: (sense, 1, cycle_init, NULL),
--                    (load, 2, phase2_context, NULL),
--                    (reason, 3, meta_reason, NULL),
--                    (reason, 4, specialist_invocation, '<cap-slug>'),  -- 1..5 of these
--                    (reason, 5, synthesis, NULL),
--                    (archive, 6, cycle_archive, NULL)

-- Cap-5 verification:
SELECT cycle_id, COUNT(*) AS specialist_count
FROM cortex_phase_outputs
WHERE artifact_type='specialist_invocation'
GROUP BY cycle_id
HAVING COUNT(*) > 5;
-- Expected: 0 rows (cap-5 always honored)

-- Cost accumulation:
SELECT c.cycle_id, c.cost_tokens AS cycle_total,
       (SELECT SUM((payload->>'cost_tokens')::int) FROM cortex_phase_outputs WHERE cycle_id=c.cycle_id) AS phase_sum
FROM cortex_cycles c
WHERE matter_slug='oskolkov' AND status='proposed';
-- Expected: cycle_total ≈ phase_sum (within rounding)
```

## Out of scope

- Phase 4 proposal card / 4-button rendering / Slack Block Kit (1C)
- Phase 5 act / GOLD propagation to wiki (1C)
- Phase 5 final-freshness check on Approve (1C)
- Director Refresh button → re-run Phase 2+3 (1C — Q3 of refresh-cycle)
- DRY_RUN flag for log-only first cycle (1C)
- Step 33 rollback script (1C)
- LLM model bump to 4.7 (separate brief; not in any 1A/1B/1C)
- Wiki write of curated knowledge (1C uses Mac Mini SSH-mirror; 1B stages locally only)

## Branch + PR

- Branch: `cortex-3t-formalize-1b`
- PR title: `CORTEX_3T_FORMALIZE_1B: Phase 3a/3b/3c (reason / invoke / synthesize)`
- Reviewer: B1 second-pair (MEDIUM trigger class — LLM API + cost writes + cross-capability) → AI Head B Tier-A merge on APPROVE + `/security-review` skill PASS

## Co-Authored-By

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
