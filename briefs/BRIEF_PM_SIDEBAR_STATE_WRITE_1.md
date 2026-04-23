# BRIEF: PM_SIDEBAR_STATE_WRITE_1 — close the sidebar-door write loop + capture today

## Context

Phase 1 of the AO PM Continuity Program (ratified 2026-04-23, artefact `_ops/ideas/2026-04-23-ao-pm-continuity-program.md` commit `f9f07a4`).

On 2026-04-23 Director discovered that AO PM's "persistent memory" breaks on the dashboard sidebar — the highest-traffic door. v3 shipped 2026-04-22 with `update_pm_project_state` wired on 3 of 4 invocation paths; sidebar was the missing one. MOVIE AM (retrofit 2026-04-23 PR #47) inherited the same gap because the retrofit mirrored AO PM without an invocation-path audit.

**Anchor incident:** Director's live-use Aukera thread (conversation_memory ids 397-399, 2026-04-23) carries high-value facts (Patrick Zuckner warning, 1.5M release withdrawal, App 8 trophy pivot, 2.5M ask sequencing) — currently retrievable only via RAG; zero state extracted into `pm_project_state`. Without this brief, those facts remain invisible to AO PM tomorrow.

**Part H applicable:** this is the first brief to ship under Amendment H of `_ops/processes/capability-extension-template.md` (canonicalized 2026-04-23 commit `dcf1c4f`). Part H §H1–H5 are enforced inline — see §Part H Audit at the bottom.

---

## Estimated time: ~3-5h Code Brisen
## Complexity: Medium
## Prerequisites:
- Amendment H landed in `_ops/processes/capability-extension-template.md` ✓ (2026-04-23)
- Singleton hook `scripts/check_singletons.sh` green ✓
- Current baker-master main at `8c66bfa` (MOVIE_AM_RETROFIT_1 D1.7)

---

## Scope table

| Deliverable | What | Where |
|---|---|---|
| **D1** | Refactor `_auto_update_pm_state` into module-level public `extract_and_update_pm_state(...)` accepting `mutation_source` | `orchestrator/capability_runner.py` |
| **D2** | Sidebar post-stream state-write hook | `outputs/dashboard.py` in `_scan_chat_capability` fast-path + delegate-path |
| **D3** | Project labeling fix — sidebar conversations logged with `project=capability_slug` not `general` | `outputs/dashboard.py` |
| **D4** | `pm_backfill_processed` table (idempotency) + `scripts/backfill_pm_state.py` + one-off Render shell run | new table DDL in `memory/store_back.py` + new script |
| **D5** | Retroactive Part H §H1 audit of remaining 20 capabilities (read-only grep + appendix documentation) | `briefs/_reports/PART_H_CAPABILITY_AUDIT_20260423.md` |
| **D6** | Trigger 3 — relevance-on-ingest sentinel for meeting transcripts + Slack DM push on match | `triggers/fireflies_trigger.py`, `triggers/plaud_trigger.py`, `triggers/youtube_ingest.py`, new helper in `orchestrator/pm_signal_detector.py` |

---

## Fix/Feature 1: Refactor `_auto_update_pm_state` → module-level public function

### Problem

`CapabilityRunner._auto_update_pm_state` (`orchestrator/capability_runner.py:1640`) is a private method with hard-coded `mutation_source="opus_auto"` (line 1708). To reuse from the sidebar (D2) and backfill script (D4), we need a public entry point that accepts arbitrary `mutation_source`.

### Current State

`orchestrator/capability_runner.py:1640-1739` — `_auto_update_pm_state(self, pm_slug: str, question: str, answer: str)`. Hard-wired to `"opus_auto"`. Called once internally at line ~1570 inside `run_streaming` after Opus produces the answer.

### Implementation

**Step 1.1** — Add module-level function `extract_and_update_pm_state` to `orchestrator/capability_runner.py`, positioned immediately AFTER `PM_REGISTRY` definition (near line 186, before `extract_correction_from_feedback`):

