# BRIEF: SOT_OBSIDIAN_UNIFICATION_1 — Single Source of Truth in baker-vault (Obsidian-native)

**Prepared by:** AI Head
**Date:** 2026-04-20
**Director-approved:** 2026-04-20 (plain English: *"proper architectural fix"* + *"mount Cowork there, I need him to be as equipped with everything, incl Cortex, as you code"* + 5-phase plan approval)
**Target reviewer:** B2
**Target implementer:** single B-code across 5 sequential PRs (one per phase)

## Context

This session, **AI Dennis (IT Shadow Agent) diagnosed "lost-file syndrome"** on his first live invocation — a pattern where operational artifacts (skills, briefs, agent memory, process docs) live in 3+ scattered locations with no index, no install procedure, no registry. Specific symptoms verified by AI Head in `/tmp/bm-draft` + local filesystem this session:

1. **AI Dennis skill exists in 3 copies** with observable drift:
   - `~/.claude/skills/it-manager/SKILL.md` — 16,150 bytes, 2026-04-19 (latest, Claude App runtime)
   - `Baker-Project/pm/ai-operations/it-manager/AI_DENNIS_SKILL.md` — 16,150 bytes, 2026-03-05 (source-of-truth-intent)
   - `Dropbox/.skills/skills/it-manager/SKILL.md` — 4,650 bytes, 2026-02-24 (**outdated by 71%**)
2. **Cowork has no local skill directory.** Verified `~/Library/Application Support/Claude/` contains only extension mounts + caches — no discrete skills folder. Cowork's skill registry is cloud-delivered; local file placement doesn't equip Cowork.
3. **`/write-brief` was undocumented** (now partially resolved — this brief is being authored under that skill, which lives at `~/.claude/skills/write-brief/SKILL.md`, 8,200+ LOC, but not documented as markdown anywhere Cowork or a new session can discover).
4. **AI Dennis memory architecture has drifted** — skill v3 (2026-03-05) specifies 3 files (`AI_DENNIS_OPERATING.md`, `AI_DENNIS_LONGTERM.md`, `AI_DENNIS_ARCHIVE.md`). Reality: only `AI_DENNIS_MEMORY.md` (single legacy file, 4,711 bytes).
5. **Cowork mounts are read-only** per AI Dennis's report. Any skill saying "update memory at session end" cannot execute from Cowork.
6. **No registry of any kind** — no INDEX for skills, briefs, shadow agents, or processes. `pm/briefs/` holds 24+ files; no INDEX.md, no TEMPLATE.md verified absent (`ls` returned file-not-found for both).

Director's framing: *"If the SoT starts to live now at Obsidian, not on render — what will be the damage?"* AI Head response: *"Render was never the SoT"* — the actual version-controlled sources of truth are GitHub repos (`baker-master` + `baker-vault`); this brief canonicalizes ops artifacts into `baker-vault/_ops/` so there is **one browsable home** (Obsidian) + **one version-controlled source** (GitHub) + **deployed copies to runtime paths** (via sync script) + **Cowork-equal access** (via MCP bridge).

**This brief is the FIRST time any of these artifacts will be canonicalized.** Prior to now, each artifact found its own home based on when it was created; no one was ever designated "the winner."

## Estimated time: ~12-16h total across 5 phases
## Complexity: Medium-High
## Prerequisites

- `~/baker-vault/` git clone exists on both Mac Mini and Director's Mac (verified this session)
- `.obsidian/` configured (verified — `app.json`, `plugins`, `workspace.json` all present)
- Baker MCP server live (verified — 25+ tools including `baker_raw_query` / `baker_raw_write`)
- B-codes live in `~/bm-b{N}/` (memory rule)
- Director available for per-phase authorization (Tier B — Phases B + D + E touch invariant / prod config)

---

## Fix/Feature 1 (Phase A): Scaffold `_ops/` tree + INDEX/TEMPLATE + sync-script skeleton

### Problem

`~/baker-vault/` has `wiki/` (CHANDA / Silver / Gold territory) but no home for operational artifacts. Skills, briefs, agent memory, and process docs currently live in 3+ scattered locations with no index.

### Current State

```
~/baker-vault/
├── config/
├── raw/
├── schema/
├── slugs.yml
└── wiki/
    ├── _inbox
    ├── entities
    ├── hot.md
    ├── index.md
    ├── matters
    ├── people
    └── research
```

No `_ops/`. No install scripts.

### Implementation

Branch: `sot-obsidian-1-phase-a`. All work in the `baker-vault` repo (NOT `baker-master`).

**Step 1.1 — Scaffold the `_ops/` tree:**

```bash
cd ~/baker-vault
mkdir -p _ops/skills _ops/briefs _ops/agents _ops/processes _install
```

**Step 1.2 — Create `_ops/INDEX.md`** with frontmatter that tells the Cortex T3 pipeline to skip this subtree:

```markdown
---
type: ops
ignore_by_pipeline: true
author: ai-head
created: 2026-04-20
---

# `_ops/` — Operational Artifacts Registry

This subtree holds skills, briefs, shadow-agent memory, and process docs for Brisen Group's AI infrastructure. It is **NOT** part of the Silver/Gold learning loop — the Cortex T3 pipeline explicitly skips anything with frontmatter `ignore_by_pipeline: true`.

## Registries

- [Skills](skills/INDEX.md) — installed agents, triggers, protocols
- [Briefs](briefs/INDEX.md) — numbered implementation briefs, status tracking
- [Agents](agents/INDEX.md) — shadow agents (AI Dennis, future)
- [Processes](processes/INDEX.md) — documented workflows (write-brief, bank-model, etc.)

## Writer contract (CHANDA Inv 9 carve-out)

CHANDA Invariant 9 says Mac Mini is the single **agent** writer to `~/baker-vault`. That applies to `wiki/` (Silver/Gold). The `_ops/` subtree is exempt — B-codes and AI Head may write via git push; Mac Mini pulls the result in the same cycle as the wiki sync. Director may edit any `_ops/` file from any machine.

See [_ops/processes/writer-contract.md](processes/writer-contract.md) for the full rule.
```

