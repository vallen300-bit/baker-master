# Hagenauer Transcript Candidates — Fireflies Search Results

**Author:** Code Brisen 3
**Task:** `briefs/_tasks/CODE_3_PENDING.md` Task 3 (2026-04-18 dispatch, commit `3c78f8c`)
**Search window:** 2026-01-18 → 2026-04-18 (90-day Fireflies retention window)
**Search date:** 2026-04-18

---

## TL;DR

**Zero strict Hagenauer transcripts in Fireflies within the 90-day window.** Searched 11 Hagenauer-specific terms (Hagenauer, Schlussabrechnung, RG7, Baden, Ofenheimer, Leitner, Moravcik, Riemergasse, Hassa, Mandarin, insolvency, Vienna, Brisen). All returned 0 hits except `Leitner` (1 hit, already in labeled corpus) and `Baden` (2 hits, both Baden-Baden Germany NOT Baden bei Wien — wrong project).

**3 Cupial-labeled meetings discuss Hagenauer-RG7 contract execution substantively.** They're classified `cupial` because the buyer-dispute angle is primary, but the transcript content is Hagenauer-adjacent (defect lists, Haginau/Hagenauer subcontractor coordination, Christine Sähn — Hagenauer PM — communication, contract retention amounts).

**Recommendation: invoke fallback (a) per pre-approval.** §10 final spec accepts the gap; Fixture #6 (Kitzbühel) stays the only full-synthesis-transcript candidate, exercised under Phase-2 scope. Optional alternative for Director: re-label one of the Cupial-adjacent meetings as `hagenauer-rg7` if the content shape matches Phase-1-scope intent better than the buyer-dispute classification.

---

## Search log (full audit trail)

