# BRIEF: AUTHOR_DIRECTOR_GUARD_1 — CHANDA detector #4 (pre-commit hook + intent-based commit-signing)

## Context

CHANDA_enforcement.md §4 row #4 requires that `author: director` files stay "untouched by agents." Detector: pre-commit hook. Today — **zero enforcement** (file shipped as PR #45 but no detector script exists yet).

**Workflow reality** (ratified 2026-04-23 by Director): Director never commits `author: director` files directly. He writes plain English to AI Head; AI Head commits the .md edit. Email-allowlist bypass therefore blocks the real workflow.

**New mechanism — intent-based commit-signing:** the hook checks the commit message for a `Director-signed:` marker carrying a short quote of Director's instruction. Agent commits touching protected files WITHOUT that marker → reject. WITH the marker → allow.

This brief:
1. Ships the detector script per CHANDA §6 path.
2. Bundles a one-line §7 amendment-log entry in `CHANDA_enforcement.md` clarifying row #4 enforcement semantics (intent-based, not identity-based).
3. Ships pytest suite exercising 6 scenarios.

**Install on baker-vault Mac Mini** is a post-merge AI Head action (SSH autonomous per charter §3), NOT in this brief's scope. Belt-and-braces install in baker-master's `.git/hooks/pre-commit` is also AI Head post-merge.

## Estimated time: ~1.5–2h
## Complexity: Low–Medium
## Prerequisites: PR #45 (`CHANDA_enforcement.md` exists) — merged `3b60b0d`.

---

## Fix/Feature 1: The detector script

### Problem

No script exists at the CHANDA §6 path. Protected files (`author: director` frontmatter) can be mutated by any agent without detection.

### Current State

- `CHANDA_enforcement.md` §4 row #4 defined + §6 detector pointer cites `invariant_checks/author_director_guard.sh` as the script path. **File does not exist.**
- `invariant_checks/` directory **does not exist** — this brief creates it.
- Pattern precedent: `scripts/check_singletons.sh` — shell script, grep-driven, exit-code-based, `ERRORS` counter → exit 1 if violations found. Mirror this style.
- **2 live protected files** in baker-vault:
  - `wiki/hot.md` (frontmatter line 4: `author: director`)
  - `_ops/ideas/2026-04-21-chanda-plain-english-rewrite.md` (frontmatter line 140: `author: director`)
- Baker-master currently has **zero** `author: director` files; hook is defensive for future.

### Implementation

**Step 1 — Create directory** `/15_Baker_Master/01_build/invariant_checks/` (matches CHANDA §6 path).

**Step 2 — Write script** at `/15_Baker_Master/01_build/invariant_checks/author_director_guard.sh`:

```bash
#!/usr/bin/env bash
# CHANDA invariant #4 — author:director files untouched by agents.
#
# Runs as pre-commit hook. Scans staged diff for any file that either
# (a) currently has `author: director` YAML frontmatter in the staged
#     version, OR
# (b) had it in HEAD (pre-commit version) — catches frontmatter-toggle
#     bypass attempts.
#
# Agents may mutate these files ONLY when the commit message contains
# a `Director-signed:` marker with a quote of Director's plain-English
# instruction (ratified 2026-04-23). No marker → reject the commit.
#
# Exit 0 = allow; Exit 1 = reject.

set -euo pipefail

# --- 1. Collect staged files (added, modified, renamed) -------------------
CHANGED_FILES=$(git diff --cached --name-only --diff-filter=AMR 2>/dev/null || true)
if [ -z "$CHANGED_FILES" ]; then
  exit 0
fi

# --- 2. Filter to candidates — .md files only (frontmatter is YAML-in-MD) --
MD_FILES=$(echo "$CHANGED_FILES" | grep -E '\.md$' || true)
if [ -z "$MD_FILES" ]; then
  exit 0
fi

# --- 3. For each .md file: is it Director-authored (pre or post)? ---------
PROTECTED_HITS=""
for f in $MD_FILES; do
  # (a) staged version — does it declare author: director in frontmatter?
  STAGED_HIT=$(git show ":$f" 2>/dev/null | \
    awk '/^---[[:space:]]*$/{ctr++; next} ctr==1 && /^author:[[:space:]]*director[[:space:]]*$/{print "HIT"; exit}' || true)

  # (b) pre-version (HEAD) — did it previously declare author: director?
  #     (Catches frontmatter-toggle bypass: delete `author: director`,
  #     then edit, then re-add — this catches the middle step.)
  PRE_HIT=""
  if git cat-file -e "HEAD:$f" 2>/dev/null; then
    PRE_HIT=$(git show "HEAD:$f" 2>/dev/null | \
      awk '/^---[[:space:]]*$/{ctr++; next} ctr==1 && /^author:[[:space:]]*director[[:space:]]*$/{print "HIT"; exit}' || true)
  fi

  if [ -n "$STAGED_HIT" ] || [ -n "$PRE_HIT" ]; then
    PROTECTED_HITS="${PROTECTED_HITS}${f}\n"
  fi
done

if [ -z "$PROTECTED_HITS" ]; then
  exit 0
fi

# --- 4. Protected file(s) being touched. Commit message must carry marker. -
# Commit message source for pre-commit: $1 if called by git's pre-commit
# via COMMIT_EDITMSG (older style), else read current commit message file.
COMMIT_MSG_FILE="${1:-.git/COMMIT_EDITMSG}"
if [ ! -f "$COMMIT_MSG_FILE" ]; then
  echo "CHANDA #4: cannot read commit message file ($COMMIT_MSG_FILE)."
  echo "This script must run as a pre-commit hook receiving the message path."
  exit 1
fi

MARKER=$(grep -E '^Director-signed:[[:space:]]*"' "$COMMIT_MSG_FILE" 2>/dev/null || true)
if [ -n "$MARKER" ]; then
  # Director-signed marker present + non-empty quote. Allow.
  exit 0
fi

# --- 5. No marker: reject with plain-English explanation -----------------
echo ""
echo "=============================================================="
echo "CHANDA invariant #4 — author:director files untouched by agents"
echo "=============================================================="
echo ""
echo "This commit mutates Director-authored file(s):"
echo -e "$PROTECTED_HITS"
echo "Agents may only commit changes to 'author: director' files when"
echo "the commit message carries a 'Director-signed:' marker with a"
echo "quoted plain-English instruction from Director."
echo ""
echo "Example acceptable commit message:"
echo "    wiki(hot.md): update Monday focus"
echo ""
echo "    Director-signed: \"rewrite hot.md — this week focus is M0 quintet\""
echo ""
echo "Per 2026-04-23 ratification: intent-based, not identity-based."
echo "=============================================================="
exit 1
```

**Step 3 — Make executable:** ensure `chmod +x invariant_checks/author_director_guard.sh` at commit time. B-code SHOULD add the executable bit in git; verify with `git ls-files --stage invariant_checks/author_director_guard.sh` (expect `100755` permission prefix).

### Key Constraints

- **Pre-commit hook (not pre-push).** CHANDA §4 specifies pre-commit; catches mutation before commit enters local history. `check_singletons.sh` is pre-push — different scope, don't conflate.
- **YAML frontmatter detection is anchored to the first `---` block.** `awk /^---/{ctr++}` counts delimiter lines; only checks lines INSIDE the first block (between first `---` at line ≥1 and second `---`). Avoids false-positives from body text that happens to contain "author: director" (e.g. inside a fenced code block quoting another file).
- **Two-sided check (staged AND pre-version):** catches the "remove frontmatter line, make other edits, re-add frontmatter line" bypass.
- **Marker regex is STRICT:** `Director-signed:` + whitespace + opening `"` quote. Empty quote = valid (presence of marker is the gate; quote content is Director-facing evidence, not verified here). A stricter version (non-empty quote content) can follow in a future brief.
- **`set -euo pipefail`** — fail fast on any unhandled error.
- **No external dependencies** — only `git`, `grep`, `awk`, `echo`. Portable to any dev machine + Mac Mini + Render (where not used).
- **Exit codes match git convention:** 0 = allow, 1 = reject.
- **Does NOT touch the working tree.** Read-only analysis of git index + HEAD.

### Verification

1. `bash -n invariant_checks/author_director_guard.sh` — shell syntax check.
2. `shellcheck invariant_checks/author_director_guard.sh` (if shellcheck is available in test env) — lint.
3. Executable bit set: `git ls-files --stage invariant_checks/author_director_guard.sh` → prefix `100755`.
4. Manual smoke test: `cd /tmp && git init t && cd t && git config user.email "test@test" && echo -e '---\nauthor: director\n---\n\nbody' > hot.md && git add hot.md && git commit -m "test" --no-verify`, then copy hook into `.git/hooks/pre-commit`, stage a mutation, verify reject/allow per marker presence.

---

## Fix/Feature 2: pytest test suite

### Problem

Without exercised tests, the hook is a silent assumption. CHANDA's tier-critical invariants deserve test coverage equal to or stronger than `check_singletons.sh`'s implicit coverage.

### Current State

- No tests for `check_singletons.sh` exist today (ship-gate relies on the hook firing in practice).
- For this brief, we add explicit pytest tests via shell-out, since the logic is nontrivial (frontmatter detection, two-sided check, marker parsing).

