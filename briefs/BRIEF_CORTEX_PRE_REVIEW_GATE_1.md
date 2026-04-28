# BRIEF: CORTEX_PRE_REVIEW_GATE_1 — URL-based pre-cycle approval gate

## Context

Cortex V1 LIVE on AO matter. First real cycle ran end-to-end tonight at $4.00 / 246K tokens / 290s. Output was substantive (citing real WhatsApp 2026-04-23 + 2026-04-27, EUR 3M penalty, 7-point Constantinos delivery). Director: `It will be triggered only by the questions where A/O is mentioned.` followed by `Is it possible, in order to economize the cost, that I'll get a message via Slack giving me an option to order the review by Cortex or not? If I choose 'order the review', then we spend $4.?` → picked **Option A — URL-based gate**.

## Estimated time: ~3-4h
## Complexity: Medium
## Trigger class: HIGH

This PR ships:
- New external HTTP endpoint with token-based auth (no X-Baker-Key — must be tap-from-Slack-DM friendly)
- New Slack DM behavior on every Cortex auto-dispatch trigger
- Async background task to fire `maybe_run_cycle` after click

→ B1 situational review REQUIRED per RA-24 trigger (external API + new auth surface). Builder ≠ B1.

**Build assignment:** B2. **Review assignment:** B1 (formal) + AI Head A (/security-review + structural).

## Behavior change

### Before (current LIVE state)

```
inbound email/WA → classify → matter_slug=oskolkov → alerts_to_signal INSERT
  → _dispatch_cortex_for_inserted → maybe_dispatch → maybe_trigger_cortex
  → maybe_run_cycle()  [$4 spend, 4-5min wall]  → proposal_card → Slack DM with 4 buttons
```

### After (with gate)

```
inbound email/WA → classify → matter_slug=oskolkov → alerts_to_signal INSERT
  → _dispatch_cortex_for_inserted → maybe_dispatch → maybe_trigger_cortex
  → cortex_pre_review_gate.post_gate(signal_id, matter_slug)
      → cheap Slack DM: "📨 New AO signal — review with Cortex (~$4)?"
        + signal preview (first 400 chars)
        + "✅ Yes review" link  (signed token)
        + "❌ Skip"      link  (signed token)
  [no spend]

Director taps "Yes review" link → opens browser →
  GET /api/cortex/gate/decide?signal_id=N&action=approve&token=<sig>
    → verify HMAC token + expiry + not-already-decided
    → record decision in baker_actions (action_type='cortex:gate:approved')
    → fire maybe_run_cycle as BackgroundTask
    → return HTML "Cycle started, ETA ~5 min, watch Slack"

Director taps "Skip" link →
  GET /api/cortex/gate/decide?signal_id=N&action=skip&token=<sig>
    → verify HMAC token + expiry + not-already-decided
    → record decision in baker_actions (action_type='cortex:gate:skipped')
    → return HTML "Skipped"
```

**Director-manual `/api/cortex/trigger` is unchanged** — it bypasses the gate (Director already chose to spend by calling it directly).

---

## Implementation

### File 1: NEW `triggers/cortex_pre_review_gate.py` (~180 LOC)

Module providing: token signing/verification + signal preview fetch + Slack DM compose & post + decision audit.

