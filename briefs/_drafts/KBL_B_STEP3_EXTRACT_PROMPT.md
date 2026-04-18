# KBL-B Step 3 — `extract` Production Prompt (Gemma local)

**Author:** Code Brisen 3
**Task:** `briefs/_tasks/CODE_3_PENDING.md` (2026-04-18)
**Model target:** `gemma4:latest` (local, macmini Ollama)
**Writes to:** `signal_queue.extracted_entities` JSONB (§4.4 schema)
**No prior eval** — this is a new prompt, conservative few-shot design.

---

## 1. The prompt template

**File:** `kbl/prompts/step3_extract.py`

```python
def build_step3_prompt(
    signal_text: str,
    source: str,              # 'email' | 'whatsapp' | 'meeting' | 'scan'
    primary_matter: str | None,
    resolved_thread_paths: list[str],
) -> str:
    """Build the extract prompt. Source and primary_matter are included
    as context hints but NOT as extraction targets — they're already
    known from Step 1 + Step 2."""
    matter_hint = primary_matter if primary_matter else "none (null matter)"
    thread_hint = ("; ".join(resolved_thread_paths[:3])
                   if resolved_thread_paths else "new thread")
    return _STEP3_TEMPLATE.format(
        signal=signal_text.replace('"', "'")[:3000],
        source=source,
        matter_hint=matter_hint,
        thread_hint=thread_hint,
    )


_STEP3_TEMPLATE = """You are an entity-extraction agent. Your job is to pull structured data out of a business signal (email, WhatsApp message, meeting transcript, or Director scan) into a strict JSON schema. Output ONLY valid JSON, no commentary.

Context (do NOT extract these — they are provided):
  source:         {source}
  primary_matter: {matter_hint}
  thread_context: {thread_hint}

Signal: "{signal}"

Respond with exactly this JSON — all 6 top-level keys MUST be present, values MUST be arrays (use [] if nothing found):

{{
  "people":       [ {{"name": "...", "role": "...", "company": "..."}} ],
  "orgs":         [ {{"name": "...", "type": "law_firm|bank|investor|contractor|hotel|family_office|advisor|regulator|other"}} ],
  "money":        [ {{"amount": 100000, "currency": "EUR", "context": "..."}} ],
  "dates":        [ {{"date": "2026-04-30", "event": "..."}} ],
  "references":   [ {{"type": "contract|invoice|case|bond|letter|document", "id": "..."}} ],
  "action_items": [ {{"actor": "...", "action": "...", "deadline": "..."}} ]
}}

**Extraction rules:**

1. **Omit, don't null.** If you can extract a person's name but not their role, emit `{{"name": "Dimitry Vallen"}}` with NO `"role"` key. Never emit `"role": null` or `"role": ""`. Same for every sub-field.

2. **Skip self-references.** Do NOT extract the Director (Dimitry Vallen) or the Director's companies (Brisen, Brisengroup) unless the signal specifically discusses them AS a subject (e.g., "appoint Dimitry as board director of X"). Mentions like email signatures and "Best, Dimitry" → skip.

3. **Money normalization.** `amount` MUST be a number (not a string). Currency MUST be ISO-4217 ("EUR", "USD", "CHF", "GBP"). Contextual phrasing ("couple million", "six-figure") → skip, do not guess.

4. **Date normalization.** `date` MUST be ISO 8601 (YYYY-MM-DD). Partial dates ("end of Q2", "next week") → skip unless context gives a real date. `event` is a 2-6 word label ("payment deadline", "court hearing", "Steininger testimony").

5. **Reference IDs.** Only emit references with a machine-usable ID. "the contract we signed" → skip. "contract no. HAG-2024-017" → emit `{{"type": "contract", "id": "HAG-2024-017"}}`. "VAT invoice 2026/42" → emit `{{"type": "invoice", "id": "2026/42"}}`.

6. **Action items.** Only emit when an actor + action is clear. "Thomas, please send the letter" → yes. "We should maybe consider..." → no. `deadline` is optional — omit if not stated.

7. **Orgs vs people.** A company mentioned only as a person's employer goes inside that person's `company` field, NOT duplicated in `orgs`. `orgs` is for organizations that are subjects in the signal (recipient of letter, counterparty in a deal, etc.).

8. **Zero results is normal.** An automated receipt or a "thanks" reply legitimately has all six arrays empty. Return `[]` six times — do not hallucinate.

{few_shot_examples}

Output the JSON for the signal above now."""


# Few-shot examples are appended at build time — kept separate so they can
# evolve without re-testing the prompt skeleton.
_FEW_SHOT_EMAIL = '''
Example 1 — email signal:
Signal: "Email Thread: Re: [EXTERN] your letter 4/2/2026 [EH-AT.FID2087]
Date: 2026-02-12
Participants: dvallen@brisengroup.com, edita.vallen@brisengroup.com, thomas.leitner@brisengroup.com
--- Edita Vallen (2026-02-12 15:18) ---
Hi Thomas, If Alric thinks it is important, please do send it. In addition, maybe it is worth saying in the same letter that we have to start works ourselves : KNX, Drywalls etc. Please check with Alric."
source: email; primary_matter: hagenauer-rg7; thread_context: wiki/hagenauer-rg7/2026-02-04_eh-letter.md

Expected output:
{{"people":[{{"name":"Thomas Leitner","company":"Brisengroup"}},{{"name":"Alric","company":"Engin+Hanousek"}}],"orgs":[],"money":[],"dates":[{{"date":"2026-02-04","event":"prior letter reference"}}],"references":[{{"type":"letter","id":"EH-AT.FID2087"}}],"action_items":[{{"actor":"Thomas Leitner","action":"check with Alric re sending the letter + KNX/drywall self-execution note"}}]}}
'''

_FEW_SHOT_WHATSAPP = '''
Example 2 — whatsapp signal:
Signal: "Hello Dimitry. I hope things are going well. I have a meeting with Wertheimer's family office (Chanel) next week. The SFO is currently running by ex JPM bankers. They have a lot of liquidity to deploy. They ask me for attractive, disruptive and relevant investment ideas in Switzerland or in Europe. I would like to introduce RG7 (not necessarily the flats). What do you think or suggest Dima in relation to RG7?"
source: whatsapp; primary_matter: wertheimer; thread_context: new thread

Expected output:
{{"people":[],"orgs":[{{"name":"Wertheimer SFO","type":"family_office"}},{{"name":"Chanel","type":"other"}}],"money":[],"dates":[],"references":[],"action_items":[{{"actor":"Dimitry","action":"advise how to introduce RG7 to Wertheimer SFO"}}]}}
'''

_FEW_SHOT_MEETING = '''
Example 3 — meeting transcript:
Signal: "Meeting: Jan 12, 02:33 PM. Duration: 56min. Summary: Court Hearing Focus: Aim to challenge Steininger family credibility. Judge to question family members, risking contradictory testimonies. Evidence Prepared: Photos and documents to counter claims about 2018 share transfer's value and ownership. Investment Opportunity: Roundshield investor withdrew, offering Dimitry a chance to negotiate a possible CHF 17 million deal. Escrow Deadlock: CHF 800,000 in escrow is frozen due to waiver non-compliance."
source: meeting; primary_matter: kitzbuhel-six-senses; thread_context: wiki/kitzbuhel-six-senses/2026-01-05_prep.md

Expected output:
{{"people":[],"orgs":[{{"name":"Steininger family","type":"other"}},{{"name":"Roundshield","type":"investor"}}],"money":[{{"amount":17000000,"currency":"CHF","context":"possible deal"}},{{"amount":800000,"currency":"CHF","context":"frozen escrow, waiver non-compliance"}}],"dates":[{{"date":"2018","event":"share transfer under dispute"}}],"references":[],"action_items":[{{"actor":"Dimitry","action":"negotiate CHF 17M deal with Roundshield counterparty"}}]}}
'''


def build_step3_prompt_with_shots(*args, **kwargs) -> str:
    """Full version with all three few-shot examples prepended."""
    shots = "\n".join([_FEW_SHOT_EMAIL, _FEW_SHOT_WHATSAPP, _FEW_SHOT_MEETING])
    return build_step3_prompt(*args, few_shot_examples=shots, **kwargs)
```

