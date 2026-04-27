# BRIEF: CORTEX_3T_FORMALIZE_1C — Phase 4/5 + scheduler + dry-run + rollback

**Milestone:** Cortex Stage 2 V1 (Steps 22-29 + Step 33 in `_ops/processes/cortex-stage2-v1-tracker.md`)
**Source spec:** `_ops/ideas/2026-04-27-cortex-3t-formalize-spec.md` + `_ops/processes/cortex-architecture-final.md`
**Estimated time:** ~14h
**Complexity:** High (Slack Block Kit interactive cards + new endpoint + GOLD propagation + scheduler + dry-run flag + rollback script)
**Trigger class:** MEDIUM (new endpoint + Slack interactive + APScheduler + cross-capability state writes + decommission rollback) → B1 second-pair-review pre-merge
**Prerequisites:** `BRIEF_CORTEX_3T_FORMALIZE_1A` shipped (cycle row + Phase 1/2/6) AND `BRIEF_CORTEX_3T_FORMALIZE_1B` shipped (Phase 3 produces synthesis + status='proposed')
**Companion sub-briefs:** 1A (foundation) + 1B (reasoning)

---

## Context

Sub-brief **1C of 3** — the interface + ops layer. 1A landed cycle persistence + Phase 1/2/6. 1B landed Phase 3 reasoning. 1C completes the cycle: Phase 4 produces a 4-button Slack proposal card with per-file Gold checkboxes; Phase 5 acts on Director's choice + propagates GOLD to curated knowledge files; APScheduler weekly matter-config drift job goes live; Step 29 DRY_RUN flag for log-only first cycle; Step 33 rollback script committed BEFORE Step 34-35 decommission of `ao_signal_detector` + `ao_project_state` (Director-consult cutover, not in this brief).

Anthropic Memory dead per Director 2026-04-28 — uses Postgres + wiki + Slack only.

---

## Problem

After 1A+1B, Cortex cycles complete to status='proposed' but produce nothing visible to Director. No Slack card, no buttons, no way to action a proposal. Curated knowledge layer is staged in `outputs/cortex_proposed_curated/<cycle_id>/` but never propagates to `wiki/matters/<slug>/curated/`. Matter-config drift detection has no scheduler. No safe-cutover path exists.

## Solution

Six pieces:
1. Phase 4 (propose) — render Slack Block Kit message with 4 action buttons (✅ Approve / ✏️ Edit / 🔄 Refresh / ❌ Reject) + per-file Gold checkboxes (per RA-23 Q2 ratification).
2. New endpoint `POST /cortex/cycle/{id}/action` — receives Slack interactivity webhook, dispatches to button handlers.
3. Phase 5 (act) — on Approve: final-freshness check + execute structured_actions + write GOLD entries via `gold_writer.append()` + propagate staged curated files to canonical wiki location via Mac Mini SSH-mirror.
4. APScheduler `_matter_config_drift_weekly_job` — Mon 11:00 UTC, mirrors `ai_head_weekly_audit_job` pattern, flags configs not updated >30d.
5. Step 29 DRY_RUN flag — env var `CORTEX_DRY_RUN=true` causes Phase 5 to log-only (no Slack post, no GOLD writes, no curated propagation, no structured_actions execution); cycle row tagged `dry_run=true`. First production cycle on AO matter ships under DRY_RUN.
6. Step 33 rollback script — `scripts/cortex_rollback_v1.sh` committed BEFORE Step 34-35 decommission. Restores `ao_signal_detector` direct trigger + `ao_project_state` Postgres reads. Director-only manual fire, <5min RTO target.

---

## Fix/Feature 1: Phase 4 — Proposal card with 4 buttons + per-file Gold checkboxes

### Problem
No Slack-side surface for Director to action Cortex proposals.

### Current State
- `outputs/dashboard.py` has Slack DM helper pattern (search for `_safe_post_dm` per subagent map). Block Kit is supported (Slack MCP `slack_send_message` accepts `blocks`).
- Phase 3c synthesis output (1B) is `proposal_text` (markdown) + `structured_actions` (JSON list).
- PR #66 GOLD workflow: `kbl/gold_writer.append(GoldEntry)` + `kbl/gold_proposer.propose(ProposedGoldEntry)` are the canonical write paths. RA-23 Q2 ratifies per-file checkbox UI extension.

### Implementation

Create `orchestrator/cortex_phase4_proposal.py` (~250 LOC).

