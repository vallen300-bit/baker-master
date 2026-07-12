# BRIEF: EVIDENCE_LEDGER_V2 — researcher method.md §8/§2/§9 + research-fan-out counter-evidence lane

## Context

Codex external critique of the researcher's evidence/citation discipline returned **5 validated-new** items (beyond what method.md §8 already enforces). They harden against three real scar classes: (a) **citation laundering** — two quotes tracing to one underlying filing counted as two "independent" HIGH sources; (b) the **Feb-2013-STR-as-2026** class — a stale *event/data* date hidden behind a fresh *publication* date; (c) **unadjudicated conflicts** — today the pipeline only *flags* cross-source disagreement (§6 + fan-out "surface, don't average"), it gives no ranking to *resolve* it. Plus two smaller gaps: missing archive/registry channels in §2, and no epistemic labelling in the report shapes.

Director-approved via lead. Authored by b1 (reassigned from cowork-ah1; b1 has method.md fresh from `RESEARCHER_CHANNEL_RECONCILE_YOUTUBE_1`). **This brief goes to lead for review BEFORE any build.**

## Estimated time: ~4h (WP1 ~2.5h, WP2 ~1.5h)
## Complexity: Medium
## Prerequisites: none. WP1 and WP2 are independent → **two separate PRs**.

## Baker Agent Vault Rails
Relevant rails: `skills-and-playbooks` (research-fan-out + researcher-verify-citations skills), `standing-contract` (researcher method.md is the standing HOW doc), `verification-surfaces` (§4.1/§4.2/§6.5/§6.6 ship-gates — the new fields must not break them).
Ignore: `build-command-center`, `loop-runner`, `bus-and-lanes`, `memory-and-lessons` (no code, no bus schema, no DB touched).

