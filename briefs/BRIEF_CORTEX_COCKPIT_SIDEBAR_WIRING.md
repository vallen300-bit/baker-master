# BRIEF: CORTEX_COCKPIT_SIDEBAR_WIRING — Cockpit sidebar renders from Triaga source-of-truth + canonical labels

**Milestone:** Render-only follow-on to B2 (per AID scope-lock 2026-05-10).
**Roadmap source:** Brisen Desk synthesis `wiki/matters/brisen/curated/2026-05-10-cockpit-vs-priorities-review.md` → AID Director-ratified Option (b) 2026-05-10 → AID scope-lock dispatch 2026-05-10.
**Estimated time:** ~5-7h
**Complexity:** Medium
**Prerequisites:**
- `kbl/slug_registry.py` (M0, production)
- `baker-vault/wiki/_priorities.yml` (Triaga-ratified 2026-04-29, schema v1, 40 matters)
- `baker-vault/slugs.yml` (v20 as of 2026-05-05, loaded by `slug_registry`)
- `BAKER_VAULT_PATH` env var set on Render (already required by `slug_registry`; same path resolves `_priorities.yml` via subdir `wiki/`)

---

## Context

Brisen Desk synthesis 2026-05-10 (live read of baker-master.onrender.com sidebar DOM vs `wiki/hot.md` regenerated from `wiki/_priorities.yml` Triaga-ratified 2026-04-29):

- ~60% of Triaga-ratified priorities **missing** from sidebar (mrci, lilienmatt, annaberg, aukera, nvidia-corinthia, franck-muller, capital-call, brisen-pr, mo-prague, citic, capital-call, m365, baker-internal Cortex 3T, etc.)
- ~40% present but under **legacy non-canonical labels** ("Mandarin Oriental Sales" vs canonical `mo-vie-am`/`mo-vie-exit`; "Oskolkov RG7" conflating `oskolkov` matter + `hagenauer-rg7` dispute; "Kempinski Kitzbühel Acquisition" Director-dismissed at Triaga Q34 but still rendered)
- **Severity dots disagree with Triaga.** Hagenauer rendered slate (1) but has TWO Critical Triaga items (Q1 GC takeover, Q2 admin defence). Pattern: red dots correlate with email/inbox volume, not Triaga priority.

Director ratified Option (b) standalone brief 2026-05-10. AID scope-lock: render-only follow-on to B2. No B2 producer dependency (B2 = wiki ingest hardening; `_priorities.yml` is stable static data already on disk).

Source-of-truth files already exist on Render via `BAKER_VAULT_PATH`:
- `wiki/_priorities.yml` — 40 matter rows, schema v1: `slug | slugs[]`, `when`, `importance`, `category`, `triaga_ref`, `description`, `notes`
- `slugs.yml` v20 — canonical `slug` → `description` + `aliases[]`, already loaded by production `kbl/slug_registry.py` singleton

---

## Problem

Cockpit sidebar (baker-master.onrender.com left panel) is a **parallel list** to the Triaga, not a view of it.

| Section | Today's render | Triaga reference |
|---|---|---|
| Projects (11) | 5 items render with title-cased slug labels (e.g. "Mandarin Oriental Sales") | 30 active priorities across 20+ canonical slugs |
| Operations (17) | Admin-only items not in Triaga (Austrian Tax 6, Cyprus Holding 1, etc.) | Should reflect Triaga `category: admin-ops-pr` / `tax` / `private-assets` filtered to active priorities |
| Inbox (184) | Flat alert dump, no priority join | N/A — alerts firehose, separate concern |
| Severity dots | `(m.worst_tier && m.worst_tier <= 2) ? 'red' : 'slate'` — driven by `MIN(alerts.tier)`, NOT by `_priorities.importance` | Triaga importance: critical / high / medium / low / frozen |
| Display drift | Header reads "Projects 11" but only 5 items render | Either 6 items filtered/hidden or count stale |

Concrete failure modes:
- Kempinski Kitzbühel — Director-dismissed Q34 — **still rendered** (no priorities-side filter).
- Hagenauer dot slate (1) when Triaga has 2 critical entries — **severely under-coloured AND undercounted**.
- mrci / lilienmatt / annaberg / aukera — Q6/Q7/Q9 active deals — **invisible** because alerts table has no matching `matter_slug` entries.

---

## Current state

### Backend: `outputs/dashboard.py:3888-3937` — `GET /api/dashboard/matters-summary`

```python
@app.get("/api/dashboard/matters-summary", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_matters_summary():
    """List matters with alert counts and worst active tier, for sidebar rendering."""
    # SIDEBAR-RESTRUCTURE-1: Get matters with alert stats + category from matter_registry
    cur.execute("""
        SELECT
            COALESCE(a.matter_slug, '_ungrouped') AS matter_slug,
            COUNT(*) AS item_count,
            MIN(a.tier) AS worst_tier,
            COUNT(*) FILTER (WHERE a.created_at >= NOW() - INTERVAL '24 hours') AS new_count,
            COALESCE(mr.category, 'inbox') AS category
        FROM alerts a
        LEFT JOIN matter_registry mr ON LOWER(REPLACE(mr.matter_name, ' ', '-')) = LOWER(a.matter_slug)
            OR LOWER(mr.matter_name) = LOWER(REPLACE(a.matter_slug, '-', ' '))
        WHERE a.status = 'pending'
        GROUP BY COALESCE(a.matter_slug, '_ungrouped'), COALESCE(mr.category, 'inbox')
        ORDER BY item_count DESC
    """)
```