```python
"""Cortex Phase 4 — proposal card. Slack Block Kit + 4 buttons + per-file Gold checkboxes."""
import json
import logging
import os
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ProposalCard:
    proposal_id: str
    cycle_id: str
    matter_slug: str
    proposal_text: str
    structured_actions: list[dict]
    proposed_gold_entries: list[dict]   # [{filename, content, default_checked}, ...]
    blocks: list[dict]                   # Slack Block Kit payload


async def run_phase4_propose(*, cycle_id: str, matter_slug: str, phase3c_result) -> ProposalCard:
    """Render proposal card + post to Slack DM (or skip in DRY_RUN)."""
    proposal_id = str(uuid.uuid4())

    # 1. Build proposed Gold entries from structured_actions + matter context
    proposed_gold = await _build_proposed_gold_entries(
        cycle_id=cycle_id,
        matter_slug=matter_slug,
        structured_actions=phase3c_result.structured_actions,
        proposal_text=phase3c_result.proposal_text,
    )

    # 2. Build Slack Block Kit payload (4 buttons + per-file Gold checkbox group)
    blocks = _build_blocks(
        proposal_id=proposal_id,
        cycle_id=cycle_id,
        matter_slug=matter_slug,
        proposal_text=phase3c_result.proposal_text,
        structured_actions=phase3c_result.structured_actions,
        proposed_gold=proposed_gold,
    )

    card = ProposalCard(
        proposal_id=proposal_id,
        cycle_id=cycle_id,
        matter_slug=matter_slug,
        proposal_text=phase3c_result.proposal_text,
        structured_actions=phase3c_result.structured_actions,
        proposed_gold_entries=proposed_gold,
        blocks=blocks,
    )

    # 3. Persist proposal_id on cycle row + cortex_phase_outputs row
    await _persist_phase4(cycle_id, card)

    # 4. Post to Slack DM (skip in DRY_RUN)
    if os.getenv("CORTEX_DRY_RUN", "false").lower() == "true":
        logger.info(f"[CORTEX_DRY_RUN] Would post Slack card for cycle {cycle_id} (skipping)")
        await _mark_dry_run(cycle_id)
    else:
        await _post_to_slack(card)

    return card


def _build_blocks(*, proposal_id, cycle_id, matter_slug, proposal_text, structured_actions, proposed_gold) -> list:
    """Slack Block Kit. 4 action buttons + per-file Gold checkbox group."""
    blocks = []
    # Header
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": f"Cortex proposal — {matter_slug}"},
    })
    # Proposal markdown body
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": proposal_text[:2900]},   # 3000-char Slack section limit
    })
    # Structured actions summary (compact)
    if structured_actions:
        actions_md = "\n".join(
            f"• *{a.get('action', '?')}* — {a.get('rationale', '')[:120]}"
            for a in structured_actions[:5]
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Proposed actions:*\n{actions_md}"},
        })
    # Per-file Gold checkboxes (RA-23 Q2 — Director can deselect)
    if proposed_gold:
        options = [
            {
                "text": {"type": "plain_text", "text": entry["filename"][:75]},
                "value": entry["filename"],
            }
            for entry in proposed_gold[:10]   # Slack max 10 options per checkbox group
        ]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Proposed Gold updates* (uncheck to skip):"},
            "accessory": {
                "type": "checkboxes",
                "action_id": f"cortex_gold_select_{proposal_id}",
                "options": options,
                "initial_options": options,   # all checked by default
            },
        })
    # 4 action buttons
    blocks.append({
        "type": "actions",
        "block_id": f"cortex_actions_{proposal_id}",
        "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "✅ Approve"},
             "style": "primary", "action_id": "cortex_approve",
             "value": json.dumps({"cycle_id": cycle_id, "proposal_id": proposal_id})},
            {"type": "button", "text": {"type": "plain_text", "text": "✏️ Edit"},
             "action_id": "cortex_edit",
             "value": json.dumps({"cycle_id": cycle_id, "proposal_id": proposal_id})},
            {"type": "button", "text": {"type": "plain_text", "text": "🔄 Refresh"},
             "action_id": "cortex_refresh",
             "value": json.dumps({"cycle_id": cycle_id, "proposal_id": proposal_id})},
            {"type": "button", "text": {"type": "plain_text", "text": "❌ Reject"},
             "style": "danger", "action_id": "cortex_reject",
             "value": json.dumps({"cycle_id": cycle_id, "proposal_id": proposal_id})},
        ],
    })
    return blocks


async def _build_proposed_gold_entries(*, cycle_id, matter_slug, structured_actions, proposal_text) -> list[dict]:
    """Read staged curated files at outputs/cortex_proposed_curated/<cycle_id>/*.md.
    Each file becomes a Director-toggleable Gold entry."""
    from pathlib import Path
    staging = Path("outputs/cortex_proposed_curated") / cycle_id
    if not staging.is_dir():
        return []
    return [
        {
            "filename": f.name,
            "content": f.read_text(encoding="utf-8", errors="replace"),
            "default_checked": True,
        }
        for f in sorted(staging.glob("*.md"))[:10]
    ]


async def _persist_phase4(cycle_id: str, card: ProposalCard) -> None:
    """INSERT phase=propose row + UPDATE cycle.proposal_id + status='tier_b_pending'."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        payload = {
            "proposal_id": card.proposal_id,
            "proposal_text": card.proposal_text[:8000],
            "structured_actions": card.structured_actions,
            "proposed_gold_entries": [{"filename": e["filename"]} for e in card.proposed_gold_entries],
            "slack_blocks": card.blocks,
        }
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'propose', 7, 'proposal_card', %s::jsonb)
            """,
            (cycle_id, json.dumps(payload, default=str)),
        )
        cur.execute(
            "UPDATE cortex_cycles SET proposal_id=%s, status='tier_b_pending', current_phase='propose' "
            "WHERE cycle_id=%s",
            (card.proposal_id, cycle_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"_persist_phase4 failed: {e}")
        raise
    finally:
        store._put_conn(conn)


async def _post_to_slack(card: ProposalCard) -> None:
    """Post Block Kit card to Director DM channel.

    B-CODE: copy the canonical _safe_post_dm pattern from triggers/ai_head_audit.py.
    Director Slack ID: U0ADW5FT5FH (verified 2026-04-28 via slack_search_users).
    """
    raise NotImplementedError("B-code: implement using existing _safe_post_dm with blocks=card.blocks")


async def _mark_dry_run(cycle_id: str) -> None:
    """In DRY_RUN, append a tag to cortex_phase_outputs payload + log to scheduler_executions."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'propose', 8, 'dry_run_marker',
                    '{"reason": "CORTEX_DRY_RUN=true; Slack post skipped"}'::jsonb)
            """,
            (cycle_id,),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"_mark_dry_run failed: {e}")
    finally:
        store._put_conn(conn)
```

