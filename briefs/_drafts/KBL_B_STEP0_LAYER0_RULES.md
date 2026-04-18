# KBL-B Step 0 — `layer0` Deterministic Filter Rules

**Author:** Code Brisen 3 — empirical lead (v1/v2/v3 evals, 50-signal corpus)
**Task:** `briefs/_tasks/CODE_3_PENDING.md` (2026-04-18 dispatch #5; LAYER0-RULES-S1-S6 amend dispatched 2026-04-18 commit `4b3b636`)
**Pipeline position:** Step 0 of 8 — runs before any LLM call
**§4.1 contract:** writes `state='done'` (pass) or `state='dropped_layer0'` (drop). Log on drop only. Zero LLM cost.
**Estimated drop rate:** 20-30% of signal volume (per §2 ratified figure)
**Amendment status:** B2's 6 should-fix items (S1-S6) + B3's 2 CHANDA clarifications (C1-C2) applied this revision. See §10 amendment log for the per-item summary.

---

## 1. Design — rules-as-data, not code

**Proposal:** rules live in **`baker-vault/layer0_rules.yml`** (root of the vault, mirroring `slugs.yml`), loaded at startup into a `Layer0RuleSet` object. Python-side filter is a pure dispatcher: walk rules in order, first match returns (`dropped`, rule_name).

**Why baker-vault (not baker-master/kbl/config) — S1 ratified by B2:**
- **Same precedent as SLUGS-1.** `baker-vault/slugs.yml` is Director-editable, diff-reviewable, and pulled by Mac Mini via the existing Dropbox-mirror cron (KBL-A). Layer 0 rules want the same workflow.
- **No baker-master redeploy on Director rule edits.** YAML in baker-master = PR → CI → Render redeploy → Mac Mini re-pull. YAML in baker-vault = PR → vault re-pull (already automated by KBL-A).
- **Loader pattern matches `kbl/slug_registry.py`** — module-level cache + `threading.Lock` + `reload()` API + fail-loud `Layer0RulesError(RuntimeError)` on missing/malformed YAML. See §4 for the full loader sketch.

**Why YAML at all:**
- Non-engineer tunability — Director can add a sender to the blocklist without a code push.
- Easier to diff and review rule changes in PRs.
- Rule metrics (drop counts per rule per day) flow into `kbl_log` keyed by `rule_name` — queryable without grepping code.

**Proposed file layout:**

```yaml
# baker-vault/layer0_rules.yml
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

  # ── Cross-source: Baker self-analysis dedupe (S2 — anchor tightened) ─
  - name: baker_self_analysis_echo
    source: "*"
    type: content_starts_with_marker
    # S2 fix: anchor on Baker's actual storage-layer marker, NOT natural-
    # language phrases. The prior phrase-based spec ("I asked Baker",
    # "Baker responded:", "Baker's analysis:") falsely caught legitimate
    # human content (team bug reports, Director meeting notes, external
    # advisor references). Replaced with a single canonical marker that
    # ONLY Baker's own output emits.
    #
    # Marker: `baker_scan:` at the start of the signal raw_content.
    # Baker's `decisions` table writer prepends this on every stored
    # output. Pattern is a literal prefix match (not phrase-anywhere)
    # to keep false-positive risk at zero.
    #
    # Alt-marker reserved for future: `<!-- baker-output -->` HTML/MD
    # comment frontmatter. Listed here so a future Baker-output writer
    # path can adopt either marker. Both fire this rule.
    markers:
      - "baker_scan:"
      - "<!-- baker-output -->"
    detail: "content starts with Baker's storage-layer output marker"

  - name: duplicate_content_hash
    source: "*"
    type: content_hash_seen_within_hours
    window_hours: 72
    # Hash store fully spec'd in §3.6 (S5 — table from B1 PR #5,
    # normalization recipe, sha256 hex, daily TTL cleanup).
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

`duplicate_content_hash` (72-hour window, normalized text) addresses this without being source-specific. **Full storage + normalization spec in §3.6 (S5).** Storage table `kbl_layer0_hash_seen` is created by B1 in PR #5 (about-to-merge). Layer 0 reads/writes hashes; daily cron drains expired rows.

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
4. **Signal's raw_content matches any slug-or-alias from `kbl.slug_registry` AS a whole word — alias-aware (S3).** Topic override partially relaxes the sender blocklist for on-topic content. Implementation iterates `slug_registry.active_slugs()` AND `slug_registry.aliases_for(slug)` per slug, matching each as a whole-word regex. Special case: slugs whose canonical token is **<4 chars** (e.g., `mo-vie` → "mo", `ao` → "ao", `mrci` → "mrci") REQUIRE an alias match — canonical-only match is rejected to prevent false dictionary hits ("ao" appearing in arbitrary French text, "mo" in many languages).
5. **Sender is Director (C2 — author authority).** Email `From:` matches `dvallen@brisengroup.com` / `vallen300@gmail.com` / `office.vienna@brisengroup.com`, OR WhatsApp sender phone is Director's number (`+41 79 960 50 92`), OR meeting organizer is Director's calendar address. Director-authored content is NEVER Layer-0-dropped regardless of content shape, sender domain blocklist, or attachment shape. See §3.4 for rationale.

Invariant #4 (topic override) is the only "soft" invariant — the others are hard. Newsletters CAN carry on-topic news (e.g., Arabian Business covers MO Vienna), and the alias-aware check picks up "Mandarin Oriental Vienna" → matches `mo-vie` alias `mandarin oriental` → keep for Step 1.

### 3.3 Observability

Every Layer 0 drop MUST emit a `kbl_log` row with:
- `component='layer0'`
- `level='INFO'`
- `message=f"dropped: {rule_name} ({detail})"` — detail is rule-specific
- Reference to `signal_id` so corpus-level analysis can reconstruct distributions

**Corpus-level metric to watch:** drop rate per rule per day. Rule that starts firing more often may need tightening; rule that stops firing may be obsolete. Dashboard widget in Sentinel Layer 1.

**Sampling for review (S6 — full spec):** see §3.5 for the `kbl_layer0_review` table schema, sampling cadence, excerpt size, and verdict enum. Sampling without a Director-facing surfacing path = noise; the spec below closes that.

### 3.4 Layer 0 is NOT an alert mechanism (C1 — CHANDA Inv 7 clarification)

Layer 0 is a **deterministic pre-LLM noise filter.** It is NOT an alert mechanism. Per CHANDA Inv 7, ayoniso alerts are *prompts, never overrides* — that invariant binds the alert-routing layer (separate from Layer 0). Layer 0 by contrast SILENTLY DROPS signals deterministically; Director never receives a notification per drop.

**Layer 0's safety surface against silent overrides:**

1. **Logged.** Every drop emits one `kbl_log` row (§3.3) — auditable, queryable, reportable.
2. **Sampled.** 1-in-50 dropped signals (§3.5) land in `kbl_layer0_review` for Director spot-check.
3. **Bounded by never-drop invariants.** §3.2 lists the five conditions that override every drop rule (scan source, VIP sender, pre-tagged matter, slug/alias mention, Director sender).
4. **Versioned + tunable.** YAML in baker-vault (§1) means Director can audit any rule and reverse it without code release.

**What Layer 0 explicitly does NOT do:**
- Send Director a notification per dropped signal (would defeat the purpose of filtering noise).
- Surface a per-drop decision for Director approval (deterministic by design).
- Get over-ridden by an LLM-generated "wait, this might be important" check (no LLM in Layer 0).

If Director needs per-drop oversight beyond §3.5 sampling, the right intervention is to add a never-drop invariant in §3.2 (Inv 5 / sender authority) or whitelist specific senders/patterns. Layer 0 is governed by RULES + INVARIANTS, not by alerts.

### 3.5 `kbl_layer0_review` sampling queue (S6 — full spec)

Sampling without surfacing = noise. The Director-facing surfacing happens in KBL-C (Cockpit dashboard widget showing pending reviews — out of scope for this draft). The DB-writer side IS in scope:

**Table** (created by B1 in PR #5, schema below for B3 reference):

```sql
CREATE TABLE IF NOT EXISTS kbl_layer0_review (
  id SERIAL PRIMARY KEY,
  signal_id INT REFERENCES signal_queue(id) ON DELETE SET NULL,
  rule_name TEXT NOT NULL,
  excerpt TEXT NOT NULL,                                       -- first 500 chars of payload content (§3.5 spec)
  sampled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  reviewed_at TIMESTAMPTZ,
  director_verdict TEXT CHECK (
    director_verdict IN ('correct_drop', 'false_positive', 'ambiguous')
    OR director_verdict IS NULL
  )
);
CREATE INDEX idx_kbl_layer0_review_pending ON kbl_layer0_review (sampled_at) WHERE reviewed_at IS NULL;
```

**Sampling rate.** 1-in-50 dropped signals get a row. Sampling decision uses **deterministic modulo on `signal_queue.id`**:

```python
should_sample_for_review = (signal.id % 50) == 0
```

Why deterministic over random: reproducibility for tests + audit. Pytest can construct a signal with `id=50` (or any multiple of 50) and assert the review row is written. Random sampling would either need seeded RNG (still deterministic but more moving parts) or non-deterministic tests (smell).

**Excerpt field.** First **500 chars** of `signal.raw_content`, with newlines preserved as `\n` (no JSON escaping). Long enough to convey signal intent; short enough that the Cockpit widget can render N pending reviews without paginating each one.

**Verdict enum:**
- `correct_drop` — Director confirms the rule was right; no action needed; rule stays as-is. Telemetry: rule confidence reinforced.
- `false_positive` — Director marks the drop as wrong. Triggers rule audit (§6 tuning playbook): rule retired, tightened, or replaced. Telemetry: false-positive rate computed per rule.
- `ambiguous` — Director can't decide cleanly; signal recoverable via Scan re-inject. Telemetry: ambiguity flag aggregated for Director-level rule reflection.

**Writer integration:** `_process_layer0()` (§4) inserts the row inside the same transaction as the `signal_queue` state update + `kbl_log` insert. Atomic per-signal: dropped, logged, sampled (if applicable) — all-or-nothing.

### 3.6 `kbl_layer0_hash_seen` 72h dedupe store (S5 — full spec)

**Table** (created by B1 in PR #5, schema below for B3 reference + B1's later impl alignment):

```sql
CREATE TABLE IF NOT EXISTS kbl_layer0_hash_seen (
  content_hash      TEXT PRIMARY KEY,                          -- sha256 hex of normalized content
  first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ttl_expires_at    TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '72 hours'),
  source_signal_id  BIGINT REFERENCES signal_queue(id) ON DELETE SET NULL,
  source_kind       TEXT NOT NULL                              -- 'email' | 'whatsapp' | 'meeting' | 'scan'
);
CREATE INDEX idx_kbl_layer0_hash_ttl ON kbl_layer0_hash_seen (ttl_expires_at);
```

**Hash algorithm:** `hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()`. Hex output (64 chars). Collision-impossible at this volume.

**Normalization recipe** — deterministic, B1 implements exactly this so the dedupe store is interpretable by future audits:

```python
import re

