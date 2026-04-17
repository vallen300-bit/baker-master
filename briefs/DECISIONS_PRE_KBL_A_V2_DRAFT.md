# Pre-KBL-A Decision Log — V2.1 (DRAFT)

**Status:** DRAFT v2.1 — post Code Brisen round-1 review, awaiting second pass + Director ratification
**Supersedes:** `briefs/DECISIONS_PRE_KBL_A.md` (v1, 6 decisions) and v2 draft commit `5cc48ec`
**Date:** 2026-04-17
**Prepared by:** AI Head (Claude Opus 4.7)
**Review lineage:** v1 → Code Brisen R1 (6 fixes + 6 gaps) → AI Head R2 (6 tweaks) → v2 draft → Code Brisen R3 (5 blockers + 15 should-fix + 6 nice-to-have + 6 missing) → **this v2.1**
**Director sign-offs received:** D2 redirect to queue-poll pattern (drop HTTP endpoint); `feature-dev:code-reviewer` subagent smoke-tested and available

---

## What Changed From V2 (60-second summary)

- **12 decisions → 15 decisions.** Three new: D13 config deployment, D14 cost tracking runtime, D15 logging/observability.
- **Biggest architectural change: D2 redirected.** HTTP endpoint on Mac Mini dropped entirely. Gold promotion now flows WhatsApp → WAHA/Render → `gold_promote_queue` PG table → Mac Mini cron polls. No Tailscale-on-Render work. Director signed off.
- **D1 circular ratification fixed.** Eval set of 50 signals built NOW from existing PG data (pre-shadow), not during shadow.
- **D6 restored value for Phase 1.** Two gates auto-proceed in Phase 1 (cost-envelope, subagent review) instead of all-deferred.
- **3 missing schema tables now specified:** `kbl_runtime_state`, `kbl_cost_ledger`, `kbl_log`, `gold_promote_queue`. Plus `signal_queue` additions.
- **5 Code Brisen blockers resolved in-spec. 11 of 15 should-fixes integrated. 5 of 6 nice-to-haves accepted. 3 of 6 missing decisions promoted to D13-D15; 3 deferred with explicit flag.**

---

## Review Response Log

### Round 3 — Code Brisen on v2 (5 BLOCKERS + 15 SHOULD + 6 NICE + 6 MISSING)

**BLOCKERS (all fixed):**

| # | Finding | V2.1 Action |
|---|---|---|
| B1 | D1 circular ratification (eval-during-shadow) | Build 50-signal eval NOW from PG (pre-shadow). Eval re-run becomes Phase 1 **exit** gate, not entry. |
| B2 | D2 `127.0.0.1:8090` not Tailscale-reachable + no LaunchAgent | Resolved by [S5] — HTTP endpoint dropped entirely. Replaced by queue-poll. |
| B3 | `kbl_runtime_state` undefined | Table defined in D8 + KBL-A schema. |
| B4 | D12 migration target (Render vs Mac Mini) | Render owns migrations. Sequenced deploy: Render first, then Mac Mini. Mac Mini fails fast if table missing. |
| B5 | No env var deployment mechanism | NEW D13. `~/baker-vault/config/env.mac-mini.yml` sourced by cron. Rotation = single commit. |

**SHOULD FIX (11 accepted, 4 with refinement):**

| # | Finding | V2.1 Action |
|---|---|---|
| S1 | `ollama ps` doesn't show GPU | D1 verification: `ollama run gemma4 "ok" --verbose 2>&1 \| grep -iE "metal\|gpu"` |
| S2 | Ollama keep_alive default 5m | Env `OLLAMA_KEEP_ALIVE=-1` (load indefinitely) |
| S3 | Qwen cold-swap → no auto-recovery | Auto-retry Gemma after 10 signals OR 1 h on Qwen. Tracked in `kbl_runtime_state`. |
| S4 | Obsidian Git auto-commit spam | Plugin setting `auto-commit-interval=300` (5-min batching) |
| S5 | Render → Mac Mini HTTP path broken | **D2 redirected.** WhatsApp `/gold` → WAHA → `gold_promote_queue` PG insert → Mac Mini cron drains. No HTTP endpoint. |
| S6 | Layer 0 email-only | Per-source rules spec'd (email/WA/transcripts/Scan) |
| S7 | Key rotation breaks Render | Sequenced rotation: new key → Render first → verify → Mac Mini → revoke old |
| S8 | Bench signals synthetic | Pull 10 real signals from `email_messages`, `whatsapp_messages`, `meeting_transcripts` |
| S9 | p90 cadence = 10% lap | Cadence at **p95** |
| S10 | D6 defer = zero Phase 1 value | Restructured: 2 gates auto-proceed in Phase 1 (cost-envelope, subagent-review); 4 manual |
| S11 | `feature-dev:code-reviewer` availability | **SMOKE-TESTED 2026-04-17, PASS.** Tiered output (CRITICAL/IMPORTANT/MINOR), confidence scores, structured findings. |
| S12 | Circuit-breaker clear condition | After 10 min: send 1-token health check with `skip_circuit` flag. 200 → clear. Error → re-backoff 10 min. |
| S13 | Raw transcripts vs "no raw in vault" | Invariant refined: "no raw **inbound communications** in vault." Transcripts (events, known participants) stay in `raw/transcripts/`. |
| S14 | Failed TTL 90d vs review cadence | `failed` = no auto-purge. `failed-reviewed` (Director-marked) = 90d TTL. |
| S15 | DST transitions | Named-time crons stored UTC, displayed in Europe/Zurich. Current named crons (Sunday 09:00) safe by happenstance. |

