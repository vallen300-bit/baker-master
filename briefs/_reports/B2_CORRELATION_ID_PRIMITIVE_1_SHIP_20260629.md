# B2 SHIP REPORT — CORRELATION_ID_PRIMITIVE_1

- **Brief:** CORRELATION_ID_PRIMITIVE_1 (read-only bus↔signal_queue thread-back identity primitive)
- **Dispatched by:** lead (bus #4630)
- **PR:** #437 — https://github.com/vallen300-bit/baker-master/pull/437
- **Branch:** `correlation-id-primitive-1`
- **Commits:** e847b14b (initial) → **8ccfeb24** (F1 fix, latest)
- **Date:** 2026-06-29
- **Deploy:** none (library only; nothing calls it in prod yet)

## Gate cycle 2 — F1 fix (codex-arch #4642 2nd-pair FAIL bounce, bus #4644)
Codex-arch flagged real parser-strictness defects in v1 of `parse_checkin_verdict`:
`v10` accepted as `v1` (prefix match); junk tokens between fields ignored by `findall`;
duplicate `outcome=` last-wins could flip `BOGUS`→`VALID`. Fixed (commit 8ccfeb24):
replaced `startswith`+`findall` with ONE fully-anchored `re.fullmatch` order-strict regex
(`CHECK_IN_VERDICT v1 sig=<digits> outcome=<enum> by=<slug>`, single-space, fields in
order, no extra/duplicate tokens; outcome alternation from `_OUTCOMES` tuple; ReDoS-safe).
Added whitespace-only-body guard (never-raise). 9 regression cases added. Field ORDER
enforced (order-strict) per gate ruling. Resolver/topic-carrier/schema untouched.
Re-ship + 2nd-pair re-request: bus #4645. **pytest now 12 passed.**

## What shipped
New `kbl/correlation.py` (read-only):
- `corr_id(signal_id)` → `sig-<id>` ; `parse_corr_id(text)` first-match-wins, non-int/no-token → `None`
- `checkin_topic` / `checkin_reply_topic` → topic-slug carriers
- `parse_checkin_verdict(body)` → never-raise parser of `CHECK_IN_VERDICT v1 sig= outcome= by=`
- `resolve_signal(signal_id)` → single read-only `LIMIT 1` lookup, never raises, `rollback()` on query error

New `tests/test_correlation.py` — 11 fixture tests (no DB/network); resolver verified against a stubbed `get_conn`.

## Done rubric
- AC1–AC5 (pure-string): covered + extras (every enum outcome accepted; None/empty inputs).
- AC6 (resolver via stub): row→dict, no-row→None, execute-raise→None+rollback, get_conn-raise→None, SQL contains `LIMIT 1`, SQL is read-only.

## G1 self-check (literal)
- `py_compile` kbl/correlation.py + tests/test_correlation.py → compile OK
- `python3 -m pytest tests/test_correlation.py -v` → **11 passed, 1 warning in 0.03s**
- no-write grep on `kbl/correlation.py` diff (INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE) → **ZERO**

## Two builder-TODO spec corrections (surfaced — flagged to lead)
1. **`kbl.db.get_conn` is a `@contextmanager`**, not a plain function. Brief pseudocode (`conn = get_conn(); ...`) would break. Used `with get_conn() as conn:`. Cursor = psycopg2 **default tuple cursor** (no RealDict) → `row[0..2]` indexing (matches brief).
2. **`signal_queue` has no `matter_slug` column.** Base table (`memory/store_back.py:7287`) defines `matter`; additions add `primary_matter` — and prod code reading matter-context from signal_queue by id uses `primary_matter` (`kbl/steps/step6_finalize.py:856`). Brief's `SELECT ... matter_slug` would raise `column does not exist` in prod → `resolve_signal` would silently return `None` forever (swallowed by the never-raise except). Fixed: `SELECT primary_matter`, exposed under the brief's documented `matter_slug` return key so the dict contract holds. Spec source (cowork-ah1 #4623) should be corrected to reflect the real column; downstream Dispatcher/monitor builders need the accurate column name.

## Constraints honored
No writes; no migration; no `airport_tickets` wiring; no `parent_id` dependency; no daemon/schema change; no deploy.

## Gate chain status
G1 ✅ → codex-arch 2nd-pair (pending) → codex G3 → lead `/security-review` G4 → lead merge → NO deploy.