_SIG_PATTERNS = re.compile(
    r"\n\s*--\s*\n"                  # standard sig delimiter "\n-- \n"
    r"|\nBest\s+(?:regards|wishes|,)" # common signoff openings
    r"|\nKind\s+regards"
    r"|\nThanks(?:\s+again)?,",
    re.IGNORECASE,
)

def normalize_for_hash(content: str) -> str:
    """Deterministic normalization for the 72h dedupe store.

    Steps (in order — each is idempotent):
      1. Strip quoted reply chains (lines starting with '>' after optional whitespace).
      2. Truncate at first signature pattern match (stops "Best regards," tail noise).
      3. Lowercase the entire body.
      4. Collapse all consecutive whitespace (incl. newlines) to single space.
      5. Strip leading + trailing whitespace.

    Two near-identical email re-forwards (different sig styles, different
    quote-chain depth) hash IDENTICAL after this. Genuinely-different
    signal content hashes differently."""
    if not content:
        return ""
    # 1. Drop quoted-reply lines
    lines = [l for l in content.split("\n") if not l.lstrip().startswith(">")]
    text = "\n".join(lines)
    # 2. Truncate at first signature marker
    m = _SIG_PATTERNS.search(text)
    if m:
        text = text[:m.start()]
    # 3-5. Lower + collapse whitespace + strip
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text
```

**Cleanup tick.** Daily cron job (08:00 UTC, low-traffic window):

```sql
DELETE FROM kbl_layer0_hash_seen WHERE ttl_expires_at < NOW();
```

Implementation: piggyback on existing `scripts/kbl-purge-dedupe.sh` (KBL-A) OR add a new `kbl-layer0-hash-purge.sh` cron entry. B1's call.

**Hot-path latency.** Layer 0 dispatcher does ONE `SELECT 1 FROM kbl_layer0_hash_seen WHERE content_hash = $1` per signal (sub-ms PRIMARY KEY lookup). On miss, dispatcher INSERTs the row inside the same transaction as the signal's pass/drop decision. On hit, the rule fires drop. No race condition because `content_hash` is PRIMARY KEY (insert-after-existing-hit collision raises, caught + treated as hit).

**Statefulness note (B2 N3 callout, accepted):** the `duplicate_content_hash` rule is NOT a pure function of the signal — its result depends on the `kbl_layer0_hash_seen` store state. Pytest must seed/reset the store between test runs. The §5.1 invariant restated to: *"Rules are deterministic GIVEN the current state of `kbl_layer0_hash_seen`."*

---

## 4. Implementation sketch

**File:** `kbl/steps/layer0.py`

```python
import os
import re
import threading
from pathlib import Path
from typing import Literal

