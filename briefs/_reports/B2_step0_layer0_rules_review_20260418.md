# KBL-B Step 0 Layer 0 Rules Draft Review (B2)

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) — Step 0 Layer 0 deterministic-filter rules review
**Reviewed:** [`briefs/_drafts/KBL_B_STEP0_LAYER0_RULES.md`](../_drafts/KBL_B_STEP0_LAYER0_RULES.md) (B3, commit `6341b94`, 527 lines)
**Cross-referenced:** §4.1 I/O contract; SLUGS-1 design pattern; D3 §247 ratification
**Date:** 2026-04-18
**Time spent:** ~35 min

---

## 1. Verdict

**READY** with 6 should-fix items — none structural, all addressable in ~45 min of revision. The bones are right: empirical grounding is solid (8 cited signals from the 50-signal eval + 1 WA + 1 meeting), the dispatcher architecture is clean, the safety-mechanism layering (VIP override → topic override → scan never-drop → rule walk) is the right shape.

The most important architectural call (rules-as-data YAML) is correct in form but wrong in location: B3 puts it in `baker-master/kbl/config/`, not `baker-vault/`. SLUGS-1 set the precedent for ops-tunable config in the vault. Same shape, same arguments — the rules belong there too.

---

## 2. Blockers

**None.**

---

## 3. Should-fix

### S1 — YAML location: `baker-vault/`, not `baker-master/kbl/config/`

**Location:** §1 ("Proposed file layout"), §4 (loader path).

B3 proposes `kbl/config/layer0_rules.yml` inside baker-master. SLUGS-1 (ratified) put `slugs.yml` in **baker-vault** for exactly the reasons B3 cites:
- Director-editable without code-review ceremony
- Diff-reviewable in PRs
- No baker-master code redeploy on edit
- Already pulled by Mac Mini via Dropbox-mirror cron (KBL-A)

If layer0 rules live in baker-master, edits require: PR → CI → Render redeploy → Mac Mini re-pull. If in baker-vault: PR → vault re-pull (already automated). The latter matches both the architectural precedent AND the operational tunability argument B3 makes in §1.

**Fix.** Move to `baker-vault/layer0_rules.yml` (root, mirrors `slugs.yml`). Loader becomes:

```python
def __init__(self):
    vault = os.environ["BAKER_VAULT_PATH"]
    data = yaml.safe_load(Path(vault).joinpath("layer0_rules.yml").read_text())
```

Same `version: N` versioning pattern as SLUGS-1. Same VIP-of-the-loader (`SlugRegistryError`-style fail-loud on missing/malformed).

### S2 — `baker_self_analysis_echo` pattern is too generic

**Location:** §1 rules block, lines 150-163.

The rule fires on phrases like `"I asked Baker"`, `"Baker responded:"`, `"Baker's analysis:"`. These are natural-language phrases that legitimate human content uses:

- A team member emailing about Baker bug reports: *"I asked Baker about X and the result was wrong"* → **dropped**.
- Director writing a meeting note: *"Baker's analysis: we should consider Y"* → **dropped**.
- An external advisor referencing Baker outputs: *"per Baker's analysis from last week..."* → **dropped**.

