# B4 ship report — AI_HOTEL_LAB_COCKPIT_UI_1 (Sprint-0 Step 5)

- **Date:** 2026-06-22
- **Dispatched by:** lead (bus #3847); rubric folded #3853 (deputy-codex #3849); admin ruling folded #3874 (codex-arch #3873)
- **Branch:** `b4/ai-hotel-lab-cockpit-ui-1` (rebased on main bdd34f0)
- **PR:** (to open) — **MERGE HELD** per gate plan
- **Commits:** 60036a4 (backend foundation), cdcdd40 (endpoints), 5c10331 (test matrix + ruling), 9e25768 (Pattern B SPA)
- **Reply-to:** lead (bus); cc deputy-codex for G2.

## What shipped

A new auth-gated cockpit at `/ai-hotel-lab` served from `outputs/dashboard.py` via
`outputs/ai_hotel_lab.py`. The role selector resolves **server-side**; partner views
are built by `policy.projection.view_as` (byte-identical external packet) and Brisen by
`build_internal_preview_packet`. No second permission engine; the browser never receives
raw rows for an external role. Dynamic UI is rendered with DOM API + `textContent` only
(no `innerHTML` sink — no XSS surface). Curated AI-Hotel evidence seed runs through the
REAL engine/projector; connector liveness is reported honestly (WIRED/PARTIAL/GAP),
nothing faked. Framed as internal cockpit / view-as milestone (not partner-live).

## AC + threat citation table (AC#/T# → named test)

| Ref | Where enforced | Named test (tests/test_ai_hotel_cockpit.py) |
|---|---|---|
| AC1 Pattern-B hierarchy | raw=amber/internal, verified=distinct, restrained light-mode | test_cockpit_page_renders_html; test_t10_* |
| AC2 packets server-side, no raw rows | view_as / build_internal_preview_packet server-side | test_ac2_brisen_internal_preview_has_full_fields_but_externals_do_not; test_t1_* |
| AC3 role switch clears prior state, no leak | server-side resolve; UI clears on role switch | test_ac3_unknown_role_fails_closed; test_t1_*; test_t2_* |
| AC4 raw inbox internal-only | /api/raw-signals returns [] for external | test_t7_raw_signal_inbox_empty_for_external |
| AC5 verified ≠ raw, lifecycle-promoted | /api/evidence promoted states only | test_t10_verified_lane_excludes_raw_internal |
| AC6 search coverage honest | /api/search coverage WIRED/GAP | test_t8_search_coverage_marks_gaps_honestly_internal |
| AC7 projection controls + audit states | approve live; revoke/refresh disabled w/ exact reason; audit drawer | test_ac7_revoke_refresh_return_step51_reason; test_ac7_approve_is_live_and_audited |
| AC8 first-screen status | first-screen stats from backend packet | test_all_four_role_views_render_without_error |
| AC9 responsive | CSS @media stacks nav/roles/search | (visual — AC11 post-deploy) |
| AC10 endpoint payload tests | all tests assert on endpoint JSON, not template | entire suite (41 tests) |
| AC11 4-role browser proof | — | **post-deploy step 5 — see Open item** |
| T1 raw-text leak | external payloads scanned for internal secrets | test_t1_no_raw_text_leak_to_external |
| T2 metadata leak | external counts content-free; generic empty state | test_t2_external_packet_counts_are_content_free |
| T3 cross-role bleed | sections + audit absent across roles | test_t3_no_cross_role_section_bleed; test_t3_cross_role_audit_is_absent |
| T4 stale/revoked persistence | revoked + stale external items absent | test_t4_revoked_item_absent_from_external_packet; test_t4_stale_external_item_not_actionable |
| T5 client-side bypass | external items carry allowlist keys only | test_t5_external_items_only_carry_allowlist_keys |
| T6 second permission engine | packet == canonical view_as output | test_t6_packet_is_byte_identical_to_canonical_view_as |
| T7 direct raw fetch | raw inbox empty; sources no internal ids | test_t7_raw_signal_inbox_empty_for_external; test_t7_external_sources_have_no_internal_ids |
| T8 search fabrication | gaps honest; zero ≠ synthetic | test_t8_search_results_never_fabricated |
| T9 source-hint leak | roadmap empty; no never_external/ids/gap reasons | test_t9_external_roadmap_is_empty; test_t9_external_sources_expose_no_never_external_or_gap_hint |
| T10 hierarchy misread | raw excluded from verified lane | test_t10_verified_lane_excludes_raw_internal; test_t10_raw_signal_only_in_raw_state |
| T11 responsive regression | CSS @media; same data boundary | (visual — AC11 post-deploy) |
| T12 proof gap | 4-role browser evidence | **post-deploy step 5 — see Open item** |

## G1 self-test (literal)

- `tests/test_ai_hotel_cockpit.py`: **41 passed**.
- Steps 1-4 suites (`test_policy_core`, `test_partner_projection`, `test_search_routing`): **231 passed**.
- `scripts/check_singletons.sh`: **OK, no violations**.
- All 4 role views render server-side; page route returns 200 HTML; no `.innerHTML` in served body.

## Open item — escalation to lead (blocks browser AC11 + Director/partner browser access)

The cockpit router is gated by `verify_ai_hotel_read_access`, which accepts the master
`X-Baker-Key` header OR the `aih_session` cookie. But that cookie is **path-scoped to
`/api/ai-hotel`** (set at the existing PIN-login endpoint), so a browser navigating to
`/ai-hotel-lab` does **not** send it — only the master-key header authorizes the page,
and a browser navigation cannot set that header. Consequence: the page is reachable by
API/header clients (and tests) but not by a plain browser session, which blocks (a) the
AC11 4-role browser screenshots and (b) real Director/partner browser use.

This needs a decision (not a builder guess — two valid options):
- A.1: widen the `aih_session` cookie path to cover `/ai-hotel-lab` (and add a cockpit
  PIN-login entry), reusing the existing scoped-session model.
- A.2: give the cockpit its own auth entry/cookie path.

Per gate plan, AC11 browser screenshots + T11/T12 visual proof land at **step 5
(post-deploy on live Render)**; the auth decision above is the prerequisite for producing
them (locally or live). Backend + tests + UI are otherwise gate-ready.

## G2 rework round 1 (deputy-codex #3879 REQUEST_CHANGES → fixed)

**Blocker 1 (HIGH, T2/T9) — external search leaked `zero_result_route`.** `get_search`
returned the internal zero-result route (`source_gap_unassigned_review`) to external
roles. Fixed at the cockpit API boundary: `zero_result_route` is now emitted only for
internal Brisen; external roles get `null` (generic empty state, Step-4 F1 invariant).
Tests: `test_t9_external_search_has_no_zero_result_route_or_gap_hint` (all 3 external
roles), `test_internal_search_keeps_zero_result_route_for_triage`.

**Blocker 2 (HIGH, T12/AC11 auth) — implemented A.1 (lead #3878).** The `aih_session`
cookie path is widened `"/api/ai-hotel"` → `"/"` so one signed session covers the
cockpit page + its API. The cockpit page route (now in dashboard.py, not the gated
router) does non-raising auth: authed session/key → cockpit; unauthenticated browser →
PIN-login challenge (reuses `/api/ai-hotel/pin-auth`), never the cockpit, never 500.
`/ai-hotel-lab/api/*` stay hard-gated (401). Test:
`test_unauthenticated_browser_is_challenged_not_served`. AC11 4-role browser/network
screenshots are produced **post-deploy on live Render** (lead #3881), now unblocked.

Re-verify: `tests/test_ai_hotel_cockpit.py` **46 passed**; Steps 1-4 **231 passed**;
singletons OK.

## Done-state

Harness-done (this PR) = backend + UI + 41 named tests green + singletons + Steps 1-4
green. Arc-done = G2/G3/G4 PASS + post-deploy AC + AC11 4-role screenshots — separate,
not claimed here.
