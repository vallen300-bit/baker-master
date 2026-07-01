# CODE_4_PENDING — dispatch (supersedes prior)

dispatch: BOX5_OUTBOUND_INGEST_1
brief: briefs/BRIEF_BOX5_OUTBOUND_INGEST_1.md
dispatched_by: lead
ship_to: lead (ship report + gate verdicts to lead)
branch: box5-outbound-ingest-1
class: production feature, additive + DARK

summary: Increment 1 — direction-aware email ingestion for the ticketing desk (Director ruling 2026-07-01). Detect outbound (sender in Brisen-controlled domains/addresses), add airport_tickets.direction, tag every arrival, and capture outbound as an action-evidence signal in baker_actions (airport_ticket.outbound_signal). Outbound NEVER boards a desk / nudges / fast-soft-routes. Dark behind AIRPORT_OUTBOUND_INGEST_ENABLED (default false). Ratification->ClickUp-timetable is Increment 2 (out of scope). 5 ACs + full impl in the brief.

diagnose (done by lead): email_messages has no direction column but outbound IS ingested (dvallen@brisengroup.com sender x26,013; sample subjects are sent mail). Direction derivable from sender domain. Bridge-only change, no triggers/ change.

gate: G1 self-check -> codex G3 on BUS (topic gate/box5-outbound-ingest-g3, effort MEDIUM) -> lead G4 /security-review -> lead squash-merge.