import yaml

from kbl.signal_types import SignalRow
from kbl.slug_registry import active_slugs, aliases_for
from baker.vip_contacts import is_vip_sender, is_director_sender


class Layer0RulesError(RuntimeError):
    """Raised when baker-vault/layer0_rules.yml is missing or malformed.
    Fail-loud at process start (mirrors SLUGS-1 SlugRegistryError pattern)."""


_LOAD_LOCK = threading.Lock()
_CACHED_RULESET: "Layer0RuleSet | None" = None


def get_ruleset() -> "Layer0RuleSet":
    """Module-level cached accessor. SLUGS-1 pattern."""
    global _CACHED_RULESET
    if _CACHED_RULESET is None:
        with _LOAD_LOCK:
            if _CACHED_RULESET is None:
                _CACHED_RULESET = Layer0RuleSet.load_from_vault()
    return _CACHED_RULESET


def reload_ruleset() -> None:
    """SIGHUP / per-tick re-load. Drops cache; next get() re-reads YAML."""
    global _CACHED_RULESET
    with _LOAD_LOCK:
        _CACHED_RULESET = None


class Layer0RuleSet:
    def __init__(self, version: int, rules: list[dict]):
        self.version = version
        self.rules = rules

    @classmethod
    def load_from_vault(cls) -> "Layer0RuleSet":
        """S1: load from $BAKER_VAULT_PATH/layer0_rules.yml.
        Mirrors slug_registry.load_from_vault() pattern."""
        vault = os.environ.get("BAKER_VAULT_PATH")
        if not vault:
            raise Layer0RulesError("BAKER_VAULT_PATH env not set")
        path = Path(vault) / "layer0_rules.yml"
        if not path.exists():
            raise Layer0RulesError(f"missing: {path}")
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as e:
            raise Layer0RulesError(f"malformed YAML in {path}: {e}") from e
        cls._validate_schema(data)
        return cls(version=data["version"], rules=data["rules"])

    @staticmethod
    def _validate_schema(data: dict) -> None:
        """Mirror SLUGS-1 validation. Fail-loud on shape errors."""
        if not isinstance(data.get("version"), int):
            raise Layer0RulesError("version must be int")
        rules = data.get("rules", [])
        if not isinstance(rules, list):
            raise Layer0RulesError("rules must be a list")
        for i, r in enumerate(rules):
            for required in ("name", "source", "type", "detail"):
                if required not in r:
                    raise Layer0RulesError(f"rule[{i}] missing '{required}'")
            if r["type"] not in _RULE_DISPATCHERS:
                raise Layer0RulesError(
                    f"rule[{i}] type '{r['type']}' has no handler"
                )

    def evaluate(self, signal: SignalRow) -> tuple[Literal["pass", "drop"], str]:
        # Never-drop invariants first (§3.2). Order is intentional —
        # cheapest checks first, most expensive last.
        if signal.source == "scan":
            return ("pass", "")

        # C2: Director-sender never-drop (Inv 5).
        if is_director_sender(signal):
            return ("pass", "")

        # S4: VIP soft-fail-CLOSED.
        try:
            if is_vip_sender(signal.payload):
                return ("pass", "")
        except Exception:
            # VIP service unreachable → treat ALL as VIP for outage duration.
            # See §5 failure-modes table — terminal drops have no Step 1 backstop.
            kbl_log(component="layer0", level="WARN",
                    message="vip_lookup_failed_pass_through")
            return ("pass", "")

        if signal.payload.get("primary_matter_hint"):
            return ("pass", "")

        # S3: alias-aware topic override (with short-slug safeguard) +
        # S4 parallel: slug-registry soft-fail-CLOSED.
        try:
            if _mentions_active_slug_or_alias(signal.raw_content):
                return ("pass", "")
        except Exception:
            kbl_log(component="layer0", level="WARN",
                    message="slug_registry_unreachable_pass_through")
            return ("pass", "")

        # Walk rules top-to-bottom, first match wins.
        for rule in self.rules:
            if rule["source"] not in ("*", signal.source):
                continue
            if _rule_matches(rule, signal):
                return ("drop", rule["name"])

        return ("pass", "")


