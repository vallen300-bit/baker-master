# BRIEF: LAB_UNIFY_P2_SKILLS_1 — SKILLS catalog page (Director groups · browsable · templates gallery links)

```yaml
brief_id: LAB_UNIFY_P2_SKILLS_1
dispatched_by: lead
assigned_to: b2
repo: brisen-lab (worktree ~/bm-b2/brisen-lab; branch b2/lab-unify-p2-skills-1 from origin/main)
status: PENDING
```

## Context

Director-ratified Lab unification, Phase 2 (single brief). Source:
`bm-aihead1/briefs/_plans/BRISEN_LAB_UNIFICATION_BUILD_PLAN_2026-07-20.md`
(§Phase 2, approved "go") + ratified layout sidebar entry 3: "SKILLS —
browsable catalog. Groups: Business (Financial / Legal / Analytical /
Communication…), Docs Writing, Research, Sources Ingestion, Technical, Design,
Publishing. Columns: full description, source of skill, location, templates
gallery (links to HTML), agents that have this skill."

Phase 1 is LIVE (items 1+2: `/v2` shell @d69e2f6, `/v2/settings-logs`
@81346e1). You (b2) built the shell — this brief replaces YOUR placeholder
SKILLS pane with the real page, same iframe pattern you used for Settings &
Logs. Cockpit revamp register is the style reference.

The Director grouping judgment is ALREADY DONE by lead — data file
`wiki/_fleet/skill-registry-categories-director.json` in baker-vault
@5a1b9e3 (8 categories, 26 groups, 135/135 slugs validated: no dupes, no
missing, no extras). Do not re-group; consume it.

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Director opens SKILLS in the Lab sidebar, expands a group, searches by name, and opens a skill's template sample in a new tab.
2. **Backend route:** NEW `GET /v2/skills` in brisen-lab `app.py` — append-only FileResponse, exact pattern of the two verified existing routes: `app.py:789 @app.get("/v2")` and `app.py:2139 @app.get("/v2/settings-logs")` (both confirmed live 200 anonymous 2026-07-20).
3. **Endpoint contract:** GET, no params, no auth (matches /v2 + /v2/settings-logs live behavior). Data = same-origin `GET /static/v2/skills-data.json` (StaticFiles mount already serves static/v2/ — settings-logs.js?v=2 confirmed served live). NO cross-origin fetch — the brisen-docs CORS anti-pattern (write-brief table) forbids fetching from brisen-docs.onrender.com; templates are `<a target="_blank">` navigation links only.
4. **State location:** baker-vault `wiki/_fleet/skill-registry.md` (ARM-owned md master, 135 skills) + `wiki/_fleet/skill-registry-categories-director.json` @5a1b9e3 (lead-owned Director grouping). Vendored into brisen-lab as a static snapshot `static/v2/skills-data.json` (vault is not web-served; catalog delta cadence is ~weekly; refresh flow documented below — honest snapshot, not a live feed).
5. **UI repo (= state-serving repo):** brisen-lab, `static/v2/skills.*` — cross-repo split is deliberate and documented: vault owns the catalog, Lab owns the Director surface (ratified layout).
6. **Director surface preference:** ratified 2026-07-20 — SKILLS is sidebar entry 3 of the unified Lab; grouping eyeballed in-page by Director, no separate approval round (build plan §Phase 2.4).
7. **Gate-1+2 reviewer instruction:** Reviewers MUST load `/v2/skills` in a browser AND `curl` `/static/v2/skills-data.json`, confirm 135 skills render across 8 categories, and spot-check at least 3 template links against the live URLs in the allowlist below (expect 200). Code-shape review is necessary but NOT sufficient.

## Estimated time: ~4h
## Complexity: Medium
## Prerequisites: none (Phase 1 live; no other brief in flight on static/v2/)

## Baker Agent Vault Rails
Relevant: build-command-center, verification-surfaces, bus-and-lanes.
Ignored: memory-and-lessons, loop-runner — read-only catalog page, no DB.

## Harness V2

- **Context Contract:** read before building: this brief (whole), `static/v2/shell.js` + `static/v2/index.html` (your own Phase-1 files — the settings-logs lazy-iframe pattern you will replicate), `static/v2/settings-logs.js` (fail-soft + textContent idiom), `~/baker-vault/wiki/_fleet/skill-registry.md` (frontmatter + table shape), `~/baker-vault/wiki/_fleet/skill-registry-categories-director.json`, one existing route test in `tests/`. Nothing else required.
- **Task class:** medium-feature (production, brisen-lab).
- **Done rubric / done-state class:** terminal = Merged + Deployed + post-deploy AC passed + writeback resolved. Post-deploy AC (lead): live `/v2/skills` renders all 8 categories / 135 skills, search filters, template links open live pages, shell SKILLS entry mounts it. Writeback: registry status HTML update by lead.
- **Gate plan:** b2 self-test (pytest + local uvicorn + browser) → push branch → blocking independent codex gate on pushed SHA (Surface contract §7 binding) → lead merge → Render auto-deploy → lead POST_DEPLOY_AC_VERDICT on bus.

