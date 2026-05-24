---
brief_id: HAG_WORKERS_PHASE_1
target: b1
reply_to: lead
shipped_at: 2026-05-24T12:13:48Z
status: shipped (Fix/Features 1, 2, 4, 5, 6 + SOP Row 12 / Supp AC A1) — AH1 Tier-B post-merge ops queued (1P keys + Render env + clones + pusher redeploy + Supp AC A3); Supp AC B1 shell aliases deferred to fast-follow per mailbox LOW-priority note
baker_vault_pr: https://github.com/vallen300-bit/baker-vault/pull/110
baker_vault_anchor: 00cbe92
baker_master_pr: https://github.com/vallen300-bit/baker-master/pull/254
baker_master_anchor: f1b41c9
brisen_lab_pr: https://github.com/vallen300-bit/brisen-lab/pull/32
brisen_lab_anchor: 594b709
bus_ship_msg_id: 855
bus_dispatch_msg_id: 850
---

# B1 ship report — HAG_WORKERS_PHASE_1

## Bottom line

Three PRs open, all tests green, all install-SOP 12-row sites touched. 5 new worker slugs (`CM-1`, `CM-2`, `CM-3`, `CM-4`, `hag-filer`) are bus-ready pending AH1 Tier-B post-merge execution (1P keys + Render env + clones + pusher launchd redeploy). Phase 1 MVP is shippable as soon as gate chain clears + Tier-B ops fire.

## PR anchors

