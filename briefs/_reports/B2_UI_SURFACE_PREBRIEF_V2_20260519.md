---
brief_id: UI_SURFACE_PREBRIEF_V2
builder: b2
target_repo: baker-vault
pr: https://github.com/vallen300-bit/baker-vault/pull/99
commit: e9ae303
branch: b2/ui-surface-prebrief-v2-hook
worktree: ~/bm-b2-baker-vault (created off origin/main, recommended option from brief)
mailbox: briefs/_tasks/CODE_2_PENDING.md
dispatched_by: lead
bus_thread: 37b5b56e-17b4-4ab2-8140-e65a43490024
bus_dispatch_msg: 507 (ACKed)
bus_claim_msg: 520
bus_ship_topic: ship/ui-surface-prebrief-v2
status: shipped
shipped_at: 2026-05-19T15:53Z
estimated_effort: 1-2h
actual_effort: ~1h (single session)
gates_pending: gate-1 (deputy/AH2 static) + gate-2 (/security-review)
---

# B2 ship report — UI_SURFACE_PREBRIEF_V2 (2026-05-19)

## TL;DR

`PreToolUse` hook + 9-case test harness + docs that hard-block brief authoring whose final content lacks `### Surface contract`. Converts the soft `ui-surface-prebrief` skill (v1.1) into a skill+hook hybrid per the brief's behavior contract. **PR #99 open against baker-vault main, all 9 harness cases green (24–60 ms latencies), all self-check boxes ticked.** Waiting on Gate-1 (deputy/AH2 cross-lane static) + Gate-2 (`/security-review`) per the brief's gate chain.

## What shipped (4 files, +448 lines)

| File | Purpose |
|---|---|
| `_ops/hooks/ui-surface-prebrief-check.sh` | Canonical hook script. Bash wrapper + jq for early exits + small python helper for safe diff simulation on `Edit`/`MultiEdit`. |
| `_ops/hooks/tests/test_ui_surface_prebrief_check.sh` | 9-case test harness. Asserts exit code + stderr substring + per-invocation latency <100 ms. |
| `_ops/hooks/README.md` | New hooks-directory README; index table; distinguishes from `.githooks/` (git-stage hooks). |
| `_ops/skills/ui-surface-prebrief/SKILL.md` | Adds `## Hook companion` cross-reference section linking to the hook + firing conditions + N/A escape. |

## Harness output (literal — no "pass by inspection")

```
PASS  01_write_brief_no_surface                          exit=2  latency=  36ms
PASS  02_write_brief_with_surface                        exit=0  latency=  34ms
PASS  03_write_brief_with_na_escape                      exit=0  latency=  34ms
PASS  04_edit_adds_acceptance_no_surface                 exit=2  latency=  59ms
PASS  05_edit_typo_fix_no_trigger                        exit=0  latency=  56ms
PASS  06_edit_adds_file_line_ref_no_surface              exit=2  latency=  59ms
PASS  07_write_non_brief_path                            exit=0  latency=  30ms
PASS  08_malformed_json_fail_open                        exit=0  latency=  24ms
PASS  09_regression_prose_no_false_positive              exit=0  latency=  55ms

Test harness summary: 9 passed, 0 failed
Latency ceiling: 100ms per invocation
```

Case 09 is a bonus regression — confirms "Section 4:1 of the contract" + "Section 1: Introduction" prose does NOT trigger the `file:line` gate. Brief flagged this as a known false-positive risk; required-extension prefix `\.(py|html|ts|js)` in the regex prevents it.

## Decisions made (within Tier-A authority)

1. **Bash wrapper + python helper for Edit/MultiEdit (not pure bash).** Brief preferred pure bash for <50 ms latency; pure-bash diff simulation on arbitrary `old_string`/`new_string` is fragile (parameter expansion does glob matching, sed-escaping arbitrary strings is error-prone). Single python call for the rare Edit case adds ~25 ms vs bash. Median latency still 36 ms; max 60 ms — well under 100 ms hard ceiling. Surfaced in PR description.
2. **Settings.json matcher `Write|Edit|MultiEdit`, path filter inside script.** Anthropic docs confirm the `matcher` field is tool-name only (not path). Path filtering moved into the script's `grep -qE '(^|/)(_ops/)?briefs/BRIEF_[^/]+\.md$'`.
3. **Single `### Surface contract` literal grep covers both the formal block AND the `### Surface contract: N/A — …` escape.** Simpler than two separate regexes; both forms share the prefix.
4. **Fail-open ERR trap + no `set -e`** — every exception path exits 0 with stderr warning. Gate logic bugs never block legitimate tool use per brief reviewer instruction #1.

## Open items / next-step ownership

- **Gate-1 (deputy/AH2 static):** AH2 to read the hook end-to-end + run the harness locally + confirm fail-open posture. Mandatory before PASS per brief's reviewer instructions.
- **Gate-2 (`/security-review`):** treats hook as security-perimeter component (gates agent tool use). LOW-MEDIUM trigger class, small bash + small python, no DB / auth / migration / external API touch.
- **Post-merge Tier-A (AH1, not B2):** picker-side install — symlinks + `.claude/settings.json` registration in `~/bm-aihead1/` and `~/bm-aihead2/` only. Exact snippet pasted verbatim in PR #99 description.

## Anchors

- Brief: `~/baker-vault/_ops/briefs/BRIEF_UI_SURFACE_PREBRIEF_V2.md` (baker-vault commit `c64e46c`).
- Mailbox: `~/bm-b2/briefs/_tasks/CODE_2_PENDING.md` (PENDING; will flip to COMPLETE on merge).
- Anthropic hooks docs: https://code.claude.com/docs/en/hooks (fetched 2026-05-19; confirmed unchanged).
- Skill being hardened: `~/baker-vault/_ops/skills/ui-surface-prebrief/SKILL.md` (v1.1, `6467edd`).
- Scar incident: brisen-lab PR #22 / #23 ship-time discovery 2026-05-19 ~07:35Z.
- Bus thread `37b5b56e-17b4-4ab2-8140-e65a43490024`: dispatch msg #507 ACKed; claim msg #520; ship msg per same-turn bus-post on this report's filing.

## Surface contract: N/A — pure tooling brief; the hook itself gates other agents' tool use but produces no user-clickable surface.
