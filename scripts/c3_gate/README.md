# C3 pilot-widening gate — run harness (rows R1-R4)

Repeatable, evidence-producing runners for the first four rows of the C3 gate
matrix (`_ops/build/baker-os-v2/05_outputs/c3-widening-gate-matrix.md`). Built by
b3 for lead (dispatch #5915; rulings #5930). **Live evidence runs stay gated on
lead's go + C2 landing** — this harness prepares and dry-validates them.

## Files
- `c3_lib.py` — shared: DB conn, table bootstrap, synthetic injection, registry
  seed, I/O stubs, evidence collectors, run-log, cleanup, the `--dry/--run`
  scaffold.
- `r1_fast_lane.py` — R1: fast lane with real participants (D-39a).
- `r2_coded_reply_dedup.py` — R2: coded reply routes E2E (D-39d).
- `r3_receipt_writeback.py` — R3: receipts write back (evidence = receipt row +
  ClickUp close + bus RECEIPT proof, per #5930 Q1a).
- `r4_nudge_stop_on_landing.py` — R4: nudges stop on landing (D-39b/c).
- `_runs/` — JSONL evidence logs (created on `--run`; git-ignored artifact).

## Modes
```
python3 scripts/c3_gate/r1_fast_lane.py            # --dry (default): spec + expected evidence, no DB
C3_HARNESS_LIVE=1 python3 scripts/c3_gate/r1_fast_lane.py --run    # execute against env DB
```
- **`--dry`** touches no DB and imports nothing heavy — safe anywhere, and is the
  authoritative description of each run + the evidence it emits.
- **`--run`** is guarded (`C3_HARNESS_LIVE=1`). It executes against the DB in the
  environment and writes a JSONL evidence record to `_runs/`.
- Run these **from the repo root** exactly as written. `c3_lib.py` inserts the repo
  root on `sys.path` (mirroring `scripts/regen_hot_md.py`) so a `--run` resolves
  `memory.*` / `orchestrator.*` / `kbl.*` without an editable install (F3, codex #6158).

## Target DB (lead #5930 Q2 — BOTH, sequenced)
- **Dev / validation:** `TEST_DATABASE_URL` → ephemeral Neon branch (the existing
  CI pattern). Registry is seeded with a synthetic participant.
- **T2 evidence:** live DB via `DATABASE_URL`. Synthetic rows are MARKED
  (`c3-gate-` prefix / `airport-lounge:c3-gate-` for journeys), cleanup runs and
  is logged. On live, R1/R2 use the REAL registered pilot participant. The gate
  certifies the LIVE pipeline — a lab copy doesn't count.

## External I/O
Stubbed by default (ClickUp + bus) so runs are deterministic and side-effect-free.
Set `C3_HARNESS_REAL_IO=1` for a true-live T2 run under lead's ClickUp policy.

## Injection entry surface
Direct `INSERT` into `email_messages` (`source=graph`) — ratified by lead (#5930
Q3) and confirmed conflict-free by both C2-lane owners (b2 #5935, b4 #5937):
`email_messages` is the real Box-5 entry surface, no pre-bridge stage today. If a
future C2 slice adds an upstream ingest/normalize stage, the runners follow it.

## Evidence per row (what codex verifies)
| Row | Run | Evidence pointer |
|---|---|---|
| R1 | fast-lane participant (2 cases) | both ticket ids + `terminal_status`/`terminal_reason` — A=FAST_TICKET, B=TICKET |
| R2 | coded reply on open thread + replay | per-msg `terminal_reason`+`dedup_key`, thread ticket count, replay `terminal_written`=0 |
| R3 | LANDED→receipt writer | receipt row id + `event_state`=RECEIPT_WRITTEN + `correlation` (receipt_written/bus id) |
| R4 | nudge ladder pre/post landing | `baker_actions` nudge window — ≥1 before landing, 0 after |

## Open C2-dependency (flagged to lead)
R2's precise "no duplicate ticket" threshold is refined by b4's C2 routing/dedup
slice. The runner EMITS the full dedup evidence now; its PASS bar is the
conservative spine invariant (same-desk thread continuity + idempotent replay).
Re-pin the bar when C2 lands.
