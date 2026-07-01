# BRIEF — BOX5_ROUTING_REVERSAL_E_1 (Baker OS V2 · Signal Journey · E lane: alias-routing OUT, explicit-code routing IN)

**Author:** lead (AH1). **dispatched_by:** lead. **Ship report + gate verdicts → lead.**
**Task class:** production feature, behaviour-change to a DARK lane (E runs only when `BOX5_FAST_LANE_ENABLED` is on; prod-off today). **Harness-V2:** full (Context Contract + AC + done rubric + gate plan below).
**Builder:** b3 (fresh). Current E code is embedded verbatim below — no prior Box 5 context required. Keep the SAVEPOINT / terminal_status-orthogonality / `handled`-flag patterns intact.
**Design source (READ FIRST):** `~/baker-vault/_ops/build/baker-os-v2/05_outputs/baker-os-v2-box5-routing-reversal-e-outbound-increment2-spec-codex-arch-20260701.md` §"Deliverable 1". This brief is the authoritative build envelope; the spec is the design rationale.

## Context
Director ruling (2026-07-01, final): name/alias matching is UNSAFE for multi-matter counterparties — "Aukera" spans Annaberg **and** MO Vienna **and** others, so a participant+alias hit cannot tell which project a message belongs to. The **explicit project code** (e.g. `BB-AUK-001`) is the universal router and may be sent to counterparties. Today the merged E soft lane (`BOX5_SOFT_FAST_LANE_1`, commit 13a57ee) routes to a desk when **participant AND alias** agree on one project. **That must stop.** Alias is no longer a routing signal. E becomes an **explicit-code routed-TICKET fallback**: it routes only on a single registered ACTIVE project code that D's hard lane did not already `FAST_TICKET` (code present, sender not participant-bound).

### Surface contract: N/A — pure backend routing logic; no clickable UI surface.

## Estimated time: ~2h · Complexity: Medium · Prerequisites: none

## Diagnose gate (already run by lead — build on these facts)
- E soft lane lives in `run_tick()` block **(e.7)**, `orchestrator/airport_ticketing_bridge.py` ~L1485-1591 (re-pin by grepping `SOFT FAST LANE` — file is volatile).
- It calls `resolve_by_participant("email", sender)` (signal 1) **and** `resolve_by_alias(subject+body)` (signal 2); routes when `agree = p_nums & a_nums` has exactly one project → routed `TICKET`, `soft_lane_participant+alias:<pn>`, confidence 0.60.
- D's hard lane **(e.5)** already handles: exactly-1 distinct code + registered ACTIVE + **sender participant-bound** → `FAST_TICKET`. When binding is absent, D falls through (`handled` stays False) and E runs. That fall-through is exactly where explicit-code routing belongs.
- `resolve_project_number(text) -> Optional[dict]` (`kbl/project_registry_store.py:191`) returns the first **registered ACTIVE** code in text order, else None; dict keys `project_number`, `matter_slug`, `desk_owner`, `clickup_list_id`. Unregistered/retired code → None.
- `extract_project_codes(text) -> list[str]` returns DISTINCT valid-shaped codes (`kbl/project_registry_store.py:243`).
- `write_terminal_status(...)` already accepts `matter_slug=`, `desk_owner=`, `manifest_match_signals=`, `confidence=` (the soft lane uses them today).
- Pilot alias seed: `seed_bb_pilot()` (`kbl/project_registry_store.py:322`) seeds `BB-AUK-001` with `aliases=["annaberg", "aukera annaberg"]`.

## Engineering Craft Gates
- **Diagnose:** applies (done above). Feedback loop = the AC pytest below; symptom = alias routes multi-matter messages; probe = AC1/AC3/AC4.
- **Prototype:** N/A — routing rule is a settled Director ruling + codex-arch spec; no design uncertainty.
- **TDD/verification:** applies — rewrite the E success test FIRST (AC1) as the vertical seam (old participant+alias→routed must become no-route), then add AC2-AC7. Use the existing bridge test harness (`tests/test_box5_ticketing_runner.py`), no implementation-coupled mocks.

## Implementation

### 1. Replace the (e.7) SOFT FAST LANE block with an EXPLICIT-CODE ROUTED lane
Delete the current `# (e.7) SOFT FAST LANE` block (the `if fast_lane and row_id and not handled:` try/except that calls `resolve_by_alias`) and replace it verbatim with:

```python
                        # (e.7) EXPLICIT-CODE ROUTED LANE — routing reversal
                        #   (BOX5_ROUTING_REVERSAL_E_1). Director ruling 2026-07-01:
                        #   name/alias matching is UNSAFE for multi-matter counterparties.
                        #   Alias is NO LONGER a routing signal. E routes ONLY on a single
                        #   registered ACTIVE project code that D's (e.5) hard lane did not
                        #   already FAST_TICKET (code present, sender not participant-bound).
                        #   Exactly 1 active code -> routed TICKET (desk review); 0 / >1 /
                        #   unregistered / retired -> fall through to (f) TICKET.
                        #   resolve_by_alias() is NOT called. Routed TICKET is NOT completion
                        #   and NOT FAST_TICKET (D's authoritative lane).
                        if fast_lane and row_id and not handled:
                            try:
                                with conn.cursor() as _sp:
                                    _sp.execute("SAVEPOINT airport_code_lane")
                                el_text = f"{arrival.subject} {arrival.full_body}"
                                # >1 distinct code = cross-matter CONFLICT -> no E route;
                                # 0 codes -> no code -> no E route. Only exactly-1 proceeds.
                                if len(set(extract_project_codes(el_text))) == 1:
                                    # Regex shape alone NEVER clears: the code must resolve
                                    # to a registered ACTIVE row (None if unregistered/retired).
                                    resolved = resolve_project_number(el_text)
                                    if resolved is not None:
                                        pn = resolved["project_number"]
                                        claim = _claim_for_terminal(conn, row_id)
                                        if claim is None:
                                            lease_skipped += 1
                                            conn.commit()
                                            handled = True
                                        elif claim[1] is not None:
                                            if result.get("ok"):
                                                issued += 1
                                            conn.commit()
                                            handled = True
                                            done = True
                                        else:
                                            claimed += 1
                                            if write_terminal_status(
                                                conn,
                                                ticket_row_id=row_id,
                                                terminal_status="TICKET",  # ROUTED, not FAST_TICKET
                                                terminal_reason=f"explicit_code_routed_ticket:{pn}",
                                                raw_source_id=arrival.message_id,
                                                matter_slug=resolved["matter_slug"],
                                                desk_owner=resolved["desk_owner"],
                                                manifest_match_signals=[
                                                    {"signal": "project_code", "value": pn,
                                                     "binding": "registry_active"}
                                                ],
                                                confidence=0.80,
                                            ):
                                                terminal_written += 1
                                                code_routed_ticket += 1
                                            if result.get("ok"):
                                                issued += 1
                                            conn.commit()
                                            handled = True
                                            done = True
                                # 0 codes / >1 codes / unregistered / retired ->
                                #   handled stays False -> fall through to (f) TICKET.
                                #   No `failed` on a clean no-route.
                            except Exception as exc:
                                # ERROR NEVER AUTO-CLEARS. Roll back to the savepoint (undo
                                # E's partial writes, KEEP issue_ticket's reservation), count
                                # failed, fall through to (f) TICKET so the arrival still ends
                                # at a visible terminal. Never a routed clear.
                                try:
                                    with conn.cursor() as _sp:
                                        _sp.execute("ROLLBACK TO SAVEPOINT airport_code_lane")
                                except Exception:
                                    try:
                                        conn.rollback()
                                    except Exception:
                                        pass
                                failed += 1
                                logger.warning(
                                    "airport_ticketing explicit-code lane row failed: %s", exc
                                )
```

### 2. Rename the counter `soft_ticket` → `code_routed_ticket`
- Init: `run_tick()` ~L1186 `soft_ticket = 0` → `code_routed_ticket = 0` (update the comment to "explicit-code routed TICKET, not FAST_TICKET/defaulted").
- Report dict: ~L1665 `"soft_ticket": soft_ticket,` → `"code_routed_ticket": code_routed_ticket,`.
- `grep -rn "soft_ticket" orchestrator/ tests/` and update EVERY consumer (tests assert this key). Leave no dangling `soft_ticket` reference.

### 3. Remove the now-unused alias resolver import
- E no longer calls `resolve_by_alias`. `grep -rn "resolve_by_alias" orchestrator/` — if E was the only caller, drop the import at `orchestrator/airport_ticketing_bridge.py:24`. Do NOT delete the function from `kbl/project_registry_store.py` (leave it defined; other future callers may exist).

