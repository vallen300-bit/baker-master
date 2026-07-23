# LAB_V2_LOOPS_TWO_NEW_LOOP_CARDS_1

**Repo:** brisen-lab · **Builder:** b2 · **Gate:** codex seat (delta) · **Lead:** dispatch + merge
**Director GO:** 2026-07-23 ("go" on adding the two cowork loops as LOOPS cards)

## Context Contract

- **Task class:** content-addition, frontend-static (small production; no API, no schema, no auth surface).
- **Inputs b2 needs:** this brief; existing card markup in `static/v2/loops.html` (build-loop card = template); loop content is QUOTED in the Task section — do NOT read baker-vault (b2 has no vault checkout).
- **Out of scope:** loops.js changes (stop + report if needed), app.py, shell.js, boards, any other page.
- **Done rubric (done-state class: gated-merge-live):** codex delta PASS → lead merges → Render deploy → lead live-verifies 5 cards + subpanel 5 + 0-iframe grid → Director eyeball. Builder DONE = ship receipt with sha + ls-remote line; not before.
- **Gate plan:** single codex seat review (drive the page, not code-shape); no self-gate (Lesson #131); lead runs live AC post-deploy.

## Problem

/v2 LOOPS grid shows 3 cards (research-loop, airport-loop, build-loop). Two new
Director-ratified loops shipped this morning as vault skills (cowork-ah1 #15228/#15230,
committed @e2afa4a + @ed5989e baker-vault) but have NO card — Director wants visibility
on the page he already checks, ahead of the AO-first pilot.

## Context

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** open a loop card to read that loop's charter, stages, and trigger words (Description-only cards; no board, no state change).
2. **Backend route:** `GET /v2/loops` at `brisen-lab/app.py:2231` (`def v2_loops(): return _v2_page("loops.html")`) — static page, no new API.
3. **Endpoint contract:** none new. Cards are static HTML sections; collapse/expand handled by shipped loops.js v8 (merged @0072721).
4. **State location:** loop definitions = baker-vault `_ops/skills/{working-set-creation,meeting-cycle}/SKILL.md`; card = descriptive static HTML in brisen-lab `static/v2/loops.html` (same precedent as build-loop card @0a079a2 — no live state binding).
5. **UI repo:** brisen-lab, /v2 LOOPS page.
6. **Director surface preference:** asked + ratified 2026-07-23 ("go") — LOOPS card grid, because it is the page Director already checks.
7. **Gate reviewer instruction:** reviewer MUST load /v2/loops (or curl it) and confirm 5 cards render, grid contract (0 iframes) intact, subpanel derives 5 loops. Code-shape review is not sufficient.

## Task

Add TWO `loop-card` sections to `static/v2/loops.html`, following the existing card
structure (build-loop is the closest template — Description view, NO board / no iframe).

**Card 4 — `data-loop="working-set-loop"` — "Working-Set Creation (Loop 1)"**
- What it is: provisions a matter's meeting working set ONCE so the meeting cycle can run forever. Pair: provision once (Loop 1), cycle forever (Loop 2).
- Stages (6): objectives session (Director) → CONTEXT bootstrap → Zheng Ming glossary walk (Director) → cycle-config authoring + registry validation → optional full tier (playbook / sacca / dashboard / minutes hub) → cycle-ready dry-run PASS report.
- Gates: 2 Director gates (objectives, glossary). Orchestrator (lead) executes zero steps; matter desk executes; Director ratifies.
- Skills: working-set-creation · context-bootstrap · cycle-config-author.

**Card 5 — `data-loop="meeting-loop"` — "Meeting Cycle (Loop 2)"**
- What it is: per-meeting operating cycle turning every recorded meeting into ratified record + folded knowledge. Runs per matter off its cycle config.
- Stages (9): config validation → record + link → plaud-pull capture → minutes → fold (playbook / CONTEXT / hub / artifact republish) → routing → grill queue → Director ratify sweep + outbound (Edita route) → pin.
- Gates: human gates inviolable — the machine never answers its own grill question, never ratifies.
- Pilot: AO / MOVIE-shares config №1 live; per-desk rollout after one clean cycle.
- Skills: meeting-cycle · plaud-pull · meeting-fold.

## Constraints

- Touch ONLY `static/v2/loops.html` (+ tests if counts asserted). loops.js should need NO change — cards without boards already supported (build-loop precedent). If loops.js DOES need a change, stop and report why before writing it.
- Grid contract preserved: 5 cards, 0 iframes on grid entry; new cards have no board host to mount.
- Subpanel parser: shell's loops subpanel is runtime-derived — verify it derives 5 entries; if the parser caps or breaks, report before hacking around it.
- Cache-bust only if a JS/CSS file changes (target: none).
- Lesson #131: receipt must include new sha + `git ls-remote` line. No self-gate.

## Acceptance criteria

1. /v2/loops grid renders 5 cards; the two new cards open to Description working view and return to grid cleanly.
2. Grid entry = 0 iframes (existing regression suite still green; node + pytest suites pass).
3. Loops subpanel in /v2 shell derives 5 loops.
4. Both themes render sanely (spot-check dark + light).
5. Card copy matches this brief's content blocks (edit for fit, do not invent stages).

## Reviewer instructions (codex)

Load /v2/loops live or from branch; confirm AC 1–3 by driving the page, not by reading code. Confirm diff scope = loops.html (+ test count bumps only).