```python
def extract_and_update_pm_state(
    pm_slug: str,
    question: str,
    answer: str,
    mutation_source: str = "auto",
    conversation_id: int | None = None,
) -> dict | None:
    """PM-FACTORY: Extract state + wiki insights from a Q/A pair and persist.

    Public entry point for sidebar state-write (mutation_source='sidebar'),
    backfill script (mutation_source='backfill_YYYY-MM-DD'), and capability
    runner (mutation_source='opus_auto'). Non-fatal — logs warning on any error.

    Args:
        pm_slug: capability slug in PM_REGISTRY (e.g. 'ao_pm', 'movie_am')
        question: Director's question (first 500 chars stored)
        answer: capability answer (first 3000 chars sent to extractor)
        mutation_source: audit tag — one of 'sidebar' / 'opus_auto' /
            'signal_<channel>' / 'cowork_mcp' / 'backfill_YYYY-MM-DD'
        conversation_id: optional pointer back to conversation_memory.id
            (used by backfill idempotency guard)

    Returns:
        dict of {updates, summary, wiki_insights_count} on success, None on failure.
    """
    import json as _json
    import anthropic as _anthropic
    from config import config

    cfg = PM_REGISTRY.get(pm_slug)
    if not cfg:
        return None

    try:
        extraction_files = cfg.get("extraction_view_files", [])
        view_file_list = ", ".join(extraction_files) if extraction_files else "view files"
        label = cfg.get("state_label", pm_slug)
        extraction_system = cfg.get(
            "extraction_system",
            f"Extract structured state updates AND wiki-worthy insights from "
            f"this {label} interaction. Return valid JSON only. No markdown fences."
        )
        state_schema = cfg.get(
            "extraction_state_schema",
            "State updates: {\"sub_matters\": {}, \"open_actions\": [], "
            "\"red_flags\": [], \"relationship_state\": {}, \"summary\": \"...\"}"
        )

        # Dedup context from existing helper — call via throwaway runner instance
        # (the helper is safe to call without full run_streaming state)
        _runner = CapabilityRunner()
        existing_context = _runner._get_extraction_dedup_context(pm_slug)

        claude = _anthropic.Anthropic(api_key=config.claude.api_key)
        resp = claude.messages.create(
            model="claude-opus-4-6",
            max_tokens=700,
            system=extraction_system,
            messages=[{"role": "user", "content": (
                f"Extract state updates from this {label} interaction.\n\n"
                f"Question: {question[:500]}\n\nAnswer: {answer[:3000]}\n\n"
                f"Return JSON with TWO sections:\n"
                f"1. {state_schema}\n"
                f"2. Wiki insights — facts or rules discovered that should become PERMANENT "
                f"knowledge in the view files. Only include if:\n"
                f"   - It's a confirmed fact, not speculation\n"
                f"   - It would be useful in future PM invocations\n"
                f"   - It's not already obvious from the question context\n"
                f"   - It's >50 characters (no trivial observations)\n\n"
                f"Confidence levels:\n"
                f"   - high = directly stated by Director OR confirmed by document\n"
                f"   - medium = inferred from Q&A pattern with supporting evidence\n"
                f"   - low = speculative or single-instance observation (will be dropped)\n\n"
                f"Available view files: {view_file_list}\n\n"
                f"{existing_context}"
                f"Return: {{\"sub_matters\": {{}}, \"open_actions\": [], \"red_flags\": [], "
                f"\"relationship_state\": {{}}, \"summary\": \"...\", "
                f"\"wiki_insights\": [{{\"insight\": \"...\", \"target_file\": \"...\", "
                f"\"target_section\": \"...\", \"confidence\": \"high|medium\"}}]}}\n"
                f"Return empty wiki_insights array if nothing wiki-worthy.\n"
                f"Only include fields with NEW information. Be concise."
            )}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:-1])
        updates = _json.loads(raw)

        wiki_insights = updates.pop("wiki_insights", [])
        summary = updates.pop("summary", f"{label} interaction")

        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        store.update_pm_project_state(
            pm_slug, updates, summary, question[:500],
            mutation_source=mutation_source,
        )
        logger.info(
            f"PM state ({pm_slug}) updated [{mutation_source}]: {summary[:80]}"
        )

        if wiki_insights and isinstance(wiki_insights, list):
            _runner._store_pending_insights(pm_slug, wiki_insights, question, summary)

        # Cross-PM signal propagation mirrors _auto_update_pm_state (line 1715-1736)
        import re as _re
        peer_pms = cfg.get("peer_pms", [])
        new_flags = updates.get("red_flags", [])
        if peer_pms and new_flags:
            signal_count = 0
            for peer in peer_pms:
                peer_kw = PM_REGISTRY.get(peer, {}).get("signal_keyword_patterns", [])
                for flag in new_flags:
                    if signal_count >= 3:
                        break
                    flag_str = str(flag)
                    for pattern in peer_kw:
                        if _re.search(pattern, flag_str, _re.IGNORECASE):
                            store.create_cross_pm_signal(
                                source_pm=pm_slug, target_pm=peer,
                                signal_type="red_flag",
                                signal_text=flag_str[:500],
                                context=f"Auto-detected from {label} state update",
                            )
                            signal_count += 1
                            break

        return {
            "updates": updates,
            "summary": summary,
            "wiki_insights_count": len(wiki_insights),
            "mutation_source": mutation_source,
        }
    except Exception as e:
        logger.debug(
            f"extract_and_update_pm_state failed [{pm_slug}][{mutation_source}]: {e}"
        )
        return None
```

**Step 1.2** — Retire the private method body. Replace `_auto_update_pm_state` (line 1640-1739) with a thin delegating wrapper:

```python
def _auto_update_pm_state(self, pm_slug: str, question: str, answer: str):
    """PM-FACTORY: Auto-update PM state after each run via Anthropic Opus.
    PM-KNOWLEDGE-ARCH-1: Also extract wiki-worthy insights for pending review.
    Delegates to extract_and_update_pm_state (module-level) with mutation_source='opus_auto'."""
    extract_and_update_pm_state(
        pm_slug=pm_slug, question=question, answer=answer,
        mutation_source="opus_auto",
    )
```

### Key Constraints

- **Cross-PM signal propagation MUST be preserved verbatim** — verified line-by-line against `capability_runner.py:1715-1736`. Losing this would silently break AO PM ↔ MOVIE AM red-flag signals.
- **`_get_extraction_dedup_context` + `_store_pending_insights`** are instance methods on `CapabilityRunner` — call via throwaway instance. Not worth extracting in this brief; keep scope narrow.
- **No model version change.** `claude-opus-4-6` stays — this brief does not touch model routing.

### Verification

```python
# Unit test: tests/test_pm_state_write.py
from orchestrator.capability_runner import extract_and_update_pm_state

def test_extract_and_update_pm_state_tags_mutation_source(monkeypatch):
    captured = {}
    class _FakeStore:
        def update_pm_project_state(self, pm_slug, updates, summary, question, mutation_source):
            captured["mutation_source"] = mutation_source
    # Patch SentinelStoreBack._get_global_instance + Anthropic call ...
    # Assert captured["mutation_source"] == "sidebar"
```

Ship gate requires this test + 2 more (see §Ship Gate).

---

## Fix/Feature 2: Sidebar post-stream state-write hook

### Problem

`_scan_chat_capability` (fast path, `outputs/dashboard.py:8088-8146`) logs capability_runs and extracts A8 tasks post-stream but never calls `update_pm_project_state`. Every sidebar interaction leaves state untouched. The delegate path (`outputs/dashboard.py:8150-8189`) has the same gap.

### Current State

- Fast path: post-stream hooks live at `dashboard.py:8088-8141` (capability_run log → baker_task update → A8 insight-to-task extraction).
- Delegate path: post-stream hooks at `dashboard.py:8164-8186` (capability_run log → baker_task update). No A8 extraction yet (out-of-scope — not changing).

### Implementation

**Step 2.1 — Fast path state-write.** Add a fire-and-forget state-write thread after the capability_run log (insert immediately after line 8121, i.e. after the `except Exception as _e: logger.warning(f"Capability run logging failed (non-fatal): {_e}")` block, BEFORE the A8 block at line 8123):

```python
            # PM-SIDEBAR-STATE-WRITE-1: fire-and-forget PM state extraction
            # for client_pm capabilities. Mirrors capability_runner's Opus-based
            # pattern with mutation_source='sidebar' for audit trail.
            if ar and ar.answer and cap.slug in PM_REGISTRY:
                def _sidebar_state_write():
                    try:
                        from orchestrator.capability_runner import (
                            extract_and_update_pm_state,
                        )
                        extract_and_update_pm_state(
                            pm_slug=cap.slug,
                            question=req.question,
                            answer=ar.answer,
                            mutation_source="sidebar",
                        )
                    except Exception as _e:
                        logger.warning(
                            f"Sidebar state-write failed [{cap.slug}] (non-fatal): {_e}"
                        )

                import threading as _threading
                _threading.Thread(target=_sidebar_state_write, daemon=True).start()
```

