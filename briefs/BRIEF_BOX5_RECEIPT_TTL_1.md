# BRIEF: BOX5_RECEIPT_TTL_1 — Airport-ticket check-in reader + stale-ticket TTL nudge

## Context

Baker OS V2 Box 5 ("Airport") issues "boarding-pass" tickets to owning matter desks on the Brisen Lab bus, then expects each desk to "check in" by replying with one of six outcome tokens. Today the **issue** half is built and the **receipt** half is not: `orchestrator/airport_ticketing_bridge.py` reserves a row, POSTs the pass, and flips `candidate → sent` — but nothing reads the desk's reply back, and nothing notices when a `sent` ticket is never answered. A repo-wide grep for `check_in_outcome=` / `check_in_at=` / `check_in_by=` / `status='checked_in'` returns **zero write sites** — those columns exist only in the `CREATE TABLE` DDL. A `sent` ticket therefore stays `sent` forever, and a desk that ignores its pass is never re-pinged. That silent rot is exactly the risk this brief removes.

This brief is **Build Order steps 1-2** of the Box-5 plan and implements locked goal **#4677.2**: *prove existing frozen tickets get delivered + checked-in + TTL-nudged BEFORE the runner generates more arrivals.* It is deliberately the receipt loop only:
- **Part 1** — a check-in reply-reader that writes the receipt fields when an owning desk replies to a ticket on the bus.
- **Part 2** — a stale-ticket TTL/nudge sweep that re-pings desks whose `sent` tickets have no check-in after a TTL, escalating to `lead` after N nudges.

Both run against the **existing frozen `airport_tickets` table**. This brief is **#439-independent** — it touches no registry, no runner, no fast lanes, no new terminal states. Those are later briefs (B–E) and are explicitly out of scope here.

### Surface contract: N/A — backend scheduler jobs (check-in reader + TTL sweep), no clickable UI surface.

### Harness V2

**Context Contract**
- **Inputs (read):**
  - Brisen Lab bus inbox for the ticketing sender slug: `GET {AIRPORT_TICKETING_BUS_URL}/msg/{ticketing_slug}?limit=N&unread=true`, header `X-Terminal-Key: <_bridge_key()>` → `{"messages":[{id, parent_id, thread_id, from_terminal, body_preview, acknowledged_at, ...}]}`.
  - Full reply body: `GET {bus}/event/{id}/full`, same header.
  - `airport_tickets` rows joined on `bus_message_id = reply.parent_id` (primary) / `bus_thread_id = reply.thread_id` (fallback).
  - `airport_tickets` stale rows: `status='sent' AND check_in_at IS NULL AND last_sent_at < NOW()-TTL AND (last_nudged_at IS NULL OR last_nudged_at <= NOW()-COOLDOWN)`.
