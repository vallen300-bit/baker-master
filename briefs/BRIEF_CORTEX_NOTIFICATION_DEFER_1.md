# BRIEF: CORTEX_NOTIFICATION_DEFER_1 — Per-invoke + per-matter Slack DM cost-warn opt-out

## Context
When `/api/cortex/run` fires and the matter has ≥30 specialist invocations in the last 24h, `outputs/dashboard.py:4329-4345` posts a `⚠️ Cortex spend watch` Slack DM to Director (`DIRECTOR_DM_CHANNEL`). This is observability-only — the run still proceeds. Director's V7 directive (2026-04-30): allow opt-out so Cortex can run silently with the cost gate auto-approving in the background. Two opt-out surfaces:

1. **Per-invoke**: `defer_notification: true` on `CortexRunRequest` body — suppresses the Slack DM for THIS call only.
2. **Per-matter**: `notification_defer: true` in `cortex-config.md` frontmatter — suppresses the Slack DM for ALL cycles on this matter.

Default behavior unchanged. Opt-out is additive (either flag suppresses; both is fine). Cost-warn STILL emits at `logger.info` for observability — only the Slack DM is gated.

Wave 2 #3 per Director ratification 2026-04-30 ~05:35Z (demoted from #1 to #3 when F-2 Scan UI render took priority after the post-deploy smoke surfaced the gap).

## Estimated time: ~2.5h
## Complexity: Low
## Prerequisites:
- baker-vault PR #13 (`d815d24`) merged — provides Wave 2 matter configs as the default no-defer baseline (none of them set `notification_defer: true`)
- PR #88 (`7a36312`) + #90 (`4615b4d`) + #91 (`f66201a`) merged — Cortex manual invoke + Scan UI + hotfix all live; this brief sits on top

---

## Fix/Feature 1: Extend `CortexRunRequest` with `defer_notification` flag

### Problem
The Pydantic model at `outputs/dashboard.py:361-373` has no field to opt out of the cost-warn Slack DM at runtime. Director needs a per-invoke knob.

### Current State
Verified at `outputs/dashboard.py:361-373`:

```python
class CortexRunRequest(BaseModel):
    """CORTEX_MANUAL_INVOKE_1: Director-invoke a Cortex cycle with SSE streaming.

    Same field shape as CortexTriggerRequest — kept distinct so future
    streaming-only fields (poll_interval override, max_phases, etc.) can
    diverge without disturbing the sync trigger contract.
    """
    matter_slug: str = Field(..., min_length=1, max_length=64,
                             description="Matter slug (must have cortex-config.md in vault)")
    director_question: str = Field(..., min_length=10, max_length=4000,
                                   description="Director's question driving the cycle")
    triggered_by: str = Field(default="director_manual", min_length=1, max_length=64,
                              description="Trigger source label — director_manual or scan_intent")
```

### Implementation

Append the new field (with backward-compatible default `False`):

```python
class CortexRunRequest(BaseModel):
    """CORTEX_MANUAL_INVOKE_1: Director-invoke a Cortex cycle with SSE streaming.

    Same field shape as CortexTriggerRequest — kept distinct so future
    streaming-only fields (poll_interval override, max_phases, etc.) can
    diverge without disturbing the sync trigger contract.
    """
    matter_slug: str = Field(..., min_length=1, max_length=64,
                             description="Matter slug (must have cortex-config.md in vault)")
    director_question: str = Field(..., min_length=10, max_length=4000,
                                   description="Director's question driving the cycle")
    triggered_by: str = Field(default="director_manual", min_length=1, max_length=64,
                              description="Trigger source label — director_manual or scan_intent")
    defer_notification: bool = Field(
        default=False,
        description=(
            "CORTEX_NOTIFICATION_DEFER_1: when true, suppress the cost-warn "
            "Slack DM for THIS invocation. Cost-warn still logs to logger.info "
            "(observability preserved); only the Slack push is gated."
        ),
    )
```

### Key Constraints
- **Default `False`** — backward-compatible. Existing curl callers, the Scan-intent branch, etc. all keep firing the Slack DM at threshold.
- **Boolean only** — no truthy-string parsing, no `Optional[bool]`. Pydantic V2 strict-on-bool by default; tests will fail-loud on bad inputs.
- **No mutation of `triggered_by`** — defer is orthogonal to trigger source.

