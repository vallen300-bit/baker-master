# DESIGN — Split quantitative benchmarking from research (tranche-3 item #13)

**Author:** b3 · **Date:** 2026-07-12 · **Source:** `wiki/research/2026-07-12-researcher-capability-extension-brief.md` item 13 · **Assigned:** lead #9422 · **Gate:** design-verify → codex terminal BEFORE build; then own PR → codex build-gate → lead merge.

## 1. Problem / current state

Researcher today handles two different things called "benchmark":

- **Qualitative** — research-type #6 "Practitioner Benchmark" (`research-types.md:125`): *what 3 named peers actually do*. Pure research, within the read-only cage. **Stays with researcher, untouched.**
- **Quantitative** — actually *measuring numbers* (latency, accuracy, throughput, cost, token counts) for systems under test. Researcher has **no clean path** here: running a measurement harness is a build activity, not read-only research. Today it either (a) defers it — `method.md:123` deferral `{class: ceiling-hit, item: "vendor benchmark undone", ...}` — so the numbers never arrive, or (b) risks estimating/fabricating figures. Both degrade report quality.

Item #13 (class **Boundary**, effort **S (process)**) fixes this by drawing the line: **researcher defines the test matrix; a build worker runs the measurements; researcher interprets.**

## 2. The split

| Phase | Owner | Cage posture |
|---|---|---|
| Define the test matrix (what to measure, how) | **Researcher** | read-only / proposal-only — unchanged |
| Run the measurements (execute harness, collect raw numbers) | **Build worker** (b-code) | build authority it already has |
| Interpret + synthesize numbers into the report | **Researcher** | read-only — unchanged |

Nothing about researcher's write-cage / tool-cage / Tier-A posture changes — it still never executes a measurement harness. The build worker already has execution authority; no new authority is minted.

## 3. Key design decision — NO generic executor (proportionate to effort-S)

The item is **S (process)**, not a framework. So: **do not build a generic benchmark-runner service.** Instead, **the test matrix IS the build brief.** Each quantitative benchmark becomes a normal build dispatch to a b-code, with the matrix as its spec. Deliverable = a **protocol + a schema + a method note**, with at most a thin schema-validator. This avoids standing up (and maintaining) an executor no one asked for.

## 4. Handoff contract

**Artifact A — benchmark matrix (researcher emits; proposal-only).** A fenced `benchmark_matrix` block in the research report / method-log, mirroring the existing structured `deferrals` block pattern (`method.md`). Schema:

```benchmark_matrix
id: <slug>
question: <the quantitative question the numbers must answer>
systems_under_test: [<name+version/endpoint>, ...]
tasks_or_datasets: [<task/dataset + source>, ...]
metrics: [<metric + unit + direction better=up|down>, ...]
harness: <how to run: tool/command sketch, deps, inputs, fixtures>
n_runs: <int>            # repetition for variance
environment: <constraints: region, hardware, model tier, rate limits>
result_schema: <expected shape of returned numbers>
interpretation: <what a pass/interesting result looks like; thresholds>
budget: <token/time ceiling for the run>
```

**Dispatch.** Researcher declares `benchmark_handoff: true` (sibling of `continuation_required`) → **lead/deputy** dispatches a build worker with the matrix as the brief (researcher does NOT dispatch — routing rule preserved).

**Artifact B — results (build worker returns).** Raw measurements keyed to the matrix, one row per `system × task × metric`, with `n_runs`, actual environment used, and caveats. Written to `wiki/research/<date>-<id>-benchmark-results.md` and posted back to researcher on the bus. Numbers only + method; **no interpretation** (that's researcher's job).

**Synthesis.** Researcher consumes Artifact B → report synthesis, citing the results artifact + the build worker + the environment (so figures are reproducible and attributable, not asserted).

## 5. Build footprint (what actually ships)

1. **Schema doc** — `benchmark_matrix` + results schema, as a template (candidate home: `wiki/research/_templates/benchmark-matrix.md` or `_ops/agents/researcher/`). Routes via lead/deputy (researcher can't self-edit its harness).
2. **Method note** (proposal) — `research-types.md` / `method.md` addition: "quantitative benchmark → emit `benchmark_matrix` + `benchmark_handoff`, never estimate or silently defer." Routes via lead/deputy.
3. **Optional thin validator** — a small script that lint-checks a `benchmark_matrix` block has all required keys before dispatch. Only if codex judges it worth the S budget; otherwise skip.

No new service, no new daemon, no executor framework, no cage change.

## 6. Open questions for codex / lead

1. Results-artifact home: a `wiki/research/` markdown data file (proposed) vs a structured store (over-build for S)?
2. Schema home: `wiki/research/_templates/` vs `_ops/agents/researcher/` — which does codex-arch prefer for a researcher-owned contract?
3. Thin validator: build it now, or defer until a first real matrix exists?
4. Confirm the "matrix = build brief, no generic executor" call — this is the load-bearing scope decision that keeps #13 at effort-S.
