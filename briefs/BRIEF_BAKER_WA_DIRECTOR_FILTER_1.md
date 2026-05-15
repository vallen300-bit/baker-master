# BRIEF: BAKER_WA_DIRECTOR_FILTER_1 — Allowlist + chokepoint enforcement for Baker → Director WhatsApp

## Context

Director directive 2026-05-15 ~18:00Z (this session): "I stopped even reading messages now from Baker on WhatsApp. ... Why do I need to know this?" Phase A killed the scheduler-watchdog WA alert; Director wants the principle generalised: **Baker NEVER WhatsApps Director about its own internal infrastructure.** Counterparty / legal / deadline / VIP / financial signals continue. Anything else is silenced at the chokepoint.

Today there are 10+ `send_whatsapp(...)` call sites across the repo. Phase A removed one. Several others (sentinel_health, embedded_scheduler hot_md nudge, action_handler alerts, etc.) still default to Director's number. Need a structural fix that survives future caller additions without re-education.

## Estimated time: 2-3h
## Complexity: Medium (single-concept, 10+ call sites to audit)
## Prerequisites: None

---

## Fix: kind= chokepoint at `send_whatsapp()`, Director-bound calls require allowlisted kind

### Problem

`outputs/whatsapp_sender.py:266` — `def send_whatsapp(text: str, chat_id: str = DIRECTOR_WHATSAPP) -> bool` — accepts arbitrary text with no classification. Every caller can implicitly push to Director's number (default chat_id). Result: 426 watchdog WA sends in 3 days buried the Steininger / ORF alert. Today's specific spam is fixed; the pattern that allowed it isn't.

### Implementation

**Step 1 — Add `kind=` parameter + allowlist enforcement to `outputs/whatsapp_sender.py`**

`outputs/whatsapp_sender.py:266` — modify signature + add chokepoint:

```python
# Director-facing allowlist. Add new values only after Director ratification.
# Anchor: Director directive 2026-05-15 — "Baker NEVER WhatsApps me about its own
# internal infrastructure. Counterparty / legal / deadline / VIP / financial only."
DIRECTOR_WA_ALLOWED_KINDS = frozenset({
    "counterparty",     # AO / Hagenauer / Cupial / MOHG action or message
    "legal_threat",     # Steininger-ORF type media or legal escalation
    "deadline",         # Hard deadlines requiring Director action
    "vip_signal",       # VIP contact event (call, email, message) needing decision
    "financial",        # Investment / capital call / payment / banking event
    "director_inbound", # Reply to Director's own outbound WA (user-initiated thread)
})

class _WADirectorBlocked(Exception):
    """Raised when a Director-bound send is missing or has a non-allowlisted kind."""


def send_whatsapp(
    text: str,
    chat_id: str = DIRECTOR_WHATSAPP,
    *,
    kind: str | None = None,
) -> bool:
    """Send WhatsApp via WAHA. Director-bound calls require an allowlisted kind=.

    For non-Director chat_id (counterparties, replies, internal numbers), kind=
    is not required — filter only applies when chat_id == DIRECTOR_WHATSAPP.

    Returns False (and logs at WARN) if a Director-bound call has a missing or
    non-allowlisted kind. Does NOT raise — caller paths must continue.
    """
    if chat_id == DIRECTOR_WHATSAPP:
        if kind is None or kind not in DIRECTOR_WA_ALLOWED_KINDS:
            logger.warning(
                "WA_DIRECTOR_BLOCKED: dropped Director-bound send. "
                "kind=%r (allowed=%s). text_preview=%r",
                kind,
                sorted(DIRECTOR_WA_ALLOWED_KINDS),
                text[:120],
            )
            # Log to baker_actions for audit + later review
            try:
                from memory.store_back import SentinelStoreBack
                store = SentinelStoreBack._get_global_instance()
                store.log_action(
                    action_type="whatsapp_blocked",
                    payload={
                        "reason": "director_kind_not_allowlisted",
                        "kind": kind,
                        "text_preview": text[:200],
                    },
                    trigger_source="whatsapp_sender",
                    success=False,
                )
            except Exception as audit_err:
                logger.warning("WA_DIRECTOR_BLOCKED audit log failed: %s", audit_err)
            return False
    # ... existing send logic unchanged below ...
```

**Step 2 — Audit + tag each existing `send_whatsapp(` call site**

For each of the 10+ call sites enumerated below, OPEN the file at the cited line, READ the trigger condition, then either:
- **Tag with `kind="<allowlisted-value>"`** if the alert is Director-relevant
- **Replace with `logger.warning(...)`** if the alert is infra-only (mirror Phase A pattern)
- **Leave unchanged** if the call is to a non-Director chat_id

