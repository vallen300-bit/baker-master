"""Weekly xAI spend reservation ledger — GROK_4_5_WEEK_TRIAL_1.

Governs the combined weekly xAI cap for the Grok-4.5 trial. Persisted, never
in-memory (order requirement, brief #11213). Append-only rows in
``xai_week_ledger`` (kind ∈ reserve/settle/release); the remaining weekly budget
is derived in ONE transaction under a Postgres advisory lock keyed on the week,
so two concurrent callers can never both slip past the cap.

Accounting identity (per week)::

    total_reserved  = Σ amount WHERE kind='reserve'
    total_settled   = Σ amount WHERE kind='settle'
    total_released  = Σ amount WHERE kind='release'
    open_reserves   = total_reserved − total_settled − total_released   (still held)
    effective_used  = total_settled + open_reserves = total_reserved − total_released
    remaining       = cap − effective_used

Lifecycle of one call (request_ref threads the three rows):

  1. ``reserve()``  — conservative pre-call hold (max_in + max_out + tool allowance).
     Granted only if ``effective_used + amount ≤ cap`` — else HARD-BLOCK (fail loud).
  2. ``settle()``   — after the response: record the ACTUAL spend and release the
     unused residual (reserved − actual) so it returns to the weekly pool.
  3. ``release()``  — if the call fails before spend, or the reserve goes stale,
     release the full remaining hold.

A crashed call leaves a reserve with no settle/release; ``sweep_stale_reserves()``
releases those after a bounded TTL and writes an audit note.

FAIL-CLOSED: on any DB/verification failure during ``reserve``, the grant is
DENIED (never silently allowed) — a cost cap must degrade closed. This is the
opposite of the tier-alarm breaker, which degrades open.

Actuals also settle into ``api_cost_log`` via the caller (source=grok_realtime,
cost_usd_override) — this ledger governs the weekly xAI cap only; it does not
replace the daily cost log.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger("baker.xai_week_ledger")

# ─────────────────────────── config ───────────────────────────

WEEKLY_CAP_USD = float(os.getenv("BAKER_XAI_WEEKLY_CAP_USD", "150.0"))
WEEKLY_WARN_USD = float(os.getenv("BAKER_XAI_WEEKLY_WARN_USD", "120.0"))
RESERVE_TTL_MIN = int(os.getenv("BAKER_XAI_RESERVE_TTL_MIN", "30"))

# Advisory-lock namespace (arbitrary constant, unique to this ledger). The lock
# key is (this namespace, week ordinal) — pg_advisory_xact_lock(int4, int4).
_LOCK_NAMESPACE = 0x78414957  # 'xAIW' bytes → int32-safe constant


# ─────────────────────────── week helpers ───────────────────────────

def week_start(d: Optional[date] = None) -> date:
    """Return the Monday (UTC) of the week containing ``d`` (default: today)."""
    if d is None:
        d = datetime.now(timezone.utc).date()
    return d - timedelta(days=d.weekday())


def _lock_key(week: date) -> int:
    """int4 lock key for a given week — the week's proleptic-Gregorian ordinal.

    Well inside int32 range (year 2026 ≈ 739000) and unique per week.
    """
    return week.toordinal()


# ─────────────────────────── table DDL ───────────────────────────

def ensure_xai_week_ledger_tables(conn) -> None:
    """Create xai_week_ledger + xai_call_audit (idempotent). Mirrors migration
    20260714a_xai_week_ledger.sql so fresh/test DBs match prod (Lesson #50)."""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS xai_week_ledger (
                id          SERIAL PRIMARY KEY,
                week_start  DATE NOT NULL,
                route       TEXT NOT NULL,
                kind        TEXT NOT NULL CHECK (kind IN ('reserve', 'settle', 'release')),
                amount_usd  NUMERIC(12, 6) NOT NULL,
                request_ref TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_xai_week_ledger_week
            ON xai_week_ledger (week_start)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_xai_week_ledger_request_ref
            ON xai_week_ledger (request_ref)
        """)
        # P1-4: at most ONE settle row per request_ref — DB-level guarantee that a
        # settle retried after a lost ack cannot double-count (belt to the in-txn
        # _has_settle no-op braces).
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_xai_week_ledger_settle_ref
            ON xai_week_ledger (request_ref) WHERE kind = 'settle'
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS xai_call_audit (
                id            SERIAL PRIMARY KEY,
                logged_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                provider      TEXT NOT NULL DEFAULT 'xai',
                model         TEXT NOT NULL,
                route         TEXT NOT NULL,
                request_ref   TEXT,
                tokens_in     INTEGER DEFAULT 0,
                tokens_out    INTEGER DEFAULT 0,
                reserved_usd  NUMERIC(12, 6) DEFAULT 0,
                est_usd       NUMERIC(12, 6) DEFAULT 0,
                actual_usd    NUMERIC(12, 6) DEFAULT 0,
                tool_schema   TEXT,
                outcome       TEXT NOT NULL,
                error_class   TEXT,
                matter_slug   TEXT DEFAULT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_xai_call_audit_logged_at
            ON xai_call_audit (logged_at)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_xai_call_audit_route
            ON xai_call_audit (route)
        """)
        conn.commit()
        cur.close()
        logger.info("xai_week_ledger + xai_call_audit tables verified")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"Could not ensure xai_week_ledger tables: {e}")


