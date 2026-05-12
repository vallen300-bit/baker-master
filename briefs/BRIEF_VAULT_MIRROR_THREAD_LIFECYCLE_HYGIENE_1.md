# BRIEF: VAULT_MIRROR_THREAD_LIFECYCLE_HYGIENE_1 — vault_mirror.py race-window cleanup + pre-commit Part 3 exclusion narrowing

## Context

Bundled hygiene follow-up from two prior PRs:

- **PR #195** (VAULT_MIRROR_NON_LOCK_REPLICA_HOTFIX_1) merged 2026-05-12 night with two architect / 2nd-pass NITs filed as fast-follows (PINNED §I).
- **PR #194** (HARNESS_SUBAGENT_MIGRATION_1) merged 2026-05-13 with a PASS-WITH-NITS MEDIUM on pre-commit Part 3's `.githooks/` exclusion being directory-wide instead of pre-commit-file-only.

Production is correct today — neither NIT blocks current behavior. This brief bundles the three small fixes into one B-code dispatch.

## Estimated time: ~1.5h
## Complexity: Low
## Prerequisites: None (PRs #194 + #195 already merged on main).

---

## Fix 1 (L1): `stop_sync_thread` — atomic-swap, join outside lock

### Problem

`vault_mirror.py:297-310` `stop_sync_thread` holds `_sync_thread_lock` across the `thread.join(timeout=5.0)` call. During Render rolling restart (concurrent `start_sync_thread` on new replica + `stop_sync_thread` on old replica), the start path blocks up to 5s waiting for the lock.

Naïve fix — release lock before join — introduces a **DIFFERENT race**: concurrent `start_sync_thread` can observe `_sync_thread.is_alive() == True` mid-join and return the dying handle.

### Current State

```python
# vault_mirror.py:297-310
def stop_sync_thread(timeout: float = 5.0) -> None:
    global _sync_thread
    with _sync_thread_lock:
        _sync_thread_stop.set()
        thread = _sync_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        _sync_thread = None
```

### Implementation

Apply atomic-swap pattern per architect's canonical NIT (PINNED §I verbatim):

> "Atomic-swap: detach `_sync_thread = None` inside lock, join the local handle outside, reset stop event inside lock again. NAÏVE release-lock-before-join introduces a DIFFERENT race (concurrent start can observe `_sync_thread.is_alive() == True` mid-join and return dying handle)."

**Recommended implementation — per-thread stop event** (race-free):

```python
def start_sync_thread(interval_seconds: Optional[int] = None) -> threading.Thread:
    """..."""
    global _sync_thread, _sync_thread_stop
    with _sync_thread_lock:
        if _sync_thread is not None and _sync_thread.is_alive():
            return _sync_thread
        interval = (
            interval_seconds if interval_seconds is not None else sync_interval_seconds()
        )
        # Fresh stop event per spawn — eliminates cross-instance signal
        # leakage between a stopping thread and its successor.
        _sync_thread_stop = threading.Event()
        _sync_thread = threading.Thread(
            target=_sync_loop,
            args=(interval, _sync_thread_stop),
            name="vault_mirror_sync",
            daemon=True,
        )
        _sync_thread.start()
        logger.info(
            "vault_mirror: per-process sync thread started (every %ss)", interval
        )
        return _sync_thread


def _sync_loop(interval_seconds: int, stop_event: threading.Event) -> None:
    """..."""
    while True:
        if stop_event.wait(timeout=interval_seconds):
            return
        try:
            sync_tick()
        except Exception:
            logger.exception("vault_mirror: sync_loop tick raised")


def stop_sync_thread(timeout: float = 5.0) -> None:
    """Signal the sync thread to exit and join. Used by tests + shutdown.

    Atomic-swap: snapshot + detach inside lock, join the local handle
    outside lock so concurrent ``start_sync_thread`` is not blocked by
    the up-to-``timeout``-second join wait. Per-thread stop Event (each
    ``start_sync_thread`` allocates a fresh one) prevents signal-state
    leakage between a stopping thread and its successor.
    Architect M1 / 2nd-pass MEDIUM (PR #193/#195 follow-up).
    """
    global _sync_thread, _sync_thread_stop
    with _sync_thread_lock:
        stop_event = _sync_thread_stop
        thread = _sync_thread
        _sync_thread = None  # detach inside lock — concurrent start sees None
    stop_event.set()  # signal outside lock — wakes _sync_loop's wait()
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)  # join outside lock — no concurrent-start block
```