Call site inventory (run `grep -rn "send_whatsapp\|outputs.whatsapp_sender" --include="*.py" .` to refresh):

| File:line | Current trigger | Classification | Action |
|---|---|---|---|
| `outputs/whatsapp_sender.py:266` | canonical sender | n/a — this is the chokepoint | modify signature + add allowlist |
| `kbl/whatsapp.py:27-29` | KBL wrapper around sender | passthrough | add `kind=` passthrough param |
| `memory/store_back.py:4450-4454` | (read code to determine trigger) | classify | tag or replace |
| `triggers/sentinel_health.py:576-577` | sentinel health alert | **infra_only** | replace with `logger.warning` |
| `triggers/sentinel_health.py:671-672` | WAHA silent alert | **infra_only** | replace with `logger.warning` |
| `triggers/sentinel_health.py:754-755` | WAHA session down alert | **infra_only** | replace with `logger.warning` |
| `triggers/embedded_scheduler.py:1134-1145` | hot_md weekly nudge | likely **deadline** | tag `kind="deadline"` after reading trigger |
| `triggers/email_trigger.py:409-416` | (read code) | classify | tag or replace |
| `triggers/email_trigger.py:1135-1144` | (read code) | classify | tag or replace |
| `triggers/waha_webhook.py:152-153` | reply in WAHA flow | non-Director chat_id likely | leave OR confirm chat_id and tag if Director |
| `triggers/waha_webhook.py:805-806` | reply in WAHA flow | non-Director chat_id likely | leave OR confirm chat_id and tag if Director |
| `orchestrator/decision_engine.py:749-750` | decision-engine agent alert | classify | tag or replace |
| `orchestrator/chain_runner.py:619-622` | chain output | classify | tag or replace |
| `orchestrator/initiative_engine.py:512-513` | initiative alert | classify | tag or replace |
| `orchestrator/convergence_detector.py:390-395` | convergence alert | classify | tag or replace |
| `orchestrator/action_handler.py:1605-1610` | action alert (explicit chat_id) | non-Director chat_id | leave unchanged |

**Decision rule when classifying:** if the alert is about an ENTITY OUTSIDE Baker (counterparty, deal, deadline, VIP, money), it gets a `kind=` tag. If the alert is about BAKER ITSELF (scheduler, queue, WAHA session, deploy, DB, sentinel), it's `infra_only` — replace with `logger.warning`.

Each row above must end with a one-line justification in the ship report (e.g., `email_trigger.py:1144 → kind="counterparty"; trigger is incoming Gmail from VIP contact, drafts a WA forward`).

**Step 3 — Pre-merge guard (CI check)**

Add `scripts/check_wa_director_kinds.sh`:

```bash
#!/usr/bin/env bash
# Fail if any send_whatsapp() call that could resolve to chat_id=DIRECTOR_WHATSAPP
# (i.e., uses the default chat_id) is missing a kind= keyword.
#
# Heuristic: a send_whatsapp(...) call without an explicit chat_id= AND without
# a kind= is suspect. False positives are acceptable; the cost is adding a kind=
# (or chat_id=) to the call.
set -euo pipefail

# Grep all callers, exclude tests + the canonical sender itself.
SUSPECT="$(grep -rn 'send_whatsapp(' --include='*.py' \
    --exclude-dir=tests --exclude-dir=.venv* \
    /Users/dimitry/bm-aihead2 \
  | grep -v 'outputs/whatsapp_sender.py:266' \
  | grep -v 'def send_whatsapp' \
  | grep -v 'import send_whatsapp' \
  | grep -v 'from outputs.whatsapp_sender' \
  | grep -v 'chat_id=' \
  | grep -v 'kind=' \
  || true)"

if [ -n "$SUSPECT" ]; then
    echo "ERROR: Director-defaulting send_whatsapp() calls missing kind=:" >&2
    echo "$SUSPECT" >&2
    echo "" >&2
    echo "Add an explicit kind=\"<allowlisted-value>\" or chat_id=\"<non-Director>\"." >&2
    echo "Allowlist: counterparty / legal_threat / deadline / vip_signal / financial / director_inbound" >&2
    exit 1
fi
echo "OK: all send_whatsapp() callers tag kind= or non-Director chat_id."
```

Wire into pre-push hook at `.githooks/pre-push` (append line: `bash scripts/check_wa_director_kinds.sh || exit 1`).

**Step 4 — Tests**

`tests/test_wa_director_filter.py` (NEW):

