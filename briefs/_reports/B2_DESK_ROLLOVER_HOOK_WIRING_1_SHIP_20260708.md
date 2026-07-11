# B2 SHIP REPORT — DESK_ROLLOVER_HOOK_WIRING_1

- **Dispatched by:** lead (#7193; rulings #7207)
- **Date:** 2026-07-08
- **Task class:** config-wiring (production agent seats; no server code, no baker-master change)
- **Repo:** desk picker dirs on this laptop (4 Dropbox-synced + 2 local); no git PR — desk dirs are not baker-master repos.

## What shipped
Wired the checkpoint+respawn Stop hook (`context-threshold-check.sh`) into the 6 live-active
**terminal** desk pickers. Each got `.claude/settings.json` with the `hooks.Stop` entry +
`rollover_window_tokens=200000` + `rollover_soft_percent=40`, and a byte-identical copy of the
hook script deployed at `.claude/hooks/context-threshold-check.sh` (relative-path pattern,
zero fork). **No role-context edits** (lead ruling #7207 Option C). **Nothing in baker-master;
nothing in the hook script itself.**

## Roster (lead ruling #7207 — live-active TERMINAL set, not the brief's stale 6-row table)
| Desk | Picker path | Loc |
|---|---|---|
| ao-desk | `~/Vallen Dropbox/Dimitry vallen/bm-ao-desk` | Dropbox |
| baden-baden-desk | `~/Vallen Dropbox/Dimitry vallen/bm-baden-baden-desk` | Dropbox |
| movie-desk | `~/Vallen Dropbox/Dimitry vallen/bm-movie-desk` | Dropbox |
| origination-desk | `~/Vallen Dropbox/Dimitry vallen/bm-origination-desk` | Dropbox |
| hag-desk | `~/bm-hag-desk` (**local**, per wake-handler cwdForAlias map) | local |
| hag-filer | `~/bm-hag-filer` (**local**, per wake-handler cwdForAlias map) | local |

- **SKIPPED brisen-desk** — status=seeded / bus_enabled=False / vault-seeded (not a running seat). Doc gets a wire-on-activation note (lead's edit).
- **SKIPPED cowork-bb-desk** — App-resident, no respawn path; outer watchdog covers it (logged follow-up).
- Brief table's `~/Vallen Dropbox/.../bm-hag-desk` path was stale (does not exist); corrected to local `~/bm-hag-desk` per lead #7207.

## AS-BUILT settings.json (per desk)
- **ao / baden-baden / movie / origination**: no prior settings.json → created fresh: `{hooks.Stop:[context-threshold-check.sh], rollover_window_tokens:200000, rollover_soft_percent:40}`. Hook script MISSING → deployed canonical.
- **hag-desk**: prior settings.json had `PreToolUse:[lane1-meta-document-guard.sh]` + `Stop:[filing-gate-session-end.sh]` — **both preserved**; rollover hook appended as a 2nd Stop entry (n_stop=2, both fire independently). Keys set 200000/40. Hook script MISSING → deployed canonical.
- **hag-filer**: prior settings.json already carried the rollover Stop hook + byte-identical script (no-op). **DELTA:** `rollover_window_tokens 1000000 → 200000` + added `rollover_soft_percent:40`. See flag below.

Post-state (machine-verified):
```
ao-desk            win=200000 soft=40 stop_hook=Y n_stop=1 hook_sha=477b56938eaa OK
baden-baden-desk   win=200000 soft=40 stop_hook=Y n_stop=1 hook_sha=477b56938eaa OK
movie-desk         win=200000 soft=40 stop_hook=Y n_stop=1 hook_sha=477b56938eaa OK
origination-desk   win=200000 soft=40 stop_hook=Y n_stop=1 hook_sha=477b56938eaa OK
hag-desk           win=200000 soft=40 stop_hook=Y n_stop=2 hook_sha=477b56938eaa OK
hag-filer          win=200000 soft=40 stop_hook=Y n_stop=1 hook_sha=477b56938eaa OK
```
Canonical hook sha256[:12] = `477b56938eaa` (all 6 match — zero fork). Idempotent re-run = 6× no-op.

## ⚠️ DELTA-FLAG needing lead/deputy confirm — hag-filer window
hag-filer was the ONLY desk pre-wired, and it carried `rollover_window_tokens=1000000` (a 1M-seat value, no soft_percent). Per your roster ruling + the wiring table I applied the desk value `200000`/`40`. **New info you didn't have when you added hag-filer to the roster:** if hag-filer's terminal actually runs a 1M context window, `200000` makes it hard-block at ~17% of real capacity (forced early rollovers). If it runs 200K like the rule's premise, `1000000` was the bug and `200000` is the fix. I could not determine its true window from here. Config takes effect on hag-filer's **next** session start, so this is vetoable now. Revert to `1000000` or keep `200000` — your call (deputy G2 may also veto).

## Acceptance criteria
- **AC1 (all live desks wired; diffs; path mismatches fail-loud):** PASS. 6 desks wired, AS-BUILT above. Path mismatch (bm-hag-desk absent → local) + roster mismatch (brisen-desk seeded, cowork-bb App-only, hag-filer added) escalated #7204 and ruled #7207 before writing.
- **AC2 (rollover-scoped terminology grep clean):** PASS. `grep -niE "handoff|[^a-z]pin[^a-z]|pinned"` across all 6 wired settings.json → no findings. (Role-context untouched, so no shared-register vocabulary risk.)
- **AC3 (emit names mechanism — dry-run):** PASS. Live dry-run vs ao-desk cwd:
  - SOFT (50% of 200k): `[rollover] context ~50% (100000 est tokens / 200000 window, soft 40% / hard 85%). Refresh the checkpoint before the next phase boundary; at 85% checkpoint and respawn.` (block=false)
  - HARD (100%): `[rollover] context ~100% ... HARD: write or refresh briefs/_checkpoints/<BRIEF_ID>.checkpoint.md now, commit + push it, post respawn request, then exit cleanly. Claim in the successor is the attempt-bump commit, not bus ack.` (decision=block)
  - **Emit-wording note (per your 4b):** soft band is terse-prepare; the FULL mechanism verbatim fires at the 85% hard band — matches the prepare(40)/execute(85) split by design. Accepted per #7207; deputy G2 may veto.
- **AC4 (watchdog sequencing statement):** see below.
- **AC5 (deputy G2 PASS + ship report):** report filed here; deputy G2 requested on bus (settings diffs + terminology grep, per #7207).

## AC4 — Watchdog ↔ self-trigger sequencing (deputy nit b, #7192; spec #7189)
The desk's **own 40% self-trigger** (this in-session Stop hook, `rollover_soft_percent=40`) is
**primary**: it nudges the desk to prepare at 40% and checkpoint at its next task boundary from
inside the session. The **outer context-cost watchdog** (agent-independent; amber ~35% / red ~40%)
is a **backstop that ORDERS ahead of the self-trigger only for agents that skip their own
checkpoint**. No double-fire: the watchdog is **state-driven, not schedule-driven** — at red-40 it
checks whether a fresh checkpoint exists; if the self-trigger already produced one, the watchdog
stays silent (it only escalates "checkpoint-required + cap NEW dispatches to the slug" when the
self-trigger was skipped). Both honor the Director hard constraint: SOFT ENFORCE only, never a
mid-flight kill — roll at a safe boundary.

## Verification method
1. Idempotent installer (`/tmp/wire_desk_rollover.py`) with dry-run before/after capture, then `--apply`.
2. Machine post-state check (keys + Stop-hook presence + hook sha vs canonical).
3. Live hook dry-run, both bands, against a real desk picker cwd.
4. Rollover-scoped terminology grep.

## Notes for lead
- Config applies on each desk's **next** session start; mid-session desks are unaffected (no restarts done, per brief constraint).
- Dropbox desks: edited in place (no temp-file moves).
- Open confirm: hag-filer window delta (above).

---

## APPENDIX — CONFIG RE-SWEEP (lead #7223, Director supersede 2026-07-08 ~10:38Z)

**Supersedes the 200000/40 as-built above.** Director directive: terminal agents inherit the
saved default model (Opus 4.8) with a **1M window** (plain-`claude` launchers carry no override;
verified via `/model`). New standard: `rollover_window_tokens=1000000` + `rollover_soft_percent=35`
(hard band unchanged = default 85). hag-filer's original 1000000 was CORRECT — my earlier 200000
was per lead's since-corrected mis-ruling; restored to 1000000 with the rest. At the old 200000 on
a real 1M seat the hook could still fire; the true bug the sweep fixes is the inverse (a 1M value on
a genuine 200K seat would never fire) — moot now that all terminal seats are confirmed 1M.

### Scope: 6 desks + workers b1–b4 (per #7223)
**Desks** (`settings.json` window→1000000, soft→35):
```
ao-desk / baden-baden-desk / movie-desk / origination-desk / hag-desk / hag-filer
  → window=1000000  soft=35  hard=(default 85)
```
**Workers b1–b4** (`settings.local.json` soft 50→35; `settings.json` window already 1000000, verified):
```
b1 / b2 / b3 / b4 → json.window=1000000  local.soft=35
```
Soft-percent LOCATION unchanged per seat convention (desks: tracked `settings.json`; workers:
gitignored `settings.local.json` where their percent already lived). Only VALUES changed.
Hooks/scripts untouched (byte-identical `477b56938eaa` everywhere). Idempotent re-run = 10× no-op.

### Re-sweep verification
- Post-state machine-checked (table above).
- Hook dry-run vs ao-desk @ 1M window: 20% → **silent**; 40% → SOFT prepare (`soft 35% / hard 85%`); 90% → HARD full-mechanism-verbatim + `decision: block`. Confirms the 35% soft threshold.
- Terminology grep still clean (only numeric values changed; no vocabulary touched).
- Deputy G2 re-pointed at the NEW values (1000000/35).

### Out of directive scope (untouched — flag for lead if wanted)
CM-1..4 workers and AH pickers (aihead1/aihead2) also carry the hook but were NOT named in #7223.
Left as-is: aihead1 intentionally stays 70/85 default; CM-1..4 not sweep-ordered. Say the word to
extend the 1000000/35 standard to them.
