# KBL-C Interface Layer — Code Brief (SKELETON / DRAFT)

**Status:** Skeleton. §1-2 ratification requested from Director before per-step detail.
**Author:** AI Head
**Date:** 2026-04-18
**Purpose:** surface architecture decisions early so Director can redirect scope before per-handler detail is written. Same skeleton-first pattern as KBL-B.

**Reading time:** ~10 minutes.

---

## 1. Purpose + Scope

### 1.1 What KBL-C is

KBL-C is the **Director-interface layer** on top of the pipeline KBL-B produces. KBL-B writes Silver wiki entries to `baker-vault/wiki/<matter>/`. KBL-C surfaces those entries to the Director, captures Director actions back into the feedback ledger, and operates the Gold promotion mechanism.

Per CHANDA §2, KBL-C implements Leg 2 (Capture). Every Director action — promote, correct, ignore, ayoniso respond, ayoniso dismiss — writes to `feedback_ledger` atomically. Without KBL-C, the Learning Loop does not close.

Realistic estimate: ~1200-1800 lines of Python across `kbl/interface/*.py` + WhatsApp webhook handler + dashboard backend; ~300 lines of schema extensions; ~250 lines of tests.

### 1.2 What KBL-C is NOT

- **Not KBL-B.** Pipeline authoring is done elsewhere. KBL-C consumes pipeline outputs and emits Director-facing surfaces.
- **Not a new signal ingestion point.** WhatsApp messages from the Director flow through the existing WAHA sentinel → `signal_queue` like any other signal. KBL-C handles the subset that are *replies to pipeline-emitted alerts*, not new signals.
- **Not a model-call layer.** No LLM work in KBL-C. If action-classification is needed (e.g., disambiguating "yes promote" vs "yes continue discussion"), it happens deterministically via command parsing or a thin Gemma classifier — not Opus.
- **Not a cockpit UI.** The Baker CEO cockpit at baker-master.onrender.com already exists; KBL-C feeds data into it, does not rebuild it.

### 1.3 Three surfaces KBL-C owns

```
1. Ayoniso alerts  → WhatsApp push → Director sees pipeline-surfaced signals
2. Gold promotion  → WhatsApp reply parsing → promote Silver → Gold (atomic ledger write)
3. Feedback        → Director corrections / dismissals → atomic ledger write
```

