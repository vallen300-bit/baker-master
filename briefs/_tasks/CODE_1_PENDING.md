# Code Brisen #1 — Pending Task

**From:** AI Head (Team 1 — Meta/Persistence)
**To:** Code Brisen #1
**Task posted:** 2026-04-24
**Status:** OPEN — `PROMPT_CACHE_AUDIT_1` (M0 quintet row 4 — Anthropic prompt-cache audit + apply to top-3 hot sites + 24h telemetry)

**Supersedes:** prior `KBL_INGEST_ENDPOINT_1` task — shipped as PR #55, merged `c578b58` 2026-04-24. Mailbox cleared.

**Parallel task note:** CITATIONS_API_SCAN_1 is dispatched to B3 in the same session. Independent scope, zero file overlap. No coordination needed; both proceed independently.

---

## Brief-route note (charter §6A)

Full `/write-brief` 6-step protocol. Brief at `briefs/BRIEF_PROMPT_CACHE_AUDIT_1.md`.

Closes M0 row 4 — Adoption 1 of the ratified 2026-04-21 Anthropic 4.7 upgrade package. Pure cost-win, zero risk (system-block caching only; no model-version flip). Existing Step 5 precedent at `kbl/anthropic_client.py:238` (`cache_control: {"type": "ephemeral"}`) is the reference.

---

## Context (TL;DR)

Only 1 of ~15 Claude call sites currently uses `cache_control`. Anthropic prompt caching gives ~90% cost reduction on cached prefix. This brief ships:
1. A static-analysis audit script (`scripts/audit_prompt_cache.py`) that inventories call sites + classifies cache eligibility.
2. Applies `cache_control: {"type": "ephemeral"}` to the top-3 highest-leverage sites: `outputs/dashboard.py` `/api/scan`, `orchestrator/capability_runner.py`, `baker_rag.py`.
3. Adds cache-hit telemetry — a `baker_actions` row per call carrying `{input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, call_site}`.
4. 24h hit-rate aggregation script with Slack alert if <60%.
5. pytest (8 scenarios) — audit-script shape + cost-math round-trip + telemetry-silent-on-failure.

## Action

Read `briefs/BRIEF_PROMPT_CACHE_AUDIT_1.md` end-to-end. 4 features with copy-pasteable content.

**Files to touch:**
- NEW `scripts/audit_prompt_cache.py` (~240 LOC, AST-based, stdlib-only).
- NEW `scripts/prompt_cache_hit_rate.py` (~110 LOC, reads baker_actions JSONB).
- NEW `kbl/cache_telemetry.py` (~70 LOC, fire-and-forget helper).
- NEW `tests/test_prompt_cache_audit.py` (~180 LOC, 8 tests).
- MODIFIED `outputs/dashboard.py` (`/api/scan` stable prefix → cache_control + log_cache_usage wiring, ~15 LOC).
- MODIFIED `orchestrator/capability_runner.py` (same pattern, ~15 LOC).
- MODIFIED `baker_rag.py` (same, ~15 LOC).

**Non-negotiable invariants:**
- Do NOT touch `kbl/anthropic_client.py` — already caches correctly.
- Do NOT touch model IDs anywhere — this is cache-only, NOT the 4.6→4.7 migration.
- Do NOT apply cache_control to call sites below the 1024-token threshold — document skips in ship report.
- `log_cache_usage` is FIRE-AND-FORGET — must never raise, never block the Claude call.
- No new env vars, no schema changes.
- Stable persona stays as a cache_control'd text block in `system=[...]`; dynamic retrieval/context moves to user message (NOT system) so the cache prefix stays stable across calls.

## Ship gate (literal output required in ship report)

**Baseline first** — `pytest tests/ 2>&1 | tail -3` on main BEFORE branching.

After implementation:

```bash
# 1. Python syntax (7 files)
for f in scripts/audit_prompt_cache.py scripts/prompt_cache_hit_rate.py \
         kbl/cache_telemetry.py tests/test_prompt_cache_audit.py \
         outputs/dashboard.py orchestrator/capability_runner.py baker_rag.py; do
  python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" || { echo FAIL $f; exit 1; }
done && echo "All 7 files syntax-clean."

# 2. Audit script runs end-to-end
python3 scripts/audit_prompt_cache.py --out /tmp/audit.md
head -30 /tmp/audit.md

# 3. Imports smoke
python3 -c "from kbl.cache_telemetry import log_cache_usage; from scripts.audit_prompt_cache import CallSite; print('OK')"

# 4. 3 hot sites carry cache_control
grep -l "cache_control" outputs/dashboard.py orchestrator/capability_runner.py baker_rag.py

# 5. New tests in isolation
pytest tests/test_prompt_cache_audit.py -v 2>&1 | tail -15   # expect 8 passed

# 6. Full-suite regression
pytest tests/ 2>&1 | tail -3                                 # +8 vs baseline, 0 regressions

# 7. Singleton hook
bash scripts/check_singletons.sh

# 8. No baker-vault writes
git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."

# 9. No API calls in test suite
grep -E "anthropic\.Anthropic\(|messages\.create" tests/test_prompt_cache_audit.py
```

**No "pass by inspection"** (per `feedback_no_ship_by_inspection.md`). Paste literal outputs.

## Ship shape

- **PR title:** `PROMPT_CACHE_AUDIT_1: audit script + top-3 cache_control + 24h hit-rate telemetry`
- **Branch:** `prompt-cache-audit-1`
- **Files:** 7 (4 new + 3 modified).
- **Commit style:** `kbl(cache): audit script + apply cache_control to scan/capability/rag + baker_actions telemetry`
- **Ship report:** `briefs/_reports/B1_prompt_cache_audit_1_20260424.md`. Include all 9 ship-gate outputs + baseline pytest line + first-pass audit-report summary + git diff --stat.

**Tier A auto-merge on B3 APPROVE + green /security-review** per SKILL.md Security Review Protocol.

## Out of scope (explicit)

- **Do NOT** bump Baker's default model from 4.6 to 4.7 — separate M4 migration brief.
- **Do NOT** enable Anthropic Citations API — that's CITATIONS_API_SCAN_1 (parallel dispatch to B3).
- **Do NOT** apply cache_control to non-top-3 sites (triggers/, tools/, backfill scripts) — second-wave follow-on (`PROMPT_CACHE_ROLLOUT_1`) after 7-day observation.
- **Do NOT** add a cron to run `prompt_cache_hit_rate.py` — on-demand only for MVP.
- **Do NOT** add a web dashboard tile for cache-hit rate.
- **Do NOT** refactor `kbl/cost.py` pricing table.
- **Do NOT** change user-message shape (cache_control only applies to system block).
- **Do NOT** touch `CHANDA.md` / `CHANDA_enforcement.md` — this brief doesn't change invariants.
- **Do NOT** touch `triggers/embedded_scheduler.py`, `memory/store_back.py`, `invariant_checks/ledger_atomic.py`, `kbl/slug_registry.py`, `models/cortex.py` — unrelated.

## Timebox

**3–3.5h.** If >5h, stop and report — likely stable-prefix extraction friction at one of the 3 hot sites.

**Working dir:** `~/bm-b1`.

---

**Dispatch timestamp:** 2026-04-24 post-PR-55-merge (Team 1, M0 quintet row 4)
**Team:** Team 1 — Meta/Persistence
**Parallel:** B3 running CITATIONS_API_SCAN_1 (M0 row 5) — independent scope, no file overlap.
**Sequence:** ENFORCEMENT_1 (#45) → GUARD_1 (#49) → LEDGER_ATOMIC_1 (#51) → KBL_SCHEMA_1 (#52) → MAC_MINI_WRITER_AUDIT_1 (#53) → KBL_INGEST_ENDPOINT_1 (#55) → **PROMPT_CACHE_AUDIT_1 (this)** — closes M0 row 4.
