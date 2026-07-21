# BRIEF: COCKPIT_BOOT_LAYOUT_RETRY_1 — cockpit boot must retry + self-heal, not die on one bad fetch

```yaml
brief_id: COCKPIT_BOOT_LAYOUT_RETRY_1
dispatched_by: lead
assigned_to: deputy-codex
repo: baker-master (local checkout; branch deputy/cockpit-boot-layout-retry-1 from origin/main)
status: PENDING — start AFTER COCKPIT_OPEN_NUDGE_SPLIT_1 ships (same file)
```

## Context

codex-arch audit #14272 P0/P1, lead-verified live 2026-07-21 morning (Lab /v2
AGENTS pane showed red "layout load failed — layout HTTP 503" + empty roster
during bus congestion): `boot()` in `scripts/cockpit_static/cockpit.js`
(~line 977) fetches `cockpit_layout.json` ONCE; on any failure it paints the
error and `return`s — no retry, no self-heal, dead until manual reload. Under
the current bus 503 storms this fires regularly.

### Problem
One transient 503 at load time bricks the Director-facing cockpit pane for the
whole session.

## Estimated time: ~1h
## Complexity: Low
## Prerequisites: COCKPIT_OPEN_NUDGE_SPLIT_1 merged (same file — avoid conflict). Coordinate with b2's LAB_UNIFY_THEME_COCKPIT_EXTENSION_1 (touches the same status surfaces): whichever merges second rebases; keep this change surface-agnostic by writing status through the existing health-line element reference, not a new one.

## Harness V2

- **Context Contract:** this brief; `cockpit.js` boot()/poll() (~955-995) + status-line surfaces (~195-260); reference retry pattern: brisen-lab `static/v2/skills.js` @d0fb907 (bounded retries + visibilitychange re-attempt, codex-gated).
- **Task class:** small-fix-production.
- **Done rubric:** Merged + resync `~/Library/Application Support/baker/cockpit/` + kickstart + live AC + POST_DEPLOY_AC_VERDICT. Writeback: lead registry note.
- **Gate plan:** self-test (fault-injection) → push → blocking codex gate on pushed SHA → lead merge → resync + kickstart → live AC → verdict.

## Implementation

1. Bounded retry in `boot()`: up to 2 retries with 1.5s/4s backoff on non-2xx / network error / timeout before showing the failure state (mirror the gated skills.js pattern incl. per-attempt AbortSignal timeout).
2. Self-heal while failed: after the failure state is shown, re-attempt boot on `visibilitychange` (gated on `visibilityState === "visible"`) AND on a slow interval (e.g. 60s) so an embedded, always-visible pane also recovers. Clear the interval on success. Boot-once guard — no duplicate sidebars/timers on recovery (assert single `buildSidebar()` effect).
3. Failure state text stays honest ("layout load failed — retrying") on whichever health-line element is current.

## Files Modified
- `scripts/cockpit_static/cockpit.js` (+ its tests if a JS/DOM harness exists; else extend the python route/static tests asserting the retry markers are served).

## Key Constraints
- No changes to poll(), wake, nudge, controller, or layout generation. Client-side boot resilience only.

## Verification
1. Fault-inject locally (serve 503 twice then 200): full cockpit renders after retries, single sidebar, single poll timer.
2. Hard-fail then recover: failure line shows; restore server; interval or visibilitychange self-heals without reload.
3. `git diff --stat`: cockpit.js + tests only.

## Quality Checkpoints
1. No duplicate timers/sidebars after recovery (boot-once proof).
2. Ship report + SHA on bus topic `cockpit/boot-retry`; codex gate on pushed SHA.
