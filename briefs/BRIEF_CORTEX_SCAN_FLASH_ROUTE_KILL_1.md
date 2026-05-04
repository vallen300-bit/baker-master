---
type: brief
title: BRIEF_CORTEX_SCAN_FLASH_ROUTE_KILL_1 — Scan→Cortex Flash-route kill switch
status: dispatched
authored_by: AH1-App (architect-reviewed 2026-05-04 — 1C / 3I addressed; ship as A-only-with-fixes)
dispatched_to: B1
dispatched_by: AH1-Terminal
dispatched_at: 2026-05-04
tier: B
---

# BRIEF_CORTEX_SCAN_FLASH_ROUTE_KILL_1

## Problem

`orchestrator/action_handler.py::classify_intent` calls Flash to classify ambiguous Scan input. Flash can return `cortex_run_action` for non-explicit phrasings (e.g. "analyze the oskolkov situation broadly") — bypassing `CORTEX_GATE_ENABLED` which protects only the signal-side / pipeline path. This is a cost-safety gap: Scan→Cortex via Flash classification ignores the gate.

This brief adds a **kill switch** env var `CORTEX_SCAN_FLASH_ROUTE_DISABLED`. When `true`, the Flash branch is skipped entirely (skip-entirely is cheaper than call-then-downgrade per architect) and `classify_intent` returns `{"type": "question"}`. Explicit Director regex commands (`run cortex on <matter>`) still route via the regex fast-path which short-circuits BEFORE the env gate — never blocked.

## Constraints

- **Skip-entirely, not call-then-downgrade.** No Flash invocation when kill switch is active — saves the Flash call cost itself.
- **Regex fast-paths preserved.** `_quick_cortex_run_detect`, `_quick_capability_detect`, `_quick_email_detect` all execute BEFORE the env gate; never affected.
- **Kill switch OFF by default.** Unset env var = current Flash behavior.
- **WhatsApp blast radius intentional.** `triggers/waha_webhook.py` calls `scan_chat → classify_intent`, so Flash-classified Cortex routes from WhatsApp will also be blocked. Director's explicit "run cortex on X" via WhatsApp still works via regex path. Architect confirmed acceptable.

## Files modified

1. **`orchestrator/action_handler.py`** — insert ~10-line gate block after line 680 (`return quick` at end of email regex fast-path), before line 682 (`try:` for Flash call). Verified line refs by Read on 2026-05-04.
   - **`import os` is NOT currently at top of file** (verified 2026-05-04). Add it.
   - Logger is configured (line 712 `logger.warning` confirms it).
   - Gate block reads env var, log breadcrumb `CORTEX_SCAN_FLASH_ROUTE_SUPPRESSED` if active, return `{"type": "question"}`.

2. **`tests/test_scan_cortex_intent.py`** — append Tests 9-11 per acceptance criteria below.

## Acceptance criteria

| #  | Test | Expected |
|----|------|----------|
| A1 | Test 9 (kill-active): env var `true` + ambiguous question → returns `{"type": "question"}`, Flash NOT called | PASS |
| A2 | Test 10 (kill-default-inactive): env var unset + Flash mocked to return `cortex_run_action` → propagates through | PASS |
| A3 | Test 11 (regex-bypass-kill): env var `true` + "Run cortex on oskolkov" → still returns `cortex_run_action` via regex | PASS |
| A4 | All existing Tests 1-8 in `tests/test_scan_cortex_intent.py` still PASS | green |
| A5 | Full pytest suite in baker-master passes literally (no "by inspection") | green |
| A6 | `/security-review` clean | PASS |
| A7 | Post-deploy: `GET /v1/services/{id}/env-vars` confirms `CORTEX_SCAN_FLASH_ROUTE_DISABLED=true` present | confirmed |
| A8 | Post-deploy smoke: ambiguous Scan question logs `CORTEX_SCAN_FLASH_ROUTE_SUPPRESSED` + returns text response (not Cortex SSE stream) | log line + text response |

A1-A6 are B1's responsibility. A7-A8 are AH1-Terminal post-merge (NOT B1).

## Test code (paste verbatim into tests/test_scan_cortex_intent.py)

