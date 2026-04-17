# Pre-KBL-A Decision Log

**Purpose:** Lock 6 open decisions before KBL-A 3T brief rewrite, so the brief has no holes that become re-dispatches later.
**Status:** Awaiting Director ratification
**Date:** 2026-04-17
**Prepared by:** AI Head (Claude Opus 4.7) after Code Brisen architecture review
**Triggered by:** Code Brisen Session 3 critique (16 items, 5 BLOCKER decisions)

---

## Decision 1 — Lock Gemma 4 8B as Pipeline Steps 1-4 Model

### Question
Which local model does the KBL pipeline use for Steps 1-4 (Triage / Resolve / Extract / Classify) on Mac Mini?

### Status
**Benchmark already done** (2026-04-16). Results in `outputs/kbl_triage_benchmark.json`. Four candidates tested on clean Mac Mini box:

| Model | Vedanā | JSON | Avg latency |
|---|---|---|---|
| **Gemma 4 8B** | **5/5** | **5/5** | **4.4s** |
| Gemma 4 26B MoE | 2/5 ❌ | 3/5 ❌ | 9.0s (thinking-model variant drops frontmatter fields) |
| Qwen 2.5 14B | 5/5 | 5/5 | 9.1s |
| Mistral Small 24B | 5/5 | 5/5 | 19.6s |

### Options
- **A. Lock Gemma 4 8B primary, Qwen 2.5 14B fallback** (only fallback kept in RAM; benchmark-based)
- B. Reconsider after more signal types tested — defers ~1 week

### Recommendation: **A**

### Rationale
Gemma 4 8B ties or beats every larger model on accuracy, at 2-4.5× the latency advantage and lowest RAM footprint. More params don't fix matter resolution (all 3 accurate models missed the same 2 entity lookups — that's a prompt-context problem, solved by KBL-11 hot.md and KBL-18 feedback ledger, not a model problem). Deferring to "test more signals" is premature optimization.

### Director Ratification
- [ ] **A — Lock Gemma 4 8B, Qwen 14B fallback**
- [ ] B — Defer, test more signals

### Consequence if A
- Roadmap step 2 ("re-run benchmark on Mac Mini") becomes steady-state latency sanity check only, not model selection
- KBL-A 3T brief hardcodes `OLLAMA_MODEL=gemma4:latest` with `OLLAMA_FALLBACK=qwen2.5:14b`
- Qwen pulled to Mac Mini (already pulled to MacBook — pull to Mini in step 2)

---

## Decision 2 — Gold-Promotion Detection Mechanism

### Question
How does the pipeline detect that Director flipped `author: director` on a wiki page (to protect it from future pipeline writes and cascade cetasikas into Silver compilation)?

### Options

**A. `fswatch` daemon on Mac Mini watches `~/baker-vault/wiki/**/*.md`**
- On change: parse frontmatter, if `author` changed to `director` → immediate commit + push
- **Pros:** Real-time (<1s latency), purely local, no interface required
- **Cons:** macOS-specific (Phase 2 portability debt), daemon process to manage via LaunchAgent, may miss changes during daemon restart, contradicts Cortex 3T #12b "fresh process per signal, no daemon" philosophy

**B. Explicit endpoint `POST /api/gold-promote` (primary) + git-diff-on-pull (backup)**
- Director uses WhatsApp command (`/gold hagenauer-rg7/court-filing-apr16.md`) or future web UI button
- Endpoint updates frontmatter server-side, commits, pushes
- **Backup path:** Each 15-min cron, `git pull` + diff-since-previous-HEAD; if any file's frontmatter now has `author: director`, treat as promotion (catches the case where Director edits in Obsidian desktop + commits+pushes manually)
- **Pros:** Works from any device (iPhone, web, WhatsApp), no daemon, belt+suspenders coverage, matches "cron-based stateless" Cortex 3T design
- **Cons:** ~15 min latency on the git-diff-on-pull path (acceptable for Gold — no rush on protection). Requires interface work in KBL-C.

