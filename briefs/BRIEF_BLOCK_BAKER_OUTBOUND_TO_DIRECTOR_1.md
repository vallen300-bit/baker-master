# BRIEF: BLOCK_BAKER_OUTBOUND_TO_DIRECTOR_1 — env-flagged hard block on Baker → Director WhatsApp + email outbound

## Context

Today (2026-05-25) Baker burned ~€92 between 00:00-05:00Z in a WhatsApp self-chat loop — Baker received its own outbound messages (re-attributed by WAHA `fromMe` handling), routed them through `_handle_director_question`, and replied to itself. Fix shipped (PR #263) closes the root-cause misclassification path. This brief adds a second, independent safety layer: an env-flagged HARD block on all Baker → Director outbound regardless of kind, intent, or upstream code path.

**Director directive (2026-05-25 ~16:30Z chat):** keep Baker's ability to send WhatsApps + emails on Director's instruction (counterparties, agents, third parties) running, but kill Baker's ability to send WhatsApps + emails TO Director himself. Belt-and-suspenders.

Anchor: this is a complement to BRIEF_BAKER_WA_DIRECTOR_FILTER_1 (kind-allowlist) which kept `director_inbound` allowed and was therefore exploited by today's loop.

### Surface contract: N/A — pure backend chokepoint guards (no clickable surface, no dashboard panel, no frontend route).

## Estimated time: ~45 min (build 25-30 min + tests 10 min + gates 5-10 min)
## Complexity: Low
## Prerequisites: none — both chokepoint files already exist with strong upstream protection

---

## Fix 1: WhatsApp hard block

### Problem

`send_whatsapp()` in `outputs/whatsapp_sender.py` already protects Director-bound sends via `DIRECTOR_PHONE_ROOTS` + `DIRECTOR_WA_ALLOWED_KINDS` (kind-allowlist from BAKER_WA_DIRECTOR_FILTER_1). But `kind="director_inbound"` is allowlisted — and today's self-chat loop exploited exactly that path. Need an env-flagged hard block that overrides the kind-check entirely.

### Current State

`outputs/whatsapp_sender.py`:
- Line 37-40: `DIRECTOR_PHONE_ROOTS` frozenset — Director's Swiss + UK numbers.
- Line 270-278: `DIRECTOR_WA_ALLOWED_KINDS` frozenset — 7 allowed kinds incl. `director_inbound`.
- Line 329-366: `send_whatsapp(text, chat_id, *, kind)` — the canonical chokepoint. Kind-check at line 355.
- Line 281-326: `_log_director_blocked(text, kind)` — audit helper that writes `whatsapp_blocked` row to `baker_actions`.

All WhatsApp outbound (incl. `_wa_reply()` in `triggers/waha_webhook.py:149`) routes through `send_whatsapp()`. Confirmed via grep — no direct `/api/sendText` callers exist.

### Implementation

**Step 1.1 — Add module-level env flag constant near top of `outputs/whatsapp_sender.py`** (insert after line 17, after `WAHA_API_KEY` line):

```python
# BAKER_BLOCK_WA_TO_DIRECTOR — env-flagged HARD block on Director-bound WA outbound.
# Independent of (and stronger than) the BAKER_WA_DIRECTOR_FILTER_1 kind-allowlist:
# when this flag is ON, NO Baker → Director WA send goes through, regardless of kind.
# Default ON. Anchor: Director directive 2026-05-25 post WhatsApp self-chat cost-runaway
# loop (~€92/day burn between 2026-05-21 and 2026-05-25 closed via PR #263).
# To re-enable Baker → Director WA (e.g. for Director-Q replies), set this env var to
# "false" via Render and redeploy.
_BLOCK_WA_TO_DIRECTOR = os.getenv("BAKER_BLOCK_WA_TO_DIRECTOR", "true").lower() in ("true", "1", "yes")
```

**Step 1.2 — Add audit helper for hard-block events** (insert after the existing `_log_director_blocked()` function, around line 326):

```python
def _log_director_hard_blocked(text: str, kind: Optional[str]) -> None:
    """Audit a Director-bound WA send blocked by the BAKER_BLOCK_WA_TO_DIRECTOR
    hard switch (distinct from the kind-allowlist block). Fails silently.
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            payload = {
                "reason": "director_hard_block_env_flag",
                "env_flag": "BAKER_BLOCK_WA_TO_DIRECTOR",
                "kind": kind,
                "text_preview": text[:200],
            }
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO baker_actions
                    (action_type, target_task_id, target_space_id, payload,
                     trigger_source, success, error_message)
                VALUES (%s, NULL, NULL, %s::jsonb, %s, %s, %s)
                """,
                (
                    "whatsapp_hard_blocked",
                    json.dumps(payload),
                    "whatsapp_sender",
                    False,
                    None,
                ),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            logger.warning(f"whatsapp_hard_blocked audit insert failed: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"whatsapp_hard_blocked audit unavailable: {e}")
```

**Step 1.3 — Add hard-block guard inside `send_whatsapp()`** (insert immediately after line 350 `requested_chat_id = chat_id` and BEFORE the existing kind-check at line 355):

```python
    # BAKER_BLOCK_WA_TO_DIRECTOR hard switch — overrides kind-allowlist entirely.
    # Hits BEFORE the kind-check so even allowlisted kinds (incl. director_inbound)
    # are dropped when this is ON. Independent failsafe against any cost-runaway
    # loop class that touches Director-bound outbound.
    if _BLOCK_WA_TO_DIRECTOR and _phone_root(chat_id) in DIRECTOR_PHONE_ROOTS:
        logger.warning(
            "WA_DIRECTOR_HARD_BLOCK: dropped Director-bound send (env-flagged). "
            "chat_id=%r kind=%r text_preview=%r",
            chat_id, kind, text[:120],
        )
        _log_director_hard_blocked(text, kind)
        return False
```

### Key Constraints

- **Do NOT remove or weaken the existing `DIRECTOR_WA_ALLOWED_KINDS` kind-check.** When `_BLOCK_WA_TO_DIRECTOR=false`, the kind-allowlist is the active protection — preserve it as-is.
- **Do NOT touch `triggers/waha_webhook.py`.** `_wa_reply()` already routes through `send_whatsapp()`; the chokepoint catches all paths.
- **Do NOT touch the existing `_log_director_blocked()` function or the `whatsapp_blocked` `action_type`.** New `whatsapp_hard_blocked` `action_type` is intentionally distinct for analytics.

### Verification

After deploy, run:

```sql
-- Confirm hard-block audit rows appear when guard fires
SELECT created_at, payload->>'reason' AS reason, payload->>'kind' AS kind
FROM baker_actions
WHERE action_type = 'whatsapp_hard_blocked'
ORDER BY created_at DESC
LIMIT 5;
```

---

## Fix 2: Email hard block

### Problem

`_send_raw_full()` in `outputs/email_alerts.py` is the canonical low-level Gmail send. Today it has no recipient-based guard — `_EMAIL_ALERTS_DISABLED` only short-circuits the proactive alert wrappers (`send_alert_email`, `send_scan_result_email`, `send_daily_summary_email`), but NOT `_send_raw_full()` itself. Director-composed paths (Type 4, Type 5) and any future caller bypass that flag.

Need a recipient-based hard block at the lowest layer covering BOTH Director addresses.

### Current State

`outputs/email_alerts.py`:
- Line 32: `DIRECTOR_EMAIL = "dvallen@brisengroup.com"`.
- Line 38: `_EMAIL_ALERTS_DISABLED` — module-level env-derived constant (pattern to mirror).
- Line 67-84: `_send_raw_full(to, subject, body)` — the canonical low-level Gmail send.
- Line 87-93: `_send_raw()` — wraps `_send_raw_full()`, returns message_id only.

Director's personal Gmail `vallen300@gmail.com` is documented in `/Users/dimitry/.claude/CLAUDE.md` (Director profile) but not yet a constant in `email_alerts.py` — add it.

### Implementation

**Step 2.1 — Add Director-emails set + env flag constant near top of `outputs/email_alerts.py`** (insert after line 33 `DASHBOARD_URL = ...`):

```python
# Director's personal Gmail (occasional fallback). Covered by hard block alongside primary.
DIRECTOR_PERSONAL_EMAIL = "vallen300@gmail.com"
DIRECTOR_EMAILS = frozenset({DIRECTOR_EMAIL.lower(), DIRECTOR_PERSONAL_EMAIL.lower()})

# BAKER_BLOCK_EMAIL_TO_DIRECTOR — env-flagged HARD block on Director-bound email
# outbound. Independent of (and stronger than) BAKER_EMAIL_ALERTS_DISABLED which
# only short-circuits proactive alert wrappers. This guard hits at the lowest
# send primitive, catching Type 4 manual summary, Type 5 composed email, and any
# future caller. Default ON. Anchor: Director directive 2026-05-25.
# To re-enable Baker → Director email, set this env var to "false" via Render and redeploy.
_BLOCK_EMAIL_TO_DIRECTOR = os.getenv("BAKER_BLOCK_EMAIL_TO_DIRECTOR", "true").lower() in ("true", "1", "yes")
```

**Step 2.2 — Add audit helper** (insert immediately before `_send_raw_full()` definition at line 67):

```python
def _log_email_director_hard_blocked(to: str, subject: str, body: str) -> None:
    """Audit a Director-bound email send blocked by the BAKER_BLOCK_EMAIL_TO_DIRECTOR
    hard switch. Mirrors WA-side audit pattern. Fails silently.
    """
    try:
        from memory.store_back import SentinelStoreBack
        import json as _json
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            payload = {
                "reason": "director_hard_block_env_flag",
                "env_flag": "BAKER_BLOCK_EMAIL_TO_DIRECTOR",
                "to": to,
                "subject_preview": (subject or "")[:200],
                "body_preview": (body or "")[:200],
            }
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO baker_actions
                    (action_type, target_task_id, target_space_id, payload,
                     trigger_source, success, error_message)
                VALUES (%s, NULL, NULL, %s::jsonb, %s, %s, %s)
                """,
                (
                    "email_hard_blocked",
                    _json.dumps(payload),
                    "email_alerts",
                    False,
                    None,
                ),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            logger.warning(f"email_hard_blocked audit insert failed: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"email_hard_blocked audit unavailable: {e}")
```

**Step 2.3 — Add guard at top of `_send_raw_full()`** (insert immediately after the docstring, before `service = _get_gmail_service()`):

```python
    # BAKER_BLOCK_EMAIL_TO_DIRECTOR hard switch — recipient-based block at the
    # lowest send primitive. Covers Type 4 / Type 5 / any future caller.
    if _BLOCK_EMAIL_TO_DIRECTOR and to and to.strip().lower() in DIRECTOR_EMAILS:
        logger.warning(
            "EMAIL_DIRECTOR_HARD_BLOCK: dropped Director-bound send (env-flagged). "
            "to=%r subject=%r", to, (subject or "")[:80]
        )
        _log_email_director_hard_blocked(to, subject, body)
        return None
```

### Key Constraints

- **Do NOT touch the existing `_EMAIL_ALERTS_DISABLED` flag.** It remains the upstream alert-only switch; the new flag is the recipient-based hard block at the lowest layer. Both flags coexist.
- **Do NOT remove `DIRECTOR_EMAIL = "dvallen@brisengroup.com"`** — `DIRECTOR_EMAILS` set REFERENCES it. Removing the constant breaks Type 3 default-recipient logic in `send_daily_summary_email`.
- **Lowercase comparison** — Gmail RFC 5321 local-parts can be case-sensitive but are case-insensitive in practice; `.strip().lower()` both sides for robust matching.

### Verification

After deploy, run:

```sql
-- Confirm hard-block audit rows appear when guard fires
SELECT created_at, payload->>'to' AS recipient, payload->>'subject_preview' AS subject
FROM baker_actions
WHERE action_type = 'email_hard_blocked'
ORDER BY created_at DESC
LIMIT 5;
```

---

## Fix 3: Render env vars

Set BEFORE merge so the deploy carries them atomically with the code:

```
BAKER_BLOCK_WA_TO_DIRECTOR=true
BAKER_BLOCK_EMAIL_TO_DIRECTOR=true
```

Use the existing `safe_env_put` MCP merge-mode pattern (per `.claude/rules/python-backend.md`). AI Head A will set these via Render API as a pre-merge Tier-A action — Code Brisen does NOT need to touch Render.

---

## Fix 4: Tests

### Test file: `tests/test_whatsapp_sender_director_hard_block.py` (NEW)

Required coverage:

1. `test_hard_block_drops_director_swiss_send_default_env` — patches `_BLOCK_WA_TO_DIRECTOR=True`, calls `send_whatsapp("hi", chat_id="41799605092@c.us", kind="counterparty")`, asserts: returns `False`, no `httpx.Client.post` call made, `whatsapp_hard_blocked` row written.
2. `test_hard_block_drops_director_uk_send` — same with `447588690632@c.us`.
3. `test_hard_block_drops_even_allowlisted_kind` — same call with `kind="director_inbound"` (was allowlisted by BAKER_WA_DIRECTOR_FILTER_1) — STILL gets blocked because hard switch precedes kind-check.
4. `test_hard_block_bypassed_when_env_false` — patches `_BLOCK_WA_TO_DIRECTOR=False`, calls with `kind="counterparty"`, asserts kind-allowlist path runs (returns False, `whatsapp_blocked` audit row, NOT `whatsapp_hard_blocked`).
5. `test_counterparty_send_unaffected` — patches `_BLOCK_WA_TO_DIRECTOR=True`, calls with a non-Director chat_id (e.g. `447588690633@c.us` — UK number 1 digit different) and `kind=None` (kinds not required for non-Director sends), asserts HTTP POST happens (mock returns 200), `whatsapp_hard_blocked` row NOT written.

Use existing `tests/test_whatsapp_sender*.py` patterns for mocking httpx + the `_get_global_instance` audit path.

### Test file: `tests/test_email_alerts_director_hard_block.py` (NEW)

Required coverage:

1. `test_hard_block_drops_brisengroup_email` — patches `_BLOCK_EMAIL_TO_DIRECTOR=True`, calls `_send_raw_full("dvallen@brisengroup.com", "subj", "body")`, asserts: returns `None`, no Gmail API call made, `email_hard_blocked` row written.
2. `test_hard_block_drops_personal_gmail` — same with `vallen300@gmail.com`.
3. `test_hard_block_drops_uppercase_and_whitespace` — calls with `"  DVallen@BrisenGroup.COM  "` to confirm `.strip().lower()` normalization works.
4. `test_hard_block_bypassed_when_env_false` — patches `_BLOCK_EMAIL_TO_DIRECTOR=False`, calls with Director email, asserts Gmail API call attempted (mock returns id).
5. `test_counterparty_email_unaffected` — patches `_BLOCK_EMAIL_TO_DIRECTOR=True`, calls with `"counsel@example.com"`, asserts Gmail API call attempted.

Use `pytest.MonkeyPatch` to override the module-level constants (`monkeypatch.setattr("outputs.email_alerts._BLOCK_EMAIL_TO_DIRECTOR", False)`). Mock `_get_gmail_service` to avoid real OAuth.

### Run command

```bash
pytest tests/test_whatsapp_sender_director_hard_block.py tests/test_email_alerts_director_hard_block.py -v
```

Both files MUST pass with literal output captured in the ship report — no "by inspection" claims.

---

## Files Modified

- `outputs/whatsapp_sender.py` — add `_BLOCK_WA_TO_DIRECTOR` module constant + `_log_director_hard_blocked()` helper + hard-block guard in `send_whatsapp()`
- `outputs/email_alerts.py` — add `DIRECTOR_PERSONAL_EMAIL` + `DIRECTOR_EMAILS` set + `_BLOCK_EMAIL_TO_DIRECTOR` env constant + `_log_email_director_hard_blocked()` helper + hard-block guard in `_send_raw_full()`
- `tests/test_whatsapp_sender_director_hard_block.py` — NEW (5 tests)
- `tests/test_email_alerts_director_hard_block.py` — NEW (5 tests)

## Do NOT Touch

- `triggers/waha_webhook.py` — `_wa_reply()` already routes through `send_whatsapp()`; chokepoint catches all paths
- `outputs/whatsapp_sender.py` existing `_log_director_blocked()` + `whatsapp_blocked` action type — preserve for non-flagged kind-rejection audit trail
- `outputs/email_alerts.py` existing `_EMAIL_ALERTS_DISABLED` + alert wrappers — preserve coexisting upstream switch
- `DIRECTOR_PHONE_ROOTS` + `DIRECTOR_WA_ALLOWED_KINDS` — preserve all entries; both keep working when env flag flipped OFF
- Any other email recipient logic (`send_composed_email`, `send_manual_summary_email`) — the chokepoint at `_send_raw_full()` covers them transparently

## Quality Checkpoints

1. Both test files run green via literal `pytest` output (include in ship report).
2. `python3 -c "import py_compile; py_compile.compile('outputs/whatsapp_sender.py', doraise=True)"` + same for `outputs/email_alerts.py` — clean.
3. Brief's verification SQL queries return zero rows pre-merge (no false-positive history); post-deploy if guard ever fires, rows appear.
4. Module import of `outputs.whatsapp_sender` does not raise — the module-level `assert _phone_root(DIRECTOR_WHATSAPP) in DIRECTOR_PHONE_ROOTS` at line 44-47 must still pass (this brief adds no constant that conflicts).
5. Render env vars `BAKER_BLOCK_WA_TO_DIRECTOR=true` + `BAKER_BLOCK_EMAIL_TO_DIRECTOR=true` confirmed present post-merge (AI Head A sets pre-merge; verify via Render API GET /env-vars after deploy).
6. Devil's advocate: confirm no direct `/api/sendText` callers bypass `send_whatsapp()` chokepoint — `grep -rn "/api/sendText" outputs/ triggers/ orchestrator/ tools/` should show only `outputs/whatsapp_sender.py`.

## Verification SQL (post-deploy)

```sql
-- 1. Are the new audit rows reachable? (Schema sanity — no rows expected unless triggered)
SELECT COUNT(*) FROM baker_actions WHERE action_type IN ('whatsapp_hard_blocked', 'email_hard_blocked');

-- 2. If guard fires, what's the kind/source pattern?
SELECT
  action_type,
  payload->>'reason' AS reason,
  payload->>'env_flag' AS env_flag,
  COUNT(*) AS hits,
  MAX(created_at) AS last_seen
FROM baker_actions
WHERE action_type IN ('whatsapp_hard_blocked', 'email_hard_blocked')
GROUP BY 1, 2, 3
ORDER BY last_seen DESC
LIMIT 20;
```

---

## Ship-gate reviewer instructions

Gate-1 architect: confirm chokepoint pattern unchanged from BRIEF_BAKER_WA_DIRECTOR_FILTER_1 — same single-point-of-control philosophy applies; new flag is strictly additive.

Gate-2 security review: confirm (a) no log line in audit helpers contains full message body — only `[:200]` previews; (b) env flag defaults read correctly via the existing `("true", "1", "yes")` idiom; (c) `.strip().lower()` on email recipient is safe for non-ASCII (no `.encode()`).

Gate-4 code-reviewer: verify the three-way match in audit helpers — `action_type` string ↔ payload `reason` ↔ logger.warning text are internally consistent.

Reviewer must run `pytest` on both new test files and paste literal output in the ship report. "By inspection" → REQUEST_CHANGES.
