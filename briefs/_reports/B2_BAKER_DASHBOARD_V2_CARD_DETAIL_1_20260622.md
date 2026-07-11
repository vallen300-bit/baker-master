# Ship Report — BAKER_DASHBOARD_V2_CARD_DETAIL_1 (UI half)

**Builder:** B2
**Date:** 2026-06-22
**Branch:** `b2/baker-dashboard-v2-card-detail-1` (off `main` @ b91f0369)
**PR:** #416 — https://github.com/vallen300-bit/baker-master/pull/416
**Dispatch:** deputy GO bus #4062 (standby #4050); scope fork escalated #4065 → Option A ratified #4068 + codex-arch no-veto #4076.
**Pairs with:** b3 backend route PR #415 (`GET /api/verified-items/{id}`). This UI PR merges AFTER #415.
**Merge:** HELD — deputy is gate owner; G0→G3 must PASS first.

---

## Scope decision (escalated before building)

The brief presumed trusted Today cards existed in the UI to click — they did not. `/api/today` shipped backend-only (TODAY_1); the live dashboard still renders legacy `loadMorningBrief()`, and live `app.js` had **0** references to `/api/today`. The drawer had nothing to attach to, and the G3 gate + post-deploy AC both require clicking a real trusted card.

Escalated to deputy (#4065). **Option A** ratified (#4068, codex-arch no-veto #4076): fold a **minimal read-only** trusted Today V2 card list into this workstream as the drawer's click target — not the full Today redesign, not the legacy cutover (future `TODAY_UI_1`).

## What shipped (3 files, frontend only)

- **`outputs/static/app.js`** — self-contained IIFE:
  - `loadTodayTrusted()` — minimal read-only list from `GET /api/today?limit_per_lane=5`, lane-grouped (critical/promises/meetings/travel); compact cards show trusted-state badge + claim + why_matters + selected_reason; whole card is the click target. Empty/unavailable states degrade clean.
  - `openVerifiedItemDrawer(id)` — `GET /api/verified-items/{id}`; right-side drawer with loading / loaded / not-found(404|422) / error states. Bounded metadata only: why · why-selected · next/owner/due/confidence · verification + counterargument · context (matter/related/people) · evidence packet metadata · sanitized audit timeline.
  - Dismiss: Escape, scrim click, close button. Cards keyboard-activatable (Enter/Space). Returns focus to the originating card. All dynamic strings via `esc()`; body via `setSafeHTML()`.
- **`outputs/static/index.html`** — trusted-Today `<section>` mounted ABOVE the legacy morning grid (legacy untouched). `loadTodayTrusted()` wired into `init()` + `switchTab('morning-brief')`. Cache-bust: app.js v128→129, style.css v83→84.
- **`outputs/static/style.css`** — compact card + right-side drawer + scrim; mobile full-width ≤560px.

## Hard exclusions honored

No mutation controls · no verify/promote · no model calls · no raw source-body fetch (backend strips + length-bounds) · legacy morning-brief untouched (no cutover) · no migration · no backend change.

## Verify (Lesson #8 — exercised the flow, not just compile-clean)

- `node --check outputs/static/app.js` → **PASS**.
- **Browser fixture demo** via Chrome (fetch-layer stub — b3 route PR #415 is unmerged and `verified_items` is dormant in prod, so a live curl returns empty): loaded the real `app.js`/`style.css` with a `window.fetch` fixture:
  - List renders lane-grouped cards from `/api/today` payload (state badge + claim + why + reason). ✓
  - Clicking a card opens the drawer with full bounded content — evidence packet + audit timeline (ai→human transitions) + red counterargument. ✓
  - 404 → safe "Not available" state. ✓
  - Escape closes · reopen · scrim-click closes. ✓
  - Desktop + mobile (full-width, scannable) both clean; **0 console errors**. ✓
- **Live click-path AC is post-deploy** (per brief): after PR #415 merged + this merged + deploy + a seeded `verified_items` row, curl `/api/today` + `/api/verified-items/{id}` and click a real card. Method noted honestly.

## Gates requested

G0 codex · G1 deputy · G2 security (raw-body leakage + auth) · G3 cross-layer (route + browser click path). Gate-request posted to deputy (bus #4077).

---

## Rework cycle 1 — G0 F1 [HIGH] XSS fix (@ 079e6411)

deputy-codex G0 = REQUEST_CHANGES (#4082/#4084). F1 [HIGH]: card `data-vi-id` used `esc(String(id))`, but `esc()` is a text-node escaper that does NOT escape `"` — an id like `11" onmouseover="alert(1)` broke out of the attribute. `/api/today` ids aren't guaranteed quote-free at the JS layer → exploitable.

**Fix** (no innerHTML attribute sink at all): cards now built via `createElement`; id set via `el.dataset.viId` (DOM API, never HTML-parsed); inner content via `setSafeHTML` of esc'd TEXT-context strings only. Listeners use the closured id; fetch already `encodeURIComponent`s it. No server value reaches any HTML attribute sink. Audited other attribute interpolations — `role`/`tabindex` static; `_stateBadge` class is static class names only. `data-vi-id` was the only server-valued attribute.

**Regression probe** (Chrome fixture, id = `11" onmouseover="...` + claim with `<img onerror>`): card has NO event attribute (attrs = class/role/tabindex/data-vi-id); evil string stored inert as data; neither payload fired; click→drawer still opens; 0 XSS. `node --check` PASS. Cache-bust app.js?v 129→130 (b1 #417 takes 129). Re-requested G0 (bus #4086).
