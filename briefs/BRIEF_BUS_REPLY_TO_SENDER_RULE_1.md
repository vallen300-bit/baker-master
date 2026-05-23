# BRIEF: BUS_REPLY_TO_SENDER_RULE_1 — codify reply-to-sender across worker orientations

> **CLOSURE NOTE 2026-05-23T13:25Z (lead):** This brief is **already-implemented** — verified on dispatch attempt. Work landed via baker-vault commit `9562cad` (2026-05-17) BEFORE this brief was authored (2026-05-22). All 6 target files contain the reply-to-sender rule:
> - `_ops/agents/b{1,2,3,4}/orientation.md` line 89/92 — workers obey rule
> - `_ops/agents/aihead2/orientation.md` line 21 — peer-AH parallel rule
> - `_ops/skills/ai-head/SKILL.md` line 213 — AH1 brief-authoring discipline
>
> Filed for audit-trail; no further action. Anti-pattern flagged per `/write-brief` "Already-implemented brief" rule.


## Context

Today (2026-05-17) we split the AH1 bus slug: terminal AH1 stays on `lead`, Cowork-App AH1 moves to `cowork-ah1` (commit `8d8adf9`, new `aihead1app` shell function in `~/.zshrc`). Routing is live. The 1Password key + 13-slug registry + daemon already supported the split.

But every downstream agent's orientation still says "bus-post `lead` on PR open" or "ship to `lead`" — hardcoded references that pre-date the split. If `cowork-ah1` dispatches a brief, the worker by default still ships to `lead`, so AH1-App's inbox stays empty and AH1-Terminal gets replies meant for the App.

This brief codifies a standing rule: **reply to the `from_terminal` of the original bus message, not hardcoded `lead`.** Updates worker orientations + AH1's own brief-authoring discipline. No infrastructure changes — purely orientation/SKILL doc edits.

## Estimated time: ~30-45 minutes
## Complexity: Low
## Ownership: AH1 (this brief writes to `baker-vault/_ops/agents/*/` — B-code-out-of-scope per CHANDA Inv 9 worker-write rule). AH1 self-executes; no B-code dispatch.

## Prerequisites

- Latest `baker-vault` main (`git fetch origin main && git pull --ff-only` on `~/baker-vault`).
- No baker-master changes; no Render deploy involved.

## API version / deprecation / fallback

Not applicable — purely orientation document edits. No external APIs.

---

## Problem statement

`cowork-ah1` is a valid bus recipient slug since today. But six downstream-agent orientation documents hardcode `lead` as the reply target. If AH1-App (Cowork) dispatches a brief, the worker's orientation tells them to ship back to `lead` (AH1-Terminal). Misrouted replies recreate the parallel-AH1 ambiguity the split was meant to fix.

**Solution:** add a standing "reply to `from_terminal` of original message" rule to each worker's orientation + SKILL.md. Replace hardcoded `lead` references where they describe addressing, not where they describe the lead role itself.

## Acceptance criteria

1. **Each of the following files contains an explicit "reply to `from_terminal`" rule** stated in plain English near the "Reporting" or "Communication" section:
   - `baker-vault/_ops/agents/b1/orientation.md`
   - `baker-vault/_ops/agents/b2/orientation.md`
   - `baker-vault/_ops/agents/b3/orientation.md`
   - `baker-vault/_ops/agents/b4/orientation.md`
   - `baker-vault/_ops/agents/aihead2/orientation.md`
   - `baker-vault/_ops/skills/aidennis-terminal/SKILL.md` (or wherever AID's canonical lives — confirm at edit time)

2. **The rule wording** (consistent across all 6 files):

   > **Reply-to-sender rule (Director-ratified 2026-05-17):** When responding to a bus message — ship report, gate verdict, ack, follow-up — bus-post to the `from_terminal` of the original message, NOT hardcoded `lead`. Today's AH1 instances are `lead` (terminal) and `cowork-ah1` (Cowork App); both addressable, neither implied. If multiple AH1 senders appear in a thread, reply to whichever sent the message you're answering. If you're unsure (e.g., initial outbound with no parent message), default to `lead`.

3. **AH1's own canonical SKILL.md** (`baker-vault/_ops/skills/ai-head/SKILL.md`) gets a parallel rule for brief-authoring discipline:

   > **Brief reply-target discipline:** When you (the dispatching AH1) write a brief, the "Reporting" / "Ship gate" sections must explicitly name your own slug (`lead` if AH1-Terminal, `cowork-ah1` if AH1-Cowork) as the bus-post target — NOT generic "post to `lead`". This pairs with the worker reply-to-sender rule so threads stay deterministic across the AH1 split.

4. **No hardcoded `bus-post lead` / `post to lead` / `ship to lead` references** remain in worker orientations after the edit (grep verification — captured in commit message). Replace with explicit reply-to-sender wording or `<dispatching-AH1-slug>` placeholder semantics.

5. **One commit per file** (or one combined commit, AH1 judgment) to `baker-vault` main with anchor "BUS_REPLY_TO_SENDER_RULE_1 (commit `<sha>`)" + push.

6. **Test plan:** AH1 verifies each file post-edit by running:
   ```
   grep -n "bus-post lead\|ship to lead\|post to.*lead\|reply.*to lead" baker-vault/_ops/agents/*/orientation.md baker-vault/_ops/skills/aidennis-terminal/SKILL.md baker-vault/_ops/skills/ai-head/SKILL.md
   ```
   Expected: any remaining matches are intentional (e.g., describing `lead` as a slug name in an example, not as a hardcoded reply target). All "where to send your reply" references should now be `from_terminal`-based.

## What this brief does NOT do

- Does NOT change `bus_post.sh` or daemon code (already live via commit `8d8adf9`).
- Does NOT touch the `BAKER_ROLE` shell mappings (already in `~/.zshrc`).
- Does NOT update brief templates retroactively for in-flight briefs (those keep their current routing — no rewrite).
- Does NOT add an enforcement hook to validate `from_terminal` use (separate brief if drift becomes an issue).
- Does NOT touch ClaimsMax / Grok / state-architecture / weekly-digest threads — unrelated.

## Out of scope

- B-code dispatch: this brief is AH1-self-executed. CHANDA Inv 9 puts vault `_ops/` writes in AH1/Director/Mac-Mini scope.
- AH1-Cowork (App instance) brief authoring on its own side — they pick up the rule on next session-start once SKILL.md edit lands.

## Ship gate

- Grep verification output captured in commit message.
- baker-vault commit pushed to `origin main`.
- Audit-trail bus-post to `lead` self with topic `merge/bus-reply-to-sender-rule-1` (since this is a vault config change, not a baker-master PR).

## Anchors

- 2026-05-17 chat — Director's question: "all workers and ah2 are aware of how to write to ah1app by bus, if they get bus from him?" surfaced the operational gap.
- Sister commit `8d8adf9` on baker-master added the `cowork-ah1` BAKER_ROLE mapping; this brief is the orientation-side counterpart.
- Composes with the existing agent-bus-posting-contract (`baker-vault/_ops/processes/agent-bus-posting-contract.md`) — extends rather than replaces.
- Composes with the `feedback_b_code_preflight_needs_ah1_verification.md` memory (same-session lesson on engineering-trust patterns) — both reinforce explicit addressing.

## Co-Authored-By

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
