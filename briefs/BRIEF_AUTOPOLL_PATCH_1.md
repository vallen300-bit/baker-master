# BRIEF: AUTOPOLL_PATCH_1 — Surgical follow-ups for B_CODE_AUTOPOLL_1 (PR #69)

## Context

PR #69 B_CODE_AUTOPOLL_1 cross-team review by AI Head A surfaced 3 correctness/robustness defects ([review comment](https://github.com/vallen300-bit/baker-master/pull/69#issuecomment-4331292374)). All are operational issues, not security — `/security-review` posted NO FINDINGS at confidence ≥8 ([audit comment](https://github.com/vallen300-bit/baker-master/pull/69#issuecomment-4332897177)).

**This patch must ship BEFORE Director pastes the autopoll startup blocks** (Q7 cohort: B2 + B3 + AI Head A first-overnight). OBS-1 is structurally critical — Q2 stop condition #2 (3 consecutive idle wakes → STOP) is unimplementable as written because wakes have no session memory.

## Estimated time: ~30-45min
## Complexity: Low
## Prerequisites: PR #69 merged to `main`

---

## Fix 1 (HIGH): OBS-1 — idle-counter persistence

### Problem

Phase 1 step 2 of [`_ops/processes/b-code-autopoll-protocol.md`](_ops/processes/b-code-autopoll-protocol.md) says:
> Track an idle counter in your scratchpad. If 3 consecutive wakes observed no fresh dispatch → STOPPED, exit.

But B-codes have no session memory across `ScheduleWakeup`. "Scratchpad" doesn't survive the wake boundary — the next wake reads the same `/loop` prompt cold. Q2 stop condition #2 is structurally broken.

### Solution

Per-B-code local state file at `~/.autopoll_state/{b_code}.yaml`. Outside any git repo, survives across wakes via filesystem. Per-B-code path so b1 / b2 / b3 counters never collide.

### Implementation

Add to [`scripts/autopoll_state.py`](scripts/autopoll_state.py) after the existing `push_state_transition` function (current end of file):

```python
_IDLE_STATE_DIR = Path.home() / ".autopoll_state"


def _idle_state_path(b_code: str) -> Path:
    """Per-B-code local state file. Survives across wakes; outside any repo."""
    return _IDLE_STATE_DIR / f"{b_code}.yaml"


def read_idle_count(b_code: str) -> int:
    """Return current idle wake count for this B-code (0 if no state file)."""
    p = _idle_state_path(b_code)
    if not p.exists():
        return 0
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except (yaml.YAMLError, ValueError, OSError):
        return 0
    val = data.get("idle_count", 0)
    return int(val) if isinstance(val, int) else 0


def increment_idle_count(b_code: str) -> int:
    """Increment idle counter, return new value. Creates state dir if missing."""
    _IDLE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = _idle_state_path(b_code)
    new = read_idle_count(b_code) + 1
    p.write_text(yaml.safe_dump({
        "idle_count": new,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "b_code": b_code,
    }, sort_keys=False))
    return new


def reset_idle_count(b_code: str) -> None:
    """Reset to 0 (call after successful claim of fresh dispatch)."""
    p = _idle_state_path(b_code)
    if p.exists():
        p.unlink()
```

Update [`_ops/processes/b-code-autopoll-protocol.md`](_ops/processes/b-code-autopoll-protocol.md) Phase 1 step 2 (lines 19-26 of current file). Replace:

```
2. Check stop conditions:
   - Read `OVERNIGHT_AUTONOMY_UNTIL` env. If unset, default to `07:00 UTC`
     today. If `now > deadline` → write a one-line STOPPED log to chat,
     do NOT call `ScheduleWakeup`, exit loop.
   - Track an idle counter in your scratchpad. If 3 consecutive wakes
     observed no fresh dispatch → STOPPED, exit. Director can re-arm via
     paste-block.
   - If the user pastes literal `STOP AUTOPOLL` into the tab → exit.
```

With:

```
2. Check stop conditions:
   - Read `OVERNIGHT_AUTONOMY_UNTIL` env. If unset, default to `07:00 UTC`
     today. If `now > deadline` → write a one-line STOPPED log to chat,
     do NOT call `ScheduleWakeup`, exit loop.
   - Read persistent idle counter:
     ```
     python3 -c "from scripts.autopoll_state import read_idle_count; \
       print(read_idle_count('bN'))"
     ```
     If returned value `>= 3` → STOPPED, exit. Director re-arms by
     deleting `~/.autopoll_state/bN.yaml` or pasting startup block.
   - If the user pastes literal `STOP AUTOPOLL` into the tab → exit.
```

Update Phase 2 step 4 (after line 44 — the `COMPLETE / RETIRED → idle reschedule` line). Add new tail line:

```
   On any "idle reschedule" branch above, BEFORE Phase 7's
   ScheduleWakeup, call:
   ```
   python3 -c "from scripts.autopoll_state import increment_idle_count; \
     print(increment_idle_count('bN'))"
   ```
   If returned value `>= 3` → STOPPED, exit (skip Phase 7 reschedule).
```

Update Phase 3 step 5 (line 48). After `git pull --rebase --quiet`, add:

```
5a. Successful claim → reset idle counter:
    ```
    python3 -c "from scripts.autopoll_state import reset_idle_count; \
      reset_idle_count('bN')"
    ```
```

### Key Constraints

- State dir `~/.autopoll_state/` is outside any git repo. NEVER commit it. Confirm via `git check-ignore ~/.autopoll_state/b3.yaml` returns nothing (it's outside cwd, so git doesn't see it at all).
- Per-B-code separation: b1's counter never affects b2's. Verified by separate filename per b_code arg.
- `read_idle_count` on missing file returns 0 (not error) — first wake after Director re-arm starts fresh.

---

## Fix 2 (MEDIUM): OBS-2 — dirty file on push reject

### Problem

Phase 3 step 8 of [`_ops/processes/b-code-autopoll-protocol.md`](_ops/processes/b-code-autopoll-protocol.md) currently reads:

```
8. If `git push` rejects (someone else's commit landed) → `git pull
   --rebase`, re-read state. If now `IN_PROGRESS` by another B-code →
   idle reschedule. Last-writer-wins per Q6 ratification.
```

But `transition_state(...)` mutated the local frontmatter file before the push attempt. After push reject, `git pull --rebase` refuses with "cannot pull with rebase: You have unstaged changes" and the loop deadlocks.

### Solution

Discard local mutation BEFORE re-pull, since LWW Q6 means the other commit wins anyway.

### Implementation

Replace Phase 3 step 8 (lines 59-61) with:

```
8. If `git push` rejects (someone else's commit landed) → discard local
   mutation per LWW Q6 (the other writer's transition wins):
   ```
   git reset --hard origin/main && git pull --rebase --quiet
   ```
   Then re-read state via `read_state(...)`. If now `IN_PROGRESS` by
   another B-code → idle reschedule. If still `OPEN` → optionally
   re-attempt claim from Phase 3 step 6.
```

NO code change to [`scripts/autopoll_state.py`](scripts/autopoll_state.py) — the script's atomic-write contract is correct. This is a protocol-doc fix only.

### Key Constraints

- `git reset --hard origin/main` is destructive but bounded to the mailbox file mutation we just made. Charter §4 destructive-actions guardrails apply elsewhere; here it's part of the LWW protocol.
- This MUST happen INSIDE the autopoll loop (Phase 3 step 8), not after — between mutation and re-pull is the only deadlock window.

---

## Fix 3 (LOW): OBS-3 — yaml.YAMLError not caught alongside ValueError

### Problem

[`scripts/autopoll_state.py`](scripts/autopoll_state.py) `_split_frontmatter` (lines 454-464) calls `yaml.safe_load(text[4:end])`. On malformed YAML inside the frontmatter delimiters, `safe_load` raises `yaml.YAMLError` (not `ValueError`).

[`read_state`](scripts/autopoll_state.py) (lines 471-478) and [`find_stale_claims`](scripts/autopoll_state.py) (lines 511-541) catch only `ValueError`. One bad mailbox would crash the AI Head A watchdog with an uncaught YAMLError.

### Solution

Convert YAMLError to ValueError inside `_split_frontmatter` so existing catchers continue to work. Single-point fix.

### Implementation

In [`scripts/autopoll_state.py`](scripts/autopoll_state.py), replace the body of `_split_frontmatter` (lines 454-464) with:

```python
def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("unterminated frontmatter")
    try:
        fm = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"malformed YAML in frontmatter: {e}") from e
    if not isinstance(fm, dict):
        raise ValueError("frontmatter is not a mapping")
    body = text[end + 5:]
    return fm, body
```

### Key Constraints

- Test must use real malformed YAML inside `---` delimiters (not just `---\n` open) — e.g., `---\nkey: [unclosed\n---\n` triggers YAMLError on the parse step (not the structural check).

---

## Files Modified

- [`scripts/autopoll_state.py`](scripts/autopoll_state.py) — add 3 functions (`read_idle_count` / `increment_idle_count` / `reset_idle_count`); patch `_split_frontmatter` to convert YAMLError → ValueError
- [`_ops/processes/b-code-autopoll-protocol.md`](_ops/processes/b-code-autopoll-protocol.md) — Phase 1 step 2 (idle counter), Phase 2 step 4 tail (increment on idle), Phase 3 step 5a (reset on claim), Phase 3 step 8 (push-reject reset+pull)
- [`tests/test_autopoll_state.py`](tests/test_autopoll_state.py) — add 5 new tests (`test_idle_count_starts_at_zero`, `test_increment_idle_count_returns_new_value`, `test_reset_idle_count_clears_state`, `test_idle_count_per_b_code_isolation`, `test_split_frontmatter_malformed_yaml_raises_valueerror`)

