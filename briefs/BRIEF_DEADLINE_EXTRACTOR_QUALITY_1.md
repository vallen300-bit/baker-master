# BRIEF_DEADLINE_EXTRACTOR_QUALITY_1 — Email Pipeline Deadline Extractor Tightening

**Date:** 2026-04-26
**Source spec:** `_ops/ideas/2026-04-26-deadline-extractor-quality-1.md`
**Author:** AI Head Build-reviewer (promoting from RA spec)
**Director defaults:** Q1/Q2/Q3 all defaulted to RA recommendations 2026-04-26 ("Your 3 question — you default. I skip")
**Trigger class:** **LOW** (no auth/DB-migration/secrets/external API/financial/cross-capability writes) → AI Head solo merge per autonomy charter §4

---

## 1. Bottom-line

Tighten the email-pipeline deadline extractor to reject promotional / event / informational language. Cat 6 audit found ~60% noise rate (25 of 42 email-extracted deadlines were spam: Loro Piana, Mother's Day, Bloomberg, Botanic, golf events, etc.).

Two-layer filter:
- **L1 Sender domain blocklist** (regex on sender, no LLM call)
- **L2 Subject/body keyword classifier** (deterministic scorer, V1)

Whitelist override on bank/legal/internal domains.

## 2. Why now

Block 2 Cat 6 close 2026-04-26 surfaced:
- 63 active deadlines in `deadlines` table
- 42 from `source_type='email'`
- **25 of 42 = noise** (signal-to-noise ~40%)
- 17 of 42 = real signal (ops, payments, meetings)

Director triaged 25 noise items into bulk-dismiss. Fix lands at extractor-level so it doesn't recur.

## 3. Architecture

| Layer | Filter | Action |
|---|---|---|
| L1 | Sender domain blocklist (regex) | Drop deadline at extraction; no LLM call; log to `deadline_extractor_suppressions` |
| L2 | Subject/body promotional keyword scorer | Drop OR downgrade to `priority=low` for Director review |

L1 = cheap. L2 = deterministic keyword scorer first (Director Q2 default).

**Whitelist (overrides both layers):**
- Bank/legal counterparty domains: gantey.ch, eh.at, merz-recht.de, peakside.com (extend per known counterparty list)
- Internal Brisen: brisengroup.com, mohg.com
- Vendor ops with legit deadlines: notion.com (terms), slack.com (renewal)

## 4. Director Q's — defaulted

| Q | Default applied |
|---|---|
| Q1: L1 blocklist scope? | **Harvest from history of 25 dismissed Cat 6 items** (anchor data §10) **+ Director-review of harvested list via Triaga HTML before deploy** |
| Q2: L2 deterministic vs LLM? | **Deterministic keyword scorer V1; revisit if precision <90% after 30 days** |
| Q3: Whitelist by domain or sender? | **Domain-level** |

## 5. Code Brief Standards

1. **API version:** N/A — internal classifier work in `email_pipeline`. Verify `triggers/email_trigger.py` + `orchestrator/deadline_manager.py` signatures stable at build start.
2. **Deprecation check:** confirm `deadline_manager.extract_deadlines()` signature unchanged 2026-04-26.
3. **Fallback note:** if L1+L2 over-filter, dashboard override per row + audit log enables tuning.
4. **DDL drift check:** new audit table `deadline_extractor_suppressions`. Grep `store_back.py` for any pre-existing `_ensure_deadline_extractor_*_base` bootstrap before migration. Verify type match.
5. **Ship gate:** literal `pytest` output. Tests for L1 blocklist (3 cases: blocked / allowed / whitelist-override), L2 scorer (3 cases: high score drop / mid-score downgrade / low-score allow).
6. **Test plan:** see §7.
7. **file:line citations:** verify every `email_trigger.py:N` and `deadline_manager.py:N` cite by reading the file.
8. **Singleton pattern:** N/A — no canonical-singleton classes touched.
9. **Post-merge handoff:** if a backfill script runs against existing deadlines table to re-classify, include `git pull --rebase origin main` immediately before invocation.
10. **Invocation-path audit (Amendment H):** N/A — no Pattern-2 capability touched.

## 6. Definition of done

- [ ] L1 sender blocklist deployed; audit-log table `deadline_extractor_suppressions` (sender, subject, dropped_at, layer, reason)
- [ ] L2 keyword classifier with tunable threshold; default tuned to maintain recall on 17 real-signal samples from Cat 6
- [ ] Whitelist override (domain-level) for bank/legal/internal
- [ ] Backfill audit: re-run extractor on last 30 days of email signals; emit suppression rate report
- [ ] Acceptance test: manual review of 50 most-recent suppressions confirms ≤10% false-positive rate
- [ ] Triaga HTML for Director review of L1 harvest list before deploy

## 7. Test plan

```
pytest tests/test_deadline_extractor_quality.py -v
# expect: ≥6 cases (L1 blocked / allowed / whitelist-override; L2 high/mid/low-score)
pytest tests/ 2>&1 | tail -3
# expect: full-suite no regressions vs baseline
```

Plus literal SELECT verifying `deadline_extractor_suppressions` rows on a test ingest run.

## 8. Out of scope

- Promotional content classification beyond deadlines
- Sender reputation system (one-strike sufficient V1)
- Cross-source noise (Slack/WhatsApp deadline extractors — separate briefs)

## 9. Promotion + dispatch path

- AI Head Tier B promotes spec → this brief.
- Pre-build: AI Head harvests sender domains from 25 dismissed Cat 6 items (§10) → Director-approve list via Triaga HTML.
- Dispatch to B1 (idle, non-trigger-class).
- B1 builds, ships PR.
- AI Head solo review (low trigger-class).

## 10. Anchor data — Cat 6 dismissed items (L1 harvest source)

- 1424, 1469, 1465, 1467, 1475, 1397, 1477, 1447, 1476, 1442, 1454, 1455, 1478, 1481, 1427, 1464, 1420, 1482, 1483, 1473, 1479, 1429, 1449, 1468, 1396

## 11. Risk register

| Risk | Mitigation |
|---|---|
| Over-filter (drops real signal) | Audit log of every suppression; Director review first 30 days |
| Sender domain renamed | L2 keyword classifier catches it even if L1 misses |
| Whitelist gap | Override-on-edit dashboard action; weekly audit of legit-but-not-whitelisted senders |

## 12. Authority chain

- Director ratification: 2026-04-26 "C" (Cat 6 close cleanup batch) + Director default-fallback 2026-04-26 ("you default. I skip")
- RA-19 spec: `_ops/ideas/2026-04-26-deadline-extractor-quality-1.md`
- AI Head Tier B: this brief + dispatch
