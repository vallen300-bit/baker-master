---
dispatch: BRIEF_HARNESS_SETUP_SKILL_1
to: b4
from: deputy
dispatched_by: deputy
status: PENDING
dispatched_at: 2026-05-29T08:50:00Z
authored: 2026-05-29
target_repo: baker-vault (markdown-only)
workdir: ~/baker-vault
estimated_time: 30-60min
complexity: Low (markdown-only)
reply_to: deputy
priority: tier-a
anchor: AH2 self-check commit 53ab51d; researcher bus #1283; Director-ratified Q1=b4 Q2=optional-post-merge 2026-05-29
brief_canonical: ~/baker-vault/_ops/briefs/BRIEF_HARNESS_SETUP_SKILL_1.md (commit 91a3840)
---

# B4 dispatch — BRIEF_HARNESS_SETUP_SKILL_1

## TL;DR

Build the `harness-setup` skill at `~/baker-vault/_ops/skills/harness-setup/SKILL.md` + companion `checklist.md` + user-global symlink + INDEX update. Markdown-only — no code, no DB, no API. ~30-60 min build.

Canonical brief body lives at `~/baker-vault/_ops/briefs/BRIEF_HARNESS_SETUP_SKILL_1.md` (commit 91a3840). Read that file first — it has the full Context / Problem / Files Modified / Verification / Acceptance criteria.

## Context (short version)

Researcher surfaced via bus #1283 that Baker should codify its harness install rubric (6-layer model from "Art of Harness Engineering" YouTube). AH2 self-check (commit 53ab51d) confirmed Baker runs 5/6 layers above standard + a bonus Layer 7 (bus / coordination substrate). Director ratified building the skill so future agents install at standard by construction.

