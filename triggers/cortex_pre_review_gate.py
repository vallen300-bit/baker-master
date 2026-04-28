"""CORTEX_PRE_REVIEW_GATE_1: cost gate for auto-dispatched Cortex cycles.

When a signal lands that would auto-fire a Cortex cycle, this module posts
a cheap Slack DM with two signed-URL links instead of firing immediately.
Director taps "Yes review" → background task fires maybe_run_cycle. Taps
"Skip" → decision recorded, no spend.

Stateless tokens: HMAC-SHA256(signal_id|action|expires_at, secret).
Secret = env var CORTEX_GATE_SECRET (>=32 chars; gate disabled if unset/short).
Token TTL = 24h.

Decision audit lives in baker_actions (action_type='cortex:gate:*');
no new table needed. Idempotency: re-clicking checks baker_actions.

Schema notes:
    signal_queue columns: id, source, signal_type, **matter** (NOT matter_slug),
    summary (NOT signal_text), payload, ... — see memory/store_back.py:6600.
    The brief used the names matter_slug / signal_text; this module uses the
    actual column names matter / summary. (Lesson #40 cousin — verify schema
    before migration; here we verify before referencing.)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

GATE_TTL_SECONDS = 24 * 3600
DIRECTOR_DM_CHANNEL = "D0AFY28N030"  # canonical (matches triggers/audit_sentinel.py:19)
PUBLIC_BASE_URL = os.environ.get(
    "BAKER_PUBLIC_BASE_URL", "https://baker-master.onrender.com"
)


def _secret() -> Optional[str]:
    """Return CORTEX_GATE_SECRET if set + length>=32, else None.

    Length floor of 32 chars enforces baseline entropy on the HMAC key.
    Read on every call — env may change between import and first signal.
    """
    s = os.environ.get("CORTEX_GATE_SECRET", "").strip()
    return s if len(s) >= 32 else None


def sign_token(*, signal_id: int, action: str, expires_at: int) -> str:
    """Sign a (signal_id, action, expires_at) tuple. Returns base64url HMAC.

    Returns empty string if secret unset/short (caller checks; if empty, gate
    is disabled and the legacy direct-fire fallback runs).
    """
    secret = _secret()
    if not secret:
        return ""
    payload = f"{signal_id}|{action}|{expires_at}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")


def verify_token(*, signal_id: int, action: str, expires_at: int, token: str) -> Tuple[bool, str]:
    """Constant-time verify (signal_id, action, expires_at, token).

    Returns (ok, error_message). Failure modes (in priority order):
      - invalid_action  : action not in {approve, skip}
      - gate_disabled   : CORTEX_GATE_SECRET unset/short
      - expired         : expires_at < now
      - bad_signature   : HMAC mismatch
    Uses hmac.compare_digest for constant-time signature comparison.
    """
    if action not in ("approve", "skip"):
        return False, "invalid_action"
    secret = _secret()
    if not secret:
        return False, "gate_disabled"
    if int(time.time()) > expires_at:
        return False, "expired"
    expected = sign_token(signal_id=signal_id, action=action, expires_at=expires_at)
    if not expected:
        return False, "gate_disabled"
    if not hmac.compare_digest(expected, token):
        return False, "bad_signature"
    return True, ""


def already_decided(signal_id: int) -> Optional[str]:
    """Return the prior decision action ('approved'|'skipped') if signal_id
    already has a baker_actions row, else None.

    Read-only; safe to call on every gate post + every gate decide.
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
                "SELECT action_type FROM baker_actions "
                "WHERE action_type IN ('cortex:gate:approved','cortex:gate:skipped') "
                "AND target_task_id = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (str(signal_id),),
            )
            row = cur.fetchone()
            cur.close()
            if not row:
                return None
            return row[0].split(":")[-1]  # 'approved' or 'skipped'
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error("already_decided lookup failed: %s", e)
        return None


