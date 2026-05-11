# BRIEF: COCKPIT_SIDEBAR_LEGACY_SLUG_ALIAS_FIX_1 — Cockpit sidebar item counts via legacy-slug alias fold

**Phase:** Phase-2 follow-on to PR #180 (CORTEX_COCKPIT_SIDEBAR_WIRING). Sidebar wiring shipped + canonical labels rendering; this brief closes the count-attribution gap.
**Estimated time:** ~3-4h
**Complexity:** Low
**Prerequisites:**
- PR #180 merged (`901c66d`) — cockpit sidebar reads `_priorities.yml` + `slug_registry.describe()` already in production.
- `kbl/slug_registry.py` singleton operational on Render (verified via live `priorities_version: 1` response).
- `BAKER_VAULT_PATH` set on Render `baker-master` (verified — priorities are loading).

---

## Context

Director observed 2026-05-11: every project in the left sidebar "Project" section displays `0` items.

Live API probe of `https://baker-master.onrender.com/api/dashboard/matters-summary`:
- `priorities_version: 1`, `fallback_mode: null` — sidebar wiring is healthy.
- Canonical priority projects (`hagenauer-rg7`, `mo-vie-am`, `ao-pm`, `mrci`, `lilienmatt`, `annaberg`, `aukera`, …) all show `item_count: 0`.
- Meanwhile, 299 pending alerts sit under legacy slugs that the priority-overlay can't match:

| Legacy alert slug (raw) | Items | New 24h | Canonical target |
|---|---:|---:|---|
| `movie_am` | 136 | 45 | `mo-vie-am` (alias registered in `slugs.yml:38`) |
| `ao_pm` | 100 | 35 | `ao-pm` (or `ao` — verify) |
| `_ungrouped` | 28 | 2 | (stays general inbox) |
| `Austrian Tax & Corporate` | 8 | 2 | `austrian-tax-corp` (free-text, NOT in slugs.yml) |
| `Oskolkov-RG7` | 8 | 2 | `hagenauer-rg7` (matter dispute) — verify with Director if ambiguous |
| `Swiss Tax & Banking` | 3 | 0 | `swiss-tax-banking` (free-text) |
| `Family Wealth Overview` | 3 | 0 | `family-wealth-overview` (free-text) |
| `Brisen-AI` | 2 | 1 | `brisen-ai` (free-text) |
| `German Property Tax` | 2 | 1 | `german-property-tax` (free-text) |
| `Mandarin Oriental Sales` | 2 | 0 | `mo-vie-exit` (already aliased? verify) |
| `Cap Ferrat Villa` | 1 | 0 | `cap-ferrat` (alias registered) |
| `Kempinski Kitzbühel Acquisition` | 1 | 0 | `kitz-kempinski` (free-text — Director-dismissed Q34, route to inbox) |
| `Cross-Border Structuring` | 1 | 0 | `cross-border-structuring` (free-text) |
| `Hagenauer` | 1 | 0 | `hagenauer-rg7` (alias registered, `slugs.yml:28`) |
| `Cyprus Holding Structure` | 1 | 0 | `cyprus-holding` (free-text) |
| `Campus Schlueterstrasse Hamburg` | 1 | 0 | `campus-schluterstrasse` (free-text) |
| `Owner's Lens` | 1 | 0 | `owners-lens` (free-text) |

Most are aliases already registered in `baker-vault/slugs.yml` but the dashboard endpoint doesn't apply normalization on the alert side. The rest (~10 free-text labels) need a small server-side alias map.

Director-ratified Option 1 (lightweight, no DB migration, no slugs.yml changes) on 2026-05-11.

---

## Problem

`get_matters_summary()` at `outputs/dashboard.py:3949` aggregates pending alerts by raw `alerts.matter_slug` then attempts to attribute counts to canonical priority slugs via the wrong-direction normalize lookup at line 3998-3999:

```python
norm = slug_normalize(p.slug) or p.slug        # p.slug is already canonical → norm == p.slug
alert = alerts_by_slug.get(norm) or alerts_by_slug.get(p.slug) or {}   # both lookups miss
```