### Implementation

**Create `tests/test_author_director_guard.py`:**

```python
"""Tests for invariant_checks/author_director_guard.sh.

Each test creates a throwaway git repo in a tmp dir, stages a mutation,
runs the hook script with a synthesized commit message, and asserts the
exit code + (where relevant) the stderr content.

No mocks — real git, real script.
"""
from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

HOOK_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "invariant_checks"
    / "author_director_guard.sh"
)


def _init_repo(tmp_path: Path) -> Path:
    """Initialize a fresh git repo in tmp_path and return its path."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    return tmp_path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _stage(repo: Path, *paths: str) -> None:
    subprocess.run(["git", "add", *paths], cwd=repo, check=True)


def _commit_clean(repo: Path, msg: str = "seed") -> None:
    """Make a seed commit (bypassing our hook for seeding).

    Sets a temp commit-msg file then uses --allow-empty for seed commits
    that don't already have staged content.
    """
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=repo, check=True)


def _run_hook(repo: Path, commit_msg: str) -> subprocess.CompletedProcess:
    """Run the hook with COMMIT_EDITMSG containing commit_msg."""
    msg_path = repo / ".git" / "COMMIT_EDITMSG"
    msg_path.write_text(commit_msg)
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT), str(msg_path)],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def test_non_md_file_passes(tmp_path: Path):
    """Scenario 1: staged change is a .py file — hook exits 0."""
    repo = _init_repo(tmp_path)
    _write(repo / "README.md", "# seed\n")
    _stage(repo, "README.md")
    _commit_clean(repo)
    _write(repo / "code.py", "print('hi')\n")
    _stage(repo, "code.py")
    result = _run_hook(repo, "feat: add code.py")
    assert result.returncode == 0, result.stderr


def test_unprotected_md_passes(tmp_path: Path):
    """Scenario 2: staged .md file with no author:director frontmatter — allow."""
    repo = _init_repo(tmp_path)
    _write(repo / "README.md", "# seed\n")
    _stage(repo, "README.md")
    _commit_clean(repo)
    _write(repo / "notes.md", textwrap.dedent("""
        ---
        author: agent
        ---
        notes body
    """).lstrip())
    _stage(repo, "notes.md")
    result = _run_hook(repo, "docs: add notes")
    assert result.returncode == 0, result.stderr


def test_protected_md_without_marker_rejects(tmp_path: Path):
    """Scenario 3: touch author:director file, no marker — reject."""
    repo = _init_repo(tmp_path)
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: director
        ---
        original body
    """).lstrip())
    _stage(repo, "hot.md")
    _commit_clean(repo, "seed hot.md")
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: director
        ---
        modified body
    """).lstrip())
    _stage(repo, "hot.md")
    result = _run_hook(repo, "tweak: hot.md body")
    assert result.returncode == 1
    assert "CHANDA invariant #4" in result.stdout
    assert "hot.md" in result.stdout


def test_protected_md_with_marker_allows(tmp_path: Path):
    """Scenario 4: touch author:director file WITH marker — allow."""
    repo = _init_repo(tmp_path)
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: director
        ---
        original body
    """).lstrip())
    _stage(repo, "hot.md")
    _commit_clean(repo, "seed hot.md")
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: director
        ---
        updated body
    """).lstrip())
    _stage(repo, "hot.md")
    msg = 'wiki(hot.md): Monday update\n\nDirector-signed: "rewrite hot.md Monday"\n'
    result = _run_hook(repo, msg)
    assert result.returncode == 0, result.stderr + result.stdout


def test_frontmatter_toggle_bypass_blocked(tmp_path: Path):
    """Scenario 5: attempt bypass by removing author:director from frontmatter.

    Pre-version has author:director; staged version drops it. Hook must
    still detect via pre-version check.
    """
    repo = _init_repo(tmp_path)
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: director
        ---
        body
    """).lstrip())
    _stage(repo, "hot.md")
    _commit_clean(repo, "seed")
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: agent
        ---
        body
    """).lstrip())
    _stage(repo, "hot.md")
    result = _run_hook(repo, "toggle: drop author flag")
    assert result.returncode == 1
    assert "CHANDA invariant #4" in result.stdout


def test_body_false_positive_ignored(tmp_path: Path):
    """Scenario 6: 'author: director' appears in BODY, not frontmatter.

    E.g. a fenced code block quoting another file. Must not trigger.
    """
    repo = _init_repo(tmp_path)
    _write(repo / "README.md", "# seed\n")
    _stage(repo, "README.md")
    _commit_clean(repo)
    content = (
        "---\n"
        "author: agent\n"
        "---\n"
        "\n"
        "This doc references the hot.md invariant. Example frontmatter:\n"
        "\n"
        "```yaml\n"
        "author: director\n"
        "```\n"
    )
    _write(repo / "doc.md", content)
    _stage(repo, "doc.md")
    result = _run_hook(repo, "docs: add example")
    assert result.returncode == 0, result.stderr + result.stdout
