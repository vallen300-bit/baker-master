# B1 Diagnostic — STEP5_OPUS_SCOPE_GATE_DIAGNOSTIC_1

**From:** Code Brisen #1
**To:** AI Head
**Date:** 2026-04-22
**Task:** `briefs/_tasks/CODE_1_PENDING.md` — post-Gate-1 content-quality investigation
**Scope:** read-only, no PR
**Effort:** ~30 min (inside 2-h timebox)

---

## TL;DR (for AI Head)

**It is not Opus.** Not a single signal has ever reached Opus. Every
`skip_inbox` decision comes from **Step 4 (deterministic policy
classifier)** before any LLM call — the "Layer 2 gate" title emitted
by Step 5's stub writer just echoes Step 4's decision.

**Root cause is parser drift in one regex.** `kbl/steps/step4_classify.py:66-69`:

```python
_ACTIVE_SECTION_RE = re.compile(
    r"^##\s+Actively\s+pressing\s*$(?P<body>.*?)(?=^##\s|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
```

The live header in `~/baker-vault/wiki/hot.md` reads
`## Actively pressing (elevate — deadline/decision this week)` —
the `\s*$` anchor rejects the parenthetical suffix, so the regex
**returns no match**, the ACTIVE set is **empty**, and Rule 1 fires
for **every** non-null primary_matter.

**Classification:** list drift (parser-side), NOT content drift, NOT
prompt drift. The hot.md content is authoritative + current.

**Fix direction:** S (~30 min + tests). Two-line parser patch + ~5
regression tests. Detail in §6.

---

## 1. Decision flow trace — claim → decision-write

`_process_signal_remote` (pipeline_tick.py) pulls a row and runs the
deterministic pipeline. The "Layer 2 gate" decision lives inside Step
4, not Step 5:

| Step | File:line | Purpose |
|------|-----------|---------|
| 1 | `kbl/pipeline_tick.py:249-255` | step1_triage claims row, writes triage_score |
| 2 | `kbl/pipeline_tick.py:264-270` | step2_resolve — thread paths |
| 3 | `kbl/pipeline_tick.py:272-277` | step3_extract — entities |
| **4** | `kbl/steps/step4_classify.py:310-365` | **deterministic policy — writes step_5_decision** |
| 4a | `step4_classify.py:324` | `_fetch_signal_row` — loads triage_score, primary_matter, related_matters, resolved_thread_paths |
| 4b | `step4_classify.py:328` | `allowed = _load_allowed_scope()` — Inv 3 fresh read per call |
| 4c | `step4_classify.py:160-174` | `_load_allowed_scope` = `_parse_hot_md_active(load_hot_md()) \| _get_scope_env_override()` |
| 4d | `step4_classify.py:143-157` | `_parse_hot_md_active` — the parser that fails |
| 4e | `step4_classify.py:259-304` | `_evaluate_rules` first-match-wins table |
| 4f | **`step4_classify.py:287-288`** | **Rule 1 (Layer 2 gate):** `if primary_matter is None or primary_matter not in allowed_scope: return SKIP_INBOX, False` |
| 4g | `step4_classify.py:357-362` | `logger.info("layer2_blocked: primary_matter=%r not in allowed=%s", ...)` |
| 4h | `step4_classify.py:364` | `_write_decision(..., SKIP_INBOX, False, "awaiting_opus")` |
| 5 | `kbl/steps/step5_opus.py:726-738` | `synthesize()` routes on step_5_decision; on SKIP_INBOX → `_build_skip_inbox_stub` + advance. **NO Opus call.** No cost ledger row. |
| 5a | `step5_opus.py:_build_skip_inbox_stub` | Emits the stub with title "Layer 2 gate: matter not in current scope" — same title regardless of which matter was rejected |

**Important:** Step 5's Opus prompts (`step5_opus_system.txt` +
`step5_opus_user.txt`) are **never reached** on SKIP_INBOX. Opus has
no input into which signals get rejected.

## 2. Prompt contents summary

### 2.1 Step 5 prompts — NOT in play for this bug

Step 5's Opus prompts only run on `FULL_SYNTHESIS` (see `synthesize()`
at `step5_opus.py:~754` — the FULL_SYNTHESIS branch is past the
early-return-for-stub guard at line 726).

For reference, the prompts don't carry the scope list either — they
see `primary_matter: <slug>` from the already-classified row and tell
Opus to write prose respecting prior Gold. No scope gating happens at
the prompt layer.

### 2.2 Step 4 — no prompt

Step 4 is pure Python policy. Docstring at `step4_classify.py:1-34`:

> No Ollama call, no Anthropic call, no Voyage call, no cost ledger row —
> Step 4 is pure Python policy.

Scope is a frozenset loaded on every call. Rules are a 6-row table
evaluated first-match-wins.

**There is no prompt to drift.** Step 4 drift must be in code or in
the hot.md parser's view of the data.

## 3. Scope list — location, content, staleness

### 3.1 Authoritative source

`$BAKER_VAULT_PATH/wiki/hot.md`, loaded by `kbl.loop.load_hot_md` on
each `classify()` call (`step4_classify.py:173`). Full path in dev:
`/Users/dimitry/baker-vault/wiki/hot.md`. Updated 2026-04-18 per the
frontmatter `updated` key.

### 3.2 Content (live, current)

Sections: `## Actively pressing (elevate — deadline/decision this
week)`, `## Watch list (elevate on any mention)`,
`## Actively frozen`, `## Null / routine (always suppress)`.

Active pressing slugs present in the current file (per my eyeball
scan):
`hagenauer-rg7`, `ao`, `mo-vie-am`, `nvidia`, `corinthia`, `m365`,
`aukera`, `lilienmatt`, `annaberg`, `cap-ferrat` — plus multi-slug
lines like `- **lilienmatt + annaberg + aukera**:` and
`- **nvidia + corinthia**:`.

**Every matter currently in the signal_queue IS in the hot.md file.**
Director-side content is fine.

### 3.3 Parser regex — broken on current header

```python
_ACTIVE_SECTION_RE = re.compile(
    r"^##\s+Actively\s+pressing\s*$(?P<body>.*?)(?=^##\s|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
```

The anchor `\s*$` requires end-of-line after "pressing". The live
header has `(elevate — deadline/decision this week)` on the same
line — non-whitespace content. Regex returns no match.

Verified against live hot.md via direct import:

```
$ python3 -c "from kbl.steps.step4_classify import _parse_hot_md_active
               from pathlib import Path
               print(_parse_hot_md_active(
                   Path('/Users/dimitry/baker-vault/wiki/hot.md').read_text()
               ))"
frozenset()
```

### 3.4 Env-override fallback

`KBL_MATTER_SCOPE_ALLOWED` is the env-side escape hatch
(`step4_classify.py:57,130-137`). If set on Render, `_load_allowed_scope`
unions it with the hot.md set. Render service config (via MCP) doesn't
expose env-var values in the service-detail response, but the symptom
proves it's not covering the Hagenauer / Lilienmatt gap — 100% of
non-null-primary signals hit SKIP_INBOX (see §4), which means the
allowed set is either empty or missing Hagenauer / Lilienmatt.
Either way: **hot.md parser is the load-bearing source and it fails.**

### 3.5 Secondary parser issue — multi-slug bullets

Even once the section regex is fixed, the slug-line regex:

```python
_ACTIVE_SLUG_LINE_RE = re.compile(
    r"^\s*[-*]?\s*\*\*(?P<slug>[A-Za-z0-9_\-]+)\*\*\s*:",
    re.MULTILINE,
)
```

only handles single-token bold spans. It won't extract anything from
`- **lilienmatt + annaberg + aukera**:` because the content between
`**...**` contains ` + ` characters outside the `[A-Za-z0-9_\-]+`
character class. Today's hot.md uses multi-slug format on at least
two lines (`lilienmatt + annaberg + aukera`, `nvidia + corinthia`).

The hot.md file explicitly documents the multi-slug format (comment
at line 13):

> Tags in bold at the start of each bullet are canonical slugs from
> `slugs.yml`. Multi-tag bullets use `slug1 + slug2` (primary first).

So the file format is intentional. The parser needs to catch up.

## 4. Stored evidence on completed rows

Live PG query via Baker MCP:

```sql
SELECT id, primary_matter, related_matters, triage_score,
       step_5_decision, status
FROM signal_queue
WHERE id IN (2, 12, 17, 18, 20, 25, 50, 51, 52, 53)
ORDER BY id;
```

| id | primary_matter | triage_score | step_5_decision | status |
|----|---------------|--------------|-----------------|--------|
| 2 | hagenauer-rg7 | 80 | skip_inbox | completed |
| 12 | hagenauer-rg7 | 80 | skip_inbox | completed |
| 17 | lilienmatt | 80 | skip_inbox | completed |
| 18 | *(NULL)* | 80 | skip_inbox | completed |
| 20 | hagenauer-rg7 | 70 | skip_inbox | completed |
| 25 | hagenauer-rg7 | 80 | skip_inbox | completed |
| 50 | hagenauer-rg7 | 70 | skip_inbox | completed |
| 51 | hagenauer-rg7 | 70 | skip_inbox | completed |
| 52 | hagenauer-rg7 | 80 | skip_inbox | completed |
| 53 | hagenauer-rg7 | 80 | skip_inbox | completed |

