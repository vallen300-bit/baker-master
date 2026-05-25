---
brief_id: SOPS_TO_SKILLS_MIGRATION_1
authored_by: deputy (AH2)
authored_at: 2026-05-25
director_ratified: 2026-05-25 (chat — Q1=A inline/pointer split at 200 LOC, Q2=B include sop/contract/runbook/coordination/template, Q3=A static trigger-keyword eval only)
target: b3
reply_target: deputy (AH2) (cc lead)
expected_time: ~2-3h
complexity: Low
target_repo: baker-vault (markdown only) + ~/.claude/skills/ (symlinks)
companion_brief: BRIEF_SKILLS_EVAL_HARNESS_1 (separate dispatch, designed to run against the output of this brief)
---

# BRIEF: SOPS_TO_SKILLS_MIGRATION_1 — Mirror canonical SOPs / procedures into the skill catalog so they auto-fire on keyword triggers

## Context

`_ops/processes/*.md` holds 48 canonical procedure docs in baker-vault. Some are already mirrored as skills at `_ops/skills/<slug>/SKILL.md` and symlinked into `~/.claude/skills/`, where Claude Code auto-loads them when their declared `MANDATORY TRIGGERS:` match the user's prompt. The skill catalog is now a cross-vendor open standard (`agentskills.io`, Dec 2025 — Anthropic, Cursor, Vercel, OpenAI, Microsoft VS, Lovable conform), so anything we ship as a `SKILL.md` is portable to other agent runtimes.

The mirror is incomplete. Several `*-sop.md` files have no skill equivalent, several `*-runbook.md` / `*-contract.md` / `*-coordination.md` / `*-template.md` files don't either, and seven skills exist only in `~/.claude/skills/` (Director's machine) and were never uplifted to vault for cross-agent sharing. Net effect: procedures that should auto-fire when their trigger keywords appear don't, and agents have to be manually pointed at the vault file via Tier 1 keyword routing in CLAUDE.md.

This brief closes that gap with a one-shot mechanical migration.

Director-ratified direction (chat 2026-05-25): full migration with vault as canonical home + symlinks from `~/.claude/skills/` to vault. Source process docs stay in `_ops/processes/` unchanged — skills mirror them.

Anchor source: thevccorner.com Substack article "Prompts Are Dead. Skills Are the New Moat" (Dec 2025) — Director read 2026-05-25, validated the migration direction. Article thesis: skills are commodity markdown; the moat is in evals proving they work. Companion `BRIEF_SKILLS_EVAL_HARNESS_1` handles the eval side.

## Estimated time: ~2-3h
## Complexity: Low
## Prerequisites
- Read access to `~/baker-vault/_ops/processes/` and `~/baker-vault/_ops/skills/`
- Write access to both + to `~/.claude/skills/` (symlinks only)
- Git push access to baker-vault (commits land canonical mirror)
- An existing `SKILL.md` to copy the frontmatter pattern from — use `~/baker-vault/_ops/skills/agent-bus-posting-contract/SKILL.md` as the canonical example

---

## Fix 1 — Audit pass + classification list

### Problem
We do not have an explicit list of which `_ops/processes/*.md` files SHOULD be skills vs. which should NOT (architecture lock docs, schemas, trackers, frame changes — these are reference, not procedures).

### Current state
- `_ops/processes/` holds 48 .md files. Mixed types: SOPs, contracts, runbooks, coordination docs, templates, architecture locks, roadmaps, schemas, trackers, one-off frame-change announcements.
- `_ops/skills/` holds 35 skill directories. Most are mirrors of `_ops/processes/` entries; a few are domain skills with no process-doc source (`back-of-envelope-math`, `pyramid-principle`, etc.).
- 14 process docs match the migration filter `*-sop.md|*-contract.md|*-runbook.md|*-coordination.md|*-template.md`. 1 already has a skill (agent-bus-posting-contract). 13 do not.

### Implementation

Run this exact bash audit at brief start, paste the output into the ship report:

