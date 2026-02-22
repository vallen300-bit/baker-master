#!/usr/bin/env python3
"""
Baker RAG Pipeline — Retrieve → Augment → Generate
====================================================
Full Punch-2 integration: Qdrant semantic search feeds context into
the 1M Claude Opus context window for reasoning.

Usage:
    python baker_rag.py --query "What is the status of the Hagenauer settlement?"
    python baker_rag.py --query "Who is Thomas Sattler?" --collections baker-people baker-conversations
    python baker_rag.py --query "..." --limit 20 --threshold 0.25
    python baker_rag.py --query "..." --dry-run   # show retrieved context without calling Claude

Architecture:
    Query → [Voyage AI embeds] → [Qdrant retrieves top-k] → [Claude Opus 4.6 reasons + answers]
"""

import anthropic
import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime

import voyageai
from qdrant_client import QdrantClient

from config.settings import config

# ─── Configuration ───────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "analysis_outputs"


# ─── Retrieval Layer ─────────────────────────────────────────────────────────

def embed_query(voyage_client, query):
    """Embed a query string using Voyage AI voyage-3."""
    result = voyage_client.embed([query], model=config.voyage.model, input_type="query")
    return result.embeddings[0]


def retrieve_context(qdrant, voyage_client, query, collections=None,
                     limit_per_collection=10, score_threshold=0.3):
    """
    Search Qdrant collections for context relevant to the query.
    Returns list of dicts with: collection, score, label, text, metadata.
    """
    if collections is None:
        collections = config.qdrant.collections

    query_vector = embed_query(voyage_client, query)
    all_results = []

    for coll in collections:
        try:
            results = qdrant.query_points(
                collection_name=coll,
                query=query_vector,
                limit=limit_per_collection,
                score_threshold=score_threshold,
            )
            for point in results.points:
                payload = point.payload or {}
                text = payload.get("text", payload.get("content", ""))
                # Build a label from whichever field exists
                label = (payload.get("name")
                         or payload.get("deal_name")
                         or payload.get("project")
                         or payload.get("meeting_title")
                         or payload.get("chat_name")
                         or payload.get("subject")
                         or payload.get("title")
                         or "unknown")

                all_results.append({
                    "collection": coll,
                    "score": point.score,
                    "label": label,
                    "text": text,
                    "metadata": {
                        k: v for k, v in payload.items()
                        if k != "text" and k != "content"
                    },
                    "token_estimate": len(text) // 4,
                })
        except Exception as e:
            print(f"  WARN: Could not search {coll}: {e}", file=sys.stderr)

    # Sort by relevance (highest first)
    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results


def format_retrieved_context(results, max_tokens=500_000):
    """
    Format retrieved results into a context block for Claude.
    Respects a token budget so we don't overflow the context window.
    """
    blocks = []
    running_tokens = 0

    for i, r in enumerate(results):
        token_est = r["token_estimate"]
        if running_tokens + token_est > max_tokens:
            blocks.append(f"\n[... {len(results) - i} more results truncated — token budget reached ...]")
            break

        # Format metadata compactly
        meta_parts = []
        md = r["metadata"]
        if md.get("date"):
            meta_parts.append(f"Date: {md['date']}")
        if md.get("participants"):
            p = md["participants"]
            if isinstance(p, list):
                meta_parts.append(f"Participants: {', '.join(p)}")
            else:
                meta_parts.append(f"Participants: {p}")
        if md.get("project"):
            meta_parts.append(f"Project: {md['project']}")
        if md.get("person_type"):
            meta_parts.append(f"Type: {md['person_type']}")
        if md.get("role"):
            meta_parts.append(f"Role: {md['role']}")
        if md.get("deal_stage"):
            meta_parts.append(f"Stage: {md['deal_stage']}")
        if md.get("status"):
            meta_parts.append(f"Status: {md['status']}")
        if md.get("section"):
            meta_parts.append(f"Section: {md['section']}")
        if md.get("source"):
            meta_parts.append(f"Source: {md['source']}")

        meta_str = " | ".join(meta_parts) if meta_parts else ""
        source_type = r["collection"].replace("baker-", "").upper()

        block = f"""--- [{source_type}] {r['label']} (relevance: {r['score']:.3f}) ---
{meta_str}
{r['text']}
"""
        blocks.append(block)
        running_tokens += token_est

    return "\n".join(blocks), running_tokens, len(blocks)