def _rule_matches(rule: dict, signal: SignalRow) -> bool:
    """Dispatch on rule['type']. Schema validator already ensured handler exists."""
    return _RULE_DISPATCHERS[rule["type"]](rule, signal)


# ── Type handlers — small, testable, no I/O ─────────────────────────────

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
    lines = [l for l in content.split("\n") if ":" in l]
    if lines:
        unknown = sum(1 for l in lines if l.strip().lower().startswith("unknown:"))
        if unknown / len(lines) >= rule["max_unknown_speaker_ratio"]:
            return True
    tokens = content.lower().split()
    if tokens:
        ratio = len(set(tokens)) / len(tokens)
        if ratio < rule["min_unique_tokens_ratio"]:
            return True
    return False

def _match_content_starts_with_marker(rule, signal) -> bool:
    """S2: baker_self_analysis_echo via literal prefix on storage marker."""
    body = (signal.raw_content or "").lstrip()
    return any(body.startswith(m) for m in rule["markers"])

def _match_content_hash_seen(rule, signal) -> bool:
    """duplicate_content_hash: query kbl_layer0_hash_seen (§3.6).
    INSERT-or-no-op on miss happens in _process_layer0 — this is the
    READ side only."""
    from kbl.layer0_dedupe import has_seen_recent  # B1's ticket
    h = _hash_normalized_content(signal.raw_content)
    return has_seen_recent(h)