---

## Feature 1: SKILLS catalog page + data snapshot

### Problem
The fleet's 135 skills are invisible to the Director — the only views are a
vault markdown table and an engineering-grouped vault HTML, neither web-served.
The ratified layout puts a browsable, Director-grouped catalog at Lab sidebar
entry 3, replacing the "arriving Phase 2" placeholder.

### Current State
- `static/v2/index.html` (~line 47): SKILLS placeholder pane (`view-skills`).
- `static/v2/shell.js`: settings-logs lazy fail-soft iframe mount — the pattern to replicate.
- Vault: `wiki/_fleet/skill-registry.md` (135 rows: slug · purpose · triggers · owner (basis) · consumers · last_verified · status) + `skill-registry-categories-director.json` @5a1b9e3.
- Old templates gallery lives on brisen-docs (`/templates/` — stays live, untouched; it retires only at Director "switch" per plan).

### Engineering Craft Gates
- Diagnose: N/A — new feature, no bug.
- Prototype: N/A — grouping fixed by lead data file; register fixed (cockpit revamp); Director eyeballs in-page per build plan.
- TDD/verification: applies — first tests BEFORE page build: (1) route test `GET /v2/skills` 200 `text/html` (FastAPI TestClient, existing pattern); (2) data-integrity test on `static/v2/skills-data.json`: parses, exactly 135 skills, every slug in every category group has a skills entry, every template URL is in the fixed allowlist below.

### Implementation

1. **`app.py`** — append-only route (verify no existing `/v2/skills` route first: `grep -n "v2/skills" app.py`):
```python
@app.get("/v2/skills")
def v2_skills():
    return FileResponse("static/v2/skills.html")
```

2. **`static/v2/skills-data.json`** — generate ONCE at build time with this snippet (run from `~/bm-b2/brisen-lab`; vault read-only — do NOT commit anything to baker-vault):
```python
#!/usr/bin/env python3
# gen: skills-data.json from vault md master + director mapping (vendored snapshot)
import json, pathlib, re
VAULT = pathlib.Path.home() / "baker-vault" / "wiki" / "_fleet"
md = (VAULT / "skill-registry.md").read_text()
mapping = json.loads((VAULT / "skill-registry-categories-director.json").read_text())
TEMPLATES = json.loads(pathlib.Path("templates-map.json").read_text())  # from brief, step 3

rows = {}
for line in md.splitlines():
    cells = [c.strip() for c in line.split("|")]
    if len(cells) >= 8 and cells[1].startswith("`") and cells[1].endswith("`"):
        slug = cells[1].strip("`")
        rows[slug] = {
            "desc": cells[2], "owner": cells[4], "consumers": cells[5],
            "last_verified": cells[6], "status": cells[7],
            "location": f"_ops/skills/{slug}/",
            "templates": TEMPLATES.get(slug, []),
        }
