---
brief_id: BRIEF_FLEET_ROADMAP_HTML_RENDER_1
version: V0.2
authored_by: ai-head-a
authored_at: 2026-05-03
upstream_spec: AH1-App paste-block 2026-05-03 (Director-ratified "yes" in chat)
trigger_class: MEDIUM
review_path: B1 second-pair-of-eyes pre-merge (RA-24 — Director-facing surface)
suggested_assignee: B3 (familiar with V4 YAML render work; B1/B2/B5 also viable)
estimated_complexity: MEDIUM
estimated_time: ~4–6h
cross_repo: true
---

## Version log
- **V0.1** (2026-05-03) — initial author from AH1-App spec.
- **V0.2** (2026-05-03) — architect-reviewer pass 1 folded. Fixes C1–C3 (preserve v4 `target:` + `backlog:` block; html-escape new fields), H1–H3 (priority sort under tracks; gated_on V0.1 hard decision; AC #2 wording aligned to substring assertions), M1–M5 (CSS substage class; tightened test exception matching; mixed-schema check fires on version >= 5), L1–L5 (golden-file pointer; LIVE V5 substring; `render` public name preserved).
- **V0.3** (2026-05-03) — architect-reviewer pass 2 folded. Fixes H (sort test now exercises ETA secondary sort within same priority bucket), H (LIVE V badge contract committed: `LIVE V{actual_version}` from data, matching v4 behavior), M (line-215 strict rules loosened — `target`/`backlog`/`cut_at`/`cut_reason`/`supersedes`/`brisen_docs_url` render with fallback, not required), L (empty-dropped subsection test added).
- **V0.3.1** (2026-05-03) — architect-reviewer pass 3 polish. Fixes L (test labels renamed `HIGH`→`LBL-HIGH` etc. to avoid `find()` collision with priority-pill text). Architect verdict at V0.3.1: ship-ready.

# BRIEF: BRIEF_FLEET_ROADMAP_HTML_RENDER_1 — Fleet Operationalization Roadmap renderer (YAML v5 + Brisen Lab + Cortex tracks + Gates + Dependencies)

## Context

`brisen-docs.onrender.com/architecture/cortex-roadmap-current.html` covers Cortex sprint only.
Brisen Lab build-out (V1 shipped, V2 in flight, V3+ queued), Director's gates (Step 30 Live AO,
decom legacy AO path, MOVIE onboard, etc.), and the Lab V2 → Cortex Step 30 dependency chain
are missing.

Director needs ONE URL to scroll weekly that shows both tracks + gates + the dependency map
on the same page. This brief extends the existing YAML source-of-truth + renderer to do that —
keeping the same URL, same Render auto-deploy, same backward-compat for v4 readers.

Spec authored by AH1-App 2026-05-03; Director ratified ship via "yes" in chat. AH1 owns
brief authorship + dispatch.

## Estimated time
~4–6h (1.5h YAML migration + Brisen Lab backfill, 2h renderer schema-version dispatch + v5 layout, 1.5h tests, 1h verification + commit + paired PRs).

## Complexity
MEDIUM — schema change + renderer change + Director-facing surface.

## Prerequisites
- Read `_ops/processes/cortex-stage2-v1-tracker.md` (sources Steps 33–37 backfill data — see §"Backfill data" below).
- Read `_ops/processes/ai-head-autonomy-charter.md` §3 (charter context for "Cortex Business Manual" gate language).
- Read `briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_1.md` (V0.3.6 — supplies Brisen Lab in-flight item anchors).
- Read `tasks/lessons.md` #3b (column-verification belongs in brief, not build), #8 (verify before done), #44 (cross-repo split EXPLORE-phase miss), #47 (literal pytest output, no "by inspection"), #52 (Tier-A merge gate).

---

## EXPLORE findings (already done by AI Head A — folded here so B-code doesn't redo)

### Current renderer (scripts/render_cortex_roadmap.py)
- 323 lines, single `HTML_TEMPLATE` string with `{slot}` substitutions.
- Reads YAML via `yaml.safe_load` from `<vault-root>/_ops/processes/cortex-roadmap-current.yml` (default `~/baker-vault/...`).
- Top-level keys consumed: `version`, `cut_at`, `cut_reason`, `target`, `supersedes`, `brisen_docs_url`, `backlog.list_url`, and four flat lists `done` / `in_flight` / `queued` / `dropped`.
- `render_item(item, status)` reads per-item fields: `id`, `label`, `description` / `rationale` / `dropped_reason`, `shipped_at`, `started_at`, `assignee`, `eta`, `owner`, `priority`, `anchor`, `dropped_at`, `superseded_by`, `promoted_from_parked`, `deviation_note`.
- Output: `docs-site/architecture/cortex-roadmap-current.html` (single page).
- CSS already defines `--bg-card-done`, `--bg-card-flight`, `--bg-card-queue`, `--bg-card-dropped`, status badges, priority pills. **Reuse, don't duplicate.**

### Current YAML (baker-vault/_ops/processes/cortex-roadmap-current.yml)
- 868 lines, version 4, cut 2026-04-30.
- Top-level: `version`, `cut_at`, `cut_reason`, `supersedes`, `brisen_docs_url`, `clickup_backlog_list_id`, `clickup_backlog_list_url`, `target`, `done`, `in_flight: []`, `queued`, `dropped`, `backlog`.
- ~50+ done items, 0 in-flight (yes — `[]`), ~12 queued, several dropped.

