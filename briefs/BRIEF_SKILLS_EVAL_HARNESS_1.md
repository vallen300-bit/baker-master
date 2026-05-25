---
brief_id: SKILLS_EVAL_HARNESS_1
authored_by: deputy (AH2)
authored_at: 2026-05-25
director_ratified: 2026-05-25 (chat — Q3=A static trigger-keyword eval only for v1; companion to SOPS_TO_SKILLS_MIGRATION_1)
target: b3
reply_target: deputy (AH2) (cc lead)
expected_time: ~4-6h
complexity: Medium
target_repo: baker-vault (Python + YAML + markdown)
depends_on: BRIEF_SOPS_TO_SKILLS_MIGRATION_1 (migration produces the skill corpus this harness measures; eval can be dispatched first but full coverage requires migration shipped)
---

# BRIEF: SKILLS_EVAL_HARNESS_1 — Static trigger-keyword eval harness for the Baker skill catalog (v1)

## Context

After `SOPS_TO_SKILLS_MIGRATION_1` ships, Baker will have ~55+ skills across `~/baker-vault/_ops/skills/` and a few specialist agent libraries. The thevccorner.com Substack article "Prompts Are Dead. Skills Are the New Moat" (Dec 2025, read by Director 2026-05-25) makes one durable claim: skills are commodity markdown; the moat is in evals proving they work. Quote: "When Skills are commodity markdown, the moat shifts to proving whether your Skills work in production. **Evals are the new gross margin.**"

We currently have zero evals on the skill catalog. We don't know:
- Whether a skill's `MANDATORY TRIGGERS:` keywords actually match the prompts that should fire it (false negatives — agent misses the skill).
- Whether a skill fires on prompts where it should NOT (false positives — wrong skill fires, noise in the catalog).
- Which skills are hot (high-utility) vs cold (low-utility, candidates for retirement).
- Whether a trigger-keyword edit (1-line change to a SKILL.md description) helps or hurts.

This brief installs a v1 eval harness scoped to STATIC TRIGGER-KEYWORD MATCH ONLY. No LLM call required; no token cost; runs in seconds. Director-ratified Q3=A (chat 2026-05-25): trigger-keyword match for v1; full LLM behavioral eval deferred to v2 once the harness pattern is proven and we have signal on what's worth measuring.

## Estimated time: ~4-6h
## Complexity: Medium
## Prerequisites
- Read access to `~/baker-vault/_ops/skills/<*>/SKILL.md` (the corpus being measured)
- Python 3.11+ (stdlib only — no pip deps for v1; the runner is intentionally lightweight)
- Write access to `~/baker-vault/_ops/evals/skills/` (new directory)
- `BRIEF_SOPS_TO_SKILLS_MIGRATION_1` shipped first is preferred but NOT a hard prerequisite — the harness reads whatever's in `_ops/skills/` at run time and reports based on what it finds. If migration hasn't shipped, the eval just reports coverage on the existing ~35 skills.

---

## Fix 1 — Define the test case format + write the starter corpus

### Problem
We need a stable, human-editable format for test cases — one record per `(prompt, expected_skill_to_fire | expected_no_fire)` tuple, with enough metadata that future drift can be diagnosed.

### Current state
No eval directory exists in baker-vault. `~/baker-vault/_ops/evals/` does not exist yet (verify with `ls ~/baker-vault/_ops/evals/ 2>&1`).

### Implementation

**1a. Create the directory + YAML format file:**

```bash
mkdir -p ~/baker-vault/_ops/evals/skills
```

**1b. Write `~/baker-vault/_ops/evals/skills/test-cases.yml`** with this structure:

```yaml
# Static trigger-keyword eval cases for Baker skill catalog.
#
# Each top-level key is a skill slug. Value is a list of test cases.
# Each test case has:
#   - prompt: a natural-language Director / agent prompt
#   - expect: "fire" (this skill should match) | "no-fire" (this skill should NOT match)
#   - rationale: one-sentence explanation, used in failure reports
#
# Scope: trigger-keyword match only. A "fire" test PASSES if any of the skill's
# MANDATORY TRIGGERS keywords appear (case-insensitive substring) in the prompt.
# A "no-fire" test PASSES if NO trigger keywords appear.

write-brief:
  - prompt: "write brief for the new feature"
    expect: fire
    rationale: "write-brief is the literal trigger phrase"
  - prompt: "draft a brief for code brisen to implement X"
    expect: fire
    rationale: "draft + brief should fire write-brief"
  - prompt: "what time is it"
    expect: no-fire
    rationale: "unrelated to brief authoring"

agent-bus-posting-contract:
  - prompt: "I'm about to dispatch b3 with a gate request"
    expect: fire
    rationale: "dispatch + b3 are MANDATORY TRIGGERS"
  - prompt: "post to bus with ship report"
    expect: fire
    rationale: "post to bus + ship report"
  - prompt: "let's grab coffee"
    expect: no-fire
    rationale: "unrelated"

ai-head:
  - prompt: "AI Head session start, resume work"
    expect: fire
    rationale: "AI Head + session start"
  - prompt: "draft an email to John"
    expect: no-fire
    rationale: "email drafting is not AI Head scope"

dropbox-file-delivery:
  - prompt: "save this report to dropbox"
    expect: fire
    rationale: "save to dropbox is the trigger"
  - prompt: "upload to my dropbox folder"
    expect: fire
    rationale: "upload to dropbox"
  - prompt: "delete the old report from disk"
    expect: no-fire
    rationale: "delete is not upload"

cascade-back-prop:
  - prompt: "ratified the decision, Director approved"
    expect: fire
    rationale: "ratified + ratification are MANDATORY TRIGGERS"
  - prompt: "the contract was finalized"
    expect: no-fire
    rationale: "finalized is not the ratification keyword"
```

**1c. Starter corpus scope:** 5 hot skills, 2-3 test cases each (mix of fire + no-fire). Total ~12-15 cases. Hot skills are the ones we observe firing most often in Director conversations — list above is a fair starter; b3 may expand it during implementation if specific skills cry out for coverage.

