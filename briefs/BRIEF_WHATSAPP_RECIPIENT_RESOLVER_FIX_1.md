---
brief_id: BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1
version: 0.3
type: incident-fix
tier: A
authored_by: AI Head B (incident-containment lane)
authored_at: 2026-05-08T07:40Z
revised_at: 2026-05-08T08:05Z (v0.3 — folded combined reviewer verdict 3 HIGH + 3 MEDIUM + 2 LOW from code-architecture-reviewer + Architect Tier B brief-review meta)
incident: waha-mis-route-marcus-pisani (2026-05-08)
director_ratification_status: pending
recommended_target_b_code: B2 (per reviewer alignment)
recommended_merge_path: PR + /security-review pass (Tier-A merge, Lesson #52)
recommended_re_enable: manual gate on Director's verbatim "re-enable whatsapp"
estimated_loc: ~120 lines (resolver patch + asymmetric Director-fail-closed verdict + path_taken audit contract + Slack-alarm hook + 7 tests)
estimated_time: 90-120 min
gate_to_re_enable: this brief shipped + tested + recipient-id assertion green + 3-smoke verification + Director's verbatim "re-enable whatsapp"

revision_log:
  - v0.1 (2026-05-08T07:40Z) — initial draft
  - v0.2 (2026-05-08T07:55Z) — first reviewer fold (3 HIGH + 1 MEDIUM + 2 LOW)
  - v0.3 (2026-05-08T08:05Z) — combined code-architecture-reviewer + Architect Tier-B verdict folded:
      HIGH-1 (re-tightened) DIRECTOR_PHONE_ROOTS made explicit literal `{"41799605092", "447588690632"}` (Swiss + UK)
      HIGH-2 (re-tightened) end-to-end Test A2 PARAMETRIZED via pytest.mark.parametrize over DIRECTOR_PHONE_ROOTS so each phone-root gets its own assertion (B-code cannot hardcode only Swiss and have UK quietly fail-open)
      HIGH-3a Director-target sends always fail-closed on LID-DB error (no DEGRADED at highest stakes)
      HIGH-3b Non-Director sends with same-phone-root LID-DB error fall back to whatsapp_messages last-known + Slack LID_MAP_UNAVAILABLE alarm + audit + allow
      MEDIUM-4 whatsapp_lid_map schema verified at v0.3 authoring time via Baker MCP raw_query — verbatim output pasted in brief
      MEDIUM-5 grep evidence block embedded — `grep -rn "_resolve_to_active_chat_id\\|sendText\\|baker-waha" outputs/ orchestrator/ tools/` output baked in (no capabilities/ dir on this branch)
      MEDIUM-6 (NEW) baker_actions audit-row contract: every code path writes exactly ONE row with a `path_taken` field (one of: short_circuit_director / resolver_returned_clean / aborted_assertion_unsafe / lid_map_unavailable_fallback / lid_map_unavailable_director_fail_closed). New Test G asserts one-row-per-path with correct path_taken value.
      LOW-7 forward-fix-loosening already struck in v0.2 (reviewer reconfirmed)
      LOW-8 re-enable smoke now THREE tests: Director short-circuit + non-Director phone-root match + non-Director DEGRADED path with simulated LID-map unreachable
      LOW-9 PII text-preview tracked as separate brief BRIEF_BAKER_ACTIONS_PII_REDACTION_1 (already noted in v0.2)
---

# BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1 — Fix `_resolve_to_active_chat_id` PII-leak vector

## Context

On 2026-05-08 between 00:02:28Z and 02:02:26Z, three Baker T1-Alert WhatsApp messages destined for Director were silently mis-routed to counterparty Marcus Pisani's WhatsApp thread (`447468357311@s.whatsapp.net`). Item #3 contained family-financial PII (Lana €650k tax tracking). Director observed via iPhone screenshot ~07:20Z and ratified WhatsApp-outbound kill switch at 07:23Z (Render env-var flip on `srv-d6dgsbctgctc73f55730`: `WAHA_BASE_URL` → bogus host). Containment GREEN at 07:32Z. WhatsApp outbound now neutralized at the network layer.

**This brief fixes the underlying bug so WhatsApp outbound can be safely re-enabled.**

Full incident dossier: `~/baker-vault/_ops/incidents/2026-05-08-waha-mis-route-marcus-pisani.md`.

## Root cause (single commit, single function)

Bug introduced in commit `7a31ad6` (2026-05-05 13:41 CEST) — *"fix(whatsapp): route to active chat_id + audit every send to baker_actions"*.

`outputs/whatsapp_sender.py:20-66` `_resolve_to_active_chat_id(chat_id)`:

```python
cur.execute(
    "SELECT chat_id FROM whatsapp_messages "
    "WHERE sender = %s ORDER BY timestamp DESC LIMIT 1",
    (chat_id,),
)
```

**Intent:** if a contact migrated `@c.us` → `@lid`, find their new chat by looking at their most recent inbound message authored from the new address.

**Flaw:** the SQL finds the most recent message where the *sender column equals the requested chat_id*. For external contacts whose only WhatsApp footprint is their own thread, this works. For **the Director's own number** (`41799605092@c.us`), the WAHA-controlled session captures every message Director sends from his iPhone — across every conversation. So `sender = 41799605092@c.us` returns the most recent chat where Director was the *typing user*, regardless of whose chat thread it is. The resolver then routes Baker's send to that thread.

**Concrete trigger sequence on 2026-05-07/08:**
1. 2026-05-07 02:28Z — T1 alert fires → resolver runs → Director's most-recent send was a self-chat T1 alert from 00:28 → resolver returns Director's self-chat → routes correctly.
2. 2026-05-07 19:08:05Z — Director typed a message to Marcus on his iPhone. WAHA event captured: sender=Director, chat_id=Marcus.
3. 2026-05-08 00:02:28Z — T1 alert fires → resolver runs → most recent `sender=Director` row is now Marcus's chat → returns Marcus's chat → **leak #1**.
4. Two more leaks at 00:02:32 and 02:02:26 same morning, same mechanism.

The bug is **silent any time Director's last typed-on-iPhone WhatsApp message was to anyone other than himself**. From the audit log (`baker_actions` action_type=`whatsapp_send`, 2026-05-05 11:47 → 2026-05-08 02:02): 19 total sends, 3 mis-routed, 16 routed correctly by coincidence (Director's last-typed activity at the time of those sends happened to be self-chat).