| Term | Results | Notes |
|---|---|---|
| `Hagenauer` | 0 | Primary target term |
| `Schlussabrechnung` | 0 | German for "final account" |
| `RG7` | 0 | Project code |
| `Ofenheimer` | 0 | E+H lawyer (Brisen's counsel) |
| `Leitner` | 1 | Single hit = `01KFJGBHN7PFVQKEV1MSXVYMB1` already in labeled corpus as `cupial` (line 28) |
| `Moravcik` | 0 | Brisen project lead on-site |
| `Baden` | 2 | Both Baden-Baden Germany (Lilienmat / FX Meyer / MRCI context) — wrong Baden, not Baden bei Wien |
| `Riemergasse` | 0 | RG7 project address |
| `Hassa` | 0 | Cupials' lawyer |
| `Mandarin` | 0 | MO Vienna context |
| `insolvency` | 0 | Hagenauer Mar 2026 insolvency |
| `Vienna` | 0 | Surprising — broad term, no hits in 90 days |
| `Brisen` | 0 | Surprising — broadest Brisen-context term, no hits |
| `Cupial` | 3 | All Cupial-buyer-dispute meetings; 2 already in labeled corpus |

**Surprising finding:** `Vienna` and `Brisen` returning zero hits suggests Fireflies coverage of Brisen meetings in the 90-day window is sparse OR the meetings transcripts don't surface those proper-noun keywords (could be rendered as e.g. "the project" rather than "RG7"). Worth confirming with Director.

---

## Candidate transcripts (ranked by Phase-1 relevance)

### Candidate #1 — `01KFB791FKNTWNEGT3JCFPGSC8` (NOT in labeled corpus)

**Title:** Release Escrow Cupial, EV + VM Jan 19, 02:31 PM
**Date:** 2026-01-19 13:31 UTC
**Duration:** 7 min
**Participants:** vallen300@gmail.com (organizer)
**Word count:** estimated ~600-1000 (short meeting)
**150-char summary:** "Pause apartment handovers until defect reviews complete; €20M contract with 3% retention being held; Haagenauer subcontractor payment coordination ongoing"
**Hagenauer-RG7 relevance:** **MEDIUM** — short meeting, discusses subcontractor payment coordination with Haagenauer, defect dispute with technical team, retention insurance from €20M Hagenauer contract. Cupial-side framing dominates, but RG7 contract mechanics are substantively present.
**Director ratification path:** if Director sees this as more `hagenauer-rg7` than `cupial` (focus on contract+retention, not buyer dispute), this becomes the Phase-1 full-synthesis transcript candidate. Otherwise drops to "tangential — leave as is."

### Candidate #2 — `01KFBBFT92YTXDV6YPDTRCKTVA` (already in labeled corpus, line 27)

**Title:** Escrow Release Cupial, zoom with Arndt Jan 19, 03:45 PM
**Date:** 2026-01-19 14:45 UTC
**Duration:** 57 min
**Participants:** vallen300@gmail.com
**150-char summary:** "Handover suspended — €1.5M defect-claim dispute exceeds 3% retention. Michael Hassa refuses key release. Coordination with Hagenauer for final invoices + escrow"
**Hagenauer-RG7 relevance:** **MEDIUM-HIGH** — substantively discusses Hagenauer contract mechanics (final invoices, payment confirmations from Hagenauer for special requests, snagging list from Hagenauer, escrow conditions tied to Hagenauer invoices). Already labeled `cupial` per Cupial-buyer-dispute primary focus.
**Director ratification path:** in labeled corpus as `cupial`. Re-label as `hagenauer-rg7` would shift the matter assignment — Director's call. Note: changing labels post-D1 ratification is a separate decision.

### Candidate #3 — `01KFJGBHN7PFVQKEV1MSXVYMB1` (already in labeled corpus, line 28)

**Title:** Escrow Release Cupial, DV,EV,T.Leitner Jan 22, 10:25 AM
**Date:** 2026-01-22 09:25 UTC
**Duration:** 11 min
**Participants:** vallen300@gmail.com
**150-char summary:** "€500K escrow unlock plan; €150K mgmt fee proposal to Christine [Sähn — Hagenauer]; Hackenau documentation handling + 14-day warning letter; budget €17.3M"
**Hagenauer-RG7 relevance:** **MEDIUM-HIGH** — coordination with Christine Sähn (Hagenauer PM) is the operational center; €17.3M budget reference; warning-letter-to-Hagenauer plan. Already labeled `cupial`.
**Director ratification path:** same as #2.

---

## What this means for §10 fixture coverage

Per task brief Task 3 fallback: *"If 0 candidates found: report 'no Hagenauer transcripts in Fireflies window' → Director rules option (a) per pre-approval, fixture #6 stays Phase-2-parameterized, §10 final spec accepts the gap."*

**Strict interpretation:** Zero `hagenauer-rg7`-labeled transcripts in Fireflies window. Invoke fallback (a). Fixture #6 (Kitzbühel) stays the full-synthesis-transcript representative under Phase-2-parameterized testing.

**Soft interpretation (offered, not pushed):** If Director re-classifies Candidate #1 (`01KFB791FKNTWNEGT3JCFPGSC8`) as `hagenauer-rg7` instead of `cupial`, it becomes a Phase-1-scope full-synthesis-transcript candidate. The transcript discusses RG7 contract retention, Haagenauer subcontractor payments, and defect-rectification mechanics — all Phase-1-scope material. The `cupial` framing is about WHICH party is in dispute (the buyers, Cupials), but the SUBSTANCE is Hagenauer-RG7 contract execution. Director may legitimately read this as `primary_matter=hagenauer-rg7, related_matters=[cupial]` rather than `primary=cupial, related=[hagenauer-rg7]`. Either is defensible.

**Decision belongs to Director — out of B3 scope per task guardrails ("Labeling yourself … out").**

---

## Confidence flags on the search itself

**Why the broad terms returned zero is worth Director attention:**

1. **`Vienna` returned 0** in a 90-day window for Brisen's Vienna-based asset operator. Either Fireflies is mostly capturing non-Vienna meetings, or the Vienna-context meetings reference projects by code name (RG7, MO) and never say "Vienna" verbatim.
2. **`Brisen` returned 0.** Brisen team meetings would presumably mention "Brisen" somewhere in 90 days. Either the meetings are pre-Jan-18, or they're using internal labels ("Brisengroup", "the team") that the keyword search doesn't normalize. **Recommend Director confirm Fireflies retention is actually 90 days for the Brisen workspace** — if it's 30 days (some plans cap shorter), that explains the empty results.
3. **The 6 Cupial/Baden hits we DID get are all from Jan 19-22, 2026.** Suggests Fireflies for vallen300@gmail.com is sparsely populated in Feb-Apr 2026 — fewer recorded meetings, not zero, but few enough that a keyword window misses most. Worth Director knowing.

If retention or coverage is the real issue (not absence of Hagenauer meetings), fallback (c) — captured-meetings-going-forward — becomes more valuable than fallback (a). But that's Director's call.

---

## Dispatch back

> B3 Hagenauer transcript search done — candidates at `briefs/_drafts/HAGENAUER_TRANSCRIPT_CANDIDATES.md`, commit `<SHA>`. **Zero strict Hagenauer transcripts found in 90-day window.** 3 Cupial-labeled meetings are tangentially Hagenauer-RG7-content-relevant; Candidate #1 (`01KFB791FKNTWNEGT3JCFPGSC8`, NOT in labeled corpus) is the strongest re-label candidate IF Director reads contract-execution focus as primary over buyer-dispute. Recommend invoking fallback (a). Coverage-flag noted: `Vienna` + `Brisen` returning 0 in a 90-day window suggests Fireflies coverage gap, not absence of Hagenauer meetings — worth Director attention separately.

---

*Drafted 2026-04-18 by B3. Search ran via Fireflies MCP. No labeling done (Director-owned per D1 ratification). No corpus modifications (separate ticket if Director ratifies any candidate).*
