"""One-off, idempotent seed of the AO-OSK-001 WhatsApp participants into project_registry.

NOT auto-run. Invoke explicitly:  python3 scripts/seed_ao_participants_registry.py
Re-runnable: register_project upserts on match_key, so repeated runs re-set exactly these
participants (idempotent for THESE rows — see caveat below).

TICKETING_AO_IDENTITY_REROUTE_1 (lead ruling #10238, Option A). AO-OSK-001 exists
(matter_slug='ao', desk_owner='ao-desk') but shipped with participants=[]. Because the ticketing
bridge tags identity-only WhatsApp by registry participation, the Eli/Joseph AO money cluster
(Director + Pohanis WA) could never resolve to the AO flight — it fell to the global BB default
and, since 2026-07-08, was silently eaten by task-6 identity suppression. This seed registers the
two AO-participant WA identities so their identity-only WA routes to the ao-desk REVIEW lane
(bridge change in orchestrator/airport_ticketing_bridge.py). Identity still never auto-routes to a
matter desk on its own (#5035) — these mint REVIEW tickets for ao-desk check-in.

CAVEAT: register_project REPLACES the whole participants list on conflict. AO-OSK-001 has
participants=[] today, so this is additive; if the AO participant set later grows via another
process, update this seed rather than blind-rerunning (a rerun would clobber the newer set).

Eli / Joseph counterparty numbers are intentionally absent: no contact identity exists for them
yet (body-mentioned, not senders). AO desk supplies them later; add rows here when it does.

desk_code 'AO' -> ao-desk is derived by register_project from the prefix; desk_owner must equal
that or register_project raises (fail loud). matter_slug 'ao' is canonical (slugs.yml).
"""
from kbl.db import get_conn
import kbl.project_registry_store as pr
import kbl.slug_registry as slug_registry

MATTER_SLUG = "ao"  # canonical (slugs.yml); AO-OSK-001 desk prefix 'AO' -> ao-desk


def main() -> int:
    # Fail loud before touching the DB if the slug isn't canonical.
    if not slug_registry.is_canonical(MATTER_SLUG):
        raise ValueError(f"matter_slug {MATTER_SLUG!r} is not canonical (slugs.yml)")
    with get_conn() as conn:
        try:
            pr.ensure_project_registry_table(conn)
            n = pr.seed_ao_participants(conn)
            conn.commit()
        except Exception:
            # get_conn() only closes on exit; roll back explicitly so a failed run leaves
            # no partial state, then re-raise so the operator sees it.
            conn.rollback()
            raise
    print(f"seeded/updated {n} AO-OSK-001 participant row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