**Step 2.2 — Delegate path state-write.** Inside `_delegate_stream` (around `dashboard.py:8184`), after the `store.update_baker_task` call and before `yield "data: [DONE]\n\n"`:

```python
            # PM-SIDEBAR-STATE-WRITE-1: fire state-write for each client_pm
            # capability referenced by the decomposer's plan.
            try:
                pm_slugs_in_plan = [
                    s for s in cap_slugs if s in PM_REGISTRY
                ]
                if result and result.answer and pm_slugs_in_plan:
                    def _delegate_state_write():
                        try:
                            from orchestrator.capability_runner import (
                                extract_and_update_pm_state,
                            )
                            for _slug in pm_slugs_in_plan:
                                extract_and_update_pm_state(
                                    pm_slug=_slug,
                                    question=req.question,
                                    answer=result.answer,
                                    mutation_source="decomposer",
                                )
                        except Exception as _e:
                            logger.warning(
                                f"Delegate state-write failed (non-fatal): {_e}"
                            )
                    import threading as _threading
                    _threading.Thread(target=_delegate_state_write, daemon=True).start()
            except Exception:
                pass
```

**Step 2.3 — Add `PM_REGISTRY` import at top of `dashboard.py`.** Check first (may already exist):

```bash
grep -n "from orchestrator.capability_runner import" outputs/dashboard.py
```

If `PM_REGISTRY` not imported, add it to an existing import line or create:

```python
from orchestrator.capability_runner import PM_REGISTRY  # PM-SIDEBAR-STATE-WRITE-1
```

### Key Constraints

- **Fire-and-forget via `threading.Thread(daemon=True)`.** Do NOT block the SSE stream completion on Opus extraction (~3-5s latency).
- **Only trigger on `cap.slug in PM_REGISTRY`.** Other capabilities (finance, legal, etc.) are Pattern-2 domain/meta, not client_pm — out of D2 scope. Part H §H2 marks them read-only-intentional (see §D5 audit).
- **Delegate path uses `mutation_source='decomposer'`** per Amendment H §H4 tag allocation — NOT `'sidebar'`, because the decomposer is a distinct surface even though invoked from the same dashboard route.
- **`req.question` must survive beyond stream completion** — Python closure over the outer scope handles this; don't mutate req.

### Verification

Add to `tests/test_pm_state_write.py`:

```python
def test_sidebar_hook_fires_on_ao_pm(monkeypatch):
    # Build fake AgentResult with ar.answer, cap.slug='ao_pm'
    # Patch extract_and_update_pm_state; assert called once with mutation_source='sidebar'
    ...

def test_sidebar_hook_skipped_for_non_pm_capability(monkeypatch):
    # cap.slug='finance' (not in PM_REGISTRY)
    # Assert extract_and_update_pm_state NOT called
    ...
```

---

## Fix/Feature 3: Project labeling fix

### Problem

Sidebar conversations log to `conversation_memory` with `project='general'` (verified 2026-04-23 via `SELECT DISTINCT project FROM conversation_memory WHERE created_at > NOW() - INTERVAL '14 days'` → all 13 rows `'general'`). This makes the backfill extractor (D4) unable to filter AO PM conversations from other sidebar traffic without content-heuristic matching.

### Current State

`outputs/dashboard.py:7946` — `project=req.project or "general"` inside the main scan flow. `SpecialistScanRequest` (`dashboard.py:280-283`) does not have a `project` field — only `question / capability_slug / history`. When a SpecialistScanRequest is converted to ScanRequest at line 5490, `project` is left unset → falls through to `"general"` at 7946.

### Implementation

**Step 3.1** — Inside `_scan_chat_capability` (`dashboard.py:7988`), right after `cap_slugs = [c.slug for c in plan.capabilities]` (line 8012), set `req.project` when the single-capability fast path resolves to a `client_pm` routed plan:

```python
    # PM-SIDEBAR-STATE-WRITE-1 D3: tag conversation_memory with capability_slug
    # for fast-path routing (so backfill + queries can isolate PM-specific history).
    if (plan.mode == "fast" and len(plan.capabilities) == 1
            and plan.capabilities[0].slug in PM_REGISTRY):
        try:
            req.project = plan.capabilities[0].slug
        except Exception:
            # ScanRequest is pydantic — mutation allowed; SpecialistScanRequest may not be.
            pass
    elif plan.mode == "delegate":
        # Delegate path: tag with comma-joined PM slugs (primary for filter).
        _pm_in_plan = [s for s in cap_slugs if s in PM_REGISTRY]
        if _pm_in_plan:
            try:
                req.project = _pm_in_plan[0]
            except Exception:
                pass
```

**Step 3.2** — Verify `ScanRequest` model at `dashboard.py:242-247` accepts mutation:

```bash
python3 -c "from outputs.dashboard import ScanRequest; r = ScanRequest(question='x'); r.project='ao_pm'; print(r.project)"
# expected: ao_pm
```

Pydantic v2 allows mutation by default. If strict mode turns out to be set, use `setattr(req, 'project', cap.slug)` with `model_config = ConfigDict(frozen=False)`.

### Key Constraints

- **Don't break existing callers.** The `/scan` endpoint uses ScanRequest and passes `req.project` downstream to FTS / RAG. If we overwrite, verify existing behavior is preserved. Grep check:
  ```bash
  grep -n "req.project\|req\.project" outputs/dashboard.py | head -20
  ```
- **Only set when routing resolves to `PM_REGISTRY`.** Otherwise leave `'general'` (existing behavior).
- **SpecialistScanRequest path** (5490) creates a ScanRequest from `req.question` only — no `project` field on source. After conversion to ScanRequest, the mutation in Step 3.1 covers it.

### Verification

```sql
-- After deploy + 1 test scan via AO PM:
SELECT id, created_at, project, LEFT(question, 50) AS q
FROM conversation_memory
WHERE created_at > NOW() - INTERVAL '10 minutes'
ORDER BY created_at DESC LIMIT 5;
-- expected: project='ao_pm' for PM-routed scans
```

