# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-20 (midday, post-SOT brief ratification)
**Status:** OPEN — SOT_OBSIDIAN_UNIFICATION_1 Phase A

---

## Task: SOT_OBSIDIAN_UNIFICATION_1 — Phase A (scaffold `_ops/` + INDEX files + writer-contract + sync skeleton)

Brief: `briefs/BRIEF_SOT_OBSIDIAN_UNIFICATION_1.md` at commit `4596383` (in baker-master repo). Read the whole brief end-to-end before starting — all five phases. You're executing **Phase A only**.

**Target PR:** against `baker-vault` (NOT baker-master). Branch: `sot-obsidian-1-phase-a`. Base: `main`. Reviewer: B2.

### New working directory

You've been working in `~/bm-b1/` (baker-master clone). Phase A is in the `baker-vault` repo. One-time setup:

```bash
cd ~
[ -d bv-b1 ] || git clone https://github.com/vallen300-bit/baker-vault.git bv-b1
cd bv-b1
git checkout main && git pull --ff-only origin main
git checkout -b sot-obsidian-1-phase-a
```

Going forward your SOT-phase work happens in `~/bv-b1/`, not `~/bm-b1/`.

### Scope (exact steps from brief §Fix/Feature 1)

Follow brief steps **1.1 through 1.9** verbatim. Summary:

1. **1.1** — `mkdir -p _ops/skills _ops/briefs _ops/agents _ops/processes _install`
2. **1.2** — Create `_ops/INDEX.md` with frontmatter (brief has full content)
3. **1.3** — Create `_ops/skills/INDEX.md` (empty skill registry, populated in Phase B)
4. **1.4** — Create `_ops/briefs/INDEX.md` + `_ops/briefs/TEMPLATE.md`
5. **1.5** — Create `_ops/agents/INDEX.md` (AI Dennis row only)
6. **1.6** — Create `_ops/processes/INDEX.md` (pointer list)
7. **1.7** — Create `_ops/processes/writer-contract.md` (the `_ops/` carve-out doc — brief has full text)
8. **1.8** — Create `_install/sync_skills.sh` (skeleton only — Phase B wires it up)
9. **1.9** — Commit + push

For `_ops/briefs/TEMPLATE.md`: copy the contents of `~/.claude/skills/write-brief/SKILL.md` verbatim (the `/write-brief` protocol text). That's the authoritative brief-writing process. Add frontmatter:

```yaml
---
type: ops
ignore_by_pipeline: true
purpose: Template and protocol for authoring Baker implementation briefs
source: ~/.claude/skills/write-brief/SKILL.md
last_synced: 2026-04-20
---
```

### Hard constraints (from brief §Key Constraints)

- **DO NOT** touch `wiki/` in this phase. Purely additive.
- **DO NOT** modify `CHANDA.md` — that's Phase E, Director-authorized.
- **DO NOT** execute `sync_skills.sh` against `~/.claude/skills/` — skeleton only in Phase A.
- **DO NOT** migrate any real skill, brief, or agent content — that's Phase B+C.
- **All 6 markdown files must have the frontmatter** `type: ops` + `ignore_by_pipeline: true`.

### Acceptance criteria (from brief §Verification)

Before pushing, verify:

```bash
ls ~/bv-b1/_ops/
# skills/ briefs/ agents/ processes/ INDEX.md

ls ~/bv-b1/_ops/skills/INDEX.md \
   ~/bv-b1/_ops/briefs/INDEX.md \
   ~/bv-b1/_ops/briefs/TEMPLATE.md \
   ~/bv-b1/_ops/agents/INDEX.md \
   ~/bv-b1/_ops/processes/INDEX.md \
   ~/bv-b1/_ops/processes/writer-contract.md
# All 6 exist.

head -5 ~/bv-b1/_ops/INDEX.md
# Frontmatter must include type: ops AND ignore_by_pipeline: true.

bash ~/bv-b1/_install/sync_skills.sh
# Expected output: Phase A skeleton message, exit 0. No actual sync.

chmod -c +x ~/bv-b1/_install/sync_skills.sh
# Ensure executable.
```

### Commit + PR

Commit message from brief step 1.9 (use it verbatim or close):

```
SOT_OBSIDIAN_UNIFICATION_1 Phase A: scaffold _ops/ + _install/ + writer-contract

Creates canonical home for operational artifacts (skills, briefs, agent
memory, process docs) in ~/baker-vault/_ops/. Frontmatter flag
ignore_by_pipeline=true keeps these files invisible to Cortex T3 learning
loop (wiki/ is Silver/Gold territory).

Registries seeded but empty; population lands in Phases B-E.

Writer-contract.md documents the _ops/ carve-out from CHANDA Inv 9.
CHANDA.md itself to be updated in Phase E with formal reference.

Director-authorized 2026-04-20 via 5-phase plan approval.

Co-Authored-By: Code Brisen 1 <code-brisen-1@brisengroup.com>
```

Open PR against `vallen300-bit/baker-vault` main. Title: `SOT_OBSIDIAN_UNIFICATION_1 Phase A: scaffold _ops/ + writer-contract`.

Ping B2 for review when CI green (note: baker-vault may have no CI pipeline — that's fine, manual review only).

### Trust marker (from brief §Trust marker)

**What in production would reveal a bug:** after this phase, `_ops/` is empty-but-present. No functional change to Baker. The only way this phase "breaks" is structural: missing INDEX, malformed frontmatter, or sync script that crashes on execute. All three are covered by the verification block above.

Expected time: 45-60 min. Read brief first; don't skip.
