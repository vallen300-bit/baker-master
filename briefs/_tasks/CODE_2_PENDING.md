# CODE_2_PENDING — CAPABILITY_THREADS_1 — 2026-04-24

**Dispatcher:** AI Head #2 (Team 2)
**Working dir:** `~/bm-b2`
**Brief:** `briefs/BRIEF_CAPABILITY_THREADS_1.md` (1587 lines — read end-to-end before implementing)
**Target branch:** `capability-threads-1`
**Complexity:** Medium–High (~10–12h)

**Supersedes:** prior `PM_EXTRACTION_MAX_TOKENS_2` task (shipped as PR #56, merged `281661dc`). Mailbox reset.

---

## Why this brief

Phase 2 of the AO PM Continuity Program (ratified 2026-04-23; source: `/Users/dimitry/baker-vault/_ops/ideas/2026-04-23-ao-pm-continuity-program.md` §6). Adds episodic memory (threads + turns) to Pattern-2 capabilities so AO PM / MOVIE AM / future PMs replay conversational *shape*, not just atomic facts.

Phase 2 gate **MET** — Phase 1 backfill visible at `ao_pm v86` / `movie_am v131` (2026-04-24 00:14–00:17Z, Aukera red-flags, Patrick Zuchner thread, EUR 1.5M release path all present). Director ratified brief 2026-04-24 after reviewing stitcher module + Part H §H2 partial-attribution reason + sidebar UI feature-flag mechanics.

---

## Working-tree setup (B2)

```bash
cd ~/bm-b2 && git fetch origin && git pull --rebase origin main
git checkout -b capability-threads-1
```

Pre-merge verification (paste outputs into PR body per lesson #40):

```bash
# 1. pgvector NOT installed (design premise)
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_raw_query","arguments":{"sql":"SELECT extname FROM pg_extension WHERE extname IN ('\''vector'\'', '\''uuid-ossp'\'')"}}}'
# Expected: uuid-ossp only; vector absent.

# 2. No pre-existing capability_threads DDL in store_back.py (lesson #37)
grep -cE '_ensure_capability_threads|_ensure_capability_turns' memory/store_back.py
# Expected: 0

# 3. No duplicate /api/pm/threads endpoint (lesson #11)
grep -n '/api/pm/threads' outputs/dashboard.py
# Expected: 0

# 4. Baseline pm_project_state version (regression baseline for Quality Checkpoint 4)
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_raw_query","arguments":{"sql":"SELECT pm_slug, version, updated_at FROM pm_project_state WHERE state_key = '\''current'\'' ORDER BY pm_slug"}}}'
# Document pre-merge values; verify advance 24h post-deploy.

# 5. Singleton hook pre-push
bash scripts/check_singletons.sh
# Expected: pass.
```

---

## What you implement (6 features — full spec in brief)

Read `briefs/BRIEF_CAPABILITY_THREADS_1.md` end-to-end. Scope in one table:

| Feature | One-line scope |
|---|---|
| **F1 — Schema** | NEW `migrations/20260424_capability_threads.sql` — `capability_threads` + `capability_turns` tables + nullable `pm_state_history.thread_id` ADD COLUMN. Zero DDL in Python (lesson #37). |
| **F2 — Stitcher** | NEW `orchestrator/capability_threads.py` — hybrid scorer (Qdrant cosine + entity Jaccard + recency half-life), `stitch_or_create_thread` + `persist_turn` + `mark_dormant_threads`. Singleton access only (Rule 8). No LLM calls. |
| **F3 — Write wiring** | MODIFY `memory/store_back.py:5228` (add `thread_id` param, `RETURNING id`). MODIFY `orchestrator/capability_runner.py:261` (stitch + persist after existing state-write). MODIFY `orchestrator/pm_signal_detector.py:149` (partial attribution, documented). MODIFY `orchestrator/agent.py:2031` (close H4 gap: `mutation_source="agent_tool"`). |
| **F4 — Read wiring** | MODIFY `orchestrator/capability_runner.py:1062+` — new method `_get_pm_thread_context`; inject Layer 1.5 section in `_build_system_prompt` between lines 1105 and 1107 (verify current line numbers before edit per Rule 7). |
| **F5 — Sidebar UI** | MODIFY `outputs/dashboard.py` — 3 new endpoints (GET list, GET turns, POST re-thread). MODIFY `outputs/static/{app.js,index.html,style.css}` — **pure DOM only** (no `innerHTML` with user content). Feature-flagged via `localStorage['baker.threads.ui_enabled']='1'`. Bump `?v=N` cache bust (lesson #4). |
| **F6 — Tests** | NEW `tests/test_capability_threads.py` (unit + SQL-assertion + integration). NEW `tests/test_capability_threads_h5.py` (§Part H §H5 cross-surface continuity test — MANDATORY). |

---

## Mandatory compliance — AI Head SKILL Rules

- **Rule 4 — migration-vs-bootstrap DDL:** grep `memory/store_back.py` for any `_ensure_capability_*` before ship. Expected: none.
- **Rule 7 — file:line verification:** EVERY cited line (`capability_runner.py:261`, `:1062`, `:1105`, `:1875`, `store_back.py:5228`, `pm_signal_detector.py:149`, `agent.py:2031`, `dashboard.py:8148`, `:8240`) must be re-verified with `grep -n` before edit. File lengths drift; do NOT trust the brief's numbers blindly.
- **Rule 8 — singleton:** `SentinelStoreBack._get_global_instance()` / `SentinelRetriever._get_global_instance()` only. Never bare constructor. `scripts/check_singletons.sh` gates pre-push.
- **Rule 10 — Part H:** brief §Part H complete (H1–H5). Cite the partial-attribution table in PR body. Signal + agent_tool deliberate-partial with reason.
- **Python rules** (`.claude/rules/python-backend.md`): every `except` → `conn.rollback()`; all DB queries → `LIMIT`; fault-tolerant writes; `re.IGNORECASE` flag (not inline `(?i)`).
- **Security** (hook-enforced): **no `innerHTML` with user-derived content** anywhere in `app.js`. Use `textContent` / `createTextNode` / `appendChild` / `replaceChildren`-equivalent.

---

## Acceptance criteria (ship gate — literal pytest green)

### Syntax + hooks

```bash
$ python3 -c "import py_compile; \
    py_compile.compile('orchestrator/capability_threads.py', doraise=True); \
    py_compile.compile('orchestrator/capability_runner.py', doraise=True); \
    py_compile.compile('orchestrator/pm_signal_detector.py', doraise=True); \
    py_compile.compile('orchestrator/agent.py', doraise=True); \
    py_compile.compile('memory/store_back.py', doraise=True); \
    py_compile.compile('outputs/dashboard.py', doraise=True); \
    print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### Ship-gate test run (literal output pasted into PR — no "pass by inspection")

```bash
$ python3 -m pytest tests/test_capability_threads.py tests/test_capability_threads_h5.py -v --run-integration 2>&1 | tail -40
```

Expected: `X passed, 0 failed` where X covers:
- entity extractor (2 tests)
- scoring / Jaccard / recency (3 tests)
- topic summary (2 tests)
- DDL smoke (1 test, integration)
- UUID guardrail (1 test)
- H5 cross-surface continuity (1 test, integration)

### Regression delta vs `main @ 281661dc`

```bash
$ python3 -m pytest 2>&1 | tail -3
# branch passes = main passes + 9 (approx; new tests only)
# branch failures == main failures (zero)
```

### Scope discipline — file count

```bash
$ git diff main..HEAD --name-only
```

Expected modified/added (~12 files; order-agnostic):
- `migrations/20260424_capability_threads.sql`
- `orchestrator/capability_threads.py`
- `orchestrator/capability_runner.py`
- `orchestrator/pm_signal_detector.py`
- `orchestrator/agent.py`
- `memory/store_back.py`
- `outputs/dashboard.py`
- `outputs/static/app.js`
- `outputs/static/index.html`
- `outputs/static/style.css`
- `tests/test_capability_threads.py`
- `tests/test_capability_threads_h5.py`

If count drifts by more than ±1, document reason in PR body.

### Schema smoke against live Render Neon (post-merge, before closing)

Paste output of verification SQL block (brief §"Verification SQL (ready-to-run post-deploy)"). Director may spot-check #2 (thread activity) and #3 (cross-surface continuity) after triggering one AO PM sidebar query.

---

## Dispatch protocol

1. Pull main + branch.
2. Read brief end-to-end — especially §Part H §H1 invocation-path enumeration (21 files grepped, 5 write callers + 16 read-only intentional) and §Part H §H2 partial-attribution table (signal + agent_tool documented reasons).
3. Implement F1 → F2 → F3 → F4 → F5 → F6 in order (dependencies flow top-down). Alternatively F6 tests drafted alongside F1/F2 (TDD). Your call.
4. Single PR OR per-feature commits — your call. `Co-Authored-By` trailer standard.
5. Push branch + open PR. PR title: `CAPABILITY_THREADS_1: episodic memory for Pattern-2 capabilities (Phase 2 of AO PM Continuity)`. PR body: brief §"Design summary" + literal ship-gate output + Part H audit table + pre-merge verification outputs.
6. Ship report: `briefs/_reports/CODE_2_RETURN.md` on your branch (standard format).
7. Tag `@ai-head-2 ready for review`.

AI Head #2 runs `/security-review` + Tier A merge + verifies post-deploy Quality Checkpoints 1–13 + enables UI flag on Director's dashboard after Checkpoints green.

---

## Hard deadline

None. Phase 3 (BRIEF_PROACTIVE_PM_SENTINEL_1) drafts in parallel per Q7 sequencing. Phase 2 ships when ready; Phase 3 ships after Phase 2 merges.

---

## Known blocking dependencies

None. All prerequisites (PR #50, PR #54, PR #56) merged. No coordination needed with Team 1's M0 quintet (orthogonal lanes).

## Known partial attributions (expected; documented in brief §Part H §H2)

- `signal` surface → `pm_state_history.thread_id` stays NULL (capability_turns row carries thread_id; documented reason: refactor of `flag_pm_signal` out of scope).
- `agent_tool` surface → no turn record (documented reason: agent-tool writes rare; H4 tag closure satisfies Amendment H for this phase).

Both are tracked for Monday 2026-04-27 audit scratch (`_ops/agents/ai-head/SCRATCH_MONDAY_AUDIT_20260427.md` §B3) as follow-up brief candidate.

— AI Head #2
