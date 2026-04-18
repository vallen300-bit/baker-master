# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** PR #4 + PR #5 amendments shipped. PR #4 merged at `8a55e82`. PR #5 in B2 review at head `c8c7a35`.
**Task posted:** 2026-04-18
**Status:** OPEN

---

## Task: LOOP-HELPERS-1 — Implement `kbl/loop.py` helper functions

**Why now:** B3's Step 1 amendment references three helper functions that don't yet exist. PR #5 schema (merging soon) creates `feedback_ledger` for the ledger read. These helpers are the Python glue between CHANDA §2 Leg 3 (Step 1 reads) and the loop-infrastructure tables. Small, testable, production-moving. Unblocks Step 1 impl the moment KBL-B §6-13 authoring is done.

### Scope

**IN**
- New module `kbl/loop.py` with three helpers:

```python
def load_hot_md(path: str | None = None) -> str | None:
    """Read hot.md from $BAKER_VAULT_PATH/wiki/hot.md by default, or explicit path.

    Returns file contents as str, or None if file absent.
    Does NOT raise on missing file (valid zero-Gold state per CHANDA Inv 1).
    Raises LoopReadError on permission/IO errors.
    """

def load_recent_feedback(conn, limit: int | None = None) -> list[dict]:
    """Query feedback_ledger for the N most recent rows.

    limit: int override; if None, reads env var KBL_STEP1_LEDGER_LIMIT (default 20).
    Returns list of dicts with keys: id, created_at, action_type, target_matter,
        target_path, signal_id, payload, director_note.
    Returns empty list if table empty (valid zero-Gold state).
    Raises LoopReadError on DB errors.
    """

def render_ledger(rows: list[dict]) -> str:
    """Format ledger rows into prompt-insertable Markdown block.

    Renders one line per row in Director-scannable format:
        [YYYY-MM-DD] <action_type> <target_matter|target_path>: <director_note or payload-summary>
    Returns "(no recent Director actions)" if rows is empty.
    """
```

- `LoopReadError` exception class (for IO / DB read failures, distinct from zero-data case)
- Env var reader with default: `KBL_STEP1_LEDGER_LIMIT=20`
- Unit tests in `tests/test_loop_helpers.py`:
  - `load_hot_md`: happy path, missing file returns None, permission error raises `LoopReadError`
  - `load_recent_feedback`: happy path (mock PG or test DB), empty table returns `[]`, DB error raises `LoopReadError`, `limit` param override works, env-var default works
  - `render_ledger`: empty list renders placeholder, single row renders correctly, 20 rows render correctly, special chars escaped if any (director_note may contain markdown)
- Fixture hot.md files in `tests/fixtures/`:
  - `hot_md_sample.md` (realistic 6-bullet content)
  - `hot_md_empty.md` (edge case — file exists but zero content)

**OUT**
- Writer-side functions (ledger writer is KBL-C territory)
- Actual Step 1 prompt wiring (KBL-B implementation, separate ticket after §6-13 authoring)
- Template rendering / prompt assembly (lives in `run_kbl_eval.py` or successor module)
- Any change to `signal_queue`, `slug_registry`, or other existing modules

### Dependencies

- PR #5 (`feedback_ledger` table schema) — merge-pending on B2 review. You can write the helpers + tests against the schema SPEC now; tests use the test DB with migration applied. If PR #5 hasn't merged by the time you push, flag — I'll sequence merge before review of PR #6.
- `BAKER_VAULT_PATH` env var (already canonical per SLUGS-1)

### CHANDA pre-push self-check

- **Q1 Loop Test:** helpers IMPLEMENT Leg 3 reading pattern. This is remedy for Inv 3 non-compliance per B3's CHANDA audit. Director pre-approved amend-now. Cite CHANDA §2 Leg 3 + §5 Q1 amend-now authorization in PR body.
- **Q2 Wish Test:** pure wish-service. No convenience shortcut.
- **Inv 1 compliance:** `load_hot_md` returning None when file absent is valid zero-Gold read (not an error). `load_recent_feedback` returning `[]` when table empty is valid zero-Gold read. Both must be tested explicitly.
- **Inv 10 compliance:** helpers read data. They do NOT rewrite prompts. Inv 10 preserved.

### Branch + PR

- Branch: `loop-helpers-1`
- Base: `main` (after PR #5 merges; if PR #5 still pending when you finish, base on PR #5's branch and note in PR body)
- PR title: `LOOP-HELPERS-1: kbl/loop.py — hot.md + feedback_ledger readers`
- Target PR: #6

### Reviewer

B2 (reviewer-separation).

### Timeline

~45-60 min.

### Dispatch back

> B1 LOOP-HELPERS-1 shipped — PR #6 open, branch `loop-helpers-1`, head `<SHA>`, <N>/<N> tests green. Ready for B2 review.

---

*Posted 2026-04-18 by AI Head. B3 parallel-running Step 0 Layer 0 rules 6-should-fix application. B2 reviewing PR #5 (your parent schema).*
