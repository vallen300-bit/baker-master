> **⚠️ SUPERSEDED 2026-04-28** — This monolithic brief (524 lines, ~36h) was authored by AI Head A in parallel with Task 2 routing ambiguity. Director ratified split into 3 sub-briefs 2026-04-28 ("recom accepted" — Item 1 = AI Head B). Active dispatchable briefs:
>
> - `briefs/BRIEF_CORTEX_3T_FORMALIZE_1A.md` — cycle persistence + Phase 1/2/6 (~12h)
> - `briefs/BRIEF_CORTEX_3T_FORMALIZE_1B.md` — Phase 3a/3b/3c reasoning (~12h)
> - `briefs/BRIEF_CORTEX_3T_FORMALIZE_1C.md` — Phase 4/5 + scheduler + dry-run + rollback (~14h)
>
> Total: ~38h split across 3 dispatchable PRs; supersession reason: anti-pattern lesson on monolithic briefs (SPECIALIST-UPGRADE-1: 5 features bundled → 19 bugs). Content below retained for audit trail; do NOT dispatch.
>
> Authority: Director RA-23 + 2026-04-28 paste-block GO + "recom accepted" on split. Authored by AI Head B (M2 lane) per Director "Item 1 — you" 2026-04-28.

---

# BRIEF: CORTEX_3T_FORMALIZE_1 — Cortex Stage 1 cycle formalization + 4-button card + AO first scope (SUPERSEDED — see banner above)

