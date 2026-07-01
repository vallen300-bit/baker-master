"""Airport Ticketing Bridge.

Turns raw Sentinel arrivals into candidate AIRPORT_TICKET records and wakes the
owning desk for check-in. The bridge is deliberately non-substantive: it routes
source-grounded tickets, but it does not decide legal, finance, CP, or nudge
outcomes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from orchestrator.dispatcher import RESERVED_RECIPIENTS, resolve_owner_slug

logger = logging.getLogger("sentinel.airport_ticketing")

_ENABLED_ENV = "AIRPORT_TICKETING_BRIDGE_ENABLED"
_KEYWORDS_ENV = "AIRPORT_TICKETING_KEYWORDS"
_DESK_ENV = "AIRPORT_TICKETING_DESK"
_MATTER_ENV = "AIRPORT_TICKETING_MATTER_SLUG"
_FLIGHT_ENV = "AIRPORT_TICKETING_FLIGHT"
_LOOKBACK_HOURS_ENV = "AIRPORT_TICKETING_LOOKBACK_HOURS"
_MAX_POSTS_ENV = "AIRPORT_TICKETING_MAX_POSTS_PER_TICK"
_BUS_URL_ENV = "AIRPORT_TICKETING_BUS_URL"
_KEY_ENV = "AIRPORT_TICKETING_TERMINAL_KEY"
_DEFAULT_BUS_URL = "https://brisen-lab.onrender.com"
_DEFAULT_KEYWORDS = ("aukera", "annaberg", "lilienmatt")
_DEFAULT_DESK = "baden-baden-desk"
_DEFAULT_MATTER = "lilienmatt"
_DEFAULT_FLIGHT = "aukera-annaberg-financing"
_DEFAULT_LOOKBACK_HOURS = 48
_DEFAULT_MAX_POSTS = 5
_SKIP_EMAIL_SENDER_PATTERNS = (
    "noreply@",
    "no-reply@",
    "notifications@",
    "notification@",
    "@clickup.com",
    "@todoist.com",
)

VALID_CHECK_IN_OUTCOMES = frozenset(
    {"VALID", "FAKE", "DUPLICATE", "WRONG_TERMINAL", "URGENT", "NEEDS_LUGGAGE_READ"}
)
VALID_URGENCY = frozenset({"low", "normal", "high", "urgent"})


@dataclass(frozen=True)
class EmailArrival:
    message_id: str
    thread_id: str
    sender_name: str
    sender_email: str
    subject: str
    full_body: str
    received_date: Optional[datetime]
    source: str
    attachments: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class AirportTicket:
    ticket_id: str
    dedup_key: str
    created_at: datetime
    source_channel: str
    source_id: str
    source_received_at: Optional[datetime]
    originator: str
    suspected_matter_slug: str
    suspected_flight: str
    proposed_desk_slug: str
    urgency_hint: str
    luggage: tuple[str, ...]
    why_ticketed: tuple[str, ...]
    known_limits: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "contract": "AIRPORT_TICKET v1",
            "ticket_id": self.ticket_id,
            "created_at": self.created_at.isoformat(),
            "source_channel": self.source_channel,
            "source_id": self.source_id,
            "source_received_at": (
                self.source_received_at.isoformat() if self.source_received_at else None
            ),
            "originator": self.originator,
            "suspected_matter_slug": self.suspected_matter_slug,
            "suspected_flight": self.suspected_flight,
            "proposed_desk_slug": self.proposed_desk_slug,
            "urgency_hint": self.urgency_hint,
            "luggage": list(self.luggage),
            "why_ticketed": list(self.why_ticketed),
            "known_limits": list(self.known_limits),
        }


def bridge_enabled() -> bool:
    raw = os.environ.get(_ENABLED_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# BOX5_TICKETING_RUNNER_1 — runner kill-switch + cursor + gauge constants.
_FAST_LANE_ENV = "BOX5_FAST_LANE_ENABLED"
# DISTINCT watermark key — must never collide with the live email poll
# ('email_poll' / 'email_poll_checked'), or the runner would rewind that cursor.
_WATERMARK_SOURCE = "airport_ticketing:email"
_STUCK_ARRIVAL_MINUTES = 30
# Sentinel desk for REJECT_NOISE rows (build_email_ticket returned None, so no real
# desk owns the arrival). reserve_noise_row keys the dedup on this so repeated noise
# de-dups; the row exists only to carry the terminal_status.
_NOISE_DESK = "unrouted"


def fast_lane_enabled() -> bool:
    """When False, every non-deterministic-clear arrival routes to the safe default
    terminal_status='TICKET' (full desk review). Freeze-by-flag kill switch
    (blocker 7b); default closed, no deploy needed to freeze a misroute. BRIEF-C has
    no fast lane yet — this only future-proofs D/E, but it is read + honored now."""
    raw = os.environ.get(_FAST_LANE_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def trigger_state_get_watermark(source: str) -> datetime:
    """Lazy wrapper over the trigger_state singleton (avoids a module-load import
    cycle; single monkeypatch point for tests)."""
    from triggers.state import trigger_state

    return trigger_state.get_watermark(source)


def trigger_state_watermark_raw(source: str) -> Optional[datetime]:
    """Lazy wrapper: raw watermark (None when NO row exists), NOT the NOW-24h
    fallback. run_tick needs to tell 'never activated' from a real cursor so a blank
    cursor starts at the full lookback floor instead of stranding the 24h→lookback
    backlog."""
    from triggers.state import trigger_state

    return trigger_state.get_watermark_raw(source)


def trigger_state_set_watermark(source: str, timestamp: datetime) -> None:
    from triggers.state import trigger_state

    trigger_state.set_watermark(source, timestamp)


def max_posts_per_tick() -> int:
    try:
        value = int(os.environ.get(_MAX_POSTS_ENV, str(_DEFAULT_MAX_POSTS)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_POSTS
    return max(0, min(value, 25))


def lookback_hours() -> int:
    try:
        value = int(os.environ.get(_LOOKBACK_HOURS_ENV, str(_DEFAULT_LOOKBACK_HOURS)))
    except (TypeError, ValueError):
        return _DEFAULT_LOOKBACK_HOURS
    return max(1, min(value, 24 * 14))


def active_keywords() -> tuple[str, ...]:
    raw = os.environ.get(_KEYWORDS_ENV, "")
    values = [part.strip().lower() for part in raw.split(",") if part.strip()]
    return tuple(values) if values else _DEFAULT_KEYWORDS


def _desk_slug() -> str:
    return os.environ.get(_DESK_ENV, _DEFAULT_DESK).strip() or _DEFAULT_DESK


def _matter_slug() -> str:
    return os.environ.get(_MATTER_ENV, _DEFAULT_MATTER).strip() or _DEFAULT_MATTER


def _flight_name() -> str:
    return os.environ.get(_FLIGHT_ENV, _DEFAULT_FLIGHT).strip() or _DEFAULT_FLIGHT


def _json_param(payload: dict[str, Any]) -> Any:
    try:
        import psycopg2.extras

        return psycopg2.extras.Json(payload)
    except Exception:
        return json.dumps(payload)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_text(value: str, *, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:limit]


def _ticket_id(source_channel: str, source_id: str, desk_slug: str) -> str:
    raw = f"AIRPORT_TICKET v1|{source_channel}|{source_id}|{desk_slug}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"airport-ticket-v1-{digest}"


def _dedup_key(source_channel: str, source_id: str, desk_slug: str) -> str:
    return f"airport-ticket:v1:{source_channel}:{source_id}:{desk_slug}"


def _urgency_for(arrival: EmailArrival, matched_keywords: list[str]) -> str:
    text = f"{arrival.subject} {arrival.full_body[:1000]}".lower()
    urgent_terms = ("urgent", "absolute priority", "today", "closing", "sign", "notary")
    if any(term in text for term in urgent_terms):
        return "urgent"
    if matched_keywords:
        return "high"
    return "normal"


def _originator(arrival: EmailArrival) -> str:
    name = _normalize_text(arrival.sender_name, limit=120)
    email = _normalize_text(arrival.sender_email, limit=160)
    if name and email:
        return f"{name} <{email}>"
    return name or email or "unknown"


def _is_automated_email_arrival(arrival: EmailArrival) -> bool:
    sender = (arrival.sender_email or "").strip().lower()
    if not sender:
        return False
    return any(pattern in sender for pattern in _SKIP_EMAIL_SENDER_PATTERNS)


def build_email_ticket(
    arrival: EmailArrival,
    *,
    now: Optional[datetime] = None,
    keywords: tuple[str, ...] | None = None,
) -> Optional[AirportTicket]:
    if _is_automated_email_arrival(arrival):
        return None

    keys = keywords or active_keywords()
    haystack = f"{arrival.subject} {arrival.full_body}".lower()
    matched = [kw for kw in keys if kw and kw.lower() in haystack]
    if not matched:
        return None

    desk_slug = resolve_owner_slug(_desk_slug()) or _desk_slug()
    if not desk_slug or desk_slug in RESERVED_RECIPIENTS:
        logger.warning("airport ticketing invalid proposed desk: %s", desk_slug)
        return None

    created_at = now or _utc_now()
    ticket_id = _ticket_id("email", arrival.message_id, desk_slug)
    body_preview = _normalize_text(arrival.full_body, limit=260)
    luggage = [
        f"email subject: {arrival.subject or '(no subject)'}",
        f"transport source: {arrival.source or 'unknown'}",
        f"thread_id: {arrival.thread_id or arrival.message_id}",
    ]
    if body_preview:
        luggage.append(f"body_preview: {body_preview}")
    for att in arrival.attachments:
        filename = _normalize_text(str(att.get("filename") or "unnamed"), limit=220)
        mime_type = _normalize_text(str(att.get("mime_type") or "unknown"), limit=120)
        size = att.get("size_bytes")
        suffix = f", {size} bytes" if size is not None else ""
        luggage.append(f"attachment: {filename} ({mime_type}{suffix})")

    why = [f"matched active flight keyword(s): {', '.join(sorted(set(matched)))}"]
    if arrival.received_date:
        why.append(f"received_at: {arrival.received_date.isoformat()}")

    return AirportTicket(
        ticket_id=ticket_id,
        dedup_key=_dedup_key("email", arrival.message_id, desk_slug),
        created_at=created_at,
        source_channel="email",
        source_id=arrival.message_id,
        source_received_at=arrival.received_date,
        originator=_originator(arrival),
        suspected_matter_slug=_matter_slug(),
        suspected_flight=_flight_name(),
        proposed_desk_slug=desk_slug,
        urgency_hint=_urgency_for(arrival, matched),
        luggage=tuple(luggage),
        why_ticketed=tuple(why),
        known_limits=(
            "Ticketing Bridge did not read or interpret attachments.",
            "Ticketing Bridge did not decide condition precedent status.",
            "Owning desk must check in as VALID, FAKE, DUPLICATE, WRONG_TERMINAL, URGENT, or NEEDS_LUGGAGE_READ.",
        ),
    )


def ensure_airport_ticket_table(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS airport_tickets (
                id BIGSERIAL PRIMARY KEY,
                ticket_id TEXT NOT NULL UNIQUE,
                dedup_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'candidate',
                source_channel TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_received_at TIMESTAMPTZ,
                originator TEXT,
                suspected_matter_slug TEXT,
                suspected_flight TEXT,
                proposed_desk_slug TEXT NOT NULL,
                urgency_hint TEXT NOT NULL DEFAULT 'normal',
                ticket JSONB NOT NULL DEFAULT '{}'::jsonb,
                bus_message_id BIGINT,
                bus_thread_id TEXT,
                last_sent_at TIMESTAMPTZ,
                check_in_outcome TEXT,
                check_in_at TIMESTAMPTZ,
                check_in_by TEXT,
                failure_reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT airport_tickets_status_check
                    CHECK (status IN ('candidate', 'sent', 'failed', 'checked_in', 'rejected')),
                CONSTRAINT airport_tickets_source_channel_check
                    CHECK (source_channel IN ('email', 'whatsapp', 'plaud', 'clickup', 'calendar', 'other')),
                CONSTRAINT airport_tickets_urgency_check
                    CHECK (urgency_hint IN ('low', 'normal', 'high', 'urgent')),
                CONSTRAINT airport_tickets_check_in_outcome_check
                    CHECK (
                        check_in_outcome IS NULL OR
                        check_in_outcome IN (
                            'VALID',
                            'FAKE',
                            'DUPLICATE',
                            'WRONG_TERMINAL',
                            'URGENT',
                            'NEEDS_LUGGAGE_READ'
                        )
                    )
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_airport_tickets_source
                ON airport_tickets (source_channel, source_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_airport_tickets_desk_status
                ON airport_tickets (proposed_desk_slug, status, last_sent_at DESC)
            """
        )
        # BOX5_RECEIPT_TTL_1: nudge-state columns for the stale-ticket TTL sweep.
        # Mirrors migrations/20260630_airport_tickets_nudge_state.sql so an
        # already-bootstrapped DB (where CREATE TABLE IF NOT EXISTS no-ops) still
        # gains the columns — the documented migration-vs-bootstrap drift fix.
        cur.execute(
            "ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS last_nudged_at TIMESTAMPTZ"
        )
        cur.execute(
            "ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS nudge_count INTEGER NOT NULL DEFAULT 0"
        )
        cur.execute(
            "ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMPTZ"
        )
    # Additive terminal-classification axis (BOX5_SCHEMA_FOUNDATION_1 / BRIEF-B).
    # Mirrors migrations/20260630_airport_tickets_terminal_columns.sql. The
    # CREATE TABLE IF NOT EXISTS above never migrates an already-created prod
    # table, so we ALTER here; this also re-asserts the constraint on every
    # Render restart so the migration can't be silently reverted.
    ensure_airport_ticket_terminal_columns(conn)


