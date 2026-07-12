---
brief_id: RESEARCHER_TRANCHE2_8_RESEARCH_MEMORY_INDEX
owner: b2
dispatched_by: lead (#9721 / #9894 / #9898)
date: 2026-07-12
status: SHIPPED — 2 PRs open, lead merges (no self-merge)
prs:
  - baker-master#542 (scripts + tests)
  - baker-vault#186 (cage + manifest + weekly backstop)
---

# B2 ship report — Research memory / index (item #8, Option B)

## Done rubric

| Requirement (design + lead rulings) | Status |
|---|---|
| Machine index `_index.json` (one record per report, heterogeneous frontmatter, best-effort) | ✅ 59 reports |
| Human `_index.md` **regenerated from the manifest** (single SoT, ruling #9898 §2) | ✅ overwrites 2026-04-14 seed |
| Fail-loud: no-frontmatter reports flagged + indexed, **never dropped** | ✅ 2 flagged `no-frontmatter` |
| Deterministic order (date desc, path asc), idempotent regen | ✅ reports byte-identical across runs |
| READ-ONLY search over the manifest (no writes/ack/arg-exec) | ✅ `search_research_index.sh` |
| Hard-pinned paths, no env/arg config (item #12 hardening) | ✅ both scripts |
| Cage: additive `IS_VETTED` exact-path only, no deny weakening (ruling cage note) | ✅ 2 entries, verified |
| Regen ownership = BOTH on-ship + Mac-Mini weekly (ruling #9898 §1) | ✅ vetted-bash step + launchd backstop |
| Semantic search deferred past ~300 docs (ruling #9898 §3) | ✅ design note; keyword+frontmatter now |

## What shipped

**baker-master PR #542**
- `scripts/regen_research_index.sh` — scans `wiki/research/*.md` (excl `_index.*`), best-effort YAML-frontmatter parse (no pyyaml dep; handles `key: value`, inline `[a,b]`, block `- item` lists), emits `_index.json` + regenerates `_index.md`. `--check` dry-run writes nothing.
- `scripts/search_research_index.sh` — READ-ONLY, AND keyword semantics across title+summary+tags+author+path, `--json`, fail-loud on missing index.
- `tests/test_research_index.py` — **16 tests, all green** (heterogeneous parse; no-frontmatter flagged-not-dropped; deterministic+idempotent; search subset/AND/tags/author/read-only; empty-corpus clean; fail-loud missing-dir/missing-index; unknown-arg reject).

**baker-vault PR #186**
- `_ops/hooks/researcher_bash_cage.sh` — 2 additive `IS_VETTED` entries. **Verified under `RESEARCHER_BASH_CAGE_ENFORCE=1`:** vetted paths → allow (exit 0); impostor `~/baker-vault/wiki/research/regen_research_index.sh` → deny (exit 2); `BASH_ENV=… <vetted>` → deny (exit 2).
- `wiki/research/_index.json` (59 reports, 2 flagged) + regenerated `_index.md`.
- `scripts/research-index-regen.sh` + `com.baker.research-index-regen.plist` — Mini weekly backstop, mirrors edge-scout, invokes the single regen SoT (no parser drift).

## Test output
```
16 passed, 1 warning in 1.15s   (pytest tests/test_research_index.py)
```

## Handed off / follow-ups
- **Mini deploy** (copy `research-index-regen.sh` + `regen_research_index.sh` to `~/Library/Application Support/baker/` + `launchctl load` the plist) → lead/deputy per edge-scout precedent.
- **Researcher-on-ship wiring**: the researcher must call `regen_research_index.sh` after each `wiki/research/` write, and `search_research_index.sh` at brief Step 0. That is a researcher method/orientation edit — routes via lead/deputy/codex, **not** a b2 self-edit (brief §3 routing rule). Flagged for lead.
- Cage entries vet `$HOME/bm-b1/scripts/…` (the researcher's runtime script home per existing IS_VETTED lineage); scripts land there when PR #542 merges to main and bm-b1 pulls.

## Rails
Two-gate Claude-side review (codex suspended #9711). Lead merges — **no self-merge**.
