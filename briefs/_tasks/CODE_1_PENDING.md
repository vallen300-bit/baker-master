---
status: pending
brief: briefs/BRIEF_RESEARCHER_VERIFY_CITATIONS_1.md
brief_id: RESEARCHER_VERIFY_CITATIONS_1
target_repo: baker-vault (skill file + symlink target) — no baker-master writes, no brisen-lab writes
matter_slug: baker-internal
dispatched_at: 2026-05-23T12:00:00Z
dispatched_by: lead
target: b1
working_branch: b1/researcher-verify-citations-1
reply_to: lead
deadline: 2026-05-24T18:00:00Z
priority: tier-b
---

# CODE_1_PENDING — RESEARCHER_VERIFY_CITATIONS_1 — 2026-05-23

**Brief:** `briefs/BRIEF_RESEARCHER_VERIFY_CITATIONS_1.md` (full text in baker-master `main` @ `cf43ee3`; pull before reading)
**Working branch:** `b1/researcher-verify-citations-1` (cut from baker-vault `main`)
**Repo:** baker-vault ONLY (skill at `_ops/skills/researcher-verify-citations/SKILL.md` + symlink into `~/bm-researcher/.claude/skills/`)
**Pre-requisites:** Phase 1 docs already landed in baker-vault `b15cf7a` (researcher `method.md` + `orientation.md` updated with Step 0 Shape Selector + Step 6.5 verify gate + §8 citation slot template + Baker-first people lookup rule).

## Bottom line

Build the `researcher-verify-citations` skill per the brief's full SKILL.md spec (lines 60-277 of the brief). Phase 2 of the 4-component researcher fine-tuning arc. ~3-4h. No baker-master changes.

## Acceptance criteria (full list — brief Quality Checkpoints 1-13)

1. `~/baker-vault/_ops/skills/researcher-verify-citations/SKILL.md` exists at canonical path.
2. Symlink `~/bm-researcher/.claude/skills/researcher-verify-citations` resolves to the canonical path (`readlink` returns `/Users/dimitry/baker-vault/_ops/skills/researcher-verify-citations`).
3. Frontmatter `name: researcher-verify-citations` matches directory name.
4. Frontmatter has `MANDATORY TRIGGERS` line per existing skill convention (mirror `grok-via-xai-api`).
5. Three-way verdict taxonomy + paywall subtype present (`PASS` / `FAIL_MISMATCH` / `UNCERTAIN_UNVERIFIABLE` / `UNCERTAIN_POSSIBLE_WALL`).
6. Strict date priority rule explicit + ordered (`datePublished` > `article:published_time` > visible header > STOP).
7. `dateModified` explicitly excluded from PASS.
8. WebFetch < 1500 chars → mandatory Chrome MCP escalation (not optional).
9. Per-URL 30s timeout + 5-min batch ceiling + explicit `Checked: YES/NO` column all present.
10. Output format matches the markdown table shape in brief lines 209-216.
11. Chrome MCP namespace detection step (`mcp__chrome__*` vs `mcp__Claude_in_Chrome__*`) explicit.
12. Skill does NOT write to vault, call other skills, or invoke Baker write tools.
13. Skill file committed to baker-vault repo (NOT baker-master).

## Ship gate

- Literal `grep` verification of all 4 hard constraints (brief lines 291-315): paste output in ship report.
- `readlink ~/bm-researcher/.claude/skills/researcher-verify-citations` returns canonical path: paste output.
- `head -5 ~/baker-vault/_ops/skills/researcher-verify-citations/SKILL.md` shows correct `name:` frontmatter: paste output.

## Reporting

- Ship PR against baker-vault `main` from branch `b1/researcher-verify-citations-1`.
- **Bus-post `lead` on PR open** with topic `ship/researcher-verify-citations-1` (per brief-reply-to-sender rule — `dispatched_by: lead` ⇒ ship-report to `lead`).
- Do NOT touch baker-master or brisen-lab in this brief.

## Out of scope (Do NOT touch)

- `_ops/agents/researcher/method.md` — Phase 1 doc lane, already landed.
- `_ops/agents/researcher/orientation.md` — Phase 1 doc lane, already landed.
- Other researcher skills (`grok-via-xai-api`, `ui-surface-prebrief`, `whatsapp-send-via-waha`).
- Baker MCP code or schema.
- Researcher CLAUDE.md.