Returns: `{ matters, projects, operations, inbox, inbox_count, count }`. Each row: `{ matter_slug, item_count, worst_tier, new_count, category }`. **No canonical label, no priority severity, no priorities filter.**

### Frontend: `outputs/static/app.js:1533-1591` — `loadMattersSummary()` + `_renderMatterSection()`

```javascript
function _renderMatterSection(containerId, matters, countId) {
    // ...
    var slug = m.matter_slug || '_ungrouped';
    var label = slug === '_ungrouped' ? 'General'
        : slug.replace(/_/g, ' ').replace(/[-]/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
    var dotClass = (m.worst_tier && m.worst_tier <= 2) ? 'red' : 'slate';
    // ...
}
```

Label = title-cased slug. Dot = binary red/slate from `worst_tier`. Neither consults `_priorities.yml` or `slugs.yml`.

### Existing `slug_registry` public API (`kbl/slug_registry.py`)

Verified via grep:

```python
def canonical_slugs() -> set[str]       # all slugs (active + retired + draft)
def active_slugs() -> set[str]          # active only
def is_canonical(slug: Optional[str]) -> bool
def normalize(raw: Optional[str]) -> Optional[str]   # alias → canonical
def describe(slug: str) -> str          # canonical description from slugs.yml
def aliases_for(slug: str) -> list[str]
def registry_version() -> int           # currently 20
def reload() -> None
```

Singleton lazy-loads from `${BAKER_VAULT_PATH}/slugs.yml` on first call. Production-wired; no changes needed.

### `_priorities.yml` shape (verified by direct read)

```yaml
schema_version: 1
ratified_at: '2026-04-29T18:45:00+02:00'
ratified_by: director
categories: [active-deal, legal-risk, financial, origination, tax, admin-ops-pr, private-assets, personal-admin]
matters:
  - slug: hagenauer-rg7
    when: urgent
    importance: critical
    category: active-deal
    triaga_ref: Q1
    description: GC takeover — complete hotel + residences build
    notes: []
  - slugs:                              # multi-slug row variant
      - lilienmatt
      - annaberg
      - aukera
    when: asap
    importance: high
    category: active-deal
    triaga_ref: Q7
    description: Move financing — multi-entity company restructure
    notes: []
```

40 rows total. `importance` enum: `critical | high | medium | low | frozen`. `category` enum matches top-level `categories` list. A row carries EITHER `slug:` (singular) OR `slugs:` (plural list, applies to multiple matters under same priority).

---

## Solution

Render-only changes. No schema changes, no signal_queue producer changes, no `_priorities.yml` writes, no `slugs.yml` writes.

**Reviewer-caught corrections applied 2026-05-10 (feature-dev:code-reviewer pass):**
- `slug_registry.describe(slug)` RAISES `KeyError` on unknown slug (verified at `kbl/slug_registry.py:215-220`), it does NOT return `None`. The Step-2 pseudocode below uses a `_safe_describe()` helper that catches the exception.
- `priorities_registry.registry_version` + `registry_ratified_at` must be imported explicitly; calls qualified.
- Singleton pattern in `slug_registry` is module-level `_cache` + `threading.Lock()` + `_get_registry()`, NOT `_get_global_instance()`. Mirror that exact pattern in `priorities_registry`.
- Fallback path: keep the LEGACY SQL+matter_registry join as an explicit `else` branch when `get_all()` returns `[]`. Do not rely on implicit-empty path.
- CSS dot classes: existing palette (`red`, `amber`, `blue`, `green`, `slate`, `lgray`) at `outputs/static/style.css:181-186` covers all 5 severity enum values. NO new CSS additions required.

### Step 1 — New loader module `kbl/priorities_registry.py`

Singleton-pattern loader for `_priorities.yml`, **exactly mirroring** `kbl/slug_registry.py` design — verified pattern:

```python
# Module-level state (matches slug_registry.py lines ~30-160)
_cache: Optional[_PrioritiesRegistry] = None
_lock = threading.Lock()

def _get_registry() -> _PrioritiesRegistry:
    global _cache
    if _cache is None:
        with _lock:
            if _cache is None:
                _cache = _parse_yaml(_resolve_yaml_path())
    return _cache

def reload() -> None:
    global _cache
    with _lock:
        _cache = None
```

NOT `_get_global_instance()`. The CLAUDE.md hard rule about `_get_global_instance()` specifically targets `SentinelRetriever()` / `SentinelStoreBack()` (covered by `scripts/check_singletons.sh`). `slug_registry` uses the module-level cache + lock pattern instead, and this new module mirrors that exactly. CI guard does NOT currently cover `priorities_registry`; that's acceptable for a Director-curated content loader (file-missing is fail-soft, not infrastructure-critical).

