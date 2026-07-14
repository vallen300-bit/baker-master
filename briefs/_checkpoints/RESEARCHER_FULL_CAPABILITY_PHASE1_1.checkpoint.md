# RESEARCHER_FULL_CAPABILITY_PHASE1_1 — checkpoint

- status: CLOSED — live fan-out addendum folded + verdict posted (lead #11147, deputy #11148). Worktree removed. attempt: 1

## ADDENDUM FOLDED — ARC CLOSED (2026-07-14)
- Researcher returned V4 live probe #11133 (thread af79f071). B4 ran the ACTUAL validate_channel_output.py (researcher cage blocks python exec):
  - Both channels (Perplexity Ask + Web/WebFetch) exit 0, type-3 conform.
  - evidence_pack_v1 sample run through channel validator = exit 1 "missing channel" → envelope-separation LIVE-PROVEN (the #10698 fix holds vs a live pack).
  - evidence_pack_v1: 18/18 fields, zero extras, all vocab-valid, on-trust Phase-1 flagged (verification=pending, worker=dry-run, claim=SAMPLE).
  - Behavior confirmations correct: dynamic N=2 saturation (no N-cap); Opus-4.8 synth; Mnilax honest-concordant.
- POST_DEPLOY_AC_VERDICT ADDENDUM posted: ac_result=PASS, done_state=DONE, writeback=complete (supersedes #11003 pending) → lead #11147 + deputy audit-cc #11148. Ack of #11133 done (endpoint + researcher #11137).
- Follow-on relayed to lead: check_inbox.sh:153 substring-greps body for "bad_terminal_key" → false key-reject on valid 200 (F1 probe msg contains the literal). Fix = test daemon top-level error field. NOT b4-lane.
- Worktree /private/tmp/b4-researcher-fullcap REMOVED. Nothing left in b4 lane.

## LEAD RULING #11018 (2026-07-14) — merge surface DONE
- Lead ruled deterministic PASS SUFFICIENT for docs-only vault merge → merge surface DONE. Live fan-out #10990 = verification ADDENDUM, NOT a blocker.
- Acked #11018. Corrected verdict posted done_state=DONE: lead #11024 + deputy #11032 (both deduped = landed).
- CONTINGENCY (lead #11018): if researcher #10990 silent at +4h from dispatch (dispatch 08:09Z → deadline ~12:09Z 2026-07-14), post wake-check to deputy (verify researcher wake state) cc lead. Background poll /tmp/b4-v4-poll.out (~25min from 08:24) covers near-term.
- Successor: fold live fan-out ADDENDUM verdict (channel-JSON conformance + on-trust pack) on researcher return → then remove worktree /private/tmp/b4-researcher-fullcap. Arc merge-surface is already DONE; addendum is verification-only.

## MERGED + V4 POST-DEPLOY (2026-07-14)
- Vault PR #196 MERGED @71a316b (lead #10969, my ack). Docs live on origin/main.
- V4 deterministic surface = PASS: validator-separation proven (Type-3 channel exit0 / evidence_pack_v1 exit1 "missing channel"); 18-field evidence_pack_v1 contract matches dispatch-templates.md verbatim; survivors intact (Opus-4.8 synth #1369, counter-evidence lane, verify-citations 6.5, 1Password excluded, gemma4:26b warning); N=3/5+$-budgets retired to dynamic/telemetry; SKILLS_INDEX regenerated; internal librarian/CM Phase-2-gated confirmed.
- POST_DEPLOY_AC_VERDICT v1 posted: lead #11003 + deputy audit-cc #11004. ac_result=PASS(deterministic), done_state=NOT_DONE, writeback=pending:live-fan-out.
- LIVE fan-out dispatched researcher #10990 (thread e1f481d5) — NOT returned in ~9min (researcher wake unconfirmable, 403 cross-inbox). Background poll running /tmp/b4-v4-poll.out (~25min).
- DEFERRED NIT (codex-cleared, fold on next SKILL.md touch): SKILL.md:88 §4a phrases counter-evidence rationale as "default trio + escalation-5" — illustrative, not an operative cap.
- NEXT (successor): if researcher #10990 returns, validate channel-JSON conformance + on-trust pack flagging → post addendum verdict to lead+deputy → DONE. If lead rules deterministic surface sufficient for docs-only merge → DONE. Worktree /private/tmp/b4-researcher-fullcap can be removed after that.

## GATE PASS (2026-07-14 — codex-arch re-gate #10956)
- codex-arch re-gate on a2cbad5 = **PASS** (#10956): both docs nits fixed (method.md "Time shape" consistent; internal-lane Phase-1 on-trust vs Phase-2 receipted distinguished), consistency sweep clean, no code/arch findings.
- Acked #10956 (HTTP 200). Relayed merge-eligible → lead #10967 (topic ship/researcher-full-capability-phase1).
- PR #196 head=a2cbad5, OPEN, merge-eligible.
- NEXT (successor): await lead merge → run V4 live probe (one SHORT fan-out + 1 librarian template, validate evidence_pack_v1) → POST_DEPLOY_AC_VERDICT to lead. Worktree /private/tmp/b4-researcher-fullcap KEEP until merge.

## REVISE round 2 (2026-07-14 — codex-arch REVISE-W-NOTES #10922)
- Codex-arch on 1ce8e5a = REVISE-W-NOTES: "no code/architecture blocker", prior substantive gaps fixed; two docs-only nits left.
- FIXED in commit **a2cbad5** (pushed), 3 files +4/-4 docs-only:
  - method.md:157 continuation-intake field list "Budget" → "Time shape" (matches renamed intake field at method.md:110).
  - dispatch-templates.md:14 "receipted evidence" → "evidence packs"; consistency sweep fixed the same contradiction at method.md:60 + orientation.md:75 (all flag Phase-1 on-trust, reserve "receipted" for Phase 2).
- Bus: ack #10922, re-gate→codex-arch #10927 (thread d5cb771b), status→lead #10931 (thread 52fbf815).
- PENDING: codex-arch re-verdict on a2cbad5 → lead merge → V4 live probe + POST_DEPLOY_AC post-merge.

## REVISE round (2026-07-14, lead dispatch #10882 — codex-arch REVISE #10871)
- Codex-arch verdict on PR #196 = REVISE (#10871): 4 docs-faithfulness gaps (docs-only; envelope-split code fix NOT faulted). Lead dispatched fix-all-four-same-PR + re-request codex-arch on same thread.
- FIXED in commit **1ce8e5a** (pushed to b4/researcher-full-capability-phase1), 6 files +39/-30, docs-only:
  - P1 `research-fan-out/checklist.md`: retired N=3/5 caps + $0.60/$0.80/$1.50/$2.30 ceilings + Opus 4.7 + "No Gemma" → dynamic fan-out, cost=telemetry, Opus 4.8 synthesizer, Gemma worker lane; R3 broken-tool path de-N=5'd.
  - P1 `researcher/orientation.md`: line-58 dispatch flow → dynamic fan-out; "4-tier/cheapest-first/escalate-to-paid" section reframed under superseded anchor (channel/tool reference, not mandatory order).
  - P2 `researcher/method.md`: budget scaffolding → time-shape + cost=telemetry (WHO intake/routing rows, intake-manifest "Budget"→"Time shape", ceiling-hit deferral class time-only).
  - P2 internal Librarian/CM route recorded Phase-2-gated (spec-ready, NOT operational); evidence-pack validator + receipt ledger = explicit hard dependency across method.md §2 + orientation.md + SKILL.md + dispatch-templates.md + output-schemas.md.
- Bus: ack #10882, re-gate→codex-arch #10916 (topic gate/pr196-...), status→lead #10918 (threaded on #10882).
- PENDING: codex-arch re-verdict on 1ce8e5a → on request_changes NEW commit (never amend), regen SKILLS_INDEX if any SKILL.md frontmatter changes, push, re-gate; then lead merge; then V4 live probe post-merge + POST_DEPLOY_AC.
- Worktree `/private/tmp/b4-researcher-fullcap` on branch @1ce8e5a — KEEP until merge.

## Prior round (SHIPPED, superseded by revise round above)

## SHIPPED (2026-07-13)
- Vault PR **#196** (`b4/researcher-full-capability-phase1`, commit 975ffb5). All 5 pieces + regenerated SKILLS_INDEX. Worktree `/private/tmp/b4-researcher-fullcap` still present (keep until merge for request_changes).
- V1 supersession grep clean, V2 survivors all present, zero cage/settings edits.
- Bus: ack→lead #10664, gemma probe→researcher #10678, ship+wrapper-spec→lead #10693, gate→codex #10695.
- **Codex gate ROUND 1 = FAIL #10698 (P1):** evidence_pack_v1 rows could not pass validate_channel_output.py (gates on research_type + REQUIRED_ROW_KEYS, rejects unknown keys) → every librarian/CM pack dropped as §7 failure. FIXED commit **959eba6**: internal lane = SEPARATE envelope ("schema":"evidence_pack_v1"), NOT a research_type channel, bypasses the validator (validator + external per-type schemas untouched); synthesizer consumes packs directly; Phase-1 no evidence-pack validator (Phase 2 ledger). Fixed output-schemas.md companion + dispatch-templates.md 2 bullets + SKILL.md §3 note. Re-gate→codex #10800, note→lead #10801.
- PENDING: (a) codex RE-gate verdict on 959eba6 → on request_changes NEW commit (never amend), regen skills index if SKILL.md changes, push, re-gate; (b) researcher gemma probe #10678 reply (confirmatory only); (c) lead merge; (d) V4 live probe post-merge (dispatch researcher one SHORT fan-out + 1 librarian template, validate evidence_pack_v1); (e) POST_DEPLOY_AC_VERDICT to lead.
- NOTE: commit hook requires SKILLS_INDEX regen when any SKILL.md changes — `python3 _ops/skills/gen_skills_index.py && git add`.

- seat: B4. dispatched_by: lead (#10640 + rider #10658). Brief @8bd8f274 governs (codex-arch competing brief REJECTED #10657).
- reply target / gate: lead. Gate: G1 self-verify → codex effort=high → lead line-review+merge → live probe → POST_DEPLOY_AC_VERDICT.

## Worktree (isolated — shared-vault-checkout hazard)
- `/private/tmp/b4-researcher-fullcap` on branch `b4/researcher-full-capability-phase1`, off origin/main @ eac69fc. ONE vault PR.
- Do NOT write to ~/baker-vault directly (it's dirty with other agents' state).

## Files to edit (all in worktree)
1. `_ops/agents/researcher/method.md` — §10 dynamic fan-out (line ~388) + §2 WHERE internal-lane pointer + supersession anchors. §10 current: "Default N=3 channels, escalation N=5. Opus 4.8 synthesizer … #1369". Footer line 401 cites #1365/#1369/#1374.
2. `_ops/agents/researcher/orientation.md` — NEW "Authority — full-capability research principal (2026-07-13)" section (cost=telemetry, action restrictions amendment 7). Keep Rule 3/5 verbatim.
3. `_ops/skills/research-fan-out/SKILL.md` — §1/§2 dynamic N + Stage-2 lane list; §3 strike Gemma-exclusion + internal-data exclusion (keep 1Password excluded); §4/§5 lane-escalation; §4a two-family challenge.
4. `_ops/skills/research-fan-out/output-schemas.md` — additive evidence_pack_v1 companion section.
5. `_ops/skills/research-fan-out/dispatch-templates.md` — NEW (librarian + CM-1..4 templates, evidence_pack_v1 contract, CM partition rule).
6. `_ops/skills/local-research-via-gemma/SKILL.md` — Fix 3b worker-role rewrite IF gemma runs, else 3c `pending-cage-route (cowork-ah1 #10528)` note. Pin gemma4:latest; keep :26b broken warning.
7. RIDER piece 5 (#10658): CM-1 doc-pin Haiku→Sonnet (zshrc cm1-cm4 all sonnet-4-6[1m]). Doc-only, same PR. TODO: locate CM-1 doc file (grep Haiku).

## Proposal binding content (extracted, in-hand)
- evidence_pack_v1 fields: question_id, lane, claim, evidence_type(fact|opinion|estimate|inference|lead), quote, source, location, publisher, author, published_at, accessed_at, source_rank(primary|authoritative-secondary|secondary|signal), supports[], contradicts[], confidence(high|medium|low), worker, verification(pass|partial|fail|pending) + "schema":"evidence_pack_v1".
- Gemma worker roles: large-corpus read/analyze; transcribe/analyze audio+visual; segment/index transcripts; extract claims/quotes/entities/dates/amounts/relationships; compare many docs; find inconsistencies/unusual patterns; alt hypotheses; independent 2nd model on same evidence; read-only retrieval where supported; return structured evidence + own interpretation for Opus to assess.
- CM partition: by source family / issue / date period / entity / competing hypothesis; NOT 4 copies of one prompt unless deliberate replication test.
- Stage-2 lanes (11): official/primary, academic/standards/regulatory, technical/GitHub, trade-press/practitioner, social/X/community, internal Baker evidence, ClaimsMax/document archive, media/transcript/visual, paid/authenticated, counter-evidence, independent alternative-model.
- Stage-4: high-stakes challenge uses TWO different model families (reduce correlated error).
- Amendment 7 action restrictions: no destructive changes, no operational commitments, no credential exposure, no unrelated confidential-data access.
- Amendment 5: permit direct bus orchestration of Librarian + CM-1..4 by Researcher. Amendment 6: normalize CM-1 doc+runtime to Sonnet.

## Survivors (must remain post-edit — Verification 2)
Opus 4.8 synthesizer (#1369), researcher-verify-citations mandatory, counter-evidence lane, matter-confidentiality re-route, action restrictions, gemma4:26b broken warning, 1Password exclusion.

## Supersession anchor pattern
`(superseded 2026-07-13 — Director best-in-class directive, bus #10567/#10584; #1369 Opus-synthesizer clause SURVIVES)`

## Do NOT touch
researcher_bash_cage.sh, picker settings*.json (cowork-ah1 #10528), research-types.md, validate_channel_output.py, researcher-verify-citations skill, slugs.yml, any code repo.

## Bus trail
ack lane→lead #10664. (pending: gemma probe dispatch→researcher; ship→lead; gate→codex.)

## PROGRESS (attempt 1)
- DONE Fix 1: method.md §10 dynamic fan-out + §2 internal-lane row + Step-0/line-279 cost-telemetry reframe + anchors. orientation.md Authority section + 4 cost-halt reframes (blocker line, daily-cost-control, time-discipline, Cost-telemetry section).
- DONE Fix 4: research-fan-out SKILL.md §1 dynamic N, §3 Gemma-worker-lanes + internal lane (1Password kept excluded), §4 router Gemma/internal overrides + Stage-2 wide lane list, §4a two-family challenge, §6 synthesizer reword (Opus-only survives), §9 cost-telemetry, Key Constraints 3/4/7 + frontmatter + YouTube reworded. Verification-1 residual grep run — remaining hits are dated anchors (OK); method.md:143 left (continuation ceiling-hit schema, adjacent subsystem, out of scope).
- Fix 3 = PATH 3c CONFIRMED cage-blocked: cage script `_ops/hooks/researcher_bash_cage.sh` L48/L51 denies curl/localhost (Gemma local Ollama). method.md §2 already audited 2026-07-12 same. Live probe dispatched to researcher #10678 (autowakes; confirmatory only). → write gemma skill worker-roles but mark `pending-cage-route (cowork-ah1 #10528)`; post blocked-cmd + wrapper spec to lead.

## REMAINING
- Fix 3: edit `_ops/skills/local-research-via-gemma/SKILL.md` — worker-role scope rewrite + pending-cage-route note; keep :26b warning + gemma4:latest pin. Then post blocked-cmd + vetted-wrapper spec to lead.
- Fix 2: NEW `_ops/skills/research-fan-out/dispatch-templates.md` (librarian + CM-1..4 template families, evidence_pack_v1 contract, CM partition rule, bus mechanics). + `output-schemas.md` additive evidence_pack_v1 companion section. (§3 fan-out pointer + method §2 row already done.)
- Piece 5 (#10658): CM-1 doc-pin Haiku→Sonnet in `_ops/agents/_universal/cm/`: CLAUDE.md.reference (L5, L48), orientation-v2.md (L11, L34), cm-1-design.md (L251/255 — careful: historical Haiku-tier analysis, only normalize the forward model-pin, not the incident history). zshrc = sonnet-4-6[1m].
- Then: Verification-2 survivor grep; git add + commit + push; PR; ship to lead for codex gate (effort=high). Live probe (Verification 4) is post-merge.

## Next concrete step
Edit gemma skill (Fix 3c) → write dispatch-templates.md + output-schemas companion (Fix 2) → CM-1 doc-pin (piece 5) → survivor grep → commit/PR/ship.
