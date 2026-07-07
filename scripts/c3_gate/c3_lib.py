#!/usr/bin/env python3
"""C3 pilot-widening gate — shared run-harness library (rows R1-R4).

Design (ratified lead #5930):
  * Each matrix row is a repeatable controlled run producing an evidence pointer
    a checker (codex) can verify independently — never "operator says so".
  * A run INJECTS a synthetic signal by direct INSERT into ``email_messages``
    (source=graph, ``message_id`` prefixed ``c3-gate-``) then drives the real
    Box-5 spine (``airport_ticketing_bridge.run_tick`` + the boarding/lounge
    flow functions) and reads back the persisted evidence.
  * Two modes per runner:
      --dry (default)  describe the run + the exact injections/calls + the
                       evidence it WOULD emit. Touches no DB, imports nothing
                       heavy — safe to run anywhere, including with no DB env.
      --run            execute against the DB in the environment. GUARDED:
                       refuses unless C3_HARNESS_LIVE=1 is set.
  * Target DB (Q2, lead #5930):
      (i)  development/validation -> ephemeral Neon branch via TEST_DATABASE_URL
           (the existing CI pattern).
      (ii) T2 EVIDENCE runs -> live DB, synthetic rows MARKED (c3-gate- prefix),
           cleanup executed + logged. Live evidence runs stay gated on lead's go.
  * External I/O (ClickUp + bus) is STUBBED by default so a run is deterministic
    and side-effect-free; set C3_HARNESS_REAL_IO=1 only for a true-live T2 run
    under lead's ClickUp policy.

This module owns: DB connection, table bootstrap, synthetic injection, registry
seeding, I/O stubs, evidence collectors, the run-log writer, and cleanup. The
per-row runners (r1..r4) compose these.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# F3 (codex #6158): allow "python3 scripts/c3_gate/rN_*.py" from the repo root
# without an editable install. Running a runner puts scripts/c3_gate on sys.path[0]
# (so `import c3_lib` resolves) but NOT the repo root — the lazy heavy imports below
# (memory.store_back, orchestrator.*, kbl.*) need it, so a real `--run` from the repo
# root failed ModuleNotFoundError before the intended DB fail-loud. Mirror
# scripts/regen_hot_md.py:67-70. Runs before any heavy import (all are lazy).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Synthetic-signal marker: every row this harness creates is prefixed so live-DB
# evidence runs can be cleaned up deterministically and never collide with real
# pilot traffic.
PREFIX = "c3-gate-"
RUNS_DIR = Path(__file__).resolve().parent / "_runs"

# HIGH-2 live-path sandbox (codex #5956). When set (live-target runs only) it pins
# BOTH the email watermark AND the received_date of every injected row to a single
# run-start instant, so the real spine sweeps ONLY this harness's freshly-injected
# c3-gate- rows and never a real un-ticketed arrival. None on the ephemeral Neon
# test branch -> injected rows keep the historical now()-1h default + blank cursor.
_SANDBOX_SINCE: Optional[datetime] = None

# MED-1 (codex #5956). Every project code this harness registers is tracked so
# cleanup can delete exactly what it created — and ONLY on the test branch. The
# real BB-AUK-001 registry row on live is NEVER touched.
_REGISTERED_CODES: set[str] = set()

# HIGH-1 (codex #5984). Sentinel boarding desk. On live-target runs the boarding
# `_DESK` filter is repointed here so run_receipt_writer / run_boarding_ttl_nudge
# production scans (WHERE desk_owner = _DESK) match ONLY this harness's seeded
# rows, never a real baden-baden-desk journey row. R3/R4 seed with `flow._DESK`
# so seed and scan agree on both branches (real desk on test, sentinel on live).
_SANDBOX_BOARDING_DESK = f"{PREFIX}desk"


def now() -> datetime:
    return datetime.now(timezone.utc)


def _default_received() -> datetime:
    """received_date for an injected row. On a sandboxed live run this is the
    pinned run-start instant (so the row lands at/after the sandbox cursor); on the
    test branch it is the historical now()-1h default."""
    return _SANDBOX_SINCE if _SANDBOX_SINCE is not None else (now() - timedelta(hours=1))


def _email_watermark_source() -> str:
    """The trigger_watermarks source key the email lane advances. Read from the
    bridge so the harness never drifts from the real cursor key."""
    from orchestrator import airport_ticketing_bridge as bridge

    return bridge._WATERMARK_SOURCE


def bind_global_store() -> None:
    """HIGH-1 (codex #5956) — unify the DB contract. ``run_tick`` and
    ``triggers.state.trigger_state`` both read/write through
    ``SentinelStoreBack._get_global_instance()``, whose pool is configured from
    ``POSTGRES_*`` env — which can point at a DIFFERENT database than the harness
    admin conn (``TEST_DATABASE_URL``/``DATABASE_URL`` via ``db_url()``). Left
    unbound, run_tick would write one DB while the harness injects/reads another.

    Repoint the global singleton at a store bound to ``db_url()`` (mirrors the
    ``tier_b_test_store`` fixture in tests/conftest.py) so the whole run — injection,
    spine tick, watermark, evidence read — is one explicit DSN. Idempotent."""
    from memory.store_back import SentinelStoreBack

    store = _HarnessStore(db_url())
    SentinelStoreBack._get_global_instance = classmethod(lambda cls: store)  # type: ignore[assignment]
    # TierBRuntime caches the store on first use; drop the cache so it re-reads the
    # patched singleton (mirrors the fixture's TierBRuntime._instance reset).
    try:
        from orchestrator import tier_b_runtime as tbr

        tbr.TierBRuntime._instance = None
    except Exception:
        pass

    # HIGH-3 (codex #5984): the project registry code/participant/thread lanes that
    # run_tick uses resolve via kbl.db.get_conn (project_registry_store does
    # `from kbl.db import get_conn`). kbl/db.py IGNORES TEST_DATABASE_URL — so
    # without this, on the test branch the harness seeds the registry in db_url()
    # while the resolver reads a DIFFERENT DB and never sees the seed. Route BOTH
    # the module and the already-bound name at db_url(). On live db_url() ==
    # DATABASE_URL, so this is a semantic no-op there.
    import contextlib

    import kbl.db as _kbl_db
    import kbl.project_registry_store as _reg_mod

    @contextlib.contextmanager
    def _harness_get_conn():
        import psycopg2

        conn = psycopg2.connect(db_url())
        try:
            yield conn
        finally:
            conn.close()

    _kbl_db.get_conn = _harness_get_conn  # type: ignore[assignment]
    _reg_mod.get_conn = _harness_get_conn  # type: ignore[assignment]


class _HarnessStore:
    """Minimal SentinelStoreBack shim bound to the harness DSN. Mirrors the
    ``_TestStore`` shim in tests/conftest.py: a fresh psycopg2 connection per
    ``_get_conn`` so run_tick's SERIALIZABLE isolation never leaks into helpers."""

    def __init__(self, dsn: str):
        import psycopg2

        self._dsn = dsn
        self._psycopg2 = psycopg2

    def _get_conn(self):
        return self._psycopg2.connect(self._dsn)

    def _put_conn(self, conn) -> None:
        if conn is None:
            return
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Environment / guards
# --------------------------------------------------------------------------- #
def db_url() -> str:
    """Resolve the harness DB URL. TEST_DATABASE_URL wins (dev/CI validation on
    the ephemeral Neon branch); DATABASE_URL is the live/T2 target. Fail loud if
    neither is set — a --run without a DB is an error, not a silent no-op."""
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit(
            "C3 harness --run needs TEST_DATABASE_URL (dev/CI) or DATABASE_URL "
            "(live/T2). Neither is set. Refusing to run."
        )
    return url


def is_live_target() -> bool:
    """True when running against the live DB (DATABASE_URL, not the Neon test
    branch). Used to label evidence + enforce the marked-rows discipline."""
    return not os.environ.get("TEST_DATABASE_URL") and bool(os.environ.get("DATABASE_URL"))


def require_run_guard() -> None:
    """A --run must carry C3_HARNESS_LIVE=1. Blocks an accidental execution that
    would write rows into whatever DB the shell happens to point at."""
    if os.environ.get("C3_HARNESS_LIVE") != "1":
        raise SystemExit(
            "C3 harness --run is guarded. Set C3_HARNESS_LIVE=1 to execute. "
            "(Live-DB T2 evidence runs additionally require lead's go per #5930.)"
        )


def real_io() -> bool:
    return os.environ.get("C3_HARNESS_REAL_IO") == "1"


# --------------------------------------------------------------------------- #
# DB connection + bootstrap
# --------------------------------------------------------------------------- #
def admin_conn():
    """Autocommit admin connection for setup/reads. Autocommit so admin reads
    never sit idle-in-transaction holding ACCESS SHARE on airport_tickets while
    run_tick wants ACCESS EXCLUSIVE for its ensure (mirrors the test fixture)."""
    import psycopg2

    conn = psycopg2.connect(db_url())
    conn.autocommit = True
    return conn


def bootstrap_tables(conn) -> None:
    """Idempotently ensure the source + spine tables exist. Uses the real
    ensure_* bootstrap functions so the harness never drifts from production DDL
    (Lesson #50)."""
    from orchestrator import airport_ticketing_bridge as bridge
    from orchestrator.airport_outbound_connector import (
        ensure_airport_outbound_events_table,
    )
    from kbl import project_registry_store as reg

    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS email_messages (
                message_id TEXT PRIMARY KEY, thread_id TEXT, sender_name TEXT,
                sender_email TEXT, subject TEXT, full_body TEXT,
                received_date TIMESTAMPTZ, source TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trigger_watermarks (
                source TEXT PRIMARY KEY, last_seen TIMESTAMPTZ,
                updated_at TIMESTAMPTZ, cursor_data TEXT
            )
            """
        )
    bridge.ensure_airport_ticket_table(conn)
    ensure_airport_outbound_events_table(conn)
    reg.ensure_project_registry_table(conn)


# --------------------------------------------------------------------------- #
# Synthetic injection + registry seeding
# --------------------------------------------------------------------------- #
def inject_email(conn, suffix: str, *, sender_email: str, subject: str,
                 body: str, thread_suffix: Optional[str] = None,
                 received: Optional[datetime] = None) -> str:
    """INSERT one synthetic inbound email. message_id = PREFIX+suffix so it is a
    marked, cleanup-able row. Returns the message_id."""
    message_id = f"{PREFIX}{suffix}"
    thread_id = f"{PREFIX}{thread_suffix}" if thread_suffix else message_id
    received = received or _default_received()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO email_messages
                (message_id, thread_id, sender_name, sender_email, subject,
                 full_body, received_date, source)
            VALUES (%s, %s, 'C3 Gate Sender', %s, %s, %s, %s, 'graph')
            ON CONFLICT (message_id) DO NOTHING
            """,
            (message_id, thread_id, sender_email, subject, body, received),
        )
    conn.commit()
    return message_id


def register_code(conn, project_number: str, *, matter_slug: str,
                  desk_owner: str = "baden-baden-desk",
                  participants: Optional[list] = None) -> Any:
    """Register an ACTIVE project code so the hard/code-routed lanes can resolve
    it. On the live DB the real registry row already exists — this is used on the
    ephemeral Neon branch where the registry is seeded per-run."""
    from kbl import project_registry_store as reg

    result = reg.register_project(
        conn, project_number=project_number, desk_owner=desk_owner,
        matter_slug=matter_slug, participants=participants or [],
    )
    # MED-1: remember what we registered so cleanup can remove exactly this row
    # (test branch only — never the real live registry row).
    _REGISTERED_CODES.add(project_number)
    return result


# --------------------------------------------------------------------------- #
# External-I/O stubs (deterministic, side-effect-free by default)
# --------------------------------------------------------------------------- #
def stub_external_io() -> None:
    """Neutralize the network side effects of the spine so a run is deterministic
    and writes nothing to ClickUp or the real bus. Only active unless
    C3_HARNESS_REAL_IO=1. Patches are module-attribute swaps (no pytest needed)."""
    if real_io():
        return
    from orchestrator import airport_ticketing_bridge as bridge
    bridge.post_ticket_to_bus = (  # type: ignore[attr-defined]
        lambda ticket: {"ok": True, "message_id": 0, "thread_id": "c3-stub"}
    )
    try:
        from orchestrator import airport_boarding_flow as flow

        flow._get_clickup_client = lambda: object()  # type: ignore[attr-defined]
        flow._mirror_clickup_status = (  # type: ignore[attr-defined]
            lambda *a, **k: {"ok": True}
        )
        flow._post_bus = (  # type: ignore[attr-defined]
            lambda *a, **k: {"ok": True, "message_id": 0}
        )
    except Exception:
        # boarding flow only needed for R3/R4; R1/R2 do not import it.
        pass


# --------------------------------------------------------------------------- #
# Evidence collectors
# --------------------------------------------------------------------------- #
def ticket_evidence(conn, source_id: str) -> Optional[dict]:
    """Routing evidence for one airport_tickets row (R1/R2)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, ticket_id, dedup_key, terminal_status, terminal_reason, "
            "       confidence, proposed_desk_slug, matter_slug, status "
            "FROM airport_tickets WHERE raw_source_id = %s LIMIT 1",
            (source_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    keys = ("id", "ticket_id", "dedup_key", "terminal_status", "terminal_reason",
            "confidence", "proposed_desk_slug", "matter_slug", "status")
    return dict(zip(keys, row))


def ticket_count_for_thread(conn, thread_id: str) -> int:
    """How many airport_tickets rows exist for a source thread (R2 dedup)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM airport_tickets WHERE source_id IN "
            "(SELECT message_id FROM email_messages WHERE thread_id = %s)",
            (thread_id,),
        )
        return int(cur.fetchone()[0])