`p.slug` is the priority-side canonical slug (e.g. `mo-vie-am`). `alerts_by_slug` is keyed by the raw alert-side slug (e.g. `movie_am`). Normalizing the priority side doesn't help — it's already canonical. The lookup never hits.

Result: every priority row gets `item_count=0`, and every alert row falls into the inbox bucket via the `slug not in priority_slugs` branch at line 4015.

---

## Current state

### Backend: `outputs/dashboard.py:3949-4075`

`GET /api/dashboard/matters-summary`:
1. Load priorities (canonical slugs).
2. Aggregate alerts SQL grouped by raw `a.matter_slug` → `alerts_by_slug` dict (raw → row).
3. For each priority, attempt `alerts_by_slug.get(slug_normalize(p.slug) or p.slug)` → MISS (wrong direction).
4. Walk `alerts_by_slug` again, anything not in `priority_slugs` → inbox bucket (catches everything).

### Slug registry (`kbl/slug_registry.py`)

- `normalize(raw)` (`kbl/slug_registry.py:195`) — case-insensitive whitespace-collapsed alias lookup. Returns canonical slug or `None`.
- `_normalize_key(raw)` (`kbl/slug_registry.py:53`) — `" ".join(raw.lower().split())`. So `"Austrian Tax & Corporate"` normalizes to `"austrian tax & corporate"` — would need to be an explicit alias entry, which slugs.yml does not contain.
- Aliases verified in `slugs.yml`: `mo-vie-am` includes `"movie_am"`, `"movie-am"`; `hagenauer-rg7` includes `"hagenauer"`, `"rg7"`; `cap-ferrat` includes `"villa-cap-ferrat"`.

### Verification probe run 2026-05-11

```bash
curl -s -H "X-Baker-Key: bakerbhavanga" "https://baker-master.onrender.com/api/dashboard/matters-summary"
```

Returns `priority_count: 36`, all priority rows `item_count: 0`, 299 alerts in inbox bucket under 17 distinct legacy keys.

---

## Solution

Two-tier alert-side normalization at the Python layer of `get_matters_summary()`:

**Tier 1 (free, via `slug_registry`):** run each raw `alerts.matter_slug` through `slug_normalize()`. Catches all legacy slugs already aliased in `baker-vault/slugs.yml` (`movie_am`, `ao_pm`, `hagenauer`, etc.).

**Tier 2 (dashboard-side constant):** for free-text labels NOT in slugs.yml aliases (the ~10 display-string labels in the table above), consult a module-level `LEGACY_DISPLAY_LABEL_ALIASES` dict.

**Fallback:** unfoldable strings stay in `alerts_by_slug` as-is — they continue to route into the inbox bucket via the existing `slug not in priority_slugs` branch at line 4015. Director's "General" inbox is preserved.

**Fold semantics:** when multiple raw slugs collapse to the same canonical (e.g. `movie_am` + a future `"movie-am"` both → `mo-vie-am`), sum `item_count`, sum `new_count`, take `MIN(worst_tier)`. This is the standard alert-aggregation fold.

---

## Implementation

### Step 1 — Add `LEGACY_DISPLAY_LABEL_ALIASES` constant in `outputs/dashboard.py`

Place near the existing constants at line 3895-3897 (`_PROJECTS_CATEGORIES`, `_OPERATIONS_CATEGORIES`, `_IMPORTANCE_RANK`):

