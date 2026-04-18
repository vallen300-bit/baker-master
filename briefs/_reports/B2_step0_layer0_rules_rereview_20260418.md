# Step 0 Layer 0 Rules — Re-Review post S1-S6 + C1-C2 (B2)

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) Task A-step0-rereview
**File:** `briefs/_drafts/KBL_B_STEP0_LAYER0_RULES.md` @ commit `64d1712`
**Author:** B3 (applied B2's 6 should-fix + their own 2 CHANDA clarifications, 8 items total)
**My prior review:** `briefs/_reports/B2_step0_layer0_rules_review_20260418.md` (READY with 6 should-fix)
**Diff stat:** `6341b94 → 64d1712`: +492/-81 across the file (now 938 lines)
**Date:** 2026-04-18
**Time:** ~25 min

---

## 1. Verdict

**READY.**

All 6 of my original should-fix items applied per intent. B3's two CHANDA clarifications (C1 not-an-alert + C2 Director-sender invariant) are sound additions. Test suite expanded with positive + negative cases for each new behavior. 0 blockers, 0 should-fix, 4 nice-to-have items — all documentation-drift cleanups, not architectural concerns.

The amendment package is exemplary in shape: every B2 item links to a §10 amendment-log row with explicit status + section list. Future readers can audit the trace without reading both reports side-by-side.

---

## 2. Blockers

**None.**

---

## 3. Should-fix

**None.**

---

## 4. Nice-to-have

### N1 — §3.6 schema sketch diverges from PR #5 actual `kbl_layer0_hash_seen` schema

**Location:** §3.6 lines 348-357.

B3's spec:
```sql
ttl_expires_at    TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '72 hours'),
source_signal_id  BIGINT REFERENCES signal_queue(id) ON DELETE SET NULL,
```

PR #5 actual (`migrations/20260418_loop_infrastructure.sql`):
```sql
ttl_expires_at   TIMESTAMPTZ NOT NULL,
source_signal_id BIGINT,                     -- FK to signal_queue.id (unenforced)
```

Two divergences:
- **DEFAULT on `ttl_expires_at`** — B3 sketches a 72h default; PR #5 has no default (writer must supply).
- **`REFERENCES signal_queue(id) ON DELETE SET NULL`** — B3 includes; PR #5 deliberately omits per its FK-vs-app-validation decision (CHANDA Inv 2 atomicity preserved at writer side).

**Fix.** Reconcile §3.6 with PR #5's actual schema, OR add a one-line note: *"Schema sketch above is illustrative; canonical schema in `migrations/20260418_loop_infrastructure.sql` (PR #5 — merged) — refer to migration file for production column types and constraint set."* Cosmetic but prevents B1 implementation drift if they read §3.6 first and trust it.

### N2 — §3.5 schema sketch diverges from PR #5 actual `kbl_layer0_review` schema (column names)

**Location:** §3.5 lines 311-325.

| B3 §3.5 column | PR #5 actual column |
|---|---|
| `sampled_at` | `created_at` |
| `rule_name` | `dropped_by_rule` |
| `excerpt` | `signal_excerpt` |
| `director_verdict` (CHECK) | `review_verdict` (no CHECK) |
| (omitted) | `source_kind TEXT NOT NULL` |
| `signal_id INT REFERENCES signal_queue(id)` | `signal_id BIGINT NOT NULL` (no REFERENCES) |
| `id SERIAL` | `id BIGSERIAL` |

§4 `_process_layer0()` (line 647) calls `kbl_layer0_review_insert(signal_id=..., rule_name=..., excerpt=...)` using B3's column names. Real B1 implementation must use PR #5's names. The writer-helper signature in §9 deliverables also uses B3's names.

This is broader drift than N1. The writer code in §4 is wrong against the actual table schema. B1 will discover this the moment they implement `kbl_layer0_review_insert()`.

**Fix.** Same shape as N1: align §3.5 + §4 writer call + §9 helper signature with PR #5's column names. Or add an illustrative-only disclaimer.

I lean (a) align — PR #5 is canonical and merged. Drift makes B1's implementation harder, not easier.

The B2-S6 missing CHECK on `review_verdict` is still the only outstanding tactical item (flagged in my PR #5 review). PR #5 doesn't add the CHECK; B3's draft has it in the sketch but not the canonical schema. Either path eventually adds it.

### N3 — Test count claim mismatch

§8 final paragraph: *"14 tests above cover the rule-set ratified post-S1-S6 + C1-C2 amendment."*

I count **16 test functions** in §8:

```
1. test_email_newsletter_dropped
2. test_email_vip_override_wins_over_blocklist
3. test_email_newsletter_but_mentions_matter_passes_via_alias
4. test_short_slug_canonical_only_does_NOT_match_topic_override
5. test_short_slug_alias_DOES_match_topic_override
6. test_wa_status_broadcast_dropped
7. test_meeting_garbled_transcript_dropped
8. test_baker_scan_marker_dropped
9. test_natural_language_baker_mention_does_NOT_drop
10. test_director_sender_email_never_dropped
11. test_director_sender_whatsapp_never_dropped
12. test_scan_query_never_dropped
13. test_duplicate_content_hash_drops_second_occurrence
14. test_layer0_review_sampling_writes_at_id_multiple_of_50
15. test_layer0_review_sampling_skips_at_id_NOT_multiple_of_50
16. test_vip_lookup_failure_passes_signal_through
```

Cosmetic — coverage is solid; one+positive+negative per new behavior is achieved. Just update the count.

### N4 — Director phone-format normalization required

**Location:** §3.2 invariant #5 + §4 `is_director_sender()` call.

C2 invariant lists Director's WhatsApp number as `+41 79 960 50 92`. CLAUDE.md (Director's primary memory file) records the same number as `+41 799605092` — different format (no spaces).

WhatsApp's WAHA backend serializes phone numbers as `41799605092@c.us` (no plus, no spaces, no dashes). The `is_director_sender()` helper (TBD per §9) must normalize both formats — and the underlying chat ID format used by the WA sentinel — before comparing.

**Fix.** Add a one-line note in §3.2 invariant #5 OR §9 deliverable for `is_director_sender`: *"Implementation must normalize phone numbers to digits-only before comparison (handles `+41 79 960 50 92`, `+41799605092`, `41799605092@c.us` interchangeably)."* Prevents an implementation bug where Director's own messages bounce off Layer 0 because of format mismatch.

---

## 5. S1-S6 + C1-C2 application audit

### S1 — YAML location: `baker-vault/`, not `baker-master/kbl/config/`

| Where applied | Status |
|---|---|
| Header (line 14) | ✓ "rules live in **`baker-vault/layer0_rules.yml`** (root of the vault, mirroring `slugs.yml`)" |
| §1 rationale (lines 16-19) | ✓ 3-bullet justification: SLUGS-1 precedent, no baker-master redeploy, slug_registry pattern |
| §4 loader (line 472) | ✓ `Path(vault) / "layer0_rules.yml"` reads from BAKER_VAULT_PATH |
| §9 deliverables (line 890) | ✓ "**`baker-vault/layer0_rules.yml`** (S1 — vault, not baker-master)" |

Applied per intent. Loader pattern explicitly mirrors SLUGS-1 (lock + cache + reload + fail-loud). ✓

### S2 — `baker_self_analysis_echo` anchor on `baker_scan:` prefix

| Where applied | Status |
|---|---|
| §1 rule (lines 156-177) | ✓ Type changed from `content_contains_any` to `content_starts_with_marker`. Markers: `["baker_scan:", "<!-- baker-output -->"]`. Comment block explains the false-positive concern. |
| §4 handler (lines 575-578) | ✓ `body.startswith(m)` literal prefix match |
| §8 positive test (line 794) | ✓ `test_baker_scan_marker_dropped` |
| §8 negative test (line 802) | ✓ `test_natural_language_baker_mention_does_NOT_drop` — explicitly covers the "I asked Baker about Mac Mini password" case from my original S2 example |

Applied with belt-and-suspenders: positive + negative + alt-marker reservation for `<!-- baker-output -->`. ✓

### S3 — Alias-aware short-slug match

| Where applied | Status |
|---|---|
| §3.2 invariant #4 (line 270) | ✓ Explicit description: "alias-aware. Implementation iterates `slug_registry.active_slugs()` AND `slug_registry.aliases_for(slug)` per slug. Special case: slugs whose canonical token is **<4 chars** ... REQUIRE an alias match" |
| §4 `_mentions_active_slug_or_alias` (lines 607-627) | ✓ `if len(primary_word) >= 4: candidates.append(primary_word)` — short-slug safeguard |
| §8 alias positive (line 747) | ✓ `test_email_newsletter_but_mentions_matter_passes_via_alias` — "Mandarin Oriental Vienna" → mo-vie alias |
| §8 short-slug canonical negative (line 759) | ✓ `test_short_slug_canonical_only_does_NOT_match_topic_override` — Portuguese "ao" doesn't fire |
| §8 short-slug alias positive (line 771) | ✓ `test_short_slug_alias_DOES_match_topic_override` — "Andrey Oskolkov" → ao via alias |

Cutoff semantics check: B3 uses `>= 4 chars` for canonical match (slugs of length 1-3 require alias). My original spec said "<4 chars must alias-match" — same boundary, opposite framing. ✓ aligned. (Interesting edge: `mrci` is exactly 4 chars and uses canonical match. Acceptable — `mrci` is not a common substring in any natural language I know of.)

### S4 — VIP soft-fail OPEN → CLOSED

| Where applied | Status |
|---|---|
| §5 failure-modes table — VIP row (line 677) | ✓ "**Soft-fail CLOSED (S4 fix).** Treat ALL senders as VIP for the duration of the outage". Reasoning correction explicit: "The previous 'Step 1 backstop' reasoning was wrong — there IS no backstop downstream." |
| §5 failure-modes table — slug-registry row (line 678) | ✓ Parallel: same soft-fail-CLOSED treatment for slug-registry exceptions |
| §4 `evaluate()` try/except (lines 510-518, 525-531) | ✓ Both blocks log WARN + return ("pass", "") |
| §8 test (line 871) | ✓ `test_vip_lookup_failure_passes_signal_through` — `mock_vip_lookup_raises(ConnectionError)` + assert pass |

Applied per intent. The reasoning correction is articulated, not hand-waved. ✓

### S5 — Hash-store full spec

| Where applied | Status |
|---|---|
| §3.6 schema sketch (lines 348-357) | ✓ — but see N1 above for sketch-vs-PR#5 drift |
| §3.6 hash algorithm (line 359) | ✓ `hashlib.sha256(...).hexdigest()` |
| §3.6 `normalize_for_hash` (lines 363-399) | ✓ Detailed 5-step recipe: drop quoted-reply lines, truncate at sig pattern, lowercase, collapse whitespace, strip. Pre-compiled `_SIG_PATTERNS` regex. |
| §3.6 cleanup tick (line 405) | ✓ Daily cron at 08:00 UTC, piggyback on existing `kbl-purge-dedupe.sh` OR new entry |
| §3.6 hot-path latency (line 410) | ✓ PRIMARY KEY lookup, sub-ms |
| §3.6 statefulness invariant (line 412) | ✓ "Rules are deterministic GIVEN the current state of `kbl_layer0_hash_seen`" — addresses my N3 callout |
| §4 `_match_content_hash_seen` (lines 580-586) | ✓ Calls `has_seen_recent(h)` from `kbl.layer0_dedupe` (B1 ticket) |
| §4 `_hash_normalized_content` (lines 590-594) | ✓ Imports `normalize_for_hash` from `kbl.layer0_dedupe` |
| §4 dispatcher hash insert semantics (lines 657-663) | ✓ **Insert on PASS only, not DROP.** Smart bias: a false-positive drop must not silently dedupe future legitimate copies of the same content. |
| §8 test (line 838) | ✓ `test_duplicate_content_hash_drops_second_occurrence` — first passes (hash stored), second drops |

Comprehensive. Insert-on-PASS-only is a sharp design decision worth highlighting — it's the right defensive posture for a dedupe table that interacts with Layer 0's drop logic.

### S6 — Review queue full spec

| Where applied | Status |
|---|---|
| §3.5 schema sketch (lines 311-325) | ✓ — but see N2 above for sketch-vs-PR#5 column-name drift |
| §3.5 sampling rate (line 327) | ✓ Deterministic `signal.id % 50 == 0`. Reasoning: reproducibility for tests + audit |
| §3.5 excerpt 500 chars (line 335) | ✓ With newlines preserved |
| §3.5 verdict enum (lines 337-340) | ✓ `correct_drop`, `false_positive`, `ambiguous` (matches my S6 spec) |
| §3.5 writer integration (line 342) | ✓ Same-transaction insert with signal_queue + kbl_log writes |
| §4 `_process_layer0()` sampling (lines 645-651) | ✓ Calls writer when `signal.id % 50 == 0` |
| §8 sample-fires test (line 853) | ✓ `test_layer0_review_sampling_writes_at_id_multiple_of_50` |
| §8 sample-skips test (line 864) | ✓ `test_layer0_review_sampling_skips_at_id_NOT_multiple_of_50` |

Sampling determinism is the right call — pytest can construct a signal with `id=50` and assert. Random sampling would either introduce seeded-RNG ceremony or non-deterministic tests. ✓

### C1 — "Layer 0 is NOT an alert mechanism" (CHANDA Inv 7 clarification)

**Location:** §3.4 (NEW, lines 287-303).

Reasoning summary:
- Inv 7 binds the alert layer (separate from Layer 0)
- Layer 0 silently drops by design — Director never receives per-drop notification
- 4 safety surfaces: logged (kbl_log), sampled (1-in-50 to review queue), bounded by never-drop invariants (5 of them), versioned + tunable via baker-vault YAML
- 3 explicit non-features: no per-drop notification, no per-drop approval, no LLM "wait this might matter" override

**Agree.** This is a thoughtful CHANDA-aware clarification. It pre-empts the future objection "but Inv 7 says alerts are prompts not overrides — is Layer 0 a silent override?" by explicitly distinguishing Layer 0's deterministic-filter posture from the alert-routing layer. The 4 safety surfaces give Director enough auditability + tunability that the silent-drop-by-design is bounded.

The non-features section is particularly good — it forecloses the alternative architectures explicitly so future contributors don't accidentally re-introduce them ("hey what if we added a Gemma 'second-look' check on Layer 0 drops?" — answered: no, Layer 0 has no LLM by design).

✓ Agree, no pushback.

### C2 — Director-sender never-drop invariant (Inv 5)

**Location:** §3.2 invariant #5 (NEW, line 271).

Reasoning summary:
- Email `From:` matches Director's 3 known addresses
- WhatsApp sender phone matches Director's number
- Meeting organizer matches Director's calendar
- Director-authored content NEVER Layer-0-dropped, regardless of content shape, sender domain, attachment shape

**Agree.** The case where Director sends a quick "ok" to a thread is real — `wa_minimum_content_length` would otherwise drop it. Same for "(just FYI, see attached)" emails Director forwards to themselves for archive — `email_unsubscribe_header_present` would catch the original sender's bulk-mail headers. C2 protects Director's own outbound from being noise-filtered.

Two implementation notes for the future B1 ticket:
- Phone-format normalization (see N4 above)
- Director's address list should ideally come from a config (e.g., `baker.director_identity` module) rather than hardcoded in `is_director_sender()`. If Director ever adds an address (or rotates phone), one update site, not multiple.

✓ Agree, with N4 caveat.

---

## 6. Deferred items audit

### N1 / N2 / N4 / N5 / G1 / G2 / G3 deferral rationales

| Item | B3 deferral rationale | My read |
|---|---|---|
| N1 (env-tunable meeting thresholds) | "YAML PR path is cheap enough" | ✓ agree — single PR per parameter twiddle is acceptable; revisit if telemetry shows frequent re-tuning |
| N2 (multi-personal-email list) | "Director's setup is single personal address" | ✓ agree — current state matches; expand if/when |
| N4 (rule reordering by drop-rate) | "defer per B3 §6.6 — not material at 50-signal scale" | ✓ agree — micro-perf |
| N5 (`version` bump policy) | "accepted as SLUGS-1-style" | ✓ agree — matches established convention |
| G1 (calendar-invite auto-emails) | "defer — add post-launch when telemetry shows count" | ✓ agree — predictable but not yet observed |
| G2 (Director outbound re-ingestion) | "addressed by C2 Inv 5 + trigger-layer dedupe primary, Layer 0 is the safety net" | ✓ agree — smart cross-reference; G2 is now partially solved by C2 |
| G3 (empty-body attachments-only) | "defer per B2 — existing local-part + sender domain rules cover the noise subset" | ✓ agree — true; revisit if attachments-only signals start escaping triage |

All deferral rationales sound. None reopened.

---

## 7. §9 deliverables for future B1 dispatch

The amendment list 5 helper functions for future B1 dispatch:

| Helper | Purpose | Source item |
|---|---|---|
| `is_director_sender(signal)` | C2 Inv 5 author-authority check (phone + email + meeting organizer normalization) | C2 |
| `kbl.layer0_dedupe.normalize_for_hash(content)` | S5 deterministic 5-step normalizer | S5 |
| `kbl.layer0_dedupe.has_seen_recent(hash)` | S5 read-side hash lookup | S5 |
| `kbl.layer0_dedupe.insert_hash(...)` | S5 write-side INSERT-on-PASS | S5 |
| `kbl_layer0_review_insert(signal_id, rule_name, excerpt)` | S6 sampling writer | S6 |

Plus the existing `is_vip_sender(payload)` (`baker.vip_contacts`) which is pre-existing.

**Scope captured.** Each helper has a clear interface, location, and triggering item. Ready for B1 implementation ticket.

One coordination flag: the writer-helper names in §4 / §9 (e.g., `kbl_layer0_review_insert(signal_id=..., rule_name=..., excerpt=...)`) use B3's column names, not PR #5's actual names. See N2 above. The B1 implementation ticket should explicitly call out: *"use PR #5's actual column names: `signal_id`, `dropped_by_rule`, `signal_excerpt`."*

---

## 8. Summary

- **Verdict:** READY.
- **Blockers:** 0.
- **Should-fix:** 0.
- **Nice-to-have:** 4 (§3.6 schema-vs-PR#5 drift; §3.5 schema-vs-PR#5 column-name drift; test count 14→16; phone-format normalization).
- **All 6 should-fix from prior review:** ✓ applied per intent.
- **C1 + C2 additions:** ✓ both sound; agree.
- **Deferral rationales:** ✓ all 7 reviewed; none reopened.
- **§9 deliverables:** 5 new helpers spec'd for future B1 ticket.

The amendment is mergeable. The 4 NICE items are documentation-drift cleanups that should land in a follow-up touch alongside the B1 implementation ticket — by then PR #5 schema is canonical and the drift is mechanically resolvable.

The amendment-log table at §10 is the kind of trace I want every future B3 / B1 amendment to include — explicit per-item status + section list. Future re-reviewers (B2 or otherwise) can audit without reading both the prior + current report side-by-side. Recommended as project convention.

**Pre-flag for AI Head:** when the B1 LAYER0-IMPL ticket is dispatched, include the §3.5 / §3.6 column-name reconciliation as a sub-task so the writer helpers + spec land aligned in one go.

---

*Re-reviewed 2026-04-18 by Code Brisen #2. File `briefs/_drafts/KBL_B_STEP0_LAYER0_RULES.md` @ `64d1712`. Cross-referenced against PR #5 actual schemas (`migrations/20260418_loop_infrastructure.sql`) and CLAUDE.md (Director phone format). No code changes; design re-review only.*
