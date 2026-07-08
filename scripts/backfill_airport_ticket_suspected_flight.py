#!/usr/bin/env python3
"""AIRPORT_TICKET_PER_FLIGHT_TAG_1 — audited airport_tickets suspected_flight backfill.

Dry-run by default. ``--run`` updates old airport_tickets rows so the column and
embedded ticket JSON carry the per-flight project code:

* registered matter_slug -> project_registry.project_number (e.g. ao -> AO-OSK-001)
* historical global BB lane -> committed BB dashboard snapshot project_code, but
  only for the bridge's historical default matter/flight pair

Every apply run writes one baker_actions audit row. Re-running after a successful
apply is idempotent: no row changes and no duplicate audit row.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kbl.db import get_conn  # noqa: E402
from orchestrator import airport_ticketing_bridge as bridge  # noqa: E402

TASK_ID = "AIRPORT_TICKET_PER_FLIGHT_TAG_1"
ACTION_TYPE = "airport_ticket.per_flight_backfill"
TRIGGER_SOURCE = "airport_ticket_per_flight_backfill"


@dataclass(frozen=True)
class TicketFlightPlan:
    ticket_id: int
    old_flight: str
    new_flight: str
    reason: str
    matter_slug: str


def _norm(value: Any) -> str:
    return str(value or "").strip()


def load_snapshot_legacy_pairs(snapshot_dir: Path | None = None) -> dict[tuple[str, str], str]:
    """Return {(legacy_matter_slug, legacy_suspected_flight): project_code}.

    Prefer explicit ``legacy_suspected_flights`` + ``legacy_matter_slugs`` fields on
    committed dashboard snapshots. Older snapshots without those fields fall back to
    the bridge's historical default matter/flight pair. This is the BB dual-match
    bridge during backfill; it is derived from repo sources, not an inline mapping.
    """
    snapshot_dir = snapshot_dir or (REPO_ROOT / "orchestrator" / "flight_dashboards")
    out: dict[tuple[str, str], str] = {}
    for path in sorted(snapshot_dir.glob("*.json")):
        try:
            snap = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        project_code = _norm(snap.get("project_code")).upper()
        if not project_code:
            continue
        legacy_flights = [
            _norm(v)
            for v in snap.get("legacy_suspected_flights", [])
            if _norm(v)
        ]
        legacy_matters = [
            _norm(v).lower()
            for v in snap.get("legacy_matter_slugs", [])
            if _norm(v)
        ]
        if not legacy_flights and _norm(snap.get("suspected_flight")) == bridge._DEFAULT_FLIGHT:
            legacy_flights = [bridge._DEFAULT_FLIGHT]
            legacy_matters = [bridge._DEFAULT_MATTER.lower()]
        for matter in legacy_matters:
            for flight in legacy_flights:
                out[(matter, flight)] = project_code
    return out


def plan_ticket_flight_backfill(
    rows: Iterable[dict[str, Any]],
    *,
    matter_to_project: dict[str, str],
    legacy_pairs: dict[tuple[str, str], str],
) -> list[TicketFlightPlan]:
    """Pure planner used by tests and the live backfill.

    Registry matter wins first. The legacy global-flight pair is deliberately narrow:
    it only matches the bridge's known historical default matter+flight pair, so a
    stray row from another matter that happened to inherit the old global flight does
    not get silently laundered into BB-AUK.
    """
    plans: list[TicketFlightPlan] = []
    for row in rows:
        row_id = int(row["id"])
        old_flight = _norm(row.get("suspected_flight"))
        matter = _norm(row.get("suspected_matter_slug")).lower()
        target: Optional[str] = None
        reason = ""
        if matter and matter in matter_to_project:
            target = matter_to_project[matter]
            reason = "registry_matter"
        elif matter and old_flight:
            target = legacy_pairs.get((matter, old_flight))
            reason = "legacy_default_matter_flight" if target else ""
        if target and old_flight != target:
            plans.append(
                TicketFlightPlan(
                    ticket_id=row_id,
                    old_flight=old_flight,
                    new_flight=target,
                    reason=reason,
                    matter_slug=matter,
                )
            )
    return plans


def _fetch_matter_to_project(conn: Any) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT LOWER(matter_slug), project_number, COUNT(*) OVER (PARTITION BY LOWER(matter_slug)) AS n
              FROM project_registry
             WHERE status = 'active'
               AND matter_slug IS NOT NULL
               AND project_number IS NOT NULL
               AND btrim(project_number) <> ''
            """
        )
        rows = cur.fetchall()
    out: dict[str, str] = {}
    for matter, project, n in rows:
        if int(n) == 1:
            out[str(matter)] = str(project).strip().upper()
    return out


