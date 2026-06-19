# BRIEF: AI_HOTEL_REMEMBER_KEY_1

**Dispatched_by:** lead (AH1) — reply-to: lead
**Owner:** b1
**Priority:** HIGH (Director-facing — empty-card incident root cause)
**Task class:** small-fix-production
**Harness-V2:** applies (production-facing static page; emit POST_DEPLOY_AC_VERDICT)
**Director GO:** 2026-06-19 (remember-key approach ratified)

## Problem
AI-Hotel dashboard + capture page source the access key ONLY from the `?key=` URL query param (`noteKey()` at `outputs/static/ai-hotel.html:613`; `KEY` from `URLSearchParams` at `outputs/static/ai-hotel-capture.html:256`). When Director opens a bookmarked/shared/nav link that dropped the key, fetch sends no `X-Baker-Key` → 401 → Field Notes render EMPTY. This is the confirmed root cause of his "can't see my card" report (deputy finding bus #3391). Data was always fine.

## Fix (remember-key)
Persist the key on first keyed visit; fall back to it when the URL has none. The page already uses `localStorage` for theme + sidebar width, so this is consistent.

**ai-hotel.html — `noteKey()` (line ~613):**
- If `?key=` present in URL: return it AND persist `localStorage.setItem('aih.key', key)` (wrap in try/catch like existing localStorage calls).
- If `?key=` absent: return `localStorage.getItem('aih.key') || ''`.
- All existing callers (lines 628, 650, 794, 818, 843) keep calling `noteKey()` unchanged.

**ai-hotel-capture.html — `KEY` resolution (line ~256):**
- Same pattern: read `params.get('key')`; if present persist to `localStorage['aih.key']`; if absent fall back to stored value. Re-evaluate the `nokey` gate (line 265) against the resolved key, not just the URL param — a remembered key should enable sending.

**Security hygiene (do this):** after caching a URL-supplied key, strip it from the visible URL via `history.replaceState({}, '', location.pathname)` so the plaintext key is not left in the address bar / browser history / referer. localStorage is per-origin and NOT shareable in a copied link — strictly better than key-in-URL.

## Acceptance criteria
1. Open page WITH `?key=bakerbhavanga` once → 14 cards load; key persisted to `localStorage['aih.key']`.
2. Then open the BARE link (no `?key=`) in same browser → cards STILL load (key from localStorage).
3. Capture page: after one keyed visit, bare-link visit re-enables the send/capture controls (nokey gate clears).
4. URL bar no longer shows `?key=...` after load (history.replaceState applied).
5. Fresh browser / cleared storage + bare link → still shows the existing "open with your access key" hint (no crash, graceful 401 empty-state preserved).
6. Wrong/stale stored key → 401 handled gracefully (existing empty-state), no console explosion.

## Kill criteria
1. Any path where a previously-working keyed session breaks = rollback.
2. Key logged to console or sent to any third party = block.
3. localStorage write without try/catch (Safari private mode throws) = block.

## Foot-guns
- Safari private mode throws on `localStorage.setItem` — MUST try/catch (existing code already does at lines 960/971).
- Don't break the legacy empty-state hint for genuinely keyless+never-visited users (AC5).
- `history.replaceState` must preserve any non-key query params if present (use a URLSearchParams delete of just `key`, then rebuild).

## Gates
- G1: pytest (no backend change expected; confirm no regression in ai_hotel suite) + manual browser exercise of AC1–AC6.
- G2: /security-review (key-handling change — confirm no new exposure).
- G3: lead routes to codex if security touches auth surface; else lead merges on G1+G2 clean.
- Post-deploy: emit POST_DEPLOY_AC_VERDICT v1 after live deploy, exercising AC1–AC4 on prod.
