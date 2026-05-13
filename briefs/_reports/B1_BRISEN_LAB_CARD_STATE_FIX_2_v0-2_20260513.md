# B1 ship report — BRISEN_LAB_CARD_STATE_FIX_2 fast-follow v0-2

**Brief:** `briefs/BRIEF_BRISEN_LAB_CARD_STATE_FIX_2.md`
**Phase:** fast-follow v0-2 (post-AH1 REQUEST_CHANGES on PR #201 + PR #16)
**Re-dispatch:** B3 occupied with DEADLINE_SIGNAL_HYGIENE_1; B1 picked per Director directive 2026-05-13
**Branch (baker-master):** `b3/brisen-lab-card-state-fix-2` @ `698b9a6`
**Branch (brisen-lab):** `b3/brisen-lab-card-state-fix-2` @ `e56cbf4`
**Date:** 2026-05-13

---

## PRs updated (fix-by-fix on existing branches — no new PRs)

| Repo | PR | Action | Head |
|---|---|---|---|
| `vallen300-bit/baker-master` | #201 | new commit `698b9a6` pushed to existing branch | `b3/brisen-lab-card-state-fix-2` |
| `vallen300-bit/brisen-lab` | #16 | new commit `e56cbf4` pushed to existing branch | `b3/brisen-lab-card-state-fix-2` |

---

## PR #201 — fix-by-fix closure

### HIGH — `extract_brief_name()` is not branch-aware

**Closed by** `698b9a6`:

- `classify_mailbox` output extended from 2-field `status|path` to 3-field
  `status|path|source` where `source` is `local` or `origin_main` (plus the
  empty case `empty||` for parser consistency).
- `snapshot_one` parses via `IFS='|' read -r mailbox_status mailbox_path mailbox_source`,
  then branches: when source is `origin_main`, streams
  `git show origin/main:<rel_path>` through the new
  `extract_brief_name_from_content` helper instead of calling
  `extract_brief_name` on a non-existent local path.
- New `extract_brief_name_from_content` mirrors `extract_brief_name`'s 3-step
  fallback (frontmatter `brief:` then first `# heading` then `(unparseable)`)
  but operates on stdin so the `[[ -f "$f" ]]` short-circuit doesn't bite.
- `pick_active_clone` unchanged — it uses `${mbox_class%%|*}` which is
  forward-compatible with the third field (still returns just `status`).

### MEDIUM 1 — Case H pre-fetched + `FORGE_SYNC_DISABLED=1` masked sync+classify integration

**Closed by** Case H' (test_forge_snapshot_push.sh):

- New fixture seeds bare origin + clones onto feature branch + flips origin/main
  to COMPLETE behind the clone's back.
- Daemon runs WITHOUT `FORGE_SYNC_DISABLED=1` and WITHOUT pre-fetching the
  clone. `sync_clone_to_main` itself must do the fetch before `classify_mailbox`
  needs origin/main.
- Asserts `mailbox_status == complete` AND `mailbox_brief_name == INTEGRATION_CHECK_BRIEF_1`
  — full pipeline green.

### MEDIUM 2 — cold-clone fallback never exercised

**Closed by** Case K (test_forge_snapshot_push.sh):

- New fixture clones + creates feature branch + strips
  `.git/refs/remotes/origin/main` + filters `packed-refs` + re-points
  `origin` remote to `file:///dev/null/does-not-exist.git` so
  `sync_clone_to_main`'s fetch can't refresh it.
- `git cat-file -e origin/main:...` returns non-zero for every probe —
  classify_mailbox falls through to the local-file fallback path
  (lines 296-307) and returns the local frontmatter status.
- Asserts `mailbox_status == in_progress` AND
  `mailbox_brief_name == COLD_CLONE_LOCAL_FALLBACK_1`.

### HIGH coverage check — Case J (no local mailbox file)

**Added** Case J to lock down the real-world trigger: B-code creates feature
branch BEFORE AH1 dispatches a new brief to main. Feature branch's working
tree never receives the new `CODE_N_PENDING.md`. Pre-fix: blank card subtitle.

- Fixture: bare origin seeded with NO mailbox, then clone + feature branch,
  then seed dir THEN adds the mailbox + pushes.
- Sanity assertion: local file does NOT exist (`! -f`).
- Asserts `mailbox_status == pending` AND
  `mailbox_brief_name == ORIGIN_ONLY_BRIEF_1` (streamed from origin/main).

### LOWs

- **L1** (`ack_dispatch_msgs.sh:150`) — for-loop switched to `read -ra ACK_IDS`
  array + `"${ACK_IDS[@]}"` iteration. IFS-defensive and gives an explicit
  TOTAL count without `wc -w`.
- **L2** (`ack_dispatch_msgs.sh:25-26`) — comment block added explaining why
  `set -u + pipefail` without `-e` is deliberate: every network/HTTP failure
  path must be non-fatal; `-e` would short-circuit the `|| { ... }` guards
  downstream.
- **L3** (`ack_dispatch_msgs.sh:91`) — dropped `-f` from inbox curl for parity
  with the per-ack POST. `-f` swallows 4xx and emits exit 22, which would
  collapse the response body and lose the HTTP code for diagnosis. Without
  `-f`, curl writes the body to stdout; the python parser yields zero matches
  on non-`messages` JSON and routes through the "no unacked messages" exit.
- **L4** (new test T6) — `test_op_binary_absent_from_path_exits_2`: runs with
  PATH stripped of `/opt/homebrew/bin` and `/usr/local/bin` (op CLI install
  dirs). Asserts exit 2 + "1Password fetch failed" stderr — proves the
  missing-binary exit code (127) propagates through `$() || { ... }` the
  same as the op-shim exit-1 case T4 already covers.

---

## PR #16 — fix-by-fix closure

### MEDIUM — drift key extended to count, age, topics

**Closed by** `e56cbf4`:

- Drift gate in `reconcileBadgeStateFromServer()` extended from `unacked_count`
  alone to `{unacked_count, oldest_unacked_age_sec, topics}`. Topics compared
  via `JSON.stringify` (stable ordering from server; small N so deep-eq cost
  is negligible). Cache initializer extended to include age + topics so the
  first reconcile cycle compares against `0` / `[]` rather than `undefined`.

### LOWs

- **L1** (drift block comment) — three-case enumeration (server-positive then
  server-zero then server-omits) replaces the prior shorter version that
  contradicted brief §3 Key Constraints. No code change — comment fix only.
- **L2** (`/api/v2/terminals` fetch) — dropped `credentials: "same-origin"`.
  It's the browser default for fetch since 2017 and the other fetches in this
  file (`loadBusiness`, `loadInitialState`) work without it. Parity over
  redundant pass-through.
- **L3** (catch block) — comment reconciled. Prior wording claimed init-vs-poll
  error logging differs but the single function silences both. New comment
  owns the silent-for-both contract + names the safety rationale (init failure
  surfaces visually as zero-unread cards, which beats false-positive counts).
- **L4** (render dispatch) — extracted `renderForAlias(alias)` helper with
  `else console.warn(...)` for unknown aliases. Both the SSE
  `bus_badge_change` handler AND `pollBadgeSanity` now use the same helper,
  so a new alias family added server-side will surface in DevTools instead of
  silently dropping renders.

---

## Ship-gate output (literal)

### Forge bash tests (12 cases, all PASS)

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
PASS: Case H' — sync_clone_to_main + classify_mailbox integrate end-to-end without pre-fetch.
PASS: Case J — feature branch with no local file extracts brief from origin/main.
PASS: Case K — cold-clone (no origin/main ref) falls back to local mailbox file.

All 12 cases PASS.
```

### Ack pytest (6 cases, all PASS)

```
$ python3.12 -m pytest tests/test_ack_dispatch_msgs.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 6 items

tests/test_ack_dispatch_msgs.py::test_happy_path_three_matching_messages PASSED
tests/test_ack_dispatch_msgs.py::test_already_acked_message_is_skipped PASSED
tests/test_ack_dispatch_msgs.py::test_slug_not_present_zero_acked_exit_zero PASSED
tests/test_ack_dispatch_msgs.py::test_key_fetch_failure_exit_2 PASSED
tests/test_ack_dispatch_msgs.py::test_single_ack_http_error_is_non_fatal PASSED
tests/test_ack_dispatch_msgs.py::test_op_binary_absent_from_path_exits_2 PASSED

============================== 6 passed in 1.63s ===============================
```

### check_singletons

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### App.js parse check (node)

```
$ node ... static/app.js  → OK: app.js parses
```

### Manual reveal — drift detection (Node simulation of the anchor case)

Anchor case: Lead "3 unread · 602m" with count stable (3 then 3) and age
drifting (0s then 36120s).

| Scenario | Pre-fix (count-only) | Post-fix (count or age or topics) |
|---|---|---|
| Lead anchor: stable count, drifting age | gate fires: false (BUG) | gate fires: true (FIXED) |
| Topic-only drift | gate fires: false | gate fires: true |
| Fully stable cache | gate fires: false | gate fires: false (no spurious reflow) |

Pre-fix: count-only gate returned false, no write, subtitle stuck at
stream-open age value forever. Post-fix: any-of-three gate returns true on
the anchor case, write fires, `renderForAlias("lead")` dispatches
`renderCard("lead")`, subtitle reflects live age within next poll tick
(at most 60s).

### Mirror install + launchctl kickstart

```
$ cp ~/bm-b1/scripts/forge_snapshot_push.sh "/Users/dimitry/Library/Application Support/baker/forge_snapshot_push.sh"
$ shasum "/Users/dimitry/Library/Application Support/baker/forge_snapshot_push.sh"
4223703b50b98ce44e18b076bc25845c432327e0  /Users/dimitry/Library/Application Support/baker/forge_snapshot_push.sh

$ launchctl kickstart -k "gui/$(id -u)/com.baker.forge-snapshot-push"
$ launchctl print "gui/$(id -u)/com.baker.forge-snapshot-push" | grep -E "state|exit code|runs"
	state = xpcproxy
	runs = 1382
	last exit code = 0
		state = active
		state = active
```

---

## 4-gate readiness (re-trigger via bus-post `ship/BRISEN_LAB_CARD_STATE_FIX_2-v0-2`)

- [x] Forge bash tests 12/12 PASS (Case H' + J + K added).
- [x] Ack pytest 6/6 PASS (T6 added).
- [x] check_singletons OK.
- [x] app.js parses (node).
- [x] Drift-gate Node simulation confirms fix on anchor case.
- [x] Mirror install + launchctl kickstart success, daemon healthy.
- [ ] AH2 `/security-review` on PR #201 (HIGH fix changes classify_mailbox output
      contract; ack script LOWs touch credential-fetch error path)
- [ ] picker-architect on PR #201
- [ ] picker-architect on PR #16
- [ ] `feature-dev:code-reviewer` 2nd-pass on PR #201 (mandatory per brief)
- [ ] `feature-dev:code-reviewer` 2nd-pass on PR #16 (mandatory per brief)

---

## Notes

- Mirror-installed forge_snapshot_push.sh runs the fast-follow code **before**
  PR #201 merges. If AH2 review forces further changes, AI Head A re-copies +
  kickstarts post-merge (same procedure B3 used in v0-1).
- The brisen-lab repo's pytest suite needs `fastapi` + `psycopg2-binary` etc.
  which aren't installed in this fresh clone; B3's v0-1 report likewise
  omitted brisen-lab pytest (JS-only changes, no Python touched). Manual
  reveal + node parse stand as the verification path per brief §3.3
  "manual-test step" allowance when no JS test infra exists.
- DO NOT touch mailbox `CODE_1_PENDING.md` until AH1 confirms re-gate-chain
  clear — sibling-dispatch hygiene per the brief frontmatter.