**NICE TO HAVE (5 accepted, 1 partial):**

| # | Finding | V2.1 Action |
|---|---|---|
| N1 | GitHub branch protection on baker-vault | Added to D7 + hardening checklist |
| N2 | "Pared prompt" rules undefined | D8 adds phrasing ("drop vault context, keep signal + schema"); full spec in KBL-B |
| N3 | p90 drain math wrong | D10 recovery SLO added: 1000-signal backlog × p95 5 min = 3.5 days drain at serial |
| N4 | `KBL_CRON_TZ` not load-bearing | Env var removed. Mac Mini system TZ set via `systemsetup -settimezone Europe/Vienna` at hardening. |
| N5 | Down-migrations for ADD COLUMN | Soft-deprecation allowed (rename to `deprecated_<col>`, stop writing). Destructive DROP not required. |
| N6 | 70% no-response threshold arbitrary | Accepted as Phase 1 placeholder; revisit with data at Phase 2. |

**MISSING DECISIONS (3 promoted, 3 deferred):**

| # | Finding | V2.1 Action |
|---|---|---|
| M1 | Logging / observability | **NEW D15.** Local rotating files + WARN+ to `kbl_log` PG. |
| M2 | OS update runbook | DEFERRED. Operational doc, not a decision. Task created post-Phase-1. |
| M3 | Vault archival | DEFERRED. Alert at >500 MB (via D15 logging). Archival strategy Phase 2. |
| M4 | Mac Mini unavailability >72h | PARTIAL into D10. Dashboard stale banner + WhatsApp alert at 6 h silence. No Render degraded pipeline Phase 1. |
| M5 | Cost tracking runtime | **NEW D14.** `kbl_cost_ledger` PG table. Pre-call estimate + post-call actual. |
| M6 | `claude -p` harness cost counted? | **YES, in D14.** `claude -p` reports tokens via stdout JSON; captured and logged. |

### Round 2 — AI Head on Code Brisen R1 response (retained from v2, condensed)

All 6 tweaks applied in v2, preserved in v2.1: D1 steelman restructured, D2 MacBook auto-push required (now via Obsidian Git plugin), D3 Layer 0 savings 10-30% (not 30-50%), D6 auto-proceed moved to Phase 2 initially (since restructured in R3 → S10 back to Phase 1 partial), D8 retry temp=0 first + pared prompt, D9 GDPR characterization removed.

### Round 1 — Code Brisen on v1 (retained from v2, condensed)

24 findings all integrated — see v2 for detail. Key: eval set, Qwen cold-swap, determinism, Obsidian plugin auth, matter array, `_inbox/`, entity-map, SSH hardening, flock mutex, ayoniso feedback, subagent gate, etc.

---

## D1 — Lock Gemma 4 8B for Pipeline Steps 1-4

### Steelman for rejected option (Haiku 4 via Anthropic API)
~$0.48/day. No Mac Mini RAM pressure. Rejected on: **(primary) data residency** — 40% of signals triage-drop before Step 5, never leaving Mac Mini if local; **(secondary) Cortex 3T #12b** architectural commitment (Haiku collapses back to 2T). Offline resilience and load balancing are tertiary.

### Spec

**Ratification condition (B1 resolution):**
- Build **pre-shadow eval set: 50 signals** pulled from existing `email_messages`, `whatsapp_messages`, `meeting_transcripts`. Sampling: stratified across source (target 20 email / 15 WA / 15 transcript) and matter (mix of Hagenauer + others to validate classifier, not just vedanā on positive matter).
- Director labels vedanā + expected matter per signal (~60-90 min).
- Run Gemma 4 8B on eval. Required pass: **vedanā accuracy ≥ 90% + JSON validity 100%**.
- If pass, lock D1. If fail, revert to option B (defer + retest).
- Eval re-run at Phase 1 close = Phase 1 **exit** gate (validates no production drift).

**Determinism (env vars):**
- `OLLAMA_MODEL=gemma4:latest`
- `OLLAMA_FALLBACK=qwen2.5:14b`
- `OLLAMA_TEMP=0`
- `OLLAMA_SEED=42`
- `OLLAMA_TOP_P=0.9`
- `OLLAMA_KEEP_ALIVE=-1` (load indefinitely, prevents cold starts at interval >5 min)

**Metal verification (S1 corrected):**
```bash
ssh macmini 'ollama run gemma4:latest "ok" --verbose 2>&1 | grep -iE "metal|gpu|cpu backend"'
```
Must show Metal. CPU backend = FAIL hardening.

**Qwen cold-swap + auto-recovery (S3):**
- Swap triggers on 2-retry Gemma failure (per D8).
- Qwen loaded cold (~25 s first request, then cached).
- **Auto-recovery:** after 10 signals on Qwen OR 1 hour elapsed, next signal retries Gemma. Recovery events logged to `kbl_runtime_state` (rate metric).
- Env: `QWEN_RECOVERY_AFTER_SIGNALS=10`, `QWEN_RECOVERY_AFTER_HOURS=1`

### Ratification
- [ ] **A — Lock Gemma 4 8B + Qwen cold-swap (conditional on 50-signal pre-shadow eval pass)**
- [ ] B — Defer lock, add more signals to eval

---

## D2 — Gold-Promotion via Queue-Poll (REDIRECTED, Director-signed-off)

### What changed from v2
HTTP endpoint on Mac Mini **dropped entirely** (resolved [B2] + [S5]). No FastAPI, no 127.0.0.1 binding, no LaunchAgent for that service, no Tailscale-on-Render.

