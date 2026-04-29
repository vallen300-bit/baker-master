---
name: local-research-via-gemma-ollama
description: How to invoke free local research / synthesis via Gemma 4 on Ollama (Mac, port 11434). Zero API cost, ~30-60s for ~1500 tokens.
when_to_use: User asks for a quick research note, brainstorming, structured first-pass on a topic where training-cutoff knowledge is sufficient. Pair with Claude review for high-stakes work.
---

# Local research via Gemma 4 (Ollama)

**Capability:** Ollama runs on this Mac at `http://localhost:11434` with two models pulled. Calls are free, fast, and offline.

```
gemma4:latest   9.6 GB   — fast, ~30-60s for 1500 tokens — USE THIS
gemma4:26b     17.0 GB   — BROKEN on this install (see warning below)
```

> ⚠️ **`gemma4:26b` is broken on this Ollama install** (confirmed 2026-04-28).
> Sanity test (`"say hello in 5 words"`) returns ~50 tokens but **0 visible characters** —
> generation budget is consumed but tokens don't decode to output. Almost certainly a
> chat-template or quantization-decoding bug in this specific Q4_K_M build, NOT a prompt issue.
> **Do not fall back to `:26b` if `:latest` answer feels shallow.** Either re-prompt with more
> structure, or escalate to Claude. To re-test after an Ollama upgrade: run the health check
> below + a 5-word sanity prompt; if it returns visible text, the bug is fixed.

## When to use

- Quick local synthesis of a topic Director hands you ("what do you know about X?")
- Brainstorming options before drafting a brief
- Structured first-pass on a question where training-cutoff knowledge is sufficient
- Any time you'd otherwise burn Claude tokens on a low-stakes research turn

## When NOT to use

- Anything requiring **fresh / post-cutoff facts** → use `WebFetch` / `WebSearch` instead
- Anything touching **Brisen-internal data** (matters, contacts, signals) → use Baker MCP / vault reads
- **High-stakes** decisions where confidence matters → use Claude (Opus) and let Gemma feed it
- Tasks where **citations** are required → Gemma can't cite, only generalize

## Call signature

```bash
curl -s -X POST http://localhost:11434/api/generate -d '{
  "model": "gemma4:latest",
  "stream": false,
  "options": {"temperature": 0.4, "num_ctx": 8192},
  "prompt": "<your prompt here>"
}' | python3 -c "import sys, json; d=json.loads(sys.stdin.read()); print(d.get('response','')); print('\n---\nTOKENS:', d.get('eval_count'),'| TIME_S:', round(d.get('total_duration',0)/1e9, 1))"
```

**Use `gemma4:latest` only.** `gemma4:26b` is broken on this install (returns empty output — see warning above). For deeper work, re-prompt `:latest` with more structure or escalate to Claude.

## Prompt template — structured research note

Always force structured headings + a confidence section so Gemma flags speculation. Skeleton:

```
You are a research assistant. Produce a structured local-knowledge research note (no web access; rely on what you know up to your training cutoff).

Topic: <topic>

Structure your output exactly like this:

# <Title>

## A. <theme 1>
- bullet 1
- bullet 2

## B. <theme 2>
- ...

## G. Confidence + caveats
- one paragraph: rate your confidence, flag what is speculation vs documented, name what would need a fresh-web check.

Keep each bullet to one sentence. Be concrete. If you do not know, say UNKNOWN rather than invent. End with section G honestly.
```

## Pairing pattern

Cheap brainstorm → expensive review:

1. Gemma drafts structured note (~30s, free)
2. Claude critiques: gaps, hallucinations, blind spots
3. Claude or Director rewrites the parts that matter

## Provenance

Capability proven in `scripts/run_kbl_eval.py` (Gemma classifier on KBL pipeline) and `triggers/youtube_ingest.py`. First Director-invoked research call: 2026-04-28 (Claude Code best practices + Anthropic-internal usage — Gemma honestly flagged Section E as speculative).

## Health check

```bash
curl -s http://localhost:11434/api/tags | python3 -c "import sys, json; print('\n'.join(m['name'] for m in json.load(sys.stdin)['models']))"
```

If empty / connection refused: Ollama isn't running. Start it: `ollama serve` (or open the Ollama app).
