# BRIEF: BOX5_HARD_FAST_LANE_1 — project-number hard fast lane + extract_project_codes conflict pre-check + aukera pilot seed correction

## Context

Box 5, **Build Order 6** — the PROJECT-NUMBER HARD FAST LANE. This brief plugs a project-number-driven fast-board decision into the per-arrival terminal-decision path that **BRIEF-C (`BOX5_TICKETING_RUNNER_1`)** builds inside `run_tick` (`orchestrator/airport_ticketing_bridge.py:780`). The hook is BRIEF-C's `(f) SAFE DEFAULT — TICKET` block (`scratchpad/brief_c_draft.md` lines 298–321): D inserts a new precedence tier **between** C's `(e)` DUPLICATE clear (~line 296) and C's `(f)` safe-default TICKET (~line 298). When the lane cleanly clears, D writes `terminal_status='FAST_TICKET'` via C's `write_terminal_status` helper instead of falling through to TICKET; on any miss/conflict/exception, control falls into C's unchanged TICKET path.

**Hard dependency:** BRIEF-C must be MERGED first — D edits C's `run_tick` body and calls C's net-new helpers (`write_terminal_status`, `_claim_for_terminal`, `fast_lane_enabled`). On `origin/main` @ `a87cab2` (`dispatch: BOX5_TICKETING_RUNNER_1 -> b4`) none of these exist yet (`grep 'write_terminal_status\|fast_lane_enabled' orchestrator/airport_ticketing_bridge.py` returns zero on main). Do NOT start D's branch until C lands.

D consumes the **#439 registry** (`kbl/project_registry_store.py`, merged): `resolve_project_number(text) -> Optional[dict]` (hard-lane single-return resolver, `status='active'` filtered, deterministic first-registered-in-text-order) and `resolve_by_participant(channel, value) -> list[dict]` (participant-set membership). Receipt/TTL (#440) and the terminal schema with the 6-state CHECK incl. `FAST_TICKET` (#441) are merged.

**Locked fast-lane rules this brief honors:**
- **#4679.2 + #4680.1** — the hard fast lane requires a registered + ACTIVE project_code **AND** (sender in the project's manifest participant set **OR** thread continuity). Sender-only matching is forbidden alone.
- **#4679.3** — regex shape alone NEVER fast-clears; registry validation (`resolve_project_number`) is mandatory.
- **F4** — BEFORE resolving, run `extract_project_codes(text)`; if **>1 distinct** valid-shaped code → cross-matter CONFLICT → do NOT fast-board; if exactly 1 → proceed to `resolve_project_number`; if 0 → no code.
- **#blocker D3** — a registry/binding-check exception must NEVER auto-clear or auto-FAST_TICKET; it routes to safe-default TICKET + counts `failed`. Distinguish "threw" from "no match".

**aukera ratification (folded seed correction):** Director ratified `matter_slug=aukera` (NOT `annaberg`) for the BB-AUK-001 pilot. Two merged seed paths still hardcode `annaberg` and must change to `aukera` (canonical in slugs.yml v23, line 65; `is_canonical('aukera')` returns True — verified live). The seed stays gated/un-run until Director GO; D only corrects the slug.

### Surface contract: N/A — backend fast-lane decision logic + a registry helper + a seed slug correction, no clickable UI surface.

### Harness V2

**Context Contract**

