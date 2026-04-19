# AI Dennis — Mac Mini Step 7 Prep

**From:** AI Head (Baker / KBL orchestration)
**To:** AI Dennis (IT Shadow Agent — Brisen Development GmbH IT Admin coverage)
**Scope:** infrastructure prep, NOT code work
**Posted:** 2026-04-19 (late morning)
**Trigger:** PR #15 STEP6-FINALIZE-IMPL opened at head `69d8483`. Step 7 is the next B1 dispatch after PR #15 merges.
**Director ratification:** Option (C) — parallel-track Mac Mini setup while B1 builds Steps 5-6; Step 7 lands on pre-prepared Mac Mini. 2026-04-19.

---

## Context — why you

Step 7 (the "commit" step) is the ONE step in the KBL pipeline that cannot run on Render. It:
- Writes finalized Markdown files into `~/baker-vault/wiki/<matter>/<date>_topic.md`
- Writes cross-link stub rows into `~/baker-vault/wiki/<matter>/_links.md`
- Runs `git commit` + `git push origin main` on the baker-vault clone
- Must serialize concurrent commits via `flock` mutex

Render's filesystem is ephemeral (every deploy wipes state) and its SSH key management is fragile. So Step 7 runs on a stable always-on host with a persistent git clone. **Mac Mini is that host.**

Per CHANDA Inv 9 (ratified 2026-04-19 clarification): "Mac Mini is the single AGENT writer. Director writes are expected from any machine." So you're setting up the agent-writer path; Director's own edits from his dev Mac are separate and already work.

---

## Your role boundary

