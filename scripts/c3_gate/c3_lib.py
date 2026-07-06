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

# Synthetic-signal marker: every row this harness creates is prefixed so live-DB
# evidence runs can be cleaned up deterministically and never collide with real
# pilot traffic.
PREFIX = "c3-gate-"
RUNS_DIR = Path(__file__).resolve().parent / "_runs"


def now() -> datetime:
    return datetime.now(timezone.utc)


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
    received = received or (now() - timedelta(hours=1))
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

    return reg.register_project(
        conn, project_number=project_number, desk_owner=desk_owner,
        matter_slug=matter_slug, participants=participants or [],
    )


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
            "  AND details::text LIKE %s "
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
        cur.execute("DELETE FROM baker_actions WHERE details::text LIKE %s", (f"%{PREFIX}%",))
        counts["baker_actions"] = cur.rowcount
    conn.commit()
    return counts


# --------------------------------------------------------------------------- #
# Runner scaffold shared by r1..r4
# --------------------------------------------------------------------------- #
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
    conn = admin_conn()
    try:
        bootstrap_tables(conn)
        stub_external_io()
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
        if not args.keep:
            removed = cleanup(conn)
            print(f"cleanup: {removed}")
        conn.close()