```bash
cd ~/baker-vault/_ops/processes
# Glob-based (avoids $(ls | grep) word-splitting on names with spaces).
shopt -s nullglob extglob
for f in *-+(sop|contract|runbook|coordination|template).md; do
  slug="${f%.md}"
  slug="${slug%-sop}"  # strip trailing -sop for skill slug
  # Verify existing skill dir actually has a SKILL.md (defends against partial prior install).
  for candidate in "$slug" "${f%.md}"; do
    if [ -f ~/baker-vault/_ops/skills/"$candidate"/SKILL.md ]; then
      echo "EXISTS: $f -> $candidate"
      continue 2
    fi
  done
  lines=$(wc -l < "$f")
  if [ "$lines" -lt 200 ]; then
    strategy="INLINE"
  else
    strategy="POINTER"
  fi
  echo "MISSING ($lines LOC, $strategy): $f -> $slug"
done
shopt -u nullglob extglob
```

Expected output (audit baseline 2026-05-25 — re-run before starting; the count may have shifted):

```
EXISTS: agent-bus-posting-contract.md
MISSING (136 LOC, INLINE): b-code-dispatch-coordination.md -> b-code-dispatch-coordination
MISSING (313 LOC, POINTER): capability-extension-template.md -> capability-extension-template
MISSING (63 LOC, INLINE): claude-settings-forge-collision-runbook.md -> claude-settings-forge-collision-runbook
MISSING (191 LOC, INLINE): cortex-config-template.md -> cortex-config-template
MISSING (116 LOC, INLINE): desk-gmail-reach-sop.md -> desk-gmail-reach
MISSING (162 LOC, INLINE): important-document-sop.md -> important-document
MISSING (210 LOC, POINTER): install-agent-to-brisen-lab-sop.md -> install-agent-to-brisen-lab
MISSING (278 LOC, POINTER): matter-onboarding-runbook.md -> matter-onboarding-runbook
MISSING (204 LOC, POINTER): project-room-build-sop.md -> project-room-build
MISSING (319 LOC, POINTER): specialist-prompt-template.md -> specialist-prompt-template
MISSING (156 LOC, INLINE): v2-bridge-cutover-runbook.md -> v2-bridge-cutover-runbook
MISSING (125 LOC, INLINE): worker-execution-of-matter-filing-sop.md -> worker-execution-of-matter-filing
MISSING (24 LOC, INLINE): writer-contract.md -> writer-contract
```

13 entries to migrate. 8 INLINE (<200 LOC), 5 POINTER (≥200 LOC).

### Key constraints
- Slug rule: trailing `-sop` stripped from filename for skill slug (`install-agent-to-brisen-lab-sop.md` → skill slug `install-agent-to-brisen-lab`). Other suffixes (`-contract`, `-runbook`, `-coordination`, `-template`) PRESERVED in the slug (matches existing skill naming).
- This filter does NOT cover architecture lock docs (`cortex-architecture-final.md`), schemas (`vault-tasks-schema-v1.md`), roadmaps (`cortex3t-roadmap.md`), trackers (`cortex-stage2-v1-tracker.md`), one-off frame-changes (`aid-frame-change-2026-05-11.md`), and similar reference docs. Those stay process-only. Director-ratified scope is procedural-only.

### Verification
Audit script output matches expected baseline (13 MISSING, 1 EXISTS) OR documents which entries shifted and why.

---

## Fix 2 — Generate the 13 missing SKILL.md files (8 INLINE + 5 POINTER)

### Problem
The 13 process docs identified in Fix 1 need their skill mirrors created with correct frontmatter so Claude Code auto-fires them on keyword match.

### Current state — canonical SKILL.md frontmatter pattern
Use `~/baker-vault/_ops/skills/agent-bus-posting-contract/SKILL.md` as the template. Frontmatter shape:

```yaml
---
name: <slug>
description: |
  <1-3 sentence "Use when ..." description that Claude Code shows in the available-skills system reminder. ~30-100 tokens.>

  MANDATORY TRIGGERS: <comma-separated list of keywords / phrases / file paths / commands that should auto-load this skill>. <One line is fine; can be 2-3 lines if many.>

  Use this skill whenever <one-sentence trigger restatement to reinforce intent>.
---

# <slug> — V1 skill

<Body — see INLINE vs POINTER below.>
```

### Implementation

**For each of the 8 INLINE files:**

