# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** SLUGS-1 shipped at `ad442cc`. Stand-by since.
**Task posted:** 2026-04-18
**Status:** OPEN — ritual acknowledgment task, short

---

## Task: CHANDA.md Onboarding — Read, Acknowledge, File Compliance Report

**Director adopted `CHANDA.md` today at `915f8ad`** — Gold file at repo root establishing KBL architectural intent. This is now the **inviolable root anchor** for every KBL session. From this commit forward, every agent startup ritual begins with CHANDA.md, *before* reading any mailbox task.

### What you must do

1. `git pull --ff-only origin main`
2. Read `CHANDA.md` end-to-end. It's one file, ~100 lines.
3. **Internalize §2 "The Learning Loop"** — the three legs (Compounding / Capture / Flow-forward). This is the main thing KBL exists to protect.
4. **Internalize §3 Invariants 1-10.** Pay particular attention to the ones that bind your typical work:
   - **Inv 4** (`author: director` files never modified by agents) — bootstrap exception applied once at `915f8ad`, never again
   - **Inv 9** (Mac Mini is the single writer; Render writes only to `wiki_staging`) — relevant when you work on schema migrations or runtime wiring
   - **Inv 10** (pipeline prompts do not self-modify) — if you're tempted to write adaptive-prompt code, stop
5. **Internalize §5 The Test.** Every push you author now passes both:
   - **Q1 Loop Test:** does this change preserve all three legs? Any touch on reading pattern / ledger write / Step 1 integration → stop + flag + wait.
   - **Q2 Wish Test:** does this serve the wish or engineering convenience? Convenience → stop + flag + wait. Both → state the tradeoff in commit message.

### Deliverable

File: `briefs/_reports/B1_chanda_ack_20260418.md` — short, ~30 lines. Structure:

```markdown
# B1 CHANDA.md Acknowledgment

**Read at commit:** 915f8ad
**Timestamp:** <UTC>

## The three legs in my own words
1. <one sentence per leg — what it means for my implementation work>
2. ...
3. ...

## Invariants most likely to bind my typical work
- <inv number>: <how it shapes decisions in implementation>
- ...

## Pre-push checklist I now run before every commit
- [ ] Q1 Loop Test passed (or flagged to AI Head)
- [ ] Q2 Wish Test passed (or tradeoff stated in commit body)
- [ ] <any additional check you adopt>

## Questions / tensions surfaced
<anything in CHANDA that conflicts with current code realities or with prior ratified decisions — flag, don't silently absorb>
```

### Why this task exists

Reading CHANDA is not optional and not one-time. Every future session starts with `cat CHANDA.md` before `cat CODE_1_PENDING.md`. This acknowledgment task establishes the ritual + creates an audit-trail report that you have onboarded the intent.

If anything in CHANDA surprises you or conflicts with what you've been building — flag it now, not later. Director specifically invited critique during adoption; your review is welcome even post-commit.

### Status after this task

You return to stand-by. SLUGS-1 shipped; Mac Mini N3 cleanup still in your parked queue (sudo rm stale symlinks — low priority). KBL-B implementation task will arrive once the brief §6-13 authoring finishes.

### Timeline

~15-20 min total (10 min reading, 5-10 min writing). Short.

### Dispatch back

> B1 CHANDA ack done — report at `briefs/_reports/B1_chanda_ack_20260418.md`, commit `<SHA>`. <any flags>

---

*Posted 2026-04-18 by AI Head. B2 mid-Step-6-scope-challenge, B3 idle post-fixture-delivery. Parallel ritual: B3 is doing the same ack task in CODE_3_PENDING.md.*