def outbound_evidence(conn, ev_ticket_id: str) -> Optional[dict]:
    """Receipt/journey evidence for one airport_outbound_events row (R3/R4)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, ticket_id, event_state, correlation, clickup_task_id "
            "FROM airport_outbound_events WHERE ticket_id = %s LIMIT 1",
            (ev_ticket_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"id": row[0], "ticket_id": row[1], "event_state": row[2],
            "correlation": row[3], "clickup_task_id": row[4]}


def nudge_actions(conn, ev_ticket_id: str) -> list:
    """baker_actions audit rows for the nudge/escalation ladder of one journey
    (R4). Returns [(action_type, created_at)] ordered."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT action_type, created_at FROM baker_actions "
            "WHERE action_type IN ('airport_boarding.nudged','airport_boarding.escalated') "
            "  AND payload::text LIKE %s "
            "ORDER BY created_at ASC",
            (f"%{ev_ticket_id}%",),
        )
        return [(r[0], r[1].isoformat() if r[1] else None) for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# Run log + cleanup
# --------------------------------------------------------------------------- #
def write_run_log(row: str, record: dict) -> Path:
    """Append one JSON record to scripts/c3_gate/_runs/<row>-<date>.jsonl.
    The log IS the evidence artifact the ship report / codex references."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    path = RUNS_DIR / f"{row}-{now().strftime('%Y%m%d')}.jsonl"
    record = {"row": row, "logged_at": stamp,
              "target": "live" if is_live_target() else "test-branch", **record}
    with path.open("a") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
    return path


def snapshot_watermark(conn, source: str) -> Optional[tuple]:
    """HIGH-2: read the current trigger_watermarks row for ``source`` so the live
    cursor can be restored byte-for-byte after the run. None when no row exists."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_seen, updated_at, cursor_data FROM trigger_watermarks "
            "WHERE source = %s",
            (source,),
        )
        return cur.fetchone()


