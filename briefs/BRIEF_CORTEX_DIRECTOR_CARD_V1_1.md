# BRIEF: CORTEX_DIRECTOR_CARD_V1_1 — Gemini 2.5 Pro swap + smoke-cycle filter

**Amends:** v1.0 `briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1.md` (PR #226, merged `5db210a`).
**Ratified:** Director 2026-05-20 night ("genini pro" + 1/2/3 approved, 4 no retranslate).
**Target:** b1.
**Branch:** `b1/cortex-director-card-v1-1`.
**Ship target:** Wed 2026-05-21 midday.

## Context

Director used the Director Card panel for the first time in prod tonight. Two issues:

1. **Haiku-distrust on Director-facing surface.** Director-ratified scar — Haiku 4.5 is no longer trusted for Director-facing translation. Sonnet 4.6 / Gemini 2.5 Pro are the defaults; Haiku stays for internal-only capabilities. Tonight Director approved swap to `gemini-2.5-pro` as the primary translator for Phase 4.5 with Sonnet 4.6 as fallback on any Gemini failure.
2. **Signal-to-noise.** 14 of the last 15 cards on the Pending tab were Oskolkov smoke / heartbeat / health-check cycles ("Smoke #3 health check" style). Director's signal is buried. v1.1 adds a default-hide smoke filter on the Pending tab with a "Show all" toggle.

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** toggle visibility of smoke/test cycles in the Cortex Pending tab (click toggle button → re-fetch + re-render the list).
2. **Backend route:** `GET /api/cortex/cycles/pending` at `outputs/dashboard.py:4559` — signature (post-v1.1): `async def list_cortex_cycles_pending(limit: int = 50, include_smoke: bool = False)`.
3. **Endpoint contract:** query params `limit: int = 50`, `include_smoke: bool = False`; auth header `X-Baker-Key` via `Depends(verify_api_key)`; returns JSON `{"cycles": [...], "count": int, "smoke_hidden_count": int, "include_smoke": bool}` where each cycle carries a new boolean `is_smoke`. v1.0 callers reading the v1.0 fields are unaffected — additions only.
4. **State location:** Postgres tables `cortex_cycles` (status, triggered_by, signal_text) + `cortex_phase_outputs` (synthesis proposal_text + director_card payload) in `baker-master`.
5. **UI repo (= state repo):** `baker-master` — surface: main dashboard Cortex Intent Feed → Pending sub-tab (existing surface from PR #223; v1.1 only adds a toggle button + smoke tag inside it).
6. **Director surface preference:** asked + ratified 2026-05-19 — chose `web dashboard` because Director explicitly rejected Slack as ratify surface that same day. v1.1 extends the already-ratified surface; no new surface introduced.
7. **Gate-1+2 reviewer instruction:** Reviewers MUST load `/api/cortex/cycles/pending` AND `/api/cortex/cycles/pending?include_smoke=true` with the exact `X-Baker-Key` header the frontend sends, confirm non-error responses, AND inspect a live Pending-tab render in a browser (toggle visible at its centroid via `elementFromPoint` per PR #224 lesson). Code-shape review (XSS-safe `esc()`, pytest green) is necessary but NOT sufficient.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites
- v1.0 (PR #226) merged + live (confirmed `266ca09` on main).
- `GEMINI_API_KEY` set on Render `baker-master` service (b1 verifies in §Pre-flight; if absent, STOP and bus-post `lead` for AH1 to handle Tier-B env-set).
- `ANTHROPIC_API_KEY` already on Render (unchanged from v1.0).

---

## Fix/Feature 1: Swap Haiku → Gemini 2.5 Pro with Sonnet 4.6 fallback

### Problem
Phase 4.5 currently calls Anthropic Haiku 4.5 directly via `client.messages.create(...)` in `orchestrator/cortex_phase4_5_director_card.py`. Director distrusts Haiku output quality for Director-facing surfaces.

### Current State
`orchestrator/cortex_phase4_5_director_card.py` lines 23-29, 109-124, 287-306, 328-336:

- `_DEFAULT_MODEL = "claude-haiku-4-5-20251001"`
- `_MODEL_ENV = "ANTHROPIC_MODEL_HAIKU"`
- `_API_KEY_ENV = "ANTHROPIC_API_KEY"`
- `_PRICE_HAIKU_INPUT_PER_M` / `_PRICE_HAIKU_OUTPUT_PER_M`
- `_get_client()` → `anthropic.Anthropic(api_key=key)`
- `client.messages.create(model=..., system=SYSTEM_PROMPT, messages=[...])`
- `_compute_haiku_cost_eur(input_tokens, output_tokens)`

Existing Gemini client at `orchestrator/gemini_client.py` exposes:
```python
from orchestrator.gemini_client import generate
resp = generate(model="gemini-2.5-pro", messages=[{"role":"user","content":"..."}], max_tokens=600, system=SYSTEM_PROMPT)
text = resp.text
in_tok = resp.usage.input_tokens
out_tok = resp.usage.output_tokens
```

### Implementation

**File: `orchestrator/cortex_phase4_5_director_card.py`**

1. **Constants block (replace lines 21-34):**

```python
# --- Model / pricing constants ------------------------------------------------

# Primary: Gemini 2.5 Pro via orchestrator.gemini_client.
# Fallback: Anthropic Sonnet 4.6 on ANY Gemini call/parse/schema failure.
_PRIMARY_MODEL = "gemini-2.5-pro"
_PRIMARY_MODEL_ENV = "GEMINI_MODEL_DIRECTOR_CARD"
_FALLBACK_MODEL = "claude-sonnet-4-6"
_FALLBACK_MODEL_ENV = "ANTHROPIC_MODEL_DIRECTOR_CARD_FALLBACK"
_ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"

# USD per 1M tokens — Gemini 2.5 Pro public list pricing (May 2026):
# input $1.25 / output $5.00. Sonnet 4.6 fallback: $3.00 / $15.00.
_PRICE_GEMINI_PRO_INPUT_PER_M = float(os.getenv("PRICE_GEMINI_PRO_IN", "1.25"))
_PRICE_GEMINI_PRO_OUTPUT_PER_M = float(os.getenv("PRICE_GEMINI_PRO_OUT", "5.00"))
_PRICE_SONNET_INPUT_PER_M = float(os.getenv("PRICE_SONNET4_IN", "3.00"))
_PRICE_SONNET_OUTPUT_PER_M = float(os.getenv("PRICE_SONNET4_OUT", "15.00"))

_MAX_TOKENS = 600
_TEMPERATURE = 0.0
_PROPOSAL_INPUT_TRIM = 6000
```

2. **Rename `_get_client()` → `_get_anthropic_fallback_client()` (lines 109-129):**

```python
_anthropic_client = None


def _get_anthropic_fallback_client():
    """Return cached anthropic.Anthropic client for Sonnet fallback. Lazy."""
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        key = os.environ.get(_ANTHROPIC_API_KEY_ENV)
        if not key:
            raise RuntimeError(f"{_ANTHROPIC_API_KEY_ENV} env var not set")
        _anthropic_client = anthropic.Anthropic(api_key=key)
    return _anthropic_client


def _reset_client_for_tests() -> None:
    global _anthropic_client
    _anthropic_client = None
```

3. **Cost helpers (replace `_compute_haiku_cost_eur` at lines 202-213):**

```python
def _compute_gemini_pro_cost_eur(input_tokens: int, output_tokens: int) -> float:
    total_per_m = (
        input_tokens * _PRICE_GEMINI_PRO_INPUT_PER_M
        + output_tokens * _PRICE_GEMINI_PRO_OUTPUT_PER_M
    )
    return float(total_per_m / 1_000_000.0)


def _compute_sonnet_cost_eur(input_tokens: int, output_tokens: int) -> float:
    total_per_m = (
        input_tokens * _PRICE_SONNET_INPUT_PER_M
        + output_tokens * _PRICE_SONNET_OUTPUT_PER_M
    )
    return float(total_per_m / 1_000_000.0)
```

4. **`translate_to_director_card()` (replace lines 255-337):** restructure into try-Gemini-then-Sonnet flow. Each path returns either a fully-validated card (with `_meta` stamped) or `FAIL_OPEN_SENTINEL`. Top-level catches Gemini failure, calls Sonnet fallback; if fallback also fails, returns the sentinel. The function NEVER raises.

```python
def translate_to_director_card(
    *,
    cycle_id: str,
    proposal_text: str,
    matter_slug: str,
    cost_telemetry: Optional[dict] = None,
) -> Optional[dict]:
    """Translate technical proposal_text into a 9-field Director Card.

    Primary: Gemini 2.5 Pro. Fallback (on any Gemini failure): Anthropic
    Sonnet 4.6. Returns the card dict on success (with ``_meta.fallback_used``
    stamped), ``FAIL_OPEN_SENTINEL`` on double failure. Never raises.
    """
    if not proposal_text:
        return None

    primary_model = os.environ.get(_PRIMARY_MODEL_ENV, _PRIMARY_MODEL)
    fallback_model = os.environ.get(_FALLBACK_MODEL_ENV, _FALLBACK_MODEL)
    user_text = _build_user_prompt(
        matter_slug=matter_slug,
        proposal_text=proposal_text[:_PROPOSAL_INPUT_TRIM],
        cost_telemetry=cost_telemetry or {},
    )

    # --- Primary: Gemini 2.5 Pro --------------------------------------------
    try:
        from orchestrator.gemini_client import generate as gemini_generate
        resp = gemini_generate(
            model=primary_model,
            messages=[{"role": "user", "content": user_text}],
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
        )
        raw_text = getattr(resp, "text", "") or ""
        in_tok = int(getattr(getattr(resp, "usage", None), "input_tokens", 0) or 0)
        out_tok = int(getattr(getattr(resp, "usage", None), "output_tokens", 0) or 0)
        parsed = _parse_json_response(raw_text)
        if parsed is not None:
            sanitized = _sanitize_card(parsed)
            err = _validate_card_schema(sanitized)
            if err is None:
                sanitized["_meta"] = {
                    "model": primary_model,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "card_gen_cost_eur": _compute_gemini_pro_cost_eur(in_tok, out_tok),
                    "fallback_used": False,
                }
                return sanitized
            logger.warning(
                "[phase4_5] cycle %s: gemini schema invalid (%s); trying Sonnet fallback",
                cycle_id, err,
            )
        else:
            logger.warning(
                "[phase4_5] cycle %s: gemini returned non-JSON; trying Sonnet fallback",
                cycle_id,
            )
    except Exception as e:
        logger.warning(
            "[phase4_5] cycle %s: gemini call failed (%s); trying Sonnet fallback",
            cycle_id, e,
        )

    # --- Fallback: Anthropic Sonnet 4.6 -------------------------------------
    try:
        client = _get_anthropic_fallback_client()
    except Exception as e:
        logger.warning("[phase4_5] cycle %s: no anthropic client for fallback: %s", cycle_id, e)
        return FAIL_OPEN_SENTINEL

    try:
        response = client.messages.create(
            model=fallback_model,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_text}],
        )
    except Exception as e:
        logger.warning("[phase4_5] cycle %s: sonnet fallback also failed: %s", cycle_id, e)
        return FAIL_OPEN_SENTINEL

    raw_text = _extract_text(getattr(response, "content", None))
    parsed = _parse_json_response(raw_text)
    if parsed is None:
        logger.warning("[phase4_5] cycle %s: sonnet fallback returned non-JSON", cycle_id)
        return FAIL_OPEN_SENTINEL
    sanitized = _sanitize_card(parsed)
    err = _validate_card_schema(sanitized)
    if err:
        logger.warning("[phase4_5] cycle %s: sonnet fallback schema invalid: %s", cycle_id, err)
        return FAIL_OPEN_SENTINEL

    usage = getattr(response, "usage", None)
    in_tok = int(getattr(usage, "input_tokens", 0) or 0)
    out_tok = int(getattr(usage, "output_tokens", 0) or 0)
    sanitized["_meta"] = {
        "model": getattr(response, "model", fallback_model),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "card_gen_cost_eur": _compute_sonnet_cost_eur(in_tok, out_tok),
        "fallback_used": True,
    }
    return sanitized
```

### Key Constraints

- Fail-open contract preserved: `translate_to_director_card` NEVER raises. Every failure path returns `None` or `FAIL_OPEN_SENTINEL`.
- `SYSTEM_PROMPT`, `_build_user_prompt`, `_parse_json_response`, `_sanitize_card`, `_validate_card_schema`, `persist_director_card`, `run_phase4_5_director_card` — UNCHANGED. Only the model-call layer + cost helpers change.
- Sonnet 4.6 fallback uses the SAME schema + same prompt — schema validator must pass for both.
- `_meta.fallback_used` is the ONLY new schema field. v1.0 callers that don't read `_meta` are unaffected.

### Verification

1. Unit tests in `tests/test_cortex_phase4_5_director_card.py`:
   - Existing 25 tests must still pass. Adapt any model-name assertion (Haiku → Gemini OR Sonnet depending on which mocked path the test drives).
   - **New test 1:** `test_gemini_primary_success_path` — monkeypatch `orchestrator.gemini_client.generate` to return a valid `GeminiResponse`. Assert `_meta.model == "gemini-2.5-pro"`, `_meta.fallback_used == False`, `_meta.card_gen_cost_eur > 0`.
   - **New test 2:** `test_sonnet_fallback_on_gemini_exception` — `gemini_generate` raises; Anthropic client returns valid response. Assert `_meta.model` contains "sonnet", `_meta.fallback_used == True`.
   - **New test 3:** `test_sonnet_fallback_on_gemini_invalid_json` — Gemini returns garbage text; Sonnet returns valid JSON. Same assertions as test 2.
   - **New test 4:** `test_sonnet_fallback_on_gemini_schema_invalid` — Gemini returns valid JSON missing `cost.action_sends_money`; Sonnet returns valid card. Same assertions as test 2.
   - **New test 5:** `test_double_failure_returns_sentinel` — both Gemini AND Sonnet raise. Assert return is `FAIL_OPEN_SENTINEL` (i.e., `None`). No exception escapes.
   - **New test 6:** `test_gemini_no_api_key_falls_back` — `GEMINI_API_KEY` unset → `gemini_generate` raises → Sonnet serves the card.

2. Manual smoke (post-merge):
   - `POST /api/cortex/run` with `matter_slug=oskolkov`, `topic="V1.1 smoke"`, `trigger=director_manual`.
   - DB: `SELECT payload->'_meta' FROM cortex_phase_outputs WHERE cycle_id='<new>' AND artifact_type='director_card'` — confirm `model="gemini-2.5-pro"`, `fallback_used=false`.
   - Render logs `[phase4_5]` should show ZERO fallback warnings on the healthy path.

---

## Fix/Feature 2: Smoke-cycle filter on Pending tab

### Problem
14 of last 15 cycles on the Pending tab were Oskolkov smoke / heartbeat / health-check noise. Director's real-cycle signal is buried. Need a default-hide filter with a "Show all" toggle.

### Current State

Backend: `outputs/dashboard.py:4559` `list_cortex_cycles_pending(limit: int = 50)` returns ALL `tier_b_pending` cycles. No notion of smoke vs real.

Frontend: `outputs/static/app.js` renders the Pending tab via the response from `/api/cortex/cycles/pending` (shipped under PR #223 / amended PR #224 hitbox). No filter UI exists today.

### Implementation

**Step 2.1 — Backend: derive `is_smoke` boolean + add `include_smoke` query param.**

Modify `list_cortex_cycles_pending` in `outputs/dashboard.py` (around line 4559):

```python
@app.get(
    "/api/cortex/cycles/pending",
    tags=["cortex"],
    dependencies=[Depends(verify_api_key)],
)
async def list_cortex_cycles_pending(
    limit: int = 50,
    include_smoke: bool = False,
):
    """List Cortex cycles awaiting Director ratification.

    By default, smoke / heartbeat / health-check cycles are EXCLUDED so
    Director sees only real cycles. Pass ``include_smoke=true`` for the
    full set (used by the frontend "Show all" toggle).

    A cycle is smoke when ANY of:
      - triggered_by ILIKE '%smoke%' OR '%health%' OR '%self_wake_smoke%'
      - signal_text ILIKE '%smoke #%' OR '%health check%' OR '%heartbeat%'
      - latest synthesis proposal_text starts with 'Smoke #' (first 200 chars)
    """
```

SQL — single query for the visible set, second query for the hidden count:

```sql
-- Visible set (filtered or not based on include_smoke):
WITH base AS (
    SELECT
        c.cycle_id::text AS cycle_id,
        c.matter_slug,
        c.triggered_by,
        c.current_phase,
        c.cost_dollars,
        c.cost_tokens,
        c.started_at,
        EXTRACT(EPOCH FROM (NOW() - c.started_at))/60 AS age_minutes,
        c.signal_text,
        (
          SELECT po.payload->>'proposal_text'
          FROM cortex_phase_outputs po
          WHERE po.cycle_id = c.cycle_id
            AND po.artifact_type = 'synthesis'
          ORDER BY po.created_at DESC
          LIMIT 1
        ) AS proposal_text,
        (
          SELECT po.payload
          FROM cortex_phase_outputs po
          WHERE po.cycle_id = c.cycle_id
            AND po.artifact_type = 'director_card'
          ORDER BY po.created_at DESC
          LIMIT 1
        ) AS director_card
    FROM cortex_cycles c
    WHERE c.status = 'tier_b_pending'
),
flagged AS (
    SELECT
        b.*,
        (
            COALESCE(b.triggered_by, '') ILIKE '%smoke%'
         OR COALESCE(b.triggered_by, '') ILIKE '%health%'
         OR COALESCE(b.triggered_by, '') ILIKE '%self_wake_smoke%'
         OR COALESCE(b.signal_text, '')  ILIKE '%smoke #%'
         OR COALESCE(b.signal_text, '')  ILIKE '%health check%'
         OR COALESCE(b.signal_text, '')  ILIKE '%heartbeat%'
         OR LEFT(COALESCE(b.proposal_text, ''), 200) ILIKE '%smoke #%'
        ) AS is_smoke
    FROM base b
)
SELECT *
FROM flagged
WHERE (%(include_smoke)s OR NOT is_smoke)
ORDER BY started_at DESC
LIMIT %(limit)s;
```

Pass `include_smoke` + `limit` via named params dict. Existing `psycopg2.extras.RealDictCursor` already imported in the function.

Hidden-count follow-up query (reuse same conn):

```python
cur.execute(
    """
    SELECT COUNT(*) AS hidden
    FROM cortex_cycles c
    WHERE c.status = 'tier_b_pending'
      AND (
            COALESCE(c.triggered_by, '') ILIKE '%smoke%'
         OR COALESCE(c.triggered_by, '') ILIKE '%health%'
         OR COALESCE(c.triggered_by, '') ILIKE '%self_wake_smoke%'
         OR COALESCE(c.signal_text, '')  ILIKE '%smoke #%'
         OR COALESCE(c.signal_text, '')  ILIKE '%health check%'
         OR COALESCE(c.signal_text, '')  ILIKE '%heartbeat%'
      )
    """
)
hidden_row = cur.fetchone()
smoke_hidden_count = int(hidden_row["hidden"] or 0) if hidden_row else 0
```

Response shape additions:

```python
return {
    "cycles": cycles,
    "count": len(cycles),
    "smoke_hidden_count": smoke_hidden_count if not include_smoke else 0,
    "include_smoke": include_smoke,
}
```

Each cycle dict gains exactly one new field: `"is_smoke": bool(r.get("is_smoke"))`.

**Step 2.2 — Frontend: "Show all" toggle on Pending tab.**

In `outputs/static/app.js`:

1. Add module-scoped `let includeSmoke = false;` near the existing Cortex tab state.
2. Adjust the Pending fetch URL: `'/api/cortex/cycles/pending?include_smoke=' + (includeSmoke ? 'true' : 'false')`.
3. Render the toggle button INSIDE the Pending tab body (NOT in the main tab bar — PR #224 hitbox lesson):

```javascript
// Pending tab body renderer, before the cycle list:
const headerEl = document.createElement('div');
headerEl.className = 'pending-filter-row';

const toggleBtn = document.createElement('button');
toggleBtn.className = 'pending-smoke-toggle';
toggleBtn.type = 'button';
const hiddenN = data.smoke_hidden_count || 0;
toggleBtn.appendChild(document.createTextNode(
    includeSmoke
        ? 'Hide smoke/test cycles'
        : (hiddenN > 0
            ? 'Show all (incl. ' + hiddenN + ' smoke)'
            : 'Show all')
));
toggleBtn.addEventListener('click', () => {
    includeSmoke = !includeSmoke;
    refreshPendingTab();   // existing refresh — reuse, do not duplicate
});
headerEl.appendChild(toggleBtn);
pendingContainerEl.appendChild(headerEl);
```

4. Per-card smoke chip — only renders when `cycle.is_smoke` is true (visible only when the toggle is in "Show all" mode, since filtered mode has no smoke cycles in the list):

```javascript
if (cycle.is_smoke) {
    const chip = document.createElement('span');
    chip.className = 'cycle-smoke-tag';
    chip.appendChild(document.createTextNode('smoke'));
    cycleTitleEl.appendChild(chip);
}
```

5. **CSS additions in `outputs/static/style.css`:**

```css
.pending-filter-row {
  display: flex;
  justify-content: flex-end;
  padding: 8px 12px 0 12px;
}

.pending-smoke-toggle {
  background: transparent;
  border: 1px solid var(--border-subtle, #d0d0d0);
  border-radius: 4px;
  padding: 4px 10px;
  font-size: 12px;
  color: var(--text-secondary, #666);
  cursor: pointer;
}
.pending-smoke-toggle:hover { background: var(--bg-hover, #f5f5f5); }

.cycle-smoke-tag {
  display: inline-block;
  margin-left: 8px;
  padding: 1px 6px;
  border-radius: 3px;
  background: #eee;
  color: #888;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
```

6. **Cache-bust:** in `outputs/static/index.html`, bump `style.css?v=76` → `style.css?v=77` and `app.js?v=N` → next integer (read current value, increment by 1).

### Key Constraints

- Toggle button MUST live in the Pending tab body — NOT the main tab bar. PR #224 hitbox lesson: do not overlay clickable elements on the tab strip.
- Per-cycle `is_smoke` flag is computed in the API response only; do NOT add a column to `cortex_cycles`. No migration in this brief.
- Filter is purely cosmetic — every cycle stays in DB, every cycle is still ratifiable via direct cycle-id URL. Filter only affects default render.
- Toggle state is per-page-session — does NOT persist to localStorage in v1.1 (queued as fast-follow).
- `include_smoke` defaults to `false` server-side — even a caller that omits the param sees the filtered view by default.

### Verification

1. Backend tests in `tests/test_dashboard_cortex_ratify.py`:
   - **Add `test_pending_filters_smoke_by_default`** — seed 2 smoke cycles (`triggered_by="smoke_test"`) + 1 real cycle. GET `/api/cortex/cycles/pending`. Assert `count==1`, `smoke_hidden_count==2`, returned cycle has `is_smoke==False`.
   - **Add `test_pending_include_smoke_true_returns_all`** — same fixture. GET `?include_smoke=true`. Assert `count==3`, `smoke_hidden_count==0`. At least one returned cycle has `is_smoke==True`.
   - **Add `test_pending_signal_text_smoke_marker`** — cycle with `triggered_by="director_manual"` but `signal_text="Smoke #4 health check"`. Default GET excludes it; `include_smoke=true` includes it with `is_smoke==True`.
   - **Add `test_pending_proposal_text_smoke_marker`** — cycle with normal triggered_by + signal_text but synthesis `proposal_text` starts with "Smoke #5 …". Same expectations.

2. Frontend smoke (post-merge):
   - Open `https://baker-master.onrender.com/` → Cortex tab → Pending sub-tab.
   - Default view: smoke cycles hidden. Button reads "Show all (incl. N smoke)".
   - Click toggle: panel re-renders with all cycles; smoke ones carry the `cycle-smoke-tag` chip; button text flips to "Hide smoke/test cycles".
   - Click toggle again: returns to filtered view.
   - `elementFromPoint` cursor-click verification: the new toggle button is clickable at its visible rectangle centroid — no overlap from `cortexCount`, tab strip, or sibling controls.

---

## Pre-flight checks (b1 must run before opening PR)

1. **`GEMINI_API_KEY` on Render `baker-master`:** check via `tools/render_env_guard.py` helpers. If absent, STOP and bus-post `lead` with topic `blocker/cortex-director-card-v1-1-gemini-key`. AH1 handles Render Tier-B env-set with Director auth. Do NOT attempt to set env vars from b1.
2. **`ANTHROPIC_API_KEY` on Render:** known-set from v1.0; sanity grep only.
3. **`orchestrator/gemini_client.py` signature** — confirm `generate(model, messages, max_tokens=..., system=...)` returns `.text` + `.usage.input_tokens` + `.usage.output_tokens` (confirmed in this brief; b1 sanity-greps before writing the swap).
4. **Baseline tests** — run `pytest tests/test_cortex_phase4_5_director_card.py tests/test_dashboard_cortex_ratify.py -v` BEFORE any edits, so regressions are attributable.

## Files Modified

- `orchestrator/cortex_phase4_5_director_card.py` — model swap + Sonnet fallback + cost helpers
- `outputs/dashboard.py` — `list_cortex_cycles_pending` gains `include_smoke` param + `is_smoke` derived flag + `smoke_hidden_count`
- `outputs/static/app.js` — Pending tab "Show all" toggle + smoke chip rendering
- `outputs/static/style.css` — `.pending-filter-row` + `.pending-smoke-toggle` + `.cycle-smoke-tag` rules
- `outputs/static/index.html` — cache-bust bumps for style.css + app.js
- `tests/test_cortex_phase4_5_director_card.py` — 6 new tests + adapt model-name assertions
- `tests/test_dashboard_cortex_ratify.py` — 4 new tests
- `briefs/_reports/B1_cortex_director_card_v1_1_<YYYYMMDD>.md` — ship report

## Do NOT Touch

- `scripts/backfill_director_cards.py` — Director ratified NO backfill of the existing 15 cycles. Grandfather them. Script remains in repo for future use but DO NOT execute against prod in this brief.
- `orchestrator/cortex_runner.py` — Phase 4.5 invocation path is unchanged. Only the translator internals change.
- `orchestrator/gemini_client.py` — used as-is. No edits.
- Migration files / `applied_migrations.lock` — no schema changes in v1.1.
- `cortex_cycles` table — no new columns. `is_smoke` is derived per-query.

## Quality Checkpoints

1. `pytest tests/test_cortex_phase4_5_director_card.py tests/test_dashboard_cortex_ratify.py -v` literally green — paste exact output in ship report. "By inspection" rejected per Baker hard rule.
2. `python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase4_5_director_card.py', doraise=True); py_compile.compile('outputs/dashboard.py', doraise=True)"` clean.
3. `bash scripts/check_singletons.sh` clean (no new direct `SentinelStoreBack()` constructions).
4. Render deploy goes green post-merge; `https://baker-master.onrender.com/api/health` returns 200.
5. Manual prod smoke per §Fix-1 + §Fix-2 verification — paste DB query result + screenshot of toggle in ship report.
6. Logs: ZERO `[phase4_5]` fallback warnings on the smoke-cycle's healthy Gemini path in the first 5 cycles post-deploy. If fallback fires on every cycle, the swap is functionally broken — surface to AH1 via bus before claiming ship.

## Verification SQL

```sql
-- Confirm new cards are Gemini-stamped (run after first post-merge cycle):
SELECT
    cycle_id::text,
    payload->'_meta'->>'model'          AS model_used,
    payload->'_meta'->>'fallback_used'  AS fallback_used,
    (payload->'_meta'->>'card_gen_cost_eur')::float AS cost_eur,
    created_at
FROM cortex_phase_outputs
WHERE artifact_type = 'director_card'
  AND created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC
LIMIT 10;

-- Confirm smoke filter logic against current cycle inventory:
SELECT
    COUNT(*) FILTER (WHERE
            COALESCE(triggered_by, '') ILIKE '%smoke%'
         OR COALESCE(triggered_by, '') ILIKE '%health%'
         OR COALESCE(signal_text, '')  ILIKE '%smoke #%'
         OR COALESCE(signal_text, '')  ILIKE '%health check%'
         OR COALESCE(signal_text, '')  ILIKE '%heartbeat%'
    ) AS would_hide,
    COUNT(*) FILTER (WHERE NOT (
            COALESCE(triggered_by, '') ILIKE '%smoke%'
         OR COALESCE(triggered_by, '') ILIKE '%health%'
         OR COALESCE(signal_text, '')  ILIKE '%smoke #%'
         OR COALESCE(signal_text, '')  ILIKE '%health check%'
         OR COALESCE(signal_text, '')  ILIKE '%heartbeat%'
    )) AS would_show,
    COUNT(*) AS total_pending
FROM cortex_cycles
WHERE status = 'tier_b_pending';
```

## API / deprecation check
- **Gemini 2.5 Pro:** model name `gemini-2.5-pro`, current GA per Google AI Studio docs (verified 2026-05-20). Pricing $1.25 / $5.00 per M tokens. API key auth via `GEMINI_API_KEY`. No deprecation announced.
- **Claude Sonnet 4.6:** model name `claude-sonnet-4-6`, current per Anthropic API (verified 2026-05-20). Pricing $3.00 / $15.00 per M tokens. No deprecation.
- **Fallback note:** if either vendor announces deprecation, v1.2 brief swaps the deprecated tier. No code-side migration shim required at v1.1.

## Reporting (bus-post-on-ship rule)

After PR open: bus-post `lead` with topic `ship/cortex-director-card-v1-1` + PR URL. After merge: same recipient, topic `complete/cortex-director-card-v1-1-merged`. Mailbox COMPLETE flip in same turn as merge (per 2026-05-19 hygiene gap).

`dispatched_by: lead` — reply target for ship/merge bus-posts is the dispatching AH1-Terminal slug.
