# CODE_3_PENDING — dispatch (supersedes prior)

dispatch: BOX5_ROUTING_REVERSAL_E_1
brief: briefs/BRIEF_BOX5_ROUTING_REVERSAL_E_1.md
to: b3
from: lead
dispatched_by: lead
ship_to: lead (ship report + gate verdicts to lead)
branch: box5-routing-reversal-e-1
class: production feature, behaviour-change to a DARK lane (E runs only when BOX5_FAST_LANE_ENABLED; prod-off)
effort: medium

summary: Routing reversal on the Box 5 E lane. Alias matching is OUT for routing (unsafe for multi-matter counterparties per Director ruling 2026-07-01 — "Aukera" spans Annaberg + MO Vienna + others). E becomes an explicit-code routed-TICKET fallback: a single registered ACTIVE project code that D's hard lane didn't FAST_TICKET routes to its desk as TICKET (confidence 0.80); 0/>1/retired/unregistered codes fall through to (f) safe-default TICKET. Rename soft_ticket -> code_routed_ticket; drop the now-unused resolve_by_alias bridge import; retire the pilot aliases in seed_bb_pilot(). Verbatim replacement code + AC1-AC7 in the brief.

design_source: ~/baker-vault/_ops/build/baker-os-v2/05_outputs/baker-os-v2-box5-routing-reversal-e-outbound-increment2-spec-codex-arch-20260701.md §Deliverable 1.

parallel-build note: b4 builds BOX5_OUTBOUND_INGEST_2 on the outbound capture path of the SAME file (orchestrator/airport_ticketing_bridge.py) — non-overlapping region. Branch off current main; rebase if b4 merges first; flag any real conflict to lead (do not average).

gate: G1 self-check (py_compile + full AC pytest + scripts/check_singletons.sh) -> codex G3 on BUS (topic gate/box5-routing-reversal-e-g3, effort MEDIUM) -> lead G4 /security-review -> lead squash-merge.