def set_watermark(conn, source: str, ts: datetime) -> None:
    """HIGH-2: pin the email cursor to ``ts`` so the tick sweeps only rows at/after
    it (the harness's freshly-injected c3-gate- rows), never a real past arrival."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trigger_watermarks (source, last_seen, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (source) DO UPDATE
              SET last_seen = EXCLUDED.last_seen, updated_at = EXCLUDED.updated_at
            """,
            (source, ts, ts),
        )
    conn.commit()


def restore_watermark(conn, source: str, snap: Optional[tuple]) -> None:
    """HIGH-2: put the real cursor back exactly as ``snapshot_watermark`` found it —
    reinstate the prior row, or DELETE if there was none (never-activated cursor)."""
    with conn.cursor() as cur:
        if snap is None:
            cur.execute("DELETE FROM trigger_watermarks WHERE source = %s", (source,))
        else:
            cur.execute(
                """
                INSERT INTO trigger_watermarks (source, last_seen, updated_at, cursor_data)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source) DO UPDATE
                  SET last_seen = EXCLUDED.last_seen,
                      updated_at = EXCLUDED.updated_at,
                      cursor_data = EXCLUDED.cursor_data
                """,
                (source, snap[0], snap[1], snap[2]),
            )
    conn.commit()


def sandbox_boarding_desk():
    """HIGH-2/HIGH-1: repoint the boarding-flow desk filter to the sentinel so the
    receipt-writer + ttl-nudge production scans (desk_owner = _DESK) see ONLY this
    harness's seeded rows. Returns the original _DESK so `finally` can restore it."""
    from orchestrator import airport_boarding_flow as flow

    orig = flow._DESK
    flow._DESK = _SANDBOX_BOARDING_DESK
    return orig


