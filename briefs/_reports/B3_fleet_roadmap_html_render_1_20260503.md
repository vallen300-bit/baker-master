---
brief: BRIEF_FLEET_ROADMAP_HTML_RENDER_1
brief_version: V0.3.1
worker: B3
status: SHIPPED
shipped_at: 2026-05-03T23:55:00Z
trigger_class: MEDIUM
review_path: B1 second-pair-of-eyes pre-merge (RA-24 — Director-facing surface)
prs:
  baker_vault: 80   # merged 3f889a0
  baker_master: 152 # awaiting B1 + AH1 review
branch: b3/fleet-roadmap-html-render-1
---

# B3 ship report — BRIEF_FLEET_ROADMAP_HTML_RENDER_1 (V0.3.1)

## Bottom line

YAML v4 → v5 migration + renderer dispatch + 13 tests + regenerated HTML. Both PRs out; vault merged (`3f889a0`), baker-master open at PR #152 with B1 second-pair-of-eyes requested.

## PRs

| PR | Repo | State | Branch | Reviewers |
|---|---|---|---|---|
| [#80](https://github.com/vallen300-bit/baker-vault/pull/80) | baker-vault | **merged** (squash `3f889a0`) | `b3/fleet-roadmap-html-render-1` | AH1 |
| [#152](https://github.com/vallen300-bit/baker-master/pull/152) | baker-master | open | `b3/fleet-roadmap-html-render-1` | AH1 + B1 (RA-24) |

## Files shipped

**baker-vault PR #80:**
- `_ops/processes/cortex-roadmap-current.yml` — v4 → v5 (827 ins / 822 del). All 46 done + 18 queued + 5 dropped v4 items preserved verbatim under `tracks.cortex.*` (verified by ID-set diff against `origin/main`); 2 backfill items added; brisen_lab track + 6 gates + 4 dependencies seeded.

**baker-master PR #152:**
- `scripts/render_cortex_roadmap.py` — public `render(yml)` preserved as entry; dispatches by `yml["version"]`. `version >= 5` → `render_v5()` (Fleet Operationalization Roadmap layout); `version <= 4` (or missing) → `render_v4()` (legacy single-track layout, body moved verbatim from prior `render()`). Strict v5 schema validator + mixed-schema guard + html-escape on v5 user-content fields + str-coerce ETA sort.
- `tests/test_render_cortex_roadmap.py` — **NEW**, 13 tests (v4 smoke / v5 two-track / v5+v6 mixed-schema / 3 missing-field guards / queued priority+ETA sort / default-priority-medium / empty-dropped-omitted / html-escape / LIVE V5 substring / gate-status-pill classes).
- `docs-site/architecture/cortex-roadmap-current.html` — regenerated (1352 lines).

## Verification (literal output, Lesson #47)

### pytest

```
$ python3 -m pytest tests/test_render_cortex_roadmap.py -v
collected 13 items

tests/test_render_cortex_roadmap.py::test_v4_renders_without_crash PASSED [  7%]
tests/test_render_cortex_roadmap.py::test_v5_renders_two_tracks_and_gates_and_deps PASSED [ 15%]
tests/test_render_cortex_roadmap.py::test_v5_mixed_schema_raises PASSED  [ 23%]
tests/test_render_cortex_roadmap.py::test_v6_mixed_schema_also_raises PASSED [ 30%]
tests/test_render_cortex_roadmap.py::test_v5_missing_required_track_raises PASSED [ 38%]
tests/test_render_cortex_roadmap.py::test_v5_missing_gates_raises PASSED [ 46%]
tests/test_render_cortex_roadmap.py::test_v5_missing_dependencies_raises PASSED [ 53%]
tests/test_render_cortex_roadmap.py::test_v5_queued_priority_sort_per_track PASSED [ 61%]
tests/test_render_cortex_roadmap.py::test_v5_default_priority_medium PASSED [ 69%]
tests/test_render_cortex_roadmap.py::test_v5_empty_dropped_subsection_omitted PASSED [ 76%]
tests/test_render_cortex_roadmap.py::test_v5_html_escape_user_fields PASSED [ 84%]
tests/test_render_cortex_roadmap.py::test_v5_live_badge_substring PASSED [ 92%]
tests/test_render_cortex_roadmap.py::test_gate_status_pill_classes_present PASSED [100%]

============================== 13 passed in 0.02s ==============================
```

### Compile + render

```
$ python3 -c "import py_compile; py_compile.compile('scripts/render_cortex_roadmap.py', doraise=True)"
(clean, exit 0)

$ python3 scripts/render_cortex_roadmap.py
[OK] Rendered ~/baker-vault/_ops/processes/cortex-roadmap-current.yml → docs-site/architecture/cortex-roadmap-current.html
```

### YAML migration verification (vault PR #80)

```
$ python3 -c "..."  # dict diff vs origin/main:
v4 done count:    46    v5 cortex done count:    46    diff: ∅
v4 queued count:  18    v5 cortex queued count:  20    diff: +2 backfill items
v4 dropped count:  5    v5 cortex dropped count:  5    diff: ∅
v4 in_flight:      0    v5 cortex in_flight:      0    diff: ∅
flat top-level done present in v5? False
flat top-level queued present in v5? False
```

### Smoke greps on regenerated HTML

```
$ grep -c "Brisen Lab"                       8  (≥1)
$ grep -c "Director's Gates"                 1  (=1)
$ grep -c "Dependencies"                     1  (≥1)
$ grep -c "LIVE V5"                          1
$ grep -c "Fleet Operationalization Roadmap" 2  (title + h1)
$ wc -l                                   1352
```

## Acceptance criteria

| # | AC | Status |
|---|---|---|
| 1 | v5 YAML parses + strict schema enforced | ✓ (`_validate_v5`) |
| 2 | v4 backward-compat structural markers | ✓ `test_v4_renders_without_crash` |
| 3 | v5 two-track layout (Brisen Lab + Cortex with purpose lines + non-empty subsections) | ✓ `test_v5_renders_two_tracks_and_gates_and_deps` |
| 4 | Gates color pills (open/pending/closed) | ✓ `test_gate_status_pill_classes_present` + CSS classes |
| 5 | Dependencies bullets `<strong>from</strong> → <strong>to</strong>: effect` | ✓ |
| 6 | Render path unchanged — manual + Render auto-deploy on push (no GHA added) | ✓ |
| 7 | Live URL end-to-end | Deferred to Director-side post-deploy smoke |
| 8 | 13/13 pytest pass (literal output) | ✓ above |
| 9 | No new CSS color system — reuse existing vars | ✓ |

## Notes / lessons

- **Sort fix surfaced during smoke against real-world v5 YAML.** PyYAML parses bare ISO dates (`eta: 2026-05-12`) as `datetime.date` and quoted dates / sentinel strings (`post-lab-v2`) as `str`. Mixing the two in one queued list crashes `sorted()` on `<` between `date` and `str`. Brief tests use string ETAs throughout so they didn't catch it; only running against migrated YAML did. Fix: coerce ETA to `str()` in the sort key (`str(date(...))` is ISO-8601 → comparable, chronologically correct). Inline comment explains why. Adds robustness for any future YAML ETA shape (date or string sentinel).
- **HTML escape applied only to v5-introduced user fields** (gates label/note, deps from/to/effect, tracks.<>.purpose). Pre-existing v4 unescaped behavior in `render_item()` grandfathered per brief §3a.
- **Public `render` name preserved** — only refactor was internal extraction to `render_v4` + new `render_v5`. Existing test imports (`rcr.render(yml)`) and CLI entry continue working.
- **Mixed-schema guard fires on `version >= 5`** (forward-compat) — `test_v6_mixed_schema_also_raises` proves it.
- **Pre-existing collection error in `tests/test_cortex_slack_interactivity.py`** (Python 3.10+ `X | None` syntax on 3.9) is unrelated to this brief; reproducible on origin/main without my changes. Flagged here so the next reviewer doesn't conflate.

## Lessons applied

- **#3b** — column-existence check belongs in brief: N/A (no DB schema), but analog applies — schema fields verified in fixtures + dict-diff before commit.
- **#8** — verify before marking done: pytest run literally + visual smoke on regenerated HTML.
- **#44** — cross-repo EXPLORE-phase miss: 2-paired-PR sequence followed; vault PR opened first, merged, locally pulled, re-rendered (no deltas), then baker-master push + PR.
- **#47** — literal pytest output, no "by inspection": ship report includes literal stdout block above.
- **#52** — Tier-A merge gate / `/security-review`: N/A — MEDIUM trigger class, no auth surface, no migrations. `/security-review` not required.