**Step 1.3 — Create `_ops/skills/INDEX.md`** as a skill registry (empty at Phase A, populated in Phase B):

```markdown
---
type: ops
ignore_by_pipeline: true
---

# Skills Registry

| Skill | Canonical Path | Runtime Paths (sync targets) | Version | Last Updated |
|---|---|---|---|---|
| *(populated in Phase B)* | | | | |

## Install procedure

Run `~/baker-vault/_install/sync_skills.sh` after any change in `_ops/skills/`. The script:
1. Reads this registry (source of truth).
2. For each row: validates canonical path exists.
3. For each runtime path: creates symlink (or copies — see script for platform choice).
4. Reports success/fail per skill.

**Do NOT manually edit skills in runtime paths.** They are symlinks (or regenerable copies). Edit only under `_ops/skills/<name>/SKILL.md`.
```

**Step 1.4 — Create `_ops/briefs/INDEX.md`** + `_ops/briefs/TEMPLATE.md`:

`INDEX.md`:

```markdown
---
type: ops
ignore_by_pipeline: true
---

# Briefs Registry

| Brief ID | Title | Status | Owner | PR | Merged |
|---|---|---|---|---|---|
| *(populated in Phase C migration)* | | | | | |

Status values: `draft` / `ratified` / `in-flight` / `merged` / `archived` / `parked`

**Numbering rule:** `BRIEF_<ALL_CAPS_NAME>_<N>` where N increments for versioned briefs (KBL_B_STEP1 v1 → v2 = same ID suffix v-tag, not new N).
```

`TEMPLATE.md` — 1:1 copy of the `/write-brief` protocol (self-documenting). AI Head will produce this in Phase A by copying the skill's instruction section verbatim.

**Step 1.5 — Create `_ops/agents/INDEX.md`** (list of shadow agents):

```markdown
| Agent | Shadows | Canonical Memory | Status |
|---|---|---|---|
| AI Dennis | Dennis Egorenkov (IT Admin) | [ai-dennis/](ai-dennis/) | deployed, migrated Phase B |
```

**Step 1.6 — Create `_ops/processes/INDEX.md`** (pointer list — contents land in Phases B–E):

```markdown
| Process | File | Scope |
|---|---|---|
| write-brief | write-brief.md | How AI Head authors briefs (Phase B) |
| bank-model | bank-model.md | Tier A/B/C authorization (Phase B) |
| writer-contract | writer-contract.md | _ops/ carve-out from Inv 9 (Phase A — this phase) |
| git-mailbox | git-mailbox.md | How B-codes dispatch (Phase B) |
```

**Step 1.7 — Create `_ops/processes/writer-contract.md`** (the one process doc that lands in Phase A):

```markdown
---
type: ops
ignore_by_pipeline: true
---

# Writer Contract — `_ops/` carve-out from CHANDA Invariant 9

**Inv 9 says:** "Mac Mini is the single agent writer to ~/baker-vault. Director may edit Gold from any machine; human writes are out-of-band and human-paced. Render writes only to wiki_staging."

**Scope of Inv 9:** `wiki/` (Silver + Gold). The learning loop depends on single-writer for Silver so Mac Mini's poller can trust what it sees.

**`_ops/` is explicitly exempt from Inv 9** because:
1. `_ops/` is outside the learning loop (pipeline skips it via `ignore_by_pipeline: true`).
2. Ops artifacts need faster iteration than Silver does — B-codes + AI Head edit frequently.
3. Git is an adequate intermediary — no direct filesystem writes by agents; all changes flow through PR + merge.

**Writer rules for `_ops/`:**
- AI Head: commits directly to `baker-vault` main (Tier B authorization per commit, per bank model).
- B-codes: work in branch, open PR against `baker-vault`, another B-code reviews, AI Head auto-merges per Tier A standing.
- Director: edits anywhere, any file, any time. Preserves `author: director` frontmatter where present.
- Mac Mini's poller: pulls `_ops/` on every cycle alongside `wiki/` sync; does NOT itself write to `_ops/`.
- Render: never writes to `_ops/` (same as Inv 9 — Render only writes `wiki_staging`).

This carve-out is a **refinement**, not a breach, of Inv 9. CHANDA.md Section 3 Invariant 9 to be updated in Phase E to cite this file.
```

**Step 1.8 — Create `_install/sync_skills.sh`** (skeleton — real content in Phase B):

```bash
#!/usr/bin/env bash
# Phase A skeleton — does nothing yet. Phase B wires it up.
set -euo pipefail

VAULT_ROOT="${HOME}/baker-vault"
CLAUDE_SKILLS="${HOME}/.claude/skills"

echo "[sync_skills] Phase A skeleton — Phase B will populate."
echo "[sync_skills] vault: ${VAULT_ROOT}/_ops/skills/"
echo "[sync_skills] target: ${CLAUDE_SKILLS}/"
exit 0
```

`chmod +x _install/sync_skills.sh`.

**Step 1.9 — Commit + push:**

```bash
cd ~/baker-vault
git add _ops/ _install/
git commit -m "SOT_OBSIDIAN_UNIFICATION_1 Phase A: scaffold _ops/ + _install/ + writer-contract

Creates canonical home for operational artifacts (skills, briefs, agent
memory, process docs) in ~/baker-vault/_ops/. Frontmatter flag
ignore_by_pipeline=true keeps these files invisible to Cortex T3 learning
loop (wiki/ is Silver/Gold territory).

Registries seeded but empty; population lands in Phases B-E.

Writer-contract.md documents the _ops/ carve-out from CHANDA Inv 9.
CHANDA.md itself to be updated in Phase E with formal reference.

Director-authorized 2026-04-20 via 5-phase plan approval.

Co-Authored-By: Code Brisen <code-brisen@brisengroup.com>"
git push origin main
```

### Key Constraints

