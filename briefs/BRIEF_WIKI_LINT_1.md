# BRIEF: WIKI_LINT_1 — Karpathy-style weekly wiki health check

**Milestone:** M1 (Wiki stream foundation)
**Roadmap source:** `_ops/processes/cortex3t-roadmap.md` §M1 (RA scope spec ratified per spec at `_ops/ideas/2026-04-26-wiki-lint-1-spec.md`)
**Estimated time:** ~6–8h
**Complexity:** Medium-High (7 checks, two LLM-assisted, scheduler integration, Slack notification)
**Prerequisites:** M0 KBL_SCHEMA_1 (PR #52), KBL_INGEST_ENDPOINT_1 (PR #55), AI_HEAD_WEEKLY_AUDIT scheduler pattern (PR #44 / `triggers/embedded_scheduler.py`)

---

## Context

RA delivered concrete-checks spec at `_ops/ideas/2026-04-26-wiki-lint-1-spec.md` — 7 checks (4 deterministic, 2 LLM-assisted with Haiku 4.5, 1 hybrid filesystem+Postgres). AI Head A critique M1.5 had blocked dispatch on "Karpathy-style audit" being a vibe; this spec hardens it.

Two wiki patterns coexist (per spec §"Two coexisting wiki patterns"):
- **Flat:** `wiki/<slug>/` with timestamped `.md` files + `_links.md`.
- **Nested:** `wiki/matters/<slug>/` with `_index.md`, `_overview.md`, `gold.md`, etc.

Both must pass lint. Per-matter pattern detection.

**RA recommendations adopted as decisions** (spec §"Open questions for AI Head /write-brief"):
- Q1 LLM choice: **Haiku 4.5** (consistency with stack; `kbl/retry.py:105` already references `claude-haiku-4-5`).
- Q2 Action checkboxes in report: **V1 = no, manual.** V2 brief later if Director wants auto-fix follow-up sentinel.
- Q3 Threshold defaults: 60d stale, 14d inbox, 90d orphan. Adjustable via env vars.

---

## Problem

Wiki accretes drift over time: retired slugs leak into new files, matter dirs orphan after counterparty goes quiet, cross-refs go one-way, gold drifts from current reality. M3 Cortex cycles will read this drifted wiki and hallucinate or misroute. Lint surfaces drift weekly so Director can prune before Cortex consumes it.

## Solution

Build a single-entrypoint lint runner `kbl/wiki_lint.py` that:
1. Walks `BAKER_VAULT_PATH/wiki/` (NOT `_ops/`, `_ledger/`, `lint/`).
2. Detects per-matter pattern (flat vs nested).
3. Runs 7 checks; each returns `LintHit(check, severity, path, line, message)`.
4. Aggregates into a markdown report (V1 location: `outputs/lint/YYYY-MM-DD.md` in baker-master + Slack summary post — see "Output path V1/V2 carve-out" below).
5. Schedules weekly via APScheduler in `triggers/embedded_scheduler.py`, mirroring the `_ai_head_weekly_audit_job` pattern (Mon 05:00 UTC per spec).

### Output path V1/V2 carve-out (architectural decision, log in PR description)

Spec §"Output" says `baker-vault/lint/YYYY-MM-DD.md`. CHANDA #9 prohibits Baker writing to `baker-vault/` directly. Two paths:
- **V1 (this brief):** Write to `outputs/lint/YYYY-MM-DD.md` in baker-master + Slack-post summary. Local-only artefact, queryable from Render filesystem.
- **V2 (separate brief, post-V1 stable):** Mirror to `baker-vault/lint/YYYY-MM-DD.md` via Mac Mini SSH-mirror from `vault_scaffolding/live_mirror/v1/lint/`. Requires Mac Mini script extension to pick up `lint/` subpath.

V1 ships first to validate check correctness without committing to the mirror plumbing.

### LLM helper addition

`kbl/anthropic_client.py` currently has `call_opus()` only (default `claude-opus-4-7`). Checks 5 + 6 need Haiku 4.5. Add:
- `call_haiku(prompt, system=None, max_tokens=1024) -> HaikuResponse` — mirror `call_opus()` signature.
- Default model: `claude-haiku-4-5`. Env override: `CLAUDE_HAIKU_MODEL`.
- Cost telemetry via existing `_compute_cost_usd` (cost map in `kbl/cost.py:43` already has `claude-haiku-4` row).

### 7 checks (per spec §"7 checks")

Implementation file structure:
```
kbl/wiki_lint.py                # entrypoint + dispatcher
kbl/lint_checks/
  __init__.py
  retired_slug_reference.py     # check 1
  missing_required_files.py     # check 2
  orphan_matter_dir.py          # check 3
  one_way_cross_ref.py          # check 4
  stale_active_matter.py        # check 5 (Haiku)
  contradiction_within_matter.py # check 6 (Haiku)
  inbox_overdue.py              # check 7
  _common.py                    # LintHit dataclass, severity enum, pattern detector
```

Each check is a pure function `run(vault_path: Path, registries: dict) -> list[LintHit]`. No I/O outside the supplied path. Tests use fixture vault at `tests/fixtures/wiki_lint/`.

### Severity gating

- **error** count > 0 → Slack post tagged `🔴 wiki lint errors` + report file.
- **warn** only → Slack post tagged `🟡 wiki lint warnings`.
- **info** only → Slack post tagged `ℹ️ wiki lint clean (info only)`.

Posts to Slack `sb-inbox` channel (per Baker convention — verify channel name in existing Slack posts before hard-coding; if drift, env var).

### Hagenauer-first acceptance test (spec §"Hagenauer-first acceptance test")

Lint must run cleanly against today's tree:
- 0 errors expected.
- Warnings expected: check 2 may flag `wiki/hagenauer-rg7/` missing `_links.md` under grandfather clause (warn, not error — flat-pattern + pre-2026-04-23 dir).
- After B1 (HAGENAUER_WIKI_BOOTSTRAP_1) ships, lint must also accept the new nested `wiki/matters/hagenauer-rg7/` shape with no errors on checks 1+2.

PR ship gate: pytest passes + dry-run on real `BAKER_VAULT_PATH` produces 0 errors.

---

## Files to modify

**Create:**
- `kbl/wiki_lint.py`
- `kbl/lint_checks/__init__.py`
- `kbl/lint_checks/_common.py`
- `kbl/lint_checks/retired_slug_reference.py`
- `kbl/lint_checks/missing_required_files.py`
- `kbl/lint_checks/orphan_matter_dir.py`
- `kbl/lint_checks/one_way_cross_ref.py`
- `kbl/lint_checks/stale_active_matter.py`
- `kbl/lint_checks/contradiction_within_matter.py`
- `kbl/lint_checks/inbox_overdue.py`
- `tests/test_wiki_lint.py` (entrypoint + dispatcher)
- `tests/test_lint_check_<each>.py` (one per check, 7 files)
- `tests/fixtures/wiki_lint/` (fixture vault tree mirroring flat + nested patterns)
- `outputs/lint/.gitkeep` (output dir placeholder)

**Modify:**
- `kbl/anthropic_client.py` — add `call_haiku()` mirroring `call_opus()`. Do NOT change `_DEFAULT_MODEL`.
- `triggers/embedded_scheduler.py` — register `_wiki_lint_weekly_job` (Mon 05:00 UTC) behind env flag `WIKI_LINT_ENABLED` (default `false` for first ship; flip to `true` once dry-run is clean).

## Files NOT to touch

- `kbl/ingest_endpoint.py` (out of scope; lint reads, doesn't ingest).
- `kbl/slug_registry.py` (read-only consumer for retired slugs).
- `baker-vault/` directly (CHANDA #9; V2 brief handles vault mirror).
- `kbl/cost.py` cost map (already has Haiku row; no changes needed).
- `_DEFAULT_MODEL` in `anthropic_client.py` — Haiku is an additive helper, not a default flip.

## Risks

- **DDL drift:** None — no Postgres writes. Lint reads `email_messages.primary_matter`, `meeting_transcripts.primary_matter`, `whatsapp_messages.primary_matter` (verify columns exist before brief execution; LONGTERM.md DDL drift rule). Grep verification: `grep -E "INSERT|UPDATE|DELETE|CREATE TABLE|ALTER" kbl/wiki_lint.py kbl/lint_checks/` returns 0 lines.
- **Haiku cost runaway:** Spec estimates ~$0.40/run. Add hard ceiling: if total Haiku tokens > 100K in a run, abort + Slack alert. Cost telemetry via existing `kbl/cost.py` path.
- **LLM determinism:** Checks 5+6 are non-deterministic. Tests use a Haiku stub returning fixed responses. Real-vault dry-run verified manually before flag flip.
- **CHANDA #9 ambiguity:** V1 carve-out documented above. PR description must surface the V2 question for Director ratification before V2 brief is drafted.
- **Slack channel hard-coding:** Verify `sb-inbox` is the right channel before hard-coding. Use env var `WIKI_LINT_SLACK_CHANNEL` with default fallback.
- **BAKER_VAULT_PATH absent on Render:** If env var unset, lint job logs warning + skips run (does NOT crash scheduler — `_ai_head_weekly_audit_job` pattern handles this gracefully; mirror the pattern).
- **Pattern detector false-positives:** A matter dir at `wiki/<slug>/` with subdirs (e.g., legacy AO migration in flight) could look both flat and nested. Detector rule: presence of `_index.md` at root → nested; otherwise flat. Document in `_common.py` docstring.

---

## Code Brief Standards (mandatory)

- **API version:** Anthropic Messages API. `claude-haiku-4-5` model ID. Verified active 2026-04-26 (referenced in `kbl/retry.py:105` and `kbl/cost.py:43-64`). Anthropic SDK already pinned in requirements.txt; no new external API.
- **Deprecation check date:** Haiku 4.5 confirmed active in cost map last touched 2026-04-21 (PROMPT_CACHE_AUDIT_1 didn't change this). No deprecation expected within M1 window.
- **Fallback:** `WIKI_LINT_ENABLED=false` (default) keeps scheduler dormant. Code ships, doesn't auto-run. Director flips after first dry-run.
- **DDL drift check:** Zero DDL. Verify per grep above.
- **Literal pytest output mandatory:** Ship report MUST include literal `pytest tests/test_wiki_lint.py tests/test_lint_check_*.py -v` stdout. ≥40 tests expected (7 checks × ~5 cases each + entrypoint coverage). No "passes by inspection" — explicit memory rule (`feedback_no_ship_by_inspection.md`).

## Verification criteria

1. `pytest tests/test_wiki_lint.py tests/test_lint_check_*.py -v` ≥40 tests pass.
2. `python -m kbl.wiki_lint --dry-run --vault-path /Users/dimitry/baker-vault` exits 0; produces a report file at `outputs/lint/<today>.md`; report contains all 7 check headers (even if 0 hits).
3. Real-vault dry-run on `BAKER_VAULT_PATH` produces 0 errors. Warnings/info acceptable. PR description lists all warnings.
4. Hagenauer-first acceptance: report cleanly shows `wiki/hagenauer-rg7/` (flat, pre-2026-04-23) under grandfather clause for check 2 — warn, NOT error.
5. Slack post fires on dry-run with summary line + report file path. (Test in dev with `WIKI_LINT_SLACK_DRY=true` env var if needed to avoid noise.)
6. `python -c "import py_compile; py_compile.compile('kbl/wiki_lint.py', doraise=True); py_compile.compile('kbl/anthropic_client.py', doraise=True); py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"` exits 0.
7. PR description includes V1/V2 carve-out + V2 question surface for Director ratification.
8. Hard ceiling on Haiku cost: simulate 200K-token run in test → lint aborts + Slack alert.

## Out of scope

- V2 vault mirror to `baker-vault/lint/` (separate brief once V1 stable).
- Action checkboxes in report (V2 once Director wants auto-fix sentinels).
- Auto-fix for one_way_cross_ref or missing reciprocal back-edges (V2).
- Lint-on-write hook in `kbl/ingest_endpoint.py` (separate brief; this is weekly batch only).
- Migration of existing flat-pattern matters to nested shape (Director-curation, not lint scope).
- Drift detector for slugs.yml itself (separate `BRIEF_KBL_SCHEMA_DRIFT_DETECTOR`, M1 row 3, still blocked on RA scope per critique M1.4).

---

## Branch + PR

- Branch: `wiki-lint-1`
- PR title: `WIKI_LINT_1: 7-check weekly wiki health audit (V1 — local output + Slack)`
- Reviewer: AI Head B (cross-team) per autonomy charter §4

## §6C orchestration note (B-code dispatch coordination)

WIKI_LINT_1 is parallel-safe with B1 (HAGENAUER_WIKI_BOOTSTRAP_1) and B3 (KBL_PEOPLE_ENTITY_LOADERS_1):
- B1 touches `scripts/` + `tests/` only.
- B3 touches `kbl/people_registry.py` + `kbl/entity_registry.py` + `kbl/ingest_endpoint.py` + `tests/`.
- B2 (this brief) touches `kbl/wiki_lint.py` + `kbl/lint_checks/*` + `kbl/anthropic_client.py` (additive helper) + `triggers/embedded_scheduler.py` + `tests/`.

`kbl/anthropic_client.py` is the only potential collision. B3 doesn't touch it. B2 adds `call_haiku()` (additive). No conflict expected.

**Hagenauer-first acceptance** in this brief depends on B1 having shipped its skeleton, OR runs against today's flat-pattern wiki. B2 can ship before B1; verification step 4 explicitly accepts grandfather-clause warn for the flat pattern.

## Co-Authored-By

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
