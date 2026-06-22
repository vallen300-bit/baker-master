---
status: PENDING
brief_id: AI_HOTEL_LAB_COCKPIT_UI_1
to: b4
from: lead
dispatched_by: lead
dispatched_at: 2026-06-22
task_class: frontend-feature
harness_v2: applies
gate_plan: G1 self-test (pytest + frontend leak tests AC1-AC11) → G2 deputy-codex gate (AC + threat rubric #3844-pending) → G3 deputy augmented chain → G4 lead /security-review + merge → POST_DEPLOY_AC_VERDICT v1 + AC11 browser screenshots
source_of_truth: codex-arch #3836 (product framing, Director GO) + deputy-codex Step-5 security rubric (#3844 requested, pending — both binding once folded)
builds_on: Step 1 policy/ (LIVE) + Step 2 policy/sources/ (LIVE) + Step 3 policy/search/ (LIVE 35e9c0f) + Step 4 policy/projection/ (LIVE 338d3f6)
---

# BRIEF — AI_HOTEL_LAB_COCKPIT_UI_1

**Sprint:** AI Hotel Lab — Sprint-0, Build Step 5 of 5 (first live cockpit UI).
**Gate owner:** deputy-codex (AC + threat-model), deputy (augmented chain), lead (security-review + merge).
**Source of truth:** codex-arch product framing (bus #3836, Director GO) + deputy-codex Step-5 security
rubric (bus #3844 — requested, fold before this is gate-ready; both binding).

---

## CONTEXT CONTRACT

**What this is.** The AI Hotel Lab **Cockpit UI** — the first live operating surface over the governed
backend shipped in Steps 1-4. A permissioned cooperation instrument: a Brisen internal command view plus
partner-safe **view-as** roles (NVIDIA / MOHG / venue owner). It makes evidence confidence, raw signals,
partner-safe sharing, and the execution roadmap usable for the Director and partners.

**What this is NOT.** NOT a static dashboard refresh or mockup. NOT a second permission engine in JS. NOT
client-side filtering of raw payloads to fake an external view. NOT marketing copy / hero pages. NOT
partner edit/write workflows (read + Brisen-side approve/revoke/refresh/audit only). NOT the final
hospitality/Bodhi operations layer.

**Hard permission rule (codex-arch #3836).**
1. Internal view may show raw signals only where the backend policy engine allows.
2. Partner views consume **ONLY** Step-4 partner projection packets (`policy.projection`).
3. Do NOT build a second permission engine in JS.
4. Do NOT filter raw internal payloads client-side to construct an external view.
5. Empty external packet states stay generic: no hidden counts, reasons, source hints, or blocked-item
   metadata (carries Step-4 F1 invariant).

**Where it lives.** baker-master repo. Serve from the existing FastAPI app (`outputs/dashboard.py`) under a
dedicated route namespace (e.g. `/ai-hotel-lab`), auth-gated like other internal surfaces. The
per-role/external data MUST come from backend endpoints that call `policy.projection` server-side — the
browser never receives raw rows for an external role.

---

## SUBSTRATE TO REUSE (do not reimplement)

- `policy.projection` (Step 4, LIVE) — the ONLY source of any external/partner-facing view packet. The
  cockpit's partner views render packets returned by `serve_external_packet` / projection serializers.
  Never reconstruct external bodies client-side.
- `policy.engine.evaluate(...)` — the ONLY internal-visibility control; the internal cockpit must reflect
  its decisions, not re-decide in JS.
- `policy.search` (Step 3) — raw_signal / research_artifact + routing. Raw Signal Inbox + section routing
  read here; raw is internal-only.
- `policy.sources.registry` (Step 2) — Source Registry / Coverage panel (available sources, gaps, stale
  domains, never_external flags). Safe source labels only externally.
- `policy.lifecycle` — Verified Evidence lane shows only promoted/verified/action-linked items; promotion
  stays human-ratified (no new path).
- Frontend pattern: **Brisen Pattern B — AI Hotel Dashboard.** Use the `design-v2` skill + the shared
  named pattern library; run `ui-surface-prebrief` before CSS. Posture: serious, precise, restrained,
  operational. Light/paper primary, dark optional. No marketing hero, no decorative gradients, no Palantir
  cosplay. Palantir-level = evidence discipline + permissions + auditability + action accountability.

---

## FIRST-SCREEN JOB (above the fold)

1. Title: **AI Hotel Lab**. 2. Current stage / sprint status. 3. Next action. 4. Evidence freshness.
5. External sharing status. 6. Role selector: Brisen / NVIDIA / MOHG / Venue Owner. 7. Advanced Search entry.

## UI SURFACES

1. Left nav across AI Hotel sections + **Execution Roadmap**.
2. Global Advanced Search command bar.
3. **Raw Signal Inbox** — amber frames, internal-only.
4. Section-routed raw signals (competitors→competitors, site→site, NVIDIA→NVIDIA, authorities/site-search→theirs).
5. **Verified Evidence lane** — trusted/current claims only, visually distinct from raw.
6. **Partner Projection panel** — per-role packets; share / revoke / audit states.
7. **Source Registry / Coverage panel** — sources, gaps, stale domains, never-external flags.
8. **Audit drawer** — lifecycle, source, reviewer, projection, revocation.

## CORE WORKFLOWS

1. Search/import signal → route suggestion → amber raw signal in relevant section.
2. Raw signal → research artifact → verified evidence → shared view → action-linked item.
3. Brisen view-as each partner before sharing.
4. Brisen approve / revoke / refresh / audit projected items.
5. Empty/missing areas → amber-framed gaps that also create/surface Execution Roadmap items (no ranking).

## ADVANCED SEARCH — coverage honesty (codex-arch #3836)

Position as a specialized AI Hotel research tool. Target scope: internal Baker/vault/Dropbox/project-room;
emails + WhatsApp where authorized; web; hospitality press; US press; Santa Clara authorities/planning/
site-search. **Do not fake unavailable coverage** — a non-live connector is shown as a source gap AND put
into the Execution Roadmap. Distinguish available sources from planned/gap sources in the UI.

---

## ACCEPTANCE CRITERIA (codex-arch #3836 — verbatim AC1-11; deputy-codex rubric #3849 FOLDED below)

- **AC1** Pattern B consistently: serious operational dashboard, restrained light mode, clear state hierarchy.
- **AC2** External views consume Step-4 projection packets only (server-side; browser gets no raw rows externally).
- **AC3** Role selector / view-as cannot leak raw text, hidden counts, blocked reasons, source hints, or stale cache.
- **AC4** Amber raw signals internal-only; route to relevant section + Execution Roadmap gap/action.
- **AC5** Trusted evidence visually separate from raw signals; requires lifecycle promotion.
- **AC6** Search UI distinguishes available sources from planned/gap sources.
- **AC7** Projection controls show approve / revoke / refresh / audit states.
- **AC8** First screen shows thesis / status / next action / evidence freshness before deep grids.
- **AC9** Mobile/tablet responsive: role selector, search, first-screen state, nav remain reachable.
- **AC10** Tests cover: no raw leak, no cross-role bleed, no client-side bypass, revoked projection hidden,
  stale projection marked, external empty state generic.
- **AC11** Browser screenshots for Brisen internal, NVIDIA, MOHG, Venue Owner views before calling done.

## DEPUTY-CODEX STEP-5 SECURITY/THREAT RUBRIC (bus #3849 — BINDING; map every row 1:1 to a named test + artifact)

**AC refinements (security-critical reads of codex-arch AC1-11):**
- AC1 Pattern-B state hierarchy is security-critical — raw/candidate cannot be styled as trusted. Test + screenshot.
- AC2 External role endpoints consume ONLY Step-4 packets server-side; browser gets no raw rows/ids/search rows/registry internals.
- AC3 Role selector/view-as is server-backed: role switch fetches that role's packet, clears prior-role state; no leak of raw text/hidden counts/blocked reasons/source hints/stale reasons.
- AC4 Raw Signal Inbox internal-only: external roles have no DOM/network/localStorage/preloaded-JSON/hidden-field raw signal text.
- AC5 Trusted Evidence lane = lifecycle-promoted only; raw/research/candidate cannot enter via CSS class or client transform.
- AC6 Search coverage honest: live connectors produce results; missing/planned render as gaps/roadmap, never fabricated rows/counts.
- AC7 Projection controls backend/audit-backed (Step-4 projection/admin state), not local toggles.
- AC8 First-screen status from backend truth; degrade to explicit stale/gap/unknown, not optimistic copy.
- AC9 Mobile/tablet keeps the same data boundary: no alternate endpoint/collapsed-drawer/cached-state/print-share path exposes external-forbidden data.
- AC10 Test matrix maps every AC/T to named tests; **endpoint payload assertions count, template-only assertions do not.**
- AC11 Browser proof: Brisen + NVIDIA + MOHG + Venue Owner screenshots + network-payload/DOM forbidden-token scan before done.

**Threat cases (T1-T12):**
- T1 Raw-text leak: raw email/WA/Plaud/doc/source text reaches external DOM/network/localStorage.
- T2 Metadata leak: external empty state exposes hidden counts/blocked reasons/stale reasons/source hints/raw labels/blocked metadata.
- T3 Cross-role bleed: NVIDIA sees MOHG/venue content or counts; MOHG sees NVIDIA/venue; venue sees partner strategy.
- T4 Stale/revoked persistence: revoked packets still visible; stale still externally actionable after refresh/revoke/source update.
- T5 Client-side permission bypass: frontend fetches broad/internal payload then filters in JS, or crafted role/query/header widens access.
- T6 Second permission engine: JS or endpoint reimplements the role matrix instead of consuming Step-4 packets.
- T7 Direct raw fetch: external view triggers `/alerts`, raw search, raw source registry/inventory, raw policy/search rows, or table-backed endpoints.
- T8 Search fabrication: unavailable email/WA/web/authority connectors shown as working, or gaps hidden behind synthetic results.
- T9 Source-hint leak: external views reveal never_external flags/internal source ids/raw paths/vendor names/internal routes/denied-source reasons.
- T10 Hierarchy misread: Pattern-B makes raw amber/candidate look verified/shared/actionable.
- T11 Responsive regression: mobile/tablet drawer/role selector/exported/printed/cached viewport leaks forbidden data or hides warnings.
- T12 Proof gap: no browser/network evidence for all four roles, or only internal screenshot → gate stays REQUEST_CHANGES.

G2 REQUEST_CHANGES on: any unmapped row, any external raw payload over the wire, any client-side permission filter, any optimistic/faked search coverage.

## NON-GOALS

1. Do not rebuild policy/search/projection logic. 2. No final hospitality/Bodhi layer. 3. No marketing-copy
external pages. 4. No partner edit/write workflows (unless separately authorized). 5. No static mockup
called done.

---

## GATE PLAN (Harness-V2)

1. **G1 self-test** — pytest backend leak/role tests (AC10) + render the 4 role views; no raw row reaches
   an external role over the wire (assert at the endpoint, not just the template).
2. **G2 deputy-codex** — AC + threat rubric (#3844). Focus: raw/hidden-count/reason/source-hint leak via
   role selector or view-as; cross-role bleed; stale/revoked packet visibility; client-side permission
   bypass / direct raw fetch; search-coverage honesty; Pattern B state-hierarchy discipline.
3. **G3 deputy** — augmented architecture/reuse read (no second permission engine; packets server-side).
4. **G4 lead** — /security-review + squash-merge.
5. **POST_DEPLOY_AC_VERDICT v1** + **AC11 browser screenshots** (4 role views) before DONE.

## CODEX-ARCH ADMIN RULING (bus #3873 — BINDING)

1. Step 5 may merge if APPROVE is server-side, audited, via the existing projection policy path.
2. **REVOKE + REFRESH must NOT appear as active controls** — render disabled/read-only with explicit
   reason: "Step 5.1 pending persisted projection-admin store". Bare 501 is not enough; the UI must show
   the disabled state + reason.
3. External partner access stays gated to **Brisen view-as / controlled demo** until revoke is live.
4. Step 5 = cockpit UI + **honest admin-state surface** (internal / view-as milestone, NOT partner-live).
5. Follow-on **Step 5.1 = AI_HOTEL_LAB_PROJECTION_ADMIN_STORE_1** (persisted revoke/refresh, audit history,
   stale/revoked packet handling, tests) — opened by lead after Step 5 merges.

## DONE RUBRIC

Met when: AC1-11 pass with named tests; G2/G3/G4 PASS; deputy-codex #3844 T# cases each mapped 1:1 to a
named test; post-deploy AC PASS on live Render; AC11 screenshots attached; `check_singletons.sh` green;
Steps 1-4 suites stay green. Citation table (AC#/T# → test) in the ship report.

**Builder:** b4. **Reply-to:** lead. Bus-post heartbeat on claim, gate-request on ship.
