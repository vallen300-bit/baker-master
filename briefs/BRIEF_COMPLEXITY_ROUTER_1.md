# COMPLEXITY-ROUTER-1: Think Hard vs Do Fast

**Date:** 2026-03-23
**Author:** PM (Cowork Session 33)
**Status:** SPEC v2 — revised after Code 300 architectural review
**Depends on:** CORRECTION-MEMORY-1 (shipped Session 33, ef0464b)
**Estimated effort:** 5-7 hours across 3 phases
**Reviewed by:** Code 300 (Session 33) — 9 concerns addressed below

---

## Code 300 Review — Accepted Changes

| # | Concern | Resolution |
|---|---------|------------|
| 1 | Switch lives in `capability_runner.py`, not `pipeline.py` | **Accepted.** Fast/deep model switch happens in `CapabilityRunner.run_streaming()` and `run_single()`. Pipeline only passes the complexity flag. |
| 2 | Fast path must NOT skip correction injection | **Accepted.** `_build_system_prompt()` runs on BOTH paths. Only model, tokens, and tool limits change. Corrections, preferences, entity context always injected. |
| 3 | Double Haiku classification is wasteful | **Accepted.** Merge intent + complexity into a single Haiku call. One prompt returns `{ intent, complexity, confidence }`. |
| 4 | Escalation gate UX undefined | **Accepted.** Option (b): discard fast response, restart silently on deep path. Worst case: 5s wasted + 30s deep = 35s total. |
| 5 | Extended thinking not currently used | **Accepted.** Phase 2 ships WITHOUT extended thinking. Model switch only (Haiku vs Opus). Extended thinking added as a separate follow-up PR once response parsing is updated. |
| 6 | Self-verification doubles deep-path cost | **Accepted. Deferred.** CORRECTION-MEMORY-1 handles quality. Self-verification moves to future backlog. |
| 7 | Draft diff detection is aspirational | **Accepted.** Removed from "Daily — No effort required." Moved to Future section. |
| 8 | Classification cost not in projections | **Accepted.** Net cost updated in projections below. |
| 9 | Max 2 tools too tight | **Accepted.** Changed to max 3 tools on fast path. |

---

## The Problem

Baker treats every request the same way. A simple "when is the Hagenauer deadline?" gets the same Opus + multi-tool pipeline as "analyze the legal posture of the Hagenauer dispute." Current data:

- 67/146 tasks are `mode: escalate` (45%) — many are simple lookups
- Cost: EUR 8.98/day at 132 calls (11 Opus, 121 Haiku)
- Average latency: ~31 seconds regardless of complexity

## Solved State

Baker classifies every incoming request as **fast** or **deep** in the same Haiku call that determines intent. Fast tasks use Haiku with capped tools. Deep tasks use Opus with full tool access. The Director can override either direction. Baker learns from corrections which tasks it's misclassifying.

---

## Architecture

### Current Flow

```
Request → classify_intent() [Haiku] → route by TOPIC
  → CapabilityRunner: same model, same budget, same tools for everything
```

### New Flow

```
Request → classify_intent_and_complexity() [single Haiku call]
  → route by TOPIC + COMPLEXITY
  → CapabilityRunner reads complexity flag:
    → FAST: Haiku, max 3 tools, 1024 tokens, <5s target
    → DEEP: Opus, unlimited tools, 4096 tokens, 120s timeout
  → ESCALATE gate: fast auto-promotes to deep if triggers hit
```

---

## Phase 1: Merged Intent + Complexity Classifier — Shadow Mode (2-3 hours)

### Modify existing `classify_intent()` → `classify_intent_and_complexity()`

**Location:** wherever `classify_intent()` currently lives (Code 300 to confirm exact file).

**Single Haiku call.** Extend the existing classification prompt to also return complexity:

```
You are a task classifier for an AI Chief of Staff.

Return a JSON object with:
- intent: the task intent (existing categories)
- complexity: "fast" or "deep"
- complexity_confidence: float 0.0–1.0
- complexity_reasoning: one sentence explaining why

FAST means:
- Single fact lookup (date, name, status, amount)
- Yes/no question with a known answer
- Simple status check ("is X healthy?", "what's the deadline for Y?")
- Forwarding or relaying information
- Reading a single data source
- Expected answer < 200 tokens

DEEP means:
- Multi-source analysis (needs data from 2+ tables/systems)
- Judgment call (legal posture, financial recommendation, strategic advice)
- Draft that will be sent externally (email, WhatsApp to VIP)
- Anything involving money, legal risk, or reputation
- Comparison or timeline reconstruction
- Expected answer > 500 tokens
- Director explicitly says "think about this", "analyze", "what should I do"

When uncertain, classify as DEEP. False-deep is expensive but safe.
False-fast is cheap but dangerous.

Request: {request}
```

### Database changes

```sql
ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS complexity VARCHAR(10);
ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS complexity_confidence FLOAT;
ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS complexity_override VARCHAR(10);
ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS complexity_reasoning TEXT;
```

### Shadow mode