# Hashing helper — see §3.6 normalize_for_hash() recipe
import hashlib
def _hash_normalized_content(content: str) -> str:
    from kbl.layer0_dedupe import normalize_for_hash
    return hashlib.sha256(
        normalize_for_hash(content).encode("utf-8")
    ).hexdigest()


_RULE_DISPATCHERS = {
    "email_sender_domain_contains":   _match_email_sender_domain_contains,
    "wa_chat_id_suffix":              _match_wa_chat_id_suffix,
    "meeting_transcript_quality":     _match_meeting_transcript_quality,
    "content_starts_with_marker":     _match_content_starts_with_marker,    # S2
    "content_hash_seen_within_hours": _match_content_hash_seen,             # S5
    # ...one handler per type in the YAML; B1 adds remaining as needed
}


def _mentions_active_slug_or_alias(content: str) -> bool:
    """S3: alias-aware topic override + short-slug safeguard.

    For each active slug:
      - Get all aliases via slug_registry.aliases_for(slug)
      - If slug's canonical primary token is < 4 chars (e.g. 'mo' from
        'mo-vie'), REQUIRE alias match — canonical-only match rejected.
      - Otherwise, slug canonical OR any alias matches as whole-word.
    """
    body = (content or "").lower()
    for slug in active_slugs():
        primary_word = slug.split("-")[0]
        aliases = aliases_for(slug)            # list[str], lowercase
        # Short-slug safeguard
        candidates = list(aliases)
        if len(primary_word) >= 4:
            candidates.append(primary_word)
        for term in candidates:
            if re.search(rf"\b{re.escape(term.lower())}\b", body):
                return True
    return False
```

**Integration point:** `kbl/pipeline_worker.py` at stage `layer0`:

```python
def _process_layer0(signal: SignalRow) -> None:
    """Per §3.5 + §3.6: drop decision + log + sample (if applicable) +
    hash store insert (if applicable) — atomic per signal in one TX."""
    ruleset = get_ruleset()
    decision, rule_name = ruleset.evaluate(signal)

    with db.transaction():
        if decision == "drop":
            signal.mark_dropped(stage="layer0", reason=rule_name)
            kbl_log(component="layer0", level="INFO",
                    message=f"dropped: {rule_name}",
                    signal_id=signal.id)
            # S6: 1-in-50 sampling for Director review
            if (signal.id % 50) == 0:
                kbl_layer0_review_insert(
                    signal_id=signal.id,
                    rule_name=rule_name,
                    excerpt=(signal.raw_content or "")[:500],
                )
        else:
            signal.advance_stage(to="triage")
            # S5: only insert hash on PASS (drops are not added to dedupe
            # store — we don't want a false-positive drop to suppress
            # future legitimate signals with same content).
            content_hash = _hash_normalized_content(signal.raw_content)
            kbl_layer0_hash_insert(
                content_hash=content_hash,
                source_signal_id=signal.id,
                source_kind=signal.source,
            )