1. Create directory `~/baker-vault/_ops/skills/<slug>/` (use the slug from Fix 1 audit output).
2. Write `~/baker-vault/_ops/skills/<slug>/SKILL.md` with:
   - Frontmatter as above. `name:` = slug. `description:` derived from the process doc's title + opening 1-3 sentences. `MANDATORY TRIGGERS:` populated from a careful read of the process doc (look for keywords likely to appear in Director / agent prompts that would benefit from this skill firing).
   - Body: prepend the H1 header `# <slug> — V1 skill`, then a 1-line drift warning + canonical source line:
     ```
     **Canonical source:** `~/baker-vault/_ops/processes/<original-filename>.md`. This skill mirrors that doc as of 2026-05-25 — keep them in sync on every edit.
     ```
   - Then paste the full body of the source process doc (everything after its frontmatter, if any).

**For each of the 5 POINTER files:**

1. Same directory + frontmatter as INLINE.
2. Body: H1 header + `## Canonical source` section that points to the vault file + one-paragraph summary of what the skill is for. Example template:
     ```markdown
     # <slug> — V1 skill (pointer)

     ## Canonical source

     The full procedure lives at `~/baker-vault/_ops/processes/<original-filename>.md` (<LOC> lines). Read that file via the Read tool when this skill fires.

     ## What this skill is for

     <1-paragraph summary — what the procedure accomplishes, when to invoke, what the output looks like.>

     ## Why pointer not inline

     Source procedure is <LOC> lines — large enough that inlining bloats the always-loaded skill catalog. Pointer pattern keeps the catalog cheap (frontmatter only) and the body loaded on-demand via Read.

     ## Foot-guns recap (full list in source doc)

     <2-4 bullets pulled from the source doc's foot-guns / lessons / anti-patterns sections. Helps the agent decide whether to read the full source.>
     ```

**Frontmatter authoring — concrete seeds for each of the 13:**

| slug | source file | strategy | description seed (one sentence) | trigger seed (top 5 keywords) |
|---|---|---|---|---|
| b-code-dispatch-coordination | b-code-dispatch-coordination.md | INLINE | Coordination protocol for dispatching briefs to B-codes b1-b4 — mailbox pattern, dispatched_by frontmatter, ship reply target. | dispatch, b-code, b1, b2, b3, b4, mailbox, CODE_N_PENDING |
| capability-extension-template | capability-extension-template.md | POINTER | Template for extending Cortex per-matter capability sets — used when adding domain-specific reasoning to a matter desk. | capability set, capability framework, matter-PM, cortex capability, capability extension |
| claude-settings-forge-collision-runbook | claude-settings-forge-collision-runbook.md | INLINE | Recovery runbook for Claude Code settings vs Forge collisions during install / upgrade. | settings.json collision, forge collision, claude code settings, harness settings |
| cortex-config-template | cortex-config-template.md | INLINE | Template for writing per-matter `cortex-config.md` that wires a matter into Cortex Stage 2. | cortex-config, cortex config, per-matter config, matter cortex setup |
| desk-gmail-reach | desk-gmail-reach-sop.md | INLINE | SOP for wiring a matter desk to reach into Gmail for transcript / document pulls. | desk gmail, gmail reach, desk email integration, matter gmail |
| important-document | important-document-sop.md | INLINE | SOP for handling Director-flagged important documents — capture, classify, store, surface. | important document, flagged document, director important, document classification |
| install-agent-to-brisen-lab | install-agent-to-brisen-lab-sop.md | POINTER | Canonical 12-row wiring map for installing a new agent (desk / worker / specialist) into Brisen Lab — proven 9x speedup vs ad-hoc install. | install agent, brisen lab install, desk on bus, new card slot, TERMINALS array, KNOWN_CARD_SLUGS, BAKER_ROLE case |
| matter-onboarding-runbook | matter-onboarding-runbook.md | POINTER | Runbook for onboarding a new matter into Baker — slug, cortex-config, capability wiring, room build, desk install. | matter onboarding, new matter, onboard matter, matter setup, slug registry, matter cortex |
| project-room-build | project-room-build-sop.md | POINTER | SOP for building a project room (7-folder Nate pattern) — used for hag-pilot, MOVIE, future matters needing dedicated room. | project room, room build, 7-folder pattern, nate pattern, matter room setup |
| specialist-prompt-template | specialist-prompt-template.md | POINTER | Template for authoring Cortex specialist prompts (legal / finance / tax-CH/AT/DE / game-theory) invoked from Phase 3b. | specialist prompt, cortex specialist, capability prompt, phase 3b prompt, domain specialist template |
| v2-bridge-cutover-runbook | v2-bridge-cutover-runbook.md | INLINE | Runbook for V2_BRIDGE cutover — migrating off paste-block-via-Director to direct bus / MCP posts. | v2 bridge, v2-bridge, cutover, bridge migration |
| worker-execution-of-matter-filing | worker-execution-of-matter-filing-sop.md | INLINE | SOP for a CM worker executing a matter filing — folder discipline, source-card fold, gate to filer. | worker filing, matter filing, CM filing, filing protocol, filer handoff, source card fold |
| writer-contract | writer-contract.md | INLINE | Contract for any agent writing to vault — what may be written, by whom, with what audit trail. | writer contract, vault write, who can write, vault write rules |

