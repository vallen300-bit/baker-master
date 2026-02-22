# Sentinel AI — Build & Deployment Guide

## Architecture Overview

```
Sentinel = Body (infrastructure + pipeline)
Baker    = Mind (persona + reasoning inside Sentinel)
```

Sentinel implements a 5-step RAG pipeline:
1. **Trigger** — External data arrives (email, WhatsApp, meeting, calendar)
2. **Retrieval** — Semantic search (Qdrant) + structured queries (PostgreSQL)
3. **Augmentation** — Orchestrator assembles prompt within 1M token budget
4. **Generation** — Claude API processes the full context
5. **Store Back** — New learnings written to Qdrant + PostgreSQL

---

## What Already Exists (From Baker Phase 4)

| Component | Status | Details |
|-----------|--------|---------|
| Qdrant `baker-whatsapp` | ✅ Live | 39 chunks, 11 contacts, Voyage AI voyage-3 embeddings |
| Qdrant cluster | ✅ Live | `baker-memory` on AWS EU Central 1 (free tier) |
| WhatsApp extracts | ✅ Done | 11 contact JSON files in `baker/whatsapp_extracts/` |
| Indexing script | ✅ Done | `baker/chunk_and_index.py` |

---

## Build Phases

### Phase 1: Local Development (Week 1-2)
**Goal:** Get the pipeline running locally with existing Baker data.

#### Prerequisites
```bash
# Python 3.11+
python --version

# PostgreSQL (local or Docker)
docker run -d --name sentinel-pg \
  -e POSTGRES_DB=sentinel \
  -e POSTGRES_USER=sentinel \
  -e POSTGRES_PASSWORD=sentinel123 \
  -p 5432:5432 \
  postgres:16

# Install dependencies
cd sentinel
pip install -r requirements.txt
```

#### Step 1: Configure environment
```bash
cp config/.env.example .env
# Edit .env with your API keys:
# - ANTHROPIC_API_KEY (get from console.anthropic.com)
# - QDRANT_API_KEY (already have from Baker)
# - VOYAGE_API_KEY (already have from Baker)
# - POSTGRES_PASSWORD=sentinel123
```

#### Step 2: Initialize PostgreSQL
```bash
psql -h localhost -U sentinel -d sentinel -f scripts/init_database.sql
```

#### Step 3: Test the pipeline
```bash
# Check system status
python cli.py status

# Ask Baker a question (uses existing WhatsApp memory)
python cli.py ask "What do I know about the Mandarin hotel in Vienna?"

# Ask with contact context
python cli.py ask "What is my relationship with Andrey?" --contact "Andrey Oskolkov"

# Generate a briefing
python cli.py briefing
```

#### Step 4: Verify in Claude Code
If using Claude Code instead of manual setup:
```bash
# Claude Code can run the entire setup
claude "Set up Sentinel AI: install dependencies, start PostgreSQL via Docker,
       run init_database.sql, configure .env with the API keys from the
       sentinel/config/.env.example, then run python cli.py status"
```

---

### Phase 2: Add Email Trigger (Week 2-3)
**Goal:** Connect M365/Outlook as the first automated trigger.

Files to create:
- `triggers/email_trigger.py` — M365 Graph API integration
- `triggers/scheduler.py` — APScheduler for polling intervals

Key decisions:
- Microsoft Graph API for Outlook access
- Azure App Registration required (M365_CLIENT_ID, M365_CLIENT_SECRET)
- Poll every 5 minutes for new emails
- Embed and index email content into `sentinel-email` Qdrant collection

---

### Phase 3: Add Meeting Trigger (Week 3-4)
**Goal:** Scan Fireflies transcripts and extract action items.

Files to create:
- `triggers/fireflies_trigger.py` — Fireflies API integration
- Scan every 2 hours per architecture spec

---

### Phase 4: Dashboard + Outputs (Week 4-6)
**Goal:** Build the output layer.

Components:
- `outputs/dashboard.py` — FastAPI web app serving CEO dashboard
- `outputs/slack_bot.py` — Slack bot for coworker chat
- `outputs/push_notifications.py` — Alert delivery

---

### Phase 5: Azure Deployment (Week 6-8)
**Goal:** Move from local to Azure EU.

Azure resources needed:
- Azure App Service (Python web app for orchestrator)
- Azure Database for PostgreSQL
- Azure Blob Storage (file archive)
- Azure AI Document Intelligence (PDF/scan processing)
- Qdrant stays on current cluster (or migrate to Azure-hosted)

---

## Project Structure

```
sentinel/
├── cli.py                          # Command-line interface
├── requirements.txt                # Python dependencies
├── BUILD_GUIDE.md                  # This file
│
├── config/
│   ├── settings.py                 # All configuration
│   └── .env.example                # Environment template
│
├── orchestrator/
│   ├── pipeline.py                 # Main RAG pipeline (5 steps)
│   └── prompt_builder.py           # Prompt assembly + token budget
│
├── memory/
│   ├── retriever.py                # Qdrant + PostgreSQL retrieval
│   └── store_back.py               # Learning loop (write back)
│
├── triggers/                       # (Phase 2+)
│   ├── email_trigger.py            # M365 email polling
│   ├── fireflies_trigger.py        # Meeting transcript scanning
│   ├── whatsapp_trigger.py         # WhatsApp message scanning
│   └── scheduler.py                # APScheduler coordination
│
├── outputs/                        # (Phase 4+)
│   ├── dashboard.py                # FastAPI CEO dashboard
│   ├── slack_bot.py                # Slack coworker chat
│   └── push_notifications.py       # Alert delivery
│
├── scripts/
│   └── init_database.sql           # PostgreSQL schema + seed data
│
└── tests/
    └── test_pipeline.py            # Pipeline tests
```

---

## Cost Estimate

| Component | Monthly Cost | Notes |
|-----------|-------------|-------|
| Claude API (1M context) | ~€200-500 | Depends on query volume |
| Qdrant Cloud | €0 (free tier) → €30+ | Upgrade when >1GB |
| PostgreSQL | €0 (Docker local) → €15+ (Azure) | |
| Voyage AI embeddings | ~€10-30 | Per embedding volume |
| Azure App Service | ~€30 | B1 tier |
| Azure Blob Storage | ~€5 | Depends on volume |
| **Total MVP** | **~€300-600/mo** | |

---

## Key API References

- **Anthropic Claude:** https://docs.anthropic.com/en/api/messages
- **Qdrant:** https://qdrant.tech/documentation/
- **Voyage AI:** https://docs.voyageai.com/
- **Microsoft Graph:** https://learn.microsoft.com/en-us/graph/
- **Fireflies API:** https://docs.fireflies.ai/
