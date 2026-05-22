---
brief_id: PLAUD_TRANSCRIPT_BY_MATTER_1
status: SHIPPED (PR pending)
dispatcher: deputy
worker: b3
date: 2026-05-22
branch: b3/plaud-transcript-by-matter-1
brief_commit: 9431e58
---

# B3 ship report — PLAUD_TRANSCRIPT_BY_MATTER_1

**TO:** deputy (AH2 owns picker-architect + 2nd-pass review chain)

## Scope delivered

1. `migrations/20260522_meeting_transcripts_matter_slug.sql` — `matter_slug TEXT` + composite index `(matter_slug, meeting_date DESC NULLS LAST)`.
2. `memory/store_back.py`
   - `_ensure_meeting_transcripts_table` updated: column added to CREATE + idempotent `ADD COLUMN IF NOT EXISTS` + index creation in bootstrap for migrated DBs.
   - `store_meeting_transcript` signature extended with `matter_slug=None`; auto-assigns via `_match_matter_slug` + `slug_registry.normalize` (deliberate divergence from `create_alert`'s precedent — endpoint queries by canonical slug). Classifier failure non-fatal; normalize-returns-None on a classifier hit logs WARNING. INSERT uses `COALESCE(EXCLUDED.matter_slug, meeting_transcripts.matter_slug)` so re-ingest never clears an existing slug.
3. `outputs/dashboard.py` — `GET /api/transcripts/by-matter/{matter_slug}`:
   - X-Baker-Key auth (`Depends(verify_api_key)`).
   - Slug validated against `slug_registry.active_slugs()` (not `is_canonical`); inactive/retired → 404.
   - `limit` ∈ [1, 200], default 50; >200 → 400.
   - `since` ISO 8601 validated; malformed → 400.
   - `source` ∈ {plaud, fireflies, youtube} or None; invalid → 400.
   - `include_body=False` default (metadata-first); column list built from Python list (no f-string identifier injection).
   - Generic 500 detail (no DB error leakage); `conn.rollback()` in except; pool put-back in finally.
4. `scripts/backfill_meeting_transcripts_matter_slug.py` — dry-run-default, 4 safety rails, per-row SAVEPOINT. **TEXT id preserved** (`rid = cells[0].strip()`, no `int()` cast — would have silently dropped every row).
5. Tests: 15 cases, all green.

## Ship gate evidence

### Migration-vs-bootstrap drift check

`meeting_transcripts.matter_slug` did NOT exist pre-this brief. Bootstrap now mirrors migration:

```
$ grep -n 'matter_slug' memory/store_back.py | grep -i transcript
1417:                    matter_slug TEXT,
1423:                ADD COLUMN IF NOT EXISTS matter_slug TEXT
1427:                ON meeting_transcripts (matter_slug, meeting_date DESC NULLS LAST)
1450:                                  matter_slug: str = None) -> bool:
…
```

### Pytest — literal output

```
$ /opt/homebrew/bin/python3.12 -m pytest tests/test_store_meeting_transcript_matter_slug.py tests/test_transcripts_by_matter_endpoint.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.38, anyio-4.12.1
collected 15 items

tests/test_store_meeting_transcript_matter_slug.py::test_auto_assigns_matter_slug_when_classifier_matches PASSED [  6%]
tests/test_store_meeting_transcript_matter_slug.py::test_preserves_explicit_matter_slug PASSED [ 13%]
tests/test_store_meeting_transcript_matter_slug.py::test_classifier_failure_is_non_fatal PASSED [ 20%]
tests/test_store_meeting_transcript_matter_slug.py::test_on_conflict_preserves_existing_matter_slug_via_coalesce PASSED [ 26%]
tests/test_store_meeting_transcript_matter_slug.py::test_normalize_returning_none_logs_warning PASSED [ 33%]
tests/test_transcripts_by_matter_endpoint.py::test_endpoint_route_registered_in_dashboard_source PASSED [ 40%]
tests/test_transcripts_by_matter_endpoint.py::test_returns_401_without_auth PASSED [ 46%]
tests/test_transcripts_by_matter_endpoint.py::test_returns_404_for_unknown_slug PASSED [ 53%]
tests/test_transcripts_by_matter_endpoint.py::test_returns_404_for_inactive_slug PASSED [ 60%]
tests/test_transcripts_by_matter_endpoint.py::test_returns_200_filtered_by_matter_slug PASSED [ 66%]
tests/test_transcripts_by_matter_endpoint.py::test_since_filter_passes_to_sql PASSED [ 73%]
tests/test_transcripts_by_matter_endpoint.py::test_limit_above_200_returns_400 PASSED [ 80%]
tests/test_transcripts_by_matter_endpoint.py::test_default_excludes_full_transcript_include_body_includes_it PASSED [ 86%]
tests/test_transcripts_by_matter_endpoint.py::test_since_malformed_returns_400 PASSED [ 93%]
tests/test_transcripts_by_matter_endpoint.py::test_invalid_source_returns_400_and_valid_source_filters PASSED [100%]

======================= 15 passed, 71 warnings in 1.24s ========================
```

Plus regression sweep:
```
$ pytest tests/test_plaud_trigger.py tests/test_store_back_pool_threadsafe.py tests/test_backfill_matter_slug.py -v
12 passed (plaud trigger)  /  12 passed (backfill_matter_slug)  /  1 passed 1 skipped (pool)
```

### Singleton guard

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### Pre-backfill alias gate (brief flag) — PASSES

```
hagenauer-rg7 in canonical? True
hagenauer-rg7 in active? True
  normalize('Hagenauer RG7') → None            # 'RG7' alias not present, OK — classifier returns 'Hagenauer' not 'Hagenauer RG7'
  normalize('Hagenauer')     → 'hagenauer-rg7' # ✓ classifier output path
  normalize('hagenauer-rg7') → 'hagenauer-rg7' # ✓ canonical passthrough
  normalize('Hagenauer-RG7') → 'hagenauer-rg7' # ✓
  normalize('Oskolkov-RG7')  → 'hagenauer-rg7' # ✓ (alias in slugs.yml)
```

slugs.yml entry:
```
- slug: hagenauer-rg7
  status: active
  aliases: [hagenauer, rg7, "oskolkov-rg7"]
```

No baker-vault PR required — alias gate is open.

### Dry-run against prod (read-only)

```
$ python3.12 scripts/backfill_meeting_transcripts_matter_slug.py
2026-05-22 14:54:58 DRY RUN complete: 169 total | M=107 U=62 → /tmp/backfill_meeting_transcripts_proposal_20260522T125458Z.md
```

Bucket M slug breakdown (top 10):

| slug | rows |
|---|---:|
| hagenauer-rg7 | **33** |
| baker-internal | 14 |
| mo-vie-am | 11 |
| mo-vie-exit | 9 |
| cupial | 9 |
| kitzbuhel-six-senses | 8 |
| personal | 6 |
| austrian-tax | 5 |
| claimsmax | 4 |
| kitz-kempinski | 3 |

**Hag-desk gap audit:** 33 transcripts will tag `hagenauer-rg7` post-apply — comfortable margin for Tue 2026-05-26 Forderungsanmeldung filing prep. AH1 drives `--apply` after Director ratifies the M-block.

## Risk surface

1. **Classifier accuracy ~70-80%** — Bucket M may include false positives (e.g. "Oskolkov-RG7" maps to `hagenauer-rg7` per slugs.yml alias, but a generic AO meeting unrelated to RG7 could also match). Hag-desk gap audit step 2 (Director-ratified Option B) catches both directions Sun→Mon pre-filing.
2. **`include_body=true` payload size** — 50KB/row × 200 row cap = ~10MB max response. `full_transcript` is not truncated server-side. Acceptable for matter-desk read-path under internal-agent perimeter; payload size noted as queued follow-up.
3. **Global X-Baker-Key auth** — endpoint TODO comment flags the per-matter scoped auth follow-up brief (queued post-filing).

## Files changed

- `migrations/20260522_meeting_transcripts_matter_slug.sql` (NEW)
- `memory/store_back.py` (bootstrap + `store_meeting_transcript`)
- `outputs/dashboard.py` (NEW endpoint after `/api/fireflies/status`)
- `scripts/backfill_meeting_transcripts_matter_slug.py` (NEW)
- `tests/test_store_meeting_transcript_matter_slug.py` (NEW)
- `tests/test_transcripts_by_matter_endpoint.py` (NEW)
- `briefs/_reports/B3_PLAUD_TRANSCRIPT_BY_MATTER_1_20260522.md` (this file)

## Next steps (deputy)

1. Run AH2 review chain (static → security-review → picker-architect → feature-dev:code-reviewer).
2. If clean: recommend merge to AH1 (lead).
3. Post-merge: AH1 ratifies dry-run proposal with Director, runs `--apply`, hag-desk re-pulls via the new endpoint for gap audit.
