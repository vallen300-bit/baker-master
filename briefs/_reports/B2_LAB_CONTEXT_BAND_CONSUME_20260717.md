# B2 ship report — Cockpit context-band consumer (deliverable 4)

- **Date:** 2026-07-17
- **Dispatch:** bus #12404 (lead) — Phase-2 cutover, deliverable 4: wire per-seat context telemetry onto the cockpit card faces so the D4 context band renders real data.
- **Brief context:** `briefs/_tasks/LAB_CONTEXT_BAND_EXPOSURE_1.md` (Lab side) + codex-arch contract #12055.
- **Branch / PR:** `b2/cockpit-context-band-consume` → PR #594 (base main).
- **Commits:** `55ef2a66` (feat), `8f0f10a1` (codex P2 fix).

## What shipped
Cockpit-side consumer only. The Lab context-band slice (`LAB_CONTEXT_BAND_EXPOSURE_1`, builder deputy-codex, brisen-lab repo) exposes per-seat usage as `context_used_percent` on `GET /api/v2/terminals`. The cockpit page's D4 band (`cockpit_static/cockpit.js`) renders `row.context_pct` (0-100, green→amber→red by usage). This change bridges the two in `scripts/cockpit_controller.py`:

- `derive_context_pct(row)` — maps `context_used_percent` → `context_pct`; null-safe, clamped [0,100], rejects bool / non-numeric / non-finite; honors an explicit `context_pct` if the Lab ever emits one.
- `glance_row_from_lab(row)` — single projection point; keeps the "only pinned `GLANCE_FIELDS`, no body/transcript leak" guarantee and adds the derivation. `LabGlance.read()` now calls it.

## Contract hard rules (#12055) — all held + tested
- Absent / stale (Lab nulls its own fields >900s) / null ⇒ `context_pct` None ⇒ band hides. No invention.
- **Session age NEVER feeds the band** (codex-arch OBJECT) — mapping reads only the usage percent; `test_derive_context_pct_never_reads_session_age`.
- No transcript / body / session-uuid leak — `test_glance_row_from_lab_projects_pinned_fields_and_context`.
- bool ≠ percent; values clamped; NaN/±inf hide the band.

## Tests
`pytest tests/test_cockpit_controller.py` → **15 passed**. 7 new tests added.

## Codex gate
Codex verify (gpt-5.6-luna, `-e high`): **PASS-WITH-NOTES**, session `019f718c-00de-7ee0-aa8a-1da82df37a97`. One P2 (NaN/inf → false full band) folded into `8f0f10a1`.

## Dependency / open item (reported to lead #12413)
Live `/api/v2/terminals` carries **no** context fields today — the Lab slice `LAB_CONTEXT_BAND_EXPOSURE_1` (deputy-codex, #12055) is **not live**. The consumer is null-safe (band hidden exactly as before) and lights up the moment Lab exposes `context_used_percent`. **The live "real data on card faces" AC (POST_DEPLOY_AC) is gated on that Lab slice deploying** — verification to follow once it lands.