---

## Fix/Feature 4: 14-day backfill + idempotency table

### Problem

§3 anchor incident: conversation_memory ids 397-399 (Aukera thread, 2026-04-23) contain high-value AO PM facts but zero state was extracted. Same for 12 other recent sidebar conversations. Without backfill, AO PM's memory starts fresh the day D2 deploys.

### Current State

- No `question_hash` column on `conversation_memory` or `pm_state_history` (verified 2026-04-23 via `information_schema.columns`).
- No existing backfill script for PM state extraction.
- `conversation_memory` row count (14 days): 13 — all `project='general'`. Realistic cost estimate: ~$0.02/conversation × 13 = ~$0.26 one-off at current density.

### Implementation

**Step 4.1 — Add idempotency table DDL to `memory/store_back.py`.**

Mirror `_ensure_ai_head_audits_table` / `_ensure_scheduler_executions_table` pattern. Insert adjacent to those (near `store_back.py:544`). New method:

```python
def _ensure_pm_backfill_processed_table(self):
    """Idempotency guard for scripts/backfill_pm_state.py.
    Tracks which (pm_slug, conversation_id) pairs have been processed so
    repeat runs of the backfill script are no-ops.
    """
    conn = self._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pm_backfill_processed (
                pm_slug TEXT NOT NULL,
                conversation_id INTEGER NOT NULL,
                processed_at TIMESTAMPTZ DEFAULT NOW(),
                mutation_source TEXT,
                PRIMARY KEY (pm_slug, conversation_id)
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_pm_backfill_processed_pm "
            "ON pm_backfill_processed(pm_slug)"
        )
        conn.commit()
        cur.close()
        logger.info("pm_backfill_processed table verified")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"Could not ensure pm_backfill_processed table: {e}")
    finally:
        self._put_conn(conn)
```

Wire into `__init__` adjacent to the existing table-ensure calls (around `store_back.py:151` — see `_ensure_scheduler_executions_table()`).

**Step 4.2 — Write `scripts/backfill_pm_state.py`.**

```python
"""Backfill PM state from recent conversation_memory history.

Iterates over conversation_memory rows in a rolling window and runs the
same Opus extraction that the sidebar hook (D2) runs on live scans. Writes
to pm_project_state with mutation_source='backfill_YYYY-MM-DD'. Idempotent
via pm_backfill_processed (pm_slug, conversation_id) PK.

Usage: python3 scripts/backfill_pm_state.py <pm_slug> [--since 14d]
Requires: DATABASE_URL env var.
"""
import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_pm_state")


def _parse_since(since: str) -> str:
    m = re.match(r"^(\d+)d$", since)
    if not m:
        raise ValueError(f"--since must be Nd (e.g. 14d); got {since}")
    return m.group(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pm_slug", help="e.g. ao_pm, movie_am")
    ap.add_argument("--since", default="14d",
                    help="lookback window, Nd format (default 14d)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print matched rows without extracting")
    args = ap.parse_args()

    days = _parse_since(args.since)
    from orchestrator.capability_runner import PM_REGISTRY, extract_and_update_pm_state
    if args.pm_slug not in PM_REGISTRY:
        raise SystemExit(f"Unknown pm_slug: {args.pm_slug}")

    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        raise SystemExit("DB connection unavailable")

    cur = None
    try:
        cur = conn.cursor()

        # Build match set. Primary: conversation_memory.project matches pm_slug
        # (post-D3 deploy). Fallback: heuristic regex over question for recent
        # rows labeled 'general' (pre-D3 bug).
        cfg = PM_REGISTRY[args.pm_slug]
        orbit = cfg.get("signal_orbit_patterns", [])
        keyword = cfg.get("signal_keyword_patterns", [])
        patterns = orbit + keyword
        regex_alt = "|".join(f"({p})" for p in patterns) if patterns else None

        # Lookback window
        cur.execute(f"""
            SELECT id, question, answer, project, created_at
            FROM conversation_memory
            WHERE created_at > NOW() - INTERVAL '{int(days)} days'
              AND answer IS NOT NULL
              AND LENGTH(answer) > 100
            ORDER BY created_at ASC
            LIMIT 500
        """)
        rows = cur.fetchall()

        # Already-processed guard
        cur.execute(
            "SELECT conversation_id FROM pm_backfill_processed "
            "WHERE pm_slug = %s",
            (args.pm_slug,)
        )
        processed_ids = {r[0] for r in cur.fetchall()}

        tag = f"backfill_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        matched = 0
        skipped = 0
        extracted = 0

        for row_id, question, answer, project, created_at in rows:
            if row_id in processed_ids:
                skipped += 1
                continue

            # Match logic: project match OR regex match on question
            is_match = False
            if project == args.pm_slug:
                is_match = True
            elif regex_alt:
                combined = f"{question or ''} {(answer or '')[:500]}"
                try:
                    if re.search(regex_alt, combined, re.IGNORECASE):
                        is_match = True
                except re.error as _re_e:
                    logger.warning(f"regex failed for {args.pm_slug}: {_re_e}")

            if not is_match:
                continue

            matched += 1
            if args.dry_run:
                logger.info(f"DRY-RUN match: conv#{row_id} [{created_at}] {question[:80]}")
                continue

            result = extract_and_update_pm_state(
                pm_slug=args.pm_slug,
                question=question or "",
                answer=answer or "",
                mutation_source=tag,
                conversation_id=row_id,
            )
            if result:
                extracted += 1
                cur.execute("""
                    INSERT INTO pm_backfill_processed
                        (pm_slug, conversation_id, mutation_source)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (pm_slug, conversation_id) DO NOTHING
                """, (args.pm_slug, row_id, tag))
                conn.commit()
                logger.info(
                    f"Extracted conv#{row_id} → {args.pm_slug} "
                    f"(summary: {result['summary'][:60]})"
                )
            else:
                logger.warning(f"Extract returned None for conv#{row_id} — not recorded as processed")

        logger.info(
            f"Backfill done [{args.pm_slug}][{args.since}]: "
            f"scanned {len(rows)}, matched {matched}, "
            f"skipped-already-processed {skipped}, extracted {extracted}"
        )
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"Backfill failed: {e}")
        raise
    finally:
        if cur:
            cur.close()
        store._put_conn(conn)


if __name__ == "__main__":
    main()
```

