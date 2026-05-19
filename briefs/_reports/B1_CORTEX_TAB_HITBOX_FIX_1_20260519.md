---
brief_id: DASHBOARD_CORTEX_TAB_HITBOX_FIX_1
builder: b1
shipped_at: 2026-05-19T16:55:00Z
pr: 224
pr_url: https://github.com/vallen300-bit/baker-master/pull/224
branch: b1/cortex-tab-hitbox-fix-1
head_sha: da87b66
dispatched_by: lead
reply_target: lead
bus_topic: ship/cortex-tab-hitbox-fix-1
trigger_class: LOW
files_changed: 2
loc: +18 / -1
---

# B1 ship report — DASHBOARD_CORTEX_TAB_HITBOX_FIX_1

## What shipped

CSS-only hot-fix for Director-blocking Cortex tab hitbox bug. PR #224 against `main`.

**Files:**

- `outputs/static/style.css` — override `.grid-cell-header.grid-header-cortex .grid-cell-count` to `position: static` (joins flex flow, no longer overlays tabs); add compact styling so the long count text doesn't dominate; tabs gain `flex-shrink:0 + z-index:1` defensively.
- `outputs/static/index.html` — cache-bust `style.css ?v=74` → `?v=75`.

Total: +18 / -1 LOC, 2 files.

## Root cause

`.grid-cell-header .grid-cell-count` was `position: absolute; right: 16px;` — designed for non-cortex grid headers (Label + Count only). When the Cortex card added tabs via `.cortex-tabs { margin-left: auto }` (DOM order: Label, Tabs, Count), the abs-positioned count overlaid the tabs at the right edge. With PR #223's longer count text ("30 events, 20 lint, 18 pending"), the count span grew leftward across all 4 tabs. `elementFromPoint` at the geometric center of every tab returned `#cortexCount` instead of the BUTTON → clicks intercepted.

## Verification

### pytest (mandatory literal output)

```
$ source .venv-b1/bin/activate && python -m pytest tests/test_dashboard*.py -v
...
======================== 45 passed, 7 warnings in 0.56s ========================
```

45 passed, 0 failed.

### `elementFromPoint` (mandatory per brief Ship gate §2)

Built Chrome MCP harness mirroring prod cortex header DOM exactly (Label / 4 tab buttons / cortexCount span with "30 events, 20 lint, 18 pending"), loaded against patched `outputs/static/style.css`:

```json
[
  {"id":"cortexTabEvents","rect":{"top":69,"left":447,"w":57,"h":19},
   "hitId":"cortexTabEvents","hitTag":"BUTTON","hitMatches":true},
  {"id":"cortexTabDedup","rect":{"top":69,"left":508,"w":57,"h":19},
   "hitId":"cortexTabDedup","hitTag":"BUTTON","hitMatches":true},
  {"id":"cortexTabLint","rect":{"top":69,"left":569,"w":42,"h":19},
   "hitId":"cortexTabLint","hitTag":"BUTTON","hitMatches":true},
  {"id":"cortexTabPending","rect":{"top":69,"left":614,"w":65,"h":19},
   "hitId":"cortexTabPending","hitTag":"BUTTON","hitMatches":true}
]
```

All 4 tabs: `elementFromPoint(rect.left + w/2, rect.top + h/2) === el`.

Count layout: `position: static`, sits right of last tab (`countRect.left=699`, last tab right edge ~679, no overlap).

Programmatic click test (calls `hit.click()` at center, captures `_cortexTab` arg):

```json
[
  {"id":"cortexTabEvents",  "fired":"events"},
  {"id":"cortexTabDedup",   "fired":"dedup"},
  {"id":"cortexTabLint",    "fired":"lint"},
  {"id":"cortexTabPending", "fired":"pending"}
]
```

All 4 fire the correct handler.

## Scope discipline

CSS-only, no JS / DB / endpoint / auth changes. Did NOT touch:

- `.grid-cell-header .grid-cell-count` default (non-cortex headers still use absolute positioning — unchanged behavior).
- `app.js _cortexTab` handler (correctly wired per brief diagnostic).
- The count text content / formatting (`30 events, 20 lint, 18 pending` joiner in app.js line 10242 — pre-existing, out of scope).
- Any other grid header / card layout.

## Open items / follow-ups

None blocking. One observation worth a future ticket (NOT in this PR):

- `.grid-cell-count` at font-size 20 / weight 700 was clearly designed for short numeric strings. The cortex card now emits multi-segment text. Compact styling in this patch handles it, but the broader pattern (header count slots variable in content type) is worth reviewing if other cards adopt similar multi-segment counts.

## Anchors

- Brief: `briefs/_tasks/CODE_1_PENDING.md` (dispatch commit `acacd36`)
- Prior dispatch closeout: BRISEN_LAB_PR22_BUTTON_REPOINT_1 (PR #24 merged `0afb432` 2026-05-19)
- Original cortex ratify panel: PR #223 (`1264ca8`) — introduced the longer count string that triggered overlap
- Director smoke bug: 2026-05-19 ~13:25Z chat
- PR: https://github.com/vallen300-bit/baker-master/pull/224
- Head SHA: `da87b66`
