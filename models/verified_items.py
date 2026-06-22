"""BAKER_DASHBOARD_V2_EVIDENCE_PACKET_1: persistence + state machine for the
Verified Operating Room.

This is the durable object model that lets Baker stand behind a dashboard item.
Three tables (created by migrations/20260622c_dashboard_v2_evidence_packet.sql):

  * ``signal_candidates``  — raw-capture staging (ingestion is the next brief).
  * ``verified_items``     — the promotion object: candidate -> verified ->
                             ratified / dismissed.
  * ``verification_events`` — append-only audit; every state change writes one
                             row in the SAME transaction as the change (AC3).

Design invariants
-----------------
* **Audit cannot be bypassed (AC3).** ``transition_item`` reads the current
  state ``FOR UPDATE``, updates ``verified_items.state`` and appends a
  ``verification_events`` row inside one transaction, then a single commit. A
  failure rolls back both — there is no code path that changes state without an
  event.
* **Evidence packet gates promotion (AC4).** A candidate cannot enter
  ``verified`` unless its row already carries source_refs + claim + confidence +
  source_trust + verification_summary + counterargument. Enforced here AND by a
  table CHECK in the migration.
* **Explicit ratification actor (AC5).** ``ratified`` requires an actor_type in
  ``RATIFY_ACTOR_TYPES`` and a non-empty actor_id. No anonymous ratification.
* **Structured dismissal (AC6).** ``dismissed`` requires a reason in
  ``DISMISS_REASONS``.

Model provenance (codex-arch addendum, bus #3748): ``extraction_model`` /
``source_model`` record which model produced the content. STORAGE ONLY — this
module never promotes based on a model, and creates no path that lets
Flash-sourced extraction reach ``verified``. The no-Flash-into-trusted-surfaces
*enforcement* lives in BAKER_DASHBOARD_V2_MODEL_LOCK_1 (b4 lane).

Connections go through the module-level ``_get_conn`` / ``_put_conn`` (the shared
``models.deadlines`` pool), monkeypatchable by tests to point at a live test DB.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import psycopg2.extras

from models.deadlines import get_conn as _pool_get_conn, put_conn as _pool_put_conn

logger = logging.getLogger("baker.models.verified_items")

# ---------------------------------------------------------------------------
# State machine + validation vocabulary (pure data — unit-testable, no DB)
# ---------------------------------------------------------------------------

STATES: frozenset[str] = frozenset({"candidate", "verified", "ratified", "dismissed"})

# Allowed forward transitions. Ratification is reachable only from `verified`
# (per plan §7 "Standing behind begins only at verified"); a candidate cannot be
# ratified directly. `dismissed` is terminal.
VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "candidate": frozenset({"verified", "dismissed"}),
    "verified": frozenset({"ratified", "dismissed"}),
    "ratified": frozenset({"dismissed"}),  # supersede / retraction
    "dismissed": frozenset(),
}

# AC6 — structured dismissal reasons.
DISMISS_REASONS: frozenset[str] = frozenset(
    {
        "marketing",
        "duplicate",
        "wrong_matter",
        "stale",
        "not_important",
        "already_handled",
        "system_noise",
        "false_deadline",
        "false_promise",
        "other",
    }
)

# AC5 — only these actors may ratify. No anonymous ratification.
RATIFY_ACTOR_TYPES: frozenset[str] = frozenset(
    {"director", "head_of_desk", "cortex_tier_b"}
)

# AC4 — fields that must be present on the verified_items row before it may enter
# `verified`. `claim` is column-NOT-NULL so it is always present, but we check it
# anyway so a caller passing an empty string fails closed here rather than at PG.
REQUIRED_EVIDENCE_FIELDS: tuple[str, ...] = (
    "source_refs",
    "claim",
    "confidence",
    "source_trust",
    "verification_summary",
    "counterargument",
)

# States a row may be CREATED in. ONLY `candidate`. `verified`, `ratified`, and
# `dismissed` are reachable EXCLUSIVELY through audited transitions
# (transition_item), which record the real actor — the verifier (cortex_tier_b /
# human) for `verified`, the ratify-actor allowlist (AC5) for `ratified`, the
# structured dismiss reason (AC6) for `dismissed`.
#
# `verified` was removed from this set (deputy-codex G0 F1, VERIFIER_1): a direct
# create into `verified` recorded a creation event with actor_type='system' —
# an UNAUDITED mint that bypassed the cortex/human verifier and broke the Verified
# Operating Room invariant ("verified" == an Opus verifier checked it via the
# audited transition; STOP cond 4). The sole runtime route to `verified` is now
# create(candidate) -> transition_item(verified). The narrow, loudly-named
# `allow_unaudited_verified_seed` kwarg on create_verified_item exists ONLY for
# test fixtures that need to seed a verified row directly; no runtime/dashboard/
# verifier code passes it.
CREATE_STATES: frozenset[str] = frozenset({"candidate"})


def is_valid_transition(from_state: Optional[str], to_state: str) -> bool:
    """True if ``from_state -> to_state`` is a legal FSM edge.

    ``from_state`` of None means creation (NULL -> candidate is the only legal
    creation edge); handled by ``create_verified_item``, not this function.
    """
    if from_state not in VALID_TRANSITIONS:
        return False
    return to_state in VALID_TRANSITIONS[from_state]


def missing_evidence_fields(packet: dict) -> list[str]:
    """Return the REQUIRED_EVIDENCE_FIELDS that are absent/empty in ``packet``.

    Empty list == complete packet. ``source_refs`` must be a non-empty list;
    every other field must be a non-empty (stripped) value. Pure — no DB.
    """
    missing: list[str] = []
    for field in REQUIRED_EVIDENCE_FIELDS:
        val = packet.get(field)
        if field == "source_refs":
            if not val or not isinstance(val, (list, tuple)) or len(val) == 0:
                missing.append(field)
            continue
        if val is None:
            missing.append(field)
        elif isinstance(val, str) and not val.strip():
            missing.append(field)
    return missing


# ---------------------------------------------------------------------------
# Connection plumbing (module-level so tests can redirect to a live test DB)
# ---------------------------------------------------------------------------


def _get_conn():
    return _pool_get_conn()


def _put_conn(conn) -> None:
    _pool_put_conn(conn)


def _as_jsonb(value) -> str:
    """Serialize a Python list/dict for a JSONB column. None -> '[]' for lists."""
    if value is None:
        return "[]"
    return json.dumps(value)


# ---------------------------------------------------------------------------
# signal_candidates — raw-capture staging (AC2 #1)
# ---------------------------------------------------------------------------


def create_signal_candidate(
    raw_source_table: str,
    raw_source_id: str,
    candidate_type: str,
    summary: str,
    extraction_model: str,
    *,
    extraction_confidence: Optional[str] = None,
    source_model: Optional[str] = None,
    matter_slug: Optional[str] = None,
    people: Optional[list] = None,
    source_trust: Optional[str] = None,
    status: str = "awaiting_verification",
) -> Optional[int]:
    """Insert one raw signal candidate. Returns new id, or None on failure.

    Fault-tolerant: failures log + return None (callers are ingestion paths that
    must not crash on a degraded DB).
    """
    conn = _get_conn()
    if not conn:
        logger.warning("verified_items: no DB connection (create_signal_candidate)")
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO signal_candidates
                (raw_source_table, raw_source_id, candidate_type, summary,
                 extraction_model, extraction_confidence, source_model,
                 matter_slug, people, source_trust, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING id
            """,
            (
                raw_source_table,
                raw_source_id,
                candidate_type,
                summary,
                extraction_model,
                extraction_confidence,
                source_model,
                matter_slug,
                _as_jsonb(people),
                source_trust,
                status,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"verified_items: create_signal_candidate failed: {e}")
        return None
    finally:
        _put_conn(conn)