You voted N on the binding-constraint probe earlier today (#1291) — closest friction was dashboard.py token-cost tracing but grep resolved fast. That probe is the anchor for skipping the LSP build and going straight to this codification.

## Source anchors (must cite in SKILL.md)

- AH2 self-check: `~/baker-vault/_ops/agents/aihead2/2026-05-29-harness-engineering-self-check.md` (commit `53ab51d`).
- Researcher bus `#1283` (Director-directed harness audit ask).
- Video URL: `https://youtu.be/ulNsa0sD8N0` — "The Art of Harness Engineering: Beyond Context Engineering".

## Body shape (mandatory sections in SKILL.md, in order)

1. Frontmatter — `name: harness-setup`, description ≤2 sentences with MANDATORY TRIGGERS list.
2. Bottom line (≤25 words).
3. **The 6-layer rubric** — one section per layer. Each layer has:
   - (a) What the video says (one paragraph).
   - (b) Baker's current state with concrete file paths or counts.
   - (c) Install step for a new agent.
   - Layer 1 Global Rules / Layer 2 Skills / Layer 3 MCP Servers / Layer 4 Codebase Search / Layer 5 Hooks / Layer 6 Sub-agents.
4. **Layer 7 — Baker-specific add: Bus / coordination substrate.** Cite `~/Desktop/baker-code/scripts/bus_post.sh` + Brisen Lab daemon URL `https://brisen-lab.onrender.com` + cross-link to `install-agent-to-brisen-lab-sop.md`.
5. Install checklist — numbered steps H1-H~12 (mirror the install-agent-to-brisen-lab 12-row pattern). Each step: command + verify + expected output. Put the deep version in companion `checklist.md`; SKILL.md just lists step IDs + 1-line summaries.
6. Worked example — point to the researcher install as the ~60-min anchor case per SOP-codification-rule.
7. When NOT to use — single-purpose ephemeral agents, sub-agent specs inheriting from existing harness, anything not getting its own picker.
8. Anchors block — commit 53ab51d + bus #1283 + video URL + Director ratifications 2026-05-29 + 90-day refresh owner = AH1.
9. Co-author block — researcher (rubric originator), AH2 (self-check), AH1 (90-day refresh + future ownership).

## Triggers list (MANDATORY TRIGGERS frontmatter line)

`install harness agent`, `new agent harness`, `harness setup`, `harness audit`, `6-layer rubric`, `harness install rubric`, `harness-setup skill`, `/harness-setup`

## Files Modified — files to create / edit

### CREATE
1. `~/baker-vault/_ops/skills/harness-setup/SKILL.md` (new, ≤300 lines).
2. `~/baker-vault/_ops/skills/harness-setup/checklist.md` (new, ≤80 lines).
3. `~/.claude/skills/harness-setup` → symlink to `~/baker-vault/_ops/skills/harness-setup` (new).

### EDIT
4. `~/baker-vault/_ops/skills/INDEX.md` — add row.

### NO OTHER CHANGES
- Do NOT touch `baker-master/` repo.
- Do NOT touch `outputs/dashboard.py`, `orchestrator/`, or `kbl/`.
- Do NOT alter existing skills.

## Verification — exact commands to run before reporting ship

```bash
# AC1: SKILL.md exists with valid frontmatter
test -f ~/baker-vault/_ops/skills/harness-setup/SKILL.md
head -10 ~/baker-vault/_ops/skills/harness-setup/SKILL.md | grep -q "^name: harness-setup"
head -10 ~/baker-vault/_ops/skills/harness-setup/SKILL.md | grep -q "MANDATORY TRIGGERS"

# AC2: checklist.md exists
test -f ~/baker-vault/_ops/skills/harness-setup/checklist.md

# AC3: All 7 layer sections present
for L in "Layer 1" "Layer 2" "Layer 3" "Layer 4" "Layer 5" "Layer 6" "Layer 7"; do
  grep -q "$L" ~/baker-vault/_ops/skills/harness-setup/SKILL.md || { echo "MISSING: $L"; exit 1; }
done

# AC4: Symlink resolves
test -L ~/.claude/skills/harness-setup
readlink ~/.claude/skills/harness-setup | grep -q "baker-vault/_ops/skills/harness-setup"
test -f ~/.claude/skills/harness-setup/SKILL.md

# AC5: Index registered
grep -q "harness-setup" ~/baker-vault/_ops/skills/INDEX.md

# AC6: Anchors cited
grep -q "53ab51d" ~/baker-vault/_ops/skills/harness-setup/SKILL.md
grep -q "#1283" ~/baker-vault/_ops/skills/harness-setup/SKILL.md
grep -q "ulNsa0sD8N0" ~/baker-vault/_ops/skills/harness-setup/SKILL.md

# AC7: Length envelopes
[ "$(wc -l < ~/baker-vault/_ops/skills/harness-setup/SKILL.md)" -le 300 ]
[ "$(wc -l < ~/baker-vault/_ops/skills/harness-setup/checklist.md)" -le 80 ]
```

All 7 ACs must pass literally (paste output in ship report). No "pass by inspection".

## Quality Checkpoints / Acceptance criteria

- **AC1** SKILL.md exists with frontmatter (name, description, MANDATORY TRIGGERS).
- **AC2** checklist.md exists, ≤80 lines.
- **AC3** All 7 layer sections present (Layers 1-6 from video + Layer 7 bus substrate).
- **AC4** User-global symlink resolves to canonical.
- **AC5** INDEX.md has new row for `harness-setup`.
- **AC6** Anchors block cites commit 53ab51d + bus #1283 + video URL.
- **AC7** SKILL.md ≤300 lines, checklist.md ≤80 lines.
- **AC8 (post-merge, non-blocking, Director-ratified OPTIONAL):** after merge, bus researcher with skill commit hash + ack request. Researcher's rubric-integrity comments land via follow-up commit, NOT re-merge gate.

## Ship report

Bus-post `deputy` with:
1. Commit hash(es).
2. Literal AC1-AC7 verify output (paste the bash block result).
3. Acknowledgment of AC8 plan (post-merge bus to researcher).

Frontmatter `dispatched_by: deputy` ensures ship report routes to deputy.

## Devil's advocate (for your awareness)

- Skill could rot — mitigated by 90-day refresh duty named in SKILL.md = AH1.
- Skill might never be invoked — counter: 6+ matter desks queued; even 2 invocations recovers build cost.
- AH2 authored this brief (Director-override on SOP-authorship rule); AH1 retakes ownership on v2 + refresh.

## Director ratifications anchored

- 2026-05-29 chat: option (a) self-check → option (iii) probe → option (ii) skill build.
- 2026-05-29 chat: Q1 = b4 (you). Q2 = optional / post-merge review.
- 2026-05-29 chat: AH2 authoring authorized ("lead is busy").

Read the canonical brief at `~/baker-vault/_ops/briefs/BRIEF_HARNESS_SETUP_SKILL_1.md` (commit 91a3840) for full Constraints section + lessons-capture line.

Go.
