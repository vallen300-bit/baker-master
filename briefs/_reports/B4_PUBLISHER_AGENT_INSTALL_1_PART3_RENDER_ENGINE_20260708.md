# B4 ship report — PUBLISHER_AGENT_INSTALL_1 Part 3 (render engine)

- **PR:** #490 → main · branch `b4/publisher-render-engine` · commit `3df3b978`
- **Dispatcher:** lead · **Class:** production code, ships DORMANT (worker `PUBLISHER_BUS_WORKER_ENABLED=false`; engine no-writes / no-model) · **State:** dark (merge = no live surface change)
- **Gate:** G1 self ✅ → G3 codex (routed by lead, bus #7325) → lead merge · **Do not self-merge**
- **Bus:** dispatch chase #7254/#7311 · AC1 fork #7317 · ship #7322 · lead ruling #7325

## What shipped
`orchestrator/publisher_render.py` (render ENGINE) + `tests/test_publisher_render.py` (26 tests). Purely additive — no existing source modified. The engine is the `render_fn` injected into `PublisherBusWorker` (Part 2, merged PR #479); the worker's `_default_render_ticket` import now resolves.

`FLIGHT_DASHBOARD_PACKET` facts → canonical Pattern-E HTML + the 5 deterministic contract gates (`verify-dashboard-render` SKILL step 4 == content-contract-v2 rules 9–11). **Pure stdlib, no model calls, no filesystem writes, stateless per render.**

## Done rubric / AC answers
- **AC2 — gates FAIL a seeded violation each.** `gate_version_stamp` (missing / non-increment), `gate_lexical` (10a German diacritic, 10a German term, 10b banned abbreviation, 10c wall-of-text **with Engine-Lab exemption**), `gate_as_of` (9a missing anchor), `gate_staleness` (9c cited version older than the living-documents register), `gate_honesty` (11a fake-live control on a read-only page, section-4 non-ledger machine counts). Clean render PASSes all 5. Tests `test_gate_*` GREEN.
- **AC1 (mechanism, A2 in-slice per lead #7325).** Figures/sections/receipts round-trip **byte-normalized** via `data-*` markers (`test_ac1_*_round_trip`); `Page vN` = **max** stamp so the Engine-Lab build-log history (v2..v15) does not trip it (`test_ac1_page_version_is_max_not_first`); **grounded on the real on-disk v1 fixture** — every receipt derived from `data-fixture.json` survives the render, non-tautological (`test_ac1_grounded_on_real_v1_fixture_receipts_survive`).
- **AC7 — per-render context isolation (spec v1.1(b)).** matter-A fact absent from a matter-B render in the same drain run (`test_ac7_no_cross_contamination_between_matters`); stateless — same input → identical output, interleaved renders independent (`test_ac7_engine_is_stateless_same_input_same_output`).
- **v1.1(a) — flight's OWN content contract.** `resolve_content_contract` picks the flight's inline contract (can extend the section set, e.g. `v11`) else the base; no hardcoded universal schema (`test_v1_1a_*`).
- **Bounce path.** Malformed packet (missing `project_code`/`matter_slug`) → `status:"bounce"` back to the desk — Publisher owns FORM only (`test_malformed_packet_bounces`).

## Design decisions (surfaced)
- **Deterministic floor, not full reproduction.** The canonical "template" is itself a 735-line filled BB-AUK page (no placeholders); a flat packet cannot regenerate a hand-authored 815-line page byte-for-byte. Per brief §10 OPEN-2 the floor is figures + sections + receipts preserved + register conformance; residual layout is AH1's call. The engine emits explicit `data-figure`/`data-receipt`/`data-page-version` markers so the fact-set round-trips exactly.
- **Compact canonical stylesheet embedded** (the `:root` Pattern-E palette + core classes lifted verbatim from `flight-dashboard-canonical-v5.html`) — keeps the engine self-contained/deterministic rather than coupling to a vault file path at render time.
- **`extract_page_version` = max `Page vN`** (or authoritative `data-page-version`), because the build log lists every historical version; a first-match would be wrong.
- **Gates operate on an immutable `RenderDoc`** built once per render — pure, unit-testable, each gate seeds one violation. Engine-Lab section excluded from the wall-of-text scope (rule 10c v2.5 exemption).
- **Stdlib `re`, not bs4** (available) — extraction targets our own deterministic `data-*` markers; regex is exact and dependency-free here. bs4 would harden shipped-hand-page fallback extraction in a later slice.

## Test evidence
- **39/39 GREEN** (literal pytest): 26 new `tests/test_publisher_render.py` + 13 `tests/test_publisher_bus_worker.py`. Worker→`render_ticket` integration resolves cleanly (`status=failed` on the v1 fixture is correct — it contains the banned abbreviation "CP", which the lexical gate flags, i.e. the engine working as designed).
- Broad suite: pre-existing ambient failures only (`FileNotFoundError`/`ModuleNotFoundError`, DB/MCP/env) — **zero publisher-related**; change is additive-only (git-confirmed).

## Named follow-up (per lead ruling #7325 — owner: BB desk, NOT b4)
- **A3 — desk-emits-v2-packet AC1 integration close.** The full AC1 *content-diff* (render-from-facts vs the shipped BB-AUK-001 matter content) is deferred to **BB desk emitting a `FLIGHT_DASHBOARD_PACKET v2` structured-facts packet** for BB-AUK-001. No such packet exists today (only the stale v1 build-infra `data-fixture.json`; the shipped Page v15 was hand-authored under content-contract-v2 — the five-hand-writer path Publisher replaces). When the desk emits a v2 packet, AC1 becomes a real desk→publisher integration test (packet → engine render → figures/sections/receipts diff vs the desk's own facts). Publisher owns FORM; the desk owns the content packet. This is the production close; the A2 fidelity-mechanism proof ships now.

## Harness V2
Task class = production code, ships DORMANT → `POST_DEPLOY_AC_VERDICT` **N/A** this slice (no live surface until canary flip).