---

## Fix/Feature 2: `POST /cortex/cycle/{id}/action` endpoint

### Problem
Slack button clicks need to land on a baker-master endpoint. No `/cortex/*` routes exist today.

### Current State
- `outputs/dashboard.py` exposes FastAPI app. Search-and-verify: `grep -n '"/cortex"' outputs/dashboard.py` → 0 matches (verified). Free path.
- Slack interactivity webhook signs requests with HMAC; existing helper for verification may exist (B-code grep `slack_signature` or `verify_slack`).

### Implementation

Add to `outputs/dashboard.py` at the END of the route block (B-code MUST grep `@app.post("/api/scan"` — line 7351 per BAKER_MCP_EXTENSION_1 brief — and add new route nearby in the dashboard-v3/scan section).

```python
@app.post("/cortex/cycle/{cycle_id}/action", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def cortex_cycle_action(cycle_id: str, request: Request):
    """Director clicked a button on the Cortex proposal card.

    Body shape (Slack interactivity OR direct API):
        {"action": "approve|edit|refresh|reject",
         "edits": "optional new text",
         "selected_gold_files": ["optional", "list"],
         "reason": "optional rejection reason"}
    """
    body = await request.json()
    action = body.get("action")
    if action not in ("approve", "edit", "refresh", "reject"):
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    from orchestrator.cortex_phase5_act import (
        cortex_approve, cortex_edit, cortex_refresh, cortex_reject,
    )
    handlers = {
        "approve": cortex_approve,
        "edit": cortex_edit,
        "refresh": cortex_refresh,
        "reject": cortex_reject,
    }
    try:
        result = await handlers[action](cycle_id=cycle_id, body=body)
        return {"status": "ok", "action": action, "result": result}
    except Exception as e:
        logger.error(f"/cortex/cycle/{cycle_id}/action [{action}] failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

EXPLORE: B-code MUST also wire the Slack interactivity webhook. If a `/slack/interactivity` endpoint already exists, dispatch by `action_id` prefix (`cortex_approve` / `cortex_edit` / `cortex_refresh` / `cortex_reject`) → call `cortex_cycle_action` with parsed body. Else add a new endpoint with HMAC signature verification (Slack signing secret env var typically `SLACK_SIGNING_SECRET`).

---

## Fix/Feature 3: Phase 5 — Act + GOLD propagation + curated knowledge wiki write

### Implementation

Create `orchestrator/cortex_phase5_act.py` (~300 LOC).

```python
"""Cortex Phase 5 — act on Director's button press.

cortex_approve: final-freshness check → execute structured_actions →
                write GOLD entries → propagate staged curated → archive.
cortex_edit: save edits → re-render → status stays tier_b_pending.
cortex_refresh: re-run Phase 2+3 → replace card in place.
cortex_reject: archive cycle status='rejected' + feedback_ledger row.
"""
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DIRECTOR_EMAILS = {"dvallen@brisengroup.com", "vallen300@gmail.com"}
DRY_RUN = os.getenv("CORTEX_DRY_RUN", "false").lower() == "true"
FRESHNESS_WINDOW_MIN = 30