## Files in scope

| File | What changes |
|------|--------------|
| `outputs/whatsapp_sender.py` | Patch `_resolve_to_active_chat_id`; add `_phone_root` + `_recipient_id_compatible` + `_lid_belongs_to_phone` + recipient-id assertion + LID-DB-error Slack alarm. |
| `tests/test_whatsapp_sender_lid.py` | Add 5 new tests. Existing 6 must continue to pass. |

**Resolver call-site grep (proven at v0.2 authoring time):** `_resolve_to_active_chat_id` is private (leading underscore) and called from exactly one site: `outputs/whatsapp_sender.py:140` inside `send_whatsapp()`. No external caller can bypass the recipient-id assertion. B-code re-runs the grep at PR time and includes output in PR description (acceptance criterion #8).

**Out of scope** for this brief (parked separately):
- Re-evaluating whether behaviour-driven resolution is the right architecture vs. static `whatsapp_lid_map` lookup. Director directive 2026-05-08 was "fix the resolver"; full architectural swap is a separate brief if needed.
- Recipient-id assertion library generalised across other channels (Slack, email). Possible follow-up.
- **PII in `baker_actions.payload.text_preview`** — current code stores 200 chars of message text in the audit row (`whatsapp_sender.py:91`). For the 3 leaked T1 alerts, this means Lana €650k tax content sits in PG. Separate brief required to either redact, hash, or bound retention. Tracked as `BRIEF_BAKER_ACTIONS_PII_REDACTION_1` (to be authored). Not in this brief's scope.

## Patch — `outputs/whatsapp_sender.py`

### Schema confirmed (queried via Baker MCP raw_query at v0.3 authoring 2026-05-08T08:05Z)

Verbatim output of `SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name='whatsapp_lid_map' ORDER BY ordinal_position`:

```
column_name    | data_type                | is_nullable
---------------+--------------------------+-------------
lid            | text                     | NO
phone          | text                     | YES
resolved_at    | timestamp with time zone | YES
source         | text                     | YES
```

Sample rows (from `SELECT * FROM whatsapp_lid_map LIMIT 3`):
```
lid: 189683338375284@lid     phone: 9607303930@c.us    resolved_at: 2026-04-15T05:51:24Z   source: api
lid: 180199815704588@lid     phone: 85263331730@c.us   resolved_at: 2026-04-28T13:37:41Z   source: api
lid: 93733517283579@lid      phone: 79255869729@c.us   resolved_at: 2026-05-05T15:45:12Z   source: api
```

**Critical:** `phone` is stored with the `@c.us` suffix, NOT bare digits. SQL parameter for the lookup is constructed as `f"{expected_phone_digits}@c.us"`. `phone` is also nullable; `_lid_belongs_to_phone` must treat NULL phone rows as non-matches (the `WHERE phone = %s` filter handles this naturally).

### Resolver call-site grep — evidence block (v0.3 authoring time)

```
$ grep -rn "_resolve_to_active_chat_id\|sendText\|baker-waha" outputs/ orchestrator/ tools/
outputs/whatsapp_sender.py:12:WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "https://baker-waha.onrender.com")
outputs/whatsapp_sender.py:20:def _resolve_to_active_chat_id(chat_id: str) -> str:
outputs/whatsapp_sender.py:140:    actual_chat_id = _resolve_to_active_chat_id(chat_id)
outputs/whatsapp_sender.py:151:                f"{WAHA_BASE_URL}/api/sendText",
$ ls -d capabilities/ 2>/dev/null || echo "(no capabilities/ dir on this branch)"
(no capabilities/ dir on this branch)
```

Single resolver call site at `outputs/whatsapp_sender.py:140`. Single sendText egress site at `outputs/whatsapp_sender.py:151`. No external caller bypasses the recipient-id assertion. B-code re-runs this exact grep at PR time and pastes output into PR description (acceptance criterion #8). If the grep at PR time surfaces any new caller, B-code escalates to AH2-T before merging.

### Change 1 — `_phone_root` helper + `DIRECTOR_PHONE_ROOTS` literal set (top-of-file)

Define BEFORE `_resolve_to_active_chat_id` so the resolver can use it. The set must be an explicit literal containing **both** Swiss and UK numbers (per reviewer HIGH-1 v0.3) — not derived dynamically from `DIRECTOR_WHATSAPP` alone, because Director's UK number `447588690632` is already in scope (per `~/.claude/CLAUDE.md` memory: "Baker dedicated number: +447588690632 (UK, Numero eSIM)") and must be pre-protected before activation rather than added in a follow-up patch.

```python
def _phone_root(chat_id: str) -> str:
    """Extract the phone-digit prefix from a WhatsApp chat id.
    `41799605092@c.us` → `41799605092`. `41799605092@s.whatsapp.net` → `41799605092`.
    `10110470463618@lid` → `10110470463618`. Empty string for unparseable input."""
    if not chat_id or "@" not in chat_id:
        return ""
    return chat_id.split("@", 1)[0]


# All phone digit-roots whose sends MUST short-circuit through the resolver
# and which trigger asymmetric Director-fail-closed handling on LID-DB error.
# Maintain as an explicit literal — adding a number is a one-line change here,
# and tests parametrized over this set automatically cover any addition.
DIRECTOR_PHONE_ROOTS = frozenset({
    "41799605092",   # Director Swiss primary (+41 79 960 50 92)
    "447588690632",  # Director-controlled Baker UK number (+44 7588 690632) — pre-protected
})

# Sanity assertion at module import: canonical DIRECTOR_WHATSAPP digits must
# be in the set. If someone changes one without the other, import fails loud.
assert _phone_root(DIRECTOR_WHATSAPP) in DIRECTOR_PHONE_ROOTS, (
    f"DIRECTOR_WHATSAPP {DIRECTOR_WHATSAPP!r} digit-root not in "
    f"DIRECTOR_PHONE_ROOTS {sorted(DIRECTOR_PHONE_ROOTS)!r} — fix the constants."
)
```

### Change 2 — `_resolve_to_active_chat_id` short-circuits Director on phone-root, not literal string

The literal-string check from v0.1 missed `41799605092@s.whatsapp.net` (which IS how Director's self-chat appears in the audit log — see incident timeline rows for 2026-05-07 02:28 / 00:28 with `actual_chat_id: 41799605092@s.whatsapp.net`). Phone-root match closes that hole and is future-proof for the UK number.

```python
def _resolve_to_active_chat_id(chat_id: str) -> str:
    """Route to the contact's most-recent active chat_id.

    Director's number is short-circuited on phone-digit match (handles
    @c.us, @s.whatsapp.net, future UK number, anything in DIRECTOR_PHONE_ROOTS).
    The behaviour-driven resolver below is correct only for *external* contacts
    whose own thread is the only place their number appears as sender.
    Director appears as sender across every chat he types in (WAHA captures
    his iPhone outbound), so the resolver must not run for him in any form.

    Why: 2026-05-08 incident — three T1 alerts mis-routed to a counterparty
    after Director typed a message to that counterparty on his iPhone. See
    `_ops/incidents/2026-05-08-waha-mis-route-marcus-pisani.md`.
    """
    if not chat_id or not chat_id.endswith("@c.us"):
        return chat_id
    if _phone_root(chat_id) in DIRECTOR_PHONE_ROOTS:
        return chat_id  # Hard short-circuit — never resolve any Director-owned address.
    # ... (rest of existing function unchanged)
```

### Change 3 — `_recipient_id_compatible` helper with **asymmetric Director-fail-closed**

Per reviewer HIGH-3 v0.3 split:

- **3a — Director-target sends always fail-closed on LID-DB error.** When the *requested* chat_id's phone-root is in `DIRECTOR_PHONE_ROOTS` and the LID-map cannot be reached to confirm a same-digit `@lid` actual, the resolver-returned address might still be a wrong-counterparty thread (the bug case). At Director's stake level, "we can't verify" must mean "we don't send." Director-target DEGRADED → UNSAFE.
- **3b — Non-Director sends fall back to the resolver's `whatsapp_messages` last-known active chat + Slack `LID_MAP_UNAVAILABLE` alarm + audit row + allow.** The risk being defended (mis-routing to a *different* phone-root) is not in play when the resolved address shares the requested phone-root; LID-map being momentarily unreachable for a same-digit `@lid` lookup doesn't justify silently aborting every legitimate Kira-style send.

Same phone-root → SAFE with no DB lookup (covers `@c.us` / `@s.whatsapp.net` / same-digit `@lid` cases). Different phone-root + actual is not `@lid` → UNSAFE (no plausible legitimate path). Different phone-root + actual IS `@lid` → require `whatsapp_lid_map` confirmation, with the asymmetric DEGRADED policy above.

```python
import enum

class _RecipientCheck(enum.Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"
    DEGRADED = "degraded"  # Non-Director only: LID-DB unreachable; allow + alarm.


def _recipient_id_compatible(requested: str, actual: str) -> _RecipientCheck:
    """Classify whether `actual` is a safe resolution of `requested`.

    Asymmetric Director-fail-closed:
    - If `_phone_root(requested) in DIRECTOR_PHONE_ROOTS`, any non-SAFE outcome
      (including DB-unreachable on @lid lookup) collapses to UNSAFE — Director-
      target sends never run in DEGRADED mode.
    - Non-Director targets follow the standard SAFE/UNSAFE/DEGRADED triage.

    SAFE — `requested == actual`, OR phone-roots match, OR `whatsapp_lid_map`
           confirms `actual` is a registered @lid for the requested phone.
    UNSAFE — phone-roots disagree AND actual is not @lid;
             OR phone-roots disagree AND LID-map says no row for this @lid;
             OR (Director-asymmetric) any DEGRADED-grade outcome when requested
             phone-root is in DIRECTOR_PHONE_ROOTS.
    DEGRADED — non-Director request AND phone-roots disagree AND actual IS @lid
               AND LID-map DB unreachable. Caller allows the send + Slack alarms
               #cockpit so the degraded path is loud, never silent.
    """
    if requested == actual:
        return _RecipientCheck.SAFE
    if _phone_root(requested) == _phone_root(actual):
        return _RecipientCheck.SAFE
    if not actual.endswith("@lid"):
        return _RecipientCheck.UNSAFE

    # Different phone-root, actual is @lid — must confirm via lid_map.
    lookup = _lid_belongs_to_phone(actual, _phone_root(requested))
    if lookup is True:
        return _RecipientCheck.SAFE
    if lookup is False:
        return _RecipientCheck.UNSAFE

    # lookup is None → DB error. Asymmetric Director-fail-closed kicks in.
    if _phone_root(requested) in DIRECTOR_PHONE_ROOTS:
        return _RecipientCheck.UNSAFE  # Director-target — never DEGRADED.
    return _RecipientCheck.DEGRADED
```

### Change 4 — `_lid_belongs_to_phone` returns Optional[bool] (None on DB error)

Crucially distinguishes "DB says no" (False — block) from "DB unreachable" (None — degrade-with-alarm). Schema baked in:

```python
def _lid_belongs_to_phone(lid_chat_id: str, expected_phone_digits: str) -> bool | None:
    """Look up whatsapp_lid_map. Returns True if the LID is registered for
    the given phone digits, False if explicitly absent, None on any DB error.

    Note: whatsapp_lid_map.phone is stored as `<digits>@c.us`, NOT bare digits.
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM whatsapp_lid_map "
                "WHERE lid = %s AND phone = %s LIMIT 1",
                (lid_chat_id, f"{expected_phone_digits}@c.us"),
            )
            row = cur.fetchone()
            cur.close()
            return row is not None  # True if row found, False if absent.
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return None  # DB-side exception → DEGRADED path.
        finally:
            store._put_conn(conn)
    except Exception:
        return None  # Connection unavailable → DEGRADED path.
```

### Change 5 — recipient-id assertion in `send_whatsapp` with `path_taken` audit contract

Per reviewer MEDIUM-6 v0.3: every code path writes **exactly one** `baker_actions` row, and that row's `payload.path_taken` field identifies which branch executed. This makes post-incident forensic reconstruction unambiguous (no more "did the leak go through the resolver path or the assertion path?").

`path_taken` enumeration (string literals; tests assert exact values):

| `path_taken` value | When |
|--------------------|------|
| `short_circuit_director` | Resolver short-circuited because `_phone_root(requested) in DIRECTOR_PHONE_ROOTS`. |
| `resolver_returned_clean` | Non-Director request, resolver ran, verdict was SAFE, HTTP POST attempted. |
| `aborted_assertion_unsafe` | Verdict UNSAFE (any cause); HTTP POST never attempted. |
| `lid_map_unavailable_fallback` | Non-Director request, verdict DEGRADED, send allowed + Slack alarm fired, HTTP POST attempted. |
| `lid_map_unavailable_director_fail_closed` | Director request, would have been DEGRADED, asymmetric policy collapsed to UNSAFE; HTTP POST never attempted. |

Implementation in `send_whatsapp` (after `actual_chat_id = _resolve_to_active_chat_id(chat_id)`):

```python
verdict = _recipient_id_compatible(requested_chat_id, actual_chat_id)
requested_is_director = _phone_root(requested_chat_id) in DIRECTOR_PHONE_ROOTS

# Determine path_taken first, then act consistently.
if verdict == _RecipientCheck.SAFE and requested_is_director and requested_chat_id == actual_chat_id:
    # Director-target where resolver short-circuited (actual unchanged from requested).
    path_taken = "short_circuit_director"
elif verdict == _RecipientCheck.UNSAFE and requested_is_director:
    # Director-target collapsed from DEGRADED-grade outcome to UNSAFE per asymmetric policy.
    # Distinguishable from a phone-root mismatch by examining the resolver inputs.
    path_taken = "lid_map_unavailable_director_fail_closed"
elif verdict == _RecipientCheck.UNSAFE:
    path_taken = "aborted_assertion_unsafe"
elif verdict == _RecipientCheck.DEGRADED:
    path_taken = "lid_map_unavailable_fallback"
else:  # SAFE, non-short-circuit
    path_taken = "resolver_returned_clean"

if verdict == _RecipientCheck.UNSAFE:
    error_message = (
        f"recipient-id assertion FAILED: requested={requested_chat_id} "
        f"resolved={actual_chat_id} path_taken={path_taken}"
    )
    logger.error(f"WhatsApp send aborted: {error_message}")
    _log_send_to_baker_actions(
        requested_chat_id=requested_chat_id,
        actual_chat_id=actual_chat_id,
        text=text,
        success=False,
        http_status=0,
        error_message=error_message,
        path_taken=path_taken,
    )
    return False

if verdict == _RecipientCheck.DEGRADED:
    # Non-Director only (Director DEGRADED has been collapsed to UNSAFE above).
    logger.warning(
        f"WhatsApp send DEGRADED: requested={requested_chat_id} "
        f"resolved={actual_chat_id} — LID-map DB unreachable, allowing"
    )
    try:
        _alarm_slack_lid_db_degraded(requested_chat_id, actual_chat_id)
    except Exception as e:
        logger.warning(f"Slack alarm dispatch failed (non-fatal): {e}")
    # Fall through to HTTP POST. The audit row written below records path_taken.

# verdict == SAFE OR DEGRADED-with-allow → proceed to HTTP POST, then audit with path_taken.
```

The existing `_log_send_to_baker_actions` helper gains a new keyword argument `path_taken: str` and inserts it into the JSONB `payload`. Backward-compat: if a future caller forgets to pass `path_taken`, default to `"unknown"` and emit a logger.warning so the gap is visible in logs. (Tests assert `path_taken` is always present in audit rows.)

### Change 6 — `_alarm_slack_lid_db_degraded` helper

Lightweight Slack post via `outputs.slack_notifier.post_to_channel` to `#cockpit`. Non-fatal; never raises.

```python
def _alarm_slack_lid_db_degraded(requested: str, actual: str) -> None:
    """Alarm Slack #cockpit when recipient-id assertion runs in DEGRADED mode
    (LID-map DB unreachable, allowed-but-could-not-verify). Non-fatal."""
    from outputs.slack_notifier import post_to_channel
    from config.settings import config
    msg = (
        f"⚠️ Baker WhatsApp recipient-id assertion DEGRADED — "
        f"requested={requested} resolved={actual}. LID-map DB unreachable; "
        f"send was allowed. Investigate whatsapp_lid_map / Postgres health."
    )
    channel = config.slack.cockpit_channel_id
    post_to_channel(channel, msg, unfurl_links=False, unfurl_media=False)
```

## Test coverage

### Tests that must continue to pass (6)

`test_resolve_returns_lid_when_phone_has_mapping`, `test_resolve_returns_input_when_no_mapping`, `test_resolve_passes_through_non_cus_chat_ids`, `test_resolve_fails_open_on_db_error`, `test_send_uses_resolved_chat_id_in_waha_call`, `test_send_audits_failure_with_response_body` — existing tests in `tests/test_whatsapp_sender_lid.py`. **No regressions allowed.**

### New tests (7) — all must pass

**Test A — Director short-circuit holds at resolver level for every form in DIRECTOR_PHONE_ROOTS:**

```python
import pytest

@pytest.mark.parametrize("director_root", sorted(sender.DIRECTOR_PHONE_ROOTS))
@pytest.mark.parametrize("suffix", ["@c.us", "@s.whatsapp.net"])
def test_director_recipient_never_resolves_elsewhere_for_any_director_root(director_root, suffix):
    """Resolver-level regression for 2026-05-08 incident, parametrized over
    every digit-root in DIRECTOR_PHONE_ROOTS and every chat-id form that
    Director's number can take. Adding a new Director root to the set
    automatically covers a new test instance — no per-root hardcoding.

    Even if whatsapp_messages contains rows where sender=Director-form-X and
    chat_id=somebody-else's-thread, _resolve_to_active_chat_id must short-
    circuit and return the input unchanged.
    """
    # Mock store returns Marcus's chat_id as "most recent for sender=Director"
    # — this would be the leak path if the short-circuit didn't fire.
    store, _, _ = _mock_store(("447468357311@s.whatsapp.net",))
    form = f"{director_root}{suffix}" if suffix == "@c.us" else f"{director_root}{suffix}"
    if not form.endswith("@c.us"):
        # Resolver only runs for @c.us inputs; @s.whatsapp.net is passthrough already.
        # Both forms must end up unchanged at the public boundary.
        assert sender._resolve_to_active_chat_id(form) == form
        return
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        result = sender._resolve_to_active_chat_id(form)
        assert result == form, (
            f"Director form {form!r} resolved to {result!r} — "
            f"short-circuit failed for root {director_root!r}; bug recurs."
        )
```

**Test A2 — END-TO-END parametrized over DIRECTOR_PHONE_ROOTS (reviewer HIGH-2 v0.3):**

```python
@pytest.mark.parametrize("director_root", sorted(sender.DIRECTOR_PHONE_ROOTS))
def test_e2e_send_never_posts_director_traffic_to_a_counterparty_for_any_director_root(director_root):
    """End-to-end regression: poison whatsapp_messages with sender=Director-root +
    chat_id=Marcus, then call send_whatsapp(text, "<root>@c.us"). Assert the HTTP
    POST chatId carries a Director-owned phone-root, NOT Marcus's chat.

    Parametrized over DIRECTOR_PHONE_ROOTS so adding the UK number (or any future
    addition) automatically gets its own green assertion. Without parametrization,
    a B-code could hardcode the Swiss number, this test would still pass, and the
    UK-number recurrence would ship undetected — exactly the failure mode the
    reviewer flagged.
    """
    requested = f"{director_root}@c.us"
    # Resolver query path returns Marcus — the poison.
    store, _, _ = _mock_store(("447468357311@s.whatsapp.net",))
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        with patch.object(sender, "_log_send_to_baker_actions"):
            with patch("httpx.Client") as MockClient:
                client_inst = MockClient.return_value.__enter__.return_value
                resp = MagicMock()
                resp.is_success = True
                resp.status_code = 200
                client_inst.post.return_value = resp
                ok = sender.send_whatsapp(text="T1 alert body", chat_id=requested)

    assert ok is True
    posted = client_inst.post.call_args
    posted_chat_id = posted.kwargs["json"]["chatId"]
    assert sender._phone_root(posted_chat_id) in sender.DIRECTOR_PHONE_ROOTS, (
        f"send_whatsapp routed Director-root {director_root!r} traffic to a non-Director "
        f"chat (chatId={posted_chat_id!r}) — bug would recur in production."
    )
    assert "447468357311" not in posted_chat_id, (
        f"Marcus's digits found in posted chat_id={posted_chat_id!r} for root {director_root!r}."
    )
```

**Test C — recipient-id assertion blocks UNSAFE resolution (non-Director phone-root mismatch):**

```python
def test_send_aborts_when_resolved_chat_id_has_different_phone_root_and_no_lid_match():
    """Defence-in-depth: non-Director request where resolver returns a wrong
    chat_id and the LID-map explicitly says no match. send_whatsapp must NOT
    POST to WAHA. Audit row records path_taken='aborted_assertion_unsafe'."""
    store, _, _ = _mock_store(("447468357311@s.whatsapp.net",))  # Marcus, not @lid
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        with patch.object(sender, "_log_send_to_baker_actions") as mock_audit:
            with patch("httpx.Client") as MockClient:
                ok = sender.send_whatsapp(text="alert", chat_id="99999999999@c.us")
                assert ok is False
                MockClient.return_value.__enter__.return_value.post.assert_not_called()
                mock_audit.assert_called_once()
                kwargs = mock_audit.call_args.kwargs
                assert kwargs["success"] is False
                assert kwargs["path_taken"] == "aborted_assertion_unsafe"
                assert "recipient-id assertion FAILED" in kwargs["error_message"]
```

**Test D — Non-Director DEGRADED path: LID-DB unreachable, send proceeds, Slack alarm fires (HIGH 3b):**

```python
def test_non_director_lid_db_unreachable_allows_send_alarms_slack_and_records_path_taken():
    """Non-Director request, resolver returns @lid for same-or-different phone-root,
    LID-map DB unreachable. Per HIGH 3b: send proceeds (no silent abort for Kira-
    style legitimate @lid contacts), Slack #cockpit alarm fires, audit row records
    path_taken='lid_map_unavailable_fallback'."""
    store, _, _ = _mock_store(("10110470463618@lid",))  # Kira's @lid, different digit-root
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        with patch.object(sender, "_lid_belongs_to_phone", return_value=None):  # DB error
            with patch.object(sender, "_alarm_slack_lid_db_degraded") as mock_alarm:
                with patch.object(sender, "_log_send_to_baker_actions") as mock_audit:
                    with patch("httpx.Client") as MockClient:
                        client_inst = MockClient.return_value.__enter__.return_value
                        resp = MagicMock()
                        resp.is_success = True
                        resp.status_code = 200
                        client_inst.post.return_value = resp
                        ok = sender.send_whatsapp(text="hi Kira", chat_id="46761387271@c.us")
    assert ok is True
    # Send proceeded.
    MockClient.return_value.__enter__.return_value.post.assert_called_once()
    # Slack LID_MAP_UNAVAILABLE alarm fired.
    mock_alarm.assert_called_once()
    # Audit row records the fallback path.
    mock_audit.assert_called_once()
    assert mock_audit.call_args.kwargs["path_taken"] == "lid_map_unavailable_fallback"
```

**Test E — Director DEGRADED-grade collapses to UNSAFE (HIGH 3a — asymmetric fail-closed):**

```python
@pytest.mark.parametrize("director_root", sorted(sender.DIRECTOR_PHONE_ROOTS))
def test_director_target_lid_db_unreachable_collapses_to_fail_closed(director_root):
    """When the requested chat_id's phone-root is in DIRECTOR_PHONE_ROOTS and the
    LID-map lookup is unreachable for an @lid resolution, the asymmetric policy
    must collapse to UNSAFE (no DEGRADED at Director's stake level). HTTP POST
    must NOT fire. Audit row must record
    path_taken='lid_map_unavailable_director_fail_closed'.

    This shouldn't normally happen because Director's resolver short-circuits at
    line 1, BUT defence-in-depth: if the short-circuit is ever bypassed by future
    refactor, the assertion layer must still fail closed for Director."""
    requested = f"{director_root}@c.us"
    # Force a path through the assertion: resolver returns a different-root @lid.
    # (In practice the short-circuit prevents this; we deliberately mock around it.)
    with patch.object(sender, "_resolve_to_active_chat_id", return_value="999999999999@lid"):
        with patch.object(sender, "_lid_belongs_to_phone", return_value=None):  # DB error
            with patch.object(sender, "_alarm_slack_lid_db_degraded") as mock_alarm:
                with patch.object(sender, "_log_send_to_baker_actions") as mock_audit:
                    with patch("httpx.Client") as MockClient:
                        ok = sender.send_whatsapp(text="director alert", chat_id=requested)
    assert ok is False
    MockClient.return_value.__enter__.return_value.post.assert_not_called()
    # No DEGRADED alarm — Director path collapsed before fallback fires.
    mock_alarm.assert_not_called()
    # Audit row records the Director-specific fail-closed path.
    mock_audit.assert_called_once()
    assert mock_audit.call_args.kwargs["path_taken"] == "lid_map_unavailable_director_fail_closed"
```

**Test F — phone-root extraction edge cases:**

```python
def test_phone_root_handles_edge_cases():
    assert sender._phone_root("41799605092@c.us") == "41799605092"
    assert sender._phone_root("41799605092@s.whatsapp.net") == "41799605092"
    assert sender._phone_root("10110470463618@lid") == "10110470463618"
    assert sender._phone_root("") == ""
    assert sender._phone_root("not-a-chat-id") == ""
    assert sender._phone_root("@c.us") == ""

def test_director_phone_roots_set_includes_both_swiss_and_uk():
    """Sanity: explicit literal contains both numbers per reviewer HIGH-1 v0.3."""
    assert "41799605092" in sender.DIRECTOR_PHONE_ROOTS
    assert "447588690632" in sender.DIRECTOR_PHONE_ROOTS
    assert sender._phone_root(sender.DIRECTOR_WHATSAPP) in sender.DIRECTOR_PHONE_ROOTS
```

**Test G — `path_taken` audit-row contract: every code path writes EXACTLY ONE row with the right value (reviewer MEDIUM-6):**

```python
@pytest.mark.parametrize("scenario,expected_path", [
    # (resolver_return, lid_lookup_return, requested, expected_path_taken)
    ("director_short_circuit",   "short_circuit_director"),
    ("clean_resolver_return",    "resolver_returned_clean"),
    ("phone_root_mismatch",      "aborted_assertion_unsafe"),
    ("non_director_lid_db_err",  "lid_map_unavailable_fallback"),
    ("director_lid_db_err",      "lid_map_unavailable_director_fail_closed"),
])
def test_path_taken_audit_row_written_exactly_once_per_scenario(scenario, expected_path):
    """Every code path writes exactly ONE baker_actions row whose payload.path_taken
    matches the expected value. No path writes zero rows. No path writes >1 row.
    Forensic reconstruction post-incident is unambiguous.

    Test wires each scenario's mocks (resolver return, lid_belongs return,
    requested chat_id) and patches _log_send_to_baker_actions to capture
    invocations. Implementation in B-code: parametrize the scenarios with
    concrete mock setups."""
    captured_audits = []
    def capture(**kwargs):
        captured_audits.append(kwargs)
    with patch.object(sender, "_log_send_to_baker_actions", side_effect=capture):
        with patch("httpx.Client") as MockClient:
            client_inst = MockClient.return_value.__enter__.return_value
            resp = MagicMock()
            resp.is_success = True
            resp.status_code = 200
            client_inst.post.return_value = resp
            # B-code: switch on `scenario` to set up resolver mock, lid mock, and
            # the chat_id passed to send_whatsapp. See the scenario→fixtures table
            # in the implementation; each fixture must produce expected_path.
            _drive_scenario(sender, scenario)  # B-code-implemented helper
    assert len(captured_audits) == 1, f"Scenario {scenario!r} wrote {len(captured_audits)} audit rows; expected 1."
    assert captured_audits[0]["path_taken"] == expected_path, (
        f"Scenario {scenario!r}: audit row path_taken={captured_audits[0]['path_taken']!r} "
        f"expected={expected_path!r}."
    )
```

## Rollback plan

If the patch lands and any send fails (e.g. recipient-id assertion blocks legitimate sends due to LID-map gaps not yet covered):

1. **Fast rollback (env-var, no redeploy needed):** keep `WAHA_BASE_URL` scrambled — kill stays in effect, no further leaks possible. Zero-cost.
2. **Code rollback:** `git revert <patch-commit>` on `main` → Render auto-deploys → restores prior buggy code, but `WAHA_BASE_URL` is still scrambled, so still safe.

**No "loosen the assertion" forward-fix path.** Reviewer verdict v0.2 explicitly removed this option — loosening the recipient-id assertion to log+allow on LID-map-miss regresses the safety guarantee that produced this brief. If LID-map gaps surface as a real problem, the right move is to *populate the LID-map* (already 1,018 rows; populate more from inbound message history), not to weaken the assertion.

## Implementation acceptance criteria

For B-code merge to proceed:

1. All 6 existing `test_whatsapp_sender_lid.py` tests pass.
2. All 7 new tests pass (Test A short-circuit parametrized over `DIRECTOR_PHONE_ROOTS`, Test A2 end-to-end parametrized, Test C UNSAFE-block, Test D non-Director DEGRADED, Test E Director-asymmetric fail-closed parametrized, Test F phone-root edges + DIRECTOR_PHONE_ROOTS literal sanity, Test G path_taken contract parametrized over 5 scenarios). Total parametrized test instances: ≥18 (2 forms × 2 roots for A; 2 roots for A2; 2 roots for E; 5 scenarios for G; plus C/D/F flat).
3. `python3 -c "import py_compile; py_compile.compile('outputs/whatsapp_sender.py', doraise=True)"` clean.
4. PR description includes verbatim copy of **Test A, Test A2, AND Test E** code in the test plan checklist (proves resolver-level + end-to-end + asymmetric Director-fail-closed regression tests were authored, parametrized over `DIRECTOR_PHONE_ROOTS`).
5. Patch does NOT touch `WAHA_BASE_URL`, `WHATSAPP_API_KEY`, or `DIRECTOR_WHATSAPP` constants. Patch DOES add `DIRECTOR_PHONE_ROOTS` (explicit literal `frozenset({"41799605092", "447588690632"})`) adjacent to `DIRECTOR_WHATSAPP`, plus the module-import sanity assert.
6. Patch does NOT remove existing audit logging (`_log_send_to_baker_actions`). Patch DOES extend it with a `path_taken: str` keyword argument; existing `payload` JSONB structure preserved + augmented (no schema migration required — JSONB).
7. `/security-review` skill PASS on the PR diff (Lesson #52 — Tier-A merges).
8. **PR description includes output of the exact grep:**
   ```
   grep -rn "_resolve_to_active_chat_id\|sendText\|baker-waha" outputs/ orchestrator/ tools/
   ```
   Expected output: exactly one resolver call site at `outputs/whatsapp_sender.py:140` (`send_whatsapp` interior); exactly one sendText egress at `:151`. Plus the `WAHA_BASE_URL` constant declaration at `:12` and the function definition at `:20`. **No other matches** in `outputs/`, `orchestrator/`, or `tools/`. If grep surfaces any new caller, B-code escalates to AH2-T before merging — the recipient-id assertion design assumes single-callsite gating.
9. PR description embeds the `whatsapp_lid_map` schema verbatim per the schema block in this brief, and confirms `_lid_belongs_to_phone` SQL uses `f"{expected_phone_digits}@c.us"` for the `phone =` parameter.
10. (NEW v0.3) PR description lists which `path_taken` value covers which code branch and confirms Test G parametrizes over all 5 paths. No code branch may write zero or >1 audit rows for a given send invocation.

## Re-enable sequence (after merge)

1. B-code merges PR; Render auto-deploys baker-master.
2. AH2-T verifies build green via `/healthz` poll.
3. AH2-T flips `WAHA_BASE_URL` back to `https://baker-waha.onrender.com` via Render MCP merge mode.
4. Auto-deploy fires; ~3-5 min.
5. **Smoke test #1 — Director short-circuit path:** `send_whatsapp(text="re-enable smoke 1/3", chat_id=DIRECTOR_WHATSAPP)`. Assert: audit row `path_taken == "short_circuit_director"`, `actual_chat_id` phone-root ∈ `DIRECTOR_PHONE_ROOTS`. Director observes message arrived in his self-chat.
6. **Smoke test #2 — non-Director phone-root match path:** `send_whatsapp(text="re-enable smoke 2/3", chat_id="9999999999@c.us")` (deliberately invalid phone number, distinct phone-root from any real contact). Assert: recipient-id assertion does NOT block (phone-roots match by reflexivity); WAHA returns 422 / chat-not-found; audit row `path_taken == "resolver_returned_clean"`, `success=False`, `http_status=422`. Proves resolver/assertion don't over-block legitimate sends.
7. **Smoke test #3 (v0.3 NEW per LOW-8) — non-Director DEGRADED path with simulated LID-map outage:** AH2-T temporarily disables LID-map access (e.g., flip a feature flag `BAKER_WHATSAPP_LID_MAP_FORCE_ERROR=true` if a B-code-supplied flag exists, or simulate via inserting a synthetic poisoned row into `whatsapp_messages` + re-running send). Then `send_whatsapp(text="re-enable smoke 3/3", chat_id="<some-non-Director-@c.us>")`. Assert: send proceeds (audit row `path_taken == "lid_map_unavailable_fallback"`), Slack `#cockpit` receives a `LID_MAP_UNAVAILABLE` alarm post (visible to AH2-T). Then immediately undo the simulated outage. **If this smoke is operationally invasive in production**, B-code may instead provide a unit-test-equivalent run via `pytest` covering the live audit-row write to `baker_actions` against a test PG branch — surface to AH2-T at PR time which path is in scope.
8. **Verification window:** observe baker_actions for 10 min post-flip. Acceptance: smoke #1 path_taken `short_circuit_director`, smoke #2 path_taken `resolver_returned_clean` + WAHA 422, smoke #3 path_taken `lid_map_unavailable_fallback` + Slack alarm fired exactly once, zero unexpected sends, zero `lid_map_unavailable_director_fail_closed` rows (Director path should never DEGRADE in production).
9. Surfaces "WhatsApp re-enabled, all 3 smoke tests green" PL paste-block to Director for awareness.

**Director's verbatim phrase required to authorize step 3 above:** `"re-enable whatsapp"`.

## PL ship-report instruction (for B-code)

End your chat ship report with a fenced PL paste-block per SKILL.md §"PL ship-report contract". PL paste-block topic: `incident/waha-mis-route-marcus-pisani-fix`.
