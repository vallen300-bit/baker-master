# BRIEF: BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1 — marketing / no-reply / survey mail off the Director Today feed

## Context
Sibling fast-follow to `BAKER_DASHBOARD_V2_INFRA_ALERT_FILTER_1` (PR #419, merged `10987cf`). #419 took **infra-health** noise off the V2 Today feed by extending the shared `_is_stoplist_noise` chokepoint. This brief takes the next noise class — **marketing / newsletter / no-reply / survey / promo** mail — off the same feed, via the **same chokepoint, same DRY pattern, same gate chain**.

The chokepoint is already wired into both bridges (V1 `alerts_to_signal` + V2 `candidate_ingest.bridge_alert_to_candidate`) by #419. **This brief only extends the noise *definition*** — it adds title patterns. No new wiring, no schema change, no endpoint, no model call.

**Audit reference:** `briefs/_reports/BAKER_DASHBOARD_AUDIT_2026-06-21.md` items #1 (marketing/promo mis-classified as deadlines) + #12 ("no-reply/marketing/survey auto-mail flagged as 'awaiting your reply' — a no-reply address can never be a quiet thread").

**Live evidence (AH1 query, 2026-06-24, prod):**
- `367` pending alerts total; `15` match a clear marketing/no-reply/survey/promo signature **now** (steady-refill, not one-off).
- Source mix feeding the noise: `proactive_pm_sentinel` (quiet-thread / awaiting-counterparty, 200 pending) and `deadline_cadence` (25 pending).
- The sender sits **inside the alert title** in the form `Quiet thread [movie_am]: email: <sender> — <subject>`, so the existing title-regex (`_STOPLIST_RE.search(title)`) can match it — no need to add a column or parse `structured_actions` (it carries no sender field; `capability_threads` has no sender column either — confirmed).

**Real live noise rows this filter targets (proof set):**
- `25642` `email: noreply-eh@highq.com — E+H Rechtsanwälte ... Daily site alert` (no-reply automated digest)
- `25646` `email: MIO »OBSERVER« — Mandarin Oriental Wien - Ihr »OBSERVER«` (newsletter)
- `25640` `email: Atelier 7 - Brasserie — How was your experience at Atelier` (survey)
- `25649` `email: MOVIE Reservations — RE: Your upcoming stay at Mandarin Or` (reservation auto-mail)
- `25758` `Due tomorrow: Use code 'FLIKISTART50' for 50% off any monthly plan.` (promo, mis-filed as deadline)

## Estimated time: ~1.5h
## Complexity: Low
## Prerequisites: none (chokepoint already live from #419)

---

## Fix 1: Marketing / no-reply / survey / promo title patterns in the shared stoplist

### Problem
Automated, bulk, and promotional mail reaches the Director Today feed as quiet-thread "awaiting your reply" cards and as fake deadlines. None of it is ever a genuine Director action: a no-reply address cannot receive a reply; a newsletter / survey / promo is not a matter event. ~97% of the morning-brief attention surface was noise pre-cleanup (audit); this is the second-largest remaining class after infra (which #419 closed).

### Current State
- `kbl/bridge/alerts_to_signal.py`
  - `STOPLIST_TITLE_PATTERNS` (≈line 99) — tuple of `re.IGNORECASE` regexes, compiled once into `_STOPLIST_RE` (≈line 126).
  - `_is_stoplist_noise(alert)` (≈line 156) — checks `alert["source"] in STOPLIST_SOURCES`, then `_STOPLIST_RE.search(title)`, then the auction special-case. Title-only; returns `bool`.
- Both bridges already call this one function:
  - V1: `kbl/bridge/alerts_to_signal.py` batch loop (≈line 658).
  - V2: `orchestrator/candidate_ingest.py` `bridge_alert_to_candidate` (≈line 341) — `if _is_stoplist_noise(alert): return {... "skipped_reason": "stoplist_noise"}`.
- **No wiring change is needed.** Adding patterns to the compiled regex automatically applies to both bridges.

### Engineering Craft Gates
- **Diagnose:** applies. Feedback loop = `pytest tests/test_bridge_stop_list_additions.py -v` (fast, pure-function) + the live count probe below. Symptom captured = the 5 proof rows above. Hypothesis (confirmed): noise senders/subjects are present verbatim in `alert["title"]`; the title regex is the correct, deterministic seam. Probe = post-deploy live count of candidates produced from the 15 marketing alerts → must be 0.
- **Prototype:** N/A — data shape and decision are known; no UI / state / data-shape uncertainty.
- **TDD/verification:** applies. Public seam = `_is_stoplist_noise(alert: dict) -> bool` (and `STOPLIST_MARKETING_PATTERNS` via `_STOPLIST_RE`). Write the vertical positive + negative cases **first** (real live titles, below), then add the patterns until green. No mocks — the function is pure.

### Implementation

**Step 1 — add a grouped, audit-commented marketing pattern tuple** in `kbl/bridge/alerts_to_signal.py`, immediately AFTER the `STOPLIST_TITLE_PATTERNS` tuple (after its closing `)`, ≈line 123) and BEFORE the `_STOPLIST_RE = re.compile(...)` line:

```python
# MARKETING_NOISE_FILTER_1: marketing / no-reply / newsletter / survey / promo.
# Kept as a SEPARATE, individually-audited group (sibling of STOPLIST_TITLE_PATTERNS)
# so a future brief can retire any single line if a matter-tag classifier subsumes it.
# Matched against the alert TITLE, which for proactive_pm_sentinel / deadline_cadence
# rows carries the sender + subject verbatim ("... email: <sender> — <subject>").
# Each class can NEVER be a genuine Director action: a no-reply address cannot receive
# a reply; a newsletter / survey / promo is not a matter event.
STOPLIST_MARKETING_PATTERNS = (
    # -- automated / no-reply senders (address appears in the title) --
    r"\bno[-_]?reply\b",            # noreply-eh@highq.com (E+H daily site-alert digest)
    r"\bdo[-_]?not[-_]?reply\b",    # do-not-reply@, donotreply@
    r"\bmailer[-_]?daemon\b",
    r"\bbounce[\w.+-]*@",           # bounce / VERP return-path senders
    r"\bnotifications?@",           # notification@ / notifications@ bulk senders
    r"\bnewsletter@",
    r"\bmarketing@",
    # -- newsletters / bulk editorial --
    r"»\s*observer\s*«",            # MIO »OBSERVER« newsletter (distinctive guillemets)
    r"\bnewsletter\b",
    r"\bwebinar\b",
    # -- satisfaction / feedback surveys --
    r"\bhow was your (?:experience|stay|visit)\b",   # Atelier 7 — "How was your experience"
    r"\brate your (?:experience|stay|recent|visit)\b",
    r"\bsatisfaction survey\b",
    r"\b(?:take|complete) (?:our|the|a) (?:short )?survey\b",
    # -- promotions / discount CTAs (deadline_cadence mis-files these as deadlines) --
    r"\b\d{1,3}\s*%\s*off\b",       # "50% off"
    r"\buse code\b",                # "Use code 'FLIKISTART50'"
    r"\b(?:promo|discount|coupon)\s+code\b",
    r"\blimited[-\s]time offer\b",
    # -- transactional reservation auto-mail (tight; retire if it ever clips real mail) --
    r"\bRE:\s*your upcoming stay\b",  # "MOVIE Reservations — RE: Your upcoming stay"
)
```

**Step 2 — fold the new group into the compiled regex.** Change the existing compile line (≈line 126) from:

```python
_STOPLIST_RE = re.compile("|".join(STOPLIST_TITLE_PATTERNS), flags=re.IGNORECASE)
```

to:

```python
_STOPLIST_RE = re.compile(
    "|".join(STOPLIST_TITLE_PATTERNS + STOPLIST_MARKETING_PATTERNS),
    flags=re.IGNORECASE,
)
```

That is the **entire** code change. `_is_stoplist_noise` is unchanged; both bridges inherit the new patterns.

**Step 3 — tests** in `tests/test_bridge_stop_list_additions.py` (the established home for incremental stoplist additions; canonical parametrized tests live in `tests/test_bridge_alerts_to_signal.py`). Import `_is_stoplist_noise` and assert against the **real live titles**:

```python
import pytest
from kbl.bridge.alerts_to_signal import _is_stoplist_noise

# Real prod titles (alerts.status='pending', 2026-06-24) the filter MUST drop.
MARKETING_NOISE_TITLES = [
    "Quiet thread [ao_pm]: email: noreply-eh@highq.com — E+H Rechtsanwälte GmbH Daily site alert",
    "Quiet thread [movie_am]: email: MIO »OBSERVER« — Mandarin Oriental Wien - Ihr »OBSERVER« Pass",
    "Quiet thread [movie_am]: email: Atelier 7 - Brasserie — How was your experience at Atelier 7",
    "Quiet thread [movie_am]: email: MOVIE Reservations — RE: Your upcoming stay at Mandarin Oriental",
    "Due tomorrow: Use code 'FLIKISTART50' for 50% off any monthly plan.",
]

@pytest.mark.parametrize("title", MARKETING_NOISE_TITLES)
def test_marketing_noise_is_stoplisted(title):
    assert _is_stoplist_noise({"source": "proactive_pm_sentinel", "title": title}) is True

# Real matter signal the filter MUST NOT drop (false-positive guards).
MATTER_SIGNAL_TITLES = [
    # genuine inbound prospect replies to MO Residences sales — REAL pipeline
    "Quiet thread [movie_am]: email: Jernej Omahen — Re: Your Interest in Mandarin Oriental Residences, Vienna",
    "Quiet thread [movie_am]: email: Ines Wöckl — Re: Your Interest in Mandarin Oriental Residences, Vienna",
    # real matter correspondence
    "Quiet thread [movie_am]: email: Thomas Bauer — RG7 Schlussabrechnung",
    "Waiting on counterparty [ao_pm]: whatsapp_outbound: Director outbound — Merz deadline confirmed",
    # Brisengroup sales-lead auto-sends — OUT of scope for v1 (see Open Item); MUST stay until Director rules
    "Quiet thread [movie_am]: email: Mykola Borsak | Brisengroup — Your Interest in Mandarin Oriental Residences",
]

@pytest.mark.parametrize("title", MATTER_SIGNAL_TITLES)
def test_matter_signal_not_stoplisted(title):
    assert _is_stoplist_noise({"source": "proactive_pm_sentinel", "title": title}) is False
```

### Key Constraints
- **Do NOT add a blanket `your interest in mandarin` pattern.** That subject is shared by real inbound prospect replies (Jernej Omahen, Ines Wöckl) AND Brisengroup outbound auto-sends. Filtering it would kill live MO Residences sales leads. Scope of this question is a **Director / MOVIE-desk business decision** — see Open Item. v1 leaves all "Your Interest" rows untouched.
- **Do NOT broaden the no-reply patterns to named human senders.** Only the literal automated-address signatures. E+H's real correspondence (from named lawyer addresses) must keep flowing — only the `noreply-eh@` daily-digest is dropped, and only because a no-reply address can definitionally never be an "awaiting your reply" thread.
- **Keep `re.IGNORECASE` on the compiled regex** (repo rule: flag, never inline `(?i)` after `|` — Python applies inline group-flags only rightward, silently breaking earlier alternatives). The single `flags=re.IGNORECASE` on `re.compile` is correct; do not move it inline.
- **Title-only, like the existing function.** Do not start scanning `body` — keep parity with `_is_stoplist_noise`'s current contract; the sender + subject are already in the title.
- **No source additions.** `proactive_pm_sentinel` and `deadline_cadence` are NOT added to `STOPLIST_SOURCES` — they carry real signal too (legit AO/MOVIE quiet threads, real deadlines). Filter by content, not by source.
- **Lesson applied (auto-cleanup-kills-user-data):** tight, high-precision patterns + explicit negative tests are the safety. Anything ambiguous (sales leads, reservations beyond the one tight RE:-pattern) stays out of v1.

### Verification
**Unit (pre-merge):**
```
pytest tests/test_bridge_stop_list_additions.py tests/test_bridge_alerts_to_signal.py -v
```
All positive cases drop, all negative cases pass through. No regression in the existing infra/auction stoplist tests.

**Live probe (post-deploy, AH1 ops step — see below):** after merge + deploy + one producer tick, no new `signal_candidates` are created from the marketing alert ids; the rows remain in `alerts` (bridge does not mutate source).

---

## Files Modified
- `kbl/bridge/alerts_to_signal.py` — add `STOPLIST_MARKETING_PATTERNS` tuple; fold it into `_STOPLIST_RE`. (~22 lines, additive.)
- `tests/test_bridge_stop_list_additions.py` — add positive + negative parametrized tests.

## Do NOT Touch
- `_is_stoplist_noise` body, `STOPLIST_SOURCES`, `STOPLIST_TITLE_PATTERNS`, the auction special-case — unchanged; this is purely additive.
- `orchestrator/candidate_ingest.py` — chokepoint already wired by #419; no change.
- `orchestrator/proactive_pm_sentinel.py` / `deadline_cadence` — upstream suppression is a separate larger brief (see Follow-ups); do not refactor sentinels here.
- `signal_candidates` / `verified_items` / any schema — no migration.

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('kbl/bridge/alerts_to_signal.py', doraise=True)"` clean.
2. Full unit run green; existing stoplist/auction/infra tests still pass (no regex regression).
3. Negative tests prove Jernej Omahen + Ines Wöckl prospect replies + AO/MOVIE WhatsApp threads + Brisengroup "Your Interest" rows are NOT filtered.
4. Gate chain mirrors #419: **G2 deputy-codex** (runtime + threat) → **G3 deputy** (review) → **G4 AH1 `/security-review`** → merge. Dual-codex on this prod PR.
5. Bus-post on ship + each gate per the agent-bus-posting-contract.

## Verification SQL
Before (baseline) and after (should be unchanged in `alerts`; the point is they stop becoming candidates):
```sql
-- How many pending alerts match the marketing signature (baseline ~15):
SELECT count(*) FROM alerts
WHERE status='pending'
  AND title ~* 'no-?reply|donotreply|mailer-daemon|»\s*observer\s*«|newsletter|webinar|how was your (experience|stay|visit)|\d{1,3}\s*%\s*off|use code|(promo|discount|coupon) code|RE:\s*your upcoming stay';
```
```sql
-- After deploy + a producer tick: no candidate should exist whose source alert is one of the marketing rows.
SELECT c.id, c.summary
FROM signal_candidates c
JOIN alerts a ON a.id::text = c.raw_source_id AND c.raw_source_table='alerts'
WHERE a.title ~* 'no-?reply|»\s*observer\s*«|how was your (experience|stay|visit)|\d{1,3}\s*%\s*off|use code'
  AND c.created_at > NOW() - INTERVAL '30 minutes'
LIMIT 20;   -- expect 0 rows
```

---

## AH1 post-merge ops step (NOT b-code work — mirrors #419 "Fix-3 card-cleanup")
After merge + deploy, AH1 runs a one-time, **audited** dismissal of already-bridged marketing candidates (the filter only stops *new* bridging; rows produced before the deploy persist), then a producer re-run, exactly as the infra filter's post-deploy AC did (`mark_candidate_auto_refused` / dismiss with `transition_item` audit). Verify Today count drops by the marketing rows and no real matter card is touched. This is an AH1 Tier-B ops step, logged to `baker_actions`.

---

## OPEN ITEM — Director decision (business, not technical)
**MO Residences sales-lead mail ("Your Interest in Mandarin Oriental Residences").** 20 pending rows, mixed:
- ~17 are Brisengroup **outbound auto-sends** ("Sales Team | Brisengroup", "Mykola Borsak | Brisengroup") — Director isn't awaiting his own team's reply, so they're noise as *quiet-thread* cards.
- ~3 are **real inbound prospect replies** ("Jernej Omahen — Re:", "Ines Wöckl — Re:") — live MOVIE sales pipeline, genuine signal.

A content filter can't safely split these (same subject). Options: (a) leave all in the feed (v1 default — safe, slightly noisy); (b) route the *outbound-direction* ones to a "Sales pipeline" bucket off the action feed (needs the direction signal + a bucket — separate brief, MOVIE-desk input); (c) suppress at the sentinel by sender-org. **Default in this brief: (a) — untouched.** Decision belongs to Director / MOVIE desk, not this filter.

## Follow-ups (out of scope; note, don't build)
- **Upstream sentinel suppression** — the deeper fix per audit #12 is that `proactive_pm_sentinel` should not *create* a quiet-thread alert for a no-reply/bulk sender at all, which would also clean the legacy V1 feed + morning brief (the bridge filter only protects the V2 Today feed). Larger change (needs sender carried into `structured_actions` or extracted at sentinel time); separate brief.
- Semantic / entity-level dedup (audit #6), null-entity rendering (#10), cross-matter fan-out (#11) — separate consolidated-brief workstreams.
