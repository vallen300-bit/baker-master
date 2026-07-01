# BRIEF: BOX5_SOFT_FAST_LANE_1 — manifest soft fast lane (>=2-signal routed TICKET, sender-only forbidden)

## Context

Box 5, **Build Order 7 — the LAST Box 5 brief.** This brief plugs the MANIFEST SOFT FAST LANE into the per-arrival terminal-decision chain that BRIEF-C (`BOX5_TICKETING_RUNNER_1`) builds inside `run_tick` (`orchestrator/airport_ticketing_bridge.py:780`) and that BRIEF-D (`BOX5_HARD_FAST_LANE_1`) extends. E inserts a NEW precedence tier — call it block **(e.7)** — **AFTER D's `(e.5)` hard-lane FAST_TICKET arm** (`scratchpad/brief_d_draft.md` lines 125–178) and **BEFORE C's `(f)` safe-default TICKET block** (`scratchpad/brief_c_draft.md` line 298). Because both D and E `continue` on a clean clear, E only executes when **D's hard lane did NOT clear** — the number was missing, unregistered/inactive, conflicting, or the sender was not participant-bound. That is exactly the "number MISSING or hard lane did not clear" precondition for the soft lane; no extra guard is needed.

**Hard dependency: BRIEF-C AND BRIEF-D must both be MERGED first.** E edits C's `run_tick` body, calls C's net-new helpers (`write_terminal_status`, `_claim_for_terminal`, `_advance`, `fast_lane` local), and sits structurally after D's `(e.5)` block. On `origin/main` @ `a87cab2` (`dispatch: BOX5_TICKETING_RUNNER_1 -> b4`) none of C's or D's helpers/branches exist yet (`grep 'write_terminal_status\|fast_lane_enabled\|extract_project_codes' orchestrator/airport_ticketing_bridge.py kbl/project_registry_store.py` returns zero for the airport bridge). **Do NOT start E's branch until BOTH C and D land.** If either is reverted, E is blocked until it re-merges.

E consumes the **#439 registry** soft-signal primitives (live on `origin/main`, `kbl/project_registry_store.py`): `resolve_by_participant(channel, value) -> list[dict]` (line 243 — participant-set membership, `status='active'` filtered) and `resolve_by_alias(text) -> list[dict]` (line 265 — matter-alias word-boundary match in text, `status='active'` filtered). Each returns 8-key dicts via `_row_to_dict` (line 168) carrying `project_number`, `matter_slug`, `desk_owner`, `status`. The terminal schema with routing columns (`matter_slug`/`desk_owner`/`manifest_match_signals`/`confidence`, #441) is merged; the 6-state CHECK does NOT include `VISIBLE_HOLD`.