# ─────────────────────────── connection plumbing ───────────────────────────

def _store():
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


# ─────────────────────────── budget math ───────────────────────────

def _totals(cur, week: date) -> tuple[float, float, float]:
    """(total_reserved, total_settled, total_released) for ``week``."""
    cur.execute(
        """SELECT
             COALESCE(SUM(amount_usd) FILTER (WHERE kind='reserve'), 0),
             COALESCE(SUM(amount_usd) FILTER (WHERE kind='settle'),  0),
             COALESCE(SUM(amount_usd) FILTER (WHERE kind='release'), 0)
           FROM xai_week_ledger WHERE week_start = %s""",
        (week,),
    )
    r = cur.fetchone()
    return float(r[0]), float(r[1]), float(r[2])


def _effective_used(cur, week: date) -> float:
    reserved, settled, released = _totals(cur, week)
    return reserved - released  # == settled + open_reserves


def remaining_budget(week: Optional[date] = None, conn=None) -> dict:
    """Report the weekly budget state. Read-only; no lock needed for a snapshot.

    Returns a dict with cap/warn/settled/open_reserves/effective_used/remaining.
    On DB failure returns remaining=0.0 with ``ok=False`` (fail-closed view).
    """
    week = week or week_start()
    own = conn is None
    if own:
        conn = _store()._get_conn()
    if not conn:
        return {"ok": False, "week_start": str(week), "cap_usd": WEEKLY_CAP_USD,
                "warn_usd": WEEKLY_WARN_USD, "settled_usd": 0.0,
                "open_reserves_usd": 0.0, "effective_used_usd": 0.0,
                "remaining_usd": 0.0}
    try:
        cur = conn.cursor()
        reserved, settled, released = _totals(cur, week)
        cur.close()
        open_reserves = reserved - settled - released
        effective_used = reserved - released
        return {
            "ok": True,
            "week_start": str(week),
            "cap_usd": WEEKLY_CAP_USD,
            "warn_usd": WEEKLY_WARN_USD,
            "settled_usd": round(settled, 6),
            "open_reserves_usd": round(open_reserves, 6),
            "effective_used_usd": round(effective_used, 6),
            "remaining_usd": round(WEEKLY_CAP_USD - effective_used, 6),
            "over_warn": effective_used >= WEEKLY_WARN_USD,
        }
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"remaining_budget read failed: {e}")
        return {"ok": False, "week_start": str(week), "cap_usd": WEEKLY_CAP_USD,
                "warn_usd": WEEKLY_WARN_USD, "settled_usd": 0.0,
                "open_reserves_usd": 0.0, "effective_used_usd": 0.0,
                "remaining_usd": 0.0}
    finally:
        if own:
            _store()._put_conn(conn)


# ─────────────────────────── reserve / settle / release ───────────────────────────