---

## 2. Rationale — why this structure

### 2.1 No prior eval — conservative design

Step 3 was never part of v1/v2/v3 evals (those measured triage only). This prompt is design-forward. I've biased toward:

- **Strict schema enforcement** (6 keys, array values) to avoid drift that would break downstream Step 5 (Opus consumes this as input context).
- **Explicit omission rule** ("omit, don't null") to prevent the tri-state JSON-null problem I saw in v3 eval — Gemma returned `"null"` strings vs Python None, costing 1-4 scored rows. Step 3 can't afford that; entity extraction is higher-stakes.
- **3 few-shots spanning all source types** — extraction needs calibration on format (email headers vs WhatsApp casual vs meeting summary), not just content. Triage didn't need few-shots because its output space is tiny (19 × 3 × 100 × 1.0); extraction's output space is large.

### 2.2 Context hints vs extraction targets

`source`, `primary_matter`, and `thread_context` are given to the model but explicitly excluded from extraction. This is critical — without the exclusion, Gemma would emit the matter slug as a "reference" entity in every signal, polluting the dataset.

The hints ARE useful because they tell the model what's likely relevant:
- If `primary_matter = cupial`, the model knows to prioritize Cupial-family names, buyer-contract references, payment amounts.
- If `thread_context = new thread`, the model knows not to reference prior threads.

