---
brief_id: BRISEN_LAB_DESK_CARD_VISUAL_DIFFERENTIATION_1
authored_by: lead (AH1-Terminal)
authored_at: 2026-05-22T17:00:00Z
matter_slug: baker-internal
target_repo: brisen-lab
priority: tier-b
tier: B
director_ratified: 2026-05-22 afternoon (Option A-revised — 3-4px top-edge accent + soft tint on .card-desk)
reply_to: lead
---

# BRIEF_BRISEN_LAB_DESK_CARD_VISUAL_DIFFERENTIATION_1

## Bottom line

Desk cards (`.card-desk` — hag-desk, researcher, future AO/MOVIE/BB) on Brisen Lab currently look identical to worker cards (b1-b4). Add visual differentiation via top-edge accent + soft background tint while preserving the left edge for dynamic status (`data-card-state="red|yellow|green|grey"`).

Pure CSS change. No JS. No bus.py. No app.py. Single PR.

## Context

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** click a desk card on Brisen Lab dashboard to open its detail panel (EXISTING behavior — this brief does NOT change the click action; visual styling only).
2. **Backend route:** N/A — no new route. Existing card click handler in `static/app.js` is untouched.
3. **Endpoint contract:** N/A — no new endpoint. Brief is CSS-only.
4. **State location:** N/A — no new state read or write. Existing `data-card-state` attribute drives left-edge color and is not modified.
5. **UI repo (= state repo):** `brisen-lab` — surface: lab UI dashboard. State stays in `brisen-lab` server-side; CSS-only diff.
6. **Director surface preference:** asked + ratified 2026-05-22 afternoon — Option A-revised (top-edge accent + soft tint on `.card-desk`). Left edge stays sacred for status. No alternative surface considered (this is visual-differentiation only on existing surface).
7. **Gate-1+2 reviewer instruction:** "Reviewers MUST load https://brisen-lab.onrender.com (or local preview) after deploy + visually confirm desk cards (hag-desk + researcher) differ from worker cards (b1-b4). Code-shape review (CSS validity, contrast ratio) is necessary but NOT sufficient — load the live UI."

## Director ratification

2026-05-22 afternoon — "Option A is a good one" — ratifying revised design: 3-4px top-edge accent + soft muted-sage or warm-beige background tint on `.card-desk`. Left edge stays sacred for status indicator.

## Scope

**In scope:**
- `static/styles.css` — add `.card-desk` rules (top-edge accent + soft tint)

**Out of scope:**
- `app.js`, `app.py`, `bus.py`, `static/index.html` — no markup or behavior changes
- `.card-worker` styling — workers stay as-is (left-edge status indicator unchanged)

## Acceptance criteria

**AC1 — Top-edge accent on `.card-desk`.**
Add 3-4px top border with a muted color distinct from left-edge status palette. Recommend muted sage (`#5a7a5a` or similar) or warm beige (`#a89968`). Pick one; AH2/picker-architect can fold on review.

**AC2 — Soft background tint on `.card-desk`.**
Background gets a very low-saturation tint (~3-5%) of the same accent hue. Stays subtle against `var(--panel)`. Must not reduce text contrast below WCAG AA on the existing `var(--text)` foreground.

**AC3 — Left edge preserved.**
`.card-desk` MUST inherit the existing `border-left: 4px solid var(--card-edge, var(--border))` from `.card`. Status indicator (`data-card-state`) must continue to drive the left-edge color exactly as it does today on worker cards.

**AC4 — Hover state preserved.**
`.card-desk:hover` must retain the existing `.card:hover { border-color: #58a6ff; }` behavior. If a separate `.card-desk:hover` is added, it must not regress the hover affordance.

**AC5 — Visual smoke.**
After deploy, hag-desk + researcher cards on https://brisen-lab.onrender.com must visibly differ from b1-b4 cards. Screenshot in PR description.

**AC6 — No JS or HTML diff.**
`static/app.js`, `static/index.html`, and any Python file must be unchanged in the PR diff. CSS-only.

## Implementation notes

Current `.card` block at `static/styles.css:233-254`:

```css
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-left: 4px solid var(--card-edge, var(--border));
  border-radius: 8px;
  padding: 16px;
  cursor: pointer;
  transition: border-color 120ms;
}

.card:hover { border-color: #58a6ff; }

.card[data-card-state="red"]    { --card-edge: #f85149; }
.card[data-card-state="yellow"] { --card-edge: #d29922; }
.card[data-card-state="green"]  { --card-edge: #2ea043; }
.card[data-card-state="grey"]   { --card-edge: #30363d; }
```

Add new block (placement: immediately after the `data-card-state` rules):

```css
/* Desk cards (hag-desk, researcher, future AO/MOVIE/BB) — visual differentiation */
.card-desk {
  border-top: 4px solid var(--desk-accent, #5a7a5a);
  background: color-mix(in srgb, var(--panel) 95%, var(--desk-accent, #5a7a5a) 5%);
}
```

(Pick a single accent color; do NOT introduce per-desk theming in v1.)

## Test plan

- Visual smoke on staging deploy: hag-desk + researcher cards visibly differ from b1-b4.
- DOM: `.card-desk` selector matches the desk cards (verify via DevTools).
- Left-edge: change `data-card-state` on hag-desk card via DevTools; verify left-edge color updates as before.
- Hover: hover over hag-desk card; border-color goes to `#58a6ff` as before.

## Ship gate

- Literal `pytest` green (no Python diff expected, so no test regression).
- Visual smoke screenshot in PR description.

## Gate-1 + Gate-2 reviewer instructions

Reviewers MUST load https://brisen-lab.onrender.com (or local preview at port 8080) after deploy + visually confirm desk cards (hag-desk + researcher) differ from worker cards (b1-b4). Code-shape review (CSS validity, WCAG AA contrast ratio on the tinted background) is necessary but NOT sufficient — the live UI must be loaded.

## Reporting

Bus-post `lead` on PR open. Reply target per dispatched_by field in mailbox UPDATE.