def reserve(route: str, amount_usd: float, request_ref: str,
            week: Optional[date] = None, conn=None) -> dict:
    """Atomically reserve ``amount_usd`` against the weekly cap for ``route``.

    Runs the read-then-insert in ONE transaction under a pg advisory lock keyed
    on the week, so concurrent reserves cannot both exceed the cap. Grants only
    when ``effective_used + amount ≤ cap`` — otherwise HARD-BLOCK (no row written).

    Returns ``{granted: bool, reason, remaining_usd, effective_used_usd,
    reserved_usd, cap_usd, warn, over_warn, week_start}``.

    FAIL-CLOSED: any DB error → ``granted=False, reason='ledger_unavailable'``.
    """
    week = week or week_start()
    if not (isinstance(amount_usd, (int, float)) and amount_usd > 0):
        return {"granted": False, "reason": "invalid_amount", "amount_usd": amount_usd,
                "remaining_usd": 0.0, "cap_usd": WEEKLY_CAP_USD, "week_start": str(week)}
    own = conn is None
    if own:
        conn = _store()._get_conn()
    if not conn:
        return {"granted": False, "reason": "ledger_unavailable",
                "remaining_usd": 0.0, "cap_usd": WEEKLY_CAP_USD, "week_start": str(week)}
    try:
        cur = conn.cursor()
        # Serialize all budget math for this week within the transaction.
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK_NAMESPACE, _lock_key(week)))
        effective_used = _effective_used(cur, week)
        projected = effective_used + float(amount_usd)
        if projected > WEEKLY_CAP_USD:
            conn.commit()  # release the xact lock; no row written
            cur.close()
            logger.error(
                "xAI weekly cap HARD-BLOCK route=%s amount=%.6f used=%.6f cap=%.2f",
                route, amount_usd, effective_used, WEEKLY_CAP_USD,
            )
            return {"granted": False, "reason": "weekly_cap_reached",
                    "remaining_usd": round(WEEKLY_CAP_USD - effective_used, 6),
                    "effective_used_usd": round(effective_used, 6),
                    "reserved_usd": round(float(amount_usd), 6),
                    "cap_usd": WEEKLY_CAP_USD, "week_start": str(week)}
        cur.execute(
            """INSERT INTO xai_week_ledger (week_start, route, kind, amount_usd, request_ref)
               VALUES (%s, %s, 'reserve', %s, %s)""",
            (week, route, float(amount_usd), request_ref),
        )
        conn.commit()
        cur.close()
        over_warn = projected >= WEEKLY_WARN_USD
        if over_warn:
            logger.warning(
                "xAI weekly WARN route=%s projected=%.6f warn=%.2f cap=%.2f",
                route, projected, WEEKLY_WARN_USD, WEEKLY_CAP_USD,
            )
        return {"granted": True, "reason": "ok",
                "remaining_usd": round(WEEKLY_CAP_USD - projected, 6),
                "effective_used_usd": round(projected, 6),
                "reserved_usd": round(float(amount_usd), 6),
                "cap_usd": WEEKLY_CAP_USD, "warn": over_warn, "over_warn": over_warn,
                "week_start": str(week)}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"reserve failed (fail-closed, denying): {e}")
        return {"granted": False, "reason": "ledger_unavailable",
                "remaining_usd": 0.0, "cap_usd": WEEKLY_CAP_USD, "week_start": str(week)}
    finally:
        if own:
            _store()._put_conn(conn)


def _has_settle(cur, week: date, request_ref: str) -> bool:
    """True if a settle row already exists for ``request_ref`` this week (P1-4)."""
    cur.execute(
        """SELECT 1 FROM xai_week_ledger
           WHERE week_start = %s AND request_ref = %s AND kind = 'settle' LIMIT 1""",
        (week, request_ref),
    )
    return cur.fetchone() is not None


def _held_for_ref(cur, week: date, request_ref: str) -> float:
    """Amount still held for one request_ref = reserved − settled − released."""
    cur.execute(
        """SELECT
             COALESCE(SUM(amount_usd) FILTER (WHERE kind='reserve'), 0)
           - COALESCE(SUM(amount_usd) FILTER (WHERE kind='settle'),  0)
           - COALESCE(SUM(amount_usd) FILTER (WHERE kind='release'), 0)
           FROM xai_week_ledger WHERE week_start = %s AND request_ref = %s""",
        (week, request_ref),
    )
    return float(cur.fetchone()[0])


