# KBL-B §10 — 10-Signal End-to-End Test Fixture

**Author:** Code Brisen 3
**Task:** `briefs/_tasks/CODE_3_PENDING.md` (2026-04-18 dispatch #6)
**Corpus:** `outputs/kbl_eval_set_20260417_labeled.jsonl` (Director-labeled, ground truth for D1)
**Purpose:** paper fixtures exercising every path through KBL-B's 8-step pipeline, annotated for §10 test-plan authoring.
**Convention:** line numbers refer to 1-indexed lines in the labeled JSONL.

---

## 0. Path-coverage matrix

| Path | Fixtures |
|---|---|
| Layer 0 drops (per-source) | #1 email, #2 meeting |
| Triage routes to inbox (low score) | #3 |
| Thread-resolve continuation | #4, #8 |
| New arc (empty resolved_thread_paths) | #5, #7 |
| Cross-link multi-matter (related_matters non-empty) | #5 |
| Full synthesis path (email) | #4, #8 |
| Full synthesis path (transcript) | #6 (under Phase-2 scope) |
| Layer 2 gate blocks non-hagenauer | #7, #9 (+ #3, #6 under Phase 1) |
| Step 5 cost-cap defer (synthetic) | #10 |

Every required path is covered at least once. #5 carries two paths (new arc + cross-link) — common for real-world signals.

**Phase 1 scope assumption:** `KBL_MATTER_SCOPE_ALLOWED = ["hagenauer-rg7"]`. Signals on other matters Layer-2-gate to inbox. Fixtures #3, #6, #7, #9 are sensitive to this env. #6 is annotated for the Phase-2 transition where additional matters join the allow-list.

---

## 1. Fixtures

### Fixture #1 — NYT family-subscription upsell (Layer 0 email drop)

**Signal:** `email:1993d6b3a1dda25a` (line 6 of labeled.jsonl)
**Paths exercised:** Layer 0 drop (email, sender-blocklist)
**Raw content excerpt:** `"Email Thread: Family subscription: Upgrade & save today. Date: 2025-09-12 Participants: nytimes@e.newyorktimes.com, vallen300@gmail.com..."`

| Step | Expected |
|---|---|
| 0 layer0 | **drop** (rule: `email_sender_blocklist_domains` → sender domain `e.newyorktimes.com`) |
| 1 triage | N/A (pipeline stopped at Step 0) |
| 2 resolve | N/A |
| 3 extract | N/A |
| 4 classify | N/A |
| 5 opus | N/A |
| 6 sonnet | N/A |
| 7 commit | N/A — terminal state `state='dropped_layer0'` |

**Rationale:** Canonical bulk newsletter. Sender domain `e.newyorktimes.com` is on the Layer 0 blocklist. No signal content mentions any matter keyword → topic override does NOT fire. Director labeled as `primary_matter=null`, `vedana=routine`, `triage_pass=False` → confirms drop is safe. Represents ~32% of email volume in the 50-signal corpus that should never reach Step 1.

---

### Fixture #2 — Garbled ASR meeting (Layer 0 meeting drop)

**Signal:** `meeting:01KJB66KQWSFF5TP65QD1QHD8P` (line 30)
**Paths exercised:** Layer 0 drop (meeting, ASR-quality floor)
**Raw content excerpt:** `"Meeting: Feb 25, 08:00 PM ... Duration: 16min Transcript: Unknown: Hello, tax listener. Unknown: Ikbukata. Unknown: Onskazto Pasadena Priglage..."`

| Step | Expected |
|---|---|
| 0 layer0 | **drop** (rule: `meeting_transcript_quality_floor` → max_unknown_speaker_ratio 0.8 exceeded + min_unique_tokens_ratio 0.3 floor breached) |
| 1-7 | N/A |

**Rationale:** 16-min duration passes `meeting_duration_min` (> 3 min). But transcript is 100% `Unknown:` speaker + ASR gibberish. Both Gemma and Qwen missed vedana + matter on this signal in v2 AND v3 evals — this is a **persistent cross-model failure** because the content is genuinely unclassifiable. Dropping at Layer 0 saves 2× LLM calls (Step 1 + Step 3) per pipeline run. High-value rule.

---

### Fixture #3 — Thin WhatsApp reply (Triage inbox route)

**Signal:** `whatsapp:false_447578191477@c.us_3A776C43AE2E3BF063CE` (line 38)
**Paths exercised:** Triage inbox route (low triage_score); also Layer 2 gate under Phase 1
**Raw content excerpt:** `"pvallen@protonmail.com is better, or the brisen email"` (53 chars total)

| Step | Expected |
|---|---|
| 0 layer0 | pass (not a status broadcast, above min content length) |
| 1 triage | primary_matter ≈ `null` OR `steininger`, vedana=`routine`, triage_score ≈ **15-30** (thin content, no actionable signal); triage_confidence ≤ 0.4 |
| 2 resolve | `[]` — below triage threshold, never resolved |
| 3 extract | N/A — **skip-extract-on-inbox-routed optimization recommended** (Step 3 brief §6 question 2) |
| 4 classify | `skip_inbox` (triage_score < 40) |
| 5 opus | skipped (reason: `triage_score < threshold`) |
| 6 sonnet | skipped |
| 7 commit | `wiki/_inbox/20260XYZ_<signal_id_short>.md` (inbox stub) |

**Rationale:** Director labeled `steininger/opportunity` because of operational context (Steininger pre-court preparation conversation). But as an isolated signal, the text alone has no business-classifiable content. Demonstrates the inbox route for thin signals — a substantial % of WhatsApp traffic. Note: even under Phase 2 scope, Step 5 still skips due to low score — inbox is terminal for this class.

---

### Fixture #4 — Re: EH letter on Hagenauer TU financial situation (Continuation + Full synthesis)

**Signal:** `email:19c526f1c6d3f2ee` (line 8)
**Paths exercised:** Thread continuation + Full synthesis (email)
**Raw content excerpt:** `"Email Thread: Re: [EXTERN] your letter 4/2/2026 [EH-AT.FID2087] ... Hi Thomas, If Alric thinks it is important, please do send it. In addition, maybe it is worth saying in the same letter that we have to start works ourselves: KNX, Drywalls..."`

| Step | Expected |
|---|---|
| 0 layer0 | pass (internal brisengroup.com correspondence, slug mention `Hagenauer` triggers topic-override even if sender were blocklisted) |
| 1 triage | primary_matter=`hagenauer-rg7`, related_matters=`[]`, vedana=`threat`, triage_score ≈ **75-85**, triage_confidence ≥ 0.9 |
| 2 resolve | `resolved_thread_paths = ["wiki/hagenauer-rg7/2026-02-04_eh-letter-draft.md"]` — matched via `In-Reply-To` header (Re: chain from original EH-AT.FID2087 letter) |
| 3 extract | `{"people":[{"name":"Alric Ofenheimer","company":"E+H"},{"name":"Arndt Blaschka","company":"E+H"},{"name":"Thomas Leitner","company":"Brisengroup"},{"name":"Niki Götz","company":"E+H"}], "orgs":[{"name":"Hagenauer Austria","type":"contractor"},{"name":"E+H","type":"law_firm"}], "money":[], "dates":[{"date":"2026-02-04","event":"letter sent"},{"date":"2026-02-11","event":"Blaschka reply"}], "references":[{"type":"letter","id":"EH-AT.FID2087"}], "action_items":[{"actor":"Thomas Leitner","action":"confirm with Alric whether to append KNX/drywall self-execution note to next letter"}]}` |
| 4 classify | `full_synthesis` (continuation: `resolved_thread_paths != []`; no related_matters cross-links; primary ∈ Phase 1 allow-list) |
| 5 opus | **fires** — drafts updated wiki entry appending Feb-12 internal discussion to the EH letter-draft arc |
| 6 sonnet | fires — polishes frontmatter, adds `related_matters: []`, source IDs, timestamps |
| 7 commit | `wiki/hagenauer-rg7/2026-02-04_eh-letter-draft.md` (UPDATED, same path as resolved thread) |

**Rationale:** The canonical "continuation" case. `Re:` subject + multi-party internal thread + clear entity set (EH lawyers, Thomas, Vladimir). Step 2 resolves via email headers alone (zero embedding cost). Director labeled `hagenauer-rg7/threat/pass=True`. Both Gemma and Qwen v3 classified correctly (matter + vedana). High-confidence full-synthesis path exercises every step cleanly.

---

### Fixture #5 — Wertheimer SFO approach (New arc + Cross-link)

**Signal:** `whatsapp:false_41798986876@c.us_AC0C466E0FF0784F45075A6534AB75B4` (line 36)
**Paths exercised:** New arc (empty resolved_thread_paths) + Cross-link multi-matter (related_matters non-empty) + Full synthesis under Phase 2
**Raw content excerpt:** `"Hello dimitry. I hope things are going well. I have a meeting with Wertheimer's family office (Chanel) next week. The SFO is currently running by ex JPM bankers... I would like to introduce RG7..."`

| Step | Expected |
|---|---|
| 0 layer0 | pass (WhatsApp DM from known intermediary, not VIP-tier but above content-length floor) |
| 1 triage | primary_matter=`wertheimer`, related_matters=`["hagenauer-rg7"]`, vedana=`opportunity`, triage_score ≈ **80-90**, triage_confidence ≥ 0.85 |
| 2 resolve | `resolved_thread_paths = []` (no existing wertheimer wiki entry — truly new arc); embedding similarity against `wiki/hagenauer-rg7/*` falls below threshold because RG7 is context, not subject |
| 3 extract | `{"people":[{"name":"Dimitry","role":"recipient"}], "orgs":[{"name":"Wertheimer SFO","type":"family_office"},{"name":"Chanel","type":"other"},{"name":"JP Morgan","type":"bank"}], "money":[], "dates":[], "references":[], "action_items":[{"actor":"Dimitry","action":"advise how to introduce RG7 to Wertheimer SFO"}]}` |
| 4 classify | `full_synthesis` + cross-link flag for Step 6 (primary ∈ Phase 1 allow-list? → NO under Phase 1 → Layer 2 gate to inbox; under Phase 2 with wertheimer added → full_synthesis) |
| 5 opus | Phase 1: skipped (inbox). **Phase 2: fires** — drafts new `wiki/wertheimer/` arc entry, includes RG7-cross-reference pointer |
| 6 sonnet | Phase 1: N/A. Phase 2: fires — adds `related_matters: [hagenauer-rg7]` frontmatter + cross-link block to `wiki/hagenauer-rg7/_links.md` |
| 7 commit | Phase 2: `wiki/wertheimer/20260403_sfo-chanel-approach.md` (NEW file) + update to `wiki/hagenauer-rg7/_links.md` |

**Rationale:** Canonical opportunity signal — first mention of wertheimer, mentions RG7 as context. Gemma v3 correctly identified primary=wertheimer (though MATTER_ALIASES scoring bug reported it as miss; real accuracy was correct). Exercises:
- New-arc resolution (embedding-based resolver returns empty)
- Cross-link logic in `related_matters`
- Phase-1-vs-Phase-2 Layer 2 gate divergence

---

### Fixture #6 — Kitzbühel court-hearing prep (Full synthesis transcript, Phase 2)

**Signal:** `meeting:01KES6JZPVPQKXYB3WP9H7NDN2` (line 26)
**Paths exercised:** Full synthesis (transcript); Layer 2 gate under Phase 1
**Raw content excerpt:** `"Meeting: Jan 12, 02:33 PM ... Duration: 56min. Summary: Court Hearing Focus: Aim to challenge Steininger family credibility. Investment Opportunity: Roundshield investor withdrew, offering Dimitri a chance to negotiate a possible CHF 17 million deal. Escrow Deadlock: CHF 800,000 in escrow..."`

| Step | Expected |
|---|---|
| 0 layer0 | pass (56min duration, substantive summary with structured action items, 4000 chars content — well above all quality floors) |
| 1 triage | primary_matter=`kitzbuhel-six-senses`, related_matters=`["steininger"]`, vedana=`opportunity`, triage_score ≈ **80-90**, triage_confidence ≈ 0.7-0.85 (both models v3 flagged this as ambiguous — some confusion with steininger) |
| 2 resolve | Phase 1: N/A (gated). Phase 2: `resolved_thread_paths = ["wiki/kitzbuhel-six-senses/2026-01-05_court-prep.md"]` via Voyage embedding similarity ≥ threshold |
| 3 extract | `{"people":[{"name":"Walter Steininger"},{"name":"Michael Steininger"},{"name":"Dietmar","role":"Wieser's attorney"},{"name":"Eric"},{"name":"Mario"},{"name":"Balash Vallen"}], "orgs":[{"name":"Steininger family","type":"other"},{"name":"Roundshield","type":"investor"},{"name":"Wieser","type":"other"}], "money":[{"amount":17000000,"currency":"CHF","context":"possible Roundshield deal"},{"amount":800000,"currency":"CHF","context":"frozen escrow"}], "dates":[], "references":[], "action_items":[{"actor":"Balash Vallen","action":"send Walter/Michael Steininger emails to legal team for court prep"},{"actor":"Eric","action":"contact Dietmar (Wieser's attorney)"},{"actor":"Mario","action":"review court hearing prep updates"}]}` |
| 4 classify | Phase 1: `skip_inbox` (primary `kitzbuhel-six-senses` ∉ `[hagenauer-rg7]`). Phase 2: `full_synthesis` + cross-link flag for `steininger`. |
| 5 opus | Phase 1: skipped (Layer 2 gate). Phase 2: fires — drafts continuation entry with updated court-prep + Roundshield opportunity note |
| 6 sonnet | Phase 2: fires — adds cross-link to `wiki/steininger/_links.md` |
| 7 commit | Phase 1: `wiki/_inbox/20260112_01KES6JZ-kitzbuhel-court-prep.md` stub. Phase 2: `wiki/kitzbuhel-six-senses/2026-01-05_court-prep.md` UPDATED. |

**Rationale:** The canonical full-synthesis transcript. Rich entity extraction (people, orgs, money, action items). Tests Step 2 transcript resolver (Voyage embeddings) rather than Step 4's metadata-only email path. **Dual-purpose:** under Phase 1 scope this signal demonstrates Layer 2 gate to inbox; under Phase 2 with `kitzbuhel-six-senses` added to allow-list, it demonstrates full-synthesis transcript. The same signal file exercises two distinct pipeline behaviors depending on env — good for regression tests that flip `KBL_MATTER_SCOPE_ALLOWED`.

---

### Fixture #7 — MRCI financial statements (Layer 2 gate, new arc)

**Signal:** `email:19d77f4c155b7b86` (line 23)
**Paths exercised:** Layer 2 gate (primary matter ∉ Phase 1 allow-list); New arc
**Raw content excerpt:** `"Email Thread: Fwd: MRCI - Summen- und Saldenlisten 2024+25 Date: 2026-04-10 Participants: balazs.csepregi@brisengroup.com, cpohanis@brisengroup.com, dvallen@brisengroup.com..."`

| Step | Expected |
|---|---|
| 0 layer0 | pass (internal Brisen correspondence; "MRCI" slug mention triggers topic-override even without the brisengroup.com allowlist) |
| 1 triage | primary_matter=`mrci`, related_matters=`["lilienmat"]` (MRCI is Oskolkov-linked with Lilienmatt restructuring context per registry), vedana=`routine` (routine financial fwd — Director labeled opportunity but the empirical Gemma/Qwen read it as threat/routine — this is a known-ambiguous signal; pipeline uses whatever Step 1 produces), triage_score ≈ **45-60**, triage_confidence ≈ 0.75 |
| 2 resolve | `resolved_thread_paths = []` — first mention of MRCI financials in vault; `Fwd:` chain is internal and doesn't match any prior MRCI wiki entry |
| 3 extract | `{"people":[{"name":"Balazs Csepregi","company":"Brisengroup"},{"name":"Siegfried Brandner","company":"Brisengroup"},{"name":"Caroline Schreiner","company":"Brisengroup","role":"EA"},{"name":"Constantinos Pohanis","company":"Brisengroup"}], "orgs":[{"name":"MRC&I GmbH","type":"other"}], "money":[], "dates":[{"date":"2026-04-09","event":"Saldenliste forwarded"}], "references":[], "action_items":[]}` |
| 4 classify | `skip_inbox` (`mrci` ∉ `KBL_MATTER_SCOPE_ALLOWED=[hagenauer-rg7]`) → route to `wiki/_inbox/` |
| 5 opus | skipped (Layer 2 gate) |
| 6 sonnet | skipped |
| 7 commit | `wiki/_inbox/20260410_19d77f4c-mrci-saldenliste-fwd.md` (inbox stub, stores `primary_matter=mrci` metadata so Phase 2 migration can pick it up) |

**Rationale:** Clean Layer 2 gate demonstration. Matter is valid but out-of-Phase-1-scope. Extraction still runs (unlike #3) because the signal passes triage threshold — but Step 5/6 skip. Stub in `wiki/_inbox/` preserves metadata for future Phase 2 promotion. Tests the `skip_inbox` decision path distinct from the triage-threshold inbox path (#3).

---

### Fixture #8 — Hagenauer MO Nemetschke reply (Continuation + Full synthesis, second arc)

**Signal:** `email:19d11ad2d0a1eb26` (line 18)
**Paths exercised:** Thread continuation + Full synthesis (email, different arc from #4)
**Raw content excerpt:** `"Email Thread: AW: [EXTERN] Re: Hagenauer 01: Mandarin Oriental [EH-AT.FID2087] Date: 2026-03-21 ... From a professional stand point we need to answer the e-mail from Mr. Nemetschke..."`

| Step | Expected |
|---|---|
| 0 layer0 | pass (internal EH correspondence with Brisen; Hagenauer + EH-AT.FID2087 slug mention; all senders brisengroup.com or eh.at) |
| 1 triage | primary_matter=`hagenauer-rg7`, related_matters=`["mo-vie"]` (subject explicitly ties to Mandarin Oriental context — but Director-labeled related_matters only `hagenauer-rg7`; model MAY cross-link MO under disambiguation rules), vedana=`threat`, triage_score ≈ **85-95** (legal response to media allegations → high urgency), confidence ≥ 0.9 |
| 2 resolve | `resolved_thread_paths = ["wiki/hagenauer-rg7/2026-03-18_nemetschke-media-demand.md"]` via `In-Reply-To` header referencing Mar-18 and Mar-21 13:10 emails |
| 3 extract | `{"people":[{"name":"Alric Ofenheimer","company":"E+H"},{"name":"Nemetschke","role":"counsel for counterparty"},{"name":"Edita Vallen","company":"Brisengroup"},{"name":"Vladimir Moravcik","company":"Brisengroup"}], "orgs":[{"name":"Brisen Development GmbH","type":"other"},{"name":"Hagenauer Austria GmbH & Co KG","type":"contractor"},{"name":"E+H","type":"law_firm"}], "money":[], "dates":[{"date":"2026-03-18","event":"Nemetschke email 11:55"},{"date":"2026-03-21","event":"Nemetschke email 13:10"}], "references":[{"type":"letter","id":"EH-AT.FID2087"},{"type":"contract","id":"TUV"}], "action_items":[{"actor":"Brisen","action":"approve DeepL-translated response to Nemetschke (reject de-facto group assertion, reserve legal action re public statements)"}]}` |
| 4 classify | `full_synthesis` + cross-link (related_matters=mo-vie) — both on Phase 1 allow-list mismatch (mo-vie ∉ allowed) — cross-link fires to `wiki/mo-vie/_links.md` EVEN IF mo-vie is out-of-scope, because cross-links are lightweight pointer writes (not full synthesis). Primary matter IS in allow-list → full_synthesis proceeds. |
| 5 opus | fires — drafts updated wiki entry appending Alric's response to Nemetschke arc |
| 6 sonnet | fires — refines frontmatter, writes cross-link stub to `wiki/mo-vie/_links.md` |
| 7 commit | `wiki/hagenauer-rg7/2026-03-18_nemetschke-media-demand.md` UPDATED + `wiki/mo-vie/_links.md` cross-link pointer appended |

**Rationale:** Second full-synthesis+continuation signal, different Hagenauer arc (Nemetschke media dispute vs. #4's EH letter-draft arc). Tests that the pipeline handles MULTIPLE parallel Hagenauer threads correctly — wiki structure under `wiki/hagenauer-rg7/` has per-topic files, not one monolithic entry. Also exercises the cross-link-without-full-synthesis edge case where `related_matters` includes an out-of-scope matter (mo-vie under Phase 1) — Step 6 writes a lightweight link stub but Step 5 doesn't re-synthesize the mo-vie arc.

---

### Fixture #9 — AO bond coupon meeting (Layer 2 gate, transcript)

**Signal:** `meeting:01KKE46362DSS8TEBZ4WY7HZ51` (line 34)
**Paths exercised:** Layer 2 gate (non-hagenauer); transcript path through Steps 0-4
**Raw content excerpt:** `"Meeting: Mar 11, 10:38 AM ... Duration: 20min. Summary: - Overdue Bond Payment: Team is handling an overdue bond coupon payment of €320,000 due mid-February with a cash flow plan. - Loan Agreements for Compliance: €2.5 million transferred as shareholder loan..."`

| Step | Expected |
|---|---|
| 0 layer0 | pass (20-min meeting, structured summary with action items, multi-topic content, well above quality floor) |
| 1 triage | primary_matter=`ao` (signal discusses Andrew/Oskolkov LCG loan structuring), related_matters=`[]` (model MAY output related to MRCI / Lilienmat since context overlaps), vedana=`threat` (overdue payment, KYC compliance urgency), triage_score ≈ **70-85**, confidence ≈ 0.7-0.85 |
| 2 resolve | N/A — Layer 2 gate hits before Step 2 wastes an embedding call? **Question for implementation:** does Layer 2 gate happen in Step 4 (as specified) or short-circuit at Step 2 to save cost? Current §4.5 says Step 4, which means Step 2 + Step 3 both run for gated signals. Open question flagged below. |
| 3 extract | `{"people":[{"name":"Andrew","role":"principal"},{"name":"Ed"},{"name":"Willie"},{"name":"Konstantinos"},{"name":"Patrick"}], "orgs":[{"name":"LCG","type":"other"},{"name":"Dilio","type":"other"},{"name":"Brazen Ventures","type":"other"},{"name":"ILU","type":"other"}], "money":[{"amount":320000,"currency":"EUR","context":"overdue bond coupon, due mid-February"},{"amount":2500000,"currency":"EUR","context":"shareholder loan for compliance"},{"amount":500000,"currency":"EUR","context":"personal expense loan via LCG"}], "dates":[{"date":"2026-02-15","event":"approximate bond coupon due date — 'mid-February'; ISO rule applied conservatively"}], "references":[], "action_items":[{"actor":"team","action":"prepare loan agreements LCG↔Dilio and LCG↔Brazen Ventures"},{"actor":"Konstantinos","action":"engage Patrick to resolve KYC requirements"}]}` |
| 4 classify | `skip_inbox` (`ao` ∉ Phase 1 allow-list) — but primary matter is preserved for Phase 2 promotion |
| 5 opus | skipped (Layer 2 gate) |
| 6 sonnet | skipped |
| 7 commit | `wiki/_inbox/20260311_01KKE463-ao-bond-coupon-stub.md` with metadata `primary_matter=ao, triage_score=79, extracted_entities=<above>` — all three fields are Phase 2 migration-ready |

**Rationale:** Layer 2 gate on a transcript source (#7 was email). Demonstrates that `skip_inbox` behavior is source-agnostic. Rich entity extraction still runs — `extracted_entities` is preserved in the inbox stub so that a later Phase 2 `wiki/_inbox/` drain job can full-synthesize without re-extraction. This tests the "inbox-as-holding-pen" invariant.

---

### Fixture #10 — SYNTHETIC: Step 5 cost-cap defer (hypothetical)

**Signal:** Synthetic, based on Fixture #4 behavior + high-cost-day scenario
**Paths exercised:** Step 5 cost-cap defer — normal pipeline path, but Step 5 cost-ledger check blocks firing
**Scenario:** A day in Phase 1 where 47 high-confidence hagenauer-rg7 signals arrive. After 45 Opus Step 5 calls, the daily cost ledger hits `KBL_DAILY_OPUS_COST_CAP_USD` (example default: $15). Signals 46 and 47 must defer gracefully.

| Step | Expected |
|---|---|
| 0 layer0 | pass (same as #4 — valid Hagenauer email) |
| 1 triage | primary_matter=`hagenauer-rg7`, vedana=`threat`, triage_score ≈ 80, confidence ≥ 0.9 (clean classification) |
| 2 resolve | `resolved_thread_paths = ["wiki/hagenauer-rg7/<arc>.md"]` (or new arc — either works) |
| 3 extract | normal extraction, ~1 min Gemma latency |
| 4 classify | `full_synthesis` — decision at this step is unchanged; cost-cap is checked INSIDE Step 5, not in Step 4 |
| 5 opus | **deferred** — Step 5 entry-point checks `kbl_cost_ledger` daily Opus total for today. Today's total ≥ cap. Instead of firing, signal advances to `state='step5_deferred_cost_cap'`, `started_at` retained. Signal is picked up by next-day's cost-reset run. Log entry: `component='step5', level='INFO', message='cost cap hit: opus deferred'`. |
| 6 sonnet | deferred (blocked by Step 5 incomplete) |
| 7 commit | deferred — no wiki write today. Tomorrow's pipeline pass will complete Steps 5-7. |

**Rationale:** The only "unhappy-path" fixture in the set. Tests:
- Cost-cap observability (`kbl_cost_ledger` aggregate query in Step 5 entry-point)
- Defer vs fail semantics — deferred signals aren't "broken", they're paused. State transitions forward-only per §4.1 invariant — `step5_deferred_cost_cap` → `step5_running` on resume, not backward.
- Idempotent resume — if Step 5 had partially run (draft started) and then deferred, the resume must discard the partial and restart cleanly at temperature 0 (D1 sampling) so cached prompt still applies.

**Implementation note for §10 pytest:** this fixture is exercised by artificially pre-seeding `kbl_cost_ledger` with rows summing to ≥ cap, then running the pipeline. No actual Opus call needed — the defer check happens before the API call.

---

## 2. What the §10 pytest harness needs

To make these 10 fixtures runnable end-to-end, §10 implementation needs:

1. **Labeled-set loader fixture** — pytest can load by `(source, signal_id)` tuple into a `SignalRow` object matching `signal_queue` schema.
2. **Mock Ollama client** — replay recorded v3 eval outputs (from `outputs/kbl_eval_results_20260418.json`) for triage. Deterministic (temp=0, seed=42) means mocking is safe.
3. **Mock Voyage embedding client** — two response shapes: (a) match `resolved_thread_paths` for continuation cases, (b) return no-match for new-arc cases. Cached per fixture.
4. **Mock Opus + Sonnet clients** — don't need semantic accuracy; just need to return valid markdown responses with frontmatter. 5-10-line canned responses fine.
5. **`kbl_cost_ledger` pre-seeding helper** — for Fixture #10.
6. **`KBL_MATTER_SCOPE_ALLOWED` env fixture** — parameterized so the same #6 fixture runs twice (Phase 1 → gate, Phase 2 → synthesize).

---

## 3. Fixture size + budget

| Category | Count | Notes |
|---|---|---|
| Real signals from labeled set | 9 | #1-#9 |
| Synthetic scenarios | 1 | #10 (Step 5 cost-cap defer) |
| Email source | 4 | #1, #4, #7, #8 |
| WhatsApp source | 2 | #3, #5 |
| Meeting source | 3 | #2, #6, #9 |
| Scan source | 0 | Deliberately none — scan NEVER drops at Layer 0 per §2 ratified; tested via a separate dedicated test case, not in end-to-end fixture |

Source distribution roughly matches the 50-signal corpus (25 email / 15 whatsapp / 10 meeting) — fixture is representative.

---

## 4. Known-ambiguous fixtures (flagged for test assertions)

Per v2 + v3 eval retrospectives, some signals are genuinely ambiguous and cannot be asserted with tight equality:

| Fixture | Ambiguity | Recommended assertion |
|---|---|---|
| #3 | Director labeled `steininger/opportunity`; models variably label null/steininger/routine | Assert `triage_score < 40` AND `classify decision in {skip_inbox, stub_only}`; do NOT assert exact primary_matter |
| #6 | Director labeled `opportunity`; models variably `opportunity` or `threat`. Persistent ambiguity | Assert `primary_matter == kitzbuhel-six-senses`, `vedana in {opportunity, threat}`, `triage_score >= 60`; don't assert exact vedana |
| #7 | Director labeled `opportunity`; models labeled `threat`/`routine`. Director was reading "potential restructuring opportunity" in financial data; models saw routine forward | Assert `primary_matter == mrci`; `vedana in {opportunity, threat, routine}`; let Phase 1 data tell us which is right |

Use tolerance assertions on ambiguous fields. Tight equality only on deterministic paths (Layer 0 drops, Step 4 classify decisions, Step 7 commit paths).

---

## 5. Open questions — RESOLVED by AI Head 2026-04-18

| OQ | Question | Resolution |
|---|---|---|
| OQ1 | Step 2 + Step 3 run for Layer-2-gated signals? | **Resolved: gate stays at Step 4** (per §4.5). Fixtures #7 and #9 are correct as-is — Step 2 + Step 3 run, Step 4 routes to inbox with rich metadata for Phase 2 promotion readiness. |
| OQ2 | Wiki entry naming convention | **Resolved: `wiki/<matter>/YYYYMMDD_<short-title>.md` is canonical.** Fixtures stand. |
| OQ3 | Fixture #10 (Step 5 cost-cap defer) in §10 pytest? | **Resolved: yes, include in §10 end-to-end pytest.** Mock `kbl_cost_ledger` pre-seeding helper required (already specified in §2 of this draft). |
| OQ4 | (was bundled into OQ3) | Same resolution as OQ3. |
| OQ5 | Scan-source fixture absence from the 10? | Standing recommendation: separate dedicated test, not in end-to-end. Awaiting AI Head confirmation; not blocking. |

## 6. Coverage gap — awaits Director decision

**No Hagenauer transcript exists in the 50-signal eval corpus.** Fixture #6 (Kitzbühel) is the only full-synthesis-transcript candidate, hence the Phase-2-scope workaround. Director must decide whether to:
- (a) Add a synthetic Hagenauer transcript to the labeled set for Phase 1 testing, OR
- (b) Accept that Phase 1 has no E2E transcript-full-synthesis test (only the Phase-2 alternate-scope path), OR
- (c) Capture a real Hagenauer meeting transcript as a future eval-corpus addition.

**No B3 action pending until Director rules.**

## 7. CHANDA compliance status (added 2026-04-18 post-CHANDA-adoption)

These fixtures **demonstrate mechanical pipeline compliance only** — they do NOT yet verify the Learning Loop legs (Compounding / Capture / Flow-forward, per CHANDA §2). Specifically:

- **Leg 1 (Compounding):** No fixture asserts that Step 5 Opus reads `wiki/<matter>/*.md` Gold before drafting.
- **Leg 2 (Capture):** No fixture exercises a Director action that triggers a feedback-ledger write.
- **Leg 3 (Flow-forward):** No fixture asserts Step 1 reads `hot.md` + feedback ledger.

**Awaits:** AI Head dispatch to upgrade fixtures with a "Loop Compliance" row per card. See `briefs/_reports/B3_chanda_ack_20260418.md` §3 for full audit.

---

*Drafted 2026-04-18 by B3 for AI Head §10 assembly. No Python executed, no evals run — paper fixtures only. Updated 2026-04-18 with AI Head OQ resolutions + CHANDA compliance status. Ready for copy-paste into §10 and for Code follow-up dispatch to wire into pytest.*