```python
# Legacy alert-table display labels → canonical priority slug.
# Free-text labels that pre-date slug_registry adoption; cannot be added to
# slugs.yml without a separate-repo PR (repo CLAUDE.md hard rule). Local
# server-side override consulted as Tier-2 fallback after slug_registry.normalize().
# Verify each canonical target against baker-vault/slugs.yml + wiki/_priorities.yml
# before adding. Unknown free-text labels stay in inbox (safe default).
LEGACY_DISPLAY_LABEL_ALIASES: dict[str, str] = {
    "Austrian Tax & Corporate": "austrian-tax-corp",
    "Swiss Tax & Banking": "swiss-tax-banking",
    "Family Wealth Overview": "family-wealth-overview",
    "German Property Tax": "german-property-tax",
    "Brisen-AI": "brisen-ai",
    "Cross-Border Structuring": "cross-border-structuring",
    "Cyprus Holding Structure": "cyprus-holding",
    "Campus Schlueterstrasse Hamburg": "campus-schluterstrasse",
    "Owner's Lens": "owners-lens",
    "Oskolkov-RG7": "hagenauer-rg7",
    "Mandarin Oriental Sales": "mo-vie-exit",
}
```

**MANDATORY pre-implementation step for the b-code:** verify each canonical target exists in `baker-vault/slugs.yml` AND `baker-vault/wiki/_priorities.yml`. For any target NOT present in BOTH:
- Either drop that map entry (label stays in inbox — safer default), OR
- Surface to AH1 in the ship report as a NEEDS-DIRECTOR-RATIFICATION item with the proposed canonical slug.

Run:
```bash
for slug in austrian-tax-corp swiss-tax-banking family-wealth-overview german-property-tax brisen-ai cross-border-structuring cyprus-holding campus-schluterstrasse owners-lens hagenauer-rg7 mo-vie-exit; do
  echo "=== $slug ==="
  grep -A1 "slug: $slug$" /Users/dimitry/baker-vault/slugs.yml | head -2
  grep -A1 "slug: $slug$\|^      - $slug$" /Users/dimitry/baker-vault/wiki/_priorities.yml | head -2
done
```

If any slug missing from `slugs.yml`: drop from the map. If missing from `_priorities.yml` only: still include (alert will attribute correctly when Director adds the priority via Triaga).

### Step 2 — Add `_fold_alerts_to_canonical()` helper in `outputs/dashboard.py`

Place immediately before `get_matters_summary()` (around line 3947, after `_build_legacy_response`):

```python
def _canonicalize_alert_slug(raw: str) -> Optional[str]:
    """Map a raw alerts.matter_slug to its canonical priority slug.

    Tier 1: slug_registry.normalize() — catches all aliases in slugs.yml
            (movie_am → mo-vie-am, hagenauer → hagenauer-rg7, etc.).
    Tier 2: LEGACY_DISPLAY_LABEL_ALIASES — covers free-text labels NOT in slugs.yml
            (e.g. "Austrian Tax & Corporate" → austrian-tax-corp).

    Returns None for unmappable strings (caller treats as inbox).
    """
    if not raw or raw == "_ungrouped":
        return None
    canonical = slug_normalize(raw)
    if canonical:
        return canonical
    return LEGACY_DISPLAY_LABEL_ALIASES.get(raw)


def _fold_alerts_to_canonical(alerts_by_slug: dict[str, dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """Fold raw-slug alert aggregations into canonical-slug aggregations.

    Returns (canonical_folded, unmapped) where:
      - canonical_folded: {canonical_slug: aggregated_row}; folds item_count + new_count
                          (summed) and worst_tier (MIN) when multiple raw slugs collapse.
      - unmapped:         {raw_slug: original_row} for slugs that did not resolve to a
                          canonical priority. Caller routes these to the inbox bucket.

    Preserves _ungrouped as unmapped (it's the canonical inbox sentinel).
    """
    canonical_folded: dict[str, dict] = {}
    unmapped: dict[str, dict] = {}

    for raw_slug, row in alerts_by_slug.items():
        canonical = _canonicalize_alert_slug(raw_slug)
        if canonical is None:
            unmapped[raw_slug] = row
            continue

        if canonical in canonical_folded:
            existing = canonical_folded[canonical]
            existing["item_count"] = (existing.get("item_count") or 0) + (row.get("item_count") or 0)
            existing["new_count"] = (existing.get("new_count") or 0) + (row.get("new_count") or 0)
            row_tier = row.get("worst_tier")
            existing_tier = existing.get("worst_tier")
            if row_tier is not None and (existing_tier is None or row_tier < existing_tier):
                existing["worst_tier"] = row_tier
        else:
            canonical_folded[canonical] = {
                "matter_slug": canonical,
                "item_count": row.get("item_count") or 0,
                "new_count": row.get("new_count") or 0,
                "worst_tier": row.get("worst_tier"),
            }

    return canonical_folded, unmapped
```