### Key constraints
- YAML must be valid (b3: run `python3 -c "import yaml; yaml.safe_load(open('...'))"` after writing — actually, stdlib doesn't ship PyYAML; use `json` + .json file OR install PyYAML at the script layer. See Fix 2 for the actual choice — keeping the corpus in JSON if PyYAML is not installed avoids a pip dep).
- DECISION POINT: YAML vs JSON for the corpus. If `python3 -c "import yaml"` succeeds in the b3 shell, use YAML (more readable). Otherwise convert the file to `test-cases.json` (one-time) and store as JSON. **b3 MUST pick one at implementation time, commit only that file (not both), and document the choice in `~/baker-vault/_ops/evals/skills/README.md` under a `## Corpus file` section so future contributors edit the right one.** Either way: filename + extension match the chosen format.
- `prompt` values must be REALISTIC — what Director / an agent would actually type. Avoid "test" or "lorem ipsum" — those don't model the trigger surface.
- `rationale` is a one-liner for failure-report readability; not parsed.
- Slug case-sensitive: must match the filesystem name of the skill directory (e.g., `agent-bus-posting-contract`, not `Agent-Bus-Posting-Contract`).

### Verification

```bash
# YAML
python3 -c "import yaml; d = yaml.safe_load(open('/Users/dimitry/baker-vault/_ops/evals/skills/test-cases.yml')); print(f'skills={len(d)}, cases={sum(len(v) for v in d.values())}')"
# Expected (starter corpus): skills=5, cases=12-15

# OR JSON (if PyYAML unavailable):
python3 -c "import json; d = json.load(open('/Users/dimitry/baker-vault/_ops/evals/skills/test-cases.json')); print(f'skills={len(d)}, cases={sum(len(v) for v in d.values())}')"
```

---

## Fix 2 — Write the runner script `run_skill_trigger_evals.py`

### Problem
The runner reads (a) the skill corpus by walking `~/baker-vault/_ops/skills/<*>/SKILL.md` and extracting each `MANDATORY TRIGGERS:` line, and (b) the test cases. For each case, it determines if the prompt would fire the skill (case-insensitive substring match of any trigger keyword in the prompt) and compares to the expected outcome.

### Current state
No runner exists. `~/baker-vault/_ops/scripts/` already holds a few shell scripts (the existing pattern); Python scripts also live there (verify with `ls ~/baker-vault/_ops/scripts/*.py 2>&1`).

### Implementation

**Write `~/baker-vault/_ops/scripts/run_skill_trigger_evals.py`:**

```python
#!/usr/bin/env python3
"""Static trigger-keyword eval for Baker skill catalog.

Reads SKILL.md files under ~/baker-vault/_ops/skills/<*>/, extracts each
skill's MANDATORY TRIGGERS keywords, then runs each test case in
~/baker-vault/_ops/evals/skills/test-cases.{yml,json}.

A "fire" case PASSES if any trigger keyword appears (case-insensitive
substring) in the prompt. A "no-fire" case PASSES if NO trigger keywords
appear. The harness does NOT call any LLM — pure static analysis.

Anchor: BRIEF_SKILLS_EVAL_HARNESS_1 — Director-ratified 2026-05-25 Q3=A.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Optional YAML; fall back to JSON if unavailable.
try:
    import yaml  # noqa: F401
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

VAULT_SKILLS = Path.home() / "baker-vault" / "_ops" / "skills"
EVALS_DIR = Path.home() / "baker-vault" / "_ops" / "evals" / "skills"

# Capture the trigger keyword block from MANDATORY TRIGGERS: header up to the
# next paragraph boundary (blank line) OR the next known body marker
# ("Use this skill", "Applies to", "Skip", "Use when"). This prevents the
# greedy capture from spilling into the trigger-restatement sentence that
# typically follows the keyword list inside the same description block.
_TRIGGER_RE = re.compile(
    r"MANDATORY TRIGGERS:\s*(.+?)(?=\n\s*\n|\n\s*Use this skill|\n\s*Use when|\n\s*Applies to|\n\s*Skip\b|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def load_skill_triggers() -> dict[str, list[str]]:
    """Walk ~/baker-vault/_ops/skills/<*>/SKILL.md and extract trigger keywords per slug."""
    result: dict[str, list[str]] = {}
    if not VAULT_SKILLS.is_dir():
        print(f"ERROR: skills dir not found: {VAULT_SKILLS}", file=sys.stderr)
        sys.exit(1)
    for entry in sorted(VAULT_SKILLS.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        text = skill_md.read_text(encoding="utf-8")
        m = _TRIGGER_RE.search(text)
        if not m:
            result[entry.name] = []
            continue
        # Trigger keywords are comma-separated, possibly across multiple lines.
        raw = m.group(1).strip()
        # Strip surrounding punctuation and split on commas. The strip set covers:
        # - whitespace (\n\t plus leading/trailing spaces)
        # - sentence punctuation (. ; :)
        # - markdown bold markers (**MANDATORY TRIGGERS:** form leaks trailing **)
        # - quote chars (skills sometimes quote phrases like "add bq permission")
        keywords = [k.strip(" .;:\n\t*\"") for k in raw.split(",")]
        keywords = [k for k in keywords if k]
        result[entry.name] = keywords
    return result


def load_test_cases() -> dict[str, list[dict]]:
    """Load test cases. Prefer YAML if available, fall back to JSON."""
    yml_path = EVALS_DIR / "test-cases.yml"
    json_path = EVALS_DIR / "test-cases.json"
    if _HAS_YAML and yml_path.is_file():
        import yaml
        return yaml.safe_load(yml_path.read_text(encoding="utf-8")) or {}
    if json_path.is_file():
        return json.loads(json_path.read_text(encoding="utf-8"))
    print(f"ERROR: no test cases found at {yml_path} or {json_path}", file=sys.stderr)
    sys.exit(1)


def keyword_fires(keywords: list[str], prompt: str) -> tuple[bool, str | None]:
    """Return (fired, matched_keyword). Match is case-insensitive substring."""
    p = prompt.lower()
    for kw in keywords:
        if kw.lower() in p:
            return True, kw
    return False, None


def main() -> int:
    triggers = load_skill_triggers()
    cases = load_test_cases()

    total = 0
    passed = 0
    failed: list[tuple[str, dict, str]] = []
    missing_skills: list[str] = []
    no_triggers: list[str] = []

    for slug, slug_cases in cases.items():
        if slug not in triggers:
            missing_skills.append(slug)
            continue
        keywords = triggers[slug]
        if not keywords:
            no_triggers.append(slug)
            # Treat as failure for each case — skill has no triggers so nothing can fire.
            for case in slug_cases:
                total += 1
                failed.append((slug, case, "skill has no MANDATORY TRIGGERS"))
            continue
        for case in slug_cases:
            total += 1
            prompt = case.get("prompt", "")
            expect = case.get("expect", "")
            fired, matched = keyword_fires(keywords, prompt)
            if expect == "fire" and fired:
                passed += 1
            elif expect == "no-fire" and not fired:
                passed += 1
            else:
                actual = "fired" if fired else "did not fire"
                detail = f"expected {expect}, got {actual}"
                if matched:
                    detail += f" (matched '{matched}')"
                failed.append((slug, case, detail))

    # Per-skill scorecard.
    per_skill: dict[str, dict[str, int]] = {}
    for slug, slug_cases in cases.items():
        per_skill[slug] = {"total": len(slug_cases), "pass": 0, "fail": 0}
    for slug, case, _ in failed:
        per_skill[slug]["fail"] += 1
    for slug in per_skill:
        per_skill[slug]["pass"] = per_skill[slug]["total"] - per_skill[slug]["fail"]

    # Report.
    print("=" * 70)
    print(f"Skill trigger eval — {total} cases across {len(cases)} skills")
    print("=" * 70)
    print(f"PASS: {passed}/{total} ({100*passed//total if total else 0}%)")
    print(f"FAIL: {len(failed)}")
    if missing_skills:
        print(f"\nSKILLS IN TEST CASES BUT NOT IN CATALOG ({len(missing_skills)}):")
        for s in missing_skills:
            print(f"  - {s}")
    if no_triggers:
        print(f"\nSKILLS WITHOUT MANDATORY TRIGGERS ({len(no_triggers)}):")
        for s in no_triggers:
            print(f"  - {s}")
    if failed:
        print("\nFAILURES:")
        for slug, case, detail in failed:
            prompt = case.get("prompt", "")[:60]
            rationale = case.get("rationale", "")
            print(f"  [{slug}] {detail}")
            print(f"    prompt: {prompt!r}")
            print(f"    rationale: {rationale}")
    print("\nPER-SKILL SCORECARD:")
    for slug in sorted(per_skill.keys()):
        s = per_skill[slug]
        marker = "OK" if s["fail"] == 0 else "FAIL"
        print(f"  [{marker}] {slug}: {s['pass']}/{s['total']}")
    print()

    # Aggregate coverage: skills in catalog without any test cases.
    uncovered = [s for s in triggers if s not in cases]
    if uncovered:
        print(f"SKILLS IN CATALOG BUT WITHOUT TEST CASES ({len(uncovered)}):")
        for s in uncovered:
            print(f"  - {s}")
        print()

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
```

**Make executable + run:**

```bash
chmod +x ~/baker-vault/_ops/scripts/run_skill_trigger_evals.py
python3 ~/baker-vault/_ops/scripts/run_skill_trigger_evals.py
```

### Key constraints
- Stdlib-only when possible. PyYAML is an optional import (graceful fallback to JSON).
- Trigger extraction regex `MANDATORY TRIGGERS:\s*(.+?)(?:\n\n|\Z)` is greedy until next blank line or end of description. b3: spot-check on 3 SKILL.md files to confirm the regex captures multi-line triggers correctly. If a skill's triggers span 3+ lines separated by `,` only (not `\n\n`), the regex catches them all. If a skill has multiple `MANDATORY TRIGGERS:` blocks, only the first matches — this is acceptable for v1 (just don't author multi-block triggers).
- Match logic is case-insensitive substring. Exact-word match was considered but rejected — "dispatch" should match "dispatching" (substring) but the false-positive cost of "art" matching "smart" is acceptable because trigger keywords are intentionally specific (e.g., "dispatch", not "art").
- Runner exit code: 0 if all cases PASS, 1 if any FAIL. Caller can use this for CI / pre-commit / Director-facing summary.
- DO NOT add scoring weights, ML models, or any LLM call. v1 is pure static.