async def cortex_approve(*, cycle_id: str, body: dict) -> dict:
    """1. Final-freshness check (last 30 min activity scan).
    2. If fresh → warn Director (return 'freshness_warning').
    3. Else → execute structured_actions + write Gold + propagate curated + archive."""
    if not await _is_fresh(cycle_id):
        return {"warning": "freshness_check_failed", "advice": "refresh_first"}

    if DRY_RUN:
        logger.info(f"[CORTEX_DRY_RUN] cortex_approve cycle={cycle_id} (no execute)")
        await _archive_cycle(cycle_id, status="approved", director_action="gold_approved")
        return {"status": "dry_run_approved"}

    # Execute structured_actions (1C V1: log-only — V2 wires to baker_actions)
    cycle_data = await _load_cycle(cycle_id)
    actions = (cycle_data.get("structured_actions") or [])
    for a in actions:
        logger.info(f"Cortex action [logged-only V1]: {a}")

    # Write Gold entries (per-file checkbox respect)
    selected = body.get("selected_gold_files") or []
    await _write_gold_entries(cycle_id=cycle_id, selected_files=selected)

    # Propagate staged curated → wiki/matters/<slug>/curated/ via Mac Mini SSH-mirror
    await _propagate_curated_via_macmini(cycle_id=cycle_id, matter_slug=cycle_data["matter_slug"])

    await _archive_cycle(cycle_id, status="approved", director_action="gold_approved")
    return {"status": "approved", "actions_logged": len(actions), "gold_files_written": len(selected)}


async def cortex_edit(*, cycle_id: str, body: dict) -> dict:
    """Save edited proposal text. Cycle status stays tier_b_pending."""
    edits = body.get("edits", "").strip()
    if not edits:
        return {"warning": "no_edits_provided"}
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'propose', 9, 'director_edit', %s::jsonb)
            """,
            (cycle_id, json.dumps({"edited_text": edits})),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"cortex_edit failed: {e}")
        raise
    finally:
        store._put_conn(conn)
    return {"status": "edits_saved"}


async def cortex_refresh(*, cycle_id: str, body: dict) -> dict:
    """Re-run Phase 2 + Phase 3 with fresh data. Replaces the card in place."""
    cycle_data = await _load_cycle(cycle_id)
    matter_slug = cycle_data["matter_slug"]
    from orchestrator.cortex_runner import _phase2_load
    from orchestrator.cortex_phase3_reasoner import run_phase3a_meta_reason
    from orchestrator.cortex_phase3_invoker import run_phase3b_invocations
    from orchestrator.cortex_phase3_synthesizer import run_phase3c_synthesize
    from orchestrator.cortex_runner import CortexCycle

    # Reconstruct minimal CortexCycle to pass through loaders
    cycle = CortexCycle(
        cycle_id=cycle_id,
        matter_slug=matter_slug,
        triggered_by="refresh",
    )
    await _phase2_load(cycle)
    phase3a = await run_phase3a_meta_reason(
        cycle_id=cycle.cycle_id,
        matter_slug=matter_slug,
        signal_text=cycle.phase2_load_context.get("signal_text", ""),
        phase2_context=cycle.phase2_load_context,
    )
    phase3b = await run_phase3b_invocations(
        cycle_id=cycle.cycle_id,
        matter_slug=matter_slug,
        signal_text=cycle.phase2_load_context.get("signal_text", ""),
        capabilities_to_invoke=phase3a.capabilities_to_invoke,
        phase2_context=cycle.phase2_load_context,
    )
    phase3c = await run_phase3c_synthesize(
        cycle_id=cycle.cycle_id,
        matter_slug=matter_slug,
        signal_text=cycle.phase2_load_context.get("signal_text", ""),
        phase2_context=cycle.phase2_load_context,
        phase3a_result=phase3a,
        phase3b_result=phase3b,
    )
    # Replace card via new Phase 4
    from orchestrator.cortex_phase4_proposal import run_phase4_propose
    new_card = await run_phase4_propose(
        cycle_id=cycle.cycle_id, matter_slug=matter_slug, phase3c_result=phase3c
    )
    return {"status": "refreshed", "new_proposal_id": new_card.proposal_id}


async def cortex_reject(*, cycle_id: str, body: dict) -> dict:
    """Archive cycle status='rejected'. Capture optional reason. Write feedback_ledger row."""
    reason = (body.get("reason") or "").strip() or "no_reason_given"
    await _archive_cycle(cycle_id, status="rejected", director_action="gold_rejected")
    await _write_feedback_ledger(cycle_id=cycle_id, action="rejected", reason=reason)
    return {"status": "rejected", "reason": reason}


# --- helpers ---

async def _is_fresh(cycle_id: str) -> bool:
    """Final-freshness check — return True if no Director activity on this matter in last 30 min."""
    from memory.store_back import SentinelStoreBack
    cycle = await _load_cycle(cycle_id)
    matter_slug = cycle["matter_slug"]
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT created_at FROM sent_emails
                WHERE created_at >= NOW() - INTERVAL '%s minutes'
                  AND (subject ILIKE %s OR body ILIKE %s)
                LIMIT 5
            ) recent
            """,
            (FRESHNESS_WINDOW_MIN, f"%{matter_slug}%", f"%{matter_slug}%"),
        )
        recent = (cur.fetchone() or [0])[0]
        cur.close()
        return recent == 0
    except Exception as e:
        conn.rollback()
        logger.error(f"_is_fresh failed: {e}")
        return True   # fail-open — better to act than block on error
    finally:
        store._put_conn(conn)


