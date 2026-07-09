# AO_PROFILE_PROGRAM_1 — Oskolkov psychological profile + 20-year reciprocity ledger (autonomous loop)

**Status:** AUTHORED — NOT DISPATCHED. Hard gate: Director final GO required before any bus dispatch (Director directive 2026-07-09: "do not dispatch without my final go").
**Author:** cowork-ah1 (program design). **Orchestrator on dispatch:** deputy (AH2).
**Anchor directives (Director, 2026-07-09, cowork-ah1 session):**
- Option 5 ratified: AO desk reads profile before every counterparty-facing advice, updates after every material contact.
- "any material advice he can not produce advice unless he reads the profile" — hard gate, materiality defined below.
- Profile must include "all the things that for the last 20 years I owe to A.O. morally or commercially, and he owes to us morally or commercially."
- Pipeline: Researcher methodology → cheap models dig ("Sonnet and Haiku, Librarian and CM1"; NB CM seats all Sonnet 1M as of 2026-07-09, no Haiku) → "somebody clever like Opus 4.8" synthesizes.
- Orchestrator NOT lead ("He is too busy"); deputy suggested, temporary Fable flip accepted per cowork-ah1 recommendation (Opus waves 0–3, Fable waves 4–5).
- First live application: upcoming negotiation to increase AO's shadow-equity participation in the MOVIE project.

---

## Problem

The existing AO profile is Director-authored and shallow — too thin to materially change AO-desk advice on a EUR 66.5M relationship. The desk has no reciprocity ledger (who owes whom, morally/commercially, over 20 years) and no enforced profile-read gate on material advice. The upcoming MOVIE shadow-equity negotiation needs both.

## Context Contract

