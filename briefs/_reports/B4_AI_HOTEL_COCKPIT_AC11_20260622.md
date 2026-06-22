# B4 — AI_HOTEL_LAB_COCKPIT_UI_1 AC11 evidence (post-deploy, live Render)

- **Date:** 2026-06-22
- **Surface:** https://baker-master.onrender.com/ai-hotel-lab (live, commit 0e40863 on main)
- **Auth:** A.1 PIN-login (POST /api/ai-hotel/pin-auth → signed `aih_session` cookie, path `/`, HTTPS).
- **Capture tool:** Chrome (logged-in debug browser) via Chrome MCP.

## AC11 — 4-role browser screenshots (attached)

| Role | File | Viewing-as label (live) | Sections shown (live) |
|---|---|---|---|
| Brisen internal | `ac11_screenshots/01_brisen_internal.png` | Brisen internal preview | all 6 (NVIDIA, MOHG, market, site, financing, marketing) · 6 visible |
| NVIDIA | `ac11_screenshots/02_nvidia.png` | NVIDIA — AI-hospitality lighthouse | nvidia_lighthouse ×2 + marketing_pr (public) · "view-as preview (not partner-live)" |
| MOHG | `ac11_screenshots/03_mohg.png` | Mandarin Oriental — ops / brand standards | mandarin_oriental_operator_logic + marketing_pr |
| Venue Owner | `ac11_screenshots/04_venue_owner.png` | Venue owner — site diligence | santa_clara_site_thesis + marketing_pr |

## Forbidden-token scan (DOM + network, live)

Both the rendered DOM (`document.body.innerText`) and the raw API responses over the
wire were scanned for internal secrets — raw_body markers, internal titles, owner
identity, internal source ids (`baker-memory`/`vault-rooms`/`src-`), gap reasons,
financing/strategy claims, routing internals (`route_target`/`route_reason`/
`policy_reason_code`/`source_gap`/`unassigned_review`/`rule 1`/`keyword match`), the
internal redaction reason, AND cross-role section names (each external role checked
against the OTHER roles' sections).

| Role | DOM forbidden hits | Wire forbidden hits (packet + raw-signals + sources + roadmap + evidence + search) |
|---|---|---|
| NVIDIA | **[] none** | **[] none** (5245 bytes scanned) |
| MOHG | **[] none** | **[] none** (3748 bytes scanned) |
| Venue Owner | **[] none** | **[] none** (3712 bytes scanned) |

Cross-role isolation confirmed live: NVIDIA shows no MOHG/venue sections; MOHG no
NVIDIA/venue; venue no NVIDIA/MOHG. External `raw-signals` empty, `roadmap` empty,
search `zero_result_route` null. Brisen-confidential financing item never appears in
any external view. Unauthenticated `GET /ai-hotel-lab` returns the PIN challenge (401),
never the cockpit.

**AC11 result: PASS.** Combined with the POST_DEPLOY_AC_VERDICT v1 (ac_result PASS,
bus #3909/#3910), Step 5 done-rubric is met.
