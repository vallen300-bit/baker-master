---
brief: FORGE_DAEMON_FRONTMATTER_STATUS_AUTHORITATIVE_1
agent: b3
branch: b3/forge-daemon-frontmatter-status-authoritative-1
pr: 191
pr_url: https://github.com/vallen300-bit/baker-master/pull/191
base_sha_pulled: b4e5c2a
shipped_at: 2026-05-12T20:17:28Z
ship_gate: PASS (literal `bash tests/test_forge_snapshot_push.sh` exit 0, 7/7 cases)
bus_post: ship/forge-daemon-frontmatter-status-authoritative-1 → message_id 152
status: SHIPPED — awaiting AH2 /security-review + picker-architect gates
---

# B3 ship report — FORGE_DAEMON_FRONTMATTER_STATUS_AUTHORITATIVE_1

## What shipped

Two folded items from `b4e5c2a` dispatch:

1. **Parser: frontmatter `status:` authoritative over filename suffix.** Shared `classify_mailbox` helper added to `scripts/forge_snapshot_push.sh`. Reads YAML frontmatter `status:` from `briefs/_tasks/CODE_N_*.md`; uses it as the final classification when present. Filename suffix is fallback. Wired into both `pick_active_clone` (scoring) and `snapshot_one` (`mailbox_status` payload). Status vocabulary expanded from `{pending, complete, empty, n/a}` to `{pending, in_progress, staged, complete, dropped, empty, n/a}`.

2. **Test fixtures: Case F + Case G.** Case F locks down the existing `f5012a9` hotfix (COMPLETE +50 beats empty +0 with newer-recency tiebreaker). Case G locks down the new frontmatter-authority path (filename `_PENDING` + `status: DROPPED` → classifies as `dropped`).

## Mapping (decided per brief's "decide sensibly" clause)

| Frontmatter `status:` | Daemon classification | `pick_active_clone` score |
|---|---|---|
| `PENDING` / `IN_PROGRESS` | `pending` / `in_progress` | +100 (active dispatch) |
| `STAGED` / `COMPLETE` | `staged` / `complete` | +50 (active clone, non-active state) |
| `DROPPED` | `dropped` | +25 (drained but still working clone) |
| (no frontmatter / unknown) | falls back to filename suffix | per filename rule |
| (no mailbox file) | `empty` (b-codes) / `n/a` (lead/deputy) | 0 |

Rationale: `STAGED` and `DROPPED` do NOT classify as pending/red, satisfying the brief's explicit constraint. `dropped` still scores positive so a drained mailbox beats an empty sibling clone in `pick_active_clone` — preserves the "this clone is the working clone for this alias" signal even after workflow ends.

## Ship gate — literal `bash tests/test_forge_snapshot_push.sh`

```
PASS: Case A — heading-style mailbox, single clone.
PASS: Case B — YAML frontmatter mailbox extracts brief: field.
PASS: Case C — two-clone alias picks pending-mailbox clone (overrides recency).
PASS: Case D — two-clone alias falls back to recency tiebreaker.
PASS: Case E — two non-git candidate paths fall back to first; daemon still emits stderr without crash.
PASS: Case F — two-clone alias picks COMPLETE-mailbox clone over empty sibling.
PASS: Case G — frontmatter status: DROPPED authoritative over filename _PENDING suffix.

All 7 cases PASS.
EXIT=0
```

All existing 5 cases (A-E) still green — no regression.

## Surprise + fold I made on the fly

`case "$x" in pat1|pat2)` alternation inside `$(...)` command substitution trips bash 3.2's parser. macOS default bash is 3.2.57; Mac Mini runs the daemon under launchd with `#!/usr/bin/env bash` → 3.2. My first draft of `pick_active_clone` scoring used a case statement and failed with "syntax error near unexpected token 'newline'". Rewrote to `if/elif` chain — functionally identical, parses clean on 3.2.

Confirmed minimal repro:
```bash
f() { result="$(case "x" in a|b) echo P;; esac)"; }
```
fails on 3.2 with the same error. Captured in the implementation note in the PR body and in a code comment at the call site so the next person doesn't reintroduce.

## Time

~50 minutes (brief estimated ~30-45). Extra ~10 min on the bash 3.2 case-statement parser issue (debug + rewrite).

## Gates required

- AH2 `/security-review`
- picker-architect

Both blocked on PR #191. Awaiting review chain.

## Bus posts

- SHIP: `ship/forge-daemon-frontmatter-status-authoritative-1` → message_id 152 → lead, 2026-05-12T20:17:28Z