# ---------------------------------------------------------------------------
# verified_items — durable promotion object (AC2 #2)
# ---------------------------------------------------------------------------


def create_verified_item(
    item_type: str,
    claim: str,
    created_by: str,
    *,
    state: str = "candidate",
    why_matters: Optional[str] = None,
    next_action: Optional[str] = None,
    owner: Optional[str] = None,
    due_at=None,
    confidence: Optional[str] = None,
    matter_slug: Optional[str] = None,
    related_matters: Optional[list] = None,
    people: Optional[list] = None,
    source_type: Optional[str] = None,
    source_trust: Optional[str] = None,
    source_refs: Optional[list] = None,
    verification_summary: Optional[str] = None,
    counterargument: Optional[str] = None,
    signal_candidate_id: Optional[int] = None,
    extraction_model: Optional[str] = None,
    source_model: Optional[str] = None,
    rationale: Optional[str] = None,
) -> Optional[int]:
    """Create a ``verified_items`` row and its creation audit event atomically.

    A new object enters at ``state='candidate'`` — the ONLY creation state. The
    creation event (``from_state=NULL -> state``) is written in the SAME
    transaction (AC3 — the audit trail covers every state the row has held).

    ``verified`` / ``ratified`` / ``dismissed`` are reachable ONLY via
    ``transition_item`` so the audited actor (verifier / ratify-actor / dismiss
    reason) cannot be bypassed at creation time. A direct create into ``verified``
    would record an ``actor_type='system'`` creation event — an UNAUDITED mint
    that breaks the "verified == a verifier checked it" invariant (deputy-codex G0
    F1 / STOP cond 4). The sole route to ``verified`` is create(candidate) ->
    ``transition_item('verified', ...)``; tests follow that same audited path.
    Returns the new id, or None on failure.
    """
    if state not in CREATE_STATES:
        logger.error(
            f"verified_items: cannot create directly in state {state!r}; "
            f"allowed create state is {sorted(CREATE_STATES)} "
            f"(use transition_item for verified/ratified/dismissed)"
        )
        return None

    conn = _get_conn()
    if not conn:
        logger.warning("verified_items: no DB connection (create_verified_item)")
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO verified_items
                (state, item_type, claim, why_matters, next_action, owner, due_at,
                 confidence, matter_slug, related_matters, people, source_type,
                 source_trust, source_refs, verification_summary, counterargument,
                 signal_candidate_id, created_by, extraction_model, source_model)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s,
                    %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                state,
                item_type,
                claim,
                why_matters,
                next_action,
                owner,
                due_at,
                confidence,
                matter_slug,
                _as_jsonb(related_matters),
                _as_jsonb(people),
                source_type,
                source_trust,
                _as_jsonb(source_refs),
                verification_summary,
                counterargument,
                signal_candidate_id,
                created_by,
                extraction_model,
                source_model,
            ),
        )
        item_id = cur.fetchone()[0]
        # Creation audit event — same transaction (AC3).
        cur.execute(
            """
            INSERT INTO verification_events
                (verified_item_id, from_state, to_state, actor_type, actor_id,
                 rationale, model, evidence_delta)
            VALUES (%s, NULL, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                item_id,
                state,
                "system",
                created_by,
                rationale or "created",
                extraction_model,
                json.dumps({"event": "create"}),
            ),
        )
        conn.commit()
        cur.close()
        return item_id
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"verified_items: create_verified_item failed: {e}")
        return None
    finally:
        _put_conn(conn)


# ---------------------------------------------------------------------------
# State transitions — the audited core (AC2 #3, AC3, AC4, AC5, AC6)
# ---------------------------------------------------------------------------


def transition_item(
    item_id: int,
    to_state: str,
    actor_type: str,
    actor_id: str,
    *,
    rationale: Optional[str] = None,
    model: Optional[str] = None,
    evidence_delta: Optional[dict] = None,
    dismiss_reason: Optional[str] = None,
) -> dict:
    """Move a ``verified_items`` row to ``to_state`` and append an audit event,
    atomically. Returns a structured result dict (never raises to the caller).

    Result shape::

        {"ok": True,  "item_id", "from_state", "to_state", "event_id"}
        {"ok": False, "error": "<code>", "detail": <optional>}

    Error codes: ``invalid_state``, ``missing_actor``, ``bad_ratify_actor``,
    ``bad_dismiss_reason``, ``not_found``, ``invalid_transition``,
    ``missing_evidence``, ``db_error``.

    The state read (``SELECT ... FOR UPDATE``), the ``UPDATE`` and the
    ``INSERT`` into ``verification_events`` all run in one transaction so the
    audit row can never be skipped (AC3).
    """
    if to_state not in STATES:
        return {"ok": False, "error": "invalid_state", "detail": to_state}
    if not actor_type or not str(actor_type).strip() or not actor_id or not str(actor_id).strip():
        return {"ok": False, "error": "missing_actor"}
    if to_state == "ratified" and actor_type not in RATIFY_ACTOR_TYPES:
        return {"ok": False, "error": "bad_ratify_actor", "detail": actor_type}
    if to_state == "dismissed" and dismiss_reason not in DISMISS_REASONS:
        return {"ok": False, "error": "bad_dismiss_reason", "detail": dismiss_reason}

    conn = _get_conn()
    if not conn:
        return {"ok": False, "error": "db_error", "detail": "no connection"}
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT state, claim, confidence, source_trust, verification_summary,
                   counterargument, source_refs
            FROM verified_items
            WHERE id = %s
            FOR UPDATE
            """,
            (item_id,),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            cur.close()
            return {"ok": False, "error": "not_found", "detail": item_id}

        from_state = row["state"]
        if not is_valid_transition(from_state, to_state):
            conn.rollback()
            cur.close()
            return {
                "ok": False,
                "error": "invalid_transition",
                "detail": f"{from_state}->{to_state}",
            }

        # AC4 — entering `verified` requires a complete evidence packet on the row.
        if to_state == "verified":
            miss = missing_evidence_fields(dict(row))
            if miss:
                conn.rollback()
                cur.close()
                return {"ok": False, "error": "missing_evidence", "detail": miss}

        if to_state == "dismissed":
            cur.execute(
                """
                UPDATE verified_items
                SET state = %s, dismiss_reason = %s, updated_at = now()
                WHERE id = %s
                """,
                (to_state, dismiss_reason, item_id),
            )
        else:
            cur.execute(
                "UPDATE verified_items SET state = %s, updated_at = now() WHERE id = %s",
                (to_state, item_id),
            )

        delta = dict(evidence_delta) if evidence_delta else {}
        if dismiss_reason:
            delta.setdefault("dismiss_reason", dismiss_reason)
        cur.execute(
            """
            INSERT INTO verification_events
                (verified_item_id, from_state, to_state, actor_type, actor_id,
                 rationale, model, evidence_delta)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                item_id,
                from_state,
                to_state,
                actor_type,
                actor_id,
                rationale,
                model,
                json.dumps(delta),
            ),
        )
        event_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        return {
            "ok": True,
            "item_id": item_id,
            "from_state": from_state,
            "to_state": to_state,
            "event_id": event_id,
        }
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"verified_items: transition_item failed: {e}")
        return {"ok": False, "error": "db_error", "detail": str(e)}
    finally:
        _put_conn(conn)


def dismiss_item(
    item_id: int,
    reason: str,
    actor_type: str,
    actor_id: str,
    *,
    rationale: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Dismiss an item with a structured reason (AC2 #4, AC6). Thin wrapper."""
    return transition_item(
        item_id,
        "dismissed",
        actor_type,
        actor_id,
        rationale=rationale,
        model=model,
        dismiss_reason=reason,
    )


def ratify_item(
    item_id: int,
    actor_type: str,
    actor_id: str,
    *,
    rationale: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Ratify a verified item (AC2 #5, AC5). Requires an explicit ratify actor."""
    return transition_item(
        item_id,
        "ratified",
        actor_type,
        actor_id,
        rationale=rationale,
        model=model,
    )


# ---------------------------------------------------------------------------
# Reads (AC2 #6)
# ---------------------------------------------------------------------------


def list_items(
    *,
    state: Optional[str] = None,
    matter_slug: Optional[str] = None,
    person: Optional[str] = None,
    item_type: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """List verified_items filtered by any of state/matter/person/type.

    ``person`` matches when the people JSONB array contains that entry
    (``people @> '["<person>"]'``). All SQL parameterized; LIMIT enforced per
    backend rule. Returns [] on degraded DB (fault-tolerant read).
    """
    if not isinstance(limit, int) or limit <= 0:
        limit = 100
    if limit > 1000:
        limit = 1000

    clauses: list[str] = []
    params: list = []
    if state is not None:
        clauses.append("state = %s")
        params.append(state)
    if matter_slug is not None:
        clauses.append("matter_slug = %s")
        params.append(matter_slug)
    if item_type is not None:
        clauses.append("item_type = %s")
        params.append(item_type)
    if person is not None:
        clauses.append("people @> %s::jsonb")
        params.append(json.dumps([person]))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    conn = _get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            f"""
            SELECT id, state, item_type, claim, why_matters, next_action, owner,
                   due_at, confidence, matter_slug, related_matters, people,
                   source_type, source_trust, source_refs, verification_summary,
                   counterargument, dismiss_reason, signal_candidate_id,
                   created_by, extraction_model, source_model,
                   created_at, updated_at
            FROM verified_items
            {where}
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"verified_items: list_items failed: {e}")
        return []
    finally:
        _put_conn(conn)


def get_events(item_id: int, limit: int = 100) -> list[dict]:
    """Return the audit trail for an item, oldest first. Read helper for tests +
    matter-room timelines."""
    if not isinstance(limit, int) or limit <= 0 or limit > 1000:
        limit = 100
    conn = _get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT id, verified_item_id, from_state, to_state, actor_type,
                   actor_id, rationale, model, evidence_delta, created_at
            FROM verification_events
            WHERE verified_item_id = %s
            ORDER BY created_at ASC, id ASC
            LIMIT %s
            """,
            (item_id, limit),
        )
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"verified_items: get_events failed: {e}")
        return []
    finally:
        _put_conn(conn)


def list_today_items(limit: int = 200) -> list[dict]:
    """BAKER_DASHBOARD_V2_TODAY_1 — read-only helper for the trusted Today
    surface. Returns ONLY ``verified``/``ratified`` rows, ordered for Today
    (ratified before verified, then due_at asc NULLS LAST, then updated_at desc,
    then id desc). Does NOT change ``list_items`` behavior (which sorts by
    updated_at only). Fault-tolerant: [] on degraded DB; rollback before return.
    """
    if not isinstance(limit, int) or limit <= 0:
        limit = 200
    if limit > 1000:
        limit = 1000
    conn = _get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT id, state, item_type, claim, why_matters, next_action, owner,
                   due_at, confidence, matter_slug, related_matters, people,
                   source_type, source_trust, source_refs, verification_summary,
                   counterargument, dismiss_reason, signal_candidate_id,
                   created_by, extraction_model, source_model,
                   created_at, updated_at
            FROM verified_items
            WHERE state IN ('verified', 'ratified')
            ORDER BY CASE WHEN state = 'ratified' THEN 0 ELSE 1 END,
                     due_at ASC NULLS LAST,
                     updated_at DESC,
                     id DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"verified_items: list_today_items failed: {e}")
        return []
    finally:
        _put_conn(conn)
