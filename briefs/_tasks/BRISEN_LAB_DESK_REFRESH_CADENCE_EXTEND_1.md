# BRIEF — BRISEN_LAB_DESK_REFRESH_CADENCE_EXTEND_1

- **Repo:** `brisen-lab` (github.com/vallen300-bit/brisen-lab) — clone fresh, NOT baker-master.
- **Branch:** `b1/brisen-lab-desk-refresh-cadence-extend-1`
- **Reply-target:** `lead` (bus). **Dispatched by:** lead. **Effort:** medium.
- **Director-ratified:** 2026-07-03 ("go ahead" — extend refresh cadence to matter desks).
- **Builds on:** PR #86 (BRISEN_LAB_FLEET_REFRESH_CADENCE_1, merged). Read `app.py` cadence block + `tests/test_refresh_cadence.py` first.

## Problem
The fleet-refresh cadence loop (#86) leaves matter desks uncovered on TWO counts:
1. **Scope:** `CADENCE_SLUGS = ("b1","b2","b3","b4","deputy-codex","codex")` — desks deliberately excluded per #86 AC6 ("heads/desks never touched").
2. **Dark:** `BRISEN_LAB_REFRESH_CADENCE_ENABLED` defaults FALSE; never enabled.

Consequence (2026-07-03): `baden-baden-desk` context expired, session wedged non-responsive (`is_working=True` but no bus check-in across 3h of nudges). Dispatcher escalated 3 stranded airport-ticketing tickets to lead (#5086/#5088/#5092). Lead force-refreshed the desk manually (msg #5094) — but that is reactive. Director ratified making desk-refresh proactive.

## Scope — what changes
Extend the cadence sweep to matter desks, under the SAME safety guards that already protect the coder slugs. **Reverse #86 AC6 for DESKS ONLY. HEADS stay excluded forever.**

- Add a new explicit constant (mirror the `CADENCE_SLUGS` hardcoded-tuple pattern = the AC bound):
  ```python
  DESK_CADENCE_SLUGS = ("hag-desk", "ao-desk", "movie-desk", "baden-baden-desk", "origination-desk")
  ```
- `_refresh_cadence_sweep` iterates `CADENCE_SLUGS + DESK_CADENCE_SLUGS`, calling per alias:
  `_refresh_one(alias, mode="stale_only", confirm_protected=True, force=False)`.
  - `mode="stale_only"` — a desk mid-matter-work is NOT stale → skipped. This is the safety property that makes desk-refresh acceptable.
  - `force=False` — a busy desk QUEUES, never force-killed mid-work.
  - `confirm_protected=True` — required to admit protected desks (same mechanism already used for the 2 protected coder slugs; does NOT widen the iterated set).
- Keep dark-flag semantics intact: zero behavior change while the flag is FALSE. Lead flips `BRISEN_LAB_REFRESH_CADENCE_ENABLED=true` on brisen-lab Render AFTER merge.

## Acceptance criteria (extend the #86 test file — do not weaken existing ACs)
1. Flag OFF → zero sweep, zero behavior change (unchanged from #86).
2. Flag ON → sweep touches EXACTLY `CADENCE_SLUGS + DESK_CADENCE_SLUGS`, each via `_refresh_one(..., mode="stale_only", confirm_protected=True, force=False)` (assert mock call args).
3. **HEADS never touched** — assert no `lead`/`aid`/`deputy`/`aihead1`/`aihead2`/`cowork-ah1` alias is ever passed to `_refresh_one`. Hard bound.
4. A busy desk QUEUES (force=False), never force-killed — explicit test.
5. Per-alias exception does not abort the sweep (unchanged; add a desk-alias case).
6. Existing 12 cadence + 28 refresh-agent tests still pass (no regression).

## Files
- `app.py` — add `DESK_CADENCE_SLUGS` const; extend `_refresh_cadence_sweep` iteration. Surgical, additive.
- `tests/test_refresh_cadence.py` — add desk-set cases (AC2/3/4/5 above).

## Verify (literal, in ship report)
- `python3 -m pytest tests/test_refresh_cadence.py tests/test_refresh_agent.py -q` → paste counts.
- `py_compile app.py`.

## Gate chain
codex G3 (effort medium — additive, guarded) → lead G4 → lead merges → **lead** flips the Render enable flag. Do NOT flip the flag yourself.

## PART 2 — delivery whitelist (CRITICAL; added by lead post-diagnosis 2026-07-03)
Cadence scheduling alone is a HALF-FIX. Live diagnosis today proved desks are
excluded from the **wakeable-terminals whitelist**, so refresh/wake signals do
NOT deliver to a desk:
- `POST /api/wake {alias: baden-baden-desk}` → `{"detail":"unknown alias"}` (400).
- `POST /api/refresh-agent?alias=baden-baden-desk&force=true` → server returns
  `outcome: refreshed` but `expired_session_ids: []` and the desk session never
  restarts; lifecycle/restart+forced-kill land in the desk's bus inbox UNACKED.

So a cadence sweep that calls `_refresh_one("baden-baden-desk", ...)` will post
signals into the void unless desks are ALSO added to the wakeable set that
`/api/wake` + the local `brisen-lab://wake/<alias>` handler validate against.

REQUIRED: locate the wakeable-terminals generator / constant (the source of the
`/api/wake` "unknown alias" whitelist — search `WAKEABLE_TERMINALS`,
`wakeable`, `ALLOWED_ALIASES`, the generated terminal identity artifacts). Add
the 5 matter desks so refresh/wake actually DELIVER. If the wakeable set is
generated from a config the b-code cannot safely edit here, STOP and report the
exact file + line to lead — do NOT ship the cadence half without a delivery path.
Confirm end-to-end in the ship report: a desk alias passed to the cadence sweep
results in an ACKED lifecycle/restart (not an orphaned unacked signal).

## Notes / foot-guns
- Desk slugs are the 5 in `/api/v2/terminals`: hag-desk, ao-desk, movie-desk, baden-baden-desk, origination-desk. If `app.py` has a canonical desk list already, reconcile against it and flag any delta — do NOT silently invent slugs.
- #86 pre-existing flaky autowake/wake-classification tests (9) fail on clean `main` order-dependently — unrelated, do not fix here, note if seen.