Add to `config/settings.py`:
```python
COMPLEXITY_SHADOW_MODE = os.getenv("COMPLEXITY_SHADOW_MODE", "true").lower() == "true"
```

When `COMPLEXITY_SHADOW_MODE=true`:
- Classification runs and results are stored to `baker_tasks`
- But execution path does NOT change — everything still runs on current model
- This gives us 48h of classification data before we trust it

### Wire into pipeline

1. Replace `classify_intent()` call with `classify_intent_and_complexity()`
2. Store complexity fields on the `baker_tasks` row
3. Pass `complexity` through to `CapabilityRunner` (but ignored in shadow mode)

### New endpoint for PM monitoring

```
GET /api/tasks/complexity-stats?days=7
```

Returns: count by complexity, average confidence, override count, fast/deep breakdown by domain. PM uses this to validate classifier accuracy before enabling Phase 2.

---

## Phase 2: Fast Path vs Deep Path Execution (2-3 hours)

**Prerequisite:** Phase 1 shadow mode has run for 48+ hours and PM has approved classification accuracy.

### Activation

Set `COMPLEXITY_SHADOW_MODE=false` on Render.

### Where the switch lives: `CapabilityRunner`

**`capability_runner.py`** — modify `run_streaming()` and `run_single()`:

```python
def _get_model_config(self, complexity: str):
    if complexity == "fast":
        return {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1024,
            "temperature": 0,
            "tool_limit": 3,
            "timeout": 10,
        }
    else:  # "deep" or None (default to deep for safety)
        return {
            "model": "claude-opus-4-6",
            "max_tokens": 4096,
            "temperature": 0,
            "tool_limit": None,  # unlimited
            "timeout": 120,
        }
```

**No extended thinking in this phase.** Deep path uses Opus without thinking blocks. Extended thinking is a separate follow-up PR that requires updating:
- Response parsing in `capability_runner.py` (thinking blocks in content)
- SSE streaming format
- Deliverable extraction logic

### What does NOT change between paths

These run identically on both fast and deep:

- `_build_system_prompt()` — corrections, preferences, entity context always injected
- Correction memory retrieval (CORRECTION-MEMORY-1) — always fires
- Task logging to `baker_tasks` — always fires
- Audit trail — always fires

### What changes between paths

| Component | Fast | Deep |
|-----------|------|------|
| Model | Haiku | Opus |
| Max output tokens | 1024 | 4096 |
| Tool call limit | 3 | unlimited |
| Timeout | 10s | 120s |
| Qdrant write-back | Skip (save cost) | Full embedding + store |
| `baker_insights` extraction | Skip | Write if novel finding |

### Scan chat path

**`orchestrator/scan_prompt.py`** — currently always streams Opus.