### Verification
```bash
# Existing curl still works (no flag → default False → Slack DM fires at threshold)
curl -s -H "X-Baker-Key: bakerbhavanga" -X POST -H "Content-Type: application/json" \
  -d '{"matter_slug":"hagenauer-rg7","director_question":"smoke","trigger_reason":"verification"}' \
  https://baker-master.onrender.com/api/cortex/run --max-time 60 -N | head -5

# New: pass defer_notification: true
curl -s -H "X-Baker-Key: bakerbhavanga" -X POST -H "Content-Type: application/json" \
  -d '{"matter_slug":"hagenauer-rg7","director_question":"silent smoke","trigger_reason":"verification","defer_notification":true}' \
  https://baker-master.onrender.com/api/cortex/run --max-time 60 -N | head -5
```

Expected: both succeed (200 SSE stream); the second produces no Slack DM regardless of specialist-count threshold state.

---

## Fix/Feature 2: Add `matter_notification_deferred()` helper to `cortex_pre_review_gate.py`

### Problem
No existing helper reads the `notification_defer` field from `cortex-config.md` frontmatter. We need a parallel of `_read_cost_estimate` that returns a bool.

### Current State
Verified at `triggers/cortex_pre_review_gate.py`:
- `matter_has_cortex_config` at line 65 (config-presence check)
- `_read_cost_estimate` at line 80 (line-based YAML-free frontmatter parse, returns float, has working error path)

The `_read_cost_estimate` pattern:
```python
def _read_cost_estimate(matter_slug: str) -> float:
    root = _vault_root()
    if not root:
        return DEFAULT_COST_ESTIMATE_DOLLARS
    cfg = root / "wiki" / "matters" / matter_slug / "cortex-config.md"
    if not cfg.is_file():
        return DEFAULT_COST_ESTIMATE_DOLLARS
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            return DEFAULT_COST_ESTIMATE_DOLLARS
        end = text.find("\n---", 3)
        if end < 0:
            return DEFAULT_COST_ESTIMATE_DOLLARS
        fm = text[3:end]
        for line in fm.splitlines():
            line = line.strip()
            if line.startswith("cost_estimate_dollars:"):
                val = line.split(":", 1)[1].strip()
                try:
                    return float(val)
                except ValueError:
                    return DEFAULT_COST_ESTIMATE_DOLLARS
        return DEFAULT_COST_ESTIMATE_DOLLARS
    except Exception as e:
        logger.error("read_cost_estimate failed matter=%s: %s", matter_slug, e)
        return DEFAULT_COST_ESTIMATE_DOLLARS
```

### Implementation

Add **immediately AFTER** `_read_cost_estimate` (around `triggers/cortex_pre_review_gate.py:112`):

```python
def matter_notification_deferred(matter_slug: str) -> bool:
    """CORTEX_NOTIFICATION_DEFER_1: True iff cortex-config.md frontmatter
    has ``notification_defer: true``.

    When True, suppress the cost-warn Slack DM for ALL Cortex cycles on
    this matter (per-matter opt-out). Logger.info still emits — only the
    Slack push is gated.

    Returns False on any of: vault unset, config missing, frontmatter
    malformed, field absent, value not truthy. Fail-closed: if we can't
    read the field cleanly, default to current behavior (DM fires).
    Mirrors ``_read_cost_estimate`` parsing pattern (no PyYAML dependency).
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
        text = cfg.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            return False
        end = text.find("\n---", 3)
        if end < 0:
            return False
        fm = text[3:end]
        for line in fm.splitlines():
            line = line.strip()
            if line.startswith("notification_defer:"):
                val = line.split(":", 1)[1].strip().lower()
                # Accept the YAML-truthy spellings; everything else (false,
                # no, off, blank) returns False. Mirror common YAML 1.1
                # behaviour without pulling in the library.
                return val in ("true", "yes", "on", "1")
        return False
    except Exception as e:
        logger.error("matter_notification_deferred failed matter=%s: %s", matter_slug, e)
        return False
```

