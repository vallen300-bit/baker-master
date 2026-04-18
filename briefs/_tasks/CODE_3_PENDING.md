# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** §6 prompts shipped (`242a4d3`, corrected at `cd8abab` for Qwen re-scoping)
**Task posted:** 2026-04-18
**Status:** OPEN — awaiting execution

---

## Task: Draft KBL-B Step 0 — Layer 0 Deterministic Rules (per-source)

You saw 50 real signals across 3 eval cycles (email + WhatsApp + meeting transcripts). You know empirically what's noise vs substance per source. Draft the deterministic Layer 0 filter rules that drop 10-30% of signals before Step 1 Triage even sees them.

### Context

Per §4.1 of `briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md`:

> **Step 0 — `layer0`** (per-source deterministic filter) drops obvious noise before any LLM touches it. 10-30% of signals drop here.

Per D3 §247 in decisions doc: Layer 0 is "per-source deterministic filter" — no model calls, no embeddings. Pure Python rules on signal metadata + content heuristics.

### Deliverable

File: `briefs/_drafts/KBL_B_STEP0_LAYER0_RULES.md`

Structure per source:

#### For each of email / whatsapp / meeting_transcript / scan_query

1. **Rule list** — each rule has:
   - **Name** (e.g., `email_sender_blocklist`, `wa_automated_number`, `transcript_too_short`)
   - **Trigger condition** (exact Python predicate on `signal_queue` row + payload JSONB)
   - **Action** (drop, always) + log message
   - **Empirical basis** — which signal(s) in your eval set motivated this rule (cite by `signal_id` or label JSONL line number)
   - **False-positive risk** — signals that LOOK like the pattern but aren't noise (your judgment)

2. **Ordering** — some rules need to run before others (e.g., check "Baker self-analysis dedupe" before "short content" because self-analyses are often short)

3. **Configurability** — which rules are hardcoded vs env-var tunable (e.g., `KBL_LAYER0_EMAIL_BLOCKLIST_DOMAINS` as CSV, `KBL_LAYER0_WA_MIN_LENGTH=20`)

### Rules you should cover at minimum

**Email:**
- Sender blocklist (LinkedIn, newsletter senders, unsubscribe-pattern domains)
- Unsubscribe link + auto-generated header detection
- Bounce/autoreply patterns
- Baker self-analysis dedupe (the 7 duplicates in your v1 eval set — they share signature patterns)
- Subject-line noise (e.g., "Your receipt for...")

**WhatsApp:**
- Automated number ranges (verification codes, 2FA services — patterns like `+12025550123` US-throwaway)
- Forwarded-without-context chain (msg body starts with `Forwarded:` or contains only a link)
- Group-join/group-leave system messages
- Voice-note placeholder signals (no transcribed content)

**Meeting transcript:**
- Minimum content threshold (your garbled Fireflies transcript at signal idx 29 — what did it look like?)
- Internal-only meeting pattern match (e.g., title contains "Baker team standup")
- Test/demo transcripts (title contains "test", "demo", "throwaway")

**Scan query:**
- Director's own queries — NEVER drop, always pass-through. Document this rule explicitly.

### What NOT to include

- **No model-based rules.** Layer 0 is deterministic only.
- **No aggregate filters** (e.g., "drop if total emails from sender > 10 this week"). Those are stateful; belong in later steps if at all.
- **No per-matter rules.** Layer 0 runs before matter classification (Step 1).
- **No retroactive rules** ("if Step 5 previously returned X for this sender"). Forward-only rules.

### Reference for Step 0 contract

§4.1 of `briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md` defines the IO contract. Your rules must fit within it (read `source`, `raw_content`, `payload->>`... / write `state='dropped_layer0'` terminal OR `state='done'` + route forward).

### Dispatch back

> B3 Step 0 rules drafted — see `briefs/_drafts/KBL_B_STEP0_LAYER0_RULES.md`, commit `<SHA>`. Rules: `<N>` per source, `<X>` env-var-tunable.

### Scope guardrails

- **Do NOT** implement Python. This is rule specification, not code. AI Head assembles into §6 / implementation brief later.
- **Do NOT** propose new `signal_queue` columns. Work within current shape.
- **DO** cite specific eval-set signals as empirical basis — this is your unique value-add.

---

## Est. time

~45 min:

- 10 min re-read your eval labels + extract noise patterns
- 30 min rule drafting with empirical citations
- 5 min ordering + configurability pass
- Commit

---

*Dispatched 2026-04-18 by AI Head.*
