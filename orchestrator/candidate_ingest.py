"""BAKER_DASHBOARD_V2_CANDIDATE_INGEST_1: the single candidate-ingestion service.

This is the quarantine between "Baker caught something" and "Baker stands behind
it". Every source (email, WhatsApp, Plaud/meeting, calendar, ClickUp/Todoist,
RSS/browser, documents, and the legacy alerts/deadlines backfill) routes through
``create_candidate`` instead of pushing raw guesses into Director-facing cards.
Candidates land in ``signal_candidates``; promotion to ``verified_items`` happens
later (manual here, automated verifier in a later tranche).

Invariants
----------
* **Single writer (AC1).** All sources call ``create_candidate``.
* **Trusted model floor (AC2).** Reuses ``orchestrator.model_policy`` — a
  candidate whose ``extraction_model`` is barred (Gemini Flash / empty) is stored
  but forced to ``source_trust='untrusted_legacy'`` and cannot be promoted to a
  trusted/verified surface without re-extraction. The floor is NOT re-implemented
  here.
* **Idempotent dedup (AC3.4 / AC4).** A deterministic ``dedup_key`` (normalized
  summary + matter + people + due date) plus a partial UNIQUE index collapses
  repeated quiet-thread/proactive/system catches and re-bridged legacy rows to a
  single candidate.
* **Legacy bridge, not replace (AC3).** ``bridge_alert_to_candidate`` /
  ``bridge_deadline_to_candidate`` create candidates from pending alerts / active
  deadlines, preserving the original id in source refs; the legacy rows are left
  intact.
* **No raw body (AC9).** ``signal_candidates`` stores summary + metadata + source
  refs only; this module never persists or returns raw email/WA/Plaud/doc bodies.
* **No Today (AC8).** This module only writes candidates; nothing here feeds
  ``/api/dashboard/morning-brief`` or ``/api/today``.

Every DB call follows the repo try/except/rollback discipline and fails closed.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from typing import Optional

import psycopg2.extras

from models.deadlines import get_conn as _pool_get_conn, put_conn as _pool_put_conn
from models.verified_items import DISMISS_REASONS
from orchestrator.model_policy import is_allowed_for_trusted, log_model_provenance

logger = logging.getLogger("baker.candidate_ingest")

# ---------------------------------------------------------------------------
# Source-trust vocabulary (AC5)
# ---------------------------------------------------------------------------

SOURCE_TRUST_VALUES: frozenset[str] = frozenset(
    {
        "director",
        "vip",
        "known_counterparty",
        "internal_system",
        "public_source",
        "marketing_or_bulk",
        "unknown",
        "untrusted_legacy",
    }
)

# Trust tiers that must stay OUT of Today and default to low priority (AC5).
LOW_PRIORITY_TRUST: frozenset[str] = frozenset({"marketing_or_bulk", "public_source"})

# Trust tiers that cannot be promoted to verified without re-extraction (AC2.3).
NON_PROMOTABLE_TRUST: frozenset[str] = frozenset({"untrusted_legacy"})

# Candidate lifecycle statuses on signal_candidates.status.
STATUS_AWAITING = "awaiting_verification"
STATUS_DISMISSED = "dismissed"
STATUS_PROMOTED = "promoted"


def classify_source_trust(
    *,
    source_type: Optional[str] = None,
    extraction_model: Optional[str] = None,
    is_director: bool = False,
    is_vip: bool = False,
    is_known_counterparty: bool = False,
    is_marketing_or_bulk: bool = False,
    legacy: bool = False,
    explicit: Optional[str] = None,
) -> str:
    """Deterministic source-trust classifier (AC5). Pure — no DB, no model call.

    Precedence (highest wins):
      1. barred extraction model  -> ``untrusted_legacy`` (AC2 — Flash/empty can
         never be trusted, regardless of who sent it).
      2. ``legacy`` backfill flag -> ``untrusted_legacy``.
      3. an ``explicit`` value from the caller, if it is in the vocabulary.
      4. director / vip / known_counterparty / marketing-or-bulk hints.
      5. source_type heuristics (system/scheduler/clickup/todoist -> internal_system,
         rss/browser -> public_source).
      6. ``unknown`` (fail-safe default — kept out of Today by later tranches).
    """
    if extraction_model is not None and not is_allowed_for_trusted(extraction_model):
        return "untrusted_legacy"
    if legacy:
        return "untrusted_legacy"
    if explicit and explicit in SOURCE_TRUST_VALUES:
        return explicit
    if is_director:
        return "director"
    if is_vip:
        return "vip"
    if is_known_counterparty:
        return "known_counterparty"
    if is_marketing_or_bulk:
        return "marketing_or_bulk"
    st = (source_type or "").lower()
    if st in ("system", "scheduler", "alerts", "deadlines", "clickup", "todoist"):
        return "internal_system"
    if st in ("rss", "browser"):
        return "public_source"
    return "unknown"


def can_promote(source_trust: Optional[str]) -> bool:
    """AC2.3 — untrusted_legacy candidates cannot be promoted without re-extraction."""
    return source_trust not in NON_PROMOTABLE_TRUST


# ---------------------------------------------------------------------------
# Dedup key (AC4)
# ---------------------------------------------------------------------------


def _normalize(text: Optional[str]) -> str:
    """Lowercase + collapse whitespace so trivially-different summaries collide."""
    return " ".join((text or "").lower().split())


def _due_component(due_at) -> str:
    if due_at is None:
        return ""
    if isinstance(due_at, datetime):
        return due_at.date().isoformat()
    if isinstance(due_at, date):
        return due_at.isoformat()
    # string — take the leading date portion if present
    return str(due_at)[:10]


def compute_dedup_key(
    summary: Optional[str],
    matter_slug: Optional[str],
    people: Optional[list],
    due_at=None,
) -> str:
    """Deterministic dedup key over normalized summary + matter + people + due.

    Content-based (NOT source-id-based) so the same issue arriving as a fresh
    alert row each cycle, or a re-bridged legacy row, collapses to one candidate
    (AC4 — "prevent repeated quiet-thread/proactive/system alerts from creating
    multiple candidate cards for the same issue"; AC3.4 idempotent re-bridge).
    """
    people_norm = ",".join(sorted((str(p) or "").lower() for p in (people or [])))
    parts = [
        "v1",
        _normalize(summary),
        (matter_slug or "").lower(),
        people_norm,
        _due_component(due_at),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Connection plumbing (module-level so tests can redirect to a live test DB)
# ---------------------------------------------------------------------------


def _get_conn():
    return _pool_get_conn()


def _put_conn(conn) -> None:
    _pool_put_conn(conn)


def _as_jsonb(value) -> str:
    if value is None:
        return "[]"
    return json.dumps(value)


# ---------------------------------------------------------------------------
# The single candidate writer (AC1 / AC2 / AC4 / AC5)
# ---------------------------------------------------------------------------


def create_candidate(
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
    due_at=None,
    source_trust: Optional[str] = None,
    legacy: bool = False,
    dedup_key: Optional[str] = None,
) -> dict:
    """Create one candidate, deduped + model-floor-gated. Returns a result dict::

        {"ok": True, "id": <int>, "created": <bool>, "source_trust": <str>,
         "trusted_model": <bool>, "dedup_key": <str>}
        {"ok": False, "error": "db_error", "detail": ...}

    ``created`` is False when an existing candidate with the same dedup_key was
    found (idempotent). The model floor (AC2) is applied here: a barred
    ``extraction_model`` forces ``source_trust='untrusted_legacy'`` so the row can
    never be promoted to a trusted surface without re-extraction. The
    ``extraction_model`` is always stored (AC2.1).
    """
    trusted_model = is_allowed_for_trusted(extraction_model)

    # Resolve trust. The classifier already applies the model-floor + legacy
    # overrides, so pass both in rather than trusting the caller blindly.
    resolved_trust = classify_source_trust(
        source_type=raw_source_table,
        extraction_model=extraction_model,
        legacy=legacy,
        explicit=source_trust,
    )

    log_model_provenance(
        model=extraction_model,
        trusted=trusted_model,
        source_channel=raw_source_table,
        output_type="signal_candidate",
        context="candidate_ingest.create_candidate",
    )

    key = dedup_key or compute_dedup_key(summary, matter_slug, people, due_at)

    conn = _get_conn()
    if not conn:
        logger.warning("candidate_ingest: no DB connection (create_candidate)")
        return {"ok": False, "error": "db_error", "detail": "no connection"}
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO signal_candidates
                (raw_source_table, raw_source_id, candidate_type, summary,
                 extraction_model, extraction_confidence, source_model,
                 matter_slug, people, source_trust, status, due_at, dedup_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            ON CONFLICT (dedup_key) WHERE dedup_key IS NOT NULL
            DO NOTHING
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
                resolved_trust,
                STATUS_AWAITING,
                due_at,
                key,
            ),
        )
        row = cur.fetchone()
        if row is not None:
            conn.commit()
            cur.close()
            return {
                "ok": True, "id": row[0], "created": True,
                "source_trust": resolved_trust, "trusted_model": trusted_model,
                "dedup_key": key,
            }
        # Conflict — a candidate with this dedup_key already exists. Idempotent.
        conn.commit()
        cur.execute("SELECT id FROM signal_candidates WHERE dedup_key = %s", (key,))
        existing = cur.fetchone()
        cur.close()
        return {
            "ok": True, "id": existing[0] if existing else None, "created": False,
            "source_trust": resolved_trust, "trusted_model": trusted_model,
            "dedup_key": key,
        }
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"candidate_ingest: create_candidate failed: {e}")
        return {"ok": False, "error": "db_error", "detail": str(e)}
    finally:
        _put_conn(conn)


# ---------------------------------------------------------------------------
# Legacy bridges (AC3) — pending alert / active deadline -> candidate
# ---------------------------------------------------------------------------


def bridge_alert_to_candidate(alert: dict) -> dict:
    """Bridge one pending ``alerts`` row to a candidate (AC3.1). Idempotent.

    Source refs preserve the original alert id. Legacy alert content was produced
    before the model floor, so it is marked ``untrusted_legacy`` (cannot promote
    without re-extraction). The alert row itself is NOT mutated (AC3 — bridge,
    don't replace).
    """
    alert_id = alert.get("id")
    title = alert.get("title") or ""
    body = alert.get("body") or ""
    summary = (title.strip() + (" — " + body.strip() if body.strip() else "")).strip()
    trigger = None
    sa = alert.get("structured_actions")
    if isinstance(sa, dict):
        trigger = sa.get("trigger")
    return create_candidate(
        raw_source_table="alerts",
        raw_source_id=str(alert_id),
        candidate_type=trigger or "alert",
        summary=summary or f"alert {alert_id}",
        extraction_model="legacy_unknown",  # barred -> untrusted_legacy
        matter_slug=alert.get("matter_slug"),
        source_trust="untrusted_legacy",
        legacy=True,
    )


def bridge_deadline_to_candidate(deadline: dict) -> dict:
    """Bridge one active ``deadlines`` row to a candidate (AC3.2). Idempotent."""
    did = deadline.get("id")
    return create_candidate(
        raw_source_table="deadlines",
        raw_source_id=str(did),
        candidate_type="deadline",
        summary=deadline.get("description") or f"deadline {did}",
        extraction_model="legacy_unknown",
        matter_slug=deadline.get("matter_slug"),
        due_at=deadline.get("due_date"),
        source_trust="untrusted_legacy",
        legacy=True,
    )


def bridge_pending_alerts(limit: int = 500) -> dict:
    """Batch-bridge pending alerts to candidates (AC3). Manual / diagnostic only —
    NOT cron-triggered (Cortex/Director-trigger invariant). Returns counts."""
    if not isinstance(limit, int) or limit <= 0 or limit > 5000:
        limit = 500
    conn = _get_conn()
    if not conn:
        return {"ok": False, "error": "db_error", "bridged": 0, "skipped": 0}
    rows: list[dict] = []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT id, title, body, matter_slug, structured_actions
            FROM alerts
            WHERE status = 'pending'
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"candidate_ingest: bridge_pending_alerts read failed: {e}")
        return {"ok": False, "error": "db_error", "bridged": 0, "skipped": 0}
    finally:
        _put_conn(conn)

    bridged = skipped = failed = 0
    for r in rows:
        res = bridge_alert_to_candidate(r)
        if not res.get("ok"):
            failed += 1
        elif res.get("created"):
            bridged += 1
        else:
            skipped += 1
    return {"ok": True, "bridged": bridged, "skipped": skipped, "failed": failed,
            "scanned": len(rows)}


def bridge_active_deadlines(limit: int = 500) -> dict:
    """Batch-bridge active deadlines to candidates (AC3). Manual / diagnostic only."""
    if not isinstance(limit, int) or limit <= 0 or limit > 5000:
        limit = 500
    conn = _get_conn()
    if not conn:
        return {"ok": False, "error": "db_error", "bridged": 0, "skipped": 0}
    rows: list[dict] = []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT id, description, matter_slug, due_date
            FROM deadlines
            WHERE status = 'active'
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"candidate_ingest: bridge_active_deadlines read failed: {e}")
        return {"ok": False, "error": "db_error", "bridged": 0, "skipped": 0}
    finally:
        _put_conn(conn)

    bridged = skipped = failed = 0
    for r in rows:
        res = bridge_deadline_to_candidate(r)
        if not res.get("ok"):
            failed += 1
        elif res.get("created"):
            bridged += 1
        else:
            skipped += 1
    return {"ok": True, "bridged": bridged, "skipped": skipped, "failed": failed,
            "scanned": len(rows)}


# ---------------------------------------------------------------------------
# Triage reads + dismissal (AC6 / AC7 / AC9 / AC10)
# ---------------------------------------------------------------------------

# Columns returned by triage reads — summary + metadata + source refs ONLY.
# NO raw body column exists on signal_candidates, so AC9 (no raw-body leakage) is
# structural; this explicit list keeps it that way if columns are added later.
_CANDIDATE_PUBLIC_COLS = (
    "id", "raw_source_table", "raw_source_id", "candidate_type", "summary",
    "extraction_model", "extraction_confidence", "source_model", "matter_slug",
    "people", "source_trust", "status", "dismiss_reason", "due_at", "created_at",
)


def list_candidates(
    *,
    matter_slug: Optional[str] = None,
    source_type: Optional[str] = None,
    candidate_type: Optional[str] = None,
    source_trust: Optional[str] = None,
    status: Optional[str] = None,
    created_after=None,
    created_before=None,
    limit: int = 100,
) -> list[dict]:
    """Matter-aware triage candidate list (AC6/AC7). Returns summaries + metadata +
    source refs only (AC9). Fault-tolerant: [] on degraded DB."""
    if not isinstance(limit, int) or limit <= 0:
        limit = 100
    if limit > 1000:
        limit = 1000

    clauses: list[str] = []
    params: list = []
    if matter_slug is not None:
        clauses.append("matter_slug = %s")
        params.append(matter_slug)
    if source_type is not None:
        clauses.append("raw_source_table = %s")
        params.append(source_type)
    if candidate_type is not None:
        clauses.append("candidate_type = %s")
        params.append(candidate_type)
    if source_trust is not None:
        clauses.append("source_trust = %s")
        params.append(source_trust)
    if status is not None:
        clauses.append("status = %s")
        params.append(status)
    if created_after is not None:
        clauses.append("created_at >= %s")
        params.append(created_after)
    if created_before is not None:
        clauses.append("created_at <= %s")
        params.append(created_before)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    conn = _get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            f"SELECT {', '.join(_CANDIDATE_PUBLIC_COLS)} FROM signal_candidates"
            f"{where} ORDER BY created_at DESC LIMIT %s",
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
        logger.error(f"candidate_ingest: list_candidates failed: {e}")
        return []
    finally:
        _put_conn(conn)


def get_candidate(candidate_id: int) -> Optional[dict]:
    """Fetch one candidate (public columns only). None if absent / degraded DB."""
    conn = _get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            f"SELECT {', '.join(_CANDIDATE_PUBLIC_COLS)} "
            f"FROM signal_candidates WHERE id = %s",
            (candidate_id,),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"candidate_ingest: get_candidate failed: {e}")
        return None
    finally:
        _put_conn(conn)


def dismiss_candidate(candidate_id: int, reason: str, actor_id: str) -> dict:
    """Dismiss a candidate with a structured reason (AC10). Reason must be in the
    shared DISMISS_REASONS vocabulary. Fails closed on a degraded DB."""
    if reason not in DISMISS_REASONS:
        return {"ok": False, "error": "bad_dismiss_reason", "detail": reason}
    if not actor_id or not str(actor_id).strip():
        return {"ok": False, "error": "missing_actor"}
    conn = _get_conn()
    if not conn:
        return {"ok": False, "error": "db_error", "detail": "no connection"}
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE signal_candidates
            SET status = %s, dismiss_reason = %s
            WHERE id = %s
            RETURNING id
            """,
            (STATUS_DISMISSED, reason, candidate_id),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if row is None:
            return {"ok": False, "error": "not_found", "detail": candidate_id}
        return {"ok": True, "id": candidate_id, "status": STATUS_DISMISSED,
                "dismiss_reason": reason}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"candidate_ingest: dismiss_candidate failed: {e}")
        return {"ok": False, "error": "db_error", "detail": str(e)}
    finally:
        _put_conn(conn)


def mark_promoted(candidate_id: int, verified_item_id: int) -> bool:
    """Flag a candidate as promoted after a verified_items row is created from it.
    Best-effort: a failure here does not invalidate the verified item."""
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE signal_candidates SET status = %s WHERE id = %s",
            (STATUS_PROMOTED, candidate_id),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"candidate_ingest: mark_promoted failed: {e}")
        return False
    finally:
        _put_conn(conn)


