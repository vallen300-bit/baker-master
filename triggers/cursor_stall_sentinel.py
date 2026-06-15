"""LONG_RUNNING_JOB_OWNERSHIP_1: cursor-stall sentinel.

Mirrors triggers/scheduler_liveness_sentinel.py, but keyed on a progress CURSOR
instead of a fire-timestamp. A job can be alive and health-green yet make zero
forward progress; this sentinel alarms on `cursor delta == 0 AND state ==
RUNNING` past a per-job threshold (the alarm that was missing during the 4-day
silent graph-backfill stall — Lesson #100).

Reads the ownership register (config/long_running_jobs.yml). For each entry it
resolves the current cursor + updated_at + RUNNING-ness from the declared
cursor_source (progress_table over email_backfill_progress, or job_heartbeats),
and posts a bus alert to the job's accountable owner + lead when stalled.

DB writes are split across two tables on purpose (deputy-codex S2 #3035):
  - job_heartbeats        — written by jobs + this sentinel's own self-beat
  - sentinel_cursor_seen  — this sentinel's observation + ATOMIC alert-window
                            claim (so a heartbeat UPSERT can't mask staleness,
                            and concurrent runs post exactly once).
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger("sentinel.cursor_stall")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_REGISTER = _REPO_ROOT / "config" / "long_running_jobs.yml"
_BUS_POST_SCRIPT = _REPO_ROOT / "scripts" / "bus_post.sh"

DEFAULT_STALL_THRESHOLD_HOURS = 6

# Cold-start grace: skip ALL checks while module-load is younger than this.
# Process-local (NOT DB-based), mirroring scheduler_liveness_sentinel so an
# in-process restart re-applies the window via reset_cold_start_anchor().
COLD_START_GRACE_SECONDS = 900  # 15 min

# Process-local cold-start anchor — captured at import (≈ process start since the
# sentinel module is imported during scheduler startup).
_MODULE_LOAD_TIME = datetime.now(timezone.utc)

# Identifier whitelist for cursor_source table/column names (these come from our
# own validated config, but never interpolate un-checked identifiers into SQL).
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def reset_cold_start_anchor() -> None:
    """Re-stamp the cold-start anchor to NOW. Called from start_scheduler() so an
    in-process scheduler restart re-applies COLD_START_GRACE_SECONDS, matching a
    fresh Render restart (mirrors scheduler_liveness_sentinel)."""
    global _MODULE_LOAD_TIME
    _MODULE_LOAD_TIME = datetime.now(timezone.utc)


def _ident(name: str) -> str:
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


def load_register(path=None) -> list[dict]:
    """Load the ownership register's job list."""
    p = Path(path) if path else _DEFAULT_REGISTER
    with open(p, "r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    return list(doc.get("jobs", []))


# ---------------------------------------------------------------------------
# Data-access object — wraps SentinelStoreBack. Each method takes its own pooled
# connection and commits independently so the atomic alert-window claim is a
# self-contained committed transaction (cross-process dedupe).
# ---------------------------------------------------------------------------
class _StoreBackDAO:
    def __init__(self):
        from memory.store_back import SentinelStoreBack
        self._store = SentinelStoreBack._get_global_instance()

    def _run(self, fn, default=None):
        conn = None
        try:
            conn = self._store._get_conn()
            if not conn:
                return default
            result = fn(conn)
            conn.commit()
            return result
        except Exception as e:
            logger.warning("cursor_stall DAO op failed: %s", e)
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            return default
        finally:
            if conn is not None:
                try:
                    self._store._put_conn(conn)
                except Exception:
                    pass

    def read_progress(self, table, cursor_col, updated_col, key_col, key_val,
                      total_col):
        t, cc, uc, kc, tc = (_ident(table), _ident(cursor_col),
                             _ident(updated_col), _ident(key_col),
                             _ident(total_col))

        def _q(conn):
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '15s'")
                cur.execute(
                    f"SELECT {cc}, {uc}, {tc} FROM {t} WHERE {kc} = %s LIMIT 1",
                    (key_val,),
                )
                return cur.fetchone()

        return self._run(_q)

    def read_heartbeat(self, job_id):
        def _q(conn):
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '15s'")
                cur.execute(
                    "SELECT cursor_text, state, updated_at FROM job_heartbeats "
                    "WHERE job_id = %s LIMIT 1",
                    (job_id,),
                )
                return cur.fetchone()

        return self._run(_q)

    def get_prior_observation(self, job_id):
        def _q(conn):
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '15s'")
                cur.execute(
                    "SELECT observed_cursor, observed_at FROM sentinel_cursor_seen "
                    "WHERE job_id = %s LIMIT 1",
                    (job_id,),
                )
                return cur.fetchone()

        return self._run(_q)

    def record_observation(self, job_id, cursor, observed_at):
        def _q(conn):
            with conn.cursor() as cur:
                # Touch ONLY observation columns — never last_alert_window_start.
                cur.execute(
                    """
                    INSERT INTO sentinel_cursor_seen (job_id, observed_cursor, observed_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (job_id) DO UPDATE SET
                        observed_cursor = EXCLUDED.observed_cursor,
                        observed_at     = EXCLUDED.observed_at
                    """,
                    (job_id, None if cursor is None else str(cursor), observed_at),
                )
            return True

        return self._run(_q, default=False)

    def claim_alert_window(self, job_id, cursor, observed_at, window) -> bool:
        """Atomically claim the alert window. Returns True iff this caller won
        the claim (a row was inserted/updated). Concurrent runs with the same
        window: exactly one wins (row-level lock on ON CONFLICT serializes)."""
        def _q(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sentinel_cursor_seen
                        (job_id, observed_cursor, observed_at, last_alert_window_start)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (job_id) DO UPDATE SET
                        last_alert_window_start = EXCLUDED.last_alert_window_start,
                        observed_cursor = EXCLUDED.observed_cursor,
                        observed_at = EXCLUDED.observed_at
                    WHERE sentinel_cursor_seen.last_alert_window_start
                          IS DISTINCT FROM EXCLUDED.last_alert_window_start
                    RETURNING job_id
                    """,
                    (job_id, None if cursor is None else str(cursor),
                     observed_at, window),
                )
                return cur.fetchone() is not None

        return self._run(_q, default=False)

    def beat_self(self, job_id, ts):
        try:
            from orchestrator import job_heartbeat
            job_heartbeat.beat(job_id, str(ts), "RUNNING")
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("cursor_stall self-beat failed: %s", e)


def _default_bus_post(recipient: str, body: str, topic: str) -> None:
    """Post an alert to the Brisen Lab bus via scripts/bus_post.sh.

    Sender identity comes from the runtime's BAKER_ROLE + terminal key env (the
    bus_post.sh credential precedence: literal env -> cache -> 1Password). Failure
    is logged, never raised — a monitoring failure must not crash the scheduler.
    """
    try:
        subprocess.run(
            [str(_BUS_POST_SCRIPT), recipient, body, topic],
            check=True, capture_output=True, text=True, timeout=40,
            cwd=str(_REPO_ROOT),
        )
    except Exception as e:
        detail = getattr(e, "stderr", "") or ""
        logger.warning("cursor_stall bus-post to %s failed: %s %s",
                       recipient, e, detail)


def _resolve(entry: dict, dao) -> tuple | None:
    """Resolve (cursor_text, updated_at, running, done) for one register entry,
    or None if the source has no row yet."""
    cs = entry.get("cursor_source") or {}
    kind = cs.get("kind")

    if kind == "heartbeat":
        row = dao.read_heartbeat(cs.get("job_id") or entry["job_id"])
        if not row:
            return None
        cursor_text, state, updated_at = row
        running = state == "RUNNING"
        done = state == "DONE"
        return (cursor_text, updated_at, running, done)

    if kind == "progress_table":
        row = dao.read_progress(
            cs["table"], cs["cursor_col"], cs["updated_col"],
            cs["key_col"], cs["key_val"], cs["total_col"],
        )
        if not row:
            return None
        cursor_val, updated_at, total = row

        # Completion source of truth = the job's own heartbeat state, when it
        # has one (codex G3 S2). cursor>=total is unreliable: graph
        # total_estimate can be NULL (folder-total read fail) and bluewin
        # done_count is an inserted-delta (< processed count), so a cleanly
        # finished backfill can look incomplete and false-alarm. Both backfills
        # write state=DONE/FAILED on completion (AC5), so honor that first.
        hb = dao.read_heartbeat(entry.get("job_id"))
        if hb is not None:
            _hb_cursor, hb_state, _hb_updated = hb
            if hb_state in ("DONE", "FAILED", "PAUSED"):
                # not actively running -> never alarm; done iff DONE
                return (str(cursor_val), updated_at, False, hb_state == "DONE")
            # hb_state == RUNNING: actively running -> stall-check the progress
            # cursor's updated_at below (running=True, done=False).
            return (str(cursor_val), updated_at, True, False)

        # Fallback (no heartbeat row yet): cursor>=total only when total known.
        done = (total is not None and cursor_val is not None
                and cursor_val >= total)
        running = not done
        return (str(cursor_val), updated_at, running, done)

    logger.warning("unknown cursor_source.kind for %s: %r",
                   entry.get("job_id"), kind)
    return None


def check_cursor_stalls(register=None, dao=None, now=None,
                        bus_post_fn=None) -> dict:
    """Scan the ownership register for stalled jobs and alert on flat-line cursors.

    ALARM when (per AC3): RUNNING AND now - updated_at > stall_threshold_hours
    AND the cursor has not advanced since the previous sentinel observation. The
    alert-window claim is DB-atomic so concurrent runs post exactly once.

    Returns a summary dict. All params optional so the scheduler can call it bare.
    """
    now = now or datetime.now(timezone.utc)
    summary: dict = {
        "checked": 0,
        "running": 0,
        "alarmed": [],
        "posted": [],
        "skipped_cold_start": False,
    }

    # ---- cold-start grace (process-local) -------------------------------
    if (now - _MODULE_LOAD_TIME).total_seconds() < COLD_START_GRACE_SECONDS:
        summary["skipped_cold_start"] = True
        summary["skipped_reason"] = "within cold-start grace"
        return summary

    if register is None:
        try:
            register = load_register()
        except Exception as e:
            summary["skipped_reason"] = f"register load failed: {e}"
            return summary

    owns_dao = dao is None
    if owns_dao:
        try:
            dao = _StoreBackDAO()
        except Exception as e:
            summary["skipped_reason"] = f"DAO init failed: {e}"
            return summary

    bus_post_fn = bus_post_fn or _default_bus_post

    try:
        for entry in register:
            job_id = entry.get("job_id")
            try:
                resolved = _resolve(entry, dao)
            except Exception as e:
                logger.warning("resolve failed for %s: %s", job_id, e)
                continue
            summary["checked"] += 1
            if resolved is None:
                continue

            cursor, updated_at, running, done = resolved
            if done or not running:
                dao.record_observation(job_id, cursor, now)
                continue

            summary["running"] += 1
            threshold = entry.get("stall_threshold_hours",
                                  DEFAULT_STALL_THRESHOLD_HOURS)

            stale = (updated_at is not None
                     and (now - updated_at).total_seconds() > threshold * 3600)
            prior = dao.get_prior_observation(job_id)
            # not advanced: either we have no prior baseline (can't prove
            # advancement on an already-stale job) or the cursor is unchanged.
            not_advanced = (prior is None) or (prior[0] == str(cursor))

            if stale and not_advanced:
                summary["alarmed"].append(job_id)
                window = updated_at  # stable per stall episode -> dedupe key
                if dao.claim_alert_window(job_id, cursor, now, window):
                    hours = (now - updated_at).total_seconds() / 3600.0
                    accountable = entry.get("accountable", "lead")
                    responsible = entry.get("responsible", "?")
                    cs = entry.get("cursor_source") or {}
                    partition = cs.get("key_val") or cs.get("kind") or "?"
                    body = (
                        f"JOB STALLED: '{job_id}' cursor={cursor} has not "
                        f"advanced for {hours:.1f}h (threshold {threshold}h). "
                        f"last progress at {updated_at}. partition={partition}. "
                        f"owner: responsible={responsible} accountable={accountable}. "
                        f"Investigate or mark DONE/FAILED."
                    )
                    topic = f"alert/job-stalled/{job_id}"
                    # post to accountable AND lead (deduped if identical)
                    targets = list(dict.fromkeys([accountable, "lead"]))
                    for t in targets:
                        bus_post_fn(t, body, topic)
                    summary["posted"].append(job_id)
            else:
                dao.record_observation(job_id, cursor, now)

        # self-heartbeat (meta-watchdog: scheduler_liveness watches this job;
        # this beat also makes the sentinel visible in job_heartbeats).
        try:
            dao.beat_self("cursor_stall_sentinel", now.isoformat())
        except Exception as e:
            logger.warning("self-beat failed: %s", e)
    finally:
        if owns_dao:
            close = getattr(dao, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    return summary