### 2.3 Few-shot selection — 3 signals, one per source type

| Example | Source | primary_matter | Why this one |
|---|---|---|---|
| 1 | email | hagenauer-rg7 | Covers: multi-participant thread, quoted reply, reference ID pattern (EH-AT.FID2087), action-item extraction from natural language. |
| 2 | whatsapp | wertheimer | Covers: casual informal text, org extraction (Wertheimer SFO, Chanel), action request to Director, all 4 empty arrays. |
| 3 | meeting | kitzbuhel-six-senses | Covers: summary-style content, multiple currency amounts (CHF 17M, CHF 800K), multiple orgs, no people (summary has no direct quotes), date normalization from partial ("2018"). |

**Why not 5 or 10 few-shots?** Latency. Prompt is already ~4K chars before signal. Gemma 4 8B at 15s/call × thousands of signals/month = material cost budget. 3 covers source diversity; more examples would need eval proof of lift.

### 2.4 Director self-reference rule

The "skip self-references" rule is operationally critical. Dimitry appears in ~every email as sender/recipient. Without the rule, `people` inflates to useless noise (Dimitry extracted 100% of the time).

The rule is intentionally narrow: "unless signal discusses them AS a subject." This preserves signals like "appoint Dimitry to board of X" or "Dimitry's personal tax matter" which are legitimate extractions.

### 2.5 Money + date formats (machine-usable)

**Money:** `amount` as number, currency as ISO-4217. This lets Step 4/5/6 do arithmetic (aggregate financial exposure across signals, flag large amounts). If Gemma returns `"amount": "17 million EUR"` string, downstream arithmetic breaks silently. The prompt shows number examples in every few-shot.

**Dates:** ISO 8601 (YYYY-MM-DD). Opus/Sonnet in Step 5/6 do temporal reasoning (what's urgent, what's overdue). Non-ISO dates cost recovery prompts = latency + cost.

### 2.6 Reference extraction — conservative, ID-bearing only

Most business signals mention "the contract" or "that letter" without an ID. Extracting those is low-value (no back-link possible) and hallucination-prone. Rule: only extract references with a parseable ID. This trades coverage for precision — acceptable because Step 5/6 Opus/Sonnet can infer reference relationships from context where needed.

---

## 3. Expected failure modes + recovery

