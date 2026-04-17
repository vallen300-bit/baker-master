# Pre-KBL-A Decision Log — V2 (DRAFT)

**Status:** DRAFT — pending Code Brisen architecture review
**Supersedes:** [`briefs/DECISIONS_PRE_KBL_A.md`](DECISIONS_PRE_KBL_A.md) (v1, 6 decisions)
**Date:** 2026-04-17
**Prepared by:** AI Head (Claude Opus 4.7)
**Review lineage:** v1 → Code Brisen critique (6 fixes + 6 gaps) → AI Head critique of response (6 weaknesses) → this v2

---

## What Changed From V1 (read this first — 60 seconds)

- **V1 had 6 decisions. V2 has 12** (6 revised + 6 new: D7–D12).
- **Two rebuttals stand** (D1 Gemma-over-Haiku; D5 serial) with strengthened justifications.
- **All 6 Code Brisen accepts from round 1 are in.**
- **All 6 AI Head tweaks from round 2 are applied** (see Response Log below).
- **Steelman-of-rejected-option** added to each decision (no more recommendation bias).
- **Every tunable is now an env var** with a default — no hardcodes. Master list at bottom.
- **D6 auto-proceed explicitly deferred to Phase 2** (eval set and FP labels don't exist during shadow mode).

---

## Review Response Log

### Round 1 — Code Brisen findings on v1 (all accepted)

| # | Finding | V2 Action |
|---|---|---|
| R1.1 | D1 eval set of 5 is a smoke test | D1 ratification is **conditional** on 50–100 signal Director-labeled eval built during shadow mode |
| R1.2 | D1 warm-fallback physics fails | D1 Qwen spec'd as **cold-swap only** (20–30 s SLO hit) |
| R1.3 | D1 non-determinism | D1 locks `temp=0, seed=42, top_p=0.9` in env |
| R1.4 | D1 Metal backend unverified | Pre-lock step: `ollama ps` + Activity Monitor GPU check on Mac Mini |
| R1.5 | D2 vault directionality ambiguous | D2 spec'd (see below) + **auto-push mechanism required** on MacBook (round-2 strengthening) |
| R1.6 | D2 endpoint host unclear | D2 hosts endpoint on **Mac Mini** (FastAPI on Tailscale), preserves single-writer |
| R1.7 | D2 WhatsApp `/gold` auth | Whitelist Director's WhatsApp ID (`41799605092@c.us`); kill-switch env var added |
| R1.8 | D2 race condition | Idempotency: noop if already `author: director`; commit only on change |
| R1.9 | D2 Gold-downgrade history | Out of scope Phase 1 — git log is truth. Phase 2 observability. |
| R1.10 | D3 multi-matter | `primary_matter` + `related_matters[]`; Step 5 fires once; Step 6 cross-links |
| R1.11 | D3 null-matter policy | Routes to `wiki/_inbox/`; weekly Director review automated via ClickUp task |
| R1.12 | D3 misclassification reconciliation | Phase 2 item — flagged explicitly |
| R1.13 | D3 "Gemma is free" imprecise | Rephrased: "no Anthropic API cost; local compute non-zero but trivial" |
| R1.14 | D3 entity-map pre-filter | Added as **layer 0** — drops obvious noise at signal_queue insert |
| R1.15 | D4 LaunchAgent plist migration | Migration scope includes plist rewrite + reload |
| R1.16 | D4 vault PAT | Mac Mini uses **SSH key** for git; only Render has `GITHUB_VAULT_TOKEN` |
| R1.17 | D4 rotation skipped by deferral | Rotate `ANTHROPIC_API_KEY` + `DATABASE_URL` **now**, independently of migration (~10 min) |
| R1.18 | D4 SSH hardening | `sshd_config`: `PasswordAuthentication no`, `PermitRootLogin no`, `AllowUsers dimitry` |
| R1.19 | D5 serial-emergent-parallel bug | **flock mutex** required (see D5) |
| R1.20 | D5 5-min assumption untested | Bench actual `claude -p` on Mac Mini before committing cron cadence |
| R1.21 | D6 eval set prerequisite | D6 auto-proceed **deferred to Phase 2** (not Phase 1) |
| R1.22 | D6 ayoniso feedback UX | KBL-C alerts include 👍/👎 WhatsApp reply parsing |
| R1.23 | D6 cost threshold scope | KBL pipeline cost only, NOT total Baker cost |
| R1.24 | D6 self-certification | Gates 2-3 require `feature-dev:code-reviewer` subagent pass; AI Head does not self-cert |

### Round 2 — AI Head tweaks on Code Brisen's response (all applied)

| # | Weakness | V2 Action |
|---|---|---|
| R2.1 | D1 rebuttal "offline resilience" weak | Steelman restructured: **(primary) data residency**, **(secondary) Cortex 3T #12b**, (tertiary) load balancing and offline resilience — not primary |
| R2.2 | D2 MacBook push assumed | MacBook requires **Obsidian Git plugin auto-commit+push on save** OR LaunchAgent auto-push every 5 min. Pick one in ratification; don't rely on Director remembering to push. |
| R2.3 | D3 entity-map savings optimistic | Spec reads "expected 10–30% subject to shadow-mode validation" — not 30–50% |
| R2.4 | D6 auto-proceed impossible in Phase 1 | Explicit: **D6 auto-proceed activates at Phase 2 kickoff**. Phase 1 uses manual gates for all 5 steps. |
| R2.5 | D8 retry temp=0.3 adds drift on first retry | First retry: same `temp=0` with **pared prompt** (drop context, keep instruction). Second retry: `temp=0.3`. Then Qwen cold-swap. Then DLQ. Anthropic backoff: **10 s, 30 s, 120 s**. |
| R2.6 | D9 "different regulatory class" wrong | Removed. Vault retention is **open item** flagged for Phase 1 close-out, not "Director-managed = no policy." Brisen is a legal entity processing counterparty data — GDPR-adjacent, not household-exempt. |

---

## D1 — Lock Gemma 4 8B for Pipeline Steps 1-4

### Question
Which local model does the KBL pipeline use for Steps 1–4 (Triage / Resolve / Extract / Classify) on Mac Mini?

### Steelman for rejected option (Haiku 4 via Anthropic API)
~$0.48/day at 100 signals × 4 steps. Removes Mac Mini RAM pressure. No model-swap dance. Haiku 4 structured output likely 5/5 on the current bench. **Rejected because:**
1. **(primary) Data residency.** ~40% of signals are triage-dropped and never leave Mac Mini if local. With Haiku, every signal's raw content (legal threats, AO financial, Hagenauer insolvency) goes to Anthropic regardless. Meaningful footprint reduction.
2. **(secondary) Cortex 3T #12b architectural commitment.** If Haiku runs Steps 1–4, Mac Mini has no reason to exist in the pipeline — that's 2T with a Render cron, which we explicitly rejected.
3. (tertiary) Load balancing, offline resilience — nice-to-haves, not decisive.

### Benchmark summary (2026-04-16)
| Model | Vedanā | JSON | Avg latency |
|---|---|---|---|
| **Gemma 4 8B** | **5/5** | **5/5** | **4.4 s** |
| Gemma 4 26B MoE | 2/5 ❌ | 3/5 ❌ | 9.0 s |
| Qwen 2.5 14B | 5/5 | 5/5 | 9.1 s |
| Mistral Small 24B | 5/5 | 5/5 | 19.6 s |

**⚠️ N=5 is a smoke test, not an eval.** See conditions below.

### Options
- **A. Lock Gemma 4 8B primary, Qwen 2.5 14B cold-swap fallback** [RECOMMENDED]
- B. Defer lock, test more signals first (delays ~1 week)

### Ratification conditions (must be true for A to stand)
- [ ] Eval set of **50–100 signals** labeled by Director built during shadow mode; Gemma must hit **≥ 90% vedanā accuracy** on it. If below, revisit.
- [ ] Pre-lock verification: `ollama ps` shows `gpu: 100%` on Mac Mini; if CPU-only, latency target invalid.
- [ ] Determinism: `temp=0, seed=42, top_p=0.9` locked in env (not CLI flags).

### Consequences if A
- KBL-A sets `OLLAMA_MODEL=gemma4:latest`, `OLLAMA_FALLBACK=qwen2.5:14b`, `OLLAMA_TEMP=0`, `OLLAMA_SEED=42`, `OLLAMA_TOP_P=0.9`.
- Qwen 2.5 14B pulled to Mac Mini during hardening (not kept warm; cold-swap only on Gemma failure).
- SLO: Gemma primary path 5 s p50; Qwen cold-swap path 25 s p50. Alerting on >10% cold-swap rate.

### Ratification
- [ ] **A — Lock Gemma 4 8B + Qwen cold-swap (conditional on eval set)**
- [ ] B — Defer

---

## D2 — Gold-Promotion Detection (Endpoint + Git-Diff Backup)

### Question
How does the pipeline detect that Director flipped `author: director` on a wiki page?

### Steelman for rejected option (fswatch daemon only)
Real-time (<1 s), purely local, no interface work. Rejected because (a) macOS-locked (fswatch doesn't work on Linux if we ever move Tier 2), (b) daemon process contradicts Cortex 3T #12b "fresh process per signal, no daemon," (c) single-path fragility — one missed event = silent invariant break.

### Spec (Option B in v1 — unchanged recommendation, tightened spec)

**Primary path: `POST /api/gold-promote`**
- **Hosted on:** Mac Mini (new FastAPI service on `127.0.0.1:8090`, exposed via Tailscale). Preserves single-writer invariant.
- **Called by:** (a) WhatsApp `/gold <path>` command parsed by KBL-C, (b) future web UI button.
- **Auth:** WhatsApp caller whitelist — `41799605092@c.us` only. Reject all others, log + alert on rejected attempts.
- **Kill-switch:** env `GOLD_PROMOTE_DISABLED=true` makes endpoint return 503. For emergency (phone lost).
- **Idempotency:** noop if frontmatter already `author: director`; commit only on change.
- **Action:** parse target file, set frontmatter `author: director`, `author_verified_at: <ISO-8601>`, commit with Director's git identity, push.

**Backup path: git-diff-on-pull**
- Every cron batch starts with `git pull`.
- Diff since previous HEAD: any `author` flipped to `director` → treat as promotion.
- Catches the case where Director edits Obsidian + commits + pushes manually.
- Latency: ≤15 min. Acceptable for Gold (no-rush protection).

### MacBook → Mac Mini sync (round-2 strengthening)

**Required:** Director's MacBook must auto-push Obsidian edits to GitHub, OR the backup path never fires for MacBook-originated changes. Two options:
- **B2a. Obsidian Git plugin: auto-commit + auto-push on save** (every N seconds). [RECOMMENDED — no new process on MacBook]
- **B2b. LaunchAgent on MacBook: `cd ~/baker-vault && git add -A && git commit -m auto && git push` every 5 min.** Requires launchctl maintenance.

### Options
- **A. Endpoint + git-diff backup + B2a MacBook Obsidian Git plugin** [RECOMMENDED]
- B. Endpoint + git-diff backup + B2b MacBook LaunchAgent

### Consequences if A
- KBL-A adds `POST /api/gold-promote` endpoint spec
- KBL-A adds git-pull-first-then-diff as initial step of every cron batch
- KBL-C adds WhatsApp `/gold` command parser with whitelist
- Director installs Obsidian Git plugin on MacBook; enabled auto-commit + auto-push
- Env vars: `GOLD_PROMOTE_DISABLED=false`, `GOLD_WHITELIST_WA_ID=41799605092@c.us`

### Ratification
- [ ] **A — Endpoint + git-diff backup + Obsidian Git plugin auto-push**
- [ ] B — Endpoint + git-diff backup + LaunchAgent auto-push
- [ ] C — Reject, propose alternative: ____________________

---

## D3 — Hagenauer Signal Scoping

### Question
How does the pipeline process Hagenauer-only in Phase 1 when signals are cross-matter?

### Steelman for rejected option (process everything, write only Hagenauer)
Day-1 validation of pipeline on full traffic — realistic load test. Rejected because cost fails target: 20× wasted Opus spend on non-Phase-1 matters (~$7.60–14.25/day waste, breaks <$10/day cap).

### Spec (Option B in v1 — unchanged, with tightened multi-matter handling)

**Three layers:**

**Layer 0 — Entity-map pre-filter (new in v2)**
- At `signal_queue` insert time, drop obvious noise: newsletters (List-Unsubscribe header), auto-replies (`Auto-Submitted: auto-replied`), promotional emails (known sender patterns).
- **Expected filter rate: 10–30%** (subject to shadow-mode validation — not 30–50% as initially estimated).
- Purely deterministic rules; no LLM.

**Layer 1 — Triage classifier (Step 1, Gemma)**
- All non-filtered signals enqueue with `matter=null`.
- Triage assigns: `primary_matter` (singular) + `related_matters` (array, may be empty) + `confidence` (0–1).
- `primary_matter=null` if triage can't classify → routes to `wiki/_inbox/`.

**Layer 2 — ALLOWED_MATTERS filter (before Step 5)**
- Step 5 Opus fires only if `primary_matter in ALLOWED_MATTERS` (env).
- Phase 1: `ALLOWED_MATTERS=hagenauer-rg7`.
- Non-allowed: signal marked `status=classified-deferred`, retained for Phase 2.

**Multi-matter handling (tightened):**
- Pipeline runs Step 5 **once on `primary_matter`**. No fan-out.
- Step 6 (Sonnet) adds cross-links in the wiki page frontmatter referencing `related_matters[]`.
- Cost: +0 vs single-matter. Data preserved.

**`_inbox/` review automation:**
- Every Sunday 09:00 Europe/Zurich, Baker creates ClickUp task: "KBL _inbox review — N signals pending" (N from DB count).
- Director triages to proper matter or drops.

### Options
- **A. Layer 0 entity-map + Layer 1 classifier + Layer 2 ALLOWED_MATTERS filter** [RECOMMENDED]
- B. Skip Layer 0 (pure classifier-only)
- C. Skip Layer 2 (process all through full pipeline)

### Consequences if A
- KBL-A schema adds `primary_matter`, `related_matters JSONB`, `triage_confidence NUMERIC(3,2)` to `signal_queue`
- KBL-A env: `ALLOWED_MATTERS=hagenauer-rg7`
- KBL-B Layer 0 implementation ahead of queue insert
- KBL-B Step 5 checks `primary_matter IN (ALLOWED_MATTERS)` before Opus call
- Phase 2 scale = env update: `ALLOWED_MATTERS=hagenauer-rg7,cupial,mo-vie,ao,...` (zero code change)

### Ratification
- [ ] **A — 3-layer (entity-map + classifier + ALLOWED_MATTERS)**
- [ ] B — Classifier-only (skip Layer 0)
- [ ] C — Process all (skip Layer 2)

---

## D4 — Secret Migration Timing (Explicit)

### Question
Migrate 5 plaintext secrets in `~/.zshrc` to 1Password before KBL-A dispatch, or after Phase 1?

### Steelman for rejected option (migrate before KBL-A)
No plaintext secrets on a remote-accessible box. Clean slate. ~45 min blocker. Rejected because Director's stated priority is Phase 1 momentum, and mitigating controls (Tailscale, SSH hardening, immediate key rotation) reduce residual risk.

### Spec (Option A in v1 — unchanged recommendation, expanded scope)

**Do NOW (part of Mac Mini hardening, blocking KBL-A dispatch):**
- [ ] Rotate `ANTHROPIC_API_KEY` (revoke old, issue new, update `~/.zshrc` + Render env)
- [ ] Rotate `DATABASE_URL` password (rotate on Neon, update both sides)
- [ ] SSH harden `/etc/ssh/sshd_config`: `PasswordAuthentication no`, `PermitRootLogin no`, `AllowUsers dimitry`
- [ ] Confirm Mac Mini uses SSH key for `vallen300-bit/baker-vault` (no PAT on disk)
- [ ] Reload sshd: `sudo launchctl kickstart -k system/com.openssh.sshd`

**Do LATER (Phase 1 close-out, week 4–5):**
- [ ] 1Password vault items created for 5 secrets
- [ ] `~/.zshrc` rewritten to use `$(op read "op://Private/ANTHROPIC/key")` pattern
- [ ] LaunchAgent plist(s) rewritten if they reference secrets directly
- [ ] Verify services restart cleanly with `op`-resolved env

### Why this is safe enough for Phase 1
- Tailscale is the only SSH entry path now (no public mDNS, no direct IP exposure)
- Stale SSH sessions cleaned 2026-04-17 (22-day-old logins killed)
- Keys rotated at migration start = fresh credentials regardless
- `~/.zshrc` is readable only by `dimitry` user (mode 0600 if not already — verify during hardening)

### Ratification
- [ ] **A — Rotate now + harden SSH now; migrate 1Password post-Phase 1**
- [ ] B — Full migration before KBL-A dispatch (~45 min blocker)

---

## D5 — `claude -p` Concurrency on Mac Mini

### Question
How many concurrent `claude -p` sessions can run during a cron batch?

### Steelman for rejected options
**B (bounded parallel 2–3):** higher throughput. Rejected: Mac Mini RAM budget (~8 GB headroom after Ollama + system) is insufficient for 2–3 `claude -p` sessions (each 2–4 GB with 200 K context), and debugging concurrency bugs in Phase 1 is low-value.

### Spec (Option A in v1 — corrected for emergent-parallel bug)

**Strict serial via file-level mutex:**

```bash
# Cron entry:
*/2 * * * * flock -n /tmp/kbl-pipeline.lock -c '/usr/local/bin/kbl-pipeline-tick.sh'
```

- `flock -n` = non-blocking. If lock held, cron exits immediately (next cron retries).
- `FOR UPDATE SKIP LOCKED` on `signal_queue` claim is **additional** (not replacement) for cross-process race safety.
- Combined: ≤1 `claude -p` at any moment, no matter how long a signal takes.

**Cron cadence during shadow mode:**
- **TBD after bench.** Initial assumption: every 2 min. Must be validated against actual `claude -p` signal processing time on Mac Mini.
- Bench requirement (blocking before cron cadence lock): process 10 representative signals through full pipeline; measure p50, p90. Set cadence ≥ p90.
- Env: `KBL_CRON_INTERVAL=*/2 * * * *` (default; adjust per bench).

### Bench spec (blocking)
- 10 Hagenauer-like signals (5 email, 3 WhatsApp, 2 meeting-transcript snippets)
- Full pipeline: Steps 0 (Layer 0 filter) → 1 → 2 → 3 → 4 (classify) → 5 (Opus) → 6 (Sonnet) → 7 (commit) → 8 (index)
- Measure: p50, p90, p99 wall-clock per signal
- Report: KBL-A brief author reviews before cron cadence committed

### Ratification
- [ ] **A — Serial via flock + cadence-TBD-per-bench**
- [ ] B — Bounded parallel 2–3 (override)
- [ ] C — External worker pool (Phase 2)

---

## D6 — Decision-Gate Auto-Proceed (Deferred to Phase 2)

### Question
Can roadmap decision gates pre-delegate thresholds to auto-proceed when metrics are clean?

### Round-2 correction
**D6 auto-proceed CANNOT fire during Phase 1 shadow mode** because:
- Eval set for vedanā accuracy is *built* during shadow (doesn't exist pre-shadow)
- FP rate for ayoniso requires Director-labeled alerts via 👍/👎 (no history)
- Cost trajectory is unestablished (no baseline)

**Phase 1:** all 5 gates are **manual**. Director reviews each brief/state check and ratifies.

**Phase 2:** auto-proceed activates per the table below, using the eval set and feedback history built in Phase 1.

### Auto-proceed table (Phase 2)

| Gate | Manual mandatory if | Auto-proceed if |
|---|---|---|
| **KBL brief ratification** | Always — first dispatch always reviewed | — |
| **Post-brief pre-dispatch** | New SPOF, new vendor, cost envelope change >50% | Within envelope + `feature-dev:code-reviewer` subagent clean pass |
| **Mid-build architecture check** | Spec drift from ratified decisions | Implementation-only changes + subagent clean pass |
| **Pre-production flag flip** | Always — production flag flip is human | — |
| **Mid-validation threshold review** | Vedanā <80% OR cost >$15/day (KBL-only) OR ayoniso FP >30% OR ayoniso no-response rate >70% | All within bounds |
| **Phase-to-phase scale** | Always — scale decision is human | — |

**Ayoniso response policy (closing round-2 gap):**
- 👍 = TP
- 👎 = FP
- No response within 24 h = **ambiguous — excluded from denominator but counted in a separate `no_response_rate` metric**. If `no_response_rate >70%`, treat as signal that alerts are too low-signal to warrant Director attention → reduce alert rate or tighten triage.

**Cost threshold scope:** `DAILY_COST_CAP` (env, default `$15`) applies to **KBL pipeline only** — Opus Step 5, Sonnet Step 6, Haiku ayoniso. Does NOT include Baker Scan, brief generation, or other non-KBL Baker costs.

**Gate subagent:** `feature-dev:code-reviewer`. Confirm available in Code Brisen's harness before Phase 2.

### Ratification
- [ ] **A — Phase 1 all-manual; Phase 2 per table**
- [ ] B — Keep all gates manual forever
- [ ] C — Propose alternative: ____________________

---

## D7 — Vault Commit Authorship (NEW)

### Question
Who is the git author on vault commits, and how is it enforced?

### Spec
- **Pipeline commits** (Layer 2 Silver writes, cetasika cascades, auto-formatting): author = `Baker Pipeline <baker@brisengroup.com>`
- **Gold promotions** (via `/api/gold-promote` endpoint): author = `Dimitry Vallen <dvallen@brisengroup.com>`
- **Director manual commits** (Obsidian Git plugin auto-push): author = Director's git identity (local `.gitconfig`)

**Enforcement:** commit-msg hook in `baker-vault/.git/hooks/commit-msg` rejects commits from `Baker Pipeline` identity if they touch any file with frontmatter `author: director` (defensive invariant: Baker Pipeline cannot overwrite Gold).

### Ratification
- [ ] **Adopt as spec'd**
- [ ] Modify: ____________________

---

## D8 — Retry Policy (NEW)

### Question
What happens when a model call fails (invalid JSON, timeout, API error)?

### Spec

**Gemma failure (local Ollama):**
1. **Retry 1:** same model, `temp=0`, **pared prompt** (drop context chunks, keep instruction + signal). ~1 s.
2. **Retry 2:** same model, `temp=0.3`. ~4 s.
3. **Retry 3:** Qwen 2.5 14B cold-swap, `temp=0`. ~25 s.
4. **DLQ:** `signal_queue.status='failed'`, error logged. Director reviews weekly (ClickUp task auto-created).

**Anthropic API error (Opus Step 5 / Sonnet Step 6):**
1. **Backoff 1:** 10 s
2. **Backoff 2:** 30 s
3. **Backoff 3:** 120 s
4. **DLQ:** `signal_queue.status='failed'`, error logged.

**5xx vs 429:**
- 429 (rate limit): backoff as above.
- 5xx: backoff as above BUT if 3 consecutive 5xx, trip circuit breaker (`KBL_ANTHROPIC_CIRCUIT_OPEN=true` in runtime state table) → pause Step 5-6 for 10 min → retry health check → resume.

### Ratification
- [ ] **Adopt as spec'd**
- [ ] Modify: ____________________

---

## D9 — PII Retention (NEW)

### Question
How long is signal content retained, and under what policy?

### Spec

**`signal_queue` table:**
- `status IN ('done', 'classified-deferred')` TTL = 30 days
- `status = 'failed'` TTL = 90 days (needed for debugging)
- `status = 'pending' OR 'in_progress'` no TTL until processed
- Automated purge: daily cron, `DELETE FROM signal_queue WHERE status IN ('done','classified-deferred') AND updated_at < now() - interval '30 days'`

**`vault/` wiki pages:**
- **No auto-purge.** Director manages.
- **Retention policy: OPEN ITEM — flagged for Phase 1 close-out.** Not committing to "Director-managed = no policy" (round-2 correction).
- Brisen is a legal entity processing counterparty data. Vault will contain fragments of third-party communications (lawyers, investors, buyers). Phase 1 close-out deliverable: documented retention policy per matter class.

**Raw signal bodies inside wiki pages:**
- Phase 1: only entity-extracted facts + summaries go into wiki. **Raw email bodies / WhatsApp text do NOT go into vault.** Raw stays in PG (`signal_queue` + existing `email_messages`, `whatsapp_messages` tables).
- Reduces PII surface in the long-retention layer.

### Ratification
- [ ] **Adopt as spec'd (retention policy deferred to Phase 1 close-out)**
- [ ] Modify: ____________________

---

## D10 — Network Partition Resilience (NEW)

### Question
What happens when Render ↔ Mac Mini connectivity fails (home internet out, Tailscale down, ISP rerouting)?

### Spec (cross-reference existing architecture)

- **Render side:** `signal_queue` is on Neon PG. Render writes continue normally. No dependency on Mac Mini for enqueue.
- **Mac Mini side:** when cron fires and cannot reach PG, `flock` exits cleanly. No side effects. Next cron retries.
- **Queue growth cap:** per Cortex 3T #18 — `MAX_SIGNAL_QUEUE_SIZE=10000` (env). When reached, new signals are logged but not enqueued (alert to Director). Prevents unbounded growth during extended partition.
- **TTL-based drop** (per Cortex 3T decision on signal priorities):
  - `priority=critical` → never dropped
  - `priority=high` → 7 days TTL on `pending` status
  - `priority=normal` → 3 days TTL
  - `priority=low` → 24 h TTL
- **Recovery:** when partition heals, cron resumes, backlog drains in p90 × backlog_count minutes.

### Ratification
- [ ] **Adopt as spec'd (cross-ref Cortex 3T #18)**
- [ ] Modify: ____________________

---

## D11 — Clock / Timezone Handling (NEW)

### Question
How are timestamps handled across Render (UTC), Mac Mini (Europe/Vienna), Director (Europe/Zurich)?

### Spec
- **Storage:** all timestamps in PG as `TIMESTAMPTZ` (timezone-aware), canonical UTC.
- **Signal metadata:** when signal has a deadline (court filing, payment due), payload carries explicit IANA TZ string: `{"deadline": "2026-05-12T14:00:00", "deadline_tz": "Europe/Vienna"}`.
- **Display:** UI converts to Director's local TZ at render time (Europe/Zurich). Not the storage layer's job.
- **Cron scheduling on Mac Mini:** cron entries use **Mac Mini's local timezone** (Europe/Vienna) for human readability (09:00 = morning). `KBL_CRON_TZ=Europe/Vienna` env for documentation.
- **Pipeline computations** (e.g., "deadline in <24 h"): always in UTC.

### Ratification
- [ ] **Adopt as spec'd**
- [ ] Modify: ____________________

---

## D12 — Schema Migration Strategy (NEW)

### Question
How do schema changes to `signal_queue` / `wiki_staging` propagate from KBL-A → KBL-B → KBL-C?

### Spec
- **Convention:** existing `_ensure_<table>()` pattern (see `SentinelStoreBack` examples in codebase).
- **Additive changes:** `ALTER TABLE ... ADD COLUMN IF NOT EXISTS <col> <type> DEFAULT <value>` — always safe, idempotent.
- **Column type changes, renames, drops:** require **explicit down-migration SQL** included in the brief that introduces the change. Reviewer verifies down-migration works on a copy before dispatch.
- **No Alembic for Phase 1.** If complexity grows (5+ migrations per brief), revisit in Phase 2.
- **Backfill:** if a new NOT NULL column needs historical values, brief MUST include backfill SQL + estimated runtime. Large tables (>100 K rows) run backfill in batches of 10 K.

### Ratification
- [ ] **Adopt as spec'd**
- [ ] Modify: ____________________

---

## Env Var Master List (all tunables)

Every decision above produces env vars instead of hardcodes. KBL-A brief must document defaults:

| Var | Default | Source decision |
|---|---|---|
| `OLLAMA_MODEL` | `gemma4:latest` | D1 |
| `OLLAMA_FALLBACK` | `qwen2.5:14b` | D1 |
| `OLLAMA_TEMP` | `0` | D1 |
| `OLLAMA_SEED` | `42` | D1 |
| `OLLAMA_TOP_P` | `0.9` | D1 |
| `ALLOWED_MATTERS` | `hagenauer-rg7` | D3 |
| `ENTITY_MAP_ENABLED` | `true` | D3 |
| `GOLD_PROMOTE_DISABLED` | `false` | D2 |
| `GOLD_WHITELIST_WA_ID` | `41799605092@c.us` | D2 |
| `KBL_CRON_INTERVAL` | `*/2 * * * *` (TBD post-bench) | D5 |
| `KBL_CRON_TZ` | `Europe/Vienna` | D11 |
| `TRIAGE_THRESHOLD` | `40` | existing Cortex 3T |
| `DAILY_COST_CAP` | `$15` (KBL-only) | D6 |
| `MAX_ALERTS_PER_DAY` | `20` | D6 (implied) |
| `MAX_SIGNAL_QUEUE_SIZE` | `10000` | D10 |
| `KBL_PIPELINE_ENABLED` | `false` (flips `true` at go-live) | existing roadmap |
| `KBL_ANTHROPIC_CIRCUIT_OPEN` | `false` (runtime flag) | D8 |

---

## Ratification Checklist

Tick the recommended option (or override) for each:

- [ ] **D1** — Lock Gemma 4 8B + Qwen cold-swap (conditional on eval set)
- [ ] **D2** — Endpoint + git-diff backup + Obsidian Git plugin auto-push
- [ ] **D3** — 3-layer scoping (entity-map + classifier + ALLOWED_MATTERS)
- [ ] **D4** — Rotate now, migrate 1Password post-Phase 1
- [ ] **D5** — Serial via flock, cadence TBD per bench
- [ ] **D6** — Phase 1 all-manual; Phase 2 per table
- [ ] **D7** — Vault commit authorship spec'd
- [ ] **D8** — Retry policy spec'd
- [ ] **D9** — PII retention spec'd (vault retention = Phase 1 close-out item)
- [ ] **D10** — Network partition spec'd
- [ ] **D11** — Clock/TZ spec'd
- [ ] **D12** — Schema migration spec'd

---

## After Ratification

AI Head rewrites `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md` (3T version) incorporating:
- All env vars from master list above with defaults + documentation
- Signal queue schema additions (`primary_matter`, `related_matters`, `triage_confidence`, `status='classified-deferred'`)
- `POST /api/gold-promote` endpoint stub on Mac Mini FastAPI
- `flock`-wrapped cron entry with placeholder cadence + bench spec
- Pre-dispatch hardening checklist: rotate keys + SSH hardening + MacBook Obsidian Git plugin install
- Retry policy tables in implementation code
- Schema `_ensure_*` pattern + down-migration SQL for any changes
- Reference to this ratified v2 for every decision locked

Brief submitted for Code Brisen architecture review (per standing brief-review procedure) → Director ratification → dispatch.

**Time estimate:** KBL-A brief rewrite 90–120 min + review 30 min + revision 30 min = ~2.5–3 h.

---

*Prepared 2026-04-17 by AI Head (Claude Opus 4.7). Status: DRAFT pending Code Brisen review.*
