# KBL-B Step 1 — `triage` Production Prompt (Gemma local)

**Author:** Code Brisen 3 — empirical lead (v1/v2/v3 evals, D1 ratified 2026-04-18)
**Task:** `briefs/_tasks/CODE_3_PENDING.md` (2026-04-18, re-engagement dispatch)
**Model target:** `gemma4:latest` (local, macmini Ollama). **Qwen 2.5 14B is wired as AVAILABILITY fallback ONLY** per D1 ratification 2026-04-18 (`briefs/DECISIONS_PRE_KBL_A_V2.md` → §"D1 Phase 1 acceptance" + §"Qwen-fallback role re-scoped"). Qwen fires when Gemma is **unreachable** (Ollama down, 3× retry failed), NOT on low-confidence. Qwen is NOT an accuracy rescue.
**Ratified D1 perf:** Gemma 88% vedana / 76% matter / 100% JSON (glossary prompt v3)
**Writes to:** `signal_queue.primary_matter`, `related_matters`, `vedana`, `triage_confidence`, `triage_score` (§4.2 contract)

---

## 1. The prompt template

**File:** `kbl/prompts/step1_triage.py` (proposal — or inline in `kbl/steps/triage.py`)

```python
from kbl.slug_registry import active_slugs, describe

def build_step1_prompt(signal_text: str) -> str:
    """Build the triage prompt with slug list + descriptions pulled live
    from the registry. The registry is the single source of truth — this
    function does not cache. Registry version is logged in ledger row."""
    slugs = active_slugs()  # list[str], excluding retired
    max_len = max(len(s) for s in slugs) + 2
    glossary = "\n".join(
        f"  {s.ljust(max_len)}— {describe(s)}" for s in slugs
    )
    return _STEP1_TEMPLATE.format(
        signal=signal_text.replace('"', "'")[:3000],
        slug_glossary=glossary,
    )


_STEP1_TEMPLATE = """You are a triage agent for a multi-matter business operation (real estate, hospitality, legal disputes, investment). Classify this signal. Output ONLY valid JSON, no commentary.

Signal: "{signal}"

Respond with exactly this JSON (all keys required):
{{
  "primary_matter":    "<slug from the glossary below, or null if no matter applies>",
  "related_matters":   ["<zero or more slugs from the glossary, excluding primary_matter>"],
  "vedana":            "opportunity" | "threat" | "routine",
  "triage_score":      <integer 0-100>,
  "triage_confidence": <number 0.0-1.0>,
  "summary":           "one line"
}}

Matter slugs (pick ONE for primary_matter whose description best matches the signal, or null):

{slug_glossary}

**Rules for `primary_matter`:**
- Must be EXACTLY one slug from the glossary above, or the JSON value null (unquoted).
- Do NOT invent slugs. Do NOT return generic categories like "hospitality", "investment", "legal", "real_estate", "business" — those are ALWAYS wrong.
- If no glossary entry matches, return null. "null" is a valid, common answer for automated notifications, newsletters, personal admin with no business link.
- A brisengroup.com email header or "Brisen" in a sender name does NOT imply brisen-lp. brisen-lp is ONLY for fund/LP vehicle matters.

**Rules for `related_matters`:**
- Array of zero or more additional slugs from the glossary.
- MUST NOT include primary_matter itself.
- Use only when the signal substantively connects a second matter (e.g., a Wertheimer approach mentioning RG7 → primary=wertheimer, related=[hagenauer-rg7]).
- If uncertain, leave as []. Over-linking is a worse error than under-linking.

**Rules for `vedana`:**
- opportunity: NEW strategic gains ONLY — a new deal, investor interest, unrequested approach, favorable market shift, novel capability revealed. Defensive wins inside an ongoing threat arc (e.g., court ruling in our favor on a dispute) stay in threat, not opportunity.
- threat: risks, problems, disputes, deadlines, unpaid invoices, regulatory issues, counterparty demands, anything requiring defensive action.
- routine: noise — receipts, automated notifications, newsletters, FYI emails, admin correspondence with no action required.

**Rules for `triage_score` (0-100):**
- Score "how much should a busy executive care about this right now?"
- 0-20 = pure noise, safe to ignore (routine automated).
- 21-39 = low priority, admin or mild context — will route to wiki/_inbox/.
- 40-69 = worth logging in its matter, no immediate action.
- 70-89 = notable — deserves synthesis, will produce a wiki entry.
- 90-100 = urgent — deadline imminent, major financial exposure, or novel strategic opportunity.

**Rules for `triage_confidence` (0.0-1.0):**
- Your estimate of how confident you are in `primary_matter` AND `vedana` together.
- 0.9+ = clear matter + clear vedana.
- 0.6-0.9 = matter obvious but vedana ambiguous, or vice versa.
- 0.3-0.6 = guessing on at least one field.
- <0.3 = you're not sure this is classifiable; consider primary_matter=null.

Output the JSON now."""
```

