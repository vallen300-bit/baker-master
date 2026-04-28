# BRIEF: CORTEX_TRIGGER_ENDPOINT_1 — Director-invoke Cortex cycle from anywhere via HTTP

## Context

Cortex V1 is LIVE on AO matter (CORTEX_DRY_RUN=false flipped 2026-04-28T21:55Z). The 5/5 dry-run promotion gate cleared with bland smoke prompts.

Tonight's first REAL cycle attempt on AO matter (cycle_id=8ba8efc3) **FAILED** with finance specialist 60s × 3 timeout. Refire with finance disabled also looks set to fail (sales attempt 1 + 2 already timed out at B3).

**Root cause:** specialist tool-use chains call Render-internal Postgres + Qdrant. From B3's local network, every tool round-trip pays cross-network latency. Light prompts fit in 60s; rich prompts don't. Disabling more capabilities is futile — it's question-weight + locality, not capability-specific.

**Fix:** add an HTTP endpoint that triggers `maybe_run_cycle` **inside the Render web-service container**, where DB+Qdrant are localhost. Director (or B-codes, or future Slack interactivity proxy) curl the endpoint with X-Baker-Key and a Director question; cycle runs at full speed; result returns or polls.

This is the proper production trigger anyway — needed for the eventual Slack interactivity proxy and any UI button.

## Estimated time: ~45min (build 25min + tests 10min + B1 review 10min)
## Complexity: Low
## Prerequisites: none — `maybe_run_cycle` already exists at `orchestrator/cortex_runner.py:62`. Auth pattern already exists.

## Trigger class: HIGH

This PR ships:
- new external HTTP endpoint
- new auth surface (X-Baker-Key on a write path)
- triggers a cycle that may produce real Slack DMs + DB writes

→ B1 situational review REQUIRED per RA-24 trigger (external API + auth) before merge. Builder ≠ B1.

**Build assignment:** B2 (App). **Review assignment:** B1 (formal) + AI Head A (/security-review + structural).

---

## Fix/Feature 1: POST /api/cortex/trigger

### Problem

No HTTP-callable entry point to `maybe_run_cycle`. Today the only invocations are:
1. `triggers/cortex_pipeline.py` (auto-dispatch from alerts_to_signal — fires when a real email/WA/meeting lands)
2. Local python REPL via B-code worktree (subject to cross-network specialist timeout)
3. Tests

Director can't fire a cycle on demand. Slack interactivity proxy (parked) will need this endpoint anyway.

### Current State

- `orchestrator/cortex_runner.py:62` — `async def maybe_run_cycle(*, matter_slug: str, triggered_by: str, trigger_signal_id: Optional[int] = None, director_question: Optional[str] = None) -> CortexCycle`
- `outputs/dashboard.py:95` — `verify_api_key` dependency (X-Baker-Key)
- Existing `/api/cortex/*` endpoints at lines 3918, 3970, 4005, 4017 — all read-only.
- `CortexCycle` dataclass has at least these fields used by callers: `cycle_id`, `status`, `current_phase`, `cost_tokens`, `cost_dollars`, `aborted_reason`, `matter_slug`, `triggered_by`. Confirm field names by reading `orchestrator/cortex_runner.py` near the `CortexCycle` dataclass before writing the response model.

### Implementation

**File:** `outputs/dashboard.py`

**Where to insert:** immediately after `get_cortex_stats` (search for `@app.get("/api/cortex/stats"` — insert the new endpoint AFTER its function body ends, before the next `@app.` decorator).

**Imports:** `maybe_run_cycle` is NOT yet imported in dashboard.py. Add at the top of the file alongside other `orchestrator` imports (around line 27-48):

```python
from orchestrator.cortex_runner import maybe_run_cycle
```

**Request body model — insert near other Pydantic models in the file (search for `class .*BaseModel` to find the local convention; add near them):**

```python
class CortexTriggerRequest(BaseModel):
    matter_slug: str = Field(..., min_length=1, max_length=64, description="Matter slug (e.g. 'oskolkov', 'movie')")
    director_question: str = Field(..., min_length=10, max_length=4000, description="Director's question driving the cycle")
    triggered_by: str = Field(default="director_manual", min_length=1, max_length=64, description="Trigger source label")
```