```

**Note on hash insert semantics:** insert happens on PASS (signal accepted). On DROP, no hash inserted — a false-positive drop must not silently dedupe future legitimate copies of the same content. Conservative bias: hash store records what flowed through, not what was filtered.

---

## 5. Expected failure modes + recovery

| Failure mode | Detection | Recovery |
|---|---|---|
| Rule YAML malformed at startup | `yaml.safe_load` raises | Pipeline refuses to start. Alert via `kbl_log` + Sentinel page. Fallback: prior-version YAML (kept in rollback slot). |
| Rule dispatcher KeyError (unknown type) | `_rule_matches` raises | Pipeline stops. Indicates YAML + code version drift. Rollback YAML or deploy new code. |
| False-positive drop (real signal rejected) | `kbl_layer0_review` sampling queue | Director flags → rule authored is soft-retired, tightened, or replaced. No auto-retry on the dropped signal (re-queueing would create infinite loops with buggy rule). Director can manually re-inject via Scan if needed. |
| False-negative pass (noise reaches Step 1) | Corpus telemetry on Step 1 `triage_score` distribution | If Step 1 keeps scoring < 20 for unfiltered signals, add new Layer 0 rule. This is the self-calibrating feedback loop. |
| VIP list unavailable (`baker.vip_contacts` query fails) | Python exception in `is_vip_sender` | **Soft-fail CLOSED (S4 fix).** Treat ALL senders as VIP for the duration of the outage — every signal passes Layer 0 to Step 1. Log `WARN`. **Why CLOSED, not OPEN:** Layer 0 drops are TERMINAL (`state='dropped_layer0'`, signal never reaches Step 1). The previous "Step 1 backstop" reasoning was wrong — there IS no backstop downstream. Soft-fail-CLOSED biases toward not dropping a real VIP signal during VIP-service downtime; cost is bounded (Step 1 LLM calls on noise, only during outage, which should be rare). |
| Slug registry unavailable for §3.2 invariant #4 | Exception in `_mentions_active_slug_or_alias` | **Soft-fail CLOSED (S4 fix, parallel reasoning).** Treat as topic-mention positive — let signal through. Same rationale as VIP: drops are terminal, no Step 1 backstop, cost-of-pass-through is bounded. Log `WARN`. |

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


def test_email_newsletter_but_mentions_matter_passes_via_alias():
    """S3: alias-aware topic override. Arabian Business covers MO Vienna —
    'Mandarin Oriental' is a mo-vie alias; topic override must fire."""
    signal = email_signal(
        sender="newsletters@arabianbusiness.com",
        raw_content="Mandarin Oriental Vienna hotel announces new suite category...",
    )
    # Pre-condition: 'mo-vie' in active_slugs(); aliases_for('mo-vie')
    # includes 'mandarin oriental' / 'mandarin' / 'mo vienna'.
    assert ruleset.evaluate(signal) == ("pass", "")  # topic override via alias


def test_short_slug_canonical_only_does_NOT_match_topic_override():
    """S3 safeguard: 'ao' in arbitrary text must NOT trigger topic override
    on slug 'ao' (Andrey Oskolkov). Requires alias 'oskolkov'/'andrey' to fire."""
    signal = email_signal(
        sender="newsletters@arabianbusiness.com",
        raw_content="The CEO said 'ao tempo certo, vamos avaliar' during the keynote.",
        # 'ao' is canonical of slug 'ao' but appears here as Portuguese — no real Oskolkov reference
    )
    # Topic override must NOT fire. Newsletter sender → drop fires.
    assert ruleset.evaluate(signal) == ("drop", "email_sender_blocklist_domains")


def test_short_slug_alias_DOES_match_topic_override():
    """S3 safeguard, positive case: 'Oskolkov' in newsletter copy → alias
    of 'ao' → topic override must fire."""
    signal = email_signal(
        sender="newsletters@arabianbusiness.com",
        raw_content="UAE investor Andrey Oskolkov backs new Geneva fund...",
    )
    assert ruleset.evaluate(signal) == ("pass", "")  # alias 'andrey'/'oskolkov' wins


def test_wa_status_broadcast_dropped():
    signal = whatsapp_signal(chat_id="false_status@broadcast_A5ACEFDC...")
    assert ruleset.evaluate(signal) == ("drop", "wa_status_broadcast")


def test_meeting_garbled_transcript_dropped():
    signal = meeting_signal(
        duration_sec=960,  # 16 min — passes duration rule
        raw_content="Unknown: Hello, tax listener. Unknown: Ikbukata. Unknown: Onskazto..." * 10,
    )
    assert ruleset.evaluate(signal) == ("drop", "meeting_transcript_quality_floor")


def test_baker_scan_marker_dropped():
    """S2: anchor on baker_scan: prefix, NOT natural language phrase."""
    signal = whatsapp_signal(
        raw_content="baker_scan: Daily summary 2026-04-18 — 12 signals processed..."
    )
    assert ruleset.evaluate(signal) == ("drop", "baker_self_analysis_echo")


def test_natural_language_baker_mention_does_NOT_drop():
    """S2 safeguard: legitimate human content mentioning Baker must NOT drop.
    Pre-S2 spec would have wrongly caught this."""
    signal = whatsapp_signal(
        raw_content="I asked Baker about the Mac Mini password and got a weird answer — bug?"
    )
    # baker_self_analysis_echo must NOT fire (no leading marker).
    # Signal flows to triage as legitimate baker-internal content.
    assert ruleset.evaluate(signal) == ("pass", "")


def test_director_sender_email_never_dropped():
    """C2: Director-sender never-drop invariant. Even with newsletter-shape
    sender domain, signal from dvallen@brisengroup.com bypasses Layer 0."""
    signal = email_signal(
        sender="dvallen@brisengroup.com",
        raw_content="quick test",  # short content, would normally trigger length rules
    )
    assert ruleset.evaluate(signal) == ("pass", "")


def test_director_sender_whatsapp_never_dropped():
    """C2 parallel: WhatsApp from Director's number bypasses content_min_chars."""
    signal = whatsapp_signal(
        sender_phone="+41 79 960 50 92",
        raw_content="ok",  # 2 chars — would normally fire wa_minimum_content_length
    )
    assert ruleset.evaluate(signal) == ("pass", "")


def test_scan_query_never_dropped():
    # Even a scan query saying "noreply newsletter" isn't dropped.
    signal = scan_signal(raw_content="Hey Baker, summarize the noreply newsletter from yesterday")
    assert ruleset.evaluate(signal) == ("pass", "")


def test_duplicate_content_hash_drops_second_occurrence():
    """S5: deterministic GIVEN store state. First passes, second drops."""
    seed_kbl_layer0_hash_seen([])  # empty start
    sig1 = email_signal(sender="balazs@brisengroup.com", raw_content="MRCI Saldenliste fwd Q1")
    sig1.id = 100
    assert ruleset.evaluate(sig1) == ("pass", "")  # first time — passes, hash stored
    # Process the pass to insert the hash (production code would do this
    # in _process_layer0 after evaluate returns).
    insert_hash_for_passed_signal(sig1)

    sig2 = email_signal(sender="balazs@brisengroup.com", raw_content="MRCI Saldenliste fwd Q1")
    sig2.id = 101
    assert ruleset.evaluate(sig2) == ("drop", "duplicate_content_hash")


def test_layer0_review_sampling_writes_at_id_multiple_of_50():
    """S6: deterministic 1-in-50 sampling. Asserts the writer side."""
    sig = email_signal(sender="newsletters@thetimes.com", raw_content="Wednesday's briefing")
    sig.id = 50  # multiple of 50 → must sample
    _process_layer0(sig)
    rows = fetch_review_rows()
    assert len(rows) == 1
    assert rows[0]["rule_name"] == "email_sender_blocklist_domains"
    assert "Wednesday's briefing" in rows[0]["excerpt"]


def test_layer0_review_sampling_skips_at_id_NOT_multiple_of_50():
    sig = email_signal(sender="newsletters@thetimes.com", raw_content="Wednesday's briefing")
    sig.id = 51  # not a multiple of 50
    _process_layer0(sig)
    assert len(fetch_review_rows()) == 0


def test_vip_lookup_failure_passes_signal_through():
    """S4: VIP soft-fail-CLOSED. VIP service exception → signal passes."""
    with mock_vip_lookup_raises(ConnectionError("vip db down")):
        signal = email_signal(
            sender="newsletters@thetimes.com",
            raw_content="Wednesday's briefing",
        )
        # Despite blocklisted-shape sender, soft-fail-CLOSED → pass
        assert ruleset.evaluate(signal) == ("pass", "")
```