### Key Constraints
- **Fail-closed**: any parse error / missing file / missing field returns `False` → DM fires (current behavior preserved).
- **No PyYAML import** — match existing `_read_cost_estimate` pattern exactly.
- **Truthy spellings**: accept `true / yes / on / 1` (case-insensitive). Mirror common YAML 1.1 booleans — don't try to be cleverer than `_read_cost_estimate`.
- **Path identical** to `_read_cost_estimate` (`<vault>/wiki/matters/<slug>/cortex-config.md`) — single source of truth.
- **Function signature**: `matter_notification_deferred(matter_slug: str) -> bool`. Grep callers won't find any yet — safe to add.

### Verification
After deploy + manual matter-config edit (in baker-vault, e.g. add `notification_defer: true` to `wiki/matters/hagenauer-rg7/cortex-config.md` on a test branch):

```python
# In Render shell or local pytest
from triggers.cortex_pre_review_gate import matter_notification_deferred
assert matter_notification_deferred("hagenauer-rg7") is True
assert matter_notification_deferred("oskolkov") is False  # not set on Wave 1 matters
assert matter_notification_deferred("not-a-matter") is False
assert matter_notification_deferred("") is False
```

---

## Fix/Feature 3: Wire the gates into the cost-warn block

### Problem
The cost-warn Slack post at `outputs/dashboard.py:4329-4345` is unconditional once the threshold is hit. Need to gate the `post_to_channel(...)` call on `req.defer_notification OR matter_notification_deferred(req.matter_slug)`.

### Current State
Verified at `outputs/dashboard.py:4327-4345`:

```python
    # Cost guardrail: warn-only Slack DM at threshold, run proceeds
    n_specialist = specialist_calls_today(req.matter_slug)
    if n_specialist >= COST_WARN_SPECIALIST_PER_DAY:
        try:
            from outputs.slack_notifier import post_to_channel
            from triggers.cortex_pre_review_gate import DIRECTOR_DM_CHANNEL
            post_to_channel(
                DIRECTOR_DM_CHANNEL,
                (
                    f"⚠️ Cortex spend watch: {req.matter_slug} has "
                    f"{n_specialist} specialist invocations in last 24h "
                    f"(warn threshold: {COST_WARN_SPECIALIST_PER_DAY}). "
                    "Run proceeding — observability ping only."
                ),
                unfurl_links=False,
                unfurl_media=False,
            )
        except Exception as e:
            logger.error("cortex_run cost-warn Slack post failed: %s", e)
```

### Implementation

Replace that block with:

```python
    # Cost guardrail: warn-only Slack DM at threshold, run proceeds.
    # CORTEX_NOTIFICATION_DEFER_1: per-invoke + per-matter opt-out.
    n_specialist = specialist_calls_today(req.matter_slug)
    if n_specialist >= COST_WARN_SPECIALIST_PER_DAY:
        # Always log for observability — separate from Slack push.
        logger.info(
            "cortex_run cost-warn matter=%s specialists=%d threshold=%d defer_invoke=%s defer_matter=%s",
            req.matter_slug,
            n_specialist,
            COST_WARN_SPECIALIST_PER_DAY,
            req.defer_notification,
            "?",  # populated below after the matter-deferred check
        )
        from triggers.cortex_pre_review_gate import (
            DIRECTOR_DM_CHANNEL,
            matter_notification_deferred,
        )
        defer_matter = matter_notification_deferred(req.matter_slug)
        if not (req.defer_notification or defer_matter):
            try:
                from outputs.slack_notifier import post_to_channel
                post_to_channel(
                    DIRECTOR_DM_CHANNEL,
                    (
                        f"⚠️ Cortex spend watch: {req.matter_slug} has "
                        f"{n_specialist} specialist invocations in last 24h "
                        f"(warn threshold: {COST_WARN_SPECIALIST_PER_DAY}). "
                        "Run proceeding — observability ping only."
                    ),
                    unfurl_links=False,
                    unfurl_media=False,
                )
            except Exception as e:
                logger.error("cortex_run cost-warn Slack post failed: %s", e)
        else:
            logger.info(
                "cortex_run cost-warn Slack DM suppressed matter=%s defer_invoke=%s defer_matter=%s",
                req.matter_slug,
                req.defer_notification,
                defer_matter,
            )
```