### Key constraints
- `MANDATORY TRIGGERS:` must be in the description body (after the leading "Use when..." paragraph), not in frontmatter as a separate key. Claude Code reads the whole description string; the magic word `MANDATORY TRIGGERS:` is the convention agents and humans both scan for.
- DO NOT modify the source `_ops/processes/<file>.md` content during this migration. Skills mirror, not replace.
- INLINE body must be byte-faithful to the source doc (after the frontmatter, if any). No editorial changes. The "mirror" claim requires it.
- POINTER body must NOT duplicate the source content — the whole point is to keep the catalog cheap. Foot-guns recap is fine as a teaser, not a copy.
- Slug must be filesystem-safe (lowercase, hyphenated, no spaces).

### Verification

For each of the 13:
```bash
ls ~/baker-vault/_ops/skills/<slug>/SKILL.md  # exists
head -5 ~/baker-vault/_ops/skills/<slug>/SKILL.md  # starts with --- frontmatter
grep -c "^name: <slug>$" ~/baker-vault/_ops/skills/<slug>/SKILL.md  # == 1
grep -c "MANDATORY TRIGGERS:" ~/baker-vault/_ops/skills/<slug>/SKILL.md  # >= 1
```

INLINE-only additional check (drift detection):
```bash
# Body byte-faithful to source. Strips YAML frontmatter (if present) from both
# sides; skips the H1 header + canonical-source marker on the skill side; then
# diffs. The awk pattern handles files both with and without frontmatter.
strip_frontmatter() {
  awk 'NR==1 && /^---$/ { in_fm=1; next }
       in_fm && /^---$/ { in_fm=0; next }
       !in_fm { print }' "$1"
}
diff <(strip_frontmatter ~/baker-vault/_ops/processes/<source>.md) \
     <(strip_frontmatter ~/baker-vault/_ops/skills/<slug>/SKILL.md \
       | awk '/^# / && !h {h=1; next} /Canonical source:/ && !c {c=1; next} h && c {print}')
# Expected: empty diff (allow small whitespace tolerance for the leading blank lines).
# False-positive failure (non-empty diff because of leading whitespace) is fine — just
# visually inspect. False-negative pass (empty diff hiding real drift) is the failure
# mode this check is designed to prevent.
```

---

## Fix 3 — Symlink each new vault skill into `~/.claude/skills/`

### Problem
Claude Code reads skills from `~/.claude/skills/`, not from `~/baker-vault/_ops/skills/`. Vault is the canonical home, but Claude Code needs the symlinks to pick the skills up at session start.

### Current state
6 existing symlinks already follow the pattern (e.g., `~/.claude/skills/agent-bus-posting-contract` -> `/Users/dimitry/baker-vault/_ops/skills/agent-bus-posting-contract`).

### Implementation

Save this one-shot script at `~/baker-vault/_ops/scripts/sop_skills_migration_symlinks.sh`, `chmod +x`, run once.