**Imports:** `Optional` is already imported at the top of `dashboard.py` (verify via `grep "^from typing import" outputs/dashboard.py`); add it if missing.

### Step 3 — Wire the helper into `get_matters_summary()`

Replace the block at `outputs/dashboard.py:3987-4026` (lookup + inbox-walk). Read the actual lines via the Read tool before editing — line numbers in this brief reflect snapshot at commit `901c66d` and may drift.

**Current (lines 3987-4026 approx):**

```python
alerts_by_slug = {r["matter_slug"]: dict(r) for r in cur.fetchall()}

# Build display rows for priorities (gate). Multi-row priorities
# for the same slug get folded — one row per slug, severity is
# the highest, category attributed to the highest-importance row.
seen_slugs: set[str] = set()
rows: list[dict] = []
for p in priorities:
    if p.slug in seen_slugs:
        continue
    seen_slugs.add(p.slug)
    norm = slug_normalize(p.slug) or p.slug
    alert = alerts_by_slug.get(norm) or alerts_by_slug.get(p.slug) or {}
    rows.append({
        "matter_slug": p.slug,
        ...
        "item_count": alert.get("item_count", 0),
        "worst_tier": alert.get("worst_tier"),
        "new_count": alert.get("new_count", 0),
    })

# Inbox = alerts WITHOUT a corresponding priority slug.
inbox_rows: list[dict] = []
for slug, row in alerts_by_slug.items():
    if slug == "_ungrouped" or slug not in priority_slugs:
        inbox_rows.append({
            ...
        })
```

**New:**

```python
alerts_by_slug = {r["matter_slug"]: dict(r) for r in cur.fetchall()}

# Fold raw alert slugs to canonical priority slugs (handles legacy aliases
# like movie_am → mo-vie-am and free-text labels like
# "Austrian Tax & Corporate" → austrian-tax-corp).
canonical_alerts, unmapped_alerts = _fold_alerts_to_canonical(alerts_by_slug)

# Build display rows for priorities (gate). Multi-row priorities
# for the same slug get folded — one row per slug, severity is
# the highest, category attributed to the highest-importance row.
seen_slugs: set[str] = set()
rows: list[dict] = []
for p in priorities:
    if p.slug in seen_slugs:
        continue
    seen_slugs.add(p.slug)
    alert = canonical_alerts.get(p.slug, {})
    rows.append({
        "matter_slug": p.slug,
        "display_label": _safe_describe(p.slug),
        "severity": p.importance,
        "category": p.category,
        "triaga_ref": p.triaga_ref,
        "description": p.description,
        "item_count": alert.get("item_count", 0),
        "worst_tier": alert.get("worst_tier"),
        "new_count": alert.get("new_count", 0),
    })

# Inbox = (a) unmapped raw-slug alerts + (b) canonical-folded alerts whose
# canonical slug is NOT a priority. Preserves "General" semantics + catches
# canonical slugs that lack a priority row.
inbox_rows: list[dict] = []
for slug, row in unmapped_alerts.items():
    inbox_rows.append({
        "matter_slug": slug,
        "display_label": _safe_describe(slug) if slug != "_ungrouped" else "General",
        "severity": "low",
        "category": "inbox",
        "triaga_ref": None,
        "description": "",
        "item_count": row.get("item_count", 0),
        "worst_tier": row.get("worst_tier"),
        "new_count": row.get("new_count", 0),
    })
for slug, row in canonical_alerts.items():
    if slug not in priority_slugs:
        inbox_rows.append({
            "matter_slug": slug,
            "display_label": _safe_describe(slug),
            "severity": "low",
            "category": "inbox",
            "triaga_ref": None,
            "description": "",
            "item_count": row.get("item_count", 0),
            "worst_tier": row.get("worst_tier"),
            "new_count": row.get("new_count", 0),
        })
```