Path resolution: `${BAKER_VAULT_PATH}/wiki/_priorities.yml` (NOTE: `_priorities.yml` lives under `wiki/`, NOT at vault root like `slugs.yml`).

Public API (mirror slug_registry naming where possible):

```python
@dataclass(frozen=True)
class Priority:
    slug: str           # canonical matter slug
    when: str           # "urgent" | "asap" | "4w" | etc.
    importance: str     # "critical" | "high" | "medium" | "low" | "frozen"
    category: str       # "active-deal" | "legal-risk" | ...
    triaga_ref: str     # "Q1", "Q34", etc. (for traceability)
    description: str
    notes: list[str]    # may be empty


class PrioritiesRegistryError(RuntimeError): ...

def get_all() -> list[Priority]:
    """All priorities, exploded per-slug (multi-slug rows split into one Priority per slug)."""

def get_by_slug(slug: str) -> Optional[Priority]:
    """Returns first matching Priority for slug; None if not in priorities.
       For matters in multiple priority rows (rare), returns the highest-importance row."""

def get_all_for_slug(slug: str) -> list[Priority]:
    """All Priority rows that include this slug (handles single + multi-slug rows)."""

def severity_for(slug: str) -> Optional[str]:
    """Highest importance enum across all priority rows for slug. None if slug not in priorities."""

def category_for(slug: str) -> Optional[str]:
    """First category found for slug (NOTE: a slug in multiple rows may have multiple categories;
       returns the highest-importance row's category for sidebar attribution)."""

def is_active_priority(slug: str) -> bool:
    """True if slug appears in any priority row."""

def registry_version() -> int:           # schema_version field
def registry_ratified_at() -> str:       # ratified_at field
def reload() -> None: ...
```

Loader rules:
- **Fail-loud on schema violation at parse time** (matches slug_registry pattern): missing required fields, unknown importance enum, unknown category enum, non-string slug → raise `PrioritiesRegistryError`.
- **Fail-soft on file-missing at runtime** (different from slug_registry): if `_priorities.yml` not found, log warning ONCE and return empty registry. Sidebar falls back to legacy behavior. (Rationale: `_priorities.yml` is Director-curated, not infrastructure-critical; vault-mirror lag should not break sidebar.)
- **Multi-slug row expansion:** if row has `slugs: [a, b, c]`, emit one `Priority` per slug at `get_all()` time. `get_by_slug(a)` returns the same priority object (semantically shared).
- **Importance ordering** for `severity_for`: `critical > high > medium > low > frozen`. Define a module-level enum `IMPORTANCE_ORDER = ("critical", "high", "medium", "low", "frozen")` for sort key.

### Step 2 — Extend `/api/dashboard/matters-summary`

Replace SQL-only path with a two-source merge:

```python
# Pseudocode flow — actual implementation in dashboard.py:3888

# Imports (top of file): explicit + qualified to avoid name clashes with slug_registry
from kbl.priorities_registry import (
    get_all as get_all_priorities,
    severity_for as priority_severity_for,
    category_for as priority_category_for,
    is_active_priority,
    registry_version as priorities_registry_version,
    registry_ratified_at as priorities_registry_ratified_at,
)
from kbl.slug_registry import describe as slug_describe, normalize as slug_normalize


def _safe_describe(slug: str) -> str:
    """slug_registry.describe() raises KeyError on unknown slug. Wrap for safety
       since _priorities.yml may contain slugs not yet in slugs.yml (separate-repo
       drift window)."""
    try:
        return slug_describe(slug)
    except KeyError:
        return slug  # fallback to raw slug; cockpit still renders, label just looks weak


def _build_legacy_response(cur) -> dict:
    """Legacy code path — runs ONLY when priorities_registry returns empty
       (e.g. _priorities.yml missing or malformed). Preserves pre-cockpit-wiring
       behavior so sidebar never goes blank on a vault-mirror lag."""
    cur.execute("""
        SELECT
            COALESCE(a.matter_slug, '_ungrouped') AS matter_slug,
            COUNT(*) AS item_count,
            MIN(a.tier) AS worst_tier,
            COUNT(*) FILTER (WHERE a.created_at >= NOW() - INTERVAL '24 hours') AS new_count,
            COALESCE(mr.category, 'inbox') AS category
        FROM alerts a
        LEFT JOIN matter_registry mr ON LOWER(REPLACE(mr.matter_name, ' ', '-')) = LOWER(a.matter_slug)
            OR LOWER(mr.matter_name) = LOWER(REPLACE(a.matter_slug, '-', ' '))
        WHERE a.status = 'pending'
        GROUP BY COALESCE(a.matter_slug, '_ungrouped'), COALESCE(mr.category, 'inbox')
        ORDER BY item_count DESC
        LIMIT 500
    """)
    all_matters = [dict(r) for r in cur.fetchall()]
    inbox_count = sum(m['item_count'] for m in all_matters if m['matter_slug'] == '_ungrouped')
    return {
        "matters": all_matters,
        "projects": [m for m in all_matters if m.get('category') == 'project'],
        "operations": [m for m in all_matters if m.get('category') == 'operations'],
        "inbox": [m for m in all_matters if m.get('category') == 'inbox' or m['matter_slug'] == '_ungrouped'],
        "inbox_count": inbox_count,
        "count": len(all_matters),
        "priorities_version": None,
        "priorities_ratified_at": None,
        "fallback_mode": "legacy_no_priorities",
    }


# Main path:

# 1. Load active priorities first (source of truth for "what should show in Projects/Operations")
priorities = get_all_priorities()  # list[Priority], multi-slug expanded; [] if file missing

# FALLBACK: if priorities empty, run legacy path (preserves pre-cockpit-wiring sidebar)
if not priorities:
    return _build_legacy_response(cur)

priority_slugs = {p.slug for p in priorities}

# 2. Pull alert counts (existing SQL, slightly modified — adds LIMIT per python-backend.md rule)
cur.execute("""
    SELECT
        COALESCE(NULLIF(a.matter_slug, ''), '_ungrouped') AS matter_slug,
        COUNT(*) AS item_count,
        MIN(a.tier) AS worst_tier,
        COUNT(*) FILTER (WHERE a.created_at >= NOW() - INTERVAL '24 hours') AS new_count
    FROM alerts a
    WHERE a.status = 'pending'
    GROUP BY COALESCE(NULLIF(a.matter_slug, ''), '_ungrouped')
    ORDER BY item_count DESC
    LIMIT 500
""")
alerts_by_slug = {r["matter_slug"]: dict(r) for r in cur.fetchall()}

# 3. For each priority slug, build the display row (priority is the gate)
rows = []
for p in priorities:
    norm = slug_normalize(p.slug) or p.slug  # canonical slug
    alert = alerts_by_slug.get(norm) or alerts_by_slug.get(p.slug) or {}
    rows.append({
        "matter_slug": p.slug,
        "display_label": _safe_describe(p.slug),           # NEW: canonical desc (KeyError-safe)
        "severity": p.importance,                          # NEW: enum string, NOT worst_tier
        "category": p.category,                            # NEW: _priorities.yml category
        "triaga_ref": p.triaga_ref,
        "description": p.description,
        "item_count": alert.get("item_count", 0),
        "worst_tier": alert.get("worst_tier"),             # kept for tooltip / debug only
        "new_count": alert.get("new_count", 0),
    })

# 4. Inbox = alerts WITHOUT a corresponding priority slug
inbox_rows = []
for slug, row in alerts_by_slug.items():
    if slug == "_ungrouped" or slug not in priority_slugs:
        inbox_rows.append({
            "matter_slug": slug,
            "display_label": _safe_describe(slug) if slug != "_ungrouped" else "General",
            "severity": "low",                              # default for non-priority inbox
            "category": "inbox",
            "item_count": row["item_count"],
            "worst_tier": row["worst_tier"],
            "new_count": row["new_count"],
        })

# 5. Bucket projects/operations by _priorities.yml category mapping
PROJECTS_CATEGORIES = {"active-deal", "legal-risk", "financial", "origination"}
OPERATIONS_CATEGORIES = {"tax", "admin-ops-pr", "private-assets", "personal-admin"}

projects = [r for r in rows if r["category"] in PROJECTS_CATEGORIES]
operations = [r for r in rows if r["category"] in OPERATIONS_CATEGORIES]

# Sort by importance (critical first), then by item_count desc, then by triaga_ref
IMPORTANCE_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "frozen": 4}
sort_key = lambda r: (IMPORTANCE_RANK.get(r["severity"], 5), -(r["item_count"] or 0), r.get("triaga_ref", ""))
projects.sort(key=sort_key)
operations.sort(key=sort_key)
inbox_rows.sort(key=lambda r: -(r["item_count"] or 0))

return {
    "matters": rows + inbox_rows,
    "projects": projects,
    "operations": operations,
    "inbox": inbox_rows,
    "inbox_count": sum(r["item_count"] for r in inbox_rows),
    "count": len(rows) + len(inbox_rows),
    "priorities_version": priorities_registry_version(),         # explicit, qualified
    "priorities_ratified_at": priorities_registry_ratified_at(),  # explicit, qualified
    "fallback_mode": None,
}
```

**Conn rollback rule** (Python backend rule, .claude/rules/python-backend.md): wrap fetch in `try/except`; `conn.rollback()` on exception before re-raising. Mirror existing function's pattern (already has try/except + `finally: store._put_conn(conn)`).

