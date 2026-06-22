"""Trusted candidate verifier — BAKER_DASHBOARD_V2_VERIFIER_1 (V2 step 4).

Single-candidate, Opus-class verifier that re-checks one ``signal_candidates`` row
against its source material and, only when the evidence supports a concrete
Director-relevant item, promotes it to a trusted ``verified_items`` row through the
existing audited candidate-shell -> ``transition_item('verified')`` state machine.

Hard invariants (brief AC1-AC10 + STOP conditions):
  * verifier model floor is OPUS-CLASS only (``model_policy.assert_trusted_verification_model``);
  * source context comes from a FIXED adapter map with hard-coded parameterized
    SELECTs — ``raw_source_table`` is NEVER interpolated into SQL (AC3);
  * raw source bodies are PROMPT-ONLY — never returned by the API, never stored in
    ``source_refs``, never emitted into Today (AC7);
  * cost breaker is checked BEFORE the model call, cost logged AFTER (AC10);
  * promotion is ONLY via ``candidate_ingest.promote_candidate_verified_by_cortex``
    (candidate shell + audited transition) — never a direct ``create_verified_item``
    in ``verified`` state (AC5 / STOP cond 4);
  * single-candidate only — no cron / batch / startup / backfill / external send (AC8).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from orchestrator import model_policy

logger = logging.getLogger("baker.candidate_verifier")

# Allowed V1 source tables (AC3). The KEYS are the only legal ``raw_source_table``
# values; each maps to an adapter holding a HARD-CODED parameterized SELECT.
SUPPORTED_SOURCE_TABLES: Tuple[str, ...] = (
    "email_messages",
    "whatsapp_messages",
    "meeting_transcripts",
    "documents",
    "alerts",
    "deadlines",
)

MAX_SOURCE_CHARS = 24000          # cap on raw source text fed to the prompt
MAX_OUTPUT_TOKENS = 1400          # verifier completion budget

_LEGAL_VERDICTS = ("promote", "reject", "needs_human")
_LEGAL_CONFIDENCE = ("high", "medium", "low")
_PROMOTABLE_CONFIDENCE = ("high", "medium")

# Keys that must never survive into an API/DB result — raw bodies / prompt text.
_RAW_BODY_KEYS = (
    "full_body", "full_text", "full_transcript", "body", "source_snippet",
    "raw_body", "text_for_prompt", "prompt", "system_prompt", "user_prompt",
    "source_text",
)


# --------------------------------------------------------------------------- #
# Source adapters — fixed map, hard-coded parameterized SQL (AC3).
# Each adapter: (conn, raw_source_id) -> source-context dict or None (not found).
# raw_source_table is matched against the dict keys; it is never put into SQL.
# --------------------------------------------------------------------------- #
def _row_get(row: Any, idx: int) -> Any:
    try:
        return row[idx]
    except Exception:
        return None


def _adapter_email_messages(conn, rid: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT message_id, thread_id, sender_name, sender_email, subject, "
        "full_body, received_date, source FROM email_messages WHERE message_id = %s",
        (rid,),
    )
    r = cur.fetchone(); cur.close()
    if not r:
        return None
    return {
        "source_type": "email_messages",
        "source_ref": {"table": "email_messages", "id": _row_get(r, 0)},
        "metadata": {"subject": _row_get(r, 4), "sender_email": _row_get(r, 3),
                     "sender_name": _row_get(r, 2), "received_date": str(_row_get(r, 6) or ""),
                     "thread_id": _row_get(r, 1)},
        "text_for_prompt": _row_get(r, 5) or "",
    }


def _adapter_whatsapp_messages(conn, rid: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, sender, sender_name, chat_id, full_text, timestamp, is_director "
        "FROM whatsapp_messages WHERE id = %s",
        (rid,),
    )
    r = cur.fetchone(); cur.close()
    if not r:
        return None
    return {
        "source_type": "whatsapp_messages",
        "source_ref": {"table": "whatsapp_messages", "id": _row_get(r, 0)},
        "metadata": {"sender_name": _row_get(r, 2), "chat_id": _row_get(r, 3),
                     "timestamp": str(_row_get(r, 5) or ""), "is_director": _row_get(r, 6)},
        "text_for_prompt": _row_get(r, 4) or "",
    }


def _adapter_meeting_transcripts(conn, rid: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, meeting_date, organizer, participants, summary, "
        "full_transcript, source, matter_slug FROM meeting_transcripts WHERE id = %s",
        (rid,),
    )
    r = cur.fetchone(); cur.close()
    if not r:
        return None
    return {
        "source_type": "meeting_transcripts",
        "source_ref": {"table": "meeting_transcripts", "id": _row_get(r, 0)},
        "metadata": {"title": _row_get(r, 1), "meeting_date": str(_row_get(r, 2) or ""),
                     "organizer": _row_get(r, 3), "matter_slug": _row_get(r, 8)},
        "text_for_prompt": _row_get(r, 6) or _row_get(r, 5) or "",
    }


def _adapter_documents(conn, rid: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, source_path, filename, document_type, matter_slug, parties, "
        "tags, full_text, token_count FROM documents WHERE id = %s",
        (rid,),
    )
    r = cur.fetchone(); cur.close()
    if not r:
        return None
    return {
        "source_type": "documents",
        "source_ref": {"table": "documents", "id": _row_get(r, 0)},
        "metadata": {"filename": _row_get(r, 2), "document_type": _row_get(r, 3),
                     "matter_slug": _row_get(r, 4)},
        "text_for_prompt": _row_get(r, 7) or "",
    }


def _adapter_alerts(conn, rid: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, body, status, structured_actions, matter_slug, source, "
        "source_id FROM alerts WHERE id = %s",
        (rid,),
    )
    r = cur.fetchone(); cur.close()
    if not r:
        return None
    return {
        "source_type": "alerts",
        "source_ref": {"table": "alerts", "id": _row_get(r, 0)},
        "metadata": {"title": _row_get(r, 1), "status": _row_get(r, 3),
                     "matter_slug": _row_get(r, 5), "source": _row_get(r, 6)},
        "text_for_prompt": _row_get(r, 2) or "",
    }


def _adapter_deadlines(conn, rid: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, description, due_date, source_type, source_id, source_snippet, "
        "confidence, priority, status, matter_slug FROM deadlines WHERE id = %s",
        (rid,),
    )
    r = cur.fetchone(); cur.close()
    if not r:
        return None
    return {
        "source_type": "deadlines",
        "source_ref": {"table": "deadlines", "id": _row_get(r, 0)},
        "metadata": {"description": _row_get(r, 1), "due_date": str(_row_get(r, 2) or ""),
                     "priority": _row_get(r, 7), "matter_slug": _row_get(r, 9)},
        "text_for_prompt": (_row_get(r, 5) or _row_get(r, 1) or ""),
    }


# table -> adapter. The ONLY place a source table name is resolved; static map.
_SOURCE_ADAPTERS = {
    "email_messages": _adapter_email_messages,
    "whatsapp_messages": _adapter_whatsapp_messages,
    "meeting_transcripts": _adapter_meeting_transcripts,
    "documents": _adapter_documents,
    "alerts": _adapter_alerts,
    "deadlines": _adapter_deadlines,
}


def fetch_source_context(conn, raw_source_table: str, raw_source_id: Any) -> dict:
    """Resolve source context via the allowlisted adapter map. Returns a context
    dict (with prompt-only ``text_for_prompt``) or an error dict. Never builds SQL
    from ``raw_source_table`` — unknown tables fail before any query (AC3)."""
    adapter = _SOURCE_ADAPTERS.get(raw_source_table)
    if adapter is None:
        return {"ok": False, "error": "unsupported_source", "detail": raw_source_table}
    ctx = adapter(conn, raw_source_id)
    if ctx is None:
        return {"ok": False, "error": "source_not_found",
                "detail": {"table": raw_source_table, "id": raw_source_id}}
    text = ctx.get("text_for_prompt") or ""
    if len(text) > MAX_SOURCE_CHARS:
        ctx["text_for_prompt"] = text[:MAX_SOURCE_CHARS]
        ctx["truncated"] = True
    ctx["ok"] = True
    return ctx


# --------------------------------------------------------------------------- #
# Pure helpers (prompt / parse / validate / sanitize) — no DB, no LLM.
# --------------------------------------------------------------------------- #
_VERIFIER_SYSTEM = (
    "You verify whether Baker can stand behind a candidate signal as a trusted, "
    "Director-relevant item. Use the source text, the candidate summary, the "
    "matter/person hints, the due date, and the source metadata. Promote ONLY if "
    "the evidence supports a concrete Director-relevant item. Always write a "
    "counterargument, even when promoting. You create an evidence packet only — "
    "you do NOT decide external sends, legal advice, or financial action. If you "
    "are uncertain, return verdict \"needs_human\". Return JSON ONLY: no markdown, "
    "no code fences, no prose before or after the JSON object."
)

_VERIFIER_SCHEMA_HINT = (
    '{"verdict":"promote|reject|needs_human","item_type":"deadline|promise|decision|'
    'meeting|task|risk|other","claim":"one concrete claim","why_matters":"practical '
    'consequence","next_action":"concrete action or none","owner":"Director|Baker|'
    'Head of Desk|counterparty|named person","due_at":"ISO-8601 or null","confidence":'
    '"high|medium|low","matter_slug":"slug or null","related_matters":[],"people":[],'
    '"source_trust":"director|vip|known_counterparty|internal_system|public_source|'
    'marketing_or_bulk|unknown","verification_summary":"what you checked",'
    '"counterargument":"why this might be wrong or noise","reject_reason":null}'
)


def build_verifier_prompt(candidate: dict, source_context: dict) -> Tuple[str, str]:
    """Build (system, user) for the verifier. Raw source text lives ONLY in the
    returned user prompt — never echoed elsewhere."""
    md = source_context.get("metadata", {}) or {}
    user = (
        "CANDIDATE (machine-extracted, unverified):\n"
        f"- type: {candidate.get('candidate_type')}\n"
        f"- summary: {candidate.get('summary')}\n"
        f"- matter_slug: {candidate.get('matter_slug')}\n"
        f"- people: {candidate.get('people')}\n"
        f"- due_at: {candidate.get('due_at')}\n"
        f"- extraction_model: {candidate.get('extraction_model')}\n"
        f"- extraction_confidence: {candidate.get('extraction_confidence')}\n\n"
        f"SOURCE TYPE: {source_context.get('source_type')}\n"
        f"SOURCE METADATA: {json.dumps(md, default=str)}\n\n"
        "SOURCE TEXT (verify against this):\n"
        f"{source_context.get('text_for_prompt', '')}\n\n"
        "Return a single JSON object exactly matching this shape (values are "
        f"examples):\n{_VERIFIER_SCHEMA_HINT}"
    )
    return _VERIFIER_SYSTEM, user


def parse_verifier_json(text: str) -> dict:
    """Strict JSON parse. Tolerates a single surrounding ```...``` fence (defensive)
    but rejects prose-wrapped or non-object output. Returns the dict, or
    ``{"_parse_error": <reason>}`` on failure (never raises)."""
    if not text or not text.strip():
        return {"_parse_error": "empty"}
    s = text.strip()
    if s.startswith("```"):
        # strip a single ```json ... ``` fence if a model added one
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    if not s.startswith("{"):
        return {"_parse_error": "not_a_json_object"}
    try:
        obj = json.loads(s)
    except Exception as e:
        return {"_parse_error": f"json_decode:{e}"}
    if not isinstance(obj, dict):
        return {"_parse_error": "not_a_json_object"}
    return obj


def validate_verifier_evidence(evidence: dict) -> List[str]:
    """Return a list of reasons the evidence is not promotable. Empty list = OK to
    promote. Enforces AC4 verdict/confidence gating + required non-empty fields."""
    reasons: List[str] = []
    if not isinstance(evidence, dict) or evidence.get("_parse_error"):
        return ["bad_json"]
    verdict = (evidence.get("verdict") or "").strip().lower()
    if verdict not in _LEGAL_VERDICTS:
        reasons.append("illegal_verdict")
        return reasons
    if verdict != "promote":
        reasons.append(f"verdict_{verdict}")
        return reasons
    conf = (evidence.get("confidence") or "").strip().lower()
    if conf not in _LEGAL_CONFIDENCE:
        reasons.append("illegal_confidence")
    elif conf not in _PROMOTABLE_CONFIDENCE:
        reasons.append("low_confidence")
    for field in ("claim", "why_matters", "verification_summary", "counterargument"):
        v = evidence.get(field)
        if not (isinstance(v, str) and v.strip()):
            reasons.append(f"missing_{field}")
    return reasons


def sanitize_verifier_result(result: dict) -> dict:
    """Strip any raw-body / prompt key from a result before it can leave the
    service (AC7). Recursive over nested dicts/lists."""
    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items() if k not in _RAW_BODY_KEYS}
        if isinstance(obj, list):
            return [_clean(v) for v in obj]
        return obj
    return _clean(result)


# --------------------------------------------------------------------------- #
# Orchestration — verify_candidate / get_verifier_health.
# LLM + DB seams are module-level so tests can monkeypatch (no real Anthropic).
# --------------------------------------------------------------------------- #
def _call_opus(system: str, user: str, *, model: str, max_tokens: int):
    from kbl.anthropic_client import call_opus
    return call_opus(system, user, max_tokens=max_tokens, model=model)


def _existing_verified_item_id(conn, signal_candidate_id: int) -> Optional[int]:
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM verified_items WHERE signal_candidate_id = %s LIMIT 1",
            (signal_candidate_id,),
        )
        r = cur.fetchone(); cur.close()
        return int(r[0]) if r else None
    except Exception:
        return None


def verify_candidate(
    candidate_id: int,
    *,
    actor_id: str = "cortex:dashboard-v2-verifier",
    model: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Verify one candidate and (unless dry_run) promote it to a trusted
    ``verified_items`` row via the audited Cortex promotion helper. Returns a
    sanitized result dict — never raw bodies, never prompt text (AC7).

    Error contract (sanitized ``{"ok": False, "error": <code>, ...}``):
      not_found · bad_candidate_status · unsupported_source · source_not_found ·
      already_verified · model_not_allowed · cost_hard_stop · provider_unavailable ·
      bad_json · verification_refused · promote_failed · internal_error
    """
    from orchestrator import candidate_ingest
    from orchestrator.cost_monitor import check_circuit_breaker, log_api_cost

    try:
        # 1-3: candidate exists + is awaiting verification.
        cand = candidate_ingest.get_candidate(candidate_id)
        if not cand:
            return {"ok": False, "error": "not_found", "candidate_id": candidate_id}
        if cand.get("status") != "awaiting_verification":
            return {"ok": False, "error": "bad_candidate_status",
                    "candidate_id": candidate_id, "status": cand.get("status")}

        # verifier model floor (Opus-class only). Resolve + assert (AC1).
        verifier_model = model or model_policy.trusted_verification_model()
        try:
            model_policy.assert_trusted_verification_model(
                verifier_model, context="verify_candidate")
        except model_policy.TrustedModelPolicyError as e:
            return {"ok": False, "error": "model_not_allowed", "detail": str(e)}

        # 4-5: source context via allowlisted adapter + dedup check, on one conn.
        conn = candidate_ingest._get_conn()
        if conn is None:
            return {"ok": False, "error": "provider_unavailable", "detail": "db"}
        try:
            existing = _existing_verified_item_id(conn, candidate_id)
            if existing is not None:
                return {"ok": False, "error": "already_verified",
                        "verified_item_id": existing, "candidate_id": candidate_id}
            ctx = fetch_source_context(conn, cand.get("raw_source_table"),
                                       cand.get("raw_source_id"))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return {"ok": False, "error": "internal_error", "detail": str(e)[:200]}
        finally:
            candidate_ingest._put_conn(conn)

        if not ctx.get("ok"):
            return {"ok": False, "error": ctx.get("error", "source_not_found"),
                    "detail": ctx.get("detail")}

        # 7: cost breaker BEFORE the model call (AC10).
        allowed, daily_cost = check_circuit_breaker()
        if not allowed:
            return {"ok": False, "error": "cost_hard_stop", "daily_cost_eur": daily_cost}

        # 8: Opus call via the wrapper.
        system, user = build_verifier_prompt(cand, ctx)
        try:
            resp = _call_opus(system, user, model=verifier_model,
                              max_tokens=MAX_OUTPUT_TOKENS)
        except Exception as e:
            # AnthropicUnavailableError / transport -> 503-class; never partial write.
            logger.warning("verifier opus call failed for candidate %s: %s",
                           candidate_id, e)
            return {"ok": False, "error": "provider_unavailable", "detail": str(e)[:200]}

        # 9: log cost AFTER (AC10). Failure here must NOT undo a promotion.
        matter = cand.get("matter_slug")
        try:
            log_api_cost(
                getattr(resp, "model_id", verifier_model),
                getattr(resp, "input_tokens", 0), getattr(resp, "output_tokens", 0),
                source="dashboard_v2_verifier", matter_slug=matter,
                cache_creation_input_tokens=getattr(resp, "cache_write_tokens", 0),
                cache_read_input_tokens=getattr(resp, "cache_read_tokens", 0),
            )
        except Exception as e:
            logger.warning("verifier cost log failed (non-fatal) candidate %s: %s",
                           candidate_id, e)

        # 10-11: strict JSON + evidence/verdict gating.
        evidence = parse_verifier_json(getattr(resp, "text", "") or "")
        if evidence.get("_parse_error"):
            return {"ok": False, "error": "bad_json", "detail": evidence["_parse_error"],
                    "candidate_id": candidate_id, "verifier_model": verifier_model}
        reasons = validate_verifier_evidence(evidence)
        if reasons:
            return sanitize_verifier_result({
                "ok": False, "error": "verification_refused", "reasons": reasons,
                "verdict": evidence.get("verdict"), "candidate_id": candidate_id,
                "verifier_model": verifier_model,
            })

        if dry_run:
            return sanitize_verifier_result({
                "ok": True, "dry_run": True, "would_promote": True,
                "candidate_id": candidate_id, "verifier_model": verifier_model,
                "verdict": "promote", "confidence": evidence.get("confidence"),
            })

        # 12: promote ONLY via the audited Cortex helper (AC5 / STOP cond 4).
        promo = candidate_ingest.promote_candidate_verified_by_cortex(
            candidate_id,
            evidence=_build_evidence_packet(evidence, ctx, cand),
            actor_id=actor_id, verifier_model=verifier_model,
        )
        if not promo.get("ok"):
            return sanitize_verifier_result(
                {"ok": False, "error": promo.get("error", "promote_failed"),
                 "detail": promo.get("detail"), "candidate_id": candidate_id})
        return sanitize_verifier_result({
            "ok": True, "candidate_id": candidate_id,
            "verified_item_id": promo.get("verified_item_id"),
            "verifier_model": verifier_model, "confidence": evidence.get("confidence"),
        })
    except Exception as e:  # never raise out of the service
        logger.exception("verify_candidate unexpected failure candidate %s", candidate_id)
        return {"ok": False, "error": "internal_error", "detail": str(e)[:200]}