**Note:** `_safe_describe()` already exists at line 3900 and handles unknown-slug `KeyError` from `slug_registry.describe()`. No new wrapper needed.

### Step 4 — Tests

Create `tests/test_dashboard_alert_fold.py`:

```python
"""Unit tests for the legacy-slug alert-side fold helpers added by
COCKPIT_SIDEBAR_LEGACY_SLUG_ALIAS_FIX_1."""

import pytest
from outputs.dashboard import (
    LEGACY_DISPLAY_LABEL_ALIASES,
    _canonicalize_alert_slug,
    _fold_alerts_to_canonical,
)


class TestCanonicalizeAlertSlug:
    def test_registered_alias_resolves(self):
        # movie_am is registered in slugs.yml line 38 under mo-vie-am
        assert _canonicalize_alert_slug("movie_am") == "mo-vie-am"

    def test_canonical_slug_passes_through(self):
        assert _canonicalize_alert_slug("hagenauer-rg7") == "hagenauer-rg7"

    def test_free_text_label_via_legacy_map(self):
        assert _canonicalize_alert_slug("Austrian Tax & Corporate") == "austrian-tax-corp"

    def test_unknown_string_returns_none(self):
        assert _canonicalize_alert_slug("some-random-string-not-in-any-registry") is None

    def test_ungrouped_sentinel_returns_none(self):
        assert _canonicalize_alert_slug("_ungrouped") is None

    def test_empty_string_returns_none(self):
        assert _canonicalize_alert_slug("") is None


class TestFoldAlertsToCanonical:
    def test_legacy_alias_folds_to_canonical_bucket(self):
        alerts = {"movie_am": {"matter_slug": "movie_am", "item_count": 136, "new_count": 45, "worst_tier": 2}}
        folded, unmapped = _fold_alerts_to_canonical(alerts)
        assert "mo-vie-am" in folded
        assert folded["mo-vie-am"]["item_count"] == 136
        assert folded["mo-vie-am"]["new_count"] == 45
        assert folded["mo-vie-am"]["worst_tier"] == 2
        assert unmapped == {}

    def test_two_raw_slugs_collapse_to_same_canonical_sum_counts(self):
        # Hypothetical: both "movie_am" and "Mandarin" (if aliased) → mo-vie-am
        # Use real aliases: hagenauer + hagenauer-rg7 both → hagenauer-rg7
        alerts = {
            "hagenauer": {"matter_slug": "hagenauer", "item_count": 5, "new_count": 1, "worst_tier": 3},
            "hagenauer-rg7": {"matter_slug": "hagenauer-rg7", "item_count": 10, "new_count": 2, "worst_tier": 1},
        }
        folded, unmapped = _fold_alerts_to_canonical(alerts)
        assert "hagenauer-rg7" in folded
        assert folded["hagenauer-rg7"]["item_count"] == 15           # summed
        assert folded["hagenauer-rg7"]["new_count"] == 3             # summed
        assert folded["hagenauer-rg7"]["worst_tier"] == 1            # MIN
        assert unmapped == {}

    def test_unknown_string_routes_to_unmapped(self):
        alerts = {"not-a-real-slug-anywhere": {"matter_slug": "not-a-real-slug-anywhere", "item_count": 3, "new_count": 0, "worst_tier": None}}
        folded, unmapped = _fold_alerts_to_canonical(alerts)
        assert folded == {}
        assert "not-a-real-slug-anywhere" in unmapped

    def test_ungrouped_routes_to_unmapped(self):
        alerts = {"_ungrouped": {"matter_slug": "_ungrouped", "item_count": 28, "new_count": 2, "worst_tier": 1}}
        folded, unmapped = _fold_alerts_to_canonical(alerts)
        assert folded == {}
        assert "_ungrouped" in unmapped

    def test_free_text_label_folds_via_legacy_map(self):
        alerts = {"Austrian Tax & Corporate": {"matter_slug": "Austrian Tax & Corporate", "item_count": 8, "new_count": 2, "worst_tier": 2}}
        folded, unmapped = _fold_alerts_to_canonical(alerts)
        assert "austrian-tax-corp" in folded
        assert folded["austrian-tax-corp"]["item_count"] == 8
        assert unmapped == {}

    def test_worst_tier_min_handles_none(self):
        alerts = {
            "hagenauer": {"matter_slug": "hagenauer", "item_count": 1, "new_count": 0, "worst_tier": None},
            "hagenauer-rg7": {"matter_slug": "hagenauer-rg7", "item_count": 1, "new_count": 0, "worst_tier": 2},
        }
        folded, _ = _fold_alerts_to_canonical(alerts)
        assert folded["hagenauer-rg7"]["worst_tier"] == 2     # None doesn't overwrite 2

    def test_legacy_display_label_aliases_dict_is_populated(self):
        # Smoke: catch the entire constant being deleted by mistake
        assert "Austrian Tax & Corporate" in LEGACY_DISPLAY_LABEL_ALIASES
        assert LEGACY_DISPLAY_LABEL_ALIASES["Austrian Tax & Corporate"] == "austrian-tax-corp"
```

