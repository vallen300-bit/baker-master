"""Visible second-look lane for shallow-router gray cases.

Default-off recorder only. A1 deliberately does not alter pipeline routing:
when enabled, low-confidence or scope-gate cases get a queryable audit row.
"""
from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal
from functools import partial
from typing import Any, Optional

_ENABLED_ENV = "KBL_ROUTER_SECOND_LOOK_ENABLED"
_FLOOR_ENV = "KBL_TRIAGE_CONFIDENCE_FLOOR"
_DEFAULT_FLOOR = 0.65

VALID_REASON_CODES = frozenset({
    "low_confidence",
    "scope_gate_skip",
    "important_source",
    "deadline_shape",
    "manual",
})
VALID_STATUSES = frozenset({"open", "released", "suppressed", "escalated", "closed"})
_SAVEPOINT_NAME = "router_second_look_audit_sp"


def enabled() -> bool:
    raw = os.environ.get(_ENABLED_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def confidence_floor() -> float:
    raw = os.environ.get(_FLOOR_ENV, str(_DEFAULT_FLOOR))
    try:
        floor = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_FLOOR
    return max(0.0, min(1.0, floor))


def should_record_low_confidence(triage_confidence: Optional[float]) -> bool:
    if triage_confidence is None:
        return False
    return float(triage_confidence) < confidence_floor()


def make_dedup_key(signal_id: Optional[int], trigger_step: str, reason_code: str) -> str:
    base = f"{signal_id or 'none'}:{trigger_step}:{reason_code}"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
    return f"router-second-look:{base}:{digest}"


def _json_param(payload: dict[str, Any]) -> Any:
    try:
        import psycopg2.extras
        return psycopg2.extras.Json(payload)
    except Exception:
        return json.dumps(payload)


def _with_savepoint(conn: Any, fn: Any) -> dict[str, Any]:
    """Run optional audit work without poisoning the caller transaction."""
    with conn.cursor() as cur:
        cur.execute(f"SAVEPOINT {_SAVEPOINT_NAME}")
    try:
        out = fn()
    except Exception:
        with conn.cursor() as cur:
            cur.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT_NAME}")
            cur.execute(f"RELEASE SAVEPOINT {_SAVEPOINT_NAME}")
        raise
    with conn.cursor() as cur:
        cur.execute(f"RELEASE SAVEPOINT {_SAVEPOINT_NAME}")
    return out


def record_item(
    conn: Any,
    *,
    signal_id: Optional[int],
    trigger_step: str,
    reason_code: str,
    primary_matter: Optional[str] = None,
    triage_score: Optional[int] = None,
    triage_confidence: Optional[float] = None,
    payload: Optional[dict[str, Any]] = None,
    dedup_key: Optional[str] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Insert-or-touch a second-look row. Returns a small result dict.

    ``force`` is for tests/manual callers; pipeline integrations use the env gate.
    """
    if not force and not enabled():
        return {"skipped": True, "reason": f"{_ENABLED_ENV} off"}
    if reason_code not in VALID_REASON_CODES:
        raise ValueError(f"invalid reason_code: {reason_code}")
    key = dedup_key or make_dedup_key(signal_id, trigger_step, reason_code)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO router_second_look_items
                (signal_id, trigger_step, reason_code, primary_matter,
                 triage_score, triage_confidence, payload, dedup_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (dedup_key) DO UPDATE
            SET updated_at = NOW()
            RETURNING id, (xmax = 0) AS inserted
            """,
            (
                signal_id,
                trigger_step,
                reason_code,
                primary_matter,
                triage_score,
                Decimal(str(triage_confidence)) if triage_confidence is not None else None,
                _json_param(payload or {}),
                key,
            ),
        )
        row = cur.fetchone()
    inserted = bool(row[1]) if row and len(row) > 1 else False
    return {"ok": True, "id": row[0] if row else None, "inserted": inserted, "dedup_key": key}


def record_low_confidence_if_needed(
    conn: Any,
    *,
    signal_id: int,
    primary_matter: Optional[str],
    triage_score: int,
    triage_confidence: float,
) -> dict[str, Any]:
    if not enabled():
        return {"skipped": True, "reason": f"{_ENABLED_ENV} off"}
    if not should_record_low_confidence(triage_confidence):
        return {"skipped": True, "reason": "confidence_above_floor"}
    return record_item(
        conn,
        signal_id=signal_id,
        trigger_step="step1_triage",
        reason_code="low_confidence",
        primary_matter=primary_matter,
        triage_score=triage_score,
        triage_confidence=triage_confidence,
        payload={"confidence_floor": confidence_floor()},
    )


def record_low_confidence_if_needed_isolated(
    conn: Any,
    *,
    signal_id: int,
    primary_matter: Optional[str],
    triage_score: int,
    triage_confidence: float,
) -> dict[str, Any]:
    if not enabled():
        return {"skipped": True, "reason": f"{_ENABLED_ENV} off"}
    if not should_record_low_confidence(triage_confidence):
        return {"skipped": True, "reason": "confidence_above_floor"}
    return _with_savepoint(
        conn,
        partial(
            record_item,
            conn,
            signal_id=signal_id,
            trigger_step="step1_triage",
            reason_code="low_confidence",
            primary_matter=primary_matter,
            triage_score=triage_score,
            triage_confidence=triage_confidence,
            payload={"confidence_floor": confidence_floor()},
        ),
    )


def record_item_isolated(conn: Any, **kwargs: Any) -> dict[str, Any]:
    if not enabled():
        return {"skipped": True, "reason": f"{_ENABLED_ENV} off"}
    return _with_savepoint(conn, partial(record_item, conn, **kwargs))


def list_items(conn: Any, *, status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    limit = max(1, min(int(limit), 500))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, signal_id, trigger_step, reason_code, primary_matter,
                   triage_score, triage_confidence, status, decided_by,
                   decision_note, payload, dedup_key, created_at, updated_at
            FROM router_second_look_items
            WHERE status = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (status, limit),
        )
        rows = cur.fetchall()
        cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in rows]
