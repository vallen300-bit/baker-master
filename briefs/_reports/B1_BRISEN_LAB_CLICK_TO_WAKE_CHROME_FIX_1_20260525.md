---
brief_id: BRISEN_LAB_CLICK_TO_WAKE_CHROME_FIX_1
reporter: b1
report_date: 2026-05-25
pr_url: https://github.com/vallen300-bit/brisen-lab/pull/37
branch: b1/brisen-lab-click-to-wake-chrome-fix-1
base: main
commit: d0025a0
status: SHIPPED
reply_target: cowork-ah1
---

# B1 ship report — BRISEN_LAB_CLICK_TO_WAKE_CHROME_FIX_1

## Summary

Single PR against `vallen300-bit/brisen-lab`. Two-file change:
- `static/app.js` (~14 lines added / 3 changed) — replaced `window.location.href = "brisen-lab://..."` with anchor-click pattern inside the existing card click handler. Synthetic `<a>`, `display:none`, `appendChild` → `click()` → `remove()`, fully synchronous so Chrome's user-activation tracker keeps the activation context from the outer click.
- `static/index.html` — cache-bust `app.js?v=15` → `app.js?v=16`.

DOM, badge-gating (`hasBadge && wakeable && !ev.shiftKey`), shift-click escape hatch, detail-modal fallback, and `tools/wake-handler/*` all unchanged per brief constraints.

## Quality checkpoints

### QC1 — anchor-click pattern present

```
$ grep -n "anchor-click\|a.click()" static/app.js
897:// window.location.href to anchor-click. Chrome blocks the former for custom
914:      a.click();
```

PASS (line 897 = inline reference comment in brief-mandated comment block; line 914 = the synthetic anchor's `.click()` call).

### QC2 — old `window.location.href = "brisen-lab` removed

```
$ grep -c 'window.location.href = "brisen-lab' static/app.js
0
```

PASS.

### QC3 — `index.html` bumped to `v=16`

```
$ grep "app.js?v=" static/index.html
  <script src="/static/app.js?v=16"></script>
```

PASS.

### QC4-6 — Chrome-side live verification

Deferred to Director / Chrome post-merge per brief §Verification: the static asset is Render-served, no local dev server runs the dashboard, and PR-branch deploys aren't wired on this repo. PR description includes the full Chrome test plan for cowork-ah1 / Director to step through after Gate-5 merge.

## Artefacts

- PR: https://github.com/vallen300-bit/brisen-lab/pull/37
- Branch: `b1/brisen-lab-click-to-wake-chrome-fix-1` @ commit `d0025a0`
- Base: `main` @ `66109ce`
- Diff stat: `static/app.js | 14 ++++++++++++--`, `static/index.html | 2 +-`

## JS sanity

```
$ node --check static/app.js
JS OK
```

## Gate chain (handing off)

- Gate-1 architecture: deputy (AH2)
- Gate-2 `/security-review`: deputy (AH2) — trivial DOM-only JS diff
- Gate-3 picker-architect: SKIP (no install / symlink change)
- Gate-4 code-reviewer 2nd-pass: deputy (AH2)
- Gate-5 merge: cowork-ah1

## Notes

- No try/catch wrapping `a.click()` per brief constraint — if the launch ever re-breaks, the Chrome console error is the diagnostic signal we want.
- Anchor element removed synchronously inside the same call frame; no `setTimeout` / microtask defer.
- Comment block in `app.js` preserves the PR #34 attribution line and adds the FIX_1 explanation for future readers.
