# BUS_FLEET_COMMS_AUDIT_1

**Dispatched:** 2026-07-12 · **Lane:** b1 · **Origin:** Director directive 2026-07-12 ("audit how the bus fleet communicates; root out all impediments to proper production work").

Harness-V2: N/A — diagnose-only audit, no production code changes; output is a findings report + prioritized fix list for lead ratification.

## Context

A week of bus incidents shows a pattern of per-seat communication defects found one at a time: ARM had no body-read surface (fixed #9164 lineage / vault PR #164); researcher's ack script rejects its own role (open, deputy assigned); codex idled on a work-order dispatch until nudged (orientation gap, patched 2026-07-11); Baker MCP shared key resolves every caller to `daemon`, so `baker_inbox_read`/ack return 403 for real seats; BB-Desk missed an airport-ticket escalation (app-resident, cannot autowake). Director wants ONE systematic audit instead of incident-driven patching.

Live symptom seed (lead, 2026-07-12): `GET /msg/all` (director key) returns 251 messages, ALL wildcard `to=*`, 251/251 unacked, 51 older than 48h (lifecycle noise never acked by anyone) — and it is unclear whether `/msg/all` even returns non-wildcard traffic, which would also affect the new /bus-console fleet view.

## Problem

Nobody has a fleet-wide map of which seats can actually (a) read message bodies mid-session, (b) ack, (c) post, (d) be woken. Defects surface only when a seat happens to fail on live work. Audit and enumerate every impediment so lead can dispatch a fix wave once, instead of patch-per-incident.

## Scope — diagnose-only, READ-ONLY (no fixes in this brief)

1. **Seat I/O matrix.** For every slug in the brisen-lab registry (`/api/v2/terminals` + `~/baker-vault/_ops/registries/agent_registry.yml`): does the seat have a working read-bodies surface, ack surface, post surface? Test with each seat's own key where retrievable (1P `BRISEN_LAB_TERMINAL_KEY_<slug>` rows), else static-inspect its picker scripts/cage. Output a table: slug × {read, ack, post, wake} × {OK / BROKEN(evidence) / N-A(reason)}.
2. **Wake-path map.** Which slugs are terminal-wakeable vs app-resident vs never-wakeable; topic-gate rules (which topics wake, which are suppressed); wake_events health for the last 7 days; the codex-class gap (seat wakes but treats dispatch as FYI — check each seat's orientation for an execute-on-dispatch rule).
3. **Identity layer.** Confirm the Baker MCP shared-key→`daemon` resolution defect scope: which MCP bus tools are unusable per-seat because of it; whether per-seat key binding in MCP is feasible (design sketch only, no build).
4. **Broadcast/ack hygiene.** Wildcard `to=*` semantics: who is expected to ack broadcasts; why 251 sit unacked; whether lifecycle noise should be auto-expired (30d TTL exists — check it covers wildcards); whether `/msg/all` shows non-wildcard traffic (affects /bus-console fidelity).
5. **Registry drift.** Cross-check the 12-row wiring map (install SOP) for every installed agent: TERMINALS arrays, KNOWN_CARD_SLUGS, alias canonicalization, orphaned/stranded slugs.
6. **Prioritized impediment list.** Every finding rated P0 (blocks production work) / P1 (causes manual Director/lead intervention) / P2 (hygiene), each with a one-line proposed fix + owner suggestion. Include or reject the "MCP per-seat identity" fix with reasoning.

## Files Modified

None (read-only audit). Report only: `briefs/_reports/B1_bus_fleet_comms_audit_1_<date>.md`.

## Verification

1. Matrix covers 100% of registry slugs — no silent omissions; N/A rows carry reasons.
2. Every BROKEN cell has reproducible evidence (command + response, key material redacted).
3. Wake map reconciles with wake_events data, not just docs.
4. Findings list cross-references the known incidents above (ARM, researcher, codex, MCP, BB-Desk) — if the audit method wouldn't have caught a known incident, the method has a gap; fix the method.

## Acceptance criteria

1. Report at `briefs/_reports/` with matrix + wake map + P0/P1/P2 list.
2. Ship-post summary to lead on bus with counts (P0/P1/P2).
3. No writes to any bus state beyond test posts to your own slug (self-addressed, then acked).
4. Runtime cap: if the full matrix exceeds one session's budget, ship partial with explicit coverage list — no silent truncation.

## References

- Registry: `~/baker-vault/_ops/registries/agent_registry.yml` · install SOP 12-row map: `_ops` skill `install-agent-to-brisen-lab`.
- Known-incident anchors: bus #9128/#9153/#9157 (ARM), #9161 item 3 (researcher ack), lessons.md #118 (codex idle), #9147 (BB-Desk escalation).
- Bus read discipline: own-key `/msg/{slug}`, ack field `acknowledged_at` (first ack can no-op — verify after POST).