```python
"""CORTEX_PRE_REVIEW_GATE_1: cost gate for auto-dispatched Cortex cycles.

When a signal lands that would auto-fire a Cortex cycle, this module posts
a cheap Slack DM with two signed-URL links instead of firing immediately.
Director taps "Yes review" → background task fires maybe_run_cycle. Taps
"Skip" → decision recorded, no spend.

Stateless tokens: HMAC-SHA256(signal_id|action|expires_at, secret).
Secret = env var CORTEX_GATE_SECRET (>=32 chars; 401 if unset).
Token TTL = 24h.

Decision audit lives in baker_actions (action_type='cortex:gate:*');
no new table needed. Idempotency: re-clicking checks baker_actions.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

GATE_TTL_SECONDS = 24 * 3600
DIRECTOR_DM_CHANNEL = "D0AFY28N030"  # canonical (matches triggers/audit_sentinel.py:19)
PUBLIC_BASE_URL = os.environ.get(
    "BAKER_PUBLIC_BASE_URL", "https://baker-master.onrender.com"
)


def _secret() -> Optional[str]:
    """Return CORTEX_GATE_SECRET if set + length>=32, else None."""
    s = os.environ.get("CORTEX_GATE_SECRET", "").strip()
    return s if len(s) >= 32 else None


def sign_token(*, signal_id: int, action: str, expires_at: int) -> str:
    """Sign a (signal_id, action, expires_at) tuple. Returns base64url HMAC.

    Returns empty string if secret unset (caller checks; if empty, gate is
    disabled and we fall through to the legacy direct-fire path).
    """
    secret = _secret()
    if not secret:
        return ""
    payload = f"{signal_id}|{action}|{expires_at}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")


def verify_token(*, signal_id: int, action: str, expires_at: int, token: str) -> Tuple[bool, str]:
    """Constant-time verify (signal_id, action, expires_at, token).

    Returns (ok, error_message). Failure modes: secret unset, expired,
    HMAC mismatch.
    """
    if action not in ("approve", "skip"):
        return False, "invalid_action"
    secret = _secret()
    if not secret:
        return False, "gate_disabled"
    if int(time.time()) > expires_at:
        return False, "expired"
    expected = sign_token(signal_id=signal_id, action=action, expires_at=expires_at)
    if not expected:
        return False, "gate_disabled"
    if not hmac.compare_digest(expected, token):
        return False, "bad_signature"
    return True, ""


def already_decided(signal_id: int) -> Optional[str]:
    """Return the decision action ('approved'|'skipped') if signal_id already
    has a baker_actions row, else None."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT action_type FROM baker_actions "
                "WHERE action_type IN ('cortex:gate:approved','cortex:gate:skipped') "
                "AND target_task_id = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (str(signal_id),),
            )
            row = cur.fetchone()
            cur.close()
            if not row:
                return None
            return row[0].split(":")[-1]  # 'approved' or 'skipped'
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error("already_decided lookup failed: %s", e)
        return None


def record_decision(*, signal_id: int, action: str, matter_slug: str) -> None:
    """Insert a baker_actions row for the gate decision."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO baker_actions (action_type, target_task_id, payload, "
                "trigger_source, success) VALUES (%s, %s, %s::jsonb, %s, %s)",
                (
                    f"cortex:gate:{action}",
                    str(signal_id),
                    f'{{"signal_id":{signal_id},"matter_slug":"{matter_slug}","action":"{action}"}}',
                    "cortex_pre_review_gate",
                    True,
                ),
            )
            conn.commit()
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error("record_decision insert failed: %s", e)


def _signal_preview(signal_id: int) -> str:
    """Fetch ~400 chars of the inbound signal's text for the gate preview."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return "(preview unavailable)"
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT signal_text FROM signal_queue WHERE id = %s",
                (signal_id,),
            )
            row = cur.fetchone()
            cur.close()
            if not row or not row[0]:
                return "(no preview)"
            txt = str(row[0])[:400]
            return txt
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error("signal_preview fetch failed: %s", e)
        return "(preview error)"


def post_gate(*, signal_id: int, matter_slug: str) -> bool:
    """Post the pre-review gate Slack DM. Returns True if posted.

    Idempotency: caller already invoked this for signal_id once → no-op
    if a baker_actions row exists for this signal_id with cortex:gate:*.
    """
    if already_decided(signal_id):
        logger.info("gate skipped — signal_id=%s already decided", signal_id)
        return False

    secret_ok = _secret() is not None
    if not secret_ok:
        logger.error(
            "CORTEX_GATE_SECRET unset/short — gate disabled, signal_id=%s "
            "would fire cycle without approval", signal_id,
        )
        return False

    expires_at = int(time.time()) + GATE_TTL_SECONDS
    approve_tok = sign_token(signal_id=signal_id, action="approve", expires_at=expires_at)
    skip_tok = sign_token(signal_id=signal_id, action="skip", expires_at=expires_at)
    approve_url = (
        f"{PUBLIC_BASE_URL}/api/cortex/gate/decide"
        f"?signal_id={signal_id}&action=approve&exp={expires_at}&token={approve_tok}"
    )
    skip_url = (
        f"{PUBLIC_BASE_URL}/api/cortex/gate/decide"
        f"?signal_id={signal_id}&action=skip&exp={expires_at}&token={skip_tok}"
    )

    preview = _signal_preview(signal_id)
    text = (
        f"📨 *New {matter_slug.upper()} signal — review with Cortex?*\n"
        f"Approx cost: $4 if approved.\n"
        f"\n*Preview:*\n>>> {preview}\n"
        f"\n<{approve_url}|✅ Yes, review (~$4)>   |   "
        f"<{skip_url}|❌ Skip>"
    )

    try:
        from outputs.slack_notifier import post_to_channel
        return bool(post_to_channel(DIRECTOR_DM_CHANNEL, text))
    except Exception as e:
        logger.error("post_gate Slack post failed signal_id=%s: %s", signal_id, e)
        return False
```