```bash
#!/bin/bash
# tools/sop-skills-migration/symlink-new-skills.sh — one-shot, run once after Fix 2 completes
set -euo pipefail

SLUGS=(
  b-code-dispatch-coordination
  capability-extension-template
  claude-settings-forge-collision-runbook
  cortex-config-template
  desk-gmail-reach
  important-document
  install-agent-to-brisen-lab
  matter-onboarding-runbook
  project-room-build
  specialist-prompt-template
  v2-bridge-cutover-runbook
  worker-execution-of-matter-filing
  writer-contract
)

VAULT_SKILLS="/Users/dimitry/baker-vault/_ops/skills"
HOME_SKILLS="$HOME/.claude/skills"

# Pre-flight: ensure home skills dir exists + is writable BEFORE any symlink work.
mkdir -p "$HOME_SKILLS"
write_test="$HOME_SKILLS/.write-test-$$"
touch "$write_test" 2>/dev/null || { echo "ERROR: $HOME_SKILLS not writable" >&2; exit 1; }
rm -f "$write_test"

created=0
skipped=0
for slug in "${SLUGS[@]}"; do
  src="$VAULT_SKILLS/$slug"
  dst="$HOME_SKILLS/$slug"
  if [ ! -d "$src" ]; then
    echo "ERROR: source missing: $src" >&2
    exit 1
  fi
  if [ -L "$dst" ]; then
    current_target=$(readlink "$dst")
    if [ "$current_target" = "$src" ]; then
      echo "SKIPPED (correct symlink exists): $dst"
      skipped=$((skipped+1))
    else
      echo "ERROR: $dst is a symlink to '$current_target', expected '$src' — manual reconciliation needed" >&2
      exit 1
    fi
  elif [ -e "$dst" ]; then
    echo "ERROR: $dst exists but is not a symlink — manual reconciliation needed" >&2
    exit 1
  else
    ln -s "$src" "$dst"
    echo "CREATED: $dst -> $src"
    created=$((created+1))
  fi
done
echo "Done. created=$created skipped=$skipped"
```

### Key constraints
- Symlink target MUST be absolute path (`/Users/dimitry/baker-vault/_ops/skills/<slug>`), not relative. Mirrors the existing pattern (verify via `readlink ~/.claude/skills/agent-bus-posting-contract`).
- If a symlink at `~/.claude/skills/<slug>` already exists, skip (do not overwrite — defensive).
- If a regular directory at `~/.claude/skills/<slug>` already exists, abort and surface to deputy (means there was a prior unmirrored install that needs reconciliation before this brief proceeds).

### Verification

```bash
for slug in b-code-dispatch-coordination capability-extension-template claude-settings-forge-collision-runbook cortex-config-template desk-gmail-reach important-document install-agent-to-brisen-lab matter-onboarding-runbook project-room-build specialist-prompt-template v2-bridge-cutover-runbook worker-execution-of-matter-filing writer-contract; do
  if [ -L "$HOME/.claude/skills/$slug" ]; then
    target=$(readlink "$HOME/.claude/skills/$slug")
    echo "OK $slug -> $target"
  else
    echo "MISSING $slug"
  fi
done
# Expected: 13 OK lines, 0 MISSING
```

---

## Fix 4 — Uplift the 7 home-only skills to vault

### Problem
Seven skills exist in `~/.claude/skills/<slug>/SKILL.md` as REGULAR FILES (not symlinks). They were authored locally and never moved to vault, so other agents (b-codes, hag-desk, matter desks) can't see them via their own picker installs. Cross-agent sharing requires the canonical body to live in vault.

### Current state — the 7 home-only skills

```
~/.claude/skills/aidennis-edge-scout/SKILL.md
~/.claude/skills/build-pm/SKILL.md
~/.claude/skills/director-facing-filter-contract-validator/SKILL.md
~/.claude/skills/director-facing-filter-stakeholder-validator/SKILL.md
~/.claude/skills/dropbox-file-delivery/SKILL.md
~/.claude/skills/skill-installation/SKILL.md
~/.claude/skills/write-brief/SKILL.md
```

Confirm the list by re-running this audit at brief start:
```bash
comm -13 <(ls ~/baker-vault/_ops/skills/ | sort) <(ls ~/.claude/skills/ | sort)
# Filter to entries that are directories (not stray files like INDEX.md)
```

### Implementation

Bundle as a one-shot uplift script at `~/baker-vault/_ops/scripts/sop_skills_migration_uplift.sh`:

```bash
#!/bin/bash
# One-shot uplift of home-only skills to vault. Run once.
# Critical safety: mv + ln -s pair is NOT atomic under set -e. If the symlink
# step fails after mv succeeds, the skill is unreachable to Claude Code. We
# pre-flight writability + use a rollback trap on the most recent move.
set -euo pipefail

SLUGS=(
  aidennis-edge-scout
  build-pm
  director-facing-filter-contract-validator
  director-facing-filter-stakeholder-validator
  dropbox-file-delivery
  skill-installation
  write-brief
)

VAULT_SKILLS="/Users/dimitry/baker-vault/_ops/skills"
HOME_SKILLS="$HOME/.claude/skills"

# Pre-flight: writability check on both dirs BEFORE any mv runs.
mkdir -p "$HOME_SKILLS" "$VAULT_SKILLS"
for d in "$HOME_SKILLS" "$VAULT_SKILLS"; do
  t="$d/.write-test-$$"
  touch "$t" 2>/dev/null || { echo "ERROR: $d not writable" >&2; exit 1; }
  rm -f "$t"
done

# Rollback trap: if we mv'd but failed to ln -s, restore the dir to home.
pending_slug=""
restore_on_error() {
  if [ -n "$pending_slug" ] && [ -d "$VAULT_SKILLS/$pending_slug" ] && [ ! -e "$HOME_SKILLS/$pending_slug" ]; then
    echo "ROLLBACK: restoring $pending_slug to home (mv succeeded but ln -s did not)" >&2
    mv "$VAULT_SKILLS/$pending_slug" "$HOME_SKILLS/$pending_slug" || true
  fi
}
trap restore_on_error EXIT

moved=0
skipped=0
for slug in "${SLUGS[@]}"; do
  src="$HOME_SKILLS/$slug"
  dst="$VAULT_SKILLS/$slug"
  if [ -L "$src" ]; then
    echo "SKIPPED (already symlink): $src"
    skipped=$((skipped+1))
    continue
  fi
  if [ ! -d "$src" ]; then
    echo "ERROR: source missing: $src" >&2
    exit 1
  fi
  if [ -e "$dst" ]; then
    echo "ERROR: destination already exists: $dst (manual reconciliation needed)" >&2
    exit 1
  fi
  pending_slug="$slug"
  mv "$src" "$dst"
  ln -s "$dst" "$src"
  pending_slug=""  # success — clear rollback marker
  echo "UPLIFTED: $slug ($src -> $dst, symlink replaced)"
  moved=$((moved+1))
done
trap - EXIT  # clear trap on clean exit
echo "Done. moved=$moved skipped=$skipped"
```

### Key constraints
- DO NOT touch skills that are ALREADY symlinks (pre-existing vault mirrors).
- DO NOT overwrite if vault destination already exists (means there was a vault-side authoring that should be reconciled by hand).
- The 7-slug list may shift between brief authoring (2026-05-25) and execution. Re-run the audit (`comm -13` above) at start; if the list differs by more than ±2 entries, surface to deputy before proceeding.

### Verification

```bash
for slug in aidennis-edge-scout build-pm director-facing-filter-contract-validator director-facing-filter-stakeholder-validator dropbox-file-delivery skill-installation write-brief; do
  if [ -L "$HOME/.claude/skills/$slug" ] && [ -d "$HOME/baker-vault/_ops/skills/$slug" ]; then
    echo "OK $slug"
  else
    echo "BROKEN $slug"
  fi
done
# Expected: 7 OK lines, 0 BROKEN
```

---

## Fix 5 — Update `_ops/skills/INDEX.md` with new entries

### Problem
`~/baker-vault/_ops/skills/INDEX.md` is the human-readable catalog of skills. It needs entries for the 13 new mirrors + the 7 uplifts so future authors discover existing skills.

### Current state
Read `~/baker-vault/_ops/skills/INDEX.md` to see the format. Likely a markdown table or bullet list of `<slug> — <one-line description>` entries.

### Implementation
For each of the 20 new entries (13 mirror + 7 uplift), append a line in the existing format. Group them at the bottom under a `## Added 2026-05-25 (SOPS_TO_SKILLS_MIGRATION_1)` heading so the audit trail is preserved.

If `INDEX.md` is structured by category (e.g., AI Head / Matter Desks / etc.), file each entry under the right category instead of a flat append. Read the file to decide.