**Milestone:** Cortex Stage 1 (RA-22 ratified 2026-04-27)
**Roadmap source:** `_ops/processes/cortex3t-roadmap-simplified.md` (canonical, vault `e426b2b`)
**Spec source:** `_ops/ideas/2026-04-27-cortex-3t-formalize-spec.md` (status `promoted`)
**Companion architecture:** `_ops/processes/cortex-architecture-final.md` (RA-23, AI Head B M2 lane)
**Estimated time:** ~36h / ~5 days
**Complexity:** High
**Prerequisites:**
- M0 closed (KBL_SCHEMA_1, CHANDA top-3 detectors, KBL_INGEST_ENDPOINT_1, PROMPT_CACHE_AUDIT_1, CITATIONS_API_SCAN_1)
- PR #66 GOLD_COMMENT_WORKFLOW_1 (`95d99f3`) merged
- PR #67 WIKI_LINT_1 (`93f7d8e`) MERGED 2026-04-28 — dispatch gate lifted
- Existing infra: `capability_threads` + `capability_turns` + `feedback_ledger` + `signal_queue` + `cortex_config` + `cortex_events` (event bus, distinct from this brief's tables)

---

## Context

Cortex-3T reasoning has no formalized 6-phase cycle structure today. `orchestrator/chain_runner.py` (751 lines) implements a 6-step pipeline (`should_chain` → `_build_planning_context` → `_generate_plan` → `_execute_plan` → `_verify_chain` → `_log_chain` → `_notify_director`) called from [pipeline.py:652](orchestrator/pipeline.py:652) — nearly 1:1 with Cortex's 6 phases (sense → load → reason → propose → act → archive). The reframe per spec L4: *"Cortex-3T = chain_runner + persistence-per-phase + named formalization."* This brief delivers that, plus a 4-button Director-facing proposal card (✅ ✏️ 🔄 ❌) with final-freshness check + Refresh re-run, GOLD workflow integration via `gold_proposer`, and AO matter wired as Stage 1 first scope.

Director ratification: *"Lock in the simplified approach new design as we now discussed it (we discussed only memory issues and found a solution through proper research and planning)."* — RA-22 2026-04-27.

---

## Problem

1. No cycle identity. chain_runner runs phases but no `cycle_id` ties them; no audit trail of *what each phase produced* survives the run.
2. No Director-facing proposal surface. `_notify_director` posts plain Slack threads; no interactive buttons, no Refresh, no final-freshness gate.
3. No "recent activity" loader in Phase 2. Cortex proposes actions Director already initiated → duplicate sends, embarrassing.
4. GOLD workflow integration unwired. Propose-phase output doesn't reach `gold_proposer.propose()` (the only caller-authorized path for Cortex; `gold_writer.append` rejects `cortex_*` modules).
5. Tier B routing per cycle implicit, not enforced. `capability_sets.autonomy_level='recommend_wait'` exists but cortex flow doesn't gate on it.

## Solution

Build `orchestrator/cortex_runner.py` wrapping `chain_runner.maybe_run_chain()` with named phases + per-phase persistence. Add `cortex_cycles` + `cortex_phase_outputs` tables (separate from existing `cortex_events` event-bus table). Wire propose-phase output to `kbl.gold_proposer.propose()`. Add new `/slack/interactive` endpoint reusing `triggers/slack_events._verify_signature` for HMAC. AO matter (`oskolkov` slug per spec; canonical verification at Step 0) as first scope. Tier B via existing `capability_sets.autonomy_level='recommend_wait'`. Stage 1 deferrals per RA-22 (no polling, no other matters, no eval suite, no Graphiti, no Anthropic Memory tool).

---

## Architecture

| Component | Path | Responsibility |
|---|---|---|
| **`orchestrator/cortex_runner.py`** | new | `run_cycle(trigger_type, signal_id, matter_slug, ...)` — wraps `chain_runner.maybe_run_chain()` with named-phase persistence. Inserts `cortex_cycles` row, writes `cortex_phase_outputs` per phase, calls `gold_proposer.propose()` at Phase 4 propose, gates Phase 5 act on Director button click via `cortex_cycles.status`. |
| **`orchestrator/cortex_phase2_loaders.py`** | new | `load_recent_activity(matter_slug, days=14)` — Director outbound emails + named-entity inbound + WhatsApp + baker_actions on the matter. Fed into Phase 3 reasoning prompt. |
| **`triggers/slack_interactive.py`** | new | `POST /slack/interactive` route. Receives Slack `block_actions` payload. Reuses `triggers.slack_events._verify_signature`. Parses `payload` form field, routes button click to `/api/cortex/cycle/{id}/action`. |
| **`/api/cortex/cycle/{cycle_id}/action`** | `outputs/dashboard.py` (new route) | POST handler. Body `{action: 'approve'|'edit'|'refresh'|'reject', edits?: str, reason?: str, response_url: str}`. Performs freshness check on approve, re-runs Phase 2+3 on refresh, archives on reject. Updates Slack card via `response_url` (replace_original=true) using existing Block Kit blocks. |
| **`migrations/20260428_cortex_cycles.sql`** | new | `cortex_cycles` (cycle lifecycle) + `cortex_phase_outputs` (per-phase artifacts). Date-prefixed per `migrations/` convention (latest example `20260427_kbl_drift_audits.sql` not present — M1.3 parked; latest committed is `20260426_gold_audits.sql`). |
| **`tests/test_cortex_runner.py`** | new | Full-cycle smoke + 4 buttons + freshness check + refresh + Tier B gating. Pattern: `tests/test_audit_sentinel.py`. |

### Phase mapping (chain_runner → cortex_runner)

| chain_runner | Cortex phase | New persistence |
|---|---|---|
| (upstream `pipeline.py:652`) | Phase 1 (sense) — already exists | none — wired to cycle creation |
| `_build_planning_context` | Phase 2 (load) | cortex_phase_outputs row, payload includes recent_activity |
| `_generate_plan` | Phase 3 (reason) | cortex_phase_outputs row, payload includes plan + reasoning trace |
| `_execute_plan` | Phase 4 (propose) | cortex_phase_outputs row + `gold_proposer.propose(ProposedGoldEntry)` |
| `_verify_chain` | embedded in Phase 4 | included in propose row |
| `_execute_plan` (act side) | Phase 5 (act) — gated on Director ✅ | cortex_phase_outputs row, only after `cortex_cycles.status='approved'` |
| `_log_chain` | Phase 6 (archive) | cortex_phase_outputs row, status → final |
| `_notify_director` | Phase 5 surface | proposal card → Slack Block Kit |

---

## SQL Schema (migration `20260428_cortex_cycles.sql`)

```sql
-- == migrate:up ==
-- BRIEF_CORTEX_3T_FORMALIZE_1 Phase 0 schema.
-- Idempotent + additive. Applied by config/migration_runner.py on next Render boot.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- cortex_cycles: one row per Cortex reasoning cycle on a matter.
CREATE TABLE IF NOT EXISTS cortex_cycles (
    cycle_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    matter_slug        TEXT NOT NULL,
    triggered_by       TEXT NOT NULL
        CHECK (triggered_by IN ('signal','director','cron','gold_comment','refresh')),
    trigger_signal_id  BIGINT,
    thread_id          UUID REFERENCES capability_threads(thread_id) ON DELETE SET NULL,
    started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at       TIMESTAMPTZ,
    last_loaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_phase      TEXT NOT NULL DEFAULT 'sense'
        CHECK (current_phase IN ('sense','load','reason','propose','act','archive')),
    status             TEXT NOT NULL DEFAULT 'in_flight'
        CHECK (status IN ('in_flight','proposed','tier_b_pending','approved','rejected','modified','failed','superseded','abandoned')),
    proposal_id        UUID,
    director_action    TEXT
        CHECK (director_action IS NULL OR director_action IN ('gold_approved','gold_modified','gold_rejected','refresh_requested')),
    feedback_ledger_id BIGINT,
    slack_channel_id   TEXT,
    slack_message_ts   TEXT,
    cost_tokens        INTEGER DEFAULT 0,
    cost_dollars       NUMERIC(10,4) DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cortex_cycles_matter_status
    ON cortex_cycles (matter_slug, status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_cortex_cycles_thread
    ON cortex_cycles (thread_id) WHERE thread_id IS NOT NULL;

-- cortex_phase_outputs: per-phase artifacts within a cycle.
-- DISTINCT from cortex_events (event-bus firehose). Phase outputs are
-- structured cycle artifacts; events are arbitrary signal observations.
CREATE TABLE IF NOT EXISTS cortex_phase_outputs (
    output_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cycle_id       UUID NOT NULL REFERENCES cortex_cycles(cycle_id) ON DELETE CASCADE,
    phase          TEXT NOT NULL
        CHECK (phase IN ('sense','load','reason','propose','act','archive')),
    phase_order    INT NOT NULL,
    artifact_type  TEXT NOT NULL,
    payload        JSONB NOT NULL,
    citations      JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cortex_phase_outputs_cycle_phase
    ON cortex_phase_outputs (cycle_id, phase_order);

COMMIT;
```

**DDL-drift verification (mandatory at Step 0):**
```bash
grep -nE "_ensure_cortex_cycles|_ensure_cortex_phase|cortex_phase_outputs|cortex_cycles" memory/store_back.py
# Must return ZERO (verified at brief draft 2026-04-28). If non-zero, reconcile per
# feedback_migration_bootstrap_drift.md BEFORE applying migration.
```

`cortex_config` table: **already exists** via bootstrap [`memory/store_back.py:2849`](15_Baker_Master/01_build/memory/store_back.py:2849) `_ensure_cortex_config_table()`. Brief does NOT add a migration for it. If new feature flags are needed (e.g. `cortex_runner_enabled`), extend the bootstrap's `INSERT INTO cortex_config (key, value) VALUES (...) ON CONFLICT DO NOTHING` block.

---

## Phase 2 recent-activity loaders

```python
# orchestrator/cortex_phase2_loaders.py
from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger("baker.cortex.phase2")

DIRECTOR_EMAILS = ("dvallen@brisengroup.com", "vallen300@gmail.com", "office.vienna@brisengroup.com")


def load_recent_activity(matter_slug: str, days: int = 14, store=None) -> dict:
    """Pulls Director outbound + named-entity inbound + baker_actions on this matter.

    Returns dict with 4 keys (each a list, never None). Bounded queries (LIMIT 200 each).
    Fault-tolerant: any single source failing returns [] for that key + warns.
    """
    from memory.store_back import SentinelStoreBack
    if store is None:
        store = SentinelStoreBack._get_global_instance()

    return {
        "director_outbound": _query_director_outbound(store, matter_slug, days),
        "entity_inbound":    _query_entity_inbound(store, matter_slug, days),
        "whatsapp_activity": _query_whatsapp_activity(store, matter_slug, days),
        "baker_actions":     _query_baker_actions(store, matter_slug, days),
    }


def _query_director_outbound(store, matter_slug: str, days: int) -> list:
    """SELECT from email_messages WHERE sender_email IN DIRECTOR_EMAILS AND <matter keyword match> AND created_at >= NOW() - days. LIMIT 200."""
    # Builder: read kbl/people_registry.matter_keywords if shipped, else hardcode keywords for AO ('oskolkov','andrey','aelio')
    ...
```

(Builder fills in queries per `email_messages` / `whatsapp_messages` / `baker_actions` schemas already in store_back.py — verify column names with `SELECT column_name FROM information_schema.columns` before each query.)

**Phase 3 reasoning prompt addition (verbatim from spec):**

> *Before proposing actions, check the loaded "recent activity" section. If Director already initiated the action being proposed, OR if the named recipient already responded, the proposal MUST adapt: verify what was received, propose a NEXT step, not a duplicate.*

---

## 4-button proposal card (Slack Block Kit)

Card posted via existing `triggers/slack_trigger._post_block_kit_message()` pattern. Structure:

```python
blocks = [
    {"type": "header", "text": {"type": "plain_text", "text": f"⚙️ Cortex proposal — {matter_slug}"}},
    {"type": "section", "text": {"type": "mrkdwn", "text": proposal_summary}},
    {"type": "context", "elements": [
        {"type": "mrkdwn", "text": f"cycle `{cycle_id[:8]}` · loaded {last_loaded_relative} · cost ${cost_dollars:.3f}"},
    ]},
    {"type": "actions", "block_id": f"cortex_cycle_{cycle_id}", "elements": [
        {"type": "button", "action_id": "cortex_approve", "text": {"type": "plain_text", "text": "✅ Approve"}, "style": "primary", "value": str(cycle_id)},
        {"type": "button", "action_id": "cortex_edit",    "text": {"type": "plain_text", "text": "✏️ Edit"},                       "value": str(cycle_id)},
        {"type": "button", "action_id": "cortex_refresh", "text": {"type": "plain_text", "text": "🔄 Refresh"},                    "value": str(cycle_id)},
        {"type": "button", "action_id": "cortex_reject",  "text": {"type": "plain_text", "text": "❌ Reject"}, "style": "danger",  "value": str(cycle_id)},
    ]},
]
```

Persist `slack_channel_id` + `slack_message_ts` on `cortex_cycles` after post (used by direct `chat.update` if `response_url` expires; normal path uses `response_url`).

| Button | `/api/cortex/cycle/{id}/action` body | Behavior |
|---|---|---|
| ✅ Approve | `{action:"approve", response_url}` | Final freshness check (1 sec scan: any new email/WA/signal in last 30 min on matter? if yes → return freshness warning; else execute Phase 5; update card via response_url with `replace_original=true`) |
| ✏️ Edit | `{action:"edit", edits, response_url}` | Save edits to `cortex_phase_outputs.payload` (append edit row); status stays `tier_b_pending`; update card showing edited text + same buttons |
| 🔄 Refresh | `{action:"refresh", response_url}` | Re-run Phase 2 (load) + Phase 3 (reason) with fresh data; update `last_loaded_at`; replace card in place with new draft |
| ❌ Reject | `{action:"reject", reason, response_url}` | Status → `rejected`; write `feedback_ledger` row (`action_type='ignore'`, payload includes cycle_id + reason); update card to gray "Rejected" state |

---

## `/slack/interactive` endpoint

```python
# triggers/slack_interactive.py
import json, logging
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from triggers.slack_events import _verify_signature  # REUSE — do not duplicate

logger = logging.getLogger("baker.slack.interactive")
router = APIRouter()


@router.post("/slack/interactive")
async def slack_interactive(request: Request, background_tasks: BackgroundTasks):
    """Slack Block Kit interactivity webhook.

    Receives form-encoded `payload=<json>` per Slack docs.
    Verifies HMAC via reused _verify_signature. Routes block_actions to
    /api/cortex/cycle/{id}/action handler. Returns 200 within 3 sec
    (Slack requirement); actual processing in background.
    """
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if not _verify_signature(body, timestamp, signature):
        raise HTTPException(status_code=401, detail="Slack signature verification failed")

    form = await request.form()
    payload_raw = form.get("payload", "")
    if not payload_raw:
        return {"ok": False, "error": "no_payload"}
    payload = json.loads(payload_raw)

    if payload.get("type") != "block_actions":
        logger.debug(f"Ignoring non-block_actions payload: {payload.get('type')}")
        return {"ok": True}

    action = (payload.get("actions") or [{}])[0]
    action_id = action.get("action_id", "")
    cycle_id = action.get("value", "")
    response_url = payload.get("response_url", "")

    if not action_id.startswith("cortex_") or not cycle_id:
        return {"ok": False, "error": "unhandled_action"}

    cortex_action = action_id.removeprefix("cortex_")  # approve|edit|refresh|reject

    # Background dispatch — keeps the 3-sec ack
    background_tasks.add_task(
        _dispatch_cortex_action,
        cycle_id=cycle_id,
        action=cortex_action,
        response_url=response_url,
        payload=payload,
    )
    return {"ok": True}


def _dispatch_cortex_action(cycle_id: str, action: str, response_url: str, payload: dict):
    """Forward to /api/cortex/cycle/{id}/action via internal call (or direct func call)."""
    from outputs.dashboard import cortex_cycle_action_handler  # internal handler
    cortex_cycle_action_handler(cycle_id=cycle_id, action=action, response_url=response_url, payload=payload)
```

Register in `outputs/dashboard.py` startup section: `app.include_router(slack_interactive.router)`.

---

## `/api/cortex/cycle/{cycle_id}/action` endpoint

Lives in `outputs/dashboard.py` near existing `/api/cortex/*` routes (4 already exist at lines 3918, 3970, 4005, 4017; new route slots cleanly).

Skeleton (full body in `cortex_runner.py` for testability; dashboard.py only thin wrapper):

```python
@app.post("/api/cortex/cycle/{cycle_id}/action", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def cortex_cycle_action(cycle_id: str, body: dict):
    from orchestrator import cortex_runner
    return cortex_runner.handle_director_action(
        cycle_id=cycle_id,
        action=body["action"],
        edits=body.get("edits"),
        reason=body.get("reason"),
        response_url=body.get("response_url"),
    )
```

`cortex_runner.handle_director_action()` does:
1. Load cycle. Reject if `status NOT IN ('proposed','tier_b_pending','modified')`.
2. Branch on action:
   - `approve` → freshness check (`_check_freshness(matter_slug, since=30 minutes)`); if dirty → return warning + leave status `tier_b_pending`. Else → execute Phase 5 act, status → `approved`, write `feedback_ledger` row `action_type='promote'`, update card.
   - `edit` → append `cortex_phase_outputs` row (artifact_type='edit'), status `tier_b_pending`, render new card with edited text.
   - `refresh` → re-run `_phase2_load()` + `_phase3_reason()`, update `last_loaded_at`, replace card.
   - `reject` → status `rejected`, write `feedback_ledger` row `action_type='ignore'` + payload.reason, render rejected card.
3. Update Slack via `response_url` POST with `{replace_original: true, blocks: [...]}`.

---

## GOLD workflow integration

**MUST USE:** `kbl.gold_proposer.propose(ProposedGoldEntry, matter=..., vault_root=...)`. **MUST NOT USE:** `kbl.gold_writer.append()` — `_check_caller_authorized()` ([kbl/gold_writer.py:49](15_Baker_Master/01_build/kbl/gold_writer.py:49)) walks the stack and rejects any frame whose module starts with `cortex_*` or `kbl.cortex`, raising `CallerNotAuthorized`.

```python
# In cortex_runner._phase4_propose():
from kbl.gold_proposer import ProposedGoldEntry, propose

entry = ProposedGoldEntry(
    iso_date=date.today().isoformat(),
    topic=plan.topic,                    # from chain_runner._generate_plan output
    proposed_resolution=plan.summary,
    proposer="cortex-3t",
    cortex_cycle_id=str(cycle_id),       # ← already in dataclass; no extension needed
    confidence=plan.confidence,
)
target_path = propose(entry, matter=matter_slug)
```

`gold_proposer` writes to the `## Proposed Gold (agent-drafted)` section at BOTTOM of the Gold file (matter or global). Director ratifies by manually moving entries up. **No auto-promote in V1** — that boundary is enforced by `gold_writer._check_caller_authorized` and is part of Hybrid C V1 design.

Director Gold approve/modify/reject lands in `feedback_ledger` via the existing pathway (`gold_promote_queue` drain → vault commit → `feedback_ledger` row). **Cortex action endpoint also writes feedback_ledger row** independently to capture the cycle-level decision. action_type values: `gold_approved` / `gold_modified` / `gold_rejected` / `refresh_requested` (existing column has no CHECK constraint — extension is safe; the migration's `cortex_cycles.director_action` CHECK enforces the same set at cycle-level for redundancy).

---

## Tier B routing per cycle

Existing `capability_sets.autonomy_level` field. AO matter (`ao_pm` row, slug `ao_pm`) and `movie_am` row both already at `recommend_wait` (verified via Baker MCP). Cortex action endpoint reads:

```python
autonomy = store.get_capability_autonomy_level(matter_slug)  # builder writes this helper
if autonomy == "recommend_wait" and action == "approve":
    # Tier B gate — execute Phase 5, but the gate IS the Director's button click.
    # No additional check needed; the click IS the authorization.
    pass
elif autonomy == "auto":
    # Future: skip card, auto-approve. Stage 1 = no auto for AO. Reject if hit.
    raise NotImplementedError("Stage 1: AO matter is recommend_wait only")
```

Stage 1 invariant: AO matter is always `recommend_wait`. Brief verifies pre-build that no `auto` autonomy_level rows exist for AO.

---

## Decomposer + synthesizer absorption (B's deferred Task 2 fold-in)

**Item 11 — Synthesizer → Phase 3c synthesis** (clear mapping):

`capability_runner.run_synthesizer(sub_results, original_question)` ([capability_runner.py:1096](15_Baker_Master/01_build/orchestrator/capability_runner.py:1096)) combines multi-source results. In cortex_runner, after `_phase3_reason()` produces a multi-source plan (e.g. legal context + financial context + counterparty model), Phase 3c invokes the synthesizer to produce the single proposal text. ~3h effort.

**Item 10 — Decomposer absorption** — *FLAG-WORTHY (see flag #1 below)*. Brief assumes Recommendation (a): Phase 1 sense gating absorbs decomposer's "should this even fire?" upstream gate. Existing decomposer's sub-task fan-out (`capability_runner.run_decomposed`) is NOT absorbed in Stage 1 — punted to Stage 2 if needed. ~2h effort. If Director ratifies Recommendation (b) instead, scope expands by ~4h (Phase 3 reason calls multi-capability sub-tasks, then Phase 3c synthesizes). See flag #1.

---

## Files to modify

- **Create:** `orchestrator/cortex_runner.py` (cycle wrapper, phase persistence, Director action handler, freshness check)
- **Create:** `orchestrator/cortex_phase2_loaders.py` (recent activity)
- **Create:** `triggers/slack_interactive.py` (POST `/slack/interactive`, reuses `_verify_signature`)
- **Create:** `migrations/20260428_cortex_cycles.sql` (two new tables)
- **Create:** `tests/test_cortex_runner.py` (pattern: `tests/test_audit_sentinel.py`)
- **Modify:** `orchestrator/pipeline.py` line 652 area — wrap `maybe_run_chain` call with `cortex_runner.run_cycle` (cortex_runner internally calls maybe_run_chain — surgical, not invasive)
- **Modify:** `outputs/dashboard.py` — register `slack_interactive.router`; add `/api/cortex/cycle/{id}/action` route slotting near existing `/api/cortex/*` (line 3918+)
- **Modify:** `memory/store_back.py` — add helpers: `insert_cortex_cycle`, `update_cortex_cycle_status`, `insert_cortex_phase_output`, `get_cortex_cycle`, `get_capability_autonomy_level`. (Bootstrap `_ensure_cortex_config_table` extended ONLY if new flag like `cortex_runner_enabled` needed — ratify with Director before adding.)
- **Modify:** `triggers/slack_trigger.py` — add `_post_cortex_proposal_card(cycle_id, blocks, channel)` helper using existing Block Kit outbound pattern (lines 700-739).

## Files NOT to touch

- **`kbl/gold_writer.py`** — `_check_caller_authorized` rejects `cortex_*` callers. Use `gold_proposer.propose` only.
- **`triggers/slack_events.py`** — existing `/slack` Events API endpoint; reuse `_verify_signature` (line 43) by import only. DO NOT extend this file with `/slack/interactive` (different endpoint, different payload shape, separate file is cleaner).
- **`cortex_events` table** — existing event bus (CORTEX-PHASE-2A). DISTINCT from `cortex_phase_outputs`. No reads/writes from cortex_runner.
- **`capability_threads` / `capability_turns`** — read-only reference (cortex_cycles.thread_id is FK; do not write to threads from cortex_runner V1).
- **`signal_queue`** — read-only (Phase 1 sense already populates it upstream).
- **`config/migration_runner.py`** — runs migrations on startup; no changes needed (just add the SQL file).

---

## Risks

- **Migration-bootstrap drift on cortex tables** — verified at draft time: `grep "_ensure_cortex_cycles\|cortex_phase_outputs" memory/store_back.py` returns ZERO. If non-zero at build time, reconcile per `feedback_migration_bootstrap_drift.md` BEFORE migration.
- **Caller-authorized rejection on gold_writer** — Cortex MUST use `gold_proposer`. Builder verifies at first integration test (mock cortex_runner module name, attempt gold_writer.append, expect `CallerNotAuthorized`).
- **`cortex_events` ≠ `cortex_phase_outputs` confusion** — cortex_events is the existing event bus; cortex_phase_outputs is the structured cycle artifact log. Brief explicitly distinguishes; reviewer checks no cortex_runner code writes to cortex_events.
- **Slack `response_url` 30-minute expiry** — if Director clicks after 30 min, response_url 404s. Fallback: use `slack_channel_id` + `slack_message_ts` persisted on cortex_cycles to call `chat.update` directly. Builder implements both paths; tests cover the expired case.
- **Slack 3-second ack** — `/slack/interactive` MUST return 200 within 3 sec. Use `BackgroundTasks` for actual cycle work (mirrors `triggers/slack_events.py:slack_events`).
- **Idempotency on action endpoint** — Director double-clicks Approve. Endpoint reads `cortex_cycles.status` first; if already `approved`, returns ok with no-op (do not re-execute Phase 5).
- **AO matter slug canonicality** — spec uses `oskolkov`. slugs.yml v12 has aliases `[oskolkov, andrey, "andrey oskolkov"]` resolving to canonical slug at `slugs.yml:38-43` area. Builder verifies canonical slug at Step 0 with `python -c "from kbl import slug_registry; print(slug_registry.get('oskolkov'))"` — uses canonical, not alias.
- **MOVIE slug discrepancy** — slugs.yml has `mo-vie-am`; AI Head B's M2-lane work used `wiki/matters/movie/...` path. NOT this brief's concern (Stage 1 = AO only) but flag for follow-up if MOVIE absorption surfaces in Stage 2.
- **Render restart mid-cycle** — `cortex_cycles.status='in_flight'` rows orphaned. Cron sentinel (Stage 2) sweeps in_flight > 10 min and marks `failed`. V1: log on startup if any in_flight rows older than 10 min, no auto-fix.
- **Render two-instance startup race** — migration is idempotent (`CREATE TABLE IF NOT EXISTS`); cortex_runner reads/writes are atomic via single PG conn from pool. No advisory lock needed for V1 (rate is bounded by Director button clicks).
- **Cost spike** — Phase 3 reason re-runs on every Refresh click. Cost guard: cap Refresh to 5 per cycle (`cortex_cycles.refresh_count` column). Add to migration if Director wants the cap; brief proposes adding as future amendment, not V1.
- **Decomposer absorption mapping (FLAG #1)** — see flag-worthy items below.

---

## Code Brief Standards (mandatory)

- **API version:**
  - Slack Web API (`chat.postMessage`, `chat.update`, `views.open` for edit modal) — confirmed 2026-current via existing `triggers/slack_trigger.py` usage. Re-verify in `/slack/interactive` PR description.
  - Slack Events API (already wired at `/slack`).
  - Slack Block Kit Interactivity (NEW endpoint `/slack/interactive`).
  - Anthropic SDK — no new calls; re-uses chain_runner's `claude_client = anthropic.Anthropic(api_key=...)`.
- **Deprecation check:** Slack endpoints stable; Block Kit interactive payload shape stable. Confirm at Step 0 by reading https://api.slack.com/reference/interaction-payloads/block-actions.
- **DDL drift check:** verified at draft time (zero hits). Re-verify at Step 0.
- **Fallback on hook failures:** N/A (no hooks). On `cortex_runner` exception during cycle: status → `failed`, write `cortex_phase_outputs` row with `artifact_type='error'`, log + Slack-DM AI Head. Never crash pipeline.py upstream.
- **Literal pytest output mandatory:** ship report MUST include literal `pytest tests/test_cortex_runner.py -v` stdout. No "passes by inspection" (per `feedback_no_ship_by_inspection.md`).

## Verification criteria

1. `pytest tests/test_cortex_runner.py -v` — minimum 12 tests pass (cycle creation, 6 phase persistences, 4 button transitions, freshness pass + freshness dirty, Tier B gate).
2. `python -c "import py_compile; py_compile.compile('orchestrator/cortex_runner.py', doraise=True); py_compile.compile('orchestrator/cortex_phase2_loaders.py', doraise=True); py_compile.compile('triggers/slack_interactive.py', doraise=True)"` exits 0.
3. **End-to-end smoke on AO signal #15725** (or equivalent fresh AO signal): cortex_cycle row created → 6 phase outputs persisted → proposal card lands in Director's Slack with 4 buttons → Approve fires freshness check → Phase 5 executes → feedback_ledger row written with `action_type='promote'`.
4. **4-button manual test:** all 4 buttons fire correct state transitions (verified via `SELECT cycle_id, status, director_action FROM cortex_cycles ORDER BY started_at DESC LIMIT 5`).
5. **Refresh idempotency:** clicking Refresh re-runs Phase 2+3 with new `last_loaded_at`; no duplicate `cortex_phase_outputs` rows for same `(cycle_id, phase, phase_order)`.
6. **Caller-authorized regression test:** unit test that import-renames cortex_runner to `cortex_test_x` and asserts `gold_writer.append()` raises `CallerNotAuthorized`. Confirms boundary holds.
7. **Slack signature verification:** integration test posts to `/slack/interactive` with bad signature → 401; with valid signature → 200 ok.
8. Migration applied: `SELECT COUNT(*) FROM schema_migrations WHERE name LIKE '%cortex_cycles%'` returns 1 (post-deploy poll up to 60s per Lesson #41).
9. PR description documents: (a) `gold_proposer` vs `gold_writer` boundary, (b) `cortex_events` vs `cortex_phase_outputs` distinction, (c) `_verify_signature` reuse from slack_events, (d) decomposer mapping decision (a or b per flag #1), (e) AO canonical slug verified.

## Verification SQL

```sql
-- Confirm cycle ran end-to-end
SELECT cycle_id, matter_slug, current_phase, status, director_action, cost_dollars
  FROM cortex_cycles
 WHERE matter_slug = 'oskolkov'
 ORDER BY started_at DESC
 LIMIT 5;

-- Confirm 6 phase outputs per completed cycle
SELECT cycle_id, COUNT(*) AS phase_count, ARRAY_AGG(phase ORDER BY phase_order) AS phases
  FROM cortex_phase_outputs
 GROUP BY cycle_id
 ORDER BY MAX(created_at) DESC
 LIMIT 5;

-- Confirm feedback_ledger captures Director action
SELECT id, action_type, target_matter, payload->>'cycle_id' AS cycle_id, director_note
  FROM feedback_ledger
 WHERE payload ? 'cycle_id'
 ORDER BY created_at DESC
 LIMIT 5;

-- Confirm Tier B routing
SELECT slug, autonomy_level, active FROM capability_sets WHERE slug='ao_pm' LIMIT 1;
```

---

## Out of scope (Stage 1 deferrals per RA-22 spec)

- Polling / scheduled re-evaluation (Director-driven refresh sufficient)
- Auto re-fire on new related signal
- Other matter scopes (MOVIE / `mo-vie-am` / Hagenauer / BD) — Stage 2
- Eval suite, model bumps (Opus 4.7), retention, trust audit — Stage 2
- Game-theory injection / Counterparty Game Advisor — Stage 2
- Graphiti adoption / Anthropic Memory tool — Brisen has equivalent built; no value-add
- Decomposer sub-task fan-out absorption (Item 10 option b) — Stage 2 if Director ratifies
- Refresh count cap (`refresh_count` column + 5-cap UI) — V2 if cost spike observed
- Cron sentinel for in_flight cycle sweep — V2
- KBL_SCHEMA_DRIFT_DETECTOR_1 (M1.3) — parked, promotion trigger first observed drift event
- `cortex_runner_enabled` env feature flag — proposed, ratify with Director before adding to bootstrap

---

## Branch + PR

- Branch: `cortex-3t-formalize-1`
- PR title: `CORTEX_3T_FORMALIZE_1: Stage 1 cycle formalization + 4-button card + AO scope (RA-22)`
- Trigger class: **HIGH** (external API surface + new endpoint + financial path through Gold + cross-capability state writes)
- Reviewer: **B1 situational review per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`** (auth/HMAC + new endpoint + DB migration + cross-capability state writes — 4 trigger classes hit). B1 review BEFORE merge mandatory.
- Builder ≠ B1 (b1-builder-can't-review-own-work). **Recommend B2** (idle as of 2026-04-28 post-PR #67 merge; capable). **NOT B3** — busy on M2 lane `BAKER_MCP_EXTENSION_1` per coordination note 2026-04-28. **NOT B1** — busy on `B_CODE_AUTOPOLL_1` (out-of-app dispatch, hands-off). **B4** as parallel option if B2 capacity uncertain.
- Cross-lane reviewer: AI Head B (Pattern C). Merge gate after B1 APPROVE + AI Head A `/security-review` skill invocation per Lesson #52.

---

## /write-brief 6-step compliance

1. **EXPLORE** — done. Verified: chain_runner public surface (8 functions), pipeline.py:652 wiring point, gold_writer caller-authorized boundary, gold_proposer ProposedGoldEntry shape (already has `cortex_cycle_id` field), slack_events.py `_verify_signature` reuse, capability_threads/capability_turns schema, feedback_ledger no-CHECK-constraint, cortex_config bootstrap pattern, autonomy_level column on capability_sets (ao_pm/movie_am at recommend_wait), 4 existing `/api/cortex/*` routes (no collision), slugs.yml AO alias resolution, MOVIE slug discrepancy (out of scope). Lesson #47 redundancy sweep clean (zero shipped feature under cortex_runner|cortex_cycles|cortex_phase_outputs|/slack/interactive).
2. **PLAN** — embedded in this brief (Architecture, Files-to-modify, Files-NOT-to-touch, Risks, Verification). Q1/Q2/Q3 from spec answered empirically. One open Q surfaced (decomposer mapping) with Recommendation.
3. **WRITE** — this file.
4. **REVIEW** — pass against lessons.md, cost impact, safety rules, Render restart, blast radius, edge cases. (Done at draft close — see flag list.)
5. **PRESENT** — handoff to Director with brief path + summary + ETA + risk level + flag list.
6. **CAPTURE LESSONS** — post-implementation: gold_proposer caller-authorized boundary, response_url 30-min expiry, cortex_events vs cortex_phase_outputs distinction. Append to `tasks/lessons.md`.

---

## Flag-worthy items at draft review

1. **Decomposer absorption mapping (Item 10).** B's actions_log says "decomposer absorption into Phase 1 sense gating," but existing decomposer at [capability_runner.py:1020-1095](15_Baker_Master/01_build/orchestrator/capability_runner.py:1020) is sub-task fan-out for question answering, not signal-relevance gating. Two interpretations:
   - **(a)** Phase 1 sense gating absorbs decomposer's "should this even fire?" gate → ~2h, lighter scope. **Brief assumes (a).**
   - **(b)** Phase 3 reason absorbs sub-task fan-out → ~6h, heavier scope, unlocks multi-capability cycles.
   - **Recommendation: (a)** for V1 — sub-task fan-out is too heavy for first cycle ship; if Cortex needs multi-capability reasoning later, promote to Stage 2. If Director ratifies (b), revised total `~40h / ~5.5 days`.
2. **`cortex_runner_enabled` env feature flag.** Proposed for kill-switch parity with `GOLD_AUDIT_ENABLED`. **Recommendation:** add to bootstrap (`_ensure_cortex_config_table` INSERT block). Director can flip to disable cortex_runner without redeploy if it misbehaves. Skipping = brief defaults to always-on.
3. **AO canonical slug.** Spec uses `oskolkov` (alias-confirmed). Canonical slug in slugs.yml line ~38-42 area NOT explicitly named in this brief — **builder verifies at Step 0** with `slug_registry.get('oskolkov')`. If canonical resolves to e.g. `andrey-oskolkov`, brief's `matter_slug='oskolkov'` queries STILL work via alias resolution, but cortex_cycles.matter_slug should store CANONICAL not alias.
4. **`refresh_count` cost cap.** Refresh re-runs Phase 2+3 (LLM calls). Director could spam Refresh and rack up cost. **Recommendation:** punt to V2 (Stage 1 ships without cap; observe production cost; cap if needed). If Director wants cap NOW, add `refresh_count INTEGER DEFAULT 0` column + 5-cap check in cortex_runner. Adds ~30 min.
5. **Slack scope.** `/slack/interactive` requires Slack app permission `commands` (already granted) OR `block_actions` interactivity URL configured in Slack app settings. **Builder verifies at Step 0** Director's Slack app has Interactivity URL pointable at `https://baker-master.onrender.com/slack/interactive`. If not, Director sets it (5-min Slack admin task) before ship.

---

## §6C orchestration note (B-code dispatch coordination)

- HIGH trigger class — B1 situational review BEFORE merge mandatory.
- Builder ≠ B1. **Recommend B2** (idle 2026-04-28). **NOT B3** (busy M2 `BAKER_MCP_EXTENSION_1`). **NOT B1** (busy `B_CODE_AUTOPOLL_1`, hands-off).
- §3 mailbox hygiene: standard `briefs/_tasks/CODE_2_PENDING.md` overwrite; mailbox marked COMPLETE post-merge.
- Wake-paste mandatory same turn as dispatch (Lesson #48). AI Head A in active Director chat lane surfaces paste-block to `b2`.
- Cross-lane orchestration: AI Head B M2 lane concurrent (BAKER_MCP_EXTENSION_1 on B3, game_theory prompt fill, MOVIE absorption wrap). File overlap check: B's M2 work in `wiki/matters/` + Baker MCP server; this brief in `orchestrator/cortex_runner.py` + `orchestrator/cortex_phase2_loaders.py` + `triggers/slack_interactive.py` + `migrations/20260428_cortex_cycles.sql` + `outputs/dashboard.py` (new route only) + `triggers/slack_trigger.py` (new helper only) + `memory/store_back.py` (new helpers only) — independent.
- **YAML frontmatter convention note (per B_CODE_AUTOPOLL_1, Director ratified 2026-04-27):** new dispatch convention introduces `status: OPEN` + `autopoll_eligible: false` frontmatter on `CODE_*_PENDING.md`. Existing dispatches stay free-form until retrofitted post-AUTOPOLL merge. **This brief's dispatch (when fired) follows existing free-form pattern**; retrofit batch lands separately.

## Co-Authored-By

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
