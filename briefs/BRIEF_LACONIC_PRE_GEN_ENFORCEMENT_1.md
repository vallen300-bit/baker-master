# BRIEF: LACONIC_PRE_GEN_ENFORCEMENT_1 — Inject laconic register into every Director-facing prompt before the model generates

## Context
Director ratified the laconic register 2026-05-25 (Rule 6) as the default for all
Director-facing replies. Adoption failed: agents skip the skill at session start;
Stop hooks (which fire AFTER generation) only create wasteful rewrite cycles.

Director directive 2026-05-26 (this session): *"Hooks exist to give agents
instruction on what NOT to say. Hooks that promote what to say. I don't see how
it will work. ... Is there any other method?"* → ratified pre-generation
context injection as the productive lever; ship for all Director-facing agents.

### Surface contract: N/A — pure harness/config work. No clickable UI, no dashboard surface, no external endpoint. Files touched: shell hook script + JSON settings + role-context markdown symlinks. Validated by hook smoke-tests (Quality Checkpoint #2-4).

## Estimated time: 2-3h (AH1 direct, no B-code)
## Complexity: Low — config + 1 hook script + per-picker symlink fanout
## Prerequisites: existing `session-start-role.sh` + `pre-send-checklist.sh` patterns

---

## Fix 1: Canonical laconic role-context

### Problem
SessionStart hook `session-start-role.sh` already injects
`<repo>/.claude/role-context/<role>.md` into the session context — but no such
file exists for any Director-facing role today.

### Implementation
Create canonical at `~/baker-vault/_ops/role-contexts/laconic-default.md` —
single source of truth. Carries the 5-block envelope, banned phrases, override
phrases, recommendation discipline, anchors.

### Files modified
- NEW: `~/baker-vault/_ops/role-contexts/laconic-default.md`

---

## Fix 2: UserPromptSubmit hook — `laconic-reminder.sh`

### Problem
SessionStart injection rolls out of the context window over a long session.
Need a per-prompt nudge that fires BEFORE the model generates each reply.

### Implementation
New hook at `~/baker-vault/_ops/hooks/laconic-reminder.sh` (symlinked into
`~/.claude/hooks/`). Mechanism: emit `hookSpecificOutput` JSON with
`additionalContext` containing the 6-rule reminder; Claude Code injects it
into the prompt's context window before generation.

Allowlist (Director-facing only):
`lead, aihead1, aihead2, cowork-ah1, cowork-ah2, aid, ben, hag-desk,
hagenauer-desk, ao-desk, baden-baden-desk, brisen-desk, movie-desk,
origination-desk, researcher`

Exempt (technical lane): `b1-b5, CM-1..4, hag-filer, architect, cortex`

Release phrases (skip injection this turn): `normal style`, `regular style`,
`/laconic off`, `longer style`, `stop laconic`.

### Files modified
- NEW: `~/baker-vault/_ops/hooks/laconic-reminder.sh`
- NEW: `~/.claude/hooks/laconic-reminder.sh` (symlink to canonical)
- MOD: `~/.claude/settings.json` — append to `UserPromptSubmit` chain

---

## Fix 3: Per-picker role-context fanout

### Problem
SessionStart hook reads `<picker>/.claude/role-context/<role>.md`. Need the
canonical content to be readable from every Director-facing picker, under
every plausible role slug (BAKER_ROLE env-var form AND cwd-fallback form).

### Implementation
For each Director-facing picker, `mkdir -p .claude/role-context/` and create
symlinks `<role>.md → ~/baker-vault/_ops/role-contexts/laconic-default.md` for
each role slug that picker might resolve to.

Coverage installed (24 symlinks, 17 pickers):
- Local: `~/bm-aihead1` (lead, aihead1), `~/bm-aihead1-cowork` (cowork-ah1),
  `~/bm-aihead2` (aihead2, deputy), `~/bm-aid` (aid), `~/bm-ben` (ben),
  `~/bm-hag-desk` (hag-desk, hagenauer-desk), `~/bm-researcher` (researcher).
- Dropbox-synced (Cowork app): `bm-aihead1`, `bm-aihead2`, `bm-aidennis-t`,
  `bm-ao-desk`, `bm-baden-baden-desk`, `bm-ben`, `bm-brisen-desk`,
  `bm-hagenauer-desk`, `bm-movie-desk`, `bm-origination-desk`.

### Key constraint
Single source of truth: any edit to canonical instantly propagates across all
pickers. No drift risk.

---

## Files Modified
- NEW canonical: `~/baker-vault/_ops/role-contexts/laconic-default.md`
- NEW canonical: `~/baker-vault/_ops/hooks/laconic-reminder.sh`
- NEW symlink: `~/.claude/hooks/laconic-reminder.sh`
- MOD: `~/.claude/settings.json` (UserPromptSubmit chain appended)
- NEW: 24 symlinks across 17 picker `.claude/role-context/` dirs

## Do NOT Touch
- Existing Stop hooks (recommendation-check, contract-gate, etc.) — kept as
  catastrophic backstop only; not the primary control.
- Existing UserPromptSubmit hooks (strategic-mode-router,
  authority-profile-preload, pre-send-checklist, annotate-pending-checker) —
  preserved; the laconic reminder appends, does not replace.
- B-code role-context dirs (b1-b4) — technical lane exempt.
- Architect picker — agent-facing, not Director-facing.

## Quality Checkpoints
1. Hook is executable: `ls -la ~/.claude/hooks/laconic-reminder.sh` ✓
2. Director-facing smoke: `echo '{"user_message":"x"}' | BAKER_ROLE=lead bash ~/.claude/hooks/laconic-reminder.sh` → 547-char additionalContext JSON ✓
3. Technical-lane smoke: same with `BAKER_ROLE=b2` → empty (exempt) ✓
4. Release-phrase smoke: same with `user_message="normal style please"` → empty (release respected) ✓
5. New session in any Director-facing picker — visible reminder in additionalContext for that prompt.
6. New session in B-code picker — NO reminder (technical lane preserved).

## Anchors
- Director ratification 2026-05-25 (Rule 6, laconic default register)
- Director ratification 2026-05-26 (this brief — pre-gen over stop-hook)
- Canonical SKILL: `~/.claude/skills/laconic/SKILL.md`
- Canonical role-context: `~/baker-vault/_ops/role-contexts/laconic-default.md`
- Canonical hook: `~/baker-vault/_ops/hooks/laconic-reminder.sh`
- Wiring: `~/.claude/settings.json`
