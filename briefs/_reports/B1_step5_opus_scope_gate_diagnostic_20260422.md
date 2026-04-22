# B1 — STEP5_OPUS_SCOPE_GATE_DIAGNOSTIC_1

**From:** Code Brisen #1
**To:** AI Head
**Date:** 2026-04-22
**Task:** read-only investigation — why does the pipeline produce zero real content (10/10 signals terminal as `skip_inbox`, including 9 `hagenauer-rg7` + 1 `lilienmatt`).
**Status:** CLOSED — root cause identified; fix direction recommended.

---

## Headline

**The "Opus scope gate" is not an Opus decision — it is a deterministic Python gate in Step 4.** Opus is never called for any of the 10 completed signals; `skip_inbox` signals take the stub path at `kbl/steps/step5_opus.py:925-937` with zero Anthropic API calls.

**Root cause:** the `_ACTIVE_SECTION_RE` regex in `kbl/steps/step4_classify.py:66-69` fails to match the current heading of `## Actively pressing` in `$BAKER_VAULT_PATH/wiki/hot.md`. The heading reads `## Actively pressing (elevate — deadline/decision this week)`; the regex anchors on `\s*$` immediately after `pressing`, so the match returns `None`. `_parse_hot_md_active()` therefore returns `frozenset()`. With no `KBL_MATTER_SCOPE_ALLOWED` env override, `allowed_scope` is empty on every `classify()` call, and Rule 1 (`primary_matter not in allowed_scope`) fires for every signal. `hagenauer-rg7` is in hot.md but invisible to the parser.

**Classification: PARSER/CONTENT DRIFT** (a specialization of list drift). The list is correct and current; the parser's section-heading regex is too strict.

**Fix size: XS.** One-line regex loosening restores Hagenauer, AO, MO Vienna AM, m365, and Cap Ferrat to scope. A secondary sub-fix (multi-slug bullet parsing) unlocks Lilienmatt + Annaberg + Aukera + NVIDIA + Corinthia.

---

## §1 — Decision flow trace

Step 5 does not carry the scope gate. The gate is Step 4; Step 5 consumes the enum.

```
pipeline_tick._process_signal
  └─► Step 4: kbl/steps/step4_classify.py:classify()           ← scope gate lives here
        ├─ _fetch_signal_row            (step4_classify.py:196-219)
        ├─ _mark_running                (step4_classify.py:222-227)
        ├─ _load_allowed_scope          (step4_classify.py:160-174)  ← Leg 3 read
        │     ├─ load_hot_md            (kbl/loop.py:64-86)
        │     ├─ _parse_hot_md_active   (step4_classify.py:143-157)  ← REGEX FAILURE
        │     └─ _get_scope_env_override(step4_classify.py:130-137)  ← empty in prod
        ├─ _evaluate_rules              (step4_classify.py:259-304)
        │     └─ Rule 1 at LINE 287:
        │         if primary_matter is None or primary_matter not in allowed_scope:
        │             return ClassifyDecision.SKIP_INBOX, False
        ├─ _write_decision              (step4_classify.py:230-245)  ← writes step_5_decision='skip_inbox'
        └─ status → 'awaiting_opus'

  └─► Step 5: kbl/steps/step5_opus.py:synthesize()
        ├─ _fetch_signal_inputs         (step5_opus.py:262-312)
        ├─ _mark_running                (step5_opus.py:318-323)
        └─ branch on decision_str at LINE 924-937:
            if decision_str in (SKIP_INBOX, STUB_ONLY):
                stub = _build_skip_inbox_stub(inputs)  ← deterministic, NO Opus call
                _write_draft_and_advance(...)
                return SynthesisResult(cost_usd=Decimal("0"))
            # FULL_SYNTHESIS path (unreached for these 10 rows) — ledger + R3 + call_opus
```

**Confirmation:** `_build_skip_inbox_stub` (step5_opus.py:604-641) writes the literal title seen in-vault — `"Layer 2 gate: matter not in current scope"` — and a body that explicitly cites the fix surface: *"add the matter to `hot.md` ACTIVE or to the `KBL_MATTER_SCOPE_ALLOWED` env override"* (step5_opus.py:582-591).

---

## §2 — Prompt contents summary (scope instructions)

Reviewed `kbl/prompts/step5_opus_system.txt` (96 lines) and `kbl/prompts/step5_opus_user.txt` (38 lines). **Neither file contains a scope allowlist, a "reject if out-of-scope" instruction, or any current-matters list.** Opus is told to WRITE a Silver draft; it is not asked to judge scope.