async def _load_cycle(cycle_id: str) -> dict:
    """Read cortex_cycles + most-recent synthesis artifact from cortex_phase_outputs."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT matter_slug, proposal_id, status FROM cortex_cycles WHERE cycle_id=%s LIMIT 1",
            (cycle_id,),
        )
        row = cur.fetchone()
        if not row:
            return {}
        matter_slug, proposal_id, status = row
        cur.execute(
            """
            SELECT payload FROM cortex_phase_outputs
            WHERE cycle_id=%s AND artifact_type='synthesis'
            ORDER BY created_at DESC LIMIT 1
            """,
            (cycle_id,),
        )
        synth_row = cur.fetchone()
        cur.close()
        synth = synth_row[0] if synth_row else {}
        return {
            "cycle_id": cycle_id,
            "matter_slug": matter_slug,
            "proposal_id": proposal_id,
            "status": status,
            "structured_actions": (synth or {}).get("structured_actions") or [],
        }
    except Exception as e:
        conn.rollback()
        logger.error(f"_load_cycle failed: {e}")
        return {}
    finally:
        store._put_conn(conn)


async def _write_gold_entries(*, cycle_id: str, selected_files: list[str]) -> None:
    """For each selected_file, build a GoldEntry + call gold_writer.append.

    EXPLORE: B-code MUST verify gold_writer.append signature (subagent map line 79).
    GoldEntry fields: iso_date, topic, ratification_quote, background, resolution,
    authority_chain, carry_forward (default 'none'), matter (Optional[str]).
    """
    from kbl.gold_writer import GoldEntry, append
    cycle = await _load_cycle(cycle_id)
    matter_slug = cycle.get("matter_slug")
    today = datetime.now(timezone.utc).date().isoformat()
    for filename in selected_files:
        # B-code: build GoldEntry from cycle.proposal_text + filename context
        # V1: skeleton entry; LLM-extracted topic/resolution can be added in V2
        entry = GoldEntry(
            iso_date=today,
            topic=f"Cortex cycle {cycle_id[:8]} — {filename}",
            ratification_quote="(Director approved via Cortex Phase 5 button)",
            background="See cortex_phase_outputs for full proposal text.",
            resolution=f"See {filename} for capability output.",
            authority_chain=f"Director GOLD via Cortex cycle {cycle_id}",
            carry_forward="none",
            matter=matter_slug,
        )
        try:
            append(entry)
        except Exception as e:
            logger.error(f"gold_writer.append failed for {filename}: {e}")


async def _propagate_curated_via_macmini(*, cycle_id: str, matter_slug: str) -> None:
    """SSH-mirror staged curated files to baker-vault wiki/matters/<slug>/curated/.

    EXPLORE: B-code MUST grep for canonical Mac Mini SSH-mirror invocation pattern.
    Likely existing helper at scripts/macmini_*.sh or similar.
    Fallback: log staging path; Director (or weekly job) propagates manually.
    """
    staging = Path("outputs/cortex_proposed_curated") / cycle_id
    if not staging.is_dir():
        return
    target_remote = f"~/baker-vault/wiki/matters/{matter_slug}/curated/"
    # B-code: invoke `ssh macmini "mkdir -p {target_remote} && rsync ..."` or
    # equivalent. Wrap in subprocess.run with timeout=30.
    # V1 fallback: log only — Director propagates via Mac Mini script run.
    logger.info(f"Curated propagation staged for cycle {cycle_id} → {target_remote}")
    logger.info(f"Files: {[f.name for f in staging.glob('*.md')]}")
    # B-code: implement subprocess.run when Mac Mini SSH pattern is verified


async def _archive_cycle(cycle_id: str, *, status: str, director_action: str | None = None) -> None:
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE cortex_cycles
            SET status=%s, director_action=%s,
                completed_at=COALESCE(completed_at, NOW()),
                current_phase='archive'
            WHERE cycle_id=%s
            """,
            (status, director_action, cycle_id),
        )
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'archive', 10, 'final_archive', %s::jsonb)
            """,
            (cycle_id, json.dumps({"status": status, "director_action": director_action})),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"_archive_cycle failed: {e}")
        raise
    finally:
        store._put_conn(conn)


async def _write_feedback_ledger(*, cycle_id: str, action: str, reason: str) -> None:
    """INSERT row into feedback_ledger linking cycle to Director's verdict.

    EXPLORE: B-code MUST verify feedback_ledger column names via
    information_schema before writing INSERT.
    """
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        # B-code: replace with verified column list
        cur.execute(
            """
            INSERT INTO feedback_ledger (cycle_id, feedback_type, payload, created_at)
            VALUES (%s, %s, %s::jsonb, NOW())
            """,
            (cycle_id, action, json.dumps({"reason": reason, "cycle_id": cycle_id})),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"_write_feedback_ledger failed (verify schema): {e}")
    finally:
        store._put_conn(conn)
```

---

## Fix/Feature 4: APScheduler matter-config drift weekly job

### Problem
RA-23 Q6 ratifies a weekly drift audit on matter cortex-config files (>30d unchanged → flag).

### Current State
- `triggers/embedded_scheduler.py:78` — `_register_jobs(scheduler)` registers cron + interval jobs.
- Pattern to mirror: `_ai_head_weekly_audit_job` (Mon 09:00 UTC, env-flag `AI_HEAD_AUDIT_ENABLED`).

### Implementation

Add to `triggers/embedded_scheduler.py`:

```python
def _matter_config_drift_weekly_job():
    """RA-23 Q6: weekly audit of wiki/matters/*/cortex-config.md.
    Flags configs with mtime >30d. Logs + Slack DM if any flagged.
    Mirrors _ai_head_weekly_audit_job pattern."""
    if os.getenv("CORTEX_DRIFT_AUDIT_ENABLED", "true").lower() != "true":
        return
    try:
        from orchestrator.cortex_drift_audit import run_drift_audit
        result = run_drift_audit()
        logger.info(f"matter_config_drift_weekly: {result.get('flagged_count', 0)} flagged")
    except Exception as e:
        logger.error(f"matter_config_drift_weekly_job failed: {e}")


# Inside _register_jobs (mirror existing pattern):
scheduler.add_job(
    _matter_config_drift_weekly_job,
    trigger=CronTrigger(day_of_week="mon", hour=11, minute=0),
    id="matter_config_drift_weekly",
    replace_existing=True,
)
```

Plus tiny new module `orchestrator/cortex_drift_audit.py` (~80 LOC) that walks `wiki/matters/*/cortex-config.md`, checks file mtime, returns flagged list.

---

## Fix/Feature 5: Step 29 DRY_RUN flag

Already woven into Phase 4 + Phase 5 (`CORTEX_DRY_RUN=true` env var). Acceptance:
- Cycle row gets `dry_run_marker` artifact in `cortex_phase_outputs`
- Phase 4 logs "would post" instead of Slack-posting
- Phase 5 cortex_approve logs "would execute" instead of executing structured_actions / writing GOLD / propagating curated
- Cycle row still completes normally (status='approved' if path taken in DRY_RUN; structured_actions skipped)
- Live first-cycle on AO matter uses `CORTEX_DRY_RUN=true` for at least 1 cycle before flag flip

---

## Fix/Feature 6: Step 33 rollback script

Create `scripts/cortex_rollback_v1.sh` (committed BEFORE Step 34-35 Director-consult cutover).

```bash
#!/usr/bin/env bash
# cortex_rollback_v1.sh — Director-only manual fire. <5 min RTO.
#
# Restores ao_signal_detector direct trigger + ao_project_state writes after
# Cortex Stage 2 V1 decommission of those paths (Steps 34-35).
#
# Usage:
#   bash scripts/cortex_rollback_v1.sh confirm
#
# What it does:
#   1. Re-enables ao_signal_detector by setting AO_SIGNAL_DETECTOR_ENABLED=true
#      via Render API.
#   2. Renames ao_project_state_legacy_frozen_<date> back to ao_project_state.
#   3. Sets CORTEX_LIVE_PIPELINE=false to halt new Cortex cycles on AO matter.
#   4. Posts Slack DM to Director confirming rollback.
#
# Prerequisites:
#   - 1Password CLI logged in (`op signin`) for Render API key access
#   - Director-only: requires `--confirm` flag