**Endpoint:**

```python
@app.post("/api/cortex/trigger", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def trigger_cortex_cycle(req: CortexTriggerRequest):
    """Director-invoke a Cortex cycle synchronously inside the Render container.

    Designed for: (a) Director curl-from-anywhere on demand, (b) the eventual
    Slack interactivity proxy, (c) UI button clicks.

    Runs maybe_run_cycle inline. Returns the terminal cycle state. The cycle's
    own asyncio.wait_for(timeout=CYCLE_TIMEOUT_SECONDS) bounds total wait time;
    if the cycle exceeds that cap, maybe_run_cycle marks the row 'failed' and
    raises asyncio.TimeoutError, which we translate to HTTP 504.
    """
    try:
        cycle = await maybe_run_cycle(
            matter_slug=req.matter_slug,
            triggered_by=req.triggered_by,
            director_question=req.director_question,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Cortex trigger timed out (matter=%s, triggered_by=%s)",
            req.matter_slug, req.triggered_by,
        )
        raise HTTPException(
            status_code=504,
            detail="Cycle exceeded internal timeout cap",
        )
    except Exception as e:
        logger.error(
            "Cortex trigger failed (matter=%s, triggered_by=%s): %s",
            req.matter_slug, req.triggered_by, e,
        )
        raise HTTPException(status_code=500, detail=f"Cycle invocation failed: {str(e)[:200]}")

    return {
        "cycle_id": cycle.cycle_id,
        "matter_slug": cycle.matter_slug,
        "triggered_by": cycle.triggered_by,
        "status": cycle.status,
        "current_phase": cycle.current_phase,
        "cost_tokens": cycle.cost_tokens,
        "cost_dollars": float(cycle.cost_dollars) if cycle.cost_dollars is not None else 0.0,
        "aborted_reason": getattr(cycle, "aborted_reason", None),
    }
```

### Key Constraints

- DO NOT change `maybe_run_cycle` signature.
- DO NOT add a new auth mechanism — reuse `Depends(verify_api_key)` exactly.
- DO NOT log `req.director_question` or `cycle.aborted_reason` at info-level — only at error level (questions may contain sensitive matter context).
- DO NOT bypass `CYCLE_TIMEOUT_SECONDS` — let it bound the wait. The endpoint will hold the connection up to that cap; Render's edge timeout is higher.
- DO NOT wrap with BackgroundTasks — sync return is intentional for V1; async polling is V1.1 if needed.
- DO NOT add this to the OpenAPI public surface anywhere — it's a Director-only path. The `tags=["cortex"]` is fine.

### Verification

**Local syntax check (B2 before push):**

```bash
cd ~/bm-b2/01_build && python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
```

**Unit test — add to `tests/test_cortex_action_endpoint.py` or create `tests/test_cortex_trigger_endpoint.py`:**