Extend `tests/test_dashboard.py` (if it has an existing `matters-summary` test fixture; otherwise add a new test file `tests/test_dashboard_matters_summary_fold.py`):

```python
def test_matters_summary_attributes_legacy_slug_alerts_to_canonical_priority(monkeypatch, db_cursor_with_alerts):
    """Integration: when alerts.matter_slug='movie_am' (136 items) and a priority
    exists for mo-vie-am, the response's projects[].item_count for mo-vie-am
    must be 136, not 0; inbox must NOT contain a movie_am row."""
    # Seed: insert alert rows with matter_slug='movie_am' under status='pending'
    # Mock priorities_registry.get_all() to include a Priority(slug='mo-vie-am', ...)
    # Hit endpoint via TestClient; assert response shape.
    ...

def test_matters_summary_unknown_free_text_label_stays_in_inbox():
    """Slug like 'Random Free-Text Not Aliased Anywhere' → inbox, NOT a project,
    NOT a 500. Guards Tier-2 fallback path."""
    ...
```

The b-code should use the existing test infrastructure pattern in `tests/test_dashboard.py` (TestClient + DB fixture). If no existing fixture for alerts seeding, the unit tests in `tests/test_dashboard_alert_fold.py` cover the helper logic standalone; the integration assertion can be a smoke curl in the ship report against a local dev server.

### Step 5 — Verification

After deploy, hit live endpoint:

```bash
curl -s -H "X-Baker-Key: $BAKER_API_KEY" "https://baker-master.onrender.com/api/dashboard/matters-summary" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('priority_count:', d.get('priorities_version'))
print('fallback_mode:', d.get('fallback_mode'))
print()
print('=== projects with item_count > 0 (should include mo-vie-am 136, ao-pm 100) ===')
for p in d.get('projects', []):
    if p.get('item_count', 0) > 0:
        print(f\"  {p['matter_slug']:25s} items={p['item_count']:3d} new={p['new_count']:3d}\")
print()
print('=== inbox_count (was 299; should drop sharply, ~28 _ungrouped + leftovers) ===')
print('  inbox_count:', d.get('inbox_count'))
"
```

Expected post-deploy:
- `mo-vie-am`: item_count ≥ 136
- `ao-pm` (or whichever canonical maps from `ao_pm`): item_count ≥ 100
- `hagenauer-rg7`: item_count ≥ 1 (folds `Hagenauer` raw + `Oskolkov-RG7` if mapped)
- `inbox_count`: drops from 299 → ~30-40 (only `_ungrouped` + unmapped free-text)

