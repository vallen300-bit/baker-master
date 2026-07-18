# B2 ship report — COCKPIT_CTX_SEVERITY_BY_VALUE (follow-up to COCKPIT_LAYOUT_REARRANGE_1)

- **Dispatch:** lead bus #12977 (2026-07-18) — Ruling 1, "the LAST item, then the seat closes."
- **Executor:** b2
- **Branch:** `b2/cockpit-ctx-severity-by-value` (off `main` @ `dec8ef31`, post PR #602 merge)
- **Report topic:** `ship/cockpit-ctx-severity-by-value`
- **Files:** `scripts/cockpit_static/cockpit.css`, `scripts/cockpit_static/cockpit.js`,
  `tests/test_cockpit_card_geometry.py` (css+js+test only — no backend/auth/JS-logic beyond the fill).

## What changed

The context bar's green→amber→red gradient was **width-scaled** — it rode the fill
element, so it ramped across each bar's own width and painted a **red tip on a
low-context row** (misleading telemetry on a Director-scan surface). Per Ruling 1
the colour is now **anchored to the value**: colour = `severity(context_pct)`.

Mechanism (css + one JS-set var, no colour math in JS):

- **cockpit.js** sets `--ctx-track-scale: (10000/pct)%` on each `.ctxfill`. The fill
  width still tracks `pct%`; `background-size` % is relative to the fill box, so a
  scale of `10000/pct` makes the gradient box span exactly **one full track**
  regardless of fill width.
- **cockpit.css** `.ctxfill` now uses `background-image` + `background-repeat: no-repeat`
  + `background-position: left center` + `background-size: var(--ctx-track-scale,100%) 100%`.
  The fill reveals the left `0..pct` slice of the full-track ramp → the colour at the
  fill's right edge is the ramp sampled at `pct`.

Result: a low-context row is green (no red tip); a near-full row's edge reaches red.
Auto-adapts to the flex-shrunk track width (incl. the ≤500px `.ctxbar` max-width:36px
media query) because the scale is a percentage, not a fixed px.

## Verification (done rubric)

- **pytest (literal):** `tests/test_cockpit_*.py` → **146 passed** (0 failed). Includes the
  new `test_context_gradient_is_anchored_to_value_not_width` guard + the retained
  `test_context_fill_is_severity_gradient`.
- **Fidelity test tightened:** new guard asserts `--ctx-track-scale` + `background-size`
  + `no-repeat` + `background-position: left` on `.ctxfill`, and that cockpit.js sets
  `--ctx-track-scale = (10000/pct)%`. Locks value-anchoring against regression.
- **Rendered-colour proof (Chrome, real DOM + canvas sample of the exact gradient at
  each value):** 8%→`79,181,74` green · 20%→green · 45%→green-yellow · 68%→`205,154,35`
  amber · 72%→amber · 85%→`235,104,60` red-orange · 95%→`248,81,73` red · 100%→red.
  Gradient box width == track width at every pct (severity-by-value confirmed).
- **Visual smoke:** `.smoke/ctx_severity_by_value.png` — eight rows 8→100%; low rows
  pure green, red only appears at the edge near full.
- **Static re-sync (AC step):** `cockpit.css` + `cockpit.js` synced to
  `~/Library/Application Support/baker/cockpit/static/`; served CSS confirmed carrying
  `--ctx-track-scale`. Director live preview updated.

## Codex gate

`codex-verify` on the tip — see bus thread. (Per Ruling 1: "codex on tip.")

## Housekeeping (Ruling: report not in PR #602)

`briefs/_reports/B2_COCKPIT_LAYOUT_REARRANGE_1_20260718.md` folded into this PR (docs-only).