def settle(request_ref: str, actual_usd: float, route: str,
           week: Optional[date] = None, conn=None) -> dict:
    """Record ACTUAL spend for ``request_ref`` and release the unused residual.

    Writes a ``settle`` row (actual) and, if the reserve exceeded actual, a
    ``release`` row for the residual so it returns to the weekly pool.

    IDEMPOTENT (P1-4): a settle that COMMITS but whose ack/return is lost to a
    network fault makes the caller retry. Under the per-week advisory lock we
    first check for an existing settle row for this ref and no-op if present
    (``reason='already_settled'``) — so a retry-after-commit never inserts a
    second settle/top-up and never double-burns the weekly cap. A partial unique
    index (``uq_xai_week_ledger_settle_ref``) enforces the one-settle-per-ref
    invariant at the DB layer as well.
    """
    week = week or week_start()
    actual = max(0.0, float(actual_usd or 0.0))
    own = conn is None
    if own:
        conn = _store()._get_conn()
    if not conn:
        return {"settled": False, "reason": "ledger_unavailable"}
    try:
        cur = conn.cursor()
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK_NAMESPACE, _lock_key(week)))
        # P1-4: idempotent no-op if this ref already settled (retry after lost ack).
        if _has_settle(cur, week, request_ref):
            conn.commit()  # release the xact lock; no new rows
            cur.close()
            logger.info(
                "xAI settle idempotent no-op route=%s ref=%s (already settled this week)",
                route, request_ref,
            )
            return {"settled": True, "reason": "already_settled",
                    "actual_usd": 0.0, "released_residual_usd": 0.0,
                    "topup_usd": 0.0, "idempotent": True, "week_start": str(week)}
        held = _held_for_ref(cur, week, request_ref)
        # P1-1 fix: actual spend can EXCEED the reservation (trial_route settles
        # max(payload cost, token-rate cost) as the conservative actual). If we
        # only ever released a residual, that excess would never reach the cap
        # (effective_used = reserved − released stays at the reserved amount).
        # Top up the reservation by the shortfall in the SAME txn so the cap
        # reflects true spend. Not cap-gated — this records spend already
        # incurred, it does not request new budget.
        topup = actual - held
        if topup > 0:
            cur.execute(
                """INSERT INTO xai_week_ledger (week_start, route, kind, amount_usd, request_ref)
                   VALUES (%s, %s, 'reserve', %s, %s)""",
                (week, route, round(topup, 6), request_ref),
            )
        cur.execute(
            """INSERT INTO xai_week_ledger (week_start, route, kind, amount_usd, request_ref)
               VALUES (%s, %s, 'settle', %s, %s)""",
            (week, route, actual, request_ref),
        )
        residual = held - actual  # only positive when actual < held
        if residual > 0:
            cur.execute(
                """INSERT INTO xai_week_ledger (week_start, route, kind, amount_usd, request_ref)
                   VALUES (%s, %s, 'release', %s, %s)""",
                (week, route, round(residual, 6), request_ref),
            )
        conn.commit()
        cur.close()
        return {"settled": True, "reason": "ok", "actual_usd": round(actual, 6),
                "released_residual_usd": round(max(0.0, residual), 6),
                "topup_usd": round(max(0.0, topup), 6),
                "week_start": str(week)}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"settle failed: {e}")
        return {"settled": False, "reason": "settle_error"}
    finally:
        if own:
            _store()._put_conn(conn)


def release(request_ref: str, route: str, reason: str = "released",
            week: Optional[date] = None, conn=None) -> dict:
    """Release the full remaining hold for ``request_ref`` (no spend recorded).

    Used when a call fails before any spend, and by the stale-reserve sweep.
    """
    week = week or week_start()
    own = conn is None
    if own:
        conn = _store()._get_conn()
    if not conn:
        return {"released": False, "reason": "ledger_unavailable"}
    try:
        cur = conn.cursor()
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK_NAMESPACE, _lock_key(week)))
        held = _held_for_ref(cur, week, request_ref)
        released = 0.0
        if held > 0:
            cur.execute(
                """INSERT INTO xai_week_ledger (week_start, route, kind, amount_usd, request_ref)
                   VALUES (%s, %s, 'release', %s, %s)""",
                (week, route, round(held, 6), request_ref),
            )
            released = held
        conn.commit()
        cur.close()
        return {"released": released > 0, "reason": reason,
                "released_usd": round(released, 6), "week_start": str(week)}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"release failed: {e}")
        return {"released": False, "reason": "release_error"}
    finally:
        if own:
            _store()._put_conn(conn)