### Steelman for rejected options
- **Endpoint on Mac Mini (Tailscale-exposed):** real-time response. Rejected: Render isn't on Tailscale, adding it = infra project; binding + LaunchAgent lifecycle = real work; end-to-end complexity higher.
- **fswatch daemon:** real-time. Rejected: macOS-lock, contradicts "fresh process per signal," single-path fragility.

### Spec

**Primary path: queue-poll**
1. Director sends WhatsApp: `/gold <path>` (e.g., `/gold hagenauer-rg7/court-filing-apr16.md`)
2. WAHA on Render receives, routed to KBL-C handler
3. Handler validates: `sender WhatsApp ID == GOLD_WHITELIST_WA_ID`. If fail, log + silent reject (no error reply to avoid probe).
4. Handler checks: `GOLD_PROMOTE_DISABLED=false`. If true, return 503-equivalent WA reply.
5. Handler inserts row: `INSERT INTO gold_promote_queue (path, requested_at, wa_msg_id) VALUES (...)`
6. Mac Mini cron first step: `SELECT ... FROM gold_promote_queue WHERE processed_at IS NULL ORDER BY requested_at LIMIT 10 FOR UPDATE SKIP LOCKED`
7. For each: verify file exists, idempotency check (`author` already `director` → noop), set frontmatter `author: director` + `author_verified_at: <ISO>`, commit with Director git identity, push
8. Mark `processed_at = now()`, `result = 'ok' | 'noop' | 'error:<msg>'`

**Backup path: git-diff-on-pull (unchanged from v2)**
- Second step of every cron batch: `git pull baker-vault`, diff since prior HEAD, any file with `author` flipped to `director` = treated as promotion.
- Catches manual Obsidian edits Director commits+pushes without `/gold` command.
- Idempotent: if queue-poll already processed, noop.

**MacBook Obsidian Git plugin (R2.2 + S4):**
- Plugin installed on Director's MacBook
- `auto-commit-interval=300` (5-min batching, not on-save — avoids commit spam)
- `auto-push=true`
- Commit message template: `auto: obsidian edits <timestamp>`

