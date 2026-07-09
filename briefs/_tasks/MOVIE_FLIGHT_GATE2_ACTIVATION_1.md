# BRIEF: MOVIE_FLIGHT_GATE2_ACTIVATION_1 — Gate-2 keyword + routing activation for MO-VIE-001

Harness-V2: task class = feature-gap activation (production config/registry, baker-master; code
only if diagnose justifies) · Context Contract: this brief + `orchestrator/airport_ticketing_bridge.py`
@main + `kbl/project_registry_store.py:288` `desk_owner_for_matter` + AO precedent
AO_FLIGHT_PROD_TICKET_ROUTING_1 (PR #483) + AIRPORT_TICKET_PER_FLIGHT_TAG_1 arc +
`confirm-package-v1.html` + manifest-FINAL — re-verify every signature at build time · done
rubric = §Verification + §Quality Checkpoints 1-5; done-state class =
**deployed-live-probe-verified** (merged ≠ done; both live probes + POST_DEPLOY_AC_VERDICT
required) · gate plan: diagnose findings → lead scope-confirm → build → PR → codex bus G3
(`reasoning_effort=medium`) → lead merge → live probes → POST_DEPLOY_AC_VERDICT on bus.

## Context
Director gave MOVIE launch GO 2026-07-09 (~16:55Z, chat). Flight MO-VIE-001 prep is closed:
participant registry 37 rows registered (27 email + 10 WA, lead single-writer, fold #8089),
confirm package Director-corrected (`_ops/build/baker-os-v2/05_outputs/flight-dashboards/MO-VIE-001/confirm-package-v1.html`).
The one launch-gated CODE lane is Gate-2 activation: today the airport ticketing bridge mints
zero MOVIE tickets because no MOVIE keyword is in the Gate-2 set and routing defaults elsewhere.
AO flight (AO-OSK-001) is the shipped precedent: AO_FLIGHT_PROD_TICKET_ROUTING_1 = PR #483
(per-matter desk routing via `project_registry.desk_owner`, lead ruling #6850) +
AIRPORT_TICKET_PER_FLIGHT_TAG_1 (per-matter `suspected_flight`). Mirror it for MOVIE.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: none (AO precedent merged on main; registry rows live)

## Baker Agent Vault Rails
Relevant: bus-and-lanes (ticket mint → movie-desk), verification-surfaces (live AC probe),
build-command-center (dispatch gating). Ignored: skills-and-playbooks, memory-and-lessons,
loop-runner — untouched.

---

## Feature 1: Gate-2 activation for MOVIE

### Problem
MOVIE arrivals (email/WA) never mint tickets: Gate-2 keyword ILIKE
(`orchestrator/airport_ticketing_bridge.py`, `_KEYWORDS_ENV = "AIRPORT_TICKETING_KEYWORDS"`,
defaults `("aukera", "annaberg", "lilienmatt")`) has no MOVIE terms, and no verified
`desk_owner` path routes mo-vie-am / mo-vie-exit tickets to movie-desk.

### Current State
- `active_keywords()` bridge ~line 357 reads env `AIRPORT_TICKETING_KEYWORDS` (global set).
- `_desk_for_matter()` bridge ~line 491 resolves `project_registry.desk_owner` per matter,
  falls back to global `_DESK_ENV` (default baden-baden-desk). Source of truth =
  `desk_owner_for_matter` (`kbl/project_registry_store.py:288`).
- KNOWN-sender widening exists (bridge ~line 98): a matter email from a KNOWN participant
  reaches Gate-2 beyond keyword ILIKE — the 37 registered MO-VIE-001 rows should feed this.
- Per-flight tag: `suspected_flight` per matter (AIRPORT_TICKET_PER_FLIGHT_TAG_1) — MOVIE
  needs mo-vie-am/mo-vie-exit → MO-VIE-001.
- Slug trap (b1 preflight H1): `movie` is a semantic ALIAS of `mo-vie-am` (slugs.yml:38) —
  Layer-3 data lives under `mo-vie-am` + `mo-vie-exit`; querying `movie` returns 0 rows.

### Engineering Craft Gates
- Diagnose: applies — FIRST verify in prod: (a) `project_registry` rows + `desk_owner` for
  mo-vie-am / mo-vie-exit (SELECT ... LIMIT 10), (b) current live `AIRPORT_TICKETING_KEYWORDS`
  env value, (c) whether the 37 registry rows are visible to KNOWN-sender widening. Post
  findings to lead BEFORE implementing. Feedback loop = seeded live probe (below), binary.
- Prototype: N/A — AO precedent is the shipped design; zero design uncertainty.
- TDD: applies — public seam = bridge tick. First test: a synthetic arrival matching a MOVIE
  keyword (or KNOWN MOVIE sender) mints exactly one ticket with desk=movie-desk +
  suspected_flight=MO-VIE-001; a lilienmatt arrival still routes baden-baden-desk (regression).

### Implementation
1. Diagnose findings post (above) — lead confirms scope on bus.
2. Propose MOVIE keyword set from manifest-FINAL + confirm package. HARD CONSTRAINTS:
   NEVER bare `movie` (false-positive floods any email containing the word); `rg7` collides
   with hagenauer-rg7 (b1 H3) — exclude or pair-disambiguate. Candidates to evaluate:
   "mandarin oriental", "riemergasse". **Lead signs off the exact list on bus BEFORE any flip.**
3. Registry: upsert `desk_owner=movie-desk` + `suspected_flight=MO-VIE-001` for mo-vie-am +
   mo-vie-exit (mirror AO rows; follow whatever write path PR #483 arc used — no new mechanism).
4. Keywords: append signed-off terms to `AIRPORT_TICKETING_KEYWORDS` on Render (baker-master).
   Env-var rule: after setting, verify ALL expected keys via Render API — don't assume.
5. Tests per TDD gate (live-PG pytest, existing bridge test conventions).

### Key Constraints
- Do NOT relitigate flight design — charter/tickets/holds are Director-confirmed.
- Holds stay held: Christian-surname (trigger=production), BDG roster, Eastdil pair (T4 dormant).
- Bridge parity: never alter the match/miss predicate construction (`_keyword_ilike_where`) —
  append config only.
- All DB access try/except + rollback; every query LIMIT'd.

### Verification
Live AC (= the done gate, Lesson #8: exercise the actual flow):
- Seeded probe: MOVIE-matter email arrival → ticket minted, desk=movie-desk,
  suspected_flight=MO-VIE-001, visible on movie-desk check-in surface.
- Regression probe: lilienmatt arrival unchanged (baden-baden-desk).
- POST_DEPLOY_AC_VERDICT v1 on bus to lead after both probes.

---

## Files Modified
- `orchestrator/airport_ticketing_bridge.py` — ONLY if AO precedent requires a code touch;
  expectation is config/registry-only. Justify any code diff in the findings post.
- `tests/test_airport_ticketing_bridge*.py` — new cases per TDD gate.

## Do NOT Touch
- `_keyword_ilike_where` / match-miss parity machinery — observability contract (G3 #4957).
- AO flight rows/env — live flight.
- `baker-vault/slugs.yml` — separate-repo PR only; alias trap is worked around, not fixed here.

## Quality Checkpoints
1. Diagnose findings posted + lead scope-confirm received.
2. Keyword list lead-signed BEFORE env flip.
3. Tests green incl. lilienmatt regression.
4. Render env verified via API after flip.
5. Both live probes pass; POST_DEPLOY_AC_VERDICT posted.

## Verification SQL
```sql
SELECT matter_slug, desk_owner, suspected_flight FROM project_registry
 WHERE matter_slug IN ('mo-vie-am','mo-vie-exit','movie') LIMIT 10;
```

Gate plan: diagnose findings → lead scope-confirm → build → PR → codex G3 (medium) →
lead merge → live probes → POST_DEPLOY_AC_VERDICT. Reply target: lead, bus topic
`baker-os-v2/movie-flight-gate2`.
