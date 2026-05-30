---
report: B3_RESEARCHER_FANOUT_SKILL_1
brief: BRIEF_RESEARCHER_FANOUT_SKILL_1
brief_anchor_commit: aca31a0 (v2)
brief_authored_by: AH2 (deputy)
shipped_by: b3
shipped_at: 2026-05-30T15:10:00Z
target_repo: baker-vault
ship_commit: 7efcded
ship_branch: main
status: COMPLETE
reply_to: deputy
gate_chain_expected:
  gate_1_static_review: deputy (AH2)
  gate_2_security: SKIPPED (markdown-only scope, per brief)
  gate_3_picker_architect: deputy (AH2)
  gate_4_code_reviewer: deputy (AH2)
  gate_5_merge: lead OR cowork-ah1
---

# B3 ship report — RESEARCHER_FANOUT_SKILL_1

## Bottom line

Shipped 4-file scope on baker-vault main, commit `7efcded`. Symlink lands at `~/.claude/skills/research-fan-out` via `sync_skills.sh`. All 16 brief quality checkpoints verified locally. Ready for AH2 Gate 1/3/4 + AH1/cowork-ah1 Gate 5 (Gate 2 skipped per markdown-only scope).

## Files shipped (4)

| File | Change | LOC |
|---|---|---|
| `_ops/skills/research-fan-out/SKILL.md` | NEW | +180 |
| `_ops/skills/research-fan-out/checklist.md` | NEW | +102 |
| `_ops/agents/researcher/method.md` | EDIT (added §10) | +13 |
| `_ops/skills/INDEX.md` | EDIT (added v1 row) | +1 |

Total: **4 files, +296 insertions, 0 deletions**.

## Commit

```
7efcded skills(research-fan-out): RESEARCHER_FANOUT_SKILL_1 ship — parallel multi-channel dispatch
```

Pushed to `vallen300-bit/baker-vault` main at 2026-05-30T15:09Z. No conflicts; fast-forward `17f2538..7efcded`.

## sync_skills.sh output

```
[sync_skills] DRY-RUN would create research-fan-out -> /Users/dimitry/baker-vault/_ops/skills/research-fan-out
[sync_skills] OK research-fan-out
```

Symlink verified:
```
lrwxr-xr-x@ 1 dimitry  staff  55 May 30 17:04 /Users/dimitry/.claude/skills/research-fan-out -> /Users/dimitry/baker-vault/_ops/skills/research-fan-out
```

`realpath ~/.claude/skills/research-fan-out` → `/Users/dimitry/baker-vault/_ops/skills/research-fan-out` (canonical hit).

`Read` on `~/.claude/skills/research-fan-out/SKILL.md` returns the canonical content with frontmatter `name: research-fan-out`, `type: skill`, and the MANDATORY TRIGGERS list — symlink fully working.

## Brief quality checkpoints (16) — verification

