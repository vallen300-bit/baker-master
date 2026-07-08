# DIAGNOSE — AO_FLIGHT_PROD_TICKET_ROUTING_1 (gate: diagnose-confirm, pre-fix)

**Author:** b1 (fresh seat) · **Date:** 2026-07-07 · **Branch:** `b1/ao-flight-ticket-routing`
**Reply topic:** `baker-os-v2/ao-flight-ticket-routing` → lead
**Status:** findings posted; HOLDING for lead scope-confirm before any fix commit.

Traced the three mint lanes in `orchestrator/airport_ticketing_bridge.py` end-to-end
(arrival → keyword/identity match → `_desk_slug()` → mint/post). Read-only; no edits to code.

## 1. Which lanes carry real matter attribution AT MINT TIME

| Lane | matter known at mint? | Evidence |
|---|---|---|
| **Plaud** | **YES** | `PlaudArrival.matter_slug` (dataclass :248) from `meetings.matter_slug` active-matter lane (:817, :835-842); ticket stamps `arrival.matter_slug or _matter_slug()` (:743). `_desk_for_matter(arrival.matter_slug)` works as the brief pre-picked. |
| **WhatsApp** | **NO** | `WhatsAppArrival` has **no `matter_slug` field** (:253-260). `build_whatsapp_ticket` stamps global `_matter_slug()` (:795). WA is fetched by participant identity (`active_participant_values(conn,"whatsapp")`), not by matter. |
| **Email** | **NO** | `build_email_ticket` stamps global `_matter_slug()` (:636). Keyword lane = flat matter-agnostic env tuple (`active_keywords()` :356-359); no keyword→matter map exists. Participant lane = identity-only, Director-barred from routing (see §3). |

**Key correction to the brief:** the Solution says *"Nonmail lanes (plaud/WA): route via `_desk_for_matter(arrival.matter_slug)`."* This is **not implementable for WA** — `WhatsAppArrival` carries no `matter_slug`. Only **Plaud** can route by matter at mint. WA sits with email.

## 2. How a ticket actually boards a desk's flight (two distinct desk fields)

- **Mint-time boarding** = the bus post in `reserve_ticket`: `recipient = resolve_owner_slug(ticket.proposed_desk_slug)` (:1783). `proposed_desk_slug` comes from `_desk_slug()` = global env `AIRPORT_TICKETING_DESK` (default `baden-baden-desk`). **This is what the brief's `_desk_for_matter` would change**, and what AC1 ("ticket boards ao-desk") targets. Correct target.
- **`desk_owner`** is a **separate `airport_tickets` column** (:1095) written *downstream* by `write_terminal_status(..., desk_owner=...)` (:1904-1949), NOT the mint-time recipient.

## 3. Existing matter→desk routing the brief's problem statement omits

The email lane already has TWO downstream matter+desk routing lanes, both sourcing the registry:
- **(e.7) explicit-project-code lane** (:2745-2811): exactly-1 registered active code → `write_terminal_status(matter_slug=resolved["matter_slug"], desk_owner=resolved["desk_owner"], ...)`.
- **(e.8) thread-continuity lane** (:2830-2879): code-less reply inheriting a prior code-bound thread → same `desk_owner`/`matter_slug` write.

Both resolve via `kbl/project_registry_store.py::resolve_project_number` / `resolve_by_thread`, which read **`project_registry.desk_owner` + `.matter_slug`** (`_row_to_dict` :168-174; `_HARD_SELECT` :185-188).

**Director-ratified multi-matter-safety ruling (lead amend #5035, comment :1525-1532):** participant identity **NEVER auto-routes** — it is a *fetch* signal only. A sender in >1 active project is ambiguous by construction and falls through to the safe-default desk. So identity→matter routing at mint is explicitly barred; it cannot be used to send AO email/WA to ao-desk.

**Net for email/WA:** an AO arrival with no explicit project code and no code-bound thread boards the **global** desk's flight at mint (`proposed_desk_slug`=baden-baden-desk) and, at most, gets a downstream `desk_owner` annotation. It does not board ao-desk's flight.

## 4. Single-source-of-truth conflict (Mnilax: surface, don't average)

The brief pre-picks a **new** env JSON map `AIRPORT_TICKETING_DESK_MAP={"ao":"ao-desk"}` as the matter→desk source. But **`project_registry.desk_owner` already encodes matter→desk ownership** and is already the source of truth consumed by the code/thread lanes AND `airport_outbound_connector`, `flight_snapshot`, `airport_boarding_flow`, `airport_lounge_writer`. A parallel env map is a second source that can drift from the registry.
- Cleaner: `_desk_for_matter(matter_slug)` resolves the desk from the matter's active `project_registry` row(s) (fallback to global `_desk_slug()` on miss / ambiguity / error), reusing the ratified registry mapping. No schema migration — a SELECT, compatible with "config-driven only".
- Caveat: a `matter_slug` may map to >1 project row. Rule needed: all active rows agree on `desk_owner` → use it; disagree → fallback to global (mirror the #5035 ambiguity discipline). AO = slug `ao`, registry id=15 — confirm 1 row / 1 desk_owner in prod before relying on this.

## 5. Scope questions for lead (HOLDING for confirm before fix)

1. **WA lane** — pre-picked "route WA via `arrival.matter_slug`" can't be built (no field). Treat WA like email (keeps global desk this brief + report follow-up), or widen scope to add WA matter attribution (which reopens the #5035 identity-routing question)?
2. **Source of `_desk_for_matter`** — registry `desk_owner` (single source of truth, no drift, SELECT-only) vs the brief's new `AIRPORT_TICKETING_DESK_MAP` env JSON (parallel source, can drift)?
3. **Does the Director goal hold with only Plaud routed?** Only Plaud carries matter at mint. If email/WA stay on the global desk (a downstream `desk_owner` annotation only), does "AO Desk receives its own tickets in production" require the bigger email/WA refactor (touches #5035), or is the Plaud slice + reported follow-up acceptable for this brief?

Files read: `orchestrator/airport_ticketing_bridge.py`, `orchestrator/flight_snapshot.py`, `kbl/project_registry_store.py`. No code changed.