- **DO NOT** touch `wiki/` in this phase. This phase is purely additive — new subtree, no existing-file edits.
- **DO NOT** modify `CHANDA.md` in this phase. Inv 9 refinement is Phase E; must cite `writer-contract.md` which itself isn't ratified until all five phases land.
- **DO NOT** execute `sync_skills.sh` on the runtime `~/.claude/skills/` directory — Phase A skeleton only. Real sync is Phase B.
- **DO NOT** migrate any real skill, brief, or agent content in Phase A. Just scaffolding.

### Verification

```bash
ls -la ~/baker-vault/_ops/
# Expected: skills/ briefs/ agents/ processes/ INDEX.md

ls ~/baker-vault/_ops/skills/INDEX.md ~/baker-vault/_ops/briefs/INDEX.md ~/baker-vault/_ops/briefs/TEMPLATE.md ~/baker-vault/_ops/agents/INDEX.md ~/baker-vault/_ops/processes/INDEX.md ~/baker-vault/_ops/processes/writer-contract.md
# All 6 should exist.

head -5 ~/baker-vault/_ops/INDEX.md
# Frontmatter must include type: ops and ignore_by_pipeline: true.

bash ~/baker-vault/_install/sync_skills.sh
# Expected: Phase A skeleton message, exit 0. No actual sync.

git -C ~/baker-vault log --oneline -1
# Expected: "SOT_OBSIDIAN_UNIFICATION_1 Phase A: scaffold ..."
```

---

## Fix/Feature 2 (Phase B): Migrate AI Dennis + populate skill/process registries

### Problem

AI Dennis skill has 3 copies with 71% drift on the oldest. Memory architecture drifted from v3 spec (3 files) to reality (1 legacy file). No write-brief or bank-model process docs exist outside of Claude App skill files.

### Current State

**AI Dennis skill sources:**
- `~/.claude/skills/it-manager/SKILL.md` — 16,150 B, 2026-04-19 (Claude App runtime)
- `Baker-Project/pm/ai-operations/it-manager/AI_DENNIS_SKILL.md` — 16,150 B, 2026-03-05
- `Dropbox/.skills/skills/it-manager/SKILL.md` — 4,650 B, 2026-02-24 (outdated)

**AI Dennis memory:**
- `Baker-Project/pm/ai-operations/it-manager/AI_DENNIS_MEMORY.md` — 4,711 B, single file (skill v3 specifies 3 files)

**Process docs:** none as markdown. `/write-brief` lives only at `~/.claude/skills/write-brief/SKILL.md` (invisible to Cowork or fresh sessions).

### Implementation

Branch: `sot-obsidian-1-phase-b`.

**Step 2.1 — Canonicalize AI Dennis skill:**

1. `cp "~/Vallen Dropbox/Dimitry vallen/Baker-Project/pm/ai-operations/it-manager/AI_DENNIS_SKILL.md" ~/baker-vault/_ops/skills/it-manager/SKILL.md` (use the March 5 16,150 B version as canonical — identical byte-count to April 19 runtime copy).
2. Verify: `diff ~/baker-vault/_ops/skills/it-manager/SKILL.md ~/.claude/skills/it-manager/SKILL.md` → expected zero diff (both should be the same 16,150 B file).
3. If diff non-zero, abort. Escalate to AI Head. Drift resolution needs Director-in-the-loop.

**Step 2.2 — Split AI Dennis memory per v3 spec:**

Read `~/Vallen Dropbox/Dimitry vallen/Baker-Project/pm/ai-operations/it-manager/AI_DENNIS_MEMORY.md`. Split into three files per skill v3 section "Memory architecture":

- `~/baker-vault/_ops/agents/ai-dennis/OPERATING.md` — short-horizon (<80 lines, rewrite-style). Contents: current IT work queue, active incidents, today's priorities. Seed from "current state" section of legacy MEMORY.md.
- `~/baker-vault/_ops/agents/ai-dennis/LONGTERM.md` — durable context (<200 lines, update-style). Contents: M365 migration state, BCOMM/EVOK vendor notes, IT infrastructure baselines. Seed from "persistent context" section.
- `~/baker-vault/_ops/agents/ai-dennis/ARCHIVE.md` — append-only. Contents: historical handovers, closed incidents. Seed from anything time-stamped in legacy MEMORY.md.

Frontmatter for all three:

```yaml
---
type: ops
ignore_by_pipeline: true
agent: ai-dennis
file_role: operating | longterm | archive
updated: 2026-04-20
---
```

**Step 2.3 — Update skill registry (`_ops/skills/INDEX.md`):**

Add row:

```markdown
| it-manager | `_ops/skills/it-manager/SKILL.md` | `~/.claude/skills/it-manager/SKILL.md` | v3 | 2026-04-20 |
```

**Step 2.4 — Update agents registry (`_ops/agents/INDEX.md`):**

Replace the placeholder row with the AI Dennis canonical pointers; add link to the three memory files.

**Step 2.5 — Wire up `sync_skills.sh`:**

Replace Phase A skeleton with real logic. Use **symlinks** (not copies) so edits in `_ops/skills/<name>/SKILL.md` instantly reach the runtime:

```bash
#!/usr/bin/env bash
set -euo pipefail

VAULT_SKILLS="${HOME}/baker-vault/_ops/skills"
CLAUDE_SKILLS="${HOME}/.claude/skills"

mkdir -p "${CLAUDE_SKILLS}"

for skill_dir in "${VAULT_SKILLS}"/*/; do
    skill_name=$(basename "${skill_dir}")
    target="${CLAUDE_SKILLS}/${skill_name}"
    source="${skill_dir}"

    # Remove stale dir if present (ONLY if it's a symlink or empty dir — never blow away real data)
    if [ -L "${target}" ]; then
        rm "${target}"
    elif [ -d "${target}" ] && [ -z "$(ls -A "${target}")" ]; then
        rmdir "${target}"
    elif [ -e "${target}" ]; then
        echo "[sync_skills] SKIP ${skill_name}: target exists and is not a symlink or empty dir. Manual review required."
        continue
    fi

    ln -s "${source%/}" "${target}"
    echo "[sync_skills] OK ${skill_name}"
done

echo "[sync_skills] done"
```

