# BRIEF: CORTEX_PRE_REVIEW_GATE_2_HARDEN — close TOCTOU + Slack-unfurl side-fire

## Context

PR #80 (CORTEX_PRE_REVIEW_GATE_1) is structurally PASS per B1 (10/10 sections clear) but A's `/security-review` + post-review analysis surfaced TWO blockers that MUST land before merge:

**Blocker 1 — TOCTOU race (security-review confidence 9, MEDIUM cost-loss).**
Between `already_decided()` read and `record_decision()` insert there is no DB-level guard. iPhone double-tap (slow 4G perceived non-response), Slack link unfurler GET, and any URL preview bot can all double-fire. Result: 2× $4 cycles, 2× competing matter-state writes.

**Blocker 2 — Slack unfurler GETs the URL (HIGH).**
`outputs/slack_notifier.post_to_channel` does not pass `unfurl_links: false` / `unfurl_media: false`. Slack's URL fetcher (`Slackbot-LinkExpanding`) GETs every URL in a posted message to render previews. Our `/api/cortex/gate/decide?action=approve` is a side-effecting GET — Slackbot's preview fetch alone would auto-approve and fire $4 the instant we post the DM, without Director ever tapping. **GET endpoints with side effects violate HTTP semantics; this is a textbook fire-on-post bug.**

This brief patches both on the existing `cortex-pre-review-gate-1` branch (no new branch). After patch lands, A re-runs /security-review to re-clear, then merges.

## Estimated time: ~1-2h
## Complexity: Low
## Trigger class: HIGH (still — this is a hardening patch on an external API + auth path)
## Builder: B2 (continuation on same branch). Reviewer: AI Head A solo (Lesson #52 + structural — B1 already cleared the structural pass; the patches are surgical).

---

## Fix 1 — Atomic idempotency via conditional INSERT

### Problem

`record_decision()` does a plain INSERT, with no protection against concurrent inserts for the same `signal_id`.

### Implementation

**File:** `triggers/cortex_pre_review_gate.py`

Modify `record_decision` signature to return `bool` (claimed=True/lost=False) and use a single atomic conditional INSERT:

```python
def record_decision(*, signal_id: int, action: str, matter_slug: str) -> bool:
    """Insert a baker_actions row for the gate decision.

    Returns True if THIS call claimed the decision row (no prior row existed),
    False if a concurrent call already claimed it. Caller must check return
    value and skip the cycle fire when False.

    Atomic via INSERT ... WHERE NOT EXISTS — Postgres serializes concurrent
    INSERTs against the same target_task_id at the row-lock level.
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            payload = (
                f'{{"signal_id":{int(signal_id)},'
                f'"matter_slug":{json.dumps(matter_slug)},'
                f'"action":{json.dumps(action)}}}'
            )
            cur.execute(
                "INSERT INTO baker_actions "
                "(action_type, target_task_id, payload, trigger_source, success) "
                "SELECT %s, %s, %s::jsonb, %s, %s "
                "WHERE NOT EXISTS ("
                "    SELECT 1 FROM baker_actions "
                "    WHERE target_task_id = %s "
                "    AND action_type IN ('cortex:gate:approved','cortex:gate:skipped')"
                ") "
                "RETURNING id",
                (
                    f"cortex:gate:{action}", str(signal_id), payload,
                    "cortex_pre_review_gate", True,
                    str(signal_id),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            return row is not None  # True if INSERT actually wrote a row
        except Exception:
            conn.rollback()
            raise
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error("record_decision insert failed: %s", e)
        return False
```

Add `import json` at module top if not already imported.

**File:** `outputs/dashboard.py`

In `/api/cortex/gate/decide`, only fire BackgroundTask if `record_decision` returned True:

```python
# Replace the existing record_decision + background_tasks.add_task block:

claimed = record_decision(signal_id=signal_id, action=action, matter_slug=matter_slug)
if not claimed:
    # Lost the race — another concurrent request already decided.
    return HTMLResponse(
        f"<h1>Already decided</h1><p>Signal {signal_id}: another decision was recorded simultaneously.</p>",
        status_code=200,
    )

if action == "approve":
    background_tasks.add_task(_cortex_gate_fire_cycle, matter_slug, signal_id)
    return HTMLResponse(
        "<h1>✅ Cycle started</h1>"
        "<p>Cortex is analyzing now. ETA ~5 minutes. Watch Slack for the proposal card.</p>",
        status_code=200,
    )

# action == "skip"
return HTMLResponse(
    "<h1>❌ Skipped</h1><p>Signal recorded as skipped. No cycle fired, no spend.</p>",
    status_code=200,
)
```

### Test

Add to `tests/test_cortex_pre_review_gate.py`:

```python
def test_record_decision_claim_then_loser(monkeypatch):
    """First call claims (returns True), second call for same signal_id loses (returns False)."""
    import triggers.cortex_pre_review_gate as g

    # Mock psycopg2 conn — first execute returns row (claim), second returns None (lost)
    fake_cur = MagicMock()
    fake_cur.fetchone.side_effect = [(1,), None]  # 1st claim, 2nd lost
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_store = MagicMock()
    fake_store._get_conn.return_value = fake_conn

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=fake_store):
        first = g.record_decision(signal_id=42, action="approve", matter_slug="oskolkov")
        second = g.record_decision(signal_id=42, action="approve", matter_slug="oskolkov")
    assert first is True
    assert second is False


def test_gate_decide_endpoint_race_loser_does_not_fire_cycle(monkeypatch):
    """If record_decision returns False (lost the race), no BackgroundTask fires."""
    monkeypatch.setenv("CORTEX_GATE_SECRET", "test-secret-32-characters-long-XX")
    import importlib, triggers.cortex_pre_review_gate as g
    importlib.reload(g)
    from outputs.dashboard import app

    exp = int(time.time()) + 3600
    tok = g.sign_token(signal_id=999, action="approve", expires_at=exp)

    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_cur.fetchone.return_value = ("oskolkov",)
    fake_conn.cursor.return_value = fake_cur
    fake_store = MagicMock()
    fake_store._get_conn.return_value = fake_conn

    cycle_fire_mock = AsyncMock()
    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=fake_store), \
         patch("triggers.cortex_pre_review_gate.already_decided", return_value=None), \
         patch("triggers.cortex_pre_review_gate.record_decision", return_value=False), \
         patch("outputs.dashboard.maybe_run_cycle", new=cycle_fire_mock):
        client = TestClient(app)
        resp = client.get(
            f"/api/cortex/gate/decide?signal_id=999&action=approve&exp={exp}&token={tok}",
        )
        assert resp.status_code == 200
        assert "Already decided" in resp.text
    # Background task ran would have called maybe_run_cycle; verify it did NOT.
    cycle_fire_mock.assert_not_awaited()
```

---

## Fix 2 — Disable Slack unfurl on the gate DM (closes the side-fire-on-post bug)

### Problem

`outputs/slack_notifier.post_to_channel(channel, text)` calls `client.chat_postMessage(channel=channel_id, text=text[:3000])` without `unfurl_links` / `unfurl_media`. Slack's default = unfurl on. Slackbot fetches every URL in the message to render previews — that GET hits `/api/cortex/gate/decide?action=approve` and fires the cycle.

### Implementation

**Step A — extend `post_to_channel` with optional kwargs (default behavior unchanged for existing callers).**

**File:** `outputs/slack_notifier.py`

```python
def post_to_channel(
    channel_id: str,
    text: str,
    *,
    unfurl_links: bool | None = None,
    unfurl_media: bool | None = None,
) -> bool:
    """... (existing docstring) ...

    Optional kwargs:
        unfurl_links: pass False to suppress URL previews (e.g. when the
                      URL itself is the action and a Slackbot preview-GET
                      would side-effect the endpoint).
        unfurl_media: pass False to suppress media previews.
        Both default None = Slack default behavior.
    """
    if not config.outputs.slack_bot_token:
        logger.warning("post_to_channel skipped: SLACK_BOT_TOKEN not configured")
        return False
    try:
        client = _get_webclient()
        kwargs = {"channel": channel_id, "text": text[:3000]}
        if unfurl_links is not None:
            kwargs["unfurl_links"] = unfurl_links
        if unfurl_media is not None:
            kwargs["unfurl_media"] = unfurl_media
        resp = client.chat_postMessage(**kwargs)
        if resp.get("ok"):
            return True
        logger.warning(
            f"post_to_channel failed ({channel_id}): {resp.get('error')}"
        )
        return False
    except Exception as e:
        logger.warning(f"post_to_channel raised ({channel_id}): {e}")
        return False
```

