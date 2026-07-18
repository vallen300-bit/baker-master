# B2 ship report — COCKPIT_LAYOUT_REARRANGE_1

- **Brief:** `briefs/BRIEF_COCKPIT_LAYOUT_REARRANGE_1.md` (deputy-authored, lead-verified)
- **Dispatch:** lead bus #12957 (2026-07-18)
- **Executor:** b2
- **Branch:** `lead/cockpit-layout-rearrange-wip` (took over @019bb602; did NOT branch from main, per brief)
- **Ship commit:** `0f1b026b`
- **PR:** #602 → main (awaiting codex gate close + lead line-read + merge; B2 does not self-merge)
- **Report topic:** `gates/cockpit-layout-rearrange-1`

## What shipped

Finished the Director's cockpit layout to mock-v3 fidelity. The WIP already carried the
summary bar, roster/sync notes, CSS regroup, and manifest tweak; this commit closes the
remaining fidelity gaps and restores a ratified invariant the regroup had broken.

Only **cockpit.css** needed a change among the 3 static files (index.html + cockpit.js were
already correct on the WIP). Changes:

1. **Context line green→amber→red gradient** (`.r-ctx .ctxfill`) — was a flat blue bar; now
   the mock-v3 severity ramp `linear-gradient(90deg,#3fb950,#d29922 70%,#f85149 92%)`.
2. **App/Cowork rows recessed** (`.row.app`) — inner shadow + darker fill, matching the
   mock's `.card.app` inset treatment, distinct from driveable rows.
3. **Thin-row geometry restored** — `.row` is a standalone rule with a literal 5-column
   template (mirrors `:root --row-columns`, kept in sync so the `.fleet-columns` header
   stays aligned) and `min-height: 26px`. The WIP regroup had hidden the template behind a
   `var()` and bumped height to 35px, breaking the Director #12800 `<=30` one-screen guard.

Tests: added two mock-v3 fidelity guards in `tests/test_cockpit_card_geometry.py` (severity
gradient; recessed `.row.app` inset shadow).

## Verification (done rubric)

- **pytest (literal):** `tests/test_cockpit_*.py` → **143 passed** (0 failed). Includes the two
  new fidelity guards + the restored geometry/contrast guards.
- **Manifest regen:** `python scripts/generate_cockpit_manifest.py --write` → **zero drift**
  (28/28 eligible, 0 unresolved, librarian removed). WIP regen + reconciliation note current;
  never hand-edited.
- **Static re-sync (mandatory AC step):**
  `rsync -a --delete scripts/cockpit_static/ "$HOME/Library/Application Support/baker/cockpit/static/"`
  — done; served CSS confirmed carrying the gradient + thin rows. Director's live preview updated.
- **Visual smoke:** self-contained preview linking the re-synced `cockpit.css` (secret-safe —
  avoids exposing the loopback Basic-auth credential). Screenshot: `.smoke/cockpit_layout_rearrange_1_fidelity.png`.
  Confirms: green→amber→red context bars by pct, recessed App/Cowork/Service rows, thin
  one-screen rows, no AG numbers, APP/SERVICE labels, amber + unread badge, Needs-GO + GO button.
- **Mock relocated:** `COCKPIT_LAYOUT_REARRANGE_MOCK_V3.html` → `briefs/_plans/` (`git mv`).

## Fidelity checklist (against the mock legend)

| Item | Status |
|---|---|
| No AG numbers | PASS |
| Narrower rows, whole fleet one scan | PASS (min-height 26px) |
| Cowork/APP recessed w/ inner shadow | PASS (new `.row.app`) |
| Context line green→amber→red by pct | PASS (mock-faithful — see open decision below) |
| Amber + count + message IDs in panel | PASS (pre-existing D5/D9) |
| Click → `check bus #id` wake | PASS (pre-existing D6) |
| Codex Arch = status-only APP in Tower | PASS (verify-only, cockpit_layout.json on main) |
| Interns Deep55 / Clerk Qwen / Clerk Haiku | PASS (verify-only) |
| Cortex in Engineering (SERVICE) | PASS (verify-only) |

## Codex gate

`codex-verify` (gpt-5.6-luna) on commit `0f1b026b`: **PASS-with-notes**. Verified clean:
geometry, WCAG AA (`.row.app` text ≈15.8:1 / muted ≈9.6:1), header/data column alignment,
scope, no JS/backend/auth touched. Two notes → both surfaced to lead (below), not averaged.

## Open decisions for lead (surfaced, not blocking merge decision — lead's call)

1. **Context gradient — mock-faithful vs severity-by-value.** Codex observed the gradient
   rides the width-scaled fill, so it ramps green→red across each bar's own width rather than
   coloring by the true context value (a low-context row shows a red tip). **The mock — the
   brief's declared design source of truth — paints the gradient on the width-scaled fill,
   and the Director visually approved exactly that.** Anchoring the ramp to the full track
   (so color = severity) is a small CSS+JS follow-up but is a redesign vs the approved mock,
   which the brief says not to improvise. Shipped the mock-faithful version. If the Director
   wants severity-by-value, I'll do the follow-up (CSS + JS + tighten the test).

2. **`#roster-note` count: 43 vs 28.** Brief checklist says roster-note should show 28 (the
   launchable-manifest count). The page renders **43 cards** and `renderSummary()` correctly
   sets roster-note to `cards.length` (43), which matches the mock exactly (6+9+11+9+5+3=43).
   28 is a different set (launchable tmux seats). Kept 43 (mock-faithful) rather than make the
   label lie about what's on screen. Flagging the brief's imprecision.

3. **Cache-bust (Codex SUGGESTION).** `index.html` uses no `?v=N` on any asset (pre-existing
   convention gap, not a regression). Cockpit is served via `rsync --delete` mirror + Director
   hard-refresh, so lessons §4's CDN-cache rationale doesn't apply. Left as-is; noting it.

## Gate handoff

PR #602 is ready for lead's line-read + merge. Per the gate plan: after merge, the served dir
is already re-synced (Director preview live); the POST_DEPLOY_AC_VERDICT stands as the
fidelity checklist above (all PASS, screenshot attached).