**There is NO `result` column stored with "what Opus said"** because
Opus was never called. On SKIP_INBOX, `synthesize()` emits the
deterministic stub and returns (`step5_opus.py:726-738`). No
`kbl_cost_ledger` rows for these signals either — confirmable via
`SELECT COUNT(*) FROM kbl_cost_ledger WHERE signal_id IN (...)` =
0 (not checked here but structurally guaranteed by the code path).

### 4.1 Whole-queue distribution

```sql
SELECT step_5_decision, status, COUNT(*) n, MIN(id), MAX(id)
FROM signal_queue GROUP BY step_5_decision, status;
```

| decision | status | n | min | max |
|----------|--------|---|-----|-----|
| skip_inbox | awaiting_commit | 2 | 47 | 55 |
| skip_inbox | completed | 20 | 2 | 53 |
| skip_inbox | opus_failed | 1 | 34 | 34 |
| skip_inbox | pending | 33 | 1 | 56 |

**56 signals total, 56 skip_inbox, 0 full_synthesis, 0 stub_only.**
The noise-band path (`stub_only`) hasn't fired either — every signal
hits Rule 1 before Rule 2.

### 4.2 Primary-matter distribution

| primary_matter | n |
|----------------|---|
| hagenauer-rg7 | 41 |
| annaberg | 8 |
| lilienmatt | 3 |
| (NULL) | 2 |
| balducci | 1 |
| wertheimer | 1 |

**41 + 3 = 44 of 56 signals** carry a slug that would pass the gate
if the parser worked (hagenauer-rg7 + lilienmatt are in the
Actively-pressing section). `annaberg` is on the Watch list — it
would still skip under strict Actively-pressing-only policy, but
it's also in the `lilienmatt + annaberg + aukera` multi-slug line
in Actively pressing. So `annaberg` flows through too if fix #2
ships (see §6).

### 4.3 Adjacent kbl_log evidence

```sql
SELECT level, component, signal_id, message
FROM kbl_log WHERE component='finalize' AND ts > NOW() - INTERVAL '6 hours'
ORDER BY ts DESC LIMIT 14;
```

14 WARN rows all `body: Value error, body too short (226-231 chars;
min 300)` across signals 38-56. These are pre-PR-#36 retry attempts
— my audit landed the 300-char body floor so new ticks no longer
hit this. Confirms the Axis 3 fresh-conn path is doing its job
(these rows made it to terminal state instead of stranding).

## 5. Root-cause classification

| Candidate cause | Verdict | Evidence |
|----------------|---------|----------|
| **List drift (parser-side)** | **ROOT CAUSE** | `_ACTIVE_SECTION_RE` returns no match against the live hot.md header; ACTIVE set is empty; every non-null primary_matter signal fails Rule 1. Verified by direct `_parse_hot_md_active()` import + eval. |
| List drift (content-side) | RULED OUT | Hot.md is current (updated 2026-04-18) and contains every slug present in signal_queue. Director-side content is fine. |
| Prompt drift | RULED OUT (non-applicable) | Step 4 has no prompt. Opus is never called for SKIP_INBOX rows. Step 5 prompts are load-bearing only on FULL_SYNTHESIS, which hasn't happened. |
| Model config (temp / tokens / etc.) | RULED OUT (non-applicable) | No model call. |
| Secondary: multi-slug bullet format | LATENT — becomes load-bearing once fix #1 ships | `_ACTIVE_SLUG_LINE_RE` doesn't parse `**slug1 + slug2**` bullets. Fixing the section regex alone recovers single-slug bullets (hagenauer-rg7, ao, m365, cap-ferrat, lilienmatt on line 40 watch list — but watch list isn't parsed either, see §7 note). Multi-slug bullets stay dropped. |

## 6. Fix direction (not a PR — direction)

Recommended option: **(a) + (b), but not (d).**

### Fix #1 — Section header regex (XS)

`kbl/steps/step4_classify.py:66-69`. Loosen the end-of-line anchor:

```python
# Before:
r"^##\s+Actively\s+pressing\s*$(?P<body>.*?)(?=^##\s|\Z)"
# After (proposed):
r"^##\s+Actively\s+pressing\b[^\n]*\n(?P<body>.*?)(?=^##\s|\Z)"
```