# ─── Generation Layer ────────────────────────────────────────────────────────

def estimate_cost(input_tokens, output_tokens=4096):
    """Estimate API call cost."""
    cc = config.claude
    if input_tokens <= 200_000:
        input_cost = (input_tokens / 1_000_000) * cc.cost_per_m_input_standard
        output_cost = (output_tokens / 1_000_000) * cc.cost_per_m_output_standard
    else:
        standard_input = (200_000 / 1_000_000) * cc.cost_per_m_input_standard
        premium_input = ((input_tokens - 200_000) / 1_000_000) * cc.cost_per_m_input_premium
        input_cost = standard_input + premium_input
        output_cost = (output_tokens / 1_000_000) * cc.cost_per_m_output_premium
    return input_cost + output_cost


BAKER_SYSTEM_PROMPT = """You are Baker, the AI Chief of Staff for Dimitry Vallen, Chairman of Brisengroup.

You have access to retrieved memory context from multiple sources: WhatsApp conversations, meeting transcripts, project documents, people profiles, and deal records. This context was retrieved by semantic search based on the user's query.

Your role:
1. **Synthesize** information across all retrieved sources — connect dots the human might miss
2. **Be specific** — cite names, dates, figures, and quotes from the retrieved context
3. **Flag gaps** — if the context doesn't fully answer the question, say so clearly
4. **Be actionable** — end with concrete next steps or recommendations
5. **Person-centric** — organize information by WHO, not by which tool/source

Response format:
- Bottom-line answer first (1-2 sentences)
- Supporting evidence with source attribution (e.g., "[WhatsApp, Feb 12]", "[Meeting, Jan 15]")
- Gaps or uncertainties
- Recommended actions

Remember: You serve as Dimitry's trusted advisor. Be warm but direct. Challenge assumptions when warranted."""


def call_baker_rag(retrieved_context, query, max_output_tokens=8192):
    """Make the RAG generation call: retrieved context → Claude → answer."""
    client = anthropic.Anthropic(api_key=config.claude.api_key)

    user_message = f"""<retrieved_memory_context>
{retrieved_context}
</retrieved_memory_context>

<query>
{query}
</query>"""

    input_token_est = len(user_message) // 4
    print(f"\n  Calling Claude Opus 4.6 (RAG mode)...")
    print(f"  Estimated input: ~{input_token_est:,} tokens")

    start_time = time.time()

    response = client.messages.create(
        model=config.claude.model,
        max_tokens=max_output_tokens,
        system=BAKER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
        extra_headers={"anthropic-beta": config.claude.beta_header},
    )

    elapsed = time.time() - start_time

    result_text = response.content[0].text
    usage = response.usage
    cost = estimate_cost(usage.input_tokens, usage.output_tokens)

    stats = {
        "model": config.claude.model,
        "mode": "rag",
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "estimated_cost_usd": round(cost, 4),
        "elapsed_seconds": round(elapsed, 1),
        "timestamp": datetime.now().isoformat(),
        "stop_reason": response.stop_reason,
    }

    return result_text, stats