| Repo | PR | Branch | HEAD | Fix/Features |
|---|---|---|---|---|
| baker-vault | [#110](https://github.com/vallen300-bit/baker-vault/pull/110) | `hag-workers-phase-1-memory` | `00cbe92` | F6 (memory scaffolds) |
| baker-master | [#254](https://github.com/vallen300-bit/baker-master/pull/254) | `b1/hag-workers-phase-1` | `f1b41c9` | F2 (bus_post), F4 (role-context), F5 (session-start hook), SOP Row 12 / Supp AC A1 (snapshot pusher) |
| brisen-lab | [#32](https://github.com/vallen300-bit/brisen-lab/pull/32) | `b1/hag-workers-phase-1-brisen-lab` | `594b709` | F1 (bus daemon slug registration: app.py + bus.py × 2 + db.py + lifecycle.py + tests) |

## Files touched (against install-SOP 12-row wiring map)

| SOP Row | Site | Repo | Status |
|---|---|---|---|
| 1 Picker folder | `~/bm-CM-N`, `~/bm-hag-filer` | filesystem | Deferred — AH1 Tier-B post-merge per brief Step 3.1 (script-side ready via session-start-role.sh cwd cases) |
| 2 Shell alias | `~/.zshrc` | local | **Deferred** to fast-follow (Supp AC B1 LOW priority — workers run in Cowork App not Terminal) |
| 3 Terminal.app profile | Mac UI | local | Deferred — same rationale as Row 2 |
| 4 Picker CLAUDE.md | per-clone | filesystem | Deferred — paired with Row 1 clones |
| 5 bus_post.sh recipient whitelist | `scripts/bus_post.sh:47` | baker-master | ✅ PR #254 |
| 6 bus_post.sh sender mapping | `scripts/bus_post.sh:71-75` | baker-master | ✅ PR #254 |
| 7 SessionStart drain hook | `~/.claude/hooks/session-start-bus-drain.sh` (user-global, NOT repo) | local | Deferred — AH1 Tier-B (not in PR scope per install-SOP) |
| 8 1Password terminal key | `op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_<slug>/credential` × 5 | 1P | Deferred — AH1 Tier-B per brief Step 1.6 |
| 9 Render env | `BRISEN_LAB_TERMINAL_KEYS` JSON | Render | Deferred — AH1 Tier-B per brief Step 1.5 (+ explicit POST /deploys per foot-gun #5) |
| 10 Brisen Lab front-end | `static/index.html` + `app.js` | brisen-lab | **Out of scope** — workers are bus-only for Phase 1 MVP; visual scoped to BRIEF_BRISEN_LAB_REDESIGN_PHASE_1 (matches researcher PR #29 pattern) |
| 11(a) bus.py `KNOWN_CARD_SLUGS` | `bus.py:895` | brisen-lab | ✅ PR #32 |
| 11(b) bus.py `_build_terminals_response` for-loop | `bus.py:1005` | brisen-lab | ✅ PR #32 |
| 11(c) app.py `TERMINALS` | `app.py:40` | brisen-lab | ✅ PR #32 |
| 11(d) Tests `test_a3_a8_a9_bus.py` | tests | brisen-lab | ✅ PR #32 (parametrized × 5 slugs × 2 functions = 10 new tests) |
| 12 Snapshot pusher | `scripts/forge_snapshot_push.sh:61-75` | baker-master | ✅ PR #254 (vault-path per researcher-scar rule) |
| — Snapshot pusher tests | `tests/test_forge_snapshot_push.sh` | baker-master | ✅ PR #254 (Cases N-R, all PASS) |
| — Memory scaffolds (F6) | `_ops/agents/_universal/cm/{op,lt,arch}.md` + `hagenauer-desk/workers/filer/{op,lt,arch}.md` | baker-vault | ✅ PR #110 |

## Ship-gate evidence

### Brief Ship Gate (literal pytest + bash output)

**`pytest tests/test_a3_a8_a9_bus.py -v` (brisen-lab, `TEST_DATABASE_URL_BRISEN_LAB` provisioned via 1Password):**

```
tests/test_a3_a8_a9_bus.py::test_bus_badge_change_emitted_for_hag_workers_phase_1[CM-1] PASSED
tests/test_a3_a8_a9_bus.py::test_bus_badge_change_emitted_for_hag_workers_phase_1[CM-2] PASSED
tests/test_a3_a8_a9_bus.py::test_bus_badge_change_emitted_for_hag_workers_phase_1[CM-3] PASSED
tests/test_a3_a8_a9_bus.py::test_bus_badge_change_emitted_for_hag_workers_phase_1[CM-4] PASSED
tests/test_a3_a8_a9_bus.py::test_bus_badge_change_emitted_for_hag_workers_phase_1[hag-filer] PASSED
tests/test_a3_a8_a9_bus.py::test_v2_terminals_response_includes_hag_workers_phase_1[CM-1] PASSED
tests/test_a3_a8_a9_bus.py::test_v2_terminals_response_includes_hag_workers_phase_1[CM-2] PASSED
tests/test_a3_a8_a9_bus.py::test_v2_terminals_response_includes_hag_workers_phase_1[CM-3] PASSED
tests/test_a3_a8_a9_bus.py::test_v2_terminals_response_includes_hag_workers_phase_1[CM-4] PASSED
tests/test_a3_a8_a9_bus.py::test_v2_terminals_response_includes_hag_workers_phase_1[hag-filer] PASSED
================== 27 passed, 3 warnings in 193.30s ==================
```

**`bash tests/test_forge_snapshot_push.sh` (baker-master):**

```
PASS: Case N — non-b-code single-clone slug (CM-1) — mailbox stays n/a.
PASS: Case O — non-b-code single-clone slug (CM-2) — mailbox stays n/a.
PASS: Case P — non-b-code single-clone slug (CM-3) — mailbox stays n/a.
PASS: Case Q — non-b-code single-clone slug (CM-4) — mailbox stays n/a.
PASS: Case R — non-b-code single-clone slug (hag-filer) — mailbox stays n/a.

All 19 cases PASS.
```

### Additional checks

- `bash -n` syntax clean on `scripts/bus_post.sh`, `.claude/hooks/session-start-role.sh`, `scripts/forge_snapshot_push.sh`
- `bash scripts/check_singletons.sh`: `OK: No singleton violations found.`
- Session-start hook smoke (synthetic `/tmp/bm-CM-1` cwd): correctly resolves `BAKER_ROLE=CM-1` from cwd fallback
- Pre-flight grep per install-SOP §"Known foot-guns" #1 (3 matches expected): ✅ 3/3 found (`bus.py:895` + `bus.py:1005` + `app.py:40`)

## Design conflicts surfaced (per Mnilax "surface conflicts, don't average")

1. **db.py `WORKER_AUTHORITY_SEED` tier = 0** (brief Step 1.3 said `3` with comment "mirrors b1-b4 tier", but b1-b4 are actually tier 0 in the existing seed; design specs confirm workers have no Tier B). Picked `0` to match design + b1-b4 actual; brief's `3` reads as copy-paste typo, but the "mirrors b1-b4" intent is unambiguous. Flagged for lead review.
2. **lifecycle.py `H4_THRESHOLDS` = 5** for all 5 new slugs. Brief said `5` with comment "same as b1-b4" — comment wrong (b1-b5 actually = 15), but `5` is correct for stateless workers (mirrors `cortex` strict pattern). Kept brief's value.
3. **`forge_snapshot_push.sh` repo-path = `/Users/dimitry/baker-vault`** for all 5 (NOT `$HOME/bm-CM-N`). Per install-SOP §"Second-pass lived foot-gun" researcher scar rule (PR #29 brief used `~/bm-researcher` which has no `.git`; pusher errored "repo missing" every 30s until hot-fix `7fb9072` 2026-05-22). Mailbox Supp AC A1 actually proposed `$HOME/bm-CM-N` paths but its own footnote calls out the vault-fallback rule — surfaced to lead as conflict, chose vault per the lesson. CMs/Filer clones are AH1 Tier-B post-merge (brief Step 3.1); using vault path makes pusher robust pre-clone-creation.

## Bash 3.2 compat catch

macOS default bash is 3.2; `${VAR^^}` parameter expansion is Bash 4+. New test loop in `tests/test_forge_snapshot_push.sh` uses `echo "$VAR" | tr '[:lower:]' '[:upper:]'` instead. Caught during local test run (`bad substitution` error); fixed before commit.

## Out of scope (AH1 Tier-B post-merge per install-SOP §"Post-merge AH1 Tier-B execution checklist")

1. Generate 5 × `op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_<slug>/credential` (Step 1.6) — `openssl rand -hex 32` per slug
2. Update Render `BRISEN_LAB_TERMINAL_KEYS` JSON + explicit `POST /deploys` (Step 1.5 + foot-gun #5)
3. Clone `~/bm-CM-1..4` + `~/bm-hag-filer` (Step 3.1) — set git identity per slug (Step 3.2)
4. Snapshot pusher launchd redeploy on MacBook + Mac Mini (Supp AC A3): `FORGE_KEY=$(plutil -extract EnvironmentVariables.FORGE_KEY raw ~/Library/LaunchAgents/com.baker.forge-snapshot-push.plist) bash scripts/install_forge_push.sh`
5. End-to-end smoke per brief Quality Checkpoint 8 (lead → CM-1 dispatch + reply)

## Deferred to fast-follow

- **Supp AC B1 shell aliases** (LOW priority per mailbox) — 5 functions in `~/.zshrc` for Terminal.app pattern. Workers run in Cowork App not Terminal; skip unless time-pressured.
- **Front-end card slot** (install-SOP Row 10) — separate brief, deferred per Phase 1 MVP scope. Pattern matches researcher PR #29 (bus-only first, visual later).
- **Phase 1.5 automation** — spawn-cm.sh + filer-daemon.py + hag-dispatch.sh (per brief §"Phase 1.5"). Brief explicitly scopes these as separate dispatch after MVP works manually.

## Anchors

- Bus dispatch #850 from `lead` 2026-05-24T11:53:21Z (ACKed)
- Bus reply #851 to `lead` 2026-05-24T11:54:53Z (orientation confirm)
- Bus ship #855 to `lead` 2026-05-24T12:13:48Z (3-PR ship report)
- Director ratified 5-design batch 2026-05-24 (baker-vault `763e8fc`)
- Filing-protocol v2 D-014 2026-05-24 (`9902430`) — hag-filer cross-blocker CLOSED
- install-SOP: `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md`
- Brief: `~/baker-vault/_ops/briefs/BRIEF_HAG_WORKERS_PHASE_1.md`
- Mailbox: `briefs/_tasks/CODE_1_PENDING.md` (commit `a9b2677`)
