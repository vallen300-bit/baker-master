# B3 Completion Report — DASHBOARD_MUTATION_FAILSAFE_1

- **Brief:** `briefs/BRIEF_DASHBOARD_MUTATION_FAILSAFE_1.md` (v2, codex-arch G0 PASS #1643)
- **Dispatched by:** cowork-ah1 (bus #1654)
- **Branch:** `b3/dashboard-mutation-failsafe-1` (commit 9aa01ad)
- **PR:** #281 (baker-master, base main) — **NOT merged** (AH gate)
- **Repo:** baker-master `outputs/static/app.js` + `outputs/static/index.html`
- **Date:** 2026-06-02

## What shipped
Frontend reliability fix for ~21 cockpit mutation action buttons that were fire-and-forget (silent failure) and applied optimistic UI without checking `resp.ok` (false success).

- **Fix 1** — `_showToast(msg, type)` backward-compatible red `error` variant.
- **Fix 2** — centralized `_mutate(url, opts, onOk, onErr)`: confirmed-`resp.ok` gate + HTTP-200-`{error}`-as-failure gate (codex-arch fold); `onOk` runs only on confirmed success.
- **Fix 3** — 19 action-button sites migrated one-at-a-time, optimistic UI moved into `onOk`; both `.then` and `await` styles. Body-bearing mutations (reschedule `{due_date}`, from-alert `{alert_id}`, feedback payloads) preserved. `d.error`-parsing handlers (`_triagePromoteCritical`/`_triageAddToPromised`) preserved (now error-styled).
- Inline `resp.ok` gates on await-sequential bespoke-UX sites: `_travelSetStatus`, `_runBrowserTask`.
- Left as-is (already gated): `bulkDismissSelected`, `bulkDismissByTier`, proposal bulk-dismiss, `_dismissCoolingContact`.
- `index.html` cache-bust `?v=122 → ?v=123`.

## Verification
- `node --check outputs/static/app.js` — clean.
- node harness on `_mutate`: happy-200 / 500 / 200+`{error}` / offline-reject → `onOk` fires only on confirmed 2xx+no-error in all four; failures = red toast + `onErr`, no false success. (Core logic proof.)
- **Deferred to reviewers + post-deploy AC:** live desktop + iPhone PWA failed-mutation exercise — not deployed yet, could not run live. Per brief, G1/G3 reviewers MUST confirm.

## Done-rubric
- **Task class:** frontend reliability.
- **Terminal state:** a failed mutation (network/500/200+`{error}`) no longer false-succeeds — card stays + red error toast; happy-path optimistic UI unchanged. Verified at logic level (node harness); live behavioral verification is the gate/post-deploy step.

## Gates
G1 (cowork-ah1 fold) → G3 (deputy). G2 `/security-review` NOT required (frontend-only; codex-arch concurred).
