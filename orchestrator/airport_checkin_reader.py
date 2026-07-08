"""BOX5_RECEIPT_TTL_1 — Airport-ticket check-in reader + stale-ticket TTL nudge.

The issue half of Box 5 (``orchestrator/airport_ticketing_bridge.py``) reserves a
ticket, POSTs a boarding pass to the owning desk on the Brisen Lab bus, and flips
``candidate -> sent``. Nothing reads the desk's reply back, and nothing notices a
``sent`` ticket that is never answered. This module closes that receipt loop:

- **Part 1** (``run_checkin_reader``) reads desk replies on the ticketing bus
  inbox, parses one of the six outcome tokens, writes the receipt fields, and
  flips ``sent -> checked_in/rejected``. ACK happens only AFTER the write commits,
  so a crash mid-tick re-reads the un-acked reply next tick and the ``status='sent'``
  guard makes the re-write a no-op (crash-safe dedup).
- **Part 2** (``run_ttl_nudge``) re-pings the owning desk for ``sent`` tickets with
  no check-in after a TTL, and escalates once to ``lead`` after N nudges.
  ``FOR UPDATE SKIP LOCKED`` + cooldown + ``nudge_count < max`` prevent double-nudge.

Both run against the existing frozen ``airport_tickets`` table; the only schema
change is the additive ``last_nudged_at`` / ``nudge_count`` ALTER (migration +
mirrored bootstrap). Ships DARK behind ``AIRPORT_CHECKIN_SWEEP_ENABLED`` (default
false). #439-independent: no registry, no runner, no new terminal states.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

from orchestrator.airport_ticketing_bridge import (
    VALID_CHECK_IN_OUTCOMES,
    _bridge_key,
    _bus_message_id,
    _json_param,
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

# CHECKIN_READER_DRAIN_DEADLETTER_1 (lead #6861) — fix for false 'desk non-responsive'
# escalations. Root cause: non-actionable replies (unparseable / no-matching-ticket /
# errored) were never ACKed, so they re-occupied the front of the oldest-first `unread`
# poll window every sweep, starving real desk disposes (check_in_at stayed NULL ->
# run_ttl_nudge escalated). Two knobs:
#   DRAIN_MAX_PAGES: drain-to-empty loop, capped pages/sweep so one sweep clears a
#                    backlog deeper than a single poll page (kills throughput cap H2).
#   DEADLETTER_MINUTES: a non-actionable reply older than this is ACKed + audited to a
#                    dead-letter row (recoverable — bus event persists, NOTHING deleted),
#                    so it stops consuming the poll budget (kills starvation H1/H3).
_DRAIN_MAX_PAGES_ENV = "AIRPORT_CHECKIN_DRAIN_MAX_PAGES"
_DEFAULT_DRAIN_MAX_PAGES = 10
_DEADLETTER_MIN_ENV = "AIRPORT_CHECKIN_DEADLETTER_MINUTES"
_DEFAULT_DEADLETTER_MIN = 30  # ~= 3 sweeps at the 10-min default cadence

# Outcome -> terminal status. VALID/URGENT/NEEDS_LUGGAGE_READ accept the arrival;
# FAKE/DUPLICATE/WRONG_TERMINAL reject it. Locked policy (see Key Constraints in
# the brief). Both target values are already legal in the frozen status CHECK.
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


# Join a reply to its ticket via the bus ids the bridge persisted on send.
_MATCH_JOIN = "(bus_message_id = %s OR (%s IS NOT NULL AND bus_thread_id = %s))"


def _write_checkin(conn: Any, *, parent_id: int, thread_id: Optional[str],
                   outcome: str, desk_slug: str) -> str:
    """Guarded receipt write. Returns one of:

    - ``"written"``   — a 'sent' ticket was updated this pass (caller ACKs).
    - ``"resolved"``  — 0-row write, but a matching ticket already carries a
                        durable check-in (``check_in_at`` set: an idempotent replay
                        of an already checked-in/rejected ticket). Caller MUST ACK,
                        else the reply is re-read forever (F1, brief lines 28+624).
    - ``"none"``      — no ticket matches the reply (caller leaves it for next tick).

    The status='sent' precondition makes a re-applied reply a no-op and stops a
    reply from downgrading a candidate/failed/already-checked-in row.
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
              AND """ + _MATCH_JOIN + """
            RETURNING ticket_id
            """,
            (outcome, desk_slug[:200], target_status, parent_id, thread_id, thread_id),
        )
        row = cur.fetchone()
        if row:
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
            return "written"
        # 0-row write: classify in the same transaction so the caller knows whether
        # to ACK (idempotent replay of an already-resolved ticket) or to leave the
        # reply un-acked (no matching ticket).
        cur.execute(
            "SELECT check_in_at FROM airport_tickets WHERE " + _MATCH_JOIN + " LIMIT 1",
            (parent_id, thread_id, thread_id),
        )
        match = cur.fetchone()
    if match is not None and match[0] is not None:
        return "resolved"
    return "none"


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _drain_max_pages() -> int:
    return _int_env(_DRAIN_MAX_PAGES_ENV, _DEFAULT_DRAIN_MAX_PAGES, 1, 100)


def _deadletter_minutes() -> int:
    # 0 disables dead-lettering (non-actionable replies retried forever, legacy behavior).
    return _int_env(_DEADLETTER_MIN_ENV, _DEFAULT_DEADLETTER_MIN, 0, 60 * 24 * 30)


def _msg_age_minutes(msg: dict[str, Any], now: datetime) -> Optional[float]:
    """Minutes since the reply was created, from the daemon's created_at. Returns None
    when there is no parseable timestamp — callers then treat the reply as TOO YOUNG to
    dead-letter (never dead-letter something whose age we cannot establish)."""
    raw = msg.get("created_at") or msg.get("timestamp")
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds() / 60.0


def _dead_letter(conn: Any, base: str, key: str, msg: dict[str, Any], *,
                 reason: str, mid: int) -> None:
    """ACK a non-actionable reply that has exceeded its retry budget and record a
    recoverable dead-letter audit row. NOTHING is deleted — the bus event persists and
    the audit captures message_id + reason so it can be replayed by hand."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, payload, trigger_source, success)
            VALUES (%s, %s, %s, %s, TRUE)
            """,
            (
                "airport_checkin.dead_letter",
                str(msg.get("parent_id") or ""),
                _json_param({
                    "message_id": mid,
                    "reason": reason,
                    "parent_id": msg.get("parent_id"),
                    "from_terminal": msg.get("from_terminal"),
                    "thread_id": msg.get("thread_id"),
                    "body_preview": str(msg.get("body_preview") or "")[:280],
                }),
                "airport_checkin_reader",
            ),
        )
    conn.commit()  # commit BEFORE ack so a crash re-reads (still un-acked) idempotently
    _ack(base, mid, key)


def run_checkin_reader(conn: Any, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Part 1: read desk replies, write receipts, ACK after commit.

    DRAIN-TO-EMPTY: loops the poll (up to DRAIN_MAX_PAGES) so a backlog deeper than one
    poll page clears in a single sweep. A ``seen`` set makes the loop terminate even
    when un-acked young non-actionable replies keep re-appearing at the front of the
    oldest-first ``unread`` window (they are processed once, then skipped).

    DEAD-LETTER: a non-actionable reply (no matching ticket / unparseable body / errored)
    older than DEADLETTER_MINUTES is ACKed + audited so it stops starving the poll budget.
    Younger ones stay un-acked and are retried next sweep (bounded retry)."""
    base, key, slug = _bus_base(), _bridge_key(), _ticketing_slug()
    if not key:
        return {"ok": False, "reason": "ticketing_key_missing", "checked_in": 0}
    _now = now or datetime.now(timezone.utc)
    dl_min = _deadletter_minutes()
    checked_in = already = parsed_none = unmatched = errors = dead_lettered = 0
    seen: set = set()

    def _old_enough(msg: dict[str, Any]) -> bool:
        if dl_min <= 0:
            return False  # dead-lettering disabled
        age = _msg_age_minutes(msg, _now)
        return age is not None and age >= dl_min

    for _page in range(_drain_max_pages()):
        messages = _fetch_inbox(base, slug, key, _poll_limit())
        fresh = [m for m in messages if _safe_int(m.get("id")) not in seen]
        if not fresh:
            break  # inbox drained (or only already-seen young replies remain)
        for msg in fresh:
            mid = _safe_int(msg.get("id"))
            if mid is None:
                # malformed daemon row (no id): un-ackable -> surface as an error, and
                # record the sentinel so the drain loop cannot re-process it forever.
                errors += 1
                seen.add(None)
                logger.warning("airport check-in reply missing id: %s", msg)
                continue
            seen.add(mid)
            try:
                parent_id = msg.get("parent_id")
                sender = str(msg.get("from_terminal") or "").strip()
                if parent_id is None or not sender or sender == slug:
                    # not a ticket reply (or self-echo): non-actionable, dead-letter by age
                    if _old_enough(msg):
                        _dead_letter(conn, base, key, msg, reason="non_reply", mid=mid)
                        dead_lettered += 1
                    continue
                body = _fetch_full_body(base, mid, key) or str(msg.get("body_preview") or "")
                outcome = parse_checkin_outcome(body)
                if outcome is None:
                    if _old_enough(msg):
                        _dead_letter(conn, base, key, msg, reason="parsed_none", mid=mid)
                        dead_lettered += 1
                    else:
                        parsed_none += 1  # young: never guess; leave un-acked, retry next sweep
                    continue
                state = _write_checkin(
                    conn, parent_id=int(parent_id), thread_id=msg.get("thread_id"),
                    outcome=outcome, desk_slug=sender,
                )
                conn.commit()  # commit BEFORE ack so a crash re-reads idempotently
                if state == "written":
                    checked_in += 1
                    _ack(base, mid, key)
                elif state == "resolved":
                    # Idempotent replay: the ticket already carries a durable check-in.
                    already += 1
                    _ack(base, mid, key)
                elif _old_enough(msg):
                    # no matching ticket AND past retry budget -> dead-letter (recoverable)
                    _dead_letter(conn, base, key, msg, reason="unmatched", mid=mid)
                    dead_lettered += 1
                else:
                    unmatched += 1  # young: leave un-acked, retry next sweep
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                if _old_enough(msg):
                    # a persistently-failing reply is dead-lettered so it can't starve the
                    # poll budget forever; the audit row + bus event keep it recoverable.
                    try:
                        _dead_letter(conn, base, key, msg, reason=f"errored:{e}"[:200], mid=mid)
                        dead_lettered += 1
                    except Exception:
                        errors += 1
                else:
                    errors += 1
                logger.warning("airport check-in reply failed id=%s: %s", msg.get("id"), e)
                continue  # one bad reply never stops the batch
    return {"ok": True, "checked_in": checked_in, "already": already,
            "parsed_none": parsed_none, "unmatched": unmatched, "errors": errors,
            "dead_lettered": dead_lettered}