def restore_boarding_desk(orig) -> None:
    from orchestrator import airport_boarding_flow as flow

    flow._DESK = orig


def sandbox_email_fetch():
    """Round-3 residual (codex #6002) + round-5 F1 (codex #6158): scope the harness's
    OWN live email tick to its own rows.

    Two independent leaks are in play:
      (1) harness tick -> REAL arrivals. The watermark pin (`_SANDBOX_SINCE`) scopes
          only the SINCE cursor; a REAL matching email arriving mid-run (at/after
          `_SANDBOX_SINCE`) would be swept, ticketed under the stubbed bus, and
          COMMIT a real `airport_tickets` row that fake-sends. This wrapper drops
          every non-`c3-gate-` row before `run_tick` can ticket it.
      (2) production/Render tick -> harness rows. Fixed PROD-side, NOT here:
          `bridge.fetch_email_arrivals` now excludes `c3-gate-` rows by default
          (`include_synthetic=False`), so a concurrent Render tick can never fetch
          them regardless of this process's monkeypatch (F1 defense-in-depth).

    Because production now excludes synthetic rows by default, the harness's own tick
    must OPT BACK IN (`include_synthetic=True`) to even see its injected rows, then
    keep ONLY them. `run_tick` calls the module-level name, so patching
    `bridge.fetch_email_arrivals` intercepts it. Returns the original fn so `finally`
    can restore. Mirrors `sandbox_boarding_desk()`; live-target only (caller-gated)."""
    from orchestrator import airport_ticketing_bridge as bridge

    orig = bridge.fetch_email_arrivals

    def _scoped(*args, **kwargs):
        # Opt into synthetic rows (prod default excludes them, F1) then keep ONLY the
        # harness's own c3-gate- rows — dropping any real concurrent arrival.
        kwargs.setdefault("include_synthetic", True)
        return [
            a for a in orig(*args, **kwargs)
            if str(getattr(a, "message_id", "") or "").startswith(PREFIX)
        ]

    bridge.fetch_email_arrivals = _scoped  # type: ignore[assignment]
    return orig