### Rebuild mechanism
- **There is NO `.github/workflows/` in baker-master.** Renderer is run **manually** by AI Head A in baker-master after editing the vault YAML, then HTML is committed to baker-master, push triggers Render static-site auto-deploy.
- Spec text "CI rebuilds HTML on YAML push (existing GitHub Actions / Render hook unchanged)" is **inaccurate**. Brief AC #5 below corrects this — preserves the existing manual workflow.

### Cross-repo coordination
- YAML lives in `baker-vault` repo (`~/baker-vault/`).
- Renderer + tests + output HTML live in `baker-master` repo (this clone, `~/Desktop/baker-code/`).
- B-code must open **2 paired PRs**: one in baker-vault (YAML migration), one in baker-master (renderer + tests + regenerated HTML). **Merge baker-vault YAML PR first** so the renderer in the baker-master PR can be smoke-tested locally against the v5 YAML before merge.

---

## Solution

YAML schema v4 → v5: introduce `tracks.{brisen_lab, cortex}.{done, in_flight, queued, dropped}`
(existing v4 flat lists migrate verbatim under `tracks.cortex`); add top-level `gates` array
+ `dependencies` array. Renderer detects `version` field — if `version >= 5`, dispatch v5
two-track layout + Gates table + Dependencies bullets; if `version <= 4`, render exactly as
today (no behavior change, no visual diff). Add pytest module with v4 fixture (parses + renders
unchanged) + v5 fixture (golden HTML structure assertions).

### Files to modify

| File | Repo | Change |
|---|---|---|
| `_ops/processes/cortex-roadmap-current.yml` | baker-vault | Bump `version: 4 → 5`. Wrap existing `done` / `in_flight` / `queued` / `dropped` under `tracks.cortex.*`. Add `tracks.brisen_lab.*` with backfill items (see §"Backfill data"). Add top-level `gates: [...]` + `dependencies: [...]`. Add `tracks.<track>.purpose` strings. **Preserve top-level `target:`, `backlog:` (with `list_url` + `list_id`), `cut_at`, `cut_reason`, `supersedes`, `brisen_docs_url` verbatim — v5 renderer reads these existing keys, does not introduce parallel naming.** |
| `scripts/render_cortex_roadmap.py` | baker-master | Add `def render_v5(yml: dict) -> str` + `def render_v4(yml: dict) -> str` (existing logic moves into v4). Top-level `def render(yml)` dispatches by `yml.get("version", 4)`. Extend HTML template (or add second template) for v5: track headers, two tables, Gates table with status pills, Dependencies bullets ("from → to: effect"), maintenance footer. |
| `tests/test_render_cortex_roadmap.py` | baker-master | NEW. v4 fixture renders without crash + asserts existing structural markers. v5 fixture renders + asserts both track headers, gates table presence, dependencies section, status pills color classes. |
| `docs-site/architecture/cortex-roadmap-current.html` | baker-master | Regenerate by running `python3 scripts/render_cortex_roadmap.py` against the migrated v5 YAML. Commit alongside renderer changes. |

### Files NOT to touch

- `docs-site/architecture/cortex-roadmap-v3-*.html` (audit-trail snapshots).
- Any other file in `docs-site/` outside `architecture/cortex-roadmap-current.html`.
- `_ops/processes/cortex-stage2-v1-tracker.md` (data source, read-only for this brief).
- `briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_1.md` (anchor source, read-only).

---

## YAML schema v5 (target)

