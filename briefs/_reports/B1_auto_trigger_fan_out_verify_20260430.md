# B1 — AUTO_TRIGGER_FAN_OUT_VERIFY_1 — SHIP REPORT (FAIL — GAP)

**Brief:** `briefs/BRIEF_AUTO_TRIGGER_FAN_OUT_VERIFY_1.md`
**Branch:** `b1/auto-trigger-fan-out-verify`
**Builder:** B1
**Date:** 2026-04-30
**Outcome:** **FAIL — gap surfaced. NO patch made (per brief §"If gap surfaced": STOP).**

## TL;DR

Auto-trigger fan-out is broken for **all 22 matters**, not just non-AO. Cost-gate code itself is correct (whitelists by `wiki/matters/<slug>/cortex-config.md` presence — all 3 test matters have configs), but the **dispatch site never feeds it a canonical slug**:

1. `kbl/bridge/alerts_to_signal.py:_dispatch_cortex_for_inserted` calls `maybe_dispatch(matter_slug=signal_row["matter"])` immediately after the `signal_queue` INSERT commits.
2. At INSERT time `signal_queue.matter` is the *raw* `alerts.matter_slug` value (PM-era labels like `Hagenauer`, `Oskolkov-RG7`, `movie_am`, `Mandarin Oriental Asset Management`).
3. Step 1 triage canonicalizes via `slug_registry.normalize()` and writes the result to `signal_queue.primary_matter` — but that runs **AFTER** the dispatch has already fired (and rejected).
4. `triggers/cortex_pre_review_gate.py:matter_has_cortex_config()` therefore looks up `wiki/matters/Hagenauer/cortex-config.md`, `wiki/matters/movie_am/cortex-config.md`, etc. → all return False → `post_gate` returns False → **no Slack DM, no cycle, no audit row**.

Net effect since CORTEX_MULTI_MATTER_GATE_1 shipped: zero auto-trigger Slack DMs for canonical matters. Only 2 historical `cortex:gate:skip` entries exist in `baker_actions` (signals 294, 315, both `matter_slug='movie_am'` on 2026-04-29) — survivors of an earlier window when a `wiki/matters/movie_am/` directory existed; the canonical slug `mo-vie-am` has never received a gate post.

## Verification methodology

Brief §"Test plan" calls for: 3 curl injections + 3 DB observations. The brief's named tables (`signal_classifications`, `cost_gate_decisions`) do not exist in the schema; canonical equivalents queried instead:

| Brief calls it | Actual table |
|----------------|--------------|
| `signal_classifications` | `signal_queue` (`matter`, `primary_matter`) |
| `cost_gate_decisions` | `baker_actions` where `action_type LIKE 'cortex:gate:%'` |
| `cortex_cycles` | `cortex_cycles` ✓ |

No `/api/test/inject-signal` endpoint exists in the codebase (`grep -ri "inject.signal\|test/inject" -- exit 1`). Direct production write was avoided — verification is pure read against live Neon via Baker MCP `baker_raw_query`. This proves the gap empirically without polluting prod with synthetic rows.

## Pre-conditions verified

```bash
# All 3 test matters present + active in slugs.yml
$ grep -E "^  - slug: (hagenauer-rg7|mo-vie-am|lilienmatt)$" /Users/dimitry/baker-vault/slugs.yml -A 1
  - slug: hagenauer-rg7
    status: active
  - slug: mo-vie-am
    status: active
  - slug: lilienmatt
    status: active

# All 3 have cortex-config.md → matter_has_cortex_config() would PASS
$ for s in hagenauer-rg7 mo-vie-am lilienmatt; do
    ls /Users/dimitry/baker-vault/wiki/matters/$s/cortex-config.md
  done
/Users/dimitry/baker-vault/wiki/matters/hagenauer-rg7/cortex-config.md   (12,987 B, 2026-04-29)
/Users/dimitry/baker-vault/wiki/matters/mo-vie-am/cortex-config.md       ( 3,392 B, 2026-04-30)
/Users/dimitry/baker-vault/wiki/matters/lilienmatt/cortex-config.md      ( 3,353 B, 2026-04-30)
```

## Per-matter findings (PROD DB read-only)

### Q1 — historical auto-trigger cycles by matter & trigger source

```sql
SELECT matter_slug, triggered_by, status, COUNT(*) FROM cortex_cycles GROUP BY 1,2,3;
```