set -euo pipefail

if [[ "${1:-}" != "confirm" ]]; then
  echo "Usage: bash scripts/cortex_rollback_v1.sh confirm"
  echo "This is a DESTRUCTIVE rollback. <5 min RTO target."
  exit 1
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] cortex_rollback_v1: START"

# 1. Re-enable ao_signal_detector
RENDER_API_KEY=$(op read "op://Private/Render API Key/credential")
SERVICE_ID="srv-d6dgsbctgctc73f55730"

curl -fsS -X PATCH "https://api.render.com/v1/services/${SERVICE_ID}/env-vars" \
  -H "Authorization: Bearer ${RENDER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '[{"key":"AO_SIGNAL_DETECTOR_ENABLED","value":"true"},{"key":"CORTEX_LIVE_PIPELINE","value":"false"}]'

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] env vars updated"

# 2. Rename ao_project_state_legacy_frozen_<date> back (B-code: parametrize date or use latest match)
DB_URL=$(op read "op://Private/Baker DB URL/credential")
psql "${DB_URL}" -c "ALTER TABLE ao_project_state_legacy_frozen_20260428 RENAME TO ao_project_state;" || \
  echo "[WARN] table rename failed — may already be ao_project_state"

# 3. Trigger Render redeploy
curl -fsS -X POST "https://api.render.com/v1/services/${SERVICE_ID}/deploys" \
  -H "Authorization: Bearer ${RENDER_API_KEY}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redeploy triggered — wait for healthy then verify ao_signal_detector"

