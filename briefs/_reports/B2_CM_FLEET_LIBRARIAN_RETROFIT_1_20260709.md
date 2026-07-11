# B2 Ship Report — CM_FLEET_LIBRARIAN_RETROFIT_1 (2026-07-09)

Dispatched by lead (bus #7571, re-route from b3). Director-ratified 2026-07-09 ~00:05Z.
Vault worktree: `~/baker-vault-b2-retrofit` on `b2/cm-fleet-librarian-retrofit-1`.

## PR

| Repo | PR | Commit | Status |
|---|---|---|---|
| baker-vault | #149 | `85f1fd7` | Open — awaiting G2 deputy delta-verify + G3 codex review |

Picker-side files (`~/bm-CM-1..4/`) deployed locally. No separate PR (picker dirs are not
repo-tracked for per-seat CLAUDE.md / .claude/settings.json / scripts — same pattern as
Librarian install row 1 deviation, #7454).

## Vault-side changes (PR #149)

| File | Action |
|---|---|
| `_ops/agents/_universal/cm/orientation-v2.md` | NEW — shared, $BAKER_ROLE-parameterized |
| `_ops/agents/_universal/cm/scripts/cm_drain.sh` | NEW — kill-switch parameterized (CM_N_DISABLED) |
| `_ops/agents/_universal/cm/scripts/cm_bus_reply.sh` | NEW — reply-only, $BAKER_ROLE mailbox |
| `_ops/agents/_universal/cm/scripts/cm_commit.sh` | NEW — wiki/_library/** only |
| `_ops/agents/_universal/cm/scripts/cm_sql.sh` | NEW — SELECT-only, same validation as librarian |
| `_ops/agents/_universal/cm/scripts/cm_sql_guard.sh` | NEW — PreToolUse guard |
| `_ops/agents/_universal/cm/scripts/cm_receipt_check.sh` | NEW — delegates to cm_receipt_check.py |
| `_ops/agents/_universal/cm/cm_receipt_check.py` | NEW — identical logic to librarian's |
| `_ops/agents/_universal/cm/cm_seeded_violation_tests.sh` | NEW — 19-test cage harness |
| `_ops/agents/_universal/cm/CLAUDE.md.reference` | NEW — picker charter template |
| `_ops/agents/_universal/cm/cm-picker-settings.reference.json` | NEW — deny list + hooks template |
| `_ops/agents/_universal/cm/cm-{1..4}-design.md` | MODIFIED — §retrofit-v2 appended |
| `_ops/hooks/cm_write_cage.sh` | NEW — wiki/_library/** allowlist cage |
| `_ops/hooks/cm_bash_cage.sh` | NEW — CM wrappers + read-only allow-list |

## Picker-side changes (deployed locally, ~/bm-CM-1..4)

| Component | CM-1 | CM-2 | CM-3 | CM-4 |
|---|---|---|---|---|
| CLAUDE.md | ✅ deployed | ✅ deployed | ✅ deployed | ✅ deployed |
| .claude/settings.json | ✅ model=claude-haiku-4-5-20251001 | ✅ model=claude-sonnet-4-6 | ✅ model=claude-sonnet-4-6 | ✅ model=claude-sonnet-4-6 |
| .claude/hooks/cm_write_cage.sh | ✅ | ✅ | ✅ | ✅ |
| .claude/hooks/cm_bash_cage.sh | ✅ | ✅ | ✅ | ✅ |
| .claude/hooks/cm_sql_guard.sh | ✅ | ✅ | ✅ | ✅ |
| scripts/cm_drain.sh | ✅ | ✅ | ✅ | ✅ |
| scripts/cm_bus_reply.sh | ✅ | ✅ | ✅ | ✅ |
| scripts/cm_commit.sh | ✅ | ✅ | ✅ | ✅ |
| scripts/cm_sql.sh | ✅ | ✅ | ✅ | ✅ |
| scripts/cm_sql_guard.sh | ✅ | ✅ | ✅ | ✅ |
| scripts/cm_receipt_check.sh | ✅ | ✅ | ✅ | ✅ |
| scripts/cm_receipt_check.py | ✅ | ✅ | ✅ | ✅ |

## Quality Checkpoint 1: Violation tests (cage must hold — all before rung-1 hunts)

```
CM-1: 19 passed, 0 failed
CM-2: 19 passed, 0 failed
CM-3: 19 passed, 0 failed
CM-4: 19 passed, 0 failed
```

Test coverage: (a) write-cage matters REJECT / _library ALLOW, (b) baker_raw_write deny,
(c) non-SELECT SQL REJECT + WITH-CTE REJECT, (d) bus reply-only, (e) crash-unacked + kill switch
(CM_N_DISABLED), (f) **ClaimsMax NOT in deny list** (CM specialist delta confirmed), (g) SQL
edge cases, (h) drain body-read subcommand present + numeric-id guard + recipient-scoped endpoint.

## Done-rubric status

| Item | Status |
|---|---|
| 1. 4/4 seats: violation-tests green | ✅ 19/19 per seat, 4/4 seats |
| 2. 4/4 seats: 8/8 seeded hunts graded vs key | ⏳ PENDING — awaiting G2/G3 merge → live seats |
| 3. 0 fabrication-canary breaches | ⏳ PENDING — awaiting live hunts |
| 4. Model pins live-proven (session banner) | ⏳ PARTIAL — settings.json pins structural; zshrc --model flag is lead Tier-B action (see Open Items) |
| 5. Vault PR merged + ship report on bus | ⏳ PENDING G2/G3 gates |

## Open items (post-merge, lead Tier-B)

1. **zshrc --model flag** (Tier-B): CM-1..4 zshrc entries (`cm1()..cm4()`) have no `--model`
   flag. The settings.json `model` field provides structural enforcement (live-verifiable via
   session banner). Lead to add `--model claude-haiku-4-5-20251001` to `cm1()` and
   `--model claude-sonnet-4-6` to `cm2()/cm3()/cm4()` for belt-and-suspenders (same pattern
   as librarian row 2). This is the mechanism the brief references when it says "read it,
   don't guess" — librarian_settings.reference.json also has no model field; pin is in zshrc.

2. **Rung-1 seeded hunts** (post-merge): re-seed Librarian's 8 known-answer hunts (key:
   `~/bm-b1/briefs/_reports/B1_LIBRARIAN_PART_C_SEEDED_HUNTS_KEY_20260708.md`) to each CM
   mailbox; grade vs key; receipt-check per answer; per-seat tally + cost read to lead.

3. ~~**Bash cage ENFORCE flip**~~ **RESOLVED at ship** (codex G3 P1 #7581, lead #7582):
   shipped enforce-ON. CM_BASH_CAGE_ENFORCE="1" in cm-picker-settings.reference.json + all
   4 deployed picker settings, mirroring librarian/picker-settings.reference.json:3. Script
   fallback stays :-0 identical to librarian_bash_cage.sh:33 (enforce delivered via settings,
   not a script-default divergence). Ramp dropped (moot). Verified: seeded suite 19/19 x4
   seats + end-to-end smoke (raw curl/python3 BLOCK, read-only/vetted ALLOW). Fix commit
   44445bf on b2/cm-fleet-librarian-retrofit-1.

## Gate status
- G2: deputy delta-verify on vault PR #149 — REQUESTED
- G3: codex review — REQUEST_CHANGES on 85f1fd7 (P1 #7581); fix pushed 44445bf, re-requested
