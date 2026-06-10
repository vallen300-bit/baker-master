# BRIEF: FABLE_5_MIGRATION_1 — Fleet migration Opus 4.8 → Claude Fable 5

## Context
Director directive 2026-06-10: switch all agents running on Opus 4.8 to Anthropic's
new **Claude Fable 5** (model ID `claude-fable-5`, GA 2026-06-09; Mythos-class;
$10/$50 per MTok — **2× Opus 4.8's $5/$25**).

The runtime switch is the **`KBL_ANTHROPIC_MODEL` Render env var** — all 15 model
call sites read it (`os.environ.get("KBL_ANTHROPIC_MODEL", "claude-opus-4-8")`), so
flipping that one var moves the entire Baker production pipeline. The hardcoded
`claude-opus-4-8` literals are env-absent fallbacks and stay valid, so they are
**deliberately out of scope** (see Do-NOT-Touch).

**This brief covers ONLY the code that BREAKS or mis-costs when the active model is
not an Opus ID.** Three pricing surfaces fail in three different ways. This code MUST
merge + deploy to prod BEFORE the env var is flipped — otherwise `kbl/cost.py`
raises `ValueError` on the first priced Fable call and crashes the cost-logging path.

### Sequencing (CRITICAL — code first, env second; Director-ratified ALL-AT-ONCE 2026-06-10)
1. **(code, this brief)** Merge + deploy the 3 pricing fixes below.
2. **(env, same maintenance window)** Apply the Render env vars in §Env Changes in ONE
   merge-mode batch: model switch + Fable prices + raised cost tiers.
3. **(lead lane)** Global Claude Code harness pin `~/.claude/settings.json` →
   `claude-fable-5` (~23 fleet agents).
4. **(ops)** Update the weekly Edge-Scout remote trigger (currently opus-4-7) → `claude-fable-5`.
5. **Post-deploy AC** (see §Post-Deploy AC) → emit `POST_DEPLOY_AC_VERDICT v1` to bus.
6. **Rollback:** revert `KBL_ANTHROPIC_MODEL`→`claude-opus-4-8` + cost tiers to 30/60/80/100.
   Code is forward-compatible (prices BOTH families) — no code rollback needed.

**Director ratifications 2026-06-10:** (1) 2× cost accepted; (2) NO 24h burn-in — go
all-at-once; (3) raise cost alarm tiers (§Env Changes). Burn-in `KBL_STEP5_MODEL` path dropped.

## Estimated time: ~1.5h
## Complexity: Low (string + pricing edits; no API-signature change — Fable uses the identical Anthropic Messages API)
## Prerequisites: none (ANTHROPIC_API_KEY already set on Render)

---

## Harness V2 — Context Contract + Done Rubric + Gate Plan

**Task class:** Small fix — production (cost-tracking code + Render env + financial governance).
**Required final state (done rubric):** Merged + Deployed + **post-deploy AC passed** + writeback resolved.
**Owner / route:** lead (AH1) implements + verifies per Director directive 2026-06-10; may sub-route to a builder.
**`dispatched_by`:** deputy (AH2). Worker replies to `deputy`; lead owns merge/deploy.

**Context Contract (what the worker has, no round-trips needed):**
- Exact files + line anchors + copy-pasteable snippets: all 3 fixes below (verified against live code 2026-06-10).
- Model ID `claude-fable-5`; price $10/$50 per MTok (Anthropic GA 2026-06-09).
- The runtime switch is the env var, not the code literals (see Do-NOT-Touch rationale).
- Env-var set MUST use merge mode (`safe_env_put` / MCP merge) — never raw array PUT (catastrophic-wipe lesson 2026-05-17).

**Gate plan:**
- **G0 (Codex cross-vendor pre-review):** required — financial cost-cap logic; cheap to run.
- **G1 (AH static read + acceptance):** lead static-reviews the diff before merge.
- **G2 (`/security-review`):** required — change is Render-env-touching + alters the daily
  cost hard-stop (financial guardrail). Not skippable as "docs-only".
- **G3 (deep gates):** N/A — no architecture or shared-contract change (pricing-table edits only).

**STOP — do not call DONE until:** prod deploy live AND post-deploy AC (below) passes AND
`POST_DEPLOY_AC_VERDICT v1` posted to bus. "Tests pass / merged / deployed" alone ≠ done.

---

## Fix 1: `kbl/cost.py` — add Fable to `_model_key()` + `PRICING` (PREVENTS HARD CRASH)

### Problem
`_model_key()` (line 53) matches only `opus`/`sonnet`/`haiku`, then checks `full_id in
PRICING`, then **`raise ValueError`**. `claude-fable-5` matches none → every call to
`estimate_cost()` / cost logging that passes the Fable model raises. This is the
crash-critical surface.

### Current State
`kbl/cost.py:34-50` (PRICING dict) and `kbl/cost.py:53-71` (`_model_key`). Pricing keys
are family aliases; prices are env-overridable.

### Implementation
**1a.** In `kbl/cost.py`, add a Fable entry to the `PRICING` dict (after the
`claude-haiku-4` block, line 47):

```python
    "claude-fable-5": {
        # Fable 5 (Mythos-class) GA 2026-06-09: $10/$50 per MTok. FABLE_5_MIGRATION_1.
        "input": float(os.getenv("PRICE_FABLE5_IN", "10.00")),
        "output": float(os.getenv("PRICE_FABLE5_OUT", "50.00")),
    },
```

**1b.** In `_model_key()`, add a `fable` branch BEFORE the final `raise` (insert after
the `haiku` branch at line 65):

```python
    if "fable" in full_id:
        return "claude-fable-5"
```

### Key Constraints
- Keep the opus/sonnet/haiku branches and the final `raise ValueError` unchanged — the
  raise-on-unknown contract (R1.B6) is load-bearing for cap enforcement.
- Family-key style: Fable currently has one version, so the exact ID `claude-fable-5`
  doubles as the family key (matches how `claude-opus-4` aliases 4-7/4-8).

### Verification
```python
from kbl.cost import _model_key, PRICING
assert _model_key("claude-fable-5") == "claude-fable-5"
assert PRICING["claude-fable-5"]["input"] == 10.0
assert PRICING["claude-fable-5"]["output"] == 50.0
# regression: opus still works
assert _model_key("claude-opus-4-8") == "claude-opus-4"
```

---

## Fix 2: `kbl/anthropic_client.py` — Fable-aware price constants (PREVENTS SILENT 2× UNDER-COUNT)

### Problem
`_compute_cost_usd()` (line 142) prices off module constants `_PRICE_OPUS_INPUT_PER_M`
($5) / `_PRICE_OPUS_OUTPUT_PER_M` ($25), hardcoded to the Opus env-var defaults. When
the active model is Fable (real $10/$50), this logs cost at **half** the true rate — no
crash, but the daily cap under-counts 2× and silently runs past budget.

### Current State
`kbl/anthropic_client.py:57` (`_DEFAULT_MODEL`) and `:68-69` (price constants), consumed
at `:157-160` in `_compute_cost_usd`.

### Implementation
Replace lines 68-69 with a model-family-aware resolution. **Constant names are
intentionally kept** (`_PRICE_OPUS_INPUT_PER_M` / `_PRICE_OPUS_OUTPUT_PER_M`) so the
consumers at lines 157-160 need NO edit:

```python
# FABLE_5_MIGRATION_1 (2026-06-10): price by the active model family.
# Fable 5 = $10/$50 per MTok (GA 2026-06-09); Opus 4.x = $5/$25 (legacy fallback).
# Constant names kept to avoid churn in _compute_cost_usd (lines 157-160).
_FABLE_ACTIVE = "fable" in _DEFAULT_MODEL
_PRICE_OPUS_INPUT_PER_M = (
    float(os.getenv("PRICE_FABLE5_IN", "10.00")) if _FABLE_ACTIVE
    else float(os.getenv("PRICE_OPUS4_IN", "5.00"))
)
_PRICE_OPUS_OUTPUT_PER_M = (
    float(os.getenv("PRICE_FABLE5_OUT", "50.00")) if _FABLE_ACTIVE
    else float(os.getenv("PRICE_OPUS4_OUT", "25.00"))
)
```

### Key Constraints
- Do NOT touch the cache multipliers (`_PRICE_OPUS_CACHE_WRITE_MUL = 2.00`,
  `_PRICE_OPUS_CACHE_READ_MUL = 0.10`, lines 74-75) — Anthropic prompt-caching ratios
  (2× write / 0.1× read) are model-agnostic and apply to Fable identically.
- `_FABLE_ACTIVE` resolves at module import from `_DEFAULT_MODEL`, which reads
  `KBL_ANTHROPIC_MODEL` — set at Render boot, so this is correct for the deployed model.
- Edge case to ACCEPT (do not over-engineer): if an operator sets `KBL_STEP5_MODEL` to a
  DIFFERENT family than `KBL_ANTHROPIC_MODEL`, the Step-5 override would be priced by the
  pipeline default's family. We run one model fleet-wide, so this mixed state is not a
  production scenario — note it in a comment, do not build per-call family detection.

### Verification
```python
import importlib, os
os.environ["KBL_ANTHROPIC_MODEL"] = "claude-fable-5"
import kbl.anthropic_client as ac; importlib.reload(ac)
assert ac._PRICE_OPUS_INPUT_PER_M == 10.0
assert ac._PRICE_OPUS_OUTPUT_PER_M == 50.0
os.environ["KBL_ANTHROPIC_MODEL"] = "claude-opus-4-8"; importlib.reload(ac)
assert ac._PRICE_OPUS_INPUT_PER_M == 5.0   # regression
```

---

## Fix 3: `orchestrator/cost_monitor.py` — add Fable to `MODEL_COSTS` (PREVENTS ~1.5× OVER-COUNT)

### Problem
`MODEL_COSTS` (line 26) is keyed by exact model ID. `claude-fable-5` is absent → lookups
fall to `DEFAULT_COSTS = {"input": 15.00, "output": 75.00}` (line 51) → over-counts Fable
spend ~1.5×. Not a crash (safe default exists), but corrupts the cost dashboard + EUR tiers.

### Current State
`orchestrator/cost_monitor.py:26-50` (`MODEL_COSTS`), `:51` (`DEFAULT_COSTS`).

### Implementation
Add a Fable entry to `MODEL_COSTS` immediately after the `claude-opus-4-6` line (line 31):

```python
    "claude-fable-5": {"input": 10.00, "output": 50.00},  # FABLE_5_MIGRATION_1, GA 2026-06-09
```

### Key Constraints
- Do NOT remove or alter the `claude-opus-4-6/4-7/4-8` rows — historical `api_cost_log`
  rows reference them; they must keep pricing old data correctly (Lesson: legacy rows).
- Leave `DEFAULT_COSTS` unchanged.

### Verification
```python
from orchestrator.cost_monitor import MODEL_COSTS
assert MODEL_COSTS["claude-fable-5"] == {"input": 10.00, "output": 50.00}
```

---

## Files Modified
- `kbl/cost.py` — Fable PRICING entry + `_model_key` fable branch (crash fix)
- `kbl/anthropic_client.py` — Fable-aware price constants (under-count fix)
- `orchestrator/cost_monitor.py` — Fable MODEL_COSTS entry (over-count fix)
- `tests/` — add Fable pricing assertions (see Quality Checkpoints)

## Do NOT Touch
- The 15 `KBL_ANTHROPIC_MODEL` call sites with `"claude-opus-4-8"` fallback defaults
  (config/settings.py:67,519; kbl/anthropic_client.py:57; kbl/steps/step5_opus.py:876,899;
  tools/ingest/classifier.py:92; tools/document_pipeline.py:34; tools/ingest/extractors.py:309;
  claimsmax/recharge_report/generator.py:18; orchestrator/cortex_phase3_{synthesizer,invoker,reasoner}.py;
  orchestrator/capability_runner.py:329; orchestrator/memory_consolidator.py:51;
  orchestrator/extraction_engine.py:317) — **the env var is the runtime switch; the opus-4-8
  fallback is a SAFE default if env is ever unset.** Changing 15 literals adds churn and risk
  (cf. Lesson #126 GEMINI-MIGRATION batch = 19 bugs) for zero runtime benefit.
- `_PRICE_OPUS_CACHE_*` multipliers — model-agnostic.
- `circuit_health_model` in `kbl/retry.py:105` (`claude-haiku-4-5`) — health probe stays on cheap Haiku.
- `tools/document_pipeline.py:32` `_HAIKU_MODEL = "gemini-2.5-flash"` — classification stays on Gemini.
- Clerk/Qwen3 config — not Claude, out of scope.

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('kbl/cost.py', doraise=True)"` (repeat for all 3 files).
2. Add a test (e.g. `tests/test_fable5_pricing.py`) asserting all three Verification blocks above; run `pytest tests/test_fable5_pricing.py -v` — literal green, not "by inspection".
3. Run the existing cost-suite regression: `pytest tests/ -k "cost" -v` — confirm opus paths still pass.
4. **Exercise the real flow (Lesson #8 — compile-clean ≠ done):** with `KBL_ANTHROPIC_MODEL=claude-fable-5` set in the shell, call `kbl.cost.estimate_cost("claude-fable-5", "test prompt", 100)` and confirm it returns a non-zero float WITHOUT raising — this is the exact path that crashes today.
5. Confirm no other `_model_key`/pricing consumer raises on `claude-fable-5` (grep `_model_key(` + `MODEL_COSTS[` + `PRICING[`).

## Verification SQL
```sql
-- After env flip + first live Fable cycle: confirm cost rows log at the $10/$50 rate,
-- not $5/$25 (under) or $15/$75 (over). Spot-check newest rows.
SELECT model, input_tokens, output_tokens, cost_usd,
       ROUND((cost_usd / NULLIF(input_tokens + output_tokens, 0)) * 1000000, 2) AS blended_per_m
FROM kbl_cost_ledger
WHERE model ILIKE '%fable%'
ORDER BY created_at DESC
LIMIT 10;
```

## Env Changes (lead/ops — merge-mode ONLY, never raw array PUT)
Apply on Render `baker-master` in one batch, AFTER the code deploy is live:

| Env var | New value | Was | Why |
|---|---|---|---|
| `KBL_ANTHROPIC_MODEL` | `claude-fable-5` | `claude-opus-4-8` | **THE switch** — moves all 15 call sites |
| `PRICE_FABLE5_IN` | `10.00` | (unset) | belt-and-braces; code default already 10.00 |
| `PRICE_FABLE5_OUT` | `50.00` | (unset) | belt-and-braces; code default already 50.00 |
| `BAKER_COST_TIER_INFO_EUR` | `60` | `30` | Director-ratified raise (2× price headroom) |
| `BAKER_COST_TIER_WARN_EUR` | `120` | `60` | Director-ratified raise |
| `BAKER_COST_TIER_CRITICAL_EUR` | `160` | `80` | Director-ratified raise |
| `BAKER_COST_HARD_STOP_EUR` | `200` | `100` | Director-ratified raise |

Use `from tools.render_env_guard import safe_env_put` or MCP merge mode. **Verify all 7 keys
landed** via Render API `GET /v1/services/{id}/env-vars` (Lesson: env set but missing on deploy).
`settings.json` global pin + Edge-Scout trigger are separate ops steps (sequence 3-4).

## Post-Deploy AC (run AFTER env flip; gates the DONE call — emit `POST_DEPLOY_AC_VERDICT v1`)
1. Trigger one real priced call path (e.g. a Scan / Step-5 cycle). Confirm **no `ValueError`**
   from `kbl.cost._model_key` (the exact crash this brief prevents).
2. `kbl_cost_ledger` newest `model ILIKE '%fable%'` rows price at blended ~$10/$50 — NOT
   $5/$25 (under) and NOT $15/$75 (over). Use the Verification SQL above.
3. Cost dashboard / `cost_monitor` shows Fable rows costed at $10/$50, tiers now 60/120/160/200.
4. Spot-confirm an agent response actually came from `claude-fable-5` (response `model` field).
5. Post `POST_DEPLOY_AC_VERDICT v1` to bus → `deputy` (and lead's own log) per `post-deploy-ac-bus-gate`.

## Risks
- **Cost governance:** at 2× per-token price the old EUR tiers (30/60/80/100) would trip at
  ~half the token volume. **Director-ratified raise to 60/120/160/200** folded into §Env
  Changes — keeps the same effective token headroom at the new price.
- **<5% Opus fallback:** Anthropic routes <5% of Fable sessions (high-risk topics) back to
  Opus 4.8 server-side — transparent to us, no action; cost for those is billed at Opus rate.
- **Mixed-family pricing** (Step-5 override ≠ pipeline model) accepted as non-production (Fix 2 note).