| matter_slug | triggered_by | count | comment |
|-------------|--------------|-------|---------|
| `Financing Vienna & Baden-Baden` | signal | 1 | 2026-04-28 — non-canonical (raw classifier label) |
| `German Property Tax` | signal | 1 | 2026-04-28 — non-canonical |
| `hagenauer-rg7` | director_manual / scan_intent | 2 | both Director-fired, never auto |
| `movie` | director_manual | 1 | non-canonical |
| `nvidia-corinthia` | director_manual | 1 | manual |
| `oskolkov` | director / director_manual / post_deploy_smoke | 15 | manual + smoke |

**No `triggered_by='signal'` cycle has ever fired for any of the 3 test matters.** The two `signal`-triggered cycles in history both used non-canonical `matter_slug` values, confirming the dispatch path passes raw classifier labels through to `maybe_run_cycle`.

### Q2 — gate decisions in baker_actions

```sql
SELECT action_type, target_task_id, payload, created_at
FROM baker_actions WHERE action_type LIKE 'cortex:gate:%' ORDER BY created_at DESC;
```

| signal_id | matter_slug | action | when |
|-----------|-------------|--------|------|
| 315 | `movie_am` | skip | 2026-04-29 09:03 |
| 294 | `movie_am` | skip | 2026-04-29 07:36 |

Only 2 events ever. Both for non-canonical `movie_am` (Director clicked skip — meaning the gate DID post for that label, which can only happen if a `wiki/matters/movie_am/` directory existed at the time). For canonical `hagenauer-rg7`, `mo-vie-am`, `lilienmatt`: **zero**.

### Q3 — recent signal_queue row inspection (last 7 d)

```sql
SELECT id, matter, primary_matter, signal_type, created_at FROM signal_queue
WHERE created_at > NOW() - INTERVAL '7 days' ORDER BY created_at DESC LIMIT 20;
```

20-row sample; representative non-canonical `matter` values seen:
`Baker`, `ao_pm`, `movie_am`, `Hagenauer`, `Oskolkov-RG7`, `Baden-Baden Projects`, `Mandarin Oriental Asset Management`. None match a canonical `slugs.yml` slug.

`primary_matter` (post-Step-1) is canonical for most rows: `hagenauer-rg7` (226 in 14 d), `lilienmatt` (26), `annaberg` (29), `nvidia-corinthia` (5), `aukera` (2), `cupial` (1), `wertheimer` (11). **`mo-vie-am`: 0** — Step 1's `slug_registry.normalize('movie_am')` fails because `movie_am` (underscore) is not in the alias list (the alias `movie-am` uses a hyphen); the row stays `primary_matter='movie_am'` non-canonical.

### Q4 — would gate accept canonical labels if the dispatch path fed them?

Static check against `triggers/cortex_pre_review_gate.py:matter_has_cortex_config()` — pure file-existence test:

| Canonical slug | `wiki/matters/<slug>/cortex-config.md` | `matter_has_cortex_config` |
|----------------|----------------------------------------|----------------------------|
| `hagenauer-rg7` | exists | **True (PASS)** |
| `mo-vie-am` | exists | **True (PASS)** |
| `lilienmatt` | exists | **True (PASS)** |

Gate code is correct. **Cost-gate would accept all 3 if the dispatch site fed it the canonical slug.** The gap is purely upstream of the gate.

## Per-matter outcome (brief §"Done definition")

| # | Matter | Signal classifies onto matter? | Cost-gate fires? | Cycle starts within 60 s? | Verdict |
|---|--------|------------------------------|------------------|---------------------------|---------|
| 1 | `hagenauer-rg7` | Step 1 sets `primary_matter='hagenauer-rg7'` (226 in 14 d) ✓; but dispatch reads `matter` (raw) ✗ | NO — never posted for canonical slug; 0 rows in `baker_actions` | NO — never a `triggered_by='signal'` cycle for this slug | **FAIL** |
| 2 | `mo-vie-am` | Step 1 fails to canonicalize `movie_am` → underscore alias missing; `primary_matter` stays `movie_am` (1 row in 14 d) ✗ | NO for canonical slug; 2 historical posts for `movie_am` (lucky directory) | NO | **FAIL** |
| 3 | `lilienmatt` | Step 1 sets `primary_matter='lilienmatt'` (26 in 14 d) ✓; dispatch reads `matter` (raw `Oskolkov-RG7` etc.) ✗ | NO — 0 rows in `baker_actions` | NO | **FAIL** |