def promote_candidate_manual(
    candidate_id: int,
    *,
    item_type: str,
    claim: str,
    actor_type: str,
    actor_id: str,
    confidence: str,
    source_trust: str,
    verification_summary: str,
    counterargument: str,
    why_matters: Optional[str] = None,
    next_action: Optional[str] = None,
    owner: Optional[str] = None,
    due_at=None,
    matter_slug: Optional[str] = None,
    people: Optional[list] = None,
    extra_source_refs: Optional[list] = None,
) -> dict:
    """AC6 — create a ``verified_items`` row from a candidate using a manually
    supplied evidence packet. Enforces:

      * an explicit human/desk verifier (guard #6 — ``actor_type`` may not be
        ``system`` or empty),
      * the candidate exists,
      * the candidate's trust allows promotion (AC2.3 — untrusted_legacy refused),
      * the evidence packet is complete (delegated to verified_items).

    AUDIT-TRAIL INTEGRITY (deputy/codex-arch guard #6): the verified_items shell
    is created in ``state='candidate'`` (whose creation event is system-authored,
    correctly — the machine creates the shell), then promoted to ``verified`` via
    ``transition_item`` with the explicit ``actor_type``/``actor_id``. That writes
    a ``verification_events`` row recording the HUMAN verifier — so the manual
    verifier appears in the audit trail, not only in ``created_by``. A direct
    ``create(state='verified')`` would have recorded ``actor_type='system'`` and
    lost the verifier.

    Returns ``{"ok": True, "verified_item_id": ..., "verify_event_id": ...}`` or an
    error dict. Source refs preserve the candidate's origin (internal id only —
    AC9).
    """
    from models.verified_items import (
        create_verified_item,
        missing_evidence_fields,
        transition_item,
    )

    if not actor_type or str(actor_type).strip().lower() in ("", "system"):
        return {"ok": False, "error": "verifier_required",
                "detail": "manual verification needs an explicit non-system verifier"}
    if not actor_id or not str(actor_id).strip():
        return {"ok": False, "error": "missing_actor"}

    cand = get_candidate(candidate_id)
    if cand is None:
        return {"ok": False, "error": "not_found", "detail": candidate_id}
    if not can_promote(cand.get("source_trust")):
        return {
            "ok": False, "error": "not_promotable",
            "detail": f"source_trust={cand.get('source_trust')} cannot promote "
                      f"without re-extraction",
        }

    source_refs = [{
        "table": cand.get("raw_source_table"),
        "id": cand.get("raw_source_id"),
        "candidate_id": candidate_id,
    }]
    if extra_source_refs:
        source_refs.extend(extra_source_refs)

    packet = {
        "source_refs": source_refs, "claim": claim, "confidence": confidence,
        "source_trust": source_trust, "verification_summary": verification_summary,
        "counterargument": counterargument,
    }
    miss = missing_evidence_fields(packet)
    if miss:
        return {"ok": False, "error": "missing_evidence", "detail": miss}

    # 1) Create the durable shell in candidate state, carrying the full evidence
    #    packet so the promotion's AC4 check passes.
    item_id = create_verified_item(
        item_type=item_type,
        claim=claim,
        created_by=f"{actor_type}:{actor_id}",
        state="candidate",
        why_matters=why_matters,
        next_action=next_action,
        owner=owner,
        due_at=due_at if due_at is not None else cand.get("due_at"),
        confidence=confidence,
        matter_slug=matter_slug if matter_slug is not None else cand.get("matter_slug"),
        people=people if people is not None else cand.get("people"),
        source_type=cand.get("raw_source_table"),
        source_trust=source_trust,
        source_refs=source_refs,
        verification_summary=verification_summary,
        counterargument=counterargument,
        signal_candidate_id=candidate_id,
        extraction_model=cand.get("extraction_model"),
        source_model=cand.get("source_model"),
        rationale="manual verification via triage (candidate shell)",
    )
    if item_id is None:
        return {"ok": False, "error": "create_failed"}

    # 2) Promote candidate -> verified, recording the explicit human verifier in
    #    verification_events (guard #6).
    tr = transition_item(
        item_id, "verified",
        actor_type=actor_type, actor_id=actor_id,
        rationale="manual verification via triage",
    )
    if not tr.get("ok"):
        return {"ok": False, "error": "promote_failed", "detail": tr,
                "verified_item_id": item_id}
    mark_promoted(candidate_id, item_id)
    return {"ok": True, "verified_item_id": item_id, "candidate_id": candidate_id,
            "verify_event_id": tr.get("event_id")}