| Failure mode | Detection | Recovery |
|---|---|---|
| Top-level JSON malformed | `json.loads()` raises | Retry once. Second failure → write `{"people":[],"orgs":[],"money":[],"dates":[],"references":[],"action_items":[]}` stub, `level='WARN'` log, continue pipeline. Step 4 can still run on empty extraction. |
| One top-level key missing | Python post-parse | Insert key with `[]` value. `level='INFO'` log. |
| Top-level value is not an array (e.g., object, string) | Python post-parse | Replace with `[]`. `level='WARN'` log. |
| Sub-field hallucination (e.g., `amount: "unknown"`) | Python validator | Drop that sub-field; keep other sub-fields of same entity. `level='INFO'` log (expected for messy input). |
| `amount` is a string like "17 million" | Python validator | Drop the money entry entirely (don't try to parse). `level='INFO'` log. |
| Date not ISO 8601 | Python validator | Drop the date entry. `level='INFO'` log. |
| Dimitry appears in people despite rule | Python post-processor | Strip; no log (noise-level). |
| `orgs` contains the primary_matter slug | Python post-processor | Strip; no log. |
| Giant output (500+ tokens) indicating confabulation | `num_predict` cap at 1024 | Cap enforces truncation → JSON malformed → retry path. Log `level='WARN'` for corpus-level drift tracking. |

### 3.1 Invariants (§4.4 restated)

Post-write, for every signal processed by Step 3:
- `extracted_entities` IS a JSON object (not array, not null)
- ALL of `people`, `orgs`, `money`, `dates`, `references`, `action_items` ARE present as keys
- Each value IS an array (possibly empty)
- No sub-field value is `null` or `""` (those are OMITTED from sub-objects per extraction rule 1)

Python validator enforces all invariants before writing to `signal_queue.extracted_entities`. A validation failure (not recoverable by dropping sub-fields) → write the empty stub.

---

## 4. Sampling config

Same as Step 1:

```python
OLLAMA_OPTIONS = {
    "temperature": 0.0,
    "seed":        42,
    "top_p":       0.9,
    "num_predict": 1024,   # Step 3 output can be larger than Step 1
}
```

**Difference from Step 1:** `num_predict=1024` (was 512). Entity extraction for a rich meeting transcript can easily produce 400+ token output. Cap at 1024 to prevent runaway confabulation while allowing full coverage.

---

## 5. Prompt cost estimate (for `kbl_cost_ledger`)

- Prompt tokens: ~1500-1800 (prompt template + 3 few-shots + signal up to 3000 chars)
- Output tokens: 100-600 (varies massively by signal density)
- Model: Gemma 4 8B local
- Cost: $0.00
- Latency: ~10-25s/call (estimated — NOT benchmarked yet; would need separate eval)

Ledger row: `step='extract'`, `model='ollama_gemma4'`, `input_tokens`, `output_tokens`, `cost_usd=0`, `latency_ms`.

---

## 6. Open questions for AI Head

1. **Few-shot rotation.** Should the 3 few-shots rotate per `primary_matter` (e.g., if primary is hagenauer-rg7, show a hagenauer-rg7 few-shot)? That would help matter-specific entity extraction (Cupial names, EH-AT reference patterns). Tradeoff: more prompt-build complexity, and the matter-scoped corpus is small. Recommend: **defer** — ship with 3 static few-shots for v1, measure quality, iterate.

2. **Pre-extraction validation.** Should Step 3 skip entirely when `primary_matter IS NULL AND triage_score < 40` (i.e., inbox-routed signals)? Saves latency on low-value signals. Empty `extracted_entities` = `{"people":[],...}` stub would be fine for inbox items. **Recommend: yes**, skip extraction on inbox-routed — cost optimization, zero risk.

3. **Emoji / non-ASCII handling.** WhatsApp signals often contain emoji. I've tested Ollama JSON mode handles them; Python `json.loads` accepts. No special rule added. Flag if you want explicit "strip emoji" or "preserve emoji".

4. **Org type taxonomy.** I hardcoded 9 types: `law_firm | bank | investor | contractor | hotel | family_office | advisor | regulator | other`. This could live in `baker-vault/org_types.yml` as a registry like slugs. **Recommend: defer** — hardcode is simpler; promote to registry only when KBL-C surfaces real need for org-type-based filtering.

---

*Drafted 2026-04-18 by B3 for AI Head §6 assembly. No evals run. Ready for copy-paste into KBL-B §6.*
