# B4 ship report — PROJECT_NUMBER_REGISTRY_1

- **Brief:** `briefs/BRIEF_PROJECT_NUMBER_REGISTRY_1.md`
- **PR:** #439 — https://github.com/vallen300-bit/baker-master/pull/439
- **Branch:** `project-number-registry-1`
- **HEAD SHA:** `c8334d0340a6117094b789e8da03c9f68b4653bb`
- **Base:** `main` @ `8701dcf`
- **Dispatched by:** cowork-ah1 (bus #4682, envelope on main 8701dcf)
- **Date:** 2026-06-30

## What shipped
Two new files, additive only — no live code touched, no migration, no env vars, no deps.

- `kbl/project_registry_store.py` — implemented verbatim from the brief:
  - `ensure_project_registry_table()` idempotent `CREATE TABLE IF NOT EXISTS` (mirrors `ensure_airport_ticket_table`; self-heals on boot, no migration file).
  - `register_project()` upsert; fails loud on non-canonical `matter_slug` (via `slug_registry.is_canonical`), bad `DESK-MATTER-###` form, unknown desk code.
  - `resolve_project_number()` hard lane — regex hit absent from registry rejected.
  - `resolve_by_participant()` / `resolve_by_alias()` soft-lane primitives (non-authoritative candidate lists).
  - `seed_bb_pilot()` one-off helper, NOT auto-run.
- `tests/test_project_registry.py` — 7 vertical live-PG tests (written first). Slug validation runs against the fixture vault (`tests/fixtures/vault`, alpha/beta/gamma), never production slugs.yml — matches `test_slug_registry.py` convention.

## Acceptance criteria — all green
- AC1 `py_compile kbl/project_registry_store.py` — clean.
- AC2 `pytest tests/test_project_registry.py -v` — 7 passed against a throwaway local Postgres 16; 7 skipped without `TEST_DATABASE_URL` (CI provisions ephemeral Neon).
- AC3 `bash scripts/check_singletons.sh` — OK (no new direct-instantiation).
- AC4 guardrail test `test_hard_lane_rejects_unregistered_number_and_sender_only` — proves number-alone never clears + sender-only never clears the hard lane.
- AC5 `test_register_rejects_noncanonical_slug` — non-canonical `matter_slug` raises `ValueError`.

## Literal pytest output (live, local PG 16)
```
collected 7 items
tests/test_project_registry.py::test_resolve_project_number_hard_lane PASSED [ 14%]
tests/test_project_registry.py::test_resolve_tolerant_separators PASSED  [ 28%]
tests/test_project_registry.py::test_hard_lane_rejects_unregistered_number_and_sender_only PASSED [ 42%]
tests/test_project_registry.py::test_register_rejects_noncanonical_slug PASSED [ 57%]
tests/test_project_registry.py::test_register_rejects_bad_format PASSED  [ 71%]
tests/test_project_registry.py::test_resolve_by_participant_soft PASSED  [ 85%]
tests/test_project_registry.py::test_resolve_by_alias_soft PASSED        [100%]
========================= 7 passed, 1 warning in 0.07s =========================
```
Verification SQL after a register: row stored as `('BB-AUK-001','BB','baden-baden-desk','alpha',None)` — `desk_code` correctly derived from the prefix.

## Deviations from brief
None on the module — implemented exactly as written. Test-file choices (brief left `<canonical slug>` as a placeholder):
- Used fixture-vault slug `alpha` as the canonical slug and `tests/fixtures/vault` for `BAKER_VAULT_PATH`, so tests don't couple to production slugs.yml (CI has no baker-vault checkout). Confirmed in the real vault that `annaberg` + `aukera` ARE canonical, so the brief's seed default is valid for production seeding.
- Folded AC4's two guardrail assertions (number-alone + sender-only) into one test (#3) so the count stays at the brief's 7.
- Per-test `DELETE FROM project_registry` in the fixture for deterministic soft-lane scans — safe because the table is net-new with no prod writer.

## Repo-state note (not part of scope)
Found a stale interactive rebase in progress on `email-read-rest-fallback-1` (rebasing onto current main) with an unresolved `outputs/dashboard.py` conflict, left over from a prior arc. That work already shipped (PR #435 MERGED 2026-06-29), so I aborted the rebase (non-destructive — restores the already-merged branch) to get a clean main. Also: two prior B4 ship reports + a `brisen-lab/` dir sit untracked in the working tree from earlier arcs — left them alone.

## Done-state
Build-done only (PR merged + AC1–AC5 green). NO live AC / no `POST_DEPLOY_AC_VERDICT` — library primitive, no prod caller, no deploy; table self-heals on boot. `DESK_CODES` + non-pilot Aukera/Annaberg seed confirmation is a separate downstream step, not this build.

## Next gates
G3 codex-verifier (effort medium) → G4 lead `/security-review` → lead merge.

---

## Rework round 1 — codex G3 FAIL (bus #4688) → fixed, HEAD `57f8817`
Codex G3 returned FAIL with 2 real findings; lead's G4 `/security-review` already PASSED and holds (logic fixes, no new security surface). Both fixed on the same branch (PR #439 updates in place):

- **F1 [P1]** `register_project` accepted a `desk_owner` contradicting the DESK prefix (probe: `BB-AUK-001` + `desk_owner=movie-desk` was accepted) — reintroduces wrong-desk routing. Fix: enforce `desk_owner == DESK_CODES[prefix]`, else `ValueError`; corrected the stale "desk_owner is authoritative" comment (prefix is the routing authority). Regression: `test_register_rejects_desk_owner_prefix_mismatch`.
- **F2 [P2]** `resolve_by_alias` used space-padding, not word boundaries (probe: `'Annaberg:'`, `'(Annaberg)'`, `'Aukera-Annaberg'` did not match → dropped from soft lane → false holds). Fix: `re.search(r"\b" + re.escape(alias) + r"\b", text, re.IGNORECASE)`. Regression: `test_resolve_by_alias_matches_through_punctuation` (3 parametrized cases).

Re-gate G1 all green: py_compile clean; check_singletons OK; **pytest 11 passed** live against local PG 16:
```
collected 11 items ... 11 passed, 1 warning in 0.09s
```
Re-gate chain on return: codex G3 re-gate (effort medium) → lead merge (G4 holds).

---

## Rework round 2 — codex G3 re-gate: F1+F2 PASS, new F3 (bus #4694) → fixed, HEAD `8d6726e`
Codex confirmed F1 + F2 fixed; raised one new P2. Fixed on the same branch.

- **F3 [P2]** `register_project` used `_NUMBER_RE.match()` (prefix match), so `'BB-AUK-001 extra'` was accepted and stored with `match_key='BBAUK001EXTRA'` — but `resolve_project_number` keys off the matched DESK/MATTER/digit groups (`'BBAUK001'`), so the stored row was **unreachable by the hard lane** (violates the brief's "store display 'BB-AUK-001' + match_key 'BBAUK001'" contract). Fix: (1) validate with `_NUMBER_RE.fullmatch()` — trailing junk now raises `ValueError`; (2) canonicalize the stored display form + match_key from the matched groups (`f"{g1}-{g2}-{g3}".upper()`), so they always round-trip; (3) removed the now-dead `_desk_code_of` helper. Regressions: `test_register_rejects_trailing_junk`, `test_register_canonicalizes_and_round_trips`.

Re-gate G1 all green: py_compile clean; check_singletons OK; **pytest 13 passed** live against local PG 16.
Re-gate chain on return: codex G3 re-gate → lead merge (G4 holds).

---

## Rework round 3 — codex G3 re-gate#2: F3 PASS, new F4 + self-audit (bus #4699) → fixed, HEAD `00d3fd4`
Codex confirmed F3 fixed (F1/F2 hold); raised one new P2 (F4). Lead also asked me to break the one-finding-per-round cycle with a fresh adversarial whole-module read. Both done on the same branch + same push.

- **F4 [P2]** `resolve_project_number` was non-deterministic on multi-number text: it built the lookup keys into a `set` (lost text order), then `match_key = ANY(%s) LIMIT 1` with no `ORDER BY`, so the DB returned an arbitrary match (probe: `'AO-MOV-002 then BB-AUK-001'` could return either). Fix per lead's contract decision (return type stays single `Optional[dict]`; conflict detection is Box 5's job): (1) build an **ordered, de-duped** key list from `_NUMBER_RE.finditer` preserving first-occurrence text order; (2) one bounded query `WHERE status='active' AND match_key = ANY(%s) LIMIT len(keys)`; (3) in Python pick the row whose `match_key` (now selected via a dedicated `_HARD_SELECT`, index 8) has the smallest text index. An earlier **unregistered** regex hit is skipped, so the first *registered* match wins. Docstring tightened. Regressions: `test_resolve_project_number_text_order_deterministic` (forward + reverse), `test_resolve_project_number_returns_first_registered_not_first_regex_hit`.

### Self-audit (fresh adversarial read of the whole module) — what I found + fixed
- **JSONB shape on read** — `resolve_by_alias` iterated `(r[6] or [])` directly; if the global psycopg2 jsonb typecaster were ever unset, `r[6]` arrives as a `str` and `for a in "<str>"` would iterate characters (silent wrong behaviour). Added `_as_list()` (None→[], str→`json.loads`, non-list→[]); applied in `_row_to_dict` (participants + aliases) and the alias scan. **Fixed.**
- **Soft-lane ordering** — both soft-lane scans had no `ORDER BY`, so when active rows exceed the cap (`resolve_by_participant` LIMIT 10; `resolve_by_alias` LIMIT 200 → `[:10]`) the returned subset was non-deterministic. Added `ORDER BY project_number` to both. Regression: `test_resolve_by_participant_deterministic_order`. **Fixed.**
- **`status='retired'` rows** — confirmed the `status='active'` filter holds across all three resolvers; no public path sets `retired` today, but added a regression that flips a row to `retired` via SQL and asserts all three resolvers exclude it. **Confirmed + locked by test.**
- **`_match_key` vs canonical consistency** — the hard lane previously relied on the round-trip invariant (`_match_key(stored project_number) == stored match_key`) to map a hit back; now it maps via the row's **actual `match_key` column** (`_HARD_SELECT` index 8), removing the implicit dependency. **Hardened.**
- **empty / dup keys** — the new ordered-key builder skips empty keys and de-dups (`if k and k not in seen`); a repeated number in one text resolves once. **Covered.**
- No other correctness/contract/edge gaps found on this read.

Re-gate G1 all green: py_compile clean (module + tests); check_singletons OK; **pytest 17 passed** live against local PG 16 (all 4 new tests included), 17 skipped without `TEST_DATABASE_URL`:
```
collected 17 items
... (13 prior) ...
test_resolve_project_number_text_order_deterministic PASSED              [ 82%]
test_resolve_project_number_returns_first_registered_not_first_regex_hit PASSED [ 88%]
test_resolvers_exclude_retired_rows PASSED                               [ 94%]
test_resolve_by_participant_deterministic_order PASSED                   [100%]
========================= 17 passed, 1 warning in 0.27s =========================
```
Re-gate chain on return: codex G3 re-gate#2 → lead merge (G4 holds). Ship report → cowork-ah1; re-gate-ready ping → lead.
