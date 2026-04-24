# Code Brisen #3 — Pending Task

**From:** AI Head (Team 1 — Meta/Persistence)
**To:** Code Brisen #3
**Task posted:** 2026-04-24
**Status:** OPEN — `CITATIONS_API_SCAN_1` (M0 quintet row 5 — Anthropic Citations API on Scan + render in Slack substrate)

**Supersedes:** prior `KBL_INGEST_ENDPOINT_1` B3 review task — APPROVE landed; PR #55 merged `c578b58` 2026-04-24. Mailbox cleared.

**Role note:** Director authorized B3 as a PARALLEL CODER for this session (2026-04-24 "Dispatch to B1 + B3 (Tier A)"). You are writing code, not reviewing. B1 is coding PROMPT_CACHE_AUDIT_1 in parallel. Independent scope, zero file overlap.

---

## Brief-route note (charter §6A)

Full `/write-brief` 6-step protocol. Brief at `briefs/BRIEF_CITATIONS_API_SCAN_1.md`.

Closes M0 row 5 — Adoption 3 of the ratified 2026-04-21 Anthropic 4.7 upgrade package. Mechanizes CHANDA Surface Invariant S5 ("Scan responses cite sources; no hallucinated citations") at the model layer — replaces prompt-engineered anti-hallucination enforcement with Anthropic's Citations API.

---

## Context (TL;DR)

Currently Scan uses prompt-level instructions ("Never fabricate citations — only cite sources you actually retrieved" in `capability_runner.py:1149`) to coerce source-anchored responses. Anthropic's Citations API does this at model level — each claim carries a pointer to its supporting document span, validated by the model.

This brief ships:
1. `kbl/citations.py` — thin adapter: `build_document_blocks()`, `extract_citations()`, `render_citations_markdown()`, `render_citations_slack_blocks()`, `Citation` dataclass, `ExtractedResponse` dataclass.
2. Wires Anthropic Citations into 3 Scan endpoints: `/api/scan`, `/api/scan/specialist`, `/api/scan/client-pm`. Retrieval hits move from system-prompt injection to `documents=[...]` blocks in the user message with `citations: {enabled: True}`.
3. Emits a `__citations__<json>` SSE event after the text stream completes (frontend parsing follow-on).
4. Slack substrate rendering — `post_scan_with_citations()` helper in `outputs/slack_notifier.py` posts answer + citation-footer Block Kit blocks.
5. CHANDA_enforcement.md §5 row S5 method column updated to reference the Citations API; §7 amendment-log row.
6. pytest — 13 scenarios covering adapter + Block Kit + graceful degradation.

**Model-agnostic:** Works on both Opus 4.6 and 4.7. Does NOT flip Baker's default model; that's the M4 eval-gated migration brief.

**Belt-and-braces:** `capability_runner.py:1149` anti-hallucination prompt instruction is RETAINED until 7-day post-merge observation. Removal is follow-on `CITATIONS_PROMPT_CLEANUP_1`.

## Action

Read `briefs/BRIEF_CITATIONS_API_SCAN_1.md` end-to-end. 5 features with copy-pasteable content.

**Files to touch:**
- NEW `kbl/citations.py` (~200 LOC).
- NEW `tests/test_citations_api_scan.py` (~200 LOC, 13 tests using `SimpleNamespace` SDK response stubs — no `unittest.mock.patch`).
- MODIFIED `outputs/dashboard.py` — 3 Scan endpoints wired: `/api/scan` @7249, `/api/scan/specialist` @5406, `/api/scan/client-pm` @5495 (~40 LOC delta).
- MODIFIED `outputs/slack_notifier.py` — new `post_scan_with_citations()` helper (~30 LOC).
- MODIFIED `CHANDA_enforcement.md` — §5 row S5 method column + §7 amendment-log +1 row.

**Non-negotiable invariants:**
- Do NOT remove `capability_runner.py:1149` anti-hallucination prompt instruction — belt-and-braces.
- Do NOT change `ScanRequest` / `SpecialistScanRequest` Pydantic input shape.
- Do NOT apply Citations to `/api/scan/image`, `/api/scan/followups`, `/api/scan/detect` — those are secondary paths (separate rollout brief).
- Do NOT change Baker's default model ID anywhere — adapter is model-agnostic.
- Adapter MUST degrade gracefully — if SDK response lacks `citations` attr on blocks, return empty citations list, NOT raise.
- Respect any `cache_control` applied by PROMPT_CACHE_AUDIT_1 (parallel B1 PR) — the stable persona block stays in `system=`; retrieval documents go in the user message. Merge-compat note below.
- Slack Block Kit caps: 3000-char mrkdwn, 10 context elements — honor both.

**Merge-compatibility with B1's parallel PR (PROMPT_CACHE_AUDIT_1):**
- Both PRs touch `outputs/dashboard.py` (`/api/scan` handler).
- B1 changes the `system=` kwarg (split stable persona + apply cache_control).
- You change the `messages=` kwarg (add document blocks, wire citations extraction).
- These are compatible but likely produce merge conflicts at the call site. Whichever merges second does a `git pull --rebase origin main` on the PR branch and resolves — keep BOTH changes (cache_control on stable system block + documents in user message + extract_citations post-call).
- AI Head will manage rebase order. Ship clean; rebase is standing §3 autonomy.

