# B2 ship report — Cockpit Phase-2 coordinated cutover (FLEET_TMUX_LAUNCH_1 §6a)

- **Dispatched by:** lead — bus #12324 (Director GO 2026-07-17), ruling #12330 (Option A).
- **Branch:** `b2/cockpit-phase2-cutover` · PR: (opened, see bus) · base `main` @92b735fe.
- **Codex cross-vendor gate:** PASS — session `019f717c-4af1-72b0-a012-96a20d97702d` (gpt-5.6-luna, `-e high`). Required by ruling #12330 before any execution.
- **State:** BUILT + gated. NOT executed. Awaits lead's coordinated quiet-window GO with the token.

## What lead asked for (ruling #12330)

1. BUILD the `cutover()` body (replace the `die`) — profile-CommandString rewrite to tmux launch, GO-token gate kept, per-seat rollback, wave-report logging; Codex blocking PASS before execution. → **done (this report).**
2. RUNBOOK to lead — quiet-window step list. → **done:** `.claude/how-to/cockpit-phase2-cutover.md` (+ INDEX entry).
3. Lead schedules the quiet window with Director + sits in-session. → **lead's action.**
4. `context_pct` card-face lane — scope in parallel, coordinate #12055, own gate. → **not started; next; see below.**

## Deliverable 1 — the cutover

The Phase-2 `cutover()` (previously built-not-executed, a hard `die`) now implements the §6a sequence, GO-gated on `COCKPIT_PHASE2_GO=LEAD-RATIFIED`:

1. Precondition gate: both pilots (`b3`, `brisen-desk`) green in the ledger; manifest strict-clean (eligible==resolved); self-seat guard (`TERM_SESSION_ID`).
2. Backup the plist; **arm a recovery trap BEFORE the quit.**
3. Single Terminal.app quit (the only Cmd+Q) + `cfprefsd` drop.
4. Rewrite ALL eligible profile CommandStrings → `tmux new-session -A -s <slug> "/bin/zsh -lic '<alias>'"` (scope §6.1), one pass, while Terminal is DOWN so it is durable (Lesson 76). Mark ledger migrated.
5. `fleet_terminals.sh up` (create tmux sessions).
6. Per-seat smoke in waves (`--wave-size`, default 5) with Terminal still down: tmux up + ttyd web 200 (+ bare `/` 404 base-path proof). A failed seat is rolled back **durably** (profile restored while Terminal down) and reported **loud**; a failed rollback flips the run to "FINISHED WITH ROLLBACK ERRORS" + exit 1.
7. Single Terminal relaunch; verified.

If anything aborts inside the danger window (incl. SIGINT/SIGTERM), the trap forces the whole fleet to ONE consistent BASELINE — restore all profiles to direct alias, clear the ledger, tear down all substrate, relaunch — and reports honestly ("BASELINE forced" only when profiles + ledger + teardown all succeeded, else "CRITICAL: recovery INCOMPLETE").

`cutover --dry-run` previews the plan read-only (no GO token, nothing written).

## Files

- NEW `scripts/cockpit_profile_rewrite.py` — plistlib rewrite/restore/restore-all of Terminal-profile CommandStrings; backup/merge-preserve; `--plan-only`; drift + Terminal-running (Lesson 76) + empty-backup + mixed-wrapper + quoting guards; atomic writes.
- `scripts/cockpit_migrate.sh` — `cutover()` body + `emergency_recover` + `smoke_seat` + `cutover_fail_seat`.
- `scripts/cockpit_rollback.sh` — §12 profile restore on `seat`/`full`, durable (quits Terminal first when a backup exists), rc-propagating.
- `scripts/fleet_terminals.sh` — `manifest_profile` helper.
- `scripts/generate_cockpit_manifest.py` — `_unwrap_commandstring` so the generator resolves identically pre/post cutover (no 0/N post-cutover).
- NEW `tests/test_cockpit_profile_rewrite.py` — 12 round-trip tests.
- `.claude/how-to/cockpit-phase2-cutover.md` + INDEX — the runbook (deliverable 2).

## Verification (Lesson #8 — live where safe)

- `pytest tests/test_cockpit_profile_rewrite.py` → **12/12 pass** (rewrite/restore/restore-all/plan-only/idempotent/drift/backup-guard/mixed-wrapper/generator-unwrap/restore-missing/restore-all-fail-loud).
- `python3 scripts/generate_cockpit_manifest.py --strict` → **exit 0, 29/29 resolved**.
- `scripts/cockpit_migrate.sh cutover --dry-run` → **exit 0**, plans 29 profiles, 0 drift, pilots green, plist untouched, no backup written.
- `py_compile` + `bash -n` clean; shellcheck clean (pre-existing `CDPATH=` idiom only).
- The real cutover was NOT executed (destructive/live; lead-gated).

## Codex hardening history (6 FAIL → PASS)

The gate did its job. Six FAIL rounds, all in the recovery/rollback/error-reporting paths (the plist primitive was sound throughout), converging on one theme — never report success over an unchecked cleanup/skip/empty-loop. Sessions: 019f7128 → 019f713a → 019f714a → 019f715a → 019f7168 → 019f7173 (FAIL) → **019f717c (PASS)**.

## Deliverable 4 — context_pct card-face lane (next)

Not started. Per ruling: scope in parallel, coordinate #12055 (LAB_CONTEXT_BAND_EXPOSURE_1 / forge snapshot pusher), own gate. Will scope after this hands to lead.