For fast-path Scan queries:
- Still inject corrections and preferences (per concern #2)
- Use Haiku model
- Cap response at 1024 tokens
- Skip injecting full meeting/email history — use only the directly relevant context

### Action handlers

**`orchestrator/action_handler.py`** — tag default complexity by action type:

| Action Type | Default Complexity | Override |
|-------------|-------------------|----------|
| `deadline_lookup` | fast | — |
| `status_check` | fast | — |
| `clickup_fetch` | fast | — |
| `email_send` (internal) | fast | — |
| `email_send` (external) | deep | — |
| `email_draft` | deep | — |
| `whatsapp_send` (VIP) | deep | — |
| `legal_analysis` | deep | — |
| `finance_analysis` | deep | — |
| `clickup_plan` | deep | — |

---

## Phase 3: Escalation Gate (1-2 hours)

### UX Decision: Silent discard and restart (option b)

If fast path triggers escalation, Baker:
1. Discards the fast-path response (user never sees it)
2. Restarts the full request on the deep path
3. Logs `complexity_override = "auto_escalated:{reason}"` on `baker_tasks`

Worst-case latency: 5s (wasted fast) + 30s (deep) = 35s. Only 4s worse than current.

### Escalation triggers

```python
async def maybe_escalate(task, fast_result):
    escalate = False
    reason = ""

    if task.complexity_confidence < 0.7:
        escalate, reason = True, "low_confidence"
    elif fast_result.tool_calls_used >= task.tool_limit:
        escalate, reason = True, "tool_limit_hit"
    elif _contains_hedging(fast_result.output):
        escalate, reason = True, "hedging_detected"
    elif _touches_legal_financial(fast_result.output) and task.domain not in ["legal", "finance"]:
        escalate, reason = True, "domain_escalation"

    if escalate:
        task.complexity = "deep"
        task.complexity_override = f"auto_escalated:{reason}"
        return await run_deep_path(task)

    return fast_result
```

### Hedging detection (simple keyword scan)

```python
HEDGING_PHRASES = [
    "i'm not sure", "i don't have enough", "this is complex",
    "i cannot determine", "insufficient information",
    "you may want to check", "i'd need more context"
]

def _contains_hedging(output: str) -> bool:
    lower = output.lower()
    return any(phrase in lower for phrase in HEDGING_PHRASES)
```

---

## Integration with CORRECTION-MEMORY-1

1. **At classification time:** Before classifying, check `baker_corrections` for routing-related corrections (e.g., "Hagenauer questions need deep analysis"). If found, bias the classifier or override directly.

2. **Post-task feedback:** Thumbs-down on a fast-path result auto-creates a correction: `correction_type: "routing"`, `learned_rule: "Task pattern X was classified fast but needed deep"`. Next time a similar request comes in, the correction biases toward DEEP.

3. **Consolidation (deferred ~April 6):** Nightly job extracts routing patterns from corrections and writes permanent rules to `director_preferences`.

---

## How to Teach Baker (Director's Guide)

### Passive — No effort required

Baker learns from your behavior automatically:

- **Thumbs up/down** on mobile or desktop → stored on `baker_tasks`, feeds classifier tuning
- **Rejecting and re-asking** ("no, think harder about this") → Baker logs the fast-path failure and auto-creates a routing correction

### On-demand — Explicit teaching

Teach Baker directly via any channel (Scan chat, WhatsApp, mobile):

| Command | What it does |
|---------|-------------|
| "Baker, remember: always think hard about [topic]" | Creates a routing correction → forces DEEP for matching requests |
| "Baker, this was overkill — fast next time" | Creates a routing correction → allows FAST for this pattern |
| "Baker, [topic] questions are always simple lookups" | Creates a routing rule in `director_preferences` |
| Thumbs down + comment on any response | Stores correction with your specific feedback |

### Weekly review — 2 minutes (once dashboard widget exists)

Review Baker's classification accuracy:

- **Misclassified fast → should have been deep:** Dangerous. You'll see these as thumbs-down on fast-path tasks. Baker auto-corrects.
- **Misclassified deep → could have been fast:** Wastes money, not dangerous. Lower priority.
- **Cost split:** How much of the daily spend is fast vs deep. Target: 70% fast, 30% deep.

### Future: Triage Dashboard (post-Phase 3, after 2-3 weeks of data)

A dedicated triage view:

1. **Domain rules** — "All legal = deep", "All status checks = fast", "Hagenauer = always deep"
2. **Misclassification review** — weekly digest of what Baker got wrong, one-click correction
3. **Cost breakdown** — fast vs deep spend per domain
4. **Pending classifications** — for sensitive topics, approve fast/deep before Baker acts

### Future: Draft diff detection (not yet built)

When the Director edits a Baker-generated draft before sending, Baker could detect the diff and store it as a correction. This requires:
- Comparing `pending_drafts.body` with the actually-sent email body
- Extracting a learned rule from the diff
- Not in scope for COMPLEXITY-ROUTER-1 — separate backlog item

---

## Expected Impact

| Metric | Before | After (projected) |
|--------|--------|-------------------|
| Daily Opus calls | ~11 | ~4-5 (only genuinely complex tasks) |
| Daily Haiku calls | ~121 | ~128 (same + replaces some Opus) |
| Classification overhead | 0 | ~0 (merged into existing intent call) |
| Daily cost | ~EUR 9.00 | ~EUR 4.50-5.50 (net of classification) |
| Simple lookup latency | ~31 seconds | <5 seconds |
| Deep analysis quality | Good | Same initially, better once extended thinking ships |
| Misclassification rate | N/A | Target <10% after 2 weeks of corrections |

---

## Implementation Order for Code 300

1. **Phase 1:** Merge intent + complexity into single Haiku call. Add DB columns. Deploy in shadow mode. **Do not change execution.** Let it classify for 48h.
2. **PM checkpoint:** PM reviews `GET /api/tasks/complexity-stats` and approves classification accuracy.
3. **Phase 2:** Wire fast/deep paths in `CapabilityRunner`. Deploy. Set `COMPLEXITY_SHADOW_MODE=false`. Monitor cost and quality for 48h.
4. **Phase 3:** Add escalation gate. Deploy. This is the safety net.
5. **Follow-up PR (separate):** Add extended thinking to deep path once response parsing is updated.

**Shadow mode is critical. Don't skip it.**

---

## Files to Modify

| File | Change |
|------|--------|
| `orchestrator/pipeline.py` (or wherever `classify_intent` lives) | Merge intent + complexity into single call, pass complexity downstream |
| `orchestrator/capability_runner.py` | `_get_model_config(complexity)` in `run_streaming()` and `run_single()` — this is where the actual model switch happens |
| `orchestrator/scan_prompt.py` | Fast-path Scan: use Haiku, cap tokens (but still inject corrections + preferences) |
| `orchestrator/action_handler.py` | Tag action types with default complexity |
| `memory/store_back.py` | Conditional Qdrant write-back (skip on fast path) |
| `outputs/dashboard.py` | New `GET /api/tasks/complexity-stats` endpoint |
| `config/settings.py` | New `COMPLEXITY_SHADOW_MODE` env var |

## New DB Columns

```sql
ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS complexity VARCHAR(10);
ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS complexity_confidence FLOAT;
ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS complexity_override VARCHAR(10);
ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS complexity_reasoning TEXT;
```

No new tables required — everything attaches to existing `baker_tasks`.