---

## Files Modified

### Modify
- `outputs/dashboard.py` — add `LEGACY_DISPLAY_LABEL_ALIASES` constant, `_canonicalize_alert_slug()` helper, `_fold_alerts_to_canonical()` helper; rewire `get_matters_summary()` lookup + inbox-walk.

### Create
- `tests/test_dashboard_alert_fold.py` — unit tests for both helpers (≥8 tests).
- Extend `tests/test_dashboard.py` OR new `tests/test_dashboard_matters_summary_fold.py` — 2 integration tests asserting fold reaches the endpoint.

---

## Files NOT to touch

- `baker-vault/slugs.yml` — separate-repo PR-only (repo CLAUDE.md hard rule). Free-text labels go in dashboard-side map per Director Option 1.
- `baker-vault/wiki/_priorities.yml` — Director-ratified via Triaga; read-only.
- `kbl/slug_registry.py` — use existing `normalize()` public API.
- `kbl/priorities_registry.py` — read-only consumer.
- `outputs/static/app.js`, `outputs/static/index.html`, `outputs/static/style.css` — API response shape unchanged; no frontend work needed.
- `alerts` table / SQL migrations — read-only; no DDL, no backfill.
- `_build_legacy_response()` at `outputs/dashboard.py:3911` — separate fallback path; intentionally unchanged.

---

## Risks

