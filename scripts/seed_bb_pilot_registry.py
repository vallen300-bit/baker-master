"""One-off, idempotent seed of the BB-AUK-001 pilot project into project_registry.

NOT auto-run. Invoke explicitly:  python3 scripts/seed_bb_pilot_registry.py
Re-runnable: register_project upserts on match_key, so repeated runs are no-ops.

Seeds exactly one scheduled-flight pilot row so the Box 5 hard-lane resolver
(`resolve_project_number`, shipped in PR #439) has a live registered project to
match. No resolver logic, no runner — this is the BRIEF-B data seed only.

matter_slug = 'annaberg' (the Baden-Baden project vehicle, Aukera-financed);
'AUK' is the human display mnemonic in the project number, NOT the aukera lender
matter. desk_code 'BB' -> baden-baden-desk is derived by register_project from the
prefix; desk_owner must equal that or register_project raises (fail loud).
"""
from kbl.db import get_conn
import kbl.project_registry_store as pr
import kbl.slug_registry as slug_registry

PROJECT_NUMBER = "BB-AUK-001"
DESK_OWNER = "baden-baden-desk"   # MUST equal DESK_CODES['BB']; desk_code is derived from 'BB'
MATTER_SLUG = "annaberg"          # AUK is the display mnemonic, not the matter slug
CLICKUP_LIST_ID = None            # no canonical Baden-Baden ClickUp list yet; backfill when provisioned
ALIASES = ["annaberg", "aukera annaberg"]


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