def ensure_airport_ticket_terminal_columns(conn: Any) -> None:
    """Additive terminal-classification axis on airport_tickets (BRIEF-B).

    CREATE TABLE IF NOT EXISTS does NOT migrate an already-created prod table, so
    we ALTER here and mirror migrations/20260630_airport_tickets_terminal_columns.sql
    verbatim (Lesson #50 migration-vs-bootstrap drift). Re-asserted on every Render
    restart so the migration can't be silently reverted.

    terminal_status is ORTHOGONAL to the live `status` lifecycle and to
    `check_in_outcome` — new axis, new column, new CHECK. Do NOT touch those two.

    All columns nullable (or NOT NULL with a list DEFAULT) -> safe on a populated
    table; no backfill required.
    """
    try:
        with conn.cursor() as cur:
            # Terminal-result fields written later by the runner (BRIEF-C) and the
            # fast lanes (BRIEF-D/E). BRIEF-B only creates the columns.
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_status TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_reason TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS project_code TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS matter_slug TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS desk_owner TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS source_refs JSONB NOT NULL DEFAULT '[]'::jsonb")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS confidence NUMERIC(3,2)")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS model_used TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS cost_tier TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS classification_version TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS registry_version TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS manifest_match_signals JSONB NOT NULL DEFAULT '[]'::jsonb")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS raw_source_table TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS raw_source_id TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_outcome_written_at TIMESTAMPTZ")

            # terminal_status CHECK — EXACTLY 6 states. VISIBLE_HOLD is DELIBERATELY
            # EXCLUDED (locked decision #4677.7): it gets its own owner + TTL +
            # escalation + sweep brief; adding it here would make it prematurely
            # writable. Do NOT "fix" this omission. DROP-then-ADD mirrors the
            # signal_queue precedent so re-runs are clean (idempotent).
            cur.execute("ALTER TABLE airport_tickets DROP CONSTRAINT IF EXISTS airport_tickets_terminal_status_check")
            cur.execute(
                """
                ALTER TABLE airport_tickets ADD CONSTRAINT airport_tickets_terminal_status_check
                    CHECK (
                        terminal_status IS NULL OR
                        terminal_status IN (
                            'DUPLICATE',
                            'REJECT_NOISE',
                            'REJECT_LOW_RELEVANCE',
                            'FAST_TICKET',
                            'TICKET',
                            'FILE_UNSORTED'
                        )
                    )
                """
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def fetch_email_arrivals(
    conn: Any,
    *,
    since: datetime,
    limit: int = 50,
    keywords: tuple[str, ...] | None = None,
) -> list[EmailArrival]:
    keys = keywords or active_keywords()
    if not keys:
        return []
    clauses: list[str] = []
    params: list[Any] = [since]
    for keyword in keys:
        pattern = f"%{keyword}%"
        clauses.append("(subject ILIKE %s OR full_body ILIKE %s)")
        params.extend([pattern, pattern])
    params.append(max(1, min(int(limit), 200)))
    where = " OR ".join(clauses)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT message_id, thread_id, sender_name, sender_email,
                   subject, full_body, received_date, source
            FROM email_messages
            WHERE received_date >= %s
              AND ({where})
            -- BOX5_TICKETING_RUNNER_1 P1-A: OLDEST-FIRST. The runner processes the
            -- backlog in cursor order and advances the watermark only over the
            -- contiguous fully-processed prefix. Newest-first (DESC) under a per-tick
            -- cap would let the cursor jump to the newest processed row while older
            -- un-processed rows fall behind since=watermark -> permanent loss.
            ORDER BY received_date ASC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = cur.fetchall()

    message_ids = [row[0] for row in rows if row and row[0]]
    attachment_map = _fetch_email_attachments(conn, message_ids)
    arrivals: list[EmailArrival] = []
    for row in rows:
        received = row[6]
        if isinstance(received, datetime) and received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        arrivals.append(
            EmailArrival(
                message_id=str(row[0] or ""),
                thread_id=str(row[1] or row[0] or ""),
                sender_name=str(row[2] or ""),
                sender_email=str(row[3] or ""),
                subject=str(row[4] or ""),
                full_body=str(row[5] or ""),
                received_date=received if isinstance(received, datetime) else None,
                source=str(row[7] or ""),
                attachments=tuple(attachment_map.get(str(row[0] or ""), ())),
            )
        )
    return arrivals


def _fetch_email_attachments(conn: Any, message_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not message_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT message_id, filename, mime_type, size_bytes
            FROM email_attachments
            WHERE message_id = ANY(%s)
            ORDER BY message_id, filename
            """,
            (message_ids,),
        )
        rows = cur.fetchall()
    out: dict[str, list[dict[str, Any]]] = {}
    for message_id, filename, mime_type, size_bytes in rows:
        out.setdefault(str(message_id), []).append(
            {"filename": filename, "mime_type": mime_type, "size_bytes": size_bytes}
        )
    return out


def reserve_ticket(conn: Any, ticket: AirportTicket) -> dict[str, Any]:
    payload = ticket.payload()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, bus_message_id
            FROM airport_tickets
            WHERE dedup_key = %s
            LIMIT 1
            """,
            (ticket.dedup_key,),
        )
        existing = cur.fetchone()
        if existing:
            status = existing[1]
            bus_message_id = existing[2]
            if status == "failed" and bus_message_id is None:
                cur.execute(
                    """
                    UPDATE airport_tickets
                    SET status = 'candidate',
                        ticket = %s,
                        failure_reason = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id
                    """,
                    (_json_param(payload), existing[0]),
                )
                row = cur.fetchone()
                return {"reserved": True, "id": row[0], "retry": True}
            return {
                "reserved": False,
                "id": existing[0],
                "status": status,
                "bus_message_id": bus_message_id,
            }

        cur.execute(
            """
            INSERT INTO airport_tickets
                (ticket_id, dedup_key, source_channel, source_id, source_received_at,
                 originator, suspected_matter_slug, suspected_flight,
                 proposed_desk_slug, urgency_hint, ticket)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (dedup_key) DO NOTHING
            RETURNING id
            """,
            (
                ticket.ticket_id,
                ticket.dedup_key,
                ticket.source_channel,
                ticket.source_id,
                ticket.source_received_at,
                ticket.originator,
                ticket.suspected_matter_slug,
                ticket.suspected_flight,
                ticket.proposed_desk_slug,
                ticket.urgency_hint,
                _json_param(payload),
            ),
        )
        row = cur.fetchone()
        if not row:
            return {"reserved": False, "id": None}
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, payload, trigger_source, success)
            VALUES (%s, %s, %s, %s, TRUE)
            """,
            (
                "airport_ticket.created",
                ticket.ticket_id,
                _json_param(
                    {
                        "ticket_id": ticket.ticket_id,
                        "source_channel": ticket.source_channel,
                        "source_id": ticket.source_id,
                        "proposed_desk_slug": ticket.proposed_desk_slug,
                    }
                ),
                "airport_ticketing_bridge",
            ),
        )
    return {"reserved": True, "id": row[0]}


def _bridge_key() -> str:
    return (
        os.environ.get(_KEY_ENV, "").strip()
        or os.environ.get("BRISEN_LAB_TERMINAL_KEY_TICKETING", "").strip()
        or os.environ.get("BRISEN_LAB_TERMINAL_KEY_DISPATCHER", "").strip()
        or os.environ.get("BRISEN_LAB_TERMINAL_KEY", "").strip()
    )


def _request_json(
    method: str,
    url: str,
    *,
    key: str,
    payload: Optional[dict[str, Any]] = None,
    timeout: int = 15,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"X-Terminal-Key": key}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return {"ok": False, "error": f"http_{e.code}", "body": body}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _bus_message_id(result: dict[str, Any]) -> Optional[int]:
    for key in ("id", "message_id", "event_id"):
        value = result.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    event = result.get("event")
    if isinstance(event, dict) and event.get("id") is not None:
        try:
            return int(event["id"])
        except (TypeError, ValueError):
            return None
    message = result.get("message")
    if isinstance(message, dict) and message.get("id") is not None:
        try:
            return int(message["id"])
        except (TypeError, ValueError):
            return None
    return None


def format_ticket_for_bus(ticket: AirportTicket) -> str:
    luggage = "\n".join(f"- {item}" for item in ticket.luggage) or "- none"
    why = "\n".join(f"- {item}" for item in ticket.why_ticketed) or "- none"
    limits = "\n".join(f"- {item}" for item in ticket.known_limits) or "- none"
    return (
        f"TO: {ticket.proposed_desk_slug}\n"
        "FROM: ticketing-desk\n"
        f"RE: AIRPORT_TICKET {ticket.suspected_flight}\n\n"
        "AIRPORT_TICKET v1\n"
        f"ticket_id: {ticket.ticket_id}\n"
        f"created_at: {ticket.created_at.isoformat()}\n"
        f"source_channel: {ticket.source_channel}\n"
        f"source_id: {ticket.source_id}\n"
        f"originator: {ticket.originator}\n"
        f"suspected_matter_slug: {ticket.suspected_matter_slug}\n"
        f"suspected_flight: {ticket.suspected_flight}\n"
        f"proposed_desk_slug: {ticket.proposed_desk_slug}\n"
        f"urgency_hint: {ticket.urgency_hint}\n"
        "luggage:\n"
        f"{luggage}\n"
        "why_ticketed:\n"
        f"{why}\n"
        "known_limits:\n"
        f"{limits}\n\n"
        "Check-in required: reply with VALID, FAKE, DUPLICATE, WRONG_TERMINAL, "
        "URGENT, or NEEDS_LUGGAGE_READ."
    )


def post_ticket_to_bus(ticket: AirportTicket) -> dict[str, Any]:
    recipient = resolve_owner_slug(ticket.proposed_desk_slug)
    if not recipient or recipient in RESERVED_RECIPIENTS:
        return {"ok": False, "error": "invalid_recipient"}
    key = _bridge_key()
    if not key:
        return {"ok": False, "error": "ticketing_key_missing"}
    base = os.environ.get(_BUS_URL_ENV, _DEFAULT_BUS_URL).rstrip("/")
    payload = {
        "kind": "dispatch",
        "body": format_ticket_for_bus(ticket),
        "to": [recipient],
        "tier_required": "B",
        "topic": f"airport-ticketing/{ticket.suspected_flight}",
    }
    result = _request_json("POST", f"{base}/msg/{recipient}", key=key, payload=payload)
    if result.get("error"):
        return result
    result["ok"] = True
    return result


def mark_ticket_sent(
    conn: Any,
    *,
    ticket: AirportTicket,
    ticket_row_id: int,
    bus_message_id: Optional[int],
    bus_thread_id: Optional[str],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE airport_tickets
            SET status = 'sent',
                bus_message_id = %s,
                bus_thread_id = %s,
                last_sent_at = NOW(),
                failure_reason = NULL,
                updated_at = NOW()
            WHERE id = %s
            """,
            (bus_message_id, bus_thread_id, ticket_row_id),
        )
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, payload, trigger_source, success)
            VALUES (%s, %s, %s, %s, TRUE)
            """,
            (
                "airport_ticket.bus_sent",
                ticket.ticket_id,
                _json_param(
                    {
                        "ticket_id": ticket.ticket_id,
                        "bus_message_id": bus_message_id,
                        "bus_thread_id": bus_thread_id,
                        "proposed_desk_slug": ticket.proposed_desk_slug,
                    }
                ),
                "airport_ticketing_bridge",
            ),
        )


def mark_ticket_failed(
    conn: Any,
    *,
    ticket: AirportTicket,
    ticket_row_id: int,
    error: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE airport_tickets
            SET status = 'failed',
                failure_reason = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (error[:500], ticket_row_id),
        )
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, payload, trigger_source, success, error_message)
            VALUES (%s, %s, %s, %s, FALSE, %s)
            """,
            (
                "airport_ticket.bus_failed",
                ticket.ticket_id,
                _json_param({"ticket_id": ticket.ticket_id, "error": error[:500]}),
                "airport_ticketing_bridge",
                error[:500],
            ),
        )