**C. Git-diff-on-pull only (no endpoint)**
- Just option B's backup path
- **Pros:** Simplest. Zero new endpoints. Director commits Gold from Obsidian git plugin.
- **Cons:** Forces Director to git-commit manually every Gold edit. Friction on iPhone (Obsidian mobile git support limited).

### Recommendation: **B (endpoint primary + git-diff backup)**

### Rationale
Option A's daemon contradicts the cron-based architecture and locks us to macOS. Option C's manual git-commit is real UX friction — Director thinking about git while trying to mark a page Gold is the wrong cognitive load. Option B gives Director two paths: (1) "flip the flag, tell Baker via WhatsApp, done" for quick promotions, and (2) "edit in Obsidian, commit, push" for deliberate batch editing. Pipeline catches both within 15 min.

### Director Ratification
- [ ] A — fswatch daemon
- [ ] **B — Endpoint primary + git-diff backup**
- [ ] C — Git-diff only

### Consequence if B
- KBL-A adds `POST /api/gold-promote` endpoint (stub — takes matter + path, updates frontmatter, commits)
- KBL-B adds git-diff-on-pull inspection as first step of every cron batch
- KBL-C adds WhatsApp command parser for `/gold <path>`

---

## Decision 3 — Hagenauer Signal Scoping Mechanism

### Question
How does the pipeline process Hagenauer-only for Phase 1, when real signals are cross-matter (Brisen team WhatsApp mentions Hagenauer + Cupial in same message; Fireflies transcripts span 5 matters; email threads drift)?

### Options

