---
dispatch: CODE_4
status: COMPLETE
brief: briefs/BRIEF_DOSSIER_ROOM_READ_1.md
rev: 3
from: cowork-ah1
date: 2026-05-30
supersedes: BRIEF_HARNESS_SETUP_SKILL_1 (DONE — deputy-confirmed bus #1386; stale mailbox)
reviewers_cleared: Codex (FAIL-LIGHT C1–C3 folded) + Architect (SOUND-WITH-NITS D1–D5 folded)
brief_commit: 9127e81
complexity: Medium
est: ~2-3h
reply_to: cowork-ah1
ship_pr: 272
ship_commit: b86cd7b
ship_branch: b4/dossier-room-read (deleted post-merge)
merged_at: 2026-05-30T14:32:00Z
security_review: CLEAN (0 findings) — cowork-ah1 bus #1396
ac8_researcher_post: bus #1397 2026-05-30T14:35:54Z
---

# CODE_4 DISPATCH — BRIEF_DOSSIER_ROOM_READ_1 (Rev 3)

**Reply to `cowork-ah1` (NOT lead) — this dispatch is from the Cowork App lane.**

**Read the full brief: `briefs/BRIEF_DOSSIER_ROOM_READ_1.md` (committed 9127e81).** This envelope is the dispatch summary only — the brief is authoritative.

## What you're building
Slug-resolved curated-room pre-read for Baker's dossier engine. Before specialists run, resolve the subject to ONE matter slug, read that room via the EXISTING KBL reader, and PUSH it into the specialist prompt as ground truth. Fixes: both Baker dossier + Researcher falsely reported the 22-May Bick concept paper "missing" when it was filed in `wiki/matters/nvidia-mohg/00_originals/`.

## Two files
1. `kbl/curated_wiki_reader.py` — add `read_room(slug)` extending existing `read_curated` (line 111). **Reuse the file's existing symlink/path containment (lines 138–166) — do NOT re-implement path safety.** Run `/security-review` on any new path join.
2. `orchestrator/research_executor.py` — add `matter_slug` to `_get_proposal` SELECT (lines 50–53, currently omits it); resolve subject→slug with strict precedence; single call-site prepend before `_run_specialists` (line 150).

## HARD GATES (must-pass — two reviewers flagged these)
1. **[Codex C2] Wrong-room collision test.** A Bick/MOHG dossier (context has "MOHG"/"Mandarin") with NO explicit `matter_slug` must NOT resolve to `mo-vie-am` (slugs.yml:38 maps `mohg`→`mo-vie-am`) and must NOT get the authoritative header. Generic single-token aliases REJECTED.
2. **[Codex C1] Explicit `matter_slug` column dominates** any context guess; SELECT must fetch it.
3. **[Codex C3] Metadata-only fallback** reads frontmatter + `_people.md` ONLY — never room bodies.
4. **[Architect D2] Authoritative header** only on explicit/exact-composite resolution; metadata-only → weak `POSSIBLY-RELATED` header; unresolved → no-op (fail closed).
5. **[Architect D1] Reuse** `curated_wiki_reader`; do not build a private room reader.
6. Fault-tolerant: any error → log → return "" → dossier proceeds unchanged. Read-only on vault.
7. Final-prompt budget assert (digest ≤8K tokens).
8. Structured resolution log per path + `room_found`; runtime kill-flag at call-site (NOT module env).

## Done =
All 11 Quality Checkpoints in the brief pass + `py_compile` clean on both files + the C2 collision regression green. Report to `briefs/_reports/`. **Reply to `cowork-ah1` via bus.** Do NOT commit/push until AH1 authorizes.

## Constraints
- Do NOT touch `kbl/slug_registry.py` (public API only), `_format_dossier_markdown`, `_generate_and_save_docx`, any `wiki/matters/**` content.
