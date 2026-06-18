# BRIEF: CORTEX_LITE_REBASE_1 — Rebase Cortex into a Matter Attention Engine (SIMPLIFIED v2)

**Author:** codex-arch (v1), revised to v2 by AH1-lead after deputy-codex reductionist review (bus #3199/#3200).
**Builder:** b1.
**Reviewer:** AH1 + independent code-review lane. Run `/security-review` — touches Cortex activation, cost gates, Director-facing action flow.
**Trigger class:** HIGH — autonomous/runtime behavior + Director-facing dashboard surface.

## Context
Director ratified the Cortex Lite direction 2026-06-17. Cortex drifted from "one useful matter attention loop" into a broad agent-runtime platform: 26 matters carry a `cortex-config.md`, and live DB shows 21 approved / 9 failed / 6 rejected cycles plus 2 `oskolkov` cycles stuck `tier_b_pending` since 2026-05-20. This brief freezes expansion and rebases Cortex into a smaller shape that produces a small number of high-quality Director decisions per week.

### Surface contract (ui-surface-prebrief skill, V1)
1. **User action:** Director taps "useful / not useful" on a pending Cortex proposal card (and reads a `stale` marker on aged ones).
2. **Backend route:** `POST /cortex/cycle/{cycle_id}/action` at `baker-master/outputs/dashboard.py:15872` — signature: `async def cortex_cycle_action(cycle_id: str, request: Request)`. Pending list: `POST /api/cortex/cycles/pending` at `outputs/dashboard.py:6940` → `list_cortex_cycles_pending(...)`.
3. **Endpoint contract:** action endpoint auth `Depends(verify_api_key)`; JSON body `{"action": <str>, ...}`; whitelist at `dashboard.py:15892` (`if action not in ("approve","edit","refresh","reject")`). v2 adds `"useful"` to that whitelist + body `{cycle_id, useful: bool, note?: str}`. No new auth, no signed token.
4. **State location:** Postgres `cortex_cycles` (+ `cortex_phase_outputs` / `feedback_ledger` for usefulness capture) in `baker-master`.
5. **UI repo (= state repo):** `baker-master` — surface: main dashboard **Cortex → Pending** tab (the web ratify panel, PR #223). NOT brisen-lab, NOT Slack.
6. **Director surface preference:** web dashboard — ratified 2026-05-19 (Director explicitly rejected Slack as the ratify surface; PR #223 built the web panel). No new surface question.
7. **Gate-1+2 reviewer instruction:** see `## Gate-1 + Gate-2 reviewer instructions` below.

## Revision note (why v2 is smaller)
v1 had 6 features + 6 env vars. deputy-codex (bus #3200) + AH1 collapsed to **4 work packages + 2 env vars** without losing the skeleton. Changes from v1:
- **Specialist-cap feature DROPPED for v1** (was v1 Feature 4). `CAP5_LIMIT=5` already preserves the ratified max; allowlist + gated pipeline clamp volume/cost enough for the proof. Defer the cap until 14-day data shows runaway fanout. Do NOT add `triggered_by` plumbing into Phase 2 context in this PR.
- **Env surface cut 6 → 2:** keep `CORTEX_LITE_ENABLED` + `CORTEX_LITE_MATTERS`. Hard-code Lite direct-fire=false and stale=72h as constants. Drop `CORTEX_LITE_DIRECT_FIRE_ALLOWED`, `CORTEX_LITE_MANUAL_SPECIALIST_CAP`, `CORTEX_LITE_SIGNAL_SPECIALIST_CAP`, `CORTEX_LITE_STALE_PENDING_HOURS`.
- **Emergency rollback** = `CORTEX_LITE_ENABLED=false` (single flag), not a per-feature env.
- **Proof rewritten** to Director's amendment: no manual cycle-running. Real inbound signals generate pending cards over 14 days; Director only taps **useful y/n** on cards he already sees.

## Skeleton intent (MUST survive — do not regress)
> Cortex Lite = a matter attention engine that produces a **small number of high-quality Director decisions per week**, with expansion frozen, direct-fire fallback removed, stale decision-debt visible, and a cheap falsifiable 14-day proof (continue only if ≥3 of 5 cycles are clearly useful).

## Estimated time: ~4-5h (down from 6-8h)
## Complexity: Low-Medium
## Prerequisites
- No open Cortex PR in flight: `gh pr list --state open --limit 20`.
- Verify real schema before editing SQL (checked 2026-06-17):
  - `cortex_cycles`: `cycle_id`, `matter_slug`, `triggered_by`, `trigger_signal_id`, `started_at`, `completed_at`, `last_loaded_at`, `current_phase`, `status`, `proposal_id`, `director_action`, `feedback_ledger_id`, `cost_tokens`, `cost_dollars`, `created_at`, `updated_at`, `last_nudge_at`.
  - `cortex_phase_outputs`: `output_id`, `cycle_id`, `phase`, `phase_order`, `artifact_type`, `payload`, `citations`, `created_at`.
- Use `/opt/homebrew/bin/python3.12` locally. Do not use bare `python3` in ship evidence.
- Verified-live for this brief (AH1, 2026-06-17): both allowlist slugs have `wiki/matters/<slug>/cortex-config.md` (`oskolkov` + `hagenauer-rg7`); 26 matters carry a cortex-config (allowlist is load-bearing, clamps 26 → 2). `triggered_by` literals in live code = `signal`, `scan_intent`, `director_gate_approve`, plus `/api/cortex/run` Field default `director_manual` (dashboard.py:1243,1258).

## Harness V2
- **Context Contract:** Repo `baker-master` (cwd `~/bm-b1`). Touch only the 11 files in "Files Modified". State = Postgres `cortex_cycles` / `cortex_phase_outputs`; vault read-only at `BAKER_VAULT_PATH`. Policy module is the single source of Lite truth; do not re-parse Lite envs elsewhere. No schema migration. No prod data mutation in the PR.
- **Task class:** Feature + runtime-policy clamp + Director-facing dashboard surface (HIGH trigger class).
- **Done rubric (answer each in the ship report, not "tests passed"):**
  1. Lite OFF (default) → existing behavior byte-identical; full test suite green.
  2. Lite ON → non-allowlisted matter with a config is blocked at `matter_has_cortex_config`.
  3. Lite ON + gate secret missing OR gate exception → `maybe_run_cycle` NOT called (two live-green tests pasted).
  4. Pending API returns `age_hours` + `is_stale_pending`; UI shows `stale` chip + 👍/👎 buttons (screenshot/desc).
  5. `useful` action persists with NO schema change; unknown action still `invalid_action`.
  6. All listed pytest run literally green (output pasted); compile clean; source guards grep-pass.
- **Done-state class:** production-facing → emit `POST_DEPLOY_AC_VERDICT v1` on the bus after AH1 deploy + env-flip (the operating-reset section), NOT at merge.
- **Gate plan:** G0 self-review (b1) → G1/G2 independent code-review lane + `/security-review` (HIGH class, mandatory) → G3 codex cross-vendor gate (fleet-touching runtime behavior) → AH1 merge → AH1 deploy + env-flip + `POST_DEPLOY_AC_VERDICT`.

## Gate-1 + Gate-2 reviewer instructions
> Reviewers MUST load `POST /cortex/cycle/{cycle_id}/action` with the exact body the frontend will send (`{"action":"useful","cycle_id":"<real-id>","useful":true}`) against a live or local instance and confirm a non-error response + persisted state. Code-shape review (XSS-safe, syntactically valid HTML/JS) is necessary but NOT sufficient — the `/api/cortex/gate/decide` `cycle_id`-vs-`signal_id` scar (2026-05-19) is exactly this class. Also confirm the two WP-C direct-fire-suppression tests run GREEN live (not "by inspection").

---

## WP-A: Single Cortex Lite policy module (2 envs, constants for the rest)

### Problem
Lite behavior must be enforced in two places (matter eligibility, direct-fire fallback). Hard-coding env parsing in each file drifts. One small module owns the policy.

### Engineering Craft Gates
- Diagnose: applies. Feedback loop = unit tests + live read-only SQL counts. Hypothesis: broad matter eligibility + direct-fire fallback let Cortex expand past the Director-useful loop.
- Prototype: N/A — policy clamp, no new interaction model.
- TDD/verification: applies. Tests written first for the policy module (below).

### Implementation
Add `orchestrator/cortex_lite_policy.py`:

```python
"""Cortex Lite policy helpers.

CORTEX_LITE_REBASE_1: centralizes the temporary 14-day Cortex Lite operating
shape. Lite mode preserves Director-invoked + gated-signal Cortex cycles but
prevents broad matter fanout and runaway direct-fire fallback while usefulness
is being proven. Specialist-cap clamp intentionally deferred (full Cortex
CAP5_LIMIT preserved); only allowlist + direct-fire-off are in this v1.
"""
from __future__ import annotations

import os

TRUE_VALUES = {"1", "true", "yes", "on"}
DEFAULT_LITE_MATTERS = ("oskolkov", "hagenauer-rg7")

# Hard-coded Lite constants (not env-tunable in v1 — keep surface minimal).
LITE_DIRECT_FIRE_ALLOWED = False
LITE_STALE_PENDING_HOURS = 72.0


def _truthy_env(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in TRUE_VALUES


def lite_enabled() -> bool:
    """True when Cortex Lite restrictions are active.

    Default false so deploy is behavior-preserving until AH1 explicitly flips
    the env flag after Director ratification.
    """
    return _truthy_env("CORTEX_LITE_ENABLED", "false")


def lite_matters() -> set[str]:
    """Matter allowlist used only when Lite is enabled."""
    raw = os.environ.get("CORTEX_LITE_MATTERS", "").strip()
    if not raw:
        return set(DEFAULT_LITE_MATTERS)
    return {part.strip() for part in raw.split(",") if part.strip()}


def matter_allowed(matter_slug: str) -> bool:
    """True when a matter may run Cortex under the current policy."""
    if not matter_slug:
        return False
    if not lite_enabled():
        return True
    return matter_slug in lite_matters()


def direct_fire_allowed() -> bool:
    """Whether the signal pipeline may bypass the pre-review gate and run a cycle.

    In Lite mode direct-fire is hard-off (constant). Emergency rollback to the
    legacy fallback is CORTEX_LITE_ENABLED=false, not a per-feature env.
    """
    if not lite_enabled():
        return True
    return LITE_DIRECT_FIRE_ALLOWED


def stale_pending_hours() -> float:
    """Age (hours) after which tier_b_pending cycles are flagged stale in UI/API."""
    return LITE_STALE_PENDING_HOURS
```

Add `tests/test_cortex_lite_policy.py`:

```python
from orchestrator import cortex_lite_policy as p


def test_lite_disabled_preserves_existing_behavior(monkeypatch):
    monkeypatch.delenv("CORTEX_LITE_ENABLED", raising=False)
    assert p.lite_enabled() is False
    assert p.matter_allowed("movie") is True
    assert p.direct_fire_allowed() is True


def test_lite_allowlist_defaults(monkeypatch):
    monkeypatch.setenv("CORTEX_LITE_ENABLED", "true")
    monkeypatch.delenv("CORTEX_LITE_MATTERS", raising=False)
    assert p.matter_allowed("oskolkov") is True
    assert p.matter_allowed("hagenauer-rg7") is True
    assert p.matter_allowed("movie") is False


def test_lite_allowlist_env_override(monkeypatch):
    monkeypatch.setenv("CORTEX_LITE_ENABLED", "true")
    monkeypatch.setenv("CORTEX_LITE_MATTERS", "oskolkov,mo-vie-am")
    assert p.matter_allowed("oskolkov") is True
    assert p.matter_allowed("mo-vie-am") is True
    assert p.matter_allowed("hagenauer-rg7") is False


def test_lite_direct_fire_hard_off(monkeypatch):
    monkeypatch.setenv("CORTEX_LITE_ENABLED", "true")
    assert p.direct_fire_allowed() is False


def test_stale_threshold_constant():
    assert p.stale_pending_hours() == 72.0
```

### Key Constraints
- Do NOT set `CORTEX_LITE_ENABLED=true` in code. Default must be behavior-preserving until AH1 flips Render env.
- Do NOT remove historical Cortex docs / roadmap files.
- Do NOT change DB schema.

### Verification
```bash
/opt/homebrew/bin/python3.12 -m pytest tests/test_cortex_lite_policy.py -v
```

---

## WP-B: Gate Cortex-eligible matters through the Lite allowlist

### Problem
The current matter gate treats any matter with `cortex-config.md` as eligible (26 today). Lite proof wants max 2.

### Current State
`triggers/cortex_pre_review_gate.py:matter_has_cortex_config` checks only config-file existence (≈lines 65-77). `outputs/dashboard.py:/api/cortex/run` and Scan cortex-run routing both call it — the right shared choke point. **Re-confirm the exact line range before editing — do not trust the ≈ ref.**

### Engineering Craft Gates
- Diagnose: applies. Pass/fail = unit test: a matter with config but not in the allowlist returns false.
- Prototype: N/A.
- TDD/verification: applies. Add the test before modifying the helper.

### Implementation
Modify `triggers/cortex_pre_review_gate.py:matter_has_cortex_config`:

```python
def matter_has_cortex_config(matter_slug: str) -> bool:
    """True iff <vault>/wiki/matters/<matter_slug>/cortex-config.md exists
    AND current Cortex policy allows this matter.

    In Cortex Lite mode, config existence is necessary but not sufficient:
    CORTEX_LITE_MATTERS is the temporary matter allowlist.
    """
    if not matter_slug:
        return False
    root = _vault_root()
    if not root:
        return False
    cfg = root / "wiki" / "matters" / matter_slug / "cortex-config.md"
    if not cfg.is_file():
        return False
    try:
        from orchestrator.cortex_lite_policy import matter_allowed
        if not matter_allowed(matter_slug):
            logger.info(
                "cortex lite skipped matter=%s not in CORTEX_LITE_MATTERS",
                matter_slug,
            )
            return False
    except Exception as e:
        logger.error("cortex lite matter policy failed matter=%s: %s", matter_slug, e)
        return False
    return True
```

Extend `tests/test_cortex_pre_review_gate.py`:

```python
def test_matter_has_cortex_config_lite_allowlist_blocks_nonlisted(monkeypatch, tmp_path):
    """Lite mode: a matter with cortex-config.md is still blocked unless allowlisted."""
    for slug in ("oskolkov", "movie"):
        matter = tmp_path / "wiki" / "matters" / slug
        matter.mkdir(parents=True)
        (matter / "cortex-config.md").write_text(
            f"---\nmatter_slug: {slug}\n---\n", encoding="utf-8",
        )
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("CORTEX_LITE_ENABLED", "true")
    monkeypatch.setenv("CORTEX_LITE_MATTERS", "oskolkov")
    import importlib
    import triggers.cortex_pre_review_gate as g
    importlib.reload(g)
    assert g.matter_has_cortex_config("oskolkov") is True
    assert g.matter_has_cortex_config("movie") is False
```

### Key Constraints
- Existing tests with Lite disabled must pass unchanged.
- Keep `matter_has_cortex_config` as the single surface used by `/api/cortex/run`, Scan routing, and pre-review gate.

### Verification
```bash
/opt/homebrew/bin/python3.12 -m pytest tests/test_cortex_pre_review_gate.py tests/test_cortex_run_endpoint.py tests/test_scan_cortex_intent.py -v
```

---

## WP-C: In Lite mode, never fall through from failed gate to direct-fire

### Problem
`triggers/cortex_pipeline.py:maybe_trigger_cortex(...)` can direct-fire a cycle when gate intent is on but `CORTEX_GATE_SECRET` is missing, or when gate dispatch errors. Fine for full Cortex; wrong for Lite — if the cheap gate fails, Cortex should skip rather than spend or create pending cards without Director intent.

### Current State (verify line refs before edit)
`maybe_trigger_cortex(...)` (≈triggers/cortex_pipeline.py:81-106): posts `post_gate(...)` when `_gate_enabled()`; falls through to direct-fire when `_secret() is None`; falls through on broad gate exception; direct-fires via `maybe_run_cycle(... triggered_by="signal" ...)`.

### Engineering Craft Gates
- Diagnose: applies. Symptom = auto path can bypass Director intent if gate is misconfigured.
- Prototype: N/A.
- TDD/verification: applies. Test that Lite + secret-missing OR gate-exception does NOT call `maybe_run_cycle`.

### Implementation
Add a lazy import near the top of `maybe_trigger_cortex` after the `matter_slug` check:

```python
    from orchestrator.cortex_lite_policy import direct_fire_allowed
```

Replace the `_secret() is None` branch:

```python
            if _secret() is None:
                if not direct_fire_allowed():
                    logger.warning(
                        "cortex lite direct-fire suppressed: gate secret missing "
                        "signal_id=%s matter=%s", signal_id, matter_slug,
                    )
                    return
                pass  # legacy direct-fire only outside Lite mode
```

Replace the broad gate-exception fallthrough:

```python
        except Exception as e:  # noqa: BLE001
            logger.error("gate dispatch failed signal_id=%s matter=%s: %s",
                         signal_id, matter_slug, e)
            if not direct_fire_allowed():
                logger.warning(
                    "cortex lite direct-fire suppressed after gate exception "
                    "signal_id=%s matter=%s", signal_id, matter_slug,
                )
                return
            # fall through to legacy path only outside Lite mode
```

Add a final guard immediately before the legacy direct-fire `try:`:

```python
    if not direct_fire_allowed():
        logger.warning("cortex lite direct-fire suppressed signal_id=%s matter=%s",
                       signal_id, matter_slug)
        return
```

Extend `tests/test_alerts_to_signal_cortex_dispatch.py`:

```python
def test_maybe_trigger_lite_secret_missing_does_not_direct_fire(monkeypatch):
    from triggers import cortex_pipeline
    calls = []
    async def _fake_cycle(**kwargs):
        calls.append(kwargs)
    monkeypatch.setenv("CORTEX_LIVE_PIPELINE", "true")
    monkeypatch.setenv("CORTEX_GATE_ENABLED", "true")
    monkeypatch.setenv("CORTEX_LITE_ENABLED", "true")
    monkeypatch.delenv("CORTEX_GATE_SECRET", raising=False)
    monkeypatch.setattr("orchestrator.cortex_runner.maybe_run_cycle", _fake_cycle)
    cortex_pipeline.maybe_dispatch(signal_id=42, matter_slug="oskolkov")
    assert calls == []


def test_maybe_trigger_lite_gate_exception_does_not_direct_fire(monkeypatch):
    from triggers import cortex_pipeline
    calls = []
    async def _fake_cycle(**kwargs):
        calls.append(kwargs)
    def _boom(**kwargs):
        raise RuntimeError("slack down")
    monkeypatch.setenv("CORTEX_PIPELINE_ENABLED", "true")
    monkeypatch.setenv("CORTEX_LIVE_PIPELINE", "true")
    monkeypatch.setenv("CORTEX_GATE_ENABLED", "true")
    monkeypatch.setenv("CORTEX_LITE_ENABLED", "true")
    monkeypatch.setenv("CORTEX_GATE_SECRET", "test-secret-32-characters-long-XX")
    monkeypatch.setattr("triggers.cortex_pre_review_gate.post_gate", _boom)
    monkeypatch.setattr("orchestrator.cortex_runner.maybe_run_cycle", _fake_cycle)
    cortex_pipeline.maybe_dispatch(signal_id=43, matter_slug="oskolkov")
    assert calls == []
```

If the harness cannot monkeypatch the lazy import exactly this way, keep the same behavior assertions but patch the module surfaces actually used in `maybe_trigger_cortex`. Do NOT weaken the assertion: Lite mode must not direct-fire. **Builder MUST show live green pytest output for these two tests — not "by inspection" (Lesson #8).**

### Key Constraints
- Outside Lite mode, current fallback behavior unchanged unless AH1 separately ratifies removal.
- Do not break upstream signal finalization: `maybe_dispatch` must still never raise.

### Verification
```bash
/opt/homebrew/bin/python3.12 -m pytest tests/test_alerts_to_signal_cortex_dispatch.py tests/test_step6_cortex_dispatch.py -v
```

---

## WP-D: Surface stale + capture "useful" on the pending card (minimal)

### Problem
Two `oskolkov` cycles are `tier_b_pending` since 2026-05-20. Pending tab shows age but doesn't classify stale debt. And the 14-day proof needs a one-tap Director usefulness verdict on cards he already sees.

### Current State
`outputs/dashboard.py:list_cortex_cycles_pending(...)` (route `POST /api/cortex/cycles/pending`, def at 6944) returns `age_minutes`, `is_smoke`, `proposal_preview`, `director_card`. `outputs/static/app.js` (≈10735-10848) renders matter, smoke chip, age, preview. Action endpoint `cortex_cycle_action` (`POST /cortex/cycle/{cycle_id}/action`, def 15878, whitelist 15892) currently accepts only approve/edit/refresh/reject. **Re-confirm all line ranges before editing.**

### Engineering Craft Gates
- Diagnose: applies. Symptom = stale cycles remain open for weeks; no usefulness capture surface.
- Prototype: N/A — one status chip + two buttons.
- TDD/verification: applies. API response-shape test + source guards + new-action test.

### Implementation — stale chip (observability)
In `list_cortex_cycles_pending(...)`, before SQL:

```python
        from orchestrator.cortex_lite_policy import stale_pending_hours
        stale_hours = stale_pending_hours()
```

Add to the `base` CTE:

```sql
                    EXTRACT(EPOCH FROM (NOW() - c.started_at))/60   AS age_minutes,
                    EXTRACT(EPOCH FROM (NOW() - c.started_at))/3600 AS age_hours,
                    (EXTRACT(EPOCH FROM (NOW() - c.started_at))/3600 >= %(stale_hours)s) AS is_stale_pending,
```

Add `"stale_hours": stale_hours` to execute params. Add to the serialized cycle:

```python
                "age_hours": float(r.get("age_hours") or 0.0),
                "is_stale_pending": bool(r.get("is_stale_pending")),
```

`app.js` pending row:

```javascript
        var staleChip = c.is_stale_pending
            ? '<span class="cycle-stale-tag">stale</span>' : '';
```

append `staleChip` next to the existing `smokeChip` in the matter span. Add `.cycle-stale-tag` style to `style.css` (compact chip, mirror `.cycle-smoke-tag`, distinct color). Bump cache-busts in `outputs/static/index.html` — **read the current `style.css?v=` and `app.js?v=` integers first, then +1 each; do NOT hard-code a guessed value.**

### Implementation — useful y/n (proof capture, NO schema change)
- Add `"useful"` to the action whitelist at `dashboard.py:15892` (alongside approve/edit/refresh/reject) + a handler. Body `{cycle_id, useful: true|false, note?: str}`.
- Persist into existing JSON, NOT a new column: write to the cycle's `feedback_ledger` JSON (via the existing feedback-ledger writer) OR a `cortex_phase_outputs` row with `artifact_type="director_usefulness"` — whichever the builder confirms is the live, already-wired store. Choose ONE; document which in the ship report.
- `app.js`: add two small buttons (👍 useful / 👎 not useful) on the pending card that POST `/cortex/cycle/{cycle_id}/action` with `{"action":"useful",...}` and reflect the captured state. No modal.
- All DB writes wrapped in try/except with `conn.rollback()` on except (hard rule).

Tests — extend `tests/test_dashboard_cortex_ratify.py`:
- Add `age_hours` + `is_stale_pending` to the `_pending_row` fixture; assert both in the response shape.
- Source guard: `is_stale_pending` appears in `outputs/dashboard.py`; `cycle-stale-tag` appears in `app.js` + `style.css`.
- New action test: POST `useful` persists and the endpoint accepts it; POST with an unknown action is still rejected (`invalid_action`).

### Key Constraints
- Do NOT auto-dismiss/auto-reject stale cycles. Stale = observability only.
- Do NOT auto-grade usefulness — the verdict is Director's tap. (Voids the proof otherwise.)
- Director/AH1 closes stale cycles via the existing dashboard action path, not raw SQL.
- Keep smoke filter behavior unchanged.

### Verification
```bash
/opt/homebrew/bin/python3.12 -m pytest tests/test_dashboard_cortex_ratify.py -v
```
Manual browser check after deploy: Cortex → Pending shows `stale` on cycles >72h; 👍/👎 buttons POST and persist (reload-stable); `Show all` still reveals smoke; no overlapping text desktop + mobile.

---

## Operating reset (AH1-owned, NOT in this PR — post-merge)
B-code does NOT mutate production data or flip prod env in this PR. After merge + deploy, AH1 performs:
1. **Pre-flight (load-bearing):** verify `CORTEX_GATE_SECRET` is set on Render. With direct-fire hard-off, a missing secret = zero real-signal cycles fire → silent dead proof. Confirm before flipping Lite on.
2. Set Render env for the proof window:
   ```text
   CORTEX_LITE_ENABLED=true
   CORTEX_LITE_MATTERS=oskolkov,hagenauer-rg7
   CORTEX_PIPELINE_ENABLED=true
   CORTEX_GATE_ENABLED=true
   ```
   Then verify ALL four persisted via Render API `GET /v1/services/{id}/env-vars` (env-set-but-missing is a known lesson).
3. Resolve the two stale `oskolkov` pending cycles via the existing dashboard Reject path (or leave visible with `stale` chip until Director decides). No raw DB writes.
4. **Proof = real signals, not manual runs.** Over 14 days, genuine inbound signals on the 2 matters generate Tier-B pending cards. Director's only act = tap 👍/👎 on cards he already sees. Continue Cortex Lite only if ≥3 of 5 rated cycles are clearly useful; else stop expansion and redesign.

## Files Modified
- `orchestrator/cortex_lite_policy.py` — NEW (2-env policy + constants).
- `triggers/cortex_pre_review_gate.py` — Lite matter allowlist via shared gate.
- `triggers/cortex_pipeline.py` — suppress direct-fire fallback in Lite mode.
- `outputs/dashboard.py` — pending API `age_hours` + `is_stale_pending`; `useful` action.
- `outputs/static/app.js` — stale chip + 👍/👎 useful buttons.
- `outputs/static/style.css` — stale chip style.
- `outputs/static/index.html` — cache-bust bump (read current, +1).
- `tests/test_cortex_lite_policy.py` — NEW.
- `tests/test_cortex_pre_review_gate.py` — allowlist test.
- `tests/test_alerts_to_signal_cortex_dispatch.py` — direct-fire suppression tests.
- `tests/test_dashboard_cortex_ratify.py` — stale + useful tests.

## Do NOT Touch
- `cortex_cycles` / `cortex_phase_outputs` schema — no migration.
- `orchestrator/cortex_phase3_reasoner.py` `CAP5_LIMIT=5` — specialist cap deferred; full Cortex max preserved. NO `triggered_by` plumbing into Phase 2 this PR.
- Historical architecture docs under `docs-site/architecture/` — preserve as history.
- `baker-vault/_ops/processes/cortex3t-roadmap*.md` — do not rewrite roadmap in a code PR.
- Existing Phase 5 approve/edit/refresh/reject handlers — extend the action whitelist with `useful`; do not refactor Phase 5.
- Game-theory capability implementation — untouched in v2 (cap feature dropped).

## Quality Checkpoints
1. Lite disabled preserves current behavior exactly.
2. Lite enabled blocks non-allowlisted matters even when `cortex-config.md` exists.
3. Lite enabled never direct-fires after gate failure / secret-missing (live green tests).
4. Manual `/api/cortex/run` still works for allowlisted matters.
5. Pending API includes `age_hours` + `is_stale_pending`.
6. Pending UI shows `stale` chip + 👍/👎 buttons; no overlap desktop/mobile.
7. `useful` action persists with NO schema change; unknown actions still rejected.
8. Smoke filter unchanged.
9. No unbounded SQL added (every new SELECT keeps a LIMIT where applicable).
10. Every `except` around DB writes calls `conn.rollback()`.
11. `index.html` cache-bust bumped for both changed assets.
12. Ship report includes literal test output, not "by inspection".

## Test Plan
```bash
/opt/homebrew/bin/python3.12 -m pytest \
  tests/test_cortex_lite_policy.py \
  tests/test_cortex_pre_review_gate.py \
  tests/test_alerts_to_signal_cortex_dispatch.py \
  tests/test_cortex_run_endpoint.py \
  tests/test_scan_cortex_intent.py \
  tests/test_dashboard_cortex_ratify.py \
  -v
```
Compile:
```bash
/opt/homebrew/bin/python3.12 -m py_compile \
  orchestrator/cortex_lite_policy.py \
  triggers/cortex_pre_review_gate.py \
  triggers/cortex_pipeline.py \
  outputs/dashboard.py
```
Source guards:
```bash
grep -n "cycle-stale-tag" outputs/static/app.js outputs/static/style.css
grep -n "is_stale_pending" outputs/dashboard.py
grep -nE "app.js\?v=|style.css\?v=" outputs/static/index.html
```

## Verification SQL
```sql
-- Pending debt after deploy
SELECT cycle_id, matter_slug, status, current_phase, started_at, cost_tokens, cost_dollars
FROM cortex_cycles
WHERE status = 'tier_b_pending'
ORDER BY started_at DESC
LIMIT 10;
```
```sql
-- Trigger mix during Lite proof
SELECT triggered_by, status, count(*) AS n
FROM cortex_cycles
WHERE started_at > NOW() - INTERVAL '14 days'
GROUP BY triggered_by, status
ORDER BY n DESC
LIMIT 20;
```

## Stop Criteria
- Any test fails.
- Lite disabled changes existing behavior.
- Lite enabled still direct-fires after gate failure.
- Non-allowlisted matter can start via `/api/cortex/run`.
- UI assets ship without cache-bust.
- B-code proposes deleting historical Cortex docs, adding a schema migration, raw-updating production `cortex_cycles`, or touching `CAP5_LIMIT`.

## Co-Authored-By
```text
Co-authored-by: codex-arch <codex-arch@brisengroup.com>
Co-authored-by: deputy-codex <deputy-codex@brisengroup.com>
```
