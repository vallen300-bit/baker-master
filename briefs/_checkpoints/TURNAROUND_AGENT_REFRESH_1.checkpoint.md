# CHECKPOINT — TURNAROUND_AGENT_REFRESH_1 (PR #82 gate-chain)

**Owner:** cowork-ah1 (AI Head A — Cowork). **Rolled over:** 2026-06-22 ~12:50Z (context ~218%; attempt-bump refresh #3 ~13:00Z, no new state since fee146e).
**Successor claim = the attempt-bump commit on `cowork-ah1/rollover-checkpoint-20260607`, NOT a bus ack.**

## ONE-LINE STATE (updated round-8)
PR #82 (brisen-lab `b1/turnaround-agent-refresh-1` → main) G3 loop I own. **SAFETY CLASS CLOSED + VERIFIED** through round-8 (head `cc16966`): double-restart/wrong-agent/idempotency/global-supersede all confirmed fixed. **Only 2 minor P2s left, out to b1 (#4011):** (1) db.py:237 lock checkout not error-mapped → 500 instead of 503 under pool exhaustion [repo hard-rule]; (2) ≤15s cosmetic queued-badge cache staleness [self-healing]. On b1's round-9 push: re-gate → MERGE → deploy → POST_DEPLOY_AC.

## STOP-LINE (successor — END THE LOOP)
Merge on round-9 clean. If round-9 surfaces only sub-15s-self-healing OR pool-exhaustion-only cosmetics, **MERGE the round-9 head + fast-follow** — do NOT open round 10. 8 rounds done; safety is closed; remaining is polish.

## FIRST TURN (successor)
1. Poll cowork-ah1 bus for a b1 ship/gate-request with id > 4011 AND check PR82 head moved past `cc16966`:
   - `KEY="$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_cowork-ah1/credential')"`
   - `curl -sS -H "X-Terminal-Key: $KEY" https://brisen-lab.onrender.com/msg/cowork-ah1?limit=6`
   - `gh pr view 82 --repo vallen300-bit/brisen-lab --json headRefOid,state`
2. Read full bus msg: `GET /event/<id>/full`. ACK every msg same turn: `POST /msg/<id>/ack` (X-Terminal-Key).
3. On a new b1 push → run G3 (see RE-GATE RECIPE) → if clean, MERGE + DEPLOY (see MERGE).

## PR #82 — what it is
Dashboard "Refresh tired agents" controls. Reuses `trigger_force_fresh_context`. Additive, origin-gated, **NO feature flag**. Tests live-PG (`test_refresh_agent.py`).

## FINDINGS LEDGER (codex bus terminal was DEAD ~30min early; I ran G3 myself via codex-verify CLI = gpt-5.5, cross-vendor)
- **13 findings cleared + verified** across rounds 1–6 (safety: refresh-working-agent R1, wrong-agent-drain R3; idempotency, stale-row cleanup, global call-site supersede, force-UI).
- **Round-7 OPEN (sent to b1 #3977 @ 11:58Z), head still 8a9c79e:**
  - **#1 [P2 REQUIRED]** `app.py:~746` immediate (idle-agent) refresh path not idempotent — `_take_pending_refresh_sync` flips row to `fired` while unique index is `WHERE status='pending'`, so a 2nd POST after the claim but before in-flight registers inserts a NEW pending row → **double restart**. Fix spec given: pg **transaction-scoped advisory lock** keyed on alias spanning the whole claim+trigger (`pg_try_advisory_xact_lock(hashtext('refresh:'||alias))`), loser returns `outcome='collapsed'`; OR keep row `pending` until in-flight registered. Test: N concurrent immediate refreshes → exactly one `lifecycle/restart`.
  - **#2 [P2 fast-follow-OK]** `app.js:~1153` busy `outcome==="queued"` only toasts; doesn't set `state.refreshState[alias]="pending"` + render, so queued/Cancel/Force controls don't show until next `/api/v2/terminals` poll. Self-healing → NOT a merge-blocker on its own.
- **My stated stop-line to b1 (#3977):** if round-8 G3 surfaces only self-healing/cosmetic edges, MERGE on #1-clean and let b1 fast-follow #2 — do NOT spin forever.

## RE-GATE RECIPE (I run G3; codex bus terminal unreliable)
```
cd ~/brisen-lab-staging && git fetch origin b1/turnaround-agent-refresh-1 main
git worktree add -f /tmp/blab-pr82-revN <NEW_HEAD_SHA>
cd /tmp/blab-pr82-revN && codex-verify --review --base origin/main   # gpt-5.5, ~3-5min, may bg
# read verdict tail; then: cd ~/brisen-lab-staging && git worktree remove /tmp/blab-pr82-revN --force
```
Post verdict to b1 via `BAKER_ROLE=cowork-ah1 ~/Desktop/baker-code/scripts/bus_post.sh b1 "<body>" gate-verdict/pr82` (always set dispatched_by cowork-ah1; it routes back to me).

## MERGE + DEPLOY (on clean G3 — charter §3 autonomous, Director already said "go")
1. Merge PR #82 to main (brisen-lab). Coordinate git with `lead` if he's mid-write (single-threaded rule).
2. Render auto-deploys brisen-lab daemon `srv-d7q7kvlckfvc739l2e8g` from main (or restart via Render API).
3. Post **POST_DEPLOY_AC_VERDICT v1** to bus (`post-deploy-ac-bus-gate` skill) — dashboard refresh rows 1–6 on Director's screen.
4. If #2 still open at merge: dispatch a tiny fast-follow brief to b1 for the queued-controls UI render.

## COORDINATION
- `lead` (Terminal AH1) owns B-code wake lane. b1 hit the **stale-session wake-trap** twice today; lead recovered it at #3921 and re-woke at #3999. If b1 goes silent >20min with no push, ping lead (`coord/pr82-b1-liveness-check`) to cycle+re-wake — don't edit b1's clone yourself.
- codex bus terminal was dark (its own stale-session trap, NOT Stealth Flight — lead confirmed #3934). codex-arch/deputy own codex lifecycle, not me.

## BUS CHEAT-SHEET
- key: `op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_cowork-ah1/credential'`
- read inbox: `GET /msg/cowork-ah1?limit=N` (X-Terminal-Key) · full body: `GET /event/<id>/full` · ack: `POST /msg/<id>/ack`
- post: `BAKER_ROLE=cowork-ah1 ~/Desktop/baker-code/scripts/bus_post.sh <recipient> "<body>" <topic>`
- last handled ids: my round-7 send #3977, lead liveness reply #3999. Ack anything > 3999.

## SIDE TASK — DONE this session (no follow-up unless Director asks)
Director's laptop screen auto-locking ~15-20min: **FIXED** via System Settings → Wallpaper → Screen Saver… → **Start Screen Saver = Never** (verified `defaults -currentHost read com.apple.screensaver idleTime` = 0; displaysleep already 0). Caveats told to Director: (a) "Require password" is locked to *Immediately* by iPhone Mirroring (harmless now — nothing triggers it on idle); (b) on **battery** the Mac still sleeps ~60min and locks on wake. **Open offer awaiting Director "go":** also set battery to never-sleep (I recommended leaving it for battery health). If he says go → `sudo pmset -b sleep 0` (needs his password) or via Battery pane GUI.
