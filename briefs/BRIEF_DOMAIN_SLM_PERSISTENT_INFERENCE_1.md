# BRIEF: DOMAIN_SLM_PERSISTENT_INFERENCE_1 — Local classifier SLM + Brisen data-sovereignty layer

**Status:** DRAFT — queued for Director ratification (no dispatch until §Open Questions all-ratified).
**Source research:** `outputs/RESEARCH_DOMAIN_SLM_PERSISTENT_INFERENCE.md` (2026-04-14, Architecture Decision #24).
**Anchor:** Director question 2026-05-20 night: "why not to have ollama installed?" → discussion clarified the real driver isn't ops cost, it's **data sovereignty for sensitive Brisen matters** (Hagenauer, Cupial, MOHG, financial figures).

### Surface contract: N/A — pure backend / inference-layer brief; no user-clickable surface (Director ratifies via chat, no dashboard/panel/button introduced).

## Context

Two-part scope:

**Part A — Classifier SLM (covered by 2026-04-14 research):** replace cloud `classify_intent()` (currently Gemini Flash) with a fine-tuned local Qwen 3.5 4B or Gemma 4 E4B on Mac Mini M4 Pro. Sub-50ms latency, zero ongoing API cost, 100% local for the routing decision. ~2-3 days of work.

**Part B — Sovereign reasoning layer (new scope, post-2026-05-20):** the deeper architectural question. Today every Cortex Phase 3 specialist (legal / finance / tax / game-theory) calls Anthropic / Google / xAI clouds with full matter content. For specific sensitive matters, Brisen may want inference to stay inside Brisen infrastructure. This is a 3-6 month architectural commitment, not a tonight env-var.

This brief queues BOTH parts. Director ratifies which part proceeds first (or both in parallel).

## Estimated time
- **Part A only:** 2-3 days build + 1-2 weeks fine-tune iteration
- **Part B (full sovereignty):** 3-6 months (hardware procurement + model selection + matter scoping)

## Complexity
- Part A: Medium (well-documented MLX → GGUF → Ollama pipeline)
- Part B: High (hardware, ops, matter classification, dual-path orchestration)

## Director ratification — 8 open questions

### Part A questions (from research §7)

1. **Base model: Qwen 3.5 4B or Gemma 4 E4B?**
   Recommendation: **Qwen 3.5 4B** — smaller (3 GB), faster iteration, better multilingual (DE/FR/RU all in your portfolio). Gemma stays in stack for the fast path; Qwen becomes the dedicated classifier.

2. **Classification taxonomy — which output categories?**
   Recommendation: **start with 4 fields** — `intent` (~15 labels), `priority` (4 levels), `matter` (active-only, ~10 slugs), `capability` (21 sets). Defer VIP recognition + multi-matter signals to v2. 1-hour interview with you to finalize labels before data-prep starts.

3. **Timing — build Part A now, or after Tier 2 vault ships?**
   Recommendation: **build the data-extraction pipeline NOW** (2 days, no model training), then **proof-of-concept fine-tune on 1,000 examples next week**, then **full production model after 2 weeks of Tier 2 event data accumulates**. Decouples blocking work.

4. **Mac Mini RAM upgrade — stay at 24 GB or upgrade to 48 GB?**
   Recommendation: **stay at 24 GB for Part A** — Qwen 4B + Gemma 12B co-exist within 24 GB during inference. Upgrade only if Part B proceeds + we want 7B+ classifier or simultaneous fine-tune+serve.

5. **Cold-start tradeoff — Ollama swaps between Gemma + Qwen with ~2-3s cold-start. Acceptable?**
   Recommendation: **acceptable** — classifier runs on signal arrival (async pipeline, not interactive); Gemma stays warm for fast-path queries. Worst case: first classifier call after Gemma run takes ~3s.

6. **Cloud GPU budget if Part A's 4B proves too small + 27B+ needed?**
   Recommendation: **no cloud GPU now** — 4B-7B will suffice for classification (research §3 confirms 4B "rivals Qwen 2.5 72B on specific domain tasks" post fine-tune). Park the cloud-GPU question.

### Part B questions (new, post-2026-05-20)

7. **Sovereignty scope — which matters require local-only inference?**
   Recommendation: **start with Hagenauer + Cupial + AO + MOVIE (4 matters)** — those have the highest sensitivity (active disputes, partner commercials, hotel financials). Other matters stay cloud-routed. Forces an explicit classifier decision per signal: "sovereign matter → local SLM → never leaves infra" vs "non-sovereign → cloud as today".

8. **Sovereign hardware — Mac Mini M4 Pro (24 GB) or step up to Mac Studio M-Ultra / GPU host?**
   Recommendation: **Mac Studio M3 Ultra 96 GB** for sovereign reasoning (~CHF 7-8K one-time, runs 70B models comfortably at 30-40 tok/s). Far cheaper than 1 year of cloud at sovereign-only volume, and the unit lives in your Geneva office under your physical control. Mac Mini M4 Pro stays as the classifier host.

## Pre-flight (when ratified, not now)

1. Confirm Mac Mini M4 Pro 24 GB is reachable from baker-master (Tailscale + OLLAMA_HOST env var pointing at `tailscale://mac-mini:11434` — would restore the OLLAMA_HOST env var I deliberately retired 2026-05-20).
2. Inventory existing labeled data (emails + WA + meetings) for Qwen training set.
3. Decide whether classifier replaces Gemini Flash entirely or runs in shadow-mode first.

## Files in scope (preview only, no edits before ratification)

- `orchestrator/capability_router.py` — `classify_intent()` swap from Gemini Flash to local Ollama HTTP
- `scripts/finetune/` — NEW directory for MLX training scripts
- `models/consolidation.py` — NEW, for nightly wiki consolidation (research §4 Pattern 1 extension)
- `triggers/embedded_scheduler.py` — add nightly consolidation job
- Render env: `OLLAMA_HOST` restored (was retired 2026-05-20) when Part A ships

## Do NOT touch until ratified

- Mac Mini OS / Ollama install (you control physically; AH1 doesn't SSH-install models on your hardware without ratification)
- `outputs/RESEARCH_DOMAIN_SLM_PERSISTENT_INFERENCE.md` — read-only source

## Ratification queue position

Added to Cortex Backlog with `priority=normal`, `eta=Director-ratification-pending`. Brief sits as DRAFT until ratified. Re-surface every weekly Monday digest until you ratify or DROP.

## Composition with shipped work

- Independent of Director Card v1.1 (dispatched tonight, b1 building).
- Independent of state-reconciler Phase 2.
- Aligned with `outputs/RESEARCH_DOMAIN_SLM_PERSISTENT_INFERENCE.md` Priority-1 items A-E.
- Part B is the architectural fulcrum that turns Brisen into a sovereign-inference-capable Group rather than a cloud-LLM-tenant.
