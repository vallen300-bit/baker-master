# BRIEF: CORTEX_MANUAL_INVOKE_1 — Streaming manual-invoke endpoint + Scan-intent route

## Context

Cortex V1 LIVE on AO matter. Today's only Director-callable surfaces are:
1. `POST /api/cortex/trigger` (BRIEF_CORTEX_TRIGGER_ENDPOINT_1, sync — waits up to 5 min, returns terminal cycle state)
2. WhatsApp/email auto-trigger gated through `cortex_pre_review_gate` (Slack DM approve/skip)

What's missing: a **streaming** manual-invoke surface that lets Director (a) trigger a cycle from anywhere with live phase visibility, and (b) say "run cortex on hagenauer-rg7" in Scan chat and have it route to the same endpoint.

Wave 1 Track 1 per V3 rev 4 roadmap (https://brisen-docs.onrender.com/architecture/cortex-roadmap-v3-any-matter.html). Pairs with Track 2 (multi-matter gate) and Tracks 3+4 (per-matter cortex-config seeds).

## Estimated time: ~4-5h (build 2.5h + tests 1h + B1 review 30min + post-deploy smoke 30min)
## Complexity: Medium-High (SSE polling design + intent classifier extension)
## Trigger class: HIGH

This PR ships:
- New external HTTP endpoint with SSE streaming
- New auth surface (X-Baker-Key on a write path)
- New Scan intent that fires real cycles (cost-bearing)
- New rate-limit + cost-guardrail logic

→ B1 situational review REQUIRED per RA-24 (external API + auth + cost-bearing trigger). **Builder ≠ B1** — this brief assigns B1 as builder per AI Head A dispatch; AI Head A + AI Head B perform `/security-review` + structural review. If AI Head A judges B1-builder ↔ B1-review concentration unacceptable, reassign builder to B2 and B1 reviews.

**Build assignment:** B1 (`~/bm-b1`). **Review assignment:** AI Head A (structural + `/security-review`) + AI Head B (cross-lane).

---

## Behavior change

### Before (current LIVE state)

```
Director wants on-demand cycle → POST /api/cortex/trigger → waits 5 min blind → returns terminal state
Director in Scan: "run cortex on hagenauer-rg7" → falls through to RAG (no Cortex routing)
```

### After

```
Director wants on-demand cycle:
  POST /api/cortex/run  →  SSE: phase_changed (sense→load→reason→propose→act→archive)
                            SSE: specialist_started / specialist_completed (per Phase 3 invocation)
                            SSE: terminal {status, cycle_id, cost_dollars}
  [client disconnect kills connection but NOT the cycle — runs to completion in background]

Director in Scan: "run cortex on hagenauer-rg7 — what's our position on Sähn dispute?"
  → classify_intent returns {type: "cortex_run_action", matter_slug: "hagenauer-rg7", question: "..."}
  → /api/scan branch routes to internal call of /api/cortex/run logic; SSE proxied through Scan stream
```

Rate limit: **5 runs/hour/matter** (HTTP 429 over).
Cost guardrail: **30 specialist invocations/day/matter** = warning posted to Director Slack DM (NOT a hard cap — observability only).

---

## Implementation

### File 1: NEW `outputs/cortex_run_stream.py` (~180 LOC)

Pure helpers — no FastAPI imports. Easier to unit-test than embedding inline in dashboard.py.

```python
"""CORTEX_MANUAL_INVOKE_1: SSE streaming + rate limit + cost guardrail
helpers for /api/cortex/run.

Streaming model: spawn maybe_run_cycle as a background asyncio.Task. Poll
cortex_cycles.current_phase + cortex_phase_outputs row count every
POLL_INTERVAL_SECONDS. Emit SSE events on transitions. Terminal when
cortex_cycles.status leaves 'in_flight'.
"""
from __future__ import annotations
import asyncio, json, logging, os, time
from typing import AsyncIterator, Optional
logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = float(os.environ.get("CORTEX_RUN_POLL_INTERVAL", "0.5"))
RUN_RATE_LIMIT_PER_HOUR = int(os.environ.get("CORTEX_RUN_RATE_LIMIT", "5"))
COST_WARN_SPECIALIST_PER_DAY = int(os.environ.get("CORTEX_COST_WARN_SPECIALIST_PER_DAY", "30"))


def runs_in_last_hour(matter_slug: str) -> int:
    """Count cycles in the last hour for matter_slug across manual triggers."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn: return 0
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM cortex_cycles "
            "WHERE matter_slug=%s "
            "AND triggered_by IN ('director_manual','scan_intent') "
            "AND started_at > NOW() - INTERVAL '1 hour'",
            (matter_slug,),
        )
        n = (cur.fetchone() or [0])[0]
        cur.close()
        return int(n)
    finally:
        store._put_conn(conn)


def specialist_calls_today(matter_slug: str) -> int:
    """Count Phase 3 specialist invocations in last 24h (capability_runs)."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn: return 0
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM capability_runs "
            "WHERE matter_slug=%s "
            "AND started_at > NOW() - INTERVAL '24 hour'",
            (matter_slug,),
        )
        n = (cur.fetchone() or [0])[0]
        cur.close()
        return int(n)
    finally:
        store._put_conn(conn)


async def stream_cycle_events(
    *, matter_slug: str, director_question: str, triggered_by: str = "director_manual",
) -> AsyncIterator[str]:
    """Spawn maybe_run_cycle in background. Yield SSE-formatted phase events.
    Yields strings already wrapped in 'data: {...}\\n\\n' format.
    """
    from orchestrator.cortex_runner import maybe_run_cycle
    yield _sse({"type": "started", "matter_slug": matter_slug,
                "triggered_by": triggered_by, "ts": time.time()})

    cycle_task = asyncio.create_task(
        maybe_run_cycle(
            matter_slug=matter_slug,
            triggered_by=triggered_by,
            director_question=director_question,
        )
    )

    last_phase: Optional[str] = None
    last_phase_output_count = 0
    while not cycle_task.done():
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        snap = _snapshot_cycle(matter_slug=matter_slug, triggered_by=triggered_by)
        if not snap: continue
        if snap.get("current_phase") != last_phase:
            last_phase = snap.get("current_phase")
            yield _sse({"type": "phase_changed", "phase": last_phase,
                        "cycle_id": snap.get("cycle_id"), "ts": time.time()})
        po_count = snap.get("phase_outputs_count", 0)
        if po_count > last_phase_output_count:
            last_phase_output_count = po_count
            yield _sse({"type": "phase_output", "count": po_count,
                        "cycle_id": snap.get("cycle_id"), "ts": time.time()})

    try:
        cycle = await cycle_task
        yield _sse({"type": "terminal", "status": cycle.status,
                    "cycle_id": cycle.cycle_id,
                    "cost_dollars": float(cycle.cost_dollars or 0.0),
                    "cost_tokens": int(cycle.cost_tokens or 0),
                    "aborted_reason": getattr(cycle, "aborted_reason", None),
                    "ts": time.time()})
    except asyncio.TimeoutError:
        yield _sse({"type": "terminal", "status": "timeout", "ts": time.time()})
    except Exception as e:
        logger.error("cortex_run stream cycle failed matter=%s: %s", matter_slug, e)
        yield _sse({"type": "terminal", "status": "failed",
                    "error": str(e)[:200], "ts": time.time()})


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _snapshot_cycle(*, matter_slug: str, triggered_by: str) -> Optional[dict]:
    """Return the latest in-flight cycle row for (matter_slug, triggered_by)."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn: return None
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT cycle_id, status, current_phase "
            "FROM cortex_cycles "
            "WHERE matter_slug=%s AND triggered_by=%s "
            "ORDER BY started_at DESC LIMIT 1",
            (matter_slug, triggered_by),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return None
        cycle_id, status, current_phase = row
        cur.execute(
            "SELECT COUNT(*) FROM cortex_phase_outputs WHERE cycle_id=%s",
            (cycle_id,),
        )
        po_count = int((cur.fetchone() or [0])[0])
        cur.close()
        return {"cycle_id": cycle_id, "status": status,
                "current_phase": current_phase, "phase_outputs_count": po_count}
    finally:
        store._put_conn(conn)
```

### File 2: MODIFY `outputs/dashboard.py`

Insert new endpoint near other `/api/cortex/*` routes (after `/api/cortex/trigger`). Pattern:

```python
from fastapi.responses import StreamingResponse
from outputs.cortex_run_stream import (
    stream_cycle_events, runs_in_last_hour, specialist_calls_today,
    RUN_RATE_LIMIT_PER_HOUR, COST_WARN_SPECIALIST_PER_DAY,
)


class CortexRunRequest(BaseModel):
    matter_slug: str = Field(..., min_length=1, max_length=64)
    director_question: str = Field(..., min_length=10, max_length=4000)
    triggered_by: str = Field(default="director_manual", min_length=1, max_length=64)


@app.post("/api/cortex/run", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def cortex_run_stream(req: CortexRunRequest):
    """Director-invoke streaming Cortex cycle. SSE Phase 1-6 events.

    Rate limit: 5 cycles/hour/matter. Cost warning: 30 specialist
    invocations/day/matter posted to Director Slack DM (warning only).
    """
    n_recent = runs_in_last_hour(req.matter_slug)
    if n_recent >= RUN_RATE_LIMIT_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit: {n_recent} runs in last hour for {req.matter_slug} (cap={RUN_RATE_LIMIT_PER_HOUR})",
        )

    n_specialist = specialist_calls_today(req.matter_slug)
    if n_specialist >= COST_WARN_SPECIALIST_PER_DAY:
        try:
            from outputs.slack_notifier import post_to_channel
            from triggers.cortex_pre_review_gate import DIRECTOR_DM_CHANNEL
            post_to_channel(
                DIRECTOR_DM_CHANNEL,
                f"⚠️ Cortex spend watch: {req.matter_slug} has {n_specialist} specialist "
                f"invocations in last 24h (warn threshold: {COST_WARN_SPECIALIST_PER_DAY}). "
                f"Run proceeding — observability ping only.",
            )
        except Exception as e:
            logger.error("cost-warn Slack post failed: %s", e)

    return StreamingResponse(
        stream_cycle_events(
            matter_slug=req.matter_slug,
            director_question=req.director_question,
            triggered_by=req.triggered_by,
        ),
        media_type="text/event-stream",
    )
```

### File 3: MODIFY `outputs/dashboard.py` `/api/scan` intent routing

Add a new branch after the `clickup_plan` block (~line 7750) BEFORE the RAG fallthrough:

```python
        elif intent.get("type") == "cortex_run_action":
            # CORTEX_MANUAL_INVOKE_1: route "run cortex on <matter>" to streaming endpoint
            _matter = intent.get("matter_slug", "").strip()
            if not _matter:
                logger.warning("cortex_run_action intent missing matter_slug; falling through")
            else:
                logger.info("SCAN_DEBUG: routing to cortex_run_stream matter=%s", _matter)
                return StreamingResponse(
                    stream_cycle_events(
                        matter_slug=_matter,
                        director_question=req.question,
                        triggered_by="scan_intent",
                    ),
                    media_type="text/event-stream",
                )
```

### File 4: MODIFY intent classifier (`_ah.classify_intent`)

Locate `classify_intent` (search `kbl/anthropic_helper.py` or wherever `_ah` resolves). Add a new intent type `cortex_run_action` to the LLM-side prompt + the JSON schema returned. Trigger phrases:
- "run cortex on <matter>"
- "fire cortex for <matter>"
- "cortex review on <matter>"

Output shape:
```json
{"type": "cortex_run_action", "matter_slug": "hagenauer-rg7", "question": "<full Director ask>"}
```

Constrain `matter_slug` to canonical slugs (load list from `kbl/slug_registry.py` or hardcode the active set if classifier prompt grows too large). On no-match → fall through to RAG.

### File 5: NEW `tests/test_cortex_run_endpoint.py` (~250 LOC, 8 tests)

Coverage:
1. `runs_in_last_hour` returns 0 when no rows / N when N rows (live-PG, auto-skip if `TEST_DATABASE_URL` unset)
2. `specialist_calls_today` same shape (live-PG)
3. `stream_cycle_events` emits `started` + `phase_changed` + `terminal` (mock `maybe_run_cycle` + `_snapshot_cycle`)
4. `POST /api/cortex/run` happy path → 200 + `text/event-stream` content-type + at least 1 SSE chunk
5. Auth: missing `X-Baker-Key` → 401
6. Validation: short `director_question` → 422
7. Rate limit: 6th request in same hour → 429 (mock `runs_in_last_hour` to return 5)
8. Cost-warn: when `specialist_calls_today` ≥ 30 → run proceeds + Slack `post_to_channel` called once

---

## Key Constraints

- DO NOT change `maybe_run_cycle` signature.
- DO NOT add a new auth mechanism — reuse `Depends(verify_api_key)` exactly.
- DO NOT log `req.director_question` at info-level — sensitive matter content (only error-level OK).
- DO NOT make rate-limit a hard CAP on cost-warn — warn-only per Director's intent (observability).
- DO NOT instantiate `SentinelStoreBack()` directly — use `_get_global_instance()` (CI guard `scripts/check_singletons.sh`).
- DO NOT bypass the existing `/api/cortex/trigger` — keep it (sync clients still need it).
- DO NOT add a new env var beyond the 3 declared (`CORTEX_RUN_POLL_INTERVAL`, `CORTEX_RUN_RATE_LIMIT`, `CORTEX_COST_WARN_SPECIALIST_PER_DAY`).

## Quality Checkpoints

1. `python3 -c "import py_compile; py_compile.compile('outputs/cortex_run_stream.py', doraise=True)"` clean
2. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` clean
3. `pytest tests/test_cortex_run_endpoint.py -v` — 8/8 PASS literal
4. Regression: `pytest tests/test_cortex_runner_phase126.py tests/test_cortex_pre_review_gate.py tests/test_cortex_action_endpoint.py -v` PASS
5. `bash scripts/check_singletons.sh` clean
6. `req.director_question` not info-logged anywhere new (grep your diff)
7. Post-deploy smoke (Render): curl with X-Baker-Key returns `text/event-stream` and ≥3 SSE chunks for AO matter
8. Scan smoke: ask Baker "run cortex on oskolkov — quick smoke" → SSE proxied through Scan UI

## Post-deploy verification (AI Head)

```sql
-- Confirm a manual cycle row landed
SELECT cycle_id, matter_slug, triggered_by, status, current_phase,
       cost_dollars, started_at, completed_at
FROM cortex_cycles
WHERE triggered_by IN ('director_manual','scan_intent')
ORDER BY started_at DESC LIMIT 5;
```

```bash
# SSE live stream smoke
BAKER_KEY="bakerbhavanga"
curl -N -X POST "https://baker-master.onrender.com/api/cortex/run" \
  -H "Content-Type: application/json" \
  -H "X-Baker-Key: $BAKER_KEY" \
  -d '{"matter_slug":"oskolkov","director_question":"Smoke — confirm SSE stream emits phase events.","triggered_by":"post_deploy_smoke"}'
# Expected: data: {"type":"started",...} → data: {"type":"phase_changed","phase":"sense"...} → ... → data: {"type":"terminal",...}
```

## Files Modified / Added

- `outputs/cortex_run_stream.py` — NEW (~180 LOC)
- `outputs/dashboard.py` — modified (+ ~80 LOC: imports, model, endpoint, scan branch)
- intent classifier source (likely `kbl/anthropic_helper.py`) — modified (+ new intent shape)
- `tests/test_cortex_run_endpoint.py` — NEW (~250 LOC, 8 tests)

## Do NOT Touch

- `orchestrator/cortex_runner.py` — out of scope. Signature, timeouts, error semantics unchanged.
- `triggers/cortex_pipeline.py` / `triggers/cortex_pre_review_gate.py` — out of scope (Track 2 = Brief 2 owns gate changes; do not race).
- Existing `/api/cortex/trigger` — leave intact (sync path).
- Frontend / static assets — no UI work in this brief.

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