### 4. Retire the pilot aliases in the seed function
- `kbl/project_registry_store.py:322` `seed_bb_pilot()` — change `aliases=["annaberg", "aukera annaberg"]` to `aliases=[]`. Update the docstring line about "'annaberg' stays as a human alias" to note aliases are retired for routing safety (routing reversal 2026-07-01).

## Key Constraints
- D's hard lane (e.5) is UNCHANGED — code+participant remains the ONLY `FAST_TICKET` path.
- Routed `TICKET` here is NOT `FAST_TICKET` and NOT completion — desk review follows.
- Broad aliases must NOT populate `matter_slug`, `desk_owner`, or `manifest_match_signals` any longer.
- SAVEPOINT/rollback contract identical to D's (e.5) — a throw rolls back to the savepoint, KEEPS the `issue_ticket` reservation, counts `failed`, falls through to (f) TICKET. Never a full `conn.rollback()` that strands the arrival.
- Every DB call in try/except; one bad row never stops the batch.
- No `triggers/` change. No new terminal states (reuse existing `TICKET`). No migration (no schema change).

## Verification (pytest, literal — no "by inspection")
Rewrite the current E success test, then add:
- AC1 (replaces old): participant + alias, SAME project, **no code** → **no E route** (no `matter_slug`, no `desk_owner`, `code_routed_ticket` not incremented; lands (f) `safe_default_desk_review`).
- AC2: `BB-AUK-001` present + registered ACTIVE + sender **unbound** → routed `TICKET`, reason `explicit_code_routed_ticket:BB-AUK-001`, matter_slug/desk_owner set, confidence 0.80, NOT `FAST_TICKET`.
- AC3: `BB-AUK-001` + ACTIVE + sender **bound** → D writes `FAST_TICKET`; E not reached (handled by e.5).
- AC4: `annaberg` alias + participant + no code → **no** routed ticket ((f) default).
- AC5: `aukera annaberg` alias + participant + no code → **no** routed ticket.
- AC6: two distinct explicit codes in one row → **no** E route (conflict → (f) TICKET).
- AC7: retired/unregistered code → **no** E route ((f) TICKET).
- Regression: flag OFF (`BOX5_FAST_LANE_ENABLED` unset) → E block not entered; inbound path byte-identical.

## Files Modified
- `orchestrator/airport_ticketing_bridge.py` — replace (e.7) block, rename counter, drop unused import.
- `kbl/project_registry_store.py` — `seed_bb_pilot()` aliases → `[]`.
- `tests/test_box5_ticketing_runner.py` — rewrite E success test + AC2-AC7 + regression.

## Do NOT Touch
- D's (e.5) hard lane, (f) safe-default block, outbound short-circuit, receipt reader.
- `resolve_by_alias()` definition in `kbl/project_registry_store.py` (leave defined; only drop the bridge import).
- Any applied migration. `orchestrator/airport_checkin_reader.py`. `triggers/`.
- The LIVE `project_registry.BB-AUK-001` row aliases — lead clears those as an activation step (Tier-B prod write), NOT in this build.

## Coordination note (parallel build)
`BOX5_OUTBOUND_INGEST_2` (b4) edits the **outbound capture path** of the same file (`airport_ticketing_bridge.py`) — a non-overlapping region (outbound short-circuit / new connector), not the E lane. Branch off current `main`. If b4's PR merges first, rebase (regions do not collide). Flag any real conflict to lead immediately (do not average).

## Gate plan
G1 self-check (`python3 -c "import py_compile; py_compile.compile('orchestrator/airport_ticketing_bridge.py', doraise=True)"` + full AC pytest + `bash scripts/check_singletons.sh`) → codex **G3 on the BUS** (topic `gate/box5-routing-reversal-e-g3`, effort MEDIUM; focus: alias never routes, explicit-code-only routing, conflict/retired/unregistered fall through, D unchanged, savepoint-strand safety, counter rename complete) → lead **G4 `/security-review`** → lead squash-merge. FAIL → findings to b3, rework, re-gate codex.

## Done rubric
Done = alias can no longer route any message; a single registered ACTIVE code routes to its desk as `TICKET` even without participant binding; code+participant still the only `FAST_TICKET`; 0/>1/retired/unregistered codes fall through to (f) TICKET; `soft_ticket` fully renamed with no dangling refs; all AC green; codex G3 PASS; G4 clean. Ship report answers THIS rubric (not "tests pass").

## Branch / hygiene
Branch `box5-routing-reversal-e-1`. Path-scoped commits. Co-author trailer: Claude Opus 4.7 (1M context).