### Key Constraints

- **Module-level `_sync_thread_stop` MUST remain a module attribute** (tests do `vault_mirror._sync_thread_stop.clear()` directly — see `tests/test_vault_mirror.py:29, 158`). Reassignment inside `start_sync_thread` preserves the attribute; tests still work because they always reset AFTER `stop_sync_thread`.
- **Daemon flag + thread name MUST remain unchanged** (`daemon=True`, `name="vault_mirror_sync"`).
- **`_sync_loop` signature changes** from `(interval_seconds)` to `(interval_seconds, stop_event)`. All callers go through `start_sync_thread` — grep confirms no external callers.
- **Do NOT remove the defensive `try/except` in `_sync_loop`** — silent-warn was the failure mode that took down the non-lock replica before PR #195; we still need `logger.exception` to capture future raises.

### Verification

New tests in `tests/test_vault_mirror.py`:

1. **`test_stop_sync_thread_does_not_block_concurrent_start`** — start thread A, in another thread call `stop_sync_thread`; while stop is mid-join, call `start_sync_thread` from a third thread. Assert: third call returns within <50ms (not blocked) AND returns a NEW thread instance (not the dying A).
2. **`test_per_thread_stop_event_isolation`** — start thread A, call `stop_sync_thread` (signals A), immediately call `start_sync_thread` to spawn B, then `_sync_thread_stop.set()` on the CURRENT module attribute. Assert: B exits cleanly (sees its OWN event), A also exited (saw the prior event). No cross-contamination.
3. **Existing tests MUST continue to pass** — `test_stop_sync_thread_joins_and_clears`, `test_start_sync_thread_concurrent_idempotent`, `test_start_sync_thread_idempotent`, `test_module_exports_lifecycle_api`.

---

## Fix 2 (L2): `mirror_status` — snapshot `_sync_thread` to local before checking

### Problem

`vault_mirror.py:338-358` `mirror_status` reads `_sync_thread` twice without holding `_sync_thread_lock`. Between the `is not None` check and the `.is_alive()` call, a concurrent `stop_sync_thread` can null `_sync_thread` → `AttributeError: 'NoneType' object has no attribute 'is_alive'`.