**Step 4.3 — Post-merge run (AI Head executes).** On AI Head's working tree AFTER PR merges:

```bash
cd ~/Desktop/baker-code && git pull --rebase origin main  # MANDATORY per SKILL.md Rule 9
source /tmp/bv312/bin/activate  # or equivalent venv with deps
export DATABASE_URL=$(op item get t77jpmwqxwlm2x32jhcup7vjie --vault "Baker API Keys" --fields credential --reveal)
python scripts/backfill_pm_state.py ao_pm --since 14d --dry-run  # inspect
python scripts/backfill_pm_state.py ao_pm --since 14d            # commit
python scripts/backfill_pm_state.py movie_am --since 14d
```

### Key Constraints

- **Idempotency via PK, not hash.** `(pm_slug, conversation_id)` with `ON CONFLICT DO NOTHING`. No question-hash column needed.
- **Bounded query with LIMIT 500.** Even 30 days of sidebar traffic fits comfortably.
- **`LENGTH(answer) > 100`** guard — skip short/empty answers (auto-routed failures etc.).
- **Regex fallback for pre-D3 rows** (all 13 rows currently labeled `general`). Uses the PM's existing `signal_orbit_patterns + signal_keyword_patterns` — no new regex to maintain.
- **`conn.rollback()` in except** — mandatory per `.claude/rules/python-backend.md`.
- **Cost cap:** Opus extraction ~$0.02 × ~50 est. matched rows = ~$1. Director's Q4 ratification budgeted $1-2.

### Verification

```sql
-- After backfill:
SELECT pm_slug, COUNT(*) AS processed, MAX(processed_at) AS newest
FROM pm_backfill_processed
WHERE pm_slug IN ('ao_pm','movie_am')
GROUP BY pm_slug;
-- expected: ao_pm ~5-15, movie_am ~1-5

-- State mutations tagged backfill_*:
SELECT pm_slug, mutation_source, COUNT(*)
FROM pm_state_history
WHERE mutation_source LIKE 'backfill_%'
GROUP BY pm_slug, mutation_source;
-- expected: rows per pm_slug with backfill_YYYY-MM-DD tag

-- Re-run idempotency check (run backfill a second time):
-- expected log: "skipped-already-processed N" where N == prior extracted count
```

---

## Fix/Feature 5: Retroactive Part H §H1 audit of remaining 20 capabilities

### Problem

Amendment H §H1 requires invocation-path enumeration for every Pattern-2 capability (client_pm + domain + meta). 22 capabilities exist; AO PM and MOVIE AM are fixed by D1–D4. The remaining 20 need the audit to confirm their read-only-intentional status (or discover another silent gap).

### Current State

Director's Q3 ratification: fold into this brief. Scope is read-only — a grep pass + appendix documenting each capability's surfaces.

### Implementation

**Step 5.1 — Run audit.** For each capability slug (enumerate from `SELECT slug FROM capability_sets ORDER BY slug`), run:

```bash
grep -rn "\"<slug>\"\|'<slug>'" orchestrator/ outputs/ triggers/ memory/ --include="*.py" \
    | grep -v "_test\|_archive\|briefs/" \
    | head -50
```

Classify each hit by surface type (sidebar / decomposer / signal / cortex / other) and record write-state (yes/no/n/a).

**Step 5.2 — Write appendix report.** Create `briefs/_reports/PART_H_CAPABILITY_AUDIT_20260423.md`:

```markdown
# Part H §H1 Audit — 22 capabilities — 2026-04-23

## Summary
- **2 capabilities with live GAP (now fixed):** ao_pm, movie_am (D1–D4 in this brief)
- **20 capabilities read-only-intentional:** documented below with reason

## Per-capability matrix

| Slug | Type | Callers | Writes `update_pm_project_state`? | Read-only-intentional reason |
|---|---|---|---|---|
| ao_pm | client_pm | capability_runner, agent, pm_signal_detector, dashboard (new via D2) | ✅ (post-D2) | — |
| movie_am | client_pm | capability_runner, agent, pm_signal_detector, dashboard (new via D2) | ✅ (post-D2) | — |
| finance | domain | capability_runner, decomposer | ❌ | Domain capability, no `pm_project_state` row — reference-only per PM_REGISTRY design |
| legal | domain | ... | ❌ | Same as finance |
| it | domain | ... | ❌ | Same as finance |
| tax_* (8 slugs) | domain | ... | ❌ | Domain capabilities — reference-only |
| decomposer | meta | agent.py orchestration | ❌ | Meta capability — routes other caps, holds no state |
| synthesizer | meta | agent.py output merging | ❌ | Meta capability — aggregates output, holds no state |
| profiling | meta | ... | ❌ | Meta capability — document assembly only |
| ... | ... | ... | ... | ... |
```

**Step 5.3 — Acceptance criteria.** Report must:
- Cover all 22 slugs from `capability_sets`
- For each: file:line of primary caller(s) verified by `grep -n`
- No capability listed without a read-state column filled

### Key Constraints

- **Read-only pass.** No code changes in D5. If the audit discovers another gap, it spawns a follow-up brief — not scope of this one.
- **Commit the report alongside the PR.** Ensures auditability of the Part H compliance claim.

---

## Fix/Feature 6: Trigger 3 — relevance-on-ingest sentinel

### Problem

`pm_signal_detector.detect_relevant_pms_meeting` (`orchestrator/pm_signal_detector.py:80-97`) exists but has NO caller. Meeting transcripts (Fireflies / Plaud / YouTube) ingest into `meeting_transcripts` without triggering PM state updates. Director's Q5 ratification: ship with Phase 1.

Additionally, `flag_pm_signal` (line 118) currently writes to `pm_project_state` but does NOT push to Slack substrate. Per ratified surface architecture (2026-04-20), proactive PM signals should surface to Director in real time via Slack DM.

### Current State

- `detect_relevant_pms_meeting(title, participants)` — requires BOTH orbit AND keyword match (high-confidence only). Exists at `pm_signal_detector.py:80`.
- `flag_pm_signal(pm_slug, channel, source, summary, timestamp)` — updates `pm_project_state.relationship_state`, emits `mutation_source=f"pm_signal_{channel}"`. Exists at `pm_signal_detector.py:118`.
- Meeting ingest call sites (verified 2026-04-23):
  - `triggers/fireflies_trigger.py` — Fireflies poller (**3 `store_meeting_transcript` call sites: lines 330, 513, 609** — all 3 need the wiring)
  - `triggers/plaud_trigger.py` — Plaud poller (**2 `store_meeting_transcript` call sites: lines 350, 519** — both need the wiring)
  - `triggers/youtube_ingest.py:223` — YouTube ingestion endpoint (1 call site)
