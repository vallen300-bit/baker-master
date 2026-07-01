# THREAD_CONTINUITY_ROUTING_1

**Owner:** lead (AH1) · **Builder:** b-code · **Gate:** codex G3 (HIGH) → lead G4 /security-review
**Source:** Director-caught miss 2026-07-01 — Aukera/Annaberg reply-chain signal would not route post-routing-reversal even once ingested.

## Problem

`BOX5_ROUTING_REVERSAL_E_1` (#446, merged 2026-07-01) retired name/alias routing —
correctly, because fuzzy name matching is unsafe for multi-matter counterparties. But it
left a **recall hole**: an email with no explicit project code, from a sender who is not a
registered participant, now routes nowhere — even when it is a direct reply on a thread
already bound to a matter. Counterparties rarely put "BB-AUK-001" in subject lines, so
genuine deal replies (e.g. Siegfried's ESG reply on the Aukera thread) fall through.

## Insight

Thread identity is a **strong** signal, unlike fuzzy names. If a prior ticket on the same
`thread_id` was already **code-bound** to an active project, a reply on that thread almost
certainly concerns the same matter. This restores recall WITHOUT reintroducing the unsafe
name matching #446 removed. It mirrors the outbound connector's own `correlate()` logic,
which already trusts `bus_thread_id` thread continuity.

## Evidence / current state

- `orchestrator/airport_ticketing_bridge.py`: `airport_tickets` stores `thread_id` (+
  `bus_thread_id`); the hard lane calls `resolve_project_number` then
  `resolve_by_participant` (bridge ~lines 1428-1460). No thread→project inheritance today.
- Resolvers live in `kbl/project_registry_store.py` (`resolve_project_number`,
  `resolve_by_participant`, `resolve_by_alias`).

## Design (target)

1. **New resolver `resolve_by_thread(thread_id) -> Optional[dict]`** (project_registry_store
   or a small thread-binding helper): return the active project a prior ticket on this
   `thread_id` was bound to — **only** if that prior binding was itself **hard/code-bound**
   (project code + participant), NOT a soft guess. This is the load-bearing safety rule:
   continuity may only inherit a high-confidence binding, so it can never launder a weak
   match forward.
2. **Wire into the lane logic** as a strong signal: a code-bound thread match is
   sufficient to route (unlike participant/alias, which stay "never sufficient alone").
   Order: explicit code (hard) → code-bound thread continuity → existing soft lane.
3. **Conflict guard:** if the thread has bindings to >1 active project (thread legitimately
   spans matters), do NOT auto-inherit — fall through to the full desk ticket (mirror the
   existing multi-code CONFLICT behavior). No silent pick.
4. **No new fuzzy matching. No alias revival.**

## Constraints

- Surgical: resolver file + `airport_ticketing_bridge.py` lane wiring + tests.
- All DB calls try/except; `.claude/rules/python-backend.md`; run on the shared txn safely
  (savepoint pattern already in the bridge — do not abort the txn on a resolver error).
- No migration if `airport_tickets.thread_id` + project binding columns already suffice
  (builder confirms; if a binding column is missing, propose it — do not assume).

## Acceptance criteria

1. A reply whose `thread_id` matches a prior **code-bound** ticket for an active project
   routes to that project — with NO code in the reply and a non-participant sender.
2. A thread whose prior binding was only a **soft** match does NOT inherit (no laundering).
3. A thread bound to >1 active project → CONFLICT → full desk ticket, not a silent pick.
4. A resolver error is savepoint-isolated; the tick completes (no txn abort).
5. Existing hard-lane + soft-lane + conflict tests stay green.

## TDD plan

1. Repro: Siegfried-style reply (no code, non-participant sender) on a thread with a prior
   code-bound BB-AUK-001 ticket → routes to BB-AUK-001 post-change (fails pre-change).
2. Anti-laundering: prior soft-bound thread → no inheritance.
3. Multi-matter thread → CONFLICT path.
4. Resolver-error savepoint isolation.

## Out of scope

- Ingestion (a thread reply must first be ingested — see `GRAPH_INGEST_SCOPE_WIDEN_1`).
- Reviving alias/name routing.
- Cross-channel (WhatsApp/meeting) thread continuity — email threads only this brief.

## Gate

G1 (builder self-verify + new tests) → **codex G3, effort HIGH** (routing correctness +
cross-matter leakage risk) → **lead G4 /security-review** → lead merge.