def _fetch_ticket_rows(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, suspected_matter_slug, suspected_flight
              FROM airport_tickets
             WHERE suspected_flight IS NOT NULL
                OR suspected_matter_slug IS NOT NULL
             ORDER BY id
            """
        )
        return [
            {"id": r[0], "suspected_matter_slug": r[1], "suspected_flight": r[2]}
            for r in cur.fetchall()
        ]


def _counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    c = Counter(_norm(r.get("suspected_flight")) or "<blank>" for r in rows)
    return dict(sorted(c.items()))


def _apply(conn: Any, plans: list[TicketFlightPlan]) -> int:
    updated = 0
    with conn.cursor() as cur:
        for plan in plans:
            cur.execute(
                """
                UPDATE airport_tickets
                   SET suspected_flight = %s,
                       ticket = CASE
                           WHEN ticket IS NULL THEN ticket
                           ELSE jsonb_set(ticket, '{suspected_flight}', to_jsonb(%s::text), true)
                       END,
                       updated_at = NOW()
                 WHERE id = %s
                   AND suspected_flight IS DISTINCT FROM %s
                """,
                (plan.new_flight, plan.new_flight, plan.ticket_id, plan.new_flight),
            )
            updated += cur.rowcount
    return updated


def _audit(conn: Any, payload: dict[str, Any]) -> Optional[int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, payload, trigger_source, success)
            SELECT %s, %s, %s::jsonb, %s, TRUE
            WHERE NOT EXISTS (
                SELECT 1 FROM baker_actions
                 WHERE action_type = %s
                   AND target_task_id = %s
                   AND success IS TRUE
                   AND payload->>'mode' = 'apply'
            )
            RETURNING id
            """,
            (
                ACTION_TYPE,
                TASK_ID,
                json.dumps(payload, sort_keys=True),
                TRIGGER_SOURCE,
                ACTION_TYPE,
                TASK_ID,
            ),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="apply the idempotent backfill")
    args = parser.parse_args(argv)

    with get_conn() as conn:
        matter_to_project = _fetch_matter_to_project(conn)
        legacy_pairs = load_snapshot_legacy_pairs()
        before_rows = _fetch_ticket_rows(conn)
        plans = plan_ticket_flight_backfill(
            before_rows,
            matter_to_project=matter_to_project,
            legacy_pairs=legacy_pairs,
        )
        payload = {
            "task": TASK_ID,
            "mode": "apply" if args.run else "dry_run",
            "before_counts": _counts(before_rows),
            "planned_total": len(plans),
            "planned_by_target": dict(Counter(p.new_flight for p in plans)),
            "planned_by_reason": dict(Counter(p.reason for p in plans)),
            "legacy_pairs": {f"{m}|{f}": p for (m, f), p in legacy_pairs.items()},
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        if not args.run:
            return 0
        updated = _apply(conn, plans)
        after_rows = _fetch_ticket_rows(conn)
        payload["updated"] = updated
        payload["after_counts"] = _counts(after_rows)
        audit_id = _audit(conn, payload)
        payload["audit_id"] = audit_id
        conn.commit()
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
