# Cortex Implementation Status

**Last updated:** 16 April 2026
**Architecture:** Cortex 3T (see `briefs/ARCHITECTURE_CORTEX_3T.md`)

---

## Tier 1 — Cortex V2 (Render, DEPLOYED)

All Cortex V2 phases are deployed and running on Render.

### Phase 0: store_decision hotfix
- **Status:** DEPLOYED
- **What:** `baker_store_decision()` writes to `baker_decisions` PG table
- **Where:** `memory/store_back.py`

### Phase 1A: wiki_pages + context loading
- **Status:** DEPLOYED — 14 pages live
- **What:** `wiki_pages` PG table with `slug`, `title`, `content`, `agent_owner`, `page_type`, `matter_slugs`. Capability runner loads pages via `_load_wiki_context()` (~8K token budget).
- **Where:** `memory/store_back.py` (table + seed), `orchestrator/capability_runner.py` (loading)
- **Consumers:** `capability_runner.py`, `dashboard.py`, `cortex.py`, `seed_wiki_pages.py`
- **Cortex 3T role:** Becomes PG read cache synced from Obsidian vault (decision #17). Render agents continue reading from this table — vault sync replaces manual seeding.

### Phase 2A: cortex_events (event bus + tool router)
- **Status:** DEPLOYED — logging events
- **What:** Append-only `cortex_events` table. Every significant action logged with `event_type`, `source`, `payload`.
- **Where:** `models/cortex.py`
- **Cortex 3T role:** Decision #6 (PG is nervous system). Tier 2 reads events for nightly consolidation (#30). Event replay for recovery (#20).

### Phase 2B: semantic dedup (Qdrant)
- **Status:** DEPLOYED — shadow mode active
- **What:** Qdrant Cloud collection with Voyage AI embeddings (voyage-3, 1024d). Deduplicates signals before processing. Currently shadow mode — logs but doesn't block.
- **Where:** Qdrant Cloud (external), `memory/retriever.py`
- **Cortex 3T role:** Decision #11 (Qdrant = Tier 1 noise reduction). Prevents duplicate signals reaching Tier 2 via signal_queue.

### Phase 3: wiki lint
- **Status:** DEPLOYED — 172 findings logged
- **What:** 4-category lint: stale pages, orphan VIPs, generation behind, broken backlinks. Runs in scheduler.
- **Where:** `models/cortex.py`
- **Cortex 3T role:** Expands to 8-category vault lint run by Tier 2 nightly (Amendment #12). Current 4-category version is the foundation.

---

## Tier 2 — Mac Mini Reasoning Engine (NOT BUILT)

### signal_queue table
- **Status:** NOT BUILT
- **What:** PG bridge table between Tier 1 and Tier 2. Schema defined in Cortex 3T doc.
- **Brief:** Not yet written
- **Depends on:** Nothing — can be built standalone

### Obsidian vault
- **Status:** SMOKE TEST COMPLETE (MacBook)
- **What:** Karpathy three-layer vault (raw/wiki/schema). 14 files committed. Structure validated with NVIDIA presentations + Aukera term sheet.
- **Location:** `~/baker-vault/` on MacBook. Will migrate to Mac Mini.
- **Brief:** `briefs/BRIEF_VAULT_PHASE1_SCHEMA_AND_CONTENT.md` (requires Director discussion)
- **Plan:** `briefs/PLAN_VAULT_OBSIDIAN_V2.md` (v2.1, 12 amendments)

### Mac Mini reasoning engine (cron + claude -p)
- **Status:** NOT BUILT
- **What:** 15-min cron reads signal_queue, Gemini Pro triages vault files, `claude -p` per signal, writes enriched cards.
- **Brief:** Not yet written
- **Depends on:** signal_queue + vault Phase 1

### Vault daemon (wiki_staging → vault sync)
- **Status:** NOT BUILT
- **What:** Routes wiki_staging entries to vault with confidence scoring. Single writer pattern.
- **Brief:** Part of vault Phase 3 plan
- **Depends on:** Vault Phase 1 + signal_queue

### Nightly consolidation
- **Status:** NOT BUILT
- **What:** Decision #30 — clusters events, updates wiki, decays confidence, flags contradictions.
- **Depends on:** Vault Phase 3

---

## Tier 3 — Director + AI Head Sessions (OPERATIONAL)

Tier 3 is the current MacBook Claude Code sessions. Already operational — this is what we're doing right now. No infrastructure to build.

### Vault access from Tier 3
- **Status:** WORKING — smoke test validated
- **What:** AI Head reads/writes vault files directly during Director sessions.

### Obsidian Web Clipper
- **Status:** INSTALLED — Chrome extension configured, saves to `raw/clippings/`

---

## Implementation Sequence

```
DONE                          NEXT                           LATER
─────────────────────         ─────────────────────          ─────────────────────
Cortex V2 Phases 0-3         signal_queue table              Vault daemon (Phase 3)
(Tier 1 complete)             Vault Phase 1 (full)           Nightly consolidation
                              Mac Mini engine                 8-category vault lint
Vault smoke test              Enriched card UI                Baker SLM (parked)
Web Clipper installed
```

---

## Key Tables (Tier 1, deployed)

| Table | Role | Cortex 3T Decision |
|---|---|---|
| `wiki_pages` | Agent knowledge (becomes vault cache) | #7, #17 |
| `cortex_events` | Append-only event bus | #6, #20, #29 |
| `baker_decisions` | Stored decisions | Phase 0 |
| `signal_queue` | Tier 1→2 bridge | NOT BUILT — #6 |
| `wiki_staging` | Tier 1 suggestions for vault | NOT BUILT — #17 |
| `tier2_heartbeat` | Mac Mini health check | NOT BUILT — #16 |