def issue_ticket(ticket: AirportTicket, conn: Any) -> dict[str, Any]:
    reserved = reserve_ticket(conn, ticket)
    if not reserved.get("reserved"):
        return {"skipped": True, "reason": "duplicate", "id": reserved.get("id")}
    ticket_row_id = int(reserved["id"])
    result = post_ticket_to_bus(ticket)
    if not result.get("ok"):
        error = str(result.get("error") or "unknown")
        mark_ticket_failed(conn, ticket=ticket, ticket_row_id=ticket_row_id, error=error)
        return {"ok": False, "reason": "bus_failed", "error": error}

    message_id = _bus_message_id(result)
    mark_ticket_sent(
        conn,
        ticket=ticket,
        ticket_row_id=ticket_row_id,
        bus_message_id=message_id,
        bus_thread_id=result.get("thread_id"),
    )
    return {"ok": True, "id": ticket_row_id, "bus_message_id": message_id}


def write_terminal_status(
    conn: Any,
    *,
    ticket_row_id: int,
    terminal_status: str,
    terminal_reason: str,
    raw_source_id: str,
) -> bool:
    """Single idempotent terminal write — the ONLY path that writes terminal_status.

    Returns True iff THIS call wrote the terminal outcome (rowcount == 1). The
    ``AND terminal_status IS NULL`` guard makes re-runs and lease-expired reclaims
    no-ops (0 rows). dedup_key UNIQUE guards duplicate ROWS; this guards duplicate
    terminal WRITES. Caller wraps in a per-row try/except + rollback.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE airport_tickets
               SET terminal_status = %s,
                   terminal_reason = %s,
                   processed_at = NOW(),
                   terminal_outcome_written_at = NOW(),
                   raw_source_table = 'email_messages',
                   raw_source_id = %s
             WHERE id = %s
               AND terminal_status IS NULL
            RETURNING id, ticket_id
            """,
            (terminal_status, terminal_reason, raw_source_id, ticket_row_id),
        )
        won = cur.fetchone()
        if won is None:
            return False
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, payload, trigger_source, success)
            VALUES ('airport_ticket.terminal_written', %s, %s,
                    'airport_ticketing_bridge', TRUE)
            """,
            (
                won[1],
                _json_param(
                    {
                        "ticket_id": won[1],
                        "terminal_status": terminal_status,
                        "terminal_reason": terminal_reason,
                    }
                ),
            ),
        )
        return True
    finally:
        cur.close()


def _claim_for_terminal(
    conn: Any, ticket_row_id: int
) -> Optional[tuple[int, Optional[str]]]:
    """Intra-tick row claim under FOR UPDATE SKIP LOCKED.

    Returns ``None`` when the row is held by a concurrent overlapping tick (SKIP
    LOCKED skipped it) or is missing — the caller treats that as ``lease_skipped``
    and must NOT advance the watermark past the arrival (it is not ours to finish).

    Returns ``(id, existing_terminal_status)`` when THIS tick holds the row lock:
      - ``existing_terminal_status is None`` -> we won a fresh row, proceed to write.
      - ``existing_terminal_status is not None`` -> already terminal on a prior tick;
        the arrival is idempotently DONE, no write needed, safe to advance past it.

    The terminal_status is read here (NOT filtered in the WHERE) precisely so
    already-terminal is distinguishable from locked — otherwise a re-fetched,
    already-cleared row would look identical to a concurrently-held one and pin the
    watermark forever. Single-replica is inherited from scheduler_lease 8800100 —
    this is row-level overlap safety only, NOT a process lease."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, terminal_status
              FROM airport_tickets
             WHERE id = %s
             LIMIT 1
             FOR UPDATE SKIP LOCKED
            """,
            (ticket_row_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return (int(row[0]), row[1])
    finally:
        cur.close()


def reserve_noise_row(conn: Any, arrival: EmailArrival) -> Optional[int]:
    """Shape (i): reserve a minimal airport_tickets row for a REJECT_NOISE arrival
    (build_email_ticket returned None) so the single status-guarded terminal write
    has a target. Keyed by dedup_key on the noise sentinel desk, so repeated noise
    de-dups and the terminal write stays idempotent. Returns the row id, or None if
    no id could be obtained (caller skips, never crashes)."""
    dedup = _dedup_key("email", arrival.message_id, _NOISE_DESK)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO airport_tickets
                (ticket_id, dedup_key, source_channel, source_id,
                 source_received_at, proposed_desk_slug)
            VALUES (%s, %s, 'email', %s, %s, %s)
            ON CONFLICT (dedup_key) DO NOTHING
            RETURNING id
            """,
            (
                f"airport-noise:{arrival.message_id}",
                dedup,
                arrival.message_id,
                arrival.received_date,
                _NOISE_DESK,
            ),
        )
        row = cur.fetchone()
        if row:
            return int(row[0])
        # dedup collision (already reserved on a prior tick) -> fetch the existing id.
        cur.execute(
            "SELECT id FROM airport_tickets WHERE dedup_key = %s LIMIT 1",
            (dedup,),
        )
        existing = cur.fetchone()
        return int(existing[0]) if existing else None
    finally:
        cur.close()


