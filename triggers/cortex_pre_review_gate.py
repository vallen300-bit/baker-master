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
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

GATE_TTL_SECONDS = 24 * 3600
DIRECTOR_DM_CHANNEL = "D0AFY28N030"  # canonical (matches triggers/audit_sentinel.py:19)
PUBLIC_BASE_URL = os.environ.get(
    "BAKER_PUBLIC_BASE_URL", "https://baker-master.onrender.com"
)


try:
    DEFAULT_COST_ESTIMATE_DOLLARS = float(
        os.environ.get("CORTEX_DEFAULT_COST_DOLLARS", "4.0")
    )
except ValueError:
    DEFAULT_COST_ESTIMATE_DOLLARS = 4.0


def _vault_root() -> Optional[Path]:
    """Return Path(BAKER_VAULT_PATH) or None if unset/invalid.

    On Render the env var points at the baker-vault-mirror checkout
    (e.g. /opt/render/project/src/baker-vault-mirror). On B-code worktrees,
    /Users/dimitry/baker-vault. Tests set it to a tmp path.
    """
    raw = os.environ.get("BAKER_VAULT_PATH", "").strip()
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_dir() else None


def matter_has_cortex_config(matter_slug: str) -> bool:
    """True iff <vault>/wiki/matters/<matter_slug>/cortex-config.md exists
    AND current Cortex policy allows this matter.

    Single source of truth for 'is this matter Cortex-enabled'. Used by the
    pre-review gate; future: also by /api/cortex/run rate-limit upstream.

    In Cortex Lite mode, config existence is necessary but not sufficient:
    CORTEX_LITE_MATTERS is the temporary matter allowlist.
    """
    if not matter_slug:
        return False
    root = _vault_root()
    if not root:
        return False
    cfg = root / "wiki" / "matters" / matter_slug / "cortex-config.md"
    if not cfg.is_file():
        return False
    try:
        from orchestrator.cortex_lite_policy import matter_allowed
        if not matter_allowed(matter_slug):
            logger.info(
                "cortex lite skipped matter=%s not in CORTEX_LITE_MATTERS",
                matter_slug,
            )
            return False
    except Exception as e:
        logger.error("cortex lite matter policy failed matter=%s: %s", matter_slug, e)
        return False
    return True


def _read_cost_estimate(matter_slug: str) -> float:
    """Read 'cost_estimate_dollars' from cortex-config.md frontmatter, else default.

    Lightweight YAML-free parse — line-based on '---'-delimited frontmatter.
    Avoids pulling in yaml just for one optional float.
    """
    root = _vault_root()
    if not root:
        return DEFAULT_COST_ESTIMATE_DOLLARS
    cfg = root / "wiki" / "matters" / matter_slug / "cortex-config.md"
    if not cfg.is_file():
        return DEFAULT_COST_ESTIMATE_DOLLARS
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            return DEFAULT_COST_ESTIMATE_DOLLARS
        end = text.find("\n---", 3)
        if end < 0:
            return DEFAULT_COST_ESTIMATE_DOLLARS
        fm = text[3:end]
        for line in fm.splitlines():
            line = line.strip()
            if line.startswith("cost_estimate_dollars:"):
                val = line.split(":", 1)[1].strip()
                try:
                    return float(val)
                except ValueError:
                    return DEFAULT_COST_ESTIMATE_DOLLARS
        return DEFAULT_COST_ESTIMATE_DOLLARS
    except Exception as e:
        logger.error("read_cost_estimate failed matter=%s: %s", matter_slug, e)
        return DEFAULT_COST_ESTIMATE_DOLLARS


def matter_notification_deferred(matter_slug: str) -> bool:
    """CORTEX_NOTIFICATION_DEFER_1: True iff cortex-config.md frontmatter
    has ``notification_defer: true``.

    When True, suppress the cost-warn Slack DM for ALL Cortex cycles on
    this matter (per-matter opt-out). Logger.info still emits — only the
    Slack push is gated.

    Returns False on any of: vault unset, config missing, frontmatter
    malformed, field absent, value not truthy. Fail-closed: if we can't
    read the field cleanly, default to current behavior (DM fires).
    Mirrors ``_read_cost_estimate`` parsing pattern (no PyYAML dependency).
    """
    if not matter_slug:
        return False
    root = _vault_root()
    if not root:
        return False
    cfg = root / "wiki" / "matters" / matter_slug / "cortex-config.md"
    if not cfg.is_file():
        return False
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            return False
        end = text.find("\n---", 3)
        if end < 0:
            return False
        fm = text[3:end]
        for line in fm.splitlines():
            line = line.strip()
            if line.startswith("notification_defer:"):
                val = line.split(":", 1)[1].strip().lower()
                return val in ("true", "yes", "on", "1")
        return False
    except Exception as e:
        logger.error("matter_notification_deferred failed matter=%s: %s", matter_slug, e)
        return False


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