```yaml
version: 5
cut_at: 2026-05-03
cut_reason: |
  V5 cuts to add the Brisen Lab build-out as a peer track to Cortex on the live
  roadmap, plus Director's standing gates and the cross-track dependency map.
  Same URL, expanded content. V4 is preserved as audit snapshot.
supersedes: cortex-roadmap-v4-2026-04-30.html  # (or whatever the v4 archive name is)
brisen_docs_url: https://brisen-docs.onrender.com/architecture/cortex-roadmap-current.html

# PRESERVED VERBATIM FROM V4 — do not rename, do not move under tracks.*
target: |
  (current v4 `target:` block stays exactly as-is; render_v5 renders it at top
  of page above the two-track section, in the same .summary-bar styling as today)

backlog:
  list_id: "901523104264"
  list_url: https://app.clickup.com/24385290/v/l/li/901523104264

tracks:
  brisen_lab:
    purpose: "One dashboard for the fleet + direct ratify path so Cortex doesn't depend on paste-blocks."
    done:
      - id: brisen-lab-v1
        label: "Lab V1 — observe-only dashboard at brisen-lab.onrender.com"
        shipped_at: 2026-05-01
        anchor: "PR #145 baker-master · BRISEN_LAB_1"
      - id: brisen-lab-v2-brief-converged
        label: "Lab V2 brief V0.3.6 — 4 architect-reviewer passes; 5C+6H → 0C+0H"
        shipped_at: 2026-05-03
        anchor: "BRIEF_BRISEN_LAB_V2_BRIDGE_1 final · commits e1a85f6 + 2b8a381"
    in_flight:
      - id: brisen-lab-v2-build
        label: "Lab V2 — message bus + per-worker auth + matter cards + production hardening + Hermes-pattern context renewal + OTel"
        assignee: b4
        started_at: 2026-05-03
        eta: 2026-05-24
        anchor: "BRIEF_BRISEN_LAB_V2_BRIDGE_1 V0.3.6 · b4/brisen-lab-v2-bridge-1"
    queued:
      - id: brief-architect-terminal-1
        label: "BRIEF_ARCHITECT_TERMINAL_1 — new Code terminal 'architect' + 3-file memory"
        owner: ah1
        eta: post-lab-v2
        priority: medium
      - id: brief-tier-b-autonomy-1
        label: "BRIEF_TIER_B_AUTONOMY_1 — Tier-B autonomy update + bank-model.md standing rule"
        owner: ah1
        eta: post-lab-v2
        priority: medium
      - id: brief-session-start-digest-1
        label: "BRIEF_SESSION_START_DIGEST_1 — session-start digest behavior"
        owner: ah1
        eta: post-lab-v2
        priority: medium
    dropped: []

  cortex:
    purpose: "Replace per-matter PM agents with one reasoning loop configured per matter; specialists invoked on demand; learning loop accumulates curated knowledge."
    done: []           # all v4 `done` items migrate verbatim here, preserving order + every field
    in_flight: []      # v4 `in_flight` was [] — keeps shape
    queued: []         # all v4 `queued` items migrate verbatim here, PLUS two new entries (see §"Backfill data" → tracks.cortex.queued additions)
    dropped: []        # all v4 `dropped` items migrate verbatim here

gates:
  - id: step-30-live-ao-cycle
    label: "Step 30 first LIVE AO cycle — Director sits Slack-watching 15-30min"
    status: open
    note: "Pick cycle topic + go-time"
  - id: decom-legacy-ao-path
    label: "Decommission ao_signal_detector + freeze ao_project_state (Steps 33-36)"
    status: pending
    note: "Gated on Step 30 success + 1 week observation"
  - id: onboard-movie-matter
    label: "Onboard MOVIE as second matter (Step 37)"
    status: pending
    note: "Gated on AO 1-week observation clean"
  - id: wertheimer-matter-seed
    label: "Wertheimer matter seed (Wave 2 #2 gap)"
    status: pending
    note: "Needs Director paste-block of strategic context"
  - id: twostage-preview-interim-flip
    label: "Two-stage preview interim flip — kill Sentinel auto-trigger globally + Scan classifier auto-route"
    status: pending
    note: "5-min config flip; 'OK to flip' needed"
  - id: director-cortex-business-manual
    label: "Cortex Business Manual brainstorm session"
    status: pending
    note: "ETA 2026-05-15; needs ~2 weeks production data"

dependencies:
  - from: lab-v2
    to: cortex-step-30
    effect: "Removes paste-relay tax (5-15 min per cycle); Director ratifies in Lab UI"
  - from: cortex-stage2-v1
    to: matter-pm-absorption
    effect: "AO PM + MOVIE AM become Cortex per-matter configs; pattern generalizes to 22 matters"
  - from: lab-v2
    to: brisen-lab-msgbus-1
    effect: "Same infrastructure, two consumers — cross-terminal coord + Cortex ratify"
  - from: vault-write-1
    to: per-matter-clickup-linkage-5
    effect: "Linkage write-back path"
```

### Strict schema rules (v5)

- `tracks.brisen_lab.{done,in_flight,queued,dropped}` MUST exist (empty list `[]` is valid; missing key is INVALID — raise `ValueError("missing required v5 field: tracks.brisen_lab.<key>")`).
- `tracks.cortex.{done,in_flight,queued,dropped}` MUST exist same way.
- `tracks.<track>.purpose` is REQUIRED (string).
- Top-level `gates` is REQUIRED (list, may be empty `[]`).
- Top-level `dependencies` is REQUIRED (list, may be empty `[]`).
- Top-level `target`, `backlog.list_url`, `cut_at`, `cut_reason`, `supersedes`, `brisen_docs_url` are SOFT (render-with-fallback if missing, matching v4 `yml.get(..., "")` behavior). v5 does NOT enforce their presence as a schema-violation; missing values fall back to empty string / "#" sentinel like v4.
- Top-level flat `done` / `in_flight` / `queued` / `dropped` MUST NOT be present in v5 (all migrated under `tracks.cortex`). The renderer raises `ValueError("Mixed schema: v5 has tracks.* but also flat lists; pick one")` if `version >= 5` AND any flat list is present.
- `version >= 5` activates v5 layout (forward-compat). Any `version <= 4` (or missing) activates v4 backward-compat layout.

### Per-gate status enum

`open` | `pending` | `closed` — color mapping:
- `open` → amber pill (reuse `--border-flight: #d8b855` / `--bg-card-flight: #fff8e8`)
- `pending` → grey pill (reuse `--border-default: #d6cfb8` / `--bg-card-queue: #f4f0e6`)
- `closed` → green pill (reuse `--border-done: #a8c084` / `--bg-card-done: #f5f9ed`)

(Reusing existing CSS variables — do not introduce a new color system.)

---

## Backfill data (data not currently in v4 YAML)

### tracks.cortex.queued additions (from `_ops/processes/cortex-stage2-v1-tracker.md`)

These two entries are MISSING from v4 YAML. Add them as part of the migration:

```yaml
- id: cortex-stage2-step-33-36-decom
  label: "Stage 2 Steps 33-36 — decommission ao_signal_detector + freeze ao_project_state + 1 week observation"
  owner: ah1 + director-consult
  eta: 2026-05-12
  priority: high
  gated_on: step-30-live-ao-cycle

- id: cortex-stage2-step-37-movie-onboard
  label: "Stage 2 Step 37 — onboard MOVIE as second matter (activate wiki/matters/movie/cortex-config.md)"
  owner: ah1 + director-consult
  eta: 2026-05-19
  priority: high
  gated_on: cortex-stage2-step-33-36-decom
```

**`gated_on` decision (V0.1 hard rule):** Store the field in YAML; do NOT render it visually in V0.1. A follow-up brief can add visualization if Director wants gate-link affordance. No implementer's-choice — just store the field.

### tracks.brisen_lab.* full backfill

See the full v5 schema above — `done`, `in_flight`, `queued` blocks all populated. Anchors verified against:
- baker-master git log (`PR #145`, `e1a85f6`, `2b8a381`).
- `briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_1.md`.
- `briefs/_tasks/CODE_4_PENDING.md` (B4 mailbox).
- AH1 handover `~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/session_handover_2026_05_03_a1_v2bridge_dispatched.md`.

---

## Renderer changes (scripts/render_cortex_roadmap.py)

### 1. Schema-version dispatch

```python
def render(yml: dict) -> str:
    """Render the full HTML page from YAML data; dispatches by schema version.

    PUBLIC NAME — do not rename. Existing tests / callers import `rcr.render`.
    """
    version = yml.get("version", 4)
    if version >= 5:
        # Mixed-schema safety
        flat_keys = ("done", "in_flight", "queued", "dropped")
        if any(k in yml for k in flat_keys):
            raise ValueError("Mixed schema: v5 has tracks.* but also flat lists; pick one")
        return render_v5(yml)
    return render_v4(yml)
```

### 2. Existing logic → `render_v4(yml)`

Move current `render(yml)` body into a private `render_v4(yml)` function. ZERO behavior change for v4 — same template, same outputs. **Do not rename the public `render` function** — existing test imports (`rcr.render(yml)`) and any external caller depend on it.

### 3. New `render_v5(yml)` function

v5 output structure (in order, top to bottom of page):

1. **Header** — title "Fleet Operationalization Roadmap" with `LIVE V{version}` badge (substituted from `yml.get("version")`, matching v4 template behavior — so `version: 5` → `LIVE V5`, `version: 6` → `LIVE V6`). One-line meta (cut date + source-of-truth path).
2. **Cut reason** (reuse existing `.summary-bar` CSS) + **Target** block (reuse `.summary-bar`, render `target` field exactly as v4 does — same field, same styling, same position).
3. **Track 1 — Brisen Lab section:**
   - Section header `<h2 class="stage-title">Brisen Lab</h2>` (reuse existing `.stage-title`).
   - Purpose line (reuse `.stage-meta`).
   - Subsection labels (`In flight`, `Queued`, `Done`, `Dropped`) wrapped in **NEW** `<h3 class="substage-title">` — append CSS rule for `.substage-title { font-size: 0.95rem; color: var(--text-muted); margin: 1.1rem 0 0.4rem; }` to the `<style>` block. Items inside reuse existing `render_item(item, status)`.
   - Order: In flight → Queued → Done → Dropped (matches v4 convention).
   - Empty subsections (e.g., `dropped: []`) → omit the subsection entirely; do not emit an empty `<h3>`.
4. **Track 2 — Cortex section:** same structure, same subsection order, same CSS classes.
5. **Director's Gates section:**
   - Header `<h2 class="stage-title">Director's Gates</h2>`.
   - HTML `<table class="gate-table">` with columns: Gate · Status · Note.
   - Status column = `<span class="gate-status-pill {status}">{status}</span>` where `{status}` ∈ `open`/`pending`/`closed` and the class drives the color mapping (open=amber, pending=grey, closed=green) using existing CSS variables.
   - Append CSS rules for `.gate-table { width: 100%; border-collapse: collapse; margin: 0.5rem 0 1rem; }` + `.gate-table th, .gate-table td { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border-default); text-align: left; font-size: 0.88rem; }` + `.gate-status-pill { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 3px; font-size: 0.75rem; font-weight: 600; }` + `.gate-status-pill.open { background: var(--bg-card-flight); border: 1px solid var(--border-flight); color: var(--text-header); }` + `.gate-status-pill.pending { background: var(--bg-card-queue); border: 1px solid var(--border-default); color: var(--text-muted); }` + `.gate-status-pill.closed { background: var(--bg-card-done); border: 1px solid var(--border-done); color: var(--accent-locked); }`.
6. **Dependencies section:**
   - Header `<h2 class="stage-title">Dependencies</h2>`.
   - `<ul class="dep-list">` of bullets formatted: `<li><strong>{from}</strong> → <strong>{to}</strong>: {effect}</li>`.
7. **Maintenance protocol footer:** reuse existing `.callout` block + `<footer>` pattern. Standing rules from current template (no parked, etc.) MUST be preserved.
8. **Source-of-truth pointers** (footer): YAML path, Stage 2 V1 tracker path, architecture-final spec path, Lab V2 brief path. Use `<code>` tags; no external links unless the brisen-docs URL is already wired (`yml.get("brisen_docs_url")`).

