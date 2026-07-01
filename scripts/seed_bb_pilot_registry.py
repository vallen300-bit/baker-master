"""One-off, idempotent seed of the BB-AUK-001 pilot project into project_registry.

NOT auto-run. Invoke explicitly:  python3 scripts/seed_bb_pilot_registry.py
Re-runnable: register_project upserts on match_key, so repeated runs are no-ops.

Seeds exactly one scheduled-flight pilot row so the Box 5 hard-lane resolver
(`resolve_project_number`, shipped in PR #439) has a live registered project to
match. No resolver logic, no runner — this is the BRIEF-B data seed only.

matter_slug = 'aukera' — the Director-ratified canonical slug for the BB-AUK-001
pilot (slugs.yml v23; is_canonical('aukera') is True). 'AUK' is the human display
mnemonic in the project number, not the slug.
desk_code 'BB' -> baden-baden-desk is derived by register_project from the prefix;
desk_owner must equal that or register_project raises (fail loud).

Aliases are RETIRED for routing safety (routing reversal 2026-07-01,
BOX5_ROUTING_REVERSAL_E_1): name/alias matching is unsafe for multi-matter
counterparties, so this seed carries no aliases — only the explicit project code
routes. Mirrors kbl.project_registry_store.seed_bb_pilot() (aliases=[]).
"""
from kbl.db import get_conn
import kbl.project_registry_store as pr
import kbl.slug_registry as slug_registry

PROJECT_NUMBER = "BB-AUK-001"
DESK_OWNER = "baden-baden-desk"   # MUST equal DESK_CODES['BB']; desk_code is derived from 'BB'
MATTER_SLUG = "aukera"            # Director-ratified canonical slug; AUK is the display mnemonic
CLICKUP_LIST_ID = "901524194809"  # 'BB-AUK-001 Timetable' list (baden-baden-desk, bus #4886, wired 2026-07-01)
ALIASES = []  # retired for routing safety (BOX5_ROUTING_REVERSAL_E_1); explicit code only


def main() -> int:
    # Fail loud before touching the DB if the slug isn't canonical.
    if not slug_registry.is_canonical(MATTER_SLUG):
        raise ValueError(f"matter_slug {MATTER_SLUG!r} is not canonical (slugs.yml)")
    with get_conn() as conn:
        try:
            pr.ensure_project_registry_table(conn)
            canonical = pr.register_project(
                conn,
                project_number=PROJECT_NUMBER,
                desk_owner=DESK_OWNER,
                matter_slug=MATTER_SLUG,
                clickup_list_id=CLICKUP_LIST_ID,
                aliases=ALIASES,
            )
            conn.commit()
        except Exception:
            # get_conn() only closes on exit; roll back explicitly so a failed run
            # leaves no partial state, then re-raise so the operator sees it.
            conn.rollback()
            raise
    print(f"seeded/updated {canonical}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