def _count_stuck_arrivals(conn: Any) -> int:
    """Journey gauge (NOT scheduler liveness): arrivals that never reached a
    terminal disposition. source_received_at is a real existing column."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT COUNT(*)
              FROM airport_tickets
             WHERE terminal_status IS NULL
               AND source_received_at < NOW() - (%s || ' minutes')::interval
            """,
            (_STUCK_ARRIVAL_MINUTES,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        cur.close()


def _advance(cur_max: Optional[datetime], candidate: Optional[datetime]) -> Optional[datetime]:
    """Track the max received_date processed this tick (UTC-coerced)."""
    if candidate is None:
        return cur_max
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    if cur_max is None or candidate > cur_max:
        return candidate
    return cur_max


def run_tick(*, now: Optional[datetime] = None) -> dict[str, Any]:
    # (a) MASTER GATE — ships dark behind AIRPORT_TICKETING_BRIDGE_ENABLED.
    if not bridge_enabled():
        return {"skipped": True, "reason": f"{_ENABLED_ENV} off"}
    cap = max_posts_per_tick()
    if cap <= 0:
        return {"skipped": True, "reason": f"{_MAX_POSTS_ENV}=0"}

    try:
        from memory.store_back import SentinelStoreBack

        store = SentinelStoreBack._get_global_instance()
    except Exception as e:
        logger.warning("airport ticketing store unavailable: %s", e)
        return {"skipped": True, "reason": "store_unavailable"}

    conn = store._get_conn()
    if not conn:
        return {"skipped": True, "reason": "database_unavailable"}

    # existing counters + NEW journey counters
    issued = skipped = failed = 0
    claimed = terminal_written = lease_skipped = 0
    deterministic_cleared = defaulted_ticket = 0
    fast_lane = fast_lane_enabled()  # honored now; only future-proofs D/E
    current = now or _utc_now()
    # (P1-A) CONTIGUOUS-PREFIX WATERMARK. The cursor may only advance over the
    # unbroken run of fully-processed arrivals from the oldest. `contiguous` flips
    # False at the first arrival that is NOT fully done (failure, bus-fail, lease
    # skip, reserve race, cap break); once False the watermark stops advancing so
    # every arrival at/after the gap stays re-fetchable next tick. NEVER a global
    # max — that is the P1-A/P1-B data-loss class codex flagged.
    watermark_candidate: Optional[datetime] = None
    contiguous = True
    try:
        ensure_airport_ticket_table(conn)  # idempotent; also ensures BRIEF-B terminal cols

        # (b) CURSOR — per-source watermark replaces the constant lookback. Keep the
        #     lookback as a FLOOR so a fresh/blank cursor cannot scan unbounded. The
        #     watermark uses a DISTINCT key, never the live email poll.
        #
        #     (P1 blank-cursor) On FIRST activation there is NO watermark row.
        #     trigger_state.get_watermark would return its NOW-24h fallback, and
        #     max(NOW-24h, floor=NOW-lookback) collapses to NOW-24h whenever the
        #     lookback exceeds 24h (default 48h) — so the 24h→lookback backlog is
        #     skipped before the first advance and stranded forever. Read the RAW row:
        #       - None (missing OR DB error) -> start at the full lookback FLOOR (safe
        #         over-scan; the status-guard + dedup make the re-scan idempotent).
        #       - a real cursor -> max(wm, floor) so we never rewind past the window.
        floor = current - timedelta(hours=lookback_hours())
        try:
            raw_wm = trigger_state_watermark_raw(_WATERMARK_SOURCE)
        except Exception as e:
            logger.warning("airport ticketing watermark read failed, using floor: %s", e)
            raw_wm = None
        since = floor if raw_wm is None else max(raw_wm, floor)

        arrivals = fetch_email_arrivals(conn, since=since, limit=cap * 4)

        for arrival in arrivals:
            if issued >= cap:
                # (P1-A) Cap reached: this arrival + every newer one (ASC order) are
                # UN-processed. They must stay re-fetchable, so the contiguous prefix
                # ends here — never advance the watermark past an un-processed row.
                contiguous = False
                break

            # `done` = this arrival reached a definite terminal disposition this tick
            # (cleared / ticketed / idempotent no-op). Only a done arrival at the head
            # of an unbroken run advances the cursor. Anything not done freezes it.
            done = False

            # (c) PER-ROW FAULT ISOLATION — one bad row never crashes the tick, and
            #     an exception NEVER auto-clears (blocker D3): it routes to `failed`,
            #     never to a deterministic clear, and never advances the cursor.
            try:
                ticket = build_email_ticket(arrival, now=current)

                if ticket is None:
                    # (d) DETERMINISTIC CLEAR — REJECT_NOISE = AUTOMATED SENDER ONLY.
                    #     (P1-C, cowork-ah1 bus #4756) build_email_ticket returns None
                    #     for an automated sender OR a no-active-keyword arrival, but
                    #     the no-keyword case is UNREACHABLE here: fetch_email_arrivals
                    #     prefilters on active keywords (ILIKE), so only automated-
                    #     sender Nones enter the runner. We assert that cause
                    #     explicitly rather than infer it, so REJECT_NOISE means
                    #     automated-sender ONLY. (Feed-widening — "every arrival ends
                    #     visible" — is a deferred post-A-E follow-up brief; do NOT
                    #     broaden the fetch scan here.)
                    if _is_automated_email_arrival(arrival):
                        noise_id = reserve_noise_row(conn, arrival)
                        if noise_id is not None:
                            if write_terminal_status(
                                conn,
                                ticket_row_id=noise_id,
                                terminal_status="REJECT_NOISE",
                                terminal_reason="automated_sender",
                                raw_source_id=arrival.message_id,
                            ):
                                terminal_written += 1
                                deterministic_cleared += 1
                            skipped += 1
                            conn.commit()
                            done = True
                        else:
                            # No target row could be reserved (transient) — do NOT
                            # clear, do NOT advance; retry next tick.
                            conn.rollback()
                            skipped += 1
                    else:
                        # Defensive: a None that is NOT an automated sender (only the
                        # dead no-keyword path or an invalid-desk misconfig) must
                        # never auto-clear (blocker D3). Surface + hold, do NOT advance.
                        conn.rollback()
                        skipped += 1
                        logger.warning(
                            "airport_ticketing: non-automated None ticket held (not "
                            "cleared): %s",
                            arrival.message_id,
                        )
                else:
                    # (e) RESERVE — DUPLICATE deterministic clear via dedup collision.
                    result = issue_ticket(ticket, conn)
                    row_id = result.get("id")

                    if (
                        result.get("skipped")
                        and result.get("reason") == "duplicate"
                        and row_id
                    ):
                        claim = _claim_for_terminal(conn, row_id)
                        if claim is None:
                            # Held by a concurrent tick — not ours; hold the cursor.
                            lease_skipped += 1
                            conn.commit()
                        elif claim[1] is not None:
                            # Already terminal on a prior tick — idempotent no-op, DONE.
                            conn.commit()
                            done = True
                        else:
                            claimed += 1
                            if write_terminal_status(
                                conn,
                                ticket_row_id=row_id,
                                terminal_status="DUPLICATE",
                                terminal_reason="dedup_key_collision",
                                raw_source_id=arrival.message_id,
                            ):
                                terminal_written += 1
                                deterministic_cleared += 1
                            skipped += 1
                            conn.commit()
                            done = True

                    # (P1-B) BUS-FAIL = FAILURE — checked BEFORE the not-row_id branch.
                    #     issue_ticket bus_failed returns ok=False with NO id; the old
                    #     code hit `not row_id` first and mis-counted it as lease_skipped
                    #     while the watermark advanced -> silent drop. It is a FAILURE:
                    #     terminal_status stays NULL, `failed` increments, the cursor
                    #     does NOT advance past it, and reserve_ticket retries it next
                    #     tick.
                    elif not result.get("ok") and result.get("reason") == "bus_failed":
                        failed += 1
                        conn.commit()  # persist mark_ticket_failed (status='failed' + audit)

                    # (f) None row_id (reserve race: another tick won ON CONFLICT) —
                    #     no-op, never a crash, NOT ours to finish, so hold the cursor.
                    elif not row_id:
                        lease_skipped += 1
                        conn.commit()

                    else:
                        # (g) SAFE DEFAULT — TICKET (full desk review). No D/E fast
                        #     lane built (and/or fast_lane False) -> every non-clear
                        #     arrival lands here; result is ok=True with a row_id.
                        claim = _claim_for_terminal(conn, row_id)
                        if claim is None:
                            lease_skipped += 1
                            conn.commit()
                        elif claim[1] is not None:
                            # Already terminal (idempotent re-tick) — DONE, no rewrite.
                            if result.get("ok"):
                                issued += 1
                            conn.commit()
                            done = True
                        else:
                            claimed += 1
                            if write_terminal_status(
                                conn,
                                ticket_row_id=row_id,
                                terminal_status="TICKET",
                                terminal_reason="safe_default_desk_review",
                                raw_source_id=arrival.message_id,
                            ):
                                terminal_written += 1
                                defaulted_ticket += 1
                            if result.get("ok"):
                                issued += 1
                            conn.commit()
                            done = True

            except Exception as exc:  # ERROR NEVER AUTO-CLEARS (blocker D3)
                try:
                    conn.rollback()
                except Exception:
                    pass
                failed += 1
                done = False
                logger.warning("airport_ticketing run_tick row failed: %s", exc)

            # (P1-A) Contiguous-prefix advance: extend the cursor only while every
            # arrival so far is done; the first not-done arrival freezes it for the
            # rest of the tick so the gap stays re-fetchable next tick.
            if not done:
                contiguous = False
            elif contiguous:
                watermark_candidate = _advance(
                    watermark_candidate, arrival.received_date
                )

        # (h) ADVANCE CURSOR to the end of the contiguous fully-processed prefix.
        #     A failed/held/un-processed arrival earlier in the batch keeps the
        #     watermark behind it so it is re-fetched next tick (no silent drop).
        if watermark_candidate is not None:
            try:
                trigger_state_set_watermark(_WATERMARK_SOURCE, watermark_candidate)
            except Exception as e:
                logger.warning("airport ticketing watermark advance failed: %s", e)

        stuck_arrivals = _count_stuck_arrivals(conn)
        stats = {
            "ok": True,
            "issued": issued,
            "skipped": skipped,
            "failed": failed,
            "claimed": claimed,
            "terminal_written": terminal_written,
            "lease_skipped": lease_skipped,
            "deterministic_cleared": deterministic_cleared,
            "defaulted_ticket": defaulted_ticket,
            "stuck_arrivals": stuck_arrivals,
            # Read + surfaced for observability. In BRIEF-C the fast lane is not
            # built, so this flag has NO behavioral branch yet — it only gates the
            # future D/E lanes (project-number / manifest). Deterministic clears
            # (DUPLICATE / REJECT_NOISE) and the safe-default TICKET run regardless.
            "fast_lane": fast_lane,
        }
        logger.info("airport_ticketing run_tick stats: %s", stats)
        return stats
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("airport ticketing tick failed: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        store._put_conn(conn)
