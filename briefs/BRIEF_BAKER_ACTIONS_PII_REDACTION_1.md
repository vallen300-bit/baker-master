# BRIEF — `baker_actions` payload PII redaction (v0.1)

**ID:** `BRIEF_BAKER_ACTIONS_PII_REDACTION_1`
**Status:** PARKED — author AH2-T 2026-05-08; dispatch ordering owned by AH1.
**Origin:** LOW-9 follow-up from incident `waha-mis-route-marcus-pisani-1` (post-mortem `~/baker-vault/_ops/incidents/2026-05-08-waha-mis-route-marcus-pisani.md`).

---

## Problem

`outputs/whatsapp_sender.py:232` writes `text[:200]` verbatim into `baker_actions.payload.text_preview` for every send. Pattern is systemic — every WhatsApp send (not just incident misroutes) accumulates 200-char message previews indefinitely.

**Concrete leakage from the 2026-05-08 incident:** rows `id 854 / 855 / 856` persist the full T1 alert texts (overdue items + counterparty names) that were originally mis-routed to Marcus Pisani. These rows now live in audit storage, readable to anyone with `baker_raw_query` access (Director + AH agents).

**Generalized risk:** every routine T1 alert / ops alert / draft notification persists a 200-char preview. Many contain entity names, monetary figures, deadlines, or counterparty references that are PII-equivalent under Brisen's posture even if individually low-value.

## Why now (LOW priority, not deferred indefinitely)

- Not bleeding — `baker_actions` reads gated to `X-Baker-Key` API + Baker MCP. No counterparty path. Not externally exposed.
- BUT: silent accumulation. 6 months of audit data = thousands of preview rows = cumulative leak surface.
- AND: the 3 incident rows exist on production storage right now, on a known-bad routing — those should be scrubbed before any future audit / forensic review.

## Constraints

1. **Audit usefulness preserved.** `path_taken`, `requested_chat_id`, `actual_chat_id`, `http_status`, `success` MUST remain unredacted — those are load-bearing for incident forensics + smoke verification. Only `text_preview` is in scope.
2. **No schema migration if avoidable.** JSONB payload structure stays; only the `text_preview` value's content changes.
3. **Reversibility.** Hash-or-truncate must be deterministic enough to dedupe / cluster repeat alerts without retaining raw content.
4. **Fail-soft.** Existing `try/except` around audit row write must remain — redaction failure must never break the send path.
5. **One-shot historical scrub** must be idempotent + reversible (snapshot the current values somewhere recoverable BEFORE scrubbing, in case of dispute).

## Acceptance criteria

### Forward (new sends)

1. `_log_send_to_baker_actions` writes `text_preview` as `{"head": <first 40 chars>, "sha256": <hex of full text>, "len": <int>}` instead of raw `text[:200]`.
   - Example: `{"head": "*T1 Alert:* OVERDUE: q30-lana-650k-tax", "sha256": "9f8…", "len": 187}`
   - "head" length 40 ≈ readable enough for an analyst to identify alert type without exposing entity / amount / counterparty detail.
2. `path_taken` short-circuit Director path (`short_circuit_director`) MAY exempt the head-truncation if the text is a Director self-message — but defaulting to redacted-everywhere is simpler and safer. Recommendation: redact uniformly.
3. Smoke previews ("re-enable smoke 1/3") are intentionally short + non-PII; they will hash-and-show-head identically to other texts (no carve-out needed).

### Historical (one-shot)

4. New script `scripts/redact_baker_actions_text_preview.py` rewrites all existing `baker_actions WHERE action_type='whatsapp_send'` rows to the new payload format.
5. Pre-redaction full-row dump to `~/baker-vault/_ops/incidents/2026-05-08-waha-mis-route-marcus-pisani-text_preview-snapshot.jsonl.gz` (vault-side, not committed in repo) — recoverable for 90 days then deleted, retention by an explicit follow-up brief.
6. Special-case the 3 incident rows (id 854, 855, 856): scrub FIRST, atomic batch.

### Tests

7. Unit: `text_preview` redaction helper produces correct `{head, sha256, len}` shape for: (a) ASCII text < 40 chars, (b) ASCII text > 200 chars, (c) UTF-8 emoji-heavy text (alert headers like "📋 *Baker AI*"), (d) empty string.
8. Integration: live-PG (`TEST_DATABASE_URL` gated) — call `send_whatsapp` mock-WAHA, assert `baker_actions` row's `payload->>'text_preview'` is JSON-parseable + has expected keys.
9. Migration: dry-run mode (`--dry-run`) on the scrub script that prints rewrites without committing; CI assert no row produces a `head` containing PII keywords from a small denylist (counterparty names from `wiki/people/` slugs).

### Out of scope (next brief)

- Email body preview redaction in any other `baker_actions` `action_type` (email_send, draft_email, etc.). This brief covers `whatsapp_send` only — extend in a follow-up after pattern stabilizes.
- Retention / TTL on `baker_actions` rows (separate retention policy brief).
- Encrypting `payload` JSONB at rest (separate infra brief).

## Files

- `outputs/whatsapp_sender.py` — modify `_log_send_to_baker_actions` payload construction (lines ~229-234).
- `scripts/redact_baker_actions_text_preview.py` (new) — one-shot scrub.
- `tests/test_baker_actions_text_preview_redaction.py` (new).
- `~/baker-vault/_ops/incidents/2026-05-08-waha-mis-route-marcus-pisani-text_preview-snapshot.jsonl.gz` (vault-side dump, B-code creates locally + AH2-T copies to vault).

## Test plan

```bash
pytest tests/test_baker_actions_text_preview_redaction.py -v
python scripts/redact_baker_actions_text_preview.py --dry-run --limit 10
# manual review of dry-run output
python scripts/redact_baker_actions_text_preview.py  # full run
```

Then live-spot-check via `mcp__baker__baker_raw_query`:

```sql
SELECT id, payload->>'text_preview' AS preview
FROM baker_actions
WHERE action_type='whatsapp_send'
  AND id IN (854, 855, 856, 859, 860)
ORDER BY id;
```

Acceptance: all 5 rows show JSON-shaped preview (head + sha256 + len), no raw alert text.

## Tier-A merge gate

`/security-review` skill on PR diff. AH2-T runs verdict per Lesson #52.

## PL ship-report contract

Standard PL paste-block per `~/baker-vault/_ops/skills/ai-head/SKILL.md` §"PL ship-report contract".

PL topic: `incident/waha-mis-route-marcus-pisani-followup-pii`.

---

**Author:** AH2-T 2026-05-08T~09:40Z
**Dispatch decision:** AH1-T against current lane backlog (#170, BEN GOLD-write, others).