## Files NOT to Touch

- [`outputs/slack_notifier.py`](outputs/slack_notifier.py) — IMPORT only (per PR #69 dispatch)
- [`config/settings.py`](config/settings.py) — env via `os.getenv` only
- [`_ops/processes/b-code-autopoll-startup.md`](_ops/processes/b-code-autopoll-startup.md) — paste-blocks unchanged
- [`_ops/processes/b-code-dispatch-coordination.md`](_ops/processes/b-code-dispatch-coordination.md) — out of scope
- All production Cortex / capability / sentinel code
- `briefs/_tasks/CODE_*_PENDING.md` mailboxes — retrofit deferred to AI Head A per PR #69 dispatch

## Quality Checkpoints

1. `pytest tests/test_autopoll_state.py -v` — **all 25 tests green** (20 existing + 5 new). Literal stdout in ship report (Lesson #47 — no "by inspection").
2. `python3 -c "import py_compile; py_compile.compile('scripts/autopoll_state.py', doraise=True)"` exits 0
3. New idle-counter API smoke test:
   ```
   rm -rf ~/.autopoll_state
   python3 -c "from scripts.autopoll_state import read_idle_count, increment_idle_count, reset_idle_count; \
     assert read_idle_count('b3') == 0; \
     assert increment_idle_count('b3') == 1; \
     assert increment_idle_count('b3') == 2; \
     assert read_idle_count('b3') == 2; \
     assert read_idle_count('b2') == 0; \
     reset_idle_count('b3'); \
     assert read_idle_count('b3') == 0; \
     print('idle counter API OK')"
   ```
   Expected stdout: `idle counter API OK`. Cleans up after.
4. YAMLError converts to ValueError verified by new test (use `---\nkey: [unclosed\n---\n` body).
5. `_ops/processes/b-code-autopoll-protocol.md` Phase 1/2/3 references match the API exactly (function names + b_code arg).
6. `/security-review` skill MANDATORY before merge per Lesson #52. Trigger class: LOW (no auth, DB writes, secrets, or external API). Solo lane-owner pass sufficient — second-pair-review trigger NOT met.
7. NO commits to `~/.autopoll_state/`. `git status` after smoke test must remain clean (the dir is at `$HOME`, outside any repo, so git won't see it — confirm with `git status` showing only the intentional patch files).

## Verification

After merge:

```bash
cd ~/bm-bN  # any worktree
python3 -c "
from scripts.autopoll_state import read_idle_count, _split_frontmatter
# OBS-1: API exists and isolates per-b-code
assert read_idle_count('b1') == 0
# OBS-3: malformed YAML raises ValueError (not YAMLError)
try:
    _split_frontmatter('---\nkey: [unclosed\n---\n')
except ValueError as e:
    assert 'malformed YAML' in str(e)
print('AUTOPOLL_PATCH_1 verified')
"
```

Expected: `AUTOPOLL_PATCH_1 verified`

## Process

1. `cd ~/bm-bN && git checkout main && git pull -q`
2. Verify PR #69 has merged: `git log --oneline -5 | grep -i autopoll` returns the squash commit.
3. `git checkout -b autopoll-patch-1`
4. Apply the 3 fixes per `## Implementation` blocks above (no improvisation — copy exactly).
5. Add 5 new tests to `tests/test_autopoll_state.py` (positions: anywhere after `# 20` test_push_state_transition_silent_on_import_failure block; renumber locally if convenient).
6. Run ship gate: `pytest tests/test_autopoll_state.py -v` — paste literal stdout into ship report.
7. Syntax check: `python3 -c "import py_compile; py_compile.compile('scripts/autopoll_state.py', doraise=True)"`
8. Run smoke test (Quality Checkpoint #3) — paste output into ship report.
9. Commit + push, open PR titled `AUTOPOLL_PATCH_1: idle-counter persistence + push-reject reset + YAMLError catch (A's review fixes)`
10. Run `/security-review` skill (Lesson #52). Paste verdict comment to PR.
11. Write ship report at `briefs/_reports/B<N>_autopoll_patch_1_<date>.md` with literal pytest + smoke stdout.
12. Mark this mailbox COMPLETE on PR-merge per §3 hygiene.

## Co-Authored-By

```
Co-authored-by: Code Brisen #<N> <b<N>@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
