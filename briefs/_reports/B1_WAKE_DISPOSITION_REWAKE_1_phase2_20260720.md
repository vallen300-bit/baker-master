# B1 ship report — WAKE_DISPOSITION_REWAKE_1 phase-2 (listener side)

- **Brief:** `briefs/_tasks/WAKE_DISPOSITION_REWAKE_1.md` (tasks 4-5, listener side)
- **Dispatched:** lead #13840 (phase-2 release), reply topic `wake-disposition-rewake-1`
- **Repo/branch:** brisen-lab `b1/wake-disposition-rewake-1` @feb0af5 (off lab main @ceb53e5 — my phase-1 listener merge is in)
- **Date:** 2026-07-20
- **Gate:** lead CLI codex-verify lane (codex seat unstable), merged-tree vs current lab main

## Controller contract consumed (baker PR #611, live)
- Wake response: `{ok, sent(bool), disposition: delivered|skipped|undelivered, reason, slug, skipped(compat)}`.
- Receipt: `GET /api/wake-receipt/<request_id>` → `{"landed": bool}`, Basic auth (same as controller).
- `undelivered` reasons (controller `_wake_disposition`): `no telemetry`, `no unacked message id`, `no wake obligation message id`.

## Task 4 — consume disposition (`dispatch_wake` success path)
- **undelivered** → LOUD `WARNING` with request-id + reconcile via the receipt endpoint + retry ONLY via the controller when definitively not-landed. Reuses the existing at-most-once machinery (`_handle_ambiguous_wake`, now `label`-parameterised so the audit trail reads `undelivered-*` vs `ambiguous-*`). Never legacy, never a duplicate.
- **skipped** (deliberate no-wake) + **delivered** → terminal, stay `INFO`.
- **absent disposition** (old controller) → legacy `sent`-based behavior, no crash. `_post_controller_wake` adds `disposition`/`reason` to the result only when present, so legacy result dicts are byte-identical (mixed-version fleet safe).

## Task 5 — enable reconcile
- `WAKE_RECEIPT_URL` now **derives** from `COCKPIT_CONTROLLER_URL` + `/api/wake-receipt` when unset (one source of truth; env override wins; `""` = explicit dormant). So reconcile is on by default against the live endpoint even if the plist re-sync lags.
- Also set explicitly in the launchd plist template (`com.baker.wake-listener.plist`); `install.sh` copies the template verbatim, so the installed plist carries it.

## Tests (27 pass py3.9 AND py3.12, isolated TEST_DATABASE_URL; dispatch-log suite green)
- `test_receipt_url_derived_from_controller_by_default`
- `test_disposition_undelivered_reconciles_and_retries` (not-landed → controller retry)
- `test_disposition_undelivered_reconciled_landed_no_retry`
- `test_disposition_skipped_is_terminal_no_reconcile`
- `test_disposition_delivered_is_success`
- `test_absent_disposition_uses_legacy_behavior_no_crash`
- Existing 4 classification tests set `receipt_url=""` (explicit dormant) to stay focused on legacy-vs-no-fallback.

## Live ACs (post-deploy, owner = lead then B1)
- AC3 (listener half): undelivered logs WARNING+ with request-id; receipt probe `GET /api/wake-receipt/<rid>`; reconcile-retry proven on a live probe — run after lead merges + re-syncs the listener to `~/.brisen-lab` + kickstarts.
- Controller-side ACs (AC1/AC2/AC4) are phase-1 (deputy-codex), already merged/live.

## Not touched
- `cockpit_controller.py` (deputy-codex phase-1, merged). Listener-only change.