def save_output(result_text, stats, query, retrieval_summary, label=None):
    """Save RAG output to file."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label_slug = (label or "rag_query").replace(" ", "_")[:40]
    filename = f"{timestamp}_{label_slug}.md"
    filepath = OUTPUT_DIR / filename

    with open(filepath, 'w') as f:
        f.write(f"# Baker RAG Analysis\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"**Query:** {query}\n\n")
        f.write(f"**Retrieval:** {retrieval_summary}\n")
        f.write(f"**Generation:** {stats['input_tokens']:,} input, "
                f"{stats['output_tokens']:,} output, "
                f"${stats['estimated_cost_usd']:.2f} cost, "
                f"{stats['elapsed_seconds']}s\n\n")
        f.write(f"---\n\n")
        f.write(result_text)

    return filepath


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Baker RAG Pipeline — Retrieve → Augment → Generate")
    parser.add_argument('--query', required=True, help='Question for Baker')
    parser.add_argument('--collections', nargs='+', default=None,
                        help=f'Qdrant collections to search (default: all). Options: {", ".join(config.qdrant.collections)}')
    parser.add_argument('--limit', type=int, default=10, help='Results per collection (default: 10)')
    parser.add_argument('--threshold', type=float, default=0.3, help='Min relevance score (default: 0.3)')
    parser.add_argument('--max-context-tokens', type=int, default=500_000,
                        help='Max tokens for retrieved context (default: 500K)')
    parser.add_argument('--max-output', type=int, default=8192, help='Max output tokens (default: 8192)')
    parser.add_argument('--label', help='Label for output file')
    parser.add_argument('--dry-run', action='store_true', help='Show retrieval results without calling Claude')
    parser.add_argument('--json-stats', action='store_true', help='Output stats as JSON to stderr')

    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  BAKER RAG PIPELINE")
    print(f"  Retrieve → Augment → Generate")
    print(f"{'='*60}")
    print(f"  Query: {args.query}")

    # ── Step 1: Retrieval ────────────────────────────────────────────────
    print(f"\n  [1/3] RETRIEVAL — Searching Qdrant...")

    qdrant = QdrantClient(url=config.qdrant.url, api_key=config.qdrant.api_key)
    voyage = voyageai.Client(api_key=config.voyage.api_key)

    results = retrieve_context(
        qdrant, voyage, args.query,
        collections=args.collections,
        limit_per_collection=args.limit,
        score_threshold=args.threshold,
    )

    print(f"  Retrieved: {len(results)} chunks from {len(set(r['collection'] for r in results))} collections")
    if results:
        print(f"  Top score: {results[0]['score']:.4f} [{results[0]['collection']}] {results[0]['label']}")
        print(f"  Min score: {results[-1]['score']:.4f} [{results[-1]['collection']}] {results[-1]['label']}")

    # Show top 5 results summary
    print(f"\n  Top results:")
    for i, r in enumerate(results[:5], 1):
        source = r["collection"].replace("baker-", "")
        print(f"    {i}. [{source}] {r['label']} (score={r['score']:.3f}, ~{r['token_estimate']} tok)")

    if not results:
        print(f"\n  No relevant context found. Try lowering --threshold or broadening the query.")
        return

    # ── Step 2: Augmentation ─────────────────────────────────────────────
    print(f"\n  [2/3] AUGMENTATION — Formatting context...")

    context_block, context_tokens, context_chunks = format_retrieved_context(
        results, max_tokens=args.max_context_tokens
    )

    total_tokens_est = context_tokens + len(BAKER_SYSTEM_PROMPT) // 4 + len(args.query) // 4
    retrieval_summary = (f"{len(results)} chunks retrieved, {context_chunks} used, "
                        f"~{context_tokens:,} context tokens")

    print(f"  Context: {context_chunks} chunks, ~{context_tokens:,} tokens")
    print(f"  Total est: ~{total_tokens_est:,} tokens ({total_tokens_est/config.claude.max_context_tokens*100:.1f}% of 1M)")
    print(f"  Est cost: ~${estimate_cost(total_tokens_est):.2f}")

    if args.dry_run:
        print(f"\n  [DRY RUN] Retrieval complete. Context block ({len(context_block):,} chars):")
        print(f"\n{'─'*60}")
        # Show first 3000 chars of context
        preview = context_block[:3000]
        if len(context_block) > 3000:
            preview += f"\n\n[... truncated, {len(context_block) - 3000:,} more chars ...]"
        print(preview)
        print(f"{'─'*60}")
        print(f"\n  No API call made. Remove --dry-run to generate.")
        return

    # ── Step 3: Generation ───────────────────────────────────────────────
    print(f"\n  [3/3] GENERATION — Calling Claude Opus 4.6...")

    result_text, stats = call_baker_rag(
        context_block, args.query, args.max_output
    )

    # Save
    filepath = save_output(result_text, stats, args.query, retrieval_summary, args.label)

    print(f"\n  {'='*50}")
    print(f"  BAKER RAG COMPLETE")
    print(f"  {'='*50}")
    print(f"  Retrieval: {retrieval_summary}")
    print(f"  Input:     {stats['input_tokens']:,} tokens")
    print(f"  Output:    {stats['output_tokens']:,} tokens")
    print(f"  Cost:      ~${stats['estimated_cost_usd']:.2f}")
    print(f"  Time:      {stats['elapsed_seconds']}s")
    print(f"  Saved:     {filepath}")
    print(f"  {'='*50}\n")

    # Output Baker's response
    print(result_text)

    if args.json_stats:
        stats["retrieval"] = retrieval_summary
        print(json.dumps(stats), file=sys.stderr)


if __name__ == "__main__":
    main()