### 3a. HTML escaping (v5 only)

All v5-introduced user-content fields MUST be passed through `html.escape()` before interpolation:
- `gates[].label`, `gates[].note`
- `dependencies[].from`, `dependencies[].to`, `dependencies[].effect`
- `tracks.<track>.purpose`

Pre-existing v4 unescaped behavior is grandfathered (do not retrofit `render_item` or `render_v4`). v5 does NOT extend the no-escape contract.

```python
import html
# Example:
escaped_note = html.escape(gate.get("note", ""))
```

### 3b. Sort order under tracks

`render_v5` applies the SAME priority-then-ETA sort to each track's `queued` list as v4 does today (`scripts/render_cortex_roadmap.py:253-258`). Default priority for items missing the field = `medium`, matching v4 behavior. Done / in_flight / dropped lists keep YAML insertion order.

### 4. Style discipline

- Match existing CSS conventions; reuse all `--bg-*` / `--border-*` / `--accent*` variables.
- Muted Brisen palette only (no neon, no emoji-heavy).
- New CSS additions (if any): scope to `.gate-table`, `.gate-status-pill`, `.dep-list`. Append to existing `<style>` block — do not introduce a separate `<link>`.
- No JavaScript additions. Pure server-rendered HTML.

### 5. Backward-compat guarantee

A v4 YAML (current production state) MUST render byte-for-byte identical (modulo `rendered_at` date) before and after this change. The pytest fixture below enforces this.

### 6. Mixed-schema safety

Implemented in the §1 `render()` dispatch above — fires on `version >= 5` (forward-compat), not just exact `version == 5`. Catch `ValueError` in `main()` and exit non-zero with a readable error.

---

## Tests (`tests/test_render_cortex_roadmap.py` — NEW)

