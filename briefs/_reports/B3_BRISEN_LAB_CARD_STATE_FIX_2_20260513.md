# B3 ship report — BRISEN_LAB_CARD_STATE_FIX_2

**Brief:** `briefs/BRIEF_BRISEN_LAB_CARD_STATE_FIX_2.md`
**Branch (baker-master):** `b3/brisen-lab-card-state-fix-2` off `main@b74da09`
**Branch (brisen-lab):** `b3/brisen-lab-card-state-fix-2` off `main@0bc8e5c`
**Branch (baker-vault):** direct push to `main`
**Date:** 2026-05-13

---

## PRs / commits

| Repo | Action | Ref | Status |
|---|---|---|---|
| `vallen300-bit/baker-master` | PR #201 | `b3/brisen-lab-card-state-fix-2` | OPEN |
| `vallen300-bit/brisen-lab` | PR #16 | `b3/brisen-lab-card-state-fix-2` | OPEN |
| `vallen300-bit/baker-vault` | direct push (CHANDA Inv 9) | `main` @ `d64c07d` | MERGED |

## Fixes shipped

### Fix 1 — Worker ack-on-ship hygiene (baker-master)

- NEW `scripts/ack_dispatch_msgs.sh` — sweep-ack inbox messages tied to a shipped brief. Topic patterns: `dispatch/<slug>(-|$)`, `request-changes/<slug>(-|$)`, `scope-amendment/<slug>(-|$)`, `ship/<slug>-v*-rerun`.
- Non-fatal on every network/HTTP failure path; exits 0 always when config is valid.
- `curl -sS` (no `-f`) on the ack POST so the real HTTP code is captured + logged on 4xx instead of collapsing to `"000"` via the `-f` exit-22 fallback.
- 5 pytest cases.

### Fix 2 — Forge daemon stale local clone (baker-master)

- NEW `sync_clone_to_main()` — quiet `git fetch origin main` (always) + `git merge --ff-only origin/main` (only when on main/master). Non-fatal.
- `classify_mailbox()` branch-aware: feature-branch clones read mailbox state from `origin/main` via `git cat-file -e` + `git show origin/main:...`. Falls back to local file when origin/main has no fetched data.
- Iteration loop calls `sync_clone_to_main` between `pick_active_clone` and `snapshot_one`. `FORGE_SYNC_DISABLED=1` short-circuits sync in tests.
- 2 new bash test cases (H + I) on top of 7 existing.

### Fix 3 — Lab UI 60s badge-sanity poll (brisen-lab)

- Extract one-shot init reconciliation into `reconcileBadgeStateFromServer()` (returns list of dirty aliases).
- NEW `pollBadgeSanity()` calls reconciler + dispatches re-renders via the same alias → render-function table the SSE `bus_badge_change` handler uses.
- `setInterval(pollBadgeSanity, 60_000)` wires it up at module load.
- `loadInitialState()` now delegates initial fetch through the helper — single source of truth.

### Process doc — §3.1 (baker-vault, direct push)

- Adds `§3.1 Bus inbox ack-on-ship` to `_ops/processes/b-code-dispatch-coordination.md` (committed at `d64c07d`).
- Documents the `ack_dispatch_msgs.sh` step + non-fatal fallback policy.

---

## Ship-gate output (literal)

### pytest (Fix 1)

```
$ python3.12 -m pytest tests/test_ack_dispatch_msgs.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 5 items

tests/test_ack_dispatch_msgs.py::test_happy_path_three_matching_messages PASSED
tests/test_ack_dispatch_msgs.py::test_already_acked_message_is_skipped PASSED
tests/test_ack_dispatch_msgs.py::test_slug_not_present_zero_acked_exit_zero PASSED
tests/test_ack_dispatch_msgs.py::test_key_fetch_failure_exit_2 PASSED
tests/test_ack_dispatch_msgs.py::test_single_ack_http_error_is_non_fatal PASSED

============================== 5 passed in 1.59s ===============================
```

### bash tests (Fix 2, 7 existing + 2 new)