```python
import asyncio
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from outputs.dashboard import app

class _FakeCycle:
    def __init__(self):
        self.cycle_id = "test-cycle-001"
        self.matter_slug = "oskolkov"
        self.triggered_by = "test"
        self.status = "tier_b_pending"
        self.current_phase = "propose"
        self.cost_tokens = 12345
        self.cost_dollars = 0.42
        self.aborted_reason = None

def test_trigger_cortex_cycle_happy_path(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-key-123")
    # Re-read module-level _BAKER_API_KEY (bound at import time)
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = "test-key-123"

    fake_cycle = _FakeCycle()
    with patch("outputs.dashboard.maybe_run_cycle", new=AsyncMock(return_value=fake_cycle)) as m:
        client = TestClient(app)
        resp = client.post(
            "/api/cortex/trigger",
            json={
                "matter_slug": "oskolkov",
                "director_question": "What is AO's actual intention by getting in touch with Siegfried?",
                "triggered_by": "test",
            },
            headers={"X-Baker-Key": "test-key-123"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cycle_id"] == "test-cycle-001"
        assert body["status"] == "tier_b_pending"
        assert body["cost_dollars"] == 0.42
        m.assert_awaited_once()

def test_trigger_cortex_cycle_unauthorized(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-key-123")
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = "test-key-123"

    client = TestClient(app)
    resp = client.post(
        "/api/cortex/trigger",
        json={
            "matter_slug": "oskolkov",
            "director_question": "test question content here",
            "triggered_by": "test",
        },
        headers={"X-Baker-Key": "wrong-key"},
    )
    assert resp.status_code == 401

def test_trigger_cortex_cycle_validation_short_question(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-key-123")
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = "test-key-123"

    client = TestClient(app)
    resp = client.post(
        "/api/cortex/trigger",
        json={
            "matter_slug": "oskolkov",
            "director_question": "tooshort",  # <10 chars
            "triggered_by": "test",
        },
        headers={"X-Baker-Key": "test-key-123"},
    )
    assert resp.status_code == 422

def test_trigger_cortex_cycle_timeout_translates_to_504(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-key-123")
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = "test-key-123"

    async def _raise_timeout(*args, **kwargs):
        raise asyncio.TimeoutError()

    with patch("outputs.dashboard.maybe_run_cycle", new=_raise_timeout):
        client = TestClient(app)
        resp = client.post(
            "/api/cortex/trigger",
            json={
                "matter_slug": "oskolkov",
                "director_question": "valid length question content here",
                "triggered_by": "test",
            },
            headers={"X-Baker-Key": "test-key-123"},
        )
        assert resp.status_code == 504
```

**Run tests:**

```bash
cd ~/bm-b2/01_build && pytest tests/test_cortex_trigger_endpoint.py -v
```

All 4 tests must pass.

**Post-deploy smoke (A or B1 runs):**

```bash
BAKER_KEY="bakerbhavanga"
curl -s -X POST "https://baker-master.onrender.com/api/cortex/trigger" \
  -H "Content-Type: application/json" \
  -H "X-Baker-Key: $BAKER_KEY" \
  -d '{
    "matter_slug": "oskolkov",
    "director_question": "Smoke test: confirm trigger endpoint reaches Phase 1 sense.",
    "triggered_by": "post_deploy_smoke"
  }' | jq .
```

Expected: 200 with cycle_id + status (could be `tier_b_pending` if specialists run cleanly, or `failed` with aborted_reason — either confirms the endpoint reached `maybe_run_cycle`).

---

## Files Modified

- `outputs/dashboard.py` — add import + Pydantic model + endpoint (3 insertions, ~70 LOC total)
- `tests/test_cortex_trigger_endpoint.py` — NEW file with 4 tests (~120 LOC)

## Do NOT Touch

- `orchestrator/cortex_runner.py` — out of scope. Its signature, timeout, and error semantics stay.
- `triggers/cortex_pipeline.py` — out of scope. Auto-dispatch path is unchanged.
- `outputs/dashboard.py` other endpoints — surgical addition only.
- Any frontend / static — no UI work in this brief.

## Quality Checkpoints

1. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` clean
2. `pytest tests/test_cortex_trigger_endpoint.py -v` — all 4 tests PASS literally (no "by inspection" per Lesson #48)
3. Endpoint requires X-Baker-Key (confirmed by 401 test)
4. Pydantic validation rejects short director_question (confirmed by 422 test)
5. asyncio.TimeoutError translates to HTTP 504 (confirmed by test)
6. Sensitive payload not info-logged (only error-level logging contains matter_slug + triggered_by, NOT director_question)
7. After Render redeploy, post-deploy smoke curl returns 200 + cycle_id

## Verification SQL (post-deploy)

```sql
-- Confirm a cycle row landed from the trigger endpoint
SELECT cycle_id, matter_slug, triggered_by, status, current_phase, started_at, completed_at, cost_dollars
FROM cortex_cycles
WHERE triggered_by = 'post_deploy_smoke'
   OR triggered_by = 'director_manual'
ORDER BY started_at DESC
LIMIT 5;
```

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
