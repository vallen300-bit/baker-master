# KBL-B Step 0 — `layer0` Deterministic Filter Rules

**Author:** Code Brisen 3 — empirical lead (v1/v2/v3 evals, 50-signal corpus)
**Task:** `briefs/_tasks/CODE_3_PENDING.md` (2026-04-18 dispatch #5)
**Pipeline position:** Step 0 of 8 — runs before any LLM call
**§4.1 contract:** writes `state='done'` (pass) or `state='dropped_layer0'` (drop). Log on drop only. Zero LLM cost.
**Estimated drop rate:** 20-30% of signal volume (per §2 ratified figure)

---

## 1. Design — rules-as-data, not code

**Proposal:** rules live in `kbl/config/layer0_rules.yml`, loaded at startup into a `Layer0RuleSet` object. Python-side filter is a pure dispatcher: walk rules in order, first match returns (`dropped`, rule_name).

**Why YAML:**
- Non-engineer tunability — Director can add a sender to the blocklist without a code push.
- Easier to diff and review rule changes in PRs.
- Rule metrics (drop counts per rule per day) flow into `kbl_log` keyed by `rule_name` — queryable without grepping code.

**Proposed file layout:**

```yaml
# kbl/config/layer0_rules.yml
version: 1
updated_at: 2026-04-18

# Drop order — rules evaluated top-to-bottom, first match wins.
# "source: *" means applies to all sources; other values are email/whatsapp/meeting/scan.
#
# Each rule emits exactly one kbl_log row on fire:
#   component='layer0', level='INFO',
#   message=f"dropped: {rule_name} ({detail})"
# The `detail` field is per-rule — see below.

rules:
  # ── Email noise — newsletter / transactional sender patterns ─────────
  - name: email_sender_blocklist_domains
    source: email
    type: email_sender_domain_contains
    match_any:
      - sailthru.com
      - amazonses.com
      - e.newyorktimes.com
      - mail.anthropic.com        # Anthropic invoice receipts
      - mail.eg.expedia.com
      - newsletter.thetimes.com
      - newsletters.arabianbusiness.com
      - pcloud.com
      - linkedin.com              # LI notifications (not InMail from known contacts)
      - substack.com
      - mailchi.mp                # Mailchimp short domain
      - list-manage.com           # Mailchimp campaign
      - mailer.constant-contact.com
    detail: "sender domain matches known newsletter/transactional list"

  - name: email_sender_local_part_patterns
    source: email
    type: email_sender_local_part_matches
    patterns:
      - '^(no[-_.]?reply|noreply)'
      - '^(newsletter|newsletters)'
      - '^(marketing|promo|promotions|offers|deals)'
      - '^(invoice|statements|billing|receipt|receipts)'
      - '^(team|hello|support)@'   # careful — some real contacts use these; see escape-valve
      - '^notifications?@'
    detail: "sender local-part indicates automated bulk mail"

  - name: email_unsubscribe_header_present
    source: email
    type: email_header_present
    headers: ["List-Unsubscribe", "Precedence"]
    precedence_values: ["bulk", "list", "junk"]
    detail: "RFC 2369 List-Unsubscribe or Precedence: bulk set"

  - name: email_to_personal_gmail_only
    source: email
    type: email_to_personal_gmail_only
    # Fires when recipient list is ONLY vallen300@gmail.com (no business address).
    # Catches commercial lists that hit Director's personal gmail but not his
    # business address. Business signals CC the business email.
    personal_address: vallen300@gmail.com
    business_addresses:
      - dvallen@brisengroup.com
      - office.vienna@brisengroup.com
    detail: "recipient list is personal-only (no business address)"

  # ── WhatsApp noise ───────────────────────────────────────────────────
  - name: wa_status_broadcast
    source: whatsapp
    type: wa_chat_id_suffix
    suffixes:
      - "status@broadcast"     # WA status ring
    detail: "WhatsApp status-ring broadcast (not a DM or group)"

  - name: wa_automated_number_blocklist
    source: whatsapp
    type: wa_sender_phone_in
    # Confirmed automated/service numbers. Populate from ops experience.
    # Placeholder entries — Director + Dennis to fill.
    numbers:
      # - "+41 12 345 67 89"   # example: bank OTP
      # - "+43 ...            # example: airline boarding
    detail: "sender is in known-automated number blocklist"

  - name: wa_minimum_content_length
    source: whatsapp
    type: content_min_chars
    threshold: 4
    detail: "message body under 4 characters (ok, 👍, .)"

  - name: wa_attachment_only_image_no_caption
    source: whatsapp
    type: wa_attachment_shape
    rule: "image_only_no_caption"
    # Image forwards with no caption — likely meme/forward, no business content.
    # Exception: preserve if sender is on VIP allowlist (see §3.3).
    detail: "image attachment with no caption, sender not VIP"

  # ── Meeting transcripts ──────────────────────────────────────────────
  - name: meeting_duration_min
    source: meeting
    type: meeting_duration_min_seconds
    threshold: 180       # 3 min
    detail: "meeting <3 min — accidental start or test"

  - name: meeting_transcript_quality_floor
    source: meeting
    type: meeting_transcript_quality
    # Rejects transcripts that look like ASR failure.
    min_words: 50
    max_unknown_speaker_ratio: 0.8   # if >80% lines are "Unknown:" speaker
    min_unique_tokens_ratio: 0.3     # if <30% unique tokens, likely repeated junk
    detail: "transcript ASR quality floor not met"

  - name: meeting_single_participant_solo
    source: meeting
    type: meeting_single_participant
    # Single-participant recordings with no actual dictation content
    # (content mostly silence, monologue filler, or ASR noise).
    require_also:
      - content_min_chars: 200
    detail: "single participant, low content — solo test recording"

  # ── Scan queries ─────────────────────────────────────────────────────
  # RULE: scan queries are NEVER dropped at Layer 0. Director asked for it,
  # Director gets it processed. This is §2 ratified and is NOT configurable.
  # No rules in this section intentionally.

  # ── Cross-source: Baker self-analysis dedupe ────────────────────────
  - name: baker_self_analysis_echo
    source: "*"
    type: content_contains_any
    # Director asks Baker a question → Baker stores the answer. If that
    # answer re-enters the signal pipeline (e.g., Baker's output is
    # quoted back in a WhatsApp), it would be re-classified + re-synthesized.
    # This rule catches Baker's own output echoing back.
    phrases:
      - "I asked Baker"
      - "Baker responded:"
      - "Baker's analysis:"
      - "stored decision:"
      - "baker_scan:"              # Baker's own stored_decisions prefix
    detail: "content echoes Baker's own prior analysis"

  - name: duplicate_content_hash
    source: "*"
    type: content_hash_seen_within_hours
    window_hours: 72
    # Hash = sha256(normalized(raw_content)) where normalized strips
    # whitespace variations, email signatures, and quoted-reply chains.
    # Bulk forwards + re-shares of the same Bloomberg article get one entry.
    detail: "identical normalized content seen within 72h window"

  - name: matter_wiki_back_reference
    source: "*"
    type: content_path_reference
    # If a signal's raw_content is largely composed of a file path like
    # wiki/hagenauer-rg7/<something>.md followed by the file's own contents,
    # it's Baker quoting its own wiki entry — not new information.
    path_prefix: "wiki/"
    min_quoted_fraction: 0.5
    detail: "content is a self-quote of vault content"
```

---

## 2. Empirical basis — what I saw in 50-signal corpus

### 2.1 Email drops (what these rules catch in the labeled set)

| Signal ID | Sender | Would fire rule | Director label |
|---|---|---|---|
| `0101019d71dd52ef-...@us-west-2.amazonses.com` | `invoice+statements@mail.anthropic.com` | `email_sender_blocklist_domains` (mail.anthropic.com) | null / routine ✓ |
| `1964a26249bc2c0c` | `team@pcloud.com` | `email_sender_blocklist_domains` (pcloud.com) | null / routine ✓ |
| `1975e7d294e34a34` | `newsletters@arabianbusiness.com` | `email_sender_local_part_patterns` + `email_sender_blocklist_domains` | null / routine ✓ |
| `1981a5b34a9b24c7` | `mail@eg.expedia.com` | `email_sender_blocklist_domains` (mail.eg.expedia.com) | null / routine ✓ |
| `198bf7246fa5649b` | `newsletters@arabianbusiness.com` | same | null / routine ✓ |
| `1993d6b3a1dda25a` | `nytimes@e.newyorktimes.com` | `email_sender_blocklist_domains` (e.newyorktimes.com) | null / routine ✓ |
| `1999a3807914bdde` | `newsletters@arabianbusiness.com` | same | null / routine ✓ |
| `20260415010106...@sailthru.com` | `noreply@newsletter.thetimes.com` | `email_sender_blocklist_domains` (newsletter.thetimes.com) + local-part | null / routine ✓ |

**8 email signals droppable at Layer 0 with high confidence. All 8 correctly labeled `null`/`routine` by Director → safe to drop. That's 8/25 emails = 32% of email volume dropped at zero cost before Step 1.**

### 2.2 WhatsApp drops

| Signal ID | Pattern | Would fire rule | Director label |
|---|---|---|---|
| `whatsapp:false_status@broadcast_A5ACEFDC...` | `status@broadcast` chat ID | `wa_status_broadcast` | personal / routine ✓ |

Only 1 confirmed WA drop in the 50-signal set. Rate may be higher in live corpus — status broadcasts are opt-in per contact and scale with follower count. `wa_minimum_content_length` + `wa_automated_number_blocklist` are speculative until live data available.

### 2.3 Meeting drops

| Signal ID | Pattern | Would fire rule | Director label |
|---|---|---|---|
| `meeting:01KJB66KQWSFF5TP65QD1QHD8P` | 16-min meeting, transcript is `"Unknown: Hello, tax listener. Unknown: Ikbukata. Unknown: Onskazto..."` — 100% "Unknown:" speakers + garbled ASR | `meeting_transcript_quality_floor` (max_unknown_speaker_ratio) | null / routine ✓ |

1 meeting drop in the 50-signal set. The transcript quality heuristic is important — this signal was a **persistent-across-all-evals-both-models vedana+matter miss** because Gemma/Qwen couldn't make sense of the ASR output. Dropping at Layer 0 saves 2× Step 1 + Step 3 LLM calls per run.

### 2.4 Baker self-analysis echoes

| Signal ID | Pattern | Would fire rule | Director label |
|---|---|---|---|
| `whatsapp:true_120363419098188402@g.us_3B51EA5A97CEB97FA5BE` | "I asked Baker how he sees himself..." | `baker_self_analysis_echo` | baker-internal / routine ✓ |
| `whatsapp:true_420774323982@c.us_3B330BA027F3346C5809` | Russian message asking about Mac Mini password | would NOT fire — this is Director-to-IT comms, legitimate baker-internal but not self-echo | baker-internal / routine |

First signal is a textbook self-analysis echo → drop. Second is legitimate operational content → keep (will get triaged to baker-internal matter, routine vedana, low score → inbox route).

**Important design note:** `baker_self_analysis_echo` targets the specific "I asked Baker / Baker responded" quoting pattern, NOT all baker-internal content. Legitimate baker-internal signals (IT admin questions, bug reports, Director testing Baker) must flow through the full pipeline so they land in `wiki/baker-internal/` with proper synthesis.

### 2.5 Dedupe evidence

B3's stand-down note flagged: "Recent B3 labeling surfaced 7 duplicates in 50 signals — real problem" (per KBL-B §2 Step 0 line 72). These are near-duplicates of Baker's own analyses re-entering via email threading or WhatsApp re-shares.

`duplicate_content_hash` (72-hour window, normalized text) addresses this without being source-specific. Hash storage lives in `kbl_log` or a dedicated `kbl_layer0_hash_seen` table (low-cardinality, short TTL).

---

## 3. Safety mechanisms

### 3.1 Escape-valve: VIP sender override

A **sender allowlist** (populated from `baker.vip_contacts` table) takes priority over the blocklist. If an email from a blocklisted domain comes from a VIP (e.g., `wertheimer@chanel-sfo.com`), it passes Layer 0 regardless of other rules.

Implementation: before evaluating drop rules, check `Layer0RuleSet.is_vip_sender(payload)`. If yes, skip directly to Step 1.

Rationale: false positives here are career-limiting. Dropping a real Wertheimer approach because it came from a Mailchimp-routed domain would be catastrophic. VIP override is cheap and scoped.

### 3.2 Never-drop invariants

These conditions NEVER trigger Layer 0 drop regardless of rule matches:

1. `source='scan'` — Director's direct query, always passes.
2. Sender email ∈ `baker.vip_contacts.email` — VIP override (§3.1).
3. Signal already has a `primary_matter` annotation from the ingestion layer (rare — some triggers pre-tag).
4. Signal's raw_content contains any slug from `kbl.slug_registry.active_slugs()` AS a whole word (e.g., "Hagenauer", "Cupial"). If a blocklisted-sender email mentions "Hagenauer" in its subject, it's likely a news article directly relevant to a matter — let Step 1 decide.

Invariant #4 is the "topic override" — it partially relaxes the sender blocklist for on-topic content. Newsletters CAN carry on-topic news (e.g., Arabian Business covers MO Vienna). Keep those for Step 1.

### 3.3 Observability

Every Layer 0 drop MUST emit a `kbl_log` row with:
- `component='layer0'`
- `level='INFO'`
- `message=f"dropped: {rule_name} ({detail})"` — detail is rule-specific
- Reference to `signal_id` so corpus-level analysis can reconstruct distributions

**Corpus-level metric to watch:** drop rate per rule per day. Rule that starts firing more often may need tightening; rule that stops firing may be obsolete. Dashboard widget in Sentinel Layer 1.

**Sampling for review:** every Nth drop (default N=50) is flagged for `kbl_layer0_review` queue, so Director can spot-check that rules aren't over-dropping. This is the D1 version of "unit tests in production" — live sampling beats offline eval for deterministic rules.

---

## 4. Implementation sketch

**File:** `kbl/steps/layer0.py`

```python
from pathlib import Path
from typing import Literal

import yaml

from kbl.signal_types import SignalRow
from kbl.slug_registry import active_slugs
from baker.vip_contacts import is_vip_sender


class Layer0RuleSet:
    def __init__(self, config_path: Path):
        data = yaml.safe_load(config_path.read_text())
        self.version = data["version"]
        self.rules = data["rules"]

    def evaluate(self, signal: SignalRow) -> tuple[Literal["pass", "drop"], str]:
        # Never-drop invariants first
        if signal.source == "scan":
            return ("pass", "")
        if is_vip_sender(signal.payload):
            return ("pass", "")
        if signal.payload.get("primary_matter_hint"):
            return ("pass", "")
        if _mentions_active_slug(signal.raw_content, active_slugs()):
            return ("pass", "")

        # Walk rules top-to-bottom, first match wins
        for rule in self.rules:
            if rule["source"] not in ("*", signal.source):
                continue
            if _rule_matches(rule, signal):
                return ("drop", rule["name"])

        return ("pass", "")


def _rule_matches(rule: dict, signal: SignalRow) -> bool:
    """Dispatch on rule['type'] — each type is a small pure function."""
    rule_type = rule["type"]
    dispatcher = _RULE_DISPATCHERS.get(rule_type)
    if dispatcher is None:
        raise ValueError(f"unknown layer0 rule type: {rule_type}")
    return dispatcher(rule, signal)


# Type handlers — small, testable, no I/O.
def _match_email_sender_domain_contains(rule, signal) -> bool:
    sender = (signal.payload.get("sender") or "").lower()
    if "@" not in sender: return False
    domain = sender.split("@", 1)[1].rstrip(">")
    return any(d.lower() in domain for d in rule["match_any"])


def _match_wa_chat_id_suffix(rule, signal) -> bool:
    chat_id = signal.payload.get("chat_id") or ""
    return any(chat_id.endswith(s) for s in rule["suffixes"])


def _match_meeting_transcript_quality(rule, signal) -> bool:
    content = signal.raw_content or ""
    if len(content.split()) < rule["min_words"]: return True
    # "Unknown:" speaker ratio
    lines = [l for l in content.split("\n") if ":" in l]
    if lines:
        unknown = sum(1 for l in lines if l.strip().lower().startswith("unknown:"))
        if unknown / len(lines) >= rule["max_unknown_speaker_ratio"]:
            return True
    # Unique-token ratio
    tokens = content.lower().split()
    if tokens:
        ratio = len(set(tokens)) / len(tokens)
        if ratio < rule["min_unique_tokens_ratio"]:
            return True
    return False


# ... (one handler per type in the YAML; add as rules evolve)

_RULE_DISPATCHERS = {
    "email_sender_domain_contains":  _match_email_sender_domain_contains,
    "wa_chat_id_suffix":             _match_wa_chat_id_suffix,
    "meeting_transcript_quality":    _match_meeting_transcript_quality,
    # ...
}


def _mentions_active_slug(content: str, slugs: list[str]) -> bool:
    import re
    body = (content or "").lower()
    for slug in slugs:
        # Whole-word match on slug + main alias (e.g., "hagenauer", "cupial")
        primary_word = slug.split("-")[0]
        if re.search(rf"\b{re.escape(primary_word)}\b", body):
            return True
    return False
```

**Integration point:** `kbl/pipeline_worker.py` at stage `layer0`:

```python
def _process_layer0(signal: SignalRow, ruleset: Layer0RuleSet) -> None:
    decision, rule_name = ruleset.evaluate(signal)
    if decision == "drop":
        signal.mark_dropped(stage="layer0", reason=rule_name)
        kbl_log(component="layer0", level="INFO",
                message=f"dropped: {rule_name}",
                signal_id=signal.id)
    else:
        signal.advance_stage(to="triage")
```

---

## 5. Expected failure modes + recovery

| Failure mode | Detection | Recovery |
|---|---|---|
| Rule YAML malformed at startup | `yaml.safe_load` raises | Pipeline refuses to start. Alert via `kbl_log` + Sentinel page. Fallback: prior-version YAML (kept in rollback slot). |
| Rule dispatcher KeyError (unknown type) | `_rule_matches` raises | Pipeline stops. Indicates YAML + code version drift. Rollback YAML or deploy new code. |
| False-positive drop (real signal rejected) | `kbl_layer0_review` sampling queue | Director flags → rule authored is soft-retired, tightened, or replaced. No auto-retry on the dropped signal (re-queueing would create infinite loops with buggy rule). Director can manually re-inject via Scan if needed. |
| False-negative pass (noise reaches Step 1) | Corpus telemetry on Step 1 `triage_score` distribution | If Step 1 keeps scoring < 20 for unfiltered signals, add new Layer 0 rule. This is the self-calibrating feedback loop. |
| VIP list unavailable (`baker.vip_contacts` query fails) | Python exception in `is_vip_sender` | Soft-fail open: log `WARN`, treat as not-VIP. Better to under-protect than to stall the pipeline. Step 1 will still be a backstop. |
| Slug registry unavailable for §3.2 invariant #4 | Exception in `_mentions_active_slug` | Soft-fail open: treat as no-mention (conservative — signals will still pass if they come from non-blocklisted senders). Log `WARN`. |

### 5.1 §4.1 invariants restated

- A signal NEVER re-enters Step 0 after exiting (per §4.1). The `stage` column advances forward-only; no re-queue of `state='dropped_layer0'` unless Director manually intervenes via Scan.
- Zero LLM cost in Step 0. No `kbl_cost_ledger` row emitted — enforced by the absence of any model call in the dispatcher.
- Drops emit exactly one `kbl_log` row. No drop emits zero rows (invisible drop = bad) and none emits more than one (noisy log).

---

## 6. Tuning — how to evolve rules post-launch

### 6.1 Metrics to track weekly

- **Drop rate per rule** — `SELECT COUNT(*) FROM kbl_log WHERE component='layer0' GROUP BY message, date_trunc('day', created_at)`. Expect long tails — a few rules do most of the work.
- **Step 1 `triage_score` distribution for NON-dropped signals** — if the lower tail thickens, Layer 0 is under-dropping.
- **Director Scan → "re-inject this" events** — any manual re-inject is a false-positive Layer 0 drop. Rule audit triggered if > 2/week.

### 6.2 When to add a rule

Rule of thumb: if a sender/pattern appears **> 5 times in `triage_score < 20` signals within a 30-day window**, promote to Layer 0. Reduces LLM cost permanently.

### 6.3 When to retire a rule

A rule that fires **< 3 times/month for 6 consecutive months** is dead weight — retire. Keep `version: 1` incrementing to track rule lifecycle.

---

## 7. Open questions for AI Head / Director

1. **VIP allowlist source of truth.** I propose `baker.vip_contacts.email` as the check. If a VIP is flagged in a different system (e.g., Linear team member), need a unified `vip_resolver()`. Defer to KBL-C or settle now?

2. **72-hour dedupe window.** Covers same-week re-shares. Could extend to 30 days for quarterly forwards, but memory cost rises. **Recommend 72h** for Phase 1, measure hit rate, extend if needed.

3. **WA automated-number blocklist bootstrap.** The 50-signal corpus has none visible. Director or Dennis (IT) should seed the list with confirmed numbers (bank OTP, airline boarding, ride-sharing, delivery services). Without the seed, this rule is dormant.

4. **Meeting transcript quality floor tuning.** Parameters (`min_words=50`, `max_unknown_speaker_ratio=0.8`, `min_unique_tokens_ratio=0.3`) are B3's first-pass. Live data may show tighter/looser is right. Recommend ship as-is, revisit after 30 days of drop-rate telemetry.

5. **Director quoted in own content — self-reference echo.** Director's own text forwarded back (e.g., Dimitry sends an email → the email client thread shows it → next sync re-includes it) — is that a Layer 0 concern or a trigger-layer dedupe concern? I've placed it in the trigger layer (dedupe by `email_message_id`). If it leaks to Layer 0, add a rule — not now.

6. **Rule evaluation ordering.** YAML order = evaluation order. Currently ordered by source (email rules first). Consider re-ordering by expected drop rate (most-common first) for a micro-perf win. Not material at 50-signal scale; material at 50k. Defer.

---

## 8. Test cases — what the first unit-test batch should cover

```python
# tests/test_layer0_rules.py

def test_email_newsletter_dropped():
    signal = email_signal(
        sender="newsletters@arabianbusiness.com",
        to=["vallen300@gmail.com"],
        subject="Daily Briefing",
    )
    assert ruleset.evaluate(signal) == ("drop", "email_sender_blocklist_domains")


def test_email_vip_override_wins_over_blocklist():
    # Wertheimer sends via a Mailchimp-routed address — must not be dropped.
    signal = email_signal(
        sender="wertheimer@mailchi.mp",
        to=["dvallen@brisengroup.com"],
        subject="Proposal",
    )
    # Pre-condition: Wertheimer is in baker.vip_contacts
    assert ruleset.evaluate(signal) == ("pass", "")


def test_email_newsletter_but_mentions_matter_passes():
    # Arabian Business covers MO Vienna — must NOT drop.
    signal = email_signal(
        sender="newsletters@arabianbusiness.com",
        raw_content="MO Vienna hotel announces new suite category...",
    )
    # Pre-condition: 'mo-vie' in active_slugs(); "vienna" or "mandarin" is a whole-word match
    # (NOTE: rule-set needs slug-keyword map — not just raw slug strings)
    assert ruleset.evaluate(signal) == ("pass", "")  # topic override


def test_wa_status_broadcast_dropped():
    signal = whatsapp_signal(chat_id="false_status@broadcast_A5ACEFDC...")
    assert ruleset.evaluate(signal) == ("drop", "wa_status_broadcast")


def test_meeting_garbled_transcript_dropped():
    signal = meeting_signal(
        duration_sec=960,  # 16 min — passes duration rule
        raw_content="Unknown: Hello, tax listener. Unknown: Ikbukata. Unknown: Onskazto..." * 10,
    )
    assert ruleset.evaluate(signal) == ("drop", "meeting_transcript_quality_floor")


def test_baker_self_analysis_dropped():
    signal = whatsapp_signal(
        raw_content="I asked Baker how he sees himself when he suggested that he should have a face."
    )
    assert ruleset.evaluate(signal) == ("drop", "baker_self_analysis_echo")


def test_scan_query_never_dropped():
    # Even a scan query saying "noreply newsletter" isn't dropped.
    signal = scan_signal(raw_content="Hey Baker, summarize the noreply newsletter from yesterday")
    assert ruleset.evaluate(signal) == ("pass", "")
```

Each rule needs: one positive (fires correctly), one negative (doesn't fire on similar-but-not-matching signal), one escape-valve test (VIP / topic / scan overrides win).

---

## 9. Deliverable summary

| Artifact | Path | Status |
|---|---|---|
| Rule YAML template | `kbl/config/layer0_rules.yml` | Draft provided in §1 |
| Dispatcher code | `kbl/steps/layer0.py` | Sketch provided in §4 |
| VIP resolver | `baker.vip_contacts` (existing) + new `is_vip_sender()` helper | TBD by code |
| Test suite | `tests/test_layer0_rules.py` | 7 test cases provided in §8 |
| Log integration | `kbl_log` with `component='layer0'` | Trivial, covered in §3.3 |
| Metrics dashboard | Sentinel Layer 1 widget | §6.1 SQL seed provided |

Drop rate target: **20-30% of total signal volume** (matches §2 ratified figure). Based on 50-signal corpus, email alone would drop ~32% (8/25). WA / meeting drops are lower-rate but lower-volume sources — overall 20-25% is realistic for Phase 1.

---

*Drafted 2026-04-18 by B3 for AI Head §6 assembly + KBL-B Step 0 implementation. No code written, no evals run. Ready for copy-paste into KBL-B §6 and for Code A/B/C to implement as a follow-up dispatch.*