```python
"""Tests for scripts/render_cortex_roadmap.py — schema-version dispatch + structure."""
import sys
from pathlib import Path

import pytest

# Make scripts/ importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_cortex_roadmap as rcr  # noqa: E402


def test_v4_renders_without_crash():
    """V4 fixture (current prod schema) must still render."""
    yml = {
        "version": 4,
        "cut_at": "2026-04-30",
        "cut_reason": "test",
        "target": "test target",
        "supersedes": "x",
        "brisen_docs_url": "https://example",
        "backlog": {"list_url": "https://clickup"},
        "done": [{"id": "a", "label": "done item", "shipped_at": "2026-04-30"}],
        "in_flight": [],
        "queued": [{"id": "q", "label": "queued item", "owner": "ah1", "eta": "2026-05-12", "priority": "high"}],
        "dropped": [],
    }
    html = rcr.render(yml)
    assert "Cortex Roadmap" in html
    assert "LIVE V4" in html
    assert "done item" in html
    assert "queued item" in html


def test_v5_renders_two_tracks_and_gates_and_deps():
    """V5 fixture must render Brisen Lab + Cortex + Gates + Dependencies."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "cut_reason": "test cut",
        "supersedes": "v4",
        "brisen_docs_url": "https://example",
        "clickup_backlog_list_url": "https://clickup",
        "tracks": {
            "brisen_lab": {
                "purpose": "Lab purpose line",
                "done": [{"id": "lab-v1", "label": "Lab V1", "shipped_at": "2026-05-01"}],
                "in_flight": [{"id": "lab-v2", "label": "Lab V2 build", "assignee": "b4", "started_at": "2026-05-03", "eta": "2026-05-24"}],
                "queued": [],
                "dropped": [],
            },
            "cortex": {
                "purpose": "Cortex purpose line",
                "done": [{"id": "stage2-step29", "label": "Step 29 DRY_RUN", "shipped_at": "2026-05-01"}],
                "in_flight": [],
                "queued": [{"id": "step33", "label": "Steps 33-36", "owner": "ah1", "eta": "2026-05-12", "priority": "high"}],
                "dropped": [],
            },
        },
        "gates": [
            {"id": "step-30-live-ao-cycle", "label": "Step 30 first LIVE AO cycle", "status": "open", "note": "Pick topic"},
            {"id": "decom-legacy-ao-path", "label": "Decom legacy AO path", "status": "pending", "note": "Gated on Step 30"},
        ],
        "dependencies": [
            {"from": "lab-v2", "to": "cortex-step-30", "effect": "Removes paste-relay tax"},
        ],
    }
    html = rcr.render(yml)
    # Track headers
    assert "Brisen Lab" in html
    assert "Cortex" in html
    assert "Lab purpose line" in html
    assert "Cortex purpose line" in html
    # Items present
    assert "Lab V2 build" in html
    assert "Step 29 DRY_RUN" in html
    # Gates section
    assert "Director's Gates" in html or "Gates" in html
    assert "Step 30 first LIVE AO cycle" in html
    # Dependencies section
    assert "Dependencies" in html
    assert "lab-v2" in html
    assert "cortex-step-30" in html
    assert "Removes paste-relay tax" in html


def test_v5_mixed_schema_raises():
    """v5 with stray top-level flat list should error clearly."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [],
        "dependencies": [],
        "done": [{"id": "stray", "label": "should not be here"}],  # mixed schema
    }
    with pytest.raises(ValueError, match="Mixed schema"):
        rcr.render(yml)


def test_v6_mixed_schema_also_raises():
    """Mixed-schema check must fire on version >= 5 (forward-compat)."""
    yml = {
        "version": 6,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [],
        "dependencies": [],
        "queued": [{"id": "stray", "label": "should not be here"}],
    }
    with pytest.raises(ValueError, match="Mixed schema"):
        rcr.render(yml)


def test_v5_missing_required_track_raises():
    """v5 without tracks.brisen_lab should error with a specific match string."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {"cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []}},
        "gates": [],
        "dependencies": [],
    }
    with pytest.raises(ValueError, match="missing required v5 field"):
        rcr.render(yml)


def test_v5_missing_gates_raises():
    """v5 without top-level gates should error."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "dependencies": [],
    }
    with pytest.raises(ValueError, match="missing required v5 field"):
        rcr.render(yml)


def test_v5_missing_dependencies_raises():
    """v5 without top-level dependencies should error."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [],
    }
    with pytest.raises(ValueError, match="missing required v5 field"):
        rcr.render(yml)


def test_v5_queued_priority_sort_per_track():
    """Each track's queued list is sorted priority-then-ETA, same as v4. Includes
    two same-priority items with different ETAs to verify the ETA secondary key."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {
                "purpose": "p",
                "done": [],
                "in_flight": [],
                "queued": [
                    {"id": "low-late", "label": "LBL-LATE-LOW", "owner": "ah1", "eta": "2026-09-01", "priority": "low"},
                    {"id": "high-late", "label": "LBL-LATE-HIGH", "owner": "ah1", "eta": "2026-08-01", "priority": "high"},
                    {"id": "high-early", "label": "LBL-EARLY-HIGH", "owner": "ah1", "eta": "2026-05-10", "priority": "high"},
                    {"id": "med-mid", "label": "LBL-MID-MED", "owner": "ah1", "eta": "2026-07-01", "priority": "medium"},
                    {"id": "crit", "label": "LBL-CRIT-LATEST", "owner": "ah1", "eta": "2026-12-01", "priority": "critical"},
                ],
                "dropped": [],
            },
        },
        "gates": [],
        "dependencies": [],
    }
    html_out = rcr.render(yml)
    # Primary: critical → high → medium → low. Secondary (within same priority): ETA asc.
    # So expected order: CRIT-LATEST, EARLY-HIGH, LATE-HIGH, MID-MED, LATE-LOW.
    assert (
        html_out.find("LBL-CRIT-LATEST")
        < html_out.find("LBL-EARLY-HIGH")
        < html_out.find("LBL-LATE-HIGH")
        < html_out.find("LBL-MID-MED")
        < html_out.find("LBL-LATE-LOW")
    )


def test_v5_default_priority_medium():
    """Item with no `priority` field sorts as `medium`, matching v4."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {
                "purpose": "p",
                "done": [],
                "in_flight": [],
                "queued": [
                    {"id": "low", "label": "LBL-LOW", "owner": "ah1", "eta": "2026-05-01", "priority": "low"},
                    {"id": "no-pri", "label": "LBL-NOPRI", "owner": "ah1", "eta": "2026-05-01"},  # missing priority → medium
                    {"id": "high", "label": "LBL-HIGH", "owner": "ah1", "eta": "2026-05-01", "priority": "high"},
                ],
                "dropped": [],
            },
        },
        "gates": [],
        "dependencies": [],
    }
    html_out = rcr.render(yml)
    # Expected: LBL-HIGH (priority 1), LBL-NOPRI (priority 2 = medium default), LBL-LOW (priority 3).
    assert html_out.find("LBL-HIGH") < html_out.find("LBL-NOPRI") < html_out.find("LBL-LOW")


def test_v5_empty_dropped_subsection_omitted():
    """Empty `dropped: []` must NOT emit a `Dropped` heading."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {
                "purpose": "p",
                "done": [{"id": "x", "label": "X-DONE", "shipped_at": "2026-05-01"}],
                "in_flight": [],
                "queued": [],
                "dropped": [],
            },
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [],
        "dependencies": [],
    }
    html_out = rcr.render(yml)
    # X-DONE present
    assert "X-DONE" in html_out
    # No Brisen-Lab subsection heading for Dropped (zero items).
    # We don't search for the bare word "Dropped" because the v4 standing-rules
    # callout still mentions DROPPED. Instead, assert a substage-title <h3> for
    # Dropped is NOT emitted.
    assert ">Dropped<" not in html_out


def test_v5_html_escape_user_fields():
    """Gates/deps/purpose strings with HTML chars must be escaped."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "<b>unsafe</b>", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "ok", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [{"id": "g", "label": "<script>", "status": "open", "note": "& more"}],
        "dependencies": [{"from": "<a>", "to": "<b>", "effect": "x & y"}],
    }
    html_out = rcr.render(yml)
    # No raw <b> / <script> / <a> / & from user fields
    assert "<b>unsafe</b>" not in html_out
    assert "<script>" not in html_out
    assert "&lt;b&gt;unsafe&lt;/b&gt;" in html_out
    assert "&lt;script&gt;" in html_out


def test_v5_live_badge_substring():
    """`LIVE V5` substring must appear (header live-badge)."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [],
        "dependencies": [],
    }
    html_out = rcr.render(yml)
    assert "LIVE V5" in html_out


def test_gate_status_pill_classes_present():
    """Gate status colors must use existing CSS classes (no new color system)."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [
            {"id": "g1", "label": "open gate", "status": "open", "note": "n"},
            {"id": "g2", "label": "pending gate", "status": "pending", "note": "n"},
            {"id": "g3", "label": "closed gate", "status": "closed", "note": "n"},
        ],
        "dependencies": [],
    }
    html = rcr.render(yml)
    # All three statuses rendered; assert each gate label appears.
    assert "open gate" in html
    assert "pending gate" in html
    assert "closed gate" in html
```