- **Outputs (write):**
  - Part 1: `UPDATE airport_tickets SET check_in_outcome, check_in_at=NOW(), check_in_by, status, updated_at=NOW()` (guarded `WHERE … status='sent'`); ACK the bus message after the write commits; `baker_actions` row `airport_ticket.checked_in`.
  - Part 2: bus re-POST to the owning desk (reuses the bridge's send path); `UPDATE airport_tickets SET last_sent_at=NOW(), bus_message_id, last_nudged_at=NOW(), nudge_count=nudge_count+1`; `baker_actions` rows `airport_ticket.renudged` / `airport_ticket.escalated`.
  - No schema migration to receipt columns (they already exist); **one tiny additive ALTER** adds nudge-state columns (`last_nudged_at`, `nudge_count`) — see Task class.
- **Side effects:** outbound bus POSTs (re-nudge to desk, single escalation to `lead`); `baker_actions` audit rows. No external email, no ClickUp, no vault writes.
- **Idempotency invariants:** (a) a reply already checked-in (`status != 'sent'`) is a no-op `UPDATE` that affects 0 rows, then ACK; (b) bus ACK happens only after the receipt write commits, so a crash mid-tick re-reads the un-acked reply next tick and the `status='sent'` guard makes the re-write a no-op; (c) the nudge cooldown filter + `FOR UPDATE SKIP LOCKED` prevent double-counting a nudge in the same or overlapping tick.

**Task class:** **additive + tiny ALTER.** Net-new reader/sweep code (no edits to the existing issue path) plus **one** additive, idempotent migration `ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS last_nudged_at TIMESTAMPTZ; ADD COLUMN IF NOT EXISTS nudge_count INTEGER NOT NULL DEFAULT 0;`, mirrored inside `ensure_airport_ticket_table` to dodge the documented migration-vs-bootstrap drift trap. The receipt columns (`check_in_outcome/at/by`, `status='checked_in'/'rejected'`, `last_sent_at`) are **untouched DDL — already present.**

**Done rubric (machine-checkable):**
- [ ] `git grep -nE "check_in_outcome\s*=|status\s*=\s*'checked_in'"` now returns a write site in `orchestrator/airport_checkin_reader.py` (was zero).
- [ ] New module `orchestrator/airport_checkin_reader.py` exposes `run_checkin_sweep(*, now=None) -> dict` (combined Part-1 reader + Part-2 nudge).
- [ ] New wrapper `triggers/airport_checkin_tick.py` exposes `run_airport_checkin_tick() -> None`.
- [ ] `triggers/embedded_scheduler.py` gains `airport_checkin_tick_enabled()` + `airport_checkin_tick_interval_seconds()` and one `if airport_checkin_tick_enabled(): add_job(... id="airport_checkin_tick" ...); register_expected_job("airport_checkin_tick", N)` block.
- [ ] Both new env gates default **false / off** (`AIRPORT_CHECKIN_SWEEP_ENABLED`).
- [ ] `pytest tests/test_airport_ticketing_bridge.py tests/test_airport_checkin_reader.py tests/test_airport_checkin_scheduler.py -q` all pass.
- [ ] `bash scripts/check_singletons.sh` passes (no direct `SentinelStoreBack()`).
- [ ] `python3 -c "import py_compile; py_compile.compile('orchestrator/airport_checkin_reader.py', doraise=True)"` clean.
- [ ] Every `cur.execute` SELECT carries a `LIMIT`; every `except` around a DB op calls `conn.rollback()`; every DB/HTTP call is inside `try/except`.

**Gate plan:**
1. **G1 — builder self-check.** Run the full test set above + singleton guard + compile check. Reproduce both flows against a live test DB (`TEST_DATABASE_URL`) per Verification; report counts.
2. **G3 — codex.** `bus_post.sh codex` for a verdict on idempotency (no double check-in / double nudge), fault-tolerance (a single bad reply parse cannot crash the sweep), and the frozen-table guarantee (only the additive ALTER).
3. **G4 — lead `/security-review`** then **lead merge.** Both jobs ship **dark**: `AIRPORT_CHECKIN_SWEEP_ENABLED` unset/false in Render env, so the scheduler logs "skipping registration" and no job runs until lead flips the flag. Single-replica execution is inherited from `scheduler_lease` (advisory lock `8800100`) — do **not** add a new lock.

## Estimated time
3–5 hours (net-new module + thin wrapper + 6-line scheduler block + 1 migration + 3 test files; no edits to existing issue logic).

## Complexity
**Medium** — two flows in one tick, bus inbox read + ACK-after-write dedup discipline, and a TTL/nudge state machine, but every primitive (bus read, bus POST, store conn, audit, scheduler registration, nudge-state columns) already has a verified in-repo precedent to mirror.

## Prerequisites
**None.** #439-independent. The `airport_tickets` table, its receipt columns, the `idx_airport_tickets_desk_status` index, the bus send path, and the scheduler-registration pattern all already exist on `origin/main`. (`orchestrator/airport_ticketing_bridge.py` is on `origin/main` only, not the current checkpoint working tree — read via `git show origin/main:<path>`.)

---

## Part 1 — Check-in reply-reader

### Problem
When an owning desk replies to a boarding-pass on the bus with one of the six outcome tokens, nothing reads that reply. The receipt columns (`check_in_outcome`, `check_in_at`, `check_in_by`) and the `checked_in` / `rejected` statuses are write-never. We must read the desk's reply, parse the outcome, and write the receipt — joining the reply to its ticket via the bus message id the bridge already persisted.

### Current State
- `format_ticket_for_bus` (`orchestrator/airport_ticketing_bridge.py:547`) ends the pass with the literal instruction: *"Check-in required: reply with VALID, FAKE, DUPLICATE, WRONG_TERMINAL, URGENT, or NEEDS_LUGGAGE_READ."* — the fixed reply vocabulary.
- `VALID_CHECK_IN_OUTCOMES = frozenset({"VALID","FAKE","DUPLICATE","WRONG_TERMINAL","URGENT","NEEDS_LUGGAGE_READ"})` (`orchestrator/airport_ticketing_bridge.py:50`) — import this; do not re-declare.
- `mark_ticket_sent` (`orchestrator/airport_ticketing_bridge.py:598`) persists `bus_message_id` (BIGINT) and `bus_thread_id` (TEXT) on every sent ticket. A desk reply carries `parent_id` = the original message id → join `airport_tickets.bus_message_id = reply.parent_id`.
- Bus read precedent: `ClerkBusWorker._fetch_inbox` (`orchestrator/clerk_bus_worker.py:449`) does `GET {lab_url}/msg/{slug}?limit=N`, header `X-Terminal-Key`, returns `data["messages"]`; `process_message` filters self/empty senders and ACKs **after** the write via `_ack_message` (`POST {lab_url}/msg/{id}/ack`).
- `_bridge_key()` (`orchestrator/airport_ticketing_bridge.py:491`) and `_request_json` (`orchestrator/airport_ticketing_bridge.py:~497`) and `_bus_message_id` (`orchestrator/airport_ticketing_bridge.py:524`) are reusable bus primitives.
- DDL CHECK already constrains `check_in_outcome` to the six tokens or NULL (`ensure_airport_ticket_table`, `orchestrator/airport_ticketing_bridge.py:283-305`); `status` CHECK already includes `checked_in` and `rejected`.

### Engineering Craft Gates
- **Diagnose — N/A.** No bug to reproduce; this is net-new behaviour. The "diagnosis" is the confirmed write-never gap (grep returns zero receipt-write sites).
- **Prototype — APPLIES.** Reply-body parsing is the one genuine uncertainty (free-text desk reply → exactly one of six tokens, case/whitespace/multi-token). Write the pure parser `parse_checkin_outcome(body: str) -> Optional[str]` first, unit-test it against: exact token, lowercase, token embedded in a sentence, two tokens (→ reject as ambiguous, return None), no token (→ None). Lock its contract before wiring DB.
- **TDD — APPLIES.** Write `tests/test_airport_checkin_reader.py` covering: (a) parser cases above; (b) a sent ticket + a matching reply → receipt fields written + status mapped + ACK called; (c) a reply whose `parent_id` matches no ticket → no write, message left for next tick (no ACK or ACK-and-skip per design, but never crash); (d) a reply matching a ticket already `checked_in` → 0-row update, no double-write; (e) one malformed reply in a batch does not stop the others.

### Implementation
Create `orchestrator/airport_checkin_reader.py`. Reuse the bridge's bus + store primitives; import the outcome frozenset.

```python
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional

from orchestrator.airport_ticketing_bridge import (
    VALID_CHECK_IN_OUTCOMES,
    _bridge_key,
    _request_json,
    ensure_airport_ticket_table,
)

logger = logging.getLogger(__name__)

_SWEEP_ENABLED_ENV = "AIRPORT_CHECKIN_SWEEP_ENABLED"
_TICKETING_SLUG_ENV = "AIRPORT_CHECKIN_TICKETING_SLUG"
_DEFAULT_TICKETING_SLUG = "ticketing-desk"
_BUS_URL_ENV = "AIRPORT_TICKETING_BUS_URL"
_DEFAULT_BUS_URL = "https://brisen-lab.onrender.com"
_POLL_LIMIT_ENV = "AIRPORT_CHECKIN_POLL_LIMIT"
_DEFAULT_POLL_LIMIT = 25

# Outcome -> terminal status. VALID/URGENT/NEEDS_LUGGAGE_READ accept the arrival;
# FAKE/DUPLICATE/WRONG_TERMINAL reject it. Locked policy (see Key Constraints).
_OUTCOME_TO_STATUS = {
    "VALID": "checked_in",
    "URGENT": "checked_in",
    "NEEDS_LUGGAGE_READ": "checked_in",
    "FAKE": "rejected",
    "DUPLICATE": "rejected",
    "WRONG_TERMINAL": "rejected",
}


def sweep_enabled() -> bool:
    raw = os.environ.get(_SWEEP_ENABLED_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _bus_base() -> str:
    return os.environ.get(_BUS_URL_ENV, _DEFAULT_BUS_URL).rstrip("/")


def _ticketing_slug() -> str:
    return (os.environ.get(_TICKETING_SLUG_ENV) or _DEFAULT_TICKETING_SLUG).strip()


def _poll_limit() -> int:
    try:
        return max(1, min(int(os.environ.get(_POLL_LIMIT_ENV, str(_DEFAULT_POLL_LIMIT))), 100))
    except (TypeError, ValueError):
        return _DEFAULT_POLL_LIMIT


def parse_checkin_outcome(body: str) -> Optional[str]:
    """Return exactly one of the 6 outcome tokens, or None if 0 or >1 present.

    Pure function. Case-insensitive whole-token match. Ambiguous (>1 distinct
    token) -> None so we never guess. Never raises on odd input.
    """
    if not body:
        return None
    try:
        upper = body.upper()
        import re

        found = {
            tok
            for tok in VALID_CHECK_IN_OUTCOMES
            if re.search(r"(?<![A-Z_])" + re.escape(tok) + r"(?![A-Z_])", upper)
        }
        if len(found) == 1:
            return next(iter(found))
        return None
    except Exception:
        return None


def _fetch_inbox(base: str, slug: str, key: str, limit: int) -> list[dict[str, Any]]:
    url = f"{base}/msg/{slug}?limit={limit}&unread=true"
    result = _request_json("GET", url, key=key)
    if result.get("error"):
        logger.warning("airport check-in inbox fetch failed: %s", result.get("error"))
        return []
    messages = result.get("messages")
    if not isinstance(messages, list):
        return []
    return [m for m in messages if isinstance(m, dict)]


def _fetch_full_body(base: str, message_id: int, key: str) -> str:
    result = _request_json("GET", f"{base}/event/{message_id}/full", key=key)
    if result.get("error"):
        return ""
    body = result.get("body") or result.get("full_body") or ""
    return body if isinstance(body, str) else ""


def _ack(base: str, message_id: int, key: str) -> None:
    try:
        _request_json("POST", f"{base}/msg/{message_id}/ack", key=key, payload={})
    except Exception as e:  # ACK is best-effort; un-acked reply re-reads idempotently next tick
        logger.warning("airport check-in ack failed id=%s: %s", message_id, e)


def _write_checkin(conn: Any, *, parent_id: int, thread_id: Optional[str],
                   outcome: str, desk_slug: str) -> int:
    """Guarded receipt write. Returns rows affected (0 if not a 'sent' ticket).

    status='sent' precondition makes a re-applied reply a no-op (idempotent) and
    stops a reply from downgrading a candidate/failed/already-checked-in row.
    """
    target_status = _OUTCOME_TO_STATUS[outcome]
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE airport_tickets
            SET check_in_outcome = %s,
                check_in_at = NOW(),
                check_in_by = %s,
                status = %s,
                updated_at = NOW()
            WHERE status = 'sent'
              AND check_in_at IS NULL
              AND (bus_message_id = %s OR (%s IS NOT NULL AND bus_thread_id = %s))
            RETURNING ticket_id
            """,
            (outcome, desk_slug[:200], target_status, parent_id, thread_id, thread_id),
        )
        row = cur.fetchone()
        if not row:
            return 0
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, payload, trigger_source, success)
            VALUES (%s, %s, %s, %s, TRUE)
            """,
            (
                "airport_ticket.checked_in",
                row[0],
                _json_param({"outcome": outcome, "by": desk_slug, "status": target_status}),
                "airport_checkin_reader",
            ),
        )
    return 1


def run_checkin_reader(conn: Any) -> dict[str, Any]:
    """Part 1: read desk replies, write receipts, ACK after commit."""
    base, key, slug = _bus_base(), _bridge_key(), _ticketing_slug()
    if not key:
        return {"ok": False, "reason": "ticketing_key_missing", "checked_in": 0}
    checked_in = parsed_none = unmatched = errors = 0
    messages = _fetch_inbox(base, slug, key, _poll_limit())
    for msg in messages:
        try:
            mid = int(msg["id"])
            parent_id = msg.get("parent_id")
            if parent_id is None:
                continue  # not a reply to a ticket; leave it
            sender = str(msg.get("from_terminal") or "").strip()
            if not sender or sender == slug:
                continue
            body = _fetch_full_body(base, mid, key) or str(msg.get("body_preview") or "")
            outcome = parse_checkin_outcome(body)
            if outcome is None:
                parsed_none += 1
                continue  # ambiguous/none: never guess; leave un-acked for human/next look
            affected = _write_checkin(
                conn, parent_id=int(parent_id), thread_id=msg.get("thread_id"),
                outcome=outcome, desk_slug=sender,
            )
            conn.commit()  # commit BEFORE ack so a crash re-reads idempotently
            if affected:
                checked_in += 1
                _ack(base, mid, key)
            else:
                unmatched += 1
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            errors += 1
            logger.warning("airport check-in reply failed id=%s: %s", msg.get("id"), e)
            continue  # one bad reply never stops the batch
    return {"ok": True, "checked_in": checked_in, "parsed_none": parsed_none,
            "unmatched": unmatched, "errors": errors}
```

Import the existing `_json_param` helper from the bridge (`from orchestrator.airport_ticketing_bridge import _json_param`) rather than re-implementing JSON adaptation.

### Key Constraints
- **Status mapping is locked policy** (codex G3 + lead to confirm at gate, do not silently change): `VALID/URGENT/NEEDS_LUGGAGE_READ → checked_in`; `FAKE/DUPLICATE/WRONG_TERMINAL → rejected`. Both are legal values already in the frozen `status` CHECK. Do **not** invent new status values.
- **`check_in_by` comes from `reply.from_terminal`** (server-authenticated), never from a `FROM:` line in the body. The `'ticketing-desk'` slug in `format_ticket_for_bus` is cosmetic; the real replying desk may be a stand-in (`baden-baden-desk` is seeded, no live picker) — take whoever actually replied.
- **Join on `parent_id → bus_message_id` primarily**; `thread_id → bus_thread_id` only as a fallback (a generic bus POST does not always inherit `thread_id`, so `parent_id` is the reliable key).
- **ACK only after the receipt write commits.** Ambiguous/unmatched replies are left un-acked deliberately — re-reading them next tick is a safe no-op under the `status='sent'` guard.
- Import `VALID_CHECK_IN_OUTCOMES` — do not re-declare (must stay identical to the DB CHECK).

### Verification
With `TEST_DATABASE_URL` set: insert a `sent` ticket with a known `bus_message_id`; feed a fake inbox message (`parent_id = that id`, body `"VALID — proceed"`); assert row now `status='checked_in'`, `check_in_outcome='VALID'`, `check_in_by='<sender>'`, `check_in_at` non-null, and a `baker_actions` `airport_ticket.checked_in` row exists. Re-run the same message → 0-row update, no second audit row. Feed an ambiguous body (`"VALID or FAKE?"`) → no write, `parsed_none` incremented.

---

## Part 2 — Stale-ticket TTL / nudge sweep

### Problem
A `sent` ticket whose desk never replies stays `sent` forever and is silently dropped. We must, after a TTL, re-ping the owning desk; after N nudges with still no check-in, escalate once to `lead` and stop re-nudging that ticket — without inventing a new status value (the `status` CHECK is frozen).

### Current State
- Stale scan is already index-served: `idx_airport_tickets_desk_status ON (proposed_desk_slug, status, last_sent_at DESC)` (`ensure_airport_ticket_table`, `orchestrator/airport_ticketing_bridge.py:317`).
- `last_sent_at` is the TTL anchor, bumped to `NOW()` by `mark_ticket_sent` (`orchestrator/airport_ticketing_bridge.py:610`). There is **no** `last_nudged_at` and **no** `nudge_count` column today.
- Canonical nudge-state precedent: `migrations/20260628b_router_second_look_and_waiting_room.sql` ships `waiting_room_items` with `last_nudge_at TIMESTAMPTZ`, `nudge_count INTEGER NOT NULL DEFAULT 0`.
- Cadence + cooldown precedent: `orchestrator/waiting_room.py:146` `run_nudge_tick` — single guarded `UPDATE … WHERE id IN (SELECT … FOR UPDATE SKIP LOCKED)` with `(last_nudge_at IS NULL OR last_nudge_at <= NOW() - (%s||' seconds')::interval)`; and `triggers/stale_cycle_nudge_sentinel.py:148` — per-row try/except, never raises.
- Migration-vs-bootstrap drift trap precedent: `migrations/20260518_cortex_cycles_add_last_nudge_at.sql` **plus** a mirrored `ALTER … ADD COLUMN IF NOT EXISTS` inside the table bootstrap (`memory/store_back.py:761`).
- Bus send to re-ping: `_request_json` + `_bridge_key` + `_bus_message_id` (bridge) — the same primitives Part 1 reuses; the desk slug is the row's `proposed_desk_slug`, and the original pass body lives in the row's `ticket` JSONB.
- Escalation target = `lead` (AG-001). `RESERVED_RECIPIENTS = {director, daemon, dispatcher}` — escalation must **never** go to the Director (Director comm rules + non-director-agents-bus-only: lead is the filter).

### Engineering Craft Gates
- **Diagnose — N/A.** Net-new; the gap (no TTL/nudge logic for `airport_tickets`) is confirmed by grep.
- **Prototype — APPLIES (small).** Mirror `is_nudge_eligible` (`orchestrator/waiting_room.py:128`) as a pure predicate so the TTL + cooldown + max-nudge eligibility is unit-testable without PG.
- **TDD — APPLIES.** `tests/test_airport_checkin_reader.py` (same file as Part 1) covers: a `sent` ticket older than TTL with no check-in → exactly one re-POST + `last_nudged_at`/`nudge_count` bumped; the same ticket inside cooldown → skipped; a ticket at `nudge_count = max` → one escalation to `lead` + no further re-nudge; a checked-in ticket → never selected.

### Implementation
Add the nudge-state columns. **(1) Migration** `migrations/20260630_airport_tickets_nudge_state.sql`:

```sql
-- BOX5_RECEIPT_TTL_1: stale-ticket nudge state on the frozen airport_tickets table.
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS last_nudged_at TIMESTAMPTZ;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS nudge_count INTEGER NOT NULL DEFAULT 0;
```

**(2) Mirror inside `ensure_airport_ticket_table`** (append after the existing index DDL, so already-bootstrapped DBs gain the columns — the documented drift fix):

```python
        cur.execute(
            "ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS last_nudged_at TIMESTAMPTZ"
        )
        cur.execute(
            "ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS nudge_count INTEGER NOT NULL DEFAULT 0"
        )
```

**(3) Part-2 logic** in `orchestrator/airport_checkin_reader.py`:

```python
_NUDGE_TTL_MIN_ENV = "AIRPORT_CHECKIN_TTL_MINUTES"
_DEFAULT_TTL_MIN = 60
_NUDGE_COOLDOWN_MIN_ENV = "AIRPORT_CHECKIN_NUDGE_COOLDOWN_MINUTES"
_DEFAULT_COOLDOWN_MIN = 60
_NUDGE_MAX_ENV = "AIRPORT_CHECKIN_MAX_NUDGES"
_DEFAULT_MAX_NUDGES = 3
_NUDGE_CAP_ENV = "AIRPORT_CHECKIN_NUDGE_MAX_PER_TICK"
_DEFAULT_NUDGE_CAP = 5
_ESCALATION_SLUG = "lead"


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(os.environ.get(name, str(default))), hi))
    except (TypeError, ValueError):
        return default


def _select_stale(conn: Any, *, ttl_min: int, cooldown_min: int,
                  max_nudges: int, cap: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, ticket_id, proposed_desk_slug, ticket, nudge_count
            FROM airport_tickets
            WHERE status = 'sent'
              AND check_in_at IS NULL
              AND nudge_count < %s
              AND last_sent_at < NOW() - (%s || ' minutes')::interval
              AND (
                  last_nudged_at IS NULL
                  OR last_nudged_at <= NOW() - (%s || ' minutes')::interval
              )
            ORDER BY last_sent_at ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            (max_nudges, ttl_min, cooldown_min, cap),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _renudge_post(base: str, key: str, *, desk_slug: str, ticket_id: str,
                  body: str, nudge_n: int) -> dict[str, Any]:
    payload = {
        "kind": "dispatch",
        "body": f"RE-NUDGE #{nudge_n} — check-in still pending\n\n{body}",
        "to": [desk_slug],
        "tier_required": "B",
        "topic": f"airport-ticketing/checkin-nudge/{ticket_id}",
    }
    return _request_json("POST", f"{base}/msg/{desk_slug}", key=key, payload=payload)


def _escalate_post(base: str, key: str, *, ticket_id: str, desk_slug: str) -> dict[str, Any]:
    payload = {
        "kind": "dispatch",
        "body": (f"ESCALATION — airport ticket {ticket_id} to {desk_slug} has had "
                 f"no check-in after max nudges. Desk is non-responsive."),
        "to": [_ESCALATION_SLUG],
        "tier_required": "B",
        "topic": f"airport-ticketing/escalation/{ticket_id}",
    }
    return _request_json("POST", f"{base}/msg/{_ESCALATION_SLUG}", key=key, payload=payload)


def run_ttl_nudge(conn: Any) -> dict[str, Any]:
    """Part 2: re-ping stale 'sent' tickets; escalate once at max nudges."""
    base, key = _bus_base(), _bridge_key()
    if not key:
        return {"ok": False, "reason": "ticketing_key_missing", "nudged": 0, "escalated": 0}
    ttl = _int_env(_NUDGE_TTL_MIN_ENV, _DEFAULT_TTL_MIN, 5, 1440)
    cooldown = _int_env(_NUDGE_COOLDOWN_MIN_ENV, _DEFAULT_COOLDOWN_MIN, 5, 1440)
    max_nudges = _int_env(_NUDGE_MAX_ENV, _DEFAULT_MAX_NUDGES, 1, 10)
    cap = _int_env(_NUDGE_CAP_ENV, _DEFAULT_NUDGE_CAP, 1, 25)

    nudged = escalated = errors = 0
    try:
        rows = _select_stale(conn, ttl_min=ttl, cooldown_min=cooldown,
                             max_nudges=max_nudges, cap=cap)
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("airport ttl-nudge select failed: %s", e)
        return {"ok": False, "error": str(e), "nudged": 0, "escalated": 0}

    for row in rows:
        try:
            ticket_blob = row.get("ticket") or {}
            if not isinstance(ticket_blob, dict):
                ticket_blob = {}
            # The bridge persists AirportTicket.payload() in the `ticket` JSONB —
            # there is NO rendered pass-body column (payload() at bridge:86-105 has
            # contract/ticket_id/source_*/originator/suspected_matter_slug/
            # suspected_flight/proposed_desk_slug/urgency_hint/luggage/why_ticketed/
            # known_limits, no body). Reconstruct the re-nudge body from those
            # persisted fields — do NOT re-fetch the source email or re-run issue.
            _lug = ticket_blob.get("luggage")
            _lug = _lug if isinstance(_lug, list) else []
            pass_body = (
                f"BOARDING PASS — RE-NUDGE — ticket {row['ticket_id']}\n"
                f"Desk: {ticket_blob.get('proposed_desk_slug') or row['proposed_desk_slug']}\n"
                f"Flight (suspected): {ticket_blob.get('suspected_flight') or 'unknown'}\n"
                f"From: {ticket_blob.get('originator') or 'unknown'}\n"
                f"Luggage: {', '.join(str(x) for x in _lug) if _lug else 'none noted'}\n"
                "Check in by replying with ONE of: "
                "VALID, FAKE, DUPLICATE, WRONG_TERMINAL, URGENT, NEEDS_LUGGAGE_READ."
            )
            next_n = int(row["nudge_count"]) + 1
            result = _renudge_post(base, key, desk_slug=row["proposed_desk_slug"],
                                   ticket_id=row["ticket_id"], body=pass_body, nudge_n=next_n)
            if result.get("error"):
                errors += 1
                conn.rollback()
                continue
            new_msg_id = _bus_message_id(result)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE airport_tickets
                    SET last_nudged_at = NOW(),
                        nudge_count = nudge_count + 1,
                        bus_message_id = COALESCE(%s, bus_message_id),
                        last_sent_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s AND status = 'sent' AND check_in_at IS NULL
                    """,
                    (new_msg_id, row["id"]),
                )
                cur.execute(
                    """
                    INSERT INTO baker_actions
                        (action_type, target_task_id, payload, trigger_source, success)
                    VALUES (%s, %s, %s, %s, TRUE)
                    """,
                    ("airport_ticket.renudged", row["ticket_id"],
                     _json_param({"nudge_count": next_n, "desk": row["proposed_desk_slug"]}),
                     "airport_checkin_reader"),
                )
            conn.commit()
            nudged += 1

            if next_n >= max_nudges:
                esc = _escalate_post(base, key, ticket_id=row["ticket_id"],
                                     desk_slug=row["proposed_desk_slug"])
                if not esc.get("error"):
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO baker_actions
                                (action_type, target_task_id, payload, trigger_source, success)
                            VALUES (%s, %s, %s, %s, TRUE)
                            """,
                            ("airport_ticket.escalated", row["ticket_id"],
                             _json_param({"to": _ESCALATION_SLUG, "nudge_count": next_n}),
                             "airport_checkin_reader"),
                        )
                    conn.commit()
                    escalated += 1
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            errors += 1
            logger.warning("airport ttl-nudge row failed id=%s: %s", row.get("id"), e)
            continue
    return {"ok": True, "nudged": nudged, "escalated": escalated, "errors": errors}


def run_checkin_sweep(*, now: Optional[datetime] = None) -> dict[str, Any]:
    """Combined tick: Part 1 reader + Part 2 TTL nudge. One job, two phases."""
    if not sweep_enabled():
        return {"skipped": True, "reason": f"{_SWEEP_ENABLED_ENV} off"}
    try:
        from memory.store_back import SentinelStoreBack

        store = SentinelStoreBack._get_global_instance()
    except Exception as e:
        logger.warning("airport check-in store unavailable: %s", e)
        return {"skipped": True, "reason": "store_unavailable"}
    conn = store._get_conn()
    if not conn:
        return {"skipped": True, "reason": "database_unavailable"}
    try:
        ensure_airport_ticket_table(conn)
        conn.commit()
        reader = run_checkin_reader(conn)
        nudge = run_ttl_nudge(conn)
        return {"ok": True, "reader": reader, "nudge": nudge}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("airport check-in sweep failed: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        store._put_conn(conn)
```

> **Builder note — re-nudge body is reconstructed, not stored.** Verified: `AirportTicket.payload()` (bridge:86-105) persists only `contract, ticket_id, created_at, source_channel, source_id, source_received_at, originator, suspected_matter_slug, suspected_flight, proposed_desk_slug, urgency_hint, luggage, why_ticketed, known_limits` in the `ticket` JSONB — there is **no** rendered pass-body and **no** `bus_body` key. The re-nudge body above is reconstructed inline from those persisted fields (`proposed_desk_slug` / `suspected_flight` / `originator` / `luggage` + the check-in instruction line). Do **not** look up `bus_body`, re-fetch the source email, or re-run the issue path.

**(4) Scheduler wrapper** `triggers/airport_checkin_tick.py` (mirror `triggers/airport_ticketing_tick.py`):

```python
def run_airport_checkin_tick() -> None:
    from orchestrator.airport_checkin_reader import run_checkin_sweep

    run_checkin_sweep()
```

**(5) Register** in `triggers/embedded_scheduler.py`. Add the two helpers next to `airport_ticketing_tick_enabled` (~line 172):

```python
def airport_checkin_tick_enabled() -> bool:
    import os

    raw = os.environ.get("AIRPORT_CHECKIN_SWEEP_ENABLED", "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def airport_checkin_tick_interval_seconds() -> int:
    import os

    try:
        minutes = int(os.environ.get("AIRPORT_CHECKIN_SWEEP_MINUTES", "10"))
    except (TypeError, ValueError):
        minutes = 10
    return max(5, min(minutes, 60)) * 60
```

Inside `_register_jobs`, immediately after the `airport_ticketing_tick` block (~line 350):

```python
    if airport_checkin_tick_enabled():
        from triggers.airport_checkin_tick import run_airport_checkin_tick

        _airport_checkin_interval = airport_checkin_tick_interval_seconds()
        scheduler.add_job(
            run_airport_checkin_tick,
            IntervalTrigger(seconds=_airport_checkin_interval),
            id="airport_checkin_tick",
            name="Airport check-in reader + TTL nudge",
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
        register_expected_job("airport_checkin_tick", _airport_checkin_interval)
        logger.info(f"Registered: airport_checkin_tick (every {_airport_checkin_interval}s)")
    else:
        logger.info(
            "airport_checkin_tick disabled via AIRPORT_CHECKIN_SWEEP_ENABLED - skipping registration"
        )
```

### Key Constraints
- **Additive ALTER, not JSONB, for nudge state.** Justification (one line): `waiting_room_items` — the table built for exactly this nudge use case — uses real `last_nudge_at`/`nudge_count` columns, which are NOT-NULL-defaultable and index-served by the existing `idx_airport_tickets_desk_status`, whereas a JSONB `ticket->>'nudge_count'` forces `::int` casts in every WHERE/UPDATE and cannot be cleanly defaulted. (This is the TTL explorer's recommended option.)
- **Migration + mirrored bootstrap ALTER both required** — `CREATE TABLE IF NOT EXISTS` no-ops on already-bootstrapped DBs, so the column must also be added in `ensure_airport_ticket_table` (the cortex_cycles drift-trap playbook).
- **`FOR UPDATE SKIP LOCKED` + the `nudge_count < max` and cooldown filters** guarantee no double-nudge across overlapping ticks and a hard ceiling on re-pings.
- **Re-nudge bumps `last_sent_at = NOW()`** so the TTL re-arms and the freshest `bus_message_id` is the one Part 1 joins against next.
- **Escalate to `lead` only, once, at `nudge_count >= max`.** Never to `director` / `daemon` / `dispatcher` (`RESERVED_RECIPIENTS`). Do **not** add a new `status` value for "escalated" — the row stays `status='sent'` and falls out of the scan via `nudge_count < max`.
- **A single bad row never aborts the sweep** — per-row `try/except` with `rollback()`, mirroring `triggers/stale_cycle_nudge_sentinel.py`.

### Verification
With `TEST_DATABASE_URL`: insert a `sent` ticket with `last_sent_at = NOW() - 2h`, `check_in_at NULL`, `nudge_count = 0`. Run `run_ttl_nudge` with stubbed bus POSTs → assert exactly one re-POST, `nudge_count = 1`, `last_nudged_at` set, `last_sent_at` bumped, one `airport_ticket.renudged` audit row. Re-run immediately → 0 nudges (cooldown). Set `nudge_count = max-1` and age past cooldown → run → `nudge_count = max`, one `airport_ticket.escalated` row to `lead`, and a subsequent run selects 0 rows.

---

## Files Modified
- **NEW** `orchestrator/airport_checkin_reader.py` — Part 1 reader + Part 2 TTL nudge + combined `run_checkin_sweep`.
- **NEW** `triggers/airport_checkin_tick.py` — thin scheduler wrapper.
- **NEW** `migrations/20260630_airport_tickets_nudge_state.sql` — additive ALTER (`last_nudged_at`, `nudge_count`).
- **NEW** `tests/test_airport_checkin_reader.py` — parser + reader + TTL/nudge/escalation tests (live-PG gated; auto-skip without `TEST_DATABASE_URL`).
- **NEW** `tests/test_airport_checkin_scheduler.py` — 3 cases (default-off, enabled-values, interval-bounds) against the new helpers (no DB).
- **EDIT** `orchestrator/airport_ticketing_bridge.py` — append the two mirrored `ALTER … ADD COLUMN IF NOT EXISTS` lines inside `ensure_airport_ticket_table` only. **No other edit to this file.**
- **EDIT** `triggers/embedded_scheduler.py` — add `airport_checkin_tick_enabled()` + `airport_checkin_tick_interval_seconds()` + one registration block.

## Do NOT Touch
- The existing **issue path** in `orchestrator/airport_ticketing_bridge.py` (`run_tick`, `issue_ticket`, `reserve_ticket`, `post_ticket_to_bus`, `mark_ticket_sent`, `mark_ticket_failed`, `build_email_ticket`, `fetch_email_arrivals`) — read-and-reuse only; the only edit to this file is the two mirrored ALTER lines.
- The `airport_tickets` **receipt-column DDL, status CHECK, source/urgency CHECKs, and indexes** — frozen; add no new status value, add no new index.
- `migrations/` already-applied files — never rewrite; this is a brand-new migration.
- `triggers/airport_ticketing_tick.py` and the existing `airport_ticketing_tick` registration block — leave intact; the receipt loop is a **separate, independently-switchable** job.
- `scheduler_lease.py` / advisory lock `8800100` — single-replica is inherited; add no new lock.
- `tasks/lessons.md` existing entries; `baker-vault/slugs.yml`; `MEMORY.md`.
- The `_CRON_JOB_IDS` list in `tests/test_scheduler_liveness_sentinel.py` — the new job is `IntervalTrigger`, so it pairs with `register_expected_job` and must **not** be added there.

## Quality Checkpoints
- [ ] Every SELECT has a `LIMIT`; every `except` wrapping a DB op calls `conn.rollback()`; every DB/HTTP call is inside `try/except`.
- [ ] Both new env gates default false/off; the job ships dark (Render env unset → scheduler logs "skipping registration").
- [ ] `VALID_CHECK_IN_OUTCOMES` imported, not re-declared; status mapping matches the frozen `status` CHECK.
- [ ] ACK only after the receipt write commits; re-reading an un-acked reply is a verified 0-row no-op.
- [ ] Nudge state via additive ALTER (migration **and** mirrored bootstrap); `FOR UPDATE SKIP LOCKED` + `nudge_count < max` + cooldown filters in the stale scan.
- [ ] Escalation goes to `lead` only, once, never to `RESERVED_RECIPIENTS`; no new status value.
- [ ] DB access via `SentinelStoreBack._get_global_instance()` → `_get_conn()` / `_put_conn()`; `bash scripts/check_singletons.sh` passes.
- [ ] A single bad reply or bad stale row cannot crash the sweep (per-item `try/except`).
- [ ] `IntervalTrigger` job pairs with `register_expected_job`; not added to `_CRON_JOB_IDS`.
- [ ] `pytest tests/test_airport_ticketing_bridge.py tests/test_airport_checkin_reader.py tests/test_airport_checkin_scheduler.py -q` green; compile-clean is not "done" — the live flows in Verification were exercised.

## Verification SQL

```sql
-- Part 1: receipts now being written (was zero before this brief). LIMIT bounded.
SELECT ticket_id, status, check_in_outcome, check_in_by, check_in_at
FROM airport_tickets
WHERE check_in_at IS NOT NULL
ORDER BY check_in_at DESC
LIMIT 20;

-- Part 1 idempotency: no ticket should ever have a receipt while status='sent'
-- (receipt write flips status). Expect 0 rows.
SELECT ticket_id, status, check_in_outcome
FROM airport_tickets
WHERE status = 'sent' AND check_in_outcome IS NOT NULL
LIMIT 20;

-- Part 2: stale 'sent' tickets eligible for the next nudge (TTL=60m here).
SELECT ticket_id, proposed_desk_slug, last_sent_at, last_nudged_at, nudge_count
FROM airport_tickets
WHERE status = 'sent'
  AND check_in_at IS NULL
  AND nudge_count < 3
  AND last_sent_at < NOW() - INTERVAL '60 minutes'
  AND (last_nudged_at IS NULL OR last_nudged_at <= NOW() - INTERVAL '60 minutes')
ORDER BY last_sent_at ASC
LIMIT 20;

-- Part 2: tickets that hit the nudge ceiling and were escalated. Expect these
-- to stay status='sent' with nudge_count >= max and fall out of the scan above.
SELECT ticket_id, proposed_desk_slug, nudge_count, last_nudged_at
FROM airport_tickets
WHERE nudge_count >= 3 AND check_in_at IS NULL
ORDER BY last_nudged_at DESC
LIMIT 20;

-- Audit trail for both parts (new action_types).
SELECT action_type, target_task_id, trigger_source, created_at
FROM baker_actions
WHERE action_type IN ('airport_ticket.checked_in', 'airport_ticket.renudged', 'airport_ticket.escalated')
ORDER BY created_at DESC
LIMIT 30;
```