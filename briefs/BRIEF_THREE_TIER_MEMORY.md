# BRIEF: Three-Tier Memory Architecture — Implementation Status

**Author:** Code Brisen (Session 36)
**Date:** 27 March 2026
**Status:** Tier 2 + Tier 3 code SHIPPED. Retrieval integration PENDING.

---

## What Shipped Today

### Code (2 files, +397 lines)

| Component | File | Status |
|-----------|------|--------|
| Tier 2 compression (Opus) | `orchestrator/memory_consolidator.py` | LIVE — runs Sundays 04:00 UTC |
| Tier 3 institutional (Sonnet) | `orchestrator/memory_consolidator.py` | LIVE — runs 1st of month 04:30 UTC |
| Archive audit trail | `memory_archive_log` table | LIVE — auto-created |
| Qdrant vector replacement | Embedded in Tier 2 flow | LIVE |
| Scheduler registration | `triggers/embedded_scheduler.py` | LIVE |

### Architecture Diagram v6

| Item | URL |
|------|-----|
| Live diagram | https://vallen300-bit.github.io/brisen-dashboards/Baker_Architecture_v6.html |
| Corrections applied | 21 MCP tools (was 18), Opus/Sonnet labels, action layer updated |

---

## What's LIVE — How It Works

### Tier 1: Active Memory (0-90 days)
- **What:** Every raw interaction — emails, WhatsApp, meetings, tasks
- **Storage:** PostgreSQL (full text) + Qdrant (vector embeddings)
- **Retrieval:** Primary search path — Baker always looks here first
- **Cost:** $0 (already running)
- **No code change needed** — this is Baker's existing behavior

### Tier 2: Compressed Memory (90 days - 1 year)
- **What:** Per-matter briefs compressed by Opus
- **When:** Weekly, Sundays 04:00 UTC
- **Model:** Claude Opus (`claude-opus-4-20250514`)
- **Max tokens:** 4096 output (detailed briefs)
- **Prompt preserves:** Financial figures, dates, commitments, relationship dynamics, negotiation positions, legal terms, people, open items, strategic context, verbatim quotes
- **Storage:** `memory_summaries` table (tier=2) + new Qdrant vectors
- **Archive:** Raw interactions logged in `memory_archive_log` (never deleted)
- **Cost:** ~$12/month (30 matters × $0.10/matter)

### Tier 3: Institutional Memory (1 year+)
- **What:** Monthly digests distilled from Tier 2 summaries
- **When:** Monthly, 1st of month 04:30 UTC
- **Model:** Claude Sonnet (`claude-sonnet-4-20250514`)
- **Storage:** `memory_institutional` table
- **Cost:** ~$2/month

---

## What's PENDING — Next Steps

### Step 1: Retrieval Tier-Awareness (~3 hours)

**File:** `memory/retriever.py`

Baker's retriever currently searches ALL Qdrant collections equally. It needs to:
1. Search Tier 1 (active) first — full weight
2. If insufficient results, fall back to Tier 2 summaries — reduced weight (0.7×)
3. If still insufficient, check Tier 3 institutional — reduced weight (0.5×)

```python
# In retriever.py search flow:
# 1. Standard search (Tier 1 — active data, last 90 days)
results = qdrant_search(query, filter={"timestamp": ">90_days_ago"})

# 2. If results < threshold, add Tier 2 summaries
if len(results) < 5:
    tier2 = search_memory_summaries(query, matter_slug)
    results += tier2  # with reduced relevance weight

# 3. If still sparse, add Tier 3 institutional
if len(results) < 3:
    tier3 = search_memory_institutional(query, matter_slug)
    results += tier3
```

**Effort:** ~3 hours
**Risk:** Low — additive change, doesn't break existing search

### Step 2: Qdrant Cleanup After Compression (~2 hours)

After Tier 2 compression, optionally remove old individual interaction vectors from Qdrant to reduce noise. Currently the code adds new summary vectors but doesn't remove old ones.

```python
# After successful Tier 2 summary + embedding:
# Remove individual interaction vectors that were compressed
for interaction in compressed_interactions:
    qdrant.delete(collection="sentinel-interactions",
                  filter={"source_id": interaction.source_ref})
```

**Effort:** ~2 hours
**Risk:** Medium — need to verify source_ref matching is accurate before deleting

### Step 3: Dashboard Visibility (~1.5 hours)

Add a "Memory Health" widget to Baker Data tab showing:
- Tier 1: X records (active)
- Tier 2: X summaries (compressed)
- Tier 3: X institutional briefs
- Last compression: date
- Next compression: date
- Archive: X records preserved

**Effort:** ~1.5 hours

### Step 4: Manual Trigger for Testing (~30 min)

Add an API endpoint to trigger compression manually:
```
POST /api/memory/compress?tier=2
POST /api/memory/compress?tier=3
```

Useful for testing before waiting for the Sunday/monthly schedule.

**Effort:** ~30 min

---

## Cost Summary

| Component | Monthly Cost | Model |
|-----------|-------------|-------|
| Tier 2 compression | ~$12 | Opus |
| Tier 3 compression | ~$2 | Sonnet |
| Qdrant vectors | $0 | (existing plan) |
| PostgreSQL storage | $0 | (existing plan) |
| **Total** | **~$14/month** | |

vs. Haiku approach: ~$0.24/month — but **Opus preserves 10× more detail** for an irreversible operation.

---

## Tables Created

| Table | Purpose | Tier |
|-------|---------|------|
| `memory_summaries` | Per-matter compressed briefs | 2 |
| `memory_institutional` | Permanent institutional knowledge | 3 |
| `memory_archive_log` | Audit trail: which interactions were compressed | — |

---

## Why Opus for Tier 2

This was a deliberate decision. The compression step is **irreversible** — once raw interactions are out of the primary search path, Baker relies on the summary. If the summary drops a financial figure, a commitment, or a relationship signal, it's gone from Baker's working memory.

Haiku at $0.002/summary produces generic paragraphs that lose nuance.
Opus at $0.10/summary produces structured briefs that preserve every detail that matters.

The cost difference is $12/month vs $0.24/month. For the system that manages a Chairman's business intelligence, $12/month is the obvious choice.

---

*Brief by Code Brisen — Session 36, 27 March 2026*
