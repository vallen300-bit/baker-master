---
brief_id: RESEARCHER_TRANCHE2_BUILD — item #7
item: 7 — Operational recency override
author: b1
date: 2026-07-12
status: DESIGN — for LEAD review (codex seats suspended; rails per lead #9712/#9720/#9723)
target_repo: baker-vault
source_brief: wiki/research/2026-07-12-researcher-capability-extension-brief.md @22ab300 (item register row 7)
---

# Design — Researcher tranche-2 item #7: Operational recency override

## 1. The ask (verbatim scope)

Item-register row 7: *"Operational recency override — topics <7 days require Grok/X or an
explicit logged waiver."* Class = Coverage, Effort = S, method **ship-gate**.

Problem it closes: a time-sensitive brief (e.g. "what's the latest on X this week") can ship
looking complete while never having walked a native-recency channel (Grok DeepSearch / Grok
X-search / Chrome MCP → x.com). WebSearch/Perplexity/Gemini lag real-time X/breaking signal by
days; for a <7-day topic that lag is a silent quality gap. The fix forces either the recency
channel to be walked, or an explicit, logged decision NOT to.

## 2. Design principle — reuse the established §4.x ship-gate pattern exactly

This is deliberately NOT a new mechanism. It is the third sibling of two already-shipped,
codex-blessed gates, so it inherits their proven shape and their anti-regex ruling:

- **§4.1 Coverage ledger → `INCOMPLETE`** — required channel partial/unavailable ⇒ label.
- **§4.2 Continuation queue → `CONTINUATION-MISSING`** — machine-readable declaration + validator, fail-closed.
- **§4.3 Recency override → `RECENCY-UNMET`** (NEW, this item) — same declare-then-gate shape.

Codex's binding ruling on §4.2 (#9312 ruling 2): **the gate reads a structured declaration, NOT
regex on prose** ("a validator cannot reliably infer gap-flags from prose"). #7 obeys the same rule.

## 3. Mechanism (three parts, mirroring §4.2)

### 3a. Declare (structured, at Step 0 intake manifest §4.0)

Add ONE field to the intake manifest (§4.0 table) so recency-sensitivity is a declared,
machine-readable fact set at Step 0 — not inferred at ship time from the report body:

| Field | Content |
|---|---|
| Recency window | `recency_sensitive: true\|false` + when true, `recency_window_days: <N>` (the freshness horizon the ask demands, e.g. 7). |

Detection is the researcher's Step-0 judgement from the brief language ("latest", "this week",
"as of today", "breaking", "current state of", an explicit date inside 7 days) — the same place
Shape (§9) and required-channels (§4.0) are already judged. It is DECLARED, not regex-sniffed.

Rationale for a declared field over prose-detection: identical to the §4.2 ruling. A brief can be
recency-sensitive with no trigger keyword, or use a keyword loosely; only a Step-0 human-in-agent
call is reliable. The manifest is where that call already lives.

### 3b. The gate rule (fail-closed)

At ship time, **if `recency_sensitive: true`**, the report passes the recency gate iff ONE of:

1. **Recency channel walked** — the coverage ledger (§4.1) shows a native-recency channel
   (`Grok DeepSearch`, `Grok X-search`, or `Chrome MCP → x.com/i/grok`) with status `complete`.
   (Reuses §4.1's existing channel-status table — no new bookkeeping surface.)
2. **Logged waiver** — a structured `recency_waiver` block is present and populated:
   ```recency_waiver
   - {reason: "<why the recency channel was not walked>", decided_by: "researcher|<dispatcher-slug>", date: <YYYY-MM-DD>}
   ```
   Waiver `reason` ∈ closed class { `channel-unavailable` (Grok/X bridge down) · `not-material`
   (topic <7d but real-time signal irrelevant to the ask) · `dispatcher-waived` (dispatcher
   explicitly said skip) }. Closed class keeps the waiver auditable, not a free-text escape hatch.

If `recency_sensitive: true` and NEITHER holds ⇒ report auto-labelled **`RECENCY-UNMET`** in its
header, and the paste-block bottom-line names the missing recency coverage (parallel to
`INCOMPLETE` / `CONTINUATION-MISSING`). If `recency_sensitive: false` ⇒ gate passes cleanly, no
block required (parallel to zero-deferral reports passing §4.2).

### 3c. Validator (cage-safe, deterministic)

New `scripts/validate_recency.sh <report>` mirroring `validate_continuation.sh`:
- Reads the report's method-log/header only (read-only, no network) — same trust pattern.
- Parses `recency_sensitive`. If `false` or absent-and-not-flagged ⇒ exit 0.
- If `true`: exit 0 iff (coverage-ledger has a native-recency channel row marked `complete`)
  OR (`recency_waiver` block present with ≥1 conformant row: reason in closed class + decided_by +
  date). Else exit non-zero with the reason on stderr ⇒ caller labels `RECENCY-UNMET`.
- Closed-set enforcement on waiver `reason` (unknown reason ⇒ non-zero), matching the
  validate_channel_output.py closed-set discipline just shipped in item #6.

## 4. Files touched (S effort — all in-cage-for-b1-build, proposal-for-researcher)

| File | Change |
|---|---|
| `_ops/agents/researcher/method.md` | Add row to §4.0 manifest table (recency_sensitive/window); add new **§4.3** (the gate rule + waiver schema), placed after §4.2 (line 145). One line in §9 Shape selector cross-ref. |
| `_ops/agents/researcher/method.md` §4.1 | Add `Grok/X` native-recency channels to the ledger's example rows so §4.3 clause 1 has an anchor (no structural change). |
| `scripts/validate_recency.sh` | NEW — deterministic gate, mirrors `validate_continuation.sh`. Exercise ≥6 paths (sensitive+channel-walked / sensitive+waiver / sensitive+neither / not-sensitive / bad-waiver-reason / malformed). |

No change to the write-cage, tool-cage, or any skill surface. No new MCP verb. Read-only + label-only.

## 5. Open questions for lead (settle in this review — no codex)

1. **Waiver authority**: may the researcher self-waive (`decided_by: researcher`), or must a
   `not-material`/`channel-unavailable` waiver still be *logged but self-approved* while a
   `dispatcher-waived` waiver requires the dispatcher on the bus? **b1 recommendation:** allow
   researcher self-waiver for all three reasons (the gate's value is the *logged, auditable
   decision*, not an approval bottleneck) — lead sees every `RECENCY-UNMET`/waiver at ship anyway.
2. **Window default**: fix the horizon at 7 days (per the brief title) or make `recency_window_days`
   a declared per-brief value defaulting to 7? **b1 recommendation:** default 7, overridable per
   brief — some asks are "today only" (<1d), the field costs nothing.
3. **Validator packaging**: standalone `validate_recency.sh`, or fold recency into a single
   `validate_shipgate.sh` that runs §4.1+§4.2+§4.3 together? **b1 recommendation:** standalone for
   this PR (matches the one-validator-per-gate precedent + smaller review surface); a later
   consolidation item can merge the three if lead wants one ship-gate entrypoint.

## 6. Done rubric (what "built" means for item #7)

- [ ] method.md §4.0 manifest gains the recency field; §4.3 added with gate rule + closed-class waiver schema.
- [ ] `validate_recency.sh` deterministic, read-only, ≥6 exercised paths, closed-set waiver enforcement, `bash -n` clean.
- [ ] No cage/skill/MCP surface touched; label-only + proposal-only preserved.
- [ ] Gate reads structured declaration only (no regex-on-prose) — honours codex #9312 ruling 2.
- [ ] PR to baker-vault, branch `b1/researcher-tranche2-item7-recency`; LEAD design-review pass → build → LEAD+deputy review → lead merge (no self-merge #9255).