def record_decision(*, signal_id: int, action: str, matter_slug: str) -> None:
    """Insert a baker_actions row for the gate decision.

    Idempotent: caller should already_decided() check first; this writes
    unconditionally. Failures are logged + swallowed (audit best-effort).

    Uses parameterized JSON to avoid injection from matter_slug. (psycopg2
    will escape the string; we do not f-string user data into SQL.)
    """
    try:
        from memory.store_back import SentinelStoreBack
        import json as _json
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            payload_json = _json.dumps({
                "signal_id": int(signal_id),
                "matter_slug": str(matter_slug),
                "action": str(action),
            })
            cur.execute(
                "INSERT INTO baker_actions (action_type, target_task_id, payload, "
                "trigger_source, success) VALUES (%s, %s, %s::jsonb, %s, %s)",
                (
                    f"cortex:gate:{action}",
                    str(signal_id),
                    payload_json,
                    "cortex_pre_review_gate",
                    True,
                ),
            )
            conn.commit()
            cur.close()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error("record_decision insert failed signal_id=%s: %s", signal_id, e)


def _signal_preview(signal_id: int) -> str:
    """Fetch ~400 chars of the inbound signal's summary for the gate preview.

    Reads `summary` column (signal_queue real schema — see module docstring).
    Sensitive content: returned only into Slack DM; never info-logged.
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return "(preview unavailable)"
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT summary FROM signal_queue WHERE id = %s",
                (signal_id,),
            )
            row = cur.fetchone()
            cur.close()
            if not row or not row[0]:
                return "(no preview)"
            return str(row[0])[:400]
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error("signal_preview fetch failed signal_id=%s: %s", signal_id, e)
        return "(preview error)"


def post_gate(*, signal_id: int, matter_slug: str) -> bool:
    """Post the pre-review gate Slack DM. Returns True if posted.

    Idempotency: returns False (no-op) if already_decided(signal_id) is set.
    Returns False if gate disabled (secret missing/short) — caller decides
    whether to fall through to legacy direct-fire.

    Logging: signal_id + matter_slug at info-level OK; preview / signal_text
    NEVER info-logged (sensitive matter content).
    """
    if already_decided(signal_id):
        logger.info("gate skipped — signal_id=%s already decided", signal_id)
        return False

    if _secret() is None:
        logger.error(
            "CORTEX_GATE_SECRET unset/short — gate disabled, signal_id=%s "
            "would fire cycle without approval", signal_id,
        )
        return False

    expires_at = int(time.time()) + GATE_TTL_SECONDS
    approve_tok = sign_token(signal_id=signal_id, action="approve", expires_at=expires_at)
    skip_tok = sign_token(signal_id=signal_id, action="skip", expires_at=expires_at)
    approve_url = (
        f"{PUBLIC_BASE_URL}/api/cortex/gate/decide"
        f"?signal_id={signal_id}&action=approve&exp={expires_at}&token={approve_tok}"
    )
    skip_url = (
        f"{PUBLIC_BASE_URL}/api/cortex/gate/decide"
        f"?signal_id={signal_id}&action=skip&exp={expires_at}&token={skip_tok}"
    )

    preview = _signal_preview(signal_id)
    text = (
        f"📨 *New {matter_slug.upper()} signal — review with Cortex?*\n"
        f"Approx cost: $4 if approved.\n"
        f"\n*Preview:*\n>>> {preview}\n"
        f"\n<{approve_url}|✅ Yes, review (~$4)>   |   "
        f"<{skip_url}|❌ Skip>"
    )

    try:
        from outputs.slack_notifier import post_to_channel
        return bool(post_to_channel(DIRECTOR_DM_CHANNEL, text))
    except Exception as e:
        logger.error("post_gate Slack post failed signal_id=%s: %s", signal_id, e)
        return False


def lookup_matter_slug(signal_id: int) -> Optional[str]:
    """Return the `matter` column for a signal_queue row, or None on miss/error.

    Used by the dashboard endpoint to populate the audit row + cycle args.
    Read-only; sensitive payload columns NOT touched.
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("SELECT matter FROM signal_queue WHERE id = %s", (signal_id,))
            row = cur.fetchone()
            cur.close()
            if not row:
                return None
            return row[0] or ""
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error("lookup_matter_slug failed signal_id=%s: %s", signal_id, e)
        return None
