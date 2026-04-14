# Research Report: Domain SLMs + Persistent Inference for Baker Three-Tier Architecture

**Date:** 14 April 2026
**Commissioned by:** Director (Architecture Decision #24)
**Reference:** `briefs/ARCHITECTURE_THREE_TIER_DRAFT.md` (24 locked decisions)

---

## 1. Executive Summary

Baker's three-tier architecture (Render → Mac Mini → MacBook) is architecturally ahead of most production agent systems in 2026. The question was: can a domain-trained small language model replace cloud APIs for signal classification? The answer is **yes, and it's practical on your hardware**.

**Key findings:**

1. **Fine-tuning is feasible on Mac Mini M4 Pro (24GB).** MLX + QLoRA can fine-tune a 7B model in 30 minutes. The full pipeline (MLX → fuse → GGUF → Ollama) is well-documented and production-ready. **Timeline: 2-3 days** from data prep to serving.

2. **Recommended base model: Qwen 3.5 4B or Gemma 4 E4B.** Both fit comfortably on 24GB, run at 50-80 tok/s, and can co-exist with Gemma 4 12B. The fine-tuned model becomes Baker's dedicated classifier; Gemma 4 handles the fast path.

3. **The case for local SLM is latency and independence, not cost.** Cloud classification at Baker's volume costs <$1/month. Local inference is 5-10x faster (50ms vs 300ms) and works offline. The real value: zero API dependency for the most critical routing decision.

4. **NVIDIA Nemotron/AI-Q patterns are valuable as architecture references, not as tools.** Nemotron fine-tuning requires NVIDIA GPUs (not available). But AI-Q's single-call intent+depth classifier, YAML-driven workflows, and plan-iterate-cite research pattern are directly adoptable.

5. **Baker's persistent inference architecture is already best-in-class.** The `cortex_events` append-only table matches Anthropic's Managed Agents pattern. The wiki_pages + Qdrant dedup + capability routing covers what LangGraph, CrewAI, and AutoGen sell as frameworks. Don't adopt frameworks — adopt the 3-4 missing patterns: confidence scoring, forgetting curves, nightly consolidation, checkpoint-before-exhaustion.

6. **Karpathy's LLM Wiki is Baker Cortex v2.** The three-layer vault (raw/wiki/schema) maps directly to Baker's architecture. The Obsidian vault IS the wiki layer. The missing pieces: confidence scoring on wiki pages, Ebbinghaus forgetting curves, and a production consolidation job.

**Bottom line:** Fine-tune Qwen 3.5 4B on 2,000 curated classification examples from Baker's email/WhatsApp history. Serve via Ollama alongside Gemma 4. Wire into `classify_intent()`. Total investment: 2-3 days of work, zero ongoing cost.

---

## 2. Architecture Comparison: NVIDIA AI-Q vs Baker Three-Tier

| Dimension | NVIDIA AI-Q | Baker Three-Tier | Assessment |
|-----------|-------------|-----------------|------------|
| **Entry classifier** | Single LLM call → {intent, depth, meta_response} | `classify_intent()` → capability match → fast/delegate | Baker should adopt single-call pattern (intent + depth in one JSON output) |
| **Routing tiers** | meta / shallow / deep | Tier 1 (8K) / Tier 2 (200K) / Tier 3 (1M) | Aligned. Baker adds physical separation (Render/Mac Mini/MacBook) |
| **Deep research** | plan → iterate → cite (3-role subagent) | `baker_deep_analyses` | Baker should adopt plan-iterate-cite with gap detection and citation verification |
| **State management** | LangGraph checkpoints (PostgresSaver) | `cortex_events` append-only + `wiki_pages` | Baker's approach is simpler and more robust. No framework dependency. |
| **Human-in-the-loop** | Clarifier agent (approval before deep research) | Director approval (draft flow) | Aligned |
| **Model routing** | YAML-defined cost/quality tiers per model | Hardcoded in Python (Flash/Pro/Opus/Gemma) | Baker should move routing config to YAML or similar declarative format |
| **Agent definition** | YAML agent configs (tools, prompts, models) | Python capability sets in `capability_runner.py` | Baker should consider YAML agent onboarding (Phase 4 opportunity) |
| **Reliability** | Middleware stack (retry, sanitize, content fix) | Ad-hoc try/except per handler | Baker should formalize reliability middleware |
| **Evaluation** | Built-in benchmark harnesses | Manual testing | Future: automated routing accuracy benchmarks |
| **Infrastructure** | NVIDIA NIM + Kubernetes | Render + Mac Mini + PostgreSQL | Baker's is simpler, cheaper, and sufficient at current scale |

**What Baker should adopt from AI-Q:**
1. Single-call intent+depth classifier (reduce two round-trips to one)
2. YAML-driven workflow configs for agent onboarding
3. Plan-iterate-cite research pattern with 5-level citation verification
4. Formal reliability middleware (retry, sanitize, timeout)

**What Baker should ignore:**
- NIM microservices, Triton, TensorRT (NVIDIA-specific)
- Kubernetes orchestration (overkill for single-instance)
- LLM Router neural network (too low volume to train)

---

## 3. Domain SLM Feasibility

### Hardware: Mac Mini M4 Pro, 24GB Unified Memory

24GB sits in a favorable position — above the 16GB minimum and well within range for models up to ~14B quantized.

### Fine-Tuning Path: MLX + QLoRA → GGUF → Ollama

| Step | Tool | Time | Notes |
|------|------|------|-------|
| Data preparation | Python scripts + Claude labeling | 6-12 hours | Export from PostgreSQL, format as JSONL |
| Fine-tune (4B model) | `mlx_lm.lora` | 10-15 min | QLoRA, 1000 iterations, batch size 1 |
| Fine-tune (7B model) | `mlx_lm.lora` | 30-45 min | Uses ~10-12GB peak RAM |
| Fuse adapter | `mlx_lm.fuse` | 2-5 min | Merge LoRA into base |
| Convert to GGUF | `convert_hf_to_gguf.py` | 5-10 min | Q4_K_M quantization |
| Import to Ollama | `ollama create` | 1 min | Custom Modelfile |
| **Total** | | **2-3 days** | Conservative, includes data curation |

### Base Model Comparison for Baker's Classification Task

Baker needs: intent classification, priority routing (critical/high/normal/low), matter detection, document type classification, VIP recognition.

| Model | Params | Q4 RAM | Fine-tune on 24GB? | Inference Speed | Recommendation |
|-------|--------|--------|---------------------|-----------------|---------------|
| **Qwen 3.5 4B** | 4B | ~3 GB | Easily (5GB peak) | ~60-80 tok/s | **PRIMARY CHOICE** — best instruction-following at this size, multilingual |
| **Gemma 4 E4B** | 9B (4.1B active) | ~6 GB | Yes | ~40-55 tok/s | **STRONG ALTERNATIVE** — already in Baker's stack |
| **Phi-4-mini** | 3.8B | ~3 GB | Easily | ~60-80 tok/s | Good reasoning, weaker multilingual |
| **Qwen 2.5 7B** | 7B | ~5 GB | Yes (~12GB peak) | ~40-55 tok/s | Best accuracy, more training time |
| **Llama 3.2 3B** | 3B | ~2.5 GB | Easily | ~70-90 tok/s | Fastest but weakest on nuanced tasks |

**Why Qwen 3.5 4B:** Research shows Qwen 3.5 4B "rivals Qwen 2.5 72B on specific domain tasks" after fine-tuning. Strong multilingual support (German/French business context). 3GB footprint co-exists with Gemma 4 12B (8GB) within 24GB.

### Can Mac Mini fine-tune AND serve simultaneously?

**Not recommended for 7B+ models.** Training (10-12GB) + serving (5-8GB) + macOS (4-6GB) exceeds 24GB. Pattern: stop Ollama → fine-tune → convert → restart Ollama. For 3-4B models, simultaneous operation IS possible (training ~5GB + serving ~3GB + OS ~5GB = ~13GB).

### Cost Comparison

| Approach | Per-classification | Monthly (3,000 calls) | Annual |
|----------|-------------------|----------------------|--------|
| Gemini Flash-Lite (cloud) | $0.00007 | $0.21 | $2.52 |
| Claude Haiku (cloud) | $0.00019 | $0.56 | $6.72 |
| Fine-tuned local SLM | $0.00 | $0.00 | $0.00 |

**The case is NOT cost.** It's latency (50ms vs 300ms), reliability (no API failures), offline capability, and architectural independence.

### Nemotron on Apple Silicon

Nemotron 3 Nano 4B inference works on Apple Silicon (~60+ tok/s, 2.84GB RAM). But **all Nemotron fine-tuning requires NVIDIA GPUs** (NeMo framework, CUDA, Slurm clusters). Pre-trained Nemotron Nano is a viable inference option alongside Qwen/Gemma, but cannot be domain-adapted on Mac Mini.

---

## 4. Persistent Inference Patterns — What Baker Should Adopt

### What "Persistent Inference" Means for Baker

When the AO PM processes a WhatsApp message about Hagenauer on day 47, it should know everything from days 1-46 without re-reading every transcript. **The state is the product.**

### Three Validated Production Patterns

**Pattern 1: Append-Only Event Log + Stateless Harness (Anthropic Managed Agents)**

Sessions are durable, append-only logs external to the context window. A `getEvents()` interface allows flexible context interrogation. When a harness crashes, a new one boots and resumes from the last event.

→ **Baker already has this.** `cortex_events` is the append-only log. `classify_intent()` + `capability_runner` is the stateless harness. The singleton pattern in `SentinelStoreBack` provides session continuity.

**Pattern 2: Three-Primitive Context Stack (Anthropic API-native)**

1. **Tool-Result Clearing** (~50K tokens): Replace old tool outputs with `[cleared]` placeholders
2. **Compaction** (~150K tokens): LLM-summarizes conversation history
3. **Memory Tool** (cross-session): File-based persistent storage

```python
context_management={
    "edits": [
        {"type": "clear_tool_uses_20250919", "trigger": {"type": "input_tokens", "value": 50000}, "keep": {"type": "tool_uses", "value": 6}},
        {"type": "compact_20260112", "trigger": {"type": "input_tokens", "value": 150000}}
    ]
}
```

→ **Baker should adopt this for Tier 1 agents.** Capability runner calls to Claude could use compaction + clearing within the 8K budget. The memory tool maps to `wiki_pages`.

**Pattern 3: Checkpoint-Before-Exhaustion**

Agents save state to external storage when approaching context limits. Anthropic's multi-agent system: "Agents save research plans to external memory before context window approaches 200,000 tokens."

→ **Baker Tier 2 (Mac Mini, 200K) should checkpoint to PostgreSQL at ~150K.** Prevents lost work from context overflow.

### Preventing Context Drift / Hallucination Accumulation

From arXiv:2601.11653: "transcript replay causes context to grow with turn count, reduces attention selectivity, and allows early errors to persist and reappear."

**Production-validated mitigations Baker should implement:**

| Strategy | Description | Baker Implementation |
|----------|-------------|---------------------|
| **Bounded compressed state** | Wiki pages overwritten with current truth, not appended to | Already in Cortex v2 design |
| **Source grounding** | Every claim cites its source | `source_snippet` in deadlines, `source_documents` in analyses |
| **Periodic lint** | Contradiction detection, staleness, orphan cleanup | Cortex Phase 3 wiki lint (just deployed) |
| **Write-path validation** | Semantic dedup before INSERT | Cortex Phase 2B Qdrant gate (deployed) |
| **Confidence decay** | Untouched knowledge loses trust over time | **NOT YET IMPLEMENTED** — add to wiki_pages |

### Persistent Inference vs RAG: Baker's Position

| Dimension | RAG | Agent Memory (Baker) |
|-----------|-----|---------------------|
| Storage | Offline ingestion | Dynamic via tools |
| Retrieval | One-shot per query | Tool-based + cached |
| Writing | Manual | Agent writes back |
| Session state | Stateless | **Stateful across sessions** |
| Best for | Static knowledge bases | Entity tracking, learning, personalization |

**Baker is already past RAG.** Wiki pages, decisions, VIP contacts are agent memory, not retrieval-augmented generation. The remaining RAG-like component (Qdrant search for document chunks) should evolve into the wiki's search layer: query wiki first, fall back to raw document search.

### Karpathy LLM Wiki = Baker Cortex v2

| Karpathy Layer | Baker Equivalent | Status |
|----------------|-----------------|--------|
| **Raw sources** | Dropbox documents → Obsidian `raw/` | Planned (Tier 2 build) |
| **Wiki** | `wiki_pages` table → Obsidian `wiki/` | Deployed (14 pages, Cortex Phase 1A) |
| **Schema** | CLAUDE.md + capability configs | Deployed |
| **Ingest** | Email/WhatsApp/meeting pipelines → cortex_events | Deployed (Phase 2B-II) |
| **Query** | Capability runner wiki context loading | Deployed (Phase 1A) |
| **Lint** | Wiki lint job | Deployed (Phase 3) |
| **Confidence scoring** | Not yet | **RECOMMENDED** |
| **Forgetting curves** | Not yet | **RECOMMENDED** |
| **Knowledge graph overlay** | Not yet | Evaluate at 200+ pages |

**Missing pieces worth building:**

1. **Confidence scoring:** Add `confidence FLOAT`, `last_accessed TIMESTAMP`, `access_count INT` to `wiki_pages`. Every read increments access_count. Confidence decays with `e^(-t/stability)` where stability increases with each access.

2. **Nightly consolidation:** Cluster cortex_events → extract patterns → update wiki pages → decay confidence on untouched knowledge → flag contradictions for Director.

3. **Memory consolidation tiers:**
   - Working memory: current session context
   - Episodic memory: cortex_events (what happened)
   - Semantic memory: wiki_pages (what is true)
   - Procedural memory: capability configs (how to do things)

---

## 5. Recommended Additions to Baker Architecture

### Priority 1: Build Now (Production-Validated, Low Effort)

| # | Change | Effort | Where |
|---|--------|--------|-------|
| A | **Single-call intent+depth classifier** — classify_intent returns `{intent, capability, depth, priority}` in one structured JSON call | 4h | `orchestrator/capability_router.py` |
| B | **Confidence scoring on wiki_pages** — add `confidence`, `last_accessed`, `access_count` columns | 2h | `memory/store_back.py` |
| C | **Nightly consolidation job** — cluster events, update wiki, decay confidence | 8h | `triggers/embedded_scheduler.py` + new `models/consolidation.py` |
| D | **Compaction + clearing on Tier 1 agents** — use Anthropic's API-native context management | 4h | `orchestrator/capability_runner.py` |
| E | **Fine-tune Baker classifier SLM** — Qwen 3.5 4B on 2K examples, deploy via Ollama | 2-3 days | Mac Mini, new `scripts/finetune/` |

### Priority 2: Build During Tier 2 Implementation

| # | Change | Effort | Where |
|---|--------|--------|-------|
| F | **Checkpoint-before-exhaustion** on Mac Mini agents | 4h | Tier 2 cron scripts |
| G | **Citation verification** on deep analyses — 5-level URL matching from AI-Q | 6h | `models/cortex.py` or new analysis pipeline |
| H | **Forgetting curves** (Ebbinghaus decay) on wiki_pages | 4h | Consolidation job |
| I | **YAML agent configs** for Tier 2 specialist onboarding | 8h | New `schema/specialist-{name}.yml` |

### Priority 3: Evaluate Later

| # | Change | When | Why Wait |
|---|--------|------|----------|
| J | **Engraph** knowledge graph overlay | Vault reaches 200+ pages | Premature optimization below that threshold |
| K | **Claude Managed Agents API** for Tier 1 | Cost evaluation needed | May replace Render hosting |
| L | **A2A protocol** for cross-agent communication | Ecosystem maturity | Too early, no standard yet |

---

## 6. Training Data Plan

### Available Data

| Source | Volume | Classification Value |
|--------|--------|---------------------|
| Classified emails (Gmail + Bluewin + Exchange) | ~50K | High — intent + matter labels |
| WhatsApp messages | ~20K | High — priority + routing labels |
| VIP contacts with roles | ~500 | Medium — entity recognition |
| Deadlines with priorities | ~200 | Medium — urgency classification |
| Wiki pages | 14 | Domain terminology anchors |
| cortex_events | ~500+ | Classification + routing decisions |
| Baker conversation memory | ~200+ | Question → capability routing examples |

### Target Dataset: 2,000-3,000 Curated Examples

**Format: JSONL (chat/instruction)**
```jsonl
{"conversations": [
  {"from": "human", "value": "Classify this signal:\n\nSource: email\nFrom: Mario Habicher <mario@moviehotel.com>\nSubject: F&B Budget Overrun Q1\nBody: The F&B department has exceeded budget by EUR 400K in Q1..."},
  {"from": "gpt", "value": "{\"intent\": \"financial_alert\", \"priority\": \"high\", \"matter\": \"movie_am\", \"capability\": \"baker-asset-mgmt\", \"vip_mentioned\": [\"mario_habicher\"]}"}
]}
```

### Data Preparation Pipeline

| Step | Method | Output | Estimated Time |
|------|--------|--------|---------------|
| 1. **Extract labeled examples** | SQL: emails with existing classification, WhatsApp with routing decisions | ~5,000 raw examples | 2-4h (scripted) |
| 2. **Generate synthetic labels** | Use Claude to classify unlabeled messages in batch | ~5,000 additional labeled examples | 2-3h (API cost ~$5-10) |
| 3. **Curate and balance** | Review sample, balance across priorities/matters/capabilities | 2,000-3,000 final examples | 4-8h (most time-consuming) |
| 4. **Split** | 80% train / 10% validation / 10% test | Ready for training | 30 min |

### Class Balance Requirements

- **Priority levels:** Equal representation (don't over-index on "normal")
- **Matters:** Cover all active matters (Hagenauer, AO, MORV, Movie AM, etc.)
- **Capabilities:** Cover all 21 capability sets
- **Edge cases:** Ambiguous messages, multi-matter signals, non-English (German/French/Russian)
- **VIP mentions:** Include examples with known VIP contacts

### Quality Control

- **Human review:** Director reviews 100 random examples from the synthetic-labeled set
- **Held-out test set:** 10% never seen during training — used for accuracy comparison vs baseline (Gemini Flash)
- **Baseline comparison:** Run test set through current `classify_intent()` (Gemini Flash) and fine-tuned model side-by-side

---

## 7. Open Questions for Director

### Decision Required

1. **Base model choice: Qwen 3.5 4B vs Gemma 4 E4B?**
   - Qwen: smaller (3GB), faster, better multilingual, newer
   - Gemma: already in stack, MoE architecture, Google ecosystem
   - Recommendation: Start with Qwen 3.5 4B (smaller = faster iteration). Gemma 4 E4B as backup.

2. **Classification taxonomy: what are the exact output categories?**
   - Intent labels (how many? which ones?)
   - Priority levels (the 4-level system or something else?)
   - Matter detection (active matters only, or also historical?)
   - Need a 1-hour interview session to finalize taxonomy before data prep starts.

3. **When to build? Now (before Tier 2 vault) or after (when more data flows)?**
   - Argument for now: classifier improves Tier 1 routing immediately
   - Argument for later: more cortex_events = better training data
   - Recommendation: Build the data extraction pipeline now, fine-tune a proof-of-concept on 1,000 examples. Full production model after 2 weeks of Tier 2 event data.

### Information Needed

4. **Mac Mini RAM:** Confirmed 24GB. Is there an option to upgrade if needed? (M4 Pro supports up to 48GB)

5. **Ollama model co-existence:** Currently Gemma 4 12B runs on Mac Mini. Adding a 4B classifier means two models. Ollama handles this natively (loads/unloads on demand). Confirm this is acceptable — there will be a ~2-3 second cold-start when switching between models.

6. **Cloud fine-tuning budget:** If Qwen 3.5 4B proves too small, stepping up to 7B-14B is still feasible on Mac Mini. But if we ever need 27B+, cloud GPU time is required (~$2-5/hour on Lambda Labs). Is there budget appetite for this? (Likely not needed — 4B-7B should suffice for classification.)

---

## Sources

### NVIDIA Nemotron + AI-Q
- [NVIDIA Nemotron Developer Page](https://developer.nvidia.com/nemotron)
- [Nemotron 3 Nano 4B GGUF (HuggingFace)](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF)
- [NVIDIA SLM Blog](https://developer.nvidia.com/blog/how-small-language-models-are-key-to-scalable-agentic-ai/)
- [Nemotron 3 Nano Training Recipe](https://docs.nvidia.com/nemotron/latest/nemotron/nano3/README.html)
- [Inside Nemotron 3 Blog](https://developer.nvidia.com/blog/inside-nvidia-nemotron-3-techniques-tools-and-data-that-make-it-efficient-and-accurate/)
- [AI-Q GitHub Repo](https://github.com/NVIDIA-AI-Blueprints/aiq)
- [AI-Q Architecture Overview](https://docs.nvidia.com/aiq-blueprint/2.0.0/architecture/overview.html)
- [AI-Q Intent Classifier Docs](https://docs.nvidia.com/aiq-blueprint/2.0.0/architecture/agents/intent-classifier.html)
- [AI-Q Deep Researcher Docs](https://docs.nvidia.com/aiq-blueprint/2.0.0/architecture/agents/deep-researcher.html)
- [LLM Router Blueprint](https://github.com/NVIDIA-AI-Blueprints/llm-router)
- [How NVIDIA Won DeepResearch Bench](https://huggingface.co/blog/nvidia/how-nvidia-won-deepresearch-bench)
- [Apple M4 Pro Nemotron Benchmarks](https://medium.com/@andreask_75652/apples-m4-pro-is-faster-than-an-m2-max-for-nemotron-3-nano-with-mlx-2f19efbc5e50)

### Apple Silicon Fine-Tuning
- [MLX Examples LoRA README](https://github.com/ml-explore/mlx-examples/blob/main/lora/README.md)
- [WWDC 2025: Explore LLMs on Apple Silicon with MLX](https://developer.apple.com/videos/play/wwdc2025/298/)
- [LoRA Fine-Tuning On Apple Silicon MacBook](https://towardsdatascience.com/lora-fine-tuning-on-your-apple-silicon-macbook-432c7dab614a/)
- [Run and Fine-Tune LLMs on Mac with MLX-LM 2026](https://markaicode.com/run-fine-tune-llms-mac-mlx-lm/)
- [Unsloth Requirements](https://unsloth.ai/docs/get-started/fine-tuning-for-beginners/unsloth-requirements)
- [unsloth-mlx (PyPI)](https://pypi.org/project/unsloth-mlx/0.3.5/)
- [mlx-tune (GitHub)](https://github.com/ARahim3/mlx-tune)
- [Ollama Importing Models](https://docs.ollama.com/import)
- [MLX to GGUF to Ollama Guide](https://www.arsturn.com/blog/from-fine-tune-to-front-line-a-deep-dive-on-converting-mlx-models-to-gguf-for-ollama)
- [Gemma 4 vs Qwen 3.5 Comparison](https://www.mindstudio.ai/blog/gemma-4-vs-qwen-3-5-open-weight-comparison)
- [Gemma 4, Phi-4, Qwen3 Accuracy Tradeoffs (arXiv)](https://arxiv.org/abs/2604.07035)
- [Mac Mini M4 LLM ROI & Benchmarks](https://like2byte.com/mac-mini-m4-16gb-local-llm-benchmarks-roi/)
- [Apple Silicon LLM Optimization Guide](https://blog.starmorph.com/blog/apple-silicon-llm-inference-optimization-guide)

### Persistent Inference + Multi-Agent Patterns
- [Anthropic: Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Anthropic: Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Anthropic: Scaling Managed Agents](https://www.anthropic.com/engineering/managed-agents)
- [Anthropic: Multi-Agent Research System](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Anthropic: Context Engineering Cookbook](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools)
- [Claude Agent SDK Overview](https://platform.claude.com/docs/en/agent-sdk/overview)
- [LangGraph Persistence Docs](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph vs CrewAI vs AutoGen 2026](https://dev.to/pockit_tools/langgraph-vs-crewai-vs-autogen-the-complete-multi-agent-ai-orchestration-guide-for-2026-2d63)
- [Microsoft Agent Framework 1.0](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [Redis: AI Agent Architecture 2026](https://redis.io/blog/ai-agent-architecture/)
- [Mem0: State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [arXiv:2601.11653: Agent Cognitive Compressor](https://arxiv.org/html/2601.11653v1)

### Karpathy LLM Wiki
- [Karpathy: LLM Wiki (Original Gist)](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [LLM Wiki v2 (Rohit Garg)](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2)
- [Karpathy's LLM Wiki in Production (Aaron Fulkerson)](https://aaronfulkerson.com/2026/04/12/karpathys-pattern-for-an-llm-wiki-in-production/)
- [Engraph: Local Knowledge Graph](https://github.com/devwhodevs/engraph)
- [LangChain: State of Agent Engineering](https://www.langchain.com/state-of-agent-engineering)
- [Leonie Monigatti: From RAG to Agent Memory](https://www.leoniemonigatti.com/blog/from-rag-to-agent-memory.html)
- [Analytics Vidhya: Memory Systems in AI Agents](https://www.analyticsvidhya.com/blog/2026/04/memory-systems-in-ai-agents/)
- [OneUpTime: Memory Consolidation](https://oneuptime.com/blog/post/2026-01-30-memory-consolidation/view)
