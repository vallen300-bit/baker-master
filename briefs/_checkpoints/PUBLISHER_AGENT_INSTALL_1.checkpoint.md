---
brief: PUBLISHER_AGENT_INSTALL_1
owner: b4
attempt: 2
updated: 2026-07-08
phase: Part 3 (render engine) — building publisher_render.py (successor seat, attempt 2)
---

# PUBLISHER_AGENT_INSTALL_1 — checkpoint

Brief: `~/baker-vault/_ops/build/baker-os-v2/05_outputs/domain-agent-program/BRIEF_PUBLISHER_AGENT_INSTALL_1.md` (@e799167)
Spec: same dir `SPEC_PUBLISHER_AGENT_v1.md`. Dispatch: bus #6295 (lead). Thread topic `baker-os-v2/publisher-install`.

## DONE (landed / merged)
- **Part 1 — rendered-surface write ACL guard.** LANDED on baker-vault main @da04b8e
  (merge of b4/publisher-render-acl-guard @185d1be). Files: `.githooks/render_acl_guard.sh`,
  `.githooks/tests/test_render_acl_guard.sh` (16 cases), `.githooks/pre-push` (mirror), chained in
  `.githooks/pre-commit`. Enforcement = `$BAKER_ROLE` fail-closed; `PUBLISHER_RENDER_ACL_BYPASS=1`
  override; `PUBLISHER_RENDER_ACL_ENFORCE` warn-default (flips ON at canary). Case-insensitive match.
  Fail-closed on diff error. Gates: G1 16/16, deputy G2, codex G3a PASS. Delivers **AC6**.
- **Part 2 — publisher render bus worker (drain core).** MERGED to baker-master main via PR #479
  (squash `a404727`). Files: `orchestrator/publisher_bus_worker.py`,
  `tests/test_publisher_bus_worker.py` (13 cases), wired in `triggers/embedded_scheduler.py`
  (`publisher_bus_poll`). Reuses clerk drain shape; stateless; per-wake cap 5 + bounded re-wake
  drain loop (`max_drain_cycles`); queue-age tripwire POSTs to lead; ack-after-receipt; bounce path;
  gate-FAIL-after-2-reruns escalation. Kill-switch `PUBLISHER_BUS_WORKER_ENABLED` default OFF (ships
  DORMANT). Gates G1 13/13 + deputy G2 + codex G3 PASS. Delivers **AC3, AC5** + the drain contract.

## PART 3 SHIPPED (attempt 2, 2026-07-08) — PR #490, commit 3df3b978, bus ship #7322
- `orchestrator/publisher_render.py` (engine) + `tests/test_publisher_render.py` (26 tests). 39/39 green
  (26 render + 13 worker). Additive-only. Worker's `_default_render_ticket` now resolves.
- Delivered: **AC2** (5 gates fail a seeded violation each), **AC1 mechanism** (figures/sections/receipts
  round-trip byte-normalized + grounded on real v1 fixture; Page vN = max), **AC7** (matter isolation +
  stateless), **v1.1(a)** per-flight contract, **v1.1(b)** stateless.
- OPEN for lead (bus #7317): AC1 CONTENT-diff target (A2 shipped in-slice; A3 = BB desk emits a v2 packet,
  recommended production close). Gate chain pending: G1 lead → G2 deputy → G3 codex. Do not self-merge.
- NEXT after gate: Part 4 (shadow-week harness setup) + install rows (5/6 registry, 8 status card,
  1-4/12 picker+alias+profile+wake) + AC4 kill-switch e2e.

## LEFT (this arc)
- **Part 3 (SHIPPED — see above) — offline re-render acceptance test = AC1.** Build the render ENGINE (injected as
  `render_fn` in publisher_bus_worker): structured flight-state facts -> HTML via canonical template +
  content-contract rules 1-11 + deterministic gates (lexical 10a-c, staleness 9c, version stamp,
  as-of 9a). Then re-render BB-AUK-001 **Page v9** from structured facts and diff vs b2's shipped v9;
  PASS = **deterministic floor** (byte-normalized match on figures + section set + receipt IDs), AH1
  adjudicates residual layout only (lead ruling brief §10 OPEN-2). Also delivers **AC2** (gates
  demonstrably FAIL a seeded violation: German diacritic 10a, wall-of-text 10c, stale stamp 9c,
  missing `Page vN`).
- **Part 4 — shadow-week harness SETUP only** (not running the week): mirror every desk fold, render
  to a shadow path (zero Director exposure), daily AH1 diff hook.
- **Install rows** (Row 5/6 registry->generator so `publisher` bus slug exists to receive tickets;
  Row 8 non-conversational status card; Rows 1-4/12 picker+alias+profile+wake). **AC4** kill-switch
  end-to-end.

## KEY PATHS
- Live page (AC1 target): `~/baker-vault/_ops/build/baker-os-v2/05_outputs/flight-dashboards/BB-AUK-001/dashboard-v1-pattern-d.html` (internal "Page v9").
- Canonical template: `~/baker-vault/wiki/_templates/flight-dashboard-canonical-v5.html` (Pattern E).
- Content contract: `~/baker-vault/_ops/build/baker-os-v2/05_outputs/flight-dashboard-prep-stack/flight-dashboard-contract.md` (FLIGHT_DASHBOARD_PACKET v1, rules 1-11).
- Verify gate: `~/baker-vault/_ops/skills/verify-dashboard-render/SKILL.md`.
- Registry (Row 5/6): `~/baker-vault/_ops/registries/agent_registry.yml` + `scripts/generate_agent_identity_artifacts.py --write` (3-repo SHA256 match).