The outer `try/except` in `outputs/dashboard.py` `/health` swallows the exception → returns `vault_sync_thread_alive: False` for one poll. False-negative obscures the actual signal the field was added to surface (PR #195 hotfix).

### Current State

```python
# vault_mirror.py:355-357
"vault_sync_thread_alive": (
    _sync_thread is not None and _sync_thread.is_alive()
),
```

### Implementation

Local-snapshot pattern (no lock needed — read-only snapshot):

```python
def mirror_status() -> dict:
    """Return ``{vault_mirror_last_pull, vault_mirror_commit_sha, vault_sync_thread_alive}`` for /health.
    ...
    """
    # Local snapshot — eliminates TOCTOU between is-not-None check and
    # is_alive() call. Concurrent ``stop_sync_thread`` can null
    # ``_sync_thread`` between the two; without snapshot, the second
    # access raises AttributeError, swallowed by /health's outer
    # try/except and surfacing as a one-poll false-negative.
    # Architect M1 / 2nd-pass LOW (PR #195 follow-up).
    thread = _sync_thread
    return {
        "vault_mirror_last_pull": (
            _last_pull_at.isoformat() if _last_pull_at else None
        ),
        "vault_mirror_commit_sha": _head_commit_sha(),
        "vault_sync_thread_alive": (
            thread is not None and thread.is_alive()
        ),
    }
```

### Key Constraints

- **Do NOT acquire `_sync_thread_lock` in `mirror_status`.** `/health` polls every ~1-5s in prod; lock contention with `start_sync_thread` / `stop_sync_thread` would serialize `/health` behind thread-lifecycle ops. Local-snapshot is sufficient.
- Module-attribute reads in CPython are atomic (GIL), so the snapshot itself doesn't tear.

### Verification

New test in `tests/test_vault_mirror.py`:

1. **`test_mirror_status_toctou_safety`** — start thread, in a tight loop call `mirror_status()` from one thread and `stop_sync_thread()` + `start_sync_thread()` from another for ~500 iterations. Assert: no `AttributeError` raised; `vault_sync_thread_alive` is always a bool (never `None`, never crashes).

---

## Fix 3 (MEDIUM): pre-commit Part 3 — narrow `.githooks/` exclusion to `pre-commit` file only

### Problem

`.githooks/pre-commit:48` `EXCLUDE_PATHS_REGEX` excludes the entire `.githooks/` directory from Part 3's retired-model-ID scan:

```bash
EXCLUDE_PATHS_REGEX='^briefs/|^tasks/lessons\.md$|^docs-site/|^\.githooks/'
```

The exclusion exists because the enforcement code itself contains the literal retired-model strings (`RETIRED_IDS_REGEX='claude-(opus-4|sonnet-4)-20250514'`). But directory-wide exclusion means any FUTURE hook file added to `.githooks/` would silently bypass the retired-model-ID check — a drift vector.

### Current State

```bash
# .githooks/pre-commit:47-48
RETIRED_IDS_REGEX='claude-(opus-4|sonnet-4)-20250514'
EXCLUDE_PATHS_REGEX='^briefs/|^tasks/lessons\.md$|^docs-site/|^\.githooks/'
```

### Implementation

Narrow the exclusion to the single legitimate file:

```bash
# .githooks/pre-commit:47-48
RETIRED_IDS_REGEX='claude-(opus-4|sonnet-4)-20250514'
EXCLUDE_PATHS_REGEX='^briefs/|^tasks/lessons\.md$|^docs-site/|^\.githooks/pre-commit$'
```

Also update the user-facing error message at line 65 to reflect the narrower exclusion:

```bash
# Before:
echo "[pre-commit] NO BYPASS. Exclusions: briefs/, tasks/lessons.md, docs-site/, .githooks/ (historical/audit-trail + enforcement code)." >&2

# After:
echo "[pre-commit] NO BYPASS. Exclusions: briefs/, tasks/lessons.md, docs-site/, .githooks/pre-commit (historical/audit-trail + enforcement code)." >&2
```

### Key Constraints

- **Do not touch Parts 1 or 2** — scope is Part 3 exclusion regex only.
- **Do not touch `RETIRED_IDS_REGEX`** — the regex itself is correct.
- **Do not add a Part-3 bypass** — "NO BYPASS by design" is intentional. The narrowing tightens enforcement; it does not relax it.

### Verification

New test cases (add to existing test harness — search for `test_pre_commit_*.sh` or `tests/test_pre_commit*.py` to find the right location; if no test harness exists for the hook yet, this fix is verified manually):

1. **Manual**: stage a NEW file `.githooks/post-commit` containing `claude-opus-4-20250514`; attempt commit; pre-commit MUST BLOCK with Part 3 message.
2. **Manual**: stage a change to `.githooks/pre-commit` itself containing `claude-opus-4-20250514` (e.g., in the `RETIRED_IDS_REGEX` literal); attempt commit; pre-commit MUST PASS (file is in exclusion).
3. **Manual**: stage a change to `briefs/test.md` containing `claude-opus-4-20250514`; pre-commit MUST PASS (file is in exclusion).

If a hook test harness exists (Bats, shellcheck-based, or Python), encode the three cases there.

---

## Files Modified

- `vault_mirror.py` — Fix 1 + Fix 2
- `.githooks/pre-commit` — Fix 3
- `tests/test_vault_mirror.py` — new tests for Fix 1 + Fix 2

## Do NOT Touch

- `outputs/dashboard.py` — `/health` integration already correct; outer try/except stays (defensive)
- `triggers/embedded_scheduler.py` — singleton scheduler unaffected; sync_tick was already migrated out per PR #193
- `briefs/_reports/B1_vault_mirror_*` — historical ship reports, append-only
- Other pre-commit Parts (1 migration immutability, 2 subagent location) — out of scope
- `RETIRED_IDS_REGEX` itself — regex is correct, only the exclusion changes

## Quality Checkpoints

After implementation, verify:

1. `python3 -c "import py_compile; py_compile.compile('vault_mirror.py', doraise=True)"` — compile clean
2. `pytest tests/test_vault_mirror.py -v` — all tests green (literal pytest output required; no "by inspection")
3. `bash .githooks/pre-commit` test pass: stage a NEW `.githooks/post-commit` with retired ID → blocks; stage `.githooks/pre-commit` change with retired ID → passes; existing exclusion paths still pass
4. Local `/health` smoke (optional, since Render restart on merge will exercise it): no AttributeError in logs during a `stop_sync_thread` + concurrent poll
5. `bash scripts/check_singletons.sh` — clean (no SentinelStoreBack/SentinelRetriever changes, should be no-op)
6. `git diff` review: only the three files above; no unrelated changes

## Verification SQL

N/A — this brief touches Python threading primitives + a shell hook; no DB changes.

## Ship Gate

Literal `pytest` output required (no "pass by inspection"). All new tests + all existing `tests/test_vault_mirror.py` tests MUST pass on a real run.

## Test plan summary

| Fix | Test | Method |
|---|---|---|
| 1 (L1) | `test_stop_sync_thread_does_not_block_concurrent_start` | NEW pytest |
| 1 (L1) | `test_per_thread_stop_event_isolation` | NEW pytest |
| 1 (L1) | Existing 7 tests in test_vault_mirror.py | Must continue passing |
| 2 (L2) | `test_mirror_status_toctou_safety` | NEW pytest (500-iter race loop) |
| 3 | New-hook-file blocking | Manual hook exercise (3 cases) |

## Risks

- **Per-thread stop event refactor**: tests reset `vault_mirror._sync_thread_stop.clear()` after each test. After this brief, that line still works (clears the most-recent event); but if a test starts a thread, calls `stop_sync_thread`, then directly inspects `_sync_thread_stop`, the inspected Event will be the one created in the most recent `start_sync_thread`. Test fixture at `tests/test_vault_mirror.py:25-29` already handles this correctly.
- **Hook test absence**: if no formal hook test exists, Fix 3 verification is manual. Accept manual verification; do NOT block the brief on building a hook test harness (out of scope).
- **No production behavior change is visible to users.** This is pure hygiene — race window narrowing + future-proofing the hook.

## Lessons applied

- **No "by inspection" ship.** Literal pytest required (lessons.md Lesson #8).
- **Function signature verification.** Brief snippets verified against actual code via Grep + Read; `_sync_loop` signature change documented.
- **Read the actual code, not a paraphrase.** PINNED §I gave the architect's caveat verbatim; brief cites it verbatim.
- **Singleton-pattern guard untouched.** `scripts/check_singletons.sh` should be no-op.

## Anchor

- PINNED §I (vault_mirror NITs from PR #195 architect 2nd-pass)
- PR #194 PASS-WITH-NITS MEDIUM (.githooks/ directory-wide exclusion)
- Director directive 2026-05-13 (this session): "delete §H and draft the bundled brief now"