**Safety:** The script never deletes a non-symlink non-empty directory. If a skill already has real files in `~/.claude/skills/`, the script skips it and logs — Director must intervene. This prevents catastrophic data loss if someone manually populated a runtime skill folder before the sync script ran.

**Step 2.6 — Document `/write-brief` + `bank-model` + `git-mailbox` as markdown:**

- `_ops/processes/write-brief.md` — copy the contents of `~/.claude/skills/write-brief/SKILL.md` verbatim as the body. Frontmatter: `type: ops`, `source_skill: write-brief`, `last_synced: 2026-04-20`. Going forward, treat `_ops/processes/write-brief.md` as the authoritative source and resync the skill from it (reverse-flow). Reverse-sync script is **out of scope for this brief** — note as follow-up.
- `_ops/processes/bank-model.md` — transcribe from `memory/feedback_ai_head_communication.md` (Director's ratified Tier A/B/C model).
- `_ops/processes/git-mailbox.md` — transcribe the mailbox pattern from current `_handovers/AI_HEAD_20260420.md` (Workflow patterns section).

**Step 2.7 — Populate processes registry:**

Update `_ops/processes/INDEX.md` rows — each process file now exists with a real link.

**Step 2.8 — Retire the 2 duplicate copies:**

- Rename `Baker-Project/pm/ai-operations/it-manager/AI_DENNIS_SKILL.md` → `AI_DENNIS_SKILL.md.retired-2026-04-20` with a one-line top comment: `# RETIRED — canonical source now at ~/baker-vault/_ops/skills/it-manager/SKILL.md`.
- Rename `Dropbox/.skills/skills/it-manager/SKILL.md` → same pattern.
- **Do not `rm`** — leave retired files in place for one sprint as a breadcrumb. Director may choose to `rm` after verifying sync_skills.sh works for 7+ days.

**Step 2.9 — Run sync_skills.sh + verify symlink:**

```bash
bash ~/baker-vault/_install/sync_skills.sh
ls -la ~/.claude/skills/it-manager
# Expected: lrwxr-xr-x ... it-manager -> /Users/dimitry/baker-vault/_ops/skills/it-manager
```

**Step 2.10 — Commit + push:**

```bash
cd ~/baker-vault
git add _ops/ _install/sync_skills.sh
git commit -m "SOT_OBSIDIAN_UNIFICATION_1 Phase B: migrate AI Dennis + populate registries

AI Dennis skill canonicalized at _ops/skills/it-manager/. Memory split
into OPERATING/LONGTERM/ARCHIVE per skill v3 spec. Process docs for
write-brief, bank-model, git-mailbox land in _ops/processes/.

sync_skills.sh now symlinks _ops/skills/ into ~/.claude/skills/ —
single edit surface, instant propagation. Script is safe-by-default:
skips any runtime path that holds real files (no data loss).

Two duplicate AI Dennis skill copies renamed .retired-2026-04-20 —
breadcrumb preserved for one sprint; Director may rm after burn-in.

Co-Authored-By: Code Brisen <code-brisen@brisengroup.com>"
git push origin main
```

### Key Constraints

- **DO NOT `rm` any existing file.** Rename to `.retired-*` only. Destructive deletion is Director-authorized only after 7+ days of burn-in.
- **DO NOT modify the live runtime skill** (`~/.claude/skills/it-manager/SKILL.md`) before the symlink is in place. Window of risk: between removing old symlink and creating new. Script handles this safely — don't reimplement.
- **Symlink direction:** vault is source, runtime is target. `ln -s /vault/path /runtime/path`. Never the other way.
- **File permissions:** symlinks should be readable by Claude App (mode 755 on parent dirs). macOS default permissions are fine; don't chmod.

### Verification

```bash
diff ~/baker-vault/_ops/skills/it-manager/SKILL.md ~/.claude/skills/it-manager/SKILL.md
# Expected: zero output (identical — because one IS the other via symlink).

readlink ~/.claude/skills/it-manager
# Expected: /Users/dimitry/baker-vault/_ops/skills/it-manager

ls ~/baker-vault/_ops/agents/ai-dennis/
# Expected: OPERATING.md LONGTERM.md ARCHIVE.md

wc -l ~/baker-vault/_ops/agents/ai-dennis/OPERATING.md
# Expected: ≤80 lines per skill v3 constraint.

wc -l ~/baker-vault/_ops/agents/ai-dennis/LONGTERM.md
# Expected: ≤200 lines per skill v3 constraint.

ls ~/baker-vault/_ops/processes/
# Expected: INDEX.md write-brief.md bank-model.md git-mailbox.md writer-contract.md

ls "Baker-Project/pm/ai-operations/it-manager/"
# Expected: AI_DENNIS_SKILL.md.retired-2026-04-20 (and MEMORY.md still present — see Phase B1 below for memory retirement)

# Director-side Obsidian check (not scriptable):
# Open Obsidian, navigate to baker-vault. Verify _ops/ shows up. Open
# _ops/skills/it-manager/SKILL.md. Confirm readable, frontmatter visible.
```

---

## Fix/Feature 3 (Phase C): Migrate `pm/briefs/` → `_ops/briefs/`

### Problem

`Baker-Project/pm/briefs/` holds 24+ briefs in a flat directory. No INDEX, no TEMPLATE, no numbering enforcement, no status tracking. New briefs have no canonical home.

### Current State

Flat directory with mixed naming conventions (`BRIEF_*.md`, `KBL_*.md`, `_DONE_*.md`). No registry. Untracked by git in some cases (per lesson #16 — "100+ briefs accumulated but never git-added").

### Implementation

Branch: `sot-obsidian-1-phase-c`.

**Step 3.1 — Freeze `Baker-Project/pm/briefs/` as historical.** Add a top-level `FROZEN.md`:

```markdown
# FROZEN — see baker-vault/_ops/briefs/

This directory is no longer the active brief location. As of 2026-04-20,
new briefs land in:

  ~/baker-vault/_ops/briefs/

Existing files here are historical only. Do not add new briefs to this folder.
Do not edit existing briefs here — copy to _ops/briefs/ first if revision needed.

Rationale: SOT_OBSIDIAN_UNIFICATION_1 Phase C (briefs/BRIEF_SOT_OBSIDIAN_UNIFICATION_1.md).
```

**Step 3.2 — Migrate existing briefs by STATUS:**

- **Merged / completed** (prefixed `_DONE_`): leave in `Baker-Project/pm/briefs/`. Historical. No migration.
- **Active / draft / ratified** (non-prefixed): `cp` to `~/baker-vault/_ops/briefs/<name>.md`. Do NOT rename. Do NOT delete from source. Add frontmatter if missing.

Exact list to copy (from verified `ls` this session):

```
BAKER-MCP-1_baker_mcp_server.md
BRIEF_AGENTIC_RAG_v1.md
BRIEF_DECISION_ENGINE_v1.md
BRIEF_MOVE_SYSHEALTH_TO_BAKERDATA.md
KBL-A_INFRASTRUCTURE_2T_CODE_BRIEF.md
KBL-A_INFRASTRUCTURE_CODE_BRIEF.md
PM-OOM-1_CODE_BRIEF.md
SENTINEL_HEALTH_1.md
```

8 briefs to copy. Each gets frontmatter:

```yaml
---
type: ops
ignore_by_pipeline: true
brief_id: <derived from filename>
status: <derived from git log / README notes>
owner: ai-head
migrated_from: Baker-Project/pm/briefs/<original>
migrated: 2026-04-20
---
```

**Step 3.3 — Populate `_ops/briefs/INDEX.md` registry** with one row per migrated brief + the three already-merged briefs from this session (#21 alias rename, #22 dead code, #23 conftest, #24 FEEDLY_WHOOP_KILL — all found in `briefs/_reports/` in baker-master).

**Step 3.4 — Copy this brief (SOT_OBSIDIAN_UNIFICATION_1) to `_ops/briefs/`** so the brief itself lives in its own registry from Phase C forward.

**Step 3.5 — Document the new brief dispatch path:**

Update `_ops/processes/git-mailbox.md` (created in Phase B): new briefs land in `~/baker-vault/_ops/briefs/` going forward. B-codes pull `baker-vault` in addition to `baker-master` to read new briefs. Dispatch mailboxes (`briefs/_tasks/CODE_*_PENDING.md`) remain in `baker-master` — that's a runtime mailbox, not a brief.

**Step 3.6 — Commit + push.**

### Key Constraints

- **DO NOT delete** any file from `Baker-Project/pm/briefs/`. Migration is copy-forward only.
- **DO NOT rename** migrated files. Preserve original names so git log can track provenance.
- **DO NOT migrate `_DONE_*`** files — those are historical, frozen in place, don't clutter new registry.
- **DO NOT migrate this brief (SOT_OBSIDIAN_UNIFICATION_1) itself until Step 3.4** — avoid chicken-and-egg during Phase C authoring.

### Verification

```bash
ls ~/baker-vault/_ops/briefs/
# Expected: ≥9 files (8 migrated + this brief + INDEX.md + TEMPLATE.md)

head -15 ~/baker-vault/_ops/briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md
# Expected: frontmatter with migrated_from pointing to original path.

cat ~/baker-vault/_ops/briefs/INDEX.md | grep -c "^|"
# Expected: ≥12 rows (8 migrated + this brief + 3 ship/merged briefs from this session + header row).

cat "Baker-Project/pm/briefs/FROZEN.md"
# Expected: the freeze notice.
```

---

## Fix/Feature 4 (Phase D): Cowork MCP bridge — `baker_vault_read`

### Problem

Cowork has no local filesystem access to `~/baker-vault/`. Its sandbox mounts are cloud-sandboxed extensions. Placing files in `_ops/` does not equip Cowork unless there's an MCP-mediated read path. Without this, AI Dennis and other Cowork-based agents cannot read skills, briefs, or agent memory from the canonical location.

### Current State

Baker MCP server (live, `mcp__baker__*` tools) has 25+ tools — all operating against PostgreSQL/Qdrant. No vault-file-read tool exists. Cowork cannot see `~/baker-vault/_ops/` content.

### Implementation

Branch: `sot-obsidian-1-phase-d`. Work in `baker-master` repo (the MCP server lives there).

**Step 4.1 — Locate the MCP tool registration.** Grep:

```bash
cd /tmp/bm-draft
grep -rn "mcp__baker__\|@mcp.tool\|register_tool\|baker_raw_query" --include="*.py" | head -20
```

Find the file that registers `baker_raw_query` and `baker_raw_write`. That's the pattern to follow.

**Step 4.2 — Add `baker_vault_read` tool:**

Behavior spec:
- Input: `path: str` (relative to `~/baker-vault/_ops/` — enforce prefix check to prevent path traversal)
- Output: file contents as string, max 500 KB. If file > 500 KB, return first 500 KB + truncation notice. If file missing, return `{"error": "not found"}`.
- Path safety: reject `..`, reject absolute paths, reject symlinks that resolve outside `_ops/`. Use `os.path.realpath()` + `startswith()` check.
- Read-only. No write counterpart (Cowork writes go through baker_raw_write or git-mailbox — separate mechanisms already covered in brief).
- Rate limit: standard MCP tool rate limit (no special handling needed beyond existing infrastructure).

**Step 4.3 — Add `baker_vault_list` tool** (directory listing):

- Input: `path: str = ""` (default = `_ops/` root)
- Output: list of `{name, type: "file"|"dir", size_bytes}` entries
- Same path-safety checks as `baker_vault_read`.

**Step 4.4 — Configuration:**

Vault path is determined at MCP server startup. Mac Mini has `~/baker-vault/` at a known location; Render does not. Options:

- (a) Env var `BAKER_VAULT_PATH` (default `~/baker-vault`) — set on Mac Mini if MCP server runs there, unset on Render → tool returns `{"error": "vault not available on this host"}`.
- (b) Render polls a cached copy synced from Mac Mini via separate channel — out of scope for this brief.

**Recommendation: (a).** MCP server today runs on Render (per existing architecture). For Cowork to access `_ops/` content, we need the MCP server to either: be hosted on Mac Mini (which has the vault) OR have a cached copy synced to Render. This is a **design question that surfaces in Phase D** — AI Head to resolve before Phase D implementation starts. Likely outcome: small FastAPI side-car on Mac Mini exposing `_ops/` read-only over Tailscale, reached by Render's MCP server via internal HTTP. Adds operational surface but preserves Render-vs-Mac-Mini separation.

**Phase D is partially blocked on this design decision.** AI Head to author a sub-brief (`SOT_OBSIDIAN_1_PHASE_D_TRANSPORT.md`) after Phase C merges, before Phase D starts implementation.

**Step 4.5 — Document in `_ops/processes/cowork-equipping.md`** (new file):

How Cowork reads `_ops/` content via `baker_vault_read` + `baker_vault_list`. Include worked example: AI Dennis in Cowork calls `baker_vault_read(path="skills/it-manager/SKILL.md")` at session start — gets canonical skill content, zero ambiguity.

**Step 4.6 — Commit + push.**

### Key Constraints

- **Path safety is load-bearing.** Test with `../`, `../../etc/passwd`, symlinks, empty string, `null` bytes. Reject everything that doesn't resolve under `_ops/`.
- **No write path in this phase.** Cowork writes stay on the legacy rails (baker_raw_write for DB, git-mailbox for code). Vault writes come via git from AI Head / B-codes.
- **Transport decision is Phase D sub-brief territory** — do not assume Render-hosted MCP can directly read Mac Mini filesystem. Solve that before implementing the tool.
- **Lesson #22 applies** — if MCP routes are added, check for existing endpoints (`grep -n "baker_vault" <mcp_server_file>`). FastAPI-style shadows apply to MCP too.

### Verification

```python
# In Cowork session after Phase D deploys:
content = mcp__baker__baker_vault_read(path="_ops/skills/it-manager/SKILL.md")
assert "AI Dennis" in content
assert len(content) < 500_000

listing = mcp__baker__baker_vault_list(path="_ops/agents/ai-dennis/")
# Expected: [{name: "OPERATING.md", ...}, {name: "LONGTERM.md", ...}, {name: "ARCHIVE.md", ...}]

# Path safety tests:
result = mcp__baker__baker_vault_read(path="../../../etc/passwd")
assert result == {"error": "invalid path"}

result = mcp__baker__baker_vault_read(path="/absolute/path")
assert result == {"error": "invalid path"}
```

---

## Fix/Feature 5 (Phase E): CHANDA Invariant 9 refinement + pipeline frontmatter filter

### Problem

CHANDA Invariant 9 says "Mac Mini is the single agent writer to ~/baker-vault" — unqualified. With `_ops/` now in the vault and B-codes writing to it via git, the invariant text conflicts with operational reality. Additionally, the Cortex T3 pipeline has no explicit `ignore_by_pipeline: true` filter — if a Silver poll ever walks `_ops/`, it will try to triage skill files and emit nonsense signals.

### Current State

`CHANDA.md` Section 3, Invariant 9, current text (verified this session):
> "Mac Mini is the single **agent** writer to `~/baker-vault`. Director may edit Gold from any machine; human writes are out-of-band and human-paced. Render writes only to `wiki_staging`."

Pipeline: no `ignore_by_pipeline` filter in `kbl/steps/step1_triage.py` or `kbl/layer0.py` (verified this session — zero matches for the phrase).

### Implementation

Branch: `sot-obsidian-1-phase-e`. Work split across **baker-vault** (CHANDA edit) and **baker-master** (pipeline filter).

**Step 5.1 — Refine CHANDA Inv 9.** Edit `baker-vault/CHANDA.md`:

```markdown
9. Mac Mini is the single **agent** writer to `~/baker-vault/wiki/` (Silver + Gold). Director may edit Gold from any machine; human writes are out-of-band and human-paced. Render writes only to `wiki_staging`. The `_ops/` subtree is carved out from this invariant per [`_ops/processes/writer-contract.md`](_ops/processes/writer-contract.md) — it is outside the learning loop (pipeline skips via `ignore_by_pipeline: true` frontmatter) and admits git-mediated writes from AI Head + B-codes.
```

Director-edit: `author: director` stays on the CHANDA frontmatter. **Tier B authorization required** — Director must say "yes" to the edit per bank model. AI Head drafts + proposes; Director ratifies; AI Head commits on explicit yes per `feedback_chanda_commit_with_authorization.md` pattern.

**Step 5.2 — Add frontmatter filter to pipeline:**

In `baker-master/kbl/steps/step1_triage.py` (or whichever module is Step 1's entry), add at the top of the triage function:

```python
def _should_skip(raw_content: str) -> bool:
    """Return True if the content's frontmatter marks it as ops-only.

    Ops artifacts (skills, briefs, agent memory, process docs) live in
    baker-vault/_ops/ and must NOT be triaged as Silver candidates.
    SOT_OBSIDIAN_UNIFICATION_1 Phase E.
    """
    if not raw_content.startswith("---"):
        return False
    try:
        import yaml
        end = raw_content.find("\n---", 4)
        if end == -1:
            return False
        fm = yaml.safe_load(raw_content[4:end])
        return bool(fm and fm.get("ignore_by_pipeline"))
    except Exception:
        # Malformed frontmatter — safer to process than silently skip
        return False


# In the actual triage entrypoint (whatever function today receives a Signal):
if _should_skip(signal.raw_content):
    logger.info(f"[triage] skipping ops-type signal id={signal.id} per ignore_by_pipeline")
    return TriageResult(verdict="drop", reason="ops-type")
```

**Step 5.3 — Add unit test:**

`tests/test_step1_triage_ops_skip.py`:

- Signal with `---\ntype: ops\nignore_by_pipeline: true\n---\n<content>` → verdict=drop, reason=ops-type
- Signal with `---\ntype: silver\n---\n<content>` → verdict continues normally
- Signal without frontmatter → verdict continues normally
- Signal with malformed frontmatter → verdict continues normally (safer to process than silently skip)

**Step 5.4 — Document the pipeline filter in `_ops/processes/pipeline-filter.md`** (new process doc): what it does, when it fires, how to test.

**Step 5.5 — Update registries:** Add the pipeline-filter process to `_ops/processes/INDEX.md`. Add this brief (SOT_OBSIDIAN_UNIFICATION_1) row to `_ops/briefs/INDEX.md` marked `status: merged` after all phases close.

**Step 5.6 — Commit + push each repo separately:**

```bash
# baker-vault commit
cd ~/baker-vault
git add CHANDA.md _ops/
git commit -m "SOT_OBSIDIAN_UNIFICATION_1 Phase E (vault): CHANDA Inv 9 refinement + process docs

Inv 9 clarified: single-agent-writer rule applies to wiki/ (Silver+Gold)
only. _ops/ is carved out — git-mediated writes from AI Head + B-codes,
outside the learning loop via ignore_by_pipeline frontmatter.

Director-authorized via explicit 'yes' on Tier B CHANDA edit.

Co-Authored-By: Director <director@brisengroup.com>"

# baker-master commit
cd /tmp/bm-draft
git checkout -b sot-obsidian-1-phase-e
# ... pipeline filter edits + test ...
git commit -m "SOT_OBSIDIAN_UNIFICATION_1 Phase E (pipeline): skip ops-type signals via frontmatter

Step 1 triage now respects ignore_by_pipeline: true frontmatter. Files
from baker-vault/_ops/ — skills, briefs, agent memory, process docs —
never enter the Silver/Gold learning loop. Pairs with CHANDA Inv 9
refinement landed in baker-vault at the same timestamp.

Unit test covers: ops-skip, silver-continue, no-frontmatter-continue,
malformed-frontmatter-continue.

Co-Authored-By: Code Brisen <code-brisen@brisengroup.com>"
```

### Key Constraints

- **Inv 9 edit is Tier B.** AI Head drafts; Director authorizes with explicit "yes"; AI Head commits with Director's quote in the commit message. Follow `feedback_chanda_commit_with_authorization.md` pattern (commit `a356e97` is the reference precedent).
- **Pipeline filter must fail open, not closed** (lesson #38 analogue — safer to over-process than to silently drop). Malformed frontmatter = process normally, not skip.
- **No secrets in the filter code.** No env-var reads. Pure function on the signal content.
- **Test matrix must cover all four cases** (ops-skip, silver-continue, no-frontmatter, malformed). Partial coverage = drift risk.

### Verification

```bash
grep -n "ignore_by_pipeline" ~/baker-vault/CHANDA.md
# Expected: one match pointing to writer-contract.md

grep -n "ignore_by_pipeline\|_should_skip" /tmp/bm-draft/kbl/steps/step1_triage.py
# Expected: at least 2 matches (import/use + helper)

cd /tmp/bm-draft && pytest tests/test_step1_triage_ops_skip.py -xvs
# Expected: 4/4 pass

# Sanity check: feed a real _ops/ file through the pipeline in dev mode:
python -c "from kbl.steps.step1_triage import _should_skip; print(_should_skip(open('/Users/dimitry/baker-vault/_ops/INDEX.md').read()))"
# Expected: True
```

---

## Files Modified (across all 5 phases)

**baker-vault repo:**
- `_ops/INDEX.md` — new (Phase A)
- `_ops/skills/INDEX.md` — new (Phase A), populated (Phase B)
- `_ops/skills/it-manager/SKILL.md` — new (Phase B)
- `_ops/briefs/INDEX.md` + `_ops/briefs/TEMPLATE.md` — new (Phase A), populated (Phase C)
- `_ops/briefs/*.md` — 8 migrated + this brief copy (Phase C)
- `_ops/agents/INDEX.md` + `_ops/agents/ai-dennis/{OPERATING,LONGTERM,ARCHIVE}.md` — new (Phase B)
- `_ops/processes/INDEX.md` + `_ops/processes/{write-brief,bank-model,git-mailbox,writer-contract,cowork-equipping,pipeline-filter}.md` — new (Phases A/B/D/E)
- `_install/sync_skills.sh` — new (Phase A skeleton + Phase B real)
- `CHANDA.md` — refined Inv 9 (Phase E, Director-authorized)

**baker-master repo:**
- `kbl/steps/step1_triage.py` (or Layer 0 equivalent) — frontmatter filter (Phase E)
- `tests/test_step1_triage_ops_skip.py` — new unit test (Phase E)
- `<mcp server file>` — `baker_vault_read` + `baker_vault_list` tools (Phase D)
- `briefs/BRIEF_SOT_OBSIDIAN_UNIFICATION_1.md` — this brief (tracked, will be superseded by copy in `_ops/briefs/`)

**Baker-Project/pm/ai-operations/it-manager/** (Dropbox):
- `AI_DENNIS_SKILL.md` → renamed `.retired-2026-04-20` (Phase B)
- `AI_DENNIS_MEMORY.md` → renamed `.retired-2026-04-20` (Phase B; content split already in vault)

**Dropbox/.skills/skills/it-manager/:**
- `SKILL.md` → renamed `.retired-2026-04-20` (Phase B)

**Baker-Project/pm/briefs/:**
- `FROZEN.md` — new (Phase C)

## Do NOT Touch

- `~/baker-vault/wiki/` — CHANDA-owned Silver/Gold territory (except Phase E's own CHANDA.md Inv 9 refinement, which is Director-authorized)
- `~/baker-vault/slugs.yml`, `~/baker-vault/config/`, `~/baker-vault/schema/`, `~/baker-vault/raw/` — unrelated subtrees
- `pm/briefs/_DONE_*.md` files — historical, frozen in place
- Any `author: director` frontmatter in CHANDA or hot.md — **never modify**
- Render service env vars — this brief does not add or change any env
- `baker-master` FastAPI dashboard — not touched
- `baker-master` `kbl/layer0.py` — the filter goes in `step1_triage.py` (earlier entry point), not Layer 0
- Any existing `mcp__baker__*` tool — Phase D ADDS two new tools, never modifies existing

## Quality Checkpoints

1. After Phase A: `_ops/` subtree exists, INDEX files present, writer-contract.md ratified, sync_skills.sh skeleton runs with exit 0.
2. After Phase B: AI Dennis skill is a single symlinked source; three memory files exist per v3 spec; 3 duplicate copies retired with `.retired-*` suffix; write-brief + bank-model + git-mailbox docs readable.
3. After Phase C: `_ops/briefs/` has ≥9 briefs + INDEX + TEMPLATE; `pm/briefs/FROZEN.md` present; no deletion anywhere.
4. After Phase D: Cowork can call `mcp__baker__baker_vault_read` and read skills/agent-memory content. AI Dennis session loads canonical skill via MCP, not local copy.
5. After Phase E: CHANDA Inv 9 refined with Director signature; pipeline filter tested 4/4; real `_ops/INDEX.md` file returns `_should_skip=True`.
6. **All 5 phases:** briefs git-tracked (lesson #16); no code snippets with unverified function signatures (lesson #17); no secrets in any file; no force-push; no destructive deletion before 7-day burn-in.

## Verification SQL

No DB state changes in this brief. One paper-trail query post-merge:

```sql
-- Confirm no signal_queue rows got created from _ops/ files (would indicate
-- pipeline filter miss in Phase E)
SELECT source, COUNT(*) FROM signal_queue
WHERE raw_content LIKE '%ignore_by_pipeline%'
GROUP BY source;
-- Expected: 0 rows
```

## Trust marker (lesson #40 — "what in production would reveal a bug")

**Three failure modes and how we'd spot them:**

1. **Phase B: symlink doesn't point at vault** — Director edits `_ops/skills/it-manager/SKILL.md`, Claude App doesn't see the change at session start. Smoke test: after Phase B, edit one line of the skill, open a fresh Claude App session, observe the change in the loaded skill text.

2. **Phase D: MCP tool leaks outside `_ops/`** — a crafted path returns content from `wiki/` (Silver) or, worse, `/etc/`. Smoke test: after Phase D, call `baker_vault_read(path="../wiki/hot.md")` from Cowork; expect `{error: invalid path}`. Also `baker_vault_read(path="../../../etc/passwd")` → `{error: invalid path}`.

3. **Phase E: pipeline filter misses an ops file** — a skill file gets treated as Silver candidate and surfaces in wiki/_inbox/. Smoke test: after Phase E deploys, copy `_ops/INDEX.md` content into a test signal row in `signal_queue` with `source='test-ops-filter'`; run pipeline tick; expect `status='routed_inbox'` OR the filter's skip-verdict (TBD by step1 terminal semantics) — NEVER `status='completed'` and NEVER a wiki file created from the content.

**The meta-pattern (per lesson #42):** this brief introduces a new filesystem-filter boundary. If we stop at unit tests and don't run the three smoke tests above in production, drift will happen silently — an ops file lands in Silver, a skill edit doesn't propagate, a path-traversal works once. Smoke tests = the gated production-exercising that lesson #42 demands.

## Acceptance criteria (brief-level)

1. All 5 phases ship as separate PRs. Each PR ≤ 3 hours. Each PR reviewed by a different B-code than the implementer.
2. After Phase E merges, `_ops/` subtree is the canonical + single source of truth for skills / briefs / agent memory / process docs. The 3 pre-existing AI Dennis skill copies are either symlinked (runtime) or retired (source).
3. Cowork (via the new MCP tool in Phase D) reads the same skill content as Claude App (via the symlink in Phase B). AI Dennis session produces identical behavior in both surfaces.
4. CHANDA.md Inv 9 text explicitly references the writer-contract carve-out. Director ratifies the edit.
5. No Silver file has ever been created from an `_ops/` signal after Phase E (verified via the SQL query above).
6. Brief itself lives at `~/baker-vault/_ops/briefs/BRIEF_SOT_OBSIDIAN_UNIFICATION_1.md` with `status: merged` by Phase E completion.
7. `tasks/lessons.md` updated with the new patterns learned (see Step 6 below).

## Dispatch plan

- Phase A → B-code (any available)
- Phase B → different B-code, reviewer = phase-A implementer
- Phase C → different B-code
- Phase D → preceded by `SOT_OBSIDIAN_1_PHASE_D_TRANSPORT.md` sub-brief (AI Head-authored) resolving MCP-on-Render vs. Mac-Mini-side-car question
- Phase E → any B-code, reviewer rotates; Director-authorized for CHANDA edit specifically

## Sub-brief gate for Phase D

Phase D cannot start until AI Head authors and Director approves `SOT_OBSIDIAN_1_PHASE_D_TRANSPORT.md` covering: where the MCP server runs, how it reaches Mac Mini's vault content, what the side-car (if any) looks like, and whether Tailscale is the transport. Expected sub-brief length: 300-500 lines. Expected author time: 60-90 min.

## Lessons captured proactively (for `tasks/lessons.md` after Phase E ships)

To be added after implementation; placeholders:

- **Lesson #43 — Skills don't live where you think they do.** Claude App reads from `~/.claude/skills/`. Cowork has no local skill folder; its skill registry is cloud-delivered via extension mounts. Any architecture that "places a file so Cowork sees it" will fail. Cowork equipping = MCP bridge, not filesystem copy.
- **Lesson #44 — Symlink safely or not at all.** The sync script never deletes a non-symlink non-empty directory. When runtime paths hold real data (manual-install residue), skip + log, don't overwrite.
- **Lesson #45 — Frontmatter filters must fail open.** Pipeline skip-decisions based on YAML parse must default to "process normally" on parse error. Silently skipping malformed files = chronic under-processing drift.

---

*Brief ratified 2026-04-20 by Director's approved 5-phase plan.*
*Written under /write-brief protocol steps 1-5. Step 6 (capture lessons) to execute after Phase E merges.*
