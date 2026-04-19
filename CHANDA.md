---
title: CHANDA — Architectural Intent
voice: gold
author: director
created: 2026-04-18
updated: 2026-04-19
status: promoted
---

# CHANDA — The Wish

> Read this file in full before every brief and every coding session. It is the only file that defines *why* Baker exists. CLAUDE.md defines *what* Baker is right now. This file defines *what Baker must remain*.

---

## 1. Mission

Harmonize **agent-speed ingestion with human-owned interpretation.**

- Human mind: one object at a time, deep judgment, conviction.
- AI: limitless objects in parallel, broad coverage, no judgment.
- KBL is the bridge. Agents write Silver. Director promotes to Gold. Gold conditions future Silver. Knowledge compounds through both breadth and depth.

The wiki is the **interest-bearing account where human judgment compounds through machine throughput.**

---

## 2. THE MAIN THING — The Learning Loop

The value of KBL is not the pipeline, the wiki, or the cards. It is **one closed loop**:

```
Director judgment (Vīmaṃsā)
   → captured as data (feedback ledger + Gold promotions)
   → read by every future pipeline run (Step 1)
   → shapes how Silver is compiled
   → presented to Director for judgment again
```

**Three legs. Break any one, the system stops learning — even if it keeps running.**

- **Leg 1 — Compounding:** Pipeline reads all Gold (by matter) before compiling Silver. No shortcuts.
- **Leg 2 — Capture:** Every Director action (promote, correct, ignore, ayoniso respond/dismiss) writes to the feedback ledger atomically. Ledger write fails → Director action fails.
- **Leg 3 — Flow-forward:** Step 1 reads `hot.md` (current-priorities cache at `~/baker-vault/wiki/hot.md`, Director-curated in Phase 1 and pipeline-maintained from Phase 3) AND the feedback ledger on every run. Not one or the other. Not on schedule. Every run.

Without all three, the system gets bigger, not smarter. It looks functional while losing its reason to exist.

---

## 3. Invariants

Non-negotiable. An engineering problem that seems to require breaking one is flagged to Director, not silently worked around.

**Loop-protecting (Section 2):**
1. Gold is read before Silver is compiled. Zero Gold is read *as* zero Gold.
2. Every Director action writes the ledger atomically, or the action fails.
3. Step 1 reads `hot.md` AND the feedback ledger on every pipeline run.

**Structural:**
4. `author: director` files are never modified by agents. Ever.
5. Every wiki file has frontmatter. Missing = pipeline failure, not warning.
6. Pipeline never skips Step 6 (Cross-link).
7. Ayoniso alerts are prompts, never overrides.
8. Silver → Gold only by explicit Director frontmatter edit. No auto-promotion.
9. Mac Mini is the single **agent** writer to `~/baker-vault`. Director may edit Gold from any machine; human writes are out-of-band and human-paced. Render writes only to `wiki_staging`.
10. Pipeline prompts do not self-modify. Learning is through data (ledger), not code.

---

## 4. Ownership — Four Iddhipāda

| Factor | Owner | Scope |
|---|---|---|
| **Chanda** (wish) | **Director** | Why we build. |
| **Viriya** (effort) | **AI / Code** | How we build. |
| **Citta** (knowledge) | **AI / Code** | What we know about the system. |
| **Vīmaṃsā** (investigation) | **Director** | Whether what was built matches the wish. |

Director owns the bookends. Without them, Viriya and Citta optimize for convenience, and the main thing drifts.

---

## 5. The Test — Before Every Push

**Q1 — Loop Test (asked first):**
Does this change preserve all three legs of Section 2?
Any change to the reading pattern (Leg 1), the ledger write mechanism (Leg 2), or the Step 1 integration (Leg 3) → stop, flag, wait for Director approval.

**Q2 — Wish Test:**
Does this serve the wish or engineering convenience?
Convenience → stop, flag, wait. Both → state the tradeoff in the commit message.

---

## 6. How This File Changes

Only the Director changes CHANDA.md. No agent, no automation, no Code session. When the wish evolves, the Director rewrites the affected section and updates the timestamp. An invariant is removed only when genuinely wrong, not inconvenient.

---

**References:** KBL-1 through KBL-18 (Baker DB #11747–11844) · Related: CLAUDE.md (state), ~/baker-vault/ (the wiki), schema/ (prompts, Tier 3 only)