def record_decision(*, signal_id: int, action: str, matter_slug: str) -> bool:
    """Atomically claim the decision row for ``signal_id`` in baker_actions.

    Returns True if THIS call inserted the row (i.e. claimed the decision),
    False if a concurrent call already claimed it (or DB unavailable / error).

    The caller MUST check the return value and skip the cycle fire when False.
    This closes the TOCTOU race between ``already_decided()`` and the prior
    plain INSERT (CORTEX_PRE_REVIEW_GATE_2 — security-review confidence 9
    blocker). Race surface includes:
      - iPhone double-tap on slow 4G (perceived non-response → user re-taps)
      - Slack URL preview unfurl GETting the link server-side
      - Any second-tap happening before the first completes

    Atomicity: ``INSERT ... SELECT ... WHERE NOT EXISTS ... RETURNING id``
    is a single statement. Postgres serializes concurrent attempts against
    the same target_task_id at row-lock level. The losing INSERT inserts no
    row; ``RETURNING id`` produces no row → ``cur.fetchone()`` returns None.

    Uses ``json.dumps`` for payload so matter_slug / action cannot SQL-inject
    via curly-brace embedding.
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            payload_json = json.dumps({
                "signal_id": int(signal_id),
                "matter_slug": str(matter_slug),
                "action": str(action),
            })
            cur.execute(
                "INSERT INTO baker_actions "
                "(action_type, target_task_id, payload, trigger_source, success) "
                "SELECT %s, %s, %s::jsonb, %s, %s "
                "WHERE NOT EXISTS ("
                "    SELECT 1 FROM baker_actions "
                "    WHERE target_task_id = %s "
                "    AND action_type IN ('cortex:gate:approved','cortex:gate:skipped')"
                ") "
                "RETURNING id",
                (
                    f"cortex:gate:{action}",
                    str(signal_id),
                    payload_json,
                    "cortex_pre_review_gate",
                    True,
                    str(signal_id),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            return row is not None  # True if INSERT actually wrote a row
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
        return False


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
    Returns False if matter has no cortex-config.md (Phase 2 has nothing to
    load → no point asking Director to approve a spend with no per-matter
    brain). Returns False if gate disabled (secret missing/short) — caller
    decides whether to fall through to legacy direct-fire.

    Logging: signal_id + matter_slug at info-level OK; preview / signal_text
    NEVER info-logged (sensitive matter content); frontmatter content beyond
    cost is NEVER logged (potential matter intel).
    """
    if already_decided(signal_id):
        logger.info("gate skipped — signal_id=%s already decided", signal_id)
        return False

    # CORTEX_MULTI_MATTER_GATE_1: whitelist by config presence. Single source
    # of truth = cortex-config.md existence under <vault>/wiki/matters/<slug>/.
    if not matter_has_cortex_config(matter_slug):
        logger.info(
            "gate skipped — matter=%s has no cortex-config.md (signal_id=%s)",
            matter_slug, signal_id,
        )
        return False

    if _secret() is None:
        logger.error(
            "CORTEX_GATE_SECRET unset/short — gate disabled, signal_id=%s "
            "would fire cycle without approval", signal_id,
        )
        return False

    cost = _read_cost_estimate(matter_slug)
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
        f"Approx cost: ${cost:.2f} if approved.\n"
        f"\n*Preview:*\n>>> {preview}\n"
        f"\n<{approve_url}|✅ Yes, review (~${cost:.2f})>   |   "
        f"<{skip_url}|❌ Skip>"
    )

    try:
        from outputs.slack_notifier import post_to_channel
        # CORTEX_PRE_REVIEW_GATE_2 (Blocker 2): suppress Slack URL unfurling.
        # The gate URLs are *side-effecting GETs* — Slack's link-preview
        # fetcher (Slackbot-LinkExpanding) will GET each URL the moment we
        # post the message, which would auto-fire record_decision + cycle
        # before the Director ever taps. Both unfurl flags must be False.
        return bool(post_to_channel(
            DIRECTOR_DM_CHANNEL, text,
            unfurl_links=False,
            unfurl_media=False,
        ))
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