All three are real signals about Baker (high signal value, especially for Director's awareness of system behavior). The rule misses by being phrase-based rather than provenance-based.

**Fix options:**

- **(a)** Anchor on Baker's actual storage-layer prefix. Baker's `decisions` table writes content with a stable marker (e.g., `baker_scan:` from B3's list, or a frontmatter `<!-- baker-output -->` comment). Match ONLY on that marker. Generic phrases dropped.
- **(b)** Hash-match against `decisions` table content. If the signal's normalized content matches (>95% jaccard) any row in `decisions` written within 30 days, drop. More robust but requires DB call in Layer 0 (vs B3's pure-Python aim).
- **(c)** Combine: keep `baker_scan:` marker as the primary phrase, drop the generic ones.

I lean (a) — single canonical Baker-output marker, matched literally, no false-positive risk.

The current §2.4 example confirms the issue: B3 acknowledges "I asked Baker how he sees himself" SHOULD drop (Director quoting Baker back) but says "I asked Baker about Mac Mini password" (legitimate IT question) should NOT drop. The rule as-written fires on **both**. The current spec relies on the Director's intent being inferable from "echoes" wording — it isn't.

### S3 — Topic-override (§3.2 invariant #4) misses slug aliases AND has 2-letter false-match risk

**Location:** §3.2 invariant #4, §4 `_mentions_active_slug` implementation.

Two sub-issues:

**(a) Aliases are ignored.** The implementation only checks `slug.split("-")[0]` — first word of slug syntax. So:
- `mo-vie` → checks "mo" only (FALSE-match risk: "mo" is a common 2-letter token in many languages including Italian "*mo* (now)", many English forms)
- `kitzbuhel-six-senses` → checks "kitzbuhel" only
- `hagenauer-rg7` → checks "hagenauer" ✓ (works)

Real risk: an email from `newsletters@arabianbusiness.com` covering "Mandarin Oriental Vienna" mentions "Mandarin" and "Vienna" but NOT "mo" as a whole word. The topic-override fails to fire → rule drops the email → signal lost.

**Fix.** Use `slug_registry.aliases_for(slug)` to get all aliases and match each as whole-word. For `mo-vie`, aliases include `["movie", "mo vienna", "mandarin", "mandarin oriental", "mo-vienna", "mohg"]` — much richer match surface.

**(b) 2-letter slugs are danger-prone.** `ao` (Andrey Oskolkov) and short slugs like `mrci` are dictionary-substring risks. `\bao\b` matches in many natural-text contexts (e.g., a French sentence). Special-case 2-letter slugs to require additional context (sender domain, subject line containing person's full name, etc.) OR exclude from topic-override entirely and rely on alias-based match (`oskolkov`, `andrey oskolkov`).

I lean: use aliases for all slugs (S3a), and for slugs whose canonical token is <4 chars, REQUIRE alias match (no canonical-only).

### S4 — VIP soft-fail-OPEN reasoning is incorrect

**Location:** §5 failure-modes table, "VIP list unavailable" row.

B3 says: *"Soft-fail open: log WARN, treat as not-VIP. Better to under-protect than to stall the pipeline. Step 1 will still be a backstop."*

**The reasoning is wrong.** Layer 0 drops are TERMINAL — `state='dropped_layer0'`, signal never reaches Step 1. So Step 1 cannot be a backstop. If VIP service is unreachable AND a real Wertheimer signal arrives via a blocklisted-shape sender domain, the signal is **dropped silently**. No Step 1 review.

**Fix options:**

- **(a)** Soft-fail-CLOSED: if VIP service is unreachable, treat ALL senders as VIP (i.e., let through to Step 1). Costs latency on Step 1 (LLM calls on noise) but never drops a real VIP signal. Safer.
- **(b)** Halt: if VIP service is unreachable, halt Layer 0 entirely; signals re-queue. Pipeline pauses but no signal loss. Severe for a transient lookup failure.
- **(c)** Accept the risk explicitly: keep soft-fail-OPEN but state plainly that "during VIP-service downtime, Layer 0 may drop a real VIP signal" so Director sees the trade-off.

I lean (a) — it's a safety bias toward not dropping. The cost is bounded (only fires during VIP outage, which should be rare).

The same issue applies to §5 row "Slug registry unavailable" (`_mentions_active_slug` returns False on exception → topic override doesn't fire). Same fix shape.

### S5 — `duplicate_content_hash` requires undefined storage infrastructure

**Location:** §1 rule (lines 165-172), §2.5 evidence claim, §3 metrics.

The rule depends on a "seen hash" store with 72h TTL. B3 says *"Hash storage lives in `kbl_log` or a dedicated `kbl_layer0_hash_seen` table."* Neither exists, neither is specified. Layer 0 can't ship without this.

**Fix.** Schema spec to add to the brief (§3 or §4):

```sql
CREATE TABLE IF NOT EXISTS kbl_layer0_hash_seen (
  content_hash TEXT PRIMARY KEY,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  first_signal_id INT REFERENCES signal_queue(id) ON DELETE SET NULL,
  ttl_expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '72 hours')
);
CREATE INDEX idx_kbl_layer0_hash_ttl ON kbl_layer0_hash_seen (ttl_expires_at);
```

Plus a cleanup tick (every N hours): `DELETE FROM kbl_layer0_hash_seen WHERE ttl_expires_at < NOW()`. Either as a cron job or piggybacked on `kbl-purge-dedupe.sh`.

Read-path latency: PRIMARY KEY lookup is fast; Layer 0 hot path stays sub-ms. ✓

Also: define normalization. B3 says *"sha256(normalized(raw_content)) where normalized strips whitespace variations, email signatures, and quoted-reply chains"* — but doesn't spec the normalizer. Add:

```python
def _normalize_for_hash(content: str) -> str:
    # Strip quoted reply chains (lines starting with '>')
    lines = [l for l in content.split('\n') if not l.lstrip().startswith('>')]
    # Strip common signature patterns (--, Best regards, etc.)
    text = '\n'.join(lines)
    text = re.split(r'\n--\s*\n|\nBest regards|\nBest,', text, maxsplit=1)[0]
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text
```

Without this, "Hi Dimitry,\n\nMessage." and "Hi Dimitry,\nMessage." hash differently — defeats dedupe.

### S6 — `kbl_layer0_review` sampling queue is undefined

**Location:** §3.3 ("Sampling for review").

B3 says *"every Nth drop (default N=50) is flagged for `kbl_layer0_review` queue, so Director can spot-check that rules aren't over-dropping."* No table schema, no UI, no surfacing mechanism specified.

**Fix.** Spec:

```sql
CREATE TABLE IF NOT EXISTS kbl_layer0_review (
  id SERIAL PRIMARY KEY,
  signal_id INT REFERENCES signal_queue(id) ON DELETE SET NULL,
  rule_name TEXT NOT NULL,
  sampled_at TIMESTAMPTZ DEFAULT NOW(),
  reviewed_at TIMESTAMPTZ,
  director_verdict TEXT CHECK (director_verdict IN ('correct_drop', 'false_drop', NULL))
);
```

Director surfacing: KBL-C dashboard widget showing N pending reviews. Director marks `correct_drop` (rule stays) or `false_drop` (triggers rule audit).

Without this, the "live sampling beats offline eval" promise is unfulfilled. Sampling without review = noise.

---

## 4. Nice-to-have

### N1 — Hardcoded meeting-quality thresholds should be env-tunable

`min_words=50`, `max_unknown_speaker_ratio=0.8`, `min_unique_tokens_ratio=0.3` are baked into the YAML. Per B3's §6.4: *"parameters are first-pass; live data may show tighter/looser is right."* Promote to env vars (or YAML-overridable per-rule) so retuning doesn't require a YAML PR per parameter twiddle. Optional — the YAML PR path is cheap.

### N2 — Personal-email override list is single-string

`personal_address: vallen300@gmail.com` is a single value. Director may have other personal emails (ProtonMail, iCloud, family domain). Make it a list:

```yaml
personal_addresses:
  - vallen300@gmail.com
  - <other@protonmail.com>  # if any
```

Cosmetic — current Director setup may not need others.

### N3 — "Idempotency" claim in §7 is imprecise re: duplicate_content_hash

Task Q7 asks: *"Confirm no hidden state."* `duplicate_content_hash` rule **has** state (the `kbl_layer0_hash_seen` store). Same content fed twice → first passes, second drops. NOT idempotent in the strict pure-function sense.

**Fix.** Reword the §5.1 invariant to: *"Rules are deterministic GIVEN the current state of the seen-hash store."* The distinction matters for testing (unit tests must seed/reset the store).

### N4 — Rule ordering by drop-rate would be a micro-perf win

B3 notes in §6.6: ordering by expected drop-rate (most-common first) is *"not material at 50-signal scale; material at 50k. Defer."* Agree — deferring is right.

### N5 — `version` bump policy unspecified

YAML has `version: 1`. SLUGS-1 sets the precedent: *"version bumps on any non-cosmetic change."* Mirror that. Otherwise `version` becomes meaningless.

---

## 5. Gaps flagged (rules that arguably should exist but don't)

### G1 — Calendar-invite auto-generated emails

`.ics`-attachment emails from Google/Outlook calendars get triaged through Step 1 but are pure metadata noise (they map to calendar events that the calendar sentinel already handles). Pattern: `Content-Type: text/calendar` header, or `multipart/mixed` with `application/ics` part.

Operational case for adding: dedupes calendar-event traffic between Email and Calendar sentinels. Not a 50-signal-corpus visible issue but predictable in live operation.

**Recommendation.** Add as a `email_calendar_invite_only` rule, low priority (post-launch when telemetry shows count).

### G2 — Director's outbound email re-ingestion

If Director sends an email and the sentinel later picks it up (e.g., from sent-folder sync, or a CC-reply chain echoing it back), it's noise — Director already knows what they wrote. Pattern: `From:` matches Director's address.

B3 mentions this in §6.5 ("Director quoted in own content — self-reference echo") and punts it to trigger-layer dedupe. Reasonable, but noting the gap so it's not lost when KBL-C ingestion updates land.

**Recommendation.** Defer to trigger-layer dedupe per B3. Flag for cross-team awareness.

### G3 — Empty-body emails with attachments-only

"See attached" emails where the body is 1-2 lines and the actual signal is the PDF/Word attachment. Layer 0 doesn't extract attachments (out of scope). Some are real (contracts, drawings), most are admin (invoices, statements).

Pattern overlaps with `email_sender_local_part_patterns` (statements/billing/invoice prefixes already caught). Plain-body-only-attachment from a known-business sender is real — keep it.

**Recommendation.** No new rule. Existing local-part patterns + sender domain blocklist cover the noise subset.

---

## 6. Architectural notes — rules-as-data YAML

### What's right

- **YAML over hardcoded constants.** Director-edit path is the killer feature; matches SLUGS-1 + KBL-A `env.mac-mini.yml` precedent.
- **Dispatcher pattern** (`rule['type']` → handler function). Clean, testable, extensible. New rule type = add YAML entry + one handler function. No core dispatcher touch.
- **First-match semantics.** Simple to reason about. Order in YAML = drop attribution. Drop decision is invariant to ordering (any match drops); ordering is for `rule_name` observability only.
- **Versioning at top level** (`version: 1`). Mirror SLUGS-1 — bump on non-cosmetic change (S5 above).
- **`source: '*'` for cross-source rules.** Clean abstraction; the dispatcher handles routing. ✓
- **Per-rule `detail` field** for log payload. Operational diagnosis without grepping code.

### What's wrong

- **Location: baker-master, should be baker-vault** (S1 above). Architectural pattern consistency.
- **Loader is hand-rolled** (line 290 sketch). Should follow the SLUGS-1 `slug_registry` pattern: module-level cache with `threading.Lock`, `reload()` API, fail-loud on missing/malformed YAML, `Layer0RulesError(RuntimeError)` exception class.
- **Schema validation absent.** SLUGS-1's loader validates shape (matters list, status enum, etc.). Layer 0 needs equivalent: every rule must have `name`, `source`, `type`; rule `type` must be in known-handlers; per-type required fields enforced. Without it, a typo-ridden YAML at deploy time is a footgun.

### What's missing

- **Hot-reload story.** SLUGS-1 has `reload()` to drop the cache. Layer 0 should match — Director edits YAML → SIGHUP or per-tick re-load picks it up without process restart. Spec the reload semantics.
- **Test fixtures.** SLUGS-1 ships `tests/fixtures/vault*/slugs.yml` for unit tests. Layer 0 should mirror: `tests/fixtures/layer0_rules_*/layer0_rules.yml` for happy-path, malformed, unknown-rule-type, etc.

---

## 7. Confirmations — §4.1 contract compliance + empirical basis

### Contract compliance (§4.1)

| §4.1 requirement | B3 spec | Status |
|---|---|---|
| Reads `source`, `raw_content`, `sender`, `recipients`, `chat_id`, `subject` | Yes (per-rule, source-dependent) | ✓ aligned (modulo B2's prior B3 finding that some live in `payload` JSONB — flagged in `B2_kbl_b_phase2_review`) |
| Writes `state='done'` (pass) OR `state='dropped_layer0'` (terminal) | §4 dispatcher returns `("pass", "")` or `("drop", rule_name)`; integration in §4 advances stage or marks dropped | ✓ |
| Ledger: zero rows (no LLM call) | §5.1 explicitly: "no `kbl_cost_ledger` row emitted" | ✓ |
| Log: on drop only; `component='layer0'`, `level='INFO'`, message=rule | §3.3 specifies | ✓ |
| Invariant: signal never re-enters Step 0 | §5.1 explicit | ✓ |

All five §4.1 contract elements covered.

### Empirical basis

| Source | Cited drops | Director label match | Drop rate |
|---|---|---|---|
| Email | 8/25 specific signals (§2.1) | All 8 = null/routine ✓ | 32% |
| WhatsApp | 1/15 (§2.2) | personal/routine ✓ | 7% |
| Meeting | 1/10 (§2.3) | null/routine ✓ | 10% |
| **Aggregate (50-signal eval)** | 10/50 | All 10 ✓ | **20%** |

20% matches D3 §247 lower bound (10-30%). Empirically sound. Each cited signal has a specific `signal_id` traceable to the labeled eval set — not vibes-based.

### Test plan (§8)

7 specific test cases covering positive (rule fires), negative (rule doesn't fire on similar input), escape-valve (VIP / topic / scan override). Format is right; per-rule coverage is sufficient for v1.

---

## 8. Summary

- **Verdict:** READY (with should-fix).
- **Blockers:** 0.
- **Should-fix:** 6 (YAML location → vault; baker-self-echo too generic; topic-override misses aliases + 2-letter slug risk; VIP soft-fail-OPEN reasoning wrong; duplicate-hash storage undefined; review-queue undefined).
- **Nice-to-have:** 5.
- **Gaps flagged:** 3 (calendar invites; outbound re-ingestion; attachments-only emails) — all defer.
- **Architectural notes:** YAML+dispatcher shape is right; loader should mirror SLUGS-1 (lock/cache/reload, schema validation, fail-loud); test fixtures should mirror SLUGS-1 layout.
- **§4.1 contract compliance:** 5/5 ✓
- **Empirical basis:** sound; 10/50 cited drops all Director-labeled noise; 20% aggregate matches D3 §247.

Drop-rate target (20-30%) is realistic. Risk surface is well-bounded by the safety-mechanism stack (scan never-drop > VIP > topic > rule walk). The 6 should-fix items are tactical, not architectural — expect ~45 min of brief revision + 2-3 hours of code implementation.

Move the YAML to baker-vault (S1) and you've also pre-resolved the Director-edit-flow question that would otherwise come up post-launch.

---

*Reviewed 2026-04-18 by Code Brisen #2. Cross-checked against §4.1 in `briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md`, SLUGS-1 (`baker-vault/slugs.yml` + `kbl/slug_registry.py`), and D3 §247 in `briefs/DECISIONS_PRE_KBL_A_V2.md`. No code, no rule authoring — pure rule-spec review.*
