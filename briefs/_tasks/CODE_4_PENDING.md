# CODE_4_PENDING — dispatch (supersedes prior)

dispatch: BOX5_OUTBOUND_INGEST_2
brief: briefs/BRIEF_BOX5_OUTBOUND_INGEST_2.md
to: b4
from: lead
dispatched_by: lead
ship_to: lead (ship report + gate verdicts to lead)
branch: box5-outbound-ingest-2
class: production feature, additive + DARK (behind existing AIRPORT_OUTBOUND_INGEST_ENABLED, default false)
effort: high

summary: Increment 2 — wire captured OUTBOUND email (Increment 1 #445) to (a) ClickUp timetable create/update and (b) flight-state progression, for RATIFYING outbound only; routine outbound stays evidence-only. New durable event state table (airport_outbound_events), state machine, ClickUp write contract (CLICKUP_TIMETABLE_WRITE v1, idempotency keys, BAKER Space only, <=10/cycle), flight-state contract (OUTBOUND_FLIGHT_TRANSITION v1, ClickUp-before-flight ordering), closure guard (never land/close from outbound alone), baker_actions audit on every write. Same flag flips skip + capture + connector TOGETHER. Activation stays Director-gated.

design_source (AUTHORITATIVE — build to it, do not re-derive): ~/baker-vault/_ops/build/baker-os-v2/05_outputs/baker-os-v2-box5-routing-reversal-e-outbound-increment2-spec-codex-arch-20260701.md §Deliverable 2. Carries full state machine + ClickUp/flight contracts + correlation order + 12 acceptance tests.

diagnose (done by lead): Increment 1 already captures outbound as candidate row + airport_ticket.outbound_signal action, short-circuiting before D/E lanes. Increment 2 EXTENDS that outbound branch only — inbound D/E/(f) untouched. Re-pin all line refs by grep (file ~1684 lines, volatile).

parallel-build note: b3 builds BOX5_ROUTING_REVERSAL_E_1 on the E lane of the SAME file — non-overlapping region. Branch off current main; rebase if b3 merges first; flag any real conflict to lead (do not average).

gate: G1 self-check (py_compile + full 12-AC pytest + scripts/check_singletons.sh) -> codex G3 on BUS (topic gate/box5-outbound-ingest-2-g3, effort HIGH) -> lead G4 /security-review -> lead squash-merge.
