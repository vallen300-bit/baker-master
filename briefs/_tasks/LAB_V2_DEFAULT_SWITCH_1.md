# BRIEF: LAB_V2_DEFAULT_SWITCH_1 — flip `/` to the new Lab shell, retire old pages (Director "switch" ratified)

```yaml
brief_id: LAB_V2_DEFAULT_SWITCH_1
dispatched_by: lead
assigned_to: b2
repo: brisen-lab (worktree ~/bm-b2/brisen-lab; branch b2/lab-v2-default-switch-1 from origin/main)
status: PENDING
```

## Context

Item 5 of the ratified unification plan. Director reviewed live /v2 and ruled
2026-07-21 morning ("both accepted" on lead's switch recommendation). Per
`briefs/_plans/BRISEN_LAB_UNIFICATION_RATIFIED_LAYOUT_2026-07-20.md`:

- `/` becomes the new v2 shell (AGENTS landing).
- **Dropped as standalone pages** (LAYOUT sheet verdicts): Templates gallery,
  Token burns, old Loops page, Bus hails, Delivery hails, Wake health,
  "Production & Lab" split. **Pages go, data stays** — every machine feed /
  API endpoint underneath is untouched (Director-briefed 2026-07-20).
- Old page URLs get redirects to their v2 successor (or `/` when none):
  token burns → `/v2/settings-logs`; templates → `/v2/skills`; old loops →
  `/v2/loops`; bus/delivery/wake-health pages → `/` (data lives in Settings &
  Logs History / future surfaces). 301s, so stale bookmarks land somewhere sane.

### Surface contract (ui-surface-prebrief, V1)

1. **User action:** Director opens brisen-lab.onrender.com/ → new shell loads (exact current /v2 experience). Old bookmarks redirect, never 404.
2. **Backend route:** `/` handler swaps to serve the v2 shell; old page routes become 301 redirects. `/v2` stays working (canonical or redirect to `/` — builder's call, note it).
3. **Endpoint contract:** ALL `/api/*` + `/msg/*` + `/cockpit/*` + `/term/*` + static data feeds byte-identical. Only HTML page routes change.
4. **State location:** none new.
5. **UI repo:** brisen-lab.
6. **Director surface preference:** ratified plan item 5.
7. **Reviewer instruction:** browser-load `/`, every old page URL (verify each 301 target renders), all 4 v2 pages, the cockpit embed, and one API endpoint before/after diff. Grep templates for links pointing at retired routes — none may remain.

## Estimated time: ~2.5h
## Complexity: Medium (deletion-heavy — the risk is over-deletion)
## Prerequisites: none

## Harness V2

- **Context Contract:** this brief; ratified layout plan (drop list section); `app.py` route registrations for `/` and each old page; `static/` inventory of old-page assets; the fleet-scan / wake daemons' URL usage (`grep -rn "onrender.com/" scripts/` in baker-master for any hardcoded old-page URLs — report findings, do not fix cross-repo).
- **Task class:** medium-feature production.
- **Done rubric:** Merged + Deployed + live AC (all redirects + feeds intact) + POST_DEPLOY_AC_VERDICT. Writeback: lead registry item 5 LIVE.
- **Gate plan:** self-test → push → blocking codex gate on pushed SHA → lead merge → Render deploy → lead live AC → verdict.

## Implementation

1. `/` serves the v2 shell (same handler/template as `/v2`).
2. Old page routes → 301 redirects per the map above. Old-page HTML/JS/CSS assets deleted ONLY when no live route references them; anything shared with a surviving feed stays.
3. The two absorbed loop BOARDS (`static/loops/*`) are NOT old pages — they stay, iframed by /v2/loops.
4. Route tests: `/` returns shell markers; each old URL returns 301 + correct Location; every `/api/*` endpoint listed in the test suite still 200s.
5. Report in ship report: exact routes removed, assets deleted, redirect map, any cross-repo hardcoded-URL findings.

## Key Constraints
- ZERO endpoint/data changes — pages only. If a "page" route doubles as a JSON feed for any consumer, KEEP the feed and flag it.
- Cockpit embed + `/term/` proxy + bus + wake daemons untouched.
- Reversible: single revert of the merge restores the old `/`.

## Verification
1. pytest green (new route tests + suite).
2. Local uvicorn: `/` = shell; old URLs 301 → live targets; spot-check 3 API endpoints unchanged.
3. `git diff --stat` matches the reported deletion list — nothing outside page routes/assets/tests.

## Do NOT Touch
- `/api/*`, `/msg/*`, `/cockpit/*`, `/term/*`, `static/loops/*` boards, static/v2/*, controller, baker-vault.

## Quality Checkpoints
1. No 404 left behind — every retired URL redirects.
2. Deletion list enumerated in ship report (fail loud on anything ambiguous — ask, don't guess).
3. Ship report + SHA on bus topic `lab-unify/default-switch`; codex gate on pushed SHA.