- System prompt: G1/G2/G3 rules about Gold + thread continuation; F1/F2 enforce `voice: silver` / `author: pipeline`; hard constraints on no-speculation, target length. Only scope-adjacent text is the illustrative `"hagenauer-rg7"` example in the `hot.md` steering section (line 27) — advisory, not a rule.
- User prompt: template slots — `{primary_matter}`, `{primary_matter_desc}`, `{triage_summary}`, `{gold_context_block}`, `{hot_md_block}`, `{feedback_ledger_block}`, `{signal_raw_text}`, `{iso_now}`. No "active matters" block.

**The task brief framing — "Opus judged every signal out-of-scope" — is not what the code is doing.** The boilerplate title `"Layer 2 gate: matter not in current scope"` is emitted by deterministic Python in `_build_skip_inbox_stub`, not by Opus.

---

## §3 — Scope list location + staleness

**Single source of truth (per code):** union of

1. `$BAKER_VAULT_PATH/wiki/hot.md` → `## Actively pressing` section → `**<slug>**:` bullets, parsed by two regexes at `kbl/steps/step4_classify.py:66-73`.
2. `KBL_MATTER_SCOPE_ALLOWED` env var (comma-separated override).

**hot.md on the MacBook vault (verified 2026-04-22):**

```
## Actively pressing (elevate — deadline/decision this week)

- **hagenauer-rg7**: GC takeover — ...
- **hagenauer-rg7**: Defend against Hagenauer administrator claims ...
- **hagenauer-rg7**: Press containment ...
- **hagenauer-rg7**: Monitor unknown fallout ...
- **ao**: €7M call to Oskolkov ...
- **mo-vie-am**: Residence #8 offer ...
- **nvidia + corinthia**: Proposal to NVIDIA + Corinthia ...
- **mo-vie-am**: Upgrade MOVIE residences sales website.
- **m365**: Kick off Microsoft 365 migration.
- **aukera + mo-vie-am**: Negotiate Aukera ...
- **lilienmatt + annaberg + aukera**: Start moving financing ...
- **cap-ferrat**: Answer BDO questions ...
- **ao**: Build dashboard ...
```

Content is **current and correct** — Director's priorities are plainly captured, matching the worklist.

**Parse result under the current regex (replicated locally, `BAKER_VAULT_PATH=/Users/dimitry/baker-vault`):**

```python
>>> _load_allowed_scope()
frozenset()
>>> for s in ['hagenauer-rg7','lilienmatt','ao','mo-vie-am','m365','cap-ferrat']:
...     print(s, s in _load_allowed_scope())
hagenauer-rg7 False
lilienmatt    False
ao            False
mo-vie-am     False
m365          False
cap-ferrat    False
```

Every single signal therefore routes to SKIP_INBOX regardless of `primary_matter` value.

**Why:** the section regex is

```python
_ACTIVE_SECTION_RE = re.compile(
    r"^##\s+Actively\s+pressing\s*$(?P<body>.*?)(?=^##\s|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
```

The `\s*$` anchor requires the heading line to end at `"pressing"` (plus optional whitespace). The actual heading is `## Actively pressing (elevate — deadline/decision this week)` — so the `$` end-of-line is not reachable and the whole section is never entered. All four H2 headings in hot.md carry parenthetical suffixes (`(elevate on any mention)`, `(always suppress)`) — this is a pattern, not a typo.

Relaxing the heading anchor to `^##\s+Actively\s+pressing\b.*?$` recovers 5 slugs from the current file:

```
['ao', 'cap-ferrat', 'hagenauer-rg7', 'm365', 'mo-vie-am']
```

Multi-slug bullets (`**nvidia + corinthia**`, `**aukera + mo-vie-am**`, `**lilienmatt + annaberg + aukera**`) still do not match — the slug-line regex `\*\*(?P<slug>[A-Za-z0-9_\-]+)\*\*` rejects whitespace and `+` inside the bold fence. That's the secondary sub-issue (§7).

**`KBL_MATTER_SCOPE_ALLOWED` on prod (Render `srv-d6dgsbctgctc73f55730`):** could not read from this session — Render MCP workspace not selected and that selection is guarded. Based on the stub filler's mention of "add to env override" as a fix option, the override is almost certainly unset or empty in prod; if it were set, the Hagenauer signals would not have routed to SKIP_INBOX. **Recommend AI Head verify via `env | grep KBL_MATTER_SCOPE_ALLOWED` on Render before taking the fix path.**

---

## §4 — Stored evidence on completed rows

Queried `signal_queue` for the 10 rows called out in the brief (ids 2, 12, 17, 18, 20, 25, 50-53) via `baker_raw_query`. Results:

| id | status | primary_matter | triage_score | step_5_decision | cross_link_hint |
|----|--------|----------------|--------------|-----------------|-----------------|
| 2 | completed | `hagenauer-rg7` | 80 | `skip_inbox` | false |
| 12 | completed | `hagenauer-rg7` | 80 | `skip_inbox` | false |
| 17 | completed | `lilienmatt` | 80 | `skip_inbox` | false |
| 18 | completed | **NULL** | 80 | `skip_inbox` | false |
| 20 | completed | `hagenauer-rg7` | 70 | `skip_inbox` | false |
| 25 | completed | `hagenauer-rg7` | 80 | `skip_inbox` | false |
| 50 | completed | `hagenauer-rg7` | 70 | `skip_inbox` | false |
| 51 | completed | `hagenauer-rg7` | 70 | `skip_inbox` | false |
| 52 | completed | `hagenauer-rg7` | 80 | `skip_inbox` | false |
| 53 | completed | `hagenauer-rg7` | 80 | `skip_inbox` | false |

**There is no stored Opus response for any of these rows** — `opus_draft_markdown` holds the deterministic stub, not a model output. No `kbl_cost_ledger` row was written by Step 5 for these signals (step5_opus.py:927-931 writes the stub and bypasses the ledger writer entirely). The "what did Opus say" question from the brief has no answer: Opus was never consulted.

Row 18 (NULL primary_matter) is consistent with both the bug hypothesis and the code as-written: Rule 1's first clause (`primary_matter is None`) fires regardless of `allowed_scope`, so id 18 would be `skip_inbox` even if the regex were fixed. The other 9 rows would have flowed through had `allowed_scope` contained `hagenauer-rg7` / `lilienmatt`.

---

## §5 — Root-cause classification

**Primary: PARSER/CONTENT DRIFT (list drift sub-type).**

- The list (hot.md) is semantically correct — Hagenauer, AO, MO Vienna AM, m365, Cap Ferrat, Lilienmatt/Annaberg/Aukera, NVIDIA/Corinthia are plainly declared ACTIVE.
- The parser's heading regex is too strict for the author's heading convention. The other three H2s in hot.md all carry parenthetical suffixes, so the convention is stable — the code is the outlier.

**Not prompt drift.** Opus never runs for skip_inbox; the prompt is not on the critical path for these 10 rows. Step 5's system+user prompt also contains no scope allowlist to drift.

**Secondary (independent, lower impact): multi-slug bullet format not parsed.**

- `**lilienmatt + annaberg + aukera**:` and `**nvidia + corinthia**:` are invisible to `_ACTIVE_SLUG_LINE_RE`. Under the primary fix alone, Lilienmatt (row 17) still routes to SKIP_INBOX. Director's hot.md convention mixes single-slug and combo bullets, so either the regex must learn combos or the file must be rewritten one-slug-per-bullet.

---

## §6 — Fix-direction recommendation

**Recommended path: (a) — regex loosening in `kbl/steps/step4_classify.py`. Effort: XS (≤30 min incl. tests).**

Three concrete edits, isolated to one file + one test file:

1. Heading anchor (primary fix — unlocks 5 slugs immediately):
   ```python
   _ACTIVE_SECTION_RE = re.compile(
       r"^##\s+Actively\s+pressing\b.*?$(?P<body>.*?)(?=^##\s|\Z)",
       re.IGNORECASE | re.MULTILINE | re.DOTALL,
   )
   ```
   The `\b.*?$` replaces `\s*$` so any trailing parenthetical is tolerated.

2. (Optional, combo fix — unlocks Lilienmatt + Aukera + NVIDIA + Corinthia) Extend `_ACTIVE_SLUG_LINE_RE` body match so combo bullets yield their component slugs:
   ```python
   _ACTIVE_SLUG_LINE_RE = re.compile(
       r"^\s*[-*]?\s*\*\*(?P<inner>[A-Za-z0-9_\-+\s]+)\*\*\s*:",
       re.MULTILINE,
   )
   ```
   with a follow-up `re.split(r"\s*\+\s*", inner)` inside `_parse_hot_md_active()` to yield the N tokens. Each token filtered against `slug_registry.active_slugs()` so any junk between the stars is dropped safely.

3. Tests: add two fixtures to `tests/test_step4_classify.py` (or wherever `_parse_hot_md_active` is exercised) covering (a) a parenthetical heading and (b) a `**slug + slug**:` combo bullet. Both assert the expected slug set.

**Alternative path (b) — rewrite hot.md.** The Director can drop the parenthetical suffixes and flatten combo bullets. Works but inverts the contract (code dictates author style to a Gold-voice file). Not recommended.

**Alternative path (c) — set `KBL_MATTER_SCOPE_ALLOWED` on Render.** Unblocks prod in one env-var push without a code change. Reasonable as a short-term mitigation *while* the PR merges, but leaves the regex brittle against the next author-side nudge. If AI Head wants prod unblocked tonight, set `KBL_MATTER_SCOPE_ALLOWED=hagenauer-rg7,ao,mo-vie-am,m365,cap-ferrat,lilienmatt,annaberg,aukera,nvidia,corinthia` as a bridge, then land (a) tomorrow.