def restore_email_fetch(orig) -> None:
    from orchestrator import airport_ticketing_bridge as bridge

    bridge.fetch_email_arrivals = orig


def cleanup(conn) -> dict:
    """Delete every marked synthetic row this harness could have created. Safe on
    live (only touches c3-gate- / airport-lounge:c3-gate- rows). Logged + returned
    so a live T2 run can prove it cleaned up after itself."""
    counts = {}
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM airport_outbound_events WHERE ticket_id LIKE %s OR message_id LIKE %s",
            (f"airport-lounge:{PREFIX}%", f"{PREFIX}%"),
        )
        counts["airport_outbound_events"] = cur.rowcount
        cur.execute("DELETE FROM airport_tickets WHERE source_id LIKE %s OR raw_source_id LIKE %s",
                    (f"{PREFIX}%", f"{PREFIX}%"))
        counts["airport_tickets"] = cur.rowcount
        cur.execute("DELETE FROM email_messages WHERE message_id LIKE %s", (f"{PREFIX}%",))
        counts["email_messages"] = cur.rowcount
        # HIGH-2 (codex #5984): live baker_actions has `payload` JSONB, no `details`.
        cur.execute("DELETE FROM baker_actions WHERE payload::text LIKE %s", (f"%{PREFIX}%",))
        counts["baker_actions"] = cur.rowcount
        # MED-1: remove the project_registry rows THIS harness seeded — TEST BRANCH
        # ONLY. On live the pilot code (BB-AUK-001) is the real registry row; never
        # delete it. _REGISTERED_CODES is empty on a fresh process, so the run-start
        # cleanup is a no-op and only the post-run cleanup removes seeded codes.
        if not is_live_target() and _REGISTERED_CODES:
            cur.execute(
                "DELETE FROM project_registry WHERE project_number = ANY(%s)",
                (list(_REGISTERED_CODES),),
            )
            counts["project_registry"] = cur.rowcount
    conn.commit()
    return counts


# --------------------------------------------------------------------------- #
# Runner scaffold shared by r1..r4
# --------------------------------------------------------------------------- #
# F2 (codex #6158): distinct "never mutated" sentinel for per-resource restore in
# main_scaffold's finally — lets it tell an un-sandboxed resource apart from one
# whose captured restore-token legitimately is None/falsy.
_UNSET: Any = object()