### Key Constraints
- **`logger.info` ALWAYS fires** when threshold hit — observability preserved regardless of Slack gate.
- **`defer_matter` computed AFTER** the per-invoke check so we don't read the vault when per-invoke already covers (small optimisation, but in any case `matter_notification_deferred` is sub-millisecond when the file exists).
- **Suppression message at `logger.info`** when DM is gated — leaves a clear trail for `actions_log.md` review.
- **Imports** stay localised inside the `if` block — match existing pattern; don't lift to module top.
- **No state writes** — pure observability gating. No `baker_actions` row needed for the suppress event (the `logger.info` line is the audit trail).

### Verification

Live curl smoke after deploy + a matter at threshold (or stub):

```bash
# Verify SUPPRESSION via per-invoke flag
curl -s -H "X-Baker-Key: bakerbhavanga" -X POST -H "Content-Type: application/json" \
  -d '{"matter_slug":"hagenauer-rg7","director_question":"silent smoke","trigger_reason":"defer-test","defer_notification":true}' \
  https://baker-master.onrender.com/api/cortex/run --max-time 60 -N | head -5

# Render logs (during/after) should show:
#   "cortex_run cost-warn matter=hagenauer-rg7 specialists=NN ... defer_invoke=True ..."
#   "cortex_run cost-warn Slack DM suppressed matter=hagenauer-rg7 defer_invoke=True defer_matter=False"
# AND NO Slack DM in DIRECTOR_DM_CHANNEL.
```

---

## Fix/Feature 4: Tests — 4 cases on the gate matrix + 2 on the helper

### New test cases in `tests/test_cortex_run_endpoint.py`

Append four parameterised cases to the existing endpoint suite (mirror its existing `monkeypatch` + stub-store fixture pattern). Each test stubs `specialist_calls_today` to return ≥`COST_WARN_SPECIALIST_PER_DAY` so the cost-warn branch always fires; the matrix covers the 4 (defer_invoke × defer_matter) combinations:

```python
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.parametrize(
    "defer_invoke,defer_matter,expect_slack_post",
    [
        (False, False, True),   # default — DM fires
        (True,  False, False),  # per-invoke suppresses
        (False, True,  False),  # per-matter suppresses
        (True,  True,  False),  # both suppress (no double-fire)
    ],
)
def test_cortex_run_cost_warn_defer_matrix(
    monkeypatch, client, defer_invoke, defer_matter, expect_slack_post
):
    """CORTEX_NOTIFICATION_DEFER_1: cost-warn Slack DM gated on
    (per-invoke OR per-matter) defer flags. Logger always fires."""
    from outputs import cortex_run_stream as crs
    from outputs import dashboard as dash
    from triggers import cortex_pre_review_gate as gate

    # Force threshold breach so the cost-warn branch fires
    monkeypatch.setattr(crs, "specialist_calls_today", lambda _s: 9999)
    monkeypatch.setattr(crs, "runs_in_last_hour", lambda _s: 0)
    monkeypatch.setattr(crs, "RUN_RATE_LIMIT_PER_HOUR", 5)
    monkeypatch.setattr(crs, "COST_WARN_SPECIALIST_PER_DAY", 30)
    monkeypatch.setattr(gate, "matter_has_cortex_config", lambda _s: True)
    monkeypatch.setattr(gate, "matter_notification_deferred", lambda _s: defer_matter)

    # Stub the SSE generator so the test exits cleanly without running a real cycle
    async def _fake_stream(*, matter_slug, director_question, triggered_by):
        import json
        yield f"data: {json.dumps({'type':'started','matter_slug':matter_slug,'ts':0})}\n\n"
        yield f"data: {json.dumps({'type':'terminal','status':'completed','cycle_id':'00000000-0000-0000-0000-000000000099','current_phase':'archive','cost_dollars':0.0,'cost_tokens':0,'ts':0})}\n\n"
    monkeypatch.setattr(crs, "stream_cycle_events", _fake_stream)

    captured = {"called": False}
    def _fake_post(*args, **kwargs):
        captured["called"] = True
    monkeypatch.setattr("outputs.slack_notifier.post_to_channel", _fake_post)

    body = {
        "matter_slug": "hagenauer-rg7",
        "director_question": "defer-matrix smoke",
        "trigger_reason": "test",
    }
    if defer_invoke:
        body["defer_notification"] = True

    resp = client.post(
        "/api/cortex/run",
        json=body,
        headers={"X-Baker-Key": "bakerbhavanga"},
    )
    assert resp.status_code == 200, resp.text
    # Drain SSE so the StreamingResponse generator runs to completion
    _ = resp.read()
    assert captured["called"] is expect_slack_post, (
        f"defer_invoke={defer_invoke} defer_matter={defer_matter}: "
        f"expected slack_post called={expect_slack_post}, got {captured['called']}"
    )
```

