# B4 ship report — ARM_ALARM_RECIPIENT_SPLIT_1

- **Brief:** BRIEF_ARM_ALARM_RECIPIENT_SPLIT_1 (deputy dispatch #11683, lead PASS + rider #11679)
- **PR:** #567 → base `main`, head `b4/arm-alarm-recipient-split`
- **Commits:** `4e19d825` (feature) + `10b97d39` (codex P2 fix)
- **Class:** production implementation — delivery-path — HIGH-IMPACT
- **Date:** 2026-07-15

## What shipped
Per-kind email recipient routing in `scripts/arm_alarm_check.sh`. The delivery
path resolves `ARM_ALARM_EMAIL_TO_<SOURCE>` (upper-cased incident source, e.g.
`ARM_ALARM_EMAIL_TO_SEMANTIC`) and, when set + non-blank, sends there; otherwise
falls back to `EMAIL_TO`. Routine enforced semantic red → lead; report/canary
emergencies → Director ops address. Closes codex F3 and clears the prerequisite
for arming `ARM_ALARM_SEMANTIC_ENFORCE=1` without paging the Director on routine
semantic delivery (lead ruling #11674/#11679).

- `resolve_recipient(source)` + fail-loud resolve log line (never a silent no-send).
- `send_email(subject, body, to)` / `deliver(subject, body, to)` — explicit recipient.
- Source (`ik.split(":",1)[0]`) threaded through FIRE, STILL-FAILING, and RECOVERY.
- Recipient resolved once at first fire and **pinned** on the incident record
  (`rec["recipient"]`); STILL-FAILING/RECOVERY reuse the pin, cleared on recovery.

## Done rubric answered
- **AC1** per-kind resolver, threaded through fire/recovery/still-failing — ✅
- **AC2** semantic→lead, report/canary→Director; RECOVERY + STILL-FAILING resolve
  to the SAME recipient as fire (rider #11679) — ✅ tests 28, 29, 31
- **AC3** no per-kind env ⇒ every kind → `EMAIL_TO` byte-identical to today — ✅ test 27
- **AC4** delivery-truth + dedupe/backoff/cooldown state machine unchanged; suite
  green + new tests added (`recipient` is an additive state field) — ✅
- **AC5** fail-loud fallback + per-kind resolve log lines; no silent no-send — ✅ tests 27, 28
- **AC6** `install_arm_alarm_job.sh --check` unaffected (installer logic untouched) — ✅
- **AC7** deploy/env wiring documented in the script header routing-map block — ✅

## Tests (literal)
`bash scripts/tests/test_arm_alarm.sh`
```
arm_alarm tests: 100 passed, 0 failed
```
13 new tests (27–31 + subassertions), all written FIRST and confirmed RED on the
unmodified script (semantic→Director, no resolve logs, per-kind ignored, and the
recovery-to-Director misfire reproduced) before implementation.

## Codex verify (mandatory high-impact gate)
Verdict: **PASS-WITH-NOTES** (gpt-5.6-luna, effort high). Two findings:
- **P1** — launchd does not yet provision `ARM_ALARM_EMAIL_TO_SEMANTIC`. Correctly
  out-of-scope for this diff (installer-owned, documented in the header deploy
  note). **Deploy prerequisite, flagged below — not a code defect.**
- **P2** — each delivery site re-resolved from live env; a mid-incident env change
  could misroute a RECOVERY. **Resolved** in commit `10b97d39` (pin recipient on
  the incident record) with a dedicated regression test (test 31), per codex's own
  recommended fix. All other 7 verify points: clean (implicit PASS).

## Out of scope / deploy prerequisite for deputy
`install_arm_alarm_job.sh` logic and `scripts/launchd/com.baker.arm-alarm.plist`
were **not** modified (per brief "Do NOT Touch"). The installer regenerates the
plist from the template on every reinstall, so to make `ARM_ALARM_EMAIL_TO_SEMANTIC=<lead>`
survive a fleet reinstall it must be added to the template's `EnvironmentVariables`
dict — an **installer-owned follow-up**. Until that lands, the semantic env must be
set host-side each deploy, or `ARM_ALARM_SEMANTIC_ENFORCE=1` arming will route
semantic red back to the Director (P1). Deputy owns the post-merge live-AC drill on
the fleet (semantic→lead, emergency→Director, incl. a semantic recovery→lead).

## Gate chain status
build (TDD) ✅ → codex verify (PASS-WITH-NOTES, P2 resolved) ✅ → **awaiting deputy
cross-lane review → lead merge** → fleet reinstall (`--check` exit 0 all hosts) →
deputy live-AC drill → `ARM_ALARM_SEMANTIC_ENFORCE=1` hard gate cleared.