- **None of the 6 call sites currently call `detect_relevant_pms_meeting`.**
- `outputs/slack_notifier.py` — existing Slack MCP helper module.

### Implementation

**Step 6.1 — Add Slack push to `flag_pm_signal`.** Extend `pm_signal_detector.py:118-144` to optionally push a Director DM on match for the `meeting` channel (ingest-relevance trigger only — email + WhatsApp already have their own high-signal paths and we don't want to flood Slack):

```python
def flag_pm_signal(
    pm_slug: str, channel: str, source: str, summary: str,
    timestamp=None, push_slack: bool = False,
):
    """Update pm_project_state with an inbound signal. Non-fatal.

    Args:
        push_slack: if True, also push a DM to Director's Slack
            (channel D0AFY28N030). Default False to preserve existing
            email/whatsapp signal flow volume; only new meeting-ingest
            wiring passes True.
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()

        signal_data = {
            "relationship_state": {
                "last_inbound_channel": channel,
                "last_inbound_from": source[:200],
                "last_inbound_summary": summary[:300],
            }
        }
        if timestamp:
            signal_data["relationship_state"]["last_inbound_at"] = (
                timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
            )

        store.update_pm_project_state(
            pm_slug,
            updates=signal_data,
            summary=f"PM signal [{channel}]: {source} — {summary[:100]}",
            mutation_source=f"pm_signal_{channel}",
        )
        logger.info(f"PM signal flagged [{pm_slug}][{channel}]: {source}")

        if push_slack:
            try:
                from outputs.slack_notifier import post_to_channel
                label = pm_slug.upper().replace("_", " ")
                text = (
                    f"*{label}*: new {channel} ingest relevant to active thread.\n"
                    f"Source: {source[:160]}\n"
                    f"Summary: {summary[:280]}"
                )
                post_to_channel(channel_id="D0AFY28N030", text=text)
            except Exception as _slack_e:
                logger.warning(
                    f"PM signal Slack push failed [{pm_slug}][{channel}]: {_slack_e}"
                )
    except Exception as e:
        logger.warning(f"PM signal flag failed [{pm_slug}]: {e}")
```

**Step 6.2 — Wire fireflies_trigger.py.** Grep for the Fireflies ingest completion point:

```bash
grep -n "store_meeting_transcript\|meeting_transcripts" triggers/fireflies_trigger.py
```

Immediately after the successful `store_meeting_transcript(...)` call, add:

```python
# PM-SIDEBAR-STATE-WRITE-1 D6: relevance-on-ingest sentinel.
try:
    from orchestrator.pm_signal_detector import (
        detect_relevant_pms_meeting, flag_pm_signal,
    )
    _matched = detect_relevant_pms_meeting(
        title=title or "", participants=participants or "",
    )
    for _pm_slug in _matched:
        flag_pm_signal(
            _pm_slug, "meeting",
            source=f"fireflies: {title[:120]}",
            summary=(summary or "")[:280],
            push_slack=True,
        )
except Exception as _pm_e:
    logger.debug(f"meeting signal detection failed (non-fatal): {_pm_e}")
```

**Step 6.3 — Wire plaud_trigger.py.** Same block, inserted after BOTH `store_meeting_transcript(...)` calls in the Plaud poller (`triggers/plaud_trigger.py:350` primary poll + `:519` PG-only backfill path). Adapt variable names to Plaud's local scope. Note: the `:519` backfill path is explicitly tagged "no pipeline.run(), no LLM (Lesson #25)" — our signal detection is regex-only and non-LLM, so it is safe to add there.

**Step 6.4 — Wire fireflies_trigger.py (all 3 call sites).** The Fireflies trigger has 3 `store.store_meeting_transcript(...)` calls at lines 330, 513, 609. Each one must be followed by the signal-detection block. Do NOT skip any — Fireflies webhooks + polling + manual ingest all converge on `store_meeting_transcript` but via different routes, and each route can be the path through which a MO/AO-relevant transcript arrives.

**Step 6.5 — Wire youtube_ingest.py.** Same block, inserted after the YouTube `store_meeting_transcript(...)` call at `triggers/youtube_ingest.py:223`. YouTube ingestion is on-demand via HTTP endpoint — signal fires once per ingest.

**Step 6.6 — `post_to_channel` helper verified present.** `outputs/slack_notifier.py:111` — `def post_to_channel(channel_id: str, text: str) -> bool` exists (shipped by BRIEF_AI_HEAD_WEEKLY_AUDIT_1, PR #44). Reuse — no new helper.

### Key Constraints

- **`push_slack=True` only on meeting channel.** Email + WhatsApp already have high-volume flows; flipping push_slack universally would spam Director. Scoped to meeting ingest per Director's Q5 ratification (Trigger 3).
- **Non-fatal everywhere.** Signal detection failure must not break meeting ingest.
- **`detect_relevant_pms_meeting` requires BOTH orbit AND keyword** — already enforced (line 94). Do not loosen; low-context short titles have high false-positive risk.
- **Slack DM channel D0AFY28N030** — Director's personal DM, same channel used by `ai_head_weekly_audit` + `ai_head_audit_sentinel` (canonical per AUDIT_SENTINEL_1). Do not introduce a new channel.
- **Existing email + WhatsApp signal detection code at `triggers/email_trigger.py:865-869` + `triggers/waha_webhook.py:906-907,962-964,1074-1076` — DO NOT modify.** They already call `flag_pm_signal` without `push_slack`, which stays the default behavior.

### Verification

```sql
-- After a Fireflies transcript containing 'Pohanis' or 'AO' ingests:
SELECT pm_slug, mutation_source, last_run_at,
       (state_json->'relationship_state'->>'last_inbound_summary') AS last_summary
FROM pm_project_state
WHERE pm_slug = 'ao_pm'
ORDER BY last_run_at DESC LIMIT 3;
-- expected: mutation_source='pm_signal_meeting', last_inbound_summary mentions Pohanis
```

Slack DM verification (manual): confirm the DM lands in D0AFY28N030 within 2 minutes of a matching meeting ingest.

---

## Files Modified

- `orchestrator/capability_runner.py` — extract `_auto_update_pm_state` to module-level `extract_and_update_pm_state` (D1)
- `outputs/dashboard.py` — fast-path + delegate-path state-write hooks (D2), project labeling fix (D3)
- `memory/store_back.py` — new `_ensure_pm_backfill_processed_table` + `__init__` wiring (D4.1)
- `scripts/backfill_pm_state.py` — NEW (D4.2)
- `orchestrator/pm_signal_detector.py` — `push_slack` parameter on `flag_pm_signal` (D6.1)
- `triggers/fireflies_trigger.py`, `triggers/plaud_trigger.py`, `triggers/youtube_ingest.py` — `detect_relevant_pms_meeting + flag_pm_signal(push_slack=True)` wiring (D6.2-D6.4)
- `outputs/slack_notifier.py` — `post_to_channel` helper if missing (D6.5)
- `tests/test_pm_state_write.py` — NEW, 5-7 tests (see §Ship Gate)
- `briefs/_reports/PART_H_CAPABILITY_AUDIT_20260423.md` — NEW (D5)

## Do NOT Touch

- `triggers/email_trigger.py:865-869` — existing PM signal flow for email, already wired, `push_slack=False` stays default
- `triggers/waha_webhook.py:906-907, 962-964, 1074-1076` — existing WhatsApp signal flow, same
- `orchestrator/capability_runner.py:1640-1739` `_auto_update_pm_state` CROSS-PM-SIGNALS block (1715-1736) — preserved verbatim in D1 refactor
- `PM_REGISTRY` schema — no field additions; all wiring uses existing `signal_orbit_patterns` + `signal_keyword_patterns`
- `pm_state_history` table schema — no new columns
- `conversation_memory` table schema — no new columns (project fix is app-layer, not DDL)
- `capability_sets` table — no modifications
- Model routing (`claude-opus-4-6` stays) — not changing

## Ship Gate

Literal `pytest` output, no "by inspection":

```
$ python3 -c "import py_compile; \
  py_compile.compile('orchestrator/capability_runner.py', doraise=True); \
  py_compile.compile('outputs/dashboard.py', doraise=True); \
  py_compile.compile('memory/store_back.py', doraise=True); \
  py_compile.compile('scripts/backfill_pm_state.py', doraise=True); \
  py_compile.compile('orchestrator/pm_signal_detector.py', doraise=True); \
  py_compile.compile('triggers/fireflies_trigger.py', doraise=True); \
  py_compile.compile('triggers/plaud_trigger.py', doraise=True); \
  py_compile.compile('triggers/youtube_ingest.py', doraise=True); \
  print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ python3 -m pytest tests/test_pm_state_write.py -v
# expected ≥5 passes:
#  test_extract_and_update_pm_state_tags_mutation_source
#  test_sidebar_hook_fires_on_ao_pm
#  test_sidebar_hook_skipped_for_non_pm_capability
#  test_backfill_idempotency_skips_processed_rows
#  test_flag_pm_signal_push_slack_only_when_requested
```

Full-suite delta check (AUDIT_SENTINEL_1 pattern):

```
$ python3 -m pytest 2>&1 | tail -3
# expected: branch passes = main passes + N (where N = new tests added)
#           branch failures == main failures (no regressions)
```

## Quality Checkpoints

1. `scripts/check_singletons.sh` green — every new `SentinelStoreBack` instantiation uses `_get_global_instance()`
2. `conn.rollback()` in every `except` that touches `conn` in `backfill_pm_state.py` + `_ensure_pm_backfill_processed_table`
3. Sidebar hook is fire-and-forget — SSE `[DONE]` yielded BEFORE extraction completes (verify via test ordering)
4. `mutation_source` tags match Amendment H §H4 canonical set (`sidebar` / `decomposer` / `opus_auto` / `signal_meeting` / `backfill_YYYY-MM-DD`)
5. Delegate path uses `'decomposer'` not `'sidebar'` (distinct surface per §H4)
6. `push_slack=True` only on meeting channel wiring; email + WhatsApp existing calls unchanged
7. `detect_relevant_pms_meeting` BOTH-orbit-AND-keyword gate preserved (no loosening)
8. Part H §H1 audit report covers all 22 capabilities (`SELECT COUNT(*) FROM capability_sets` → audit row count must match)
9. Ship-gate test count ≥ 5 with literal pass output

## Verification SQL (post-deploy + backfill)

```sql
-- QC A: Sidebar state-write confirmed live
SELECT pm_slug, mutation_source, COUNT(*) AS hits, MAX(created_at) AS newest
FROM pm_state_history
WHERE mutation_source IN ('sidebar', 'decomposer')
  AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY pm_slug, mutation_source;
-- expected: ≥1 row per active PM after a test scan

-- QC B: Project labeling fix confirmed
SELECT project, COUNT(*)
FROM conversation_memory
WHERE created_at > NOW() - INTERVAL '24 hours'
  AND project IN ('ao_pm', 'movie_am')
GROUP BY project;
-- expected: ≥1 row per PM that received a sidebar scan

-- QC C: Backfill captured historical rows
SELECT pm_slug, COUNT(*) AS backfilled, MAX(processed_at) AS newest
FROM pm_backfill_processed
GROUP BY pm_slug;
-- expected: ao_pm ≥ 5 (Aukera thread + others), movie_am ≥ 1

-- QC D: Backfill produced state_history entries
SELECT pm_slug, mutation_source, COUNT(*)
FROM pm_state_history
WHERE mutation_source LIKE 'backfill_%'
GROUP BY pm_slug, mutation_source;
-- expected: matches QC C counts

-- QC E: Trigger 3 fires on meeting ingest
SELECT pm_slug, mutation_source, last_run_at
FROM pm_project_state
WHERE pm_slug IN ('ao_pm','movie_am')
  AND last_run_at > NOW() - INTERVAL '24 hours'
  AND (state_json->'relationship_state'->>'last_inbound_channel') = 'meeting';
-- expected: rows after next matching Fireflies/Plaud ingest
```

---

## Part H §H1–H5 Audit (MANDATORY — this brief modifies ao_pm + movie_am, both client_pm)

### §H1 — Invocation path enumeration (`ao_pm`, `movie_am`)

```bash
$ grep -rn "ao_pm\|movie_am" orchestrator/ outputs/ triggers/ memory/ \
    --include="*.py" | grep -v "_test\|_archive"
```

| file:line | Entry function | Surface | Reads state? | Writes state? |
|---|---|---|---|---|
| `orchestrator/capability_runner.py:1640` (pre-D1) / `orchestrator/capability_runner.py:~186` (post-D1) | `_auto_update_pm_state` / `extract_and_update_pm_state` | capability_runner Opus loop | full | yes (`opus_auto`) |
| `orchestrator/agent.py:2031` | `run_agent_loop` | decomposer-driven agent | full | yes |
| `orchestrator/pm_signal_detector.py:136` | `flag_pm_signal` | signal detector | partial (relationship_state only) | yes (`pm_signal_<channel>`) |
| `outputs/dashboard.py:8088` (pre-D2) → `:8122` (post-D2) | `_scan_chat_capability` fast-path | sidebar | full (via runner.run_streaming) | **yes (post-D2, `sidebar`)** |
| `outputs/dashboard.py:8150` (pre-D2) → `:8186` (post-D2) | `_scan_chat_capability` delegate-path | decomposer-multi | full | **yes (post-D2, `decomposer`)** |
| `scripts/backfill_pm_state.py` (NEW) | `main` | one-off Opus replay | read-only from conversation_memory | yes (`backfill_YYYY-MM-DD`) |

### §H2 — Write-path closure verified

Post-D2: every meaningful-interaction caller writes. No read-only-intentional exceptions for `ao_pm`/`movie_am`.

### §H3 — Read-path completeness

- Fast path + delegate path: read all 3 layers via `CapabilityRunner.run_streaming` (Layer 1 from `pm_project_state`, Layer 2 from `extraction_view_files` via `_resolve_view_dir`, Layer 3 via Qdrant retrieval chunks). Existing behavior, unchanged.
- Signal detector path: Layer 1 partial (reads + updates `relationship_state` only — intentional; signal detection is lightweight).
- Backfill: Layer 3 only (reads `conversation_memory`); does not need Layer 1/2 (it's replaying historical Q/A, not generating new answers).

### §H4 — `mutation_source` tag allocation

| Surface | Tag |
|---|---|
| Sidebar fast-path | `sidebar` |
| Sidebar delegate-path | `decomposer` |
| Capability runner internal | `opus_auto` (unchanged) |
| Signal detector email | `pm_signal_email` (unchanged) |
| Signal detector WhatsApp | `pm_signal_whatsapp`, `pm_signal_whatsapp_outbound` (unchanged) |
| Signal detector meeting (NEW via D6) | `pm_signal_meeting` |
| Backfill script | `backfill_YYYY-MM-DD` |

### §H5 — Cross-surface continuity acceptance test

> *Fact F posted via sidebar at time T → query via decomposer at T+5min → assert F surfaces in the decomposer response.*

Test:
1. Via sidebar, ask AO PM: *"Patrick Zuckner warned that a release request would trigger a trust-level review; confirm stored."*
2. After SSE `[DONE]`, assert `pm_state_history` has a fresh row with `pm_slug='ao_pm'` and `mutation_source='sidebar'` (SQL: see QC A above).
3. 5+ minutes later, query via the decomposer: *"What are the latest open concerns on the Aukera thread?"*
4. Decomposer loads `pm_project_state.state_json.red_flags` or `relationship_state` and surfaces the Patrick warning. Pass if surfaced; fail if not.

Automatable subset: (1)(2)(4) coverable in `tests/test_pm_state_write.py::test_cross_surface_continuity_via_decomposer`. Step (3) is the natural 5-minute cache-window; unit test compresses to 0s.

---

## Prerequisites / coordination

- **Merged:** AI Head folds Amendment H into `_ops/processes/capability-extension-template.md` + `_ops/skills/ai-head/SKILL.md` (Action 1, baker-vault commit `dcf1c4f`, 2026-04-23) ✓
- **Orthogonal / non-blocking:** GUARD_1 (meta team), KBL_SCHEMA_1 (meta team), Cortex-3T pre-mortem — no shared files or schemas
- **Phase 2 (BRIEF_CAPABILITY_THREADS_1) gate:** this brief's D2 (sidebar write-path) is the thread stitch anchor; authoring of Phase 2 brief begins only after this PR merges

## Post-merge sequence (AI Head executes per standing auth)

1. Merge PR on B2 APPROVE + green ship gate (Tier A)
2. Wait for Render deploy live
3. Verify `Registered:` log lines unaffected; verify no new warnings
4. Run backfill locally per Step 4.3: `python scripts/backfill_pm_state.py ao_pm --since 14d --dry-run` → inspect → real run → `movie_am` same
5. Run QC A–E SQL
6. Run Part H §H5 acceptance test manually (sidebar scan → 5-min wait → decomposer query)
7. Push Slack substrate summary to Director with backfill row counts + QC results
8. Append closeout to `SCRATCH_MOVIE_AM_20260423.md` (or new AO_PM scratch if closed)

## Cost impact

- Per sidebar scan: +1 Opus extraction (~$0.02) on every AO PM / MOVIE AM interaction. At current traffic (~5/day between both PMs) = ~$3/month.
- Per meeting ingest match: +0 LLM (no extraction on signal; just flag + Slack push).
- One-off backfill: ~$0.20–$2 depending on matched row count.
- Total ongoing: ~$5–$10/month (well under Director's $10–$30/month budget from Q4 ratification).

## Acceptance criteria (brief-level, for AI Head review)

- D1 refactor preserves CROSS-PM-SIGNALS block verbatim
- D2 hook is fire-and-forget (does not block `[DONE]` yield)
- D3 fix mutates `req.project` only when routed capability is in PM_REGISTRY
- D4 backfill is idempotent across multiple runs
- D5 report covers all 22 capabilities from `capability_sets`
- D6 Slack push scoped to meeting channel only (`push_slack=True` not set on email/whatsapp existing calls)
- Every `file:line` citation verified by opening the source file (Rule 7)
- Every `SentinelStoreBack` use goes through `._get_global_instance()` (Rule 8)
- Post-merge sequence includes `git pull --rebase origin main` before any script run (Rule 9)
- Part H §H1–H5 filled in (Rule 10)