### Verification

```bash
# Run the eval.
python3 ~/baker-vault/_ops/scripts/run_skill_trigger_evals.py
# Expected after starter corpus: PASS rate 100% (12-15/12-15) on the 5 hot skills.
# Coverage report: SKILLS IN CATALOG BUT WITHOUT TEST CASES = ~50 (the rest of the catalog).

# Exit code check
python3 ~/baker-vault/_ops/scripts/run_skill_trigger_evals.py; echo "exit=$?"
# Expected: exit=0
```

If any starter-corpus case FAILS:
- The test case might be wrong: rewrite the prompt or rationale.
- The skill's `MANDATORY TRIGGERS:` might be too narrow / too broad: surface to deputy + b3 may extend the trigger in the same SKILL.md (one-line edit) and re-run.

---

## Fix 3 — Document how to extend the corpus + run the harness

### Problem
The harness is useless if future authors don't know how to add test cases when they ship a new skill or modify an existing one.

### Current state
No docs yet.

### Implementation

**Write `~/baker-vault/_ops/evals/skills/README.md`:**

```markdown
# Skill trigger evals

Static trigger-keyword eval harness for the Baker skill catalog. Runs in seconds; no LLM call; no token cost.

Anchor: `BRIEF_SKILLS_EVAL_HARNESS_1` (Director-ratified 2026-05-25, Q3=A v1 scope).

## Corpus file

The starter corpus lives in **`test-cases.<EXT>`** in this directory, where `<EXT>` is the format b3 chose at implementation time (`yml` if PyYAML was available, `json` otherwise). Only ONE of the two files is committed — confirm which by `ls test-cases.*` before editing. The other format is NOT supported.

## Run

```bash
python3 ~/baker-vault/_ops/scripts/run_skill_trigger_evals.py
```

Exit 0 = all cases PASS. Exit 1 = at least one FAIL — read the per-skill scorecard at the bottom of the report.

## Add a test case for a skill

Open `test-cases.yml` (or `.json`), find the skill slug (top-level key — must match the filesystem name of the directory under `~/baker-vault/_ops/skills/`), append a new case:

```yaml
my-skill-slug:
  - prompt: "natural-language prompt that should or should not fire this skill"
    expect: fire           # or "no-fire"
    rationale: "one sentence explaining the expectation"