- **Matter:** oskolkov (canonical slug `ao` alias per D-014 realignment). Exposure EUR 66,511,752 principal (D-001).
- **Existing profile:** Director-authored, shallow — insufficient to materially change desk advice. Relationship card (AO_FLIGHT_RELATIONSHIP_1, PR #495) currently carries read×6 / red_flags×5 / orbit×7, desk-receipted.
- **Corpus available:** Baker DB documents (322+ AO-tagged), `baker_email_search` (incl. bluewin since 2026-06-09; pre-06-09 Bluewin history only via Mail.app on Director's machine — known gap, flag don't block), Gmail, WhatsApp via `/api/whatsapp/messages` (AO chat 491736903746@c.us, vip_contacts id 1893), transcripts via `/api/transcripts/by-matter/oskolkov`, ClaimsMax archive, vault `wiki/matters/oskolkov/` curated + findings.
- **Lookback:** 20 years (Director's ledger directive supersedes the earlier 15-year phrasing), bounded by data availability — hunts must state coverage floor actually reached.
- **Sensitivity rule (standing, from AO_FLIGHT_RELATIONSHIP_1):** full profile + ledger = DESK-ONLY vault files, never rendered pages, never CEO card. Card receives a distilled non-sensitive layer only, via ao-desk content lane + AH publish (contract rule 13). Rosfinmonitoring profile, Constantinos bereavement / info-asymmetry class items stay off-card.

## Task class

Orchestration program (multi-agent loop) + one small build item (materiality hook, wave 5 B-code sub-brief). No production code in waves 0–4.

## Participants

| Seat | Role | Model |
|---|---|---|
| deputy | Orchestrator + wave-4 synthesizer | Opus 4.8 waves 0–3; **Fable flip waves 4–5** (Director executes/authorizes seat model change; revert at close) |
| researcher | Wave-0 methodology (research-fan-out + verify-citations) | per seat |
| librarian (AG-209) | Registry-driven corpus hunts (operational today) | Sonnet 1M |
| CM-1 / CM-2 / CM-3 | Hunt diggers | Sonnet 1M (all CM seats now Sonnet 1M — no Haiku, Director 2026-07-09) |
| ao-desk, movie-desk, baden-baden-desk, brisen-desk | Consultants: touchpoint census, finding annotation, gap flags | per seat |
| codex | Cross-vendor gate on methodology (G0) + final profile (G3) | codex CLI |
| cowork-ah1 | Program AUTHOR only — App-resident, NOT autonomous; joins Director at the final ratify decision. Does NOT receive mid-loop worker reports | — |
| lead | Only: Tier-B env flips (desk autowake whitelist) + merges if any | — |
| Director | Wave-end checkpoints; ratifies materiality definition, final profile + ledger | — |

## The loop — five waves

**Wave 0 — Methodology + census (target 1 day).**
- Researcher: how professional counterparty/psychological profiles are constructed (negotiation intelligence, private-banking KYC, executive profiling; sections, evidence standards, common failure modes) + how obligation/reciprocity ledgers are built. Output: `wiki/research/` report, citation-verified.
- Parallel desk census: each consultant desk lists known AO touchpoints over 20 years — deals, favors, rescues, defaults, concessions, personal gestures, broken promises — each with date + where evidence likely sits.
- Exit gate: codex G0 PASS on methodology → deputy converts methodology + census into a hunt taxonomy (per-source, per-theme hunt briefs with receipt requirements).

**Wave 1 — Corpus hunts (target 2–3 days).**
- Librarian + CM seats sweep WhatsApp, transcripts, emails, documents per taxonomy. Every finding receipted (doc id / message id / transcript id + verbatim quote — Lesson #78: quote must support the conclusion, not just the number).
- Findings land in vault `wiki/_library/findings/` per librarian pattern; deputy tallies coverage per source per theme.
- Exit gate: every taxonomy cell either has findings or an explicit MISS with coverage note. No silent caps.

**Wave 2 — Desk consultation loop (target 2–3 days).**
- Deputy digests findings → consultant desks annotate: confirm, correct, add context, flag gaps. Gaps re-fire hunts (back to Wave 1 mechanics).
- Loop-until-dry: iterate until **2 consecutive rounds produce no new material findings**.
- **Room-filing lane (Director GO 2026-07-09 — "dig once, file twice"):** as findings validate, ao-desk files them into the AO project room (`wiki/matters/oskolkov/`) as curated entries — 20-year timeline, commitments register, document index. POINTER pattern (Aukera-room precedent): room entries reference the canonical `_library/findings/` receipts, never duplicate content. Purpose: the MOVIE shadow-equity negotiation prep reads a stocked room, no re-digging. Sensitive-class items follow the standing desk-only rule.
- Wake mechanics: desk autowake currently suspended (`BRISEN_LAB_AUTOWAKE_DISABLED_SLUGS`). Default: deputy asks lead for a temporary whitelist of the 4 consultant desks for loop duration (Tier-B env flip; restore at loop close). Fallback: batch consultation rounds via manual wakes at Director's normal cadence.

**Wave 3 — Ledger assembly (target 1 day).**
- Deputy assembles the 20-year reciprocity ledger: two directions (Brisen/Director owes AO ↔ AO owes Brisen/Director), each entry tagged moral or commercial, dated, receipted, materiality-weighted. Unverifiable entries marked [assumed] — never silently dropped or silently kept.

**Wave 4 — Synthesis (Fable; target 1 day).**
- Deputy (on Fable) writes the profile from receipted material only: personality read, decision patterns, pressure points, reciprocity balance, negotiation do/don't, MOVIE shadow-equity application section (leverage options INCLUDING the counter-case — where reciprocity framing beats pressure framing; the profile flags, Director chooses per situation).
- Outputs (desk-only): `wiki/matters/oskolkov/curated/ao-psychological-profile-v1.md` + `ao-reciprocity-ledger-v1.md`.

**Wave 5 — Gates + wiring (Fable; target 1–2 days).**
- codex G3 adversarial pass (receipts spot-check, direction-flip audit) → ao-desk validation → **Director ratification of profile + ledger**.
- Card distillate: ao-desk authors non-sensitive card layer → AH publish lane.
- Materiality hook build (B-code sub-brief, deputy authors via /write-brief): ao-desk blocked from producing material advice without attested profile read. **Materiality definition (proposed v1 — Director ratifies at final GO):** (1) money impact ≥ EUR 250K; (2) any equity/security/deal-structure change; (3) any outbound draft to AO or his circle; (4) any negotiation position or strategy call. Routine status/reconciliation ungated.
- Desk process update: option-5 loop (read-before-advise + write-after-contact) written into ao-desk process file.

## Loop mechanics (deputy)

- **Routing (Director 2026-07-09):** cowork-ah1 is App-resident and CANNOT run autonomously/autowake; deputy is terminal-resident and runs the loop unattended. Therefore **deputy sets `dispatched_by: deputy` on every wave dispatch — ALL worker reports route to deputy, not cowork-ah1.** Deputy self-drives waves 0–4 (heartbeats, gap re-fires, loop-until-dry, transitions) without waiting on cowork-ah1.
- Bus topic: `ao-profile/wave-N-*`; every wave transition + blocker posted for the record.
- **Escalation to Director + cowork-ah1 only at:** (a) the final assembled profile + ledger for the ratify decision ("You will see the report at the end, and we decide with you what to do" — Director), or (b) a genuine blocker / kill-criterion. Everything mid-loop is deputy's.
- Re-entry: deputy is wakeable; on rollover, PINNED-style wait-state in deputy memory; loop resumes from last wave checkpoint.

## Kill criteria + budget

- Digger spend cap ~EUR 20/day; program soft cap **EUR 200 total** — breach before Wave-3 completion → pause + Director checkpoint (not silent overrun).
- Kill: methodology fails codex G0 twice → program back to Director. Wave-2 produces zero material findings in first two rounds → profile ships as "thin-corpus" honest version, Director decides continue/stop. Hard deadline checkpoint: day 10.

## Files Modified

Waves 0–4 write NO production code. New vault artifacts only:
- `wiki/research/<date>-counterparty-psych-profile-methodology.md` (researcher, wave 0)
- `wiki/_library/findings/*` hunt findings (librarian/CM pattern, wave 1–2)
- `wiki/matters/oskolkov/curated/ao-psychological-profile-v1.md` + `ao-reciprocity-ledger-v1.md` (desk-only, wave 4)
- AO project room curated entries (timeline / commitments / doc index, pointer-style; ao-desk, wave 2 filing lane)
- ao-desk process file (option-5 loop line, wave 5)
- Card distillate: existing ao-desk content lane files only (wave 5, separate publish)
- Materiality hook = separate wave-5 B-code sub-brief with its own Files Modified; not built under this brief.

## Verification

- Wave 0: codex G0 verdict on methodology posted to bus.
- Wave 1–2: per-taxonomy-cell tally (finding or explicit MISS + coverage note); receipts spot-checkable by id.
- Wave 4: codex G3 adversarial receipts audit (direction-flip check per Lesson #78).
- Wave 5: hook sub-brief carries its own test plan; ao-desk validation + Director ratification on the profile itself.
- Loop health: daily deputy heartbeat on bus; >24h silence escalates to cowork-ah1.

## Done rubric / Acceptance criteria

1. Profile + ledger ratified by Director, desk-only, every claim receipted.
2. Card distillate live via publish lane; sensitive items verifiably absent.
3. Materiality hook enforcing profile-read on ao-desk material advice (tested).
4. Option-5 loop in ao-desk process file.
5. MOVIE shadow-equity section usable as negotiation-prep input.
5b. AO room stocked: validated findings filed pointer-style (timeline, commitments, doc index) — negotiation prep needs zero re-digging.
6. Deputy reverted to Opus 4.8; desk autowake whitelist restored.

## Gate plan

codex G0 (methodology) → per-wave deputy checkpoints → codex G3 (profile) → ao-desk validation → Director ratification. Hook build sub-brief runs standard b-code gate chain.

### Surface contract

N/A — orchestration program; the only UI change (card distillate) travels the existing ao-desk content lane + AH publish (contract rule 13), not this brief.

Harness-V2: blocks above (context contract, task class, done rubric, gate plan); no production code in this brief itself.
