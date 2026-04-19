# KBL-B Step 5 — `opus_step5` Production Prompt (Claude Opus cloud)

**Author:** Code Brisen 3 (B3) — empirical lead
**Task:** `briefs/_tasks/CODE_3_PENDING.md` (2026-04-18 dispatch — STEP5-OPUS-PROMPT)
**Model target:** `claude-opus-4-7` (1M context, cloud Anthropic API).
**Fires only when:** Step 4 `_decide_step5_path()` returns `step_5_decision='full_synthesis'`. `stub_only` / `cross_link_only` / `skip_inbox` / `paused_cost_cap` branches write deterministic stubs upstream and do NOT call this prompt (KBL-B §2 Step 5, §4.6).
**Writes to:** `signal_queue.opus_draft_markdown TEXT` (KBL-B §4.6).
**Consumed by:** Step 6 `finalize()` (deterministic per REDIRECT 2026-04-18 — no LLM second pass). Frontmatter + body from this prompt are the canonical Silver artifact; `finalize()` only validates schema, appends `related_matters[]` cross-link stubs, and writes. Opus output MUST therefore be vault-ready.
**CHANDA compliance (binding):**
- **Inv 1** — `{gold_context_by_matter}` is passed on every call; zero-Gold is represented as the empty-sentinel block and the prompt handles it as a valid state, not an error (§1.2 rule Z).
- **Inv 3** — `{hot_md_block}` and `{feedback_ledger_recent}` are re-read from source on every call (same `kbl/loop.py` helpers as Step 1, no caching).
- **Inv 8** — frontmatter `voice: silver` emitted unconditionally. Step 5 never self-promotes to `gold` (§1.3 rule F1).
- **Inv 10** — this prompt is a stable template. All variability comes through data blocks.
- **Inv 4** — frontmatter `author: pipeline` (machine-generated Silver). `author: director` is reserved for Gold promotions and this prompt never writes it.

**Q1 Loop Test self-assessment:** prompt DESIGN is the Leg 1 compounding mechanism (it is where Gold is read, honored, and fed back into Silver). §1.2 rules G1-G3 codify the mandatory handling. A reviewer disagreeing with any G-rule is flagging a Leg 1 concern and MUST escalate per CHANDA §5. See §4.

---

## 1. The prompt template

### 1.1 Builder

**File:** `kbl/prompts/step5_opus.py` (proposal — or inline in `kbl/steps/opus_step5.py`)

```python
from kbl.slug_registry import describe
from kbl.loop import load_hot_md, load_recent_feedback, render_ledger
from kbl.vault import load_gold_context_by_matter  # proposed — see §1.4

def build_step5_opus_prompt(
    signal_raw_text: str,
    extracted_entities: dict,
    primary_matter: str | None,
    related_matters: list[str],
    vedana: str,
    triage_summary: str,
    resolved_thread_paths: list[str],
    conn,
) -> tuple[str, str]:
    """Build the Step 5 Opus synthesis prompt. Returns `(system, user)` —
    the stable `system` block is prompt-cacheable across signals; the `user`
    block carries per-signal data.

    CHANDA Inv 1: `gold_context_by_matter` is always loaded — empty string
    on zero-Gold matters, not omitted. CHANDA Inv 3: `hot.md` + feedback
    ledger are re-read on every call (no caching). Both are mandatory.

    `conn` is the live psycopg connection passed in by the Step 5 pipeline
    worker (same ownership model as Step 1 per PR #6).

    Callers MUST NOT call Opus directly on `stub_only` / `cross_link_only` /
    `skip_inbox` / `paused_cost_cap` signals — `_decide_step5_path()` at
    the Step 4→5 boundary is the gate (KBL-B §2 Step 5 / §4.5). This
    builder trusts upstream filtering."""

    # CHANDA Inv 1 read — mandatory on every call, even when matter is null.
    # Empty-Gold is represented by the string "(no prior Gold entries for
    # this matter)" so the model sees an explicit zero-state, not an absent
    # block (prompt caching prefers a stable shape).
    if primary_matter:
        gold_context = load_gold_context_by_matter(primary_matter)
        gold_context_block = gold_context if gold_context else "(no prior Gold entries for this matter)"
    else:
        gold_context_block = "(primary_matter is null — no matter-scoped Gold to read)"

    # CHANDA Inv 3 reads — same helpers as Step 1, stateless.
    hot_md_content        = load_hot_md()
    hot_md_block          = hot_md_content if hot_md_content else "(no current-priorities cache available)"
    ledger_rows           = load_recent_feedback(conn, limit=None)  # env default — see §1.4 OQ
    rendered              = render_ledger(ledger_rows)
    feedback_ledger_block = rendered if rendered else "(no recent Director actions)"

    system = _STEP5_SYSTEM_TEMPLATE  # stable, cacheable — see §1.2

    user = _STEP5_USER_TEMPLATE.format(
        signal_raw_text       = signal_raw_text[:50000],
        extracted_entities    = _render_entities(extracted_entities),
        primary_matter        = primary_matter or "null",
        primary_matter_desc   = (describe(primary_matter) if primary_matter else "no matter"),
        related_matters       = ", ".join(related_matters) if related_matters else "(none)",
        vedana                = vedana,
        triage_summary        = triage_summary,
        resolved_thread_paths = _render_paths(resolved_thread_paths),
        gold_context_block    = gold_context_block,
        hot_md_block          = hot_md_block,
        feedback_ledger_block = feedback_ledger_block,
        iso_now               = _iso_utc_now(),
    )
    return system, user
```

### 1.2 Template — `system` block (prompt-cacheable)

Stable across signals. Cached via Anthropic prompt-caching on the system block. Changes to this string are a prompt-version event — bump cache key + re-measure cost.

```python
_STEP5_SYSTEM_TEMPLATE = """You are the synthesis agent for the Baker wiki (KBL — Knowledge Base Loop). You receive one business signal (email thread, WhatsApp thread, meeting transcript, or Director scan query) plus structured context, and you produce ONE Markdown document: YAML frontmatter + prose body. This document becomes a Silver wiki entry — a draft the Director will read and may promote to Gold.

## Core rules (non-negotiable — violations break the learning loop)

**G1 — Read the Gold, honor the Gold.** The `gold_context_by_matter` block contains ALL existing Director-promoted Gold entries for `primary_matter`. Before writing anything, read it. Your body MUST respect those judgments. If the current signal CONTRADICTS prior Gold, flag it explicitly with a line beginning `⚠ CONTRADICTION:` inside the body. Never silently overwrite. Never paraphrase Gold as if it were your own conclusion — Gold is Director judgment, your role is to extend it, not replace it.

**G2 — Zero Gold is a valid state.** If `gold_context_by_matter` says `(no prior Gold entries for this matter)` or `(primary_matter is null — no matter-scoped Gold to read)`, produce a FIRST entry. Tone: "this is the opening record for the matter." Do NOT invent prior history. Do NOT refuse. The pipeline requires a Silver draft on every `full_synthesis` decision.

**G3 — Thread continuation, not parallel narrative.** If `resolved_thread_paths` is non-empty, the prose MUST explicitly continue / amend / correct those existing vault pages. Reference them by path in a `## Continues` or `## Amends` block. Do NOT write a standalone narrative that duplicates state the vault already has.

**F1 — Frontmatter `voice: silver` always.** You never emit `voice: gold`. Promotion is the Director's action, triggered by explicit frontmatter edit, not by this prompt.

**F2 — Frontmatter `author: pipeline` always.** You are the machine-generated Silver writer. `author: director` is reserved for Gold promotions (CHANDA Inv 4 protection engages on that value — pipeline never writes it). Use `pipeline`.

## Hard constraints (signal-level discipline)