## Ship gate (literal output required in ship report)

**Baseline first** — `pytest tests/ 2>&1 | tail -3` on main BEFORE branching.

After implementation:

```bash
# 1. Python syntax (5 files — 2 new + 3 modified + 1 CHANDA_enforcement.md implicit)
for f in kbl/citations.py tests/test_citations_api_scan.py \
         outputs/dashboard.py outputs/slack_notifier.py; do
  python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" || { echo FAIL $f; exit 1; }
done && echo "All 4 Python files syntax-clean."

# 2. Import smoke
python3 -c "from kbl.citations import Citation, ExtractedResponse, build_document_blocks, extract_citations, render_citations_markdown, render_citations_slack_blocks; print('OK')"

# 3. Scan endpoints wire the adapter
grep -c "build_document_blocks\|extract_citations" outputs/dashboard.py   # expect ≥3 (one per Scan endpoint)

# 4. Slack helper exists
grep -n "def post_scan_with_citations" outputs/slack_notifier.py          # expect 1

# 5. CHANDA §5 row S5 updated
grep "Anthropic Citations API (model-level grounding)" CHANDA_enforcement.md  # expect ≥1

# 6. CHANDA §7 amendment log — 5 dated rows
grep -c "^| 2026-04" CHANDA_enforcement.md                                # expect 5

# 7. New tests in isolation
pytest tests/test_citations_api_scan.py -v 2>&1 | tail -20                 # expect 13 passed

# 8. Full-suite regression
pytest tests/ 2>&1 | tail -3                                               # +13 vs baseline, 0 regressions

# 9. Belt-and-braces prompt retained
grep "Never fabricate citations" orchestrator/capability_runner.py         # expect 1 hit

# 10. Singleton hook
bash scripts/check_singletons.sh

# 11. No baker-vault writes
git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
```

**No "pass by inspection"** (per `feedback_no_ship_by_inspection.md`). Paste literal outputs.

## Ship shape

- **PR title:** `CITATIONS_API_SCAN_1: Anthropic Citations adapter + 3 Scan endpoints wired + Slack substrate render + S5 §5/§7`
- **Branch:** `citations-api-scan-1`
- **Files:** 5 (2 new + 3 modified).
- **Commit style:** `kbl(citations): Citations API adapter + Scan endpoints + Slack substrate + CHANDA §5 S5 mechanical enforcement`
- **Ship report:** `briefs/_reports/B3_citations_api_scan_1_20260424.md`. Include all 11 ship-gate outputs + baseline pytest line + git diff --stat.

**Tier A auto-merge on AI Head REVIEW + green /security-review** (Director explicit for this session — skip the B3-review-of-own-code gate since you're coding; AI Head does a 1-pass read-through before auto-merge).

## Out of scope (explicit)

- **Do NOT** apply Citations to non-Scan paths (ingest, capability_runner direct calls, chain_runner, triggers, tools, scripts/backfill_*) — `CITATIONS_ROLLOUT_1` follow-on handles.
- **Do NOT** retire the prompt-level anti-hallucination instruction — 7-day observation gate.
- **Do NOT** bump the `anthropic` SDK version — if current SDK doesn't support Citations schema, adapter degrades (empty citations); document in ship report. Bump is a separate brief.
- **Do NOT** migrate Baker's default model ID — this brief is model-agnostic.
- **Do NOT** add Citations to `/api/scan/image` (Anthropic Citations doesn't support images per 2026-04 release).
- **Do NOT** edit frontend (vanilla JS). Backend emits `__citations__` event; frontend parsing is separate `SCAN_CITATIONS_FRONTEND_1` follow-on.
- **Do NOT** touch `kbl/anthropic_client.py` (Step 5 path — unrelated).
- **Do NOT** refactor SSE stream machinery — insert citations emission at end-of-stream only.
- **Do NOT** touch `memory/store_back.py`, `invariant_checks/ledger_atomic.py`, `kbl/slug_registry.py`, `kbl/cache_telemetry.py` (B1's parallel brief).

## Timebox

**3.5–4h.** If >5.5h, stop and report — likely SDK-version incompatibility with Citations API schema. Fallback: degrade adapter to empty-citation mode + document in ship report + flag for SDK-bump follow-on.

**Working dir:** `~/bm-b3`.

---

**Dispatch timestamp:** 2026-04-24 post-PR-55-merge (Team 1, M0 quintet row 5 — coder slot)
**Team:** Team 1 — Meta/Persistence
**Parallel:** B1 running PROMPT_CACHE_AUDIT_1 (M0 row 4). Both touch `outputs/dashboard.py` `/api/scan`; merge-second rebases per charter §3.
**Sequence:** ENFORCEMENT_1 (#45) → GUARD_1 (#49) → LEDGER_ATOMIC_1 (#51) → KBL_SCHEMA_1 (#52) → MAC_MINI_WRITER_AUDIT_1 (#53) → KBL_INGEST_ENDPOINT_1 (#55) → **CITATIONS_API_SCAN_1 (this, closing M0 row 5)**.