# 4. Slack DM Director (best-effort)
curl -fsS -X POST "https://baker-master.onrender.com/api/slack/dm-director" \
  -H "X-Baker-Key: bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"message":"⚠️ Cortex V1 rollback executed — ao_signal_detector restored, Cortex pipeline halted. Verify within 5 min."}' || \
  echo "[WARN] Slack DM failed — manually notify"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] cortex_rollback_v1: DONE — verify manually within 5 min"
```

EXPLORE: B-code MUST verify exact `op://` paths with Director or `op item list` before committing the script (secrets paths are environment-specific). Hardcoding may need adjustment.

---

## Files Modified

**Create (5):**
- `orchestrator/cortex_phase4_proposal.py`
- `orchestrator/cortex_phase5_act.py`
- `orchestrator/cortex_drift_audit.py`
- `scripts/cortex_rollback_v1.sh` (chmod +x)
- 4 test files (`tests/test_cortex_phase4_proposal.py`, `_phase5_act.py`, `_drift_audit.py`, `_rollback_smoke.py`)

**Modify (3):**
- `outputs/dashboard.py` — add `POST /cortex/cycle/{id}/action` endpoint
- `triggers/embedded_scheduler.py` — register `_matter_config_drift_weekly_job` (Mon 11:00 UTC)
- `orchestrator/cortex_runner.py` — replace 1B's Phase 3 termination point: after Phase 3c, call Phase 4 propose (`run_phase4_propose`); cycle status sequence in_flight → reason → tier_b_pending (post-card-post) → approved/rejected/modified (post-button-press) → archive

## Files NOT to touch
- `orchestrator/chain_runner.py`
- `orchestrator/capability_runner.py`
- 1A migrations / Phase 1/2/6
- 1B Phase 3a/3b/3c modules — Phase 5 imports them for Refresh; no edits
- `kbl/gold_writer.py:_check_caller_authorized()` — accepted as defense-in-depth per Director Item 5 ratification 2026-04-28
- `_ops/director-gold-global.md` legacy path — separate follow-up brief to retire

---

## Code Brief Standards (mandatory)