### Key constraints
- Preserve existing entries unchanged.
- Each new line names the slug, the one-line "Use when..." description from the SKILL.md (copy verbatim), and a 4-letter tag (INLINE/POINTER/UPLIFT) so the migration provenance is visible.

### Verification
b3: read `INDEX.md` first to determine its actual structure (bullet list vs markdown table vs categorized). Pick the count-check that matches:
```bash
# If INDEX.md is bullet list (lines start with "- "):
grep -c "^- " ~/baker-vault/_ops/skills/INDEX.md
# Count up by exactly 20 (13 new mirrors + 7 uplifts)

# If INDEX.md is a markdown table (rows start with "|"):
grep -c "^|" ~/baker-vault/_ops/skills/INDEX.md
# Count up by exactly 20 (excluding header + separator rows already present)

# If structure is ambiguous: fail loud, surface to deputy, do NOT proceed.
```

---

## Fix 6 — Verify skills auto-load in a fresh Claude Code session

### Problem
The catalog wiring is only worth anything if Claude Code actually picks the skills up at session start. Need to confirm before declaring the brief shipped.

### Implementation

1. Open a fresh Claude Code session in `~/bm-b3/` (or any picker directory).
2. In the system-reminder block at session start, look for the `## Available skills` section. Confirm at least 5 of the 13 new + 7 uplift slugs appear (full set should appear; ≥5 is the floor since the available-skills list may be paginated or filtered).
3. Spot-check 3 trigger fires by issuing prompts that should auto-load the skill:
   - "install a new agent to brisen lab" → expect `install-agent-to-brisen-lab` skill to fire
   - "write brief for X" → expect `write-brief` skill to fire
   - "dispatch b3 with brief Y" → expect `b-code-dispatch-coordination` skill to fire (or be available in the catalog)
4. For each spot-check that does NOT fire: read the SKILL.md's `MANDATORY TRIGGERS:` line, identify why the keyword didn't match, surface to deputy. If it's a missing trigger keyword: append it + re-test.

### Key constraints
- Spot-check 3 minimum. Document the prompts used + fire/no-fire result in the ship report.
- If a trigger doesn't fire and the missing keyword is obvious from the source process doc, b3 may add it inline (1-line edit to description). If the miss is non-obvious, surface to deputy — do not guess.

### Verification

Ship report includes:
- The audit-script output from Fix 1
- The 3 spot-check prompts + fire/no-fire results
- Total skill count in vault before/after (`ls ~/baker-vault/_ops/skills/ | wc -l`)
- Total symlinks in home before/after (`find ~/.claude/skills/ -maxdepth 1 -type l | wc -l`)

---

## Files Modified

- `~/baker-vault/_ops/skills/<slug>/SKILL.md` — 13 new files created (Fix 2)
- `~/baker-vault/_ops/skills/<slug>/` — 7 directories moved from `~/.claude/skills/` (Fix 4)
- `~/baker-vault/_ops/skills/INDEX.md` — 20 new entries appended (Fix 5)
- `~/baker-vault/_ops/scripts/sop_skills_migration_symlinks.sh` — new one-shot script (Fix 3)
- `~/baker-vault/_ops/scripts/sop_skills_migration_uplift.sh` — new one-shot script (Fix 4)
- `~/.claude/skills/<slug>` — 20 new symlinks (13 from Fix 3 + 7 replacements from Fix 4)

## Do NOT Touch

- `~/baker-vault/_ops/processes/*.md` — canonical bodies stay unchanged. Skills mirror, not replace.
- `~/baker-vault/_ops/skills/agent-bus-posting-contract/` — already migrated, leave alone.
- Existing symlinks in `~/.claude/skills/` — only ADD new ones, do not modify or recreate existing ones.
- `~/bm-aihead1/.claude/skills/`, `~/bm-aihead2/.claude/skills/`, `~/bm-b{1,2,3,4}/.claude/skills/` — picker-local skills directories. This brief touches user-global `~/.claude/skills/` only. Picker symlinks (if any) are wired separately by the picker install SOPs.
- `~/.claude/CLAUDE.md`, project CLAUDE.md, and AH1/AH2 orientation files — no Tier 1 routing edits needed. Skills auto-fire on trigger; no manual routing required.