All three flow through WhatsApp as primary channel (per Director's usage pattern), with vault-commit fallback for when Director edits frontmatter directly on Mac Mini.

### 1.4 Ratified inheritances (don't re-open)

- **CHANDA Inv 2:** every Director action writes the ledger atomically, or the action fails. KBL-C enforces this or nothing — there is no soft-fail mode for ledger writes in Phase 1.
- **CHANDA Inv 4:** `author: director` files are never modified by agents. KBL-C's promotion mechanism flips `author: pipeline` → `author: director` on Director WhatsApp confirmation — that single transition is the ONLY time an agent writes an `author: director` frontmatter field, and it's under explicit Director command.
- **CHANDA Inv 7:** Ayoniso alerts are prompts, never overrides. If Director doesn't respond to an alert, the signal stays at Silver. Pipeline never auto-promotes.
- **CHANDA Inv 8:** Silver → Gold only by explicit Director frontmatter edit. KBL-C's WhatsApp flow IS the explicit edit — the reply "promote" is the Director action, the frontmatter flip is the mechanical effect.
- **CHANDA Inv 9:** Mac Mini is the single writer. KBL-C on Render writes to `wiki_staging` (PG table) for any vault-destined change; Mac Mini daemon drains `wiki_staging` → vault git.
- **D2:** Gold promotion via `gold_promote_queue` PG table + Mac Mini cron drain — existing KBL-A infra, KBL-C wires it.
- **WAHA Plus:** WhatsApp is the primary Director channel. Self-hosted on Render (~$26/mo). Existing sentinel wires inbound; KBL-C wires outbound.

### 1.5 Three actor model

| Actor | Surface | Verbs |
|---|---|---|
| **Pipeline (KBL-B)** | writes `signal_queue.state='done'` + Silver wiki entry | emit |
| **Ayoniso dispatcher (KBL-C §3)** | reads newly-completed entries, sends WhatsApp push | surface |
| **WhatsApp reply handler (KBL-C §4)** | parses Director reply, writes `feedback_ledger`, writes `gold_promote_queue` if promote | capture |
| **Gold drain (KBL-A)** | reads `gold_promote_queue`, flips frontmatter, commits to vault | materialize |

---

## 2. 4-handler architecture

### 2.1 Handler 1 — Ayoniso Alert Dispatcher

**Purpose:** When a pipeline-emitted Silver entry meets ayoniso criteria (heuristic: `triage_score ≥ ALERT_THRESHOLD` OR `vedana='threat'` OR `primary_matter ∈ hot.md ACTIVE`), push a WhatsApp message to Director summarizing the entry.

**Mechanism:** cron-triggered poll of `signal_queue WHERE state='done' AND ayoniso_dispatched_at IS NULL` every 2min. For each hit, compose summary + send via WAHA outbound, mark `ayoniso_dispatched_at=now()`.

**Alert shape:**
```
🔔 <primary_matter> <vedana emoji>
<triage_summary one-sentence>
📎 wiki/<matter>/<file>.md
Reply: promote | correct | ignore | dismiss
```

**Rate limiting:** max N alerts per hour (env `KBL_ALERT_RATE_LIMIT=6`), queue the rest for next tick.

**Idempotency:** `ayoniso_dispatched_at` set atomically with the WAHA send. If WAHA fails, don't mark — next tick retries.

### 2.2 Handler 2 — WhatsApp Reply Handler (Gold Promotion)

**Purpose:** Parse Director replies to ayoniso alerts. Map reply to action, write `feedback_ledger` atomically, enqueue vault mutation if needed.

**Command grammar (deterministic parser, no LLM):**
- `promote` / `p` / `✅` — Silver → Gold. Writes `feedback_ledger(action_type='promote')` + `gold_promote_queue` row. Mac Mini daemon picks up, flips `voice: silver` → `voice: gold`, `author: pipeline` → `author: director`, commits.
- `correct <field>=<value>` / `c <field>=<value>` — edit a single frontmatter field (e.g., `correct primary_matter=cupial`). Writes `feedback_ledger(action_type='correct', payload=<field/value>)`. Mac Mini daemon applies.
- `ignore` / `i` — mark entry as seen but no action. Writes `feedback_ledger(action_type='ignore')`. No vault mutation.
- `dismiss` / `d` / `❌` — same as ignore but marks "this shouldn't have been alerted." Writes `feedback_ledger(action_type='ayoniso_dismiss')`. Informs future alert thresholds.
- `respond <free text>` — Director annotates. Writes `feedback_ledger(action_type='ayoniso_respond', director_note=<text>)`. Vault mutation: append Director-note block to wiki entry.

**Reply-to-signal correlation:** WhatsApp reply includes a quote-reference to the original alert; the handler extracts the `signal_id` from the alert message. If quote-reference missing, the handler responds "couldn't match your reply to an alert — please quote the original message."

**Atomicity (CHANDA Inv 2):** the feedback_ledger write happens in the SAME transaction as any vault-mutation enqueue (`gold_promote_queue` row insert). If PG is unreachable, the WhatsApp reply is NOT acknowledged to Director — WAHA returns a "retry later" message. Directors' actions never silently succeed without ledger trail.

### 2.3 Handler 3 — Vault-Edit Ingestion (fallback capture)

**Purpose:** Director sometimes edits wiki frontmatter directly on Mac Mini Obsidian (bypasses WhatsApp). A file-watcher detects these edits, classifies as Director actions, writes `feedback_ledger` after-the-fact.

**Mechanism:** `launchd` plist on Mac Mini watches `baker-vault/wiki/*.md` for git-commit events where `author.name='Dimitry Vallen'` (his git identity). For each committed file, diff frontmatter against previous version, classify:
- `voice: silver → voice: gold` AND `author: pipeline → author: director` = promote
- `primary_matter` field changed = correct
- Body append that adds `@ director:` prefix = respond
- `deleted` or moved to `wiki/_archive/` = ignore

Write `feedback_ledger` row via local → Render sync.

**Why this matters:** Director's vault edits are the ground truth. Even if WhatsApp is down for a week, Director's Obsidian edits still flow into the ledger. CHANDA Inv 2 holds.

### 2.4 Handler 4 — Dashboard Data Feeder

**Purpose:** Feeds the existing CEO cockpit (`baker-master.onrender.com`) with KBL-B pipeline metrics.

**Surfaces:**
- Per-matter signal volume (last 24h / 7d / 30d)
- Per-matter Gold count + Silver-pending count
- Cost-per-day bar chart (from `kbl_cost_ledger`)
- Alert queue length + dispatched-but-unanswered count
- Ayoniso miss-rate (alerted but never-responded-or-dismissed)

**Read-only layer** — no mutations. Pure aggregation queries via FastAPI endpoints.

---

## 3. Schema touches

### 3.1 Extend `signal_queue` (Ayoniso tracking)

```sql
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS ayoniso_dispatched_at TIMESTAMPTZ;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS ayoniso_responded_at TIMESTAMPTZ;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS ayoniso_response_action TEXT;
CREATE INDEX IF NOT EXISTS idx_signal_queue_ayoniso_pending
  ON signal_queue (state) WHERE state='done' AND ayoniso_dispatched_at IS NULL;
```

### 3.2 New table — `gold_promote_queue` (if not existing from KBL-A)

Per D2 — KBL-A specified the table; verify exists. If not:

```sql
CREATE TABLE IF NOT EXISTS gold_promote_queue (
  id              BIGSERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  signal_id       BIGINT NOT NULL,
  target_path     TEXT NOT NULL,
  action_type     TEXT NOT NULL,   -- 'promote' | 'correct' | 'respond'
  payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
  drained_at      TIMESTAMPTZ,
  drained_commit_sha TEXT
);
CREATE INDEX IF NOT EXISTS idx_gold_promote_queue_pending
  ON gold_promote_queue (created_at) WHERE drained_at IS NULL;
```

### 3.3 `wiki_staging` remains from KBL-A

KBL-C writes go through `wiki_staging` per CHANDA Inv 9. No new schema.

---

## 4-N. Remaining sections (next AI Head push after §1-3 ratification)

- **§4 Per-handler I/O contracts** — similar shape to KBL-B §4: reads / writes / ledger / log / invariants per handler
- **§5 WhatsApp command grammar formal spec** — full parser table, ambiguity handling, error responses
- **§6 Ayoniso threshold design** — how `triage_score ≥ ALERT_THRESHOLD` interacts with hot.md ACTIVE + Phase 1 matter scope
- **§7 Error matrix** — handler × failure × recovery (same shape as KBL-B §7)
- **§8 Testing plan** — per-handler unit tests, end-to-end WhatsApp reply simulation, ledger atomicity stress tests
- **§9 Rollout sequence** — Phase 1 deploy post-KBL-B, shadow-alert mode (send alert but don't commit), flip to production
- **§10 Acceptance criteria** — Director-response latency p95, zero-silent-promotion invariant, cost budget for WAHA

---

## Asks of Director

1. **Ratify §1.2 scope** — KBL-C is interface + Gold promotion + feedback capture. WhatsApp primary + vault-edit fallback. No LLM calls (deterministic parser). One-word confirm to lock.
2. **Ratify §2 four-handler architecture** — Ayoniso dispatcher + WhatsApp reply handler + Vault-edit watcher + Dashboard feeder. One-word confirm.
3. **Ratify §2.2 command grammar** — `promote` / `correct <field>=<value>` / `ignore` / `dismiss` / `respond <text>`. Any missing verb?
4. **Ayoniso threshold default** — what triage_score triggers an alert by default? Suggested: `≥ 70` OR `vedana='threat'` OR `primary_matter ∈ hot.md ACTIVE`. Director feedback shapes §6.

These ratifications unblock per-handler detail (§4-10).

---

*Prepared 2026-04-18 by AI Head as skeleton. Awaits Director ratification before per-handler detail.*