### File 2: MODIFY `triggers/cortex_pipeline.py`

Change `maybe_trigger_cortex` so that when `CORTEX_GATE_ENABLED=true` (NEW env, default true), it posts the gate instead of firing the cycle. When unset/false, falls through to legacy direct-fire.

```python
# Add near _live_pipeline_enabled
def _gate_enabled() -> bool:
    """Reads CORTEX_GATE_ENABLED. Default true."""
    return os.environ.get("CORTEX_GATE_ENABLED", "true").strip().lower() == "true"


# Modify maybe_trigger_cortex body, after the matter_slug check:
async def maybe_trigger_cortex(...) -> None:
    if not _live_pipeline_enabled():
        return
    if not matter_slug:
        return

    # CORTEX_PRE_REVIEW_GATE_1: post gate instead of firing cycle when gate enabled
    if _gate_enabled():
        try:
            from triggers.cortex_pre_review_gate import post_gate
            posted = post_gate(signal_id=signal_id, matter_slug=matter_slug)
            if posted:
                logger.info(
                    "cortex pre-review gate posted (signal_id=%s, matter=%s) — awaiting Director decision",
                    signal_id, matter_slug,
                )
                return
            # post_gate returned False — disabled or already decided.
            # If already decided, do nothing. If disabled (secret missing), fall through
            # to legacy direct-fire so Cortex still works.
            from triggers.cortex_pre_review_gate import already_decided, _secret
            if already_decided(signal_id):
                return
            if not _secret():
                logger.error(
                    "CORTEX_GATE_ENABLED but CORTEX_GATE_SECRET missing — falling through to direct fire",
                )
                # fall through to legacy path below
            else:
                return  # post_gate failed for other reasons — skip cycle to avoid runaway
        except Exception as e:
            logger.error("gate dispatch failed: %s — falling through", e)
            # fall through

    # Legacy direct-fire path (kept for kill-switch and compatibility)
    try:
        from orchestrator.cortex_runner import maybe_run_cycle
        await maybe_run_cycle(
            matter_slug=matter_slug, triggered_by="signal", trigger_signal_id=signal_id,
        )
    except Exception as e:
        logger.error(...)
```

### File 3: MODIFY `outputs/dashboard.py`

Add new endpoint near other `/api/cortex/*` routes (after `/api/cortex/trigger`):

```python
from fastapi.responses import HTMLResponse  # add to imports if not present
from fastapi import BackgroundTasks  # already imported

@app.get("/api/cortex/gate/decide", tags=["cortex"], response_class=HTMLResponse)
async def cortex_gate_decide(
    signal_id: int,
    action: str,
    exp: int,
    token: str,
    background_tasks: BackgroundTasks,
):
    """CORTEX_PRE_REVIEW_GATE_1: tap-from-Slack endpoint for the cost gate.

    Auth: signed-token (HMAC) — no X-Baker-Key (must be openable by Slack tap).
    Token = HMAC-SHA256(signal_id|action|expires_at, CORTEX_GATE_SECRET).

    Idempotent: re-clicking after decision returns the recorded decision page.
    """
    from triggers.cortex_pre_review_gate import (
        verify_token, already_decided, record_decision,
    )

    ok, err = verify_token(signal_id=signal_id, action=action, expires_at=exp, token=token)
    if not ok:
        return HTMLResponse(
            f"<h1>Gate link invalid</h1><p>Reason: {err}</p>",
            status_code=403,
        )

    prior = already_decided(signal_id)
    if prior:
        return HTMLResponse(
            f"<h1>Already decided</h1><p>Signal {signal_id}: <b>{prior}</b></p>",
            status_code=200,
        )

    # Lookup matter_slug from signal_queue for the audit row + eventual cycle
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="db_unavailable")
        try:
            cur = conn.cursor()
            cur.execute("SELECT matter_slug FROM signal_queue WHERE id = %s", (signal_id,))
            row = cur.fetchone()
            cur.close()
        finally:
            store._put_conn(conn)
        if not row:
            return HTMLResponse(
                f"<h1>Signal not found</h1><p>signal_id={signal_id}</p>",
                status_code=404,
            )
        matter_slug = row[0] or ""
    except HTTPException:
        raise
    except Exception as e:
        logger.error("gate decide signal lookup failed: %s", e)
        return HTMLResponse("<h1>Lookup error</h1>", status_code=500)

    record_decision(signal_id=signal_id, action=action, matter_slug=matter_slug)

    if action == "approve":
        # Fire cycle in background — don't block the HTTP response
        background_tasks.add_task(
            _cortex_gate_fire_cycle, matter_slug, signal_id,
        )
        return HTMLResponse(
            "<h1>✅ Cycle started</h1>"
            "<p>Cortex is analyzing now. ETA ~5 minutes. Watch Slack for the proposal card.</p>",
            status_code=200,
        )

    # action == "skip"
    return HTMLResponse(
        "<h1>❌ Skipped</h1>"
        "<p>Signal recorded as skipped. No cycle fired, no spend.</p>",
        status_code=200,
    )


async def _cortex_gate_fire_cycle(matter_slug: str, signal_id: int) -> None:
    """Background-task wrapper — fires maybe_run_cycle after gate approval."""
    try:
        cycle = await maybe_run_cycle(
            matter_slug=matter_slug,
            triggered_by="director_gate_approve",
            trigger_signal_id=signal_id,
        )
        logger.info(
            "gate-approved cycle complete: cycle_id=%s status=%s cost=$%.4f",
            cycle.cycle_id, cycle.status, cycle.cost_dollars or 0.0,
        )
    except Exception as e:
        logger.error(
            "gate-approved cycle failed signal_id=%s matter=%s: %s",
            signal_id, matter_slug, e,
        )
```