**A. Entity-map keyword filter at ingest**
- Before signal hits `signal_queue`, check if any Hagenauer entity mentioned (Hagenauer, RG7, Christine Sähn, Mykola, specific addresses)
- If yes → enqueue with `matter=hagenauer-rg7`. If no → drop.
- **Pros:** Cheap, deterministic, drops non-Phase-1 traffic at the door
- **Cons:** Drops cross-matter emails that need processing for other matters in Phase 2 (data loss). Misses signals that mention Hagenauer implicitly (project codename, person's title, etc.).

**B. Triage classifier sets matter field; pipeline filters at Step 5**
- All signals enqueue with `matter=null`
- Step 1 triage (Gemma, free) assigns `matter` (or `multi` for cross-matter)
- Pipeline processes through Steps 1-4 for ALL signals (free)
- Step 5 (Opus, paid) only runs if `matter in ALLOWED_MATTERS` (env var, Phase 1 = `['hagenauer-rg7']`)
- **Pros:** No data loss (everything classified, nothing dropped). Cost contained (Gemma is free; Opus only fires on Phase 1 matter). Phase 2 expansion = add matter to env var — zero pipeline rewrite.
- **Cons:** Processes ~20× more signals through Gemma than strictly needed (Gemma is free but not instant — adds Mac Mini load)

**C. Process everything through full pipeline, write only Hagenauer wiki entries**
- No filter anywhere — full 8-step pipeline on every signal
- Only Hagenauer signals get `wiki/hagenauer-rg7/` file writes
- **Pros:** Validates whole pipeline on full traffic from day 1
- **Cons:** 20× wasted Opus spend (at $0.08-0.15/signal × ~100 signals/day × 95% non-Hagenauer = $7.60-14.25/day wasted). Fails Phase 1 cost target (<$10/day).

### Recommendation: **B (triage classifies all, Step 5 filters by allowed matters)**

### Rationale
- A loses Phase 2 data (a Cupial signal dropped in Phase 1 is a signal we'll never process)
- C fails cost target
- B is the only option that preserves data AND contains cost AND enables zero-rewrite Phase 2 expansion. Gemma load at ~100 signals/day is trivial (each ~2s → 200s/day of Gemma time).

### Director Ratification
- [ ] A — Entity-map filter at ingest
- [ ] **B — Classifier + ALLOWED_MATTERS filter at Step 5**
- [ ] C — Process everything, write only Hagenauer

### Consequence if B
- KBL-A adds `ALLOWED_MATTERS` env var (default `hagenauer-rg7`)
- KBL-B pipeline Step 5 checks `matter in ALLOWED_MATTERS` before Opus call; if not, marks signal `status=classified-deferred`, returns
- Phase 2 scale becomes: `ALLOWED_MATTERS=hagenauer-rg7,cupial,mo-vie,ao,...`

---

## Decision 4 — Secret Migration Timing (Explicit)

### Question
Should the 5 plaintext secrets in `~/.zshrc` on Mac Mini (ANTHROPIC_API_KEY, DATABASE_URL, QDRANT_URL, QDRANT_API_KEY, VOYAGE_API_KEY) migrate to 1Password before KBL-A dispatch, or after Phase 1?

### Background
Director said "not urgent" earlier. Code Brisen critique flagged "make it explicit — don't leave as chicken-and-egg refactor task."

### Options

**A. Env vars now, 1Password migration post-Phase 1 (explicit deferral)**
- KBL-A, KBL-B, KBL-C use `os.getenv("ANTHROPIC_API_KEY")` pattern
- Migration scheduled as Phase 1 post-validation task (week 4-5)
- **Pros:** Unblocks KBL-A dispatch. Matches Director's stated priority.
- **Cons:** Known debt — plaintext secrets on a remote-accessible box until Phase 1 validates.

**B. Migrate before KBL-A dispatch (block Phase 1 start ~45 min)**
- Director signs in to `op`, 5 items created, `.zshrc` rewritten
- KBL code uses `os.getenv()` same way (the `.zshrc` resolves via `op read` at shell startup)
- Rotate ANTHROPIC_API_KEY + DATABASE_URL during migration
- **Pros:** No plaintext secret exposure. Clean slate.
- **Cons:** 45-min blocker.

### Recommendation: **A (explicit deferral)**

### Rationale
Director already assessed risk as non-urgent. Migration doesn't change application code — it's a `.zshrc` change only. Can happen any time post-Phase 1 without code impact. Keep momentum on the actual pipeline build.

Mitigating controls Phase 1:
- Tailscale is the ONLY SSH entry path now (no more public mDNS or direct IP)
- Stale SSH sessions cleaned (22-day-old logins from previous months killed)
- GitHub vault token already in Render env (not Mac Mini zshrc)

### Director Ratification
- [ ] **A — Env vars now, migrate post-Phase 1**
- [ ] B — Migrate before KBL-A dispatch

### Consequence if A
- Roadmap step 11 stays where it is (between validation and Phase 2)
- KBL-A/B/C briefs use `os.getenv()` everywhere
- Roadmap header notes: "Secrets: plaintext in `~/.zshrc`, migration deferred to Phase 2 prep"

---

## Decision 5 — `claude -p` Concurrency Cap on Mac Mini

### Question
How many concurrent `claude -p` processes can run per cron batch?

### Background
Mac Mini RAM ~24 GB total. Running apps + Ollama 8B warm consume ~16 GB. Leaves ~8 GB for `claude -p` sessions. Each session loading 200K context uses 2-4 GB RAM.

### Options

**A. Strictly serial (1 at a time) — Phase 1**
- Cron claims one signal with `FOR UPDATE SKIP LOCKED`, processes, exits
- Next signal picked by next cron iteration (or inner loop if batch has multiple)
- **Max concurrency:** 1
- **Throughput at 10 min/signal:** ~144/day — more than 100 signals/day ceiling
- **Pros:** Safe memory, matches Cortex 3T #12b "fresh process per signal" intent
- **Cons:** Serial bottleneck if signal volume spikes

**B. Bounded parallel (2-3) — Phase 1**
- Cron claims 2-3 signals, processes in parallel subprocesses
- Bounded explicitly via semaphore
- **Pros:** Higher throughput
- **Cons:** Tighter memory, risk of swap, harder debugging

**C. Queue-based external worker pool**
- Out of scope for Phase 1 — over-engineered

### Recommendation: **A (strictly serial for Phase 1, revisit Phase 2)**

### Rationale
At Phase 1 target volume (~100 signals/day, Hagenauer only) and cron cadence (96 runs/day), the math is: 96 slots × 1 signal × ~5 min average = ~8 hours of pipeline work per day. Plenty of headroom. Parallel adds risk for no benefit at this volume. Revisit in Phase 2 when volume grows 10-20×.

### Director Ratification
- [ ] **A — Serial, 1 at a time**
- [ ] B — Bounded parallel 2-3
- [ ] C — External worker pool

### Consequence if A
- KBL-B cron signature: `claim_one_signal() → process() → exit()`
- `FOR UPDATE SKIP LOCKED` still needed (prevents race between overlapping cron runs if one takes >15 min)
- Cron set to every 2 min (not 15) during shadow mode so backlog drains if a signal takes 20 min — decision to refine in KBL-B brief

---

## Decision 6 — Auto-Proceed Thresholds at Decision Gates

### Question
Can some of the 5 decision gates in the roadmap pre-delegate thresholds, to avoid 5-10 days of waiting during Phase 1 execution?

### Proposal

| Gate | Manual review mandatory | Auto-proceed if |
|---|---|---|
| **After step 4** (KBL-A 3T brief ready) | ✅ Always — first brief always reviewed before dispatch | — |
| **After step 6** (KBL-B brief ready) | Cost estimate changes >50% from KBL-A; new vendor; any new SPOF | Within previous cost envelope, no new vendors, no new SPOF |
| **After step 8** (KBL-C brief ready) | Any change to Gold protection invariant; any change to ayoniso semantics | Implementation-only, no decision drift |
| **Before step 13** (flip `KBL_PIPELINE_ENABLED=true`) | ✅ Always — production flag flip | — |
| **Mid-shadow-mode (step 15)** | Vedanā accuracy <80% OR cost >$15/day OR ayoniso FP >30% | Vedanā ≥80% AND cost ≤$15/day AND FP ≤30% |
| **End of Phase 1 → Phase 2 scale** | ✅ Always — scale decision | — |

**Result:** 3 mandatory gates + 3 auto-proceed-if-safe gates. Saves ~4-6 days of waiting if metrics are clean.

### Director Ratification
- [ ] **Adopt above table**
- [ ] Keep all 5 gates manual (no auto-proceed)
- [ ] Propose changes: ____________________

---

## Summary — Ratification Checklist

Tick the recommended option (or override) for each:

- [ ] **D1 — Lock Gemma 4 8B primary, Qwen fallback** (recommended: A)
- [ ] **D2 — Gold promotion via endpoint + git-diff backup** (recommended: B)
- [ ] **D3 — Classifier + ALLOWED_MATTERS filter at Step 5** (recommended: B)
- [ ] **D4 — Env vars now, 1Password migration post-Phase 1** (recommended: A)
- [ ] **D5 — `claude -p` strictly serial, 1 at a time** (recommended: A)
- [ ] **D6 — Auto-proceed thresholds at 3 of 6 gates** (recommended: table above)

---

## After Ratification

AI Head rewrites `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md` (3T version) with:
- Gemma 4 8B locked + Qwen fallback pull
- `POST /api/gold-promote` endpoint stub (+ git-diff-on-pull scaffolding for KBL-B)
- `ALLOWED_MATTERS` env var (+ Phase 1 default)
- Env var pattern for secrets (no `op` dependency yet)
- Serial cron signature + `FOR UPDATE SKIP LOCKED`
- Cost circuit-breaker at pipeline entry (not just Step 5)
- Architecture review gate between KBL-A write + dispatch
- Time estimate: 12-16h (up from 6-8h per Code Brisen's recalibration)

Then Director review → KBL-A dispatch to Code Brisen.

---

*Prepared 2026-04-17. Awaiting Director ratification. Estimated review time: 15-30 min.*
