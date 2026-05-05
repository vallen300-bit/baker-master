# BRIEF: BAKER-INTERVAL-PARAMETERIZATION-SWEEP-1 — Convert non-standard `INTERVAL '%s <unit>'` idiom across live code

## Context

Baker has 20 live-code sites using the non-standard idiom `INTERVAL '%s days'` / `INTERVAL '%s hours'` / `INTERVAL '%s minutes'` with psycopg2 parameter binding. This pattern was flagged by gate-4 code-reviewer on PR #158 (B2 cost-instrumentation) as a runtime crash; investigation surfaced a broader truth: the idiom is **fragile and non-standard, not always crashing**. psycopg2 uses Python `%` formatting under the hood — integer `days` values substitute as bare integers and produce valid SQL (`INTERVAL '7 days'`); string values would crash via double-quoting. Today all sites pass integers, so no production crashes. **But the idiom is type-fragile**: a single accidental `str(days)` call upstream silently breaks the query. B2's PR #158 fold replaced 2 sites in `cost_monitor.py` with the canonical safe form `(INTERVAL '1 day' * %s)`. This brief sweeps the remaining **18 sites** to either `make_interval(<unit> => %s)` (preferred — Postgres-native, expressive) or `(INTERVAL '1 unit' * %s)` (acceptable — used by B2's fold + scripts/prompt_cache_hit_rate.py).

**Estimated time:** ~1 day
**Complexity:** Low (mechanical refactor; ~20 single-line edits)
**Prerequisites:** B2 PR #158 (BAKER_COST_INSTRUMENTATION_1) MERGED FIRST so this brief doesn't touch `cost_monitor.py` and avoid merge conflicts
**Tier:** A (no auth surface, no DB schema change, no functional behavior change — pure refactor)

**Director ratification:** 2026-05-05 chat ("go AH2 + author sweep brief") — architect spot-check on B2 fold flagged the broader infestation, Director authorized sweep brief.

---

