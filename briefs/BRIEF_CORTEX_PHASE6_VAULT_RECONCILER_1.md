# BRIEF: CORTEX_PHASE6_VAULT_RECONCILER_1 — Drift detector for vault-write-outside-counter-txn gap

**Milestone:** Phase 6 Reflector V1 follow-up (post Brief 3 ship 2026-04-30 via PR #129 + #132)
**Dispatcher:** AI Head A — Tier B (autonomous merge on green; reads markers + re-emits, no auth/secrets/cross-capability writes)
**Builder:** TBD on dispatch (B1/B2/B3 currently in App AI Head A curation campaign; B4 has freshest Reflector context)
**Estimated time:** ~2–3h
**Complexity:** Low–Medium (single-file module + APScheduler wiring + tests)
**Prerequisites:** PR #129 + #132 merged on main; Reflector live in production with `CORTEX_PHASE6_REFLECTOR_ENABLED=true` default

---

## Context

Brief 3 (CORTEX_PHASE6_REFLECTOR_1) shipped 2026-04-30 with one inherent gap surfaced in B4's CODE_4_PENDING handover (S2): **vault write happens outside the counter-update transaction.**

In `orchestrator/cortex_phase6_reflector.py:reflect_cycle`:

- Lines 615–693 — counter increment + idempotency-marker INSERT inside one txn
- Line 694 — `conn.commit()` ends that txn
- Lines 724–737 — `write_proposed_actions_to_vault(...)` called AFTER commit, in a try/except that only logs

If the vault write throws (filesystem permissions, disk full, path race with another writer, mac-mini sync glitch), the marker is already committed, counters are already incremented, but `proposed-config-deltas.md` is missing. Subsequent sweeps then skip the cycle:

- Pre-check at lines 595–606 — `SELECT 1 FROM cortex_phase_outputs WHERE cycle_id = %s AND artifact_type = 'reflector_complete'` → returns row → returns `already_reflected: True`
- Sweep enumerator at lines 840–843 — `cycle_id NOT IN (SELECT cycle_id FROM cortex_phase_outputs WHERE artifact_type = 'reflector_complete')` → cycle filtered out

Net failure mode: the learning loop "looks complete" in PG (counters moved, marker present), but Director's per-matter `proposed-config-deltas.md` never appears for that cycle. Cortex's vault-side surface for human review is silently dark on the affected cycles.

**Why not transactional fix:** vault write goes to filesystem (`vault_scaffolding/live_mirror/v1/matters/<slug>/proposed-config-deltas.md` per CHANDA #9), which can't participate in PG transactions. Outbox/2PC patterns are heavier infra than this gap warrants. Cheap reconciler is the right shape.

---

## Problem

Reflector marker presence in `cortex_phase_outputs` (artifact_type='reflector_complete') is currently a proxy for "vault write succeeded." It isn't. The two operations are sequenced in the code but split across a transaction boundary that can fail open.

Today this gap is unmonitored — there's no counter, no log alert, no replay path. A vault-write failure on a Triaga-decided cycle is invisible until Director notices a missing entry in `proposed-config-deltas.md` (which can be days/weeks later or never, depending on whether the matter is actively being reviewed).

## Solution

Build `orchestrator/cortex_phase6_reconciler.py` — periodic background job that:

1. Enumerates `cortex_phase_outputs` rows where `artifact_type = 'reflector_complete'`, ordered by `created_at ASC`, `LIMIT 200` per run
2. For each marker, computes expected vault path: `{staging_root}/matters/{matter_slug}/proposed-config-deltas.md` (same logic as `write_proposed_actions_to_vault`, lines 316–317)
3. Checks (a) file exists, (b) file contains a `## Cycle {cycle_id} —` header line (matches the block format at line 322)
4. If file missing OR cycle block absent: re-emit by calling `write_proposed_actions_to_vault(...)` with the same args the Reflector would have used — `cycle_id`, `matter_slug`, `proposal_text` (re-loaded via `_load_proposal_text`), `cited_ids` + `triaga_outcome` (from marker payload), `today_iso` (today's date — block represents replay date, not original cycle date)
5. Audit each re-emit to `baker_actions` (action_type='cortex_reflector_reconcile', trigger_source='cortex_phase6_reconciler', payload includes `marker_created_at` + `replay_date` + `vault_path`)

V1 reads the marker payload only — it does NOT touch counters (those already incremented during original Reflector run). Reconciler is pure vault-write-replay.

---

## Module shape

`orchestrator/cortex_phase6_reconciler.py` — new file, ~150–200 lines. Public API:

```python
def reconcile_vault_writes(
    *,
    limit: int = 200,
    staging_root: Optional[Path] = None,
) -> dict:
    """Find reflector_complete markers whose vault file is missing or
    incomplete; re-emit the vault block for each.

    Returns counts: {checked, missing_file, missing_block, re_emitted,
                     re_emit_failed, errors}.
    """

def reconcile_vault_writes_sync(
    *,
    limit: int = 200,
    staging_root: Optional[Path] = None,
) -> dict:
    """Sync wrapper for APScheduler."""
```

Reuse `write_proposed_actions_to_vault` from `cortex_phase6_reflector.py:296`, `_load_proposal_text` from `:496`, and the `_get_store()` helper from `:121`. Do NOT duplicate the citation regex / TTL constants — import them.

**Marker payload schema (already written by Reflector at lines 667–674):**
```json
{
  "reflected_at": "...",
  "outcome": "helpful|harmful|stale",
  "cited_ids": [...],
  "unknown_ids": [...],
  "had_invalid_tokens": bool,
  "had_any_citation_match": bool
}
```

`outcome`, `cited_ids`, `reflected_at` are everything the reconciler needs to re-emit. `proposal_text` is NOT in the marker payload — re-load via `_load_proposal_text(conn, cycle_id)` exactly like the Reflector does at line 610.

---

## Block-presence check

Reflector writes the block at `cortex_phase6_reflector.py:321–326`:

```python
block = (
    f"\n## Cycle {cycle_id} — {today_iso} ({triaga_outcome})\n\n"
    ...
)
```

Reconciler check: `f"## Cycle {cycle_id} —" in target.read_text(encoding='utf-8')`. Substring match is sufficient — cycle_id is UUID, collision-free.

If file missing: write fresh (`write_proposed_actions_to_vault` handles file-not-exists path at lines 328–345).
If file exists but block missing: append (same fn, append path at lines 346–348).

Idempotency: if both sweep and reconciler race on a never-written cycle, both could append. Cheap mitigation — re-check block presence immediately before append:

```python
if not target.exists() or f"## Cycle {cycle_id} —" not in target.read_text(encoding='utf-8'):
    write_proposed_actions_to_vault(...)
```

V1 accepts the small race window (filesystem-level; sub-second). Reflector sweep cadence is 60 min default, reconciler at 65 min stagger means actual collision is rare. V2 can tighten via fcntl.flock if drift surfaces.

---

## APScheduler wiring

Edit `triggers/embedded_scheduler.py` — add new job AFTER the entire existing `phase6_reflector_sweep` env-gated block (lines 809–840 inclusive — `_reflector_enabled` gate through the `Skipped` else-branch log). Insertion point is line 841, immediately before the `BRIEF_MOVIE_AM_RETROFIT_1 D5` comment at line 842. Do NOT insert inside the if/else (the else-branch at 837–840 is the skip path). Pattern matches the existing block exactly:

```python
# Phase 6 Reconciler — vault-write-outside-counter-txn drift detector.
# Reads cortex_phase_outputs reflector_complete markers and re-emits
# vault block when proposed-config-deltas.md is missing or lacks the
# cycle's block (gap from Reflector vault write happening outside the
# counter-update txn at cortex_phase6_reflector.py:694 → :724).
# Env gate CORTEX_PHASE6_RECONCILER_ENABLED (default true).
# Cadence: REFLECTOR_RECONCILER_INTERVAL_MINUTES (default 65 min,
# 5-min stagger from sweep to reduce collision).
_reconciler_enabled = _os.environ.get(
    "CORTEX_PHASE6_RECONCILER_ENABLED", "true"
).lower()
if _reconciler_enabled not in ("false", "0", "no", "off"):
    from orchestrator.cortex_phase6_reconciler import reconcile_vault_writes_sync
    try:
        _reconciler_minutes = int(
            _os.environ.get("REFLECTOR_RECONCILER_INTERVAL_MINUTES", "65")
        )
    except (TypeError, ValueError):
        _reconciler_minutes = 65
    if _reconciler_minutes < 15:
        logger.warning(
            "REFLECTOR_RECONCILER_INTERVAL_MINUTES=%s below 15min floor; clamping to 15",
            _reconciler_minutes,
        )
        _reconciler_minutes = 15
    scheduler.add_job(
        reconcile_vault_writes_sync,
        IntervalTrigger(minutes=_reconciler_minutes),
        id="phase6_reconciler",
        name=f"Cortex Phase 6 vault reconciler (every {_reconciler_minutes} min)",
        coalesce=True, max_instances=1, replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info(
        f"Registered: phase6_reconciler (every {_reconciler_minutes} min)"
    )
else:
    logger.info(
        "Skipped: phase6_reconciler (CORTEX_PHASE6_RECONCILER_ENABLED=false)"
    )
```

Floor 15 min (vs. 5 min for sweep) — reconciler is recovery, not primary path; no need to run more often than sweep.

---

## V1 explicit drops (build simple, refine from practice)

- **No counter rollback.** If counters incremented but vault write failed, counters stay. Reconciler corrects the visible artifact only.
- **No ClickUp reconciliation.** ClickUp write is DORMANT in V1 (`REFLECTOR_CLICKUP_WRITE=false` default per channels-last). When Brief 5 lands and flips that env, a separate reconciler-V2 brief covers ClickUp drift.
- **No alerting threshold.** V1 logs each re-emit at INFO and counts in return dict; Director eyeballs `baker_actions WHERE action_type='cortex_reflector_reconcile'` if curious. V2 candidate: alert if `re_emitted > N` per day (threshold TBD on production data).
- **No replay backstop for missing markers.** Reconciler ONLY runs on cycles where the marker exists. Cycles where the entire Reflector pass failed (no marker, no counter, no vault) are visible via the existing sweep — they re-enter the next sweep naturally because the `NOT IN reflector_complete` filter still selects them.
- **No metrics dashboard.** Phase 6 metrics (sweep + reconciler counts) are V2 dashboard work.
- **No cross-matter consistency check.** Reconciler is per-cycle; doesn't validate that a matter's `proposed-config-deltas.md` is internally consistent across cycles.

---

## Tests

`tests/test_phase6_reconciler.py` — pytest, live-PG (skip if `TEST_DATABASE_URL` unset, mirrors `tests/test_phase6_reflector_sweep.py` pattern):

1. **happy path no-op** — marker exists, vault file exists with cycle block → returns `re_emitted=0`, no FS write
2. **missing file** — marker exists, vault file absent → file written from scratch with frontmatter + cycle block
3. **missing block** — marker exists, vault file has frontmatter + other cycle blocks but not this one → cycle block appended; existing blocks intact (substring assertion)
4. **idempotent re-run** — back-to-back invocation: second run is `re_emitted=0` because first re-emit landed
5. **proposal_text re-load** — marker exists, no file; verify reconciler calls `_load_proposal_text` (mock or read assertion) and writes the same proposal_text the Reflector would have
6. **bounded enumeration** — insert 250 markers, run with default `limit=200` → counts.checked == 200; second run picks up remaining 50
7. **error isolation** — one cycle's re-emit raises (mock vault path unwritable) → counts.errors == 1, other cycles still re-emit; no global rollback
8. **audit row** — verify `baker_actions` row inserted per re-emit (action_type='cortex_reflector_reconcile')

Live-PG fixtures should use the same scaffold as `test_phase6_reflector_sweep.py` (cortex_cycles + cortex_phase_outputs + tmp staging_root via `tmp_path`).

---

## Acceptance criteria

- `orchestrator/cortex_phase6_reconciler.py` compiles clean (`python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase6_reconciler.py', doraise=True)"`)
- `triggers/embedded_scheduler.py` registers `phase6_reconciler` job; `singleton_check.sh` passes
- `tests/test_phase6_reconciler.py` — all 8 tests pass live-PG
- No regression in existing `tests/test_phase6_reflector_sweep.py` (51 tests, must stay green)
- Manual smoke: in a TEST_DATABASE_URL-set local run, insert a `reflector_complete` marker WITHOUT calling `write_proposed_actions_to_vault`; run `reconcile_vault_writes_sync()`; verify file appears at `vault_scaffolding/live_mirror/v1/matters/<slug>/proposed-config-deltas.md` with the expected cycle block
- `baker_actions` audit row format documented in commit message

---

## Architect-review checkpoints (apply per Lesson #52 + the architect-review track record from PR #125 + #129)

When the build PR opens, AI Head A invokes `code-architecture-reviewer` subagent on the diff. Specifically check:

- **Counter idempotency** — reconciler MUST NOT increment any counter. Verify no UPDATE on `cortex_directives` anywhere in the diff.
- **Vault path computation** — reconciler's path computation must EXACTLY match Reflector's at lines 316–317, including default `staging_root` resolution. Drift here = reconciler writes to one path, sweep writes to another, both report success.
- **Marker enumeration scope** — query MUST filter `artifact_type = 'reflector_complete'` only. Don't enumerate all phase outputs; performance footgun.
- **Replay date semantics** — `today_iso` passed to `write_proposed_actions_to_vault` should be TODAY (replay date), not the marker's `reflected_at`. Block header indicates "this is what the Reflector emitted on this date" — replay block is honestly dated as a replay.
- **Audit completeness** — `baker_actions` row must capture enough context to debug a drift incident: original `marker_created_at`, `cycle_id`, `matter_slug`, `outcome`, `vault_path`, `replay_date`.

---

## Branch + dispatch shape

Branch: `b<N>/cortex-phase6-vault-reconciler-1`
Mailbox: `briefs/_tasks/CODE_<N>_PENDING.md` overwrite (busy-check first per `_ops/processes/b-code-dispatch-coordination.md` §2 + Lesson #54 `gh pr list` precheck)
PR title: `feat(cortex): Phase 6 vault reconciler — drift detector for vault-write-outside-counter-txn (CORTEX_PHASE6_VAULT_RECONCILER_1)`
PR body must reference: this brief path + Brief 3 PR #129 + #132 + the file:line gap citations above.

---

## Cross-references

- Brief 3 (predecessor): `briefs/BRIEF_CORTEX_PHASE6_REFLECTOR_1.md`
- Reflector module: `orchestrator/cortex_phase6_reflector.py` (PR #129 + #132)
- Sweep job: `triggers/embedded_scheduler.py:809–840`
- Brief 4 (schema): `briefs/BRIEF_CORTEX_CONFIG_DIRECTIVES_SCHEMA_1.md` (PR #125 + #127)
- CHANDA #9 (mac-mini-writer constraint): `~/baker-vault/_ops/processes/cortex-architecture-final.md` (vault-side)
- Handover origin: `~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/session_handover_2026_04_30_late_brief3_4_shipped.md` (S2)