```

Re-run the harness. If PASS, commit + push the new case. If FAIL, either (a) fix the prompt to match what should actually fire, or (b) extend the skill's `MANDATORY TRIGGERS:` line in `~/baker-vault/_ops/skills/<slug>/SKILL.md` to cover the missing keyword.

## Cover a new skill

When you ship a new skill, add 2-3 test cases for it in `test-cases.yml`:
- 1-2 cases that SHOULD fire (positive cases — prompts a Director / agent would realistically type).
- 1 case that should NOT fire (negative case — a prompt that brushes near the skill's domain but doesn't actually need it).

This is not optional. A skill without test cases shows up in the "SKILLS IN CATALOG BUT WITHOUT TEST CASES" section of every run. The longer that list, the less the eval covers.

## Foot-guns

- **Trigger keyword too generic.** If a skill's MANDATORY TRIGGERS include "post" (4 chars, common substring), every prompt with "post-deploy" or "important" fires it. Sharpen the keyword (`bus-post`, `mailbox post`).
- **Trigger keyword too specific.** If a skill's MANDATORY TRIGGERS only includes the exact phrase "BRISEN_LAB_REDESIGN_PHASE_1", no Director prompt will ever use that literal. Add the natural-language paraphrase ("brisen lab redesign", "dashboard redesign").
- **Test case prompt not realistic.** "test prompt 1" is not a real prompt. Use what Director / an agent would actually type.

## v2 (not in this brief)

- Behavioral eval against a baseline (does the skill firing actually improve the agent's output?). Requires LLM calls; token-cost-bound.
- Auto-generated test cases from observed Director conversations.
- Continuous run (cron / pre-commit / SessionEnd hook).
- Trend tracking — pass rate over time per skill.
```

