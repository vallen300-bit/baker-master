---
status: PENDING
brief: briefs/BRIEF_FLEET_ROADMAP_HTML_RENDER_1.md
trigger_class: MEDIUM
dispatched_at: 2026-05-03T22:30:00Z
dispatched_by: ai-head-a
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: null
pr: null
autopoll_eligible: false
---

# DISPATCH: B3 → BRIEF_FLEET_ROADMAP_HTML_RENDER_1 (V0.3.1)

**Brief:** `briefs/BRIEF_FLEET_ROADMAP_HTML_RENDER_1.md` (V0.3.1, ship-ready after 3 architect-reviewer passes)

**Note:** Overwrites prior CODE_3 closure on `BRIEF_CHROME_DEBUG_PERMANENT_1` (B3 shipped 2026-05-02; ship report archived at `briefs/_reports/B3_chrome_debug_permanent_1_20260502.md`).

## Why you (B3)

You shipped every prior render-script work on baker-master:
- PR #101 — `roadmap: render script + V4 HTML + brisen-docs index updates`
- PR #148 — `docs(roadmap): re-render V4 HTML from YAML — Step 29 closure`
- PR #121 / #118 / #115 / #113 — successive re-renders.

V5 dispatch is an extension of patterns you already own (`render_v5(yml)` alongside renamed `render_v4`).

## Pass-history convergence (architect-reviewer code-architecture-reviewer)

- Pass 1: 3 Critical / 3 High / 5 Medium / 5 Low — V0.2 patch
- Pass 2: 0 Critical / 2 High / 1 Medium / 3 Low — V0.3 patch
- Pass 3: 0 Critical / 0 High / 0 Medium / 2 Low (acceptable, polished into V0.3.1)
- Architect's final verdict at V0.3.1: **ship-ready**

## Read order (recommended)

1. **§Version log + V0.3.x patch history** — explains WHY each constraint exists; many are responses to specific architect findings.
2. **§Solution → Files to modify** — 4 files across 2 repos (baker-vault YAML + baker-master renderer/tests/HTML).
3. **§YAML schema v5 (target)** — full schema example. Note: `target:` and `backlog:` are PRESERVED FROM V4 verbatim (not renamed, not moved).
4. **§Strict schema rules (v5)** — required vs SOFT (render-with-fallback) fields. `target`/`backlog`/`cut_at`/etc. are SOFT.
5. **§Renderer changes** — §1 dispatch + §2 `render_v4` rename + §3 `render_v5` layout + §3a html-escape + §3b sort.
6. **§Tests** — 12 test functions; copy-paste runnable.
7. **§Acceptance criteria** — 9 ACs. AC #6 corrects the upstream spec's GitHub-Actions-rebuild claim (no GHA in baker-master; rebuild is manual + Render auto-deploy on push).
8. **§Cross-repo PR coordination** — paired PRs, baker-vault YAML PR merges FIRST.

## Constraints

- **MEDIUM trigger class. B1 second-pair-of-eyes review on the baker-master PR before merge** (RA-24 — Director-facing surface). `/security-review` NOT required.
- **2 paired PRs.** Branch in BOTH repos: `b3/fleet-roadmap-html-render-1`. Open baker-vault PR (YAML migration) FIRST; wait for AH1 merge; pull merged YAML locally; then open baker-master PR (renderer + tests + regenerated HTML).
- **Public function name `render` MUST be preserved** — existing tests + callers depend on it. New code: `render` (entry) → `render_v4` / `render_v5` (private).
- **No new CSS color system.** Reuse existing `--bg-*`, `--border-*`, `--accent-*` variables. New CSS rules append to existing `<style>` block.
- **HTML escape v5-introduced user-content fields** (gates label/note, deps from/to/effect, tracks.<>.purpose). Pre-existing v4 unescaped behavior is grandfathered — do NOT retrofit.
- **No GitHub Actions added.** Out of scope. Existing manual + Render auto-deploy stays.
- **No force-push to main** — rebase + standard squash-merge only.

## ETA

~4–6h end-to-end (1.5h YAML migration + Brisen Lab backfill, 2h renderer changes, 1.5h tests, 1h verification + paired PRs). Calibrate on first push if your read of complexity differs.

## Coordination

- Branch: `b3/fleet-roadmap-html-render-1` (both repos)
- Heartbeat: update `last_heartbeat` in this mailbox file every ~4h while in flight
- Blocker: surface to AH1 via `blocker_question` field; do not stall silently
- PR opens against `main` in both repos
- Required reviewers: AH1 (both PRs); B1 second-pair-of-eyes on baker-master PR

## Reference (this clone)

- AI Head autonomy charter: `_ops/processes/ai-head-autonomy-charter.md`
- B-code dispatch coordination: `_ops/processes/b-code-dispatch-coordination.md`
- Lessons (read #3b, #8, #44, #47, #52 minimum): `tasks/lessons.md`
- Existing renderer: `scripts/render_cortex_roadmap.py` (323 lines)
- Existing YAML (v4): `~/baker-vault/_ops/processes/cortex-roadmap-current.yml` (868 lines)
