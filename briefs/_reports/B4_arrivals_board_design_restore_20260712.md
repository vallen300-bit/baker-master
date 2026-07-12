# B4 ship report — ARRIVALS_BOARD_DESIGN_RESTORE

- **Brief / dispatch:** bus #9293 (from `deputy`, Director order via lead #9289). Tier-B. Own build+verify, **do NOT self-merge**.
- **Repo:** baker-master · **PR:** #532 · **Branch:** `b4/arrivals-board-design-restore` (`f57a3e61`)
- **Reply target:** lead (+ deputy) · **Date:** 2026-07-12
- **Gate chain:** build → codex G3 gate (#9330 to `codex`) → lead merge (= deploy) → Director eyeballs live.

## Problem
The live arrivals board drifted from the approved frozen design (`~/baker-vault/_ops/build/baker-os-v2/05_outputs/flight-dashboards/arrivals-board-v6.html`, 8 Jul) through the PR #524 "V8-port" styling lineage. The register — palette, header treatment, tile sizing, spacing — changed while the content kept growing.

## Diagnose — register drift enumerated (live → frozen)
Diff scope was the **design register only** (typography / colors / spacing / card-row / header), per brief.

| Area | Live (drifted) | Frozen v6 (restored) |
|---|---|---|
| `--line` (table lines) | `#3A453B` (lightened/greened) | `#1E211D` |
| `--amber` | `#FFD267` | `#FFC64B` |
| `--white` | `#FFFDF3` | `#EFECE2` |
| `--green` | `#69DF83` | `#41D96E` |
| `--dim` / `--pend` / `--bg` / `--panel` / `--head` / `--tile-shadow` | V8 values | frozen values (both themes) |
| Header | `display:grid` + big `box-shadow`, border 1px, radius 8, pad 22/26, gap 28 | frozen `flex`, border 2px, radius 6, pad 14/20, gap 16, no shadow |
| `h1` | `37px / .16em` | `24px / .20em` |
| `.brand` / `.btn` / `.clock` | V8 type + spacing | frozen type + spacing |
| Tiles | `.tile 14×23 r3 11px` + `.tile.meta` (8×18 dim) + `.tile.wht` (9×21) shrink | uniform frozen `15×23 r2 11.5px`; meta/wht = **color only**, full size |
| Table | `table-layout:fixed` + `<colgroup>` %widths + `box-shadow` | frozen `auto`, 2px border, r6, no shadow |
| `thead/tbody` padding | 15/18, td height 76px | frozen 11/10 + 13/10 |
| `.foot` | `8px / .12em` | `10px / .20em` |
| Flap settle | `950 + i*70` ms | frozen `220 + i*30` ms |

## Restore — surgical, template-only
Single file changed: `outputs/templates/arrivals_board_template.html` (`git diff --stat origin/main`: +48 / −70, one file). **No Python, no data bindings touched** — `orchestrator/arrivals_board.py` row generator unchanged; `__ROWS__` / `__STAMP__` placeholders and all `data-cls` classes preserved.

### Judgment calls (preserved as content/robustness, NOT register)
1. **`--red` / `.tile.red`** — the DELAYED status color. It's a content binding the row generator emits (`status == "DELAYED"`), but the frozen *static demo* has no delayed flight, so there is no frozen red to "restore to." Kept live's red unchanged. Flagged to codex.
2. **`<meta http-equiv="refresh" content="120">` + favicon** — live board auto-refreshes; frozen is a static demo. Kept.
3. **`overflow-x:auto` table wrapper** — invisible on desktop (no register change), prevents mobile-PWA horizontal overflow (frontend rule: 375px). Kept, but **dropped** the register-altering `@media (max-width:1180px)` tile/column resize the V8 port added.

These three are the only deviations from a byte-faithful frozen restore; each is content/robustness, not the Director-facing desktop register.

## Verify (verify-dashboard-render — applicable gates)
- **Real-browser render:** template rendered through the **live** `arrivals_board._row_html` generator (identical sample rows for old vs new), Chrome port 9222.
- **Interact:** light-mode toggle exercised via the VIEW handler → `bg #E9E9E4`, `amber #8A6300` (frozen light values). ✅
- **Console:** zero messages / zero errors. ✅
- **Register match:** AFTER vs FROZEN_REFERENCE screenshots align on h1 size, muted amber, uniform tiles, dark table lines, panel width, foot. ✅
- **Tests:** `python3 -m pytest tests/test_arrivals_board.py tests/test_cockpit_serve.py -q` → **11 passed, 1 skipped**. No test asserted on the reverted CSS.
- **Screenshots:** `briefs/_reports/arrivals_shots/` — `BEFORE.png` (drifted), `AFTER.png` (restored dark), `AFTER_light.png`, `FROZEN_REFERENCE.png`. (DELAYED-red rows in the samples are content, not register — accepted reflow.)

## Acceptance criteria
- **(a)** design register matches frozen v6 (typography/color/spacing/card-row/header) — ✅
- **(b)** content bindings unchanged + reflow accepted — ✅ (generator untouched; more rows reflow)
- **(c)** before/after screenshots + verify-dashboard-render — ✅
- **(d)** codex gate PASS — **routed to `codex` (#9330)**; verdict pending → routes to lead + b4
- **(e)** report PR + verdict to lead — ✅ (bus #9331)

## Deploy
No env vars, no migrations — template-only. Render auto-deploys on merge to main.
