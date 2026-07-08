# SHIP REPORT — AO_LABEL_MAP_CANONICAL_FIX_1

| Field | Value |
|---|---|
| built_by | deputy (AH2) — re-routed from deputy-codex (dead seat) per lead #6802 |
| branch | `deputy/ao-label-map-canonical-fix-1` (off origin/main @60e2d3e) |
| task class | classifier label-map fix + registry rename; Option A per lead #6822 |
| gate | G1 self ✅ → codex G3 (gate/ao-label-map-g3, effort=medium) → lead merge → AC4 post-deploy |

## ROUND-2 ADDENDUM (deputy, 2026-07-08) — codex G3 FAIL #6935 remediation

**Why round-1 was incomplete (codex #6934/#6935, valid P1):** round-1 only flipped the
`'Oskolkov'` hint value. But the real AO corpus lives under `/Baker-Feed/AO_MASTER/…`
folders that contain **no literal `Oskolkov` substring** — they contain `RG7`, so the generic
`'RG7' -> 'Riemergasse 7'` hint won first-match and mislabeled them. Round-1's AC1 test masked
this by using a path that literally contained `Oskolkov`.

**Round-2 fix (surgical, zero non-AO blast radius):**
1. **`tools/document_pipeline.py`** — added two **root-scope** keys at the TOP of
   `PATH_MATTER_HINTS`: `'AO_MASTER' -> 'Oskolkov'` and `'AO_RG7' -> 'Oskolkov'`. Because
   `get_path_matter_hint` returns first-match, placing the AO root scope first makes it beat
   both the generic `'RG7'` hint AND any subfolder-name collision. Matcher logic UNCHANGED
   (no global reordering) — the only paths whose hint changes are those containing `AO_MASTER`/
   `AO_RG7`, and (verified prod) those strings appear **only** in AO docs. Every non-AO path's
   output is byte-identical to before.
2. **`tests/test_document_pipeline_matter_hint.py`** — added 4 parametrized AC1 tests using
   **real prod source_paths** (one per AO_MASTER subtree family + the 1 email doc outside
   AO_MASTER), a generic-`RG7`→Riemergasse regression test (proves AO keys don't steal genuine
   Riemergasse docs), and a **foot-gun ordering guard** asserting AO keys iterate before `RG7`.

**Prod evidence (read-only, `documents` table):** 597 docs under `AO_MASTER` currently scattered
across **10 wrong matters** (Baker 82, Financing 37, Cupial/Kitzbühel/Cap-Ferrat/MO-AM/Brisen-AI…);
268 contain `AO_RG7`, of which exactly **2** live outside `AO_MASTER` (both AO reconciliation docs
— caught by the standalone `AO_RG7` key). Codex's 305 was the RG7-collision subset; this fix
covers the full 597-doc AO_MASTER corpus.

**Tests:** `BAKER_VAULT_PATH=… pytest tests/test_document_pipeline_matter_hint.py -v` → **11 passed**.

**Scope note:** this is the LIVE-hint fix for docs going forward. The 597 already-stored
mislabels are re-tagged by the offline `backfill_matter_from_path.py` (separate, lead-coordinated),
not by this code change.

---

## What shipped (surgical — 3 code files + 1 new test)

1. **`tools/document_pipeline.py:118`** — `PATH_MATTER_HINTS['Oskolkov']`: `'Oskolkov-RG7'` → `'Oskolkov'`. The retired combined label is no longer minted; `'Oskolkov'` normalizes to canonical slug `ao` (verified `slug_registry.normalize('Oskolkov') == 'ao'`).
2. **`memory/store_back.py:3931`** — matter_registry category-seed tuple: `"Oskolkov-RG7"` → `"Oskolkov"` (fresh-deploy consistency with the renamed row).
3. **`scripts/backfill_matter_from_path.py:50-53`** — AO path map: `"Oskolkov-RG7"` → `"Oskolkov"` (2nd AO-scoped mint site; manual one-time CLI, not imported live, but closed for AC2 "no mintable path").
4. **`tests/test_document_pipeline_matter_hint.py`** (NEW) — AC1/AC2 + regression.

## Live registry rename — DEPLOY STEP (run at merge, coordinated)

- `UPDATE matter_registry SET matter_name='Oskolkov' WHERE id=15 AND matter_name='Oskolkov-RG7'` — audited raw_write, lead-authorized (#6822). UNIQUE-safe: no existing `Oskolkov` matter_name (verified live).
- **Ordering:** run RIGHT AFTER the Render deploy of this branch (hint→'Oskolkov' code live), to minimise the window where the hint says 'Oskolkov' but the active-matter list still says 'Oskolkov-RG7'. Not run yet (avoids a pre-merge prod mismatch).

## Acceptance criteria

- **AC1** — new Oskolkov-folder doc classifies to `ao`: `get_path_matter_hint(oskolkov_path)` names `'Oskolkov'` (not `-RG7`) + `normalize('Oskolkov')=='ao'`. **PASS** (real test output, 5/5).
- **AC2** — `Oskolkov-RG7` not mintable by any code path: not in `PATH_MATTER_HINTS.values()`; backfill AO path map closed. **PASS** (test + grep).
- **AC3** — existing tests pass; diff surgical. **PASS** — my suite 5/5; legacy-fold suites unchanged; 10 pre-existing failures in `test_backfill_matter_slug.py` are env-gated and **fail identically on clean origin/main** (stash-verified — NOT introduced here).
- **AC4** — post-deploy: first live Oskolkov doc after merge carries `ao` — POST_DEPLOY_AC_VERDICT after deploy + the live UPDATE.

## live-PG statement (per Ship-Gate rule @df5b253)

Unit tests are logic-only (hint map + slug normalize) — **live-PG: N/A** (no DB fixture). The registry rename's DB effect is the one-row live UPDATE above, verified by pre/post `baker_raw_query`, not pytest.

## Consumer catalog — literal `Oskolkov-RG7` across baker-master (lead precondition #6822)

| Site | Role | Orphaned by rename? |
|---|---|---|
| `tools/document_pipeline.py:118` | mint (hint) | **FIXED** → 'Oskolkov' |
| `memory/store_back.py:3931` | registry seed name | **FIXED** → 'Oskolkov' |
| `scripts/backfill_matter_from_path.py:50-53` | mint (path map, manual CLI) | **FIXED** → 'Oskolkov' |
| `outputs/dashboard.py:7205` | legacy fold `Oskolkov-RG7→hagenauer-rg7` | NO — handles residual legacy strings; intentionally untouched |
| `kbl/bridge/alerts_to_signal.py:638` | comment (historical) | NO — non-code |
| `scripts/insert_ao_pm_capability.py:99`, `scripts/backfill_matter_slug.py:329` | prompt/comment text | NO — no live label mint |
| `tests/test_dashboard_alert_fold.py`, `tests/test_backfill_matter_slug.py` | assert legacy fold `→hagenauer-rg7` | NO — legacy fold untouched, still green |

No consumer orphaned: the only `→ao` semantics live on the classifier path (fixed here); every remaining `Oskolkov-RG7` string is a legacy `→hagenauer-rg7` fold that this fix deliberately leaves intact.

## Follow-up (OUT of this brief, lead #6822)

- **slugs.yml `oskolkov-rg7 → hagenauer-rg7` mis-alias** (baker-vault-slugs, line 28) — CONFIRMED landmine. Separate-repo PR to draft after this ships; post to lead for merge.
