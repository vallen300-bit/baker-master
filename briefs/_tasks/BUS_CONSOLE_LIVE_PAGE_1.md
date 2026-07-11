# BUS_CONSOLE_LIVE_PAGE_1

**Dispatched_by:** lead (AH1) · 2026-07-11 · Director-ordered ("interactive check bus", option B ratified)
**Repo:** baker-master (page + API proxy) — PR to main
**Task class:** Director-facing UI surface, read-only · **Harness-V2:** Context Contract below; gate = codex G3 medium + lead review; deploy Director-visible on merge
**Priority:** normal

## Context
Director wants a live, interactive window into the agent bus without asking lead to "check bus". Bus data lives on brisen-lab (`GET /msg/{slug}` per-terminal, X-Terminal-Key auth); baker-master serves Director-facing pages (arrivals board pattern: PIN cookie gate, 404-on-unauth). Context Contract: this brief + `outputs/dashboard.py` arrivals-board section (route `/arrivals`, `_arrivals_board_*` helpers) + `outputs/templates/arrivals_board_template.html` (V8 register, merged PR #524) are the only required inputs. Done-state: page live behind PIN, showing real traffic.

## Problem
Bus traffic is visible only via per-terminal API keys and CLI scripts. Director has no read surface at all; today he relayed "check bus" ~30 times in one session.

## Deliverables
1. `GET /bus-console` page on baker-master — same auth pattern as `/arrivals`: `ARRIVALS_BOARD_PIN` cookie gate (reuse the existing cookie/PIN helpers; 404 on unauth). Visual register: V8 arrivals aesthetic (dark panel, mono, amber) — engine-room variant OK, but Director-facing polish.
2. Server-side proxy endpoint `GET /api/bus-console.json` that reads brisen-lab with a server-held key (env `BRISEN_LAB_CONSOLE_KEY`, read-only; NEVER ship a terminal key to the browser). Returns last N messages fleet-wide or per-recipient: id, from, to, topic, kind, body_preview, created_at, acknowledged_at.
3. Page features: auto-refresh ≤60s; filter by recipient + unacked-only toggle; unacked rows highlighted; newest first; click row → expand full body_preview. READ-ONLY — no post, no ack from the page (v1).
4. Fault-tolerant: brisen-lab unreachable → page shows honest "BUS UNREACHABLE since <t>" banner, never a stack trace (Lesson: stale ≠ healthy).

## Files to touch
- `outputs/dashboard.py` (routes `/bus-console`, `/api/bus-console.json`)
- `outputs/templates/bus_console_template.html` (new)
- `tests/test_bus_console.py` (new)

## Constraints
- Do NOT touch `/arrivals` or its helpers beyond importing/reusing the auth check.
- No terminal key in HTML/JS — proxy only. Codex gate must probe for key leakage.
- Which brisen-lab endpoint serves a fleet-wide read with one key: diagnose first (daemon firehose vs per-slug loop); if only per-slug works, loop server-side over a fixed slug list from the registry — do not hardcode more than the source already does.

## Verification
Live exercise (not "by inspection"): local run, curl both routes unauth (expect 404) and with PIN cookie (expect 200 + real rows); screenshot or curl'd HTML with ≥1 real message row in ship report.

## Quality Checkpoints / Acceptance criteria
- AC1: unauth `/bus-console` → 404; with PIN cookie → 200.
- AC2: `/api/bus-console.json` returns real bus rows; no X-Terminal-Key string anywhere in served HTML/JS.
- AC3: unacked filter + recipient filter work (probe with live data).
- AC4: brisen-lab down (bad host env in test) → honest banner, HTTP 200 page still renders.
- AC5: pytest suite green incl. new tests; py_compile clean on dashboard.py.

## Done rubric
Ship report answers each AC with live output. Chain: author → codex G3 (medium) → lead review → lead merge (merge = deploy) → POST_DEPLOY_AC_VERDICT with live probes → Director gets URL + PIN note.
