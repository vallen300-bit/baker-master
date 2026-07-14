# BRIEF: BUS_INTENT_TYPES_1 — Command/Event intent enum on the typed envelope (additive; generalizes execute-obligation; ARM unacked-SLO predicate; releases deputy-codex charter HOLD #10422)

> Bus-hardening **intent-types arc** (fresh arc, on the revamp critical path — lead #10605/#10622). EXTENDS
> the Case One P3 typed envelope + P4 intent-granular alerting; does **not** draft a net-new envelope.
> Authored by deputy (AH2, standing bus-health owner). **TO codex-arch for G0 → lead PASS → build.**
> Binding folds: plan v3 zero-silent-loss invariant (#10397) + ARM charter v1.1a F4 SLO scope (#10422).

dispatched_by: lead (#10622/#10625 — intent-types SPEC, extend-not-redraft ruling)
assigned_to: <builder — lead assigns after codex-arch G0 + lead PASS>
task_class: backend-contract (brisen-lab `bus.py` derive+store `intent` at POST; `db.py` additive column + backfill migration; ARM/P4 SLO predicate reads `intent`) + fleet-client read-surface (readers/dashboards can filter on `intent`; **no client is required to supply it**)
Harness-V2: Context Contract + done rubric + gate plan inline.
effort: medium

## Context

**Context Contract.** Repo: brisen-lab (`bus.py` POST path — derive `intent` from `kind`, server-side, and stamp it on the authoritative row exactly as `execute_obligation` is derived today; `db.py` + migration — additive `intent` column + one-shot backfill). Consumers: ARM's unacked-SLO alarm predicate + the P4 delivery-health surface read `intent`. **No new service, no new envelope, no new kind.** The `intent` field is a coarse semantic label that sits *above* the existing `kind` enum and is derived from it — the same derive-and-store pattern P3 already uses for `execute_obligation` (`bus.py:1939`).

**Why now (critical path).** deputy-codex's ARM-custodian charter is on **HOLD #10422** until the bus has a first-class **command** class carrying an **unacked-SLO**. ARM v1.1a F4 restricts SLO-alarm scope to "root execute-obligation / P5 delivery records" and requires a "machine-readable dispatch state" to key on. Today that predicate is spelled two different ways in code (`_is_delivery_tracked` = `kind=='dispatch' AND execute_obligation`; `_is_assignment` = `kind=='dispatch' AND parent_id is None`) with no single first-class label ARM can name. This brief gives the fleet that label — `intent ∈ {command, event}` — so ARM's charter predicate has one canonical, queryable field to alarm on, releasing HOLD #10422.

### SCOPE DEDUPE (MANDATORY — lead #9563 discipline). Already shipped / owned elsewhere; this brief must NOT re-cover, re-define, or double-gate:
- **P3 typed envelope + `VALID_KINDS` + `EXECUTE_OBLIGATION_KINDS` + server-derived `execute_obligation`** — UNTOUCHED. `intent` is derived FROM `EXECUTE_OBLIGATION_KINDS`; it does not redefine kinds or the obligation field. **R1: `VALID_KINDS` is unchanged.**
- **P4.2 dispatch-warning (`_is_assignment`, `bus.py:126`)** — UNTOUCHED and NOT double-gated. The alarm-fatigue guard stays keyed on `_is_assignment` (root dispatch). `command` is the semantic superset that `assignment` is a strict subset of; this brief adds **no second warning** and changes **no existing alert's firing condition**. See "Reconciliation" below — this is the load-bearing constraint from lead #10622.
- **P5 delivery state machine (`_is_delivery_tracked`, `bus.py:88`)** — UNTOUCHED. The SLO refinement (which command rows the unacked-SLO fires on) continues to REUSE `_is_delivery_tracked`; `intent` labels the row, it does not re-scope what P5 tracks.
- **P4.3 traceparent / delivery-receipts / dead-letter** — UNTOUCHED. Those are the transport of the zero-silent-loss guarantee; this brief only marks WHICH messages that guarantee is asserted on (commands), it does not re-implement receipts.

## Problem

The typed envelope classifies messages by `kind` (`dispatch/ack/broadcast/ratify_required/ratify_decision/alert`) and derives a boolean `execute_obligation`. That is enough for the P4/P5 gates but leaves three gaps for the reliability/ARM layer:

1. **No first-class Command vs Event distinction.** The single deepest reliability question — "is this message an *instruction someone must act on and that must not be silently lost* (Command), or a *notification that something happened, fire-and-forget* (Event)?" — is not a field. It is inferable (`kind ∈ {dispatch, ratify_required}` ≈ command) but not *named*, so every consumer re-derives it ad hoc. ARM cannot name a predicate that does not exist.

2. **The zero-silent-loss invariant has no scope marker.** Plan v3 (#10397) / Baker OS V2's main objective is **"no signal disappears silently."** That guarantee is meaningful for **commands** (a lost dispatch is a lost order — E20 tonight) but *not* for events (a lost `bus_busy_retry` broadcast is noise — suppressing it is correct, P4.2). Without an `intent` label, "apply zero-silent-loss here" and "this is droppable noise" are the same untyped row — so the guarantee is applied by scattered heuristics, not by one classification. ARM v1.1a F4 needs exactly this scope marker to avoid alarm fatigue.

3. **deputy-codex ARM charter blocked (HOLD #10422).** The custodian charter cannot arm its unacked-SLO until a `command` class with an SLO exists to arm on. This is a hard prerequisite gate, not a nice-to-have.

## Fix (one field, three uses, zero behavior change to existing gates)

### 1 — `intent` derived + stamped server-side at POST (mirrors `execute_obligation`)
Add a single typed field `intent ∈ {command, event}`, derived **server-side** from `kind` at POST and stamped on the authoritative row — exactly the pattern P3 uses for `execute_obligation` (`bus.py:1939`), so identity is server-derived and unforgeable (P3.4 property preserved):

```
intent = "command" if kind in EXECUTE_OBLIGATION_KINDS else "event"
#   command: {dispatch, ratify_required}   (act-on-receipt, must-not-be-silently-lost)
#   event:   {ack, broadcast, ratify_decision, alert}   (notification, fire-and-forget)
```

Server derives and stamps; a client-supplied `intent` is **ignored/overridden** (never trusted), same as `execute_obligation`. No client change is required — this is what "migration must be additive; intent defaults derived from kind" (#10622) means, implemented literally.

**Reply-case: RULED (lead #10665) — a threaded reply stays `intent=command`.** A reply is `kind=dispatch` with `parent_id` set, so the `kind`-only derivation labels it `command`, and P5 continues to delivery-track it. This is **intended, not an edge to special-case:** reply payloads carry the fleet's obligation-bearing traffic (verdicts, rulings, ship confirms), and the entire tonight incident class is *missed replies* — pulling replies off the unacked-SLO lane would blind the SLO to exactly what this arc fixes. Fatigue is already guarded because `_is_assignment` excludes replies from the dispatch-warning. So the derivation stays pure `kind`-only (no `parent_id` branch); replies are `command` + delivery-tracked + carry NO dispatch-warning. A regression asserts this triple.

### 2 — ARM unacked-SLO keys on the UNCHANGED P5 predicate; `intent==command` is the queryable charter LABEL (NO new gate)
**Ratified Option A (#10888):** the ARM unacked-SLO alarm (the charter predicate that releases HOLD #10422) fires on the **unchanged P5 predicate** — `intent` adds **no firing term**:

```
_is_delivery_tracked(kind, execute_obligation)  AND  unacked_past_SLA
    i.e.  kind == "dispatch"  AND  execute_obligation == TRUE  AND  unacked_past_SLA
```

`_is_delivery_tracked` is **reused verbatim** (`bus.py`) — it already resolves to the root worker-start dispatch and already **excludes** `ratify_required` (a Director-gated decision path, not a worker-start dispatch — the existing P5 comment). So:
- `intent==command` is the **stored/queryable charter LABEL** ARM's charter *names* (satisfies v1.1a F4 "machine-readable dispatch state" + releases #10422) — a label on the row, **not a conjunct in the firing predicate**. `_derive_intent` adds no firing condition (shipped `bus.py` @e488f9d comment: "intent is a label, not a gate").
- `_is_delivery_tracked` is the **actual SLO predicate** — the set of commands carrying the *worker* unacked-SLO — unchanged, so P5's scope does not move.
- The nesting `_is_delivery_tracked ⊂ intent==command` holds by construction (a delivery-tracked dispatch is always a command), so the label correctly *describes* every SLO-tracked row without gating it.
- `ratify_required` is correctly a *command* (obligation-bearing) but rides the Director-gated ratify lane, NOT the worker unacked-SLO — the label and the SLO predicate being separate is exactly what keeps this clean.

This adds **no new firing condition** and **no second warning** — the ARM SLO keys on the predicate P5 already computes; `intent` gives ARM's charter one queryable field to *name*, not a new gate to fire on.

### 3 — `intent` as an observability/filter dimension (P4 dashboard + readers)
The P4 delivery-health surface and read helpers can filter/group by `intent` (command-lane delivery latency, event-lane volume) — a queryable dimension, not a new metric. Purely additive read-side.

## Reconciliation (the load-bearing constraint — lead #10622: "reconcile, don't double-gate")

Three predicates now form a strict nesting, each owning ONE job — no overlap, no double-gate:

| Predicate | Field/fn | Owns | Fires |
|---|---|---|---|
| `intent==command` | NEW derived label | *semantic class* + ARM charter marker | nothing on its own — a label |
| `_is_delivery_tracked` | P5, unchanged | *delivery state machine + worker unacked-SLO* | re-wake / escalate / ARM SLO |
| `_is_assignment` | P4.2, unchanged | *dispatch-WARNING (alarm fatigue)* | the one dispatch-warning |

`assignment ⊂ delivery-tracked ⊂ command`. Each existing gate keeps its exact current firing condition; `intent` is the umbrella label, not a parallel gate. A message is warned-on by AT MOST one predicate (`_is_assignment`), tracked by exactly the P5 set, and labeled `command`/`event` for ARM + observability. **No message can be double-warned or double-escalated by this change** (a required test, below).

## Files Modified

- brisen-lab `db.py` + migration: additive `ALTER TABLE bus_messages ADD COLUMN intent TEXT` (nullable, no default constraint that rewrites history) + one-shot backfill `UPDATE ... SET intent = CASE WHEN kind IN ('dispatch','ratify_required') THEN 'command' ELSE 'event' END WHERE intent IS NULL`. Additive-only per repo migration rules — new migration file, never an edit to an applied one.
- brisen-lab `bus.py`: derive `intent` at POST next to the existing `execute_obligation = kind in EXECUTE_OBLIGATION_KINDS` line (~`:1939`) and include it in the INSERT column list + the row-serialization dict (`:136` area); a `_derive_intent(kind)` helper co-located with `EXECUTE_OBLIGATION_KINDS`. ARM/P4 SLO predicate is the **unchanged P5** `_is_delivery_tracked(...)`; `intent` is stored as a queryable label ARM's charter names, **not** a firing conjunct (ratified Option A #10888). **Do NOT touch** `VALID_KINDS`, `EXECUTE_OBLIGATION_KINDS`, `_is_delivery_tracked`, `_is_assignment`.
- Read surface: serialize `intent` in the message dict so readers/dashboard can filter; `intent` NOT required on any POST (server derives).
- Tests (brisen-lab): (a) derivation table — each of the 6 kinds maps to the correct intent; (b) server ignores/overrides a client-supplied `intent` mismatching the kind; (c) backfill sets every legacy row; (d) **no-double-gate** — a root dispatch trips `_is_assignment` exactly once and is labeled `command`; a `ratify_required` is `command` but is NOT delivery-tracked and does NOT trip the worker unacked-SLO; an `ack`/`broadcast`/`alert` is `event` and trips nothing; (e) ARM SLO predicate fires on an unacked past-SLA root command and does NOT fire on any event; **(f) reply-case regression (lead #10665) — a threaded reply (`kind=dispatch`, `parent_id` set) is labeled `intent=command` AND is `_is_delivery_tracked` AND does NOT trip the dispatch-warning (`_is_assignment` false). Assert all three in one test.**

## Verification

1. **Derivation (server-side, unforgeable):** POST each of the 6 kinds → `intent` stamped correctly; a POST with a client `intent` contradicting its kind → server value wins, client value discarded. No garbage/forged intent enters storage.
2. **Additive migration:** legacy rows all carry `intent` post-backfill; a pre-migration reader (no `intent` awareness) still functions (column is ignored, not required); existing kinds/dispatch/ack flows byte-unchanged.
3. **No-double-gate (the load-bearing test):** replay tonight's E20 crossed-gate scenario + a normal dispatch + a reply + an ack + a broadcast → exactly the SAME warnings/escalations fire as on pre-change main (assert `_is_assignment` and `_is_delivery_tracked` outputs are identical before/after); the ONLY new observable is the `intent` label on each row.
4. **ARM charter predicate:** an unacked-past-SLA root command surfaces to ARM's SLO predicate — the **unchanged P5 predicate** `_is_delivery_tracked(kind, execute_obligation) AND unacked_past_SLA` (`kind='dispatch' AND execute_obligation=TRUE`); `intent==command` is the stored/queryable charter LABEL on the row, **not a firing conjunct** (ratified Option A #10888, matching shipped `bus.py` @e488f9d). An event never trips the SLO; a `ratify_required` (command, not delivery-tracked) does not trip the *worker* SLO. Confirm deputy-codex can now arm its charter by naming `intent==command` (HOLD #10422 predicate satisfied).
5. **Live AC:** post-deploy fleet drill — post a real command + a real event across seats; the delivery-health surface shows the command on the command-lane with the zero-silent-loss guarantee asserted, the event fire-and-forget; force an unacked command past SLA → ARM alarms; force a lost event → no alarm (correctly droppable). Emit `POST_DEPLOY_AC_VERDICT v1`. Deputy (bus-health owner) folds the command-lane SLO into the dispatcher sweep + confirms HOLD #10422 releases.

## Quality Checkpoints / Acceptance criteria

- **done rubric:** (1) `intent ∈ {command,event}` derived server-side from `kind` and stamped on the row (client value never trusted); (2) additive migration + backfill, existing kinds/gates byte-unchanged, `VALID_KINDS`/`EXECUTE_OBLIGATION_KINDS`/`_is_delivery_tracked`/`_is_assignment` untouched; (3) ARM unacked-SLO predicate is the unchanged P5 `_is_delivery_tracked` (`intent==command` is a stored/queryable label ARM names, **not** a firing conjunct — ratified Option A #10888) — no new gate, no double-warning (proven by test 3); (4) reply-case RULED (replies = `command` + delivery-tracked + no dispatch-warning, per lead #10665) with regression test (f) asserting the triple; (5) `intent` queryable on the P4 read surface; (6) live drill AC + `POST_DEPLOY_AC_VERDICT v1` + HOLD #10422 release confirmed.
- **done-state class:** production contract correctness → live fleet drill AC required (compile-clean ≠ done — Lesson #8).
- **gate plan:** deputy authors → **codex-arch G0** (cross-vendor architecture review — codex seats lifted #9711-over 2026-07-13) → **lead PASS** → lead assigns builder → builder implements → independent gate (codex correctness) + non-author test-run → lead merges → deploy → deputy verifies live as bus-health owner + confirms HOLD #10422 release.
- **Harness-V2:** covered inline (Context Contract + done rubric + gate plan + task class).

## Dedupe / cross-links

- **Extends** Case One P3 (typed envelope + `execute_obligation` derive-pattern — `intent` reuses it exactly) + P4.2 (`_is_assignment` warning — untouched, superset-labeled) + P5 (`_is_delivery_tracked` — reused verbatim as the SLO refinement). Redefines/redoes none of them.
- **Unblocks** deputy-codex ARM-custodian charter HOLD #10422 (v1.1a F4 needs the `command` label + unacked-SLO to arm).
- **Realizes** plan v3 zero-silent-loss invariant (#10397 / Baker OS V2 main objective) as a *typed scope marker*: the guarantee is asserted on `intent==command`, droppable on `intent==event` — so "protect this" and "this is noise" are finally different fields, not scattered heuristics.
- **Reconciliation is the acceptance bar** (lead #10622): the Command/Event enum must reconcile with P4.2's `kind=assignment` warning, NOT double-gate it — enforced structurally by the strict `assignment ⊂ delivery-tracked ⊂ command` nesting + test 3.
- Evidence: current-main `bus.py` (`VALID_KINDS:69`, `EXECUTE_OBLIGATION_KINDS:79`, `_is_delivery_tracked:88`, `_is_assignment:126`, derive-pattern `:1939`) @ origin/main `ca5e9d8`; P3 brief `BRIEF_CASE_ONE_P3_CONTRACT_IDENTITY_1.md`; P4 brief `BRIEF_CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1.md`; ARM amendment `_ops/build/baker-os-v2/05_outputs/domain-agent-program/DRAFT_SPEC_ARM_BUS_CUSTODIAN_AMENDMENT_V1.md` §v1.1a F4; lead dispatch #10622/#10625 + night-orders #10605.
