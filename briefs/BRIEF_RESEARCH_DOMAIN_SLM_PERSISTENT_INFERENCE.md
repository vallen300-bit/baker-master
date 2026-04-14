# BRIEF: RESEARCH — Domain SLMs + Persistent Inference for Baker Three-Tier Architecture

## Context

Baker is an AI Chief of Staff system with a three-tier architecture:
- **Tier 1 (Render):** Always-on sensors — email, WhatsApp, calendar polling. Fast, shallow, 8K context.
- **Tier 2 (Mac Mini):** Reasoning engine — Obsidian vault, deep analysis, enriched cards. 200K context via Claude Code.
- **Tier 3 (MacBook):** Director + AI Head — decisions, strategy, full review. 1M context.

Architecture draft with 24 locked decisions: `briefs/ARCHITECTURE_THREE_TIER_DRAFT.md`

**The question this research must answer:** How should we build the triage/classification layer for Tier 2 — and can a domain-trained small language model (SLM) running locally replace cloud API calls for signal routing?

## What You Need to Research

### 1. NVIDIA Nemotron + Domain SLMs
- What is Nemotron? Architecture, model sizes, fine-tuning approach
- How do enterprises fine-tune Nemotron for vertical domains (construction claims, procurement, hospitality standards)?
- What training data volume is needed? Format? Quality requirements?
- Can Nemotron run on Apple Silicon (Mac Mini M2/M4)? Or NVIDIA GPU only?
- What open alternatives exist for Apple Silicon? (Gemma, Llama, Phi, Mistral)
- Cost comparison: domain SLM vs cloud API (Gemini Pro, Claude Haiku) for classification tasks

### 2. NVIDIA AI-Q Blueprint
- Architecture deep-dive: how does the orchestration node classify intent?
- What is "Dynamic Routing" — how does it select model depth per request?
- How does the Deep Research Agent work? (plan → iterate → cite)
- What is "Persistent Context Management" — virtual workspaces, artifact storage?
- How does AI-Q handle multi-agent coordination?
- GitHub repo: https://github.com/NVIDIA-AI-Blueprints/aiq — study the code

### 3. Persistent Inference Patterns
- What does "persistent inference" mean in production? (not one-shot, agents that maintain state)
- How do enterprise systems handle long-running agent context across sessions?
- State management patterns: database-backed, file-backed (Obsidian/markdown), vector-backed
- How do systems prevent context drift / hallucination accumulation over time?
- What's the difference between persistent inference and RAG? When to use which?

### 4. Fine-Tuning on Apple Silicon
- **MLX** (Apple's ML framework) — can it fine-tune 7B-27B models on M2/M4 Mac Mini?
- **Unsloth** — does it support Apple Silicon? What models?
- **Ollama custom models** — `ollama create` from fine-tuned weights. Workflow?
- **OpenClaw** — already installed on our MacBook. Can it serve as gateway for fine-tuned models?
- Training data preparation: what format? How to convert Baker's PostgreSQL data + Obsidian .md files into training pairs?
- Memory requirements: can Mac Mini (16GB/32GB RAM) fine-tune and serve simultaneously?

### 5. Industry Architecture Patterns for Multi-Tier Agent Systems
- How do other companies structure sensor → reasoning → decision tiers?
- Microsoft AutoGen / Semantic Kernel agent patterns
- LangGraph / LangChain agent orchestration (used by AI-Q)
- CrewAI, Autogen, Agency Swarm — multi-agent coordination
- Anthropic's own agent patterns (Claude Agent SDK, tool use, multi-turn)
- What's the state of the art for "signal queue" patterns between agent tiers?

### 6. Karpathy LLM Wiki Pattern — Extended
- Original: raw → wiki → schema three-layer vault
- How have others implemented this? (LLM Wiki v2 by Nav Toor, others?)
- Confidence scoring on knowledge — how to implement?
- Forgetting curves — how to age out stale knowledge?
- Knowledge graph overlays on markdown vaults?

## What Baker Already Has (don't reinvent)

- `cortex_events` — append-only event bus (Tier 1)
- `wiki_pages` — 14 pages, will become PG read cache synced from Obsidian vault
- Qdrant Cloud — semantic dedup + vector search (Tier 1)
- `classify_intent()` — existing intent classifier in capability router
- Gemma 4 via Ollama on Mac Mini — free local inference, ~52 t/s
- OpenClaw installed — gateway for local LLMs
- Gemini Flash/Pro — already integrated (`call_flash()`, `call_pro()`)
- Claude Opus via Anthropic API — deep analysis

## Deliverable

Write a structured research report to `outputs/RESEARCH_DOMAIN_SLM_PERSISTENT_INFERENCE.md` with:

1. **Executive Summary** — 1 page, key findings, recommendation for Baker
2. **Architecture Comparison Table** — NVIDIA AI-Q vs Baker three-tier, what aligns, what's different
3. **Domain SLM Feasibility** — can we fine-tune on Apple Silicon? Which base model? How much data needed? Timeline estimate.
4. **Persistent Inference Patterns** — what Baker should adopt, what's overkill
5. **Recommended Additions to Baker Architecture** — concrete changes to `briefs/ARCHITECTURE_THREE_TIER_DRAFT.md`
6. **Training Data Plan** — what Baker data to use, format, estimated volume
7. **Open Questions** — things that need Director decision

## Constraints

- This is RESEARCH ONLY. Do not write code. Do not modify any files except the output report.
- Be thorough — we are not in a hurry. Read actual GitHub repos, technical blogs, documentation.
- Be honest about what works on Apple Silicon vs requires NVIDIA GPUs.
- Baker runs on a Mac Mini (Apple M-series) + Render (Linux). No NVIDIA hardware.
- Focus on practical applicability to Baker, not general AI theory.
- Reference specific URLs, papers, repos for everything.

## How to Start

1. Read `briefs/ARCHITECTURE_THREE_TIER_DRAFT.md` — understand the 24 locked decisions
2. Read `briefs/CORTEX_V2_BIG_PICTURE.md` — the original two-tier concept
3. Web search the topics above — go deep, follow links, read GitHub repos
4. Structure your findings into the deliverable format
5. Save to `outputs/RESEARCH_DOMAIN_SLM_PERSISTENT_INFERENCE.md`
