# B4 ship report — CONTEXT_TRIM_AUDIT_1

dispatch: bus #2732 (lead, 2026-06-10) | reply-to: lead | Harness-V2: N/A — docs/memory maintenance, no prod code

## Phase 1 — EXECUTED: lead auto-memory index trim

Target: `~/.claude/projects/-Users-dimitry-bm-aihead1/memory/MEMORY.md` ≤8KB, zero lost facts.

**Result: 19,797 B → 7,944 B (~5.3k → ~2.1k tokens/session).** AC met.

What was done:
1. Every entry compressed to one line (title-link + ≤15-word hook), regrouped under 8 headers (NEXT SESSION PREP / HANDOVER / FLEET ROUTING / AID DISCIPLINE / VERIFICATION / DIRECTOR-FACING REGISTER / BUS MECHANICS / OPS REFERENCE / MATTER+PEOPLE).
2. Detail verification before compression: dumped/grepped all ~50 linked typed files against their index lines. All detail already lives in the typed files except ONE index-only fact — the install-SOP 2026-05-22 update (vault PR #105 `d54afd9`, Row 11 → four places incl. `app.py:40`). Appended to `reference_brisen_lab_install_sop.md` §SOP updates.
3. Stale/closed moved to `MEMORY_ARCHIVE.md` §Archived 2026-06-10: b2 wake audit (typed file says FULLY CLOSED 2026-06-10, PR #73 merged — old index line was stale saying "mirror remaining"), next-session-prep 2026-05-19 pm, handover 2026-05-21 dawn.
4. Traceability belt-and-braces: verbatim pre-trim MEMORY.md snapshot appended to `MEMORY_ARCHIVE.md` (archive is load-on-demand; now 28.7KB). Every dropped word is recoverable there even beyond the typed-file verification.
5. Added one previously unindexed typed file to the index (`feedback_aid_program_tracker_can_be_stale.md` — existed on disk, no index line).

Integrity checks run: all 50 index links resolve to existing files; no old-index entry orphaned (each is in new index or archive); final size 7,944 B.

## Phase 2 — READ-ONLY REPORT (no changes made)

### (a) ~/.claude/skills audit — 187 entries, user-global, loads into EVERY session on this Mac

**Measured cost: ~25.5k tokens of skill list per session system prompt** (85,472 desc chars + 3,392 name chars at ~3.7 chars/token + ~8 tokens/skill list overhead). That is ~12.8% of a 200K window burned before the first user message, in every picker: AH1, AH2, B-codes, desks, researcher, clerk.

Classification by likely user:

| Bucket | Count | Est. tokens | Likely user | Proposed location |
|---|---|---|---|---|
| Design pack (a-b-test-design … wireframe-spec, UX laws, critique-*) | 93 | ~4.6k | design/UI sessions only (Lab UI, dashboard work) | relocate: vault `_ops/skills/` canonical + symlink into the picker(s) that do UI work |
| AH-ops/orchestration (ai-head*, write-brief, pin-protocol, bus-posting-contract, b-code-dispatch, install-agent-to-brisen-lab, engineering-router, done-rubrics, post-deploy-ac, harness-setup, cortex/capability templates, html-triage, matter-onboarding, project-room-build, v2-bridge/forge runbooks…) | ~28 | ~5.5k | AH1/AH2 only | relocate: symlink into `bm-aihead1/.claude/skills/` + `bm-aihead2/.claude/skills/` only |
| Desk/document production (brisen-balazs-*, pichler-*, executive-*, mckinsey/nvidia-html, memo-* pack, claimsmax-*, transcripts-by-matter, counterparty-model, negotiation-prep, email/whatsapp send-pull, dropbox-file-delivery, desk-gmail-reach…) | ~30 | ~7.5k | matter desks (+ AH occasionally) | relocate: desk-picker symlinks (V17 precedent: 7 desk skills moved 2026-05-08, picker meter 8%→4%) |
| Thinking/strategy tools (devils-advocate, pre-mortem, wardley, helmer-7-powers, pyramid-principle, scenario-planning, eval-design, model-selection…) | ~20 | ~3.5k | AH + desks, low frequency | relocate to on-demand dir + one INDEX hook line each (how-to INDEX pattern) |
| Universal utilities (x-twitter, chrome-debug-recovery, local-research-via-gemma, grok-via-xai-api, youtube-analyze, research-fan-out, laconic, it-manager, feature-scout…) | ~16 | ~3.5k | genuinely fleet-wide | keep user-global |

**Projected savings if all four relocations execute:** worker/B-code session ~25.5k → ~3.5k (saves ~22k tokens ≈ 11% of window); AH1 session (keeps AH-ops via picker scope) ~25.5k → ~9k (saves ~16.5k ≈ 8%); desk session keeps desk pack ~11k (saves ~14.5k ≈ 7%). Design pack alone is the cheapest first move: 93 skills, ~4.6k tokens, lowest blast radius.

**Risks / verify-before-execute:**
- R1 — desks rely on auto-load as their ONLY capability-propagation channel (lead memory `feedback_desks_not_on_bus`: "SKILL.md auto-load IS the comms channel"). Any relocation must symlink into every picker that needs the skill, same turn, per the V17 desk-scope-move pattern. Missing one picker silently removes a capability with no error.
- R2 — Tier-0 docs hardcode `~/.claude/skills/laconic/SKILL.md` by absolute path (dropbox-tier0 Rule 6, AH2 Tier-0 read #4, B-code orientation §register). Moving `laconic` breaks mandated reads; keep it global or patch every referencing doc in the same PR.
- R3 — Cowork-spawned worktree sessions (`<picker>/.claude/worktrees/<name>`) must still resolve picker-scoped skills; the 2026-05-10 cwd-check incident shows worktree paths break path assumptions. Test one worktree spawn before fleet rollout.
- R4 — duplication layer: x-twitter, chrome-debug-recovery, local-research-via-gemma exist BOTH as user-global skills and as `.claude/how-to/INDEX.md` entries (double-loaded hooks). Consolidate to one layer during the move.
- R5 — token figures are chars/3.7 + ~8/skill overhead estimates, ±20%; harness serialization overhead not directly measurable from here.

### (b) bm-aihead1/CLAUDE.md audit — 28,184 B ≈ ~7.6k tokens, auto-loaded every session in this clone

Caveat first: this file is `baker-master` repo-checked-in — identical across bm-b1..b4/aihead clones. Per-clone trimming = repo divergence. The clean mechanism is the one lead already used for laconic: SessionStart hook injection from `.claude/role-context/<role>.md`, keyed on cwd.

Section-level findings (bytes / est tokens / proposal):

| Section | Size | Proposal | Est. saving/session |
|---|---|---|---|
| 3 role blocks (B-code 2.5KB + AH2 3.7KB + AH1 5.5KB) | 11.7KB / ~3.2k tok | Move each block to `.claude/role-context/<role>-orient.md`, injected by the existing SessionStart hook for the matching cwd only; CLAUDE.md keeps a 3-line pointer per role. Every session currently loads all three; each needs exactly one. | ~2.1k tok (the two foreign role blocks) |
| Architecture — Cortex 3T | 2.8KB / ~760 tok | Stale ("Today (2026-04-29)", DRY_RUN pending, 18-capability counts). Move to `CLAUDE_REFERENCE.md` / Tier-1 keyword row; keep 3-line pointer. | ~700 tok |
| DIRECTOR COMMUNICATION RULES | 3.1KB / ~850 tok | Rules 3/4/5 near-duplicate dropbox-tier0.md which auto-loads in the same context. Keep Rule 1 + Rule 2 deltas + anchors; point to tier0 for the rest. | ~600 tok |
| Operating model | 1.2KB / ~320 tok | RA-retirement narrative + stale `~/Desktop/baker-code` paths. Compress to 4 lines. | ~200 tok |
| Reference pointers | 1.2KB / ~330 tok | Half the rows duplicate Tier-1 tables in the role blocks. Halve. | ~150 tok |
| Stack / Workflow / Commands / Hard rules / Out of scope / Memory / Compaction / Session start-end | ~5.4KB | Keep — load-bearing, dense. | 0 |

**Total proposed: 28.2KB → ~13-14KB, saving ~3.7-3.8k tokens/session for every agent opening any clone of this repo.** Combined with (a), a B-code session start drops ~25k tokens ≈ 12-13% of window; AH1 drops ~20k ≈ 10% — on top of the PINNED prune + laconic-read fixes already shipped.

No changes made for Phase 2 — lead gates before any execution.

---

# Stage 1 EXECUTED — design-pack relocation (lead GO, bus #2735)

**Result: ~/.claude/skills 187 → 95 entries. 92 design-pack skills moved to `~/.claude/skills-archive/`. Est. ~4.5k tokens removed from every session's system prompt, fleet-wide.**

## What was done
1. Created `~/.claude/skills-archive/`; moved 92 of the 93 design-pack slugs there (full list below). 90 were symlinks into `~/baker-vault/_ops/skills/<slug>` — canonical bodies untouched in the vault; only the runtime link moved. 2 were real dirs (`jtbd`, `three-horizons`) — moved whole, contents intact in archive.
2. **Deviation from the 93:** `analog-library` KEPT global. Reference scan found it actively invoked by name in `~/bm-ben/CLAUDE.md` §Applied-skills, `~/baker-vault/_ops/agents/researcher/orientation.md`, and `research-agent/LONGTERM.md` (which documents user-global install as its contract, "verified 5/5"). It is a business thinking tool misclassified into the design bucket. Keeping it global costs ~130 tokens and zero breakage; per-picker symlinks would have made the LONGTERM contract stale. All other 92 had ZERO references (path-form and word-form) across picker CLAUDE.md files, orientation/operating/LONGTERM files, how-to INDEXes, and global config. The only other hit was a false positive (`pattern-library` as substring of `prompt-pattern-library`).

## Verification (literal outputs)
Fresh headless session (`claude -p`, haiku, cwd ~):
```
laconic: yes
wireframe-spec: no
design-critique: no
fitts-law: no
analog-library: yes
write-brief: yes
```
Desk picker boot (`claude -p`, haiku, cwd ~/bm-ben — the picker that references analog-library):
```
boot: ok
analog-library skill available: yes
laconic skill available: yes
```
Filesystem: 95 remain in `~/.claude/skills` (187−92 ✓), 92 in archive, archived symlinks still resolve to vault bodies (spot-checked `wireframe-spec/SKILL.md` readable through the archived link).

## Rollback
`for s in $(ls ~/.claude/skills-archive); do mv ~/.claude/skills-archive/$s ~/.claude/skills/; done` — single command, no data was deleted anywhere.

## FOOT-GUN — sync_skills.sh will regress this (action needed before next sync run)
`~/baker-vault/_install/sync_skills.sh` symlinks EVERY `_ops/skills/*/` dir into `~/.claude/skills/` unconditionally. Any future run re-creates all 90 moved symlinks and silently undoes this trim. Needs a follow-up vault PR adding an exclusion list (e.g. a `_ops/skills/.archive-list` the script skips) before anyone re-runs sync. Flagged to lead; not executed (vault process change, lead gates).

## The 92 moved slugs
a-b-test-design accessibility-audit accessibility-test-plan aesthetic-usability affinity-diagram animation-principles card-sort-analysis click-test-plan color-system competitive-analysis component-spec content-strategy critique-brand-consistency critique-composition critique-typography critique-visual-hierarchy dark-mode-design data-visualization design-brief design-critique design-debt-audit design-impact-reporting design-ingest design-negotiation design-principles design-qa-checklist design-rationale design-review-process design-sprint-plan design-system-adoption design-system-governance design-token design-token-audit diary-study-plan doherty-threshold empathy-map error-handling-ux experience-map feedback-patterns fitts-law form-design gesture-patterns handoff-spec heuristic-evaluation hicks-law icon-system illustration-style information-architecture interview-script jobs-to-be-done journey-map jtbd law-of-common-region law-of-proximity layout-grid loading-states localization-design metrics-definition micro-interaction-spec millers-law motion-system naming-convention navigation-patterns north-star-vision onboarding-design opportunity-framework pattern-library presentation-deck prototype-strategy readable-measure research-repository responsive-design search-ux service-blueprint spacing-system stakeholder-alignment state-machine summarize-interview survey-design team-workflow test-scenario theming-system three-horizons typography-scale usability-test-plan user-flow-diagram user-persona ux-writing version-control-strategy visual-hierarchy von-restorff-effect wireframe-spec