### New helper-level cases in `tests/test_cortex_pre_review_gate.py`

```python
def test_matter_notification_deferred_true(monkeypatch, tmp_path):
    """notification_defer: true in frontmatter → returns True."""
    from triggers import cortex_pre_review_gate as gate
    matter = tmp_path / "wiki" / "matters" / "test-defer"
    matter.mkdir(parents=True)
    (matter / "cortex-config.md").write_text(
        "---\nmatter_slug: test-defer\nnotification_defer: true\n---\n# body\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    assert gate.matter_notification_deferred("test-defer") is True


def test_matter_notification_deferred_false_when_field_absent(monkeypatch, tmp_path):
    """field absent → returns False (default behavior preserved)."""
    from triggers import cortex_pre_review_gate as gate
    matter = tmp_path / "wiki" / "matters" / "test-no-defer"
    matter.mkdir(parents=True)
    (matter / "cortex-config.md").write_text(
        "---\nmatter_slug: test-no-defer\n---\n# body\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    assert gate.matter_notification_deferred("test-no-defer") is False


def test_matter_notification_deferred_false_when_config_missing(monkeypatch, tmp_path):
    """no cortex-config.md → returns False (fail-closed)."""
    from triggers import cortex_pre_review_gate as gate
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    assert gate.matter_notification_deferred("ghost-matter") is False


def test_matter_notification_deferred_truthy_spellings(monkeypatch, tmp_path):
    """yes/on/1 also accepted as truthy."""
    from triggers import cortex_pre_review_gate as gate
    for spelling in ("yes", "on", "1", "True", "TRUE"):
        matter = tmp_path / "wiki" / "matters" / f"m-{spelling.lower()}"
        matter.mkdir(parents=True, exist_ok=True)
        (matter / "cortex-config.md").write_text(
            f"---\nmatter_slug: m-{spelling.lower()}\nnotification_defer: {spelling}\n---\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
        assert gate.matter_notification_deferred(f"m-{spelling.lower()}") is True, spelling
```

### Ship gate

```bash
pytest tests/test_cortex_run_endpoint.py tests/test_cortex_pre_review_gate.py tests/test_cortex_run_stream.py tests/test_scan_cortex_intent.py -v
```