## Design Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Canonical replacement form: `make_interval(<unit> => %s)`** | Already used at 9 live-code sites (memory/store_back.py, orchestrator/pipeline.py, orchestrator/agent_metrics.py, triggers/rss_trigger.py, document_generator.py). Postgres-native, expressive, type-safe. Single canonical form across entire codebase post-sweep. |
| 2 | **Acceptable alternative: `(INTERVAL '1 day' * %s)`** | Used at B2 fold (cost_monitor.py:334,386) + scripts/prompt_cache_hit_rate.py:57. Allowed where the `make_interval` form would conflict with existing query patterns or read awkwardly. B-code chooses per site. |
| 3 | **DO NOT touch `cost_monitor.py`** | B2's PR #158 fold owns 2 sites there. Sequencing: #158 merges first, then this sweep is a clean diff against post-#158 main. |
| 4 | **In-scope: live code only** | `briefs/*.md` historical specs are NOT live code; skip. `tests/*.py` only if they query live PG (most don't); skip mock-based tests. |
| 5 | **Site-by-site verification before swap** | Each site: identify the parameter type currently passed (int / str / coerced). If int: safe today, swap is hardening. If str: swap is crash-fix. Document each in ship report. |
| 6 | **Test gate: regression-prevention scanner** | New test `tests/test_no_legacy_interval_pattern.py` greps live-code (`orchestrator/`, `outputs/`, `baker_mcp/`, `kbl/`, `triggers/`, `scripts/`, `memory/`) for the legacy pattern; FAILS if any match. Runs in CI; future regressions caught at PR time. |
| 7 | **Single PR** | Atomic refactor; one /security-review; one /code-reviewer 2nd-pass. ~20 lines + test file. |
| 8 | **Kill-switch: NOT REQUIRED** | Pure refactor with no behavior change; no env-var needed. |
| 9 | **IN scope: BOTH psycopg2-bound AND Python-`%`-formatted sites** | Architect post-WRITE review caught initial inconsistency — 5+ sites use Python `%` formatting against SQL string with constants/variables, NOT psycopg2 binding. Same surface fix (canonical `make_interval(<unit> => %s)`), different param-passing path. Folding ALL into a single canonical pass is cleaner than splitting into two briefs. Per-site classification table in §"Sites to remediate" specifies which path each uses. |
| 9.1 | **In scope: `.replace("%s days", f"{days} days")` form too** (initiative_engine.py:560 style) | Third anti-pattern — manual string-replace. Same canonical fix. Explicitly call this out so B-code worker doesn't miss it OR add it back as workaround. |
| 9.2 | **Param-type-aware fix:** | psycopg2-bound sites get `make_interval(<unit> => %s)` with bind tuple unchanged. `%`-formatted constants get `make_interval(<unit> => %s)` with the constant added to the bind tuple (NOT formatted into the SQL). Site classification table specifies. |
| 10 | **Acceptance: ZERO matches of `INTERVAL '%s` regex in live code post-merge** | Verified via the regression test from Decision #6. |

---

## Sites to remediate (20 total in live code, mapped post-B2-merge)

### `baker_mcp/baker_mcp_server.py` (7 sites)

| Line | Pattern | Param source |
|---|---|---|
| 1005 | `due_date <= NOW() + INTERVAL '%s days'` | `args.get("days", 7)` (int) |
| 1027 | `created_at >= NOW() - INTERVAL '%s days'` | `args.get("days", 7)` (int) |
| 1042 | `created_at >= NOW() - INTERVAL '%s days'` | `args.get("days", 7)` (int) |
| 1114 | `ingested_at >= NOW() - INTERVAL '%s days'` | `args.get("days", 3)` (int) |
| 1130 | `created_at >= NOW() - INTERVAL '%s days'` | `args.get("days", 30)` (int) |
| 1153 | `created_at >= NOW() - INTERVAL '%s days'` | `args.get("days", 30)` (int) |
| 1191 | `br.created_at >= NOW() - INTERVAL '%s days'` | `args.get("days", 7)` (int) |

All use `params.append(days)` as separate bind param; all integer; safe today, swap = hardening.

### `outputs/dashboard.py` (6 sites)

| Line | Pattern | Param-passing path |
|---|---|---|
| 2246 | `created_at < NOW() - INTERVAL '%s days'` | psycopg2-bound (int) |
| 3929 | `created_at >= NOW() - INTERVAL '%s hours'` | psycopg2-bound (int) |
| 3939 | `created_at >= NOW() - INTERVAL '%s hours'` | psycopg2-bound (int) |
| 9558 | `created_at > NOW() - INTERVAL '%s days'` | **Python `%` formatting** — verify caller; if `days` is request-query-param, this is injection-shaped (not just type-fragile). Canonical fix moves param to psycopg2 bind tuple. |
| 9573 | `created_at > NOW() - INTERVAL '%s days'` | **Python `%` formatting** — same as above |
| 9585 | `created_at > NOW() - INTERVAL '%s days'` | **Python `%` formatting** — same as above |

### `orchestrator/memory_consolidator.py` (3 sites — ALL in scope, including line 219)

| Line | Pattern | Param-passing path |
|---|---|---|
| 219 | `ci.timestamp < NOW() - INTERVAL '%s days'` | **Python `%` formatting** against `TIER1_TO_TIER2_AGE_DAYS` constant (line 223: `""" % (CONSTANT, ...)`). Folded back in per Decision #9. |
| 252 | `ci.timestamp < NOW() - INTERVAL '%s days'` | **Python `%` formatting** against `TIER1_TO_TIER2_AGE_DAYS` + others — same anti-pattern. |
| 570 | `period_end < NOW() - INTERVAL '%s days'` | **Python `%` formatting** against `TIER2_TO_TIER3_AGE_DAYS` constant. |

### Other (4 sites)

| File:Line | Pattern | Param-passing path |
|---|---|---|
| `orchestrator/cortex_phase5_act.py:438` | `created_at >= NOW() - INTERVAL '%s minutes'` | psycopg2-bound — verify |
| `orchestrator/initiative_engine.py:560` | `created_at > NOW() - INTERVAL '%s days'` | **Manual `.replace("%s days", f"{int(days)} days")`** — third anti-pattern (Decision #9.1). Canonical fix replaces with `make_interval(days => %s)` + bind tuple. |
| `kbl/bridge/alerts_to_signal.py:435` | `NOW() - INTERVAL '%s hours'` | psycopg2-bound — verify |
| `scripts/backfill_missed_attachments.py:45` | `received_date > NOW() - INTERVAL '%s days'` | psycopg2-bound (int, `(days,)`) |

**Total: 19 sites** (memory_consolidator.py line 219 folded back in per architect post-WRITE review; B2 #158 merge clears cost_monitor.py:334,386 separately).

**Two anti-pattern classes (per architect post-WRITE review):**
- **Type-fragile (psycopg2-bound):** ~12 sites. Today integer-only, works fine. Future string-typed param would crash. Hardening fix.
- **Injection-shaped (`%` formatting / `.replace()`):** ~7 sites. Today against constants or int-coerced values, works fine. If `days` ever flows from user input, real SQL-injection risk. **Higher-priority subset within the sweep.** B-code should remediate these FIRST in the PR sequence so a partial-merge (if needed) lands the injection-shaped fixes ahead of type-fragile ones.

---

## Implementation pattern

For each site, swap:

```python
# BEFORE
"WHERE created_at >= NOW() - INTERVAL '%s days'"
# (with separate params.append(days) or (days,) tuple)
```

```python
# AFTER (preferred)
"WHERE created_at >= NOW() - make_interval(days => %s)"
# (param binding unchanged)
```

OR (acceptable, B2-fold style):

```python
# AFTER (alternative)
"WHERE created_at >= NOW() - (INTERVAL '1 day' * %s)"
```

B-code worker chooses per site based on readability + surrounding code style.

**Important:** if a site has `%s` substituted via Python `%` formatting (not psycopg2 binding) — e.g., `""" % (CONST,)` outside `cur.execute(..., (params,))` — DO NOT swap. Different anti-pattern, out of scope. Verify each site before changing.

---

## Test gate: regression scanner

**NEW file:** `tests/test_no_legacy_interval_pattern.py`

```python
"""Prevents regression of INTERVAL '%s <unit>' anti-pattern across live code.

After BAKER-INTERVAL-PARAMETERIZATION-SWEEP-1 ships, no live-code site should
use `INTERVAL '%s <unit>'`. This test enforces that property at PR time.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
LIVE_DIRS = ["orchestrator", "outputs", "baker_mcp", "kbl", "triggers",
             "scripts", "memory", "tools", "models", "config"]
# Catch-all on \w+ unit; covers days/hours/minutes/seconds/weeks/months/years +
# any future units. Matches both psycopg2-bound `INTERVAL '%s X'` and
# Python-`%`-formatted `INTERVAL '%s X'` (regex matches the source, not runtime).
LEGACY_PATTERN = re.compile(r"INTERVAL\s+'%s\s+\w+'")
SELF_FILE = "test_no_legacy_interval_pattern.py"

def test_no_legacy_interval_pattern_in_live_code():
    """Fails if any live-code .py file contains INTERVAL '%s <unit>'."""
    matches = []
    for d in LIVE_DIRS:
        path = REPO_ROOT / d
        if not path.exists():
            continue
        for py_file in path.rglob("*.py"):
            if py_file.name == SELF_FILE:
                continue  # this test contains the legacy pattern in its docstring/regex
            try:
                text = py_file.read_text()
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if LEGACY_PATTERN.search(line):
                    matches.append(f"{py_file.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not matches, (
        "Legacy INTERVAL '%s <unit>' pattern found in live code. "
        "Use make_interval(<unit> => %s) or (INTERVAL '1 <unit>' * %s) instead. "
        "Sites:\n  " + "\n  ".join(matches)
    )
```

Test must pass post-sweep on B-code's local pytest run before PR opens.

---

## Acceptance Criteria

| AC | Description | Verification |
|---|---|---|
| **A1** | All 18 sites enumerated in §"Sites to remediate" swapped to canonical form | Per-site grep confirms; ship report enumerates each (file:line, before/after snippet) |
| **A2** | `tests/test_no_legacy_interval_pattern.py` GREEN on b-code branch | Literal pytest output |
| **A3** | Existing tests touching the modified files still GREEN | Full pytest run, literal output |
| **A4** | No site picked the wrong canonical form (B-code judgment validated by reviewer) | feature-dev:code-reviewer 2nd-pass scrutinizes form choice |
| **A5** | `cost_monitor.py` UNTOUCHED in this PR | git diff confirms; if it appears, conflict with B2 #158 |
| **A6** | Per-site param-type + param-passing-path verification documented in ship report | Each site: classify as (a) psycopg2-bound type-fragile, (b) Python `%` formatting injection-shaped, (c) `.replace()` injection-shaped. For (b) + (c) — verify whether `days` flows from request params or other user input; flag as injection-shaped if yes. Anti-pattern class (a/b/c), pre-fix snippet, post-fix snippet, source of `days`/`hours` value. |
| **A6.1** | Injection-shaped sites (b + c) MUST be in earliest commits of the PR | Per Decision in §"Sites to remediate" — partial-merge safety. Ship report records commit-by-commit ordering. |
| **A6.2** | Test scanner skips its own file (`test_no_legacy_interval_pattern.py`) | Per regression test §SELF_FILE skip; verify with deliberate test-of-the-test. |
| **A7** | NO new env vars introduced | Pure refactor; if env var creeps in, scope deviation |
| **A8** | feature-dev:code-reviewer 2nd-pass clean | Per SKILL.md `59f23c4` Trigger §2 — DB query change touches data-path; mandatory trigger |

**Ship gate:** literal pytest GREEN + A1-A8 all met. NO behavioral change expected; if any test that was passing pre-sweep fails post-sweep, investigate (likely a site where the swap accidentally changed semantics — e.g., interval unit mismatch).

---

## Open questions for AH1 (none expected)

None. Architect verified canonical form already in use at 9 sites; B2's fold validated the alternative form. Pure mechanical refactor.

---

## Out-of-scope (flagged for follow-up)

1. **Other Python `%` formatting against SQL strings** beyond the INTERVAL idiom — broader anti-pattern across the codebase (e.g., dynamic ORDER BY, dynamic table names). NOT in this sweep; flag for follow-up brief `BRIEF_BAKER_PYTHON_PERCENT_SQL_FORMATTING_SWEEP_1.md` if Director approves. (INTERVAL-specific `%` formatting IS in scope per Decision #9.)
2. **Historical brief `*.md` files** containing the legacy pattern — not live code; skip.
3. **Test fixtures or string templates** — case-by-case if grep surfaces any.

---

## Sequencing

1. **WAIT for B2 PR #158 to merge** (touches `cost_monitor.py:265,313` → `334,386`).
2. B-code (B1, B2, or B3 depending on availability) claims this brief.
3. Run grep-verify of all 18 sites against fresh main HEAD (line numbers may shift post-B2-merge).
4. Per-site read + param-type verification; document in scratch.
5. Apply swaps + add regression test.
6. Live pytest GREEN.
7. Open PR.
8. AH1 reviews + merges.
9. Verify regression test green in CI for next 7 days; no false positives.

---

## Reference

- B2 fold commit: `34b0628c` on `b2/baker-cost-instrumentation-1` — establishes `(INTERVAL '1 day' * %s)` form
- Canonical `make_interval` form precedent: `memory/store_back.py:4370,4397,5240`, `orchestrator/pipeline.py:235`, `orchestrator/agent_metrics.py:131,186`, `triggers/rss_trigger.py:520`, `document_generator.py:237`
- Architect spot-check that surfaced the broader scope: agent ID `a4b176c011756277d` (2026-05-05)
- BRIEF_PERSISTENT_DOCS_PANEL.md row 813 — earlier ratified `make_interval(days => %s)` as fix for same pattern (LOW finding)
- psycopg2 parameterization docs: https://www.psycopg.org/docs/usage.html#passing-parameters-to-sql-queries