# --- Part 2 — stale-ticket TTL / nudge sweep --------------------------------

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


def _select_escalatable(conn: Any, *, max_nudges: int, cap: int) -> list[dict[str, Any]]:
    """Rows that hit the nudge ceiling but have NOT been escalated yet. Kept
    separate from the nudge scan so a transient escalation-POST failure leaves
    escalated_at NULL and the row is retried next sweep (F2) — never stranded."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, ticket_id, proposed_desk_slug
            FROM airport_tickets
            WHERE status = 'sent'
              AND check_in_at IS NULL
              AND nudge_count >= %s
              AND escalated_at IS NULL
            ORDER BY last_sent_at ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            (max_nudges, cap),
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
            # there is NO rendered pass-body column. Reconstruct the re-nudge body
            # from those persisted fields; do NOT re-fetch the source email or
            # re-run the issue path.
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
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            errors += 1
            logger.warning("airport ttl-nudge row failed id=%s: %s", row.get("id"), e)
            continue

    # Pass 2 — escalate at-max-but-unescalated rows. Decoupled from the nudge pass
    # so a failed escalation POST leaves escalated_at NULL and is retried next
    # sweep (F2: never strand a row at nudge_count>=max without escalating). The
    # escalated_at guard makes this exactly-once on success.
    try:
        esc_rows = _select_escalatable(conn, max_nudges=max_nudges, cap=cap)
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("airport escalation select failed: %s", e)
        esc_rows = []
    for row in esc_rows:
        try:
            esc = _escalate_post(base, key, ticket_id=row["ticket_id"],
                                 desk_slug=row["proposed_desk_slug"])
            if esc.get("error"):
                errors += 1
                conn.rollback()  # release locks; row stays eligible (escalated_at NULL)
                continue
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE airport_tickets
                    SET escalated_at = NOW(), updated_at = NOW()
                    WHERE id = %s AND escalated_at IS NULL
                    """,
                    (row["id"],),
                )
                cur.execute(
                    """
                    INSERT INTO baker_actions
                        (action_type, target_task_id, payload, trigger_source, success)
                    VALUES (%s, %s, %s, %s, TRUE)
                    """,
                    ("airport_ticket.escalated", row["ticket_id"],
                     _json_param({"to": _ESCALATION_SLUG}),
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
            logger.warning("airport escalation row failed id=%s: %s", row.get("id"), e)
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
        reader = run_checkin_reader(conn, now=now)
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
