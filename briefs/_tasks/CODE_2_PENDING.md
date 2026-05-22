---
status: pending
brief: briefs/BRIEF_BRISEN_LAB_DESK_CARD_VISUAL_DIFFERENTIATION_1.md
brief_id: BRISEN_LAB_DESK_CARD_VISUAL_DIFFERENTIATION_1
target_repo: brisen-lab
matter_slug: baker-internal
dispatched_at: 2026-05-22T17:05:00Z
dispatched_by: lead
target: b2
working_branch: b2/brisen-lab-desk-card-visual-1
working_dir: ~/bm-b2-brisen-lab
reply_to: lead
deadline: 2026-05-23T17:00:00Z
priority: tier-b
director_auth: 2026-05-22 chat — "go" on §X batch-ratification (Group A item 22)
prior_mailbox_state: superseded — previous CODE_2_PENDING.md was WAHA_OUTBOUND_CAPTURE_1 COMPLETE (PR #235 shipped 2026-05-21T07:30:00Z). b2 idle since.
gate_chain:
  gate_1_static: REQUIRED (AH1 fires feature-dev:code-reviewer)
  gate_2_security_review: SKIPPABLE — pure CSS in brisen-lab; AH1 judgment
  gate_3_cross_lane_architecture: REQUIRED (picker-architect — UI visual change on Director-facing surface)
  gate_4_2nd_pass_code_reviewer: SKIPPABLE — does not trigger criteria 1-7 (CSS-only, no auth / no DB / no concurrency / no external surface / not >2-week brief / not multi-repo). AH1 may fire anyway if visual judgment requires second eye.
estimated_effort: 30-45 min (read brief + CSS + screenshot)
ui_surface_prebrief: completed at brief authoring time (brief §Surface contract block satisfies)
---

# CODE_2_PENDING — BRISEN_LAB_DESK_CARD_VISUAL_DIFFERENTIATION_1 — 2026-05-22

**Brief:** `briefs/BRIEF_BRISEN_LAB_DESK_CARD_VISUAL_DIFFERENTIATION_1.md` (commit `d1412bb` on main, PR #243 merged)
**Working branch:** `b2/brisen-lab-desk-card-visual-1` (off origin/main in brisen-lab repo)
**Target repo:** `brisen-lab` (NOT baker-master). Clone at `~/bm-b2-brisen-lab/`.
**Pre-requisites:** none.

## Bottom line

CSS-only ~15 LOC change in `brisen-lab/static/styles.css`. Add `.card-desk` rules so desk cards (hag-desk, researcher) visibly differ from worker cards (b1-b4) while preserving the left-edge status indicator. Director ratified Option A-revised 2026-05-22 afternoon.

## Pre-flight (mandatory before edit)

1. `cd ~/bm-b2-brisen-lab && git fetch origin main` — sync.
2. Check current local state: `git status -sb`. If on a stale branch (e.g. `b2/brisen-lab-sse-daemon-last-seen-fix-1`), `git checkout main && git pull --ff-only origin main`. Discard or stash any uncommitted file local changes before checkout.
3. `git checkout -b b2/brisen-lab-desk-card-visual-1`

## Implementation

Read the full brief at `~/bm-b2/briefs/BRIEF_BRISEN_LAB_DESK_CARD_VISUAL_DIFFERENTIATION_1.md` for full spec.

Patch summary: add new `.card-desk` block immediately after the `data-card-state` rules in `brisen-lab/static/styles.css` (currently lines 233-254). Recommended block:

```css
/* Desk cards (hag-desk, researcher, future AO/MOVIE/BB) — visual differentiation */
.card-desk {
  border-top: 4px solid var(--desk-accent, #5a7a5a);
  background: color-mix(in srgb, var(--panel) 95%, var(--desk-accent, #5a7a5a) 5%);
}
```

You may pick a different muted-sage / warm-beige accent if WCAG AA contrast on `var(--text)` is tighter with another value. Document the choice in the PR description.

## Acceptance criteria

Per brief §Acceptance criteria — AC1 (top-edge accent) + AC2 (soft tint) + AC3 (left edge preserved) + AC4 (hover preserved) + AC5 (visual smoke screenshot) + AC6 (no JS / no HTML / no Python diff).

## Ship gate

- Literal `pytest` green in brisen-lab repo (verify no test regression — CSS-only diff should not affect any test).
- Screenshot in PR description showing hag-desk card + researcher card vs b1-b4 cards side-by-side on the live or local-preview brisen-lab UI.

## Reporting (bus reply-to-sender)

On PR open, bus-post `lead` per `dispatched_by`:

```bash
BAKER_ROLE=b2 ~/bm-b2/scripts/bus_post.sh lead \
  "ship/brisen-lab-desk-card-visual-1 — PR #<N> open in brisen-lab; CSS-only +<X> LOC; screenshot in PR; awaiting AH1+architect gate chain (gates 1+3 required; 2+4 skippable per mailbox)." \
  ship/brisen-lab-desk-card-visual-1
```

`lead` (AH1-Terminal) handles gate orchestration + merge sequence.

## Heartbeat cadence (per §B-code stall chase — Director-ratified 2026-05-05)

Minimum every 12h while actively building. Two consecutive 12h misses → `lead` auto-surfaces stall to Director. Given the ~30-45 min scope here, expect single completion event, not multiple heartbeats.