**Locked soft-lane rules this brief honors (#4680):**
- Number **MISSING (or hard lane did not clear)** + manifest match = SOFT fast lane. E runs only after D falls through.
- Requires **>=2 INDEPENDENT signals** AND **no competing active manifest conflict**.
- **SENDER-ONLY matching is FORBIDDEN** — one signal never clears; sender (participant) alone never clears.
- **Weak / conflicting → TICKET** (full desk review), NEVER `VISIBLE_HOLD` (its own brief #4677.7, not in the 6-state CHECK).
- **#blocker D3** — a manifest-check exception NEVER auto-clears → safe-default TICKET + count `failed`. Distinguish "threw" from "no match".
- **Soft clear is INFERENCE, not an authoritative project number → `terminal_status='TICKET'` (a ROUTED ticket), NOT `FAST_TICKET`.** `FAST_TICKET` is reserved for D's authoritative hard lane.

### Surface contract: N/A — backend soft-lane manifest decision logic, no clickable UI surface.

### Harness V2

**Context Contract**

- **Inputs:**
  - The soft-lane branch inside C's `run_tick` per-arrival loop, positioned after D's `(e.5)` and before C's `(f)`. Per-arrival signals live on the `EmailArrival` frozen dataclass (`airport_ticketing_bridge.py:57`): `message_id`, `sender_email`, `subject`, `full_body`, `received_date`.
  - `row_id = result.get("id")` from C's `issue_ticket(ticket, conn)` (`brief_c_draft.md:274`) — the only `airport_tickets` row id available at the decision point.
  - The existing `fast_lane` local computed once at `run_tick` top (`brief_c_draft.md:227`, `fast_lane = fast_lane_enabled()`, env `BOX5_FAST_LANE_ENABLED`, default false). **REUSE it — do NOT re-read the env.**
  - Registry: `resolve_by_participant('email', sender_email.strip().lower())` (signal 1) + `resolve_by_alias(subject + ' ' + full_body)` (signal 2). Both #439, merged.
- **Outputs:** on a clean >=2-signal no-conflict soft match, `terminal_status='TICKET'` (ROUTED) written via C's `write_terminal_status` **extended** with the routing columns (`matter_slug`, `desk_owner`, `manifest_match_signals`, `confidence`); a NEW `soft_ticket` per-tick counter added to C's stats dict as `'soft_ticket': soft_ticket`. No other output shape change.
- **Side-effects:** one terminal write (routed `TICKET`) + its `baker_actions` audit row (both inside `write_terminal_status`); a `_claim_for_terminal` row lock. NO new table, NO schema change, NO new scheduler/cursor/lease. Reuses D-added registry import (extend it).
- **Idempotency invariants:** E writes the terminal ONLY through C's status-guarded `write_terminal_status` (`... WHERE id=%s AND terminal_status IS NULL`) after winning `_claim_for_terminal` (`FOR UPDATE SKIP LOCKED`). Re-runs / overlapping ticks match 0 rows → no double routed-TICKET. The routing columns are written **inside the same guarded UPDATE** (via optional kwargs appended to the SET clause), so they are never written outside the `terminal_status IS NULL` guard. The resolvers are read-only + swallow their own exceptions to `[]` (same input → deterministic output within a tick).

**Task class:** **additive decision logic; possibly extends `write_terminal_status` with optional routing kwargs.** One new branch (block e.7) in C's `run_tick` between D's `(e.5)` and C's `(f)`; four optional kwargs appended to C's `write_terminal_status` signature (default None, appended to the SET clause only when provided — byte-compatible for C's and D's existing callers); one new counter + stats key. No net-new registry helper (E composes the two existing #439 resolvers). No schema migration, no new job, no new lock.

**Done rubric (machine-checkable):**

1. **Runs only after the hard lane misses + flag on**: E's branch is gated `if fast_lane and row_id:` reusing C's pre-computed `fast_lane` local, and is positioned textually AFTER D's `(e.5)` block (which `continue`s on a FAST_TICKET clear) and BEFORE C's `# (f) SAFE DEFAULT` comment. With the flag false, the branch is skipped and C's TICKET default covers everything.
2. **>=2 signals required**: FAST clear requires BOTH `resolve_by_participant` AND `resolve_by_alias` to return a hit for the SAME `project_number` — encoded as `len(agree) == 1` where `agree = participant_project_numbers & alias_project_numbers`. A test with only one resolver hitting must NOT clear.
3. **Sender-only never clears**: an arrival where only `resolve_by_participant` hits (alias empty / disagrees) → `agree` empty → `terminal_status == 'TICKET'`, `soft_ticket` not incremented (test `sender-only -> TICKET`).
4. **1 signal never clears**: symmetrically, alias-only hit → `agree` empty → TICKET (test `alias-only -> TICKET`).
5. **Conflict → TICKET**: participant and alias each hit but on DIFFERENT projects, OR the agreement set has >1 element → `len(agree) != 1` → falls through to (f) TICKET, no routed clear (test `2 candidate projects -> TICKET`).
6. **Soft clear → routed TICKET with routing columns set, NOT FAST_TICKET**: on `len(agree) == 1`, the write is `terminal_status='TICKET'` with `matter_slug`, `desk_owner`, `manifest_match_signals`, `confidence` all populated. `grep -c "terminal_status=\"FAST_TICKET\"\|terminal_status='FAST_TICKET'"` in E's branch is 0 (only D writes FAST_TICKET).
7. **Never VISIBLE_HOLD**: `grep -c 'VISIBLE_HOLD' orchestrator/airport_ticketing_bridge.py` is 0; every non-clear soft path falls through to C's existing TICKET block.
8. **Error never auto-clears**: E's own resolve/compose/write block is wrapped so any raised exception increments `failed` and falls through to TICKET (never a routed clear, never `soft_ticket++`); a clean `[]`/no-agreement from a resolver is a normal no-match → TICKET (test `error -> TICKET + failed`). `deterministic_cleared` and `fast_ticket` are never incremented by E.

**Gate plan:** G1 (builder self-test: `pytest tests/test_project_registry.py -v` + the new soft-lane branch tests green; `tests/test_box5_ticketing_runner.py` green to prove no regression in C's loop; `python3 -c "import py_compile; py_compile.compile('orchestrator/airport_ticketing_bridge.py', doraise=True); py_compile.compile('kbl/project_registry_store.py', doraise=True)"`) → **codex G3** (verifier verdict on the diff) → **lead `/security-review` G4** → **lead merge**. Ships **dark** behind `BOX5_FAST_LANE_ENABLED` (default false) — flag false → C's safe-default TICKET covers everything, E adds nothing live until lead flips the Render flag.

## Estimated time

3–4 hours (one builder). The branch + kwarg extension are surgical; most cost is the signal-fusion / conflict / sender-only / error test matrix. Sits on top of C's concurrency + idempotency + D's precedence machinery, all reused unchanged.

## Complexity

**Medium.** Edits are small and all precedents are in-repo, but the correctness surface (>=2-signals-mandatory, sender-only-never-clears, conflict→TICKET, error-never-auto-clears, gate honored, TICKET-not-FAST_TICKET) must be proven by test, not inspection.

## Prerequisites

- **BRIEF-C MERGED.** E edits C's `run_tick` body and calls C's net-new helpers `write_terminal_status` (`brief_c_draft.md` §2), `_claim_for_terminal` (§5), `_advance` (§ note after 387), and reuses C's `fast_lane = fast_lane_enabled()` local (§4, run_tick line 227) plus the `(f)` block structure.
- **BRIEF-D MERGED.** E's block (e.7) is positioned immediately after D's `(e.5)` hard-lane block. E depends on D's `continue`-on-clear so that E only runs when the hard lane did NOT clear. D also adds the `from kbl.project_registry_store import ...` import that E extends with `resolve_by_alias`.
- **#439 merged** — `resolve_by_participant` + `resolve_by_alias` live on `origin/main` (`kbl/project_registry_store.py`). Confirmed.
- **#441 merged** — routing columns `matter_slug`/`desk_owner`/`manifest_match_signals`/`confidence` + the 6-state CHECK are live (confirmed types below). Confirmed.
- **Serialize-after-D (explicit).** E must be authored, gated, and merged strictly after BOTH C and D. Do not parallelize with D: E's branch references file regions ((e.5) end, (f) start, C's helpers) that only exist after C+D land. On `origin/main` @ `a87cab2` none exist — branch E off a base containing both merges.

### Problem

After BRIEF-D, an arrival with no clean registered+bound project number still falls to a full-review desk `TICKET`. Many such arrivals are nonetheless routable by inference: the sender is a known project participant AND a registered matter alias appears in the subject/body. When TWO independent manifest signals agree on ONE project, the arrival can be routed straight to the right desk without full triage — but as a ROUTED `TICKET`, not a `FAST_TICKET`, because inference is weaker than an authoritative project number. Four failure modes must be foreclosed: (1) a single signal (sender-only, or alias-only) must never clear — sender-only is explicitly forbidden (#4680); (2) two signals pointing at different projects (a competing manifest conflict) must not route; (3) a weak/no match must fall to full-review TICKET, never `VISIBLE_HOLD`; (4) a DB/registry exception must never be misread as a clean route (#blocker D3). E adds exactly this one tier, gated dark, with TICKET as the safe fallback for every uncertain path.

### Current State (file:line)

- `resolve_by_participant` — `kbl/project_registry_store.py:243` — `def resolve_by_participant(channel: str, value: str) -> list[dict]`. Returns ACTIVE projects whose `participants` JSONB `@> [{channel, value}]` (EXACT-EQUAL, CASE-SENSITIVE on both channel and value; `ORDER BY project_number LIMIT 10`). Guard: empty channel OR value → `[]`. Swallows exceptions → `[]` (line 260-262). Email channel value = literal `"email"`; call with `sender_email.strip().lower()`. **Sender-only match = ONE signal — never clears alone.**
- `resolve_by_alias` — `kbl/project_registry_store.py:265` — `def resolve_by_alias(text: str) -> list[dict]`. Loads up to 200 ACTIVE rows (`ORDER BY project_number LIMIT 200`), then per row tests each alias as a true word-boundary regex `re.search(r'\b'+re.escape(a)+r'\b', text, re.IGNORECASE)` (`re.escape` handles punctuation + multi-word aliases like `'aukera annaberg'`). One hit per project, returns `out[:10]`. Guard: empty text → `[]`. Swallows exceptions (partial `out` kept). **Second, independent signal.**
- `_row_to_dict` — `kbl/project_registry_store.py:168` — the return shape for both resolvers: 8 keys `{project_number, desk_code, desk_owner, matter_slug, clickup_list_id, participants, aliases, status}`. Confirms each hit carries `project_number` + `matter_slug` + `desk_owner`.
- `ensure_airport_ticket_terminal_columns` — `orchestrator/airport_ticketing_bridge.py:343` — the routing columns E populates (VERIFIED live on `origin/main` @ `a87cab2`): `project_code TEXT` (line 363), `matter_slug TEXT` (364), `desk_owner TEXT` (365), `confidence NUMERIC(3,2)` (367), `manifest_match_signals JSONB NOT NULL DEFAULT '[]'::jsonb` (372). `NUMERIC(3,2)` = max 9.99 with 2 decimals — a 0.00–1.00 confidence fits. `manifest_match_signals` defaults to `'[]'`.
- `_json_param` — `orchestrator/airport_ticketing_bridge.py:146` — module-local JSONB param adapter used by `reserve_ticket`/`mark_ticket_sent`/C's `write_terminal_status`. Route `manifest_match_signals` through it. **No new import.** (Type note: `_json_param` is hinted `dict[str, Any]` but E passes a `list` for `manifest_match_signals` — runtime-safe (`psycopg2.extras.Json` / the `json.dumps` fallback both accept lists), so a linter/type-checker flag here is a false positive, not a bug.)
- **BRIEF-C hook** (`scratchpad/brief_c_draft.md`): per-arrival loop inside a per-row `try/except` (the `except` at draft line 323 → `conn.rollback()` + `failed += 1` + `continue`). `write_terminal_status(conn, *, ticket_row_id, terminal_status, terminal_reason, raw_source_id) -> bool` (§2, draft line 120) — status-guarded (`WHERE id=%s AND terminal_status IS NULL RETURNING id, ticket_id`), writes the `baker_actions` audit row, does NOT currently write routing columns. `_claim_for_terminal(conn, ticket_row_id) -> Optional[int]` (§5, draft line 364). `fast_lane` local (draft line 227). `_advance` helper (draft note after line 387). Counter init at draft line 226; success stats dict at draft lines 335-346.
- **BRIEF-D hook** (`scratchpad/brief_d_draft.md`): block `(e.5)` HARD FAST LANE (draft lines 125-178) sits between C's (e) DUPLICATE and (f) SAFE DEFAULT. On a clean clear it writes `FAST_TICKET` + `continue`s (draft line 166); on any miss/conflict/exception it does NOT `continue` — control falls through. D adds the import `from kbl.project_registry_store import extract_project_codes, resolve_project_number, resolve_by_participant` (draft line 122). **E's block goes immediately after D's `(e.5)` block ends (its trailing fall-through, draft line 176-177) and before C's `# (f) SAFE DEFAULT` comment.**

### Engineering Craft Gates

**Diagnose.** The bug-shaped risks: (a) a single signal clearing (sender-only, forbidden); (b) two signals on different projects routing into the wrong matter; (c) an exception in the resolve/compose/write block read as a clean route. Reproduce each as a FAILING test BEFORE wiring: a participant-only arrival must land TICKET (alias empty → no agreement); a two-different-project arrival must land TICKET (`len(agree) != 1`); a monkeypatched `write_terminal_status` (or `_claim_for_terminal`) that raises must increment `failed` and land TICKET, never a routed clear.

**Prototype.** The signal fusion is pure set logic over the two resolvers' outputs — prototype `agree = {h['project_number'] for h in p_hits} & {h['project_number'] for h in a_hits}` against a seeded BB-AUK-001 (participant + alias both registered) and confirm `len(agree) == 1` only when both point at the same project. No throwaway DB needed beyond the standard `store` fixture.

**TDD.** Write the sender-only→TICKET, alias-only→TICKET, participant+alias-same-project→routed-TICKET, 2-candidate-conflict→TICKET, and error→TICKET+failed tests FIRST. The branch behavior is exercised against C+D's merged `run_tick` (live-PG, auto-skips without `TEST_DATABASE_URL`); the pure resolver precedents already exist in `tests/test_project_registry.py`.

### Implementation

Two files: `orchestrator/airport_ticketing_bridge.py` (the `write_terminal_status` kwarg extension + the new soft-lane branch + the `soft_ticket` counter). No net-new registry helper — E composes the two existing #439 resolvers. Signatures VERIFIED against `origin/main` @ `a87cab2` and the C/D drafts.

**1. EXTEND C's `write_terminal_status` with four optional routing kwargs (default None, appended to the SET clause only when provided).** This keeps ONE atomic status-guarded write path (the `terminal_status IS NULL` guard is C's sole idempotency backstop) — a separate follow-up UPDATE would write the routing columns OUTSIDE the guard, risking a double-write on reclaim and taking a second row lock. C's and D's existing callers pass none of the new kwargs → no routing columns written → byte-compatible. Extend C's helper (`brief_c_draft.md` §2) as follows:

```python
def write_terminal_status(
    conn: Any,
    *,
    ticket_row_id: int,
    terminal_status: str,
    terminal_reason: str,
    raw_source_id: str,
    matter_slug: Optional[str] = None,       # NEW (BRIEF-E) — routing columns, appended
    desk_owner: Optional[str] = None,        # NEW  only when provided; None => untouched
    manifest_match_signals: Optional[list] = None,  # NEW  JSONB via _json_param
    confidence: Optional[float] = None,      # NEW  NUMERIC(3,2), 0.00-1.00
) -> bool:
    """Single idempotent terminal write (BRIEF-C). Returns True iff THIS call wrote the
    terminal outcome (rowcount == 1). The `AND terminal_status IS NULL` guard makes
    re-runs / lease-expired reclaims no-ops. BRIEF-E adds four OPTIONAL routing kwargs
    that append to the SET clause ONLY when non-None, so C's and D's callers (which pass
    none) are byte-compatible and no routing column is written on their path."""
    cur = conn.cursor()
    try:
        set_parts = [
            "terminal_status = %s",
            "terminal_reason = %s",
            "processed_at = NOW()",
            "terminal_outcome_written_at = NOW()",
            "raw_source_table = 'email_messages'",
            "raw_source_id = %s",
        ]
        params: list[Any] = [terminal_status, terminal_reason, raw_source_id]
        if matter_slug is not None:
            set_parts.append("matter_slug = %s");   params.append(matter_slug)
        if desk_owner is not None:
            set_parts.append("desk_owner = %s");     params.append(desk_owner)
        if manifest_match_signals is not None:
            set_parts.append("manifest_match_signals = %s")
            params.append(_json_param(manifest_match_signals))  # JSONB
        if confidence is not None:
            set_parts.append("confidence = %s");     params.append(confidence)  # NUMERIC(3,2)
        params.append(ticket_row_id)
        cur.execute(
            "UPDATE airport_tickets SET " + ", ".join(set_parts)
            + " WHERE id = %s AND terminal_status IS NULL RETURNING id, ticket_id",
            params,
        )
        won = cur.fetchone()
        wrote = won is not None
        if wrote:
            ticket_id_text = won[1]
            cur.execute(
                """
                INSERT INTO baker_actions
                    (action_type, target_task_id, payload, trigger_source, success)
                VALUES ('airport_ticket.terminal_written', %s, %s,
                        'airport_ticketing_bridge', TRUE)
                """,
                (
                    ticket_id_text,
                    _json_param({
                        "ticket_id": ticket_id_text,
                        "terminal_status": terminal_status,
                        "terminal_reason": terminal_reason,
                    }),
                ),
            )
        return wrote
    finally:
        cur.close()
```

> The dynamic SET clause is safe from injection — every appended fragment is a fixed string literal with a `%s` placeholder; only `params` carry data. `confidence` is a Python float in `[0,1]` (e.g. `0.60`); psycopg adapts float→numeric — keep 2-decimal precision (values ≥ 10 or 3-digit whole parts violate `NUMERIC(3,2)`; a 0–1 confidence never does). `manifest_match_signals` MUST go through `_json_param()` (JSONB column).

**2. EXTEND D's registry import** at the top of `orchestrator/airport_ticketing_bridge.py`. D added `from kbl.project_registry_store import extract_project_codes, resolve_project_number, resolve_by_participant`. Add `resolve_by_alias`:

```python
from kbl.project_registry_store import (
    extract_project_codes, resolve_project_number,
    resolve_by_participant, resolve_by_alias,   # resolve_by_alias NEW (BRIEF-E)
)
```

**3. The soft-lane branch — insert in C's `run_tick` AFTER D's `(e.5)` hard-lane block (its trailing fall-through, `brief_d_draft.md:176-177`) and BEFORE the `# (f) SAFE DEFAULT` comment (`brief_c_draft.md:298`).**

```python
                # (e.7) SOFT FAST LANE — manifest inference, >=2 independent signals
                #   (BRIEF-E). Runs ONLY when D's (e.5) hard lane did NOT clear (D
                #   `continue`s on a FAST_TICKET clear, so control only reaches here on
                #   number-missing / unregistered / conflict / unbound). Gated on C's
                #   `fast_lane` local (BOX5_FAST_LANE_ENABLED, default false).
                #   A clean clear requires: participant-signal AND alias-signal BOTH
                #   pointing at EXACTLY ONE common project (no competing active manifest).
                #   Sender-only / single-signal / conflict / error -> fall through to
                #   (f) TICKET (full desk review). NEVER FAST_TICKET (that is D's
                #   authoritative lane), NEVER VISIBLE_HOLD. #4680 + #blocker D3.
                if fast_lane and row_id:
                    try:
                        sender = (arrival.sender_email or "").strip().lower()
                        p_hits = resolve_by_participant("email", sender)          # signal 1
                        a_hits = resolve_by_alias(f"{arrival.subject} {arrival.full_body}")  # signal 2
                        p_nums = {h["project_number"] for h in p_hits}
                        a_nums = {h["project_number"] for h in a_hits}
                        agree = p_nums & a_nums  # projects carrying BOTH independent signals
                        # len(agree)==1 enforces BOTH >=2 signals AND no competing
                        # conflict in one check: 0 => <2 signals on one project
                        # (incl. sender-only) -> TICKET; >1 => competing manifests -> TICKET.
                        if len(agree) == 1:
                            pn = next(iter(agree))
                            row = next(h for h in p_hits if h["project_number"] == pn)
                            claim = _claim_for_terminal(conn, row_id)
                            if claim is None:
                                lease_skipped += 1
                                conn.commit()
                                continue
                            claimed += 1
                            if write_terminal_status(
                                conn,
                                ticket_row_id=row_id,
                                terminal_status="TICKET",   # ROUTED, not FAST_TICKET
                                terminal_reason=f"soft_lane_participant+alias:{pn}",
                                raw_source_id=arrival.message_id,
                                matter_slug=row["matter_slug"],
                                desk_owner=row["desk_owner"],
                                manifest_match_signals=[
                                    {"signal": "participant", "value": sender},
                                    {"signal": "alias", "project": pn},
                                ],
                                confidence=0.60,  # fixed pilot constant; no learned model yet
                            ):
                                terminal_written += 1
                                soft_ticket += 1
                            if result.get("ok"):
                                issued += 1
                            conn.commit()
                            max_received = _advance(max_received, arrival.received_date)
                            continue
                        # 0 agreement (incl. sender-only / alias-only) OR >1 (competing
                        # active manifest conflict): do NOT continue -> fall through to
                        # (f) TICKET.
                    except Exception as exc:
                        # ERROR NEVER AUTO-CLEARS (#blocker D3). The resolvers swallow
                        # their own exceptions to [] (a legitimate no-match), so the only
                        # escaping raises come from _claim_for_terminal/write_terminal_status.
                        # A raise is NOT a clear: roll back, count failed, fall through to
                        # (f) TICKET. Never soft_ticket++, never a routed clear.
                        conn.rollback()
                        failed += 1
                        logger.warning("airport_ticketing soft-fast-lane row failed: %s", exc)
                        # fall through to (f) TICKET (do NOT continue, do NOT route)

                # (f) SAFE DEFAULT — TICKET (full desk review). [BRIEF-C, unchanged]
```

> The inner `try/except` wraps **E's own** composition only — it does not swallow C's existing per-row handler. Distinguish: resolver returned `[]` / no agreement = normal no-match → fall through to (f) TICKET with NO `failed` increment; code raised = `failed` → fall through to (f) TICKET. `sender-only` can never clear because the alias signal must independently agree; `alias-only` can never clear because the participant signal must independently agree (`agree` is the intersection).

**4. The `soft_ticket` counter.** Add `soft_ticket = 0` to C's counter init line (`brief_c_draft.md:226`, alongside `claimed = terminal_written = lease_skipped = deterministic_cleared = defaulted_ticket = 0` and D's `fast_ticket = 0`), and add `"soft_ticket": soft_ticket,` to C's success stats dict (`brief_c_draft.md:335-346`). Do NOT increment `deterministic_cleared` (DUPLICATE/REJECT_NOISE only), `defaulted_ticket` (C's plain (f) fall-through), or `fast_ticket` (D's hard lane). Reuse C's existing `failed` counter for soft-lane exceptions (D3-consistent).

### Key Constraints

- **>=2 INDEPENDENT signals mandatory.** `resolve_by_participant` (signal 1) AND `resolve_by_alias` (signal 2) must BOTH hit the SAME `project_number`. Encoded as `len(agree) == 1` where `agree = p_nums & a_nums`.
- **Sender-only + single-signal NEVER clear** (#4680). Participant-only → alias set empty → `agree` empty → TICKET. Alias-only → participant set empty → `agree` empty → TICKET.
- **Conflict → TICKET.** `>1` project in `agree` (or signals on different projects → empty intersection) = competing active manifest → falls through to (f) TICKET, no route.
- **Soft clear → routed `TICKET`, NOT `FAST_TICKET`.** Soft lane is inference. `FAST_TICKET` is reserved for D's authoritative hard lane. On a clean clear, populate `matter_slug` + `desk_owner` (from the resolved project dict) + `manifest_match_signals` (JSONB list of the two matched signal names/values) + `confidence` (0.60 pilot constant). Document `FAST_TICKET`-on-soft as a FUTURE escalation once soft precision is measured.
- **Pilot v1 signals = participant + alias ONLY.** thread-continuity has NO clean primitive on main (BRIEF-D established `airport_tickets` does not persist a queryable `email_thread_id`; the thread id lands only as free-text luggage at `airport_ticketing_bridge.py:225`). document-fingerprint (no persisted content-hash column — `hashlib` is only for `_ticket_id`/`_dedup_key`) and channel-source-ref (`source_channel` is a coarse 6-value enum, not a per-project binding) are DEFERRED. **Do NOT invent thread/fingerprint/channel signals.** Note thread-continuity's future fix in the ship report (add a queryable `email_thread_id` column).
- **Safe fallback = `TICKET`** (full desk review), NEVER `VISIBLE_HOLD`. `VISIBLE_HOLD` is its own brief (#4677.7), not in BRIEF-B's 6-state CHECK (`DUPLICATE/REJECT_NOISE/REJECT_LOW_RELEVANCE/FAST_TICKET/TICKET/FILE_UNSORTED`) — writing it violates the CHECK. Weak / conflicting / no-match / error all → C's existing (f) TICKET path.
- **Gated by `BOX5_FAST_LANE_ENABLED`** — reuse C's `fast_lane` local (do NOT re-read env). Flag false → branch skipped, C's TICKET default covers everything; E adds nothing live until lead flips the Render flag.
- **Error never auto-clears** (#blocker D3) — E's own resolve/compose/write in a `try/except`; any raise → `conn.rollback()` + `failed += 1` + fall through to (f) TICKET. Never a routed clear, never `soft_ticket++` on error. Distinguish "threw" (`failed`) from "no >=2-signal match" (silent fall-through, no `failed`).
- **Every `except` calls `conn.rollback()`. All DB-touching calls inside try/except.** Every registry read is bounded (resolvers `LIMIT 10`/`LIMIT 200` internally).
- **Terminal write via C's status-guarded helper only** — the routing columns ride inside the SAME guarded UPDATE (extended kwargs), never a second unguarded write.
- **`manifest_match_signals` records the matched signal names + project_number + confidence** — a JSONB list, e.g. `[{"signal":"participant","value":<sender>},{"signal":"alias","project":<pn>}]`, plus `confidence` in its own column. Route through `_json_param()`.

### Verification

New soft-lane branch tests in `tests/test_project_registry.py` (extend the existing 347-line file; live-PG, auto-skips without `TEST_DATABASE_URL`). Seed BB-AUK-001 ACTIVE with a participant `{channel:"email", value:<sender>}` AND an alias (e.g. `"aukera annaberg"`), plus a second registered project for the conflict case. Branch behavior is exercised against C+D's merged `run_tick`. **Register the project with `matter_slug=CANONICAL_SLUG`** — the test harness points `slug_registry` at `tests/fixtures/vault`, where `alpha` is the ONLY canonical slug; `register_project` rejects non-canonical slugs, so do NOT register `matter_slug='aukera'` in the pytest path (`aukera` is canonical only in the prod vault). `desk_owner='baden-baden-desk'` is fine (BB prefix → `DESK_CODES['BB']`, a module constant, fixture-independent + free-text column).

| # | Test | Assert |
|---|------|--------|
| 1 | sender-only → TICKET | arrival from a registered participant sender, NO matter alias in subject/body, flag ON: `resolve_by_participant` hits, `resolve_by_alias` empty → `agree` empty → `terminal_status == 'TICKET'`, `matter_slug`/`manifest_match_signals` NOT populated by soft lane, `soft_ticket == 0` |
| 2 | alias-only → TICKET | arrival carrying the registered alias but from a sender NOT in participants, flag ON: `resolve_by_alias` hits, `resolve_by_participant` empty → `agree` empty → `terminal_status == 'TICKET'`, `soft_ticket == 0` |
| 3 | participant + alias, same project → routed TICKET | arrival from the registered participant sender AND carrying that project's alias, flag ON: `terminal_status == 'TICKET'`, `terminal_reason` startswith `soft_lane_participant+alias`, `matter_slug == CANONICAL_SLUG` (the resolver echoes back the registered slug — `'alpha'` in the fixture vault, `'aukera'` only against a prod DB), `desk_owner == 'baden-baden-desk'`, `manifest_match_signals` JSONB records participant + alias, `confidence == 0.60`, `soft_ticket == 1`, NOT `FAST_TICKET` |
| 4 | 2 candidate projects → TICKET | participant resolves to project A, alias resolves to project B (or the agreement set has >1 element), flag ON: `len(agree) != 1` → `terminal_status == 'TICKET'`, no routing columns set by soft lane, `soft_ticket == 0` |
| 5 | error → TICKET + failed | monkeypatch `write_terminal_status` (or `_claim_for_terminal`) to raise on the matching row: that row's `terminal_status` is NOT a routed clear (TICKET or NULL per fall-through), tick increments `failed` (NOT `deterministic_cleared`/`fast_ticket`/`soft_ticket`), remaining rows still process |
| 6 | hard-lane-already-cleared → soft lane NOT reached | a registered + participant-bound project-NUMBER arrival, flag ON: D's `(e.5)` writes `FAST_TICKET` and `continue`s → E never runs → `terminal_status == 'FAST_TICKET'`, `soft_ticket == 0` (proves precedence: E only runs after D falls through) |
| 7 | flag-off no-op | with `BOX5_FAST_LANE_ENABLED` unset and the participant+alias-same-project arrival: `terminal_status == 'TICKET'` (the branch is skipped), no routing columns set, `soft_ticket == 0` |
| 8 | compile + targeted suite | `python3 -c "import py_compile; py_compile.compile('orchestrator/airport_ticketing_bridge.py', doraise=True); py_compile.compile('kbl/project_registry_store.py', doraise=True)"`; `pytest tests/test_project_registry.py -v`; plus `tests/test_box5_ticketing_runner.py` to prove no regression in C's/D's loop |

## Files Modified

- `orchestrator/airport_ticketing_bridge.py` — extend `write_terminal_status` with four optional routing kwargs (`matter_slug`/`desk_owner`/`manifest_match_signals`/`confidence`, appended to the SET clause only when provided); extend D's registry import with `resolve_by_alias`; insert the soft-lane branch (block e.7) in `run_tick` between D's (e.5) and C's (f); add `soft_ticket` counter init + `"soft_ticket"` stats key.
- `tests/test_project_registry.py` — add cases 1–7 (soft-lane branch, live-PG) + the compile/targeted step (case 8).

## Do NOT Touch

- **D's hard lane** (block (e.5), `FAST_TICKET` write, `extract_project_codes`, the participant-binding gate) — E sits AFTER it and only runs when D falls through; E does not alter D's branch, its conflict gate, or its FAST_TICKET semantics.
- **C's deterministic-clear logic** (block (b) REJECT_NOISE, (e) DUPLICATE) and its **safe-default (f) TICKET** block — E inserts a tier between (e.5) and (f) and falls through to (f); it does not alter the clear paths or (f).
- **`resolve_by_participant` / `resolve_by_alias` internals** — their active-filtering, matching semantics (containment / word-boundary), bounds, and exception→`[]` behavior are #439-locked. E consumes them; E does not re-implement matching or re-filter.
- **The `terminal_status` CHECK constraint** (#441, 6-state) — do not add states, do not migrate. E writes only `TICKET` (already permitted).
- **The live `status` / `check_in_outcome` axes** — E writes only the `terminal_status` axis (via `write_terminal_status`). The candidate/sent/failed `status` axis and the receipt `check_in_outcome` axis are untouched.
- **`VISIBLE_HOLD`** — its own brief (#4677.7); not in the CHECK; never written here.
- **`FAST_TICKET` semantics** — reserved for D's authoritative hard lane. E never writes `FAST_TICKET`; the soft-lane clear is always a routed `TICKET`.
- **No new scheduler / cursor / lease / advisory lock / table / migration.** Reuse C's `_claim_for_terminal` + `write_terminal_status` + `_advance` + watermark machinery.

## Quality Checkpoints

- [ ] Branch off a base with BOTH BRIEF-C and BRIEF-D merged (C's helpers + D's (e.5) block present).
- [ ] With the flag OFF, run `tests/test_box5_ticketing_runner.py` and confirm C's + D's behavior is byte-for-byte unchanged (E is a no-op when `fast_lane` is false).
- [ ] The only soft-lane terminal write is `terminal_status="TICKET"` with all four routing kwargs populated; `grep -c 'FAST_TICKET' ` within E's branch == 0.
- [ ] `grep -c 'VISIBLE_HOLD' orchestrator/airport_ticketing_bridge.py` == 0.
- [ ] `len(agree) == 1` is the sole soft-clear condition; sender-only and alias-only tests both land TICKET.
- [ ] Every `except` in E's block calls `conn.rollback()`; the exception path increments `failed`, never `soft_ticket`.
- [ ] `write_terminal_status` extension is byte-compatible for C's + D's existing callers (they pass no routing kwargs → no routing column written).
- [ ] `manifest_match_signals` routed through `_json_param()`; `confidence` is a 0–1 float.
- [ ] codex G3 verdict obtained; lead `/security-review` G4 passed before merge.
- [ ] Ship report states: (a) participant+alias-only for pilot v1; (b) thread-continuity/fingerprint/channel-ref deferred with the proposed `email_thread_id`-column fix noted; (c) soft clear routes as TICKET (not FAST_TICKET) with `confidence=0.60` placeholder pending calibration; (d) FAST_TICKET-on-soft flagged as a future escalation.

## Verification SQL

```sql
-- After a flag-ON tick over a seeded participant+alias-same-project arrival:
-- a ROUTED TICKET with routing columns populated (NOT FAST_TICKET).
SELECT id, terminal_status, terminal_reason, matter_slug, desk_owner,
       confidence, manifest_match_signals, raw_source_table, raw_source_id
  FROM airport_tickets
 WHERE terminal_reason LIKE 'soft_lane_participant+alias:%'
 ORDER BY terminal_outcome_written_at DESC
 LIMIT 5;
-- Expect terminal_status = 'TICKET'; matter_slug = the registered slug
--   (prod DB seeded via scripts/seed_bb_pilot_registry.py -> 'aukera';
--    pytest fixture-vault -> CANONICAL_SLUG 'alpha' — do not cross them),
-- desk_owner = 'baden-baden-desk', confidence = 0.60,
-- manifest_match_signals = a 2-element JSONB array (participant + alias),
-- raw_source_table = 'email_messages'. NEVER FAST_TICKET on this path.

-- Idempotency: re-running the tick writes no second terminal (status-guard holds).
SELECT id, terminal_outcome_written_at
  FROM airport_tickets
 WHERE terminal_reason LIKE 'soft_lane_participant+alias:%';
-- terminal_outcome_written_at must be UNCHANGED across a second tick.

-- Sender-only / alias-only / conflict never populate soft routing columns:
-- any plain (f) TICKET has NULL matter_slug/desk_owner and the default '[]' signals.
SELECT COUNT(*) AS mislabeled_soft
  FROM airport_tickets
 WHERE terminal_status = 'TICKET'
   AND terminal_reason NOT LIKE 'soft_lane_%'
   AND (matter_slug IS NOT NULL OR desk_owner IS NOT NULL
        OR manifest_match_signals <> '[]'::jsonb)
 LIMIT 1;
-- Expect 0 — only the soft lane populates routing columns on a TICKET.

-- No forbidden state ever written.
SELECT DISTINCT terminal_status FROM airport_tickets WHERE terminal_status IS NOT NULL;
-- Must be a subset of {DUPLICATE, REJECT_NOISE, REJECT_LOW_RELEVANCE, FAST_TICKET, TICKET, FILE_UNSORTED}.
-- VISIBLE_HOLD must NOT appear.

-- Audit row for every soft routed TICKET.
SELECT action_type, target_task_id, success
  FROM baker_actions
 WHERE action_type = 'airport_ticket.terminal_written'
   AND payload::jsonb ->> 'terminal_reason' LIKE 'soft_lane_participant+alias:%'
 ORDER BY created_at DESC LIMIT 5;

-- Confidence never violates NUMERIC(3,2) on any soft-routed row.
SELECT COUNT(*) AS bad_confidence
  FROM airport_tickets
 WHERE confidence IS NOT NULL
   AND (confidence < 0 OR confidence > 1)
 LIMIT 1;
-- Expect 0.
```