**Flagged edit location for the follow-up brief:**
- `kbl/steps/step4_classify.py:66-69` (`_ACTIVE_SECTION_RE`) — primary
- `kbl/steps/step4_classify.py:70-73` + `kbl/steps/step4_classify.py:143-157` (`_ACTIVE_SLUG_LINE_RE` + `_parse_hot_md_active`) — combo bullets

---

## §7 — Adjacent findings

1. **Combo-bullet pattern is load-bearing in hot.md.** Three of the 13 actively-pressing lines use `**slug1 + slug2 + slug3**:` shape. Under the primary fix alone, these still drop. Lilienmatt appears ONLY inside a combo bullet; without the combo fix (or a hot.md rewrite), Lilienmatt remains dark.

2. **Empty-scope state is silent-by-design, not loud.** `step4_classify.py:146-151` documents empty-set as "valid zero-Gold state" under Inv 1. Combined with an INFO-level log at `step4_classify.py:357-362` (`layer2_blocked: primary_matter=... not in allowed=[]`), the parser breakage cannot page anyone — it looks like "Director hasn't declared priorities today." Consider adding a WARN when `load_hot_md()` returns non-empty content but `_parse_hot_md_active()` returns empty: that is the exact signature of the current failure and would have surfaced it Day 1.

3. **Rule 1 conflates two failure modes.** `primary_matter is None` and `primary_matter not in allowed_scope` both map to `SKIP_INBOX` with the same boilerplate title. Row 18 (NULL primary_matter, a Step 3 extraction gap) and rows 2/12/20/25/50-53 (Step 3 extracted the right slug, scope gate rejected it) are indistinguishable at the Director level. A Step 6-visible reason code in the stub frontmatter (`skip_reason: null_matter` vs `skip_reason: out_of_scope`) would let the Director triage two different real problems.

4. **Env-override path is effectively undocumented-in-practice.** `KBL_MATTER_SCOPE_ALLOWED` appears only in step4_classify.py constants and step5_opus.py stub body. No README, no CLAUDE.md, no hot.md pointer. Directors who read only hot.md have no way to discover it. Worth a two-line note in hot.md header ("parser reads `## Actively pressing`; headings must be `## Actively pressing[…]`; combo bullets use `**slug1 + slug2**:`") until the parser is hardened.

5. **CROSS_LINK_ONLY is dead code but claimed live.** `ClassifyDecision.CROSS_LINK_ONLY` (step4_classify.py:94) is documented "Phase 2 — unreachable today" and Step 5 asserts it's never seen (step5_opus.py:17). Not related to this diagnostic; flagged for pruning in a future cleanup brief.

6. **`primary_matter=null` is routine.** Of the 10 rows, only id 18 had NULL primary_matter. Step 3's matter-extraction is otherwise doing its job — the bottleneck is the scope gate, not the extractor.

---

## §8 — Verification commands used (for reviewer reproduction)

```bash
# hot.md regex reproduction
python3 -c "
import sys; sys.path.insert(0, '.')
import os
os.environ['BAKER_VAULT_PATH'] = '/Users/dimitry/baker-vault'
from kbl.steps.step4_classify import _parse_hot_md_active, _load_allowed_scope
from kbl.loop import load_hot_md
hot = load_hot_md()
print('parsed:', sorted(_parse_hot_md_active(hot)))
print('allowed:', sorted(_load_allowed_scope()))
"
# → parsed: []
# → allowed: []

# stored-row evidence
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_raw_query","arguments":{"sql":"SELECT id, primary_matter, triage_score, step_5_decision FROM signal_queue WHERE id IN (2,12,17,18,20,25,50,51,52,53) ORDER BY id"}}}'
```

---

## Summary for AI Head

- **Not an Opus problem. Not a prompt problem. Not a model-config problem.** A single heading-regex mismatch in `kbl/steps/step4_classify.py:66-69` empties `allowed_scope` on every classify invocation; Rule 1 then rejects everything.
- **Fix is XS** — one-line regex loosening + 2-line test, contained in Step 4. Follow-up second fix for combo bullets unlocks Lilienmatt.
- **Prod can be unblocked tonight** via `KBL_MATTER_SCOPE_ALLOWED` env-var push on Render if you don't want to wait for the PR cycle.
- **Recommend follow-up brief: `BRIEF_STEP4_SCOPE_GATE_PARSER_HARDENING_1`** covering edits 1+2+WARN log at §7.2 + (optional) `skip_reason` frontmatter field from §7.3.

— B1, 2026-04-22
