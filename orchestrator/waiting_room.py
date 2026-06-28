"""Fleet-wide waiting-room foundation for chartered Baker work.

Default-off nudge rail. B1 only persists and evaluates waiting-room items; it
does not wire scheduled missed-departure or branch teardown automation.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

_NUDGE_ENABLED_ENV = "WAITING_ROOM_NUDGE_ENABLED"
_NUDGE_COOLDOWN_ENV = "WAITING_ROOM_NUDGE_COOLDOWN_SECONDS"
_DEFAULT_COOLDOWN_SECONDS = 3600
_NUDGE_MAX_PER_RUN_ENV = "WAITING_ROOM_NUDGE_MAX_PER_RUN"
_DEFAULT_MAX_PER_RUN = 10

VALID_FLIGHT_TYPES = frozenset({"scheduled", "chartered"})
VALID_STATUSES = frozenset({"waiting", "ready", "nudged", "released", "cancelled"})


def nudge_enabled() -> bool:
    raw = os.environ.get(_NUDGE_ENABLED_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def nudge_cooldown_seconds() -> int:
    try:
        value = int(os.environ.get(_NUDGE_COOLDOWN_ENV, str(_DEFAULT_COOLDOWN_SECONDS)))
    except (TypeError, ValueError):
        return _DEFAULT_COOLDOWN_SECONDS
    return max(60, value)


def nudge_max_per_run() -> int:
    try:
        value = int(os.environ.get(_NUDGE_MAX_PER_RUN_ENV, str(_DEFAULT_MAX_PER_RUN)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_PER_RUN
    return max(0, min(value, 100))


def make_dedup_key(flight_type: str, item_type: str, item_ref: str) -> str:
    base = f"{flight_type}:{item_type}:{item_ref}"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
    return f"waiting-room:{base}:{digest}"


def _json_param(payload: dict[str, Any]) -> Any:
    try:
        import psycopg2.extras
        return psycopg2.extras.Json(payload)
    except Exception:
        return json.dumps(payload)


def upsert_item(
    conn: Any,
    *,
    flight_type: str,
    item_type: str,
    item_ref: str,
    owner_slug: Optional[str] = None,
    reason_code: Optional[str] = None,
    ready_after: Optional[datetime] = None,
    payload: Optional[dict[str, Any]] = None,
    dedup_key: Optional[str] = None,
) -> dict[str, Any]:
    if flight_type not in VALID_FLIGHT_TYPES:
        raise ValueError(f"invalid flight_type: {flight_type}")
    key = dedup_key or make_dedup_key(flight_type, item_type, item_ref)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO waiting_room_items
                (flight_type, item_type, item_ref, owner_slug, reason_code,
                 ready_after, payload, dedup_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (dedup_key) DO UPDATE
            SET owner_slug = EXCLUDED.owner_slug,
                reason_code = EXCLUDED.reason_code,
                ready_after = EXCLUDED.ready_after,
                payload = EXCLUDED.payload,
                updated_at = NOW()
            RETURNING id, (xmax = 0) AS inserted
            """,
            (
                flight_type,
                item_type,
                item_ref,
                owner_slug,
                reason_code,
                ready_after,
                _json_param(payload or {}),
                key,
            ),
        )
        row = cur.fetchone()
    inserted = bool(row[1]) if row and len(row) > 1 else False
    return {"ok": True, "id": row[0] if row else None, "inserted": inserted, "dedup_key": key}


def set_status(
    conn: Any,
    *,
    item_id: int,
    status: str,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE waiting_room_items
            SET status = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING id, status
            """,
            (status, item_id),
        )
        row = cur.fetchone()
    return {"ok": bool(row), "id": row[0] if row else None, "status": row[1] if row else None}


def is_nudge_eligible(
    *,
    status: str,
    ready_after: Optional[datetime],
    last_nudge_at: Optional[datetime],
    now: Optional[datetime] = None,
    cooldown_seconds: Optional[int] = None,
) -> bool:
    if status not in {"waiting", "ready", "nudged"}:
        return False
    current = now or datetime.now(timezone.utc)
    if ready_after and ready_after > current:
        return False
    cooldown = timedelta(seconds=cooldown_seconds or nudge_cooldown_seconds())
    if last_nudge_at and current - last_nudge_at < cooldown:
        return False
    return True


def run_nudge_tick(conn: Any) -> dict[str, Any]:
    if not nudge_enabled():
        return {"skipped": True, "reason": f"{_NUDGE_ENABLED_ENV} off"}
    cap = nudge_max_per_run()
    if cap <= 0:
        return {"skipped": True, "reason": f"{_NUDGE_MAX_PER_RUN_ENV}=0"}
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE waiting_room_items
            SET status = 'nudged',
                last_nudge_at = NOW(),
                nudge_count = nudge_count + 1,
                updated_at = NOW()
            WHERE id IN (
                SELECT id
                FROM waiting_room_items
                WHERE flight_type = 'chartered'
                  AND status IN ('waiting', 'ready', 'nudged')
                  AND (ready_after IS NULL OR ready_after <= NOW())
                  AND (
                      last_nudge_at IS NULL
                      OR last_nudge_at <= NOW() - (%s || ' seconds')::interval
                  )
                ORDER BY created_at ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id
            """,
            (nudge_cooldown_seconds(), cap),
        )
        rows = cur.fetchall()
    return {"ok": True, "nudged": len(rows), "ids": [row[0] for row in rows]}


def register_waiting_room_workers(scheduler) -> list[str]:
    """Future scheduler hook placeholder.

    B1 deliberately does not wire a scheduled missed-departure system. Keep a
    no-op function so tests can assert the default-off scheduler contract.
    """
    return []