def sweep_stale_reserves(ttl_min: Optional[int] = None, conn=None) -> dict:
    """Release reserves older than the TTL that were never settled or released.

    A crashed call leaves a fully-open reserve; this returns that budget to the
    pool and writes an audit note (outcome='swept_stale_reserve') per ref.
    Returns ``{swept: int, released_usd: float}``.
    """
    ttl = RESERVE_TTL_MIN if ttl_min is None else ttl_min
    own = conn is None
    if own:
        conn = _store()._get_conn()
    if not conn:
        return {"swept": 0, "released_usd": 0.0, "reason": "ledger_unavailable"}
    try:
        cur = conn.cursor()
        # Refs whose reserve is older than the TTL and that have NO settle and NO
        # release yet (still fully held). Lock per-week is taken inside release().
        cur.execute(
            """SELECT r.request_ref, r.week_start, r.route, SUM(r.amount_usd)
               FROM xai_week_ledger r
               WHERE r.kind = 'reserve'
                 AND r.created_at < NOW() - (INTERVAL '1 minute' * %s)
                 AND NOT EXISTS (
                     SELECT 1 FROM xai_week_ledger s
                     WHERE s.request_ref = r.request_ref
                       AND s.kind IN ('settle', 'release'))
               GROUP BY r.request_ref, r.week_start, r.route""",
            (ttl,),
        )
        stale = cur.fetchall()
        cur.close()
        swept = 0
        released_usd = 0.0
        for ref, wk, route, amt in stale:
            res = release(ref, route, reason="stale_reserve_ttl", week=wk, conn=conn)
            if res.get("released"):
                swept += 1
                released_usd += float(res.get("released_usd") or 0.0)
                _write_audit(
                    conn, model="grok-4.5", route=route, request_ref=ref,
                    reserved_usd=float(amt), outcome="swept_stale_reserve",
                    error_class="stale_reserve_ttl",
                )
        return {"swept": swept, "released_usd": round(released_usd, 6)}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"sweep_stale_reserves failed: {e}")
        return {"swept": 0, "released_usd": 0.0, "reason": "sweep_error"}
    finally:
        if own:
            _store()._put_conn(conn)


# ─────────────────────────── per-call audit ───────────────────────────

def _write_audit(conn, *, model: str, route: str, request_ref: Optional[str] = None,
                 tokens_in: int = 0, tokens_out: int = 0, reserved_usd: float = 0.0,
                 est_usd: float = 0.0, actual_usd: float = 0.0,
                 tool_schema: Optional[str] = None, outcome: str = "ok",
                 error_class: Optional[str] = None,
                 matter_slug: Optional[str] = None) -> None:
    """Insert one xai_call_audit row. Never raises to the caller. NEVER stores
    prompt bodies or secrets — structured metadata only."""
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO xai_call_audit
               (provider, model, route, request_ref, tokens_in, tokens_out,
                reserved_usd, est_usd, actual_usd, tool_schema, outcome,
                error_class, matter_slug)
               VALUES ('xai', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (model, route, request_ref, int(tokens_in or 0), int(tokens_out or 0),
             round(float(reserved_usd or 0.0), 6), round(float(est_usd or 0.0), 6),
             round(float(actual_usd or 0.0), 6), tool_schema, outcome,
             error_class, matter_slug),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"_write_audit failed (non-fatal): {e}")


def write_call_audit(**kwargs) -> None:
    """Public audit-write that grabs its own connection. Fault-tolerant."""
    conn = _store()._get_conn()
    if not conn:
        logger.warning("write_call_audit: no DB connection; audit row dropped")
        return
    try:
        _write_audit(conn, **kwargs)
    finally:
        _store()._put_conn(conn)