**Step B — pass the flags from `post_gate`.**

**File:** `triggers/cortex_pre_review_gate.py`

Find the line that calls `post_to_channel(DIRECTOR_DM_CHANNEL, text)` and change to:

```python
return bool(post_to_channel(
    DIRECTOR_DM_CHANNEL, text,
    unfurl_links=False,
    unfurl_media=False,
))
```

### Test

Add to `tests/test_cortex_pre_review_gate.py`:

```python
def test_post_gate_disables_slack_unfurl(monkeypatch):
    """post_gate MUST call post_to_channel with unfurl_links=False + unfurl_media=False."""
    monkeypatch.setenv("CORTEX_GATE_SECRET", "test-secret-32-characters-long-XX")
    import importlib, triggers.cortex_pre_review_gate as g
    importlib.reload(g)

    captured = {}
    def _fake_post(channel, text, *, unfurl_links=None, unfurl_media=None):
        captured["channel"] = channel
        captured["unfurl_links"] = unfurl_links
        captured["unfurl_media"] = unfurl_media
        return True

    with patch("triggers.cortex_pre_review_gate.already_decided", return_value=None), \
         patch("triggers.cortex_pre_review_gate._signal_preview", return_value="preview"), \
         patch("outputs.slack_notifier.post_to_channel", side_effect=_fake_post):
        ok = g.post_gate(signal_id=42, matter_slug="oskolkov")
    assert ok is True
    assert captured["unfurl_links"] is False, "MUST suppress unfurl_links to prevent side-fire on Slack URL preview"
    assert captured["unfurl_media"] is False, "MUST suppress unfurl_media as well"
```

---

## Quality Checkpoints

1. py_compile clean on `triggers/cortex_pre_review_gate.py`, `outputs/slack_notifier.py`, `outputs/dashboard.py`
2. New tests PASS literally:
   - `test_record_decision_claim_then_loser` ✓
   - `test_gate_decide_endpoint_race_loser_does_not_fire_cycle` ✓
   - `test_post_gate_disables_slack_unfurl` ✓
3. All 7 prior gate tests still PASS literally
4. Regression suite (`tests/test_cortex_pipeline.py tests/test_alerts_to_signal_cortex_dispatch.py tests/test_cortex_runner_phase126.py`) PASS literal
5. `post_to_channel` existing callers (`audit_sentinel`, `ai_head_audit`×2, `wiki_lint`) unaffected (default kwargs=None preserves prior call signature)
6. Branch is still `cortex-pre-review-gate-1`; same PR #80 — push hardening commit on top

## Files Modified

- `triggers/cortex_pre_review_gate.py` — `record_decision` returns bool + atomic conditional INSERT + post_gate passes unfurl flags
- `outputs/slack_notifier.py` — `post_to_channel` extended with optional unfurl_links / unfurl_media kwargs
- `outputs/dashboard.py` — gate endpoint checks `record_decision` return; only fires BackgroundTask on True
- `tests/test_cortex_pre_review_gate.py` — 3 new tests appended

## Do NOT Touch

- `orchestrator/cortex_runner.py`
- `kbl/bridge/alerts_to_signal.py`
- `triggers/cortex_pipeline.py` (gate fork already correct from PR #80)
- Other dashboard endpoints
- `audit_sentinel.py` / `ai_head_audit.py` / `wiki_lint.py` (post_to_channel callers — must remain unaffected)

## After patch ships — A executes

1. /security-review re-run on updated diff
2. Re-confirm B1 sections C (URL endpoint) + E (Idempotency) — quick A-solo recheck (B1 review still valid for the rest)
3. Squash-merge PR #80 with both commits
4. Render env vars + redeploy + smoke (per original brief §"After merge — A executes")

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