| # | Checkpoint | Verdict |
|---|---|---|
| 1 | SKILL.md frontmatter has `name`, `description`, MANDATORY TRIGGERS list | PASS — 9 trigger phrases |
| 2 | SKILL.md body has 10 numbered sections | PASS — `grep -cE "^## [0-9]+\." → 10` |
| 3 | method.md §10 references skill by path + ratification anchor | PASS — `~/.claude/skills/research-fan-out/SKILL.md` + bus #1365/#1369/#1374 |
| 4 | INDEX.md row added | PASS — `research-fan-out` row, v1, 2026-05-30 |
| 5 | `sync_skills.sh --dry-run` shows symlink without errors | PASS — see above |
| 6 | `sync_skills.sh` creates symlink at `~/.claude/skills/research-fan-out` | PASS — see above |
| 7 | `Read` on symlink target returns canonical content | PASS — frontmatter + body match |
| 8 | Mnilax quote verbatim from `~/bm-b3/CLAUDE.md` §ENGINEERING RULES | PASS — SKILL.md line 103: `> **"Surface conflicts, don't average them."**` |
| 9 | No mention of Gemma as synthesizer (bus #1369) | PASS — every Gemma mention is explicit "NOT the synthesizer / NOT a fan-out channel" |
| 10 | No mention of Sonnet anywhere as synthesizer option (bus #1369) | PASS — Sonnet only appears in "no Sonnet tier switch" disclaimers |
| 11 | YouTube channel = "transcript fetch only, Opus reasons" (bus #1374) | PASS — §3 channel menu entry verbatim |
| 12 | Internal Brisen channels (vault/claimsmax/transcripts/WA/gmail) NOT in menu | PASS — §3 explicit exclusion block at top |
| 13 | Cost ceiling table present (default $0.60-1.50, escalation $0.80-2.30) | PASS — §9 table |
| 14 | Failure modes (3/3 / 2/3 / 1/3 / 0/3) explicit | PASS — §7 four bullets, verbatim caveats |
| 15 | Verification section names concrete smoke-test topic + acceptance | PASS — "Anthropic's Claude Agent SDK current state + community examples", <15 min, <$0.80 |
| 16 | Ship report cites brief by `brief_anchor_commit` SHA | PASS — this report frontmatter + commit body |

## Codex pre-review folds (bus #1394)

All 4 findings landed in v2 brief and shipped here:

- **M1** (router rewrite using verbatim research-type names): SKILL.md §4 table uses types `1, 2, 3, 5, 6, 7, 8, 10` (fan-out), `9` (sequential), `4` (matter desk) — names verbatim from `research-types.md`.
- **L1** (renamed "14-channel" → "external research-channel menu"): SKILL.md §3 header + explicit exclusion of Internal Brisen + 1Password + Gemma-as-channel.
- **L2** (2/3 + 1/3 caveat wording required verbatim): SKILL.md §7 carries both verbatim caveat strings; checklist.md R7 references them.
- **L3** (synthesizer prompt MUST include both verbatim Mnilax quote AND operational expansion): SKILL.md §6 carries both, in that order, both as blockquotes.

## Director Q closures from v2 brief

- **Q1** (companion checklist?) — YES, shipped at `~/baker-vault/_ops/skills/research-fan-out/checklist.md` (12 steps R1-R12, mirrors `harness-setup/checklist.md` H1-H12 pattern).
- **Q2** (skill slug?) — `research-fan-out` confirmed; canonical path + symlink + INDEX row all use it.

## Out-of-scope items confirmed untouched

- `orchestrator/research_executor.py` (baker-master server-side dossier engine) — not touched. Different repo, different lane.
- `~/bm-researcher/CLAUDE.md` — not touched. Pointer is in `method.md §10`, not in picker CLAUDE.md (per brief).
- Existing Researcher skills (`grok-via-xai-api`, `local-research-via-gemma`, `x-twitter`, `youtube-analyze`, `anthropic-feature-scout`, `researcher-verify-citations`, `pin-protocol`, `whatsapp-send-via-waha`, register skills) — REFERENCED in §3 channel menu, NOT modified.
- `_ops/agents/researcher/research-types.md` — READ only; not modified.
- Other agents' in-flight baker-vault state (PINNED.md, architect failure-modes-bank.md, HAG curated HTML batch, nvidia PDF, _research/, etc.) — NOT staged, NOT committed. `git diff --cached --stat` confirmed scope was exactly 4 files / 296 insertions.

## Anchors

- Brief canonical: `~/baker-vault/_ops/briefs/BRIEF_RESEARCHER_FANOUT_SKILL_1.md` commit `aca31a0` (v2, codex amends folded + Director Q1/Q2 closed).
- Dispatch mailbox: `briefs/_tasks/CODE_3_PENDING.md` (status: COMPLETE, ship_commit: 7efcded).
- Director ratifications: bus `#1365` (design), `#1369` (Opus-only synthesizer), `#1374` (YouTube transcript-only + Gemma out of fan-out path); AH2 chat 2026-05-30 ~12:05Z (Q1=YES checklist.md, Q2=slug `research-fan-out`).
- Codex pre-review: bus `#1394` (PASS-WITH-NOTES, all 4 findings folded into v2 brief).
- Precedent: BRIEF_HARNESS_SETUP_SKILL_1 (b4 shipped 2026-05-29) — same shape, same lane.
- Mnilax source: `~/bm-b3/CLAUDE.md` §ENGINEERING RULES line 40, Director-ratified 2026-05-11, source `https://x.com/Mnilax/status/2053116311132155938`.
- Anthropic multi-agent research pattern: `https://www.anthropic.com/engineering/multi-agent-research-system`.
