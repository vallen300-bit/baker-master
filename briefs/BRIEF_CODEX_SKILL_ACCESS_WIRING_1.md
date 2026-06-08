# BRIEF — CODEX_SKILL_ACCESS_WIRING_1

**Task class:** agent-infra wiring (docs + bootstrap + git hook). No baker-master runtime code.
**Complexity:** Low-Medium
**Priority:** tier-b
**Owner / report to:** dispatched by `cowork-ah1`; report on the bus to `lead` (b-code bus-only-to-lead rule) and reference this brief id.

### Surface contract: N/A — no rendered UI surface; this is agent-bootstrap + git-hook + doc wiring.

## Context
Codex agents (codex-arch / codex / deputy-codex) run the OpenAI Codex harness — they have **no Claude-Code skill registry**, so a dispatch saying "call `html-triage`" is meaningless to them; they can only READ a `SKILL.md` file and follow it. This surfaced live on the NVIDIA MO dashboard dispatch: codex-arch couldn't find `html-triage` as a skill.

Immediate fix already shipped by cowork-ah1 (vault commit `e04eeb4`):
- `~/baker-vault/_ops/skills/SKILLS_INDEX.md` — machine-generated catalog: 186 skills, each row = slug + absolute `SKILL.md` path + one-line description, with a header stating the "skills are FILE PATHS — read-and-follow, never call" rule.
- `~/baker-vault/_ops/skills/gen_skills_index.py` — the generator (stdlib only, no deps).

Your job: make this **durable + self-maintaining + auto-loaded** by every Codex lane, and document the dispatch convention.

## Files to modify
1. `~/baker-vault/_ops/skills/gen_skills_index.py` — add a `--check` mode.
2. `~/baker-vault/.githooks/pre-commit` — wire the refresh/staleness guard.
3. `~/.codex/AGENTS.md` (global Codex bootstrap — covers ALL Codex lanes).
4. `~/baker-vault/_ops/agents/codex-arch/AGENTS.md` (canonical mirror) + `~/bm-codex-arch/AGENTS.md` (live picker — keep the two byte-identical, per the file's own mirror note).
5. `~/baker-vault/_ops/processes/cross-agent-knowledge-dispatch.md` — add the dispatch convention.

## Files NOT to touch
- The 186 `SKILL.md` files themselves.
- `briefs/_tasks/CODE_3_PENDING.md` and anything under lead's dashboard-wave orchestration.
- baker-master application code (`outputs/`, `orchestrator/`, `kbl/`, etc.).

## Implementation

### Task 1 — generator `--check` mode (`gen_skills_index.py`)
Add an argparse (or `sys.argv`) `--check` flag: regenerate the index **in memory** and compare to the on-disk `SKILLS_INDEX.md`. If identical → print `SKILLS_INDEX up to date` and exit 0. If different → print a short diff summary (counts + first differing slug) and exit 1. Default (no flag) keeps current behaviour: write the file. Keep it dependency-free (stdlib only). Do NOT change the output format — the index is already committed and consumed.

### Task 2 — staleness guard in baker-vault `pre-commit`
In `~/baker-vault/.githooks/pre-commit` (the active hook — confirm via `git -C ~/baker-vault config core.hooksPath`), add a guard that runs ONLY when the commit's staged files include any `_ops/skills/*/SKILL.md` (added/modified/deleted) OR `_ops/skills/gen_skills_index.py`:
- run `python3 _ops/skills/gen_skills_index.py --check`;
- if it exits non-zero, **regenerate** (`python3 _ops/skills/gen_skills_index.py`), `git add _ops/skills/SKILLS_INDEX.md`, and let the commit proceed with the refreshed index — OR (cleaner, your call) block the commit with a message telling the committer to regenerate + re-stage. Pick the **block-and-tell** path if auto-add risks surprising the committer; match whatever pattern the existing guards in this hook use (read them first — `brief_sop_check.sh`, `state_reconciler_pre_commit.sh`). Fail loud, never silently skip.
- Wrap so a missing `python3` or generator error does NOT hard-break unrelated commits — print a clear warning and exit per the hook's existing convention.

### Task 3 — auto-load into Codex bootstraps
**Global (`~/.codex/AGENTS.md`)** — add a short standing block (covers codex-arch, codex, deputy-codex in one place):
> ## Brisen skills are FILES, not registry calls
> You have no Claude-Code skill registry. To use any Brisen "skill", READ its `SKILL.md` and FOLLOW it — never try to "invoke"/"call" it. The full catalog (≈186 skills, slug → absolute path → description) is `~/baker-vault/_ops/skills/SKILLS_INDEX.md`. Grep it by keyword to find a skill; open the path it gives. Regenerate via `python3 ~/baker-vault/_ops/skills/gen_skills_index.py`.

**codex-arch (`_ops/agents/codex-arch/AGENTS.md` + live `~/bm-codex-arch/AGENTS.md`)** — add `~/baker-vault/_ops/skills/SKILLS_INDEX.md` as item 3 in the "Session-start orientation" numbered list (after the build INDEX reads), with a half-line: "the skill catalog — skills are files you read, not registry calls." Keep both copies byte-identical (the file's top comment requires the mirror).

### Task 4 — dispatch convention doc
In `~/baker-vault/_ops/processes/cross-agent-knowledge-dispatch.md`, add a short subsection "Dispatching skill-driven work to Codex / non-Claude-Code harnesses": when the target is a Codex lane, cite every skill as its **absolute `SKILL.md` path** + "read and follow", never a bare skill name + "call"; point them at `SKILLS_INDEX.md`. One paragraph + a one-line good/bad example.

## Verification (literal output in your ship report — not "by inspection")
1. `cd ~/baker-vault && python3 _ops/skills/gen_skills_index.py --check` → exits 0, prints "up to date".
2. Touch a throwaway: temporarily append a space to any `SKILL.md`, `--check` → exits 1 with diff summary; revert.
3. `git -C ~/baker-vault config core.hooksPath` → confirm it points at `.githooks`; show the added guard lines.
4. Simulate the hook path: stage a trivial `SKILL.md` edit in a scratch branch, attempt commit, show the guard firing (then discard).
5. `grep -n "SKILLS_INDEX" ~/.codex/AGENTS.md ~/baker-vault/_ops/agents/codex-arch/AGENTS.md ~/bm-codex-arch/AGENTS.md` → all three reference the index.
6. `diff ~/baker-vault/_ops/agents/codex-arch/AGENTS.md ~/bm-codex-arch/AGENTS.md` → identical (no output).
7. `grep -n "read and follow" ~/baker-vault/_ops/processes/cross-agent-knowledge-dispatch.md` → convention present.

## Constraints
- Additive edits to AGENTS.md / docs — don't remove or reorder existing content.
- Generator stays stdlib-only.
- baker-vault commits: coordinate single-threaded git per the shared-dir rule; this brief's commits are vault-side — bus `lead`/`cowork-ah1` before pushing if either is mid-commit.
- Fail loud: if any verification step can't pass, report it RED, don't paper over it.