1. **No speculation.** Everything in the body must be derivable from `signal_raw_text`, `extracted_entities`, or the context blocks. If you need to fill a gap, say so ("recipient unclear from thread") — do not fabricate.
2. **No hallucinated participants, amounts, dates, or reference IDs.** The extracted entities are the authorized set. If a name or number appears in the signal text but not in entities, you may reference it but must attribute it to the signal text, not claim independent knowledge.
3. **No long verbatim quotes.** Any direct quote from raw signal longer than ~30 characters must carry a source-line citation (e.g., `(from Ofenheimer email 2026-03-02)`). Short phrasings (<30 chars) may be quoted inline without citation.
4. **No preamble or postamble.** The output begins with `---` (frontmatter open) and ends with the final body line. No "Here's the draft" opener, no "Let me know" closer.
5. **Target length: 300-800 tokens body.** Longer only if the signal genuinely warrants it (e.g., a 40-page meeting transcript with 8 decisions). Bias toward tight prose.

## How to use `hot.md` (steering, not override)

`hot_md_block` is Director's current-priorities cache. If the triage summary cites hot.md (ACTIVE / BACKBURNER / ACTIVELY FROZEN), acknowledge it in one sentence of the body:

> "Director's current focus on `hagenauer-rg7` elevated the triage score; this entry is filed accordingly."

If hot.md is `(no current-priorities cache available)`, do not mention steering at all. Zero-Gold state is silent, not narrated.

## How to use the feedback ledger (pattern, not mandate)

`feedback_ledger_recent` shows the last N Director actions. Use it as calibration:
- If Director recently `correct`-ed a similar-shape signal (same source, similar sender, similar body), frame your draft the way the correction implies — not the way the original errored model did.
- If Director recently `promote`-d Silver → Gold for this matter, match the tone/structure of what was promoted (the promoted entries are inside `gold_context_by_matter`; cross-reference).
- The ledger is historical data, not a rule. A genuinely-different signal overrides the pattern — but cite the override in the body if ledger suggested otherwise.

If ledger is `(no recent Director actions)`, proceed without ledger steering.

## Output format

Exactly one Markdown document. Frontmatter first, then body. Both mandatory.

### Frontmatter — required keys (in this order)

```yaml
---
title: <short noun phrase, under 80 chars, no trailing period>
voice: silver
author: pipeline
created: <ISO-8601 UTC timestamp, provided as {iso_now}>
source_id: <signal_id from input>
primary_matter: <slug or null>
related_matters: [<slug>, <slug>]   # empty array [] if none
vedana: <opportunity | threat | routine>
---
```

Optional frontmatter keys (include when applicable):
- `thread_continues: [<path>, <path>]` — if `resolved_thread_paths` is non-empty
- `deadline: <YYYY-MM-DD>` — if the signal has a hard deadline
- `money_mentioned: [<amount> <ccy>, ...]` — up to 3 most material figures

### Body structure

1. **One-paragraph summary** — 2-4 sentences. What is this signal, why does it matter, what changed.
2. **Key facts** — bulleted. People, organizations, dates, amounts, references. Drawn from `extracted_entities`, not re-extracted from raw text.
3. **Decisions / pending actions** — bulleted. One line per item with actor + action + deadline (if known). If `action_items` in entities is empty, this section may be omitted.
4. **Context** — one paragraph. How this signal relates to prior Gold, prior threads, or Director's current focus. If zero-Gold + new thread + hot.md empty, this section is two sentences at most ("First record for this matter. No prior Gold context.") — do not pad.
5. **Cross-references** (only if `related_matters` non-empty) — bulleted `- see wiki/<related-matter>/` entries, one per slug. Do NOT write speculative cross-matter analysis here; that is `finalize()`'s structural job if it's structural at all, and the Director's if it's interpretive.

### Contradiction handling

If the signal conflicts with a specific prior Gold entry, insert a line in the Context section:

> `⚠ CONTRADICTION: signal states X; Gold entry wiki/<matter>/<path>.md states Y. Director review requested.`

Never resolve the contradiction yourself. Never delete or revise Gold content. Flag and stop.

## Invariants summary (for your self-check before emitting)

- Frontmatter begins with `---`, 9 required keys present, `voice: silver`, `author: pipeline`.
- Body begins with prose summary, not a heading.
- No preamble, no postamble.
- Gold referenced by path if referenced at all.
- `resolved_thread_paths` entries appear in body or in `thread_continues` frontmatter.
- No speculation beyond inputs.

Output the Markdown document now."""
```

### 1.3 Template — `user` block (per-signal)

```python
_STEP5_USER_TEMPLATE = """## Signal triage output

primary_matter:  {primary_matter}
matter purpose:  {primary_matter_desc}
related_matters: {related_matters}
vedana:          {vedana}
triage_summary:  {triage_summary}

## Resolved thread paths (Step 2 output — may be empty)

{resolved_thread_paths}

## Extracted entities (Step 3 output)

{extracted_entities}

## Prior Gold for this matter (Leg 1 compounding — CHANDA Inv 1)

{gold_context_block}

## Director's current-priorities cache (hot.md — CHANDA Inv 3 Leg 3)

{hot_md_block}

## Recent Director actions (feedback ledger — CHANDA Inv 3 Leg 3)

{feedback_ledger_block}

## Signal raw text (truncated at 50K chars)

{signal_raw_text}

## Timestamp for frontmatter `created` field

{iso_now}