- **Inputs:**
  - `extract_project_codes(text: str) -> list[str]` — NET-NEW pure helper in `kbl/project_registry_store.py`. Input = `arrival.subject + ' ' + arrival.full_body`. NO DB.
  - The hard-lane branch inside C's `run_tick` per-arrival loop. Per-arrival signals all live on the `EmailArrival` frozen dataclass (`airport_ticketing_bridge.py:57`): `message_id`, `thread_id`, `sender_email`, `subject`, `full_body`, `received_date`.
  - `row_id = result.get("id")` from C's `issue_ticket(ticket, conn)` (`brief_c_draft.md:274`) — the only airport_tickets row id available at the decision point.
  - The existing `fast_lane` local computed once at `run_tick` top (`brief_c_draft.md:227`, `fast_lane = fast_lane_enabled()`, env `BOX5_FAST_LANE_ENABLED`, default false). REUSE it — do NOT re-read the env.
  - Registry: `resolve_project_number(text)`, `resolve_by_participant('email', sender_email.lower())` (both #439, merged).
- **Outputs:** on a clean hard-lane clear, `terminal_status='FAST_TICKET'` written via `write_terminal_status`; a NEW `fast_ticket` per-tick counter added to C's `run_tick` stats dict as `'fast_ticket': fast_ticket`. No other output shape change.
- **Side-effects:** one terminal write (`FAST_TICKET`) + its `baker_actions` audit row (both inside `write_terminal_status`); a `_claim_for_terminal` row lock. NO new table, NO schema change, NO new scheduler/cursor/lease. Seed edits change two literal strings; seed remains un-run.
- **Idempotency invariants:** D writes the terminal ONLY through C's status-guarded `write_terminal_status` (`... WHERE id=%s AND terminal_status IS NULL`) after winning `_claim_for_terminal` (`FOR UPDATE SKIP LOCKED`). Re-runs / overlapping ticks match 0 rows → no double FAST_TICKET. `extract_project_codes` is pure (same input → same output, no state). The seed upserts on `match_key` (already idempotent).

**Task class:** additive decision logic + net-new pure helper + seed slug fix. One new branch in C's `run_tick` between blocks (e) and (f); one net-new pure-regex helper in `kbl/project_registry_store.py`; one new counter + stats key; two one-line seed corrections (+ one breaking test assertion). No schema migration, no new job, no new lock.

**Done rubric (machine-checkable):**

1. `extract_project_codes` is **pure / no-DB / distinct**: `grep -A12 'def extract_project_codes' kbl/project_registry_store.py` shows NO `get_conn`/`cur`/`execute`; it reuses the module-level `_NUMBER_RE` (no second `re.compile`); returns distinct codes in first-occurrence text order.
2. **Regex reuse, not duplication**: `grep -c 're.compile' kbl/project_registry_store.py` is unchanged from main (the helper references `_NUMBER_RE`, defines no new pattern).
3. **>1 distinct code NEVER FAST_TICKETs**: the branch contains `if len(set(...)) > 1` (or equivalent on the distinct list) that falls through to (f) TICKET; test `>1 code -> TICKET` passes.
4. **Regex-only never clears**: a 1-code arrival whose code is unregistered (`resolve_project_number` → None) falls through to TICKET; registry validation is mandatory (test `regex-only-no-row -> TICKET` passes).
5. **Participant-OR-thread binding required**: FAST_TICKET is written only when `resolve_by_participant('email', sender_email.lower())` returns a dict whose `project_number` equals the resolved row's `project_number`. (Thread-continuity is a documented TODO — see Key Constraints; pilot v1 = participant-binding-only.)
6. **Conflict / no-row / no-binding → TICKET, not VISIBLE_HOLD**: `grep -c 'VISIBLE_HOLD' orchestrator/airport_ticketing_bridge.py` is 0; every non-clear hard-lane path falls through to C's existing TICKET block.
7. **FAST_TICKET only on a clean clear**: the only `terminal_status='FAST_TICKET'` write in the file is inside the `if bound:` arm after a non-None active resolve.
8. **Gated by `BOX5_FAST_LANE_ENABLED`**: the entire branch is under `if fast_lane and row_id:` reusing C's pre-computed `fast_lane` local; with the flag false, `grep` shows the branch is skipped and C's TICKET default covers everything (D adds nothing live).
9. **Error never auto-FAST_TICKETs**: D's own extract/resolve/bind composition is wrapped so any raised exception increments `failed` and falls through to TICKET (never FAST_TICKET); a clean `None`/`[]` from a resolver is a normal no-match → TICKET. `deterministic_cleared` is never incremented by D.
10. **Seed `matter_slug == 'aukera'`**: `grep -c 'matter_slug="annaberg"\|MATTER_SLUG = "annaberg"' kbl/project_registry_store.py scripts/seed_bb_pilot_registry.py` is 0; both now read `aukera`; `tests/test_project_registry.py` asserts `seed.MATTER_SLUG == 'aukera'`.

**Gate plan:** G1 (builder self-test: `pytest tests/test_project_registry.py -v` green incl. the new pure-regex tests + the flipped seed assertion; targeted `tests/test_box5_ticketing_runner.py` green to prove no regression in C's loop; `python3 -c "import py_compile; py_compile.compile('orchestrator/airport_ticketing_bridge.py', doraise=True); py_compile.compile('kbl/project_registry_store.py', doraise=True)"`) → **codex G3** (verifier verdict on the diff) → **lead `/security-review` G4** → **lead merge**. Ships **dark** behind `BOX5_FAST_LANE_ENABLED` (default false). The **seed stays un-run until Director GO** — D corrects the slug only; running `scripts/seed_bb_pilot_registry.py` is a separate, gated step.

## Estimated time

3–4 hours (one builder). The helper + branch are surgical; most cost is the binding/conflict/error test matrix.

## Complexity

**Medium.** Edits are small and all precedents are in-repo, but the correctness surface (regex-only-never-clears, binding mandatory, error-never-FAST_TICKETs, gate honored) must be proven by test, not inspection. Sits on top of C's concurrency/idempotency machinery, which D reuses unchanged.

## Prerequisites

- **BRIEF-C MERGED.** D edits C's `run_tick` body and calls C's net-new helpers `write_terminal_status` (`brief_c_draft.md` §2), `_claim_for_terminal` (§5), and reuses C's `fast_lane = fast_lane_enabled()` local (§4, run_tick line 227) plus the `(e)`/`(f)` block structure. On `origin/main` @ `a87cab2` none of these exist — C is dispatched to b4, not merged. **Branch D off a base that contains C's merge.** If C is reverted, D is blocked until C re-merges.
- **#439 merged** — `resolve_project_number` + `resolve_by_participant` are live on `origin/main` (`kbl/project_registry_store.py`). Confirmed.
- **#441 merged** — `FAST_TICKET` is already a permitted value in BRIEF-B's 6-state terminal_status CHECK, so the write is schema-valid. Confirmed.
- **Serialize-after-C (explicit).** D must be authored, gated, and merged strictly after C. Do not parallelize: D's branch references file regions that only exist after C lands.

### Problem

BRIEF-C makes every non-deterministic-clear arrival a desk `TICKET` (safe-by-default). The hard fast lane is the legitimate fast-board: an arrival that carries a registered, active project number AND is provably bound to that project (the sender is in its manifest participant set) does not need full desk triage — it can go straight to `FAST_TICKET`. But three failure modes must be foreclosed: (1) a regex shape that merely *looks* like a code but isn't registered must not clear (#4679.3); (2) two different project codes in one message signal a cross-matter conflict and must not fast-board (F4); (3) a DB/registry exception must never be misread as a clean clear (#blocker D3). D adds exactly this one tier, gated dark, with TICKET as the safe fallback for every uncertain path.

### Current State (file:line)

- `extract_project_codes` — **does NOT exist** on `origin/main` (net-new; F4-deferred to Box 5). Must be built in `kbl/project_registry_store.py`, placed immediately AFTER `resolve_project_number` (after line 240) and BEFORE `resolve_by_participant` (line 243) — it is the hard-lane conflict pre-check and belongs with the hard lane.
- `_NUMBER_RE` — `kbl/project_registry_store.py:45` — `re.compile(r"\b([A-Za-z]{2,4})[\s\-_]([A-Za-z]{2,4})[\s\-_]?(\d{1,4})\b")`. THE module-level DESK-MATTER-### regex. 3 groups: desk(2-4 alpha), matter(2-4 alpha), digits(1-4). First separator required, second optional (`BB-AUK001` matches). `resolve_project_number` uses `_NUMBER_RE.finditer(text)` at line 211; `register_project` uses `_NUMBER_RE.fullmatch` at line 98. **`extract_project_codes` MUST reuse `_NUMBER_RE` — do not duplicate the pattern.**
- `resolve_project_number` — `kbl/project_registry_store.py:191` — `resolve_project_number(text: str) -> Optional[dict]`. On match: 8-key dict `{project_number, desk_code, desk_owner, matter_slug, clickup_list_id, participants, aliases, status}`. On no-match: `None`. Filters `status='active'`, single-return, deterministic first-REGISTERED-in-text-order (unregistered regex hits skipped, line 245-249). On internal exception: logs + returns `None` (line 238-240) — so a thrown error is indistinguishable from no-match via its return alone (informs D3 handling below).
- `resolve_by_participant` — `kbl/project_registry_store.py:243` — `resolve_by_participant(channel: str, value: str) -> list[dict]`. Returns ACTIVE projects whose `participants` JSONB `@> [{channel, value}]`. Email channel value is the literal string `"email"` (seed row proof, line 305: `participants=[{"channel": "email", "value": "balazs@brisengroup.com"}]`). Returns `[]` on empty args or exception (line 260-262).
- `seed_bb_pilot` — `kbl/project_registry_store.py:303-307` — line **304** hardcodes `matter_slug="annaberg"`. `aliases` (line 306 `["annaberg", "aukera annaberg"]`) is a human mnemonic set, NOT the matter_slug. "Callable one-off; NOT auto-run."
- `scripts/seed_bb_pilot_registry.py` — line **21** `MATTER_SLUG = "annaberg"` (+ docstring lines 10-11 + the inline comment "AUK is the display mnemonic, not the matter slug"). `__main__`-guarded, NOT auto-run.
- `tests/test_project_registry.py:311-321` — `test_seed_bb_pilot_registry_constants_consistent` asserts `seed.MATTER_SLUG == "annaberg"` at line **318**. This breaks when the seed flips; D MUST update it to `"aukera"`. All other tests use the fixture-vault `CANONICAL_SLUG = "alpha"` (line 26) and are unaffected.
- **BRIEF-C hook** (from `scratchpad/brief_c_draft.md`): the per-arrival loop runs inside a per-row `try/except` (the `except` at draft line 323 → `conn.rollback()` + `failed += 1` + `continue`). D inserts its branch between block `(e)` DUPLICATE's trailing `continue` (draft line 296) and the `# (f) SAFE DEFAULT` comment (draft line 298). `row_id = result.get("id")` is available from `issue_ticket` (draft line 274). C's helpers: `write_terminal_status(conn, *, ticket_row_id, terminal_status, terminal_reason, raw_source_id) -> bool` (draft §2), `_claim_for_terminal(conn, ticket_row_id) -> Optional[int]` (draft §5), `fast_lane` local (draft line 227). Stats counters init at draft line 226; success dict at draft lines 335-346.

### Engineering Craft Gates

**Diagnose.** The bug-shaped risks are: (a) a fake/unregistered code clearing on shape alone; (b) two codes fast-boarding into the wrong matter; (c) an exception in the resolve/bind composition being read as a clean clear. Reproduce each as a failing test BEFORE wiring: an unregistered 1-code arrival must land TICKET (resolve returns None); a 2-distinct-code arrival must land TICKET (conflict gate); a monkeypatched `resolve_by_participant` that raises must increment `failed` and land TICKET, never FAST_TICKET.

**Prototype.** `extract_project_codes` is pure regex — prototype it standalone against `_NUMBER_RE` and confirm the canonical-form dedup (`'bb auk 001'` and `'BB-AUK001'` collapse to one `'BB-AUK-001'`) before folding in. No DB needed.

**TDD.** Write the conflict-gate, regex-only-no-row, valid-code+binding, valid-code-no-binding, and error tests FIRST. The pure-regex `extract_project_codes` tests need NO live PG (no `store` fixture). They must pass after the change; the branch tests exercise C's merged loop.

### Implementation

Two files: `kbl/project_registry_store.py` (the net-new helper + the seed slug fix) and `orchestrator/airport_ticketing_bridge.py` (the one new branch in C's `run_tick` + the `fast_ticket` counter). Plus the breaking assertion in `tests/test_project_registry.py`. Signatures VERIFIED against `origin/main` @ `a87cab2` and `scratchpad/brief_c_draft.md`.

**1. NET-NEW `extract_project_codes` — place after line 240 (`resolve_project_number`'s end), before `resolve_by_participant` (line 243). Pure regex, reuses `_NUMBER_RE`, NO DB:**

```python
def extract_project_codes(text: str) -> list[str]:
    """Conflict pre-check primitive (F4): DISTINCT valid-SHAPED DESK-MATTER-### codes
    in text order. Pure regex (reuses _NUMBER_RE), NO registry/DB hit. >1 distinct code
    => Box 5 treats it as a cross-matter CONFLICT and does NOT fast-board. Canonical
    form ('BB-AUK-001') matches register_project's stored display (line 116), so
    'bb auk 001' and 'BB-AUK001' collapse to one code. Regex shape alone NEVER clears —
    the actual clearance still requires resolve_project_number (registry, active) AND
    participant binding; this only filters shape + counts distinct codes for the
    conflict gate (#4679.3)."""
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _NUMBER_RE.finditer(text):
        code = f"{m.group(1)}-{m.group(2)}-{m.group(3)}".upper()
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out
```

Prototyped against the live regex: `'AO-MOV-002 then BB-AUK-001'` → `['AO-MOV-002','BB-AUK-001']`; `'bb auk 001 and BB-AUK001'` → `['BB-AUK-001']` (dedup); `'ref ZZ-XX-99 see BB-AUK-001'` → `['ZZ-XX-99','BB-AUK-001']`; `''` → `[]`.

**2. The hard-lane branch — insert in C's `run_tick` between block (e) DUPLICATE's trailing `continue` (`brief_c_draft.md:296`) and the `# (f) SAFE DEFAULT` comment (`brief_c_draft.md:298`).** Add the import at the top of the file: `from kbl.project_registry_store import extract_project_codes, resolve_project_number, resolve_by_participant`.

```python
                # (e.5) HARD FAST LANE — project-number-driven fast-board (BRIEF-D).
                #   Gated on the existing `fast_lane` local (BOX5_FAST_LANE_ENABLED,
                #   default false). When false OR the lane does not cleanly clear,
                #   control FALLS THROUGH to the unchanged (f) SAFE DEFAULT TICKET.
                #   FAST_TICKET requires ALL of: exactly 1 distinct code; a registered
                #   ACTIVE row; sender bound to THAT project's participant set.
                #   Any conflict / no-row / no-binding / exception -> TICKET (never
                #   VISIBLE_HOLD, never FAST_TICKET). #4679.2/.3 + #4680.1 + D3.
                if fast_lane and row_id:
                    try:
                        hl_text = f"{arrival.subject} {arrival.full_body}"
                        codes = extract_project_codes(hl_text)
                        if len(set(codes)) == 1:
                            resolved = resolve_project_number(hl_text)  # active-filtered, single-return; None on no-match OR internal error
                            if resolved is not None:
                                pn = resolved["project_number"]
                                hits = resolve_by_participant("email", (arrival.sender_email or "").strip().lower())
                                bound = any(h["project_number"] == pn for h in hits)
                                # thread-continuity (the OR branch of #4679.2) is a
                                # documented TODO — no queryable email-thread store
                                # exists on main; pilot v1 is participant-binding-only.
                                if bound:
                                    claim = _claim_for_terminal(conn, row_id)
                                    if claim is None:
                                        lease_skipped += 1
                                        conn.commit()
                                        continue
                                    claimed += 1
                                    if write_terminal_status(
                                        conn,
                                        ticket_row_id=row_id,
                                        terminal_status="FAST_TICKET",
                                        terminal_reason=f"hard_lane_project_code_participant_bound:{pn}",
                                        raw_source_id=arrival.message_id,
                                    ):
                                        terminal_written += 1
                                        fast_ticket += 1
                                    if result.get("ok"):
                                        issued += 1
                                    conn.commit()
                                    max_received = _advance(max_received, arrival.received_date)
                                    continue
                        # CONFLICT (>1 code), no-code (0), no registered row, or
                        # unbound sender: do NOT continue — fall through to (f) TICKET.
                    except Exception as exc:
                        # ERROR NEVER AUTO-FAST_TICKETs (#blocker D3). A raised error in
                        # the extract/resolve/bind composition is NOT a clear: roll back,
                        # count failed, and fall through to the safe-default TICKET path.
                        conn.rollback()
                        failed += 1
                        logger.warning("airport_ticketing hard-fast-lane row failed: %s", exc)
                        # fall through to (f) TICKET (do NOT continue, do NOT FAST_TICKET)

                # (f) SAFE DEFAULT — TICKET (full desk review). [BRIEF-C, unchanged]
```

> The inner `try/except` wraps **D's own** composition only — it does not swallow C's existing per-row handler. A raised error falls through to (f) TICKET after the rollback (the resolvers themselves swallow their own exceptions to `None`/`[]`, so the only escaping raises come from `_claim_for_terminal`/`write_terminal_status`, which D must not let auto-clear). A clean `None` from `resolve_project_number` (no match) or empty `hits` (no binding) is normal — it simply falls through to (f) TICKET with NO failed increment. Distinguish: "resolver returned None/[]" = normal no-match/no-binding → TICKET; "code raised" = `failed` → TICKET.

**3. The `fast_ticket` counter.** Add `fast_ticket = 0` to C's counter init line (`brief_c_draft.md:226`, alongside `claimed = terminal_written = lease_skipped = deterministic_cleared = defaulted_ticket = 0`), and add `"fast_ticket": fast_ticket,` to C's success stats dict (`brief_c_draft.md:335-346`). Do NOT increment `deterministic_cleared` (DUPLICATE/REJECT_NOISE only) nor `defaulted_ticket` for a fast-lane clear.

**4. SEED CORRECTION — `annaberg` → `aukera` (slug only; aliases unchanged).**

- `kbl/project_registry_store.py:304` — change `matter_slug="annaberg",` → `matter_slug="aukera",`. Leave `project_number="BB-AUK-001"`, `desk_owner="baden-baden-desk"`, `participants`, and `aliases=["annaberg", "aukera annaberg"]` unchanged.
- `scripts/seed_bb_pilot_registry.py:21` — change `MATTER_SLUG = "annaberg"` → `MATTER_SLUG = "aukera"`. Update the now-stale docstring lines 10-11 and the inline comment so they no longer claim AUK is the display mnemonic "NOT the aukera matter" (the matter IS now aukera); only the assignment line is load-bearing. Leave `PROJECT_NUMBER`, `DESK_OWNER`, `ALIASES` unchanged. Seed stays `__main__`-guarded / un-run.
- `tests/test_project_registry.py:318` — change `assert seed.MATTER_SLUG == "annaberg"` → `assert seed.MATTER_SLUG == "aukera"`; update the docstring at lines 314-315 to read aukera. (`is_canonical('aukera')` is True, so `register_project`'s gate accepts it; `desk_owner='baden-baden-desk'` stays consistent with `DESK_CODES['BB']`.)

### Key Constraints

- **`extract_project_codes` reuses `_NUMBER_RE`** (line 45) — no duplicate pattern. Pure, no DB.
- **Regex shape alone NEVER fast-clears** (#4679.3) — registry validation via `resolve_project_number` is mandatory; an unregistered 1-code text returns `None` → TICKET.
- **>1 distinct code → never FAST_TICKET** (F4) — falls through to TICKET.
- **Binding mandatory** (#4679.2 + #4680.1) — `resolve_by_participant('email', sender_email.lower())` must return the SAME `project_number` the resolver cleared. Sender-only matching is not the test here — it is "sender ∈ THIS cleared project's manifest". Pilot v1 uses **participant-binding only**.
- **Thread-continuity = documented TODO.** The OR branch of #4679.2 has no clean signal on main: `email_messages.thread_id` exists but `airport_tickets` does NOT persist it as a queryable column (only `source_id=message_id` and the unrelated `bus_thread_id`; the email thread_id lands only as free-text luggage at `airport_ticketing_bridge.py:225`). Do NOT invent a thread signal or scan JSONB luggage. Note the future fix in the ship report: add a queryable `email_thread_id` column to `airport_tickets` (populated from `EmailArrival.thread_id` at reserve time) so a later brief can do an indexed "prior FAST_TICKET/TICKET in the same email thread for the same project" lookup.
- **Safe fallback = `TICKET`** (full desk review), NEVER `VISIBLE_HOLD`. `VISIBLE_HOLD` is its own brief (#4677.7) and is NOT in BRIEF-B's 6-state CHECK (`DUPLICATE/REJECT_NOISE/REJECT_LOW_RELEVANCE/FAST_TICKET/TICKET/FILE_UNSORTED`) — writing it now violates the CHECK. Conflict / no-row / no-binding / fake-or-dup all → C's existing TICKET path (D simply does NOT `continue`).
- **Gated by `BOX5_FAST_LANE_ENABLED`** — reuse C's `fast_lane` local (do not re-read env). Flag false → branch skipped, C's TICKET default covers everything; D adds nothing live until lead flips the Render flag.
- **Error never auto-FAST_TICKETs** (#blocker D3) — D's own extract/resolve/bind in a `try/except`; any raise → `conn.rollback()` + `failed += 1` + fall through to TICKET. Never FAST_TICKET on error. Every `except` calls `conn.rollback()`; all DB-touching calls are inside try/except.
- **`FAST_TICKET` only on a clean clear** — written exactly once, via `write_terminal_status` after winning `_claim_for_terminal`.
- **`bus_failed` on the fast-lane path is a known no-op edge case (codex G3 awareness).** D's FAST_TICKET arm increments `issued` on `result.get("ok")` but, unlike C's (f) block, omits the `elif result.get("reason") == "bus_failed": failed += 1` arm. A FAST_TICKET clear whose bus post failed therefore increments neither `issued` nor `failed` (the terminal write itself already succeeded). Acceptable for pilot v1 — note it in the ship report; do NOT add VISIBLE_HOLD/retry here.
- **Use raw `subject` + `full_body`** (no `.lower()`) for extract/resolve — `_NUMBER_RE` and `_match_key` uppercase internally; lowercasing is unnecessary. Lowercase ONLY the `sender_email` for the binding key (matches the seed convention).
- **Seed stays gated/un-run** — D corrects the slug only; running the seed is a separate Director-GO step.

### Verification

New pure-regex tests + branch tests in `tests/test_project_registry.py` (extend the existing 347-line file). The `extract_project_codes` tests need NO live PG / NO `store` fixture (pure regex). The branch behavior is exercised against C's merged `run_tick` (live-PG, auto-skips without `TEST_DATABASE_URL`).

| # | Test | Assert |
|---|------|--------|
| 1 | `extract_project_codes` distinct/order | `extract_project_codes('AO-MOV-002 then BB-AUK-001') == ['AO-MOV-002','BB-AUK-001']`; `extract_project_codes('ref ZZ-XX-99 see BB-AUK-001') == ['ZZ-XX-99','BB-AUK-001']`; `extract_project_codes('') == []` |
| 2 | `extract_project_codes` dedup (conflict input) | `extract_project_codes('bb auk 001 and BB-AUK001') == ['BB-AUK-001']`; and `len(set(extract_project_codes('AO-MOV-002 and BB-AUK-001'))) == 2` (the >1 conflict trigger) |
| 3 | regex-only, no registry row → TICKET | a 1-code arrival whose code is unregistered: `resolve_project_number` → None; arrival's `terminal_status == 'TICKET'`, NOT `FAST_TICKET`; `fast_ticket` not incremented |
| 4 | valid code + participant binding → FAST_TICKET | seed BB-AUK-001 active with `participants=[{channel:email,value:sender}]`; arrival from that sender carrying `BB-AUK-001`, flag ON: `terminal_status == 'FAST_TICKET'`, `terminal_reason` startswith `hard_lane_project_code_participant_bound`, `fast_ticket == 1` |
| 5 | valid code, NO binding → TICKET | same registered code but sender NOT in participants: `resolve_by_participant` returns no matching `project_number`; `terminal_status == 'TICKET'`, `fast_ticket == 0` |
| 6 | >1 distinct code → TICKET | arrival carrying two distinct registered codes, flag ON: conflict gate fires; `terminal_status == 'TICKET'`, NOT `FAST_TICKET` |
| 7 | error → TICKET + failed | monkeypatch `resolve_by_participant` (or `_claim_for_terminal`) to raise on one row: that row's `terminal_status` is NOT `FAST_TICKET` (TICKET or NULL per fall-through), tick increments `failed` (NOT `deterministic_cleared`/`fast_ticket`), remaining rows still process |
| 8 | flag-off no-op | with `BOX5_FAST_LANE_ENABLED` unset and the registered-code+bound arrival: `terminal_status == 'TICKET'` (the branch is skipped), `fast_ticket == 0` |
| 9 | seed writes aukera | `import scripts.seed_bb_pilot_registry as seed; assert seed.MATTER_SLUG == 'aukera'`; and `seed_bb_pilot`'s row dict has `matter_slug == 'aukera'` |
| 10 | compile + targeted suite | `python3 -c "import py_compile; py_compile.compile('orchestrator/airport_ticketing_bridge.py', doraise=True); py_compile.compile('kbl/project_registry_store.py', doraise=True)"`; `pytest tests/test_project_registry.py -v`; plus `tests/test_box5_ticketing_runner.py` to prove no regression in C's loop |

## Files Modified

- `kbl/project_registry_store.py` — add `extract_project_codes()` (after line 240, before `resolve_by_participant`); change `matter_slug="annaberg"` → `"aukera"` at line 304 (`seed_bb_pilot`).
- `orchestrator/airport_ticketing_bridge.py` — add the import of `extract_project_codes`/`resolve_project_number`/`resolve_by_participant`; insert the hard-lane branch in `run_tick` between C's blocks (e) and (f); add `fast_ticket` counter init + `"fast_ticket"` stats key.
- `scripts/seed_bb_pilot_registry.py` — change `MATTER_SLUG = "annaberg"` → `"aukera"` at line 21 (+ stale docstring/comment).
- `tests/test_project_registry.py` — add cases 1–8; flip the breaking assertion at line 318 (`seed.MATTER_SLUG == "aukera"`) + its docstring.

## Do NOT Touch

- **`resolve_project_number` internals** — its single-return, active-filtering, deterministic-text-order, and exception→None behavior are #439-locked. D consumes it; D does not re-implement ordering or re-filter.
- **BRIEF-C's deterministic-clear logic** (blocks (b) REJECT_NOISE, (e) DUPLICATE) and its **safe-default (f) TICKET** block — D inserts a tier between (e) and (f) and falls through to (f); it does not alter (b)/(e)/(f).
- **The `terminal_status` CHECK constraint** (#441, 6-state) — do not add states, do not migrate. `FAST_TICKET` is already permitted; that is the only state D writes.
- **The live `status` / `check_in_outcome` axes** — D writes only the `terminal_status` axis (via `write_terminal_status`). The candidate/sent/failed `status` axis and the receipt `check_in_outcome` axis are untouched.
- **`VISIBLE_HOLD`** — its own brief (#4677.7); not in the CHECK; never written here.
- **`_NUMBER_RE`** — reuse, do not edit or duplicate. **`DESK_CODES`** — untouched. **`aliases`** in the seed — unchanged (human mnemonic, not the matter_slug).
- **No new scheduler / cursor / lease / advisory lock / table / migration.** Reuse C's `_claim_for_terminal` + `write_terminal_status` + watermark machinery.

## Quality Checkpoints

- After `extract_project_codes`: run the case-1/2 pure-regex tests in isolation (no PG) — they must pass without a `store` fixture.
- After the branch: with the flag OFF, run `tests/test_box5_ticketing_runner.py` and confirm C's behavior is byte-for-byte unchanged (D is a no-op when `fast_lane` is false).
- Grep guards: `grep -c 'VISIBLE_HOLD' orchestrator/airport_ticketing_bridge.py` == 0; `grep -c 're.compile' kbl/project_registry_store.py` unchanged from main; `grep -c 'matter_slug="annaberg"\|MATTER_SLUG = "annaberg"'` across the two seed files == 0.
- Confirm the only `terminal_status='FAST_TICKET'` write in the file is inside the `if bound:` arm after a non-None active resolve.
- Ship report MUST state: (a) participant-binding-only for pilot v1; (b) thread-continuity deferred with the proposed `email_thread_id`-column fix; (c) seed corrected but un-run (pending Director GO).

## Verification SQL

```sql
-- After a flag-ON tick over a seeded bound arrival: exactly one FAST_TICKET, audited.
SELECT id, terminal_status, terminal_reason, raw_source_table, raw_source_id
  FROM airport_tickets
 WHERE terminal_status = 'FAST_TICKET'
 ORDER BY terminal_outcome_written_at DESC
 LIMIT 5;
-- Expect terminal_reason LIKE 'hard_lane_project_code_participant_bound:BB-AUK-001',
-- raw_source_table = 'email_messages', raw_source_id = the arrival message_id.

-- Idempotency: re-running the tick writes no second terminal (status-guard holds).
SELECT id, terminal_outcome_written_at
  FROM airport_tickets
 WHERE terminal_status = 'FAST_TICKET';
-- terminal_outcome_written_at must be UNCHANGED across a second tick.

-- No forbidden state ever written.
SELECT DISTINCT terminal_status FROM airport_tickets WHERE terminal_status IS NOT NULL;
-- Must be a subset of {DUPLICATE, REJECT_NOISE, REJECT_LOW_RELEVANCE, FAST_TICKET, TICKET, FILE_UNSORTED}.
-- VISIBLE_HOLD must NOT appear.

-- Audit row for every FAST_TICKET write.
SELECT action_type, target_task_id, success
  FROM baker_actions
 WHERE action_type = 'airport_ticket.terminal_written'
   AND payload::jsonb ->> 'terminal_status' = 'FAST_TICKET'
 ORDER BY created_at DESC LIMIT 5;

-- Seed correction landed (run only under Director GO, after seeding):
SELECT project_number, matter_slug, desk_owner, status
  FROM project_registry
 WHERE project_number = 'BB-AUK-001';
-- Expect matter_slug = 'aukera', desk_owner = 'baden-baden-desk', status = 'active'.
```