Must produce literal green output — no "pass by inspection" (Lesson #48). Paste the literal pytest tail in the ship report.

---

## Files Modified
- `outputs/dashboard.py` — extend `CortexRunRequest` (1 new field) + replace cost-warn block (~20 lines)
- `triggers/cortex_pre_review_gate.py` — add `matter_notification_deferred()` helper (~30 lines, mirrors `_read_cost_estimate`)
- `tests/test_cortex_run_endpoint.py` — new parametrized test (4 matrix cases)
- `tests/test_cortex_pre_review_gate.py` — 4 new helper-level tests (true / field absent / config missing / truthy spellings)

## Do NOT Touch
- `outputs/cortex_run_stream.py` — pure SSE / cost-counting helper, no notification surface
- `outputs/slack_notifier.py` — `post_to_channel` already correct; gating is upstream
- `outputs/dashboard.py:7854-7886` (Scan `cortex_run_action` branch) — Scan invocation goes through the streaming endpoint and inherits the per-invoke flag from the body if Director ever wires it through Scan UI; no edit needed in this brief
- `outputs/dashboard.py:4220-4269` (`trigger_cortex_cycle` sync endpoint) — no Slack DM there; out of scope
- `triggers/cortex_pre_review_gate.py:_read_cost_estimate` and signing/verification machinery — independent concerns
- `wiki/matters/*/cortex-config.md` files — Director adds `notification_defer: true` per-matter via gold-comment workflow when wanted; this brief ships the read-path only, no vault writes

## Quality Checkpoints

1. `pytest tests/test_cortex_run_endpoint.py tests/test_cortex_pre_review_gate.py tests/test_cortex_run_stream.py tests/test_scan_cortex_intent.py` literal green
2. `bash scripts/check_singletons.sh` clean (no new constructor calls)
3. `python -c "from outputs.dashboard import app; print(any(getattr(r, 'name', '') == 'cortex_run_stream' for r in app.routes))"` returns the same as before merge (no route regressions)
4. Curl smoke A: `defer_notification: true` on a matter at threshold → no Slack DM; Render logs show `cost-warn Slack DM suppressed`
5. Curl smoke B: no `defer_notification` field → Slack DM fires (regression check)
6. Manual matter-frontmatter edit: add `notification_defer: true` to a test matter's `cortex-config.md` on a vault branch (do NOT merge during this brief), confirm `matter_notification_deferred()` returns True via a one-shot `python -c` on Render shell
7. JS console clean (no frontend changes — should be zero impact)
8. **Logger trail** — every threshold hit produces `cortex_run cost-warn matter=...` regardless of suppression. `actions_log.md` retroactive review possible.
9. No new env vars required. No DB migrations. No schema changes.
10. Backward compat: existing curl callers / Scan-intent path / future signal-driven cycles all keep firing the DM at threshold.

## API version / deprecation / fallback notes (Code Brief Standards 1-3)

- **API version:** internal endpoints only. Pydantic V2 (already in `requirements.txt`); `Field(default=False)` is V2-correct.
- **Deprecation check:** N/A — internal Baker FastAPI endpoint.
- **Fallback:** if vault unavailable on Render (env var unset), `matter_notification_deferred()` returns `False` → DM fires (current behavior). Fail-closed preserves observability.

## Migration-vs-bootstrap DDL check (Code Brief Standards #4)
- **No DDL.** No new column, no migration. Pure read-path through the existing `cortex-config.md` frontmatter file.

## Singleton pattern check (Code Brief Standards #8)
- New helper `matter_notification_deferred()` does NOT touch `SentinelStoreBack` / `SentinelRetriever`. No singleton risk. `scripts/check_singletons.sh` clean.

## File:line citation verification (Code Brief Standards #7)
- `outputs/dashboard.py:361-373` — verified (`CortexRunRequest` Pydantic model)
- `outputs/dashboard.py:4275-4310` — verified (`@app.post /api/cortex/run` endpoint definition)
- `outputs/dashboard.py:4327-4345` — verified (cost-warn Slack post block)
- `triggers/cortex_pre_review_gate.py:65-77` — verified (`matter_has_cortex_config`)
- `triggers/cortex_pre_review_gate.py:80-111` — verified (`_read_cost_estimate` template for the new helper)
- `triggers/cortex_pre_review_gate.py:DIRECTOR_DM_CHANNEL` constant at L37 — verified (canonical DM channel ID)
- `outputs/slack_notifier.py::post_to_channel` — present + signature compatible (already used by current code path)

## Cost impact (Step 4 review)
- **Lower** API cost when defer is set — Slack post API call is suppressed; cost-warn observability is logger.info only (free).
- **No new** LLM calls. No new DB writes (logger.info only). Net cost: very slightly lower than today.

## Render restart survival
- All state in env / vault file. No in-memory drift. Frontmatter parse is per-call (no caching) — safe across restarts. Per-invoke flag is in request body (transient, no persistence concern).

## Blast radius
- **Worst case if implemented wrong:** Slack DMs are silently suppressed when they should fire (false-True from `matter_notification_deferred`). Mitigation: fail-closed default + logger.info trail makes a regression visible in 60 seconds of log review.
- **Rollback path:** revert the dashboard.py block to the unconditional post; the new helper is dead code if not called. Minimal blast surface.
