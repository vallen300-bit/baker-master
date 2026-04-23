# Code Brisen #1 — Pending Task

**From:** AI Head (Team 1 — Meta/Persistence)
**To:** Code Brisen #1
**Task posted:** 2026-04-23
**Status:** OPEN — `KBL_SCHEMA_1` (M0 quintet row 1 — baker-vault schema v1 greenfield scaffolding)

**Supersedes:** prior `LEDGER_ATOMIC_1` task — shipped as PR #51, merged `38a8997` 2026-04-23. Mailbox cleared.

---

## Brief-route note (charter §6A)

Full `/write-brief` 6-step protocol. Brief at `briefs/BRIEF_KBL_SCHEMA_1.md`.

M0 quintet row 1 — unblocks KBL_INGEST_ENDPOINT (M0 row 3) and future `kbl/people_registry.py` + `kbl/entity_registry.py` briefs. Design calls locked by Director 2026-04-23 ("default recom is fine"): 3-way taxonomy (matter/person/entity), 7-field frontmatter, firstname-lastname people slugs, greenfield.

---

## Context (TL;DR)

Baker-vault's schema is 1-line stub. `schema/templates/` empty. `people.yml` / `entities.yml` don't exist. Only `slugs.yml` (v9, matters only) is authoritative.

This brief ships **6 content files** under a staging path `vault_scaffolding/v1/` **in baker-master** (no baker-vault writes from B-code — Mac Mini is the sole vault writer per CHANDA #9). AI Head post-merge SSH-copies to baker-vault.

## Action

Read `briefs/BRIEF_KBL_SCHEMA_1.md` end-to-end. Each of the 6 files has verbatim content in the brief — copy-paste then verify frontmatter parses.

**Files to create (all NEW, all under `vault_scaffolding/v1/` in baker-master):**

1. `vault_scaffolding/v1/schema/VAULT.md` — ~170 lines. 9 sections (§1–§9). Fenced YAML example block inside §2. Amendment log in §9.
2. `vault_scaffolding/v1/schema/templates/matter.md` — ~40 lines. 7-field frontmatter + 8 body sections.
3. `vault_scaffolding/v1/schema/templates/person.md` — ~35 lines. 7-field frontmatter + 6 body sections.
4. `vault_scaffolding/v1/schema/templates/entity.md` — ~35 lines. 7-field frontmatter + 6 body sections.
5. `vault_scaffolding/v1/people.yml` — 2-entry seed (`dimitry-vallen`, `andrey-oskolkov`). Version 1.
6. `vault_scaffolding/v1/entities.yml` — 3-entry seed (`brisen-capital-sa`, `brisen-development-gmbh`, `aelio-holding-ltd`). Version 1.

**Total: 6 new files, ~345 lines.**

**Non-negotiable invariants:**
- Baker-vault is NOT touched — zero paths starting with `baker-vault/` or `~/baker-vault/` in the diff.
- Staging directory `vault_scaffolding/v1/` is genuinely new in baker-master. Do NOT put files anywhere else.
- Every `.md` template has all 7 required frontmatter keys: `type`, `slug`, `name`, `updated`, `author`, `tags`, `related`.
- Every `.yml` registry has `version: 1` + `updated_at: 2026-04-23` + a named list (`people:` / `entities:`).
- No slug appears in its own `aliases:` list (mirrors `slug_registry.py` load-time rule).
- `dimitry-vallen` and `andrey-oskolkov` use firstname-lastname format per VAULT.md §3.2.

## Ship gate (literal output required in ship report)

**Baseline first** — run `pytest tests/ 2>&1 | tail -3` on `main` BEFORE branching; record the `N passed, M failed` line in the ship report.

Then, after implementation:

```bash
# 1. YAML frontmatter parses — VAULT.md
python3 -c "import yaml; raw = open('vault_scaffolding/v1/schema/VAULT.md').read(); fm = raw.split('---')[1]; d = yaml.safe_load(fm); assert d['type'] == 'schema' and d['version'] == 1"

# 2. YAML frontmatter parses — 3 templates
for f in vault_scaffolding/v1/schema/templates/*.md; do python3 -c "import yaml; raw = open('$f').read(); fm = raw.split('---')[1]; yaml.safe_load(fm)" || { echo "FAIL: $f"; exit 1; }; done && echo "All 3 templates parse OK."

# 3. Template frontmatter has all 7 required keys
for f in vault_scaffolding/v1/schema/templates/*.md; do n=$(grep -E '^(type|slug|name|updated|author|tags|related):' "$f" | wc -l | tr -d ' '); [ "$n" = "7" ] || { echo "FAIL: $f has $n keys"; exit 1; }; done && echo "All 3 templates have 7 frontmatter keys."

# 4. Registry files load + slug uniqueness
python3 -c "
import yaml
for fn, key in [('vault_scaffolding/v1/people.yml', 'people'), ('vault_scaffolding/v1/entities.yml', 'entities')]:
    d = yaml.safe_load(open(fn))
    assert d['version'] == 1, fn
    slugs = [e['slug'] for e in d[key]]
    assert len(slugs) == len(set(slugs)), f'{fn}: duplicate slugs'
    for e in d[key]:
        assert e['slug'] not in e.get('aliases', []), f'{fn}: slug in own aliases ({e[\"slug\"]})'
        assert e['status'] in ('active', 'retired', 'draft'), f'{fn}: bad status'
print('Registry files valid.')
"

# 5. VAULT.md structure counts
grep -c "^## §" vault_scaffolding/v1/schema/VAULT.md   # expect 9

# 6. Directory structure — exactly 6 files
find vault_scaffolding -type f | sort

# 7. No leaked absolute paths
grep -rn "/Users/dimitry" vault_scaffolding/ || echo "OK: no absolute paths leaked."

# 8. Singleton hook still green
bash scripts/check_singletons.sh

# 9. Full-suite regression delta (no test changes in this brief; expect parity)
pytest tests/ 2>&1 | tail -3

# 10. No baker-vault writes in diff
git diff --name-only main...HEAD | grep -E "^(baker-vault|~?/baker-vault)" || echo "OK: no baker-vault paths in diff."
```

**No "pass by inspection"** (per `feedback_no_ship_by_inspection.md`). Paste literal outputs.

## Ship shape

- **PR title:** `KBL_SCHEMA_1: Vault schema v1 scaffolding (templates + people.yml + entities.yml + VAULT.md)`
- **Branch:** `kbl-schema-1`
- **Files:** 6 new content files under `vault_scaffolding/v1/`.
- **Commit style:** `kbl(schema-v1): seed vault scaffolding — 3-way taxonomy, 7-field frontmatter, minimal people+entities registries`
- **Ship report:** `briefs/_reports/B1_kbl_schema_1_20260423.md`. Include all 10 ship-gate outputs (literal), `git diff --stat`, line count per file, and pre-change pytest baseline.

**Tier A auto-merge on B3 APPROVE + green CI** (standing per charter §3).

## Out of scope (explicit)

- **Do NOT** write to `baker-vault/` directly — Mac Mini is sole vault writer (CHANDA #9). AI Head post-merge SSH-copies the 6 files.
- **Do NOT** touch `slugs.yml` in either repo — v9 authoritative for matters, unchanged this brief.
- **Do NOT** ship `kbl/people_registry.py` / `kbl/entity_registry.py` loaders — follow-on briefs.
- **Do NOT** retrofit existing `wiki/` content to new schema — Director-gated follow-on (`KBL_SLUGS_RETAXONOMY_1`).
- **Do NOT** bulk-import people from CLAUDE.md people table — 2-seed (`dimitry-vallen`, `andrey-oskolkov`) is deliberate; Director/AI Head populate further entries per PR.
- **Do NOT** bulk-import entities beyond the 3-seed (`brisen-capital-sa`, `brisen-development-gmbh`, `aelio-holding-ltd`) — same reason.
- **Do NOT** add `author: director` frontmatter to `vault_scaffolding/v1/schema/VAULT.md` in baker-master — the Director-signed mutation guard applies to the vault-side file only. Staging copy uses `author: director` inside the VAULT.md body because THAT copy will become the protected vault file after AI Head mirrors; the baker-master staging file having the frontmatter is fine (CHANDA #4 hook isn't installed on baker-master yet per handover).
- **Do NOT** touch `triggers/embedded_scheduler.py`, `memory/store_back.py`, `models/cortex.py`, `CHANDA_enforcement.md`, `CHANDA.md` — all unrelated.

## Timebox

**2–2.5h.** If >3.5h, stop and report — likely content drift or mis-scope.

**Working dir:** `~/bm-b1`.

---

**Dispatch timestamp:** 2026-04-23 post-PR-51-merge (Team 1, M0 quintet row 1 — KBL schema v1)
**Team:** Team 1 — Meta/Persistence
**Sequence:** ENFORCEMENT_1 (#45) → GUARD_1 (#49) → LEDGER_ATOMIC_1 (#51) → **KBL_SCHEMA_1 (this)** → MAC_MINI_WRITER_AUDIT_1 (docs, last)
