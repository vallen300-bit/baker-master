---
status: pending
brief: briefs/BRIEF_RESEARCHER_ON_BUS_1.md
brief_id: RESEARCHER_ON_BUS_1
target_repo: brisen-lab (front + server + tests) + baker-master (bus_post + forge pusher + tests + drain-hook fixture) + baker-vault (agent-bus-posting-contract SKILL)
matter_slug: baker-internal
dispatched_at: 2026-05-22T13:35:00Z
dispatched_by: lead
target: b1
working_branch: b1/researcher-on-bus-1
reply_to: lead
deadline: 2026-05-23T18:00:00Z
priority: tier-b
---

# CODE_1_PENDING — RESEARCHER_ON_BUS_1 — 2026-05-22

**Brief:** `briefs/BRIEF_RESEARCHER_ON_BUS_1.md` (full text in `~/bm-b1/briefs/`)
**Working branch:** `b1/researcher-on-bus-1` (branch off `main` of each repo touched)
**Repos:** brisen-lab + baker-master + baker-vault (three-PR sequence per SOP)
**SOP anchor:** `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` (ratified 2026-05-22)
**Template:** `briefs/BRIEF_HAGENAUER_DESK_ON_BUS_1.md` (shipped 2026-05-21 + 3 follow-on fixes 2026-05-22)
**Pre-requisites:** none — Researcher picker at `~/bm-researcher/` already exists; nothing else wired.

## Bottom line

Install Researcher (Cowork-App-only, Tier-A read-only) onto Brisen Lab bus. Slug = `researcher`. Card in `row-desks` next to hag-desk. 10/12 SOP rows in scope (rows 2 + 3 N/A — no Terminal alias, no Terminal.app profile for cowork-app).

## Acceptance criteria (full)

See brief AC1-AC12 (full text in `~/bm-b1/briefs/BRIEF_RESEARCHER_ON_BUS_1.md`). Summary:

- **AC1** — `~/bm-researcher/CLAUDE.md` update (preserve existing Tier-0 reads + first-message phrase; add canonical bus_post.sh ref + BAKER_ROLE wiring + send-capable narrow-topics rule).
- **AC2 + AC3** — `~/bm-b1/scripts/bus_post.sh:45` + `:55-73`: add `researcher` to recipient + sender whitelists.
- **AC4** — `~/.claude/hooks/session-start-bus-drain.sh:43-62`: add `researcher` to BAKER_ROLE case. If `tests/fixtures/session-start-bus-drain.sh` exists in baker-master, edit both in same PR.
- **AC5** — `~/baker-vault/_ops/skills/agent-bus-posting-contract/SKILL.md`: add `researcher` to recipient slugs line + Researcher subsection.
- **AC6** — brisen-lab `static/index.html` row-desks: append researcher article; `static/app.js:9` TERMINALS + `:11-16` TERMINAL_LABELS: append entries.
- **AC7 + AC8** — `~/bm-b1-brisen-lab/bus.py:895-897` KNOWN_CARD_SLUGS + `:1005` _build_terminals_response: append `"researcher"` to both tuples.
- **AC9** — `~/bm-b1-brisen-lab/tests/test_a3_a8_a9_bus.py`: add `test_bus_badge_change_emitted_for_researcher` + `test_v2_terminals_response_includes_researcher` (mirror hag-desk patterns at lines ~240 + ~272).
- **AC10** — `~/bm-b1/scripts/forge_snapshot_push.sh:61-70` TERMINALS: append `"researcher:/Users/dimitry/bm-researcher"`.
- **AC11** — `~/bm-b1/tests/test_forge_snapshot_push.sh`: add Case M (mirror Case L at lines ~668-701, substitute hag-desk → researcher). Update final count to "All 14 cases PASS."
- **AC12** — AH1 post-merge smoke (NOT b1).

## Pre-flight grep (defends SOP foot-gun #1)

```
grep -nE '"lead"\|"deputy"\|"b1"\|"hag-desk"' ~/bm-b1-brisen-lab/bus.py
```
Expect: 2 matches (lines ~895 KNOWN_CARD_SLUGS + ~1005 for-loop). If >2, surface to lead before editing.

## Three-repo PR sequence (per SOP)

1. **baker-vault PR first** — AC5 SKILL update. Doc-only; merge on green review.
2. **baker-master PR second** — AC2 + AC3 + AC4 (if fixture exists) + AC10 + AC11. Run `bash tests/test_forge_snapshot_push.sh` → 14 cases PASS. Merge on green.
3. **brisen-lab PR third** — AC6 + AC7 + AC8 + AC9. Run `pytest tests/test_a3_a8_a9_bus.py -v` → all PASS. Merge LAST (card slot most-visible; bad if card exists before bus routing accepts slug).

## AC1 filesystem edit (no PR)

After all 3 PRs merge, update `~/bm-researcher/CLAUDE.md`. Capture before/after diff in ship report.

## AC4 user-global edit

If `~/bm-b1/tests/fixtures/session-start-bus-drain.sh` does NOT exist: edit the user-global hook (`~/.claude/hooks/session-start-bus-drain.sh`) directly + capture diff in ship report + flag SOP-row-7 gap. lead will `cp` the deployed fixture post-merge if you ship the fixture in baker-master PR.

## Ship gate

- baker-master PR: literal `bash tests/test_forge_snapshot_push.sh` output (14 cases PASS) in ship report.
- baker-vault PR: doc-only, no test required.
- brisen-lab PR: literal `pytest tests/test_a3_a8_a9_bus.py -v` output in ship report.
- Pre-flight grep output captured in ship report.
- `~/.claude/hooks/session-start-bus-drain.sh` diff + `~/bm-researcher/CLAUDE.md` content captured.

NO "pass by inspection."

## Reporting

- Bus-post `lead` on EACH PR open with topic `pr-open/researcher-on-bus-1`.
- Bus-post `lead` on ship-complete with all 3 PR/SHA anchors + filesystem state.
- Ship report: `briefs/_reports/B1_RESEARCHER_ON_BUS_1_20260522.md`.

## Co-Authored-By

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