## Target repo + isolation
**baker-vault only** (docs/skills — NO baker-master code, NO DB, NO migrations). All edits via an **isolated git worktree or clone off origin/main** per `_ops/processes/vault-writer-worktree-isolation.md` — never the shared `~/baker-vault` checkout. **Re-read each target section against origin/main at build time** — the shared checkout was found stale during CHANNEL_RECONCILE (cage + method.md both behind origin/main). Line numbers below are origin/main @`d0098d6`-era + the CHANNEL_RECONCILE reconcile (PR #182); treat them as anchors, re-grep before editing.

## Engineering Craft Gates (brief-level)
- **Diagnose:** N/A — not a bug; additive discipline upgrade from an external critique.
- **Prototype:** N/A — the artifacts are prose contracts (slot template, router table), not an uncertain UI/state model. Field shapes are specified below; no throwaway needed.
- **TDD / verification:** **applies (light).** The load-bearing seam is the **ship-gate validators** (`scripts/validate_continuation.sh` + the verify-citations skill's slot parser). New §8 fields must NOT break slot parsing or the `INCOMPLETE`/`CONTINUATION-MISSING` gates. Verification = (1) a hand-authored sample report using the new slot passes the existing gates unchanged; (2) the verify-citations skill still extracts URL/date/byline from the extended slot. No live web fetch required to prove the schema change.

---

## WORK PACKAGE 1 (PR #1): Evidence-ledger fields + adjudication hierarchy + registry channels + epistemic labels

Target file: `_ops/agents/researcher/method.md`.

### WP1.1 — Independence dedup (kills citation laundering)

**Problem.** §8 Confidence rule (line ~224 post-reconcile): *"HIGH confidence requires ≥2 sources at primary or secondary tier with matching publication dates."* Two articles both quoting the **same** underlying filing/press-release satisfy this while being **one** real source.

**Current state.** §8 slot template (the fenced block at ~line 205-214) has: Claim / URL / Pub date / Byline / Accessed / Tier / Confidence / [Optional] Quote.

**Change.**
1. Add two fields to the §8 slot block, after `Tier:`:
   ```
   Underlying source: <the ORIGINAL document this traces to — filing / release / dataset / person; "same as URL" if this IS the primary>
   Independent?: <yes | no — no if it re-reports another cited slot's Underlying source>
   ```
2. Amend the §8 **Confidence rule** HIGH line to (verbatim replacement):
   > **HIGH** confidence requires ≥2 sources at `primary` or `secondary` tier that are **independent** (distinct `Underlying source` — two slots tracing to the same filing/release/dataset count as **one**), with matching event/data dates (see §8 date rule).
3. Add one line under the Confidence rule: *"Independence is judged on `Underlying source`, not on URL or outlet — three outlets reprinting one Reuters wire = one source."*

### WP1.2 — Event/data date distinct from publication date (Feb-2013-STR scar)

**Change.** In the §8 slot block, replace the single `Pub date:` line with two:
```
Pub date: <YYYY-MM-DD of the article/page — or "not visible">
Event/data date: <YYYY-MM-DD the underlying fact/statistic/event is FROM — may equal Pub date; "same as pub" if so>
```
Add under §8 → Snippet-vs-page rule (or a new one-liner): *"A 2026 article citing a Feb-2013 statistic has Pub date 2026 but Event/data date 2013 — the LOW-confidence 18-month-staleness test (Confidence rule) runs against **Event/data date**, never Pub date."*
Amend the LOW rule line accordingly (it currently keys staleness off "primary source date"; make it explicitly `Event/data date`).

### WP1.3 — Exact location field

**Change.** Add to the §8 slot block, after `Quote:`:
```
Location: <page / paragraph / section / timestamp — where in the source the claim sits; "n/a" for a short page>
```
One-liner under §8: *"Location makes a claim re-checkable without re-reading the whole source; mandatory for filings, PDFs, standards, and >2000-word pages."*

### WP1.4 — Conflict-adjudication hierarchy at Step 7

**Problem.** §6 failure modes + fan-out synthesizer "surface, don't average" **flag** conflicts but give no ranking to **resolve** them.

**Current state.** method.md §4 HOW table row 7 = "Synthesis + file write". The fan-out synthesizer (research-fan-out §6) surfaces disagreements in a "Flagged disagreements" subsection.

**Change.** Add a new subsection `### 4.4 Conflict-adjudication hierarchy (Step 7)` after §4.3, with this ladder (highest wins; verbatim):
> When two sources conflict on a fact, adjudicate by rank, highest wins, and **state the rank you applied**:
> 1. **Primary document** (filing, signed contract, official statistics-agency release, regulator publication, court submission).
> 2. **Authoritative structured data** (EDGAR/Handelsregister/patent registry, official dataset, exchange feed).
> 3. **Independent secondary** (bylined journalist / named analyst with a verifiable date, tracing to a *distinct* underlying source).
> 4. **Expert commentary** (attributed practitioner opinion, conference talk, named-person interview).
> 5. **Social** (X/LinkedIn posts, verified account).
> 6. **Unattributed aggregation** (search snippet, AI-summary, un-bylined aggregator) — never resolves a conflict; only raises a question.
>
> Adjudication does **not** replace "surface, don't average" — you still show BOTH sides in the Flagged-disagreements block; the hierarchy tells the reader which side the report **leans** and why. If the two conflicting sources sit at the **same** rank, do NOT pick — surface unresolved and drop the dependent claim to MEDIUM/LOW.

Cross-reference this from §6 (conflict row) and add a one-line pointer in research-fan-out §6 synthesizer output ("rank per method.md §4.4"). **The fan-out skill pointer is a one-line add in WP1 (same doctrine); the router lane is WP2.**

### WP1.5 — §2 WHERE: archive + structured-registry rows

**Change.** Add two rows to the §2 WHERE table (keep the Reach column from PR #182):

| Channel | Tool | Reach | Notes |
|---|---|---|---|
| Web archives | `WebFetch` (web.archive.org/…) | ✅ (domain-gated) | Wayback snapshots for dead links, pre-edit versions, "what did this page say on date X". Cite the snapshot URL + the snapshot timestamp as Event/data date. |
| Structured registries | `WebFetch` — EDGAR (sec.gov), Handelsregister (handelsregister.de / unternehmensregister.de), patents (patents.google.com, EPO Espacenet) | ✅ (domain-gated) | Rank-2 authoritative structured data (§4.4). Primary-tier for corporate filings, officers, ownership, IP. `gh`/`curl` remain cage-blocked — WebFetch only. |

(Both are WebFetch → domain-gated: a new domain prompts for approval per settings.local.json; note that in the row so the builder/researcher expects the prompt.)

### WP1.6 — Epistemic labels in both report shapes

**Change.** In §9, add to BOTH Short Shape and Full Shape a one-line instruction: each finding/claim carries an epistemic label — **`[fact]`** (verifiable, cited) / **`[reported-claim]`** (a source asserts it; not independently confirmed) / **`[inference]`** (the researcher's own deduction from cited facts) / **`[unresolved]`** (conflicting or uncorroborated). Place the label at the start of the finding line, before the citation slot. Add to §8 Empty-slot rule cross-ref: `[inference]` and `[unresolved]` may ship without a full slot but MUST be labelled as such — never dressed as `[fact]`.

### WP1 verification
- Hand-author one sample Short-Shape and one Full-Shape finding using the extended §8 slot; confirm `scripts/validate_continuation.sh` (if it parses slots) and the verify-citations slot extractor still read URL/Pub date/Byline without error.
- Grep method.md for every prior reference to "≥2 sources" / "Pub date" / "primary source date" and confirm none now contradict the new independence + event-date rules (internal consistency — the #1 doc-drift trap).

---

## WORK PACKAGE 2 (PR #2): Counter-evidence lane in research-fan-out router

Target file: `_ops/skills/research-fan-out/SKILL.md` (+ one method.md §10 pointer).

**Problem.** Step 6.6 (adversarial refutation) refutes findings **after** the draft exists — reactive. There is no deliberate **disconfirming search BEFORE drafting** — the fan-out picks N confirming channels and never tasks a channel to actively hunt evidence the thesis is *wrong*. Confirmation bias enters at search time, before 6.6 can catch it.

**Current state.** research-fan-out §4 router picks a default trio / escalation-5 of **confirming** channels per research-type. §5 dispatches them in parallel; §6 synthesizes; Step 6.5/6.6 verify/refute after.

**Change.**
1. Add `### 4a. Counter-evidence lane (disconfirming search — BEFORE synthesis)` to the skill:
   - For any **deep-dive / FULL-shape** fan-out (research-types 1/2/3/4-excluded/5/6/7/8/10 when run as a deep dive), add **one dedicated counter-evidence sub-agent** to the dispatch (N→N+1), prompted to **search for evidence the brief's leading hypothesis is false/overstated/outdated** — NOT to summarize the topic. Its output contract: disconfirming findings + their citation slots + an explicit "no disconfirming evidence found after searching X/Y/Z" if genuinely none.
   - Distinct from 6.6: **6.6 refutes the draft's claims by reasoning over already-fetched sources; the counter-evidence lane performs NEW external searches for disconfirming sources before the draft exists.** State this contrast verbatim in the skill so they are not conflated.
   - Feed its output into the synthesizer (§6) as a first-class input; the synthesizer must address disconfirming findings in the Flagged-disagreements block, adjudicated per method.md §4.4.
2. Cost/scope guard: counter-evidence lane fires on **deep-dive/FULL only** (not Short-shape first-pass) to hold the cost ceiling; log it in the §9 cost line (N+1 sub-agents). Skippable with a logged reason if the topic has no falsifiable thesis (pure enumeration).
3. Add a method.md §10 one-liner pointing to the new lane.

### WP2 verification
- Dry-run trace: pick one FULL-shape research-type, show the dispatch now includes the counter-evidence sub-agent with a self-contained disconfirming prompt, and that §9 cost logging reflects N+1. No live dispatch required for the doc PR; the researcher seat exercises it on the next real deep-dive (note as a post-merge live check for lead).

---

## Files Modified
- **WP1:** `_ops/agents/researcher/method.md` (§8 slot + Confidence/LOW rules, §4.4 new subsection, §2 two rows, §9 epistemic labels, §6 + fan-out one-line pointers).
- **WP2:** `_ops/skills/research-fan-out/SKILL.md` (new §4a + §9 cost line) + `_ops/agents/researcher/method.md` §10 one-liner.

## Do NOT Touch
- `researcher_bash_cage.sh` / any cage file — **no cage change in this brief** (no new channel needs a Bash path; archives/registries are WebFetch, already reachable).
- Step 6.5 / 6.6 skill logic — WP2 is additive (a new *search* lane), it does not alter refutation.
- baker-master code, DB, migrations, slugs.yml — none in scope.
- The §2 Reach column semantics from PR #182 — extend the table, don't rewrite existing rows.

## Related cleanup (flag to lead, NOT in this brief's scope)
- research-fan-out §3 (line ~53) still lists **GitHub via `Bash gh search`/`gh api`** — cage-blocked per PR #182. Same for §4 router "GitHub" cells. Should be reconciled to WebFetch/Chrome in a follow-up (consistency with method.md §2). Out of scope here; noted so it isn't lost.

## Quality Checkpoints
1. Extended §8 slot still parses through the verify-citations extractor (URL/Pub date/Byline unaffected).
2. Internal consistency: no surviving "≥2 sources" / staleness reference contradicts the new independence + Event/data-date rules.
3. §4.4 hierarchy composes with "surface, don't average" (both-sides shown; hierarchy = lean, not silent pick; same-rank → unresolved).
4. WP2 counter-evidence lane is unambiguously distinct from Step 6.6 in the skill text (search-before vs refute-after).
5. Both PRs are independent and separately mergeable; each from an isolated vault worktree.
6. Gate plan: Claude-side review (codex suspended, Director order #9711); lead merges each PR. Post-merge, researcher seat exercises §4.4 + counter-evidence lane on the next real deep-dive (lead-tracked live check).

## Gate plan
- Design: none needed (fields + ladder + lane fully specified above).
- Build: independent Claude-side review (deputy or non-author B-code) per PR.
- Lead merges. No production deploy / no `POST_DEPLOY_AC_VERDICT` (docs/skills only, no live Baker surface).
- Harness-V2: applies (Context Contract + done rubric via Quality Checkpoints + gate plan above). Docs/skills task class.
