# BRIEF: BAKER_CORTEX_BUS_HEARTBEAT_1 — Cortex phase-boundary bus heartbeat to brisen-lab

## Context

The Brisen Lab "Cortex" system card stays grey despite Cortex actively running cycles (29 cycles since 2026-04-28; latest 2026-05-15 oskolkov approved). Root cause (deputy-verified bus #440): `static/app.js:464` in brisen-lab derives `state.cortex.last_phase` from bus envelopes where `from === "cortex"` OR `topic.startsWith("cortex/")` — and Cortex never emits any. Cortex's real activity lives in baker-master Postgres (`cortex_cycles`, `cortex_phase_outputs`) which brisen-lab DB cannot see (`bus.py` comment: "Cortex tables — may not exist in brisen-lab DB; soft-fail"). The card was wired to a heartbeat source Cortex never produces.

Fix: emit a bus envelope from `orchestrator/cortex_runner.py` at every phase boundary so brisen-lab's `renderCortexCard()` can show grey→green within 2 min of the next cycle. This is Fix #1 of a two-fix sequence (Fix #2 = card drilldown to tier_b_pending list, separately briefed after #1 ships).

Director ratified plan 2026-05-18 via deputy. Dispatch sequenced: this brief first (Fix #1); cortex-card-drilldown brief after #1 PR merges.

## Estimated time: ~3-4 hours
## Complexity: Low
## Target: b3 (deputy-recommended + lead-cleared; cortex internals fit)
## Target repo: baker-master
## Matter slug: baker-internal
## Trigger class: LOW (no new external surface, no auth/DB schema change, no MCP tool, no Render env flip; emits to existing brisen-lab `/msg/` endpoint with existing `cortex` slug; ≤80 LOC delta expected)

## Prerequisites
- 1Password vault has `BRISEN_LAB_TERMINAL_KEY_cortex` (confirmed by deputy — `bus_post.sh` slug registry includes `cortex`; `bus.py` already has `"cortex": 5` budget cap).
- Baker-master `cortex_runner.py` HEAD on main is at `4dd404c` (verified by AH1-Cowork in this session). Phase-boundary line refs below cite that HEAD.
- Production brisen-lab bus endpoint: `POST https://brisen-lab.onrender.com/msg/` (deprecation check date: 2026-05-18 — no deprecation flagged).

---

## Scope

### Change 1 — Add `_emit_cortex_heartbeat()` helper (new function)

**Where:** new function near top of `orchestrator/cortex_runner.py` (after imports, before `CortexCycle` dataclass at line ~39).

**Signature:**
```python
async def _emit_cortex_heartbeat(
    cycle: "CortexCycle",
    phase: str,
    status: str,
) -> None:
    """Post a phase-boundary heartbeat to brisen-lab bus.

    Best-effort: NEVER raises. Bus-post failure logs at warning and returns.
    The lab is observability, not control plane — phase progression cannot
    block on bus availability.
    """
```

**Body:** POST to `${BRISEN_LAB_URL:-https://brisen-lab.onrender.com}/msg/` with:
- Headers: `X-Terminal-Key: ${BRISEN_LAB_TERMINAL_KEY_CORTEX}` (env var; raise/skip if missing — log warn + return without raising), `Content-Type: application/json`.
- JSON body:
  ```python
  {
    "from_terminal": "cortex",
    "to_terminals": ["lead"],
    "topic": f"cortex/{cycle.matter_slug}/cycle-phase/{phase}",
    "kind": "heartbeat",
    "body": f"cycle_id={cycle.cycle_id} matter={cycle.matter_slug} phase={phase} status={status}",
  }
  ```
- Timeout: 5 seconds (`httpx.AsyncClient(timeout=5.0)` or `aiohttp` equivalent — match whatever HTTP client is already imported in `orchestrator/`; do NOT introduce a new dependency).
- Fault-tolerance (HARD): wrap the full POST in `try/except Exception`. On ANY failure (timeout, 4xx, 5xx, connection error, missing env var) log at `logger.warning` with `extra={"cycle_id": ..., "phase": ..., "error_class": ...}` and return. Phase progression must continue.

**Topic format invariant (verified against `static/app.js:464` derivation):** brisen-lab parses `msg.topic.split("/").pop()` to read the phase name from the topic tail. The topic MUST be exactly `cortex/<matter_slug>/cycle-phase/<phase_name>` — phase_name in {sense, load, reason, propose, archive, failed}. Don't reorder, don't add suffixes.

### Change 2 — Emit at every phase boundary in `run_cycle()`

**Where:** `orchestrator/cortex_runner.py` `run_cycle()` (the async function at line ~140; phase blocks at lines 153, 157, 166, 175, 211 verified against HEAD `4dd404c`).

Insertion points (call AFTER the `cycle.current_phase = "<phase>"` line and the phase function returns successfully):

1. **After `_phase1_sense(cycle)` returns** (line 154 area) — emit `phase="sense", status="ok"`.
2. **After `_phase2_load(cycle)` returns** (line 158 area, after the signal_text plumbing on line 163) — emit `phase="load", status="ok"`.
3. **After `_phase3_reason(cycle)` returns** (line 167 area) — emit `phase="reason", status=cycle.status` (will be `proposed` on success, `failed` on phase3 failure; phase3 catches its own exceptions).
4. **After `_phase4_propose(cycle)` succeeds** (line 178 area, INSIDE the `if await _phase4_propose(cycle):` true branch BEFORE `proposal_card_posted = True`) — emit `phase="propose", status="tier_b_pending"`. (Cycle status is set to `tier_b_pending` inside `_phase4_propose` per the existing comment at line ~169-173.)
5. **After `_phase6_archive(cycle)` returns** (line 213 area) — emit `phase="archive", status=cycle.status`.
6. **In the outer `except Exception` block** (line 193 area, after `cycle.status = "failed"` and `cycle.aborted_reason = ...`) — emit `phase=cycle.current_phase, status="failed"`. This catches whole-cycle failures not handled by inner phase try/excepts.

### Change 3 — Emit ratify-required signal when entering tier_b_pending

**Where:** same insertion point as #4 above (after `_phase4_propose` success).

**Why:** brisen-lab card needs a distinct signal for the `>120s stuck badge` (`app.js:241`) and `state.cortex.open_director_qs` counter (`app.js:470`). Phase-heartbeat alone tells the lab "Cortex is moving"; the ratify-required topic tells the lab "a Director button-press is pending."

**Emit additionally** (after the phase=propose heartbeat):
- Topic: `cortex/{cycle.matter_slug}/ratify-required`
- Body: `f"cycle_id={cycle.cycle_id} matter={cycle.matter_slug} proposal_summary={short_summary[:200]}"` — pull `short_summary` from `cycle.phase3c_result` (whatever 1-line synthesis field already exists; if no 1-line field exists, use the first 200 chars of `str(cycle.phase3c_result)`).

Same fault-tolerance + timeout as Change 1.

---

## Tests to add

Add `tests/test_cortex_bus_heartbeat.py`:

1. `test_emit_cortex_heartbeat_posts_correct_topic` — mock `httpx.AsyncClient.post` (or whichever HTTP client); construct a `CortexCycle` with fixed `cycle_id` + `matter_slug="oskolkov"`; call `_emit_cortex_heartbeat(cycle, "sense", "ok")`; assert POST URL `https://brisen-lab.onrender.com/msg/`, header `X-Terminal-Key` non-empty, JSON body's `topic == "cortex/oskolkov/cycle-phase/sense"` and `from_terminal == "cortex"` and `body` contains `cycle_id=<...> matter=oskolkov phase=sense status=ok`.

2. `test_emit_cortex_heartbeat_swallows_http_errors` — mock the HTTP client to raise `httpx.ConnectError("nope")`; call the helper; assert it returns None without raising; assert `logger.warning` was called with `extra` containing `error_class="ConnectError"`.

3. `test_emit_cortex_heartbeat_swallows_timeout` — mock to raise `asyncio.TimeoutError`; same assertions.

4. `test_emit_cortex_heartbeat_skips_when_key_missing` — `monkeypatch.delenv("BRISEN_LAB_TERMINAL_KEY_CORTEX", raising=False)`; assert helper logs warn + returns; HTTP client NEVER called.

5. `test_run_cycle_emits_all_five_phase_heartbeats_on_happy_path` — mock all `_phaseN_*` to return success; mock `_emit_cortex_heartbeat` to record calls; run `run_cycle(matter_slug="oskolkov", triggered_by="test", trigger_signal_id=None)`; assert exactly 5 heartbeat calls in order: sense, load, reason, propose, archive. Plus 1 `ratify-required` topic.

6. `test_run_cycle_emits_failed_heartbeat_on_outer_exception` — mock `_phase2_load` to raise `RuntimeError("boom")`; assert heartbeats: sense (ok), then failed (with `current_phase="load"`).

7. `test_run_cycle_continues_when_heartbeat_raises` — mock `_emit_cortex_heartbeat` to raise (simulating a leak past its own try/except, e.g. bug in the helper). The cycle MUST still complete all phases. This is the load-bearing fault-tolerance invariant — the helper has its own try/except but the cycle's call sites also need to not assume the helper is safe. Wrap each call site in its own `try/except Exception` that logs + continues. (This is belt-and-suspenders against future regression.)

**Target test count delta:** +7 tests. All `pytest -q tests/test_cortex_bus_heartbeat.py` green.

**Existing test suite:** `pytest` must remain green. No cortex_runner.py test regressions expected — phase boundary semantics unchanged, only adds best-effort emit calls.

---

## Standards checklist (deputy-mandated)

- [x] Exact endpoint cited: `POST https://brisen-lab.onrender.com/msg/`
- [x] Deprecation check date: 2026-05-18 (no deprecation flagged)
- [x] Fallback: bus-post fail → log + continue cycle (NEVER block phase progression)
- [x] file:line citations verified against HEAD `4dd404c`: cortex_runner.py:154, 157, 166, 175, 178, 211; app.js:464, 470, 241, 667 (verified by deputy bus #440)
- [x] Singleton pattern: N/A (no new global state)
- [x] Migration-vs-bootstrap: N/A (no DDL)
- [x] Invocation-path audit: N/A (not a capability_set row mutation)
- [x] Auth: env var `BRISEN_LAB_TERMINAL_KEY_CORTEX` — slug already registered in `bus.py` budget cap; 1P key already provisioned

---

## Ship gate

1. `pytest` green (full suite).
2. `pytest -q tests/test_cortex_bus_heartbeat.py` green (the 7 new tests).
3. Compile-clean check: `python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_runner.py', doraise=True)"`.
4. PR opened against baker-master `main` with branch `b3/cortex-bus-heartbeat-1`.
5. **Bus-post on PR open:** `BAKER_ROLE=b3 ~/Desktop/baker-code/scripts/bus_post.sh deputy "<PR URL> + <head_sha>" dispatch/cortex-card-fixes/ship-1` — this routes back to deputy (the dispatcher), per deputy #440 explicit routing.
6. Manual smoke (post-merge, AH1-Cowork owns): fire a small oskolkov cycle (e.g. low-cost test signal); watch brisen-lab UI; Cortex card transitions grey → green within 2 min.

## Gate chain (LOW trigger class)

- gate_1_ah2_static: REQUIRED
- gate_2_security_review: REQUIRED
- gate_3_picker_architect: NOT_REQUIRED (LOW)
- gate_4_2nd_pass_code_reviewer: NOT_REQUIRED (LOW)

Tier-A merge authority on green gates per standing AH1 charter §3.

## Branch + commit identity

- Branch: `b3/cortex-bus-heartbeat-1`
- Commit identity: `Code Brisen #3 <b3@brisengroup.com>`
- No `--no-verify`.

Open this brief and go.
