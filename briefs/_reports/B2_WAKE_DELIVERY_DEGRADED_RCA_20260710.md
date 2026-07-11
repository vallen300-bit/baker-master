# RCA — WAKE_DELIVERY_DEGRADED (dispatch #8676, lead → b2, 2026-07-10)

**Mode:** diagnose-first. No fix built. Fix proposals below require lead GO + the
live-wake AC from `project_wake_focus_guard_v2_hard_regression_2026-07-09`
(prove one background spawn + one background nudge before shipping).

**Bottom finding:** two independent root causes, both live today.
1. **Server:** the idempotent-post dedup path drops the wake permanently when the
   first POST commits the row but 503s before the wake fires (symptom 1).
2. **Laptop:** the FOCUS_GUARD_V2-**hard** patch that was rolled back 2026-07-09
   **re-landed today at 17:14Z** and kills all autonomous wakes (symptoms 2, 3, 4).

---

## Symptom 1 — server dedup-wake gap (CM-1 #8618, deduped:true, zero wakes)

**Confirmed root cause.** In `brisen-lab/bus.py:_post_msg_inner`:
- `_insert()` (bus.py ~889) commits the row and returns `is_new=True`.
- `_apply_post_side_effects()` (bus.py ~941, gated `if is_new:`) runs broadcast +
  badge + the auto-wake decision loop. That loop makes DB calls via `get_conn()`
  (`_master_autowake_enabled`, `_emit_badge_refresh`, `_audit_wake_event`).
- If the psycopg2 pool is at maxconn during side-effects, `db.get_conn()` raises
  `BusPoolExhausted` → `app.py:114` handler returns **HTTP 503 `bus_busy_retry`**.
  The row is already durable; the `wake_request` broadcast never fired.
