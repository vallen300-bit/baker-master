---
brief_id: RESEARCHER_ON_BUS_1
builder: b1
ship_date: 2026-05-22
status: shipped
brief_commit: 0880ab0
dispatch_commit: 1e2d5a5
bus_dispatch_msg_id: 677
---

# B1 ship report — RESEARCHER_ON_BUS_1

## Bottom line

10 of 12 SOP rows shipped (rows 2 + 3 N/A — Cowork-App-only agent, no Terminal alias / Terminal.app profile). 3 PRs open, all tests green, both filesystem edits captured. Bus #677 acked (#678 ack receipt). AH1 Tier-B post-merge (1P key + Render env + redeploy + AC12 smoke) remains.

## PR anchors

| Repo | PR | Branch | Commit |
|---|---|---|---|
| baker-vault | [#104](https://github.com/vallen300-bit/baker-vault/pull/104) | `b1/researcher-on-bus-1` | `4747f12` |
| baker-master | [#241](https://github.com/vallen300-bit/baker-master/pull/241) | `b1/researcher-on-bus-1` | `225adb4` |
| brisen-lab | [#29](https://github.com/vallen300-bit/brisen-lab/pull/29) | `b1/researcher-on-bus-1` | `49e96fe` |

## AC coverage

| AC | Description | Files | Status |
|---|---|---|---|
| AC1 | Picker CLAUDE.md update | `~/bm-researcher/CLAUDE.md` | ✓ filesystem (no PR) |
| AC2 | bus_post.sh recipient whitelist | baker-master `scripts/bus_post.sh:45,48` | ✓ PR #241 |
| AC3 | bus_post.sh sender BAKER_ROLE | baker-master `scripts/bus_post.sh:67,70` | ✓ PR #241 |
| AC4 | SessionStart drain hook | baker-master `tests/fixtures/session-start-bus-drain.sh:55-56` + user-global `~/.claude/hooks/session-start-bus-drain.sh:56` | ✓ PR #241 (fixture) + filesystem (user-global) |
| AC5 | agent-bus-posting-contract SKILL | baker-vault `_ops/skills/agent-bus-posting-contract/SKILL.md` | ✓ PR #104 |
| AC6 | brisen-lab front-end | `static/index.html:43-44` + `static/app.js:9,11-16` | ✓ PR #29 |
| AC7 | bus.py KNOWN_CARD_SLUGS | `bus.py:896` | ✓ PR #29 |
| AC8 | bus.py for-loop tuple | `bus.py:1005` | ✓ PR #29 |
| AC9 | bus.py regression tests | `tests/test_a3_a8_a9_bus.py` (2 new tests) | ✓ PR #29 |
| AC10 | forge_snapshot_push TERMINALS | baker-master `scripts/forge_snapshot_push.sh:70` | ✓ PR #241 |
| AC11 | forge test Case M | baker-master `tests/test_forge_snapshot_push.sh` | ✓ PR #241 |
| AC12 | AH1 post-merge smoke | (AH1 scope, post-merge) | ⏳ awaiting |

## Pre-flight grep (SOP foot-gun #1 defense)

```
$ grep -nE '"lead"|"deputy"|"b1"|"hag-desk"' ~/bm-b1-brisen-lab/bus.py
896:    "lead", "deputy", "b1", "b2", "b3", "b4", "cortex", "cowork-ah1", "hag-desk",
1005:    for slug in ("lead", "cowork-ah1", "deputy", "b1", "b2", "b3", "b4", "hag-desk"):
```

Result: 2 matches (KNOWN_CARD_SLUGS + for-loop), exactly as brief predicted. Both edited under AC7 + AC8.

## Ship gates

### baker-master — `bash tests/test_forge_snapshot_push.sh` (literal)

```
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
PASS: Case L — non-b-code single-clone slug (desk pattern) — mailbox stays n/a.
PASS: Case M — non-b-code single-clone slug (Cowork-App-only) — mailbox stays n/a.

All 14 cases PASS.
```

### baker-vault — doc-only PR (no test gate required per SOP).

### brisen-lab — `pytest tests/test_a3_a8_a9_bus.py -v` (literal)

```
tests/test_a3_a8_a9_bus.py::test_a3_dispatch_kind_sets_wake_attempted_at_on_drain PASSED
tests/test_a3_a8_a9_bus.py::test_a4_exclude_self_filter PASSED
tests/test_a3_a8_a9_bus.py::test_a5_director_only_tier_validates PASSED
tests/test_a3_a8_a9_bus.py::test_a8_soft_delete_sender_within_window PASSED
tests/test_a3_a8_a9_bus.py::test_a8_director_can_delete_anytime PASSED
tests/test_a3_a8_a9_bus.py::test_a9_retention_forever_soft_delete_only PASSED
tests/test_a3_a8_a9_bus.py::test_inbox_badge_count_in_terminals_response PASSED
tests/test_a3_a8_a9_bus.py::test_inbox_badge_clears_on_ack PASSED
tests/test_a3_a8_a9_bus.py::test_inbox_badge_excludes_broadcast_wildcard PASSED
tests/test_a3_a8_a9_bus.py::test_inbox_badge_sse_event_emitted_on_post PASSED
tests/test_a3_a8_a9_bus.py::test_bus_badge_change_emitted_for_hag_desk PASSED
tests/test_a3_a8_a9_bus.py::test_v2_terminals_response_includes_hag_desk PASSED
tests/test_a3_a8_a9_bus.py::test_bus_badge_change_emitted_for_researcher PASSED
tests/test_a3_a8_a9_bus.py::test_v2_terminals_response_includes_researcher PASSED
tests/test_a3_a8_a9_bus.py::test_inbox_badge_excludes_soft_deleted PASSED
tests/test_a3_a8_a9_bus.py::test_ack_forbidden_emits_no_badge_change PASSED
tests/test_a3_a8_a9_bus.py::test_inbox_badge_multi_recipient PASSED
================== 17 passed, 3 warnings in 132.45s (0:02:12) ==================
```

Run env: `TEST_DATABASE_URL_BRISEN_LAB` fetched from 1Password.

## Filesystem state (no PR)

### `~/bm-researcher/CLAUDE.md` (AC1)

Rewritten end-to-end to:
- Add `method.md` + `research-types.md` to Tier-0 read list (in addition to existing global + orientation + canonical memory).
- Add `## Bus (RESEARCHER_ON_BUS_1, 2026-05-22)` section: canonical bus_post.sh path = `~/bm-b1/scripts/bus_post.sh`, BAKER_ROLE=researcher required, narrow-topics rule (`ship/research-*`, `question/<target>`), no Tier-B, posting pattern.
- Preserve existing Tier-A authority block + first-message confirmation phrase verbatim.
- Add `cwd path is /Users/dimitry/bm-researcher` block scope.

53 lines total (vs 22 lines before).

### `~/.claude/hooks/session-start-bus-drain.sh` (AC4 user-global)

```diff
@@ -53,6 +53,7 @@
     cortex|CORTEX)                      SLUG=cortex ;;
     aid|AID)                            SLUG=aid ;;
     hag-desk|HAG-DESK|hagenauer-desk)   SLUG=hag-desk ;;
+    researcher|RESEARCHER)              SLUG=researcher ;;
     *)
         # No BAKER_ROLE → silent no-op. Cwd-based fallback intentionally NOT
         # mirrored here to avoid auto-draining for sessions not meant to be on
```

Verification: `grep -n researcher ~/.claude/hooks/session-start-bus-drain.sh` → `56:    researcher|RESEARCHER)              SLUG=researcher ;;`.

## SOP-row-7 gap closed

`tests/fixtures/session-start-bus-drain.sh` in baker-master was stale: it was missing `hag-desk` even though deployed user-global `~/.claude/hooks/session-start-bus-drain.sh` had it (added direct via cp during HAGENAUER_DESK_ON_BUS_1 post-merge). This brief's fixture edit (PR #241) brings the fixture back into parity by adding **both** `hag-desk` (catch-up) and `researcher` (this brief). After PR #241 merges, AH1's `cp tests/fixtures/session-start-bus-drain.sh ~/.claude/hooks/` Tier-B will preserve the deployed state.

## Risks / counter-points (from brief, observed during build)

1. **Picker proliferation:** N/A — no new picker created. Net new = 1 cockpit card. ✓
2. **bus.py three-slug-list trap:** defended via pre-flight grep + AC7 + AC8 + AC9 (regression tests for both KNOWN_CARD_SLUGS + for-loop). ✓
3. **Cowork-App-only:** documented in AC1 picker CLAUDE.md (`export BAKER_ROLE=researcher` instruction). ✓
4. **Tier-A discipline not enforced by bus_post.sh:** documented in AC1 + AC5 — discipline is human-layer, not transport-layer. ✓
5. **10 slugs total:** noted in brief §Risks. No action.

## Bus-post trail

| Event | Bus msg | Topic |
|---|---|---|
| #677 dispatch ack | (server `{"ok":true}` post-ack) | dispatch/researcher-on-bus-1 |
| PR1 open (baker-vault) | #679 | pr-open/researcher-on-bus-1 |
| PR2 open (baker-master) | #681 | pr-open/researcher-on-bus-1 |
| PR3 open (brisen-lab) | #682 | pr-open/researcher-on-bus-1 |
| Ship-complete (this report) | pending — posting after this file commits | ship/researcher-on-bus-1 |

## What AH1 needs next (out-of-band Tier-B)

1. Merge order: baker-vault #104 → baker-master #241 → brisen-lab #29 (LAST, per SOP).
2. Generate `researcher` terminal key (`openssl rand -hex 32`) → 1P store as `BRISEN_LAB_TERMINAL_KEY_researcher`.
3. Patch brisen-lab Render env `BRISEN_LAB_TERMINAL_KEYS` JSON map with new entry → `POST /deploys`.
4. `cp ~/bm-b1/tests/fixtures/session-start-bus-drain.sh ~/.claude/hooks/session-start-bus-drain.sh` (Mac Mini + MacBook). User-global already edited on MacBook; cp re-aligns from canonical fixture.
5. Forge install rerun on Mac Mini + MacBook so the daemon picks up `researcher:/Users/dimitry/bm-researcher` TERMINAL.
6. AC12 smoke: AH1→researcher test post + researcher→lead reverse smoke + browser card render check on https://brisen-lab.onrender.com/.
