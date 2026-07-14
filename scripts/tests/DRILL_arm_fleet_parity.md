# ARM Fleet Parity Two-Sided Drill

This runbook is the written GO-gate for each arming-ladder step. A step does
not advance on repo tests alone.

## Repo Side

Run from the canonical `baker-master` checkout:

```bash
bash scripts/tests/test_arm_alarm.sh
bash scripts/tests/test_arm_cadence.sh
bash scripts/tests/test_arm_fleet_parity.sh
bash scripts/tests/test_fleet_client_parity.sh
```

Required evidence:

- Each installer reports `RESULT: CLEAN` for a current deployed worker.
- A one-byte deployed-worker mutation reports the sha mismatch and exits non-zero.
- A plist interval mismatch reports the expected/current interval difference.
- An absent manifest job reports `RED ... NOT-INSTALLED`, never a skip.
- A cadence connection failure carries `health=db_unreachable` and the alarm
  names `db_unreachable(cadence)`.
- A fresh `health=degraded` cadence snapshot does not page.
- `ARM_ALARM_MISSING_IS_RED=1` turns a never-seen marker into RED.
- A stale client copy reports `STALE` and `missing the started-emit capability`.
- An unconfirmable client seat is RED in the roll-up.

## Host Side

Run on the always-on ARM host after the code is merged and the check bundle is
refreshed:

```bash
bash scripts/arm_fleet_parity.sh
```

Record the exact output and commit SHA. Then, in the isolated ARM deploy
directory, deliberately append one byte to one deployed worker and run:

```bash
bash scripts/arm_fleet_parity.sh
```

The affected job must report `DRIFT` within one sentinel cycle. Re-run its
installer, then run the sweep again; every expected host job must return
`CLEAN`.

## Client Side

The dispatcher supplies explicit seat repositories to the roll-up. The
roll-up uses each seat's local `git rev-parse HEAD` plus the working-tree
parity check; an unreadable seat is RED:

```bash
bash scripts/fleet_client_parity.sh --rollup --capability-probe \
  --seat aihead1="$HOME/bm-aihead1" \
  --seat aihead2="$HOME/bm-aihead2"
```

Every seat in the manifest's `distributed_to` classes must report `CLEAN`
before the step-4 `acked-not-started` drain measurement is trusted. Record the
seat names, local HEADs, and the complete parity output in the ladder evidence.

## GO Record

For each ladder step, record:

```text
step:
repo_tests:
host_sweep_before:
host_mutation:
host_sweep_after:
client_rollup:
all_distributed_seats_clean:
lead_go:
```

The `MISSING_IS_RED=1` flip remains OFF until the lead records GO on the
two-sided drill. After the live drill, post `POST_DEPLOY_AC_VERDICT v1`.