```
$ bash tests/test_forge_snapshot_push.sh

PASS: Case A — heading-style mailbox, single clone.
PASS: Case B — YAML frontmatter mailbox extracts brief: field.
PASS: Case C — two-clone alias picks pending-mailbox clone (overrides recency).
PASS: Case D — two-clone alias falls back to recency tiebreaker.
PASS: Case E — two non-git candidate paths fall back to first; daemon still emits stderr without crash.
PASS: Case F — two-clone alias picks COMPLETE-mailbox clone over empty sibling.
PASS: Case G — frontmatter status: DROPPED authoritative over filename _PENDING suffix.
PASS: Case H — feature-branch clone reads mailbox state from origin/main.
PASS: Case I — on-main clone uses local frontmatter (FIX_1 regression check).

All 9 cases PASS.
```

### check_singletons

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### Mirror install + launchctl kickstart

```
$ cp ~/bm-b3/scripts/forge_snapshot_push.sh "/Users/dimitry/Library/Application Support/baker/forge_snapshot_push.sh"
$ shasum "/Users/dimitry/Library/Application Support/baker/forge_snapshot_push.sh"
73ea9402815a9a20970b81f68bb8d076d8de5987  /Users/dimitry/Library/Application Support/baker/forge_snapshot_push.sh

$ launchctl kickstart -k "gui/$(id -u)/com.baker.forge-snapshot-push"
$ launchctl print "gui/$(id -u)/com.baker.forge-snapshot-push" | grep -E "state|exit code|runs"
	state = running
	runs = 1348
	last exit code = 0
		state = active
		state = active
```

### Fix 1 dogfood — ack against this dispatch's msg #210

```
$ BAKER_ROLE=b3 ./scripts/ack_dispatch_msgs.sh --brief-slug BRISEN_LAB_CARD_STATE_FIX_2
[ack] b3/210: OK
[ack] acked 1 of 1 messages for BRISEN_LAB_CARD_STATE_FIX_2 on b3's inbox
```

End-to-end verification: helper resolves 1Password key for b3 → fetches `/msg/b3?limit=50` → filters by topic pattern `dispatch/brisen_lab_card_state_fix_2` → POSTs `/msg/210/ack` → HTTP 200.

---

## Gates required (post-merge, owned by AH1/AH2)

- [ ] AH2 `/security-review` on baker-master PR #201 (helper reads `op` credentials)
- [ ] picker-architect on PR #201
- [ ] picker-architect on brisen-lab PR #16
- [ ] `feature-dev:code-reviewer` 2nd-pass on PR #201 (Tier-B trigger #4)
- [ ] `feature-dev:code-reviewer` 2nd-pass on brisen-lab PR #16

## Manual end-to-end (post-merge)

3. **Fix 1 — synthetic dispatch zombie sweep:** dispatch `dispatch/ZOMBIE_TEST_1` to b4 via `bus_post.sh`; run `BAKER_ROLE=b4 scripts/ack_dispatch_msgs.sh --brief-slug ZOMBIE_TEST_1`; verify 0 unread on inbox via direct curl.
4. **Fix 2 — feature-branch + mailbox flip:** commit mailbox flip on `~/bm-aihead1` while a B-code is on a feature branch; reload Lab within 60s; verify card flips green.
5. **Fix 3 — DevTools stale-badge:** `state.busBadge.lead = { unacked_count: 99, oldest_unacked_age_sec: 999999 }; renderCard("lead");` → wait 60s → expect auto-reconcile to server-reported value.

---

## Notes / known follow-ups

- Mirror-installed forge_snapshot_push.sh runs from `/Users/dimitry/Library/Application Support/baker/` **before** PR #201 merges. If AH2 review forces changes, AH1 re-copies + kickstarts post-merge.
- 1Password CLI dependency: the helper script's runtime path uses `op read`; the test path injects `BRISEN_LAB_TERMINAL_KEY_OVERRIDE` to keep pytest hermetic.
- Per brief §Do NOT Touch: no changes to `scripts/forge_snapshot_push.sh:189-241` (FIX_1 frontmatter classifier core); only ADDED `sync_clone_to_main` + branch-aware reads.