**Kill-switch:** `GOLD_PROMOTE_DISABLED=true` in config makes KBL-C handler reject all `/gold` commands with a "Gold promotion currently disabled" WA reply. For lost-phone emergency.

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS gold_promote_queue (
  id SERIAL PRIMARY KEY,
  path TEXT NOT NULL,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  wa_msg_id TEXT,
  processed_at TIMESTAMPTZ,
  result TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_gold_queue_pending ON gold_promote_queue (requested_at) WHERE processed_at IS NULL;
```

### Ratification
- [x] **SIGNED OFF BY DIRECTOR** — queue-poll pattern (2026-04-17)
- Residual options removed.

---

## D3 — Hagenauer Signal Scoping (3-Layer, Per-Source Layer 0)

### Steelman for rejected options
- **Entity-map filter at ingest (drop non-matter):** data loss — Phase 2 would miss Cupial signals dropped in Phase 1. Rejected.
- **Process everything through full pipeline:** 20× Opus cost = fails <$10/day cap. Rejected.

### Spec

**Layer 0 — Per-source deterministic filter (S6 corrected):**

| Source | Rule | Typical filter rate |
|---|---|---|
| Email | `List-Unsubscribe` header present OR `Auto-Submitted: auto-replied` OR sender domain in `NEWSLETTER_BLOCKLIST` env | ~30% |
| WhatsApp | Sender in `WA_BLOCKLIST` env OR media-only from non-VIP contact (no text) | ~10-15% |
| Meeting transcripts | `duration_seconds < 60` OR `word_count < 10` | ~5% |
| Scan outputs | N/A (Scan doesn't produce signals) | — |

**Expected overall Layer 0 filter rate: 10-30%** (subject to shadow-mode validation; not 30-50% as earlier estimated).

Env: `LAYER0_ENABLED=true`, `NEWSLETTER_BLOCKLIST=...`, `WA_BLOCKLIST=...`

**Layer 1 — Triage classifier (Step 1 Gemma):**
- All non-filtered signals enqueue with `matter=null`
- Triage returns: `primary_matter` (singular string) + `related_matters` (JSONB array, may be empty) + `triage_confidence` (0-1)
- `primary_matter=null` → routes to `wiki/_inbox/` (Director weekly review)

**Layer 2 — ALLOWED_MATTERS filter (before Step 5):**
- Step 5 Opus fires only if `primary_matter IN ALLOWED_MATTERS` (env)
- Phase 1: `ALLOWED_MATTERS=hagenauer-rg7`
- Non-allowed → `status=classified-deferred`, retained for Phase 2 (zero code change to scale)

**Multi-matter handling:**
- Step 5 runs once on `primary_matter`. No fan-out.
- Step 6 adds cross-links in frontmatter referencing `related_matters[]` for cross-matter discoverability.

**`_inbox/` review automation:**
- Every Sunday 09:00 Europe/Zurich (stored as cron UTC), Baker creates ClickUp task: "KBL _inbox review — N signals pending" with count.

### Ratification
- [ ] **A — 3-layer per-source (entity-map + classifier + ALLOWED_MATTERS)**
- [ ] B — Classifier-only (skip Layer 0)
- [ ] C — Process all (skip Layer 2)

---

## D4 — Secret Migration Timing + Sequenced Rotation (S7)

### Steelman for rejected option (migrate-before-KBL-A)
Clean slate, no plaintext. Rejected for Phase 1 momentum; residual risk mitigated via Tailscale-only SSH + hardening + immediate rotation.

### Spec

**DO NOW (part of Mac Mini hardening, blocks KBL-A dispatch):**

**Sequenced ANTHROPIC_API_KEY rotation (S7):**
1. Generate NEW `ANTHROPIC_API_KEY` via Anthropic console (old stays valid through 24 h grace)
2. Update Render env var → Render auto-redeploys → verify Baker healthy
3. Update Mac Mini `~/.zshrc` → `source` in active sessions → restart any services reading it
4. Verify both sides: `curl -H "x-api-key: $NEW_KEY" https://api.anthropic.com/v1/messages ...` returns 200 from each host
5. Revoke OLD key via Anthropic console

**Sequenced DATABASE_URL rotation:**
1. Create new Neon role with same perms (or new password for existing role)
2. Update Render env → Render restarts → verify all sentinels reconnect
3. Update Mac Mini `~/.zshrc` → restart any DB-connecting services
4. Drop old role / revoke old password

**SSH hardening:**
- `/etc/ssh/sshd_config`: `PasswordAuthentication no`, `PermitRootLogin no`, `AllowUsers dimitry`
- Reload: `sudo launchctl kickstart -k system/com.openssh.sshd`
- Verify via second SSH session BEFORE committing the reload

**Mac Mini uses SSH key for git** (not PAT). Verify `git -C ~/baker-vault remote -v` shows git@ format.

**Shell config perms:** `chmod 600 ~/.zshrc` verify.

**DO LATER (Phase 1 close-out, week 4-5):**
- 1Password Plan A migration: `op` items, `.zshrc` rewritten to `$(op read ...)`, LaunchAgent plists updated (scope includes plist, not just zshrc).

### Ratification
- [ ] **A — Sequenced rotation + SSH hardening NOW; 1Password migration post-Phase 1**
- [ ] B — Full 1Password migration before KBL-A dispatch (~45 min blocker)

---

## D5 — `claude -p` Serial Concurrency via Flock + p95 Cadence (S8, S9)

### Steelman for rejected options
- **Bounded parallel 2-3:** throughput. Rejected: Mac Mini ~8 GB headroom insufficient for 2-3 × (2-4 GB claude -p). Debugging concurrency in Phase 1 low-value.

### Spec

**Serial via file mutex:**
```bash
# /etc/cron.d/kbl-pipeline (or launchd plist equivalent)
*/2 * * * * flock -n /tmp/kbl-pipeline.lock -c '/usr/local/bin/kbl-pipeline-tick.sh'
```
- `flock -n` non-blocking; lock held → cron exits immediately, next interval retries
- `FOR UPDATE SKIP LOCKED` on `signal_queue` is cross-process safety (belt+suspenders)
- Combined invariant: **≤1 `claude -p` at any moment**

**Bench-before-cadence (S8 real signals):**
- Pull 10 real signals from PG: stratified 5 email + 3 WA + 2 transcript (per D1 eval set lineage — can reuse). Sizes: 2 short, 6 medium, 2 long.
- Run full pipeline (Layer 0 → Step 8) on each.
- Measure wall-clock per signal: p50, p90, **p95**, p99.
- Cadence = `ceil(p95)` rounded to minute.
- If p95 > 10 min: cron at every 10 min, but investigate why (likely Opus cache cold — KBL-B can pre-warm).

**Cadence env:** `KBL_CRON_INTERVAL=*/2 * * * *` (default, overridden per bench).

### Ratification
- [ ] **A — Serial via flock + cadence locked post-bench at p95**
- [ ] B — Bounded parallel 2-3 (override)

---

## D6 — Decision-Gate Auto-Proceed (Phase 1 Partial, per S10)

### What changed from v2
v2 deferred ALL auto-proceed to Phase 2 (zero Phase 1 value). v2.1 enables **2 auto-proceed gates in Phase 1** that don't need shadow-mode data.

### Subagent availability (S11 resolved)
`feature-dev:code-reviewer` smoke-tested 2026-04-17 in AI Head session. **PASS.** Output tiered CRITICAL/IMPORTANT/MINOR with confidence scores. Suitable for gate 3 auto-proceed in Phase 1. Before activating in Code Brisen's harness, one smoke test there is required (task F in current Code Brisen #2 parallel work).

### Phase 1 gate table

| Gate | Phase 1 mode | Rule |
|---|---|---|
| **KBL brief ratification** | MANUAL | Always Director |
| **Post-brief pre-dispatch cost check** | AUTO-PROCEED IF | Projected cost (tokens × price) within `DAILY_COST_CAP`; no new vendor; no new SPOF. Automated via pre-dispatch script. |
| **Architecture review subagent pass** | AUTO-PROCEED IF | `feature-dev:code-reviewer` returns 0 CRITICAL + ≤2 IMPORTANT findings on the brief + implementation PR |
| **Production flag flip** | MANUAL | Always Director |
| **Mid-shadow threshold review** | MANUAL (Phase 1) | Eval set built here; Phase 2 can auto-proceed on thresholds |
| **Phase-to-phase scale** | MANUAL | Always Director |

**Phase 1 result:** 2 auto-proceed + 4 manual. Saves ~2-4 days vs all-manual.

### Ayoniso response policy (Phase 1 metrics)

- 👍 (reply within 24 h) = TP
- 👎 (reply within 24 h) = FP
- **No response in 24 h = ambiguous, excluded from denominator**. Tracked separately as `no_response_rate`.
- If `no_response_rate > 70%`: signal alerts are too low-signal → reduce alert rate or tighten triage. Threshold is Phase 1 placeholder; revisit with data.

**Cost threshold scope:** `DAILY_COST_CAP=15` (USD) applies to **KBL pipeline only** — Opus Step 5, Sonnet Step 6, Haiku ayoniso, `claude -p` harness. Does NOT include Baker Scan, brief generation, non-KBL costs.

### Ratification
- [ ] **A — Phase 1 2-auto + 4-manual per table**
- [ ] B — All gates manual Phase 1 + 2
- [ ] C — Override specific gate: ____________________

---

## D7 — Vault Commit Authorship + Branch Protection (N1)

### Spec

**Git identity matrix:**
| Writer | Author | Scope |
|---|---|---|
| Pipeline | `Baker Pipeline <baker@brisengroup.com>` | Silver wiki writes, cetasika cascades, auto-formatting |
| Gold promotion via queue | `Dimitry Vallen <dvallen@brisengroup.com>` | Triggered by `/gold` command |
| Manual Obsidian edits | Director's local git identity | Director-authored content |

**Enforcement:**
- Commit-msg hook in `baker-vault/.git/hooks/commit-msg` rejects commits from `Baker Pipeline` identity if they touch any file with frontmatter `author: director`.
- **GitHub branch protection on `vallen300-bit/baker-vault` main (N1):**
  - `required_linear_history=true`
  - `allow_force_pushes=false`
  - `allow_deletions=false`
  - Signed commits required for changes to `wiki/**/*.md` with frontmatter `author: director` **IF** Director has GPG configured (otherwise flag as hardening item, don't block)

### Ratification
- [ ] **Adopt as spec'd**
- [ ] Modify: ____________________

---

## D8 — Retry Policy + Circuit Breaker + Runtime State (B3 + S12)

### Spec

**Gemma retry ladder:**
1. Retry 1: same model, `temp=0`, **pared prompt** (N2: drop vault context, keep signal + schema). ~1 s.
2. Retry 2: same model, `temp=0.3`. ~4 s.
3. Retry 3: Qwen cold-swap, `temp=0`. ~25 s.
4. DLQ: `signal_queue.status='failed'`, error logged to `kbl_log` (D15).

**Anthropic retry ladder (Opus Step 5 / Sonnet Step 6):**
- Backoff: 10 s → 30 s → 120 s → DLQ
- **5xx ≠ 429.** 429 (rate limit): backoff only. 5xx: backoff + increment consecutive-5xx counter in `kbl_runtime_state`. If counter ≥ 3 → circuit opens.

**Circuit breaker (B3 + S12):**
- State in `kbl_runtime_state` table (NEW — see schema below).
- Open: `kbl_runtime_state['anthropic_circuit_open'] = 'true'`. Steps 5-6 halt. Signals queue, don't process.
- **Clear condition (S12):** after 10 min open, automated health check:
  ```
  POST /v1/messages with minimal 1-token request, header skip_circuit=true
  ```
  - 200 → `anthropic_circuit_open = 'false'`, counter reset
  - Error → re-backoff 10 min, retry health check
- Health check calls use `skip_circuit=true` flag to avoid recursive self-block.

**Runtime state schema:**
```sql
CREATE TABLE IF NOT EXISTS kbl_runtime_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by TEXT
);
-- Seed keys (all optional, nullable default):
-- anthropic_circuit_open: 'false'
-- anthropic_5xx_counter: '0'
-- qwen_active: 'false'
-- qwen_swap_count_today: '0'
-- qwen_active_since: <timestamp>
```

### Ratification
- [ ] **Adopt retry + circuit-breaker + runtime-state spec**
- [ ] Modify: ____________________

---

## D9 — PII Retention (S13 + S14 refinements)

### Spec

**`signal_queue` TTL hierarchy:**
- `status='done' OR 'classified-deferred'` → 30 d TTL (auto-purge)
- `status='failed'` → **no auto-purge** (S14 — Director-on-vacation protection)
- `status='failed-reviewed'` → 90 d TTL (Director explicitly marked post-review)
- `status='pending' OR 'in_progress'` → no TTL until processed; cap via `MAX_SIGNAL_QUEUE_SIZE` (D10)
- Automated purge: daily cron `DELETE FROM signal_queue WHERE status IN ('done','classified-deferred') AND updated_at < now() - interval '30 days'`

**Vault retention (per-source, S13):**

| Content class | Vault | PG |
|---|---|---|
| Extracted entities / summaries (wiki pages) | YES (`wiki/`, no auto-purge) | mirrored in `wiki_pages` cache |
| Raw INBOUND communications (email bodies, WhatsApp text) | **NO** (raw stays in PG only: `email_messages`, `whatsapp_messages`) | YES |
| Raw TRANSCRIPTS (Fireflies, Plaud, YouTube) | YES (`raw/transcripts/`) — captured events, known participants, distinct PII class | YES |
| Scan outputs | YES (`wiki/` under matter) | YES |

**Vault `wiki/` retention policy:** OPEN ITEM flagged for **Phase 1 close-out**. Director to specify per-matter retention (Hagenauer permanent? Cupial 5 years? etc.). Brisen is a legal entity processing counterparty data — GDPR-adjacent, requires documented policy.

### Ratification
- [ ] **Adopt TTL hierarchy + per-source vault policy (retention policy open for Phase 1 close-out)**
- [ ] Modify: ____________________

---

## D10 — Network Partition + Recovery SLO (M4 partial + N3)

### Spec

**Partition behavior:**
- Render side: `signal_queue` on Neon, always writable. No Mac Mini dependency for enqueue.
- Mac Mini side: cron fires, can't reach PG, `flock` exits cleanly. Next cron retries.
- Queue growth cap: `MAX_SIGNAL_QUEUE_SIZE=10000` (env). At cap: reject new enqueue, alert Director via WhatsApp.

**Priority-based TTL on `pending`:**
- `priority=critical` → never dropped
- `priority=high` → 7 d TTL on `pending`
- `priority=normal` → 3 d TTL
- `priority=low` → 24 h TTL

**>72 h Mac Mini unavailability (M4 partial):**
- Dashboard renders "Tier 2 OFFLINE — last heartbeat <timestamp>" banner
- Baker sends Director WhatsApp alert at 6 h of Mac Mini silence (heartbeat table polled by Render)
- Signals continue queuing; priority=low starts TTL-dropping at 24 h
- No Render-side degraded pipeline Phase 1 (explicit 3T choice)

**Recovery SLO (N3):**
- At serial D5 + p95 5 min processing: 1000-signal backlog drains in ~5000 min = **~3.5 days**
- Shadow mode expected volume ~100 signals/day = backlog accumulates ~0.5 day per day of partition
- Acceptable up to ~3 days partition before backlog exceeds daily drain capacity

### Ratification
- [ ] **Adopt partition + recovery SLO spec**
- [ ] Modify: ____________________

---

## D11 — Clock / Timezone (N4: env var removed)

### Spec

- **Storage:** all timestamps PG `TIMESTAMPTZ`, canonical UTC.
- **Signal deadlines:** payload carries explicit IANA TZ: `{"deadline": "2026-05-12T14:00:00", "deadline_tz": "Europe/Vienna"}`.
- **Display:** UI converts to Director's Europe/Zurich at render time.
- **Cron scheduling:**
  - Interval-based crons (`*/2 * * * *`) — TZ-independent, use Mac Mini system TZ (Europe/Vienna)
  - Named-time crons (e.g., Sunday 09:00) — stored as UTC (`0 7 * * 0` = 09:00 Europe/Zurich CEST, `0 8 * * 0` CET). Document accepted pair.
- **Mac Mini system TZ setup (N4 replaces env var):**
  ```bash
  sudo systemsetup -settimezone Europe/Vienna
  ```
  Part of hardening checklist. No `KBL_CRON_TZ` env var (was documentation-only).

### Ratification
- [ ] **Adopt clock/TZ spec**
- [ ] Modify: ____________________

---

## D12 — Schema Migration (B4: Render owns, sequenced deploy)

### Spec

**Migration owner:** Render. All `_ensure_*` calls run at Render app startup via existing `SentinelStoreBack` or equivalent init path. Mac Mini code is a **consumer** — reads/writes tables but does NOT create them.

**Deploy sequence (enforced by brief dispatch order):**
1. KBL-A PR merged → Render auto-deploys → `_ensure_kbl_runtime_state`, `_ensure_kbl_cost_ledger`, `_ensure_kbl_log`, `_ensure_gold_promote_queue`, `_ensure_signal_queue_additions` all run on startup
2. Verify via PG: `\d kbl_runtime_state` etc. present
3. THEN Mac Mini code pulled + `launchctl unload && load` on relevant LaunchAgents
4. Mac Mini cron fires, expects tables present. Fails fast with `TableNotFound` error if not.

**Additive changes:** `ALTER TABLE ... ADD COLUMN IF NOT EXISTS <col> <type> DEFAULT <value>` (N5 down-migration = soft-deprecate: `ALTER RENAME TO deprecated_<col>`).

**Breaking changes (type change, rename, drop):** require **explicit down-migration SQL** in the brief that introduces the change. Reviewer verifies down-migration works on copy before dispatch.

**Backfill:** any NEW NOT NULL column requires backfill SQL + estimated runtime. Tables >100K rows run backfill in batches of 10K.

**No Alembic for Phase 1.** Revisit if >5 migrations per brief.

### Ratification
- [ ] **Adopt migration spec + deploy sequence**
- [ ] Modify: ____________________

---

## D13 — Config Deployment Mechanism (NEW, per B5)

### Question
How are ~20 env vars deployed and kept in sync across MacBook / Mac Mini / Render without manual drift?

### Spec

**Source of truth: `~/baker-vault/config/env.mac-mini.yml`** (committed to baker-vault repo)

```yaml
# Mac Mini config (tunables only — NO SECRETS)
# Secrets stay in ~/.zshrc (or op:// post-migration)
ollama:
  model: "gemma4:latest"
  fallback: "qwen2.5:14b"
  temp: 0
  seed: 42
  top_p: 0.9
  keep_alive: "-1"

matter_scope:
  allowed: ["hagenauer-rg7"]
  layer0_enabled: true
  newsletter_blocklist: ["newsletter.example.com"]
  wa_blocklist: []

gold_promote:
  disabled: false
  whitelist_wa_id: "41799605092@c.us"

pipeline:
  cron_interval: "*/2 * * * *"
  triage_threshold: 40
  max_queue_size: 10000
  qwen_recovery_after_signals: 10
  qwen_recovery_after_hours: 1

cost:
  daily_cap_usd: 15
  max_alerts_per_day: 20

flags:
  pipeline_enabled: false  # flipped true at go-live
```

**Deploy mechanism:**
1. Mac Mini cron wrapper (`/usr/local/bin/kbl-pipeline-tick.sh`) first step: `git -C ~/baker-vault pull`
2. Wrapper sources config via yq: `eval $(yq -r 'to_entries[] | "export KBL_\(.key | ascii_upcase)=\(.value)"' ~/baker-vault/config/env.mac-mini.yml)` (flattened naming convention: `KBL_OLLAMA_MODEL`, etc.)
3. Pipeline Python reads via `os.getenv("KBL_OLLAMA_MODEL")`
4. **Rotation = edit yml, commit, push.** Next cron (≤2 min) picks up.

**Secrets stay out:** `ANTHROPIC_API_KEY`, `DATABASE_URL`, `QDRANT_*`, `VOYAGE_API_KEY` — in `.zshrc` (or `op` post-migration). NOT in env.mac-mini.yml.

**Render config:** Render env vars set via Render dashboard. Overlap (like `ANTHROPIC_API_KEY`) duplicated intentionally. NON-SECRET tunables like `DAILY_COST_CAP` — either duplicate on Render or read from a separate `config/env.render.yml` in baker-vault. **Phase 1: Render env set manually via dashboard. Phase 2: consider auto-deploy from baker-vault.**

### Ratification
- [ ] **Adopt: env.mac-mini.yml in baker-vault + cron-sourced**
- [ ] Modify: ____________________

---

## D14 — Cost Tracking Runtime Mechanism (NEW, per M5 + M6)

### Question
How is `DAILY_COST_CAP` enforced? Where are costs logged? Is `claude -p` harness cost counted?

### Spec

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS kbl_cost_ledger (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  signal_id UUID REFERENCES signal_queue(id),
  step TEXT NOT NULL,                -- 'layer0' | 'triage' | 'resolve' | 'extract' | 'classify' | 'opus_step5' | 'sonnet_step6' | 'claude_harness' | 'ayoniso'
  model TEXT NOT NULL,               -- 'gemma4:latest' | 'qwen2.5:14b' | 'claude-opus-4' | 'claude-sonnet-4' | 'claude-haiku-4' | 'claude-harness-p'
  input_tokens INTEGER,
  output_tokens INTEGER,
  cost_usd NUMERIC(10,6),            -- 0 for local Gemma/Qwen
  success BOOLEAN NOT NULL DEFAULT TRUE,
  metadata JSONB
);
CREATE INDEX IF NOT EXISTS idx_cost_ledger_day ON kbl_cost_ledger ((ts::date));
```

**Enforcement:**
- **Pre-call estimate:** before Step 5 Opus / Step 6 Sonnet, query `SELECT COALESCE(SUM(cost_usd),0) FROM kbl_cost_ledger WHERE ts::date = now()::date`. If `+ estimated_cost > DAILY_COST_CAP`: **circuit opens**, signal completes with `status='cost-deferred'`, skip to next cron (resumes at UTC midnight).
- **Post-call actual:** log row with actual token counts from Anthropic response `usage` field.
- `claude -p` (M6): harness invocation logs its own `input_tokens + output_tokens` from the `claude -p --output-format json` response. Counted.
- **Local models (Gemma, Qwen):** `cost_usd=0`, but tokens still logged for throughput metrics.

**Dashboard:**
- Daily cost rollup query: `SELECT step, SUM(cost_usd), SUM(input_tokens+output_tokens) FROM kbl_cost_ledger WHERE ts::date = now()::date GROUP BY step`
- Served by existing baker-master dashboard (KBL-C extends).

**Cost ceiling behavior:**
- Hard cap: `DAILY_COST_CAP` breached → circuit opens for rest of UTC day.
- Soft alert: at 80% of cap, WhatsApp alert "KBL at 80% daily cap ($12/$15)".

### Ratification
- [ ] **Adopt cost-ledger schema + enforcement + alerts**
- [ ] Modify: ____________________

---

## D15 — Logging & Observability (NEW, per M1)

### Question
Where do KBL pipeline logs go? How does Director debug shadow-mode surprises?

### Spec

**Local rotating logs on Mac Mini:**
- Destination: `/var/log/kbl/pipeline.log` (DEBUG+)
- Rotation: `/etc/newsyslog.d/kbl.conf` — 10 MB per file, 7 files retained (~70 MB max)
- Mirror to Dropbox: daily `rsync` at 23:50 Europe/Vienna to `~/Dropbox-Vallen/_02_DASHBOARDS/kbl_logs/`

**PG central log (WARN+):**
```sql
CREATE TABLE IF NOT EXISTS kbl_log (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  level TEXT NOT NULL,               -- 'WARN' | 'ERROR' | 'CRITICAL'
  component TEXT NOT NULL,           -- 'layer0' | 'triage' | 'pipeline' | 'gold_promote' | 'circuit_breaker' | ...
  signal_id UUID,
  message TEXT NOT NULL,             -- short, not full bodies
  metadata JSONB
);
CREATE INDEX IF NOT EXISTS idx_kbl_log_day_level ON kbl_log (ts::date, level);
```

**What goes where:**
- DEBUG/INFO: local file only (cheap, verbose)
- WARN+: local file + PG (query-able from dashboard)
- CRITICAL: local + PG + **WhatsApp alert to Director** (with 5-min dedupe by `component + message` hash)

**Vault size monitoring (M3 partial):**
- Daily cron on Mac Mini: `du -sm ~/baker-vault` → INSERT row into `kbl_log` as INFO level
- Alert at >500 MB (WARN), >1 GB (CRITICAL with archival guidance)

**Canary / heartbeat (supports KBL-A monitoring):**
- Every 30 min, pipeline wrapper pings `kbl_runtime_state['mac_mini_heartbeat'] = now()`
- Render-side monitor: alerts if heartbeat >30 min stale (silent failure detector, per Cortex 3T intent)

### Ratification
- [ ] **Adopt logging + observability spec**
- [ ] Modify: ____________________

---

## Env Var Master List (v2.1)

Every tunable has a default. Per D13, Mac Mini tunables live in `~/baker-vault/config/env.mac-mini.yml`. Secrets stay in `.zshrc`. Render env via dashboard.

| Var (after yml flatten) | Default | Source |
|---|---|---|
| `KBL_OLLAMA_MODEL` | `gemma4:latest` | D1 |
| `KBL_OLLAMA_FALLBACK` | `qwen2.5:14b` | D1 |
| `KBL_OLLAMA_TEMP` | `0` | D1 |
| `KBL_OLLAMA_SEED` | `42` | D1 |
| `KBL_OLLAMA_TOP_P` | `0.9` | D1 |
| `KBL_OLLAMA_KEEP_ALIVE` | `-1` | D1/S2 |
| `KBL_QWEN_RECOVERY_AFTER_SIGNALS` | `10` | D1/S3 |
| `KBL_QWEN_RECOVERY_AFTER_HOURS` | `1` | D1/S3 |
| `KBL_ALLOWED_MATTERS` | `hagenauer-rg7` | D3 |
| `KBL_LAYER0_ENABLED` | `true` | D3 |
| `KBL_NEWSLETTER_BLOCKLIST` | `""` (CSV) | D3 |
| `KBL_WA_BLOCKLIST` | `""` | D3 |
| `KBL_GOLD_PROMOTE_DISABLED` | `false` | D2 |
| `KBL_GOLD_WHITELIST_WA_ID` | `41799605092@c.us` | D2 |
| `KBL_CRON_INTERVAL` | `*/2 * * * *` (post-bench) | D5 |
| `KBL_TRIAGE_THRESHOLD` | `40` | existing |
| `KBL_DAILY_COST_CAP` | `15` (USD, KBL-only) | D6/D14 |
| `KBL_MAX_ALERTS_PER_DAY` | `20` | D6 |
| `KBL_MAX_SIGNAL_QUEUE_SIZE` | `10000` | D10 |
| `KBL_PIPELINE_ENABLED` | `false` (flips `true` at go-live) | existing |

**Removed from v2:** `KBL_CRON_TZ` (N4 — not load-bearing, replaced by Mac Mini `systemsetup`).

**Runtime state (NOT env vars, live in `kbl_runtime_state` PG table per D8):**
- `anthropic_circuit_open`, `anthropic_5xx_counter`, `qwen_active`, `qwen_active_since`, `qwen_swap_count_today`, `mac_mini_heartbeat`

---

## Ratification Checklist

Tick the recommended option (or override) for each:

- [ ] **D1** — Gemma 4 8B + Qwen cold-swap (conditional on 50-signal pre-shadow eval ≥90% vedanā)
- [x] **D2** — Queue-poll pattern (DIRECTOR-SIGNED 2026-04-17)
- [ ] **D3** — 3-layer per-source scoping
- [ ] **D4** — Sequenced rotation + SSH hardening NOW; 1Password post-Phase 1
- [ ] **D5** — Serial via flock + p95 cadence post-bench
- [ ] **D6** — Phase 1: 2-auto-proceed + 4-manual gates
- [ ] **D7** — Vault commit matrix + GitHub branch protection
- [ ] **D8** — Retry ladders + circuit breaker + `kbl_runtime_state` table
- [ ] **D9** — TTL hierarchy + per-source vault policy (wiki retention open for Phase 1 close-out)
- [ ] **D10** — Partition + recovery SLO
- [ ] **D11** — Clock/TZ (UTC storage, IANA in payload, system TZ Europe/Vienna)
- [ ] **D12** — Render-owns-migrations + sequenced deploy
- [ ] **D13** — Config deployment via `env.mac-mini.yml` in baker-vault
- [ ] **D14** — Cost tracking via `kbl_cost_ledger` + circuit at cap
- [ ] **D15** — Logging: local rotating + PG WARN+ + Dropbox mirror + heartbeat

---

## Deferred (flagged for post-Phase-1 or Phase 2)

| Item | Reason | Target |
|---|---|---|
| M2 OS update runbook | Operational doc, not decision | Post-Phase 1 documentation task |
| M3 Vault archival strategy | Alert at >500 MB covers Phase 1 | Phase 2 design |
| Wiki retention policy per matter | Not blocking Phase 1 pipeline | Phase 1 **close-out** (mandatory before Phase 2) |
| `feature-dev:code-reviewer` in Code Brisen harness smoke test | Confirmed available in AI Head Claude app; harness verification outstanding | Before first D6 auto-proceed activation |
| 1Password secret migration | D4 explicit deferral | Phase 1 close-out |
| UPS (APC BE600) | Hardware delivery | Concurrent with other hardening |

---

## After Ratification

AI Head writes `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md` (3T version) incorporating every decision above plus:
- Schema SQL for: `signal_queue` additions, `kbl_runtime_state`, `kbl_cost_ledger`, `kbl_log`, `gold_promote_queue` (Code Brisen #2 pre-stages per parallel task E)
- Deploy sequence: Render first, Mac Mini second
- Mac Mini hardening checklist (rotate keys, SSH config, GitHub branch protection, Obsidian Git plugin setup, system TZ, `env.mac-mini.yml` created)
- Flock wrapper, cron entry, LaunchAgent plists (no HTTP endpoint needed per D2)
- Reference to this ratified v2.1 for every decision locked

Brief submitted for Code Brisen architecture review → Director ratification → dispatch.

**Time estimate:** KBL-A brief 2-3 h (bigger than v2 estimate due to v2.1 scope growth — pre-staged schema helps).

---

*Prepared 2026-04-17 by AI Head (Claude Opus 4.7). V2.1 post Code Brisen round-1 review. Status: DRAFT pending second review pass + Director ratification.*
