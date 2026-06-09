---
status: PENDING
brief_id: M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1
dispatch: M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1
to: b2
dispatched_by: lead
priority: CRITICAL
Harness-V2: applies (production mail pipeline) — Context Contract + task class + done rubric + gate plan below
---

# M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1 — Baker is BLIND to Director's M365/Outlook inbox (CRITICAL)

## Context (Context Contract)

Director migrated his primary work mailbox `dvallen@brisengroup.com` from legacy Google/Exchange to **Microsoft 365 / Outlook ~2026-06-03**. A prior session pin (§A-LEAD-0607, 2026-06-07) claimed *"OUTLOOK/M365 FEED RESTORED — BAKER_USE_GRAPH=true, graph_mail sentinel healthy, mail flowing, Peter Storer search PASS"*. **Director ratified 2026-06-09 that this claim is WRONG.** Baker cannot see post-migration brisengroup mail.

**Evidence (today, 2026-06-09):** Director needed a 6 Jun 17:59 email from Mario Spanyi (`M.Spanyi@eh.at`, E+H) re a court hearing (hearing 10 Jun — legal deadline). `baker_gmail_search` returned ZERO for `from:M.Spanyi@eh.at` after 2026/06/05; the `EH-AT.FID93225` thread is only visible up to 1 Jun (pre-migration). Director had to paste the body + save attachments by hand.

**Why critical:** FAIL-SILENT — searches return empty, not an error. Any agent/desk relying on `baker_gmail_*` for brisengroup mail silently misses everything post-migration → confidently-wrong answers on legal deadlines + counterparty threads. The signal_queue / watermark ingestion is Gmail-sourced and now misses work mail.

**Conflict to resolve (do NOT trust either side — verify with evidence):**
- PIN says graph_mail sentinel is healthy + Peter Storer search PASSed.
- Desk evidence says post-6/3 brisengroup mail is unsearchable.
- Reconcile: is graph_mail actually ingesting M365 into the store? Did the prior "PASS" only hit a pre-migration cached doc? Is `baker_gmail_search` simply the WRONG surface (Gmail-OAuth only, never touches the M365/graph store) while `baker_search` would find it — or is the store genuinely empty of M365 mail?

## Problem

Determine the true state of M365 mail ingestion + search, then restore Baker's ability to find/ingest Director's Outlook mail. Legal-deadline mail is silently invisible.

## Phase 1 — DIAGNOSIS (read-only, NO code changes, report first)

Answer with evidence (commands + outputs):

1. **Ingestion:** Does the `graph_mail` sentinel actually pull M365 mail for `dvallen@brisengroup.com`? Check `/health`, the sentinel watermark, recent ingested rows (last successful run; row count post-2026-06-03; any auth/permission errors). Is `BAKER_USE_GRAPH` actually true on Render baker-master? Are the Graph creds (cert-based `M365_*` / Entra app) present + valid?
2. **Store/search:** Can `baker_search` / SentinelRetriever surface a known post-migration brisengroup email? Concrete test: the Spanyi `EH-AT.FID93225` thread / `M.Spanyi@eh.at` 6 Jun 17:59. Does it exist in the store at all?
3. **Tool surface:** Confirm what `baker_gmail_search` / `baker_gmail_read_message` actually connect to (Gmail OAuth only?). Is there ANY tool surface reaching M365 mail today? (Determines whether the SOP / desks must stop using `baker_gmail_search` for brisengroup mail.)
4. **Pipeline:** Is signal_queue classification + watermarks Gmail-only, or does graph_mail feed them? What breaks downstream.

**STOP after Phase 1.** Bus-post `lead` a findings summary + a concrete fix plan (smallest change that makes Spanyi's 6 Jun email findable). Do NOT implement until lead greenlights — the fix likely touches Render env / Entra app config (Tier-B, lead authorizes). NOTE: cert-based `M365_*` creds + an Entra app already exist on Render (PIN reports cert auth authenticated cleanly, no 403/consent gap), so the likely root cause is a pipeline / tool-surface bug, NOT a missing app registration — confirm which in Phase 1.

## Current State

To be established by Phase 1 — this is a diagnosis-first brief. Do not assume the PIN's "restored" claim; reproduce the blindspot with the live Spanyi search before forming the fix.

## Phase 2 — FIX (only on lead greenlight, after Phase 1)

Scope set by Phase 1 findings. Likely one of: (a) graph_mail config/auth repair + restart; (b) point the mail tool surface at the merged store; (c) net-new Graph Mail connector (messages + attachments) mirroring the Gmail tool surface, dual-source with `vallen300@gmail.com` kept on Gmail. Tests first (reproduce the blindspot with a failing test, then make it pass).

## Files Modified (Phase 2, expected — confirm in Phase 1)

- `triggers/` — Gmail polling / graph_mail ingestion
- `tools/` — mail tool definitions (baker_gmail_* surface)
- graph config module — the `@dataclass` GraphConfig with import-time env freeze (b2's prior dx)
- possibly `kbl/` — retriever wiring for the merged mail store

## Do NOT Touch

- `vallen300@gmail.com` Gmail polling path — personal account stays on Gmail (dual-source).
- Outbound email / send paths — this is a READ/ingestion fix only.
- Unrelated sentinels (todoist, roadmap_drift) — out of scope.

## Verification (done rubric — task class: cross-layer production bugfix)

NOT "tests pass". Done =
1. `baker_search` (or the corrected tool surface) returns Mario Spanyi's 6 Jun 17:59 email from `M.Spanyi@eh.at` (live, against prod store) — the exact email Director couldn't find.
2. A NEW M365 email sent to `dvallen@brisengroup.com` becomes searchable within one ingestion cycle (prove the pipeline is live, not just backfilled).
3. `baker_gmail_*` (or replacement) no longer fail-silent on brisengroup mail — either they reach M365 or they error loudly with a pointer to the right tool.
4. POST_DEPLOY_AC_VERDICT v1 posted to bus with the live Spanyi-find evidence.

## Quality Checkpoints

1. AC1: Phase 1 findings posted to bus `lead` with command outputs (no "by inspection").
2. AC2: Spanyi 6 Jun email findable post-fix (live prod evidence pasted).
3. AC3: New-mail ingestion proven live (not just historical backfill).
4. AC4: No fail-silent path remains for brisengroup mail — silent-empty becomes loud-error or correct-hit.
5. New integration has health monitoring: a graph_mail staleness alert fires if no M365 mail ingested in N hours.

## Verification SQL

```sql
-- Phase 1: is any M365/graph-sourced mail in the store post-migration?
SELECT source, COUNT(*), MAX(created_at)
FROM signal_queue
WHERE created_at > '2026-06-03'
GROUP BY source
ORDER BY 2 DESC
LIMIT 20;
-- (confirm actual table/column names in Phase 1 via information_schema before trusting)
```

## Gate plan

G0 codex (autonomous) on diagnosis + fix plan → lead reviews Phase 1 → G2 /security-review on the Phase 2 diff (touches OAuth/creds) → G3 codex on implementation → lead merges → POST_DEPLOY_AC live-verified by the Spanyi test.

## Escalation

- You own the full diagnosis + fix (engineering + Azure/Entra config) — do NOT hand the Azure piece to AID-T (Director standing rule: engineering goes to B-codes/codex, not AID).
- If the fix needs a Render env change or Entra app permission change → prepare the exact change + flag to lead (Tier-B; lead authorizes).
- If admin consent in Director's M365 tenant is genuinely required (Director-as-tenant-admin action) → flag to lead as Tier-C; do not block Phase 1 on it.