```

### Key Constraints

- **No mocks** — real `git init`, real `git add`, real shell-out. Tests are slower (~2–3 s total for 6 tests) but honest.
- **pytest `tmp_path` fixture** auto-cleans the throwaway repo per test.
- **Seed commit discipline:** every test makes an initial commit BEFORE staging the mutation, so `git show HEAD:path` has a pre-version to compare.
- **Subprocess timeout not used** — shells exit fast. Add 10s `timeout=` if CI flakes.
- **Frontmatter awk logic mirrors the script** — any false-positive/negative fix applies to both script and test expectations. Keep aligned.

### Verification

1. `pytest tests/test_author_director_guard.py -v` — expect 6 passed.
2. `python3 -c "import py_compile; py_compile.compile('tests/test_author_director_guard.py', doraise=True)"` — zero output.
3. Run one test in isolation to prove the happy path shells out correctly:
   ```
   pytest tests/test_author_director_guard.py::test_protected_md_with_marker_allows -v
   ```
4. Full-suite regression: `pytest tests/ 2>&1 | tail -3` — expect +6 passes, 0 new failures.

---

## Fix/Feature 3: CHANDA_enforcement.md §7 amendment-log entry

### Problem

CHANDA_enforcement.md §4 row #4 text reads "`author: director` files untouched by agents" (identity-based). Director's ratified 2026-04-23 workflow is intent-based (agents commit with `Director-signed:` marker). Row text should NOT change — but §7 amendment log must record the enforcement semantics refinement so future readers understand the detector's actual behavior.

### Current State

- `CHANDA_enforcement.md` shipped as PR #45 (`3b60b0d`).
- §7 amendment log currently has ONE row:
  ```
  | 2026-04-21 | all | Initial creation from CHANDA rewrite session | "yes" (2026-04-21) |
  ```

### Implementation

**Append one row** to §7 amendment log table:

```
| 2026-04-23 | §4 row #4 + §6 | Enforcement refined to intent-based: agent commits to `author: director` files allowed only when commit message carries `Director-signed:` quote marker. Row #4 text unchanged; detector script at `invariant_checks/author_director_guard.sh` implements the check (AUTHOR_DIRECTOR_GUARD_1, PR TBD). | Director workflow definition 2026-04-23 ("To change any files I write to you AI Head in plain English") |
```

Edit location in `CHANDA_enforcement.md`: after the existing 2026-04-21 row, before end-of-file or end-of-§7. (File has no §8 — the amendment log is the last section.)

### Key Constraints

- **One-line insert only.** Do not modify row #4 text itself; do not modify §6 detector pointer (it already points to the correct script path).
- **Keep Markdown table alignment** — pipe separators + spacing matches existing row style.
- **Close file at §7.** Do not add §8 or footer (per original CHANDA_ENFORCEMENT_1 scope).

### Verification

1. `grep -c "| 2026-04" CHANDA_enforcement.md` → 2 (one from 2026-04-21, one from 2026-04-23).
2. `grep "Director-signed" CHANDA_enforcement.md` → at least 1 hit (the new row).
3. `tail -1 CHANDA_enforcement.md` → the new row is the last content line (file ends at §7 amendment log).
4. `wc -l CHANDA_enforcement.md` — now ~77 lines (was 76).
5. `git diff --stat CHANDA_enforcement.md` → `1 insertion(+)`.

---

## Files Modified

- NEW `invariant_checks/author_director_guard.sh` — detector shell script (~70 LOC, executable).
- NEW `tests/test_author_director_guard.py` — 6 pytest scenarios (~120 LOC).
- MODIFIED `CHANDA_enforcement.md` — +1 row in §7 amendment log.

## Do NOT Touch

- `scripts/check_singletons.sh` — unrelated (singleton hook). Don't refactor shared helpers — the two scripts are short enough to live independently.
- `CHANDA.md` — paired rewrite is `CHANDA_PLAIN_ENGLISH_REWRITE_1` (separate brief).
- `.git/hooks/` — hook installation is AI Head post-merge (both baker-master and baker-vault on Mac Mini via SSH). Do NOT bundle an install script in this brief.
- `.github/workflows/` — no CI yet; out of scope.
- Any existing `author: director` file in baker-vault — those are Director's.
- `triggers/embedded_scheduler.py`, `memory/store_back.py`, `outputs/slack_notifier.py` — unrelated.

## Quality Checkpoints

Run in order. Paste literal output in ship report.

1. **Shell syntax:**
   ```
   bash -n invariant_checks/author_director_guard.sh
   ```
   Expect: zero output.

2. **Executable bit:**
   ```
   git ls-files --stage invariant_checks/author_director_guard.sh
   ```
   Expect: starts with `100755` (executable in git).

3. **Pytest (new tests):**
   ```
   pytest tests/test_author_director_guard.py -v
   ```
   Expect: `6 passed`. Test names match brief exactly.

4. **Syntax check Python test:**
   ```
   python3 -c "import py_compile; py_compile.compile('tests/test_author_director_guard.py', doraise=True)"
   ```
   Expect: zero output.

5. **Singleton hook still green:**
   ```
   bash scripts/check_singletons.sh
   ```
   Expect: `OK: No singleton violations found.`

6. **Full-suite regression delta:**
   ```
   pytest tests/ 2>&1 | tail -3
   ```
   Baseline (post-PR #48 merge on main): check at dispatch time. Expected delta: +6 passes, 0 new failures/errors.

7. **Amendment log check:**
   ```
   grep -c "^| 2026-04" CHANDA_enforcement.md   # expect 2
   grep "Director-signed" CHANDA_enforcement.md  # expect >=1 hit
   tail -1 CHANDA_enforcement.md                 # should be the new 2026-04-23 row
   ```

8. **Manual smoke** (optional, not gating):
   ```
   cd /tmp && rm -rf t && git init -q t && cd t && \
     git config user.email t@t && git config user.name t && \
     printf -- '---\nauthor: director\n---\nbody\n' > hot.md && \
     git add hot.md && git commit -qm seed && \
     printf -- '---\nauthor: director\n---\nmodified\n' > hot.md && \
     git add hot.md && \
     printf "tweak\n" > .git/COMMIT_EDITMSG && \
     bash ~/bm-b5/invariant_checks/author_director_guard.sh .git/COMMIT_EDITMSG; echo "exit=$?"
   ```
   Expect: exit=1 + CHANDA #4 rejection message.

## Verification SQL

N/A — no DB changes.

## Rollback

- `git revert <merge-sha>` — single-PR revert restores state.
- Env kill-switch: **none shipped** (hook is local-only, no env gate needed — to bypass, use `git commit --no-verify` once, flagged in charter as requiring Director authorization).

---

## Ship shape

- **PR title:** `AUTHOR_DIRECTOR_GUARD_1: CHANDA detector #4 pre-commit hook (intent-based commit-signing)`
- **Branch:** `author-director-guard-1`
- **Files:** 3 — new shell script + new pytest + 1-line MODIFIED CHANDA_enforcement.md.
- **Commit style:** match prior CHANDA commits. Example: `chanda(detector#4): author:director files guarded by intent-based commit-signing hook`
- **Ship report:** `briefs/_reports/B5_author_director_guard_1_20260423.md`. Include:
  - All 8 Quality Checkpoint outputs (literal)
  - 1-line diff proving the CHANDA_enforcement.md amendment-log entry landed
  - `git ls-files --stage invariant_checks/author_director_guard.sh` showing `100755` executable bit