- `scripts/bus_post.py:_post()` (AGENT_BUS_IDEMPOTENT_POST_1, lead #8366) retries
  503 with the **same idempotency_key**. Retry hits `ON CONFLICT DO NOTHING` →
  `is_new=False` → `_apply_post_side_effects()` is **skipped** ("original already
  applied them" — but it did not). Sender gets 200. Net: **zero wakes.**

**Why wake_health shows fired_24h=0 AND suppressed_24h=0 for CM-1:** the wake
decision loop (which writes every `wake_events` audit row, fired or suppressed)
lives *inside* the skipped side-effects. fired=0 **and** suppressed=0 is the
signature of "the loop never ran," not "the wake was suppressed" — corroborates
the dedup-skip path exactly.

`is_new` conflates *"this INSERT created the row"* with *"side-effects completed."*
Wake-delivery state is not persisted, so a post-commit failure on attempt 1 is
invisible to the dedup branch on attempt 2.

**Aggravator:** CM-1 is a coder, not in `app.py:DESK_BACKLOG_WAKE_SLUGS`, so the
`_desk_backlog_wake_sweep` fallback never re-wakes it. A dropped wake to a coder
stays dropped forever.

**Dead scaffolding found:** `brisen_lab_msg.wake_attempted_at` column + partial
index `WHERE wake_attempted_at IS NULL` (db.py:408/427, named "hot drain path")
**exist but are never written** — grep shows read-only (bus.py 1069/1100). The
durable wake-drain this schema was built for was never implemented.

### Fix proposal (symptom 1) — needs lead GO
- **(A) Persist + re-drive.** On success, stamp `wake_attempted_at`. On a dedup
  hit (`is_new=False`), re-run `_apply_post_side_effects` iff the original row's
  `wake_attempted_at IS NULL`. Makes wake idempotent on **delivery**, not INSERT;
  reuses the already-scaffolded column/index. *Recommended — matches evident
  original design intent.*
- **(B) Durable wake-drain loop** over `wake_attempted_at IS NULL AND kind=dispatch`
  → fire + stamp. General safety net for ANY dropped inline wake (not just dedup),
  and covers coders that the desk-backlog sweep skips.
- **(C) Best-effort side-effects** so pool-exhaustion can't turn a committed insert
  into a 503. Weakest alone (still loses the wake if pool truly exhausted).
- **Recommend A + B together.** A closes the dedup-specific gap; B is the general
  net + coder coverage.

---

## Symptoms 2 & 4 — FOCUS_GUARD_V2-hard re-landed (autonomous wakes dead)

**Confirmed root cause — a re-land of the 2026-07-09 regression.**
Deployed `~/Applications/Brisen Lab Wake.app/Contents/Resources/Scripts/main.scpt`
(mtime **Jul 10 17:14**) contains "FOCUS_GUARD_V2 hardening (2026-07-09)" blocks:
- live tab + `not wantFg` → `logWakeSkip "background_no_terminal_nudge"` + return
  (no nudge).
- absent + `not wantFg` → `logWakeSkip "background_absent_no_spawn"` + return
  (no spawn).

Server sends `foreground:false` for autonomous wakes, so **every** autonomous wake
is fg=0 → badge/log-only. Handler log confirms: wall-to-wall
`background_no_terminal_nudge` for lead, hag-desk, movie-desk, baden-baden-desk,
b1, b3 from 15:16Z onward; `background_absent_no_spawn` + `spawn_cooldown` for
baden-baden-desk 15:45–15:51Z.

**Re-land mechanism (two-repo drift):**
- **baker-master** `brisen-lab/` subdir — `main` is **clean** (V2-soft, 0 V2-hard lines).
- **standalone brisen-lab repo** (`github.com/vallen300-bit/brisen-lab`, checked out
  at `bm-{cowork,b1,b2,b3}-brisen-lab`) — `main` carries commit **d5051d0 "Harden
  background wakes against focus steal"** (2026-07-09 13:25 +0200 = 11:25Z) — the
  V2-hard patch, **never reverted.** The 2026-07-09 11:24Z rollback only restored
  the deployed `.scpt` file, not git.
- The deploy/rebuild path (`build.sh`) uses the **standalone** repo. Today's
  BRISEN_DESK_ON_BUS_1 lab install (commit 16d4dff "3/3 lab … wake maps") ran
  `build.sh` from `bm-cowork-brisen-lab` at **17:14** (mtimes: poisoned source
  17:14 = deployed main.scpt 17:14 = wake-register.log 17:14) → recompiled main.scpt
  WITH V2-hard → live.

### Fix proposal (symptoms 2 & 4) — needs lead GO
- **Revert d5051d0** on the brisen-lab standalone repo `main` (proper `git revert`,
  not just a file restore this time). Restore V2-soft: background wakes deliver
  silently (nudge live seats, spawn absent ones) *without* focus steal; focus only
  on fg=1.
- Pull the revert into all `bm-*-brisen-lab` checkouts (purge the poison at source).
- Rebuild main.scpt from reverted source; re-run `build.sh` + `register-url-handler.sh`.
- **Systemic guard (root of the re-land):** the wake-handler has TWO divergent git
  sources (baker-master subdir vs standalone repo). Either reconcile to one source
  of truth, or add a build/CI assertion that the compiled main.scpt does NOT contain
  `background_no_terminal_nudge` / `background_absent_no_spawn`. Make the 2026-07-09
  live-wake AC a hard gate on any wake-handler change.

---

## Symptom 3 — manual `open brisen-lab://wake/CM-1` at ~15:52Z, no handler log line

**RCA.** At 15:52Z the deployed main.scpt was still the 2026-07-09 V2-soft rollback
(rebuild came later, 17:14). CM-1 is a known alias (main.scpt line 434 →
`/Users/dimitry/bm-CM-1`, line 64), so a bound V2-soft handler would spawn/nudge
**and** log. **No log line = the `brisen-lab://` URL scheme was not bound to Brisen
Lab Wake.app at 15:52Z** (scheme drift). Evidence: `register-url-handler.sh` re-ran
at 17:14 (wake-register.log mtime) — the scheme needed re-claiming. The 17:14
`build.sh` re-registered the scheme (fixing symptom 3) but simultaneously recompiled
with V2-hard (causing symptom 2).

**Secondary:** a raw `open brisen-lab://wake/CM-1` with no `?fg=1` defaults to fg=0
(background). Under the now-deployed V2-hard it would be dropped
(`background_absent_no_spawn`) even with the scheme bound. Manual Director/lead
wakes must pass `?fg=1` (the dashboard click does; a raw `open` does not).

**Monitoring gap:** the scheme drift persisted ~1.5h before manual remediation. The
listener self-heals on a consecutive -600/-609 streak, but a V2-soft handler that
*logs a skip* returns `open` rc=0 → looks healthy → no streak → no self-heal. A
handler that skips-but-exits-0 is invisible to the listener's health check.

### Fix proposal (symptom 3) — needs lead GO
- Covered by the V2-hard revert (§2/4).
- Consider a periodic (not login-only) scheme-binding re-assert, or a listener
  health probe that treats a run of `background_*` skips as a degradation signal.

---

## Evidence index
- Server: `brisen-lab/bus.py` `_post_msg_inner` / `_apply_post_side_effects`;
  `brisen-lab/app.py:114` (503 handler), `DESK_BACKLOG_WAKE_SLUGS`;
  `brisen-lab/db.py:408/427` (unused wake_attempted_at); `scripts/bus_post.py:_post`.
- Laptop: deployed main.scpt decompiled (V2-hard present, mtime 17:14);
  `~/.brisen-lab/wake-handler.log` (skip reasons); `~/.brisen-lab/wake-register.log`
  (17:14 re-register); standalone brisen-lab `main` @ d5051d0.
- Prior incident: `~/.claude/projects/-Users-dimitry-bm-aihead1/memory/`
  `project_wake_focus_guard_v2_hard_regression_2026-07-09.md`.