## SPEC v1.1 (Director-ratified 2026-07-07, cowork-ah1 #6855 / lead #6862 — @vault main)
Two binding additions join the AC set (AC1-AC6 + these two):
- **(a) Per-flight content-contract, NO universal schema.** The engine loads EACH FLIGHT's OWN
  content-contract at render time. `FLIGHT_DASHBOARD_PACKET v1` (below) is the BASE/template shape,
  not a one-size schema — a flight's own contract governs its render. Engine must resolve the
  per-flight contract from the ticket/matter, not hardcode PACKET v1.
- **(b) Per-render context isolation, one matter per render cycle.** New **AC7 (cross-contamination):**
  a matter-A fact must NEVER appear in a matter-B render within the same drain run. Engine must be
  stateless per render (no module-level caches keyed across matters); the Part-2 worker already calls
  render_fn(ticket) per message with no shared state — keep it that way + add the seeded AC7 test.
Lead: fold (a)/(b) fully at Part 4; (a) already corrected in the Part-3 design below.

## PART 3 SPEC (gathered 2026-07-07)
- **Input schema (base/template):** `FLIGHT_DASHBOARD_PACKET v1` (contract file above) — the base
  structured-facts shape. Per v1.1(a) the engine loads the flight's OWN contract per render.
  Fields incl. project_code/flight_name/matter_slug, current_state (+ state vocab), blockers,
  workstreams, evidence, ticket/dispatch/clickup refs, proof_gaps, last_refreshed_at.
- **Gate definitions are in `verify-dashboard-render/SKILL.md` step 4 (NOT the contract file):**
  - version-stamp: `Page vN` present + incremented.
  - lexical 10a/10b/10c: no German diacritics/terms; no banned abbreviations; no text block
    >2 sentences outside Engine Lab (build/audit log exempt per v2.5).
  - as-of 9a: every figure/claim tile carries an as-of anchor.
  - staleness 9c: diff vs the matter's `living-documents-register.md`; older-than-registered = STALE/FAIL.
  - honesty 11a: no fake-live controls; machine-section counts from a live ledger query, not a snapshot.
  - Steps 1-3 (open in real browser via Chrome 9222, interact, console zero-errors) = the browser half;
    step 4 gates = the deterministic/scriptable half the engine runs as code.

## AC1-TARGET FINDING (attempt 2, 2026-07-08) — escalated to lead
The checkpoint's AC1 plan assumed a structured-facts PACKET matching the shipped BB-AUK-001 page.
**It does not exist.** Only on-disk packet = `data-fixture.json` = FLIGHT_DASHBOARD_PACKET **v1**
(build-infra facts: "Flight lifecycle store missing" / ledger D-20/D-23/D-24; last_refreshed 2026-07-01).
The shipped page (now **Page v15**, not v9) follows content-contract **v2** (`content-contract-v2.md`,
rules to v2.5, 9 sections) which SUPERSEDES v1. No v2 matter-content PACKET was ever captured — the
page was hand-authored by BB desk (the very five-hand-writer path Publisher replaces). AC1-target fork
posted to lead (options A1 author v2 packet from page / A2 round-trip on existing v1 fixture / A3 defer
content-diff to BB desk emitting a v2 packet — desk owns content, publisher owns form). Recommended
A3-production + A2-in-slice. Gates/renderer/AC2/AC7 are unaffected — building now.
Register for staleness gate: `wiki/matters/lilienmatt/living-documents-register.md` (rich, real).

## NEXT CONCRETE STEP
Build `orchestrator/publisher_render.py` = `render_ticket(ticket)->dict`: (1) the 5 deterministic
gate functions (lexical/staleness/version-stamp/as-of/honesty) as pure code returning
{gate,verdict,detail} — these deliver **AC2** (unit tests seed one violation each: German diacritic,
wall-of-text >2 sentences, stale stamp, missing `Page vN`); (2) facts->HTML via canonical template
`wiki/_templates/flight-dashboard-canonical-v5.html`; (3) **AC1** deterministic-diff test re-rendering
BB-AUK-001 v9 (`.../flight-dashboards/BB-AUK-001/dashboard-v1-pattern-d.html`) from its extracted
PACKET facts — PASS = byte-normalized match on figures + section set + receipt IDs (brief §10 OPEN-2).
Wire `render_ticket` as the worker's default `render_fn`. Per v1.1(a): resolve the flight's OWN
content-contract from the ticket/matter at render time (no hardcoded universal schema). Per v1.1(b):
keep the engine stateless per render + add the **AC7** seeded cross-contamination test (matter-A fact
absent from a matter-B render in the same drain run). Sequencing lean (with lead): engine before the
3-repo registry regen.

Gate chain on return: G1 self-verify -> G2 deputy -> G3 codex (route via `codex` bus slug).
Report to lead on topic `baker-os-v2/publisher-install`.