Accepts any tail on the header line (parenthetical, emoji, section
tag, etc.) then captures body up to the next H2.

### Fix #2 — Multi-slug bullet parsing (S)

`kbl/steps/step4_classify.py:70-73`. Replace the single-slug regex
with a two-step parse: first extract the full bold span from each
bullet, then split into slug tokens.

```python
# Match the bolded header on each bullet (any content inside **...**).
_ACTIVE_BULLET_BOLD_RE = re.compile(
    r"^\s*[-*]?\s*\*\*(?P<bold>[^*\n]+)\*\*\s*:",
    re.MULTILINE,
)
# Extract canonical slugs from the bold span (handles "a + b + c"
# multi-tag format per hot.md line 13 comment).
_SLUG_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_\-]*")

def _parse_hot_md_active(hot_md_content):
    ...
    slugs = set()
    for m in _ACTIVE_BULLET_BOLD_RE.finditer(section.group("body")):
        bold = m.group("bold").lower()
        slugs.update(_SLUG_TOKEN_RE.findall(bold))
    return frozenset(slugs)
```

### Regression tests (bundled with the fix, S)

1. `test_parse_hot_md_active_with_parenthetical_section_header` — header with " (elevate — ...)" returns the expected slug set.
2. `test_parse_hot_md_active_with_multi_slug_bullet` — `**a + b + c**:` yields {a, b, c}.
3. `test_parse_hot_md_active_live_vault_header` — read the real `~/baker-vault/wiki/hot.md` (skip on CI if BAKER_VAULT_PATH points at fixtures), assert `hagenauer-rg7` + `lilienmatt` are in the result.
4. `test_parse_hot_md_active_empty_section_body_returns_empty` — existing behavior.
5. `test_parse_hot_md_active_missing_section_still_returns_empty` — existing behavior.

### Data recovery (separate brief)

Pipeline re-run for the 56 skip_inbox rows would need
`UPDATE signal_queue SET status='awaiting_classify', step_5_decision=NULL,
target_vault_path=NULL, final_markdown=NULL ... WHERE step_5_decision='skip_inbox'`
— destructive, requires Director auth, and only some of those rows
should be reprocessed (the genuinely out-of-scope ones should stay
as stubs). Flag for a follow-up recovery brief once the parser fix
is in.

### Alternative: env-only unblock (not recommended)

Setting `KBL_MATTER_SCOPE_ALLOWED=hagenauer-rg7,lilienmatt,annaberg,
ao,mo-vie-am,aukera,...` on Render works immediately without a code
change, but moves the source-of-truth off hot.md (which the Director
owns) into Render env (which the Director doesn't maintain). Net
drift risk higher than the XS code fix. Only consider if the parser
fix is blocked.

### Effort total

**Fix #1 + Fix #2 + tests = S (~45-60 min).**

## 7. Adjacent findings

1. **Bridge is fine.** `primary_matter` and `related_matters` arrive
   correctly on every signal. The slugs match hot.md content.
2. **Step 1 triage is fine.** Scores of 70-80 are justified for
   Hagenauer / Lilienmatt signals. The gate fails AFTER triage.
3. **Watch list is not parsed.** The classifier only reads
   `## Actively pressing`. Signals tagged with Watch-list-only
   slugs (`mrci`, `mo-prague`, `franck-muller`, `brisen-pr`,
   `mo-vie-am`, `mo-vie-exit`, `personal`) would skip even with the
   parser fix. The current queue has 1 `annaberg` signal that
   wouldn't be rescued by fix #1 alone — but is rescued by fix #2
   (it's in the `lilienmatt + annaberg + aukera` multi-slug line).
   Separate decision: should watch-list matter cascade to allowed
   scope too? Out of scope for this diagnostic — surface as a
   follow-up policy question for Director.
4. **No Opus cost was spent.** Dollar-terms this failure mode is
   free — Step 4 rejects before Step 5's cost gate. But content
   throughput is zero, which is the Gate 2 problem.
5. **PR #36 pre-existing body-too-short errors visible in
   `kbl_log`.** The 300-char floor I landed today catches these —
   the 14 WARN rows pre-date the deploy. New ticks will stay clean
   on body length.
6. **"Layer 2 gate" stub title is misleading.** It says "matter not
   in current scope" but the actual cause (for this queue) is
   "parser can't read the scope list" — not "Director excluded the
   matter." A helpful belt-and-suspenders would be for the stub to
   name the expected slug set in the body so the Director can see
   "I expected these 0 slugs" and notice the drift. Low priority;
   surface if doing broader stub-prose work.

— B1
