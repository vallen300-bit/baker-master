# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-20 (afternoon, post-bridge-merge + post-Phase-B-merge)
**Status:** OPEN — SOT_OBSIDIAN_UNIFICATION_1 Phase C

---

## Task: Phase C — migrate `Baker-Project/pm/briefs/` → `_ops/briefs/`

Gate cleared: Phase B merged at baker-vault `778e704`. Runtime symlink flip for AI Dennis completed (AI Head, Tier B, logged). Phase A + B subtree now populated and live-linked.

**Brief:** `briefs/BRIEF_SOT_OBSIDIAN_UNIFICATION_1.md` at commit `4596383` in baker-master — read §Fix/Feature 3 (Phase C) end-to-end before starting.

---

## Scope summary (full detail in brief §3)

- Freeze `/Users/dimitry/Vallen Dropbox/Dimitry vallen/Baker-Project/pm/briefs/` as historical (add FROZEN.md banner — do NOT delete any files).
- Migrate 8 active non-`_DONE_*` briefs → `_ops/briefs/<name>.md` in baker-vault with proper frontmatter (writer-contract per Phase A).
- Populate `_ops/briefs/INDEX.md` registry. Include:
  - The 8 migrated briefs
  - This session's 4 shipped briefs (SOT Phase A + B commit refs, bridge brief, helper v2 brief).
  - Plus the bridge brief itself + SOT brief.
- Copy `BRIEF_SOT_OBSIDIAN_UNIFICATION_1.md` to `_ops/briefs/` (chicken-and-egg resolved — brief self-references once in vault).
- Document new brief dispatch path in `_ops/processes/git-mailbox.md`: B-codes now pull baker-vault in addition to baker-master for new briefs.

**Copy-forward only. No deletions.** Lesson #16 applies — every migrated brief must land in git at destination before Dropbox-side is archived.

## Target

- **Repo:** baker-vault
- **Branch:** `sot-obsidian-1-phase-c`
- **Base:** `main` at `778e704` (post-Phase-B)
- **Reviewer:** B2

Report your ship to `_reports/B3_sot_phase_c_ship_<YYYYMMDD>.md` in baker-vault. B2 reviews per normal flow. AI Head auto-merges on APPROVE per Tier A.

## After this

Phase D is next (MCP bridge `baker_vault_read` to equip Cowork-side AI Dennis). AI Head will author a separate transport sub-brief (`SOT_OBSIDIAN_1_PHASE_D_TRANSPORT.md`) first. Phase E (CHANDA Inv 9 refinement + pipeline frontmatter filter) follows — CHANDA edit is Tier B, Director's explicit yes required.

You're not on Phase D implementation yet — that routes TBD once transport is decided. You'll get a fresh dispatch when it's time.

Close tab after ship.