**LIMIT rule:** LIMIT 500 on the alerts query (current code has no LIMIT — Lesson #unbounded-queries cousin).

### Step 3 — Frontend `_renderMatterSection`

Edit `outputs/static/app.js:1554-1591`:

```javascript
function _renderMatterSection(containerId, matters, countId) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.textContent = '';
    var totalCount = 0;
    for (var i = 0; i < matters.length; i++) {
        var m = matters[i];
        var slug = m.matter_slug || '_ungrouped';
        if (slug === '_ungrouped' && containerId !== 'inboxSubList') continue;

        // NEW: canonical label from API (slug_registry.describe), fall back to title-cased slug
        var label = m.display_label
            || (slug === '_ungrouped' ? 'General'
                : slug.replace(/_/g, ' ').replace(/[-]/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); }));
        // Truncate to fit sidebar width (60 chars; existing nav-label CSS handles overflow)
        if (label.length > 60) label = label.substring(0, 57) + '...';

        // NEW: severity dot from Triaga importance (priority-driven), fall back to worst_tier (legacy)
        // Mapping uses EXISTING palette in outputs/static/style.css:181-186:
        //   .nav-dot.red    (--red    #C75050)         — critical
        //   .nav-dot.amber  (--amber  #D4A535)         — high
        //   .nav-dot.blue   (--blue   #C9A96E gold)    — medium
        //   .nav-dot.slate  (--slate  rgba muted)      — low
        //   .nav-dot.lgray  (--lgray  rgba lighter)    — frozen
        // NO new CSS rules required.
        var dotClass;
        if (m.severity) {
            switch (m.severity) {
                case 'critical': dotClass = 'red'; break;
                case 'high':     dotClass = 'amber'; break;
                case 'medium':   dotClass = 'blue'; break;
                case 'low':      dotClass = 'slate'; break;
                case 'frozen':   dotClass = 'lgray'; break;
                default:         dotClass = 'slate';
            }
        } else {
            // Legacy fallback for inbox items without priority context
            dotClass = (m.worst_tier && m.worst_tier <= 2) ? 'red' : 'slate';
        }

        totalCount += m.item_count || 0;

        var item = document.createElement('div');
        item.className = 'nav-item';
        item.dataset.tab = 'matters';
        item.dataset.matter = slug;
        if (m.triaga_ref) item.dataset.triagaRef = m.triaga_ref;  // for debug / tooltip

        var dot = document.createElement('span');
        dot.className = 'nav-dot ' + dotClass;
        item.appendChild(dot);

        var lbl = document.createElement('span');
        lbl.className = 'nav-label';
        lbl.textContent = label;
        var titleParts = [label];
        if (m.triaga_ref) titleParts.push('Triaga ' + m.triaga_ref);
        if (m.description) titleParts.push(m.description);
        titleParts.push('items: ' + (m.item_count || 0));
        item.title = titleParts.join(' · ');
        item.appendChild(lbl);

        var cnt = document.createElement('span');
        cnt.className = 'nav-count';
        cnt.textContent = m.item_count;
        item.appendChild(cnt);

        container.appendChild(item);
    }
    setText(countId, totalCount || '');
}
```

**XSS safety:** all user-derived strings (`label`, `title`, `slug` data attr) flow through `textContent` / `dataset` (DOM API auto-escape). No `innerHTML` introduced. (Lesson cousin: phantom `_escHtml()` — DOM API is the safer pattern.)

### Step 4 — CSS dot classes (NO new CSS required)

Existing palette at `outputs/static/style.css:180-186` already provides all 5 dot classes needed:

```
.nav-dot.red    { background: var(--red);   }  /* #C75050  */
.nav-dot.amber  { background: var(--amber); }  /* #D4A535  */
.nav-dot.blue   { background: var(--blue);  }  /* #C9A96E (gold) */
.nav-dot.slate  { background: var(--slate); }  /* rgba muted     */
.nav-dot.lgray  { background: var(--lgray); }  /* rgba lighter   */
```

Severity → dot class mapping (locked in Step 3 JS): critical→red, high→amber, medium→blue, low→slate, frozen→lgray.

Verification grep (run before assuming): `grep -nE "\\.nav-dot" outputs/static/style.css` — must show all 5 classes.

NO new CSS rules. NO hex value invention. The Brisen Desk synthesis flagged "Director preference: McKinsey-style muted colors" — the existing palette is already muted-gold/champagne brand-aligned. Don't introduce orange/grey out-of-palette.

### Step 5 — Cache bust

`outputs/static/index.html`: bump `?v=N` on `app.js` query string. iOS PWA hard caches — frontend rule mandates the bump.

### Step 6 — Tests

Create `tests/test_priorities_registry.py`:

- Test fixture at `tests/fixtures/priorities/_priorities_mini.yml` — 5 stub matters covering: single slug, multi-slug (3 slugs), each importance enum value, each category enum value, notes-present/empty.
- 10+ tests:
  - `test_singleton_loads_once` — calling `get_all()` twice doesn't re-read file.
  - `test_multi_slug_row_expansion` — row with `slugs: [a, b, c]` produces 3 `Priority` entries via `get_all`, each retrievable via `get_by_slug`.
  - `test_severity_for_critical / high / medium / low / frozen` — five enum-mapping tests.
  - `test_severity_for_unknown_slug_returns_none` — slug not in priorities → None.
  - `test_category_for_active_deal / tax / etc.` — category-mapping tests.
  - `test_is_active_priority_true / false` — boolean.
  - `test_missing_file_returns_empty_warns_once` — point loader at non-existent path; first call logs warning, returns empty; second call silent.
  - `test_malformed_yaml_raises_loud` — fixture with bad schema → `PrioritiesRegistryError`.
  - `test_unknown_importance_enum_raises_loud` — fixture with `importance: invalid` → error.
  - `test_reload_re_reads_file` — modify fixture path between calls; `reload()` picks up changes.

Extend `tests/test_dashboard.py` (or wherever `/api/dashboard/matters-summary` is tested — check via grep `matters-summary` in `tests/`):
- `test_matters_summary_priorities_overlay` — mock `priorities_registry` with fixture; mock DB cursor; assert returned `projects` has entries for slugs in priorities but NOT in alerts table.
- `test_matters_summary_severity_from_priority_not_worst_tier` — priority with `importance: critical` + no alerts → response row has `severity: 'critical'`, NOT `worst_tier`-derived value.
- `test_matters_summary_dismissed_slug_excluded` — slug not in priorities → goes to inbox bucket, NOT projects.
- `test_matters_summary_priorities_unavailable_falls_back` — point priorities_registry at missing file; call `reload()`; assert response has `fallback_mode: "legacy_no_priorities"` AND `priorities_version: null` AND projects/operations bucketed via `matter_registry.category` (i.e. `_build_legacy_response(cur)` branch exercised).
- `test_safe_describe_unknown_slug_returns_raw` — `_safe_describe()` helper called with a slug NOT in slugs.yml returns the raw slug string, does NOT raise KeyError (catches the `slug_registry.describe()` exception path).

---

## Files Modified

### Create
- `kbl/priorities_registry.py` (~150-200 lines; loader singleton)
- `tests/test_priorities_registry.py` (~10 tests, ~250 lines)
- `tests/fixtures/priorities/_priorities_mini.yml` (~30 lines)
- `tests/fixtures/priorities/_priorities_bad_schema.yml` (~10 lines, for malformed-schema test)

### Modify
- `outputs/dashboard.py` — `get_matters_summary()` at line 3888 (rewrite SQL path + add priorities overlay)
- `outputs/static/app.js` — `_renderMatterSection` at line 1554 (canonical label + severity-from-API)
- `outputs/static/index.html` — cache-bust `app.js?v=N+1` (verify current N first)
- `tests/test_dashboard.py` (or named test file for `/api/dashboard/matters-summary`) — extend coverage
- (CSS — NO changes required; existing palette at `outputs/static/style.css:180-186` already provides all 5 dot classes)

---

## Files NOT to touch

- `baker-vault/wiki/_priorities.yml` — read-only; Director-ratified via Triaga; this brief consumes only.
- `baker-vault/slugs.yml` — separate-repo PR-only (repo CLAUDE.md hard rule).
- `kbl/slug_registry.py` — use existing public API (`describe`, `normalize`); no changes.
- `kbl/ingest_endpoint.py` — render-only scope; no ingest path changes.
- `signal_queue` table / SQL — producer side unchanged per AID scope-lock 2026-05-10.
- `matter_registry` table — legacy fallback retained for inbox flat-bucket category attribution; do NOT modify rows.
- `outputs/static/mobile.css` / `mobile.html` / `mobile.js` — mobile pass deferred to V2 (acceptable per Brisen Desk synthesis — primary is desktop sidebar; mobile sidebar already collapses).
- `kbl/bridge/alerts_to_signal.py` — hot.md consumption pattern; out of scope for sidebar.

---

## Risks

- **Singleton pattern adherence:** `priorities_registry` follows the EXACT pattern used by `slug_registry` (module-level `_cache: Optional[_PrioritiesRegistry]` + `_lock = threading.Lock()` + `_get_registry()` double-checked-lock function). NOT `_get_global_instance()` style — that CLAUDE.md hard rule targets specifically `SentinelRetriever()` / `SentinelStoreBack()` (covered by `scripts/check_singletons.sh`). Do NOT invent a `_get_global_instance()` method on a class for `priorities_registry`; copy slug_registry's module-level pattern verbatim. CI guard does NOT currently extend to this new module — acceptable for a Director-curated content loader (file-missing is fail-soft, not infrastructure-critical).
- **Fail-soft on missing file vs slug_registry fail-loud:** intentional divergence — `slugs.yml` is infrastructure (validator gates ingest); `_priorities.yml` is content (Director-curated). Document divergence in module docstring.
- **Cache-bust skip** (Frontend rule, frontend.md): iOS PWA hard caches — MUST bump `?v=N` on `app.js` reference in `index.html`. If skipped, Director sees old code from cache for 24h+.
- **Multi-slug row semantics drift:** if a Triaga later puts the same slug in TWO priority rows with different importance, `severity_for` returns highest. Document the rule in module docstring + test it explicitly. (`_priorities.yml` shape currently doesn't have this case but future Triagas might.)
- **Unbounded query** (Python backend rule): alerts query needs `LIMIT 500`. Current code has no LIMIT — this brief adds one.
- **conn.rollback on exception** (Python backend rule): existing endpoint has `try: ... finally: store._put_conn(conn)` but no `except`. Add `except` with `conn.rollback()` + log + 503 (already wrapped in outer try/except HTTPException pattern; mirror it).
- **Function-signature drift** (Lesson #44 / #45): verified `slug_registry` public API by grep before writing this brief. Code-Brisen must NOT improvise on `describe`/`normalize` signatures — they're verified at `kbl/slug_registry.py:215` (`describe`) and `kbl/slug_registry.py:195` (`normalize`).
- **Missing import for new module** (Lesson cousin): when adding `from kbl.priorities_registry import ...` to `outputs/dashboard.py`, verify imports block compiles. py_compile check mandated below.
- **CSS dot class additions:** NOT needed. Existing palette at `outputs/static/style.css:180-186` provides all 5 classes (red/amber/blue/slate/lgray). Severity-to-class mapping documented inline in Step 3 JS. Don't introduce out-of-palette colors.
- **iOS PWA viewport (375px)** (Frontend rule): test sidebar collapses + new dot classes render correctly at narrow viewport.
- **Render restart survival:** loader caches in-memory; restart re-reads. No persistence needed.
- **Backwards compat for clients reading `worst_tier`:** keep `worst_tier` in response (tooltip / debug); just stop using it as primary severity driver. No downstream API consumers known.

---

## Code Brief Standards (mandatory)

- **API version:** internal Python only. No external API calls. `_priorities.yml` schema_version 1 verified 2026-05-10 (file frontmatter).
- **Deprecation check date:** N/A — internal Python; no external deprecation surface.
- **Fallback:** if `_priorities.yml` missing/malformed at runtime, `get_all()` returns `[]`, sidebar response uses legacy `worst_tier`/`item_count` path. Sidebar does NOT crash; warns to log once.
- **DDL drift check:** zero DDL. Verify with `grep -E "INSERT|UPDATE|DELETE|CREATE TABLE|ALTER" outputs/dashboard.py kbl/priorities_registry.py` — must return ONLY pre-existing matches (no new lines in `priorities_registry.py`; existing DDL in `dashboard.py` unrelated to this endpoint).
- **Literal pytest output mandatory:** Ship report MUST include literal `pytest tests/test_priorities_registry.py tests/test_dashboard.py::test_matters_summary_priorities_overlay tests/test_dashboard.py::test_matters_summary_severity_from_priority_not_worst_tier tests/test_dashboard.py::test_matters_summary_dismissed_slug_excluded tests/test_dashboard.py::test_matters_summary_priorities_unavailable_falls_back -v` stdout. ≥15 tests expected (10 registry + 5 endpoint). NO "passes by inspection."
- **LLM calls:** none in this brief. Render-only data layer.
- **Mobile rendering:** verify sidebar at 375px viewport — Lesson family on iPhone PWA. Include screenshot in ship report (Director uses PWA primarily).

---

## Verification criteria

1. **pytest unit suite passes:**
   ```
   pytest tests/test_priorities_registry.py tests/test_dashboard.py -v
   ```
   ≥15 net new tests pass. Existing dashboard tests unaffected.

2. **py_compile clean:**
   ```
   python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True); py_compile.compile('kbl/priorities_registry.py', doraise=True)"
   ```
   Exit 0.

3. **Real-vault endpoint smoke:** with `BAKER_VAULT_PATH=/Users/dimitry/baker-vault`:
   ```
   curl -s -H "X-Baker-Key: $BAKER_API_KEY" http://localhost:8080/api/dashboard/matters-summary | jq
   ```
   - Response includes `priorities_version: 1` + `priorities_ratified_at: "2026-04-29T18:45:00+02:00"`.
   - `projects[]` includes entries for `mrci`, `lilienmatt`, `annaberg`, `aukera`, `franck-muller`, `nvidia-corinthia` (Triaga-active slugs WITHOUT pending alerts).
   - `projects[]` does NOT include `kitz-kempinski` (Director-dismissed Q34).
   - Hagenauer entry: `severity: "critical"`, NOT `worst_tier: 1+slate`.
   - Each row has `display_label` = `slug_registry.describe()` output (e.g. `mrci` → "MRCI GmbH — Baden-Baden 50% / AO 50% direct" or whatever slug_registry returns).

4. **UI smoke (production cockpit, post-deploy):**
   - Projects section: shows ≥10 entries (today shows 5). mrci, lilienmatt, annaberg, aukera visible.
   - Kempinski Kitzbühel: GONE.
   - Hagenauer: red dot (critical), not slate.
   - Cyprus Holding / Family Wealth Overview / Swiss Tax / Owner's Lens: moved out of admin-only Operations (these are not in `_priorities.yml`; should appear as low-priority or filtered).

5. **Mobile viewport smoke (375px wide, iOS PWA):**
   - Sidebar collapses correctly.
   - New dot classes render with correct muted colors.
   - Cache bust verified (new `app.js?v=N` served).

6. **DDL drift verification:**
   ```
   grep -E "INSERT|UPDATE|DELETE|CREATE TABLE|ALTER" kbl/priorities_registry.py
   ```
   Returns 0 lines.

7. **Fallback verification:** temporarily move `_priorities.yml` aside; call `priorities_registry.reload()`; curl endpoint; assert response shape carries `fallback_mode: "legacy_no_priorities"` and `priorities_version: null`; sidebar renders the LEGACY shape (projects/operations/inbox bucketed by `matter_registry.category`, dot color from `worst_tier`). The explicit `_build_legacy_response(cur)` branch in Step 2 makes this path deterministic — Code Brisen MUST keep that branch intact and exercised by a test.

8. **Singleton verification:** grep for direct instantiation of priorities loader class in test fixtures; must use module-level `get_all()` / `reload()` API only.

---

## Phase split — what Phase 1 does NOT do (AID-flagged 2026-05-10)

**This brief is Phase 1 (render hygiene). It does NOT implement Ask #4 from the original cockpit review.**

Ask #4 from the Brisen Desk synthesis was "wire Director interactions on the sidebar (ratify / dismiss / snooze / open) to emit Gold writes per B6 + I6." Without that, Phase 1 is hygiene only — sidebar renders correctly but Director's clicks don't train Cortex.

**Phase 2 brief = `CORTEX_COCKPIT_GOLD_WRITES_1`** (separate brief, AH1 authors next session). Scope: frontend click/right-click handlers on sidebar items + backend POST endpoint(s) + Gold-write row schema (matter_slug, action_kind ∈ {ratify, dismiss, snooze, open}, timestamp, director_id, optional gold_write_text) + idempotency/rate-limit + tests. Phase 2 IS the B6 + I6 implementation surface. Phase 2 depends on Phase 1 merging first (builds on the rendered sidebar).

**Cross-links (corrected):**
- Phase 1 cross-links: B2 only (cockpit reads stable `_priorities.yml` contract).
- Phase 2 cross-links: B6 + I6 (Phase 2 implements the Gold-write capture flow).
- This brief does NOT close out B6 or I6 tracker entries. Phase 2 does.

---

## Out of scope

- **Inbox flat-bucket flattening** — Brisen Desk §E observation; separate brief (not B2-dependent either).
- **People panel** — Director flagged as separate issue.
- **Ideas / Media tabs** — empty, not in this scope.
- **`_priorities.yml` schema changes** — Director ratifies via Triaga.
- **signal_queue producer-side changes** — AID scope-lock 2026-05-10.
- **"Operations" section's admin-only items (Cyprus Holding, Family Wealth Overview, Swiss Tax & Banking, Owner's Lens)** — these need `_priorities.yml` additions via a fresh Triaga; brief CANNOT add them by inference.
- **Auto-fix for one-way slug drift in alerts table** — alerts.matter_slug strings carry legacy values; this brief reads-only.
- **Mobile sidebar rewrite** — mobile already collapses; new dot classes verified in 375px smoke but no structural mobile changes.
- **CSS theme overhaul** — only the 3 new dot color classes (`orange`/`amber`/`grey`); existing `.red` / `.slate` unchanged.
- **`/api/dashboard/matters-summary` API contract removal of `worst_tier`** — retained for tooltip / debug; future deprecation deferred.

---

## Branch + PR

- Branch: `cortex-cockpit-sidebar-wiring`
- PR title: `CORTEX_COCKPIT_SIDEBAR_WIRING: cockpit sidebar reads _priorities.yml + canonical labels from slugs.yml`
- **Reviewer pass MANDATORY:** `feature-dev:code-reviewer` (per AID scope-lock 2026-05-10) — confidence-based filtering; HIGH issues only.
- **Tier-A merge:** YES (user-facing surface change to cockpit). `/security-review` skill MANDATORY (Lesson #52). Run on PR before merge.
- **Cross-team review:** AI Head B per autonomy charter §4.
- **AID scope-confirm gate:** Before dispatch from AI Head A to Code Brisen, AH1 surfaces brief to AID in chat. AID reads + confirms render-only scope match. Only then b-code mailbox flip.

## §6C orchestration note (B-code dispatch coordination)

CORTEX_COCKPIT_SIDEBAR_WIRING is parallel-safe with:
- B3 fold-fix (CORTEX_TIER_B_RUNTIME_V1, PR #179) — touches `orchestrator/tier_b_*` paths; zero overlap with `outputs/dashboard.py:3888` or `outputs/static/app.js:1554`.
- M1 remaining briefs (COUNTERPARTY_PROFILE_SCHEMA_1, HAGENAUER_SUBCONTRACTOR_PROFILES_1) — touch `kbl/` schema layer; zero overlap with this brief's render-layer files.

This brief touches `kbl/priorities_registry.py` (new), `outputs/dashboard.py` (one endpoint), `outputs/static/app.js` (one function), `outputs/static/index.html` (one cache-bust line), and `tests/` (new files + extension). No file conflicts with any current or queued b-code dispatch.

**Dispatch sequencing:** Hold for AID scope-confirm. Dispatch to b2 (currently free, Brisen Lab Surface 6A completed 2026-05-05). b2's mailbox `CODE_2_PENDING.md` is currently WhatsApp resolver COMPLETE — overwrite per `_ops/processes/b-code-dispatch-coordination.md` §3 mailbox hygiene.

---

## Co-Authored-By

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
