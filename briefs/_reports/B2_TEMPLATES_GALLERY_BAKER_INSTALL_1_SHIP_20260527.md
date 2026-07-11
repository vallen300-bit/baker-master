---
report: B2_TEMPLATES_GALLERY_BAKER_INSTALL_1
to: lead
from: b2
status: SHIPPED_PENDING_MERGE
shipped_at: 2026-05-27
pr: https://github.com/vallen300-bit/baker-master/pull/268
branch: b2/templates-gallery-baker-install-1
brief: briefs/BRIEF_TEMPLATES_GALLERY_BAKER_INSTALL_1.md
companion: TEMPLATES_GALLERY_LAB_INSTALL_1 (b4, brisen-lab)
---

# B2 ship report — TEMPLATES_GALLERY_BAKER_INSTALL_1

## Status
Shipped to PR #268, awaiting Gate-1/2 review + AH1-T merge. Pre-merge live probe of `https://brisen-docs.onrender.com/templates/` returns 404 (expected — Render redeploys static site on merge to main).

## What shipped
1. **Gallery HTML** — `docs-site/templates/index.html` (byte-identical copy of hag-desk staged source, 218 lines).
2. **Sample stubs** — 8 placeholder `.html` files under `docs-site/templates/samples/` for T1-T4 sample/blank hrefs (`.docx` deferred to hag-desk follow-up per brief).
3. **Both manifests** — `TEMPLATES` block inserted at top of `docs-site/index.json` AND `outputs/static/presentations.json`; `updated_at` bumped to 2026-05-27 in both.
4. **Baker dashboard nav** — `nav-item-external` anchor placed exact slot Documents → Templates Gallery → Dossiers in `outputs/static/index.html`; `target=_blank rel=noopener noreferrer`.
5. **CSS** — `.nav-item-external` rule in `outputs/static/style.css` (no underline, inherit nav color); cache-bust `style.css?v=78 → v=79`.

## Quality checkpoints — local
| # | Check | Result |
|---|-------|--------|
| 1 | Both JSON manifests parse-clean | ✅ both load via `json.load`, `folders[0].name == "TEMPLATES"`, `updated_at == "2026-05-27"` |
| 2 | Nav anchor placed between Documents/Dossiers | ✅ verified at `outputs/static/index.html` lines 110-117 |
| 3 | `target=_blank` + `rel=noopener noreferrer` | ✅ XSS-safe external link |
| 4 | Local serve probe — gallery 200 | ✅ `python3 -m http.server` returned 200 + 6393 bytes |
| 5 | Local serve probe — sample stubs 200 | ✅ all 8 `.html` stubs return 200 |
| 6 | Local serve probe — `.docx` 404 | ✅ intentional, deferred per brief |
| 7 | `wc -l docs-site/templates/index.html` | ✅ 218 (unchanged from staged) |
| 8 | Gallery file identical to staged source | ✅ `diff -q` clean |

## Live probe (post-merge — reviewer Gate)
Per brief §Gate-1+2 reviewer instruction: load `https://brisen-docs.onrender.com/templates/` after Render auto-deploy and confirm 200 + 5-card cream/navy render. Pre-merge: 404 (expected).

## Files modified
```
A docs-site/templates/index.html (NEW, 218 lines)
A docs-site/templates/samples/t1-blank-template.html (NEW, stub)
A docs-site/templates/samples/t1-per-line-claim-report.html (NEW, stub)
A docs-site/templates/samples/t2-blank-template.html (NEW, stub)
A docs-site/templates/samples/t2-cross-case-audit.html (NEW, stub)
A docs-site/templates/samples/t3-blank-template.html (NEW, stub)
A docs-site/templates/samples/t3-strategic-memo.html (NEW, stub)
A docs-site/templates/samples/t4-blank-template.html (NEW, stub)
A docs-site/templates/samples/t4-matter-evidence.html (NEW, stub)
M docs-site/index.json (TEMPLATES folder added at index 0)
M outputs/static/presentations.json (TEMPLATES folder added at index 0)
M outputs/static/index.html (new nav-item-external anchor + cache-bust v=79)
M outputs/static/style.css (.nav-item-external rule)
M briefs/_tasks/CODE_2_PENDING.md (status PENDING → IN_PROGRESS)
```

## Notes
- No backend touched (`outputs/dashboard.py` unchanged per brief §Do NOT Touch).
- No `switchTab()` registration — external anchor handles new-tab via native `target="_blank"`.
- iOS PWA cache-bust applied per `.claude/rules/frontend.md` (v=78 → v=79 on `style.css`).
- Static-serve probes via `python3 -m http.server` rather than `python outputs/dashboard.py` — change is static-asset-only, FastAPI server stack requires Postgres + Anthropic credentials not loaded locally. Reviewer Gate covers the live `brisen-docs.onrender.com/templates/` confirmation per brief.