### File 4: NEW `tests/test_cortex_pre_review_gate.py` (~200 LOC, 7 tests)

```python
"""Tests for CORTEX_PRE_REVIEW_GATE_1.

Coverage:
1. sign_token / verify_token roundtrip — happy path
2. verify_token rejects expired token
3. verify_token rejects bad signature
4. verify_token rejects unknown action
5. verify_token returns gate_disabled when CORTEX_GATE_SECRET unset
6. already_decided returns prior decision when baker_actions row exists
7. /api/cortex/gate/decide endpoint full happy path (approve flow)
"""
import os
import time
from unittest.mock import patch, AsyncMock, MagicMock
import pytest
from fastapi.testclient import TestClient

# Set secret BEFORE importing the gate module so module-level reads pick it up
os.environ["CORTEX_GATE_SECRET"] = "test-secret-32-characters-long-XX"

from triggers.cortex_pre_review_gate import (
    sign_token, verify_token, GATE_TTL_SECONDS,
)


def test_sign_verify_roundtrip():
    exp = int(time.time()) + 3600
    tok = sign_token(signal_id=42, action="approve", expires_at=exp)
    assert tok
    ok, err = verify_token(signal_id=42, action="approve", expires_at=exp, token=tok)
    assert ok and err == ""


def test_verify_expired():
    exp = int(time.time()) - 60  # 1 min ago
    tok = sign_token(signal_id=42, action="approve", expires_at=exp)
    ok, err = verify_token(signal_id=42, action="approve", expires_at=exp, token=tok)
    assert not ok and err == "expired"


def test_verify_bad_signature():
    exp = int(time.time()) + 3600
    ok, err = verify_token(
        signal_id=42, action="approve", expires_at=exp, token="garbage",
    )
    assert not ok and err == "bad_signature"


def test_verify_unknown_action():
    exp = int(time.time()) + 3600
    ok, err = verify_token(signal_id=42, action="DELETE", expires_at=exp, token="x")
    assert not ok and err == "invalid_action"


def test_secret_unset_disables_gate(monkeypatch):
    monkeypatch.delenv("CORTEX_GATE_SECRET", raising=False)
    import importlib, triggers.cortex_pre_review_gate as g
    importlib.reload(g)
    assert g.sign_token(signal_id=1, action="approve", expires_at=int(time.time())+60) == ""
    ok, err = g.verify_token(signal_id=1, action="approve", expires_at=int(time.time())+60, token="x")
    assert not ok and err == "gate_disabled"
    # Restore for downstream tests
    monkeypatch.setenv("CORTEX_GATE_SECRET", "test-secret-32-characters-long-XX")
    importlib.reload(g)


def test_already_decided_returns_prior(monkeypatch):
    """already_decided returns 'approved' when a baker_actions row exists."""
    import triggers.cortex_pre_review_gate as g
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_cur.fetchone.return_value = ("cortex:gate:approved",)
    fake_conn.cursor.return_value = fake_cur

    fake_store = MagicMock()
    fake_store._get_conn.return_value = fake_conn
    fake_store._put_conn = MagicMock()

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=fake_store):
        result = g.already_decided(signal_id=42)
    assert result == "approved"


def test_gate_decide_endpoint_approve_flow(monkeypatch):
    """Full path: signed URL → 200 HTML + background_task scheduled."""
    monkeypatch.setenv("CORTEX_GATE_SECRET", "test-secret-32-characters-long-XX")
    import importlib, triggers.cortex_pre_review_gate as g
    importlib.reload(g)

    from outputs.dashboard import app

    exp = int(time.time()) + 3600
    tok = g.sign_token(signal_id=999, action="approve", expires_at=exp)

    # Mock signal_queue lookup + record_decision + cycle fire
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_cur.fetchone.return_value = ("oskolkov",)
    fake_conn.cursor.return_value = fake_cur
    fake_store = MagicMock()
    fake_store._get_conn.return_value = fake_conn

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=fake_store), \
         patch("triggers.cortex_pre_review_gate.already_decided", return_value=None), \
         patch("triggers.cortex_pre_review_gate.record_decision"), \
         patch("outputs.dashboard.maybe_run_cycle", new=AsyncMock(return_value=MagicMock(
             cycle_id="bg-cycle-1", status="tier_b_pending", cost_dollars=4.0,
         ))):
        client = TestClient(app)
        resp = client.get(
            f"/api/cortex/gate/decide?signal_id=999&action=approve&exp={exp}&token={tok}",
        )
        assert resp.status_code == 200, resp.text
        assert "Cycle started" in resp.text
```