**Tier A auto-merge on B3 APPROVE** (standing per charter §3).

## Post-merge (AI Head, not B-code):

AI Head post-merge actions (autonomous per charter §3):

1. SSH Mac Mini → install `invariant_checks/author_director_guard.sh` as baker-vault pre-commit hook:
   ```
   ssh macmini
   cd ~/baker-vault
   cp <baker-master-clone>/invariant_checks/author_director_guard.sh .git/hooks/pre-commit-chanda-4
   # Wire into .git/hooks/pre-commit if one exists; else symlink:
   [ ! -e .git/hooks/pre-commit ] && ln -s pre-commit-chanda-4 .git/hooks/pre-commit
   chmod +x .git/hooks/pre-commit .git/hooks/pre-commit-chanda-4
   ```
2. Smoke-test by making a tiny edit to `wiki/hot.md` without a marker, attempting to commit — expect rejection.
3. Log AI Head action to `actions_log.md`.
4. Install belt-and-braces hook in baker-master `.git/hooks/pre-commit` on Director's laptop (requires Director's local action — flag in post-merge report, do not attempt remote).

## Timebox

**1.5–2h.** If >3h, stop and report — something's wrong.

**Working dir:** `~/bm-b5` (Team 1 fresh clone, idle). Per OPERATING.md row 2a.