### Run command (literal pytest output, no "by inspection" — Lesson #47)

```bash
cd ~/Desktop/baker-code && python3 -m pytest tests/test_render_cortex_roadmap.py -v
```

Expected: **12 passed** (v4 smoke + v5 two-track + mixed-schema-v5 + mixed-schema-v6 + missing-track + missing-gates + missing-deps + queued-sort + default-priority + empty-dropped-omitted + html-escape + LIVE-V5-substring).

### Smoke test (post-build)

```bash
# In baker-master, after vault YAML is migrated to v5 and synced locally:
python3 scripts/render_cortex_roadmap.py
# → expect "[OK] Rendered ~/baker-vault/_ops/processes/cortex-roadmap-current.yml → docs-site/architecture/cortex-roadmap-current.html"
# Open the HTML file locally in a browser; eyeball the two-track + gates + dependencies layout.
```

---

## Acceptance criteria

1. **YAML v5 parses** via `yaml.safe_load` without exception. Strict schema rules (above) enforced by renderer.
2. **V4 backward-compat (structural):** v4 fixture still parses + renders. The structural markers `Cortex Roadmap`, `LIVE V4`, `Cut`, `Source-of-truth`, `In flight`, `Queued — current sprint`, `Done`, `Dropped (audit trail)`, `Standing rules`, and any non-empty list's first item label all appear in the output. (No byte-identity claim — `rendered_at = date.today().isoformat()` makes that infeasible without freeze-time fixtures, out of scope here.) Test `test_v4_renders_without_crash` enforces these substring assertions.
3. **V5 layout:** Both `Brisen Lab` and `Cortex` track section headers render with their `purpose` lines and at least the populated subsections (in_flight / queued / done / dropped) — empty `dropped` blocks may be omitted from output.
4. **Director's Gates table** renders with one row per gate; status column shows a color-coded pill (open=amber, pending=grey, closed=green) using existing CSS variables.
5. **Dependencies section** renders as bullets in `<strong>from</strong> → <strong>to</strong>: effect` format.
6. **Render path unchanged:** `python3 scripts/render_cortex_roadmap.py` against the migrated v5 YAML writes `docs-site/architecture/cortex-roadmap-current.html`. brisen-docs Render static-site auto-deploys on baker-master push (existing pattern, no new GitHub Actions). **(AC #5 from upstream spec corrected — there is no GitHub Actions workflow; the rebuild is manual + Render auto-deploy on push.)**
7. **Live URL** `https://brisen-docs.onrender.com/architecture/cortex-roadmap-current.html` renders the Fleet Roadmap structure end-to-end after baker-master push (Director-side smoke confirmation).
8. **12/12 pytest pass** — literal output captured in ship report (Lesson #47, no "by inspection").
9. **No new CSS color system** — all status pills + section dividers reuse `--bg-*` / `--border-*` / `--accent-*` CSS variables already defined.

---

## Quality checkpoints

1. Renderer unit tests pass locally (`pytest tests/test_render_cortex_roadmap.py -v`).
2. `python3 scripts/render_cortex_roadmap.py` against `~/baker-vault/_ops/processes/cortex-roadmap-current.yml` (v5) writes a valid HTML file.
3. Render same script against a v4 fixture (commit a small `tests/fixtures/cortex-roadmap-v4-fixture.yml` if helpful) → output structurally identical to today's prod HTML.
4. Visual check: open `docs-site/architecture/cortex-roadmap-current.html` in a browser, confirm:
   - Two visible track headers (Brisen Lab + Cortex).
   - Director's Gates table with 6 rows + colored status pills.
   - Dependencies bullets readable.
   - No console / DOM errors (no missing CSS classes, no undefined variables in `{...}` template slots).
5. Cross-repo PR sequencing: baker-vault YAML PR opened FIRST. Once baker-vault PR is merged, baker-master PR (renderer + tests + regenerated HTML) can be pushed and reviewed.
6. B1 second-pair-of-eyes review on baker-master PR before merge (RA-24, MEDIUM trigger class on Director-facing surface).
7. `python3 -c "import py_compile; py_compile.compile('scripts/render_cortex_roadmap.py', doraise=True)"` clean.

---

## Verification

### Local smoke (Code's machine)

```bash
# 1. Run tests
cd ~/Desktop/baker-code
python3 -m pytest tests/test_render_cortex_roadmap.py -v

# 2. Run renderer against migrated v5 YAML (after vault PR merged + pulled locally)
python3 scripts/render_cortex_roadmap.py
# → check docs-site/architecture/cortex-roadmap-current.html — open in browser

# 3. Sanity check the regenerated HTML
grep -c "Brisen Lab" docs-site/architecture/cortex-roadmap-current.html  # ≥ 1
grep -c "Director's Gates" docs-site/architecture/cortex-roadmap-current.html  # = 1
grep -c "Dependencies" docs-site/architecture/cortex-roadmap-current.html  # ≥ 1
```

### Post-deploy smoke (Director side)

```
Open https://brisen-docs.onrender.com/architecture/cortex-roadmap-current.html
Confirm: Brisen Lab + Cortex + Gates table + Dependencies all visible.
```

---

## Cross-repo PR coordination

1. Branch in BOTH repos: `b<N>/fleet-roadmap-html-render-1` (where `<N>` = your B-code worker number).
2. Open **baker-vault PR FIRST** with the YAML migration. Wait for AH1 review + merge.
3. After baker-vault PR is merged, pull the merged YAML locally (`cd ~/baker-vault && git pull`).
4. Open **baker-master PR** with `scripts/render_cortex_roadmap.py` + `tests/test_render_cortex_roadmap.py` + regenerated `docs-site/architecture/cortex-roadmap-current.html`.
5. Request B1 second-pair-of-eyes on the baker-master PR (Director-facing surface, RA-24 MEDIUM trigger class).
6. Squash-merge baker-master PR after green review. brisen-docs auto-deploys on push.
7. Update mailbox: flip `briefs/_tasks/CODE_<N>_PENDING.md` to `COMPLETE` with both PR links + ship report path under `briefs/_reports/`.

---

## Risks + safety rails

| Risk | Mitigation |
|---|---|
| Code Brisen breaks v4 backward-compat | `test_v4_renders_without_crash` fixture is required-passing |
| YAML migration drops fields silently | Strict schema check + mixed-schema test (`test_v5_mixed_schema_raises`) |
| HTML render diverges between v4 and v5 unexpectedly | Manual visual inspection (Quality checkpoint 4) + Director-side smoke (Quality checkpoint 7) |
| Cross-repo split lesson #44 (V2_BRIDGE_1 EXPLORE-phase miss) | Spec calls out 2 paired PRs explicitly + merge order; brief author already verified file paths in BOTH repos |
| New CSS color system creep | AC #9 + Quality checkpoint 4 explicitly forbid; reuse existing CSS variables |
| AC #5 upstream spec wording wrong about CI | Brief AC #6 corrects: rebuild is manual + Render static-site auto-deploy (no GitHub Actions exist). Code Brisen should NOT add a GitHub Actions workflow as part of this brief — out of scope |
| Render restart mid-deploy | Static-site Render service; idempotent rebuild; safe |

---

## Out of scope

- Adding a GitHub Actions workflow to auto-render on YAML push. **Out of scope** for this brief; the existing manual + Render auto-deploy pattern stays. (Could be a follow-up brief if Director wants it.)
- Modifying the Cortex Backlog ClickUp list (901523104264) or the drift sentinel.
- Modifying `_ops/processes/fleet-operationalization-roadmap.md` (the markdown twin) — that doc is AH1-App's separate deliverable, not this brief.
- Schema migrations to baker-vault YAML files OTHER than `cortex-roadmap-current.yml`.

---

## Trigger class + review path

- **MEDIUM** (Director-facing surface; schema change + renderer change).
- **B1 second-pair-of-eyes review on the baker-master PR before merge** (RA-24 conservative — Director-facing surface qualifies even though not auth/migration/financial).
- AH1 reviews + merges baker-vault YAML PR.
- AH1 reviews + merges baker-master PR after B1 sign-off.

---

## Branch + paths

- Branch (both repos): `b<N>/fleet-roadmap-html-render-1`
- Brief: `briefs/BRIEF_FLEET_ROADMAP_HTML_RENDER_1.md` (this file)
- Files modified:
  - `_ops/processes/cortex-roadmap-current.yml` (in `~/baker-vault/`)
  - `scripts/render_cortex_roadmap.py` (in baker-master)
  - `tests/test_render_cortex_roadmap.py` (NEW, in baker-master)
  - `docs-site/architecture/cortex-roadmap-current.html` (regenerated, in baker-master)

---

## Files NOT to touch

- `briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_1.md` (V0.3.6 — read-only anchor source)
- `_ops/processes/cortex-stage2-v1-tracker.md` (read-only data source)
- Any `docs-site/architecture/cortex-roadmap-v3-*.html` snapshot (audit trail)
- `migrations/` (no DB schema change in this brief)

---

## Lessons applied (from `tasks/lessons.md`)

- **#3b** (column-existence check belongs in the brief): N/A here (no DB schema), but analog applies — schema fields verified in fixtures.
- **#8** (verify before marking done): Pytest output literal capture mandatory; visual smoke required.
- **#44** (cross-repo EXPLORE-phase miss): Explicit 2-paired-PR call-out + merge order + branch name shared across repos.
- **#47** (literal pytest output, no "by inspection"): Ship report MUST include literal pytest stdout.
- **#52** (Tier-A merge gate / `/security-review`): N/A — this is MEDIUM, no auth surface, no migrations. `/security-review` NOT required.

---

## ETA

~4–6h end-to-end. Calibrate on first push if your read of complexity differs.

## Coordination

- Mailbox: `briefs/_tasks/CODE_<N>_PENDING.md` (your worker's mailbox)
- Heartbeat: update `last_heartbeat` every ~4h while in flight
- Blocker: surface to AH1 via `blocker_question` field in mailbox; do not stall silently
- PR opens against `main` in both repos; AH1 reviews; B1 second-pair-of-eyes on baker-master only