### Key Constraints (DO NOT)

- DO NOT remove the legacy direct-fire fallback in `maybe_trigger_cortex` — kill-switch behavior matters.
- DO NOT change `/api/cortex/trigger` (manual endpoint — bypasses gate intentionally).
- DO NOT log `signal_text` / preview content at info level (preview goes to Slack only — sensitive).
- DO NOT use `BAKER_API_KEY` for the gate endpoint — must be tap-clickable from Slack-on-iPhone (no header injection on iOS Safari follow-link).
- DO NOT make CORTEX_GATE_SECRET shorter than 32 chars (validation enforced).
- DO NOT cache the verified token (tokens are stateless; idempotency is via `already_decided` check on baker_actions).

### Quality Checkpoints

1. `python3 -c "import py_compile; py_compile.compile('triggers/cortex_pre_review_gate.py', doraise=True)"` clean
2. `python3 -c "import py_compile; py_compile.compile('triggers/cortex_pipeline.py', doraise=True)"` clean
3. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` clean
4. `pytest tests/test_cortex_pre_review_gate.py -v` — 7/7 PASS literal
5. `pytest tests/test_cortex_runner_phase126.py tests/test_cortex_pipeline.py tests/test_alerts_to_signal_cortex_dispatch.py -v` regression — all PASS literal
6. HMAC uses `hmac.compare_digest` (constant-time)
7. CORTEX_GATE_SECRET length validated (>=32)

## Files Modified / Added

- `triggers/cortex_pre_review_gate.py` — NEW (~180 LOC)
- `triggers/cortex_pipeline.py` — modified (~30 LOC added, _gate_enabled() + gate path)
- `outputs/dashboard.py` — modified (+~70 LOC: endpoint + background fire helper)
- `tests/test_cortex_pre_review_gate.py` — NEW (~200 LOC, 7 tests)

## Do NOT Touch

- `orchestrator/cortex_runner.py` — out of scope
- `kbl/bridge/alerts_to_signal.py` — `_dispatch_cortex_for_inserted` calls `maybe_dispatch` which is unchanged in interface
- Existing `/api/cortex/trigger` endpoint — manual path, bypasses gate

## After merge — A executes

1. Set Render env vars (per-key PUT):
   - `CORTEX_GATE_SECRET` = 32+ random chars (gen via `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`)
   - `CORTEX_GATE_ENABLED=true`  (default true; explicit for clarity)
2. Render redeploy
3. Smoke test:
   - Synthesize a fake gate URL with valid token via `triggers/cortex_pre_review_gate.sign_token`
   - GET it → expect 200 + "Cycle started" HTML
4. Trigger an organic-style test by manually inserting a signal_queue row + calling `maybe_dispatch` → expect Slack DM with 2 links, no cycle yet
5. Tap "Skip" link → 200 "Skipped" + baker_actions row + no cycle
6. Trigger again → tap "Yes review" → 200 "Cycle started" + 4-5min later proposal_card lands

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