- **You execute infrastructure tasks** — SSH, git, systemd/launchd, filesystem, monitoring. Director approves major changes.
- **You do NOT write KBL code.** Step 7's Python impl is B1's job (next dispatch after PR #15 merges).
- **You do NOT touch baker-vault content.** Only the clone's plumbing.
- **Escalate to Director** on: SSH key creation, GitHub deploy-key setup, any network config change, any destructive filesystem op.

---

## Task scope — 5 infra items

### 1. Fresh baker-vault clone on Mac Mini

**Where:** `~/baker-vault/` on Mac Mini (match the path used on dev Mac for consistency).

**How:**
```bash
cd ~/
# If exists, confirm it's clean + up-to-date
ls baker-vault 2>&1 && cd baker-vault && git status && git pull --ff-only origin main
# If missing:
git clone git@github.com:vallen300-bit/baker-vault.git ~/baker-vault
```

**Escalation:** if the clone doesn't exist and SSH auth fails, ask Director for a deploy key or credential refresh.

### 2. Dedicated git identity for the Baker Pipeline

**Why:** Commits from Step 7 should be attributable to "the pipeline" — not Director's personal git identity. Keeps the audit trail clean.

**Config (run inside the baker-vault clone, NOT global):**
```bash
cd ~/baker-vault
git config user.name "Baker Pipeline"
git config user.email "pipeline@brisengroup.com"
git config commit.gpgsign false  # unless Director wants signed commits (flag to AI Head)
```

**Verify:**
```bash
git config --get user.name   # → "Baker Pipeline"
git config --get user.email  # → "pipeline@brisengroup.com"
```

### 3. SSH key for `git push` from the pipeline

**Options — flag preference to Director before executing:**
- **(a)** Reuse Director's existing `~/.ssh/id_ed25519` on Mac Mini (simplest; Mac Mini commits look as if Director pushed from Mac Mini)
- **(b)** Create a dedicated ed25519 deploy key for baker-vault, add as a GitHub deploy key with WRITE access. Cleaner attribution; more setup.

**Lean (b)** per "single AGENT writer" semantic — makes pipeline commits distinguishable in GitHub audit trail. But only execute after Director confirms.

### 4. `flock` mutex pattern

**Why:** Step 7 may be called by multiple concurrent signals (pipeline_tick processes N signals per minute). Only one can run `git commit + push` at a time on the vault clone.

**Design:**
- Lockfile location: `~/baker-vault/.lock` (inside the clone but outside `wiki/`)
- Step 7 Python code will wrap commit+push in `flock ~/baker-vault/.lock sh -c '...'`
- Lock timeout: 60 seconds — longer than typical commit+push, short enough to fail fast if hung
- **You don't write the Python.** You verify the lock path is writable by the user running the pipeline

**Verify:**
```bash
# Create lock dir, test manual lock acquire/release
touch ~/baker-vault/.lock
flock -n ~/baker-vault/.lock -c 'echo "locked"' && echo "lock works"
```

### 5. Render → Mac Mini bridge (the hand-off question)

**The question:** how does Render (where Steps 1-6 run) hand off to Mac Mini (where Step 7 runs)?

**Two patterns — flag preference to Director:**
- **(a) Pull model** — Mac Mini polls PG every N seconds: `SELECT * FROM kbl_cross_link_queue WHERE realized_at IS NULL` + `SELECT * FROM signal_queue WHERE status='awaiting_commit'`. Mac Mini claims, commits, marks realized. No inbound network on Mac Mini. Simplest.
- **(b) Push model** — Render sends HTTP/SSH signal to Mac Mini when a signal reaches `awaiting_commit`. Mac Mini runs a small listener service. Faster latency; more moving parts.

**Lean (a) pull model.** Latency of 15-30s polling is irrelevant for a knowledge-compounding pipeline (signals don't need sub-minute freshness in the vault). Zero inbound network exposure on Mac Mini (good security posture). No new service to monitor. Matches the existing `pipeline_tick` cron pattern.

**Your infra job for pattern (a):**
- Set up a launchd plist on Mac Mini that runs a small Python script every 60s
- Script connects to Neon PG (via `DATABASE_URL` env var), checks for `awaiting_commit` signals + unrealized cross-links
- **The script itself is B1's code**, not yours. You provision the launchd plist + env + logging.

### 6. Monitoring / health check

**Why:** If Mac Mini goes offline or the pipeline-commit process hangs, you need to know BEFORE a Silver entry rots in PG.

**Simple approach:**
- Mac Mini writes a heartbeat row to a `mac_mini_heartbeat` table in Neon every minute (via cron or launchd)
- Baker's existing `sentinel_health` endpoint (`baker-master.onrender.com/health`) exposes this heartbeat's age
- Alert threshold: >5 minutes since last heartbeat = WARN, >15 minutes = critical

**Your infra job:** provision the heartbeat script + launchd. Script content is 10 lines; B1 can provide the exact Python on next dispatch if needed.

---

## Deliverables + dispatch back

After completing items 1-4 (items 5-6 can be deferred until B1 hands you Step 7 code):

> AI Dennis Mac Mini Step 7 prep COMPLETE:
> - Item 1: baker-vault clone at `~/baker-vault` @ commit `<SHA>`, clean working tree
> - Item 2: git identity `Baker Pipeline <pipeline@brisengroup.com>` set locally in clone
> - Item 3: SSH option chosen: <(a) reuse Director key | (b) dedicated deploy key (public key: `<key>`)>
> - Item 4: flock tested at `~/baker-vault/.lock`, manual acquire/release working
> - Items 5-6 pending: waiting on B1's Step 7 code for launchd + heartbeat script
> Mac Mini is Step 7-ready from an infra standpoint.

---

## Escalation items (flag to Director before executing)

1. **SSH option (a) vs (b)** — which key approach?
2. **GPG commit signing** — required or skip?
3. **Ownership of heartbeat + polling scripts** — one combined launchd plist or two separate?

---

## Timeline

- Items 1-2: ~15 min (plus Director SSH question)
- Item 3: ~10 min post-Director decision
- Item 4: ~5 min
- Items 5-6: deferred to post-PR-#15 when B1 ships Step 7 code + you pair on deploy

**Total for infra-ready state: ~30-45 min + Director decision wait time.**

---

## Role discipline reminders (from `AI_DENNIS_SKILL.md`)

- Every significant action writes a ledger entry to your memory
- Escalation is a feature, not a failure — over-escalate on first-time infrastructure touches
- Your goal is "Mac Mini Step 7-ready when B1 arrives with code" — not "build Step 7 yourself"

---

*Posted 2026-04-19 by AI Head. B1 will dispatch Step 7 code separately after PR #15 merges. Your work can run entirely in parallel.*
