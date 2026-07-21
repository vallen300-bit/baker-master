# LEAD checkpoint — overnight 2026-07-22 (Lab V2 full-working-condition goal)

**Goal (Director, asleep):** finish Brisen Lab V2 to full working condition; work
autonomously; manage worker context refreshes; self-refresh at context limit.
Default-page flip stays HELD (no "switch" word given).

## DONE tonight (all codex-gated, merged, live)

1. **LAB_V2_SKILLS_BAR_SHADOW_1** — brisen-lab PR #175 merged @7019e6f
   (codex PASS no-findings #14969 after 3 fix rounds: #14943 scrollY-keyed
   premature shadow → rectTop; #14952 hidden-bar fresh-load false-stuck →
   barShouldElevate + after-render sync; #14959 one-line structural lock).
2. **LAB_V2_HEADER_UNIFORMITY_1** — brisen-lab PR #176 merged @4ad2a19
   (codex PASS no-findings #15001 after 1 round: #14997 fresh-load false-stuck
   on LOOPS/SETTINGS → pinned AND scrolled>0). Theme toggle now INSIDE pinned
   sidebar brand row — Director screenshot AC #14965 (toggle covered terminal
   collapse chevron) closed by construction. Render deploy in flight, marker
   probe running (bg task).
3. **COCKPIT_HEADER_BLOCK_STICKY_1** — baker-master merged @25be856f
   (deputy-codex build; stale-base caught → rebase onto bfa4fcad, assets v11;
   320px summary-status wrap fix @b5de238d; codex PASS #14954/#15019).
   Local cockpit static resynced, serving ?v=11, sticky markup live-verified.
4. **meeting-prep-doc skill deployed** (Director-ordered via cowork-ah1 #14987):
   user-global symlink + SKILLS_INDEX 137→138, vault @51edc23 (isolated
   worktree; shared checkout untouched, unrelated grill-with-docs mod left alone).

## IN FLIGHT / NEXT

- **BG probe** for Render deploy of @4ad2a19 (shell.css brand-row/is-stuck
  markers). On live: six-view sweep — AGENTS (open-terminal + toggle clearance),
  LOOPS, SKILLS, BAKER DASHBOARD embed, ARRIVALS BOARD, SETTINGS&LOGS; console
  errors; both themes.
- **cowork-ah1** asked (#15021) to re-verify all four views in Director Chrome
  (morning OK — laptop likely off).
- **Deputy-codex released** (#15020, worktree removable). **b2 released** (#15002).
- Outstanding non-V2 owed (do NOT drop): post-hoc codex gate on 5cce9ae+a55a6c5
  (#14619 re-ask); ctx-band FAIL re-ship → then COCKPIT_INBOX_AGE_ONLY_1;
  arrivals embed AC (Phase A leg).

## Mechanics

- Bus polling: `KEY=$(tr -d '\r\n' < ~/.brisen-lab/keys/lead)`; GET
  /msg/lead, filter `id > last` AND `'lead' in to_terminals` (daemon noise
  otherwise); full body via /event/{id}/full; ack POST /msg/{id}/ack.
- brisen-lab merges: /Users/dimitry/bm-lead-brisen-lab (clean main checkout).
- baker-master merges: via bm-b4 (checkout main, merge, push, restore
  b4/docs-cleanup-orphaned-reports).
- Cockpit resync: git archive <sha> scripts/cockpit_static → rsync into
  `~/Library/Application Support/baker/cockpit/static/` (static-only; no
  kickstart needed unless controller changed).
- Worker ctx bands checked via cockpit /api/agents (all ≤30% at 22:45Z).
- Codex seat is SERIAL — queue gates; nudge after ~30 min silence.
- Deputy-codex drifts role after daemon refresh (twice tonight: acted as
  reviewer #14988) — re-state BUILDER lane explicitly on re-dispatch.
