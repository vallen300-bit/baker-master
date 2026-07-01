# Sacca: inbound signals not reaching the Box 5 ticketing desk

Classification: **problem** — a working capability is failing to deliver; no upside frame (pure incumbent harm). Author: lead (AH1). For cowork-ah1 second-eyes review, 2026-07-01.

## Problem frame

**1. Dukkha — what is the problem.**
The end-to-end signal journey (inbound email → ingestion → ticketing → routing → desk) is not happening reliably; materially-relevant signals never reach the desk. [known]
- `airport_tickets`: 5 rows total, latest 2026-07-01 05:57Z, none in ~9.5h since. [known]
- Live proof: Siegfried→Balazs Aukera/Annaberg ESG email (2026-07-01 13:09Z) is a real deal signal that never reached baden-baden-desk. [known]
- Cost: the desk runs the matter blind to fresh signals; Director is the failover, manually spotting gaps. The downstream Box 5 work (correlation fix, status mapping) is moot without intake. [known]

**2. Samudaya — origin.**
Box 5 was built as a **narrow single-lane pilot**, not a general intake; the journey has 4 sequential filters, each dropping signals **silently**: [known]
- Gate 1 — Ingestion: graph poller scans Dimitry's **Inbox folder only** (`_FOLDER="Inbox"`); filed/subfolder mail never enters `email_messages`. [known]
- Gate 2 — Ticketing pull: bridge only reads emails matching `active_keywords()` (default `aukera/annaberg/lilienmatt`), scoped to one desk/matter/flight via env, behind `AIRPORT_TICKETING_BRIDGE_ENABLED`. Any email lacking those 3 words is never pulled. [known]
- Gate 3 — Routing: post-#446 (routing reversal) only explicit project codes or registered participants route; code-less non-participant mail routes nowhere. [known]
- Gate 4 — Observability: every drop is silent — no log of "considered but dropped", so gaps are invisible until a human notices. [known]
- Sustained by: the pilot scope was never widened to a general journey; each gate was individually reasonable but they compound multiplicatively. [assumed]

**3. Nirodha — what good looks like (testable).**
Every materially-relevant inbound email reaches the correct desk within one tick cycle — regardless of folder, phrasing, or explicit code — and every intentionally-dropped signal is logged and queryable. [known]
- Test A: replay Siegfried's ESG email through the live journey → a BB-AUK-001 ticket lands on baden-baden-desk. [known]
- Test B: a subfolder-filed, code-less email on a matter-bound thread also lands as a ticket. [known]
- Test C: a dropped/irrelevant email appears in a queryable "dropped signals" trail with a reason. [known]

**4. Magga — path.**

| # | Step | Owner | Due | Proof of done |
|---|---|---|---|---|
| 1 | Widen ingestion past Inbox (per-folder delta enumeration — Option B; mailbox-wide delta doesn't exist, b2-verified) | b2 | in flight | subfolder email ingests into `email_messages` |
| 2 | Thread-continuity routing (code-bound thread inheritance) | b3 | in flight | code-less reply on a bound thread routes to its matter |
| 3 | Broaden Gate 2: replace 3-keyword gate with matter-scoped relevance (per-matter participant/thread binding, or classifier) | new brief | TBD | a relevant non-keyword email is pulled into ticketing |
| 4 | Add drop observability — log every considered-but-dropped signal + reason | new brief | TBD | dropped signals queryable; Test C passes |
| 5 | Verify tick runs on schedule + widen pilot beyond single lane (enabled, scheduled, multi-matter) | lead | TBD | `airport_tickets` grows across matters; scheduler confirmed |
| 6 | End-to-end live canary: replay Siegfried's ESG email | lead/b-code | after 1-5 | BB-AUK-001 ticket lands on baden-baden-desk (Test A) |

## Research list
1. Is `AIRPORT_TICKETING_BRIDGE_ENABLED` actually `true` on Render, and is the tick scheduled/running on an interval? (5 tickets then silence suggests enabled-but-starved OR tick stalled.) [needs-research]
2. What produced the 5 existing tickets, and when did new-ticket creation stop — keyword starvation, ingestion gap, or tick halt? [needs-research]
3. Is the 3-keyword gate the intended long-term design, or a pilot artifact to widen? (design intent, Director/architect) [needs-research]
4. Does widening ingestion to all folders create volume/noise the keyword gate was compensating for? (interaction risk between fixes 1 and 3) [needs-research]

## Devils-advocate (self, pre-cowork)
- Fixing Gates 1+2+3 without Gate 4 (observability) means the NEXT silent gap is also invisible — Gate 4 may be the highest-leverage step, not the last. [assumed]
- Widening ingestion (fix 1) before broadening the keyword gate (fix 3) could flood the single-lane pilot with unmatched mail that's silently dropped anyway — sequence 3 before/with 1. [assumed]
- Biggest unknown: is the tick even running? If the scheduler stalled (research #1), fixes 1-3 are irrelevant until it's restarted. Verify #1 FIRST.