3/3 FAIL. Auto-trigger fan-out is non-functional for canonical matters.

## Root cause (single sentence)

`kbl/bridge/alerts_to_signal.py:577` calls `maybe_dispatch(matter_slug=signal_row["matter"])` immediately post-INSERT — before Step 1 triage runs and writes the canonical slug to `signal_queue.primary_matter` — so the gate's matter-config lookup always misses.

Compounding issues found while diagnosing:
- `proactive_pm_sentinel` writes `alerts.matter_slug='movie_am'` directly, bypassing canonicalization — and `movie_am` (underscore) isn't in the `mo-vie-am` alias list in `slugs.yml` (only `movie-am` with hyphen is).
- The bridge's `map_alert_to_signal` sets both `matter` and `primary_matter` to the raw `alert.matter_slug`; only Step 1 later overwrites `primary_matter`.

## Per brief §"If gap surfaced"

> **STOP.** Do not patch in this brief. File the gap as a new V4 queued item via paste-block to AI Head A. AI Head A authors a follow-up patch brief.

Followed verbatim — no code changes on this branch. Branch contains this report only.

## Paste-block for AI Head A (V4 queue)

```
GAP — AUTO_TRIGGER_FAN_OUT broken for ALL 22 matters (not just non-AO)

Severity: HIGH. Auto-trigger has been silently dead since multi-matter gate
shipped. Director-manual + scan_intent paths still work; signal-triggered
auto-fan-out has never reached canonical-slug gate posts (0 rows in
baker_actions for canonical hagenauer-rg7 / mo-vie-am / lilienmatt — only 2
historical events for non-canonical 'movie_am').

Root cause: kbl/bridge/alerts_to_signal.py:577 dispatches with raw
signal_queue.matter (PM-era labels like 'Hagenauer', 'Oskolkov-RG7',
'movie_am') BEFORE Step 1 triage canonicalizes via slug_registry.normalize()
and writes the canonical slug to primary_matter. Gate's
matter_has_cortex_config(matter_slug) therefore always misses.

Three candidate fixes (rank order, my recommendation in bold):

  **A. Move dispatch from bridge tick to Step 6 finalize** — fire
     maybe_dispatch(signal_id, primary_matter) only after Step 1+5+6 land
     a canonical primary_matter on the row. Cleanest separation; aligns
     with operating model where Step 1 triage is the canonicalizer.
     Cost: ~30-line move + one new test asserting dispatch fires from
     finalize, not bridge. CORTEX_3T_FORMALIZE_1C Amendment A2 wired the
     hook into bridge — this would re-wire it one stage later.

  B. Canonicalize in dispatch — call slug_registry.normalize(signal_row["matter"])
     inside _dispatch_cortex_for_inserted. Smaller diff but treats Step 1
     as redundant for the dispatch axis; risks divergence if Step 1 ever
     adds matter-tag logic the bridge can't see (e.g., model-driven
     reclassification).

  C. Add aliases to slugs.yml — adds 'movie_am', 'ao_pm', 'Hagenauer',
     'Oskolkov-RG7', etc. as aliases for their canonical slugs. Patches
     the symptom; doesn't address the temporal ordering bug. Aliases for
     classifier-internal labels also pollute the registry. NOT recommended.

Compounding gap: slug_registry doesn't normalize 'movie_am' (underscore) →
'mo-vie-am'. Only 'movie-am' (hyphen) is in the alias list. Either add
the underscore alias OR normalize underscore→hyphen in the lookup.
Independent of A/B/C.

Test matters used: hagenauer-rg7, mo-vie-am, lilienmatt — all 3 have
wiki/matters/<slug>/cortex-config.md ratified, all 3 are status=active in
slugs.yml v15. Verification was read-only against live Neon (no synthetic
prod writes) — see briefs/_reports/B1_auto_trigger_fan_out_verify_20260430.md.

Asking AI Head A to author follow-up patch brief.
```

## Files changed

None (verification only). This ship report is the sole artifact on `b1/auto-trigger-fan-out-verify`.

## Next step

Open PR with this report only. AI Head A reviews, posts paste-block to Director, drafts follow-up patch brief once the fix candidate is ratified.
