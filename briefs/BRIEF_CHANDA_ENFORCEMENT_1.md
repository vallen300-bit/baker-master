# BRIEF: CHANDA_ENFORCEMENT_1 — Create CHANDA_enforcement.md (invariant matrix + severity tiers)

## Context

CHANDA.md today mixes directional missions with aspirational invariants. Invariants are honor-system audits at pre-push — no mechanical detection, no severity tiering. Research Agent ratified a 2-file split (2026-04-21, Director "yes"): directional content stays in CHANDA.md; operational enforcement (invariants + detectors + severity tiers + amendment log) moves to a new `CHANDA_enforcement.md`.

This brief lands the enforcement file **only**. The paired CHANDA.md rewrite is a separate brief (Research's `2026-04-21-chanda-plain-english-rewrite.md`) and is NOT in scope here.

Source artifact (verbatim content to insert, §1–§7): `/Users/dimitry/baker-vault/_ops/ideas/2026-04-21-chanda-engineering-matrix.md` lines 37–110.

## Estimated time: ~15 min
## Complexity: Low
## Prerequisites: none (standalone insert; paired CHANDA.md rewrite sequences after)

---

## Fix/Feature 1: Create CHANDA_enforcement.md

### Problem
CHANDA.md invariants are flat (no severity tiering), untestable (no detectors), and unenforced (honor-system audit). Research's engineering matrix (ratified 2026-04-21) breaks them into 11 KBL + 5 Surface invariants with 3 severity tiers and mechanical detectors. That content needs a canonical home.

### Current State
- `CHANDA.md` exists at `/15_Baker_Master/01_build/CHANDA.md` (101 lines) — contains missions + 10 flat invariants today
- `CHANDA_enforcement.md` — **does not exist**
- `invariant_checks/` dir — **does not exist** (follow-on detector briefs create it; not this brief)
- Source content: `/Users/dimitry/baker-vault/_ops/ideas/2026-04-21-chanda-engineering-matrix.md` §1–§7 (lines 37–110 of that artifact)

### Implementation

**Step 1 — Create the file** at this absolute path:

```
/Users/dimitry/Vallen Dropbox/Dimitry vallen/Baker-Project/15_Baker_Master/01_build/CHANDA_enforcement.md
```

**Step 2 — Content.** Copy verbatim from Research's engineering-matrix artifact, §1 through §7 (source lines 37–110 of `/Users/dimitry/baker-vault/_ops/ideas/2026-04-21-chanda-engineering-matrix.md`). Exact file body below. No modifications, no re-wording, no additions.

```markdown
# CHANDA Enforcement — engineering matrix

## §1. Purpose & audience

> This file is the operational complement to CHANDA.md. It translates the 5 missions into testable invariants with severity tiers and mechanical detectors. Every agent whose actions can trigger an invariant must read this at session start: Code agents (commit-time rules), runtime pipeline (loop-mechanics rules), surface handlers (user-facing safety rules). Research-agents may skip.

## §2. Severity tiers

| Tier | Behavior on breach | Audience |
|---|---|---|
| **critical** | Halt the operation; explicit unblock required | Director + AI Head, immediate |
| **warn** | Operation continues; breach surfaced in end-of-session report | Director end-of-session |
| **policy** | No runtime check; enforced at PR review | Code reviewer / AI Head |

Breach response is per-tier, not per-invariant. Predictable.

## §3. Detection methods

1. **Static check** (pre-commit hook, CI) — fails the PR. Best for file-structure invariants.
2. **Runtime assertion** — fails the operation. Best for pipeline-loop invariants.
3. **Infra-level enforcement** (credentials, permissions) — physically impossible to breach. Best for writer-isolation.
4. **Monitor + alert** (post-hoc) — detects after the fact. Best for rate/quota.
5. **PR review checklist** — human gate, last resort for genuinely architectural rules.

## §4. KBL invariants (11 rows)

| # | Invariant | Tier | Method | Detector |
|---|---|---|---|---|
| 1 | Gold read before Silver compile | critical | runtime assert | `assert gold_loaded == True` before compile |
| 1b | Cold-start (zero Gold) handling | critical | runtime gate | if `gold_count < N` → flag confidence-lowered; continue. N deferred. |
| 2 | Ledger write atomic with Director action | critical | runtime DB txn | wrap ratify + ledger in same transaction |
| 3 | Step 1 reads hot.md AND ledger every run | critical | runtime assert | log both file opens; verify at pipeline end |
| 4 | `author: director` files untouched by agents | critical | pre-commit hook | scan diff for frontmatter `author: director`; reject |
| 5 | Every wiki file has frontmatter | warn | static scan | quarantine un-frontmattered files; warn, don't halt |
| 6 | Pipeline never skips Step 6 (Cross-link) | critical | runtime assert | Step 6 counter check at pipeline end |
| 7 | Automated alerts are suggestions, never overrides | policy | architectural | alerts enter a queue; PR review checks no actuator path |
| 8 | Silver → Gold only by Director frontmatter edit | critical | runtime + git | pipeline refuses to write `voice: gold`; commit signer verified |
| 9 | Mac Mini single writer | critical | infra-level | Render has no push credentials for main vault repo |
| 10 | Pipeline prompts do not self-modify | policy | file permissions | prompt files read-only at runtime |

**Total:** 11 rows. 9 critical, 1 warn, 2 policy.
**Note on #5:** deliberately downgraded from original CHANDA (was critical) to avoid brittle-tripwire failure mode — one stale file with missing frontmatter should not halt the pipeline.

## §5. Surface invariants (5 rows — NEW)

| # | Invariant | Tier | Method |
|---|---|---|---|
| S1 | Baker never auto-sends to external recipients (drafts only) | critical | runtime: external flag on recipient → force draft mode |
| S2 | Every write to external systems logs to `baker_actions` atomically | critical | runtime DB txn |
| S3 | Kill switches respected (`BAKER_*_READONLY` env vars) | critical | runtime assertion at write-path entry |
| S4 | Rate caps enforced (max 10 writes/cycle/integration) | critical | runtime counter |
| S5 | Scan responses cite sources; no hallucinated citations | warn | post-response validator: grep citations against source IDs |

**Total:** 5 rows. 4 critical, 1 warn.

## §6. Detector script pointers

Detectors live under `/15_Baker_Master/01_build/invariant_checks/`.

**First build — top-3 critical (Director-approved 2026-04-21):**

| Invariant | Detector script | Method | Integration point |
|---|---|---|---|
| #2 Ledger atomicity | `invariant_checks/ledger_atomic.py` | runtime DB txn wrapper | all Director-action handlers |
| #4 Author:director files | `invariant_checks/author_director_guard.sh` | pre-commit hook | git hook + CI |
| #9 Mac Mini single writer | *(infra config — no script)* | Render deploy manifest: no push creds | Render dashboard + deploy YAML |

Remaining 13 detectors (KBL 1, 1b, 3, 5, 6, 7, 8, 10 + S1–S5) deferred to subsequent briefs after top-3 ship stably for 30 days.

## §7. Amendment log

Append-only. Every change to this file gets a row. Director signs via commit.

| Date | Section | Change | Director auth |
|---|---|---|---|
| 2026-04-21 | all | Initial creation from CHANDA rewrite session | "yes" (2026-04-21) |
```

**That is the entire content of the file.** Do not add a §8 or anything beyond §7.

### Key Constraints

- **File name:** exactly `CHANDA_enforcement.md` (underscore, not hyphen). Case-sensitive.
- **Location:** `/15_Baker_Master/01_build/` — same directory as `CHANDA.md`.
- **Content:** verbatim §1–§7 from source artifact. No rewording, no additions, no reordering.
- **Frontmatter:** **none**. Source artifact has frontmatter (`type: architecture` etc.) because it's a research-agent idea file. The production file does NOT carry that frontmatter — it's a human-authored canonical doc, not a pipeline-ingestible artifact.
- **DO NOT** touch `CHANDA.md` (paired rewrite is its own brief, `CHANDA_PLAIN_ENGLISH_REWRITE_1`, sequences next).
- **DO NOT** create `invariant_checks/` dir or any detector scripts (follow-on briefs: `AUTHOR_DIRECTOR_GUARD_1`, `LEDGER_ATOMIC_1`, `MAC_MINI_WRITER_AUDIT_1`).
- **DO NOT** edit CLAUDE.md, MEMORY.md, or any other file.

### Verification

**Source of truth:** the code block above in the **Implementation → Step 2** section of this brief is the exact, byte-perfect content of the production file. Copy that block verbatim into the target file (including the H1 title `# CHANDA Enforcement — engineering matrix` at the top, no frontmatter above it).

1. `ls -la /Users/dimitry/Vallen\ Dropbox/Dimitry\ vallen/Baker-Project/15_Baker_Master/01_build/CHANDA_enforcement.md` — file exists.
2. `head -1 CHANDA_enforcement.md` — returns exactly `# CHANDA Enforcement — engineering matrix` (no leading frontmatter, no BOM).
3. `grep -c '^## §' CHANDA_enforcement.md` — returns `7` (seven section headings §1 through §7).
4. `tail -1 CHANDA_enforcement.md` — returns the amendment log row: `| 2026-04-21 | all | Initial creation from CHANDA rewrite session | "yes" (2026-04-21) |`
5. `grep -c '^| ' CHANDA_enforcement.md` — returns `22` (3 severity-tier rows + 1 header + 11 KBL invariants + 1 header + 5 Surface invariants + 1 header + 3 detector rows + 1 header + 1 amendment row + table separator rows — if the count is off by a small number that's fine; the exact number is not load-bearing, only approximate).
6. `wc -l CHANDA_enforcement.md` — expect ~75 lines (±5).
7. No other files modified: `git status --short` should show only `?? 15_Baker_Master/01_build/CHANDA_enforcement.md` (and the staged brief + CODE_1_PENDING.md if those are still uncommitted).
8. Grep for "§8" in CHANDA_enforcement.md — returns zero matches (file must end at §7).

---

## Files Modified

- `/15_Baker_Master/01_build/CHANDA_enforcement.md` — **NEW** (pure insert)

## Do NOT Touch

- `/15_Baker_Master/01_build/CHANDA.md` — paired rewrite is `CHANDA_PLAIN_ENGLISH_REWRITE_1`, not this brief.
- `/15_Baker_Master/01_build/invariant_checks/` — directory does not exist; follow-on detector briefs create it.
- `CLAUDE.md`, `MEMORY.md`, `tasks/lessons.md` — unrelated.
- Any Python file — this brief is markdown-only.

## Quality Checkpoints

1. File created at exact path above.
2. Content byte-identical to source artifact lines 37–110 (verify via `diff`).
3. No frontmatter prepended.
4. No trailing §8 or footer added.
5. `git status` shows only one new file.
6. Commit message follows repo convention (see recent: `chanda(§…)` or `create(chanda_enforcement)` style).
7. No CI checks triggered (markdown-only, no test suite involvement).

## Verification SQL

N/A — no DB changes.

## Rollback

`git revert <commit>` — single-commit, single-file, clean revert.