Emit the Markdown document now. Frontmatter first, then body. No preamble."""
```

### 1.4 Helper signatures

Existing helpers (from PR #6 `kbl/loop.py`, merged at `6c23d36` — reused verbatim):

```python
def load_hot_md(path: str | Path | None = None) -> str | None: ...
def load_recent_feedback(conn, limit: int | None = None) -> list[dict]: ...
def render_ledger(rows: list[dict]) -> str: ...
class LoopReadError(RuntimeError): ...
```

Proposed new helper (Leg 1 read — does NOT currently exist in `kbl/`):

```python
def load_gold_context_by_matter(matter_slug: str, vault_path: str | Path | None = None) -> str:
    """Read ALL wiki entries for `matter_slug` whose frontmatter `voice: gold`
    is set, concatenated into a single string with page-break separators.

    Path resolution: `$BAKER_VAULT_PATH/wiki/<matter_slug>/**/*.md` (or
    `vault_path` if explicitly given). Only files with `voice: gold` in
    frontmatter are included — Silver entries are excluded. Order: by
    frontmatter `created` ascending (chronological), so the model reads
    Director's judgment in the order it was formed.

    Separator between entries (for readability):

        ---
        # wiki/<matter>/<path>.md — created 2026-02-04T12:00:00Z
        ---

    Returns:
      - Non-empty string if ≥1 Gold entry exists for the matter.
      - Empty string "" if zero Gold entries for the matter (valid state
        per CHANDA Inv 1 — caller substitutes the zero-Gold sentinel block).
      - Empty string "" if vault path does not exist (bootstrap state —
        same as zero-Gold from prompt's perspective).

    Raises `LoopReadError` ONLY on true I/O failure (permission denied,
    filesystem error). Missing-files → "". Mirrors the `load_hot_md`
    fail-soft contract.

    CHANDA Inv 1 implication: every Step 5 invocation calls this function.
    No caching. A Director who just committed Gold expects the next
    pipeline tick to read the new file."""
```

**Ownership note:** this helper lives in **B1's lane** (`kbl/loop.py` or a new `kbl/vault.py` sibling). B3 does not implement Python — this signature is proposed here for B1 to ship as a follow-on PR (suggested name: `LOOP-GOLD-READER-1`). Until that PR lands, Step 5 cannot fire in production — flag in §5.

**Env-var naming (proposal):** `KBL_STEP5_LEDGER_LIMIT` — mirrors `KBL_STEP1_LEDGER_LIMIT` (PR #6). Default to 20 rows. Recommend ledger limit is shared between Step 1 and Step 5 (same ledger, same recency window) unless profiling shows Step 5 benefits from a deeper window. If AI Head prefers a single env var `KBL_LEDGER_LIMIT` governing both steps, state so; I can amend. Open question OQ2.

---

## 2. Changes against the main brief

None — this is first authoring of the Step 5 Opus prompt. KBL-B §6.3 is currently a stub in the main brief; this draft is the fill-in. When AI Head folds this into KBL-B §6.3, treat this file as the authoritative source and replace the stub wholesale.

One consequential reconciliation to flag:
- **`author` value — resolved to `author: pipeline`** (AI Head 2026-04-18, per B2 STEP5-OPUS review S1). Aligns with existing `kbl/gold_drain.py` (line 146) and B2's Step 6 scope review. Lifecycle semantics: pipeline writes `author: pipeline` + `voice: silver`; Director promotes to `author: director` + `voice: gold` (CHANDA Inv 4 protection engages on `author: director`). Draft-session `tier2` convention retired. See §5 OQ1.

---

## 3. Worked examples

Three examples drawn from the labeled corpus (`outputs/kbl_eval_set_20260417_labeled.jsonl`). Each shows the input blocks the builder would assemble, the expected Opus output as Markdown, and a short rationale.

Examples focus on CHANDA-binding behavior (zero-Gold, continuation, cross-matter). Entity extraction detail is truncated for readability — the real prompt receives full JSON from Step 3.

### Example 1 — Zero-Gold, Hagenauer email (opening record for the matter)

**Why this example:** Exercises Leg 1 zero-Gold path (G2). Proves the prompt does not fail-soft into a stub or refuse when the matter has no prior judgment; it produces a valid FIRST entry with first-record tone. Exercises Inv 1 end-to-end.

**Source signal:** corpus line 10, `signal_id=email:19cb01431b40fddf`, Ofenheimer's first letter to Hagenauer requesting Aufschlüsselung des Sicherstellungsbegehrens.

**Input blocks (assembled by builder):**

```
primary_matter:        hagenauer-rg7
matter purpose:        Hagenauer RG7 Baden bei Wien — final account dispute with GC
related_matters:       (none)
vedana:                threat
triage_summary:        Ofenheimer drafting first formal letter to Hagenauer re security-claim
                       breakdown; buys time, strategy call 8:30 next morning.

resolved_thread_paths: (none — new thread)

extracted_entities:
  people: Alric Ofenheimer (E+H, lawyer), Thomas Leitner (Brisengroup)
  orgs: Hagenauer, Engin+Hanousek
  money: (none)
  dates: 2026-03-03 (letter send day), 2026-03-03 08:30 (strategy call)
  references: EH-AT.FID2087
  action_items: Thomas Leitner: final strategy agreement by 08:30
                Ofenheimer: send letter after strategy call

gold_context_block:    (no prior Gold entries for this matter)

hot_md_block:          (no current-priorities cache available)

feedback_ledger_block: (no recent Director actions)

signal_raw_text:       [full Ofenheimer email, ~1200 chars]
iso_now:               2026-03-02T18:43:00Z
```

**Expected Opus output:**

```markdown
---
title: Ofenheimer first letter to Hagenauer — Aufschlüsselung request
voice: silver
author: pipeline
created: 2026-03-02T18:43:00Z
source_id: email:19cb01431b40fddf
primary_matter: hagenauer-rg7
related_matters: []
vedana: threat
deadline: 2026-03-03
---

Engin+Hanousek partner Alric Ofenheimer has drafted the first formal letter from Brisen to Hagenauer, requesting a breakdown of Hagenauer's Sicherstellungsbegehren (security claim). The draft is held pending a strategy call with Thomas Leitner at 08:30 on 2026-03-03; letter sends the same day once strategy is agreed. Ofenheimer's stated purpose is to gain time — immediate silence after this demand would be a plausible TCA-termination pretext for Hagenauer, whereas a formal information request is not.

**Key facts**
- Sender: Alric Ofenheimer (Engin+Hanousek, `a.ofenheimer@eh.at`)
- Recipient on Brisen side: Thomas Leitner; Edita Vallen, Dimitry Vallen, Vladimir Moravcik on copy
- Reference: E+H file `EH-AT.FID2087`
- Draft letter attached to the email (contents not in this signal — separate document)
- Strategy call: 2026-03-03 08:30

**Decisions / pending actions**
- Thomas Leitner + Ofenheimer: finalize letter content by 08:30 on 2026-03-03.
- Brisen strategy call 2026-03-03 08:30 — agree on the Aufschlüsselung ask vs. alternate responses before letter sends.

**Context**
First record for `hagenauer-rg7` in the wiki. No prior Gold context. This entry opens the arc; subsequent filings (letter-sent confirmation, Hagenauer reply, etc.) should continue rather than replace it.
```

**Rationale:** First Gold record. Note the absence of hot.md and ledger acknowledgement — both were `(no ... available)`, so the body does not mention steering (per G-rules). `deadline: 2026-03-03` surfaces because the signal has a hard next-morning cutoff. No cross-links (empty `related_matters`), so no `## Cross-references` section. Body tone is operational, not speculative.

### Example 2 — Continuation, MO Vienna meeting (extends prior Gold)

**Why this example:** Exercises G3 (thread continuation) and G1 (honor prior Gold). Also exercises hot.md steering acknowledgement. Demonstrates the model reads Gold and builds on it rather than re-narrating.

**Source signal:** corpus line 28, `signal_id=meeting:01KGMW7QJH530CT89AGFHYGTEE`, Feb 4 meeting on MO Vienna AI / data-platform strategy.

**Input blocks:**

```
primary_matter:        mo-vie-am
matter purpose:        Mandarin Oriental Vienna — Asset Management (hotel ops, F&B,
                       residences, service, occupancy). Distinct from mo-vie-exit.
related_matters:       m365
vedana:                opportunity
triage_summary:        MOVIE AI platform scoping — elevated per Director's hot.md focus on
                       mo-vie-am; intersects with the m365 migration initiative.

resolved_thread_paths: wiki/mo-vie-am/2026-01-28_ai-platform-scoping.md

extracted_entities:
  people: (none — summary format, no direct attributions)
  orgs: Mandarin Oriental Hong Kong (MOHG HQ AI team), Data Vision
  money: 3000 GBP (Data Vision monthly fee — sunset target)
  dates: (none specific — forward-looking)
  references: (none)
  action_items: Dimitry: follow-up with MOHG HK AI team
                Dimitry: recruit DB architect + programmer

gold_context_block:
  --- wiki/mo-vie-am/2026-01-28_ai-platform-scoping.md created 2026-01-28T14:00:00Z ---
  # MO Vienna AI/data platform — initial scoping
  ...3 paragraphs of Director-promoted content re initial vendor scan,
  Data Vision dissatisfaction, and intent to build in-house...

hot_md_block:
  - ACTIVE: mo-vie-am — Residence #8 offer, residences sales website, AI platform
  - ACTIVE: hagenauer-rg7 — GC takeover, administrator defence, press containment
  - ACTIVE: m365 — kick off Microsoft 365 migration
  - WATCH: mo-vie-exit — start sale process via Laura Wenk + MO

feedback_ledger_block:
  2026-02-01 11:20 | promote | mo-vie-am | sig:2101abc | "initial scoping — promoted as-is"

signal_raw_text:       [44min meeting summary, ~2400 chars]
iso_now:               2026-02-04T18:47:00Z
```

**Expected Opus output:**

```markdown
---
title: MO Vienna AI platform — Feb 4 scoping follow-up
voice: silver
author: pipeline
created: 2026-02-04T18:47:00Z
source_id: meeting:01KGMW7QJH530CT89AGFHYGTEE
primary_matter: mo-vie-am
related_matters: [m365]
vedana: opportunity
thread_continues: [wiki/mo-vie-am/2026-01-28_ai-platform-scoping.md]
money_mentioned: [3000 GBP]
---

This 44-minute meeting extends the Jan 28 scoping thread. Three additions since the opening entry: (a) the Data Vision sunset is quantified at ~£3,000/month and becomes the business case for replacement; (b) the target scope widens to include top-10 SPA + PMS integrations with GDPR/PCI compliance as load-bearing constraints; (c) execution requires a DB architect and a programmer — a recruiting item, not a scoping item.

**Key facts**
- Data Vision charged: ~£3,000/month, lacks automation, error-prone — sunset target.
- Scope: integrate top-10 SPA and PMS data into a single platform; vertical-AI on top.
- Constraints: GDPR + PCI compliance shape architecture; legacy-system inertia cited (17% AI penetration in US hospitality).
- MOHG Hong Kong AI team identified as a collaboration vector.

**Decisions / pending actions**
- Dimitry: follow up with MOHG HK AI team (no deadline stated).
- Dimitry: source DB architect + programmer (no deadline stated).

## Continues
Extends `wiki/mo-vie-am/2026-01-28_ai-platform-scoping.md`. The Jan 28 entry introduced dissatisfaction with Data Vision and the intent to build; this entry quantifies the replacement case and names the two hires needed to execute. No contradiction with the prior Gold.

**Context**
Director's current focus on `mo-vie-am` (hot.md ACTIVE) elevated this meeting's triage — the Feb 1 promotion of the scoping entry confirms the matter is on the Gold track. `m365` cross-referenced because the Microsoft 365 migration is the live tech-infrastructure thread in hot.md and the proposed data-platform work runs through the same identity / tenancy stack.

## Cross-references
- see wiki/m365/ — M365 migration intersects data-platform identity + tenancy
```

**Rationale:** Body explicitly continues prior Gold (`## Continues` section with path). hot.md acknowledgement is one sentence in Context. Ledger `promote` event is acknowledged via "Feb 1 promotion … confirms the matter is on the Gold track" — this is how ledger pattern propagates WITHOUT parroting. `money_mentioned` frontmatter surfaces the £3K figure. `related_matters: [m365]` triggers the `## Cross-references` bullet. No contradiction with prior Gold, so no ⚠ line. (Cross-link swapped from the retired `theailogy` slug — v9 slugs.yml fold.)

### Example 3 — Cross-matter WhatsApp (Wertheimer primary, hot.md-linked secondary)

**Why this example:** Exercises cross-matter handling (Step 1 `related_matters` is authoritative per post-REDIRECT, so the prompt just honors it). Exercises hot.md cross-matter elevation acknowledgement. Exercises zero-Gold primary with non-zero Gold on a related matter.

**Source signal:** corpus line 35, `signal_id=whatsapp:false_41798986876@c.us_AC0C466E0FF0784F45075A6534AB75B4`, intermediary intro to Wertheimer SFO, mentions RG7.

**Input blocks:**

```
primary_matter:        wertheimer
matter purpose:        Wertheimer family office — UHNW counterparty, exploratory
related_matters:       mo-vie-am, balducci
vedana:                opportunity
triage_summary:        Wertheimer SFO approach; elevated per hot.md (wertheimer slug-mention
                       upstream of signal) + slug-mention of RG7 in text (hagenauer-rg7
                       ACTIVE, cross-matter single-shot elevation applied per STEP1-S1).

resolved_thread_paths: (none — new thread)

extracted_entities:
  people: (none named in signal beyond Dimitry)
  orgs: Wertheimer SFO (family_office), Chanel (other)
  money: (none)
  dates: "next week" — omitted per Step 3 ISO-8601 rule
  references: (none)
  action_items: Dimitry: advise how to introduce RG7 to Wertheimer SFO

gold_context_block:    (no prior Gold entries for this matter)

hot_md_block:
  - ACTIVE: hagenauer-rg7 — GC takeover, administrator defence, press containment
  - ACTIVE: mo-vie-am — Residence #8 offer, residences sales website, AI platform
  - WATCH: mo-vie-exit — start sale process via Laura Wenk + MO

feedback_ledger_block:
  2026-04-15 17:30 | promote | wertheimer | sig:44aa01 | "first WG message — accepted"

signal_raw_text:       [full WhatsApp text ~400 chars]
iso_now:               2026-04-17T09:12:00Z
```

**Expected Opus output:**

```markdown
---
title: Wertheimer SFO — intro request re RG7 and EU-Switzerland ideas
voice: silver
author: pipeline
created: 2026-04-17T09:12:00Z
source_id: whatsapp:false_41798986876@c.us_AC0C466E0FF0784F45075A6534AB75B4
primary_matter: wertheimer
related_matters: [mo-vie-am, balducci]
vedana: opportunity
---

An intermediary with a meeting scheduled next week at Wertheimer's family office (Chanel, ex-JPM bankers, high-liquidity) is asking Dimitry how to introduce RG7 — explicitly "not necessarily the flats" — to the SFO. The request is a positioning question, not a pitch authorization.

**Key facts**
- Counterparty: Wertheimer SFO (Chanel), operated by ex-JPM bankers, stated as having "a lot of liquidity to deploy."
- Intermediary: sender of the WhatsApp message (name not surfaced in this signal).
- Target introduction: RG7 (Hagenauer Baden development), explicitly excluding the flats.
- Timing: intermediary's meeting with the SFO is "next week" (exact date not given).

**Decisions / pending actions**
- Dimitry: advise the intermediary on the RG7 framing — what dimension of RG7 (non-flats) is the right positioning for a high-liquidity UHNW buyer.

**Context**
Director's current focus (`hot.md`: `hagenauer-rg7` ACTIVE, `mo-vie-am` ACTIVE) elevated the triage — the RG7 mention in the signal text qualifies for cross-matter elevation against the hagenauer-rg7 ACTIVE entry, applied single-shot per the rule. This is the opening Gold-track record for `wertheimer`; the Apr 15 promotion of the first Wertheimer message in the ledger confirms the matter is live. No prior Gold context for `wertheimer` — treat as the opening record for strategic framing decisions.

## Cross-references
- see wiki/mo-vie-am/ — SFO would plausibly be introduced to the hotel asset alongside RG7
- see wiki/balducci/ — prior intermediary pattern
```

**Rationale:** Zero-Gold on `wertheimer` → opening-record tone in Context. hot.md elevation acknowledged, and the cross-matter single-shot rule is referenced by name so the Director can trace the steering. Ledger `promote` event referenced without copying content. `related_matters: [mo-vie-am, balducci]` from Step 1 is honored verbatim as frontmatter + cross-refs — the prompt does NOT second-guess the Step 1 cross-link choice (post-REDIRECT contract). Note that `hagenauer-rg7` is NOT in `related_matters` despite the RG7 text mention — that's a Step 1 classification decision and Step 5 respects it; the RG7 mention enters the narrative as signal content, not as a cross-matter link.

### Example 4 — Threat-vedana continuation (Hagenauer administrator claim)

**Why this example:** Exercises `vedana: threat` on a continuing arc with multiple prior Gold entries, deadline frontmatter propagation, and the ledger-pattern recognition of prior Director corrections on the same matter. Threat is the highest-volume vedana class in production (hagenauer-rg7 concentration ~27.5% per FIREFLIES_MATTER_INDEX_20260418.md), so few-shot coverage matters.

**Source signal:** constructed from the hot.md entry "Defend against Hagenauer administrator claims on Brisen" + the Mar 30 Fireflies session `01KMZA958DZDZX6YF969P3F4JQ` (2.5h Hagenauer bankruptcy fallout). Email from Hagenauer insolvency administrator to Brisen demanding unpaid contract variations.

**Input blocks:**

```
primary_matter:        hagenauer-rg7
matter purpose:        RG7 final-account dispute, Baden bei Wien (insolvency Mar 2026)
related_matters:       (none)
vedana:                threat
triage_summary:        Hagenauer insolvency administrator formal demand — €1.2M in alleged
                       unpaid contract variations, 14-day response deadline; elevated per
                       hot.md ACTIVE "Defend against Hagenauer administrator claims" +
                       recent Director promotions in ledger on adjacent Hagenauer signals.

resolved_thread_paths: wiki/hagenauer-rg7/2026-03-28_insolvency-walkthrough.md,
                       wiki/hagenauer-rg7/2026-03-30_bankruptcy-fallout-session.md

extracted_entities:
  people: [Counterparty Administrator] (Hagenauer insolvency trustee, court-appointed),
          Alric Ofenheimer (E+H, Brisen lawyer)
  orgs: Hagenauer (via administrator), Engin+Hanousek
  money: 1200000 EUR (claimed unpaid variations), 600000 EUR (Brisen disputed portion)
  dates: 2026-04-13 (14-day response deadline)
  references: EH-AT.FID2087, Admin-Case-HAG-2026-047
  action_items: Ofenheimer: draft response within 14 days; Thomas Leitner: reconcile
                variation ledger against administrator's line items

gold_context_block:
  --- wiki/hagenauer-rg7/2026-03-02_ofenheimer-first-letter.md created 2026-03-02T18:43:00Z ---
  # Ofenheimer first letter to Hagenauer — Aufschlüsselung request
  ...Brisen requested breakdown of Hagenauer's Sicherstellungsbegehren; buys time
  pre-TCA-termination...

  --- wiki/hagenauer-rg7/2026-03-28_insolvency-walkthrough.md created 2026-03-28T14:02:00Z ---
  # Hagenauer insolvency walkthrough
  ...receiver appointed; creditor claims inventoried; Brisen's position as owed-party
  vs. Hagenauer's position as general-contractor-in-insolvency mapped...

  --- wiki/hagenauer-rg7/2026-03-30_bankruptcy-fallout-session.md created 2026-03-30T14:07:00Z ---
  # Stable Brisen assets vs unstable construction business
  ...2.5h session; Brisen strategy is to ring-fence MOV + RG7 completion work from
  Hagenauer's liquidation estate; any administrator claims against Brisen must be
  rebutted with variation-ledger evidence...

hot_md_block:
  - ACTIVE: hagenauer-rg7 — GC takeover, administrator defence, press containment
  - ACTIVE: mo-vie-am — Residence #8 offer, residences sales website, AI platform
  - ACTIVE: ao — €7M call over Apr/May/Jun
  - WATCH: brisen-pr — Sandra Luger article material

feedback_ledger_block:
  2026-04-01 09:14 | promote  | hagenauer-rg7 | sig:3d11aa | "insolvency walkthrough — Gold as-is"
  2026-04-01 09:15 | promote  | hagenauer-rg7 | sig:3d12bb | "bankruptcy fallout — Gold with minor edits"
  2026-03-29 16:40 | correct  | hagenauer-rg7 → hagenauer-rg7 | sig:3c09aa | "vedana was opportunity; should be threat — insolvency fallout is defensive"

signal_raw_text:       [administrator letter + internal Brisen email thread ~3800 chars]
iso_now:               2026-03-30T11:20:00Z
```

**Expected Opus output:**

```markdown
---
title: Hagenauer administrator — €1.2M variation claim against Brisen
voice: silver
author: pipeline
created: 2026-03-30T11:20:00Z
source_id: email:19d0ff2c87b4ffee
primary_matter: hagenauer-rg7
related_matters: []
vedana: threat
thread_continues: [wiki/hagenauer-rg7/2026-03-28_insolvency-walkthrough.md, wiki/hagenauer-rg7/2026-03-30_bankruptcy-fallout-session.md]
deadline: 2026-04-13
money_mentioned: [1200000 EUR, 600000 EUR]
---

Hagenauer's court-appointed insolvency administrator has formally demanded €1.2M from Brisen for alleged unpaid contract variations on RG7, with a 14-day response window (expires 2026-04-13). The demand maps directly onto the ring-fence-and-rebut strategy crystallized in the Mar 30 session — this is the first concrete filing the administrator has made against Brisen, not a generic creditor announcement. Brisen's internal read: roughly half the claimed amount (~€600K) is genuinely disputed; the remaining €600K matches line items already logged in the variation ledger and will need reconciled treatment, not blanket denial.

**Key facts**
- Demand: €1.2M claimed unpaid variations. Brisen disputed: ~€600K. Potentially payable: ~€600K (subject to Ofenheimer review).
- Sender: Hagenauer insolvency administrator, court-appointed; reference `Admin-Case-HAG-2026-047`.
- Response deadline: 2026-04-13 (14-day statutory window).
- E+H file: `EH-AT.FID2087` (same file as Mar 2 Aufschlüsselung exchange).

**Decisions / pending actions**
- Ofenheimer: draft response before 2026-04-13 — line-by-line variation-ledger reconciliation, not blanket rebuttal.
- Thomas Leitner: pull variation ledger from project records, cross-tie to administrator's line items.
- Brisen: decide whether to settle the ~€600K matched portion or hold for court arithmetic. (Strategy call needed before 2026-04-10 to leave Ofenheimer drafting room.)

## Continues
Extends `wiki/hagenauer-rg7/2026-03-28_insolvency-walkthrough.md` (receiver-control mechanics) and `wiki/hagenauer-rg7/2026-03-30_bankruptcy-fallout-session.md` (ring-fence strategy). Neither prior Gold anticipated a specific administrator demand this early; this entry is the first concrete test of the ring-fence posture.

**Context**
Director's current focus on `hagenauer-rg7` (hot.md ACTIVE — "Defend against Hagenauer administrator claims") elevated this signal's triage, consistent with the matter's dominant position across the last three Gold promotions (ledger: three promote events in the 48 hours preceding this signal). The Mar 29 ledger correction ("vedana was opportunity; should be threat — insolvency fallout is defensive") directly shapes this entry's framing — defensive containment, not strategic reframing. No contradiction with prior Gold; this signal is the predicted next step in the administrator arc.
```

**Rationale:** Threat continuation with three prior Gold entries read + honored. `deadline: 2026-04-13` propagates from the 14-day statutory window — this is the pattern for every deadline-bearing threat signal. The ledger correction ("vedana was opportunity; should be threat — insolvency fallout is defensive") is explicitly referenced in Context — demonstrating how the vedana-discipline pattern propagates from ledger into framing, not just into the frontmatter field. Money amounts surface in `money_mentioned` (up to 3, per §1.2). No `⚠ CONTRADICTION:` because the signal extends the arc rather than contradicting it.

### Example 5 — Opportunity-vedana discipline (NVIDIA + Corinthia strategic overture)

**Why this example:** Exercises `vedana: opportunity` discipline — per `memory/vedana_schema.md`, opportunity is reserved for NEW strategic gains, not defensive wins inside ongoing arcs. The NVIDIA+Corinthia thread is a genuinely new partnership overture (hot.md ACTIVE "Proposal to NVIDIA + Corinthia — deliver early this week"), making it the canonical opportunity example. Also exercises zero-Gold on `corinthia` with a related matter (`nvidia`) that does have Gold.

**Source signal:** constructed from the Mar 17 Fireflies session `01KKYTW7Y73ZFN19266JB9MYC2` (Robotics in hotel ops — Corinthia tech-partnership MOU context) + the Apr 9 session `01KNSK7HEQ6ZXFWPQ88XH87JHC` (NVIDIA-led value-proposition crafting). Email-level overture from Corinthia side agreeing to formal MOU and requesting Brisen positioning paper.

**Input blocks:**

```
primary_matter:        corinthia
matter purpose:        Corinthia Hotels — tech-partnership MOU context
related_matters:       nvidia, mo-vie-am
vedana:                opportunity
triage_summary:        Corinthia CTO agrees to formal tech-partnership MOU with NVIDIA-backed
                       AI pilot; requests Brisen positioning paper by 2026-04-22. Elevated per
                       hot.md ACTIVE "nvidia + corinthia: Proposal to NVIDIA + Corinthia —
                       deliver early this week" + slug-mention of mo-vie-am as reference asset.

resolved_thread_paths: (none — first formal Corinthia commitment; prior Gold is on nvidia, not
                       corinthia)

extracted_entities:
  people: [Corinthia CTO], [NVIDIA BD contact]
  orgs: Corinthia Hotels, NVIDIA
  money: (none — positioning stage, no term sheet)
  dates: 2026-04-22 (positioning paper due), 2026-05-15 (pilot kickoff target)
  references: (none — MOU draft not attached yet)
  action_items: Dimitry: draft positioning paper by 2026-04-22
                Dimitry: align NVIDIA BD on Corinthia pilot scope before paper lands

gold_context_block:    (no prior Gold entries for this matter)

hot_md_block:
  - ACTIVE: nvidia + corinthia — Proposal to NVIDIA + Corinthia, deliver early this week
  - ACTIVE: hagenauer-rg7 — GC takeover, administrator defence, press containment
  - ACTIVE: mo-vie-am — Residence #8 offer, residences sales website, AI platform
  - ACTIVE: m365 — kick off Microsoft 365 migration

feedback_ledger_block:
  2026-04-10 14:22 | promote  | nvidia   | sig:41aa11 | "NVIDIA value-prop session — Gold as-is"
  2026-04-08 11:30 | promote  | nvidia   | sig:40bb22 | "GPU credit negotiation + claimsmax infra — Gold"
  2026-04-05 09:14 | correct  | corinthia → corinthia | sig:3f22cc | "was labeled mo-vie-am primary; should be corinthia primary w/ mo-vie-am in related"

signal_raw_text:       [Corinthia CTO email + thread header ~2200 chars]
iso_now:               2026-04-17T10:05:00Z
```

**Expected Opus output:**

```markdown
---
title: Corinthia CTO — formal MOU commitment, positioning paper requested
voice: silver
author: pipeline
created: 2026-04-17T10:05:00Z
source_id: email:19e4a2b5c1e3ffaa
primary_matter: corinthia
related_matters: [nvidia, mo-vie-am]
vedana: opportunity
deadline: 2026-04-22
---

Corinthia's CTO has converted the informal tech-partnership thread into a formal MOU commitment: Brisen to deliver a positioning paper by 2026-04-22, pilot kickoff targeted 2026-05-15. The overture is genuinely new strategic territory — prior Gold for `nvidia` covered compute and value-proposition crafting, but no Gold entry existed for `corinthia` as a committed counterparty. This is the opening record.

**Key facts**
- Counterparty: Corinthia Hotels, CTO-level sponsor.
- Partner: NVIDIA (BD contact engaged via Apr 9 value-proposition session).
- Commitment: formal MOU (draft not yet attached); positioning paper due 2026-04-22.
- Pilot target: 2026-05-15 kickoff.
- Reference asset signalled: `mo-vie-am` — Corinthia side referenced MOV as the comparable luxury-hospitality property where AI + robotics have been scoped.

**Decisions / pending actions**
- Dimitry: draft positioning paper by 2026-04-22 (7-day window from this signal).
- Dimitry: align NVIDIA BD on Corinthia pilot scope before paper lands — ensure the positioning doesn't commit to NVIDIA compute terms the BD team hasn't agreed to.

**Context**
First record for `corinthia` in the wiki. Prior Gold on `nvidia` (two entries in the last 10 days: value-prop session + GPU-credit negotiation) establishes the compute-side narrative this signal plugs into, but the commercial opening is new. Director's current focus on the combined `nvidia + corinthia` track (hot.md ACTIVE entry explicitly pairs them) elevated triage. Ledger correction on 2026-04-05 — reclassifying a prior signal from `mo-vie-am` primary to `corinthia` primary — set the precedent this entry follows: Corinthia commitments are `corinthia`-primary even when MOV is mentioned as reference.

Vedana: `opportunity` is correct per the vedana schema — this is a NEW strategic gain (first formal commitment from a new counterparty), not a defensive win inside an ongoing threat arc.

## Cross-references
- see wiki/nvidia/ — compute / partnership counterpart
- see wiki/mo-vie-am/ — reference asset Corinthia cited in the overture
```

**Rationale:** Opportunity-vedana discipline explicitly cited in body Context ("NEW strategic gain, not a defensive win") — demonstrates the prompt honoring the vedana schema rather than defaulting to "positive-sounding = opportunity." Zero-Gold on `corinthia` with non-zero Gold on `nvidia` (related matter) tests the case where the prompt must NOT paraphrase `nvidia` Gold into the body as if it were `corinthia` history. Ledger correction explicitly referenced as the precedent this entry follows — demonstrates ledger pattern propagation on taxonomy (not just content). `deadline: 2026-04-22` surfaces from the signal's hard date.

### Example 6 — Contradiction handling (counterparty repudiates prior commitment)

**Why this example:** Exercises the `⚠ CONTRADICTION:` body marker per §1.2 rule G1. Contradictions are the highest-stakes loop event: Opus silently overwriting prior Gold breaks Director's trust in the wiki — a single failure can cost weeks of loop-integrity recovery. This example is the canonical test that the prompt flags + stops, never resolves.

**Source signal:** constructed from the hot.md entry "ao: €7M call to Oskolkov over Apr/May/Jun — dispatch via Constantinos + transfer schedule. Paper prepared." + the Mar 21 Fireflies session `01KM83CE3MP1P7AP1C22HHG77V` (3.3h CRM with AO, Traube Tonbach). Scenario: AO's advisor walks back the Apr/May/Jun tranching committed at Tonbach.

**Input blocks:**

```
primary_matter:        ao
matter purpose:        Andrey Oskolkov — principal investor (Aelio Holding Ltd)
related_matters:       constantinos, capital-call
vedana:                threat
triage_summary:        AO's advisor signals preference for Jun/Jul/Aug split on the €7M call,
                       not the Apr/May/Jun commitment captured in prior Gold. Defensive — a
                       commitment unwind, not a new gain.

resolved_thread_paths: wiki/ao/2026-03-21_tonbach-capital-call-commit.md

extracted_entities:
  people: Constantinos ([Counterparty Advisor]), Dimitry Vallen
  orgs: Aelio Holding Ltd
  money: 7000000 EUR (full call amount — unchanged)
  dates: 2026-06-01 (proposed new first tranche), 2026-04-30 (original first tranche)
  references: (none — verbal conversation relay via Constantinos)
  action_items: Dimitry: decide whether to accept June-start or hold to April commitment;
                Constantinos: book follow-up call with AO to confirm

gold_context_block:
  --- wiki/ao/2026-03-21_tonbach-capital-call-commit.md created 2026-03-21T17:45:00Z ---
  # AO capital-call commitment at Traube Tonbach
  During the 3.3h relationship meeting at Traube Tonbach on 2026-03-21, Oskolkov
  verbally committed to a €7M capital call tranched across April / May / June 2026,
  €2.33M per month, first transfer by 2026-04-30. Constantinos to handle transfer
  mechanics; Brisen to prepare the capital-call paper (status: prepared, per 2026-03-24
  finance update). Commitment verbal — not yet papered on AO side. Director read:
  "firm handshake; expect paper within 14 days."

  --- wiki/ao/2026-03-24_capital-call-paper-prepared.md created 2026-03-24T10:18:00Z ---
  # Brisen capital-call paper prepared
  Brisen-side capital-call document prepared by finance (Balazs/Nikolai) consistent
  with the Tonbach commitment. Awaiting AO counter-signature.

hot_md_block:
  - ACTIVE: ao — €7M call to Oskolkov over Apr/May/Jun, dispatch via Constantinos
  - ACTIVE: hagenauer-rg7 — GC takeover, administrator defence
  - ACTIVE: mo-vie-am — Residence #8 offer, residences sales website
  - WATCH: ao — build dashboard of owed/owes/promised both directions

feedback_ledger_block:
  2026-03-25 08:30 | promote  | ao | sig:3b11aa | "Tonbach commit record — promoted unchanged"
  2026-03-25 08:31 | promote  | ao | sig:3b12bb | "capital-call paper prep — Gold as-is"

signal_raw_text:       [WhatsApp thread Constantinos → Dimitry ~900 chars]
iso_now:               2026-04-08T14:20:00Z
```

**Expected Opus output:**

```markdown
---
title: AO advisor signals Jun/Jul/Aug split preference — possible unwind of Tonbach commit
voice: silver
author: pipeline
created: 2026-04-08T14:20:00Z
source_id: whatsapp:true_41798986876@c.us_BDE1A5C73F20948E
primary_matter: ao
related_matters: [constantinos, capital-call]
vedana: threat
thread_continues: [wiki/ao/2026-03-21_tonbach-capital-call-commit.md]
money_mentioned: [7000000 EUR]
---

Constantinos (AO's advisor) conveyed that Oskolkov is now asking whether the €7M call could run Jun/Jul/Aug instead of Apr/May/Jun, shifting the first tranche from 2026-04-30 to 2026-06-01. The full €7M amount is unchanged; only the cadence moves. The message was relayed via WhatsApp, not confirmed by AO in writing.

**Key facts**
- Channel: Constantinos (AO advisor) → Dimitry, WhatsApp.
- New proposal: €7M same, tranches Jun/Jul/Aug, first transfer ~2026-06-01.
- Prior commitment (Gold): tranches Apr/May/Jun, first transfer by 2026-04-30.
- AO direct confirmation: NOT present in this signal. Constantinos relaying only.

**Decisions / pending actions**
- Dimitry: decide whether to (a) accept June-start and update the prepared capital-call paper, (b) hold to the April commitment and push back via Constantinos, (c) escalate to a direct AO call. Hold decision pending Director review — see contradiction flag below.
- Constantinos: book follow-up call with AO to confirm whether this is AO's firm preference or a probing signal.

**Context**
Director's current focus on `ao` (hot.md ACTIVE "€7M call to Oskolkov over Apr/May/Jun") elevated triage. The Tonbach Gold commit + the Mar 24 capital-call paper-prep Gold both encode the Apr/May/Jun cadence as firm; this signal softens that.

⚠ CONTRADICTION: signal states AO prefers Jun/Jul/Aug tranching with first transfer 2026-06-01; Gold entry `wiki/ao/2026-03-21_tonbach-capital-call-commit.md` states AO committed to Apr/May/Jun tranching with first transfer 2026-04-30. The Tonbach commitment was verbal at a relationship meeting; the repudiation is relayed via advisor on WhatsApp. Neither is papered. Director review requested before this entry is acted on or the Gold is revised.

## Continues
Extends `wiki/ao/2026-03-21_tonbach-capital-call-commit.md`. This signal is the first indication the Tonbach handshake may not hold in its original form; resolution (confirm / accept / push back) is Director-only.
```

**Rationale:** The `⚠ CONTRADICTION:` line is the load-bearing output — it cites the specific Gold path, restates the prior commitment verbatim, restates the new signal, names the channel-weight asymmetry (verbal handshake vs. WhatsApp advisor relay), and explicitly requests Director review. It does NOT recommend which side wins. The body's Decisions section explicitly parks the decision ("Hold decision pending Director review — see contradiction flag below") rather than letting the action items drift into implied overwrite. `vedana: threat` because a commitment unwind is defensive per the vedana schema. `thread_continues` points to the Tonbach Gold so the Director can open both entries side-by-side in one click.

### Example 7 — Stub-only boundary (pipeline-documentary negative example)

**Why this example:** Documents the Step 4→5 boundary. This prompt's §1 establishes that Step 5 fires only on `full_synthesis` — `stub_only`, `cross_link_only`, `skip_inbox`, and `paused_cost_cap` are written deterministically upstream and never reach Opus. This example is NOT a few-shot for synthesis — it is a **contrast artifact** showing what the pipeline produces WITHOUT Opus, so reviewers (and Opus itself, if somehow misrouted) can recognize the shape and refuse gracefully rather than synthesize over it.

**Negative-example framing (read this first):**

> If Opus receives inputs resembling this example — `triage_score` in the 40-45 band, `triage_confidence < 0.5`, `resolved_thread_paths == []`, thin `extracted_entities` — the pipeline's `_decide_step5_path()` gate at the Step 4→5 boundary (KBL-B §4.5) SHOULD have classified as `stub_only` and written the deterministic stub WITHOUT calling Opus. If you're seeing this as Opus input, something misrouted. **Preferred behavior:** synthesize normally but include a body footnote noting "triage score borderline — routing review suggested." **Never emit the `status: stub_auto` frontmatter marker yourself** — that marker is reserved for deterministic stubs and signals to the Director that Opus was not involved.

**Source signal:** constructed from a noise-band marketing pitch — a hospitality-tech vendor emailing MOV's general inbox pitching their PMS integration service. Matches `mo-vie-am` by slug-mention but carries no action requirement, no counterparty weight, no deadline.

**Input blocks (as Step 4 sees them, BEFORE gating):**

```
primary_matter:        mo-vie-am
matter purpose:        Mandarin Oriental Vienna — Asset Management
related_matters:       (none)
vedana:                routine
triage_score:          42
triage_confidence:     0.45
triage_summary:        Generic PMS-integration sales pitch to MOV; slug-matches mo-vie-am but
                       no action, no deadline, no counterparty weight. Borderline noise.

resolved_thread_paths: (none)

extracted_entities:
  people: [Vendor BD rep]
  orgs: [PMS Vendor]
  money: (none — "request a quote" CTA only)
  dates: (none)
  references: (none)
  action_items: (none)

gold_context_block:
  --- wiki/mo-vie-am/2026-01-28_ai-platform-scoping.md created 2026-01-28T14:00:00Z ---
  ...initial vendor scan, Data Vision dissatisfaction, intent to build...
  --- wiki/mo-vie-am/2026-02-04_feb-4-scoping-followup.md created 2026-02-04T18:47:00Z ---
  ...quantified Data Vision sunset, two hires needed...

hot_md_block:
  - ACTIVE: mo-vie-am — Residence #8 offer, residences sales website, AI platform
  - ACTIVE: hagenauer-rg7 — GC takeover, administrator defence

feedback_ledger_block:
  2026-04-14 11:00 | ignore   | mo-vie-am | sig:42cc33 | "vendor pitch — noise; suppress similar in future"

signal_raw_text:       [generic vendor cold email ~800 chars]
```

**Expected PIPELINE output (deterministic stub, NOT an Opus call):**

```markdown
---
title: [PMS Vendor] — PMS-integration sales pitch (auto-stub)
voice: silver
author: pipeline
created: 2026-04-17T15:30:00Z
source_id: email:19e6aa33bb22ffcc
primary_matter: mo-vie-am
related_matters: []
vedana: routine
status: stub_auto
triage_score: 42
---

Generic PMS-integration sales pitch to MOV. No action, no deadline, no counterparty weight. Retained as routine record only; see `wiki/mo-vie-am/_inbox/` for similar low-signal correspondence. Director previously ignored a similar pitch on 2026-04-14 (ledger sig:42cc33).
```

**Rationale:** The `status: stub_auto` frontmatter marker is the load-bearing contract — it tells the Director (and downstream tooling) that no Opus call occurred and the body is a 2-3 sentence placeholder, not synthesized prose. The body cites the recent ledger `ignore` event so the Director can see the suppression pattern is self-consistent. This output is **NOT produced by Opus** — it is generated by the deterministic stub writer inside `_decide_step5_path()` per KBL-B §4.5, using the same frontmatter model. The example exists in this prompt as boundary documentation: Opus should recognize the input shape and refuse to synthesize over it. If Opus ever emits `status: stub_auto` voluntarily, it is a prompt-adherence bug — flag to Director immediately.

---

## 4. CHANDA pre-push self-check

| Test | Assessment |
|---|---|
| **Q1 Loop Test** | **This prompt IS Leg 1.** It is the mechanism by which Gold conditions future Silver. Design choices in §1.2 rules G1-G3 and the mandatory `gold_context_block` pass in §1.1 encode Leg 1. A reviewer who challenges G1-G3 is flagging a Leg 1 concern and MUST escalate per §5 before a merge. **Not a new Leg violation** — this prompt CREATES the Leg 1 reading pattern for Step 5, consistent with Inv 1. Flagged for Director visibility regardless. |
| **Q2 Wish Test** | Serves wish (synthesis of loop inputs into reviewable Silver, with Gold honored). Engineering convenience is co-satisfied (prompt-caching on the stable system block). Tradeoff: input cost rises with Gold corpus size — a matter with 100 Gold entries will push per-call cost up noticeably. Mitigated by prompt-caching on the system block + ledger-limited context. Revisit if Phase 1 shows a single matter exceeds ~40K tokens of Gold; at that point, a Gold-summarization pre-step is the right answer, not a truncation cap. |
| **Inv 1 compliance** | Zero-Gold case produces a valid first entry (Example 1). Empty-sentinel block, not absent. Prompt rule G2 enforces first-record behavior. |
| **Inv 3 compliance** | `hot.md` + feedback ledger re-read on every call via the same `kbl/loop.py` helpers Step 1 uses. Not cached. |
| **Inv 4 compliance** | Frontmatter `author: pipeline` always. `author: director` never emitted by this prompt — it is reserved for Director Gold promotions, where CHANDA Inv 4's "never modified by agents" protection engages. (§5 OQ1 resolved 2026-04-18 — `tier2` convention retired in favor of `pipeline`.) |
| **Inv 5 compliance** | Every emitted wiki file has full 9-key frontmatter. Missing frontmatter is a pipeline failure (Step 6 `finalize()` validates — out of this prompt's scope but the prompt is the producer). |
| **Inv 6 compliance** | Cross-link section emitted when `related_matters` non-empty. Step 6 finalize() applies structural cross-link handling deterministically, NOT this prompt. |
| **Inv 7 compliance** | No ayoniso override behavior in this prompt — Step 5 is the synthesis step, not the alerting step. |
| **Inv 8 compliance** | `voice: silver` always. No self-promotion. Rule F1 mandates this; §1.2 hard rule. |
| **Inv 9 compliance** | Single-writer Mac Mini constraint is a Step 7 harness concern, not this prompt's. |
| **Inv 10 compliance** | Prompt is a stable template. All variation comes through data blocks. Prompt string is not rewritten per-signal. |

---

## 5. Open questions for AI Head

1. **`author:` frontmatter value — RESOLVED 2026-04-18 to `author: pipeline`** (AI Head, per B2 STEP5-OPUS review S1). Lifecycle locked: pipeline writes `author: pipeline` + `voice: silver`; Director promotion flips both to `author: director` + `voice: gold`, at which point CHANDA Inv 4's "never modified by agents" protection engages. Draft-session `tier2` convention retired throughout this file in the STEP5-S1-AUTHOR-RENAME pass. Aligns with existing `kbl/gold_drain.py` (line 146) and B2's Step 6 scope review. No outstanding question.

2. **Ledger limit env-var shape.** This prompt proposes `KBL_STEP5_LEDGER_LIMIT` to mirror PR #6's `KBL_STEP1_LEDGER_LIMIT`. Two env vars may be overkill — the ledger is the same table, the recency window the same concept. **Recommend:** single `KBL_LEDGER_LIMIT` governing both Step 1 and Step 5 unless profiling shows Step 5 benefits from a deeper window. I'll amend per your call.

3. **Gold-corpus size ceiling.** Inv 1 mandates reading ALL Gold for the matter. A mature matter (say `hagenauer-rg7` in Phase 3) could easily have 50-200 Gold entries × 500-1500 tokens each → 25K-300K input tokens on the Gold block alone. Opus 1M-context handles it; cost does not. **Recommend:** defer to Phase 1 close-out measurement. If cost ledger shows Gold block dominates input tokens per call, introduce a Gold-summarization pre-step (itself a Silver → Silver synthesis run by Sonnet or Haiku) that condenses prior Gold into ~2K tokens of canonical matter-state before Step 5 reads it. Out of scope for this prompt; flagging for forward design.

4. **Opus 1M context vs 200K.** The task header says `claude-opus-4-7` (1M context). KBL-B §2 Step 5 says `claude-opus-4-7` without context-size qualifier. The 1M variant is materially more expensive per token. **Recommend:** default to 200K and only escalate to 1M on OversizedInputError (Gold corpus genuinely exceeds 200K). Graceful fallback is cheap; auto-1M is a standing cost commitment. AI Head call.

5. **`load_gold_context_by_matter` helper implementation (blocks Phase 1 Step 5 firing).** This helper does not currently exist in `kbl/`. I've proposed the signature in §1.4. **B1 needs to ship it** (suggested follow-on PR name: `LOOP-GOLD-READER-1`). Step 5 cannot fire until it lands. If AI Head prefers B1 ships it inside the Step 5 implementation PR rather than as a separate loader PR, that also works — my preference is separated so the Leg 1 reader is independently reviewable.

6. **Prompt-caching cache key.** The `system` block is stable across signals; Anthropic prompt-caching keyed on the system block would materially reduce per-call input cost. The cache key should be `(prompt_version, slug_glossary_hash)`. Slug list is NOT inside the system block in this draft (matter descriptions come through `primary_matter_desc` in the user block), so slug churn does NOT invalidate the system cache. **Flag:** confirm this is the intended cache shape. If AI Head prefers slug glossary in the system block for matter-awareness, that's a tradeoff (slug churn → cache invalidation). I'd keep it out.

7. **Contradiction-flag behavior vs ayoniso alerts.** Rule G1's `⚠ CONTRADICTION:` marker is a body-level annotation. KBL-A has a separate ayoniso-alert mechanism (D7 / Inv 7). Are these intended to be independent channels (Step 5 marker = documentary; ayoniso = runtime alert routing) or should Step 5 also raise an ayoniso event on contradiction? **Recommend:** keep them independent. The ⚠ marker ensures the Director sees the contradiction when reading the Silver entry; ayoniso is a separate signaling concern. But flagging in case AI Head's D7 wiring expects Step 5 to surface contradictions to the alert bus too.

8. **Entity rendering inside user block.** `_render_entities(extracted_entities)` is assumed in §1.1. I have NOT specified its output format — a compact JSON dump vs a human-readable bulleted block vs a mixed form. **Recommend:** compact JSON dump (the model handles JSON; it's token-efficient; and downstream debugging can diff the input blocks trivially). If AI Head prefers bulleted, I'll amend — a ~30-char change.

---

*Drafted 2026-04-18 by B3 for AI Head §6.3 fold. No evals run (scope guardrail — Step 5 eval requires live vault + Gold corpus, Phase-1 close-out concern). Ready for B2 review.*