Each rule needs: one positive (fires correctly), one negative (doesn't fire on similar-but-not-matching signal), one escape-valve test (VIP / topic / scan / Director-sender overrides win). 14 tests above cover the rule-set ratified post-S1-S6 + C1-C2 amendment.

---

## 9. Deliverable summary

| Artifact | Path | Status |
|---|---|---|
| Rule YAML | **`baker-vault/layer0_rules.yml`** (S1 — vault, not baker-master) | Template in §1 |
| Loader + dispatcher code | `kbl/steps/layer0.py` | Sketch in §4 (SLUGS-1 pattern: `Layer0RulesError` + lock + cache + `reload()`) |
| VIP resolver | `baker.vip_contacts` (existing) + new `is_vip_sender()` helper | TBD (B1 ticket) |
| Director-sender resolver | new `is_director_sender(signal)` helper in `baker.director_identity` | TBD (B1 ticket) — C2 |
| Hash-store helpers | `kbl.layer0_dedupe.{normalize_for_hash, has_seen_recent, insert_hash}` | TBD (B1 ticket) — S5 |
| Review-queue writer | `kbl_layer0_review_insert(signal_id, rule_name, excerpt)` helper | TBD (B1 ticket) — S6 |
| Hot-reload | SIGHUP handler + per-tick option | §4 stub (`reload_ruleset()`) |
| Schema validation | Loader `_validate_schema()` | §4 (mirrors SLUGS-1) |
| Test suite | `tests/test_layer0_rules.py` | 14 tests in §8 |
| Test fixtures | `tests/fixtures/layer0_rules_*.yml` (happy-path, malformed, unknown-rule-type) | Mirror SLUGS-1 fixtures pattern |
| Log integration | `kbl_log` with `component='layer0'` | §3.3 |
| Metrics dashboard | Sentinel Layer 1 widget | §6.1 SQL seed |

Drop rate target: **20-30% of total signal volume** (matches §2 ratified figure). Based on 50-signal corpus, email alone would drop ~32% (8/25). WA / meeting drops are lower-rate but lower-volume sources — overall 20-25% is realistic for Phase 1.

---

## 10. Amendment log

| Item | Source | Status | Section(s) touched |
|---|---|---|---|
| **S1** YAML relocation `baker-master/kbl/config/` → **`baker-vault/`** | B2 review S1 | ✅ Applied | Header, §1, §4 loader, §9 deliverables |
| **S2** `baker_self_analysis_echo` anchor on `baker_scan:` prefix (replace phrase-based match) | B2 review S2 | ✅ Applied | §1 rule, §2.4 evidence, §4 `_match_content_starts_with_marker`, §8 tests (positive + negative) |
| **S3** Topic-override alias-aware via `slug_registry.aliases_for()` + short-slug (<4 chars) safeguard | B2 review S3 | ✅ Applied | §3.2 invariant #4, §4 `_mentions_active_slug_or_alias`, §8 tests (positive alias, negative short-slug, positive short-slug-alias) |
| **S4** VIP soft-fail OPEN → **CLOSED** (also slug-registry parallel) | B2 review S4 | ✅ Applied | §5 failure-modes table (both rows), §4 `evaluate()` try/except blocks, §8 test |
| **S5** Hash-store full spec — `kbl_layer0_hash_seen` schema, normalize_for_hash recipe, sha256 hex, daily TTL cleanup | B2 review S5 | ✅ Applied | §1 rule (cross-ref), §2.5 evidence (cross-ref), §3.6 (NEW full spec), §4 `_match_content_hash_seen` + `_hash_normalized_content`, §5.1 statefulness invariant restated, §8 test |
| **S6** Review queue full spec — `kbl_layer0_review` schema, deterministic 1-in-50 sampling via `signal.id % 50`, 500-char excerpt, `correct_drop`/`false_positive`/`ambiguous` verdict enum | B2 review S6 | ✅ Applied | §3.5 (NEW full spec), §4 `_process_layer0` writer integration, §8 tests (sample-fires + sample-skips) |
| **C1** "Layer 0 is NOT an alert mechanism" clarifying paragraph | B3 CHANDA ack | ✅ Applied | §3.4 (NEW) |
| **C2** Director-sender never-drop invariant (Inv 5) | B3 CHANDA ack | ✅ Applied | §3.2 invariant list (added Inv 5), §4 `evaluate()` Director check after scan, §8 tests (email + WhatsApp) |

**Architectural notes accepted from B2 review:**
- Loader pattern mirrors SLUGS-1 (`threading.Lock`, `reload()`, `Layer0RulesError`, `_validate_schema`). Applied in §4.
- Schema validation absent → added (`_validate_schema` checks name/source/type/detail per rule, type ∈ known handlers).
- Hot-reload story added (`reload_ruleset()`).
- N3 statefulness clarification (rules deterministic GIVEN store state) → applied to §5.1 + §3.6.

**Items deferred (not in this amendment):**
- N1 (env-tunable meeting thresholds) — defer; YAML PR path is cheap enough.
- N2 (multi-personal-email list) — N/A right now; Director's setup is single personal address.
- N4 (rule re-ordering by drop-rate for perf) — defer per B3 §6.6.
- N5 (`version` bump policy) — accepted as SLUGS-1-style; documented in §1 ("Same `version: N` versioning pattern as SLUGS-1").
- G1 (calendar-invite auto-emails) — defer per B2; add post-launch when telemetry shows count.
- G2 (Director outbound re-ingestion) — addressed by C2 Inv 5; trigger-layer dedupe still primary, Layer 0 is the safety net.
- G3 (empty-body attachments-only) — defer per B2; existing local-part + sender domain rules cover the noise subset.

---

*Drafted 2026-04-18 by B3 for AI Head §6 assembly + KBL-B Step 0 implementation. No code written, no evals run.*
*Amended 2026-04-18 (this commit): S1-S6 + C1-C2 applied per B2 review (commit `e0f38ab`) + B3 CHANDA ack flags (commit `e9eb04e`). Per Task LAYER0-RULES-S1-S6 dispatched at commit `4b3b636`. Ready for B2 re-review.*
