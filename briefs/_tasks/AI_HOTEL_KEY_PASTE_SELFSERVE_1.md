# BRIEF: AI_HOTEL_KEY_PASTE_SELFSERVE_1

**Dispatched_by:** lead (AH1) — reply-to: lead
**Owner:** b1
**Priority:** HIGH (Director still hits empty Field Notes via the dashboard route)
**Task class:** small-fix-production
**Harness-V2:** applies (emit POST_DEPLOY_AC_VERDICT)
**Authority:** Tier-B design call (AH1) — deputy finding bus #3410

## Problem (structural gap remember-key can't close)
REMEMBER_KEY (PR #385/#386) cures the bookmarked-link case but NOT the dashboard route: the main dashboard's AI-Hotel link is `<a href="/static/ai-hotel.html" target=_blank>` with NO `?key=`, and the dashboard root holds no key to inject. When Director reaches Field Notes from a different surface (dashboard, Cowork app, phone) than the one where he opened the keyed link, `localStorage['aih.key']` doesn't cross → he sees the "Open with ?key=…" empty hint. The page can't self-heal because no surface in that path carries a key.

## Fix — self-service key entry on the empty state
When Field Notes render the keyless empty state (`ai-hotel.html`, the `nempty` hint at ~line 630), ADD a one-time key input so the page is self-service from ANY entry surface:
- Render an input (`type=password`, placeholder "Paste access key") + a "Load field notes" button below the existing hint text.
- On submit: `localStorage.setItem('aih.key', value.trim())` (try/catch, Safari-private safe), then re-run the captures fetch / `renderNotes()` so cards load immediately without a page reload.
- Reuse the existing `noteKey()` resolution (PR #385) so the stored key flows to every fetch.
- If the entered key is wrong (fetch 401), show a brief inline "key not accepted" message and keep the input visible — do not wipe the stored key silently into a broken state.
- Optional nicety: a small "Forget key" link when a key IS stored, for shared-device safety.

## Acceptance criteria
1. From a fresh surface with no stored key, the empty state shows a key input + load button.
2. Pasting the valid key loads all cards immediately (no full reload) and persists `aih.key`.
3. Reaching the page again on that surface (any route) loads cards from the stored key.
4. Wrong key → inline "not accepted" message, input stays, no crash, no silent broken state.
5. Existing keyed-URL path and bookmarked-link path (PR #385/#386) still work unchanged.
6. Safari private mode (localStorage throws) degrades gracefully — input still allows a session load.

## Kill criteria
1. Any regression to the working keyed-URL or remember-key paths = rollback.
2. Key echoed to console / DOM text / network beyond the X-Baker-Key fetch = block.

## Gates
- G1: pytest (no backend change expected; confirm no ai_hotel regression) + browser exercise of AC1–AC4.
- G2: /security-review (key-handling UI surface).
- G3: lead merges on G1+G2 clean (route to codex only if auth surface materially changes).
- Post-deploy: emit POST_DEPLOY_AC_VERDICT after live, exercising AC1–AC4 via Chrome MCP on prod.