def _build_evidence_packet(evidence: dict, ctx: dict, cand: dict) -> dict:
    """Assemble the metadata-only evidence packet handed to the promotion helper.
    source_refs carry ONLY {table,id,candidate_id} — no raw body/snippet (AC7)."""
    src_ref = dict(ctx.get("source_ref") or {})
    src_ref["candidate_id"] = cand.get("id")
    return {
        "item_type": evidence.get("item_type") or cand.get("candidate_type") or "other",
        "claim": evidence.get("claim"),
        "why_matters": evidence.get("why_matters"),
        "next_action": evidence.get("next_action"),
        "owner": evidence.get("owner"),
        "due_at": evidence.get("due_at") or cand.get("due_at"),
        "confidence": (evidence.get("confidence") or "").strip().lower(),
        "matter_slug": evidence.get("matter_slug") or cand.get("matter_slug"),
        "related_matters": evidence.get("related_matters") or [],
        "people": evidence.get("people") or cand.get("people") or [],
        "source_type": ctx.get("source_type"),
        "source_trust": evidence.get("source_trust") or cand.get("source_trust"),
        "source_refs": [src_ref],
        "verification_summary": evidence.get("verification_summary"),
        "counterargument": evidence.get("counterargument"),
        # original machine-extraction model preserved for the audit delta (AC5.9).
        "candidate_extraction_model": cand.get("extraction_model"),
    }


def get_verifier_health() -> dict:
    """Health for the auth-gated endpoint (AC6). Metadata only — no source text."""
    vmodel = model_policy.trusted_verification_model()
    health = {
        "status": "ok",
        "verifier_model": vmodel,
        "verifier_model_allowed": model_policy.is_allowed_for_trusted_verification(vmodel),
        "supported_source_tables": list(SUPPORTED_SOURCE_TABLES),
    }
    try:
        from orchestrator import candidate_ingest
        conn = candidate_ingest._get_conn()
        if conn is not None:
            try:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM signal_candidates "
                            "WHERE status = 'awaiting_verification'")
                health["awaiting_candidates_count"] = int(cur.fetchone()[0])
                cur.close()
            finally:
                candidate_ingest._put_conn(conn)
        else:
            health["count_unavailable"] = True
    except Exception:
        health["count_unavailable"] = True
    return health