---

## 2. Rationale — why this structure

### 2.1 Empirical basis

v3 eval (D1-ratified) proved three levers:

| Lever | Empirical effect |
|---|---|
| Adding vedana semantic rule (v2) | Gemma +16pp vedana (70% → 86%) |
| Adding per-slug glossary (v3) | Gemma +42pp matter (34% → 76%) |
| Adding disambiguation notes for `brisen-lp` (v3) | Eliminated v2's 13/33 dominant error (hagenauer-rg7 → brisen-lp) |

All three retained in production prompt.

### 2.2 Changes from v3 eval prompt

| Change | Why |
|---|---|
| Slug list + descriptions sourced from `slug_registry` at call time, not hardcoded | Single source of truth. When SLUGS-2 splits `edita-russo`, the prompt self-updates. No prompt re-deploy needed. |
| Added `related_matters` array | Required by §4.4 schema (Step 4 `classify` policy uses it for cross-link decisions). Not in v1-v3 evals because those didn't test it. |
| Added `triage_confidence` (0-1) | Required by §4.2 contract. Not in v1-v3 prompts — those only asked for `triage_score`. Confidence is captured for future calibration studies + low-confidence routing to `wiki/_inbox/` for Director review. **NOT used to trigger Qwen fallback** — Qwen is availability-only per D1 re-scoping (2026-04-18). |
| Explicit reject-list for generic categories ("hospitality", "investment") | Gemma in v1 hallucinated those at 4% rate. Glossary alone in v3 eliminated most. Explicit rejection makes it robust for production corpus (broader than 50-signal eval). |
| "A brisengroup.com email header does NOT imply brisen-lp" | v3's most effective disambiguator — kill the dominant v2 error. Retained verbatim. |

### 2.3 What's NOT in this prompt

- **`matter_slug_schema` pointer** — the "matter slugs are a living body" architectural note (v2 analysis artifact) is NOT surfaced in the prompt. Prompt-level content is pure classification; architecture lives in docs.
- **Source-type hints** — no `<source=email>` marker in the prompt. Prior evals didn't benefit from source-tagging, and the labeled set showed models match source context well from content alone.
- **Few-shot examples** — Step 1 is a schema task, not a reasoning task. Per v3 results, few-shots would add latency without moving accuracy. Reserved for Step 3.
- **Per-slug "bad example" counter-samples** — e.g., "this is NOT cupial" for a hagenauer-rg7 email. Deferred — adds prompt length (already 2× v2 at ~3.5K chars), and the disambiguation block covers the top 2 errors.

### 2.4 Interaction with Step 4 (classify) policy

The `related_matters` array is consumed by Step 4 §4.5:

| Step 1 produces | Step 4 decision |
|---|---|
| `related_matters == []` | `full_synthesis` (single arc) |
| `related_matters != []` | `full_synthesis` + Step 6 cross-link flag |

Step 1 MUST NOT put `primary_matter` inside `related_matters` (would double-count). The prompt constraint "MUST NOT include primary_matter itself" is enforced.

---

## 3. Expected failure modes + recovery

