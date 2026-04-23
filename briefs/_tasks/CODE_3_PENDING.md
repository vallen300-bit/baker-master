# CODE_3_PENDING — B3 REVIEW: PR #52 KBL_SCHEMA_1 — 2026-04-23

**Dispatcher:** AI Head (Team 1 — Meta/Persistence)
**Working dir:** `~/bm-b3`
**Target PR:** https://github.com/vallen300-bit/baker-master/pull/52
**Branch:** `kbl-schema-1`
**Brief:** `briefs/BRIEF_KBL_SCHEMA_1.md` (shipped in commit `3349c20`)
**Ship report:** `briefs/_reports/B1_kbl_schema_1_20260423.md` (commit `0cc018c`)

**Supersedes:** prior `LEDGER_ATOMIC_1` B3 review — APPROVE landed; PR #51 merged `38a8997`. Mailbox cleared.

---

## What this PR does

Ships M0 quintet row 1 — baker-vault schema v1 greenfield scaffolding staged in baker-master. 6 new files, 352 lines total. Zero code changes, zero baker-vault writes (CHANDA #9 single-writer preserved).

- NEW `vault_scaffolding/v1/schema/VAULT.md` — 9-section rules doc (§1 3-way taxonomy, §2 7-field frontmatter, §3 slug naming, §4 lifecycle, §5 cross-linking, §6 `author: director` guard, §7 new-page lifecycle, §8 out-of-scope, §9 amendment log).
- NEW `vault_scaffolding/v1/schema/templates/matter.md` — 7-field frontmatter + 8 body sections.
- NEW `vault_scaffolding/v1/schema/templates/person.md` — 7-field frontmatter + 6 body sections.
- NEW `vault_scaffolding/v1/schema/templates/entity.md` — 7-field frontmatter + 6 body sections.
- NEW `vault_scaffolding/v1/people.yml` — 2-entry seed (`dimitry-vallen`, `andrey-oskolkov`), version 1.
- NEW `vault_scaffolding/v1/entities.yml` — 3-entry seed (`brisen-capital-sa`, `brisen-development-gmbh`, `aelio-holding-ltd`), version 1.

B1 reported: 10/10 ship gate PASS, regression parity (19f/830p/19e identical main vs branch — content-only PR adds zero tests), 25 min build.

---

## Your review job (charter §3 — B3 routes; Tier A auto-merge on APPROVE)

### 1. Scope lock — exactly 6 files, all under `vault_scaffolding/v1/`

**Paste into b3 shell:**

```bash
cd ~/bm-b3 && git fetch && git checkout kbl-schema-1 && git pull -q
git diff --name-only main...HEAD
```

Expect exactly these 6 paths, nothing else:

```
vault_scaffolding/v1/entities.yml
vault_scaffolding/v1/people.yml
vault_scaffolding/v1/schema/VAULT.md
vault_scaffolding/v1/schema/templates/entity.md
vault_scaffolding/v1/schema/templates/matter.md
vault_scaffolding/v1/schema/templates/person.md
```

**Reject if:** any path starts with `baker-vault/` or `~/baker-vault/` (would violate CHANDA #9). Also reject if `slugs.yml`, `kbl/`, `models/`, `tests/`, or any `.md` in `briefs/` (other than the report) was touched.

### 2. YAML frontmatter parses on all 4 `.md` files

```bash
# VAULT.md
python3 -c "import yaml; raw = open('vault_scaffolding/v1/schema/VAULT.md').read(); fm = raw.split('---')[1]; d = yaml.safe_load(fm); assert d['type'] == 'schema' and d['version'] == 1"

# 3 templates
for f in vault_scaffolding/v1/schema/templates/*.md; do
  python3 -c "import yaml; raw = open('$f').read(); fm = raw.split('---')[1]; yaml.safe_load(fm)" || { echo "FAIL: $f"; exit 1; }
done && echo "All 3 templates parse OK."
```

All return zero errors.

### 3. All 3 templates have 7 frontmatter keys

```bash
for f in vault_scaffolding/v1/schema/templates/*.md; do
  n=$(grep -E '^(type|slug|name|updated|author|tags|related):' "$f" | wc -l | tr -d ' ')
  [ "$n" = "7" ] || { echo "FAIL: $f has $n keys, expected 7"; exit 1; }
done && echo "All 3 templates have 7 frontmatter keys."
```

Expect: `All 3 templates have 7 frontmatter keys.`

### 4. Registry validity — version, uniqueness, no slug-in-own-aliases, valid status

```bash
python3 -c "
import yaml
for fn, key in [('vault_scaffolding/v1/people.yml', 'people'),
                ('vault_scaffolding/v1/entities.yml', 'entities')]:
    d = yaml.safe_load(open(fn))
    assert d['version'] == 1, fn
    assert 'updated_at' in d, fn
    slugs = [e['slug'] for e in d[key]]
    assert len(slugs) == len(set(slugs)), f'{fn}: duplicate slugs'
    for e in d[key]:
        assert e['slug'] not in e.get('aliases', []), f'{fn}: slug in own aliases ({e[\"slug\"]})'
        assert e['status'] in ('active', 'retired', 'draft'), f'{fn}: bad status'
print('Registry files valid.')
"
```

Expect: `Registry files valid.`

### 5. Expected seed populations are correct

```bash
python3 -c "
import yaml
p = yaml.safe_load(open('vault_scaffolding/v1/people.yml'))
e = yaml.safe_load(open('vault_scaffolding/v1/entities.yml'))
assert len(p['people']) == 2, f'people count: {len(p[\"people\"])}'
assert len(e['entities']) == 3, f'entities count: {len(e[\"entities\"])}'
assert {x['slug'] for x in p['people']} == {'dimitry-vallen', 'andrey-oskolkov'}
assert {x['slug'] for x in e['entities']} == {'brisen-capital-sa', 'brisen-development-gmbh', 'aelio-holding-ltd'}
print('Seed populations correct.')
"
```

Expect: `Seed populations correct.`

### 6. VAULT.md structure — exactly 9 sections

```bash
grep -c "^## §" vault_scaffolding/v1/schema/VAULT.md
```

Expect: `9`.

### 7. No leaked absolute paths / no Dropbox paths

```bash
grep -rn "/Users/dimitry" vault_scaffolding/ || echo "OK: no absolute paths leaked."
grep -rn "Dropbox" vault_scaffolding/ || echo "OK: no Dropbox references."
```

Expect: both OK messages. Absolute paths / Dropbox refs would couple staging to Director's specific machine — reject.

### 8. Baker-vault integrity — not touched

```bash
git diff --name-only main...HEAD | grep -E "(^baker-vault/|~/baker-vault|/baker-vault/)" || echo "OK: no baker-vault writes."
```

Expect: `OK: no baker-vault writes.` Any hit here is a CHANDA #9 violation — hard reject.

### 9. Singleton hook still green

```bash
bash scripts/check_singletons.sh
```

Expect: `OK: No singleton violations found.`

### 10. Regression parity (content-only PR; zero test changes)

```bash
pytest tests/ 2>&1 | tail -3
```

Expect same counts as main. B1 reported `19 failed, 830 passed, 19 errors`. Compare to main baseline at review time — should be identical (no new tests, no test deletions). If branch shows fewer passes or more failures, something in the content files is interfering with pytest collection — reject.

### 11. Slug format — firstname-lastname rule enforced for people.yml

```bash
python3 -c "
import yaml, re
d = yaml.safe_load(open('vault_scaffolding/v1/people.yml'))
for e in d['people']:
    assert re.fullmatch(r'[a-z]+(-[a-z]+)+', e['slug']), f'bad slug format: {e[\"slug\"]}'
print('People slugs follow firstname-lastname format.')
"
```

Expect: `People slugs follow firstname-lastname format.`

### 12. VAULT.md body references §§1–§9 in order

```bash
grep "^## §" vault_scaffolding/v1/schema/VAULT.md | head -9
```

Expect headers in order §1 through §9. Out-of-order suggests accidental edit drift.

---

## If 12/12 green

Post APPROVE comment on PR #52. Tier A auto-merge on APPROVE (standing per charter §3). Write ship report to `briefs/_reports/B3_pr52_kbl_schema_1_review_20260423.md`.

Overwrite this file with a "B3 dispatch back" summary section replacing the review-job content. Commit + push on main.

## If any check fails

Use `gh pr review --request-changes` with a specific list. Route back to B1 via new CODE_1_PENDING.md task. Do NOT merge.

---

## Timebox

**~20–30 min.** Content review is mechanical; this is the smallest review this week.

---

**Dispatch timestamp:** 2026-04-23 post-PR-52-ship (Team 1, M0 quintet row 1 B3 review)
**Team:** Team 1 — Meta/Persistence
**Sequence:** ENFORCEMENT_1 (#45) → GUARD_1 (#49) → LEDGER_ATOMIC_1 (#51) → **KBL_SCHEMA_1 (#52, this review)** → MAC_MINI_WRITER_AUDIT_1 (docs, last)
