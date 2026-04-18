# Pre-KBL-A Decision Log — V2 (RATIFIED)

**Status:** RATIFIED 2026-04-17 by Director (Dimitry Vallen). Final version v2.3.
**Supersedes:** v1, v2 draft `5cc48ec`, v2.1 commit `0f48ba9`, v2.2 commit `27b3a5f`
**Date:** 2026-04-17
**Prepared by:** AI Head (Claude Opus 4.7)
**Review lineage:** v1 → CB-R1 → AH-R2 → v2 → CB-R3 (5B/15S/6N/6M) → v2.1 → CB-R4 (3B/12S/3N/1M) → v2.2 → CB-R5 (1B/1S) → **this v2.3**
**Director sign-offs received:** D2 redirect to queue-poll pattern (drop HTTP endpoint); `feature-dev:code-reviewer` subagent available (R4 asked for evidence — see Appendix A)

---

## What Changed From V2.2 (10-second summary)

- **1 R5 blocker fixed:** D13 git pull strategy — `-X theirs` → `-X ours` (semantics invert during rebase; `-X ours` in rebase mode = prefer upstream = Director's push wins, which is the rotation gold-path guarantee).
- **1 R5 should-fix applied:** D13 yq expression adds `select($p | last | type != "number")` to suppress stray `_0`, `_1` numeric-index exports from arrays.

## What Changed From V2.1 (carried forward)

- **3 R4 blockers fixed:** D13 yq expression rewritten for nested YAML (B1), array→CSV conversion added (B2), D14 FK types corrected to match `signal_queue.id` = INTEGER (B3).
- **4 high-value should-fixes integrated:** D6 Gate 2 split into 2a-auto-cost + 2b-manual-architecture (S3), D6 Gate 3 invocation spec'd as AI-Head-at-pre-dispatch (S4), D14 token estimation mechanism defined (S7), D12 Mac Mini install mechanism spec'd (S12).
- **3 quick wins:** D13 git-pull conflict strategy (S6), D14 80%-cap alert dedupe (S8), D15 `kbl_alert_dedupe` table + rsync cron moved into yml + sudo items added to hardening (S9-S11).
- **Appendix A:** Subagent smoke-test evidence (M1).

---

## Review Response Log

### Round 5 — Code Brisen on v2.2 (1 BLOCKER + 1 SHOULD)

| # | Finding | V2.3 Action |
|---|---|---|
| R5.B1 | D13 `git pull --rebase -X theirs` — semantics inverted during rebase (rebase swaps ours/theirs), so local Mac Mini commits win, NOT Director's push. Rotation gold-path guarantee broken. | Changed to `git pull --rebase -X ours` — in rebase mode, `ours` = upstream = Director's push = wins on conflict. Validated with `git-rebase(1)` docs. |
| R5.S1 | D13 yq `paths(scalars, arrays)` recurses INTO arrays, producing stray `KBL_<PATH>_0`, `_1` exports alongside canonical CSV | Added `select($p | last | type != "number")` filter to drop numeric-index path components |

R5 verifications (all passed):
- D14 `signal_id INTEGER` matches `signal_queue.id` SERIAL/INTEGER ✓
- Token estimation fallback chain practical (char/4 conservative) ✓
- Appendix A smoke-test evidence sufficient per R4.M1 ✓

### Round 4 — Code Brisen on v2.1 (3 BLOCKERS + 12 SHOULD + 3 NICE + 1 MISSING)

**BLOCKERS (all fixed in v2.2):**

| # | Finding | V2.2 Action |
|---|---|---|
| R4.B1 | D13 yq flattening broken for nested YAML | yq rewritten using `paths(scalars,arrays)` recursion — produces flat `KBL_<PATH>_<UPPER>` names |
| R4.B2 | D13 array→CSV missing | yq conditional: arrays get `join(",")`, scalars `tostring` |
| R4.B3 | D14 `signal_id UUID` mismatch with `signal_queue.id` = INTEGER | All FK signal_id columns changed to `INTEGER` to match Code Brisen #2's committed schema draft (`briefs/_drafts/KBL_A_SCHEMA.sql`) |

**SHOULD-FIX (7 applied, 5 deferred to KBL-A stage per R4 recommendation):**

| # | Finding | V2.2 Action |
|---|---|---|
| R4.S3 | D6 Gate 2 "no new vendor / SPOF" not algorithmically decidable | Gate 2 split: 2a auto-cost + 2b manual-architecture |
| R4.S4 | D6 Gate 3 subagent invocation path unspec'd | AI Head invokes `feature-dev:code-reviewer` at pre-dispatch, attaches verdict to ratification packet |
| R4.S6 | D13 git pull conflict strategy | `git pull --rebase -X theirs` with Director-authored preferred; on merge conflict, wrapper alerts Director + exits, flock releases |
| R4.S7 | D14 token estimation mechanism | Anthropic `/v1/messages/count_tokens` endpoint + per-model price env table; fallback to char/4 heuristic if endpoint unavailable |
| R4.S8 | D14 80%-cap alert spam | Alert once per UTC day at 80% threshold (dedup via `kbl_alert_dedupe` table — S10) |
| R4.S10 | D15 CRITICAL alert dedup store | NEW `kbl_alert_dedupe(component_msg_hash PK, first_seen, last_sent)` in KBL-A schema |
| R4.S11 | D15 /var/log/kbl + newsyslog.d need sudo | Moved to hardening checklist as pre-dispatch one-time Director setup (alongside SSH hardening + system TZ) |
| R4.S12 | D12 Mac Mini code install mechanism | Install script `scripts/install_kbl_mac_mini.sh` creates symlinks from baker-code clone to /usr/local/bin, registers LaunchAgents. Run once per KBL-A dispatch. |
| R4.S1 | D1 eval label ambiguity on Phase-2 matters | DEFERRED to Eval Playbook (Code Brisen #2) — measure classifier accuracy, not pipeline output |
| R4.S2 | D1 blocks on 60-90 min Director labeling | DEFERRED — acknowledgment only, not a spec change |
| R4.S5 | yq not in standard Mac Mini tools | DEFERRED into hardening checklist: `brew install yq` |
| R4.S9 | Dropbox rsync cron not in yml | Applied — added to `env.mac-mini.yml` in D13 |

**NICE-TO-HAVE (1 applied, 2 deferred):**

| # | Finding | V2.2 Action |
|---|---|---|
| R4.N2 | D7 GPG condition creates ambiguous Gold strength | Explicit: Phase 1 accepts identity-only Gold protection (weak); GPG is Phase 2 hardening item |
| R4.N1 | `/gold` UX friction | DEFERRED — Phase 1 fuzzy-match is out of scope |
| R4.N3 | `config/` breaks 3-layer vault | DEFERRED — acknowledged architectural drift; alternative `schema/config/` noted but not adopted Phase 1 |

**MISSING (1, addressed):**

| # | Finding | V2.2 Action |
|---|---|---|
| R4.M1 | Subagent smoke-test evidence | NEW Appendix A at end of doc — verbatim findings + agent ID + verdict analysis |

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

### Ratification — RATIFIED with Director override 2026-04-17

**Director override applied:** key rotation postponed ("other things to worry about now"). SSH hardening still proceeds NOW (drop-in ready at `briefs/_drafts/200-hardening.conf`).

**Effective D4:**
- **DO NOW:** SSH hardening (`/etc/ssh/sshd_config.d/200-hardening.conf` + `sshd -t` + reload)
- **DEFERRED to Phase 1 close-out (bundled):** `ANTHROPIC_API_KEY` rotation + `DATABASE_URL` rotation + 1Password migration + `~/.zshrc` rewrite + LaunchAgent plist updates

**Residual risk assessment (Phase 1):**
- Tailscale is sole SSH entry path (no public surface)
- SSH hardening drop-in eliminates password auth + restricts to `dimitry` user
- `.zshrc` secrets at rest on Mac Mini protected by FileVault (assumed on)
- Acceptable for ~4-6 week Phase 1 window

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

### Phase 1 gate table (R4 S3 + S4 corrections applied)

| Gate | Phase 1 mode | Rule | Invoker |
|---|---|---|---|
| **1. KBL brief ratification** | MANUAL | Always Director | Director reads brief |
| **2a. Pre-dispatch cost envelope** | AUTO-CHECK | Projected cost (from D14 token estimator × per-model price table) within `DAILY_COST_CAP`. Script runs, outputs pass/fail. | AI Head at pre-dispatch |
| **2b. Pre-dispatch architecture judgment** | MANUAL | "No new vendor; no new SPOF." Human architectural judgment — not algorithmic. | Director reads AI Head's 1-line summary |
| **3. Architecture review subagent** | AUTO-PROCEED IF | `feature-dev:code-reviewer` returns 0 CRITICAL + ≤2 IMPORTANT findings on the brief/PR | AI Head invokes subagent at pre-dispatch, attaches verdict + findings to ratification packet |
| **4. Production flag flip** | MANUAL | Always Director | Director flips `KBL_PIPELINE_ENABLED=true` |
| **5. Mid-shadow threshold review** | MANUAL (Phase 1) | Eval set built here; Phase 2 can auto-proceed on thresholds | Director reviews weekly |
| **6. Phase-to-phase scale** | MANUAL | Always Director | Director approves |

**Phase 1 result:** 2 auto (2a, 3) + 4 manual (1, 2b, 4, 5, 6) — Gate 2 is now effectively hybrid. Saves ~1-3 days vs all-manual (reduced from v2.1 estimate because 2b is manual).

**Subagent invocation concrete flow (S4 resolution):**
1. AI Head finishes brief/PR
2. AI Head calls `feature-dev:code-reviewer` with the brief content inline
3. Parse verdict: check for `CRITICAL` count (must be 0), `IMPORTANT` count (must be ≤2), or for harness variants: `Verdict: Passes` / `Verdict: Fails`
4. If PASS: proceed; attach verdict to ratification packet for Director visibility
5. If FAIL: loop back — fix findings, re-invoke, repeat until pass or escalate
6. Gate 3 output is ALWAYS human-visible in ratification packet (never "silent auto-proceed")

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

**Enforcement — defense in depth (per Code Brisen #2 Task B finding):**

1. **Promote worker enforcement (primary).** The Mac Mini `kbl-gold-drain.sh` worker reads `gold_promote_queue`, validates request, writes frontmatter, commits with Director identity. This is the single writer path for Gold promotions — we control it entirely.
2. **Commit-msg hook (local):** in `baker-vault/.git/hooks/commit-msg` rejects commits from `Baker Pipeline` identity if they touch any file with frontmatter `author: director`. Client-side, bypassable but defense.
3. **GitHub branch protection on `vallen300-bit/baker-vault` main** (applied 2026-04-17 per Code B2):
   - `required_linear_history=true`
   - `allow_force_pushes=false`
   - `allow_deletions=false`
   - `enforce_admins=false` — intentional Director emergency override.
4. **NO path-specific GPG signing.** R4.N2 decision: Phase 1 accepts identity-only Gold protection (weak — any push-authorized actor could commit with Director identity). GPG/SSH-signed commits + CODEOWNERS + Actions verifier = Phase 2 hardening. Explicit acceptance, not deferred-by-oversight.

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
1. KBL-A PR merged → Render auto-deploys → `_ensure_kbl_runtime_state`, `_ensure_kbl_cost_ledger`, `_ensure_kbl_log`, `_ensure_gold_promote_queue`, `_ensure_kbl_alert_dedupe`, `_ensure_signal_queue_additions` all run on startup
2. Verify via PG: `\d kbl_runtime_state` etc. present
3. THEN Mac Mini code installed (S12 resolution below)
4. Mac Mini cron fires, expects tables present. Fails fast with `TableNotFound` error if not.

**Mac Mini code installation (S12 resolution):**

One-time install script at `scripts/install_kbl_mac_mini.sh` in baker-master repo:
```bash
#!/bin/bash
set -euo pipefail
REPO="${HOME}/Desktop/baker-code"          # or wherever Director clones baker-master locally
TARGET="/usr/local/bin"

# 1. Symlink pipeline scripts (not copy — stays in sync with git pulls)
sudo ln -sf "${REPO}/scripts/kbl-pipeline-tick.sh" "${TARGET}/kbl-pipeline-tick.sh"
sudo ln -sf "${REPO}/scripts/kbl-gold-drain.sh"    "${TARGET}/kbl-gold-drain.sh"
sudo chmod +x "${REPO}/scripts/kbl-"*

# 2. Install LaunchAgent plists for cron-equivalent jobs (cron still works but launchd is macOS-native)
cp "${REPO}/launchd/com.brisen.kbl.pipeline.plist" "${HOME}/Library/LaunchAgents/"
launchctl unload "${HOME}/Library/LaunchAgents/com.brisen.kbl.pipeline.plist" 2>/dev/null || true
launchctl load   "${HOME}/Library/LaunchAgents/com.brisen.kbl.pipeline.plist"

# 3. Validate
which kbl-pipeline-tick.sh
launchctl list | grep kbl
```

**Run when:** once per KBL-A dispatch (first time) + after any script changes.
**Owner:** Director or AI Head (via SSH post-hardening).
**Pull updates:** `git -C ~/Desktop/baker-code pull` — symlinks mean no re-install needed for pure script updates.

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
  temp: "0"
  seed: "42"
  top_p: "0.9"
  keep_alive: "-1"

matter_scope:
  allowed: ["hagenauer-rg7"]              # array → CSV on export
  layer0_enabled: "true"
  newsletter_blocklist: []                # array → CSV
  wa_blocklist: []                        # array → CSV

gold_promote:
  disabled: "false"
  whitelist_wa_id: "41799605092@c.us"

pipeline:
  cron_interval: "*/2 * * * *"
  triage_threshold: "40"
  max_queue_size: "10000"
  qwen_recovery_after_signals: "10"
  qwen_recovery_after_hours: "1"

cost:
  daily_cap_usd: "15"
  max_alerts_per_day: "20"

flags:
  pipeline_enabled: "false"               # flipped true at go-live

observability:
  dropbox_rsync_time: "23:50"             # Europe/Vienna — S9: cron defined here
  vault_size_warn_mb: "500"
  vault_size_critical_mb: "1000"
```

All values stored as STRINGS (quoted) for uniform `tostring` in the export expression — prevents YAML-parsed ints/bools from surprising the shell.

**Deploy mechanism (B1 + B2 + S6 + R5.B1 + R5.S1 fixes):**

1. Mac Mini cron wrapper (`/usr/local/bin/kbl-pipeline-tick.sh`) first step:
   ```bash
   git -C ~/baker-vault pull --rebase -X ours
   ```
   - **Why `-X ours` (R5.B1):** during rebase, git swaps "ours" and "theirs" — `ours` in rebase mode refers to the upstream being rebased onto (origin/main = Director's push). So `-X ours` = prefer upstream on conflict = Director's config change wins. This is the rotation gold-path guarantee.
   - If unresolvable conflict remains after `-X ours`: `git rebase --abort`, wrapper inserts CRITICAL row in `kbl_log` with `component=git-conflict`, triggers WhatsApp alert via `kbl_alert_dedupe`, flock releases, next cron retries.

2. Wrapper sources config via `yq` (correct recursive flattening + array-to-CSV + R5.S1 numeric-index filter):
   ```bash
   eval "$(yq -r '
     [paths(scalars, arrays) as $p |
       select($p | last | type != "number") |
       "export KBL_" + ($p | map(. | ascii_upcase) | join("_")) + "=" +
       (getpath($p) |
         if type == "array" then join(",") else tostring end
       )
     ] | .[]
   ' ~/baker-vault/config/env.mac-mini.yml)"
   ```
   - `select($p | last | type != "number")` prevents `paths` from emitting individual array-index paths (`matter_scope.allowed.0`) in addition to the array-as-a-whole path (`matter_scope.allowed`). Without this filter, you get BOTH `KBL_MATTER_SCOPE_ALLOWED=hagenauer-rg7` (canonical) AND stray `KBL_MATTER_SCOPE_ALLOWED_0=hagenauer-rg7`.
   - Produces (clean): `KBL_OLLAMA_MODEL=gemma4:latest`, `KBL_MATTER_SCOPE_ALLOWED=hagenauer-rg7`, `KBL_MATTER_SCOPE_NEWSLETTER_BLOCKLIST=""`, etc.

3. Pipeline Python reads via `os.getenv("KBL_MATTER_SCOPE_ALLOWED", "").split(",")` for list types, direct `os.getenv()` for scalars.

4. **Rotation = edit yml, commit, push.** Next cron (≤2 min) picks up.

**Testing the yq expression (required before KBL-A dispatch):**
Director or Code Brisen #2 runs on sample yml, diffs expected-output. Test script: `scripts/test_env_yml_flatten.sh` creates representative yml → runs expression → asserts against expected CSV/string output.

**Prerequisites added to hardening checklist (S5):**
- `brew install yq` (required for deploy mechanism above)
- `yq --version` verified ≥ 4.0

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

**Schema (B3 FK type fix — INTEGER to match `signal_queue.id`):**
```sql
CREATE TABLE IF NOT EXISTS kbl_cost_ledger (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  signal_id INTEGER REFERENCES signal_queue(id),  -- was UUID, corrected per R4.B3
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

**Per-model price table (environment-seeded at Render startup, read at each pre-call estimate):**
```python
# Hardcoded in Python but values from env for rotation
KBL_PRICING = {
    "claude-opus-4":   {"input": float(os.getenv("PRICE_OPUS4_IN",  "15.00")),  "output": float(os.getenv("PRICE_OPUS4_OUT",  "75.00"))},
    "claude-sonnet-4": {"input": float(os.getenv("PRICE_SONNET4_IN", "3.00")),  "output": float(os.getenv("PRICE_SONNET4_OUT", "15.00"))},
    "claude-haiku-4":  {"input": float(os.getenv("PRICE_HAIKU4_IN",  "0.80")),  "output": float(os.getenv("PRICE_HAIKU4_OUT",   "4.00"))},
    "gemma4:latest":   {"input": 0.0, "output": 0.0},
    "qwen2.5:14b":     {"input": 0.0, "output": 0.0},
}
# Prices in USD per 1M tokens. Director updates on Anthropic price changes.
```

**Token estimation mechanism (S7 resolution):**

Pre-call cost estimate function:
```python
def estimate_cost(model: str, prompt: str, max_output_tokens: int) -> float:
    """
    Preferred: Anthropic count_tokens endpoint (exact).
    Fallback: tiktoken / anthropic SDK tokenizer.
    Fallback of fallback: char/4 heuristic.
    """
    try:
        # Primary — Anthropic endpoint if available
        resp = anthropic_client.messages.count_tokens(model=model, messages=[{"role":"user","content":prompt}])
        input_tokens = resp.input_tokens
    except (AttributeError, APIError):
        try:
            # Fallback 1 — SDK tokenizer
            from anthropic import Anthropic
            input_tokens = Anthropic().count_tokens(prompt)
        except Exception:
            # Fallback 2 — char heuristic (overestimates slightly, conservative)
            input_tokens = len(prompt) // 4 + 1
    price = KBL_PRICING[model]
    return (input_tokens * price["input"] + max_output_tokens * price["output"]) / 1_000_000
```

**Enforcement:**
- **Pre-call estimate:** before Step 5 Opus / Step 6 Sonnet:
  ```python
  today_spent = SELECT COALESCE(SUM(cost_usd),0) FROM kbl_cost_ledger WHERE ts::date = now()::date
  estimated = estimate_cost(model, prompt, max_output_tokens)
  if today_spent + estimated > DAILY_COST_CAP:
      mark signal status='cost-deferred'
      open cost-circuit in kbl_runtime_state
      exit
  ```
- **Post-call actual:** log row with actual token counts from Anthropic response `usage` field (more accurate than pre-call estimate; used for ledger truth).
- `claude -p` (M6): harness logs its own `input_tokens + output_tokens` from `claude -p --output-format json` response. Counted toward cap.
- **Local models (Gemma, Qwen):** `cost_usd=0`, tokens logged for throughput metrics, NOT counted toward cap.

**Dashboard:**
- Daily cost rollup: `SELECT step, SUM(cost_usd), SUM(input_tokens+output_tokens) FROM kbl_cost_ledger WHERE ts::date = now()::date GROUP BY step`
- Served by existing baker-master dashboard (KBL-C extends).

**Cost ceiling behavior:**
- Hard cap: `DAILY_COST_CAP` breached → circuit opens for rest of UTC day (state in `kbl_runtime_state.cost_circuit_open`).
- Soft alert at 80% (S8 dedupe applied):
  - Check `kbl_alert_dedupe` table for `alert_key='cost_80pct_' || today_utc_date`
  - If no row: insert + send WhatsApp "KBL at 80% daily cap ($12/$15)"
  - If row exists: silent (already alerted today)
- Same pattern at 95% and 100% — distinct alert keys, each fires once per UTC day.

**Circuit auto-clear:** at UTC 00:00 daily, cron clears `cost_circuit_open` in `kbl_runtime_state`.

### Ratification
- [ ] **Adopt cost-ledger schema + enforcement + alerts**
- [ ] Modify: ____________________

---

## D15 — Logging & Observability (NEW, per M1)

### Question
Where do KBL pipeline logs go? How does Director debug shadow-mode surprises?

### Spec

**Local rotating logs on Mac Mini (S11 — requires sudo setup):**
- Destination: `/var/log/kbl/pipeline.log` (DEBUG+)
- Rotation: `/etc/newsyslog.d/kbl.conf` — 10 MB per file, 7 files retained (~70 MB max)
- Mirror to Dropbox: daily `rsync` at `observability.dropbox_rsync_time` (env from D13 yml, default 23:50 Europe/Vienna) to `~/Dropbox-Vallen/_02_DASHBOARDS/kbl_logs/`

**One-time Director sudo setup (S11, added to hardening checklist):**
```bash
sudo mkdir -p /var/log/kbl
sudo chown dimitry:staff /var/log/kbl
sudo chmod 755 /var/log/kbl
sudo cp scripts/newsyslog-kbl.conf /etc/newsyslog.d/kbl.conf
sudo chmod 644 /etc/newsyslog.d/kbl.conf
# newsyslog re-reads config on next scheduled run (hourly by default)
```

**PG central log (WARN+, B3 FK fix):**
```sql
CREATE TABLE IF NOT EXISTS kbl_log (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  level TEXT NOT NULL,               -- 'WARN' | 'ERROR' | 'CRITICAL'
  component TEXT NOT NULL,           -- 'layer0' | 'triage' | 'pipeline' | 'gold_promote' | 'circuit_breaker' | 'git-conflict' | ...
  signal_id INTEGER REFERENCES signal_queue(id),  -- corrected per R4.B3
  cycle_id UUID,                     -- groups rows from same cron run (per Code B2 schema draft)
  message TEXT NOT NULL,             -- short, not full bodies
  metadata JSONB
);
CREATE INDEX IF NOT EXISTS idx_kbl_log_day_level ON kbl_log (ts::date, level);
```

**NEW — alert dedupe table (S10 resolution):**
```sql
CREATE TABLE IF NOT EXISTS kbl_alert_dedupe (
  alert_key TEXT PRIMARY KEY,        -- e.g., 'cost_80pct_2026-04-17' or '<component>_<msg_hash>_<bucket>'
  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_sent TIMESTAMPTZ NOT NULL DEFAULT now(),
  send_count INTEGER NOT NULL DEFAULT 1
);
-- Purge older-than-7-days dedupe entries nightly
```

Usage pattern (Python, at alert emission):
```python
def emit_critical_alert(component: str, message: str, bucket_minutes: int = 5):
    bucket = int(time.time() // (bucket_minutes * 60))
    alert_key = f"{component}_{hashlib.sha256(message.encode()).hexdigest()[:16]}_{bucket}"
    # INSERT ... ON CONFLICT (alert_key) DO NOTHING
    # If row actually inserted (check rowcount): send WhatsApp
    # If conflict (row existed): silent
```

**What goes where:**
- DEBUG/INFO: local file only (cheap, verbose)
- WARN+: local file + PG (query-able from dashboard)
- CRITICAL: local + PG + **WhatsApp alert to Director** (5-min dedupe via `kbl_alert_dedupe`)

**Vault size monitoring (M3 partial):**
- Daily cron on Mac Mini: `du -sm ~/baker-vault` → INSERT row into `kbl_log` as INFO level
- Alert via `emit_critical_alert` at >500 MB (WARN), >1 GB (CRITICAL with archival guidance)

**Canary / heartbeat (supports KBL-A monitoring):**
- Every 30 min, pipeline wrapper pings `kbl_runtime_state.key='mac_mini_heartbeat'`, value = `now()` ISO-8601
- Render-side monitor: alerts if heartbeat >30 min stale (silent failure detector, per Cortex 3T intent)

### Ratification
- [ ] **Adopt logging + observability spec**
- [ ] Modify: ____________________

---

## Env Var Master List (v2.1)

Every tunable has a default. Per D13, Mac Mini tunables live in `~/baker-vault/config/env.mac-mini.yml`. Secrets stay in `.zshrc`. Render env via dashboard.

> **Note (2026-04-17, post-R1 doc fix for S6):** the table below is the canonical **names as they exist in env after yq flattening** — corrected from flat names (`KBL_ALLOWED_MATTERS`) to hierarchical (`KBL_MATTER_SCOPE_ALLOWED`) to match what D13's yq expression actually produces. For the complete implementation-grade reference see `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF_DRAFT.md` §16.

| Var (after yml flatten) | Default | Source |
|---|---|---|
| `KBL_OLLAMA_MODEL` | `gemma4:latest` | D1 |
| `KBL_OLLAMA_FALLBACK` | `qwen2.5:14b` | D1 |
| `KBL_OLLAMA_TEMP` | `0` | D1 |
| `KBL_OLLAMA_SEED` | `42` | D1 |
| `KBL_OLLAMA_TOP_P` | `0.9` | D1 |
| `KBL_OLLAMA_KEEP_ALIVE` | `-1` | D1/S2 |
| `KBL_MATTER_SCOPE_ALLOWED` | `hagenauer-rg7` | D3 |
| `KBL_MATTER_SCOPE_LAYER0_ENABLED` | `true` | D3 |
| `KBL_MATTER_SCOPE_NEWSLETTER_BLOCKLIST` | `""` (CSV) | D3 |
| `KBL_MATTER_SCOPE_WA_BLOCKLIST` | `""` (CSV) | D3 |
| `KBL_GOLD_PROMOTE_DISABLED` | `false` | D2 |
| `KBL_GOLD_PROMOTE_WHITELIST_WA_ID` | `41799605092@c.us` | D2 |
| `KBL_PIPELINE_CRON_INTERVAL_MINUTES` | `2` (TBD post-bench) | D5 |
| `KBL_PIPELINE_TRIAGE_THRESHOLD` | `40` | existing |
| `KBL_PIPELINE_MAX_QUEUE_SIZE` | `10000` | D10 |
| `KBL_PIPELINE_QWEN_RECOVERY_AFTER_SIGNALS` | `10` | D1/S3 |
| `KBL_PIPELINE_QWEN_RECOVERY_AFTER_HOURS` | `1` | D1/S3 |
| `KBL_COST_DAILY_CAP_USD` | `15` (KBL-only) | D6/D14 |
| `KBL_COST_MAX_ALERTS_PER_DAY` | `20` | D6 |
| `KBL_FLAGS_PIPELINE_ENABLED` | `false` (flips `true` at go-live) | existing |
| `KBL_OBSERVABILITY_DROPBOX_RSYNC_TIME` | `23:50` | D15 |
| `KBL_OBSERVABILITY_VAULT_SIZE_WARN_MB` | `500` | D15 |
| `KBL_OBSERVABILITY_VAULT_SIZE_CRITICAL_MB` | `1000` | D15 |

**Removed from v2:** `KBL_CRON_TZ` (N4 — not load-bearing, replaced by Mac Mini `systemsetup`).

**Runtime state (NOT env vars, live in `kbl_runtime_state` PG table per D8):**
- `anthropic_circuit_open`, `anthropic_5xx_counter`, `qwen_active`, `qwen_active_since`, `qwen_swap_count_today`, `mac_mini_heartbeat`, `cost_circuit_open`

---

## Ratification Checklist — ALL RATIFIED 2026-04-17

- [x] **D1** — Gemma 4 8B + Qwen availability-fallback. **Ratified 2026-04-18 at 88v/76m for Phase 1** (see §"D1 Phase 1 acceptance" clarification below for rationale + Phase 2 gate). Original 90/80 thresholds superseded by Phase-1-operational-acceptance framing.
- [x] **D2** — Queue-poll pattern (Director-signed 2026-04-17)
- [x] **D3** — 3-layer per-source scoping
- [x] **D4** — **[DIRECTOR OVERRIDE 2026-04-17]** SSH harden NOW; key rotation + 1Password migration deferred together to Phase 1 close-out. Mitigating controls: Tailscale-only SSH + SSH hardening drop-in.
- [x] **D5** — Serial via flock + p95 cadence post-bench
- [x] **D6** — Phase 1: 2-auto-proceed + 4-manual gates
- [x] **D7** — Vault commit matrix + GitHub branch protection (Phase 1 identity-only Gold; GPG = Phase 2)
- [x] **D8** — Retry ladders + circuit breaker + `kbl_runtime_state` table
- [x] **D9** — TTL hierarchy + per-source vault policy (wiki retention open for Phase 1 close-out)
- [x] **D10** — Partition + recovery SLO
- [x] **D11** — Clock/TZ (UTC storage, IANA in payload, system TZ Europe/Vienna)
- [x] **D12** — Render-owns-migrations + sequenced deploy + `install_kbl_mac_mini.sh`
- [x] **D13** — Config deployment via `env.mac-mini.yml` in baker-vault (git pull --rebase -X ours)
- [x] **D14** — Cost tracking via `kbl_cost_ledger` + circuit at cap + token estimation
- [x] **D15** — Logging: local rotating + PG WARN+ + Dropbox mirror + heartbeat + `kbl_alert_dedupe`

**Vocabulary standardization (AI Head ruling 2026-04-17, not a decision, clarification):**
- `vedana` enum throughout KBL: `opportunity | threat | routine` (production schema canonical). Classical `pleasant / unpleasant / neutral` map deprecated at Phase 1 close-out.

**D1 Qwen-fallback role re-scoped (Director-ratified 2026-04-17, clarification):**

Original D1 §173-177 framed Qwen 2.5 14B cold-swap as a fallback that would rescue Gemma failures. D1 eval retry v2 (`briefs/_reports/B3_d1_eval_retry_20260417.md` @ `6328f11`) showed Qwen **underperforms** Gemma on vedana accuracy (80% vs 86%) under the shared fair-prompt conditions. The "accuracy rescue" framing is therefore incorrect.

Director ratified **option (b):** Qwen remains wired as an **availability fallback only** — if Gemma is unreachable, Qwen keeps the pipeline moving at acceptable-but-lower accuracy. Qwen is **not** an accuracy rescue.

Operational implications:
- `OLLAMA_FALLBACK=qwen2.5:14b` remains in config (per §161)
- Cold-swap mechanism + auto-recovery (§173-177) remain unchanged
- Expectations change: a Qwen-active pipeline tick emits a `WARN`-level `kbl_log` entry (`component=triage`, message: "running on availability fallback, accuracy degraded") so Director sees it. KBL-B brief §6 will wire this.
- **Deferred:** third-model eval for a real *accuracy* fallback (candidates: Llama 3.3 70B, Mixtral 8x7B) moved to Phase 1 close-out or later. Not blocking D1.

---

**D1 Phase 1 acceptance — Gemma ratified at 88v/76m (Director-ratified 2026-04-18, ACCEPTANCE):**

D1 v3 eval retry (`briefs/_reports/B3_d1_eval_v3_20260417.md` @ `aba04d6`) landed Gemma at **88% vedana (target 90%, 2pp short) / 100% JSON / 76% matter (target 80%, 4pp short)**. v3 glossary lifted matter from 34% (v2) → 76% (+42pp) — clearly not diminishing returns.

**Director ratified Gemma-final for Phase 1** on 2026-04-18, overriding the original 90%/80% thresholds based on the following operational reasoning:

1. **Phase 1 scope is Hagenauer-only.** Layer 2 enforcement (`KBL_MATTER_SCOPE_ALLOWED=hagenauer-rg7`) blocks non-Hagenauer from reaching Step 5 Opus. 24% matter errors in Phase 1 mostly route to `wiki/_inbox/` — the designed catch-all, not a failure state.
2. **Inbox + weekly Director review** is the safety net. Misclassified signals are recoverable with Director's weekly inbox pass, which is architectural intent, not a workaround.
3. **Downstream pipeline recovery.** Step 2 (resolve) and Step 4 (classify) independently filter noise and detect routing errors. Single-step classifier accuracy at 76% does not equal pipeline-end correctness at 76%.
4. **Measurement noise.** Measurement bug #2 (stale `MATTER_ALIASES["brisen-lp"]` including `wertheimer`) contributes ~1-2pp of the gap. Auto-resolves on SLUGS-1 merge (no manual fix required). 4-5 ambiguous signals in the labeled set contribute an additional uncertain margin.
5. **Pre-data thresholds were prophylactic, not operational.** 90%/80% was set before we knew what Gemma could do or how downstream safety nets performed. Post-v3, we have both pieces of evidence.

**Phase 2 gate (not yet ratified, flagged for close-out):** before expanding `KBL_MATTER_SCOPE_ALLOWED` beyond `hagenauer-rg7`, re-eval Gemma against live Phase 1 production data (not synthetic labels). Minimum threshold for Phase 2 expansion to be revisited at that point — live data is a more honest measurement than a 50-signal eval set.

**B3's 9 self-written slug descriptions** (from `briefs/_reports/B3_d1_eval_v3_20260417.md` §2c) are accepted as-is into `baker-vault/slugs.yml` via the SLUGS-1 merge. Director retains editorial control — can refine any description via direct baker-vault PR at any time. No further ratification ceremony required.

**Path B (bug-fix + relabel + v4 run)** is **not executed.** Reason: the measurement hygiene gains are marginal relative to the Phase 2 close-out gate, where live-data re-eval supersedes synthetic-set measurement anyway. Path A (third-model eval) is also not executed — Gemma-ratified means no alternate model needed.

**D1 status: RATIFIED.** Qwen remains wired as availability fallback per prior clarification. All downstream briefs (KBL-B §1.4, §6, etc.) can now reference Gemma-final without conditional framing.

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

**Critical-path acknowledgment (R4.S2):** D1 ratification depends on Director spending 60-90 min labeling 50 signals for the pre-shadow eval. This sits on the critical path between v2.2 ratification and KBL-A dispatch. Director should schedule the labeling session alongside ratification review (combined ~2 h block).

---

*Prepared 2026-04-17 by AI Head (Claude Opus 4.7). V2.3 post Code Brisen R5 spot-check. **Status: RATIFIED 2026-04-17 by Director Dimitry Vallen.** 5 review rounds (R1 through R5), 71 findings addressed across iterations. 15 decisions locked.*

---

## Appendix A — Subagent Smoke-Test Evidence (R4.M1 resolution)

**Test date:** 2026-04-17
**Session:** AI Head (Claude Opus 4.7, Mac app instance)
**Agent invoked:** `feature-dev:code-reviewer`
**Agent ID returned:** `a6b3570dae2c6467c`

### Test input

Inline 16-line Python function representative of KBL pipeline code (signal queue drain):

```python
def drain_signal_queue(conn, max_signals=10):
    """Drain pending signals and mark as in_progress."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM signal_queue
        WHERE status = 'pending'
        ORDER BY created_at
        LIMIT %s
        FOR UPDATE SKIP LOCKED
    """, (max_signals,))
    ids = [row[0] for row in cur.fetchall()]
    if ids:
        cur.execute("""
            UPDATE signal_queue
            SET status = 'in_progress'
            WHERE id = ANY(%s)
        """, (ids,))
    conn.commit()
    return ids
```

### Verbatim output (abbreviated)

```
CRITICAL: No issues at this severity level.

IMPORTANT:
- Missing cursor close / resource leak — Confidence: 85
- No exception handling around commit — Confidence: 82

MINOR (below reporting threshold — noted for completeness):
- ORDER BY created_at without tiebreaker on id gives non-deterministic ordering
- No logging when ids is empty

Summary: Two reportable issues, both IMPORTANT tier. Cursor leak = higher
operational risk. Missing rollback on commit failure = higher correctness risk.
Subagent is functioning. Output shape confirmed.
```

### Verdict analysis per D6 Gate 3 rule

- **CRITICAL count:** 0 ✓ (rule: must be 0)
- **IMPORTANT count:** 2 ✓ (rule: must be ≤2)
- **Gate 3 outcome for this test:** PASS (but note findings for Director visibility)

Both IMPORTANT findings are legitimate (cursor resource management + rollback on commit failure). Subagent does NOT invent phantom bugs. Signal-to-noise: high.

### Cross-harness variant (Code Brisen #2 independent test, 2026-04-17)

Code Brisen #2 independently smoke-tested `feature-dev:code-reviewer` in its harness. Output shape differs slightly:
- AI Head (Mac app): tiered CRITICAL/IMPORTANT/MINOR + confidence scores
- Code Brisen (CLI): `Verdict: Passes/Fails` lead + informational/flagged distinction

**D6 Gate 3 parser must handle both shapes.** Parse rule:
```
if "Verdict: Passes" in output or ("CRITICAL" not found and "IMPORTANT" count ≤ 2): PASS
else: FAIL → loop to fix
```

### Conclusion

`feature-dev:code-reviewer` subagent is available, functional, and suitable for D6 Gate 3 auto-proceed in Phase 1. Output is machine-parseable in both harness variants. Smoke test evidence preserved here for ratification audit trail.