```python
# ---------------------------------------------------------------------------
# Test 9 — CORTEX_SCAN_FLASH_ROUTE_DISABLED suppresses Flash branch
# ---------------------------------------------------------------------------

def test_classify_intent_flash_route_kill_active(monkeypatch):
    """When CORTEX_SCAN_FLASH_ROUTE_DISABLED=true, classify_intent must NOT
    invoke Flash and must return type=question even if Flash WOULD have
    classified the input as cortex_run_action. Closes the cost-safety gap
    where Scan→Cortex bypasses CORTEX_GATE_ENABLED. Anchor: BRIEF_CORTEX_
    SCAN_FLASH_ROUTE_KILL_1, architect-reviewed 2026-05-04."""
    from orchestrator import action_handler as ah

    monkeypatch.setenv("CORTEX_SCAN_FLASH_ROUTE_DISABLED", "true")

    # Ambiguous question that would NOT match the regex fast-path. If the
    # kill switch is wired correctly, call_flash must NOT be invoked at all
    # (skip-entirely is cheaper than call-then-downgrade per architect).
    with patch("orchestrator.gemini_client.call_flash") as mock_llm:
        out = ah.classify_intent("analyze the oskolkov situation broadly")

    assert out == {"type": "question"}
    mock_llm.assert_not_called()


def test_classify_intent_flash_route_kill_inactive_default(monkeypatch):
    """When CORTEX_SCAN_FLASH_ROUTE_DISABLED is unset (default), Flash branch
    runs as before — verify the kill switch is OFF by default. Mocks Flash to
    return cortex_run_action; assert it propagates through unchanged."""
    from orchestrator import action_handler as ah

    monkeypatch.delenv("CORTEX_SCAN_FLASH_ROUTE_DISABLED", raising=False)

    with patch("orchestrator.gemini_client.call_flash") as mock_llm:
        # Mock Flash response shape: GeminiResponse with .text + .usage attrs
        mock_resp = type(
            "FakeResp",
            (),
            {
                "text": '{"type": "cortex_run_action", "matter_slug": "oskolkov", "question": "x"}',
                "usage": type("U", (), {"input_tokens": 10, "output_tokens": 5})(),
            },
        )()
        mock_llm.return_value = mock_resp
        out = ah.classify_intent("analyze the oskolkov situation broadly")

    assert out["type"] == "cortex_run_action"
    assert out["matter_slug"] == "oskolkov"
    mock_llm.assert_called_once()


def test_classify_intent_regex_path_unaffected_by_kill(monkeypatch):
    """Even with CORTEX_SCAN_FLASH_ROUTE_DISABLED=true, explicit "run cortex
    on <matter>" regex commands MUST still route to cortex_run_action. The
    regex fast-path short-circuits BEFORE the env gate. Director's explicit
    invocations are never blocked."""
    from orchestrator import action_handler as ah

    monkeypatch.setenv("CORTEX_SCAN_FLASH_ROUTE_DISABLED", "true")

    with patch("orchestrator.gemini_client.call_flash") as mock_llm:
        out = ah.classify_intent("Run cortex on oskolkov — quick smoke")

    assert out["type"] == "cortex_run_action"
    assert out["matter_slug"] == "oskolkov"
    mock_llm.assert_not_called()
```

## Quality checkpoints (B1 must satisfy)

1. Verify `import os` already present at top of `orchestrator/action_handler.py` before assuming. If missing, add. **(verified 2026-05-04: NOT present — must add.)**
2. Verify `logger` is already configured before assuming. **(verified: yes, see `logger.warning` line 712.)**
3. Run literal `pytest tests/test_scan_cortex_intent.py -v` — paste output in ship report. No "by inspection".
4. Run full pytest suite to verify no incidental break elsewhere — paste output in ship report.
5. `/security-review` against the diff. Surface findings.

## Do NOT touch

- `orchestrator/action_handler.py::_quick_cortex_run_detect` — explicit Director regex commands stay untouched.
- `orchestrator/action_handler.py::_quick_capability_detect`, `_quick_email_detect` — other regex fast-paths preserved.
- `triggers/cortex_pipeline.py` — `_live_pipeline_enabled`, `_pipeline_dispatch_enabled`, `_gate_enabled` all stay (they protect signal-side path; this brief protects Scan-side path).
- `triggers/cortex_pre_review_gate.py` — Slack-DM approval gate stays.
- `outputs/dashboard.py::scan_chat`, `/api/cortex/run`, `/api/cortex/trigger` — endpoints unchanged.
- `outputs/cortex_run_stream.py` — never reached when `classify_intent` returns `question`.
- `triggers/waha_webhook.py` — intentional included blast radius (see Constraints).

## Out of scope

- `BRIEF_CORTEX_TWOSTAGE_PREVIEW_1` — full Free-Preview-to-Tap-to-Upgrade pattern (separate brief, queued).
- Master `CORTEX_AUTO_TRIGGER_KILL` env var (architect dropped — over-engineering on already-safe defaults).
- Pinning `CORTEX_PIPELINE_ENABLED=false` / `CORTEX_LIVE_PIPELINE=false` explicitly on Render (architect dropped — false impression they were unsafe).
- Code change to `triggers/waha_webhook.py` — intentional included blast radius via shared `classify_intent`.
- UI surface change in Scan / dashboard — out of scope.

## Verification SQL

N/A — no DB schema changes. Verification is via env-var presence + log breadcrumb + test suite.

## Lane

- AH1-App authored (architect-reviewed 2026-05-04: 1C / 3I addressed; ship as A-only-with-fixes)
- AH1-Terminal commits brief + dispatches via `briefs/_tasks/CODE_1_PENDING.md`
- B1 builds + opens PR
- `/security-review` mandatory (Tier-B per SKILL.md)
- AH1-Terminal merges on green CI + clean security-review
- AH1-Terminal sets Render env var post-merge + verifies deploy + smoke tests:
  - Use `mcp__render__update_environment_variables` (MCP merge mode — never raw PUT per `.claude/rules/python-backend.md`)
  - Trigger deploy (`mcp__render__create_*` deploy or POST `/v1/services/{id}/deploys` `{"clearCache": "do_not_clear"}`) — Lesson #39: PUT does NOT auto-restart
  - Verify env var present post-deploy
  - Smoke test: ambiguous Scan question → log line `CORTEX_SCAN_FLASH_ROUTE_SUPPRESSED` fires + response is text not SSE Cortex stream