- **API version:** Slack Block Kit (verified via `mcp__d6fe7d26-...__slack_send_message` accepting `blocks`); Anthropic Claude Opus + Gemini Pro production-active 2026-04-28
- **Deprecation check date:** Slack Block Kit, FastAPI, APScheduler all 2026-04-28 active
- **Fallback:** `CORTEX_DRY_RUN=true` (default `false` after first observation week) → Phase 4 doesn't post Slack, Phase 5 doesn't execute. `CORTEX_DRIFT_AUDIT_ENABLED=true` (default true) controls drift job.
- **DDL drift check:** N/A (no new Postgres tables; only writes existing 1A tables)
- **Literal pytest output mandatory:** Ship report MUST include literal `pytest tests/test_cortex_phase4_*.py tests/test_cortex_phase5_*.py tests/test_cortex_drift_audit.py -v` stdout. ≥35 tests. NO "by inspection."
- **Function-signature verification (Lesson #44):** B-code MUST grep before coding:
  - `_safe_post_dm` in `triggers/ai_head_audit.py` (canonical Slack DM helper)
  - `gold_writer.append` signature (subagent map line 79; verify `GoldEntry` fields)
  - `feedback_ledger` columns via `information_schema.columns`
  - `_register_jobs` in `triggers/embedded_scheduler.py:78` (mirror cron pattern)
  - `op://` paths (Director or `op item list` confirmation before committing rollback script)

## Verification criteria

1. `pytest tests/test_cortex_phase4_*.py tests/test_cortex_phase5_*.py tests/test_cortex_drift_audit.py -v` ≥35 tests pass, 0 regressions in 1A + 1B test suites.
2. End-to-end on stub matter (CORTEX_DRY_RUN=true): trigger cycle → 1A+1B+1C all phases run → Phase 4 logs "would post Slack" → cycle row status='approved' (after stub-button-press) → curated propagation logged.
3. `POST /cortex/cycle/{cycle_id}/action` accepts all 4 actions; rejects invalid action with 400.
4. Block Kit payload validates: `python -c "import json; json.dumps(blocks)"` exits 0; structure matches Slack schema (B-code can use Slack's Block Kit Builder for sanity check).
5. Refresh button re-runs Phase 2+3, produces NEW proposal_id, replaces card in place (NEW row in cortex_phase_outputs with phase_order > previous).
6. Approve final-freshness check: insert sent_email matching matter slug in last 30 min → `_is_fresh()` returns False → cortex_approve returns `{"warning": "freshness_check_failed"}`.
7. Reject path writes `feedback_ledger` row with `feedback_type='rejected'` + reason in payload.
8. APScheduler `matter_config_drift_weekly` registered (verify via `/api/health` scheduler section: 50+ jobs after deploy).
9. `bash scripts/cortex_rollback_v1.sh` (without `confirm` arg) prints usage + exits 1; `bash scripts/cortex_rollback_v1.sh confirm` exits 0 in dry-run env (B-code uses test sandbox or stub env vars).
10. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True); ..."` exits 0 for all touched files.

## Quality Checkpoints

1. Slack Block Kit payload ≤ 50 blocks, each section ≤ 3000 chars (Slack limits)
2. Per-file Gold checkbox group ≤ 10 options (Slack max for `checkboxes` element)
3. Final-freshness check fails-OPEN on DB error (logs error + returns True; better to act than block)
4. DRY_RUN flag respected in BOTH Phase 4 (no Slack post) AND Phase 5 (no execute/write)
5. Rollback script has `set -euo pipefail` + explicit `confirm` arg requirement
6. Rollback script has 4 explicit timestamps (start, env-update, redeploy, end)
7. `gold_writer.append` calls wrap in try/except (caller-stack-guard may reject in some test contexts)
8. Refresh button does NOT replicate cycle_id — same cycle, new proposal_id (track via cortex_phase_outputs rows)
9. Slack interactivity HMAC verified before dispatching to handlers (or rely on `verify_api_key` if internal-only)
10. Mac Mini SSH propagation has 30s subprocess timeout
11. Drift audit job env-flag default `true` (visible by default; flip false to silence)
12. No new entries in `requirements.txt`

## Verification SQL

```sql
-- After E2E DRY_RUN test, expected:
SELECT current_phase, status, director_action, cost_dollars
FROM cortex_cycles
WHERE matter_slug='oskolkov' AND created_at >= NOW() - INTERVAL '5 minutes'
ORDER BY started_at DESC LIMIT 5;
-- Expected: status='approved'/'rejected'/'modified', current_phase='archive', cost_dollars > 0

-- Phase 4 + Phase 5 outputs present:
SELECT phase, phase_order, artifact_type FROM cortex_phase_outputs
WHERE cycle_id=(SELECT cycle_id FROM cortex_cycles WHERE matter_slug='oskolkov' ORDER BY started_at DESC LIMIT 1)
ORDER BY phase_order;
-- Expected: includes (propose, 7, proposal_card), (archive, 10, final_archive)

-- Drift audit job registered:
SELECT job_id, next_run_time FROM apscheduler_jobs
WHERE job_id='matter_config_drift_weekly' LIMIT 1;
-- Expected: next_run_time = next Monday 11:00 UTC
```

## Out of scope

- Step 30 first live cycle on AO matter — Director-consult, not in this brief
- Step 34 ao_signal_detector decommission — Director-consult, separate change
- Step 35 ao_project_state rename — Director-consult, separate change
- Step 36 1-week observation period — operational, not code
- Step 37 MOVIE matter onboarding — post-observation, Director-consult
- Step 38 close BRIEF_CORTEX_3T_FORMALIZE_1 — operational
- Update of `kbl/gold_writer.py` write-path constant (legacy `_ops/director-gold-global.md` → `wiki/_cortex/director-gold-global.md`) — separate follow-up brief
- LLM model bump to 4.7 — separate brief

## Branch + PR

- Branch: `cortex-3t-formalize-1c`
- PR title: `CORTEX_3T_FORMALIZE_1C: Phase 4/5 + scheduler + dry-run + rollback`
- Reviewer: B1 second-pair (MEDIUM trigger class — new endpoint + Slack interactive + scheduler + decommission rollback) → AI Head B Tier-A merge on APPROVE + `/security-review` skill PASS

## Co-Authored-By

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
