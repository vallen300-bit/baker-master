"""BAKER_DASHBOARD_V2_PIPELINE_ACTIVATION_1 — the workers that fill the V2 surface.

The V2 trust substrate (signal_candidates / verified_items / verification_events +
manual verifier) shipped, but prod is EMPTY: there is no running worker that
(A) creates candidates from the legacy live pools, nor (B) drains awaiting
candidates through the Opus verifier. `/api/today` is correctly empty because
nothing trusted exists yet.

This module adds both workers PLUS their scheduler registration — all behind
three env flags that DEFAULT OFF / 0, so merging + deploying this code spends
**$0** and changes **zero behavior**. Activation (flipping the flags + setting a
cap) is a separate Director-gated step, not part of the shipping PR.

Control surface (all default OFF/0):
  * ``DASHBOARD_V2_BRIDGE_ENABLED``        (default false) — gates producer A.
  * ``DASHBOARD_V2_VERIFIER_ENABLED``      (default false) — gates worker B.
  * ``DASHBOARD_V2_VERIFIER_MAX_PER_TICK`` (default 0)     — hard cap on LLM
    calls per verifier tick. 0 == disabled even if the flag is on.

Defence-in-depth on AC1 (flags OFF = zero-op):
  1. ``register_dashboard_v2_workers`` does NOT add a job whose flag is off, so a
     default deploy registers ZERO new scheduler jobs.
  2. Each tick function ALSO self-gates: called directly with the flag off it
     returns ``{"skipped": True, ...}`` before any DB read or model call.

Reuse, do not reimplement: producer calls the existing idempotent
``candidate_ingest`` bridges; worker B calls the existing ``verify_candidate``
(which owns the Opus-class floor + cost breaker). No new model selection here.
Every tick is fault-tolerant — a degraded DB / LLM error logs + is contained, so
a tick can never crash the scheduler.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("baker.dashboard_v2_workers")

# Internal cadence defaults (the 3 brief flags are the control surface; these are
# sensible intervals with optional ops override, floored to avoid hot loops).
_PRODUCER_DEFAULT_INTERVAL = 900   # 15 min
_VERIFIER_DEFAULT_INTERVAL = 300   # 5 min
_INTERVAL_FLOOR = 60

_PRODUCER_DEFAULT_MAX = 200        # alerts/deadlines bridged per producer tick
_VERIFIER_HARD_CEILING = 100       # absolute cap on LLM calls/tick regardless of env


# --------------------------------------------------------------------------- #
# Env config (read at call time so a flag flip needs no code change, only env).
# --------------------------------------------------------------------------- #
def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def bridge_enabled() -> bool:
    return _env_flag("DASHBOARD_V2_BRIDGE_ENABLED", False)


def verifier_enabled() -> bool:
    return _env_flag("DASHBOARD_V2_VERIFIER_ENABLED", False)


def verifier_max_per_tick() -> int:
    """Hard cap on LLM verifier calls per tick. Default 0 (disabled). Clamped to
    [0, _VERIFIER_HARD_CEILING] so a bad env value can never unleash a flood."""
    n = _env_int("DASHBOARD_V2_VERIFIER_MAX_PER_TICK", 0)
    if n <= 0:
        return 0
    return min(n, _VERIFIER_HARD_CEILING)


def producer_max_per_tick() -> int:
    n = _env_int("DASHBOARD_V2_BRIDGE_MAX_PER_TICK", _PRODUCER_DEFAULT_MAX)
    if n <= 0:
        return _PRODUCER_DEFAULT_MAX
    return min(n, 2000)


def _interval(name: str, default: int) -> int:
    n = _env_int(name, default)
    return n if n >= _INTERVAL_FLOOR else _INTERVAL_FLOOR


# --------------------------------------------------------------------------- #
# A. Candidate producer tick (free — no LLM).
# --------------------------------------------------------------------------- #
def run_candidate_producer_tick() -> dict:
    """Bridge the legacy pending-alert + active-deadline pools into
    ``signal_candidates`` (idempotent via dedup_key). Bounded per tick.

    Zero-op when ``DASHBOARD_V2_BRIDGE_ENABLED`` is off (AC1). Fault-tolerant:
    any failure logs + returns a result dict; never raises into the scheduler.
    """
    if not bridge_enabled():
        return {"skipped": True, "reason": "DASHBOARD_V2_BRIDGE_ENABLED off"}
    limit = producer_max_per_tick()
    out = {"ok": True, "bridged": 0, "skipped": 0, "failed": 0, "scanned": 0}
    try:
        from orchestrator.candidate_ingest import (
            bridge_pending_alerts,
            bridge_active_deadlines,
        )
        for fn in (bridge_pending_alerts, bridge_active_deadlines):
            try:
                res = fn(limit=limit)
            except Exception as e:  # one bridge failing must not skip the other
                logger.error("dashboard_v2 producer: %s failed: %s", fn.__name__, e)
                out["ok"] = False
                continue
            if not res.get("ok"):
                out["ok"] = False
            for k in ("bridged", "skipped", "failed", "scanned"):
                out[k] += int(res.get(k, 0) or 0)
    except Exception as e:  # import / unexpected — contained (AC4)
        logger.error("dashboard_v2 producer tick failed: %s", e)
        return {"ok": False, "error": "tick_failed", "detail": str(e)[:200]}
    logger.info(
        "dashboard_v2 producer tick: bridged=%(bridged)s skipped=%(skipped)s "
        "failed=%(failed)s scanned=%(scanned)s", out,
    )
    return out


# --------------------------------------------------------------------------- #
# B. Verifier queue tick (LLM cost — capped + breaker-gated).
# --------------------------------------------------------------------------- #
def run_verifier_queue_tick() -> dict:
    """Drain up to ``verifier_max_per_tick()`` awaiting candidates through the
    existing ``verify_candidate`` (which owns the Opus-class floor + cost breaker;
    no new model selection here).

    Zero-op when the flag is off OR the cap is 0 (AC1/AC3). Stops early on a cost
    hard-stop so it never hammers the breaker. Fault-tolerant per candidate — one
    bad candidate logs + is skipped, never crashes the tick (AC4).
    """
    if not verifier_enabled():
        return {"skipped": True, "reason": "DASHBOARD_V2_VERIFIER_ENABLED off"}
    cap = verifier_max_per_tick()
    if cap <= 0:
        return {"skipped": True, "reason": "DASHBOARD_V2_VERIFIER_MAX_PER_TICK=0"}

    out = {"ok": True, "processed": 0, "promoted": 0, "refused": 0,
           "errored": 0, "parked": 0, "cost_stopped": False, "cap": cap}
    try:
        from orchestrator import candidate_ingest
        from orchestrator import candidate_verifier
        candidates = candidate_ingest.list_candidates(
            status="awaiting_verification", limit=cap)
    except Exception as e:
        logger.error("dashboard_v2 verifier tick: queue read failed: %s", e)
        return {"ok": False, "error": "queue_read_failed", "detail": str(e)[:200]}

    for cand in candidates[:cap]:
        cid = cand.get("id") if isinstance(cand, dict) else None
        if cid is None:
            continue
        try:
            res = candidate_verifier.verify_candidate(cid)
        except Exception as e:  # verify_candidate shouldn't raise, but contain it
            logger.error("dashboard_v2 verifier: candidate %s raised: %s", cid, e)
            out["errored"] += 1
            continue
        out["processed"] += 1
        if res.get("ok"):
            out["promoted"] += 1
        elif res.get("error") == "cost_hard_stop":
            # Breaker tripped — stop this tick, do not keep calling the model.
            out["cost_stopped"] = True
            out["processed"] -= 1  # this one didn't actually run the model to completion
            logger.warning("dashboard_v2 verifier: cost hard-stop — ending tick early")
            break
        elif res.get("error") in ("verification_refused", "bad_json"):
            # G2 F1 (cost-leak): the model WAS called and refused this candidate.
            # Park it out of the awaiting queue so the next tick does NOT re-spend
            # an Opus call on the same noisy row. Fault-tolerant — a failed park
            # logs but never crashes the tick.
            out["refused"] += 1
            try:
                mark = candidate_ingest.mark_candidate_auto_refused(cid)
                if mark.get("ok") and mark.get("parked"):
                    out["parked"] += 1
                else:
                    logger.warning("dashboard_v2 verifier: park failed for %s: %s",
                                   cid, mark)
            except Exception as e:
                logger.error("dashboard_v2 verifier: park raised for %s: %s", cid, e)
        else:
            # Pre-model / transient errors (source_not_found, model_not_allowed,
            # provider_unavailable, internal_error, promote_failed): no Opus cost
            # was spent, so they are left awaiting for a later retry — NOT parked.
            out["errored"] += 1
    logger.info(
        "dashboard_v2 verifier tick: processed=%(processed)s promoted=%(promoted)s "
        "refused=%(refused)s errored=%(errored)s cost_stopped=%(cost_stopped)s",
        out,
    )
    return out


# --------------------------------------------------------------------------- #
# C. Scheduler registration — gated; a disabled worker adds NO job (AC1).
# --------------------------------------------------------------------------- #
def register_dashboard_v2_workers(scheduler) -> list:
    """Register producer A + verifier B on ``scheduler``, each ONLY if its flag is
    on (verifier additionally needs cap > 0). Returns the list of registered job
    ids (empty on a default OFF deploy). Safe to call from ``_register_jobs``.
    """
    from apscheduler.triggers.interval import IntervalTrigger

    registered: list = []

    def _watch(job_id: str, interval: int) -> None:
        # Pair interval jobs with the liveness sentinel like the rest of the
        # scheduler; observability only, so never let it break registration.
        try:
            from triggers.scheduler_liveness_sentinel import register_expected_job
            register_expected_job(job_id, interval)
        except Exception:
            pass

    if bridge_enabled():
        interval = _interval("DASHBOARD_V2_BRIDGE_INTERVAL_SECONDS",
                             _PRODUCER_DEFAULT_INTERVAL)
        scheduler.add_job(
            run_candidate_producer_tick,
            IntervalTrigger(seconds=interval),
            id="dashboard_v2_candidate_producer",
            name="Dashboard V2 candidate producer (alerts/deadlines -> candidates)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=60,
        )
        _watch("dashboard_v2_candidate_producer", interval)
        registered.append("dashboard_v2_candidate_producer")
        logger.info("Registered: dashboard_v2_candidate_producer (every %ss)", interval)
    else:
        logger.info("Skipped: dashboard_v2_candidate_producer (DASHBOARD_V2_BRIDGE_ENABLED off)")

    if verifier_enabled() and verifier_max_per_tick() > 0:
        interval = _interval("DASHBOARD_V2_VERIFIER_INTERVAL_SECONDS",
                             _VERIFIER_DEFAULT_INTERVAL)
        scheduler.add_job(
            run_verifier_queue_tick,
            IntervalTrigger(seconds=interval),
            id="dashboard_v2_verifier_queue",
            name="Dashboard V2 verifier queue (drain awaiting candidates)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=60,
        )
        _watch("dashboard_v2_verifier_queue", interval)
        registered.append("dashboard_v2_verifier_queue")
        logger.info("Registered: dashboard_v2_verifier_queue (every %ss, cap %s)",
                    interval, verifier_max_per_tick())
    else:
        logger.info("Skipped: dashboard_v2_verifier_queue "
                    "(DASHBOARD_V2_VERIFIER_ENABLED off or MAX_PER_TICK=0)")

    return registered