def main_scaffold(row: str, dry_description: str, run_fn: Callable[[Any], dict]) -> None:
    """Common argparse + dispatch for a per-row runner.

    run_fn(conn) -> {"pass": bool, "evidence": {...}, "notes": str}
    """
    import argparse

    ap = argparse.ArgumentParser(description=f"C3 gate runner — {row}")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry", action="store_true", default=True,
                      help="describe the run + expected evidence, touch no DB (default)")
    mode.add_argument("--run", action="store_true",
                      help="execute against the env DB (needs C3_HARNESS_LIVE=1)")
    ap.add_argument("--keep", action="store_true",
                    help="skip post-run cleanup of the synthetic rows")
    args = ap.parse_args()

    if not args.run:
        print(f"=== C3 GATE {row} — DRY (no DB touched) ===\n")
        print(dry_description.strip() + "\n")
        print("Run for real with:  C3_HARNESS_LIVE=1 python3 "
              f"scripts/c3_gate/{Path(sys.argv[0]).name} --run")
        return

    require_run_guard()
    # HIGH-1: unify the DB contract BEFORE any spine call so run_tick +
    # trigger_state read/write the SAME DB the harness injects into.
    bind_global_store()
    conn = admin_conn()

    # HIGH-2: on a live-target run, sandbox the shared email cursor. Snapshot the
    # real watermark, then pin it to run-start; every injected row lands AT that
    # instant (via _SANDBOX_SINCE) so the tick sweeps ONLY this harness's rows and
    # never a real un-ticketed arrival. The real cursor is restored in `finally`.
    global _SANDBOX_SINCE
    wm_source = _email_watermark_source()
    # F2 (codex #6158): per-resource restore markers. Each records whether ITS
    # resource was (or may have been) mutated, so the `finally` can restore exactly
    # what changed, independent of whether the LATER mutations succeeded. The prior
    # single `sandboxed` flag flipped only after all three mutations, so a failure
    # between set_watermark and the last monkeypatch left the real cursor pinned.
    wm_snapshot: Optional[tuple] = None
    wm_pinned = False
    boarding_desk_orig: Any = _UNSET
    email_fetch_orig: Any = _UNSET
    try:
        bootstrap_tables(conn)
        stub_external_io()
        if is_live_target():
            # Snapshot BEFORE pinning; mark each resource the instant it is (or is
            # about to be) mutated. wm_pinned is set pessimistically BEFORE
            # set_watermark so an ambiguous partial commit still triggers restore
            # (restore_watermark reinstates the snapshot idempotently either way).
            wm_snapshot = snapshot_watermark(conn, wm_source)
            _SANDBOX_SINCE = now()
            wm_pinned = True
            set_watermark(conn, wm_source, _SANDBOX_SINCE)
            # HIGH-1: scope the R3/R4 boarding-flow production scans to harness rows.
            boarding_desk_orig = sandbox_boarding_desk()
            # Round-3 residual (codex #6002): scope the email lane to harness rows so a
            # real concurrent arrival mid-run can never be ticketed under the stub.
            email_fetch_orig = sandbox_email_fetch()
        result = run_fn(conn)
        log_path = write_run_log(row, {"pass": result["pass"],
                                       "evidence": result.get("evidence"),
                                       "notes": result.get("notes", "")})
        verdict = "PASS" if result["pass"] else "FAIL"
        print(f"=== C3 GATE {row} — {verdict} ===")
        print(json.dumps(result.get("evidence"), indent=2, default=str))
        print(f"run-log: {log_path}")
        if result.get("notes"):
            print(f"notes: {result['notes']}")
    finally:
        # F2 (codex #6158): restore EACH sandboxed resource independently of the
        # others. In-memory monkeypatches unwind FIRST (attribute swaps that can't
        # fail on DB I/O), then the watermark DB restore LAST — so a DB error there
        # can never strand the module globals patched.
        if email_fetch_orig is not _UNSET:
            restore_email_fetch(email_fetch_orig)
        if boarding_desk_orig is not _UNSET:
            restore_boarding_desk(boarding_desk_orig)
        if wm_pinned:
            restore_watermark(conn, wm_source, wm_snapshot)
            print(f"watermark restored: {wm_source}")
        if not args.keep:
            removed = cleanup(conn)
            print(f"cleanup: {removed}")
        _SANDBOX_SINCE = None
        conn.close()