```python
"""BAKER_WA_DIRECTOR_FILTER_1 — Director-bound send rejection."""
from unittest.mock import patch, MagicMock
import pytest

from outputs.whatsapp_sender import send_whatsapp, DIRECTOR_WHATSAPP, DIRECTOR_WA_ALLOWED_KINDS


@patch("outputs.whatsapp_sender._post_to_waha")  # whatever the actual WAHA HTTP fn is named
def test_director_send_without_kind_blocked(mock_post):
    """No kind= + Director chat_id → blocked, returns False, no HTTP call."""
    result = send_whatsapp("test alert", chat_id=DIRECTOR_WHATSAPP)
    assert result is False
    mock_post.assert_not_called()


@patch("outputs.whatsapp_sender._post_to_waha")
def test_director_send_with_infra_kind_blocked(mock_post):
    """kind='scheduler' (not in allowlist) + Director chat_id → blocked."""
    result = send_whatsapp("test", chat_id=DIRECTOR_WHATSAPP, kind="scheduler")
    assert result is False
    mock_post.assert_not_called()


@patch("outputs.whatsapp_sender._post_to_waha", return_value=True)
def test_director_send_with_allowlisted_kind_allowed(mock_post):
    """kind='counterparty' + Director chat_id → sends."""
    result = send_whatsapp("AO sent a thing", chat_id=DIRECTOR_WHATSAPP, kind="counterparty")
    assert result is True
    mock_post.assert_called_once()


@patch("outputs.whatsapp_sender._post_to_waha", return_value=True)
def test_non_director_chat_id_kind_optional(mock_post):
    """Other chat_id → no kind required."""
    result = send_whatsapp("test", chat_id="41XXXXXXXXX@c.us")
    assert result is True
    mock_post.assert_called_once()


def test_allowlist_contents():
    """Allowlist contains exactly the 6 ratified categories."""
    assert DIRECTOR_WA_ALLOWED_KINDS == frozenset({
        "counterparty", "legal_threat", "deadline",
        "vip_signal", "financial", "director_inbound"
    })
```

### Key Constraints

- DO NOT remove the `send_whatsapp` function — only modify signature + add chokepoint.
- DO NOT raise on a block; return False so callers (which already handle False gracefully per Phase A precedent) keep working.
- DO NOT change behavior for non-Director chat_ids; allowlist applies only to `chat_id == DIRECTOR_WHATSAPP`.
- DO log every block to `baker_actions` (`action_type='whatsapp_blocked'`) so AH1/AH2 can review and add new `kind=` values if a real signal gets dropped.
- The pre-merge CI guard is heuristic (grep-based, no AST parse) — false positives are OK; just add `kind=` or `chat_id=`.

### Verification

1. `python3 -c "import py_compile; py_compile.compile('outputs/whatsapp_sender.py', doraise=True)"` clean.
2. `pytest tests/test_wa_director_filter.py -v` — 5 passed (literal in ship report).
3. `bash scripts/check_wa_director_kinds.sh` exits 0 after all 10+ call sites are tagged.
4. Post-merge 24h: query `SELECT action_type, COUNT(*) FROM baker_actions WHERE action_type IN ('whatsapp_send','whatsapp_blocked') AND created_at > NOW() - INTERVAL '24 hours' GROUP BY 1` — paste result. Expected: most rows in `whatsapp_send` are allowlisted kinds; `whatsapp_blocked` rows surface any caller still missing `kind=` (those become follow-up cleanups).
5. Ship report MUST include the audit table (Step 2) with per-row classification justification.

## Files Modified

- `outputs/whatsapp_sender.py` — add `DIRECTOR_WA_ALLOWED_KINDS`, modify `send_whatsapp` signature, chokepoint logic
- `kbl/whatsapp.py` — passthrough `kind=` to underlying sender
- ~10 caller files (each tagged with `kind=` or replaced with `logger.warning`)
- `scripts/check_wa_director_kinds.sh` (NEW)
- `.githooks/pre-push` — append the check script
- `tests/test_wa_director_filter.py` (NEW)

## Do NOT Touch

- WAHA webhook endpoint logic (`triggers/waha_webhook.py` — only its outbound `send_whatsapp` calls if Director-bound)
- The `DIRECTOR_WHATSAPP` constant (canonical phone number)
- Any non-WhatsApp output paths (email, Slack, etc. — out of scope)

## Ship gate

Literal pytest output + literal `bash scripts/check_wa_director_kinds.sh` exit-0 output + Step 2 audit table in ship report.

## Trigger class

MEDIUM — touches an external-surface helper (`send_whatsapp` is the WAHA boundary) + edits >10 files. Mandatory 2nd-pass code-reviewer per `_ops/skills/ai-head/SKILL.md` §"Code-reviewer 2nd-pass Protocol" trigger #4 (external-surface endpoints + MCP/security perimeter).

## Builder

**B3** (free; CODE_3_PENDING COMPLETE on CORTEX_TIER_B_RUNTIME_V1).

Worktree: `~/bm-b3`.

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