- **Free-text label drift.** If a new free-text alert slug appears that's not in `LEGACY_DISPLAY_LABEL_ALIASES`, it silently routes to inbox. Acceptable (safe default); not silent (inbox count visible in cockpit). Future improvement: log unrecognized slugs once-per-day for visibility (out of scope for this brief).
- **Ambiguous mapping — `Oskolkov-RG7`.** This label could mean either `ao` (the counterparty) or `hagenauer-rg7` (the dispute matter). Brief maps it to `hagenauer-rg7` (the dispute is the active project). If Director objects, drop the entry; the 8 items return to inbox.
- **Canonical slug not in slugs.yml.** Some Tier-2 free-text targets (e.g. `austrian-tax-corp`, `swiss-tax-banking`) may not yet exist in `slugs.yml`. The pre-implementation verification step (Step 1 grep) catches this — drop unverified entries.
- **Conn rollback rule** (`.claude/rules/python-backend.md`): no new SQL paths; existing `except: conn.rollback()` at `outputs/dashboard.py:4055-4061` covers all changes. The fold helpers are pure-Python.
- **LIMIT rule:** alerts SQL already has `LIMIT 500` (line 3985). No change.
- **Singleton rule:** N/A — no Sentinel-class instances; `slug_registry` already singleton via existing module pattern.
- **Migration-vs-bootstrap drift:** N/A — zero DDL.
- **Function-signature drift** (Lesson #44/#45 family): `slug_normalize(None)` returns `None`; `slug_normalize("unknown")` returns `None`. Helper handles both. Verified via `kbl/slug_registry.py:195`.
- **Phantom helper risk:** `_safe_describe()` exists at `outputs/dashboard.py:3900` — verified via Read. Do not re-define.
- **Render restart survival:** module-level dict + slug_registry singleton; restart re-loads cleanly.
- **Backwards compat:** API response shape unchanged. Frontend `app.js:_renderMatterSection` reads same fields. Only `item_count`/`new_count` values shift from inbox to projects.
- **Performance:** O(n) fold on alerts dict (≤500 rows per LIMIT). Negligible.

---

## Code Brief Standards (mandatory)

- **API version:** internal Python only; no external API surface.
- **Deprecation check date:** N/A.
- **Fallback:** unmapped slugs → inbox bucket (safe default). `_build_legacy_response()` path untouched for `_priorities.yml`-missing case.
- **DDL drift check:** zero DDL added. Verify: `grep -E "INSERT|UPDATE|DELETE|CREATE TABLE|ALTER" outputs/dashboard.py` should show no NEW matches versus `git diff main`.
- **Literal pytest output mandatory:** ship report MUST include literal `pytest tests/test_dashboard_alert_fold.py -v` stdout (≥8 passing tests) AND `pytest tests/test_dashboard.py -v` (existing suite unaffected). NO "passes by inspection."
- **py_compile clean:** `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` exit 0.
- **LLM calls:** none. Render-only data layer.
- **Mobile rendering:** not affected — API response shape unchanged; existing cockpit JS handles it.
- **Singleton pattern `_get_global_instance()`:** N/A — no Sentinel classes touched.

---

## Verification criteria

1. **pytest unit suite passes:**
   ```
   pytest tests/test_dashboard_alert_fold.py -v
   ```
   ≥8 tests pass.

2. **py_compile clean:**
   ```
   python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
   ```
   Exit 0.

3. **Live endpoint smoke (post-Render-deploy):**
   ```bash
   curl -s -H "X-Baker-Key: $BAKER_API_KEY" \
     "https://baker-master.onrender.com/api/dashboard/matters-summary" \
     | python3 -c "import sys,json; d=json.load(sys.stdin); print('mo-vie-am:', next((p for p in d['projects'] if p['matter_slug']=='mo-vie-am'), {}).get('item_count'))"
   ```
   Must print `136` (or current production count for `movie_am` raw).

4. **Inbox-count delta:**
   Pre-deploy `inbox_count: 299`. Post-deploy should drop to ≤50.

5. **UI smoke (Director-facing):**
   - Director opens cockpit, clicks Project section in left sidebar.
   - At minimum these now show non-zero counts: Mandarin Oriental Vienna AM (`mo-vie-am`), Oskolkov / AO (`ao-pm`), Hagenauer RG7 (`hagenauer-rg7`).
   - Inbox bucket no longer dominates.

6. **Regression guard:**
   ```
   pytest tests/ -v -k "matters_summary or dashboard"
   ```
   No prior-passing test fails.

---

## Out of scope

- **Backfill alerts table** with canonical slugs — separate brief, Option 2 path (deferred). This brief is Option 1 (read-only API layer).
- **Add free-text labels to `slugs.yml`** — separate-repo PR; can land later as cleanup. Dashboard-side map is the operational fix.
- **Sidebar Phase 2 (Gold writes)** — `CORTEX_COCKPIT_GOLD_WRITES_1` brief, AH1 authors separately.
- **`Oskolkov-RG7` semantic resolution** — mapped to `hagenauer-rg7` here; if Director prefers a different attribution, single-line map edit.
- **Logging unrecognized slugs** — future "drift sentinel" for new free-text labels; not blocking.
- **Mobile sidebar rewrite** — unchanged.

---

## Branch + PR

- Branch: `b2/cockpit-legacy-slug-alias-fix-1`
- PR title: `COCKPIT_SIDEBAR_LEGACY_SLUG_ALIAS_FIX_1: fold legacy alert slugs to canonical priorities`
- **Tier-A merge:** YES (user-facing surface change; affects cockpit counts Director sees).
- **`/security-review` MANDATORY** per Lesson #52 + SKILL.md §Security Review Protocol.
- **2nd-pass `feature-dev:code-reviewer`:** OPTIONAL — no auth/DB/concurrency surface touched (trigger classes 1-4 not hit, scope <100 LOC, not part of cross-repo merge sequence). AH1 judgment at review time: fire if anything smells off.
- **Cross-lane review:** AH2 per autonomy charter §3.

## §6C orchestration note (B-code dispatch coordination)

- Touches `outputs/dashboard.py` (one endpoint), `tests/` (new files). Zero overlap with any active b1/b3/b4 dispatch.
- b2 mailbox `CODE_2_PENDING.md` currently lists BUS_DRAIN_CURSOR_CAP_FIX_1 (P3) — that work was already shipped via PR #184 (`990a606`) per last night's handover. Overwrite per `_ops/processes/b-code-dispatch-coordination.md` §3 mailbox hygiene before dispatch.

---

## Co-Authored-By

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