## Quality Checkpoints

1. Audit script output (Fix 1) matches the expected baseline ±2 entries.
2. 13 new `SKILL.md` files created, each with valid frontmatter (`name:` matches dirname, description contains `MANDATORY TRIGGERS:`).
3. INLINE bodies byte-faithful to source process doc (diff check).
4. POINTER bodies do NOT duplicate the source content (no full body copy).
5. 13 new symlinks in `~/.claude/skills/`, target absolute paths into vault.
6. 7 uplifted skills moved cleanly: vault contains the real directory, home contains a symlink to it.
7. `INDEX.md` has 20 new entries under the migration heading.
8. Fresh Claude Code session shows the new skills in the `## Available skills` system-reminder block.
9. 3 spot-check trigger fires documented in the ship report (PASS or surface-to-deputy).
10. `git status` in baker-vault shows only the migration scope (no unrelated edits).
11. Pre-commit hook clean (cascade-backprop check passes — this migration touches `_ops/skills/`, not `_ops/agents/`, so cascade rule does not apply; verify the hook doesn't false-positive).
12. Commit message references this brief id + lists the 13 + 7 slugs in the body.

## Verification SQL

N/A — this brief touches markdown files and symlinks only. No database writes.

## Gate chain (after ship)

- Gate-1 architecture: deputy (AH2) — verify the 13 + 7 slug list matches the audit
- Gate-2 security: deputy (AH2) — light pass (markdown + symlinks; the two scripts must not run as root, must not touch outside the two named directories)
- Gate-3 picker-architect: SKIP (no install / picker / harness change)
- Gate-4 code-reviewer 2nd-pass: deputy (AH2) — verify INLINE byte-faithfulness + POINTER no-duplication + symlink targets absolute
- Gate-5 merge: lead (AH1) — merges vault commit + runs the 2 one-shot scripts once each, observes `created=N skipped=M` audit line

## Reply target

Post your ship report bus message to **deputy (AH2)** with topic `ship/sops-to-skills-migration-1`. Deputy runs Gates 1+2+4 then hands to lead for Gate-5 merge + script execution. CC lead on the ship report so he sees the queue.

## Director context

Director read thevccorner.com Substack article "Prompts Are Dead. Skills Are the New Moat" on 2026-05-25. The article validated the direction we'd already started — `_ops/skills/` is the canonical mirror for SOPs, the agentskills.io open standard makes `SKILL.md` portable across agent runtimes (Anthropic, Cursor, Vercel, OpenAI, Microsoft VS), and skills auto-fire on trigger keyword without needing manual Tier 1 routing in CLAUDE.md.

Director-ratified Q-locks (chat 2026-05-25, in response to deputy's plan presentation):
- Q1 = A: body strategy is INLINE for SOPs <200 LOC, POINTER for ≥200 LOC.
- Q2 = B: migration scope is `*-sop.md|*-contract.md|*-runbook.md|*-coordination.md|*-template.md`, NOT every process doc.
- Q3 = A: companion eval brief targets static trigger-keyword match only for v1.

## What NOT to do

- Do NOT bulk-rewrite the source `_ops/processes/*.md` docs. Skills mirror; canonical body stays in process file.
- Do NOT inline the 5 POINTER files. They're flagged POINTER because the catalog cost would be too high.
- Do NOT add new skills outside the 13 migration + 7 uplift list. Scope creep is the failure mode this brief is designed to prevent.
- Do NOT modify trigger keywords in pre-existing skills (`agent-bus-posting-contract` and other already-symlinked entries). The 7 uplift edits move the file but do NOT edit its content.
- Do NOT install a recurring sync hook. This is a one-shot migration. Future drift between `_ops/processes/<file>.md` and the INLINE skill body will be flagged by the companion eval brief, not auto-resolved here.
- Do NOT bypass git hooks (--no-verify). The cascade-backprop check is the only relevant hook; this migration doesn't touch desk runtime, so it should pass clean. If it fails, surface to deputy — do not bypass.
- Do NOT touch `~/.claude/CLAUDE.md` or any picker CLAUDE.md to "add Tier 1 routing for the new skills". Skills auto-fire on the trigger keywords declared in their description; manual routing is the OLD pattern we're moving off.