### Key constraints
- README must reference the brief id.
- v2 section is a placeholder for future work, not a commitment.

### Verification

```bash
test -f ~/baker-vault/_ops/evals/skills/README.md
head -3 ~/baker-vault/_ops/evals/skills/README.md
# Expected: starts with "# Skill trigger evals"
```

---

## Fix 4 — Initial baseline report + scorecard commit

### Problem
We need a first-run baseline so future runs can be compared to it. Director also wants to see what the harness actually outputs before signing off.

### Current state
N/A — first run.

### Implementation

1. After Fixes 1-3 are complete, run the harness:
   ```bash
   python3 ~/baker-vault/_ops/scripts/run_skill_trigger_evals.py > ~/baker-vault/_ops/evals/skills/baseline-20260525.txt 2>&1
   ```

2. Read the output. The report should show:
   - PASS rate on the 5 hot skills (target: 100% on starter corpus — these are the ones we hand-wrote).
   - "SKILLS IN CATALOG BUT WITHOUT TEST CASES" list — this is the v2 backlog. Long list expected.
   - "SKILLS WITHOUT MANDATORY TRIGGERS" — should be empty IF the migration brief shipped correctly. If non-empty, surface to deputy + flag the skills that need their description edited to add a `MANDATORY TRIGGERS:` line.

3. Commit the baseline file alongside the harness + corpus.

4. Include the report in the ship message (paste under "QC #N — baseline run output").

### Key constraints
- The baseline file is checkpointed at this date so we can compare a future run against it.
- If the starter corpus run shows < 100% PASS, that is a real defect — either the corpus is wrong or the skill trigger is wrong. Fix before declaring shipped.

### Verification

Ship report includes the baseline output. Baseline file committed under `~/baker-vault/_ops/evals/skills/baseline-20260525.txt`.

---

## Files Modified

- `~/baker-vault/_ops/evals/skills/test-cases.yml` (or `.json`) — new file (Fix 1)
- `~/baker-vault/_ops/scripts/run_skill_trigger_evals.py` — new file (Fix 2)
- `~/baker-vault/_ops/evals/skills/README.md` — new file (Fix 3)
- `~/baker-vault/_ops/evals/skills/baseline-20260525.txt` — new file (Fix 4)

## Do NOT Touch