fm = re.match(r"---\n(.*?)\n---", md, re.S).group(1)
out = {
    "source": {"md_last_updated": re.search(r"last_updated: (\S+)", fm).group(1),
               "skill_count": int(re.search(r"skill_count: (\d+)", fm).group(1)),
               "mapping": "skill-registry-categories-director.json @5a1b9e3"},
    "categories": mapping["categories"],
    "skills": rows,
}
assert len(rows) == out["source"]["skill_count"], f"row parse mismatch: {len(rows)}"
mapped = [s for c in mapping["categories"] for g in c["groups"] for s in g["slugs"]]
assert sorted(mapped) == sorted(rows), "mapping/master drift"
pathlib.Path("static/v2/skills-data.json").write_text(json.dumps(out, indent=1))
print(f"wrote {len(rows)} skills")
```
   If the two asserts fail (catalog moved since @5a1b9e3), STOP and post to lead — do not hand-patch the mapping.

3. **`templates-map.json`** (build-time input, commit it next to the generator step in `scripts/` or inline it in the snippet — your call; content is FIXED by lead, all URLs verified live 200 on 2026-07-21):
```json
{
 "pichler-report": [{"label": "Per-trade claim report (T1)", "url": "https://brisen-docs.onrender.com/templates/samples/t1-per-line-claim-report.html"}],
 "pichler-report-english": [{"label": "Per-trade claim report (T1)", "url": "https://brisen-docs.onrender.com/templates/samples/t1-per-line-claim-report.html"}],
 "executive-audit-html": [{"label": "Cross-case audit (T2)", "url": "https://brisen-docs.onrender.com/templates/samples/t2-cross-case-audit.html"}],
 "executive-memo-ellie-style": [{"label": "Strategic memo (T3)", "url": "https://brisen-docs.onrender.com/templates/samples/t3-strategic-memo.html"}],
 "mckinsey-report-html": [{"label": "Matter evidence report (T4)", "url": "https://brisen-docs.onrender.com/templates/samples/t4-matter-evidence.html"}],
 "brisen-balazs-word-style": [{"label": "Counterparty proposal (T5, docx)", "url": "https://brisen-docs.onrender.com/templates/samples/t5-counterparty-proposal.docx"}],
 "project-room-build": [{"label": "Project room structure (T6)", "url": "https://brisen-docs.onrender.com/templates/samples/t6-project-room-structure.html"}]
}
```
   URL allowlist for the data-integrity test = exactly these 7 URLs. No other external URL may appear in skills-data.json.

4. **`static/v2/skills.html` + `static/v2/skills.js?v=1`** — vanilla JS, cockpit register tokens (copy from your shell.css work). Layout:
   - Header: title + count line (`135 skills · 8 categories · snapshot <md_last_updated>`) + search box.
   - One section per category (category color as accent bar, desc line under name), groups as collapsible sub-sections (default: collapsed; search auto-expands matches).
   - Per skill row (expandable): **name** · status chip · description (full `desc` text) · source (`owner` string, keep the `(inf·…)` basis marker — it is an honesty caveat, not noise) · location (plain text code style) · templates (links from `templates`, `target="_blank" rel="noopener"`; "—" when empty) · agents (`consumers` string as chip) · last_verified.
   - Fetch `/static/v2/skills-data.json` with `AbortSignal.timeout(8000)` + try/catch; on failure render `Skills catalog data unavailable.` — never a blank page. If any category contains a slug missing from `skills`, render it as a name-only row (never drop) — mirrors the vault generator's UNCATEGORIZED honesty rule.
   - XSS: ALL dynamic text via `textContent`; template URLs set via `el.href` only after `url.startsWith("https://brisen-docs.onrender.com/templates/")` check (defense-in-depth on top of the test allowlist). No innerHTML with data strings. No `_escHtml` helper exists — do not reference one.
   - Search: client-side filter on slug + desc + group + category, 150ms debounce.
5. **Shell integration** (your own Phase-1 files): replace the SKILLS placeholder pane in `static/v2/index.html` with the same lazy fail-soft iframe pattern you built for Settings & Logs (`/v2/skills`; 404/error → fallback pane, not blank iframe); extend `shell.js` accordingly. Bump cache-bust on every static asset you touch (`shell.css`/`shell.js` are at `?v=2` — bump to `?v=3`; new files start `?v=1`).
6. Standalone-first: `/v2/skills` must render correctly opened directly; the shell merely iframes it.

### Key Constraints
- ZERO edits to old Lab pages, cockpit static, controller, any existing handler, brisen-docs, baker-vault (vault is READ-ONLY input).
- Read-only page: no POST anywhere; no new API endpoints beyond the FileResponse route.
- skills-data.json is a build-time vendored snapshot — do NOT add runtime fetches to vault or brisen-docs, do NOT add a cron. Refresh flow (documented, out of your scope): on catalog delta, ARM/lead reruns the generator snippet and ships the refreshed JSON as a trivial follow-up commit.
- Financial figures: none anywhere on this page.

### Verification
1. `pytest` — route test + data-integrity test green; suite no regressions.
2. Local uvicorn: `/v2/skills` renders 8 categories / 135 skills; search narrows and auto-expands; every populated template link opens the live brisen-docs page (spot-check ≥3 by hand in browser); kill the JSON (rename temporarily) → page shows the unavailable message, shell shows your fallback pane.
3. `/v2` shell: SKILLS sidebar entry mounts the page; AGENTS/LOOPS/SETTINGS panes unaffected.
4. Old `/` untouched (git diff: only new files + one app.py route + your two shell files).

## Files Modified
- `app.py` (+4 lines, one route) · `static/v2/skills.html` · `static/v2/skills.js` · `static/v2/skills-data.json` (new) · `static/v2/index.html` + `static/v2/shell.js` (SKILLS pane swap, cache-bust bump) · `tests/test_v2_skills_route.py` (new)

## Do NOT Touch
- Old Lab static files, cockpit/, controller, all existing app.py handlers.
- `static/v2/settings-logs.*` (b1's item-2 files — live).
- baker-vault (read-only input; the mapping file is lead-owned).

## Quality Checkpoints
1. Data-integrity test enforces 135/135 + URL allowlist — mapping drift fails the build loudly, never silently.
2. Every fetch has timeout + try/catch + visible degraded state; unmapped/missing slugs render, never drop.
3. Owner `(inf·…)` basis markers preserved (ARM registry honesty caveat).
4. Ship report to lead on bus (`lab-unify/p2-skills`) with branch + HEAD SHA; codex gate routes on your pushed SHA.

## Verification SQL
N/A — static page over a vendored JSON snapshot; no DB access.