| Failure mode | Detection | Recovery |
|---|---|---|
| JSON malformed | `json.loads()` raises | Retry once with same prompt — the retry actually protects against transient Ollama/network hiccups (connection reset, buffer underrun, partial response). Under temp=0 + seed=42, Gemma is deterministic — a true JSON bug would repeat identically. Retry succeeding = transient cause; retry failing identically → write stub with `triage_score=0`, route to inbox, log. (B2 review S2 fix, 2026-04-18.) |
| `primary_matter` is a generic category ("investment") | `slug_registry.normalize()` returns None | Treat as `primary_matter=null`. Route to inbox if `triage_score < 40`; else continue as null-matter signal. Do NOT retry. |
| `primary_matter` is a well-formed slug not in registry | `slug_registry.normalize()` returns None (same path as generic category) | Same as above. Logged at `level='WARN'` in case a new slug is in flux (e.g., mid-SLUGS-2 split). |
| `vedana` not in enum | Validate at Python level | Force `vedana='routine'`, `triage_score=20`, log `WARN`. Don't retry — Gemma deviating from enum after v3 rules means something is wrong structurally. |
| `related_matters` contains `primary_matter` | Python dedupe | Strip `primary_matter` from the array before write. No log. |
| `triage_confidence < LOW_CONF_THRESHOLD` (default 0.5) | Step 1 post-processing | Route signal to `wiki/_inbox/` for Director review regardless of `triage_score`. Log `level='INFO'`, `component='triage'`, `message='low_confidence_to_inbox'`. **Do NOT retry with Qwen.** Qwen is availability-only fallback per D1 ratification 2026-04-18. |
| Gemma unreachable (Ollama timeout or 3× connection failure) | Ollama HTTP client | Cold-swap to Qwen 2.5 14B (existing KBL-A mechanism, §D1 §173-177). Emit `level='WARN'`, `component='triage'`, `message='running on availability fallback, accuracy degraded'` per D1 Qwen-fallback clarification. Auto-recovery after 10 signals on Qwen OR 1h elapsed, retry Gemma. |
| Gemma returns no triage_confidence (pre-v3 schema) | Python post-parse | Default to 0.7 if other fields clean, 0.3 if any other field had to be coerced. Log `WARN` for telemetry drift. |

### 3.1 Invariants (§4.2 restated)

Post-write, for every signal processed by Step 1:
- `vedana IS NOT NULL` ← enforced by prompt + Python validation
- `triage_score IS NOT NULL` ← enforced by prompt + Python default to 0 on failure
- `(primary_matter IS NULL) IMPLIES (related_matters = '[]'::jsonb)` ← enforced by Python post-processor
- `primary_matter NOT IN related_matters` ← enforced by Python dedupe

---

## 4. Sampling config (unchanged from D1)

```python
OLLAMA_OPTIONS = {
    "temperature": 0.0,
    "seed":        42,
    "top_p":       0.9,
    "num_predict": 512,
}
```

D1 eval used these exact values for Gemma + Qwen. Change only after Phase-1 close-out re-eval shows delta with different sampling.

---

## 5. Prompt cost estimate (for `kbl_cost_ledger`)

- Prompt tokens: ~900-1100 (19 slugs × ~25 tokens avg + rules + signal up to 3000 chars)
- Output tokens: 60-100 (JSON schema)
- Model: Gemma 4 8B local
- Cost: $0.00 (Ollama local, no API charge)
- Latency: ~6-15s/call on macmini (v3 measured)

Ledger row: `step='triage'`, `model='ollama_gemma4'`, `input_tokens`, `output_tokens`, `cost_usd=0`, `latency_ms`.

---

## 6. Open questions for AI Head

1. **Qwen fallback trigger** — ~~confidence threshold~~ **RESOLVED by AI Head 2026-04-18.** Qwen fires ONLY on Gemma unreachability (Ollama down or 3× retry failed). D1 ratification 2026-04-18 re-scoped Qwen as availability-only fallback, not accuracy rescue. Confidence-based Qwen ensemble is not spec. Low confidence → route to `wiki/_inbox/` for Director review (see §3 table).

2. **`triage_score` calibration.** No eval measured score calibration. In v3 the score bucket hit 94% (alignment with Director's triage_pass_expected y/n), which is good but not a calibration proof. If Phase-1 close-out shows drift (e.g., Gemma consistently over-scores), add a post-hoc linear rescale. Out of scope for this prompt draft.

3. **Related-matters-only signals.** Edge case: a signal is ONLY about matter X (as context) but references Y → should primary_matter be X or null? Current prompt biases toward X (pick one glossary match). If operational data shows mis-routing, add a rule: "If signal is a forwarded reference not an action, prefer `primary_matter=null` and list both in `related_matters`." Deferred.

---

*Drafted 2026-04-18 by B3 for AI Head §6 assembly. No evals run (scope guardrail). Ready for copy-paste into KBL-B §6.*