- `~/baker-vault/_ops/skills/<*>/SKILL.md` — the harness READS these; do not modify trigger keywords during eval work. If a trigger needs tightening / broadening, that is a follow-up edit on the source skill, not a change made by this brief.
- `~/baker-vault/_ops/processes/*.md` — out of scope (source process docs stay unchanged).
- `~/.claude/skills/` — out of scope (this brief doesn't touch user-installed skills, only reads vault-side).
- Any pre-commit hook, SessionEnd hook, cron — v2 work. Do NOT install continuous-run automation in v1.

## Quality Checkpoints

1. `~/baker-vault/_ops/evals/skills/` directory exists with `test-cases.{yml,json}` + `README.md` + `baseline-20260525.txt`.
2. `~/baker-vault/_ops/scripts/run_skill_trigger_evals.py` exists, is executable, runs to completion in < 5 seconds.
3. Starter corpus has 5 skills × 2-3 cases each = 12-15 test cases. All PASS on first run.
4. Baseline report committed shows coverage on the starter 5 skills + lists uncovered skills (~50) as the v2 backlog.
5. README explains how to add new test cases — one-paragraph instruction + YAML/JSON shape example.
6. Runner regex spot-checked on 3 SKILL.md files chosen to cover the known edge cases: (a) one plain `MANDATORY TRIGGERS:` (e.g. `agent-bus-posting-contract`), (b) one with markdown bold around the marker like `**MANDATORY TRIGGERS:**`, (c) one with quoted phrase keywords like `"add bq permission"`. Verify keywords list is clean (no `**` survivors, no quote-char survivors, no over-capture into the next paragraph).
7. Runner exits 0 on all-PASS, 1 on any FAIL. Confirmed by deliberately breaking one test case temporarily during dev (then restoring).
8. No PyYAML hard dep. If PyYAML is available, harness uses it; otherwise uses JSON. Document the choice in the ship report.
9. No LLM calls in any of the new code. No `anthropic`, `openai`, or HTTP clients imported in the runner.
10. Pre-commit hook clean. The harness is read-only; cascade-backprop should not fire.

## Verification SQL

N/A — pure filesystem + Python work.

## Gate chain (after ship)

- Gate-1 architecture: deputy (AH2) — verify the harness reads vault skills correctly + corpus YAML/JSON shape is sane
- Gate-2 security: deputy (AH2) — light pass (runner is read-only Python; no `subprocess.run` with user-controlled input; no eval / exec; verify regex DoS surface is bounded)
- Gate-3 picker-architect: SKIP (no install / picker / harness change)
- Gate-4 code-reviewer 2nd-pass: deputy (AH2) — Python code review focus on: regex correctness, edge cases (empty trigger list, missing skill), YAML/JSON fallback path
- Gate-5 merge: lead (AH1) — merges vault commit + runs the harness once + observes baseline report

## Reply target

Post your ship report bus message to **deputy (AH2)** with topic `ship/skills-eval-harness-1`. CC lead. Deputy runs Gates 1+2+4 then hands to lead for Gate-5 merge + first baseline run.

## Director context

Director read thevccorner.com Substack article "Prompts Are Dead. Skills Are the New Moat" on 2026-05-25 — see companion brief `BRIEF_SOPS_TO_SKILLS_MIGRATION_1` for the migration context. The article's most durable claim: **evals are the new gross margin**. We're starting to take that seriously with a v1 harness that's cheap, fast, and proves the pattern.

Director-ratified Q-lock Q3=A (chat 2026-05-25): trigger-keyword match only for v1. Full LLM behavioral eval is v2 work, dispatched separately once v1 has signal worth modeling.

## What NOT to do

- Do NOT call any LLM (Anthropic, OpenAI, Gemini, Grok). v1 is static. v2 is where LLM calls go.
- Do NOT install the runner as a cron / pre-commit hook / SessionEnd hook. Director ratification needed before v1 becomes continuous.
- Do NOT add scoring weights, ML models, or trigger-keyword auto-tuning. v1 is pure regex + substring match.
- Do NOT extend the corpus beyond the 5 hot skills × 2-3 cases starter. Coverage of the rest of the catalog is v2 — `BRIEF_SKILLS_EVAL_CORPUS_EXPANSION` would be its own follow-up.
- Do NOT edit `MANDATORY TRIGGERS:` in any skill's SKILL.md as part of this brief. That changes the corpus the harness is measuring. If a trigger needs adjusting, surface to deputy with the eval report; deputy decides whether to follow-up brief or one-line fix.
- Do NOT auto-generate test cases from any source (conversations, git log, etc.). v1 is hand-authored. Auto-generation is v2.
- Do NOT add the harness to CI / GitHub Actions. v1 is a manual run; lead executes once per release.
